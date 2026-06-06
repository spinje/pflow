# Task 155 Review: Workflow Graph Model for Multi-Renderer Support

## Metadata

- **Implementation Date:** 2026-06-06 (single day; planning → phases 0–7 → 4-agent review → 7 review fixes → adversarial verification/hardening pass).
- **Branch:** `feat/workflow-graph-multi-renderer` (merge-base `a77e46bb`).
- **Branch commits:** `800cb5cd` (plan ready) → `8f5dfb5c` (plan) → `9deec140` (implementation + 4 reviews) → `99063155` (verification fixes).
- **Authoritative artifacts:** `implementation/implementation-plan.md` (build guide; §6 deviations table is canonical), `implementation/progress-log.md` (the journey), ADRs 0001/0003/0004.

## Executive Summary

Extracted a renderer-agnostic **GraphModel** from the text-in/text-out `mermaid/` package: one IR walk (`build_graph`) now produces pure-data dataclasses, and Mermaid became the first *renderer* over that model (`render_mermaid`). The ~1650-line Mermaid package was replaced by `graph/` (model + build + scope + renderer); `generate_mermaid()` survives as a thin compat shim so no external caller changed. This is the static "see" substrate for the planned React Flow web UI — it carries zero runtime/rendering state.

## Implementation Overview

### What Was Built

A `graph/` package under `core/workflow/`:

```
IR → build_graph() → GraphModel ─┬→ render_mermaid()   → str
                                 ├→ render_react_flow() → {nodes,edges,groups}  (future)
                                 └→ dataclasses.asdict  → JSON payload          (future)
```

- **`model.py`** — frozen dataclasses, no Mermaid syntax. Structural identity `NodeId(node_id, ancestor_path)` (ADR-0003); `AncestorStep(node_id, batch_index?)`. `Node`/`Edge`/`Container`/`LoopSpec`/`BatchSpec`/`IOPort`/`SourceRef`. `is_decision`/`is_terminal`/`shadowed`/`node` are **derived methods, not stored fields**. `__post_init__` enforces three invariants (unique ids, edge/host/member referential integrity, `Node.parent`↔`Container.members` bidirectional consistency).
- **`build.py`** — the single IR walk, structured as a per-level two-sub-pass (create all identities/containers/child-IO maps first, then resolve all edges). Recursion-stack cycle detection, sub-workflow expansion, batch (literal-all-items / leaf-as-data / dynamic-one-representative), `unexpanded` discriminator, data-flow inference.
- **`scope.py`** — only `refs_in`/`source_refs_in` (moved verbatim). `Scope.resolve`/`for_level` were **reimplemented structurally inside build**, not moved.
- **`renderers/mermaid.py`** — consumes only the model; derives flat IDs, shapes, classDefs, labels, batch truncation, end sink, suppression.
- **`mermaid/__init__.py`** — compat shim, exports only `generate_mermaid`. The 5 private modules (`_context/_edges/_io/_render/_scope.py`, ~1650 lines) were deleted.

### Deviations from the plan (the parts that matter most)

| Plan said | Actually shipped | Why |
|---|---|---|
| **Mermaid ignores `EdgeKind.END` edges**; derive sink purely from `is_terminal()`; "D2 adds zero Mermaid edges" | **Mermaid renders explicit END edges** to `pflow_end` (deduped against the terminal-sink so a node that's both isn't drawn twice) | Review found authored `next: end` routes were invisible in the first renderer. The model's structural truth should be visible. This **did shift two goldens** (`error-handling.mmd` +3, `generate-changelog.mmd` +2). |
| `node()` is "O(1) lookup (cache dict)" | `node()` is an **O(n) linear scan** (`model.py:126`); `_require_node` in build is also linear | Fine at current scale (82-node harness); no cache was added. See Technical Debt. |
| Node identity is `NodeId(node_id, ancestor_path)`, bare | IO nodes needed **synthetic `__inputs__`/`__outputs__` scope markers** in `ancestor_path` | Valid IR reuses one name for both an input and output (`generate-changelog` has `changelog_file` in both); bare `NodeId(name, path)` collided and tripped the uniqueness invariant. |
| Spec: heading-level `source` back-ref | Added **`Node.param_sources: dict[str, SourceRef]`** (review fix) | Click-to-read needs per-param origins (prompt/command/code), not just the node heading. |

Everything else tracked the plan: derived views over stored flags, structural identity, primitive-only (no analysis/SCC layer, ADR-0004), `resolve_child` as the one injected port.

## Files Modified/Created

### Core (new)
- `graph/model.py` (259) — the contract. Read this first.
- `graph/build.py` (781) — the only IR reader. Two-sub-pass walk; the 4-path data-flow reimplementation lives here.
- `graph/scope.py` (35) — pure ref extraction.
- `graph/renderers/mermaid.py` (886) — GraphModel → Mermaid; the most complex remaining code is `_resolve_edge_endpoints` (routing-map reconstruction) and `_assign_flat_ids` (collision dedup).
- `graph/__init__.py`, `graph/renderers/__init__.py`, `graph/CLAUDE.md`.

### Core (modified)
- `markdown_parser.py` (+24) — **Phase 0:** persist `_routes_to_end` at both write-sites (bullet `next: end` and AST code `next = "end"`). The single IR-contract change.
- `ir_schema.py` (+13) — whitelist `_routes_to_end` (mirrors `_source_*` convention) + **reject authored `end`/`__end__` node IDs** (review fix — stops programmatic IR colliding with the synthetic sink).
- `mermaid/__init__.py` — gutted to the shim; `mermaid/CLAUDE.md` rewritten as shim guidance; 5 private modules deleted.
- `cli/commands/visualize.py` (+2) — pass `source_file=` so root-workflow nodes carry a click-to-read pointer (children already got it from `SubWorkflowResult.path`).
- `core/CLAUDE.md`, `core/workflow/CLAUDE.md` — document `_routes_to_end` and repoint navigation at `graph/`.

### Docs (regenerated Mermaid blocks)
- `docs/reference/cli/index.mdx`, `plan-to-code/README.md`, `parallel-planner-review/README.md`. The parallel-planner README had **real semantic drift** — it described the old hand-wired counter loop; the workflow now uses a declarative `loop:` on `run-cycle`. Prose was corrected to match the rendered graph.

### Tests
- `test_graph_build.py` (713) — **the main structural test surface.** 26 tests asserting on the returned `GraphModel` (no mocks; `resolve_child` via plain closures).
- `test_graph_mermaid_renderer.py` (258) — renderer-specific: collision/leak regressions + a structural-validity sweep.
- `test_mermaid.py` (±213) — migrated off the 6 deleted helper exports; renderer behavior now tested through `generate_mermaid`.
- `test_mermaid_golden.py` (+26) + new golden `multi-output-batch-fan.mmd` + fixtures under `examples/_test_fixtures/graph/multi-output-batch/` — pins the batch-output-fan cardinality (W6) that no prior golden covered.
- `test_ir_schema.py` (+58), `test_markdown_parser.py` (+43) — Phase 0 coverage.

## Integration Points & Dependencies

### Incoming (what depends on this)
- `cli/commands/visualize.py` → `generate_mermaid()` (the **only** production consumer; the shim is the stable surface).
- `test_mermaid_golden.py`, `test_mermaid.py`, `test_visualize.py` → `generate_mermaid()`.
- **Future:** the unfiled web-UI task → `build_graph()` + `dataclasses.asdict()`; Task 133 (JSONL trace) → the runtime-overlay join contract (NodeId mirrors runtime identity).

### Outgoing (what this depends on)
- `sub_workflow_resolver.SubWorkflowResult` — `build_graph` consumes `resolve_child: (params, base_path) -> SubWorkflowResult | None`; reads `.ir` (file-resolved, prompts inlined), `.path`, `.warnings`. Does **not** re-resolve files.
- `workflow_id.synthesize_inline_workflow_id` — cycle-stack key for path-less inline children.
- `runtime.template_resolver.TemplateResolver` — `scope.py` reuses `split_coalesce_operands`/`is_literal_operand` (lazy import).
- IR fields read: `id/type/purpose/params/batch/loop/inputs/outputs/edges/_source_line/_source_lines/_source_files/_routes_to_end/start_node`.

### The `_routes_to_end` three-site coupling (load-bearing)
Parser **writes** it (2 sites) → schema **whitelists** it (`additionalProperties:False` node object) → build **consumes** it to synthesize the per-level `__end__` node + `EdgeKind.END` edge. The exact name `_routes_to_end` must match at all three sites — a mismatch silently fails schema validation of committed `next: end` examples (`conditional-branching`, `error-handling`). It is **inert** to engine/validator/compiler (they route on `edges`, not top-level node fields).

## Architectural Decisions & Tradeoffs

### Key decisions
- **Derived views, not stored flags** (`is_decision`/`is_terminal`/`shadowed`/shape). Adding a stored decision/shape field re-entangles model and render — the exact debt this task removed. → Alternative (stored fields, per spec sketch) rejected.
- **Structural identity + renderer-derived flat IDs** (ADR-0003). The model never stores `parent__child`; the renderer derives it. This is what lets a future live overlay join runtime events losslessly. → Alternative (keep Mermaid's flat-string IDs in the model) rejected — it would make React Flow a translator over a Mermaid-shaped thing.
- **Two-sub-pass build.** The legacy resolver read routing maps *live* mid-walk (`Scope.resolve` non-snapshot reads), so a ref to a later sibling resolved against half-built state. Creating all identities before resolving any edge is strictly cleaner and removes the partial-read fragility.
- **Loop = node property, not edge** (ADR-0001). `LoopSpec` on `Node`; the engine self-re-enters with no edge. Loop `while`/`until`/`carry` refs deliberately produce **no** data-flow edges (stay metadata); only `max_iterations: ${ref}` creates a dependency edge.
- **`→ end` as a distinct `EdgeKind.END`** (not BRANCH). A BRANCH-kind end edge would corrupt `is_decision` (distinct-branch-label count). Distinct kind keeps `is_decision` (BRANCH-only) and `is_terminal` (excludes ERROR+END) correct.

### Technical debt incurred
- **O(n) lookups in the model/build** (`GraphModel.node`, `_GraphBuilder._require_node`, and `shadowed`'s `_has_expanded_outputs`/`_batch_item_members`/`_expanded_input_members` helpers each scan all nodes/containers). The renderer builds its own `nodes_by_id` dict, so render is fine; the model helper is not cached. Quadratic-ish in `build` and per-`shadowed`-call. Acceptable now; cache if graphs grow large.
- **Flat-id collision scheme is patched, not bulletproof** (`_assign_flat_ids`). The legacy string-concat namespace (`parent__child`, `pflow_end`, `input_x`, batch `dots`) is inherently collision-prone. The fix disambiguates with numeric suffixes and pre-reserves synthetic ids; a **residual fixpoint case** (a node colliding with a *suffixed* host's synthetic id, requiring the host name to also collide) is left unfixed **by design**. The real answer is an injective id scheme in the React Flow renderer, not more patching.
- **Model purity is grep-verified, not test-gated.** No automated test fails if `classDef`/`@{`/`:::`/`fill:` leaks into `model.py`/`build.py`. Future agents must keep running the grep (plan §9.2).
- **Model vs render suppression asymmetry.** `GraphModel.shadowed()` is the general model-level view; the renderer's `_edge_shadowed_for_render` is deliberately **narrower** (keeps a single direct arrow for node-to-node data-flow, since Mermaid has no separate visual treatment). Two suppression predicates that must not be conflated.

## Testing Implementation

### Strategy
Structural assertions moved to `test_graph_build.py` (assert on the `GraphModel` through `build_graph`'s interface, no mocks); goldens demoted to the *Mermaid adapter's* regression tripwire. `resolve_child` is injected as a plain closure in tests — the one port, no mock framework.

### Critical test cases (catch real bugs, not coverage)
- `test_nested_subworkflow_outputs_thread_to_sibling_consumer` — asserts the **endpoint** `score.score → compile` (output_field + target = the output Node), not mere existence. The first build cut **missed this** (it only generated data-flow for expanded child inputs, mirroring old Mermaid); this test forced the broader structural truth.
- `test_synthetic_input_and_output_with_same_name_have_distinct_identity` — guards the `changelog_file`-in-both collision that the `__inputs__`/`__outputs__` markers fix.
- `test_shadowed_suppresses_direct_same_source_data_flow_edges` / `test_shadowed_preserves_expanded_output_sources_and_requires_full_batch_coverage` — the shim cutover exposed a real regression (`prepare → subwf` suppressed when the only replacement edge was `workflow-input → subwf-input`); these pin same-source coverage + the 3-clause batch rule.
- `test_public_mermaid_output_is_structurally_valid` (10 real workflows, `descriptions=True`) — guards a bug class **goldens cannot**: a golden freezes the exact string *including a broken one* if regenerated after a bug. Asserts no `${}` leak, balanced subgraph/end nesting, no id defined twice.
- The 5 collision/leak regression tests (`test_node_name_colliding_with_*`, `test_template_refs_in_descriptions_do_not_leak`) — **mutation-verified**: reverting either fix fails them. These are the only tests exercising the collision code path with actual collisions (no real workflow names a node `pflow_end`).
- `test_routes_to_end_builds_synthetic_end_edges_without_changing_decision_or_terminal` — exercises both parser write-sites (bullet + code path) and confirms END edges don't perturb `is_decision`/`is_terminal`.
- `test_graph_model_is_asdict_json_serializable_with_adversarial_values` — proves serialization with nested/non-string batch items and a `SourceRef` from a `Path`, not just clean subjects.

## Unexpected Discoveries

### Gotchas (documented in the progress log; verify, don't re-derive)
- **The spec's "nearest-consumer-only" for top-level inputs was a misnomer.** The code does **pair-dedup**: an edge to *each distinct consumer*, deduped on `(source, target)`. (Finding F13.)
- **Cycle detection was already a recursion-stack**, not a global visited set. Only gap fixed: path-less inline children now key on `synthesize_inline_workflow_id` (an md5 collision = a vanishingly-rare false cycle, commented as acceptable).
- **A hand-wired backward-edge cycle within one level** (e.g. `run-validate → check-validate → fix-tests → run-validate`) is NOT a sub-workflow re-entry — it stays a faithful edge and never touches the recursion stack.
- **An empty/degenerate resolved child** (`not child.ir.get("nodes")`) must be marked `unexpanded="unresolved"` — otherwise an empty Container reads as a successful expansion.
- **`SubWorkflowResult.warnings` are Diagnostic objects** — stored as `str()` in `annotations` because Diagnostics break `json.dumps`.

### Edge cases
- Input/output name reuse (synthetic scope markers).
- 0-item batch, dynamic batch (`items=None`) — the per-item label rule must no-op, never `IndexError`/`NoneType`-subscript.
- A node with both an ERROR edge and an END edge is still `is_terminal=True`.
- `${a ?? b}` coalesce → N data-flow edges sharing a target; literal operands (`"none"`) filtered by `source_refs_in`.

## Patterns Established (reuse these)

- **Pure builder + injected port.** `build_graph(ir, *, resolve_child, base_path, source_file, max_depth)` is a pure function of `(IR, resolve_child)`. Test by asserting on the returned model; inject `resolve_child` as a closure. No mocks, ever.
- **Two-sub-pass over a recursive structure.** When a later element's resolution depends on earlier siblings, create *all* identities in pass A, resolve *all* relations in pass B. Avoids order-dependent partial reads.
- **Structural identity, renderer-derived presentation IDs.**
  ```python
  NodeId("evaluate", (AncestorStep("analyze-sources"), AncestorStep("score")))   # 3-deep nested
  NodeId("critique", (AncestorStep("reviews", 0),))                              # literal batch item 0
  ```
  Renderers derive `parent__child` flat IDs; the model stays presentation-free. Mirrors runtime/trace identity so a future event-log overlay joins losslessly (N loop visits : 1 static node).
- **Derived views over stored flags.** If a fact is a pure function of the edge list / node set, expose it as a method, don't store it. Deletion-test every would-be field.
- **Compat shim for a refactored package.** Re-export only the one public symbol (`generate_mermaid`); delete private internals; migrate tests off helper imports. Zero external-caller churn.

### Anti-patterns to avoid
- Don't put Mermaid syntax (or any render/runtime concern) in `model.py`/`build.py`.
- Don't re-derive terminality by a raw edge walk in a renderer — call `graph.is_terminal()` (it excludes END+ERROR). A verbatim "no non-error out" port reads `handle-error` as non-terminal once it carries an END edge.
- Don't collapse the two-sub-pass into one walk.

## Breaking Changes

- **API:** none external. `generate_mermaid()` signature preserved (gained an optional `source_file=`). The 6 private Mermaid helpers were deleted — only test code imported them.
- **Behavioral:** `pflow visualize` now draws `--> pflow_end` for authored `next: end` routes (2 golden shifts). New IR validation: node IDs `end`/`__end__` are now rejected at parse/validate time.
- **IR contract:** new optional parser-injected `_routes_to_end` boolean on nodes (inert to runtime).

## Future Considerations

### Extension points
- **`render_react_flow(graph)`** slots into `renderers/` with no `build_graph` change — this is the committed endgame and the real second consumer. The Phase 7 throwaway sketch confirmed completeness (82 nodes / 152 edges / 14 containers / 1 loop / 4 END edges on the 163 harness, no info loss) but was **discarded, not committed** — re-derive it if you need the check again.
- **`annotations: dict`** on Node and Container is the open seam (ADR-0004). Author-declared annotations (e.g. `pattern: tournament`) need a future validator Step-8 carve-out — the slot is free but end-to-end author annotations are out of scope here.
- **Runtime-overlay join (Task 133 / web UI).** The static NodeId already mirrors runtime identity; the overlay animates IO/END nodes (which have no runtime events) via edges, and fans dynamic-batch/loop N:1 onto the single representative. Documented in `graph/CLAUDE.md` → "Runtime Overlay Join Contract" — do not change the model to fit the trace; join onto it.

### Scalability
- The O(n) model lookups (above) are the first thing to cache if graph sizes grow by an order of magnitude.

## AI Agent Guidance

### Quick start for related tasks
Read in order: `graph/model.py` (the contract) → `graph/CLAUDE.md` (invariants) → `graph/build.py` (`build_level` is the spine) → `renderers/mermaid.py` if touching output. The `implementation-plan.md` §6 deviations table and §4e (edge construction) are the densest references.

### Common pitfalls
- Renaming `_routes_to_end` at fewer than all three sites → silent schema-validation failure of committed examples.
- Editing `is_terminal`/`is_decision` semantics → the `handle-error --> pflow_end` parity pin and decision-shape detection both ride on them.
- Touching the model's `shadowed()` and assuming the renderer uses it directly — the renderer has its own narrower `_edge_shadowed_for_render`.
- Trusting `CLAUDE.md`/plan line numbers — they drift; re-anchor against current code (the plan itself warns of this).

### Test-first recommendations
When modifying build: add the model-level assertion to `test_graph_build.py` first (assert the **endpoint**, e.g. exact `Edge` with `output_field`/`input_name`, not "an edge exists"). When modifying the renderer: run the golden suite (tripwire) + `test_public_mermaid_output_is_structurally_valid` (the structural guard goldens can't provide), and mutation-check any new collision/escaping fix. Always re-run the model-purity grep — it has no automated gate.

---

*Generated from implementation context of Task 155.*
