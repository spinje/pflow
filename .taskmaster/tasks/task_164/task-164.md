# Task 164: Resume Workflow From a Failed Node

## Description
Add the ability to resume a failed workflow run from the node that failed — restoring
the outputs of already-completed upstream nodes from disk and continuing execution from
the failed node onward — instead of re-running the whole workflow from scratch.

## Status
not started

## Priority
medium

## Problem
A workflow that fails partway (an `llm`/`http`/`mcp`/`claude-code` node times out, a
transient API error survives the in-process retries) can only be re-run from the
beginning today. For a long, expensive, multi-stage run — e.g. the Task 163 plan-to-code
harness, where a single run is many minutes and several dollars — losing stage 5 means
re-paying for stages 1-4. There is no resume.

## Solution
`pflow <workflow> --resume` (surface TBD; see CLI Surface) restores the completed-node
outputs from the failed run's trace and **re-enters the graph walk at the failed node K,
following successors to the end** — the missing "resume-and-continue" half of the existing
`--only` snapshot machinery.

## Relationship to Task 125 (shared substrate)
Task 125 (HITL gates) and this task are the **same primitive under different triggers**:
checkpoint → restore → continue. See task-125.md "Architecture". The division of labour:
- **Task 125 blocking gates** need NO substrate (verified: in-TTY in-place pause works) → independent, built first.
- **THIS task builds the checkpoint→restore→continue substrate** — it is the general,
  HITL-free exercise of it.
- **Task 125 durable resume + non-TTY gates** then reuse this substrate as a thin trigger
  (stop-at-a-gate instead of stop-at-a-failure).
Build order: 125-blocking → 164 (this) → 125-durable.

## Reuse: what already exists (verified 2026-06)
The reconstruction half ships, tested, via `--only` (issue #443):
- `seed_snapshot_into_shared(shared, events, exclude=K)` (`workflow_trace.py:347`) — rebuilds
  shared store from a prior trace, scoped to nodes that ran *before* K. Exactly the seeding a
  resume needs.
- The **dry-run planner already composes "seed → start at K → follow successors"**
  (`execution/plan.py:_resolve_walk_start` 486-530 + walk 319-360) — proof the pattern works
  against the real compiled graph; it only withholds execution.
- The walk loop is start-node-agnostic: only `curr = workflow.start_node` (`engine.py:435`)
  hardcodes the entry; `find_node_by_id` returns any K.
- Failed runs DO persist a trace (`final_status:"failed"` + `failed_node_ids`, saved in the
  CLI `finally` at `cli/commands/run.py:294-298`).

## The delta (new work — moderate, leaning small)
1. A resume entry point: `_run_only_snapshot`'s seeding prologue (`engine.py:519-530`) but
   enter the walk loop at `curr = find_node_by_id(start, K)` instead of early-returning.
2. Reset `node_visit_counts` before the walk (`engine.py:431-432`).
3. Do NOT set `__execution__["only_node"]` on the resume path (so outputs route across the
   resumed tail, not just K).
4. A **resume-scoped snapshot loader** that ACCEPTS a `failed` trace (today
   `load_full_run_events`, `workflow_trace.py:179-188`, rejects it) and identifies K as the
   failed node.
5. Refine `restored_nodes` to mean "seeded AND not visited this run" — derive post-walk from
   `node_visit_counts` (`execution_state.py:144-145` is the one display-contract touchpoint).

## Known Hard Problems
- **Node-K idempotency (the core problem).** K may have *partially* side-effected before
  failing (an http POST that sent but timed out on the response, an mcp tool that created a
  resource, a claude-code node that already committed). Re-running double-fires. Reuse the
  existing side-effect taxonomy: `_default_cache_for_node_type` already classifies which
  node types side-effect (only `llm` caches by default) — same classification tells you which
  K is resume-safe vs. needs a guard/confirm. Recommended phasing: prove the substrate on an
  *idempotent* K first (an `llm` timeout — re-run is safe), then layer idempotency handling
  for side-effecting K.
- **Conditional-branch divergence.** A resumed run may take a different branch than the
  snapshot did; downstream nodes run fresh, but verify branch-dependent state resolves
  correctly (Searcher B's flagged verification target).
- **Hard kill ≠ graceful failure.** A SIGKILL / `KeyboardInterrupt` does NOT persist a trace
  (save is in the CLI `finally`). Scope this feature to graceful failures (node raised/timed
  out, run completed as FAILED).
- **Nested / sub-workflow resume is OUT of scope (v1).** Dotted `--only parent.child` is
  rejected on every live path today; the child plumbing (`_pflow_child_only_node`) exists but
  is dormant (#443). Resuming *into* a sub-workflow is a deferred follow-up. v1 resumes only
  at top-level node K.
- **Lossy serialization.** Trace uses `json.dump(..., default=str)` (`workflow_trace.py:850`)
  — non-JSON-native values resurrect as `str()`. Either ensure resumable shared values are
  JSON-native or harden serialization. Shared with Task 125.

## CLI Surface (open — coordinate with Task 125)
`pflow resume` is a name Task 125 also wants (for resuming a paused gate). Decide whether one
`pflow resume` serves both "resume a paused approval" and "resume a failed run", or whether
this is `pflow <workflow> --resume` / `--from-failed`. Resolve jointly with 125.

## Dependencies
- **Task 125** — shares the checkpoint/resume substrate; build order 125-blocking → this → 125-durable.
- **Task 73** (deprecated, "Checkpoint Persistence for External Agent Repair") — prior art;
  its side-effect/idempotency analysis still applies. Read `.taskmaster/tasks/task_73/`.
- **`--only` machinery** (issue #443) — the reconstruction half this builds on.

## Verification
- Resume from a failed *idempotent* node (llm timeout): upstream restored, not re-run; K and
  downstream execute; final outputs correct; cost reflects only re-run nodes.
- Resume from a failed *side-effecting* node (http/mcp): K's prior partial side-effect does
  NOT double-fire (guarded per side-effect taxonomy).
- A run that took a conditional branch resumes onto the correct branch.
- `restored_nodes` shows upstream-of-K as not_executed; K-onward as executed.
- No prior failed trace → clear error (`OnlySnapshotMissingError`-style), not a silent re-run.
- Hard-kill case reported honestly as not-resumable (no trace).

## References
- **Verified capability facts (2026-06, with file:line):** see Reuse + The delta above.
- **Sibling spec:** `.taskmaster/tasks/task_125/task-125.md` (HITL gates — "Architecture",
  "Reuse", "Known Hard Problems" sections describe the shared substrate).
- **Prior art:** `.taskmaster/tasks/task_73/` (deprecated checkpoint-persistence; idempotency analysis).
- **Key source files:** `src/pflow/runtime/engine/engine.py` (walk loop, `_run_only_snapshot`,
  `find_node_by_id`), `src/pflow/runtime/workflow_trace.py` (`seed_snapshot_into_shared`,
  `load_full_run_events`, `load_snapshot_or_raise`), `src/pflow/execution/plan.py`
  (`_resolve_walk_start` — the existing seed+walk-from-K composition proof),
  `src/pflow/runtime/engine/instrumentation.py` (`initialize_execution_state`,
  `enforce_loop_guard`), `src/pflow/execution/execution_state.py` (`restored_nodes` relabel),
  `src/pflow/cli/commands/run.py` (trace-save `finally`).
