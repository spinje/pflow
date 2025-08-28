#!/usr/bin/env python
"""
MCP Test Client - Understanding the Protocol
This helps us understand what pflow needs to implement for MCP server support.

Run with:
  uv run python scratchpads/mcp-integration/test-client.py

Prerequisites:
  uv add --dev "mcp[cli]"
"""

import asyncio
import json
import os
import tempfile
from typing import Optional


class MCPTestClient:
    """Test client to understand MCP protocol behavior."""

    async def test_filesystem_server(self):
        """Test against the official filesystem MCP server."""
        print("=" * 60)
        print("Testing Filesystem MCP Server")
        print("=" * 60)

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            print("ERROR: MCP SDK not installed. Run: uv add --dev 'mcp[cli]'")
            return

        # Start filesystem server pointing to /tmp
        params = StdioServerParameters(command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"])

        try:
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                # 1. Initialize (handshake)
                print("\n1. INITIALIZE (Handshake)")
                await session.initialize()
                print("✓ Handshake complete")

                # 2. List available tools
                print("\n2. LIST TOOLS")
                tools = await session.list_tools()
                for tool in tools.tools:
                    print(f"  - {tool.name}: {tool.description}")
                    if hasattr(tool, "inputSchema") and tool.inputSchema:
                        schema_dict = tool.inputSchema
                        if hasattr(schema_dict, "model_dump"):
                            schema_dict = schema_dict.model_dump()
                        print(f"    Input schema: {json.dumps(schema_dict, indent=6)}")

                # 3. List resources (first 5)
                print("\n3. LIST RESOURCES")
                try:
                    resources = await session.list_resources()
                    for resource in resources.resources[:5]:
                        print(f"  - {resource.uri}")
                        if hasattr(resource, "name"):
                            print(f"    Name: {resource.name}")
                except Exception as e:
                    print(f"  ⚠️  Could not list resources: {e}")

                # 4. Call a tool - create test file and read it
                print("\n4. CALL TOOL: read_file")

                # Create a test file
                with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                    f.write("Hello from MCP test client!\nThis is a test of the MCP protocol.")
                    test_file = f.name

                print(f"  Created test file: {test_file}")

                # Call read_file tool
                result = await session.call_tool("read_file", {"path": test_file})

                print(f"  Tool result type: {type(result)}")

                # Extract content from result
                if hasattr(result, "content"):
                    for content in result.content or []:
                        if hasattr(content, "text"):
                            print(f"  File content:\n    {content.text}")
                        else:
                            print(f"  Content type: {type(content)}")

                # Clean up test file
                os.unlink(test_file)
                print("  ✓ Test file cleaned up")

        except Exception as e:
            print(f"\n⚠️  Filesystem server test failed: {e}")
            import traceback

            traceback.print_exc()

    async def test_github_server(self):
        """Test against GitHub MCP server (if GITHUB_TOKEN is available)."""
        print("\n" + "=" * 60)
        print("Testing GitHub MCP Server")
        print("=" * 60)

        # Check for GitHub token
        if not os.environ.get("GITHUB_TOKEN"):
            print("⚠️  Skipping: GITHUB_TOKEN not set in environment")
            print("  To test GitHub MCP server, set GITHUB_TOKEN environment variable")
            return

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            print("ERROR: MCP SDK not installed")
            return

        params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_TOKEN": os.environ["GITHUB_TOKEN"]},
        )

        try:
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                # Initialize
                await session.initialize()
                print("✓ Connected to GitHub MCP server")

                # List tools
                tools = await session.list_tools()
                print(f"\nAvailable GitHub tools ({len(tools.tools)}):")
                for tool in tools.tools[:10]:  # Show first 10
                    print(f"  - {tool.name}: {tool.description}")

                if len(tools.tools) > 10:
                    print(f"  ... and {len(tools.tools) - 10} more")

        except Exception as e:
            print(f"⚠️  GitHub server test failed: {e}")

    async def test_json_rpc_raw(self):
        """Test raw JSON-RPC communication to understand the protocol at a low level."""
        print("\n" + "=" * 60)
        print("Raw JSON-RPC Communication Test")
        print("=" * 60)

        import json
        import subprocess

        # Start server process manually
        print("\nStarting MCP server subprocess...")
        proc = subprocess.Popen(
            ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def send_request(method: str, params: Optional[dict] = None, request_id: int = 1) -> dict:
            """Send JSON-RPC request and get response."""
            request = {"jsonrpc": "2.0", "method": method, "id": request_id}
            if params is not None:
                request["params"] = params

            request_str = json.dumps(request) + "\n"
            print(f"  → Request: {request_str.strip()}")
            proc.stdin.write(request_str)
            proc.stdin.flush()

            response_str = proc.stdout.readline()
            print(f"  ← Response: {response_str.strip()[:200]}...")  # Truncate long responses

            try:
                return json.loads(response_str)
            except json.JSONDecodeError as e:
                print(f"    ERROR: Failed to parse response: {e}")
                return {}

        try:
            # Test initialize
            print("\n1. Testing initialize...")
            response = send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "pflow-test-client", "version": "1.0.0"},
                },
                request_id=1,
            )

            if "result" in response:
                print("  ✓ Initialize successful")
                server_info = response.get("result", {}).get("serverInfo", {})
                if server_info:
                    print(f"    Server: {server_info.get('name')} v{server_info.get('version')}")

            # Test tools/list
            print("\n2. Testing tools/list...")
            response = send_request("tools/list", {}, request_id=2)

            if "result" in response:
                tools = response.get("result", {}).get("tools", [])
                print(f"  ✓ Found {len(tools)} tools")
                for tool in tools[:3]:  # Show first 3
                    print(f"    - {tool.get('name')}")

        finally:
            # Clean up
            print("\nTerminating server process...")
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            print("  ✓ Server process terminated")

    async def test_async_to_sync_wrapper(self):
        """Test pattern for wrapping async MCP calls in sync functions."""
        print("\n" + "=" * 60)
        print("Async-to-Sync Wrapper Pattern Test")
        print("=" * 60)

        async def _async_list_tools() -> list[str]:
            """Async implementation."""
            try:
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client
            except ImportError:
                return ["ERROR: MCP SDK not installed"]

            params = StdioServerParameters(
                command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
            )

            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [t.name for t in tools.tools]

        def sync_list_tools() -> list[str]:
            """Synchronous wrapper around async MCP call."""
            return asyncio.run(_async_list_tools())

        # Test the sync wrapper
        print("\nCalling async function from sync context...")
        tool_names = sync_list_tools()
        print("✓ Successfully called async function synchronously")
        print(f"  Found tools: {tool_names}")


async def main():
    """Run all tests."""
    client = MCPTestClient()

    # Run tests
    await client.test_filesystem_server()
    await client.test_github_server()
    await client.test_json_rpc_raw()
    await client.test_async_to_sync_wrapper()

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print("\n✅ Key learnings for pflow MCP implementation:")
    print("1. Handshake via initialize() is mandatory")
    print("2. Tools have JSON Schema for input validation")
    print("3. Results come as content blocks with text/image/etc")
    print("4. Everything in SDK is async (needs asyncio.run wrapper)")
    print("5. Stdio transport uses newline-delimited JSON-RPC 2.0")
    print("6. Server subprocess management needs proper cleanup")
    print("\n📝 Next steps:")
    print("1. Install MCP SDK: uv add --dev 'mcp[cli]'")
    print("2. Run this test: uv run python scratchpads/mcp-integration/test-client.py")
    print("3. Implement MCPNode with async wrapper")
    print("4. Add compiler metadata injection")
    print("5. Create CLI commands for MCP management")


if __name__ == "__main__":
    print("MCP Test Client - Protocol Validation")
    print("=====================================\n")

    # Check if running in an event loop already
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" in str(e):
            print("ERROR: Already running in event loop. Use await main() instead.")
        else:
            raise
