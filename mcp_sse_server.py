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
    """실제 JupyterHub API를 사용하는 클라이언트"""
    
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
    
    async def add_cell(self, notebook_path: str, content: str, cell_type: str = "code", position: int = -1) -> Dict[str, Any]:
        """노트북에 셀 추가"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            # 먼저 노트북 내용 가져오기
            response = await session.get(f"{server_url}/api/contents/{notebook_path}")
            
            if response.status_code != 200:
                return {"success": False, "error": f"Notebook not found: {notebook_path}"}
            
            notebook = response.json()
            cells = notebook["content"]["cells"]
            
            # 새 셀 생성
            new_cell = {
                "cell_type": cell_type,
                "metadata": {},
                "source": content.split('\n') if '\n' in content else [content]
            }
            
            if cell_type == "code":
                new_cell["outputs"] = []
                new_cell["execution_count"] = None
            
            # 셀 추가 (position이 -1이면 마지막에 추가)
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
                    "content_length": len(content),
                    "timestamp": time.time()
                }
            else:
                return {"success": False, "error": f"Failed to update notebook: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error adding cell: {str(e)}")
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

async def add_cell_to_jupyterhub(content: str, cell_type: str = "code") -> Dict[str, Any]:
    """JupyterHub 노트북에 셀 추가 (시뮬레이션)"""
    try:
        logger.info(f"Adding {cell_type} cell with content: {content[:50]}...")
        
        # 시뮬레이션: 약간의 지연 후 성공 응답
        await asyncio.sleep(0.5)
        
        return {
            "success": True,
            "message": f"Successfully added {cell_type} cell to notebook",
            "cell_type": cell_type,
            "content_length": len(content),
            "timestamp": time.time(),
            "notebook": "test_notebook.ipynb"
        }
        
    except Exception as e:
        logger.error(f"Error adding cell: {str(e)}")
        return {"success": False, "error": str(e)}

# JupyterHub 클라이언트 인스턴스
jupyter_client = JupyterHubClient(**JUPYTERHUB_CONFIG)

@mcp.tool()
async def create_notebook(notebook_name: str, path: str = "") -> Dict[str, Any]:
    """새 Jupyter 노트북을 생성합니다.
    
    Args:
        notebook_name: 생성할 노트북 이름
        path: 노트북을 생성할 경로 (기본값: 루트)
    
    Returns:
        노트북 생성 결과
    """
    return await jupyter_client.create_notebook(notebook_name, path)

@mcp.tool()
async def list_notebooks(path: str = "") -> Dict[str, Any]:
    """JupyterHub 노트북 목록을 조회합니다.
    
    Args:
        path: 조회할 경로 (기본값: 루트)
    
    Returns:
        노트북 목록과 정보
    """
    return await jupyter_client.list_notebooks(path)

@mcp.tool()
async def get_notebook_content(notebook_path: str) -> Dict[str, Any]:
    """노트북의 내용과 셀들을 조회합니다.
    
    Args:
        notebook_path: 노트북 파일 경로
    
    Returns:
        노트북 내용과 셀 정보
    """
    return await jupyter_client.get_notebook_content(notebook_path)

@mcp.tool()
async def add_cell(notebook_path: str, content: str, cell_type: str = "code", position: int = -1) -> Dict[str, Any]:
    """노트북에 셀을 추가합니다.
    
    Args:
        notebook_path: 노트북 파일 경로
        content: 셀에 추가할 내용
        cell_type: 셀 타입 (code 또는 markdown)
        position: 셀을 삽입할 위치 (-1이면 마지막에 추가)
    
    Returns:
        셀 추가 결과
    """
    return await jupyter_client.add_cell(notebook_path, content, cell_type, position)

@mcp.tool()
async def delete_cell(notebook_path: str, cell_index: int) -> Dict[str, Any]:
    """노트북에서 셀을 삭제합니다.
    
    Args:
        notebook_path: 노트북 파일 경로
        cell_index: 삭제할 셀의 인덱스
    
    Returns:
        셀 삭제 결과
    """
    return await jupyter_client.delete_cell(notebook_path, cell_index)

@mcp.tool()
async def delete_notebook(notebook_path: str) -> Dict[str, Any]:
    """노트북을 삭제합니다.
    
    Args:
        notebook_path: 삭제할 노트북 파일 경로
    
    Returns:
        노트북 삭제 결과
    """
    return await jupyter_client.delete_notebook(notebook_path)

@mcp.tool()
async def start_kernel(notebook_path: str) -> Dict[str, Any]:
    """노트북을 위한 새 커널을 시작합니다.
    
    Args:
        notebook_path: 노트북 파일 경로
    
    Returns:
        커널 시작 결과
    """
    return await jupyter_client.start_kernel(notebook_path)

@mcp.tool()
async def list_running_kernels() -> Dict[str, Any]:
    """실행 중인 커널 목록을 조회합니다.
    
    Returns:
        실행 중인 커널 목록
    """
    return await jupyter_client.list_running_kernels()

@mcp.tool()
async def start_user_server() -> Dict[str, Any]:
    """사용자의 Jupyter 서버를 시작합니다.
    
    Returns:
        서버 시작 결과
    """
    return await jupyter_client.start_user_server()

@mcp.tool()
def get_server_status() -> Dict[str, Any]:
    """MCP 서버 상태를 반환합니다.
    
    Returns:
        서버 상태 정보
    """
    return {
        "status": "running",
        "timestamp": time.time(),
        "version": "2.0.0",
        "transport": "sse",
        "features": [
            "create_notebook",
            "list_notebooks",
            "get_notebook_content",
            "add_cell",
            "delete_cell", 
            "delete_notebook",
            "start_kernel",
            "list_running_kernels",
            "start_user_server"
        ],
        "jupyter_config": {
            "hub_url": JUPYTERHUB_CONFIG["hub_url"],
            "username": JUPYTERHUB_CONFIG["username"]
        }
    }

# 리소스 정의
@mcp.resource("jupyter://user-info")
def get_user_info() -> str:
    """현재 사용자 정보"""
    return f"""
# JupyterHub User Information

- Username: {JUPYTERHUB_CONFIG['username']}
- Hub URL: {JUPYTERHUB_CONFIG['hub_url']}
- Server Status: Connected
- API Version: 2.0.0

## Available Operations
- Create and manage notebooks
- Add, edit, and delete cells
- Start and manage kernels
- List and navigate directories

Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""

@mcp.resource("jupyter://help")
def get_help_info() -> str:
    """JupyterHub MCP 사용 도움말"""
    return """
# JupyterHub MCP Server Help

## Available Tools

### Notebook Management
- `create_notebook(name, path)` - Create a new notebook
- `list_notebooks(path)` - List notebooks in a directory
- `get_notebook_content(path)` - Get notebook content and cells
- `delete_notebook(path)` - Delete a notebook

### Cell Operations
- `add_cell(notebook_path, content, cell_type, position)` - Add a cell
- `delete_cell(notebook_path, cell_index)` - Delete a cell

### Kernel Management
- `start_kernel(notebook_path)` - Start a new kernel
- `list_running_kernels()` - List active kernels

### Server Management
- `start_user_server()` - Start user's Jupyter server
- `get_server_status()` - Check server status

## Example Usage

```python
# Create a new notebook
create_notebook("my_analysis.ipynb", "projects")

# Add a code cell
add_cell("projects/my_analysis.ipynb", "print('Hello World!')", "code")

# Add a markdown cell
add_cell("projects/my_analysis.ipynb", "# My Analysis", "markdown", 0)

# List all notebooks
list_notebooks()
```

For more information, visit: {JUPYTERHUB_CONFIG['hub_url']}
"""

if __name__ == "__main__":
    print(f"🚀 Starting {SERVER_NAME}...")
    print(f"📍 Server will be available at: http://{SERVER_HOST}:{SERVER_PORT}/sse")
    print(f"📝 JupyterHub URL: {JUPYTERHUB_CONFIG['hub_url']}")
    print(f"👤 Username: {JUPYTERHUB_CONFIG['username']}")
    print("🔧 Transport: SSE (Server-Sent Events)")
    print(f"📊 Log Level: {log_level}")
    print("\n🛠️ Available tools:")
    print("  - create_notebook")
    print("  - list_notebooks")
    print("  - get_notebook_content")
    print("  - add_cell")
    print("  - delete_cell")
    print("  - delete_notebook")
    print("  - start_kernel")
    print("  - list_running_kernels")
    print("  - start_user_server")
    print("  - get_server_status")
    print("\n📡 Starting server...")
    
    # SSE 방식으로 서버 실행
    mcp.run(
        transport="sse",
        host=SERVER_HOST,
        port=SERVER_PORT
    )