# Registry — Node Discovery and Persistence

Registry metadata resolves node classes and interfaces for compilation, validation,
and agent-facing discovery. Storage is `~/.pflow/registry.json`.

## Navigation

| Concern | Owner |
|---|---|
| Loading, filtering, persistence, refresh | `registry.py:Registry` |
| Discovering node classes | `scanner.py:scan_for_nodes` |
| Resolving user-typed node IDs | `node_id.py:normalize_node_id` |
| Parsing node Interface docstrings | `metadata_extractor.py:PflowMetadataExtractor`; authoring rules in `nodes/CLAUDE.md` |
| Rendering node specifications | `context_builder.py:build_component_context`, `build_nodes_context` |
| LLM component selection | `discovery.py:find_components` |
| Structure-field reduction | `smart_filter.py` |
| Virtual MCP entries and reconciliation | `mcp/registrar.py:MCPRegistrar` |

## Persistence hazards

`Registry.load()` filters according to settings by default. `save()` **replaces**
the complete node set: loading filtered and saving it permanently loses hidden
entries. Always load with `include_filtered=True` before replacement writes.
`save` preserves wrapper metadata; reconciliation can publish metadata_updates
alongside the node set.

Atomic replacement lets readers see an old or new complete file. The module lock
serializes in-process I/O only; it does not provide cross-process read-modify-write
transaction isolation.

`scan_for_nodes` imports discovered modules, executing their Python code. Scan
trusted source directories only.

## Node edits not appearing

`registry.py:_core_nodes_outdated` checks version and source freshness;
`_source_newer_than_scan` handles editable-install mtime changes.
`_refresh_core_nodes` preserves non-core metadata (including legacy untyped entries),
but fresh core metadata wins same-name collisions.

Two refresh constraints are easy to miss:

- `_scan_core_nodes` records time **before** reading sources; stamping after the
  scan can hide a concurrent edit from the next freshness check.
- Surviving-file mtimes do not detect deleted node sources; version refresh is
  the deletion recovery path.

For an interface mismatch after refresh, inspect `metadata_extractor.py` and the
node's machine-read docstring before changing downstream renderers or validators.
