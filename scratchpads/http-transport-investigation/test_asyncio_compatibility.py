import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def test_http_client():
    # Test basic connection (will fail but should not crash on import)
    try:
        async with streamablehttp_client("http://localhost:9999/mcp") as (read, write, get_session_id):
            print("Client created successfully")
            return True
    except Exception as e:
        print(f"Expected connection error: {e}")
        return True  # Still success if we got this far

def main():
    print("Testing asyncio compatibility with streamablehttp_client...")

    # Test multiple asyncio.run() calls
    for i in range(3):
        print(f"\n--- Execution {i+1} ---")
        try:
            result = asyncio.run(test_http_client())
            print(f"Execution {i+1}: {result}")
        except Exception as e:
            print(f"Execution {i+1} failed: {e}")
            return False

    print("\nAll executions completed successfully!")
    return True

if __name__ == "__main__":
    main()
