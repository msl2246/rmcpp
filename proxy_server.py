"""Create an MCP server that proxies requests through an MCP client.

This server is created independent of any transport mechanism.
"""

import typing as t
import logging
import json
import re
import traceback
from mcp import server, types
from mcp.client.session import ClientSession

logger = logging.getLogger(__name__)

def get_capability(capabilities: t.Any, path: str) -> bool:
    """Safely access capability attributes.
    
    Args:
        capabilities: Server capabilities object
        path: Attribute path with '.' separator (e.g., 'resources.subscribe')
    
    Returns:
        Whether the capability is supported (False if uncertain)
    """
    if not capabilities:
        return False
        
    obj = capabilities
    for part in path.split('.'):
        if not hasattr(obj, part):
            return False
        obj = getattr(obj, part)
    
    return bool(obj)

async def create_proxy_server(remote_app: ClientSession) -> server.Server:  # noqa: C901
    """Create a server instance from a remote app."""
    try:
        response = await remote_app.initialize()
        capabilities = response.capabilities
        server_name = response.serverInfo.name
        server_version = getattr(response.serverInfo, 'version', 'unknown')
        
        logger.info(f"Creating proxy server for {server_name} v{server_version}")
        logger.debug(f"Server capabilities: {capabilities}")

        app = server.Server(server_name)

        # Enhanced error handler wrapper for request handlers
        def create_error_handler(handler_fn):
            async def wrapped_handler(req):
                try:
                    return await handler_fn(req)
                except Exception as e:
                    error_message = str(e)
                    logger.error(f"Error in handler: {e}")
                    
                    # Enhanced JSON parsing error detection and detailed logging
                    if ("Unexpected non-whitespace character" in error_message or 
                        "JSON" in error_message or 
                        "SyntaxError" in error_message):
                        
                        # 상세한 오류 정보 로깅
                        logger.error(f"JSON parsing error details: {e.__class__.__name__}")
                        logger.error(f"Error message: {error_message}")
                        
                        # 스택 트레이스 로깅
                        tb_str = ''.join(traceback.format_tb(e.__traceback__))
                        logger.error(f"Stack trace:\n{tb_str}")
                        
                        # 직렬화 도중 예외가 발생한 경우 원본 데이터 로깅 시도
                        if hasattr(e, 'doc'):
                            # JSONDecodeError인 경우
                            pos = getattr(e, 'pos', 0)
                            context_start = max(0, pos - 20)
                            context_end = min(len(e.doc), pos + 20)
                            logger.error(f"JSON document context around position {pos}: '{e.doc[context_start:context_end]}'")
                            
                            # 오류 위치 표시
                            pos_marker = ' ' * (min(20, pos) - context_start) + '^'
                            logger.error(f"Error position: {pos_marker}")
                            
                            # 복구 시도: 여러 JSON 객체가 연속된 경우
                            if pos > 0 and e.doc[:pos].strip().endswith('}'):
                                try:
                                    # 첫 번째 유효한 JSON 객체 추출 시도
                                    valid_json = e.doc[:pos].strip()
                                    logger.info(f"Attempting to recover JSON: {valid_json}")
                                    parsed_data = json.loads(valid_json)
                                    logger.info(f"Successfully recovered JSON object")
                                    # 복구된 데이터로 요청 처리 재시도
                                    return await handler_fn(req)
                                except Exception as recovery_error:
                                    logger.error(f"Failed to recover: {recovery_error}")
                        
                        # 위치 정보 추출
                        pos_info = ""
                        if hasattr(e, 'pos'):
                            pos_info = f" at position {e.pos}"
                            if hasattr(e, 'lineno') and hasattr(e, 'colno'):
                                pos_info += f" (line {e.lineno}, column {e.colno})"
                        elif hasattr(e, 'doc') and hasattr(e, 'pos'):
                            pos_info = f" at position {e.pos}"
                        else:
                            # 오류 메시지에서 위치 정보 추출 시도
                            pos_match = re.search(r'at position (\d+)', error_message)
                            if pos_match:
                                pos_info = f" at position {pos_match.group(1)}"
                        
                        # Return a proper error response for JSON parsing errors
                        return types.ServerResult(
                            types.ErrorResponse(
                                code=-32700, 
                                message=f"JSON parsing error{pos_info}: {error_message}"
                            )
                        )
                    # Re-raise all other exceptions
                    raise
            return wrapped_handler

        # prompts capabilities handling
        if get_capability(capabilities, 'prompts'):
            logger.info(f"Server {server_name} supports prompts")

            async def _list_prompts(_: t.Any) -> types.ServerResult:  # noqa: ANN401
                try:
                    result = await remote_app.list_prompts()
                    return types.ServerResult(result)
                except Exception as e:
                    logger.error(f"Error in list_prompts: {e}")
                    raise

            app.request_handlers[types.ListPromptsRequest] = create_error_handler(_list_prompts)

            async def _get_prompt(req: types.GetPromptRequest) -> types.ServerResult:
                try:
                    result = await remote_app.get_prompt(req.params.name, req.params.arguments)
                    return types.ServerResult(result)
                except Exception as e:
                    logger.error(f"Error in get_prompt with {req.params.name}: {e}")
                    raise

            app.request_handlers[types.GetPromptRequest] = create_error_handler(_get_prompt)
        else:
            logger.info(f"Server {server_name} does not support prompts")

        # resources capabilities handling
        if get_capability(capabilities, 'resources'):
            logger.info(f"Server {server_name} supports resources")

            async def _list_resources(_: t.Any) -> types.ServerResult:  # noqa: ANN401
                try:
                    result = await remote_app.list_resources()
                    return types.ServerResult(result)
                except Exception as e:
                    logger.error(f"Error in list_resources: {e}")
                    raise

            app.request_handlers[types.ListResourcesRequest] = create_error_handler(_list_resources)

            # register read_resource handler
            async def _read_resource(req: types.ReadResourceRequest) -> types.ServerResult:
                try:
                    result = await remote_app.read_resource(req.params.uri)
                    return types.ServerResult(result)
                except Exception as e:
                    logger.error(f"Error in read_resource with {req.params.uri}: {e}")
                    raise

            app.request_handlers[types.ReadResourceRequest] = create_error_handler(_read_resource)

            # register only if subscription feature is supported
            if get_capability(capabilities, 'resources.subscribe'):
                logger.info(f"Server {server_name} supports resource subscriptions")
                
                async def _subscribe_resource(req: types.SubscribeRequest) -> types.ServerResult:
                    try:
                        await remote_app.subscribe_resource(req.params.uri)
                        return types.ServerResult(types.EmptyResult())
                    except Exception as e:
                        logger.error(f"Error in subscribe_resource with {req.params.uri}: {e}")
                        raise

                app.request_handlers[types.SubscribeRequest] = create_error_handler(_subscribe_resource)

                async def _unsubscribe_resource(req: types.UnsubscribeRequest) -> types.ServerResult:
                    try:
                        await remote_app.unsubscribe_resource(req.params.uri)
                        return types.ServerResult(types.EmptyResult())
                    except Exception as e:
                        logger.error(f"Error in unsubscribe_resource with {req.params.uri}: {e}")
                        raise

                app.request_handlers[types.UnsubscribeRequest] = create_error_handler(_unsubscribe_resource)
        else:
            logger.info(f"Server {server_name} does not support resources")

        # logging capabilities handling
        if get_capability(capabilities, 'logging'):
            logger.info(f"Server {server_name} supports logging")

            async def _set_logging_level(req: types.SetLevelRequest) -> types.ServerResult:
                try:
                    await remote_app.set_logging_level(req.params.level)
                    return types.ServerResult(types.EmptyResult())
                except Exception as e:
                    logger.error(f"Error in set_logging_level with {req.params.level}: {e}")
                    raise

            app.request_handlers[types.SetLevelRequest] = create_error_handler(_set_logging_level)
        else:
            logger.info(f"Server {server_name} does not support logging")

        # tools capabilities handling
        if get_capability(capabilities, 'tools'):
            logger.info(f"Server {server_name} supports tools")

            async def _list_tools(_: t.Any) -> types.ServerResult:  # noqa: ANN401
                try:
                    tools = await remote_app.list_tools()
                    return types.ServerResult(tools)
                except Exception as e:
                    logger.error(f"Error in list_tools: {e}")
                    raise

            app.request_handlers[types.ListToolsRequest] = create_error_handler(_list_tools)

            async def _call_tool(req: types.CallToolRequest) -> types.ServerResult:
                try:
                    result = await remote_app.call_tool(
                        req.params.name,
                        (req.params.arguments or {}),
                    )
                    return types.ServerResult(result)
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Error calling tool {req.params.name}: {e}")
                    return types.ServerResult(
                        types.CallToolResult(
                            content=[types.TextContent(type="text", text=str(e))],
                            isError=True,
                        ),
                    )

            app.request_handlers[types.CallToolRequest] = create_error_handler(_call_tool)
        else:
            logger.info(f"Server {server_name} does not support tools")

        # progress notification handler - supported by most servers
        async def _send_progress_notification(req: types.ProgressNotification) -> None:
            try:
                await remote_app.send_progress_notification(
                    req.params.progressToken,
                    req.params.progress,
                    req.params.total,
                )
            except Exception as e:
                logger.error(f"Error in send_progress_notification: {e}")
                # Notifications don't return responses, so propagate the error
                raise

        app.notification_handlers[types.ProgressNotification] = _send_progress_notification

        # complete handler - supported by most servers
        async def _complete(req: types.CompleteRequest) -> types.ServerResult:
            try:
                result = await remote_app.complete(
                    req.params.ref,
                    req.params.argument.model_dump(),
                )
                return types.ServerResult(result)
            except Exception as e:
                logger.error(f"Error in complete: {e}")
                raise

        app.request_handlers[types.CompleteRequest] = create_error_handler(_complete)

        logger.info(f"Proxy server for {server_name} created successfully")
        return app
        
    except Exception as e:
        logger.error(f"Failed to create proxy server: {e}")
        raise