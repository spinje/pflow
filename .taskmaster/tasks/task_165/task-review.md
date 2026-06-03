# Task 165 Review: Shrink the Trace — Per-Run Interning + Canonical LLM Prompt/System (issue #382)

## Metadata
- **Implementation Date:** 2026-06-03
- **Format version:** trace `2.4.0 → 2.5.0`
- **PR:** _pending (`/create-pr`)_
- **Provenance of this review:** authored by the agent that designed the implementation plan and ran
  the multi-agent code review + adversarial verification (read every staged diff, ran the suites,
  measured the size win, dissected the baseline behavior). The code itself was written by a separate
  implementing agent; the "as-built" facts below are **verified against the staged diff and tests**,
  and the implementer's own decisions/deviations come from `implementation/progress-log.md`. Treat any
  claim here as verified-by-review, not author-recollection.

## Executive Summary

Workflow traces (100MB+) are shrunk losslessly by (A) per-run **content interning** at the disk
boundary, (B) **canonicalizing** each LLM event's prompt/system into one field each, and (C) capturing
prewarm-batch prompts as **cache blocks** so the shared prefix dedupes. A real 9.44 MB fixture interns
to 6.32 MB (33%, round-trip identical); a real CLI run collapsed a shared prefix from 17 copies to 1.
The on-disk format is non-additive (it removes fields) but fully backward-readable.

## What Was Built (and where it diverged from the plan)

Faithful to the plan across Phases 1–5. Verified deviations (all sound):

- **`load_trace_file` returns `Any`, not `dict[str, Any]`.** Deliberate: it resolves dict-shaped JSON
  and returns non-dict JSON **unchanged**, so the three callers keep their own validation
  (`isinstance(data, dict)` / "missing format_version"). Widening the type is compatibility, not scope.
- **No `# noqa: S324` on the md5 call.** The plan specified it; it's **wrong** — Ruff does not flag
  `hashlib.md5(..., usedforsecurity=False)`, so the suppression would itself trip `RUF100`. (Correct
  the plan if reused.)
- **Three helper extractions to satisfy Ruff C901 instead of suppressing it:**
  `_template_resolutions_for_item_trace`, `_promote_item_llm_data`, `_strip_redundant_item_llm_fields`
  (batch_executor) and `_mirror_rendered_trace_inputs` (llm.py `post`). These improved the final shape.
- **`is_llm_node_type(node_type_name)` added** to `instrumentation.py` with `_should_write_cache_metadata`
  delegating to it (the plan recommended this rename-for-intent; the gate logic is identical, `== "LLMNode"`).
- **The `("prompt","llm_prompt")` entry was removed from the batch promotion loop** — without this, the
  generic loop would clobber the block-shaped `llm_prompt` back to a flat string. This was a
  plan-review-flagged hazard; the fix is in place and tested.

## Files & their load-bearing role

### Core
- `src/pflow/core/trace_io.py` **(new, pure, stdlib-only)** — `intern_blobs` / `resolve_blobs` /
  `load_trace_file`. **Must stay in `core/`**: `core/trace_report.py` imports it, and the layering is
  strictly `runtime → core`; moving it into `runtime/workflow_trace.py` would create a cycle.
- `src/pflow/runtime/workflow_trace.py` — version bump; `intern_blobs` in `save_to_file` (the single
  write seam); `_iter_workflow_traces` routed through `load_trace_file` (preserving the corrupt-file
  `try/except`); `_strip_redundant_llm_trace_fields` for parent LLM events (after `_add_llm_data`).
- `src/pflow/runtime/engine/batch_executor.py` — `_capture_item_trace` now takes `node_type_name`
  (threaded from 3 call sites), is the **single blocks-or-flat writer** of `llm_prompt`, and strips
  per-item LLM copies (copying `template_resolutions` first).
- `src/pflow/core/trace_report.py` — `generate_report` through `load_trace_file`; `_append_str_or_blocks`
  extracted and reused by **both** `## Cached System` and the `## Prompt` `elif llm_prompt` branch.
- `src/pflow/nodes/llm/llm.py` — `_mirror_rendered_trace_inputs` adds `shared["user_message_blocks"]`
  next to the existing `shared["prompt"]`/`["system"]` seams.
- `src/pflow/runtime/engine/instrumentation.py` — `is_llm_node_type` gate.

## Integration Points & Dangerous Edges (the landmine map)

A naive edit to any of these reintroduces a real bug — each has a guarding test:

1. **`intern_blobs` purity is load-bearing.** `save_to_file` sets `trace_data["nodes"] = self.events`
   — the dump tree **aliases the live event dicts**. The walk must rebuild a new container at every
   level (no "no large leaf → return same sub-dict" short-circuit) and use a **fresh** blob
   accumulator (never a mutable default arg). Guard: `test_intern_blobs_does_not_mutate_or_alias_input_containers`.
2. **`str`-leaf-only interning is load-bearing.** `resolve_blobs` substitutes the *same* `blobs[h]`
   object into N positions — safe only because strings are immutable. Do not extend interning to
   dict/list blobs without revisiting this.
3. **Strip ordering.** Strip the redundant copies **after** the `llm_prompt`/`llm_system` promotion,
   which reads the **live** store (parent: `self.llm_prompts` + the `node_output` arg; batch: local
   `node_output`). Reorder and promotion breaks.
4. **Batch `template_resolutions` is a caller-owned reference** (`item_event["template_resolutions"] =
   last_resolutions`, no copy — unlike the parent path's sanitize-copy). Strip via copy-then-filter,
   never in place. Guard: `test_llm_batch_item_trace_strips_without_mutating_last_resolutions`.
5. **The kept `if "prompt" in resolutions` branch in `_format_resolutions` is the backward-compat
   seam.** Old traces (which still carry `template_resolutions.prompt`) render through it; removing it
   breaks old-trace rendering AND non-LLM nodes that happen to have a `prompt` param.
6. **Single read seam.** Any new code that reads a trace from disk MUST go through `load_trace_file`,
   or it sees raw `{"$pflow_blob": …}` refs. There are exactly **three** content readers today.
7. **`node_params.system` must stay** (feeds the `## System` config line); only `node_params.prompt`
   is dead-and-stripped.
8. **Top-level `"blobs"` is now reserved** — `intern_blobs` overwrites any pre-existing one. (Nested
   user `blobs` keys survive; guard: `test_resolve_removes_only_top_level_blob_trailer`.)

### Shared Store Keys
- `shared["user_message_blocks"]` — **new** capture seam written by `LLMNode.post` (prewarm batch
  only; a `list[dict]`). NOT `__`-prefixed (so interning processes it); read by `_capture_item_trace`,
  then popped from the stored `node_output` so it isn't a duplicate copy. Mirrors the pre-existing
  `shared["prompt"]` / `shared["system"]` trace-capture seams.

## Patterns Established (reuse these)

- **Disk-encoding-only transform at the I/O boundary.** Pure `intern`/`resolve`, one write seam
  (`save_to_file`), one read seam (`load_trace_file`); in-memory is *always* plain content. This is
  also the **single migration seam** for the deferred jsonl/streaming format (Task 133) — swap a jsonl
  parser behind `load_trace_file` and the `substitute_refs` walk is unchanged.
- **Union-tolerant readers for format evolution.** The format bump removes fields, yet nothing broke
  because readers *prefer canonical, fall back to legacy* and **require neither**. This is the general
  recipe for evolving the trace shape without a migration: change the producer, leave the reader a
  superset. Do not make a reader require the new shape.
- **Producer-side, node-aware strip — never a generic-mechanism filter.** Canonicalization lives at
  the LLM-event recording layer gated on `is_llm_node_type`; the generic template resolver and the
  interning walk stay dumb. A magic-string `key == "prompt"` filter in the resolver would wrongly hit
  a shell/code node's `prompt` param — explicitly avoided.

## Test Wisdom (which tests catch real bugs vs. coverage)

- `test_intern_blobs_does_not_mutate_or_alias_input_containers` — the **aliasing/purity** regression
  (the subtle one; a mutation-only test misses it).
- `test_llm_batch_item_trace_strips_without_mutating_last_resolutions` — the caller-owned-reference
  aliasing hazard.
- `test_prewarm_batch_items_capture_user_message_blocks_for_interning` — **real engine run** (not a
  hand-built fixture) proving (C) end-to-end: items get block prompts → shared prefix interns to one
  blob (17→1). This is the test that proves the feature's purpose.
- `test_each_batch_item_llm_captures_own_rendered_prompt` — batch-seam guard; doubles as the
  **degraded/flat-`llm_prompt`** path (non-prewarm batch).
- `test_resolve_removes_only_top_level_blob_trailer` + `test_malformed_blob_map_degrades_to_noop` —
  the nested-`blobs` and malformed-map edges.
- `TestTraceFixtureBuilderShapeParity` + the committed-fixture drift guard — confirm the producer shape
  and the committed cache-analysis fixtures didn't drift (they're already in the canonical shape).

## Gotchas & Discoveries (will save a future agent hours)

- **The Task 159 baseline `verify.sh` is pre-drifted on this branch — NOT by #382.** It runs each case
  under `env -i` (no API key) and diffs `analyze-cache`/`report` output against committed `expected-*.txt`.
  On this branch ~10/11 cases in surface `03` "drift" — but so do the **static greenfield** cases,
  which read no trace at all and #382 cannot touch. Root cause: the committed expected predates an
  unrelated `analyze-cache` "Missing API key" blocking-errors change (came in via main). The
  trace-reading cases drift **identically** (same missing-key block) with no shape/blobs drift, proving
  #382 is **transparent**. **Do NOT regenerate `expected-*.txt` in this PR** — that conflates an
  unrelated change with #382 and bakes the no-key state into the baseline. Baseline staleness is a
  separate main-branch maintenance task.
- The full suite shows **4 "failures" that are environmental** — `uv`-subprocess sandbox panics, not
  product. Excluding them: 7507 passed, 19 skipped.
- **`_promote_item_llm_data` runs for any dict-shaped `node_output`, not gated on `is_llm_event`** (the
  strip *is* gated). This matches pre-existing behavior (the old promotion loop was also ungated), so
  no regression, but it's a known loose end: a future tidy-up would gate the whole promotion helper.

## Breaking / Behavioral Changes

- **Format 2.5.0 is non-additive** (removes the redundant LLM copies). All consumers gate on
  `format_version.startswith("2.")` and ship together; old code reading a *new* trace would see raw
  refs, but there are no external/persisted old readers.
- **The raw prompt *template* (`${…}`) is no longer in the trace JSON for LLM events** (it lived in the
  now-stripped `node_params.prompt` / `template_resolutions.prompt.template`). It was never *rendered*
  in `--report`, and resolved per-item prompts remain — but an agent grepping raw JSON won't see the
  template structure (it's in the `.pflow.md` source).
- **`--only` can no longer re-seed `${node.prompt}`/`${node.system}`** (canonical in `llm_prompt`/
  `llm_system`; live runs unaffected — `post` still writes `shared["prompt"]`). No workflow uses this.

## AI Agent Guidance

### Quick start for related trace work
Read in order: `src/pflow/core/trace_io.py` (the whole encoding in ~100 lines), then the two strip
sites (`workflow_trace.record_node_execution`, `batch_executor._capture_item_trace`), then
`trace_report._format_resolutions` (the union-tolerant reader). The single mental model: **blobs exist
only on disk; the read seam resolves them; consumers always see plain, union-shaped content.**

### Common pitfalls
- Adding a trace reader that bypasses `load_trace_file` → raw refs leak.
- Editing the interning walk to short-circuit or use a mutable-default accumulator → purity/leak bug.
- "Simplifying" the batch `template_resolutions` strip to an in-place `pop` → mutates caller state.
- Running `verify.sh` and treating its drift as a #382 regression → it's pre-existing (see Gotchas).

### If you extend to jsonl/streaming (Task 133)
The placement of blobs changes (top-trailer → inline-first-occurrence) but the ref convention, the
content-hash, and the substitution walk are identical. Swap the parser behind `load_trace_file`; keep
the walk shape-agnostic (it already is).

---

*Generated from the design + review + verification context of Task 165 (issue #382).*
