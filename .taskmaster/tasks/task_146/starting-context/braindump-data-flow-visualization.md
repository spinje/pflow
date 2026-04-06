# Braindump: Mermaid Visualization — Data Flow Evolution

## Where I Am

Implementation is functionally complete. All the planned features plus significant post-plan evolution are done. 4639 tests pass, `make check` clean. The lyrics-generator renders with accurate data-flow edges, source-traced outputs, batch semantics, depth coloring, and type-differentiated shapes.

The code is in a good state but the routing logic is complex (5 interacting maps). The user is satisfied with the direction but may want further refinement.

## User's Mental Model

The user evaluates visualizations by **comprehension, not aesthetics**. Their core question at every step was: "Can someone who doesn't know this workflow understand what data flows where?"

Key phrases they used repeatedly:
- "is this correct?" — they catch every false connection. Truth > prettiness.
- "what does this edge mean?" — every edge must have a defensible interpretation.
- "where does [X] come from?" — they think in terms of data provenance, not execution order.
- "lets discuss this before you implement anything" — they want to understand the design space before committing to code.

**How their understanding evolved**: They started by pointing at rendered diagrams and asking questions. Each question exposed a deeper issue. The progression was: "what does end mean" → "why aren't inputs connected" → "why does easter-eggs connect to all 4 inputs" → "where does lyrics come from" → "shouldn't the producing node connect to the output". Each was a natural consequence of the previous fix making a new problem visible.

**Their unstated priority**: The diagram should make the ARCHITECTURE of a workflow legible to someone seeing it for the first time. Batch parallelism, data provenance, and sub-workflow boundaries are the three things they care most about.

## Key Insights

**The inputs/outputs as separate boxes idea**: The user suggested rendering inputs/outputs OUTSIDE subgraphs as standalone nodes at the parent level, creating a clear visual boundary. I argued against it — `create-songs` has ~15 outputs, which would create massive clutter between the subgraph and `prepare-evaluation`. The user accepted this but the tension is unresolved. If someone revisits this, the compromise was: keep IO inside subgraphs but connect them accurately via data-flow edges and source-field parsing. The "separate boxes" idea might still be better for SIMPLE sub-workflows (1-2 inputs, 1 output) — a hybrid approach could work.

**Batch item sub-workflows have floating inputs**: The `emotional-reviews` items (emotional-architecture, narrative, imagery) expand as subgraphs with input parallelograms inside. But no data-flow edges connect to them because the batch parent's params use `${item.*}` refs (which we correctly skip) and we don't have a mechanism to trace per-item data flow. The params like `lyrics: ${write-lyrics.response}` ARE on the batch parent node, but `_generate_data_flow_edges` only fires for the parent subgraph, not for each expanded batch item inside. This is a known gap — the user noticed it (image #13) but we moved on to more impactful fixes.

**Multi-output subgraph routing is incomplete**: In `_resolve_ref_source`, when a sibling has >1 output, we fall back to the subgraph box because we can't determine which output without the field name. But we DO have the field name in the regex match — `_PARAM_REF_RE` captures the node ID but not the field. This could be fixed by capturing the field too (like `_SOURCE_NODE_FIELD_RE` does in `_render_subworkflow_outputs`) and matching against the outgoing_map. I didn't fix this because single-output routing covered the most common cases.

## Assumptions & Uncertainties

ASSUMPTION: Node params that match child input names are the child's inputs. This is true for workflow nodes but the reserved params list (`_RESERVED_PARAMS = {"workflow", "workflow_ir", "storage_mode", "type"}`) might be incomplete. If new reserved params are added to workflow nodes, they could create false data-flow edges.

ASSUMPTION: `batch.items` template refs always reference a sibling node (`${node.field}`). If they reference a parent input directly (`${input_name}`), `_extract_batch_source` won't find it in `sibling_node_ids`.

UNCLEAR: Should the edge label suppression (discussed early: suppress edge labels when `action == edge["to"]`) be implemented? It was mentioned but never done. The user's fetch-sources screenshot showed `fetch-youtube → fetch-youtube` looking redundant.

NEEDS VERIFICATION: The `_SUBGRAPH_FILLS` colors were picked for dark theme. Haven't tested on light themes. The `color:#fff` in `_subgraph_style` will make subgraph labels white — bad on light themes.

## Unexplored Territory

UNEXPLORED: The `_render_legend` function is still in the code (dead code since we stopped calling it). Should be cleaned up.

UNEXPLORED: Data-flow edges for batch item sub-workflows. When `emotional-reviews` expands 3 review sub-workflows, each has inputs (`lyrics`, `concept_brief`, etc.) but no edges connect to them. The parent's params have the refs (`lyrics: ${write-lyrics.response}`) but `_generate_data_flow_edges` runs at the parent batch node level, not inside the fork/join subgraph. A fix would need to: (1) for each expanded batch item, (2) map the parent's non-`${item.*}` params to the child's inputs, (3) generate edges from sibling nodes to each item's input nodes. This is the main remaining visual gap.

CONSIDER: The outgoing_map currently only handles subgraphs expanded via `_render_subgraph` (regular workflow nodes). Batch inline subgraphs rendered by `_render_batch_inline` don't populate outgoing_map. If a batch node has outputs, structural edges from it won't route through them.

MIGHT MATTER: Performance with very deep workflows. Each nesting level multiplies the parameter threading (16+ params to `_render_node`). For depth-5 with many sub-workflows, the line count can grow large (lyrics-generator produces ~300 lines of mermaid). Mermaid renderers can struggle with >500 nodes.

CONSIDER: The `style` directives for subgraph fills are emitted AFTER the `end` keyword but at the same indent level. Some Mermaid renderers might not support `style` on subgraphs. Tested on Mermaid.live — works. Not tested on GitHub's built-in mermaid renderer.

MIGHT MATTER: The `_SOURCE_NODE_FIELD_RE` regex `(?:^|[\s{?])([a-zA-Z0-9_-]+)\.([a-zA-Z0-9_-]+)` captures node ID and first field. But nested paths like `${node.sub.path}` only capture the first two segments. This is fine for current usage but could miss deeper paths.

## What I'd Tell Myself

1. **Start with data flow, not graph structure.** The initial plan treated this as "make the graph prettier." The real problem was "show where data comes from." If starting over, I'd build the data-flow edge system first and add shapes/colors after.

2. **Don't route structural edges through IO.** This was the biggest time sink. Three iterations (cross-product, name-matching, data-flow replacement) before getting it right. The insight is simple in hindsight: execution order edges and data flow edges are fundamentally different concerns.

3. **The user's questions ARE the spec.** Every "what does this mean?" pointed to a real design flaw. Don't explain away visual confusion — fix the underlying model.

4. **Test by rendering, not by string matching.** Many bugs were invisible in test assertions but obvious in rendered diagrams. The Mermaid output at `scratchpads/mermaid-improvements/lyrics-generator-v2.mmd` was the real test suite.

## Open Threads

1. **Batch item data-flow edges** — the main remaining visual gap. See UNEXPLORED above.
2. **Edge label suppression** — `classify -->|fetch-youtube| fetch-youtube` is redundant when label matches target. Discussed but not implemented.
3. **Multi-output field matching in _resolve_ref_source** — currently falls back to subgraph box for >1 outputs. Could capture the field name and match against outgoing_map.
4. **Light theme support** — subgraph fills and `color:#fff` are dark-theme-only.
5. **Dead code cleanup** — `_render_legend` function and the `_find_terminal_nodes` function (only used for top-level branching workflows without outputs now — could simplify).

## Relevant Files & References

- Implementation: `src/pflow/core/workflow/mermaid.py` (1019 lines)
- CLI: `src/pflow/cli/commands/visualize.py` (100 lines)
- Tests: `tests/test_core/test_mermaid.py` (1061 lines, 50 tests)
- CLI tests: `tests/test_cli/test_visualize.py` (216 lines, 8 tests)
- Progress log: `.taskmaster/tasks/task_146/implementation/progress-log.md` (comprehensive)
- Task spec: `.taskmaster/tasks/task_146/task-146.md`
- Test workflow: `/Users/andfal/projects/music-generation/workflows/lyrics-generator/lyrics-generator.pflow.md`
- Current output: `scratchpads/mermaid-improvements/lyrics-generator-v2.mmd`
- Song-creator sub-workflow: `/Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md` (key for understanding choose-chorus and emotional-reviews params)

## For the Next Agent

Start by reading the progress log at `.taskmaster/tasks/task_146/implementation/progress-log.md` — it documents every design decision and mistake. Then render `scratchpads/mermaid-improvements/lyrics-generator-v2.mmd` in a Mermaid viewer to see the current state.

The user's working pattern: they render the diagram, screenshot specific sections, and ask "what does this mean?" or "is this correct?". Always check the actual mermaid output against their question — don't guess.

The most impactful remaining improvement is connecting batch item sub-workflow inputs (UNEXPLORED above). The user noticed it but deferred.

Don't try to simplify the routing maps without fully understanding the interaction rules. Each map exists because a simpler approach produced wrong edges. The progress log's "Mistake 1" and "Mistake 2" sections explain why.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
