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

from pflow.registry import Registry


@click.group(name="registry")
def registry() -> None:
    """Manage the pflow node registry."""
    pass


def _extract_package_name(name: str, metadata: dict) -> str:
    """Extract package/group name from node name.

    Args:
        name: Node name
        metadata: Node metadata

    Returns:
        Package name for grouping
    """
    node_type = _get_node_type(name, metadata)

    if node_type == "mcp":
        # mcp-{server}-{tool} → server
        parts = name.split("-", 2)
        return parts[1] if len(parts) > 1 else "unknown"

    elif node_type == "core":
        # Special handling for file operations
        if name in ["read-file", "write-file", "copy-file", "move-file", "delete-file"]:
            return "file"

        # Standalone nodes (single-node packages)
        if name in [
            "llm",
            "shell",
            "mcp",
            "echo",
            "example",
            "custom-name",
            "no-docstring",
            "retry-example",
            "structured-example",
        ]:
            # For test nodes, group them
            if name in ["echo", "example", "custom-name", "no-docstring", "retry-example", "structured-example"]:
                return "test"
            return name

        # Extract prefix (git-, github-, etc.)
        if "-" in name:
            return name.split("-")[0]

        return name

    else:  # user nodes
        return "user"


def _format_node_name(name: str, metadata: dict, package: str) -> str:
    """Format node name for display (remove redundant prefixes).

    Args:
        name: Full node name
        metadata: Node metadata
        package: Package name

    Returns:
        Formatted display name
    """
    node_type = _get_node_type(name, metadata)

    if node_type == "mcp":
        # Remove mcp-{server}- prefix and clean up underscores
        prefix = f"mcp-{package}-"
        if name.startswith(prefix):
            tool_name = name[len(prefix) :]
            # Remove redundant server prefix if present (e.g., slack_add_reaction → add_reaction)
            if tool_name.startswith(f"{package}_"):
                tool_name = tool_name[len(package) + 1 :]
            # Convert underscores to hyphens for consistency
            return tool_name.replace("_", "-")
        return name

    elif node_type == "core":
        # For file operations, keep full name for clarity
        if package == "file":
            return name
        # For standalone packages, just show the name
        if package == name:
            return name
        # For test nodes, show full name
        if package == "test":
            return name
        # For others, optionally remove package prefix
        # But for git/github, keeping full name is clearer
        return name

    return name  # user nodes show full name


def _group_nodes_by_package(nodes: dict) -> dict:
    """Group nodes by their package/server.

    Args:
        nodes: All registry nodes

    Returns:
        Grouped nodes by type and package
    """
    grouped: dict[str, dict[str, list[tuple[str, dict]]]] = {"core": {}, "mcp": {}, "user": {}}

    for name, metadata in nodes.items():
        node_type = _get_node_type(name, metadata)
        package = _extract_package_name(name, metadata)

        if node_type not in grouped:
            grouped[node_type] = {}

        if package not in grouped[node_type]:
            grouped[node_type][package] = []

        grouped[node_type][package].append((name, metadata))

    # Sort packages and nodes within packages
    for node_type in grouped:
        for package in grouped[node_type]:
            grouped[node_type][package].sort(key=lambda x: x[0])
        grouped[node_type] = dict(sorted(grouped[node_type].items()))

    return grouped


def _display_package_section(package_nodes: dict, section_type: str) -> None:
    """Display a section of nodes grouped by package."""
    for package, nodes in package_nodes.items():
        count = len(nodes)
        unit = ("node" if count == 1 else "nodes") if section_type == "core" else ("tool" if count == 1 else "tools")
        click.echo(f"\n{package} ({count} {unit})")

        for name, metadata in nodes:
            display_name = _format_node_name(name, metadata, package)
            desc = metadata.get("interface", {}).get("description", "")
            # Use 75 chars for description
            desc = desc[:72] + "..." if len(desc) > 75 else desc[:75]
            click.echo(f"  {display_name:25} {desc}")


def _display_user_nodes(user_nodes: dict) -> None:
    """Display user nodes."""
    for _package, package_nodes in user_nodes.items():
        for name, metadata in package_nodes:
            desc = metadata.get("interface", {}).get("description", "")
            # Use 75 chars for description
            desc = desc[:72] + "..." if len(desc) > 75 else desc[:75]
            click.echo(f"  {name:25} {desc}")


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
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def list_nodes(output_json: bool) -> None:
    """List all registered nodes."""
    reg = Registry()

    try:
        # Check if this is first time (for user feedback)
        first_time = not reg.registry_path.exists()

        if first_time and not output_json:
            click.echo("[Auto-discovering core nodes...]")

        nodes = reg.load()  # Auto-discovers if needed

        if output_json:
            _output_json_nodes(nodes)
        else:
            if not nodes:
                click.echo("No nodes registered.")
                return

            # Filter out the virtual mcp node before grouping
            filtered_nodes = {
                name: metadata for name, metadata in nodes.items() if name != "mcp"
            }  # Exclude the virtual MCP base node

            # Group nodes by package
            grouped = _group_nodes_by_package(filtered_nodes)

            # Count totals for summary
            total_core = sum(len(nodes) for nodes in grouped["core"].values())
            total_user = sum(len(nodes) for nodes in grouped["user"].values())
            total_mcp = sum(len(nodes) for nodes in grouped["mcp"].values())

            # Display Core Packages
            if grouped["core"]:
                click.echo("\nCore Packages:")
                click.echo("─" * 13)
                _display_package_section(grouped["core"], "core")

            # Display MCP Servers
            if grouped["mcp"]:
                click.echo("\nMCP Servers:")
                click.echo("─" * 12)
                _display_package_section(grouped["mcp"], "mcp")

            # Display User Nodes
            if grouped["user"]:
                click.echo("\nUser Nodes:")
                click.echo("─" * 10)
                _display_user_nodes(grouped["user"])

            # Display total summary
            total = total_core + total_user + total_mcp
            click.echo(f"\nTotal: {total} nodes ({total_core} core, {total_user} user, {total_mcp} mcp)")

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


def _display_interface_section(items: list, section_name: str) -> None:
    """Display a section of interface items (inputs/outputs/params)."""
    if items:
        click.echo(f"  {section_name}:")
        for item in items:
            key = item.get("key") or item.get("name", "?")
            desc = f" - {item.get('description', '')}" if item.get("description") else ""
            click.echo(f"    - {key}: {item.get('type', 'any')}{desc}")


def _display_node_suggestions(similar: list) -> None:
    """Display node name suggestions."""
    if similar:
        click.echo("\nDid you mean:")
        for n in similar:
            # Show cleaned names for MCP nodes
            if n.startswith("mcp-"):
                parts = n.split("-", 2)
                if len(parts) >= 3:
                    clean_name = parts[2].replace(f"{parts[1]}_", "").replace("_", "-")
                    click.echo(f"  - {n} (or try: {parts[1]}-{clean_name})")
                else:
                    click.echo(f"  - {n}")
            else:
                click.echo(f"  - {n}")


def _resolve_node_name(node: str, nodes: dict) -> str:
    """Try to resolve a node name to its registry key.

    Handles common variations like:
    - slack-add-reaction -> mcp-slack-slack_add_reaction
    - add-reaction -> mcp-slack-slack_add_reaction (if unique)
    - filesystem-read-file -> mcp-filesystem-read_file
    """
    # Try exact match first
    if node in nodes:
        return node

    # Try with underscores instead of hyphens
    underscore_name = node.replace("-", "_")
    if underscore_name in nodes:
        return underscore_name

    # For MCP-style names, try various patterns
    if "-" in node:
        parts = node.split("-", 1)
        if len(parts) == 2:
            server, tool = parts
            tool_underscore = tool.replace("-", "_")

            # Try mcp-{server}-{tool} patterns
            variations = [
                f"mcp-{server}-{tool}",
                f"mcp-{server}-{tool_underscore}",
                f"mcp-{server}-{server}_{tool}",
                f"mcp-{server}-{server}_{tool_underscore}",
            ]

            for variant in variations:
                if variant in nodes:
                    return variant

    # Try just the tool name if it's unique
    tool_matches = []
    for key in nodes:
        if key.startswith("mcp-") and (node in key or underscore_name in key):
            tool_matches.append(key)

    if len(tool_matches) == 1:
        return str(tool_matches[0])

    # No match found
    return node


@registry.command(name="describe")
@click.argument("node")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def describe(node: str, output_json: bool) -> None:
    """Show detailed information about a specific node."""
    reg = Registry()

    try:
        nodes = reg.load()

        # Try to resolve the node name
        resolved_node = _resolve_node_name(node, nodes)

        if resolved_node not in nodes:
            click.echo(f"Error: Node '{node}' not found", err=True)
            # Suggest similar
            similar = [n for n in nodes if node.lower() in n.lower()][:5]
            _display_node_suggestions(similar)
            sys.exit(1)

        # Use the resolved name
        node = resolved_node
        metadata = nodes[node]

        if output_json:
            _output_json_describe(node, metadata)
        else:
            # Human-readable output
            interface = metadata.get("interface", {})
            click.echo(f"Node: {node}")
            click.echo(f"Type: {_get_node_type(node, metadata)}")
            click.echo(f"Description: {interface.get('description', 'No description')}")

            # Show interface details
            click.echo("\nInterface:")
            _display_interface_section(interface.get("inputs", []), "Inputs")
            _display_interface_section(interface.get("outputs", []), "Outputs")
            _display_interface_section(interface.get("params", []), "Parameters")

            # Example usage
            click.echo("\nExample Usage:")
            params = interface.get("params", [])
            if params:
                param_str = " ".join([f"--{p.get('key', p.get('name', ''))} <value>" for p in params[:2]])
                click.echo(f"  pflow {node} {param_str}")
            else:
                click.echo(f"  pflow {node}")

    except Exception as e:
        click.echo(f"Error: Failed to describe node: {e}", err=True)
        sys.exit(1)


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
    valid_nodes, invalid_nodes = _categorize_nodes(user_nodes, output_json)

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


@registry.command(name="search")
@click.argument("query")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def search(query: str, output_json: bool) -> None:
    """Search for nodes by name or description."""
    reg = Registry()

    try:
        results = reg.search(query)

        if output_json:
            output = {
                "query": query,
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
            if not results:
                click.echo(f"No nodes found matching '{query}'")
                return

            click.echo(f"Found {len(results)} nodes matching '{query}':\n")

            # Table header
            click.echo("Name                 Type    Match   Description")
            click.echo("─" * 60)

            # Show top 10 results
            for name, data, score in results[:10]:
                node_type = _get_node_type(name, data)
                desc = data.get("interface", {}).get("description", "")[:35]
                if len(data.get("interface", {}).get("description", "")) > 35:
                    desc = desc[:32] + "..."

                # Match indicator
                if score == 100:
                    match = "exact"
                elif score == 90:
                    match = "prefix"
                elif score == 70:
                    match = "name"
                else:
                    match = "desc"

                click.echo(f"{name:20} {node_type:7} {match:7} {desc}")

            if len(results) > 10:
                click.echo(f"\n... and {len(results) - 10} more results")

    except Exception as e:
        click.echo(f"Error: Failed to search: {e}", err=True)
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
