import asyncio
import traceback
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def test_with_full_traceback():
    print("Testing with full error details...")

    try:
        async with streamablehttp_client("http://localhost:9999/mcp") as (read, write, get_session_id):
            print(f"Transport created, session ID: {get_session_id()}")

            async with ClientSession(read, write) as session:
                print("ClientSession created")
                # Just wait a moment to see if there are background tasks
                await asyncio.sleep(0.1)
                print("Sleep completed")

    except Exception as e:
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception message: {str(e)}")
        print("Full traceback:")
        traceback.print_exc()
        return False

    return True

def main():
    print("=== Error investigation ===\n")

    try:
        result = asyncio.run(test_with_full_traceback())
        print(f"\nTest result: {result}")
    except Exception as e:
        print(f"\nasyncio.run() failed: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
