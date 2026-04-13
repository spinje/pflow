# Guide Package

Agent-facing guide content and composition logic for `pflow guide`.

## How It Works

`pflow --help` and `pflow guide` (no args) both render `entry.md` via `render_entry_content()`.

`pflow guide <topics...>` composes content from static markdown files + dynamic registry data via `compose_guide()`. Args can be topic names, workflow file paths, or saved workflow names (auto-detects topics from the workflow IR).

## Directory Layout

```
src/pflow/guide/
├── __init__.py          # render_entry_content, compose_guide, detect_topics_from_ir, list_topics
├── entry.md             # Capability map — rendered by pflow --help and pflow guide (no args)
├── core.md              # Framework fundamentals (explicit topic, not auto-included)
├── nodes/               # Per-node-type guides (static prose + dynamic interface from registry)
│   ├── http.md, llm.md, code.md, shell.md, file.md, mcp.md
└── features/            # Per-feature guides (static content only)
    ├── batch.md, branching.md, sub-workflows.md
```

## Topic Resolution

`_resolve_topic_path()` checks: `core.md` (top-level) → `nodes/<topic>.md` → `features/<topic>.md`. First match wins.

## Dynamic Interface Injection

Node topics (http, llm, code, shell, file) get Parameters + Outputs sections appended at render time, read from the registry. This keeps interface info in sync with actual node implementations.

The mapping is in `_TOPIC_TO_NODE_TYPES`. Topics not listed there (mcp, features, core) get static content only. The `file` topic maps to both `read-file` and `write-file` node types.

**Known issue**: The metadata extractor (`registry/metadata_extractor.py`) sometimes parses `(optional, default: value)` as a separate `key: "default"` param. The guide formatter filters these out with `if p.get("key") != "default"`.

## Adding a New Topic

1. Create `nodes/<type>.md` or `features/<name>.md` with static prose
2. If it's a node topic, add the mapping to `_TOPIC_TO_NODE_TYPES` in `__init__.py`
3. Add the topic name to `RESERVED_WORKFLOW_NAMES` in `core/workflow/save_service.py`
4. Update `entry.md` topic list (it's the navigation layer)

The topic is automatically discoverable — `list_topics()` scans the filesystem.

## Workflow-Scoped Auto-Detection

`detect_topics_from_ir()` walks the IR to find relevant topics:
- Node `type` → topic (via `_NODE_TYPE_TO_TOPIC` for non-1:1 mappings, `mcp-*` prefix → `mcp`)
- `node["batch"]` present → `batch`
- Edge with `action != "default"` → `branching`

## Content Principles

- `entry.md` is orientation/navigation only — no building advice
- `core.md` teaches framework fundamentals — loaded once explicitly
- Node/feature chunks are self-contained — each usable without reading other chunks
- `--help` teaches command mechanics; guide teaches when/why and provides the interface reference
- Dynamic interfaces come last (after static prose) — agents prefer guidance before reference
