#!/usr/bin/env python
"""
MCP Debugging Utilities
=======================

Tools for troubleshooting MCP connections and protocol issues.

Usage:
  python examples/mcp-integration/mcp-debugging.py test filesystem
  python examples/mcp-integration/mcp-debugging.py inspect filesystem list_allowed_directories
  python examples/mcp-integration/mcp-debugging.py repl
  python examples/mcp-integration/mcp-debugging.py diagnose --all

Commands:
  test <server>     - Quick connectivity test for a server
  inspect <server> <tool> - Detailed protocol inspection for a tool call
  repl              - Interactive REPL for sending custom commands
  diagnose          - Run comprehensive diagnostics

Prerequisites:
  pip install 'mcp[cli]'  # or: uv add 'mcp[cli]'
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ==============================================================================
# SECTION 1: QUICK DIAGNOSTICS
# Fast tests to verify basic MCP connectivity and functionality.
# ==============================================================================


class QuickDiagnostics:
    """Quick tests for MCP server connectivity."""

    @staticmethod
    def get_server_config(server_name: str) -> Dict[str, Any]:
        """Get configuration for known servers."""
        configs = {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                "test_tool": "list_allowed_directories",
                "test_args": {}
            },
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", "")},
                "test_tool": "list_repositories",
                "test_args": {}
            },
            "slack": {
                "command": "npx",
                "args": ["-y", "@zencoderai/slack-mcp-server"],
                "env": {
                    "SLACK_BOT_TOKEN": os.environ.get("SLACK_BOT_TOKEN", ""),
                    "SLACK_TEAM_ID": os.environ.get("SLACK_TEAM_ID", "")
                },
                "test_tool": "slack_get_users",
                "test_args": {}
            }
        }

        if server_name not in configs:
            # Return generic config for unknown servers
            return {
                "command": "npx",
                "args": ["-y", f"@modelcontextprotocol/server-{server_name}"],
                "test_tool": None,
                "test_args": {}
            }

        return configs[server_name]

    async def test_server_startup(self, server_name: str) -> bool:
        """Test if a server can start and initialize."""
        print(f"\n🔍 Testing {server_name} server startup...")

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            print("  ❌ MCP SDK not installed. Run: pip install 'mcp[cli]'")
            return False

        config = self.get_server_config(server_name)

        # Check environment variables if needed
        if "env" in config:
            missing_vars = []
            for var, value in config["env"].items():
                if not value:
                    missing_vars.append(var)

            if missing_vars:
                print(f"  ⚠️ Missing environment variables: {', '.join(missing_vars)}")
                print(f"     Set these before testing {server_name}")
                return False

        # Try to start and connect
        print(f"  📡 Starting server process...")
        start_time = time.time()

        try:
            server_params = StdioServerParameters(
                command=config["command"],
                args=config.get("args", []),
                env=config.get("env", {})
            )

            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    # Test initialization
                    await session.initialize()
                    elapsed = time.time() - start_time
                    print(f"  ✅ Server started and initialized in {elapsed:.2f}s")

                    # List available tools
                    tools = await session.list_tools()
                    print(f"  📦 Found {len(tools.tools)} tools")

                    # Show first few tools
                    for tool in tools.tools[:3]:
                        print(f"     • {tool.name}")
                    if len(tools.tools) > 3:
                        print(f"     ... and {len(tools.tools) - 3} more")

                    # Test a tool if configured
                    if config.get("test_tool"):
                        print(f"  🧪 Testing tool: {config['test_tool']}")
                        try:
                            result = await session.call_tool(
                                config["test_tool"],
                                config.get("test_args", {})
                            )
                            print(f"  ✅ Tool call successful")
                        except Exception as e:
                            print(f"  ⚠️ Tool call failed: {e}")

                    return True

        except Exception as e:
            print(f"  ❌ Failed to start server: {e}")
            return False

    async def test_all_servers(self) -> None:
        """Test all configured servers."""
        servers = ["filesystem", "github", "slack"]

        print("\n" + "=" * 60)
        print("TESTING ALL CONFIGURED SERVERS")
        print("=" * 60)

        results = {}
        for server in servers:
            results[server] = await self.test_server_startup(server)

        # Summary
        print("\n📊 Test Summary:")
        for server, success in results.items():
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"  {server}: {status}")


# ==============================================================================
# SECTION 2: PROTOCOL INSPECTOR
# Detailed inspection of MCP protocol messages and responses.
# ==============================================================================


class ProtocolInspector:
    """Inspect MCP protocol messages at a low level."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.messages = []

    def capture_raw_communication(self, server_name: str) -> None:
        """
        Capture raw JSON-RPC communication with a server.

        This uses subprocess directly to see the actual protocol messages.
        """
        print(f"\n🔬 Inspecting raw protocol for {server_name}")
        print("=" * 60)

        config = QuickDiagnostics.get_server_config(server_name)

        # Start server subprocess
        print(f"Starting subprocess: {config['command']} {' '.join(config['args'])}")
        proc = subprocess.Popen(
            [config["command"]] + config.get("args", []),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, **config.get("env", {})}
        )

        def send_and_receive(method: str, params: dict = None, req_id: int = 1) -> dict:
            """Send JSON-RPC request and capture response."""
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "id": req_id
            }
            if params is not None:
                request["params"] = params

            # Send request
            request_str = json.dumps(request)
            print(f"\n→ REQUEST [{req_id}]:")
            print(json.dumps(request, indent=2))

            proc.stdin.write(request_str + "\n")
            proc.stdin.flush()

            # Get response
            response_str = proc.stdout.readline()
            try:
                response = json.loads(response_str)
                print(f"\n← RESPONSE [{req_id}]:")

                # Pretty print but truncate large responses
                response_pretty = json.dumps(response, indent=2)
                if len(response_pretty) > 1000 and not self.verbose:
                    print(response_pretty[:1000] + "\n... [truncated]")
                else:
                    print(response_pretty)

                self.messages.append({
                    "request": request,
                    "response": response,
                    "timestamp": datetime.now().isoformat()
                })

                return response

            except json.JSONDecodeError as e:
                print(f"Failed to parse response: {e}")
                print(f"Raw: {response_str[:200]}")
                return {}

        try:
            # 1. Initialize
            response = send_and_receive(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "mcp-debugger",
                        "version": "1.0.0"
                    }
                },
                req_id=1
            )

            # 2. List tools
            response = send_and_receive("tools/list", {}, req_id=2)

            # 3. Call a tool if available
            if response.get("result", {}).get("tools"):
                first_tool = response["result"]["tools"][0]
                print(f"\n🧪 Testing tool: {first_tool['name']}")

                # Prepare arguments based on schema
                test_args = {}
                if "inputSchema" in first_tool:
                    schema = first_tool["inputSchema"]
                    if schema.get("properties"):
                        # Use empty/default values for required fields
                        for prop, spec in schema["properties"].items():
                            if prop in schema.get("required", []):
                                if spec.get("type") == "string":
                                    test_args[prop] = ""
                                elif spec.get("type") == "number":
                                    test_args[prop] = 0
                                elif spec.get("type") == "boolean":
                                    test_args[prop] = False

                send_and_receive(
                    "tools/call",
                    {
                        "name": first_tool["name"],
                        "arguments": test_args
                    },
                    req_id=3
                )

        finally:
            # Cleanup
            print("\n🛑 Terminating subprocess...")
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            print("✅ Subprocess terminated")

    def decode_content_blocks(self, result: dict) -> None:
        """Decode and display content blocks from a tool result."""
        print("\n📦 Content Blocks Analysis:")

        if "content" in result:
            for i, content in enumerate(result["content"]):
                print(f"\n  Block {i + 1}:")

                if hasattr(content, "__dict__"):
                    # Object with attributes
                    for key, value in content.__dict__.items():
                        if not key.startswith("_"):
                            print(f"    {key}: {value[:100] if isinstance(value, str) else value}")
                elif isinstance(content, dict):
                    # Dictionary
                    for key, value in content.items():
                        print(f"    {key}: {value[:100] if isinstance(value, str) else value}")
                else:
                    # Other types
                    print(f"    Type: {type(content)}")
                    print(f"    Value: {str(content)[:100]}")

        if "structuredContent" in result:
            print(f"\n  Structured Content:")
            print(json.dumps(result["structuredContent"], indent=4))

        if result.get("isError"):
            print(f"\n  ⚠️ Tool returned error flag")

    async def inspect_tool_call(self, server_name: str, tool_name: str, args: dict = None) -> None:
        """Inspect a specific tool call in detail."""
        print(f"\n🔍 Inspecting {server_name}:{tool_name}")
        print("=" * 60)

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            print("❌ MCP SDK not installed")
            return

        config = QuickDiagnostics.get_server_config(server_name)
        server_params = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env", {})
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Get tool info
                tools = await session.list_tools()
                tool_info = None
                for tool in tools.tools:
                    if tool.name == tool_name:
                        tool_info = tool
                        break

                if not tool_info:
                    print(f"❌ Tool '{tool_name}' not found")
                    return

                # Show tool schema
                print(f"\n📋 Tool Schema:")
                print(f"  Name: {tool_info.name}")
                print(f"  Description: {tool_info.description}")

                if hasattr(tool_info, "inputSchema") and tool_info.inputSchema:
                    print(f"\n  Input Schema:")
                    schema_dict = tool_info.inputSchema
                    if hasattr(schema_dict, "model_dump"):
                        schema_dict = schema_dict.model_dump()
                    print(json.dumps(schema_dict, indent=4))

                # Call the tool
                print(f"\n🚀 Calling tool with args: {args or {}}")
                start_time = time.time()

                try:
                    result = await session.call_tool(tool_name, args or {})
                    elapsed = time.time() - start_time

                    print(f"✅ Tool executed in {elapsed:.3f}s")

                    # Analyze result
                    self.decode_content_blocks({"content": result.content if hasattr(result, "content") else []})

                except Exception as e:
                    print(f"❌ Tool execution failed: {e}")


# ==============================================================================
# SECTION 3: COMMON ISSUES DEBUGGER
# Diagnose and fix common MCP integration issues.
# ==============================================================================


class IssueDebugger:
    """Debug common MCP issues with actionable solutions."""

    def check_path_permissions(self, path: str) -> None:
        """
        Check filesystem path permissions and symlink resolution.

        Common issue: /tmp vs /private/tmp on macOS
        """
        print(f"\n🔍 Checking path: {path}")
        print("=" * 60)

        path_obj = Path(path)

        # Check if path exists
        if path_obj.exists():
            print(f"✅ Path exists")
            print(f"  Type: {'Directory' if path_obj.is_dir() else 'File'}")
            print(f"  Absolute: {path_obj.absolute()}")
            print(f"  Resolved: {path_obj.resolve()}")

            # Check permissions
            if os.access(path, os.R_OK):
                print(f"  Read: ✅")
            else:
                print(f"  Read: ❌")

            if os.access(path, os.W_OK):
                print(f"  Write: ✅")
            else:
                print(f"  Write: ❌")
        else:
            print(f"❌ Path does not exist")

            # Check parent directory
            parent = path_obj.parent
            if parent.exists():
                print(f"  Parent exists: {parent}")
            else:
                print(f"  Parent missing: {parent}")

        # macOS specific checks
        if sys.platform == "darwin" and "/tmp" in path:
            print(f"\n⚠️ macOS /tmp symlink detected!")
            print(f"  /tmp → /private/tmp (symlink)")
            print(f"  MCP servers see: /private/tmp")
            print(f"  Solution: Use /private/tmp in configurations")

    def verify_environment_variables(self, server_name: str) -> bool:
        """Check if required environment variables are set."""
        print(f"\n🔍 Checking environment for {server_name}")
        print("=" * 60)

        required_vars = {
            "github": ["GITHUB_TOKEN"],
            "slack": ["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
            "openai": ["OPENAI_API_KEY"],
        }

        if server_name not in required_vars:
            print(f"  No specific environment variables required")
            return True

        all_set = True
        for var in required_vars[server_name]:
            value = os.environ.get(var)
            if value:
                # Mask the value for security
                masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
                print(f"  {var}: ✅ (set to {masked})")
            else:
                print(f"  {var}: ❌ (not set)")
                all_set = False

        if not all_set:
            print(f"\n  Solution: Set missing variables before running:")
            for var in required_vars[server_name]:
                if not os.environ.get(var):
                    print(f"    export {var}=your_value_here")

        return all_set

    def test_type_conversion(self) -> None:
        """
        Test parameter type conversion issues.

        Common issue: Template resolver converting numbers to strings
        """
        print("\n🔍 Testing Type Conversion")
        print("=" * 60)

        test_cases = [
            ("limit", "3", int, 3),  # Should be number
            ("enabled", "true", bool, True),  # Should be boolean
            ("threshold", "3.14", float, 3.14),  # Should be float
            ("name", "test", str, "test"),  # Should stay string
        ]

        print("Testing parameter type preservation:")
        for param, value, expected_type, expected_value in test_cases:
            # Simulate what template resolver should do
            if value.isdigit():
                converted = int(value)
            elif value in ["true", "false"]:
                converted = value == "true"
            elif "." in value and value.replace(".", "").isdigit():
                converted = float(value)
            else:
                converted = value

            if type(converted) == expected_type and converted == expected_value:
                print(f"  {param}: '{value}' → {converted} ({type(converted).__name__}) ✅")
            else:
                print(f"  {param}: '{value}' → {converted} ({type(converted).__name__}) ❌")
                print(f"    Expected: {expected_value} ({expected_type.__name__})")

    def diagnose_task_group_error(self) -> None:
        """
        Diagnose "unhandled errors in a TaskGroup" errors.

        Common causes:
        1. Multiple server processes (retry bug)
        2. Type mismatches in parameters
        3. Missing required parameters
        """
        print("\n🔍 Diagnosing TaskGroup Errors")
        print("=" * 60)

        print("\nCommon causes and solutions:")

        print("\n1. Multiple Server Processes (Retry Bug)")
        print("  Symptom: 'Starting server' appears multiple times")
        print("  Cause: Each retry starts new subprocess")
        print("  Solution: Set max_retries=1 in MCPNode")

        print("\n2. Type Mismatches")
        print("  Symptom: TaskGroup error with type-related message")
        print("  Cause: String passed where number expected")
        print("  Solution: Check template resolver preserves types")

        print("\n3. Missing Required Parameters")
        print("  Symptom: TaskGroup error with validation message")
        print("  Cause: Required parameter not provided")
        print("  Solution: Check tool schema for required fields")

        print("\n4. Environment Variables")
        print("  Symptom: Authentication or permission errors")
        print("  Cause: Missing tokens or credentials")
        print("  Solution: Set required environment variables")

    async def run_comprehensive_diagnostics(self) -> None:
        """Run all diagnostic checks."""
        print("\n" + "=" * 60)
        print("COMPREHENSIVE MCP DIAGNOSTICS")
        print("=" * 60)

        # 1. Environment check
        print("\n[1/4] Environment Variables")
        self.verify_environment_variables("github")
        self.verify_environment_variables("slack")

        # 2. Path checks
        print("\n[2/4] Filesystem Paths")
        self.check_path_permissions("/tmp")
        if sys.platform == "darwin":
            self.check_path_permissions("/private/tmp")

        # 3. Type conversion
        print("\n[3/4] Type Conversion")
        self.test_type_conversion()

        # 4. Common errors
        print("\n[4/4] Common Error Patterns")
        self.diagnose_task_group_error()

        print("\n" + "=" * 60)
        print("Diagnostics complete!")


# ==============================================================================
# SECTION 4: INTERACTIVE REPL
# Interactive command-line interface for MCP exploration.
# ==============================================================================


class MCPRepl:
    """Interactive REPL for MCP protocol exploration."""

    def __init__(self):
        self.session = None
        self.server_name = None
        self.history = []

    async def connect(self, server_name: str) -> bool:
        """Connect to an MCP server."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            print("❌ MCP SDK not installed")
            return False

        config = QuickDiagnostics.get_server_config(server_name)

        print(f"Connecting to {server_name}...")

        try:
            server_params = StdioServerParameters(
                command=config["command"],
                args=config.get("args", []),
                env=config.get("env", {})
            )

            # Note: In real REPL, we'd need to keep these connections alive
            # This is simplified for demonstration
            print(f"✅ Connected to {server_name}")
            self.server_name = server_name
            return True

        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False

    def run_repl(self) -> None:
        """Run the interactive REPL."""
        print("\n" + "=" * 60)
        print("MCP INTERACTIVE REPL")
        print("=" * 60)
        print("\nCommands:")
        print("  connect <server>  - Connect to a server")
        print("  list              - List available tools")
        print("  call <tool> <args> - Call a tool (args as JSON)")
        print("  history           - Show command history")
        print("  help              - Show this help")
        print("  quit              - Exit REPL")
        print()

        while True:
            try:
                # Get input
                cmd = input(f"mcp({self.server_name or 'disconnected'})> ").strip()

                if not cmd:
                    continue

                self.history.append(cmd)

                # Parse command
                parts = cmd.split(None, 1)
                command = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""

                # Execute command
                if command == "quit":
                    print("Goodbye!")
                    break

                elif command == "help":
                    print("Available commands:")
                    print("  connect <server> - Connect to server")
                    print("  list - List tools")
                    print("  call <tool> <args> - Call tool")
                    print("  history - Show history")
                    print("  quit - Exit")

                elif command == "history":
                    for i, h in enumerate(self.history[-10:]):
                        print(f"  {i}: {h}")

                elif command == "connect":
                    if args:
                        asyncio.run(self.connect(args))
                    else:
                        print("Usage: connect <server>")

                elif command == "list":
                    if self.server_name:
                        print("Available tools:")
                        print("  (would list tools here in real implementation)")
                    else:
                        print("Not connected. Use: connect <server>")

                elif command == "call":
                    if self.server_name:
                        # Parse tool and arguments
                        tool_parts = args.split(None, 1)
                        if len(tool_parts) >= 1:
                            tool_name = tool_parts[0]
                            tool_args = {}

                            if len(tool_parts) > 1:
                                try:
                                    tool_args = json.loads(tool_parts[1])
                                except json.JSONDecodeError:
                                    print("Invalid JSON for arguments")
                                    continue

                            print(f"Calling {tool_name} with {tool_args}")
                            print("(would execute tool here in real implementation)")
                    else:
                        print("Not connected. Use: connect <server>")

                else:
                    print(f"Unknown command: {command}")
                    print("Type 'help' for available commands")

            except KeyboardInterrupt:
                print("\nUse 'quit' to exit")
            except Exception as e:
                print(f"Error: {e}")


# ==============================================================================
# MAIN: Command-line interface for debugging utilities
# ==============================================================================


def main():
    """Main entry point for debugging utilities."""

    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()

    if command == "test":
        # Quick test of a server
        if len(sys.argv) < 3:
            print("Usage: mcp-debugging.py test <server>")
            return

        server = sys.argv[2]
        diagnostics = QuickDiagnostics()

        if server == "--all":
            asyncio.run(diagnostics.test_all_servers())
        else:
            asyncio.run(diagnostics.test_server_startup(server))

    elif command == "inspect":
        # Detailed protocol inspection
        if len(sys.argv) < 3:
            print("Usage: mcp-debugging.py inspect <server> [tool] [args]")
            return

        server = sys.argv[2]
        inspector = ProtocolInspector(verbose="--verbose" in sys.argv)

        if len(sys.argv) < 4:
            # Just inspect protocol messages
            inspector.capture_raw_communication(server)
        else:
            # Inspect specific tool
            tool = sys.argv[3]
            args = {}
            if len(sys.argv) > 4:
                try:
                    args = json.loads(sys.argv[4])
                except json.JSONDecodeError:
                    print(f"Invalid JSON for arguments: {sys.argv[4]}")
                    return

            asyncio.run(inspector.inspect_tool_call(server, tool, args))

    elif command == "repl":
        # Interactive REPL
        repl = MCPRepl()
        repl.run_repl()

    elif command == "diagnose":
        # Run diagnostics
        debugger = IssueDebugger()

        if "--all" in sys.argv or len(sys.argv) < 3:
            asyncio.run(debugger.run_comprehensive_diagnostics())
        else:
            # Specific diagnostic
            what = sys.argv[2]
            if what == "paths":
                path = sys.argv[3] if len(sys.argv) > 3 else "/tmp"
                debugger.check_path_permissions(path)
            elif what == "env":
                server = sys.argv[3] if len(sys.argv) > 3 else "github"
                debugger.verify_environment_variables(server)
            elif what == "types":
                debugger.test_type_conversion()
            elif what == "taskgroup":
                debugger.diagnose_task_group_error()
            else:
                print(f"Unknown diagnostic: {what}")
                print("Options: paths, env, types, taskgroup")

    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
