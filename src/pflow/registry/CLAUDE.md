# Registry — Node Discovery and Persistence

The registry is pflow's central catalog of available nodes. It stores metadata for all node types (core, user, MCP) and is used by the compiler for node resolution, type validation, and interface extraction.

## File Tree

```
registry/
├── __init__.py              # Re-exports: Registry, scan_for_nodes
├── registry.py              # Registry class — load/save/search/filter against ~/.pflow/registry.json
├── scanner.py               # Discover Node subclasses via importlib (executes code!)
├── metadata_extractor.py    # Parse Interface section from node docstrings into structured metadata
├── context_builder.py       # Build LLM-optimized node/component context (build_component_context, build_nodes_context)
├── smart_filter.py          # LLM-powered field reduction for structure-only mode
├── discovery.py             # LLM-powered component discovery (find_components)
└── prompts/
    └── component_browsing.md  # Component browsing prompt template
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
- **Fixing kebab split**: Override when auto-conversion produces wrong results
- **Intentional rename**: `PythonCodeNode` → `code`

### Interface Extraction

`PflowMetadataExtractor` parses `Interface:` sections from node docstrings. Two modes (auto-detected):
- **Simple format**: `- Params: file_path, encoding` → list of strings
- **Enhanced format**: `- Params: file_path: str  # Path to read` → list of dicts with key, type, description

Enhanced format supports nested structures for dict/list outputs. See `nodes/CLAUDE.md` for the full Interface format spec.

## Integration Points

| Consumer | Usage | `include_filtered` |
|----------|-------|-------------------|
| `runtime/compilation/` | Node class resolution, interface metadata, MCP validation, output validation | Default (filtered) |
| `mcp/registrar.py` | Register/remove virtual MCP tool entries | **True** (safe) |
| `cli/main.py` auto-sync | Clean old MCP entries before re-syncing | **True** (safe) |
| `cli/commands/mcp.py`, `_probe_impl.py` | MCP list/find/describe, probe | Default (filtered) |
| `core/workflow/validator.py` | Validate node types exist | Default (filtered) |
| `mcp_server/services/` | Registry service for MCP server | Default (filtered) |
| `registry/context_builder.py` | Node specs for discovery and planning | Default (filtered) |

## Critical Details

### The `include_filtered` Footgun

`load()` applies settings-based filtering by default (`include_filtered=False`). `save()` does a **complete replacement** of the registry file.

**If you load filtered and save, you permanently lose all filtered-out entries.**

The safe pattern: always use `load(include_filtered=True)` before any `save()` call. The MCP registrar does this correctly.

**Historical footgun** (removed): The old `cli/commands/registry.py:_add_nodes_to_registry()` loaded with default filtering and saved back — deleting denied nodes on `pflow registry scan`. Both the file and the `registry scan` command were removed in Task 151.

### Scanner Executes Code

`scan_for_nodes()` uses `importlib.import_module()` to discover `BaseNode` subclasses. This **executes Python code** in the scanned directories. Only use with trusted source directories.

### Core Refresh Triggers

`load()` re-scans core nodes when either:

1. **Version mismatch** — stored `version` differs from current pflow version.
2. **Source mtime newer than `last_core_scan`** — catches docstring changes in editable / from-source installs where the version string hasn't moved. The walk under `Path(pflow.nodes.__file__).parent` costs ~0.3ms on warm cache and fires zero times on non-editable installs (install mtimes never move).

User and MCP nodes are preserved through the refresh via `_refresh_core_nodes()`. Legacy registries without a `last_core_scan` field are treated as stale and self-heal on the next load. Timestamps are written in UTC; naive legacy timestamps are interpreted as local time for backward compatibility.

### Registry File Format

All writes use a unified structured format:
```json
{
  "version": "0.10.0",
  "last_core_scan": "2026-03-22T...",
  "metadata": {"mcp_config_hash": "..."},
  "nodes": {"shell": {...}, "llm": {...}}
}
```

- `save()` preserves existing version/timestamp/metadata, only replaces nodes
- `_save_with_metadata()` updates version and timestamp (used after core node discovery)
- `get_metadata()`/`set_metadata()` read/write the `metadata` field directly
- `_load_from_file()` still handles legacy flat format (`{node1: ..., node2: ...}`) for backward compatibility, stripping any `__metadata__` keys
