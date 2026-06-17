# Task 168 — Implementation Progress Log

> **What this is:** the *journey* — the order decisions were actually made, the forks taken, the
> alternatives rejected, and the reasoning that lives in no other doc.
> **What this is NOT** (look elsewhere): the *what/why* → `task-168.md`; the *how* (phases, wire
> contract, file:line, the H1–H13 review fixes) → `implementation/implementation-plan.md`; the
> load-bearing "why a server" → `ADR-0005`; vocabulary → `CONTEXT.md`. This log *references* them;
> it never restates them.
> **How to read this:** search for the dated entry covering your area — do NOT read it whole
> (~90k tokens, mostly history). For CURRENT behavior the CLAUDE.mds + `visualization-requirements.md`
> are canonical; this log is the why/journey, and reversed decisions carry *(superseded …)* markers —
> check for one before acting on any rule you find here.

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

- **Parallel work — Task 133:** cleared to proceed alongside — disjoint file sets (168 =
  `graph/` + `cli/` + `ui/` + `web/`; 133 = `runtime/trace` + `cache` + `instrumentation`). Two shared
  touch-points to coordinate: `graph/CLAUDE.md` (both may edit, different sections) and the **read-only
  `NodeId` / Runtime-Overlay-Join-Contract** identity seam — neither may change it; it's where the two
  substrates eventually meet.

---

## Implementation log

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

### Phase 2 — `render_react_flow` translator + typed contract (2026-06-07) ✅

New `renderers/react_flow.py` (`RFRef/RFParam/RFNode/RFEdge/RFGroup/RFGraph` frozen dataclasses +
`render_react_flow`), registered in both `__init__.py`s. Consumes only GraphModel + its derived views;
loop/batch/io/source emitted as plain dicts via `asdict()` on the frozen model sub-dataclasses (matches the
contract's `dict | None` typing, DRY). `shadowed` emits the model's **general** `graph.shadowed(edge)` fact,
never Mermaid's narrower `_edge_shadowed_for_render`. Mermaid goldens still byte-identical.

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

**Final state:** Mermaid goldens byte-identical; renderer import-purity verified (model/scope only). Phases 1–2 are complete and I'm confident in them.

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

**Post-review state:** Mermaid goldens byte-identical. Contract is now reviewed + hardened — ready to freeze for Phase 3.

### Phase 3 — `pflow ui` command + Starlette server + `[ui]` extra (2026-06-08) ✅

New files: `execution/graph_service.py` (the H11 helper), `ui/__init__.py`, `ui/server.py`,
`cli/commands/ui.py`, `tests/test_cli/test_ui.py` (12 tests). Edited: `cli/main.py` (register `ui_cmd`),
`pyproject.toml` (`[ui]` extra + dev deps), `.gitignore` (`src/pflow/ui/static/`). Mermaid goldens untouched. Real Task 163
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
Phase-3 files only) in parallel with hands-on break attempts. Two real fixes landed.

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
truncated to `{"nodes": {"bad":`).

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
host/port/url — guards against tested-but-unwired).

### Phase 4 — `web/` frontend (Vite + React + React Flow + ELK) (2026-06-08) ✅

New top-level `web/` tree: Vite + React 18 + `@xyflow/react` v12 + `elkjs`, building into `src/pflow/ui/static/`.
Modules mirror the plan: `types.ts` (hand-mirrored contract) → `api.ts` (the single data-loading seam, overlay-ready)
→ `flow.ts` (the RFGraph→React Flow transform — the heart) → `layout.ts` (client-side ELK) → `nodes/`
(Detailed/Compact/Group/End components) → `CatalogView`/`GraphView`/`ReadPanel`/`Toolbar`/`App`. All advertised
interactions implemented: collapse/expand (re-layout), focus+context (no re-layout), density toggle, LR/TD toggle,
click-to-read. `npm run build` → 1.79 MB bundle (ELK dominates, as the plan's Risks§ predicted); served + harness
renders (82 nodes) through the real Phase-3 server.

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
other three surfaced real, fixable gaps — all addressed. The wheel still bundles `index.html`+`assets/`.

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

### Visual iteration: loop arcs + density-governed edges (2026-06-08, user-driven)

Two design changes after a user review of the running UI. Both are **pure frontend visual policy — zero contract change.**

**Loops were only a text badge — now a synthesized loop-back arc.** A loop is a `LoopSpec` on a node, not an edge, so `flow.ts` synthesizes a self-loop edge per looped node, anchored to the node — or to its **group** when it's a looped sub-workflow host (the arc wraps the container). A new `LoopEdge` custom edge draws a smooth amber arc (bulge perpendicular to the source→target chord, so it reads in both LR and TD) labeled `↻ while/until <condition> ≤ cap`. Self-loops are filtered out of ELK (`layout.ts`) — ELK never routes them; LoopEdge owns the path. The redundant loop *badge* was removed (the arc + read-panel carry it). Skips a loop whose node is hidden inside a *collapsed ancestor* (only draws on the box that actually loops). Chosen over a loop-frame/stacked-deck after putting the options to the user (mockups) — arc won as the most universally legible.

**Density now governs EDGE density, with progressive disclosure (the key user insight).** Beautiful mode was drawing all the green `${ref}` data-flow lines — incoherent, since the data wiring is literally the ports/chips of the *advanced* node. Fix: data-flow edges are **built but `hidden` in beautiful** (control-flow skeleton only — slate/blue), and `applyFocus` **reveals just the focused node's** data lines on click (hidden elsewhere). The elegant bit: no density flag in `applyFocus` — it reveals any *default-hidden* edge incident to the focus, and only buildFlow (which knows density) sets the default. Hidden data-flow is also excluded from ELK so the beautiful layout stays tight; revealed-on-focus edges route best-effort through it (fine for an on-demand reveal). Shadow-dimming now only applies in advanced (beautiful's control edges show full-strength since the data lines that shadowed them are hidden). Sequential edges got a clearer stroke so the skeleton reads as one coherent flow. Pinned by tests: beautiful hides data-flow / advanced shows it; focusing a node reveals only its incident data line; clearing focus re-hides.

### Visual iteration 2: readability batch — spacing, color, forks, IO pills (2026-06-08, user-driven)

After the user reviewed the running UI on the harness (everything cramped on one line, blending together, forks unclear). Diagnosis: the "line" is honest (a linear pipeline IS a line) — the real bugs were **tight spacing + monochrome nodes + IO-card bloat**. User chose (via mockups) the readability batch, keep LR, defer gradient edges. All visual policy — **zero contract change.**

- **Spacing doubled** (`layout.ts`): `nodeNodeBetweenLayers` 64→130, `nodeNode` 36→64, + `NETWORK_SIMPLEX` placement. A cramped pipeline reads as a smear; this gives it air.
- **Color nodes by type** (`utils/format.kindColor` + a `--kind` CSS var on each node): the node's identity color (shell=emerald, http=sky, llm/claude=violet, code=amber, …) on the left border + glyph. **Control edges take their source node's type color** (inline `style.stroke` + matching arrowhead) — the stepping stone to the deferred source→target gradient. error/end/data/loop keep semantic colors. This is what kills "blends together."
- **IO nodes → compact port pills** — the single biggest declutter: the harness's **53 IO nodes** (43 input + 10 output) were full-size cards bloating every sub-workflow box. *(Superseded same day: iteration 4 replaced the pills wholesale with the consolidated ports node — mechanism there.)*
- **Forks = labeled border handles** (n8n-Switch style; `BranchPorts`, `branchHandle`): a decision node's branch outcomes (`fix-tests`/`push`/…) render as one labeled source handle per outcome on the right border, each line leaving its own named handle — clear which value goes where. **Shown in BOTH densities** (a fork is structure, not advanced data detail), so `CompactNode` became a small card (header + branch rows) instead of a pill. Branch labels no longer ride the edge mid-line. Sized into `leafSize` (branch rows in both densities).
- **Smooth edges**: all edges now bezier (`type: "default"`) — the curvy look.

Pinned by tests: branch edges use `branchHandle(label)` and the node carries `branchLabels` (both densities); a control edge is stroked with its source node's `kindColor`. **Deferred (next visual step):** source→target **gradient** edges (per-edge SVG `<linearGradient>` + custom edge — not a React Flow built-in; the user opted to ship this batch first).

### Visual iteration 4: IO ports → one consolidated "table" node (2026-06-08, user-driven, planned)

User insight: the clutter wasn't *that* inputs are shown, it's that **each input was its own node**. Fix (the React Flow table-node pattern): `input_wrapper`/`output_wrapper` → ONE **Inputs**/**Outputs** node with a **row + handle per port**, shown in **both** densities; row-level focus preserves "click an input → see its connections." Planned first (the user approved the plan), then built. Pure frontend — zero contract change. *(The ports table itself was later replaced wholesale by IO-rows-on-the-workflow-node, 2026-06-10 — see that entry; the row-level-focus and dual-handle ideas survive there.)*

**What survives of the build** *(the deleted table's mechanics trimmed 2026-06-11 — they described
dead code)*: **row-level focus was born here** — every edge carries `data.from`/`data.to` (its
*original* contract endpoints), so focus can be a node id, an owner id, or a **single port id**
(a row), revealing just that port's lines even though its edges re-anchor onto a shared node;
clicking a row drives it via a small `InteractionContext` (`focusPort`) — keeps node `data`
callback-free. Both mechanisms are live today (PortRows / applyFocus).

**Follow-up fix — every port row needs BOTH handles (the missing binding edges).** First cut gave each row only a *source* handle (feed-out). But a port bridges two scopes: an **input** RECEIVES from the parent (binding) AND feeds consumers; an **output** RECEIVES from a producer AND feeds the parent. The contract has these "receive" edges (verified: 30 into input ports like `repo_dir→repo_dir`, 11 into output ports like `check-validate→ok`) — but they targeted the row's source-type handle, so React Flow couldn't attach them and they silently didn't draw (the user spotted the missing lines). Fix: each row now renders a **target** handle (`portTargetHandle`, left/top — receives) AND a **source** handle (`portHandle`, right/bottom — feeds); `targetHandleFor` routes an IO target to `portTargetHandle`. Pinned by an assertion that a binding edge lands on the target handle.

### Visual iteration 3: IO-in-beautiful + layout philosophy resolved (2026-06-08, user-driven)

Reviewing the running UI, the user hit two layout problems, both now resolved.

- **IO ports float in beautiful + sub-workflows look empty.** Root cause: IO nodes connect ONLY via data-flow, which beautiful hid AND `layout.ts` excluded from ELK → disconnected islands ELK parked off to the side. Fix (two parts): (1) **hide IO ports + their wrapper groups in beautiful** (shown in advanced, where they read fine — the user's call; IO-touching edges are dropped silently, before `renderAnchor`, so it's not mistaken for a broken-anchor warn); (2) **feed data-flow edges to ELK for layout even when they render hidden** — layout reflects ALL structure so a data-only node never floats; density decides only what's *drawn*. Pinned by a test (advanced shows the IO pill + wrapper; beautiful hides port + wrapper + its edge, body still renders).

- **"Everything on a thin line" — chased, then resolved as a non-problem.** Tried ELK `wrapping` (fold the chain into rows). Verified it works (1 row → 3, at root AND — after applying the options to every composite, not just root — inside nested groups). But the user correctly rejected it: wrapping cuts at an arbitrary **width** threshold and sweeps the inter-row edge back to the far left (a "carriage return"), which isn't how n8n works. **The real finding (verified against the contract):** the harness's `check-groups` "branches" reconverge into a forward chain (`review-round → simplify → verify`; `check-groups → simplify` feeds the same chain), so they're *sequential*, not independent — ELK correctly lines them up horizontally. **This workflow is structurally a pipeline; a pipeline IS a line (n8n would draw it the same).** The fork is shown via the labeled border handles, not by spreading. **Decision: no wrapping.** The honest n8n model — sequence flows one direction; a *genuinely* independent fork fans down on its own (verified: a Switch→3-independent-targets lays them in one column, y-spread 280). Don't re-litigate "make the pipeline 2D" — it's 1D by structure.

### Small feature: beautiful labels its revealed data lines (2026-06-08)

User clicked `fetch-data` in beautiful and asked where `stdout` went. Cause: output/input field *names* are advanced-only (node rows); a compact node shows only its name, so a revealed data line had nowhere to surface the field. Fix: in beautiful, a data-flow edge is labeled with what flows (`output_field → input_name`, e.g. `stdout → data`); advanced stays unlabeled (the rows already say it). Pinned by a test. (Also confirmed `conditional-branching` genuinely has 0 inputs — `fetch-data` makes its own data — so the absent Inputs node is correct, not a bug.)

### Docs + requirements persisted (2026-06-08)

- New **`visualization-requirements.md`** (task folder) — the one-page what-must-hold checklist
  (hard requirements / decided principles / implemented / wanted / deferred). The *what*,
  complementing this log's *why* and the CLAUDE.md *how*. *(Its contents have evolved heavily
  since — the doc is the living source, not this snapshot.)*
- **`web/CLAUDE.md`** (already existed) got the consolidated-ports + dual-handle + row-level-focus concepts and the jsdom/handle-type finding below. **`ui/CLAUDE.md`** stale path fixed (`api.ts` → `api/client.ts`). Left `execution/`, `registry/`, `graph/` CLAUDE.mds alone (Phase-1–3 / Task-133 coordination, not this session's authored work).

### Finalize verification + a real test-quality pass (2026-06-08)

**Ran the full gates** (hadn't since Phase 3) — green. *Gotcha surfaced:* once `web/` is staged, pre-commit's `pretty-format-json` reformats `web/` JSON (it expanded `tsconfig.json`'s inline arrays); it auto-fixes on first run, then converges. `package.json`/`package-lock.json` were already compliant.

**Test-quality pass (the bar is "passing the *right* thing", not "passing").** A probe revealed the load-bearing fact: **React Flow renders ZERO edge DOM under jsdom** and logs no handle error — so the existing GraphView "no edge/handle errors" assertion was **theater** (passed because no edges exist, not because they're correct). Acted:
- **Removed** that theater assertion (kept the mount test's real parts: pipeline mounts, nodes + `${ref}` chip render) and **removed** a tautological "edges take the source color" change-detector.
- **Added the HANDLE-TYPE INVARIANT** — the recurring bug was always a handle-*type* mismatch (a `sourceHandle` that's secretly target-type → React Flow silently drops the edge; it bit us twice). Made `handleType` authoritative in `handles.ts` (each id scheme → "source"/"target", throws on unknown); a pure `flow.test.ts` test asserts every edge's `sourceHandle` is source-type and `targetHandle` is target-type across a graph exercising all schemes (ports/branch/param/output/node-level). **Mutation-verified:** reverting the port-binding fix makes it fail. This is the only reliable catch for the silent-drop class — jsdom can't, so edge integrity is a pure test, never a render test.

**Honest residual (stated, not hidden):** built blind (no canvas) — a *component* rendering the wrong handle type, or visual/layout ugliness, still rests on the user's eyes; the *build-side* logic where the real bugs lived is now locked. Known-deferred: the **smart edge-router** (skip/loop edges overlap nodes in dense graphs — biggest quality gap) and **gradient edges**.

### Phase 5 — docs + model-purity guard + final gates (2026-06-08) ✅

**Scope reality: most of Phase 5 had already crept into Phase 3/4.** `ui/CLAUDE.md` (Phase-3 handoff), `web/CLAUDE.md` (Phase-4 + visual-iteration entries), and the full `make check`/`make test` gates were all already landed and committed. The *genuine* Phase-5 remainder was narrow: (1) `graph/CLAUDE.md` — Phase 4 explicitly **deferred** it ("Left graph/CLAUDE.md untouched"); (2) the stale parent map in `core/workflow/CLAUDE.md`; (3) the H12 purity guard; (4) re-running the gates. No production code changed — Phase 5 is docs + one meta-test.

**`graph/CLAUDE.md`** (+ parent `core/workflow/CLAUDE.md`): added `react_flow.py` to both File Maps + a Renderer-Notes paragraph (injective `n{i}`/`g{j}` ids — NOT Mermaid's collision-patched scheme, no shared helpers; emits the **general** `shadowed()` fact not Mermaid's render policy; truncation lives in the renderer; pointer to `ui/CLAUDE.md` for the wire contract). Added a `Node.params` invariant bullet (inline values + the non-dict guard + Mermaid-invisibility). Generalized the intro's "no Mermaid syntax" → "no render syntax (Mermaid/React Flow/ELK)" with a pointer to the new purity test. Added `render_react_flow` to the parent Key-Symbols row. **Left the "Runtime Overlay Join Contract" section untouched** — it's the read-only Task-133 coordination seam.

**Purity guard `tests/test_core/test_graph_model_purity.py` (H12).** Two tests: (a) `model.py`/`build.py` carry no render tokens (`elk`/`position`/`classDef`/`:::`/`parentNode`); (b) AST-check that `react_flow.py` imports only `graph.model`/`graph.scope`, never `mermaid`.

- **The load-bearing insight that keeps the guard honest:** the forbidden set is render *syntax* tokens, NOT the words "mermaid"/"react flow" — both appear as legitimate **prose** in the model (`model.py:154` "Mermaid end-sink"; `build.py:721` "React Flow renderer" docstring). Forbidding the prose words would false-fail the guard; forbidding the syntax tokens catches the real leak (a layout coord, a Mermaid directive, RF's `parentNode` field). Verified both prose lines survive.
- **H12 word-boundary precision:** alphanumeric tokens match on `\b…\b` (case-insensitive) so `position` flags but `decomposition`/`composition` don't; `:::` (punctuation, no word boundary) matches as a substring. Mutation-checked the helpers directly (standalone `position`/`ClassDef`/`elk`/`:::` flag with correct line numbers; `decomposition`/`composition` don't; a `mermaid` import and a non-allowed graph import are both caught).
- **Deviation from plan-prose, justified:** scanned **model.py + build.py only** (the two files the plan names + the two where render syntax could plausibly creep — `scope.py` is already a pure regex extractor, out of the named set). Scoped the import-purity check to **react_flow.py only** (not a symmetric mermaid check) — the plan keeps `mermaid.py` untouched, and `mermaid.py` legitimately imports `scope.refs_in` too, so a symmetric assertion would add nothing.

**Gates (the Phase-5 deliverable):** No production code touched, so Mermaid goldens are inherently byte-identical and the server/contract runtime is unchanged from committed Phase 4 — re-verification of runtime behavior would be redundant.

**Not re-run (stated, not skipped):** the browser E2E (plan steps 3–5: `pflow ui` renders the harness + six patterns) and `make ui-build` were verified by the Phase-4 agent (the 131 KB harness render, the empty-wheel `artifacts` fix). Phase 5 changed zero runtime/frontend code, so those outcomes can't have regressed; re-driving a browser here adds no signal — the one genuinely un-re-verified item is the *visual* "no information loss" bar, which rests on the user's eyes (the build-side contract logic is locked by tests).

**Staging:** `web/` (38 files incl. `package-lock.json` — npm ci needs the lock; `node_modules`/`dist`/`src/pflow/ui/static` gitignored) was committed in `38fd6fe0` ("phase 4 implemented"); the only uncommitted Phase-5 work was the 2 CLAUDE.md edits + the purity test + this log.

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

**Mutation-verified (the only thing that makes it worth keeping):** injected an edge-drop into the renderer's `_resolve_edges` (skip `branch` edges) → the test **fails on both `conditional-branching` and the harness** with a precise message (`check-validate -[branch]-> fix-tests … silently dropped`). The old integrity-only assertion passed that same mutation.

Considered and **rejected** as low-value: expanding the test to all 58 examples (the 6 are deliberately chosen for structural variety — the rest are redundant shapes, i.e. coverage-padding); a real-data W1 boundary check (reimplements `_visible_anchor` in the test for marginal gain over the strong synthetic pin); browser-based CI tests (high-maintenance/flaky — manual browser verification is the right level for the visual layer).

### Task review + PR opened — task landed (2026-06-08) ✅

Wrote `task-review.md` (the knowledge-transfer doc for future agents: deviations, the GOLD gotchas, patterns/anti-patterns, the forward-compat overlay seam) with explicit trust boundaries marked (`[verified]` = what I implemented/verified end-to-end; `[relayed+read]` = Phases 1–4 internals from this log cross-checked against the committed code). Committed Phase 5 as `7d2f73b0` on top of `38fd6fe0` ("phase 4 implemented") — docs + the two mutation-verified guards + review + log; no production-code changes. Pushed the branch (was unpushed) and opened **PR #496** (`feat/workflow-visualization-static-viewer → main`, +10858/−32, 67 files, 2 commits).

**Issue-link decision (the one fork at PR time):** verified **no GitHub issue maps to Task 168** — issue #168 is an unrelated *closed* issue (template-consumer debt), and #452 is about loop-edge rendering in the *Mermaid* `visualize`, a sibling concern in a different renderer. The repo has issue-less (task-tracked) PRs, so no `Fixes` line; per the user's choice the PR references **#452 as *related*** only. `task-168.md` Status is **done**.

**Handoff caveat left in the PR body:** the `web/` bundle is built in CI only on the *release* workflow (`setup-node` + `make ui-build`); any PR-CI that builds wheels needs a Node step too, or the `[ui]` wheel ships empty (guarded by the `test -f static/index.html` assertion). Nothing else outstanding — the feature is complete and verified.

### Code-review response — evaluated, 1 disputed + 3 doc/comment touch-ups (2026-06-08) ✅

Evaluated an external code review of PR #496 (4 findings, no criticals). The headline: the **one item flagged "fix before merge" was a false positive.** Reviewer claimed `handles.ts`'s `PORT_SOURCE = "io:"` is a strict prefix of `PORT_TARGET = "iot:"`, making `handleType` order-dependent (reorder → IO targets mis-typed as source → React Flow silently drops the edge). **Disputed:** the trailing colon breaks it — `"iot:x".startsWith("io:")` is `false`, so the two are already disjoint and no string starts with both; reordering the branches is a no-op. Verified empirically + exhaustively across every prefix pair. Also disproved the secondary claim (the HANDLE-TYPE invariant fixture *does* exercise an `iot:` handle in a target slot, so a genuine type bug fails it). Left a defensive comment instead of the proposed rename — neutralizes the misread (and the real footgun: dropping a colon would make bare `"io"` prefix `"iot"`) without churning correct, well-tested constants.

The other three were valid low-priority polish, applied (all non-behavioral): (a) **no-CORS security tripwire** comment in `server.py::create_app` — the absent `Access-Control-Allow-Origin` is load-bearing (binds 127.0.0.1, read-only GET, so a cross-origin page can't read the 422 body that may echo a source line); a future `CORSMiddleware`/mutating endpoint must revisit the file-content exposure; (b) **inline-all payload-size** forward-compat note in `ui/CLAUDE.md` (multi-MB payloads are fine local single-user; remote/multi-client may want a by-ref fetch); (c) renamed `test_build_bug_on_validated_ir_is_loud_500` → `test_unexpected_pipeline_exception_is_loud_500` (it patches `resolve_validate_build` wholesale, so the name overstated the validate/build boundary). 4 files, +28/−6. Uncommitted.

---

# Phase A — Visual Redesign (Tines/n8n aesthetic) — HANDOFF (2026-06-09)

> **What this is.** A *user-driven, frontend-only* restyle of the `pflow ui` canvas to the
> Tines/n8n/Flowise look — done across one long iterative session, **building blind** (the
> implementing agent has no canvas; the user reviewed each iteration via screenshots). Spec/
> design for Phase A: `../research/visual-redesign-knowledge.md` (the KB — Flowise teardown,
> gradient technique, gotchas) + `implementation/sub-plans/phase-a-plan.md`. At handoff time all Phase A
> work was uncommitted and one piece — the icon *connector stub* — was unfinished; it was SOLVED
> in the 2026-06-09 entries below (the handoff's problem statement is kept, compressed, for the
> confirmed-hypothesis history).

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

The mount test (`GraphView.test.tsx`) and `flow.test.ts` (incl. a new TD-fork test + the HANDLE-TYPE
invariant) are green.

## Critical learnings & insights (the GOLD — origin record; CURRENT canonical versions live in `web/CLAUDE.md`)

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
   Removed `DESC_LINE`; `leafSize` returns `HEADER_HEIGHT` (68) for compact. *(The second half of
   this learning is SUPERSEDED, 2026-06-09: the flare now anchors to the TILE itself — a child of
   `.node-tile` — so it's height-independent and no stub `top` re-derivation exists. The
   fixed-68px compact height still holds.)*
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

## The open problem at handoff — the icon connector stub (SINCE SOLVED — history only)

At handoff the connector stub (a kind-colored flare bridging a control edge into the icon tile,
TD+beautiful) was UNFINISHED: a visible gap between stub tip and edge, a gap at the tile base, and
wrong proportions — the implementing agent was blind (no browser) and its on-paper geometry kept
disagreeing with the render. The handoff's central hypothesis — **React Flow mis-measures a
`Handle` nested inside a transformed, absolutely-positioned container extending OUTSIDE the node's
box** — was later MEASURED and confirmed (~5px endpoint divergence), and its preferred fix shipped:
handle on the node border, flare as pure decoration. The full resolution story lives in the
2026-06-09 entries below ("real-browser feedback loop" → "implemented + tuned" → "SOLVED — the
paint ≠ the box"); the current geometry rules live in `web/CLAUDE.md` → "Icon connector flare".
*(Standing user choices from this phase: Option B tile — neutral + brand icon, NOT solid-color;
subtle card border. Don't re-litigate.)*

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

### The connector bug — MEASURED, not theorized

First use of the new loop: `inspect` on `conditional-branching` framed on `classify` quantified all
three reported gaps (edge endpoint vs flare tip **~5px**; flare base vs tile **~2px**; box 16×14 →
the hourglass look) and **confirmed the handoff hypothesis**: the `<Handle>` inside the transformed,
outside-the-box `.node-connector` div makes React Flow draw the edge endpoint ~5px from where the
handle renders. The structural fix (handle on the node border; flare as pure opaque decoration
overlapping both ends, so gaps CANNOT exist) was designed here and built in the next entry.

### Connector flare — implemented + tuned live in a real browser (2026-06-09) ✅

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

*(The user also made manual edits this session — a `:root` palette re-theme; base anchor nudged to
`+3px` exact-touch. Built in `WorkflowNode.tsx` + `index.css`; landed in `dc419be4` with the
remaining two symptoms resolved in the next entry.)*

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
Behavior-neutral by construction; real-browser screenshot of
`conditional-branching` TD/beautiful identical. Remaining batch (in order): lazy-ELK dynamic import →
class-name grep comments → `metrics.ts` consolidation → `defaultHidden`.

### Endpoint fades: error/end edges blend into their nodes (2026-06-09, user-driven) ✅

User request from a screenshot: the solid-red error edge slams into the amber source and the green
target connector; wanted the line to take each node's type color for the last ~20–30px ("a small fade
… from both nodes at either side"), and the same for the grey end edge but only at the node end.

**Implementation — one stops-builder, not a new edge component.** All four control kinds
(`sequential`/`branch`/`error`/`end`) now route through `GradientEdge` (`flow.ts toFlowEdge`:
`isControl = CONTROL_KINDS.has(...)`); the exported pure `gradientStops(kind, from, to, chordLen)`
decides the stop list: sequential/branch keep the full-length source→target blend (unchanged);
**error** = node color → red at `FADE_PX` (26px) → red → target color at both ends; **end** = node
color → faint grey at the source only (the end-sink side stays grey). Offsets are `FADE_PX` as a
fraction of the source→target chord (the `userSpaceOnUse` gradient axis), clamped to 0.4 so the two
fades can't cross on short edges; degenerate zero chords fall back to the clamp. CSS strokes for
`.edge-error`/`.edge-end` were REMOVED (the component owns color now — same rule as
sequential/branch); the end edge's dot pattern stays in CSS.

**Two decisions worth keeping:** (1) semantic colors are `var(--danger)`/`var(--text-faint)` set via
the stop's `style` (a CSS context, so `var()` resolves) — the user manually re-themes `:root`, so a TS
mirror would drift; (2) extending `GradientEdge` beat a separate `FadeEdge` under the deletion test
(path/label/gradient scaffolding would be duplicated for a 20-line stop-list difference).

**Side effect (accepted):** the error label now renders as the bordered `.edge-label` chip (it rides
the custom edge), consistent with TD branch labels.

**Verified:** 5 new tests pin the stop geometry; a flow test pins all-control-kinds→gradient —
a regression to `"default"` would render INVISIBLY since CSS no longer strokes those kinds. Real-browser screenshots confirm red→green landing on the error handler's
connector and the green→grey dotted exit. `FADE_PX = 26` is the tuning knob.

### Best-practices batch 2 — lazy ELK + metrics single-source + defaultHidden + tripwire (2026-06-09) ✅

The rest of the fresh-eyes review's leverage list, in one pass. Geometry verified **pixel-identical** via `inspect` after the CSS-var migration
(tile 84×84, connector 21×17, same coordinates); both densities screenshot correctly through the real
server.

- **Lazy ELK (`layout.ts`).** Initial bundle **1.79 MB → 372 KB** (121 KB gzip); ELK is its own
  1.44 MB chunk loaded on FIRST layout via a memoized `loadElk()` (dynamic import inside the
  already-async `layoutGraph` — callers unchanged). A failed chunk load rejects `layoutGraph` → the
  hook's existing error-banner path; no new failure mode. *Gotcha:* elkjs's instance type is the
  named `ELK` interface, NOT the default export (that's the constructor object). *Load-bearing
  check:* the relative dynamic import resolves through the Python `StaticFiles` server under
  `base:"./"` — verified by rendering through the real server. The wheel's `artifacts` glob already
  covers the new chunk file; Vite's >500 KB warning now refers to the *async* ELK chunk — harmless.
- **`graph/metrics.ts` — geometry single-sourced (kills THE recurring bug class).** Seven
  layout-coupled constants (node-header 68, row 26, ports-header 30, tile 56, tile-border 3,
  edge-stroke 3, group-header 38) live in ONE module: `flow.ts` sizes (same exported names — no
  caller churn), `layout.ts` group padding (derived `groupHeaderH + 8`, was a magic 46),
  `WorkflowNode` (`CONN.tipW` + the anchor's border term — the "keep equal to index.css" comment
  contracts are gone), `GradientEdge` stroke width. `main.tsx` injects them as CSS custom properties
  on `:root` BEFORE first paint; **9 CSS rules** now read the vars, with a `:root` note that CSS must
  never hardcode these numbers again. `metricsCssVars()` is a pure map (no DOM) so `graph/` stays
  node-env testable; the DOM loop lives in main.tsx.
- **`defaultHidden` on `EdgeData`.** Set once by the build (`toFlowEdge` / loop arcs); `applyFocus`
  now reads the data fact, not the mutable `hidden` flag it also writes. The implicit "applyFocus
  must only ever see the pristine `laid` snapshot" invariant is no longer load-bearing —
  re-processing decorated output is safe (matters for the overlay's future incremental updates).
- **ELK-size dev tripwire (`WorkflowNode`) — with the twist that makes the naive version useless:**
  React Flow PINS the node box to the predicted size (`.node` fills 100%), so `offsetHeight` always
  "agrees" with `leafSize` — drift shows up as content OVERFLOWING the pinned box. The tripwire
  compares `scrollHeight > clientHeight` on **detailed** nodes only (compact is fixed-height and its
  connector flare legitimately overflows below the box → false positives). Dev-only
  (`import.meta.env.DEV`, compiled out of prod), inert under jsdom (`clientHeight 0` guard).
- **Grep-ability comments:** the constructed class families now name their construction sites at
  their CSS rule blocks — `edge-${kind}` (flow.ts toFlowEdge) + literal `edge-loop`/`edge-shadowed`/
  `edge-dimmed` (applyFocus), and `group-${kind}` (GroupNode). `kind-*`/`ports-*` have no CSS rules →
  nothing to annotate.

**The best-practices list is complete.** Everything actionable from the fresh-eyes pass is done (memo,
lazy ELK, metrics, defaultHidden, tripwire, grep comments); the consciously-rejected items (CSS Modules
migration, Tailwind, state lib/router, React 19 churn, a11y for a localhost tool) are recorded in the
review entry — don't re-litigate without a new trigger.

### Connector jag follow-up + click-to-expand feature (2026-06-09) ✅

*(The paint≠box root cause this session found is the canonical "Connector flare SOLVED" entry
above — not retold here.)* Two residual touches:
- **Jag follow-up (user spotted):** landing the cove EXACTLY on the border's outer edge puts the
  silhouette's 90° corner on the color boundary → a 1px AA jag. Added `baseSink: 1` — the landing
  line sits 1px INSIDE the border, the curve crosses the edge while still sloped, no corner on the
  silhouette. (`baseSink + baseApron` must stay < the 3px border.) Verified by zoomed screenshot
  crops (sips crop+upscale of the `screenshot` output — a useful trick the tooling docs don't name).
  *(Later re-tuned: baseSink → 0, anchor +2, 2026-06-10 — under the new palette no jag reproduces.)*
- **Focus ring** → `var(--kind, var(--accent))` (user ask).

**Click-to-expand in beautiful (new feature, user-driven).** Clicking a node expands it in place to
the full advanced body — and its DATA-FLOW endpoints expand with it, so the revealed lines land
row-to-row (output row → param row) and the floating `stdout → data` label drops when they do (rows
name the fields; the label STAYS when an end falls back to node level, e.g. `input_name` naming a
dict KEY inside a param rather than a param — conditional-branching's `data` is this case, matching
advanced exactly). Control-only neighbors stay compact. Design decisions, in order:
- **Re-layout on expansion — the user overturned my no-re-layout recommendation, and was right.**
  I'd proposed z-elevated overlap (the "focus never re-layouts" principle); the user chose re-layout
  for TD. In TD a card grows ALONG the flow axis straight into the node below — and an expanding
  neighbor ABOVE the focus must push everything down — so re-layout is near-mandatory, not merely
  worth it. One code path both directions (LR gets it free). The principle is now scoped: *focus
  dim/reveal never re-layouts; focus-EXPANSION does (beautiful only — in advanced the expansion set
  is a stable EMPTY constant, so clicks there still never re-layout).*
- **Camera anchoring is what makes re-layout feel acceptable:** the hook records the focused node's
  absolute position across the re-layout and pans the viewport by the delta IN THE SAME EFFECT that
  pushes the new positions — the graph reflows around a stationary clicked node. Anchoring applies
  only when the SAME view (graph/density/direction/collapsed identity-compared via a ref) re-laid
  out, i.e. only expansion changed; workflow/direction/density changes keep their own fit semantics.
- **`expanded` is a per-node FLAG, not a density override** (`LeafData.expanded`): density stays
  "compact" so the TOP flare survives on an expanded card while the body renders; the BOTTOM flare is
  dropped (tile no longer abuts the bottom border — it would float mid-card). Handle resolution went
  per-ENDPOINT (`rowsVisible(id) = detailed || expanded.has(id)`), so a half-expanded line lands on
  the row only where the row actually renders (the silent-drop rule), keeping its label.
- **`?focus=` URL param** (read-only, resolved like `node=`): deep-links the click state AND is the
  only way the screenshot/inspect tooling can capture the focused/expanded state (it can't click).
  *Gotcha hit:* applying it at `status==="ready"` raced React Flow's store (empty `getNodes()` burned
  the one-shot flag, silently no-op) — gate on `useNodesInitialized`, same as the fit effect.

Verified in the real browser both TD and LR via `focus=` screenshots (expansion, row-landing, label
rules, anchoring, flares, dimming, kind ring). +8 pins (expandTargets/expanded-build/
row-to-row+label/half-expanded/advanced-ignores/ports-focus + 2 viewParams).
Files: `flow.ts` (expandTargets, BuildOptions.expanded, per-endpoint handles, label rule),
`WorkflowNode.tsx`, `useWorkflowGraph.ts` (expansion derivation + anchoring), `GraphView.tsx` +
`viewParams.ts` (focus=), `index.css`, `web/CLAUDE.md`, SKILL.md (focus param), this doc +
visualization-requirements.md. Zero contract/Python change.

### CONDITION pseudo-kind (2026-06-09, user-driven) ✅

**CONDITION: a decision code node now presents as its ROLE, not its kind** (label `CONDITION`, generated
fork-dots icon, hot orange `#ffa657`) — replacing the incoherent blue "decision" pill (three identity
voices on one card: python tile, amber CODE, blue pill; hierarchy inverted — the structural headline was
the smallest element). The fork that made it safe: the user challenged "can a shell node even be a
condition?" → verified NO — dynamic `next` routing is **code-only** (guide/features/branching.md), so
`is_decision ⟹ kind == code` (confirmed empirically: corpus sweep of all buildable examples — every
decision node is code). Tines' role-as-type model therefore applies cleanly; my earlier "worker-decider"
objection (a shell node that runs checks AND branches) is impossible by construction. Decisions, all
user-made: label = full replacement (not "CODE · CONDITION"); color = NEW orange, code keeps `#ffd479`
(blue rejected — llm/http/accent already own blue; recoloring code would churn the commonest kind and
collide with loop/warn ambers); icon = upside-down share/fork dots (one in, two out — a mini node-graph;
user-picked over split-arrows/lightning/diamond). Implementation: `isCondition`/`nodeColor`/
`CONDITION_COLOR` in `utils/format.ts` are THE seam (card + tile + category + edge gradients all route
through `nodeColor`); icon is a data-URI SVG generated from `CONDITION_COLOR` (can't drift); CSS
`--decision` repointed blue→orange so branch handles/labels match the node (hardcoded blue tints in
`.branch-label` → color-mix on the var); decision badge deleted (loop-badge precedent); ReadPanel shows
`code · condition` (canvas↔`type: code` mappability). Kind gate (`kind === "code"`) is defensive for a
future where branching extends. +4 pins (condition presentation ×3, condition edge color);
verified on canvas (conditional-branching TD/beautiful screenshot).

### Tines edge language: rounded-orthogonal paths + ELK ports (2026-06-09, user-driven) ✅

> User goal: edge paths like the Tines references (axis-aligned runs, generous rounded turns, the
> trunk splitting just below the source, straight columns into targets). Two rounds: the path swap,
> then a 4-issue review against screenshots. **All `web/` — zero contract/Python change.**

**Round 1 — path generator swap.** Picked via a `shoot` SVG lab (3 variants side by side): bezier vs
midpoint-rail smoothstep vs **near-source rail** (the Tines signature) — user confirmed direction.
`GradientEdge`: `getBezierPath` → `getSmoothStepPath` with `borderRadius` and a `railCenter()` helper
(`centerY = sourceY + 24` when the target is far enough ahead; mirror for LR; stock midpoint/wrap
routing otherwise — short hops, backward edges). Gradient/fades/labels untouched (the path is just
`d` under the same stroke).

**Round 2 — the user's 4 issues, and the unifying root cause.** (1) end-dot edge jogged for no
reason; (2) S-jog with two hard turns into a merge target; (3) fan-out children too far + the
image-12 pattern (primary child continues the parent's column straight); (4) data edges (still
bezier) swooping across node bodies. **Issues 1–3 were ONE bug: ELK aligns node CENTERS but every TD
control handle renders at the ICON COLUMN (x=34)** — every "straight" connection carried a ~100px
handle offset that beziers had hidden and orthogonal exposed honestly. Fixes:
- **ELK fixed ports (TD only, `layout.ts`):** every leaf declares `FIXED_POS` ports at `ICON_COL_X`
  (top/bottom); edges whose endpoint handle is `NODE_IN`/`NODE_OUT` connect port-to-port. Port-aware
  NETWORK_SIMPLEX aligns columns icon-to-icon: chains + end sinks dead straight, exactly one branch
  continues the trunk. LR stays portless (side-centered handles already match ELK's center anchors).
- **Leftmost-stays-straight (user decision):** each target's FIRST non-error control in-edge (model
  order) gets `elk.layered.priority.straightness=10` — the leftmost sibling keeps the straight
  column through forks AND merges.
- **Error branches order LAST (user decision):** nodes whose only control in-edges are `error` are
  partitioned to the end of their sibling list; with model order forced, error handlers fan out
  rightmost (TD) / bottom (LR).
- **GOTCHA (bisected with a standalone elkjs script, /tmp/elk-bisect.mjs):** EVERY
  `considerModelOrder.strategy` value CRASHES elkjs under `INCLUDE_CHILDREN` with a cross-hierarchy
  edge ("Cannot read properties of undefined (reading 'a')").
  `crossingMinimization.forceNodeModelOrder` is the survivor and does what we need. The vitest ELK
  smoke test caught this pre-browser.
- **TD layer spacing 140 → 80** (direction-aware; LR keeps 140) — the Tines proximity.
- **Data edges → built-in `smoothstep`** (`pathOptions.borderRadius`), dotted styling intact — kills
  the issue-4 bezier swoop; full node-avoidance stays the deferred smart-router.
- **Geometry single-sourced:** `METRICS.headerPad`/`edgeRadius` + derived `ICON_COL_X` (was a
  hardcoded `left:34` in WorkflowNode and a number ELK never knew); `--header-pad` CSS var.

**Verified:** tests updated (type-pin: data_flow → smoothstep + radius); screenshots TD/LR/advanced/harness; `inspect` proves alignment numerically — trunk column
x=506/506/506, merge 141→141, end dot 871→870 (1px = dot-center rounding). The harness's backward
cycle edge (validate→decide) now draws as the clean orthogonal U from the Tines reference. **Known
residuals:** LR merge target sits ~8px off the straight row (no LR ports yet); loop arcs (LoopEdge)
still the old amber bezier arc — restyling to the orthogonal U is the agreed next step.

**Follow-up round (user-caught, same session):** (a) *data edge landed on the node TOP instead of the
`inputs` row* — `input_name` was a dict KEY (`inputs: {data: ${...}}`), and row-matching only knew
param NAMES; `targetHandleFor` now lands on the param row CONTAINING the key, gated on that key's
value being a `${...}` string (the exact condition that created the edge — degrade, never
mis-attribute). (b) *rail corners noticeably tighter than the rest* — smoothstep clamps every bend to
HALF its adjoining segment, so the 24px rail offset starved its corners to ~12px vs 18 everywhere
else; `RAIL_OFFSET` is now derived `2×CORNER_RADIUS` (36) with closer targets getting the halfway
point (== stock midpoint, so the old "enough room" threshold is deleted, not tuned). +1 pin:
dict-key row landing. Verified on canvas (advanced: stdout line lands on the `inputs` row;
beautiful: merge corner now full-radius).

### Condition icon finalized via shoot-lab iteration (2026-06-09) ✅

Iterated the condition glyph in a `/tmp/condition-icon-lab.html` shoot-lab (9 color variants × both
render sizes, mock tiles) instead of rebuilding the app per attempt — the right loop for shape/color
taste. User picked **all-hollow + leg gradient**: orange in-ring, white out-rings, legs blending
orange→white (the icon does in miniature what GradientEdge does on the canvas). Final
`assets/icons/condition.svg` is built to make the lab's two gotchas structurally impossible:
- **objectBoundingBox gradients apply in the path's LOCAL space, BEFORE its transform** — a flipped
  path flips its gradient (cost one "looks identical to 8" round + one upside-down round). Fixed by
  BAKING the flip into the path coordinates (scripted y→175−y, no transform in the file) so the
  gradient axis reads naturally.
- **Ring cores are true `evenodd` HOLES (transparent), not tile-colored circles** — the tile bg shows
  through with nothing hardcoded, so a future tile re-theme can't strand the icon. The enlarged top
  ring is a stroked circle (outer 40/inner 24) matching the r24 hole; gradient stops 0.41→0.62 span
  exactly the legs' VISIBLE run (they emerge from under the r40 ring at y≈72; out-rings stay pure
  white). Lesson reconfirmed: a blend hidden under an opaque overlay reads as no blend — set stops
  to the visible run, not the geometric one.

### Ports-node rows connect SIDEWAYS in both directions (2026-06-09, user-caught) ✅

In TD the
Inputs/Outputs row handles were `Position.Top/Bottom` — each row's dot rendered floating at its
bottom-center BETWEEN rows, and binding edges dove into the middle of the stack (visually
disconnected; reproduced on the real lyrics-generator workflow). A row in a vertical table always
connects on its left/right sides — the same rule the advanced param/output rows already follow;
direction moves the trunk, not a table row's connection point. Fixed by making the row sides
CONSTANT (left=receive / right=feed); a side bonus of constant sides is the handles no longer
move on an LR↔TD flip (direction-dependent handle positions without `useUpdateNodeInternals`
are a stale-measurement trap). Verified via `inspect` (row handles at the node's left/right
edges, per-row y) + a zoomed crop: all six output bindings land exactly on their row dots.
*(PortsNode died with the IO-rows redesign, 2026-06-10; the rows-connect-SIDEWAYS rule survives
on PortRows and is a design principle in visualization-requirements.md.)*

### Ports-edge follow-ups: facing sides + data-edge lanes (2026-06-09) ✅

**Ports-row edges attach on the side FACING their peer (user-caught crossings, same session) —
machinery since DELETED; lessons only** *(mechanics trimmed 2026-06-11 — they described dead
code)*. Binding edges between two ports nodes left the source's right side and wrapped all the
way around to the target's left — and sibling wrap-arounds crossed each other. Root cause:
handle sides were fixed at BUILD time, but which side faces the peer is only knowable AFTER
layout — so a post-layout side-flip pass over mirrored handles shipped here. *(The entire
facing-sides machinery was DELETED with the ports table in the IO-rows redesign: rows on the
boundary got structural sides — the flip problem ceased to exist rather than being solved. What
survives: the side comparison must use the HANDLE x, not node centers — see the row-side
settlement entry — and the trailing-colon prefix discipline still documented in handles.ts.)*
NOT a router — full crossing avoidance stays the deferred smart edge-router.

**Data-edge LANES: parallel bindings no longer overlap pixel-exactly (user-caught, same session).**
All data edges at a node turned at smoothstep's default 20px stub, so a 6-row Inputs node's
bindings shared ONE vertical lane (and the consumer side shared another) — visually a single
ambiguous line. `assignDataEdgeLanes` (flow.ts, build-time — it's lane multiplexing, not geometry)
greedily gives each data edge the smallest stub-offset bucket unused at EITHER endpoint node
(offset = 16 + 8·lane, 6 buckets then wrap), so shared verticals fan apart on both sides. Control
edges exempt — a fork/merge sharing its rail IS the trunk look. `FlowEdge` type now carries
`pathOptions` explicitly (RF's Edge union only types it on the smoothstep variant). Gotcha that
shaped the test: two parallel NODE_IN-landing data edges between the same pair DEDUPE (the `seen`
key), so the fixture needs real param rows for parallel lines to exist at all. Verified on the
harness seg-gate (zoomed crop): distinct parallel lanes, each into its own row. Remaining
crossings between unrelated lanes = the deferred smart edge-router.

### Perf: layout cache + ELK in a Web Worker (2026-06-09, user-driven) ✅

User asked about re-layout cost when clicking a node on large workflows. **Measured first** (temp
vitest probe on the real 128-node lyrics-generator contract): buildFlow 0.4ms, **ELK ~120–170ms per
layout, on the main thread** — the whole cost, and it ran TWICE per click-cycle (expansion + the
un-focus recompute of the already-seen base layout). Two fixes, both in the established seams:

- **Layout cache (`useWorkflowGraph`):** Map keyed by the full layout-affecting state
  (`density|direction|collapsed|expanded` — focus itself is NOT layout-affecting, only its derived
  expansion set), insertion-order eviction at 24, cleared per workflow fetch. A cache hit applies
  SYNCHRONOUSLY — un-focusing and re-clicking land in one paint, no ELK, no async gap. Camera
  anchoring still applies (the pan is a delta between layouts, cached or not).
- **ELK in a Web Worker (`layout.ts loadElk`):** `elk-api` shell + Vite `?worker` import of
  `elk-worker.min.js`; first-click layouts still take ~150ms but no longer freeze the canvas. A
  load-time probe layout fails fast; fallback to the bundled main-thread ELK — silent under
  node/vitest (no `Worker`), `console.warn` in a browser (a silent fallback is an invisible perf
  regression). **Verified through the real Python server** (resource-timing probe via a throwaway
  evaluate_script workflow): worker chunk fetched, bundled chunk NOT fetched. Wheel disk note: both
  chunks now ship (~+1.4MB) — the fallback is never fetched at runtime unless needed.
- **Also diagnosed (user observation):** the "instantly expands then everything moves" two-phase
  look = the instant focus pass (ring/dim/reveal on the OLD layout) + the ELK result landing ~150ms
  later with the camera-anchoring pan. Cache collapses the gap to ~0 for seen states. A CSS
  `transform` transition on nodes was considered and REJECTED: RF computes edge paths from store
  positions (updated once), so nodes would glide while edges snap — detached lines; the correct
  per-frame store interpolation is the genuinely costly option. Don't revisit without measuring.

The ELK smoke test exercises the node fallback path.

**Cache-click "shake" fixed (user-caught): the stale-paint guard.** On a cached click the two
effects fire in the same commit, and the decoration effect ran FIRST with the new focus against the
OLD laid snapshot — one frame of ring/dim/reveal at stale positions, then the cached layout + pan:
a visible shake (the same mechanism as the original two-phase look, compressed to one frame). Fix:
the laid snapshot carries the `layoutKey` it was computed for, and the decoration effect paints
ONLY a matching snapshot — every click is now exactly one visible change, cached or not (uncached
clicks no longer flash the stale decoration either; with the worker there's no freeze during the
wait). Focus-only changes (advanced mode) keep the same key, so pure restyles stay instant.
Focused-state render verified via `focus=` screenshot.

### Animated expansion transitions — store interpolation, size-gated (2026-06-10, user-driven) ✅

The user chose to test the animation previously rejected-on-paper — with the agreed guard: small
flows only. Built the CORRECT variant (the one the rejection note priced): positions interpolate
THROUGH the React Flow store per frame so edge paths follow the nodes — a CSS transform transition
would glide nodes while edges (computed from store positions, updated once) snap: detached lines.
In `useWorkflowGraph` effect 4:
- Start positions (`pendingFromRef`) captured under the SAME condition as the camera-anchoring pan
  (expansion-only re-layout of the same view) — direction/density/collapse changes keep their snap
  + fit semantics; focus-only re-decorations never animate (`paintedRef` identity check).
- 200ms easeOutCubic; the anchoring pan eases WITH the positions so the clicked node stays
  stationary through the whole glide, not just at the endpoints.
- **Per frame, only MOVED nodes get new object identity** — memo'd unmoved nodes skip re-render;
  the final frame sets the exact decorated snapshot so identities settle.
- **Gates:** `ANIMATE_MAX_NODES = 60` flow nodes (per-frame edge recompute is the real cost — the
  128-node lyrics-generator snaps as before; conditional-branching glides), `prefers-reduced-motion`
  → snap, mid-glide interruption (view change/unmount) lands on the final state in cleanup.
Tuning knobs: `ANIMATE_MAX_NODES` / `ANIMATE_MS` (hook top). End-state verified
pixel-identical via the `focus=` screenshot (that load path exercises the
animation: base layout → focus applied → animated expansion → settle). *(Two transient flow-test
failures during this round were the OTHER agent's in-flight smoothstep→DataEdge-lanes conversion —
resolved by them before this entry; not animation-related.)*

**DataEdge born: per-lane geometry for the middle rails (2026-06-10) — its FIRST color treatment
was a same-day detour, superseded by the focus-fade correction below.** Lane stubs alone left the
MIDDLE rails overlapping (each edge's mid-segment sits at its own source→target midpoint —
near-identical for same-stack bundles). The built-in smoothstep exposes no centerX/centerY, hence
the custom `components/edges/DataEdge.tsx` (type "data"): lane → stub AND mid-rail offset; the
component owns the stroke, so `.edge-data_flow` CSS keeps ONLY the dash — a regression to a
built-in edge type renders INVISIBLY (type-test pinned). Lane rides `EdgeData.lane`
(pathOptions removed). Colors were explored via an extended shoot-lab (5 panels) and first shipped
as lane-tinted bodies + endpoint node-color fades — reverted within hours (user: confusing). The
lab finding that SURVIVES: **full node-color gradients on data lines are rejected WITH EVIDENCE** —
same-endpoint bundles get IDENTICAL gradients exactly where disambiguation is needed, and the
teal=data semantic dies. Verified on the harness seg-gate crop: lanes parallel and traceable.

**User verdict: animation KEPT** ("this looks great"). Open calibration
question parked for later: is `ANIMATE_MAX_NODES = 60` the right cap, or can the per-frame cost
comfortably carry 100+? Measure before raising.

### Dark themed minimap (2026-06-10) ✅

The stock white `<MiniMap>` was the last unthemed surface — a white hole in the dark canvas on
every screenshot. Now: dark rounded container + border + out-of-viewport mask in `index.css`
(`.react-flow__minimap*`), and per-node fills via `minimapNodeColor` (GraphView): leaves take
their kind color through the `nodeColor` seam (CONDITION-aware), groups a faint white wash so
containers read as regions, ports/end neutral. **Gotcha: minimap node fills must be REAL color
strings, not CSS vars** — React Flow paints them as SVG fill attributes, where `var()` does not
resolve (the container/mask are CSS, so vars are fine there). Verified via zoomed crop on the
lyrics-generator: kind-colored dots, region washes, visible viewport window.

**Color correction (user clarified, 2026-06-10): focus-directional fade, NOT lane tints / node fades.**
The C+D treatments (lane-tinted bodies + endpoint node-color fades) read as confusing — what the user
actually wanted: a revealed line draws SOLID at the CLICKED node and fades a hint toward its far end
(direction-from-the-click). Reverted both color treatments (lane GEOMETRY — stubs + rail spread —
stays); `applyFocus` now marks incident data edges with `EdgeData.focusEnd` ("source"/"target" = the
end the focus is on; identity check extended so unfocusing restores object identity); `DataEdge`
draws unfocused lines flat `--data-edge`, focused ones as a same-color opacity gradient 1 → FADE_TO
(0.45, the tuning knob) oriented from the clicked end. The detour's lane-tint vars deleted
(deletion test). +1 pin (focusEnd ends/clearing/control-exempt); verified via `focus=classify`
screenshot.

**Zoom controls themed too (user-caught) + a tooling gotcha.** Same dark treatment as the minimap
for `.react-flow__controls*` (raised bg, border, `fill: currentColor` so the +/−/fit glyphs follow
the text color). While verifying, a screenshot came back with the OLD bundle (bezier edges, white
minimap) despite a fresh build — **the MCP Chrome's HTTP cache heuristically reuses assets because
StaticFiles sends no `Cache-Control`**; source-vs-render check confirmed the tree was fine. Pinned
in the skill's troubleshooting: cache-bust with a throwaway `&v=` param. (The real fix —
`Cache-Control: no-cache` on index.html — landed 2026-06-10 with the worker-hang closure.)

**LR branch fan-outs get lanes too (user-caught, 2026-06-10).** In LR a fork's outcomes leave their
OWN labeled row handles, yet railCenter funneled them all onto ONE shared vertical rail — distinct
lines collapsed into one segment. The TD shared rail is the trunk-split look and stays; the asymmetry
is structural: TD branches leave ONE point (the icon column), LR branches leave DIFFERENT rows.
`assignDataEdgeLanes` → `assignEdgeLanes` (now covers data_flow + branch + error; sequential exempt —
one out per node, merge rails already differ by source); `railCenter` takes a `lane` and staggers
centerX by 8px/lane in LR ONLY (TD ignores lane, pinned by test). +3 pins (railCenter: LR distinct
rails / TD shared / short-hop clamp). Verified on conditional-branching LR crop: three
distinct rails where there was one.

### Docs synced + corner radius tuned 18 → 24 → 20 (2026-06-10)

The edge-language arc was user-accepted ("great work"); synced the sibling docs — notably the
`web/CLAUDE.md` edges bullet was still claiming data_flow is a CSS-stroked built-in, now an
INVISIBLE-regression trap.

**Corner radius — user-tuned twice, settled at 20.** `METRICS.edgeRadius` 18 → 24 → **20** (one
constant, both edge components); DataEdge `STUB_BASE` 16 → 24. The honest answer to "are all
corners equally round?": NO by construction — the radius is a MAX; smoothstep clamps every bend to
HALF its adjoining segment, so cramped spots render tighter (data stubs were the worst at 8px, now
12px min; TD adjacent-layer hops cap ~17px regardless of the constant — raising THOSE needs more
layer spacing or custom bend math, not a knob). The dotted-vs-solid "different radius" perception =
control-side clamping + data wrap-arounds CHAINING two bends into one extra-round sweep. The
constant's own comment records the history and both effects.

### Collapse controls + big workflows open as an overview (2026-06-10, user-driven) ✅

The "big workflows open readable" batch (minimap theming was done separately just before). UI for
the toolbar control was decided via AskUserQuestion mockups — **buttons + count won**
(`[⊟|⊞] 4/12 open`; disabled states carry the extremes; the whole control hides when a workflow has
no containers). Implementation:
- **`graph/collapse.ts` (pure, node-env tested):** `collapsibleGroupIds` (workflow/batch only — IO
  wrappers are ports nodes, not boxes) + `initialCollapsed(graph, mode, protect)`:
  over-`AUTO_COLLAPSE_NODE_BUDGET` (60) workflows open fully collapsed; `collapse=all|none` URL
  param overrides both ways; a `node=`/`focus=` deep-link target's whole ancestor chain stays
  expanded (the link must always show its target). Budget doubles as a first-paint win: the first
  ELK run on the 128-node lyrics flow now lays out ~20 boxes instead of 100+.
- **GraphView:** one-shot per-workflow effect applies the initial set when the contract arrives;
  collapse-all clears focus (a ring on a hidden node is meaningless), expand-all keeps it. Toolbar
  gets `groupCount`/`openCount` (replaced the old conditional "expand all" link-button).
- **Verified in the browser:** lyrics-generator opens as a ~17-box pipeline ("0/23 open",
  collapse-all disabled); `node=fetch-youtube` deep link opens with exactly its 2-group ancestor
  chain expanded ("2/23 open") and frames the node; small workflows (no groups) show no control.
  +9 pins (7 collapse policy, 2 viewParams).

### Row-side semantics settled: strict param/output sides + gap-centered wrap rails (2026-06-10) ✅

**The detour (same day, reverted within hours — kept for its two surviving insights):** the
stdout→inputs data line wrapped around the condition node with its midpoint rail hugging the card's
top border. The first fix generalized facing-sides to param/output rows (mirrored handles) — and
the user immediately caught the cost: it trades away the **in-left/out-right convention**
("shouldn't we be consistent?"). What SURVIVED the revert: (a) the side comparison must use the
**HANDLE x**, not node centers — a row source exits its node's RIGHT edge, so a vertically stacked
pair (centers equal) still reads "peer to the east"; (b) the old near-vertical test had pinned the
bug as desired behavior — interrogate what a green test actually asserts before trusting it.

**The settlement (user decision):** ONLY ports rows switch sides (a ports row is a scope BRIDGE —
both directions ARE its semantics, dots on both sides by hard requirement); param/output rows are
STRICT-sided (the param/output mirrors were deleted, not parked). The ORIGINAL complaint — the rail
hugging the border — got its proper fix instead: new **`assignDataRails`** post-layout pass — a
data edge whose endpoint boxes have a clear gap on an axis gets `data.railX/railY` centered IN that
gap; DataEdge uses the hint over the blind handle-midpoint (which is what landed 10px above the
card). Post-layout edge decoration is now TWO passes chained in the hook
(`graph/portSides.ts`): `assignFacingSides` (ports rows, handle-x comparison) → `assignDataRails`
(rail hints; clears ENDPOINT nodes only — third-party nodes remain the smart-router's job). Pins:
param-never-flips + 3 assignDataRails cases. Verified: stdout→inputs wraps to the LEFT handle with
its rail mid-gap, ~55px clear of both nodes.

### Session close (THE close — earlier per-arc closes were merged here) (2026-06-10)

**Everything from "Connector aspect-ratio root cause" (2026-06-09) down is ONE UNCOMMITTED batch**
from two agents working the same files in parallel — the arcs are the entries above (connector +
CONDITION; the Tines edge language; the row-side settlement; the perf round; animated expansion;
minimap/controls theming; collapse controls; metrics + palette). **A per-author split was evaluated and
rejected** — WorkflowNode/index.css/flow.ts/flow.test.ts/useWorkflowGraph.ts/web/CLAUDE.md
interleave both authors, and each side's work references the other's (CONN reads METRICS; lanes
ride DataEdge; portSides + the layout cache wire into the same hook). Commit as one
visual-milestone batch.

*(Executed: the batch landed as `ec67c273` "alot of ui improvements" — gates ran, untracked files
added. Disk note that outlives it: the wheel's `artifacts` glob now also ships the ELK worker chunk
alongside the main-thread fallback, ~+1.4MB.)*

**Open threads for a next session (not blockers):** loop arcs → orthogonal U *(done — see the
loop-U / loop-rule-row entries below)*; LR merge ~8px residual (no LR ELK ports); smart edge-router
(deferred, dense-graph tail — `assignDataRails` clears endpoint nodes only, not third parties);
`ANIMATE_MAX_NODES`/`AUTO_COLLAPSE_NODE_BUDGET` both = 60 by guess — measure before raising; TD
adjacent-layer corner clamp (~17px regardless of `edgeRadius` — needs layer spacing or custom bend
math, not a knob). Bigger arcs: search/jump-to-node (⌘K); the live-run observability overlay
(Task 133 events onto `RFRef` — the next real increment).

### Sub-workflow node redesign + loop orthogonal U + batch deck (2026-06-10, user-driven) ✅ (uncommitted)

> Planned as "loop arcs → orthogonal U", but the user re-sequenced it correctly: *design the
> sub-workflow node FIRST* (both states) — the U wraps the box, so the box defines the loop's
> geometry. All `web/` — zero contract/Python change. Decisions made via a shoot-lab
> (`/tmp/subwf-lab/index.html`, three sections) + AskUserQuestion; all three recommendations
> accepted. Verified in the real browser on the
> tournament (TD expanded/collapsed, LR), run-cycle (batch deck), orchestrate (nested + the U
> around a whole region).

**The design (user-picked):** a container is ONE OBJECT IN TWO STATES. Collapsed = a real node
card (exact leaf anatomy — tile + frame + icon, category, name, count pill); expanded = a region
whose header is the card's identity shrunk (mini-tile + icon + category + title + count pill),
kind-tinted border. Sub-workflow kind color = **magenta `#e26ad8`** (lab compared candidates
AGAINST palette neighbors: hot pink collides with mcp `#ff8fab`, violet with claude-code/batch).
**Looped sub-workflow swaps its tile icon to the amber loop glyph** (user's idea) — safe because
the category line still says SUB-WORKFLOW; leaf kinds never swap (their icon IS their identity).
*(The swap was RETIRED with the chip rail, 2026-06-10 — identity never mutates; behavior is
border chrome.)*
Mid-build the user added the **batch deck** (Tines stacked-copies reference image) — shipped as
pure CSS pseudo-elements on `.group-card.group-batch` + `.node.batched` (unexpanded dynamic
batches).

**Structural payoff of leaf-anatomy reuse (the argument that won option 1a):** collapsed groups
joined the TD machinery for ~free — ELK icon-column ports (`layout.ts` portable set; trunks ran
through collapsed groups with a jog before) + connector flares (exported `Connector` from
WorkflowNode) + focus-dimming via the existing `.node.dimmed` rule (`applyFocus` updated: a
collapsed group dims like a leaf; expanded regions keep the deliberate never-dim).

**Gotchas (each cost a round):**
- **`--` inside an XML comment is ILLEGAL and breaks the whole SVG** — `loop.svg`'s comment said
  "the CSS `--loop` var" → Chrome's torn-image glyph. Both new icons now carry a no-double-hyphen
  note.
- **React Flow's base stylesheet styles `node-group` wrappers itself** (grey bg/border/padding) —
  invisible until our own group CSS stopped covering it. Neutralized in index.css; GroupNode owns
  the visual.
- **`group.members.length` is the WRONG count** for "what's in this box": direct children only
  (undercounts nesting) and counts IO ports/hosts a reader wouldn't. `memberCount` = recursive
  step count (excludes io/end/hosts), computed in buildFlow.
- **Card control-incidence must come from FLOW edges, post-re-anchoring** (a group is never a
  contract endpoint; an internal edge re-anchors to source==target and is dropped — it must not
  light a flare). Post-pass in buildFlow, after the edge loop.

**Loop U (the original goal, now trivial against the settled box):** `assignLoopRails` joined the
post-layout decoration chain (4th pass in portSides.ts) — TD: `railX` = box right + 36, LR:
`railY` = box top − 36; `LoopEdge` feeds the rail to `getSmoothStepPath` as `centerX`/`centerY`.
**The rail is load-bearing**: a self-loop's endpoints share an axis, so the default midpoint runs
the line straight back through the node. Stroke went 1.5 → full `--edge-stroke`. Label moved off
the smoothstep path-center (mid-rail — pokes past the rightmost node, fitView clips it) onto the
U's TOP RUN, and its pill bg became OPAQUE (translucent bg let the line strike through the text).
*(Label placement was superseded TWICE the same day — top run → bottom run → no floating label on
leaves at all; final policy in the "↻ loop-rule row" entry below.)*
**The U carries the app's ONE arrowhead** (user ask): an own `<polygon>` at the re-entry, CSS
`--loop` fill — RF marker objects take only literal colors, and a loop is the only edge whose
direction the layout doesn't imply. Old perpendicular-bulge bezier deleted — it cut straight
through any box taller than its fixed 80px bulge (every screenshot this session showed it).

**Parallel-agent note:** another agent worked the same tree this session (branch ordinals /
palette re-theme in index.css + portSides.ts); edits were re-read before writing and their
`assignBranchOrdinals` pass was left untouched — `assignLoopRails` chains after it in the hook.

**Residual polish (not blockers):** mid-chain loops share NODE_IN with the sequential trunk —
the arrow can sit near a top flare (check when a real case shows); deck + bottom flare on a
looped *batch* card untested (rare combo); expanded-region handles stay border-centered (the U
wraps the region fine).

### Shell batch groups never render — batch is a modifier, not a box (2026-06-10, user-caught) ✅ (uncommitted)

User caught two presentation bugs the redesign surfaced: a batched LEAF rendered as a "▸ 0 nodes"
BATCH card (an empty container — nothing to reveal), and a batched SUB-WORKFLOW required clicking
*through* a batch box to reach the sub-workflow. Their framing — *"it should be handled as a
subworkflow WITH batch, not a subworkflow inside a batch"* — matched the contract shapes exactly,
inspected before coding: a dynamic batch emits a batch group with **zero direct members** (empty
for a batched leaf — the leaf renders beside it; or holding only the workflow group for a batched
sub-workflow). **Rule: a memberless batch group is a decorator SHELL and never renders.** Literal
batches (real item-copy members) keep their container — there are actual items to reveal.
*(SUPERSEDED 2026-06-11 — the memberlessness discriminator was the CRITICAL review-fixes bug: a
literal batch group ALSO has zero direct node members (its items are child GROUPS), so this rule
swallowed literal batches whole. The surviving rule is literal-vs-dynamic + child groups, single
copy in `shellBatchIds` — see the review-fixes entry.)*

Implementation (flow.ts): `shellBatch` set + `effectiveParent` (reparents children past shells);
`groupsByHost` skips shells → `primaryGroupForHost`/`renderAnchor` land host edges, title, badges,
loop anchor, and the deck (`hostNode.batch` → `.batched` class on the collapsed card) on the
WORKFLOW group; `collapse.ts collapsibleGroupIds` excludes shells (untogglable, and they inflated
the N/M count — run-cycle went 0/2 → 0/1 open). The OLD H8 test pinned the old policy (edge lands
on the outermost = batch shell) — rewritten to the new one (shell absent, edge → workflow group,
title on it) + 2 new pins (batched-leaf shell never renders; collapse excludes shells). Verified in browser: batch-test (leaf with deck + ×N badge, no empty
box), run-cycle collapsed (magenta SUB-WORKFLOW card + deck, one click into the body) and expanded
(ONE region, batch badge in its header — no nested batch box).

### Branch labels: entry-anchored + spatial ordinals (2026-06-10, user-driven) ✅

TD fork pills moved from the mid-rail strip to the TARGET's entry (bare text + dark shadow halo —
iterated pill → backdrop-box → halo with the user; left edge at the node's left border `+4px`,
`labelAnchor`/`LABEL_NUDGE_X` in GradientEdge), prefixed with a condition-orange ordinal; error
labels stay mid-edge, unnumbered. **The surprise that shaped it: declared order does NOT survive
layout.** The leftmost-stays-straight policy keeps the trunk child centered under the source, so
siblings don't land in declared order — caught live on conditional-branching (process-large declared
first, laid out center). Numbering therefore had to be POST-LAYOUT (an `assignBranchOrdinals`
pass — deleted same day with the ordinals; the declared-order-doesn't-survive-layout lesson is
what remains load-bearing: it's why `orderForkSiblings` exists). **LR row numbering consciously deferred:** BranchPorts rows render in declared
order, which can disagree with the spatial numbers — two different numbers for one outcome across a
direction toggle is worse than none. *(The ordinals were removed the same day and the whole
machinery deleted — see the placement-settled entry below.)*

### Branch CONDITIONS on the edge (2026-06-10, planned + built) ✅

The user's ask: expanding a condition node should show WHY each branch fires ("if len(items) > 5",
"else"). The structural fact: unlike loops (declared `LoopSpec.condition`), branch conditions exist
ONLY inside the decision node's Python — so this is AST extraction, and the design rule is
**fail-closed: absent beats wrong** (comprehension UI must never mis-attribute a condition).

- **Phase 0 sweep first** (scratchpads/condition-labels/): all 66 example files + lyrics-generator →
  only **3 decision nodes exist in the whole corpus** (lyrics has none). The initial pattern set
  bailed on the harness's `check-groups`; two extensions made it 3/3 FULL: **adjacent-duplicate arms
  join with `or`** (`if commits == 0 or not gate_ok` — adjacency keeps elif-guard semantics exact;
  non-adjacent still bails) and **in-arm ternaries compose** (`elif is_last and cap == 0` /
  `cap != 0` via a compare-flip negation prettifier; an else-slot ternary just extends the chain).
- **Python:** `RFEdge.condition: str | None` (additive, default None) + `_branch_conditions` in
  react_flow.py (stdlib `ast` — fine: the purity guard restricts only graph-package imports).
  Memoized per decision node; keyed off the edge's ORIGINAL source so re-anchored branch edges keep
  their condition. Accounting check: every `next` assignment in the file must be structurally
  modeled or the whole node bails (the two-separate-ifs last-write-wins trap). A default before a
  chain WITH an else arm is dead code — omitted, not guessed. 3 new tests incl. a 9-case bail matrix.
- **Frontend:** display contract decided with the user — outcome label stays at the target entry,
  condition rides MID-PATH (smoothstep's labelX/Y), orange + halo, truncated 40 (full text on title
  + the read panel's new outcome→condition table, fed by GraphView from contract edges). Visibility
  baked at BUILD time into `EdgeData.condition` (advanced always; beautiful when
  `rowsVisible(e.source)` — expansion already re-runs the build, so no new mechanism).
- **Verified:** wire (curl: conditions on branch edges, None on error), browser all three states
  (beautiful hidden / focus=classify reveals + panel table / advanced always) + the harness's
  4-outcome check-groups. Goldens byte-identical; purity green.

### Container header parity across the fold (2026-06-10, user-driven) ✅ (uncommitted)

User requirement, three parts: (1) opening a sub-workflow/batch must change NOTHING in its
header — icon size/placement/border, name + description, all identical to the collapsed card and
positioned like a normal node's; (2) the count pill goes ABSOLUTE on the top-right border (both
states, so it doesn't move either); (3) the trunk flows INTO the expanded region's tile (flare
and all) like any node. Implementation: GroupNode renders ONE shared `.node-header` block for
both states (the mini-tile identity header is gone); `groupHeaderH` 44 → **68 == nodeHeaderH**
(ELK region padding derives from it); `.group-pill` absolute at top −9px / right 14px (opaque bg
masks the border under it); expanded TD handles moved to the icon column with the TOP flare
(bottom stays collapsed-only — the region's tile is at its top); the flare-incidence post-pass
now fills ALL groups, not just collapsed.

**Two gotchas found in-browser (each invisible to the suite):**
- **RF's base stylesheet sets `text-align: center` on `node-group` wrappers** — the region
  header text rendered centered while the card's was left-aligned. Added to the wrapper
  neutralizer (the same rule that kills RF's grey group chrome).
- **An ELK port on a COMPOUND node crashes elkjs under INCLUDE_CHILDREN when an edge references
  it** ("NEdge must have a source and target NNode") — same crash family as considerModelOrder.
  The in-process smoke test missed it (its group had no in-edge); run-cycle in the browser hit it
  immediately. Expanded groups therefore get NO ELK port (rendered handles still at the icon
  column; smoothstep absorbs the offset) — pinned by a new TD layout test with an edge into an
  expanded group.

Also fixed: the loop edge's `zIndex: 20` (a relic of the bezier arc that had to paint above the
boxes it crossed) lifted the U above the EdgeLabelRenderer layer and struck through its own label
pill — removed; the U wraps OUTSIDE its box so elevation serves nothing. The pill bg also went
opaque (`color-mix` over `--bg`). Verified in browser:
tournament expanded/collapsed are pixel-parallel (same tile/text/pill, arrow into the tile in
both), run-cycle's region takes the branch trunk into its tile with the `parallel batch ×N`
badge in the header.

### Branch label/condition placement settled + ordinals removed (2026-06-10, user-driven) ✅

Three rounds against screenshots: (1) **fork targets now lay out in the code's chain order**
(`orderForkSiblings`, layout.ts) — the first `if`'s target lands leftmost; the prior order came from
Steps declaration, which is irrelevant to a fork's reading order. (2) **Condition pills sit on a
LONE segment** (`conditionAnchor`): the path midpoint when the edge owns a real rail run (side
branches), the final descent (+5px user-tuned) for the straight child whose midpoint IS the shared
rail crossing — first cut put ALL pills on the descent, user caught that it wasted the side branch's
clean mid-run spot. (3) **Ordinal numbers removed** same-day after trying them — with code-order
layout they were redundant. The whole spatial-ordinal machinery went with them (deletion test:
`EdgeData.branchIndex`, the buildFlow seed, `assignBranchOrdinals` + 4 tests, `.edge-label-num`
CSS); the branch-pill marker is now just `kind === "branch" && label != null`. Condition pills are
standard `.edge-label` pills (white text, orange tint via `--label-c`).

### Session close — branch-label + condition-label batch (2026-06-10)

**One uncommitted batch again, interleaved with the second agent's parallel work** (their
loop-arc→orthogonal-U + collapsed-group-card arc — shared files: flow.ts, layout.ts, portSides.ts,
useWorkflowGraph.ts, index.css, web/CLAUDE.md); per-author split impractical (standing precedent).

**This agent's slice** = the three entries above (entry-anchored TD labels, code-order fork
layout, the branch-CONDITION feature end-to-end) + the same-day ordinal removal. Phase-0
evidence kept in-tree: `scratchpads/condition-labels/` (corpus sweep — only 3 decision nodes
exist; 3/3 extract FULL). *(Batch landed; gates were re-run on the merged tree.)*

**Open threads (not blockers):** TD branches going the SAME direction share collinear rails —
condition pills would sit on overlapping segments (no corpus case yet; revisit with the smart
router); `LONE_RUN_MIN=60` / `OUTCOME_CLEAR=26` are eyeballed knobs; extraction v1 skips `match`
statements (fail-closed, documented in react_flow.py); LR outcome labels stay on BranchPorts rows
(conditions there ride the read panel + mid-path pill when visible).

### The ↻ loop-rule row: the U lands on the rule (2026-06-10, user-designed) ✅ (uncommitted)

The user, looking at the harness's looped `review-round` leaf, asked the right semantic question:
*"what if we show an additional 'input param' — max_review_rounds — and end the loop with an arrow
into this input?"* Answer worked through together: semantically YES with one framing fix — the
loop config is authored NODE config (like params), so a row is honest, but it must present as a
**LOOP RULE** (amber ↻ row), not a data param (`max_review_rounds` parameterizes the loop
mechanism, not the node's inputs — a fake param row would lie against the file). Full design
(user approved via AskUserQuestion):

- **Leaf with rows visible** (advanced / focus-expanded): the card grows a `↻ while <cond> ≤ cap`
  row (leafSize +1; `LOOP_ROW` target handle, right side — the rail's side); the U's arrow lands
  ON it; the floating label DROPS (the row holds the rule — the same convention as data lines
  dropping `stdout → data` on row-landing).
- **Beautiful, unexpanded leaf:** a BARE U into NODE_IN, **no label at all** (the user's "hide
  this in beautiful" — the skeleton stays quiet; the loop reads as shape, click to see why).
- **Group anchors** (regions have no rows): floating pill in ADVANCED only, gated by
  `data.loop`'s presence (its only consumer is the LoopEdge label).

This also CLOSED the label-collision saga properly: an interim same-day bottom-run move (a
micro-step between the loop-U and header-parity entries, not separately logged) ends up mattering
for the group-advanced case only; leaves never float a label again. The earlier
strike-through the user kept seeing was their browser's stale-cache bundle (no `Cache-Control` —
the known gotcha), not a regression. Pinned by 4 new flow tests (row landing advanced/expanded,
bare-U beautiful, group label policy) + the legacy loop pin updated (data.loop is now the label
switch, never on leaf edges). Verified on execute-plan in
the browser: quiet bare U unfocused; focus-expanded card shows the amber rule row at the body's
end with the U's arrow landing on it; ReadPanel carries the full spec as before.

**Same-session refinements (user-driven):** (1) the rule SPLIT into two rows — condition (the
U's landing) + the cap `≤ ${max_…}` on its own row; one row truncated both operands into mush
(`${review-round.result.continu… ≤ ${max_r…`); leafSize counts 2 when a cap exists. (2) An amber
**↻ mark on the category line** (`CLAUDE CODE ↻`, `.loop-mark`) — a compact looped leaf said
nothing about looping (the U alone made the user ask "is this a loop?"); identity stays in kind
color, behavior in loop amber. Verified on execute-plan: both rows legible, arrow on the
condition row, mark visible at compact size. *(The category mark was retired with the chip rail
the same day — the border ↻ chip took the telegraph role.)*

### Task 169 spawned: agent↔browser point-and-watch channel (2026-06-10)

Reviewing execute-plan screenshots, the agent described where the floating Inputs node sits —
and the user couldn't find it ("I can't find it"): the live trigger for a day-old idea. The
agent can *see* the canvas (screenshot/inspect skill) but can't *point* in the user's window,
nor *watch* what the user clicks. → **Task 169** (`task_169/task-169.md`): SSE push channel +
CLI focus/frame commands broadcast to open windows + a user-event ring buffer — reusing the
`?focus=` mechanics wholesale, building the overlay's transport WITHOUT pinning Task 133's
event schema. Settled in the spec: delivery reports carry per-window visibility; open-if-absent
is an explicit flag; force-focusing an existing background tab is impossible by web platform
design (recorded so nobody tries).

### Condition pills edge-colored + the LR settlement: row conditions + back rails (2026-06-10, user-driven) ✅ (uncommitted)

Three changes from one review session, all `web/` — zero contract/Python change. Verified in the real browser (conditional-branching advanced crop; execute-plan
check-groups LR advanced + beautiful focus-expanded).

**1. Condition pills take their EDGE's color** (user accepted my observation against their n8n/Tines
references): GradientEdge's condition pill `--label-c` went `var(--decision)` → `to` — the target
node's color, the exact rule the outcome/error pills already follow ("the line's color where it
arrives"). Bare-text outcome labels stay as-is (user choice). One line + doc sync.

**2. LR conditions move ONTO the BranchPorts rows; mid-path pills die in LR.** The user's screenshot
(check-groups focus-expanded, LR) showed the two failure modes at once: a condition pill CLIPPED
under the node card (nodes paint above the EdgeLabelRenderer layer) and another floating in dead
space — root cause: `conditionAnchor` only has a real placement rule for TD; LR fell back to the
path midpoint, and two of check-groups' four outcomes route BACKWARD (loop-backs), so their wrapped
midpoints land anywhere. Settlement (the same convention as loop-rule rows and data labels dropping
on row-landing — the row is the condition's home): `LeafData.branchConditions` (label → condition,
populated only when the rows show it: advanced / focus-expanded), BranchPorts renders quiet muted
text beside each outcome pill (`.branch-cond`, CSS-ellipsized; pill `flex-shrink: 0` wins the row;
full text on title + read panel). The edge pill is suppressed for a labeled LR branch whose flow
source IS the decision node — a re-anchored branch (collapsed source, no rows) keeps it; TD keeps
pills everywhere. The old flow test pinned LR-advanced-pill-on-edge as desired — rewritten to the
new policy (the "interrogate what a green test asserts" lesson again).

**3. Backward branch/error edges get a BACK RAIL (`assignBackRails`, 4th post-layout pass).** The
knots beside the rows: `railCenter` only shapes FORWARD targets; a backward edge kept smoothstep's
stock wrap, U-turning at the default ~20px stub right at the source handle — four branch rows
emitting at nearly the same point curled into spaghetti. The pass (portSides.ts, the
assignLoopRails pattern) gives each backward branch/error edge a rail in the clear zone PAST both
endpoint boxes — LR below (the loop U owns above), TD left (the loop rail owns the right) —
staggered by the edge's existing lane; GradientEdge now prefers `data.railX/railY` over its
railCenter default (conditionally spread — an explicit `centerX: undefined` is not the same as
absent to smoothstep). **Sequential deliberately excluded** — the harness's backward cycle already
renders the clean orthogonal U; don't perturb what works. Third-party node avoidance remains the
deferred smart router. Verified: the group-tick loop-back now travels ONE clean dashed rail below
the whole node row (the n8n return-path look); knots gone.

### TD condition pills → the target's final approach (2026-06-10, user-driven) ✅ (uncommitted)

Follow-up: the user's TD screenshot showed condition pills "behind the edges" / colliding. Two
false leads dismissed BY MEASUREMENT (throwaway evaluate_script probes, since deleted — synthetic
clicks don't trigger RF selection, so a probe that needs the clicked state must dispatch the click
itself): (a) **no z-order bug exists** — `elementsFromPoint` at every pill center puts the label
div first, edges below; no edge svg carries a zIndex and `elevateEdgesOnSelect` is RF's default
false; (b) the "connected nodes not expanding" report was a false flag (user confirmed —
data-flow neighbors expand; the screenshot's neighbors were sub-workflow CARDS and a control-only
claude node, neither expandable by design). **The real finding: two sibling pills rendered at a
PIXEL-IDENTICAL rect** (597,706 — measured) — in TD every fork sibling shares the rail Y, so
same-direction siblings' path midpoints land in the same crossing zone; back-railed loop-backs'
midpoints sit on their wraps. conditional-branching "worked" only because its two anchors happened
to separate.

**Fix — ONE rule: a condition pill sits on the FINAL APPROACH into its target**, stacked above the
bare-text outcome label (`conditionAnchor` rewritten: descent-centering for ALL TD branches —
forward uses the fork rail, backward a fixed approach zone; LR re-anchored fallbacks anchor just
left of the target entry; rows hold all other LR conditions). Collision-free by construction (one
branch per target entry); the old "straight child only" descent gate + `LONE_RUN_MIN` deleted —
the side branch's "clean mid-run" preference didn't survive 4-outcome forks. T3 (condition rows on
TD cards) was considered and REJECTED with the user: TD forks fan from the icon column, so a row
would be a routing row no wire touches (the loop CAP row is annotation, but routing rows invite
edge-matching), and it would duplicate the target-entry outcome label. +2 pins (sibling-distinct-anchors, backward-approach; old midpoint pins rewritten); verified on check-groups TD: each pill stacks above its own target (`elif is_last and cap != 0` →
`review-round` → node).

**Residual (stated):** two branches re-anchoring to the SAME collapsed target would stack their
pills again (same entry, by construction) — no offset-by-index until a real case shows.

### Click a branch target → its condition reveals (2026-06-10, user-driven) ✅ (uncommitted)

Small follow-up the new anchor made natural: in beautiful, clicking a branch TARGET now reveals
the condition pill on ITS incoming branch edge ("why was I reached?") — just that one, not the
fork's siblings. Mechanism fits the existing focus-reveal pattern: `EdgeData.condition` is now
ALWAYS carried (was set-only-when-shown — nothing for a click to reveal), the old visibility rule
became the build-time `conditionShown` flag, and `applyFocus` sets a transient `conditionRevealed`
on branch edges whose target / `data.to` is the focus (identity-checked like `focusEnd`, so
unfocus restores object identity). GradientEdge renders on `conditionShown || conditionRevealed`.
With the final-approach anchor the revealed pill lands stacked above the clicked node's outcome
label — exactly where the eye is. Works in both directions (in LR the source's rows aren't visible
when only the target is clicked, so the edge pill is the only honest home). +1 reveal pin (build pins moved from condition-presence to `conditionShown`); verified in the browser (`focus=process-large`: pill above the clicked node, dimmed sibling bare).

### IO rows on the workflow node — the ports table dies (2026-06-10, user-driven) ✅ (uncommitted)

> Plan: `implementation/sub-plans/io-rows-plan.md` (locked design + deletions inventory). Spec deltas
> folded into `visualization-requirements.md`; the how into `web/CLAUDE.md` → "IO is ROWS…".
> Triggered by the execute-plan screenshot: a 14-row floating INPUTS table, visibly connected
> to nothing in beautiful. Frame that won: a leaf already renders its inputs as rows ON the
> node — a workflow's declared IO is the same kind of thing, so the separate table was a
> modeling inconsistency, not a styling problem. Design settled via shoot-lab mockups
> (`/tmp/io-rows-lab/`, v4 + 8px padding). Zero Python change (verified pre-plan by a
> contract-mapping searcher: names/levels/required/types/binding-edges all on the wire;
> output descriptions were already there on `purpose`, never surfaced — now a row tooltip).

**The shape:** one `PortRows` renderer, three locations. Root wrapper → standalone IO CARD
(type `"io"`, id = wrapper id so focus/deep-links/`expandTargets` survive; compact in
beautiful with a `"14 inputs"` pill — the motivating fix; rows under the leaf showBody rule).
Nested wrapper → rows on the workflow GROUP: collapsed card grows a two-column area (inputs
left; outputs right, staggered ONE row down ALWAYS — `ioRowsCount`, the in→out diagonal is
the information, user-decided incl. equal counts); expanded region renders inputs as the
LEFT SIDEBAR + outputs as a bottom-right strip with full-width dividers — the collapsed
diagonal stretched around the body. The sidebar is ELK LEFT PADDING (`groupPadding`,
layout.ts), so the body's first layer lays out BESIDE it with no per-node forcing — the
user's "first node next to the inputs" ask, generalized. Rejected: last-node-beside-outputs
(multiple endings, collides with branch fan-out, tiny win).

**Deleted (the simplicity payoff):** `PortsNode.tsx` + the `ports` node type + all `.ports*`
CSS + `portsHeaderH`; `assignFacingSides` + `HYSTERESIS` + the `iotr:`/`iol:` mirror handles
+ their 6 tests — the side-flip problem CEASED TO EXIST (rows on the boundary have
structural sides: receive left, feed right, the strict param/output convention) rather than
being solved. `io:`/`iot:` handle ids, `data.from`/`to` row-focus, and the ELK island rule
carried over untouched.

**Phase-0 experiments that de-risked it (all in /tmp, pre-implementation):**
- group↔own-child hierarchical edges (the new region-row shapes) survive elkjs under the
  REAL option set (INCLUDE_CHILDREN + NETWORK_SIMPLEX + forceNodeModelOrder + fixed leaf
  ports + straightness) — the crash family is option-dependent, so the minimal-option test
  alone wasn't evidence.
- **`elk.nodeSize.minimum` needs `nodeSize.constraints: MINIMUM_SIZE` AND is applied in
  ELK's internal coordinates — TRANSPOSED under direction DOWN** (asked (560,540), got
  540×560; RIGHT is unswapped). TD passes `(minH, minW)`. Measured, comment-pinned in
  layout.ts. Used to clamp a region whose inputs sidebar is taller than its body.

**Two correctness calls made during the build:**
- `PortRows` renders BOTH handles on every row, role-less side visually `quiet` (opacity 0)
  — an edge naming a missing handle is React Flow's silent-drop class; attachment must not
  depend on per-location reasoning (the synthetic invariant fixture immediately proved the
  point: it binds INTO a root input, impossible in real contracts but must still attach).
- With rows hidden (beautiful), parallel bindings between one pair DEDUPE to one node-level
  line — correct by construction, because any focus that could reveal them re-runs the build
  with the OWNER in the expansion set (`expandTargets` is owner-aware now), where each
  binding has its own row handle. The two focus tests were rewritten to mirror the real
  hook pipeline (build-with-expansion THEN applyFocus) instead of decorating an unexpanded
  build — the first drafts encoded the bypass and failed honestly.

**Verified:** new pins — nested-wrapper rows on group data + row
handles + per-owner visibility; root IO cards + description surfacing + expansion path;
owner-aware expandTargets; sidebar-padding layout test. Real browser:
execute-plan beautiful (quiet 13-inputs card heading the chain — the before/after of the
motivating screenshot), focus=g0 (card expands to 13 rows, lane-staggered teal lines fan to
consumers), run-cycle advanced (region sidebar + body beside it + bottom strip;
batched-sub-workflow collapsed card shows the two-column diagonal with binding lines on row
dots — the shell-batch reparenting composed with groupIO via `effectiveParent` untouched),
conditional-branching beautiful (zero-IO control: pixel-identical to before).

**Parallel-agent note:** built alongside the LR outcome-label agent in the same files
(flow.ts/CLAUDE.md); reconciled by adding the `EdgeData.outcome` declaration their in-flight
code referenced. Open follow-ups (not blockers): LR region strip placement reads fine but
only TD was deeply verified; ReadPanel for io-card clicks (port list) parked as an open knob.

### LR outcome labels at target entries + target-click reveal moves to the source row (2026-06-10, user-driven) ✅ (uncommitted)

Two LR fixes from the user's screenshots, closing the condition-presentation arc. All `web/`;
built in parallel with the IO-rows agent in the same files (their `outcome` reconciliation note
above is this work's field).

**1. LR targets get their outcome name whenever the source's rows show.** The rows say
`else → group-tick` but finding WHICH box group-tick is meant tracing the dashed line. Now a
labeled LR branch carries its outcome label under the same visibility as the row conditions
(`lrOutcomeLabel = rowsVisible(source)`, toFlowEdge) — rows + target labels appear together
(advanced / source focus-expanded), beautiful's skeleton stays quiet. The `labelAnchor` Left
arm moved ABOVE the line (right+bottom-aligned at the entry) — the old on-line position struck
the text with its own edge.

**2. The LR target-click reveal lands on the SOURCE's row, not an edge pill (user-caught: the
entry pill sat ON the clicked card —- targetY is the LR entry's vertical center).** applyFocus
is now the one place that knows WHERE a reveal lives: a labeled LR branch whose flow source is
a leaf → `LeafData.revealedConditions` on the source (merged over `branchConditions` in
WorkflowNode — the row is the condition's LR home in both the build-time and the revealed
case); TD, or an LR branch re-anchored onto a group (no rows) → the edge pill
(`conditionRevealed`, as before). `EdgeData.outcome` (always carried) keys the row. The
residual LR pill's `conditionAnchor` arm also moved above the entry (stacked over the outcome
label, mirroring TD's stack); conditionAnchor now returns `selfTranslate` like labelAnchor.

**Debug discipline note (cost an hour, worth recording):** the live verification on
execute-plan kept failing while the pure pipeline passed — a scratch vitest run of
buildFlow→applyFocus against the REAL `/api/graph` contract proved the logic correct, and a
DOM probe then showed the simplify card neither expanded nor focused: **execute-plan's
`?focus=` deep-link stopped applying to the canvas entirely** (it worked in this session's
11:15 screenshots; the read panel still opens, which masks it). Verified NOT this work:
`conditional-branching`'s deep-link reveals correctly through the same code. Likely the
parallel GraphView/useWorkflowGraph rework or an auto-collapse interaction — **flagged as an
open thread for the IO-rows agent's territory, not chased into their in-flight files.**

**Verified:** pins — LR-labels; the reveal test covers both arms (TD edge
pill, LR row + clearing restores); labelAnchor/conditionAnchor pins updated to the above-line
anchors. Real browser: execute-plan LR focus=check-groups (bare-text
`review-round` above its target's entry), conditional-branching LR focus=process-large (the
condition appears on the source's row beside the outcome pill; clicked card expands; DOM probe
confirms exactly one `.branch-cond`).

**Same-day follow-ups (user-caught, 2026-06-10):** (1) an open region's IO rows were gated on
the showBody rule, so in beautiful a sub-workflow's inputs/outputs were INVISIBLE unless some
focus incidentally expanded the owner — an open container hiding its interface reads as "has
none". Rule refined: an OPEN region always shows its rows, both densities; beautiful still
hides the LINES (skeleton rule untouched, no new toggle needed — `ioRowsShown` is now the
single render-truth set edge resolution reads, so row handles exist exactly where rows do).
Collapsed cards keep the showBody rule. (2) the expanded root IO card was missing the card
shell entirely — its class list said `node expanded` but the shell (radius/bg/border) lives
on `.node.compact/.detailed`, and `.node.expanded` stacked a second divider on the
`.io-rows` one. Fix: the io card is ALWAYS `compact`. (3) clicking an open io card now
TOGGLES it closed (GraphView treats `type:"io"` like a container — focus IS its open state).
Verified in browser (run-cycle beautiful: sidebar + strip visible, no lines;
execute-plan focus=g0: rounded shell, single divider).

**Strip-row hug + the "wrong handle" non-bug (user-raised, 2026-06-10):** the outputs strip's
full-width right-aligned rows left the LEFT (receive) dot floating mid-strip, far from its
label — a producer line looked like it landed on nothing / "the wrong one". CSS fix: strip
rows are `fit-content` (right-aligned column), so the receive dot sits directly beside the
text. The semantic question it raised was verified against the SOURCE FILES, not the render:
`execute-plan` outputs pr_url/summary/segments; `run-from-plan` consumes `${execute-plan.pr_url}`
+ `${execute-plan.summary}` but nothing reads `segments` — so "line in, bare feed dot out" on
the segments row is the truth (an unconsumed output), not a rendering bug.

**Harness doc note (2026-06-10):** annotated `execute-plan.pflow.md` → `### segments` as
deliberately unconsumed (diagnostic surface; `run-from-plan` reads only pr_url + summary) —
the viewer surfaced it, the user asked for the note. IR-safe (description prose); re-validated
through `/api/graph` (64 nodes, unchanged).

### `?focus=` deep-link freeze: investigated to the worker boundary — HANDED OFF (2026-06-10)

The deep-link regression flagged earlier was bisected layer by layer (focus state ✓ set; build/
applyFocus/expandTargets ✓ correct on the real contract in node; ELK input ✓ lays out on main
thread AND in a standalone raw worker, even as the exact 3-call sequence): **the app's ELK
worker goes silent on the focus-expansion layout** — message sent, no reply, no error event —
and elk-api has no `worker.onerror`, so the promise (and the canvas) hang forever. Real clicks
work everywhere; only the deep-link path on execute-plan freezes (worked at 11:15 — a same-day
regression). Remaining delta: the Vite-bundled worker chunk vs the raw artifact, transport
timing, or a send-side elk-api issue. **Full findings, repro kit, next 3 experiments, the
left-in-place `[dbg]` instrumentation (strip before commit!), and a ship-regardless watchdog
workaround: `implementation/sub-plans/handoff-focus-deeplink-worker-hang.md`.**

### Root IO cards join the control skeleton (2026-06-10, user-driven) ✅ (uncommitted)

User showed run-from-plan TD: the Inputs/Outputs cards floated beside the spine, flare-less and
visibly connected to nothing (their only edges are data-flow, hidden in beautiful). Ask: *"inputs
should behave just like nodes — the 'shapes' [connector flares] going out from inputs and an edge
into the first node; same for outputs but reversed."* All `web/`; zero contract/Python change.

- **Synthesized `io-flow:` control edges (flow.ts):** Inputs card → each root ENTRY step (no
  incoming control edge; **falls back to the FIRST root step on a root cycle** — semantically
  honest, pflow starts execution at the first step) and each root `is_terminal` step's
  representative (via `renderAnchor` — a terminal sub-workflow host anchors on its GROUP card/
  region) → Outputs card. *(The `is_terminal` filter was itself the floating-Outputs bug —
  replaced by control-sink derivation 2026-06-11, see the closing entry.)*
  `kind: "sequential"` / `type: "gradient"` so every downstream policy
  (incidence, gradient, focus dim, lanes-exempt) treats them as the control trunk they visually
  are; colors blend IO teal ↔ the step's `nodeColor`. Drawn in BOTH densities (structure, like
  forks). NOT contract edges — visual policy only; the per-port data lines are untouched.
- **Incidence unified into ONE post-pass.** Leaf `hasIncoming`/`hasOutgoing` came from
  contract-edge sets at construction while groups used the flow-edge post-pass; the synthesized
  edges only exist at flow level, so the post-pass now fills ALL flare-bearing types (node/group/
  io) and construction sets `false`. The contract-level sets remain solely for entry detection.
- **IO cards got the full leaf flare anatomy** (IOCardNode): TD icon-column handles (same
  geometry as WorkflowNode), per-side `Connector` flares, expanded card drops the BOTTOM flare
  (the leaf rule); joined layout.ts's TD `portable` ELK-port set so the trunk runs dead straight
  through the io tiles.
- **Bug caught by the new test, worth the lesson:** the gradient direction was keyed off
  `from === source` — true for BOTH the in-edge (from=card=source) and the out-edge
  (from=step=source), so the Outputs blend ran backwards. Made the direction an explicit
  `end: "in" | "out"` param. An implicit discriminator that happens to correlate is not a
  discriminator.

+4 pins (skeleton edges both densities + incidence flags; terminal-host anchors on
group; cycle fallback; zero-IO unchanged). Verified in the real browser
on run-from-plan: TD beautiful (cards head/tail the spine, teal flare out of INPUTS into
resolve-repo's top flare, magenta→teal into OUTPUTS), LR (clean horizontal pipeline), TD advanced
(skeleton edge lands on the icon column among the data lines). *(Parallel-agent note: built alongside
the focus-deeplink worker-hang investigation — their `[dbg]` instrumentation in layout.ts
createElk was left untouched; my layout.ts edit is the `portable` set only.)*

**Collapsed-card outputs BOTTOM-ANCHORED (2026-06-10, user-caught) ✅ (uncommitted).** The
execute-plan card (13 inputs / 3 outputs) showed the outputs hugging the TOP-right — the
"staggered ONE row down" rule was designed against balanced counts, where one-row-down IS the
bottom. Fix is a strict generalization, not a re-litigation: `PortRows.stagger` (boolean class)
→ `staggerRows` (a count, inline `margin-top: calc(n × var(--row-h))`), with GroupNode passing
`ioRowsCount − nOut` — pixel-identical wherever `nOut + 1 ≥ nIn` (every balanced case, incl.
equals), and the card's bottom-right corner when inputs dominate. `ioRowsCount`/ELK sizing
unchanged → zero layout drift; the `.io-col.stagger` CSS rule deleted. Matches the expanded
region's design (outputs strip at the bottom-right — "the collapsed diagonal stretched around
the body"). Verified via zoomed crop on run-from-plan
(collapse=all, advanced TD): outputs end at the last row, lines exit at the corner toward the
OUTPUTS card.

### Focus-deep-link worker hang: CLOSED — defended, root cause environmental (2026-06-10) ✅ (uncommitted)

Continued `sub-plans/handoff-focus-deeplink-worker-hang.md` (full verdict written into its status header —
not restated here). The short of it: completed the evidence matrix the handoff left open — the
**Vite-built worker chunk is innocent** (driven headlessly in plain node against the captured
message sequence: terminates fine; the esbuild re-minify + `"use strict"` wrap changes nothing),
the live root is **capture-faithful** (zero non-finite values — killed the NaN-laundering theory),
the message **is posted** (send-side wrap), and `messageerror` (the never-checked event) stays
silent. Then the decisive non-result: **the hang stopped reproducing everywhere** — 13+ trials,
including the exact commit (`a13d93ac`) rebuilt in an isolated worktree, with and without CPU
load. Every historical sighting lived in the day-old, focus-stolen, tab-accumulating MCP Chrome;
after its restart, nothing reproduces. Conclusion: environmental (that Chrome instance), not a
code path — the user's "the screenshot window steals focus while I type" observation is the
plausible mechanism class (occluded/backgrounded long-lived instance), unproven.

**Shipped instead of a ghost-hunt:**
- **`layoutWithWatchdog` (`layout.ts`)** — the handoff's recommended defense: 10s of worker
  silence → `console.warn` fingerprint, re-run on the bundled main-thread ELK, terminate the
  silent worker, DEMOTE the session to main-thread layouts (bounded badness: one stall max,
  never a dead canvas; a blocked main thread can't falsely trip the timer — its result settles
  the race before the timer callback runs). 3 new pins in `layout.test.ts` (pass-through /
  rejection propagates / silent-engine rescue + terminate). The bundled build moved to a shared
  memoized `loadBundledElk` (fallback + rescue, one loader).
- **`Cache-Control: no-cache` on index.html** (`_BundleFiles(StaticFiles)` in `ui/server.py`) —
  the stale-bundle trap that repeatedly polluted this feature's debugging (and observations in
  this very investigation). Hashed assets stay heuristically cacheable; only the HTML entry must
  revalidate. Pinned in `test_ui.py`.
- **chrome-devtools MCP → `--headless=true`** (`~/.pflow/mcp-servers.json`): kills the
  focus-stealing annoyance AND removes the occlusion-interference class from future sessions;
  verified the screenshot/inspect tooling works headless (focus deep-link applies, 12 dimmed).
- **All `[dbg]` instrumentation stripped** (layout.ts, useWorkflowGraph.ts) per the handoff's
  cleanup note; repro worktree removed.

Deep-link verified live on the final cleaned build (execute-plan, LR/beautiful,
focus=simplify → expanded card + 12 dimmed). *(Parallel-agent note: built alongside the io-flow
skeleton agent in layout.ts/web-CLAUDE.md — their `portable` io-card change untouched.)*

### Headless MCP Chrome made the STANDING default — verified identical for the agent (2026-06-10, user-decided) ✅

Follow-up to the hang closure above, after the user confirmed the direction: the screenshot/
inspect Chrome window was pure annoyance ("usually just a flicker for a couple of seconds" that
steals focus mid-typing) — so **headless is now the standing default, headed is an explicit
opt-in** (only when the user asks to watch; flag flipped back after). The user's one condition —
*"make sure it works identical for you as AI agent"* — was verified on both axes the tooling has,
not assumed:

- **Paint** (`screenshot.pflow.md`, conditional-branching TD/beautiful): gradient edges, the
  CONDITION card + fork icon, connector flares, dashed branch edges + labels, error pill, dotted
  end edge, themed minimap — all render pixel-faithful to the headed known-goods (PNG read).
- **Measure** (`inspect.pflow.md`, `node=classify`): geometry lands at the documented metrics
  exactly — compact leaf 230×68 CSS px, tile 56×56, both TD connector stubs measured, `node=`
  camera framing works, **all 7 edges carry pathRects** (the thing jsdom can't see — the loop's
  reason to exist). Headless output is authoritative.

Made durable in `SKILL.md` (the manual every agent reads before driving the browser): a
"Headless by default" section records the default + the verification + the exact opt-in/revert
steps (remove `--headless=true` from `~/.pflow/mcp-servers.json`, pkill the profile, re-add when
done — never leave headed on); the stale-cache troubleshooting note updated for the new
`Cache-Control: no-cache` index.html header (only hashed `assets/*` may still need a `&v=` bust).
Side benefit restated: no occluded agent-browser windows = the suspected environmental condition
for the worker hang can no longer form.

### Container SELECT vs corner-button TOGGLE — design D shipped (2026-06-10, user-driven) ✅ (uncommitted)

> Plan (locked design, facts, decisions, rejected alternatives):
> `implementation/sub-plans/container-select-plan.md`. Design chosen via THREE shoot-lab mockup rounds
> (`/tmp/expand-btn-lab/`): V2 corner button (over border-button/split-pill/pill-as-button) ·
> A1 arrows-out/in glyphs (over unfold/chevron/plus) · R1 full-button-at-rest (over quiet/
> tinted/hover-only — user picked after the labs were opened IN their browser, a worthwhile
> step the AskUserQuestion flow alone didn't give). All `web/`; zero contract/Python change.

The seam: a container click carried two intents (select vs open) and only open existed —
containers could never be focused (their bindings were permanently invisible in beautiful),
never reached the read panel, and the card that LOOKS like a node was the only card that
didn't select. Now: **body = SELECT** (focus + read panel via the group's HOST node — purpose/
bindings/loop/batch/source all live there), **corner `.group-toggle` button + double-click =
TOGGLE** (`zoomOnDoubleClick` off; the button's stopPropagation is load-bearing and pinned).

- **`applyFocus` UNIT semantics:** focus on a group id selects the whole unit — descendants
  (flow `parentId` BFS) + every edge touching any of them; internal wiring and boundary
  bindings light, the rest dims, the unit's hidden data lines reveal. Leaf/port focus
  degrades to unit={focus} — the existing focus pins passed UNTOUCHED (the regression
  proof). `edgeTouchesFocus` deleted (absorbed by `touches`). Group focus does NO neighbor
  expansion (`expandTargets` already returns ∅ for group ids) → pure restyle, no ELK.
- **The toggle channel** rides the existing `InteractionContext` (`toggleGroup` beside
  `focusPort`) — node `data` stays callback-free. GroupNode renders the button in BOTH
  states; batched LEAVES get nothing by construction (user-caught during planning: batch
  is a modifier — only GroupNode-rendered containers are openable).
- **Deep links select containers BY NAME:** `resolveNodeFlatId` resolves a group-host's
  node_id to its representative group (skipping memberless batch shells) — previously
  `focus=execute-plan` resolved to null (the host node is never rendered). Task 169 needs
  exactly this verb.
- **Muscle-memory note:** "click card to open" is GONE (the one behavior change users feel);
  the always-visible button + dblclick cover it.

+10 pins (applyFocus unit ×3, viewParams host-resolution ×3, GraphView
click-semantics jsdom ×1 — body selects + button toggles + stays-collapsed-on-select; the
isolated-GroupNode test was correctly skipped per plan since Handle requires node context).
Verified in the real browser on run-from-plan:
`focus=execute-plan` deep-link selects the collapsed card (kind ring, corner button rendered,
read panel with the host's bindings dict, revealed teal binding lines incl. the labeled
pr_url line, unrelated nodes dimmed) and with `collapse=none` selects the expanded region
(interior full-strength — every outside node in this workflow is genuinely connected to the
unit, verified against the bindings, so nothing dims: correct, not a bug).

**Same-day follow-ups (user-caught, 2026-06-10): container select expands its IO rows; IO
labels die.** Two screenshots, one root cause. (1) Selecting a sub-workflow in beautiful
revealed its bindings NODE-level: 13 input bindings deduped into ONE line whose surviving
label single-named the first port ("base_branch" standing in for 13 inputs — actively
misleading, not just noisy). The user's frame: selection should expand the card "with just
inputs and outputs". Fix: `expandTargets` treats a workflow/batch group focus as ALL of its
IO ports (child wrappers' members) — the port's OWNER is the group, so the card grows its
two-column IO area (the existing `ioRowsVisible: expandedSet.has(g.id)` seam — zero new
mechanism) and each binding's far end expands too; every line lands row-to-row, dedupe
disappears (distinct row handles). Group select in beautiful now re-layouts exactly like
leaf focus-expansion (cached/animated/anchored) — the plan's "pure restyle v1" was
superseded the same day by the user's better call. (2) The floating pills on IO bindings
(`base_branch`, `plan_path`, …) duplicated what the named rows already say — IO-touching
data lines now carry NO label ever (`ioBinding` in the edge loop → toFlowEdge); leaf-to-leaf
lines keep `stdout → data`. +2 pins (container expandTargets incl. far ends;
io-label suppression with a leaf-to-leaf keep); verified in browser
(focus=execute-plan: 13 named rows, row-landed lines, bottom-anchored outputs composing,
zero pills).

### LR row PORTS: binding bundles run straight (2026-06-10, user-driven) ✅ (uncommitted)

User: *"why are ALL lines not straight here?"* (the focus-expanded run-from-plan bundle, LR).
**Measured, not theorized** (inspect): the two cards' row grids sat at a constant **+52px
offset** (inputs rows y=141,167,193…; sub-workflow rows y=193,219,245…) — ELK aligns BOXES,
and LR declared no ports, so it couldn't know rows exist; any ΔY then renders as the
rounded-orthogonal Z-jog, and lanes deliberately stagger the 13 jogs apart.

Fix (the TD icon-column principle extended to LR rows):
- **`flow.ts rowAnchorsFor(node)`** — pure, owns each row handle's (side, y) inside its box,
  mirroring the components' render order exactly: leaf body = params → outputs → loop rows,
  BranchPorts below; io card / collapsed group card = `.io-rows` chrome + column label +
  rows, outputs BOTTOM-ANCHORED (the stagger). New `METRICS.ioRowsChrome: 11` (= the
  `.io-rows` margin-top 4 + border 1 + padding-top 6 — documented coupling, the rule can't
  read one CSS var). Expanded regions return none (compound-port crash).
- **`layout.ts`**: in LR, row-bearing nodes declare FIXED_POS ports from the anchors; edge
  endpoints whose handle matches a declared port connect port-to-port.
- **THE non-obvious bit (the test caught it):** ports alone changed nothing — ELK still
  aligned boxes, leaving exactly the 11px chrome delta in the synthetic fixture. Ports make
  alignment POSSIBLE; a **straightness priority** makes NETWORK_SIMPLEX pay for it.
  Row-to-row edges get priority **5** (below the control trunk's 10 — the spine wins when
  they compete). With it: alignment ≤1px, pinned by a real-ELK test.

**Verified in the real browser** (inspect): both cards' rows now at IDENTICAL y's
(193,219,245,…) — the 52px offset is gone; screenshot shows the 13-line bundle dead flat,
each line leaving its row dot and running straight into its named row. +3 pins (rowAnchorsFor leaf ordering incl. loop-row offsets; io-card chrome + bottom-anchored
group outputs + region-none; the real-ELK ≤1px alignment pin). Honest
residual: rows can only align where orderings/pitches allow — a row feeding two places, or
differing row orders, still jogs (correct geometry); the LR merge ~8px node-level residual
is untouched (different anchor class).

### `is_decision` end-route fix: continue-or-stop gates become CONDITION nodes (2026-06-10, user-driven) ✅

> Born from the TRANSFORM pseudo-kind feasibility discussion (the user's check-validate
> screenshot): the Phase-0 corpus sweep (scratchpads/transform-role/) found **4 of the 6 real
> deciders in the corpus had `is_decision=False`** — `gate`, `check-commits`, `check-final`,
> `check-validate` — because their stop arms (`next: "end"`) become END edges, never BRANCH,
> and the model required ≥2 BRANCH labels. The user's screenshot node was literally rendering
> as plain CODE. An existing test had PINNED the gap as desired behavior
> (`…without_changing_decision_or_terminal` asserted `not is_decision(check)`) — the
> "interrogate what a green test asserts" lesson, again.

- **Model (`model.py is_decision`):** a decision = ≥2 distinct OUTCOMES = branch labels ∪
  {end if an END out-edge exists}. Zero branch labels (static `- next: end`, or every arm →
  end) stays a non-decision, so `is_decision ⟹ kind == code` holds by construction. Pinned
  by an outcome-matrix test + the rewritten routes-to-end test.
- **Mermaid impact, judged not regressed:** a full 56-example corpus render diff (before/after,
  scratchpads/transform-role/mermaid_corpus.py) shows EXACTLY the 4 nodes (×their parent
  expansions, 6 files) flipping rect→decision diamond — the semantic intent. Goldens
  byte-identical (none contain these workflows); no end-sink second-order changes fired.
- **Contract (`react_flow.py`):** a decision's END edge now carries the extracted condition
  for the reserved outcome `"end"` (`_branch_condition` accepts EdgeKind.END gated on
  `is_decision` — a static end route stays condition-free). And `_render_conditions` no
  longer BAILS on duplicate-outcome-in-non-adjacent-arms (check-validate's exact shape:
  `end` at arms 0 and 2): it LISTS the selecting arms verbatim, `"if ok · else"` — each
  fragment is the file's own text, so it can't mis-attribute, only abbreviate (user approved
  relaxing the bail; the or-join stays reserved for adjacent plain arms where it's exact).
  Two bail-matrix cases became render cases.
- **Frontend:** buildFlow appends `"end"` LAST to a decision's `branchLabels` (forward
  outcomes first, stop last — a separate pass so contract edge order can't reorder it);
  BranchPorts renders it as a FAINT row (`.branch-port-end` — a real outcome that stops the
  flow, styled like the end edge/dot it feeds); the LR end edge leaves `branchHandle("end")`
  (mirrors the row's render condition — the silent-drop rule); the END edge's condition
  follows the existing pill/row split (TD: pill on the final approach into the end dot; LR:
  the row; beautiful: quiet until focus-expanded) and the target-click reveal now covers the
  end dot ("why did flow stop here?"). ReadPanel's outcome table includes the END edge as
  `→ end` (GraphView filter + label fallback).
- **Verified:** real browser on validate-fix — TD shows the CONDITION card (orange fork icon)
  with the `if ok · else` pill above the end dot; LR shows both fork rows
  (`elif round < cap → fix-tests`, `if ok · else → end` faint) with each line leaving its own
  row handle. *Gotcha re-confirmed: the already-running `pflow ui` server serves OLD Python —
  restart it after a model/renderer change (the bundle rebuild is not enough).* +5 pins.
- **Spawned, not yet built:** the TRANSFORM pseudo-kind itself (sweep verdict: 10/20 unique
  corpus code nodes are pure transforms, 0 false positives with exception-constructors
  whitelisted; 6/10 have literal result dicts for a future Level-2 output-shape extraction).

### LR icon-row SPINE: the trunk passes straight THROUGH the nodes (2026-06-10, user-driven) ✅ (uncommitted)

User, after the row-port fix: *"what about the actual nodes, why are they not in a straight
line? Maybe it's related to that we are not connecting the solid edges into the 'image' like
TD?"* — exactly right, plus their follow-up: the output edge must leave the OTHER side at the
SAME height. LR control handles were side-CENTERED, so ELK aligned centers of wildly
different-height cards and the spine wandered. The fix is the TD icon-column principle rotated:

- **`ICON_ROW_Y`** (metrics, = header center 34): every LR control handle — leaf, io card,
  group card AND region — sits at the icon row, in on the left / out on the right; layout.ts
  declares matching FIXED ports (regions stay port-less, smoothstep absorbs). The `portable`
  set now spans BOTH directions with direction-appropriate port pairs, merged with row ports
  into one list per node.
- **LR LEFT tile flare** (`CONNECTOR_LEFT` — the TOP path transposed, arc sweeps flipped by
  the reflection): the incoming edge flows into the tile's left border, gap-free by the same
  construction rules. NO right flare — the tile sits at the card's LEFT; the outgoing edge
  leaves the card's right border plain at the icon row (geometry, not an omission).
- **Priorities are WEIGHTS, not constraints — the measured surprise:** with trunk 10 vs
  13 bindings × 5, the BUNDLE won and preflight sat 233px off the spine. Trunk → **100**
  (above any plausible bundle); bindings stay 5.
- **GRID PARITY** makes both wishes compatible where it matters: the io card's rows now carry
  an INPUTS/OUTPUTS column caption (matching a group card's columns — one shared grid:
  header + chrome + label + rows), so when the spine aligns two card headers their bindings
  align row-to-row SIMULTANEOUSLY. Leaf↔card bindings have no parity guarantee and may keep
  small jogs — honest geometry, stated not hidden.

**Verified in the real browser** (inspect, focus-expanded run-from-plan LR): ALL five spine
tiles at y=98 — including the previously-stray preflight and outputs card — AND the g0↔g1
binding rows identical (199,225,251,…): spine straight + bundle straight at once. Zoomed
crops: the left flares are seamless (cove into each tile, gradient through). +1 spine pin for different-height leaves; the card↔card alignment pin rewritten to
the parity guarantee + a header-alignment assert.

**Exit-gap fix (user-caught, same session): no new shape needed — tuck the terminus.** The LR
OUT edge started ~2px OUTSIDE the card border (RF anchors a right-side handle at its own
right edge, past the border), and a bright 3px line stopping beside the dim 1.5px card border
read as unplugged. Measured (handle rect 655–659 vs border 657; path start 659), then fixed
with the flare side's own trick: `right: 5` on the LR NODE_OUT handle tucks the terminus 5px
UNDER the card — edges render behind nodes, so the line emerges through the border, seamless
by construction (the same reason `left: 5` already made flare-less LEFT entries clean). All
three card components; rejected adding a visible dot/shape — the "clean lines into borders"
language stays. Verified by zoomed crop: line flush with the border on exit, into the flare
on entry.

### TRANSFORM pseudo-kind shipped (2026-06-10, user-driven) ✅

> The second presented role, following CONDITION's exact playbook (Phase-0 sweep →
> fail-closed AST classifier → additive contract fact → format.ts seam → shoot-lab pick).
> Sweep evidence: scratchpads/transform-role/ (10/20 unique corpus code nodes are pure
> transforms; 6 hybrids excluded by definition; 4 genuinely effectful).

- **Python (react_flow.py):** `RFNode.is_transform: bool` + module-level `_is_transform_code`
  — a fail-closed purity walk: whitelisted modules/builtins, author-bound names allowed,
  forbidden-name check on ANY `ast.Name` reference (closes the `o = open; o(...)` aliasing
  hole the sweep prototype had), forbidden statement shapes (with/async/global/del), must
  assign `result`, must NOT assign `next` (a pure decider is CONDITION's — the two roles are
  mutually exclusive by construction, no frontend precedence logic needed).
- **The corpus regression that tuned the whitelist:** banning `object`/`type` as names cost
  two REAL transforms — `impl: object` is the code-node input ANNOTATION convention, not a
  builtin reference. Forbidden set = genuinely effectful/dynamic names only. Production
  classifier verified at exact sweep parity (10/10) through the full server path.
- **Frontend:** `TRANSFORM_COLOR #5fd4dd` cyan + the shuffle glyph (`transform.svg`, crossing
  flows cyan→white, condition.svg's gradient language) — both user-picked via a shoot-lab
  (`/tmp/transform-icon-lab/`; morph + funnel rejected, lime + amber rejected for shell-green
  collision / no separation). Seam extensions only: `isTransform` + `nodeColor`/`categoryLabel`
  arms (a `RoleFacts` structural type), `iconFor` arm, ReadPanel `code · transform`. Edge
  gradients pick the cyan up automatically through the nodeColor seam (test-pinned).
- **Tines sub-modes considered + deferred (user question, answered with the mapping):**
  extract/dedupe/message-only are flavors our one TRANSFORM covers (the `purpose` line
  names the specifics; intent-inference from arbitrary Python breaks fail-closed);
  explode/implode = pflow batch; "automatic" = the llm kind; delay/throttle = no pflow
  analog. Recorded in visualization-requirements.md. Next refinement when wanted:
  Level-2 result-shape extraction (6/10 corpus transforms have literal result dicts).
- **Verified:** real browser on deep-research TD/beautiful — all five transforms (prepare/
  normalize/compile/combine/final-report) wear the cyan shuffle identity, edges blend to
  cyan, clearly apart from magenta/violet/teal neighbors. +5 web pins (incl. the
  defensive CONDITION-wins and kind-gate cases) + a Python renderer matrix (+2 tests, 14 cases).

**Finalization (same session):** ruff C901 forced the classifier into small per-concern
helpers (`_assigned_names` / `_bound_names` / `_transform_disqualifies` — a net readability
win, not just a lint appeasement). One genuine tooling gotcha cost two rounds: **ruff
SIM114 auto-MERGES adjacent `elif` branches with identical bodies, and the merged form
fails mypy** (`FunctionDef|ClassDef` or-ed with `ExceptHandler and n.name` widens `n.name`
to `str | None`) — a fixer-vs-checker fight where `make check` can never converge. Fix:
make the bodies structurally different (`bound.update({n.name} if n.name else ())`),
comment pinned in react_flow.py. Both arcs of this session — the
`is_decision` end-route fix and the TRANSFORM pseudo-kind — are complete, browser-verified,
and uncommitted on the branch alongside the parallel agent's LR row-ports work.

**LR exit DOT (user-driven, same session): the user was right — a shape DOES look better.**
After the tuck fix I'd argued "no new element"; the user pushed back, so a shoot-lab settled
it (5 candidates on the real card anatomy, opened in their browser): **E1 solid dot** won —
a kind-colored 10px dot straddling the right border at the icon row, the n8n output-port
convention — over hollow ring (new visual vocabulary), nub, baseline, and a mini border
flare (structurally weak: the cove language needs the 3px tile border to sink into; the card
border is 1.5px subtle). Pure decoration on all three card components; the invisible tucked
handle stays the real connection point. **The correctness subtlety:** `hasOutgoing` became
HANDLE-aware (incidence counts only edges leaving NODE_OUT) — an LR decision's outcomes
leave their BranchPorts rows (which have their own dots), so a pure decider must not light
an icon-row exit; in TD forks fan from NODE_OUT, so nothing changes there (pinned). Verified by zoomed crop (yellow dots on the code
cards' exits, line into the next tile's flare).

### TRANSFORM Level 2 planned + plan-reviewed — ready for a fresh implementer (2026-06-10)

Design settled with the user against an iterated mock (now persisted:
`implementation/transform-l2-mock/`): result-shape rows with `name: type` format
(the authored annotation syntax), wholesale-read vs wrapper-collapsed row policies,
quiet-dot unread keys, the no-line-without-a-read invariant, one-level depth, and
Half B's observed-usage generalization to all kinds. Tines' transform sub-modes were
mapped and consciously deferred (recorded in visualization-requirements.md).

**Plan:** `implementation/sub-plans/transform-l2-plan.md` — hardened for handoff (a fresh agent,
no conversation context): 9 locked decisions, 12 verified facts with symbol anchors,
atomic steps with done-whens, anti-goals, per-phase gates. The two load-bearing
technical calls, both code-verified: the sub-path dies at the ref REGEX (scope.py:12,
one-segment capture) so retention starts there with a new `refs_with_path_in` (the
`(root, field)` shape of `refs_in` is frozen — three callers); and `Edge.output_path`
must be `compare=False` or dedup changes and Mermaid breaks (the input_name
multi-role-lossiness precedent).

**`review-plan` pass (0 critical / 7 major / 6 minor — all folded in).** The catches
that mattered: F3 claimed two DATA_FLOW emission sites — there are THREE (the
input→consumer site stays on `refs_in`); `_resolve_ref` has a fourth return case
(bare ref + single declared output); the batch-alias exclusion must be an EXPLICIT
guard (a per-item key colliding with the batch source's output_field name makes the
equality rule coincidentally attach a wrong path); the row set must be authored ∪
OBSERVED (an observed-only key otherwise loses its line to NODE_OUT — the exact read
the feature exists for); "exactly one result assignment" needed pinned semantics
(subscript mutations count; empty dict → keys=None; valueless `result:` AnnAssign is
an input declaration); web-tree type-greenness required at the END of each phase
(fixture factories); and a `/code-review` step joined Phase 4.

Phases 1–2 are Python-only and start anytime; Phase 3 carries a HARD entry gate
(`git status web/src/` clean — the parallel agent's LR row-ports work shares its files).

### Batch/loop CHIP RAIL: the batch pill dies, the corner chrome unifies (2026-06-10, user-driven) ✅ (uncommitted)

> Design locked via a 3-round shoot-lab (`/tmp/batch-chip-lab/`), Tines corner-chips as the
> user's reference. Plan + the per-round picks: `implementation/sub-plans/batch-chip-rail-plan.md`.
> Round 1: **A3** (tinted capsule, icon + count) · **B3** (dynamic shows `×N`; I flagged the
> fake-number concern, user overrode — source rides the tooltip) · **C2** (loop chip, same
> vocabulary). Round 2 (user idea): EVERYTHING moves to the top border as one rail; the
> `▸ N nodes` count pill restyles to the chip language. Round 3 (user idea): the count moves
> INSIDE the expander — `[25 ⤢]`, "nodes" + chevron die; **F1-square** final (rounded-square
> 7px: round = info chip, square = button).

The trigger: the header `parallel batch ×N` pill squeezed the 2-line description to
uselessness ("Genera… a pe…") while DUPLICATING the deck — violating Badges.tsx's own
"a badge earns its place only when nothing else shows the fact" rule.

- **New `ChipRail.tsx`:** loop chip (amber round ↻; tooltip = polarity + condition + cap) +
  batch chip (purple capsule, stack glyph, `×{count}` literal / `×N` dynamic; tooltip =
  parallel|sequential + `over ${source_ref}`). Straddles the top border (top −11px),
  right-aligned, BOTH container states (header-parity holds). GroupNode appends the merged
  count-expander (keeps class `.group-toggle` — the GraphView click-semantic pins passed
  untouched; stopPropagation + dblclick unchanged). Leaves get chips only.
- **Retired:** the Badges batch arm (+ `.badge-batch`, the already-dead `.badge-loop`), the
  category-line `.loop-mark`, the `iconFor` looped-sub-workflow loop-glyph swap (identity
  never mutates — behavior is border chrome), the `▸ N nodes` count pill + separate corner
  button. The io card's `"N inputs"` pill restyled to the 22px chip language (same species).
- **The non-obvious find:** `.node.detailed` was `overflow: hidden` (compact had already
  been re-set visible for connector stubs) — it would have CLIPPED the rail, and had been
  SILENTLY clipping the batch deck on advanced cards all along. Both densities are now
  `overflow: visible`; rows have transparent backgrounds so the rounded corners survive
  (browser-verified). The header's `padding-right: 34px` corner-button clearance died too.
- **Reserved seam, stated in the docs:** the rail is the future live-overlay's status-chip
  home — status joins leftmost, outranks modifiers. Dynamic `×N` is exactly the slot a
  per-run real count fills.

**Verified:** +6 ChipRail pins (literal ×3 / dynamic ×N + tooltip /
sequential naming / loop+batch order / expander slot / chip-less null). Real browser (headless loop): batch-test TD/beautiful (leaf chip + deck,
description full width), run-cycle collapsed card (`[⧉ ×N] [3 ⤢]` rail) AND open region
(same rail across the fold), execute-plan review-round advanced (amber ↻ chip on a
detailed card — the overflow fix at work; clean CLAUDE CODE category), io card pill
parity (zoomed crops). Zero Python/contract change.

### TRANSFORM Level 2 — result shape + per-key edge landing (2026-06-10) ✅ (uncommitted)

> Plan: `implementation/sub-plans/transform-l2-plan.md` (approved + review-folded). Built phase-by-phase
> per the plan; this entry records the DEVIATIONS and surprises only. **Corpus Mermaid diff EMPTY** (56/56, before/after via a HEAD worktree — run
> twice: post-Phase-2 and on the final tree); browser-verified on all four plan cases.

**Built as planned (no restating):** `RFResultShape`/`_result_shape_from_code` (Half A),
`refs_with_path_in` one-shared-walk extractor, `Edge.output_path` `compare=False`,
build sites 1+2 with the alias-guard + equality rule, `RFEdge.output_path` cleared with
re-anchoring, the `OutputRow` single-source row model + D2/D3/D4 composition + the per-key
landing ladder. The plan's verified facts held — zero integration surprises in Phases 1–3.

**7-agent review (the Phase-4 step-0 gate) → all fixes landed same session:**
- **The convergent find (5 of 7 agents): the fail-closed promise had mutation holes.** The
  plan's pinned "result assignment" definition (Assign/AnnAssign/AugAssign target-walk +
  subscript) missed `result.update({...})` / `.pop()` / `del result[k]` / `for result in` /
  `with ... as result` — each ships a keys list that LIES (probed live by two agents).
  Fixed beyond the plan's letter, per its own rationale: new `_result_shape_uncertain`
  invalidates `keys` on ANY attribute access on `result` (no mutating-vs-pure whitelist —
  `.get()` also kills keys; absent beats wrong), del/for/with/comprehension/match-as
  rebinding. Aliasing (`r = result`) stays statically invisible — accepted residual.
- **Two mutation-verified test gaps (test-fidelity agent), both closed:** (1) deleting the
  site-2 equality guard survived ALL 3087 core tests — the plan's own done-when case was too
  weak to reach it; pinned via an output `source: "${input_x.y.z}"` (resolves to an input →
  `output_field=None` → tail must stay off). (2) Mutating the edge-scan to mark sub-reads as
  bare survived all 177 web tests (the unit matrix injects FieldReads directly; the seam
  between scan and composition was untested) — pinned by asserting the exact flat D3 row list
  from REAL edges.
- **Renderer dedup key now includes `output_path`** (3 agents flagged the residual as
  understated): site-2 output-source edges carry `input_name=None`, so two sub-key refs in ONE
  `source:` expression collapsed to one RF edge — the second key lost its line AND rendered
  quiet-unread. The plan called extending the key optional; the quiet-row consequence made it
  real. Build-level dedup (site 1, same input_name) stays first-path-wins — that one is
  Mermaid-coupled and locked.
- Smaller: `EMPTY_READS` frozen + a readonly view type (the future-refactor corruption trap);
  `{"x": None}` ships type `"None"` not `"NoneType"`; ReadPanel unknown types use the in-file
  `"—"` convention; the all-null shape state (`result = compute()` → `(None, None)` = "provably
  assigns result, nothing further") documented on both contract mirrors; authored-only `result`
  rows order FIRST (primary product).

**THE honest finding (agent-UX critical, NOT fixed — needs a user decision): quiet ≠
unconsumed.** Observed reads derive from DATA_FLOW edges, and plain-param refs
(`prompt: ${gen.result.ok}`) form NO edges (the known model scope limit) — so a key consumed
only through a prompt/command body renders as a quiet "produced but unconsumed" row: an
affirmative wrong claim, where pre-L2 there was merely no line. Documented as "no tracked
reader" in web/CLAUDE.md + the requirements doc; candidate fix (frontend-side param-text scan
into observedReadsByNode — scope-aware sibling matching, no new lines) parked for the user.
Also parked: ReadPanel doesn't show observed/deep read paths (the plan's ">1-level paths"
promise under-delivered; GraphView is the parallel agent's territory today).

**Parallel-agent note:** built alongside the edge-selection agent (their EdgePanel/
`selected`/zIndex work) in flow.ts/flow.test.ts/GraphView/useWorkflowGraph. Their in-flight
red test self-resolved; final gates ran green on the merged tree. The 7-agent review saw the
combined diff — two reviewers explicitly separated the foreign work and checked L2
interactions against it (none adverse).

**Browser verification (server restarted per F11; bundle rebuilt):** validate-fix
`run-validate` advanced → quiet `→ result: dict` parent + nested active `· ok`/`· round` rows,
lines leaving the key rows (mock §3); execute-plan `group-tick` → three flat `→ result.*` D3
rows, three lines (mock §2); deep-research `combine` → parent + nested keys, ONE wholesale
line (mock §1); validate-fix beautiful at rest → unchanged skeleton, no rows/lines. Wire
probed: `result_shape` + `output_path` ship exactly the F1 shapes.

**Quiet-rows decision RESOLVED (user, same day): the param-text scan shipped.** The user chose
option (a) — `scanParamReads` (flow.ts) merges plain-param `${sibling.field.key}` reads into
the observed set so quiet truthfully means "no reader at all". Deliberate bounds, each pinned
by a test: scope-aware (same-parent `node_id` only — a name reused in another sub-workflow
can't be mis-marked), the reader's batch alias is skipped, and a param read NEVER creates a
new top-level field row (no edge + no shape → no row = no claim) nor a line (D5 intact — the
un-quieted test also asserts zero data-flow edges). Residual: refs outside params (loop
conditions) are not scanned. The parallel agent's transient
`__scratch.test.ts` is the only tsc noise on the shared tree (theirs to clean).

### Edge SELECTION (click) + EdgePanel shipped (2026-06-10, user-driven) ✅ (uncommitted)

> Plan + the 4-lens plan review (R1–R16 hardening): `implementation/sub-plans/edge-selection-plan.md`.
> Design converged in conversation: edge-click chosen over hover-first (sticky, touch,
> agent-verifiable, deep-linkable, panel content — hover is the gated follow-on on the same
> machinery); selection = "the loud version of yourself" (hue carries identity, brightness
> carries state — never a foreign selection color). All `web/`; zero contract/Python change.

The review earned its run: all four lenses independently converged on the same seams —
GradientEdge's twin stray RF-`selected` branch, chip navigation needing `resolveNodeFlatId`'s
host resolution, the `loop:` redirect needing the RENDER anchor (`e.source`, a group id for
looped sub-workflows — `data.from` is the suppressed host), and the two findings that became
the load-bearing rules: **the applyFocus identity-bailout must compare the new fields** (a
focused CONTROL edge changes nothing else in its tuple — selection would silently never land)
and **an edge-id focus has no `from/to` escape hatch through rebuilds** (collapse re-anchor/
dedupe can erase the id → GraphView clears the selection rather than leave an all-dim canvas
under a live panel).

- **Pure layer:** `applyFocus` edge arm (only-the-connection incidence — deliberately NOT the
  unit machinery; endpoints lit via `connected`, focusEnd explicitly cleared, `edge-shadowed`
  stripped, `selected`/`dimmed` written to data, zIndex an applyFocus-OWNED channel — my first
  cut fell back to `e.zIndex` and the re-processing test caught the stale-1000 immediately);
  `expandTargets` edge arm (endpoints into the OUTPUT set, never `foci` — the R6 trap).
- **Wiring:** pure `edgeClickAction` dispatch (loop redirect / io-flow restyle-only+panel-clear /
  full select), R7 invalidation effect, `deleteKeyCode={null}`, camera anchor maps edge→flow
  source endpoint at set time.
- **EdgePanel** (5 variants) + the R16 extraction (`ParamBlock`/`OutcomeTable` out of ReadPanel,
  extended with highlight-this-ref / mark-this-row). The dict-key binding walk (`bindingParam`
  mirrors `targetHandleFor`) proved itself on the FIRST live render: run-from-plan's
  `happy-check.result → impl` lands inside the `inputs` dict param, highlighted correctly.
- **Components:** bright `--data-edge-selected` (provisional `#8fe8c0` — shoot-lab pending),
  halo under-stroke (INLINE stroke — RF's base stylesheet greys `.selected` paths), label
  suppression on the selected edge, `.label-dimmed` on pills (previously sibling outcome labels
  glowed at full strength over a 0.18-opacity canvas — R10).
- **Deep link:** `focus=<flat edge id>` shipped as the deterministic escape hatch (the
  screenshot loop + Task 169 need it; STABLE addressing stays deferred). Live verification
  immediately exposed the gap the impact review predicted: `initialCollapsed`'s protect chain
  was node-only, so `focus=e14` without `node=` auto-collapsed both endpoints → edge dropped →
  R7 cleared it → silent no-op. Fixed: an edge target protects BOTH endpoints' chains (pinned).

**The verification detour worth recording:** beautiful-mode edge focus initially measured
unexpanded (n49 at 68px, e2 unrendered) across 3 runs + a fresh headless Chrome — looked like
a wiring bug. The scratch-vitest-on-the-real-contract discipline proved the pure pipeline
correct (collapsed {g6,g9} matches the toolbar's 2/4, n49 expands to 316, e2 reveals), and a
12s-wait DOM probe then showed everything LANDS — the **ELK worker hang resurfaced** on the
deep-link expansion layout and `layoutWithWatchdog` rescued at 10s exactly as designed
(bounded badness, never a dead canvas). Re-probes minutes later: 3s, no stall, twice — the
same nondeterministic environmental class the hang handoff closed with; the watchdog defense
has now earned its keep in the wild. No action.

**Verified live** (screenshot/inspect loop, all via `focus=<edge id>`): data edge advanced TD
(bright dotted line + halo, dim canvas, panel with highlighted ref + file:line); beautiful
data edge (both endpoints expand, row-to-row, 24 edges dimmed, halo — DOM-probed);
branch e12 (marked outcome table, condition, suppressed own pill); decision-end e14 (end ·
outcome + table, protect-chain fix confirmed); error edge on conditional-branching (red
gradient + halo, semantics line, even the branch label pills dim now). **Honest residuals:**
no natural card-crossing case found in the framed shots, so elevation-over-card + the elevated
hit-band remain visually unproven (zIndex confirmed applied; worst case = old behavior);
the selected-shade × halo-weight shoot-lab is pending the user's pick.

New pins: 10 flow edge-focus/expand, 6
viewParams dispatch/resolution, 13 EdgePanel variants (incl. dict-key + role-less + bundle
fixtures), 1 collapse edge-protect.
*(Parallel-agent note: their output-rows/chip-rail work landed in the same files
(flow.ts/types.ts/ReadPanel) throughout — all my edits re-read fresh; their ReadPanel
result_shape facts and my ParamBlock/OutcomeTable extraction compose cleanly.)*

**ReadPanel "untruncated home" promise closed (same day, follow-up).** The last knowingly
under-delivered plan item (Phase 3.2's ">1-level paths"): GraphView now passes `reads` beside
`branches` — the node's outgoing data-flow edges as full dotted paths
(`output_field[.output_path…]`, deduped) — and the panel renders a `consumed` fact
(`result.ok, result.round` on run-validate, verified in-browser via the focus deep-link).
Unblocked because the parallel agent finished their GraphView/ReadPanel rework (and removed
their `__scratch.test.ts`). +1 pin: clicking a producer surfaces the full-depth consumed paths, incl. a 2-deep
`result.a.b`.

**Output-schema shapes + the result_shape → output_shape generalization (same day, user-driven).**
The user's screenshot question ("why does the ship card show a bare `→ result` + `· pr_url`?")
surfaced that structured-output nodes DECLARE their shape — `output_schema` is authored truth the
extractor ignored (AST-over-Python only). Shipping it required one contract correction first: llm's
structured output lands in `response`, NOT `result` (llm.py "Writes:"; claude-code's lands in
`result`) — so the shape must NAME ITS FIELD or llm rows would describe a port that doesn't exist.
Renamed `RFNode.result_shape` → **`output_shape`** with a `field` member ("result" | "response");
the field is hours old and uncommitted, so the rename cost nothing and kills the naming lie before
it ships. `_shape_from_output_schema(schema, field)` (fail-closed: only top-level `type: object`
with dict properties; templated `${...}` schemas are strings → None) feeds claude-code
(field="result") and llm (field="response"); code nodes unchanged (field="result"). Key types use
each source's OWN vocabulary (Python names from annotations, "string"/"number" from schemas) —
authored text, never normalized. Frontend: `outputRowsFor`/`scanParamReads`/ReadPanel all follow
`shape.field`. Execute-plan now ships shapes on all 5 schema'd claude-code nodes (probed: ship →
pr_url/summary: string). Also same session: the row tooltip carries `field: type` (a long label
ellipsizes the faint type suffix away — user question exposed it). +1 response-field pin; goldens untouched (renderer-only).

**Post-entry verification + decisions from the Q&A round (2026-06-10, late):**
- **llm response-shape verified LIVE on corpus** (the output-shape entry predated this):
  run-cycle's `plan` node ships `{field: response, keys: [issues: array]}` on the wire and
  renders its response rows on canvas — both shape sources (AST + output_schema) and both
  fields (result/response) now have real-browser evidence, not just pins.
- **Rename totality finished:** two test NAMES still said `result_shape`
  (`test_result_shape_extraction_matrix` / `..._ships_on_the_contract_...`) — renamed to
  `output_shape` forms; the only remaining `result_shape` tokens in the tree are the two
  internal helpers (`_result_shape_from_code`/`_result_shape_uncertain`), whose names are
  correct (they extract the result-field shape specifically).
- **Considered + REJECTED: registry-declared interface rows.** "A node can output many
  root objects" (shell: stdout/stderr/exit_code/…; llm: response/error/prompt/llm_usage) —
  the row machinery already handles multiple roots per node (rows are per observed FIELD).
  Documenting ALL of a kind's potential roots as quiet rows from the registry's declared
  interface was considered and rejected: it would pin a fixed block of mostly-noise rows on
  every advanced card. Rows come only from authored shapes or actual reads — no row = no
  claim. (If ever revisited: the source is the node registry, and output_shape becomes a list.)
- **Open knob (user undecided):** the nested-row glyph — `· ok` (current, per the approved
  mock) vs `.ok` (mirrors the `${result.ok}` ref syntax). Don't change without their call.

### Session close — TRANSFORM L2 + follow-ups batch (2026-06-10)

**One joint uncommitted batch again** (32 modified files), interleaved with the parallel
agent's edge-selection + chip-rail arcs in the same web files — per-author split impractical
(same precedent as the two prior batches). **This agent's slice** = the L2 contract chain
(scope/model/build/react_flow + tests) and its web half (types/flow/WorkflowNode/ReadPanel/
GraphView + styles/tests) + doc sync. *(Batch landed; gates re-run green on the merged tree —
corpus Mermaid diff empty, run twice via a HEAD worktree.)*

**Open threads (not blockers):** the watch item — advanced density grew (every
shape-bearing node carries rows; reads fine on run-cycle/execute-plan, user's eyes on the
big harness are the acceptance test); llm `error`/`prompt`/`llm_usage` and shell's binary
flags stay observed-only by design; expression-level type inference deliberately not
attempted (the fail-closed bar).

**Same-day follow-up (user-caught, 2026-06-10): the data panel's param/highlight was BLIND to
sub-workflow input ports.** The user clicked `result → concept_brief` (a binding into a
sub-workflow's input) and saw no highlighted `${ref}` — the panel's `bindingParam` looked only
at the direct TARGET, and a port has no params; the authored text lives on the sub-workflow
STEP's `inputs:` mapping in the parent file. This is the most common binding shape in real
fan-out workflows and none of the corpus fixtures covered it. Fix: `portOwnerHost`
(EdgePanel.tsx) resolves port → wrapper → parent group → HOST node; an input-port target
shows the host's `inputs` param with this edge's ref highlighted (binding key = the PORT's
name), and the io fact now words the port honestly by direction ("sub-workflow input of
song-creator" / "workflow input" / "workflow output" — it previously said "workflow output"
for every io target). Pinned by a jsdom fixture mirroring the user's exact shape; verified
live on run-from-plan e66 (group-tick.result → execute-plan's delta port: the `inputs` dict
renders with only `${group-tick.result.delta}` marked).

**Chip-click camera follow (user-caught, 2026-06-11).** A chip naming an off-screen card
selected it invisibly — the panel swapped but the canvas looked dead. `onNavigate` now also
`fitView`s the target (padding 0.45, maxZoom 1.2, 300ms — "bring into view", not a close-up;
in beautiful the expansion re-layout that may follow anchors on the same id, so the target
stays near where the fit put it). Verified via a DOM-click probe on run-from-plan e66:
camera transform changed + panel swapped to the chip's node.

**Outcome-table layout fix (user-caught, 2026-06-11).** The shared facts table's fixed 76px
label column (sized for "loop cap") wrapped outcome names mid-word and orphaned the arrow
("→\nprocess-\nlarge"). OutcomeTable now carries `facts outcomes`: labels one-line
(min 76px, ellipsis past 55% with title tooltip), rows padded 4px and baseline-aligned;
`.fact-marked` keeps just the bg (spacing moved to the row rule). Screenshot-verified on the
user's exact case (conditional-branching e2).

### 4-lens deep review of `d8e4a3a9..HEAD` + my-side fixes (2026-06-11) ✅

> Reviewed the COMMITTED merge of both parallel workstreams (edge selection × output
> rows/L2/chip rail) with 4 scoped lenses (feature-interactions / silent-failures /
> simplicity / test-fidelity). Workstream-B + shared items handed off with full repro/DoD:
> `implementation/sub-plans/review-fixes-handoff.md` (9 issues — headlined by the CRITICAL
> pre-existing literal-`items:` batch hole: host=True + memberless batch group → node
> invisible, spine dropped; repro verified live, screenshot in /tmp/pflow-shots). My-side
> items fixed in the same session:

- **EdgePanel learned `output_path`** (interactions-W1): title/bundle/highlight carry the
  sub-key path — two sub-key lines from one field now read as the distinct connections
  they are; the highlight prefix includes the path so sibling refs never co-light. +3 pins.
- **Deep-link invalidation race FIXED** (silent-W1): the hook now exposes `builtEdgeIds`
  (synchronous with focus-derived expansion) and the clear-on-disappear effect consults
  IT, never the painted lagging edges — a deep-linked dedupe-losing binding id now
  survives (live-verified: run-from-plan `focus=e134`, the 4th binding of the n13→g1
  bundle: halo + dim + panel land).
- **`portOwnerHost` walks past hostless item containers** (silent-W2) + the io fact never
  calls a nested port a "workflow input" (`portIsNested`). Pinned with the
  batch→hostless-item→wrapper topology.
- **`bindingParam` consolidated into flow.ts** (simplicity-1): `targetHandleFor` now
  consumes the single copy — canvas landing and panel can no longer drift.
- **Coalesce-aware highlight** (silent-S3): ParamBlock matches per `??` operand.
- **EdgeHalo extracted** (simplicity-7); Chip dead ternary removed (simplicity-5);
  **EdgePanel fixtures got production-style divergent ids** (test-W3 — flat id ≠ node_id;
  an id↔name confusion now fails ~10 formerly-blind assertions).
- Deferred with full spec into the handoff doc: the camera-follow regression pin (test-W2).

Bundle rebuilt; live probes green.

### Review-fixes batch: all 9 handoff issues closed (2026-06-11) ✅

> Worked `implementation/sub-plans/review-fixes-handoff.md` start to finish — every issue verified
> against the live code/contract BEFORE fixing (workstream-A's items were confirmed
> already landed in `e7f2bd7b`). One issue grew: the rest matched the doc exactly.

**Issue 1 (CRITICAL) — scope was WIDER than the handoff stated (user-caught mid-fix,
independently confirmed by my own contract dump minutes earlier): BOTH literal-batch
shapes were invisible, not just the leaf.** A literal batch OF SUB-WORKFLOWS (deep-research
`reviews`, song-creator `emotional-reviews`/`craft-reviews`) ships a memberless batch group
whose item workflow containers are child GROUPS with `host=None` — so the old
`members.length === 0` shell rule swallowed it, the `is_group_host` host had no on-canvas
representative, and `renderAnchor` warn-dropped every edge touching it (song-creator: 6
edges, the spine shattered at both batch steps). The handoff's own DoD #4 ("sub-workflow
batches still render") would have passed while leaving it broken. Two-sided fix:
- **Python:** `_is_group_host`'s literal arm now requires KEPT item containers
  (`_literal_batch_hosts_with_items`) — a literal-batched LEAF ships `False` (leaf items
  are BatchSpec.items data; no body to draw — it renders as a leaf with deck + the
  previously-DEAD literal `⧉ ×3` chip), an all-unexpanded literal workflow batch ships
  `False` too; a literal batch with expanded items stays `True`. +3 renderer pins.
- **Frontend:** `shellBatchIds` (flow.ts) is now THE single copy of the shell rule —
  dynamic batch group ⇒ always a shell ("sub-workflow WITH batch" reparenting intact,
  run-cycle untouched); literal batch group ⇒ shell only when it holds no child groups.
  The literal batch container renders as the host's representative box (title, chip rail,
  deck, collapsible, counted in N/M, deep-linkable by name). buildFlow + `collapse.ts`
  + `viewParams.ts` all consume the helper — the rule lived in THREE drifting copies,
  which is exactly how the bug class shipped. +2 flow pins (the leaf repro shape; the
  song-creator shape incl. a truncation-re-anchored host-level edge), +1 collapse,
  +1 viewParams.
- **Verified live** (screenshots in /tmp/pflow-shots): the leaf repro renders
  `prep → fan(⧉ ×3 + deck) → done` in both densities; song-creator's spine is one
  connected chain ("0/9 open" — the batch boxes now count), collapsed card `[⧉ ×4][4 ⤢]`,
  truncated `craft-reviews` `[⧉ ×5][2 ⤢]` (honest: full count on the chip, kept
  representatives on the expander), expanded region shows the item groups inside.

**Issues 2–9, per the handoff's DoD (deviations only):**
- **2:** `_module_scope_walk` (new) scopes `_result_assignments` + `_is_transform_code`'s
  result accounting to MODULE level — purity/`next` gates stay whole-tree (fail-closed
  direction). Comprehension-walrus still counts (PEP 572 binds in the containing scope);
  lambdas skipped. Pinned: nested-def-only `result` → shape None + not-transform;
  module literal UNPOLLUTED by a helper's local (an improvement over the old "second
  assignment" reading); top-level if/else PRESERVED (shape ships, keys None).
- **3:** the `compare=False` pin went in `test_graph_build.py` and was MUTATION-VERIFIED
  (removing `compare=False` → two edges → red; restored → green). NOTE-TO-SELF recorded:
  I restored the mutation via `git checkout model.py` — safe here (model.py carried no
  uncommitted work) but the same reflex later reverted my OWN uncommitted GraphView.tsx
  edits during the Issue-9 mutation check; re-applied. Mutate via targeted edits, restore
  via targeted edits — never `git checkout` a file that may carry in-flight work.
- **4:** `scanParamReads` now splits `??` operands and skips literals (mirrors
  `TemplateResolver.split_coalesce_operands`/`is_literal_operand` exactly); the provably
  wrong "literal operands can't false-positive" comment replaced with the real argument.
  Pinned both ways (quoted-literal ref stays quiet; non-literal operand still reads).
- **5:** `toFlowEdge` takes `decisionEnd` (computed from the `decisionIds` set at the call
  site) — outcome "end" now rides a condition-null decision END edge (branchLabels and
  EdgePanel already used the correct rule; EdgeData was the odd one out).
- **6:** `paramTextReads` extracted as the shared walk; `scanParamReads` consumes it and
  new exported `consumedReadPaths` (edges full-depth + param reads, same no-new-claims
  gate) feeds GraphView's `reads` prop — panel and canvas can no longer disagree. Pinned
  pure (flow.test) + jsdom (prompt-only read lists in the panel).
- **7:** Badges.tsx DELETED (the unexpanded badge is inlined in WorkflowNode, GroupNode's
  shape); `.badge-more` CSS gone; ChipRail absorbed `ModifierChips` (unexported, double
  guard gone). No visual change — markup identical by construction, pins untouched.
- **8:** `ioOwners(graph)` returns BOTH maps (wrapper→owner, port→owner) from one
  implementation — buildFlow's `wrapperOwner`/`ioNodeToOwner` and expandTargets' loose
  `g.parent ?? g.id` copy both replaced. All existing pins stayed green unchanged.
- **9:** the camera-follow pin partial-mocks `@xyflow/react` (fitView spy wraps + calls
  through; `useNodesInitialized` stubbed true — jsdom's no-op ResizeObserver means RF
  never measures, so the deep-link/fit effects were unreachable in ANY jsdom test).
  Covers the `focus=<edge id>` GraphView arm too (previously untested). MUTATION-VERIFIED
  (deleting the `fitView` call in `onNavigate` → red).

**Gates:** Mermaid goldens byte-identical (model.py/build.py untouched — the Python changes are
RF-renderer-only); bundle rebuilt, server restarted (the
serves-old-Python gotcha), final advanced-density screenshot green.

**Still deferred (unchanged from the handoff's deferred section):** the flow.ts
decomposition (now ~1700 lines), `toFlowEdge`'s positional params, the selected-edge
shade/halo shoot-lab (user pick).

### SPINE alignment (2026-06-11, user-driven) ✅ (uncommitted)

The user's staircase screenshot → root cause: expanded regions have no ELK port (compound
crash), so ELK center-anchors them while handles render on the icon line — drift compounds
down every chain. Fix: `web/src/graph/spine.ts alignSpine` (new post-layout POSITION pass,
called at the end of `layoutGraph` so cache/anchoring/animation see aligned positions): each
PURE sequential chain (forks/merges/multi-terminal sinks break it; error edges don't) aligns
its anchors to its HEAD's, per scope, both directions; shifts that would crowd a sibling
(`SPINE_CLEARANCE`) are skipped. Measured straight on run-from-plan + deep-research (TD + LR);
deep-research's Outputs card stays off-spine correctly (6 terminals → merge sink) *(changed
2026-06-11: the sink-derivation fix leaves deep-research ONE sink, so its Outputs card now joins
the spine — the multi-source merge rule still applies where real merges exist)*. 12 pins in
`spine.test.ts` incl. a real-ELK integration test, mutation-verified (unwiring → red). Zero contract/Python change; flow.ts untouched (parallel handoff agent's
file).

### The frontend LOSSLESSNESS invariant + real-contract fixtures (2026-06-11, user-prompted) ✅

> The user's "passing the right thing" challenge, answered with the gap this very
> session proves: the literal-batch bug fired buildFlow's "dropped edge — no on-canvas
> anchor" console.warn on real workflows for a DAY and no test listened. Python had its
> no-info-loss test (model→RF); the frontend half (RF→flow) did not exist — and every
> web test ever written feeds buildFlow HAND-BUILT contracts (the synthetic-fixture
> trap, tests/CLAUDE.md #19: my own Issue-1 web fixtures bake `is_group_host: false`,
> so reverting the Python fix would have left them green).

Two pieces, both mutation-verified:

- **`web/src/graph/lossless.test.ts`** — `expectLossless(graph, view)`: (1) the
  production warn becomes a test FAILURE; (2) every non-IO contract node must have an
  on-canvas representative; (3) every contract edge's connectivity must survive — some
  flow edge of the same kind connects a representative of its source to one of its
  target, unless both share one (a legitimate internal drop). Representatives derive
  from the contract's own semantics THROUGH THE PRODUCTION SEAMS (`ioOwners`,
  `shellBatchIds`) — never a renderAnchor re-implementation. Swept over a 7-shape
  synthetic structural matrix (chain+data / decision+error+end / dynamic batch leaf /
  dynamic batch sub-wf+loop / literal batch leaf / literal batch sub-wf incl. the
  truncation-re-anchored edge / nested IO wrappers+bindings) × up to 6 view states
  (both densities × both directions, collapse-all, focus-expanded).
- **Committed REAL contracts** (`web/src/test/fixtures/contracts/*.json` —
  conditional-branching / run-cycle / deep-research, generated by
  `tests/fixtures/react_flow_contracts/_generate.py`), swept through the same
  invariant. Drift-guarded by `tests/test_core/test_react_flow_contract_fixtures.py`
  (committed JSON == live renderer output; regen command in the failure message —
  the cache_analysis `_generate.py` pattern). This closes the cross-language seam: a
  contract change OR a fixture-workflow edit fails the Python guard loudly; a
  composition regression fails the web invariant against REAL renderer output.

**Mutation evidence (the only reason to trust it):** (1) reintroducing the old
`members.length === 0` shell rule → the song-creator synthetic shape AND the real
deep-research contract fail (the exact Issue-1 class, caught at both layers — the
shared-helper mutation cannot cancel out: the host loses all representatives either
way); (2) a SILENT no-warn branch-edge drop → the decision shape + conditional-branching
+ run-cycle fail via the connectivity accounting — the invariant is not warn-theater.
Both restored via targeted edits (the git-checkout lesson applied).

Also closed while interrogating my own tests: the leaf unexpanded BADGE had zero render
coverage (Issue 7's DoD said "trust the existing test" — it didn't exist; the
no-visual-change claim rested on markup inspection alone). Added the GraphView jsdom pin
(badge text + tooltip). Fixed collapse.test's stale shell-definition comment ("no direct
members" — the exact misreading that shipped the bug).

**Considered + NOT done (judged not worth it):** a JS↔Python ref-grammar parity matrix
for `paramTextReads` beyond the coalesce pins (the residuals — bracket refs, loop
conditions — are documented and both sides agree by construction today); browser CI
(established decision); more unit pins for their own sake.

**Literal-batch card category → "BATCH-WORKFLOW" (2026-06-11, user-decided; first cut
"SUB-WORKFLOW · BATCH" was revised to the compact form the same session).** The
newly-rendering literal batch container said bare "BATCH" (the GROUP's kind) while its
dynamic sibling says "SUB-WORKFLOW" + chip — the same authored step changed identity by
items-authoring style, and the batch fact appeared twice (label + chip). Now
`groupCategory` (GroupNode) composes identity-first for a batch container with a
workflow-kind host; other batch shapes keep the plain label. Both states (header parity —
one markup). Verified on song-creator.

### Session close — review-fixes batch + losslessness invariant + label (2026-06-11)

**One uncommitted batch again, interleaved with the parallel spine-alignment agent**
(their slice: `spine.ts` + `spine.test.ts` + `layout.ts` — untouched here; per-author split
impractical per the standing precedent). **This agent's slice** = the three entries above (the 9-issue review-fixes batch,
the losslessness invariant + real-contract fixtures, the BATCH-WORKFLOW label): the Python
renderer + the new drift guard, the web flow/collapse/viewParams/components changes + tests,
and the doc sync. *(Landed as `70fc42c7`.)*

**Open threads (not blockers):** the truncated literal batch's chip-vs-expander reading
(`⧉ ×5` true count beside `[2 ⤢]` kept-representative steps — both honest, can read as a
contradiction; revisit if it confuses); the deferred trio unchanged (flow.ts decomposition
~1750 lines, `toFlowEdge` options-object — now 13 positional params, selected-edge
shade/halo shoot-lab awaiting the user's pick); fixture-workflow edits to
conditional-branching / run-cycle / deep-research now fail the contract drift guard with a
one-command regen (by design — the failure message carries it).

### Floating Outputs card: io-flow sinks derive from control edges, not `is_terminal` (2026-06-11, user-caught) ✅

The user's screenshots (lyrics-generator): the Outputs card floated beside the spine,
attached to nothing. Root cause, confirmed by rendering the real contract: the io-flow
synthesis filtered Outputs-side anchors on the contract's `is_terminal`, but that model
fact counts DATA_FLOW out-edges (deliberately — Mermaid end-sink parity, model.py:169's
own warning comment) — so the most natural authoring shape, *a final leaf whose result is
sourced into a declared workflow output*, reads non-terminal (`build-report -[DATA_FLOW]->
report`). lyrics-generator had ZERO terminal root steps → zero `io-flow:` edges → the card
was a data-only island (its data edges hidden in beautiful). And unlike the Inputs side,
the Outputs side had NO fallback. **Why "sometimes":** a workflow ending in a SUB-WORKFLOW
worked (run-from-plan — the data edges feeding root outputs originate from the
sub-workflow's internal output ports, so the host NodeId has no out-edges and stays
terminal); a workflow ending in a leaf that feeds an output didn't. The feature's original
verification subjects (run-from-plan, run-cycle) were all the working shape —
**deep-research had the bug too** (old root terminals: `[]`, confirmed).

**Fix (flow.ts only — visual policy; the contract's `is_terminal` is untouched, Mermaid
parity unthreatened):** sink-ness is now derived from contract edges — a root step with no
outgoing `sequential`/`branch` edge (error/end excluded, the model's own clauses minus the
DATA_FLOW one). Repurposed the never-consumed `outgoingControl` dead set into
`outgoingForward`; added the missing LAST-root-step fallback mirroring the Inputs side's
first-step fallback (a root cycle can no longer strand the card either). A
second-Python-fact alternative (`is_control_terminal` on RFNode) was rejected under the
deletion test — the frontend already holds the edges.

**Verified:** corpus sink-set diff (old vs new): lyrics-generator `[] → [build-report]`,
deep-research `[] → [final-report]`, run-from-plan/conditional-branching unchanged. Real
browser TD/beautiful: lyrics-generator + deep-research both render one continuous spine
Inputs → … → Outputs. +1 pin (the exact bug shape — final leaf feeds a
declared output with `is_terminal: false`, asserts the io-flow edge exists and the
mid-chain step gets none; the cycle test extended with the Outputs-side fallback). Zero Python/contract change.

### Output-shape typing extended: locals + certainties + branch dicts + kind shapes (2026-06-11, user-driven) ✅ (uncommitted)

Trigger: the user's lyrics screenshot ("why can't we show result.files is an array? why is
result.output_… truncated?") → corpus audit. **Root cause:** `_key_type` was DEPTH-0 — it typed
only what sat syntactically at the dict value position, while the corpus's dominant authoring
style is "build locals up top, assemble result at the end" (55% of keys were `"k": some_local`).
Fix: the `_TypeScope` resolver chain in react_flow.py — rules live in ui/CLAUDE.md →
`RFNode.output_shape`, forms pinned in `test_key_type_resolution_matrix`. Corpus 17% → 65% of
keys typed; the residual is honestly uncertain (conditional bindings, loop-built strings).
Renderer-only + one CSS rule (`.param-name.out` — the 42% cap reserved room for a param value
output rows don't have); deep-research is the only fixture that changed. Browser-verified on
the user's exact cases; flow.ts (the parallel agent's in-flight file) deliberately untouched —
the schema-less llm shape rides `outputRowsFor`'s existing D4 quiet-row path with zero
frontend changes.

**Decisions/surprises the code and docs don't carry:**
- **Latent bug fixed in passing:** the old `inputs.get(name)` arm shipped a REBOUND input's
  stale annotation type (`text: str` + `text = text.split()` claimed str). Now every binding
  site is unanimity-checked; an annotated input seeds its own resolution (induction base: the
  first binding IS the input value), so same-type rebinding (`text.strip()`) still resolves.
- **Schema-present ≠ schema-less (the correctness line):** a templated/non-object
  `output_schema` stays None, never "str" — its runtime value is parsed JSON. Only a fully
  ABSENT schema ships the kind's free-form-text contract (`_llm_kind_shape`). The user chose
  the quiet-row presence (every schema-less llm card grows `→ response: str`) over
  type-only-when-observed.
- **The two-assignment pins survived the branch-dict generalization unchanged** — their
  fixtures' key sets happen to differ, which is exactly the new rule's bail condition.
- **Deferred (needs its own decision):** registry-declared interface types for observed rows
  on shell/http/file/mcp nodes (`stdout: string`) — a contract extension, the third authored
  type source. `output_schema`'s `anyOf`/list-form/`$ref` gaps: zero corpus occurrences, left
  fail-closed.

### Registry types on observed rows: the third type source wired (2026-06-11, user-approved design) ✅ (uncommitted)

The deferred decision from the typing audit, shipped: `RFGraph.kind_output_types` (kind →
output field → declared type, from the registry's parsed docstring interfaces) — full rules in
ui/CLAUDE.md. The design call that matters: **kind-level facts ship once per payload and are
INJECTED at the server seam** (`Registry.output_types_by_kind()` → `render_react_flow(...,
kind_output_types=)`) — the renderer stays registry-free (purity), the model never carries
platform facts, and the frontend join is one fallback line in `outputRowsFor` (types existing
rows, never creates one — the old "noise rows" rejection stays honored). Rejected: per-node
shape lists (duplicates kind facts N times + re-opens D4 row-forcing) and any hardcoded
kind→type table (registry drift). Decisions a future agent needs:

- **`any` entries are dropped at the read-model** (`output_types_by_kind` docstring) — a type
  that says nothing is not a fact worth shipping; MCP tools without an outputSchema all
  declare `result: any`.
- **The fixture generator MUST mirror the server's injection** (`_generate.py` — caught when
  the first regen shipped an empty map): committed contracts represent the real wire, and the
  drift guard passing under the isolated registry proves core-kind interfaces are
  deterministic across environments.
- The map effectively serves shell/http/file/mcp only — llm/claude-code/code always carry an
  authored shape, which wins by fallback order.

Fixtures regen'd (all three gain the field); browser-verified —
conditional-branching's shell card shows `→ stdout: str`.

**Self-audit catch (same session):** the frontend fallback was pinned unit-level only — the
buildFlow argument threading `graph.kind_output_types` to the rows was unpinned (deleting it
kept every test green: the tested-but-unwired trap). Added the buildFlow-level wiring pin
(flow.test.ts). Honest residual, cosmetic: registry types show on canvas rows but not in the
read panel's facts (panels show authored text only — revisit only if it confuses).

### IO interface panel: the io card's dead click gets its panel (2026-06-11, user-driven) ✅ (uncommitted)

> Plan (locked decisions D1–D7, verified facts, steps): `implementation/sub-plans/io-panel-plan.md`.
> Trigger: the user's screenshot — clicking the OUTPUTS card does nothing in advanced
> (GraphView's own comment called the missing panel "a parked knob"). Three searcher passes
> verified the wiring before planning; built phase-by-phase per the plan. This entry records
> the deviations and finds only.

**THE research find that grew the Python slice — `required` polarity was WRONG on the wire.**
`build.py:_add_inputs` defaulted a missing `required:` to `False`; every runtime reader
(validator.py:1663, workflow_executor, ir_preparation, path_validation, describe-formatter,
context.py) defaults `True`, and ir_schema documents `default: True`. So the canvas tooltips
mislabeled every input that doesn't author `required:` — and the new panel would have too.
Fixed at the source. **The plan's predicted golden risk fired exactly once:** Mermaid renders
`(type, required)` on input port labels, so `document-processor.mmd` changed — verified
against the source workflows (title/body omit `required:` → they ARE required at runtime) and
regenerated: the old golden was the mislabel. Contract fixtures regenerated (the drift guard's
two failures were exactly the two fixtures with inputs — conditional-branching has none).

**Contract additions (inputs gain the symmetry outputs had):** input `description` → `purpose`
(`_add_inputs` mirrors `_add_outputs`), `IOPort.default: Any = None` (authored value verbatim;
an authored `default: null` is indistinguishable from absent — accepted, pathological).
**Input `source` stays None (deviation from the plan's "verify, don't assume" item):** the
parser injects `_source_line` only for outputs/nodes, and the inputs schema is
`additionalProperties: False` — injecting it means a schema change, scope creep. The panel
shows source for outputs only.

**Frontend shape (per plan, no surprises):** `wrapperPorts` lifted from a buildFlow closure to
a module-level export (THE single copy — canvas rows and panel entries can't disagree);
`IoPanel` is a third sibling panel (EdgePanel's `Chip` exported — the ReadPanel-exports
precedent; `.read-panel` shell + facts CSS reused; 5 small `.io-port-*` rules added);
GraphView grew the `selectedIoGroup` third resolution arm (disjoint by id namespace) and the
io toggle arm DIED — every node-shaped thing now selects identically. `focusPort` became
owner-aware via `ioOwners`: a ROOT card's row click also opens the panel with that entry
marked; nested rows stay focus-only. No-claims rule carried over: an input with zero
data-flow edges shows NO "used by" row (loop-condition reads form no edges — quiet ≠
unconsumed; never an affirmative "unused").

**Test gotchas (each cost a round):** jsdom has no `scrollIntoView` (optional-call the
method); `syncUrl`'s replaceState LEAKS density across tests in GraphView.test.tsx (an
earlier test's "advanced" click persisted in the URL — the io test pins `?density=beautiful`
in a try/finally); the 29 hand-built `io:` fixture literals needed `default: null` (kept
REQUIRED in the TS mirror deliberately — the wire always ships it, and optionalizing it
re-opens the synthetic-fixture trap).

**Verified live** (headless loop, server restarted per the serves-old-Python gotcha, on the
user's actual lyrics-generator): OUTPUTS advanced TD → panel with `report` + description +
`lyrics-generator.pflow.md:689` + `build-report TRANSFORM` producer chip + `result` field;
INPUTS beautiful focus=g0 → card expands to rows, lines reveal, panel shows `sources`
(`array · required`, full multi-line description, 3 consumer chips incl. an io-port chip)
and `output_base` with `default: ./output`. Wire probed: `purpose`/`required: true`/`default`
all ship.

**Gates:** +7 pins (5 IoPanel jsdom + 2
GraphView click-semantics — the old toggle had NO jsdom pin, a known gap, so nothing
was rewritten); Mermaid goldens green (1 intentional regen, above); the do-not-revert
`required`-polarity note went into ui/CLAUDE.md. Full `make check`/`make test` deferred to
the joint batch close (parallel agent mid-flight — the standing branch precedent).

**Same-day follow-ups (user-caught, 2026-06-11): the "any" filler dies; the producer row
reads as a phrase.** Two screenshot catches on the new panel. (1) `report any` — but the
output authors NO `type:` (verified at the source: description + `source:` only), so "any"
was an INVENTED claim — worse, the canvas card beside it shows the producer's `→ result: str`.
The typing arc (same day, parallel agent) covered canvas output rows but not the io-port
slot — this closed the gap: new `producedTypeOf` (flow.ts, beside `outputRowsFor`) derives an
UNDECLARED output's type from its producer, fail-closed, in the SAME resolution order the
rows use (authored shape field/key type → registry `kind_output_types`; deeper paths /
multi-edge interpolations → nothing). Authored `type:` always wins; single-producer-edge
only. ReadPanel's identical `?? "any"` io fact → the in-file "—" convention. NO filler
anywhere — absent beats wrong. (2) `← [chip]………result` — the field floated to the row's far
edge (`.edge-chip` is `flex: 1 1 0`, the EdgePanel two-endpoint layout); in these rows a chip
is one WORD of a phrase, so `.io-port-uses .edge-chip` un-stretches and the field renders
dot-prefixed snug beside it: `← [build-report · TRANSFORM] .result`. The IoPanel fixture now exercises the derivation (untyped output + shaped producer → `str`,
`queryByText("any")` null); browser-verified on the same lyrics-generator
deep link — `report str` + the one-phrase producer row.

**Round 3 (user-caught, same day): the derived type moves INTO `wrapperPorts`; arrows become
words.** (1) "we are not showing report: str in outputs?" — right: the derivation had landed
panel-side only, while the canvas io row reads the same `Port.dataType`. Moved it into
`wrapperPorts` itself (output ports with no authored `type:` + exactly one producer edge →
`producedTypeOf`), so the CANVAS row now shows `report str` too and the panel's local
derivation block was deleted — one copy, three surfaces (io card row, group-card rows, panel).
(2) "should we say 'data coming from'?" — the bare ←/→ arrows were replaced with the panel's
existing label-word vocabulary (`feeds`/`consumed`/…): a faint `from` heads the producer row
(`from [build-report · TRANSFORM] .result` — one phrase) and `used by` heads the consumer
chips. Browser-verified — the OUTPUTS card row and the panel both read `report str`.

**Round 4 (user-caught, same day): the two row grammars unify; a single-port card titles
itself with the port's description.** (1) "why are these styled differently?" — `report str`
(io row) vs `result: str` (leaf output row): same 12px base (`.react-flow__node`) and the same
`--row-h`, but TWO components — PortRows predates type display entirely (io types only arrived
with today's derivation), so it had a detached 10px `.io-type` and no colon while WorkflowNode's
output rows render the full-size faint `: type` suffix. PortRows now uses the SAME `.row-type`
suffix (one "name: type" vocabulary wherever rows render); `.io-type` deleted. (2) "shouldn't
we show the description instead of 'lyrics-generator' if it's only 1 output?" — yes, and the
user's premise is exactly right: the Inputs/Outputs SECTION has no description slot in the
format, only individual ports do — so a SINGLE-port card now titles itself with that port's
description (the leaf `description || identity` convention; multi-port keeps the workflow
name; the tooltip always carries `workflowName — description`). Browser-verified —
the OUTPUTS card reads `Summary of the run — songs created…` / `report: str`, matching the
transform's `result: str` two inches above it.

### Name labels MOCK: node ids as floating chrome + adaptive IO width (2026-06-11, user-driven) (uncommitted, MOCK — not productionized)

> Design exploration, user-judged via the screenshot loop; all code marked `MOCK`. Tests/docs
> deliberately NOT updated — pins on TD outcome labels and the title id-fallback will fail
> until the design is locked and hardened. A parallel agent works the same files (hover
> feature); slices coexist, one transient clobber scare proved false on re-grep.

- **NameLabel** (WorkflowNode, reused by GroupNode): the node's name (node_id, the `${ref}`
  key) floats above the card as border chrome — like the chip rail, so it dims/selects/
  animates with the card for free and ELK doesn't know. TD: right of the incoming line
  (`ICON_COL_X + 10`, 7px up); LR: above-left (`left: 8`, 6px up) — the BELOW variant
  (n8n-style) was mocked and REJECTED: an inner leaf's label collides with its region's
  outputs strip. Beautiful = `humanizeId()` ("My nice node" — first-char uppercase only,
  rest-casing preserved); advanced = verbatim mono id. Groups: primary host groups only,
  both fold states; IO cards skip (no `${ref}` identity). The in-card title no longer falls
  back to node_id (category-only when purpose is absent).
- **TD outcome labels DIED** (GradientEdge suppresses branch pills): a pflow outcome IS the
  target's node id (`_structural_edge` label = `str(action)` = the `next` value), so the
  target's NameLabel spells the same string at the same entry. Conditions + error pills
  stay; LR BranchPorts rows stay (the condition home). This amends the "forks labeled at
  the target's entry" hard-requirement MECHANISM, not its intent — update
  visualization-requirements.md when productionizing. The "end" outcome dot now carries no
  text (condition still rides the END edge) — looked fine, revisit if missed.
- **Widths**: COMPACT_WIDTH 230 → 280 (user-tuned through 248/258 — fitView masks width
  changes in screenshots, proven by inspect: 258 CSS px measured while "not noticing");
  COLLAPSED_GROUP_WIDTH/IO_CARD_WIDTH 260 → 300 in step (containers must keep their width
  lead or the hierarchy inverts).
- **Adaptive group-IO width** (user-caught truncation: execute-plan's `max_review_rounds:
  in…`): TWO causes — the `.io-rows-cols` 50/50 `flex: 1 1 0` split capped a long input row
  at half the card even beside an EMPTY outputs band, and `GROUP_IO_WIDTH = 380` was fixed
  both ways. Fix: columns size to content + `space-between` (dots stay on the borders);
  `groupIoWidth()` (flow.ts) predicts width from the longest `name: type *` row per column —
  mono rows make char-count exact (`IO_CHAR_W = 7.2`) — clamped
  [COLLAPSED_GROUP_WIDTH, 480]: "prefer the unexpanded card's width when possible" (user
  decision). GROUP_IO_WIDTH deleted. Verified: execute-plan renders all 13 input rows
  untruncated. Residual: the root IO card stays fixed-width (same treatment applies if
  wanted).

Shots: /tmp/pflow-shots/*mockname*. Web test failures are EXPECTED at this stage (MOCK, see above).

### Panel chips → shared avatar component + connection sections + the HOVER system (2026-06-11/12, user-driven) ✅

> One arc across a session, parallel to another agent's workstream (their files left
> alone except surgical touches; their pre-existing GraphView.test failure is NOT ours).
> Every visual claim below browser-verified via the screenshot loop; hover via the NEW
> hover.pflow.md (see last bullet).

- **Chip restyle (user-designed):** panel chips became mini node AVATARS — 28px canvas
  tile (kind-color border + native icon) + name, no wrapper box; category word on the
  tooltip. Extracted to `web/src/components/Chip.tsx` (EdgePanel's export had a third
  consumer coming — the seam got real): Chip + ChipStack + ConnectionSections +
  producersOf/consumersOf (one private dataNeighbors). A NESTED io-port chip is
  SCOPE-PREFIXED (`create-songs.concept` — a bare port name loses whose input it is,
  user-caught); root ports stay bare. IoPanel port-producer rows drop a field that just
  repeats the port name (`pr_url .pr_url` said it twice).
- **ReadPanel tail = `references (N)` + `referenced by (N)`** (upstream first — data
  flows in→out). Contract edges only, BY DECISION: the plain-param edge gap is being
  fixed at the model (.taskmaster/tasks/task_168/implementation/sub-plans/proposal.md — that doc was
  TRIGGERED by this feature's under-report finding); both sections complete for free
  when it lands. Empty direction → no section (no-claims).
- **HOVER = mark a SET of canvas subjects, a PURE highlight** (no focus change, no
  expansion, NO camera move — user decision). Chip hover marks its resolved node; ROW
  hover (param/output/io rows) marks every edge landing on the row + each far end —
  `rowTouches` over the FLOW edges (the resolved landings; a contract re-derivation was
  the first plan, killed by the user's final-simplicity directive). One
  `useHoverMarks` set, two readers by id namespace: nodes ring (`.hover-mark` =
  focus ring + un-dim), edges light with the SELECTED treatment (EdgeHalo + bright)
  minus elevation. Marks wiped on any focus/selection/structure change (a click can
  unmount the hovered source — its mouseleave never fires).
- **ALL rows speak ONE connection language (user-caught drift):** wired = teal name +
  live dot; static/unwired = muted + quiet dot — dynamic params, read outputs, and io
  rows identically. THREE real drift bugs fixed: `.port-handle`'s teal was silently
  overridden by the LATER generic `.handle` rule (CSS order, equal specificity); io
  text inset was 14px vs the leaf 10px (io rows now ARE the leaf row geometry); io
  dots floated inside the card (now ON the border — `--io-inset` beside each region
  padding; cards need none). Io wiring is SIDE-AWARE (`Port.receives`/`feeds`,
  PortRows picks per `handles`): a sub-workflow output no caller reads is grey even
  though its inner producer edge exists (user-caught on `segments`); a nested port
  with no line in view is click-INERT (the into-nowhere click, user-caught — root
  card rows always click, the panel is the payoff).
- **hover.pflow.md (NEW, the verification gap closed):** the screenshot skill gained a
  third workflow — dispatch a real `mouseover` on a named row via chrome-devtools
  evaluate_script (React's onMouseEnter delegates through native mouseover), return
  `{ringedNodes, haloedEdges}` counts + screenshot. First run: hovering curate-briefs'
  `inputs` → 3 ringed / 3 haloed, matching its three refs — the production hover path
  verified in a real browser, ending the "hover is the one thing we can't see" residual.

Gates green (example-validation included — the new .pflow.md auto-enrolled). Honest watch-item, not
fixed: every edge/node component consumes the hover context, so one hover transition
re-renders them all — cheap renders, but sweep-across-rows on the ~124-edge harness is
untested; if it janks, the fix is a subscription with selector semantics, not less hover.

### Markdown + code rendering: prose renders, params highlight, canvas strips (2026-06-12) ✅

> Plan: `scratchpads/markdown-code-rendering/implementation-plan.md` (the what/how — three
> treatments, the shiki seam, the language table). This entry carries only deviations,
> review outcomes, and learnings. Zero Python changes — `web/` + docs only.

**Deviations from the plan, each with the reason:**

- **`paramLanguage` gained a "non-string scalar → null" gate** the plan's table doesn't
  have. Rules 2–5 implicitly assume string values; without the gate a non-string scalar
  (`code: 42`) highlighted "42" as python. Fail-closed extension, caught by my own
  table-matrix test before review.
- **The plan's rationale for the `2*3` corruption pin is factually wrong — the pinned
  behavior stands anyway.** The plan claims react-markdown renders `2*3 and 4*5`
  LITERALLY; probed: CommonMark allows intraword `*`, so the panel renders it with
  `<em>` (spec example `5*6*78`). The strip is therefore documented as *deliberately
  more conservative than the renderer* (under-strip beats corrupting numbers), not as
  renderer parity. Canvas and panel can legitimately disagree on CHROME for these freak
  shapes; never on content.
- **The plan's inline "separator rule" failure mode does not reproduce on
  react-markdown 10.1.0.** `unwrapDisallowed` does NOT concatenate block boundaries —
  mdast-to-hast newline text nodes survive unwrapping (my probe + two review agents'
  independent probes). The `p`/`li` trailing-space mapping shipped anyway: an explicit
  space beats relying on an upstream formatting detail, and it's plan-locked.
- **GraphView.test.tsx got the highlight `vi.mock` insulation too** (plan named only
  EdgePanel.test): its ReadPanel tests mount ParamBlocks whose languages resolve
  (bash/json) — same real-shiki-under-jsdom bleed mechanism. IoPanel.test followed
  post-review for symmetry.
- **`@types/hast` added as a devDep** — highlight.ts imports `Root`/`ElementContent`
  types; declare what you import, even type-only.

**7-agent review (`/code-review`) — what it caught, all fixed + gated green:**

- **CRITICAL (silent-failures, execution-verified): `stripMarkdown` corrupted
  code-adjacent prose.** (a) The code-span rule ran BEFORE the emphasis rules, so
  backtick-protected content got de-shielded then stripped: a backticked dunder
  like `__init__` lost its underscores, a backticked `*emphasis*` its stars. (b) The
  emphasis captures' bare `\S` tail happily matched a delimiter: `use *args and
  **kwargs` became "use args and *kwargs". Fix: code spans now lift out to U+0000
  placeholders before any rule and restore after (CommonMark's own protection order);
  capture tails are each rule's non-delimiter class; `_` additionally refuses an
  intraword CLOSE (`_private_var` stays whole — exactly CommonMark's `_` rule);
  emphasis never pairs across a blank line (inlines are per-paragraph). Six new
  corruption pins lock all of it.
- **Raw NUL BYTES in source (impact + validation, both tripped on it).** The U+0000
  escape I intended in CodeBlock's cache key landed as a literal 0x00 byte — the file
  read as binary to git/grep/ripgrep and *hid from the reviewers' own consumer sweeps*
  (the exact failure class the single-copy audits depend on). Fixed byte-level (raw
  byte → the six-char escape text, via python, since my tool output re-converts the
  escape to a raw byte every time); also fixed the same pre-existing 1-byte issue in
  committed `spine.ts:61`. **Standing learning: never emit the NUL escape directly in
  agent tool output for this repo — route it through a byte-level python pass.**
- **The kind-to-language WIRING was unobserved (test-fidelity, mutation-proved: an
  empty `kind` in ReadPanel passed all 327 tests).** Every suite mocked `highlight`
  and ignored its args, so dropping the `kind` prop would silently kill all panel
  highlighting. Added `toHaveBeenCalledWith(prompt, "markdown")` (EdgePanel,
  claude-code prompt) + `("echo hi", "bash")` (GraphView ReadPanel arm).
- **Suggestions taken:** a `paramLanguage` outputs-subset-of-`HIGHLIGHT_LANGS` drift
  pin; oversize-input `console.info` (the one degradation not obvious from context);
  IoPanel.test mock symmetry. **Disputed and NOT done:** inline heading concatenation
  (impact lens) — refuted empirically by two other agents and my own probe, see
  deviation 3. Concurrency + agent-UX + feature-interactions lenses: zero findings
  (the memo-reset race is unconstructible single-threaded; shiki builds a fresh hast
  per call so markRefs' in-place mutation can't double-mutate).

**Learnings worth keeping:**

- **`.pflow.md` descriptions reject `-` bullets** (parser: "use `*` for documentation
  bullets") **and claim any fenced block as a fence-named param** — so authored
  descriptions can't carry fenced code; the Markdown fence path is real but reaches
  only via multi-paragraph prose surfaces. `*` bullets are valid markdown, so
  rendering is unaffected.
- **The memo-reset retry IS provable under vitest:** wrap `createHighlighterCore` via
  `vi.mock` + a hoisted `{fail, attempts}` state — the module import always succeeds
  (no module-cache poisoning); only the factory call fails, so attempt counts
  discriminate reset-vs-memoized exactly. Order-sensitive (failure tests first,
  before the memo fills); documented in the test header, loud-not-silent if reordered.
- **`git checkout -- <file>` to undo a scratch mutation NUKES uncommitted work** — it
  restores HEAD, not pre-mutation state. Cost: re-applying format.ts by hand
  mid-session. Mutation checks on dirty files need targeted edit-reverts.

**Gates at close:** shiki in its own lazy chunks (core ~30 kB gz + engine
+ 5 grammars + theme, loaded on first highlight), main chunk grows by react-markdown
only. Browser-verified via the screenshot loop (`/tmp/pflow-shots/md-render-test-*`):
llm prompt = colored markdown SOURCE with the selected edge's ref marked INSIDE the
colors; python/json param colors; IoPanel rendered prose (bullets + bold, no raw
markers); canvas cards stripped; catalog row inline-bold on one line; plan-to-code's
file-referenced prompt markdown-colored. Residual: a scratch `md-render-test` workflow
was saved to `~/.pflow/workflows` for the catalog screenshot (removal needs a manual
`rm -rf ~/.pflow/workflows/md-render-test` — no CLI delete verb; rm was
permission-denied in session).

### Source pane: left `.pflow.md` view, click-synced both ways (2026-06-12) ✅

> Plan: `scratchpads/source-pane/implementation-plan.md` (review-hardened; the locked
> decisions — NO diff view, one-file-at-a-time + breadcrumb, host→parent-file /
> member→child-file — live there and in web/CLAUDE.md's Source pane bullet). Built by
> one agent, reviewed + fixed by another the same day; this entry consolidates both
> plus the two user-driven follow-ups. One Python change: the `/api/source` endpoint.

**What shipped:** `/api/source` (inline-ALL files in one response, file set derived from
the GraphModel — never the truncation-lossy RFGraph; no client file param → no traversal
surface; root = first top-level node WITH a source file, the inputs-before-steps trap);
`SourcePane` (left pane, `source=1` URL param + toolbar toggle, resizable under a
symmetric two-pane width budget with a 320px canvas floor); pure mapping in
`utils/sourceMap.ts` (nodeAtLine / breadcrumbFor / nodeBlockRange / wrappableLines);
click-sync both directions through the existing `onNavigate` + `resolveEndpointFlatId`
seams. Source FETCH lives in GraphCanvas beside the graph fetch — one snapshot kills the
deep-link race AND graph/source drift across an agent edit.

**Build decisions that stuck:**

- `resolveEndpointFlatId` gained an io-member→wrapper-group arm so `## Outputs`
  `source:` lines focus the Outputs card. Side effect, judged an improvement: a
  `focus=`/`node=` deep link naming a PORT now selects the io card instead of
  dead-ending.
- **THE browser-discovered gotcha: real shiki line spans ship `properties.class` (a
  plain string), NOT `className`** — the pane rendered plain text in real Chrome while
  every test passed on the array shape. `hastLines` accepts both; the regression test
  uses the real shape. (Same lesson class as "jsdom renders no edge DOM": test doubles
  must copy production shapes, not plausible ones.)
- Sync Starlette route like catalog/graph (no async wrapper around sync disk I/O);
  `UnicodeDecodeError` handled with `OSError` (same user-visible class).

**4-lens review (the originally-skipped gate, run post-hoc) — bugs found + fixed:**

- `breadcrumbFor` dropped the node's `ref.ancestor_path` and re-derived the chain from
  the FILE (first invocation in contract order) — a child file invoked from two host
  steps crumbed and NAVIGATED to the wrong invocation. Fixed to walk the node's own
  path; the pin's fixture proves the trap (it asserts fileChainFor picks the other host).
- Stale `activeLine` survived line-less file switches (root crumb, null-line nodes) —
  the new file scrolled to and marked a meaningless line. Line-less switches now clear.
- No window-resize re-clamp: both panes are flex no-shrink, so shrinking the window
  after both widened crushed the canvas to 0 with no recovery. Resize listener added.
- Smaller: lingering missing-file notice; shiki-upgrade scroll yank (`highlighted`
  dropped from the scroll effect deps — rows keep positions across the upgrade);
  `highlight.ts`'s header still promised the REJECTED diff view (doc contradiction
  with the same changeset's recorded no-diff decision — fixed in 3 places).
- **11 mutation-verified pins added where review-critical wiring was unobserved**:
  crumb click-time resolution (a raw-host-id mutant dimmed the whole canvas with all
  tests green), iterate-until-resolves fall-through, ancestorHost's
  is_group_host/port filters (same-level io/host name collision), the GraphView
  clamp-RESERVATION plumbing (the kind-prop lesson repeating: unit-pinned function,
  unobserved call site — the writer proved the prescribed 1200px viewport could NOT
  kill the mutant and moved to 1000px where the budget binds), the deep-link race
  `source` dep, the error-branch hidden toggle, and the server's unreadable-file skip
  arm (patched at `pflow.ui.server.Path` — a global `read_text` patch 422s during
  RESOLUTION before the skip arm is ever reached).

**Follow-ups (user-driven, same day):**

- **Block EXTENT:** selecting a node tints its whole authored block barely-visibly
  (`.src-line-block`, 5% accent vs the heading's 16%). The end derives from the next
  mapped construct or a `#`/`##` section heading in the TEXT — **fence-aware**, or
  every prompt's `## Rules` would have truncated its node's block (`nodeBlockRange`).
- **Prose WRAP:** lines outside ``` fences soft-wrap at the pane width; fenced code AND
  prompts keep exact layout + the horizontal scrollbar (`wrappableLines` — the fence is
  the honest discriminator the pane can know). Mechanics: `pre-wrap` alone never wraps
  inside a `max-content` grid track — the width pin to `var(--source-w)` is
  load-bearing.

**Judged acceptable, not fixed:** sub-920px viewports floor both panes at 300 and
squeeze the canvas below 320 (pre-existing in kind); the body-line vs heading-line
active-mark echo (same gesture, two outcomes — revisit if felt); inline-root invoking
saved-name subs shows a bare disabled crumb for child files (rare entry path);
sourceMap.test's absolute fixture paths break LOUDLY on fixture regen; `overflow-wrap:
anywhere` can break a long unbroken token mid-word at narrow pane widths.

**User-reported "can't see anything on open" — diagnosed, not a code bug:** all three
flows (path / catalog name / `source=1`) render from a fresh build in a real browser.
Cause: a stale tab across a rebuild (old index.html → 404'd lazy-chunk hashes → no
layout) or a stale bundle. Hard refresh after `make ui-build`.

**Gates at close:** browser-verified end-to-end (multi-file navigation + breadcrumbs, block tint,
wrap-vs-fence, the host/member file split on run-from-plan).

### Chip navigation overhaul: port-chip camera fix → deferred follow → navigate-without-opening → pinned selection (2026-06-12, user-driven) ✅

> One arc, four user-caught steps, each fix exposing the next layer — all in `web/`
> (zero Python). Verified per step in a real browser against the user's own
> lyrics-generator workflow (128 nodes; NOT in this repo —
> `~/projects/music-generation/workflows/lyrics-generator/`), driven by a new real
> CLICK harness (promoted to the skill at close, see last bullet). Parallel to the
> source-pane workstream — test counts below include their landings.

- **Io-port chip click "zoomed to nowhere" (user-caught).** A ReadPanel reference
  chip naming a sub-workflow port (`enforce-diversity.concepts`, data edge from the
  port member node) focused an id that is NEVER a rendered node (io members render
  as rows on their owner) — TWO silent skips: `onNavigate`'s camera follow no-oped
  (focus id not in `getNodes()`), and the beautiful expansion re-layout's camera
  anchor resolved no position so the compensation pan no-oped (the EXACT hole the
  edge-focus arm already special-cased in `useWorkflowGraph` — ports were missed).
  At 128 nodes the snap re-layout jumped the canvas out from under a stationary
  camera. Fix: BOTH spots resolve a port to its OWNER card via `ioOwners` (anchor
  effect + `onNavigate` fit fallback). New GraphView pin: a port-chip click
  fitViews the owner.
- **First click landed wrong, second click right (user-caught after the fix).**
  `onNavigate` started its 300ms `fitView` at CLICK time, computed against the
  target's PRE-re-layout position; the expansion re-layout then moved everything
  (warm sessions hit the cached-layout synchronous arm — deterministic repro). Fix:
  the camera follow is DEFERRED to the paint the click produces — new `paintEpoch`
  from `useWorkflowGraph` (bumped after every COMPLETED decoration paint; animated
  glides bump when they land), `GraphView` arms a pending follow and fires it on
  the bump. A SAME-focus navigate repaints nothing → fits immediately (the old
  path). Leaf chips silently had the same race (previously masked by the anchor
  keeping the target "near where the fit put it").
- **Chips NAVIGATE WITHOUT OPENING (user decision).** The user liked the port-chip
  gesture (panel stays, camera centers, connection lights) and asked for it on node
  chips too: one-line change in the shared `Chip` (`onNavigate(resolved)` — no
  selectedId), inherited by ALL consumers (ReadPanel ConnectionSections, IoPanel
  rows, EdgePanel endpoints — the EdgePanel keeps describing its connection while
  the camera follows an endpoint). A chip answers "where is it / how are we
  connected?"; click the centered node itself to open it. Two test pins updated to
  the new call shape (one io-chip pin already encoded it).
- **The panel's subject card contracted mid-read (user-caught immediately after).**
  Beautiful expansion derived from FOCUS alone, so chip-navigating to create-songs
  collapsed build-report's body while its panel stayed open. Root inconsistency: a
  BATCH sub-workflow's `${x.results}` edges attach at HOST level, which a container
  focus's port-level scan never reaches (a leaf chip like build-file-list kept the
  subject open — direct edge; the container chip didn't). Fix at the seam:
  `expandTargets(graph, focus, pinned)` — the open panel's subject pins its OWN
  card (leaf body / container io rows) in every arm, SELF only (no neighborhood —
  focus owns that); `useWorkflowGraph` passes `selectedId` through the new
  `view.selected`. Empty results return the shared `NO_EXPANSION` constant in ALL
  arms (the build-memo identity rule — a fresh empty Set per click would re-run
  build+ELK). flow.test pins: pinned survives any focus, a pinned container pins
  itself, a pinned edge id pins nothing.
- **Real-click verification harness PROMOTED to the skill (user decision):**
  `examples/real-workflows/screenshot-pflow-web-ui/click.pflow.md` (4th workflow,
  SKILL.md row added) — dispatch a real `click` on a `selector`(+`text`) match,
  report `{panel, before/after rect of measure_id, visible, transform}` +
  screenshot. Deep links capture STATES; this captures what a click DOES (camera
  follow, panel stays-vs-swaps — the gap this whole arc was diagnosed through).
  Generalized from a bug-specific two-click scratch harness
  (`scratchpads/io-chip-camera/`, deleted after promotion — the cached-path race
  repro = a second click step in the SAME run, since a reload resets in-page
  state; copy the `click` step for any multi-click sequence). Limitation
  documented: one click per run.

**Gates at close:** browser-verified end-to-end: the port chip centers
the enforce-diversity card with its row lit (cold AND warm/cached paths); the
create-songs chip keeps `panel: "build-report"` while the camera centers its group;
after the pin fix build-report keeps its expanded body (192px @1.2× = rows rendered)
while the camera leaves.

### Sub-workflow ConnectionSections were EMPTY — group hosts aggregate their ports (2026-06-12, user-caught) ✅

- **The gap:** selecting a sub-workflow (execute-plan) showed NO `references` /
  `referenced by` — `dataNeighbors` (Chip.tsx) walked edges touching the HOST id,
  but a sub-workflow's data flow lives on its io-PORT members (bindings target
  input ports, reads leave output ports; only batch `${x.results}` reads attach
  host-level — which is why create-songs showed a partial section and execute-plan
  showed none).
- **Fix — the host aggregates as a BLACK BOX:** subjects widen to host + its
  direct wrappers' port members; far ends are listed only when OUTSIDE the
  container subtree (an input's inner consumer / an output's inner producer is
  the body's wiring, not the unit's neighborhood). Leaf behavior byte-identical
  (subjects = {id}, internal = ∅). Verified on run-from-plan: execute-plan now
  shows `references (10)` (resolve-repo + the root input ports it binds) +
  `referenced by (2)` (pr_url, summary — the parent outputs reading it).
- Chip.test pin: host lists external feeder/reader + host-level batch read,
  never internals; the inner member's own sections stay port-scoped. Browser-verified.

### In-card row hover + io-dot centering (2026-06-12, user-caught) ✅

- **"No hover state" on io/workflow card rows — the system worked, the PAINT was
  invisible.** Investigated with the hover harness first: row hover marked
  1 ringed + 1 haloed in every state (advanced, beautiful-focused) — the
  hover-set channel was fine. The user meant IN-CARD feedback: the only row
  :hover anywhere was `.io-row`'s 4% white (imperceptible), and leaf
  param/output rows had NONE. Fix: ONE shared rule (`.param-row:not(.loop-row)
  :hover, .io-row:hover` at 7%) — every interactive row reads hot under the
  cursor; inert loop-rule rows stay quiet; `.focused`/`.hover-mark`
  (accent-soft) still win by sheet order.
- **Io dots sat ~4px OUTSIDE their card border (cards AND regions) — a
  double-offset.** Measured via a new scratch geometry harness
  (`scratchpads/io-row-geometry/measure.pflow.md`: wrapper/card/row/handle
  rects + computed styles): React Flow's base handle style ALREADY translates
  a left/right handle by ∓50% of its own width, so the stock "centered on the
  row edge" offset is `left: 0` (a leaf param handle computes exactly that) —
  the io rules' `-4px` pushed every dot out by 4px on top of it. Fix: the two
  rules become `calc(0px - var(--io-inset))`. Verified: card dots ±0.5 screen
  px from the border (== the leaf's), region sidebar dot +0.1 px through its
  10px `--io-inset`.
- Learning worth keeping: **don't infer handle geometry from authored CSS —
  React Flow's base sheet composes transforms under it.** Computed-style +
  rect measurement (the geometry harness) settles it in one run.

CSS-only; browser-verified (hovered row
visibly tinted + its line haloed; dots on the border at leaf parity).

### IO-card text hugs its connection side (2026-06-12, user-proposed) ✅

Root Inputs card rows right-align, root Outputs card rows left-align — the one
place that broke the app-wide "text sits beside its dot" convention (leaf output
rows right-align with right dots; an Inputs card FEEDS so its dots are right,
yet its text hugged the far left). Mechanism: alignment keys on which side
carries the LIVE handle (`alignRight = feed || (both && output)` → `.io-col-right`
in PortRows), NOT on input/output kind — so the collapsed group card's
two-column area and region sidebar/strip are untouched (their live side already
matched their alignment). `.io-row-out` died (alignment was its only job).
Browser-verified: both root cards flipped, group card byte-identical.

### Visual-invariants harness + CSS-order tripwire (2026-06-12, architecture-review candidate 5) ✅

> First candidate executed from the architecture work order (the 2026-06-12
> handoff HTML; chosen order 5 → 3 → 4, with flow.ts-touching candidates 2/1
> DEFERRED until the param-ref-data-flow-edges agent lands — candidate 2 moves
> `scanParamReads` into `graph/scan.ts`, a head-on move-vs-edit collision).
> Zero production change; both parts are pure verification surface.

- **Part A — `visual-invariants.pflow.md`** (5th skill workflow,
  `examples/real-workflows/screenshot-pflow-web-ui/`): open-and-settle + one
  evaluate_script + screenshot, returning a JSON verdict. Three invariants:
  (1) every bordered io DOT centers within 2 CSS px of its owner card/region
  border — the check `matches()` the SAME four `--io-inset` CSS selector
  groups production uses, never re-deriving which side a row connects on
  (region rows' inner-scope dots sit at the row edge by design and are
  excluded by construction); (2) every `/api/graph` contract edge id appears
  in the DOM, extras must be `loop:`/`io-flow:` — coverage by IDENTITY, not a
  re-derived count of the synthesis rules; self-skips with a reason unless
  `density=advanced&collapse=none` (hidden/re-anchored edges are design, not
  drops); (3) no two leaf node rects overlap >1 CSS px (regions excluded —
  children render inside them by design).
- **Verified on both fixture workflows** (plan-to-code `run-from-plan`:
  53 dots / 27 leaves / 153 contract edges all rendered (+3 synthesized);
  `deep-research`: 17/11/37) and **mutation-tested end-to-end**: re-adding the
  historical `-4px` dot offset → rebuilt → `passed:false` with 53 violations
  at 3 CSS px; restored → green; `git diff` empty.
- **THE pflow gotcha this surfaced: a code node whose output JSON carries
  `ok: false` is FAILED by the engine's API-warning detector**
  (`api_warning_detector._check_boolean_error_flags` — it JSON-parses string
  results; the same class as the GH #301 error_action caveat). The verdict's
  first run with `ok:false` died at the `clean` step with a misleading
  "API error: API request failed". Verdict key renamed `ok` → `passed`
  (avoid `ok`/`success`/`succeeded`/`status`/`errors`/`error` as top-level
  output keys in ANY pflow workflow that reports failures as data). Noted in
  the skill's SKILL.md.
- **Part B — `web/src/cssOrder.test.ts`** (node-env, runs in CI): pins the two
  equal-specificity rule pairs where source order decides paint —
  `.react-flow__handle.handle` BEFORE `.port-handle`, `.node.dimmed` BEFORE
  `.node.hover-mark` — with failure messages explaining the cascade rule.
  Both pairs mutation-verified (swapped → exactly the right test fails with
  the explanatory message → restored byte-identical). Comments are stripped
  before matching so prose mentioning a selector can't shadow its rule.
- **Deviation from the handoff's sketch:** the test reads `index.css` via
  `node:fs` (+ `@types/node` devDep, the @types/hast precedent), NOT the
  cleaner-looking `import raw from "./index.css?raw"` — PROBED: vitest's CSS
  stub intercepts `.css` imports before Vite's `?raw` handling and returns an
  EMPTY string (compiles everywhere, asserts nothing — the vacuous-pass class
  the lossless suite exists to kill). `@types/node` checked safe first: the
  only timer-handle typing is `ReturnType<typeof setTimeout>` (overload-shift
  immune).

Gates at close: example-validation green (the new .pflow.md auto-enrolled), both fixtures
`passed:true` in a real browser.

### GH #508 filed + fixed: the api-warning detector's un-gated JSON-string unwrap (2026-06-13) ✅

> Spin-off from the visual-invariants harness (previous entry): tracing the
> "successful clean node failed as API error" gotcha to its exact code path
> revealed a gating BUG, not just an aggressive heuristic — filed as
> https://github.com/spinje/pflow/issues/508 (user-decided: new issue
> cross-linked to #301, not a #301 comment — separable, surgical fix vs #301's
> non-trivial pattern redesign) and fixed on this branch.

- **Root cause, pinned:** `unwrap_mcp_response` already encodes the decision
  "result-wrapper inspection is limited to MCP nodes" (`inspect_result`,
  threaded from `config.node_type_name`) — but only the DICT-result arm was
  gated; `_parse_mcp_json_result` (the JSON-STRING-result arm) ran
  unconditionally first. The smoking-gun asymmetry: a code node returning
  `result = {"ok": False}` as a dict was SAFE; the identical data
  `json.dumps`'d was parsed, promoted to "the API response", flag-checked,
  and the node FAILED with "API error: API request failed". Same data,
  different serialization, opposite fate.
- **Fix:** both arms now share the one `if inspect_result:` gate
  (api_warning_detector.py). Deliberately NOT changed, both pre-pinned by
  existing tests: top-level explicit failure flags stay type-agnostic
  (`test_top_level_explicit_failure_flags_remain_type_agnostic`), and MCP
  string-result inspection stays fully alive (the Slack channel_not_found
  scenario).
- **4 regression tests** (test_api_warning_system.py): the observed code-node
  shape → None; the dict/string symmetry pin; MCP string-result still warns
  under an explicit `node_type_name="MCPNode"`. Mutation-verified: reverting
  the gate fails exactly the two non-MCP tests, MCP test stays green.
- **Our-side note recorded in the skill:** the harness verdicts keep avoiding
  `ok`/`success`-style keys regardless — they also transit MCP
  evaluate_script nodes, where flag inspection is INTENDED behavior; the
  whole skill family survives detection today only because chrome-devtools
  wraps results in prose that fails `json.loads` (luck, not design).

### The `?raw` CSS trap: upstream status settled, NOT filed (2026-06-13, user decision)

> Follow-up question on the candidate-5 deviation: "is this fixed in a newer
> vitest?" Answer pinned by probes so nobody re-runs them: NO.

- **Probed standalone** (clean two-file repro, zero config, default settings —
  scratch project, outside the repo): `?raw` on `.txt` returns content; `?raw`
  on `.css` returns vitest's empty CSS stub. Reproduces on **4.1.8 (the
  latest stable — what we run)** AND **5.0.0-beta.4 (the newest published
  version, period)**. `test.css: true` restores real content (the
  interception point is the default `css: false` stub, confirmed via a probe
  config in-repo, deleted after).
- **Untracked upstream:** `gh search` over vitest-dev issues AND PRs finds
  nothing for the `?raw`+CSS combination; the sibling `?inline` query was
  fixed in vitest#3954 (closed COMPLETED, 2023) — `?raw` never got the same
  treatment.
- **User decision: do NOT file upstream.** Repo coverage verified instead:
  zero `?raw` usage in `web/src` (the only mention is cssOrder.test.ts's
  warning comment); the test reads via `node:fs` and its presence assertions
  make an empty read fail loudly ("rule is missing"), so a vacuous pass is
  impossible by construction; web/CLAUDE.md's tripwire bullet now carries the
  full precision (versions probed, `test.css: true` workaround REJECTED —
  enabling CSS processing for every test to prettify one import). Honest
  residual: a future unrelated `.css?raw` import elsewhere would hit the trap
  fresh — documentation is the only guard; a lint ban was judged machinery
  the deletion test doesn't justify.

### Every `${ref}` is an edge — unified data-flow emission + prompt-cache edges (2026-06-13) ✅

> Plan: `implementation/sub-plans/unified-data-flow-edges-plan.md` (review-hardened; the three
> landmines, locked decisions, and expected numbers live there — this entry carries
> only deviations, verification outcomes, and learnings). Context handoff:
> `starting-context/braindump-unified-data-flow-edges.md`. All five phases landed in
> one sitting, gates in plan order.

**What shipped (plan-conformant):** `_add_one_param_input_edges` → `_add_ref_edges`
(THE emitter; the `elif root in level.inputs: continue` deletion is the whole semantic
change), `_add_declared_input_edges` + the `connected` pair-dedup deleted,
`_params_strings` deepened to validator parity with the `shallow` flag,
react_flow's `_string_leaves` in lockstep (H5), scope.py `(?<!\$)` lookbehind +
`_VAR_NAME_PATTERN` fullmatch grammar gate, Mermaid landmine-3 input-source filter +
per-diagram rendered-line dedup, `_add_cache_edges` (`input_name="prompt_cache"`),
ONE fixture regen, frontend: advanced shadow-dim removed, `bindingLabel` helper
(dataFlowLabel + EdgePanel cache arm + interpolated/bundle facts), grammar mirror in
`paramTextReads` (`splitCoalesceOperands` + `VAR_NAME_RE`, gate the UNtrimmed single
operand), docs synced (graph/CLAUDE.md, ui/CLAUDE.md, web/CLAUDE.md,
visualization-requirements.md, proposal status).

**Deviations from the plan, each with the reason:**

- **ONE Mermaid golden regenerated in Phase 1 (generate-changelog LR) — an
  ORDER-only delta the plan's "all 9 byte-identical" verification missed.** Root
  cause: `slack_channel` feeds two nodes through `inputs:` dicts (now emitted by the
  FIRST walk, `_add_child_input_data_flow`, since the input-skip died) and one node
  through a plain param (the later params walk) — the rendered input-edge lines
  swapped order. Verified safe before regen: sorted line MULTISETS byte-identical
  (`diff <(sort old) <(sort new)` empty), so content is unchanged — not a landmine
  (the landmine section's shapes all checked clean). The other 8 goldens stayed
  byte-identical as predicted.
- **`test_param_is_dynamic_uses_ref_extractor_not_str_repr` pinned the OLD one-level
  walk** (`nested: False`) — the plan's "deltas verified unpinned by any test" sweep
  missed it. Updated to the new truth (`nested`/`listed` True) — squarely the H5
  lockstep, not a weakened assertion.
- **The purity guard rejected the word "position" in my `_params_strings` docstring**
  (render-token scan over build.py). Reworded. Good guard.
- **EdgePanel's "interpolated" fact also routes through `bindingLabel`** (plan named
  only bundle entries): a 3-chunk consumer would read "one of 3 references into
  `prompt_cache`" — the raw sentinel the helper exists to hide.
- **Pre-existing RUF059 in `test_schema_coercion.py` fixed in passing** (unused
  unpack `coerced_fields` → `_coerced_fields`) — committed file, blocked `make check`
  for everyone, unrelated to this work.
- **Mermaid's line dedup keys on the arrow text WITHOUT the indent** (plan said
  "line string"): the same logical arrow at two indents would still dedup —
  strictly safer; behaviorally identical on the corpus (the exactly-once pin +
  byte-identical goldens prove no double-render site existed anyway).

**Verification outcomes:**

- Python: new pins — 8 build tests (sibling/plain-param, interpolated multi-ref,
  list param, deep-dict shallow guard, opaque-batch input edge, alias no-edge,
  literal operands + coalesce, escaped/spaced extractor cases), 6 cache tests
  (incl. the real multi-chunk example: 3 producers × 2 consumers = 6 edges,
  level-local sub-workflow cache, malformed shapes), 2 Mermaid tests (landmine-3
  arrow survival — MUTATION-VERIFIED by disabling the filter; same-pair line dedup).
- Contract fixtures: ONE regen, diff READ — run-cycle +6 edges (all explained:
  multi-param same-input reads + plain-param sibling refs), deep-research and
  conditional-branching edge multisets IDENTICAL (id renumbering only), zero
  node-set/group/fact flips. `prompt-caching-multi-chunk` enrolled (pins cache
  edges in the drift guard + the frontend lossless sweep).
- Corpus sweep: 65 built / 14 skipped (the unchanged baseline), 885 data edges
  (plan predicted ~830 EXCLUDING cache edges + two examples added since the
  measurement), build time unchanged.
- Browser (screenshot skill): changelog-simple advanced — new lines land on their
  param rows (get-latest-tag.stdout → get-commits.command verified in-frame), trunk
  full-strength; prompt-caching — three cache lines, EdgePanel "cached context /
  response → cached prompt prefix", extract's ReadPanel `referenced by (3)` (the
  braindump's open thread, closed); beautiful reveal labeled `response → cached
  prefix`; visual-invariants PASS on plan-to-code (181/181 contract edges rendered,
  0 violations) AND deep-research; lyrics-generator renders sane.
- **The shadow-dim USER GATE artifact:** `/tmp/pflow-shots/shadow-dim-comparison.png`
  (left = dim re-added via temp edits + rebuild, right = shipped). The before state
  dims 11 of changelog-simple's sequential spine segments to near-invisibility —
  the predicted "advanced dims most of the spine". Presented to the user with the
  implementation report; the agreed fallback (dim only when NO same-pair data edge
  exists) remains available if they want the middle option.

**Learnings worth keeping:**

- **`git checkout -- <file>` after a mutation test NUKED the uncommitted
  landmine-3 filter** — the braindump warned about EXACTLY this and it still
  happened (cost: one re-apply). Mutation checks on dirty files need targeted
  edit-reverts, never git restore. (Second occurrence in this task's history —
  treat as a standing rule.)
- **A stale browser page CAN defeat the `&v=` cache-buster once**: the first
  "before" screenshot showed no dim despite the bundle on disk having it; the
  live-DOM diagnostic (`check-shadow` scratch workflow: count `.edge-shadowed`,
  read computed opacity) proved the dim WAS live, and a retake matched. For
  paint-vs-bundle doubt, query the DOM — don't re-stare at pixels.
- **A 0.35-opacity delta on ONE short trunk segment is invisible at screenshot
  thumbnail scale** — pixel-diff (`ImageChops.difference(...).getbbox()`) found the
  5×121px changed strip instantly and proved the dim was rendering. Crops lie at
  low zoom; diffs don't.
- The `pflow ui` server must be RESTARTED after Python changes (it answered with
  11 data edges from pre-change code; the catalog probe happily reused it).

### Paint-pipeline tests for useWorkflowGraph (2026-06-13, architecture-review candidate 3) ✅

> Second candidate executed from the 2026-06-12 architecture work order, Route A
> as locked: tests through the hook's EXISTING interface — ZERO production
> change (the hook's diff is empty; only the test file is new). The layout
> cache, stale-paint guard, camera anchoring, paintEpoch, the animated glide,
> and mid-flight cancellation execute under tests for the first time — the
> machinery where the last three user-caught bugs lived.

- **The harness (web/src/hooks/useWorkflowGraph.test.tsx, jsdom):** renderHook
  inside `ReactFlowProvider`; `fetchGraph` mocked KEEPING the real `ApiError`
  (the hook's catch arm discriminates `instanceof` — a factory dropping the
  class crashes the error path instead of testing it); `layoutGraph` mocked as
  a CONTROLLABLE DEFERRED (`pendingLayouts` resolved/rejected on cue inside
  `act`, each resolve choosing per-node positions) — never an instant stub, so
  every ordering claim holds while a layout is genuinely in flight;
  `@xyflow/react` partial-mocked to observe `setViewport` and serve a
  test-controlled viewport (zoom-scaling assertable).
- **All 11 handoff sequences pinned:** stale-paint guard (a focus mid-flight
  paints nothing — `nodes` keeps identity, paintEpoch flat — and the resolve is
  exactly ONE paint already carrying the focus); layout cache (ELK exactly
  twice across focus/unfocus/refocus; cached applies land synchronously);
  eviction bound (>24 states evict oldest, recent states hit — the cache keys
  on the derived string, a fresh equal-content Set still hits); paintEpoch
  glide semantics (bumps when the glide LANDS, not when it starts; mid-glide
  interpolation observed at t=0.5; the skipped stale paint never bumps);
  camera anchoring leaf/io-port/edge arms (pan = anchor delta, zoom-scaled
  against the current viewport); NO pan on direction/density changes (those
  transitions own their viewport via GraphView's fit); pinned-subject survival
  (chip-navigating focus to a container keeps the selected leaf expanded);
  workflow switch mid-layout discards the stale resolve (no paint from the old
  workflow); layout rejection → status "error" with the message, never a stuck
  "loading".
- **Mutation-verified per the handoff's done-when:** reverting the port-anchor
  fix (`owner ?? focus` → `focus` in the anchor effect) fails EXACTLY the
  io-port anchoring test — setViewport never fires, the silent no-op the
  2026-06-12 "zoom to nowhere" bug shipped as — and nothing else; restored
  byte-identical (git diff empty).
- **THE harness gotcha (cost one 335s worker kill, worth the entry on its
  own): a partial-mock of `useReactFlow` MUST memoize its returned instance.**
  `getViewport`/`setViewport` sit in the decoration effect's dep array; fresh
  function identities per render re-fire the effect after its own paint
  (setNodes → render → new fns → effect → setNodes…) — an infinite microtask
  loop that starves the worker so thoroughly no vitest timeout can fire (the
  fork is killed from outside). The real `useReactFlow` memoizes; the mock now
  `useMemo`s on `[inst]`. GraphView.test's `fitView` wrapper survives
  unmemoized only because `fitView` sits in no effect deps there — copy THIS
  file's pattern for any future hook-level RF mock.
- **Path levers, as the handoff prescribed:** anchoring tests force the snap
  path by overriding matchMedia to prefers-reduced-motion (restored per test);
  the glide test stubs rAF into a manual frame queue + pins `performance.now`,
  driving mid-glide and landing frames explicitly. Candidate 4's extracted
  hooks (`usePanelPair`/`useCameraNavigation`) should reuse this harness.
- **Two pins beyond the handoff's 11 (self-review loose ends):**
  (a) `builtEdgeIds` — the ONE returned-interface member the 11 sequences left
  uncovered, and it exists exactly for a race: two parallel bindings dedupe to
  one node-level line unexpanded; focusing the deduped edge id (the deep-link
  gesture) puts it back in the SAME build the focus triggers — builtEdgeIds
  carries it synchronously while the painted `edges` lag one layout
  round-trip (GraphView's invalidation reading the painted set is how the
  2026-06-11 deep-link cancellation shipped). (b) the glide-interruption
  cleanup: a direction change mid-glide lands the EXACT final snapshot, no
  paintEpoch bump (the glide never landed) — without it, interpolated
  positions strand on screen for the whole next-layout window.

Gates at close: zero production change. flow.ts untouched —
no collision surface with the param-ref-data-flow-edges workstream.

### GraphView slimmed: usePanelPair + useCameraNavigation extracted (2026-06-13, architecture-review candidate 4) ✅

> Third candidate executed from the 2026-06-12 architecture work order — the two
> state machines that had outgrown GraphView's wiring move to `hooks/`, exactly
> the handoff's scoped pair (its "do NOT slice further" lock honored — the rest
> is legitimate wiring). Zero behavior change: every moved line and comment
> travels verbatim; GraphView 585 → 467 lines.

- **`usePanelPair(sourceOpen)`** — the two pane widths, the four drag/reset
  callbacks, the persistence effects, and the symmetric re-clamp including the
  review-derived window-resize arm (comment moved with it). `SOURCE_WIDTH_KEY`
  moved too; the pure clamp math stays in `utils/panelWidth.ts`. The
  mutant-calibrated clamp test (GraphView.test, the 1000px viewport) passes
  unchanged.
- **`useCameraNavigation({status, paintEpoch, graph, workflow, direction,
  initialView, ioPorts, focus, setFocus, setSelectedId, clearHover})`** — the
  fit-on-view-change effect (fitKey/lastFit/nodesInitialized gating), the
  one-shot `focus=` deep link (its nodesInitialized gate + the burn-the-flag
  comment moved verbatim — the handoff's named trap), `onNavigate` with the
  io-port→owner resolution, and the pending-follow ref consumed on
  `paintEpoch`. Calls `useReactFlow`/`useNodesInitialized` itself (GraphView
  no longer does). Two interface deviations from the handoff's sketch, both
  narrowing: the hook takes `ioPorts` (the ports map — its only use), not the
  whole ioOwners result; and a `clearHover` callback instead of the raw
  `setHovered` setter (the hook needs "wipe transient marks", not `NO_HOVER`
  knowledge — the appendix's "keep the setHovered(NO_HOVER) calls" intent
  holds, the call just lives behind a GraphView-memoized callback).
- GraphView keeps `graphRef`/`edgesRef` (the interaction callbacks still need
  them); the hook mints its own internal graphRef — two refs over one value,
  invisible. GraphView's ref comment updated to its remaining purpose.
- **Focused hook tests added (the handoff's conditional taken — candidate 3's
  harness exists):** `useCameraNavigation.test.tsx` pins what the component
  tests can't DISCRIMINATE — a NEW-focus navigate fits on the NEXT paintEpoch,
  never at click time (the 2026-06-12 "first click landed wrong" regression,
  directly observable here because paintEpoch is a plain prop); same-focus =
  immediate fit; port→owner follow; an unresolvable target arms nothing; one
  view-fit per workflow|direction|node key. The mock applies the candidate-3
  gotcha: a STABLE module-level `useReactFlow` instance (fitView/getNodes sit
  in effect dep arrays — fresh identities per render would consume the pending
  follow before the epoch bump it waits for). `usePanelPair.test.tsx` pins the
  window-resize re-clamp (the crushed-canvas-to-0 bug — previously untestable
  wiring: the component test sets innerWidth BEFORE mount and never fires the
  resize listener), persistence of the re-clamped widths, and the
  open-vs-closed reservation ceiling (620 vs 860 at a 1400 viewport).

Gates at close: GraphView tests pass UNEDITED (the extraction is invisible
through the component interface — the done-when). No `flow.ts` / Python surface
touched — still clear of the param-ref workstream.

### The "cached prefix" row — cache edges get a visible landing (2026-06-13, user-caught) ✅

> Follow-up to the unified-edge entry above, same day. The user opened the
> prompt-caching view and asked "I can't see it?" — geometry confirmed the cache
> edge's pathRect terminated at the EXACT pixel of the control trunk's NODE_IN
> entry (no param row exists for `prompt_cache`, so `targetHandleFor` fell back
> node-level and the line merged invisibly into the spine). Hard requirement #1
> ("edges land on the EXACT handle") had no handle to land on.

- **Fix = the loop-row pattern, frontend-only:** consumer cards render ONE
  `cached prefix` row (`LeafData.cacheRow`, derived from incoming
  `input_name="prompt_cache"` edges — wired by construction → the dynamic row
  language for free via `param-row dynamic`), between params and outputs. New
  `CACHE_ROW` target handle (handles.ts, registered in `handleType`); all four
  row consumers moved in lockstep: WorkflowNode (render), `leafSize` (+1 row),
  `rowAnchorsFor` (left anchor, shifts outputs down), `targetHandleFor`
  (the prompt_cache arm lands BEFORE bindingParam — which can never match the
  reserved name anyway: the parser lifts `prompt_cache` out of params,
  verified). Rows hidden (beautiful) → NODE_IN fallback unchanged; multiple
  chunks fan onto the one row via the existing lane machinery; row hover marks
  far ends through `rowTouches` for free.
- 4 new flow.test pins (CACHE_ROW landing in advanced, anchor position between
  params/outputs, +1 ROW_HEIGHT height, NODE_IN in beautiful + CACHE_ROW on
  focus-expansion); the HANDLE-TYPE INVARIANT sweeps the new handle
  automatically.
- Browser-verified: prompt-caching — the selected cache line lands ON the row
  (all three consumers show theirs); multi-chunk — three laned lines fan onto
  summarize's single row; visual-invariants PASS (15/15 contract edges).

### Per-chunk cache rows + the rendered cached-prefix block (2026-06-13, user-designed) ✅

> Follow-up refining the single "cached prefix" row (previous entry) into the
> user's design: SHOW the chunks. Two surfaces, one data rule.

- **Contract (small, the only way to get prose):** `Node.cached_prefix` /
  `RFNode.cached_prefix` — the consumer's cached system prefix as authored
  TEMPLATE text, assembled in `_add_cache_edges` (already iterating exactly
  this data) with the runtime's own rule (`build_cache_system_blocks`:
  `prose_before + ${var}`, declaration order, consumed chunks only). Mermaid
  ignores it; goldens stay; one fixture regen (additive: `cached_prefix: null`
  ×65 + two assembled values).
- **Canvas:** `LeafData.cacheRow: boolean` → `cacheRows: string[]` (per-chunk,
  prefix order). Row key/label = the chunk's authored ref text rebuilt from its
  edge (`cacheChunkKey` — safe as a label because the parser enforces chunk
  name == var; the SAME helper derives rows and lands edges, so a line can
  never miss its row — no positional name↔edge join, which dedup/self-skip
  could misalign). N>1 → a handle-less `cached prefix ×N` label row + nested
  `·` chunk rows; single chunk → one flat row with the ref as value. Rows sit
  immediately BEFORE the `prompt` param (`cacheInsertIndex`, shared by render/
  size/anchors — request order: system → cached prefix → prompt; the user's
  call, confirmed). `CACHE_ROW` constant → `cacheHandle(key)` prefix scheme
  ("cache:", target type).
- **ReadPanel:** `CachedPrefixBlock` — the assembled template rendered like a
  prompt param (markdown SOURCE coloring), placed by the same
  `cacheInsertIndex` before `prompt`. The user reads the panel top-to-bottom
  as the model receives the request.
- Tests: 2 new Python pins (assembly matches prose+vars in declaration order
  on the real multi-chunk example; subset-only assembly), the 4 cache-row
  flow pins rewritten + a multi-chunk landing/anchor pin, a GraphView panel
  pin (block order model → cached prefix → prompt). Browser-verified: multi-chunk card shows ×3 + three
  per-chunk rows each receiving its own line; single-chunk flat row;
  panel template block with prose + ${var}; visual-invariants PASS.

### Per-ref binding sub-rows — paramRowsFor unifies the left column (2026-06-13, user-designed) ✅

> The user asked why multi-ref params don't show their refs like cache chunks
> now do — and the simplicity directive pointed at the consolidation: the left
> column gets its `outputRowsFor` mirror, and the cache special-casing
> DISSOLVES into it. Net: more capability, fewer mechanisms. Frontend-only.

- **`paramRowsFor(node, refRows)` (flow.ts)** assembles the ordered
  `ParamRowItem[]` left column — params · the cached-prefix group before
  `prompt` · per-ref sub-rows under any param receiving ≥2 refs — consumed by
  WorkflowNode/leafSize/rowAnchorsFor (`LeafData.paramRows`). DELETED into it:
  `cacheRows` LeafData field, the cache-block JSX, `emitCacheAnchors`, the
  cacheRowCount sizing arm, `cacheHandle` (→ generalized
  `bindingRowHandle(input_name, ref)`, one "bind:" prefix).
- **One derivation, one landing rule:** `refRowsByNode` groups data edges by
  the parent they land under (the containing param via `bindingParam` —
  covering interpolated refs AND dict-key bindings — or "prompt_cache");
  `targetHandleFor` reads the SAME map: cache edges always land on their chunk
  row; param edges land on their ref's sub-row only when the group has ≥2
  (single ref keeps the param row — no sub-row noise on the common case).
  Sub-row labels render as the established `ref-chip`; dict-key rows prepend
  their key; `·` kept as the one nesting glyph (user decisions).
- **CSS fix found in browser:** the `.param-name` 42% width cap truncated a
  ref chip to "…" against an empty value column — `.ref-row .param-name
  { max-width: 100% }`, the exact exemption output rows already had.
- **Rewritten pin:** "two refs land on the SAME prompt handle" (flow.test) —
  the old truth this feature deliberately changes; now pins per-ref landings,
  anchor order below the param row, the single-ref no-sub-row arm, and
  dict-key rows.
- **Browser-verified:** multi-chunk card (3 chips, 3 landings); harness
  invariants PASS (181/181 edges, 0 overlaps) with sane leaf heights (densest
  leaf `implement` 500px — its `inputs` dict now shows 5 per-key rows, each
  with its own line, instead of 5 lines merging into one row);
  lyrics-generator renders sane.

### flow.ts split + the nodeRows row model (2026-06-13, architecture-review candidates 2 + 1) ✅

> The last two candidates from the 2026-06-12 architecture work order — executed
> AFTER the param-ref-data-flow-edges workstream landed, exactly as the deferral
> intended (candidate 2 moves `scanParamReads`, which that agent was editing).
> The handoff's manifests were ADAPTED to the post-handoff code: paramRowsFor /
> RefRow / cacheInsertIndex (none existed on 2026-06-12) land in `rows.ts`, and
> scan.ts carries the unified-edge grammar mirrors (`splitCoalesceOperands`,
> `VAR_NAME_RE`). All five work-order candidates are now done.

**Candidate 2 — `graph/flow.ts` split along its seams (1,965 → 1,017 lines):**

- Four new modules, `flow.ts` stays the package FAÇADE (`export *` re-exports —
  ZERO import churn outside `graph/`): `scan.ts` (param-text read scan +
  `producedTypeOf`, `consumedReadPaths`, `FieldReads`/`EMPTY_READS`); `io.ts`
  (`ioOwners`, `wrapperPorts`, `shellBatchIds`, `Port`); `rows.ts` (row models +
  ALL sizing: size constants, `groupIoWidth`/`ioRowsCount`/`ioAreaHeight`,
  `cacheInsertIndex`, `paramRowsFor`, `outputRowsFor`, `leafSize` (now exported),
  `rowAnchorsFor`); `focus.ts` (`applyFocus`, `expandTargets`, `rowTouches`,
  `SELECTED_EDGE_Z`, `NO_EXPANSION`). Dependency DAG holds: scan → io → rows →
  focus/flow; rows/focus take flow's types TYPE-only (TS-erased, no runtime
  cycle); the ONE `NO_EXPANSION` instance lives in focus.ts and buildFlow
  imports it (the build-memo identity rule kept single-copy).
- **Test split with ZERO assertion edits** (the candidate's done-when): shared
  fixture builders → `graph/testFixtures.ts` (non-.test name); the
  outputRowsFor + rowAnchorsFor describes → `rows.test.ts`; plain-param-read +
  consumedReadPaths describes → `scan.test.ts`; the three IO describes →
  `io.test.ts`; applyFocus/expandTargets/rowTouches describes → `focus.test.ts`;
  build/landing/HANDLE-TYPE/ELK-smoke/loop/cache describes stay in
  `flow.test.ts` (2,397 → ~1,390 lines). 421/421 green at the split's stop
  point; lossless/spine/portSides/layout suites untouched.

**Candidate 1 — `nodeRows`: a leaf's WHOLE body as one handle-carrying list:**

- `NodeRow` (rows.ts) = ParamRowItem variants (param rows gain their
  `targetHandle`) → `output` rows (with `sourceHandle`) → `loop-condition`
  (LOOP_ROW) → `loop-cap` (only when set). `nodeRows` COMPOSES
  paramRowsFor/outputRowsFor — their D-rules and tests are untouched. The four
  hand-mirrored consumers became mechanical walks: `WorkflowNode` = one switch
  over `row.kind` (handles arrive ON the rows — the component no longer imports
  paramHandle/outputHandle/LOOP_ROW); `leafSize` body count = `rows.length`
  (signature simplified — the loop-row arithmetic dissolved into the list);
  `rowAnchorsFor` = every row advances y, only handle-bearing rows emit an
  anchor (the "loop rows advance but don't anchor" trap is now structural);
  `sourceHandleFor`'s ladder consults `rowsByNode` (the generalized
  `outputRowsByNode`). **The S1 scenario ("add a row kind") now touches
  `rows.ts` + one JSX branch.**
- **The ONE interface change:** `LeafData.paramRows` + `outputRows` →
  `LeafData.rows` (keeping both representations would have re-opened the drift
  this candidate closes). 10 test sites reading `leaf.data.outputRows` updated
  MECHANICALLY via a `leafOutputRows` helper — every expected array
  byte-identical (shape-only edits; the handoff's must-pass-unchanged list —
  rowAnchorsFor geometry, spine ≤1px, HANDLE-TYPE, leafSize heights, lossless —
  all pass without edits). 4 new pins (rows.test.ts): body order, handle
  attachment, the loop-cap presence rule, and the leafSize/anchor lockstep now
  asserted mechanically against `nodeRows().length`.

**Verification (the geometric-identity bar, both candidates):**

- Before-geometry captured PRE-split via the inspect workflow; after BOTH
  candidates the full geometry JSON (every node/tile/handle/edge rect) is
  **byte-identical** on both fixtures: run-from-plan (31 nodes,
  advanced+collapse=none) and deep-research (16 nodes). visual-invariants PASS
  on both (181/181 and 37/37 contract edges rendered, 0 dot violations,
  0 overlaps). Zero Python changes.

### Batch-item values in the ReadPanel (2026-06-16, user-driven) ✅

Frontend-only — literal-batch items already ride the contract: file-reference
prompts resolve into the IR at the resolver boundary BEFORE the graph is built,
so `batch.items[i].prompt` is the file's CONTENT, not its path (the `_source_files`
provenance is NOT carried to the model — so there is no path to surface, only the
resolved value). Two additions on that data:
- **ParamBlock `${item.x}` expansion** (`utils/batchItems.ts` resolver): a value
  reading the batch alias on a LITERAL batch grows a `▸ N items` toggle, expanding
  in place to its per-item resolved values, each headed by the item's
  discriminating field (`focus: emotional`). Interpolated values substitute per
  item; non-alias refs stay verbatim; dynamic batch → no toggle.
- **Flat `batch items` block** (`components/BatchItems.tsx`): a collapsed
  disclosure below the structural facts listing every item with all fields —
  short scalars inline, long values behind a `▸ name <size>` pill. The
  whole-config view (surfaces item fields no param reads), complementing the
  per-param view above.
Browser-verified on lyrics-generator's `analyze` (6 specialist prompts, sizes
1.5–3.7 KB). +16 web pins; zero Python/contract change.

### Live source auto-update: the canvas updates in place as the `.pflow.md` is edited (2026-06-16, user-driven) ✅ (staged)

> Remaining DOC work + full
> Born from a CLI-exposure discussion (how `pflow ui`/`visualize` surface to
> agents) → the user's idea: make the UI auto-update when the `.pflow.md` source is
> edited, so an AGENT builds a workflow while the USER watches it take shape. The
> interactive agent↔user loop gets richer in Task 169; this is its baseline.

**The decision that shaped it — poll now, NOT SSE.** The server is already
stateless and re-parses per request, so the data is fresh on the next fetch; only
the *trigger* was missing. Split the feature into DETECTION (how the browser learns
of a change) and REACTION (re-fetch + rebuild in place). Detection = a client
**poll** of a new `GET /api/version` fingerprint; reaction = an in-place re-fetch
that preserves view state. SSE is Task 169's transport (agent→browser commands +
user-event channel); building it here would duplicate/pre-empt it. The poll is a
COMPLETE solution (1.5s on localhost, visibility-gated), not a stopgap — when 169's
SSE lands it can call the same reaction trigger via a push, with nothing downstream
changing. On by default; `pflow ui --no-watch` (→ `?watch=0`) freezes it. The
"swaps cleanly for SSE" framing is in the handoff; user confirmed the no-reload
mechanic (in-place React reconcile, not `location.reload()`) before build.

**What shipped (5 phases, all browser-verified):** `GET /api/version` +
`_source_files_for` fallback chain (build files → entry file → saved-name path →
literal path → `[]`; ALWAYS 200 so an invalid mid-edit never breaks the poll);
`fetchVersion`; `useSourceWatch` (poll: seeds a baseline, fires only on a CHANGE,
visibility-gated, swallows transient errors, in-flight-guarded); the `reload`
re-fetch path in `useWorkflowGraph` (distinguishes workflow-change=full-reset from
same-workflow-reload=in-place via `prevWorkflowRef`; a SEPARATE `reloadError`
channel keeps the last-good canvas + a non-blocking banner on a mid-edit 422 rather
than the full-screen error — status machine untouched); the `watch` view param +
`--no-watch` flag. **Invalid edits never advance the UI** — the canvas holds the
last valid render + a "Source has errors — showing the last valid version" banner
(first diagnostic only; full list deferred — a one-line widen if wanted), the source
pane holds the last valid source (`/api/source` also 422s when invalid), and both
resume on the next valid save. Verified live: valid edit 2→3 nodes viewport-identical;
`--no-watch` frozen; invalid → banner + last-good, no full-screen.

**3-agent Opus review (`review-silent-failures` / `review-concurrency-safety` /
`review-feature-interactions`) on the staged diff → 5 fixes (A–E), all landed:**
- **Concurrency: clean** (no races; the `cancelled`-closure + `key={workflow}`
  remount primitives hold across every interleaving, incl. StrictMode double-invoke).
- **A** — *source pane was stale on reload* (`fetchSource` keyed on `[workflow]`
  only → stale text + WRONG line→node mapping). Now keys on `[workflow, reload]`,
  keeps last-good (no blank flash), silent on a failed reload (the canvas banner
  signals it). Browser-verified (inserted marker appears in the pane).
- **B (load-bearing)** — *preserved selection/focus/collapse re-pointed after a
  STRUCTURAL edit.* Flat ids `n{i}`/`g{j}` are POSITIONAL (renderer `enumerate`), so
  an insert/delete/reorder (NOT an append) re-numbers them → a held flat id pointed
  at the WRONG node (silent) or a vanished one dimmed the whole canvas (the `:217`
  invalidation guarded edges, not nodes). Fix: `web/src/graph/remap.ts` — remap
  through the STABLE structural ref (`node_id` + `ancestor_path` + `port`, the
  contract's own overlay join key) in a GraphView `useLayoutEffect` (pre-paint → no
  flicker); identity-preserving so an append is a no-op (no build churn).
  Browser-verified: focus FOLLOWS `done` through an insert-before, never jumps to the
  inserted node. +9 remap pins.
- **C** — saved-by-NAME workflows (the catalog default) stopped tracking
  edits-while-parse-broken (the literal-path fallback only fires for path args). Now
  resolves the name to its entry path directly via `WorkflowManager.get_path`.
- **D** — `/api/version` could 500 on a validated-but-unbuildable IR (the `/api/graph`
  500 regime). The first `try` now catches any exception → falls through → never 500
  (the poll must not break).
- **E** — overlapping out-of-order polls could fire a redundant reload (both
  reviewers); added an `inFlight` guard.

**Gates:** `make check` clean (mypy 235); Python ui suite 34; web suite 467
(+remap/poll/reload/watch pins); Mermaid goldens untouched (no model/contract
change — this is the server + frontend only).

**Tooling graduated (user-decided):** the three scratch same-page-across-edit
verification harnesses were CONSOLIDATED into one verdict-returning skill workflow,
`examples/real-workflows/screenshot-pflow-web-ui/live-reload.pflow.md` (+ a SKILL.md
row) — the screenshot skill's 6th workflow and its ONLY same-page-across-edit check
(every other reopens the page per run). It self-seeds a throwaway workflow, drives
append/insert-before-focused/corrupt on one open page, and returns `{passed, checks}`
(in-place/viewport/remap/source-refresh/invalid-held — all `passed:true` on verify).
It's the regression guard for the live-reload path AND the same-page-react primitive
Task 169 extends. The scratch trio was removed (`plan.md` kept).

**Known limitation (reviewers agreed not worth fixing):** a workflow that's
mid-edit-invalid in a SUB-WORKFLOW file tracks only the entry file's mtime until it
parses again — recovery still works on the fixing save.

**What's LEFT (documentation only — handoff written):** the user-facing/agent docs
were drafted + held pending verification (now done). Per the handoff: `entry.md`
capability block + Features topic line; new `pflow guide visualization` topic (+
`RESERVED_WORKFLOW_NAMES`); `docs/reference/cli/index.mdx` `pflow ui` section + card
+ visualize↔ui cross-links; a `task_169` poll→push coordination note; and the
canonical current-behavior docs (`ui/CLAUDE.md` `/api/version`, `web/CLAUDE.md` the
poll/reload/remap, `visualization-requirements.md` the live-update feature + limit).
Framing the user owns: `visualize` = the agent's own structural read; `ui` = OFFER
to the user + run in background + it live-updates as you build.

### CLI exposure + `visualize`→`mermaid` rename + doc surfaces (2026-06-16) ✅

> From "how do `pflow ui`/`visualize` surface to agents?" The user's reframing
> SUPERSEDES the framing note just above: an agent does NOT need a diagram to
> understand a workflow — the `.pflow.md` is self-describing, and Mermaid is strictly
> NOISIER for an LLM (verified side-by-side on conditional-branching: 8 lines of
> `classDef` chrome + shape syntax, minus the actual branch logic).

- **`pflow visualize` → renamed `pflow mermaid`** (hard rename, no alias — no users).
  Now niche: run it ONLY on an explicit "give me a mermaid/markdown diagram" ask. Aligns
  the command with its internal `core/workflow/mermaid` module. File/function/registration/
  tests/golden-hints + all current-behavior dev-doc refs updated; history (CHANGELOG,
  `task_*` journals) left accurate.
- **RESERVED_WORKFLOW_NAMES:** + `mermaid`/`ui`/`analyze-cache` (CLI commands a saved name
  must not shadow — `ui`/`analyze-cache` were pre-existing gaps) + `visualization` (guide
  topic); `visualize` freed.
- **Agent guide (the discoverability fix):** `entry.md` gains ONE Features line → new
  `guide/features/visualization.md`. `ui` is PRIMARY + user-facing: user signals "see it"
  → OPEN it (`pflow ui <workflow>` auto-opens their browser); unprompted → OFFER it.
  `mermaid` is a niche footnote. Dropped the literal `&` (backgrounding is runtime-dependent,
  not a shell idiom). **Progressive disclosure:** NO `pflow[ui]` line in the guide — the
  agent meets the extra only IF `pflow ui` errors on a missing dep (~never, since
  starlette/uvicorn ride `mcp[cli]`).
- **Docs:** `index.mdx` `## UI command` + card + `Visualize`→`Mermaid` + cross-links. The
  live-source feature's canonical docs (handoff items) also landed — `/api/version`
  (`ui/CLAUDE.md`), poll/reload/remap (`web/CLAUDE.md`, verified against real
  `useSourceWatch.ts`/`remap.ts`), the requirements entry, the `task_169` poll→push note.
- **Bug found + fixed — the `[ui]` install hint named a nonexistent package.** The
  missing-extra error printed `pip install pflow[ui]`, but the distribution is `pflow-cli`
  (no `pflow` dist exists) and `pip` wouldn't reach a `uv tool`-isolated install. Now
  `→ uv tool install 'pflow-cli[ui]'` (hint + dev doc + pinning test). Two pure-prose
  `pflow[ui]` shorthands (`ui/__init__.py`, ADR-0005) left pending a decision.

Gates: `make check` clean (mypy 235); rename/guide/ui/docs suites green; Mermaid goldens
untouched (CLI-only rename — `generate_mermaid` unchanged).

### Panel header avatar + clickable source link (2026-06-16, user-driven) ✅

Two small panel polish items; frontend-only, zero Python/contract change.

- **Single-subject panel header → a large node AVATAR** (new shared
  `components/PanelHeader.tsx`): kind-colored tile (`iconFor`/`nodeColor`,
  CONDITION/TRANSFORM-aware) + category eyebrow + the name as a NAVIGATE button
  that re-centers the camera (the Chip's navigate-without-opening gesture, just
  bigger). Used by ReadPanel (leaf nodes AND sub-workflow/container HOST panels —
  coherent for free, since a container select renders ReadPanel on its host) and
  IoPanel (avatar = the io card, name → the card). EdgePanel keeps its connection
  header (two endpoint chips — no single subject). The name stays the panel `<h2>`
  with an inner nav button, so the existing `getByRole("heading")` tests held
  unchanged. +6 pins (PanelHeader ×4 incl. navigate + heading-survives; IoPanel
  header-navigates; ReadPanel renders via the shared header).
- **Read-panel source link `file:line` is now clickable** → opens the source pane
  (if closed) AND scrolls it to that line. Closed→open scrolls via SourcePane's
  existing selectedNode effect; an already-open re-scroll rides a new `jump`
  counter (GraphView bumps it on the link click → SourcePane re-asserts the
  selected node's file/line and scrolls, covering "scrolled away" + "browsed to
  another file via breadcrumb"). +2 pins (SourcePane jump re-assert; ReadPanel
  source-link button-vs-plain).

Gates: tsc clean; full web suite 475 (+8); bundle rebuilt + served. Visual layer
rests on the user's eyes (browser tooling not wired in this worktree).

### Auto-direction default (Tier 0) + skip-rail prototype REVERTED (2026-06-17, user-driven) ✅

> Attacking "edges drawn THROUGH unrelated boxes" (the deferred smart edge-router).
> Measured first with a THROWAWAY probe workflow (modeled on `visual-invariants.pflow.md`:
> sample every rendered edge path against every leaf-card box; count + red-highlight
> crossings) — used to take the readings below, then removed (not promoted: the metric
> it serves is for the deferred router, and it overlapped visual-invariants).

- **The reframing finding: DIRECTION dominates, not routing.** The plan-to-code harness
  drew **55% of edges through a box in LR vs 8% in TD** (same 183 edges); a clean
  workflow 0%. Predictor is DATA-EDGE DENSITY — a dense LOOPLESS workflow (changelog
  42%) is as bad as a looped one, a sparse looped one (orchestrate 13%) is fine — split
  clean at ~1.4 data/node.
- **Tier 0 — auto-direction (SHIPPED, uncommitted):** `graph/direction.ts autoDirection`
  opens a non-trivial (≥16 node) data-dense (≥1.4 data/node) workflow TD, else LR. Wired
  as a one-shot-per-workflow GraphView `useLayoutEffect` mirroring auto-collapse (frozen
  per workflow → a live-reload never re-rotates; explicit `direction=`/toolbar toggle
  wins); `viewParams.direction` went nullable (absent = AUTO, like `collapse`). Harness
  55%→8%, changelog 42%→22%, sparse workflows unchanged (re-measured with no
  `direction=`). +6 `direction.test.ts` pins; 481 web tests green.
- **Tier 1 — skip-rail pass PROTOTYPED then REVERTED (negative result, worth recording):**
  `assignSkipRails` (post-layout, reroute a box-crossing data edge into a side gutter)
  *regressed* the harness — 15→48 naive, 15→39 even after restricting to same-column
  skips with verified-clear gutters. A rail hint moves only ONE segment; the short
  approach RUNS + cross-region sprawl add as many crossings as they remove. The residual
  genuinely needs full obstacle-avoiding routing (Tier 2) — no cheap rail shortcut.
  Reverted via `git checkout HEAD --` on the 3 touched files (Tier-1 only; Tier-0 files
  untouched). At ~8% (advanced+expanded ONLY — hidden by default), Tier 2 reads as polish.
  Full reasoning + the Tier-2 risks: `visualization-requirements.md` → "Smart edge-router".
