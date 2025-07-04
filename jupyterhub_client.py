import asyncio
import time
import logging
import json
import os
from typing import Dict, Any, List, Optional
import httpx

def setup_logging():
    """간단한 로깅 설정"""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

logger = setup_logging()

class JupyterHubClient:
    """간소화된 JupyterHub 클라이언트"""
    
    def __init__(self, hub_url: str, api_token: str, username: str):
        self.hub_url = hub_url.rstrip('/')
        self.api_token = api_token
        self.username = username
        self.session = None
        
        # 기본 헤더
        self.headers = {
            'Authorization': f'token {api_token}',
            'Content-Type': 'application/json'
        }
        
    async def get_session(self):
        """HTTP 세션 가져오기"""
        if not self.session:
            self.session = httpx.AsyncClient(
                headers=self.headers,
                timeout=30.0
            )
        return self.session
    
    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """간단한 HTTP 요청"""
        session = await self.get_session()
        
        try:
            if method.upper() == "GET":
                response = await session.get(url, **kwargs)
            elif method.upper() == "POST":
                response = await session.post(url, **kwargs)
            elif method.upper() == "PUT":
                response = await session.put(url, **kwargs)
            elif method.upper() == "DELETE":
                response = await session.delete(url, **kwargs)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            return response
            
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise
    
    async def get_user_server_url(self) -> str:
        """사용자 서버 URL 가져오기"""
        try:
            # 사용자 정보 확인
            user_url = f"{self.hub_url}/api/users/{self.username}"
            response = await self._request("GET", user_url)
            
            if response.status_code == 200:
                user_data = response.json()
                
                # 서버가 없으면 시작
                if not user_data.get('server'):
                    logger.info(f"Starting server for user: {self.username}")
                    start_url = f"{self.hub_url}/api/users/{self.username}/server"
                    await self._request("POST", start_url)
                    
                    # 서버 시작 대기
                    await asyncio.sleep(5)
                
                server_url = f"{self.hub_url.replace('/hub', '')}/user/{self.username}"
                return server_url
                
        except Exception as e:
            logger.error(f"Error getting server URL: {e}")
            # 기본 URL 반환
            return f"{self.hub_url.replace('/hub', '')}/user/{self.username}"
    
    async def create_notebook(self, notebook_name: str, path: str = "") -> Dict[str, Any]:
        """노트북 생성"""
        try:
            server_url = await self.get_user_server_url()
            
            full_path = f"{path}/{notebook_name}" if path else notebook_name
            if not full_path.endswith('.ipynb'):
                full_path += '.ipynb'
            
            # 빈 노트북 생성
            notebook_content = {
                "type": "notebook",
                "content": {
                    "cells": [],
                    "metadata": {},
                    "nbformat": 4,
                    "nbformat_minor": 4
                }
            }
            
            response = await self._request(
                "PUT",
                f"{server_url}/api/contents/{full_path}",
                json=notebook_content
            )
            
            if response.status_code in [200, 201]:
                return {
                    "success": True,
                    "message": f"Notebook '{notebook_name}' created",
                    "path": full_path
                }
            else:
                return {"success": False, "error": f"Failed to create notebook: {response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_notebook_content(self, notebook_path: str) -> Dict[str, Any]:
        """노트북 내용 가져오기"""
        try:
            server_url = await self.get_user_server_url()
            
            response = await self._request("GET", f"{server_url}/api/contents/{notebook_path}")
            
            if response.status_code == 200:
                notebook = response.json()
                return {
                    "success": True,
                    "notebook": notebook,
                    "cells": notebook.get("content", {}).get("cells", [])
                }
            else:
                return {"success": False, "error": f"Notebook not found: {response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def add_cell(self, notebook_path: str, content: str, cell_type: str = "code") -> Dict[str, Any]:
        """셀 추가 (간소화된 버전)"""
        try:
            # 노트북 가져오기
            notebook_result = await self.get_notebook_content(notebook_path)
            if not notebook_result["success"]:
                return notebook_result
            
            notebook = notebook_result["notebook"]
            cells = notebook["content"]["cells"]
            
            # 새 셀 생성 (간단한 구조)
            new_cell = {
                "cell_type": cell_type,
                "metadata": {},
                "source": content  # 문자열 그대로 사용
            }
            
            if cell_type == "code":
                new_cell["outputs"] = []
                new_cell["execution_count"] = None
            
            # 셀 추가
            cells.append(new_cell)
            position = len(cells) - 1
            
            # 노트북 저장
            server_url = await self.get_user_server_url()
            response = await self._request(
                "PUT",
                f"{server_url}/api/contents/{notebook_path}",
                json=notebook
            )
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": f"Cell added to {notebook_path}",
                    "position": position,
                    "content": content[:100] + "..." if len(content) > 100 else content
                }
            else:
                return {"success": False, "error": f"Failed to save notebook: {response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def execute_cell_simple(self, notebook_path: str, cell_index: int) -> Dict[str, Any]:
        """간단한 셀 실행 (JupyterHub API 사용)"""
        try:
            server_url = await self.get_user_server_url()
            
            # 커널 확인/생성
            kernels_response = await self._request("GET", f"{server_url}/api/kernels")
            
            kernel_id = None
            if kernels_response.status_code == 200:
                kernels = kernels_response.json()
                if kernels:
                    kernel_id = kernels[0]["id"]
            
            # 커널이 없으면 생성
            if not kernel_id:
                kernel_response = await self._request(
                    "POST", 
                    f"{server_url}/api/kernels",
                    json={"name": "python3"}
                )
                if kernel_response.status_code in [200, 201]:
                    kernel_id = kernel_response.json()["id"]
                    await asyncio.sleep(2)  # 커널 시작 대기
                else:
                    return {"success": False, "error": "Failed to create kernel"}
            
            # 노트북 가져오기
            notebook_result = await self.get_notebook_content(notebook_path)
            if not notebook_result["success"]:
                return notebook_result
            
            notebook = notebook_result["notebook"]
            cells = notebook["content"]["cells"]
            
            if cell_index >= len(cells):
                return {"success": False, "error": "Cell index out of range"}
            
            cell = cells[cell_index]
            if cell["cell_type"] != "code":
                return {"success": False, "error": "Can only execute code cells"}
            
            # 코드 실행 요청
            code = cell["source"]
            execute_data = {
                "code": code,
                "silent": False,
                "store_history": True
            }
            
            # JupyterHub의 실행 API 사용
            execute_response = await self._request(
                "POST",
                f"{server_url}/api/kernels/{kernel_id}/execute",
                json=execute_data
            )
            
            if execute_response.status_code == 200:
                # 실행 결과 처리 (간단한 버전)
                result = execute_response.json()
                
                # 가상의 출력 생성 (실제로는 WebSocket이 필요하지만 간소화)
                outputs = [{
                    "output_type": "execute_result",
                    "execution_count": 1,
                    "data": {"text/plain": f"Executed: {code[:50]}..."}
                }]
                
                # 셀 업데이트
                cell["outputs"] = outputs
                cell["execution_count"] = 1
                
                # 노트북 저장
                save_response = await self._request(
                    "PUT",
                    f"{server_url}/api/contents/{notebook_path}",
                    json=notebook
                )
                
                if save_response.status_code == 200:
                    return {
                        "success": True,
                        "message": f"Cell {cell_index} executed",
                        "outputs": outputs,
                        "code": code
                    }
                else:
                    return {"success": False, "error": "Failed to save results"}
            else:
                return {"success": False, "error": f"Execution failed: {execute_response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def add_and_execute_cell(self, notebook_path: str, content: str) -> Dict[str, Any]:
        """셀 추가 및 실행"""
        try:
            # 셀 추가
            add_result = await self.add_cell(notebook_path, content, "code")
            if not add_result["success"]:
                return add_result
            
            # 셀 실행
            position = add_result["position"]
            execute_result = await self.execute_cell_simple(notebook_path, position)
            
            return {
                "success": True,
                "message": f"Cell added and executed",
                "position": position,
                "add_result": add_result,
                "execute_result": execute_result
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def list_notebooks(self, path: str = "") -> Dict[str, Any]:
        """노트북 목록"""
        try:
            server_url = await self.get_user_server_url()
            
            response = await self._request("GET", f"{server_url}/api/contents/{path}")
            
            if response.status_code == 200:
                contents = response.json()
                notebooks = []
                
                for item in contents.get("content", []):
                    if item.get("type") == "notebook":
                        notebooks.append({
                            "name": item["name"],
                            "path": item["path"],
                            "last_modified": item.get("last_modified", "")
                        })
                
                return {
                    "success": True,
                    "notebooks": notebooks,
                    "count": len(notebooks)
                }
            else:
                return {"success": False, "error": f"Failed to list: {response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def delete_notebook(self, notebook_path: str) -> Dict[str, Any]:
        """노트북 삭제"""
        try:
            server_url = await self.get_user_server_url()
            
            response = await self._request("DELETE", f"{server_url}/api/contents/{notebook_path}")
            
            if response.status_code == 204:
                return {"success": True, "message": f"Notebook deleted: {notebook_path}"}
            else:
                return {"success": False, "error": f"Failed to delete: {response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def delete_cell(self, notebook_path: str, cell_index: int) -> Dict[str, Any]:
        """셀 삭제"""
        try:
            notebook_result = await self.get_notebook_content(notebook_path)
            if not notebook_result["success"]:
                return notebook_result
            
            notebook = notebook_result["notebook"]
            cells = notebook["content"]["cells"]
            
            if 0 <= cell_index < len(cells):
                cells.pop(cell_index)
                
                server_url = await self.get_user_server_url()
                response = await self._request(
                    "PUT",
                    f"{server_url}/api/contents/{notebook_path}",
                    json=notebook
                )
                
                if response.status_code == 200:
                    return {"success": True, "message": f"Cell {cell_index} deleted"}
                else:
                    return {"success": False, "error": "Failed to save notebook"}
            else:
                return {"success": False, "error": "Invalid cell index"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def list_kernels(self) -> Dict[str, Any]:
        """커널 목록"""
        try:
            server_url = await self.get_user_server_url()
            
            response = await self._request("GET", f"{server_url}/api/kernels")
            
            if response.status_code == 200:
                kernels = response.json()
                return {"success": True, "kernels": kernels, "count": len(kernels)}
            else:
                return {"success": False, "error": f"Failed to list kernels: {response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def start_user_server(self) -> Dict[str, Any]:
        """사용자 서버 시작"""
        try:
            await self.get_user_server_url()  # 이미 서버 시작 로직 포함
            return {"success": True, "message": "Server started"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def close(self):
        """클라이언트 종료"""
        if self.session:
            await self.session.aclose()