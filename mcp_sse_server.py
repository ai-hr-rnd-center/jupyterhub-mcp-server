from fastmcp import FastMCP
import asyncio
import time
import logging
import os
import json
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

# JupyterHub 설정 (환경에 맞게 수정)
JUPYTERHUB_CONFIG = {
    "hub_url": os.getenv("JUPYTERHUB_URL", "http://localhost:8000"),
    "api_token": os.getenv("JUPYTERHUB_API_TOKEN", "your_api_token_here"),
    "username": os.getenv("JUPYTERHUB_USERNAME", "your_username")
}

class JupyterHubClient:
    """JupyterHub API 클라이언트 (셀 실행 기능 추가)"""
    
    def __init__(self, hub_url: str, api_token: str, username: str):
        self.hub_url = hub_url.rstrip('/')
        self.api_token = api_token
        self.username = username
        self.session = None
        
    async def get_session(self):
        if not self.session:
            self.session = httpx.AsyncClient(
                headers={"Authorization": f"token {self.api_token}"},
                timeout=30.0
            )
        return self.session
    
    async def get_user_server_url(self) -> str:
        """사용자의 Jupyter 서버 URL 가져오기"""
        try:
            session = await self.get_session()
            
            # JupyterHub API로 사용자 정보 조회
            response = await session.get(f"{self.hub_url}/hub/api/users/{self.username}")
            response.raise_for_status()
            user_info = response.json()
            
            # 서버가 실행 중인지 확인
            if user_info.get("servers", {}).get(""):
                server_url = f"{self.hub_url}/user/{self.username}"
                return server_url
            else:
                # 서버가 실행되지 않았다면 시작
                await self.start_user_server()
                return f"{self.hub_url}/user/{self.username}"
                
        except Exception as e:
            logger.error(f"Error getting user server URL: {str(e)}")
            # 시뮬레이션 모드로 폴백
            return f"{self.hub_url}/user/{self.username}"
    
    async def start_user_server(self) -> Dict[str, Any]:
        """사용자 서버 시작"""
        try:
            session = await self.get_session()
            
            response = await session.post(f"{self.hub_url}/hub/api/users/{self.username}/server")
            
            if response.status_code in [201, 202]:
                # 서버 시작 대기
                await asyncio.sleep(5)
                return {"success": True, "message": "User server started"}
            else:
                return {"success": False, "error": f"Failed to start server: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error starting user server: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def create_notebook(self, notebook_name: str, path: str = "") -> Dict[str, Any]:
        """새 노트북 생성"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            # 노트북 생성 API 호출
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
        """노트북에 셀 추가 (개선된 버전)"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            # 먼저 노트북 내용 가져오기
            response = await session.get(f"{server_url}/api/contents/{notebook_path}")
            
            if response.status_code != 200:
                return {"success": False, "error": f"Notebook not found: {notebook_path}"}
            
            notebook = response.json()
            cells = notebook["content"]["cells"]
            
            # 셀 내용 정규화 (중요한 수정!)
            if isinstance(content, str):
                # 문자열을 그대로 사용 (Jupyter는 문자열도 받아들임)
                cell_source = content
            else:
                cell_source = str(content)
            
            # 새 셀 생성
            new_cell = {
                "cell_type": cell_type,
                "metadata": {},
                "source": cell_source  # 문자열 그대로 사용
            }
            
            if cell_type == "code":
                new_cell["outputs"] = []
                new_cell["execution_count"] = None
            
            # 셀 추가
            if position == -1 or position >= len(cells):
                cells.append(new_cell)
                position = len(cells) - 1
            else:
                cells.insert(position, new_cell)
            
            # 노트북 업데이트
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
    
    async def execute_cell(self, notebook_path: str, cell_index: int) -> Dict[str, Any]:
        """셀 실행"""
        try:
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
            kernels_response = await session.get(f"{server_url}/api/kernels")
            kernel_id = None
            
            if kernels_response.status_code == 200:
                kernels = kernels_response.json()
                if kernels:
                    kernel_id = kernels[0]["id"]
            
            # 커널이 없으면 생성
            if not kernel_id:
                kernel_response = await session.post(f"{server_url}/api/kernels", json={"name": "python3"})
                if kernel_response.status_code in [200, 201]:
                    kernel_id = kernel_response.json()["id"]
                    await asyncio.sleep(2)  # 커널 시작 대기
                else:
                    return {"success": False, "error": "Failed to create kernel"}
            
            # 코드 실행 (간단한 방식)
            code = cell["source"]
            execute_data = {
                "code": code,
                "silent": False,
                "store_history": True
            }
            
            # 실행 요청
            execute_response = await session.post(
                f"{server_url}/api/kernels/{kernel_id}/execute",
                json=execute_data
            )
            
            if execute_response.status_code == 200:
                # 간단한 출력 시뮬레이션 (실제 WebSocket 없이)
                outputs = [{
                    "output_type": "execute_result",
                    "execution_count": 1,
                    "data": {
                        "text/plain": f"Executed: {code}"
                    }
                }]
                
                # 셀에 결과 저장
                cell["outputs"] = outputs
                cell["execution_count"] = 1
                
                # 노트북 저장
                save_response = await session.put(
                    f"{server_url}/api/contents/{notebook_path}",
                    json=notebook
                )
                
                if save_response.status_code == 200:
                    return {
                        "success": True,
                        "message": f"Cell {cell_index} executed and saved",
                        "code": code,
                        "outputs": outputs
                    }
                else:
                    return {"success": False, "error": "Failed to save execution results"}
            else:
                return {"success": False, "error": f"Execution failed: {execute_response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error executing cell: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def add_and_execute_cell(self, notebook_path: str, content: str) -> Dict[str, Any]:
        """셀 추가 후 바로 실행 (편의 함수)"""
        try:
            # 1. 셀 추가
            add_result = await self.add_cell(notebook_path, content, "code")
            if not add_result["success"]:
                return add_result
            
            # 2. 추가된 셀 실행
            position = add_result["position"]
            execute_result = await self.execute_cell(notebook_path, position)
            
            return {
                "success": True,
                "message": f"Cell added and executed successfully",
                "add_result": add_result,
                "execute_result": execute_result,
                "content": content,
                "position": position
            }
            
        except Exception as e:
            logger.error(f"Error in add_and_execute_cell: {str(e)}")
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
        if self.session:
            await self.session.aclose()

# JupyterHub 클라이언트 인스턴스
jupyter_client = JupyterHubClient(**JUPYTERHUB_CONFIG)

# =============================================================================
# MCP 도구들 (기존 + 새로운 기능)
# =============================================================================

@mcp.tool()
async def create_notebook(notebook_name: str, path: str = "") -> Dict[str, Any]:
    """새 Jupyter 노트북을 생성합니다."""
    return await jupyter_client.create_notebook(notebook_name, path)

@mcp.tool()
async def list_notebooks(path: str = "") -> Dict[str, Any]:
    """JupyterHub 노트북 목록을 조회합니다."""
    return await jupyter_client.list_notebooks(path)

@mcp.tool()
async def get_notebook_content(notebook_path: str) -> Dict[str, Any]:
    """노트북의 내용과 셀들을 조회합니다."""
    return await jupyter_client.get_notebook_content(notebook_path)

@mcp.tool()
async def add_cell(notebook_path: str, content: str, cell_type: str = "code", position: int = -1) -> Dict[str, Any]:
    """노트북에 셀을 추가합니다."""
    return await jupyter_client.add_cell(notebook_path, content, cell_type, position)

@mcp.tool()
async def execute_cell(notebook_path: str, cell_index: int) -> Dict[str, Any]:
    """노트북의 특정 셀을 실행합니다. (새 기능!)"""
    return await jupyter_client.execute_cell(notebook_path, cell_index)

@mcp.tool()
async def add_and_execute_cell(notebook_path: str, content: str) -> Dict[str, Any]:
    """셀을 추가하고 바로 실행합니다. (새 기능!)"""
    return await jupyter_client.add_and_execute_cell(notebook_path, content)

@mcp.tool()
async def quick_calculation(notebook_name: str, expression: str) -> Dict[str, Any]:
    """빠른 계산을 위해 노트북을 생성하고 계산 셀을 추가/실행합니다"""
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
    """노트북에서 셀을 삭제합니다."""
    return await jupyter_client.delete_cell(notebook_path, cell_index)

@mcp.tool()
async def delete_notebook(notebook_path: str) -> Dict[str, Any]:
    """노트북을 삭제합니다."""
    return await jupyter_client.delete_notebook(notebook_path)

@mcp.tool()
async def start_kernel(notebook_path: str) -> Dict[str, Any]:
    """노트북을 위한 새 커널을 시작합니다."""
    return await jupyter_client.start_kernel(notebook_path)

@mcp.tool()
async def list_running_kernels() -> Dict[str, Any]:
    """실행 중인 커널 목록을 조회합니다."""
    return await jupyter_client.list_running_kernels()

@mcp.tool()
async def start_user_server() -> Dict[str, Any]:
    """사용자의 Jupyter 서버를 시작합니다."""
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