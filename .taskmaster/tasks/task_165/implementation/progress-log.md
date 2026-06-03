# Issue 382 Implementation Progress

## Phase 1 - Interning core

Implemented `src/pflow/core/trace_io.py` with a pure disk-boundary trace transform:
`intern_blobs`, `resolve_blobs`, and `load_trace_file`. The walk is shape-agnostic over dict/list
containers, interns only large string leaves, preserves reserved `__` subtrees inline, emits a
top-level `blobs` trailer, and resolves back to the original in-memory shape with the trailer
removed.

Key decisions and observations:
- The purity invariant is load-bearing because future wiring will pass live event dicts into the
  dumper. Tests assert that even traces with no interned leaves get rebuilt containers instead of
  aliasing input subcontainers.
- `resolve_blobs` removes only the top-level `blobs` trailer. A nested user key named `blobs` must
  survive resolution; this was caught during review of the first pass and covered with a regression
  test.
- Malformed traces degrade conservatively: no `blobs` map, a non-dict map, missing blob hashes, or
  non-string blob values do not crash resolution. Missing/non-string refs stay as refs.
- Deviation from plan: the plan asked for `# noqa: S324` on the md5 call. Current Ruff config treats
  that suppression as unused when `usedforsecurity=False` is present, so the implementation keeps
  `usedforsecurity=False` and omits the stale `noqa`. This preserves the security intent without
  carrying a lint suppression the toolchain rejects/removes.

Verification:
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff check src/pflow/core/trace_io.py tests/test_core/test_trace_io.py`
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_trace_io.py -q` -> `10 passed`
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m mypy src/pflow/core/trace_io.py` -> success

Stopped after Phase 1 as requested. No runtime trace writer/reader wiring, format bump, or LLM
canonicalization has been implemented yet.

## Phase 2 - Wire interning at trace write/read seams

Wired `intern_blobs` into `WorkflowTraceCollector.save_to_file` after trace assembly and before
`json.dump`, preserving the invariant that live `collector.events` remain plain resolved content.
Bumped `TRACE_FORMAT_VERSION` to `2.5.0` and updated the nearby changelog comment to name the new
`blobs`/`$pflow_blob` disk shape plus the planned canonical LLM prompt/system shape for this format.

Routed the three trace-content readers through `load_trace_file`:
- `_iter_workflow_traces` in `runtime/workflow_trace.py`, preserving the existing corrupt-file
  skip wrapper around JSON/OSError failures.
- `_load_trace_explicit` in `core/prompt_cache_analysis/trace_loading.py`.
- `generate_report` in `core/trace_report.py`.

Key decisions and observations:
- `load_trace_file` now resolves only dict-shaped JSON and returns non-dict parsed JSON unchanged
  for caller validation. This preserves the old behavior where `_iter_workflow_traces` could skip
  non-dict candidates and `_load_trace_explicit` could produce its existing "missing
  format_version" validation error. The plan typed `load_trace_file` as returning `dict[str, Any]`;
  widening it to `Any` is deliberate compatibility, not scope expansion.
- Dry-run `--only` coverage uses cache-key parity: a cached target depending on a large interned
  upstream output remains `cached` only if the planner seeds resolved content before template
  resolution. If a raw blob ref leaked, the target command would hash differently and the plan would
  report `execute`.
- The stale comment claiming LLM nodes do not write `prompt` to shared was corrected; `LLMNode.post`
  does write it, while the trace hook remains the preferred non-batch capture path.
- No Phase 3 canonical stripping was implemented yet. The version comment mentions that final 2.5.0
  contract because Phase 2 owns the format bump, but current Phase 2 runtime traces still include
  the redundant LLM copies until Phase 3.

Verification:
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff check ...` over all modified source
  and test files -> passed.
- Focused Phase 2 pytest command covering trace_io, writer, snapshot, dry-run `--only`, version pin,
  report, analyze-cache explicit, and corrupt autoload/listing paths -> `19 passed`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_runtime/test_workflow_trace.py tests/test_runtime/test_only_snapshot.py tests/test_runtime/test_trace_format_2_2.py -q` -> `117 passed`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_trace_report.py tests/test_core/test_cache_analysis_trace_listing.py ... -q` -> `203 passed`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m mypy src/pflow/core/trace_io.py src/pflow/runtime/workflow_trace.py src/pflow/core/trace_report.py src/pflow/core/prompt_cache_analysis/trace_loading.py` -> success.

Stopped after Phase 2 as requested. Phase 3 canonical LLM prompt/system stripping has not been
started.

## Phase 3 - Canonical LLM prompt/system trace shape

Implemented the LLM trace-shape canonicalization for parent events and direct batch item events.
LLM prompt content now lives in `llm_prompt`; effective system content lives in `llm_system`.
Redundant LLM copies are stripped from `node_output.prompt`, `node_output.system`,
`template_resolutions.prompt`, `template_resolutions.system`, and `node_params.prompt`.
`node_params.system` is intentionally kept so reports can still show the configured system line,
distinct from the effective/cached system.

Implementation details:
- Added `is_llm_node_type(node_type_name)` in `runtime/engine/instrumentation.py` and made the
  existing `_should_write_cache_metadata` delegate to it. This keeps behavior identical
  (`LLMNode` only) while giving trace-shape code a name that matches what it is deciding.
- Parent `WorkflowTraceCollector.record_node_execution` strips only after `_add_llm_data` has
  promoted prompt/system from the live node output or trace hook. This preserves promotion order.
- Batch `_capture_item_trace` now receives `node_type_name` from all three call sites and strips
  only when it is `LLMNode`.
- Batch `template_resolutions` are copied before stripping for LLM items. This is load-bearing:
  `last_resolutions` is a caller-owned object, and mutating it in place would corrupt other
  attribution/debug data. A direct regression test verifies the original dict still carries
  `prompt`, `system`, and unrelated keys after capture.
- To keep final code simple enough for local standards, the batch item logic was split into
  `_template_resolutions_for_item_trace`, `_promote_item_llm_data`, and
  `_strip_redundant_item_llm_fields` instead of suppressing Ruff's complexity warning.

Tests added/extended:
- Parent unit coverage for exact LLM strip asymmetry and non-LLM `prompt`/`system` preservation.
- Engine-produced LLM event coverage with mock adapter: `llm_prompt`/`llm_system` present,
  redundant prompt/system copies absent, and `node_params.system` kept.
- Parallel batch LLM coverage: each item keeps its canonical `llm_prompt`; item
  `node_output`/`template_resolutions` no longer carry prompt/system copies.
- Direct batch aliasing regression for `_capture_item_trace`.

Verification:
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_runtime/test_workflow_trace.py tests/test_runtime/test_trace_integration.py tests/test_core/test_trace_report.py -q` -> `296 passed`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_trace_io.py tests/test_runtime/test_trace_format_2_2.py tests/test_runtime/test_only_snapshot.py -q` -> `43 passed`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m mypy src/pflow/runtime/workflow_trace.py src/pflow/runtime/engine/batch_executor.py src/pflow/runtime/engine/instrumentation.py` -> success.
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff check ...` over all modified files
  from Phases 1-3 -> passed.

Stopped after Phase 3 as requested. Phase 4 cache-block prompt capture has not been started.

## Phase 4 Handoff - Cache-block prompt capture

Current invariants from Phases 1-3:
- Blob interning is disk-only. Runtime event trees and all reader outputs are resolved/plain content.
- `load_trace_file` is the read seam for trace content. It resolves dict-shaped traces and returns
  non-dict JSON unchanged so existing callers can reject/skip with their own validation.
- LLM events are canonical: rendered user prompt is `llm_prompt`; effective system is
  `llm_system`. Redundant LLM `prompt`/`system` copies are stripped from `node_output` and
  `template_resolutions`; `node_params.prompt` is stripped; `node_params.system` is kept.
- Batch LLM item canonicalization already copies `template_resolutions` before stripping, so
  `last_resolutions` is not mutated.

Phase 4 implementation targets:
- `src/pflow/nodes/llm/llm.py`: in `LLMNode.post`, mirror `prep_res["user_message_blocks"]` into
  `shared["user_message_blocks"]` when it is a list, next to the existing `system_blocks` seam.
  Keep the existing flat `shared["prompt"]` write.
- `src/pflow/runtime/engine/batch_executor.py`: update `_capture_item_trace` so `llm_prompt` is
  written by one explicit blocks-or-flat path. Remove `("prompt", "llm_prompt")` from the generic
  promotion loop, prefer `node_output["user_message_blocks"]` when it is a list, otherwise fall back
  to flat `node_output["prompt"]`, then remove `user_message_blocks` from stored `node_output`.
- `src/pflow/core/trace_report.py`: extract the existing str-or-blocks body renderer from
  `_format_cached_system` and use it for both `## Cached System` and the `## Prompt` fallback branch
  that reads `event["llm_prompt"]`. This must cover both top-level node files and per-batch-item
  report files because both flow through `_format_resolutions`.

Phase 4 hazards to verify while coding:
- Promotion order matters. If the old `("prompt", "llm_prompt")` loop entry remains after blocks
  are assigned, it can clobber block-shaped prompts back to flat strings.
- `user_message_blocks` must not remain in stored `node_output`, or it becomes another duplicate
  copy in the trace.
- Warmup items stay unchanged by plan: they only carry `llm_prompt: "Reply with: OK"` and do not
  contain the shared static prefix.
- Degraded/non-prewarm path must continue to use flat `str` `llm_prompt`.
- Renderer must handle `str | list[dict]`; without this, joining report lines can fail when
  `llm_prompt` is block-shaped.

Suggested rereads before Phase 4 implementation:
- `src/pflow/nodes/llm/llm.py` around `LLMNode.post` and `system_blocks` handling.
- `src/pflow/runtime/engine/batch_executor.py` around `_capture_item_trace` after Phase 3 changes.
- `src/pflow/core/trace_report.py` around `_format_cached_system` and `_format_resolutions`.
- `tests/test_runtime/test_batch_prewarm.py` and relevant report tests for prewarm/report coverage.

Suggested Phase 4 tests:
- Prewarm batch with at least two real items and a large shared static prefix: each real item's
  `llm_prompt` is `list[dict]`; the shared prefix block text interns to one shared blob across
  items after save; per-item suffixes remain distinct.
- Degraded/no-block path: item `llm_prompt` remains flat `str` and canonical stripping still holds.
- Report rendering: block-shaped `llm_prompt` renders fenced JSON for both the top-level node file
  path and the per-batch-item file path; flat prompt output remains unchanged.

Known-good sandbox commands:
- Use `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest ...`, not `uv run` or
  `make test`, in this sandbox.
- Recent successful guards: trace/report/integration focused suites passed after Phase 3; rerun the
  affected subset plus new Phase 4 tests before proceeding to Phase 5.

## Phase 4 - Cache-block prompt capture

Implemented block-shaped prompt capture for prewarm batch LLM items. `LLMNode.post` now mirrors
`prep_res["user_message_blocks"]` into shared when prep built cache-rendered user blocks, while
keeping the existing flat `shared["prompt"]` and effective `shared["system"]` seams. Batch item trace
promotion now has a single `llm_prompt` writer: prefer `node_output["user_message_blocks"]` when it
is a list, otherwise fall back to the flat rendered prompt. The stored `node_output` copy drops
`user_message_blocks` along with the redundant prompt/system fields, so the trace keeps one
canonical prompt copy per LLM item.

Updated report rendering by extracting the existing str-or-blocks body renderer from
`## Cached System` and reusing it for the `llm_prompt` fallback branch. This covers both top-level
node files and per-batch-item report files because both flow through `_format_resolutions`.

Key decisions and observations:
- The batch promotion order is load-bearing. Removing the generic `("prompt", "llm_prompt")`
  promotion entry prevents a flat prompt from clobbering the block-shaped prompt after blocks are
  detected.
- The promoted blocks intentionally share the live per-item list by reference until trace
  sanitization/interning. This is safe because downstream trace code rebuilds rather than mutates;
  the code comment records that boundary.
- Warmup items were left unchanged per plan. They still carry only `llm_prompt: "Reply with: OK"`
  and do not contain the shared static prefix, so there was no duplication to remove.
- Non-batch capture and the LLM adapter were not touched. The only producer change is `LLMNode.post`
  exposing data already produced by prep for batch trace capture.
- Loose-end note: `_capture_item_trace` still invokes `_promote_item_llm_data` for any dict-shaped
  `node_output`, matching the inherited Phase 3 shape. Phase 4 kept that scope to avoid an
  unrelated behavior change, but if this area is tightened later the cleaner contract is likely to
  gate the whole LLM promotion helper on `is_llm_event`; today only LLM nodes are expected to emit
  `response`/`system`/`user_message_blocks` in this shape.
- Deviation from plan: adding the extra `post()` branch tripped Ruff C901, so the prompt/system
  trace mirroring was extracted into `_mirror_rendered_trace_inputs`. This is behavior-identical and
  improves the final code shape instead of suppressing the complexity warning.

Tests added/extended:
- Node-level prewarm test now asserts `shared["user_message_blocks"]` mirrors the adapter blocks.
- Engine prewarm batch test asserts real batch items carry `llm_prompt` as blocks, stored
  `node_output` has no duplicate block/flat prompt copy, and interning collapses the shared static
  prefix block to one blob across items.
- Direct `_capture_item_trace` test pins blocks-over-flat precedence and duplicate cleanup.
- Report tests assert block-shaped `llm_prompt` renders fenced JSON for both top-level node files
  and per-batch-item files.

Verification:
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_nodes/test_llm/test_batch_cache_prefix.py tests/test_runtime/test_trace_integration.py tests/test_core/test_trace_report.py -q` -> `233 passed`
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_runtime/test_batch_prewarm.py tests/test_core/test_trace_io.py tests/test_runtime/test_workflow_trace.py -q` -> `120 passed`
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest <5 new/changed focused tests> -q` -> `5 passed`
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff check ...` over Phase 4 source/tests -> passed
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m mypy src/pflow/nodes/llm/llm.py src/pflow/runtime/engine/batch_executor.py src/pflow/core/trace_report.py` -> success

Stopped after Phase 4 as requested. Phase 5 fixture regeneration, full-suite/check validation, Task
159 baseline classification, and runtime documentation updates have not been started.

## Post-Phase 4 adversarial CLI verification

Ran manual CLI verification after Phase 4 using `pflow --help`, `pflow guide core`, and relevant
guide topics (`llm batch prompt-caching shell code file`) as the operating surface. Used
`HOME=/private/tmp/...` per the sandbox-testing skill so traces/reports stayed out of the real home.

Manual artifacts created:
- `scratchpads/issue-382-shrink-trace-interning/manual-local-trace.pflow.md`
- `scratchpads/issue-382-shrink-trace-interning/manual-llm-prewarm.pflow.md`
- `scratchpads/issue-382-shrink-trace-interning/manual-llm-block-trace.json`

What was verified:
- Local executable workflow (`shell` → parallel batch `code` → `code` → `write-file`) completed via
  the real pflow CLI with `--report --output-format json`.
- The written trace had `format_version=2.5.0`, `blobs` as the last top-level key, 5 blobs, and raw
  `$pflow_blob` refs.
- `load_trace_file` resolved the same trace back to plain content: no `blobs` key, no `$pflow_blob`
  refs, `process-each.batch_items` length 3, first item prefix length 3900, and summary
  `names=blue, green, red; doubled_total=12; prefix_len=3900`.
- The exact repeated 3900-byte prefix was stored once as one blob and referenced 17 times, proving
  real CLI trace writing deduped nested repeated leaves.
- Explicit `pflow report <trace>` rendered full plaintext content and no `$pflow_blob` refs.
- `pflow --only summarize --output-format json` seeded upstream data from the interned trace and
  produced the expected summary without executing upstream nodes.
- `pflow --dry-run --only summarize` used the same interned-trace snapshot seam without surfacing
  refs.
- Synthetic 2.5 LLM block trace through real `pflow report` rendered block-shaped `llm_prompt` as
  fenced JSON in both per-item and regular node files; regular node file also rendered block-shaped
  `llm_system` under `## Cached System`. No `$pflow_blob` refs leaked into report files.
- LLM prewarm workflow validated and dry-ran with a fake `ANTHROPIC_API_KEY`; `analyze-cache
  --no-trace-autoload` completed. The workflow was not executed because this sandbox has no real or
  offline LLM provider configured.

Issues/limits found during verification:
- Initial full-suite context run produced 4 failures, all subprocess tests invoking
  `/opt/homebrew/bin/uv` and panicking before Python/pflow ran. The sandbox-testing skill already
  documented this class, but its known-exclusion list is stale by one additional uv-subprocess test
  (`test_importing_helper_module_does_not_import_litellm`). Adjusted near-full run excluding those
  uv failures passed: `7507 passed, 19 skipped`.
- The first local workflow draft used `python` in a shell node; sandbox PATH did not provide it.
  Fixed the manual workflow to call `.venv/bin/python`.
- One early LLM dry-run returned `'str' object has no attribute 'get'` because I ran it in parallel
  with a command deleting the same `HOME`. Serial rerun with isolated home succeeded; not a product
  finding.
- The local workflow emits an existing validator warning for nested access on shell stdout
  (`${build-source.stdout.items}`) even though the runtime stdout is valid JSON and the workflow
  succeeds. This is useful noise to know about, but not introduced by trace interning.

Verification commands/results:
- Initial near-full context suite -> 4 uv-subprocess sandbox failures, `7507 passed, 19 skipped`.
- Adjusted near-full suite excluding uv-subprocess sandbox failures ->
  `7507 passed, 19 skipped`.
- `ruff check` over changed source/tests -> passed.
- `mypy` over changed source modules -> success.
