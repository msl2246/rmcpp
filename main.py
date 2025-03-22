"""The entry point for the rmcpp application. It sets up the logging and runs the main function.

Two ways to run the application:
1. Run the application as a module `uv run -m rmcpp`
2. Run the application as a package `uv run rmcpp`

"""

import argparse
import asyncio
import logging
import os
import sys
import typing as t

from mcp.client.stdio import StdioServerParameters

from sse_client import run_sse_client
from sse_server import SseServerSettings, run_sse_server


def setup_logging(level: str = "INFO") -> None:
    """Set up logging with better formatting and proper level."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Improved log format
    log_format = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    
    # Adjust log level for external libraries
    if numeric_level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


SSE_URL: t.Final[str | None] = os.getenv(
    "SSE_URL",
    None,
)


def main() -> None:
    """Start the client using asyncio."""
    parser = argparse.ArgumentParser(
        description=(
            "Start the MCP proxy in one of two possible modes: as an SSE or stdio client."
        ),
        epilog=(
            "Examples:\n"
            "  rmcpp http://localhost:8080/sse\n"
            "  rmcpp --headers Authorization 'Bearer YOUR_TOKEN' http://localhost:8080/sse\n"
            "  rmcpp --sse-port 8080 -- your-command --arg1 value1 --arg2 value2\n"
            "  rmcpp your-command --sse-port 8080 -e KEY VALUE -e ANOTHER_KEY ANOTHER_VALUE\n"
            "  rmcpp your-command --sse-port 8080 --allow-origin='*'\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "command_or_url",
        help=(
            "Command or URL to connect to. When a URL, will run an SSE client, "
            "otherwise will run the given command and connect as a stdio client. "
            "See corresponding options for more details."
        ),
        nargs="?",  # Required below to allow for coming form env var
        default=SSE_URL,
    )

    sse_client_group = parser.add_argument_group("SSE client options")
    sse_client_group.add_argument(
        "-H",
        "--headers",
        nargs=2,
        action="append",
        metavar=("KEY", "VALUE"),
        help="Headers to pass to the SSE server. Can be used multiple times.",
        default=[],
    )

    stdio_client_options = parser.add_argument_group("stdio client options")
    stdio_client_options.add_argument(
        "args",
        nargs="*",
        help="Any extra arguments to the command to spawn the server",
    )
    stdio_client_options.add_argument(
        "-e",
        "--env",
        nargs=2,
        action="append",
        metavar=("KEY", "VALUE"),
        help="Environment variables used when spawning the server. Can be used multiple times.",
        default=[],
    )
    stdio_client_options.add_argument(
        "--pass-environment",
        action=argparse.BooleanOptionalAction,
        help="Pass through all environment variables when spawning the server.",
        default=False,
    )

    sse_server_group = parser.add_argument_group("SSE server options")
    sse_server_group.add_argument(
        "--sse-port",
        type=int,
        default=0,
        help="Port to expose an SSE server on. Default is a random port",
    )
    sse_server_group.add_argument(
        "--sse-host",
        default="127.0.0.1",
        help="Host to expose an SSE server on. Default is 127.0.0.1",
    )
    sse_server_group.add_argument(
        "--allow-origin",
        nargs="+",
        default=[],
        help="Allowed origins for the SSE server. Can be used multiple times. Default is no CORS allowed.",  # noqa: E501
    )
    
    # Logging related arguments
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level (default: INFO)"
    )
    
    # Cache capability support related arguments
    parser.add_argument(
        "--disable-capability-check",
        action="store_true",
        help="Disable capability-based method filtering. All methods will be tried regardless of server capabilities."
    )
    
    # Retry related arguments
    parser.add_argument(
        "--max-retries",
        type=int,
        default=1,
        help="Maximum number of retries for failed requests (default: 1)"
    )

    args = parser.parse_args()

    if not args.command_or_url:
        parser.print_help()
        sys.exit(1)
    
    # Set up logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    if (
        SSE_URL
        or args.command_or_url.startswith("http://")
        or args.command_or_url.startswith("https://")
    ):
        # Start a client connected to the SSE server, and expose as a stdio server
        logger.info(f"Starting SSE client to {args.command_or_url} and stdio server")
        headers = dict(args.headers)
        if api_access_token := os.getenv("API_ACCESS_TOKEN", None):
            headers["Authorization"] = f"Bearer {api_access_token}"
        
        try:
            # Pass configuration options
            config = {
                "disable_capability_check": args.disable_capability_check,
                "max_retries": args.max_retries,
            }
            asyncio.run(run_sse_client(args.command_or_url, headers=headers, config=config))
        except KeyboardInterrupt:
            logger.info("Interrupted by user. Shutting down...")
        except Exception as e:
            logger.error(f"Error running SSE client: {e}")
            sys.exit(1)
        return

    # Start a client connected to the given command, and expose as an SSE server
    logger.info(f"Starting stdio client with command '{args.command_or_url}' and SSE server")

    # The environment variables passed to the server process
    env: dict[str, str] = {}
    # Pass through current environment variables if configured
    if args.pass_environment:
        env.update(os.environ)
    # Pass in and override any environment variables with those passed on the command line
    env.update(dict(args.env))

    stdio_params = StdioServerParameters(
        command=args.command_or_url,
        args=args.args,
        env=env,
    )
    sse_settings = SseServerSettings(
        bind_host=args.sse_host,
        port=args.sse_port,
        allow_origins=args.allow_origin if len(args.allow_origin) > 0 else None,
        log_level=args.log_level,
    )
    
    try:
        asyncio.run(run_sse_server(stdio_params, sse_settings))
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Shutting down...")
    except Exception as e:
        logger.error(f"Error running SSE server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()