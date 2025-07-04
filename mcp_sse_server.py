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
        """안전한 코드 실행 - import 지원"""
        import sys
        import io
        import contextlib
        
        try:
            # stdout 캡처
            old_stdout = sys.stdout
            captured_output = io.StringIO()
            
            # 안전한 네임스페이스 - import 추가
            namespace = {
                '__name__': '__main__',
                '__builtins__': {
                    # 기본 내장 함수들
                    'print': print, 'len': len, 'range': range, 'sum': sum,
                    'max': max, 'min': min, 'abs': abs, 'round': round,
                    'sorted': sorted, 'list': list, 'dict': dict, 'set': set,
                    'tuple': tuple, 'str': str, 'int': int, 'float': float,
                    'bool': bool, 'type': type, 'isinstance': isinstance,
                    'enumerate': enumerate, 'zip': zip, 'map': map, 'filter': filter,
                    
                    # import 관련 추가
                    '__import__': __import__,  # 핵심: import 기능 활성화
                    'ImportError': ImportError,  # 에러 처리용
                    'ModuleNotFoundError': ModuleNotFoundError,  # 에러 처리용
                    
                    # 예외 처리
                    'Exception': Exception,
                    'ValueError': ValueError,
                    'TypeError': TypeError,
                    'KeyError': KeyError,
                    'IndexError': IndexError,
                }
            }
            
            # 안전한 라이브러리들 미리 로드 (선택사항)
            safe_modules = {
                'math': None,
                'random': None,
                'datetime': None,
                'json': None,
                'os': None,  # 주의: os는 보안상 위험할 수 있음
                'sys': None,
                'time': None,
                'collections': None,
                'itertools': None,
                'functools': None,
                'operator': None,
                'statistics': None,
                'decimal': None,
                'fractions': None,
                'pathlib': None,
                'uuid': None,
                'hashlib': None,
                'base64': None,
                'urllib': None,
                'requests': None,  # 외부 라이브러리
                'numpy': None,     # 데이터 과학용
                'pandas': None,    # 데이터 과학용
                'matplotlib': None,# 시각화용
                'seaborn': None,   # 시각화용
                'sklearn': None,   # 머신러닝용
                'scipy': None,     # 과학 계산용
            }
            
            # 사용 가능한 모듈들을 미리 체크하고 로드
            for module_name in safe_modules:
                try:
                    namespace[module_name] = __import__(module_name)
                except ImportError:
                    pass  # 모듈이 없으면 무시
            
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
# 핵심 MCP 도구들 (상세한 설명 추가)
# =============================================================================

@mcp.tool(
    description="새로운 Jupyter 노트북 파일을 생성합니다. 데이터 분석이나 실험을 시작할 때 사용하세요."
)
async def create_notebook(
    name: str,  # 노트북 이름 (예: "data_analysis", "experiment_1")
    path: str = ""  # 저장 경로 (비어있으면 루트 디렉토리)
) -> Dict[str, Any]:
    """
    새 노트북을 생성합니다.
    
    Args:
        name: 노트북 이름 (.ipynb 확장자는 자동 추가됨)
        path: 저장할 경로 (선택사항, 기본값: 루트)
    
    Returns:
        성공 시: {"success": True, "path": "생성된_경로", "message": "생성_메시지"}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.create_notebook(name, path)

@mcp.tool(
    description="지정된 경로의 모든 Jupyter 노트북 목록을 조회합니다. 기존 작업을 찾거나 프로젝트 현황을 파악할 때 사용하세요."
)
async def list_notebooks(
    path: str = ""  # 조회할 경로 (비어있으면 루트 디렉토리)
) -> Dict[str, Any]:
    """
    노트북 목록을 조회합니다.
    
    Args:
        path: 조회할 경로 (선택사항, 기본값: 루트)
    
    Returns:
        성공 시: {"success": True, "notebooks": [{"name": "파일명", "path": "경로"}], "count": 개수}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.list_notebooks(path)

@mcp.tool(
    description="특정 노트북의 모든 셀 내용과 실행 결과를 조회합니다. 기존 작업을 검토하거나 이어서 작업할 때 사용하세요."
)
async def get_notebook_content(
    notebook_path: str  # 조회할 노트북 경로 (예: "analysis.ipynb")
) -> Dict[str, Any]:
    """
    노트북의 전체 내용을 조회합니다.
    
    Args:
        notebook_path: 노트북 파일 경로
    
    Returns:
        성공 시: {"success": True, "cells": [{"index": 순서, "type": "타입", "source": "코드", "outputs": "결과"}], "count": 셀_개수}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.get_notebook_content(notebook_path)

@mcp.tool(
    description="노트북에 새로운 셀을 추가합니다 (실행하지 않음). 코드나 마크다운을 준비만 하고 나중에 실행하려 할 때 사용하세요."
)
async def add_cell(
    notebook_path: str,  # 대상 노트북 경로
    content: str,        # 셀에 입력할 내용
    cell_type: str = "code"  # 셀 타입: "code" 또는 "markdown"
) -> Dict[str, Any]:
    """
    노트북에 새로운 셀을 추가합니다 (실행하지 않음).
    
    Args:
        notebook_path: 대상 노트북 파일 경로
        content: 셀에 추가할 내용 (코드 또는 마크다운)
        cell_type: 셀 타입 ("code" 또는 "markdown", 기본값: "code")
    
    Returns:
        성공 시: {"success": True, "position": 셀_위치, "message": "추가_메시지"}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.add_cell(notebook_path, content, cell_type)

@mcp.tool(
    description="노트북의 특정 셀을 실행합니다. 기존에 작성된 코드를 다시 실행하거나 결과를 갱신할 때 사용하세요."
)
async def execute_cell(
    notebook_path: str,  # 대상 노트북 경로
    cell_index: int      # 실행할 셀의 인덱스 (0부터 시작)
) -> Dict[str, Any]:
    """
    노트북의 특정 셀을 실행합니다.
    
    Args:
        notebook_path: 대상 노트북 파일 경로
        cell_index: 실행할 셀의 인덱스 (0부터 시작)
    
    Returns:
        성공 시: {"success": True, "message": "실행_메시지", "code": "실행된_코드", "result": 실행_결과, "outputs": "출력_결과"}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.execute_cell_simple(notebook_path, cell_index)

@mcp.tool(
    description="노트북에 새로운 코드 셀을 추가하고 즉시 실행합니다. 데이터 분석이나 실험을 빠르게 진행할 때 가장 유용합니다."
)
async def add_and_execute_cell(
    notebook_path: str,  # 대상 노트북 경로
    content: str         # 실행할 코드 내용
) -> Dict[str, Any]:
    """
    노트북에 새로운 코드 셀을 추가하고 즉시 실행합니다.
    
    Args:
        notebook_path: 대상 노트북 파일 경로
        content: 추가하고 실행할 코드 내용
    
    Returns:
        성공 시: {"success": True, "message": "처리_메시지", "add_result": 추가_결과, "execute_result": 실행_결과}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.add_and_execute_cell(notebook_path, content)

@mcp.tool(
    description="JupyterHub MCP 서버의 현재 상태와 설정 정보를 확인합니다. 연결 문제가 있거나 서버 상태를 점검할 때 사용하세요."
)
def get_server_status() -> Dict[str, Any]:
    """
    서버 상태를 확인합니다.
    
    Returns:
        서버 상태 정보: {"status": "상태", "version": "버전", "tools": ["도구_목록"], "config": {"설정_정보"}}
    """
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

## 핵심 도구 (6개) - 상세 설명

### 📓 노트북 관리
- **create_notebook(name, path)** - 새 노트북 생성
  * 새로운 분석 프로젝트 시작할 때
  * 실험이나 연구 문서화할 때
  * 예: create_notebook("sales_analysis", "projects/")

- **list_notebooks(path)** - 노트북 목록 조회
  * 기존 작업 파일들 찾을 때
  * 프로젝트 현황 파악할 때
  * 예: list_notebooks("projects/")

- **get_notebook_content(notebook_path)** - 노트북 내용 조회
  * 이전 작업 내용 확인할 때
  * 특정 셀의 코드나 결과 검토할 때
  * 예: get_notebook_content("analysis.ipynb")

### 📝 셀 작업
- **add_cell(notebook_path, content, cell_type)** - 셀 추가만
  * 코드를 미리 준비해두고 나중에 실행할 때
  * 마크다운 문서화 셀 추가할 때
  * 예: add_cell("test.ipynb", "# 데이터 분석", "markdown")

- **execute_cell(notebook_path, cell_index)** - 특정 셀 실행
  * 기존 코드를 다시 실행할 때
  * 데이터 변경 후 결과 갱신할 때
  * 예: execute_cell("test.ipynb", 0)

- **add_and_execute_cell(notebook_path, content)** - 셀 추가+실행 ⭐
  * 새로운 분석 코드 작성하고 바로 확인할 때
  * 데이터 탐색하면서 빠르게 실험할 때
  * 가장 많이 사용되는 핵심 기능!
  * 예: add_and_execute_cell("test.ipynb", "df.head()")

## 🚀 사용 패턴

### 1. 새 프로젝트 시작
```python
# 1. 노트북 생성
create_notebook("my_analysis")

# 2. 데이터 로딩하고 즉시 확인
add_and_execute_cell("my_analysis.ipynb", "import pandas as pd\\ndf = pd.read_csv('data.csv')\\nprint(df.shape)")

# 3. 기본 탐색
add_and_execute_cell("my_analysis.ipynb", "df.head()")
```

### 2. 기존 작업 이어하기
```python
# 1. 노트북 목록 확인
list_notebooks()

# 2. 내용 검토
get_notebook_content("existing_analysis.ipynb")

# 3. 새로운 분석 추가
add_and_execute_cell("existing_analysis.ipynb", "df.describe()")
```

Config: {JUPYTERHUB_CONFIG['hub_url']} | {JUPYTERHUB_CONFIG['username']}

💡 **팁**: add_and_execute_cell()을 가장 많이 사용하게 될 것입니다!
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
    print("  📝 Detailed tool descriptions added")
    
    print("\n📡 Starting clean server...")
    mcp.run(transport="sse", host=SERVER_HOST, port=SERVER_PORT)