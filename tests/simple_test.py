import sys
import os
import asyncio

# Add the parent directory to sys.path to be able to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server_fetch.server import serve

async def test_fetch_server():
    try:
        # Use Google as a simple test URL
        print("Starting MCP fetch server test...")
        await serve(None, True)  # Ignore robots.txt for testing
    except Exception as e:
        print(f"Error running fetch server: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_fetch_server()) 