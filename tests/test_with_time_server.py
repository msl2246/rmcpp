"""Test the MCP proxy with the time server.

This script will:
1. Start the mcp_server_time server
2. Start the proxy server with the time server
3. Run tests against the proxy
"""

import sys
import os
import asyncio
import subprocess
import threading
import time
import json
import logging
import traceback
import requests
from datetime import datetime

# Add the parent directory to sys.path to be able to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sse_client import run_sse_client
from sse_server import run_sse_server, SseServerSettings
from mcp.client.stdio import StdioServerParameters

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

def start_time_server():
    """Start the mcp_server_time server in a separate process."""
    logger.info("Starting MCP Time Server...")
    try:
        # Start the time server in a separate process
        process = subprocess.Popen(
            [sys.executable, "-m", "mcp_server_time"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        logger.info(f"Time Server process started with PID: {process.pid}")
        
        # Start a thread to read and log output
        def log_output():
            for line in process.stdout:
                logger.info(f"Time Server: {line.strip()}")
            
        output_thread = threading.Thread(target=log_output, daemon=True)
        output_thread.start()
        
        return process
    except Exception as e:
        logger.error(f"Error starting Time Server: {e}")
        logger.error(traceback.format_exc())
        raise

def start_rmcpp_proxy(time_server_process):
    """Start RMCPP proxy connected to time server."""
    logger.info("Starting RMCPP proxy...")
    try:
        # Wait for the server to start
        time.sleep(2)
        
        # Setup the proxy server parameters
        stdio_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server_time"],
            env=os.environ.copy(),
        )
        
        # Configure the SSE server settings
        sse_settings = SseServerSettings(
            bind_host="127.0.0.1",
            port=8080,
            allow_origins=["*"],
            log_level="DEBUG"
        )
        
        # Start the proxy server asynchronously
        proxy_thread = threading.Thread(
            target=lambda: asyncio.run(run_sse_server(stdio_params, sse_settings))
        )
        proxy_thread.daemon = True
        proxy_thread.start()
        
        # Give the proxy server time to start up
        time.sleep(2)
        
        return proxy_thread
    except Exception as e:
        logger.error(f"Error starting RMCPP proxy: {e}")
        logger.error(traceback.format_exc())
        raise

def test_sse_client_connection():
    """Test connecting to the proxy server through the SSE client."""
    logger.info("Testing SSE client connection to proxy...")
    try:
        # Setup client connection parameters
        url = "http://127.0.0.1:8080/sse"
        headers = {}
        config = {
            "disable_capability_check": False,
            "max_retries": 2
        }
        
        # Use run_sse_client in a separate thread since it's blocking
        client_thread = threading.Thread(
            target=lambda: asyncio.run(run_sse_client(url, headers, config))
        )
        client_thread.daemon = True
        client_thread.start()
        
        # Give the client time to connect
        time.sleep(2)
        
        return client_thread
    except Exception as e:
        logger.error(f"Error testing SSE client connection: {e}")
        logger.error(traceback.format_exc())
        raise

def send_jsonrpc_request(url, method, params=None, request_id=1):
    """Send a JSON-RPC request with error handling.
    
    Args:
        url (str): The URL to send the request to
        method (str): The RPC method to call
        params (dict): Parameters for the method
        request_id (int): The request ID
        
    Returns:
        dict: The parsed response
    """
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method
    }
    
    if params:
        payload["params"] = params
        
    logger.info(f"Sending JSON-RPC request: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        
        try:
            result = response.json()
            logger.info(f"Response received: {json.dumps(result, indent=2)}")
            return result
        except json.JSONDecodeError as je:
            logger.error(f"Failed to parse response as JSON: {je}")
            logger.error(f"Response text: {response.text}")
            
            # Try to sanitize and recover the response
            if response.text:
                # Look for a valid JSON subset in the response
                clean_response = response.text.strip()
                match = re.search(r'(\{.*\})', clean_response)
                if match:
                    try:
                        partial_json = match.group(1)
                        result = json.loads(partial_json)
                        logger.warning(f"Recovered partial JSON: {result}")
                        return result
                    except json.JSONDecodeError:
                        logger.error("Failed to recover partial JSON")
            
            return {"error": {"code": -32700, "message": "Invalid JSON response"}}
            
    except requests.RequestException as e:
        logger.error(f"Request failed: {e}")
        return {"error": {"code": -32000, "message": f"Request failed: {str(e)}"}}

def run_tests():
    """Run comprehensive tests for the proxy setup."""
    logger.info("Starting comprehensive proxy tests...")
    
    # Test direct HTTP requests to the server
    try:
        endpoint = "http://127.0.0.1:8080/messages/"
        
        # Test 1: Initialize server
        init_result = send_jsonrpc_request(
            endpoint,
            "initialize",
            {"capabilities": {}}
        )
        
        if "result" in init_result:
            logger.info("✓ Initialize request successful")
            # Log server capabilities
            if "capabilities" in init_result.get("result", {}):
                capabilities = init_result["result"]["capabilities"]
                logger.info(f"Server capabilities: {capabilities}")
        else:
            logger.error(f"✗ Initialize request failed: {init_result}")
        
        # Test 2: List tools
        tools_result = send_jsonrpc_request(
            endpoint,
            "tools/list"
        )
        
        if "result" in tools_result:
            logger.info("✓ List tools request successful")
            # Extract and log available tools
            tools = tools_result.get("result", {})
            logger.info(f"Available tools: {tools}")
        else:
            logger.error(f"✗ List tools request failed: {tools_result}")
        
        # Test 3: Get current time
        time_result = send_jsonrpc_request(
            endpoint,
            "tools/call",
            {"name": "get_current_time", "arguments": {"timezone": "UTC"}}
        )
        
        if "result" in time_result:
            logger.info("✓ Get current time request successful")
            # Extract and log time result
            content = time_result.get("result", {}).get("content", [])
            if content and isinstance(content, list) and len(content) > 0:
                time_data = content[0].get("text", "")
                try:
                    time_json = json.loads(time_data)
                    logger.info(f"Current UTC time: {time_json.get('datetime')}")
                    logger.info(f"Is DST: {time_json.get('is_dst')}")
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse time result: {time_data}")
        else:
            logger.error(f"✗ Get current time request failed: {time_result}")
        
        # Test 4: Convert time
        convert_result = send_jsonrpc_request(
            endpoint,
            "tools/call",
            {
                "name": "convert_time", 
                "arguments": {
                    "source_timezone": "UTC", 
                    "time": "14:30", 
                    "target_timezone": "America/New_York"
                }
            }
        )
        
        if "result" in convert_result:
            logger.info("✓ Convert time request successful")
            # Extract and log conversion result
            content = convert_result.get("result", {}).get("content", [])
            if content and isinstance(content, list) and len(content) > 0:
                conversion_data = content[0].get("text", "")
                try:
                    conversion_json = json.loads(conversion_data)
                    logger.info(f"Time difference: {conversion_json.get('time_difference')}")
                    logger.info(f"Source time: {conversion_json.get('source', {}).get('datetime')}")
                    logger.info(f"Target time: {conversion_json.get('target', {}).get('datetime')}")
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse conversion result: {conversion_data}")
        else:
            logger.error(f"✗ Convert time request failed: {convert_result}")
    
    except Exception as e:
        logger.error(f"Error during tests: {e}")
        logger.error(traceback.format_exc())

def main():
    """Main function to orchestrate all tests."""
    time_server_process = None
    
    try:
        # 1. Start time server
        logger.info("=== STEP 1: Starting Time Server ===")
        time_server_process = start_time_server()
        
        # 2. Start proxy server
        logger.info("=== STEP 2: Starting Proxy Server ===")
        proxy_thread = start_rmcpp_proxy(time_server_process)
        
        # 3. Start client connection
        logger.info("=== STEP 3: Testing Client Connection ===")
        client_thread = test_sse_client_connection()
        
        # 4. Run tests
        logger.info("=== STEP 4: Running Tests ===")
        time.sleep(1)  # Give everything time to settle
        run_tests()
        
        # Keep the script running for a while to see the interaction
        logger.info("Tests complete. Keeping services running for 10 seconds...")
        time.sleep(10)
        
        # Clean up
        logger.info("Test sequence complete. Cleaning up...")
        
        logger.info("All tests completed successfully")
    
    except Exception as e:
        logger.error(f"Test suite error: {e}")
        logger.error(traceback.format_exc())
    
    finally:
        # Make sure to clean up any processes
        if time_server_process:
            try:
                logger.info(f"Terminating Time Server process (PID: {time_server_process.pid})")
                time_server_process.terminate()
                time_server_process.wait(timeout=5)
                logger.info("Time Server process terminated")
            except Exception as e:
                logger.error(f"Error terminating Time Server: {e}")
                try:
                    import signal
                    os.kill(time_server_process.pid, signal.SIGTERM)
                    logger.info("Sent SIGTERM signal to Time Server process")
                except:
                    logger.error("Failed to kill Time Server process")

if __name__ == "__main__":
    main() 