# Task 164: Resume Workflow From a Failed Node

## Description
Add the ability to resume a failed workflow run from the node that failed — restoring
the outputs of already-completed upstream nodes from disk and continuing execution from
the failed node onward — instead of re-running the whole workflow from scratch.

> **Refreshed 2026-07-02 against main — hard-kill claim corrected, Task 173/175 inheritance
> added, attempt-chain lineage added (approved 2026-07-02).** Basis: four parallel code audits
> against current `main` (post Tasks 172/173/175 + #531).

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
`pflow <workflow> --resume` (surface TBD; see CLI Surface + Open decisions) restores the
completed-node outputs from the failed run's trace and **re-enters the graph walk at the failed
node K, following successors to the end** — the missing "resume-and-continue" half of the
existing `--only` snapshot machinery. A resumed attempt is a **new run with its own trace**,
linked to the source via `resumed_from` — see "Run lineage (attempt chains)" below.

## Relationship to Task 125 (shared substrate)
Task 125 (HITL gates, blocking) and this task are the **same primitive under different
triggers**: checkpoint → restore → continue. See task-125.md "Architecture". The division of
labour (125's durable phase was split out as **Task 171** on 2026-06-12, so each task is one PR):
- **Task 125 (blocking gates)** needs NO substrate (verified: in-TTY in-place pause works) → independent, built first.
- **THIS task builds the checkpoint→restore→continue substrate** — it is the general,
  HITL-free exercise of it.
- **Task 171 (durable resume tokens + non-TTY gates)** then reuses this substrate as a thin
  trigger (stop-at-a-gate instead of stop-at-a-failure), persisting 125's decision payload.
Build order: **125 → 164 (this) → 171**.

## Reuse: what already exists (verified 2026-06; refs refreshed 2026-07-02)
The reconstruction half ships, tested, via `--only` (issue #443):
- `seed_snapshot_into_shared(shared, events, exclude=K)` (`workflow_trace.py:427`) — rebuilds
  shared store from a prior trace, scoped to nodes that ran *before* K. Exactly the seeding a
  resume needs.
- The **dry-run planner already composes "seed → start at K → follow successors"**
  (`execution/plan.py:_resolve_walk_start`, 468-492) — proof the pattern works
  against the real compiled graph; it only withholds execution.
- The walk loop is start-node-agnostic: only `curr = workflow.start_node` (`engine.py:682`)
  hardcodes the entry; `find_node_by_id` returns any K.
- Failed runs DO persist a trace (`final_status:"failed"` + `failed_node_ids`). Since Task 172
  (streaming JSONL transport), **every event line streams to disk at emit time**
  (`_flush_event`, `workflow_trace.py:944-955`) — persistence no longer hinges on a CLI
  `finally` block.

## The delta (new work — refreshed 2026-07-02; moderate, leaning small)
1. **Phase 0 (pure refactor, lands first):** extract the shared **seed + locate-entry** helper
   from `engine._run_only_snapshot` (`engine.py:752`) and `plan._resolve_walk_start`
   (`plan.py:468-492`) — see Engine/planner parity plan point 1 (which carries the scope guard)
   and Run-query extraction below.
2. **A resume-scoped loader `load_resume_source(...)`** — the only genuinely new read logic.
   Reuses `_iter_workflow_traces` (`workflow_trace.py:110-149`), whose documented invariant —
   "MUST NOT filter on final_status — status policy lives in each consumer" — exists for
   exactly this. Accepts `failed` (entry = first of `failed_node_ids`); later `paused`
   (entry = `paused_node_id`, Task 171); rejects `success` ("nothing to resume") and — v1 —
   `incomplete`. Lookup by `execution_id` = glob + meta-line check (meta is line 1, cheap).
3. **Engine re-entry: `WorkflowEngine.run(..., resume_from=K)`** — seed via the shared helper
   (`exclude=K`), reset `node_visit_counts` (`engine.py:678-679`),
   `curr = find_node_by_id(start, K)` (`engine.py:503`), do NOT set
   `__execution__["only_node"]` (so outputs route across the resumed tail, not just K), then
   enter the existing walk — `route_action` handles everything after K.
4. **Input re-seeding is a read, not a build:** `meta.inputs` ships since Task 175
   (`runner.py:284-294` stamps it; stored raw on disk, `workflow_trace.py:634-640`); allow CLI
   overrides to win. Caveats: `inputs` may be `null` if unstamped, and MCP / `--no-trace` runs
   write NO trace at all (`runner.py:156`) — nothing to resume.
5. **Stale-definition detection is pre-built:** `content_hash` (Task 173,
   `workflow_trace.py:575-583`) is on the meta line — hash mismatch (workflow edited since the
   failed run) → warn + `--force`.
6. Refine `restored_nodes` to mean "seeded AND not visited this run" — derive post-walk from
   `node_visit_counts`; the single display touchpoint is now `execution_state.py:118`.
7. **Fidelity guard** (resolves parity-plan point 5's declared spec-gate; recorded in Open
   decisions, rec: loud-caveat, NOT a dedicated snapshot store): at seed time, scan seeded
   values for `"<binary data: N bytes>"` placeholders / unresolvable shapes and refuse with an
   actionable error. All three lossiness sources: `default=str`
   (`workflow_trace.py:933`/`:941`), `_sanitize_for_json` bytes→placeholder + dunder-drop
   (`:1206-1233`), and the 2.5.0 LLM `prompt`/`system` strip (`:209-224`) — the documented
   `--only` caveat applies to resume verbatim. A second persistence format is not earned
   (deletion test).

## Run lineage (attempt chains) — approved 2026-07-02
Approved by the task owner 2026-07-02; **this spec is the canonical home** (task-171
cross-references it).

A resumed attempt is a **new trace with a new `execution_id`**, carrying
`resumed_from: <source execution_id>` on the meta line. Appending to the source trace is
impossible by construction: content after `run.complete` is treated as corruption (verified
invariant, `core/trace_io.py:140-145`).

Rules:
- **Resume targets the newest attempt in a chain.**
- **Token/consumption semantics fall out:** a chain with a newer attempt = already consumed.
- **Pre-resume liveness check** via the writer's advisory flock (`_lock_trace_handle`,
  `workflow_trace.py:74-90`) — the `is_trace_locked` probe exists at `ui/run_tailer.py:135` —
  rejects resuming a still-running run.
- **UI/report consumers join chains via `resumed_from`.** Note for the Task 173 overlay:
  without the join, one logical execution renders as multiple runs.

This mirrors Temporal's workflow-id/run-id split and n8n's retries-pointing-at-parent.

## Run-query extraction (Phase 0 opportunity, added 2026-07-02)
Five consumers now glob `~/.pflow/debug` + parse the meta line + apply their own status
policy: `_iter_workflow_traces`, the UI's `scan_traces`, analyze-cache autoload, this task's
`load_resume_source`, and 171's `resume list`. Fold these into one sanctioned query home
during Phase 0 — an extraction of existing code, not new architecture.

## Engine/planner parity plan (added 2026-06-11 — from the planner-mirror refactor, issue #504 / PR #505)

The planner-mirror refactor (PR #505) made five engine/planner surfaces shared
(`validate_only_target`, `route_action`, `new_execution_state`, `build_batch_output`,
`build_snapshot_degraded_diagnostic`) and quantified the drift record this task walks into:
8–9 of 10 post-dry-run commits touched `plan.py` in lockstep with engine changes, and the
closest precedent to THIS task — the `--only` snapshot change (`ac479cfd`) — cost **+78 plan.py
lines alongside +175 engine lines** because entry/seeding semantics are plan.py's mirror
surface. Consequences for this task's implementation plan:

1. **Phase 0 (first phase of this task's PR, pure refactor): extract the shared
   "seed + locate-entry" helper.** The composition exists twice today —
   `engine._run_only_snapshot`'s prologue (`engine.py:752`) and `plan._resolve_walk_start`
   (`plan.py:468-492`) — and the delta above would add a third copy. Extract it into `runtime/`
   with both existing callers rewired FIRST (parity suites as the safety net, zero behavior
   change), then build resume's engine mode and any planner view as additional callers. Do not
   extract it before this task starts: the helper's interface is shaped by resume's needs
   (continue-walking vs run-one-node, failed-trace policy vs full-run policy) — designing it
   without the third consumer risks a wrong seam (ADR-0006 doctrine: share rules/data, not
   traversal; the helper is a rule). Scope guard (carry verbatim): the shared part is
   seed + locate-entry only… if the helper starts growing a `mode` parameter or callbacks,
   that's the overengineering smell. Task 166 is the payoff precedent: loop-carry landed
   behind `plan_node()` and cost zero plan.py work.
2. **Decide the dry-run story explicitly.** Does `--dry-run --resume` exist (planner predicts
   the resumed tail's cache/cost)? If yes, the planner becomes the helper's fourth caller via
   `_resolve_walk_start`. If no, record that as a scoped-out decision — don't leave it implicit,
   or the planner silently lies about resume runs. (Recorded in Open decisions below;
   decide at 164 start.)
3. **Write the parity test first, mutation-verified.** Before feature code, add a drift-suite
   test pinning "engine's resume entry state == planner's walk-start state" (copy the recipe
   from `test_plan_batch_sub_workflow_output_shape_matches_engine`, PR #505 — which demonstrated
   a re-forked shape literal passes all 43 pre-existing batch/drift tests and is caught only by
   a call-site parity pin). Mutation-check it by re-forking one side before trusting it.
4. **Now-shared pieces to reuse directly:** `validate_only_target` is the validation pattern
   (and likely the function) for the resume target K — note it now hard-errors on `""`;
   `route_action` means "continue the walk after K" needs zero new routing logic;
   `build_snapshot_degraded_diagnostic` is the template for a resume-scoped degraded/lossy-state
   advisory (one builder, per-surface params); any new `__execution__` key resume needs goes in
   `new_execution_state()` (`node_state.py`) — never a per-side literal.
5. **Snapshot fidelity is a spec-gate, not an implementation detail.** The Lossy-serialization
   bullet below understates the decision: `--only` accepted trace sanitization (bytes →
   placeholder, dunder-drop, `default=str`) as an iteration-tool caveat, but resume is a
   reliability feature — ADR-0002 explicitly reserves the "dedicated snapshot store" escape
   hatch for when the trace coupling bites. **Status 2026-07-02:** the spec-gate now has a
   concrete resolution candidate — the fidelity guard (delta item 7) — recorded as an open
   USER decision with recommendation loud-caveat, NOT a dedicated snapshot store (see Open
   decisions). Still confirm BEFORE Phase 0 (it changes what the shared helper reads).

> Line-number caveat: the `file:line` refs in Reuse / The delta were refreshed 2026-07-02
> against `main` (post Tasks 172/173/175 + #531). `_validate_only_target` is module-level
> `validate_only_target`; the walk loop dispatches via `route_action`. Re-verify offsets at
> implementation time — the trace/engine files are actively evolving.

## Product stance (v1) — added 2026-07-02
- **At-least-once semantics.** The resumed node K may have partially executed side effects
  before failing; re-running re-fires them. This is the product stance, not a footnote: resume
  gives at-least-once execution of K, and the confirm/`--force` policy (see Open decisions)
  governs when the user must acknowledge it.
- **Top-level granularity.** A failure inside a sub-workflow resumes by re-running the whole
  `WorkflowExecutor` host node — the seed machinery is top-level-scoped via
  `final_events_by_node`. Documented v1 limitation; the memo cache softens the re-run cost.

## Known Hard Problems
- **Node-K idempotency (the core problem).** K may have *partially* side-effected before
  failing (an http POST that sent but timed out on the response, an mcp tool that created a
  resource, a claude-code node that already committed). Re-running double-fires — see the
  at-least-once product stance above. Reuse the existing side-effect taxonomy:
  `_default_cache_for_node_type` (`compiler.py:641`) already classifies which node types
  side-effect (only `llm` caches by default) — same classification tells you which K is
  resume-safe vs. needs a guard/confirm (policy in Open decisions). Recommended phasing: prove
  the substrate on an *idempotent* K first (an `llm` timeout — re-run is safe), then layer
  idempotency handling for side-effecting K.
- **Conditional-branch divergence.** A resumed run may take a different branch than the
  snapshot did; downstream nodes run fresh, but verify branch-dependent state resolves
  correctly (Searcher B's flagged verification target).
- **Hard kill vs graceful failure — CORRECTED 2026-07-02 (this spec's pre-172 claim was false).**
  This spec previously said a SIGKILL / `KeyboardInterrupt` does not persist a trace. Since
  Task 172, every event line streams to disk at emit time (`_flush_event`,
  `workflow_trace.py:944-955`), so Ctrl+C/SIGKILL leaves an *incomplete-but-readable* trace:
  the `run.complete` trailer is absent and the reader synthesizes
  `final_status="incomplete"` with transitive orphan-drop (`core/trace_io.py:225-237`).
  Note `"incomplete"` is reader-synthesized, never producer-written — no on-disk `incomplete`
  trailer exists. The graceful/hard-kill discriminator is therefore **`run.complete` present
  vs absent** — NOT trace-exists vs not. Resume-after-Ctrl+C is now physically possible;
  whether v1 supports it is an open USER decision (rec: NO — see Open decisions).
- **Nested / sub-workflow resume is OUT of scope (v1).** Dotted `--only parent.child` is
  rejected on every live path today; the child plumbing (`_pflow_child_only_node`) exists but
  is dormant (#443). Resuming *into* a sub-workflow is a deferred follow-up. v1 resumes only
  at top-level node K — see the top-level-granularity product stance above.
- **Lossy serialization.** Three lossiness sources in the trace: `json.dump(..., default=str)`
  (`workflow_trace.py:933`/`:941`) — non-JSON-native values resurrect as `str()`;
  `_sanitize_for_json` bytes→placeholder + dunder-drop (`:1206-1233`); and the 2.5.0 LLM
  `prompt`/`system` strip (`:209-224`). Mitigated at seed time by the fidelity guard (delta
  item 7). Shared with Task 125.

## CLI Surface (open — spans 164+171; decide at 164 start)
`pflow resume` is a name Task 171 also wants (for resuming a paused gate via token). Two
candidates:
- **`pflow resume [<workflow>|<execution-id>]`** — bare = newest failed run; an
  `execution-id` = that exact attempt; the same surface serves 171's token addressing.
- **`pflow <workflow> --resume` / `--from-failed`** — flag on the existing run surface.
Resolve jointly with 171 (flagged in task-171.md Dependencies too); recommendation recorded
in Open decisions below.

## Open decisions (USER — recorded 2026-07-02, each with a recommendation)
None of these are silently decided; the task owner decides at 164 start.
1. **CLI surface** — `pflow resume [<workflow>|<execution-id>]` vs a `--resume` flag (see CLI
   Surface above). Spans 164+171. **Rec: the `pflow resume` subcommand** — one surface serves
   both tasks (bare = newest failed; id = exact attempt; token-addressable for 171).
2. **`--dry-run` × resume** — in or out of v1? If in, the planner becomes the shared helper's
   fourth caller via `_resolve_walk_start`; if out, record it explicitly so the planner
   doesn't silently lie about resume runs (parity plan point 2). **Rec: in** — the planner
   already composes seed→start-at-K, so it's cheap, and it keeps `--dry-run` honest.
3. **Incomplete-trace resume (Ctrl+C/SIGKILL tails)** — physically possible post-Task-172
   (see Known Hard Problems). **Rec: NO for v1** — entry-node identification is ambiguous for
   incomplete tails (no `failed_node_ids`; the last-seen node may have half-run). Deliberate
   scoping, revisit later.
4. **Side-effecting-K policy** — confirm-prompt vs `--force`, keyed off the
   `_default_cache_for_node_type`-style side-effect taxonomy (`compiler.py:641`). **Rec:**
   confirm-prompt in a TTY, require `--force` non-TTY, only when K's node type is classified
   side-effecting; idempotent K (e.g. `llm`) resumes without ceremony.
5. **Snapshot fidelity** — loud-caveat (fidelity guard, delta item 7) vs ADR-0002's dedicated
   snapshot store escape hatch. **Rec: loud-caveat** — a second persistence format is not
   earned (deletion test); revisit only if the guard fires often in practice.

## Dependencies
- **Task 125** — shares the checkpoint/resume substrate; build order **125 → this → 171**.
- **Task 171** — durable resume tokens / non-TTY gates (split from 125's durable phase,
  2026-06-12); the second consumer of this task's substrate. Cross-task contract (restated
  2026-07-02): **one reader, one source (the trace), two terminal statuses
  (`failed`/`paused`)** — `load_resume_source` accepts `paused` with entry = `paused_node_id`.
  Task 171 follows this task's implementation, and cross-references the Run lineage section
  above as canonical.
- **Tasks 172 / 173 / 175 (shipped)** — inherited capabilities this task *reads*, not builds:
  streaming JSONL trace transport (172), `content_hash` on the meta line (173), `meta.inputs`
  stamping (175). See The delta items 4–5 and Known Hard Problems (hard-kill correction).
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
- Incomplete trace (Ctrl+C/SIGKILL tail — `run.complete` absent, reader-synthesized
  `incomplete`) → rejected with a clear "v1 doesn't resume incomplete runs" error (deliberate
  scoping, see Open decisions), not a crash or silent re-run.
- Resumed attempt writes a NEW trace with a new `execution_id` and `resumed_from` on the meta
  line; the source trace is never appended to. Resume targets the newest attempt in a chain.
- Resuming a still-running run is rejected (advisory-flock liveness probe, `is_trace_locked`).
- `content_hash` mismatch (workflow edited since the failed run) → warn + require `--force`.
- Fidelity guard: seeded values containing `"<binary data: N bytes>"` placeholders →
  actionable refusal, not a silent resume with corrupt state.
- Phase-0 extraction lands first with parity suites passing unmodified; the engine↔planner
  walk-entry parity test exists and is mutation-verified (re-fork one side → test fails)
  BEFORE resume feature code (see Engine/planner parity plan).

## References
- **Verified capability facts (refs refreshed 2026-07-02, with file:line):** see Reuse +
  The delta above.
- **Failure-state edge cases (#255):** `research/255-failure-state-edge-cases.md`
  (2026-06-18, in this task's dir) is the authoritative home — trust it over the stale issue
  body. Re-verified 2026-07-02: pre-engine exceptions still yield `shared_after={}`
  (`runner.py:773-775`; the failure annotation is only attached inside `_compile_and_execute`,
  `runner.py:323-328`), and the engine bypass is now CLI-probe-only
  (`cli/commands/_probe_impl.py:157` — the MCP side already routes through the engine).
- **Sibling spec:** `.taskmaster/tasks/task_125/task-125.md` (HITL gates — "Architecture",
  "Reuse", "Known Hard Problems" sections describe the shared substrate).
- **Prior art:** `.taskmaster/tasks/task_73/` (deprecated checkpoint-persistence; idempotency analysis).
- **Key source files:** `src/pflow/runtime/engine/engine.py` (walk loop, `_run_only_snapshot`
  at `:752`, `find_node_by_id`), `src/pflow/runtime/workflow_trace.py`
  (`seed_snapshot_into_shared` `:427`, `load_full_run_events` `:227` with status allowlist
  `:259-261`, `_iter_workflow_traces` `:110-149`, `_flush_event` `:944-955`, writer flock
  `_lock_trace_handle` `:74-90`), `src/pflow/ui/run_tailer.py:135` (`is_trace_locked` probe),
  `src/pflow/core/trace_io.py` (reader-synthesized `incomplete`
  `:225-237`, post-`run.complete` corruption invariant `:140-145`),
  `src/pflow/execution/plan.py` (`_resolve_walk_start` `:468-492` — the existing
  seed+walk-from-K composition proof), `src/pflow/runtime/engine/instrumentation.py`
  (`initialize_execution_state`, `enforce_loop_guard`),
  `src/pflow/execution/execution_state.py` (`restored_nodes` relabel, `:118`),
  `src/pflow/execution/runner.py` (`meta.inputs` stamping `:284-294`, no-trace paths `:156`).
