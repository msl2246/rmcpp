import sys
import os
import asyncio

# Add the parent directory to sys.path to be able to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import subprocess
import time
import threading

def start_server():
    print("Starting MCP fetch server...")
    try:
        # Start the fetch server in a separate process
        process = subprocess.Popen(
            [sys.executable, os.path.join(os.path.dirname(__file__), "simple_test.py")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Print server output in real-time
        for line in process.stdout:
            print(f"Server: {line.strip()}")
        
    except Exception as e:
        print(f"Error starting server: {e}")
    
def start_rmcpp_proxy():
    print("Starting RMCPP proxy...")
    try:
        # Wait for the server to start
        time.sleep(3)
        
        # Start RMCPP with the fetch server
        # Updated to use the new package structure
        rmcpp_process = subprocess.Popen(
            [sys.executable, "-m", "rmcpp.main", sys.executable, 
             os.path.join(os.path.dirname(__file__), "simple_test.py"), 
             "--sse-port", "8080"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Print RMCPP output in real-time
        for line in rmcpp_process.stdout:
            print(f"RMCPP: {line.strip()}")
            
    except Exception as e:
        print(f"Error starting RMCPP: {e}")

if __name__ == "__main__":
    # Start server in a separate thread
    server_thread = threading.Thread(target=start_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Start RMCPP in main thread
    start_rmcpp_proxy()
    
    print("Test complete.") 