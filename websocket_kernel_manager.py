#!/usr/bin/env python3
"""
WebSocket 기반 JupyterHub 커널 매니저 (개선 버전)
기존 MCP 서버에 최소한의 변경으로 통합 가능한 모듈
"""

import asyncio
import os
import websockets
import json
import time
import uuid
import threading
import queue
import requests
from typing import Dict, Any, Optional
import logging
from dotenv import load_dotenv
load_dotenv()

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
        self._session_id = None
        self._kernel_id = None
        self._ws = None
        self._ws_url = None
        
        # WebSocket 메시지 처리 (직접 처리 방식)
        self._running = False
        
        # 사용자 URL
        self.user_url = f"{self.hub_url.replace('/hub', '')}/user/{self.username}"
        
        # 초기화 락 (연결 중복 방지)
        self._init_lock = threading.Lock()
    
    async def ensure_connection(self):
        """연결 확인 및 초기화"""
        # 이미 연결되어 있으면 바로 반환
        if self._connected and self._ws and self._session_id:
            return True
            
        with self._init_lock:
            # 락 획득 후 다시 확인
            if self._connected and self._ws and self._session_id:
                return True
                
            try:
                # 1. 세션, 커널 확인/생성
                await self._ensure_session_and_kernel()
                
                # 2. WebSocket 연결
                await self._connect_websocket()
                
                # 3. 연결 상태 설정
                self._connected = True
                self.logger.info(f"WebSocket 커널 연결 완료: {self._kernel_id}")
                return True
                
            except Exception as e:
                await self._cleanup()
                self.logger.error(f"커널 연결 실패: {e}")
                return False
    
    # async def _ensure_kernel(self):
    #     """커널 확인 또는 생성"""
    #     try:
    #         headers = {}
    #         if self.api_token:
    #             headers["Authorization"] = f"token {self.api_token}"
            
    #         # 기존 커널 확인
    #         response = requests.get(f"{self.user_url}/api/kernels", headers=headers, timeout=10)
            
    #         if response.status_code == 200:
    #             kernels = response.json()
    #             for kernel in kernels:
    #                 if kernel.get('execution_state') == 'idle':
    #                     self._kernel_id = kernel['id']
    #                     self.logger.info(f"기존 커널 사용: {self._kernel_id}")
    #                     return
            
    #         # 새 커널 생성
    #         response = requests.post(
    #             f"{self.user_url}/api/kernels",
    #             json={"name": "python3"},
    #             headers=headers,
    #             timeout=10
    #         )
            
    #         if response.status_code in [200, 201]:
    #             kernel_info = response.json()
    #             self._kernel_id = kernel_info['id']
    #             self.logger.info(f"새 커널 생성: {self._kernel_id}")
    #         else:
    #             raise Exception(f"커널 생성 실패: {response.status_code} - {response.text}")
                
    #     except Exception as e:
    #         raise Exception(f"커널 설정 실패: {e}")

    async def _ensure_session_and_kernel(self):
        """세션 기반 커널 확인 또는 생성"""
        try:
            headers = {}
            if self.api_token:
                headers["Authorization"] = f"token {self.api_token}"
            
            # 노트북 파일 경로 (MCP 서버의 DEFAULT_NOTEBOOK 사용)
            notebook_path = os.getenv("DEFAULT_NOTEBOOK", "session_notebook.ipynb")
            
            # 1. 기존 세션 확인 (노트북 파일 기준)
            response = requests.get(f"{self.user_url}/api/sessions", headers=headers, timeout=10)
            
            if response.status_code == 200:
                sessions = response.json()
                for session in sessions:
                    # 같은 노트북 파일의 세션이 있으면 재사용
                    if session.get('path') == notebook_path or session.get('name') == notebook_path:
                        self._session_id = session['id']
                        self._kernel_id = session['kernel']['id']
                        self.logger.info(f"기존 세션 재사용: {self._session_id} (커널: {self._kernel_id})")
                        return
            
            # 2. 기존 세션이 없으면 새 세션 생성
            self.logger.info(f"새 세션 생성: {notebook_path}")
            
            session_data = {
                "path": notebook_path,
                "name": "session_notebook.ipynb", 
                "type": "notebook",
                "kernel": {
                    "name": "python3"
                }
            }
            
            response = requests.post(
                f"{self.user_url}/api/sessions",
                json=session_data,
                headers=headers,
                timeout=10
            )
            
            if response.status_code in [200, 201]:
                session_info = response.json()
                self._session_id = session_info['id']
                self._kernel_id = session_info['kernel']['id']
                self.logger.info(f"새 세션 생성 완료: {self._session_id} (커널: {self._kernel_id})")
            else:
                raise Exception(f"세션 생성 실패: {response.status_code} - {response.text}")
                
        except Exception as e:
            raise Exception(f"세션 설정 실패: {e}")    
    
    async def _connect_websocket(self):
        """WebSocket 연결 (스레드 없는 버전)"""
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
            
            # 스레드 없이 작동
            self._running = True
            
            self.logger.debug(f"WebSocket 연결: {self._ws_url}")
            
        except Exception as e:
            raise Exception(f"WebSocket 연결 실패: {e}")
    
    async def execute_code_websocket(self, code: str, timeout: int = 60) -> Dict[str, Any]:
        """
        WebSocket을 통한 코드 실행 (직접 메시지 처리)
        """
        try:
            # 연결 확인
            if not self._connected or not self._ws:
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
            
            # 메시지 전송
            await self._ws.send(json.dumps(message))
            
            # 응답 직접 수집
            outputs = []
            result = None
            execution_finished = False
            start_time = time.time()
            
            while time.time() - start_time < timeout and not execution_finished:
                try:
                    response_msg = await asyncio.wait_for(self._ws.recv(), timeout=2.0)
                    data = json.loads(response_msg)
                    
                    # 해당 실행의 메시지인지 확인
                    parent_msg_id = data.get('parent_header', {}).get('msg_id', '')
                    if parent_msg_id != msg_id:
                        continue
                    
                    msg_type = data.get('header', {}).get('msg_type', '')
                    content = data.get('content', {})
                    
                    # 출력 처리
                    if msg_type == 'stream':
                        outputs.append(content.get('text', ''))
                    elif msg_type == 'execute_result':
                        data_content = content.get('data', {})
                        if 'text/plain' in data_content:
                            result = data_content['text/plain']
                    elif msg_type == 'error':
                        error_text = '\n'.join(content.get('traceback', []))
                        outputs.append(f"ERROR: {error_text}")
                    elif msg_type == 'status' and content.get('execution_state') == 'idle':
                        execution_finished = True
                        break
                        
                except asyncio.TimeoutError:
                    continue
            
            if not execution_finished:
                return {
                    "success": False,
                    "error": f"실행 타임아웃 ({timeout}초)",
                    "result": None,
                    "output": "",
                    "note": "Execution timed out"
                }
            
            return {
                "success": True,
                "result": result,
                "output": ''.join(outputs),
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
        
    async def restart_session(self) -> Dict[str, Any]:
        """현재 세션을 완전히 재시작 (새로운 세션 + 커널 생성)"""
        try:
            old_session_id = self._session_id
            old_kernel_id = self._kernel_id
            
            # 1. 기존 세션 종료
            if self._session_id:
                await self._terminate_current_session()
            
            # 2. WebSocket 연결 정리
            await self._cleanup()
            
            # 3. 새로운 세션 시작
            success = await self.ensure_connection()
            
            if success:
                self.logger.info(f"세션 재시작 완료: {old_session_id} → {self._session_id}")
                return {
                    "success": True,
                    "message": "세션 재시작 완료",
                    "old_session_id": old_session_id,
                    "new_session_id": self._session_id,
                    "old_kernel_id": old_kernel_id,
                    "new_kernel_id": self._kernel_id
                }
            else:
                return {
                    "success": False,
                    "error": "새로운 세션 생성 실패"
                }
                
        except Exception as e:
            self.logger.error(f"세션 재시작 오류: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _terminate_current_session(self):
        """현재 세션 종료"""
        try:
            if not self._session_id:
                return
                
            headers = {}
            if self.api_token:
                headers["Authorization"] = f"token {self.api_token}"
            
            response = requests.delete(
                f"{self.user_url}/api/sessions/{self._session_id}",
                headers=headers,
                timeout=10
            )
            
            if response.status_code in [200, 204]:
                self.logger.info(f"세션 종료 완료: {self._session_id}")
            else:
                self.logger.warning(f"세션 종료 실패: {response.status_code}")
                
        except Exception as e:
            self.logger.error(f"세션 종료 오류: {e}")
    
    def get_session_info(self) -> Dict[str, Any]:
        """현재 세션 정보 반환"""
        return {
            "session_id": self._session_id,
            "kernel_id": self._kernel_id,
            "connected": self._connected,
            "ws_url": self._ws_url
        }        
    
    async def _cleanup(self):
        """리소스 정리"""
        try:
            self._running = False
            
            if self._ws:
                await self._ws.close()
                self._ws = None
            
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


# 테스트 함수
async def test_websocket_manager():
    """WebSocket 매니저 테스트"""
    
    HUB_URL = os.getenv("JUPYTERHUB_URL", "http://localhost:8000")
    USERNAME = os.getenv("JUPYTERHUB_USERNAME", "your_username")
    API_TOKEN = os.getenv("JUPYTERHUB_API_TOKEN", "your_api_token_here")
    
    # 로깅 설정
    logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
    logger = logging.getLogger(__name__)
    
    ws_manager = None
    
    try:
        print("🚀 WebSocket 매니저 테스트")
        print("=" * 50)
        
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
        if 'x' in globals_data:
            print(f"   ✅ 변수 x 발견: {globals_data['x']}")
        if 'y' in globals_data:
            print(f"   ✅ 변수 y 발견: {globals_data['y']}")
        
        print("\n🎉 모든 테스트 완료!")
        
    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if ws_manager:
            await ws_manager._cleanup()
            print("\n🧹 정리 완료")


if __name__ == "__main__":
    asyncio.run(test_websocket_manager())