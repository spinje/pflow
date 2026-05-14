## 2026-05-14 — Runtime pre-dispatch strip for below-min cache markers

Closes the Gemini hard-failure footgun (`Cached content is too small. total_token_count=1135, min_total_token_count=2048`) reported in `scratchpads/pflow-caching-agent-ux-notes.md` issue #3 / GH #393.

### Problem

When `prompt_cache:` or `prewarm: true` is declared on an LLM node, the resolved cache content depends on dynamic data (CLI params, upstream LLM output, batch items). When the rendered content is below the provider's minimum, three bad things happened:

- **Gemini** rejected the call hard — workflow died after $-cost upstream work.
- **Anthropic** silently no-op'd the marker; user only learned post-call via 0/0 cache telemetry.
- The existing `_emit_observed_below_min_cache_warning` fires in `LLMNode.post()` *after* `exec()` returns — but `exec_res["status"] == "error"` triggers an early return before the warning point, so on the Gemini failure case the warning **never fired**.

### What was implemented

A pre-dispatch token check at the single seam `_assemble_cache_prep` (`src/pflow/nodes/llm/llm.py:507`). When cumulative tokens through any `cache_control`-bearing block are below `get_min_cache_tokens(model)`, the marker is stripped (`del block["cache_control"]`), the call goes out uncached, and a catalog-backed `cache.below-min-tokens` Diagnostic is emitted with new `evidence_kind="pre_dispatch"`.

**~80 LOC across 2 production files**:
- `src/pflow/nodes/llm/llm.py` — 3 helpers (`_count_text_tokens`, `_strip_below_min_cache_markers`, `_emit_pre_dispatch_below_min_warning`) + 9-line call into `_assemble_cache_prep`.
- `src/pflow/core/cache_analysis/warning_catalog.py` — new `_BELOW_MIN_TOKENS_MESSAGE_PRE_DISPATCH` template + entry in `_BELOW_MIN_TOKENS_DISPATCH`. No new catalog ID — extended existing `cache.below-min-tokens` with a third evidence tier.

### Why this shape

Verified by 4 parallel `pflow-codebase-searcher` runs before writing code:

1. **Thresholds are 100% hardcoded** in `llm_capabilities.py:68-91` — and they must stay that way. Empirically confirmed `litellm.model_cost` has no `min_cache_tokens` field; only `min`-containing keys are `supports_minimal_reasoning_effort` and `supports_native_streaming` (unrelated). Anthropic/Gemini don't expose minimums via SDK either. Hardcoded table is the top-10% pattern (mypy/ruff/rustc do the same for provider quirks that change quarterly).

2. **Single dispatch seam.** `_assemble_cache_prep` has exactly one production caller (`LLMNode.prep:797`). Both block-builders (system + user_message_blocks for batch prewarm) converge there. Model, provider, resolved bytes, shared store, and node_id are all in scope. No new architecture needed.

3. **DD#19 byte-identity preserved.** The memo hash (`compute_node_config(prompt_cache_content=...)`) runs in `plan_node._render_cache_for_hash` BEFORE dispatch. The strip mutates only the `cache_control` key on rendered blocks — text bytes are untouched, so memo cache_key is identical whether strip fires or not. Verified by `test_pre_dispatch_strip_does_not_mutate_text_bytes`.

4. **Observed-tier doesn't double-emit.** After strip, the provider sees no `cache_control` markers → returns no cache telemetry fields → `has_cache_telemetry=False` at `llm.py:193` → existing observed-tier emission correctly suppresses itself. Zero coordination logic needed.

### Edge cases handled

- **Per-batch-item**: `_assemble_cache_prep` is called per-call; heterogeneous batches (some items above min, some below) get correct per-item decisions with zero coupling.
- **Multiple markers** (system + user_prefix): cumulative-token walk evaluates each marker independently. Each provider cache scope is checked against the min.
- **Unknown model**: `get_min_cache_tokens` returns `CONSERVATIVE_FLOOR=4096`. Strips aggressively for unknown models — the right default.
- **`litellm.token_counter` raises**: falls back to `len(text) // 4`. The heuristic biases toward false-strip over false-keep (Gemini rejection), the cheaper error.
- **OpenAI**: `cache_control` is already a no-op there; stripping is also a no-op. `prompt_cache_key` kwargs stay (harmless).

### Testing

- **8 new production-shape tests** at `tests/test_nodes/test_llm/test_prompt_cache_below_min_runtime.py`: below-min strips, above-min keeps, exact-threshold boundary, Gemini 4096, unknown-model floor, observed-tier no-double-emit, heuristic fallback.
- **1 new catalog test** at `test_cache_analysis_warnings.py` for the `pre_dispatch` message template.
- **1 new hash-invariance test** at `test_prompt_cache_hash.py` proving the strip doesn't touch text bytes.
- **5 existing tests adjusted**: `test_prompt_cache_rendering.py`, `test_batch_cache_prefix.py`, `test_runner.py`, `test_no_cache_flag.py`, `test_trace_integration.py` got a one-line strip-bypass — their fixtures intentionally use tiny content for shape testing. Each adjustment documented inline pointing at the dedicated strip test file.

`make test` 6766 pass / 1 skip. `make check` clean (ruff, mypy 207 files, deptry).

### Baseline regeneration

All 82 baseline cases under `.taskmaster/tasks/task_159/baseline/` regenerated with **zero byte drift**. Structurally correct: every baseline case exercises `analyze-cache` / `report` / `visualize` / `guide` (static analysis or recorded traces) — none reach the runtime dispatch seam.

Added a `pre_dispatch` deferral note to the baseline README. A baseline case for the strip tier is the natural v1.x addition once trace 2.3.0 records `cache_skipped_reason` (the field that would let an `analyze-cache --from-trace` case observe the event).

### Key insights / learnings

1. **The dispatch seam matters more than provider abstraction.** Originally weighed a per-provider adapter pattern; rejected after the searcher confirmed all paths converge at `_assemble_cache_prep`. One seam means one check, no Provider/Capability protocol class, no new module — the change is additive within the existing data model.

2. **Hardcoded provider tables are not technical debt — they're the right shape for rare-change capability data.** The instinct to make it "dynamic" was wrong here: litellm doesn't expose the field, providers don't either, and "configurable via settings.json" would shift the bug from "we hardcoded the wrong value" to "the user hardcoded the wrong value."

3. **The catalog-as-SSoT pattern paid off.** Adding a third evidence_kind was a 3-line catalog change (template + dispatch entry). Zero new shared-store keys, zero new module, zero new catalog ID. The existing `make_diagnostic("cache.below-min-tokens", evidence_kind=...)` factory already validates required context at construction.

4. **Fail-open token counter, fail-closed threshold check.** When `litellm.token_counter` raises, fall back to chars/4 heuristic — that's fail-open for measurement. But the threshold comparison stays strict: below min → strip. The asymmetry is intentional: false-strip loses savings (cheap), false-keep produces a Gemini rejection (expensive).

5. **Pitfall #19 confirmed.** First test pass had a false negative: `test_above_min_keeps_cache_control_no_warning` failed because `MockLLMClient` default `cache_creation/read=0` made `has_cache_telemetry=True` fire the *observed* tier even when our strip didn't fire. Fixed by staging realistic telemetry. The bug-shaped-fixture trap is real even for tests testing my own new code.

### Closes / unblocks

- **Closes**: Scratchpad #3 (runtime prewarm hard-fail), GH #393 (runtime defense).
- **Unblocks**: Followups #4 (analyzer recommendation symmetry) — orthogonal but complementary fix; Scratchpad #19 (conditional warmup suggestion) — needs trace 2.3.0 field which is the natural next step now that the runtime detection exists.

### Files touched

Production:
- `src/pflow/nodes/llm/llm.py`
- `src/pflow/core/cache_analysis/warning_catalog.py`

Tests:
- `tests/test_nodes/test_llm/test_prompt_cache_below_min_runtime.py` (new)
- `tests/test_core/test_cache_analysis_warnings.py`
- `tests/test_runtime/test_prompt_cache_hash.py`
- `tests/test_nodes/test_llm/test_prompt_cache_rendering.py`
- `tests/test_nodes/test_llm/test_batch_cache_prefix.py`
- `tests/test_execution/test_runner.py`
- `tests/test_integration/test_no_cache_flag.py`
- `tests/test_runtime/test_trace_integration.py`

Docs:
- `.taskmaster/tasks/task_159/baseline/README.md` (`pre_dispatch` deferral note)

## 2026-05-14 — Follow-ups 2 start: separate provider prompt-cache evidence from local pflow memo reuse

Implemented the trace-analysis split between provider LLM calls and pflow-local cache hits. The analyzer now keeps two LLM-call views from trace data: a historical view that may descend into cached subtrees for token/cost estimation, and a provider-current-run view that does not treat cached memo/in-process events as provider calls. Summary telemetry now records provider call count, provider cache read/write tokens, local memo hits, local in-process hits, and historical input tokens skipped by local reuse.

Critical learning: cached trace events can preserve historical `llm_call` payloads, including `cache_read_input_tokens`, but those payloads are not proof that provider prompt caching happened in the current run. A resumed pflow run may skip the LLM call before the provider sees anything. Any user-facing "provider cache" number must come from current provider events only; historical cached-event payloads are valid for estimates, not for current provider-cache evidence.

Renderer changes make that distinction explicit in text and JSON. Text output now labels actual deltas as including local cache reuse when applicable, adds a "Local pflow cache reuse" line, reports "Provider cache in this run" separately, and tells agents to rerun with `--no-cache` when they need a clean provider prompt-cache measurement.

Tests added coverage for memo-hit traces that previously would have counted historical provider cache reads, plus renderer/JSON shape coverage for the new summary fields. Regenerated staged baselines for `03-analyze-cache-modes/07-autoload-prefers-success`, `08-autoload-failed-only`, and `09-autoload-rejected-names-file`; each was verified individually with `verify.sh`.
