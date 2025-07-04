import asyncio
import time
import logging
import logging.handlers
import os
import json
from typing import Dict, Any, List, Optional
import httpx

def setup_logging():
    """구조화된 로깅 설정"""
    # 로그 디렉토리 생성
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
    # 로그 레벨 설정
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    # 메인 로거 설정
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level))
    
    # 기존 핸들러 제거 (중복 방지)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 포맷터 설정
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )
    
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # 메인 로그 파일 핸들러 (자동 로테이션)
    file_handler = logging.handlers.RotatingFileHandler(
        filename=f"{log_dir}/server.log",
        maxBytes=50*1024*1024,  # 50MB
        backupCount=7,
        encoding='utf-8'
    )
    file_handler.setFormatter(detailed_formatter)
    file_handler.setLevel(logging.INFO)
    
    # 에러 전용 로그 파일
    error_handler = logging.handlers.RotatingFileHandler(
        filename=f"{log_dir}/error.log", 
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setFormatter(detailed_formatter)
    error_handler.setLevel(logging.ERROR)
    
    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(simple_formatter)
    console_handler.setLevel(getattr(logging, log_level))
    
    # 핸들러 추가
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    logger.addHandler(console_handler)
    
    return logger

# 로깅 설정
logger = setup_logging()

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
            logger.info(f"Getting server URL for user: {self.username}")
            session = await self.get_session()
            
            # JupyterHub API로 사용자 정보 조회
            response = await session.get(f"{self.hub_url}/hub/api/users/{self.username}")
            response.raise_for_status()
            user_info = response.json()
            
            # 서버가 실행 중인지 확인
            if user_info.get("servers", {}).get(""):
                server_url = f"{self.hub_url}/user/{self.username}"
                logger.info(f"User server is running: {server_url}")
                return server_url
            else:
                # 서버가 실행되지 않았다면 시작
                logger.info("User server not running, starting...")
                await self.start_user_server()
                return f"{self.hub_url}/user/{self.username}"
                
        except Exception as e:
            logger.error(f"Error getting user server URL: {str(e)}")
            # 시뮬레이션 모드로 폴백
            return f"{self.hub_url}/user/{self.username}"
    
    async def start_user_server(self) -> Dict[str, Any]:
        """사용자 서버 시작"""
        try:
            logger.info(f"Starting server for user: {self.username}")
            session = await self.get_session()
            
            response = await session.post(f"{self.hub_url}/hub/api/users/{self.username}/server")
            
            if response.status_code in [201, 202]:
                # 서버 시작 대기
                logger.info("Server start request sent, waiting for startup...")
                await asyncio.sleep(5)
                logger.info("User server started successfully")
                return {"success": True, "message": "User server started"}
            else:
                logger.error(f"Failed to start server: HTTP {response.status_code}")
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
            logger.info(f"Adding {cell_type} cell to notebook: {notebook_path} at position {position}")
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            # 먼저 노트북 내용 가져오기
            response = await session.get(f"{server_url}/api/contents/{notebook_path}")
            
            if response.status_code != 200:
                logger.error(f"Notebook not found: {notebook_path} (HTTP {response.status_code})")
                return {"success": False, "error": f"Notebook not found: {notebook_path}"}
            
            notebook = response.json()
            cells = notebook["content"]["cells"]
            
            # 셀 내용 처리 - 다양한 형태의 입력 지원
            if isinstance(content, list):
                # 이미 리스트인 경우
                cell_source = content
            elif isinstance(content, str):
                # 문자열인 경우 - 여러 방법으로 줄바꿈 처리
                if '\\n' in content:
                    # \\n이 문자열로 들어온 경우 (이스케이프된 줄바꿈)
                    cell_source = content.replace('\\n', '\n').split('\n')
                elif '\n' in content:
                    # 실제 줄바꿈이 있는 경우
                    cell_source = content.split('\n')
                else:
                    # 한 줄인 경우에도 리스트로 변환
                    cell_source = [content]
            else:
                # 그 외의 경우 문자열로 변환
                cell_source = [str(content)]
            
            # 빈 줄 제거하지 않음 (Jupyter에서는 빈 줄도 의미가 있을 수 있음)
            # 단, 마지막 빈 줄만 제거 (일반적인 관례)
            while cell_source and cell_source[-1] == '':
                cell_source.pop()
            
            # 새 셀 생성
            new_cell = {
                "cell_type": cell_type,
                "metadata": {},
                "source": cell_source
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
                logger.info(f"Cell added successfully to {notebook_path} at position {position}")
                return {
                    "success": True,
                    "message": f"Cell added to {notebook_path}",
                    "cell_type": cell_type,
                    "position": position,
                    "content_length": len(''.join(cell_source)) if isinstance(cell_source, list) else len(content),
                    "lines_count": len(cell_source) if isinstance(cell_source, list) else 1,
                    "timestamp": time.time()
                }
            else:
                logger.error(f"Failed to update notebook: HTTP {response.status_code}")
                return {"success": False, "error": f"Failed to update notebook: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error adding cell to {notebook_path}: {str(e)}")
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