"""Create a local SSE server that proxies requests to a stdio MCP server."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal, List, Optional

import uvicorn
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.routing import Mount, Route

from proxy_server import create_proxy_server

logger = logging.getLogger(__name__)

@dataclass
class SseServerSettings:
    """Settings for the server."""
    bind_host: str
    port: int
    allow_origins: List[str] | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

def create_starlette_app(
    mcp_server: Server,
    *,
    allow_origins: List[str] | None = None,
    debug: bool = False,
) -> Starlette:
    """Create a Starlette application that can serve the provided mcp server with SSE."""
    sse = SseServerTransport("/messages/")
    
    async def handle_sse(request: Request) -> None:
        """Handle SSE connections with robust error handling."""
        try:
            logger.debug("Establishing SSE connection")
            async with sse.connect_sse(
                request.scope,
                request.receive,
                request._send,  # noqa: SLF001
            ) as (read_stream, write_stream):
                try:
                    logger.debug("Starting MCP server run")
                    
                    # Enhance read_stream to better handle malformed JSON
                    original_receive = read_stream.receive
                    
                    async def enhanced_receive():
                        try:
                            message = await original_receive()
                            logger.debug(f"Received message: {message}")
                            
                            # Validate message format (additional validation)
                            if not isinstance(message, dict):
                                logger.error(f"Invalid message format received: {message}")
                                return {
                                    "jsonrpc": "2.0",
                                    "error": {
                                        "code": -32700,
                                        "message": f"Invalid message format: not a JSON object"
                                    },
                                    "id": None
                                }
                            
                            return message
                        except Exception as e:
                            error_message = str(e)
                            if "Unexpected non-whitespace character" in error_message or "JSON" in error_message:
                                logger.error(f"JSON parsing error in received message: {e}")
                                # Log more details about the error context
                                logger.error(f"Error context: {e.__class__.__name__}, Location: {getattr(e, 'pos', 'Unknown')}")
                                # Return an error notification instead of failing
                                return {
                                    "jsonrpc": "2.0",
                                    "error": {
                                        "code": -32700,
                                        "message": f"JSON parsing error: {error_message}"
                                    },
                                    "id": None
                                }
                            raise
                    
                    # Replace the receive method with our enhanced version
                    read_stream.receive = enhanced_receive
                    
                    await mcp_server.run(
                        read_stream,
                        write_stream,
                        mcp_server.create_initialization_options(),
                    )
                    logger.info("MCP server run completed normally")
                except Exception as e:
                    logger.error(f"Error in MCP server run: {str(e)}")
                    # Attempt to notify client about the error
                    try:
                        await write_stream.send({
                            "jsonrpc": "2.0",
                            "error": {
                                "code": -32000,
                                "message": f"Server error: {str(e)}"
                            },
                            "id": None
                        })
                    except Exception as send_error:
                        logger.error(f"Failed to send error to client: {str(send_error)}")
        except Exception as e:
            logger.error(f"SSE connection error: {str(e)}")
    
    middleware: List[Middleware] = []
    if allow_origins is not None:
        middleware.append(
            Middleware(
                CORSMiddleware,
                allow_origins=allow_origins,
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        )
    
    return Starlette(
        debug=debug,
        middleware=middleware,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

async def run_sse_server(
    stdio_params: StdioServerParameters,
    sse_settings: SseServerSettings,
) -> None:
    """Run the stdio client and expose an SSE server with robust error handling.
    
    Args:
        stdio_params: The parameters for the stdio client that spawns a stdio server.
        sse_settings: The settings for the SSE server that accepts incoming requests.
    """
    # Implement retry mechanism for connection issues
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            logger.info(f"Starting stdio client with command: {stdio_params.command}")
            async with stdio_client(stdio_params) as streams:
                try:
                    logger.info("Creating client session")
                    async with ClientSession(*streams) as session:
                        try:
                            logger.info("Creating proxy server")
                            mcp_server = await create_proxy_server(session)
                            
                            # Bind SSE request handling to MCP server
                            logger.info("Creating Starlette app")
                            starlette_app = create_starlette_app(
                                mcp_server,
                                allow_origins=sse_settings.allow_origins,
                                debug=(sse_settings.log_level == "DEBUG"),
                            )
                            
                            # Configure HTTP server
                            logger.info(f"Starting HTTP server on {sse_settings.bind_host}:{sse_settings.port}")
                            config = uvicorn.Config(
                                starlette_app,
                                host=sse_settings.bind_host,
                                port=sse_settings.port,
                                log_level=sse_settings.log_level.lower(),
                            )
                            http_server = uvicorn.Server(config)
                            await http_server.serve()
                            return  # Normal exit
                            
                        except Exception as e:
                            logger.error(f"Error in proxy server: {str(e)}")
                            raise
                            
                except Exception as e:
                    logger.error(f"Error in client session: {str(e)}")
                    raise
        
        except asyncio.CancelledError:
            logger.info("Operation cancelled")
            raise
            
        except Exception as e:
            retry_count += 1
            logger.error(f"Error in stdio client (attempt {retry_count}/{max_retries}): {str(e)}")
            
            if retry_count >= max_retries:
                logger.error(f"Maximum retries ({max_retries}) reached, giving up")
                raise
                
            # Wait before retrying with exponential backoff
            wait_time = 1.0 * (2 ** (retry_count - 1))  # 1, 2, 4, 8, ... seconds
            logger.info(f"Retrying in {wait_time:.1f} seconds...")
            await asyncio.sleep(wait_time)