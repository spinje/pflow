import asyncio
import traceback
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def test_initialization():
    print("Testing MCP client initialization...")

    try:
        async with streamablehttp_client("http://localhost:9999/mcp") as (read, write, get_session_id):
            print(f"Transport created, session ID: {get_session_id()}")

            async with ClientSession(read, write) as session:
                print("ClientSession created")

                # This is where the error likely occurs
                print("Attempting to initialize session...")
                await session.initialize()
                print("Session initialized successfully")

    except Exception as e:
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception message: {str(e)}")
        print("Full traceback:")
        traceback.print_exc()
        return False

    return True

def main():
    print("=== Initialization test ===\n")

    for i in range(2):
        print(f"\n--- Test {i+1} ---")
        try:
            result = asyncio.run(test_initialization())
            print(f"Test {i+1} result: {result}")
        except Exception as e:
            print(f"asyncio.run() failed in test {i+1}: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    main()
