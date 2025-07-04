import os
import time
from fastmcp import FastMCP
from dotenv import load_dotenv
from jupyterhub_client import JupyterHubClient
from utils import split_code_into_blocks
from typing import Dict, Any

# 환경변수 로드
load_dotenv()

# 서버 설정
SERVER_NAME = os.getenv("SERVER_NAME", "JupyterHub MCP Server")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# JupyterHub 설정
JUPYTERHUB_CONFIG = {
    "hub_url": os.getenv("JUPYTERHUB_URL", "http://localhost:8000"),
    "api_token": os.getenv("JUPYTERHUB_API_TOKEN", "your_api_token_here"),
    "username": os.getenv("JUPYTERHUB_USERNAME", "your_username")
}

# FastMCP 서버 생성
mcp = FastMCP(SERVER_NAME)

# 헬퍼 함수
def get_client():
    """JupyterHub 클라이언트 인스턴스를 생성합니다."""
    return JupyterHubClient(**JUPYTERHUB_CONFIG)

# =============================================================================
# 서버 상태 도구
# =============================================================================

@mcp.tool()
def get_server_status():
    """MCP 서버 상태를 반환합니다."""
    return {
        "status": "running",
        "timestamp": time.time(),
        "version": "2.0.0",
        "transport": "sse",
        "features": [
            "create_notebook", 
            "list_notebooks", 
            "get_notebook_content", 
            "delete_notebook",
            "add_cell", 
            "add_code_blocks", 
            "delete_cell",
            "start_kernel", 
            "list_running_kernels", 
            "start_user_server"
        ],
        "jupyter_config": {
            "hub_url": JUPYTERHUB_CONFIG["hub_url"],
            "username": JUPYTERHUB_CONFIG["username"]
        }
    }

# =============================================================================
# 노트북 관리 도구
# =============================================================================

@mcp.tool()
async def create_notebook(notebook_name: str, path: str = "") -> Dict[str, Any]:
    """새 Jupyter 노트북을 생성합니다.
    
    Args:
        notebook_name: 생성할 노트북 이름
        path: 노트북을 생성할 경로 (기본값: 루트)
    
    Returns:
        노트북 생성 결과
    """
    client = get_client()
    try:
        return await client.create_notebook(notebook_name, path)
    finally:
        await client.close()

@mcp.tool()
async def list_notebooks(path: str = "") -> Dict[str, Any]:
    """JupyterHub 노트북 목록을 조회합니다.
    
    Args:
        path: 조회할 경로 (기본값: 루트)
    
    Returns:
        노트북 목록과 정보
    """
    client = get_client()
    try:
        return await client.list_notebooks(path)
    finally:
        await client.close()

@mcp.tool()
async def get_notebook_content(notebook_path: str) -> Dict[str, Any]:
    """노트북의 내용과 셀들을 조회합니다.
    
    Args:
        notebook_path: 노트북 파일 경로
    
    Returns:
        노트북 내용과 셀 정보
    """
    client = get_client()
    try:
        return await client.get_notebook_content(notebook_path)
    finally:
        await client.close()

@mcp.tool()
async def delete_notebook(notebook_path: str) -> Dict[str, Any]:
    """노트북을 삭제합니다.
    
    Args:
        notebook_path: 삭제할 노트북 파일 경로
    
    Returns:
        노트북 삭제 결과
    """
    client = get_client()
    try:
        return await client.delete_notebook(notebook_path)
    finally:
        await client.close()

# =============================================================================
# 셀 관리 도구
# =============================================================================

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
    client = get_client()
    try:
        return await client.add_cell(notebook_path, content, cell_type, position)
    finally:
        await client.close()

@mcp.tool()
async def add_code_blocks(notebook_path: str, content: str, auto_split: bool = True) -> Dict[str, Any]:
    """코드를 자동으로 분석하여 여러 셀로 나누어 추가합니다.
    
    Args:
        notebook_path: 노트북 파일 경로
        content: 추가할 코드 내용
        auto_split: 자동으로 논리적 블록으로 분할할지 여부
    
    Returns:
        셀 추가 결과
    """
    client = get_client()
    try:
        if not auto_split:
            # 분할하지 않고 하나의 셀로 추가
            return await client.add_cell(notebook_path, content, "code")
        
        # 코드를 논리적 블록으로 분할
        code_blocks = split_code_into_blocks(content)
        
        results = []
        for i, block in enumerate(code_blocks):
            if block.strip():  # 빈 블록 제외
                result = await client.add_cell(notebook_path, block, "code")
                results.append({
                    "block_index": i,
                    "success": result.get("success", False),
                    "message": result.get("message", ""),
                    "position": result.get("position", -1)
                })
        
        successful_blocks = sum(1 for r in results if r["success"])
        
        return {
            "success": True,
            "message": f"Added {successful_blocks} code blocks to {notebook_path}",
            "total_blocks": len(code_blocks),
            "successful_blocks": successful_blocks,
            "results": results,
            "timestamp": time.time()
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await client.close()

@mcp.tool()
async def delete_cell(notebook_path: str, cell_index: int) -> Dict[str, Any]:
    """노트북에서 셀을 삭제합니다.
    
    Args:
        notebook_path: 노트북 파일 경로
        cell_index: 삭제할 셀의 인덱스
    
    Returns:
        셀 삭제 결과
    """
    client = get_client()
    try:
        return await client.delete_cell(notebook_path, cell_index)
    finally:
        await client.close()

# =============================================================================
# 커널 관리 도구
# =============================================================================

@mcp.tool()
async def start_kernel(notebook_path: str) -> Dict[str, Any]:
    """노트북을 위한 새 커널을 시작합니다.
    
    Args:
        notebook_path: 노트북 파일 경로
    
    Returns:
        커널 시작 결과
    """
    client = get_client()
    try:
        return await client.start_kernel(notebook_path)
    finally:
        await client.close()

@mcp.tool()
async def list_running_kernels() -> Dict[str, Any]:
    """실행 중인 커널 목록을 조회합니다.
    
    Returns:
        실행 중인 커널 목록
    """
    client = get_client()
    try:
        return await client.list_running_kernels()
    finally:
        await client.close()

# =============================================================================
# 파일 관리 도구
# =============================================================================

@mcp.tool()
async def start_user_server() -> Dict[str, Any]:
    """사용자의 Jupyter 서버를 시작합니다.
    
    Returns:
        서버 시작 결과
    """
    client = get_client()
    try:
        return await client.start_user_server()
    finally:
        await client.close()

# =============================================================================
# 리소스 정의
# =============================================================================

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
    return f"""
# JupyterHub MCP Server Help

## Available Tools

### Notebook Management
- `create_notebook(name, path)` - Create a new notebook
- `list_notebooks(path)` - List notebooks in a directory
- `get_notebook_content(path)` - Get notebook content and cells
- `delete_notebook(path)` - Delete a notebook

### Cell Operations
- `add_cell(notebook_path, content, cell_type, position)` - Add a cell
- `add_code_blocks(notebook_path, content, auto_split)` - Add code with auto-split
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

# Add a code cell with auto-split
add_code_blocks("projects/my_analysis.ipynb", '''
import pandas as pd
import numpy as np

df = pd.read_csv('data.csv')
print(df.head())

# Analysis code
result = df.groupby('category').mean()
print(result)
''', auto_split=True)

# List all notebooks
list_notebooks()
```

For more information, visit: {JUPYTERHUB_CONFIG['hub_url']}
"""

# =============================================================================
# 서버 실행
# =============================================================================

if __name__ == "__main__":
    print(f"🚀 Starting {SERVER_NAME}...")
    print(f"📍 Server will be available at: http://{SERVER_HOST}:{SERVER_PORT}/sse")
    print(f"📝 JupyterHub URL: {JUPYTERHUB_CONFIG['hub_url']}")
    print(f"👤 Username: {JUPYTERHUB_CONFIG['username']}")
    print("🔧 Transport: SSE (Server-Sent Events)")
    print(f"📊 Log Level: {os.getenv('LOG_LEVEL', 'INFO')}")
    
    print("\n🛠️ Available tools:")
    print("  - create_notebook")
    print("  - list_notebooks")
    print("  - get_notebook_content")
    print("  - add_cell")
    print("  - add_code_blocks (AUTO-SPLIT)")
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