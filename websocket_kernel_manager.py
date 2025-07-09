#!/usr/bin/env python3
"""
WebSocket 기반 JupyterHub 커널 매니저
기존 MCP 서버에 최소한의 변경으로 통합 가능한 모듈
"""

import asyncio
import websockets
import json
import time
import uuid
import threading
import queue
import requests
from typing import Dict, Any, List, Optional
import logging

class WebSocketKernelManager:
    """
    WebSocket 기반 JupyterHub 커널 매니저
    기존 MCP 서버의 _safe_execute 를 대체할 수 있는 인터페이스 제공
    """
    
    def __init__(self, 
                 hub_url: str,
                 username: str, 
                 api_token: str = None,
                 logger: Optional[logging.Logger] = None):
        
        self.hub_url = hub_url.rstrip('/')
        self.username = username
        self.api_token = api_token
        self.logger = logger or logging.getLogger(__name__)
        
        # 연결 상태
        self._connected = False
        self._kernel_id = None
        self._ws = None
        self._ws_url = None
        
        # WebSocket 메시지 처리
        self._message_queue = queue.Queue()
        self._ws_thread = None
        self._running = False
        self._pending_executions = {}
        
        # 사용자 URL
        self.user_url = f"{self.hub_url.replace('/hub', '')}/user/{self.username}"
        
        # 초기화 락 (연결 중복 방지)
        self._init_lock = threading.Lock()
    
    async def ensure_connection(self):
        """연결 확인 및 초기화 (필요시에만)"""
        if self._connected and self._ws and not self._ws.closed:
            return True
            
        with self._init_lock:
            if self._connected and self._ws and not self._ws.closed:
                return True
                
            try:
                await self._initialize_connection()
                return True
            except Exception as e:
                self.logger.error(f"커널 연결 실패: {e}")
                return False
    
    async def _initialize_connection(self):
        """커널 연결 초기화"""
        try:
            # 1. 커널 확인/생성
            await self._ensure_kernel()
            
            # 2. WebSocket 연결
            await self._connect_websocket()
            
            # 3. 커널 준비 대기
            await self._wait_for_kernel_ready()
            
            self._connected = True
            self.logger.info(f"WebSocket 커널 연결 완료: {self._kernel_id}")
            
        except Exception as e:
            await self._cleanup()
            raise Exception(f"커널 초기화 실패: {e}")
    
    # 커널이 존재할 때 유지될 필요가 있을지는 확인해봐야함. 요청때마다 새로운 커널이 필요할수도 있고
    # 다른 파일에서 같은 커널이 사용되면 변수가 공유되는데, 이게 맞는건지도 모르겠음
    async def _ensure_kernel(self):
        """커널 확인 또는 생성"""
        try:
            headers = {}
            if self.api_token:
                headers["Authorization"] = f"token {self.api_token}"
            
            # 기존 커널 확인
            response = requests.get(f"{self.user_url}/api/kernels", headers=headers, timeout=10)
            
            if response.status_code == 200:
                kernels = response.json()
                for kernel in kernels:
                    if kernel.get('execution_state') == 'idle':
                        self._kernel_id = kernel['id']
                        self.logger.info(f"기존 커널 사용: {self._kernel_id}")
                        return
            
            # 새 커널 생성
            response = requests.post(
                f"{self.user_url}/api/kernels",
                json={"name": "python3"},
                headers=headers,
                timeout=10
            )
            
            if response.status_code in [200, 201]:
                kernel_info = response.json()
                self._kernel_id = kernel_info['id']
                self.logger.info(f"새 커널 생성: {self._kernel_id}")
            else:
                raise Exception(f"커널 생성 실패: {response.status_code} - {response.text}")
                
        except Exception as e:
            raise Exception(f"커널 설정 실패: {e}")
    
    async def _connect_websocket(self):
        """WebSocket 연결"""
        try:
            # WebSocket URL 생성
            if self.user_url.startswith('https://'):
                ws_protocol = 'wss://'
                base_url = self.user_url[8:]
            else:
                ws_protocol = 'ws://'
                base_url = self.user_url[7:]
            
            self._ws_url = f"{ws_protocol}{base_url}/api/kernels/{self._kernel_id}/channels"
            
            # 헤더 설정
            headers = {}
            if self.api_token:
                headers["Authorization"] = f"token {self.api_token}"
            
            # WebSocket 연결
            self._ws = await websockets.connect(
                self._ws_url,
                additional_headers=headers if headers else None,
                ping_interval=30,
                ping_timeout=10
            )
            
            # 메시지 리스너 시작
            self._running = True
            self._ws_thread = threading.Thread(target=self._message_listener_thread)
            self._ws_thread.daemon = True
            self._ws_thread.start()
            
            self.logger.debug(f"WebSocket 연결: {self._ws_url}")
            
        except Exception as e:
            raise Exception(f"WebSocket 연결 실패: {e}")
    
    def _message_listener_thread(self):
        """메시지 리스너 스레드"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._message_listener())
        except Exception as e:
            self.logger.error(f"메시지 리스너 오류: {e}")
        finally:
            self.logger.debug("메시지 리스너 종료")
    
    async def _message_listener(self):
        """메시지 수신 처리"""
        try:
            while self._running and self._ws:
                try:
                    message = await asyncio.wait_for(self._ws.recv(), timeout=1.0)
                    data = json.loads(message)
                    self._message_queue.put(data)
                    await self._handle_execution_response(data)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    self.logger.warning("WebSocket 연결 종료")
                    break
        except Exception as e:
            self.logger.error(f"메시지 리스너 내부 오류: {e}")
    
    async def _handle_execution_response(self, data: dict):
        """실행 응답 처리"""
        try:
            msg_type = data.get('header', {}).get('msg_type', '')
            parent_msg_id = data.get('parent_header', {}).get('msg_id', '')
            
            if parent_msg_id in self._pending_executions:
                future = self._pending_executions[parent_msg_id]
                
                if msg_type == 'status' and data.get('content', {}).get('execution_state') == 'idle':
                    if not future.done():
                        future.set_result(True)
        except Exception as e:
            self.logger.error(f"실행 응답 처리 오류: {e}")
    
    async def _wait_for_kernel_ready(self):
        """커널 준비 대기"""
        try:
            msg_id = self._generate_msg_id()
            
            message = {
                'header': {
                    'msg_id': msg_id,
                    'username': self.username,
                    'session': self._generate_session_id(),
                    'msg_type': 'kernel_info_request',
                    'version': '5.0'
                },
                'parent_header': {},
                'metadata': {},
                'content': {},
                'channel': 'shell',
                'buffers': []
            }
            
            await self._ws.send(json.dumps(message))
            
            # 응답 대기
            timeout = 15
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    response = self._message_queue.get(timeout=1)
                    if response.get('header', {}).get('msg_type') == 'kernel_info_reply':
                        return
                except queue.Empty:
                    continue
            
            raise Exception("커널 준비 타임아웃")
            
        except Exception as e:
            raise Exception(f"커널 준비 확인 실패: {e}")
    
    async def execute_code_websocket(self, code: str, timeout: int = 60) -> Dict[str, Any]:
        """
        WebSocket을 통한 코드 실행
        기존 _safe_execute와 호환되는 인터페이스
        """
        try:
            # 연결 확인
            if not await self.ensure_connection():
                return {
                    "success": False,
                    "error": "WebSocket 연결 실패",
                    "result": None,
                    "output": "",
                    "note": "WebSocket connection failed"
                }
            
            msg_id = self._generate_msg_id()
            
            # execute_request 메시지
            message = {
                'header': {
                    'msg_id': msg_id,
                    'username': self.username,
                    'session': self._generate_session_id(),
                    'msg_type': 'execute_request',
                    'version': '5.0'
                },
                'parent_header': {},
                'metadata': {},
                'content': {
                    'code': code,
                    'silent': False,
                    'store_history': True,
                    'user_expressions': {},
                    'allow_stdin': False,
                    'stop_on_error': True
                },
                'channel': 'shell',
                'buffers': []
            }
            
            # 실행 추적
            future = asyncio.Future()
            self._pending_executions[msg_id] = future
            
            # 메시지 전송
            await self._ws.send(json.dumps(message))
            
            # 실행 완료 대기
            try:
                await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                return {
                    "success": False,
                    "error": f"실행 타임아웃 ({timeout}초)",
                    "result": None,
                    "output": "",
                    "note": "Execution timed out"
                }
            finally:
                if msg_id in self._pending_executions:
                    del self._pending_executions[msg_id]
            
            # 결과 수집
            result_data = self._collect_execution_results(msg_id)
            
            return {
                "success": True,
                "result": result_data.get("result"),
                "output": result_data.get("output", ""),
                "note": "Executed via WebSocket on JupyterHub kernel"
            }
            
        except Exception as e:
            self.logger.error(f"코드 실행 실패: {e}")
            return {
                "success": False,
                "error": str(e),
                "result": None,
                "output": "",
                "note": "WebSocket execution failed"
            }
    
    def _collect_execution_results(self, msg_id: str) -> Dict[str, Any]:
        """실행 결과 수집"""
        outputs = []
        result = None
        
        # 잠시 대기 후 메시지 수집
        time.sleep(0.3)
        
        collected_messages = []
        while True:
            try:
                message = self._message_queue.get(block=False)
                collected_messages.append(message)
            except queue.Empty:
                break
        
        # 해당 실행의 메시지만 필터링
        for message in collected_messages:
            parent_msg_id = message.get('parent_header', {}).get('msg_id', '')
            if parent_msg_id == msg_id:
                msg_type = message.get('header', {}).get('msg_type', '')
                content = message.get('content', {})
                
                if msg_type == 'stream':
                    outputs.append(content.get('text', ''))
                elif msg_type == 'execute_result':
                    data = content.get('data', {})
                    if 'text/plain' in data:
                        result = data['text/plain']
                elif msg_type == 'error':
                    error_text = '\n'.join(content.get('traceback', []))
                    outputs.append(f"ERROR: {error_text}")
        
        return {
            "result": result,
            "output": ''.join(outputs)
        }
    
    async def get_kernel_globals_websocket(self) -> Dict[str, Any]:
        """
        WebSocket을 통한 전역 변수 조회
        기존 get_kernel_globals와 호환되는 인터페이스
        """
        globals_code = '''
import json
import inspect
import builtins
from types import ModuleType

result = {}
builtin_names = dir(builtins)
jupyter_vars = ['In', 'Out', 'exit', 'quit', 'get_ipython', 'display', '_', '_oh', '_dh', '_sh']

for k, v in globals().items():
    if (k.startswith('_') or k in builtin_names or 
        isinstance(v, ModuleType) or k in jupyter_vars):
        continue
        
    try:
        if inspect.isfunction(v):
            doc = v.__doc__
            doc_summary = doc.split('\\n')[0].strip() if doc else ""
            result[k] = [type(v).__name__, doc_summary]
        elif isinstance(v, (int, float, bool, str, type(None))):
            result[k] = [type(v).__name__, v]
        elif hasattr(v, '__len__'):
            result[k] = [type(v).__name__, f"length: {len(v)}"]
        else:
            result[k] = [type(v).__name__, ""]
    except:
        try:
            result[k] = [type(v).__name__, ""]
        except:
            result[k] = ["unknown", ""]

print(json.dumps(result))
'''
        
        try:
            execution_result = await self.execute_code_websocket(globals_code)
            
            if execution_result["success"]:
                output = execution_result.get("output", "")
                try:
                    # JSON 파싱 시도
                    start = output.find('{')
                    end = output.rfind('}') + 1
                    if start >= 0 and end > start:
                        json_str = output[start:end]
                        return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
            
            return {}
            
        except Exception as e:
            self.logger.error(f"전역 변수 조회 실패: {e}")
            return {}
    
    async def _cleanup(self):
        """리소스 정리"""
        try:
            self._running = False
            
            if self._ws:
                await self._ws.close()
                self._ws = None
            
            if self._ws_thread and self._ws_thread.is_alive():
                self._ws_thread.join(timeout=2)
            
            self._connected = False
            
        except Exception as e:
            self.logger.error(f"정리 중 오류: {e}")
    
    def _generate_msg_id(self) -> str:
        """메시지 ID 생성"""
        return f"msg_{uuid.uuid4().hex[:8]}_{int(time.time())}"
    
    def _generate_session_id(self) -> str:
        """세션 ID 생성"""
        return f"session_{uuid.uuid4().hex[:8]}"


# 기존 MCP 서버와의 통합을 위한 어댑터 클래스
class WebSocketExecutionAdapter:
    """
    기존 MCP 서버의 _safe_execute를 WebSocket 실행으로 대체하는 어댑터
    """
    
    def __init__(self, ws_manager: WebSocketKernelManager):
        self.ws_manager = ws_manager
    
    async def safe_execute_websocket(self, code: str) -> Dict[str, Any]:
        """
        기존 _safe_execute와 완전히 호환되는 WebSocket 실행
        """
        return await self.ws_manager.execute_code_websocket(code)
    
    async def get_kernel_globals_websocket(self) -> Dict[str, Any]:
        """
        기존 get_kernel_globals와 호환되는 WebSocket 버전
        """
        return await self.ws_manager.get_kernel_globals_websocket()


# 사용 예시 및 테스트
async def test_websocket_manager():
    """WebSocket 매니저 테스트"""
    
    # 설정
    HUB_URL = "http://13.124.0.18:8000"
    USERNAME = "user4"
    API_TOKEN = "test-token"  # 토큰 설정
    
    # 로깅 설정
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    ws_manager = None
    
    try:
        print("🚀 WebSocket 매니저 테스트")
        
        # 매니저 생성
        ws_manager = WebSocketKernelManager(HUB_URL, USERNAME, API_TOKEN, logger)
        
        # 어댑터 생성
        adapter = WebSocketExecutionAdapter(ws_manager)
        
        # 1. 간단한 실행
        print("\n📝 1. 간단한 실행 테스트")
        result = await adapter.safe_execute_websocket("print('Hello WebSocket!')")
        print(f"   결과: {result}")
        
        # 2. 변수 설정
        print("\n📝 2. 변수 설정")
        result = await adapter.safe_execute_websocket("x = 42\ny = 'test'")
        print(f"   결과: {result}")
        
        # 3. 변수 사용
        print("\n📝 3. 변수 사용")
        result = await adapter.safe_execute_websocket("print(f'x={x}, y={y}')")
        print(f"   결과: {result}")
        
        # 4. 전역 변수 조회
        print("\n📝 4. 전역 변수 조회")
        globals_data = await adapter.get_kernel_globals_websocket()
        print(f"   전역 변수: {len(globals_data)}개")
        for k, v in list(globals_data.items())[:3]:
            print(f"   {k}: {v}")
        
        print("\n✅ 모든 테스트 완료!")
        
    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        
    finally:
        if ws_manager:
            await ws_manager._cleanup()


if __name__ == "__main__":
    asyncio.run(test_websocket_manager())