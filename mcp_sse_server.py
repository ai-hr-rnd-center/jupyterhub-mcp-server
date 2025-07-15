from fastmcp import FastMCP
import asyncio
import time
import logging
import os
import json
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import io
import contextlib
import httpx
from python_code_checker import python_code_type_checker, _strip_ansi
from websocket_kernel_manager import WebSocketKernelManager, WebSocketExecutionAdapter

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
DEFAULT_NOTEBOOK = os.getenv("DEFAULT_NOTEBOOK", "session_notebook.ipynb")

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

        self.ws_manager = WebSocketKernelManager(
            hub_url, username, api_token, logger
        )
        self.ws_adapter = WebSocketExecutionAdapter(self.ws_manager)

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
    
    async def ensure_default_notebook(self) -> bool:
        """기본 노트북이 없으면 생성"""
        try:
            server_url = await self.get_server_url()
            session = await self.get_session()
            
            # 노트북 존재 확인
            response = await session.get(f"{server_url}/api/contents/{DEFAULT_NOTEBOOK}")
            
            if response.status_code == 200:
                logger.info(f"Default notebook {DEFAULT_NOTEBOOK} already exists")
                return True
            
            # 노트북이 없으면 생성
            logger.info(f"Creating default notebook: {DEFAULT_NOTEBOOK}")
            
            notebook = {
                "type": "notebook",
                "content": {
                    "cells": [],
                    "metadata": {
                        "kernelspec": {
                            "display_name": "Python 3",
                            "language": "python",
                            "name": "python3"
                        },
                        "language_info": {
                            "name": "python",
                            "version": "3.8.0"
                        }
                    },
                    "nbformat": 4,
                    "nbformat_minor": 4
                }
            }
            
            response = await session.put(f"{server_url}/api/contents/{DEFAULT_NOTEBOOK}", json=notebook)
            
            if response.status_code in [200, 201]:
                logger.info(f"Successfully created {DEFAULT_NOTEBOOK}")
                return True
            else:
                logger.error(f"Failed to create {DEFAULT_NOTEBOOK}: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error ensuring default notebook: {e}")
            return False
    
    # async def list_notebooks(self, path: str = "") -> Dict[str, Any]:
    #     """노트북 목록"""
    #     try:
    #         server_url = await self.get_server_url()
    #         session = await self.get_session()
            
    #         response = await session.get(f"{server_url}/api/contents/{path}")
            
    #         if response.status_code == 200:
    #             contents = response.json()
    #             notebooks = []
                
    #             for item in contents.get("content", []):
    #                 if item.get("type") == "notebook":
    #                     notebooks.append({
    #                         "name": item["name"],
    #                         "path": item["path"]
    #                     })
                
    #             return {"success": True, "notebooks": notebooks, "count": len(notebooks)}
    #         else:
    #             return {"success": False, "error": f"Failed: {response.status_code}"}
                
    #     except Exception as e:
    #         return {"success": False, "error": str(e)}
    
    
    async def add_cell(self, content: str, cell_type: str = "code") -> Dict[str, Any]:
        """기본 노트북에 셀 추가"""
        try:

            # 기본 노트북 존재 확인 및 생성
            if not await self.ensure_default_notebook():
                return {
                    "success": False,
                    "error": f"Failed to ensure default notebook: {DEFAULT_NOTEBOOK}",
                    "position": -1
                }
                        
            server_url = await self.get_server_url()
            session = await self.get_session()
            
            # 노트북 가져오기
            response = await session.get(f"{server_url}/api/contents/{DEFAULT_NOTEBOOK}")
            if response.status_code != 200:
                return {"success": False, "error": f"Default notebook not found: {DEFAULT_NOTEBOOK}", "position": -1}
            
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
                return {"success": True, "position": position, "message": "Added {cell_type} cell at position {position}", "notebook": DEFAULT_NOTEBOOK}
            else:
                return {"success": False, "error": "Failed to save notebook", "position": -1}
                
        except Exception as e:
            return {"success": False, "error": str(e), "position": -1}
    
    async def execute_cell(self, cell_index: int) -> Dict[str, Any]:
        """기본 노트북의 특정 셀 실행"""
        try:

            if not await self.ensure_default_notebook():
                return {
                    "success": False,
                    "error": f"Failed to ensure default notebook: {DEFAULT_NOTEBOOK}",
                    "outputs": [{
                        "output_type": "error",
                        "ename": "NotebookNotFound",
                        "evalue": f"Failed to ensure default notebook: {DEFAULT_NOTEBOOK}",
                        "traceback": [f"Failed to ensure default notebook: {DEFAULT_NOTEBOOK}"]
                    }]
                }
                        
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
                cell["outputs"] = [{
                    "output_type": "error",
                    "ename": "ExecutionError",
                    "evalue": result.get("error", "Unknown error"),
                    "traceback": [result.get("error", "Unknown error")]
                }]
                # cell["outputs"] = outputs
            
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
            
    async def clear_notebook(self) -> Dict[str, Any]:
        """현재 작업 노트북의 모든 셀 삭제"""
        try:
            # 기본 노트북 존재 확인
            if not await self.ensure_default_notebook():
                return {
                    "success": False,
                    "error": f"노트북을 찾을 수 없습니다: {DEFAULT_NOTEBOOK}",
                    "cleared_cells": 0
                }
            
            server_url = await self.get_server_url()
            session = await self.get_session()
            
            # 노트북 가져오기
            response = await session.get(f"{server_url}/api/contents/{DEFAULT_NOTEBOOK}")
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"노트북 읽기 실패: {response.status_code}",
                    "cleared_cells": 0
                }
            
            notebook = response.json()
            
            # 기존 셀 개수 저장
            original_cell_count = len(notebook["content"]["cells"])
            
            # 모든 셀 삭제 (빈 리스트로 교체)
            notebook["content"]["cells"] = []
            
            # 노트북 저장
            response = await session.put(f"{server_url}/api/contents/{DEFAULT_NOTEBOOK}", json=notebook)
            
            if response.status_code == 200:
                logger.info(f"노트북 초기화 완료: {original_cell_count}개 셀 삭제")
                return {
                    "success": True,
                    "message": f"노트북 초기화 완료: {original_cell_count}개 셀이 삭제되었습니다",
                    "cleared_cells": original_cell_count,
                    "notebook": DEFAULT_NOTEBOOK
                }
            else:
                return {
                    "success": False,
                    "error": f"노트북 저장 실패: {response.status_code}",
                    "cleared_cells": 0
                }
                
        except Exception as e:
            logger.error(f"노트북 초기화 오류: {e}")
            return {
                "success": False,
                "error": str(e),
                "cleared_cells": 0
            }
                    
    async def restart_kernel_variables(self) -> Dict[str, Any]:
        """JupyterHub 커널 변수 초기화 (커널 재시작)"""
        try:
            if not self.ws_manager:
                return {
                    "success": False,
                    "error": "WebSocket 커널 매니저가 초기화되지 않았습니다"
                }
            
            # 현재 커널 ID 저장
            old_kernel_id = self.ws_manager._kernel_id
            
            # 커널 재시작 (새로운 커널 생성)
            await self.ws_manager._cleanup()  # 기존 연결 정리
            self.ws_manager._connected = False
            self.ws_manager._kernel_id = None
            self.ws_manager._ws = None
            
            # 새로운 커널로 연결
            success = await self.ws_manager.ensure_connection()
            
            if success:
                new_kernel_id = self.ws_manager._kernel_id
                logger.info(f"커널 재시작 완료: {old_kernel_id} → {new_kernel_id}")
                
                return {
                    "success": True,
                    "message": "커널 변수 초기화 완료: 모든 변수가 삭제되었습니다",
                    "old_kernel_id": old_kernel_id,
                    "new_kernel_id": new_kernel_id
                }
            else:
                return {
                    "success": False,
                    "error": "새로운 커널 연결에 실패했습니다"
                }
                
        except Exception as e:
            logger.error(f"커널 재시작 오류: {e}")
            return {
                "success": False,
                "error": str(e)
            }
                            
    async def reset_all(self) -> Dict[str, Any]:
        """노트북과 커널 모두 완전 초기화"""
        try:
            # 1. 노트북 초기화
            notebook_result = await self.clear_notebook()
            
            if not notebook_result["success"]:
                return {
                    "success": False,
                    "error": f"노트북 초기화 실패: {notebook_result['error']}",
                    "cleared_cells": 0
                }
            
            # 2. 커널 변수 초기화
            kernel_result = await self.restart_kernel_variables()
            
            if not kernel_result["success"]:
                return {
                    "success": False,
                    "error": f"커널 초기화 실패: {kernel_result['error']}",
                    "cleared_cells": notebook_result["cleared_cells"],
                    "partial_success": "노트북은 초기화되었지만 커널 초기화 실패"
                }
            
            logger.info("완전 초기화 완료: 노트북 + 커널")
            return {
                "success": True,
                "message": f"완전 초기화 완료: {notebook_result['cleared_cells']}개 셀 삭제 + 커널 변수 초기화",
                "cleared_cells": notebook_result["cleared_cells"],
                "notebook_reset": True,
                "kernel_reset": True,
                "old_kernel_id": kernel_result.get("old_kernel_id"),
                "new_kernel_id": kernel_result.get("new_kernel_id")
            }
            
        except Exception as e:
            logger.error(f"완전 초기화 오류: {e}")
            return {
                "success": False,
                "error": str(e),
                "cleared_cells": 0
            }                            

    async def _safe_execute(self, code: str) -> Dict[str, Any]:
        return await self.ws_adapter.safe_execute_websocket(code)
    
    async def execute_code(self, content: str) -> Dict[str, Any]:
        """코드 실행 (셀 추가 + 실행)"""
        try:
            try:
                self.python_code_type_checker(content)
            except ValueError as e:
                return {
                    "success": False,
                    "error": f"Code validation failed: {str(e)}",
                    "code": content,
                    "validation_failed": True
                }
                        
            # 셀 추가
            add_result = await self.add_cell(content, "code")
            if not add_result["success"]:
                return add_result
            
            # 바로 실행
            position = add_result["position"]
            execute_result = await self.execute_cell(position)
            
            return {
                "success": True,
                "message": "Code executed successfully",
                "add_result": add_result,
                "execute_result": execute_result,
                "notebook": DEFAULT_NOTEBOOK
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    

    async def get_execution_history(self) -> Dict[str, Any]:
        """기본 노트북 실행 히스토리 조회"""
        try:
            # 기본 노트북 존재 확인 및 생성
            if not await self.ensure_default_notebook():
                return {
                    "success": False,
                    "error": f"Failed to ensure default notebook: {DEFAULT_NOTEBOOK}",
                    "cells": [],
                    "count": 0,
                    "notebook": DEFAULT_NOTEBOOK
                }
            
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

    async def get_kernel_globals(self, as_text: bool = False) -> Dict[str, Any]:
        """WebSocket을 통한 전역 변수 조회"""
        try:
            globals_data = await self.ws_adapter.get_kernel_globals_websocket()
            
            if as_text:
                return {
                    "success": True,
                    "variables": json.dumps(globals_data, ensure_ascii=False, indent=2),
                    "count": len(globals_data),
                    "source": "websocket"
                }
            else:
                return {
                    "success": True,
                    "variables": globals_data,
                    "count": len(globals_data),
                    "source": "websocket"
                }
        except Exception as e:
            logger.error(f"전역 변수 조회 실패: {e}")
            return {
                "success": False,
                "variables": "{}" if as_text else {},
                "count": 0,
                "error": str(e)
            }
        
    async def to_ai_history(self, exclude_empty: bool = True, max_output_length: int = 200) -> Dict[str, Any]:
        """노트북을 AI 대화 히스토리 형태로 변환"""
        
        def _truncate(text, reverse=False):
            """텍스트를 지정된 길이로 자르기"""
            if not text:
                return ""
            msg = "(...truncated)"
            if len(text) > max_output_length:
                if reverse:
                    return msg + text[-max_output_length:]
                else:
                    return text[:max_output_length] + msg
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
                        parts.append(f"[{mime} output]")
                return "\n".join(parts)
            
            elif output_type == 'error':
                traceback = output.get("traceback", [])
                return "[Error] " + _truncate('\n'.join(traceback), reverse=True)
            
            return "[unknown output type]"
        
        try:
            # 노트북 내용 가져오기
            notebook_result = await self.get_execution_history()
            
            if not notebook_result["success"]:
                return {
                    "success": False,
                    "error": notebook_result["error"],
                    "history": [],
                    "count": 0
                }
            
            cells = notebook_result.get("cells", [])
            history = []
            
            for cell in cells:
                cell_type = cell.get("type", "")
                content = cell.get("source", "").strip()
                
                # 빈 셀 제외 옵션
                if exclude_empty and not content:
                    continue
                
                # 역할 결정
                role = None
                if cell_type == "code":
                    role = "assistant"  # 코드 셀 = assistant
                elif cell_type == "markdown":
                    role = "user"       # 마크다운 셀 = user
                
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
                            content += "\n\n# Execution result:\n" + "\n".join(output_texts)
                
                history.append({
                    'role': role,
                    'content': content
                })
            
            return {
                "success": True,
                "history": history,
                "count": len(history),
                "timestamp": time.time(),
                "notebook": DEFAULT_NOTEBOOK
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "history": [],
                "count": 0
            }

    async def close(self):
        """정리"""
        if self.session:
            await self.session.aclose()

# 클라이언트 인스턴스
client = JupyterHubClient(**JUPYTERHUB_CONFIG)

# =============================================================================
# 커널 중심 MCP 도구들
# =============================================================================

@mcp.tool(
    description="현재 작업 노트북에 새로운 코드 셀을 추가하고 즉시 실행합니다. 가장 일반적인 사용 패턴입니다."
)
async def add_and_execute_cell(
    content: str         # 추가하고 실행할 코드 내용
) -> Dict[str, Any]:
    """
    현재 작업 노트북에 새로운 코드 셀을 추가하고 즉시 실행합니다.
    
    Args:
        content: 추가하고 실행할 코드 내용
    
    Returns:
        성공 시: {"success": True, "message": "처리_메시지", "add_result": 추가_결과, "execute_result": 실행_결과}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.execute_code(content)


@mcp.tool(
    description="현재 작업 노트북에 새로운 셀을 추가합니다 (실행하지 않음)."
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
        성공 시: {"success": True, "message": "실행_메시지", "code": "실행된_코드", "result": 실행_결과}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.execute_cell(cell_index)

@mcp.tool(
    description="노트북과 커널을 모두 초기화합니다. 모든 셀을 삭제하고 커널 변수도 초기화하는 완전 초기화입니다."
)
async def reset_all() -> Dict[str, Any]:
    """
    노트북과 커널을 모두 완전히 초기화합니다.
    
    Returns:
        성공 시: {"success": True, "message": "완전 초기화 완료", "cleared_cells": 셀_개수}
        실패 시: {"success": False, "error": "에러_메시지"}
        
    Note:
        - 노트북의 모든 셀이 삭제됩니다
        - 커널의 모든 변수가 초기화됩니다
        - 완전히 새로운 상태로 시작할 수 있습니다
    """
    return await client.reset_all()

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
    return await client.get_kernel_globals(as_text)

@mcp.tool(
    description="현재 노트북을 AI 대화 히스토리 형태로 변환합니다. 셀의 타입을 기반으로 user/assistant 역할을 구분합니다."
)
async def get_ai_history(
    exclude_empty: bool = True,      # 빈 셀 제외 여부
    max_output_length: int = 200     # 출력 텍스트 최대 길이
) -> Dict[str, Any]:
    """
    현재 노트북을 AI 대화 히스토리 형태로 변환합니다.
    
    Args:
        exclude_empty: 빈 셀을 제외할지 여부
        max_output_length: 출력 텍스트의 최대 길이
    
    Returns:
        성공 시: {"success": True, "history": 대화_히스토리, "count": 메시지_개수}
        실패 시: {"success": False, "error": "에러_메시지"}
    """
    return await client.to_ai_history(exclude_empty, max_output_length)


# =============================================================================
# 관리용 도구들 (선택사항 - 필요시에만 사용)
# =============================================================================

# @mcp.tool(
#     description="새로운 Jupyter 노트북 파일을 생성합니다 (관리용 - 기본 작업 노트북과 별도)."
# )
# async def create_notebook(
#     name: str,  # 노트북 이름
#     path: str = ""  # 저장 경로
# ) -> Dict[str, Any]:
#     """
#     새 노트북을 생성합니다 (관리용).
    
#     Args:
#         name: 노트북 이름 (.ipynb 확장자는 자동 추가됨)
#         path: 저장할 경로 (선택사항, 기본값: 루트)
    
#     Returns:
#         성공 시: {"success": True, "path": "생성된_경로", "message": "생성_메시지"}
#         실패 시: {"success": False, "error": "에러_메시지"}
#     """
#     return await client.create_notebook(name, path)

# @mcp.tool(
#     description="지정된 경로의 모든 Jupyter 노트북 목록을 조회합니다 (관리용)."
# )
# async def list_notebooks(
#     path: str = ""  # 조회할 경로
# ) -> Dict[str, Any]:
#     """
#     노트북 목록을 조회합니다 (관리용).
    
#     Args:
#         path: 조회할 경로 (선택사항, 기본값: 루트)
    
#     Returns:
#         성공 시: {"success": True, "notebooks": [노트북_목록], "count": 개수}
#         실패 시: {"success": False, "error": "에러_메시지"}
#     """
#     return await client.list_notebooks(path)

@mcp.tool(
    description="JupyterHub MCP 서버의 현재 상태와 설정 정보를 확인합니다."
)
def get_server_status() -> Dict[str, Any]:
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
        "core_tools": ["add_and_execute_cell", "execute_code", "get_execution_history", "add_cell", "execute_cell"],
        "management_tools": ["create_notebook"],
        "config": {
            "hub_url": JUPYTERHUB_CONFIG["hub_url"],
            "username": JUPYTERHUB_CONFIG["username"]
        }
    }

@mcp.tool(description="현재 WebSocket에서 사용 중인 커널 정보 확인")
async def debug_current_kernel():
    if client.ws_manager:
        return {
            "kernel_id": client.ws_manager._kernel_id,
            "connected": client.ws_manager._connected,
            "ws_url": client.ws_manager._ws_url
        }
    return {"no_kernel_manager": True}

@mcp.resource("jupyter://help")
def get_help() -> str:
    return f"""
# JupyterHub MCP Server v1.0.0

## 🚀 핵심 도구 (5개) - 커널 에이전트용

### 💻 코드 실행
- **add_and_execute_cell(content)** - 셀 추가하고 즉시 실행
  * 가장 일반적인 사용 패턴!
  * 새로운 분석이나 계산을 바로 수행할 때
  * 예: add_and_execute_cell("import pandas as pd\\ndf = pd.read_csv('data.csv')\\nprint(df.shape)")

- **execute_code(content)** - 코드 즉시 실행 (위와 동일)
  * add_and_execute_cell과 같은 기능
  * 예: execute_code("df.head()")

- **get_execution_history()** - 실행 히스토리 조회
  * 이전에 실행한 코드들과 결과 확인할 때
  * 현재 작업 상태 파악할 때

### 📝 셀 관리
- **add_cell(content, cell_type)** - 셀 추가만 (실행 안함)
  * 코드를 준비해두고 나중에 실행할 때
  * 마크다운 문서화할 때

- **execute_cell(cell_index)** - 특정 셀 재실행
  * 이전 코드를 다시 실행할 때
  * 데이터 변경 후 결과 갱신할 때

- **reset_all()** - 노트북 + 커널 완전 초기화 ♻️

## 📁 관리 도구 (선택사항)
- create_notebook(name, path) - 별도 노트북 생성

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

### 3. 작업 히스토리 확인
```python
# 지금까지 실행한 모든 셀 확인
get_execution_history()
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
    
    print("\n🎯 Core Tools (5) - Kernel Agent:")
    print("  💻 add_and_execute_cell ⭐, execute_code")
    print("  📊 get_execution_history")
    print("  📝 add_cell, execute_cell")
    
    print("\n📁 Management Tools (2) - Optional:")
    
    print("\n📡 Starting kernel-focused server...")
    mcp.run(transport="sse", host=SERVER_HOST, port=SERVER_PORT)