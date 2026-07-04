# Orchestrator Progress Log

_Mutable state companion to `orchestrator-kickoff.md`. **`## Now` is edited in place and must
always be true** (correct it the moment reality diverges); **`## Log` is append-only** (newest
entry first). Every claim here is a pointer — verify against git/gh/`./scripts/tasks` at boot._

## Now (last verified: 2026-07-04)

**Current arc: resume/HITL — 125 ✅ → 164 ✅ → 174 ✅ → 171 (next) → 176.** 164 (PR #559, closes
#255) + 174 (PR #560) merged 2026-07-04; their worktrees pruned; roadmap + specs reconciled.

**Next action: Task 171** (durable resume tokens / non-TTY gates) — unblocked by 164; the second
consumer of its checkpoint→restore→continue substrate. Before launching:
- **Read `task_164/task-review.md` FIRST** — the shipped-substrate handoff (invariants that must not
  break, the `paused` insertion point, gotchas). The 171 spec already absorbed the handoff (banner +
  "UI attempt-chain rendering" section) — trust the review over any pre-impl phrasing.
- **Loader-extraction trigger:** the resume loader (~400 lines: `ResumeSource`/`load_resume_source`/
  entry resolvers) accreted in `runtime/workflow_trace.py`. 171's `paused` arm is the third consumer
  → **extract to `runtime/resume_source.py` FIRST** (parity net first, zero behavior change).
- **171 now also owns the `resumed_from` run-list UI** (owner decision 07-04; ADR-0010 consequence
  updated) — surface `resumed_from` in `/api/runs` + link chains in the run selector.
- Open decisions to settle at 171 start: MCP/`--no-trace` gated-runs-require-trace · paused-status
  encoding (rec `final_status:"paused"` trailer) · pause exit code · token security (rec: trust local
  fs, record it) · MCP structured-result token surface. **#542 (retention) must be designed
  WITH/AFTER 171** — a `paused` trace is a live obligation, not a prunable debug artifact.

**What 164/174 actually shipped (deeper than spec — read the reviews):** 164 = `pflow resume` for
failed AND interrupted runs (Decision 3 landed IN); entry = the `_terminal_failure_root` frontier
rule (replaced Decision 9's event-order rule after a proven both-fail-chain bug — ADR-0010 amended
2×); trace format **2.6.0** (`resumed_from`/`restored`); zero-event runs now finalize `failed`
(global semantics change); 3 deep-review proven-bug fixes (failed events never seeded — also fixed
`--only` degraded-snapshot; incomplete-tail entry; escalation fold-at-load). 174 = `--say` TTS +
self-pacing walkthroughs (playback-beacon closed loop, blocked-hold); NodeCallout reuse held;
ADR-0011/0012 written; **zero engine/runtime contact** — the parallel-lane collision analysis was
validated in practice.

**Worktrees:** 164/174 pruned. **HELD — needs a user call:** `feat-unified-node-storage` is clean but
its branch is `docs/task-133-crash-tail-scope` (name ≠ dir) with ONE unmerged docs commit `41281872`
([skip review], crash-tail scoping) — the "rejected premise, safe to prune" label doesn't match; do
not force-delete blind. Many other merged `fix-*`/`feat-*` trees also remain (broader cleanup not yet
done — not proposed this session).

**Parallel-lane candidates (verified 2026-07-02 unless marked):**
- **#561** (new, spawned by 174) — TTS clip cache for `--say`; deferred design task, backlog.
- **#546** — pinned-run resolve race (real bug in shipped 175 launch; small; disjoint from 125).
- **#541** ruff drift — **likely already resolved by #557's single-sourcing → verify + close.**
- **#538** liveness backstop · **#544** `llm_*` write-side canonicalization · **#549** post-#539
  visibility cleanup · **#528** CLI `--output-format` stragglers.
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

### 2026-07-04 — 164 + 174 merged; post-merge reconcile
Both shipped: 164 (PR #559, closes #255) and 174 (PR #560). Read both task-reviews — both went
DEEPER than spec. 164: `pflow resume` covers failed AND interrupted runs (Decision 3 landed in); the
entry rule was rewritten mid-build to `_terminal_failure_root` (frontier) after a proven both-fail
on-error bug; trace format → 2.6.0; zero-event runs now `failed`; a 5-agent deep-review added 3
proven-bug fixes (failed events never seeded — also fixed `--only` degraded; incomplete-tail entry;
escalation fold-at-load). 174: `--say` + self-pacing walkthroughs (playback beacons, blocked-hold),
ADR-0011/0012, NodeCallout reuse held, **zero engine contact** — collision call validated.
Reconcile done: CLAUDE.md roadmap (125/164/174 → ✅, minimalized to short names per owner; Next =
171 → 176); ADR-0010 consequence corrected (`resumed_from` UI is **171's**, not 173's); task-171.md
banner updated (164 shipped, handoff absorbed, loader-extraction trigger). Pruned 164/174 worktrees;
**held `feat-unified-node-storage`** (1 unmerged docs commit `41281872`, branch≠dir name — needs a
user call, not a blind force-delete). #561 (TTS cache) filed to backlog; #541 flagged verify+close.
**Left off: 171 is next (unblocked); the held worktree + #541 close await user.**

### 2026-07-04 — Task 174 parallel-lane prep + launch
User asked whether 174 could run parallel to the in-flight 164. Ran the two-dimension collision
analysis (file-surface map + semantic): **disjoint** — 174 is UI-channel/TTS, never touches engine
or trace format; only conditional overlap (`ui/server.py` run-list) is out of both tasks' committed
scope (ADR-0010 → Task 173). Verified the one load-bearing external assumption (Gemini TTS model
current; request shape drifted → builder-pins). User flagged a reuse opportunity ("boxes beside
nodes"); verified → `NodeCallout` (Task 175, 174 named co-target) — folded reuse note into spec +
brief, shrinking 174's frontend. Right-sized prep: thin brief only, NO decision session / braindump
/ pre-written ADR (spec complete; flagged a ship-time ADR for the LiteLLM-TTS-bypass). Launched 174
on fable in parallel. **Left off: 164 + 174 both building; #546 held; #541 verify+close pending;
`feat-unified-node-storage` prune candidate.**

### 2026-07-03 — Task 164 decision session + launch
Ran the 164-start sitting. Re-audited the spec against `1d9c6b2c` (3 parallel opus audits) — substrate
intact post-125/#557; corrected the run-query "five consumers" claim (→ 3 independent + 1 delegating,
`report.py` had been missed). Locked all 5 decisions as a DECIDED ledger; two shifted at the table:
**#3 incomplete-trace resume flipped from rec-NO to preferred-IN** (complexity assessed at plan time —
a real scope expansion, surface-then-decide), and **#4 non-TTY side-effecting-K = hard error, not a
prompt** (owner correction: agents can't answer y/n → error telling them to confirm with their user +
re-run `--force`; mirrors 125's `GateNotInteractiveError`). A verification killed the heavyweight #5
option: binary round-trips losslessly (base64-before-store), so the dedicated snapshot store is
declined — fidelity guard is a narrow backstop only. Wrote **ADR-0010**, brief + braindump. Committed
`0ffd9266`, then launched the worktree on **fable**. **Model-rule clarification from the owner:** the
"never fable" rule governs the orchestrator's *research subagents*; the *worktree builder* is a
different, more important role where **fable is best-in-class and preferred** (folded into kickoff §5).
**Left off: 164 building; #546 still held; #541 still needs verify+close; `feat-unified-node-storage`
worktree still a prune candidate.**

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
