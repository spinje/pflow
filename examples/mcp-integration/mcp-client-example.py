#!/usr/bin/env python
"""
MCP Client Reference Implementation
====================================

This file demonstrates how to implement an MCP CLIENT, complementing
mcp-protocol-reference.py which shows the SERVER side.

The examples progress from simple to complex:
1. Minimal viable client - just connect and call a tool
2. Production patterns - error handling and multiple servers
3. Async-to-sync bridge - the critical pattern pflow uses
4. How pflow implements it - simplified MCPNode demonstration

Prerequisites:
  pip install 'mcp[cli]'  # or: uv add 'mcp[cli]'

Run examples:
  python examples/mcp-integration/mcp-client-example.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional


# ==============================================================================
# PART 1: MINIMAL VIABLE MCP CLIENT
# This shows the absolute minimum needed to connect to an MCP server.
# ==============================================================================


class MinimalMCPClient:
    """The simplest possible MCP client implementation."""

    async def connect_and_list_tools(self) -> None:
        """
        Connect to a filesystem server and list available tools.

        This demonstrates the three mandatory steps:
        1. Create connection (stdio_client)
        2. Initialize handshake (session.initialize)
        3. Use the protocol (session.list_tools)
        """
        print("\n" + "=" * 60)
        print("MINIMAL CLIENT: Connect and List Tools")
        print("=" * 60)

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            print("ERROR: MCP SDK not installed. Run: pip install 'mcp[cli]'")
            return

        # Configure server - filesystem is simplest to test
        server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        )

        # Connect and interact
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Step 1: Mandatory handshake
                await session.initialize()
                print("✅ Connected and initialized")

                # Step 2: Discover tools
                tools = await session.list_tools()
                print(f"\n📦 Available tools ({len(tools.tools)}):")
                for tool in tools.tools[:5]:  # Show first 5
                    print(f"  • {tool.name}: {tool.description}")

    async def call_simple_tool(self) -> None:
        """
        Call a simple tool with no parameters.

        This shows how to execute a tool and handle the response.
        """
        print("\n" + "=" * 60)
        print("MINIMAL CLIENT: Call a Tool")
        print("=" * 60)

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call list_allowed_directories - no parameters needed
                print("\n📁 Calling list_allowed_directories...")
                result = await session.call_tool("list_allowed_directories", {})

                # Extract content from response
                if hasattr(result, "content"):
                    for content in result.content:
                        if hasattr(content, "text"):
                            print(f"  Result: {content.text}")


# ==============================================================================
# PART 2: PRODUCTION CLIENT PATTERNS
# Real-world patterns for robust MCP client implementation.
# ==============================================================================


class ProductionMCPClient:
    """Production-ready MCP client with error handling and multiple servers."""

    def __init__(self, server_name: str, server_config: dict):
        """
        Initialize with server configuration.

        Args:
            server_name: Identifier for this server (e.g., "filesystem", "github")
            server_config: Dict with command, args, and optional env
        """
        self.server_name = server_name
        self.server_config = server_config

    async def robust_initialize(self, max_retries: int = 3) -> Any:
        """
        Initialize with retry logic for transient failures.

        Shows how to handle:
        - Server startup failures
        - Network timeouts
        - Initialization errors
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        print(f"\n🔄 Connecting to {self.server_name} (with retries)...")

        for attempt in range(max_retries):
            try:
                server_params = StdioServerParameters(
                    command=self.server_config["command"],
                    args=self.server_config.get("args", []),
                    env=self.server_config.get("env", {})
                )

                async with stdio_client(server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        print(f"  ✅ Connected on attempt {attempt + 1}")

                        # Return the session info
                        tools = await session.list_tools()
                        return {"tools": len(tools.tools), "server": self.server_name}

            except Exception as e:
                print(f"  ⚠️ Attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(1)  # Wait before retry

    async def handle_tool_errors(self) -> None:
        """
        Demonstrate error handling when calling tools.

        Shows how to:
        - Handle missing parameters
        - Deal with permission errors
        - Extract error messages from responses
        """
        print("\n" + "=" * 60)
        print("ERROR HANDLING: Tool Execution Failures")
        print("=" * 60)

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to read a file that doesn't exist
                print("\n🔍 Testing error handling...")
                try:
                    result = await session.call_tool(
                        "read_file",
                        {"path": "/nonexistent/file.txt"}
                    )

                    # Check for error in response
                    if hasattr(result, "isError") and result.isError:
                        print("  ❌ Tool returned error flag")

                    # Extract error from content
                    if hasattr(result, "content"):
                        for content in result.content:
                            if hasattr(content, "text") and "error" in content.text.lower():
                                print(f"  ❌ Error: {content.text}")

                except Exception as e:
                    print(f"  ❌ Exception: {e}")

    @staticmethod
    async def multi_server_example() -> None:
        """
        Connect to multiple MCP servers in parallel.

        This pattern is useful for:
        - Aggregating tools from different sources
        - Building composite workflows
        - Load balancing across servers
        """
        print("\n" + "=" * 60)
        print("MULTIPLE SERVERS: Parallel Connections")
        print("=" * 60)

        servers = [
            {
                "name": "filesystem",
                "config": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
                }
            }
        ]

        # Add GitHub if token available
        if os.environ.get("GITHUB_TOKEN"):
            servers.append({
                "name": "github",
                "config": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": os.environ["GITHUB_TOKEN"]}
                }
            })

        # Connect to all servers in parallel
        tasks = []
        for server in servers:
            client = ProductionMCPClient(server["name"], server["config"])
            tasks.append(client.robust_initialize(max_retries=1))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        print("\n📊 Connection results:")
        for server, result in zip(servers, results):
            if isinstance(result, Exception):
                print(f"  • {server['name']}: ❌ Failed - {result}")
            else:
                print(f"  • {server['name']}: ✅ {result['tools']} tools")

    def expand_environment_variables(self, config: dict) -> dict:
        """
        Expand ${VAR} syntax in configuration values.

        This is critical for pflow's MCP implementation:
        - User configs can reference environment variables
        - Expansion happens at runtime, not config time
        - Supports both ${VAR} and $VAR syntax
        """
        import re

        expanded = config.copy()

        # Expand in args
        if "args" in expanded:
            expanded["args"] = [
                re.sub(r'\$\{([^}]+)\}', lambda m: os.environ.get(m.group(1), ''), arg)
                for arg in expanded["args"]
            ]

        # Expand in env
        if "env" in expanded:
            for key, value in expanded["env"].items():
                if isinstance(value, str):
                    expanded["env"][key] = re.sub(
                        r'\$\{([^}]+)\}',
                        lambda m: os.environ.get(m.group(1), ''),
                        value
                    )

        return expanded


# ==============================================================================
# PART 3: THE CRITICAL ASYNC-TO-SYNC BRIDGE
# This pattern is essential for pflow since PocketFlow nodes are synchronous
# but the MCP SDK is asynchronous.
# ==============================================================================


class AsyncToSyncWrapper:
    """
    Bridges async MCP SDK with sync PocketFlow nodes.

    This is the KEY PATTERN that makes MCP work in pflow:
    - PocketFlow nodes have sync exec() methods
    - MCP SDK only provides async methods
    - asyncio.run() creates a new event loop each time
    - This provides isolation and avoids conflicts
    """

    def __init__(self, server_name: str, tool_name: str):
        self.server_name = server_name
        self.tool_name = tool_name
        self.server_config = self._get_server_config(server_name)

    def _get_server_config(self, server_name: str) -> dict:
        """Get server configuration (simplified for example)."""
        configs = {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
            },
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", "")}
            }
        }
        return configs.get(server_name, configs["filesystem"])

    async def _execute_tool_async(self, arguments: dict) -> dict:
        """
        Async implementation that actually calls the MCP server.

        This is what runs inside asyncio.run() in the sync wrapper.
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=self.server_config["command"],
            args=self.server_config.get("args", []),
            env=self.server_config.get("env", {})
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(self.tool_name, arguments)

                # Extract content (simplified)
                if hasattr(result, "content") and result.content:
                    for content in result.content:
                        if hasattr(content, "text"):
                            return {"result": content.text}

                return {"result": str(result)}

    def execute_tool(self, arguments: dict) -> dict:
        """
        SYNCHRONOUS method that wraps async MCP calls.

        This is the pattern used in pflow's MCPNode.exec() method.
        Each call creates a new event loop via asyncio.run().

        Why this works:
        - asyncio.run() is designed for this use case
        - Each call is isolated (new event loop)
        - No event loop conflicts or leakage
        - Clean subprocess lifecycle management
        """
        try:
            # THE CRITICAL LINE - async to sync bridge
            return asyncio.run(self._execute_tool_async(arguments))
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def demonstrate_pattern():
        """Show the async-to-sync pattern in action."""
        print("\n" + "=" * 60)
        print("ASYNC-TO-SYNC BRIDGE: The pflow Pattern")
        print("=" * 60)

        # Create wrapper for a specific tool
        wrapper = AsyncToSyncWrapper("filesystem", "list_allowed_directories")

        # Call from synchronous context (like PocketFlow's exec())
        print("\n🔄 Calling async MCP from sync context...")
        result = wrapper.execute_tool({})  # Sync call!

        print(f"✅ Sync result: {result}")

        # This is exactly what happens in pflow's MCPNode:
        print("\n📝 In pflow's MCPNode, this pattern looks like:")
        print("""
        def exec(self, prep_res: dict) -> dict:
            # Synchronous method required by PocketFlow
            return asyncio.run(self._exec_async(prep_res))

        async def _exec_async(self, prep_res: dict) -> dict:
            # Async implementation using MCP SDK
            ...
        """)


# ==============================================================================
# PART 4: HOW PFLOW IMPLEMENTS MCP
# Simplified version of pflow's actual MCPNode implementation.
# ==============================================================================


class SimplifiedMCPNode:
    """
    Simplified version of pflow's MCPNode.

    This demonstrates:
    - Virtual node concept (one class, many tools)
    - Metadata injection pattern
    - Shared store integration
    - Why universality matters
    """

    def __init__(self):
        """Initialize node (called by PocketFlow)."""
        self.server_name = None
        self.tool_name = None

    def set_params(self, params: dict) -> None:
        """
        Receive parameters including injected metadata.

        The compiler injects special parameters for MCP nodes:
        - __mcp_server__: Which server to connect to
        - __mcp_tool__: Which tool to execute

        This is how one MCPNode class handles ALL MCP tools!
        """
        # Extract injected metadata (added by compiler)
        self.server_name = params.pop("__mcp_server__", None)
        self.tool_name = params.pop("__mcp_tool__", None)

        # Regular parameters become tool arguments
        self.tool_args = params

        print(f"\n🔧 Virtual node configured:")
        print(f"  Server: {self.server_name}")
        print(f"  Tool: {self.tool_name}")
        print(f"  Args: {self.tool_args}")

    def prep(self, shared: dict) -> dict:
        """
        Prepare for execution (PocketFlow lifecycle).

        In real MCPNode:
        - Validates configuration
        - Expands environment variables
        - Prepares arguments for tool
        """
        print(f"\n📋 Preparing MCP tool: {self.server_name}-{self.tool_name}")

        # Template resolution would happen here in real implementation
        resolved_args = self.tool_args.copy()

        return {
            "server": self.server_name,
            "tool": self.tool_name,
            "arguments": resolved_args
        }

    def exec(self, prep_res: dict) -> dict:
        """
        Execute the MCP tool (sync method as required by PocketFlow).

        This is where the async-to-sync bridge is CRITICAL!
        """
        # Create wrapper for this specific tool
        wrapper = AsyncToSyncWrapper(prep_res["server"], prep_res["tool"])

        # Execute synchronously (asyncio.run() inside)
        return wrapper.execute_tool(prep_res["arguments"])

    def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        """
        Post-process results (PocketFlow lifecycle).

        In real MCPNode:
        - Stores result in shared store
        - Extracts individual fields for easy access
        - Returns action for flow control
        """
        # Store main result
        shared["result"] = exec_res.get("result", exec_res.get("error"))

        # In real implementation, structured data fields are extracted:
        # If result is {"temp": 22, "humidity": 65}
        # Then: shared["temp"] = 22, shared["humidity"] = 65

        print(f"\n💾 Stored in shared: {list(shared.keys())}")

        return "default"  # Action for flow control

    @staticmethod
    def demonstrate_virtual_nodes():
        """
        Show how virtual nodes work in pflow.

        Key insight: The registry has many entries, but they all
        point to the same MCPNode class with different metadata.
        """
        print("\n" + "=" * 60)
        print("VIRTUAL NODES: One Class, Many Tools")
        print("=" * 60)

        print("\n📚 Registry entries (simplified):")
        registry_entries = {
            "mcp-filesystem-read_file": {
                "class_name": "MCPNode",
                "file_path": "virtual://mcp",  # Not a real file!
            },
            "mcp-filesystem-write_file": {
                "class_name": "MCPNode",  # Same class!
                "file_path": "virtual://mcp",
            },
            "mcp-github-create_issue": {
                "class_name": "MCPNode",  # Same class!
                "file_path": "virtual://mcp",
            },
        }

        for node_type, entry in registry_entries.items():
            print(f"  • {node_type} → {entry['class_name']}")

        print("\n🎯 Compiler metadata injection:")
        print("""
        When compiler sees node type "mcp-filesystem-read_file":
        1. Splits on "-" → ["mcp", "filesystem", "read_file"]
        2. Injects params["__mcp_server__"] = "filesystem"
        3. Injects params["__mcp_tool__"] = "read_file"
        4. MCPNode receives this metadata and knows what to do
        """)

        print("\n⚡ Why this matters:")
        print("  • No code generation needed")
        print("  • New MCP servers work without code changes")
        print("  • One universal node handles everything")
        print("  • Clean separation of concerns")

    @staticmethod
    def demonstrate_universality():
        """
        Show why MCPNode must remain universal (no server-specific code).
        """
        print("\n" + "=" * 60)
        print("UNIVERSALITY: Why No Server-Specific Code")
        print("=" * 60)

        print("\n❌ NEVER do this in MCPNode:")
        print("""
        # BAD - Server-specific logic
        if self.server_name == "filesystem":
            args["path"] = os.path.abspath(args["path"])
        elif self.server_name == "github":
            args["token"] = self.validate_github_token(args["token"])
        """)

        print("\n✅ INSTEAD, MCPNode is just a protocol client:")
        print("""
        # GOOD - Universal protocol client
        result = await session.call_tool(self.tool_name, self.tool_args)
        # That's it! Server handles its own logic
        """)

        print("\n🎯 This universality means:")
        print("  • Tomorrow's MCP servers work today")
        print("  • No maintenance burden as ecosystem grows")
        print("  • Clean architecture with single responsibility")


# ==============================================================================
# MAIN: Run all examples to demonstrate the concepts
# ==============================================================================


async def main():
    """Run all example sections in sequence."""

    print("""
╔══════════════════════════════════════════════════════════════╗
║          MCP Client Reference Implementation                 ║
║                                                              ║
║  This demonstrates how to implement MCP clients,            ║
║  progressing from simple to pflow's actual approach.        ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # Part 1: Minimal Client
    minimal = MinimalMCPClient()
    await minimal.connect_and_list_tools()
    await minimal.call_simple_tool()

    # Part 2: Production Patterns
    await ProductionMCPClient.multi_server_example()

    prod_client = ProductionMCPClient(
        "filesystem",
        {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        }
    )
    await prod_client.handle_tool_errors()

    # Part 3: Async-to-Sync Bridge
    AsyncToSyncWrapper.demonstrate_pattern()

    # Part 4: How pflow Does It
    SimplifiedMCPNode.demonstrate_virtual_nodes()
    SimplifiedMCPNode.demonstrate_universality()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY: Key Takeaways")
    print("=" * 60)
    print("""
📚 What we learned:
1. MCP clients need: initialize → list_tools → call_tool
2. Production clients need error handling and retries
3. The async-to-sync bridge is critical for pflow
4. Virtual nodes let one class handle all MCP tools
5. Universality (no server code) ensures future compatibility

🔗 Related files:
• mcp-protocol-reference.py - How servers should behave
• mcp-debugging.py - Tools for troubleshooting
• /src/pflow/nodes/mcp/node.py - Actual implementation

🎯 The pflow approach:
• Virtual nodes in registry point to MCPNode class
• Compiler injects __mcp_server__ and __mcp_tool__
• MCPNode uses asyncio.run() for sync interface
• No server-specific code ensures universality
    """)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
