"""FastMCP server instance for pflow.

This module creates the central FastMCP server instance that all tools
register with via decorators. The :class:`PflowMCP` subclass installs a
unified exception boundary on both ``call_tool`` and ``read_resource`` so
unhandled exceptions reach agents as structured ``Diagnostic`` output,
matching the CLI's outer ``except Exception`` in ``cli/commands/run.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError, ToolError

from pflow.core.diagnostic import Diagnostic, Severity, exception_to_diagnostics
from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.suggestion_utils import find_similar_items

logger = logging.getLogger(__name__)


# Hand-rolled rich-text service exceptions pass through to preserve today's
# pre-formatted output. This list shrinks once services migrate to typed
# pflow exceptions (out-of-scope follow-up to issue #325).
# pydantic_core.ValidationError (v2) is a ValueError subclass, so argument-
# validation errors pass through without special-casing.
_PASS_THROUGH_TYPES: tuple[type[BaseException], ...] = (
    ValueError,
    TypeError,
    RuntimeError,
    FileExistsError,
)


def _should_render(original: Exception) -> bool:
    """Return True if ``original`` should go through the Diagnostic renderer.

    Self-describing exceptions (``hasattr(..., 'to_diagnostics')``) always
    render — covers every ``PflowError`` subclass plus ``MaxNodeVisitsError``
    (which is a ``RuntimeError`` subclass by design).  Producer bugs without
    ``to_diagnostics()`` (``AttributeError``, ``KeyError``, ``IndexError`` …)
    also render.  Bare pre-formatted ``ValueError`` / ``TypeError`` /
    ``RuntimeError`` / ``FileExistsError`` pass through so FastMCP's default
    handling surfaces their rendered text unchanged.
    """
    if hasattr(original, "to_diagnostics"):
        return True
    return not isinstance(original, _PASS_THROUGH_TYPES)


_MCP_WRAPPER_TYPES: tuple[type[Exception], ...] = (ToolError, ResourceError)


def _is_function_resource_wrapper(exc: Exception) -> bool:
    """FunctionResource.read wraps any exception it sees as
    ``ValueError(f"Error reading resource {uri}: {e}")``.  Recognize the
    shape so the unwrap walks past it to the original producer exception.

    Drift guard: ``test_resource_producer_bug_raises_with_rendered_diagnostic``
    asserts the 3-layer unwrap walks through this wrapper — a mcp-SDK minor
    release that reworded the prefix would fail that test.
    """
    return isinstance(exc, ValueError) and str(exc).startswith("Error reading resource ")


def _unwrap_cause(wrapper: Exception) -> Exception:
    """Walk __cause__/__context__ past MCP wrapper layers to the original exception.

    Known wrapping patterns (mcp 1.26.0):
    - ``Tool.run`` uses ``raise ToolError(...) from e`` → original in ``__cause__``
    - ``FastMCP.read_resource`` uses ``raise ResourceError(str(e))`` inside
      ``except`` → original in implicit ``__context__``
    - ``FunctionResource.read`` uses ``raise ValueError(f"Error reading ...")``
      inside ``except`` → original in implicit ``__context__``

    We deliberately do NOT walk past non-wrapper exceptions, so service code
    like ``raise ValueError(hint) from e`` preserves the ValueError as the
    outer type (today's pass-through behavior).
    """
    seen = {id(wrapper)}
    current: Exception = wrapper
    while isinstance(current, _MCP_WRAPPER_TYPES) or _is_function_resource_wrapper(current):
        nxt = current.__cause__ or current.__context__
        if nxt is None or id(nxt) in seen or not isinstance(nxt, Exception):
            break
        seen.add(id(nxt))
        current = nxt
    return current


def _render_exception(original: Exception) -> str:
    """Render ``original`` via the shared pipeline, iterating ALL diagnostics.

    Matches ``cli/error_output.py::display_exception_text`` so CLI and MCP
    produce byte-identical text for the same exception.

    Defensive: if a misbehaving ``to_diagnostics()`` method raises (e.g. a
    third-party exception that happens to have the attribute but fails when
    called), fall through to the bare string form rather than letting the
    secondary exception escape the entire boundary.
    """
    try:
        diagnostics = exception_to_diagnostics(original)
    except Exception:
        # Defensive: any failure in the rendering pipeline (e.g. a misbehaving
        # third-party to_diagnostics() method) falls back to bare-string output
        # rather than letting a secondary exception escape the boundary.
        logger.exception("exception_to_diagnostics raised while rendering %r", original)
        return f"Error: {original}"
    if not diagnostics:
        return f"Error: {original}"
    return "\n".join(format_diagnostic(d) for d in diagnostics)


def _build_unknown_tool_diagnostic(name: str, available_tools: list[str]) -> Diagnostic:
    """Construct a ``Tool Not Found`` diagnostic with similar-names suggestions."""
    similar = find_similar_items(name, available_tools, max_results=3, method="fuzzy")
    suggestions: list[str] = []
    if similar:
        suggestions.append(f"Did you mean: {', '.join(similar)}")
    suggestions.append("Run `workflow_discover` or `registry_discover` to find the right tool.")
    return Diagnostic(
        severity=Severity.ERROR,
        source="mcp",
        title="Tool Not Found",
        message=f"Unknown tool: {name}",
        suggestions=suggestions,
        context={"category": "not_found", "similar_names": similar or None},
    )


def _build_unknown_resource_diagnostic(uri: Any, available_uris: list[str]) -> Diagnostic:
    """Construct a ``Resource Not Found`` diagnostic with similar-URI suggestions."""
    similar = find_similar_items(str(uri), available_uris, max_results=3, method="fuzzy")
    suggestions: list[str] = []
    if similar:
        suggestions.append(f"Did you mean: {', '.join(similar)}")
    # Derive the "known resources" list from the live registry so the hint
    # stays correct when resources are added or removed.
    known = ", ".join(available_uris) if available_uris else "(none registered)"
    suggestions.append(f"Check the resource URI. Known pflow resources: {known}.")
    return Diagnostic(
        severity=Severity.ERROR,
        source="mcp",
        title="Resource Not Found",
        message=f"Unknown resource: {uri}",
        suggestions=suggestions,
        context={"category": "not_found", "similar_names": similar or None},
    )


class PflowMCP(FastMCP):
    """FastMCP subclass with a unified exception boundary.

    Overrides ``call_tool`` and ``read_resource`` to catch producer bugs
    escaping the tool / resource layer and convert them to structured
    ``CallToolResult(isError=True)`` / rendered resource text using the
    shared ``Diagnostic`` pipeline. Matches the CLI's outer
    ``except Exception`` in ``cli/commands/run.py``.
    """

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        try:
            return await super().call_tool(name, arguments)
        except ToolError as te:
            # Unknown-tool errors are raised at tool_manager.py:91 without
            # `from e` and outside any except block — both __cause__ and
            # __context__ are None. Render with similar-name suggestions.
            # Drift guard: test_typo_returns_did_you_mean_suggestion pins
            # this prefix; a mcp-SDK rewording would fail that test.
            if te.__cause__ is None and te.__context__ is None and str(te).startswith("Unknown tool:"):
                available = [t.name for t in await self.list_tools()]
                diagnostic = _build_unknown_tool_diagnostic(name, available)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=format_diagnostic(diagnostic))],
                    isError=True,
                )

            original = _unwrap_cause(te)
            if not _should_render(original):
                # Debug-log the pass-through so a producer bug misclassified
                # into the pass-through list still leaves an audit trail.
                logger.debug(
                    "Passing through %s in MCP tool %s: %s",
                    type(original).__name__,
                    name,
                    original,
                )
                raise
            # logger.exception uses sys.exc_info(), which surfaces the full
            # wrapper → original chain via __cause__/__context__ — strictly
            # more useful than logging the unwrapped original alone.
            logger.exception("Unhandled exception in MCP tool %s", name)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=_render_exception(original))],
                isError=True,
            )

    async def read_resource(self, uri: Any) -> Any:
        try:
            return await super().read_resource(uri)
        except (ResourceError, ValueError) as exc:
            # Unknown-resource URIs raise `ValueError("Unknown resource: ...")`
            # from resource_manager.py:105 (concrete resources) or
            # `ResourceError("Unknown resource: ...")` from FastMCP. Render
            # with similar-URI suggestions, symmetric with the unknown-tool
            # path. Must re-raise (not return contents) because the MCP
            # resource protocol signals failure via a JSON-RPC error.
            # Drift guard: test_unknown_resource_renders_rich_diagnostic pins
            # this prefix; a mcp-SDK rewording would fail that test.
            if exc.__cause__ is None and exc.__context__ is None and str(exc).startswith("Unknown resource:"):
                available = [str(r.uri) for r in await self.list_resources()]
                diagnostic = _build_unknown_resource_diagnostic(uri, available)
                raise ResourceError(format_diagnostic(diagnostic)) from exc

            # For anything else, only intercept ResourceError — FastMCP's
            # wrapping for exceptions raised INSIDE resource handlers. A
            # bare ValueError that isn't an unknown-resource marker is not
            # something we can classify, so let it propagate.
            if not isinstance(exc, ResourceError):
                raise

            original = _unwrap_cause(exc)
            if not _should_render(original):
                logger.debug(
                    "Passing through %s reading MCP resource %s: %s",
                    type(original).__name__,
                    uri,
                    original,
                )
                raise
            logger.exception("Unhandled exception reading MCP resource %s", uri)
            # MCP resource protocol has no isError channel; re-raise as
            # ResourceError so the lowlevel handler produces a proper
            # JSON-RPC error response. Matches FastMCP's default pass-through
            # behavior — programmatic agents see the error at the protocol
            # level, not as successful-looking content.
            raise ResourceError(_render_exception(original)) from original


# Create the FastMCP server instance with instructions for agents.
# All tools and resources register with this instance via decorators.
mcp = PflowMCP(
    "pflow",
    instructions="""🚨 MANDATORY WORKFLOW PROTOCOL 🚨

WHEN TO FOLLOW - Any request where you will create/build a pflow workflow:
• "Create a workflow that does X"
• "Help me build/make a workflow"
• "Automate X with pflow"
• User describes task → you produce .pflow.md workflow file

REQUIRED SEQUENCE (no exceptions, no skipping):
1. workflow_discover first → Check if suitable workflow already exists
   → 95%+ confidence match? Execute with `workflow_execute` tool (don't rebuild)
2. If building new → Read `pflow://instructions` resource BEFORE using other tools (NON-OPTIONAL)
   → Contains complete 10-step development loop + best practices
   → ⛔ DO NOT skip to building unless you have read the FULL `pflow://instructions` mcp resource
3. Then use registry_discover, registry_describe, etc.

SANDBOXED ENVIRONMENTS:
If no CLI access (pflow --version fails) or no shared filesystem:
→ Use `pflow://instructions/sandbox` resource instead

PURPOSE: Prevents duplicate workflows, ensures established patterns.""",
)


# Import all tool and resource modules to register them
# This happens at import time via decorators
def register_tools() -> None:
    """Import all tool and resource modules to register them with the server.

    This function is called during server startup to ensure all tools
    and resources are registered before the server starts handling requests.
    """
    # Import tool modules to trigger @mcp.tool() decorators
    # We need to import these modules for their side effects (decorator registration)
    # Explicitly reference them to satisfy linting
    # Import resource modules to trigger @mcp.resource() decorators
    from .resources import instruction_resources
    from .tools import (
        discovery_tools,
        execution_tools,
        registry_tools,
        workflow_tools,
    )

    # Explicitly reference the modules to satisfy ruff F401
    _ = (
        discovery_tools,
        execution_tools,
        registry_tools,
        workflow_tools,
        instruction_resources,
    )


__all__ = ["PflowMCP", "mcp", "register_tools"]
