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
