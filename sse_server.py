"""Create a local SSE server that proxies requests to a stdio MCP server."""

import asyncio
import logging
import json
import re
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
                            
                            # 문자열인 경우 JSON 파싱 시도
                            if isinstance(message, str):
                                try:
                                    # 여러 JSON 객체가 있는지 확인
                                    message_str = message.strip()
                                    # 첫 번째 유효한 JSON 객체만 추출
                                    if message_str.startswith('{') and '}' in message_str:
                                        end_pos = message_str.find('}') + 1
                                        valid_json = message_str[:end_pos]
                                        logger.debug(f"Extracting first JSON object: {valid_json}")
                                        message = json.loads(valid_json)
                                    else:
                                        message = json.loads(message_str)
                                except json.JSONDecodeError as je:
                                    logger.error(f"Failed to parse JSON string: {je}")
                                    # 기존 오류 처리 로직으로 이동
                                    raise
                            
                            # Validate message format (additional validation)
                            if not isinstance(message, dict):
                                logger.error(f"Invalid message format received: {type(message).__name__}")
                                return {
                                    "jsonrpc": "2.0",
                                    "error": {
                                        "code": -32700,
                                        "message": f"Invalid message format: {type(message).__name__}, expected dict"
                                    },
                                    "id": None
                                }
                            
                            # 필수 필드 검증
                            if "jsonrpc" not in message:
                                logger.warning(f"Message missing 'jsonrpc' field: {message}")
                                # 경고만 기록하고 계속 진행
                            
                            return message
                        except json.JSONDecodeError as je:
                            # 상세한 JSON 디코드 오류 처리
                            error_message = str(je)
                            logger.error(f"JSON decode error in received message: {je}")
                            logger.error(f"Error position: {je.pos}, line {je.lineno}, column {je.colno}")
                            
                            # 문서 컨텍스트 로깅 및 복구 시도
                            if hasattr(je, 'doc') and je.doc:
                                context_start = max(0, je.pos - 10)
                                context_end = min(len(je.doc), je.pos + 10)
                                logger.error(f"Document context: '{je.doc[context_start:context_end]}'")
                                
                                # 여러 JSON 객체가 연속된 경우 첫 번째 객체만 추출 시도
                                if je.pos > 0 and je.doc[:je.pos].strip().endswith('}'):
                                    try:
                                        # 첫 번째 유효한 JSON 객체 추출 시도
                                        valid_json = je.doc[:je.pos].strip()
                                        logger.info(f"Attempting to recover first JSON object: {valid_json}")
                                        parsed_message = json.loads(valid_json)
                                        logger.info(f"Successfully recovered JSON object")
                                        return parsed_message
                                    except json.JSONDecodeError:
                                        logger.error("Failed to recover first JSON object")
                            
                            # JSON 오류 응답 반환
                            return {
                                "jsonrpc": "2.0",
                                "error": {
                                    "code": -32700,
                                    "message": f"JSON parsing error at position {je.pos}: {error_message}"
                                },
                                "id": None
                            }
                        except Exception as e:
                            error_message = str(e)
                            if "Unexpected non-whitespace character" in error_message or "JSON" in error_message:
                                logger.error(f"JSON parsing error in received message: {e}")
                                # Log more details about the error context
                                logger.error(f"Error context: {e.__class__.__name__}, Location: {getattr(e, 'pos', 'Unknown')}")
                                
                                # 오류 메시지에서 위치 정보 추출
                                position_match = re.search(r'at position (\d+)', error_message)
                                position = position_match.group(1) if position_match else "unknown"
                                
                                # Return an error notification instead of failing
                                return {
                                    "jsonrpc": "2.0",
                                    "error": {
                                        "code": -32700,
                                        "message": f"JSON parsing error at position {position}: {error_message}"
                                    },
                                    "id": None
                                }
                            
                            # 다른 예외 로깅 개선
                            logger.error(f"Unexpected error in enhanced_receive: {e}")
                            logger.error(f"Error type: {type(e).__name__}")
                            raise
                    
                    # Replace the receive method with our enhanced version
                    read_stream.receive = enhanced_receive
                    
                    # 추가 보호 레이어: write_stream 래핑
                    original_send = write_stream.send
                    
                    async def enhanced_send(data):
                        try:
                            logger.debug(f"Sending message: {data}")
                            return await original_send(data)
                        except Exception as e:
                            logger.error(f"Error sending message: {e}")
                            # 전송 오류는 다시 발생시킵니다 - 이것은 연결 문제를 나타낼 수 있음
                            raise
                    
                    # write_stream.send를 향상된 버전으로 교체
                    write_stream.send = enhanced_send
                    
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