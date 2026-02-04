"""Shared formatter for workflow list display.

This module provides formatting for workflow lists across CLI and MCP interfaces.
Returns markdown-formatted text that agents can easily read.

Usage:
    >>> from pflow.execution.formatters.workflow_list_formatter import format_workflow_list
    >>> workflows = [{"name": "my-workflow", "description": "Test workflow"}]
    >>> print(format_workflow_list(workflows))
    Saved Workflows:
    ────────────────────────────────────────

    my-workflow
      Test workflow

    Total: 1 workflow
"""

from typing import Any


def format_workflow_list(workflows: list[dict[str, Any]]) -> str:
    """Format workflow list as markdown.

    Args:
        workflows: List of workflow metadata dicts (from WorkflowManager.list_all())

    Returns:
        Formatted markdown string

    Example:
        >>> workflows = [
        ...     {"name": "analyzer", "description": "Analyzes PRs"},
        ...     {"name": "deployer", "description": "Deploys code"}
        ... ]
        >>> result = format_workflow_list(workflows)
        >>> "analyzer" in result
        True
        >>> "Total: 2 workflows" in result
        True
    """
    if not workflows:
        return _format_empty_list()

    lines = [
        "Saved Workflows:",
        "─" * 40,
    ]

    for wf in workflows:
        name = wf.get("name", "Unknown")
        desc = wf.get("description", "No description")
        lines.append(f"\n{name}")
        lines.append(f"  {desc}")

    # Add count
    count = len(workflows)
    plural = "workflow" if count == 1 else "workflows"
    lines.append(f"\nTotal: {count} {plural}")

    return "\n".join(lines)


def _format_empty_list() -> str:
    """Format message for empty workflow list.

    Returns:
        Formatted help message
    """
    lines = [
        "No workflows saved yet.",
        "",
        "To save a workflow:",
        "  1. Create a .pflow.md workflow file",
        "  2. Save it: pflow workflow save my-workflow.pflow.md --name my-workflow",
    ]
    return "\n".join(lines)
