"""Workflow interface description formatter.

Provides shared formatting logic for displaying workflow interfaces,
used by both CLI and MCP server to ensure output parity.
"""

from typing import Any

from pflow.core.types import input_usage, usage_arguments

from .history_formatter import format_execution_history


def format_workflow_interface(name: str, metadata: dict[str, Any]) -> str:
    """Format workflow interface specification for display.

    Args:
        name: Workflow name
        metadata: Workflow metadata containing IR and description

    Returns:
        Formatted markdown string showing:
        - Workflow name and description
        - Input parameters (required/optional, descriptions, defaults)
        - Output values (declared type, descriptions)
        - Example usage command

    Example:
        >>> metadata = {
        ...     "description": "Analyzes GitHub PRs",
        ...     "ir": {
        ...         "inputs": {
        ...             "repo": {"type": "string", "description": "Repository name"},
        ...             "verbose": {"type": "boolean", "description": "Verbose output", "default": False}
        ...         },
        ...         "outputs": {
        ...             "analysis": {"type": "object", "description": "PR analysis results"}
        ...         }
        ...     }
        ... }
        >>> print(format_workflow_interface("pr-analyzer", metadata))
        Workflow: pr-analyzer
        Description: Analyzes GitHub PRs
        <BLANKLINE>
        Inputs:
          - repo (string, required): Repository name
          - verbose (boolean, optional): Verbose output
            Default: false
        <BLANKLINE>
        Outputs:
          - analysis (object): PR analysis results
        <BLANKLINE>
        Example Usage:
          pflow pr-analyzer repo=<string>
    """
    ir = metadata.get("ir", {})
    description = metadata.get("description") or "No description"

    # Build formatted sections
    lines = []

    # Basic info
    lines.append(f"Workflow: {name}")
    lines.append(f"Description: {description}")

    # Execution history (if available) — fields are top-level in flat metadata
    if execution_history := _format_execution_history_section(metadata):
        lines.append(execution_history)

    # Inputs section
    lines.append(_format_inputs_section(ir))

    # Outputs section
    lines.append(_format_outputs_section(ir))

    # Example usage section
    lines.append(_format_example_usage_section(name, ir))

    return "\n".join(lines)


def _format_execution_history_section(metadata: dict[str, Any]) -> str:
    """Format the execution history section.

    Args:
        metadata: Workflow metadata (flat structure, execution fields at top level)

    Returns:
        Formatted execution history section or empty string if no history
    """
    if not metadata:
        return ""

    history = format_execution_history(metadata, mode="detailed")
    if not history:
        return ""

    lines = ["\nExecution History:"]
    lines.append(history)

    return "\n".join(lines)


def _format_inputs_section(ir: dict[str, Any]) -> str:
    """Format the inputs section of workflow interface.

    Args:
        ir: Workflow IR containing inputs specification

    Returns:
        Formatted inputs section with required/optional status and defaults
    """
    if not ir.get("inputs"):
        return "\nInputs: None"

    lines = ["\nInputs:"]

    for input_name, config in ir["inputs"].items():
        usage = input_usage(config)
        stdin_marker = " [stdin]" if usage.stdin else ""
        status = "required" if usage.required else "optional"
        lines.append(f"  - {input_name}{stdin_marker} ({usage.type}, {status}): {config.get('description', '')}")
        if usage.default is not None:
            lines.append(f"    Default: {usage.default}")

    return "\n".join(lines)


def _format_outputs_section(ir: dict[str, Any]) -> str:
    """Format the outputs section of workflow interface.

    Args:
        ir: Workflow IR containing outputs specification

    Returns:
        Formatted outputs section — a declared type in parentheses, then the description
    """
    if not ir.get("outputs"):
        return "\nOutputs: None"

    lines = ["\nOutputs:"]

    for output_name, config in ir["outputs"].items():
        desc = config.get("description", "")
        stdout_marker = " [stdout]" if config.get("stdout") is True else ""
        declared_type = f" ({config['type']})" if isinstance(config.get("type"), str) else ""
        lines.append(f"  - {output_name}{stdout_marker}{declared_type}: {desc}")

    return "\n".join(lines)


def _format_example_usage_section(name: str, ir: dict[str, Any]) -> str:
    """Format the example usage section.

    Shows the command with each required input as ``name=<placeholder>``.

    Args:
        name: Workflow name
        ir: Workflow IR containing inputs specification

    Returns:
        Formatted example usage command
    """
    lines = ["\nExample Usage:"]

    lines.append("  " + " ".join([f"pflow {name}", *usage_arguments(ir.get("inputs") or {})]))

    return "\n".join(lines)
