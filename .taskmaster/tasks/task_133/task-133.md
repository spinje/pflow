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
- **Two choke points, not one.** Read side: `TraceTree.from_event_log` (reassemble tree from flat
  log) — one place, most consumers funnel through it. Write side: today **each sub-workflow gets its
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

## Trigger conditions

- **Pin D1/D2/D3 + build the span log** when: the live-overlay work begins (after static Task 155;
  alongside Task 164 / Task 125). Record it explicitly as a *liveness bet* — the disk fix alone
  would not require it.
- **Build the global blob store + GC** when: cross-run dedup is *observed* (e.g. `~/.pflow/debug`
  accumulates GB across runs that share content). Until then, per-run scope wins on simplicity +
  portability + reversibility.

## References

- **#382** — the now-work (honest model + per-run interning). The observed disk fix.
- Full session reasoning + verified findings (with `file:line`): `starting-context/braindump-storage-architecture-session.md`
- Root-cause measurement: Task 159 `BASELINE-AUDIT.md` L-8
- Related issues: #370 (typed trace contract → folds into D1), #366 (per-event `workflow_path`), #357 (cache-key vs config-hash filter asymmetry)
- Related tasks: 106 (memo cache — SQLite, `output_hash` hook), 108 (trace — "execution IS a tree", no-truncation), 155 (static GraphModel), 164 (resume), 125 (escalation/HITL)
- Key source: `src/pflow/runtime/workflow_trace.py`, `src/pflow/runtime/cache.py`, `src/pflow/runtime/engine/instrumentation.py`, `src/pflow/core/trace_tree.py`, `src/pflow/core/trace_report.py`
