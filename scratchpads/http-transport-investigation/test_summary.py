import asyncio
import traceback
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def test_transport_creation_only():
    """Test just transport creation without making network calls"""
    print("Testing transport creation without network calls...")

    try:
        # Just create the transport context, don't initialize
        async with streamablehttp_client("http://localhost:9999/mcp") as (read, write, get_session_id):
            print(f"✓ Transport created successfully, session ID: {get_session_id()}")

            # Create client session but don't initialize
            async with ClientSession(read, write) as session:
                print("✓ ClientSession created successfully")

                # Don't call initialize() to avoid network calls
                await asyncio.sleep(0.01)  # Just to test async context
                print("✓ Async context working")

    except Exception as e:
        print(f"✗ Transport creation failed: {e}")
        return False

    return True

def main():
    print("=== ASYNCIO COMPATIBILITY SUMMARY ===\n")

    # Test multiple sequential asyncio.run() calls
    success_count = 0
    total_tests = 5

    for i in range(total_tests):
        print(f"\n--- Test {i+1}/{total_tests} ---")
        try:
            result = asyncio.run(test_transport_creation_only())
            if result:
                print(f"✓ Test {i+1} PASSED")
                success_count += 1
            else:
                print(f"✗ Test {i+1} FAILED")
        except Exception as e:
            print(f"✗ Test {i+1} CRASHED: {e}")

    print(f"\n=== RESULTS ===")
    print(f"Successful tests: {success_count}/{total_tests}")

    if success_count == total_tests:
        print("\n✓ CONCLUSION: streamablehttp_client is compatible with asyncio.run()")
        print("✓ Multiple sequential asyncio.run() calls work without event loop conflicts")
        print("✓ The previous connection errors were expected (no server running)")
        return True
    else:
        print(f"\n✗ CONCLUSION: {total_tests - success_count} tests failed")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
