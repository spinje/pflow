# Task 133 — Implementation Progress Log

> **What this is:** the *journey* of building the streamable-trace foundation — decisions made during
> the build, deviations from the plan, surprises, bugs. Not a restatement of the plan.
> **What this is NOT:** the *why/what* → `task-133.md`; the *how* (phases, spike resolutions, file:line)
> → `implementation/implementation-plan.md`; the decision → `context/adr/0007-...`.

## Meta-state (2026-06)

Building **Phases A–C only** — the *transport + correlation* layer (flat JSONL, `run_id`/`parent_id`/
`seq`, reconstruct-to-dict). This is the **schema-independent, overlay-proof** subset: the live overlay
(the eventual consumer) can only *extend* this layer additively, never invalidate it. **Phase D
(liveness/incremental append) and the D1 span taxonomy are deliberately NOT built** — they need the
overlay as their validator (spike #4). Nothing user-visible changes; the reconstruct-to-dict reader
keeps every existing consumer byte-identical.

Spikes #1 (reader map), #2 (no-lock `seq`, VERIFIED + invariant), #3 (flush perf, RESOLVED) are
closed. #4 deferred by design; #5 trivial/deferred.

## Build log

### Phase A — extract `substitute_refs` ✅ (2026-06)
Pulled the inlined substitution `walk` out of `resolve_blobs` into a module-level
`substitute_refs(obj, blob_map)` in `core/trace_io.py` (the extraction #382 deliberately YAGNI'd, per
the old `trace_io.py:100-101` note). Behavior-preserving: `resolve_blobs` now builds the map from the
`blobs` trailer and delegates. The future JSONL reader (Phase C) will build the map from inline
first-occurrence declarations and call the same function.
- **Gate:** `tests/test_core/test_trace_io.py` 11/11 pass; ruff + mypy clean.
- No surprises. Pure refactor.

### DEVIATION (design pivot, before coding B/C) — collector unification is NOT in A–C
Reading the actual engine (`engine.run` save/restore, `record_trace` embed chain, the batch drain)
flipped Phase B's scope. The original plan put **collector unification** (one collector across
sub-workflows, `parent_id` instead of embedding, threading `run_id` through `engine.run`) in Phase B.
That surgery is **only needed for Phase D (liveness/incremental write)** — *not* for the flat-format
transport. The in-memory collector already builds a correctly ordered nested tree, so all correlation
(`seq`/`parent_id`/`run_id`/`id`) is **derivable from that tree at save time**. So A–C became a
**disk-boundary serialization transform** touching only `trace_io.py` + `save_to_file` + fixtures —
**zero engine changes**. Self-reviewed for loose ends; user-confirmed three decisions: (1) granularity
= flatten node+sub-workflow events to lines, batch items inline; (2) **D-stable** format = aggregates
in a `run.complete` trailer now (the one bit of D pulled forward); (3) keep `.json` extension. Plan §3
rewritten to match. **Next: independent plan review (3 reviewers) before writing B/C.**

### Plan review (review-plan + impact-completeness + silent-failures) — DONE; plan revised
17 confirmed findings, 0 disputed — the review paid off. Folded into plan §3/§5:
- **Discriminator was fragile** → positive `pflow_trace` marker on the meta line; **keep
  `format_version` 2.5.0** (transport sniffed, not versioned — Decision 1; kills the version-pin churn).
- **`json_output` would be dropped** → generic top-level fold (`meta ∪ run.complete == all top-level keys`).
- **`id` must be `seq`, never `node_id`** (loop revisits / cross-subworkflow collisions); group on `(id, parent_id)`.
- **Sub-workflow-inside-a-batch (`batch_items[].events`)** → batch items + everything nested stay INLINE;
  only top-level `sub_workflow_events` promote.
- **Trailer-absent ≠ success** (fix `... or "success"` at `workflow_trace.py:215`, `trace_loading.py:225`);
  **malformed → raise `JSONDecodeError`** (preserve the 3 callers' degrade); **orphan `parent_id` → raise**.
- **Strip ONLY the 4 correlation fields**; preserve `node_output._pflow_child_workflow_paths`.
- **Scope correction:** NOT 3 files — ~7 test files read raw traces and must migrate; +docs; +new
  round-trip/regression tests. Bigger than "~2 days"; user accepted the larger scope.
- Decisions locked: keep 2.5.0 + marker · raise-on-corrupt / reject-on-incomplete · proceed at larger scope.

### Phase B — flatten core landed (writer logic) ✅, save_to_file NOT yet flipped
`trace_io.flatten_trace_to_lines(trace_data) -> list[dict]` implemented as a **pure** function (DFS
pre-order `seq`=`id`; generic meta/`run.complete` fold so `json_output` can't drop; sub-workflow
events promoted to lines; batch items + their nested `events` stay inline; interning over the flat
structure → `blobs` trailer line; `pflow_trace: "jsonl/1"` marker). Deliberately did NOT wire
`save_to_file` yet — that flip is atomic with the Phase C reader, so the suite stays green and the
B/C checkpoint can review the flatten logic first.
- **Gate met:** new `test_flatten_trace_to_lines_contract` + existing → `test_trace_io.py` 12/12;
  ruff + mypy clean. Contract covered: DFS order, parent chains, loop-recovery distinct ids, batch
  inline (incl. nested `events`), generic fold (json_output), interning, input purity.
### B/C `/code-review` checkpoint (silent-failures + impact-completeness + test-fidelity) — DONE
Verdict: writer logic **correct & invertible** (silent-failures LOW risk; `seq` monotonic/gap-free with
`parent<child`; impact-completeness verified every producer shape incl. warmup `index:-1` and
batch-nested-deeper by direct execution; test-fidelity: gate sound, not hollow). 0 disputed. Applied:
- **Reserved-key collision guard** in the flatten walk — `line.update` would silently clobber an event
  key named `kind`/`id`/`seq`/`parent_id`/`run_id`; now raises `ValueError` at the producing seam (safe
  today, but spike #5 OTel `kind` / Phase D span-ids would have silently violated it).
- **`only_node` → `_META_KEYS`** (knowable-at-start + snapshot-filter key); `final_status` stays a trailer aggregate.
- **Gate strengthened** (the #19 thin-fixture fix): rich-event passthrough (exact key-set) assertion +
  warmup item + both-channels event + recursive/deep nesting + batch-nested-buried + empty-trace +
  collision-raises + `default=str` leaf + interning round-trip. → `test_trace_io.py` 15/15; ruff+mypy clean.
- **Plan text:** `kind` added to Phase C strip list (was missing — finding S1); `only_node` meta note.

- **Next:** Phase C — `load_trace_file` marker detection + reconstruction (strip the 5 line keys,
  trailer-absent=incomplete, malformed→`JSONDecodeError`, orphan→raise), atomic `save_to_file` flip,
  raw-file test migration (~7 files), fixture/doc updates, full transparency-oracle gate.

### Phase C — reconstruct-to-dict reader + atomic writer flip — ✅ DONE
Implemented as one atomic change (writer flip + reader land together so the suite goes green in one push):
- **Writer flip:** `WorkflowTraceCollector.save_to_file` now writes JSONL via `flatten_trace_to_lines`
  (was `json.dump(intern_blobs(...), indent=2)`). `TRACE_FORMAT_VERSION` stays `2.5.0` (content
  unchanged; transport identified by the `pflow_trace: "jsonl/1"` marker).
- **Reader:** `load_trace_file` detects the marker on the first line → reconstructs via
  `reconstruct_trace_from_lines` / `_partition_trace_lines` / `_rebuild_event_tree` (split out to clear
  `C901`). Strips the 5 line keys (incl. `kind`); orphan `parent_id` / unknown kind / missing meta →
  `JSONDecodeError`; trailer-absent crash-tail → `final_status="incomplete"`; resolves blobs via
  `substitute_refs`; legacy single-object traces still load (dual-read, marker absent → old path).
- **Status fix:** `trace_loading._collect_candidate_traces` bucket routing → `successful if status in
  ("success","degraded") else failed`, so an `incomplete` crash-tail is non-reusable (and
  `load_full_run_events` already rejects it). Old absent-`final_status` traces still default to success.
- **Test migration:** ~40 raw `json.load(trace_file)` reads → `load_trace_file` across **7** test files
  (the 5 planned + `test_metrics_integration.py` ×3 and `test_cache_analysis_token_estimation.py` ×1 —
  the two the impact/test-fidelity reviewers caught that my first sweep missed). No assertions weakened;
  the on-disk interning test was *rewritten* (not deleted) to assert the JSONL shape.
- **Docs:** `mcp-agent-instructions.md` (jq/JSONL note), `runtime/CLAUDE.md` (JSONL-transport bullet),
  `prompt_cache_analysis/CLAUDE.md` (Runtime Trace Contract note).

**Phase C `/code-review` (silent-failures + impact-completeness + test-fidelity) — DONE, all addressed:**
- silent-failures: **LOW risk, 0 actionable** — empirically tested ~25 edge cases; reader airtight,
  `incomplete` propagation correct both directions, no production-reachable silent failure.
- impact-completeness + test-fidelity (independently): the **4 missed `trace_files` tests** → migrated;
  test-fidelity suggestion → added a disk-seam malformed-JSONL test (`load_trace_file` raises
  `JSONDecodeError`). Migration confirmed high-fidelity (byte-identical assertions, real fixtures).

**Verification (the "fully happy" bar):** full suite **7769 passed, 1 skipped** · `test_trace_io.py`
22/22 · `pytest -m trace_files` 162/162 · ruff + mypy clean on all changed files · **real-CLI e2e**:
`pflow examples/batch-test.pflow.md` + `parent-with-sub` wrote valid JSONL on disk (meta+marker,
correlated event lines, batch_items inline, sub-workflow events promoted, `run.complete`+`blobs`
trailers); `pflow report`/`analyze-cache` read them back via reconstruction.

## A–C COMPLETE — status & what's next
**Phases A, B, C are done and green.** pflow's trace is now a flat, greppable, **D-stable JSONL** log on
disk, reconstructed transparently for every existing reader; nothing user-visible changed. **Nothing is
committed** (user commits). **Deferred to Phase D (with the live overlay):** collector unification +
incremental/streaming append (`seq` at emit time, the no-lock main-thread design), inline-first-occurrence
blobs, and the D1 span taxonomy — none built; the on-disk format A–C established does not change, only
*when* correlation is assigned. The `run.complete` trailer is already in place, so Task 164 inherits its
graceful-vs-crash discriminator for free.

## Critical learnings & gotchas (carry these — costly to re-derive)

1. **To find EVERY test affected by a trace-shape change, run `uv run pytest -m trace_files` — not a
   hand-picked file list.** `WorkflowTraceCollector.save_to_file` is a **no-op under pytest** except in
   `@pytest.mark.trace_files` tests (autouse `disable_trace_file_writes_by_default`, `tests/conftest.py`).
   So a format change only breaks trace_files-marked tests (+ real subprocess e2e). My first migration
   sweep ran a curated file list and **missed 2 files** (`test_metrics_integration.py`,
   `test_cache_analysis_token_estimation.py`); the impact/test-fidelity reviewers caught them. `pytest -m
   trace_files` is the authoritative migration oracle (it was exactly 162 pass + the 4 misses).

2. **`incomplete` status is set in the RECONSTRUCTION, deliberately NOT by changing the readers'
   `... or "success"` default.** That default is load-bearing back-compat: legitimate pre-2.x / synthetic
   traces have no `final_status` and must read as `"success"`. A crash-tail NEW trace (no `run.complete`
   line) is distinguished by `reconstruct_trace_from_lines` setting `final_status="incomplete"` (guard:
   `if not run_complete` — *absent* trailer line vs *present-but-empty* one). Do NOT "simplify" the
   readers to treat absent==not-success; it would silently break every legacy trace. (Found by the
   silent-failures reviewer; the naive fix at `load_full_run_events:215` / `trace_loading.py:225` was the
   trap.)

3. **Round-trip identity holds only modulo `default=str`.** `save_to_file` dumps with
   `json.dump(..., default=str)`, so a `Path`/`datetime`/`set` leaf is stringified on write (lossy,
   one-way). `reconstruct(flatten(x)) == x` is byte-exact only for JSON-native data — the round-trip test
   uses a JSON-native fixture; the non-native-leaf test only asserts flatten *doesn't choke* and the leaf
   survives flatten (the coercion is `json.dump`'s job at write). Don't assert byte-exact round-trip on
   arbitrary production `node_output`/batch `item` data.

4. **Spike #2's no-lock global `seq` is NOT exercised by A–C.** A–C assigns `seq` single-threaded at save
   time (one DFS walk over the already-materialized tree), so the "no lock needed because all appends are
   main-thread" design is **unvalidated in production** — it only becomes load-bearing at Phase D
   (emit-time assignment under the batch `ThreadPoolExecutor`). Re-verify it, plus the reserved-key
   invariant below, when building Phase D.

5. **The reserved-key guard (`_RESERVED_LINE_KEYS` in `trace_io.py`) is a forward-safety tripwire, not
   dead code.** It raises `ValueError` (caught fail-loud at `run.py:148` → `trace_file=None`) if a
   producer ever emits a top-level event key named `kind`/`id`/`seq`/`parent_id`/`run_id`. It can't fire
   today (the producer's event key set is closed and disjoint) — its whole purpose is to make a FUTURE
   change (OTel `kind` alignment, Phase D span ids, or the LLM trace hook materializing an event from its
   worker thread) fail loud at the seam instead of silently clobbering data. Keep it.

6. **`verify.sh` (Task 159 baseline) was NOT used.** It's a pre-drifted read-path oracle (runs under
   `env -i`, no API key) and the 7769-test suite + real-CLI e2e gave stronger coverage. A future
   trace-shape change *can* use it as a read-path cross-check, but must first reconcile its pre-existing
   drift (a separate main-branch task — do not regenerate `expected-*.txt` as part of a feature PR).

> **For the Phase D agent:** the buildable contract + invariants are in `implementation-plan.md` §3
> ("Deferred to Phase D") and §6 (Risks). One-line summary: the **on-disk JSONL format is fixed — don't
> change it**; Phase D changes *when* correlation is assigned (save→emit), *how* events are collected
> (per-sub-workflow collectors → one run-scoped collector via the `engine.run` save/restore +
> `WorkflowExecutor` change — the invasive piece, untouched by A–C), and blob placement (trailer →
> inline-first-occurrence for live tailing). The D1 span taxonomy stays unpinned until the overlay
> validates it.
