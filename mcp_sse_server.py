from fastmcp import FastMCP
import asyncio
import time
import logging
import os
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

# 로깅 설정
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)

SERVER_NAME = os.getenv("SERVER_NAME", "JupyterHub MCP Server")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# FastMCP 서버 생성
mcp = FastMCP(SERVER_NAME)

# JupyterHub 설정 (환경에 맞게 수정)
JUPYTERHUB_CONFIG = {
    "hub_url": os.getenv("JUPYTERHUB_URL", "http://localhost:8000"),
    "api_token": os.getenv("JUPYTERHUB_API_TOKEN", "your_api_token_here"),
    "username": os.getenv("JUPYTERHUB_USERNAME", "your_username")
}

async def add_cell_to_jupyterhub(content: str, cell_type: str = "code") -> Dict[str, Any]:
    """JupyterHub 노트북에 셀 추가 (시뮬레이션)"""
    try:
        logger.info(f"Adding {cell_type} cell with content: {content[:50]}...")
        
        # 시뮬레이션: 약간의 지연 후 성공 응답
        await asyncio.sleep(0.5)
        
        return {
            "success": True,
            "message": f"Successfully added {cell_type} cell to notebook",
            "cell_type": cell_type,
            "content_length": len(content),
            "timestamp": time.time(),
            "notebook": "test_notebook.ipynb"
        }
        
    except Exception as e:
        logger.error(f"Error adding cell: {str(e)}")
        return {"success": False, "error": str(e)}

# MCP 도구 정의 - add_cell만
@mcp.tool()
async def add_cell(content: str, cell_type: str = "code") -> Dict[str, Any]:
    """JupyterHub 노트북에 셀을 추가합니다.
    
    Args:
        content: 셀에 추가할 내용
        cell_type: 셀 타입 (code 또는 markdown)
    
    Returns:
        셀 추가 결과
    """
    return await add_cell_to_jupyterhub(content, cell_type)

if __name__ == "__main__":
    print("🚀 Starting JupyterHub Add Cell MCP SSE Server...")
    print(f"📍 Server will be available at: http://localhost:8080/sse")
    print(f"📝 JupyterHub URL: {JUPYTERHUB_CONFIG['hub_url']}")
    print(f"👤 Username: {JUPYTERHUB_CONFIG['username']}")
    print("🔧 Transport: SSE (Server-Sent Events)")
    print("\n🛠️ Available tool:")
    print("  - add_cell(content, cell_type)")
    print("\n📡 Starting server...")
    
    # SSE 방식으로 서버 실행
    mcp.run(
        transport="sse",
        host=SERVER_HOST,
        port=SERVER_PORT
    )