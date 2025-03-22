import sys
import traceback
from mcp_server_fetch import serve
import asyncio

async def test_serve():
    try:
        await serve(None, False)
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_serve()) 