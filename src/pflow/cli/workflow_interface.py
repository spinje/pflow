"""CLI adapter for workflow-interface formatting."""

from typing import Any

from pflow.execution.formatters.workflow_describe_formatter import format_workflow_interface
from pflow.execution.result import ResolvedWorkflow


def resolved_interface_metadata(resolved: ResolvedWorkflow) -> dict[str, Any]:
    """The interface metadata of a resolved FILE — ``describe`` and ``<workflow> --help`` of one (a saved
    workflow's is ``WorkflowManager.load``, which adds its run history).

    The description is the file's H1 prose; the IR carries none.
    """
    return {"ir": resolved.ir, "description": resolved.description}


def format_workflow_interface_for_cli(
    name: str,
    metadata: dict[str, Any],
    *,
    example_name: str,
    source: str | None = None,
) -> str:
    """Render a raw heading and a separately shell-safe example command.

    The shared formatter intentionally has one name argument because MCP and
    saved-workflow callers use the same value for both surfaces. Local CLI
    paths need different display and shell representations, so adapt the
    formatter output at this boundary and fail loudly if its heading contract
    ever changes. ``source`` adds a ``Source:`` line under the heading.
    """
    formatted = format_workflow_interface(example_name, metadata)
    heading, separator, remainder = formatted.partition("\n")
    expected_heading = f"Workflow: {example_name}"
    if heading != expected_heading:
        raise RuntimeError(f"Unexpected workflow interface heading: {heading!r}")

    source_line = f"\nSource: {source}" if source is not None else ""
    return f"Workflow: {name}{source_line}{separator}{remainder}"
