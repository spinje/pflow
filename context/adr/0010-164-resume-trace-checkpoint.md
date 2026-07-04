# Resume restores from the debug trace (not a dedicated snapshot store), and a resumed run is a new immutable attempt linked by `resumed_from`

## Status

accepted (2026-07-03)

Resume-from-failure (Task 164) needs two things the codebase can already provide: a **checkpoint**
to restore completed-node outputs from, and a **run identity** for the resumed attempt. Decision:
resume reuses the **debug trace** as its checkpoint — the same source `--only` uses (ADR-0002) — and
a resumed attempt is a **new trace with a new `execution_id` carrying `resumed_from: <source id>`**,
never an append to the source. The engine re-enters the graph walk at the failed node K by seeding
upstream from the trace (`seed_snapshot_into_shared(exclude=K)`), then follows `route_action` to the
end — the "resume-and-continue" half of the `--only` snapshot machinery. Canonical detail lives in
`task-164.md` ("Run lineage (attempt chains)", "Reuse", Decision 5); this ADR records the two
load-bearing calls durably.

**Amended 2026-07-03 (plan session): attempt traces are self-contained.** A resumed attempt
re-records each restored upstream node's final event (copied from the source trace) into its own
trace at seed time, marked `restored` with zero cost — the same shape as `cached` events. Without
this, an attempt trace holds only K-onward events, which breaks resume-of-a-resume (the newest
attempt — the mandated resume target — has no upstream outputs to seed) and silently poisons later
`--only` runs (a successful attempt becomes the newest `success` trace, the snapshot loader selects
it, and upstream references fail to resolve). `resumed_from` stays pure lineage — never a data
dependency a reader must follow.

**Amended 2026-07-04 (Phase-5 review): entry K is the ROOT of the terminal failure region, not the
last unrecovered node.** Resume must choose ONE step to re-enter at (K). The rule: **the earliest
failed step with no successful/cached step after it in event order** — the "frontier" of what
actually completed. This is Temporal's replay-frontier idea reduced to a one-pass scan of the trace
(pflow re-enters at K and lets `route_action` re-derive the path forward, the same way Airflow
re-evaluates trigger rules on a cleared task). Two behaviours this pins, both Decision 9's intent:
- A `K --on-error--> F` chain where BOTH fail resumes at **K** (the primary), NOT F (the fallback
  that stopped the run). Re-running K re-evaluates its branch, so a fixed K follows its SUCCESS edge
  and F never runs. The earlier `_unrecovered_failed_node_ids`-only selection resumed at F because
  routing tags the recovered primary K as "recovered" and filtered it out — the frontier rule
  decouples entry selection from that set (which now only answers "real failure vs. gate stop").
- A failure whose recovery genuinely **succeeded** (a success sits after it) is NOT re-run — the
  later, separate failure is K. This is strictly more precise than Airflow's "re-run every failed
  task," which would wastefully re-do the recovered branch.

**Known sharp edge (may bite; needs care in follow-ups):** at-least-once (Decision 4) still applies
to the whole K-onward tail — resuming a both-fail chain at the primary means that if the primary
still fails, the fallback F runs AGAIN (a second at-least-once firing of F's side effects across
attempts, on top of K's). The confirm/`--force` policy gates K's type, but does NOT separately
warn that a downstream on-error fallback may also re-fire. Acceptable for v1 (resume is at-least-once
by construction and F already fired once), but a durable-resume / compensation feature (Task 171+)
that wants exactly-once or saga-style rollback must revisit this — the frontier rule chooses the
re-entry point, it does not bound how many side-effecting steps the resumed tail may re-run.

**Amended 2026-07-04 (post-implementation review, two proven-bug fixes):**

1. **Seed fidelity: failed events are never seeded.** `seed_snapshot_into_shared` reconstructs
   the shared store AS IT EXISTED in the source run — a node whose final event is `failed` had
   its data in `__failures__`, never the store, so seeding it resolves coalesce paths
   (`${primary.x ?? fallback.x}`) that the original run resolved to the fallback (proven: a
   resumed tail silently computed the failed primary's empty output). The filter lives at the
   single seam, so it also fixes the identical latent divergence in `--only` against a DEGRADED
   snapshot, and it narrows Decision 6's re-record scope for free: a failed-recovered upstream
   node is neither seeded, listed as restored, nor re-recorded — the attempt trace no longer
   flips it to cached-success.
2. **Incomplete tails ending in a failure re-enter at the terminal-failure root** — the same
   frontier rule as the failed arm (extracted as `_terminal_failure_root`; it needs no warnings
   data, which an interrupted trace's missing trailer could never supply). The between-nodes
   single-default-successor resolution applies ONLY to success-ending tails: a failed last
   node's taken route may have been its ERROR edge, so its default successor is provably the
   wrong branch (proven: a kill between a recovered failure and its handler resumed past the
   handler; a kill after an unrecovered failure resumed past the failure). Decision 7's intent —
   never a wrong-branch guess — is preserved; strictly more tails become resumable instead of
   wrong.

## Considered options

- **Dedicated snapshot store (ADR-0002's reserved escape hatch)** — rejected. ADR-0002 built
  `--only` on the trace but reserved a purpose-built store "if the trace coupling ever bites,"
  and flagged resume-as-reliability-feature as the likely trigger. It does **not** bite: the one
  documented lossy case (binary → `"<binary data: N bytes>"` placeholder) does not occur in normal
  flows — the binary-producing nodes (`read-file`/`http`/`shell`) base64-encode to a `str` **before**
  the shared-store write, and strings round-trip losslessly through the trace blob mechanism
  (verified 2026-07-03). The only genuine-`bytes` vector is a `code`/python node returning raw bytes,
  handled by a **loud fidelity guard** (refuse-with-actionable-error at seed time), not a second
  persistence subsystem. A whole new store (schema, write-every-run, lifecycle) for a sub-1% edge
  case fails the deletion test.
- **Append the resumed run to the source trace (one file per logical execution)** — rejected, and
  impossible by construction: content after a `run.complete` line is treated as corruption (a
  verified reader invariant, `core/trace_io.py`). A new trace + `resumed_from` back-pointer is the
  only shape the on-disk format permits.
- **Chain-union at read time (attempt traces hold only K-onward events; readers walk
  `resumed_from` links and union events)** — rejected. Chain-awareness would spread into every
  snapshot consumer (`load_full_run_events` for `--only`, the resume loader, report/UI joins);
  self-contained traces keep all readers unchanged for the cost of one writer-side mechanism.
- **Exclude resumed traces from snapshot sources (the `--only`-trace treatment)** — rejected.
  `--only` would silently ignore the newest real run, and the resume loader would still need the
  union logic for resume-of-a-resume.
- **Mutable checkpoint file updated in place** — rejected. Immutable attempts give free lineage,
  a natural "newest attempt = the one to resume," and no write-contention with a still-running
  producer (a pre-resume advisory-flock liveness probe rejects resuming a live run). Mirrors
  Temporal's workflow-id/run-id split and n8n's retries-point-at-parent.

## Consequences

- **The trace is now load-bearing for two core features, not one.** `--no-trace` / MCP in-memory
  runs write no trace and are therefore unresumable — surfaced as a hard error, never a silent
  re-run (same posture ADR-0002 set for `--only`).
- **UI/report consumers must join attempt chains via `resumed_from`** or one logical execution
  renders as several disconnected runs (flagged for the Task 173 overlay).
- **CLI surface is `pflow resume [<workflow>|<execution-id>]`** — one subcommand serves both the
  failure-resume path (this task) and 171's paused-gate resume, consistent with ADR-0009's already
  committed `pflow resume <execution-id>` approval verb. (A `pflow <wf>` → `pflow run <wf>` rename
  is under separate consideration and would make `run`/`resume` sibling verbs; out of 164 scope.)
- **Restored events must not double-count.** Re-recorded upstream events carry zero cost and are
  excluded from `nodes_executed`/cost aggregates (mirroring `cached`); the chain join via
  `resumed_from` is where true whole-execution cost lives.
- **At-least-once semantics for node K.** Restoring upstream but re-running K means K's side effects
  can re-fire; the side-effect-taxonomy-keyed confirm/`--force` policy (Decision 4) governs when
  the user must acknowledge it. Idempotent K (`llm`) resumes silently.

## References

- ADR-0002 (`--only` reuses the trace, not the memo cache; the reserved dedicated-store escape hatch
  this ADR declines). ADR-0009 (approval surfaces / the `pflow resume` verb). ADR-0001 (loop engine
  re-entry — the walk-loop re-entry precedent).
- Tasks: 164 (this — the checkpoint→restore→continue substrate), 125 (gate primitive built on the
  same conceptual substrate), 171 (durable pause/token — second consumer of resume, `paused` as the
  second terminal status alongside `failed`).
- Canonical spec text: `task-164.md` "Run lineage (attempt chains)", "Reuse: what already exists",
  Decisions ledger.
