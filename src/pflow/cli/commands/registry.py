"""Registry CLI commands for pflow.

This Click group is invoked by main_wrapper.py when it detects "registry" as the first
positional argument. The wrapper manipulates sys.argv to remove "registry" before calling
this group, allowing normal Click command processing for the subcommands.

Architecture: main_wrapper.py -> registry() group -> individual commands (list, describe, search, scan)
"""

import json
import sys
from pathlib import Path
from typing import Optional

import click

from pflow.execution.formatters.registry_list_formatter import format_registry_list
from pflow.execution.formatters.registry_search_formatter import format_search_results
from pflow.registry import Registry


@click.group(name="registry")
def registry() -> None:
    """Manage the pflow node registry."""
    pass


def _output_json_nodes(nodes: dict) -> None:
    """Output nodes in JSON format."""
    output = {
        "nodes": [
            {
                "name": name,
                "type": _get_node_type(name, data),
                "description": data.get("interface", {}).get("description", ""),
            }
            for name, data in nodes.items()
        ]
    }
    click.echo(json.dumps(output, indent=2))


@registry.command(name="list")
@click.argument("filter_pattern", required=False)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def list_nodes(filter_pattern: str | None, output_json: bool) -> None:
    """List registered nodes, optionally filtered by pattern.

    Without pattern: Shows all nodes grouped by package.
    With pattern: Shows matching nodes sorted by relevance.
    Multiple keywords: Space-separated keywords use AND logic.

    Examples:
        pflow registry list                 # All nodes
        pflow registry list github          # Nodes matching 'github'
        pflow registry list github api      # Nodes matching 'github' AND 'api'
    """
    reg = Registry()

    try:
        # Check if this is first time (for user feedback)
        first_time = not reg.registry_path.exists()

        if first_time and not output_json:
            click.echo("[Auto-discovering core nodes...]")

        # If filter provided, use search (relevance-sorted)
        if filter_pattern:
            results = reg.search(filter_pattern)

            if output_json:
                # Format as JSON with scores
                output = {
                    "query": filter_pattern,
                    "results": [
                        {
                            "name": name,
                            "type": _get_node_type(name, data),
                            "score": score,
                            "description": data.get("interface", {}).get("description", ""),
                        }
                        for name, data, score in results
                    ],
                }
                click.echo(json.dumps(output, indent=2))
            else:
                # Transform for shared formatter
                matches = [
                    {
                        "node_id": name,
                        "description": data.get("interface", {}).get("description", ""),
                        "match_type": _get_match_type_from_score(score),
                        "metadata": data,
                    }
                    for name, data, score in results
                ]

                # Use shared search formatter
                result = format_search_results(filter_pattern, matches)
                click.echo(result)
        else:
            # No filter - show all grouped by package (current behavior)
            nodes = reg.load()

            if output_json:
                _output_json_nodes(nodes)
            else:
                # Use shared formatter for CLI parity with MCP
                result = format_registry_list(nodes)
                click.echo(result)

    except Exception as e:
        click.echo(f"Error: Failed to list nodes: {e}", err=True)
        sys.exit(1)


def _output_json_describe(node: str, metadata: dict) -> None:
    """Output node description in JSON format."""
    interface = metadata.get("interface", {})
    output = {
        "name": node,
        "type": _get_node_type(node, metadata),
        "module": metadata.get("module", ""),
        "class_name": metadata.get("class_name", ""),
        "description": interface.get("description", ""),
        "interface": interface,
    }
    click.echo(json.dumps(output, indent=2))


def _handle_nonexistent_path(scan_path: Path, path: Optional[str], output_json: bool) -> None:
    """Handle case when scan path doesn't exist."""
    error_msg = f"Path does not exist: {scan_path}"
    if output_json:
        output = {"error": error_msg, "path": str(scan_path)}
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo(error_msg)
        if not path:  # Default path
            click.echo("\nTo add custom nodes:")
            click.echo(f"  1. Create directory: mkdir -p {scan_path}")
            click.echo(f"  2. Add node files: cp my_node.py {scan_path}/")
            click.echo("  3. Run scan again: pflow registry scan")
    sys.exit(1)


def _categorize_nodes(user_nodes: list, output_json: bool) -> tuple[list, list]:
    """Categorize nodes into valid and invalid."""
    valid_nodes = []
    invalid_nodes = []

    for node in user_nodes:
        interface = node.get("interface", {})
        desc = interface.get("description", "No description")

        # Check if node is valid (has required methods)
        if node.get("class_name"):
            valid_nodes.append(node)
            if not output_json:
                click.echo(f"  ✓ {node['name']}: {desc}")
        else:
            invalid_nodes.append(node)
            if not output_json:
                click.echo(f"  ⚠ {node['name']}: Invalid - missing required methods")

    return valid_nodes, invalid_nodes


def _add_nodes_to_registry(valid_nodes: list, reg: Registry) -> int:
    """Add valid nodes to registry and return count."""
    current_nodes = reg.load()
    added_count = 0

    for node in valid_nodes:
        name = node["name"]
        node_copy = dict(node)
        node_copy["type"] = "user"
        del node_copy["name"]
        current_nodes[name] = node_copy
        added_count += 1

    reg._save_with_metadata(current_nodes)
    return added_count


def _output_json_scan(found: int, added: int, valid_nodes: list) -> None:
    """Output scan results in JSON format."""
    output = {
        "found": found,
        "added": added,
        "nodes": [
            {"name": node["name"], "description": node.get("interface", {}).get("description", "")}
            for node in valid_nodes
        ],
    }
    click.echo(json.dumps(output, indent=2))


def _perform_scan(reg: Registry, scan_path: Path, force: bool, output_json: bool) -> None:
    """Perform the actual scanning and adding of nodes."""
    if not output_json:
        click.echo(f"Scanning {scan_path} for custom nodes...\n")

    # Scan for nodes
    user_nodes = reg.scan_user_nodes(scan_path)

    if not user_nodes:
        if output_json:
            _output_json_scan(0, 0, [])
        else:
            click.echo("No valid nodes found.")
        return

    # Categorize nodes
    valid_nodes, _invalid_nodes = _categorize_nodes(user_nodes, output_json)

    if not valid_nodes:
        if output_json:
            _output_json_scan(len(user_nodes), 0, [])
        else:
            click.echo("\nNo valid nodes to add.")
        return

    # Confirm addition (skip in JSON mode or with --force)
    if not output_json and not force and not click.confirm(f"\nAdd {len(valid_nodes)} nodes to registry?"):
        click.echo("Cancelled.")
        return

    # Add nodes to registry
    added_count = _add_nodes_to_registry(valid_nodes, reg)

    if output_json:
        _output_json_scan(len(user_nodes), added_count, valid_nodes)
    else:
        click.echo(f"✓ Added {added_count} custom nodes to registry")


def _handle_scan_error(e: Exception, output_json: bool) -> None:
    """Handle errors during scanning."""
    if output_json:
        output = {"error": str(e)}
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo(f"Error: Failed to scan: {e}", err=True)
    sys.exit(1)


@registry.command(name="scan")
@click.argument("path", required=False)
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def scan(path: Optional[str], force: bool, output_json: bool) -> None:
    """Scan for custom user nodes.

    Default path: ~/.pflow/nodes/

    Examples:
        pflow registry scan                  # Scan default location
        pflow registry scan ./my-nodes/      # Scan custom directory
    """
    reg = Registry()
    scan_path = Path(path) if path else (Path.home() / ".pflow" / "nodes")

    # Security warning
    if not output_json:
        click.echo("⚠️  WARNING: Custom nodes execute with your user privileges.")
        click.echo("   Only add nodes from trusted sources.\n")

    if not scan_path.exists():
        _handle_nonexistent_path(scan_path, path, output_json)

    try:
        _perform_scan(reg, scan_path, force, output_json)
    except Exception as e:
        _handle_scan_error(e, output_json)


def _get_node_type(name: str, metadata: dict) -> str:
    """Determine node type from name and metadata.

    Args:
        name: Node name
        metadata: Node metadata dict

    Returns:
        Node type: "core", "user", or "mcp"
    """
    # Check if explicitly marked
    if "type" in metadata:
        return str(metadata["type"])

    # Check for MCP pattern
    if name.startswith("mcp-"):
        return "mcp"

    # Check for virtual path (MCP)
    file_path = metadata.get("file_path", "")
    if "virtual://mcp" in file_path:
        return "mcp"

    # Check for core node path
    if "/src/pflow/nodes/" in file_path:
        return "core"

    # Default to user
    return "user"


def _get_match_type_from_score(score: int) -> str:
    """Convert search score to match_type for formatter.

    Args:
        score: Registry search score (100=exact, 90=prefix, 70=name, else=description)

    Returns:
        Match type: "exact", "prefix", "node_id", or "description"
    """
    if score == 100:
        return "exact"
    elif score == 90:
        return "prefix"
    elif score >= 70:
        return "node_id"
    else:
        return "description"


@registry.command(name="discover")
@click.argument("query")
def discover_nodes(query: str) -> None:
    """Discover nodes needed for a specific task.

    Uses LLM to intelligently select relevant nodes based on
    a natural language description of what you want to build.

    Example:
        pflow registry discover "I need to fetch GitHub data and analyze it"
    """
    from pflow.registry.discovery import discover_components

    # Validate query before processing
    query = query.strip()
    if not query:
        click.echo("Error: registry discover query cannot be empty", err=True)
        sys.exit(1)
    if len(query) > 500:
        click.echo(f"Error: Query too long (max 500 characters, got {len(query)})", err=True)
        click.echo("  Please use a more concise description", err=True)
        sys.exit(1)

    try:
        result = discover_components(query)
    except Exception as e:
        # Show agent-friendly error without internal details
        from pflow.cli.discovery_errors import handle_discovery_error

        handle_discovery_error(
            e,
            discovery_type="node",
            alternative_commands=[
                ("pflow registry list", "Browse all nodes"),
                ("pflow registry describe <node>", "Get node specifications"),
            ],
        )
        sys.exit(1)

    # Display rendered component context
    if result.component_context:
        click.echo(result.component_context)
    elif result.node_ids:
        click.echo(f"Found {len(result.node_ids)} relevant nodes:")
        for nid in result.node_ids:
            click.echo(f"  - {nid}")
    else:
        click.echo("No relevant nodes found.")
        click.echo("\nTip: Try a more specific query or use 'pflow registry list' to see all nodes.")


@registry.command(name="run")
@click.argument("node_type")
@click.argument("params", nargs=-1)
@click.option(
    "--output-format",
    type=click.Choice(["json"]),
    default=None,
    help="Output format: json bypasses structure mode for raw output",
)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed execution information")
def run_node(
    node_type: str,
    params: tuple[str, ...],
    output_format: str | None,
    verbose: bool,
) -> None:
    """Run a single node with provided parameters for testing.

    Examples:

        pflow registry run read-file file_path=/tmp/test.txt

        pflow registry run llm prompt="Hello world"

        pflow registry run mcp-slack-fetch channel=C123

        pflow registry run shell command="ls -la" --output-format json

    This command is useful for:

    - Testing node parameters before building workflows

    - Discovering output structure for nodes with 'Any' types

    - Verifying credentials and authentication

    - Quick iteration during workflow development

    Node name variations (MCP nodes):

    - Full: mcp-slack-composio-SLACK_SEND_MESSAGE

    - Server-qualified: slack-composio-SLACK_SEND_MESSAGE

    - Tool name only: SLACK_SEND_MESSAGE (if unique)
    """
    from pflow.cli.commands.registry_run import execute_single_node

    execute_single_node(
        node_type=node_type,
        params=params,
        output_format=output_format or "text",  # Default to text for formatter
        show_structure=(output_format != "json"),  # Structure mode unless --output-format json
        verbose=verbose,
    )


def normalize_node_id(user_input: str, available_nodes: set[str]) -> str | None:
    """Normalize node ID to match registry format.

    Handles multiple input formats:
    - Full format: mcp-server-TOOL_NAME
    - Hyphen variant: mcp-server-TOOL-NAME (converts to underscore)
    - Short form: TOOL_NAME or TOOL-NAME (tries to match unique tool)

    Args:
        user_input: User-provided node ID
        available_nodes: Set of registered node IDs

    Returns:
        Normalized node ID if found, None otherwise
    """
    # Try exact match first
    if user_input in available_nodes:
        return user_input

    # Strategy 1: Try converting ALL hyphens to underscores (for simple short forms)
    normalized_all = user_input.replace("-", "_")
    if normalized_all in available_nodes:
        return normalized_all

    # Strategy 2: For MCP format, try smart conversion
    # Pattern: mcp-{server}-{TOOL-NAME} or {server}-{TOOL-NAME}
    # We want: mcp-{server}-{TOOL_NAME} (hyphens in prefix, underscores in tool)
    if "mcp-" in user_input or user_input.count("-") >= 2:
        # Try to find matching node by comparing with hyphens converted to underscores in tool name only
        for node_id in available_nodes:
            # Create a version of node_id with underscores replaced by hyphens for comparison
            node_with_hyphens = node_id.replace("_", "-")
            if user_input == node_with_hyphens:
                return node_id

    # Strategy 3: Try matching as short form (just tool name without prefix)
    # For MCP tools: TOOL_NAME → mcp-server-TOOL_NAME
    # For MCP tools with hyphens: TOOL-NAME → mcp-server-TOOL_NAME
    matches = []
    for node_id in available_nodes:
        # Check if node ends with the user input (exact or normalized)
        if node_id.endswith(user_input) or node_id.endswith(normalized_all):
            matches.append(node_id)

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        # Ambiguous - return None and let caller handle error
        return None

    return None


def _validate_andnormalize_node_ids(
    node_ids: tuple[str, ...], available_nodes: set[str]
) -> tuple[list[str], dict[str, list[str]], list[str]]:
    """Validate and normalize node IDs.

    Args:
        node_ids: User-provided node IDs to validate
        available_nodes: Set of available node IDs from registry

    Returns:
        Tuple of (normalized_ids, ambiguous_nodes, invalid_nodes)
    """
    normalized_ids = []
    invalid_nodes = []
    ambiguous_nodes = {}

    for user_id in node_ids:
        normalized = normalize_node_id(user_id, available_nodes)
        if normalized:
            normalized_ids.append(normalized)
        else:
            # Check if it was ambiguous
            normalized_check = user_id.replace("-", "_")
            matches = [n for n in available_nodes if n.endswith(user_id) or n.endswith(normalized_check)]
            if len(matches) > 1:
                ambiguous_nodes[user_id] = matches
            else:
                invalid_nodes.append(user_id)

    return normalized_ids, ambiguous_nodes, invalid_nodes


def _handle_node_validation_errors(
    ambiguous_nodes: dict[str, list[str]], invalid_nodes: list[str], available_nodes: set[str]
) -> None:
    """Display errors for ambiguous or invalid nodes and exit.

    Args:
        ambiguous_nodes: Mapping of ambiguous user IDs to matching node IDs
        invalid_nodes: List of invalid user IDs
        available_nodes: Set of available node IDs for error messages
    """
    if ambiguous_nodes:
        for user_id, matches in ambiguous_nodes.items():
            click.echo(f"Error: Ambiguous node name '{user_id}'. Found in multiple servers:", err=True)
            for match in sorted(matches):
                click.echo(f"  - {match}", err=True)
            click.echo("\nPlease specify the full node ID or use format: {server}-{tool}", err=True)
        sys.exit(1)

    if invalid_nodes:
        click.echo(f"Error: Unknown nodes: {', '.join(invalid_nodes)}", err=True)
        click.echo("\nAvailable nodes:", err=True)
        for node in sorted(available_nodes)[:20]:  # Show first 20
            click.echo(f"  - {node}", err=True)
        if len(available_nodes) > 20:
            click.echo(f"  ... and {len(available_nodes) - 20} more", err=True)
        click.echo("\nUse 'pflow registry list' to see all nodes.", err=True)
        sys.exit(1)


@registry.command(name="describe")
@click.argument("node_ids", nargs=-1, required=True)
def describe_nodes(node_ids: tuple[str, ...]) -> None:
    """Get detailed information about specific nodes.

    Shows complete interface specifications including inputs,
    outputs, parameters, and examples.

    Example:
        pflow registry describe github-get-pr llm write-file
    """
    from pflow.registry.context_builder import build_component_context

    # Load registry
    reg = Registry()
    registry_metadata = reg.load()

    # Validate node IDs exist with normalization
    # registry_metadata is dict[str, dict] where keys are node IDs
    available_nodes = set(registry_metadata.keys())

    # Validate and normalize all node IDs
    normalized_ids, ambiguous_nodes, invalid_nodes = _validate_andnormalize_node_ids(node_ids, available_nodes)

    # Handle any validation errors
    if ambiguous_nodes or invalid_nodes:
        _handle_node_validation_errors(ambiguous_nodes, invalid_nodes, available_nodes)

    # Build detailed context using normalized IDs
    try:
        context = build_component_context(
            selected_node_ids=normalized_ids, selected_workflow_names=[], registry_metadata=registry_metadata
        )
        click.echo(context)
    except Exception as e:
        click.echo(f"Error building node details: {e}", err=True)
        sys.exit(1)
