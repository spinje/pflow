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
