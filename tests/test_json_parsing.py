"""Test JSON parsing error handling in our MCP proxy client and server."""

import asyncio
import json
import logging
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sse_client import ErrorResponse, CapabilityAwareClientSession

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class MockReadStream:
    def __init__(self, should_raise=False):
        self.should_raise = should_raise
        
    async def read(self):
        if self.should_raise:
            # Simulate JSON parsing error at position 4 (column 5)
            raise json.JSONDecodeError("Unexpected non-whitespace character after JSON", "{abc}", 4)
        return {"jsonrpc": "2.0", "result": {"success": True}, "id": 1}

class MockWriteStream:
    async def write(self, data):
        logger.debug(f"Mock write: {data}")

async def test_json_error_handling():
    """Test how our session handles JSON parsing errors."""
    logger.info("Testing JSON error handling in client session")
    
    # Test case 1: Normal operation
    logger.info("Test case 1: Normal JSON operation")
    read_stream = MockReadStream(should_raise=False)
    write_stream = MockWriteStream()
    
    session = CapabilityAwareClientSession(read_stream, write_stream)
    result = await session._send_request("test/method")
    logger.info(f"Normal operation result: {result}")
    assert result == {"success": True}, "Normal operation should return successful result"
    
    # Test case 2: JSON parsing error
    logger.info("Test case 2: JSON parsing error handling")
    read_stream_with_error = MockReadStream(should_raise=True)
    write_stream = MockWriteStream()
    
    session = CapabilityAwareClientSession(read_stream_with_error, write_stream)
    result = await session._send_request("test/method")
    
    logger.info(f"Error handling result: {result}")
    assert isinstance(result, ErrorResponse), "Should return an ErrorResponse object"
    assert result.code == -32700, "Should have the JSON parsing error code"
    assert "JSON parsing error" in result.message, "Should contain JSON parsing error message"
    
    logger.info("All tests passed!")

if __name__ == "__main__":
    asyncio.run(test_json_error_handling()) 