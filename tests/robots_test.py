import sys
import os
import asyncio

# Add the parent directory to sys.path to be able to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server_fetch.server import check_may_autonomously_fetch_url, get_robots_txt_url

async def test_robots_txt_functionality():
    """Test the robots.txt checking functionality."""
    # Test with multiple URLs
    test_urls = [
        "https://example.com",
        "https://www.python.org", 
        "https://github.com",
        "https://www.google.com",
        # More restrictive sites
        "https://facebook.com",
        "https://twitter.com",
        "https://linkedin.com",
        "https://archive.org/wayback"
    ]
    
    # Test with different user agents
    user_agents = [
        "MCP-Test-Agent/1.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "ModelContextProtocol/1.0 (Autonomous; +https://github.com/modelcontextprotocol/servers)"
    ]
    
    for test_url in test_urls:
        print(f"\n\n{'='*50}")
        print(f"Testing robots.txt for URL: {test_url}")
        print(f"{'='*50}")
        
        # Get robots.txt URL
        robots_url = get_robots_txt_url(test_url)
        print(f"Original URL: {test_url}")
        print(f"Robots.txt URL: {robots_url}")
        
        for user_agent in user_agents:
            print(f"\nTesting with user agent: '{user_agent}'")
            try:
                # Check if autonomous fetching is allowed
                await check_may_autonomously_fetch_url(test_url, user_agent)
                
                # If we get here, fetching is allowed
                print(f"✓ Autonomous fetching is allowed for {test_url}")
                
            except Exception as e:
                print(f"✗ Autonomous fetching is NOT allowed: {str(e).split('\\n')[0]}")

if __name__ == "__main__":
    asyncio.run(test_robots_txt_functionality()) 