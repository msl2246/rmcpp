"""Create a local server that proxies requests to a remote server over SSE."""

import logging
import asyncio
import json
import re
import time
import traceback
from typing import Any, Dict, Optional, Set, Union, List

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.server.stdio import stdio_server

from proxy_server import create_proxy_server

logger = logging.getLogger(__name__)

# Define local ErrorResponse since it may not be available in mcp package
class ErrorResponse:
    """Error response from an MCP server."""
    
    def __init__(self, code: int, message: str):
        """Initialize an error response.
        
        Args:
            code: The error code
            message: The error message
        """
        self.code = code
        self.message = message

class CapabilityAwareClientSession(ClientSession):
    """ClientSession with capability awareness to prevent unsupported method calls."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.server_capabilities: Dict[str, Any] = {}
        self.unsupported_methods: Set[str] = set()
        self.max_retries: int = 1
        self.disable_capability_check: bool = False
        self._request_id: int = 0
        
        # Store read and write streams for direct access
        if len(args) >= 2:
            self.read_stream = args[0]
            self.write_stream = args[1]
            
            # Patch the read stream to handle JSON parsing errors
            self._patch_read_stream()
    
    def _patch_read_stream(self):
        """Enhance read_stream to better handle malformed JSON."""
        if not hasattr(self.read_stream, 'original_read'):
            # Store original read method
            self.read_stream.original_read = self.read_stream.read
            
            # Create new enhanced read method
            async def enhanced_read():
                try:
                    result = await self.read_stream.original_read()
                    logger.debug(f"Received response: {result}")

                    # 추가 검증: result가 유효한 dict인지 확인
                    if not isinstance(result, dict):
                        logger.error(f"Invalid response format (not a dict): {type(result)}")
                        error_msg = f"Invalid response format: {type(result).__name__}, expected dict"
                        return {
                            "jsonrpc": "2.0",
                            "error": {
                                "code": -32700,
                                "message": error_msg
                            },
                            "id": self._request_id
                        }
                    
                    # 추가 검증: 필수 필드가 있는지 확인
                    if "jsonrpc" not in result:
                        logger.warning(f"Response missing 'jsonrpc' field: {result}")
                        # 여전히 응답을 처리할 수 있으므로 경고만 기록
                    
                    return result
                except json.JSONDecodeError as je:
                    error_message = str(je)
                    logger.error(f"JSON decode error in read_stream.read(): {je}")
                    logger.error(f"Error position: {je.pos}, line {je.lineno}, column {je.colno}")
                    logger.error(f"Document context: '{je.doc[max(0, je.pos-10):je.pos+10]}'")
                    
                    # 상세한 오류 정보를 포함한 응답 반환
                    return {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32700,
                            "message": f"JSON parsing error at position {je.pos}: {error_message}"
                        },
                        "id": self._request_id
                    }
                except Exception as e:
                    error_message = str(e)
                    logger.error(f"Error in read_stream.read(): {e}")
                    
                    if "Unexpected non-whitespace character" in error_message or "JSON" in error_message:
                        logger.error(f"JSON parsing error in read_stream.read(): {e}")
                        logger.error(f"Error context: {e.__class__.__name__}, Location: {getattr(e, 'pos', 'Unknown')}")
                        
                        # 오류 메시지에서 위치 정보 추출 시도
                        position_match = re.search(r'at position (\d+)', error_message)
                        position = position_match.group(1) if position_match else "unknown"
                        
                        # Return an error object instead of failing
                        return {
                            "jsonrpc": "2.0",
                            "error": {
                                "code": -32700,
                                "message": f"JSON parsing error at position {position}: {error_message}"
                            },
                            "id": self._request_id
                        }
                    raise
            
            # Replace read method with enhanced version
            self.read_stream.read = enhanced_read
    
    def _next_request_id(self) -> int:
        """Generate the next request ID.
        
        Returns:
            Incremented request ID
        """
        self._request_id += 1
        return self._request_id
    
    async def initialize(self):
        """Initialize connection and store server capabilities."""
        response = await super().initialize()
        self.server_capabilities = response.capabilities or {}
        logger.info(f"Server capabilities: {self.server_capabilities}")
        return response
    
    def _is_method_supported(self, method_name: str) -> bool:
        """Check if method is supported based on server capabilities."""
        # Return True always if capability check is disabled
        if self.disable_capability_check:
            return True
            
        # Already verified unsupported methods
        if method_name in self.unsupported_methods:
            return False
            
        # Initialization methods are always supported
        if method_name in ["initialize", "notifications/initialized"]:
            return True
            
        # Capabilities-based validation
        if method_name.startswith("resources/"):
            return bool(getattr(self.server_capabilities, "resources", False))
            
        elif method_name.startswith("prompts/"):
            return bool(getattr(self.server_capabilities, "prompts", False))
            
        elif method_name.startswith("tools/"):
            return bool(getattr(self.server_capabilities, "tools", False))
            
        # Try by default
        return True
    
    async def _send_request(self, method_name: str, *args, **kwargs):
        """Send a request to the MCP server.
        
        This implementation is added to prevent dependency on the parent class's method
        which might not exist in the current version of the MCP SDK being used.
        
        Args:
            method_name: The method name to call
            *args: Positional arguments to pass to the method
            **kwargs: Keyword arguments to pass to the method
            
        Returns:
            The method response
        """
        try:
            # Direct implementation to send RPC request
            # Get the read and write streams from the class
            read_stream = self.read_stream
            write_stream = self.write_stream
            
            # Prepare request data
            request_data = {
                "jsonrpc": "2.0",
                "id": self._next_request_id(),
                "method": method_name,
                "params": kwargs if kwargs else (args[0] if args else {})
            }
            
            # Send request
            await write_stream.write(request_data)
            
            # Wait for response with enhanced error handling
            try:
                response = await read_stream.read()
                # Validate that response is properly formatted
                if not isinstance(response, dict):
                    logger.error(f"Invalid response format: {response}")
                    return ErrorResponse(code=-32700, message=f"Invalid response format: not a JSON object")
            except Exception as json_error:
                logger.error(f"JSON parsing error: {json_error}")
                return ErrorResponse(code=-32700, message=f"JSON parsing error: {str(json_error)}")
            
            # Handle response
            if "error" in response:
                error = response["error"]
                logger.error(f"RPC error: {error}")
                return ErrorResponse(code=error.get("code", 0), message=error.get("message", "Unknown error"))
            
            return response.get("result")
        except Exception as e:
            logger.error(f"Error sending request: {e}")
            raise
    
    async def _send_request_with_retry(self, method_name: str, *args, **kwargs):
        """Check if method is supported, send request and retry if needed."""
        if not self._is_method_supported(method_name):
            logger.debug(f"Skipping unsupported method: {method_name}")
            return ErrorResponse(code=-32601, message="Method not found")
        
        for attempt in range(self.max_retries + 1):
            try:
                # Use our own _send_request implementation instead of parent's
                return await self._send_request(method_name, *args, **kwargs)
            except Exception as e:
                error_message = str(e)
                
                # Log detailed error information for JSON parsing errors
                if "Unexpected non-whitespace character" in error_message or "SyntaxError" in error_message:
                    logger.error(f"JSON parsing error in {method_name}: {error_message}")
                    # Return a proper error response instead of retrying
                    return ErrorResponse(code=-32700, message=f"JSON parsing error: {error_message}")
                
                # Method not found error detection
                if "Method not found" in error_message or "-32601" in error_message:
                    logger.warning(f"Method not supported by server: {method_name}")
                    self.unsupported_methods.add(method_name)
                    return ErrorResponse(code=-32601, message="Method not found")
                
                # Retry if it's not the last attempt
                if attempt < self.max_retries:
                    delay = (attempt + 1) * 0.5  # Incremental delay
                    logger.warning(f"Error calling {method_name}, retrying in {delay:.1f}s ({attempt+1}/{self.max_retries}): {e}")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Failed calling {method_name} after {self.max_retries} retries: {e}")
                    raise
    
    # Override each method to check support and apply retry logic
    async def list_resources(self):
        return await self._send_request_with_retry("resources/list")
    
    async def list_prompts(self):
        return await self._send_request_with_retry("prompts/list")
    
    async def list_tools(self):
        return await self._send_request_with_retry("tools/list")
    
    async def read_resource(self, uri):
        return await self._send_request_with_retry("resources/read", uri)
    
    async def get_prompt(self, name, arguments):
        return await self._send_request_with_retry("prompts/get", name, arguments)
    
    async def call_tool(self, name, arguments):
        return await self._send_request_with_retry("tools/call", name, arguments)


async def run_sse_client(
    url: str, 
    headers: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None
) -> None:
    """Run the SSE client with capability awareness and error handling.

    Args:
        url: The URL to connect to.
        headers: Headers for connecting to MCP server.
        config: Additional configuration options.
    """
    config = config or {}
    headers = headers or {}
    
    logger.info(f"Connecting to SSE server at {url}")
    
    try:
        async with sse_client(url=url, headers=headers) as streams:
            # Create and configure enhanced ClientSession
            session = CapabilityAwareClientSession(*streams)
            session.max_retries = config.get("max_retries", 1)
            session.disable_capability_check = config.get("disable_capability_check", False)
            
            async with session:
                try:
                    logger.info("Creating proxy server")
                    app = await create_proxy_server(session)
                    
                    logger.info("Starting stdio server")
                    async with stdio_server() as (read_stream, write_stream):
                        logger.info("Running proxy server")
                        await app.run(
                            read_stream,
                            write_stream,
                            app.create_initialization_options(),
                        )
                except asyncio.CancelledError:
                    logger.info("Server operation cancelled")
                    raise
                except Exception as e:
                    logger.error(f"Error running proxy server: {e}")
                    raise
    except asyncio.CancelledError:
        logger.info("SSE client operation cancelled")
        raise
    except Exception as e:
        logger.error(f"Error connecting to SSE server: {e}")
        raise