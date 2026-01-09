"""Shared formatters for workflow discovery results.

This module provides formatting functions for displaying workflow discovery
results across CLI and MCP interfaces. All formatters return strings that can
be displayed directly or incorporated into structured responses.

Usage:
    >>> from pflow.execution.formatters.discovery_formatter import format_discovery_result
    >>> result = format_discovery_result(
    ...     discovery_result={"workflow_name": "test", "confidence": 0.9},
    ...     workflow={"metadata": {...}, "ir": {...}},
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
        ...     "metadata": {"description": "Analyzes PRs", "version": "1.0.0"},
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

    # Confidence score
    confidence = result.get("confidence", 0)
    lines.append(f"**Confidence**: {confidence:.0%}")

    # Reasoning
    if reasoning := result.get("reasoning"):
        lines.append(f"\n*Match reasoning*: {reasoning}")

    return "\n".join(lines)


def format_workflow_metadata(workflow: dict[str, Any]) -> list[str]:
    """Format workflow metadata section.

    Args:
        workflow: Workflow dict with metadata

    Returns:
        List of formatted lines
    """
    lines = []

    if "metadata" in workflow:
        meta = workflow["metadata"]
        if isinstance(meta, dict):
            lines.append(f"**Description**: {meta.get('description', 'No description')}")
            lines.append(f"**Version**: {meta.get('version', '1.0.0')}")

    # Add execution history if available
    if "rich_metadata" in workflow:
        history = format_execution_history(workflow["rich_metadata"], mode="compact")
        if history:
            lines.append(f"**Executed**: {history}")

    return lines


def format_workflow_flow(ir: dict[str, Any]) -> list[str]:
    """Format workflow node flow.

    Args:
        ir: Workflow IR with flow field

    Returns:
        List of formatted lines
    """
    lines = []

    if "flow" in ir:
        flow = ir.get("flow", [])
        if flow:
            # Show first 3 nodes in flow
            flow_str = " >> ".join([edge["from"] for edge in flow[:3]])
            if len(flow) > 3:
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
            req = "(required)" if spec.get("required") else "(optional)"
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
    workflows: list[dict[str, Any]],
    query: str,
    reasoning: str | None = None,
    max_suggestions: int = 10,
) -> str:
    """Format no matches message with workflow suggestions and LLM reasoning.

    When workflow discovery doesn't find a match above the confidence threshold,
    show available workflows to help users discover what exists and refine their query.
    Optionally includes LLM reasoning to explain why no match was found.

    Args:
        workflows: List of workflow metadata dicts with 'name' and 'description'
        query: The user's original search query
        reasoning: Optional LLM reasoning explaining why no match was found
        max_suggestions: Maximum number of suggestions to show (default: 5)

    Returns:
        Formatted string with suggestions and guidance

    Example:
        >>> workflows = [
        ...     {"name": "test-workflow", "description": "Test workflow"},
        ...     {"name": "github-analyzer", "description": "Analyze GitHub PRs"}
        ... ]
        >>> result = format_no_matches_with_suggestions(workflows, "test something")
        >>> "Possibly related workflows:" in result
        True
        >>> "test-workflow" in result
        True
    """
    lines = []

    # No match header
    lines.append(f'No workflows found matching "{query}" (minimum 70% confidence).')

    # Add LLM reasoning if provided
    if reasoning:
        lines.append(f"\nWhy: {reasoning}")

    if workflows:
        # TODO: Change label back to "Possibly related workflows:" after enhancing LLM
        # to return top 3-5 matches with individual confidence scores instead of just
        # returning all workflows via list_all(). Current implementation shows ALL
        # workflows, not LLM-ranked suggestions.
        lines.append("\nAvailable workflows:")

        # Limit to max_suggestions
        for workflow in workflows[:max_suggestions]:
            name = workflow.get("name", "unknown")
            lines.append(f"  • {name}")

        # Show count if more workflows exist
        if len(workflows) > max_suggestions:
            remaining = len(workflows) - max_suggestions
            lines.append(f"\n... and {remaining} more workflow{'' if remaining == 1 else 's'}")

    lines.append("\nTry:")
    lines.append('  • More specific query: "workflow for [specific task]"')

    if not workflows:
        lines.append("  • Recommendation: Create your first workflow")
    else:
        lines.append("  • Recommendation: Try building a new workflow")

    return "\n".join(lines)
