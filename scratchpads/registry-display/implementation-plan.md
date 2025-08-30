# Implementation Plan: Grouped Registry Display

## Objective
Transform the flat registry list into a hierarchical, package-grouped display that's more readable and organized.

## Current vs. Desired Output

### Current (Flat Display)
```
Name                 Type    Description
────────────────────────────────────────
git-checkout         core    Create or switch to a git branch
git-commit           core    Create a git commit
mcp-slack-slack_add_reaction mcp     Add a reaction emoji to a message
```

### Desired (Grouped Display)
```
Core Packages:
─────────────
git (2 nodes)
  git-checkout         Create or switch to a git branch
  git-commit           Create a git commit

MCP Servers:
────────────
slack (1 tool)
  add_reaction         Add a reaction emoji to a message
```

## Design Decisions

### 1. Node Grouping Logic

#### Core Nodes
- **Pattern**: Extract prefix before first hyphen
- **Examples**:
  - `git-checkout` → Package: "git"
  - `github-list-issues` → Package: "github"
  - `read-file` → Package: "file" (special case: verb-noun pattern)
- **Special cases**:
  - Standalone nodes (llm, shell, mcp, echo) → Own single-node package
  - Verb-noun pattern (read-file, write-file) → Group by noun (file)

#### MCP Nodes
- **Pattern**: `mcp-{server}-{tool}`
- **Extract**: Server name as package
- **Display**: Tool name only (remove mcp-server- prefix)
- **Example**: `mcp-slack-slack_add_reaction` → Package: "slack", Display: "add_reaction"

#### User Nodes
- **Pattern**: Group by parent directory if structured, otherwise flat
- **Display**: Full name (user nodes may have custom naming)

### 2. Display Formatting

#### Layout Structure
```
[Section Header]
[Underline]
[package] ([count])
  [node-name]         [description]
  [node-name]         [description]

[package] ([count])
  [node-name]         [description]
```

#### Column Widths
- **Node name**: 20 chars (indented items)
- **Description**: 75 chars (increased from 40)
- **Total width**: ~100 chars (fits most terminals)

#### Indentation
- Package names: No indent
- Node items: 2 spaces
- Consistent alignment for readability

### 3. Implementation Components

#### Helper Functions

```python
def _extract_package_name(name: str, metadata: dict) -> str:
    """Extract package/group name from node name."""
    node_type = _get_node_type(name, metadata)

    if node_type == "mcp":
        # mcp-{server}-{tool} → server
        parts = name.split("-", 2)
        return parts[1] if len(parts) > 1 else "unknown"

    elif node_type == "core":
        # Special handling for verb-noun patterns
        if name in ["read-file", "write-file", "copy-file", "move-file", "delete-file"]:
            return "file"

        # Standalone nodes
        if name in ["llm", "shell", "mcp", "echo"]:
            return name

        # Extract prefix (git-, github-, etc.)
        if "-" in name:
            return name.split("-")[0]

        return name

    else:  # user nodes
        # Could extract from file_path if needed
        return "user"

def _format_node_name(name: str, metadata: dict, package: str) -> str:
    """Format node name for display (remove redundant prefixes)."""
    node_type = _get_node_type(name, metadata)

    if node_type == "mcp":
        # Remove mcp-{server}- prefix
        prefix = f"mcp-{package}-"
        if name.startswith(prefix):
            # Also clean up tool name (slack_ prefix, underscores)
            tool_name = name[len(prefix):]
            if tool_name.startswith(f"{package}_"):
                tool_name = tool_name[len(package)+1:]
            return tool_name.replace("_", "-")
        return name

    elif node_type == "core":
        # For file operations, keep full name
        if package == "file":
            return name
        # For standalone packages, just show the name
        if package == name:
            return name
        # For others, remove package prefix if present
        prefix = f"{package}-"
        if name.startswith(prefix):
            return name[len(prefix):]
        return name

    return name  # user nodes show full name

def _group_nodes_by_package(nodes: dict) -> dict:
    """Group nodes by their package/server."""
    grouped = {
        "core": {},
        "mcp": {},
        "user": {}
    }

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
```

### 4. Main Display Logic

Update the `list_nodes` command in `src/pflow/cli/registry.py`:

```python
def _display_grouped_nodes(grouped: dict) -> None:
    """Display nodes in grouped format."""

    # Core packages
    if grouped.get("core"):
        click.echo("\nCore Packages:")
        click.echo("─" * 13)

        for package, nodes in grouped["core"].items():
            count = len(nodes)
            unit = "node" if count == 1 else "nodes"
            click.echo(f"\n{package} ({count} {unit})")

            for name, metadata in nodes:
                display_name = _format_node_name(name, metadata, package)
                desc = metadata.get("interface", {}).get("description", "")[:75]
                if len(metadata.get("interface", {}).get("description", "")) > 75:
                    desc = desc[:72] + "..."
                click.echo(f"  {display_name:20} {desc}")

    # MCP servers
    if grouped.get("mcp"):
        click.echo("\nMCP Servers:")
        click.echo("─" * 12)

        for server, tools in grouped["mcp"].items():
            count = len(tools)
            unit = "tool" if count == 1 else "tools"
            click.echo(f"\n{server} ({count} {unit})")

            for name, metadata in tools:
                display_name = _format_node_name(name, metadata, server)
                desc = metadata.get("interface", {}).get("description", "")[:75]
                if len(metadata.get("interface", {}).get("description", "")) > 75:
                    desc = desc[:72] + "..."
                click.echo(f"  {display_name:20} {desc}")

    # User nodes
    if grouped.get("user"):
        click.echo("\nUser Nodes:")
        click.echo("─" * 10)

        for package, nodes in grouped["user"].items():
            for name, metadata in nodes:
                desc = metadata.get("interface", {}).get("description", "")[:75]
                if len(metadata.get("interface", {}).get("description", "")) > 75:
                    desc = desc[:72] + "..."
                click.echo(f"  {name:20} {desc}")
```

### 5. Testing Strategy

1. **Unit tests for helper functions**:
   - Test package extraction for various node names
   - Test name formatting (prefix removal)
   - Test grouping logic

2. **Integration tests**:
   - Test with real registry data
   - Verify output format
   - Check JSON output unchanged

3. **Edge cases**:
   - Empty registry
   - Single node packages
   - Very long descriptions
   - Special characters in names

### 6. Implementation Order

1. First, create helper functions in registry.py
2. Update list_nodes command to use grouped display
3. Test with real data
4. Update unit tests
5. Document the change

## Success Criteria

- [x] Nodes grouped by package/server
- [x] Redundant prefixes removed
- [x] Descriptions use 75 char width
- [x] Clear visual hierarchy
- [x] Package counts displayed
- [x] JSON output unchanged
- [x] All tests pass