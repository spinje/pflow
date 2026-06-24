# Braindump: Task 173 checkpoint handoff (2026-06-24, REWRITTEN at the D6-Phase-1 pause)

> This file was the *slice → host-node.start* handoff; everything below "Next is the checkpoint" is now
> DONE and has been replaced. It is now the **D6 Phase-1 pause** handoff. Tacit stuff only — the journey,
> the DR-1..7 decisions, and the gates are in the files below; this is what ISN'T in them.

**Read these FIRST, then this:**
- `.taskmaster/tasks/task_173/implementation/d6-plan.md` — **the authoritative spec for what you're
  building now** (run-navigation). Revised post-deep-review; the **DR-1..7 decisions** are binding.
- `.taskmaster/tasks/task_173/implementation/progress-log.md` — the full chronological journey (P1 verify,
  P2 host-lighting, the `--only` fix, the fork pass, the deep-review, the Phase-1 foundation). Read the last
  three dated sections.
- `.taskmaster/tasks/task_173/implementation/implementation-plan.md` — the older D1–D7/workstreams/R1–R8
  context (the slice + checkpoint era). Still accurate for the shipped core; superseded by `d6-plan.md` for
  the D6 navigation work.
- `.taskmaster/tasks/task_173/starting-context/braindump-producer-handoff-2026-06-23.md` — the 172→173
  tailer trap list. **Still 100% relevant** (read-raw-lines, last-wins-by-id, blobs-backward-only).

## State in one line

**P1 (join) + P2 (host node.start + group-lighting) + the `--only` fix + the D6 Phase-1 FOUNDATION (the
shared `scan_traces`/`read_run_status` refactor) are all SHIPPED and COMMITTED** — 3 commits: `1fa6d7a6`
(slice), `bbc1dd91` (P2 + `--only`), `48d7a24f` (Phase-1 foundation + deep-reviewed `d6-plan.md`). Clean
tree. Next concrete move: `GET /api/runs` on `scan_traces`.

## CRITICAL practical facts (would bite immediately)

- **Everything is COMMITTED — clean tree at `48d7a24f`** (`make test` 8132, `make check` clean at commit).
  The 3 commits: `1fa6d7a6` (slice), `bbc1dd91` (P2 host-lighting + `--only` fix + docs), `48d7a24f` (D6
  Phase-1 shared scanner + deep-reviewed `d6-plan.md` + this handoff). You start from a clean slate — no
  uncommitted work to reconcile.
- **⚠ THE SERVER IMPORTS `run_tailer.py` AT STARTUP — you MUST restart `pflow ui` after any
  server/tailer code change before browser-verifying.** This bit me with the `--only` fix (the running
  server had stale code; I started a fresh one on :8766). **The :8766 server currently running has the
  `--only` fix but NOT the Phase-1 `scan_traces` refactor** — restart it (`pkill -f "pflow ui"` then
  `uv run pflow ui --no-open --port <port>`) before you trust a browser check of Phase-1 code. (:8765 was
  killed; only :8766 may still be up.)
- **The authoritative status signal is the DOM `status-*` class, NOT a screenshot.** I built
  `scratchpads/task-173-live-overlay/verify/overlay-status-probe.pflow.md` (reads each node's `status-*`
  class via a chrome-devtools `evaluate_script` node, reusing the skill's `open-and-settle` by ABSOLUTE
  path). **Use it.** I learned this the hard way: my first P1 screenshot was genuinely ambiguous
  (success-green vs running-blue at canvas zoom) — the DOM read removed all doubt. This + the
  "launch live run → poll the trace until the target node has a `node.start` and no completion →
  read/screenshot" loop is the verification SHAPE for everything in D6. It's a **strong tool-elevation
  candidate** (no existing skill drives a *live* run); record the verdict in `task-review.md` (doesn't
  exist yet) at task end.
- **Verification artifacts are in `scratchpads/task-173-live-overlay/verify/`** (gitignored): the probes
  (`subworkflow-probe` + `child-probe`, `batch-probe`, `fast-probe`, `subworkflow-fail-probe`,
  `overlay-status-probe`) and screenshots. The old `producer_check.py`/`tailer_check.py` are superseded by
  committed tests — discard. `slice-probe.pflow.md` is the original template.

## What you're building now (D6 Phase 1+) — the tacit shape

`d6-plan.md` has the DR decisions; here's the stuff that bites that the plan states but you'll under-weight:

- **DR-1 (the structural one): `ensure_tailer` keys on `workflow_key` ALONE today** (`server.py:146`). A
  pinned (`&run=`) replay and an unpinned live overlay of one workflow would fight over one tailer. You must
  re-key on `(workflow_key, run_id|None)` — this is the biggest change in Phase 2, not a tweak. There is
  **no `_poll_once`** — the poll body is inline in `RunTailer.run()`; branch once on `self._run_id`
  (pinned skips `discover_live_trace` entirely; resolve `run_id→Path` ONCE via `to_thread`, not every poll).
  A stale/missing `run_id` → broadcast `run-not-found` (don't sit on an all-`pending` canvas).
- **`/api/runs` consumes `scan_traces` (the foundation I built), NOT `_iter_workflow_traces`** — the latter
  does a full `load_trace_file` parse per candidate (defeats the cheap-read goal). The `--only` policy lives
  in the CALLER: `scan_traces` yields it raw, `/api/runs` LABELS it, `discover_live_trace` EXCLUDES it.
  `test_scan_traces_yields_raw_candidates_keeping_only_policy_in_callers` pins this — if you ever pull the
  `--only` filter into `scan_traces`, that test fails loudly. **Don't.**
- **`/api/run-node` (Phase 5) WILL leak `node_type` if you "return the full event."** Mirror
  `run_tailer._run_event` (the GOLD STANDARD — it projects an allowlist + drops `node_type` with a comment)
  and map kind via `node_type_tag()` (`core/node_type_display.py`, verified to exist). The full trace event
  carries `node_type` (Python class name) on EVERY line — a blacklist-by-omission will ship it.
- **Liveness is a HEURISTIC — don't try to make it exact.** `STALE_RUN_S` (default 60s): not-complete +
  fresh mtime = live; not-complete + stale = crashed. A slow LLM node (no append for 60s) false-reads as
  crashed; observe-don't-host forbids process tracking, so this is the best available. Expose RAW facts
  (`complete`/`final_status`/`live`/`only_node`) and let the UI compose the badge — do NOT invent an
  `interrupted` wire word (use the producer's `incomplete`/null).
- **The hash-glob optimization is deferred.** `scan_traces` uses an unscoped `glob("workflow-trace-*.json")`
  + `meta.workflow_path` filter (correct, O(N)). DR-3 mentions a `workflow-trace-{md5(path)[:8]}-*` prefilter
  for `?workflow=X`; if you add it, reuse the producer's EXACT hash (`format_trace_filename` in
  `workflow_trace.py`) or you'll silently miss this workflow's traces. It's a perf refinement, not
  correctness — I deliberately left it.

## Tacit traps (still 100% live)

- **Watch the browser console.** The dev-only join-miss warn (`GraphView.tsx`) — `"pflow overlay: N
  run-event(s) join to no graph node…"` — is your ONLY signal when producer-`ancestor_path` vs
  renderer-`RFRef` drift (the node silently never lights, nothing raises). Replaying historical runs +
  nested sub-workflows is where this resurfaces.
- **Shell nodes have a 30s default command timeout** — a slow probe needs `- timeout: 150`. And **every
  `.pflow.md` STEP needs a description paragraph** between `### heading` and `- params`, or it's a PARSE
  error → no trace written → easy to misread as "the overlay broke." (Both cost me a confused minute.)
- **`@pytest.mark.trace_files`** is required for any test asserting on disk (conftest patches `_open_stream`
  OFF otherwise). The `RunTailer` unit tests sidestep this by hand-writing trace files (`_write_trace`).
- **Don't "simplify" back:** the distinct `node.start` *kind* (not `event`+`status:running`); the tailer's
  `to_thread` *split* (I/O in thread, parse/state on loop — wrapping the whole poll re-introduces a
  `snapshot()` race); and `_emit_node_start` (the single-sourced node.start wire shape shared by
  `begin_node` + `descend` — don't re-duplicate it). All load-bearing.
- **v1 boundary that is NOT a bug:** a parallel/sequential batch-OF-SUB-WORKFLOWS host + batch ITEMS show
  pending-until-done (they never descend the run collector; workers can't touch it). For a batch that lights
  running, use a batch of LEAF nodes. Don't chase it.

## User's mental model (their words + how it evolved this session)

- **"Show what's running"** is the whole point — a live overlay that can't show the in-flight node is
  **"half a product."** They think in **"observe, don't host"** and **"simplicity of the FINAL code."**
- They chose **MAXIMAL** D6 scope (live overlay + `/api/runs` + catalog badge + per-workflow history/replay
  + a **global dashboard**). The framing that sold it: *live and historical are the same render path.*
- **They push HARD for honesty over rubber-stamping.** Mid-session: *"Are you FULLY happy with the
  implementation? Any loose ends?"* — and they meant it: I found a real gap (failed-host unverified) by
  taking it seriously. Don't present green as done; surface what you HAVEN'T verified.
- **They think in ADVERSARIAL verification.** They had me spin up a fork "verification specialist" with
  explicit anti-patterns: *"verification avoidance"* and *"being seduced by the first 80%."* Their exact
  framing: **"Test suite results are context, not evidence... the implementer is an LLM too — its tests may
  be heavy on mocks, circular assertions, or happy-path coverage."** The fork found the `--only` bug. When
  in doubt, drive the real thing and try to break it.
- **They want reviewed, methodical progress.** They explicitly chose "commit → `/deep-review` the approach →
  build" before a verification-heavy chunk. Bring impactful decisions with reasoning + a recommendation
  (the AskUserQuestion pattern worked every time). They flagged context budget — efficiency-minded.

## NEEDS VERIFICATION / still-unverified (the honest list)

The fork pass verified a LOT (nesting, node_id collision, loops, branching, run-reset at the wire level,
crash, degraded, cached, 64-queue under a bursty 60-node run). **Still NOT driven in a real browser** (low
risk, mechanism sound — but the user will ask):
- **Looped SUB-WORKFLOW host** flipbook (looped leaf + nested host tested separately, not combined).
- **Genuinely simultaneous concurrent runs** of one workflow (tested sequential A→B; the unpinned default
  picks newest-by-mtime among live and can flicker — DR-1/the pin is the fix).
- **`status-cached` for a real LLM node** (used a `code` node with `cache:true`; no API key).
- **In-page run-reset VISUAL** (proved at the SSE-wire level + fresh-page-follows-B, not one persistent page
  resetting live).
- The **expanded-region running ring is subtle** (the ChipRail status chip, Phase 4, is the fix — folded
  into the Phase-3 group work).
`d6-plan.md`'s 6 manual-test scenarios cover most of these — close them as you build the surfaces.

## What I'd tell myself

- The highest-leverage habit this session: **the DOM-status probe + drive-a-live-run loop.** Lean on it for
  every D6 surface — screenshots alone will burn you on status color.
- **The deep-review was worth it.** 5 agents on the plan caught 7 real under-specifications (the tailer
  keying, the `final_status` signal gap, the `node_type` leak) BEFORE any code. The DR-1..7 are hard-won —
  follow them; don't re-derive.
- The `--only` bug is a reminder: **the live overlay and the post-hoc readers (`_iter_workflow_traces`)
  share trace-dir semantics but differ on policy.** Keep policy in the caller; mechanism in `scan_traces`.

## For the next agent

1. **Start by** reading `d6-plan.md` (DR-1..7) + the last 3 progress-log sections. Clean tree at
   `48d7a24f` — restart the UI server (the running one has stale `run_tailer` code) before any browser check.
2. **First move:** `GET /api/runs` on `scan_traces` (label `--only`, non-200 on scan error, `200+[]` for
   zero runs, include inline `ir-hash:` runs by name) — then the `&run=` pin (DR-1 tailer re-keying), then
   the 3 surfaces + the ChipRail chip, then `/api/run-node` (DR-4 projection).
3. **The user cares most about:** the overlay actually working in a real browser (DOM-verified), being
   brought into impactful decisions with your reasoning, and honest accounting of what you HAVEN'T verified.
   Keep the progress log updated as you go; commit green milestones (ask first).

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read
> and understood by summarizing the key points, then state you're ready to proceed.
