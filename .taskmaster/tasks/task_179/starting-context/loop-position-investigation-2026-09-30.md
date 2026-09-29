# Durable loop position: codebase investigation (2026-09-30)

Gathered by a `pflow-codebase-searcher` (Opus) for the main orchestrator, session-09, against main @ 08e1eb68. The code is identical to 8bb82c30 for these paths. **Line numbers drift: re-verify at start.**

## 1. Loop execution model (VERIFIED)

**Structure.**
- A loop wraps ONE node; the engine re-enters that same node. There is no loop-body graph: a multi-step body is a looping `workflow` host (ADR-0001; `types.py:39-53`).
- `loop:` and `batch:` are mutually exclusive on one step (`types.py:44`, ADR-0001:46).

**State lives only in `_run_inner` locals, and none of it is traced:**
- `loop_counts` / `loop_caps` (`engine.py:790-791`), incremented at `:812-813`.
- `__iteration__`, written to `shared` by `loop_runtime_scope` (`loop_control.py:47-50`) and popped at loop end or on error (`engine.py:834, 849`).
- `__loop_active__`, a depth counter that suppresses memo reads and is propagated to children (`workflow_executor.py:153-156`).

**Carried inputs are not stored.** They are re-derived each round from the node's own previous output `shared[node_id]`:
- `is_carry_iteration` is `__iteration__ > 1` (`loop_control.py:88-91`).
- `carry_effective_config` swaps the carry templates into `inputs` (`:94-118`), called from `plan_node`.

**Per-iteration outputs are not accumulated.** Each iteration overwrites `shared[node_id]`; only the last survives, plus the `loop_stopped` stamp (`engine.py:1029-1033`).

**Condition, cap and visit guard.**
- The condition is read from the fresh `shared[node_id]` after each clean return (`_loop_should_reenter`, `engine.py:978-1026`; `evaluate_loop_condition`, `loop_control.py:121-170`).
- The cap is resolved once, at the first re-entry check, and memoized (`engine.py:1016-1019`). A template cap reads `dict(shared)` (`loop_control.py:184-186`).
- Hard visit guard: `node_visit_counts` (`instrumentation.py:53-82`, `MAX_NODE_VISITS` = 100 at `:24`), reset at the start of each run (`engine.py:780-781`).

**What a resume at iteration N must rebuild** (INFERRED):
- `loop_counts[K] = N-1`, so the next increment gives N.
- `shared[K]` = iteration N-1's output, which feeds both carry and the condition.
- `__iteration__ = N`, set by the scope once the count is right.
- The cap, re-resolved from the seeded upstream (same value if the seed is faithful).
- `node_visit_counts[K] = N-1`, if the guard should stay exact.
- For an escalation at iteration N, the next step is the re-entry DECISION: fold the answer into iteration N's output, set `loop_counts = N`, then run `_loop_should_reenter`.

## 2. What the saved run holds today (VERIFIED)

**Trace version and baseline.**
- Trace version is `2.7.0` (`workflow_trace.py:33-41`). New fields bump the minor version; readers check only `startswith("2.")` (`:164`). 2.6.0 and 2.7.0 were both additive.
- Task-159 baseline `verify.sh` re-runs the `command.sh` cases and diffs against the committed `expected-*.txt`. It pins CLI output, not the trace schema.

**Per-iteration events.**
- Every iteration gets its own event with a new seq (`record_node_execution` → `_stamp_correlation`, `workflow_trace.py:667-771`).
- Each event carries a copy of `shared[K]` (`instrumentation.py:586-592`) and the resolved `node_params`, including that round's carried inputs (`engine.py:1426`).
- There is **NO iteration field**: the iteration can only be INFERRED from the order of same-`node_id` events.
- Only the last event per node counts (`final_events_by_node`, `workflow_trace.py:403-429`).

**What resume restores.**
- Per-node output and the shared store are restored as output-only seeding of nodes BEFORE the entry: `seed_snapshot_into_shared` (`resume_source.py:810-855`) via `_seedable_final_events`, whose slice ends before the entry's first event (`:310-328`).
- So none of K's own iterations are ever seeded. "NEVER seeds `exclude` itself" is a stated invariant (`:843`).
- Also restored: inputs from `meta.inputs`. Restored events are re-recorded as `cached/restored` (`engine.py:942-953`).

**Pause record and entry points.**
- The pause record is `{paused_node_id, gate_request}` on the trailer (`engine.py:1556-1559`). `GateRequest` has no loop or iteration field (`core/gate.py:34-50`).
- An approval enters at the gated node, with no event for that visit (`resume_source.py:489-492`).
- A failure enters at the root of the terminal failure region (`:415-447`).
- A between-nodes stop after a loop node is refused (`resume_preflight.py:185-197, 261-273`).

**Seeding fidelity limits.** LLM `prompt`/`system` are stripped, and binary placeholders make resume refuse (`resume_source.py:381-388, 594-601`; runtime/CLAUDE.md "Traces, snapshots, and resume").

## 3. Symptoms and roots

- **(a) Iteration-1-only pause.** `_gate_pausable` returns `loop_config is None or iteration == 1` for approvals (`engine.py:120-121`) and `loop_config is None` for escalations (`:122-124`). Root: loop position is not saved. VERIFIED.
- **(b) Failure-resume re-runs earlier iterations.** Resume enters K with fresh `loop_counts` and the round-1 seed.
  - Side-effect confirmation checks only K's type (`resume_preflight.py:298-324`).
  - Pinned by `tests/test_runtime/test_resume_engine.py:736`; task-164 review says "don't 'fix' it" (`task_164/task-review.md:188`).
  - Same root as (a). VERIFIED.
- **(c) No loop info on pause surfaces.** One formatter, `format_resume_answer_command` (`gate_prompt.py:195-205`), has four consumers:
  - CLI pause (`run.py:661-667`);
  - MCP paused text (`execution_service.py:228-255`);
  - `resume list` (`resume.py:425-471`);
  - the answer-required error (`exceptions.py:1481-1495`).

  The pause record has no loop data. Saving position naturally supplies it. The `run.py:467-509` loop warning and `_fully_answered_gate_ids` become obsolete. VERIFIED / INFERRED.
- **(d) Host trace record overwritten (#659).** A DIFFERENT root: a stale attribute on the node object.
  - `WorkflowExecutor._host_frame` is reset only in `exec()` (`workflow_executor.py:383`) and set by `descend()` (`:448`).
  - The approval gate fires at step 7.5 (`engine.py:1273-1279`), before `node._run`, so on iteration 2 `exec()` never runs.
  - The gate branch reads iteration 1's frame (`engine.py:1581`) and calls `record_trace(..., frame=host_frame)` (`:1583-1596`), which reuses iteration 1's seq (`workflow_trace.py:760`).
  - The reader deduplicates by id, last one wins (`trace_io.py:205-207`).

  This is a PREREQUISITE: it corrupts the per-iteration history a durable resume seeds from. VERIFIED.
- **(e) The documented re-fork recipe is a loop that escalates** (`guide/features/approval.md:81-102`), but loop escalations cannot pause (`approval.md:76`, `engine.py:122-124`). The canonical recipe hard-fails whenever no one is at a terminal. Same root as (a). VERIFIED.

## 4. Interactions

- **Batch.** Cannot share a step with a loop. A batch inside a looping host's child reads no loop state (`batch_executor.py` never uses `__iteration__`). VERIFIED.
- **Nested sub-workflows.** The child gets `__loop_active__` only (`workflow_executor.py:153-156`). Child gates never pause (`nested=True`, `:440`), so a mid-loop resume re-runs the whole child for iteration N. VERIFIED.
- **`--only`.** A loop target runs one iteration at `iteration=1` (`engine.py:887-890`). Task 166 deferred this: "can't reproduce a mid-loop iteration" (`task_166/.../implementation-plan.md:478, 494`). VERIFIED.
- **Dry-run planner.** Walks the loop once at iteration 1 and costs it up to the cap (`plan.py:358-382, 903-922, 2462-2464`), so a mid-loop resume preview would overstate. INFERRED.
- **Web UI `/api/resume`.** Runs `preflight_resume` and then spawns `pflow resume` (`ui/server.py:1115-1200`); it reads no loop state. The overlay keeps the last event per node, keyed by event id (`ui/run_node.py:148-165`; `web/src/types.ts:42-46`). `LoopSpec` comes from the IR (`types.ts:164-169`). VERIFIED.
- **MCP.** Produces the paused response only. ADR-0010: MCP in-memory runs are unresumable. Not re-checked.
- **Readers of loop info today:** `run.py:502-509` (IR `loop`), `resume_preflight._node_has_loop`, `_gate_pausable`, `plan.py`.

## 5. Prior art (VERIFIED quotes)

- `task_164/task-164.md:340-341`: "K **restarts at iteration 1** (loop state `loop_counts`/`__iteration__` is engine-ephemeral, never traced — documented, not engineered around)."
- `task_164/task-review.md:188`: "documented stance, not an accident; don't 'fix' it."
- `task_164/.../progress-log.md:1440-1447` (C3): between-nodes after a loop refuses; "Chose refuse over resume-at-the-loop … as the minimal safe fix". Reviewers: "treat loop nodes as ambiguous unless the re-entry decision is persisted."
- `task_164/starting-context/braindump-planner-mirror-session.md:112-114`: "UNEXPLORED … Likely answer: K restarts at iteration 1 … but decide explicitly."
- `task_171/task-review.md:39-43`: "Pause is a promise … loop/`code`/terminal escalations … all stay `failed`."
- ADR-0010 "Known sharp edge": at-least-once over the K-onward tail; a durable or exactly-once feature "must revisit this".
- ADR-0001 and ADR-0009 contain no mid-loop resume decision. Task 125 has nothing on it.

## 6. Collision with Task 170 (VERIFIED against its branch diff + uncommitted worktree)

**Task 170's edits:**
- code inside the carry check `_assert_carried_inputs_resolved` (`engine.py:253-256`);
- adds `_plan_left_unresolved`;
- edits `_resolve_template_string`;
- changes imports in `loop_control.py` and `batch_executor.py`;
- its plan migrates `evaluate_loop_condition` (plan:720).

**This task most likely edits:**
- the loop counters in `_run_inner` (`:790-834`);
- `_gate_pausable`;
- the gate branch (`:1527-1596`);
- `_prepare_resume` / `seed_walk_entry`;
- `resume_source` / `resume_preflight`;
- the trace schema.

**Overlap:** textual adjacency in `engine.py` only, UNLESS the design seeds carry through `plan_node` / `carry_effective_config` / `_assert_carried_inputs_resolved`, which is a real overlap. So land after Task 170 or rebase onto it.

## Gaps

- No iteration index is recorded anywhere. "Event k = iteration k" is INFERRED, and it breaks once events are overwritten as in (d).
- MCP trace persistence for pauses was not re-checked.
