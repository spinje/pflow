# Task 146: Rich Mermaid Visualization — Batch Semantics, Node Typing, and Flow Clarity

## Description

Improve the Mermaid workflow visualization (from Task 145) to surface batch/fan-out semantics, use standard flowchart shapes for node types and decision points, eliminate visual noise (duplicate edges), and show data flow across sub-workflow boundaries. Tested against a complex real-world workflow (lyrics-generator: 15 top-level steps, 4 sub-workflows, 7 nested sub-sub-workflows, batch operations at every level).

## Status

done

## Completed

2026-04-06

## What Was Actually Built

The implementation evolved significantly beyond the original spec through iterative visual review. Key additions not in the original plan:

- **External IO wrappers** — sub-workflow inputs/outputs rendered as dashed wrapper subgraphs OUTSIDE the pipeline subgraph, replacing internal IO. Cross-boundary edges connect inputs to internal start nodes and internal producing nodes to outputs.
- **Data-flow edges from template refs** — param template refs (`${node.field}`) parsed to generate edges showing actual data provenance, not just execution order. Structural edges suppressed when data-flow covers the connection.
- **Batch item data-flow edges** — parent batch node's params generate edges to each expanded item's input nodes (e.g., `write-lyrics → emotional-architecture__in_lyrics`).
- **Mermaid `procs` shape** (stacked rectangles) for dynamic batch nodes and ellipsis nodes — visually communicates "runs multiple times."
- **Dynamic batch variable names** — `(parallel x|sources|)` instead of `(parallel xN)`, showing actual source.
- **Top-level workflow outputs** — rendered as dashed wrapper at the bottom, connected from producing nodes.
- **Smart top-level input connections** — inputs connect to actual consuming nodes via param analysis, not blindly to the first node.
- **Legend removed** — shapes and colors are self-explanatory with type labels.
- **Sub-workflow outputs replace end nodes** — `content` and `source_type` are more meaningful than `(("end"))`.

See `implementation/progress-log.md` for the full evolution, design decisions, and traps for future agents.

## Priority

high

## Problem

The current mermaid generator produces topologically correct but visually flat diagrams. Testing against the lyrics-generator workflow revealed 14 issues where the visualization erases critical architectural information:

1. **Batch semantics invisible** — `create-songs` runs 4 song pipelines in parallel, `analyze` runs 6 specialist LLM calls, `emotional-reviews` runs 3 review workflows — all render as single nodes. The fan-out/fan-in pattern is the core architectural story of the workflow, and the chart completely erases it.

2. **Duplicate edges** — When a code node has AST-scanned `next: str = "target"` AND is followed by that target in document order, both a document-order edge (no `action` key) and a named action edge appear. Example: `classify --> fetch-youtube` renders twice.

3. **No terminal indicator** — Nodes with `- next: end` (all branch endpoints in fetch-source) just dead-end. No visual marker distinguishing intentional termination from missing edges.

4. **MCP type labels too long** — `mcp-klavis-youtube-get_youtube_video_transcript` makes nodes extremely wide.

5. **No node type differentiation** — LLM, code, shell, MCP, workflow, and write-file nodes all render as identical rectangles. No shapes, no colors.

6. **No decision node shapes** — Routing nodes (like `classify` with 4 conditional branches) render as plain rectangles instead of diamonds.

7. **No workflow inputs shown** — The chart starts at the first node with no indication of what feeds the pipeline.

8. **Template workflow refs in batch prevent expansion** — `emotional-reviews` uses `workflow: ${item.workflow}` so the resolver returns None. But the batch items contain literal paths (`./reviews/review-emotional-architecture.pflow.md`). The data IS available, just not used.

9. **No color legend** — Even with type differentiation, there's no key explaining what shapes/colors mean.

10. **No `--descriptions` flag** — Node purposes are available in the IR (`node["purpose"]`) but not surfaced in the chart.

## Solution

Modify `src/pflow/core/workflow/mermaid.py` and `src/pflow/cli/commands/visualize.py` to produce rich, standards-compliant flowcharts:

### Batch Representation (BPMN multi-instance pattern)

- **Batched sub-workflows** (create-songs ×N): Subgraph labeled `"name (parallel ×N)"`, internal pipeline shown once
- **Small static named batches ≤4** (3 reviewers): Fork/join showing each item by name
- **Large static named batches >4** (6 analysts): Show 2 named items + `⋯ ×6` ellipsis node
- **Dynamic batches** (score-choruses): `×N` in node label
- **Non-parallel batches**: Same patterns but labeled `×N` without "parallel"

### Standard Flowchart Shapes

- Diamond `{"..."}` — decision/routing nodes (≥2 non-error named action edges)
- Rectangle `["..."]` — process nodes (default)
- Stadium `(["..."])` — LLM nodes (distinctive, suggests "processing/thinking")
- Subroutine `[["..."]]` — shell nodes (suggests external command)
- Hexagon `{{"..."}}` — MCP nodes (suggests external service)
- Cylinder `[("...")]` — write-file nodes (suggests storage)
- Parallelogram `[/"..."/]` — input nodes
- Circle `(("end"))` — terminal marker

### Other Improvements

- Duplicate edge suppression
- End nodes for branching workflows
- MCP type formatting with `<br/>`
- classDef color coding with legend subgraph
- Top-level input nodes
- `--descriptions` CLI flag
- Back-edge support verification

## Design Decisions

- **Shapes encode flow semantics, colors encode node type**: Shapes (diamond, rectangle, stadium, etc.) tell you what role a node plays in the flow. Colors via classDef provide additional type scannability for renderers that support CSS. Both work independently — shapes are universal, colors are a bonus.

- **Keep type in labels**: Even though shapes indicate type, the label still includes `(type)` for clarity when shapes are ambiguous or the renderer doesn't support them well. Example: `classify["classify (code)"]` with diamond shape.

- **BPMN multi-instance + Mermaid `procs` shape**: Mermaid v11+ supports `@{ shape: procs }` (stacked rectangles) for dynamic batch single nodes. Batched sub-workflows use `parallel x|source|` wrapper subgraphs. Combined, these immediately communicate "runs multiple times."

- **Fork/join for small named batches**: When there are ≤4 inline items with meaningful names (3 reviewers: emotional-architecture, narrative, imagery), show all items explicitly with fork/join edges. The names carry important semantic information worth the extra nodes.

- **Actual variable names for dynamic batches**: `(parallel x|sources|)` instead of `(parallel xN)` — shows where the batch items come from. Extracted from the first segment of the `batch.items` template ref.

- **Decision = ≥2 non-error named action edges**: A node with multiple conditional `next` targets is a decision. Error edges (`on-error`) don't count — error handling isn't a routing choice. Document-order edges (no `action` key) don't count either.

- **Outputs replace end nodes in sub-workflows**: Sub-workflow outputs (`content`, `source_type`) are more meaningful than `(("end"))`. Output nodes are connected from their producing internal nodes via source-field parsing. End nodes only appear for top-level branching workflows without declared outputs.

- **External IO wrappers for all expanded sub-workflows**: Inputs and outputs render as dashed wrapper subgraphs OUTSIDE the pipeline subgraph, at the parent scope. This enables cross-boundary data-flow edges and makes IO visible at a glance. All expanded sub-workflows get external IO — no batch exception.

- **Data-flow edges from template refs replace structural edges**: Param refs (`${node.field}`) generate edges showing actual data provenance. Structural edges are suppressed when data-flow covers the connection. This shows WHERE data comes from, not just what runs after what.

- **Top-level outputs rendered**: Workflow outputs appear as a dashed wrapper at the bottom, connected from producing nodes. Shows what the pipeline ultimately produces.

- **Top-level inputs connect to actual consumers**: Inputs connect to the node that references them via param analysis, not blindly to the first node. `output_base` connects to `build-file-list`, not to `fetch-sources`.

- **MCP type: keep full path, format readably**: The tool path is important context. Use `<br/>` line breaks to prevent excessively wide nodes.

- **Descriptions as opt-in flag**: `--descriptions` adds the first sentence of `node["purpose"]` to labels. Off by default because it creates visual overload for complex workflows (40+ nodes).

## Dependencies

- Task 145: Mermaid Workflow Visualization — the foundation this builds on (completed, merged)

## Requirements

### Batch Indication

- Nodes with `batch` config must show batch semantics in the visualization
- Static inline items (`batch.items` is a list): show count or individual items
- Dynamic items (`batch.items` is a template string): show `×N`
- `batch.parallel: true` must be indicated (e.g., "parallel ×N" vs "×N")
- Fork/join pattern for ≤4 inline named items: show each item by name with fan-out/fan-in edges
- Parallel ×N wrapper subgraph for batched sub-workflows: internal pipeline shown once
- For >4 inline items: show 2 representative items + `⋯ ×count` ellipsis node
- Item labels extracted from batch item dicts using heuristic: `focus` > `lens` > `name` > `label` > first short string value

### Template Workflow Refs in Batch

- When `params.workflow` is a template ref (e.g., `${item.workflow}`) but `batch.items` is an inline list with literal `workflow` paths, the generator must resolve each item's workflow individually
- Each resolved sub-workflow renders as a separate node in the fork/join pattern
- If resolution fails for an item, render that item as an opaque node (graceful degradation)

### Duplicate Edge Suppression

- When a `(from, to)` pair has both a document-order edge (no `action` key) and a named action edge (has `action` key), suppress the document-order edge
- Error edges (`action: "error"`) are never suppressed
- `action: "default"` edges are suppressed if a named action edge exists for the same pair

### Terminal Indicators

- Nodes with zero outgoing edges in a workflow that contains decision nodes get connected to an `(("end"))` node
- Simple linear pipelines (no decision nodes) do NOT get end markers
- One shared end node per workflow/subgraph scope
- The end node uses circle shape `(("end"))`

### Node Type Differentiation

- Each node type renders with a distinct Mermaid shape:
  - `code` → rectangle `["..."]` (default process)
  - `llm` → stadium `(["..."])`
  - `shell` → subroutine `[["..."]]`
  - `mcp*` → hexagon `{{"..."}}`
  - `write-file` → cylinder `[("...")]`
  - `workflow` (opaque, not expanded) → rounded rectangle `("...")`
- Node type remains in the label text: `name (type)`
- classDef color styling applied per type (works in renderers that support CSS)

### Decision Node Shapes

- Nodes with ≥2 outgoing edges with distinct named actions (excluding `action: "error"` and `action: "default"` and edges with no `action` key) render as diamonds `{"..."}`
- Decision shape overrides the type-based shape (a code node that routes is a diamond, not a rectangle)

### MCP Type Formatting

- MCP node types (`mcp-server-tool`) formatted with `<br/>` for readability
- Full tool path preserved (not truncated)
- Example: `fetch-youtube-mcp<br/>(mcp: klavis-youtube/get_transcript)`

### Workflow Inputs

- Top-level workflow inputs from `ir["inputs"]` rendered as parallelogram nodes `[/"..."/]`
- Show input name and type: `[/"sources (array, required)"/]`
- Connected to actual consuming nodes via param/batch analysis (not blindly to first node)
- Sub-workflow inputs rendered as external dashed wrappers (part of external IO)

### Workflow Outputs

- Top-level workflow outputs rendered as dashed wrapper subgraph at the bottom
- Connected from producing nodes via source-field parsing
- Sub-workflow outputs rendered as external dashed wrappers (part of external IO)

### CLI Changes

- New `--descriptions` flag (default: off): adds first sentence of `node["purpose"]` to node labels via `<br/>`
- Existing flags (`--depth`, `--direction`, `-o`) unchanged

### Back-Edge Support

- Edges where `to` references a node earlier in the pipeline (loops/retries) must render correctly
- No special styling needed — Mermaid's layout engine handles upward-curving arrows naturally
- Add test coverage to verify

## Implementation Notes

### IR Data Locations (verified)

- Batch config: `node["batch"]` (top-level, sibling to `params`, NOT inside params)
- Batch items: `node["batch"]["items"]` — `list` for inline, `str` for template ref
- Batch parallel: `node["batch"]["parallel"]` — boolean, defaults to False
- Node description: `node["purpose"]` — populated from prose between H3 heading and first `- key:`
- Workflow inputs: `ir["inputs"]` — dict of `{name: {description, type, required, default}}`
- Edge action: `edge.get("action")` — absent for document-order, `"default"` for explicit, string for named

### Decision Node Detection

Count edges where `from == node_id` AND `action` key exists AND `action not in ("error", "default")`. If count ≥ 2, it's a decision node. Verified: `classify` has 4 named actions (fetch-youtube, fetch-webpage, read-file, pass-text) → diamond. `fetch-youtube` has only 1 error edge → NOT a decision.

### Item Label Extraction Heuristic

Batch item dicts in the lyrics-generator use these keys consistently:
- `focus` for reviews (`"emotional-architecture"`, `"narrative"`, `"imagery"`)
- `focus` for analysts (`"emotional"`, `"details"`, `"narrative"`, etc.)
- `lens` for concept generators (`"heart"`, `"mind"`, `"body"`, `"full"`)

Priority: `name` > `label` > `focus` > `lens` > first string value ≤30 chars (excluding `workflow`, `prompt`, `command`)

### Edge Deduplication Logic

```python
# Build set of (from, to) pairs that have named action edges
named_pairs = {(e["from"], e["to"]) for e in edges if "action" in e}
# Filter: keep edge if it has an action key OR its (from, to) isn't in named_pairs
filtered = [e for e in edges if "action" in e or (e["from"], e["to"]) not in named_pairs]
```

### Fork/Join Edge Rerouting

When a batch node renders as fork/join with individual items:
- Incoming edges to the batch node → fan out to each item node
- Outgoing edges from the batch node → fan in from each item node
- The batch node ID is replaced by the individual item node IDs in the edge list

### Template Workflow Resolution from Batch Items

For nodes where `params.workflow` is `${item.workflow}` and `batch.items` is an inline list:
1. Iterate over each item in the batch items list
2. Check if item has a `workflow` key with a literal (non-`${`) path
3. If so, call `resolve_sub_workflow({"workflow": item["workflow"]}, base_path)`
4. Render each resolved sub-workflow as a node in the fork/join pattern

### Files to Modify

- `src/pflow/core/workflow/mermaid.py` — main generator (currently 163 lines)
- `src/pflow/cli/commands/visualize.py` — add `--descriptions` flag
- `tests/test_core/test_mermaid.py` — add tests for all new features
- `tests/test_cli/test_visualize.py` — add test for `--descriptions` flag

## Verification

### Concrete Test Case

The primary verification target is the lyrics-generator workflow at `/Users/andfal/projects/music-generation/workflows/lyrics-generator/lyrics-generator.pflow.md`. The improved output must show:

1. `fetch-sources` with external IO wrappers (input: `source`, outputs: `content`, `source_type`), diamond `classify` → 4 named branches → error fallback, NO end nodes
2. `analyze-sources` with external IO, `analyze` inside as fork/join for 6 specialists (2 shown + `... x6` procs node)
3. `choose-concepts` with external IO (inputs: `analyses`, `brief`; outputs: `selected_concepts`, etc.), fork/join for 4 lenses
4. `create-songs` with external IO, full internal pipeline including:
   - `choose-chorus` with nested external IO
   - `emotional-reviews` as fork/join with batch item data-flow edges from `write-lyrics` to each item's inputs
   - `craft-reviews` as fork/join with batch item data-flow edges
5. `classify` node as diamond shape (4 conditional branches)
6. All LLM nodes as stadium shapes, shell as subroutine, MCP as hexagon
7. `sources` connected to `fetch-sources__in_source` (not the subgraph box), `output_base` connected to `build-file-list`
8. No duplicate `classify --> fetch-youtube` edge
9. Dynamic batch nodes (`curate-briefs`, `score-choruses`, `save-outputs`) as `procs` (stacked rectangles) with variable names
10. Top-level `report` output at the bottom connected from `build-report`
11. Data-flow edges through output wrappers (e.g., `fetch-sources__out_content → analyze-sources__in_content`)

### Unit Tests (53 total)

All original task 145 tests updated + new tests covering:
- Batch fork/join, ellipsis, dynamic label, edge rerouting
- Decision nodes, node shapes, classDefs
- External IO wrappers, cross-boundary edges
- Data-flow edges from params, batch item data-flow
- Sub-workflow outputs replace end nodes
- Top-level outputs rendered
- `--descriptions` flag, back-edges
- **High-value regression tests**:
  - Suppression without replacement keeps structural edge (silent disconnection guard)
  - External IO doesn't duplicate with internal IO (`suppress_io` propagation)
  - Top-level inputs connect to actual consumers (not blindly to first node)

### Regression

- All existing test_mermaid.py tests pass
- All existing test_visualize.py tests pass
- `make check` passes
- `make test` passes

## Known Limitations

1. **Batch sub-workflow output fan** — create-songs' 13 outputs all fan to prepare-evaluation via structural edge routing. Can't be fixed without splitting `outgoing_map`'s dual purpose (routing vs signal for `_resolve_ref_source`). See `scratchpads/mermaid-improvements/change1-failed-analysis.md` for 4 failed attempts and root cause analysis.

2. **`_connect_top_level_inputs` is first-consumer-only** — each top-level input connects to the first node that references it. Connecting to all consumers creates long-range edges that destroy dagre layout.

3. **`procs` shape can't use `:::classDef`** — requires `style` directives via `_classdef_to_style()`.

## References

- Mermaid generator: `src/pflow/core/workflow/mermaid.py` (~1444 lines)
- Visualize command: `src/pflow/cli/commands/visualize.py` (100 lines)
- Mermaid tests: `tests/test_core/test_mermaid.py` (~1100 lines, 53 tests)
- CLI tests: `tests/test_cli/test_visualize.py` (~216 lines, 8 tests)
- Progress log: `.taskmaster/tasks/task_146/implementation/progress-log.md`
- External IO prototype: `scratchpads/mermaid-improvements/external-io-prototype.mmd`
- Change 1 failure analysis: `scratchpads/mermaid-improvements/change1-failed-analysis.md`
- Cross-boundary edge test: `scratchpads/mermaid-improvements/cross-boundary-test.mmd`
- Test workflow: `/Users/andfal/projects/music-generation/workflows/lyrics-generator/lyrics-generator.pflow.md`
- Current output: `scratchpads/mermaid-improvements/lyrics-generator-v3.mmd`
