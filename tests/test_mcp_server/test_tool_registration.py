"""Fast tests for MCP tool registration.

These tests verify that tools are properly registered with the FastMCP server
without requiring slow subprocess or protocol integration tests.

CRITICAL: These tests would have caught the missing import bug where
register_tools() lost its import statements, resulting in zero tools
being exposed to AI agents despite all service-layer tests passing.

Performance target: All 6 tests complete in < 100ms total.
"""

import asyncio
import inspect


class TestToolRegistration:
    """Fast tests verifying tool registration mechanism works.

    These tests catch critical bugs in the tool registration infrastructure:
    - Missing imports in register_tools()
    - Typos in @mcp.tool() decorators
    - Tool function deletion or renaming
    - Import chain breakage
    """

    def test_tools_registered_count(self):
        """CRITICAL: Verify all production tools are registered.

        Execution time: ~10ms
        What it catches: Missing imports in register_tools()

        This is the PRIMARY guard against the production bug where imports
        were accidentally removed from server.py, resulting in zero tools
        being exposed despite all service tests passing.
        """
        from pflow.mcp_server.server import mcp, register_tools

        # Register tools
        register_tools()

        # List registered tools (use asyncio.run for sync context)
        tools = asyncio.run(mcp.list_tools())
        production_tools = [t for t in tools if not t.name.startswith("test_")]

        # We have 11 production tools after commenting out settings_tools and test_tools:
        # - workflow_discover, workflow_execute, workflow_validate, workflow_save (execution_tools)
        # - workflow_list, workflow_describe (workflow_tools)
        # - registry_discover, registry_run, registry_describe, registry_search, registry_list (registry_tools)
        # Enforce minimum of 10 to allow for future deprecations
        assert len(production_tools) >= 10, (
            f"Expected at least 10 production tools, but only {len(production_tools)} registered! "
            f"Tools found: {[t.name for t in production_tools]}\n"
            f"Check if register_tools() is missing imports in src/pflow/mcp_server/server.py"
        )

    def test_critical_tools_registered(self):
        """Verify critical workflow tools exist by name.

        Execution time: ~15ms
        What it catches: Typos in tool names, @mcp.tool() decorator mistakes

        Tests the core workflow loop tools that agents depend on.
        If these are missing, agents cannot build or execute workflows.
        """
        from pflow.mcp_server.server import mcp, register_tools

        register_tools()
        tools = asyncio.run(mcp.list_tools())
        tool_names = [t.name for t in tools]

        # Core workflow loop tools (Priority 1 from task spec)
        critical_tools = [
            "workflow_discover",  # Find existing workflows
            "workflow_execute",  # Run workflows
            "workflow_validate",  # Validate before execution
            "workflow_save",  # Save to library
            "registry_discover",  # Find nodes for building
            "registry_run",  # Test node execution
        ]

        missing_tools = [tool for tool in critical_tools if tool not in tool_names]

        assert not missing_tools, (
            f"Critical tools missing: {missing_tools}. "
            f"Available tools: {tool_names}\n"
            f"Check tool definitions in src/pflow/mcp_server/tools/"
        )

    def test_tool_modules_importable(self):
        """Verify all tool modules can be imported without errors.

        Execution time: ~5ms
        What it catches: Import errors, circular dependencies, syntax errors

        This test ensures the import chain is intact. If register_tools()
        tries to import a broken module, this test catches it early.
        """
        # Should not raise ImportError
        try:
            from pflow.mcp_server.tools import (
                discovery_tools,  # noqa: F401
                execution_tools,  # noqa: F401
                registry_tools,  # noqa: F401
                workflow_tools,  # noqa: F401
            )

            # Note: settings_tools and test_tools are commented out in server.py
            # from pflow.mcp_server.tools import settings_tools
            # from pflow.mcp_server.tools import test_tools

        except ImportError as e:
            raise AssertionError(f"Failed to import tool module: {e}") from e


class TestToolWiring:
    """Fast tests verifying tools are correctly wired to services.

    These tests ensure the glue code between FastMCP tools and service
    layer is correct, catching refactoring bugs and interface mismatches.
    """

    def test_tool_schemas_valid(self):
        """Verify tools have correct parameter schemas.

        Execution time: ~20ms
        What it catches: Missing parameters, wrong types, schema errors

        FastMCP generates schemas from function signatures. This test
        ensures critical tools have the expected parameters.
        """
        from pflow.mcp_server.server import mcp, register_tools

        register_tools()
        tools = asyncio.run(mcp.list_tools())

        # Check workflow_validate schema (most critical validation tool)
        validate_tool = next((t for t in tools if t.name == "workflow_validate"), None)
        assert validate_tool is not None, f"workflow_validate tool not found! Available: {[t.name for t in tools]}"

        # Verify schema structure
        tool_dict = validate_tool.model_dump()
        assert "inputSchema" in tool_dict, "Tool missing inputSchema"
        schema = validate_tool.inputSchema

        assert "properties" in schema, "Schema missing properties"
        assert "workflow" in schema["properties"], "Missing 'workflow' parameter"

        # Verify workflow is required
        assert "required" in schema, "Schema missing required fields"
        assert "workflow" in schema["required"], "'workflow' should be required"

    def test_tool_functions_exist_and_async(self):
        """Verify tool functions are defined and async.

        Execution time: ~15ms
        What it catches: Function deletion, wrong signature, missing async

        Tools must be async functions for FastMCP. This test ensures
        critical tools exist and are properly defined.
        """
        from pflow.mcp_server.tools import execution_tools, workflow_tools

        # Check execution tools exist
        assert hasattr(execution_tools, "workflow_validate"), "workflow_validate function missing"
        assert hasattr(execution_tools, "workflow_execute"), "workflow_execute function missing"
        assert hasattr(execution_tools, "workflow_save"), "workflow_save function missing"

        # Check workflow tools exist
        assert hasattr(workflow_tools, "workflow_list"), "workflow_list function missing"
        assert hasattr(workflow_tools, "workflow_describe"), "workflow_describe function missing"

        # Verify they're async functions (required by FastMCP)
        assert inspect.iscoroutinefunction(execution_tools.workflow_validate), "workflow_validate must be async"
        assert inspect.iscoroutinefunction(execution_tools.workflow_execute), "workflow_execute must be async"
        assert inspect.iscoroutinefunction(execution_tools.workflow_save), "workflow_save must be async"

    def test_services_imported_by_tools(self):
        """Verify tools can access their service dependencies.

        Execution time: ~10ms
        What it catches: Service import removal, module refactoring breaks

        Tools depend on service layer. This test ensures the import chain
        from tools → services is intact.
        """
        try:
            # Execution tools should be able to import ExecutionService
            # Discovery tools should be able to import DiscoveryService
            from pflow.mcp_server.services.discovery_service import DiscoveryService  # noqa: F401
            from pflow.mcp_server.services.execution_service import ExecutionService  # noqa: F401

            # Registry tools should be able to import RegistryService
            from pflow.mcp_server.services.registry_service import RegistryService  # noqa: F401

            # Workflow tools should be able to import WorkflowService
            from pflow.mcp_server.services.workflow_service import WorkflowService  # noqa: F401

        except ImportError as e:
            raise AssertionError(f"Tool service dependency import failed: {e}") from e


# Performance note: These tests should complete in < 100ms total.
# If tests become slow (> 200ms), investigate what changed in:
# - FastMCP initialization time
# - Tool registration overhead
# - Import chain complexity
