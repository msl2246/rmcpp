"""Specialized test for debugging JSON parsing errors in the MCP proxy.

This script will identify exactly where and why "Unexpected non-whitespace character" errors occur.
"""

import sys
import os
import asyncio
import json
import logging
import re
import traceback
from typing import Dict, Any, Optional, Union, List

# Add the parent directory to sys.path to be able to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sse_client import ErrorResponse, CapabilityAwareClientSession

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

class DebuggingReadStream:
    """A read stream implementation that logs all data transfers and can simulate errors."""
    
    def __init__(self, responses=None, error_on_response=None):
        """Initialize the debugging read stream.
        
        Args:
            responses: List of responses to return in sequence
            error_on_response: Index of response that should cause an error
        """
        self.responses = responses or []
        self.error_on_response = error_on_response
        self.call_count = 0
        self.original_read = None  # For compatibility with patching
    
    async def read(self) -> Union[Dict[str, Any], str, bytes]:
        """Simulate reading a message, with detailed error information."""
        self.call_count += 1
        logger.debug(f"Read called (#{self.call_count})")
        
        if not self.responses:
            response = {"jsonrpc": "2.0", "result": {"status": "ok"}, "id": self.call_count}
            logger.debug(f"Default response: {response}")
            return response
        
        if self.call_count <= len(self.responses):
            response = self.responses[self.call_count - 1]
            
            # If this response should cause an error, simulate it
            if self.error_on_response == self.call_count:
                # If it's a string, we'll raise a JSON parse error
                if isinstance(response, str):
                    logger.debug(f"Simulating JSON parse error with: {response}")
                    # Extract the position information from the JSON string
                    if not response.startswith('{'):
                        error_position = 0
                    else:
                        match = re.search(r'[^,\{\}\"\s\w\d\:_-]', response)
                        error_position = match.start() if match else 4
                    
                    logger.debug(f"Raising JSONDecodeError at position {error_position}")
                    raise json.JSONDecodeError(
                        f"Unexpected non-whitespace character after JSON", 
                        response, 
                        error_position
                    )
                return response
            
            logger.debug(f"Returning response #{self.call_count}: {response}")
            return response
        
        # Default response if we've gone through all prepared responses
        default_response = {"jsonrpc": "2.0", "result": {"status": "complete"}, "id": self.call_count}
        logger.debug(f"End of responses, returning default: {default_response}")
        return default_response

class DebuggingWriteStream:
    """A write stream implementation that logs all writes."""
    
    def __init__(self):
        """Initialize the debugging write stream."""
        self.messages = []
    
    async def write(self, data):
        """Record and log the written data."""
        self.messages.append(data)
        logger.debug(f"Write called with: {data}")
        return True

async def test_different_json_error_patterns():
    """Test various patterns that could trigger the JSON parsing error."""
    logger.info("Testing various JSON error patterns")
    
    # Test cases - different ways JSON parsing can fail
    test_cases = [
        {"name": "Valid JSON", "input": {"key": "value"}, "should_fail": False},
        {"name": "Invalid key (no quotes)", "input": "{key: 'value'}", "should_fail": True},
        {"name": "Missing closing brace", "input": "{\"key\": \"value\"", "should_fail": True},
        {"name": "Extra character", "input": "{\"key\": \"value\"}x", "should_fail": True},
        {"name": "Invalid Unicode", "input": "{\"key\": \"value\\u00xxxx\"}", "should_fail": True},
        {"name": "Control character", "input": "{\"key\": \"value\u0001\"}", "should_fail": True},
        {"name": "Invalid escape", "input": "{\"key\": \"value\\z\"}", "should_fail": True},
        {"name": "Binary content", "input": b'\x00\x01\x02', "should_fail": True},
    ]
    
    for case in test_cases:
        logger.info(f"Test case: {case['name']}")
        
        # Create streams with the test input
        read_stream = DebuggingReadStream(
            responses=[case["input"]], 
            error_on_response=1 if case["should_fail"] else None
        )
        write_stream = DebuggingWriteStream()
        
        try:
            # Create client session and call method
            session = CapabilityAwareClientSession(read_stream, write_stream)
            result = await session._send_request("test/method")
            
            # Check result
            if case["should_fail"]:
                if isinstance(result, ErrorResponse) and result.code == -32700:
                    logger.info(f"✓ Expected error: {result.message}")
                else:
                    logger.error(f"✗ Expected error but got: {result}")
            else:
                if not isinstance(result, ErrorResponse):
                    logger.info(f"✓ Successfully processed: {result}")
                else:
                    logger.error(f"✗ Got unexpected error: {result.message}")
        except Exception as e:
            logger.error(f"Exception during test case '{case['name']}': {str(e)}")
            logger.error(traceback.format_exc())

async def find_problematic_json_patterns():
    """Attempt to find the exact pattern causing issues in the real system."""
    logger.info("Testing common JSON error patterns from real-world cases")
    
    # These patterns are based on real-world errors from logs
    problematic_patterns = [
        '{"jsonrpc":"2.0","id":1,"method":"initialize"}x',  # Extra character after valid JSON
        '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n{"extra":"data"}',  # Multiple JSON objects in stream
        '{jsonrpc:"2.0",id:1,method:"initialize"}',  # Missing quotes around keys
        '{"jsonrpc":"2.0",\n"id":1,\n"method":"initialize"\n}',  # Newlines in JSON
        'undefined',  # Non-JSON content
        '{}abc',  # Valid JSON followed by invalid characters
        '{"jsonrpc":"2.0","id":1,method:"initialize"}',  # Mixed quoting styles
    ]
    
    for i, pattern in enumerate(problematic_patterns):
        logger.info(f"Testing problematic pattern #{i+1}: {pattern[:30]}...")
        
        try:
            read_stream = DebuggingReadStream(responses=[pattern], error_on_response=1)
            write_stream = DebuggingWriteStream()
            
            session = CapabilityAwareClientSession(read_stream, write_stream)
            result = await session._send_request("test/method")
            
            logger.info(f"Result for pattern #{i+1}: {result}")
            if isinstance(result, ErrorResponse):
                logger.info(f"Error code: {result.code}, Message: {result.message}")
        except Exception as e:
            logger.error(f"Exception with pattern #{i+1}: {str(e)}")
            logger.error(f"Pattern content: {pattern}")
            logger.error(traceback.format_exc())

async def test_json_recovery_enhanced():
    """Enhanced test for verifying our JSON error recovery functionality."""
    logger.info("Testing JSON error recovery with simulation of real CapabilityAwareClientSession")
    
    # Create a sequence of responses to simulate real interactions
    responses = [
        {"jsonrpc": "2.0", "result": {"serverInfo": {"name": "Test Server"}, "capabilities": {}}, "id": 1},  # Normal initialize response
        '{"jsonrpc":"2.0","id":2,method:"list_tools"}',  # Malformed JSON in second call
        {"jsonrpc": "2.0", "result": {"tools": []}, "id": 3},  # Normal response after error
    ]
    
    try:
        read_stream = DebuggingReadStream(responses=responses, error_on_response=2)
        write_stream = DebuggingWriteStream()
        
        # Test the complete client session flow
        session = CapabilityAwareClientSession(read_stream, write_stream)
        
        # 1. Initialize
        result = await session._send_request("initialize")
        logger.info(f"Initialize result: {result}")
        
        # 2. Try operation with invalid JSON (should recover)
        result = await session._send_request("tools/list")
        logger.info(f"List tools result (after error): {result}")
        
        if isinstance(result, ErrorResponse):
            assert result.code == -32700, "Should have correct error code"
            logger.info(f"Got expected error code: {result.code}")
        else:
            logger.error(f"Expected ErrorResponse but got: {result}")
        
        # 3. Try another valid operation
        result = await session._send_request("test/another_call")
        logger.info(f"Another call result: {result}")
    except Exception as e:
        logger.error(f"Exception during enhanced recovery test: {str(e)}")
        logger.error(traceback.format_exc())

async def test_position_4_error():
    """Specifically test the 'position 4' error that's been observed."""
    logger.info("Testing cases that may produce the position 4 error")
    
    # Create patterns that might trigger the position 4 error
    position_4_patterns = [
        '{"id":1}data',               # Additional data after valid JSON
        '{"id":1}\n{"id":2}',         # Two JSON objects without separation
        '{"id":1}    {"id":2}',       # Whitespace between JSON objects
        '{"id":1,"x":true}text',      # Text after valid JSON
        '{"id":1}]',                  # Invalid JSON character right after valid JSON
        '{"id":1,"jsonrpc":"2.0"}x',  # 'x' character at position 25
    ]
    
    for i, pattern in enumerate(position_4_patterns):
        logger.info(f"Testing position 4 pattern #{i+1}: {pattern}")
        
        try:
            # First check what json.loads() does with this pattern
            try:
                parsed = json.loads(pattern)
                logger.info(f"Direct JSON loads result: {parsed}")
            except json.JSONDecodeError as je:
                logger.info(f"JSON loads error: {je}")
                logger.info(f"Error position: {je.pos}, line: {je.lineno}, column: {je.colno}")
                # Extract context around the error
                start = max(0, je.pos - 10)
                end = min(len(pattern), je.pos + 10)
                logger.info(f"Context: '{pattern[start:end]}'")
                logger.info(f"Position: {' ' * (min(10, je.pos) - start)}^")
            
            # Now test with our client session
            read_stream = DebuggingReadStream(responses=[pattern], error_on_response=1)
            write_stream = DebuggingWriteStream()
            
            session = CapabilityAwareClientSession(read_stream, write_stream)
            result = await session._send_request("test/method")
            
            if isinstance(result, ErrorResponse):
                logger.info(f"Client session result: Error {result.code} - {result.message}")
            else:
                logger.info(f"Client session result: {result}")
                
        except Exception as e:
            logger.error(f"Exception with position 4 pattern #{i+1}: {str(e)}")
            logger.error(traceback.format_exc())

async def main():
    """Run all tests."""
    logger.info("Starting JSON parsing error tests")
    
    try:
        await test_different_json_error_patterns()
        logger.info("\n")
        
        await find_problematic_json_patterns()
        logger.info("\n")
        
        await test_json_recovery_enhanced()
        logger.info("\n")
        
        await test_position_4_error()
        logger.info("\n")
        
        logger.info("All tests completed")
    except Exception as e:
        logger.error(f"Error in main test sequence: {str(e)}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(main()) 