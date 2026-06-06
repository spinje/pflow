# Braindump: Task 155 — its real role, why it now LEADS, and what the GraphModel must actually serve (2026-06-02)

`task-155.md` is a thorough spec — read it for the *what* (two-layer architecture, GraphModel
dataclasses, `build_graph`/`render_mermaid` split, Scope reuse, load-bearing mermaid invariants,
order of work, verification). **Don't re-derive any of that.** This braindump is the tacit layer:
what changed about 155's *role and priority* during a long strategy conversation, the real driver
behind it, and the design tensions that conversation surfaced but the spec doesn't mention.

---

## The two status facts that aren't (clearly) in the spec

1. **155 is UNBLOCKED — its only hard dependency landed.** The spec says "Option X consolidation
   (branch `fix/cluster-mermaid-visualizer-fidelity`) must land before 155 starts." It HAS landed,
   on `main`: commit `b3bad44a` *"fix: consolidate mermaid ref resolution (fixes #283, #263)
   (#299)"*. `src/pflow/core/workflow/mermaid/_scope.py` exists (139 lines) — that's the `Scope`
   primitive the spec tells you to reuse. So 155 is ready to start **now**; don't go looking for an
   unlanded branch. (Minor: the package is now **6 files / ~1573 lines**, not the spec's "5 files /
   ~1500" — `_scope.py` is the sixth, added by Option X.)

2. **155 was just promoted from "medium pre-step" to "the recommended LEAD."** In this session the
   user worked through the whole build order for the "see + control the agentic harness" cluster
   and the decision landed on: **155 leads the "understand/see" track** (it's unblocked, low-risk,
   a pure refactor, and the direct path to the visual UI they want), with HITL/escalation
   (Task 125) as a parallel "control" track. So if you're picking this up, it's likely because it's
   *next*, not someday.

---

## The REAL driver (the spec frames it as architectural debt — that's not why the user cares)

The spec motivates 155 as "text-in-text-out debt / enable a second renderer." True, but that's not
the user's actual pull. The driver is **Task 163** (the plan-to-code agentic harness, a *tree* of
`.pflow.md` sub-workflows). The user, building it, said — and this is the load-bearing quote —
**"It's very hard for me as a human user to understand how this agentic workflow actually works and
I NEED to have full control."** They want to **SEE** it: *"a visual UI that users can SEE how a
workflow looks like, what inputs that leads to what nodes etc, clicking to read prompts,
descriptions etc, run in a react server locally on demand using something like react flow."*

So 155 is not abstract renderer-plumbing to them — it's **the substrate for a specific
react-flow UI** that lets them comprehend a complex multi-file agentic graph. That reframes two
things below.

---

## The "two substrates" frame — the single most important architectural context

This conversation crystallized that the whole "see + control" vision rests on **two independent
substrates**, and 155 is exactly one of them:

- **Substrate 1 — GraphModel + static structure (THIS task, 155).** IR → GraphModel. **Zero runtime
  data.** "What the workflow *looks like*."
- **Substrate 2 — a streamable, span-shaped runtime event log** (being designed RIGHT NOW in a
  separate trace/cache-storage redesign thread — content-addressed blobs + per-run interning +
  streamable spans). "What a given *run did*."

They are **independent** and **converge only at the UI**: 155 *draws* the graph; the event log
*animates* it (which node ran, its output, the branch taken). **Neither depends on the other.**

> **The load-bearing constraint this puts on you:** keep the GraphModel **purely static/structural**.
> The spec already says "no mermaid syntax in the model." Add to that: **no runtime concerns either**
> (no execution status, no outputs, no timing). Those belong to Substrate 2. If you bake runtime
> into the GraphModel you re-entangle the two substrates the whole architecture keeps separate.
> Do NOT try to unify 155 with the storage/trace thread — they're deliberately orthogonal.

---

## What this means for the GraphModel design (the spec's sketch is necessary but not sufficient for the user's actual goal)

> **Update (this session):** the reasoning in this section predates the spec rewrite. It is now
> *settled, not open* — the rewritten `task-155.md` **requires** the per-node source back-ref
> (description / prompt-ref / params) and an `annotations` slot. Read the below for *why* those
> matter, not as a gap still to close.

The spec's verification says "write a throwaway ~20-line React Flow sketch to confirm the model is
sufficient." **Take that far more seriously than "a formality to prove a second renderer is
possible."** Because the user's actual target IS a React Flow UI, the sketch is a real design check:
*does the GraphModel carry what a click-to-read-prompts UI needs?*

The spec's node-record sketch (`id/kind/shape/label/purpose/batch_suffix/parent_subgraph_id`) is
tuned for *mermaid*. The user's UI also needs, per node: the **description**, the **prompt
content (or a ref to it)**, and the **params/inputs** — so a user can click a node and read its
prompt. Mermaid doesn't need those, so they're easy to omit and then discover missing when the UI
task starts.

- **CONSIDER:** design `build_graph`'s per-node record so the UI task can ADD those fields
  (description, prompt-ref, params) **without re-walking the IR** — e.g. carry the source `node_id`
  so a renderer can look params up from the IR, or include an extensible per-node `meta`. The point
  of 155 is "the IR walk happens once"; if the UI later has to re-walk the IR to get prompts, 155
  failed its own thesis.
- **Hold the line on scope, though** *(updated this session)*: mermaid parity is a regression
  **tripwire, not a frozen contract** — if the correct model shifts a golden, investigate and
  regenerate (rewritten `task-155.md` → Verification); don't contort the model to preserve
  byte-parity. And the seam decision moved: 155 now **carries the per-node source back-ref
  (click-to-read) and an `annotations` slot as requirements** — no longer deferred to the UI task
  (verified cheap). Still deferred: rich UI-only rendering and the analysis layer (ADR-0004). The
  discipline still holds — extract the GraphModel, don't over-build — the line just moved.

---

## Use the Task 163 harness as a real test subject (not just `deep-research`)

The spec's canonical test workflow is `examples/nested/deep-research/`. Keep that for golden parity.
But the user's *actual* comprehension target is the 163 harness:
`examples/agent-orchestration/plan-to-code/run-from-plan.pflow.md` → `execute-plan` →
`implement-chunk` + prompts (a real, deep tree of sub-workflows with loops and batch). **Render that
through your GraphModel + sketch** as the real-world check that the model captures what the user
needs to *understand the thing they're actually struggling with*. If the GraphModel + a react-flow
sketch make that harness legible (structure, input→node wiring, clickable prompts), 155 has served
its true purpose. (`pflow visualize <wf> --depth 5 --descriptions` renders it as Mermaid **today** —
that's the $0 baseline; 155 → UI is the interactive, multi-renderer upgrade of exactly that.)

---

## User's working style (consistent all session — matters for whoever picks this up)

- **Reasons from PROPERTIES, not categories.** "agentic"/"batch is a strength" reasoning loses; "is
  this static or runtime? pure or side-effecting? relational or intrinsic?" wins.
- **"why is X?" / "won't this be the same?" is a CATCH, not a question.** This session they caught me
  (a) claiming claude-code nodes are opaque black boxes — wrong, the `.jsonl` transcript is on disk;
  (b) over-selling a `pflow watch` command as solving a pain the streamed CLI already solves;
  (c) over-rotating to a "global content-addressed store" when per-run interning was the right,
  simpler call. Each time: **verify, concede, don't defend.** They were right every time.
- **Wants claims VERIFIED before they're written** (file:line). They explicitly asked me to run
  codebase searches before editing specs. Don't assert about the mermaid internals without checking.
- **"Prioritize simplicity of the FINAL code; what would the top 10% of similar codebases do;
  elegance must be earned."** They will reject clever/elegant if it's unearned standing complexity.
  For 155 this cuts toward: the GraphModel should be plain dataclasses that obviously map to both
  mermaid and react-flow — if the model needs a clever abstraction to be "reusable," it's wrong.
- **Prove the cheap path first.** The static Mermaid view exists today; 155's value is the *reusable
  substrate*, so frame/justify it as "make the IR-walk reusable," not "build viz from scratch."

---

## Assumptions & uncertainties

- **RESOLVED (this session): the GraphModel carries enough for click-to-read.** Verified the IR
  already holds it — `purpose` (description), `params` (incl. `prompt`), and
  `_source_files`/`_source_lines`/`_source_line` (the on-disk origin) — and synthetic (expanded/batch)
  nodes are reachable at build time. The rewritten `task-155.md` now **requires** the per-node source
  back-ref (populated, not just a seam); statically-unresolvable `${template}` refs render opaque.
- **ASSUMPTION: the UI is genuinely coming** (the user committed to the runtime substrate this
  session and has stated the UI intent repeatedly). 155's "do the full refactor not the Scope-only
  consolidation" bet (in the spec's Design Decisions) rests on the UI being real. It is. Don't
  second-guess and ship a half-refactor.
- **UNCLEAR: who files the web-UI task and what it depends on.** It's still unfiled. It needs BOTH
  substrates: GraphModel (155) for structure + the streamable event log (storage thread) for the
  live overlay. Whoever files it should reference both.

## Unexplored territory

- **UNEXPLORED: how the react-flow UI reads the GraphModel at runtime.** The user said "run in a
  react server locally on demand." The likely shape: a `pflow ui`/`--serve` command emits
  `dataclasses.asdict(GraphModel)` as JSON; a local React app renders it. 155 should make sure the
  GraphModel is cleanly `asdict`-able (the spec says "no new deps; `dataclasses.asdict` + `json.dumps`
  for any future payload" — honor that literally; no non-serializable fields).
- **RESOLVED (this session, ADR-0003): node identity is structural, not the mermaid convention.**
  Verified (searcher B) that mermaid's flat IDs do **not** match the runtime/trace IDs — the runtime
  is structural (bare `node_id` + ancestry + batch index). So the GraphModel adopts the **runtime's
  structural identity** `(node_id, ancestor_path, batch_index?)` and renderers *derive* their flat IDs.
  That is exactly what lets the live overlay join runtime events onto static nodes later — the goal
  this bullet flagged, now achieved structurally (NOT by keeping the mermaid convention in the model).
- **CONSIDER: sub-workflow expansion depth in the UI.** Mermaid uses `--depth`. The 163 harness is a
  deep tree; the UI will want collapse/expand interactivity. The GraphModel already encodes nesting
  (`parent_subgraph_id`, `nesting_depth`) — make sure that's rich enough for a UI to collapse/expand
  per-subgraph, which mermaid renders statically but a UI does interactively.

## Open threads

- **155 leads; escalation (Task 125, blocking slice) is the parallel track.** They don't block each
  other. The storage/trace redesign (Substrate 2) is in flight in another thread; the user committed
  to building the streamable span-model event log there.
- **File the web-UI task** (depends on GraphModel + event log). Not done.
- **DONE (this session):** 155 is now scoped — `task-155.md` was rewritten to current truth
  (structural identity, loop field, Container, click-to-read, primitive-only Non-Goals), with ADR-0003
  and ADR-0004 recording the load-bearing decisions. Next artifact is the implementation plan.

## Relevant files & references

- `task-155.md` — the spec (authoritative; don't re-derive).
- `src/pflow/core/workflow/mermaid/` — the package to refactor; `_scope.py` (139L) is the landed
  `Scope` primitive; `CLAUDE.md` there has the file map + load-bearing invariants.
- `b3bad44a` — the commit that landed Option X (your unblock).
- `examples/agent-orchestration/plan-to-code/` — the 163 harness; the user's REAL comprehension
  target; use it as a test subject for the GraphModel + react-flow sketch.
- `.taskmaster/tasks/task_125/` — the parallel "control" track (HITL/escalation); its
  `braindump-escalation-and-resume-substrate.md` has the full "two-substrates / see+control" context
  this braindump summarizes from 155's angle.
- The trace/cache storage thread (Substrate 2) — no task file I can point to yet; it's the live
  redesign producing the streamable span-model event log the UI's live overlay will consume.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points — especially (1) 155 is unblocked
> (Option X landed) and was promoted to lead; (2) the GraphModel must stay PURELY static —
> runtime/live data is a separate substrate (the storage thread's event log), and the two converge
> only at the UI; (3) the real driver is a react-flow UI to comprehend the Task 163 harness, so the
> throwaway sketch is a genuine design check and the model **carries** (not just seams) a per-node
> source back-ref for description/prompt/params — parity is a **tripwire**, not byte-identical; (4)
> node identity is **structural** (ADR-0003) so the live overlay can join runtime events later — then
> state you're ready to proceed.
