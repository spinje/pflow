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
│   ├── http.md, llm.md, claude-code.md, code.md, shell.md, file.md, mcp.md
└── features/            # Per-feature guides (static content only)
    ├── batch.md, branching.md, error-handling.md, loop.md, patterns.md, prompt-caching.md, sub-workflows.md
```

## Topic Resolution

`_resolve_topic_path()` first canonicalizes the topic via `_TOPIC_ALIASES` (e.g. `caching` → `prompt-caching`), then checks: `core.md` (top-level) → `nodes/<topic>.md` → `features/<topic>.md`. First match wins. Aliases are kept out of auto-detection and the menu so generated pointers use the public topic name.

## Dynamic Interface Injection

Node topics (http, llm, claude-code, code, shell, file) get Parameters + Outputs sections appended at render time, read from the registry. This keeps interface info in sync with actual node implementations.

The mapping is in `_TOPIC_TO_NODE_TYPES`. Topics not listed there (mcp, features, core) get static content only. The `file` topic maps to all five file node types (`read-file`, `write-file`, `copy-file`, `move-file`, `delete-file`).

**Known issue**: The metadata extractor (`registry/metadata_extractor.py`) sometimes parses `(optional, default: value)` as a separate `key: "default"` param. The guide formatter filters these out with `if p.get("key") != "default"`.

## Adding a New Topic

1. Create `nodes/<type>.md` or `features/<name>.md` with static prose
2. If it's a node topic, add the mapping to `_TOPIC_TO_NODE_TYPES` in `__init__.py`
3. Add the topic name to `RESERVED_WORKFLOW_NAMES` in `core/workflow/save_service.py`
4. Update `entry.md` topic list (it's the navigation layer)

The topic is automatically discoverable — `list_topics()` scans the filesystem.

## Workflow-Scoped Auto-Detection

`detect_topics_from_ir()` walks a single IR to find relevant topics:
- Node `type` → topic (via `_NODE_TYPE_TO_TOPIC` for non-1:1 mappings, `mcp-*` prefix → `mcp`)
- `node["batch"]` present → `batch`; `node["loop"]` → `loop`; `node["retry"]` → `error-handling`
- `node["prompt_cache"]` or `node["prewarm"]` present (presence, not truthiness) → `prompt-caching`
- Top-level `ir["cache"]` (parsed `## Cache` block) → `prompt-caching`
- Edge with `action == "error"` → `error-handling`; any other non-`default` action → `branching`

`_topics_from_workflow_file()` walks the workflow TREE: parses the root,
runs `detect_topics_from_ir` on every reachable IR via `_collect_topics`
recursing through `workflow:` nodes (uses `resolve_sub_workflow`). Cycle
protection via resolved-path set; broken descendants and cycles emit a
single stderr warning each and are skipped (root parse errors still raise
`GuideError`). Saved-name CLI form (`pflow guide my-saved-workflow`) routes
through the same walker via `WorkflowManager.get_path()`.

## Content Principles

- `entry.md` is orientation/navigation only — no building advice
- `core.md` teaches framework fundamentals — loaded once explicitly
- Node/feature chunks are self-contained — each usable without reading other chunks
- `--help` teaches command mechanics; guide teaches when/why and provides the interface reference
- Dynamic interfaces come last (after static prose) — agents prefer guidance before reference
