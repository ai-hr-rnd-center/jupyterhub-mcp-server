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

def get_client():
    """클라이언트 생성"""
    return JupyterHubClient(**JUPYTERHUB_CONFIG)

# =============================================================================
# 기본 도구들
# =============================================================================

@mcp.tool()
def get_server_status():
    """서버 상태 확인"""
    return {
        "status": "running",
        "version": "2.0.0-simplified",
        "features": [
            "create_notebook", "list_notebooks", "delete_notebook",
            "add_cell", "add_code_blocks", "delete_cell",
            "execute_cell", "add_and_execute_cell",
            "list_kernels", "start_user_server"
        ],
        "config": {
            "hub_url": JUPYTERHUB_CONFIG["hub_url"],
            "username": JUPYTERHUB_CONFIG["username"]
        }
    }

@mcp.tool()
async def create_notebook(notebook_name: str, path: str = "") -> Dict[str, Any]:
    """노트북 생성"""
    client = get_client()
    try:
        return await client.create_notebook(notebook_name, path)
    finally:
        await client.close()

@mcp.tool()
async def list_notebooks(path: str = "") -> Dict[str, Any]:
    """노트북 목록"""
    client = get_client()
    try:
        return await client.list_notebooks(path)
    finally:
        await client.close()

@mcp.tool()
async def get_notebook_content(notebook_path: str) -> Dict[str, Any]:
    """노트북 내용 조회"""
    client = get_client()
    try:
        return await client.get_notebook_content(notebook_path)
    finally:
        await client.close()

@mcp.tool()
async def delete_notebook(notebook_path: str) -> Dict[str, Any]:
    """노트북 삭제"""
    client = get_client()
    try:
        return await client.delete_notebook(notebook_path)
    finally:
        await client.close()

@mcp.tool()
async def add_cell(notebook_path: str, content: str, cell_type: str = "code") -> Dict[str, Any]:
    """셀 추가"""
    client = get_client()
    try:
        return await client.add_cell(notebook_path, content, cell_type)
    finally:
        await client.close()

@mcp.tool()
async def add_code_blocks(notebook_path: str, content: str, auto_split: bool = True) -> Dict[str, Any]:
    """코드 블록 추가 (자동 분할)"""
    client = get_client()
    try:
        if not auto_split:
            return await client.add_cell(notebook_path, content, "code")
        
        # 코드 분할
        blocks = split_code_into_blocks(content)
        results = []
        
        for i, block in enumerate(blocks):
            if block.strip():
                result = await client.add_cell(notebook_path, block, "code")
                results.append({
                    "block_index": i,
                    "success": result.get("success", False),
                    "position": result.get("position", -1)
                })
        
        return {
            "success": True,
            "message": f"Added {len(blocks)} code blocks",
            "results": results
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await client.close()

@mcp.tool()
async def delete_cell(notebook_path: str, cell_index: int) -> Dict[str, Any]:
    """셀 삭제"""
    client = get_client()
    try:
        return await client.delete_cell(notebook_path, cell_index)
    finally:
        await client.close()

@mcp.tool()
async def execute_cell(notebook_path: str, cell_index: int) -> Dict[str, Any]:
    """셀 실행"""
    client = get_client()
    try:
        return await client.execute_cell_simple(notebook_path, cell_index)
    finally:
        await client.close()

@mcp.tool()
async def add_and_execute_cell(notebook_path: str, content: str) -> Dict[str, Any]:
    """셀 추가 및 실행"""
    client = get_client()
    try:
        return await client.add_and_execute_cell(notebook_path, content)
    finally:
        await client.close()

@mcp.tool()
async def quick_calculation(notebook_path: str, expression: str) -> Dict[str, Any]:
    """빠른 계산 (노트북 생성 및 실행)"""
    client = get_client()
    try:
        # 노트북 생성 (존재하지 않으면)
        notebook_result = await client.get_notebook_content(notebook_path)
        if not notebook_result["success"]:
            notebook_name = notebook_path.split('/')[-1]
            path = '/'.join(notebook_path.split('/')[:-1])
            create_result = await client.create_notebook(notebook_name, path)
            if not create_result["success"]:
                return create_result
        
        # 계산 실행
        return await client.add_and_execute_cell(notebook_path, expression)
        
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await client.close()

@mcp.tool()
async def list_kernels() -> Dict[str, Any]:
    """커널 목록"""
    client = get_client()
    try:
        return await client.list_kernels()
    finally:
        await client.close()

@mcp.tool()
async def start_user_server() -> Dict[str, Any]:
    """사용자 서버 시작"""
    client = get_client()
    try:
        return await client.start_user_server()
    finally:
        await client.close()

# =============================================================================
# 리소스
# =============================================================================

@mcp.resource("jupyter://help")
def get_help() -> str:
    """도움말"""
    return f"""
# JupyterHub MCP Server (Simplified)

## 주요 기능
- 노트북 생성/삭제/조회
- 셀 추가/삭제/실행
- 코드 블록 자동 분할
- 빠른 계산 실행

## 사용 예시

### 기본 사용
```python
# 노트북 생성
create_notebook("test.ipynb")

# 셀 추가 및 실행
add_and_execute_cell("test.ipynb", "print('Hello World')")

# 빠른 계산
quick_calculation("calc.ipynb", "1 + 1")
```

### 코드 블록 분할
```python
# 여러 줄 코드를 자동으로 분할하여 추가
add_code_blocks("analysis.ipynb", '''
import pandas as pd
import numpy as np

data = pd.DataFrame({{'x': [1,2,3], 'y': [4,5,6]}})
result = data.mean()
print(result)
''')
```

Config: {JUPYTERHUB_CONFIG['hub_url']} | {JUPYTERHUB_CONFIG['username']}
"""

# =============================================================================
# 서버 실행
# =============================================================================

if __name__ == "__main__":
    print(f"🚀 {SERVER_NAME} (Simplified)")
    print(f"📍 http://{SERVER_HOST}:{SERVER_PORT}/sse")
    print(f"📝 JupyterHub: {JUPYTERHUB_CONFIG['hub_url']}")
    print(f"👤 User: {JUPYTERHUB_CONFIG['username']}")
    
    print("\n🛠️ Available tools:")
    print("  📓 create_notebook, list_notebooks, delete_notebook")
    print("  📝 add_cell, add_code_blocks, delete_cell")
    print("  ⚡ execute_cell, add_and_execute_cell, quick_calculation")
    print("  🔧 list_kernels, start_user_server")
    
    print("\n📡 Starting server...")
    mcp.run(transport="sse", host=SERVER_HOST, port=SERVER_PORT)