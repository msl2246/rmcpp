"""Create a local server that proxies requests to a remote server over SSE."""

import logging
import asyncio
from typing import Any, Dict, Optional, Set

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.server.stdio import stdio_server

from .proxy_server import create_proxy_server

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
    
    async def _send_request_with_retry(self, method_name: str, *args, **kwargs):
        """Check if method is supported, send request and retry if needed."""
        if not self._is_method_supported(method_name):
            logger.debug(f"Skipping unsupported method: {method_name}")
            return ErrorResponse(code=-32601, message="Method not found")
        
        for attempt in range(self.max_retries + 1):
            try:
                return await super()._send_request(method_name, *args, **kwargs)
            except Exception as e:
                error_message = str(e)
                
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