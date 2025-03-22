## About

The `rmcpp` is a tool that lets you switch between server transports. There are two supported modes:

1. stdio to SSE
2. SSE to stdio

## 1. stdio to SSE

Run a proxy server from stdio that connects to a remote SSE server.

This mode allows clients like Claude Desktop to communicate to a remote server over SSE even though it is not supported natively.

```mermaid
graph LR
    A["Claude Desktop"] <--> |stdio| B["rmcpp"]
    B <--> |SSE| C["External MCP Server"]

    style A fill:#ffe6f9,stroke:#333,color:black,stroke-width:2px
    style B fill:#e6e6ff,stroke:#333,color:black,stroke-width:2px
    style C fill:#e6ffe6,stroke:#333,color:black,stroke-width:2px
```

### 1.1 Configuration

This mode requires passing the URL to the MCP Server SSE endpoint as the first argument to the program.

Arguments

| Name             | Required | Description                                      | Example                                       |
| ---------------- | -------- | ------------------------------------------------ | --------------------------------------------- |
| `command_or_url` | Yes      | The MCP server SSE endpoint to connect to        | http://example.io/sse                         |
| `--headers`      | No       | Headers to use for the MCP server SSE connection | Authorization 'Bearer my-secret-access-token' |

Environment Variables

| Name               | Required | Description                                                                  | Example    |
| ------------------ | -------- | ---------------------------------------------------------------------------- | ---------- |
| `API_ACCESS_TOKEN` | No       | Can be used instead of `--headers Authorization 'Bearer <API_ACCESS_TOKEN>'` | YOUR_TOKEN |

### 1.2 Example usage

`rmcpp` is supposed to be started by the MCP Client, so the configuration must be done accordingly.

For Claude Desktop, the configuration entry can look like this:

```json
{
  "mcpServers": {
    "rmcpp": {
        "command": "rmcpp",
        "args": ["http://example.io/sse"],
        "env": {
          "API_ACCESS_TOKEN": "access-token"
        }
    }
  }
}
```

## 2. SSE to stdio

Run a proxy server exposing a SSE server that connects to a local stdio server.

This allows remote connections to the local stdio server. The `rmcpp` opens a port to listen for SSE requests, spawns a local stdio server that handles MCP requests.

```mermaid
graph LR
    A["LLM Client"] <-->|SSE| B["rmcpp"]
    B <-->|stdio| C["Local MCP Server"]

    style A fill:#ffe6f9,stroke:#333,color:black,stroke-width:2px
    style B fill:#e6e6ff,stroke:#333,color:black,stroke-width:2px
    style C fill:#e6ffe6,stroke:#333,color:black,stroke-width:2px
```

### 2.1 Configuration

This mode requires the `--sse-port` argument to be set. The `--sse-host` argument can be set to specify the host IP address that the SSE server will listen on. Additional environment variables can be passed to the local stdio server using the `--env` argument. The command line arguments for the local stdio server must be passed after the `--` separator.

Arguments

| Name                 | Required                   | Description                                                      | Example               |
| -------------------- | -------------------------- | ---------------------------------------------------------------- | --------------------- |
| `command_or_url`     | Yes                        | The command to spawn the MCP stdio server                        | uvx mcp-server-fetch  |
| `--sse-port`         | No, random available       | The SSE server port to listen on                                 | 8080                  |
| `--sse-host`         | No, `127.0.0.1` by default | The host IP address that the SSE server will listen on           | 0.0.0.0               |
| `--env`              | No                         | Additional environment variables to pass to the MCP stdio server | FOO=BAR               |
| `--pass-environment` | No                         | Pass through all environment variables when spawning the server  | --no-pass-environment |
| `--allow-origin`     | No                         | Pass through all environment variables when spawning the server  | --allow-cors "\*"     |

### 2.2 Example usage

To start the `rmcpp` server that listens on port 8080 and connects to the local MCP server:

```bash
# Start the MCP server behind the proxy
rmcpp uvx mcp-server-fetch

# Start the MCP server behind the proxy with a custom port
rmcpp --sse-port=8080 uvx mcp-server-fetch

# Start the MCP server behind the proxy with a custom host and port
rmcpp --sse-host=0.0.0.0 --sse-port=8080 uvx mcp-server-fetch

# Start the MCP server behind the proxy with a custom user agent
# Note that the `--` separator is used to separate the `rmcpp` arguments from the `mcp-server-fetch` arguments
rmcpp --sse-port=8080 -- uvx mcp-server-fetch --user-agent=YourUserAgent
```

This will start an MCP server that can be connected to at `http://127.0.0.1:8080/sse`

## Installation

### Installing via PyPI

The stable version of the package is available on the PyPI repository. You can install it using the following command:

```bash
# Option 1: With uv (recommended)
uv tool install rmcpp

# Option 2: With pipx (alternative)
pipx install rmcpp
```

Once installed, you can run the server using the `rmcpp` command. See configuration options for each mode above.

### Installing via Github repository (latest)

The latest version of the package can be installed from the git repository using the following command:

```bash
uv tool install git+https://github.com/msl2246/rmcpp
```

> [!NOTE]
> If you have already installed the server, you can update it using `uv tool upgrade --reinstall` command.

> [!NOTE]
> If you want to delete the server, use the `uv tool uninstall rmcpp` command.

## Command line arguments

```bash
usage: rmcpp [-h] [-H KEY VALUE] [-e KEY VALUE] [--pass-environment | --no-pass-environment] [--sse-port SSE_PORT] [--sse-host SSE_HOST]
                 [--allow-origin ALLOW_ORIGIN [ALLOW_ORIGIN ...]]
                 [command_or_url] [args ...]

Start the MCP proxy in one of two possible modes: as an SSE or stdio client.

positional arguments:
  command_or_url        Command or URL to connect to. When a URL, will run an SSE client, otherwise will run the given command and connect as a stdio client. See corresponding options for more details.

options:
  -h, --help            show this help message and exit

SSE client options:
  -H KEY VALUE, --headers KEY VALUE
                        Headers to pass to the SSE server. Can be used multiple times.

stdio client options:
  args                  Any extra arguments to the command to spawn the server
  -e KEY VALUE, --env KEY VALUE
                        Environment variables used when spawning the server. Can be used multiple times.
  --pass-environment, --no-pass-environment
                        Pass through all environment variables when spawning the server.

SSE server options:
  --sse-port SSE_PORT   Port to expose an SSE server on. Default is a random port
  --sse-host SSE_HOST   Host to expose an SSE server on. Default is 127.0.0.1
  --allow-origin ALLOW_ORIGIN [ALLOW_ORIGIN ...]
                        Allowed origins for the SSE server. Can be used multiple times. Default is no CORS allowed.

Examples:
  rmcpp http://localhost:8080/sse
  rmcpp --headers Authorization 'Bearer YOUR_TOKEN' http://localhost:8080/sse
  rmcpp --sse-port 8080 -- your-command --arg1 value1 --arg2 value2
  rmcpp your-command --sse-port 8080 -e KEY VALUE -e ANOTHER_KEY ANOTHER_VALUE
  rmcpp your-command --sse-port 8080 --allow-origin='*'
```

## Testing

Check the `rmcpp` server by running it with the `mcp-server-fetch` server. You can use the [inspector tool](https://modelcontextprotocol.io/docs/tools/inspector) to test the target server.

```bash
# Run the stdio server called mcp-server-fetch behind the proxy over SSE
rmcpp --sse-port=8080 uvx mcp-server-fetch &

# Connect to the SSE proxy server spawned above using another instance of rmcpp given the URL of the SSE server
rmcpp http://localhost:8080/sse

# Send CTRL+C to stop the second server

# Bring the first server to the foreground
fg

# Send CTRL+C to stop the first server
```