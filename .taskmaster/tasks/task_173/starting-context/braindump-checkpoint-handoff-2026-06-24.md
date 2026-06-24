# Braindump: Task 173 checkpoint handoff (2026-06-24, UPDATED post-flock / D6 Phase-3a-3b)

> Living handoff, updated in place. SHIPPED since the original Phase-1 pause: D6 **Phase 1+2** (`/api/runs` +
> `&run=` pin), **Phase 3a/3b** (catalog running-badge + run selector), and **EXACT `flock` liveness** (which
> REPLACED the `STALE_RUN_S` heuristic). Tacit stuff only — the journey, the DR-1..7 decisions, and the gates
> are in the files below; this is what ISN'T in them.

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

**The live-overlay CORE + D6 Phase 1+2 + Phase 3a/3b + EXACT flock liveness are all SHIPPED and COMMITTED.**
7 Task-173 commits: `c9f31a20` (slice) → `4c036b6d` (host-lighting + `--only` fix) → `29ed2fea` (shared
scanner foundation) → `01721ca3` (keepalive test) → `075dc825` (`/api/runs` + `&run=` pin) → `05dd6d9c`
(catalog badge + run selector) → `1bab750c` (flock liveness). Clean tree; `make test` **8145**, `make check`
clean (mypy 238), vitest **572**, `tsc` clean. **Next: the user's UI-polish items (see the section below),
THEN Phase 3c global dashboard → Phase 4 ChipRail chip → Phase 5 `/api/run-node` detail panel → pin D1 →
`task-review.md` + tool-elevation verdict.**

## UI items to address BEFORE the next plan phases (user-identified, 2026-06-24)

> The user flagged these from clicking around the live overlay; they want them done before resuming the
> Phase 3c/4/5 sequence. **(AWAITING the user's list — to be filled in this handoff before it's final.)**

## CRITICAL practical facts (would bite immediately)

- **Everything is COMMITTED — clean tree at `1bab750c`** (`make test` 8145, `make check` clean, vitest 572).
  7 Task-173 commits (see "State in one line"). Clean slate — no uncommitted work. NOTE: hashes were rebased
  since the original handoff — the old `1fa6d7a6`/`bbc1dd91`/`48d7a24f` are now `c9f31a20`/`4c036b6d`/`29ed2fea`.
- **⚠ THE SERVER SERVES STALE CODE + A STALE BUNDLE until you restart it.** `pflow ui` imports
  `run_tailer.py`/`server.py` at startup AND serves the *built* `web/` bundle. After ANY server/tailer change
  → `pkill -f "pflow ui"` then `uv run pflow ui --no-open --port 8765`; after ANY `web/` change →
  `make ui-build` (+ cache-bust the MCP browser with `&v=<new>`). This is the #1 "why didn't my change show
  up" trap — it bit me repeatedly across phases.
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

## Shipped invariants to PRESERVE + remaining-phase traps

`d6-plan.md` has the DR decisions; DR-1 / `/api/runs` / liveness are now SHIPPED — these are the invariants
NOT to break + the traps for the phases still ahead:

- **DR-1 (SHIPPED): tailers are keyed on `(workflow_key, run_id|None)`** (`server.py`
  `ensure_tailer`/`release_tailer`/`broadcast_run`/`windows_for_run`/`_send_or_evict`; `RunTailer.run()`
  branches on `self._run_id` — pinned resolves `run_id→Path` ONCE via `_resolve_pinned`, never re-discovers;
  stale id → `run-not-found`). **Invariant to PRESERVE:** run-events go via run-scoped `broadcast_run`
  (pinned + unpinned of one workflow must NEVER cross-feed); Point's `broadcast` stays workflow-scoped. And
  `ensure_tailer` treats a DONE task as ABSENT (the dead-tailer-reuse Critical fix from the Phase-1+2
  deep-review) — don't undo that liveness check.
- **`/api/runs` (SHIPPED) consumes `scan_traces`, NOT `_iter_workflow_traces`** (the latter full-parses per
  candidate). **Invariant to PRESERVE:** the `--only` policy lives in the CALLER — `scan_traces` yields raw,
  `/api/runs` LABELS `--only`, `discover_live_trace` EXCLUDES it.
  `test_scan_traces_yields_raw_candidates_keeping_only_policy_in_callers` pins it — never pull the `--only`
  filter into `scan_traces`.
- **`/api/run-node` (Phase 5, NOT built) WILL leak `node_type` if you "return the full event."** Mirror
  `run_tailer._run_event` (the GOLD STANDARD — it projects an allowlist + drops `node_type` with a comment)
  and map kind via `node_type_tag()` (`core/node_type_display.py`, verified to exist). The full trace event
  carries `node_type` (Python class name) on EVERY line — a blacklist-by-omission will ship it.
- **Liveness is now EXACT via `flock` (SHIPPED `1bab750c`) — `STALE_RUN_S` is DELETED; do NOT bring it back.**
  The producer holds an advisory `flock(LOCK_EX|LOCK_NB)` on its open trace handle for the run's lifetime
  (`workflow_trace.py::_lock_trace_handle`); the kernel frees it on ANY process exit. The server probes it
  (`run_tailer.is_trace_locked` — separate-fd `LOCK_NB`); `/api/runs` `live = not complete and
  is_trace_locked is not False`. An incomplete run with a FREE lock → broadcast `run-stopped` ONCE → the
  canvas flips dangling `running`→`stopped` (amber). **Subtle bug ALREADY FIXED (don't reintroduce):** a
  clean `finalize()` landing in the read→probe gap looked like a free-lock crash → `_check_stopped`
  re-confirms via `read_run_status` (the `run.complete` trailer flushes BEFORE the lock releases, so a free
  lock + still-incomplete tail = a REAL crash). Caveats baked in: **`flock` not `lockf`** (per-handle / OFD —
  `lockf` is a per-process footgun); Unix-only with a no-`fcntl` Windows fallback (incomplete=live); local-FS
  assumption; `is_trace_locked`'s `except OSError: return True` degrades an unsupported FS to always-alive,
  NOT false-stopped. **`flock` detects DEATH, not HANG** — the alive-but-stuck backstop is the ONLY deferred
  liveness piece → **GH #538** (re-scoped).
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
  `snapshot()` race); `_emit_node_start` (single-sourced node.start shape shared by `begin_node` + `descend`);
  and the flock pieces — `flock` not `lockf`, the free-lock `read_run_status` re-confirm (the clean-finish
  race fix), and `is_trace_locked`'s `except OSError: return True` (unsupported-FS probe → always-alive, NOT
  false-stopped). All load-bearing.
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
- **"Simplicity of the FINAL code" is their literal tie-breaker — they invoke it verbatim to push past
  band-aids.** On liveness they rejected BOTH heuristics by reasoning it out (fixed-60s → false
  "interrupted" for LLM nodes; "incomplete=running" reframe → blue-blinks-forever on crash) and asked *"what's
  the right solution the top 10% of codebases would build — have we considered it?"* → which landed on
  `flock` (it DELETES code: the heuristic + all the per-node-timeout/retry bookkeeping a deadline approach
  needs). They also probe relentlessly ("doesn't it just blink forever then?") — answer the failure mode
  honestly, don't hand-wave. Lesson: when a heuristic feels unsatisfying, they want the exact primitive that
  makes the final code SIMPLER, not a tuned guess.

## NEEDS VERIFICATION / still-unverified (the honest list)

Since the original list: **flock death-detection IS now browser-verified** (`kill -9` mid-node → `stopped`,
no forever-blink; a 67s-silent node stays `live`), and **concurrent runs now have the `&run=` pin** as the
fix. **Still NOT driven in a real browser** (low risk, mechanism sound — but the user WILL ask):
- **Looped SUB-WORKFLOW host** flipbook (looped leaf + nested host tested separately, not combined).
- **`status-cached` for a real LLM node** (used a `code` node with `cache:true`; no API key).
- **The in-place dropdown→pin SWAP as one live click** (covered by composition: `RunSelector` `onSelect` unit
  test + the Phase-2 `&run=` browser proof — but not one continuous gesture).
- **In-page run-reset / run-stopped VISUAL on ONE persistent page** (proved at the SSE-wire level + a
  fresh-page reload; not a single page transitioning live).
- The **expanded-region running ring is subtle** → the **ChipRail status chip (Phase 4)** is the fix.
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

1. **Start by** reading `d6-plan.md` (DR-1..7 — still the spec for the remaining surfaces) + the last few
   progress-log sections (Phase 1+2, 3a/3b, flock + its deep-review). Clean tree at `1bab750c`. Restart
   `pflow ui` + `make ui-build` before ANY browser check (see the stale-server trap above).
2. **First move: the user's UI-polish items ("UI items to address" section above) — those come BEFORE the
   next plan phases.** Then the remaining D6/closeout in order: **Phase 3c** global dashboard (`?view=runs`,
   DR-7) → **Phase 4** ChipRail status chip (also fixes the subtle expanded-region ring) → **Phase 5**
   `/api/run-node` detail panel (DR-4 allowlist projection — the `node_type`-leak trap above) → **pin D1** →
   **`task-review.md`** + the tool-elevation verdict (the DOM-status-probe + drive-a-live-run loop is the
   strong elevate candidate).
3. **The user cares most about:** the overlay working in a real browser (DOM-verified, not just green tests);
   being brought into impactful decisions with your reasoning + a recommendation (the AskUserQuestion
   pattern); honest accounting of what you HAVEN'T verified; and simplicity of the FINAL code. Commit green
   milestones — **ASK first** (NEVER `git commit` unprompted).
4. **Cleanup owed:** remove the temp saved workflow `~/.pflow/workflows/zzz-badge-probe` (a sandbox blocked
   the `rm`) + kill any leftover background `sleep` runs from the demo. The showcase workflows under
   `scratchpads/task-173-live-overlay/showcase/` are demo artifacts (elevate-or-discard at task end).

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read
> and understood by summarizing the key points, then state you're ready to proceed.
