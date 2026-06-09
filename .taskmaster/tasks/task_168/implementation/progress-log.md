# Task 168 — Implementation Progress Log

> **What this is:** the *journey* — the order decisions were actually made, the forks taken, the
> alternatives rejected, and the reasoning that lives in no other doc.
> **What this is NOT** (look elsewhere): the *what/why* → `task-168.md`; the *how* (phases, wire
> contract, file:line, the H1–H13 review fixes) → `implementation/implementation-plan.md`; the
> load-bearing "why a server" → `ADR-0005`; vocabulary → `CONTEXT.md`. This log *references* them;
> it never restates them.
>
> **Meta-state (2026-06-07):** design + plan + a 4-lens plan review are complete; the plan is approved.
> **Implementation is being carried out by a separate agent.** This log *seeds* the journey with the
> pre-implementation design story; the implementing agent appends the live build narrative below the line.

## The design journey (2026-06-06 → 06-07)

Entries in the order decisions were made. Each records the *trigger* (usually a user catch), not just
the outcome — that's the part the spec/plan/ADR don't carry.

**1. Entry point.** Opened right after Task 155 shipped the renderer-agnostic GraphModel. Stated goal:
*"design and plan for visualizing pflow workflows in a canvas like react flow."* Framed explicitly as
EXPLORE/DESIGN, not a build.

**2. Delivery architecture — the load-bearing fork (→ local server).** I opened recommending the
*cheapest* path: a self-contained static HTML **export (A)** over a local **server (B)** or **JSON-only
(C)**. The **user overturned it** with three arguments, two of which held: (a) *"would lean deps really
deter installers?"* → **conceded weak** (pflow already ships litellm/claude-agent-sdk; a server is
marginal); (b) a server makes live JSONL streaming intrinsically possible (a `file://` page can't tail a
growing log); (c) the local server is the cloud platform's analog → code reuse. → **Chose B.**
*Trigger: user pushback.* (A/C rejections recorded in ADR-0005.)

**3. Server tech (→ Starlette/ASGI, gated by a `[ui]` extra).** User caught the next over-claim:
*"why is Starlette better than stdlib?"* → **conceded**: for a static one-shot viewer stdlib suffices;
Starlette only earns it under concurrent live streams / WebSocket / cloud-ASGI parity. The leanness
worry was then neutralized *properly* — not by crippling the server (stdlib) but by gating it behind
`pflow[ui]`.

**4. The observability realization — and holding the line.** User surfaced the real destination:
*"it's for observability, right? all your workflows, concurrent runs, previous runs... maybe I'm getting
ahead of myself."* → Mapped onto the two-substrates frame: catalog + static structure = substrate-1
(now), live/concurrent/historical runs = substrate-2 (deferred event log). Resolution: **architect** for
observability, **build** the static slice first, **defer** the runtime layer — building it now would pin
a 5-consumer event schema before its consumers exist. Terminology sharpened: "invocation" → **Run**
(added to `CONTEXT.md`).

**5. "Build the runtime layer first?" — no.** User: *"should I build the runtime layer before the UI?
Is that Task 133?"* → Read Task 133: it's now a *decision record*, #382 (disk fix) is **already done**,
and the span-log (D1/D2/D3) is explicitly gated behind the static UI as its real consumer. Static-first
stands; the span schema is pinned *against* the UI, not before it.

**6. ADR scope (→ one ADR, not two).** Proposed ADR-0005 (delivery=server) — kept. Then over-proposed an
ADR-0006 for the wire contract; user: *"what do we need the ADR for?"* → **conceded**: the contract
shape is the *spec* of task 168 (rationale already in ADR-0005's Considerations), so a second ADR just
duplicates. No ADR-0006.

**7. Frontend stack & layout.** Vite + React + React Flow (v12 / `@xyflow/react`) + React Router v7 —
with the caveat RR7 must run **SPA/data mode, not framework/SSR** (else a Node server fights the Python
backend). Layout: user asked *"what is ELK/dagre for?"* and *"the modern way? only ELK?"* → **client-side
ELK** (handles pflow's nested containers; dagre = lighter fallback), the canonical React-Flow pattern.
Direction (LR/TD) confirmed a render **knob**, not baked into the model.

**8. Two display modes (from the user's reference images).** User shared a Flowise-style "advanced" view
+ two clean "beautiful" views, plus a progressive-disclosure idea (simple-until-you-click-a-node). →
Resolved as **one model at two densities** (advanced = priority; beautiful = a projection). The
**view-vs-edit fork** was named: this increment is read-only; visual *editing* is a deliberate later
axis (after overlay + HITL). I also over-claimed *"pflow is better than Flowise"*; user didn't follow it
→ **narrowed**: pflow's wiring is *derived from `${}` templates* so the viewer **reveals** implicit
structure — vs Flowise's hand-drawn wiring (not a general "better").

**9. Wire contract (→ Option B: a Python translator).** Fork: raw `asdict` (A) vs a `render_react_flow`
translator (B) vs hybrid (C). → **B** (asdict drops the derived predicates + ships nested `NodeId`). Two
simplifications I *introduced* (not user-driven), both to keep the FINAL code simpler: (a) mint a trivial
**injective** flat-id from the already-unique `NodeId` instead of reusing/refactoring Mermaid's
collision-patched `_assign_flat_ids` → `mermaid.py` is never touched; (b) **drop the dead `/events` SSE
stub** → overlay-readiness is the structural `ref` + pluggable data-loading, not a no-op route.

**10. Param values + the two AskUserQuestion forks.** Where values live: **`Node.params` model
extension (c1)** over renderer-joins-IR (c2) — renderer purity + one read-model + editor-ready. Then two
forks put to the user: **(i) large params** — user caught my sloppy *"in-memory IR"* phrasing (*"the UI
is always on, but pflow only runs while a workflow runs?"*) → I clarified the lifecycle (the server
re-parses the file *per request*; values are already in hand) → chose **inline-all** (kills the
lazy-fetch endpoint *and* the file-reader). **(ii) bundle packaging** → **single package** (bundle under
`src/pflow/ui/static/`, `[ui]` gates only server deps); rejected a separate `pflow-ui` package as
unearned two-pipeline complexity.

**11. Spec authored, mockup purged.** Wrote `task-168.md`. User flagged the earlier React-Flow *mockup*
(`loop-containers-mockup.html`) was **NOT** what they wanted → stripped every reference to it and to all
scratchpad docs; acceptance reframed as *"completeness, not matching a specific visual design."*

**12. Plan written against verified facts.** Three `pflow-codebase-searcher` passes converted every
integration point to file:line before a word of plan was written. The searcher finding that *shaped* the
design: large prompt/code values are **already inline** in the IR and there is **no** file-by-line reader
— which is what made inline-all the simpler call and retired the entire by-ref machinery.

## Verification passes — and what they changed

- **3 fact-finding searchers** (pre-plan) — turned assumptions into facts. Net: confirmed `Node` is
  mutable (one-line `params` add), confirmed the injective-id simplification is safe, and surfaced the
  no-file-reader fact above.
- **4-lens plan review** (`review-plan` / `feature-interactions` / `impact-completeness` /
  `silent-failures`) — **confirmed the core sound** (Mermaid byte-identical, invariants params-safe,
  injective ids, asdict round-trip, single render consumer) and surfaced **13 fixes (H1–H13)**, folded
  into the plan's *Review Hardening* section. The lone *critical* was **H1** (the release CI has no Node
  step → the `[ui]` wheel would have shipped an **empty** bundle). The highest-confidence correctness
  fixes were each raised independently by 3–4 lenses: `is_dynamic` must not use `str(value)` (H5);
  `input_name=None` is *common*, so edge rendering must be additive-not-subtractive (H6); the
  host-is-not-1:1 GraphModel shapes (H8). *(Contents of H1–H13 live in the plan — not restated here.)*

## Current state & open threads (2026-06-07)

- **Implementation:** in progress by a separate agent. Live build notes go below the line.
- **Open — H13 spec follow-up:** `task-168.md` still reads "large values lazy-fetched"; it must be
  updated to the decided **inline-all** approach so spec and plan agree. *(Not yet done.)*
- **Parallel work — Task 133:** cleared to proceed alongside — disjoint file sets (168 =
  `graph/` + `cli/` + `ui/` + `web/`; 133 = `runtime/trace` + `cache` + `instrumentation`). Two shared
  touch-points to coordinate: `graph/CLAUDE.md` (both may edit, different sections) and the **read-only
  `NodeId` / Runtime-Overlay-Join-Contract** identity seam — neither may change it; it's where the two
  substrates eventually meet.

---

## Implementation log

<!-- Implementing agent: append dated entries below as phases land. Capture DEVIATIONS from the plan,
     surprises, bugs, and decisions — not a restatement of the plan's steps. -->

_(No implementation entries yet — seeded 2026-06-07. Phase order per the plan: Node.params →
render_react_flow → pflow ui server + [ui] extra → web/ frontend → docs/purity/E2E.)_

### Phase 1 — `Node.params` model extension (2026-06-07) ✅

Added `Node.params: dict[str, Any]` (model.py, after `param_sources`) and populated it at the single
body-node construction site (build.py Pass A). Synthetic input/output/end nodes keep the default `{}`.

**Deviation (justified): used a named `_node_params(raw_node)` helper, not the plan's inline
`raw_node.get("params", {})`.** Two reasons: (1) H3 mandates a non-dict guard (unvalidated IR carries
`params: None`/str/list), and the inline walrus form H3 sketched
(`p if isinstance((p := ...), dict) else {}`) reads badly as a kwarg; (2) every other `Node` field here
is filled by a named helper (`_build_loop`/`_build_batch`/`_source_ref`/`_param_source_refs`) — a
`_node_params` helper keeps that symmetry and makes the guard named + independently testable. Mirrors the
existing `_params_strings(Any)→dict` guard shape exactly. Net: simpler final code, not just easier.

**Scope split on H3's test ask:** H3 wants a `params: None` case "routed through `render_react_flow`" —
deferred to Phase 2 (the renderer doesn't exist yet). Phase 1 covers the guard at the build level
(`None`/list/missing → `{}`) plus the full-multiline-prompt-inline + scalar-round-trip assertions.

**Verified:** insertion mid-dataclass is positional-safe (audited all `Node(...)` sites in src+tests —
none construct past `kind` positionally; `mermaid.py` only reads `Node`). Mermaid goldens **byte-identical**
(`test_mermaid_golden.py` + `test_graph_mermaid_renderer.py` green — params are Mermaid-invisible).
`test_graph_build.py` 42 passed; ruff + mypy clean on both changed files.

### Phase 2 — `render_react_flow` translator + typed contract (2026-06-07) ✅

New `renderers/react_flow.py` (`RFRef/RFParam/RFNode/RFEdge/RFGroup/RFGraph` frozen dataclasses +
`render_react_flow`), registered in both `__init__.py`s. Consumes only GraphModel + its derived views;
loop/batch/io/source emitted as plain dicts via `asdict()` on the frozen model sub-dataclasses (matches the
contract's `dict | None` typing, DRY). `shadowed` emits the model's **general** `graph.shadowed(edge)` fact,
never Mermaid's narrower `_edge_shadowed_for_render`. 17 new tests + mypy/ruff clean; Mermaid goldens still
byte-identical (77 graph tests green).

**Deviation 1 — `is_dynamic` mirrors `_params_strings` EXACTLY (str + dict-of-str leaves; NO list descent),
not the plan prose's "dict/list" (H5).** The load-bearing invariant is "can never disagree with the
DATA_FLOW edges", and the edge builder (`_params_strings`, build.py:761) is dict-only. List descent would
flag `is_dynamic=True` on a list param the edge builder ignores → a chip with no edge. Mirroring exactly
gives the clean property: `is_dynamic=True` ⟺ a DATA_FLOW edge exists (single-role case). Uses
`source_refs_in` (not `str(value)`), so literal operands like `${5}` correctly read static. The leaf walk is
**reimplemented locally**, not imported from build.py, to honor the H12 purity rule (renderer imports only
`model`/`scope` — verified).

**Deviation 2 — added `is_group_host: bool` to RFNode (mandated by H8(b), absent from the plan's dataclass
listing).** Defined it to mirror Mermaid's *actual* leaf-vs-group decision — literal batch OR
(workflow-host AND `unexpanded is None`) — not H8's looser "id ∈ any workflow/batch host". The looser rule
draws an empty group + suppresses the leaf box for an **unexpanded** dynamic batch (its batch container
exists but has no body), losing the unexpanded badge. The chosen rule is structural (does the host have an
expanded body?), not visual policy, so it doesn't violate the "don't copy Mermaid's `shadowed` render
policy" guard.

**H9 truncation (the one genuinely novel/risky bit) — implemented.** Representative-item truncation in the
translator: nodes/containers/edges under hidden literal-batch items (index ≥2 when count >4) are dropped,
mirroring Mermaid's `_visible_batch_indexes`; the full per-item descriptors still ride `RFNode.batch.items`
and the count via `batch.count`. Confirmed on real workflows: deep-research 41 model nodes → 29 RF (its
>4-item `reviews` batch collapses to 2 representatives, integrity intact); Task 163 harness 82→82 (no >4
literal batches), 131 KB payload.

**Fixture note:** the two-ref edge test uses workflow **inputs** (`${a.x} and ${b.y}` → two edges,
`input_name="prompt"` each), after empirically confirming body-to-body data flow forms via
inputs/sub-workflow-bindings/output-sources — **not** arbitrary `${node.field}` in a regular leaf param
(those draw no edge). This is a real property of the model worth knowing for Phase 4 chip rendering.

### Post-Phase-2 review + H13 spec follow-up (2026-06-07) ✅

**H13 closed.** Aligned `task-168.md` with the decided plan (5 edits): "large values lazy-fetched via
`source_ref`" → **inline-all + representative-batch-item truncation**; dropped the stale `/api` click-to-read
endpoint and the dead `/events` SSE stub from the Server§; and tightened the `is_dynamic` spec line from the
loose "value contains `${...}`" (the `str(value)` trap) to the precise `source_refs_in`-over-string-leaves
derivation actually implemented. Spec and plan now agree.

**Loose-ends pass — added 2 tests pinning the most consequential deviation.** The `is_group_host`
`unexpanded is None` guard (my Deviation 2) had no direct test. Added `test_unexpanded_node_keeps_its_reason_and_stays_a_leaf`
and `test_unexpanded_dynamic_batch_host_is_not_a_group` — the latter is the exact differentiator: a dynamic
batch whose child fails to resolve creates a batch container (host=node) *before* failing, so H8's looser
"id ∈ any container host" rule would mis-flag it as a group and draw a phantom empty box; the chosen
expanded-body rule keeps it a leaf with a badge. Now locked.

**Reviewed, judged acceptable (not defects), flag for Phase 4):**
- *Truncated-batch item↔group mapping is positional-by-`batch_index`, not by list order.* `RFNode.batch.items`
  keeps all N descriptors but only 2 item groups survive; the frontend must map a group to its item via the
  member ref's `ancestor_path[].batch_index` (the contract carries it), not by enumerating items. Contract is
  sufficient; ergonomics are Phase 4's.
- *`unexpanded_items` annotation keys are ints pre-JSON, strings post-`json.dumps`.* Inherent to JSON; the
  frontend reads string keys. Asserted on the int form (pre-wire) in the test.
- *Deeply-nested (>1 level) param refs read `is_dynamic=False`* — but this AGREES with the edge builder
  (`_params_strings` is also one-level), so the invariant holds; the raw value still shows the `${...}` text.

**Final state:** full `tests/test_core/` green (**3068 passed**); Mermaid goldens byte-identical; mypy + ruff
clean; renderer import-purity verified (model/scope only). Phases 1–2 are complete and I'm confident in them.

### 3-lens AI review + fixes (2026-06-07) ✅

Ran `review-silent-failures` / `review-simplicity` / `review-test-fidelity` in parallel against the staged
contract (it's an ideal standalone review unit: pure `GraphModel→RFGraph`, no consumers yet, so contract
flaws are cheapest to fix now). Simplicity came back **clean** (every increment over the plan's "~10 lines"
is earned under the deletion test; the `_string_leaves`↔`_params_strings` duplication is purity-forced, not a
smell). Three real findings, all fixed:

- **W1 (silent-failures) — REAL BUG, fixed.** H9 truncation silently dropped cross-boundary DATA_FLOW edges
  (kept source → hidden batch item) with no fallback — confirmed on the shipped `deep-research` example
  (`combine → summary@{2,3,4}`, 3 edges vanished). Mermaid preserves this via its arrow into the `xN` procs
  box; RF lost the "feeds the rest too" signal → information loss on the acceptance bar. **Fix:** new
  `_visible_anchor` re-attaches a truncated endpoint to its batch host (the same "degrade to node level,
  never omit" principle the contract already applies to `input_name=None`); the re-anchored endpoint's role
  label is cleared (it no longer names a host port), self-loops (both endpoints under one hidden item) drop,
  and the N identical host-level edges dedupe to one. Consolidated the truncation threshold into one
  `_is_hidden_index` helper shared by `_path_hidden` + `_visible_anchor`. Non-truncated graphs are byte-for-byte
  unchanged (dedupe is a no-op there). Pinned by `test_truncation_preserves_cross_boundary_dependency_via_host`.
- **W1 (test-fidelity) — `is_dynamic` test didn't catch its named trap.** Mutation-tested: swapping in
  `bool(source_refs_in(str(value)))` still passed. Added a `{"schema": {"deep": "${x}"}}` fixture (ref below
  the one-level leaf walk) — `str(value)` would false-positive, the leaf walk correctly reads `False`. Now the
  test pins Deviation 1's dict-only descent.
- **W2 (test-fidelity) — `RFEdge.shadowed` had ZERO coverage** (constant-folding it to `False` passed all
  tests). Added `test_shadowed_emits_the_models_general_fact` (hand-built shadowed structural edge → asserts
  the general `graph.shadowed` fact rides through, and data-flow edges read `False`).
- **S1 (minor) — added `depth_limit` reason through the renderer** (`max_depth=0`) so >1 unexpanded reason
  round-trips the contract, not just `unresolved`.

**Consciously deferred (not defects):** the `default=str` 500-vs-stringify boundary is a Phase-3 server concern
(intentional H2 tradeoff); a 0-item batch renders an empty group (exact Mermaid parity, recoverable via
`batch.count`) — Phase-4 frontend handles it. **Not done (judged not worth it):** the full `is_dynamic⟺edge`
biconditional matrix test (the nested-dict fixture already pins the trap); merging the two `unexpanded` tests
(both cover distinct code paths — the dynamic-batch one is the sole pin for Deviation 2).

**Post-review state:** full `tests/test_core/` green (**3071 passed**, +3); Mermaid goldens byte-identical;
full-tree mypy clean (231 files); ruff clean. Contract is now reviewed + hardened — ready to freeze for Phase 3.

### Phase 3 — `pflow ui` command + Starlette server + `[ui]` extra (2026-06-08) ✅

New files: `execution/graph_service.py` (the H11 helper), `ui/__init__.py`, `ui/server.py`,
`cli/commands/ui.py`, `tests/test_cli/test_ui.py` (12 tests). Edited: `cli/main.py` (register `ui_cmd`),
`pyproject.toml` (`[ui]` extra + dev deps), `.gitignore` (`src/pflow/ui/static/`). Full suite **7794
passed, 1 skipped**; `make check` clean (pre-commit/mypy/deptry); Mermaid goldens untouched. Real Task 163
harness renders through `/api/graph`: 82 nodes / 153 edges / 14 groups / 131 KB (matches Phase 2 numbers).

**The load-bearing surprise — starlette + uvicorn are ALREADY base deps (transitive via `mcp[cli]`).**
`mcp` requires `starlette>=0.27` + `uvicorn>=0.31.1`, both installed in every base env. Consequences: (1)
the `[ui]` extra adds **no new wheel** in practice — the "base install gains no new runtime dep" intent is
honored *and then some*; (2) `pflow ui` will actually start the server in any real env, so the
`pip install pflow[ui]` hint is a **defensive fallback**, not a path users hit. Still declared the extra
(a feature must own its direct deps, not lean on another's transitive ones — and it survives mcp dropping
them) and kept the hint. The H4 hint-test therefore can't uninstall starlette; it **simulates** the absent
extra via `patch.dict(sys.modules, {"uvicorn": None})` (a `None` entry forces `import uvicorn` →
ImportError). This is the correct robust verification given the dep reality.

**H11 helper placement — `execution/graph_service.py`, not `core/workflow/graph/`.** `resolve_validate_build`
orchestrates `resolve_workflow` + `WorkflowRunner.validate` (execution layer) + `build_graph` (core). Putting
it in `core` would invert layering (core → execution); `execution` is the natural orchestration home both
`cli/visualize`, `cli/ui`, and `ui/server` sit above. It raises `WorkflowGraphValidationError(PflowError)`
carrying the `Diagnostic` list (overrides `to_diagnostics()`), so a caller renders (CLI exit-1) or serializes
(server 422) without re-deriving. **`visualize`/`analyze-cache` NOT migrated** to it — deferred, per plan, to
avoid perturbing Mermaid goldens; `ui` is the sole consumer for now (the point of H11 is that `ui` isn't a
third literal copy, not that the existing two get rewritten now).

**H2 three failure arms, confirmed in code:** (a) producer bug inside `validate()` genuinely escapes
(`runner.py:404` `raise` for non-`WorkflowValidationError`/`CompilationError`) → helper's `except Exception`
wraps it → **422**; (b) `not vresult.valid` → **422**; (c) build/render bug on validated IR → **propagates →
loud 500** (only `WorkflowGraphValidationError` is caught in the endpoint). Added a 4th arm: missing
`?workflow=` → **400** (malformed request, distinct from "the named workflow is invalid" = 422). All four
tested. `_json(data, default=str)` centralizes the exotic-value tolerance.

**Deviation (justified) — conditional static mount + 503 fallback, not the plan's unconditional
`StaticFiles` mount.** `StaticFiles(directory=...)` raises `RuntimeError` at *construction* when the dir is
missing, and `src/pflow/ui/static/` is gitignored + unbuilt until Phase 4's `make ui-build`. An unconditional
mount would crash `create_app()` in **every** Phase-3 env and source checkout. So: mount `StaticFiles` only
when `static/index.html` exists, else a catch-all route returns a **503 with an agent-actionable hint**
("build it with `make ui-build`"). This is strictly better than `check_dir=False` (which 404s opaquely) and
than crashing. The API routes are registered *before* the catch-all so `/api/*` is never shadowed.

**Empirical finding (shaped the `default=str` test):** pflow's markdown param parser keeps an unquoted ISO
date (`2026-06-08`) as a **string**, not a YAML `datetime.date`; and validation **rejects unknown params**.
So an exotic non-JSON-native value can't reach `/api/graph` through a real `.pflow.md`. The `default=str`
guard is still load-bearing defense (nested values, future date-typed params), so I pinned it at the seam
directly — a `_json(...)` unit test with a `datetime.date` — rather than via an unconstructable end-to-end
fixture. This guards the exact JSONResponse-swap regression H2 names.

**H4 lazy boundary** verified in-process (pop `pflow.ui.server` + `pflow.cli.commands.ui` from `sys.modules`,
re-import the command module, assert the server stays unimported) — robust regardless of test order, no
subprocess needed.

**Deferred to later phases (not skipped):** the `web/` frontend + `make ui-build` target + the H1 CI
`setup-node`/build step (Phase 4); `ui/CLAUDE.md` + purity guard + docs (Phase 5). Phase 3 is the
server/CLI/extra/packaging slice only, per the plan's phasing.

### Phase 3 adversarial verification + 3-lens AI review (2026-06-08) ✅

Ran 3 read-only review agents (concurrency / silent-failures / simplicity, scoped to the **unstaged**
Phase-3 files only) in parallel with hands-on break attempts. Two real fixes landed; final suite **7796
passed, 1 skipped**, `make check` clean.

**THE last-20% find — cold-registry concurrency race (fixed at server level).** My green suite + an earlier
*warm* concurrency stress (60 concurrent reqs, all 200, deterministic) both MISSED it because they warmed the
registry sequentially first. A *cold* attack — empty `$HOME` so every concurrent first request triggers the
registry's lazy scan+write at once — reproduced a **user-facing failure: 9/16 concurrent first-requests
returned 422 ("unknown node type") with `Failed to parse registry JSON` torn-read errors and nondeterministic
payloads.** The browser firing `/api/catalog` + `/api/graph` together on a cold registry (fresh install /
post-upgrade) is exactly this. The concurrency agent *predicted* the race but rated it "low/self-correcting"
on the assumption the request reads in-memory scan results, not the torn file — empirically **false** under
concurrent cold scans. **Fix:** a Starlette `lifespan` warm (`_warm_registry` → `Registry().load()` once,
single-threaded, before serving) in `create_app()`. Re-running the identical attack → **all 200, 1
deterministic payload, 0 failures.** Root cause is pre-existing non-atomic registry writes
(`registry.py:381`); the deeper fix (atomic tempfile+os.replace, the pattern WorkflowManager/SettingsManager
already use) is a **separate pre-existing-code follow-up**, deliberately NOT pulled into Phase 3 scope —
flagged for a dedicated change. The startup warm fully closes the observed UI failure (mid-serving re-scan
needs a source-mtime change during a run — not a realistic single-user path).

**Port-in-use UX bug (found pre-review, fixed).** My `except OSError` around `uvicorn.run` was dead code —
uvicorn swallows the bind error and `sys.exit(1)`s with its own log line, and "Serving…" printed before the
doomed bind. Replaced with a `_port_available` pre-bind probe. Now: `Port N is already in use. → try a
different --port (e.g. --port N+1)`, exit 1, no misleading line. Verified via real subprocess + regression test.

**Silent-failures finding (fixed) — over-broad `except ImportError`.** The hint guard wrapped both `import
uvicorn` AND `from pflow.ui.server import create_app`, so a genuine ImportError *inside* the server module (a
future bad import / circular import) would mis-report as "install pflow[ui]" and swallow the real traceback.
Scoped the guard to the extra's own packages (`starlette`/`uvicorn`); the `create_app` import now sits outside
it → real bugs surface loudly.

**Other break attempts — all clean:** production bundle path (NEVER tested before; built a fake bundle →
index+assets serve, `/api/*` not shadowed by the catch-all mount, 404 on missing asset, 405 on POST, HEAD
200); adversarial `/api/graph?workflow=` inputs (cycle, self-referencing sub-workflow, missing file,
directory, `/etc/hosts`, path-traversal, name-with-spaces, 8 KB query) — every one a clean 422/200 in <0.1s,
**no hang, no 500**; real subprocess over a real socket (all prior tests were in-process/in-thread) → up in
~0.6s, harness renders 131 KB.

**Reviewed, consciously deferred (not defects for Phase 3), each with rationale:**
- *Broken saved workflows silently absent from `/api/catalog`* (silent-failures, sev 2) — inherited from
  `list_all()`'s documented skip (parity with `pflow list`); surfacing a `skipped[]` array is a frontend/product
  decision best made in Phase 4, and forcing it now means either touching `manager.py` (scope creep) or
  re-implementing the parse loop (the duplication the simplicity review just blessed the absence of).
- *`_port_available` returns False on ANY OSError* — `--port 80` (EACCES) is mislabeled "in use", but the
  advice ("try a different --port") stays correct; errno-branching is complexity for a rare path on an 8765-
  default dev tool.
- *SPA deep-route 404* — with a bundle present, `/graph/123` 404s (no index.html fallback). Latent **Phase-4**
  concern once React Router lands (needs an SPA catch-all or hash routing); v1 is single-view at `/`, so not a
  Phase-3 bug.

**Review verdicts:** simplicity — *clean bill of health, zero findings* (the `resolve_validate_build`
single-consumer extraction survives the deletion test: it de-duplicates a literal sequence that already exists
in `visualize.py`+`analyze_cache.py`). concurrency — thread-safe by construction except the one registry race
(now warmed away at the server boundary). silent-failures — LOW; the 422-never-empty invariant and the
422/500-never-200 split both traced clean.

### Root-cause fix replaces the workaround: atomic registry write, warm removed (2026-06-08) ✅

Simplicity/no-shortcuts pass. The cold-registry race was being held off by a *server-side warm*
(`_warm_registry` + lifespan) — a workaround that made the UI server correct but left the actual bug
(non-atomic registry writes) in place for every other consumer. Fixed the **root cause** instead: extracted
`Registry._write_atomic` (tempfile + `os.replace`) and routed all **three** duplicated non-atomic writes
(`save`, `set_metadata`, `_save_with_metadata`) through it. This is the pattern `WorkflowManager`/
`SettingsManager` already use — so it's *consistency*, not new complexity, and it's a net **simplification**
(3 duplicated `open(...,"w")+json.dump` blocks → 1 helper).

**Then deleted the warm.** Empirically isolated the two fixes: with the warm DISABLED and only the atomic
write present, the cold-concurrency attack passed **5/5 then 3/3 rounds** (24 concurrent first requests each,
all 200, deterministic). So the atomic write fixes the root cause on its own; the warm was redundant. Per the
deletion test (removing it *eliminates* complexity rather than moving it — correctness now lives at the
registry layer), removed `_warm_registry`, `_lifespan`, the `lifespan=` wiring, its test, and the `logging`/
`asynccontextmanager`/`AsyncIterator` imports. `server.py` is back to plain endpoints + `create_app`. For a
localhost single-user tool, a startup-warm once the registry is atomically safe was exactly the kind of
"solve it twice" the simplicity steer warns against.

**Regression guard (mutation-checked).** Three behavior tests in `test_registry.py::TestRegistryAtomicWrite`
pin the property without testing implementation: a *failed* write leaves the previous registry intact and
leaves no `.tmp` debris (the old truncate-and-write destroys the file mid-write). Mutation check confirmed:
reverting `_write_atomic` to the old `open(...,"w")` makes the test fail (original not preserved → file
truncated to `{"nodes": {"bad":`). Full suite **7801 passed**; `make check` clean; 119 registry tests green.

**Net:** the bug is fixed properly for ALL registry consumers (not just `pflow ui`), the server is *simpler*
than before the bug was found, and the fix is locked by a load-bearing test.

*Consistency pass on the new `_write_atomic`:* dot-prefixed temp file (`.registry.*.tmp`) matching
settings.py/manager.py (was a visible `tmpXXXX.tmp`); confirmed the registry file mode becomes `0o600`
(consistent with the rest of `~/.pflow/`, was `0o644`); no fsync (matches the existing pattern — a
regenerable cache needs none); verified cleanup holds even when `os.replace` itself fails, not just
`json.dump`; switched the debris assertions from `glob("*.tmp")` to `iterdir()` (glob's dotfile matching
varies across the 3.10–3.14 range, so the dot-prefix could have made them vacuous).

### Phase 4 handoff: `src/pflow/ui/CLAUDE.md` written (2026-06-08) ✅

A fresh Phase-4 agent sees the plan + `task-168.md` + this log + the code — **not this conversation**. Gaps:
the API error-envelope shapes / status arms, the `?workflow=` URL param the command opens with, the SPA-404 /
`base="./"` static behavior, and the contract rendering rules (`input_name=None`, `is_group_host`, batch
`ancestor_path[].batch_index` mapping) lived only in code or scattered Phase-2 entries; and `graph/CLAUDE.md`
doesn't yet mention the renderer. Consolidated all of it into **`src/pflow/ui/CLAUDE.md`** — the consumption
contract Phase 4 codes against (endpoints/statuses/error bodies, the `?workflow=` auto-load, the SPA-routing
caveat, the load-bearing RFGraph rendering rules with pointers to react_flow.py + the H-items, and the H1 CI
wiring). Pulled forward from Phase 5 deliberately: it documents the *completed* server Phase 4 consumes;
`web/CLAUDE.md` (the not-yet-built frontend) rightly stays Phase 5. **Left `graph/CLAUDE.md` untouched** —
it's a Task-133 coordination touch-point and discoverability is covered by ui/CLAUDE.md's pointer to
react_flow.py. Passes pre-commit + `tests/test_docs/`.

### Browser-open fixed: poll-until-ready, not a guessed delay (2026-06-08) ✅

Follow-up on a residual the verification round flagged and consciously deferred. The browser was opened by a
blind `threading.Timer(0.5, ...)` — a guess that races a cold-registry startup (browser opens → "connection
refused"). Root cause: `uvicorn.run()` blocks, so the lazy pattern fire-and-forgets a timer. Replaced with
`_open_browser_when_ready`: a daemon thread that polls the port (`connect_ex`) until it accepts, THEN opens.
Reliable because uvicorn binds the listening socket only *after* lifespan startup (the registry warm)
completes — so a successful connect means fully-ready-to-serve. Falls back to opening after a 15s timeout so a
stuck probe never silently skips the browser. 3 deterministic tests (helper waits-then-opens against a real
late-binding socket; fallback-opens when nothing listens; command wires the readiness thread with the right
host/port/url — guards against tested-but-unwired). Full suite 7799 passed; `make check` clean.

### Phase 4 — `web/` frontend (Vite + React + React Flow + ELK) (2026-06-08) ✅

New top-level `web/` tree: Vite + React 18 + `@xyflow/react` v12 + `elkjs`, building into `src/pflow/ui/static/`.
Modules mirror the plan: `types.ts` (hand-mirrored contract) → `api.ts` (the single data-loading seam, overlay-ready)
→ `flow.ts` (the RFGraph→React Flow transform — the heart) → `layout.ts` (client-side ELK) → `nodes/`
(Detailed/Compact/Group/End components) → `CatalogView`/`GraphView`/`ReadPanel`/`Toolbar`/`App`. All advertised
interactions implemented: collapse/expand (re-layout), focus+context (no re-layout), density toggle, LR/TD toggle,
click-to-read. `npm run build` → 1.79 MB bundle (ELK dominates, as the plan's Risks§ predicted); served + harness
renders (82 nodes) through the real Phase-3 server. tsc strict clean; 17 frontend tests (15 flow/format + 2 wiring).

**THE load-bearing find — the plan's packaging claim was WRONG; the `[ui]` wheel shipped an EMPTY bundle.** The plan
(and H1) asserted "No wheel-inclusion change needed: the bundle ships via `packages=["src/pflow"]`". Built a wheel and
inspected it: `pflow/ui/server.py` present, **`pflow/ui/static/` ABSENT**. Root cause: hatchling honors `.gitignore`
by default, and `src/pflow/ui/static/` is gitignored — so the on-disk bundle is force-EXCLUDED from the wheel, even
though `packages=` names its parent. H1 correctly identified the CI-has-no-Node gap but assumed the inclusion
mechanism worked; it didn't. **Fix:** `[tool.hatch.build.targets.wheel] artifacts = ["src/pflow/ui/static/**/*"]`
(hatchling's mechanism for force-including VCS-ignored build outputs). Re-inspected: `index.html` + `assets/*` now in
the wheel. This is the single most consequential Phase-4 correction — without it the entire `pflow[ui]` install path
ships a 404. (Sdist still lacks the bundle by design — end users install the prebuilt wheel; `pip install pflow[ui]`
prefers it. Matches "end users never run Node".)

**Brittle Phase-3 test exposed + fixed.** `test_root_without_bundle_returns_503_hint` asserted the static dir is
absent (`assert not (...static/index.html).exists()`) — true in a clean checkout, but Phase 4's `make ui-build`
makes the bundle exist locally, so the test became environment-dependent (green in CI, red after a local build).
Re-pinned it to `patch("pflow.ui.server._STATIC_DIR", tmp_path)` so it tests the fallback regardless of the ambient
bundle, and ADDED `test_built_bundle_is_served_and_api_is_not_shadowed` (the now-reachable served-bundle arm: `/`
serves index.html, assets resolve, `/api/*` not shadowed). Both deterministic.

**Key transform decisions (`flow.ts` — where the H-item rules live):**
- *Split structural build from focus.* `buildFlow(graph, {density,direction,collapsed})` feeds ELK; `applyFocus(nodes,
  edges, focus)` is a separate cheap pass returning NEW arrays (so React re-renders) — focus/selection never re-run
  layout (plan: focus is "the same data + an interaction"); collapse/density/direction do.
- *Groups become React Flow group nodes; `is_group_host` leaves are suppressed* (H8). Edges into a suppressed host
  re-anchor to its OUTERMOST group (a host is not 1:1 with a group — dynamic-batch-of-subworkflow has two). A single
  `renderAnchor()` maps any contract node id → its on-canvas representative (itself / its group / the outermost
  collapsed ancestor), so EVERY edge is additive — `input_name=None`, collapse-hidden, and host-suppressed endpoints
  all degrade to a node/group-level connection, never dropped (H6/W1). All edge handle ids are guaranteed to exist on
  the rendered node (param handle only when a matching param row exists, else `NODE_IN`), so React Flow never floats an
  edge to a missing handle.
- *Per-row connection handles.* DetailedNode renders a left target handle per param row inside `position:relative`
  rows (React Flow measures DOM rects — no pixel math), so a `${ref}` line lands on its exact row; output fields become
  right-side source ports. Verified by behavior tests, incl. `${a.x} and ${b.y}` → two edges onto one `prompt` handle.

**Build wiring (H1):** `make ui-build` (`cd web && npm ci && npm run build`); `make build` now depends on it so local
wheels include the bundle; the release CI (`on-release-main.yml` publish job) gains `actions/setup-node@v4` + `make
ui-build` BEFORE `uv build`. `web/package-lock.json` committed (npm ci needs it); `node_modules`/`dist` gitignored.

**Bundle size (1.79 MB / 555 KB gzip):** ELK is ~80% of it. Acceptable in the base wheel (disk, not runtime — plan
Risks§). Left as-is for v1; if it bites, lazy-load elkjs as an async chunk or drop to dagre — isolated to `layout.ts`.

**Deliberately NOT done (Phase 5, per the stop-after-4 instruction):** `web/CLAUDE.md`, the model-purity guard test,
the CLAUDE.md updates, and the full `make check`/`make test` final gate. Everything is staged for them.

### Phase 4 review (4 agents) + fixes + frontend restructure (2026-06-08) ✅

Ran 4 review agents in parallel (simplicity / silent-failures / feature-interactions / test-fidelity) scoped to the
unstaged Phase-4 files, with hands-on verification alongside. Simplicity returned a near-clean bill (one dedup). The
other three surfaced real, fixable gaps — all addressed. Final: web **24 tests** (4 files) + Python **17 ui tests**
green; tsc strict + production build clean; wheel still bundles `index.html`+`assets/`.

**Silent-failures (the consequential ones — "never crash / never a silent blank canvas"):**
- *C1 — unhandled `layoutGraph()` rejection → permanent "Laying out…".* The ELK effect had no `.catch`; an ELK throw
  hung the canvas forever on a successfully-fetched workflow. Fixed: the layout promise now `.catch`es into the error
  banner (status `"error"`), and a successful re-layout clears a stale layout error. Pinned by a GraphView test that
  mocks `layoutGraph` to reject and asserts the banner (not "Laying out…").
- *C2 — no Error Boundary + unchecked 200 cast → white screen.* Added `ErrorBoundary` around `<App>` (catch-all → banner,
  not a blank page), and `fetchGraph` now validates the 200 is the contract shape (`isRFGraph`) and throws an `ApiError`
  instead of casting a lie that `buildFlow` would crash on mid-render. Both pinned (`api/client.test.ts` malformed-200).
- *observability warns* — `flow.ts` warns (not silently drops) if an edge has no on-canvas anchor; `layout.ts` warns if
  ELK omits a node; degenerate 0-node graph shows "no visible structure" instead of a silent void.

**Test-fidelity (all real coverage gaps, not wrong assertions):** added the missing-handle fallback test (`input_name`
naming a non-existent param → `NODE_IN`, the literal guard that prevents a floated/dropped edge); the two-group-host
outer-selection test (the H8 dynamic-batch-of-subworkflow case — both groups at the same depth, so the parent-filter,
not depth, picks the outer; this is the exact logic I'd verified against real `run-cycle.pflow.md`); the `applyFocus`
dimmed-edge branch; strengthened the collapse test with a re-anchored-handle assertion; `GraphView` now rejects with the
**real** `ApiError` (was a hand-rolled stub testing a fiction); `test_ui.py` served-bundle test asserts `api.json()==[]`
(proves `/api/*` returns catalog JSON, not a shadowing `index.html`).

**Feature-interactions:** the headline packaging interaction was confirmed handled (wheel bundles, sdist omits by design,
CI builds before `uv build`). Two residuals fixed: (W1) added a CI `test -f .../static/index.html` guard so a missing
bundle fails LOUDLY instead of `uv build` silently shipping empty (hatchling treats a zero-match `artifacts` glob as a
no-op — the only guard is this assertion + CI ordering); (W2) corrected the stale `ui/CLAUDE.md` line that still claimed
"no wheel-config change needed" — it now documents that `artifacts` is load-bearing and must not be removed.

**Simplicity:** consolidated the whitespace-collapse/truncate logic duplicated in `DetailedNode` into the shared
`utils/format` (`collapseWhitespace`/`truncate`) — the one real cross-file duplication. Reviewer otherwise judged the
`flow.ts` transform, the node-component split, and the abstractions all earned (pass the deletion test).

**Frontend restructure → role-slot layout (user-driven).** The flat `src/` (~25 loose files) became role folders, after
aligning on the principle *folders are conventions future agents follow* (a one-file `hooks/` is good — it's where the
overlay's event hook lands without the agent deciding). Final:
`api/` (client; `events.ts` plugs in here for the overlay) · `graph/` (pure transform: flow/layout/handles, React-free
so its tests run node-env) · `hooks/` (useWorkflowGraph) · `utils/` (format) · `views/` (CatalogView/GraphView — the
screens `App` switches between) · `components/` (Toolbar/ReadPanel/ErrorBoundary/nodes — reusable pieces) · `test/`
(rf-jsdom) · root: shell + `types.ts` (the single cohesive contract). The data pipeline was extracted from `GraphView`
into `useWorkflowGraph` — GraphView is now pure presentation + interaction; the hook owns fetch→build→layout→focus and is
where C1/empty-status live. types.ts stays a single root file (folder-with-one-file there is just indirection on the
most-imported module).

**Staging note (for whoever commits):** the entire `web/` tree is currently untracked — it must be `git add`ed *with
`web/package-lock.json`* (npm ci in CI needs the lock); `node_modules`/`dist`/`src/pflow/ui/static` stay gitignored.

### Visual iteration: loop arcs + density-governed edges (2026-06-08, user-driven)

Two design changes after a user review of the running UI. Both are **pure frontend visual policy — zero contract change.** web **30 tests** (+6); tsc + build clean.

**Loops were only a text badge — now a synthesized loop-back arc.** A loop is a `LoopSpec` on a node, not an edge, so `flow.ts` synthesizes a self-loop edge per looped node, anchored to the node — or to its **group** when it's a looped sub-workflow host (the arc wraps the container). A new `LoopEdge` custom edge draws a smooth amber arc (bulge perpendicular to the source→target chord, so it reads in both LR and TD) labeled `↻ while/until <condition> ≤ cap`. Self-loops are filtered out of ELK (`layout.ts`) — ELK never routes them; LoopEdge owns the path. The redundant loop *badge* was removed (the arc + read-panel carry it). Skips a loop whose node is hidden inside a *collapsed ancestor* (only draws on the box that actually loops). Chosen over a loop-frame/stacked-deck after putting the options to the user (mockups) — arc won as the most universally legible.

**Density now governs EDGE density, with progressive disclosure (the key user insight).** Beautiful mode was drawing all the green `${ref}` data-flow lines — incoherent, since the data wiring is literally the ports/chips of the *advanced* node. Fix: data-flow edges are **built but `hidden` in beautiful** (control-flow skeleton only — slate/blue), and `applyFocus` **reveals just the focused node's** data lines on click (hidden elsewhere). The elegant bit: no density flag in `applyFocus` — it reveals any *default-hidden* edge incident to the focus, and only buildFlow (which knows density) sets the default. Hidden data-flow is also excluded from ELK so the beautiful layout stays tight; revealed-on-focus edges route best-effort through it (fine for an on-demand reveal). Shadow-dimming now only applies in advanced (beautiful's control edges show full-strength since the data lines that shadowed them are hidden). Sequential edges got a clearer stroke so the skeleton reads as one coherent flow. Pinned by tests: beautiful hides data-flow / advanced shows it; focusing a node reveals only its incident data line; clearing focus re-hides.

### Visual iteration 2: readability batch — spacing, color, forks, IO pills (2026-06-08, user-driven)

After the user reviewed the running UI on the harness (everything cramped on one line, blending together, forks unclear). Diagnosis: the "line" is honest (a linear pipeline IS a line) — the real bugs were **tight spacing + monochrome nodes + IO-card bloat**. User chose (via mockups) the readability batch, keep LR, defer gradient edges. web **34 tests** (+4); tsc + build clean. All visual policy — **zero contract change.**

- **Spacing doubled** (`layout.ts`): `nodeNodeBetweenLayers` 64→130, `nodeNode` 36→64, + `NETWORK_SIMPLEX` placement. A cramped pipeline reads as a smear; this gives it air.
- **Color nodes by type** (`utils/format.kindColor` + a `--kind` CSS var on each node): the node's identity color (shell=emerald, http=sky, llm/claude=violet, code=amber, …) on the left border + glyph. **Control edges take their source node's type color** (inline `style.stroke` + matching arrowhead) — the stepping stone to the deferred source→target gradient. error/end/data/loop keep semantic colors. This is what kills "blends together."
- **IO nodes → compact port pills** (new `port` node type + `PortNode`): the single biggest declutter — the harness's **53 IO nodes** (43 input + 10 output) were full-size cards bloating every sub-workflow box; now small pills. A `flow.ts` handle guard routes every edge to/from an IO node to node-level handles (port pills have no per-field handles, so nothing floats).
- **Forks = labeled border handles** (n8n-Switch style; `BranchPorts`, `branchHandle`): a decision node's branch outcomes (`fix-tests`/`push`/…) render as one labeled source handle per outcome on the right border, each line leaving its own named handle — clear which value goes where. **Shown in BOTH densities** (a fork is structure, not advanced data detail), so `CompactNode` became a small card (header + branch rows) instead of a pill. Branch labels no longer ride the edge mid-line. Sized into `leafSize` (branch rows in both densities).
- **Smooth edges**: all edges now bezier (`type: "default"`) — the curvy look.

Pinned by tests: branch edges use `branchHandle(label)` and the node carries `branchLabels` (both densities); IO nodes emit type `port`; a control edge is stroked with its source node's `kindColor`. **Deferred (next visual step):** source→target **gradient** edges (per-edge SVG `<linearGradient>` + custom edge — not a React Flow built-in; the user opted to ship this batch first). *(Superseded below: the `port`-pill rendering was replaced by the consolidated ports node.)*

### Visual iteration 4: IO ports → one consolidated "table" node (2026-06-08, user-driven, planned)

User insight: the clutter wasn't *that* inputs are shown, it's that **each input was its own node**. Fix (the React Flow table-node pattern): `input_wrapper`/`output_wrapper` → ONE **Inputs**/**Outputs** node with a **row + handle per port**, shown in **both** densities; row-level focus preserves "click an input → see its connections." Planned first (the user approved the plan), then built. web **37 tests**; tsc + build clean. Pure frontend — zero contract change.

- **flow.ts:** `ioWrappers` → one `type:"ports"` node per wrapper (id reuses the wrapper's `g*` id; rows = its member IO nodes). IO member nodes are no longer emitted; `ioNodeToPort` maps each to `(portsNodeId, portHandle(id))`. `renderAnchor` resolves an IO node to its ports node; the handle functions return the **row handle** when the edge reaches the ports node (else node-level, for a collapsed-past re-anchor). The whole `showIO`/hide-IO-in-beautiful/drop-IO-edges machinery is **deleted** — IO is always shown; its edges are ordinary data-flow (hidden-in-beautiful, revealed on focus).
- **Row-level focus (the one new mechanic):** every edge now carries `data.from`/`data.to` (its *original* contract endpoints). `applyFocus` matches incidence via `edgeTouchesFocus` = flow endpoints **OR** `data.from`/`to` — so focus can be a node id, the ports-node id, or a **single port id** (a row), and a port reveals just its own lines even though its edges re-anchor onto the shared ports node. The ports node highlights its `focusedPortId` row. Clicking a row drives this via a small `InteractionContext` (`focusPort`) — keeps node `data` callback-free.
- **Components:** new `PortsNode` (header + clickable rows + per-row handle), `PortNode` deleted, `ports` registered (drop `port`). CSS swapped pill → table.
- **Net effect:** one tidy Inputs box per level instead of N floating pills; no floating (one node, ELK-positioned near consumers via data-flow-in-layout); click a row → that input's line(s) + consumer(s) light up; click a consumer → all its input lines reveal; advanced shows everything. Removes more code than it adds.

**Follow-up fix — every port row needs BOTH handles (the missing binding edges).** First cut gave each row only a *source* handle (feed-out). But a port bridges two scopes: an **input** RECEIVES from the parent (binding) AND feeds consumers; an **output** RECEIVES from a producer AND feeds the parent. The contract has these "receive" edges (verified: 30 into input ports like `repo_dir→repo_dir`, 11 into output ports like `check-validate→ok`) — but they targeted the row's source-type handle, so React Flow couldn't attach them and they silently didn't draw (the user spotted the missing lines). Fix: each row now renders a **target** handle (`portTargetHandle`, left/top — receives) AND a **source** handle (`portHandle`, right/bottom — feeds); `targetHandleFor` routes an IO target to `portTargetHandle`. Pinned by an assertion that a binding edge lands on the target handle.

### Visual iteration 3: IO-in-beautiful + layout philosophy resolved (2026-06-08, user-driven)

Reviewing the running UI, the user hit two layout problems, both now resolved. web **35 tests**; tsc + build clean.

- **IO ports float in beautiful + sub-workflows look empty.** Root cause: IO nodes connect ONLY via data-flow, which beautiful hid AND `layout.ts` excluded from ELK → disconnected islands ELK parked off to the side. Fix (two parts): (1) **hide IO ports + their wrapper groups in beautiful** (shown in advanced, where they read fine — the user's call; IO-touching edges are dropped silently, before `renderAnchor`, so it's not mistaken for a broken-anchor warn); (2) **feed data-flow edges to ELK for layout even when they render hidden** — layout reflects ALL structure so a data-only node never floats; density decides only what's *drawn*. Pinned by a test (advanced shows the IO pill + wrapper; beautiful hides port + wrapper + its edge, body still renders).

- **"Everything on a thin line" — chased, then resolved as a non-problem.** Tried ELK `wrapping` (fold the chain into rows). Verified it works (1 row → 3, at root AND — after applying the options to every composite, not just root — inside nested groups). But the user correctly rejected it: wrapping cuts at an arbitrary **width** threshold and sweeps the inter-row edge back to the far left (a "carriage return"), which isn't how n8n works. **The real finding (verified against the contract):** the harness's `check-groups` "branches" reconverge into a forward chain (`review-round → simplify → verify`; `check-groups → simplify` feeds the same chain), so they're *sequential*, not independent — ELK correctly lines them up horizontally. **This workflow is structurally a pipeline; a pipeline IS a line (n8n would draw it the same).** The fork is shown via the labeled border handles, not by spreading. **Decision: no wrapping.** The honest n8n model — sequence flows one direction; a *genuinely* independent fork fans down on its own (verified: a Switch→3-independent-targets lays them in one column, y-spread 280). Don't re-litigate "make the pipeline 2D" — it's 1D by structure.

### Small feature: beautiful labels its revealed data lines (2026-06-08)

User clicked `fetch-data` in beautiful and asked where `stdout` went. Cause: output/input field *names* are advanced-only (node rows); a compact node shows only its name, so a revealed data line had nowhere to surface the field. Fix: in beautiful, a data-flow edge is labeled with what flows (`output_field → input_name`, e.g. `stdout → data`); advanced stays unlabeled (the rows already say it). Pinned by a test. (Also confirmed `conditional-branching` genuinely has 0 inputs — `fetch-data` makes its own data — so the absent Inputs node is correct, not a bug.)

### Docs + requirements persisted (2026-06-08)

- New **`visualization-requirements.md`** (task folder) — a one-page checklist of the **hard requirements** (handles land exactly; no info-loss in advanced; consolidated dual-handle ports nodes; row-level focus; beautiful = control skeleton + click-to-reveal; explicit fork handles), **decided principles** (a linear pipeline IS a line; layout reflects all structure even when hidden; focus never re-layouts), **implemented**, **wanted/deferred** (gradient edges; smart edge-router), and the deferred increments (overlay, editing). The *what*, complementing this log's *why* and the CLAUDE.md *how*.
- **`web/CLAUDE.md`** (already existed) got the consolidated-ports + dual-handle + row-level-focus concepts and the jsdom/handle-type finding below. **`ui/CLAUDE.md`** stale path fixed (`api.ts` → `api/client.ts`). Left `execution/`, `registry/`, `graph/` CLAUDE.mds alone (Phase-1–3 / Task-133 coordination, not this session's authored work).

### Finalize verification + a real test-quality pass (2026-06-08)

**Ran the full gates** (hadn't since Phase 3): `make test` **7802 passed / 1 skipped**; `make check` clean (lock, pre-commit, mypy 235 files, deptry). *Gotcha surfaced:* once `web/` is staged, pre-commit's `pretty-format-json` reformats `web/` JSON (it expanded `tsconfig.json`'s inline arrays); it auto-fixes on first run, then converges. `package.json`/`package-lock.json` were already compliant.

**Test-quality pass (the bar is "passing the *right* thing", not "passing").** A probe revealed the load-bearing fact: **React Flow renders ZERO edge DOM under jsdom** and logs no handle error — so the existing GraphView "no edge/handle errors" assertion was **theater** (passed because no edges exist, not because they're correct). Acted:
- **Removed** that theater assertion (kept the mount test's real parts: pipeline mounts, nodes + `${ref}` chip render) and **removed** a tautological "edges take the source color" change-detector.
- **Added the HANDLE-TYPE INVARIANT** — the recurring bug was always a handle-*type* mismatch (a `sourceHandle` that's secretly target-type → React Flow silently drops the edge; it bit us twice). Made `handleType` authoritative in `handles.ts` (each id scheme → "source"/"target", throws on unknown); a pure `flow.test.ts` test asserts every edge's `sourceHandle` is source-type and `targetHandle` is target-type across a graph exercising all schemes (ports/branch/param/output/node-level). **Mutation-verified:** reverting the port-binding fix makes it fail. This is the only reliable catch for the silent-drop class — jsdom can't, so edge integrity is a pure test, never a render test.

**Honest residual (stated, not hidden):** built blind (no canvas) — a *component* rendering the wrong handle type, or visual/layout ugliness, still rests on the user's eyes; the *build-side* logic where the real bugs lived is now locked. Known-deferred: the **smart edge-router** (skip/loop edges overlap nodes in dense graphs — biggest quality gap) and **gradient edges**. Final: web **38 tests**, tsc strict + build clean; Python **7802** + `make check` clean.

### Phase 5 — docs + model-purity guard + final gates (2026-06-08) ✅

**Scope reality: most of Phase 5 had already crept into Phase 3/4.** `ui/CLAUDE.md` (Phase-3 handoff), `web/CLAUDE.md` (Phase-4 + visual-iteration entries), and the full `make check`/`make test` gates were all already landed and committed. The *genuine* Phase-5 remainder was narrow: (1) `graph/CLAUDE.md` — Phase 4 explicitly **deferred** it ("Left graph/CLAUDE.md untouched"); (2) the stale parent map in `core/workflow/CLAUDE.md`; (3) the H12 purity guard; (4) re-running the gates. No production code changed — Phase 5 is docs + one meta-test.

**`graph/CLAUDE.md`** (+ parent `core/workflow/CLAUDE.md`): added `react_flow.py` to both File Maps + a Renderer-Notes paragraph (injective `n{i}`/`g{j}` ids — NOT Mermaid's collision-patched scheme, no shared helpers; emits the **general** `shadowed()` fact not Mermaid's render policy; truncation lives in the renderer; pointer to `ui/CLAUDE.md` for the wire contract). Added a `Node.params` invariant bullet (inline values + the non-dict guard + Mermaid-invisibility). Generalized the intro's "no Mermaid syntax" → "no render syntax (Mermaid/React Flow/ELK)" with a pointer to the new purity test. Added `render_react_flow` to the parent Key-Symbols row. **Left the "Runtime Overlay Join Contract" section untouched** — it's the read-only Task-133 coordination seam.

**Purity guard `tests/test_core/test_graph_model_purity.py` (H12).** Two tests: (a) `model.py`/`build.py` carry no render tokens (`elk`/`position`/`classDef`/`:::`/`parentNode`); (b) AST-check that `react_flow.py` imports only `graph.model`/`graph.scope`, never `mermaid`.

- **The load-bearing insight that keeps the guard honest:** the forbidden set is render *syntax* tokens, NOT the words "mermaid"/"react flow" — both appear as legitimate **prose** in the model (`model.py:154` "Mermaid end-sink"; `build.py:721` "React Flow renderer" docstring). Forbidding the prose words would false-fail the guard; forbidding the syntax tokens catches the real leak (a layout coord, a Mermaid directive, RF's `parentNode` field). Verified both prose lines survive.
- **H12 word-boundary precision:** alphanumeric tokens match on `\b…\b` (case-insensitive) so `position` flags but `decomposition`/`composition` don't; `:::` (punctuation, no word boundary) matches as a substring. Mutation-checked the helpers directly (standalone `position`/`ClassDef`/`elk`/`:::` flag with correct line numbers; `decomposition`/`composition` don't; a `mermaid` import and a non-allowed graph import are both caught).
- **Deviation from plan-prose, justified:** scanned **model.py + build.py only** (the two files the plan names + the two where render syntax could plausibly creep — `scope.py` is already a pure regex extractor, out of the named set). Scoped the import-purity check to **react_flow.py only** (not a symmetric mermaid check) — the plan keeps `mermaid.py` untouched, and `mermaid.py` legitimately imports `scope.refs_in` too, so a symmetric assertion would add nothing.

**Gates (the Phase-5 deliverable):** `make check` clean (ruff, ruff-format, mypy **235 files**, deptry, pre-commit); `make test` **7804 passed / 1 skipped** (+2 purity tests). No production code touched, so Mermaid goldens are inherently byte-identical and the server/contract runtime is unchanged from committed Phase 4 — re-verification of runtime behavior would be redundant.

**Not re-run (stated, not skipped):** the browser E2E (plan steps 3–5: `pflow ui` renders the harness + six patterns) and `make ui-build` were verified by the Phase-4 agent (the 131 KB harness render, the empty-wheel `artifacts` fix). Phase 5 changed zero runtime/frontend code, so those outcomes can't have regressed; re-driving a browser here adds no signal — the one genuinely un-re-verified item is the *visual* "no information loss" bar, which rests on the user's eyes (the build-side contract logic is locked by tests).

**Staging correction:** earlier Phase-4 log entries flagged `web/` as untracked-needs-`git add` — that was true when written but is now **stale**: `web/` (38 files incl. `package-lock.json`) was committed in `38fd6fe0` ("phase 4 implemented"). The only uncommitted Phase-5 work is the 2 CLAUDE.md edits + the new purity test + this log; a normal `git add` of the new test is all that's needed.

### Adversarial verification pass — whole feature, in a REAL browser (2026-06-08) ✅

Verification-specialist pass: treated the green suite as *context, not evidence* and tried to break the whole Task 168 feature end-to-end (beyond Phase-5 scope), closing the implementer's own **"built blind — no canvas"** residual.

- **Contract on real data (not synthetic unit graphs):** swept **all 58 buildable example workflows** through the exact server path (`resolve_validate_build → render_react_flow`). **0 referential-integrity failures**, **0 JSON round-trip failures**, and — matching each model node to its RF node by structural `ref` — **0 pure information-loss edges** (every edge whose both endpoints survive truncation is present). The 3 truncation-boundary edges that exist (deep-research `combine → summary@{2,3,4}`, the W1 case) **all survive** via host re-anchoring. The contract's headline "no information loss" claim holds on real workflows.
- **Server robustness (live, real socket):** every adversarial `/api/graph?workflow=` input — empty, nonexistent, `/etc/hosts`, `../../../etc/passwd`, a directory, missing param, `POST` — returns a clean `400/422/405` in <0.1s, **no 500, no hang**; the real built bundle serves at `/`.
- **Frontend in a real headless Chrome** (the part jsdom provably can't test): rendered the **hardest** workflow (deep-research — batch truncation + 16 nested groups) and the **largest** (82-node harness). Measured after a 2.5s settle: **`edgeCount` 37 in the DOM == 37 in the contract** (the silent-edge-drop class that bit the build twice — confirmed clean end-to-end), handles land on the correct param rows, nested groups + color-by-type render, `fitView` fits with padding, and the density toggle drops **37 → 7** edges (beautiful = control skeleton only, exactly as claimed).
- **Corrected one false hypothesis (discipline note):** a first screenshot looked "un-fit on load" → I suspected a `fitView` timing bug. Rigorous in-page measurement after settle disproved it: the graph fits correctly; the un-fit shot was the `shoot` skill racing the async ELK layout (its documented "heavy async page" caveat), **not** a product bug. Screenshot = context; the post-settle measurement = evidence.

**Verdict:** tried hard to break it; **found no real bugs.** The "built blind" residual is now closed — the feature is verified rendering correctly in a real browser on its two worst-case workflows. (My Phase-5 changes are runtime-inert: the server ran from this worktree with them present and behaved identically.)

### Test-quality fix: real-workflow test now guards "no information loss", not just integrity (2026-06-08) ✅

The verification pass surfaced one genuinely shallow assertion (the bar is *passing the right thing*, not passing). `test_real_workflows_render_with_referential_integrity` rendered 6 real workflows (incl. `conditional-branching`, `error-handling`, the harness) but asserted **only referential integrity** — which **cannot catch a dropped edge** (a missing edge is still internally consistent). So a regression that silently dropped a branch / error / data-flow edge between two *visible* nodes on a real workflow would pass every test: the synthetic tests only check hand-built shapes, and this one only checked internal consistency. The W1 cross-boundary drop is well-pinned, but **only synthetically** (`test_truncation_preserves_cross_boundary_dependency_via_host`).

Fix (not new coverage — a missing assertion on an existing test): added `_assert_no_dropped_edges(graph, rf)` — match each model node to its RF node by **structural ref**, then assert every model edge whose both endpoints survive is present, across ALL edge kinds; truncation-hidden endpoints are skipped (their re-anchoring stays pinned by the synthetic W1 test). Renamed the test to `…_without_information_loss`. This is exactly the model→RF check my corpus sweep did manually, made permanent on the 6 representative shapes.

**Mutation-verified (the only thing that makes it worth keeping):** injected an edge-drop into the renderer's `_resolve_edges` (skip `branch` edges) → the test **fails on both `conditional-branching` and the harness** with a precise message (`check-validate -[branch]-> fix-tests … silently dropped`). The old integrity-only assertion passed that same mutation. Reverted clean; full suite **7804 passed**, `make check` clean.

Considered and **rejected** as low-value: expanding the test to all 58 examples (the 6 are deliberately chosen for structural variety — the rest are redundant shapes, i.e. coverage-padding); a real-data W1 boundary check (reimplements `_visible_anchor` in the test for marginal gain over the strong synthetic pin); browser-based CI tests (high-maintenance/flaky — manual browser verification is the right level for the visual layer).

### Task review + PR opened — task landed (2026-06-08) ✅

Wrote `task-review.md` (the knowledge-transfer doc for future agents: deviations, the GOLD gotchas, patterns/anti-patterns, the forward-compat overlay seam) with explicit trust boundaries marked (`[verified]` = what I implemented/verified end-to-end; `[relayed+read]` = Phases 1–4 internals from this log cross-checked against the committed code). Committed Phase 5 as `7d2f73b0` on top of `38fd6fe0` ("phase 4 implemented") — docs + the two mutation-verified guards + review + log; no production-code changes. Pushed the branch (was unpushed) and opened **PR #496** (`feat/workflow-visualization-static-viewer → main`, +10858/−32, 67 files, 2 commits).

**Issue-link decision (the one fork at PR time):** verified **no GitHub issue maps to Task 168** — issue #168 is an unrelated *closed* issue (template-consumer debt), and #452 is about loop-edge rendering in the *Mermaid* `visualize`, a sibling concern in a different renderer. The repo has issue-less (task-tracked) PRs, so no `Fixes` line; per the user's choice the PR references **#452 as *related*** only. `task-168.md` Status is **done**.

**Handoff caveat left in the PR body:** the `web/` bundle is built in CI only on the *release* workflow (`setup-node` + `make ui-build`); any PR-CI that builds wheels needs a Node step too, or the `[ui]` wheel ships empty (guarded by the `test -f static/index.html` assertion). Nothing else outstanding — the feature is complete and verified.

### Code-review response — evaluated, 1 disputed + 3 doc/comment touch-ups (2026-06-08) ✅

Evaluated an external code review of PR #496 (4 findings, no criticals). The headline: the **one item flagged "fix before merge" was a false positive.** Reviewer claimed `handles.ts`'s `PORT_SOURCE = "io:"` is a strict prefix of `PORT_TARGET = "iot:"`, making `handleType` order-dependent (reorder → IO targets mis-typed as source → React Flow silently drops the edge). **Disputed:** the trailing colon breaks it — `"iot:x".startsWith("io:")` is `false`, so the two are already disjoint and no string starts with both; reordering the branches is a no-op. Verified empirically + exhaustively across every prefix pair. Also disproved the secondary claim (the HANDLE-TYPE invariant fixture *does* exercise an `iot:` handle in a target slot, so a genuine type bug fails it). Left a defensive comment instead of the proposed rename — neutralizes the misread (and the real footgun: dropping a colon would make bare `"io"` prefix `"iot"`) without churning correct, well-tested constants.

The other three were valid low-priority polish, applied (all non-behavioral): (a) **no-CORS security tripwire** comment in `server.py::create_app` — the absent `Access-Control-Allow-Origin` is load-bearing (binds 127.0.0.1, read-only GET, so a cross-origin page can't read the 422 body that may echo a source line); a future `CORSMiddleware`/mutating endpoint must revisit the file-content exposure; (b) **inline-all payload-size** forward-compat note in `ui/CLAUDE.md` (multi-MB payloads are fine local single-user; remote/multi-client may want a by-ref fetch); (c) renamed `test_build_bug_on_validated_ir_is_loud_500` → `test_unexpected_pipeline_exception_is_loud_500` (it patches `resolve_validate_build` wholesale, so the name overstated the validate/build boundary). 4 files, +28/−6. `test_ui.py` 17 passed; ruff + mypy clean. Uncommitted.

---

# Phase A — Visual Redesign (Tines/n8n aesthetic) — HANDOFF (2026-06-09)

> **What this is.** A *user-driven, frontend-only* restyle of the `pflow ui` canvas to the
> Tines/n8n/Flowise look — done across one long iterative session, **building blind** (the
> implementing agent has no canvas; the user reviewed each iteration via screenshots). Spec/
> design for Phase A: `../research/visual-redesign-knowledge.md` (the KB — Flowise teardown,
> gradient technique, gotchas) + `implementation/phase-a-plan.md`. **All Phase A work is
> uncommitted** (per the standing "never commit unless told" rule) and sits on top of the
> committed Task-168 static viewer. **One piece is UNFINISHED** (the icon *connector stub*) —
> see "THE OPEN PROBLEM" below; that's where the next agent picks up.

## What Phase A changed (all in `web/`, zero contract/Python change)

The contract (`render_react_flow`) and the Python server are **untouched**. Everything is
frontend visual policy. Files: `utils/format.ts`, new `utils/icons.ts`, new `assets/icons/*.svg`,
new `public/favicon.ico`, new `vite-env.d.ts`, new `components/nodes/WorkflowNode.tsx` (replaces
the deleted `DetailedNode`+`CompactNode`), `components/nodes/index.ts`, new
`components/edges/GradientEdge.tsx`, `components/edges/index.ts`, `components/nodes/BranchPorts.tsx`,
`graph/flow.ts`, `views/GraphView.tsx`, `index.css` (heavily), `index.html`, the two `.test.ts(x)`,
`web/CLAUDE.md`.

1. **Node card → Option B (neutral tile + native-color icon).** Icon registry in `utils/icons.ts`
   (one `KIND_ICON` map; `llm` is resolved from its `model` param's `provider/` prefix → brand
   icon, default sparkle). Vendored SVGs from `pflow-cloud/public/`. (http/file are placeholders;
   `code` reuses python.)
2. **ONE leaf component** `WorkflowNode` (React Flow `type:"node"`; density rides in `data`) —
   collapsed the old Detailed/Compact split. Card shows category (type) + description (`purpose`,
   else `node_id`, 2-line clamp); `node_id` is on the tooltip + read panel.
3. **Gradient control edges** (`GradientEdge`, `userSpaceOnUse` source→target blend) for
   sequential/branch; data/error/end stay CSS-stroked. **No arrowheads** (removed). Edge width 3px.
4. **Type-colored card border + faint kind-tinted bg.** Softened the whole palette (the harsh
   neon green → calmer teal `--data-edge`/`--ref`).
5. **Beautiful is the default density.** Background `#0D0D0D`, dots `#272727`
   (`<Background bgColor color>` on `GraphView`).
6. **TD "through the icon".** In TD the control handles align to the icon column; **forks fan from
   `NODE_OUT`** (the icon) with their label riding the edge (`BranchPorts` renders only in **LR**).
   Computed `hasIncoming`/`hasOutgoing` per node in `buildFlow` (from `CONTROL_KINDS` edges) →
   `LeafData`, to drive the connector stubs.
7. **Favicon** wired.

Gates after every step: **`tsc --noEmit` clean, `vitest` 39 passing, `npm run build` clean.** The
mount test (`GraphView.test.tsx`) and `flow.test.ts` (incl. a new TD-fork test + the HANDLE-TYPE
invariant) are green.

## Critical learnings & insights (the GOLD — read before touching the canvas)

1. **React Flow renders ALL edges in one SVG layer BEHIND the nodes.** This is the single most
   important constraint and the root of the whole "edge flows *into* the icon" saga. A stock edge
   *cannot* be drawn on top of / inside an opaque node — it's painted over at the node's box edge.
   Any "line into the icon with a rounded junction" (the Tines look) must be drawn by **our own
   geometry** (a per-node connector stub, an elevated edge, or a transparent card). We chose the
   per-node stub. (Options enumerated in the KB §9 and in the chat: transparent-card, elevated-
   zIndex, full-height-tile — all still on the table if the stub proves too fiddly.)
2. **`useUpdateNodeInternals(id)` is MANDATORY when handle positions move** (e.g. an LR↔TD flip, or
   a stub appearing/disappearing). React Flow caches handle bounds at mount; without a re-measure,
   edges (and their `EdgeLabelRenderer` labels) compute from **stale** coordinates and **fly to the
   canvas origin**. This was the "fork labels as full-width bars at the far-left" bug #1.
   `WorkflowNode` calls it in a `useEffect` keyed on `[id, direction, density, hasIncoming, hasOutgoing]`.
3. **`EdgeLabelRenderer` children MUST be `position: absolute`.** Without it the label `<div>` is a
   normal block that stretches to the full container width and ignores its transform → a full-width
   bar. This was fork-label bug #2 (`.edge-label` was missing `position:absolute`; `.loop-edge-label`
   had it, which is why loop labels always worked).
4. **The tile dominates the header height — so beautiful nodes are a FIXED 68px.** The 56px icon
   tile is taller than any 2-line description, so adding height for a 2nd line (the old `DESC_LINE`)
   made the box taller than the content → the tile drifted off-center → **unequal connector stubs**.
   Removed `DESC_LINE`; `leafSize` returns `HEADER_HEIGHT` (68) for compact. The connector stubs
   ANCHOR to the vertically-centered tile via `calc(50% ± Npx)` — they DEPEND on the tile being
   centered. If you ever let the header grow, re-derive the stub `top`.
5. **Building blind is the core difficulty.** The geometry repeatedly *calc'd correctly on paper but
   rendered wrong*. The visual layer needs a **real browser with devtools** — see the OPEN PROBLEM.
6. **Vite `.svg` imports need `web/src/vite-env.d.ts`** (`/// <reference types="vite/client" />`)
   for tsc; isolated to `utils/icons.ts` so the heavily-imported `format.ts` stays asset-free.
7. **`color-mix(in srgb, var(--kind) N%, …)`** is used everywhere for type-tinting — modern-browser-
   only, fine for a localhost dev tool. The **tile (image) border = full `var(--kind)` 3px** to match
   the edge color; the **node CARD border stays subtle (1.5px, 55%) — do NOT thicken/recolor it**
   (explicit user instruction).
8. **Forks-through-icon split LR vs TD:** LR keeps the n8n labeled border handles (`BranchPorts`);
   TD routes branches through `NODE_OUT` with the label on the edge. `BranchPorts` returns `null` in
   TD; `sourceHandleFor`/`toFlowEdge`/`leafSize` are all `direction`-aware. Don't "unify" this away
   without re-checking both modes.

## THE OPEN PROBLEM — the icon connector stub (UNFINISHED — start here)

**Goal (the Tines look, image #11/#14/#17 in the chat):** in **TD + beautiful**, a control edge
should appear to **flow into the icon tile** with a small, rounded, kind-colored **connector stub**
bridging the edge to the tile. Two stubs per node — **top** (rendered only if `hasIncoming`) and
**bottom** (only if `hasOutgoing`), **same size**, anchored to the tile's top/bottom border, each
ending in a short **straight tip** that pokes a few px **outside** the node to meet the edge.

**Where it lives:** `WorkflowNode.tsx` — the `Connector` component (owns its `Handle` at the stub
tip) + the `CONNECTOR_TOP`/`CONNECTOR_BOTTOM` SVG path constants; `index.css` `.node-connector*`
rules; `.node.compact { overflow: visible }` (so the stub can extend outside); `LeafData.hasIncoming/
hasOutgoing` (computed in `flow.ts buildFlow`). The stub **owns its handle** (the `Handle` sits at
the stub's tip *inside the connector `<div>`*) — done specifically so the edge endpoint and the
shape can't drift apart.

**Three issues the user reports STILL present (after the owns-its-handle rewrite):**
1. **Gap between the stub TIP and the edge line** — top AND bottom. The edge connects *further out*
   than where the stub ends.
2. **Small gap between the stub BASE and the tile (image) border** — the base floats above the tile
   instead of touching it.
3. **Shape proportions** — the flare needs to **stretch further in X** (wider) and **a bit less in
   Y** (shorter). Tune the two path constants (`viewBox 0 0 16 14`) + `.node-connector` width/height.

**Why I could not fix #1/#2 (and what I now believe):** my geometric model says the stub tip (the
`<div>`'s `top: calc(50% - 42px)` ⇒ −8px on a 68px node) and the handle (at the `<div>`'s `top:0`)
COINCIDE, and the stub base (`+14px` ⇒ 6px) equals the tile-top (also 6px). On paper: no gaps. But
the user sees gaps on every side, **so my model of the rendered positions is wrong** — and I'm blind,
so I can't see where. **Strong hypothesis:** React Flow mis-measures a `Handle` that lives **inside a
nested, `transform`ed, absolutely-positioned container that extends OUTSIDE the node's box**. RF
computes handle bounds relative to the node; a handle whose box is above/below the node bounds (the
"outside" extension) and under an extra `translateX(-50%)` is exactly the kind of case RF's measurement
gets wrong. That would put the *edge endpoint* somewhere other than the *rendered stub tip* → the gap.

**HOW TO DEBUG IT (do this first — with a real browser, which I never had):**
- Run `uv run pflow ui`, open `conditional-branching`, toggle **TD** + **beautiful**, open devtools.
- Measure the **actual** rendered numbers and compare to the model: (a) the node's `offsetHeight`
  (is it really 68?); (b) the `.node-tile`'s `getBoundingClientRect` top/bottom; (c) the
  `.node-connector`'s rect; (d) the edge `<path d>` endpoint coords (in the `.react-flow__edges` SVG);
  (e) what React Flow stored for the handle position (`useStore(s => s.nodeLookup.get(id))` →
  `internals.handleBounds`). **The discrepancy between (d) the edge endpoint and (c) the stub tip is
  the bug.** I was reasoning from the model; the next agent should reason from the DOM.

**If the nested-handle hypothesis holds, the likely fixes (in order of preference):**
- **Stop extending the handle outside the node.** Put `NODE_IN`/`NODE_OUT` back on the node's
  **border** (the most reliable RF position — a plain `Position.Top`/`Bottom` at the icon column),
  and let the connector stub bridge **border→tile** *inside* the node (purely decorative, drawn on
  top of the card, no handle of its own). The edge connects at the border (reliable); the stub covers
  the small border→tile gap. You lose the "tip pokes outside" detail, but you gain a rock-solid edge
  join. (The user wanted the tip outside *because* there was a gap; if the border join is seamless,
  the desire for "outside" may evaporate.)
- **Or** keep the owns-its-handle idea but render the `Handle` as a **direct child of `.node`** (not
  nested in the transformed connector `<div>`), positioned with the SAME `calc` as the stub tip, and
  call `useUpdateNodeInternals` (already wired). Then verify in the browser that RF's stored handle
  position equals the stub tip.
- **Or** abandon the stub and switch to one of the other "edge-into-icon" strategies (KB §9 / chat):
  transparent card + handle on the tile + **elevated edge `zIndex`** (edge drawn ON TOP, so it's
  visibly inside the icon) — simplest conceptually, but elevated edges can paint over *other* nodes
  in dense graphs, so scope it.

**The shape (#3) is a trivial swap once the gaps are solved:** edit `CONNECTOR_TOP`/`CONNECTOR_BOTTOM`
(viewBox `0 0 16 14`; flat tip = the ≈3px end, flat base = the wide end on the tile) + the
`.node-connector` `width`/`height`. The user OFFERED to provide the exact Tines SVG path but hasn't —
**ask for it**; it's a one-line drop-in and removes all the guessing.

## State at handoff
- **Uncommitted.** All Phase A work is on the `feat/workflow-visualization-static-viewer` branch,
  working tree only (the committed history ends at Phase 5 / PR #496). The next agent should treat
  the connector as WIP; everything *else* in Phase A (cards, icons, gradient edges, palette, TD
  trunk+forks, labels) is in good shape and the user has accepted it through iteration.
- **Gates green** (`tsc`, `vitest` 39, `build`). The bundle is rebuilt into `src/pflow/ui/static/`.
- **Reference images** (the aesthetic target) are in the chat: Tines nodes = solid-ish tile + edge
  flowing into the icon with a rounded connector + flat (90°) caps. We are on **Option B** (neutral
  tile + brand icons) per an explicit user choice — do NOT re-litigate the tile to solid color.
- **Read next:** `../research/visual-redesign-knowledge.md` (Phase A design + Flowise teardown),
  `implementation/phase-a-plan.md` (the plan + simplicity decisions), `web/CLAUDE.md` (updated
  component/edge/connector notes), this section, then the code.

---

## Closing the "built blind" gap — a real-browser feedback loop (2026-06-09)

> Every prior agent on this feature built **blind** (the phrase recurs through this log and
> `visualization-requirements.md`): screenshot-review only, no DOM, no measurement. The connector
> stub stalled for exactly that reason — the geometry *calc'd right on paper but rendered wrong*, and
> nobody could see where. This session built the missing feedback loop, then used it to **measure** the
> connector bug instead of theorizing it. No production `web/` code changed yet — this is tooling +
> diagnosis; the fix is teed up below.

### The way of working (HOW lives in the skill — this is WHEN/WHY)

> Usage (commands, params, output shape, jq, troubleshooting): `.claude/skills/screenshot-pflow-web-ui/SKILL.md`.
> **Do not restate it here.** Three tools, each for a different question — pick by what you're verifying:

- **Shape (a curve, a flare, an icon) → `shoot` a standalone SVG/HTML.** Render the candidate in a
  throwaway `.html`, `shoot` the `file://`, Read the PNG. ~3s, **no app build**, fully isolated from
  React/ELK. Used it to compare three flare paths in `/tmp/flare-lab.html` (kept) against the Tines
  reference. This is the right loop for *aesthetics* — the app is too slow and too noisy to iterate a
  curve in.
- **Geometry / gaps / positioning → `inspect.pflow.md`.** Reads real `getBoundingClientRect` rects for
  every node box / tile / connector / handle + every edge path, as JSON. This is the thing the codebase
  kept saying it lacked ("jsdom can't see edges"): a real-browser geometry **verifier**. Use it to
  quantify a gap, assert edges land on handles, find off-canvas nodes, or **diff before/after a fix**.
- **Holistic look → `screenshot.pflow.md`.** Eyeball the whole settled canvas.

The split that matters: **`inspect` answers "does it sit right" (numbers); `shoot`/`screenshot` answer
"does it look right" (eyes).** `inspect` can't judge a curve; a screenshot can't give you a 5px gap.

### Tooling decisions (the journey the skill doesn't carry)

- **Shared `open + settle` core as a nested sub-workflow** (`shared/open-and-settle.pflow.md`), reused by
  both `screenshot` and `inspect` — the load-bearing async-settle poll lives in **one** place. The open
  feasibility question was *does the MCP Chrome page survive the sub-workflow boundary?* — **verified yes**
  (open happens inside the sub-workflow; the parent's `shot`/`measure` act on that same page). Picked this
  over duplicating the poll; the user chose the nested approach explicitly.
- **Renamed `workflow.pflow.md` → `screenshot.pflow.md`** (the folder now hosts two tools + `shared/`).
- **`inspect` emits clean, pipeable JSON**: a `clean` code node strips the chrome-devtools
  `Script ran on page and returned …` wrapper, and `pflow … -p -o geometry` strips pflow's own progress/
  header — so it pipes straight to `jq`. **Filter in-shell** (the dump is ~1K tokens small / ~11K large in
  advanced — too big to read whole; jq before it hits context). Added `nodeId` per node so you select by
  the author-known id.
- **`examples/real-workflows/` is now excluded wholesale from `test_example_validation.py`** (like
  `invalid/`/`legacy/`). Cause: adding a `type: workflow` node made the validator **recurse** into the
  mcp-laden sub-workflow and fail — the skip heuristic only pre-scans *top-level* node types (a latent gap
  the test docstring had already flagged). User's call: exclude the dir. `test_ir_examples` was never at
  risk (schema-only, no recursion). Both green.
- **Nested-node caveat (found by testing `document-processor`, which invokes a sub-workflow twice):** a
  node inside a sub-workflow renders + measures fine (correct screen-space rects at any depth, groups
  default-expanded), but **`node_id` is NOT unique across sub-workflows** — disambiguate by the flat
  `dataId`. (Bonus: a sub-workflow's internal node may show `connTop/Bottom: null` — *correct*; connector
  stubs are **control**-flow-gated and a single-node sub-workflow has only data flow.)

### The connector bug — now MEASURED, not theorized (hand-off ready)

Ran `inspect` on `conditional-branching` framed on `classify` (TD/beautiful, viewport scale 1.5):
- incoming edge ends at **y=538**; flare tip at **543** → **~5px gap** (gap #1, symmetric on the bottom).
- flare base at **564**; tile top at **566** → **~2px gap** (gap #2).
- flare box **16×14** — nearly square → the pinched/hourglass look (gap #3).
- **Root cause CONFIRMED (was the handoff's hypothesis):** the `<Handle>` lives *inside* the transformed,
  outside-the-box `.node-connector` div, and React Flow draws the edge endpoint ~5px **outside** where the
  handle element actually renders. Measured, not guessed.

**The fix (designed, not yet written) — make the gaps structurally impossible, not pixel-tuned:**
1. Move `NODE_IN`/`NODE_OUT` onto the node **border** at the icon column (the reliable RF measurement —
   the existing `fallbackHandleStyle` path); **drop the `<Handle>` from `Connector`**.
2. Make the flare a pure **opaque decoration** layered edge < flare(z1) < tile(z2). The edge ends under
   the opaque flare → its terminus is *hidden* → gaps #1/#2 **cannot exist** (works for any endpoint under
   the flare; no sub-pixel agreement needed). This is why it'll be verifiable by screenshot, not blind math.
3. Swap the path for the real Tines shape (wider/shorter — eyeball start = variant **B** in the lab; the
   user offered the exact path). `/tmp/flare-lab.html` already renders the **zero-gap ideal** as the visual
   target.
4. **Verify:** `inspect` before/after — assert the edge `pathRect` end is now *inside* the `connTop`/
   `connBottom` rect, and the flare base meets the `tile` edge. Screenshot to confirm the shape.

**State:** all tooling uncommitted (working tree). Connector fix **not started** — waiting on go-ahead
and (optionally) the Tines path. Diagnosis is done; the next step is purely the `WorkflowNode.tsx` +
`index.css` edits above.

### Connector flare — implemented + tuned live in a real browser (2026-06-09) ✅ (uncommitted)

> The fix designed above is now BUILT and then tuned across a long live-iteration session with the user.
> **All in `web/` — zero contract/Python change.** Worked entirely through the real-browser loop:
> `inspect` for geometry (real `getBoundingClientRect`), a throwaway `shoot`-able SVG lab for *shape*,
> `screenshot` for the whole canvas. First time the connector was tuned against MEASURED DOM, not blind.

**Build v1 — handle off the flare, flare on top (closed the 5px gap by construction).** Two structural
changes, not pixel-matching: (1) `NODE_IN`/`NODE_OUT` moved onto the node **border** (a direct,
untransformed child → RF measures it reliably); `Connector` became **pure decoration** (no handle).
(2) The flare is **opaque, on top, same `--kind` color**, and the edge ends at the border handle *under*
it — so the terminus is hidden and a gap is impossible regardless of sub-pixel alignment. **Root cause of
the original gap, confirmed:** a `<Handle>` nested in the `transform: translateX(-50%)`, outside-the-box
`.node-connector` div is mis-measured by RF — the edge endpoint diverges ~5px from where the handle renders.

**TOUCH not THROUGH — the user's diagnosis that finally unstuck it.** A long shape detour (flat-hug coves,
5 escalating widths, an interactive slider tuner) kept missing because I treated it as a *curve* problem.
The user reframed: the flare must **touch the tile border's OUTER edge**, not **go through** it into the
dark face. A `touch` vs `through` lab made it obvious — penetrating the border leaves a dark **notch** where
the concave sides meet the face; landing on the outer edge flows cleanly into the top border. *That was the
real bug, not the cove shape.*

**Angle confusion (logged so it isn't repeated).** I twice flipped the base-landing angle the wrong way.
"Round → flat" = the cove turns **horizontal (tangent)** as it meets the tile (flat landing), NOT
vertical/perpendicular (90°). Flat was right from the start; the "90°" variants were the regression.

**Architecture pivot (user's idea): anchor to the TILE, not the node.** The flare was positioned with
`calc(50% ± px)` magic tied to node height + header padding — fragile per-node. Made `Connector` a **child
of `.node-tile`** (`position: relative` on the tile; `.node-connector-top { bottom: calc(100% + Npx) }`).
Now the base is **always** at the tile edge regardless of node height — no node-height math. The load-bearing
structural win; strictly simpler.

**Gotchas, all measured not guessed:**
- **Exact touch leaves a ~1px anti-aliasing seam** → **overlap** the base into the border. But overlap must
  stay **within** the 3px border (same color → invisible); past it into the face = the notch again. Overlap ∈ (0, border).
- **An absolutely-positioned child's containing block is the ancestor's PADDING box** (inside its 3px border),
  so `bottom: calc(100%)` lands at the *inner* border edge — `+Npx` is needed to push the base out to the
  right place. (Cost a "base overshot into the face" round.)
- **The tip MUST equal the edge stroke width (3px).** To resize the cove, keep the **tip units fixed** and the
  **div width == SVG viewBox width** (1 unit = 1px); scaling the box uniformly shrinks the tip too.
- **Flare height is bounded below by the tile→edge distance** (edge ends on the node border; tile is inset by
  the header padding). To shorten it, **pull the handles toward the tile** (`top`/`bottom` offset on the border
  handle) so the edge terminates closer in — then the cove shrinks without re-opening a gap.
- **The SVG `shoot` lab is great for SHAPE but DIVERGES from the live render for sub-pixel / same-color-contact**
  questions (e.g. behind-vs-on-top looked identical in the lab because flare and tile border share `--kind`) —
  use `inspect` for those.

**Final geometry (verified via `inspect`):** flare 14px wide (3px tip) × 9px tall, anchored to the tile,
base overlapping the border, tip + edge + tile all centered on the icon column; both ends covered, no gap, no notch.

**State / next:** built in `WorkflowNode.tsx` + `index.css`; **uncommitted**. The user also made manual edits
this session (a `:root` palette re-theme; nudging the base positioning to `+3px` = exact touch). **Before
commit:** run the gate (tsc/vitest + `make check`) and update any Phase-A test that asserted the old
connector-owns-a-handle structure (the `Connector` no longer renders a `<Handle>`).

### Connector flare SOLVED — the paint ≠ the box (viewBox/element mismatch) (2026-06-09) ✅

> Landed in `dc419be4` ("improvements to shape"). Closes the flare saga above.

**The user's two remaining symptoms — "an angle going into the border" and "the stem is ~1px thinner
than the edge" — were ONE bug.** The path was authored in `viewBox="0 0 14 13"` but the element was
14×9px. An SVG with no `preserveAspectRatio` defaults to `xMidYMid meet`: scale = min(14/14, 9/13) ≈ 0.69
→ the browser painted a **69%-size copy** of the designed flare (≈9.7×9), horizontally centered with
~2.2px dead margins. So the tip rendered 3×0.69 ≈ **2.08px** against the 3px edge (the "1px too small"),
and the cove's flat tangent landing compressed into ~3 antialiased px (the "angle"). **Crucially this is
invisible to rect measurement** — the user had verified the bounding box was correct, and it WAS; the
mis-scaled paint inside it is what no `getBoundingClientRect` can see. *Discipline note for the tooling:
`inspect` verifies BOXES; paint-vs-box bugs still need the zoomed screenshot (`sips` crop + upscale).*

**Fix — structural, so the class can't recur (not pixel-nudging):**
- **One `CONN` constant set** (WorkflowNode.tsx) drives the path, the viewBox, AND the element's inline
  width/height. CSS no longer carries any connector geometry — the TS↔CSS dual-source is exactly what
  drifted (cf. the stale "18×13" comment three edits behind the code).
- **Elliptical-arc fillets (`A`)** replace the eyeballed cubics: tangent exactly vertical at the 3px stem,
  exactly horizontal at the base — flat landing by construction, not by tuning.
- **Overlap aprons baked into the path:** a 2px stem rides under the edge terminus (same width + color,
  collinear → invisible), the base sinks 2px INTO the 3px tile border (anchor `+3px` exact-touch →
  `+1px`; within the border, never past it). Sub-pixel alignment now matters at NEITHER end.

**Verified in the real browser:** `inspect` — box 14×11 CSS px, base 2px inside the border, centered on
the handle; zoomed crops of both junctions — full-width stem, smooth flat landing, no notch. User: *"Great!
This is much better!"*

### Fresh-eyes frontend review → ranked leverage list (2026-06-09)

User asked for a structure/best-practices pass over `web/` before continuing UI work. Read the whole tree
(~3.1k lines). **Verdict: healthy** — the RF traps are all avoided (module-level `nodeTypes`/`edgeTypes`,
callbacks kept out of node `data` via `InteractionContext`, identity-preserving `applyFocus`, pure
node-env transform, status machine + ErrorBoundary). Real findings, ranked by leverage (agreed with user):

1. **Geometry dual-sourced TS↔CSS, synced only by comment strings — THE recurring bug class** of this
   feature's history (`HEADER_HEIGHT`/`ROW_HEIGHT`/tile 56/border 3/edge-stroke 3/handle `left:34`…; it
   produced the tile-drift, the viewBox drift, every stale-comment round). Plan: a `metrics.ts` exporting
   the layout-coupled constants, injected once as CSS custom properties (the `--kind` mechanism, proven).
2. **ELK sizing is open-loop** — `leafSize` predicts heights, components stretch to fit, nothing detects
   drift → silent overlaps. Plan: dev-mode tripwire (warn when `offsetHeight` ≠ assigned height); the full
   measure-then-layout loop only if the tripwire ever fires.
3. **`applyFocus` reads `e.hidden` as "default-hidden" AND writes it** — correct only because the hook
   always re-applies focus to the pristine `laid` snapshot; the invariant is structural, not typed. Plan:
   explicit `defaultHidden` on `EdgeData`, set once in `buildFlow`.
4. Registered components not `memo`'d (fixed below). 5. ELK statically imported — ~80% of the 1.79 MB
   bundle; `layoutGraph` is already async so a dynamic import is nearly free. 6. Stringly class names
   (`edge-${kind}`, `kind-${node.kind}`) defeat grep — plan: construction-site comments in `index.css`.

**Judged fine, do NOT churn:** the single CSS sheet at this size; no Tailwind/CSS-in-JS/state-lib/router;
React 18; per-edge `<defs>` in GradientEdge; the TD/LR fork-policy spread (direction is a real axis — an
abstraction would just hide the branching).

### Best-practices batch 1 — memoize all registered RF components (2026-06-09) ✅

All six (`WorkflowNode`/`PortsNode`/`GroupNode`/`EndNode`/`GradientEdge`/`LoopEdge`) wrapped as
`memo(function Name …)` (named, so devtools keep the name), and the constraint documented in BOTH type
registries ("every registered component must be memo()'d"). This is the RF-documented practice that
*composes* with `applyFocus`'s identity preservation — which was previously wasted: every store churn
(pan/zoom/any focus click) re-rendered all nodes; now only nodes whose data identity changed render.
Behavior-neutral by construction; gates green (vitest 53, tsc strict + build); real-browser screenshot of
`conditional-branching` TD/beautiful identical. Remaining batch (in order): lazy-ELK dynamic import →
class-name grep comments → `metrics.ts` consolidation → `defaultHidden`.
