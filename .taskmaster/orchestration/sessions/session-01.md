# session-01 — ARCHIVE: converted pre-restructure orchestrator-progress-log.md

_Converted 2026-07-11 during the orchestration restructure (DECISIONS #1, #6). The `## Now`
snapshot below is FROZEN AS OF 2026-07-11 and superseded by `CURRENT-STATE.md`; the `## Log`
entries are the authentic pre-restructure session history (2026-06-16 → 2026-07-11).
Original file history: `git log -- .taskmaster/orchestration/orchestrator-progress-log.md`._

---

# Orchestrator Progress Log

_Mutable state companion to the `/start-orchestration` command — the current build state its boot
sequence verifies against. `## Now` is the current truth; `## Log` is append-only, newest first._

## Now (last verified: 2026-07-11)

**Current arc: resume/HITL — 125 ✅ → 164 ✅ → 174 ✅ → 171 ✅ → 176 (IN FLIGHT).**
**IN FLIGHT: Task 176** in worktree `feat-web-ui-approval-bridge` (branch
`feat/web-ui-approval-bridge`, launched on **fable** 2026-07-11, based on `276672a4` — the commit
carrying the refreshed spec). Brief verified present in the worktree
(`scratchpads/task-176-web-approval-bridge/BRIEF.md`). The 176 spec-refresh + decision session
ran the same day: spec fully rewritten against verified main (three parallel audits + personal
spot-checks), 3-item decision ledger LOCKED by the owner (escalation-answering IN · greying
IN-phased-last · `resolved_via:"ui"` OUT — rationale in the ledger, do not re-litigate).
**On merge:** verify personally (esp. the pre-flight no-silent-no-op rule and the resume
`PFLOW_EXECUTION_ID` hook — both were orchestrator catches, not spec inheritance), reconcile
roadmap (176 → ✅ closes the resume/HITL arc), check whether the greying cut-line was exercised
(→ follow-up issue), then #546/#568 unblock (serialized behind 176). Key
verified facts that reshaped the task: the gate payload does NOT reach the browser (both server
read paths are deliberate allowlists — real server-side half); resume has full JSON output but
exit 1 conflates refusal/failure; a paused-gate answer never hits side-effect confirm;
`PFLOW_EXECUTION_ID` is run-only (resume needs the mirror hook); paused runs are terminal →
immune to #566; the spawn needs extraction (3rd consumer) + the win32 branch. No new ADR —
nothing hard-to-reverse decided (resolved_via deferral is additive-later; ADR-0009 already
covers the surface pattern).

**171 shipped** (PR #563, merged 2026-07-05, squash `e55f0d30`; verified personally 2026-07-11 —
worktree tip content incl. the post-review `isdecimal` fix confirmed in main). Read
`task_171/task-review.md` before any resume/gate/trace work. Beyond-spec deltas that change 176's
ground: **MCP now streams traces** (the never-stream special case is deleted); exit code **4 =
paused** (beside 3 = denied); trace format **2.7.0** (`final_status:"paused"` + `paused_node_id` +
`gate_request` on the `run.complete` trailer); loader extracted to `runtime/resume_source.py`;
`ExecutionResult.is_durable_pause` is the single durability home (CLI + MCP consume it); `/api/runs`
surfaces `resumed_from` + UI paused badge/chain marker shipped. Follow-on filed: **#562** (resumable
inline workflows — trace stores workflow content).

**Unplanned lane shipped while 171 was in flight: Task 116 Windows Compatibility** (PR #564, merged
2026-07-07 — jumped the queue from "Later"; roadmap + task Status reconciled 2026-07-11). ADR-0013:
POSIX-sh-everywhere — shell steps are Git-Bash-backed on win32, never a cmd/PowerShell fallback.
Blocking `windows-latest` CI job is live. Hardening tail also merged: #570 (shared Claude/Codex agent
assets), #571 + #573 (Windows test workflow fix + speed), #576 (zero-warning suite, explicit
encoding + `EncodingWarning` net). Spawned issues: **#566** (Windows liveness signal for streamed
trace UI — no `fcntl`; explicitly NOT an mtime heuristic), **#567** (POSIX shell-node process-group
kill on timeout — Windows tree-kills, POSIX leaks grandchildren), **#568** (track/cancel detached
UI-launched runs, must respect ADR-0008), **#572** (Windows dev test workflow portability), **#574**
(pytest isolation fixture overhead), **#575** (code-node bare I/O uses locale encoding on Windows).

**Loose ends CLOSED 2026-07-11 (owner-approved):** #541 verified fixed by #557 and closed; task
statuses corrected (163 → done, 117 → not started — uncommitted); the full worktree sweep ran —
all 30 stale trees + branches deleted after per-branch verification (merged-PR headRefOid == tip,
clean). The long-held `feat-unified-node-storage` mystery resolved: its branch was **merged all
along** (PR #526, 2026-06-21) — the 07-04 "unmerged commit" label was a squash-merge misread —
and its content was later superseded by 172's crash-tail tolerance anyway. Only main + the
in-flight `feat-web-ui-approval-bridge` remain.

**Parallel-lane candidates (re-scanned 2026-07-11; deep-verified 2026-07-02 unless marked):**
- **#542** trace retention — **NOW UNBLOCKED** (its gate was "design WITH/AFTER 171"). Design must
  treat `paused` traces as live obligations, never prunable; `resume list` depends on trailer scan.
- **#562** resumable inline workflows — natural 171 follow-on; touches trace format → serialize
  with any other trace toucher.
- **#546** pinned-run resolve race · **#561** TTS clip cache (design, backlog) · **#538** liveness
  backstop (now partially superseded by #566's Windows framing? — check before starting either).
- **#544** `llm_*` write-side canonicalization · **#549** post-#539 visibility cleanup · **#528**
  CLI `--output-format` stragglers.
- **#565** (new 07-07) — probe advertises MCP tool outputs as top-level `${success}` but values
  live under `result.*` — agent-facing correctness bug, small, likely registry/probe surface.
- **#357** memo-cache drift — issue state UNVERIFIED since 2026-06-23 → check. (Its old fix
  worktree `fix/fix-cache-key-drift` was pruned in the 07-11 sweep — merged as PR #524, the
  guard; the issue itself may still be open work.)

**Session handoff (2026-07-11) — everything committed; working tree clean.** Two commits:
`276672a4` (176 spec refresh + ledger, 116/CLAUDE.md reconcile) and the closing docs commit
(status fixes 163→done/117→not started, this log, the squash-merge sub-trap added to the
kickoff command's failure mode #1). Neither is pushed. The brief lives only in the launched
worktree (`scratchpads/` is gitignored — by design).

**Watch list (non-obvious, easy to miss):**
- **176 in flight:** the spec refresh + decision lock is DONE (2026-07-11 — do not redo);
  what remains watchable: the builder must surface any engine/payload need as an escalation
  (spec rule), the greying cut-line may spawn a follow-up issue, and real-browser verification
  requires killing stale `pflow ui` servers first (the reuse-if-up probe serves old code —
  recorded 171 gotcha).
- **Trace-format seam is hot:** 171 (2.7.0) + #562 + #542 all touch trace/trailer semantics —
  serialize; never fan out.
- Recurring fact-conflation attractor: `is_trace_locked` (probe, `ui/run_tailer.py`) vs
  `_lock_trace_handle` (writer flock, `workflow_trace.py`) — two independent agents got this
  wrong; distrust docs that place the probe in `workflow_trace.py`. #566 adds a Windows dimension.
- Trace-touching work: the Task-159 baseline (`task_159/baseline/verify.sh`, restored green via
  #535) is a free outer regression net — run it.
- Windows is now a **blocking CI gate** — any new platform-sensitive code (subprocess, encoding,
  paths, `fcntl`) must clear `tests-windows`; ADR-0013 governs shell semantics.
- Spec file:line refs were last bulk-refreshed 2026-07-02 and the repo has since absorbed #557's
  format pass + 116's 117-file diff — treat ALL file:line refs as stale; re-verify at use.

## Log (append-only, newest first)

### 2026-07-11 — 176 launched + all four loose ends closed (same session, continued)
176 committed (`276672a4`: refreshed spec + ledger + 116/CLAUDE.md reconcile) and launched on
**fable** in `feat-web-ui-approval-bridge` (brief verified in-tree, base = the spec commit).
Then the owner cleared the parked items: (1) held worktree — investigation flipped the premise:
branch `docs/task-133-crash-tail-scope` was MERGED via PR #526 all along (the 07-04 "unmerged"
label was a commit-id-vs-squash misread — same trap as ever), and main's `trace_io.py` has since
shipped the truncated-tail tolerance that commit called deferred → deleted with the sweep.
(2) #541 closed with evidence (local `uv run --frozen ruff` hook = uv.lock 0.15.0). (3) 163 →
done, 117 → not started. (4) Full sweep: 30 worktrees + branches removed, each gated on
merged-PR headRefOid == tip; the one dirty tree's dirt was only an untracked brief copy.
**Left off: 176 building on fable; status flips + this log are uncommitted (ride the next docs
commit); on 176's merge — verify the two orchestrator catches, reconcile, unblock #546/#568.**

### 2026-07-11 — Task 176 spec-refresh + decision session (same session as the boot below)
Ran the 176-start sitting. Three parallel opus audits (UI server / web frontend / resume CLI)
classified every draft claim; personal spot-checks confirmed the load-bearing four. Draft's
biggest false assumption killed: trailer keys do NOT forward generically — `_RUN_COMPLETE_FIELDS`
(`run_tailer.py:611`) and `_run_entry` (`server.py:1178`) are deliberate allowlists, so 176 has a
real server-side half (light-wire `paused_node_id` + on-demand masked `gate_request` endpoint —
orchestrator-owned plan call). Step-back audit caught two gaps the spec couldn't know: the
DEVNULL fire-and-forget spawn makes refused resumes silent no-ops (fix: in-process pre-flight,
the `/api/run` pattern) and `PFLOW_EXECUTION_ID` is honored by `run` only (resume needs the
mirror hook or the browser can't pin the new attempt). Owner locked 3 decisions (ledger in the
spec): escalations IN, greying IN-phased-last, `resolved_via:"ui"` OUT — approved on the
plain-language rationale now recorded verbatim in ledger #3 (spoofable, no consumer, fails the
deletion test; lineage is the structural provenance). Spec rewritten in place with provenance;
brief written (curated index, trust notes). Collisions recorded: #546/#568 serialized behind
176; #542 semantic rule (paused traces un-prunable) in both places. No ADR (nothing
hard-to-reverse). **Left off: awaiting owner go to commit spec+brief and launch the worktree on
fable; held worktree + #541 + 117/163 statuses still pending from the boot.**

### 2026-07-11 — boot: week-stale log reconciled; 171 + 116 shipped
Boot verification (user prompt: "171 and 116 completed and a lot more") found `## Now` a week
stale. Verified merged reality: **171** (PR #563, 07-05 — read the PR body; worktree tip's
post-review `isdecimal` fix confirmed present in `runtime/resume_source.py` on main → worktree
prunable) and **116 Windows** (PR #564, 07-07, ADR-0013) + its hardening tail (#570/#571/#573/#576).
Six new issues slotted into lanes (#562 trace follow-on; #565 probe bug; #566/#567/#568 Windows/
process lifecycle; #572/#574 test-infra hygiene). Reconciled: CLAUDE.md (116 → ✅, removed from
Later), task-116 Status → done (its flip condition — blocking green Windows gate — was met at
merge), this log's `## Now` rewritten. **#542 retention is now unblocked** (its gate was 171).
Flagged, not fixed: tasks 117 + 163 read "in progress" with no live work — owner call. **Left off:
176 is next on the critical path but its spec predates 171's beyond-spec deltas → spec refresh
required before launch; held worktree + #541 close + 117/163 status still await the user.**

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
