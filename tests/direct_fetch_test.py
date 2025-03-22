import sys
import os
import asyncio

# Add the parent directory to sys.path to be able to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server_fetch.server import fetch_url, extract_content_from_html, get_robots_txt_url, check_may_autonomously_fetch_url

async def test_fetch_functionality():
    """Test the core fetch functionality directly."""
    # Test with multiple URLs
    test_urls = [
        "https://example.com",
        "https://www.python.org",
        "https://github.com/modelcontextprotocol/servers"
    ]
    
    user_agent = "MCP-Test-Agent/1.0"
    
    for test_url in test_urls:
        print(f"\n\n{'='*50}")
        print(f"Testing fetch functionality with URL: {test_url}")
        print(f"{'='*50}")
        
        try:
            # Test robots.txt URL generation
            robots_url = get_robots_txt_url(test_url)
            print(f"\n--- Robots.txt URL ---")
            print(f"Original URL: {test_url}")
            print(f"Robots.txt URL: {robots_url}")
            
            # Test fetching a URL
            content, prefix = await fetch_url(test_url, user_agent)
            
            print("\n--- Fetch Result ---")
            print(f"Prefix: {prefix}")
            print(f"Content summary (first 100 chars): {content[:100]}...")
            print(f"Total content length: {len(content)} characters")
            
            # Test HTML extraction if content is HTML
            if "<html" in content[:100] or prefix == "":
                print("\n--- HTML Extraction Result ---")
                print(f"Markdown summary (first 100 chars): {content[:100]}...")
                
            print(f"Test for {test_url} completed successfully!")
            
        except Exception as e:
            print(f"Error testing {test_url}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_fetch_functionality()) 