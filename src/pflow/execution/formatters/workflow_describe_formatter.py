"""Workflow interface description formatter.

Provides shared formatting logic for displaying workflow interfaces,
used by both CLI and MCP server to ensure output parity.
"""

from typing import Any

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
        - Output values (with descriptions)
        - Example usage command

    Example:
        >>> metadata = {
        ...     "description": "Analyzes GitHub PRs",
        ...     "ir": {
        ...         "inputs": {
        ...             "repo": {"required": True, "description": "Repository name"},
        ...             "verbose": {"required": False, "description": "Verbose output", "default": False}
        ...         },
        ...         "outputs": {
        ...             "analysis": {"description": "PR analysis results"}
        ...         }
        ...     }
        ... }
        >>> print(format_workflow_interface("pr-analyzer", metadata))
        Workflow: pr-analyzer
        Description: Analyzes GitHub PRs
        <BLANKLINE>
        Inputs:
          - repo (required): Repository name
          - verbose (optional): Verbose output
            Default: False
        <BLANKLINE>
        Outputs:
          - analysis: PR analysis results
        <BLANKLINE>
        Example Usage:
          pflow pr-analyzer repo=<value>
    """
    ir = metadata.get("ir", {})
    description = metadata.get("description", "No description")

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
        required = config.get("required", True)
        req_text = "required" if required else "optional"
        desc = config.get("description", "")
        default = config.get("default")

        lines.append(f"  - {input_name} ({req_text}): {desc}")
        if default is not None:
            lines.append(f"    Default: {default}")

    return "\n".join(lines)


def _format_outputs_section(ir: dict[str, Any]) -> str:
    """Format the outputs section of workflow interface.

    Args:
        ir: Workflow IR containing outputs specification

    Returns:
        Formatted outputs section with descriptions
    """
    if not ir.get("outputs"):
        return "\nOutputs: None"

    lines = ["\nOutputs:"]

    for output_name, config in ir["outputs"].items():
        desc = config.get("description", "")
        lines.append(f"  - {output_name}: {desc}")

    return "\n".join(lines)


def _format_example_usage_section(name: str, ir: dict[str, Any]) -> str:
    """Format the example usage section.

    Shows command with required parameters as placeholders.

    Args:
        name: Workflow name
        ir: Workflow IR containing inputs specification

    Returns:
        Formatted example usage command
    """
    lines = ["\nExample Usage:"]

    # Collect required parameters
    example_params = []
    if "inputs" in ir:
        for input_name, config in ir["inputs"].items():
            if config.get("required", True):
                example_params.append(f"{input_name}=<value>")

    # Build the example command
    command = f"  pflow {name}"
    if example_params:
        command += f" {' '.join(example_params)}"

    lines.append(command)

    return "\n".join(lines)
