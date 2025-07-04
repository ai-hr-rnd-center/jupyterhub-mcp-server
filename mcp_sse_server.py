from fastmcp import FastMCP
import asyncio
import time
import logging
import os
import json
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import httpx

load_dotenv()

# 간단한 로깅
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper()),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

# FastMCP 서버
mcp = FastMCP(SERVER_NAME)

class SimpleJupyterHubClient:
    """간소화된 JupyterHub 클라이언트 - 핵심 기능만"""
    
    def __init__(self, hub_url: str, api_token: str, username: str):
        self.hub_url = hub_url.rstrip('/')
        self.api_token = api_token
        self.username = username
        self.session = None
        
    async def get_session(self):
        if not self.session:
            self.session = httpx.AsyncClient(
                headers={'Authorization': f'token {self.api_token}'},
                timeout=30.0
            )
        return self.session
    
    async def get_server_url(self) -> str:
        """사용자 서버 URL (서버 시작 포함)"""
        try:
            session = await self.get_session()
            
            # 사용자 상태 확인
            response = await session.get(f"{self.hub_url}/hub/api/users/{self.username}")
            if response.status_code == 200:
                user_info = response.json()
                
                # 서버가 없으면 시작
                if not user_info.get("servers", {}).get(""):
                    logger.info("Starting user server...")
                    await session.post(f"{self.hub_url}/hub/api/users/{self.username}/server")
                    await asyncio.sleep(5)
                
                return f"{self.hub_url}/user/{self.username}"
                
        except Exception as e:
            logger.error(f"Server setup error: {e}")
            
        return f"{self.hub_url}/user/{self.username}"
    
    async def create_notebook(self, name: str, path: str = "") -> Dict[str, Any]:
        """노트북 생성"""
        try:
            server_url = await self.get_server_url()
            session = await self.get_session()
            
            full_path = f"{path}/{name}" if path else name
            if not full_path.endswith('.ipynb'):
                full_path += '.ipynb'
            
            notebook = {
                "type": "notebook",
                "content": {
                    "cells": [],
                    "metadata": {},
                    "nbformat": 4,
                    "nbformat_minor": 4
                }
            }
            
            response = await session.put(f"{server_url}/api/contents/{full_path}", json=notebook)
            
            if response.status_code in [200, 201]:
                return {"success": True, "path": full_path, "message": f"Created {name}"}
            else:
                return {"success": False, "error": f"Failed: {response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def list_notebooks(self, path: str = "") -> Dict[str, Any]:
        """노트북 목록 (간소화)"""
        try:
            server_url = await self.get_server_url()
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
    
    async def get_notebook_content(self, notebook_path: str) -> Dict[str, Any]:
        """노트북 내용"""
        try:
            server_url = await self.get_server_url()
            session = await self.get_session()
            
            response = await session.get(f"{server_url}/api/contents/{notebook_path}")
            
            if response.status_code == 200:
                notebook = response.json()
                cells = []
                
                for i, cell in enumerate(notebook.get("content", {}).get("cells", [])):
                    cells.append({
                        "index": i,
                        "type": cell.get("cell_type"),
                        "source": cell.get("source", ""),
                        "outputs": cell.get("outputs", [])
                    })
                
                return {"success": True, "cells": cells, "count": len(cells)}
            else:
                return {"success": False, "error": f"Not found: {response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def add_cell(self, notebook_path: str, content: str, cell_type: str = "code") -> Dict[str, Any]:
        """셀 추가"""
        try:
            server_url = await self.get_server_url()
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
                return {"success": True, "position": position, "message": "Cell added"}
            else:
                return {"success": False, "error": "Save failed"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def execute_cell_simple(self, notebook_path: str, cell_index: int) -> Dict[str, Any]:
        """간단한 셀 실행 (실제 계산 포함)"""
        try:
            server_url = await self.get_server_url()
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
            logger.info(f"Executing: {code[:50]}...")
            
            # 간단한 로컬 실행 (안전한 코드만)
            result = await self._safe_execute(code)
            
            # 결과를 노트북에 저장
            if result["success"]:
                outputs = []
                
                if result.get("output"):
                    outputs.append({
                        "output_type": "stream",
                        "name": "stdout",
                        "text": result["output"]
                    })
                
                if result.get("result") is not None:
                    outputs.append({
                        "output_type": "execute_result",
                        "execution_count": 1,
                        "data": {"text/plain": str(result["result"])},
                        "metadata": {}
                    })
                
                cell["outputs"] = outputs
                cell["execution_count"] = 1
            else:
                # 에러 저장
                cell["outputs"] = [{
                    "output_type": "error",
                    "ename": "ExecutionError",
                    "evalue": result.get("error", "Unknown error"),
                    "traceback": [result.get("error", "Unknown error")]
                }]
            
            # 노트북 저장
            response = await session.put(f"{server_url}/api/contents/{notebook_path}", json=notebook)
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": f"Executed cell {cell_index}",
                    "code": code,
                    "result": result,
                    "outputs": cell["outputs"]
                }
            else:
                return {"success": False, "error": "Failed to save results"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _safe_execute(self, code: str) -> Dict[str, Any]:
        """안전한 코드 실행"""
        import sys
        import io
        import contextlib
        
        try:
            # stdout 캡처
            old_stdout = sys.stdout
            captured_output = io.StringIO()
            
            # 안전한 네임스페이스
            namespace = {
                '__name__': '__main__',
                '__builtins__': {
                    'print': print, 'len': len, 'range': range, 'sum': sum,
                    'max': max, 'min': min, 'abs': abs, 'round': round,
                    'sorted': sorted, 'list': list, 'dict': dict, 'set': set,
                    'tuple': tuple, 'str': str, 'int': int, 'float': float,
                    'bool': bool, 'type': type, 'isinstance': isinstance
                }
            }
            
            # 안전한 수학 라이브러리
            try:
                import math
                namespace['math'] = math
            except:
                pass
            
            result = None
            
            with contextlib.redirect_stdout(captured_output):
                # 코드 실행
                if '\n' in code.strip():
                    # 여러 줄 코드
                    exec(code, namespace)
                    # 마지막 줄이 표현식이면 결과로 사용
                    lines = code.strip().split('\n')
                    last_line = lines[-1].strip()
                    if last_line and not any(last_line.startswith(kw) for kw in 
                                           ['print', 'import', 'from', 'def', 'class', 'if', 'for', 'while', 'try', 'with']):
                        try:
                            result = eval(last_line, namespace)
                        except:
                            pass
                else:
                    # 한 줄 코드
                    try:
                        result = eval(code, namespace)
                    except SyntaxError:
                        exec(code, namespace)
            
            output = captured_output.getvalue()
            
            return {
                "success": True,
                "result": result,
                "output": output
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            sys.stdout = old_stdout
    
    async def add_and_execute_cell(self, notebook_path: str, content: str) -> Dict[str, Any]:
        """셀 추가 + 실행"""
        try:
            # 셀 추가
            add_result = await self.add_cell(notebook_path, content, "code")
            if not add_result["success"]:
                return add_result
            
            # 바로 실행
            position = add_result["position"]
            execute_result = await self.execute_cell_simple(notebook_path, position)
            
            return {
                "success": True,
                "message": "Cell added and executed",
                "add_result": add_result,
                "execute_result": execute_result
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def close(self):
        """정리"""
        if self.session:
            await self.session.aclose()

# 클라이언트 인스턴스
client = SimpleJupyterHubClient(**JUPYTERHUB_CONFIG)

# =============================================================================
# 핵심 MCP 도구들 (간소화)
# =============================================================================

@mcp.tool()
async def create_notebook(name: str, path: str = "") -> Dict[str, Any]:
    """새 노트북을 생성합니다."""
    return await client.create_notebook(name, path)

@mcp.tool()
async def list_notebooks(path: str = "") -> Dict[str, Any]:
    """노트북 목록을 조회합니다."""
    return await client.list_notebooks(path)

@mcp.tool()
async def get_notebook_content(notebook_path: str) -> Dict[str, Any]:
    """노트북 내용을 조회합니다."""
    return await client.get_notebook_content(notebook_path)

@mcp.tool()
async def add_cell(notebook_path: str, content: str, cell_type: str = "code") -> Dict[str, Any]:
    """셀을 추가합니다 (실행하지 않음)."""
    return await client.add_cell(notebook_path, content, cell_type)

@mcp.tool()
async def execute_cell(notebook_path: str, cell_index: int) -> Dict[str, Any]:
    """특정 셀을 실행합니다."""
    return await client.execute_cell_simple(notebook_path, cell_index)

@mcp.tool()
async def add_and_execute_cell(notebook_path: str, content: str) -> Dict[str, Any]:
    """셀을 추가하고 바로 실행합니다."""
    return await client.add_and_execute_cell(notebook_path, content)

@mcp.tool()
def get_server_status() -> Dict[str, Any]:
    """서버 상태를 확인합니다."""
    return {
        "status": "running",
        "version": "3.0.0-clean",
        "timestamp": time.time(),
        "tools": ["create_notebook", "list_notebooks", "get_notebook_content", 
                 "add_cell", "execute_cell", "add_and_execute_cell"],
        "config": {
            "hub_url": JUPYTERHUB_CONFIG["hub_url"],
            "username": JUPYTERHUB_CONFIG["username"]
        }
    }

@mcp.resource("jupyter://help")
def get_help() -> str:
    return f"""
# JupyterHub MCP Server v3.0.0 (Clean)

## 핵심 도구 (6개)

### 노트북 관리
- `create_notebook(name, path)` - 노트북 생성
- `list_notebooks(path)` - 노트북 목록
- `get_notebook_content(notebook_path)` - 노트북 내용 조회

### 셀 작업  
- `add_cell(notebook_path, content, cell_type)` - 셀 추가만
- `execute_cell(notebook_path, cell_index)` - 셀 실행만
- `add_and_execute_cell(notebook_path, content)` - 셀 추가+실행

## 사용 예시

```python
# 노트북 생성
create_notebook("test")

# 셀 추가하고 실행
add_and_execute_cell("test.ipynb", "result = 1 + 1\\nprint(f'Result: {{result}}')")

# 기존 셀 실행
execute_cell("test.ipynb", 0)
```

Config: {JUPYTERHUB_CONFIG['hub_url']} | {JUPYTERHUB_CONFIG['username']}
"""

if __name__ == "__main__":
    print(f"🚀 {SERVER_NAME} v3.0.0 (Clean)")
    print(f"📍 http://{SERVER_HOST}:{SERVER_PORT}/sse")
    print(f"📝 JupyterHub: {JUPYTERHUB_CONFIG['hub_url']}")
    print(f"👤 User: {JUPYTERHUB_CONFIG['username']}")
    
    print("\n🛠️ Core Tools (6):")
    print("  📓 create_notebook, list_notebooks, get_notebook_content")
    print("  📝 add_cell, execute_cell, add_and_execute_cell")
    
    print("\n✨ Improvements:")
    print("  🧹 Removed duplicated functions")
    print("  🔧 Simplified WebSocket (removed)")
    print("  ⚡ Safe local execution")
    print("  📊 Cleaner error handling")
    
    print("\n📡 Starting clean server...")
    mcp.run(transport="sse", host=SERVER_HOST, port=SERVER_PORT)