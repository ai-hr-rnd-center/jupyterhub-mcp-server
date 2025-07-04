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
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
    """간소화된 JupyterHub 클라이언트 - 핵심 기능만"""
    
    def __init__(self, hub_url: str, api_token: str, username: str):
        self.hub_url = hub_url.rstrip('/')
        self.api_token = api_token
        self.username = username
        self.session = None
        
        # WebSocket 관련
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
        
        self.headers = {
            'Authorization': f'token {api_token}',
            'Content-Type': 'application/json'
        }
        
    async def get_session(self):
        if not self.session:
            self.session = httpx.AsyncClient(headers=self.headers, timeout=30.0)
        return self.session
    
    async def get_user_server_url(self) -> str:
        """사용자 서버 URL"""
        try:
            session = await self.get_session()
            response = await session.get(f"{self.hub_url}/hub/api/users/{self.username}")
            
            if response.status_code == 200:
                user_info = response.json()
                if not user_info.get("servers", {}).get(""):
                    # 서버 시작
                    await session.post(f"{self.hub_url}/hub/api/users/{self.username}/server")
                    await asyncio.sleep(5)
                
                return f"{self.hub_url}/user/{self.username}"
        except Exception as e:
            logger.error(f"Error getting server URL: {e}")
            
        return f"{self.hub_url}/user/{self.username}"
    
    async def create_notebook(self, notebook_name: str, path: str = "") -> Dict[str, Any]:
        """노트북 생성"""
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
            
            response = await session.put(f"{server_url}/api/contents/{full_path}", json=notebook_content)
            
            if response.status_code in [200, 201]:
                return {
                    "success": True,
                    "message": f"Created notebook: {notebook_name}",
                    "path": full_path
                }
            else:
                return {"success": False, "error": f"Failed: {response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def add_cell(self, notebook_path: str, content: str, cell_type: str = "code") -> Dict[str, Any]:
        """셀 추가"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            # 노트북 가져오기
            response = await session.get(f"{server_url}/api/contents/{notebook_path}")
            if response.status_code != 200:
                return {"success": False, "error": "Notebook not found"}
            
            notebook = response.json()
            cells = notebook["content"]["cells"]
            
            # 새 셀 추가
            new_cell = {
                "cell_type": cell_type,
                "metadata": {},
                "source": content
            }
            
            if cell_type == "code":
                new_cell["outputs"] = []
                new_cell["execution_count"] = None
            
            cells.append(new_cell)
            position = len(cells) - 1
            
            # 저장
            response = await session.put(f"{server_url}/api/contents/{notebook_path}", json=notebook)
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": f"Added cell to {notebook_path}",
                    "position": position
                }
            else:
                return {"success": False, "error": "Failed to save"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def setup_kernel_and_websocket(self) -> bool:
        """커널과 WebSocket 설정"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            # 커널 확인/생성
            response = await session.get(f"{server_url}/api/kernels")
            if response.status_code == 200:
                kernels = response.json()
                if kernels:
                    self.kernel_id = kernels[0]["id"]
                else:
                    # 새 커널 생성
                    response = await session.post(f"{server_url}/api/kernels", json={"name": "python3"})
                    if response.status_code in [200, 201]:
                        self.kernel_id = response.json()["id"]
                        await asyncio.sleep(3)
                    else:
                        return False
            
            # WebSocket URL 설정
            ws_url = f"{server_url}/api/kernels/{self.kernel_id}/channels"
            parsed_url = urllib.parse.urlparse(ws_url)
            ws_protocol = "wss" if parsed_url.scheme == "https" else "ws"
            self.ws_url = f"{ws_protocol}://{parsed_url.netloc}{parsed_url.path}"
            
            logger.info(f"Kernel: {self.kernel_id}, WebSocket: {self.ws_url}")
            
            # WebSocket 연결
            return await self._connect_websocket()
            
        except Exception as e:
            logger.error(f"Kernel setup error: {e}")
            return False
    
    async def _connect_websocket(self) -> bool:
        """WebSocket 연결"""
        try:
            def connect():
                try:
                    headers = [f"Authorization: token {self.api_token}"]
                    cookies = f"jupyterhub-user={self.username}"
                    
                    self.ws = websocket.create_connection(
                        self.ws_url, 
                        header=headers, 
                        cookie=cookies,
                        timeout=30
                    )
                    return True
                except Exception as e:
                    logger.error(f"WebSocket error: {e}")
                    return False
            
            # 비동기에서 동기 함수 실행
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, connect)
            
            if success:
                self.ws_queue = queue.Queue()
                self.ws_stop_event.clear()
                
                # 리스너 시작
                self.ws_listener = threading.Thread(target=self._ws_listener)
                self.ws_listener.daemon = True
                self.ws_listener.start()
                
                logger.info("WebSocket connected")
                return True
            return False
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            return False
    
    def _ws_listener(self):
        """WebSocket 리스너"""
        try:
            while not self.ws_stop_event.is_set():
                try:
                    msg = self.ws.recv()
                    if msg:
                        self.ws_queue.put(json.loads(msg))
                except websocket.WebSocketTimeoutException:
                    continue
                except:
                    break
        except Exception as e:
            logger.error(f"WebSocket listener error: {e}")
    
    async def execute_cell(self, notebook_path: str, cell_index: int) -> Dict[str, Any]:
        """셀 실행"""
        try:
            # 커널/WebSocket 설정
            if not self.kernel_id or not self.ws:
                if not await self.setup_kernel_and_websocket():
                    return {"success": False, "error": "Failed to setup kernel/WebSocket"}
            
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            # 노트북 가져오기
            response = await session.get(f"{server_url}/api/contents/{notebook_path}")
            if response.status_code != 200:
                return {"success": False, "error": "Notebook not found"}
            
            notebook = response.json()
            cells = notebook["content"]["cells"]
            
            if cell_index >= len(cells):
                return {"success": False, "error": "Cell index out of range"}
            
            cell = cells[cell_index]
            if cell["cell_type"] != "code":
                return {"success": False, "error": "Not a code cell"}
            
            code = cell["source"]
            logger.info(f"Executing: {code[:100]}...")
            
            # 실행 요청 (동기)
            def execute():
                msg_id = f"exec_{time.time()}"
                
                msg = {
                    'header': {
                        'msg_id': msg_id,
                        'username': self.username,
                        'session': f"session_{time.time()}",
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
                    }
                }
                
                self.ws.send(json.dumps(msg))
                
                # 결과 수집
                outputs = []
                start_time = time.time()
                is_idle = False
                
                while not is_idle and time.time() - start_time < 30:
                    try:
                        msg = self.ws_queue.get(timeout=1)
                        parent_id = msg.get('parent_header', {}).get('msg_id', '')
                        
                        if parent_id != msg_id:
                            continue
                        
                        msg_type = msg.get('header', {}).get('msg_type', '')
                        content = msg.get('content', {})
                        
                        if msg_type == 'status' and content.get('execution_state') == 'idle':
                            is_idle = True
                        elif msg_type == 'stream':
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
            
            # 비동기에서 동기 실행
            loop = asyncio.get_event_loop()
            outputs = await loop.run_in_executor(None, execute)
            
            # 결과 저장
            cell["outputs"] = outputs
            cell["execution_count"] = self.execution_count
            
            response = await session.put(f"{server_url}/api/contents/{notebook_path}", json=notebook)
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": f"Executed cell {cell_index}",
                    "code": code,
                    "outputs": outputs,
                    "execution_count": self.execution_count
                }
            else:
                return {"success": False, "error": "Failed to save results"}
                
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return {"success": False, "error": str(e)}
    
    async def add_and_execute_cell(self, notebook_path: str, content: str) -> Dict[str, Any]:
        """셀 추가 후 바로 실행"""
        try:
            # 셀 추가
            add_result = await self.add_cell(notebook_path, content, "code")
            if not add_result["success"]:
                return add_result
            
            # 바로 실행
            position = add_result["position"]
            execute_result = await self.execute_cell(notebook_path, position)
            
            return {
                "success": True,
                "message": "Cell added and executed",
                "add_result": add_result,
                "execute_result": execute_result
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def list_notebooks(self, path: str = "") -> Dict[str, Any]:
        """노트북 목록"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            response = await session.get(f"{server_url}/api/contents/{path}")
            
            if response.status_code == 200:
                contents = response.json()
                notebooks = []
                
                for item in contents.get("content", []):
                    if item.get("type") == "notebook":
                        notebooks.append({
                            "name": item["name"],
                            "path": item["path"]
                        })
                
                return {"success": True, "notebooks": notebooks, "count": len(notebooks)}
            else:
                return {"success": False, "error": f"Failed: {response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def close(self):
        """정리"""
        try:
            if hasattr(self, 'ws_stop_event'):
                self.ws_stop_event.set()
            if hasattr(self, 'ws') and self.ws:
                self.ws.close()
            if self.session:
                await self.session.aclose()
        except:
            pass

# 클라이언트 인스턴스
jupyter_client = JupyterHubClient(**JUPYTERHUB_CONFIG)

# =============================================================================
# MCP 도구들 (핵심 기능만)
# =============================================================================

@mcp.tool()
async def create_notebook(notebook_name: str, path: str = "") -> Dict[str, Any]:
    """새 Jupyter 노트북을 생성합니다."""
    return await jupyter_client.create_notebook(notebook_name, path)

@mcp.tool()
async def list_notebooks(path: str = "") -> Dict[str, Any]:
    """노트북 목록을 조회합니다."""
    return await jupyter_client.list_notebooks(path)

@mcp.tool()
async def add_cell(notebook_path: str, content: str, cell_type: str = "code") -> Dict[str, Any]:
    """노트북에 셀을 추가합니다 (실행하지 않음)."""
    return await jupyter_client.add_cell(notebook_path, content, cell_type)

@mcp.tool()
async def execute_cell(notebook_path: str, cell_index: int) -> Dict[str, Any]:
    """특정 셀을 실행합니다."""
    return await jupyter_client.execute_cell(notebook_path, cell_index)

@mcp.tool()
async def add_and_execute_cell(notebook_path: str, content: str) -> Dict[str, Any]:
    """셀을 추가하고 바로 실행합니다."""
    return await jupyter_client.add_and_execute_cell(notebook_path, content)

@mcp.tool()
def get_server_status() -> Dict[str, Any]:
    """서버 상태를 확인합니다."""
    return {
        "status": "running",
        "version": "2.1.0-clean",
        "features": ["create_notebook", "list_notebooks", "add_cell", "execute_cell", "add_and_execute_cell"],
        "jupyter_config": {
            "hub_url": JUPYTERHUB_CONFIG["hub_url"],
            "username": JUPYTERHUB_CONFIG["username"]
        }
    }

@mcp.resource("jupyter://help")
def get_help() -> str:
    """사용 도움말"""
    return f"""
# JupyterHub MCP Server - Core Functions

## 핵심 도구 (5개)

### 노트북 관리
- `create_notebook(name, path)` - 새 노트북 생성
- `list_notebooks(path)` - 노트북 목록 조회

### 셀 작업
- `add_cell(notebook_path, content, cell_type)` - 셀 추가만
- `execute_cell(notebook_path, cell_index)` - 특정 셀 실행만
- `add_and_execute_cell(notebook_path, content)` - 셀 추가 + 바로 실행

## 사용 예시

```python
# 1. 노트북 생성
create_notebook("test")

# 2. 셀 추가 (실행 안함)
add_cell("test.ipynb", "x = 1 + 1")

# 3. 셀 실행
execute_cell("test.ipynb", 0)

# 4. 셀 추가 + 바로 실행
add_and_execute_cell("test.ipynb", "print(f'Result: {{x}}')")
```

Config: {JUPYTERHUB_CONFIG['hub_url']} | {JUPYTERHUB_CONFIG['username']}
"""

if __name__ == "__main__":
    print(f"🚀 Starting {SERVER_NAME} (Clean Version)")
    print(f"📍 http://{SERVER_HOST}:{SERVER_PORT}/sse")
    print(f"📝 JupyterHub: {JUPYTERHUB_CONFIG['hub_url']}")
    print(f"👤 User: {JUPYTERHUB_CONFIG['username']}")
    
    print("\n🛠️ Core Tools:")
    print("  📓 create_notebook, list_notebooks")
    print("  📝 add_cell, execute_cell, add_and_execute_cell")
    
    print("\n📡 Starting server...")
    
    mcp.run(transport="sse", host=SERVER_HOST, port=SERVER_PORT)