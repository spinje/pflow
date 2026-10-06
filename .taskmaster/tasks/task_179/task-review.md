# Task 179 Review: Durable Loop Position

## Metadata
- Implemented 2026-10-05 → 2026-10-06 on `feat/task-179-durable-loop-position`. Planner: Fable. Orchestrator: Opus. P1–P3 and every gate-fix round: one Opus implementer. P4 (web): Fable.
- Closes #659. #656 was folded in here; its button was not built (ruling later reversed — #656 reopened). Supersedes #615's iteration-1-only pause rule (PR #655). Trace format **2.7.0 → 2.8.0**.
- The journey (rulings verbatim, gate dispositions, mutation evidence, real-surface transcripts) is in `implementation/progress-log.md`. The design rationale is in `implementation/implementation-plan.md` §3 and in ADR-0010's Task-179 amendment.

## Read First — the load-bearing block
- **What exists now:** a loop step's position is part of the saved run. A run that pauses (approval or escalation) or fails inside a loop resumes at the iteration where it stopped. Every later gated iteration pauses again with a new token, so the web UI's plain Approve finishes a gated loop. Resume refuses to restore anything the trace could not save and restore unchanged, and a gate whose resume would refuse stays `failed` instead of issuing a dead token.
- **Read these first:**
  - `runtime/resume_source.py`: `resume_iteration` (the ONE reader of events' `iteration`), `_seedable_final_events` (the (step, iteration) slice), `lossy_seed`, `_guard_seed_scope`, `_apply_gate_resolutions` (folds by iteration).
  - `runtime/engine/engine.py`: `prepare_resume_entry` / `ResumeEntry` and `continue_after_step` (shared by engine and planner); `_prepare_resume`; `_lossy_resume_seed`; `_gate_pausable`; the gate except-arm (`not originating` host-frame conjunct, lossy conjunct).
  - `runtime/engine/loop_control.py::should_reenter` (moved out of the engine — now the walk's AND the resume's decision).
  - `runtime/workflow_trace.py::_sanitize_for_json` (the `lossy` marker) and `record_node_execution(iteration=, lossy=)`.
- **Invariants that must NOT break:**
  - **One reader of position.** Only the loader (`resume_iteration`) reads the event `iteration`; the engine and planner receive `resume_iteration` and never scan events for it. A second reader re-forks the off-by-one rules — recovered failure, after-K, keyless `None`.
  - **The seed slice is `>=`, not `==`.** It ends at the entry's first event whose `iteration` (keyless = 1) is `>= entry_iteration`. With `==`, `--only K` against a resumed attempt (which holds a restored N−1 and live N.., never a 1) seeds K's own stale output. Sole pin: `test_only_loop_target_against_a_resumed_attempt_never_seeds_its_own_output`.
  - **`resume_iteration`'s `None` means "no recorded position", not "iteration 1".** It drives both the D7 restart advisory and the preflight's "no recorded loop position" refusal for an after-K source. Collapsing it to 1 sends an unpositioned after-K source past the preflight into the runner's `ValueError` guard.
  - **Escalation decisions fold onto the iteration that raised them** (gate lines carry `iteration`). Folding onto the final event either false-refuses (an answered iteration-1 escalation, then a failure at 2) or applies iteration 1's answer to iteration 2's unanswered question.
  - **Engine and planner share `prepare_resume_entry` / `continue_after_step` / `assert_carried_inputs_resolved`.** The dry-run predicts exactly what the run does. A planner-local copy re-opens the carry-guard divergence the gate caught.
  - **Pause is a promise, now including fidelity.** The gate arm stays `failed` when `_lossy_resume_seed` (the loader's own `lossy_seed` derivation) finds a marked event the resume would seed. Never mirror the loader's guard with a second check.
  - **The `lossy` marker judges AUTHOR-produced values only.** Engine keys (`_ENGINE_OUTPUT_KEYS`, top level only) and a batch host's `errors[i].exception` are exempt. Marking them would refuse every batch resume; widening an exemption beyond its exact path silences real author losses (both happened at the gate).
  - **The gate arm records a sub-workflow host's frame only when `not originating`.** A gate at this level either fired pre-exec (no frame this visit; a stale one from the previous iteration lingers, which was #659) or post-exec (step 16 already used it).

## What Was Built (actual vs. planned)
The plan's P1–P4 shipped as written. These deviations carry the knowledge:
- **Recovered-failure position (beyond plan §8's "noted, not engineered").** A mid-task reviewer reproduced it: K fails at 3, an on-error back edge re-enters K, and K's gate pauses at 4. The resume ran 3. The fix lives in `resume_iteration`: a failed final event followed by any success/cached event means "the walk moved past it" → N+1. That also covers a kill after the recovery, which the plan's pause-record idea would have missed.
- **`continue_after_step` / `prepare_resume_entry` / `ResumeEntry`** are module-level functions shared by engine and planner. The plan had the engine method plus a planner copy calling `should_reenter`. The gate's simplicity lens folded the rest of resume-entry preparation into one function too.
- **The after-K decision installs `__iteration__`** (the completed count) while it runs, because a `while: ${__iteration__}` or a `max_iterations: ${__iteration__}` must see what the live walk saw.
- **The preflight derives a substituted successor's OWN position** (`resume_iteration(events, successor)`) rather than resetting it to 1. A successor already reached by a back edge continues its count.
- **`resume_entry_iteration`** became a fourth engine stamp. It drives `⤷ Resumed from … at 'k' (iteration 3)` and the dry-run header; the text shows it only when > 1.
- **Lossy-seed refusal (C1/W1, user ruling A, scope "Option 1").** The falsifier proved that carried state restored through JSON silently diverged: int keys became strings, `__` keys were dropped, and `default=str` stringified sets, dates and Decimals. Per-iteration approval then gave a different answer from `--auto-approve`, with exit 0. This predates the task for upstream steps (Task 164). The task made it the headline path, so it was closed here.
  - **The marker:** trace events now carry `lossy: ["path: kind", …]`.
  - **The loader:** refuses a marked seeded event with `ResumeFidelityError`, which names the step, path and kind and gives the JSON-native remedy.
  - **The producer:** no longer pauses on one.
  - **Pre-2.8.0 traces** keep the binary-placeholder scan (`_predates_lossy_marker`).
  - **User-visible:** a resume whose restored upstream value would have been silently coerced now refuses with the field named, for non-loop resumes too.
  - **Deliberate strictness (ruled; falsifier round 2 confirmed it by execution):** the refusal is per EVENT, not per field read. A `datetime` stamped beside the data a downstream step actually reads still blocks failure-resume, and keeps a later gate from pausing; on `main` those runs resumed. The remedy is printed (make the result JSON-native). Option (a), refusing only when a marked path is actually referenced, was considered and not built. It would need reference tracking across carry and templates, which is a second analysis beside the seed derivation. Revisit only on an observed user complaint.
- **Not built in this task:** #656's "approve all remaining iterations" button. The checkpoint ruling ("not now") was reversed by the user after the merge: #656 is reopened as the button + the loop's limit in the gate ("iteration 1 of 3" / "of up to 3"), shipping after #714 (Approve/Deny below the gate panel's scroll fold — visible in this task's own checkpoint screenshots). The design is plan §4 P4b; the limit is not on the wire yet — it must be added to `GateRequest` at the engine's gate builder (`runtime/engine/gate.py`), which is engine contact.
- **Not built, by ruling:** a final-step loop escalation still cannot pause (ruling (b)); `approval.md` says the re-fork recipe needs a step after the loop.
- `_fully_answered_gate_ids` was KEPT. It states answer-vs-occurrence multiplicity, which continuation makes more true, not less.

## Patterns & Anti-Patterns
- **The resume entry is a (step, iteration) pair, not a mode.** `seed_walk_entry(entry_iteration=)` refines the entry's identity; `--only` is the same rule at iteration 1. A "continue" mode flag on the shared composition was rejected (Task 164's scope guard).
- **One derivation, N consumers, extended to the producer.** `lossy_seed` is `_seedable_final_events` plus a marker check, and the pause decision calls it. Whenever a producer must predict a consumer's refusal, call the consumer's derivation.
- **Mark at the writer, refuse at the reader.** Lossiness is only knowable when the value is written. The reader cannot tell a `"1"` key from a coerced `1`. Same lesson as Task 164's "writer honesty over reader compensation".
- **Anti-pattern: a separate loop-state channel** (rejected in plan §3). The guard must scan exactly what gets seeded, so a second channel means a second derivation.
- **Anti-pattern: counting same-node events for position.** It is fragile under #659-class overwrites; the event carries its own `iteration`.

## Gotchas & Non-Obvious Coupling
- **Two writers decide what survives the trace.** `_sanitize_for_json` drops keys and replaces bytes; `_flush_line`'s `json.dumps(default=str)` stringifies everything else and coerces non-string keys. The marker check therefore sits in the sanitizer, before the `default=str` fallback. Any new event writer that bypasses `record_node_execution` must route `node_output` through the sanitizer, or it ships unmarked lossy data.
- **Restored re-records must copy `iteration` AND `lossy`**, or resume-of-a-resume restarts at 1 or silently seeds a lossy value.
- **A sub-workflow host emits no `node.start`.** A looping host killed mid-iteration therefore reads as "between iterations" (`(None, H)`). That is why `_side_effect_refusal` checks `entry_node_id or last_completed_node_id`, and why it can ask about a loop step that won't re-run after the loop exits (accepted cost).
- **A `code` loop step is a dynamic router.** Killed between iterations, it refuses rather than continuing; the guide says so.
- **The run-start "will pause at approval gate(s)" note and the dry-run ⏸ footer can promise a pause that doesn't happen**, when a gate later stays `failed` for a lossy seed. This can't be known before the upstream step runs; the gate's error states the real reason.
- **Known limit, documented in ADR-0010 and `runtime/CLAUDE.md`:** only the entry step's loop counter is restored. A hand-written back edge into a loop step restarts it at 1 when the pause is at a different step, or when a resumed attempt that continued after a recovered failure is itself killed. The fix is `loop_positions` in the attempt's meta line, which needs `META_KEYS`, `_meta_fields` and the fixture builder to move together. No observed case yet.
- **Not covered here:** `--only` still seeds `lossy`-marked events (ADR-0002's own limitation; ruled out of scope).
- **Not covered here:** str/int `Enum` values are written as their plain value and are unmarked (same family as tuple→list).
- **Task-159 baseline:** this branch adds no drift. The 5 drifts after #704 also drift on an export of pristine `origin/main` `baf2d73f` (checked with `run-case.sh`); they belong with #680.

## Integration Points
- **Trace 2.8.0 (additive):**
  - `iteration` on loop-node events and on `gate` lines (opt-in key, absent when `None`, so `TraceFixtureBuilder` parity holds);
  - `iteration` inside `gate_request` (`null` for non-loop gates);
  - `lossy` on events.
  - `RESERVED_LINE_KEYS` unchanged; consumers still gate on `startswith("2.")`.
- **`GateRequest.iteration`** (additive, ADR-0009 payload). It reaches `masked_gate_dict`, so the CLI JSON pause document, `GET /api/gate` and the web eyebrow see it. `PausedRun.iteration` feeds `resume list` (text `approval · iteration 2`, JSON `iteration`).
- **Engine ctor:** `resume_iteration`, and `resume_after` (mutually exclusive with `resume_from` and `only_node`). The runner maps an after-K `ResumeSource` (`entry_node_id=None`, `entry_iteration ≥ 2`) to `resume_after`; anything else unresolved still raises `ValueError`.
- **`ResumeSource.entry_iteration`** (default 1; `None` = no recorded position).
- **`ResumeFidelityError`** now carries `lossy` entries and covers all four loss kinds. The web bridge's refusal vocabulary is unchanged (same class).
- **Execution JSON:** `execution.resume_entry_iteration`; the dry-run `resume.entry_iteration`. Pause output now keeps WARNING/INFO diagnostics (`diagnostics` in JSON; `errors` stays `[]`).
- **Serialize behind this:** #690 (it touches `_side_effect_refusal`, which changed here) and #458 (the `--only` snapshot surface).

## Tests That Matter
Run `test_resume_source.py`, `test_resume_engine.py`, `test_resume_lossy.py`, `test_gate_pause.py`, `test_gate_trace.py`, `test_only_snapshot.py`, `test_plan_drift.py`, `test_paused_cli.py` and `test_resume_cli.py` when touching any of this. Each ★ below was mutation-verified (Edit + revert).
- ★ `test_loop_k_resumes_at_the_failed_iteration` — the stance pin. It asserts the effects file is exactly `1 2 3 3 4 5`; a restart gives `…1 2…`. It replaced the weak pin that could not tell the stances apart.
- ★ `test_resumed_carry_loop_matches_an_uninterrupted_run` — content-asserting carry identity (Task 166's lesson).
- ★ `test_only_loop_target_against_a_resumed_attempt_never_seeds_its_own_output` — the `>=` rule. It fails alone under `==`.
- ★ `test_approval_after_a_recovered_failure_resumes_at_the_gated_iteration` and `test_kill_after_a_recovered_failure_continues_past_the_failed_iteration` — the recovered-failure rule.
- ★ The D2b pair: `test_answered_loop_escalation_then_failure_resumes_with_the_recorded_decision` and `test_earlier_iteration_answer_never_decides_a_later_unanswered_escalation`.
- ★ The parity nets: `test_engine_and_planner_mid_loop_resume_state_match`, `test_engine_and_planner_resume_after_loop_step_decide_alike` and `test_resumed_plan_applies_the_carry_guard_like_the_engine`.
- ★ `TestResumeAfterLoopStep` — falsy exit, cap exit, the condition seeing `__iteration__`, and the template cap.
- ★ `test_escalation_pause_mirrors_the_preflight` — producer ↔ preflight.
- ★ `test_looping_gated_host_keeps_first_iteration_event` (#659). The existing orphan pins guard the `not originating` conjunct's other half.
- ★ `test_resume_lossy.py` — each falsifier repro paired with a JSON-native twin:
  - refusal names the key;
  - the gate does not pause on a lossy seed;
  - the escalation half;
  - engine-key and batch-exception exemptions;
  - batch items are marked.
- `test_approve_yes_on_loop_gate_pauses_each_iteration_until_done` + `test_loop_gate_position_reaches_every_pause_surface` + `test_mcp_loop_pause_then_cli_resumes_each_iteration` — the user-visible chain on CLI, JSON, `resume list`, the refusal and MCP.
- `test_refork_recipe_pauses_and_resumes_non_interactively` — the documented escalation recipe.
- `test_trace_without_loop_position_restarts_the_loop_and_says_so` — old traces never guess.

---
*Distilled from the implementation context of Task 179. The chronological journey lives in `implementation/progress-log.md` — this review is the durable forward-reference, not a re-narration of it.*
