# Task 146: Rich Mermaid Visualization — Progress Log

## Implementation Approach

The plan specified 9 sequential phases. In practice, all phases were implemented as a single coordinated rewrite of `mermaid.py` because the phases are deeply interconnected — edge deduplication feeds into edge rendering, decision detection feeds into node shapes, fork_join_map spans batch rendering and edge rerouting. Testing was done incrementally.

## Phase 1: Edge Preprocessing

**Status**: Complete. No deviations.

- `_deduplicate_edges`: Builds set of (from, to) pairs with named action edges, then filters out document-order and "default" edges for those pairs. Error edges preserved.
- `_detect_decision_nodes`: Counts distinct non-error, non-default named actions per source node. >= 2 = decision.

**Key insight**: The `"action" in edge` check (key existence) vs `edge.get("action")` distinction is critical. Document-order edges have NO `action` key. Explicit edges always have one. This was correctly specified in the plan.

## Phase 2: Node Shape Mapping

**Status**: Complete. Minor deviations.

- `_SHAPE_MAP` covers llm, shell, write-file, code, workflow with distinct bracket syntaxes
- `_get_node_shape` checks decision first, then MCP prefix, then lookup
- `_format_node_type` handles MCP line breaks
- `_format_label` assembles full label with optional batch suffix and descriptions
- `_first_sentence` strips markdown bold/italic, finds first sentence boundary, truncates to 80 chars
- `_render_classdefs` adds 8 classDef declarations

**All 15 existing tests updated** — every assertion checking node declaration syntax (brackets, css classes) was changed from the old `'id["label"]'` format to new typed shapes like `'id[["label"]]:::shell'`.

## Phase 3: Batch Rendering

**Status**: Complete. No deviations from plan.

- `_get_item_label` with priority keys (name, label, focus, lens) and skip keys (workflow, prompt, command, model)
- `_render_batch_inline` creates subgraph with fork/join items. <=4 shows all, >4 shows 2+ellipsis
- `fork_join_map` populated by batch rendering, consumed by edge rendering for fan-out/fan-in
- Dynamic batch (`items` is a string template) adds `(parallel xN)` or `(xN)` to labels/subgraph labels

**Decision**: Used `... x6` for ellipsis (plan said `⋯ ×6`). The unicode ellipsis and multiplication sign render fine in Mermaid but the ASCII versions are more universally safe. This is a cosmetic difference.

## Phase 4: Terminal End Nodes

**Status**: Complete. No deviations.

- `_find_terminal_nodes` finds nodes with no non-error outgoing edges
- End node `(("end"))` only rendered when `decision_nodes` is non-empty (branching workflow)
- End node edges route through `fork_join_map` for fork/join terminal nodes

## Phase 5: Input Nodes

**Status**: Complete. No deviations.

- `_render_inputs` creates parallelogram `[/"label"/]:::input` nodes
- Connected to start node (first node in IR or `start_node` if specified)
- Only rendered at top level (depth 0), not for sub-workflows

## Phase 6: Legend

**Status**: Complete. No deviations.

- `_render_legend` adds disconnected subgraph with one node per type
- Always rendered (even for simple workflows) — provides consistent key

**Impact on existing tests**: The `test_depth_zero_no_expansion` CLI test asserted `"subgraph" not in result.output` but the Legend subgraph is always present. Fixed assertion to filter out Legend subgraphs. Similarly `test_no_resolver_skips_expansion` needed the same treatment.

## Phase 7: CLI --descriptions Flag

**Status**: Complete. No deviations.

- Added `--descriptions` click flag to `visualize.py`
- Threaded `descriptions: bool` through `generate_mermaid` -> `_render_workflow` -> `_render_node`
- Descriptions appear as `<br/>First sentence.` in node labels

## Phase 8: Back-Edge Test

**Status**: Complete. No code changes needed. Test confirms back-edges render correctly.

## Phase 9: Final Assembly

**Status**: Complete.

### Ruff Complexity Refactor

The original plan had all logic in `_render_workflow`, which hit C901 complexity (>10). Refactored into:
- `_render_workflow` (orchestrator, ~20 lines) — iterates nodes, calls `_render_node`, then `_render_end_nodes_and_edges`
- `_render_node` — handles single node: batch fork/join, dynamic batch, sub-workflow expansion, or regular shape
- `_dynamic_batch_label` — extracts batch suffix string
- `_render_subgraph` — handles sub-workflow expansion with cycle tracking
- `_render_edge` — single edge with fork/join fan-out/fan-in
- `_render_end_nodes_and_edges` — end nodes + edge loop + terminal connections

This added ~30 lines but each function is under complexity 10.

### Mypy Fix

`edge.get("action")` returns `Any | None` which mypy can't narrow to `str` through conditional checks. Fixed with `str(action)` in the `_escape_label` call.

### Unused Variable

Plan mentioned `batch_suffix` variable but it was never actually used — `dynamic_batch_label` serves the purpose. Removed.

## Verification Results

### Automated
- `make check`: All passing (ruff, mypy, deptry)
- `make test`: 4632 tests passing
- `test_mermaid.py`: 43 tests (15 updated existing + 28 new)
- `test_visualize.py`: 8 tests (7 existing + 1 new)

### Manual — lyrics-generator
All 11 verification points from the spec confirmed:
1. Input parallelograms for `sources` and `output_base`
2. `fetch-sources` as `(parallel xN)` with diamond `classify`, 4 branches, error, end node, no duplicate edges
3. `analyze-sources` as `(parallel xN)` with `analyze` fork/join showing 2 items + `... x6`
4. `choose-concepts` with `generate-concepts` fork/join for 4 lenses
5. `create-songs` as `(parallel xN)` with nested choose-chorus, emotional-reviews (3 items), craft-reviews (3 items)
6. Type-specific shapes (stadium, subroutine, hexagon, etc.)
7. classDefs at top
8. Legend at bottom
9. CSS class suffixes on all nodes
10. No duplicate classify edge
11. End nodes in fetch-source

### Manual — descriptions flag
Verified descriptions appear with `<br/>` and first sentence extraction.

## Files Modified

| File | Lines before | Lines after | Change |
|------|-------------|-------------|--------|
| `src/pflow/core/workflow/mermaid.py` | 163 | ~500 | Full rewrite |
| `src/pflow/cli/commands/visualize.py` | 92 | 100 | +8 lines (--descriptions flag) |
| `tests/test_core/test_mermaid.py` | 392 | ~630 | 15 tests updated + 28 new tests |
| `tests/test_cli/test_visualize.py` | 199 | ~225 | 1 test updated + 1 new test |

## Deviations from Plan

1. **Cosmetic**: Used ASCII `... x6` instead of unicode `⋯ ×6` for ellipsis and multiplication
2. **Structure**: Decomposed `_render_workflow` into 5 smaller functions to satisfy ruff C901 complexity limit
3. **No separate phases**: All phases implemented as one coordinated change since they're deeply coupled
4. **Unused batch_suffix**: Plan specified it but `dynamic_batch_label` already served that purpose — removed
5. **`_WORKFLOW_TYPES` as module constant**: Moved from local variable to module-level constant for clarity

## Post-Review Fixes (2026-04-06)

Three issues identified during manual review:

### 1. Black text in colored nodes
Added `color:#000` to all classDef declarations. Without this, dark-themed renderers show gray text on colored backgrounds, making labels hard to read.

### 2. Decision node count verification
Only `classify` is a decision node — confirmed correct. It's the only node in the entire lyrics-generator with >=2 named action edges (4 conditional branches: fetch-youtube, fetch-webpage, read-file, pass-text). All other inter-node edges are document-order.

### 3. Batch item workflow expansion (spec item 8)
Implemented `_try_expand_batch_item` — when batch items have literal `workflow` paths (not `${...}` template refs), each item's sub-workflow is resolved and expanded as a nested subgraph. This makes `craft-reviews` and `emotional-reviews` show their internal `review (llm)` node instead of opaque "workflow" rectangles.

**Implementation**: Added optional parameters to `_render_batch_inline` for sub-workflow resolution context. New `_try_expand_batch_item` function checks each item dict for a `workflow` key with a literal (non-template) path, resolves via `resolve_child`, and renders as a subgraph if successful. Falls back to opaque node on resolution failure.

**Tests added**: `test_batch_item_workflow_expansion` and `test_batch_item_template_workflow_not_expanded`.

**Final counts**: 4634 tests passing, 45 mermaid tests, 8 CLI visualize tests.

## Sub-Workflow Data Flow — Design Evolution (2026-04-06)

This section documents the most significant design changes — a multi-step evolution driven by iterative manual review. Each step revealed a deeper problem with how the visualization represented data flow across sub-workflow boundaries.

### Problem: "What does `end` mean? How does this relate to the next step?"

The user couldn't understand the fetch-sources subgraph. The `(("end"))` node looked like workflow termination, not branch convergence. And the connection to analyze-sources was a single structural edge to the subgraph box — no indication of what data flows between them.

**Root cause**: The visualization showed execution topology but erased data flow at sub-workflow boundaries. A reader couldn't answer: "What goes in? What comes out? What feeds the next step?"

### Solution 1: Sub-workflow boundary IO nodes

Added `_render_subworkflow_inputs` (parallelogram entry nodes) and `_render_subworkflow_outputs` (stadium exit nodes) inside subgraphs. Output nodes replaced `end` nodes — `content` and `source_type` are much more meaningful than `end`.

**Key design decision**: Outputs are connected to their actual producing nodes by parsing the `source` field in the IR's outputs section. `source: ${fetch-youtube.stdout ?? fetch-youtube-mcp.result ?? ...}` uses `_SOURCE_NODE_FIELD_RE` to extract all referenced node IDs and connect them. This is far more accurate than connecting all terminal nodes to all outputs.

**Tests**: `test_subworkflow_outputs_replace_end_node`, `test_subworkflow_inputs_rendered_inside`, `test_subworkflow_linear_outputs_connected`.

### Solution 2: Output routing for structural edges (outgoing_map)

When an expanded subgraph has outputs, structural edges FROM that subgraph should route through the output nodes. `outgoing_map` maps `subgraph_id → {output_name: mermaid_id}`. The `_resolve_edge_endpoints` function handles this: `fetch-sources → analyze-sources` becomes `out_content → analyze-sources`.

### Mistake 1: Cross-product IO routing

First attempt at routing edges THROUGH both IO maps used a cross-product: all outputs × all inputs. This created false connections — `source_type → content` (wrong: source_type doesn't feed content).

**Fix**: Name matching — only connect output→input when names match. If no names match, fall back to subgraph-level edge.

**Lesson**: Naive cross-product routing between IO boundaries produces incorrect visualizations. Name matching is essential but imperfect (names can differ: output `analysis` vs input `analyses`).

### Mistake 2: Routing structural edges through inputs (incoming_map)

Added `incoming_map` to route structural edges TO sub-workflow inputs (mirroring outgoing_map). This produced wrong connections: `easter-eggs → all 4 choose-chorus inputs`. Easter-eggs is the previous node in execution order but it doesn't produce creative_direction, architecture, etc.

**Root insight**: **Structural edges represent execution order, not data flow.** The IR's edges say "this runs after that." Data flow is encoded in template refs across params. Conflating them produces wrong visualizations. This was the single most important insight of the entire implementation.

### Solution 3: Data-flow edges from param template refs

Replaced input routing with `_generate_data_flow_edges` — parses the parent node's `params` for `${node_id.field}` template refs and generates edges from the actual source nodes to the corresponding input nodes.

For `choose-chorus` with params `creative_direction: ${creative-direction.response}`:
- `creative-direction` (the node) → `choose-chorus__in_creative_direction` (the input)

Three ref types handled by `_resolve_ref_source`:
1. **Sibling node ref** (`${creative-direction.response}`) → connect from sibling node
2. **Parent input ref** (`${concept_brief}`) → connect from parent's input parallelogram
3. **Batch item ref** (`${item.content}`) → connect from batch source node (parsed from `batch.items` template)

**Tests**: `test_data_flow_edges_from_params`, `test_data_flow_skips_item_refs`.

### Structural edge suppression

When data-flow edges connect to a subgraph's inputs, the structural edge to that subgraph box is redundant. Added `data_flow_targets` set to track which subgraphs have data-flow edges.

**Critical nuance**: Only suppress when the source has NO outputs. When the source HAS outputs, the structural edge routes through outgoing_map with name matching — this is the correct way to show output→input connections between two expanded subgraphs.

### Batch source tracing

For batch workflow nodes with `${item.*}` params, the data source IS traceable: parse `batch.items` template ref. `batch: {items: "${zip-concepts-with-briefs.result}"}` → `zip-concepts-with-briefs` feeds the inputs.

**Edge case**: Skip batch source data-flow edges when the batch source has outputs in `outgoing_map` — the name-matched structural edge already handles the connection correctly, avoiding duplicates.

### Subgraph output routing in source expressions

When `_render_subworkflow_outputs` parses `source: ${choose-chorus.winning_chorus}`, it now checks if `choose-chorus` is in `outgoing_map`. If so, it matches the field name (`winning_chorus`) against the subgraph's output names and routes through `choose-chorus__out_winning_chorus` instead of the subgraph box.

Same pattern applied in `_resolve_ref_source` for data-flow edges: when a sibling node has exactly one output, route through it instead of the subgraph box.

### Subgraph depth coloring

Added `_subgraph_style` function — emits a `style` directive after each subgraph `end` with progressively darker fills based on nesting depth. Uses `_SUBGRAPH_FILLS` array (`#2a2a2e` → `#333338` → `#3c3c42` → `#45454c`).

### Legend removal

Removed `_render_legend` — the legend was visual clutter. Node shapes and colors are self-explanatory with type labels.

## Key Architectural Decisions

### Execution order vs data flow are different concerns

The IR has two data sources for visualization:
1. `edges` — execution order (structural, document order, named actions)
2. `node.params` template refs + `output.source` expressions — data flow

The visualization now renders BOTH:
- Structural edges show pipeline ordering (what runs after what)
- Data-flow edges show param provenance (what feeds what)
- Output source edges show what nodes produce each output

Structural edges are suppressed when data-flow edges cover the same connection to avoid redundancy.

### Five routing maps in edge rendering

Edge rendering uses five interacting mechanisms:
1. `fork_join_map` — symmetric fan-out/fan-in for batch inline items
2. `outgoing_map` — routes structural edges FROM subgraphs through their output nodes
3. `incoming_map` — routes structural edges TO subgraphs through their input nodes (only when source has outputs — name matching)
4. `data_flow_targets` — suppresses structural edges to subgraphs that have data-flow edges (only when source has no outputs)
5. Data-flow edges from `_generate_data_flow_edges` — param template refs connecting source nodes to input nodes

The interaction rules:
- If source in outgoing_map AND target in incoming_map → name-matched output→input routing
- If source in outgoing_map AND target NOT in incoming_map → fan from all outputs to target
- If source NOT in outgoing_map AND target in data_flow_targets → suppress (data-flow edges handle it)
- Otherwise → plain structural edge through fork_join_map

### Source field parsing vs terminal detection

Initially, terminal nodes (no outgoing edges) were connected to ALL output nodes. This was replaced by source field parsing: `source: ${node.field}` tells us exactly which node produces each output. This eliminated false connections and made the diagram accurately show which specific node feeds each output.

## Hard-Won Lessons

1. **Structural edges ≠ data flow.** This was the core insight. Routing structural edges through IO nodes pretends execution order IS data flow — and it's wrong. Data flow lives in template refs.

2. **Cross-product routing creates false connections.** All outputs × all inputs is wrong. Name matching is required, and even name matching is imperfect when names differ across boundaries.

3. **Suppression rules interact.** Every new routing mechanism must account for existing ones. `data_flow_targets` suppression must not fire when `outgoing_map` provides name-matched routing. Batch source data-flow edges must not fire when outgoing_map already handles the connection.

4. **Every fix revealed the next problem.** Adding IO nodes → revealed wrong edge routing → led to data-flow edges → revealed batch source tracing → revealed output-through-subgraph routing. Each layer of correctness exposed the next incorrectness. This is inherent to visualization: what looks right in code often looks wrong when rendered.

5. **Iterative visual review is essential.** Every rendering choice that seemed correct in code revealed issues when the user saw the rendered diagram. Fresh eyes catch problems invisible to the implementer. The user's questions — "what does this edge mean?", "is this correct?" — drove all the important design changes.

6. **Visualization is a data-flow problem, not a graph-layout problem.** The initial approach treated visualization as "render the IR's graph structure." The evolved approach treats it as "show where data comes from and where it goes." This required going beyond the IR's edge list to parse template refs and source expressions.

## External IO Refactor (2026-04-06, second session)

### Problem

Sub-workflow IO nodes were rendered INSIDE subgraphs, forcing 3 complex routing maps (`outgoing_map`, `incoming_map`, `data_flow_targets`) to wire edges across subgraph boundaries. The user wanted IO rendered OUTSIDE as dashed wrapper subgraphs — inputs before the pipeline, outputs after — matching a hand-crafted prototype at `scratchpads/mermaid-improvements/external-io-prototype.mmd`.

### Failed First Attempt

The first implementation plan tried to simultaneously:
1. Move IO outside subgraphs
2. Eliminate all 3 routing maps
3. Add batch item data-flow edges

This broke everything. Root causes:
- **Routing maps were removed before external IO was wired.** Edges that depended on `outgoing_map` for output→downstream routing lost their mechanism.
- **Batch sub-workflows were excluded from IO wrappers.** The plan incorrectly assumed batch nodes shouldn't get external IO. The prototype showed ALL expanded sub-workflows (including batch) with IO wrappers.
- **`end` nodes reappeared.** Internal IO was suppressed but `_render_end_nodes_and_edges` still generated end nodes because `output_ids` was empty (outputs were supposed to be external but weren't rendered for batch nodes).
- **Structural edge suppression fired without replacement edges.** `data_flow_targets` suppressed structural edges, but the data-flow edges that should have replaced them were also suppressed by a different rule.
- **The plan was followed mechanically instead of preserving current behaviors.** The plan referenced patterns (like end nodes) that the v2 code had already moved past. The implementer followed the plan's function-level changes rather than understanding what the current code does correctly.

**Key lesson**: When refactoring working code, start from "what does this code do correctly today?" and ensure every behavior survives. Don't follow a plan that predates the code's current state.

### Successful Second Attempt — Approach

**Critical insight**: The routing maps don't need to be eliminated. They track by mermaid ID, which stays the same regardless of where nodes are rendered. The actual change is purely about rendering POSITION — IO nodes emit at parent scope in dashed wrappers instead of inside the subgraph. All routing logic stays identical.

The implementation uses a `suppress_io` flag:
1. `_render_workflow` accepts `suppress_io: bool = False`
2. When `suppress_io=True`: skip internal IO rendering (`_render_subworkflow_inputs`/`_render_subworkflow_outputs`) and skip end node generation
3. The PARENT renders IO externally via new functions, then passes `suppress_io=True` to the child

### What Changed

**New functions:**
- `_render_external_inputs(child_ir, lines, indent, node_id, prefix)` — renders dashed wrapper subgraph with input parallelograms at parent scope, plus cross-boundary edges from inputs to child's start node
- `_render_external_outputs(child_ir, lines, indent, node_id, prefix, outgoing_map, child_outgoing_map)` — renders dashed wrapper subgraph with output stadiums, parses source fields for producing-node→output edges, populates `outgoing_map`
- `_generate_batch_item_data_flow(node, expanded_items, lines, indent, prefix, sibling_node_ids)` — generates data-flow edges from parent batch node's params to each expanded item's input nodes

**Modified functions:**
- `_render_workflow` — added `suppress_io` param, returns `outgoing_map` for parent access
- `_render_subgraph` — added `suppress_io` param, returns child's `outgoing_map`
- `_render_node` — sub-workflow expansion now renders external IO (input wrapper → subgraph with suppress_io=True → output wrapper), passes child's `outgoing_map` to `_render_external_outputs`
- `_render_batch_inline` — added `sibling_node_ids` and `data_flow_targets` params, calls `_generate_batch_item_data_flow` after rendering
- `_try_expand_batch_item` — returns `Optional[dict]` (child IR) instead of `bool`, so `_render_batch_inline` can access child inputs for data-flow edge generation
- `_render_edge` — batch item data-flow suppression: when a fork_join_map target has ALL expanded items in `data_flow_targets`, suppress the structural edge entirely

**Deleted:**
- `_populate_outgoing_map` — replaced by `_render_external_outputs` which does both rendering and map population
- `_render_legend` — removed earlier (dead code after legend was dropped)

**Preserved unchanged:**
- `outgoing_map`, `incoming_map`, `data_flow_targets` — same routing logic, same IDs
- `_generate_data_flow_edges`, `_resolve_ref_source`, `_extract_batch_source` — same data-flow edge generation
- `_resolve_edge_endpoints` — same structural edge routing
- All batch, fork/join, decision detection, shape mapping, styling logic

### Critical Implementation Details

#### Nested outgoing_map scoping

`_render_external_outputs` for create-songs needs to route through choose-chorus's output nodes. But choose-chorus's `outgoing_map` entries are built inside create-songs' `_render_workflow` call — a different scope than the parent's `_render_external_outputs`.

**Fix**: `_render_workflow` returns its `outgoing_map`. `_render_subgraph` captures and returns it. `_render_node` passes it as `child_outgoing_map` to `_render_external_outputs`. The output source-field parser checks `child_outgoing_map` first, then falls back to the parent's `outgoing_map`.

Without this fix: edges from choose-chorus to create-songs' outputs connect to the choose-chorus subgraph BOX instead of routing through choose-chorus's specific output nodes (e.g., `choose-chorus__out_winning_chorus`).

#### Batch item data-flow edge suppression

Batch items that receive data-flow edges (e.g., `write-lyrics → emotional-architecture__in_lyrics`) also receive structural edges through `fork_join_map` (e.g., `write-lyrics → emotional-architecture`). This creates duplicate connections — every input gets TWO edges from the same source.

**Fix**: `_generate_batch_item_data_flow` returns a set of item mermaid IDs that received data-flow edges. These are added to `data_flow_targets`. In `_render_edge`, when a structural edge's target is in `fork_join_map`, check if ALL expanded items are in `data_flow_targets` — if so, suppress the entire structural edge.

The suppression must check ALL items (not just one) because partial suppression would leave some items connected via structural edge and others via data-flow edge, creating inconsistency.

#### Mermaid ID convention is load-bearing

External IO nodes use the SAME mermaid ID convention as internal IO: `{prefix}{node_id}__in_{name}` for inputs, `{prefix}{node_id}__out_{name}` for outputs. This is critical — all routing maps, data-flow edges, and structural edge routing use these IDs. Changing the convention would break everything.

#### `suppress_io` prevents end node regression

When the parent handles IO externally, the child's `_render_workflow` has no `output_ids` (internal outputs aren't rendered). Without `suppress_io`, `_render_end_nodes_and_edges` would generate end nodes (condition: `decision_nodes and not output_ids`). The `suppress_io` flag explicitly prevents this: "my parent handles terminals via output wrappers, don't add end nodes."

This was the #1 regression in the failed first attempt — end nodes reappeared because the suppression mechanism didn't exist.

### Cleanup Done

- Removed dead `_render_legend` function (13 lines)
- Fixed `_find_terminal_nodes` double-call in `_render_end_nodes_and_edges` (computed twice with same args)
- Changed `_SUBGRAPH_FILLS` from dark-theme-only hex values to neutral grays that work on both themes (Mermaid doesn't support `rgba()`)
- Removed `color:#fff` from `_subgraph_style` (text color now inherits from theme)
- Deleted `_populate_outgoing_map` (replaced by `_render_external_outputs`)

### Traps for Future Agents

1. **Don't remove the routing maps.** `outgoing_map`, `incoming_map`, `data_flow_targets` look like they should be unnecessary with external IO. They're not — structural edges still route through them for output→input name matching and fork/join fan-out. Removing them was the #1 cause of the failed first attempt.

2. **Don't change the mermaid ID convention.** IDs like `{prefix}{node_id}__in_{name}` are referenced by routing maps, data-flow edges, and structural edge routing. Every component agrees on this convention. Changing it requires updating ALL consumers.

3. **`_render_workflow` return value is essential.** It returns `outgoing_map` so the parent can route edges through nested sub-workflow outputs. Forgetting to capture and pass this causes edges to connect to subgraph boxes instead of output nodes.

4. **Batch item suppression checks ALL items.** The `all(ft in data_flow_targets for ft in fork_targets)` check ensures structural edges are only suppressed when EVERY expanded item has data-flow coverage. Partial suppression would create inconsistent visual connections.

5. **`suppress_io` and end nodes are coupled.** If you change the end node logic, check `suppress_io`. If you change when IO is rendered externally, check end node generation. They're two sides of the same coin.

6. **Internal IO still exists for batch item sub-workflows.** Expanded batch items (via `_try_expand_batch_item`) call `_render_workflow` with default `suppress_io=False`, so they get internal IO. Only top-level sub-workflow expansion (in `_render_node`) uses `suppress_io=True`. This is intentional — giving batch items external IO would create 3 wrapper subgraphs per item for what are often single-node pipelines.

## Post-Refactor Fixes (2026-04-06, same session)

### Batch item output routing

**Problem**: Structural edges from expanded batch items (emotional-architecture → format-emotional-reviews) went to the item's subgraph BOX instead of routing through the item's output node (`review_text`).

**Root cause**: `_resolve_edge_endpoints` checks `outgoing_map` for the ORIGINAL from_id (the batch node `emotional-reviews`), which has no outputs. After fork_join_map expansion to individual items, each item's outgoing_map entries were never checked.

**Two fixes required**:

1. **Populate outgoing_map for batch items** — in `_render_batch_inline`, after each item is expanded via `_try_expand_batch_item`, populate `outgoing_map[item_mermaid_id]` with the child IR's declared output IDs. Required passing `outgoing_map` as a new parameter to `_render_batch_inline`.

2. **Check outgoing_map after fork_join expansion** — in `_resolve_edge_endpoints`, after expanding via fork_join_map, check each expanded item against outgoing_map. If an item has outputs, route through them instead of the subgraph box. Before: returned `[(fid, tid) for fid in from_ids for tid in to_ids]`. After: loops through from_ids, checks `outgoing_map.get(fid)`, routes through outputs when present.

### Batch item data-flow edge suppression

**Problem**: Expanded batch items with data-flow edges (e.g., `write-lyrics → emotional-architecture__in_lyrics`) also received structural edges through fork_join_map (`write-lyrics → emotional-architecture`). Duplicate connections.

**Fix**: `_generate_batch_item_data_flow` returns a set of item mermaid IDs that received data-flow edges. Added to `data_flow_targets`. In `_render_edge`, when a structural edge's target is in fork_join_map, suppress if ALL expanded items are in `data_flow_targets`. Required passing `data_flow_targets` as a new parameter to `_render_batch_inline`.

### Mermaid `procs` shape for batch nodes

**Discovery**: Mermaid v11+ supports `@{ shape: procs }` — renders as stacked rectangles, visually communicating "runs multiple times." Incompatible with `:::classDef` syntax, requires `style` directives instead.

**Applied to**:
- Dynamic batch single nodes (`curate-briefs`, `score-choruses`, `save-outputs`) — stacked rectangles replace regular shapes
- Ellipsis nodes (`... x6`) inside fork/join subgraphs — stacked rectangles instead of plain rectangles

**Implementation**: `_classdef_to_style(css_class)` helper converts classDef name to inline style string. Uses `_CLASSDEF_STYLES` lookup dict (single source of truth shared with `_render_classdefs`).

### Dynamic batch variable names

**Change**: `(parallel xN)` → `(parallel x|sources|)` using actual source variable from template ref.

`_dynamic_batch_label` extracts the first segment of `${ref.field}` via `_PARAM_REF_RE`. Examples:
- `${sources}` → `x|sources|`
- `${fetch-sources.results}` → `x|fetch-sources|`
- `${build-grouped-items.result.items}` → `x|build-grouped-items|`

**Pipe escaping**: The `|` delimiters must NOT be escaped by `_escape_label`. Fixed in both `_format_label` (appends batch suffix after escaping the main label) and `_render_subgraph` (escapes node_id separately, concatenates batch label raw).

### Traps for Future Agents (addendum)

7. **`outgoing_map` must be passed to `_render_batch_inline`.** Without it, expanded batch items have no output routing entries, and structural edges go to subgraph boxes instead of output nodes.

8. **`_resolve_edge_endpoints` must check outgoing_map after fork_join expansion.** The original from_id (batch node) won't be in outgoing_map — only the expanded items will. Check each `fid` in the expanded `from_ids` list.

9. **`procs` shape can't use `:::classDef`.** Use `style` directives via `_classdef_to_style()`. If you add new shapes that use `@{}` syntax, they need the same treatment.

10. **Batch suffix `|` delimiters bypass `_escape_label`.** The pipe characters in `x|sources|` must survive for Mermaid rendering. Both `_format_label` and `_render_subgraph` append the batch suffix AFTER escaping the rest of the label.

## Additional Improvements (2026-04-06, continued)

### Top-level workflow output rendering

Added `_render_top_level_outputs` — renders workflow outputs as a dashed wrapper subgraph at the bottom of the graph. Same pattern as sub-workflow external outputs (source-field parsing connects producing nodes to output nodes). The lyrics-generator shows `report` output connected from `build-report`.

Top-level outputs are rendered at `current_depth == 0` in `_render_workflow`, after the node loop. When top-level outputs exist, they replace end nodes (same `output_ids` mechanism as sub-workflow outputs).

### Smart top-level input connections

Replaced blind "all inputs → first node" with data-flow-based connections. New functions:

- `_connect_top_level_inputs(ir, lines, incoming_map)` — orchestrator, called from `_render_workflow` after all nodes rendered (so `incoming_map` is populated)
- `_connect_input_from_params(node, inputs, in_dict, mermaid_id, lines, connected)` — scans node params for `${input_name}` refs, connects to matching input wrapper or node
- `_connect_input_from_batch(node, inputs, in_dict, mermaid_id, lines, connected)` — scans `batch.items` template ref for input refs
- `_collect_param_refs(params)` — collects string values from params including nested dicts (code node `inputs` dict)
- `_refs_input(value, input_name)` — checks if a string contains `${input_name}` or `${input_name.`

**Result**: `sources` connects to `fetch-sources__in_source` (the sub-workflow's input wrapper), `output_base` connects to `build-file-list` (where it's actually used). Neither blindly connects to the first node.

**Nested params discovery**: Code nodes store their declared inputs as `params.inputs` (a dict of `{name: "${ref}"}`). `_collect_param_refs` recurses one level into nested dicts to find these refs. Without this, `output_base: ${output_base}` inside `params.inputs` was invisible.

### Mermaid `procs` shape for ellipsis nodes

The `... x6` ellipsis nodes in fork/join subgraphs (representing truncated batch items >4) now use `@{ shape: procs }` (stacked rectangles) instead of plain rectangles. Matches the `procs` shape used for dynamic batch single nodes. Styled via `style` directive (same `_classdef_to_style` mechanism).

### Failed: Batch output structural edge suppression (Change 1)

**Goal**: For batch sub-workflows (create-songs with 13 outputs), stop fanning structural edges through ALL outputs to the next node. Outputs should be informational only (connected from internal producing nodes, NOT to downstream).

**Four attempts, all failed.** See `scratchpads/mermaid-improvements/change1-failed-analysis.md` for detailed analysis.

**Root cause**: `outgoing_map` is a shared signal, not just routing data. Three functions read it for different purposes:

1. `_resolve_edge_endpoints` — decides HOW to route structural edges (fan through outputs vs direct)
2. `_resolve_ref_source` — decides WHETHER to generate data-flow edges (skips when source has outputs, because "structural edge handles it")
3. `_render_edge` — decides whether suppression applies (source not in outgoing_map)

Modifying `outgoing_map` contents (filtering, popping entries) changes all three behaviors simultaneously. Every attempt to suppress output fan-out for batch nodes had cascading side effects that broke data-flow edge generation or structural edge suppression elsewhere.

**The fundamental tension**: `outgoing_map` serves two conflicting purposes for batch nodes:
- Routing structural edges through outputs (we want to STOP this for batch)
- Signaling `_resolve_ref_source` to skip data-flow edges (we want to KEEP this)

These can't be separated without splitting the map into two separate data structures (routing vs signal), which is a deeper refactor.

**Status**: Accepted as known limitation. The 13-output fan for create-songs is the only visual issue. Everything else works correctly. See analysis doc for unverified approaches that might work in the future.

### Traps for Future Agents (addendum)

11. **`outgoing_map` is a shared signal, not just data.** `_resolve_ref_source` reads it to decide whether to SKIP data-flow edge generation. Removing entries doesn't just change routing — it enables data-flow edges that were previously suppressed, creating new cross-connections that destroy dagre layout.

12. **Long-range edges destroy dagre layout.** Any edge that skips pipeline stages (e.g., `input_sources → prepare-brief-inputs` jumping over 6 intermediate nodes) can scatter the entire diagram. `_connect_top_level_inputs` must only connect to the NEAREST consuming node with matching input wrappers, not to every node that references the input.

13. **Nested params in code nodes.** Code node declared inputs live at `params.inputs` (a nested dict), not at the top level of `params`. `_collect_param_refs` handles this by recursing one level into nested dicts. Without this, top-level inputs referenced by code nodes are invisible to `_connect_top_level_inputs`.

14. **Always render and visually verify.** String-level checks (grep) can confirm "correct" edges while the rendered diagram is catastrophically broken. The lyrics-generator mermaid output MUST be rendered in mermaid.live after every change.

## Known Limitations

1. **Batch sub-workflow output fan**: create-songs' 13 outputs all fan to prepare-evaluation via structural edge routing. Can't be fixed without splitting `outgoing_map`'s dual purpose (routing vs signal).

2. **`_connect_top_level_inputs` is first-consumer-only**: Each top-level input connects to the first node that references it. If an input is referenced by multiple nodes at different pipeline stages, only the first connection is shown. Connecting to all consumers would create long-range edges that destroy layout.

## Code Review Fixes (2026-04-06, PR #228 review)

Addressed findings from automated code review (Google Code Review Agent + claude-code review agent). Most findings were disputed after evidence gathering — the reviewer misunderstood upstream guarantees or suggested changes that would produce worse behavior. Three substantive fixes and three minor cleanups.

### 1. Extracted `_connect_sources_to_output` helper (DRY fix)

**Problem**: Three functions contained identical 10-line source-field parsing loops:
- `_render_top_level_outputs` (lines 365-378)
- `_render_subworkflow_outputs` (lines 441-454)
- `_render_external_outputs` (lines 655-669)

All three: parse `source` with `_SOURCE_NODE_FIELD_RE.findall()`, filter by `node_ids`, compute `src_mid` with a prefix, look up in outgoing map(s), emit edge via 3-way routing decision (exact field match → single-output fallback → direct node fallback).

**Differences**: (a) ID prefix for `_to_mermaid_id` (empty, `prefix`, or `child_prefix`), (b) outgoing map lookup strategy (single map vs child→parent cascade in `_render_external_outputs`).

**Fix**: New `_connect_sources_to_output(source, out_mid, node_ids, id_prefix, lines, indent, *outgoing_maps)` — accepts varargs outgoing maps checked in order (first match wins). Three call sites reduced from ~10 lines each to 1-2 lines.

### 2. Removed dead `_SOURCE_NODE_RE` regex

`_SOURCE_NODE_RE` (captured node only, no field) was defined but never used anywhere. Superseded by `_SOURCE_NODE_FIELD_RE` (captures both node and field). Removed.

### 3. Fixed vacuous test assertion

`test_batch_item_template_workflow_not_expanded` line 720 asserted `'quality ("quality (workflow)")' not in out` — but that string (with a space before the paren) can never appear in Mermaid output. The assertion was vacuously true. Replaced with positive assertion: `'reviews__quality("quality (workflow)"):::workflow' in out`.

### 4. Minor cleanups

- **Em-dash consistency**: Two `--` in docstrings (`_try_resolve_child`, `_to_mermaid_id`) changed to `—` to match the file's dominant style (9 em-dash occurrences vs 2 double-dash).
- **Test phase numbering**: Added missing `Phase 6: Sub-workflow IO and data-flow edges` header between Phase 5 and Phase 7.
- **`_collect_param_refs` docstring**: Clarified that it goes one level deep intentionally (code node `params.inputs` is a nested dict), not "nested dicts" generically.

### Disputed review findings (no action)

| Finding | Why disputed |
|---------|-------------|
| `re.match` → `re.search` in `_first_sentence` | Input is pre-stripped by markdown parser (`line.strip()` at parse time). Even without stripping, whitespace matches `[^.!?]` so `re.match` works. `re.search` could return mid-text fragments in edge cases — worse behavior. |
| Tests import private functions | Direct testing of `_deduplicate_edges`, `_detect_decision_nodes`, etc. is valuable — they have specific isolated logic. Making them public is a worse API decision. Standard Python practice. |
| Hardcoded local paths in implementation-plan.md | Internal `.taskmaster/` artifact, not user-facing docs. The path is intentional context for the developer. |
| `_first_sentence` mid-word truncation at 80 chars | Diagram labels — not worth the complexity for a rare cosmetic edge case. |
| Duplicate `_find_terminal_nodes` test | Reviewer cited non-existent line numbers (file is 1173 lines, reviewer cited 2083). The test at line 763 combines integration smoke check + unit assertions for a specific edge case (error-only edges). Not redundant. |

## Post-Review Features (2026-04-06, same session)

### Markdown output wrapping (`-o diagram.md`)

When the `-o` output path ends with `.md`, the mermaid output is wrapped in a markdown document with the workflow's H1 title and description:

```markdown
# Workflow Title

Description prose from the H1 section.

```mermaid
graph TD
...
```​
```

`.mmd` output remains raw mermaid (no wrapping).

**Implementation**: Added `title: Optional[str]` and `description: Optional[str]` to `ResolvedWorkflow` in `result.py`. Populated from `MarkdownParseResult` in the two `workflow_resolver.py` paths that already call `parse_markdown` (`_try_load_from_file`, `_load_library_workflow`). The visualize command checks the output extension and wraps accordingly. Falls back to filename stem when title is unavailable (dict/content sources).

### Subgraph descriptions with `--descriptions`

When `--descriptions` is enabled, expanded sub-workflow subgraph labels now include the node's purpose (first sentence), matching the behavior of regular nodes:

```
subgraph fetch-sources ["fetch-sources (workflow)<br/>Fetches content from multiple source types."]
```

**Implementation**: Added `purpose` parameter to `_render_subgraph`, passed from the call site in `_render_node` where `purpose = node.get("purpose", "")` is already available. Appends `<br/>{_first_sentence(purpose)}` to the subgraph label when `descriptions=True` and purpose is non-empty.

### Theme-safe subgraph depth coloring (`fill-opacity`)

Replaced hardcoded light-theme hex fills (`#f5f5f5`, `#ebebeb`, etc.) with `fill:#808080,fill-opacity:N` — a neutral gray overlay that darkens on light backgrounds and lightens on dark backgrounds. Verified in mermaid.live on both themes.

**Depth levels**: 0.07, 0.14, 0.21, 0.28 (progressively more contrast at deeper nesting).

**IO wrappers**: `fill:#808080,fill-opacity:0.04` (subtler than depth fills, with `stroke-dasharray:4 4`).

**Why this works**: Mermaid generates SVG, and SVG natively supports `fill-opacity` as a separate property from `fill`. `rgba()` is NOT supported by Mermaid's style parser, but `fill-opacity` passes through correctly.

### Nested sub-workflow output routing test

Added `test_nested_subworkflow_output_routes_through_child_output` — verifies that when an outer sub-workflow's output references an inner sub-workflow's output (e.g., `source: ${choose-chorus.winning_chorus}`), the edge routes through the inner's specific output node (`out_winning_chorus`), not through the inner subgraph box. This is the only test that exercises the two-map cascade in `_connect_sources_to_output` — the mechanism that was the focus of the most debugging effort in the original implementation.

## Final State

### Files Modified
| File | Lines |
|------|-------|
| `src/pflow/core/workflow/mermaid.py` | ~1440 (from 163) |
| `src/pflow/cli/commands/visualize.py` | 105 (from 92) |
| `src/pflow/execution/result.py` | +2 lines (title, description fields) |
| `src/pflow/execution/workflow_resolver.py` | +5 lines (populate title, description) |
| `tests/test_core/test_mermaid.py` | ~1200 (from 392) |
| `tests/test_cli/test_visualize.py` | ~255 (from 199) |

### Test Counts
- `test_mermaid.py`: 55 tests (15 original updated + 40 new)
- `test_visualize.py`: 10 tests (7 original + 3 new)
- Full suite: 65 mermaid + visualize tests passing
- `make check`: clean (ruff, mypy, deptry)
