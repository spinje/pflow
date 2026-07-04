# Task 164 Review: Resume Workflow From a Failed Node

## Metadata
- Implemented 2026-07-04 on branch `feat/resume-failed-node` (spec/decisions locked 2026-07-03).
- Commits: `66652b83` (Phases 0+1), `34324519` (Phase 2 + wedge fix), `cf11e281` (Phases 3–6),
  `717fe445`+`04474c30` (review-fixes batch: 3 proven-bug fixes + agent-UX pass — see progress
  log entries "Review-fixes batch" onward). A post-merge-prep **deep-review batch** followed
  (2026-07-04, 5-agent battery): escalation-fold fix + seed-scope consolidation — see the
  progress-log deep-review entry. Not merged.
- Verification at close: `make test` **8489 passed, 0 failed**; `make check` green; every subtle
  assertion mutation-verified (Edit + revert, never `git stash`).
- Pending human items: sign-off on (1) seed-fidelity reaching `--only` degraded snapshots,
  (2) Decision 6/7/9 letter refinements (annotated in the spec, intent preserved), (3) the JSON
  failure document's `execution_id`/`resume_command` fields, (4) zero-event traces now `failed`;
  plus the plan-designated manual browser check (`make ui-build` + `pflow ui` over a resumed run).

## Read First — the load-bearing block

**What exists now:** `pflow resume [TARGET] [KEY=VALUE]... [--force] [--dry-run]` resumes a failed
OR interrupted (Ctrl+C/SIGKILL) run: the loader picks the source trace and entry step, the engine
seeds upstream outputs and re-enters the **existing** walk (one loop, parameterized entry), and the
attempt writes a new self-contained trace linked via `resumed_from`.

**Read these first:**
- `src/pflow/runtime/workflow_trace.py` — `ResumeSource`, `load_resume_source` (refusal ladder),
  `_terminal_failure_root` (entry rule), `_resolve_incomplete_entry`, `seed_snapshot_into_shared`,
  `_attempt_consumed_work`.
- `src/pflow/runtime/engine/engine.py` — `seed_walk_entry` (shared with `--only` + planner),
  `_prepare_resume` (seed → init → stamps → Decision-6 re-record).
- `src/pflow/cli/commands/resume.py` — target disambiguation, hash gate, between-nodes successor,
  side-effect policy.
- `src/pflow/core/exceptions.py` — `ResumeSourceError` + 9 subclasses (the agent-facing contract).
- `src/pflow/execution/plan.py::_resolve_walk_start` — the planner mirror (dry-run parity).

**Invariants that must NOT break:**
- **Unrecovered-set check runs BEFORE frontier selection** in `_resolve_resume_entry`. It is NOT
  redundant: a recovered failure can be the trace's last event when its on-error handler was
  gate-stopped — frontier-only logic resumes at that failure instead of refusing at the gate.
  Sole pin: `test_gate_stop_at_the_on_error_handler_refuses_naming_the_gate` (every other test
  stays green if you "simplify" this away).
- **Two node-type vocabularies.** A trace event's `node_type` is a Python CLASS name
  (`"LLMNode"`); `is_side_effecting` consumes IR REGISTRY names (`"llm"`). Feeding an event's
  type to the predicate force-confirms the idempotent-llm path (`is_side_effecting("LLMNode")` is
  True). `ResumeSource` deliberately carries NO node-type field; the CLI derives K's type from
  `resolved.ir["nodes"]` only.
- **Seed = the seedable set, everywhere.** `_seedable_final_events` (deep-review consolidation)
  is the ONE derivation — final events before the entry, minus failed-final-status nodes (their
  data lived in `__failures__`, never the store). `seed_snapshot_into_shared` writes from it and
  returns it; the loader guards scan its values; `restored_nodes` and the re-record loop derive
  from the returned map. Filtering at a call site instead re-opens the silent-wrong-data
  coalesce bug; scanning more than it (e.g. superseded loop-iteration events) re-opens the
  guard-superset false-refusal.
- **Escalation markers fold BEFORE the guards run.** A node's event freezes its marker UNDECIDED
  (engine records at step 16; the gate writes the decision into the live store at 17.7); the
  decision survives only as a disk-only gate resolution line. `_apply_gate_resolutions` folds
  resolutions into the events at load time — remove it and every resume with a RESOLVED upstream
  escalation false-refuses (`test_resolved_escalation_upstream_resumes_end_to_end` is the
  real-collector pin), and attempt traces stop carrying the decided marker (breaking
  resume-of-a-resume without re-joining gate lines).
- **`resumed_from` is set on the collector at CONSTRUCTION** (before `start_streaming`) — it rides
  the meta line. `_meta_fields` + `core/trace_io.META_KEYS` + the test fixture builder move
  together or the field misroutes to the trailer.
- `_iter_workflow_traces` never gains a `final_status` filter (each consumer owns status policy);
  `runtime/` never imports `ui/` (the local flock probe + raw-line reader duplication is the
  accepted price); every raw-JSONL need goes through `_iter_raw_trace_lines`, nothing else.
- Restored events are GENUINE events (in-memory AND disk) — unlike `gate`/`node.start` lines,
  which stay disk-only. They must reach `final_events_by_node` or self-containment breaks.
- `resume_from` + `only_node` are mutually exclusive (engine `ValueError`); a `ResumeSource` with
  `entry_node_id=None` must never reach `runner.run` (the CLI resolves it first; runner guards).

## What Was Built (actual vs. planned)

The plan (implementation-plan.md) was followed phase-for-phase; the divergences are where the
knowledge is:

- **The entry rule was replaced after implementation — twice removed from the spec's wording.**
  Decision 9's "earliest failed node in EVENT order" was implemented as `min(unrecovered set)` and
  was WRONG for `K --on-error--> F` both-fail chains: recovery warnings stamp at **routing time**
  (engine step 17.5 — before F even runs), so the primary is always "recovered" and selection
  returned the fallback. Final rule: `_terminal_failure_root` — earliest failed node with no
  success/cached node after it in event order. Two synthetic tests had encoded fictional shapes
  that masked this (see Tests).
- **Seed fidelity (post-review):** failed-final-status nodes are never seeded — proven divergence:
  a `${primary.x ?? fallback.x}` coalesce in the resumed tail resolved the seeded failed primary
  (`used=`) instead of falling through (`used=fallback-data`). Side effects of the fix: `--only`
  degraded-snapshot seeding changed identically (same latent bug), and Decision 6's re-record no
  longer flips a failed-recovered node to cached-success in the attempt trace.
- **Incomplete tails ending in a FAILED event** re-enter at the terminal-failure root; the
  between-nodes single-default-successor rule applies only to success-ending tails (proven: the
  old rule resumed past an unhandled failure, and skipped an on-error handler by taking the
  default edge the run never took).
- **Wedge fix (mid-implementation discovery):** a resume attempt that dies before executing
  anything used to finalize as `success` on disk (zero-event `_determine_trace_status` lie) and
  permanently consume the attempt chain. Now: zero-event runs finalize `failed` (GLOBAL trace
  semantics change), and the superseded scan counts only attempts that **consumed work**
  (`_attempt_consumed_work(path, candidate)`: ≥1 non-restored event OR a dangling top-level
  `node.start` OR live flock) — the liveness clause closes a minutes-wide double-resume race during
  K's first execution.
- **Dead vs interrupted attempt tracking (PR #559 review, C1+C4):** `_attempt_consumed_work` grew a
  `path` arg and a **dangling-top-level-`node.start`** check (extracted as `_dangling_top_level_starts`,
  shared with the incomplete arm) — an attempt SIGKILL'd MID-step reconstructs to restored-only
  events (the dangling start is dropped), so the old content-only predicate mislabeled it "did
  nothing." Consequences it now prevents: (C1) `resume <source>` re-running a started step because the
  mid-step attempt failed to supersede; (C4) `resume <workflow>` wedging on a dead zero-work attempt
  instead of falling through to the older resumable run. The workflow-name selector
  (`_select_resume_trace`) skips a candidate only when it did no work AND is not live — a run
  mid-startup is selected then refused as still-running, never skipped (race guard); by-exec-id never
  skips. One deliberate message shift: `resume <workflow>` on a lone meta-only crash now gives the
  generic "no resumable run" (the specific "before its first step" message stays reachable via
  by-exec-id). Both bugs were reproduced against production BEFORE the fix and graduated as
  mutation-verified pins in `test_resume_source.py`.
- Smaller deviations, each logged with rationale: third engine stamp `resume_entry_node` (the
  indicator needs K; the two planned stamps didn't carry it); `ResumeSource.workflow_path` field
  (by-exec-id resume must re-resolve the workflow); bare `pflow resume` is a usage error; Phase 3
  shipped without `--dry-run` so no milestone had a lying flag; dry-run keeps the stale-hash gate
  but skips the side-effect confirm (nothing executes); dynamic-router refusal = "last completed
  is a `code` node" (`has_dynamic` is parse-only, not in the IR — safe over-approximation);
  failure surfaces gained the resume hint on stderr (survives `-p`) and `execution_id` +
  `resume_command` in the JSON failure document.

## Patterns & Anti-Patterns

- **Frontier over bookkeeping:** derive "where to re-enter" from event statuses alone
  (`_terminal_failure_root`), never from warnings — incomplete traces have NO warnings (the
  trailer that carries them is exactly what an interrupted run lacks), so any warnings-based rule
  is structurally impossible on half the inputs. This is why the same function serves both arms.
- **Writer honesty over reader compensation:** the wedge fix pattern. When a trace lies
  (zero-event "success"), fix the writer for every consumer; only then add the reader-side policy
  (consumption predicate). A loader-only guard would have left the UI showing a crashed run as ✓.
- **Probe-then-graduate:** the review bugs were established by temporary tests asserting the
  CORRECT semantics (failure ⟺ bug), then graduated as regression pins. Beats arguing from code
  reading; the probe is the evidence and becomes the test.
- **Call-site parity pins for mirrored surfaces** (engine↔planner): unit tests on the shared
  helper cannot catch a re-fork; only `test_engine_and_planner_walk_entry_state_match` (+ resume
  variant) can. Both mutation-verified in both directions.
- **Anti-pattern — "mirrors X" docstrings without a pin.** Both review bugs and the guard-scope
  loose end trace to a helper whose safety claim ("failed traces already rejected by the loader",
  "mirrors seed_snapshot_into_shared") drifted when a second caller class arrived. If you write
  "mirrors/assumes X", either derive from X or pin it.
- **Anti-pattern — synthetic fixtures encoding shapes production never writes** (tests/CLAUDE.md
  pitfall #19, twice bitten here): the fictional both-fail fixtures omitted the recovery warning
  real routing always stamps. Defense that worked: one keystone test driving a REAL failed run
  through `WorkflowRunner` + verifying fixture shapes against producers, not against the reader.

## Gotchas & Non-Obvious Coupling

- **"Recovered" means "an error edge exists", not "the recovery succeeded."** Both channels
  (`on_error_recovery` at engine step 17.5; `api_warning` with `recovered=True`) stamp when the
  handler EXISTS, before it runs. Any logic reading recovery warnings as outcomes is wrong.
- **`failed_node_ids` on disk is alphabetically sorted** — display/aggregate data, never
  entry-selection input.
- **JSON failure output cannot know the finalized trace path**: `set_json_output` mutates the
  trace during output handling, so finalize happens in the `finally` AFTER the JSON document is
  printed. `_resumable_execution_id` therefore gates on trace-enabled + the collector's private
  `_stream_failed` (accepted single-consumer private read) instead of `ctx.obj["trace_file"]`.
- **The resume affordance is gated by a SOUND SUPPRESSOR, not a full loader mirror** (C2): both the
  stderr hint (`_maybe_echo_resume_hint`) and the JSON `resume_command` (`_resumable_execution_id`)
  gate on `collector.has_resumable_step()` — the loader's STATUS arm only
  (`_determine_trace_status == "failed"` AND a non-empty unrecovered set), computed IN MEMORY
  because the JSON path runs pre-finalize. Contract: **`False` ⟹ the loader definitely refuses**
  (safe to hide the hint); **`True` is necessary-not-sufficient**. It deliberately does NOT replicate
  the loader's seed-scope guards (lossy-binary / undecided-escalation) — those need the disk-only
  gate-resolution fold (`_apply_gate_resolutions`), and replaying it in memory would FALSE-refuse a
  resolved escalation (a false negative that hides the hint on a resumable run — the dangerous
  direction). So a rare lossy-upstream failure may still show a hint that then refuses (an actionable
  refusal). It kills the C2-reported dead-ends: all-steps-succeed-but-output-unbuildable (trace
  `final_status` is `success`), zero-step crash, gate stop. Do NOT "simplify" to "did any step run":
  a recovered failure is a completed step but not a resumable one. The sound direction is pinned by
  `test_has_resumable_step_agrees_with_the_loader_on_common_cases` (drives BOTH surfaces on real
  runs — a shallow "assert the predicate in isolation" test would not catch predicate↔loader drift).
- **Trace-fixture rules that cost real time:** gate/`node.start` lines must be spliced BEFORE
  `run.complete` (content after the trailer raises); a leaf's terminal event REUSES its
  `node.start`'s reserved id (dangling-start detection is exact id matching); top-level scoping
  of the dangling scan is load-bearing (a sub-workflow kill leaves a dangling CHILD start whose
  id isn't in the top-level graph).
- **`reconstruct_trace_from_lines` merges meta + trailer into one flat dict** — a reader finds
  `resumed_from` regardless of which line carried it (why the superseded scan worked before
  META_KEYS gained the field).
- **Restored-event blob re-interning is automatic** (re-record flows through `_flush_event` with
  a fresh per-run declared set) — pinned on-disk by the ≥2 KB round-trip test; a re-record path
  that bypassed `_flush_event` would fail it.
- **Restored `node_output` stamps on `is not None`, not truthiness** (restored-only branch) — a
  real `{}` output must survive a second resume as `{}`, not as absent (coalesce distinguishes).
- **UI renders restored as "cached" on purpose:** unknown status strings are silently DROPPED by
  the frontend (`RUN_STATUSES` allowlist, events.ts) — an honest `"restored"` status renders as
  nothing without a two-file frontend change. `restored: true` is stripped by the tailer
  projection and never reaches SSE.
- **Loop-K restarts at iteration 1** (loop state is engine-ephemeral, never traced) — documented
  stance, not an accident; don't "fix" it.
- **`make check` couldn't see untracked files** (pre-commit filters by `git ls-files`) — fixed in
  the Makefile (git-agnostic `ruff check .` runs first). For NEW files, that fix is why lint
  errors now fail fast.
- **Guide prose needs outside-reader eyes:** the agent-UX review pass caught message leaks but
  read the guide with spec-primed eyes — "K" (×4) survived until the owner caught it. Vocabulary
  scrubs should grep guide prose for single-letter shorthand explicitly.

## Integration Points

- **Task 171 plugs in here** (its designer should read this first): `load_resume_source`'s
  gate-stopped refusal arm is the `paused` insertion point (one added arm, entry =
  `paused_node_id`); `_attempt_consumed_work` is reusable for `resume list`; the CLI subcommand
  extends with token addressing. **Before adding the arm, extract the loader into
  `runtime/resume_source.py`** — the accretion note + trigger is recorded in task-171.md.
  **UI attempt-chain rendering is folded into 171** (owner decision 2026-07-04): surface
  `resumed_from` in `/api/runs` + link/group a chain's attempts in the run selector — see
  task-171.md "UI attempt-chain rendering" for the scoped list.
- **Contracts changed:** trace format → **2.6.0** (meta `resumed_from`, event `restored`;
  additive — `startswith("2.")` gates unaffected); zero-event runs now trail `failed` (all trace
  consumers); `--only` no longer seeds failed-recovered nodes from degraded snapshots; JSON
  failure documents gain `execution_id`/`resume_command`; success JSON gains
  `resumed_from`/`nodes_restored`/`resume_entry_node`.
- **Depends on (reads, doesn't build):** streaming JSONL transport (172), `content_hash` (173),
  `meta.inputs` (175), `--only` seed machinery (#443), gate channels (125).
- **Threading shape:** CLI → `execute_json_workflow` via `ctx.obj["resume_source"]` →
  `WorkflowRunner.run(resume_source=)` kwarg (the 125 `gate_resolver` precedent — RunnerConfig
  stays primitive-typed) → collector `resumed_from` + engine's three resume params.
  `seed_walk_entry` now has four callers (engine `--only`, engine resume, planner `--only`,
  planner resume); scope guard stands: if it grows a mode flag or callback, back off.
- **MCP is deliberately outside:** MCP runs write no trace; the hint gates on `trace_file`, the
  JSON fields ride a CLI-only kwarg, and `mcp_server/` contains no resume mention — an MCP agent
  is never told to run a command that can't work.

## Tests That Matter

Run `tests/test_runtime/test_resume_source.py`, `tests/test_runtime/test_resume_engine.py`,
`tests/test_cli/test_resume_cli.py`, and `tests/test_execution/test_plan_drift.py` when touching
anything above. The ones guarding real regressions (★ = mutation-verified):

- ★ `test_engine_and_planner_walk_entry_state_match` + `test_engine_and_planner_resume_entry_state_match`
  (plan_drift) — the ONLY net that catches an engine/planner re-fork; 8384 other tests passed a
  deliberately drifted fork during verification.
- ★ `test_gate_stop_at_the_on_error_handler_refuses_naming_the_gate` — sole pin for the
  unrecovered-check-before-frontier ordering (bypassing the check fails ONLY this test).
- ★ `test_both_primary_and_fallback_fail_resumes_at_the_primary_e2e` + the rewritten loader pair —
  the frontier rule against REAL on-error traces.
- ★ `test_recovered_failure_upstream_is_not_seeded` — the seed-fidelity coalesce bug
  (`used=fallback-data`), plus restored-list and re-record exclusions.
- ★ The two incomplete-tail tests (`…unrecovered_failure_reenters_at_the_failure`,
  `…killed_before_the_error_handler…`) — failure-ending tails never take the default edge.
- ★ `test_attempt_trace…`/`test_resume_of_a_resume…`/`--only`-after-resume poisoning regression —
  Decision 6 self-containment (disable the re-record loop → exactly these fail).
- ★ `test_refused_attempt_does_not_wedge_the_chain` — writer honesty + consumption predicate.
- ★ `test_resolved_escalation_upstream_resumes_end_to_end` + the three synthetic fold pins
  (dict/string/last-resolution-wins) — the escalation false-refusal (deep-review); disabling
  `_apply_gate_resolutions` fails exactly these four.
  `test_superseded_iteration_escalation_does_not_refuse` pins the guard-scans-seedable-set-only
  consolidation (`_seedable_final_events`).
- `test_real_failed_run_is_resumable_end_to_end` — the keystone that makes the ~30 synthetic
  loader fixtures trustworthy (a loader reading fields production never writes would refuse here).
- `test_llm_failed_node_resumes_without_confirmation` + the `is_side_effecting` matrix — pins the
  registry-name vocabulary (`LLMNode` → True is the trap being guarded).
- `test_crafted_failure_before_a_success_refuses_instead_of_crashing` — loader totality (typed
  refusal, never a raw `ValueError`, on engine-unproducible traces).
- CLI: `-p` hint survival, JSON `execution_id`/`resume_command` presence + `--no-trace` omission.

---
*Distilled from the implementation context of Task 164. The chronological journey — including the
six-phase build, the wedge fix, the entry-rule bug hunt, and the review-fixes batch — lives in
`implementation/progress-log.md`; the fix-batch plan is `implementation/review-fixes-plan.md`.
Decision rationale: task-164.md (Decisions 1–9, with 2026-07-04 refinement annotations) and
ADR-0010 (as amended).*
