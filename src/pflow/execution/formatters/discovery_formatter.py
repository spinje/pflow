"""Shared formatters for workflow discovery results.

This module provides formatting functions for displaying workflow discovery
results across CLI and MCP interfaces. All formatters return strings that can
be displayed directly or incorporated into structured responses.

Usage:
    >>> from pflow.execution.formatters.discovery_formatter import format_discovery_result
    >>> result = format_discovery_result(
    ...     discovery_result={"workflow_name": "test", "confidence": 0.9},
    ...     workflow={"description": "...", "ir": {...}},
    ... )
    >>> print(result)
    ## test
    ...
"""

from typing import Any

from .history_formatter import format_execution_history


def format_discovery_result(result: dict[str, Any], workflow: dict[str, Any]) -> str:
    """Format and display workflow discovery results.

    Args:
        result: Discovery result with workflow_name, confidence, reasoning
        workflow: Workflow IR with metadata, flow, inputs, outputs

    Returns:
        Formatted markdown string

    Example:
        >>> result = {
        ...     "workflow_name": "github-analyzer",
        ...     "confidence": 0.85,
        ...     "reasoning": "Matches PR analysis requirements"
        ... }
        >>> workflow = {
        ...     "description": "Analyzes PRs", "version": "1.0.0",
        ...     "ir": {
        ...         "inputs": {"repo": {"required": True, "type": "string"}},
        ...         "outputs": {"analysis": {"type": "object"}}
        ...     }
        ... }
        >>> formatted = format_discovery_result(result, workflow)
        >>> "## github-analyzer" in formatted
        True
        >>> "85%" in formatted
        True
    """
    lines = []

    # Header with workflow name
    workflow_name = result.get("workflow_name", "Unknown")
    lines.append(f"\n## {workflow_name}")

    # Metadata section
    metadata_lines = format_workflow_metadata(workflow)
    lines.extend(metadata_lines)

    # Extract IR (handle wrapped format)
    ir = workflow.get("ir", workflow)

    # Flow section
    flow_lines = format_workflow_flow(ir)
    lines.extend(flow_lines)

    # Inputs/Outputs section
    io_lines = format_workflow_inputs_outputs(ir)
    lines.extend(io_lines)

    # Confidence score and reasoning
    confidence = result.get("confidence", 0)
    lines.append(f"**Confidence**: {confidence:.0%}")

    if reasoning := result.get("reasoning"):
        lines.append(f"*Why*: {reasoning}")

    # Actionable guidance based on confidence
    lines.append("")
    lines.append(_format_confidence_guidance(workflow_name, confidence, ir))

    return "\n".join(lines)


def _format_confidence_guidance(workflow_name: str, confidence: float, ir: dict[str, Any]) -> str:
    """Return actionable next-step guidance based on confidence level.

    High confidence → run immediately.
    Medium confidence → show differences, ask user.
    Low confidence → suggest modifications or building new.
    """
    # Build example run command from inputs
    run_hint = _build_run_hint(workflow_name, ir)

    if confidence >= 0.95:
        return f"**→ High confidence match.** Run it:\n  {run_hint}"

    if confidence >= 0.80:
        return (
            f"**→ Partial match.** Show the user what this workflow does vs what they asked for.\n"
            f"  Ask: use as-is, modify, or build new?\n"
            f"  Details: `pflow describe {workflow_name}`"
        )

    # 70-79% (below 70% is handled by format_no_matches_with_suggestions)
    return (
        f"**→ Weak match.** Suggest modifying this workflow to fit.\n"
        f"  Review: `pflow describe {workflow_name}`\n"
        f"  Source: `cat ~/.pflow/workflows/{workflow_name}/{workflow_name}.pflow.md`"
    )


def _build_run_hint(workflow_name: str, ir: dict[str, Any]) -> str:
    """Build an example pflow run command from workflow inputs."""
    parts = [f"pflow {workflow_name}"]
    inputs = ir.get("inputs", {})
    for key, spec in inputs.items():
        if spec.get("required", True) and not spec.get("stdin"):
            input_type = spec.get("type", "string")
            parts.append(f'{key}="<{input_type}>"')
    return " ".join(parts)


def format_workflow_metadata(workflow: dict[str, Any]) -> list[str]:
    """Format workflow metadata section.

    Handles both flat metadata (from WorkflowManager.load()) and legacy
    wrapper format ({"metadata": {"description": ...}}).

    Args:
        workflow: Workflow dict with metadata (flat or wrapped)

    Returns:
        List of formatted lines
    """
    lines = []

    # Flat metadata (production format from WorkflowManager.load())
    description = workflow.get("description")
    version = workflow.get("version")

    # Fallback to legacy wrapper format
    if description is None and "metadata" in workflow:
        meta = workflow["metadata"]
        if isinstance(meta, dict):
            description = meta.get("description")
            version = meta.get("version")

    if description:
        lines.append(f"**Description**: {description}")
    if version:
        lines.append(f"**Version**: {version}")

    # Add execution history if available (flat metadata, fields at top level)
    if workflow.get("execution_count", 0) > 0:
        history = format_execution_history(workflow, mode="compact")
        if history:
            lines.append(f"**Executed**: {history}")

    return lines


def format_workflow_flow(ir: dict[str, Any]) -> list[str]:
    """Format workflow node flow.

    Handles both "edges" (production IR format) and legacy "flow" key.

    Args:
        ir: Workflow IR with edges or flow field

    Returns:
        List of formatted lines
    """
    lines = []

    edges = ir.get("edges") or ir.get("flow") or []
    if edges:
        # Show first 3 nodes in flow
        flow_str = " >> ".join([str(edge.get("from", "?")) for edge in edges[:3]])
        if len(edges) > 3:
            flow_str += " >> ..."
        lines.append(f"**Node Flow**: {flow_str}")

    return lines


def format_workflow_inputs_outputs(ir: dict[str, Any]) -> list[str]:
    """Format workflow inputs and outputs.

    Args:
        ir: Workflow IR with inputs and outputs

    Returns:
        List of formatted lines
    """
    lines = []

    # Format inputs
    if inputs := ir.get("inputs"):
        lines.append("**Inputs**:")
        for key, spec in inputs.items():
            req = "(required)" if spec.get("required", True) else "(optional)"
            input_type = spec.get("type", "any")
            desc = spec.get("description", "")
            lines.append(f"  - {key}: {input_type} {req} - {desc}")

    # Format outputs
    if outputs := ir.get("outputs"):
        lines.append("**Outputs**:")
        for key, spec in outputs.items():
            output_type = spec.get("type", "any")
            desc = spec.get("description", "")
            lines.append(f"  - {key}: {output_type} - {desc}")

    return lines


def format_no_matches_with_suggestions(
    workflow_names: list[str],
    query: str,
    reasoning: str | None = None,
    max_suggestions: int = 10,
) -> str:
    """Format no matches message with workflow suggestions and LLM reasoning.

    When workflow discovery doesn't find a match above the confidence threshold,
    show available workflows to help users discover what exists and refine their query.
    Optionally includes LLM reasoning to explain why no match was found.

    Args:
        workflow_names: List of workflow names
        query: The user's original search query
        reasoning: Optional LLM reasoning explaining why no match was found
        max_suggestions: Maximum number of suggestions to show (default: 10)

    Returns:
        Formatted string with suggestions and guidance

    Example:
        >>> names = ["test-workflow", "github-analyzer"]
        >>> result = format_no_matches_with_suggestions(names, "test something")
        >>> "test-workflow" in result
        True
    """
    lines = []

    # No match header
    lines.append(f'No workflows found matching "{query}" (minimum 70% confidence).')

    # Add LLM reasoning if provided
    if reasoning:
        lines.append(f"\nWhy: {reasoning}")

    if workflow_names:
        lines.append("\nAvailable workflows:")

        for name in workflow_names[:max_suggestions]:
            lines.append(f"  • {name}")

        # Show count if more workflows exist
        if len(workflow_names) > max_suggestions:
            remaining = len(workflow_names) - max_suggestions
            lines.append(f"\n... and {remaining} more workflow{'' if remaining == 1 else 's'}")

    lines.append("\n**→ No match.** Build a new workflow.")
    lines.append("  Start with: `pflow guide core`")
    lines.append('  Or try a more specific query: `pflow find "workflow for [specific task]"`')

    return "\n".join(lines)
