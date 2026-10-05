# Task 179: Durable Loop Position — pause and resume continue at the iteration where a loop stopped

## Description

Make a loop's position part of the saved run, so a run that pauses (approval or escalation gate)
or fails inside a loop resumes at the iteration where it stopped instead of restarting the loop.
One mechanism replaces today's loop special cases (the iteration-1-only pause rule, the loop
refusals, the loop warnings) and makes per-iteration human approval work everywhere — terminal,
agents, MCP, and the web UI's ordinary Approve button.

## Status

not started

## Priority

high

## Roadmap

next

## Problem

`guide/features/resume.md:82`: *"Loop iteration position is not part of the saved run, so a
resumed loop step begins its loop again."* All loop state lives in locals of `_run_inner`
(`loop_counts`/`loop_caps` `runtime/engine/engine.py:790-791`; `__iteration__` via
`loop_runtime_scope`, `loop_control.py:47-50`); carried inputs are re-derived from the node's
previous output `shared[K]`; trace events carry no iteration field (`workflow_trace.py:667-771`);
resume never seeds the entry node's own output (`resume_source.py:843`, "NEVER seeds `exclude`
itself"). Consequences, all one root:

- **Per-iteration approval can't pause past round 1.** Since #615 (PR #655) `_gate_pausable`
  allows an approval on a loop step only at iteration 1 (`engine.py:120-121`); later rounds fail
  (exit 1) unless pre-approved with `--auto-approve`. Agents (non-TTY) and the web UI (whose
  Approve sends only `--approve yes`) cannot give per-round consent — a gated loop can't be
  finished from the browser (#656, folded here).
- **Loop escalations can't pause at all** (`engine.py:122-124`) — yet the documented re-fork
  recipe (`guide/features/approval.md:81-102`) is a loop that escalates, so it hard-fails whenever
  no one is at a terminal.
- **Failure-resume inside a loop re-runs every completed iteration's side effects** (resume
  enters K with fresh counters and the round-1 seed; pinned by
  `tests/test_runtime/test_resume_engine.py:736`).
- **Pause surfaces carry no loop information** — the one formatter
  `format_resume_answer_command` (`execution/gate_prompt.py:195-205`) feeds CLI pause output, the
  MCP paused response, `resume list`, and the answer-required error; none can say "round N of M"
  or give loop guidance because the pause record (`{paused_node_id, gate_request}`,
  `engine.py:1556-1559`; `GateRequest` `core/gate.py:34-50`) has no loop field.

**This overturns a documented stance, by user ruling.** Task 164 chose restart-at-1 deliberately
(`task_164/task-164.md:340-341`; `task_164/task-review.md:188`: "documented stance, not an
accident; don't 'fix' it"), and between-nodes resume after a loop is refused "as the minimal safe
fix" (`task_164/.../progress-log.md:1440-1447`: "treat loop nodes as ambiguous unless the
re-entry decision is persisted"). This task persists that decision. ADR-0010's at-least-once
contract (Decision 4) still holds — continuation NARROWS re-firing to iteration N instead of
1..N; the ADR gets an amendment, not a reversal.

User ruling, 2026-09-30 (asked *"why are we not doing the "real fix" again?"*, then *"yes go
ahead"* on: spec the real fix now, build after Task 170, fold #656 into it).

## Solution

Persist loop position in the trace, restore it on resume, and let one pausability rule —
"pause only where resume can honour the token" — hold for loops with no loop exception.

## Design Decisions

- **One mechanism for pause AND failure** — the same saved position serves approval, escalation,
  and failure-resume; special-casing any one of them keeps a second rule alive (Q1 = (c)).
- **Delete what the mechanism makes obsolete, in-task** — `_gate_pausable`'s loop clauses, the
  #615 loop warning (`cli/commands/run.py:468-480`), the between-nodes-after-a-loop refusal
  (`resume_preflight.py:261-273`), and every statement of the restart rule. NOT deleted:
  `_fully_answered_gate_ids` (`run.py:499-515`) — it states answer-vs-occurrence multiplicity
  (`--approve yes` answers one gate; a loop step has up to `max_iterations` occurrences, so the
  answered step still pauses at the next iteration and belongs in the `--dry-run` ⏸ footer and the
  run-start note). Restart-rule statements: `guide/features/resume.md:82`, `guide/features/approval.md:34, 52`,
  `runtime/engine/CLAUDE.md` ("Approval additionally requires no loop or the loop's first iteration"),
  `docs/reference/cli/index.mdx:90`. The deletion test is the acceptance bar for "simpler final code".
- **The "pinned" restart test is a weak pin.** `tests/test_runtime/test_resume_engine.py:736`
  (`test_loop_k_restarts_at_iteration_one`) fails at iteration 1, where restart and continue produce the
  same output — it cannot distinguish the two stances and passes unchanged under (c). The replacement
  test fails mid-loop (round ≥2) so it actually pins continuation.
- **#659 (stale host frame overwrites a looping sub-workflow step's iteration record) is a
  prerequisite phase**, not a separate lane: resume seeds from exactly that per-iteration history.
- **#656's "approve all remaining rounds" button is decided here, once**, in this task's UI pass:
  with per-round pause working, the ordinary Approve finishes a gated loop; the convenience is
  built only if the user still wants it after seeing the per-round flow (show-before-code).
- The user's governing lens, verbatim: *"We should prioritize simplicity of the FINAL code, not
  how easy it is to get there. When in doubt we should ask ourselves whats the right solution that
  the top 10% of codebases similar to this one would implement, have we considered it yet? What
  this doesnt mean is overfitting to "top 10% of codebases" and overengineering, this is about more
  simple code that is optimized for AI agents to understand and add features to."*

## Decisions (Q1/Q2 user rulings; Q3–Q6 resolved by the planner — rationale in `implementation/implementation-plan.md` §3)

- **Q1 (user) — scope. DECIDED 2026-10-05: (c).** (a) approval gates only; (b) approval + escalation
  (unblocks the documented re-fork recipe); (c) (b) + failure-resume (changes Task 164's pinned stance
  and its test). User ruling: *"go ahead with this"* on the recommendation (c) — one mechanism, and only
  (c) lets every loop special case go.
- **Q2 (user) — failure-resume default under (c). DECIDED 2026-10-05: continue unless the saved state
  can't be restored faithfully, then refuse with guidance** (as resume already does for binary
  placeholders, `resume_source.py:381-388, 594-601`). No restart flag (a second mode nothing needs yet).
  Correction (refreshed 2026-10-05 against main): LLM prompt/system stripping is NOT at those lines — it
  lives in `workflow_trace.py` (`_strip_redundant_llm_trace_fields`) and today's resume does not refuse
  on it; the planner decides whether a stripped prompt counts as "can't restore faithfully" for a loop
  node (it did not for Task 164's node-level resume).
- **Q3 — where position is stored. DECIDED (planner, 2026-10-05): (a)** — `iteration` on every
  loop-node trace event (format `2.8.0`, additive), plus `GateRequest.iteration` so the pause record —
  and therefore every pause surface — knows the iteration without reading the event stream. No
  `max_iterations` on the gate (no consumer). Rationale and rejected options: implementation plan §3.
- **Q4 — seeding K's own last output. DECIDED: the resume entry is a (step, iteration) pair.**
  `_seedable_final_events(events, entry, entry_iteration=1)` ends its slice before the entry's event for
  that iteration, so the entry's earlier iterations are upstream of it and seed like any completed work;
  the invariant becomes "never seed the iteration about to run". `--only` passes iteration 1 and is
  unchanged. One rule for both surfaces; no second seed channel, no mode flag.
- **Q5 — re-derive vs restore. DECIDED:** restored — the loop's own counter (`loop_counts[K] =
  entry_iteration − 1`) and `shared[K]` (via the seed). Re-derived by unchanged code — `__iteration__`,
  carry (`plan_node` → `carry_effective_config`), the condition, the cap (re-resolved at the attempt's
  first re-entry check). Not restored — the hard visit guard (a per-process safety net; the restored
  counter bounds the cap exactly).
- **Q6 — pause surfaces. DECIDED: all of them, from one field.** `format_gate_lines` renders `Loop
  iteration N` from `gate_request["iteration"]` (CLI pause stderr, MCP `Gate:` block, the answer-required
  error); the CLI JSON pause document and `GET /api/gate` carry it inside `gate_request`; `resume list`
  threads `PausedRun.iteration` from the trailer's `gate_request` into its row; the web gate panel shows it
  in its eyebrow. Position is read from the trace once (the loader) and from the trailer once (`resume
  list`) — never from the event stream twice.
- **Q2 correction resolved:** a stripped LLM `prompt`/`system` is not a loader refusal; a carry
  referencing it fails loudly at the resumed iteration through the existing strict carry guard
  (`LoopCarryError`), the same stance as node-level resume.

## Rulings at launch (2026-10-05, main orchestrator with the user)

- **Final-step loop escalation — DECIDED (b)**: a loop step whose escalation fires on the workflow's final step
  keeps today's cannot-pause rule (the default-successor conjunct); `guide/features/approval.md` states that the
  re-fork recipe needs a step after the loop. User: *"go ahead with your recommendations and implement"* on the
  planner's recommendation. (c) — dropping the conjunct for all escalations via `resume_after` — is recorded as
  its own future ruling, not built here.
- Serialize/fold note (also on main's spec copy): **#690** (fix-then-resume refused twice — side-effect gate
  ignores that the entry never executed; stale-workflow gate hashes the whole IR) and **#458** (`--only` demands
  inputs it then ignores) sit on `resume_preflight.py` / the snapshot surface — the task orchestrator notes in the
  progress log whether Q2's rule already decides them or they stay behind this task.

## Dependencies

- **Task 170** (One Template Language) — MERGED 2026-10-01 (PR #673); rebase-free start. Its edit sites were: it edits the carry check
  inside `engine.py` (`_assert_carried_inputs_resolved`, `:253-256`), `_resolve_template_string`,
  and migrates `evaluate_loop_condition`; this task's likely edits (loop counters `:790-834`,
  `_gate_pausable`, the gate branch `:1527-1596`, `_prepare_resume`, `resume_source`,
  `resume_preflight`, the trace schema) are adjacent, and any seeding through
  `plan_node`/`carry_effective_config` would overlap directly. Engine + trace-format →
  serialize.
- **#659** — folded in as the first phase.
- **Citation drift (refreshed 2026-10-05 against main `e402a1e6`):** every claim in this spec and the
  investigation re-verified; none wrong. Line numbers moved: `engine.py` +12 after ~line 270 (Task 170;
  `_gate_pausable` at `:98-132` unmoved; loop counters now `:802-846`, gate fires `:1285-1291`, gate
  branch `:1504-1608`, `--only` loop target `:899-902`); `loop_control.py` −8 after ~130
  (`evaluate_loop_condition` `:121-161`, template cap `:168-176`); `cli/commands/run.py` +2 (#615 warning
  `:469-480`, `_fully_answered_gate_ids` `:499-515`). Re-verify file:line at start regardless.

## Requirements

- A run paused at an approval (and, per Q1, escalation) gate on iteration N of a loop step issues
  a resume token; answering it runs iteration N and continues the loop — rounds 1..N-1 do not
  re-run, and a later gated round pauses again with a new token.
- (Per Q1/Q2) A run that failed at iteration N resumes at iteration N; completed iterations'
  side effects do not re-fire; when the saved state can't be restored faithfully, resume refuses
  with guidance.
- Carry, loop condition, and cap behave identically to an uninterrupted run from the resumed
  iteration on (same `__iteration__`, same carried inputs, same stop).
- The trace records loop position per Q3; older traces (no position) keep today's behaviour
  (restart-at-1) and say so, never guess.
- Pause surfaces (per Q6) show the loop position consistently across CLI, MCP, `resume list`,
  and the answer-required error.
- The obsolete loop special cases listed under Design Decisions are deleted, and the guides
  (`guide/features/resume.md`, `approval.md`) state the one rule.
- The web UI's Approve finishes a multi-round gated loop round by round.

## Implementation Notes

- **Ground truth + prior art:** `starting-context/loop-position-investigation-2026-09-30.md`
  (loop execution model with `file:line`, saved-run contents, symptom roots, interactions,
  Task 164/171/ADR-0010 quotes, Task 170 collision map). Re-verify at start.
- **Interactions to cover:** nested sub-workflow hosts (child gates never pause, `nested=True`,
  `workflow_executor.py:440` — a resumed iteration N re-runs the whole child for N); `--only` on a
  loop target (runs one iteration at `iteration=1`, `engine.py:887-890` — shares the seeding code);
  the dry-run planner (walks the loop once, costs up to the cap — a mid-loop resume preview must
  not overstate); the web UI overlay (last event per node, `ui/run_node.py:148-165`); the live
  trace stream (Tasks 172/173).
- Trace-format change: version bump + the Task-159 baseline
  (`.taskmaster/tasks/task_159/baseline/verify.sh`) as the outer regression net; plan-mode
  deep-review is mandatory (engine + trace).
- ADR: amend ADR-0010 (at-least-once narrows to the resumed iteration) and record the
  loop-position decision (Q3/Q4) — hard to reverse, surprising, real trade-off.

## Verification

- A 3-round approval-gated loop, run non-interactively: pause at round 1 → answer → round 1 runs,
  pause at round 2 with a new token → answer → … → completes; the effects file has exactly 3
  lines (presence) and no line twice.
- Same through the web UI (real browser, `screenshot-pflow-web-ui` skill) with only the Approve
  button.
- (Q1 b/c) The documented re-fork escalation recipe pauses and resumes non-interactively.
- (Q1 c) A loop failing at round 3 of 5 resumes at round 3; rounds 1–2's side effects fire once
  in total (counted), carry into round 3 equals an uninterrupted run's.
- A looping gated sub-workflow host stopped at round 2 keeps round 1's trace event (#659).
- An old-format trace (no position) resumes with restart-at-1 and says so.
- Deleted special cases are gone (grep) and their tests replaced, not orphaned.
- Real surface: `uv run pflow` + `pflow resume` non-TTY (`</dev/null`), MCP paused response,
  `pflow resume list`; `make test-all-local`; Task-159 baseline unchanged (the same pre-existing drifts as the
  base commit — 8 at `90b891cb`, recorded in the plan — and no new ones).

## References

- `starting-context/loop-position-investigation-2026-09-30.md` — the investigation (cited).
- Issues: #615 / PR #655 (one-answer rule + iteration-1 pause — superseded here), #656 (UI
  approve-all — folded), #659 (host-frame overwrite — first phase).
- Prior decisions: Task 164 (`task-164.md:340-341`, `task-review.md:188`), Task 171
  (`task-review.md:39-43` "pause is a promise"), Task 166 (stateful loop, `carry`), ADR-0001
  (loop engine re-entry), ADR-0010 (resume trace checkpoint, at-least-once).
