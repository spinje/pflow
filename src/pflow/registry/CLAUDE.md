# Registry — Node Discovery and Persistence

The registry is pflow's central catalog of available nodes. It stores metadata for all node types (core, user, MCP) and is used by the compiler for node resolution, type validation, and interface extraction.

## File Tree

```
registry/
├── __init__.py              # Re-exports: Registry, normalize_node_id, scan_for_nodes
├── registry.py              # Registry class — load/save/search/filter against ~/.pflow/registry.json
├── scanner.py               # Discover Node subclasses via importlib (executes code!)
├── node_id.py               # normalize_node_id() — resolve user-typed node IDs to registry keys (exact/hyphen/suffix tiers)
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
| `"core"` | `_scan_core_nodes()` | No — re-scanned on version change |
| `"user"` | `scan_user_nodes()` (Python API only — `pflow registry scan` CLI was removed in Task 151) | Yes |
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
| `cli/mcp_sync.py` auto-sync (via `cli/commands/run.py`) | Clean old MCP entries before re-syncing | **True** (safe) |
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

User and MCP nodes are preserved through the refresh via `_refresh_core_nodes()`. Structured-wrapper registries missing either `version` or `last_core_scan` still hit the mtime path (the `not version and not last_scan` gate short-circuits only when BOTH are absent — legacy flat-format registries, which still heal via a version bump). Timestamps are written in UTC; naive legacy timestamps are interpreted as local time for backward compatibility.

**Race-safety**: `_scan_core_nodes()` captures the scan-start timestamp BEFORE `scan_for_nodes()` reads sources and does not persist anything itself. First-use initialization saves the discovered core nodes once; `_refresh_core_nodes()` merges preserved non-core nodes in memory and saves one complete snapshot. Stamping `last_core_scan` with a POST-scan time would lose any concurrent edit made during the scan window (mtime < stored timestamp on the next load → no refresh).

**Limits**:
- **Deletions aren't detected.** Removing a `src/pflow/nodes/**/*.py` file doesn't bump the mtime of surviving files, so the mtime path keeps serving the dead entry. Heals via version bump. Stat'ing the nodes dir itself would catch the immediate parent but is accepted complexity for a rare case.

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
