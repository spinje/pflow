# Task 173 Review: Live Execution Overlay

## Metadata
- **Implemented:** 2026-06-23 → 2026-06-29, branch `feat/live-execution-overlay`.
- **Commits (recent anchors; many across the branch):** version-aware replay `e2db36b2`, run-discovery `494b0385`, "This run" detail panel `477c95a3`, catalog redesign `dd0203d5`, analyze-cache R6 `057e30f2`. The D1-pin doc edits (ADR-0008 + `d1-event-schema.md`) and this review are uncommitted at write time.
- **Status:** feature-complete, browser-verified, **not yet merged**. No external users (CLAUDE.md) — formats are cheap to change, but **the test suite and the producer↔consumer wire ARE the contract**.
- **Journey:** the blow-by-blow (every decision, dead end, and browser check) lives in `implementation/progress-log.md`. Plans: `implementation/implementation-plan.md` (overlay), `implementation/d6-plan.md` (run discovery), `~/.claude/plans/yes-lets-write-the-fancy-simon.md` (detail panel). This review is the distilled forward-reference, not a re-narration.
- **Spawned Task 175** (run-from-UI) — the direct next consumer of this work; see Integration Points.

## Read First — the load-bearing block

**What exists now.** The engine streams its trace file incrementally as it runs (eager `meta` at t=0, a disk-only `node.start` marker per main-thread node, an advisory `flock` lock held for the run's life). The `pflow ui` server **tails that file** — the run never pushes to the server (ADR-0008) — and broadcasts deltas over SSE; the browser joins each event onto the static graph by **NodeId** and lights the node (running/success/cached/failed/stopped). A RunSelector pins/replays any past run; a "This run" detail panel reads one node's resolved input/output/cost/tokens directly off the trace. **The UI observes; it never hosts a run.**

**Read these first** (the spine — `file:symbol`):
- `runtime/workflow_trace.py` — `begin_node:835`, `descend:779`, `_emit_node_start:806`, `start_streaming:891`, `_assert_owner_thread:750`, `_lock_trace_handle:74`, `finalize:1001`.
- `core/trace_io.py` — node.start skip-arm `:144`, `RESERVED_LINE_KEYS:44`, `META_KEYS:29`.
- `ui/run_tailer.py` — `scan_traces:217`, `discover_live_trace:262`, `RunTailer.run:336`, `_resolve_pinned:413`, `is_trace_locked:106`, `_check_stopped:388`, `_consume`/`_handle:486`.
- `ui/server.py` — `_Hub.ensure_tailer:183`, `broadcast_run:151`, `events:447`, `runs:711`, `run_node:733`, security note `:826`.
- `ui/run_node.py` — `run_node_detail:35`, `_read_matching_event:65`, `_ref_matches:122`, `_redact:198`.
- frontend — `graph/focus.ts` (`refKey:17`, `applyStatus:33`), `api/events.ts` (the 7 run arms `:121`), `views/GraphView.tsx` (`subscribe:643`, gate `TERMINAL_RUN_STATUSES:68`).

**Invariants that must NOT break** (rule → what breaks):
1. **Read RAW trace lines for the join; never `load_trace_file`/`reconstruct` in the tailer or `run_node`.** They strip `ancestor_path`+`port` (`RESERVED_LINE_KEYS`) — the exact join keys → every event joins nothing → **silently blank overlay, no error.** This is the #1 recurring trap.
2. **`node.start` is disk-only** (never appended to `self.events`) and **reuses the reserved `_HostFrame.seq`**, threaded into ALL THREE completion sites (`engine:1161/1217/1298`). Break it → seq gaps, the marker never collapses onto its completion (duplicate/stuck nodes), and `nodes_executed` / `tree()==reconstruct` drift. (`begin_node` for leaves and `descend` for hosts both return `_HostFrame` — there is no separate "start frame" type; the engine local is *named* `start_frame` but typed `_HostFrame`.)
3. **Workers never call the run-scoped collector** (`_assert_owner_thread:750`) — they route to buffer collectors. Break it → non-deterministic `seq` corruption in a parallel-batch-of-sub-workflows run.
4. **The tailer is keyed `(workflow_key, run_id)` and `broadcast_run` is run-scoped.** Collapse either → a pinned replay and the live overlay of the same workflow cross-feed events.
5. **Any handler that touches the hub must be `async def`** (the hub's queues are lock-free + loop-affine). `runs`/`run_node` are sync ONLY because they touch zero hub state.
6. **Producer emit-time `ancestor_path` must `sameRef`-match the renderer `RFRef`.** `refKey` (JS, `focus.ts:17`) and `_ref_matches` (Python, `run_node.py:122`) are independent replicas of that ONE identity. Drift = silent non-lighting; the only alarms are the dev-only `console.warn` (`GraphView:717`) and the join pin test (below).
7. **Never surface raw `node_type`** (Python class name) to an agent — always `node_type_tag()`.
8. **Every secret-redaction site defers to `security_utils.is_sensitive_parameter`** (one word-aware rule).
9. **`start_streaming()` runs AFTER the `only_node` stamp** (`engine:650`→`655`), or `--only` runs poison their own meta.

## What Was Built vs Planned (divergences a future agent would otherwise "fix" back)

- **Running state = a distinct `node.start` line kind**, reader-ignored — NOT the originally-approved `event + status:"running"` re-flush. Overloading `event` would change its meaning for every post-hoc reader (`report`/`analyze-cache`/`--only`) and break raw-line-count tests; the seq-reuse + last-wins substance is unchanged. Now pinned in ADR-0008 + `d1-event-schema.md`.
- **`flock` advisory lock replaced the `STALE_RUN_S=60s` mtime heuristic** — exact death detection. The heuristic false-read a >60s LLM/claude-code node as "interrupted." `flock` detects death, not **hang** (a hung-but-alive process keeps the lock) → hang backstop deferred to **GH #538**.
- **Catalog git-bucketing** (runs grouped by git repo, "Other" last) replaced the plan's flat saved∪ran list (user's evolution). The **global `?view=runs` dashboard was deliberately NOT built** — `App.tsx` stays 2-view; the catalog covers per-workflow history. Don't "complete" it without a real third-view need.
- **ChipRail status-chip (planned Phase 4) was retired**, not skipped — the corner `StatusBadge` + hover chip solve the same visibility need. `ChipRail` now carries only static behavior-modifier chips.
- **Detail-panel `output` = report-parity precedence** (`llm_response` else `node_output`), not the plan's "combined dict" — avoids double-showing an LLM node's text.
- **`run-stale` is a full broadcast** (mirrors `run-stopped`), not the plan's snapshot-only — see Gotchas (first-subscriber timing).

## Seams & Contracts (where to extend; the leverage)

- **The D1 event-schema seam** is the ONE producer↔consumer contract (`node.start`/`event`/`blob`/`run.complete` kinds; `status` enum; `content_hash` for stale-replay detection). Canonical, as-built: `task_133/design/d1-event-schema.md`. Change the wire only there, then re-run the join pin.
- **The NodeId / `sameRef` join.** Producer stamps emit-time `ancestor_path` (elements `{node_id, batch_index}`); the renderer derives `RFRef`; they meet at `sameRef`. There are THREE replicas of this identity — keep them in lockstep: producer (`workflow_trace`), JS `refKey` (`focus.ts:17`), Python reader `_ref_matches` (`run_node.py:122`).
- **`scan_traces` is mechanism-only** (`run_tailer.py:217`): yields raw `TraceCandidate`s, newest-first, hash-scoped to a workflow's filename prefix when a `workflow_key` is given (so an idle viewer never opens unrelated files). It applies **no** `--only`/`final_status`/sort policy — each caller does (`discover_live_trace` excludes `--only` + prefers live; `/api/runs` LABELS `--only`). Adding policy here silently corrupts the other caller. `TraceCandidate.meta` is shared by reference across cache hits → treat read-only.
- **`broadcast_run` vs `broadcast`** (`server.py:151-181`): run-scoped vs workflow-scoped delivery, both through the single `_send_or_evict` eviction-policy home. Point commands stay workflow-scoped; run-events are run-scoped.
- **Numeric helpers are promoted to shared homes** so the UI is a **peer** of `trace_tree`, never an importer of `trace_report` internals: `trace_tree.event_cost`/`batch_item_cost` (`:524/:546`) + `llm_usage.input_token_total` (`:73`). The source-policy (`trace_partial`/`unavailable`→None) lives in ONE place. `trace_report`'s three privates now delegate; `_input_token_total` is kept-as-delegation only because a test imports it (`test_trace_report.py:30`). The hover chip and the panel both consume `event_cost`, so cost can't drift (a cached node → `0.0` on both).
- **One redaction rule** (`security_utils.is_sensitive_parameter:50`) — a delimiter-bounded word-signature match, so `author`/`tokens`/`secretary` no longer false-match while `api_key`/`X-API-Key`/`apiKey` do. Five consumers defer (`sanitize_parameters`, `mask_sensitive_value`, `rerun_display`, `batch_item_summary`, the panel).
- **Frontend status restyle is identity-preserving** (`applyStatus:33`): it returns the SAME node object when status is unchanged so `memo()` skips it; it is layered AFTER `applyFocus`, and `status` is not in `layoutKey` → status changes never trigger an ELK re-layout. The status map is keyed by `refKey` end-to-end. `status` is OPTIONAL on `LeafData`/`GroupData` → an idle canvas is byte-identical to pre-Task-173. The detail-panel gate is a conditional **render** (not CSS-hide) → a loop's next iteration remounts `ThisRunSection` and refetches the latest.

## Gotchas & Non-Obvious Coupling (the "if I'd known this" gold)

- **Eager `meta` created a new failure mode:** a run that crashes before its first node now leaves a `meta`-only file. Any "newest trace" consumer must prefer a COMPLETE trace — `report.py` and analyze-cache were guarded (R5/R6). A future trace-dir reader inherits this.
- **First-subscriber timing (bit us twice — `stopped`, then `stale`).** `events()` has no `await` between `create_task(tailer.run())` and `put_nowait(snapshot())`, so the first subscriber's snapshot is taken BEFORE the tailer latches any run-level signal. **Any new latched signal must be BOTH broadcast AND carried in `snapshot()`** (broadcast for the present opener — who is the first subscriber on every fresh page load — snapshot for late subscribers). Snapshot-only silently misses the opener.
- **`flock` confirm-before-claim race.** A clean `finalize()` also frees the lock (it flushes `run.complete` BEFORE releasing). So a free lock alone ≠ crash; `_check_stopped` re-reads the tail to confirm the run is still incomplete before broadcasting `run-stopped`, else a successful run flashes "stopped."
- **The overlay's failures are INVISIBLE to unit tests** — a node that doesn't light raises nothing. Browser verification is mandatory; the reusable instrument is the **overlay-status-probe** (a `.pflow.md` that reads each node's `status-*` class / badge `title` / computed style off the settled DOM). A green unit test over a wrong join assumption is worse than none.
- **`pointer-events:none` on the badge silently defeated the native `title` tooltip** — and reading the `title` ATTRIBUTE off the DOM "passed" while hovering showed nothing. Verify the behavior, not the attribute.
- **Chrome-scoped CSS vars (`--bg-field`/`--border`) are UNDEFINED on the React Flow canvas layer** → a badge/tooltip using them renders transparent. Use literals (`#1c1c1c`, the `#0d0d0d` halo) for anything that lives on the canvas.
- **Cached-node reduced input is producer-side, not a panel bug.** A cache-hit event records only the static `code` param, not the resolved `inputs`, so the panel shows less for a cached node. Pre-existing (Task 172); filed **GH #540**. Don't "fix" it in the panel.
- **RunSelector re-pick was a no-op that wiped the overlay** — `setRunId(same)` doesn't re-fire the SSE effect that refills the cleared status map. Guard: `if (next === runId) return`. Any "reselect current" path needs this.
- **A `web/` change is invisible until `make ui-build` + restart `pflow ui`** (the server serves the built bundle and imports the Python at startup). This caused several false "it didn't work" cycles — rebuild+restart before every browser check.
- **Long-lived SSE broke clean Ctrl+C shutdown** → `_Hub.shutdown()` wakes blocked queues with a sentinel so each stream RETURNS (not force-cancelled); `ui.py` uses a `uvicorn.Server` instance + restores the default SIGINT handler so uvicorn owns shutdown.
- **Process note:** test-writer subagents twice `git checkout`'d files mid-task (destroying uncommitted edits) and reconstructed them from memory — verify on-disk state with `git diff` after delegating edits to a subagent.

## Integration Points (blast radius + the Task-175 handoff)

- **Depends on:** Task 172 producer (the D1 schema + emit-time correlation), Task 169 SSE bus (envelope only), Task 155/168 static graph + NodeId (ADR-0003), ADR-0005/0008.
- **New dependents:** the `pflow ui` server (now stateful — a tailer per `(workflow_key, run_id)`); the detail panel; Task 164 (resume) inherits the streamable/crash-truncatable substrate; Task 125 (HITL) rides the same SSE envelope.
- **Task 175 (run-from-UI) is the direct next consumer** — hand it these:
  - (a) A launch POST is ADR-0008-clean **only as a detached `pflow run` subprocess** — the run writes its trace; the existing tailer/overlay observe it; the server stays a pure observer (no new run-hosting code).
  - (b) It is the FIRST mutating endpoint → it MUST revisit the security note (`server.py:826`): loopback + no-CORS + required `application/json` already block cross-origin POSTs; the lone gap is **DNS rebinding** → add a `Host`-header guard. No auth/CSRF needed for a single-user loopback server.
  - (c) **Inputs are recorded nowhere today** (trace `meta` omits them; they only seed the shared store) → 175's keystone is stamping `meta.inputs` onto the SAME eager-meta line this task made eager.
- **New contracts:** the trace gains `node.start` lines + eager `meta` + `content_hash` + a `flock` lock; new read-only GET endpoints `/api/runs`, `/api/run-node`, and `&run=` on `/api/events`. No external consumers → no migration, but the join keys are pinned by the test below.

## Tests That Matter (run these when you touch the overlay)

- **`test_runtime_event_refs_join_onto_the_static_graph`** — THE join pin (producer `ancestor_path` == renderer `RFRef`, covering `node.start`, leaf, and host). Re-run after ANY change to either side of the join. The one unit guard for the overlay's signature silent failure.
- **`test_emit_time_trace.py`** — `begin_node` disk-only + seq-reuse; the parallel-batch "no owner-thread error" safety net (a future refactor routing a worker through the run-scoped collector fails loudly here).
- **`tests/test_cli/test_run_tailer.py`** — hash-scoped discovery (another workflow's trace never opened), prefer-live, batched + last-wins delivery, byte-boundary buffering, `_resolve_pinned` / `run-not-found`, exact-liveness (provably FAILS under the old mtime heuristic), and the clean-finish-no-false-stop race guard.
- **`tests/test_cli/test_run_node.py`** — raw-read + structural ref match on a nested `ancestor_path`, blob resolve, last-wins, start-only→None, the **C1 NESTED-key redaction** (a flat redactor passes the top-level test while leaking a nested `headers.Authorization`), `_`-prefixed key drop, truncated-vs-malformed-line handling.
- **`tests/test_core/test_security_utils.py`** — the word-boundary redaction (`author`/`tokens` NOT matched; delimited secret variants matched).
- **Frontend:** `graph/status.test.ts` (refKey + `applyStatus` identity-preservation, host-group lighting, `unrecorded`), `api/runEvents.test.ts` (the 7 SSE arms + strict-boolean coercion), `ThisRunSection.test.tsx`, `views/GraphView.test.tsx` (the terminal gate + the **mutation-verified** re-pick guard).

## Deferred + Tool-Elevation Verdict

- **Filed:** GH **#538** (hang backstop — `flock` detects death, not hang), **#539** (SSE 6-connections/origin limit with many open graph tabs), **#540** (cached-node resolved inputs), **#541** (ruff pin sync — `make check` IS green; only a *direct* `.venv` ruff 0.15 run flags pre-existing files). **Unfiled:** trace retention/pruning — `~/.pflow/debug` grows unbounded (the dashboard's all-scan cost + ~1100 dead pre-172 files); Task 175 will multiply traces, so this is a reasonable fast-follow.
- **v1 boundaries (by design, not bugs):** batch ITEMS and the batch-OF-sub-workflow HOST get no `node.start` (the no-lock worker rule) → they show pending-until-done; a secret embedded in a free-text STRING value is uncaught (key-name redaction only — same residual as `pflow report` + the on-disk trace).
- **Doc debt (one-liners):** `ui/CLAUDE.md`'s `/api/runs` shape omits `git_root` (code ships it, `server.py:691`); `_has_run_complete` (`run_tailer.py:100`) appears dead with a stale docstring (`discover_live_trace` reads `cand["complete"]`); `_read_matching_event`'s docstring omits its `OSError`→None degrade path (`run_node.py:83`).
- **Tool-elevation verdict (owed by this task):** ELEVATE the **overlay-status-probe** + the **"drive a live run → poll the trace to a known state → read the DOM / screenshot"** loop — no existing skill drives a live run, and it was the decisive instrument for every overlay verification (status classes, badge `title`, computed style). The static `screenshot-pflow-web-ui` skill opens a URL with no concept of run state. The "restyle-as-static-HTML → shoot → user-picks" mockup loop is a secondary elevate candidate. The one-off verify `.pflow.md`s themselves are throwaway (discard).

---
*Distilled from the implementation context of Task 173. The chronological journey — every decision, dead end, and browser check — lives in `implementation/progress-log.md`; this review is the durable forward-reference, not a re-narration of it.*
