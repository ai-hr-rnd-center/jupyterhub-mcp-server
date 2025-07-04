from fastmcp import FastMCP
import asyncio
import time
import logging
import os
import json
import queue
import threading
import urllib.parse
import websocket
import ssl
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
import httpx

load_dotenv()

# 로깅 설정
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)

SERVER_NAME = os.getenv("SERVER_NAME", "JupyterHub MCP Server")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# FastMCP 서버 생성
mcp = FastMCP(SERVER_NAME)

# JupyterHub 설정
JUPYTERHUB_CONFIG = {
    "hub_url": os.getenv("JUPYTERHUB_URL", "http://localhost:8000"),
    "api_token": os.getenv("JUPYTERHUB_API_TOKEN", "your_api_token_here"),
    "username": os.getenv("JUPYTERHUB_USERNAME", "your_username")
}

class JupyterHubClient:
    """WebSocket 기반 실제 커널 통신을 지원하는 JupyterHub 클라이언트"""
    
    def __init__(self, hub_url: str, api_token: str, username: str):
        self.hub_url = hub_url.rstrip('/')
        self.api_token = api_token
        self.username = username
        self.session = None
        
        # WebSocket 관련 (jupyterhub_memory.py에서 가져온 핵심 부분)
        self.ws = None
        self.ws_queue = queue.Queue()
        self.ws_listener = None
        self.ws_stop_event = threading.Event()
        self.kernel_lock = threading.Lock()
        
        # 커널 정보
        self.kernel_id = None
        self.kernel_url = None
        self.ws_url = None
        self.execution_count = 0
        
        # 인증 헤더
        self.headers = {
            'Authorization': f'token {api_token}',
            'Content-Type': 'application/json',
            'X-JupyterHub-User': username,
            'X-JupyterHub-API-Token': api_token
        }
        
    async def get_session(self):
        if not self.session:
            self.session = httpx.AsyncClient(
                headers=self.headers,
                timeout=30.0
            )
        return self.session
    
    async def get_user_server_url(self) -> str:
        """사용자 서버 URL 가져오기"""
        try:
            session = await self.get_session()
            
            # 사용자 정보 확인
            response = await session.get(f"{self.hub_url}/hub/api/users/{self.username}")
            response.raise_for_status()
            user_info = response.json()
            
            if user_info.get("servers", {}).get(""):
                server_url = f"{self.hub_url}/user/{self.username}"
                return server_url
            else:
                await self.start_user_server()
                return f"{self.hub_url}/user/{self.username}"
                
        except Exception as e:
            logger.error(f"Error getting user server URL: {str(e)}")
            return f"{self.hub_url}/user/{self.username}"
    
    async def start_user_server(self) -> Dict[str, Any]:
        """사용자 서버 시작"""
        try:
            session = await self.get_session()
            response = await session.post(f"{self.hub_url}/hub/api/users/{self.username}/server")
            
            if response.status_code in [201, 202]:
                await asyncio.sleep(5)
                return {"success": True, "message": "User server started"}
            else:
                return {"success": False, "error": f"Failed to start server: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error starting user server: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def get_or_create_kernel(self) -> Optional[str]:
        """커널 가져오기 또는 생성 (jupyterhub_memory.py 방식)"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            # 기존 커널 확인
            response = await session.get(f"{server_url}/api/kernels")
            if response.status_code == 200:
                kernels = response.json()
                if kernels:
                    self.kernel_id = kernels[0]["id"]
                    self.kernel_url = f"{server_url}/api/kernels/{self.kernel_id}"
                    logger.info(f"Using existing kernel: {self.kernel_id}")
                    return self.kernel_id
            
            # 새 커널 생성
            kernel_spec = {"name": "python3"}
            response = await session.post(f"{server_url}/api/kernels", json=kernel_spec)
            
            if response.status_code in [200, 201]:
                kernel_info = response.json()
                self.kernel_id = kernel_info["id"]
                self.kernel_url = f"{server_url}/api/kernels/{self.kernel_id}"
                
                # WebSocket URL 설정
                ws_url = f"{server_url}/api/kernels/{self.kernel_id}/channels"
                parsed_url = urllib.parse.urlparse(ws_url)
                ws_protocol = "wss" if parsed_url.scheme == "https" else "ws"
                self.ws_url = f"{ws_protocol}://{parsed_url.netloc}{parsed_url.path}"
                
                logger.info(f"Created new kernel: {self.kernel_id}")
                
                # WebSocket 연결
                if await self._connect_websocket():
                    await asyncio.sleep(3)  # 커널 준비 대기
                    return self.kernel_id
                else:
                    return None
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting/creating kernel: {str(e)}")
            return None
    
    async def _connect_websocket(self) -> bool:
        """WebSocket 연결 설정 (jupyterhub_memory.py 기반)"""
        try:
            logger.info(f"Connecting to WebSocket: {self.ws_url}")
            
            # 인증 헤더 설정
            headers = [
                f"Authorization: token {self.api_token}",
                f"X-JupyterHub-User: {self.username}",
                f"X-JupyterHub-API-Token: {self.api_token}"
            ]
            
            # 쿠키 설정
            cookies = f"jupyterhub-user={self.username}; jupyterhub-hub-login={self.api_token}"
            
            # WebSocket 연결 (동기 방식이므로 스레드에서 실행)
            def connect_ws():
                try:
                    self.ws = websocket.create_connection(
                        self.ws_url,
                        header=headers,
                        cookie=cookies,
                        timeout=30
                    )
                    return True
                except Exception as e:
                    logger.error(f"WebSocket connection failed: {e}")
                    return False
            
            # 비동기에서 동기 함수 실행
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, connect_ws)
            
            if success:
                # 메시지 큐 초기화
                self.ws_queue = queue.Queue()
                self.ws_stop_event.clear()
                
                # 리스너 스레드 시작
                self.ws_listener = threading.Thread(target=self._ws_listener_thread)
                self.ws_listener.daemon = True
                self.ws_listener.start()
                
                logger.info("WebSocket connection established")
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect WebSocket: {str(e)}")
            return False
    
    def _ws_listener_thread(self):
        """WebSocket 메시지 리스너 (jupyterhub_memory.py에서 가져옴)"""
        try:
            while not self.ws_stop_event.is_set():
                try:
                    msg = self.ws.recv()
                    if msg:
                        self.ws_queue.put(json.loads(msg))
                except websocket.WebSocketTimeoutException:
                    continue
                except websocket.WebSocketConnectionClosedException:
                    break
        except Exception as e:
            logger.error(f"WebSocket listener error: {str(e)}")
    
    def _send_execute_request(self, code: str) -> str:
        """코드 실행 요청 전송 (jupyterhub_memory.py 방식)"""
        msg_id = f"exec_{time.time()}"
        
        header = {
            'msg_id': msg_id,
            'username': self.username,
            'session': f"session_{time.time()}",
            'msg_type': 'execute_request',
            'version': '5.0'
        }
        
        content = {
            'code': code,
            'silent': False,
            'store_history': True,
            'user_expressions': {},
            'allow_stdin': False,
            'stop_on_error': True
        }
        
        msg = {
            'header': header,
            'parent_header': {},
            'metadata': {},
            'content': content,
            'channel': 'shell',
            'buffers': []
        }
        
        self.ws.send(json.dumps(msg))
        return msg_id
    
    def _collect_execution_results(self, msg_id: str, timeout: int = 30) -> List[Dict]:
        """실행 결과 수집 (jupyterhub_memory.py 방식)"""
        outputs = []
        start_time = time.time()
        is_idle = False
        
        while not is_idle and time.time() - start_time < timeout:
            try:
                msg = self.ws_queue.get(timeout=1)
                
                parent_msg_id = msg.get('parent_header', {}).get('msg_id', '')
                if parent_msg_id != msg_id:
                    continue
                
                msg_type = msg.get('header', {}).get('msg_type', '')
                content = msg.get('content', {})
                
                if msg_type == 'status' and content.get('execution_state') == 'idle':
                    is_idle = True
                    continue
                
                # 출력 처리
                if msg_type == 'stream':
                    outputs.append({
                        "output_type": "stream",
                        "name": content.get('name', 'stdout'),
                        "text": content.get('text', '')
                    })
                elif msg_type == 'execute_result':
                    self.execution_count = content.get('execution_count', self.execution_count + 1)
                    outputs.append({
                        "output_type": "execute_result",
                        "execution_count": self.execution_count,
                        "data": content.get('data', {}),
                        "metadata": content.get('metadata', {})
                    })
                elif msg_type == 'display_data':
                    outputs.append({
                        "output_type": "display_data",
                        "data": content.get('data', {}),
                        "metadata": content.get('metadata', {})
                    })
                elif msg_type == 'error':
                    outputs.append({
                        "output_type": "error",
                        "ename": content.get('ename', 'Error'),
                        "evalue": content.get('evalue', ''),
                        "traceback": content.get('traceback', [])
                    })
                
            except queue.Empty:
                continue
        
        return outputs
    
    # 기존 메서드들 유지하되 실행 부분만 개선
    async def create_notebook(self, notebook_name: str, path: str = "") -> Dict[str, Any]:
        """새 노트북 생성"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            full_path = f"{path}/{notebook_name}" if path else notebook_name
            if not full_path.endswith('.ipynb'):
                full_path += '.ipynb'
            
            notebook_content = {
                "type": "notebook",
                "content": {
                    "cells": [],
                    "metadata": {},
                    "nbformat": 4,
                    "nbformat_minor": 4
                }
            }
            
            response = await session.put(
                f"{server_url}/api/contents/{full_path}",
                json=notebook_content
            )
            
            if response.status_code in [200, 201]:
                return {
                    "success": True,
                    "message": f"Notebook '{notebook_name}' created successfully",
                    "path": full_path,
                    "url": f"{server_url}/notebooks/{full_path}"
                }
            else:
                return {"success": False, "error": f"Failed to create notebook: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error creating notebook: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def add_cell(self, notebook_path: str, content: str, cell_type: str = "code", position: int = -1) -> Dict[str, Any]:
        """노트북에 셀 추가"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            response = await session.get(f"{server_url}/api/contents/{notebook_path}")
            if response.status_code != 200:
                return {"success": False, "error": f"Notebook not found: {notebook_path}"}
            
            notebook = response.json()
            cells = notebook["content"]["cells"]
            
            # 셀 내용 정규화
            cell_source = content
            
            new_cell = {
                "cell_type": cell_type,
                "metadata": {},
                "source": cell_source
            }
            
            if cell_type == "code":
                new_cell["outputs"] = []
                new_cell["execution_count"] = None
            
            if position == -1 or position >= len(cells):
                cells.append(new_cell)
                position = len(cells) - 1
            else:
                cells.insert(position, new_cell)
            
            response = await session.put(
                f"{server_url}/api/contents/{notebook_path}",
                json=notebook
            )
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": f"Cell added to {notebook_path}",
                    "cell_type": cell_type,
                    "position": position,
                    "content_preview": content[:50] + "..." if len(content) > 50 else content
                }
            else:
                return {"success": False, "error": f"Failed to update notebook: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error adding cell: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def execute_cell_with_websocket(self, notebook_path: str, cell_index: int) -> Dict[str, Any]:
        """WebSocket을 통한 실제 셀 실행"""
        try:
            with self.kernel_lock:
                server_url = await self.get_user_server_url()
                session = await self.get_session()
                
                # 노트북 내용 가져오기
                response = await session.get(f"{server_url}/api/contents/{notebook_path}")
                if response.status_code != 200:
                    return {"success": False, "error": f"Notebook not found: {notebook_path}"}
                
                notebook = response.json()
                cells = notebook["content"]["cells"]
                
                if cell_index >= len(cells):
                    return {"success": False, "error": f"Cell index {cell_index} out of range"}
                
                cell = cells[cell_index]
                if cell["cell_type"] != "code":
                    return {"success": False, "error": "Can only execute code cells"}
                
                # 커널 확인/생성
                kernel_id = await self.get_or_create_kernel()
                if not kernel_id:
                    return {"success": False, "error": "Failed to get kernel"}
                
                # WebSocket이 연결되어 있는지 확인
                if not self.ws or not self.ws_listener or not self.ws_listener.is_alive():
                    if not await self._connect_websocket():
                        return {"success": False, "error": "Failed to connect WebSocket"}
                
                # 코드 실행
                code = cell["source"]
                logger.info(f"Executing code via WebSocket: {code[:100]}...")
                
                # 동기 함수를 비동기에서 실행
                def execute_sync():
                    msg_id = self._send_execute_request(code)
                    return self._collect_execution_results(msg_id, timeout=30)
                
                loop = asyncio.get_event_loop()
                outputs = await loop.run_in_executor(None, execute_sync)
                
                # 결과를 노트북에 저장
                cell["outputs"] = outputs
                if outputs:
                    for output in outputs:
                        if output.get("output_type") == "execute_result":
                            cell["execution_count"] = output.get("execution_count")
                            break
                    else:
                        cell["execution_count"] = self.execution_count
                
                # 노트북 저장
                save_response = await session.put(
                    f"{server_url}/api/contents/{notebook_path}",
                    json=notebook
                )
                
                if save_response.status_code == 200:
                    return {
                        "success": True,
                        "message": f"Cell {cell_index} executed successfully via WebSocket",
                        "code": code,
                        "outputs": outputs,
                        "execution_count": cell.get("execution_count")
                    }
                else:
                    return {"success": False, "error": "Failed to save execution results"}
                
        except Exception as e:
            logger.error(f"Error executing cell with WebSocket: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def add_and_execute_cell_with_websocket(self, notebook_path: str, content: str) -> Dict[str, Any]:
        """셀 추가 후 WebSocket으로 실행"""
        try:
            # 셀 추가
            add_result = await self.add_cell(notebook_path, content, "code")
            if not add_result["success"]:
                return add_result
            
            # 추가된 셀 실행
            position = add_result["position"]
            execute_result = await self.execute_cell_with_websocket(notebook_path, position)
            
            return {
                "success": True,
                "message": f"Cell added and executed successfully via WebSocket",
                "add_result": add_result,
                "execute_result": execute_result,
                "content": content,
                "position": position
            }
            
        except Exception as e:
            logger.error(f"Error in add_and_execute_cell_with_websocket: {str(e)}")
            return {"success": False, "error": str(e)}
    
    # 기존 메서드들 유지
    async def list_notebooks(self, path: str = "") -> Dict[str, Any]:
        """노트북 목록 조회"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            response = await session.get(f"{server_url}/api/contents/{path}")
            
            if response.status_code == 200:
                contents = response.json()
                notebooks = []
                
                if contents.get("type") == "directory":
                    for item in contents.get("content", []):
                        if item.get("type") == "notebook":
                            notebooks.append({
                                "name": item["name"],
                                "path": item["path"],
                                "last_modified": item["last_modified"],
                                "created": item["created"],
                                "size": item.get("size", 0)
                            })
                
                return {
                    "success": True,
                    "notebooks": notebooks,
                    "count": len(notebooks),
                    "path": path
                }
            else:
                return {"success": False, "error": f"Failed to list notebooks: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error listing notebooks: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def get_notebook_content(self, notebook_path: str) -> Dict[str, Any]:
        """노트북 내용 조회"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            response = await session.get(f"{server_url}/api/contents/{notebook_path}")
            
            if response.status_code == 200:
                notebook = response.json()
                cells = []
                
                if notebook.get("content"):
                    for i, cell in enumerate(notebook["content"].get("cells", [])):
                        cells.append({
                            "index": i,
                            "cell_type": cell.get("cell_type"),
                            "source": cell.get("source", ""),
                            "execution_count": cell.get("execution_count"),
                            "outputs": cell.get("outputs", [])
                        })
                
                return {
                    "success": True,
                    "notebook_path": notebook_path,
                    "cells": cells,
                    "cell_count": len(cells),
                    "last_modified": notebook.get("last_modified")
                }
            else:
                return {"success": False, "error": f"Failed to get notebook: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error getting notebook content: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def delete_cell(self, notebook_path: str, cell_index: int) -> Dict[str, Any]:
        """노트북에서 셀 삭제"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            # 노트북 내용 가져오기
            response = await session.get(f"{server_url}/api/contents/{notebook_path}")
            
            if response.status_code != 200:
                return {"success": False, "error": f"Notebook not found: {notebook_path}"}
            
            notebook = response.json()
            cells = notebook["content"]["cells"]
            
            if 0 <= cell_index < len(cells):
                deleted_cell = cells.pop(cell_index)
                
                # 노트북 업데이트
                response = await session.put(
                    f"{server_url}/api/contents/{notebook_path}",
                    json=notebook
                )
                
                if response.status_code == 200:
                    return {
                        "success": True,
                        "message": f"Cell {cell_index} deleted from {notebook_path}",
                        "deleted_cell_type": deleted_cell.get("cell_type"),
                        "remaining_cells": len(cells)
                    }
                else:
                    return {"success": False, "error": f"Failed to update notebook: {response.status_code}"}
            else:
                return {"success": False, "error": f"Invalid cell index: {cell_index}"}
                
        except Exception as e:
            logger.error(f"Error deleting cell: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def start_kernel(self, notebook_path: str) -> Dict[str, Any]:
        """커널 시작"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            # 새 커널 세션 시작
            kernel_spec = {"name": "python3"}
            response = await session.post(
                f"{server_url}/api/kernels",
                json=kernel_spec
            )
            
            if response.status_code in [200, 201]:
                kernel_info = response.json()
                return {
                    "success": True,
                    "kernel_id": kernel_info["id"],
                    "kernel_name": kernel_info["name"],
                    "message": "Kernel started successfully"
                }
            else:
                return {"success": False, "error": f"Failed to start kernel: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error starting kernel: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def list_running_kernels(self) -> Dict[str, Any]:
        """실행 중인 커널 목록"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            response = await session.get(f"{server_url}/api/kernels")
            
            if response.status_code == 200:
                kernels = response.json()
                return {
                    "success": True,
                    "kernels": kernels,
                    "count": len(kernels)
                }
            else:
                return {"success": False, "error": f"Failed to list kernels: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error listing kernels: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def delete_notebook(self, notebook_path: str) -> Dict[str, Any]:
        """노트북 삭제"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            response = await session.delete(f"{server_url}/api/contents/{notebook_path}")
            
            if response.status_code == 204:
                return {
                    "success": True,
                    "message": f"Notebook '{notebook_path}' deleted successfully"
                }
            else:
                return {"success": False, "error": f"Failed to delete notebook: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error deleting notebook: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def close(self):
        """리소스 정리"""
        try:
            if hasattr(self, 'ws_stop_event'):
                self.ws_stop_event.set()
            
            if hasattr(self, 'ws_listener') and self.ws_listener and self.ws_listener.is_alive():
                self.ws_listener.join(timeout=2)
            
            if hasattr(self, 'ws') and self.ws:
                self.ws.close()
            
            if self.session:
                await self.session.aclose()
                
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")


# JupyterHub 클라이언트 인스턴스
jupyter_client = JupyterHubClient(**JUPYTERHUB_CONFIG)

# =============================================================================
# MCP 도구들 (기존 + 새로운 기능)
# =============================================================================

@mcp.tool()
async def execute_cell_real(notebook_path: str, cell_index: int) -> Dict[str, Any]:
    """WebSocket을 통한 실제 셀 실행 (jupyterhub_memory 방식)
    
    이 도구는 실제 JupyterHub 커널에서 코드를 실행하고 결과를 받아옵니다.
    변수 상태가 유지되고 모든 Python 라이브러리를 사용할 수 있습니다.
    """
    return await jupyter_client.execute_cell_with_websocket(notebook_path, cell_index)

@mcp.tool()
async def add_and_execute_cell_real(notebook_path: str, content: str) -> Dict[str, Any]:
    """셀 추가 후 WebSocket으로 실제 실행 (jupyterhub_memory 방식)
    
    이 도구를 사용하면:
    - 실제 JupyterHub 환경에서 코드 실행
    - 모든 Python 패키지 사용 가능
    - 변수 상태 유지 (이전 셀에서 정의한 변수 사용 가능)
    - 실제 Jupyter 출력 형식
    """
    return await jupyter_client.add_and_execute_cell_with_websocket(notebook_path, content)

@mcp.tool()
async def quick_calculation_real(notebook_name: str, expression: str) -> Dict[str, Any]:
    """실제 JupyterHub 커널에서 빠른 계산 실행
    
    이 도구는 다음을 수행합니다:
    1. 노트북 생성 (없으면)
    2. 코드 셀 추가
    3. WebSocket으로 실제 실행
    4. 결과를 노트북에 저장
    
    복잡한 계산, 데이터 분석, 그래프 생성 등 모든 Python 코드가 실행 가능합니다.
    """
    try:
        notebook_path = f"{notebook_name}.ipynb"
        
        # 노트북 생성 (존재하지 않으면)
        content_result = await jupyter_client.get_notebook_content(notebook_path)
        if not content_result.get("success"):
            create_result = await jupyter_client.create_notebook(notebook_name)
            if not create_result["success"]:
                return create_result
        
        # 실제 실행
        result = await jupyter_client.add_and_execute_cell_with_websocket(notebook_path, expression)
        return {
            "success": True,
            "message": f"Real calculation completed: {expression}",
            "notebook": notebook_path,
            "expression": expression,
            "result": result
        }
        
    except Exception as e:
        logger.error(f"Error in quick_calculation_real: {str(e)}")
        return {"success": False, "error": str(e)}
        
@mcp.tool()
async def create_notebook(notebook_name: str, path: str = "") -> Dict[str, Any]:
    """새 Jupyter 노트북을 생성합니다.
    
    이 도구를 사용해야 하는 경우:
    - 사용자가 새로운 노트북 생성을 요청할 때
    - 데이터 분석, 실험, 계산을 위한 새로운 작업공간이 필요할 때
    - 프로젝트별로 별도의 노트북을 만들고 싶을 때
    
    Args:
        notebook_name: 생성할 노트북 이름 (예: "data_analysis", "experiment_1")
        path: 노트북을 생성할 디렉토리 경로 (기본값: 루트 디렉토리)
    
    Returns:
        Dict with success status, message, file path, and access URL
    
    Example:
        create_notebook("my_analysis", "projects") -> creates "projects/my_analysis.ipynb"
    """
    return await jupyter_client.create_notebook(notebook_name, path)

@mcp.tool()
async def list_notebooks(path: str = "") -> Dict[str, Any]:
    """JupyterHub에서 노트북 목록을 조회합니다.
    
    이 도구를 사용해야 하는 경우:
    - 사용자가 기존 노트북들을 확인하고 싶을 때
    - 특정 디렉토리의 노트북들을 찾을 때
    - 작업할 노트북을 선택하기 전에 목록을 보고 싶을 때
    
    Args:
        path: 조회할 디렉토리 경로 (기본값: 루트 디렉토리)
    
    Returns:
        Dict with notebook list, count, and metadata (name, path, modified date, size)
    
    Example:
        list_notebooks() -> shows all notebooks in root
        list_notebooks("projects") -> shows notebooks in projects folder
    """
    return await jupyter_client.list_notebooks(path)

@mcp.tool()
async def get_notebook_content(notebook_path: str) -> Dict[str, Any]:
    """노트북의 전체 내용과 모든 셀들을 조회합니다.
    
    이 도구를 사용해야 하는 경우:
    - 노트북의 현재 상태를 확인할 때
    - 셀의 내용이나 실행 결과를 검토할 때
    - 노트북을 수정하기 전에 현재 내용을 파악할 때
    - 특정 셀의 인덱스나 내용을 찾을 때
    
    Args:
        notebook_path: 조회할 노트북 파일 경로 (예: "analysis.ipynb", "projects/data.ipynb")
    
    Returns:
        Dict with full notebook content, cell list with indices, types, source code, and outputs
    
    Example:
        get_notebook_content("analysis.ipynb") -> shows all cells and their content
    """
    return await jupyter_client.get_notebook_content(notebook_path)

@mcp.tool()
async def add_cell(notebook_path: str, content: str, cell_type: str = "code", position: int = -1) -> Dict[str, Any]:
    """노트북에 새로운 셀을 추가합니다 (실행하지 않음).
    
    이 도구를 사용해야 하는 경우:
    - 코드나 마크다운을 노트북에 추가만 하고 싶을 때 (실행 안함)
    - 여러 셀을 차례로 추가한 후 나중에 실행하고 싶을 때
    - 마크다운 셀로 설명이나 제목을 추가할 때
    - 특정 위치에 셀을 삽입하고 싶을 때
    
    주의: 이 도구는 셀을 추가만 합니다. 코드를 실행하지 않습니다.
    코드를 추가하고 바로 실행하려면 add_and_execute_cell을 사용하세요.
    
    Args:
        notebook_path: 대상 노트북 파일 경로
        content: 셀에 추가할 내용 (코드 또는 마크다운)
        cell_type: "code" 또는 "markdown" (기본값: "code")
        position: 셀을 삽입할 위치 (-1이면 마지막에 추가)
    
    Returns:
        Dict with success status, cell position, and content preview
    
    Example:
        add_cell("test.ipynb", "import pandas as pd", "code")
        add_cell("test.ipynb", "# Data Analysis", "markdown", 0)
    """
    return await jupyter_client.add_cell(notebook_path, content, cell_type, position)

@mcp.tool()
async def execute_cell(notebook_path: str, cell_index: int) -> Dict[str, Any]:
    """노트북의 특정 셀을 실행하고 결과를 노트북에 저장합니다.
    
    이 도구를 사용해야 하는 경우:
    - 이미 존재하는 특정 셀만 실행하고 싶을 때
    - 노트북의 일부 셀만 재실행하고 싶을 때
    - 셀 번호를 알고 있고 그 셀만 실행하고 싶을 때
    
    주의: 셀 인덱스는 0부터 시작합니다. 노트북 내용을 먼저 확인하세요.
    
    Args:
        notebook_path: 대상 노트북 파일 경로
        cell_index: 실행할 셀의 인덱스 (0부터 시작)
    
    Returns:
        Dict with execution results, outputs, and updated notebook status
    
    Example:
        execute_cell("analysis.ipynb", 0) -> executes first cell
        execute_cell("analysis.ipynb", 2) -> executes third cell
    """
    return await jupyter_client.execute_cell(notebook_path, cell_index)

@mcp.tool()
async def add_and_execute_cell(notebook_path: str, content: str) -> Dict[str, Any]:
    """노트북에 코드 셀을 추가하고 즉시 실행합니다.
    
    이 도구를 사용해야 하는 경우:
    - 새로운 코드를 노트북에 추가하고 바로 실행 결과를 보고 싶을 때
    - 데이터 분석이나 계산을 단계별로 진행할 때
    - 사용자가 "코드를 추가하고 실행해줘"라고 요청할 때
    - 실험적인 코드를 빠르게 테스트하고 싶을 때
    
    이것은 add_cell + execute_cell을 한번에 수행하는 편의 기능입니다.
    
    Args:
        notebook_path: 대상 노트북 파일 경로
        content: 실행할 Python 코드
    
    Returns:
        Dict with both add and execution results, including outputs and cell position
    
    Example:
        add_and_execute_cell("test.ipynb", "print('Hello World')")
        add_and_execute_cell("analysis.ipynb", "df = pd.read_csv('data.csv')\nprint(df.shape)")
    """
    return await jupyter_client.add_and_execute_cell(notebook_path, content)

@mcp.tool()
async def quick_calculation(notebook_name: str, expression: str) -> Dict[str, Any]:
    """빠른 계산이나 간단한 코드 실행을 위해 노트북을 생성하고 코드를 실행합니다.
    
    이 도구를 사용해야 하는 경우:
    - 사용자가 "1+1 계산해줘", "수학 계산해줘" 같은 간단한 요청을 할 때
    - 노트북이 없는 상태에서 새로 만들어서 계산하고 싶을 때
    - 일회성 계산이나 실험을 위해 새로운 노트북이 필요할 때
    - 완전히 새로운 작업을 시작할 때
    
    이 도구는 다음을 자동으로 수행합니다:
    1. 노트북이 없으면 생성
    2. 코드 셀 추가
    3. 즉시 실행
    4. 결과를 노트북에 저장
    
    Args:
        notebook_name: 생성할 노트북 이름 (.ipynb 확장자 자동 추가)
        expression: 실행할 Python 코드나 수학 계산식
    
    Returns:
        Dict with complete operation results including notebook creation and execution
    
    Example:
        quick_calculation("calc", "1 + 1")
        quick_calculation("analysis", "import numpy as np; print(np.mean([1,2,3,4,5]))")
        quick_calculation("test", "result = 2 ** 10\nprint(f'2^10 = {result}')")
    """
    try:
        # 노트북 경로 생성
        notebook_path = f"{notebook_name}.ipynb"
        
        # 노트북이 존재하는지 확인
        content_result = await jupyter_client.get_notebook_content(notebook_path)
        
        # 노트북이 없으면 생성
        if not content_result["success"]:
            create_result = await jupyter_client.create_notebook(notebook_name)
            if not create_result["success"]:
                return create_result
        
        # 계산 셀 추가 및 실행
        result = await jupyter_client.add_and_execute_cell(notebook_path, expression)
        return {
            "success": True,
            "message": f"Quick calculation completed: {expression}",
            "notebook": notebook_path,
            "expression": expression,
            "result": result
        }
        
    except Exception as e:
        logger.error(f"Error in quick_calculation: {str(e)}")
        return {"success": False, "error": str(e)}

@mcp.tool()
async def delete_cell(notebook_path: str, cell_index: int) -> Dict[str, Any]:
    """노트북에서 특정 셀을 삭제합니다.
    
    이 도구를 사용해야 하는 경우:
    - 잘못 추가된 셀을 제거하고 싶을 때
    - 노트북을 정리하고 불필요한 셀을 삭제할 때
    - 에러가 있는 셀을 제거하고 싶을 때
    
    주의: 삭제된 셀은 복구할 수 없습니다.
    
    Args:
        notebook_path: 대상 노트북 파일 경로
        cell_index: 삭제할 셀의 인덱스 (0부터 시작)
    
    Returns:
        Dict with deletion status and remaining cell count
    
    Example:
        delete_cell("test.ipynb", 2) -> deletes third cell
    """
    return await jupyter_client.delete_cell(notebook_path, cell_index)

@mcp.tool()
async def delete_notebook(notebook_path: str) -> Dict[str, Any]:
    """노트북 파일을 완전히 삭제합니다.
    
    이 도구를 사용해야 하는 경우:
    - 더 이상 필요없는 노트북을 제거하고 싶을 때
    - 실험용으로 만든 임시 노트북을 정리할 때
    - 저장공간을 확보하고 싶을 때
    
    주의: 삭제된 노트북은 복구할 수 없습니다.
    
    Args:
        notebook_path: 삭제할 노트북 파일 경로
    
    Returns:
        Dict with deletion confirmation
    
    Example:
        delete_notebook("old_experiment.ipynb")
    """
    return await jupyter_client.delete_notebook(notebook_path)

@mcp.tool()
async def start_kernel(notebook_path: str) -> Dict[str, Any]:
    """노트북을 위한 새로운 Python 커널을 시작합니다.
    
    이 도구를 사용해야 하는 경우:
    - 커널이 없어서 코드 실행이 안될 때
    - 커널이 죽었거나 응답하지 않을 때
    - 새로운 Python 환경에서 코드를 실행하고 싶을 때
    
    Args:
        notebook_path: 커널을 시작할 노트북 경로 (참조용)
    
    Returns:
        Dict with kernel ID, name, and startup status
    
    Example:
        start_kernel("analysis.ipynb")
    """
    return await jupyter_client.start_kernel(notebook_path)

@mcp.tool()
async def list_running_kernels() -> Dict[str, Any]:
    """현재 실행 중인 모든 Python 커널의 목록을 조회합니다.
    
    이 도구를 사용해야 하는 경우:
    - 시스템 리소스 사용량을 확인하고 싶을 때
    - 실행 중인 커널들을 모니터링하고 싶을 때
    - 커널 관리나 문제 해결이 필요할 때
    
    Returns:
        Dict with list of running kernels, their IDs, and count
    
    Example:
        list_running_kernels() -> shows all active Python kernels
    """
    return await jupyter_client.list_running_kernels()

@mcp.tool()
async def start_user_server() -> Dict[str, Any]:
    """사용자의 JupyterHub 서버를 시작합니다.
    
    이 도구를 사용해야 하는 경우:
    - JupyterHub 서버가 중지되어 있을 때
    - 노트북 작업을 시작하기 전에 서버를 확실히 실행하고 싶을 때
    - 서버 연결 문제가 있을 때
    
    이 도구는 보통 자동으로 호출되므로 수동으로 사용할 필요는 거의 없습니다.
    
    Returns:
        Dict with server startup status and message
    
    Example:
        start_user_server() -> ensures JupyterHub server is running
    """
    return await jupyter_client.start_user_server()

@mcp.tool()
def get_server_status() -> Dict[str, Any]:
    """MCP 서버 상태를 반환합니다."""
    return {
        "status": "running",
        "timestamp": time.time(),
        "version": "2.1.0",
        "transport": "sse",
        "features": [
            "create_notebook", "list_notebooks", "get_notebook_content", "delete_notebook",
            "add_cell", "execute_cell", "add_and_execute_cell", "quick_calculation", "delete_cell",
            "start_kernel", "list_running_kernels", "start_user_server"
        ],
        "new_features": [
            "execute_cell - 셀 실행 기능",
            "add_and_execute_cell - 셀 추가 후 바로 실행",
            "quick_calculation - 빠른 계산 (노트북 생성 + 셀 추가 + 실행)"
        ],
        "jupyter_config": {
            "hub_url": JUPYTERHUB_CONFIG["hub_url"],
            "username": JUPYTERHUB_CONFIG["username"]
        }
    }

# =============================================================================
# 리소스 (업데이트)
# =============================================================================

@mcp.resource("jupyter://help")
def get_help_info() -> str:
    """JupyterHub MCP 사용 도움말 (업데이트)"""
    return f"""
# JupyterHub MCP Server v2.1.0 - Enhanced with Cell Execution

## 🚀 새로운 기능들

### 셀 실행 기능
- `execute_cell(notebook_path, cell_index)` - 특정 셀 실행
- `add_and_execute_cell(notebook_path, content)` - 셀 추가 후 바로 실행  
- `quick_calculation(notebook_name, expression)` - 빠른 계산

## 📝 사용 예시

### 1+1 계산 예시
```python
# 방법 1: 빠른 계산 (가장 간단)
quick_calculation("calc", "1 + 1")

# 방법 2: 단계별 실행
create_notebook("test")
add_and_execute_cell("test.ipynb", "result = 1 + 1\\nprint(f'Result: {{result}}')")

# 방법 3: 수동 단계
create_notebook("manual")
add_cell("manual.ipynb", "1 + 1", "code")
execute_cell("manual.ipynb", 0)
```

### 복잡한 계산 예시
```python
quick_calculation("analysis", '''
import numpy as np
data = np.array([1, 2, 3, 4, 5])
mean = data.mean()
print(f"Mean: {{mean}}")
''')
```

## 🛠️ 전체 도구 목록

### Notebook Management
- create_notebook, list_notebooks, get_notebook_content, delete_notebook

### Cell Operations  
- add_cell, execute_cell, add_and_execute_cell, delete_cell
- **quick_calculation** (⭐ 새 기능)

### Kernel Management
- start_kernel, list_running_kernels

### Server Management  
- start_user_server, get_server_status

Config: {JUPYTERHUB_CONFIG['hub_url']} | {JUPYTERHUB_CONFIG['username']}
"""

if __name__ == "__main__":
    print(f"🚀 Starting {SERVER_NAME} v2.1.0...")
    print(f"📍 Server will be available at: http://{SERVER_HOST}:{SERVER_PORT}/sse")
    print(f"📝 JupyterHub URL: {JUPYTERHUB_CONFIG['hub_url']}")
    print(f"👤 Username: {JUPYTERHUB_CONFIG['username']}")
    print("🔧 Transport: SSE (Server-Sent Events)")
    
    print("\n✨ New Features in v2.1.0:")
    print("  ⚡ execute_cell - Execute specific cells")
    print("  🚀 add_and_execute_cell - Add and execute in one step")
    print("  🧮 quick_calculation - Instant calculations")
    
    print("\n🛠️ Available tools:")
    print("  📓 Notebooks: create_notebook, list_notebooks, get_notebook_content, delete_notebook")
    print("  📝 Cells: add_cell, execute_cell, add_and_execute_cell, delete_cell")
    print("  🧮 Quick: quick_calculation")
    print("  🔧 System: start_kernel, list_running_kernels, start_user_server, get_server_status")
    
    print("\n📡 Starting server...")
    
    # SSE 방식으로 서버 실행
    mcp.run(
        transport="sse",
        host=SERVER_HOST,
        port=SERVER_PORT
    )