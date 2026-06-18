# Task 168 Review: Workflow Visualization Web UI — Static Structure Viewer

## Metadata
- **Design + plan:** 2026-06-06 → 06-07. **Implementation:** 2026-06-07 → 06-08.
- **Branch:** `feat/workflow-visualization-static-viewer`. **PR #496** = the static increment (Phases 1–5). The **visual/interaction layer + contract extensions** then landed on the same branch (~47 commits total, through 2026-06-17).
- **Scope of THIS review:** the FULL feature. The static increment (Phases 1–5) is documented below as before; the **visual/interaction layer + contract extensions** (*The Visual / Interaction Layer* section) I did **NOT** implement — those facts are **[relayed]** from `implementation/progress-log.md`, cross-checked against the `web/` CLAUDE.md suite + code via parallel review agents.
- **Source of truth for the journey:** `.taskmaster/tasks/task_168/implementation/progress-log.md` (unusually rich — every phase's deviations live there). Spec: `task-168.md`. How: `implementation/implementation-plan.md` (the H1–H13 review-hardening section is load-bearing). Requirements checklist: `visualization-requirements.md`.
- **Trust boundary (per CLAUDE.md):** Phase 5 (docs, purity guard, test-quality fix) I implemented directly. The *whole feature* I verified end-to-end (live server, real-browser screenshots, a 58-workflow contract sweep, mutation tests) — marked **[verified]**. Phases 1–4 internals I relay from the progress log cross-checked against the committed code I read — marked **[relayed+read]**. I did not write Phases 1–4.

## Executive Summary
Adds a **second renderer** (`render_react_flow`) and a **local Starlette server** (`pflow ui`, behind a `pflow[ui]` extra) that serves a Vite/React/React-Flow/ELK SPA over a **typed, React-Flow-native JSON contract** derived from the Task 155 `GraphModel`. It reveals structure that is invisible in `.pflow.md` text: input→node wiring, `${ref}` template connections, params (click-to-read), nested sub-workflow/batch/loop containers. That static increment is the FOUNDATION; a large **visual/interaction layer** (Tines/n8n visual language, click-to-read panels, a source pane, live-source auto-update) and substantial **contract extensions** then landed on top of it (see *The Visual / Interaction Layer* below). Still deferred but architected-for: the **live-run overlay** (the structural `RFRef` join key + a pluggable `api/` data seam + a `status`-prop separation in node components) and **visual editing** (the per-param `SourceRef` seam).

## Implementation Overview

### What Was Built
1. **`Node.params` model field** (Phase 1) — authored param *values* inline on the graph model, for click-to-read. **[relayed+read]**
2. **`render_react_flow(graph) -> RFGraph`** (Phase 2) — a translator emitting frozen dataclasses (`RFGraph/RFNode/RFEdge/RFGroup/RFParam/RFRef`) that `asdict`+`json.dumps` round-trips. **[verified]**
3. **`execution/graph_service.py`** (Phase 3, the H11 helper) — `resolve_validate_build(workflow, *, max_depth) -> GraphModel`, the single orchestration seam (`resolve_workflow` → `WorkflowRunner.validate` → `build_graph`). **[verified]**
4. **`ui/server.py` + `cli/commands/ui.py` + `[ui]` extra** (Phase 3) — Starlette app, `/api/catalog` + `/api/graph`, static mount; `pflow ui` Click command. **[verified]**
5. **`web/` frontend** (Phase 4) — Vite + React 18 + `@xyflow/react` v12 + `elkjs`, building into `src/pflow/ui/static/`. **[verified rendering, real browser]**
6. **Docs + purity guard + test-quality** (Phase 5) — CLAUDE.md updates, `test_graph_model_purity.py`, strengthened real-workflow renderer test. **[implemented]**

### Deviations from the plan (each with a reason that matters downstream)
- **The plan's packaging claim was WRONG (the single most consequential correction).** Plan/H1 said "no wheel-inclusion change needed; the bundle ships via `packages=["src/pflow"]`." Hatchling **honors `.gitignore`**, and `src/pflow/ui/static/` is gitignored → it is *force-excluded* from the wheel. Fix: `[tool.hatch.build.targets.wheel] artifacts = ["src/pflow/ui/static/**/*"]` (`pyproject.toml:109`). Without it the `[ui]` wheel ships an empty bundle and `pflow ui` 404s. **[verified — built a wheel, inspected contents]**
- **`Node.params` uses a named `_node_params(raw_node)` helper with a non-dict guard** (`build.py`), not the plan's inline `raw_node.get("params", {})` — H3: unvalidated IR may carry `params: None`/str/list. Mirrors the existing `_build_loop`/`_build_batch` helper symmetry. **[relayed+read]**
- **`is_dynamic` mirrors `build.py`'s `_params_strings` EXACTLY** (string + dict-of-string leaves; **no list descent**), not the plan prose's "dict/list" (H5). Invariant: `is_dynamic=True` ⟺ a DATA_FLOW edge exists. List descent would flag a chip with no edge. **[verified]**
- **Added `RFNode.is_group_host: bool`** (absent from the plan's dataclass listing; H8). Defined structurally as `literal-batch OR (workflow-host AND unexpanded is None)` — NOT H8's looser "id ∈ any host," which would draw a phantom empty group for an *unexpanded* dynamic batch. **[verified]**
- **W1 (found in review, not the plan): truncation silently dropped cross-boundary DATA_FLOW edges.** `_visible_anchor` re-anchors a truncated endpoint to its batch host; never drops. **[verified — 3 such edges in `deep-research`, all survive]**
- **`graph_service.py` lives in `execution/`, not `core/`** — it orchestrates `WorkflowRunner.validate` (execution layer); putting it in `core` inverts layering. **[verified+read]**
- **Cold-registry concurrency torn-read fixed at the ROOT**, not worked around. The UI firing `/api/catalog`+`/api/graph` on a cold registry triggered concurrent lazy scan+writes → torn JSON reads → 422s. Fixed via `Registry._write_atomic` (tempfile+`os.replace`), the pattern `WorkflowManager`/`SettingsManager` already use; a server-side warm workaround was added then *deleted* once the root fix proved sufficient. **[relayed+read]**

## The Visual / Interaction Layer + Contract Extensions (post-PR #496) **[relayed]**

> The static increment above is the foundation; the **bulk of the feature** — the Tines/n8n
> visual language, the interaction model, the source pane, and a much richer contract — landed
> across ~40 user-driven arcs afterward. The canonical *how* is the **`web/` CLAUDE.md suite**,
> so this section captures only the cross-cutting knowledge a future agent can't find there.

**Read first for frontend work:** `web/CLAUDE.md` (cross-cutting invariants + folder map) →
`web/src/graph/CLAUDE.md` (the pure transform) · `…/components/CLAUDE.md` (render) ·
`…/hooks/CLAUDE.md` (runtime machinery) · `…/utils/CLAUDE.md` (helpers). Verify the visual layer
in a real browser via `.claude/skills/screenshot-pflow-web-ui` (jsdom cannot).

**The contract grew substantially** (load-bearing for ANY consumer; source of truth =
`react_flow.py` + `graph/CLAUDE.md`): `RFNode.output_shape` (+ `field` naming the port
result/response) and `cached_prefix`; `RFEdge.condition` (fail-closed AST extraction of branch
conditions) + `output_path`; the **unified `${ref}` edge model** — every validator-enforced
`${ref}` now emits one DATA_FLOW edge, so `is_dynamic ⟺ an edge exists` (the old pair-dedup is
gone); **prompt-cache edges** (`input_name="prompt_cache"`); `IOPort` gained `purpose`/`default`
+ the **corrected `required` polarity** (was `False`, now the validator's `True` — one Mermaid
golden updated); `is_decision` now counts the reserved **end route** (continue-or-stop gates ARE
decisions). Two **presented pseudo-kinds**, classified fail-closed in Python — CONDITION (a
decision code node) and TRANSFORM (a pure-reshape code node). Registry interface types reach the
renderer via `kind_output_types`, **injected at the server seam** (renderer stays registry-free
— purity). New endpoints: **`/api/source`** (source pane) + **`/api/version`** (the
live-source-update poll).

**The GOLD — frontend gotchas that cost hours (none findable by reading code):**
- **React Flow draws ALL edges BEHIND nodes** (one SVG layer) → a line flowing *into* an icon
  must be OUR geometry (the connector flare), never a stock edge.
- **jsdom renders ZERO edge DOM** and logs no handle error → edge integrity MUST be a pure
  `graph/flow.test.ts` test (the HANDLE-TYPE INVARIANT). A handle of the wrong *type* silently
  drops the edge (bit the build twice).
- **elkjs crashes, both pinned by layout tests:** a fixed port on a COMPOUND node under
  `INCLUDE_CHILDREN` when an edge references it, and *every* `considerModelOrder.strategy` value
  on a cross-hierarchy edge (`forceNodeModelOrder` is the lone survivor). Also: `nodeSize.minimum`
  is applied **transposed** under direction DOWN — pass `(minH, minW)` in TD.
- **`StaticFiles` sends no `Cache-Control`** → a stale `index.html` repeatedly defeated
  debugging; fix = `Cache-Control: no-cache` on the HTML entry only.
- **The visual layer can't be verified without a real browser** — jsdom can't see edges, and a
  paint-vs-box bug (e.g. a viewBox/element mismatch rescaling the drawing) is invisible to
  `getBoundingClientRect`. Automated guards: the **frontend lossless invariant**
  (`web/src/graph/lossless.test.ts`) + the **Python contract drift guard** (committed real
  contracts vs the live renderer).

## Files Modified/Created

### Core changes
- `src/pflow/core/workflow/graph/model.py` — `Node.params: dict[str, Any]` field. **[relayed+read]**
- `src/pflow/core/workflow/graph/build.py` — `_node_params()` helper + call site in Pass A. **[relayed+read]**
- `src/pflow/core/workflow/graph/renderers/react_flow.py` — **the contract + translator** (the file to read first). **[verified]**
- `src/pflow/core/workflow/graph/renderers/__init__.py`, `graph/__init__.py` — register exports.
- `src/pflow/execution/graph_service.py` — `resolve_validate_build` + `WorkflowGraphValidationError(PflowError)`. **[verified]**
- `src/pflow/ui/server.py` — `create_app()`, `/api/catalog` (`:66`), `/api/graph` (`:80`), `_json` (`:53`), `_frontend_not_built` 503 (`:101`). **[verified]**
- `src/pflow/cli/commands/ui.py` + `cli/main.py` registration — the `pflow ui` command (lazy server import; browser poll-until-ready). **[verified]**
- `src/pflow/registry/registry.py` — `Registry._write_atomic` (atomic write, 3 call sites). **[relayed+read]**
- `pyproject.toml` — `[ui]` extra (`:45`), dev deps, `artifacts` (`:109`). **[verified]**
- `.github/workflows/on-release-main.yml` — `setup-node` + `make ui-build` BEFORE `uv build`, + a guard failing if `static/index.html` is missing. **[relayed+read]**
- `Makefile` — `ui-build` target; `build` depends on it.
- `web/` — full Vite/React tree (38 tracked files; `node_modules`/`dist`/`src/pflow/ui/static` gitignored).

### Test files (which ones actually catch bugs)
- `tests/test_core/test_graph_react_flow_renderer.py` — **critical.** Property-assertion style. Contains the W1 synthetic guard (`test_truncation_preserves_cross_boundary_dependency_via_host`) and the real-workflow no-info-loss test (`test_real_workflows_render_without_information_loss`, 6 representative workflows). **[verified + mutation-tested]**
- `tests/test_core/test_graph_model_purity.py` — **meta-test.** `model.py`/`build.py` carry no render tokens; `react_flow.py` imports only `model`/`scope`. **[implemented + mutation-tested]**
- `tests/test_cli/test_ui.py` — the four `/api/graph` status arms, catalog shape, served-bundle vs 503 fallback, the H4 lazy-import boundary. **[relayed+read]**
- `tests/test_registry/test_registry.py::TestRegistryAtomicWrite` — atomic-write property (failed write leaves prior registry intact). **[relayed+read]**
- `web/src/graph/flow.test.ts` — **the only reliable edge-integrity guard** (the HANDLE-TYPE INVARIANT; see Gotchas). jsdom can't test edges, so this is a pure transform test. **[relayed+read]**

## Integration Points & Dependencies

### Incoming (what reaches into this task)
- `pflow ui` CLI → `graph_service.resolve_validate_build` → `render_react_flow`. The browser → `/api/catalog`, `/api/graph?workflow=<name|path>`.
- Frontend single data seam: `web/src/api/client.ts` (a future `/events` overlay subscription plugs in *here*, not in components).

### Outgoing (what this depends on)
- **Task 155 `GraphModel`** (`build_graph` + the `graph/` package + its derived views `is_decision`/`is_terminal`/`shadowed`). Renderer purity: consumes ONLY the model, never IR.
- `execution/workflow_resolver.resolve_workflow`, `execution/runner.WorkflowRunner.validate`, `core.workflow.sub_workflow_resolver.resolve_sub_workflow`, `core.workflow.manager.WorkflowManager.list_all/get_path`, `registry.Registry`.
- `starlette`/`uvicorn` — declared by `[ui]` but **already transitive base deps via `mcp[cli]`** (`starlette>=0.27`, `uvicorn>=0.31.1`). So the extra adds no new wheel in practice and the `pip install pflow[ui]` hint is a *defensive fallback*, not a path real users hit. **[relayed+read]**

### The forward-compat join contract (load-bearing for the deferred overlay)
`RFRef{node_id, ancestor_path[{node_id, batch_index}], port}` is the EXACT structural identity a future Task-133 runtime overlay joins onto (`graph/CLAUDE.md` → "Runtime Overlay Join Contract"). Body nodes always `port=None`; the join keys on `(node_id, ancestor_path)`. **Do not flatten the structural identity away** — the flat `id` (`n{i}`) is React-Flow-only; both ship per node.

### Shared store keys
None — `pflow ui` runs **no workflows**; every request is read-only (resolve→validate→build→render).

## Architectural Decisions & Tradeoffs
- **Translator, not `asdict(GraphModel)`.** `asdict` ships a nested `NodeId` (not a string `id`) and **drops the derived predicates** (`is_*`/`shadowed` are *methods*). The translator bakes them as facts → one source of truth, frontend never re-implements model semantics. Reversible (the contract is the seam).
- **Injective flat ids `n{i}`/`g{j}`** from the already-unique `NodeId`, NOT Mermaid's collision-patched `_assign_flat_ids`. RF ids aren't user-visible; the structural `ref` carries identity. `n*`/`g*` namespaces are disjoint → no collision loop. **`mermaid.py` is never touched.**
- **Inline-ALL param values** (incl. full prompts/code) in `/graph`; the server re-parses the small `.pflow.md` per request, so values are in hand. Retired the entire by-ref/lazy-fetch machinery. Bounded against batch×depth fan-out by **representative-batch-item truncation** (≤2 + count; mirrors Mermaid's `_visible_batch_indexes`).
- **Predicates as facts; visual policy in TS.** `shadowed()` ships the model's *general* fact; the RF frontend dims (advanced) / hides (beautiful) — it must **not** copy Mermaid's narrower `_edge_shadowed_for_render`.
- **Layout client-side (ELK).** Keeps the contract presentation-free; enables instant re-layout on collapse/expand; handles nested containers (ELK's strength). Cost: ELK is ~80% of the 1.79 MB bundle (disk, not runtime — acceptable; isolated to `web/src/graph/layout.ts` if it ever bites).
- **Single package; bundle ships under `src/pflow/ui/static/`** via the `artifacts` force-include (see Deviations). `[ui]` gates only the *server* deps.

### Technical debt / deferred (deliberate)
- `visualize`/`analyze-cache` NOT migrated to `graph_service` (the point of H11 was to keep `ui` from being a *third* literal copy, not to rewrite the existing two — avoids perturbing Mermaid goldens). Low-risk follow-up.
- Frontend polish: **smart edge-router** (skip/loop edges overlap nodes in dense graphs — the biggest visual gap) and **gradient edges**, both deferred by the user.
- The **sdist** omits the bundle by design (end users install the prebuilt wheel; never run Node).

## Unexpected Discoveries (the GOLD — non-obvious, cost-a-future-agent-hours)
1. **Hatchling honors `.gitignore`.** `packages=` names a parent, but a gitignored child is still excluded. `artifacts` is the only mechanism to force-include a VCS-ignored build output. A zero-match `artifacts` glob is a silent no-op — the CI `test -f .../static/index.html` guard is the only thing that fails loudly.
2. **jsdom renders ZERO React Flow edge DOM** and logs no handle error. Any "no edge errors" assertion under jsdom is **theater** (it passes because no edges exist). Edge integrity MUST be a pure `flow.ts` test.
3. **A handle id of the wrong *type* silently drops the edge** (a `sourceHandle` that's secretly target-type). This bit the build twice. `handles.ts` makes `handleType` authoritative; `flow.test.ts` asserts every `sourceHandle` is source-type / `targetHandle` is target-type. **[verified end-to-end: 37 contract edges == 37 DOM edges in a real browser]**
4. **Body-to-body data flow only forms via workflow `inputs`, sub-workflow input bindings, or output `source:`** — NOT an arbitrary `${node.field}` in a regular leaf param (that draws no DATA_FLOW edge). Critical when reasoning about which `${ref}` becomes a chip/line.
5. **`StaticFiles(directory=...)` raises `RuntimeError` at *construction*** if the dir is missing. Since `static/` is gitignored+unbuilt in a source checkout, the mount is **conditional** (`server.py`): mount only if `static/index.html` exists, else a catch-all returns 503 with a `make ui-build` hint. API routes are registered BEFORE the catch-all and must stay that way.
6. **`fitView` needs the page to settle.** A screenshot taken before async ELK + the one-shot `fitView` rAF shows an un-fit top-left view. This is a *screenshot race*, not a bug — proven by in-page measurement after a 2.5s settle (graph fits with padding). **Discipline note: a screenshot of an async-layout page is context, not evidence; measure node bounds vs the pane.**
7. **An exotic non-JSON-native param value can't reach `/api/graph` through a real `.pflow.md`** — the markdown parser keeps an unquoted ISO date as a *string*, and validation rejects unknown params. The `_json(..., default=str)` guard is still load-bearing defense (nested/future date-typed values); pinned by a unit test on `_json` directly, not an unconstructable e2e fixture.

## Patterns Established (reuse these)
- **Renderer purity:** consume `GraphModel` + derived views only; import only `model`/`scope`; **reimplement** a shared leaf-walk locally (don't import `build.py`'s `_params_strings`) to keep the import boundary clean. Mechanized by `test_graph_model_purity.py`.
- **Additive edges, never subtractive:** `input_name=None` / collapse-hidden / group-host-suppressed endpoints all degrade to a node/group-level connection via a single `renderAnchor()` (frontend) and `_visible_anchor` (Python) — never dropped. A missing anchor *warns*, never silently drops.
- **Predicates-as-facts** at the model boundary; visual policy downstream.
- **Single orchestration seam with a typed error** (`graph_service`): `WorkflowGraphValidationError` carries `Diagnostic`s; one caller renders to CLI exit-1, another serializes to HTTP 422 — no re-derivation. A build bug on validated IR is NOT caught → loud 500, never a 200-with-empty-graph.
- **Atomic file write** (`_write_atomic`: tempfile + `os.replace`, dot-prefixed temp, chmod 600, no fsync for a regenerable cache) — the project-wide pattern for `~/.pflow/` state.
- **Frontend role-slot folders** (`api/ graph/ hooks/ utils/ views/ components/`): a one-file folder is intentional — it's where the next agent's code lands without a decision (e.g. `api/events.ts` for the overlay).

### Anti-patterns (do NOT)
- `bool(source_refs_in(str(value)))` for `is_dynamic` — false-positives on dict/list, disagrees with the edge builder.
- Copy Mermaid's `_edge_shadowed_for_render` into the contract.
- Reuse Mermaid's `_assign_flat_ids` or otherwise couple the two renderers.
- Add any render token (`elk`/`position`/`classDef`/`:::`/`parentNode`) to `model.py`/`build.py` — the purity guard fails.
- Assert "no edge errors" under jsdom.

## Breaking Changes
The static increment: none — `Node.params` is additive; `render_mermaid` ignores it. **Post-PR-#496:** `pflow visualize` was **renamed to `pflow mermaid`** (hard rename, no alias — no users; `pflow ui` is the new primary viewer verb), and the `required`-polarity contract fix changed ONE Mermaid golden (`document-processor.mmd` — the old `(string)` input-port label was the bug; now `(string, required)`). Base `pip install pflow` still gains no new *direct* runtime dep and no bundle.

## Future Considerations (extension points)
- **Task 169 (agent↔browser channel):** an SSE push + CLI focus/frame commands. The shipped live-source-update **poll** (`/api/version` → in-place reload via `useSourceWatch` + `remap.ts`) is its baseline — detection is separable from reaction, so 169's SSE can replace the poll with a push calling the same trigger; the `?focus=`/`node=`/`?focus=<edge id>` deep links + the screenshot skill are the addressing it reuses.
- **Live-run overlay (next increment):** subscribe in `web/src/api/`; node components already separate static data from a future `status` prop; join runtime events onto `RFRef`. The two substrates (structure vs. runtime JSONL) share ONLY the `NodeId` — do not couple them.
- **Visual editing increment:** `RFParam.source` (a `SourceRef{file,line}`) is the seam that makes write-back *surgical* (target a source line) rather than a destructive file regeneration.
- **A third renderer:** follow `render_react_flow`'s purity pattern; mint your own injective ids; don't touch the others.
- **Migrate `mermaid`/`analyze-cache` onto `graph_service`** when convenient (`visualize` was renamed `mermaid`; re-run Mermaid goldens after).

## AI Agent Guidance

### Quick start for related tasks — read first, in order
1. `src/pflow/ui/CLAUDE.md` — the **HTTP + contract consumption rules** (the four `/api/graph` status arms; the H5/H6/H8/H9 rendering rules that prevent information loss; the `?workflow=` auto-load; the SPA-404 caveat; the `artifacts` packaging note).
2. `src/pflow/core/workflow/graph/renderers/react_flow.py` — the contract's source of truth (frozen dataclasses + the `_ReactFlowRenderer`).
3. **`web/CLAUDE.md` + its `src/graph` / `components` / `hooks` / `utils` sub-docs** — the frontend's canonical *how* (cross-cutting invariants in the root; per-folder detail below). For ANY visual-layer work start HERE, not the progress log; verify in a real browser via `.claude/skills/screenshot-pflow-web-ui`.
4. `graph/CLAUDE.md` — model invariants + the Runtime Overlay Join Contract (a Task-133 coordination touch-point; don't change the identity seam).

### Common pitfalls (from this build)
- Editing a workflow example won't break the renderer tests *unless* it breaks an invariant — they assert properties, not frozen counts. But adding a `.pflow.md` under `examples/` auto-enrolls it in IR validation (`test_docs/test_example_validation.py` rglob).
- Don't remove `artifacts` from `pyproject.toml` or the CI `make ui-build`/`setup-node` steps — the `[ui]` wheel silently ships empty.
- A new edge-handle id scheme must register its type in `handles.ts` or React Flow drops the edge with no error.

### Test-first when modifying
- Touching `render_react_flow` / the model: run `test_graph_react_flow_renderer.py` + `test_graph_model_purity.py`; confirm Mermaid goldens (`test_mermaid_golden.py`) stay byte-identical.
- Touching the frontend transform: run `web` `flow.test.ts` (the handle-type invariant). jsdom can't catch edge drops — never rely on a render test for edge integrity.
- Touching the server: `tests/test_cli/test_ui.py` covers all four status arms + the lazy-import boundary; a real-browser check is the only way to validate the *visual* layer (the build-side logic is locked by tests).

---

*Generated from implementation + end-to-end verification context of Task 168.*
