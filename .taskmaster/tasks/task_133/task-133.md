# Task 133: Trace/Cache Storage Architecture

## Description

Architecture decision record for how pflow stores execution data: how node outputs, prompts, and events are stored across the trace and cache subsystems, why they stay separate, and where each stream of future work lives. The original premise — merging trace and cache into one content-addressed per-node store — was rejected; see "What this task is now" and the Decision below.

## Status

in progress

## Priority

low (the observed disk pain is owned by #382; the remainder is gated behind the live-UI line)

## What this task is now

It previously read *"Unified Per-Node Storage for Trace and Cache"* and proposed one
content-addressed per-node store (`~/.pflow/store/{content_hash}.json`) with the trace as a
generated artifact. That premise is rejected (see **Decision** below). Task 133 is now the
**trace/cache storage architecture decision record**: how execution data (node outputs, prompts,
events) is stored across the trace and cache subsystems, why they stay separate, and where each
piece of future work lives.

## In scope

- The decision and its rationale (why the merge was rejected; the converged model).
- Governing/indexing the three implementation streams:
  - **Now → #382** — honest event model + per-run content interning *on the current tree*. Solves
    the observed 100MB disk pain. No span/streaming commitment. *(Implementation lives in #382.)*
  - **Deferred → streamable span-model event log** (D1/D2/D3 below) — the liveness foundation for
    the live UI overlay. Gated behind static **Task 155** + the live-overlay work. This task holds
    the *design*; the *implementation* spawns later and cites this task.
  - **Far-future → global content-addressed blob store + GC** — gated on *observed* cross-run
    dedup need.

## Out of scope

- Implementing the disk fix (#382).
- Building the live UI (Task 155 static GraphModel; Task 164 resume; Task 125 escalation/HITL).
- The span-log implementation itself (spawns from the live-overlay work; cites this task).

---

## Decision: the trace↔cache merge is rejected

**The original premise does not address the observed problem.** The user's pain is a 100MB+ trace
file. The trace↔cache overlap is only **~3MB of the ~100MB** — merging the stores would remove the
*smallest* cost center. The 100MB is **within-trace** duplication (one prompt stored up to 4× per
event; the same system prompt across hundreds of calls), measured at **53MB → ~12MB** once
duplicated text is stripped (Task 159 BASELINE-AUDIT L-8).

Further, the two subsystems have genuinely different shapes and should stay separate:

| | Trace | Cache (memoization) |
|---|---|---|
| Access pattern | sequential, run-scoped read | random keyed lookup (`hash(config+inputs)`) |
| Lifecycle | accumulates for debugging; delete freely | current-state; TTL-evicted (24h) |
| Substrate | per-run JSON in `~/.pflow/debug/` | one SQLite DB `~/.pflow/cache/cache.db` (zlib BLOBs) |

A log cannot answer an O(1) point lookup; an index cannot serve a tailable stream. The only thing
they legitimately share is **content** (the node-output blob). Globally sharing that blob across
both stores would **re-couple** the lifecycles 106/108 deliberately separated (a blob referenced by
both a TTL cache row and a deletable trace has the *union* lifecycle → a global GC problem) while
buying only the ~3MB cross-system win.

> The spec's `~/.pflow/store/{content_hash}.json` file-store idea was the Task 106 *braindump's
> abandoned leaning* ("leaning toward files"), overridden by the SQLite decision before 106 shipped.
> It appears nowhere in `src/`. Trust order: shipped code + 106 decision > the not-started 133 spec.

## Converged architecture: share content within a run, not stores

- **Per-run interning** — within a single run/trace, store each unique large blob **once**, by
  content hash; everything references it. Kills the *dominant* within-run duplication. Self-contained
  (delete the trace → blobs go with it), portable, trivial GC. → **#382, now.**
- **Trace** = (eventually) a streamable, span-shaped, append-only event log referencing per-run
  blobs. → deferred (D1/D2/D3).
- **Cache** = a keyed index keeping its **own** (already-compressed, ~3MB) copy. Unchanged. We
  *accept* the ~3MB cross-system duplication in exchange for fully decoupled lifecycles and zero
  cross-subsystem GC.

The cache schema already carries an `output_hash` column (added "reserved for future trace
unification (Task 133)"). It is the **cache's own** content hash — keep it, but it is **not**
evidence for merging the stores; do not treat it as a mandate.

---

## Deferred span-model design (D1/D2/D3) — NOT YET PINNED

Pin these only when the live-overlay work starts. The single load-bearing, expensive-to-retrofit
decision is **the event model must be streamable (span-shaped) from the start** — everything else is
incremental and reversible. **The disk fix (#382) needs none of this.**

**D1 — span granularity / event taxonomy (the real spec work).** Define the atomic span and its
correlation fields (`event_id` / `parent_id` / `run_id` / `seq`). Decisions: loop re-execution →
new span (≈free, events are per-visit today); batch items → child spans; LLM calls → child spans;
**node/LLM internal `max_retries` retries → currently untraced; making them sub-span "attempts" is
NEW emit points, not free — be precise about which "retry" is meant**; nested sub-workflows →
`parent_id` chaining across the workflow boundary. *Recommendation:* per-execution span, batch-items
and LLM-calls as child spans, retries as attempts within a span.
- **Two choke points, not one.** Read side: `TraceTree.from_dict` (today reads *already-nested*
  structure; flat-log reassembly is the future change — see "verified foundation" below) — one
  place, most consumers funnel through it. *(Corrected 2026-06-07: `from_event_log` does not exist
  in code; the real reassembly entry point is `from_dict`.)* Write side: today **each sub-workflow gets its
  own collector** (save/restored around `engine.run`, propagated via `__trace_collector__`);
  one-log-per-run means unifying that into span-context correlation — a collector + `WorkflowExecutor`
  change, not just a format change.

**D2 — run-level aggregates can't be a header.** `final_status`, `llm_summary`, `nodes_executed`,
`failed_node_ids` are unknown at stream start. *Recommendation:* a trailer `run_complete` event
carries them; readers compute partial aggregates from events when the trailer is absent (crash).
This **is Task 164's failure discriminator for free**: trailer present + `failed` = graceful,
resumable; trailer absent = hard crash, not resumable.

**D3 — interning + liveness ordering, and global `seq`.** Emit blob content at **first occurrence,
in stream order** (don't hoist the blob table to a trailer). This makes refs **backward-only**, so a
forward live tailer never hits an undefined ref *and* any crash-truncated log is self-consistent
(post-crash reader = live tailer). Liveness forces one tailable stream → serialized appends → a
**single lock around (assign seq, append, flush)** yields global monotonic `seq` for free; per-writer
buffers fragment the stream and are out. Single-process/multi-thread only (batch parallelism is
`ThreadPoolExecutor`, not subprocesses), so a lock suffices — promote to a queue + writer-thread only
if contention is *observed*. The writer must flush frequently or a crash loses the tail.

**The one contract point.** When D1 is pinned, write it **once, in one place that all consumers
cite** — trace, cache, live-UI overlay, Task 164 (resume keys on node/span IDs), Task 125
(escalation events). A five-consumer schema each thread re-infers is the textbook source of the
post-merge integration bugs this codebase guards against. This subsumes **#370** (typed trace
contract).

---

## D1/D2/D3 — verified foundation, trust boundary & spikes (2026-06-07)

A verification session pinned the current-state facts this deferred design rests on (against code +
the OpenTelemetry spec) and the roadmap that now justifies it. **Roadmap (author, 2026-06-07):
initial UI (React Flow over Task 155's `GraphModel`) → this task (the event stream) → live execution
overlay (possibly HITL / Task 125 first).** The live overlay is therefore the *next real consumer*
after this task — which turns the unified "one event source, many renderers" model from a
hypothetical seam into an earned one. **Build at this task, after the initial UI. The build STARTS
with the spikes below, not the schema.**

This section is a *design with a verified foundation + a gated spike list* — **NOT a ready-to-code
spec.** It refines (does not replace) D1/D2/D3 above.

### Trust boundary

**Verified (against code / OTel spec):**
- Current trace: **no per-event IDs** (only a per-run `execution_id`); **no `parent_id`** (nesting is
  structural embedding via `batch_items`/`sub_workflow_events`); file written **once at end** (no
  tailable file today). `trace_io.intern_blobs` writes blobs as a **trailer** (last key), str-only,
  skips `__`-keys.
- Per-event time: **one** naive-local `datetime.now().isoformat()` stamped at record (≈end) time;
  `duration_ms` via `perf_counter`. **Batch-item and warmup events carry no timestamp and no
  `node_id`** (keyed by `index`; `-1` = warmup sentinel) — a genuinely different event shape.
- Progress callback (`create_progress_callback`) is a **separate, structured, loosely-coupled** live
  channel firing at node *start* / batch-item / *completion* — distinct sink (`__progress_callback__`)
  from the trace collector (`__trace_collector__`), no shared emission point.
- OTel: spans export **on end only** (`OnStart` is a no-op for the standard processors); **no
  in-progress export** → OTLP cannot feed a live overlay. **No standard cost attribute**
  (`gen_ai.usage.*` standardizes only token counts, incl. cache + reasoning).

**Forced (entailed by the above — safe to commit):**
- Append-only ⇒ cannot embed ⇒ nesting **must** be by `parent_id` reference (replaces today's
  embedding).
- Live tailing ⇒ blobs **must** be inline first-occurrence (define-before-use), **not** the current
  trailer. This is exactly D3's prescription — verified the current code is the *opposite* and must
  change (`trace_io.resolve_blobs` already carries a TODO for the JSONL reader).
- Run aggregates unknown at start ⇒ **must** be the D2 `run.complete` trailer.
- Overlay needs a node-**start** signal and a stable per-event **id** ⇒ both must be synthesized
  (today absent).
- Overlay cannot be fed from OTLP ⇒ pflow's own stream is the live source of truth; OTel is at most a
  post-hoc projection.

**Needs proving (spike before committing — do NOT treat as settled):**
1. **Migration blast radius (HIGH).** Every current reader breaks on a format change:
   `TraceTree.from_dict`, `trace_report`, `metrics`, `analyze-cache`, `--only` snapshot restore,
   `report`. The full reader set + migration cost were NOT mapped this session.
2. **Unify-vs-parallel + concurrency reconciliation (HIGH).** Folding the progress channel and trace
   into one emission means reconciling **two concurrency-buffering models** (per-worker progress
   buffer vs the `shared["_batch_trace"]` accumulator). Assessed "moderate cost," not measured.
   Fallback if expensive: keep two channels, share only the event *schema*.
3. **Per-node append+flush performance (MED-HIGH).** D3's single-lock-around-(seq, append, flush)
   under batch `ThreadPoolExecutor` is an assumption, unmeasured.
4. **Overlay/HITL actual data needs (MED).** Is the progress callback's payload sufficient, or does
   the overlay need resolved inputs/outputs (which live in the trace, not the callback)? Resolves as
   the UI work begins.
5. **OTel export round-trips as a rename (LOW).** Never prototyped — the "export is cheap later"
   claim is unproven. (Not building it; field-name alignment only.)

### Refinements to D1/D2/D3 (verification corrections)
- **D1 read-side name was wrong:** `TraceTree.from_dict`, not `from_event_log` (no such method).
  Today it reads *already-nested* structure; flat-log reassembly is the future change.
- **D1 "batch items → child spans" needs promotion:** today batch items are degenerate (no `node_id`,
  no timestamp). The redesign must promote them to first-class events with real
  `id`/`parent_id`/timestamps.
- **D1 "loop → new span (per-visit)" confirmed:** events are per-visit today; `final_events_by_node`
  (last-occurrence) is the current collapse rule.
- **D3 confirmed against code:** current interning is a trailer (opposite of D3) — D3's
  first-occurrence prescription stands and requires the change `trace_io` already flags.

### Proposed event schema (the one contract point; pin *after* spikes pass)
One typed event per JSONL line; nesting by `parent_id`; OTel-aligned names so a future export is a
rename (**not** an exporter — build only when a second real consumer appears):
- **Identity/correlation:** `id` (↔ span_id), `parent_id` (↔ parent_span_id), `run_id` (↔ trace_id),
  `seq` (monotonic).
- **Lifecycle:** `kind` (`run.start` / `node` / `llm` / `blob` / `run.complete` / a HITL-escalation
  kind for Task 125), `start`, `end`, `status`.
- **Payload:** kind-specific (node: node_id/type/resolved-io/mutations; llm: `gen_ai.usage.*` token
  names + `cost_usd`; blob: hash + bytes).
- **Consumers are *renderers* of this one stream:** durable JSONL writer, stderr progress display,
  live overlay, (future) OTel export. **Whether the existing progress callback folds into this
  emission or stays parallel is spike #2's outcome, not pre-decided.**

### Cross-cutting insights (carry these; they cost hours to re-derive)
- **Two jobs, two substrates.** Live overlay ← pflow's own event stream; post-hoc / ecosystem ← OTel
  export. Never conflate.
- **Borrow the data model, not the wire envelope.** Align correlation fields with OTel / `gen_ai`;
  keep clean flat pflow JSONL. OTLP's `resourceSpans` envelope would import complexity and hurt
  agent-readability.
- **OTel-liveness reality.** OTel is live for *metrics/logs*; *traces* are completion-reported —
  pflow's long-running nodes are exactly where that gap bites. Don't expect OTLP to carry liveness.

### Prereq
- **Issue #492** (`input_tokens` semantics: LLMNode cache-inclusive vs ClaudeCode uncached) should
  land first, so the unified `llm` event carries consistent token semantics. Cost (`cost_usd`) is
  unaffected by that bug. (✅ this was just merged to main)

---

## Trigger conditions

- **Pin D1/D2/D3 + build the span log** when: the live-overlay work begins (after static Task 155;
  alongside Task 164 / Task 125). Record it explicitly as a *liveness bet* — the disk fix alone
  would not require it.
  - *2026-06-07 roadmap:* sequence is **initial UI → this task → live execution (possibly HITL
    first)**. The overlay is the next consumer, so the design is grounded (see "verified foundation,
    trust boundary & spikes") and gated on spikes #1–3 — not on further design. Build still starts
    with the spikes, not the schema.
- **Build the global blob store + GC** when: cross-run dedup is *observed* (e.g. `~/.pflow/debug`
  accumulates GB across runs that share content). Until then, per-run scope wins on simplicity +
  portability + reversibility.

## References

- **#382** — the now-work (honest model + per-run interning). The observed disk fix.
- Full session reasoning + verified findings (with `file:line`): `starting-context/braindump-storage-architecture-session.md`
- Root-cause measurement: Task 159 `BASELINE-AUDIT.md` L-8
- Related issues: #370 (typed trace contract → folds into D1), #366 (per-event `workflow_path`), #357 (cache-key vs config-hash filter asymmetry), #492 (`input_tokens` semantics inconsistency — prereq for the unified `llm` event)
- Related tasks: 106 (memo cache — SQLite, `output_hash` hook), 108 (trace — "execution IS a tree", no-truncation), 155 (static GraphModel), 164 (resume), 125 (escalation/HITL)
- Key source: `src/pflow/runtime/workflow_trace.py`, `src/pflow/runtime/cache.py`, `src/pflow/runtime/engine/instrumentation.py`, `src/pflow/core/trace_tree.py`, `src/pflow/core/trace_report.py`
