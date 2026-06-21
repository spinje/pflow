# Task 133 Review: Trace/Cache Storage Architecture (decision + A–C JSONL transport)

## Metadata

- **Implemented:** A–C by a prior agent (2026-06); rebased onto main + design phase (ADR-0008 + D1) this
  session. Commit **`ad1c1958`** on `feat/unified-node-storage` (rebased onto main; PR pending).
- **Status:** DONE. A–C shipped (the transport); the deferred span-log is pinned as a DRAFT and split into
  **Tasks 172 (producer) / 169 (transport) / 173 (consumer)**.
- **Journey (not duplicated here):** `implementation/progress-log.md` (build log + the 6 gotchas + the
  Post-A–C section). This review is the durable forward-reference on top of it.
- **Calibration:** no external users, but **the test suite + the system's own behavior ARE the contract**
  (per root CLAUDE.md). So the load-bearing risk is "silently break a reader / the suite," not
  back-compat with outside consumers.

## Read First — the load-bearing block

- **What exists now:** the trace is a **flat JSONL** log on disk (one `meta` line, one `event` line per
  node, `run.complete` + `blobs` trailers), but **reconstructed to the byte-identical nested dict** every
  existing reader already expected. Correlation (`id`/`seq`/`parent_id`/`run_id`) is **derived at SAVE
  time** from the in-memory nested tree — *not* at emit time. Nothing user-visible changed.
- **Read these first** (symbols, not lines — line numbers drifted in the rebase, re-grep):
  - `core/trace_io.py` → `flatten_trace_to_lines`, `reconstruct_trace_from_lines`, `_rebuild_event_tree`,
    `substitute_refs`, `load_trace_file`, `_META_KEYS`, `_RESERVED_LINE_KEYS`, marker `"jsonl/1"`.
  - `runtime/workflow_trace.py` → `WorkflowTraceCollector`, `save_to_file`, `record_node_execution`.
  - For Phase D: `context/adr/0008-live-execution-overlay.md` + `design/d1-event-schema.md`.
- **Invariants that must NOT break:**
  - **The reconstruct contract.** `load_trace_file` → `TraceTree.from_dict` must keep producing the same
    nested dict. Break it → `report`, `analyze-cache`, and `--only` snapshot restore silently mis-read.
  - **`pytest -m trace_files` is the only oracle that sees format changes.** `save_to_file` is a **no-op
    under pytest** except in `@pytest.mark.trace_files` tests. A format change validated with a hand-picked
    file list will silently miss tests (it missed 4 in A–C).
  - **`incomplete` is set in reconstruction, never by changing the readers' `... or "success"` default.**
    That default is load-bearing back-compat for legacy/synthetic traces with no `final_status`. "Simplify"
    it and every legacy trace silently reads wrong.
  - **`_RESERVED_LINE_KEYS` is a fail-loud tripwire, not dead code.** Keep it — it makes a future producer
    that emits `kind`/`id`/`seq`/`parent_id`/`run_id` fail at the seam instead of clobbering data.

## What Was Built (actual vs. planned)

- **A–C is a disk-boundary serialization transform, NOT engine surgery.** The original plan put collector
  unification in Phase B; reading the actual engine (`engine.run` save/restore + the embed chain) flipped
  that to Phase D. So A–C touches only `trace_io.py` + `save_to_file` + fixtures/tests — **zero engine,
  zero hot-path, zero collector-lifecycle changes.** All correlation is *derived from the already-built
  nested tree at save time*.
- **Format is "D-stable":** the `run.complete` trailer was pulled forward so A–C's on-disk shape ==
  Phase D's eventual streaming shape (Task 164 inherits the graceful-vs-crash discriminator for free).
- **Format version stays `2.5.0`** — the JSONL transport is identified by the positive `pflow_trace`
  marker, *sniffed not versioned* (kills version-pin churn; the `== "2.5.0"` test stays green).
- **This session added the design layer:** ADR-0008 (architecture) + D1 schema (event contract); the
  deferred Phase D was split into Tasks 172/169/173. The implementation-plan's §3 Phase-D framing is now
  **superseded** by those (see the progress-log Post-A–C section).

## Patterns & Anti-Patterns

- **PATTERN — change the I/O boundary, keep the in-memory shape.** Reconstruct-to-dict at the single read
  seam (`load_trace_file`) kept ~22 consumers untouched (the ~2-day path vs. a ~2-week native-flat
  rewrite). Reuse this lever for any future trace format change.
- **PATTERN — positive format marker, not parse-inference.** Detect JSONL by the `pflow_trace` marker on
  line 1, not by "does the whole file parse as one JSON value." A review killed the parse-inference version
  as fragile. Dual-read: marker absent → the legacy `resolve_blobs` path.
- **PATTERN — generic top-level fold.** `meta ∪ run.complete == all of today's top-level keys`, derived
  from the built dict, never hand-enumerated — so a conditional key (`json_output`) can't silently drop.
- **ANTI-PATTERN — do not treat absent `final_status` as not-success** (breaks legacy traces; see invariant).
- **ANTI-PATTERN (Phase D) — do not keep the in-memory store nested.** ADR-0008 reverses an initial
  keep-nested lean: collector unification *naturally* produces a flat list; keeping it nested needs *new*
  re-nesting logic and leaves two shapes. Flat + a derived `tree()` (reusing `_rebuild_event_tree`) is the
  call. And **do not trust the implementation-plan's `file:line`** — stale after the rebase.

## Gotchas & Non-Obvious Coupling

The progress-log holds all 6 in full; the ones that bite *outside* A–C:

- **The metrics/cost path reads the LIVE collector, not the disk seam.** `result.trace` is the
  `WorkflowTraceCollector` object; the CLI+MCP cost summary calls `collect_llm_calls()` → builds a
  `TraceTree` over `self.events` and recurses `sub_workflow_events`. So "reconstruct keeps readers green"
  does **not** cover it. This is the single biggest Phase-D trap (the in-memory shape is its own blast
  radius). Same for `_collect_llm_summary` and `final_events_by_node`.
- **`final_events_by_node` keys by `node_id` over the flat *top-level* list and intentionally ignores
  nested children.** Safe today (children are nested). Under a flat in-memory store (Phase D) a child's
  `node_id` could overwrite a parent's → wrong `final_status`/`failed_node_ids`. It needs top-level
  scoping, not a recursive walk.
- **The `__pflow_prompt_cache__` save/restore sits beside `__trace_collector__` in `engine.run` and looks
  identical — but is semantically opposite** (intentionally per-workflow; NOT propagated). A refactor that
  "unifies the two parallel blocks" breaks cache scoping silently. Verified clean; leave it.
- **`default=str` in `save_to_file` is lossy one-way** (Path/datetime/set → str). Round-trip identity is
  byte-exact only for JSON-native data. Matters for any future faithful-restore need (Task 164 resume).
- **Rebase trap (this session):** removing an `import json` while main added json-using tests produced a
  conflict that `git` *and* `git merge-tree` reported as **clean** (semantic, not textual). Distrust
  "merge is clean" for trace-test files; run the suite.

## Integration Points

- **Read seam (singular):** `load_trace_file` — 3 content-callers (`workflow_trace._iter_workflow_traces`,
  `prompt_cache_analysis/trace_loading._load_trace_explicit`, `trace_report.generate_report`); everything
  else funnels through `TraceTree.from_dict`. Keeping this contract is what makes the transport swap safe.
- **In-memory consumers (NOT via disk — the Phase-D blast radius):** `collect_llm_calls` (CLI + MCP cost
  summary), `_collect_llm_summary` (the `llm_summary` trailer), `final_events_by_node`/`_determine_trace_status`
  (`failed_node_ids`, `final_status`). They read the live collector's `events`.
- **Contracts:** the on-disk JSONL line shape (`meta`/`event`/`run.complete`/`blobs`); `format_version`
  `2.5.0` + the `pflow_trace: "jsonl/1"` marker; the read-only **NodeId = (node_id, ancestor_path)** join
  contract (shared with Task 168 — neither side changes it unilaterally).
- **Docs reconciled:** `mcp-agent-instructions.md` (jq/JSONL), `runtime/CLAUDE.md`,
  `prompt_cache_analysis/CLAUDE.md`.

## Tests That Matter

- **`uv run pytest -m trace_files`** — the authoritative format oracle (162 at A–C, 164 post-rebase). Run
  this for *any* trace-shape change; a curated file list misses tests (`save_to_file` no-op otherwise).
- **`tests/test_core/test_trace_io.py`** — the flatten↔reconstruct round-trip + contract tests (DFS order,
  parent chains, loop-recovery distinct ids, batch inline, generic fold incl. `json_output`, interning,
  collision-raises, `default=str` leaf, malformed-JSONL → `JSONDecodeError`). This is the transparency
  oracle that proves transport changed but meaning didn't.
- **Phase-D gap (does NOT exist yet):** the round-trip oracle only proves `flatten`↔`reconstruct`
  self-consistency. Phase D changes the *producer* (save→emit), so it needs a **NEW live-engine → on-disk
  JSONL → existing-reader integration test** — the round-trip won't catch emit-path bugs.

## Extension Points (the deferred work)

- **Phase D = Task 172** (emit-time producer / collector unification), **Task 169** (SSE transport),
  **Task 173** (live overlay consumer). The contract is **ADR-0008 + `design/d1-event-schema.md`**; the
  tacit knowledge (reversals, traps, how-to-work-with-the-user) is in
  `task_172/starting-context/braindump-design-and-review-session.md`.
- The on-disk format A–C established **does not change** in Phase D — only *when* correlation is assigned
  (save→emit), *how* events are collected (one run-scoped collector), and blob placement (trailer →
  inline-first-occurrence). Spikes #1–3 are closed; re-verify the no-lock `seq` invariant against current
  code.

---
*Distilled from Task 133's implementation context. The chronological journey lives in
`implementation/progress-log.md`; this review is the durable forward-reference.*
