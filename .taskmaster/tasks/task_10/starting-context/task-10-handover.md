# Task 10: Registry CLI Commands - Implementation Handoff

## 🔴 Critical Discoveries About Existing Code

### Registry Class Has Almost Nothing
The `Registry` class (`src/pflow/registry/registry.py`) currently has **only 4 methods** and **NO search functionality**. Don't look for a search method - it doesn't exist. You'll need to add:
- `search()` method with scoring logic
- Auto-discovery logic in `load()`
- Type differentiation (core/user/mcp)
- Version tracking

### Registry Uses Destructive Saves
**WARNING**: `Registry.save()` completely replaces the entire registry.json file. It doesn't merge or update - it's a full replacement. This means:
- Always load existing registry before making changes
- Never call save() with partial data
- Consider adding file locking if worried about concurrent access

### Scanner Returns List, Registry Wants Dict
The `Scanner.scan_for_nodes()` returns a **list** of node metadata, but Registry stores nodes as a **dict** with node names as keys. There's `Registry.update_from_scanner()` that does this conversion, but it has a quirk: if there are duplicate node names, the **last one wins** silently.

## 🎯 Key Design Decisions We Made

### Auto-Discovery, Not Manual Setup
After much discussion, we decided core nodes should auto-discover on first `pflow registry list` rather than requiring users to run a setup command. This means:
- Check if registry.json exists in `Registry.load()`
- If not, trigger auto-discovery of `src/pflow/nodes/` subdirectories
- Save with version metadata for future upgrade detection

### User Nodes Need Explicit Scanning
For security, user nodes in `~/.pflow/nodes/` require explicit `pflow registry scan` with:
- Security warning about arbitrary code execution
- Confirmation prompt (unless --force)
- Clear "user" type marking in registry

### Simple Search is Intentional
We chose basic substring matching over fuzzy search because:
- Zero dependencies
- Predictable behavior
- Good enough for <100 nodes in MVP
- Easy to replace later with vector search

Scoring: exact=100, prefix=90, name contains=70, description contains=50

## 🔥 Hidden Complexities

### MCP Nodes Are Virtual
MCP nodes (like `mcp-github-create-issue`) are **not real Python files**. They:
- All point to the same `MCPNode` class
- Use `"virtual://mcp"` as their file path
- Have special `mcp_metadata` in their interface
- Get server/tool names injected at runtime by the compiler

To detect MCP nodes: check if name starts with `"mcp-"` pattern.

### CLI Routing is Hacky but Works
The routing in `main_wrapper.py` is weird but intentional:
1. Pre-parses sys.argv to find first positional arg
2. If it's "registry" (or "mcp"), manipulates sys.argv to remove it
3. Calls the Click group directly
4. Restores sys.argv in finally block

This hack exists because Click's catch-all workflow arguments would consume "registry" as a workflow argument otherwise. Follow the exact pattern from MCP.

### MetadataExtractor Complexity
The `PflowMetadataExtractor` supports two docstring formats (simple and enhanced). It uses regex patterns and can parse nested structures. Don't try to simplify this - both formats are actively used in the codebase.

## 📁 Files and Patterns to Study

**Must understand these files:**
- `src/pflow/cli/mcp.py` - Copy this pattern exactly for registry.py
- `src/pflow/cli/main_wrapper.py` - See MCP routing pattern
- `src/pflow/registry/registry.py` - Understand current limitations
- `src/pflow/registry/scanner.py` - Returns list format
- `tests/test_cli/test_cli.py` - CLI test patterns

**Key patterns to follow:**
```python
# CLI routing pattern (main_wrapper.py)
if first_arg == "registry":
    original_argv = sys.argv[:]
    try:
        registry_index = sys.argv.index("registry")
        sys.argv = [sys.argv[0]] + sys.argv[registry_index + 1:]
        registry()  # Call the Click group
    finally:
        sys.argv = original_argv

# Type detection pattern
if name.startswith("mcp-"):
    node_type = "mcp"
elif "virtual://mcp" in metadata.get("file_path", ""):
    node_type = "mcp"
elif "/src/pflow/nodes/" in metadata.get("file_path", ""):
    node_type = "core"
else:
    node_type = "user"
```

## ⚠️ Things That Look Obvious But Aren't

1. **"Just add a refresh command"** - No! We decided against it. Refresh happens automatically when pflow version changes.

2. **"Registry should validate nodes"** - No! Scanner already does validation. Registry just stores.

3. **"Use Click subcommands normally"** - No! Must use the main_wrapper.py routing pattern.

4. **"Store version per node"** - No! MVP uses placeholder "1.0.0" for all. Real versioning is post-MVP.

5. **"Add node removal command"** - No! Not in scope for MVP.

## 🔒 Security Considerations

### User Nodes Execute Arbitrary Code
When implementing scan:
- **Always** show the security warning
- **Always** require confirmation (unless --force)
- Make the warning scary enough that users pay attention
- Remember: `importlib.import_module()` executes code at import time

Example warning:
```
⚠️  WARNING: Custom nodes execute with your user privileges.
   Only add nodes from trusted sources.
```

### Registry Corruption Recovery
Since Registry returns empty dict on any error, core nodes would be lost. Solution:
- Auto-discover core nodes if registry is empty/corrupt
- This provides automatic recovery
- Log the corruption but don't fail

## 🧹 Clean Up After Implementation

**DELETE** `scripts/populate_registry.py` - it's the temporary solution this task replaces.

Update any documentation that references populate_registry.py to use the new registry commands instead.

## 💡 Non-Obvious Integration Points

1. **Planning system** benefits from searchable registry but doesn't require changes
2. **Compiler** already handles registry lookups, just needs registry to auto-initialize
3. **Tests** should mock Registry to avoid file I/O - see existing test patterns
4. **MCP commands** already populate registry via MCPRegistrar - don't break this

## 🎭 What We Promised the User

The user was very clear about:
- Zero setup required - core nodes must auto-discover
- Security warnings for user nodes are non-negotiable
- Search must be simple for MVP (we'll add vector search later)
- Must update --help to mention registry commands
- Type differentiation (core/user/mcp) helps users understand trust levels

## 📊 Performance Expectations

- Auto-discovery should complete in <2 seconds (scanning ~12 core node files)
- Search should return in <100ms for 1000 nodes (O(n) is fine)
- Don't optimize prematurely - simple and working beats clever and broken

## 📝 Additional Critical Details Not in Specs

### Registry JSON Storage Quirk
The registry stores nodes **without** the "name" field in the value:
```json
{
  "read-file": {  // name is the KEY
    "module": "pflow.nodes.file.read_file",
    "class_name": "ReadFileNode",
    // NO "name" field here!
  }
}
```
The `update_from_scanner()` method removes the "name" field when converting from scanner's list format.

### Scanner Error Behavior
Two different behaviors for errors:
- **Import errors**: Logs warning and CONTINUES (skips the file)
- **Interface parsing errors**: FAILS FAST with actionable error message

This means if a node has malformed docstring, the entire scan fails. This is intentional to force fixing documentation.

### Exit Codes Clarification
- `describe` non-existent node: Exit 1
- `scan` with no valid nodes: Exit 0 (not an error)
- `scan` path doesn't exist: Exit 1
- All commands with `--json` errors: Exit 1 with error in stderr

### Main Help Text Location
The help text to update is in `src/pflow/cli/main.py`:
```python
@click.command(
    name="pflow",
    help="""pflow - Plan Once, Run Forever

    Natural language to deterministic workflows.

    Commands:
      registry    Manage node registry (list, search, add custom nodes)  # ADD THIS
      mcp         Manage MCP server connections
    ...
    """,
```

### Permissions Error Handling
If `~/.pflow/` isn't writable:
- Display clear error: "Error: Cannot write to ~/.pflow/registry.json - check permissions"
- Exit with code 1
- Don't try fallback locations

### Display Truncation Rules
- Descriptions: Truncate at 40 chars with "..."
- Node names: Never truncate (they're typically short)
- In JSON output: Never truncate anything

### Testing Infrastructure Note
CLI tests use a planner blocker from `tests/shared/planner_block.py`. Your registry tests should mock the Registry class similarly to avoid file I/O.

### Actual Core Node Count
Don't assume exactly 12 core nodes. The actual count depends on what's in `src/pflow/nodes/` subdirectories. Currently includes:
- file/ (read-file, write-file, etc.)
- git/ (git-commit, git-diff, etc.)
- github/ (github-get-issue, github-list-issues, etc.)
- llm/ (llm node)
- shell/ (shell node)
- mcp/ (virtual nodes, not scanned)

### Delete populate_registry.py Timing
Delete it AFTER verifying the new commands work. This prevents breaking existing users if something goes wrong.

## 🚨 Final Warnings

1. **Test with empty ~/.pflow/ directory** - First-time user experience must work
2. **Test with corrupted registry.json** - Must recover gracefully
3. **Don't forget --json flag** for all commands - Scripts depend on it
4. **Check exit codes** - Different commands have different error codes
5. **The spec is complete** - Don't add features not in the spec
6. **Registry stores nodes without "name" in value** - It's the dict key instead
7. **Scanner fails fast on bad docstrings** - This is intentional
8. **Don't truncate node names** - Only truncate descriptions

---

**TO THE IMPLEMENTING AGENT**: Please read through all the context documents (task-10.md, task-10-spec.md, TASK-10-SPECIFICATION.md) along with this handoff before starting implementation. Once you've absorbed all the context, confirm you're ready to begin implementing Task 10. Do NOT start coding until you've read everything and understand the full scope.