"""Tests for the PflowMCP exception boundary (issue spinje/pflow#325).

Verifies that unhandled exceptions escaping MCP tool/resource handlers are
routed through the shared Diagnostic pipeline — same structural behavior as
the CLI's outer ``except Exception`` in ``cli/commands/run.py``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from mcp import types
from mcp.server.fastmcp.exceptions import ResourceError, ToolError

from pflow.core.exceptions import MaxNodeVisitsError
from pflow.mcp_server.server import mcp, register_tools

# Register all tools / resources once for the module. Idempotent.
register_tools()


# Minimal valid workflow for tools that declare `workflow` as a required
# parameter. The patched service methods raise before the content matters,
# but the parameter must satisfy pydantic's required-field check first.
_MINIMAL_WORKFLOW = (
    "# Test\n\n"
    "A description with enough length to pass validation.\n\n"
    "## Steps\n\n"
    "### echo-step\n\n"
    "Step description.\n\n"
    "- type: echo\n"
    "- params:\n"
    "  - message: hi\n"
)


def _run(coro):
    """Synchronous wrapper around asyncio.run for test readability."""
    return asyncio.run(coro)


class TestUnhandledProducerBugs:
    """Producer bugs without ``to_diagnostics()`` render via the shared pipeline."""

    def test_str_returning_tool_renders_structured_output(self):
        with patch(
            "pflow.mcp_server.services.execution_service.ExecutionService.validate_workflow",
            side_effect=AttributeError("'str' object has no attribute 'get'"),
        ):
            result = _run(mcp.call_tool("workflow_validate", {"workflow": _MINIMAL_WORKFLOW}))

        assert isinstance(result, types.CallToolResult)
        assert result.isError is True
        assert len(result.content) == 1
        text = result.content[0].text
        assert "'str' object has no attribute 'get'" in text
        # Proves we bypassed FastMCP's default rendering, which would
        # prefix every message with "Error executing tool X:".
        assert "Error executing tool" not in text

    def test_dict_returning_tool_renders_structured_output(self):
        with patch(
            "pflow.mcp_server.services.execution_service.ExecutionService.plan_workflow",
            side_effect=KeyError("__producer_bug_sentinel__"),
        ):
            result = _run(mcp.call_tool("plan_workflow", {"workflow": _MINIMAL_WORKFLOW}))

        assert isinstance(result, types.CallToolResult)
        assert result.isError is True
        assert result.structuredContent is None
        assert "__producer_bug_sentinel__" in result.content[0].text


class TestSelfDescribingExceptions:
    """Exceptions with ``to_diagnostics()`` render via their own rich output,
    even when they subclass a pass-through type. Pins the inversion-predicate
    decision — reverting to an isinstance-only pass-through would fail here."""

    def test_max_node_visits_renders_as_infinite_loop(self):
        with patch(
            "pflow.mcp_server.services.execution_service.ExecutionService.execute_workflow",
            side_effect=MaxNodeVisitsError("node-x", 100, 50),
        ):
            result = _run(
                mcp.call_tool(
                    "workflow_execute",
                    {"workflow": _MINIMAL_WORKFLOW, "parameters": {}},
                )
            )

        assert result.isError is True
        text = result.content[0].text
        # Title from MaxNodeVisitsError.to_diagnostics() — would be lost if
        # MaxNodeVisitsError were passed through as a plain RuntimeError.
        assert "Infinite Loop Detected" in text
        assert "node-x" in text


class TestPassThrough:
    """Hand-rolled rich-text service exceptions pass through unchanged so
    today's pre-formatted output is preserved.  Follow-up: migrate services
    to typed pflow exceptions and shrink the pass-through list."""

    def test_bare_value_error_passes_through(self):
        # Pass-through re-raises ToolError. In production flow the lowlevel
        # handler converts it to CallToolResult(isError=True) via
        # _make_error_result(str(e)). `match=` pins the ORIGINAL service
        # message through the re-raise — without it, a regression that
        # wrapped as ToolError("internal error") would silently pass.
        with (
            patch(
                "pflow.mcp_server.services.execution_service.ExecutionService.validate_workflow",
                side_effect=ValueError("pre-formatted rich text from service"),
            ),
            pytest.raises(ToolError, match=r"pre-formatted rich text from service"),
        ):
            _run(mcp.call_tool("workflow_validate", {"workflow": _MINIMAL_WORKFLOW}))


class TestCliMcpParity:
    """MCP boundary produces byte-identical rendered text to the CLI boundary
    for the same unhandled exception (issue #325 contract)."""

    def test_attribute_error_text_matches_cli(self, capsys):
        from pflow.cli.error_output import display_exception_text

        exc_message = "'str' object has no attribute 'get'"

        # CLI path writes one diagnostic per line to stderr via click.echo.
        display_exception_text(AttributeError(exc_message))
        cli_text = capsys.readouterr().err.rstrip("\n")

        # MCP path: patch a service to raise the same exception and call
        # through the boundary.
        with patch(
            "pflow.mcp_server.services.execution_service.ExecutionService.validate_workflow",
            side_effect=AttributeError(exc_message),
        ):
            result = _run(mcp.call_tool("workflow_validate", {"workflow": _MINIMAL_WORKFLOW}))
        mcp_text = result.content[0].text.rstrip("\n")

        assert cli_text == mcp_text, f"CLI/MCP output diverged:\nCLI:\n{cli_text!r}\n\nMCP:\n{mcp_text!r}"

    def test_max_node_visits_matches_cli(self, capsys):
        """Self-describing exceptions produce byte-identical CLI/MCP text.

        Pins the `hasattr to_diagnostics` branch structurally — a divergence
        in how self-describing exceptions flow through the renderer between
        the two surfaces would fail here.
        """
        from pflow.cli.error_output import display_exception_text

        exc = MaxNodeVisitsError("node-x", 100, 50)

        display_exception_text(exc)
        cli_text = capsys.readouterr().err.rstrip("\n")

        with patch(
            "pflow.mcp_server.services.execution_service.ExecutionService.execute_workflow",
            side_effect=MaxNodeVisitsError("node-x", 100, 50),
        ):
            result = _run(
                mcp.call_tool(
                    "workflow_execute",
                    {"workflow": _MINIMAL_WORKFLOW, "parameters": {}},
                )
            )
        mcp_text = result.content[0].text.rstrip("\n")

        assert cli_text == mcp_text, f"CLI/MCP output diverged:\nCLI:\n{cli_text!r}\n\nMCP:\n{mcp_text!r}"


class TestUnknownTool:
    """Calling an unregistered tool renders a rich 'Tool Not Found' diagnostic."""

    def test_typo_returns_did_you_mean_suggestion(self):
        # Deliberate typo close to a real tool name.
        result = _run(mcp.call_tool("workflow_validat", {"workflow": _MINIMAL_WORKFLOW}))

        assert isinstance(result, types.CallToolResult)
        assert result.isError is True
        text = result.content[0].text
        assert "Tool Not Found" in text
        assert "Unknown tool: workflow_validat" in text
        # The real tool name should appear in the Did you mean: suggestions.
        assert "workflow_validate" in text


class TestResourceBoundary:
    """Resources go through a separate FastMCP code path (read_resource →
    ResourceError). The override covers them symmetrically and raises
    ResourceError (instead of returning success content) so the protocol
    layer produces a proper JSON-RPC error response."""

    def test_resource_producer_bug_raises_with_rendered_diagnostic(self):
        async def run_with_failing_resource():
            # Patch the underlying function on the Resource object so
            # FastMCP.read_resource → resource.read() → resource.fn()
            # raises our sentinel. The chain is:
            #   AttributeError → ValueError("Error reading resource ...")
            #                  → ResourceError (from FastMCP)
            # _unwrap_cause must walk past the ValueError wrapper to the
            # original AttributeError for proper rendering.
            resource = await mcp._resource_manager.get_resource("pflow://instructions")
            assert resource is not None
            with patch.object(resource, "fn", side_effect=AttributeError("resource producer bug sentinel")):
                return await mcp.read_resource("pflow://instructions")

        with pytest.raises(ResourceError) as exc_info:
            _run(run_with_failing_resource())

        rendered = str(exc_info.value)
        # Original AttributeError message must survive the 3-layer unwrap.
        assert "resource producer bug sentinel" in rendered
        # Proves the unwrap walked PAST the FunctionResource wrapper — the
        # outer wrapper's message is "Error reading resource ..."; if the
        # unwrap stopped there we'd render a ValueError diagnostic, not
        # the AttributeError's.
        assert "Error reading resource" not in rendered
        # Proves we rendered through _builtin_exception_diagnostic's
        # AttributeError path (title="Execution Failed") rather than
        # ValueError's validation branch (title="Validation Error").
        assert "Execution Failed" in rendered

    def test_unknown_resource_renders_rich_diagnostic(self):
        """Unknown-resource URI gets a 'Resource Not Found' diagnostic with
        similar-URI suggestions, symmetric with the unknown-tool path."""
        with pytest.raises(ResourceError) as exc_info:
            _run(mcp.read_resource("pflow://instructons"))  # typo

        rendered = str(exc_info.value)
        assert "Resource Not Found" in rendered
        assert "Unknown resource" in rendered
        # Similar real URI should appear in the Did you mean: suggestions.
        assert "pflow://instructions" in rendered
