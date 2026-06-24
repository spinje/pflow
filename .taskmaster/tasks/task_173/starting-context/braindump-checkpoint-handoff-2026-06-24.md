# Braindump: Task 173 checkpoint handoff (2026-06-24)

**Read these FIRST, then this** (this doc deliberately does NOT repeat them):
- `.taskmaster/tasks/task_173/implementation/implementation-plan.md` — decisions D1–D7, workstreams A–E,
  the **Deep-review findings (R1–R8)** with a status header, the **"NOT yet built"** line (authoritative
  remaining work), the risk register.
- `.taskmaster/tasks/task_173/implementation/progress-log.md` — the chronological journey, every deviation,
  the hardening pass, the learnings.
- `.taskmaster/tasks/task_173/starting-context/braindump-producer-handoff-2026-06-23.md` — the 172→173
  tailer trap list (still 100% relevant).

This braindump is ONLY the tacit stuff that isn't in those files.

## State in one line

The **hardened thin slice is shipped, fully green, browser-verified, and UNCOMMITTED.** Next is the
checkpoint: **host `node.start` (option a)** → then one sub-workflow + one parallel batch end-to-end.

## CRITICAL practical facts (would bite immediately)

- **Nothing is committed.** All ~17 files are working-tree only (`git status`: 14 modified + `run_tailer.py`,
  `tests/test_cli/test_run_tailer.py`, `web/src/graph/status.test.ts`, `web/src/api/runEvents.test.ts`). The
  user hasn't decided whether to commit the green milestone — **ask before doing anything destructive.**
- **`report.py` was rebuilt from memory by a subagent** that `git checkout`'d it (destroying the uncommitted
  R5 edit) during a mutation test. I verified its `git diff` is byte-identical to intent (+30/-2). It's fine —
  but **never let a subagent run mutation tests that `git checkout` files carrying uncommitted work.** Tell
  any test-writer subagent this explicitly.
- Verification artifacts live in `scratchpads/task-173-live-overlay/verify/` (the `slice-probe.pflow.md`,
  baseline/after logs, screenshots, and now-superseded `producer_check.py`/`tailer_check.py` throwaways —
  the committed tests replace those two; discard them).

## THE next-step recipe (host node.start = option a) — the tacit mechanics

The plan says "`descend()` flushes its own start line." Here's the *how* and the trap the plan doesn't spell out:

- `WorkflowTraceCollector.descend(node_id)` (`runtime/workflow_trace.py`) already reserves the host's `seq`
  and builds the `_HostFrame` **pre-order, before the body runs**. Add a **disk-only** `node.start` flush
  there (same shape `begin_node` writes: `kind:"node.start"`, `status:"running"`, the frame's
  `seq`/`parent_id`/`ancestor_path`, `port:None`), NOT appended to `self.events`. The host's completion event
  (engine step 16, `frame=host_frame`) already reuses `frame.seq` → last-wins. node_type is always
  `"WorkflowExecutor"` for descend callers (hardcode it or thread it; don't overthink).
- **Why this is safe:** descend is only ever called on the **run-scoped collector on the owner (main) thread**
  (it already `_assert_owner_thread()`s). The OLD buffer path "never descends" (pinned by
  `test_old_path_sequential_batch_of_subworkflows_stays_nested`). So a flush there can't hit a worker.
- **Gate after:** re-run the 3 host-frame pins + the join pin (now covers node.start) + the equivalence tests
  (`tree()==reconstruct`). Then **browser-verify a real sub-workflow** — the host card should light *running*
  while its children run, instead of dead-until-complete.

### ⚠ The non-obvious gap option (a) does NOT close (I'd be furious not to flag this)

Host `node.start` via `descend()` lights **sequential sub-workflow hosts** and (via `begin_node`)
**flat nodes + batch-of-LEAF hosts**. It does **NOT** light a **parallel-batch-of-SUB-WORKFLOWS host**:
that host is a `WorkflowExecutor` (so `begin_node` skips it) AND it does **not descend** the run collector
(items run on workers via the buffer path). So it records only at completion → shows pending-until-done.
**For the checkpoint's parallel-batch case, use a batch of LEAF nodes (e.g. parallel batch of `llm`/`shell`)
so the host lights running** — or knowingly accept host-pending for batch-of-subworkflows and document it.
Don't chase this as a bug; it's the v1 boundary (batch-item granularity is deferred regardless).

## Tacit traps the next agent WILL hit

- **Watch the browser console during checkpoint verification.** I added a dev-only join-miss warn
  (`GraphView.tsx`, R1): `"pflow overlay: N run-event(s) join to no graph node…"`. The checkpoint
  (non-empty `ancestor_path`) is exactly where producer-`ancestor_path`-vs-renderer-`RFRef` **drift** first
  appears, and it fails SILENTLY (node never lights, nothing raises). That console warn is your only signal —
  if a sub-workflow child doesn't light, check the console before debugging anything else.
- **Shell nodes have a 30s default command timeout.** My first probe `sleep 30` → timed out → run *failed*
  (the overlay correctly showed red, which accidentally proved the failed path). Use a sub-30s sleep or
  `- timeout: 120`.
- **Screenshot timing:** poll the trace until the node is mid-flight (`node.start` present, no completion),
  THEN screenshot. `uv run` startup (a few seconds) eats a naive fixed-delay window. The recipe is in the
  progress-log verification section; reuse `scratchpads/.../verify/slice-probe.pflow.md` as the template.
- **`@pytest.mark.trace_files`** is required for any test asserting on disk — the conftest patches
  `_open_stream` OFF otherwise (`begin_node` still returns a frame and reserves seq, but writes nothing).
- **Don't "simplify" two things back:** (1) the distinct `node.start` *kind* into `event`+`status:running`
  (breaks every reader + the raw-line-count tests — see progress-log deviation); (2) the tailer's
  to_thread *split* (I/O in thread, parse/state on loop) into "just wrap `_poll_once` in to_thread" — that
  re-introduces a `snapshot()`-vs-mutation race. Both are load-bearing.

## User's mental model (their words + priorities)

- **"Show what's running"** is the whole point — they overrode the spec's deferred-flipbook and had me build
  `node.start` because a live overlay that can't show the in-flight node is **"half a product."** They think
  in terms of **"observe, don't host"** and **"the simplicity of the FINAL code."**
- They chose **MAXIMAL run-navigation scope** (live overlay + `/api/runs` + catalog running-badge +
  per-workflow history/replay + a **global dashboard**). They want the full thing, not minimal. The framing
  that sold it: *live and historical are the same render path* (a finished trace is a live run that ended).
- **They want to UNDERSTAND, not rubber-stamp.** They asked sharp drill-downs ("how does the server know a run
  is running?", "what does *distinct line kind* mean and what are the implications?"). Bring decisions to them
  with reasoning + a recommendation (the AskUserQuestion pattern worked); don't silently proceed on anything
  impactful. They flagged context budget proactively — they're efficiency-minded.
- **Real-browser verification is non-negotiable** to them — a green unit test over a wrong assumption "is
  worse than none" (it reverted a prior #529 attempt). Always screenshot the actual canvas.

## UNEXPLORED / decisions still open

- **UNCLEAR: the launch POST (`POST /api/run`, D4) — in v1 or not?** I recommended deferring (it's the only
  mutating endpoint → the CORS tripwire trigger), but the global dashboard makes a "Run" button tempting. The
  user hasn't ruled either way. Surface it when you reach the dashboard.
- **CONSIDER: the detail panel isn't designed yet.** The run-event currently carries only
  `ref+status+duration+cost` (blobs deliberately OFF the wire). Rich detail (resolved IO, tokens, `llm_call`)
  needs either fatter events (re-introduces the blob-on-wire problem) or a GET endpoint reading the post-run
  trace. Decide the source before building it.
- **MIGHT MATTER: MCP runs don't stream** (`trace_enabled=False`) — an agent run via the **MCP server tool**
  is NOT watchable; via the **CLI** it is. The ADR's "watch any agent run" has this asterisk. The launch-POST
  spawns a CLI run, so that path is fine, but set expectations.
- **CONSIDER: the dashboard is a big, verification-heavy chunk** — 3 views, each its own mandatory
  browser-verification surface. The shared `/api/runs` + replay engine is cheap; the *views* multiply the
  verification. Sequence the data layer first, prove replay, then add views one at a time.
- **`&run=` pinning needs its own tailer code path** (review S-a): the current `_poll_once` always switches to
  `discover_live_trace`'s newest; a pinned *historical* run must NOT be yanked when a new live run starts.
  Build this with the dashboard, not before.

## What I'd tell myself

- The single highest-leverage thing I did was **make the join failure loud** (the pin now covers node.start +
  the dev console warn). Everything else about this feature is recoverable; a silent join miss is the one bug
  that looks identical to "working." Lean on those guards hard at the checkpoint.
- I almost recommended **option (b)** for the host wrinkle (the plan originally leaned that way). The review
  killed it. Option (a) is right. Don't reopen it.
- The throwaway-verify-script → committed-test promotion is done for the producer + tailer; the remaining
  **tool-elevation verdict** is for the `slice-probe.pflow.md` + the "launch live run → poll trace → screenshot
  overlay" loop. That loop is a strong *elevate* candidate (no existing skill drives a *live* run) — record the
  verdict in `task-review.md` at task end (it doesn't exist yet).

## For the next agent

1. **Start by** reading the plan + progress log (above), then confirm the working tree is still green
   (`make test`, `make check`, `cd web && npx vitest run`) — nothing's committed, so don't assume.
2. **First implementation move:** host `node.start` via `descend()` (the recipe above), gated by the 3
   host-frame pins, then browser-verify a sub-workflow host lights running.
3. **Then** the checkpoint's parallel batch — use a batch of LEAF nodes (per the gap above).
4. **The user cares most about:** the overlay actually showing live state (verified in a real browser), and
   being brought into impactful decisions with your reasoning. Keep the plan + progress log updated as you go.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read
> and understood by summarizing the key points, then state you're ready to proceed.
