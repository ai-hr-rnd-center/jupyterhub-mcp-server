import os
import time
from fastmcp import FastMCP
from dotenv import load_dotenv
from jupyterhub_client import JupyterHubClient

# 환경변수 로드
load_dotenv()

# 서버 설정
SERVER_NAME = "JupyterHub MCP Server"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# JupyterHub 설정
JUPYTERHUB_URL = os.getenv("JUPYTERHUB_URL", "http://localhost:8000/hub")
JUPYTERHUB_TOKEN = os.getenv("JUPYTERHUB_API_TOKEN", "your_token_here")
JUPYTERHUB_USER = os.getenv("JUPYTERHUB_USERNAME", "your_username")

# MCP 서버 생성
mcp = FastMCP(SERVER_NAME)

def get_client():
    """클라이언트 생성"""
    return JupyterHubClient(JUPYTERHUB_URL, JUPYTERHUB_TOKEN, JUPYTERHUB_USER)

# =============================================================================
# 기본 도구들
# =============================================================================

@mcp.tool()
def get_server_status():
    """서버 상태"""
    return {
        "status": "running",
        "version": "1.0.0",
        "hub_url": JUPYTERHUB_URL,
        "username": JUPYTERHUB_USER,
        "timestamp": time.time()
    }

@mcp.tool()
async def create_notebook(notebook_name: str, path: str = ""):
    """노트북 생성"""
    client = get_client()
    try:
        result = await client.create_notebook(notebook_name, path)
        return result
    finally:
        await client.close()

@mcp.tool()
async def add_cell(notebook_path: str, content: str, cell_type: str = "code"):
    """셀 추가"""
    client = get_client()
    try:
        result = await client.add_cell(notebook_path, content, cell_type)
        return result
    finally:
        await client.close()

@mcp.tool()
async def list_notebooks(path: str = ""):
    """노트북 목록"""
    client = get_client()
    try:
        result = await client.list_notebooks(path)
        return result
    finally:
        await client.close()

@mcp.tool()
async def delete_notebook(notebook_path: str):
    """노트북 삭제"""
    client = get_client()
    try:
        result = await client.delete_notebook(notebook_path)
        return result
    finally:
        await client.close()

@mcp.tool()
async def start_user_server():
    """사용자 서버 시작"""
    client = get_client()
    try:
        result = await client.start_user_server()
        return result
    finally:
        await client.close()

@mcp.tool()
async def quick_calculation(notebook_name: str, expression: str):
    """빠른 계산"""
    client = get_client()
    try:
        # 노트북 생성
        create_result = await client.create_notebook(notebook_name)
        if not create_result["success"]:
            return create_result
        
        # 계산 셀 추가
        add_result = await client.add_cell(f"{notebook_name}.ipynb", expression, "code")
        return {
            "success": True,
            "message": f"Added calculation: {expression}",
            "notebook": f"{notebook_name}.ipynb",
            "expression": expression,
            "create_result": create_result,
            "add_result": add_result
        }
    finally:
        await client.close()

# =============================================================================
# 리소스
# =============================================================================

@mcp.resource("jupyter://help")
def get_help():
    """도움말"""
    return f"""
# JupyterHub MCP Server

## 설정
- Hub URL: {JUPYTERHUB_URL}
- Username: {JUPYTERHUB_USER}
- Server: {SERVER_HOST}:{SERVER_PORT}

## 사용법

### 1+1 계산 예시
```python
quick_calculation("calc", "1 + 1")
```

### 단계별 사용
```python
# 1. 노트북 생성
create_notebook("test")

# 2. 셀 추가
add_cell("test.ipynb", "result = 1 + 1\\nprint(result)")

# 3. 목록 확인
list_notebooks()
```

## 도구 목록
- get_server_status()
- create_notebook(name, path)
- add_cell(notebook_path, content, cell_type)
- list_notebooks(path)
- delete_notebook(notebook_path)
- start_user_server()
- quick_calculation(notebook_name, expression)
"""

# =============================================================================
# 서버 실행
# =============================================================================

if __name__ == "__main__":
    print(f"🚀 {SERVER_NAME}")
    print(f"📍 http://{SERVER_HOST}:{SERVER_PORT}/sse")
    print(f"📝 JupyterHub: {JUPYTERHUB_URL}")
    print(f"👤 User: {JUPYTERHUB_USER}")
    
    print("\n🛠️ Tools:")
    print("  - create_notebook")
    print("  - add_cell")
    print("  - list_notebooks")
    print("  - delete_notebook")
    print("  - start_user_server")
    print("  - quick_calculation")
    
    print("\n📡 Starting server...")
    
    mcp.run(
        transport="sse",
        host=SERVER_HOST,
        port=SERVER_PORT
    )