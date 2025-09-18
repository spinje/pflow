import asyncio
import json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def test_http_client_detailed():
    print("Attempting to connect to HTTP MCP server...")

    try:
        async with streamablehttp_client("http://localhost:9999/mcp") as (read, write, get_session_id):
            print(f"Transport created with session ID: {get_session_id()}")

            # Try to create a client session
            async with ClientSession(read, write) as session:
                print("ClientSession created successfully")

                # Try to initialize (this will likely fail with connection error)
                try:
                    await session.initialize()
                    print("Session initialized successfully")

                    # Try to list tools
                    result = await session.list_tools()
                    print(f"Tools available: {result}")

                except Exception as init_error:
                    print(f"Initialization failed (expected): {init_error}")
                    return "connection_failed_as_expected"

    except Exception as e:
        print(f"Transport creation failed: {e}")
        return "transport_failed"

    return "success"

async def test_event_loop_isolation():
    """Test if multiple asyncio.run() calls work without event loop conflicts"""
    print("Testing event loop isolation...")

    # Get current event loop info
    try:
        current_loop = asyncio.get_running_loop()
        print(f"Current loop: {current_loop}")
    except RuntimeError:
        print("No running event loop (expected)")

    return "loop_test_complete"

def main():
    print("=== Detailed asyncio compatibility test ===\n")

    # Test 1: Basic transport functionality
    for i in range(3):
        print(f"\n--- Test Run {i+1} ---")
        try:
            result = asyncio.run(test_http_client_detailed())
            print(f"Result: {result}")
        except Exception as e:
            print(f"Test {i+1} failed with error: {e}")
            print(f"Error type: {type(e).__name__}")

    # Test 2: Event loop isolation
    print(f"\n--- Event Loop Isolation Test ---")
    try:
        loop_result = asyncio.run(test_event_loop_isolation())
        print(f"Loop test result: {loop_result}")
    except Exception as e:
        print(f"Event loop test failed: {e}")

    print("\n=== Test completed ===")

if __name__ == "__main__":
    main()
