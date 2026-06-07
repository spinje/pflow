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
