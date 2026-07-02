# Orchestrator Progress Log

_Mutable state companion to `orchestrator-kickoff.md`. **`## Now` is edited in place and must
always be true** (correct it the moment reality diverges); **`## Log` is append-only** (newest
entry first). Every claim here is a pointer — verify against git/gh/`./scripts/tasks` at boot._

## Now (last verified: 2026-07-02)

**Current arc: resume/HITL — build order 125 → 164 → 171 → 176 (→ 174).** Prep is complete;
build has NOT started.

**Next action: create the Task 125 worktree** (blocking approval gates). The braindump + spec are
committed, so they travel with the checkout — the launch brief can be thin (point at them + the
pre-flight). All inputs ready on `main` (`c02a4bde`):
- Specs 125/164/171 refreshed 2026-07-02 against main (four fable code-audits) + personally
  verified. `task-125.md` is authoritative; the tacit layer is
  `task_125/starting-context/braindump-2026-07-02-decision-session.md` (read it — it carries the
  locked-decision rationales, the escalation-trigger scoping trap, and the implementation
  checklist).
- 125 decisions **1–3 LOCKED** (gate event in scope · `--auto-approve=<node-id>` scoped ·
  batch-host `approval:` rejected at validation); **4–5 open-with-rec** (non-TTY failure timing ·
  denial semantics) — confirm at plan time.
- ADR-0009 (approval surfaces = out-of-process bridges) accepted. Task 176 (web bridge) drafted,
  thin, blocked on the arc.

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
