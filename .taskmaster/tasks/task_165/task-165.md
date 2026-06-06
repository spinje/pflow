# Task 165: Shrink the Trace — Per-Run Interning + Canonical LLM Prompt/System (issue #382)

## Description

Workflow traces (`~/.pflow/debug/workflow-trace-*.json`) reach 100MB+ from duplicated content. This
shrinks them losslessly via per-run content interning and by canonicalizing each LLM event's prompt
and system into a single field, while keeping the trace a plaintext, agent-searchable debug artifact.
On-disk trace format bumps `2.4.0 → 2.5.0`.

> **Artifact split (each has one job):** this file = *why/what/decisions*.
> `implementation/implementation-plan.md` = the detailed *how* (phases, file:line insertion points,
> edge cases, Definition of Done §13). `implementation/progress-log.md` = the chronological build
> record + adversarial verification. Read this first, then the plan for execution detail.

## Status

done

## Completed

2026-06-04

## Priority

medium

## Problem

The observed pain is a 100MB+ trace file. The bulk is **duplicated content** on two axes:

1. **Cross-event / cross-tier flow** — a node's generated content reappears byte-identical in every
   downstream node's inputs, prompts, and resolutions, across batch items and nested sub-workflows.
2. **Within-event redundancy** — each LLM event stored the same resolved prompt in **3–4 fields**
   (`llm_prompt`, `node_output.prompt`, `template_resolutions.prompt.resolved`, `node_params.prompt`)
   and the same effective system in 2–3 fields.

Hard constraint: the trace must stay **searchable** — agents grep/`jq` it while debugging (Task 108:
full content, no truncation). So compression is ruled out.

## Solution

Three complementary changes, all on the **current end-dumped JSON tree** (no span/streaming redesign
— that is deferred to Task 133):

- **(A) Per-run content interning** — at dump time, large string leaves (≥ ~1 KB) become
  content-addressed refs `{"$pflow_blob": "<hash>"}`; the unique content is stored once in a
  top-level `blobs` trailer; resolved back at load time. Disk-encoding only — in-memory is always
  plain content.
- **(B) Canonical LLM prompt/system** ("honest event model") — an LLM event surfaces the rendered
  prompt in **one** field (`llm_prompt`, `str | list[dict]`) and the effective system in
  `llm_system`; the redundant copies are stripped.
- **(C) Cache-block prompt capture** — for a prewarm batch, each item's user prompt is captured as
  the cache-rendered **blocks** the API received, so the byte-identical shared static-prefix block
  dedupes to **one** blob under interning.

## Design Decisions

The strategic *why-this-shape* choices (implementation-level locks — sentinel name, trailer
placement, md5, empty-blobs convention, the LLM-node gate helper — live in the plan's §3 to avoid
repeating them here):

- **Interning over gzip/compression.** Searchability is load-bearing; compression makes the file
  opaque. This single constraint picks interning.
- **Per-run interning, not a global cross-run blob store.** Self-contained (delete the trace → blobs
  go), portable, trivial GC, reversible. The global store stays gated on *observed* cross-run dedup
  need (Task 133).
- **Canonical single field (Option 2), not "leave the copies and just intern them."** We chose to
  *remove* the redundant prompt/system copies, not just dedupe them on disk, because the repetition
  itself hurts code legibility and a single canonical field makes the future typed-trace contract
  (Task 133 / #370) cleaner. Net: capability up, distinct code paths down.
- **The strip is producer-only and node-aware.** Interning stays a dumb, shape-agnostic leaf-walk
  that knows nothing about prompts; canonicalization happens at the LLM-event recording layer (gated
  on the node type), never as a magic-string filter in the generic template resolver.
- **(C) is batch-only.** Prewarm is gated on batch, so `user_message_blocks` never exists off the
  batch path — the non-batch capture path and the LLM adapter are untouched.
- **Backward-compatibility by construction.** `resolve_blobs` no-ops on traces with no `blobs` map;
  readers are union-tolerant (prefer canonical fields, fall back to legacy); the version gate is a
  `startswith("2.")` prefix. Old traces read/render identically — verified.
- **`node_params.system` kept, `node_params.prompt` stripped.** System's raw config feeds the
  `## System` report line (distinct from the effective `llm_system`); `node_params.prompt` had zero
  readers (dead).

## Dependencies

- **Task 159 (Prompt Caching)** — provides the cache-rendered blocks that (C) captures and that
  (B)'s `llm_system` already uses; `prep_res["user_message_blocks"]` / `system_blocks` are its output.
- **Task 133 (Trace/Cache Storage Architecture)** — the decision record that scoped #382 as the
  observed-disk now-work and deferred the streaming span-model.

## Requirements

Properties the implementation must satisfy (testable; grouped by area).

### Interning (A)
- Large string leaves (≥ `INTERN_MIN_BYTES`) become `{"$pflow_blob": hash}` refs; unique content is
  stored once in a top-level `blobs` trailer (last key).
- `intern_blobs` is **pure** — it rebuilds every container and never mutates the live event dicts
  (`trace_data["nodes"]` aliases `collector.events`). Interns `str` leaves only; never interns the
  value under a reserved `__`-prefixed key.
- `resolve_blobs(intern_blobs(t))` is byte-identical to `t`; `resolve_blobs` is a no-op when there is
  no `blobs` map and degrades (no crash) on a malformed one.
- All trace-content reads route through a single seam (`load_trace_file`); no consumer ever sees a
  raw ref.

### Canonical LLM shape (B)
- An LLM event carries the rendered prompt only in `llm_prompt` and the effective system only in
  `llm_system`.
- `prompt`/`system` are stripped from `node_output` and `template_resolutions`; `node_params.prompt`
  is stripped; `node_params.system` is kept.
- Stripping is node-aware (LLM nodes only), happens **after** promotion, and the batch path copies
  `template_resolutions` before stripping (it is a caller-owned reference).

### Cache-block capture (C)
- Prewarm batch items capture `llm_prompt` as `list[dict]` blocks; the shared static-prefix block
  dedupes to one blob; the degraded path (no blocks built) falls back to a flat `str`.

### Compatibility
- Pre-2.5.0 traces read and render identically; `--only` seeding, `--report`, and `analyze-cache`
  are unaffected.
- Accepted caveat: an `--only` snapshot can no longer re-seed `${node.prompt}`/`${node.system}`
  (canonical in `llm_prompt`/`llm_system`; live runs unaffected — `post` still writes
  `shared["prompt"]`).

## Implementation Notes

- New pure, stdlib-only module **`src/pflow/core/trace_io.py`** holds `intern_blobs` /
  `resolve_blobs` / `load_trace_file` — placed in `core/` so the three readers (one in `runtime/`,
  two in `core/`) import it with no `runtime → core` cycle.
- Strip sites: `record_node_execution` (parent) and `_capture_item_trace` (batch), gated on
  `is_llm_node_type` (added to `engine/instrumentation.py`, with `_should_write_cache_metadata`
  delegating to it).
- **Plan deviation found during implementation:** the plan's `# noqa: S324` on the md5 call is
  unneeded — Ruff does not flag md5 when `usedforsecurity=False` is passed, so the suppression would
  itself be flagged `RUF100`. Omitted. (Correct the plan if it is reused.)
- Detailed phases, exact insertion lines, edge cases, and the acceptance checklist are in
  `implementation/implementation-plan.md`.

## Verification

Measured and confirmed (full detail in `implementation/progress-log.md`):

- **Lossless size win:** the committed 9.44 MB `live-gemini-lyrics-generator.trace.json` interns to
  **6.32 MB (33% / 3.1 MB smaller)**, round-trip byte-identical, 383 blobs. This is a *lower bound* —
  it is an already-hand-minimized fixture and interning alone; a raw production trace shrinks more
  (canonicalization + interning subsume the old hand-minimizer).
- **(C) dedup, real CLI run:** a shared static prefix went from **17 inline copies to 1 blob**;
  resolution, `--only` seeding, and report rendering all correct on a real 2.5.0 trace.
- **Backward-compat:** reading committed old-format trace fixtures produces byte-identical
  analyze-cache/report output (interning transparent after resolve).
- **Suite:** 7507 tests pass (the 4 excluded are environmental `uv`-subprocess sandbox failures, not
  product); ruff + mypy clean.
- Acceptance criteria checklist: `implementation/implementation-plan.md` §13 (Definition of Done).

Out of scope / not blockers: the Task 159 baseline `verify.sh` is pre-drifted on this branch by an
unrelated `analyze-cache` change (proven — static greenfield cases drift; #382 is transparent), so do
NOT regenerate its `expected-*.txt` here. Peak-memory reduction and the streaming/jsonl span model
are explicitly deferred.

## References

- GitHub issue **#382** (the source spec; note: it had 3 factual errors the plan corrects).
- `implementation/implementation-plan.md` — phased how + Definition of Done.
- `implementation/progress-log.md` — chronological build record + adversarial CLI verification.
- **Task 133** — trace/cache storage architecture decision record (scoped #382; deferred streaming).
- **Task 159** — prompt caching (source of the cache blocks; `BASELINE-AUDIT.md` L-8 filed this).
- Key source: `src/pflow/core/trace_io.py`, `src/pflow/runtime/workflow_trace.py`,
  `src/pflow/runtime/engine/batch_executor.py`, `src/pflow/runtime/engine/instrumentation.py`,
  `src/pflow/core/trace_report.py`, `src/pflow/nodes/llm/llm.py`,
  `src/pflow/core/prompt_cache_analysis/trace_loading.py`.
