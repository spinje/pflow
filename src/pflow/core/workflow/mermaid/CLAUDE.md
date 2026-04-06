# Mermaid Visualization Package

Generates Mermaid flowchart diagrams from workflow IR. Handles sub-workflow expansion (recursive), batch item rendering, data-flow edge inference, and structural edge routing.

## Public API

```python
from pflow.core.workflow.mermaid import generate_mermaid

mermaid_str = generate_mermaid(
    ir,                              # workflow IR dict
    resolve_child=resolve_sub_workflow,  # sub-workflow resolver callback
    base_path=Path("/path/to/workflow"),
    max_depth=5,                     # sub-workflow expansion depth
    direction="TD",                  # "LR" or "TD"
    descriptions=True,               # add node purpose to labels
)
```

Consumers: `cli/commands/visualize.py`, `tests/test_core/test_mermaid.py`, `tests/test_core/test_mermaid_golden.py`.

## File Map

```
mermaid/
├── __init__.py    # Re-exports generate_mermaid + 5 test-visible helpers
├── _context.py    # MermaidConfig (frozen), MermaidContext (mutable), constants, pure utilities
├── _edges.py      # Edge dedup/detection, routing resolution, data-flow edge generation
├── _io.py         # Input/output node rendering (top-level, sub-workflow, external wrappers)
├── _render.py     # Core pipeline: generate_mermaid → _render_workflow → _render_node
└── CLAUDE.md
```

**Import DAG** (no cycles): `_context` ← `_edges`, `_io` ← `_render` ← `__init__`. No cross-calls between `_edges` and `_io`.

## Function-to-File Map

| Function | File | Purpose |
|----------|------|---------|
| `generate_mermaid` | `_render.py` | Public entry point — creates context, kicks off pipeline |
| `_render_workflow` | `_render.py` | Orchestrates one workflow level (nodes → inputs → outputs → edges) |
| `_render_node` | `_render.py` | Dispatches: batch inline / sub-workflow expansion / regular node |
| `_render_batch_inline` | `_render.py` | Fork/join or 2+ellipsis for batch items |
| `_try_expand_batch_item` | `_render.py` | Resolves and renders a batch item's sub-workflow |
| `_render_subgraph` | `_render.py` | Renders expanded sub-workflow as mermaid subgraph |
| `_render_end_nodes_and_edges` | `_render.py` | Terminal end nodes + all structural edge rendering |
| `_try_resolve_child` | `_render.py` | Sub-workflow resolution with cycle detection |
| `_deduplicate_edges` | `_edges.py` | Remove doc-order edges when named-action edge exists |
| `_detect_decision_nodes` | `_edges.py` | Find nodes with ≥2 named action edges |
| `_find_terminal_nodes` | `_edges.py` | Find nodes with no non-error outgoing edges |
| `_resolve_edge_endpoints` | `_edges.py` | Route edges through IO maps and fork/join maps |
| `_render_edge` | `_edges.py` | Render one edge with suppression + routing logic |
| `_generate_data_flow_edges` | `_edges.py` | Parse `${ref}` in params → edges to sub-workflow inputs |
| `_generate_batch_item_data_flow` | `_edges.py` | Data-flow edges from parent params to expanded batch items |
| `_extract_batch_source` | `_edges.py` | Extract source node ID from batch items template ref |
| `_resolve_ref_source` | `_edges.py` | Resolve a template ref name to a mermaid source ID |
| `_render_inputs` | `_io.py` | Top-level workflow input parallelograms |
| `_connect_top_level_inputs` | `_io.py` | Connect inputs to actual consuming nodes via param analysis |
| `_render_top_level_outputs` | `_io.py` | Top-level output wrapper subgraph at bottom |
| `_render_subworkflow_inputs` | `_io.py` | Internal sub-workflow input nodes (when not suppressed) |
| `_render_subworkflow_outputs` | `_io.py` | Internal sub-workflow output nodes (when not suppressed) |
| `_render_external_inputs` | `_io.py` | Dashed input wrapper subgraph at parent scope |
| `_render_external_outputs` | `_io.py` | Dashed output wrapper subgraph at parent scope |
| `_connect_sources_to_output` | `_io.py` | Parse source expression → connect producing nodes to output |
| `MermaidConfig` | `_context.py` | Frozen config dataclass (resolve_child, max_depth, etc.) |
| `MermaidContext` | `_context.py` | Mutable per-level state (routing maps, indent, prefix) |
| Pure utilities (13) | `_context.py` | `_to_mermaid_id`, `_escape_label`, `_get_node_shape`, `_format_label`, `_first_sentence`, `_classdef_to_style`, `_subgraph_style`, `_get_item_label`, `_dynamic_batch_label`, `_format_node_type`, `_refs_input`, `_collect_param_refs`, `_render_classdefs` |

## Two Kinds of Edges

The output has **structural edges** (from the IR's `edges` list — execution order) and **data-flow edges** (inferred from `${ref}` template patterns in node params). Data-flow edges show where data actually flows into sub-workflow inputs. When both exist for the same target, the structural edge is suppressed (`data_flow_targets` set controls this).

**Critical insight**: Structural edges ≠ data flow. Three failed attempts at routing structural edges through IO proved that conflating execution order with data flow produces wrong visualizations. Data flow lives in template refs, not in the IR's edge list.

## MermaidContext: Shared vs Per-Level State

`ctx.child(prefix, suppress_io, base_path)` creates a new context for recursive sub-workflow rendering.

| Field | Lifetime | Notes |
|-------|----------|-------|
| `lines`, `seen` | **Shared** (same object reference across all depths) | All recursion levels append to the same `lines` list |
| `prefix`, `indent`, `current_depth`, `suppress_io`, `base_path` | **Per-level** (set at creation, immutable after) | `indent = "    " * (current_depth + 1)` |
| `outgoing_routes`, `has_expanded_outputs`, `fork_join_map`, `incoming_map`, `data_flow_targets` | **Per-level** (fresh empty, populated during `_render_workflow`) | The 5 routing maps |
| `decision_nodes`, `parent_inputs`, `sibling_node_ids` | **Per-level** (set by `_render_workflow` at start) | IR-derived, read-only after set |

## The `outgoing_routes` / `has_expanded_outputs` Split

**INVARIANT: These two must always be written together.** Any code that writes `ctx.outgoing_routes[id] = value` must also write `ctx.has_expanded_outputs.add(id)`.

| Field | Type | Purpose | Readers |
|-------|------|---------|---------|
| `outgoing_routes` | `dict[str, dict[str, str]]` | Edge routing — maps mermaid IDs to `{output_name: output_mermaid_id}` | `_resolve_edge_endpoints`, `_render_edge`, `_resolve_ref_source` (routing) |
| `has_expanded_outputs` | `set[str]` | Skip signal — "this node has expanded outputs, structural edges handle it" | `_resolve_ref_source` (line 115), `_render_edge` (line 186) |

Exactly **two write sites**: `_render_external_outputs` (`_io.py:348-349`) and `_render_batch_inline` (`_render.py:272-275`).

The split enables a future fix for the batch output fan limitation — `outgoing_routes` could exclude batch entries while `has_expanded_outputs` keeps them. Not applied yet; both are populated identically.

## The `suppress_io` Pattern

When a parent expands a sub-workflow, it renders IO **externally** (dashed wrappers at parent scope). The child renders with `suppress_io=True` to avoid duplicate IO.

Rendering order in `_render_node` for an expanded sub-workflow:
1. `_render_external_inputs` — input wrapper (BEFORE subgraph)
2. `_render_subgraph` with `suppress_io=True` — sub-workflow content
3. `_render_external_outputs` — output wrapper (AFTER subgraph)
4. `_generate_data_flow_edges` — upstream nodes → child inputs

Batch item expansion (`_try_expand_batch_item`) does NOT use `suppress_io` — items use internal IO.

## Mermaid ID Convention (Load-Bearing)

All mermaid node IDs follow: `{prefix}{node_id}` where prefix accumulates via `parent_id + "__"` at each nesting level. IO nodes use `{prefix}{node_id}__in_{name}` and `{prefix}{node_id}__out_{name}`.

**Do not change this convention.** Every routing map, data-flow edge, and structural edge routing function assumes these IDs. Changing them requires updating ALL consumers.

## `_connect_sources_to_output` Varargs

Takes `*outgoing_maps` (not `ctx.outgoing_routes` directly) because callers search different map combinations:
- `_render_top_level_outputs`: `ctx.outgoing_routes` (parent only)
- `_render_subworkflow_outputs`: `ctx.outgoing_routes` (current level only)
- `_render_external_outputs`: `_child_out, ctx.outgoing_routes` (child first, then parent — for nested routing)

## `base_path` Is Per-Level

Lives on `MermaidContext`, not `MermaidConfig`, because sub-workflows can live in different directories. `_render_subgraph` and `_try_expand_batch_item` compute `child_base = child_result.path.parent` and pass it to `ctx.child(base_path=child_base)`.

## Testing

```bash
# Unit tests (55) + golden file tests (7) + CLI tests (10)
uv run pytest tests/test_core/test_mermaid.py tests/test_core/test_mermaid_golden.py tests/test_cli/test_visualize.py -v

# Manual verification (REQUIRED for edge routing changes):
uv run pflow visualize <workflow.pflow.md> --depth 5 --direction TD -o output.mmd
# Render in mermaid.live — string-level checks miss visual breakage
```

Golden files at `tests/test_core/golden_mermaid/`. To regenerate after intentional changes:
```bash
uv run pflow visualize <workflow> [flags] -o tests/test_core/golden_mermaid/<name>.mmd
```

## Common Pitfalls

1. **Don't remove routing maps.** They look redundant with external IO. They're not — `has_expanded_outputs` is a shared signal for `_resolve_ref_source`. Removing entries creates cascading failures.
2. **Don't change the mermaid ID convention.** `{prefix}{node_id}__in_{name}` and `__out_{name}` are referenced by every routing mechanism.
3. **`suppress_io` and end nodes are coupled.** Changing one without the other causes end node regression.
4. **`_render_workflow` return value is essential.** Returns `outgoing_routes` for nested output routing. Ignoring it causes edges to connect to subgraph boxes.
5. **Batch suffix `|` delimiters bypass `_escape_label`.** Pipe characters in `x|sources|` must survive for Mermaid rendering. `_format_label` and `_render_subgraph` append batch suffix AFTER escaping.
6. **Always render and visually verify.** String-level assertions can pass while the rendered diagram is broken.

## Known Limitation

**Batch output fan**: When a batch node with expanded workflow items has outputs, structural edges fan through ALL outputs to the downstream node. The `outgoing_routes`/`has_expanded_outputs` split was designed to enable fixing this — see `scratchpads/mermaid-improvements/change1-failed-analysis.md` for 4 failed attempts and root cause analysis.
