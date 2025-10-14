#!/usr/bin/env python
"""Real-world integration test for the MCP server.

This tests the actual MCP protocol communication, not just unit tests.
"""

import asyncio
import json
import sys


async def test_real_server():
    """Test the real MCP server with actual protocol communication."""
    try:
        # Import MCP client components
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        print("Starting real MCP server test...")

        # Start the server as a subprocess
        server_process = await asyncio.create_subprocess_exec(
            "uv",
            "run",
            "pflow",
            "mcp",
            "serve",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        print("✅ Server process started")

        # Create a client session
        async with stdio_client(server_process) as (read, write):
            async with ClientSession(read, write) as session:
                print("✅ Client connected to server")

                # Initialize the connection
                await session.initialize()
                print("✅ Session initialized")

                # List available tools
                tools = await session.list_tools()
                print(f"✅ Found {len(tools)} tools:")

                # Show first few tools
                for tool in tools[:5]:
                    print(f"   - {tool.name}: {tool.description[:50]}...")

                # Test a simple tool (ping)
                result = await session.call_tool("ping", {"echo": "test"})
                print(f"✅ Ping tool worked: {result}")

                # Test workflow_validate
                test_workflow = {
                    "ir_version": "0.1.0",
                    "nodes": [{"id": "test", "type": "test-node-simple", "params": {}}],
                    "edges": [],
                }

                result = await session.call_tool("workflow_validate", {"workflow": test_workflow})
                print(f"✅ Workflow validation: valid={result.get('valid')}")

                return True

    except ImportError as e:
        print(f"❌ MCP client not installed: {e}")
        print("Install with: pip install mcp")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        # Cleanup
        if "server_process" in locals():
            server_process.terminate()
            await server_process.wait()


async def test_server_startup():
    """Test that the server starts without errors."""
    try:
        print("\nTesting server startup...")

        # Start server and check it doesn't crash immediately
        process = await asyncio.create_subprocess_exec(
            "uv",
            "run",
            "pflow",
            "mcp",
            "serve",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Give it a moment to start
        await asyncio.sleep(1)

        # Check if still running
        if process.returncode is None:
            print("✅ Server is running")

            # Send a basic JSON-RPC request
            request = (
                json.dumps({
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    },
                    "id": 1,
                })
                + "\n"
            )

            # Send request
            process.stdin.write(request.encode())
            await process.stdin.drain()

            # Try to read response (with timeout)
            try:
                response = await asyncio.wait_for(process.stdout.readline(), timeout=5.0)

                if response:
                    data = json.loads(response.decode())
                    print(f"✅ Got response: {data.get('result', {}).get('protocolVersion')}")
                    return True
                else:
                    print("❌ No response from server")
                    return False

            except asyncio.TimeoutError:
                print("❌ Server didn't respond (timeout)")
                # Check stderr for errors
                stderr = await process.stderr.read(1000)
                if stderr:
                    print(f"Server errors:\n{stderr.decode()}")
                return False

        else:
            # Process exited
            stderr = await process.stderr.read()
            print(f"❌ Server crashed: {stderr.decode()}")
            return False

    except Exception as e:
        print(f"❌ Startup test failed: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        if "process" in locals():
            process.terminate()
            await process.wait()


def main():
    """Run all real-world tests."""
    print("=" * 60)
    print("MCP Server Real-World Integration Tests")
    print("=" * 60)

    # Test server startup with basic protocol
    success = asyncio.run(test_server_startup())

    # Only run full client test if MCP client is available
    try:
        import mcp

        print("\nRunning full client test...")
        client_success = asyncio.run(test_real_server())
        success = success and client_success
    except ImportError:
        print("\n⚠️ Skipping full client test (mcp package not installed)")
        print("The server is working with basic JSON-RPC protocol")

    if success:
        print("\n🎉 MCP server is working!")
        print("\nTo use with Claude Desktop, add this to your config:")
        print(
            json.dumps(
                {
                    "mcpServers": {
                        "pflow": {"command": "uv", "args": ["run", "pflow", "mcp", "serve"], "cwd": "/path/to/pflow"}
                    }
                },
                indent=2,
            )
        )
        return 0
    else:
        print("\n❌ MCP server has issues that need fixing")
        return 1


if __name__ == "__main__":
    sys.exit(main())
