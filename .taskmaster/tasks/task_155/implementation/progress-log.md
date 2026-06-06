# Task 155 — Implementation Progress Log

Workflow Graph Model for Multi-Renderer Support. Living document — append as work proceeds.

> **Authoritative build guide:** `implementation/implementation-plan.md` (this folder). Spec:
> `task-155.md` (reconciled to the plan; plan §6 wins on deviations). ADRs: 0001/0003/0004.

---

## Implementation steps (from plan §7)

- [x] **Phase 0 — parser/schema `_routes_to_end`** (`markdown_parser.py` both write-sites + `ir_schema.py` whitelist + tests; confirm committed `next: end` examples still validate). Small, LOW risk, separate commit. *Build depends on this field.*
- [x] **Phase 1 — `graph/model.py`** (dataclasses + derived helpers `is_decision`/`is_terminal`/`shadowed`/`node`; assert `Node.parent`↔`Container.members` + edge-endpoint referential integrity).
- [x] **Phase 2 — `graph/scope.py`** (move `refs_in`/`source_refs_in` *verbatim*; `resolve`/`for_level` are NOT here — reimplemented in build).
- [x] **Phase 3 — `graph/build.py`** (the big one: two-sub-pass; expansion + recursion-stack cycle detection incl. `path is None`; the 4-path Scope→structural reimplementation; batch carry-all / leaf-as-data / dynamic-one-expansion; `unexpanded` + empty-IR guard; `_routes_to_end`→END node+edge; `shadowed`/`is_decision`/`is_terminal`). **Main structural test surface** `test_graph_build.py`.
- [x] **Phase 4 — `graph/renderers/mermaid.py`** (`render_mermaid`; move pure utils; rewrite label builders to read dataclasses; flat-id + truncated-tail collapse + batch-fan + end-sink-parity + pair-dedup + suppression at render).
- [x] **Phase 5 — compat shim** (`mermaid/__init__.py` re-exports only `generate_mermaid`; migrate `test_mermaid.py` helper imports/tests).
- [x] **Phase 6 — remove old internals** (delete `_context/_edges/_io/_render/_scope.py`; update `mermaid/CLAUDE.md`; add `graph/CLAUDE.md`).
- [x] **Phase 7 — throwaway react-flow completeness sketch** (6 patterns + 163 harness, no info loss; discard).
- [x] **Post: doc reconciliation** (plan §12) — `task-155.md`, `CONTEXT.md`, `core/CLAUDE.md`, `workflow/CLAUDE.md`, `graph/CLAUDE.md`, and rendered Mermaid doc blocks reconciled.

**Agent handoff (N=3):** agent 1 = phases 0–3 (structural), agent 2 = phase 4 (renderer), agent 3 = phases 5–7. Firebreak at 3→4 (the two-layer split, locked by the frozen `GraphModel` + build suite).

---

## 2026-06-06 15:57 CEST — Planning complete, plan approved

Spent the session taking the task from "scoped spec" to a verified, review-hardened, approved implementation plan. **No code written yet** — Phase 0 is next.

**What happened:**
- Read spec + 3 braindumps + research findings + master session log + ADRs 0001/0003/0004 + CONTEXT.md.
- 6 `pflow-codebase-searcher` passes verified the model design against current code (findings F1–F14 in plan §2).
- **3 review rounds** (`/code-review` plan mode): round 1 (review-plan/simplicity/feature-interactions/impact-completeness), round 2 + round 3 (review-plan/feature-interactions/silent-failures). Final verdict: **risk LOW, design sound, ready** — every finding was a tractable plan edit, not a redesign.
- `/plan-breakdown` → N=3 agent split (in plan §12a).
- Reconciled `task-155.md` to the plan (6 surgical edits + 1 pointer note).
- Copied the approved plan to `implementation/implementation-plan.md`.

**Key decisions locked (rationale in plan §6):**
- 💡 Model is **leaner than the original spec sketch** — `shape`/`is_decision`/`is_terminal`/suppression are **derived views**, not stored; routing maps (`outgoing_routes` etc.) are **build scratch, not model fields**; dropped `Edge.via_coalesce` and the leaf `NodeId.batch_index`.
- 💡 **Identity** = `NodeId(node_id, ancestor_path)` with `batch_index` on each `AncestorStep`. Leaf batch items are `BatchSpec.items` *data*, not Nodes. Mirrors runtime identity (ADR-0003) so the future live-overlay join is lossless.
- 💡 **D1 (batch):** carry ALL literal items; the `…dots` ellipsis is render-only (fixed the blocking gap where `__dots` had edges but no identity).
- 💡 **D2 (`- next: end`):** modeled as an `EdgeKind.END` edge to a synthetic per-level END node, sourced from a NEW Phase 0 parser field `_routes_to_end`. Distinct edge kind so `is_decision`(BRANCH-only)/`is_terminal`(excludes END) stay correct. Mermaid ignores END edges (parity); React Flow consumes them.
- 💡 `descriptions` → `render_mermaid` (not build); source back-ref is a `(file,line)` pointer.

**The verifications that changed the plan (don't re-derive):**
- ❌ My initial assumption that cycle detection was global-visited → **wrong**; it's already a recursion-stack (port as-is; only fix the `path is None` gap via `synthesize_inline_workflow_id`).
- ❌ My initial D2 framing (BRANCH edge / Node flag) → **wrong on two counts**: `- next: end` is *discarded at parse time* (needs the parser change), AND a BRANCH-kind end edge would corrupt `is_decision`. Resolved via the parser field + distinct `EdgeKind.END`.
- ❌ "nearest-consumer-only" (spec wording) → **misnomer**; the code does pair-dedup (each distinct consumer, deduped per `(source,target)`).
- ✅ The runtime-overlay join (Substrate 2 / future JSONL trace, Task 133) is **compatible by design** (ADR-0003); the JSONL rework *strengthens* it. No model change; documented as pins in plan §6a.
- ✅ The 4-path Scope migration is **exhaustive** (no 5th); compat surface is exactly `generate_mermaid` + 6 test-only helpers.

**Top risks carried into implementation (plan §10):**
- ⚠️ **#1 — the 4-path Scope→structural reimplementation in `build.py`** (Phase 3). The bulk of the work; the highest-risk phase. Stays with one agent.
- ⚠️ The `handle-error → pflow_end` parity pin — the renderer MUST call `graph.is_terminal()` (END-excluding), not re-walk edges. Single most important D2 regression guard.
- ⚠️ Batch-output-fan reconstruction without the routing maps → add a multiple-outputs golden (no current golden pins it).

**Decided: no new ADR.** The one candidate (the runtime-inert `_routes_to_end` IR field) follows the existing `_source_*` parser-injected-field convention (which has no ADR) → document in `core/CLAUDE.md` + `graph/CLAUDE.md`, not an ADR.

**Next action:** Phase 0 — the `_routes_to_end` parser/schema change (separate commit).

## 2026-06-06 — Phases 0–3 implemented; firebreak reached

Implemented the structural layer through the planned 3→4 firebreak. Phase 0 was included before Phase 1 because the progress log still had it unchecked and Phase 3 depends on `_routes_to_end`; skipping it would have made END edges unrecoverable.

**What landed:**
- Parser/schema: `_routes_to_end` is set for authored `- next: end`, mixed `- next: target, end`, and AST literal `next = "end"` without adding an IR edge or changing runtime routing. Schema whitelists it as a boolean parser metadata field.
- New `src/pflow/core/workflow/graph/`: `model.py` dataclasses + derived helpers/invariant checks, `scope.py` pure `refs_in`/`source_refs_in`, `build.py` two-sub-pass IR walk, and package exports.
- `build_graph()` now emits structural/data-flow/END edges, loop and batch specs, containers, source refs, unexpanded reasons, synthetic per-level END nodes, and structural identities for nested and batch-expanded children.
- Added `tests/test_core/test_graph_build.py` with model-level coverage for nested output threading, literal/dynamic/leaf batches, END edges, loops, coalesce output sources, unexpanded reasons, `path is None` cycles, sibling same-child expansion, top-level input pair-dedup, shadowing, and JSON serialization.
- Added `graph/CLAUDE.md`; updated `core/CLAUDE.md` to document `_routes_to_end`.

**Key implementation learning:** the first build pass missed normal-node `params.inputs` data-flow (`score.score -> compile`) because old Mermaid only generated this path for expanded child inputs. The model needs the broader structural truth, so `params.inputs` now resolves sibling/output refs to either the node itself or the child input node when the consumer is an expanded workflow.

**Intentional note for Phase 4:** IO wrapper containers are modeled as structural children of the workflow level they belong to; Mermaid can still render them externally where needed. This keeps the model semantic and avoids baking Mermaid placement into `build_graph`.

**Verification run:**
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_ir_schema.py tests/test_core/test_markdown_parser.py tests/test_core/test_graph_build.py -q` → 279 passed.
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_mermaid.py tests/test_core/test_mermaid_golden.py tests/test_cli/test_visualize.py tests/test_core/test_graph_build.py -q` → 110 passed.
- `.venv/bin/ruff check src/pflow/core/markdown_parser.py src/pflow/core/ir_schema.py src/pflow/core/workflow/graph tests/test_core/test_graph_build.py tests/test_core/test_markdown_parser.py tests/test_core/test_ir_schema.py` → clean.
- `.venv/bin/mypy src/pflow/core/workflow/graph src/pflow/core/markdown_parser.py src/pflow/core/ir_schema.py` → clean.
- Purity grep for Mermaid syntax in `graph/model.py` and `graph/build.py` → no matches.
- Direct parser/schema probe for committed `next: end` examples passed after standard `ir_version` injection; expected flags: `conditional-branching: handle-error`, `error-handling: save-result/create-fallback`, `validate-fix: check-validate`.

**Firebreak status:** Phase 4 renderer work is not started. The current public graph API is ready for review before Mermaid is rewritten over it.

## 2026-06-06 16:38 CEST — Phase 4 implemented; stop point reached

Implemented `graph.renderers.mermaid.render_mermaid(graph, direction, descriptions)` over `GraphModel` and exported it from `pflow.core.workflow.graph`; the legacy `pflow.core.workflow.mermaid.generate_mermaid` path is intentionally untouched for Phase 5. Added `tests/test_core/test_graph_mermaid_renderer.py` to compare `render_mermaid(build_graph(...))` byte-for-byte against the legacy renderer for all current golden subjects.

**Key learnings / necessary deviations:**
- Synthetic IO identity needed a small Phase-3 correction: valid IR can use the same name for an input and output (`generate-changelog` has `changelog_file` in both). Bare `NodeId(name, ancestor_path)` collided, so inputs/outputs now add synthetic marker ancestry (`__inputs__` / `__outputs__`) while keeping `node_id` as the authored name. Mermaid strips those markers; executable node identity is unchanged.
- `build_graph` was missing two batch data-flow facts needed by both the model and renderer: dynamic batch `${item.*}` inputs route from the batch source, and literal workflow batches need sibling-to-item-input edges. Added structural coverage and tests instead of recreating those edges inside the Mermaid renderer.
- `GraphModel.shadowed()` was narrowed so normal-node data-flow does not suppress structural execution edges. Mermaid batch truncation still needs render-visible suppression, so hidden-item/dots suppression lives in the renderer where the truncation decision exists.

**Verification run:**
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_graph_build.py tests/test_core/test_graph_mermaid_renderer.py -q` → 24 passed.
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_mermaid.py tests/test_core/test_mermaid_golden.py tests/test_cli/test_visualize.py tests/test_core/test_graph_build.py tests/test_core/test_graph_mermaid_renderer.py -q` → 120 passed.
- `.venv/bin/ruff check src/pflow/core/workflow/graph tests/test_core/test_graph_build.py tests/test_core/test_graph_mermaid_renderer.py` → clean.
- `.venv/bin/mypy src/pflow/core/workflow/graph` → clean.
- `grep -RInE 'classDef|@\{|:::|fill:|stroke:|<br/>' src/pflow/core/workflow/graph/model.py src/pflow/core/workflow/graph/build.py` → no matches.

**Firebreak status:** Phase 4 is complete. Phase 5 compat-shim cutover is not started.

## 2026-06-06 17:03 CEST — Phase 5 implemented; review stop point reached

Cut over `pflow.core.workflow.mermaid` to a compatibility shim that exports only `generate_mermaid`, delegates IR walking to `build_graph()`, and delegates syntax emission to `render_mermaid()`. Migrated `test_mermaid.py` off the six old helper exports: renderer behavior stays covered through `generate_mermaid`, edge preprocessing moved to `test_graph_build.py`, and renderer utility checks moved to `test_graph_mermaid_renderer.py` against `LoopSpec`/`BatchSpec`-shaped inputs.

**Key learning / deviation:** the shim switch exposed a real Phase-4 regression that the legacy parity test could not see: `GraphModel.shadowed()` suppressed `prepare -> subwf` when the only replacement data-flow edge was `workflow input -> subwf input`. That disconnects execution order and violated an existing regression test, so I fixed `shadowed()` to require data-flow coverage from the same structural source and pinned the case at the model boundary. This is not a scope expansion; the compat shim could not safely ship while changing existing Mermaid behavior.

**Verification run:**
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_graph_build.py tests/test_core/test_graph_mermaid_renderer.py tests/test_core/test_mermaid.py tests/test_core/test_mermaid_golden.py tests/test_cli/test_visualize.py -q` → 115 passed.
- `.venv/bin/ruff check src/pflow/core/workflow/mermaid/__init__.py src/pflow/core/workflow/graph/model.py tests/test_core/test_mermaid.py tests/test_core/test_graph_build.py tests/test_core/test_graph_mermaid_renderer.py` → clean.
- `.venv/bin/mypy src/pflow/core/workflow/mermaid/__init__.py src/pflow/core/workflow/graph/model.py` → clean.

**Stop status:** Phase 5 is complete. Phase 6 deletion/docs cleanup and Phase 7 throwaway React Flow sketch are not started.

## 2026-06-06 17:18 CEST — Phase 6 implemented; review stop point reached

Removed the old Mermaid implementation internals (`_context.py`, `_edges.py`, `_io.py`, `_render.py`, `_scope.py`) now that the compatibility shim delegates through `workflow.graph`. Rewrote `mermaid/CLAUDE.md` as shim guidance, updated `graph/CLAUDE.md` with renderer ownership and the same-source `shadowed()` invariant, and reconciled `core/workflow/CLAUDE.md` so navigation points at `graph/` instead of deleted Mermaid internals.

**Key learning / deliberate non-edit:** task research/context files still mention old Mermaid internals with historical line evidence. I left those alone because they are part of Task 155's audit trail, not active code navigation. Active `src/`, `tests/`, `docs/`, and `examples/` references to deleted private Mermaid modules were checked; only intended historical/doc notes and unrelated `diagnostic_render.py` matches remain.

**Verification run:**
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_graph_build.py tests/test_core/test_graph_mermaid_renderer.py tests/test_core/test_mermaid.py tests/test_core/test_mermaid_golden.py tests/test_cli/test_visualize.py -q` → 115 passed.
- `.venv/bin/ruff check src/pflow/core/workflow/graph src/pflow/core/workflow/mermaid tests/test_core/test_graph_build.py tests/test_core/test_graph_mermaid_renderer.py tests/test_core/test_mermaid.py` → clean.
- `.venv/bin/mypy src/pflow/core/workflow/graph src/pflow/core/workflow/mermaid` → clean.

**Stop status:** Phase 6 is complete. Phase 7 throwaway React Flow completeness sketch is not started.

## 2026-06-06 17:19 CEST — Phase 7 completed; review stop point reached

Ran a disposable inline `render_react_flow(graph)` sketch that converted `GraphModel` into React Flow-shaped
`{nodes, edges, groups}` data, then discarded it. The sketch preserved every graph node, edge
`EdgeKind`, container, parent/member link, loop/batch/unexpanded field, END edge, and source-ref payload.

**Subjects checked:** classify-and-act (`examples/core/conditional-branching.pflow.md`),
fan-out-and-synthesize (`examples/nested/deep-research/deep-research.pflow.md`), adversarial-verification
(synthetic guide-shaped workflow), generate-and-filter (synthetic guide-shaped workflow), tournament
(`examples/core/stateful-loop-tournament.pflow.md`), loop-until-done (synthetic loop workflow), and the Task
163 harness (`examples/agent-orchestration/plan-to-code/run-from-plan.pflow.md`) at `max_depth=5`.

**Key learning:** no model/build gap was found. The harness graph exposed 82 nodes, 152 edges, 14 containers,
1 loop, and 4 `EdgeKind.END` abort edges; all were representable without reading IR or Mermaid syntax. Root
workflow source refs carry source lines with `file=None`, while expanded child nodes carry child file paths;
the sketch preserved this as-is rather than adding root-file knowledge outside `GraphModel`.

**Verification run:**
- Disposable sketch via `HOME=/private/tmp/pflow-test-home .venv/bin/python - <<'PY' ... PY` → passed all
  completeness assertions.

**Stop status:** Phase 7 is complete. Per user instruction, stopping here for review; post-phase doc
reconciliation remains unchecked.

## 2026-06-06 17:20 CEST — Manual CLI regression pass

Ran a verification-specialist pass against the real `pflow` CLI, not just graph unit tests. Read
`pflow --help`, `pflow guide core`, targeted guide topics (`code`, `shell`, `file`, `batch`, `loop`,
`branching`, `error-handling`, `sub-workflows`, `patterns`), and `pflow visualize --help` first so the
manual workflows matched supported syntax.

**Baseline suite:** sandbox near-full command produced `7720 passed, 19 skipped, 4 failed`. All four failures
were subprocess tests invoking `/opt/homebrew/bin/uv`, which panicked before Python started (`Attempted to
create a NULL object` / `Tokio executor failed`), matching the known sandbox failure mode. No graph/manual
verification conclusion is based on those tests.

**Manual workflows created under `scratchpads/task-155-manual-verification/`:**
- `graph-stress-main.pflow.md` + `transform-child.pflow.md`: dynamic batch over a static child workflow,
  branch + code `next = "end"`, child IO expansion, output coalescing.
- `fallback-end.pflow.md`: `on-error` recovery into `next: end`.
- `loop-parent.pflow.md` + `loop-round.pflow.md`: loop on a sub-workflow host with `carry`.
- `dynamic-child.pflow.md`: runtime-selected child path; static graph must keep it opaque.
- `literal-batch-parent.pflow.md`: literal batch over child workflow with >2 items.

**CLI checks and results:**
- `pflow ... --validate-only` caught two real authoring mistakes in the scratch branch workflow (missing
  explicit `- next:` on branch targets); after fixing the scratch file, validation passed.
- `pflow graph-stress-main.pflow.md --output-format json` executed successfully: summary
  `{"names":["b","c"],"total":12,"count":3}` with the expected validator advisory for JSON string nested
  access.
- `pflow fallback-end.pflow.md --output-format json` completed degraded with the expected on-error warning
  and fallback result.
- `pflow loop-parent.pflow.md --output-format json` executed three child rounds and returned
  `{"total":3,"stopped":"condition"}`.
- `pflow dynamic-child.pflow.md child_path=./loop-round.pflow.md --output-format json` executed successfully
  from the scratch directory when using the absolute venv CLI path.
- `pflow literal-batch-parent.pflow.md --output-format json` processed all 4 items and returned
  `{"count":4,"total":30}`.
- `pflow visualize ... --depth 0` kept static workflow batch nodes opaque; `--depth 5` expanded child IO and
  child nodes. `loop-parent` rendered the loop badge on the workflow subgraph. `dynamic-child` visualized as
  an opaque workflow node while execution resolved the child at runtime. Committed END examples still show
  `handle-error --> pflow_end` in `conditional-branching`.

**Key learning:** no Task-155 regression was found. The only surprises were guide-enforced authoring
constraints in the scratch workflow and the literal-batch renderer threshold: batches with `count <= 4`
render all items; the dots collapse starts above that threshold (confirmed in renderer code and deep-research
output).

## 2026-06-06 17:21 CEST — Root source-file back-ref tightened

Added optional `source_file` plumbing to `build_graph()` and the `generate_mermaid()` shim, and passed the
resolved workflow path from `pflow visualize`. This makes root workflow nodes carry
`SourceRef(file=<root workflow path>, line=<heading line>)`, matching the already-existing child workflow
behavior from `SubWorkflowResult.path`. Mermaid output remains unchanged; the fix is for the future
click-to-read UI contract.

**Verification run:**
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_graph_build.py tests/test_core/test_graph_mermaid_renderer.py tests/test_core/test_mermaid_golden.py tests/test_cli/test_visualize.py -q` → 50 passed.
- `.venv/bin/ruff check src/pflow/core/workflow/graph src/pflow/core/workflow/mermaid src/pflow/cli/commands/visualize.py tests/test_core/test_graph_build.py tests/test_core/test_graph_mermaid_renderer.py tests/test_core/test_mermaid_golden.py` → clean.
- `.venv/bin/mypy src/pflow/core/workflow/graph src/pflow/core/workflow/mermaid src/pflow/cli/commands/visualize.py` → clean.
- Manual `pflow visualize` probes for `loop-parent` and committed `conditional-branching` remained stable,
  including the `handle-error --> pflow_end` pin.

## 2026-06-06 17:31 CEST — Phase 8 doc reconciliation complete

Completed the post-phase documentation reconciliation. Verified the active graph vocabulary and invariants in
`context/CONTEXT.md`, `src/pflow/core/CLAUDE.md`, `src/pflow/core/workflow/CLAUDE.md`, and
`src/pflow/core/workflow/graph/CLAUDE.md` against the implemented GraphModel shape, then updated the stale
task status from `not started` to `implemented; pending review`.

Regenerated the three plan-named Mermaid documentation blocks from the current CLI:
`docs/reference/cli/index.mdx`, `examples/agent-orchestration/plan-to-code/README.md`, and
`examples/agent-orchestration/parallel-planner-review/README.md`. The parallel-planner README had a real
semantic drift: it described the old hand-wired counter/check loop, but the workflow now uses a declarative
`loop:` on `run-cycle`; the prose was updated to match the rendered graph.

**Verification run:**
- `HOME=/private/tmp/pflow-test-home .venv/bin/pflow visualize examples/core/conditional-branching.pflow.md`
  → regenerated the CLI reference block and preserved `handle-error --> pflow_end`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/pflow visualize examples/agent-orchestration/plan-to-code/run-from-plan.pflow.md --depth 5 --direction TD --descriptions`
  → regenerated the Task 163 harness README block.
- `HOME=/private/tmp/pflow-test-home .venv/bin/pflow visualize examples/agent-orchestration/parallel-planner-review/orchestrate.pflow.md --depth 5 --direction TD`
  → regenerated the parallel-planner README block.

**Deviation:** I did not re-run the full test suite for this doc-only phase. The touched rendered blocks were
generated by the same CLI path covered earlier, and Phase 8 changed no Python code. I used compact
non-description rendering for the parallel-planner README because its existing diagram was a structural
overview; the stale fact was the loop shape, not missing node prose.

## 2026-06-06 17:31 CEST — Four-agent staged code review complete

Ran the requested `$code-review` pass against the staged Task 155 changes with the four most relevant
specialists: validation consistency, feature interactions, impact completeness, and test fidelity. I used four
agents instead of the skill's full seven-agent default because the user explicitly constrained this pass to four.

**Confirmed findings:** direct structural-edge shadowing is implemented inconsistently with its docstring and
plan predicate; explicit `_routes_to_end` edges exist in the model but disappear from Mermaid output for
non-decision/non-terminal-sink cases; custom batch `as:` aliases are stored but ignored by data-flow extraction;
`loop.max_iterations: ${input}` does not create an input dependency edge; click-to-read source refs preserve only
the node heading, not param-level `_source_lines`/`_source_files`; programmatic IR can still use reserved
synthetic ids such as `__end__`; and the plan-required multi-output batch golden is missing.

**Disputed / lower-priority findings:** `_routes_to_end` being schema-valid is intentional parser metadata rather
than a runtime contract, but reserved-id and uniqueness checks should prevent it from becoming ambiguous. Private
renderer-helper tests are a maintainability smell, not a blocking behavior issue. The Mermaid shim doc omission
for `source_file` is real but documentation-only.

**Verification performed:** read the task spec, implementation plan, all three starting-context braindumps, and
this progress log; verified the high-signal claims with targeted `.venv/bin/python` probes under
`HOME=/private/tmp/pflow-test-home`. No code fixes were applied in this pass; the next step is to decide whether
to implement all confirmed fixes now or split behavior fixes from test/documentation cleanups.

## 2026-06-06 17:46 CEST — Review issues 1–3 fixed

Implemented the first three confirmed review fixes. `GraphModel.Node` now carries `param_sources` alongside the
heading-level `source`, so click-to-read consumers can open prompt/code/command origins without re-walking IR.
`build_graph()` now honors custom batch aliases when resolving dynamic batch item refs and avoids treating literal
item alias refs as sibling-node refs. Mermaid now renders explicit `EdgeKind.END` routes to the visual `pflow_end`
sink instead of hiding them for parity.

**Deliberate deviation from plan:** the original Phase 4 plan said Mermaid should ignore model END edges. The
review showed that this makes valid authored `next: end` routes invisible in the first renderer. I changed Mermaid
to render explicit END edges because the graph model's structural truth should be visible; the resulting golden
changes are limited to workflows with authored terminal routes.

**Verification run:**
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_graph_build.py tests/test_core/test_graph_mermaid_renderer.py tests/test_core/test_mermaid.py tests/test_core/test_mermaid_golden.py -q` → 109 passed.
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_cli/test_visualize.py -q` → 11 passed.
- `.venv/bin/ruff check src/pflow/core/workflow/graph tests/test_core/test_graph_build.py tests/test_core/test_mermaid.py tests/test_core/test_graph_mermaid_renderer.py tests/test_core/test_mermaid_golden.py` → clean.
- `.venv/bin/mypy src/pflow/core/workflow/graph` → clean.

## 2026-06-06 17:56 CEST — Review issues 4–7 fixed

Implemented the remaining confirmed review fixes. `build_graph()` now treats `loop.max_iterations` template refs
as normal dependencies while leaving loop `while`/`until` and `carry` as metadata. `GraphModel.shadowed()` now
recognizes direct same-source data-flow coverage, and the Mermaid renderer deliberately keeps a single direct
arrow for that case instead of dropping the edge or rendering duplicates. `GraphModel` rejects duplicate node and
container identities, and `validate_ir()` now rejects authored `end` / `__end__` node IDs so programmatic IR
cannot collide with graph terminal sentinels.

Added a test-only golden fixture for a literal workflow batch whose child exposes two outputs. The committed
golden pins the visible item-output fan (`summary` and `score`) plus the hidden-item dots route to the downstream
node, without adding synthetic examples to the user-facing workflow set.

**Key decision:** Mermaid render suppression is intentionally narrower than `GraphModel.shadowed()` for direct
node-to-node data-flow. The model-level view is useful for richer renderers; Mermaid has no separate visual
treatment for that direct data-flow edge, so preserving the single existing arrow is simpler and avoids a misleading
missing connection.

**Verification run:**
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_graph_build.py tests/test_core/test_ir_schema.py tests/test_core/test_mermaid.py tests/test_core/test_mermaid_golden.py -q` → 184 passed.
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_cli/test_visualize.py -q` → 11 passed.
- `.venv/bin/ruff check src/pflow/core/ir_schema.py src/pflow/core/workflow/graph tests/test_core/test_graph_build.py tests/test_core/test_ir_schema.py tests/test_core/test_mermaid.py tests/test_core/test_mermaid_golden.py` → clean.
- `.venv/bin/mypy src/pflow/core/ir_schema.py src/pflow/core/workflow/graph` → clean.
