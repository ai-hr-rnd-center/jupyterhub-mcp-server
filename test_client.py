import asyncio
import json
from contextlib import AsyncExitStack
from mcp import ClientSession
from mcp.client.sse import sse_client

async def simple_test():
    """간단한 MCP 서버 테스트"""
    
    server_url = "http://localhost:8080/sse"
    
    print("🧪 Simple FastMCP Test")
    print(f"📍 Connecting to: {server_url}")
    print("-" * 40)
    
    try:
        async with AsyncExitStack() as stack:
            # SSE 연결
            read, write = await stack.enter_async_context(sse_client(server_url))
            session = await stack.enter_async_context(ClientSession(read, write))
            
            # 연결 확인
            await session.initialize()
            print("✅ Connected!")
            
            # 1. 서버 상태 확인
            print("\n📊 Server Status:")
            result = await session.call_tool("get_server_status", arguments={})
            status = json.loads(result.content[0].text)
            print(f"  Status: {status['status']}")
            print(f"  Features: {len(status['features'])} tools available")
            
            # 2. 노트북 목록 확인
            print("\n📚 Notebook List:")
            result = await session.call_tool("list_notebooks", arguments={})
            notebooks = json.loads(result.content[0].text)
            if notebooks['success']:
                print(f"  Found {notebooks['count']} notebooks")
            else:
                print(f"  Error: {notebooks.get('error', 'Unknown')}")
            
            # 3. 간단한 셀 추가 테스트
            print("\n📝 Adding a simple cell:")
            test_notebook = "test.ipynb"
            
            # 노트북 생성 (이미 있어도 상관없음)
            await session.call_tool("create_notebook", arguments={"notebook_name": test_notebook})
            
            # 셀 추가
            result = await session.call_tool("add_cell", arguments={
                "notebook_path": test_notebook,
                "content": "print('Hello from MCP!')",
                "cell_type": "code"
            })
            
            cell_result = json.loads(result.content[0].text)
            if cell_result['success']:
                print(f"  ✅ Cell added at position {cell_result['position']}")
            else:
                print(f"  ❌ Failed: {cell_result.get('error')}")
            
            # 4. 코드 블록 분할 테스트
            print("\n🔧 Testing code block split:")
            long_code = """
import numpy as np
import pandas as pd

# Data creation
data = np.random.randn(100, 3)
df = pd.DataFrame(data, columns=['A', 'B', 'C'])

# Analysis
print(df.head())
print(df.describe())
"""
            
            result = await session.call_tool("add_code_blocks", arguments={
                "notebook_path": test_notebook,
                "content": long_code,
                "auto_split": True
            })
            
            blocks_result = json.loads(result.content[0].text)
            if blocks_result['success']:
                print(f"  ✅ Added {blocks_result['successful_blocks']} code blocks")
            else:
                print(f"  ❌ Failed: {blocks_result.get('error')}")
            
            print("\n🎉 Test completed successfully!")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")

def main():
    print("🚀 Starting Simple MCP Test")
    print("Make sure the server is running on http://localhost:8080/sse")
    print()
    
    try:
        asyncio.run(simple_test())
    except KeyboardInterrupt:
        print("\n⛔ Test interrupted by user")
    except Exception as e:
        print(f"💥 Unexpected error: {e}")

if __name__ == "__main__":
    main()