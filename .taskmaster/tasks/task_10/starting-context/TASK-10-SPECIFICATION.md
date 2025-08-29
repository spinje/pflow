# Task 10: Registry CLI Implementation Specification

## Executive Summary

Implement CLI commands for registry operations (`pflow registry list|describe|search|scan`) to replace the temporary `scripts/populate_registry.py` script. Core nodes auto-discover on first use, while user nodes require explicit scanning with security warnings.

## Verified Architecture Components

### Registry Class (`src/pflow/registry/registry.py`)
**Current capabilities:**
- `load()` - Returns dict of all nodes (empty dict if file missing)
- `save(nodes)` - Complete replacement save (destructive)
- `update_from_scanner(scan_results)` - Converts scanner format to registry format
- `get_nodes_metadata(node_types)` - Get specific nodes by exact name

**Missing capabilities we need to add:**
- Auto-discovery of core nodes on first load
- Search functionality
- Differentiation between core/user/mcp nodes
- Version tracking for upgrade detection

### Scanner (`src/pflow/registry/scanner.py`)
**Function signature:** `scan_for_nodes(directories: list[Path]) -> list[dict[str, Any]]`
**Returns:** List of dicts with keys: module, class_name, name, docstring, file_path, interface
**Handles:** Recursive scanning, import errors, invalid nodes (with warnings)

### MetadataExtractor (`src/pflow/registry/metadata_extractor.py`)
**Extracts:** description, inputs, outputs, params, actions from docstrings
**Supports:** Both simple and enhanced Interface formats

### MCP Integration (`src/pflow/mcp/registrar.py`)
**Naming:** `mcp-{server}-{tool}` pattern
**Storage:** Uses virtual path `"virtual://mcp"`, always MCPNode class

### CLI Routing (`src/pflow/cli/main_wrapper.py`)
**Pattern:** Pre-parse sys.argv, detect first positional arg, manipulate argv, route to group

## Implementation Plan

### 1. Enhance Registry Class

```python
# src/pflow/registry/registry.py

class Registry:
    def __init__(self, registry_path: Optional[Path] = None):
        self.registry_path = registry_path or (Path.home() / ".pflow" / "registry.json")
        self._cached_nodes = None  # Add caching

    def load(self) -> dict[str, dict[str, Any]]:
        """Load registry, auto-discovering core nodes if needed."""
        # Check if registry exists
        if not self.registry_path.exists():
            # First time - auto-discover core nodes
            self._auto_discover_core_nodes()

        # Load registry
        nodes = self._load_from_file()

        # Check if core nodes need refresh (version change)
        if self._core_nodes_outdated(nodes):
            nodes = self._refresh_core_nodes(nodes)

        self._cached_nodes = nodes
        return nodes

    def _auto_discover_core_nodes(self) -> None:
        """Auto-discover and save core nodes on first use."""
        from pflow.registry.scanner import scan_for_nodes
        import pflow.nodes
        from pathlib import Path

        # Find core nodes directory
        nodes_path = Path(pflow.nodes.__file__).parent

        # Scan all subdirectories
        subdirs = [d for d in nodes_path.iterdir()
                   if d.is_dir() and not d.name.startswith("__")]

        # Scan and save
        scan_results = scan_for_nodes(subdirs)

        # Convert to registry format with type marking
        registry_nodes = {}
        for node in scan_results:
            name = node["name"]
            node_copy = dict(node)
            node_copy["type"] = "core"  # Mark as core node
            del node_copy["name"]  # Registry doesn't store name in value
            registry_nodes[name] = node_copy

        # Save with metadata
        self._save_with_metadata(registry_nodes)

    def _save_with_metadata(self, nodes: dict) -> None:
        """Save nodes with metadata like version and timestamps."""
        import json
        from datetime import datetime
        import pflow

        data = {
            "version": getattr(pflow, "__version__", "0.0.1"),
            "last_core_scan": datetime.now().isoformat(),
            "nodes": nodes
        }

        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.registry_path, "w") as f:
            json.dump(data, f, indent=2)

    def search(self, query: str) -> list[tuple[str, dict, int]]:
        """Simple substring search with scoring.

        Returns list of (name, metadata, score) tuples.
        """
        query_lower = query.lower()
        results = []
        nodes = self.load()

        for name, metadata in nodes.items():
            name_lower = name.lower()
            desc_lower = metadata.get("description", "").lower()

            # Simple scoring
            score = 0
            if name_lower == query_lower:
                score = 100
            elif name_lower.startswith(query_lower):
                score = 90
            elif query_lower in name_lower:
                score = 70
            elif query_lower in desc_lower:
                score = 50

            if score > 0:
                results.append((name, metadata, score))

        # Sort by score desc, then name
        results.sort(key=lambda x: (-x[2], x[0]))
        return results

    def scan_user_nodes(self, path: Path) -> list[dict]:
        """Scan for user nodes with validation."""
        from pflow.registry.scanner import scan_for_nodes

        if not path.exists():
            return []

        # Scan the path
        scan_results = scan_for_nodes([path])

        # Mark as user nodes
        for node in scan_results:
            node["type"] = "user"

        return scan_results
```

### 2. Create Registry CLI Command Group

```python
# src/pflow/cli/registry.py

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


@registry.command(name="list")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def list_nodes(output_json: bool) -> None:
    """List all registered nodes."""
    reg = Registry()

    try:
        nodes = reg.load()  # Auto-discovers if needed

        if output_json:
            # JSON output
            output = {
                "nodes": [
                    {
                        "name": name,
                        "type": data.get("type", "core"),
                        "description": data.get("interface", {}).get("description", "")
                    }
                    for name, data in nodes.items()
                ]
            }
            click.echo(json.dumps(output, indent=2))
        else:
            # Check if first time
            if not reg.registry_path.exists():
                click.echo("[Auto-discovering core nodes...]")

            if not nodes:
                click.echo("No nodes registered.")
                return

            # Group by type
            core_nodes = [(n, d) for n, d in nodes.items() if d.get("type") == "core"]
            user_nodes = [(n, d) for n, d in nodes.items() if d.get("type") == "user"]
            mcp_nodes = [(n, d) for n, d in nodes.items() if n.startswith("mcp-")]

            # Display table
            click.echo("\nName                 Type    Description")
            click.echo("─" * 60)

            # Core nodes first
            for name, data in sorted(core_nodes):
                desc = data.get("interface", {}).get("description", "")[:40]
                click.echo(f"{name:20} {'core':7} {desc}")

            # User nodes
            for name, data in sorted(user_nodes):
                desc = data.get("interface", {}).get("description", "")[:40]
                click.echo(f"{name:20} {'user':7} {desc}")

            # MCP nodes
            for name, data in sorted(mcp_nodes):
                desc = data.get("interface", {}).get("description", "")[:40]
                click.echo(f"{name:20} {'mcp':7} {desc}")

            total = len(nodes)
            click.echo(f"\nTotal: {total} nodes "
                      f"({len(core_nodes)} core, {len(user_nodes)} user, {len(mcp_nodes)} mcp)")

    except Exception as e:
        click.echo(f"Error: Failed to list nodes: {e}", err=True)
        sys.exit(1)


@registry.command(name="describe")
@click.argument("node")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def describe(node: str, output_json: bool) -> None:
    """Show detailed information about a specific node."""
    reg = Registry()

    try:
        nodes = reg.load()

        if node not in nodes:
            click.echo(f"Error: Node '{node}' not found", err=True)

            # Suggest similar
            similar = [n for n in nodes if node.lower() in n.lower()][:5]
            if similar:
                click.echo("\nDid you mean:")
                for n in similar:
                    click.echo(f"  - {n}")

            sys.exit(1)

        metadata = nodes[node]
        interface = metadata.get("interface", {})

        if output_json:
            output = {
                "name": node,
                "type": metadata.get("type", "core"),
                "module": metadata.get("module", ""),
                "class_name": metadata.get("class_name", ""),
                "description": interface.get("description", ""),
                "interface": interface
            }
            click.echo(json.dumps(output, indent=2))
        else:
            # Human-readable output
            click.echo(f"Node: {node}")
            click.echo(f"Type: {metadata.get('type', 'core')}")
            click.echo(f"Description: {interface.get('description', 'No description')}")

            # Show interface details
            click.echo("\nInterface:")

            # Inputs
            inputs = interface.get("inputs", [])
            if inputs:
                click.echo("  Inputs:")
                for inp in inputs:
                    desc = f" - {inp.get('description', '')}" if inp.get('description') else ""
                    click.echo(f"    - {inp.get('key', inp.get('name', '?'))}: "
                             f"{inp.get('type', 'any')}{desc}")

            # Outputs
            outputs = interface.get("outputs", [])
            if outputs:
                click.echo("  Outputs:")
                for out in outputs:
                    desc = f" - {out.get('description', '')}" if out.get('description') else ""
                    click.echo(f"    - {out.get('key', out.get('name', '?'))}: "
                             f"{out.get('type', 'any')}{desc}")

            # Parameters
            params = interface.get("params", [])
            if params:
                click.echo("  Parameters:")
                for param in params:
                    desc = f" - {param.get('description', '')}" if param.get('description') else ""
                    click.echo(f"    - {param.get('key', param.get('name', '?'))}: "
                             f"{param.get('type', 'any')}{desc}")

            # Example usage
            click.echo("\nExample Usage:")
            if params:
                param_str = " ".join([f"--{p.get('key', p.get('name', ''))} <value>"
                                     for p in params[:2]])
                click.echo(f"  pflow {node} {param_str}")
            else:
                click.echo(f"  pflow {node}")

    except Exception as e:
        click.echo(f"Error: Failed to describe node: {e}", err=True)
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
                        "type": data.get("type", "core"),
                        "score": score,
                        "description": data.get("interface", {}).get("description", "")
                    }
                    for name, data, score in results
                ]
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
                node_type = data.get("type", "core")
                desc = data.get("interface", {}).get("description", "")[:35]

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
def scan(path: Optional[str], force: bool) -> None:
    """Scan for custom user nodes.

    Default path: ~/.pflow/nodes/

    Examples:
        pflow registry scan                  # Scan default location
        pflow registry scan ./my-nodes/      # Scan custom directory
    """
    reg = Registry()

    # Determine scan path
    scan_path = Path(path) if path else (Path.home() / ".pflow" / "nodes")

    # Security warning
    click.echo("⚠️  WARNING: Custom nodes execute with your user privileges.")
    click.echo("   Only add nodes from trusted sources.\n")

    if not scan_path.exists():
        click.echo(f"Path does not exist: {scan_path}")
        if not path:  # Default path
            click.echo("\nTo add custom nodes:")
            click.echo(f"  1. Create directory: mkdir -p {scan_path}")
            click.echo(f"  2. Add node files: cp my_node.py {scan_path}/")
            click.echo(f"  3. Run scan again: pflow registry scan")
        sys.exit(1)

    try:
        click.echo(f"Scanning {scan_path} for custom nodes...\n")

        # Scan for nodes
        user_nodes = reg.scan_user_nodes(scan_path)

        if not user_nodes:
            click.echo("No valid nodes found.")
            return

        # Show discovered nodes
        valid_nodes = []
        for node in user_nodes:
            interface = node.get("interface", {})
            desc = interface.get("description", "No description")

            # Check if node is valid (has required methods)
            if node.get("class_name"):
                click.echo(f"  ✓ {node['name']}: {desc}")
                valid_nodes.append(node)
            else:
                click.echo(f"  ⚠ {node['name']}: Invalid - missing required methods")

        if not valid_nodes:
            click.echo("\nNo valid nodes to add.")
            return

        # Confirm addition
        if not force:
            if not click.confirm(f"\nAdd {len(valid_nodes)} nodes to registry?"):
                click.echo("Cancelled.")
                return

        # Add to registry
        current_nodes = reg.load()

        # Add user nodes
        for node in valid_nodes:
            name = node["name"]
            node_copy = dict(node)
            node_copy["type"] = "user"
            del node_copy["name"]
            current_nodes[name] = node_copy

        # Save updated registry
        reg._save_with_metadata(current_nodes)

        click.echo(f"✓ Added {len(valid_nodes)} custom nodes to registry")

    except Exception as e:
        click.echo(f"Error: Failed to scan: {e}", err=True)
        sys.exit(1)
```

### 3. Update CLI Routing

```python
# src/pflow/cli/main_wrapper.py

def cli_main() -> None:
    """Main entry point that routes between workflow execution and subcommands."""
    from .main import workflow_command
    from .mcp import mcp
    from .registry import registry  # Add import

    # Pre-parse to find first non-option argument
    first_arg = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            first_arg = arg
            break

    if first_arg == "mcp":
        # Route to MCP group
        original_argv = sys.argv[:]
        try:
            mcp_index = sys.argv.index("mcp")
            sys.argv = [sys.argv[0]] + sys.argv[mcp_index + 1 :]
            mcp()
        finally:
            sys.argv = original_argv

    elif first_arg == "registry":  # Add registry routing
        # Route to Registry group
        original_argv = sys.argv[:]
        try:
            registry_index = sys.argv.index("registry")
            sys.argv = [sys.argv[0]] + sys.argv[registry_index + 1 :]
            registry()
        finally:
            sys.argv = original_argv

    else:
        # Run the workflow command (default behavior)
        workflow_command()
```

### 4. Update Main Help Text

```python
# src/pflow/cli/main.py - Update the main command help

@click.command(
    name="pflow",
    help="""pflow - Plan Once, Run Forever

Natural language to deterministic workflows.

Commands:
  registry    Manage node registry (list, search, add custom nodes)
  mcp         Manage MCP server connections

Examples:
  pflow "summarize latest github issues"      # Natural language workflow
  pflow read-file => llm => write-file        # CLI pipe syntax
  pflow registry list                         # See available nodes
  pflow registry search github                # Find GitHub nodes
  pflow mcp list                             # List MCP servers

Run 'pflow COMMAND --help' for more information on a command.""",
    context_settings={"help_option_names": ["-h", "--help"]},
)
```

## Testing Strategy

```python
# tests/test_cli/test_registry_cli.py

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from pflow.cli.registry import registry


class TestRegistryCLI:
    """Test registry CLI commands."""

    def test_list_auto_discovers_core_nodes(self, tmp_path):
        """First use auto-discovers core nodes."""
        with patch("pflow.registry.Registry.registry_path", tmp_path / "registry.json"):
            runner = CliRunner()
            result = runner.invoke(registry, ["list"])

            assert result.exit_code == 0
            assert "[Auto-discovering core nodes...]" in result.output
            assert "read-file" in result.output
            assert "core" in result.output

    def test_list_json_output(self, mock_registry):
        """List supports JSON output."""
        runner = CliRunner()
        result = runner.invoke(registry, ["list", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "nodes" in data
        assert any(n["name"] == "read-file" for n in data["nodes"])

    def test_describe_shows_interface(self, mock_registry):
        """Describe shows full interface details."""
        runner = CliRunner()
        result = runner.invoke(registry, ["describe", "read-file"])

        assert result.exit_code == 0
        assert "Interface:" in result.output
        assert "Inputs:" in result.output
        assert "file_path" in result.output

    def test_describe_node_not_found(self, mock_registry):
        """Describe shows error for missing node."""
        runner = CliRunner()
        result = runner.invoke(registry, ["describe", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_search_finds_matches(self, mock_registry):
        """Search finds matching nodes."""
        runner = CliRunner()
        result = runner.invoke(registry, ["search", "file"])

        assert result.exit_code == 0
        assert "read-file" in result.output
        assert "write-file" in result.output

    def test_search_ranking(self, mock_registry):
        """Search ranks exact matches higher."""
        runner = CliRunner()
        result = runner.invoke(registry, ["search", "read-file"])

        assert result.exit_code == 0
        assert "exact" in result.output

    def test_scan_shows_warning(self, tmp_path):
        """Scan shows security warning."""
        runner = CliRunner()
        result = runner.invoke(registry, ["scan", str(tmp_path)])

        assert "WARNING: Custom nodes execute with your user privileges" in result.output

    def test_scan_requires_confirmation(self, tmp_path, sample_node_file):
        """Scan requires user confirmation."""
        # Create a valid node file
        node_file = tmp_path / "my_node.py"
        node_file.write_text(sample_node_file)

        runner = CliRunner()
        result = runner.invoke(registry, ["scan", str(tmp_path)], input="n\n")

        assert "Cancelled" in result.output

    def test_scan_force_flag(self, tmp_path, sample_node_file):
        """Scan --force skips confirmation."""
        node_file = tmp_path / "my_node.py"
        node_file.write_text(sample_node_file)

        runner = CliRunner()
        result = runner.invoke(registry, ["scan", str(tmp_path), "--force"])

        assert "Added" in result.output
        assert "Cancelled" not in result.output
```

## Migration Notes

1. **Delete** `scripts/populate_registry.py` after implementation
2. **Auto-migration**: Old registry format detected and converted automatically
3. **Backward compatibility**: Existing registry.json files continue to work

## Success Criteria

- [x] Core nodes auto-discover on first use (no setup required)
- [x] User can list all nodes with type differentiation
- [x] User can search nodes with simple substring matching
- [x] User can see detailed node information
- [x] User can add custom nodes with explicit warning and confirmation
- [x] JSON output available for all commands
- [x] Help text updated to mention registry commands
- [x] All commands have comprehensive tests
- [x] populate_registry.py script deleted

## Key Design Decisions

1. **Auto-discovery**: Core nodes discovered automatically, no manual scan needed
2. **Security model**: User nodes require explicit scan with warning
3. **Search simplicity**: Basic substring matching for MVP, vector search later
4. **Type differentiation**: Clear labeling of core/user/mcp nodes
5. **JSON support**: All commands support `--json` for scripting
6. **No versioning in MVP**: Show "1.0.0" placeholder, real versioning post-MVP