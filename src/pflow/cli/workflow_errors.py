"""Workflow error display and formatting.

Text-mode error display for ExecutionResult failures. JSON error output
is now handled by error_output.py.
"""

from __future__ import annotations

from typing import Any

import click


def _display_api_error_response(raw_response: dict[str, Any]) -> None:
    """Display API error response details.

    Args:
        raw_response: Raw API response dict
    """
    click.echo("\n  API Response:", err=True)

    # GitHub/API errors often have 'errors' array
    if errors_list := raw_response.get("errors"):
        for api_err in errors_list[:3]:
            field = api_err.get("field", "unknown")
            msg = api_err.get("message", api_err.get("code", "error"))
            click.echo(f"    - Field '{field}': {msg}", err=True)
    elif msg := raw_response.get("message"):
        click.echo(f"    {msg}", err=True)

    if doc_url := raw_response.get("documentation_url"):
        click.echo(f"\n  Documentation: {doc_url}", err=True)


def _display_mcp_error_details(mcp_error: dict[str, Any]) -> None:
    """Display MCP tool error details.

    Args:
        mcp_error: MCP error dict
    """
    click.echo("\n  MCP Tool Error:", err=True)

    if details := mcp_error.get("details"):
        click.echo(f"    Field: {details.get('field')}", err=True)
        click.echo(f"    Expected: {details.get('expected')}", err=True)
        click.echo(f"    Received: {details.get('received')}", err=True)
    elif msg := mcp_error.get("message"):
        click.echo(f"    {msg}", err=True)


def _display_single_error(
    error: dict[str, Any],
    error_number: int,
    verbose: bool = False,
) -> None:
    """Display a single workflow error with all details.

    Shell command details (command, stdout, stderr) are always shown on failure
    for agent diagnosis — not gated by verbose.

    Args:
        error: Error dict from ExecutionResult
        error_number: Error number for display (1-indexed)
        verbose: Reserved for future use (shell details are always shown)
    """
    category = error.get("category") or "unknown"

    if error_number == 1:
        header = "❌ Compilation failed" if category == "compilation" else "❌ Workflow execution failed"
        click.echo(header, err=True)

    node_id = error.get("node_id") or "unknown"
    message = error.get("message") or "Unknown error"

    click.echo(f"\nError {error_number} at node '{node_id}':", err=True)
    click.echo(f"  Category: {category}", err=True)
    click.echo(f"  Message: {message}", err=True)

    # Show suggestion and compilation-specific context
    _display_suggestion_and_compilation_context(error, category)

    # Show raw API response if available (SECURITY FIX: Sanitize before display)
    if (raw := error.get("raw_response")) and isinstance(raw, dict):
        from pflow.core.security_utils import sanitize_parameters

        sanitized_raw = sanitize_parameters(raw)
        _display_api_error_response(sanitized_raw)

    # Show MCP error details (SECURITY FIX: Sanitize before display)
    if (mcp := error.get("mcp_error")) and isinstance(mcp, dict):
        from pflow.core.security_utils import sanitize_parameters

        sanitized_mcp = sanitize_parameters(mcp)
        _display_mcp_error_details(sanitized_mcp)

    # Show available fields for template errors
    if category == "template_error" and (available := error.get("available_fields")):
        total = error.get("available_fields_total", len(available))
        click.echo(f"\n  Available fields in node (showing {min(len(available), 5)} of {total}):", err=True)
        for field in available[:5]:
            click.echo(f"    - {field}", err=True)
        if len(available) > 5:
            click.echo(f"    ... and {len(available) - 5} more (in error details)", err=True)

        # Show trace file hint if fields were truncated
        if error.get("available_fields_truncated"):
            click.echo("\n  📁 Complete field list available in trace file", err=True)
            click.echo("     ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json", err=True)

    # Always show shell command details on failure (agents need this for diagnosis)
    if "shell_command" in error:
        _display_shell_error_details(error)


def _display_suggestion_and_compilation_context(error: dict[str, Any], category: str) -> None:
    """Display suggestion and compilation-specific fields from error dict."""
    if suggestion := error.get("suggestion"):
        click.echo(f"\n  Suggestion: {suggestion}", err=True)

    if category == "compilation":
        if node_type := error.get("node_type"):
            click.echo(f"  Node type: {node_type}", err=True)
        if sub_path := error.get("sub_workflow_path"):
            click.echo(f"  Sub-workflow: {sub_path}", err=True)


def _display_shell_error_details(error: dict[str, Any]) -> None:
    """Display shell command details for a failed shell node.

    Args:
        error: Error dict containing shell_command, shell_stdout, shell_stderr
    """
    click.echo("\n  Shell details:", err=True)
    cmd = error.get("shell_command", "")
    # Truncate very long commands
    cmd_display = cmd[:200] + "..." if len(cmd) > 200 else cmd
    click.echo(f"    Command: {cmd_display}", err=True)
    if stdout := error.get("shell_stdout"):
        stdout_preview = stdout[:300] + "..." if len(stdout) > 300 else stdout
        click.echo(f"    Stdout: {stdout_preview}", err=True)
    if stderr := error.get("shell_stderr"):
        stderr_preview = stderr[:300] + "..." if len(stderr) > 300 else stderr
        click.echo(f"    Stderr: {stderr_preview}", err=True)


def _display_text_error_details(
    result: Any,
    verbose: bool = False,
) -> None:
    """Display detailed text error output.

    Args:
        result: ExecutionResult with error details
        verbose: Reserved for future use (shell details are always shown)
    """
    if not result or not hasattr(result, "errors") or not result.errors:
        # Fallback to generic message
        click.echo("cli: Workflow execution failed - Node returned error action", err=True)
        click.echo("cli: Check node output above for details", err=True)
        return

    for i, error in enumerate(result.errors, 1):
        _display_single_error(error, i, verbose=verbose)
