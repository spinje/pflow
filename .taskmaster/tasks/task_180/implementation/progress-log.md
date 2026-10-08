# Task 180 — progress log

## [2026-10-07 00:40] task-planner (Fable) — planning complete, plan self-reviewed
- Did: investigated (3 searchers + executed scenario harness), wrote `implementation-plan.md` and the user
  checkpoint `show-before-code.md`, ran the mandatory plan-mode deep-review (8 lenses, direct launches:
  review-plan, architecture-fit, silent-failures, impact-completeness, feature-interactions, agent-ux,
  validation-consistency, concurrency-safety), folded every confirmed finding into the plan.
- Changed: `implementation/implementation-plan.md`, `implementation/show-before-code.md`, spec cite
  `task-180.md` (`resume_preflight.py:158-173` → `:161-192`).
- Verified (executed, isolated HOME): BEFORE column of all 16 checkpoint rows; a non-batched host writes
  `node.start`, a batched host does not; `--force` today skips an inserted upstream step, ignores an edited
  input default (recorded value wins, `KEY=VALUE` overrides), runs a downstream insertion; Task-159 baseline
  on the base: 75 pass / 12 drift (same 12 as Task 183's list). Verified by read (file:line in the plan §1):
  attempt traces re-record only `entry.seeded`; `--approve yes` matches by node id only; the document-order
  edge has no `action` key; `entry_never_started` gates only on `content_hash`.
  | Assumed: Task 183's 2.9.0 claim read from its branch's plan, not from a build.
- Deviations/surprises vs spec: (1) Task 179's review line 53 ("a sub-workflow host emits no node.start")
  is wrong for non-batched hosts — code and PR #719 are right; flagged for the main orchestrator, not
  edited. (2) The spec's "In scope by ruling" says the carve-out is DELETED; the plan narrows it to
  pre-180 traces instead (D1b) — deleting it unconditionally would skip the side-effect confirmation for a
  batched host on every 2.3–2.8 trace (three lenses converged; confirmed at `resume_source.py:393`).
  (3) A paused-approval step edited after approval is a consent hole the whole-hash gate was silently
  closing — row 14, checked (feature-interactions C1, confirmed at `gate_prompt.py:84-89`).
- Deep-review dispositions (plan mode): CONFIRMED and folded — carve-out × old traces (arch-fit W1 /
  feature-int W1 / impact C1 → D1b); D4-by-events false-refuses resume-of-a-resume with a failed-recovered
  start step (review-plan C1 → start step recorded in meta; checked set = restored set, D3); paused
  approval edited (feature-int C1 → D3); row 12/13 wording and the row-4 text not buildable with one hash
  (review-plan W1/W2, agent-ux W1-W4, silent S3 → `next` recorded verbatim, resume-point-exists check
  first, `removed` lead, generic `--force` line); edge normalisation crash on implicit next + `on-error`
  (silent W2 / review-plan W3 / impact S4 → `.get("action","default")`); gate-arm guard + batch drain
  (concurrency S2 / feature-int S1 / review-plan W4 → D1); D11 must share the runner's pre-meta step, not
  copy it (validation W1-W3 / silent W3 / review-plan W5 → `WorkflowRunner.preflight`, `/api/run` too);
  P1 test 8 twin unbuildable (silent W4 → dropped); in-memory orphan not closed unless `begin_node`
  reserves in memory (silent S1 → D1); readers of dangling starts untested (impact W1 → P1 test 9);
  `test_resume_cli.py:611` import (impact W2 / review-plan S3); `start_node_id` in core + local clash
  (impact S1); `_read_meta` reasoning (impact S2); spec open questions to be folded (review-plan W6 → P0);
  recipe-stability sentence and honest `--force` reversal price (arch-fit open decisions 1–2); ADR-0010
  amendment carries the rejections (arch-fit S1); JSON context fields, older-version wording,
  between-nodes text, guide wording (agent-ux S2/S4/S5/S6). DECLINED with reason — agent-ux S1 (new
  output line for an edited loop resume point → D13, guide sentence instead); agent-ux S3 (literal re-run
  command with recorded inputs → scope); agent-ux W5's advisory (→ checkpoint row 9 option (c), user's
  call); review-plan S2 / feature-int S3 (exclude policy-only keys from the hash → kept fail-closed, stated
  in D2 and the checkpoint). review-plan W2's second half ACCEPTED: the "only reachable under --force"
  comments stay true — the plan no longer rewrites them. Concurrency: clean (no new cross-thread state).
- Self-checks: fully happy with the plan's shape; residual doubt: whether the user wants row 14 (paused
  approval edited) to refuse or to re-ask — the plan refuses (consent is for what was seen); the
  checkpoint says so.
- Next: main orchestrator surfaces `show-before-code.md`; P1 may build before the ruling; P0 + P2/P3 after it.

## [2026-10-07] main orchestrator — show-before-code RULED
- Did: relayed `show-before-code.md` to the user in plain language; user: *"yes go with your recommendations"*.
- Changed: spec gains `## Decisions (ruled 2026-10-07)`; checkpoint file header carries the ruling.
- Verified: all 16 AFTER rows as proposed; `--force` (a) one flag. | Assumed: nothing.
- Deviations/surprises: none — the planner's residual doubt (row 14 refuse vs re-ask) resolved as refuse.
- Next: build (P0–P4) launches after Task 118 Part 2 merges (engine seam); P1 may start earlier if the seam frees.

## [2026-10-08 09:00] task-orchestrator (Opus) — bootstrap + P0
- Did: merged `origin/main` `1d393487` into the branch (clean, merge `9e4e6ab6`; Task 118 Part 2, PRs #725/#726/#744 now under the plan); `make install`; recorded baselines; wrote P0 (spec: open questions → `## Resolved questions`, `## Solution`/`## Requirements`/`## Verification`, the "In scope by ruling" guard sentence now says NARROWS per the accepted D1b delta; Status → in progress).
- Changed: `task-180.md`.
- Verified: `make test` baseline on the merged tree — **10586 passed, 0 failed**. Task-159 baseline — **76 pass / 11 drift**: `02-validator-errors/03,05; 03-analyze-cache-modes/05-09; 04-warning-catalog/03,09d,09e; 10-live-recordings/03` (the plan's §1 list minus `12-real-world-lyrics-generator/04`, which main now passes). Any drift outside these 11 is ours. Plan anchors re-checked on the merged tree: `engine.py:1364-1369` skip + stale "deferred" comment, gate arm guard `:1672`, except-arm drain `:1704`, completion `frame=host_frame or start_frame` `:1433/:1508/:1718`; `workflow_trace.py` `descend :876`, `begin_node :932`, `_meta_fields :1043`, `TRACE_FORMAT_VERSION = "2.8.0" :44`; `runner.py:204`; `resume_preflight.py` `_check_content_hash :161`, `_side_effect_refusal :326`, carve-out `:354`.
- Deviations/surprises: (1) Post-Task-118, a shell `command` holding `${…}` is a validation ERROR — every new fixture/scenario binds values through `env:` (shell) / `inputs:` (code); the planner's scenario harness predates this. (2) PR #744 renders the server's `errors[0]` verbatim in the web resume panel, so the plan §7 #721 note is moot — new refusal text reaches the browser with no `web/` edit (none will be made). (3) Baseline drift set shrank by one (above).
- Next: launch ONE Opus `task-phase-implementer` on P1 (effort high); mid-task review (silent-failures + feature-interactions) after it.

## [2026-10-08 02:54] phase-implementer (Opus) — P1 `node.start` for every step (engine + collector)
- Did: built D1 as written. `begin_node` reserves a seq for every node on a run-scoped collector (emits only when streaming), parks the frame in `_pending_start`; `descend` pops it and pushes THAT frame when `node_id` and enclosing host match, else falls back to today's reserve + push + emit. Engine 8.5 drops the `!= "WorkflowExecutor"` conjunct; the gate arm records `getattr(node, "_host_frame", None) or start_frame` under `frame is not None and not originating`, draining the batch trace there; `success=True` kept. Preflight carve-out untouched (P3).
- Changed: `runtime/workflow_trace.py` (`__init__`, `begin_node`, `descend`, `_emit_node_start` docstring), `runtime/engine/engine.py` (8.5 comment + condition; gate-arm comment, guard, frame, drain), `runtime/engine/CLAUDE.md` (Gate control flow; Batch boundaries drain sentence), `runtime/CLAUDE.md` (new node.start paragraph), ADR-0008 as-shipped note, `tests/test_runtime/test_emit_time_trace.py` (+12 tests, 2 stale comments), `tests/test_cli/test_resume_cli.py` (+2 tests, stale carve-out comment, stale looping-host docstring).
- Verified: `make check` green; `make test` **10600 passed, 0 failed** (baseline 10586 → +14 new, no regressions). Real runs (`uv run pflow`, isolated HOME), raw JSONL:
  - S1 batched host (`batch.items: ["a","b"]`): `node.start host id=0 parent=None` → `event host id=0 parent=None success batch_items=2` → `run.complete success` (before: the `event` only — planner's executed harness; and mutation M1 below).
  - S2 non-batched host + leaf: `node.start host 0/None` · `node.start fire 1/0` · `event fire 1/0` · `event host 0/None` · `node.start after 2/None` · `event after 2/None` — one start per host visit.
  - S3 looping non-batched host (3 iterations): `start host 0` · `start judge 1/0` · `event judge 1/0` · `event host 0 iter=1` · `start host 2` · … · `event host 2 iter=2` · `start host 4` · … · `event host 4 iter=3`.
  - S5 batched host, item 0 → plain child, item 1 → `approval: required` child, stdin </dev/null: exit 1 "Gate needs a human"; `node.start host 0/None` → `event host 0/None success batch_items=1` (item 0, success) → `run.complete failed`.
  - S9 real CLI: run of produce → batched host, trace cut before the host's event → `pflow resume <id>` prints "Resuming re-runs step 'host' (a workflow step)…" (entry = host via the dangling start).
  - Mutations (Edit + revert via scratch script; sources byte-restored each time): M1 re-add engine skip → 10 fail incl. test 1 (both params), 5, 6, 9 (both); M2 descend never takes over → 7 fail incl. test 2 (two starts), 3, 4, 7, 8; M3 gate-arm guard back to `_host_frame` only → test 5 + the triple fail; M4 gate arm passes `batch_trace_items` (no drain) → test 5 fails (presence); M5 `begin_node` stream-only again → test 7 in-memory + test 8 fail.
  | Assumed: nothing reads a non-streamed run's seqs differently — seqs are byte-identical by construction (nothing reserves between `begin_node` and `descend`/completion) and the full suite incl. fixture-parity tests is green.
- Deviations/surprises: (1) Plan says gate arm `frame = host_frame or start_frame`; the LOCAL `host_frame` is only assigned after `node._run` returns, so it is always `None` on a raise — built as `getattr(node, "_host_frame", None) or start_frame` (the old `getattr` read, plus the fallback). Same intent. (2) `runtime/CLAUDE.md` had NO node.start bullet to edit — added a 5-line paragraph after the `_open_child_trace` one. (3) Test 6 needs a templated `workflow: ${pick.result}`: a static missing/broken child path is rejected by validation before the trace exists, so neither runtime arm is reachable with a literal path. (4) Test 7 fault-injects `WorkflowExecutor._expose_child_outputs` (monkeypatch) — no natural post-descend `post` failure exists; it's the only mock in the new tests. (5) Test 5's batched host now records `success=True` on a child gate (plan's kept choice); checked it changes no resume semantics: a gate-stopped `failed` run with no failed event still refuses via `_raise_gate_stopped_or_generic`, and `--only` excludes failed traces — same as a non-batched host already did. (6) Stale text left for later phases (outside P1 files): `execution/resume_preflight.py:352` comment ("The engine skips begin_node for WorkflowExecutor…") and `execution/CLAUDE.md:73` ("a batched host writes no `node.start`") — P3 owns both with the carve-out; `runtime/engine/instrumentation.py::record_trace` docstring says `frame` is "passed only for a WorkflowExecutor host; None for every other node" — stale since Task 173, more so now; not in any phase's file list → orchestrator's call (P4 or a one-line fix). Guide/CLI-reference "a sub-workflow step always asks" stays true until P3.
- Self-checks: fully-happy pass done in-context — doubts raised and resolved: stale `_pending_start` after a leaf (harmless: next `begin_node` overwrites, and a match also requires the same enclosing host; every production `descend` is preceded by its own `begin_node` on the same thread); in-memory seq identity (by construction + suite); parallel-batch completion order (made the S1 index assertion order-free). test-reflect: not needed — not directed, and every new test is mutation-backed (M1–M5 above) with presence/absence pairs (S5 ungated twin; S7 in-memory vs streamed).
- Next: mid-task review (silent-failures + feature-interactions) on P1's diff, then P2+P3.
- Self-checks addendum (orchestrator round, 2026-10-08): (1) Gate-arm `getattr(node, "_host_frame", None) or start_frame` — CONFIRMED dead half: `engine.run` installs `self.trace` as `shared["__trace_collector__"]` (`engine.py:893-894`), so a host always descends into the collector whose `begin_node` left the frame pending → takeover → `_host_frame is start_frame`; when `start_frame` is None (buffer collector) the host never descends. The same holds at ALL four completion sites, so I folded the whole `host_frame` local away: api-warning / step 16 / except / gate arm now pass `frame=start_frame`; gate guard `start_frame is not None and not originating`; the guard comment restates #659 in `start_frame` terms (`not originating` now only matters for the 17.7 escalation). Mutations re-run on the simplified lines: M3 (pre-P1 guard `getattr(node,"_host_frame") is not None`) → test 5 + triple fail; new M3b (drop `not originating`) → `test_host_own_escalation_records_host_once` fails; M4 no-drain → test 5; M5 → test 7/8; M1/M2 now fail 25/19 (host completions depend on begin_node's frame — coupling made explicit, the pre-existing orphan pins fire too). All restored byte-identical. (2) `instrumentation.py::record_trace` docstring fixed (frame = `begin_node`'s reservation, hosts included; None for a buffer collector or a node that never began). `make check` green; `make test` 10600 passed / 0 failed. Remaining loose end, NOT fixed (outside P1's files): `WorkflowExecutor._host_frame` is now read only by its own `finally` ascend guard — the comments at `workflow_executor.py:82-85` ("so the engine's getattr read is safe") and `:481-482` ("captured into self._host_frame for the parent engine") are stale; simplest final form is a local "descended" flag in `exec` (and dropping `_host_frame` from `test_node_stateless_invariant.py:45`'s allowlist). Recommend folding into P4 or a follow-up; importance 1.

## [2026-10-08] task-orchestrator — P1 verified + committed
- Verified: `make check` green, `make test` 10600/0 re-run by me after the loose-ends round; read the engine + collector diff (takeover, gate arm).
- Self-checks: fully-happy round raised (by me) the dead `getattr(_host_frame)` gate-arm half → simplified to `start_frame` at all four completion sites; `record_trace` docstring fixed. test-reflect: not needed — every new test is mutation-backed (M1–M5, M3b) with presence/absence pairs.
- Deviation dispositions: gate-arm `frame=` (accepted, now `start_frame`); `runtime/CLAUDE.md` new paragraph (accepted); `resume_preflight.py:352` + `execution/CLAUDE.md:73` stale text → P3 (with the carve-out); `WorkflowExecutor._host_frame` now read only by its own ascend guard + stale comments `workflow_executor.py:82-85, :481-482` + allowlist `tests/test_node_stateless_invariant.py:45` → **P4 item** (local "descended" flag in `exec`).
- Next: mid-task review (review-silent-failures + review-feature-interactions) on P1's diff, run by the P1 implementer through the pflow fan-out.

## [2026-10-08 03:10] phase-implementer (Opus, gate-runner) — P1 mid-task review (silent-failures + feature-interactions)
- Did: dispatched `review-silent-failures` + `review-feature-interactions` through `workflows/review/run-review-lenses.pflow.md` (provider codex, cross-model), target = `git diff bf04dc50..2ebd151a` (code only) against spec + plan §3 D1/D1b + §5 P1; waited in-turn; read the report in full.
- Changed: `tests/test_runtime/test_emit_time_trace.py` (gate-stopped batched-host test parametrized over `parallel`); review artifact `implementation/reviews/p1-midtask.txt` (uncommitted, orchestrator's call).
- Verified: Coverage 2/2 lenses delivered, no failed lens. Findings: **0 Critical, 0 Warning, 1 Suggestion**. Both lenses independently walked frame ownership, every completion path, gate originating-vs-child, batch × nesting, loops/cache/`--only`, in-memory runs, and the resume readers (`_dangling_top_level_starts`, `_attempt_consumed_work`, `entry_never_started`, `_resolve_incomplete_entry`, `run_tailer`, `final_events_by_node`) and reported them clean; both confirmed D1b's carve-out correctly untouched. `make check` green; `make test` **10601 passed, 0 failed** (+1 param).
  | Assumed: the lenses' clean verdicts are static reads (neither executed tests) — the executed evidence is P1's mutation set + this round's re-runs.
- Dispositions: **S1 (feature-interactions) — parallel child-gate stop not asserted for start/completion pairing → FIXED.** Parametrized `test_batched_host_stopped_by_an_item_gate_pairs_its_start_and_keeps_completed_items` over `parallel`; the gated item's child gets a 0.3 s `code` step first so item 0 completes before item 1's worker gate fires (completion-order sorting on the ungated twin). Passed 5/5 consecutive runs. Mutation re-check on the new param: M3 (pre-P1 guard) → both params fail; M4 (no drain) → both params fail; sources restored byte-identical.
- Deviations/surprises: no Critical/Warning to verify against code. The fix's first attempt failed validation (a `code` step must declare `result:`), caught before landing. The parallel variant leans on a timing margin (0.3 s against a ~10 ms echo), per tests/CLAUDE.md pitfall #15. If it ever flakes, the fallback is to assert only the host pairing for `parallel=True`.
- Self-checks: clean. P1's only remaining loose end is the `WorkflowExecutor._host_frame` cleanup, already parked for P4 by the orchestrator.
- Next: P2+P3 on resume.
- Determinism follow-up (orchestrator round): DEVIATED from the directed marker-poll design, because a marker is NOT a guarantee. Item 0's batch-trace entry is appended in its worker by `_capture_item_trace` (`batch_executor.py:952`) AFTER its child workflow returns, so a marker written by the child's last step precedes it. The gated worker could see the marker, raise, and have the main thread drain `_batch_trace` before item 0's entry lands. Built instead: the parallel case runs `parallel: true, max_concurrent: 1`. That is still `_execute_parallel` (deep-copied node, pool-thread gate crossing back through its future), and a one-thread pool runs FIFO, so item 0's whole `process_item`, `_capture_item_trace` included, completes before item 1 starts. Order is guaranteed, and the 0.3 s sleep is gone. The test now asserts `errors[0].context["parallel_batch"] is parallel`, proving the worker path ran. The sequential case's IR is byte-identical to before (`max_concurrent` is emitted only for parallel). 5/5 runs pass. M3 (guard) and M4 (drain) fail both params, with sources restored. `make check` is green; `make test` shows 10601 passed, 0 failed.

## [2026-10-08] task-orchestrator — P1 mid-task review closed; P2+P3 routing
- Did: accepted the mid-task review (0 Critical / 0 Warning; Suggestion fixed) and the implementer's `max_concurrent: 1` deviation from my marker-poll instruction (a marker races the worker's post-return `_capture_item_trace` append — sound); committed `efee7428` with `reviews/p1-midtask.txt` (Task 118 precedent).
- Verified: `make check` green, `make test` 10601/0.
- Routing: P2+P3 go to a FRESH Opus implementer (effort high). Stated reason: the P1 implementer is at ~278k tokens (notification metadata) and P2+P3 is the plan's largest bundle; P1's knowledge is externalized in this log and its surface (engine frames) is disjoint from P2/P3's (meta line, preflight, exceptions, runner, UI server). The P1 implementer remains queryable.
- Next: P2+P3 bundled; then mid-task review (review-silent-failures + review-agent-ux) on P2+P3's diff.
