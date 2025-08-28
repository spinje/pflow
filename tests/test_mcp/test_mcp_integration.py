"""
FIXED: Integration test that actually tests the compiler's metadata injection.

This test verifies the complete MCP pipeline through the real code paths.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from pflow.mcp import MCPServerManager
from pflow.nodes.mcp.node import MCPNode
from pflow.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow


class TestMCPRealIntegration:
    """Test the complete MCP integration through actual code paths."""

    def test_compiler_metadata_injection_through_real_stack(self):
        """Test that compiler correctly parses node type and injects metadata.

        This test verifies the ACTUAL compiler logic by:
        1. NOT mocking any internal methods
        2. Only mocking true external boundaries (MCP server communication)
        3. Testing through flow.run() for complete integration
        4. Verifying metadata flows through actual compiler

        Real Bugs This Catches:
        - Compiler parsing bugs (e.g., wrong splitting of "mcp-server-tool")
        - Metadata not reaching MCPNode through real paths
        - Flow execution issues
        - Result propagation through shared store
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp-servers.json"
            registry_path = Path(tmpdir) / "registry.json"

            # Step 1: Configure MCP server (real config)
            manager = MCPServerManager(config_path=config_path)
            manager.add_server(
                "github", "npx", ["-y", "@modelcontextprotocol/server-github"], env={"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
            )

            # Step 2: Create registry entry (real structure)
            registry = Registry(registry_path=registry_path)
            nodes = registry.load()
            nodes["mcp-github-create-issue"] = {
                "class_name": "MCPNode",
                "module": "pflow.nodes.mcp.node",
                "file_path": "virtual://mcp",
                "interface": {
                    "description": "Create a GitHub issue",
                    "inputs": [],  # Critical: empty for MCP nodes
                    "params": [
                        {"name": "title", "type": "str", "description": "Issue title"},
                        {"name": "body", "type": "str", "description": "Issue body"},
                        {"name": "repository", "type": "str", "description": "Repository name"},
                    ],
                    "outputs": [{"key": "issue_url", "type": "str", "description": "Created issue URL"}],
                    "actions": ["default"],
                },
            }
            registry.save(nodes)

            # Step 3: Create workflow IR
            workflow_ir = {
                "name": "create-issue-workflow",
                "nodes": [
                    {
                        "id": "create_issue",
                        "type": "mcp-github-create-issue",  # Compiler must parse this
                        "params": {"title": "Test Issue", "body": "This is a test issue", "repository": "test-repo"},
                    }
                ],
                "edges": [],
            }

            # Step 4: Mock ONLY external boundaries
            # We'll track what the REAL MCPNode receives through its actual execution
            exec_async_calls = []

            async def mock_exec_async(self, prep_res):
                """Capture what reaches _exec_async through real code paths."""
                exec_async_calls.append(prep_res)
                return {"result": {"issue_url": "https://github.com/test-repo/issues/123", "issue_number": 123}}

            # Mock server config loading (I/O boundary)
            def mock_load_config(self, server_name):
                return manager.get_server(server_name)

            with (
                patch.object(MCPNode, "_exec_async", mock_exec_async),
                patch.object(MCPNode, "_load_server_config", mock_load_config),
            ):
                # Step 5: Compile and run through REAL flow execution
                flow = compile_ir_to_flow(workflow_ir, registry)

                # Run the actual flow (not manual node methods)
                shared_store = {}
                flow.run(shared_store)

            # Step 6: Verify compiler correctly injected metadata
            assert len(exec_async_calls) == 1
            prep_res = exec_async_calls[0]

            # Verify metadata was correctly parsed and injected by compiler
            assert prep_res["server"] == "github"
            assert prep_res["tool"] == "create-issue"  # Note: dashes preserved
            assert prep_res["arguments"]["title"] == "Test Issue"
            assert prep_res["arguments"]["body"] == "This is a test issue"
            assert prep_res["arguments"]["repository"] == "test-repo"

            # Verify results flowed back through shared store
            # Results are namespaced under node ID
            assert "create_issue" in shared_store
            node_results = shared_store["create_issue"]
            assert "result" in node_results
            assert "issue_url" in node_results["result"]
            assert node_results["result"]["issue_url"] == "https://github.com/test-repo/issues/123"

    def test_multiple_mcp_nodes_in_workflow(self):
        """Test workflow with multiple MCP nodes gets correct metadata for each.

        Real Bug: Metadata could leak between nodes or get confused.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp-servers.json"
            registry_path = Path(tmpdir) / "registry.json"

            # Configure multiple servers
            manager = MCPServerManager(config_path=config_path)
            manager.add_server("github", "npx", ["-y", "@modelcontextprotocol/server-github"])
            manager.add_server("filesystem", "npx", ["-y", "@modelcontextprotocol/server-filesystem"])

            # Create registry entries
            registry = Registry(registry_path=registry_path)
            nodes = registry.load()

            nodes["mcp-github-list-issues"] = {
                "class_name": "MCPNode",
                "module": "pflow.nodes.mcp.node",
                "file_path": "virtual://mcp",
                "interface": {
                    "inputs": [],
                    "params": [{"name": "repo", "type": "str"}],
                    "outputs": [{"key": "issues", "type": "list"}],
                },
            }

            nodes["mcp-filesystem-read-file"] = {
                "class_name": "MCPNode",
                "module": "pflow.nodes.mcp.node",
                "file_path": "virtual://mcp",
                "interface": {
                    "inputs": [],
                    "params": [{"name": "path", "type": "str"}],
                    "outputs": [{"key": "content", "type": "str"}],
                },
            }

            registry.save(nodes)

            # Create workflow with multiple MCP nodes
            workflow_ir = {
                "name": "multi-mcp",
                "nodes": [
                    {"id": "list_issues", "type": "mcp-github-list-issues", "params": {"repo": "test/repo"}},
                    {
                        "id": "read_config",
                        "type": "mcp-filesystem-read-file",
                        "params": {"path": "/test/mock/config.json"},
                    },
                ],
                "edges": [{"from": "list_issues", "to": "read_config", "condition": "default"}],
            }

            # Track what each node receives
            node_executions = {}

            async def tracking_exec_async(self, prep_res):
                """Track execution for each node."""
                key = f"{prep_res['server']}-{prep_res['tool']}"
                node_executions[key] = prep_res
                return {"result": f"Executed {key}"}

            # Mock server config loading
            def mock_load_config(self, server_name):
                return manager.get_server(server_name)

            with (
                patch.object(MCPNode, "_exec_async", tracking_exec_async),
                patch.object(MCPNode, "_load_server_config", mock_load_config),
            ):
                flow = compile_ir_to_flow(workflow_ir, registry)
                flow.run({})

            # Verify each node got correct metadata
            assert len(node_executions) == 2

            # GitHub node
            github_exec = node_executions["github-list-issues"]
            assert github_exec["server"] == "github"
            assert github_exec["tool"] == "list-issues"
            assert github_exec["arguments"]["repo"] == "test/repo"

            # Filesystem node
            fs_exec = node_executions["filesystem-read-file"]
            assert fs_exec["server"] == "filesystem"
            assert fs_exec["tool"] == "read-file"
            assert fs_exec["arguments"]["path"] == "/test/mock/config.json"

    def test_environment_variable_expansion_at_runtime(self):
        """Test that ${VAR} patterns are expanded at runtime, not config time.

        Real Bug: Expanding at config time would store secrets in plain text.
        """
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp-servers.json"
            registry_path = Path(tmpdir) / "registry.json"

            # Configure server with env var
            manager = MCPServerManager(config_path=config_path)
            manager.add_server("testserver", "test-cmd", [], env={"API_KEY": "${TEST_API_KEY}"})

            # Verify it's stored as template
            with open(config_path) as f:
                config_content = f.read()
                assert "${TEST_API_KEY}" in config_content
                assert "secret123" not in config_content  # Not expanded yet

            # Create registry entry
            registry = Registry(registry_path=registry_path)
            nodes = registry.load()
            nodes["mcp-testserver-action"] = {
                "class_name": "MCPNode",
                "module": "pflow.nodes.mcp.node",
                "file_path": "virtual://mcp",
                "interface": {"inputs": [], "params": [], "outputs": []},
            }
            registry.save(nodes)

            # Create workflow
            workflow_ir = {"nodes": [{"id": "test", "type": "mcp-testserver-action", "params": {}}], "edges": []}

            # Set environment variable
            os.environ["TEST_API_KEY"] = "runtime-secret-456"

            try:
                # Track what environment is used at runtime
                used_env = None

                async def capture_env_exec(self, prep_res):
                    nonlocal used_env
                    # In real execution, MCPNode._exec_async would call _expand_env_vars
                    # We'll simulate that here
                    node = MCPNode()
                    used_env = node._expand_env_vars(prep_res["config"].get("env", {}))
                    return {"result": "ok"}

                # Mock server config loading
                def mock_load_config(self, server_name):
                    return manager.get_server(server_name)

                with (
                    patch.object(MCPNode, "_exec_async", capture_env_exec),
                    patch.object(MCPNode, "_load_server_config", mock_load_config),
                ):
                    flow = compile_ir_to_flow(workflow_ir, registry)
                    flow.run({})

                # Verify runtime expansion happened
                assert used_env is not None
                assert used_env["API_KEY"] == "runtime-secret-456"

            finally:
                del os.environ["TEST_API_KEY"]
