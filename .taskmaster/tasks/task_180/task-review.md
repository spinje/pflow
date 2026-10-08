# Task 180 Review: Resume Refuses Only When an Edit Touches a Restored Step

## Metadata
- Implemented 2026-10-08 on `feat/task-180-resume-step-identity` (main `1d393487` merged in). Planner: Fable. Orchestrator: Opus.
  Implementers (all Opus): P1 (engine); P2+P3 on a fresh one; P4 plus the completion gate on a third.
- Closes #690. Narrows (does not delete) PR #719's batched-host carve-out. Trace format **2.8.0 → 2.9.0** (additive).
- Ruled behaviour: `implementation/show-before-code.md` (16 rows; `--force` stays one flag).
- Journey, every deviation, every gate finding and its disposition, and the observed output of all 16 rows: `implementation/progress-log.md`.
- Review reports: `implementation/reviews/` (P1 and P3 mid-task reviews, the completion battery, the falsifier).

## Read First — the load-bearing block
- **What exists now:** every trace's meta line records `step_identity`. That is each top-level step's definition hash (everything except prose) and its outgoing routes, plus the start step. Resume refuses only when a step whose saved output it restores was edited, removed or rerouted, when the workflow now starts elsewhere, when the resume point is gone, or when a paused approval step being approved was edited. Edits at or after the resume point, and prose anywhere, pass without `--force`. Separately, every step that begins now writes a top-level `node.start`, batched sub-workflow hosts included.
- **Read these first:**
  - `execution/resume_preflight.py`: `_check_workflow_identity`, `_identity_changes`, `_side_effect_refusal` (the D1b conjunct).
  - `core/workflow_id.py::step_identity`, and `core/ir_schema.py::outgoing_edges` / `start_node_id`.
  - `core/exceptions.py`: `StepIdentityChanges`, `ResumeStaleWorkflowError`, `_rerouted_lead`.
  - `runtime/workflow_trace.py`: `begin_node` / `descend` (the `_pending_start` takeover).
  - `execution/runner.py::WorkflowRunner.preflight`.
- **Invariants that must NOT break:**
  - **The checked set is `restored_node_ids(source)`, Task 179's seed derivation, never "steps with events".**
    - Attempt traces re-record only seeded steps, so a step that failed and recovered has no event in an attempt.
    - Deriving the set from events false-refuses an unedited resume of a resume (pin: `test_resume_of_a_resume_with_a_failed_recovered_start_step_passes`).
  - **The resume point is never compared, except a paused approval being APPROVED, and then only its definition.**
    - Comparing its `next` refuses "a step added after the gate".
    - Checking it on `--approve no` refuses a denial, which runs nothing.
  - **Fail-closed on the recorded map.** A checked step that is missing from the map, or malformed in it, counts as edited, never as unchanged (pins in `test_resume_preflight.py`). A meta `step_identity` that is not a dict with a `steps` dict loads as `None`, which means the whole-hash fallback. A silent "no change" here restores stale outputs with exit 0.
  - **D1b keys on ABSENCE of `step_identity`, not on the version number.**
    - Traces 2.3–2.8 carry `content_hash` but never wrote a batched host's `node.start`, so their "never started" proof is false for a `workflow`-type entry, and the confirmation must still be asked.
    - Keying on the number would break the moment Task 183 or anyone else takes the next minor.
  - **What `step_identity` hashes is part of the trace format** (rule stated at `TRACE_FORMAT_VERSION`). Change the recipe → bump the minor AND make the preflight treat older maps as absent. **That version guard does not exist yet** (one recipe so far): whoever changes the recipe must add it, or every old trace refuses with a false "'X' was edited".
  - **`begin_node` reserves for every node on a run-scoped collector, streaming or not; `descend` takes over that frame only on a matching `node_id` AND the same enclosing host.** That one seq is what the completion event reuses. A second reservation shifts every later seq and orphans children. On-disk `event` seqs are byte-identical to 2.8.0: the falsifier diffed main against the branch over 7 workflows, and the only differences were the meta key and the batched host's start.

## What Was Built (actual vs. planned)
P1–P4 shipped as planned. These deviations carry knowledge:
- **Gate arm records with `start_frame`, not `host_frame`.** The local `host_frame` is assigned only after `node._run` returns, so it is always `None` on a raise. After the takeover, `WorkflowExecutor._host_frame` was dead and was removed; its ascend guard is now `run_collector is not None`. The gate arm also drains the batch trace, so a batched host stopped by an item's gate keeps its completed items.
- **Per-step `cache` map (format shape beyond D2).** A step that uses `## Cache` chunks also records `cache: {chunk: hash}`. Without it, the ruled row-10 text "(a `## Cache` chunk it uses changed)" can't be told apart from a change in which chunks the step selects. The lead fires only when a chunk used both before and now changed its content.
- **One edge reader.** `ir_schema.outgoing_edges` (`from`/`source`, `to`/`target`, missing `action` → `"default"`) serves both `step_identity` and the preflight's `_single_default_successor`. The compiler's `_wire_nodes` keeps its own loop because it rejects malformed edges. `start_node_id` is likewise one rule for the compiler and the graph build; `core/workflow/context.py` uses a different rule on purpose.
- **"Skipped" is computed, not assumed.** A new route target or a new start step is reported as skipped only when the resume neither restores it nor reaches it, over any route, from where it continues: `_reachable`. A plain between-nodes source continues from its last step's current successors.
  - An `error` route never counts, because the restored step succeeded.
  - The `--force` suggestion names the skipped step ("('prepare' is skipped)") only when there is one; old traces say "(a step inserted among them is skipped)".
- **Refusal text was tightened beyond the ruled block's wording, by the mid-task and completion agent-ux rounds; no ruled lead and no refuse/pass outcome changed:**
  - Approval-edited and between-nodes bodies no longer claim "that edit would not take effect" (under `--force` the step runs).
  - Routes carry their action ("'shape', 'alert' on error instead of 'shape'").
  - Row 13 keeps a second, true lead for the predecessor's changed `next`.
  - Resume point gone: no `--force` offer, because the engine refuses a removed K anyway.
- **`ResumeStaleWorkflowError(changes: StepIdentityChanges | None)`.** A typed frozen record replaced a `dict[str, Any]` splatted as kwargs. `None` means the whole-hash fallback. `cache_edited` and `skipped` qualify other changes and are not truthy alone. JSON `context` carries `changed_steps`, `new_start`, `resume_point` and `resume_point_missing`; `node_id` is set when exactly one step is named.
- **`WorkflowRunner.preflight(workflow, params) -> PreparedWorkflow`** (prepare + validate + strip + compile). `plan()`, `/api/run` and `/api/resume` all call it, so an edited workflow with a validator-only ERROR is a 400 before spawn. That spawn used to die silently, and it became reachable without `--force` because of this task. Order is unchanged: `preflight_resume` → side-effect raise → `preflight`.
- **Not changed:** `--only` (D8), the UI replay banner (whole `content_hash`, prose included — correct for "different version"), and `web/` components. PR #744 already renders `errors[0]` verbatim; only the two web test fixtures got the new strings.

## Patterns & Anti-Patterns
- **Static identity from the IR, not the engine's memo `config_hash`.** The memo hash varies per loop iteration (rendered prompt-cache content) and omits `loop`/`retry`/`approval` and edges. Rejected; reuse would tie resume correctness to cache-key evolution.
- **One meta map, not per-event stamps.** Per-event hashes would make restored re-records copy a third key (Task 179's "copy `iteration` AND `lossy`" trap).
- **"Definition minus prose", fail-closed.** Policy-only keys (`retry`, `cache`, `prewarm`, `batch.parallel`) count as edits. A new node key (Task 118's `env:`) is covered automatically. A denylist is the later refinement if over-refusal is ever observed.
- **Refusal text must only claim what resume will do.** Three gate rounds each found a lead that over-claimed: "would not take effect" under `--force`, "would skip it" for a reachable step, a skip claim for an error route. When adding a lead, decide it from the same derivation the engine walks (`_reachable`), not from the edit's shape.
- **Anti-pattern: a deterministic-looking sleep in a parallel batch test.** The batch trace is appended in the worker after the child returns, so even a marker file races it. Use `max_concurrent: 1` (still the worker path, ordered by submission).

## Gotchas & Non-Obvious Coupling
- **The hash covers the RESOLVED IR as the parser emits it.** A parser or normalisation change that alters node dicts for unchanged source changes every hash. Every resume of an older trace then refuses with a false "'X' was edited". The same was true of `content_hash`, but the message now names a step. Hold IR emission stable, or bump the minor with the version guard above.
- **Precision limit after `--force` (accepted, plan D5):** a forced attempt's meta records the IR it ran with, so resuming that attempt passes even though a restored output predates the edit. The falsifier confirmed this is no worse than before.
- **Child-file edits of a `type: workflow` step are invisible** to both hashes (row 15); only the `workflow:` path string is hashed. A future fix inherits the recipe-stability rule.
- **A between-nodes source (interrupted or escalation-paused) with a step inserted right after `last_completed` refuses,** per the ruled "now leads somewhere else". Under `--force` the inserted step RUNS, because the successor resolves against the current workflow. This is a ruling-refinement candidate (pass it), surfaced upward, not built.
- **`node.start` now dangles for a killed batched host**, so the resume entry is the host and the confirmation is asked (`test_run_killed_inside_a_batched_host_resumes_at_the_host`). The overlay also shows a batched host `running` for the first time.
- **The meta line grows ~60 bytes per step**; both meta readers use `readline()` (no bounded window).
- **#729** (a partial trace offered to resume) is not made trivial by `step_identity`; it is an entry-resolution question in `_resolve_incomplete_entry`.
- **Pre-existing, seen during the gate, not fixed:**
  - Web "Resume anyway" is offered when the resume point is gone.
  - The replay banner overlaps the refusal panel title at 760×560.
  - A failed `--only` run prints an unusable resume hint.
  - A batched host stopped by a child gate resumes as "marked failed but has no failed step".

## Integration Points
- **Trace 2.9.0:**
  - meta `step_identity` (`trace_io.META_KEYS`, `_meta_fields`, `tests/shared/trace_jsonl.py` iterates META_KEYS);
  - `node.start` for batched hosts;
  - `ResumeSource.step_identity` (`_recorded_step_identity` type guard);
  - `run_tailer._read_meta` pops the key, for memory only;
  - `content_hash` is still written (UI banner, `entry_never_started`'s post-173 gate, old-trace fallback).
- **Web bridge:** same class, same `refusal: "stale_workflow"`, `hash_known` kept, `context` fields added. The panel renders the server text verbatim.
- **CLI/JSON:** `errors[0].context.{changed_steps,new_start,resume_point,resume_point_missing}`, plus an "At: node 'X'" line when exactly one step is named.
- **Task 183** takes the next trace minor (2.10.0) and re-pins `test_format_version_is_2_9_0`.

## Tests That Matter
Run `test_resume_identity.py`, `test_resume_cli.py`, `test_paused_cli.py`, `test_resume_preflight.py`, `test_resume_source.py`, `test_emit_time_trace.py`, `test_workflow_id.py`, `test_plan_drift.py` and `test_ui_interaction_server.py::TestResumeEndpoint` when touching any of this. Every pin below was mutation-verified (P1 M1–M5/M3b, P2 ×4, P3 M1–M10/M4b, plus each gate fix):
- `tests/test_cli/test_resume_identity.py` — one real-CLI test per ruled row (`test_row1_…` through `test_row16_…`), plus:
  - the D1b pair `test_batched_host_on_an_older_trace_still_needs_confirmation` / `test_batched_host_without_a_start_on_a_current_trace_is_proof_it_never_began`;
  - `test_rerouting_to_a_step_the_resume_still_reaches_never_claims_it_is_skipped`;
  - `test_an_added_on_error_route_to_a_new_step_refuses_naming_the_action_without_a_skip_claim`;
  - `test_a_forced_attempt_records_the_workflow_it_ran_with`.
- `test_paused_cli.py`:
  - row 14 `test_editing_the_approved_step_refuses_and_force_proceeds`;
  - `test_denying_an_edited_approval_step_passes_and_ends_denied`;
  - `test_a_step_added_after_the_paused_gate_passes_and_the_gate_runs`;
  - the escalation trio, incl. `test_a_step_inserted_after_the_escalation_refuses_without_claiming_a_skip`.
- `test_resume_preflight.py` fail-closed arms: `test_a_restored_step_missing_from_the_recorded_map_counts_as_edited`, `test_a_malformed_recorded_step_counts_as_edited_never_as_unchanged`, `test_the_resume_point_itself_is_never_compared`.
- `test_emit_time_trace.py` P1 pins:
  - `test_batched_host_writes_one_paired_top_level_start`;
  - `test_non_batched_host_writes_exactly_one_start_per_visit` (the double-begin catch);
  - `test_batched_host_stopped_by_an_item_gate_pairs_its_start_and_keeps_completed_items` (sequential + parallel; gate-arm guard + drain);
  - `test_descend_takes_over_only_the_frame_begun_for_that_host`;
  - `test_host_whose_post_raises_after_descend_keeps_its_child_linked` (in-memory orphan).
- UI: `test_validator_only_error_in_an_edited_workflow_is_400_with_every_error` and `test_relative_sub_workflow_and_new_optional_input_pass_the_preflight` (the false-400 pair that a hand-copied validator would fail). `test_plan_drift.py::test_plan_and_preflight_refuse_the_same_pre_trace_error`.

---
*Distilled from the implementation context of Task 180. The chronological journey lives in `implementation/progress-log.md` — this review is the durable forward-reference, not a re-narration of it.*
