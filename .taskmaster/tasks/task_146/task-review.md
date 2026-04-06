# Task 146 Review: Rich Mermaid Visualization

## Metadata

- Implementation Date: 2026-04-05 to 2026-04-06 (across 3 sessions with different agents)
- Post-implementation code review and external IO refactor: 2026-04-06

## Executive Summary

Transformed the mermaid generator from a flat topology renderer (163 lines) into a data-flow visualization system (1444 lines) that shows batch parallelism, sub-workflow boundary IO, data provenance through template refs, and type-differentiated node shapes. The implementation evolved through iterative visual review — the user's questions about rendered diagrams drove every major design change. The most important architectural insight: structural edges (execution order) and data-flow edges (what feeds what) are fundamentally different concerns that must be rendered separately.

## Implementation Overview

### What Was Built

The original spec described 10 visual improvements (shapes, colors, batch labels, dedup, etc.). The implementation delivered all of those PLUS four major unplanned features that emerged from iterative review:

1. **External IO wrappers** — sub-workflow inputs/outputs as dashed wrapper subgraphs OUTSIDE the pipeline, with cross-boundary edges. Replaces internal IO.
2. **Data-flow edges from template refs** — `${node.field}` refs in params generate edges showing actual data provenance. Structural edges suppressed when data-flow covers the connection.
3. **Batch item data-flow edges** — parent batch node's params generate edges to each expanded item's inputs.
4. **Mermaid `procs` shape** (v11+) — stacked rectangles for dynamic batch nodes, visually communicating "runs multiple times."

Plus: top-level output rendering, smart input connections to actual consumers, subgraph depth coloring, variable names in batch labels.

### Implementation Approach

Three sessions with different implementation stages:

**Session 1** (different agent): Initial implementation — shapes, colors, batch fork/join, edge dedup, decision nodes, descriptions flag. Then iterative visual review with user added: sub-workflow IO nodes, data-flow edges, outgoing_map/incoming_map/data_flow_targets routing, source-field parsing. This produced the v2 "internal IO" code.

**Session 2** (this agent, first pass): External IO refactor attempt — tried to simultaneously move IO outside, eliminate routing maps, and add batch item data-flow. Failed catastrophically. Reverted.

**Session 3** (this agent, second pass): Successful external IO refactor using `suppress_io` flag. Preserved all routing maps. Added `procs` shape, variable names, top-level outputs, smart input connections. Fixed batch item output routing and data-flow edge suppression.

**Session 4**: Code review fixes (DRY extraction, vacuous test fix, em-dash consistency). New features: `.md` output wrapping with title/description, subgraph descriptions, theme-safe `fill-opacity` styling. Golden file test suite. Package decomposition refactor: single 1450-line file → `mermaid/` package with `MermaidContext` object and `outgoing_map` split.

## Files Modified/Created

### Core Changes

- `src/pflow/core/workflow/mermaid/` — Package (5 files, ~1500 lines total, from single 163-line file). `_context.py` (289), `_edges.py` (293), `_io.py` (351), `_render.py` (470), `__init__.py` (22). Public API (`generate_mermaid`) unchanged.
- `src/pflow/cli/commands/visualize.py` (92 → 106 lines) — Added `--descriptions` flag, `.md` output wrapping.
- `src/pflow/execution/result.py` — Added `title`, `description` fields to `ResolvedWorkflow`.
- `src/pflow/execution/workflow_resolver.py` — Populates `title`/`description` from `parse_markdown`.

### Test Files

- `tests/test_core/test_mermaid.py` (392 → ~1257 lines, 55 tests) — All 15 original tests updated for new shape syntax. 40 new tests including 4 high-value regression tests.
- `tests/test_core/test_mermaid_golden.py` (new, 7 tests) — Byte-exact golden file comparisons against real workflows.
- `tests/test_core/golden_mermaid/` (new, 7 files) — Golden baselines for 5 in-repo + 2 lyrics-generator workflows.
- `tests/test_cli/test_visualize.py` (199 → ~258 lines, 10 tests) — 3 new tests (descriptions, `.md` output, `.mmd` output).

**Critical tests** (catch real bugs, not just coverage):
- `test_suppression_without_replacement_keeps_structural_edge` — guards against silent disconnection when data-flow name matching fails
- `test_external_io_does_not_duplicate_with_internal_io` — catches `suppress_io` propagation bugs
- `test_top_level_input_connects_to_actual_consumer` — catches regression to blind first-node connection

## Architectural Decisions & Tradeoffs

### Structural edges vs data-flow edges are separate concerns

The IR has two data sources: `edges` (execution order) and `node.params` template refs (data flow). The visualization renders BOTH, with structural edges suppressed when data-flow covers the connection. This was the single most important insight — three failed attempts at routing structural edges through IO proved that conflating execution order with data flow produces wrong visualizations.

### Five routing maps are intentionally kept

`outgoing_map`, `incoming_map`, `data_flow_targets`, `fork_join_map`, and data-flow edges interact through specific rules. The failed refactor attempt proved these can't be simplified by elimination — `outgoing_map` is a shared signal that `_resolve_ref_source` reads to decide whether to SKIP data-flow edge generation. Removing it changes three behaviors simultaneously.

### External IO uses `suppress_io` flag, not map elimination

IO moved outside subgraphs by adding a `suppress_io` parameter. When True, the child skips internal IO and end nodes; the parent renders IO externally. The routing maps stay unchanged because mermaid IDs follow the same convention regardless of rendering position.

### `procs` shape requires `style` directives

Mermaid's `@{ shape: procs }` syntax is incompatible with `:::classDef`. Batch nodes use `style` directives via `_classdef_to_style()`, while all other nodes use `:::classDef`. `_CLASSDEF_STYLES` dict is the single source of truth for both paths.

### Technical Debt

- **`outgoing_map` dual purpose** — now split into `outgoing_routes` (routing) and `has_expanded_outputs` (signal). Both populated identically today. The split enables a future fix for the batch output fan — `outgoing_routes` could exclude batch entries while `has_expanded_outputs` preserves the skip signal.
- ~~**`_render_node` has 18 parameters**~~ — resolved. `MermaidContext` object reduces to 2 params (`node`, `ctx`).
- **Internal IO still exists for batch items** — expanded batch items use `suppress_io=False` (internal IO). External IO would add 3 wrapper subgraphs per item for what are often single-node pipelines.

## Unexpected Discoveries

### `outgoing_map` is a shared signal, not just data

Four failed attempts to suppress batch output fan-out all broke because removing entries from `outgoing_map` changed `_resolve_ref_source`'s skip behavior, enabling data-flow edges that were previously suppressed, creating cross-connections that destroyed dagre layout. See `scratchpads/mermaid-improvements/change1-failed-analysis.md`.

### Long-range edges destroy dagre layout

Any edge that skips pipeline stages (e.g., `input_sources → prepare-brief-inputs` jumping over 6 nodes) scatters the entire diagram. `_connect_top_level_inputs` must connect to the NEAREST consumer only.

### Nested outgoing_map scoping

`_render_external_outputs` for create-songs needs choose-chorus's output entries, but those live in create-songs' internal `outgoing_map`. Fixed by having `_render_workflow` return its `outgoing_map` and `_render_subgraph` pass it up to the parent.

### Code node params are nested

Code nodes store declared inputs at `params.inputs` (a nested dict), not at the top level. `_collect_param_refs` must recurse one level into nested dicts.

### Mermaid doesn't support `rgba()` but does support `fill-opacity`

Subgraph fills use `fill:#808080,fill-opacity:N` — neutral gray overlay that works on both light and dark themes. `rgba()` fails in Mermaid's style parser, but SVG `fill-opacity` passes through correctly.

## Patterns Established

### External IO wrapper pattern

For any expanded sub-workflow:
1. Render input wrapper subgraph (dashed) BEFORE the pipeline subgraph
2. Render pipeline subgraph with `suppress_io=True`
3. Render output wrapper subgraph (dashed) AFTER
4. Cross-boundary edges: inputs → internal start, producing → outputs
5. Pass child's `outgoing_map` to output renderer for nested routing

### Data-flow edge generation pattern

For each expanded sub-workflow, scan parent node's params for `${ref.field}` template refs. Resolve source (sibling node, parent input, or batch source). Generate edge to the matching child input node. Add to `data_flow_targets` for structural edge suppression.

### `procs` shape pattern

For `@{ shape: ... }` nodes that can't use `:::classDef`: emit a `style` directive on the next line using `_classdef_to_style()`. Same colors as classDef, different application mechanism.

## Breaking Changes

### Behavioral Changes

- Sub-workflow IO now renders OUTSIDE subgraphs (was inside). Visual change only — no API change.
- Top-level inputs connect to actual consumers (was: first node). `output_base` no longer connects to `fetch-sources`.
- Top-level workflow outputs rendered at bottom (was: not rendered).
- Dynamic batch labels show variable names `x|sources|` (was: `xN`).
- Legend removed (was: rendered at bottom).
- End nodes only appear for top-level branching workflows without outputs (was: inside all branching sub-workflows).

## Known Limitations

1. **Batch sub-workflow output fan** — create-songs' 13 outputs all fan to prepare-evaluation. The `outgoing_routes`/`has_expanded_outputs` split now enables fixing this (not yet applied).
2. **Top-level inputs first-consumer-only** — connecting to all consumers creates long-range edges that destroy layout.
3. **`procs` shape + `:::classDef` incompatible** — requires `style` directive workaround.

## AI Agent Guidance

### Quick Start for Related Tasks

Read `src/pflow/core/workflow/mermaid/CLAUDE.md` — contains file map, function-to-file map, context state table, common pitfalls, and testing commands.

Then read in order:
1. `_render.py` — start with `generate_mermaid`, then `_render_workflow`, then `_render_node`
2. `_context.py` — `MermaidContext` class and all constants/utilities
3. `.taskmaster/tasks/task_146/implementation/progress-log.md` — design evolution and traps

### Test-First Recommendations

```bash
# After any change to mermaid/:
uv run pytest tests/test_core/test_mermaid.py tests/test_core/test_mermaid_golden.py tests/test_cli/test_visualize.py -v
make check
```

The four high-value regression tests catch the most dangerous failure modes. If any fail, do NOT proceed:
- `test_suppression_without_replacement_keeps_structural_edge`
- `test_external_io_does_not_duplicate_with_internal_io`
- `test_top_level_input_connects_to_actual_consumer`
- `test_nested_subworkflow_output_routes_through_child_output`

---

*Generated from implementation context of Task 146*
