# Task 172 — Implementation Progress Log

> **What this is:** the *journey* — decisions locked, alternatives rejected, and what the review battery
> surfaced — during the **design + plan + review** session (2026-06-22). **Not yet implemented.**
> **What this is NOT:** the *what/why* → `task-172.md`; the *how* + per-phase gates →
> `implementation/implementation-plan.md`; the original-design tacit knowledge → the two
> `starting-context/braindump-*` files. This log is the **delta** those don't capture — read it for *why the
> plan looks the way it does* and *what was already tried and dropped*, so you don't re-litigate.

## 2026-06-22 — Session: research → design discussion → plan → 3 review rounds → spec alignment

Pre-flight re-grep (6 parallel `pflow-codebase-searcher` passes) confirmed every file:line against current
`main` (the rebase-stale-refs trap is closed). Then a design discussion with the user, a full plan, **three
`/deep-review` rounds (9 specialist passes)** folded in, and finally the task spec was re-aligned to the
locked decisions. The plan converged (round 3 found zero correctness issues — only test-sharpening).

---

## Decisions locked THIS session (and the reasoning, not just the verdict)

These were **open or unstated** in the original braindumps; they are now settled. The task spec + plan record
the verdicts — this records *why*, so a future agent doesn't re-open them.

- **Adopt the `status` enum (REVERSED from "lean skip").** My initial instinct (and the braindumps') was to
  keep `success`+`cached` for v1. The user asked *"we don't have to be backward compatible with old traces —
  does that change anything?"* — and it did: the **only** real objection to the enum was that it would coexist
  forever with legacy booleans (two representations = harder to reason about). No-back-compat **removes that
  objection**, so the enum becomes the genuinely simpler end-state (one producer-set field vs. derivation
  scattered across ~15 readers). This is the user's "simplicity of the FINAL code" lens in action — it flipped
  the call.
- **No-backward-compat (confirmed by user).** Enables the enum + inline blobs cleanly. **But review scoped it
  down:** it does *not* license ripping out the `... or "success"` defaults (6+ sites, entangled with
  `analyze-cache` reuse policy + synthetic fixtures) or the legacy single-object reader. Those are inert for
  modern traces — left intact. (Round-1 review-plan + impact-completeness both caught the over-broad removal.)
- **Lenient *transitive* orphan-drop for incomplete traces.** The user pushed hard on *"is nothing resumable
  when a crash is inside a sub-workflow?"* The honest answer: children flush before their host's completion
  event, so a crash mid-sub-workflow orphans them. Rather than accept "recover nothing," the reader drops
  dangling children **transitively** in incomplete (no-`run.complete`) traces only → recovers everything
  well-formed. This is *reader policy over data the producer already wrote* — the clean split that keeps the
  producer dumb and makes Task 164 (resume) an additive layer, not a rewrite. (This was the framing that
  satisfied the user's extensibility question.)
- **`node.start` / in-flight signals stay deferred.** The user asked why. Recorded reasoning: no v1 consumer
  needs it (overlay is L1/completion; ADR-0008 accepts the parallel/batch "running" gap), it doubles the
  producer surgery + adds reader merge logic, and its *shape* isn't knowable until a consumer (overlay-L2 or
  Task 164) validates it — building it now = guessing. It's cleanly additive later (the host-descent stack is
  exactly its hook), so deferring costs ~nothing.

---

## The conceptual crux (worth internalizing before you touch the engine)

**Host span emit-ordering.** A sub-workflow host's event is recorded at *completion* (engine step 16), but its
children record *during* its execution — so children flush **before** the host. Reconstruct needs
`parent.seq < child.seq`, so the host's `seq` must be **reserved at descent** (pushed on the stack) and used
at completion. I hand-verified this reserve-at-descent scheme reproduces today's **DFS pre-order `seq`
exactly** (nested / sibling / sequential cases) — which is *why* the equivalence test passes for complete runs
without changing reconstruct. The flip side: a crash mid-sub-workflow leaves children referencing a never-
written host → the lenient transitive drop (above) is the answer, not a producer change.

---

## Alternatives considered and REJECTED this session (don't re-explore)

- **Run-level dead-end signal instead of flipping the node event** (for the routing dead-end). Verified the
  trace's `failed_node_ids`/`final_status` read **only** the per-event `status` flag — the run-level
  `__failures__`/`__execution__` state is never consulted at save time. A run-level approach would need a new
  channel into `_determine_trace_status` *and* break `test_failed_node_invariant.py`. **Rejected** for the
  **re-flush a corrected line** approach (smaller blast radius; keeps the single source of truth).
- **1-event-lag / deferred flush** (hold the last event un-flushed so a correction lands before flush).
  **Rejected:** it delays the live stream by one event, and on a slow node (30s LLM call) the *previous*
  node's completion wouldn't surface for 30s — unacceptable for a "live" overlay.
- **Keep-nested in-memory store** — already rejected in the original braindumps; not re-opened.

---

## What the 3 review rounds surfaced (the non-obvious ones)

- **The `status` enum is one atomic change, not a trailing pass** (round 1, validation-consistency). The cost
  readers (`trace_tree.py` `cached` boundaries) break the instant the producer writes `status` — so producer
  + every reader + central fixtures land together.
- **`tree() == reconstruct(disk)` gives FALSE confidence on cost** (round 3, validation-consistency **and**
  test-fidelity, independently). Both feed the same `TraceTree`, so a missed `cached`→`status` reader leaves
  them *equal but wrong*. ⇒ the equivalence test's cost/status assertions **must be hardcoded literals**, and
  it must include a **cached node nested inside a sub-workflow** (assert `parent_id == host.seq`). This is the
  single most load-bearing test detail.
- **The two-pass reconstruct (dedup-by-id last-wins) elegantly subsumes BOTH** the lenient orphan-drop and the
  dead-end correction re-flush — one mechanism, two problems. (Emerged while resolving the round-2 dead-end
  finding.)
- **A bug I caught in my own plan during review:** I had scoped `mark_last_event_failed` to top-level events
  (to avoid child-overwrites-parent) — but a routing dead-end *inside a sub-workflow* (GH #250) targets a
  *child* event, which top-level scoping would silently miss. Fixed: it scans **all** events (most-recent match
  is unambiguous); only the dict-keying aggregators need top-level scope.
- **Concurrency verified clean** (round 2, concurrency-safety): no constructible interleaving reaches the run
  collector's `seq` from a worker. Hardening added anyway — a main-thread `assert` on `_next_seq`/`descend`/
  `ascend` turns a future silent `seq` gap into a loud failure; `_host_frame` added to the existing `:324`
  instance-reuse reset.
- **`tree()` must be `is_run_scoped`-guarded** (round 2, silent-failures): `_rebuild_event_tree` *raises* on
  un-stamped events, so a bare `tree()` would crash on buffer/test collectors. Guard: rebuild only when
  run-scoped, else return raw `self.events` (already tree-shaped) — also semantically correct.

---

## Confidence calibration (honest)

**~85% the plan is correct as written.** Verified hard: every file:line (3× over), the core architecture
(concurrency couldn't break it, DFS-`seq` equivalence hand-checked), the consumer inventory (complete), the
producer↔reader contract (consistent all four ways). The residual ~15% is **implementation-discovery** that no
review can close — specifically the **two-pass reconstruct + dead-end re-flush** (new logic, reviewed once,
never *run*) and the streaming-flush + pytest-gate I/O timing. The braindump's warning holds: **a green
skeleton (step-1 gate) proves almost nothing about the hard part** — the real bar is the step-2 sub-workflow
+ parallel-batch checkpoint. Build skeleton-first so that risk surfaces in hours, not after the whole thing is
built. ~300 LOC is a **floor**.

## Next step

Capture the test baseline (`pytest -m trace_files` + the named-files set in the plan), then build **Pieces
1+2+status atomically** and get the skeleton equivalence test green **before** touching the engine. Then
Piece 3 + the checkpoint. Then Pieces 4+5 (streaming). Run the code-stage review trio after.

---

## 2026-06-22 — Session: pre-flight + boundary re-cut (implementation start)

**Pre-flight done (baseline + re-grep).** Baseline captured & green: `pytest -m trace_files` = **164 passed**,
the named set = **549 passed**, 0 failures (saved to `baseline-trace_files.txt` / `baseline-named.txt`). Four
parallel `pflow-codebase-searcher` passes re-verified every cited line against current code. All land; minor
doc-drift corrected **in the plan itself** (consolidated note at top): batch→collector drain is `engine.py:1180`
(not `batch_executor.py`); `_pflow_stack` is f-string-composed (`:177` stale); `trace_report.py` has 16
status-read sites (not ~13); `run.py:_echo_target_node_path`/`_save_trace_file` read neither `success`/`cached`
(scoping/finalize sites, not status-read sites). Confirmed cached + api-warning paths funnel through
`record_trace → record_node_execution`, and the two collector construction sites (`runner.py:141` root,
`workflow_executor.py:361` buffer).

**Decision (approved by planning agent): re-cut the Phase-1/Phase-2 boundary.** The original plan bundled
the `status` migration with emit-time correlation + a whole-file writer in step 1. Pre-flight found that
pre-stamping correlation onto `self.events` (a) collides with `flatten_trace_to_lines`'s reserved-key guard
(forces a writer swap), and (b) is incoherent before Piece 3 — top-level events would be stamped in
*completion* order, a different seq space than flatten's DFS-derived nested-child seqs, with no single
coherent seq space until Piece 3's reserve-at-descent. **Pre-stamping buys nothing before Piece 3** (flatten
already derives correct correlation at save). So the boundary moved: **step 1 = `status` migration only
(writer untouched, `is_run_scoped=False` so correlation is dormant scaffolding); step 2 = correlation +
collector unification + the whole-file writer, as one coherent change (with Piece 3).** Same G2 end-state and
final code. The planning agent confirmed there was no hidden intent behind a Phase-1 `finalize()`. Plan's
build-order section updated with the rationale.

**Status migration approach — booleans at the boundary.** `record_node_execution` keeps its `success`/`cached`
params and derives the `status` enum once (the single event-producing seam); the engine/instrumentation call
sites that compute those booleans (`instrumentation.py:586/594`, `engine.py:1192`) are UNCHANGED. Only direct
event/item dict writers change. This is a deliberate deviation from Piece 6.2's literal call-site list —
rationale: concentrate the `success`/`cached`→`status` mapping in one place rather than scatter it across
callers (deletion test). `_status(success, cached) = "cached" if cached else ("failed" if not success else
"success")` — `cached` implies success at write time (errors aren't cached); a later routing dead-end flips to
`"failed"` via `mark_last_event_failed`, so the old `(cached, !success)`→`failed` ambiguity collapses cleanly
into the single field.

**Next:** implement step 1 (status migration), run the suite to green, report the delta, then step 2.

---

## 2026-06-22 — Step 1 COMPLETE: `status` enum migration (green-suite gate met)

**Result:** full suite **8006 passed / 0 failed** (`uv run pytest tests/ -n4 -m "not e2e" --ignore=…/test_llm_integration.py`); `make check` green (ruff + ruff-format + mypy "no issues in 236 source files" + deptry). Baseline delta: **0 regressions** (baseline was trace_files=164 + named=549 green; both subsets remain green inside the 8006). Writer UNCHANGED (still `flatten_trace_to_lines`, now carrying `status`) — correlation still derived at save; `is_run_scoped` stays `False` everywhere this step (scaffolding dormant).

**What changed (per-node `success`/`cached` → one `status` enum):**
- **Producer** (`workflow_trace.py`): new `_node_status(success, cached)` (the single mapping site); `record_node_execution` writes `status`; `mark_last_event_failed` sets `status="failed"`; `_unrecovered_failed_node_ids` reads `status == "failed"`. Plus dormant scaffolding: `is_run_scoped` ctor flag, `tree()` (rebuild when run-scoped, else `self.events`), `_top_level_events()`, cost readers routed through `tree()`, status/count readers through `_top_level_events()` (all no-op while `is_run_scoped=False`).
- **Batch** (`batch_executor.py`): item + warmup dicts write `status` (items carry no `cached`).
- **Readers**: `trace_tree.py` 5 cached sites → `status == "cached"` (covers `trace_loading.py` transitively via `WalkEvent.is_cached`); `trace_report.py` 16 sites → `status` reads; `_row_status` collapses to `str(event_or_item.get("status", "success"))` (the `str()` is load-bearing — mypy `no-any-return`).
- **Fixtures/tests**: `trace_fixture_builder.py` + `_make_event` (kept `success`/`cached` params as intent, map to `status`); 4 static `cache_analysis/*.json` regenerated via `_generate.py`; ~14 test files migrated (10 via parallel `test-writer-fixer`, one per file; + `test_batch_node`/`test_batch_prewarm` stragglers; + a fidelity sweep of 6 residual `"cached": True` fixtures across `test_trace_tree`/`test_cache_analysis_*`).

**Key learnings / deviations (with rationale):**
- **Booleans-at-the-boundary (deviation from Piece 6.2's literal call-site list).** `record_node_execution` keeps its `success`/`cached` params and derives `status` once; `instrumentation.py:586/594` + `engine.py:1192` are UNCHANGED. Rationale: concentrate the mapping in the single event-producing seam (deletion test) rather than scatter `status` strings across callers. Already noted in the plan's pre-flight corrections.
- **Display preserved, not modernized.** A cached node still renders `Status: success [cached]`; `_row_status` table shows `success`/`cached`/`failed`. Changing the display is a separate, user-visible decision — out of scope for a shape migration.
- **`(cached, !success)` ambiguity is gone.** `_node_status` is cached-wins (a cached node succeeded this run); a cached-then-failed routing dead-end is recorded `status="failed"` via the flip. Updated `_row_status`'s docstring + the one test (`test_cached_and_failed_event_renders_failed_not_cached`) that pinned the old dual-field shape.
- **Every failure was a stale fixture/assertion, never a src bug** — each fixer independently confirmed cost/count assertions passed UNCHANGED once fixtures carried `status` (the strongest evidence the migration is behavior-preserving). The `'trace' != 'trace'` cache-analysis scare was a stale `"cached": True` inline fixture, not a cost-reader regression.
- **Fidelity (pitfall #19):** residual `"cached": True` fixtures silently stop exercising the cached path (reader now keys on `status`) — swept 6. One (`per_id_emission`) had a PAIRED assertion reading `cached` that also needed migrating; the lesson is to migrate fixture + its assertions together.
- **Enforced atomicity:** the builder↔producer shape-parity test (`TestTraceFixtureBuilderShapeParity`) + the committed-JSON drift test made the builder + static-fixture migration mandatory, not optional — exactly as `tests/CLAUDE.md` #19 intends.

**Next: step 2** (the deep core) — flip root `is_run_scoped=True`, host-descent stack, collector unification (flat children w/ emit-time `parent_id`/`ancestor_path` via reserve-at-descent), `tree()`→rebuild, whole-file emit-direct writer. Per the planning agent: WRITE the equivalence (hardcoded cost literals + nested-cached `parent_id == host.seq`) + OLD-path-preservation tests FIRST as the driver. Streaming stays step 3.

---

## 2026-06-22 — Step 2 COMPLETE: collector unification + emit-time correlation + new writer (G2 met)

**Result:** full suite **8011 passed / 0 failed**; `make check` green (mypy "no issues in 236 source files",
ruff + ruff-format + deptry). The deep surgery caused **only 2 net regressions**, both expected and fixed
(see below). Smoke + 5 dedicated driver tests prove the *new* behavior (the existing suite only proves
no-regression).

**What changed (the producer goes flat + emit-time):**
- **`workflow_trace.py`**: `_HostFrame` dataclass; run-scoped `__init__` state (`_seq_counter`,
  `_host_stack`, `_owner_thread`); `descend`/`ascend`/`_next_seq`/`_current_ancestor_path` (reserve-seq-at-
  descent = DFS pre-order); `_assert_owner_thread` (loud no-lock guard); `record_node_execution(frame=...)`
  stamps `id`/`seq`/`parent_id`/`run_id`/`ancestor_path`/`port` when run-scoped (frame → reserved seq, else
  `_next_seq` + `_host_stack[-1]`); `save_to_file` is **dual-path** — run-scoped → `emit_flat_events_to_lines`
  (verbatim flat events), buffer/test → A-C `flatten_trace_to_lines` (derive at save).
- **`trace_io.py`**: new `emit_flat_events_to_lines` (emit-time counterpart to `flatten`).
- **`runner.py`**: root collector `is_run_scoped=True`.
- **`workflow_executor.py`**: `_open_child_trace` helper decides NEW (descend into run collector) vs OLD
  (per-sub-workflow buffer) path; `exec` reuses the run collector on NEW, ascends in `finally`, embeds only
  on OLD; `_host_frame` reset per run.
- **`engine.py`**: reads `_host_frame` after `node._run`, threads it into all three `record_trace` paths
  (step-16, except, api-warning). **`instrumentation.py`**: `frame` param on `record_trace` + `handle_api_warning`.

**Driver tests (`tests/test_runtime/test_emit_time_trace.py`, all green):** equivalence (sub-workflow, NEW
flat path: `tree()==reconstruct(disk)` + cost literal + `parent_id==host.id` + `ancestor_path`); **cached node
nested inside a sub-workflow** (two-run memo hit — the load-bearing case: cached child still nests under host,
run-2 cost EXCLUDES it); **OLD-path preservation** (parallel batch of sub-workflows stays inline with NO
correlation keys — the highest-risk silent regression, asserted discriminatingly); looped-sub-workflow
re-descend (distinct host seq per visit, balanced stack); ADR-0008 checkpoint (sequential sub-workflow AND
parallel batch in ONE run). Routing-dead-end (top-level + sub-workflow-internal) + loop-recovery covered by
existing tests (updated for the flat shape).

**Deviations / decisions (CLEAR reasons):**
- **api-warning frame threading (correctness addition, not in the plan's explicit list).** A `WorkflowExecutor`
  host that descended and then hits api-warning records its completion via `handle_api_warning` (step 10),
  BEFORE step 16 — without the frame there, the host event would take a fresh `seq` while its children
  reference the reserved one → orphaned children. So `frame` is threaded into all THREE record paths
  (step-16, except, api-warning), not just step-16. Required for correctness; the plan only named step-16.
- **`node_id` declared on `WorkflowExecutor`, NOT `BaseNode`.** `descend(self.node_id)` needs the typed attr.
  Declaring it on `BaseNode` (the "universal" view — the compiler sets it on every node) BROKE 2 ClaudeCode
  tests that distinguish an ABSENT `node_id` for their schema-error fallback. Localizing to WorkflowExecutor
  (the only `self.node_id` reader) keeps every other node's absent-node_id behavior intact. (Caught by the
  full suite — exactly the blast-radius the manifesto warns about for core changes.)
- **Dual-path writer keeps `flatten_trace_to_lines`** (for buffer/test collectors that save under
  `@trace_files`) rather than removing it now — Piece 4's "remove flatten" lands in step 3. `emit_flat_events_to_lines`
  duplicates the meta/run.complete/blob-trailer assembly; step 3/4 consolidates.
- **`_open_child_trace` helper** extracted from `exec` to fold C901 complexity (the NEW-path branching pushed
  exec 10→11). Two intentional invariant `assert`s carry `# noqa: S101` (the plan wants loud asserts).
- **The 2 expected regressions, fixed:** (1) the stateless-invariant meta-test (added `_host_frame` to its
  WorkflowExecutor allowlist, next to `_child_trace_events`); (2) `test_routing_failure_in_sub_workflow...`
  asserted the OLD nested `sub_workflow_events` shape — updated to the flat `parent_id == host.id` linkage
  (strengthened with the explicit linkage assertion, the failed-node analogue of the cached-nested check).

**Not done (step 3 = streaming):** per-event flush, inline-first-occurrence blobs, two-pass reconstruct
(dedup + lenient transitive orphan-drop), crash-tail tolerance, dead-end re-flush. The writer is whole-file
(emit-direct from the flat store) — the clean seam the plan specifies before streaming.

### Self-audit finding (fixed): `only_node` clobber on `--only <sub-workflow>` (issue #443 class)

Introspection found — and a new regression test pins — a real bug Phase 2 introduced: `engine.run` stamped
`self.trace.only_node = self.only_node` unconditionally. With collector unification, a sub-workflow's child
engine REUSES the run collector, so `--only <a-sub-workflow-node>` had the child engine re-stamp `only_node`
to its own `None`, wiping the root's `--only` marker → the saved trace would masquerade as a full-run
snapshot source (the exact issue #443 the field exists to prevent). The full suite did NOT catch it (no
existing test does `--only` on a WorkflowExecutor node + checks the marker). **Fix:** only the ROOT engine
(`_pflow_depth == 0`) stamps `only_node`; nested engines reuse the collector untouched. (A first attempt
keyed on `saved_trace is self.trace` was wrong — true for the root too if the collector is pre-installed —
which is itself a useful lesson: the depth check is the robust root/child discriminator.) Regression test:
`test_only_on_subworkflow_does_not_clobber_only_node`. Suite still 8012 green, `make check` clean.

---

## 2026-06-22 — Code-stage review round (4 specialists) + gap-closing + manual e2e

Ran the 4 most relevant reviewers on the staged diff: **impact-completeness, silent-failures,
feature-interactions, concurrency-safety** (chose these over test-fidelity to spend the slots on code bugs
I can't self-see; covered the known test gaps myself below). **No Critical bugs.** Strong cross-corroboration:
the `status` migration is complete, the only_node clobber hunt is exhaustive (only_node was the only
run-level attr a child could corrupt), and concurrency-safety **could not construct a worker→run-collector
race** (verified with a live probe; both routing clauses independently hold). The headline equivalence test
was explicitly validated as "not a paper tiger."

**Findings + fixes (all applied; suite 8014 green, `make check` clean):**
- **descend/ascend imbalance** (flagged by 3 of 4 reviewers — strongest signal). `descend()` sat outside the
  `try/finally` that `ascend()`s, so a `CompilationError` in the gap orphaned a host frame (latent today —
  aborts the run — but one refactor from silently mis-nesting sibling sub-workflows). **Fix:** `_open_child_trace`
  no longer descends; `exec` does compile/storage/engine-creation FIRST (so a `CompilationError` propagates
  unrouted, before any descend), then descends immediately before the `try`; `finally` ascends guarded by
  `_host_frame is not None`. The descend's owner-thread assert stays outside the `except` (stays loud, not
  masked as a sub-workflow failure). Balance pinned by Test C + D's `_host_stack == []` asserts.
- **`_echo_target_node_path` walked the flat store** (`run.py`) — the Piece-2.B top-level scoping I had
  *documented but not applied*; the reviewer disproved the plan's "unreachable" claim (`--only <sub-workflow>
  --report` reaches it via NEW-path descent). **Fix:** enumerate top-level (`parent_id is None`) + detect a
  container by `node_type == "WorkflowExecutor"` too (a flat host has no stored `sub_workflow_events`). Low
  severity (only a stderr hint; the report itself is correct) but a genuine sibling of the only_node class.
- **Tests added:** `test_host_recorded_after_ascend_with_frame_keeps_children_linked` (the api-warning timing —
  host recorded AFTER ascend must reuse its reserved frame or children orphan → `reconstruct` raises on a
  COMPLETE trace; a regression there hard-fails the whole trace, so it's locked) and
  `test_old_path_sequential_batch_of_subworkflows_stays_nested` (the instance-reuse path the parallel test
  didn't cover; locks the `_host_frame` reset).
- **Docs:** legacy `trace_report` fallback comments (now modern-`status`-only under no-back-compat) + the stale
  `_add_llm_data` comment (NEW path shares `llm_prompts`, safe via record-at-completion ordering). Deleted the
  concurrency reviewer's scratch probe file.
- **Left untested (judged acceptable):** 2-deep OLD-path (sub-wf→batch→sub-wf) — clause-2 (buffer
  `is_run_scoped=False`) is independently sufficient and the ADR-0008 checkpoint + reasoning cover it.

**Manual e2e (the braindump's "verification you can reproduce").** The chained `uv run pflow` readback
subprocesses STALLED (exactly the env issue the braindump warned about — not a pflow bug; the real `pflow run`
itself exited 0 and wrote the trace). Did it the recommended way instead: ONE in-process driver (real engine →
`save_to_file` flat-emit → `load_trace_file` reconstruct → real `generate_report`). Green:
`greet`(seq0,parent None) · `call-child`(seq1 reserved-at-descent, parent None) · `child-greet`(seq2,
parent_id=1, ancestor=[call-child]); reconstruct re-nests `child-greet` under `call-child`;
`tree()==reconstruct(disk)`; `generate_report` reads it back into a `summary.md`. `nodes_executed=2` (top-level
only). Confirms producer → flat JSONL → reconstruct → report end-to-end on a real sub-workflow.

**State:** Phases 1+2 complete, reviewed, gap-closed. Full suite **8014 passed**, `make check` clean. Step 3
(streaming: per-event flush, inline blobs, two-pass reconstruct, crash-tail, dead-end re-flush) remains.

---

## 2026-06-22 — Step 3 COMPLETE: per-event streaming (Pieces 4+5+5.4) + 4-specialist review

**Result:** full suite **8023 passed / 0 failed**; `make check` clean (ruff + ruff-format + mypy "no issues in
236 source files" + deptry); in-process e2e green. Baseline delta (captured pre-change): `pytest -m trace_files`
**170→174**, named set **557→565**, full suite **8014→8023** — **0 regressions** (all deltas are new step-3
tests). 4-specialist code review (silent-failures, impact-completeness, test-fidelity, feature-interactions)
found **no Critical/High** — only the suggestions folded in below.

**What changed (the producer streams; the reader gains two-pass + crash-tail):**
- **`core/trace_io.py`** — `_RESERVED_LINE_KEYS` += `ancestor_path`/`port` (stripped on read); `_partition_trace_lines`
  swapped the plural `blobs` arm for a singular `blob` arm (and now RAISES on a `blob` line missing
  `md5`/`value` — corruption stays a visible `JSONDecodeError`, silent-failures finding); `_rebuild_event_tree`
  is **two-pass** (dedup-by-`id` last-wins + lenient **transitive** orphan-drop when `is_incomplete`);
  `reconstruct_trace_from_lines` threads `is_incomplete = not run_complete`; `load_trace_file` **tolerates a
  truncated final line** → `incomplete` (malformed earlier line still raises). New shared primitives
  `intern_event_leaves` + `_inline_blobs` give ONE on-disk blob representation (inline first-occurrence
  `blob` lines, backward-only) across the streaming writer AND the whole-file writers (`flatten_trace_to_lines` /
  `emit_flat_events_to_lines` refactored to `_inline_blobs`; `blobs` trailer removed everywhere).
- **`runtime/workflow_trace.py`** — `__init__(stream_to_disk=...)` + streaming state (`_stream`/`_stream_path`/
  `_declared_blobs`/`_finalized`); `_open_stream` (lazy, meta-first, the single pytest-gate target),
  `_flush_event`/`_flush_line`/`_emit_blob_line`, `_meta_line`/`_meta_fields`/`_aggregates`, `finalize()`
  (run.complete trailer + close, idempotent), `__del__` (defensive close). `record_node_execution` flushes each
  event after append; `mark_last_event_failed` **re-flushes** the corrected line; `save_to_file` dispatches
  (run-scoped→`finalize`, buffer→whole-file `flatten`); filename timestamp moved save-time→`self.start_time`.
- **Gate wiring:** `runner.py` passes `stream_to_disk=config.trace_enabled`; `mcp_server/.../execution_service.py`
  both `run()` sites pass `trace_enabled=False`; `cli/commands/run.py::_save_trace_file` → `finalize()`;
  `tests/conftest.py` no-ops `_open_stream` (in addition to `save_to_file`) for non-`trace_files` tests.
- **Tests:** new reader tests (inline-blob, dedup-last-wins, transitive-orphan, complete-orphan-raises,
  crash-tail tolerate) replacing the two now-inverted A–C tests; new streaming tests (incremental-flush-then-
  finalize, finalize-idempotent, dead-end re-flush, shared-blob-declared-once, both gates); `test_filename_format`
  rewritten to `start_time`. **Docs:** refreshed the canonical format references (`runtime/CLAUDE.md`,
  `prompt_cache_analysis/CLAUDE.md`, the MCP agent `jq` example) — `blobs` trailer → inline `blob` lines,
  streaming/crash-tail now shipped (were "deferred Phase D").

**Decisions / deviations (with reasoning):**
- **Flatten KEPT, blob representation UNIFIED (deviation from Piece 4's "remove flatten").** `flatten_trace_to_lines`
  is the A–C round-trip oracle in `test_trace_io.py` AND the buffer/test whole-file writer across 9 files —
  removing it guts real coverage and forces migrating every bare-collector save. Instead I unified the *on-disk
  blob representation* to inline `blob` lines via one shared `_inline_blobs`/`intern_event_leaves` (used by both
  streaming and whole-file), achieving the plan's "one representation" intent (one reader arm, one disk shape)
  without the churn. The braindump explicitly flagged this as a conscious choice (keep-dual vs remove-and-migrate).
- **MCP `trace_enabled=False` (deviation from "no MCP changes needed").** Pre-flight VERIFIED MCP persists no
  trace today (no `save_to_file`/`finalize` call; `WorkflowTraceCollector` has no `trace_path` attr, so the MCP
  error-path `hasattr(..., "trace_path")` is always False). MCP free-rides on the `trace_enabled=True` default,
  so WITHOUT this flag the new streaming would start writing MCP traces to `~/.pflow/debug` → unintended
  `--only`/analyze-cache snapshot sources (a regression). Setting `trace_enabled=False` is behavior-preserving
  AND closes that latent regression — and makes `trace_enabled` the single coherent "persist this trace" gate
  (CLI=True/`--report`-forced, MCP=False, `--no-trace`=False). The impact reviewer independently confirmed.
  **Discovered (pre-existing, OUT OF SCOPE):** `mcp_server/CLAUDE.md` + `execution_tools.py` docstring claim MCP
  "traces always saved" — wrong before this diff (MCP never saved); flagged, not fixed (a separate cleanup).
- **Two-layer gate.** `stream_to_disk` (production: CLI yes / MCP+`--no-trace` no) + the conftest `_open_stream`
  no-op (tests: non-`trace_files` no). The conftest must gate `_open_stream` (not just `save_to_file`) because
  streaming now happens DURING `record_node_execution`, not at an end-of-run save — the braindump's "I/O timing
  reveals things" made concrete.
- **`save_to_file()` kept as a run-scoped→`finalize()` delegator.** The CLI calls `finalize()` directly (plan),
  but delegation means the existing `@trace_files` equivalence tests that call `collector.save_to_file()` keep
  working unchanged (events already streamed during the run; `save_to_file`→`finalize` just caps the trailer).
- **Self-audit added `__del__`** (defensive stream close) for the streamed-but-never-`finalize`d handle-leak case
  (a `trace_files` test that runs a workflow but never saves) — production always finalizes via the CLI.

**Review findings folded in (all 4 specialists, no Critical/High):**
- *test-fidelity (real):* the transitive-orphan test asserted only top-level node_ids → couldn't distinguish a
  clean transitive drop from a silently re-homed node (mutation-confirmed). Strengthened to the full-structure
  assertion `trace["nodes"] == [{"node_id": "top"}]` + "child"/"grandchild" absent anywhere; renamed honestly.
- *test-fidelity (gap):* added `test_streaming_blob_shared_across_events_declared_once` — the streaming cross-flush
  `_declared_blobs` dedup (distinct from the whole-file within-call dedup; never-run path).
- *silent-failures (take-or-leave → applied):* `_partition_trace_lines` now raises on a `blob` line missing
  `md5`/`value` instead of silently skipping (which would leave a later event's `$pflow_blob` ref unresolved).
- *impact-completeness (docs):* refreshed the stale format docs (above).
- *Verified clean by the panel:* the new shared file handle is **main-thread-only** by the SAME `__index__`/
  `is_run_scoped` routing gate that protects no-lock `seq` (workers route to `stream_to_disk=False` buffers →
  `_flush_event` no-ops); gate correct both directions; dead-end re-flush wins via dedup; crash-tail scoped to
  the final line + incomplete traces only; `finalize`/`__del__` robust against double-call/partial-construction;
  JSON-mode `json_output` correctly rides the `finalize()` trailer.

**Manual e2e (in-process driver, the reproducible verification):** real engine (shell sub-workflow with a >1KB
payload) → STREAMED JSONL (`['meta','event','blob','blob','event','event','run.complete']`) → both blob lines
precede their ref (backward-only) → child `big` nests under `call-child` via emit-time `parent_id`/`ancestor_path`
→ `load_trace_file` reconstructs (blobs resolved, `ancestor_path`/`port` stripped, `tree()==reconstruct`) →
`generate_report` reads it back. `nodes_executed=2` (top-level only).

**Per-event flush PERFORMANCE on a big run not measured** (don't pre-optimize; batched-flush-with-periodic-fsync
is the lever if needed). The MCP "traces always saved" doc/code mismatch is pre-existing and left for a separate
cleanup.

---

## 2026-06-22 — Step 3: `/deep-review` round (5 specialists) + fixes

Ran the user-requested `/deep-review` (5 agents: concurrency-safety, simplicity, test-fidelity, silent-failures,
impact-completeness) on the full step-3 diff after the manual 4-agent round, focused on the post-round fixes.
**No Critical/High.** Also ran the one verification not yet done: `make test-e2e` = **43 passed**.

**Confirmed findings + fixes (all applied; suite 8024 green, `make check` clean, e2e green):**
- **(simplicity) Deleted `emit_flat_events_to_lines`.** It had NO production caller after streaming (run-scoped
  saves stream; buffer saves use `flatten_trace_to_lines`) and near-duplicated `flatten`. Its one test (the
  host-after-ascend canary) was **re-pointed at the real streaming path** (`stream_to_disk=True` → `finalize()`
  → `load_trace_file`), which is *stronger* — it now pins the reconstruct-survives invariant on-disk through the
  production writer instead of a hand-built emit. This reverses my step-3 self-audit "keep it" call; the fresh
  reviewer's deletion-test framing (a third writer no production path calls) was decisive. Removed ~24 LOC, one
  fewer writer (minimal set is now `flatten` for buffer/nested + the streaming path).
- **(test-fidelity + silent-failures, 2 reviewers converged) Added `test_reconstruct_blob_line_missing_value_raises`.**
  The blob-arm raise (the prior round's own fix) was the last unguarded corruption arm with no regression pin —
  an unexercised guard is itself a silent-failure risk. Closes it (mirrors `test_reconstruct_unknown_kind_raises`).
- **(impact-completeness, 2 Warnings) Refreshed 2 stale `blobs`-trailer claims my first doc sweep missed:**
  `runtime/CLAUDE.md:133` (the 2.5.0 bullet's "save_to_file calls intern_blobs … blobs trailer" — now false) and
  the `workflow_trace.py` class docstring ("2.5.0 on disk … top-level blobs trailer"). Plus the `TRACE_FORMAT_VERSION`
  comment, the `substitute_refs` "future JSONL reader" wording, and my own Task 172 CLAUDE.md bullet (which still
  named the now-deleted `emit_flat`).
- **(concurrency, cheap hardening) Added `_assert_owner_thread()` to `_flush_event`.** Makes the no-lock invariant
  LOCAL: a future caller that flushes the run collector off the main thread fails loud rather than racing silently
  (no-op for buffer collectors — owner is None). Aligns with the Piece-1 loud-guard philosophy.

**Verified clean by the panel (cross-corroborated):** the new shared file handle (`_stream`) is **main-thread-only
by the SAME `__index__`/`is_run_scoped` gate that protects no-lock `seq`** — concurrency-safety could not construct
a worker→run-collector-stream path and confirmed it with the empirical `len(collector.events)==1` parallel-batch
test; `__del__` is shutdown-safe and the streamed handle is never shared cross-thread; the crash-tail tolerance and
the blob-arm raise are structurally disjoint (truncated tail = invalid JSON dropped pre-partition; the raise only
fires on valid-JSON-missing-field lines no writer emits); the strengthened transitive-orphan test now discriminates
the re-home mutations (mutation-confirmed); the `_aggregates`/`_meta_fields` factoring, the two intern walks,
`__del__`, and the flush asymmetry all survive the deletion test; `finalize()` mid-write failure reconstructs as
`incomplete`, never silent success.

**Final verification:** `pytest -m trace_files` **176**, full `make test` **8024**, `make test-e2e` **43**,
`make check` clean (mypy 236 files), in-process e2e green. **0 regressions** vs the captured baseline.

**State: Step 3 COMPLETE — producer done, reviewed (manual 4 + deep-review 5), gap-closed, committed.** This
producer is the dependency for Task 169 (SSE transport) and Task 173 (live overlay consumer).

---

## 2026-06-22 — Step 3 follow-up: consumer verification + MCP doc accuracy

User asked the "fully happy / loose ends" probe. Closed the residuals concretely (suite 8025 green, `make check`
clean):
- **Measured per-event flush overhead = 8.9 µs/event** (17.8 ms for 2000 nodes). It's `file.flush()` to the OS
  page cache, NOT `os.fsync`, so it's negligible for any real run. Closes the "unmeasured performance" residual.
- **Verified ALL debug-trace consumers read a real STREAMED trace** (the user's "have we verified all works?").
  Enumerated every `load_trace_file` consumer: `generate_report` (`pflow report`/`--report`), the shared
  `_iter_workflow_traces` autoload (analyze-cache **and** the `--only` snapshot loader), and full `analyze()`.
  Found the gap: the analyze-cache unit tests all hand-build *legacy single-object* JSON, so analyze-cache on a
  *streamed* trace was unverified. Added `test_streamed_trace_is_read_by_all_disk_consumers` (real LLM run →
  streamed trace → drives `generate_report` + `_iter_workflow_traces` + `load_full_run_events` + `analyze(auto_load_trace=True)`,
  asserting each consumes the streamed file). `--only` is *also* already covered by `test_only_snapshot.py`'s
  `@trace_files` real-run tests (they now read streamed snapshots). All consumers verified.
- **Fixed 3 agent-facing MCP docs** that claimed MCP execute saves a trace (it never did, and Task 172 makes it
  explicit via `trace_enabled=False`; ADR-0008 locks streaming as CLI-only v1): `execution_tools.py`
  (`workflow_execute` tool docstring — LLM-facing), `mcp_server/CLAUDE.md`, and `mcp-agent-instructions.md`. Left
  the `instruction_resources.py` "can access trace files" lines (those describe filesystem-access capability —
  true for full-access agents reading CLI-written traces — not an MCP-saves claim).
- **Verified the test gate is airtight (the "tests shouldn't save files" question):** non-`trace_files` tests
  write nothing (conftest no-ops `save_to_file` + `_open_stream`; pinned by `test_non_trace_files_run_does_not_stream_to_disk`);
  `@trace_files` tests intentionally write to **isolated tmp homes** (their purpose — testing the on-disk format
  round-trip). Confirmed the real `~/.pflow/debug` count is unchanged (1138→1138) across the heaviest streaming
  test files — zero real-dir pollution.
