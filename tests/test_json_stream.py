"""Test JSON streaming recovery functionality.

This script tests the ability to recover when multiple JSON objects are received in a single stream
without proper separators, which is one of the main causes of "Unexpected non-whitespace character at position X" errors.
"""

import sys
import os
import asyncio
import json
import logging
from typing import Dict, Any, List

# Add the parent directory to sys.path to be able to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sse_client import CapabilityAwareClientSession

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

class TestReadStream:
    """Test read stream that returns predefined responses."""
    
    def __init__(self, responses):
        """Initialize with a list of responses to return."""
        self.responses = responses
        self.call_count = 0
        self.original_read = self.read  # Required for patching in CapabilityAwareClientSession
    
    async def read(self):
        """Return the next response."""
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            logger.debug(f"TestReadStream returning: {response}")
            return response
        
        logger.debug("TestReadStream returning default response")
        return {"jsonrpc": "2.0", "result": "default response", "id": 9999}

class TestWriteStream:
    """Test write stream that records writes."""
    
    def __init__(self):
        """Initialize with an empty list of writes."""
        self.writes = []
    
    async def write(self, data):
        """Record the write and return True."""
        self.writes.append(data)
        return True

async def test_concatenated_json():
    """Test handling of multiple JSON objects concatenated together."""
    logger.info("Testing concatenated JSON handling")
    
    # Test cases for concatenated JSON
    test_cases = [
        {
            "name": "Two objects without separator",
            "input": '{"jsonrpc":"2.0","id":1,"result":{"data":true}}{"jsonrpc":"2.0","id":2,"method":"test"}',
            "expected_first_id": 1
        },
        {
            "name": "Two objects with whitespace",
            "input": '{"jsonrpc":"2.0","id":3,"result":{"data":true}} {"jsonrpc":"2.0","id":4,"method":"test"}',
            "expected_first_id": 3
        },
        {
            "name": "Two objects with newline",
            "input": '{"jsonrpc":"2.0","id":5,"result":{"data":true}}\n{"jsonrpc":"2.0","id":6,"method":"test"}',
            "expected_first_id": 5
        },
        {
            "name": "Valid object followed by invalid content",
            "input": '{"jsonrpc":"2.0","id":7,"result":{"data":true}}invalid',
            "expected_first_id": 7
        }
    ]
    
    success_count = 0
    
    for test_case in test_cases:
        logger.info(f"Running test: {test_case['name']}")
        
        # Create test streams
        read_stream = TestReadStream([test_case["input"]])
        write_stream = TestWriteStream()
        
        # Create client session
        session = CapabilityAwareClientSession(read_stream, write_stream)
        
        try:
            # Send a test request
            result = await session._send_request("test")
            
            # Check the result (now we look for the 'data' field in result instead of ID)
            if isinstance(result, dict) and result.get("data") is True:
                logger.info(f"✓ Test passed: Successfully extracted first JSON object")
                success_count += 1
            else:
                logger.error(f"✗ Test failed: Expected result with data:true, got: {result}")
        except Exception as e:
            logger.error(f"✗ Test failed with exception: {e}")
    
    logger.info(f"Test summary: {success_count}/{len(test_cases)} tests passed")
    return success_count == len(test_cases)

async def test_error_recovery():
    """Test recovery from JSON parsing errors."""
    logger.info("Testing JSON error recovery")
    
    error_test_cases = [
        {
            "name": "Missing closing brace with recoverable content",
            "input": '{"jsonrpc":"2.0","id":1,"result":{"data":true}',
            "should_recover": False
        },
        {
            "name": "Invalid JSON followed by valid JSON",
            "input": 'invalid{"jsonrpc":"2.0","id":2,"result":{"data":true}}',
            "should_recover": False
        },
        {
            "name": "Position 4 error (classic case)",
            "input": '{"jsonrpc":"2.0","result":{"data":false}}{"jsonrpc":"2.0","id":3,"result":{"data":true}}',
            "should_recover": True
        }
    ]
    
    success_count = 0
    
    for test_case in error_test_cases:
        logger.info(f"Running error test: {test_case['name']}")
        
        # Create test streams
        read_stream = TestReadStream([test_case["input"]])
        write_stream = TestWriteStream()
        
        # Create client session
        session = CapabilityAwareClientSession(read_stream, write_stream)
        
        try:
            # Send a test request
            result = await session._send_request("test")
            
            # Check if result is an error response
            if isinstance(result, dict) and "data" in result:
                # 성공적인 결과
                if test_case["should_recover"]:
                    # 검증: data값이 false인지 확인 (Position 4 error 테스트 케이스)
                    if result.get("data") is False:
                        logger.info(f"✓ Test passed: Successfully recovered first JSON object")
                        success_count += 1
                    else:
                        logger.error(f"✗ Test failed: Recovered but got unexpected result: {result}")
                else:
                    logger.error(f"✗ Test failed: Should not have recovered, but got: {result}")
            elif hasattr(result, "code") and result.code == -32700:
                # 파싱 오류
                if not test_case["should_recover"]:
                    logger.info(f"✓ Test passed: Correctly reported error for unrecoverable JSON")
                    success_count += 1
                else:
                    logger.error(f"✗ Test failed: Should have recovered but got error: {result.message}")
            else:
                logger.error(f"✗ Test failed: Unexpected result: {result}")
        except Exception as e:
            logger.error(f"✗ Test failed with exception: {e}")
    
    logger.info(f"Error recovery test summary: {success_count}/{len(error_test_cases)} tests passed")
    return success_count == len(error_test_cases)

async def main():
    """Run all tests."""
    logger.info("Starting JSON streaming tests")
    
    try:
        # Run concatenated JSON tests
        concat_success = await test_concatenated_json()
        
        # Run error recovery tests
        recovery_success = await test_error_recovery()
        
        if concat_success and recovery_success:
            logger.info("All tests passed successfully!")
        else:
            logger.error("Some tests failed. Please check the logs.")
    except Exception as e:
        logger.error(f"Test suite error: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 