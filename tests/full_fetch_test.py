import sys
import os
import asyncio
import json

# Add the parent directory to sys.path to be able to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server_fetch.server import (
    fetch_url, 
    extract_content_from_html, 
    get_robots_txt_url, 
    check_may_autonomously_fetch_url,
    Fetch
)

async def test_fetch_server_functionality():
    """Test all the functionality of the fetch MCP server."""
    # Test URLs and their expected outcomes
    test_cases = [
        {
            "name": "Simple HTML page",
            "url": "https://example.com",
            "raw": False,
            "start_index": 0,
            "max_length": 5000,
            "expected_result": {
                "success": True,
                "content_type": "html"
            }
        },
        {
            "name": "Raw mode test",
            "url": "https://example.com",
            "raw": True,
            "start_index": 0,
            "max_length": 5000,
            "expected_result": {
                "success": True,
                "content_type": "raw"
            }
        },
        {
            "name": "Content pagination test",
            "url": "https://www.python.org",
            "raw": False,
            "start_index": 100,
            "max_length": 1000,
            "expected_result": {
                "success": True,
                "content_type": "html"
            }
        }
    ]
    
    user_agent = "ModelContextProtocol/1.0 (Autonomous; +https://github.com/modelcontextprotocol/servers)"
    
    print(f"{'='*70}")
    print(f"COMPREHENSIVE FETCH MCP SERVER TEST")
    print(f"{'='*70}")
    
    # Test all cases
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n\n{'-'*70}")
        print(f"TEST CASE #{i}: {test_case['name']}")
        print(f"{'-'*70}")
        
        url = test_case["url"]
        raw = test_case["raw"]
        start_index = test_case["start_index"]
        max_length = test_case["max_length"]
        
        try:
            # Test robots.txt check
            print(f"Checking robots.txt for {url}...")
            robots_url = get_robots_txt_url(url)
            print(f"Robots.txt URL: {robots_url}")
            
            try:
                await check_may_autonomously_fetch_url(url, user_agent)
                print(f"✓ Robots.txt check passed")
            except Exception as e:
                print(f"✗ Robots.txt check failed: {str(e).split('\\n')[0]}")
                continue
            
            # Test URL fetching
            print(f"\nFetching content from {url} (raw={raw}, start_index={start_index}, max_length={max_length})...")
            content, prefix = await fetch_url(url, user_agent, force_raw=raw)
            
            # Simulate the pagination and truncation logic
            original_length = len(content)
            if start_index >= original_length:
                content = "<error>No more content available.</error>"
            else:
                truncated_content = content[start_index : start_index + max_length]
                if not truncated_content:
                    content = "<error>No more content available.</error>"
                else:
                    content = truncated_content
                    actual_content_length = len(truncated_content)
                    remaining_content = original_length - (start_index + actual_content_length)
                    if actual_content_length == max_length and remaining_content > 0:
                        next_start = start_index + actual_content_length
                        content += f"\n\n<error>Content truncated. Call the fetch tool with a start_index of {next_start} to get more content.</error>"
            
            # Print results
            print(f"\n--- Fetch Results ---")
            print(f"Content type: {'Raw' if prefix else 'HTML converted to Markdown'}")
            print(f"Content length: {len(content)} characters")
            print(f"Content snippet: {content[:100]}...")
            
            if len(content) > 150:
                print(f"Test case passed!")
                
        except Exception as e:
            print(f"Error in test case: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n\n{'='*70}")
    print("All tests completed!")
    print(f"{'='*70}")

if __name__ == "__main__":
    asyncio.run(test_fetch_server_functionality()) 