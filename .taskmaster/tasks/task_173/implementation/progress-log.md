# Task 173 — Live Execution Overlay — Implementation Progress Log

> Living document. The full implementation plan (decisions D1–D7, all workstreams, build order, risk
> register) lives at `.taskmaster/tasks/task_173/implementation/implementation-plan.md`. This log captures the
> *journey*: what I did, why, what I learned, and where I deviated from the plan/spec.

---

## 2026-06-23 — Context gathering & design (pre-code)

Read order: `task-173.md` → `d1-event-schema.md` → the 172→173 handoff braindump → the three pin tests
in `test_emit_time_trace.py` → the kickoff brief (`scratchpads/task-173-live-overlay/kickoff-brief.md`).
Dispatched five parallel `pflow-codebase-searcher` agents (ADR-0008, SSE transport, frontend seams,
producer discovery/ripple, engine emit points) and verified their citations against `main` before coding.

### Key findings that shaped the build

- **Transport is settled by ADR-0008 and it's NOT the obvious one.** The tempting design — have
  `pflow run` POST events to the server (mirroring `pflow ui focus`) — is the alternative ADR-0008
  **rejects** (server may be down at run start, no replay mid-run, lifecycle coupling). Mandated design:
  the run only writes its trace file; the `pflow ui` server **tails** it. This makes the previously
  stateless server **stateful** for the first time (a tailer per watched workflow).
- **The frontend seams are genuinely reserved.** `applyFocus` (`web/src/graph/focus.ts`) is the exact
  template for a status pass — it returns the *same* node object when nothing changed, so `memo()` skips
  it. The stable join key is the `RFRef` (`node_id + ancestor_path + port`), already used by
  `remap.ts::sameRef`/`flatIdForRef`. SSE bus is vocabulary-agnostic → adding a `run-event` type is 3
  additive spots.
- **The tailer's traps are pinned by tests** I can read as spec (`test_streamed_wire_*`): read RAW lines
  (NOT `load_trace_file` — it strips `ancestor_path`/`port`, the join keys), tolerate a truncated final
  line, key on `id` last-wins (dead-end re-flush), resolve blobs forward-only.
- **`node.start` is cheap** (engine-emit-points search): the producer already has the exact machinery —
  `mark_last_event_failed` re-flushes the same `id` with a corrected status; the reader dedups last-wins.
  A start signal is that mechanism pointed at node *start*. The one hard limit: parallel-batch *items*
  can't get individual start signals (no-lock owner-thread rule) — the batch *host* can.

### Decisions (with the user)

- **D1 — running-state representation: build `node.start`** (user-confirmed via AskUserQuestion).
  The kickoff brief reopened this (task-173.md had deferred it / accepted a "flipbook"); I recommended
  building it because the flipbook is *fragile inference* (impossible for parallel batch) while
  `node.start` is *one honest signal* → a clean `pending→running→done` state machine. Schema authority
  granted by the brief.
- **D6 — run-discovery scope: maximal** (user chose "core + in-context + global dashboard"). The insight
  I surfaced: **live and historical are the same render path** (a finished trace is a live run that
  ended), so replay/history/dashboard are *views over one `/api/runs` data layer* — the cost is
  per-view browser verification, not architecture. Deferred to post-slice phases.
- **D4 — launch POST: deferred** (recommend; the only mutating endpoint → the CORS tripwire trigger).
- **Slice-first** (user agreed): the one empirically-unverifiable risk is the runtime join (does the
  producer's `ancestor_path` actually `sameRef`-match the renderer's `RFRef` so the right node lights?).
  The slice is the cheapest test of that, and it *is* step 1 of the real build, not throwaway.

### Terminology (CONTEXT.md, updated inline)

`task-173.md` says "watch a run execute," but **"Watch" and "Auto-update" are both already glossary
terms** (agent watching user interactions; viewer watching the source file). The overlay is a *third*
watching → added **"Overlay"** as the canonical noun + made the ambiguity note three-way.

---

## 2026-06-23 — Thin vertical slice: implementation

Baseline captured first: `make test` = **8119 passed** (the diff target).

### DEVIATION FROM THE APPROVED D1 ENCODING (the most important call this session)

The AskUserQuestion preview I got approval on showed the running signal as a `kind:"event"` line with
`status:"running"`, re-flushed at completion (same id, last-wins). **On contact with the code I shipped
it as a DISTINCT `kind:"node.start"` line instead.** Why:

1. Overloading `event` with `status:"running"` changes what `event` means for *every* reader (today
   `event` = "a node finished"; `report`/`analyze-cache`/`--only` all bank on that).
2. It breaks existing tests that count raw `event` lines on disk (they'd see 2× lines) — CLAUDE.md
   explicitly warns against rewriting contract tests.

A distinct kind keeps `event` = "completion" untouched and makes `node.start` a *known-but-ignored*
kind for post-hoc readers. The substance the user approved (build node.start, reuse the seq/last-wins
machinery) is unchanged. **It's also what D1's own "Deferred" section already named it.** Confirmed with
the user after the fact; they understood and accepted.

- 💡 **Insight:** `node.start` and the completion `event` share the same `id` (the start reserves the
  seq, the completion reuses it via the threaded frame). For the *reader*, node.start is skipped
  entirely, so the shared id is just bookkeeping that keeps on-disk `event` seqs **byte-identical** to a
  no-node.start run. For the *tailer*, the shared id is the last-wins key (running → terminal).
- **Cost (honest):** +1 small line per main-thread node in streamed traces (no payload on the start
  line). Bounded; a big loop adds 1 line/iteration.

### What I built, file by file

**Producer (`src/pflow/runtime/`):**
- `workflow_trace.py`:
  - `begin_node(node_id, node_type) -> _HostFrame | None` — reserves the node's `seq`, flushes a
    **disk-only** `node.start` line (NOT appended to `self.events`), returns a frame. Run-scoped +
    `stream_to_disk` only; owner-thread asserted via `_next_seq`.
  - `start_streaming()` — public wrapper for eager `_open_stream()` at run start (A1).
- `engine.py`:
  - `run()` depth-0, AFTER the `only_node` stamp (line ~650): `self.trace.start_streaming()` — eager
    meta so the file exists from t=0 (the `only_node` ordering is load-bearing — issue #443).
  - `_execute_node` step 8.5 (after `call_start_callback`): `start_frame = self.trace.begin_node(...)`
    **guarded `config.node_type_name != "WorkflowExecutor"`** (hosts reserve via `descend()`; host
    node.start deferred). Threaded `frame=host_frame or start_frame` into **all three** completion
    sites (step-16 record, step-10 api-warning, except-path record) so the terminal event reuses the
    reserved seq on every path — never re-takes it → no seq gaps for failing nodes.
- `trace_io.py`: `_partition_trace_lines` — one arm `elif kind == "node.start": continue` (skip; a
  live-only marker, not unknown-kind corruption).

**Server (`src/pflow/ui/`):**
- `run_tailer.py` (NEW) — the deep module for the file-tail. `discover_live_trace` matches by
  `meta.workflow_path` (robust to filename-hash details / path normalization) newest-by-mtime;
  `RunTailer` reads RAW lines from a byte offset, carries the incomplete final line, accumulates the
  blob map, keys state by `id` (last-wins), and **batches one poll's deltas into a single `run-events`
  message** (a fast run could emit >64 lines/poll and trip the hub's 64/conn eviction). `snapshot()`
  catches a mid-run subscriber up.
- `server.py`: `_Hub` gains `ensure_tailer`/`release_tailer` (one tailer per workflow_key, ref-counted
  to viewers); `events()` attaches the tailer on subscribe + sends the snapshot, releases on disconnect.

**Frontend (`web/`):**
- `types.ts`: `NodeStatus`, `RunEvent`, `RunComplete`.
- `graph/flow.ts`: `status?: NodeStatus` on `LeafData` (optional → `buildFlow` needs no change;
  `applyStatus` is the sole writer; pending = absent = no styling).
- `graph/focus.ts`: `refKey(ref)` (stable structural key, survives flat-id renumber) + `applyStatus`
  (the overlay restyle pass — identity-preserving like `applyFocus`, leaf nodes only in v1).
- `hooks/useWorkflowGraph.ts`: `runStatus` (optional, defaults to a stable `EMPTY_STATUS` constant);
  `applyStatus` layered after `applyFocus` in the decoration effect (a status-only change keeps the
  same `laid` → snaps, no re-layout/animation).
- `api/events.ts`: `RunHandlers` (optional via `PointHandlers & Partial<RunHandlers>` → back-compat) +
  guards + `run-events`/`run-snapshot`/`run-complete`/`run-reset` dispatch arms.
- `views/GraphView.tsx`: `runStatus`/`runBanner` state, run handlers in `subscribe` (keyed by `refKey`,
  so they need no graph + never re-subscribe), a minimal run banner.
- `components/nodes/WorkflowNode.tsx`: destructure `status`, push `status-${status}` class.
- `index.css`: status rings (outline, so they coexist with the focus box-shadow; running pulses) + banner.

---

## 2026-06-23 — Verification

Validated each layer in isolation BEFORE the browser (cheap, fast feedback), then end-to-end in a real
browser (the mandatory step — the kickoff brief warns a green unit test over a wrong assumption is worse
than none).

1. **Producer (throwaway `verify/producer_check.py`):** eager meta → file from t=0; node.start markers
   present with running status + join keys; seq reused (start.id == event.id); event seqs contiguous;
   reader drops node.start; `tree() == reconstruct`; final_status=success. ✅
2. **Server tailer (`verify/tailer_check.py`):** discovery by meta.workflow_path; run-reset on switch;
   batched run-events; **mid-run snapshot shows `b: running` while in-flight**; last-wins on shared id;
   port=null; run-complete banner. ✅
3. **Real engine (the probe run):** `meta, node.start(slow), event(slow), node.start(middle),
   event(middle), node.start(done), event(done), run.complete` — 3+3, ids reused, seqs 0/1/2. ✅
4. **Real browser (`screenshot-pflow-web-ui`):** all three states confirmed —
   - **running**: `slow` blue/pulsing mid-sleep, others idle
   - **failed**: `slow` red + "Run failed · 1 failed" banner
   - **success**: all green + "Run success · 3 nodes" banner; opened AFTER completion → also proved
     **replay-a-finished-run** (one render path).

### Learnings from verification

- 💡 **Discovery by `meta.workflow_path` beats hash-glob.** Avoids any drift with the producer's
  filename-hash logic and tolerates path normalization. The tailer reads only each candidate's first
  line. (Also: stale **pre-Task-172 single-object traces** in `~/.pflow/debug` fail `json.loads` on
  line 1 → `_read_meta` returns None → correctly skipped.)
- ❌ **A shell node has a default 30s command timeout.** My first probe used `sleep 30` → timed out →
  the run *failed*. This was actually a *good* accident — the overlay correctly rendered the failure
  (red node + "Run failed" banner), proving the failed path. Fixed by `- timeout: 120` + `sleep 40`.
- 💡 **Poll the trace to remove screenshot timing guesswork.** Instead of guessing when the run is
  mid-flight, I polled the trace file until `slow` had a `node.start` but no completion, *then*
  screenshotted. Reliable. (uv-run startup overhead — a few seconds — had eaten my first naive window.)
- 💡 The screenshot skill opens a *static* URL; it has no concept of run state. Driving a live run +
  polling + screenshotting is a new verification shape — a candidate to elevate (see below).

### Quality gates (final, all green)

- `make test`: **8119 passed** = baseline (zero regressions), after both the producer/engine/reader
  changes AND the server changes.
- `make check`: clean — ruff, ruff-format, **mypy (no issues, 238 files)**, deptry. (ruff auto-fixed
  one import-order nit on first pass.)
- Frontend: **535 vitest passed** + strict `tsc --noEmit` clean.

---

## Owed before merge / next phases

> _Snapshot at slice-completion (2026-06-23). PARTIALLY SUPERSEDED: the Deep-review + Hardening sections
> below resolved the committed tests + the report.py guard; current remaining work lives in the plan's
> "NOT yet built" line. Kept here as the historical state at this point in the journey._

- **Committed tests for the slice** (verified via throwaway scripts + browser, but not yet pinned):
  collector `begin_node` (disk-only line, seq reuse, owner-thread), reader `node.start` skip-arm,
  the tailer (discover/read/batch/snapshot/last-wins), and the frontend overlay pass + dispatch arms.
- **Host seq-reservation wrinkle + host `node.start`** (full A2): unify where a host reserves its seq so
  a host can also show `running`. Gated by the three host-frame pin tests
  (`test_looped_subworkflow_re_descends_distinct_seq_balanced_stack`,
  `test_host_recorded_after_ascend_with_frame_keeps_children_linked`,
  `test_subworkflow_child_id_collision_does_not_corrupt_top_level_status`).
- **Eager-`meta` ripple guards** (now that crashed-before-first-completion runs leave a meta-only file):
  `cli/commands/report.py` (unguarded mtime glob — will pick a meta-only/in-flight file) and the
  analyze-cache "failed run" mislabel.
- **The checkpoint** (real "done" bar): one sub-workflow + one parallel batch end-to-end through the
  overlay (the cases the slice sidesteps; where join correctness on a non-empty `ancestor_path` and the
  batch flipbook actually get exercised).
- **`/api/runs` + replay + the three discovery surfaces (D6)** and the **detail panel**.
- **Pin D1** once the shipped overlay has validated the consumer-derivation contract.
- **Tool-elevation verdict** for the throwaway probe + verify scripts (discard vs. elevate) — record in
  `task-review.md` at task end. The "drive a live run + poll trace + screenshot overlay" loop is a
  strong elevate candidate (no existing skill workflow drives a live run).

## 2026-06-23 — Deep review (4 agents: plan / concurrency / silent-failures / impact)

Ran 4 review agents over the moved plan + the shipped slice. Outcome: **no criticals in the slice's
happy-path correctness; `begin_node` proven thread-safe** (routing-based — workers never reach the
run-scoped collector). Full findings (R1–R8 + suggestions) folded into `implementation-plan.md` →
"Deep-review findings". Highlights:
- **R1 (critical, fix now):** the join pin is BLIND to `node.start` (only checks `kind=="event"`), and
  there's no consumer-side join-miss detection → a `node.start` drift silently never lights. Cheap fixes.
- **R2 (critical):** `discover_live_trace` ignores `run.complete` → a finished run can shadow a live one.
- **R3:** tailer blocks the event loop (needs `asyncio.to_thread`). **R4:** `_read_new` `errors="ignore"`
  loses bytes split across a poll boundary (non-ASCII node ids). **R7:** snapshot `put_nowait` lacks the
  `QueueFull` guard.
- **R5/R6 (plan gaps, Workstream B):** report.py picks in-flight files (real); analyze-cache mislabels
  (cosmetic — **W2 resolved to the milder case**: incomplete → failed bucket, label-only).
- Cross-check win: two reviewers independently confirmed report.py + analyze-cache are the ONLY affected
  trace-dir consumers (no missed consumer), and `node.start`/`LeafData.status?` have no other readers.

## 2026-06-24 — Slice hardening pass (deep-review fixes R1–R5, R7 + owed tests R8)

Landed the cheap shipped-slice fixes the review surfaced, before moving to the checkpoint:
- **R1 (join silent-failure):** extended the join pin `test_runtime_event_refs_join_onto_the_static_graph`
  to cover `node.start` (was event-only — blind to the running-state line); added a dev-only join-miss
  `console.warn` in `GraphView` for run-events whose ref matches no graph node (keyed on the FULL graph,
  so a collapsed-group child isn't a false positive).
- **R2 (discovery):** `discover_live_trace` now PREFERS a live file (no `run.complete`, via a bounded
  tail read `_has_run_complete`) over a newer-by-mtime finished one — a finished run no longer shadows a
  concurrent live one.
- **R3 (loop-blocking I/O):** rewired `RunTailer.run()` — discover + read run via `asyncio.to_thread`;
  parse + state-mutation + broadcast stay ON the loop. Split deliberately to AVOID a new race: putting
  the whole `_poll_once` in a thread would have raced `snapshot()` on the loop. Only `_offset` is
  thread-touched (serialized); `_state`/`_run`/`_buf` are loop-only.
- **R4 (byte loss):** `_consume` now buffers RAW BYTES and decodes only complete lines (was
  `decode(errors="ignore")` on byte-offset reads). Note: the producer is ASCII-only (`json.dumps`
  default `ensure_ascii=True`), so this is defensive robustness, not a live bug — the test documents that
  honestly (`ensure_ascii=False` to construct genuine multibyte input).
- **R5 (eager-meta ripple):** `pflow report` no-arg now prefers the newest COMPLETE trace
  (`_trace_is_complete`), emitting "No completed trace found…" + exit 1 when only in-flight/interrupted
  traces exist. (analyze-cache R6 mislabel deferred — cosmetic, selection is already correct.)
- **R7:** the snapshot `put_nowait` now degrades gracefully (`contextlib.suppress(asyncio.QueueFull)`).

**Owed tests written (R8):** `test_begin_node_emits_disk_only_running_marker_and_reuses_seq` +
`test_parallel_batch_of_subworkflows_streams_without_owner_thread_error` (the routing-based no-lock safety
net — a future refactor routing a worker through `_execute_node` breaks it loudly); `test_run_tailer.py`
(6 tests: prefer-live discovery, batching+last-wins, byte-boundary); 2 report auto-select tests; 22
frontend tests (`status.test.ts` refKey/applyStatus identity-preservation; `runEvents.test.ts` SSE dispatch).

**Integrity note:** the report test-writer agent accidentally `git checkout`'d `report.py` (destroying the
uncommitted R5 edit) and reconstructed it from memory. I verified the result `git diff` is byte-identical
to the intended change (`+30/-2`, the `_trace_is_complete` helper + prefer-complete selection) — clean.

**Gates (all green):** `make test` 8129 passed (8119 baseline + 10 new Python tests, 0 regressions);
`make check` clean (mypy 238); frontend 557 vitest + strict `tsc`. **Browser re-verified** the rewired
tailer end-to-end: `slow` lights blue/running mid-flight (the `to_thread` + prefer-live + byte-buffer
path the unit tests don't exercise).

## Deviations from plan — summary

| Plan said | Shipped | Why |
|---|---|---|
| D1: `event`+`status:running`, last-wins | distinct `node.start` kind, reader-ignored | keeps `event`=completion; back-compat with all readers + the test suite; matches D1's own naming |
| (frontend) seed `status` default in `buildFlow` | `status` optional, `applyStatus` is sole writer | fewer touch points; pending = absent = no styling |
| (tailer) broadcast per-line | batch deltas per poll into one `run-events` | a fast run could exceed the hub's 64/conn queue and silently evict the viewer |
