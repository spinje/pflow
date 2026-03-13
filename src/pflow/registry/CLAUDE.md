# Registry — Node Discovery and Persistence

The registry is pflow's central catalog of available nodes. It stores metadata for all node types (core, user, MCP) and is used by the compiler for node resolution, type validation, and interface extraction.

## File Tree

```
registry/
├── __init__.py              # Re-exports: Registry, scan_for_nodes
├── registry.py              # Registry class — load/save/search/filter against ~/.pflow/registry.json
├── scanner.py               # Discover Node subclasses via importlib (executes code!)
└── metadata_extractor.py    # Parse Interface section from node docstrings into structured metadata
```

## How the Registry Works

### Storage

File: `~/.pflow/registry.json`. Auto-created on first use by scanning `src/pflow/nodes/` subdirectories.

### Node Types

| Type | Set by | Survives core refresh? |
|------|--------|----------------------|
| `"core"` | `_auto_discover_core_nodes()` | No — re-scanned on version change |
| `"user"` | `scan_user_nodes()` / CLI `pflow registry scan` | Yes |
| `"mcp"` | `MCPRegistrar` (from `mcp/registrar.py`) | Yes |

### Node Naming Convention

Class name → kebab-case with `Node` suffix stripped:
- `ReadFileNode` → `read-file` (auto-conversion)
- `LLMNode` → `llm` (explicit override, though auto would also produce `llm`)
- Can be overridden with explicit `name` class attribute on the class

Common override reasons:
- **Prefix additions**: GitHub nodes (`GetIssueNode` → `github-get-issue`) add category prefix
- **Fixing kebab split**: `GitHubCreatePRNode` would auto-convert to `git-hub-create-pr`, override fixes to `github-create-pr`
- **Intentional rename**: `PythonCodeNode` → `code`

### Interface Extraction

`PflowMetadataExtractor` parses `Interface:` sections from node docstrings. Two modes (auto-detected):
- **Simple format**: `- Params: file_path, encoding` → list of strings
- **Enhanced format**: `- Params: file_path: str  # Path to read` → list of dicts with key, type, description

Enhanced format supports nested structures for dict/list outputs. See `nodes/CLAUDE.md` for the full Interface format spec.

## Integration Points

| Consumer | Usage | `include_filtered` |
|----------|-------|-------------------|
| `runtime/compiler.py` | Node class resolution, interface metadata, MCP validation, output validation | Default (filtered) |
| `mcp/registrar.py` | Register/remove virtual MCP tool entries | **True** (safe) |
| `cli/main.py` auto-sync | Clean old MCP entries before re-syncing | **True** (safe) |
| `cli/registry.py` commands | List, search, describe, scan | Mixed — see known bugs |
| `core/workflow_validator.py` | Validate node types exist | Default (filtered) |
| `mcp_server/services/` | Registry service for MCP server | Default (filtered) |
| `planning/` | Context building for planner | Default (filtered) |

## Critical Details

### The `include_filtered` Footgun

`load()` applies settings-based filtering by default (`include_filtered=False`). `save()` does a **complete replacement** of the registry file.

**If you load filtered and save, you permanently lose all filtered-out entries.**

The safe pattern: always use `load(include_filtered=True)` before any `save()` call. The MCP registrar does this correctly.

**Known footgun**: `cli/registry.py:_add_nodes_to_registry()` loads with default filtering and saves back — will delete denied nodes when user runs `pflow registry scan`.

### Scanner Executes Code

`scan_for_nodes()` uses `importlib.import_module()` to discover `BaseNode` subclasses. This **executes Python code** in the scanned directories. Only use with trusted source directories.

### Version-Based Core Refresh

On pflow version change, `load()` detects the mismatch via the stored `version` field and re-scans core nodes. User and MCP nodes are preserved through the refresh.

## Known Bugs — Registry Format Inconsistency

Two save methods write **incompatible formats**:

| Method | Format | Called by |
|--------|--------|----------|
| `save(nodes)` | Flat: `{node1: ..., __metadata__: {...}}` | MCP registrar, CLI auto-sync cleanup |
| `_save_with_metadata(nodes)` | Structured: `{version: ..., nodes: {node1: ...}}` | Auto-discovery, CLI registry scan |

`_load_from_file()` detects format by checking for a `"nodes"` key. This causes:

1. **`get_metadata()` silently fails** on structured format — returns default because `data["nodes"]` has no `__metadata__` key. Result: MCP auto-sync cache never works, re-syncing every run (~500ms waste).

2. **`set_metadata()` writes orphaned data** — adds `__metadata__` at top level of structured file, but `_load_from_file()` only returns `data["nodes"]`, so the metadata is never readable.

3. **`save()` destroys structured format** — overwrites `{version: ..., nodes: ...}` with flat dict, permanently losing version tracking until next `_save_with_metadata()` call.

4. **`__metadata__` leaks as fake node** in flat format — appears as phantom "user" node under "custom" package in `pflow registry list`. No guards anywhere in the display chain (settings filter passes it through via wildcard `*` allow).

5. **Format flip-flops** between flat and structured depending on which code path writes last. Typical sequence: auto-discover (structured) → MCP sync calls `save()` (flat) → `set_metadata()` works (flat) → version upgrade triggers refresh (structured again, metadata lost).

**Self-healing quirk**: After first MCP sync converts to flat format, the sync cache works correctly on subsequent runs. It only breaks again on pflow version upgrades.

**Root cause**: Two save methods that should have been unified into one format. Fix would be to standardize on the structured format for all writes.
