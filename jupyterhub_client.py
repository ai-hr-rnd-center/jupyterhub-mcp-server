import asyncio
import logging
import os
from typing import Dict, Any
import httpx

# 간단한 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class JupyterHubClient:
    """매우 간단한 JupyterHub 클라이언트"""
    
    def __init__(self, hub_url: str, api_token: str, username: str):
        self.hub_url = hub_url.rstrip('/')
        self.api_token = api_token
        self.username = username
        self.session = None
        
        # URL 검증
        if not self.hub_url.startswith(('http://', 'https://')):
            self.hub_url = f"http://{self.hub_url}"
        
        logger.info(f"JupyterHub Client initialized: {self.hub_url}")
        
    async def get_session(self):
        """HTTP 세션"""
        if not self.session:
            self.session = httpx.AsyncClient(
                headers={'Authorization': f'token {self.api_token}'},
                timeout=30.0
            )
        return self.session
    
    async def get_user_server_url(self) -> str:
        """사용자 서버 URL"""
        try:
            # 사용자 서버 URL 생성 (간단한 방식)
            if '/hub' in self.hub_url:
                base_url = self.hub_url.replace('/hub', '')
            else:
                base_url = self.hub_url
            
            server_url = f"{base_url}/user/{self.username}"
            logger.info(f"User server URL: {server_url}")
            return server_url
            
        except Exception as e:
            logger.error(f"Error getting server URL: {e}")
            raise
    
    async def create_notebook(self, notebook_name: str, path: str = "") -> Dict[str, Any]:
        """노트북 생성"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            # 노트북 경로
            full_path = f"{path}/{notebook_name}" if path else notebook_name
            if not full_path.endswith('.ipynb'):
                full_path += '.ipynb'
            
            # 기본 노트북 구조
            notebook_content = {
                "type": "notebook",
                "content": {
                    "cells": [],
                    "metadata": {},
                    "nbformat": 4,
                    "nbformat_minor": 4
                }
            }
            
            # 노트북 생성
            response = await session.put(
                f"{server_url}/api/contents/{full_path}",
                json=notebook_content
            )
            
            if response.status_code in [200, 201]:
                return {
                    "success": True,
                    "message": f"Created notebook: {notebook_name}",
                    "path": full_path
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to create notebook: {response.status_code}"
                }
                
        except Exception as e:
            logger.error(f"Error creating notebook: {e}")
            return {"success": False, "error": str(e)}
    
    async def add_cell(self, notebook_path: str, content: str, cell_type: str = "code") -> Dict[str, Any]:
        """셀 추가"""
        try:
            server_url = await self.get_user_server_url()
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
            
            # 노트북 저장
            save_response = await session.put(
                f"{server_url}/api/contents/{notebook_path}",
                json=notebook
            )
            
            if save_response.status_code == 200:
                return {
                    "success": True,
                    "message": f"Added cell to {notebook_path}",
                    "position": len(cells) - 1
                }
            else:
                return {"success": False, "error": "Failed to save notebook"}
                
        except Exception as e:
            logger.error(f"Error adding cell: {e}")
            return {"success": False, "error": str(e)}
    
    async def list_notebooks(self, path: str = "") -> Dict[str, Any]:
        """노트북 목록"""
        try:
            server_url = await self.get_user_server_url()
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
                
                return {
                    "success": True,
                    "notebooks": notebooks,
                    "count": len(notebooks)
                }
            else:
                return {"success": False, "error": f"Failed to list: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error listing notebooks: {e}")
            return {"success": False, "error": str(e)}
    
    async def delete_notebook(self, notebook_path: str) -> Dict[str, Any]:
        """노트북 삭제"""
        try:
            server_url = await self.get_user_server_url()
            session = await self.get_session()
            
            response = await session.delete(f"{server_url}/api/contents/{notebook_path}")
            
            if response.status_code == 204:
                return {"success": True, "message": f"Deleted: {notebook_path}"}
            else:
                return {"success": False, "error": f"Failed to delete: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error deleting notebook: {e}")
            return {"success": False, "error": str(e)}
    
    async def start_user_server(self) -> Dict[str, Any]:
        """사용자 서버 시작"""
        try:
            session = await self.get_session()
            
            # 사용자 상태 확인
            user_response = await session.get(f"{self.hub_url}/api/users/{self.username}")
            
            if user_response.status_code == 200:
                user_data = user_response.json()
                
                if not user_data.get('server'):
                    # 서버 시작
                    start_response = await session.post(f"{self.hub_url}/api/users/{self.username}/server")
                    
                    if start_response.status_code in [200, 201, 202]:
                        # 서버 시작 대기
                        await asyncio.sleep(3)
                        return {"success": True, "message": "Server started"}
                    else:
                        return {"success": False, "error": f"Failed to start server: {start_response.status_code}"}
                else:
                    return {"success": True, "message": "Server already running"}
            else:
                return {"success": False, "error": f"User not found: {user_response.status_code}"}
                
        except Exception as e:
            logger.error(f"Error starting server: {e}")
            return {"success": False, "error": str(e)}
    
    async def close(self):
        """클라이언트 정리"""
        if self.session:
            await self.session.aclose()