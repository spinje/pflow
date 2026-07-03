# Orchestrator Progress Log

_Mutable state companion to `orchestrator-kickoff.md`. **`## Now` is edited in place and must
always be true** (correct it the moment reality diverges); **`## Log` is append-only** (newest
entry first). Every claim here is a pointer — verify against git/gh/`./scripts/tasks` at boot._

## Now (last verified: 2026-07-03)

**Current arc: resume/HITL — build order 125 ✅ → 164 (next) → 171 → 176 (→ 174).**

**Next action: create the Task 164 worktree** (resume-from-failed-node) — all prep done, awaiting
user go. 125 shipped clean (#554); the checkpoint→restore→continue substrate is now 164's to build.
Launch-ready inputs (all on `main`, uncommitted where noted):
- **Spec re-audited 2026-07-03** against `1d9c6b2c` (3 parallel opus audits: engine/trace/planner).
  Substrate structurally intact post-125 + post-#557; `task-164.md` banner + run-query section
  updated (the "five consumers" claim was wrong — corrected to 3 independent + 1 delegating).
  Line refs drift small; re-verify at impl time.
- **All 5 decisions DECIDED 2026-07-03** and recorded as a ledger in `task-164.md` (do not
  re-litigate): CLI = `pflow resume <wf|exec-id>` subcommand · `--dry-run`×resume IN · incomplete-
  trace resume PREFERRED-IN (complexity assessed at plan time — scope change vs old "no") · side-
  effecting-K = taxonomy-keyed, **non-TTY = hard error not prompt** · fidelity = loud-caveat guard,
  snapshot store declined (binary round-trips via base64, verified). `pflow run` rename scoped OUT.
- **ADR-0010 written** (`context/adr/0010-164-resume-trace-checkpoint.md`, accepted).
- **Brief + braindump** in `scratchpads/task-164-resume/` (travel into the worktree via copy_folder).
- 164 folds in **#255 (open)** — trust `task_164/research/255-failure-state-edge-cases.md` over the
  stale issue body; close #255 when 164 ships.
- Launch cmd: `uv run pflow git-worktree-task-creator task_description='Task 164 — Resume Workflow
  From a Failed Node' work_type=task copy_folder=scratchpads/task-164-resume`. **164 is the sole
  engine toucher — no live collision** (#546 held, UI-only; Task 170 not in flight).

**Decision schedule (get these from the user at the named moment, not before):**
- **164 start:** CLI surface (`pflow resume` subcommand rec; spans 164+171) · `--dry-run`×resume ·
  incomplete-trace resume (rec: no) · side-effecting-K policy · **snapshot fidelity (get BEFORE
  planning — it shapes the shared helper)**. Once fidelity + checkpoint are confirmed → **write
  ADR-0010 (trace-as-checkpoint + attempt chains)**; canonical text sits in task-164/171 specs.
  164 also folds in **#255 (open)** — trust `task_164/research/255-failure-state-edge-cases.md`
  over the stale issue body; close #255 when 164 ships.
- **171 start:** trace-as-checkpoint confirm (importance 4) · MCP/`--no-trace` gated-runs-require-
  trace sub-decision · paused-status encoding · token security (rec: trust local fs, recorded) ·
  the pause exit code · MCP structured-result token surface.

**In-flight worktrees:** none building. Cleanup candidates from `git worktree list`: many merged
`fix-*`/`feat-*` trees remain; `feat-unified-node-storage` is the **rejected** Task-133 premise —
prune so nobody builds on it.

**Parallel-lane candidates (all verified open 2026-07-02 unless marked):**
- **#546** — pinned-run resolve race (real bug in shipped 175 launch; small; disjoint from 125).
- **#538** liveness backstop · **#544** `llm_*` write-side canonicalization · **#549** post-#539
  visibility cleanup · **#541** ruff drift · **#528** CLI `--output-format` stragglers.
- **#542** trace retention — ⚠️ **design WITH/AFTER 171** (paused traces are live obligations;
  sequencing comment posted on the issue 2026-07-02).
- **#357** memo-cache drift — guard merged (#524), fix worktree existed
  (`fix/fix-cache-key-drift`); issue state **UNVERIFIED since 2026-06-23 → check**.

**Watch list (non-obvious, easy to miss):**
- 125 pre-flight #1: confirm the UI tailer + frontend tolerate an unknown event `kind`
  (`run_tailer.py` + web) before emitting the `gate` event.
- 125 scope trap: the escalation **trigger** is half-designed (Task 99 unbuilt; signal mechanism
  flagged "known-broken" in the 2026-06-02 braindump) — surface as an explicit scoping decision;
  don't let it silently double the task.
- **Engine hot spot:** 125 and 164 both edit `_execute_node`/engine internals → strictly
  sequential, never parallel worktrees.
- Recurring fact-conflation attractor: `is_trace_locked` (probe, `ui/run_tailer.py:135`) vs
  `_lock_trace_handle` (writer flock, `workflow_trace.py:74-90`) — two independent agents got
  this wrong; distrust docs that place the probe in `workflow_trace.py`.
- **Task 170** (One Template Language, Refactors backlog) conflicts with 164 in `plan.py`
  (planner-mirror braindump) — do not run them in parallel.
- Trace-touching work (171's new `paused` status especially): the Task-159 baseline
  (`task_159/baseline/verify.sh`, restored green via #535) is a free outer regression net — run it.
- All spec file:line refs were refreshed 2026-07-02; this area moves fast — re-verify at
  implementation time.

## Log (append-only, newest first)

### 2026-07-03 — boot: reconciled state after 125 shipped
Boot verification found `## Now` stale on two counts. (1) **Task 125 shipped clean** (#554, merged
2026-07-02) — read the task-review (`task_125/task-review.md`): payload-is-the-seam (ADR-0009) held,
escalation landed in scope via `result.escalation`, the orphaned-trace-event bug is the sharpest
gotcha (engine reaches `WorkflowExecutor._host_frame`). 171 depends on `GateRequest`/
`GateResolution` **unchanged**. (2) **Subagent model rule flipped fable→opus** (`3f3286f9`); user
set the durable rule 2026-07-03 (never fable; sonnet only for mechanical searcher lookups) — folded
into kickoff §3. Also shipped since last log: **#557** (single-source ruff +
py310 modernization, repo-wide format pass — drifts all spec file:line refs) and **v0.14.0**
(release). Next: refresh 164 spec against `1d9c6b2c`, confirm the 5 open decisions + fidelity, then
launch 164. **Left off: discussing next options with the user; 164 not yet launched.**
Ledger note: **#541** (ruff drift) is effectively resolved by #557's single-sourcing but still
OPEN — verify + close. `feat-unified-node-storage` worktree (rejected Task-133 premise) still
present — still a prune candidate.

### 2026-07-02 — resume/HITL arc prep completed (the decision session)
Verified 125/164/171 spec claims against main via four parallel fable investigations; found the
164 "hard-kill leaves no trace" claim false post-172, 171's purpose-built state file resting on
dead premises, and the 125 gate seam real but batch-excluded. Refreshed all three specs
(subagent edits + personal full-read verification — 9 residual cross-file errors found and fixed
by hand). Step-back audit surfaced the missing **attempt-chain lineage** seam (approved; canonical
in task-164.md) and the **#542 retention collision** (comment posted). User locked 125 decisions
1–3; ADR-0009 written; Task 176 drafted (Slack/external surfaces deliberately NOT tasked —
observed-problems rule); CLAUDE.md roadmap corrected (175 → done; 176 added); 125 braindump
written. All committed: `c02a4bde`. The orchestration kickoff + this log were created the same
session. **Left off: 125 worktree not yet created.**

### 2026-06-16 → 2026-07-01 — the trace/overlay arc (context for how we got here)
Failure-state cluster fixed first (#522/#523 + #491; storage_mode removed) as the resume
prerequisite. Then the substrate arc shipped end-to-end: Task 133 A–C (JSONL trace, #525) →
172 (emit-time producer, #530) → 169 (SSE point/watch, #527) → #529 (reconnect/discovery, #533) →
#531 (one writer/reader, #534) → 173 (live overlay, #543) → #540 (cache-hit IO, #545) →
175 (run-from-UI, #547) → #539 (multi-tab SSE, #548). #532 restored the Task-159 baseline oracle
(#535). Key standing decisions from the arc: trace/cache stay separate (ADR-0007); UI observes,
never hosts (ADR-0008); the trace is the single event source. The resume/HITL arc builds directly
on all of it.
