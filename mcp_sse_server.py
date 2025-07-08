from fastmcp import FastMCP
import asyncio
import time
import logging
import os
import json
from typing import Dict, Any, List, Optional, Union
from dotenv import load_dotenv
import io
import contextlib
import httpx
from python_code_checker import python_code_type_checker, _strip_ansi

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

# 기본 노트북 경로 (하드코딩)
DEFAULT_NOTEBOOK = os.getenv("DEFAULT_NOTEBOOK", "kernel_workspace.ipynb")

# JupyterHub 설정
JUPYTERHUB_CONFIG = {
    "hub_url": os.getenv("JUPYTERHUB_URL", "http://localhost:8000"),
    "api_token": os.getenv("JUPYTERHUB_API_TOKEN", "your_api_token_here"),
    "username": os.getenv("JUPYTERHUB_USERNAME", "your_username")
}

# FastMCP 서버
mcp = FastMCP(SERVER_NAME)

class JupyterHubClient:
    """JupyterHub 클라이언트"""
    
    def __init__(self, hub_url: str, api_token: str, username: str):
        self.hub_url = hub_url.rstrip('/')
        self.api_token = api_token
        self.username = username
        self.session = None
        
        self.python_code_type_checker = python_code_type_checker
        self.strip_ansi = _strip_ansi     

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
        """노트북 생성 (관리용 - 기본 노트북과 별도)"""
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
        """노트북 목록"""
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
    
    async def get_notebook_content(self) -> Dict[str, Any]:
        """기본 노트북 내용 조회 - 수정된 반환 타입"""
        try:
            server_url = await self.get_server_url()
            session = await self.get_session()
            
            response = await session.get(f"{server_url}/api/contents/{DEFAULT_NOTEBOOK}")
            
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
                
                return {
                    "success": True,
                    "cells": cells,
                    "count": len(cells),
                    "notebook": DEFAULT_NOTEBOOK
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to get notebook: {response.status_code}",
                    "cells": [],
                    "count": 0,
                    "notebook": DEFAULT_NOTEBOOK
                }
                
        except Exception as e:
            logger.error(f"Error getting notebook content: {e}")
            return {
                "success": False,
                "error": str(e),
                "cells": [],
                "count": 0,
                "notebook": DEFAULT_NOTEBOOK
            }
    
    async def add_cell(self, content: str, cell_type: str = "code") -> Dict[str, Any]:
        """기본 노트북에 셀 추가 - 수정된 반환 타입"""
        try:
            server_url = await self.get_server_url()
            session = await self.get_session()
            
            # 노트북 가져오기
            response = await session.get(f"{server_url}/api/contents/{DEFAULT_NOTEBOOK}")
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Default notebook not found: {DEFAULT_NOTEBOOK}",
                    "position": -1
                }
            
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
            response = await session.put(f"{server_url}/api/contents/{DEFAULT_NOTEBOOK}", json=notebook)
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "position": position,
                    "message": f"Added {cell_type} cell at position {position}",
                    "notebook": DEFAULT_NOTEBOOK
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to save notebook",
                    "position": -1
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to add cell: {str(e)}",
                "position": -1
            }
    
    async def execute_cell(self, cell_index: int) -> Dict[str, Any]:
        """기본 노트북의 특정 셀 실행 - 수정된 반환 타입"""
        try:
            server_url = await self.get_server_url()
            session = await self.get_session()
            
            # 노트북 가져오기
            response = await session.get(f"{server_url}/api/contents/{DEFAULT_NOTEBOOK}")
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Default notebook not found: {DEFAULT_NOTEBOOK}",
                    "outputs": [{
                        "output_type": "error",
                        "ename": "NotebookNotFound",
                        "evalue": f"Default notebook not found: {DEFAULT_NOTEBOOK}",
                        "traceback": [f"Default notebook not found: {DEFAULT_NOTEBOOK}"]
                    }]
                }
            
            notebook = response.json()
            cells = notebook["content"]["cells"]
            
            if cell_index >= len(cells):
                return {
                    "success": False,
                    "error": "Cell index out of range",
                    "outputs": [{
                        "output_type": "error",
                        "ename": "IndexError",
                        "evalue": "Cell index out of range",
                        "traceback": ["Cell index out of range"]
                    }]
                }
            
            cell = cells[cell_index]
            if cell["cell_type"] != "code":
                return {
                    "success": False,
                    "error": "Not a code cell",
                    "outputs": [{
                        "output_type": "error",
                        "ename": "CellTypeError",
                        "evalue": "Not a code cell",
                        "traceback": ["Not a code cell"]
                    }]
                }
            
            code = cell["source"]

            try:
                self.python_code_type_checker(code)
            except ValueError as e:
                return {
                    "success": False,
                    "error": f"Code validation failed: {str(e)}",
                    "outputs": [{
                        "output_type": "error",
                        "ename": "ValidationError",
                        "evalue": str(e),
                        "traceback": [f"Code validation failed: {str(e)}"]
                    }]
                }
            
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
                outputs = [{
                    "output_type": "error",
                    "ename": "ExecutionError",
                    "evalue": result.get("error", "Unknown error"),
                    "traceback": [result.get("error", "Unknown error")]
                }]
                cell["outputs"] = outputs
            
            # 노트북 저장
            response = await session.put(f"{server_url}/api/contents/{DEFAULT_NOTEBOOK}", json=notebook)
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": f"Executed cell {cell_index}",
                    "code": code,
                    "outputs": cell["outputs"]
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to save results",
                    "outputs": [{
                        "output_type": "error",
                        "ename": "SaveError",
                        "evalue": "Failed to save results",
                        "traceback": ["Failed to save results"]
                    }]
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "outputs": [{
                    "output_type": "error",
                    "ename": type(e).__name__,
                    "evalue": str(e),
                    "traceback": [str(e)]
                }]
            }
            
    async def _safe_execute(self, code: str) -> Dict[str, Any]:
        """최소한의 로컬 실행"""
        import sys
        import io
        import contextlib
        
        try:
            # stdout 캡처
            old_stdout = sys.stdout
            captured_output = io.StringIO()
            
            # 기본 네임스페이스
            namespace = {
                '__name__': '__main__',
                '__builtins__': __builtins__,  # 기본 내장 함수들 모두 허용
            }
            
            # 자주 사용되는 모듈들 미리 로드
            common_modules = ['math', 'random', 'datetime', 'json', 'time']
            for module_name in common_modules:
                try:
                    namespace[module_name] = __import__(module_name)
                except ImportError:
                    pass
            
            # numpy, pandas도 있으면 로드
            data_modules = ['numpy', 'pandas']
            for module_name in data_modules:
                try:
                    namespace[module_name] = __import__(module_name)
                except ImportError:
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
            
            clean_output = self.strip_ansi(output)

            return {
                "success": True,
                "result": result,
                "output": clean_output,
                "note": "This is local execution for basic operations. For full Jupyter functionality, the code will be executed on JupyterHub kernel."
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "note": "Local execution failed. The code will still be saved to the notebook for JupyterHub kernel execution."
            }
        finally:
            sys.stdout = old_stdout
    
    async def execute_code(self, content: str) -> List[Any]:
        """코드 실행 (셀 추가 + 실행) - 간단한 출력 반환"""
        try:
            try:
                self.python_code_type_checker(content)
            except ValueError as e:
                # 검증 실패시 에러 출력 객체 반환
                return [{
                    "output_type": "error",
                    "ename": "ValidationError",
                    "evalue": str(e),
                    "traceback": [f"Code validation failed: {str(e)}"]
                }]
                        
            # 셀 추가
            add_result = await self.add_cell(content, "code")
            if not add_result["success"]:
                return [{
                    "output_type": "error",
                    "ename": "CellAddError", 
                    "evalue": add_result["error"],
                    "traceback": [add_result["error"]]
                }]
            
            # 바로 실행
            execute_result = await self.execute_cell(add_result["position"])
            return execute_result.get("outputs", [])
            
        except Exception as e:
            return [{
                "output_type": "error",
                "ename": type(e).__name__,
                "evalue": str(e),
                "traceback": [str(e)]
            }]
    
    async def close(self):
        """정리"""
        if self.session:
            await self.session.aclose()

# 클라이언트 인스턴스
client = JupyterHubClient(**JUPYTERHUB_CONFIG)

# =============================================================================
# 커널 중심 MCP 도구들 (notebook_path 제거)
# =============================================================================

@mcp.tool(
    description="현재 작업 노트북에 새로운 코드 셀을 추가하고 즉시 실행합니다. 가장 일반적인 사용 패턴입니다."
)
async def add_and_execute_cell(
    content: str         # 추가하고 실행할 코드 내용
) -> List[Any]:
    """
    현재 작업 노트북에 새로운 코드 셀을 추가하고 즉시 실행합니다.
    
    Args:
        content: 추가하고 실행할 코드 내용
    
    Returns:
        실행 결과 출력 리스트
    """
    return await client.execute_code(content)

@mcp.tool(
    description="Python 코드를 실행합니다. add_and_execute_cell과 동일한 기능입니다."
)
async def execute_code(
    content: str  # 실행할 Python 코드
) -> List[Any]:
    """
    Python 코드를 실행합니다.
    
    Args:
        content: 실행할 Python 코드
    
    Returns:
        실행 결과 출력 리스트
    """
    return await client.execute_code(content)

@mcp.tool(
    description="현재 작업 노트북의 모든 셀 내용과 실행 결과를 조회합니다."
)
async def get_execution_history() -> Dict[str, Any]:
    """
    현재 작업 노트북의 실행 히스토리를 조회합니다.
    
    Returns:
        성공 시: {"success": True, "cells": [셀_목록], "count": 셀_개수, "notebook": "노트북명"}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.get_notebook_content()

@mcp.tool(
    description="현재 작업 노트북에 새로운 셀을 추가합니다."
)
async def add_cell(
    content: str,        # 셀에 입력할 내용
    cell_type: str = "code"  # 셀 타입: "code" 또는 "markdown"
) -> Dict[str, Any]:
    """
    현재 작업 노트북에 새로운 셀을 추가합니다.
    
    Args:
        content: 셀에 추가할 내용 (코드 또는 마크다운)
        cell_type: 셀 타입 ("code" 또는 "markdown", 기본값: "code")
    
    Returns:
        성공 시: {"success": True, "position": 셀_위치, "message": "추가_메시지"}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.add_cell(content, cell_type)

@mcp.tool(
    description="현재 작업 노트북의 특정 셀을 실행합니다."
)
async def execute_cell(
    cell_index: int      # 실행할 셀의 인덱스 (0부터 시작)
) -> Dict[str, Any]:
    """
    현재 작업 노트북의 특정 셀을 실행합니다.
    
    Args:
        cell_index: 실행할 셀의 인덱스 (0부터 시작)
    
    Returns:
        성공 시: {"success": True, "message": "실행_메시지", "code": "실행된_코드", "outputs": 실행_결과}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.execute_cell(cell_index)

# =============================================================================
# 관리용 도구들 (선택사항 - 필요시에만 사용)
# =============================================================================

@mcp.tool(
    description="새로운 Jupyter 노트북 파일을 생성합니다 (관리용 - 기본 작업 노트북과 별도)."
)
async def create_notebook(
    name: str,  # 노트북 이름
    path: str = ""  # 저장 경로
) -> Dict[str, Any]:
    """
    새 노트북을 생성합니다 (관리용).
    
    Args:
        name: 노트북 이름 (.ipynb 확장자는 자동 추가됨)
        path: 저장할 경로 (선택사항, 기본값: 루트)
    
    Returns:
        성공 시: {"success": True, "path": "생성된_경로", "message": "생성_메시지"}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.create_notebook(name, path)

@mcp.tool(
    description="지정된 경로의 모든 Jupyter 노트북 목록을 조회합니다 (관리용)."
)
async def list_notebooks(
    path: str = ""  # 조회할 경로
) -> Dict[str, Any]:
    """
    노트북 목록을 조회합니다 (관리용).
    
    Args:
        path: 조회할 경로 (선택사항, 기본값: 루트)
    
    Returns:
        성공 시: {"success": True, "notebooks": [노트북_목록], "count": 개수}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.list_notebooks(path)

@mcp.tool(
    description="커널의 전역 변수와 함수 목록을 조회합니다. 현재 정의된 변수, 함수, 객체들을 확인할 때 사용하세요."
)
async def get_kernel_globals(
    as_text: bool = False  # JSON 텍스트로 반환할지 여부
) -> Dict[str, Any]:
    """
    커널의 전역 변수와 함수 목록을 조회합니다.
    
    Args:
        as_text: True이면 JSON 텍스트로 반환, False이면 파싱된 객체 반환
    
    Returns:
        dict: 전역변수 정보 (예: {"df": ["DataFrame", "length: 1000"], "x": ["int", 42]})
    """
    # globals() 조회를 위한 특별한 코드
    globals_code = '''
import json
import inspect
import builtins
from types import ModuleType

def _get_globals():
    result = {}
    builtin_names = dir(builtins)

    # Jupyter environment variables
    jupyter_vars = ['In', 'Out', 'exit', 'quit', 'get_ipython', 'display', 'original_ps1', 
                'REPLHooks', 'get_last_command', 'PS1', '_', '_oh', '_dh', '_sh']

    for k, v in globals().items():
        # Skip builtins, private objects, modules, and Jupyter variables
        if (k.startswith('_') or k in builtin_names or 
            isinstance(v, ModuleType) or k in jupyter_vars):
            continue
            
        try:
            # Include docstring for functions
            if inspect.isfunction(v):
                doc = v.__doc__
                doc_summary = doc.split('\\n')[0].strip() if doc else ""
                result[k] = [type(v).__name__, doc_summary]
            # Include value for basic types
            elif isinstance(v, (int, float, bool, str, type(None))):
                result[k] = [type(v).__name__, v]
            # Include length for collections
            elif hasattr(v, '__len__'):
                result[k] = [type(v).__name__, f"length: {len(v)}"]
            # Include type only for other objects
            else:
                result[k] = [type(v).__name__, ""]
        except:
            # Handle errors
            try:
                result[k] = [type(v).__name__, ""]
            except:
                result[k] = ["unknown", ""]

    print(json.dumps(result))

_get_globals()
'''
    
    try:
        # 전역 변수 조회 코드 실행
        outputs = await client.execute_code(globals_code)
        
        # 출력에서 JSON 찾기
        globals_data = {}
        for output in outputs:
            if output.get("output_type") == "stream" and output.get("name") == "stdout":
                try:
                    globals_data = json.loads(output.get("text", "{}"))
                    break
                except json.JSONDecodeError:
                    continue
        
        if as_text:
            return {
                "success": True,
                "globals": json.dumps(globals_data, ensure_ascii=False, indent=2),
                "count": len(globals_data),
                "notebook": DEFAULT_NOTEBOOK
            }
        else:
            return {
                "success": True,
                "globals": globals_data,
                "count": len(globals_data),
                "notebook": DEFAULT_NOTEBOOK
            }
            
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(
    description="현재 노트북을 AI 대화 히스토리 형태로 변환합니다. 셀의 타입을 기반으로 user/assistant 역할을 구분합니다."
)
async def get_ai_history(
    exclude_empty: bool = True,      # 빈 셀 제외 여부
    max_output_length: int = 100,    # 출력 텍스트 최대 길이
    as_text: bool = False            # JSON 텍스트로 반환할지 여부
) -> Dict[str, Any]:
    """
    현재 노트북을 AI 대화 히스토리 형태로 변환합니다.
    
    Args:
        exclude_empty: 빈 셀을 제외할지 여부
        max_output_length: 출력 텍스트의 최대 길이
        as_text: True이면 JSON 텍스트로 반환, False이면 파싱된 객체 반환
    
    Returns:
        성공 시: {"success": True, "history": 대화_히스토리, "count": 메시지_개수}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    
    def _truncate(text, reverse=False):
        """텍스트를 지정된 길이로 자르기"""
        if not text:
            return ""
        msg = "( Truncated )"
        if len(text) > max_output_length:
            if reverse:
                return msg + '\n' + text[::-1][:max_output_length][::-1]
            else:
                return text[:max_output_length] + '\n' + msg
        else:
            return text
    
    def _extract_output_text(output):
        """출력 객체에서 텍스트 추출"""
        output_type = output.get("output_type", "")
        
        if output_type == 'stream':
            return _truncate(output.get("text", ""))
        
        elif output_type in ('execute_result', 'display_data'):
            parts = []
            data = output.get("data", {})
            for mime, content in data.items():
                if mime == 'text/plain':
                    parts.append(_truncate(str(content)))
                else:
                    parts.append(f"[{mime} result exists]")
            return "\n".join(parts)
        
        elif output_type == 'error':
            traceback = output.get("traceback", [])
            return "[Error exists] : " + _truncate('\n'.join(traceback), reverse=True)
        
        return "[unknown output data type exists]"
    
    try:
        # 노트북 내용 가져오기
        notebook_result = await client.get_notebook_content()
        
        if not notebook_result["success"]:
            return notebook_result
        
        cells = notebook_result.get("cells", [])
        history = []
        
        for cell in cells:
            # 메타데이터에서 태그 확인 (현재는 구현되지 않았으므로 기본 로직 사용)
            cell_type = cell.get("type", "")
            content = cell.get("source", "").strip()
            
            # 빈 셀 제외 옵션
            if exclude_empty and not content:
                continue
            
            # 역할 결정 (현재는 간단한 휴리스틱 사용)
            # TODO: 향후 메타데이터 태그 기반으로 개선 필요
            role = None
            if cell_type == "code":
                # 코드 셀은 일반적으로 assistant 역할
                role = "assistant"
            elif cell_type == "markdown":
                # 마크다운 셀은 일반적으로 user 역할
                role = "user"
            
            if role is None:
                continue
            
            # 출력 결과 처리 (코드 셀인 경우)
            if cell_type == "code":
                outputs = cell.get("outputs", [])
                if outputs:
                    output_texts = []
                    for output in outputs:
                        output_text = _extract_output_text(output)
                        if output_text:
                            output_texts.append(output_text)
                    
                    if output_texts:
                        content += "\n\nCode cell execution result:\n" + "\n".join(output_texts)
            
            history.append({
                'role': role,
                'content': content
            })
        
        if as_text:
            return {
                "success": True,
                "history": json.dumps(history, ensure_ascii=False, indent=2),
                "count": len(history),
                "notebook": DEFAULT_NOTEBOOK
            }
        else:
            return {
                "success": True,
                "history": history,
                "count": len(history),
                "notebook": DEFAULT_NOTEBOOK
            }
            
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool(
    description="JupyterHub MCP 서버의 현재 상태와 설정 정보를 확인합니다."
)
async def get_server_status() -> Dict[str, Any]:
    """
    서버 상태를 확인합니다.
    
    Returns:
        서버 상태 정보
    """
    return {
        "status": "running",
        "version": "4.0.0-kernel-focused",
        "timestamp": time.time(),
        "default_notebook": DEFAULT_NOTEBOOK,
        "core_tools": ["add_and_execute_cell", "execute_code", "get_execution_history", "add_cell", "execute_cell", "get_kernel_globals", "get_ai_history"],
        "management_tools": ["create_notebook", "list_notebooks"],
        "config": {
            "hub_url": JUPYTERHUB_CONFIG["hub_url"],
            "username": JUPYTERHUB_CONFIG["username"]
        }
    }

@mcp.resource("jupyter://help")
def get_help() -> str:
    return f"""
# JupyterHub MCP Server v4.0.0 - Kernel Focused

## 🎯 핵심 변경사항
- **DEFAULT_NOTEBOOK**: `{DEFAULT_NOTEBOOK}` (하드코딩)
- **notebook_path 제거**: 모든 도구에서 경로 파라미터 제거
- **커널 중심 접근**: 단일 작업 공간에서 코드 실행

## 🚀 핵심 도구 (8개) - 커널 에이전트용

### 💻 코드 실행
- **add_and_execute_cell(content)** ⭐⭐ - 셀 추가하고 즉시 실행
  * 가장 일반적인 사용 패턴!
  * 새로운 분석이나 계산을 바로 수행할 때
  * 예: add_and_execute_cell("import pandas as pd\\ndf = pd.read_csv('data.csv')\\nprint(df.shape)")

- **execute_code(content)** ⭐ - 코드 즉시 실행 (위와 동일)
  * add_and_execute_cell과 같은 기능
  * 예: execute_code("df.head()")

### 📊 상태 조회
- **get_execution_history()** - 실행 히스토리 조회
  * 이전에 실행한 코드들과 결과 확인할 때
  * 현재 작업 상태 파악할 때

- **get_kernel_globals(as_text=False)** - 전역 변수 조회
  * 현재 정의된 변수, 함수, 객체들 확인할 때
  * 커널 상태 점검할 때
  * 예: get_kernel_globals()

- **get_ai_history(exclude_empty=True, max_output_length=100)** - AI 대화 히스토리
  * 노트북을 대화 형태로 변환할 때
  * AI 에이전트 간 히스토리 공유할 때
  * 예: get_ai_history()

- **get_server_status()** - 서버 상태 확인
  * 서버 설정과 상태 정보 확인할 때

### 📝 셀 관리
- **add_cell(content, cell_type)** - 셀 추가만 (실행 안함)
  * 코드를 준비해두고 나중에 실행할 때
  * 마크다운 문서화할 때

- **execute_cell(cell_index)** - 특정 셀 재실행
  * 이전 코드를 다시 실행할 때
  * 데이터 변경 후 결과 갱신할 때

## 📁 관리 도구 (선택사항)
- create_notebook(name, path) - 별도 노트북 생성
- list_notebooks(path) - 노트북 목록 조회

## 🎯 사용 패턴

### 1. 즉시 코드 실행 (가장 일반적) ⭐
```python
# 바로 실행하고 결과 확인
add_and_execute_cell("print('Hello, World!')")
add_and_execute_cell("import numpy as np\\narr = np.array([1,2,3])\\nprint(arr.mean())")
```

### 2. 단계별 작업
```python
# 1. 코드 준비
add_cell("import pandas as pd\\ndf = pd.read_csv('data.csv')", "code")

# 2. 실행
execute_cell(0)

# 3. 다음 단계
add_and_execute_cell("df.head()")
```

### 3. 상태 조회
```python
# 지금까지 실행한 모든 셀 확인
get_execution_history()

# 현재 정의된 변수들 확인
get_kernel_globals()

# 노트북을 대화 히스토리로 변환
get_ai_history()
```

## 💡 핵심 장점
- **경로 고민 불필요**: 항상 `{DEFAULT_NOTEBOOK}` 사용
- **빠른 실행**: add_and_execute_cell()로 바로 코드 실행
- **커널 네임스페이스 활용**: 변수가 계속 유지됨
- **단순화된 워크플로우**: 경로 관리 없이 코드 실행에 집중

Config: {JUPYTERHUB_CONFIG['hub_url']} | {JUPYTERHUB_CONFIG['username']}
Default Notebook: {DEFAULT_NOTEBOOK}

⚡ **추천**: add_and_execute_cell()을 주로 사용하세요!
"""

if __name__ == "__main__":
    print(f"🚀 {SERVER_NAME} v4.0.0 (Kernel Focused)")
    print(f"📍 http://{SERVER_HOST}:{SERVER_PORT}/sse")
    print(f"📝 JupyterHub: {JUPYTERHUB_CONFIG['hub_url']}")
    print(f"👤 User: {JUPYTERHUB_CONFIG['username']}")
    print(f"📓 Default Notebook: {DEFAULT_NOTEBOOK}")
    
    print("\n🎯 Core Tools (8) - Kernel Agent:")
    print("  💻 add_and_execute_cell ⭐, execute_code")
    print("  📊 get_execution_history, get_kernel_globals, get_ai_history, get_server_status")
    print("  📝 add_cell, execute_cell")
    
    print("\n📁 Management Tools (2) - Optional:")
    print("  📓 create_notebook, list_notebooks")
    
    print("\n✨ Key Changes:")
    print("  🎯 DEFAULT_NOTEBOOK hardcoded")
    print("  🚫 notebook_path parameters removed")
    print("  ⚡ Kernel-focused workflow")
    print("  🧹 Simplified for agents")
    
    print("\n📡 Starting kernel-focused server...")
    mcp.run(transport="sse", host=SERVER_HOST, port=SERVER_PORT)