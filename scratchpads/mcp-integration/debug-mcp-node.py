#!/usr/bin/env python
"""Debug script to test MCPNode execution directly."""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pflow.mcp.manager import MCPServerManager
from pflow.nodes.mcp.node import MCPNode

# Set up detailed logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def test_mcp_node_sync():
    """Test MCPNode synchronously (how pflow calls it)."""
    print("\n" + "=" * 60)
    print("Testing MCPNode Synchronously")
    print("=" * 60)

    # Create node instance
    node = MCPNode()

    # Set parameters as compiler would
    params = {
        "__mcp_server__": "filesystem",
        "__mcp_tool__": "list_allowed_directories",
        # No other params needed for this tool
    }

    print(f"\nSetting params: {params}")
    node.set_params(params)

    # Create shared store
    shared = {}

    try:
        # Run prep
        print("\n1. Running prep()...")
        prep_res = node.prep(shared)
        print(f"   Prep result: {prep_res}")

        # Run exec
        print("\n2. Running exec()...")
        exec_res = node.exec(prep_res)
        print(f"   Exec result: {exec_res}")

        # Run post
        print("\n3. Running post()...")
        action = node.post(shared, prep_res, exec_res)
        print(f"   Action: {action}")
        print(f"   Shared store: {shared}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()


async def test_mcp_direct_async():
    """Test MCP protocol directly with async."""
    print("\n" + "=" * 60)
    print("Testing MCP Protocol Directly (Async)")
    print("=" * 60)

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # Load server config
    manager = MCPServerManager()
    config = manager.get_server("filesystem")

    if not config:
        print("❌ Filesystem server not configured")
        return

    print(f"\nServer config: {json.dumps(config, indent=2)}")

    # Prepare server parameters
    params = StdioServerParameters(command=config["command"], args=config.get("args", []), env=config.get("env", {}))

    print("\n1. Starting MCP server subprocess...")

    try:
        # Add timeout to prevent hanging
        async with asyncio.timeout(10):
            async with stdio_client(params) as (read, write):
                print("   ✓ Server subprocess started")

                async with ClientSession(read, write) as session:
                    print("   ✓ Client session created")

                    # Initialize handshake
                    print("\n2. Sending initialize...")
                    await session.initialize()
                    print("   ✓ Handshake complete")

                    # Call tool
                    print("\n3. Calling list_allowed_directories tool...")
                    result = await session.call_tool("list_allowed_directories", {})
                    print(f"   ✓ Tool result: {result}")

                    # Extract content
                    if hasattr(result, "content"):
                        for content in result.content or []:
                            if hasattr(content, "text"):
                                print(f"   Content: {content.text}")

                    print("\n4. Closing session...")
                    # Session closes automatically with context manager

            print("   ✓ Server subprocess terminated")

    except asyncio.TimeoutError:
        print("\n❌ Operation timed out after 10 seconds")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()


def test_asyncio_run_wrapper():
    """Test asyncio.run() wrapper pattern."""
    print("\n" + "=" * 60)
    print("Testing asyncio.run() Wrapper")
    print("=" * 60)

    async def async_func():
        print("   In async function")
        await asyncio.sleep(0.1)
        return "async result"

    print("\n1. Testing simple asyncio.run()...")
    try:
        result = asyncio.run(async_func())
        print(f"   ✓ Result: {result}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    print("\n2. Testing nested asyncio.run() (should fail)...")
    try:
        # This should fail if already in event loop
        result = asyncio.run(async_func())
        # Try to call asyncio.run again (simulating nested call)
        asyncio.run(async_func())
    except RuntimeError as e:
        if "cannot be called from a running event loop" in str(e):
            print(f"   ✓ Expected error: {e}")
        else:
            print(f"   ❌ Unexpected error: {e}")
    except Exception as e:
        print(f"   ❌ Other error: {e}")


def check_server_config():
    """Check if filesystem server is configured."""
    print("\n" + "=" * 60)
    print("Checking Server Configuration")
    print("=" * 60)

    manager = MCPServerManager()
    servers = manager.list_servers()

    print(f"\nConfigured servers: {servers}")

    if "filesystem" in servers:
        config = manager.get_server("filesystem")
        print("\nFilesystem server config:")
        print(json.dumps(config, indent=2))
        return True
    else:
        print("\n❌ Filesystem server not configured")
        print("   Run: pflow mcp add filesystem npx -- -y @modelcontextprotocol/server-filesystem /tmp")
        return False


def main():
    """Run all debug tests."""
    print("MCP Node Debug Script")
    print("=" * 60)

    # Check configuration
    if not check_server_config():
        return

    # Test asyncio.run wrapper
    test_asyncio_run_wrapper()

    # Test MCP protocol directly
    print("\nTesting MCP protocol directly...")
    asyncio.run(test_mcp_direct_async())

    # Test MCPNode
    print("\nTesting MCPNode (as pflow would call it)...")
    test_mcp_node_sync()

    print("\n" + "=" * 60)
    print("Debug Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
