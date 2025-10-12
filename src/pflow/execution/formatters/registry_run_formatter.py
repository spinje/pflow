"""Shared formatters for registry run error messages.

This module provides formatting functions for registry_run error cases,
ensuring CLI and MCP display consistent, helpful error messages.
"""

from pflow.core.suggestion_utils import find_similar_items, format_did_you_mean


def format_node_not_found_error(node_type: str, available_nodes: list[str]) -> str:
    """Format error message when node is not found in registry.

    Args:
        node_type: The node type that wasn't found
        available_nodes: List of all available node IDs

    Returns:
        Formatted error message with suggestions and guidance
    """
    lines = [f"❌ Node '{node_type}' not found in registry"]

    # Find similar nodes using shared utility
    suggestions = find_similar_items(node_type, available_nodes, max_results=5, method="substring")

    # Format suggestion message
    fallback = None if suggestions else sorted(available_nodes)[:10]

    suggestion_msg = format_did_you_mean(
        node_type, suggestions, item_type="node", fallback_items=fallback, max_fallback=10
    )

    lines.append("")
    lines.append(suggestion_msg)

    # Add guidance on how to find nodes
    lines.append("")
    lines.append("To find the right node:")
    lines.append('  - Use registry_discover to search: "describe what you want to do"')
    lines.append("  - Use registry_list to see all available nodes")

    return "\n".join(lines)


def format_execution_error(node_type: str, exception: Exception, verbose: bool = False) -> str:
    """Format error message when node execution fails.

    Provides specific guidance based on error type.

    Args:
        node_type: The node type that failed to execute
        exception: The exception that was raised
        verbose: Whether to include verbose error details

    Returns:
        Formatted error message with context and guidance
    """
    error_type = type(exception).__name__
    error_msg = str(exception)

    lines = [f"❌ Failed to execute node '{node_type}'"]
    lines.append("")

    # Common error patterns with specific guidance
    if isinstance(exception, FileNotFoundError):
        lines.append(f"Error: {error_msg}")
        lines.append("")
        lines.append("Verify the file path exists and is accessible.")
    elif isinstance(exception, PermissionError):
        lines.append(f"Error: {error_msg}")
        lines.append("")
        lines.append("Check file permissions and access rights.")
    elif isinstance(exception, ValueError) and "required" in error_msg.lower():
        lines.append(f"Error: {error_msg}")
        lines.append("")
        lines.append(f"Use 'registry_describe {node_type}' to see required parameters.")
    elif "timeout" in error_msg.lower():
        lines.append("Error: Node execution timed out")
        lines.append("")
        lines.append("Try increasing timeout if supported.")
    else:
        # Generic error
        lines.append(f"Error: {error_msg}")
        lines.append("")
        lines.append(f"Use 'registry_describe {node_type}' to see required parameters.")

        if verbose:
            lines.append("")
            lines.append(f"Error type: {error_type}")

            # For MCP nodes, provide specific guidance
            if node_type.startswith("mcp-"):
                lines.append("")
                lines.append("For MCP nodes:")
                lines.append("  1. Check if server is configured with settings_show")
                lines.append("  2. Verify credentials are set (environment variables)")
                lines.append("  3. Check the MCP server logs for connection issues")

    return "\n".join(lines)


def format_ambiguous_node_error(node_type: str, matches: list[str]) -> str:
    """Format error message when node name is ambiguous.

    Args:
        node_type: The ambiguous node type
        matches: List of matching node IDs

    Returns:
        Formatted error message with all matches
    """
    lines = [f"❌ Ambiguous node name '{node_type}'. Found in multiple servers:"]

    for match in sorted(matches):
        lines.append(f"  - {match}")

    lines.append("")
    lines.append("Please specify the full node ID or use format: {server}-{tool}")

    # Show examples if possible
    if matches:
        lines.append("")
        lines.append("Examples:")
        example = matches[0]
        parts = example.split("-")
        if len(parts) >= 3 and parts[0] == "mcp":
            # MCP node - show different formats
            server_parts = parts[1:-1]
            tool = parts[-1]
            lines.append(f"  registry_run('{example}')  # Full format")
            lines.append(f"  registry_run('{'-'.join(server_parts)}-{tool}')  # Server-qualified")

    return "\n".join(lines)
