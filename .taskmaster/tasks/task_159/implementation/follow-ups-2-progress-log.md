## 2026-05-14 — Runtime pre-dispatch strip for below-min cache markers

Closes the Gemini hard-failure footgun (`Cached content is too small. total_token_count=1135, min_total_token_count=2048`) reported in `scratchpads/pflow-caching-agent-ux-notes.md` issue #3 / GH #393.

### Problem

When `prompt_cache:` or `prewarm: true` is declared on an LLM node, the resolved cache content depends on dynamic data (CLI params, upstream LLM output, batch items). When the rendered content is below the provider's minimum, three bad things happened:

- **Gemini** rejected the call hard — workflow died after $-cost upstream work.
- **Anthropic** silently no-op'd the marker; user only learned post-call via 0/0 cache telemetry.
- The existing `_emit_observed_below_min_cache_warning` fires in `LLMNode.post()` *after* `exec()` returns — but `exec_res["status"] == "error"` triggers an early return before the warning point, so on the Gemini failure case the warning **never fired**.

### What was implemented

A pre-dispatch token check at the single seam `_assemble_cache_prep` (`src/pflow/nodes/llm/llm.py:507`). When cumulative tokens through any `cache_control`-bearing block are below `get_min_cache_tokens(model)`, the marker is stripped (`del block["cache_control"]`), the call goes out uncached, and a catalog-backed `cache.below-min-predicted` Diagnostic is emitted with new `evidence_kind="pre-send"`.

**~80 LOC across 2 production files**:
- `src/pflow/nodes/llm/llm.py` — 3 helpers (`_count_text_tokens`, `_strip_below_min_cache_markers`, `_emit_pre-send_below_min_warning`) + 9-line call into `_assemble_cache_prep`.
- `src/pflow/core/cache_analysis/warning_catalog.py` — new `_BELOW_MIN_TOKENS_MESSAGE_PRE_DISPATCH` template + entry in `_BELOW_MIN_TOKENS_DISPATCH`. No new catalog ID — extended existing `cache.below-min-predicted` with a third evidence tier.

### Why this shape

Verified by 4 parallel `pflow-codebase-searcher` runs before writing code:

1. **Thresholds are 100% hardcoded** in `llm_capabilities.py:68-91` — and they must stay that way. Empirically confirmed `litellm.model_cost` has no `min_cache_tokens` field; only `min`-containing keys are `supports_minimal_reasoning_effort` and `supports_native_streaming` (unrelated). Anthropic/Gemini don't expose minimums via SDK either. Hardcoded table is the top-10% pattern (mypy/ruff/rustc do the same for provider quirks that change quarterly).

2. **Single dispatch seam.** `_assemble_cache_prep` has exactly one production caller (`LLMNode.prep:797`). Both block-builders (system + user_message_blocks for batch prewarm) converge there. Model, provider, resolved bytes, shared store, and node_id are all in scope. No new architecture needed.

3. **DD#19 byte-identity preserved.** The memo hash (`compute_node_config(prompt_cache_content=...)`) runs in `plan_node._render_cache_for_hash` BEFORE dispatch. The strip mutates only the `cache_control` key on rendered blocks — text bytes are untouched, so memo cache_key is identical whether strip fires or not. Verified by `test_pre-send_strip_does_not_mutate_text_bytes`.

4. **Observed-tier doesn't double-emit.** After strip, the provider sees no `cache_control` markers → returns no cache telemetry fields → `has_cache_telemetry=False` at `llm.py:193` → existing observed-tier emission correctly suppresses itself. Zero coordination logic needed.

### Edge cases handled

- **Per-batch-item**: `_assemble_cache_prep` is called per-call; heterogeneous batches (some items above min, some below) get correct per-item decisions with zero coupling.
- **Multiple markers** (system + user_prefix): cumulative-token walk evaluates each marker independently. Each provider cache scope is checked against the min.
- **Unknown model**: `get_min_cache_tokens` returns `CONSERVATIVE_FLOOR=4096`. Strips aggressively for unknown models — the right default.
- **`litellm.token_counter` raises**: falls back to `len(text) // 4`. The heuristic biases toward false-strip over false-keep (Gemini rejection), the cheaper error.
- **OpenAI**: `cache_control` is already a no-op there; stripping is also a no-op. `prompt_cache_key` kwargs stay (harmless).

### Testing

- **8 new production-shape tests** at `tests/test_nodes/test_llm/test_prompt_cache_below_min_runtime.py`: below-min strips, above-min keeps, exact-threshold boundary, Gemini 4096, unknown-model floor, observed-tier no-double-emit, heuristic fallback.
- **1 new catalog test** at `test_cache_analysis_warnings.py` for the `pre-send` message template.
- **1 new hash-invariance test** at `test_prompt_cache_hash.py` proving the strip doesn't touch text bytes.
- **5 existing tests adjusted**: `test_prompt_cache_rendering.py`, `test_batch_cache_prefix.py`, `test_runner.py`, `test_no_cache_flag.py`, `test_trace_integration.py` got a one-line strip-bypass — their fixtures intentionally use tiny content for shape testing. Each adjustment documented inline pointing at the dedicated strip test file.

`make test` 6766 pass / 1 skip. `make check` clean (ruff, mypy 207 files, deptry).

### Baseline regeneration

All 82 baseline cases under `.taskmaster/tasks/task_159/baseline/` regenerated with **zero byte drift**. Structurally correct: every baseline case exercises `analyze-cache` / `report` / `visualize` / `guide` (static analysis or recorded traces) — none reach the runtime dispatch seam.

Added a `pre-send` deferral note to the baseline README. A baseline case for the strip tier is the natural v1.x addition once trace 2.3.0 records `cache_skipped_reason` (the field that would let an `analyze-cache --from-trace` case observe the event).

### Key insights / learnings

1. **The dispatch seam matters more than provider abstraction.** Originally weighed a per-provider adapter pattern; rejected after the searcher confirmed all paths converge at `_assemble_cache_prep`. One seam means one check, no Provider/Capability protocol class, no new module — the change is additive within the existing data model.

2. **Hardcoded provider tables are not technical debt — they're the right shape for rare-change capability data.** The instinct to make it "dynamic" was wrong here: litellm doesn't expose the field, providers don't either, and "configurable via settings.json" would shift the bug from "we hardcoded the wrong value" to "the user hardcoded the wrong value."

3. **The catalog-as-SSoT pattern paid off.** Adding a third evidence_kind was a 3-line catalog change (template + dispatch entry). Zero new shared-store keys, zero new module, zero new catalog ID. The existing `make_diagnostic("cache.below-min-predicted", evidence_kind=...)` factory already validates required context at construction.

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
- `.taskmaster/tasks/task_159/baseline/README.md` (`pre-send` deferral note)

## 2026-05-14 — Follow-ups 2 start: separate provider prompt-cache evidence from local pflow memo reuse

Implemented the trace-analysis split between provider LLM calls and pflow-local cache hits. The analyzer now keeps two LLM-call views from trace data: a historical view that may descend into cached subtrees for token/cost estimation, and a provider-current-run view that does not treat cached memo/in-process events as provider calls. Summary telemetry now records provider call count, provider cache read/write tokens, local memo hits, local in-process hits, and historical input tokens skipped by local reuse.

Critical learning: cached trace events can preserve historical `llm_call` payloads, including `cache_read_input_tokens`, but those payloads are not proof that provider prompt caching happened in the current run. A resumed pflow run may skip the LLM call before the provider sees anything. Any user-facing "provider cache" number must come from current provider events only; historical cached-event payloads are valid for estimates, not for current provider-cache evidence.

Renderer changes make that distinction explicit in text and JSON. Text output now labels actual deltas as including local cache reuse when applicable, adds a "Local pflow cache reuse" line, reports "Provider cache in this run" separately, and tells agents to rerun with `--no-cache` when they need a clean provider prompt-cache measurement.

Tests added coverage for memo-hit traces that previously would have counted historical provider cache reads, plus renderer/JSON shape coverage for the new summary fields. Regenerated staged baselines for `03-analyze-cache-modes/07-autoload-prefers-success`, `08-autoload-failed-only`, and `09-autoload-rejected-names-file`; each was verified individually with `verify.sh`.

## 2026-05-14 — Follow-ups 2 Stage 2: split below-min IDs and wire trace-visible runtime evidence

Implemented the Stage 2 plan. The old single below-min catalog row is now distinct IDs for predicted, observed, rendered-strip, prewarm-disabled, and conditional-warmup findings. The runtime now records `cache_skipped_reason` and `prewarm_disabled_reason` in `llm_usage`/trace 2.3.0, and `build_cache_render_dict(workflow, shared)` performs the workflow-entry pre-flight check that disables below-min batch prewarm before serialization can happen.

Key integration learning: `engine.py` cannot import cache-analysis helpers at module import time without closing a runtime/analyzer cycle. The pre-flight check uses lazy imports inside `_should_disable_below_min_prewarm`; that is intentional and narrower than introducing a new shared module just to avoid one cold-path import.

`analyze-cache --from-trace` now rehydrates catalog-backed runtime warnings from trace-level `warnings[]`. This is the right source for rendered/observed/prewarm-disabled evidence because those diagnostics already contain measured runtime context; deriving them only from per-event marker fields would lose token counts.

Deliberate semantic change: `is_below_min_cache(model, tokens)` returns false when the model is unknown or unresolved. This removed dynamic-before-static recommendations whose only threshold proof came from the conservative unknown-model floor. The real-world lyrics-generator baselines were regenerated to reflect that: unresolved-model rows no longer claim below-min-dependent dynamic warnings until the model is known.

Verification notes:
- Focused regression set: 905 passed.
- Near-full sandbox pytest: 6791 passed, 19 skipped, excluding seven subprocess tests that invoke Homebrew `uv` and panic in this sandbox before Python starts.
- Full baseline oracle: 86 passed, 0 drifted, 0 harness errors. Used a temporary `/private/tmp/pflow-uv-shim/uv` because the baseline harness invokes `uv run`.
- Targeted ruff on touched files passed. Full `ruff check .` still fails on unrelated pre-existing RUF043/RUF059 issues in tests outside this change set.
- Grep gates for the legacy below-min ID and directory slug are clean across `src`, `tests`, `docs`, and `.taskmaster`; the dead-code gates for the removed catalog dispatch symbols are clean in `src`.

## 2026-05-14 — Stage 2 post-review fixes

Code review caught one real bug and two cleanups in the Stage 2 work above.

### `_per_node_warnings` early-return swallowed conditional-warmup detector

`elif first is not None and first > 0 and not row.declared_prompt_cache` had `return diagnostics` when `tokenize_prompt_region` returned None (unresolved `${var}` refs in the static prefix). The conditional-warmup detector lives further down the same function and was unreachable for any batch node with unresolvable prefix refs — the exact scenario it was designed for.

Fix: replaced the early return with a `if prefix_tokens is not None:` wrap so the `cache.batch-prewarm-below-min` emit is skipped but execution falls through to the trace-driven conditional-warmup branch. Regression test in `test_cache_analysis_per_id_emission.py::test_conditional_warmup_recommended_fires_when_static_prefix_has_unresolvable_refs` drives a workflow with `${upstream-data.summary}` in the static prefix plus a trace fixture with mixed `cache_skipped_reason` and asserts the diagnostic fires. Mutation-tested.

### `cache.dynamic-before-static` false positive for heterogeneous-batch prompts

Baseline `10-live-recordings/05-gemini-lyrics-generator` and `12-real-world-lyrics-generator/01-analyze-cache-text` were emitting a contradictory recommendation for `generate-chorus-options`, `analyze`, and `generate-concepts`: "move `${item.prompt}` after stable content; appears before ~0 stable tokens; Projected cache ratio after fix: 0%". Move 0 tokens for 0% improvement.

Root cause is shape-level: `is_below_min_cache(model, tokens)` returns False when the model is empty (heterogeneous-batch rows carry `model=""`) so the threshold-based suppression in `_find_batch_static_tail_after_dynamic` failed to fire even at `stable_tail_tokens=0`. The predicate is fine for CLAIM-type diagnostics (don't assert below-min without a model) but wrong at recommendation-SUPPRESSION gates.

Fix: added an explicit zero-payoff guard at the single producing site (`_find_batch_static_tail_after_dynamic`, ~line 3097) — `if stable_tail_tokens is None or stable_tail_tokens <= 0: return None`. Narrow scope: only suppresses the provably-meaningless "move 0 stable tokens" case; legitimate recommendations with substantial stable tails (e.g. `write-lyrics` ~1002 tokens) still fire. Regression test in `test_dynamic_before_static_silent_for_heterogeneous_batch_with_no_stable_tail`. Mutation-tested.

Open shape issue worth flagging: `is_below_min_cache` is overloaded across claim-type and suppression-type call sites. Three other suppression-gate sites (`analyze.py:2928, 2957, 3049`) still use the predicate; if false positives surface there too, the right fix is a sibling predicate (e.g. `is_likely_below_min_cache` using `get_min_cache_tokens`'s `CONSERVATIVE_FLOOR` fallback). Out of scope for this fix — none of those sites emit visibly-broken output in current baselines.

### Cleanup

- Removed dead-stub `_select_message_template` in `warning_catalog.py` (7-LOC pass-through with 4 unused kwargs left over from the catalog ID split); inlined the trivial `spec.message_template.format(**format_dict)` at the call site.

### Verification

- 589 cache-analysis tests pass (+1 from before). Full default suite 6775 pass / 10 skipped.
- Touched-file `ruff` + `mypy` clean.
- `verify.sh`: 85 pass / 1 drift (`15-run-flag-interactions/03-report-with-only` — pre-existing `/dev/fd/62: Operation not permitted` sandbox issue, unrelated).
- Regenerated 6 baselines whose `cache.dynamic-before-static` items were the false-positive shape: `10-live-recordings/05-gemini-lyrics-generator`, `12-real-world-lyrics-generator/{01-text,02-json,03-song-creator-text,04-guide}`, plus the dedicated `04-warning-catalog/07-cache.dynamic-before-static` (which was always empty — workflow has neither `prompt_cache` nor `batch`, no emission path fires; the directory is an orphan stub).
