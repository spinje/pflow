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

## 2026-06-24 — Host node.start investigation (4 parallel subagents, pre-implementation)

Per the user's directive to verify all assumptions/ambiguity before building host node.start. Outcome:
the braindump's "producer one-liner in `descend()`" was INCOMPLETE — host node.start ALSO needs new
FRONTEND work, and the checkpoint is smaller than thought. Four verified findings:

1. **Producer `descend()` flush is SAFE — exact code in hand.** `descend()` is the ONLY production caller,
   run-scoped + owner-thread only (the OLD buffer path never descends). The host completion already reuses
   `frame.seq`, so the host node.start MUST emit with the frame's EXISTING seq (NOT a fresh `_next_seq()`)
   and MUST stay disk-only (NOT appended to `self.events`) — else `nodes_executed` / `tree()==reconstruct`
   break. Add a `stream_to_disk`-gated `_open_stream()` + `_flush_line(..., intern=False)` mirroring
   `begin_node`; hardcode `node_type="WorkflowExecutor"` (not carried on the frame). All 3 host-frame pins
   PASS unchanged (they read in-memory events or `load_trace_file`, which drops `node.start`).
2. **Join target exists + matches — no drift.** A sub-workflow host has a joinable leaf `RFRef`
   (`ancestor_path=[]` top-level, `port=null`); `descend` stamps the same (both exclude the host's own
   frame). The join pin only asserts the CHILD joins today — EXTEND it to assert the HOST node.start joins.
3. **Frontend CANNOT light a group/host today — the real gap.** `applyStatus` bails on `type !== "node"`
   (`focus.ts:28`); `GroupData` has no `status`; `flatIdForRef` searches `graph.nodes` only and the host
   leaf is suppressed (`buildFlow` skips `is_group_host`). So a host node.start lands unclaimed → nothing
   lights. Needs ~5 frontend changes: `GroupData.status`; an `applyStatus` group-branch keyed on
   `hostNode.ref` (only the PRIMARY group lights — mirror `showTitle`); a `GroupNode` `status-${status}`
   class push; a CSS `.group` ring; (optional ChipRail chip).
4. **The checkpoint SHRANK.** A parallel batch of LEAF nodes ALREADY lights its host running today (step
   8.5 `begin_node` has NO batch guard — only sub-WORKFLOW hosts are skipped). And a sub-workflow's leaf
   CHILDREN already light with a non-empty `ancestor_path`. So the riskiest thing (#6 join-drift on a
   non-empty `ancestor_path`) is verifiable NOW with zero new code. Only the HOST GROUP lighting needs new
   work — and it matters most for COLLAPSED sub-workflows. Batch-of-sub-workflows host stays
   pending-until-done (v1 boundary, unchanged).

**Reshaped sequence (verify-the-risk-first — inverts the braindump's "host node.start before checkpoint"):**
- **P1 (no new code):** browser-verify an EXPANDED sub-workflow's children light (non-empty
  `ancestor_path`; watch the join-miss `console.warn`) + a parallel-batch-of-leaves host lights + items
  flipbook. This is the JOIN gate — the one risk that looks identical to "working" when broken.
- **P2:** host-group lighting — the producer `descend()` flush + the ~5 frontend group changes + extend the
  join pin + CSS. Browser-verify a sub-workflow host lights (expanded AND collapsed).
- Then commit the checkpoint.
Justification for the inversion: the investigation showed host-lighting is a bigger FRONTEND chunk, while
the JOIN risk is testable with zero new code — so verify the risk first, build the polish second.

### P1 verified (2026-06-24, real browser via a NEW overlay-status-probe)

Built `scratchpads/task-173-live-overlay/verify/overlay-status-probe.pflow.md` — reads each node's
`status-*` DOM class (reliable where eyeballing a ring colour is NOT; reuses the skill's `open-and-settle`
by absolute path). Strong ELEVATE candidate (no existing tool reads overlay status). Results:
- **Sub-workflow JOIN gate CLEARED.** On the completed `subworkflow-probe` run, `child-slow` (ref
  `(child-slow, [{call-child,null}], null)`) and `child-fast` both lit `status-success` — the
  non-empty-`ancestor_path` join works at the DOM level, not just the wire (the wire was byte-identical:
  producer `node.start` ancestor_path == renderer RFRef). `top` success too. The #1 silent-join-failure
  risk is gone.
- **Live running renders.** On the live `batch-probe` run, the batch host `fanout` showed `status-running`
  MID-FLIGHT — confirming both the cheat-sheet correction (batch LEAF host lights via `begin_node`, no
  batch guard at step 8.5) AND the live snapshot+stream path (not just replay).
- **Host group NOT lit.** `call-child` (the host GROUP, dataId `g0`) carried no status class — exactly the
  P2 gap. → proceeding to P2.

## 2026-06-24 — P2 complete: host node.start + frontend group-lighting (browser-verified)

The host-lighting increment, scoped from the 4-subagent investigation. Shipped:
- **Producer:** `descend()` now flushes a disk-only host `node.start` (reusing the host frame's reserved
  seq) so a sub-workflow host group lights `running` while its body runs. Single-sourced the `node.start`
  wire shape into a new `_emit_node_start` helper shared by `begin_node` (leaves, reserve here) + `descend`
  (hosts, reuse the frame seq) — a deletion-test win (the contract line lives in ONE place). All 3
  host-frame pins + the `tree()==reconstruct` equivalence tests stay green.
- **Join pin:** extended `test_runtime_event_refs_join_onto_the_static_graph` to assert the HOST's
  `node.start` joins the static graph (was child-only) — regression-guards the new behaviour.
- **Frontend (the gap the braindump missed):** `GroupData.status`; an `applyStatus` group-branch keyed on
  the HOST's ref (PRIMARY group only — `showTitle` — so a host backing >1 group lights once); `GroupNode`
  pushes `status-${status}` (collapsed card → `.node.status-*`, expanded region → new `.group.status-*`
  CSS). +4 `status.test.ts` cases (host-group lights, non-primary doesn't, identity preserved, host-ref
  join).
- **Browser-verified (authoritative DOM `status-*` read via the new overlay-status-probe):** the host
  group `call-child` lights `status-running` MID-FLIGHT in BOTH expanded (g0=running, child-slow=running
  inside) and collapsed (g0=running, children hidden — the case that matters most). The trace confirmed
  the producer emits `node.start call-child running []`.

**Gates:** `make test` 8129 (= baseline, 0 regressions); `make check` clean (mypy 238); vitest 561 (557 +
4). Host `node.start` is now COMPLETE for every main-thread node; a parallel/sequential
batch-OF-SUB-WORKFLOWS host + batch ITEMS stay pending-until-done (the v1 boundary — they never descend the
run collector; workers can't touch it).

## 2026-06-24 — Adversarial verification pass (fork specialist) + the one finding it surfaced

Ran a fork verification specialist ("try to BREAK it; trace files + DOM over unit tests; find the last
20%"). It built its own adversarial workflows and drove real CLI/UI. Verdict: **the overlay core is solid**
— the join held under every shape (2-level nesting: producer ancestor_path == renderer RFRef at every
depth; same node_id at two scopes lights independently; loop-leaf flipbook; branching untaken-branch stays
pending), and state transitions all behaved (running→done/failed/degraded/cached; run-reset follows B not
stale A at the SSE-wire level; crash leaves a sane dangling `running`; a bursty 60-node run delivered in 6
batched SSE messages → NO 64-queue eviction; cached node emits no node.start; batch-of-subworkflow
boundary holds). Honestly-unverified (low risk): in-page run-reset *visual*, looped *sub-workflow* host,
genuinely-simultaneous concurrent runs, `status-cached` for an LLM (used a code node), the banner DOM
element.

**The one real finding — `--only` traces shadow the last full run — FIXED + verified.**
`discover_live_trace` matched by `meta.workflow_path` but did NOT exclude `only_node` traces (inconsistent
with `_iter_workflow_traces`, which excludes them). After a `--only` iteration, the overlay followed the
`--only` trace (records only its target) → every other node falsely `pending`, shadowing the user's last
full run (and would clutter D6 history). Fix: `discover_live_trace` now reads `meta` once per candidate
and skips `only_node` traces (mirrors `_iter_workflow_traces`). Verified: unit
(`test_discover_excludes_only_node_traces` — `--only` trace newer by mtime, discovery still returns the
full run) AND end-to-end (real full run + `--only step-b` on a fresh server → overlay shows BOTH nodes
`status-success`, not step-a pending). Decision for D6: `/api/runs` history should LABEL `--only` runs
(not exclude) — distinct from the live overlay, which excludes them.

## 2026-06-24 — D6 plan + 5-agent `/deep-review` (plan mode) → plan revised

Wrote `d6-plan.md` (the run-navigation chunk: `/api/runs` + replay/run-selection + 3 surfaces + ChipRail
chip + detail panel), then ran `/deep-review` (5 specialists: plan-structure, concurrency, silent-failures,
impact-completeness, agent-ux). **Verdict: no Critical foundation error — architecture verified sound** —
but 7 convergent UNDER-SPECIFICATIONS, all confirmed against code, now resolved as decisions `[DR-1..7]` in
`d6-plan.md`:
- **DR-1 (3 agents):** the tailer is cached one-per-`workflow_key` → a pinned replay + an unpinned live
  overlay of one workflow collide. Key the tailer on `(workflow_key, run_id|None)`; pinned resolves
  `run_id→Path` once (to_thread) + never re-discovers; `run-not-found` on a stale `run_id`. The pinned-LIVE
  path is the ONLY way to watch one of N concurrent runs → first-class.
- **DR-2 (4 agents):** `_has_run_complete` is boolean-only (verified) → `final_status` would be silently
  null. Expose RAW facts (`complete`/`final_status`-from-trailer/`live`/`only_node`), no synthesized
  `interrupted` word; `STALE_RUN_S` (60s) heuristic with a documented false-positive window.
- **DR-3 (4 agents):** shared scanner = MECHANISM ONLY (yields raw candidates, no `--only`/`final_status`/
  sort policy — caller-applied); `/api/runs` uses cheap helpers NOT `_iter_workflow_traces` (full-parse
  cost); symmetric `--only` meta-test. `report.py`/`trace_loading.py` stay out (verified).
- **DR-4 (2 agents):** `/api/run-node` must be an allowlist PROJECTION (mirror `_run_event`), drop raw
  `node_type`, map via `node_type_tag()` (verified exists), `ref`=`refKey` string.
- **DR-5 (2 agents):** inline/MCP runs (`ir-hash:` path) included, surfaced by name, doc'd out of
  `?workflow=<file>`.
- **DR-6 (3 agents):** each new fetch owns its catch → degraded render; `/api/runs` non-200 on scan error,
  `[]` only for zero runs; skip unreadable traces.
- **DR-7 (1 agent, verified):** `App.tsx` `?view=runs` wins over `?workflow=`; param-based (no SPA
  catch-all).
User chose my recommended resolutions (pin keyed on `(workflow_key, run_id)`; producer vocabulary;
fold all 7). `d6-plan.md` ends with 6 named manual-test scenarios. → building Phase 1 next.

## 2026-06-24 — D6 Phase 1 FOUNDATION: the shared scanner (built, verified, UNCOMMITTED)

Started Phase 1 per `d6-plan.md`. The delicate shared-scanner refactor (DR-3 — the review's #1 trap) is done
in `src/pflow/ui/run_tailer.py`:
- **`read_run_status(path) -> (complete: bool, final_status: str | None)`** (DR-2) — extends the bool-only
  `_has_run_complete` to ALSO extract `final_status` from the `run.complete` trailer via the same cheap
  64 KB tail read, so `/api/runs` reports a finished run's status WITHOUT a full `load_trace_file` parse.
  `_has_run_complete` is now a thin wrapper over it.
- **`scan_traces(workflow_key=None, debug_dir=None) -> list[TraceCandidate]`** — the ONE mechanism-only
  trace-dir scanner: a raw `TraceCandidate` TypedDict per trace (`path`/`meta`/`complete`/`final_status`/
  `mtime`), newest-first by mtime, with NO `--only`/`final_status`/sort policy (each CALLER filters its
  own). One head-read + one tail-read per file, never a full parse — so the all-runs dashboard stays cheap.
- **`discover_live_trace`** re-pointed at `scan_traces` (applies its `--only`-exclude + prefer-live as
  CALLER policy) — **behavior preserved** (all 7 original tests green).
- Tests: `read_run_status` extraction (success/failed/live=`(False, None)`) + the **DR-3 symmetric `--only`
  meta-test** (`scan_traces` INCLUDES the `--only` run, `discover_live_trace` EXCLUDES it — a future
  policy-collapse fails loudly).

Gates: 9 tailer tests pass (7 + 2 new); ruff + mypy clean. **UNCOMMITTED** (`run_tailer.py` +
`test_run_tailer.py` only — server/bundle untouched). NOT a full `make test` yet (do before committing).
**Next:** `GET /api/runs` on `scan_traces` (label `--only`, non-200 on scan error, `200+[]` for zero runs
per DR-5/DR-6) → the `&run=` pin (DR-1: tailer keyed on `(workflow_key, run_id)`) → the 3 surfaces + the
ChipRail chip → the `/api/run-node` detail panel (DR-4 projection).

## 2026-06-24 — D6 Phase 1 + Phase 2: `/api/runs` data layer + the `&run=` pin (built, browser-verified)

> Baseline re-captured at HEAD `01721ca3` (fresh context, trust-nothing): `make test` **8132**,
> `make check` clean (mypy 238), vitest **561**. The diff target for this chunk.

Built Phase 1 (`/api/runs`) and Phase 2 (the `&run=` pin) **together** (user decision — they're coupled:
the pin is the concurrent-run fix and the biggest structural change, and the dashboard will invite clicking
into concurrent runs). User also chose "the pin IS the concurrency fix — no interim flicker hack."

**Phase 1 — `GET /api/runs` (server):**
- `runs()` handler (sync → threadpool; touches no hub state, so the async-handler invariant doesn't apply
  and the blocking trace-dir scan never stalls the loop). Bare → all runs; `?workflow=X` → that workflow's
  history (resolved via `_workflow_key`, matched on `meta.workflow_path` through the committed `scan_traces`).
- `_run_entry` projects each `TraceCandidate` → `{run_id, workflow_name, workflow_path, start_time, complete,
  final_status, live, only_node, trace_file}`. RAW facts per DR-2; `live` is the one derived hint
  (`not complete and now-mtime < _STALE_RUN_S=60`). `--only` runs LABELLED not excluded (DR-3 — that's the
  live overlay's policy, in `discover_live_trace`, NOT history's).
- **DR-6 softening (flagged honestly):** `scan_traces` is shared with the live tailer and stays
  non-throwing, so `/api/runs` returns `200+[]` for a hard total-scan failure too (not non-200). The
  dominant DR-6 case — one unreadable trace among many — IS handled (per-file skip). Documented in the
  handler docstring. (The user accepted this trade when I surfaced it.)

**Phase 2 — the `&run=` pin (server + tailer, DR-1):**
- Tailers re-keyed `dict[str, …]` → `dict[tuple[str, str|None], …]`. `_Conn` gains `run_id`. Added
  `windows_for_run` (ref-count a run-scoped tailer) and **`broadcast_run`** (deliver run-events ONLY to
  Viewers of that exact `(workflow_key, run_id)`). The collision DR-1 fixes: a pinned replay and the
  unpinned live overlay of ONE workflow now get SEPARATE tailers AND separate delivery — they never
  cross-feed. Point's `broadcast` stays workflow-scoped (applies to every Viewer regardless of run).
- `ensure_tailer`/`release_tailer` keyed on `(workflow_key, run_id)`; the tailer's broadcast callback is
  bound to its `run_id` (`lambda k, msg: self.broadcast_run(k, run_id, msg)`).
- `RunTailer` gains `run_id`. `run()` branches ONCE: **pinned** → `_resolve_pinned` (match
  `meta.execution_id` over `scan_traces`, NO `--only` exclude — pinning a labelled `--only` run is an
  explicit choice) resolves the file ONCE, then tails it forever (never re-discovers → a new live run can't
  yank it); a stale id → broadcast `run-not-found` and RETURN. **Unpinned** → today's follow-newest.
- `events()` reads `&run=`; threads `run_id` through register/ensure/release.

**Frontend (minimal Phase-2 wiring; the run-SELECTION UI is Phase 3):**
- `events.ts`: `subscribe(workflow, handlers, runId?)` appends `&run=` when set; new `runNotFound` handler +
  `run-not-found` dispatch arm.
- `GraphView`: reads `?run=` at mount, passes to `subscribe`; `runMissing` state → a "Run not found" banner;
  cleared on snapshot/reset.

**Tests (committed):** +2 tailer (`_resolve_pinned` matches execution_id incl. an `--only` candidate;
`run-not-found` broadcasts + the run() loop terminates), +4 `/api/runs` endpoint (raw facts incl. live;
`?workflow=` filters + LABELS `--only`; empty-dir→`200 []`; unknown name→404), +1 hub `broadcast_run`
scoping (pinned vs unpinned never cross-feed; Point reaches both), +3 frontend (`run-not-found` arm, `&run=`
passthrough, no-runId omits it).

**Gates (all green):** `make test` **8139** (8132 + 7 Python, 0 regressions); `make check` clean (mypy 238,
ruff-format reformatted my long test lines once); vitest **564** (561 + 3); strict `tsc` clean.

**Browser/real-server verification (the mandatory step — driven against a freshly rebuilt bundle + a
restarted :8765 server):**
- `/api/runs` over REAL engine runs: two finished `runs-probe` runs list newest-first with correct facts;
  `?workflow=` filters to them; a mid-flight `slow-runs-probe` run reads `complete=False, final_status=null,
  live=True`; an `--only second` run is PRESENT + LABELLED (`only_node="second"`).
- The pin at the SSE wire: `&run=<good>` → `connected → run-snapshot{} → run-events{first,second,third:
  success} → run-complete:success`; `&run=<bogus>` → `connected → run-snapshot{} → run-not-found`.
- **DOM (overlay-status-probe):** pinning a finished run lit `first/second/third` all `status-success` in a
  real browser — the `&run=` pin replays the RIGHT run end-to-end.
- **Screenshot:** `&run=ghost` → the "Run not found — it may have been cleared from ~/.pflow/debug" banner,
  nodes NOT falsely lit (empty status map). (`/tmp/pflow-shots/runs-probe-ghost-run-id-*.png`.)

**Known minor (v1-acceptable, documented):** a pinned FINISHED run's FIRST snapshot is empty (the tailer
task hasn't read the file at the subscribe instant) → nodes light via `run-events` deltas ~`_POLL_S` (0.25s)
later — a sub-second flash of unstyled→success on open. Same catch-up the unpinned first-viewer already uses;
not worth coupling subscribe to the poll cadence to remove.

**Deviation from `d6-plan.md` (minor):** none structural. DR-6's "non-200 on a hard scan error" softened to
`200+[]` (above) to keep the shared scanner non-throwing for the tailer.

**Next (Phase 3+):** the 3 frontend surfaces (catalog running-badge → per-workflow history dropdown →
`?view=runs` global dashboard, each its own browser-verify + own fetch catch per DR-6) → Phase 4 ChipRail
status chip → Phase 5 `/api/run-node` detail panel (DR-4 allowlist projection) → pin D1 → tool-elevation
verdict + `task-review.md`.

### Deep-review of the Phase 1+2 diff (6 agents) + fixes — all applied, re-verified

User gated the commit on a `/deep-review` first. Ran 6 specialists (concurrency, silent-failures, impact,
agent-UX, test-fidelity, simplicity) over the uncommitted diff. **1 Critical + 2 Warnings + 3 Suggestions,
all confirmed against the code; node_type-leak check PASSED (both projections are literal allowlists);
impact found ZERO missed consumers.** Fixed all six (user chose "all"):

- **🔴 Critical (concurrency + silent-failures, independently) — dead pinned tailer reused → silent blank
  canvas.** `ensure_tailer` reused a `_tailers` entry by presence; a pinned `run-not-found` tailer returns
  (task done) but its entry lingers until the last viewer leaves. A SECOND viewer — or a single tab
  RECONNECTING within the ~15s keepalive-linger window (the dropped conn lingers in `_conns` until its next
  failed write, so `release_tailer` hasn't fired) — reused the dead tailer → empty snapshot, never
  `run-not-found` → the exact all-pending blank canvas the message prevents. **Fix:** `ensure_tailer` treats
  a DONE task as absent (`entry is not None and not entry[1].done()`) and starts fresh — re-resolves +
  re-broadcasts; self-heals any dead-task path. + regression test `test_ensure_tailer_replaces_a_terminated_tailer`.
- **🟡 Warning (agent-UX) — `run-not-found` banner misattributed cause.** It named only "cleared from
  ~/.pflow/debug"; the same path fires for a wrong/typo'd `run_id`. **Fix:** banner now echoes the `runId`
  (already in scope), names BOTH causes, and the recovery ("Remove `?run=` to follow the newest run").
  Browser-screenshot-verified.
- **🟡 Warning (test-fidelity) — the `broadcast_run` test asserted queue SIZES, not contents** → a
  transposed-`run_id` cross-feed would pass. **Fix:** drains each queue, asserts message TYPES per conn
  (pinned = `[run-events, clear]`, unpinned = `[run-reset, clear]`).
- **🟢 Simplicity — `broadcast_run` duplicated `broadcast`'s eviction loop + re-inlined `windows_for_run`.**
  **Fix:** extracted `_Hub._send_or_evict` (the one eviction-policy home); `broadcast`/`broadcast_run` now
  both reuse it over their respective `windows_for*`.
- **🟢 Impact — `/api/runs` absent from the `ui/CLAUDE.md` HTTP-contract list.** **Fix:** added the entry.
- **🟢 Test-fidelity — fixture drift.** **Fix:** both `_write_trace` helpers now comment that their consumed
  keys mirror the producer + the join keys are pinned by `test_emit_time_trace.py` (pitfall #19).

**Verified clean (no findings), per the agents:** node_type leakage (allowlists), `/api/runs` field
nullability, the live/finished snapshot→delta catch-up, `broadcast_run` eviction-during-iteration (fresh
list), closure capture, the thread/loop split, `release_tailer` ref-counting, the sync `runs()` handler, the
DR-6 `200+[]` softening (sound + documented), frontend `runId` stability.

### Liveness exactness — basic flock built NOW; hang backstop → GH #538

User pushed on the `STALE_RUN_S=60s` heuristic: a real LLM node (120s default timeout) or claude-code node
(300s) running >60s false-reads "interrupted" / loses its catalog badge. Reasoned it through: a pure
"incomplete = running" reframe just flips the failure (a crashed run blinks blue forever). Conclusion
(by the simplicity-of-final-code principle): the right fix is an **`flock` advisory lock on the trace
handle** (kernel = exact source of truth for death; deletes `STALE_RUN_S` + all the per-node-timeout/retry
bookkeeping a deadline approach would need). Verified the producer holds the trace handle open for the whole
run (so the lock rides it), every node type is bounded (no unbounded node), and `Node._exec` retries are
invisible in the trace (silent during backoff).

**Decision (user, after weighing drawbacks):** build the **basic flock NOW** (this branch) — exact
death-detection replacing `STALE_RUN_S`. The **only** deferred piece is the **hang-protection staleness
backstop** for the rare *alive-but-stuck* process (`flock` detects death, not hang) → re-scoped into **GH
#538**. Drawbacks carried into the build: Unix-only (`fcntl`) + Windows fallback, local-FS assumption,
`flock` (per-handle) NOT `lockf` (per-process footgun), probe on `asyncio.to_thread`, a frontend "stopped"
state for the exact death signal.

**Gates after fixes (all green):** `make test` **8140** (8132 + 8 Python: +2 tailer pin, +5 runs/broadcast,
+1 dead-tailer regression); `make check` clean (mypy 238); vitest **564** (561 + 3); strict `tsc`. **Browser
re-verified** (rebuilt bundle + restarted server): pinned GOOD run still lights `first/second/third`
`status-success` (the `ensure_tailer` fix didn't regress the happy path); the new run-not-found banner
renders with the id + both causes + recovery (`/tmp/pflow-shots/runs-probe-typo-xyz-123-*.png`).

## 2026-06-24 — D6 Phase 3a+3b: catalog running-badge + run selector (browser-verified)

The first two run-discovery surfaces, on the `/api/runs` data layer (Phase 1+2). Frontend-only — no Python
touched, so the Python gates hold.

- **3a — catalog "● running" badge** (`CatalogView`): a second `/api/runs` fetch (its OWN catch, DR-6 — a
  failure shows no badge, never blanks the catalog), filtered to `live`, matched by absolute
  `workflow_path` → a pulsing dot on running workflows.
- **3b — run selector** (`RunSelector`, in the Rail's reserved top slot): lists this workflow's runs
  (`/api/runs?workflow=X`) with status marks composed from the RAW facts (running ● / success ✓ / failed ✗ /
  `--only` ⊘). Picking a finished run **pins** it (`&run=`, the Phase-2 mechanism) → the overlay swaps
  **in place** (no reload, camera/focus kept); "● Live — follow newest" un-pins. `runId` moved from a
  mount-time `useMemo` to `useState`, written to the URL via `writeViewParams({run})`; the SSE effect
  re-subscribes on `runId` change (the dep was already wired in Phase 2).
- **Plumbing:** `RunInfo` type; `fetchRuns` in `client.ts`; `writeViewParams` gained `run`; `Rail` gained an
  opaque `runControl` top slot; `_send_or_evict` (Phase-1+2 review) untouched.
- **Tests:** `RunSelector.test.tsx` (run-mark mapping, fetch-on-open, pin/unpin callbacks, empty list) +
  `CatalogView.test.tsx` (badge matched-by-path, DR-6 no-badge-on-failure). vitest **570** (564 + 6).
- **Browser-verified:** catalog badge live (`/shoot` — `zzz-badge-probe ● running`); Rail shows the run
  control top-slot; the dropdown lists runs with correct marks (skill `click` workflow). Pin end-state was
  DOM-verified in Phase 2; the in-place dropdown→swap is covered by composition (RunSelector `onSelect` unit
  test + the Phase-2 `&run=` browser proof).

Gates: vitest **570** + strict `tsc` clean; Python unchanged (`make test` 8140 / `make check` clean hold).

**Next:** basic **flock** liveness (this branch — see the liveness section above; hang backstop → #538), then
Phase 3c global dashboard, Phase 4 ChipRail chip, Phase 5 detail panel.

## 2026-06-24 — Basic flock liveness: EXACT death-detection (built + browser-verified)

Replaced the `STALE_RUN_S=60s` mtime heuristic with an **advisory lock** the producer holds on its trace
handle for the run's lifetime; the server probes it. The kernel releases the lock on ANY process exit, so
"lock held" == alive — exact, no time threshold. (Hang backstop deferred → #538.)

- **Producer** (`workflow_trace.py`): `_lock_trace_handle` takes `flock(LOCK_EX|LOCK_NB)` on the open
  streaming handle in `_open_stream`; released automatically by `_close_stream` / process exit. Behind
  `try: import fcntl` + `contextlib.suppress(Exception)` (best-effort, same posture as `_close_stream` — a
  wrapped/non-fd handle like the I/O-fault test's stub, or no fcntl on Windows, degrades silently; NEVER
  affects the run). [Fixed a regression here: my first version let the stub's missing `.fileno()`
  AttributeError propagate → 2 producer I/O-fault tests failed; the broad suppress fixes it.]
- **Consumer** (`run_tailer.py`): `is_trace_locked(path) -> bool | None` (True=alive / False=free /
  None=no-fcntl), a SEPARATE-fd `LOCK_NB` probe that releases immediately if it acquires. The tailer's
  `_check_stopped` (extracted to keep `run()` under the C901 complexity cap) broadcasts **`run-stopped`
  ONCE** when an incomplete run's lock is free → the canvas flips dangling `running` nodes to `stopped`.
- **Server** (`server.py`): deleted `_STALE_RUN_S`; `_run_is_live` = `not complete and is_trace_locked is
  not False` (Unix exact; no-fcntl → incomplete=live fallback). `/api/runs` `live` is now EXACT.
- **Frontend**: `NodeStatus += "stopped"`; `events.ts` `run-stopped` arm; `GraphView` flips `running`→
  `stopped` + a "Run stopped" banner (reset on snapshot/reset/select); `RunSelector` runMark shows
  `stopped` (was the guessed "interrupted") for a not-live unfinished run; amber `.status-stopped` CSS.
- **Tests:** `is_trace_locked` primitive (held vs free, in-process — flock conflicts across
  open-descriptions), the producer holds the lock while streaming + frees on finalize, the tailer
  broadcasts `run-stopped` on incomplete+unlocked, `/api/runs` exact-liveness (finished / leftover-crashed
  / held-lock → False/False/True), `run-stopped` SSE dispatch, `RunSelector` stopped-mark. (`_unix_only`
  skip for the fcntl tests.)

**Gates (all green):** `make test` **8143** (8140 + 3 Python); `make check` clean (mypy 238); vitest **571**
(+1); strict `tsc`.

**Browser-verified (real runs, fresh bundle + restarted server):**
- **False-interrupted FIXED:** a single `sleep 90` node, silent for **67s** with zero trace appends, still
  read `live=True` in `/api/runs` (under the old heuristic it false-read "interrupted" at 60s).
- **Exact death:** started a fast→slow workflow, `kill -9` mid-slow-node → the overlay-status-probe read
  `quick=status-success, slow=status-stopped`; the screenshot shows the amber `slow` node + the "Run
  stopped — the process exited before finishing." banner (no forever-blue-blink). `/api/runs` for the
  killed run read `(complete=False, live=False)`.

The interim STALE_RUN_S note above is now superseded — flock is the shipped mechanism; only the hang
backstop remains (#538, re-scoped).

### Deep-review of the flock diff (3 specialists + an adversarial fork) + fixes

User gated the commit on a review (3 most-relevant agents) + a fork that drives the real system. Outcome: the
core flock bet was verified SOLID (OFD semantics, non-blocking probe, the open()→flock() startup window
closed because discovery keys on the `meta` line written AFTER the lock, concurrent runs lock distinct
files); 1 Critical + 1 Warning confirmed and FIXED; 1 Warning disputed.

- **🔴 Critical (concurrency, reproduced) — false `run-stopped` on a CLEAN finish.** Each poll reads bytes
  (to_thread) → consumes (sets `self._run` only if `run.complete` was in those bytes) → probes the lock
  (to_thread). A run that calls `finalize()` (flush `run.complete` → close → release lock) in the read→probe
  gap is seen as free-lock + `self._run is None` → a false `run-stopped` on a SUCCESSFUL run (+ the frontend
  never cleared `runStopped` on completion → contradictory state). The reviewer reproduced the exact
  interleaving; the fork didn't trigger it in a handful of runs (narrow window) — deterministic analysis
  caught what the dynamic sweep missed. **Fix:** `_check_stopped`, on a free-lock reading, re-confirms via
  `read_run_status` — `finalize()` flushes the trailer BEFORE releasing the lock, so a free lock guarantees
  the trailer is on disk if it finished; only a STILL-incomplete tail = a real crash. + frontend
  `runComplete` clears `runStopped` (defensive). + regression test (`_check_stopped` on an unlocked-COMPLETE
  trace → no broadcast). Browser-re-verified: a genuinely-killed run STILL flips to `stopped`.
- **🟡 Warning 1 (silent-failures, confirmed) — late subscriber blue-forever.** `run-stopped` is one-shot
  (latched); a viewer subscribing AFTER it (reload / 2nd tab reusing the tailer) got a `snapshot()` lacking
  the stopped state → nodes read `running` forever. **Fix:** `snapshot()` carries `"stopped": self._stopped`;
  `events.ts` threads it; `GraphView.runSnapshot` flips dangling `running`→`stopped`. + tests.
- **⚪ Warning 2 (no-flock FS false-stopped) — DISPUTED.** The reviewer traced the producer (lock silently not
  taken) but not the consumer probe: `is_trace_locked` does `except OSError: return True`, so on an
  unsupported-`flock` FS the probe ALSO errors → returns True (alive) → safe always-alive degrade (same class
  as Windows), NOT false-stopped. No code change; the `_check_stopped` docstring now notes a free lock can
  also mean streaming-disabled-by-I/O-fault (a rare degraded path where the trace stopped growing anyway).
- **✅ Test-fidelity: clean** — each new test mutation-verified discriminating; notably
  `test_lists_runs_with_exact_liveness` provably FAILS under the old mtime heuristic (pins the new behavior).
  **Process incident:** the test-fidelity agent accidentally `git checkout`'d run_tailer.py + workflow_trace.py
  (the 2nd such agent incident this task) and reconstructed them; I independently verified the on-disk code
  matches my intended state (the `_check_stopped` extraction, the broad-suppress, `is_trace_locked` OSError→True)
  + the file set + green gates — faithful, no loss.
- **✅ Fork (adversarial, real system): all 9 scenarios PASS** — live-stays-running, clean-finish-no-stop,
  kill→stopped (only running flips), concurrency isolation, pin finished-vs-killed, meta-only crash,
  switch-after-stopped, broadcast-once. Honest gaps: the hang case (#538) + Windows/NFS (not testable on
  local Unix).

**Gates after fixes (all green):** `make test` **8145** (+2 Python: clean-finish race guard + snapshot-stopped);
`make check` clean (mypy 238); vitest **572** (+1); strict `tsc`. Browser-re-verified the killed-run→stopped
path under the new confirming-read.

## 2026-06-24 — UI polish: corner status BADGES replace the border ring (+ chip-rail shift)

The first of the user's UI-polish items (the overlay's *visual* status treatment). The user found
the **border ring confusing** — a success-green border on a node read as "is this node green by
identity or by status?" (acute for a non-green kind: an HTTP node, blue by kind, turned green-bordered
on success). They asked for **n8n-style corner badges** instead (ref images: a red `!` error badge; a
spinning-arrows running marker; a checkmark for done).

### Decisions (with the user, via AskUserQuestion + an HTML prototype)
- **Badge-only — drop ALL status border rings.** The corner badge is the single per-node status
  surface. (Chosen over "badge + keep a subtle running pulse" and "badge + faint rings".)
- **Glyphs:** running = two spinning arrows (CSS-rotated); success = green check; failed = red `!`
  (the Image #1 ref); stopped = amber stop-square; cached = grey check; pending = no badge.
- **Relate-to-existing-badges plan (the user explicitly asked "how do these relate to the current
  badges?").** Enumerated the 5 existing surfaces (ChipRail chips; inline `.badge` pills; the status
  rings; the run-banner; the catalog running-dot). The coherence call: the corner badge **supersedes
  the ChipRail's reserved status-chip slot** (the formerly-planned Phase 4 "ChipRail status chip" is
  **DROPPED** — the corner badge solves the same expanded-region-visibility problem). Net: **three
  distinct node surfaces** now — corner StatusBadge (live run-status) · ChipRail (static behavior
  modifiers + the one count-expander button) · inline `.badge` pills (static structural markers).
  Updated the 4 "reserved for status" docs (`ChipRail.tsx`, the `index.css` rail comment,
  `components/CLAUDE.md`, `web/CLAUDE.md`).
- **Prototype-before-code:** built a standalone HTML mockup (`scratchpads/.../badge-mockup/index.html`)
  of all states + the two glyph picks, rendered it via the `shoot` skill on a `file://` URL, and the
  user picked running-A (spinning arrows) + cached-A (grey check) from it before any real code. (Strong
  tool-elevation candidate: "prototype a restyle as static HTML → shoot → user picks" — record in
  `task-review.md`.)

### Chip-rail shift (a follow-up the user spotted)
When a corner badge overhangs the top-right, the rail's rightmost element (a `×3` batch chip, or a
group's count-expander) tucked under it (badge on top → clipped). **Fix:** `ChipRail` gains a `shifted`
prop (`.chip-rail.shifted { right: 22px }`, ~9px clearance), passed `shifted={!!status}` from
`WorkflowNode`/`GroupNode` — so chips shift left ONLY when a badge is present; a badge-less node keeps
its chips at the corner.

### Files
- **NEW** `web/src/components/nodes/StatusBadge.tsx` (+ `.test.tsx`) — the corner overlay; inline SVG
  glyphs, `color:#fff`, per-status bg in CSS; renders nothing for pending. Memo-free (trivial child of
  the memo'd node).
- `WorkflowNode.tsx` / `GroupNode.tsx` — render `<StatusBadge status={status} />` on the node/group
  root; **removed the now-dead `status-${status}` class push** (rings gone).
- `index.css` — deleted all `.node/.group.status-*` outline rings + the `pflow-run-pulse` keyframe;
  added `.status-badge` (corner, halo `#0d0d0d` literal — `var(--bg)` is chrome-scoped) + per-status
  bg + `pflow-badge-spin`; added `.chip-rail.shifted`.
- `ChipRail.tsx` — `shifted` prop. Docs: `ChipRail.tsx` / `components/CLAUDE.md` / `web/CLAUDE.md` /
  the `index.css` rail comment all updated (status slot retired → corner badge).
- **Frontend-only — NO Python touched** (`make test` 8145 / `make check` hold).

### Verification (real browser, DOM-confirmed via the overlay-status-probe + screenshots)
- **running** — blue spinning-arrows badge on a leaf (`slow`) AND a sub-workflow host group
  (`call-child`); others pending/no-badge. DOM: `["status-badge","status-running"]`.
- **success** — green check on every node + "Run success" banner.
- **failed** — red `!` (matches Image #1) on `boom` + "Run failed · 1 failed" banner.
- **ring removed** — proven against the BUILT bundle CSS (no `.node.status-*` outline rule); the green
  on shell cards is the shell **kind color `#7ee787`** (identity), NOT status.
- **host group** badge (expanded region) + **child join** via non-empty `ancestor_path`
  (`child-slow` lit inside the host).
- **coexistence** — the running badge sits beside the host's ChipRail count-expander with no overlap.
- **chip shift** — `fanout`'s `×3` chip clears the success badge with a clean gap (the Image #4 fix).
- **Honestly NOT separately browser-shot** (same `StatusBadge` code path; unit-tested; only color/glyph
  or mount-identical differ): `stopped` (amber) + `cached` (grey) badges, and the *collapsed* host card.

### Gates
vitest **572 → 579** (+7: 6 `StatusBadge` + 1 chip-shift), zero regressions; strict `tsc` + `vite build`
clean. Python untouched.

### Status / artifacts
**UNCOMMITTED** (awaiting the user's go). Throwaway artifacts (gitignored): `badge-mockup/index.html`,
`verify/fail-badge-probe.pflow.md` — elevate-or-discard verdict at task end. The remaining D6 phases
(3c global dashboard → Phase 5 detail panel → pin D1) are unchanged; Phase 4 (ChipRail status chip) is
now **dropped** (absorbed by the corner badge).

## 2026-06-24 — Tailer scan performance: hash-scoped discovery + (mtime,size) cache (committed `1160b808`)

Surfaced by the user spotting two stale `pflow ui` servers at ~8% CPU each. Root cause: the unpinned overlay
tailer calls `discover_live_trace` every 0.25 s, and `scan_traces` globbed + opened + JSON-parsed EVERY
`workflow-trace-*.json` in `~/.pflow/debug` (1251 files / 309 MB locally) to match on the in-file
`meta.workflow_path` — so an idle viewer re-read the whole dir 4×/s. The user pushed past my first instinct
("cache the big scan") to the real question — *why read other workflows' files at all?* — the correct
framing: the producer already encodes `md5(workflow_path)[:8]` in every filename, so discovery never needs to
open unrelated files.

Two fixes, both in `src/pflow/ui/run_tailer.py::scan_traces`:
- **Hash-scoped glob (the real fix).** When `workflow_key` is set (live overlay + per-workflow history),
  glob `workflow-trace-{md5(workflow_key)[:8]}-*.json` not `workflow-trace-*.json`. The overlay now touches
  only THIS workflow's handful, independent of total history. `_same_path` stays as the 8-char-collision
  guard (mirrors `_iter_workflow_traces`). Bare scan (`workflow_key=None`, the dashboard) still lists all —
  its job. **No producer change needed:** `WorkflowManager.get_path` already `.resolve()`s and the file
  branch resolves, so a name- or file-launched run's stored `workflow_path` == the UI's `_workflow_key`
  (both resolved) → hashes match. Verified on REAL data: 8/8 producer-written traces discovered via the exact
  UI path, `key == meta.workflow_path` every time (so no silent-miss for file-backed workflows). Behaviorally
  identical to the old `_same_path` match (both sides are resolved strings ⟹ same-path ⟺ same hash).
- **(mtime,size) read-through cache** (`_SCAN_CACHE`, lock-guarded — scan runs in the Starlette threadpool
  for `/api/runs` AND via `to_thread` for the tailer). `meta` head + a finished trace's tail are immutable, so
  an unchanged file is a cache hit; only the one growing live file is re-read. **Negative verdicts cached
  too** — the empirical cold/warm timing caught that ~1137 of the 1251 are pre-Task-172 single-object traces
  `_read_meta` returns None for; without caching the None they were re-opened every poll (the gap the
  valid-trace fixtures missed — pitfall #19). This keeps the *dashboard's* legitimately-all scan cheap on
  repeat polls.

Empirical (real `~/.pflow/debug`): scoped overlay scan **0.68 ms (16 files)** — no longer scales with dir
size; bare dashboard scan 5.9 ms warm vs ~25 ms cold.

Tests (committed with the change): `test_scan_traces_is_hash_scoped_to_a_workflow` (another workflow's trace
is never opened), `_caches_unchanged_files` / `_rereads_a_grown_file` / `_caches_unreadable_files`. ALL
discovery/runs fixtures now build filenames via the REAL `format_trace_filename` (helper `_tp` in
`test_run_tailer.py`; `test_ui.py` `?workflow=` test too), so a producer↔consumer hash drift fails loudly.
Gates: `make test` **8149** (8145 + 4), `make check` clean (mypy 238), vitest 579 unchanged (no web/ touch).

**Follow-up — the os.scandir hotspot (found by the user observing the fresh server STILL at ~7% CPU).** The
hash-scope narrowed which files are OPENED, but `Path.glob` still `os.scandir`'d the whole 1251-entry dir on
EVERY 0.25 s poll — a `sample` of the running server showed `ScandirIterator_iternext` as the hotspot across
the threadpool (amplified by 4 open tabs' tailers). My isolated timing missed it (a tight-loop scan ran
cache-hot at 0.68 ms; the live server's per-poll cold scandir over 309 MB is far slower). Fix: a
**directory-listing cache** (`_DIR_LIST_CACHE`, keyed on `(dir, pattern)` → `(dir_mtime, paths)`) — the file
LIST changes only on create/delete/rename, which bumps the dir mtime, so a poll over a static dir reuses the
prior glob and costs ONE stat, not a scandir. A finished run changes only file CONTENT (caught by the
per-file `(mtime,size)` cache), so freshness holds. `scan_traces` refactored into `_stat_sorted_listing` +
`_file_facts` helpers (also clears C901). Steady-state scoped poll now **16.6 µs → ~0.007%/core at 4 Hz**
(was ~7%). +1 test (`test_scan_traces_skips_rescandir_when_dir_unchanged`); `make test` **8150**, `make check`
clean. **A running server must be RESTARTED to pick up the new code** (it imports run_tailer.py at startup) —
the user's server 87192 still shows the old ~7% until restarted.

Still owed (separate, deferred): trace **retention/pruning** of `~/.pflow/debug` (the durable bound on the
dashboard's all-scan + the ~1137 dead old-format files); orphaned-`pflow ui`-process cleanup is lifecycle (the
`pkill`/`rm` was sandbox-denied to the agent → user runs it). An OS file-watcher (true zero-idle) is
unnecessary now the overlay scans only a handful.

## 2026-06-24 — UI-polish item: RunSelector re-pick wiped the overlay (user-found, fixed)

The user, walking the live overlay, found: pick a run from the RunSelector, then pick the SAME run again →
the node status markers vanish. **Root cause:** `selectRun` (`GraphView.tsx`) unconditionally cleared
`runStatus` (+ banner/missing/stopped) and relied on the SSE re-subscribe effect (deps `[graphReady,
workflow, runId]`) to repopulate from the new run's snapshot. Re-picking the SAME run leaves `runId`
UNCHANGED → `setRunId(same)` is a React no-op → the effect never re-fires → the markers are wiped with
nothing to refill them (same for re-clicking "Live — follow newest" while already unpinned).

**Fix:** a one-line guard — `if (next === runId) return;` at the top of `selectRun` (+ `runId` added to its
deps). Re-picking the current selection is now a no-op; the menu still closes (`RunSelector.pick` owns that,
independent of `onSelect`); a genuine switch to a different run is unaffected (runId changes → effect re-fires
→ repopulates).

**Regression test** (`GraphView.test.tsx`, the first run-overlay coverage in this file): a faithful jsdom
repro — start pinned to `r1`, light `greet` via a `runEvents` snapshot, re-pick `r1` from the menu, assert
the `run status: success` badge survives. **Mutation-verified:** commenting out the guard makes it fail
(badge gone) — it catches THIS bug, not something incidental.

**Gates:** strict `tsc` clean; vitest **580** (579 + 1); Python untouched (frontend-only). **Process note:**
the user first re-tested against a STALE bundle (I'd changed source but not run `make ui-build` + restarted
`pflow ui`) → "it didn't work"; the fix was correct, it just wasn't deployed. Rebuilt + restarted (also
force-killed two stuck `pflow ui` processes pegging CPU since earlier) → user confirmed working in the browser.
Lesson re-learned: a `web/` source change is invisible until rebuild + server restart.

## 2026-06-24 — `pflow ui` Ctrl+C: server ignored SIGINT, then exited noisily (user-found, fixed)

The user reported the `pflow ui` server **didn't stop on Ctrl+C** (screenshot: repeated `^C` ignored). NOT
the perf change (it's pure `scan_traces` logic, no threads/signals/lifecycle). Root cause is the live overlay
introducing **long-lived SSE connections** (`/api/events`) to a previously GET-only server. Three layered
issues, each surfaced + fixed in order by driving the REAL server (I CAN'T reach localhost HTTP from my tools,
but I CAN start the server, `kill -INT` it, and read its stdout — that's how I verified the no-client case;
the user verified the with-a-tab case):

1. **Hang forever.** `uvicorn.run(...)` had no `timeout_graceful_shutdown`, so on Ctrl+C it waited
   indefinitely for the open SSE streams (held by the browser tab) to drain — they never do. Fix:
   `timeout_graceful_shutdown=2`. User confirmed: server now EXITS (was: hung).
2. **`SystemExit: 130` traceback wall.** uvicorn captures signals while serving and RE-RAISES SIGINT into
   whatever handler was installed before it — pflow's global `main._handle_sigint` (`sys.exit(130)`, meant for
   `pflow run`). So `sys.exit` fired inside the event loop mid-teardown → a SystemExit tangled with the
   tasks uvicorn was force-cancelling (the "During handling of the above exception" cascade). Fix in `ui.py`:
   restore `signal.default_int_handler` before serving so uvicorn owns the whole shutdown, and
   `contextlib.suppress(KeyboardInterrupt)` around it. Verified: no-client shutdown is now a clean exit (only
   `Serving…` then the prompt returns — no traceback). This was MOST of what the user saw.
3. **`Cancel N running task(s)` + a CancelledError per stream.** With (2) gone, the residual noise was uvicorn
   force-cancelling the SSE streams after the 2 s grace (they never close on their own). Fix: close them
   cleanly on shutdown. Switched `ui.py` from `uvicorn.run(...)` to a `uvicorn.Server(uvicorn.Config(...))`
   instance and wrapped its `handle_exit` to call a new `_Hub.shutdown()` FIRST — which marks every `_Conn`
   inactive and wakes its blocked `queue.get` with a `_SHUTDOWN_SENTINEL`, so each SSE generator RETURNS (its
   `finally` unregisters + releases the tailer) instead of being force-cancelled. `events()`'s loop breaks on
   the sentinel. **User confirmed clean shutdown in the real browser.**

Test ripple: the `uvicorn.run` switch to a `Server` instance broke 4 tests that `patch("uvicorn.run")` —
repointed all 8 patch sites to `patch("uvicorn.Server.run")`, and the host/port-wiring assertion now reads
`uvicorn.Config` kwargs (host/port moved from `run(...)` to `Config(...)`). +1 unit test
(`test_hub_shutdown_ends_streams_with_a_sentinel`) pins the mechanism in-process (the part not needing a live
socket). Gates: `make test` **8151** (+2 since the perf commit: hub-shutdown + the earlier scan test),
`make check` clean (mypy 238). Files: `src/pflow/ui/server.py` (`_SHUTDOWN_SENTINEL`, `_Hub.shutdown`,
`events()` sentinel break), `src/pflow/cli/commands/ui.py` (Server + handle_exit wrap + signal restore),
`tests/test_cli/test_ui.py` + `test_ui_commands.py`.

**Honest boundary:** the with-a-tab clean shutdown was verified by the USER (real browser); I verified the
no-client clean exit + the `_Hub.shutdown` mechanism myself. An OS-level edge (a tab mid-`run-events` flush at
the exact shutdown instant) is not separately exercised — low risk, the sentinel + `conn.active=False` make
the generator return regardless.

## 2026-06-25 — Phase 1 (version-aware replay): pre-implementation findings + two plan corrections

New plan: `~/.claude/plans/yes-lets-write-the-fancy-simon.md` (version-DETECTION for replay + catalog
extension). Read it, `task-173.md`, the 2026-06-24 braindump, and this whole log. Then traced every Phase-1
site against `638ac7d0` (clean tree = the plan's stated baseline: `make test` 8151, `make check` mypy 238,
vitest ~580). Confirmed the load-bearing pristine-IR invariant directly: `_prepare_workflow` calls
`_fill_declared_defaults(resolved.ir, params)` which reads `resolved.ir["inputs"]` but writes ONLY to
`params` — so the stamp site (`runner.py:140`, before `compile_workflow`) hashes pristine resolved IR, and
`resolve_workflow(path).ir` on the replay side is the identical resolution. Good.

**Two corrections to the plan's 1B, both code-grounded (NOT deferrals) — see the implementation entry for the
fixes:**

1. **FI-W1 "snapshot-only, no broadcast" is WRONG for the FIRST subscriber → I add a `run-stale` BROADCAST
   (full `run-stopped` mirror).** The plan claims `stale_version` is "latched at `_resolve_pinned` (top of
   `run()`), before any subscriber's `snapshot()`". Traced `events()` (server.py:463-475): `ensure_tailer`
   does `asyncio.create_task(tailer.run())` then `events()` calls `put_nowait(tailer.snapshot())` with **NO
   `await` between** — so the created task CANNOT have run yet (it only runs at the next loop suspension), and
   the first subscriber's snapshot is taken with `_stale_version` still `False`. `_resolve_pinned` latches the
   real value only later, and snapshot-only delivery never re-reaches that already-connected subscriber (no
   delta carries it). Since opening `?run=<id>` makes YOU the first subscriber every time (fresh tailer per
   page load), snapshot-only misses essentially every real replay. Fix = mirror `run-stopped` FULLY: a
   `run-stale` broadcast (reaches the present subscriber, after the resolve, on the loop) PLUS the snapshot
   field (catches late subscribers). This is MORE faithful to "mirror `runStopped`" than the plan's partial
   version — `run-stopped` itself uses exactly this dual delivery. (This is the same first-subscriber timing
   the log's earlier "Warning-1 / snapshot-stopped" fix already discovered for `stopped`.)

2. **The plan's `_switch()` reset of `_stale_version` would CLOBBER the just-latched value → I omit it.** Plan
   says add `self._stale_version = False` to `_switch` "(defensive; pinned never switches)". But pinned
   switches EXACTLY ONCE: `run()` does `pinned = _resolve_pinned()` (latches stale) → `self._switch(pinned)`
   immediately after. Resetting in `_switch` wipes the latch before any broadcast/snapshot reads it. `_switch`
   resets PER-FILE state; `_stale_version` is per-RUN, latched once, never flips — so it must NOT be in
   `_switch`. Unpinned never sets it (stays `False`), so omitting the reset is safe there too.

**Banner-stacking refinement (1C):** replaying a STALE FINISHED run shows BOTH the new "different version"
banner AND the existing run-outcome banner — and all `.run-banner`s are `position:absolute; top:12px;
right:12px`, so a literal "mirror run-stopped" would fully overlap them (only one visible). Wrapping the run
banners in a `.run-banners` flex-column (anchored top-right; each banner becomes a static child) makes
stacking robust for every combination. Minimal + the right structure; documented as a refinement, not a new
feature.

**types.ts note:** the plan's "add `stale_version?` to the run-snapshot message type" is vacuous — there is
no `RunSnapshot` interface; `stopped` is read inline as `message.stopped === true` in events.ts. I thread
`stale_version` the same inline way (no types.ts change for the message). The real signature change is
`RunHandlers.runSnapshot` gaining a `stale: boolean` param.

## 2026-06-25 — Phase 1 SHIPPED (version-aware replay) — built, gated, awaiting browser verify + review

All four sub-parts done. Gates: `make test` **8163** (8151 baseline + 12 new, 0 regressions); `make check`
clean (mypy 238, ruff/ruff-format/deptry); vitest **583** (580 + 3); strict `tsc` clean. NOT yet browser-
verified (the mandatory headline check — stale replay banner + unchanged-id nodes still light) — that's the
next step before commit.

**1A producer** — `workflow_id.py`: factored `canonical_ir_digest(ir)` out of `synthesize_inline_workflow_id`
(now wraps it); fixed the stale "RAW parsed IR" docstring → "RESOLVED IR" (every caller passes `resolved.ir`).
`runner.py`: stamp `content_hash = canonical_ir_digest(resolved.ir)` at the one resolved-IR site (before
compile) + pristine-invariant comment. `workflow_trace.py`: `content_hash` keyword-only ctor arg → `_meta_fields`.
`trace_io.py`: `content_hash` appended to `META_KEYS`.

**1B server** — `run_tailer.py`: `_is_stale(run_hash)` (resolve current file → compare digest; False on None
hash / `ir-hash:` key / resolve-raises); `_resolve_pinned` latches `self._stale_version` as a side effect;
`snapshot()` carries it; new `_start_pinned()` helper (extracted to keep `run()` under C901) broadcasts
`run-stale` after the resolve. **1C frontend** — `events.ts` `runStale` handler + `run-stale` arm + `stale`
threaded through `runSnapshot`; `GraphView` `runStale` state + handler + resets + the banner; `index.css`
`.run-banners` flex stack + `.run-banner.run-stale`. **1D** — `d1-event-schema.md`: `node.start` kind row,
`content_hash` in the meta list, eager-meta caveat de-staled.

**Deviations (all in the pre-impl entry above, code-grounded):** (1) added a `run-stale` BROADCAST — the
plan's snapshot-only FI-W1 misses the first subscriber (its snapshot is taken before the tailer task latches
stale; traced `events()` has no await between `create_task` and `put_nowait(snapshot())`). Full `run-stopped`
mirror. (2) did NOT add `_stale_version` reset to `_switch` — the pinned path calls `_switch` right after the
latch, so resetting would clobber it. (3) wrapped the run banners in a `.run-banners` flex column — a stale
finished replay shows the version banner AND the outcome banner; literal "mirror run-stopped" (both
`absolute; top:12px`) would overlap.

**Key learnings:**
- **The stamp is pristine, but a bare inline dict gets `edges` added by `_validate` before the stamp.** The
  inline producer test first asserted `content_hash == canonical_ir_digest(raw_dict)` and FAILED — probing
  showed `_prepare_workflow` adds inferred top-level `edges` to a bare dict IR in place (a file's parser
  already produces `edges`, so the FILE round-trip matches — and the file producer test passed). Settled the
  inline assertion on the plan's actual wording (`workflow_path == ir-hash:content_hash`, structural). The
  file-backed path — the ONLY one the banner runs in — round-trips cleanly (real-runner round-trip test green).
- **Tests drive the REAL runner for the round-trip** (declared-defaults workflow → run → stamped hash ==
  `resolve_workflow(path).ir` digest → not stale; rename node → stale) and the REAL resolver for the deleted-
  referenced-file catch (`CompilationError` confirmed raised, then swallowed → not stale).

**Honest boundary:** browser verification (stale-replay banner DOM + unchanged-id nodes lighting via the
overlay-status-probe; an unedited replay shows NO banner) is NOT yet done — it's the next step. Phase 2
(catalog extension) not started.

### Browser verification DONE (real headless Chrome, rebuilt bundle + restarted server)

Drove the headline end-to-end (`scratchpads/.../verify/stale-banner-probe.pflow.md` — reads `.run-banner`
class/text + every node's `status-*` class from the settled DOM). Real CLI run of a 2-node shell workflow
stamped `content_hash` into its trace meta (`7bc3c0b3…`, confirmed on disk — producer validated through the
real CLI, not just the harness). Then:
- **UNEDITED pinned replay** → banners `[run-success]` only (NO `run-stale`); both `alpha` + `beta`
  `status-success`. ✓
- **EDITED (renamed `beta`→`gamma`) pinned replay of the OLD run** → banners `[run-stale, run-success]`
  (BOTH render, stacked, no overlap — the `.run-banners` flex deviation validated); `alpha` (unchanged id)
  `status-success`, `gamma` `[]` (the old-`beta` events join no graph node — the "plausible but wrong"
  picture the banner exists to flag). ✓ Screenshot: `/private/tmp/pflow-shots/stale-wf-…-edshot1-…png`.

**This specifically validates deviation #1 (the `run-stale` BROADCAST).** The probe's page is the FIRST
subscriber to a fresh `(wf, run)` tailer, so its snapshot was taken before the latch (stale=False) — only the
broadcast could have delivered the banner. The plan's snapshot-only approach would have shown NOTHING here.
The integration unit tests can't reach (create_task→snapshot→broadcast ordering against a real EventSource)
is now confirmed working.

### Loose end found in review → fixed: the fingerprint was hashing source-LINE provenance (user decision)

Probing the digest surfaced a real discrepancy with the plan's edge-case list: `resolved.ir` carries
source-LOCATION metadata (`_source_line`/`_source_lines`/`_source_files`), so a comment/whitespace edit that
shifts a node's line number flipped the digest → flagged stale, even though the graph is byte-identical. The
plan explicitly claimed "comment/whitespace-only edit → not stale" — so the impl over-warned vs. the plan's
own intent. (Empirically confirmed: a blank line shifted a node `_source_line` 7→8 → different digest.)

Surfaced as a decision (AskUserQuestion); **user chose "hash the logical IR (strip provenance)".** Added
`workflow_content_hash(ir) = canonical_ir_digest(_strip_source_provenance(ir))` to `workflow_id.py` (strips
exactly `{_source_line, _source_lines, _source_files}` recursively — verified that set is the complete
source-location key set, and that `_routes_to_end` is SEMANTIC and correctly preserved). Producer stamp
(`runner.py`) + replay compare (`run_tailer._is_stale`) BOTH switched from `canonical_ir_digest` to it.
`canonical_ir_digest` stays raw for the inline `ir-hash:` id (a dict IR has no provenance → strip is a no-op
→ the inline `content_hash == ir-hash:` digest symmetry still holds). Pure (rebuilds containers, never
mutates `resolved.ir`) — pinned by a no-mutation test.

**Re-verified in the browser** (server restarted for the Python change): a line-shifting whitespace edit →
NO `run-stale` banner (both nodes light); a node rename → still `run-stale` + alpha lights / gamma pending.
Gates: `make test` **8166** (+3 `workflow_content_hash` tests); `make check` clean; vitest 583 / tsc unchanged
(no web/ touch). D1 doc updated to describe `content_hash` as `workflow_content_hash` (logical, provenance
stripped).

**Phase 1 is now complete AND browser-verified.** Phase 2 (catalog extension) not started. A fresh `pflow ui`
on :8765 (my rebuilt bundle + restarted Python) is left running; verify artifacts (`stale-banner-probe`,
`stale-wf`/`ws-wf` scratch workflows) are gitignored throwaways (elevate-or-discard at task end).

Phase 1 COMMITTED `e2db36b2` (clean tree before Phase 2).

## 2026-06-25 — Phase 2: catalog extension (workflows that have run, saved ∪ local) — built + browser-verified

Frontend-only client-side grouping over the already-shipped `/api/runs` (no server/producer change). The
catalog now lists saved workflows PLUS a "Ran but not saved" section for ad-hoc/CLI/agent runs (ADR-0008 —
those aren't in the saved catalog).

- **2A** `CatalogView.tsx`: a pure `groupRuns(runs) → Map<workflow_path, {name, inline, anyLive, latest}>`
  (newest-first → first-seen is latest; `anyLive` ORs liveness). Saved rows keep the running badge (now from
  the group). Ran-but-unsaved = groups whose path isn't a saved path (raw string equality — the shipped
  contract), gated on `items` LOADED so a saved workflow is never briefly mis-listed while the catalog fetch
  is in flight. File-backed rows open by PATH (`onOpen(group.path)`); the per-row indicator is the running
  badge while live, else the latest run's status mark — reusing `runMark` (exported from `RunSelector`, one
  status palette).
- **2B** inline/stdin/MCP runs (`ir-hash:` path) render by `workflow_name`, NON-openable (a static `<div>`,
  "inline run · no file to open"). Deleted/moved file rows ship as-is (clicking → the existing `/api/graph`
  422 banner).
- **2C** de-staled the liveness docs: `types.ts` `RunInfo` ("mtime" → exact `flock`; "null for inline" →
  `ir-hash:`) and the `/api/runs` section of `src/pflow/ui/CLAUDE.md` (`_STALE_RUN_S` deleted → `flock`).
- CSS: `.catalog-subhead`, `.catalog-item-static` (no pointer/hover), `.catalog-item-status` (mark color via
  the shared `.run-mark.run-*` palette).

**Case-fold edge (SF-W3): accepted for v1 + pinned.** Raw `workflow_path` equality now governs row presence;
`Path.resolve()` doesn't case-fold, so a same-file/different-case launch on a case-insensitive FS shows a
duplicate ran-but-unsaved row. A test names that outcome so the seam can't silently graduate; server-side
normalized dedup is the documented escalation.

**Tests (vitest, +6):** `groupRuns` (fold/latest/anyLive/inline); saved∪ran merge (unsaved file row appears,
saved not duplicated); open-by-name vs open-by-path; inline non-openable; running-badge-vs-status-mark; the
case-fold duplicate pin. The 2 existing badge/DR-6 tests still pass (DR-6 extended: a runs-fetch failure also
shows no "Ran but not saved" section). vitest **589** (583 + 6); `tsc` clean; `make check` clean (Python
untouched → `make test` 8166 holds).

**Browser-verified** (rebuilt bundle, catalog DOM read via `catalog-probe.pflow.md`): the "Ran but not saved"
section renders; an inline `ir-hash:` run (`inline-demo`) is a NON-openable `<div>` ("inline run · no file to
open") with a ✓ mark; the scratch ad-hoc file workflow (`stale-wf`) is an OPENABLE button with a ✓ mark; 42
ad-hoc file rows openable. "Click → opens" is covered by composition (the open-by-path unit test + App.tsx's
unchanged `onOpen → ?workflow=` routing). Saved-catalog screenshot confirms no regression to existing rows.

**Honest boundary:** the bare `/api/runs` scans the whole `~/.pflow/debug` (the all-runs dashboard) — many
ad-hoc rows accumulate (42 here); trace retention/pruning is the deferred bound (noted in the perf entry,
unchanged by this work). "Click → opens" for an ad-hoc row not separately browser-driven (composition above).

### Self-review pass → 1 defensive bug fixed (DR-6)

Re-scrutinizing Phase 2: the ran-but-unsaved SORT dereferenced `start_time` unguarded
(`b.latest.start_time.localeCompare(...)`). `RunInfo.start_time` is typed `string`, but a malformed/legacy
trace whose meta lacks it yields `null` at runtime → `.localeCompare` on null throws → the sort throw
propagates to the ErrorBoundary and BLANKS the whole catalog (violating DR-6). Fixed with `?? ""` on both
sides; pinned by a mutation-verified test (TWO unsaved runs so the comparator actually fires, one with a null
start_time — reverting the guard reproduces `TypeError: ...null (reading 'localeCompare')` and fails the test).
+1 empty-state test (zero saved + a run → the "Ran but not saved" section shows, the "No saved workflows yet"
message is suppressed). vitest **591** (+2 since the Phase-2 entry); `tsc` clean.

**Flagged for the user (not defects):** the ran-but-unsaved list is unbounded (one row per distinct ad-hoc
workflow ever run) until trace retention lands — a UX-scope decision (accept per-plan vs cap to recent-N vs
recency filter). Minor/accepted-per-plan: saved rows show only the running badge (no last-run status mark,
unlike unsaved rows); `runMark` is exported from `RunSelector` (its primary home) rather than extracted to a
neutral util for its 2nd consumer.

## 2026-06-25 — Catalog git-bucketing (user-chosen evolution of the flat Phase-2 list)

The user rejected an arbitrary cap/recency-window for the unbounded ad-hoc list and chose a principled
organization: **bucket ran-but-unsaved runs by their git repo**, with a separate "Other" bucket — the way a
developer thinks (by project), and the `/tmp`/inline throwaways fall into "Other" by meaning, not truncation.
This DEVIATES from the plan's flat saved∪ran list (the user evolving the design — their call).

- **Server (`server.py`):** a cached `_git_root(workflow_path)` — pure-Python upward `.exists()` walk for
  `.git` (a FILE in a worktree/submodule, a DIR in a clone — so `.exists()`, not `.is_dir()`), cached by
  PARENT DIRECTORY behind a lock. **Performance (the user's concern):** git is a property of the directory and
  runs cluster by directory, so the walk runs ~once per distinct folder per process lifetime, then it's all
  dict hits — NOT per run, NOT per poll. No `git` subprocess. Rides the existing `/api/runs` scan (no new
  endpoint). `_run_entry` adds a `git_root` field. Restart reflects a new `git init` (standing server
  semantics). Tests: repo-backed → root, no-repo → None, inline → None, and a `.git`-FILE worktree case.
- **Frontend (`CatalogView.tsx`):** `RunInfo.git_root`; pure `bucketUnsaved()` (group by gitRoot, repos
  sorted by recency, "Other" last, basename labels); a collapsible `Section` (Saved · per-repo · Other). All
  sections collapsible; default-collapsed = ONLY "Other" (Saved + repos open). `runMark` reused for the
  per-row status. CSS: `.catalog-section*` + chevron rotate; the dead `.catalog-subhead` removed.
- **Tests rewritten** for the bucketed shape: `groupRuns` (threads gitRoot), `bucketUnsaved` (recency order,
  Other-last, basename), Saved-collapsible, repo-bucket open-by-default, Other-collapsed→expand→inline
  non-openable, open-by-name vs open-by-path, running-badge vs status-mark, the null-start_time guard, the
  case-fold dup. +3 RunInfo fixtures gained `git_root` (RunSelector/GraphView tests).

**Gates:** `make test` **8168** (+2 server git_root); `make check` clean (mypy 238, ruff-format wrapped my
long test lines once); vitest **593**; `tsc` clean.

**Browser-verified on REAL data** (rebuilt bundle + restarted server; `catalog-probe.pflow.md` DOM read +
screenshot): `/api/runs` git_root distribution = 106 runs under the worktree repo (`.git`-FILE case detected
end-to-end), 14 under `~/.pflow`, 12 Other. Catalog rendered: **Saved (9, open) · feat-live-execution-overlay
(29 distinct, open) · .pflow (1, open) · Other (4, COLLAPSED by default)**; expanding Other revealed the
inline `inline-demo` row as a non-openable `<div>`; saved workflows are NOT double-listed in repo buckets
(counts are distinct-workflows, not runs). Screenshot confirms the collapsible "SAVED" header (chevron +
count). A fresh `pflow ui` on :8765 (my rebuilt bundle + git_root server) is left running.

## 2026-06-25 — Per-node "no recorded state" badge in a stale replay (user-requested)

Reviewing Tab 3, the user asked: in a stale replay, the renamed/new node (`summarize`) sits blank (reads as
pending) — show a DISTINCT badge so the mismatch is located on the canvas. Built it, frontend-only.

**Honest semantics (agreed with the user):** the badge means "the pinned run recorded NO state for this
node" — NOT "this node is the one that changed." We deliberately don't store the old graph (detection, not
old-graph rendering), so we can't single out the renamed node; "no recorded state" is the truthful claim, and
it ALSO covers untaken conditional branches in that version. The user accepted that. Glyph: a dashed `—`
(their pick), muted/hollow grey badge so it never reads as a real status.

**Gate (the user interrogated this precisely): `runStale && runBanner !== null`** — both already in GraphView
state, no new server signal. `runStale` is only ever set in the pinned path (implies replay); `runBanner`
(the `run.complete` trailer) ⟺ "finished, no more events coming". So a still-LIVE pinned-stale run does NOT
mark (a blank node might still run); a crashed/stopped stale run does NOT mark (no trailer → ambiguous). Only
a cleanly-finished stale replay marks.

**Mechanism:** a new consumer-derived `NodeStatus = "unrecorded"`. `applyStatus(nodes, status, markUnmatched)`
— when `markUnmatched`, a joinable node (leaf, or a primary host group) absent from the status map resolves to
`"unrecorded"` instead of blank. The flag threads `GraphView (runStale && runBanner) → useWorkflowGraph view →
applyStatus`; placing the policy IN `applyStatus` (the one place that extracts every node's refKey) sidesteps
the circular dep with `graph`. `StatusBadge` gains the dashed glyph (the `Record<NodeStatus>` forces it);
muted-hollow CSS.

**Tests (+6):** `applyStatus` markUnmatched (gap→unrecorded, real status preserved, off→blank, primary-host
marked / non-primary + hostless untouched); `StatusBadge` renders `unrecorded`; a GraphView integration test
pinning the gate — stale+LIVE → NOT marked, then `run-complete` → the unmatched node flips to `unrecorded`,
the matched one keeps success. vitest **599** (593 + 6); `tsc` clean. Frontend-only (Python 8168 / make check
hold).

**Browser-verified** (rebuilt bundle, `stale-banner-probe` DOM + screenshot on the real `stale-review` replay
— `report` renamed → `summarize`): `fetch`/`transform` `status-success`, **`summarize` `status-unrecorded`**
(the dashed badge), both banners stacked. The user's existing Tab 3 needs a REFRESH to pick up the rebuilt
bundle.

**Deferred (the "precise half", not built — only the badge was approved):** the complementary signal —
recorded nodes that VANISHED from the current graph (`report`) — is a definite mismatch we can name exactly
but can't badge (no node on canvas); it could be surfaced as a count in the stale banner. Today it's only the
dev-console join-miss warn. Offer to the user.

## 2026-06-25 — Badge hover detail (friendly status + duration/cost), user-requested

The user wanted every status badge to show its state info on hover. Key find: the tailer ALREADY emits
`duration_ms` + `cost_usd` per node event (`_run_event`), but the frontend dropped them (the overlay map kept
only the status word). So this was frontend-only: retain the metrics, render a friendly hover label.

- **Data model:** promoted the overlay map `Map<refKey, NodeStatus>` → `Map<refKey, NodeRunState>` (status +
  optional `durationMs`/`costUsd`). `applyStatus` now splits it onto `data.status` (badge glyph/color,
  unchanged) + `data.runDetail` (hover metrics); identity still gated on STATUS (metrics arrive in the same
  terminal event, so they never move without it). One map, one concept — chosen over a parallel detail map
  (simplicity of the final code). GraphView's 3 handlers (snapshot/events/stopped) build NodeRunState.
- **Copy** (`runStatusLabel` in StatusBadge, the badge's `title`; the `aria-label` stays the stable
  "run status: <status>" for a11y + tests): running → "Running…"; success/failed → "Succeeded/Failed · 1.2s"
  (+ " · $0.0034" when cost > 0; sub-second → "Nms"); cached → "Cached — reused a prior result"; stopped →
  "…process exited before this node finished"; unrecorded → "No recorded state — recorded against a different
  version of the workflow". Error TEXT for a failed node is NOT shown (off the overlay wire by design — noted).
- **Presentation: native `title`** (per my recommendation, the user's "go ahead") — ships now, accessible,
  works on the 22px badge; ~1s browser delay is the only downside. A custom styled tooltip is the easy upgrade
  if it feels clunky.
- **Tests (+3):** `applyStatus` threads metrics onto `runDetail`; `runStatusLabel` copy + duration/cost
  formatting + the special-state strings. The `status.test.ts` maps moved to a `statusMap()` helper (bare
  status → NodeRunState). vitest **602** (599 + 3); `tsc` clean. Frontend-only (Python 8168 holds).

**Browser-verified** (rebuilt bundle, badge `title` read off the DOM on the real runs): overlay-review →
`fetch`/`transform`/`report` titles `"Succeeded · 5ms"`/`"Succeeded · 3ms"` (duration; no cost — shell);
stale-review → `summarize` title `"No recorded state — recorded against a different version of the workflow"`.
The user's open Tab 3 needs a REFRESH to pick up the rebuilt bundle.

## 2026-06-25 — SSE multi-tab connection limit → GH #539 (deferred follow-up)

User hit new graph tabs stalling on "loading" with several open at once. Diagnosed (server healthy, 1.9% CPU,
all endpoints <200ms): the live overlay holds ONE persistent SSE (`EventSource` → `/api/events`) per GRAPH
tab, the server is HTTP/1.1, and browsers cap 6 connections/origin — so ~6 open graph tabs exhaust the pool
and new tabs queue behind the held-open streams. Classic SSE-over-HTTP/1.1 limit; catalog tabs don't count
(short-lived fetches). Filed **GH #539** (preferred fix: close-SSE-on-hidden / reopen-on-focus) with a
prominent "do NOT regress" section — the `onerror`-driven trigger-agnostic reconnect + single-flight invariant
(`events.ts`), the "SSE recovery must NOT key on visibilitychange" rule (`hooks/CLAUDE.md`), and the
server tailer ref-counting / dead-pinned-tailer-reuse / keepalive-linger (`server.py`). Not a blocker for the
single-tab common case; no code change this session.

## 2026-06-25 — Verify → 4-agent review → the hover-tooltip bug (user-found) + fix

Fresh-context pass over the staged followups (Phase 2 catalog extension + git-bucketing + the `unrecorded`
badge + badge hover detail). User flow: **verify gates → review with the 4 MOST relevant agents → commit.**

**Gates re-run (this session, all green, = the log's claims):** `make test` **8168**, `make check` clean
(mypy 238, ruff, ruff-format, deptry), vitest **602**, strict `tsc` clean.

**4-agent review of the staged diff (user capped it at the 4 most relevant — NOT the full panel):**
simplicity, silent-failures, impact-completeness, feature-interactions. **Three came back CLEAN**
(no Critical/Warning): simplicity positively confirmed the cross-segment consolidation held (`runMark`
exported not re-derived, `eventState` hoisted, `applyStatus`'s two branches share one `patchFor`);
impact-completeness traced the `NodeStatus → NodeRunState` map value-type flip to its ONE writer
(`applyStatus`) + a fully-enumerated reader set (the 4 SSE handlers + tests), all converted, with `tsc`
mechanically guarding the additive `git_root`/`unrecorded`; silent-failures confirmed both "potential silent
drop" paths are correct (top-level trace `workflow_path` is contractually always a path or `ir-hash:`) and
both `localeCompare` DR-6 guards present.

**The one Critical — `markUnmatched` × batch-of-sub-workflows host — was investigated and DISPROVEN
empirically.** feature-interactions claimed such a host is "absent from the status map in ANY replay" → would
be falsely badged `unrecorded` in a stale completed replay. The premise was wrong: the "never descends the
run collector" v1 boundary denies the host only its `node.start` (RUNNING marker), NOT its terminal
completion `event` (the main thread writes that at step 16 with `frame=None` → fresh seq → a normal event
line). Verified THREE ways: (1) a real LLM-free batch-of-sub-workflows run (`scratchpad/bos/parent.pflow.md`,
a dynamic parallel batch over a doubling child) → the `fanout` host trace line is `kind=event status=success
ancestor_path=[]` (terminal event present; no `node.start`, matching "pending-while-running"); (2) a
`pflow-codebase-searcher` code-trace (engine `_execute_node` step-16 always records the host on the main
thread); (3) the progress log's own wording "pending-until-**done**". So the host's ref IS in a completed
run's status map → `applyStatus.resolve()` hits `status.get(key)` first → never synthesizes `unrecorded`. Not
a defect. (The related batch-BODY-inner-nodes case in an expanded stale replay falls under the
already-user-accepted "no recorded state" semantics — same bucket as untaken branches.) Remaining review
items are pre-existing accepted v1 edges (case-fold row dup; saved-row shows no last-run mark) + a cosmetic
stopped-flip shape nit — none blocking.

**Hover-detail bug (user-found): the badge `title` tooltip never appears → ROOT CAUSE `pointer-events:none`.**
The feature is fully wired (the `title` carries the friendly label WITH duration — DOM-confirmed
`"Succeeded · 16ms"` on a real pinned run), but `.status-badge { pointer-events: none }` (`index.css:582`)
means the badge never RECEIVES hover, so the native `title` tooltip can never fire. The earlier "browser-
verified" only read the `title` ATTRIBUTE off the DOM (present regardless) — it never tested that hovering
SHOWS it. Classic verification-over-a-wrong-assumption (the hover detail was added AFTER the badge CSS; the
pre-existing `pointer-events:none` silently defeated it).
- **Fix (user chose the one-liner over a custom tooltip):** `.status-badge` → `pointer-events: auto` + a
  comment pinning WHY (the tooltip needs hover; a click on the 22px corner badge has no own handler so it
  bubbles to the node → selection unaffected; the corner overhang makes the pan dead-zone negligible).
- **Verified (real browser, rebuilt bundle):** the badge probe now reads `pointerEvents: "auto"` with the
  correct `title`; a node click still opens its panel (`click.pflow.md` → `panel: "gather", ok: true`) → no
  selection regression. The OS-rendered native tooltip itself is NOT headless-screenshot-capturable — that's
  the inherent native-`title` limit the user accepted (a custom styled tooltip is the upgrade if it feels
  clunky). Gates after the CSS change: vitest **602**, `tsc` clean (Python untouched → 8168 / `make check`
  hold).
- **Tool note:** a one-off `badge-hover` DOM probe (reads each `.status-badge`'s `title` + computed
  `pointer-events`) was the decisive check — a stronger elevate candidate alongside the overlay-status-probe
  (record at task end); used and discarded this session.

### Follow-up: replaced the native `title` with a CUSTOM hover chip (user-requested, matches the rail tip)

The user then asked for a CUSTOM tooltip "in the same style as the floating bar" (the rail's `.rail-tip`
"Show source" chip) instead of the bare native `title` — the upgrade the prior note flagged. Built it:
- **`StatusBadge.tsx`:** dropped `title={…}`; render a `<span className="status-badge-tip" aria-hidden>` child
  carrying `runStatusLabel(status, detail)` (status verb + duration/cost). `aria-label` stays the a11y fact.
- **`index.css`:** folded the chrome-chip LOOK into ONE shared selector `.rail-tip, .status-badge-tip` (the
  maintainable home for "the dark hover chip"); each owner positions it (rail = right of icon; badge = right
  of the corner badge). The rail chip is visually unchanged.
- **THE TRAP (caught by a computed-style probe, NOT by eyeballing):** `var(--bg-field)`/`var(--border)` are
  CHROME-SCOPED tokens — UNDEFINED on the React Flow canvas layer where the badge lives. My first version read
  `background: rgba(0,0,0,0)` (TRANSPARENT) on the badge chip vs `rgb(28,28,28)` on the rail. Fix: the shared
  chip uses LITERAL `#1c1c1c` / `rgba(255,255,255,0.08)` (same reason the badge halo is a `#0d0d0d` literal —
  web/CLAUDE.md chrome-palette note); values equal the chrome tokens so the rail is unchanged. (`var(--text)`
  DOES resolve on the canvas → kept for the chip text.)
- **Verified (real browser, rebuilt bundle):** computed-style parity — badge chip `background:
  rgb(28,28,28)`, `border: 1px solid rgba(255,255,255,0.08)` == the `.rail-tip` chip; text `Succeeded · 16ms`;
  default `opacity:0`. A framed screenshot with the chips force-shown (CSS `:hover` isn't scriptable) shows
  the dark rounded chip beside the badge, matching the "Show source" floating-bar look. +1 vitest
  (`StatusBadge.test.tsx`: the chip carries the label, no native `title`, `aria-hidden`). Gates: vitest
  **603**, `tsc` clean (Python untouched → 8168 / `make check` hold).

## 2026-06-26 — Detail panel Phase 1: promote the shared numeric helpers (built, gated; live-wire browser re-check pending)

New plan: `~/.claude/plans/yes-lets-write-the-fancy-simon.md` — the **detail panel** ("This run" node
inspector). Phase 1 only this session (user: build Phase 1, then stop for review). Goal: kill the
report-internals import — make the UI a PEER of `trace_tree`/`llm_usage`, never a consumer of
`trace_report`'s privates — and single-source the cost/token numbers so the report, the live chip, and the
(Phase-2) panel can't drift. Baseline re-captured at HEAD `494b0385` (clean tree): `make test` **8168**,
`make check` clean (mypy 238), vitest 603, `tsc` clean.

**Shipped (4 prod edits + 3 test modules):**
- **`trace_tree.py`** — added module-level `event_cost(event, *, include_cached=False)` + `batch_item_cost(item)`:
  thin wrappers over the existing public `cost_for_event`/`cost_for_batch_item` that encode the
  `source in {trace_partial, unavailable} → None` policy in ONE place (was duplicated in report's two
  privates). `batch_item_cost` keeps the empty `events=()` form (the method walks the passed `item`, not
  `self.events`). Both added to `__all__`; the canonical cost-policy docstring now lives here.
- **`llm_usage.py`** — added public `input_token_total(llm_call) -> (int, int)` (the read-side counterpart of
  `normalize_litellm_usage_tokens`); body = the old `_input_token_total`. Canonical docstring lives here.
- **`trace_report.py`** — the three privates (`_compute_event_cost`, `_compute_batch_item_cost`,
  `_input_token_total`) are now one-line delegations to the promoted functions; **all three names kept**
  (`test_trace_report.py` imports them at lines 22/23/30 — dropping any ImportErrors the whole module). Both
  lazy `from … import TraceTree` inside-function imports deleted → the promoted functions imported at top.
  `metrics.py:189` correctly left alone (run-total sum, different semantics).
- **`run_tailer._run_event`** — hover-chip cost converged onto `event_cost(line)` (was the raw
  `(line.get("llm_call") or {}).get("cost_usd")`). Behavioral change: a CACHED node now reports `0.0` (it
  paid nothing this run) instead of the retained SOURCE-call cost — so the chip agrees with `pflow report` +
  the (Phase-2) panel. node.start/non-LLM → None (unchanged); non-cached priced → its own cost (unchanged).
  `trace_tree` imported at top (stdlib-only → no cycle, cheap; the file's existing lazy imports are for the
  HEAVY resolver, not this).

**Deviations from plan:** none structural. Two micro-decisions, both noted:
1. The delegation docstrings are trimmed to "delegates to X" pointers so the policy has ONE home (the
   promoted function); the canonical multi-line explanation moved to `trace_tree.event_cost` /
   `llm_usage.input_token_total`. Avoids the truth living in two places — a duplication smell the plan
   implied ("one place") but didn't spell out for the docstrings.
2. `batch_item_cost` takes no `include_cached` (the plan's snippet only put it on `event_cost`; no batch
   caller needs the diagnostic mode) — matches the plan's explicit signature line.

**Tests (+13):** `test_trace_tree.py` +6 (event_cost: priced leaf, no-llm→None, unpriced→None, cached→0.0;
batch_item_cost: sums children, none-when-empty); NEW `test_llm_usage.py` +4 (inclusive input,
prompt_tokens fallback, explicit-None→0 coercion, empty); `test_run_tailer.py` +3 (the convergence pin —
cached `_run_event` cost == `event_cost` == 0.0 NOT 0.42; priced == its own cost; node.start == None). The
existing report delegation tests (`_input_token_total` @1077, `_compute_event_cost`/`_compute_batch_item_cost`
@1610–1720) still pass → parity preserved (they now exercise the promoted functions transitively).

**Gates (all green):** `make test` **8181** (8168 + 13, 0 regressions); `make check` clean (mypy 238;
ruff-format collapsed one wrapped call-line once). Frontend untouched → vitest 603 / `tsc` hold.

**Honest boundary:** the live-wire convergence (`_run_event` cost) is unit-proven but NOT yet
browser-re-checked (the plan flags it because it touches the shipped SSE wire). The VISIBLE chip is
unchanged — a cached node's chip label is "Cached — reused a prior result" (never showed a cost), and
non-cached costs are byte-identical — so the risk is minimal, but rebuild + restart + drive-a-cached-run is
the one outstanding Phase-1 verification. Stopping for review per the user's instruction; will drive the
browser check on the go-ahead (or fold it into the Phase-3 end-to-end). Phases 2 (`run_node.py` +
`/api/run-node`) and 3 (the `ThisRunSection` frontend) not started.

## 2026-06-26 — Detail panel Phase 2: `run_node.py` + the `/api/run-node` handler (built, gated, real-HTTP-verified)

The backend for the "This run" section: one read-only GET that resolves ONE node's runtime record off its
trace — the interactive single-node counterpart of `pflow report`. Baseline (post-Phase-1, clean tree):
`make test` 8181, `make check` clean (mypy 238).

**Pre-impl verification (the load-bearing assumption — checked, NOT trusted):** the panel's value-prop is
"realized input, post-`${...}` resolution, not the template". The recording layer's docstring
(`workflow_trace.py:649`) says `node_params` is recorded "BEFORE template resolution" — which would BREAK
the value-prop. Traced it: `engine.py:1116` sets `node.params = resolved_params` BEFORE `record_trace`
(`:1204`), so the recorded `node_params` is POST-resolution; the docstring is stale. Confirmed EMPIRICALLY
with a real CLI run of a templated shell node → `node_params == {"command": "echo \"hello World\""}` (the
`${name}` resolved). The plan's deep-review claim holds. Also confirmed the producer writes ancestor_path
elements as `{node_id, batch_index}` (`workflow_trace.py:777`) — exactly the frontend `AncestorStepRef`, so
the structural ref match replicates `sameRef` (the already-shipped+browser-verified overlay join).

**Shipped:**
- **`src/pflow/ui/run_node.py` (NEW)** — `run_node_detail(workflow_key, run_id, ref) -> dict | None`.
  (1) RESOLVE: pinned → match `meta.execution_id` over `scan_traces` (same as `_resolve_pinned`); unpinned →
  `discover_live_trace` — REUSING run_tailer's discovery, never `RunTailer` internals. (2) READ: RAW
  forward-scan (NEVER `load_trace_file` — it strips the `ancestor_path`/`port` join keys), accumulate the
  blob map, keep the LAST matching `kind=="event"` (NOT `node.start` — terminal-after-start, last-wins =
  loop's latest / dead-end re-flush), tolerate a truncated FINAL line / raise on a malformed earlier one,
  `substitute_refs` at EOF; a surviving `$pflow_blob` sentinel (missing/corrupt blob) → `None`, never
  rendered. Ref match = structural `sameRef` replica (node_id + port + ancestor_path element-wise). (3)
  PROJECT to the `RunNodeDetail` allowlist: `node_type_tag` (NEVER the raw class), `event_cost` (the shared
  Phase-1 policy — cached → 0.0, converged with the chip), `input_token_total` + separate output token,
  `input = node_params(resolved) + llm_prompt/llm_system`, `output = llm_response else node_output`.
- **Secret masking (review-C1 Critical):** a genuinely RECURSIVE key-redactor on BOTH `input` AND `output`,
  descending every nested dict/list (catches `headers.Authorization` + a list-of-dicts `api_key` + an
  `access_token` in node_output), reusing `is_sensitive_parameter`, DROPPING `sanitize_parameters`'s 100-char
  truncation (the panel shows the full realized command/prompt). Residual = a secret inside a STRING leaf
  (Option 1, same as report + on-disk trace).
- **`server.py`** — sync `run_node(request)` handler (threadpool, like `runs()` — touches no hub state) + the
  `Route("/api/run-node", run_node)` before the static catch-all. 400 missing/malformed `ref`, 404
  unresolvable workflow / no matching run+event, 200 `_json(detail)`. Docstring notes the read-exposure/CORS
  tripwire (read-only GET, same class as `/api/graph`). + `ui/CLAUDE.md` HTTP-contract entry.

**Deviations from plan (2, both reasoned):**
1. **`output` mirrors the REPORT's Response-vs-output rule** (`llm_response` headline ELSE `node_output`,
   a single value) rather than the plan's literal "node_output and/or llm_response" combined dict. The plan's
   type is `object | string | null` (a single value) and the report is the established, sensible precedent
   (an LLM node's text is the headline; its `node_output.response` is stripped redundant anyway). Combining
   both would double-show. Simpler + consistent with the shipped renderer; one-line change if product wants
   both.
2. **Added a brief `/api/run-node` entry to `ui/CLAUDE.md`** (not in the plan's Phase-2 file map). It's the
   HTTP-contract index and the Phase-1+2 impact reviewer flagged missing CLAUDE.md entries — closing the doc
   debt at the source rather than accruing it.

**Tests (+19, `tests/test_cli/test_run_node.py`):** 13 `run_node_detail` (pinned resolve + project; unpinned
discover; NESTED-ancestor_path child vs top-level same-name; blob resolve; missing-blob→None; last-wins
re-flush; missing ref/run; start-only stopped→None; the **C1 masking** — nested + list-of-dicts redacted in
BOTH input AND output, long command FULL/untruncated; node_type tagged; LLM tokens/cost/response; cached→0.0)
+ 6 handler (400 missing-workflow / missing-ref / malformed-ref, 404 unknown-workflow / no-event, 200
happy-path). Filenames built via the REAL `format_trace_filename` so the hash-scoped glob actually matches.

**Verification (real, not just green tests):** (a) EMPIRICAL in-process smoke of `run_node_detail` against a
REAL on-disk trace (pinned + unpinned + missing-ref + bogus-run); (b) REAL HTTP `curl` against a running
`pflow ui` on :8799 → `/api/run-node` 200 with the full tagged/resolved `RunNodeDetail`, 400 (missing ref),
404 (unknown workflow), 404 (absent node) — the full uvicorn→Starlette→handler→reader→trace stack. (The
`TestClient` handler tests already exercise the real ASGI app + routes; the curl closes the network layer.)

**Gates (all green):** `make test` **8200** (8181 + 19, 0 regressions); `make check` clean (mypy 239 —
`run_node.py` added); frontend untouched → vitest 603 / `tsc` hold.

**Honest boundary:** Phase 2 is BACKEND-ONLY — there's no UI consuming `/api/run-node` yet (the
`ThisRunSection` is Phase 3), so there's no panel to screenshot. The endpoint is proven by the in-process
smoke + the real-HTTP curl + 19 tests. Phase 3 (the `ThisRunSection` component, `fetchRunNode`,
`RunNodeDetail` wire type, ReadPanel/GraphView wiring + the terminal-only gate, and the click-a-node DOM
browser check) NOT started.

### Self-review pass (adversarial, "any loose ends?") → 1 real bug found + fixed

Re-scrutinized Phases 1+2, distrusting the green tests (most Phase-2 cases rested on SYNTHETIC fixtures —
pitfall #19). Drove the two riskiest cases against REAL traces and read the frontend to confirm a claim:
- **🔴 Real bug — the panel LEAKED `_`-prefixed reserved internal keys.** `run_node_detail`'s `output`/`input`
  returned `node_output`/`node_params` verbatim, so a sub-workflow host's `_pflow_child_workflow_paths` (and
  a code node's `_source_line`/`_source_lines`) reached the agent — violating the display-site convention
  every OTHER agent-facing surface follows (`trace_report` / `node_output_formatter` filter `_`-prefixed
  keys). Confirmed on a REAL sub-workflow trace: `call-child` host output = `['_pflow_child_workflow_paths',
  'child-greet']`. **Fix:** `_public_top_level()` drops top-level `_`-prefixed keys from input + output
  (top-level only, matching the report — a nested user `_id` survives). Re-verified on the real trace: host
  output now `['child-greet']` (the real exposed child output kept, the internal key gone). +1 test.
- **✅ C1 (sub-workflow child) — cleared on REAL data, not just the fixture.** A real `child-greet`
  (`ancestor_path=[{call-child, null}]`) resolves via `run_node_detail`; the real trace's ancestor_path shape
  matches the structural match exactly.
- **✅ C2 (interned blob) — cleared on REAL data.** A real >1 KB shell stdout (interned as a `$pflow_blob`
  line) resolves back to the full 2000-char string.
- **✅ Phase-1 cached-chip "invisible change" claim — CONFIRMED by reading the frontend** (`runStatusLabel`):
  cost shows ONLY for `success`/`failed` with `costUsd > 0`; `cached` → "Cached — reused a prior result" (no
  cost). So the cached→0.0 wire change is genuinely invisible. Not a loose end.
- **`_output` (the plan deviation) re-examined → report-PARITY, not a regression.** `_strip_redundant_llm_trace_fields`
  strips only `prompt`/`system` from `node_output` (NOT `response`), and `llm_response` is set only when
  `node_output["response"]` is a STRING. My `llm_response`-else-`node_output` rule is byte-for-byte the
  report's `_format_node_output` precedence — so a structured node (dict response → no `llm_response`) shows
  its `node_output`, exactly like the report. Parity, by construction.

Gates after the fix: `make test` **8201** (+1), `make check` clean (mypy 239).

### Follow-up round (user reviewed the loose-end list) → 3 addressed

- **Secret-redaction false positive — FIXED + the THREE divergent impls consolidated into one.** The raw
  substring check (`any(sensitive in key_lower)`) redacted innocent names that merely CONTAINED a sensitive
  word (`author`→`auth`, `secretary`→`secret`, `tokens`→`token`). There were also THREE divergent
  sensitivity checks: `is_sensitive_parameter` (substring), `sanitize_parameters`'s OWN inline substring,
  and `rerun_display`'s exact-match. Replaced with ONE word-aware rule in `is_sensitive_parameter`
  (`security_utils.py`): normalize a key to a sentinel-bounded `_word_word_` signature (split on
  snake/kebab/dotted/camelCase) and substring-match the sensitive names' signatures — so `api_key` /
  `X-API-Key` / `apiKey` / `my_api_key` match as WHOLE words while `author`/`secretary`/`tokens` don't.
  `sanitize_parameters` (MCP/error/runner-metadata redaction) + `rerun_display` (was exact-match — now also
  catches delimited variants it missed) + `mask_sensitive_value` (probe cache) + the panel all defer to the
  one rule. Accepted boundary: a delimiter-less `myapikey` is one word (won't match embedded `apikey`) —
  realistic secret params are delimited. Verified every redaction-asserting test in the suite pins only REAL
  secrets (none relied on a substring false positive). NEW `tests/test_core/test_security_utils.py` (+8) pins
  the word-boundary behavior incl. the `author` fix; `core/CLAUDE.md` updated.
- **Empty `&run=` → 404 → fixed.** `?run=` (empty string) hit the pinned path (match execution_id `""` → no
  match → 404) instead of "unpinned / follow newest". Coalesced `request.query_params.get("run") or None` in
  the handler. +1 test. (The real frontend omits the param when unpinned, but the defensive case now reads
  right.)
- **Whole-file read in `_read_matching_event` — kept, made the intent explicit.** Reasoned it through (the
  "top 10% simplest" lens): it's a ONE-SHOT read of one node, finding the LAST match needs a full scan
  anyway, traces are modest, and it matches `load_trace_file`/`generate_report` (every other trace reader
  reads whole-file). A streaming/two-pass reader would ADD complexity for no real benefit at this scale —
  over-engineering. Left as-is + a docstring note so a future agent doesn't "optimize" it into the tailer's
  incremental machinery.
- **Phase-1 live-wire browser re-check — folded into the Phase-3 end-to-end** (per the user) — a real click
  on a cached node will exercise the converged chip + the panel together.

Gates after this round: `make test` **8210** (+9, 0 regressions across ALL the redaction consumers —
diagnostic_render / error_formatter / runner-metadata / rerun_display / settings / execution_cache);
`make check` clean (mypy 239); `security_utils` doctests pass. Remaining noted-not-blocking: an UNPINNED
panel-vs-overlay run-switch has a sub-second inconsistency window (the pinned/common replay path is
race-free); a secret embedded in a free-text string VALUE is uncaught by key-name redaction (Option 1, same
as `pflow report` + the on-disk trace).

## 2026-06-26 — Detail panel Phase 3: the "This run" frontend section (built, gated, BROWSER-verified)

The frontend that consumes `/api/run-node` — the detail panel's "This run" section. Frontend-only (no
Python touched → 8210 / `make check` hold). Baseline: vitest 603, `tsc` clean.

**Shipped (4 prod files + 2 NEW):**
- **`web/src/types.ts`** — `RunNodeDetail` (snake_case WIRE shape: `node_type`/`status`/`duration_ms`/
  `cost_usd`/`tokens{input,output,cache_read}`/`error`/`input`/`output`), beside `RunInfo`/`RunEvent` — NOT
  `NodeRunState`'s camelCase (a derived in-app type).
- **`web/src/api/client.ts`** — `fetchRunNode(workflow, runId, ref)`: encodes the structural `RFRef` as JSON
  in the query (the ONE wire encoding — `sameRef` identity, never a positional flat id), `&run=` only when
  pinned; `isRunNodeDetail` shape-validates the 200 (like `isRFGraph`) so a server bug surfaces in the
  section's catch, not deep in render.
- **`web/src/components/nodes/StatusBadge.tsx`** — EXPORTED `fmtDuration`/`fmtCost` (were module-private) so
  the panel single-sources the SAME formatting as the hover chip (there is no separate `formatDuration`).
- **`web/src/components/ThisRunSection.tsx` (NEW)** — own fetch + `useEffect` keyed `[workflow, runId,
  refKey(nodeRef)]` (the stable structural key, not the nodeRef object) + OWN catch (DR-6 — a failed fetch
  shows a small "Couldn't load run detail", never throws/blanks the panel) + a loading state. Renders the
  `<details className="panel-section" open><summary>This run</summary>` idiom: a `.facts` table (Type/Status/
  Time/Cost/Tokens — cost only when >0, tokens only for an LLM) + Error/Input/Output sections. Generic
  rendering (no per-node-type curation): each value via the panel's existing `CodeBlock` (`text` for strings,
  `json` for objects — both scroll-capped via `.read-param-value`, no truncation). REUSES `.panel-section`/
  `.facts`/`.read-panel-params`/`.read-param` — adds NO CSS (the plan's "≈ no new CSS").
- **`web/src/components/ReadPanel.tsx`** — optional `workflow`/`runId`/`showRunDetail` props; renders
  `<ThisRunSection>` after `ConnectionSections`. Optional → ReadPanel stays standalone-renderable (no run →
  no section).
- **`web/src/views/GraphView.tsx`** — the terminal-only gate: `showRunDetail =
  TERMINAL_RUN_STATUSES.has(runStatus.get(refKey(selectedNode.ref))?.status ?? "")` where TERMINAL =
  {success, cached, failed}; `running`/`stopped`/`unrecorded`/pending excluded. A status-driven CONDITIONAL
  render (not CSS-hide) → a live node flipping running→completion remounts the section; threads
  `workflow`/`runId`.

**Tests (+10, vitest 613):** `client.test.ts` +4 (fetchRunNode: ref-JSON query + `&run=` when pinned /
omitted when null; ApiError on malformed-200 / 404). NEW `ThisRunSection.test.tsx` +5 (facts+input+output;
cost+tokens+string-output; cost OMITTED when cached→0; error block + null-output omitted; DR-6 degrade —
"Couldn't load" without blanking). `GraphView.test.tsx` +1 (the gate: a RUNNING node → panel open but NO
"This run"; flip to success → the section mounts + fetches its Output live).

**Browser-verified (the headline — real click → real /api/run-node → real DOM, via `panel-probe.pflow.md`
reading the section off the settled canvas):** a 3-node run (`greet` shell-templated success, `config` code
with a sensitive input, `boom` shell exit-3 failure), PINNED replay:
- **greet** → facts type=`shell` (tagged, not the raw class) / status=success / time=4ms; Input shows the
  RESOLVED `echo "hello World"` (not `${name}`); Output shows stdout `hello World`.
- **config** → Input renders `inputs { "api_key": "<REDACTED>", "note": "visible-value" }` — REDACTION in the
  real DOM (nested key redacted, normal value full).
- **boom** → an **Error** block "Command failed with exit code 3".
- **UNPINNED** (`discover_live_trace`, no `&run=`) → identical for all three (the live-overlay's own path).
- **CACHED** (2nd run, `config` cache:true) → status=`cached`, **NO cost fact** (event_cost cached → 0 →
  omitted) — the Phase-1 chip↔panel convergence confirmed on the panel side (the chip side is unit-tested +
  code-read: `runStatusLabel` shows no cost for cached).

**Honest finding (NOT a bug — noted; now tracked in GH #540):** a cached node's trace event records only the
static `code` param, NOT the resolved `inputs` (the producer's cache-hit branch passes `node.params` — the
pre-resolution original — to `handle_cached_execution`, and never captures `template_resolutions`; the
`node.params = resolved_params` assignment is miss-path only, `engine.py:~1116`). So the cached config panel
shows `code` only and "no redaction needed" (no `api_key` recorded). The panel faithfully renders the trace
and is CONSISTENT with `pflow report` (same node_params). Pre-existing PRODUCER behavior (Task 172), not
introduced here; the fresh node's redaction was browser-confirmed. Filed **GH #540** (record resolved
inputs + template_resolutions on cache-hit events) — the resolved inputs ARE computed for the cache key, so
the data is available to thread through.

**Not browser-driven (the standing task boundary):** an LLM node's cost/tokens facts — no API key (covered
by the `ThisRunSection` vitest with a fixture). Gates: vitest **613** (603 + 10); `tsc` clean; Python
untouched (8210 / `make check` hold). **Phase 3 COMPLETE — the detail panel feature is end-to-end.**

### Phase 3 follow-up — "This run" redesign (user-requested, browser-verified)

The user found the original `<details>`/`.facts` section near-invisible ("should be the MOST distinct section…
not even a border"). Redesigned its HEADER to mirror the panel's top (`PanelHeader`) and made it a distinct
card (their spec, confirmed point-by-point):
- **`StatusBadge`** gained an `inline` variant (static, no corner offset / halo / hover chip) so the run-status
  badge renders INSIDE a 40×40 tile — replacing the node icon.
- **`ThisRunSection`** header: the badge-tile + `status` (grey eyebrow) over the status VALUE (white, 17px, the
  header "name") + the duration `· cost` where the description sat. `type` DROPPED (redundant with the panel's
  top header). Tokens (LLM only) on a small muted line. The whole section is now a bordered, elevated CARD
  (`.this-run`: `1px var(--border)` + `var(--bg-field)` #1c1c1c + radius + padding) — no longer a collapsible
  `<details>`; reuses the panel's existing classes, adds ~30 lines of scoped CSS.
- Status word stays white (the badge + glyph carry the color); the gated statuses map to the green ✓ / red `!`
  / grey ✓ badges.

**Browser-verified (rebuilt bundle, `panel-shot.pflow.md`):** `greet` → green ✓ tile, `status` / **success** /
4ms; `boom` → red `!` tile, **failed** / 3ms + Error block; `config` (cached) → grey ✓ tile, **cached** / 0ms.
The card now clearly stands out as the most distinct section, its header parallel to the node header at the
top of the panel. Tests updated (the facts table → the status header): `ThisRunSection.test.tsx` asserts the
`status` eyebrow + value + folded `duration · cost` subtitle + tokens line; the GraphView gate test keys on the
section's `Output`/`status` instead of the removed "This run" summary. Gates: vitest **613** (unchanged count),
`tsc` clean; Python untouched.

**Tile refinements (user-driven):** the run-status badge sits in a 40×40 tile with a **2px status-COLORED
border** (matching the badge it frames + the node tile at the panel top). Single-sourced a **status palette**
(`--status-running/success/cached/stopped` at `:root`; `failed` = `--danger`) used by BOTH the corner badge
background AND the tile border so they can't drift. Browser-verified green/red/grey tiles.

**A11y fix (self-review):** dropping the "This run" `<summary>` left the section unnamed → added
`aria-label="This run"` on the `<section>`; the inline tile badge's `aria-label` was redundant with the
visible "status / value" text → the inline variant is now `aria-hidden` (the corner badge keeps its label).

### ruff version split: `make check` is GREEN — only a direct `.venv` ruff run is red (corrected 2026-06-27)

An earlier fresh-context pass reported `make check` **red** and blamed "env ruff drift." **That was a
misdiagnosis — corrected + verified 2026-06-27.** `make check` runs `pre-commit run -a`, whose ruff hook is
**hard-pinned to v0.11.5** (`.pre-commit-config.yaml`) in its OWN isolated env → it **passes** (confirmed:
`pre-commit run ruff` on both flagged files → Passed). The red came from running `uv run ruff check`
*directly*, which uses the **`.venv`'s 0.15.0** (resolved from the `ruff>=0.11.5` *floor* in `pyproject.toml`);
0.15.0 enables newer rules (RUF043/RUF059) that 0.11.5 doesn't. So `make check`/CI were green the whole time —
the two ruff installs just diverge. The version-sync cleanup (bump the pin + fix the 9 pre-existing findings)
is filed as **GH #541** — out of scope for this PR.

- **MINE — done (version-agnostic; pass under BOTH ruffs):** (1) **C901** `run_node._read_matching_event` was
  11 > 10 → extracted `_iter_trace_lines` (the JSONL parse + truncation-tolerance), dropping it under 10 (also
  cleaner: parse vs dispatch). (2) **S105** an `access_token` redaction assertion in `test_run_node.py` read
  as a hardcoded secret → `# noqa: S105` (the codebase's existing pattern, e.g. `test_error_formatter.py`).
  Both are genuine improvements regardless of ruff version; my changed files pass cleanly. `mypy` clean (239);
  `make test` **8210**.
- **PRE-EXISTING (NOT this task, NOT a failing gate) → GH #541:** ruff 0.15.0 (a *direct* `.venv` run only —
  **NOT** `make check`) flags files UNMODIFIED by me at HEAD `494b0385`: `tests/test_core/test_trace_io.py:435`
  (RUF043 — `match="after run.complete"` unescaped `.`) and `tests/test_nodes/test_claude/test_schema_coercion.py`
  (RUF059 ×8 — unused unpacked vars). These do **not** fail `make check`/CI (pinned 0.11.5). Fix = bump the
  pre-commit pin + `match=r"after run\.complete"` + `_`-prefix the unused vars. Tracked in #541.

Honest residual loose ends (none blocking): running/stopped BADGE colors not re-driven post palette-refactor
(identical-by-construction — `var(--status-*)`; success/cached/failed verified); the cost/tokens subtitle
unit-tested but not browser-driven (no API key); cached-node reduced-input → GH #540. The full Task-173
detail-panel diff is UNCOMMITTED; most of it is STAGED (not by me) but the latest a11y + lint fixes are
UNSTAGED → `git add -A` before any commit.

## 2026-06-27 — Isolated deep review of the staged detail-panel diff (2 agents) + verified fixes

User gated next steps on a focused review of the STAGED diff. Ran **2 read-only specialists** (scoped to the
two highest-regret areas rather than the full battery — the diff already had a plan-stage 3-agent review + a
self-review + a follow-up round):
- **`review-impact-completeness`** over the `security_utils.is_sensitive_parameter` consolidation (a SHARED
  rule modified → check ALL consumers).
- **`review-silent-failures`** over `run_node.py` + the `/api/run-node` handler.

**Verdict: no Critical, no in-scope code bugs.** Impact verified the consolidation COMPLETE + non-regressive
(the `SENSITIVE_KEYS` list byte-for-byte intact across HEAD→staged; every one of the 8 consumers traced; the
bidirectional behaviour shift fully accounted for — every narrowing is an intended false-positive fix or the
documented delimiter-less boundary, every `rerun_display` broadening is a real delimited secret). Silent-failures
verified the reader correct across all 7 dimensions (recursive redactor + `$pflow_blob` guard both genuinely
DEEP-recursive; partial `llm_call` never KeyErrors; handler maps a bad ref → 400 and real corruption → a loud
500). Three findings folded (each independently re-confirmed against the code before acting):

- **W1 (Warning) — the truncation-tolerance guard was correct but UNPINNED.** `_iter_trace_lines` tolerates a
  truncated FINAL line (mid-flush tail) and RAISES on a malformed EARLIER line ("corrupt must be visible"), but
  no test exercised either direction — a future refactor could silently flip it (swallow corruption → wrong
  panel data, or 500 on every live mid-flush poll) with all tests green. **Fix:** +2 fixtures
  (`test_truncated_final_line_is_tolerated`, `test_malformed_earlier_line_raises_not_silently_swallowed`).
- **S1 (Suggestion) — an `OSError` mid-scan silently 404'd as "node didn't run."** **Fix:** a `logger.debug`
  breadcrumb at the `read_text` seam (keeps the 404 — a transient read shouldn't 500) + a test
  (`test_os_error_mid_scan_returns_none`; discovery uses `open()`, so patching `Path.read_text` isolates the
  fault to the reader). Verified in `run_tailer` that discovery is robust to a corrupt middle line
  (`read_run_status` catches per-line `ValueError`; `_read_meta` reads the head only).
- **Out-of-scope leak the impact agent surfaced + user chose to fold in (Option A) — the 4th, un-consolidated
  redaction path.** `runtime/engine/batch_item_summary.py` carried its OWN `SENSITIVE_KEY_FRAGMENTS` tuple with
  a raw-substring match — MISSING `pwd`/`private_key`/`ssh_key`/`credential(s)`, so a short-valued failed-batch
  field named e.g. `pwd` rendered VERBATIM in the summary (pre-existing, Task-172-era; long values already
  hash). **Fix:** deleted `_is_sensitive_key` + the local tuple → `_summarize_field` now defers to the shared
  `is_sensitive_parameter` (no import cycle — `security_utils` is stdlib-only core; verified). Net: the leak
  closes AND the last raw-substring copy is gone, so "every redaction site defers to one rule" (`core/CLAUDE.md`)
  is now literally true (updated to list `batch_item_summary`). Behaviour delta: gains
  `pwd`/`private_key`/`ssh_key`/`credentials`/`access_token`; drops the over-match on `author`/`tokens`/`secretary`
  (never real secrets). +6 tests (5 parametrized newly-redacted names + 1 over-redaction guard).

**Gates (all green):** `make test` **8219** (8210 baseline + 9: +3 run_node, +6 batch-summary; **0 regressions**);
`make check` clean (mypy 239; ruff auto-dropped one now-unused `# noqa: S106`). The W1/S1 + batch-summary fixes
are UNSTAGED (the rest of the detail-panel diff is staged) → `git add -A` before any commit.

**Still owed to close the task** (unchanged): pin D1 · `task-review.md` + tool-elevation verdict · commit.

## 2026-06-27 — Catalog redesign: last-run times + name-only rows (user-requested, browser-verified)

The user found the catalog inconsistent: saved rows were name/catalog-ordered and showed NOTHING about past
runs (only a live badge), while the git-bucketed ran-but-unsaved rows were recency-sorted with a status mark —
and every row carried a noisy absolute path (+ a description on saved rows). Four asks, all frontend-only:

- **Last-run time** — a new `utils/format.ts::timeAgo(iso, nowMs?)` (relative "3m ago" / "yesterday" / a date
  past a week; `""` for a null/unparseable stamp; injectable `now` for deterministic tests). The producer
  writes a tz-less local `datetime.isoformat()` → `new Date` reads it as LOCAL (correct for the loopback).
- **Name-only rows** — unified BOTH row types to `name (left) · RunMeta (right)`; dropped the visible
  description + path → they ride the row's hover `title` (description run through the existing `stripMarkdown`).
  The `Markdown` inline render is gone from the catalog.
- **Recency sort everywhere** — the Saved section now sorts by most-recent run (was catalog order); a never-run
  workflow sinks to the bottom (alpha among peers). Repo buckets were already recency-sorted.
- **Dashboard button** — held off (it would link to a screen that doesn't exist; the catalog now covers the
  per-workflow run surface). Coupled to the deferred global-dashboard decision.

`RunMeta` is the one right-side summary: a pulsing `● running` while live, else the `runMark` status glyph
(✓/✗/⊗/⊘) + the `timeAgo` label, or a muted `never run`. CSS: `.catalog-item` became a single flex row
(name ellipsizes so it never shoves the meta off); added `.catalog-item-meta/-time/-never`; removed the now-dead
`.catalog-item-desc/-path/-status`.

**Self-review found + fixed one real bug.** `RunMeta` claimed `never run` whenever there was no run group — but
`runGroups` is ALSO empty while `/api/runs` is in flight AND on a DR-6 failure, so a scan failure made every
saved row FALSELY assert "never run" (and the happy path flashed it before data arrived). Gated `never run` on a
new `runsLoaded` flag (set only on a successful runs fetch); pending/failure now render no run-meta. Pinned by
the DR-6 test (`queryByText("never run")` is null on failure).

**Tests (+9, vitest 621):** `format.test.ts` +5 (`timeAgo`: null/invalid → ""; just-now/minutes/hours;
yesterday/Nd; absolute-date past a week; future-skew → just now). `CatalogView.test.tsx` +3 (last-run time +
never-run; description/path moved to the hover title, markdown-stripped, absent from the body; Saved recency
sort) + the existing path/inline assertions moved from body text to `getByTitle`, + the DR-6 no-false-never-run
assertion. `tsc` strict clean; Python untouched (8219 / `make check` hold).

**Browser-verified** (rebuilt bundle, `catalog-redesign-probe.pflow.md` — settle until the runs data renders,
DOM read + full-page screenshot, over 171 real runs): Saved shows `shoot ✓ 3m ago` / `git-worktree-task-creator
✓ 3d ago` above the `never run` rows (recency confirmed); the worktree repo bucket shows the live
`catalog-redesign-probe ● running` plus color-coded ✓/✗/⊗/⊘ marks + relative times; `noAbsPathInBody: true`
(path lives only in the hover title). Screenshot confirms the clean single-line rows.

**Documented limitations (not bugs — disclosed, not fixed):** (1) the catalog is a ONE-SHOT `/api/runs` fetch at
mount — relative times don't tick and the running badge can go stale if a run finishes while it's open (tied to
the deferred dashboard-polling decision, not bolted on here); (2) path-equality matching can read `never run` for
a workflow that ran under a different path spelling (the same v1 case-fold boundary, now more visible as a
positive claim); (3) native `title` hover (delay / no touch / unstyled — the agreed "maybe hover" choice); (4) a
truncated long name has no tooltip recovery (names are short in practice). `views/CLAUDE.md` still calls
CatalogView "Trivial" — stale doc debt, predates the bucketing.

## 2026-06-27 — Closed analyze-cache R6 (the deferred eager-meta label mislabel)

R6 was the last open eager-`meta` ripple from the slice's deep review (deferred as cosmetic; selection was
always correct). With eager-`meta`, an interrupted / still-in-flight run leaves a `meta`-only trace with no
`run.complete` trailer → `final_status="incomplete"`. `analyze-cache` autoload correctly buckets `incomplete`
*with* genuine failures (non-reusable, never shadows a good run — `_collect_candidate_traces`), but
`_autoload_selection_with_disclosure` (`trace_loading.py`) **hardcoded "(failed run)"** in both disclosure
notes → an interrupted run was reported to the agent as a *failed* run, misattributing the cause.

- **Fix:** added `_non_reusable_outcome_label(data)` — reads `final_status` and returns `"incomplete run"`
  vs `"failed run"`; both disclosure branches now defer to it (the no-success branch destructures
  `failed[0]` so it has the trace `data`, not just the path). Pure wording change — **selection,
  bucketing, and all cost/token math are untouched** (the label feeds no computation). Mirrors the D6
  raw-facts principle (DR-2: don't synthesize a wrong status word). The sibling `_format_rejection_note`
  already read the real `final_status`, so it needed no change.
- **Tests (+2, both directions pinned):** `test_autoload_skip_note_labels_incomplete_run_not_failed`
  (newer incomplete shadowed by older success → note says "incomplete run", NOT "failed run"; selection
  still the success) + `test_autoload_no_success_note_labels_incomplete_run_not_failed` (only-incomplete →
  no-success note says "incomplete run"). Also strengthened the two existing `final_status="failed"` tests
  to assert the note still says "failed run" (not "incomplete run") — so the helper can't regress to a
  single label.
- **Gates (all green):** `make test` **8221** (8219 baseline + 2, 0 regressions); `make check` clean
  (mypy 239 files, ruff/ruff-format pinned, deptry). UNCOMMITTED (not committed per the no-auto-commit rule).

## 2026-06-29 — Remaining-items review + D4 (launch) spun out into Task 175

A review session (no overlay code changed) to answer "what's left in the original plan + d6?", then a long
design discussion of the deferred **D4 launch button** that grew into its own feature and was spun out.

**Remaining-items audit (original `implementation-plan.md` + `d6-plan.md` vs shipped):**
- **Built / done:** slice, sub-workflow + batch checkpoint, `/api/runs` + `&run=` pin + replay, catalog
  running-badge + RunSelector, detail panel, flock liveness. R6 closed (entry above).
- **The ONE plan feature not built: the global runs dashboard** (`?view=runs`, d6 Phase 3c / build-order
  step 4 / DR-7). Confirmed absent (no `App.tsx` route, no view file) — **deliberately held off** (the
  catalog covers per-workflow run history; the dashboard would link to a screen that doesn't exist). Not
  a dropped item; a conscious deferral.
- **ChipRail status chip (d6 Phase 4) was RETIRED by design**, not skipped — `ChipRail.tsx:11` documents
  the slot was dropped in favor of the StatusBadge corner-badge + hover-chip overlay (commit `494b0385`).
  The run-status-visibility need is met, differently.
- **D4 launch POST** stayed deferred (the CORS/exposure tripwire trigger) — now revived as Task 175.
- **analyze-cache R6:** closed (entry above). **Still owed to CLOSE Task 173 (unchanged):** pin D1 +
  `task-review.md` (incl. the tool-elevation verdict for the overlay-status probe). These are
  independent of Task 175.

**D4 → Task 175 ("Run workflows from the UI"):** the launch-button discussion expanded into launch +
auto-generated inputs form + run inspection + re-run, and was given its own task (`task_175/task-175.md`
+ a design-discussion braindump in `task_175/starting-context/`; added to root `CLAUDE.md` "Next?").
Findings that touch Task 173's own record:
- **Security re-evaluation (the tripwire the plan reserved):** a launch POST is ADR-0008-clean if it
  **spawns `pflow run` as a detached subprocess** (the run writes its trace; the existing tailer +
  overlay observe it — no new server code; server stays a pure observer). The only real web threat is a
  malicious page driving the loopback server; loopback + no-CORS + strict `application/json`
  (`_json_body`) already block cross-origin form/JSON POSTs — the lone gap is **DNS rebinding**, closed
  by a `Host`-header guard. No auth/CSRF tokens (overengineering for single-user loopback). So D4 is
  *not* the landmine the "tripwire" framing implied — it's a thin spawn + a Host check.
- **Inputs are recorded NOWHERE today** (trace `meta` omits them; inputs seed the shared store, no event)
  → Task 175's keystone is recording `meta.inputs` in the eager meta. Relevant here because it's a small
  producer change to the SAME meta line this task made eager.
- **The frontmatter execution store (`last_execution_params` et al.) is deprecatable** once `meta.inputs`
  exists (3 CLI display consumers only; lossy/saved-only) — but carries an MCP-history cost (MCP/
  `--no-trace` runs write frontmatter, no trace), so deprecation is a **follow-on**, not part of 175.
- **Trace durability finding (affects this task too):** `~/.pflow/debug` has **no cleanup/rotation/TTL/
  cap** and no clear command — traces grow unbounded. The overlay already generates traces; the run
  button will generate many more. A retention policy is a reasonable fast-follow (not blocking, not
  filed yet).

## 2026-06-29 — Task 173 CLOSED: D1 pinned + task-review written (doc-only)

The two owed close-out items, both doc-only (no code touched):
- **Pin D1.** `context/adr/0008-live-execution-overlay.md` `Status: proposed`→`accepted` + a dated "Update —
  as shipped" note (architecture landed as decided; the one v1-scope refinement: `node.start` was BUILT, not
  deferred, for every main-thread node — the true remaining boundary is batch ITEMS + the batch-of-sub-workflow
  HOST). `task_133/design/d1-event-schema.md`: the two "consumer-derivation pending the live overlay / before
  final pinning" hedges flipped to **validated + pinned** (the overlay shipped + browser-verified the contract).
- **`task-review.md`** written — the distilled, seam-first forward-reference (must-not-break invariants, seams &
  contracts, gotchas, the Task-175 handoff, regression-catching tests, and the owed tool-elevation verdict:
  elevate the overlay-status-probe + the drive-live-run loop). `task-173.md` `## Status`→`done`, `## Completed`
  2026-06-29.

Remaining (non-blocking, deferred): the **S-d docs/guide** pass (the overlay isn't yet documented for users);
a trace-retention issue (unfiled); 3 doc-debt one-liners (`ui/CLAUDE.md` `/api/runs` missing `git_root`; the
likely-dead `_has_run_complete`; `_read_matching_event`'s OSError docstring) — all noted in the review's Deferred section.

**Follow-up (same day) — S-d + the 3 doc-debt one-liners DONE (doc/docstring-only):**
- **S-d docs/guide:** user docs (`docs/reference/cli/index.mdx`) gain a no-internals overlay paragraph
  (watch a run · replay · click-a-node detail · catalog run-state); `pflow guide` (`features/ui.md`) gains an
  overlay bullet with the CLI-vs-MCP watchability caveat (only CLI runs stream — agent-actionable);
  `web/CLAUDE.md`'s stale "Top slot reserved for the future run/status control" → `RunSelector`.
- **Doc-debt:** `ui/CLAUDE.md` `/api/runs` shape gains `git_root`; the dead `_has_run_complete` REMOVED from
  `run_tailer.py` (zero callers verified — `discover_live_trace` reads `cand["complete"]`; one test rationale
  docstring scrubbed too → no dangling reference); `run_node._read_matching_event` docstring gains its
  `OSError`→`None` degrade path. `make check` green (mypy 239); the affected tests pass (109).
Trace-retention is filed as **#542** (the last remaining noted item — a fast-follow).
