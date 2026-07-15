"""CLI adapter for workflow-interface formatting."""

from typing import Any

from pflow.execution.formatters.workflow_describe_formatter import format_workflow_interface


def format_workflow_interface_for_cli(
    name: str,
    metadata: dict[str, Any],
    *,
    example_name: str,
) -> str:
    """Render a raw heading and a separately shell-safe example command.

    The shared formatter intentionally has one name argument because MCP and
    saved-workflow callers use the same value for both surfaces. Local CLI
    paths need different display and shell representations, so adapt the
    formatter output at this boundary and fail loudly if its heading contract
    ever changes.
    """
    formatted = format_workflow_interface(example_name, metadata)
    heading, separator, remainder = formatted.partition("\n")
    expected_heading = f"Workflow: {example_name}"
    if heading != expected_heading:
        raise RuntimeError(f"Unexpected workflow interface heading: {heading!r}")

    return f"Workflow: {name}{separator}{remainder}"
