# MCP Test Client Strategy

## Executive Summary

**Recommendation: Build a test harness using the official MCP SDK before implementing pflow's MCPNode**

This approach de-risks our implementation by:
1. Validating our understanding of the MCP protocol
2. Testing against real MCP servers
3. Creating reference implementations for debugging
4. Understanding edge cases and error handling

## Verified Information (from official sources)

### Official Python SDK (`mcp`)
- **Source**: modelcontextprotocol/python-sdk (GitHub)
- **Installation**: `uv add "mcp[cli]"` or `pip install "mcp[cli]"`
- **Architecture**: Async-only (uses asyncio)
- **Transports**: stdio, SSE, Streamable HTTP, direct execution
- **Dependencies**: Includes httpx, websockets for full transport support

### MCP Inspector
- **Source**: modelcontextprotocol.io/docs/tools/inspector
- **Purpose**: Interactive debugging tool for MCP servers
- **Installation**: No install needed, runs via `npx`
- **Command**: `npx @modelcontextprotocol/inspector <server-command>`
- **Features**: Tools tab, Resources tab, Prompts tab, message logging

### Protocol Details (verified)
- **Format**: JSON-RPC 2.0 over newline-delimited messages (stdio)
- **Handshake**: Required `initialize` method first
- **Methods**: Namespaced like `tools/list`, `tools/call`
- **Tool schemas**: JSON Schema format for parameters
- **Content blocks**: Results returned as typed content (text, image, etc.)

---

## Test Setup Plan

### Phase 1: Quick Smoke Test (5 minutes)

```bash
# Test with Inspector - visual confirmation
npx -y @modelcontextprotocol/inspector npx @modelcontextprotocol/server-filesystem ~/Desktop

# What to verify:
# - Can see tools listed
# - Can call read_file tool
# - Can see results
```

### Phase 2: Python Test Client (30 minutes)

Create `/scratchpads/mcp-integration/test-client.py`:

```python
"""
MCP Test Client - Understanding the Protocol
This helps us understand what pflow needs to implement.
"""
import asyncio
import json
from typing import Any, Dict, List
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MCPTestClient:
    """Test client to understand MCP protocol behavior."""

    async def test_filesystem_server(self):
        """Test against the official filesystem MCP server."""
        print("=" * 60)
        print("Testing Filesystem MCP Server")
        print("=" * 60)

        # Start filesystem server
        params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                # 1. Initialize (handshake)
                print("\n1. INITIALIZE")
                await session.initialize()
                print("✓ Handshake complete")

                # 2. List available tools
                print("\n2. LIST TOOLS")
                tools = await session.list_tools()
                for tool in tools.tools:
                    print(f"  - {tool.name}: {tool.description}")
                    if hasattr(tool, 'inputSchema'):
                        print(f"    Input: {json.dumps(tool.inputSchema.model_dump(), indent=6)}")

                # 3. List resources
                print("\n3. LIST RESOURCES")
                resources = await session.list_resources()
                for resource in resources.resources[:5]:  # First 5
                    print(f"  - {resource.uri}")

                # 4. Call a tool
                print("\n4. CALL TOOL: read_file")
                # Create a test file first
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    f.write("Hello from MCP test!")
                    test_file = f.name

                result = await session.call_tool(
                    "read_file",
                    {"path": test_file}
                )

                print(f"  Result: {result}")
                for content in result.content or []:
                    if hasattr(content, 'text'):
                        print(f"  Content: {content.text}")

                # Clean up
                import os
                os.unlink(test_file)

    async def test_github_server(self):
        """Test against GitHub MCP server (if available)."""
        print("\n" + "=" * 60)
        print("Testing GitHub MCP Server")
        print("=" * 60)

        # This requires GITHUB_TOKEN env var
        import os
        if not os.environ.get("GITHUB_TOKEN"):
            print("⚠️  Skipping: GITHUB_TOKEN not set")
            return

        params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_TOKEN": os.environ["GITHUB_TOKEN"]}
        )

        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    print(f"Available tools: {[t.name for t in tools.tools]}")
        except Exception as e:
            print(f"⚠️  GitHub server test failed: {e}")

    async def test_json_rpc_raw(self):
        """Test raw JSON-RPC communication to understand protocol."""
        print("\n" + "=" * 60)
        print("Raw JSON-RPC Communication")
        print("=" * 60)

        import subprocess
        import json

        # Start server process
        proc = subprocess.Popen(
            ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        def send_request(method: str, params: Dict = None, id: int = 1):
            """Send JSON-RPC request and get response."""
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "id": id
            }
            if params:
                request["params"] = params

            request_str = json.dumps(request) + "\n"
            print(f"  → Request: {request_str.strip()}")
            proc.stdin.write(request_str)
            proc.stdin.flush()

            response_str = proc.stdout.readline()
            print(f"  ← Response: {response_str.strip()}")
            return json.loads(response_str)

        try:
            # Initialize
            response = send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {}
            })

            # List tools
            response = send_request("tools/list", id=2)

        finally:
            proc.terminate()

async def main():
    """Run all tests."""
    client = MCPTestClient()

    # Test different servers
    await client.test_filesystem_server()
    await client.test_github_server()
    await client.test_json_rpc_raw()

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print("✓ Filesystem server works")
    print("✓ JSON-RPC protocol understood")
    print("\nKey learnings for pflow implementation:")
    print("1. Handshake is required (initialize)")
    print("2. Tools have JSON Schema for inputs")
    print("3. Results come as content blocks")
    print("4. Everything is async in the SDK")
    print("5. Stdio uses newline-delimited JSON")

if __name__ == "__main__":
    asyncio.run(main())
```

### Phase 3: Protocol Analysis (1 hour)

Create a client that logs all JSON-RPC messages:

```python
"""
MCP Protocol Logger - Understand exact message format
"""
import asyncio
import json
from datetime import datetime

class ProtocolLogger:
    """Log all JSON-RPC messages for analysis."""

    def __init__(self, output_file="mcp-protocol-log.jsonl"):
        self.output_file = output_file
        self.messages = []

    async def log_session(self):
        """Log a complete MCP session."""
        # ... implementation that wraps stdio and logs all messages
```

---

## What We Learn for pflow

### 1. Protocol Details
- **Handshake**: Must send `initialize` first
- **Message format**: Newline-delimited JSON-RPC 2.0
- **Tool schemas**: JSON Schema in `inputSchema`
- **Results**: Come as `content` blocks (text, image, etc.)

### 2. Architecture Insights
- **Async everywhere**: SDK is fully async
- **Transport abstraction**: Clean separation of transport/session
- **Type safety**: Pydantic models for everything

### 3. Implementation Strategy

For pflow, we should:

1. **Build minimal sync wrapper** around async operations
2. **Focus on stdio only** (simplest transport)
3. **Reuse message formats** from SDK
4. **Keep it simple** - just enough for MCPNode

---

## Next Steps

1. **Today**: Run the test client to understand protocol
2. **Tomorrow**: Build minimal MCP client for pflow
3. **Day 3**: Integrate with MCPNode and registry

## Commands to Run Now

```bash
# 1. Install MCP SDK for testing
cd /Users/andfal/projects/pflow
uv add --dev "mcp[cli]"

# 2. Test with Inspector (visual)
npx -y @modelcontextprotocol/inspector npx @modelcontextprotocol/server-filesystem ~/Desktop

# 3. Run our test client
uv run python scratchpads/mcp-integration/test-client.py

# 4. Check what we learned
cat mcp-protocol-log.jsonl | jq .
```

---

## Decision: Build Test Client First ✅

**Yes, build the test client first because:**
1. De-risks the implementation
2. Validates our understanding
3. Provides reference for debugging
4. Takes only 1-2 hours
5. Helps us build the minimal client we actually need

The official SDK is perfect for testing but too heavy for pflow. We'll learn from it and build our own minimal implementation.