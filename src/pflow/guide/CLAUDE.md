# Guide Package

Agent-facing content and composition for `pflow guide`.

## Directory map

```text
guide/
├── __init__.py  # Guide composition and topic detection
├── entry.md     # Entry and navigation content
├── core.md      # Framework fundamentals
├── nodes/       # Node-topic prose
└── features/    # Feature-topic prose
```

## Navigation and composition

| Concern | Owner |
|---|---|
| `--help` / no-topic guide entry | `render_entry_content`, `entry.md` |
| Topic/workflow argument composition | `compose_guide`, `_resolve_arg` |
| Public topic aliases and file lookup | `_TOPIC_ALIASES`, `_resolve_topic_path` |
| Available topics | `list_topics` scans `nodes/` and `features/` |
| Registry interface injection | `_TOPIC_TO_NODE_TYPES`, `_get_node_interface`, `_format_interface` |
| Single-IR topic detection | `_node_topics`, `detect_topics_from_ir` |
| Workflow-tree topic detection | `_topics_from_workflow_file`, `_collect_topics` |

`core.md` is an explicit topic, not automatically included. Mapped node topics combine
static guidance with registry-derived Parameters/Outputs appended at render time;
the MCP topic and feature chunks are static. `_TOPIC_TO_NODE_TYPES` owns mappings, including the
multi-node file topic. `_format_interface` filters extractor `default` artifacts
and internal output keys; preserve these guards.

Aliases canonicalize before lookup; menus and detected topics use public names.
False-valued prompt-cache controls still select the feature topic when non-None;
explicit None does not. Consult detection helpers rather than duplicating their
feature-to-field inventory.

## Adding a topic

1. Add static prose under `nodes/` or `features/`.
2. For node interface injection, update `_TOPIC_TO_NODE_TYPES`.
3. Reserve the topic in `core/workflow/save_service.py:RESERVED_WORKFLOW_NAMES`.
4. Update `entry.md` navigation.

Filesystem discovery alone does not update the mapping, reserved names, or menu.

## Workflow-scoped detection

`detect_topics_from_ir` examines one IR. File/saved-workflow arguments go through
`_topics_from_workflow_file` and `_collect_topics`, resolving descendant workflows.
Root parse errors raise GuideError; broken descendants and already-seen paths warn
and are skipped. Keep those different failure policies when changing traversal.

## Content principles

- Each node/feature chunk must work independently of other chunks.
- CLI help explains command mechanics; guide prose explains when/why.
- Append dynamic interfaces after guidance; keep parameter inventories in node
  docstrings/registry, not static guide prose.
