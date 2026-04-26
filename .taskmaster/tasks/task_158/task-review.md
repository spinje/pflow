# Task 158 Review: Replace `llm` Library with LiteLLM via pflow-Owned Adapter

## Metadata

- **Branch**: `feat/prompt-caching-lite-llm`
- **HEAD**: `e9c950f0`
- **Implementation window**: 2026-04-24 → 2026-04-26 (3 calendar days, ~30 sessions documented in progress log §25–§40)
- **Commits since baseline `8349df88`**: 30
- **Diff vs `main`**: 126 files (+29,670 / −5,536). Production diff is much smaller; bulk of additions are in spike scripts, progress log, research notes, and the LiteLLM-bundled `uv.lock` regen.
- **Tests**: 5,380 passed, 9 skipped. Sacred `test_plan_drift.py` (32 parity tests) green at every commit.
- **Status**: Implementation complete and end-to-end verified against real Anthropic / Gemini / OpenAI APIs (§38). Ready for PR.

## Executive Summary

Replaced Simon Willison's `llm` library with a pflow-owned adapter (`src/pflow/core/llm_client.py`) backed by LiteLLM, becoming the single seam for every LLM call in the codebase. Three architectural changes ship together because the migration touches all of them: a typed exception hierarchy with structured discriminators, a diagnostic pipeline integrated through a new `llm_failure` category, and a tracing redesign that replaces the broken `llm.get_model` monkey-patch with a `shared["__trace_collector__"]` save/restore seam. Caching syntax (the original motivating use case) is deliberately deferred to Task 159 — this branch is pure substrate.

## Implementation Overview

### What Was Built

**1. The adapter seam** — `core/llm_client.py`. Public API: `complete(*, model, prompt, system, temperature, max_tokens, attachments, schema, reasoning_kwargs, model_options, timeout, trace_hook) -> AdapterResponse`. Wraps `litellm.completion`. Owns:

- Building the LiteLLM `messages` list from `system + prompt + attachments`
- Translating reasoning kwargs (Anthropic `thinking={"type":"enabled","budget_tokens":N}`, Gemini top-level `thinking_budget`, OpenAI `reasoning_effort`)
- Translating every LiteLLM exception into a typed `LLMCallError` subclass — caught structurally at `openai.OpenAIError` (the OpenAI SDK base; `litellm.exceptions.OpenAIError` is a sibling class, not a parent — see Gotcha §1)
- Normalizing the response to a stable `AdapterResponse` (provider quirks for cache tokens collapse here)
- Reading cost from `response._hidden_params["response_cost"]` (LiteLLM owns pricing)
- Firing optional `trace_hook` at `before_call` / `after_call`

**Lazy `import litellm`** inside `complete()` and `_classify_litellm_error()` keeps non-LLM CLI invocations fast (saves ~700ms — see Performance §1).

**2. Typed exception hierarchy** — `core/exceptions.py`. `LLMCallError(PflowError)` + 6 subclasses, each with structured discriminators and `to_diagnostics()` overrides:

| Subclass | Discriminator | When raised |
|---|---|---|
| `UnknownModelError` | `reason: "unknown_name" \| "missing_prefix"` | `NotFoundError`, `LiteLLMUnknownProvider`, "LLM Provider NOT provided" `BadRequestError` |
| `MissingApiKeyError` | `kind: "missing_key" \| "lacks_permission"` | `AuthenticationError`, `PermissionDeniedError` |
| `LLMTransientError` | `kind: "timeout" \| "rate_limit" \| "server_error" \| "connection"` | `Timeout`, `RateLimitError`, `InternalServerError`, `APIConnectionError` (non-SDK) |
| `MissingSdkError` | `package: str` | `APIConnectionError` whose `__cause__` chain contains `ImportError` |
| `InvalidRequestError` | (default fallback) | Other deterministic 4xx — schema, content-policy, context-window, etc. |
| `LLMResponseParseError` | — | Pydantic schema validation failure on a successful call's JSON response |

Every instance carries `model: str | None` and `provider_message: str | None` — the latter is the **raw upstream text** distinct from `str(self)` (the pflow-wrapped framing). Don't conflate them: `Diagnostic.message` is the WHAT, `context["provider_message"]` is the WHY.

**3. Tracing redesign** — `runtime/workflow_trace.py`. Deleted the `llm.get_model` monkey-patch and the `_active_collectors[thread_id]` registry. Replaced with `shared["__trace_collector__"]` save/restore around `engine.run`'s graph walk. LLMNode reads it in `prep()`, captures `trace_hook` BEFORE submitting to the inner `ThreadPoolExecutor` (the worker-thread boundary that broke the old design empirically — `_active_collectors[main_thread_id]` never matched `worker.thread_id`).

**Free behavior fix**: `event["llm_prompt"]` now actually populates in trace JSON. The prior implementation looked correct but the thread-id mismatch silently dropped every literal-prompt capture. `pflow report`'s `## Prompt` section is now reliably present.

**4. Provider registry** — `core/llm_providers.py` (new, ~78 lines, dependency-free). `ProviderInfo` dataclass + `PROVIDERS` tuple + `detect_provider` / `normalize_model_name` / `model_name_without_provider`. Single source of truth consumed by adapter normalization, reasoning capability detection, and env-var derivation.

**5. Reasoning-options channel consolidation** — `core/llm_reasoning_map.py` is the canonical translator. Raw `model_options` rejects reasoning keys (`thinking`, `thinking_budget`, `thinking_effort`, `reasoning_effort`, `reasoning_max_tokens`, `thinking_level`) at `_validate_model_options` — pflow has dedicated channels and bypassing them silently drops provider-specific translation. `smart_filter` now routes through `map_reasoning_options(model, "none", None, None)` instead of substring-sniffing.

**6. Pricing module deletion** — `core/llm_pricing.py` (188 lines, 41 stale model entries) is gone. Cost comes from LiteLLM's `_hidden_params["response_cost"]`. `enrich_llm_usage_with_cost` is also gone (was a 30-line helper that became dead code post-migration; producers now write `cost_usd` directly). Engine modules MUST NOT import `llm_client.py` — see Performance §1.

**7. Bare model-name auto-prefix** — Two layers: settings CLI normalizes at write time with user feedback (`gemini-3-flash-preview` → `gemini/gemini-3-flash-preview`); adapter `_normalize_model_name` is the safety net for names from workflow files. Mapping: `claude-*` → `anthropic/`, `gemini-*` → `gemini/`, `gpt-*`/`o1-*`/`o3-*`/`o4-*` → `openai/`. Unknown bare names pass through (preserves custom/self-hosted models).

**8. Dependency changes** — Dropped `llm`, `llm-anthropic`, `llm-gemini`. Added `litellm==1.82.6` (NOT `1.83.x` — those hard-pin `click==8.1.8` which downgrades pflow's click 8.3.1 and breaks 3 CliRunner-based tests). Added `openai` as direct dep (was transitive via litellm; now explicit because the adapter catches `openai.OpenAIError`).

### Implementation Approach

**Phased**: Phase 0 spike (5 concerns: cache mechanics, composition matrix, pricing authority, operational checks, exception detection) → Phase A (12 sub-steps A.1–A.12) → 3 rounds of code review (each driving structural improvements rather than band-aids) → perf-fix pass → end-to-end verification.

**Architectural principle that drove every decision**: "Simplicity of the FINAL code, not how easy it is to get there." This converted multiple "minimum-diff" patches into structural fixes. Notably:

- Item #6 (Phase A code review) — became Option F (adapter raises typed exceptions) instead of `raise_for_status()` on `AdapterResponse`. Deletes the `error`/`status` fields entirely; consumers catch `LLMCallError`.
- Phase A code review #2 — became "completing the typed-exception architecture" with `to_diagnostics()` overrides, instead of patching each callsite.
- §39 structural review-fix pass — became the provider registry + transient `kind` discriminator + `model_options` rejection + `provider_message` field, instead of separate small fixes for `o4-*` drift, generic transient diagnostics, schema-validation swallow.

## Files Modified/Created

### New core files (the load-bearing additions)

- `src/pflow/core/llm_client.py` (919 lines) — the adapter seam. Single source of truth for LLM calls.
- `src/pflow/core/llm_providers.py` (78 lines) — provider metadata registry. Dependency-free.
- `src/pflow/core/llm_reasoning_map.py` (204 lines) — reasoning capability detection + `map_reasoning_options()`. Replaces the live `model.Options.model_fields` introspection from the `llm` library.

### Modified production files (most architecturally significant)

- `src/pflow/core/exceptions.py` — `LLMCallError` + 6 subclasses with `provider_message` + `diagnostic_context()` + `to_diagnostics()` overrides. `LLM_FAILURE_CATEGORY` constant.
- `src/pflow/core/diagnostic.py` — `LLM_FAILURE_CATEGORY = "llm_failure"`, `LLM_WARNING_CATEGORY = "llm_warning"`, `normalize_runtime_warning()`.
- `src/pflow/nodes/llm/llm.py` — single `_call_llm` boundary catches `LLMCallError`; `LLMTransientError` re-raises for retry. `_propagate_error_to_shared` is the single mutation seam for every error path. Reads `shared["__trace_collector__"]` in `prep()`.
- `src/pflow/runtime/workflow_trace.py` — monkey-patch deleted. `get_trace_hook(node_id)` is the new mechanism. `__trace_collector__` filtered from saved trace output.
- `src/pflow/runtime/engine/engine.py` — `_NODE_TYPE_FAILURE_CATEGORY` adds `LLMNode → FAILURE_CATEGORY_LLM`. `engine.run()` save/restore around graph walk.
- `src/pflow/execution/executor_service.py` — `_FAILURE_CATEGORY_MAP` adds `"llm_failure": "llm_failure"`. `_enrich_error_from_node_output` lifts `_diagnostic_context` from `node_output` to runtime Diagnostic context.
- `src/pflow/registry/discovery.py`, `src/pflow/registry/smart_filter.py`, `src/pflow/core/workflow/discovery.py` — the 3 non-LLMNode call sites; all migrated to `complete()`. `smart_filter` narrow `except (LLMCallError, ConnectionError, OSError)`.
- `src/pflow/cli/find_errors.py` — `LLMCallError` branch ahead of generic fallthrough; renders rich `to_diagnostics()` directly.
- `src/pflow/cli/commands/settings.py` — bare model-name normalization at write time + `pflow settings set-env` help-text.
- `src/pflow/core/llm_config.py` — dropped `_has_llm_key()`, `get_llm_cli_default_model()`, all `subprocess` paths. Two-tier resolution: env → settings.

### Deleted files

- `src/pflow/core/llm_pricing.py` (188 lines) — replaced by LiteLLM's `_hidden_params["response_cost"]`.
- `tests/test_core/test_llm_pricing.py` — production module is gone.
- `tests/test_nodes/test_llm/test_llm_reasoning.py` — superseded by `test_llm_reasoning_map.py` + new classes in `test_llm.py`.

### Critical test files

- `tests/test_core/test_llm_client.py` (1,149 lines) — adapter contract. **`TestAdapterSealContract`** is parametrized over 16 LiteLLM exception classes + 1 synthetic-unknown subclass. Catches "any future LiteLLM exception leaks past the adapter." If you add a branch to `_classify_litellm_error`, add a row here.
- `tests/test_core/test_llm_reasoning_map.py` (366 lines) — every provider/family path including the Opus 4.5 `thinking_effort` precedence and OpenRouter false-positive regression.
- `tests/test_core/test_llm_providers.py` (33 lines) — provider registry contract.
- `tests/test_execution/test_executor_service_llm.py` (219 lines) — end-to-end pipeline: real `litellm.exceptions` → `_classify_litellm_error` → typed pflow exception → LLMNode → runner → `result.errors[i].context`. Pins `provider_message` across 5+ layers.
- `tests/test_runtime/test_trace_integration.py` — `TestLLMTraceHookCapture`, `TestSubWorkflowTraceCollector`, `TestParallelBatchSubWorkflowTrace`. Regression guards for the trace_hook seam.
- `tests/test_execution/test_plan_drift.py` — **32 sacred parity tests**. Asserts planner ↔ runtime cost parity. Green at every commit; if it ever fails on a Task 158/159 change, stop and investigate.
- `tests/conftest.py` — `mock_llm_client` autouse fixture replaces `pflow.core.llm_client.complete` (and 4 consumer-module bindings). Path-substring skip on `/llm/` (NOT `_llm/` — see Gotcha §3).

## Integration Points & Dependencies

### Adapter is the single seam

```
LLMNode._call_llm ───┐
discovery.find_components ─┤
smart_filter.smart_filter ─┼──> pflow.core.llm_client.complete() ──> litellm.completion()
workflow.discovery.find_workflow ─┘
```

NO consumer outside `core/llm_client.py` imports `litellm.exceptions` or `openai`. Architectural seal verified by:
```bash
grep -rn 'litellm\.exceptions\|^import openai\|^from openai' src/pflow/
# Expected: hits ONLY in core/llm_client.py (and incidental docstrings)
```

### Failure category propagation

```
LLMCallError raised
  → LLMNode._call_llm catch
  → _error_dict_from_exception (reads to_diagnostics())
  → _propagate_error_to_shared (writes _diagnostic_context to shared)
  → mark_node_failed (archives to shared["__failures__"])
  → executor_service._enrich_error_from_node_output (lifts to runtime Diagnostic)
  → ExecutionResult.errors[i].context  (final JSON output)
```

`_FAILURE_CATEGORY_MAP["llm_failure"] = "llm_failure"` — LLM is its own category, distinct from generic `"execution_failure"`. Filter on `category="llm_failure"` to find LLM errors in JSON output.

### Shared Store Keys

| Key | Routing | Owner | Purpose |
|---|---|---|---|
| `__trace_collector__` | Root (dunder bypass) | `engine.run()` save/restore | Active `WorkflowTraceCollector`. LLMNode reads in `prep()`, captures `trace_hook` BEFORE worker-thread submission. |
| `__warnings__` | Root (dunder bypass) | `LLMNode.post()` writes structured warning dicts | Adapter empty-response detection results. Lifted via `normalize_runtime_warning()` to `Diagnostic` with `category="llm_warning"`. |
| `__failures__` | Root (dunder bypass) | `mark_node_failed` | Archived per-node error records. `_enrich_error_from_node_output` reads `data._diagnostic_context`. |
| `_diagnostic_context` | Namespaced (single `_`) | `LLMNode._propagate_error_to_shared` | Per-node forwarding of `to_diagnostics()` context dict to `executor_service`. |
| `error`, `error_class` | Namespaced | LLMNode error path | `error_class` is machine-parseable cause; surfaced to `result.errors[i].context.error_class`. |
| `prompt` | Namespaced | LLMNode.post() | The rendered prompt string. `batch_executor._capture_item_trace` reads it for per-item batch trace prompts (was a documented gap before B11). |
| `response`, `llm_usage` | Namespaced | LLMNode.post() | Output payload + token/cost dict. |

**Routing rule**: Single-leading-underscore keys land in `parent[node_id][key]` via `NamespacedSharedStore`. Double-dunder `__key__` keys bypass to root. **`NamespacedSharedStore` does NOT implement `pop()`** — for save/restore, use unconditional write-back (write `None` back), not `.pop()`.

### Outgoing Dependencies

- LiteLLM 1.82.6 (NOT 1.83.x — see Gotcha §2). Pinned for Gemini PR #15226 fix; verified end-to-end.
- `openai` (direct dep — `core/llm_client.py` catches `openai.OpenAIError`).

## Architectural Decisions & Tradeoffs

### Key decisions

| # | Decision | Why | Alternative considered |
|---|---|---|---|
| 1 | Adapter is the SINGLE seam | One translation point for exceptions, response shape, cost extraction, trace hooks. Future caching plugs in here. | Direct LiteLLM calls scattered across LLMNode + 3 discovery callers (drift risk, no central enforcement) |
| 2 | Typed exceptions with structured discriminators | Crossing a typed boundary loses any signal not in the typed contract. `e.reason` survives; `"missing_prefix" in str(e)` does not when LiteLLM rewords. | Substring-match exception messages (fragile; the `Pydantic ValidationError` PATTERN EXCEPTION in the old code was exactly this trap) |
| 3 | `provider_message` separate from `Diagnostic.message` | Wrapping discards raw upstream text; agents need both the WHAT (pflow framing) and the WHY (provider text). | One field carrying both purposes (collapses real failure modes; "Quota exceeded" vs "Invalid key" become indistinguishable inside `MissingApiKeyError`) |
| 4 | `category="llm_failure"` (its own bucket) | LLM-specific cost/retry/key-rotation policies; structured remediations agents filter on; auth/permission/model-name discrimination is unique to LLM. | Generic `"execution_failure"` (loses agent-side filtering) |
| 5 | `shared["__trace_collector__"]` save/restore | Survives the `ThreadPoolExecutor` worker-thread boundary the previous design relied on. Reuses existing `_PROPAGATED_KEYS` infrastructure. | Per-thread-id global state (empirically broken — the design pattern was inherited from llm-library era and didn't actually work in production traces) |
| 6 | Provider registry as canonical source of truth | Adding `o4-*` previously required edits in 3 places that drifted out of sync. Registry = one-line addition. | Hardcoded constants in `llm_client.py` + `llm_reasoning_map.py` + `exceptions.py` (the actual pre-§39 state) |
| 7 | Cost from LiteLLM, not from a pflow table | LiteLLM has 2,678 models priced (vs pflow's 41); per-provider cache multipliers are correct (pflow's was Anthropic-only); new-model releases ship pricing without a pflow update. | Maintain `MODEL_PRICING` table (~30 model entries became stale, gpt-4o was 2x outdated) |
| 8 | Lazy `import litellm` inside `complete()` | LiteLLM eager-loads ~700ms of provider handlers; non-LLM CLI paths (`--version`, `validate`, `--dry-run`, cached runs) shouldn't pay it. | Top-level import (made `pflow --version` 4× slower, multiplied through ~30 subprocess tests) |
| 9 | Bare model auto-prefix in TWO layers | Settings CLI gives immediate UX feedback at write time; adapter is the safety net for workflow files. | Adapter only (loses settings UX) or settings only (workflow files still hit Vertex routing trap) |
| 10 | `model_options` rejects reasoning keys | Two reasoning paths drift; `model_options` bypasses provider-specific translation in `_translate_reasoning_for_litellm`. | Warn-and-merge with precedence rules (silent user-intent drops; documented edge case proliferates) |

### Technical debt incurred

1. **First LLM call's `duration_ms` includes ~700ms of one-time litellm import.** For multi-call workflows: 1/N nodes affected; for single-call: the only node affected. Cost predictions (token-based) and total wall-clock are unaffected. Documented in `core/CLAUDE.md`. Option C (subtract via shared-store) was 17 lines of coordination across 3 files — rejected as bad complexity-to-value.
2. **`smart_filter` silent degradation.** `except (LLMCallError, ConnectionError, OSError)` falls back to unfiltered field set when the filtering call fails. Intentional (filtering is best-effort), but with the new `LLMCallError` umbrella, more paths flow through this silencer. Pre-existing behavior; just more reachable.
3. **`exec_fallback` substring-detects `"timed out"`.** Avoids re-importing `litellm.exceptions` from `nodes/llm/llm.py` (preserves the seal). If LiteLLM ever changes its `Timeout` `str()` representation, this breaks silently. Mitigation: in-thread timeout tests assert on the message; retry-exhaustion path would need manual re-verification.
4. **9 follow-up GH issues filed** for non-blocking findings: #347 (standardize node prep validation), #348 (centralize LiteLLM provider metadata for UX), #349 (reasoning option edge cases), #350 (zero/partial cost display), #351 (batch trace + warning aggregation), #352 (secondary diagnostic context polish), #353 (typed sub-discriminators for `MissingApiKeyError`), #354 (enrich suggestions from `provider_message` text), #355 (codify autouse-mock-bypass test pattern).

## Testing Implementation

### Strategy applied

- **Unit-level seal-contract tests** (`TestAdapterSealContract`) for every classification branch — parametrized over 16 LiteLLM exception classes. Synthetic-unknown subclass test verifies the default-fallback path.
- **Layer-by-layer pinning** for the failure-category propagation: `tests/test_execution/test_executor_service_llm.py` runs through `WorkflowRunner` (not unit-only helpers) and asserts `result.errors[0].context.category == "llm_failure"`.
- **End-to-end pinning of `provider_message`**: `test_real_litellm_exception_provider_message_reaches_runner_diagnostics` patches `litellm.completion` (one layer below the autouse mock) to raise a real `litellm.exceptions.AuthenticationError` and asserts the raw text appears in `result.errors[0].context["provider_message"]`. A regression in any of the 5+ layers fails this test loudly.
- **Sacred parity tests** (`test_plan_drift.py`, 32 tests) — green at every commit. Pin planner ↔ runtime cost parity. **Regression here is a STOP signal.**
- **Real-API smoke** (§38) — 35 manual tests across all 3 providers, batch, sub-workflows, error paths, `--report`, `--dry-run`, `--no-cache`, `--validate-only`, structured output, extended thinking, pre-Phase-A trace backwards compat.

### Critical test cases

| Test | What it pins |
|---|---|
| `TestAdapterSealContract.test_litellm_exception_wraps_to_typed_pflow_exception` | Every classified LiteLLM exception becomes a typed `LLMCallError` subclass |
| `TestAdapterSealContract.test_seam_threads_provider_message_to_every_classification` | Every classification branch threads `provider_message=str(exc)` to the typed exception |
| `TestAdapterSealContract.test_unknown_litellm_subclass_wraps_safely` | Default fallback wraps unknown future classes as `InvalidRequestError` (deterministic, NOT transient — won't infinite-retry) |
| `test_real_litellm_exception_provider_message_reaches_runner_diagnostics` | Full pipeline: real exception → seam → LLMNode → runner → `result.errors[i].context.provider_message` |
| `TestSmartFilterMinimizesReasoning` | smart_filter routes via `reasoning_kwargs` (canonical channel), with `assert last_call["model_options"] is None` regression guard |
| `test_disable_gemini_3` | `effort="none"` on Gemini 3 maps to `thinking_level=minimal` (Gemini 3 has no off-switch) |
| `TestLLMTraceHookCapture` | trace_hook fires across the worker-thread boundary; `event["llm_prompt"]` populates |
| `TestParallelBatchSubWorkflowTrace` | Sub-workflow LLM prompts land in child collector's `llm_prompts` (not parent's) |
| `test_opus_45_max_tokens_takes_precedence_over_effort` | Anthropic Opus 4.5 `thinking_effort` precedence preserved (was load-bearing in the legacy llm-library code) |

## Unexpected Discoveries

### Gotchas

1. **`litellm.exceptions.OpenAIError` is a SIBLING of every other LiteLLM exception, not a parent.** `litellm.exceptions.BadRequestError.__mro__` shows `→ openai.BadRequestError → openai.APIError → openai.OpenAIError`. The package's own `OpenAIError` class is a separate path. Catching `litellm.exceptions.OpenAIError` would miss every other class. **Catch `openai.OpenAIError`** — the structural base. Same trap one layer down: `litellm.exceptions.Timeout` does NOT inherit from `litellm.exceptions.APIConnectionError`.

2. **`litellm==1.83.x` hard-pins `click==8.1.8`.** Every release in the 1.83.x series. Downgrades pflow's click 8.3.1 and breaks 3 CliRunner tests that depend on click 8.2+'s default stderr separation. Pin 1.82.6 or test before bumping. (1.84.0+ surveyed via PyPI JSON API — issue persists.)

3. **The autouse mock skip pattern is path-substring-based on `/llm/`.** Files at `tests/test_nodes/test_llm/test_llm.py` get the mock applied because the path contains `_llm/`, not `/llm/`. This is by design — those are unit tests. **Tests needing real-adapter behavior must patch `litellm.completion` ONE LAYER BELOW** `pflow.core.llm_client.complete` (the seal-contract test pattern). Patching `pflow.core.llm_client.litellm.completion` ALSO fails because `litellm` is no longer a module attribute (lazy import).

4. **Bare Gemini names route to Vertex AI**, not Google AI Studio. `gemini-3-flash-preview` (no prefix) → Vertex AI path → needs Google Cloud SDK → `APIConnectionError`. Three symptoms: wrong routing, 3 retries on permanent failure, ~120 lines of stderr noise. Fixed in §38 via auto-prefix + `MissingSdkError` classification + LiteLLM logger silencing.

5. **`NamespacedSharedStore` does NOT implement `pop()`.** It implements `update`, `__setitem__`, `__getitem__`, `__contains__`, `get`, `setdefault`, `keys`, `items`, `values`, `__iter__`, `__len__`. For save/restore patterns on shared keys that may be visible to a child's namespaced store, use **unconditional write-back** (write `None` back), not `.pop()`. The previous `_pflow_child_only_node` precedent at `engine.py:157` uses `.pop()` only because it's a parent-side regular dict, not a child's namespaced proxy.

6. **`compiler.py:299` sets `node.node_id` as a dynamic attribute.** Not declared on the class. `LLMNode.prep()` reads `getattr(self, "node_id", None)` to satisfy mypy. Same pattern any future node needing its own ID will follow.

7. **Lint complexity warnings are signal, not noise.** Both C901 hits during this work (`_normalize`, `format_execution_success`) surfaced abstractions that the inline code was hiding (extracting `_detect_empty_response_warnings`, `_mirror_pricing_tri_state`, `_LLMSummaryAccumulator` improved readability). Don't suppress; extract.

8. **Dead-field bug pattern**: when extending an internal contract with a new field, **trace where it's consumed**. §32 added `error_class` to `LLMNode`'s internal error dict. Tests passed. But `LLMNode.post()` didn't surface it to `shared`, so the field was buried at the internal layer and never reached JSON output. §34 caught this one layer up — `error_class` set in `shared` but `executor_service._enrich_error_from_node_output` had no LLM branch to lift it. Same pattern, recursive.

### Edge cases discovered

- Anthropic models with thinking enabled require `temperature=1.0`. Identical `BadRequestError` across Opus 4.5, Sonnet 4.5, Sonnet 4.6, Haiku 4.5 — verified by §31's spike. The error message is exemplary (WHAT + HOW + docs URL) so pflow does NOT pre-validate; it propagates the actionable Anthropic message via `LLMCallError.provider_message`.
- Gemini-3-flash-preview is a reasoning model. With low `max_tokens` and no `reasoning_effort: minimal`, all visible-token budget goes to internal reasoning → `text=""` with `finish_reason=length`. The empty-response warning system (`AdapterResponse.warnings`) detects this with dual remediation (raise `max_tokens` OR lower `reasoning_effort`).
- Anthropic Opus 4.5's `thinking_effort` precedence over `thinking_budget` — load-bearing legacy llm-library invariant, preserved verbatim in `EFFORT_RATIOS` + `_translate_reasoning_for_litellm`.
- Empty-response gating is on `text` presence, not `output_tokens > 0`. Provider refusals fire at zero tokens — a `content_filter` finish_reason with zero tokens IS the diagnostic, not a "silent success."

## Patterns Established

### Reusable patterns (USE these in Task 159 and beyond)

**Pattern 1 — Structured discriminators at the seam, never substring-matching across it.**
```python
# Adapter side (the seam):
def _classify_litellm_error(exc, *, model):
    if "LLM Provider NOT provided" in str(exc):
        return UnknownModelError(message, reason="missing_prefix", ...)  # structured
    return UnknownModelError(message, reason="unknown_name", ...)

# Consumer side (LLMNode):
except UnknownModelError as e:
    if e.reason == "missing_prefix":  # branch on attribute, NOT message text
        ...
```
Crossing a typed boundary loses any signal that isn't in the typed contract. If you add a sub-case to a typed exception, add a structured attribute. NEVER encode the discriminator in message text and parse it on the consumer side.

**Pattern 2 — `to_diagnostics()` overrides as the single source of truth.**
```python
class UnknownModelError(LLMCallError):
    def to_diagnostics(self) -> list[Diagnostic]:
        # Returns single-element list (PflowError convention).
        suggestions = [...]  # branch on self.reason
        return [Diagnostic(
            message=str(self),
            title="Unknown Model",
            suggestions=suggestions,
            context=self.diagnostic_context(reason=self.reason),
            category=LLM_FAILURE_CATEGORY,
            see_also=["llm"],
        )]
```
Single source of truth for prose + structured context per error type. Pre-execution path (cli/find_errors) reads it directly; runtime path forwards it via `_diagnostic_context` dict. No consumer reimplements remediation logic.

**Pattern 3 — Adapter is the single source of truth for derived data.**
```python
# Cost, reasoning_tokens, thinking_budget all extracted/mirrored at _normalize.
# Consumers of AdapterResponse.usage get a complete picture from one read.
```
Don't make LLMNode mirror request-side state into response-side outputs. If a derived field is needed downstream, compute it at `_normalize`.

**Pattern 4 — Lazy-import heavy machinery; module-level imports for cheap types/data.**
```python
# Module level: cheap types and data
from pflow.core.exceptions import LLMCallError
from pflow.core.llm_providers import detect_provider

# Function body: heavy machinery
def complete(...):
    import litellm  # ~700ms one-time cost
    import openai
```
Engine modules MUST NOT import `llm_client.py` (re-introduces the cost into eager CLI startup).

**Pattern 5 — Catch the structural base, not the friendly-named one.**
```python
# WRONG: misses every other LiteLLM exception
except litellm.exceptions.OpenAIError: ...

# RIGHT: the actual MRO base
except openai.OpenAIError: ...
```
When dealing with vendored exception hierarchies (LiteLLM wraps OpenAI SDK), introspect MRO before assuming the package's own `XError` class is the right catch base.

**Pattern 6 — Walk `__cause__` for permanent-vs-transient classification.**
```python
def _classify_transient_kind(exc):
    if isinstance(exc, APIConnectionError):
        if _has_import_error_cause(exc):
            return "missing_sdk"  # permanent; don't retry
        return "connection"  # transient; retry helps
```
`APIConnectionError` from a missing `import` is permanent; from a network timeout is transient. The exception chain distinguishes them.

**Pattern 7 — Provider metadata in ONE registry, NOT scattered.**
```python
# pflow.core.llm_providers.PROVIDERS — single source of truth
ProviderInfo("anthropic", "anthropic/", ("claude-",), "ANTHROPIC_API_KEY"),
ProviderInfo("openai", "openai/", ("gpt-", "o1", "o3", "o4"), "OPENAI_API_KEY"),
ProviderInfo("gemini", "gemini/", ("gemini-",), "GEMINI_API_KEY"),
```
Adding a provider/family is a one-line registry change. Don't replicate `("claude-", ...)` across `llm_client.py` + `llm_reasoning_map.py` + `exceptions.py`.

**Pattern 8 — Single-error-path mutation seam.**
```python
def _propagate_error_to_shared(shared, exec_res, *, response_already_set, preserve_usage):
    # Single place where every error path writes to shared.
    # Future error path: build error_dict, call this. Can't forget _diagnostic_context.
```
4 error paths in LLMNode all flow through one helper. New error sources must use it.

**Pattern 9 — `provider_message` is the WHY, `Diagnostic.message` is the WHAT.**
```python
# In _classify_litellm_error:
return MissingApiKeyError(
    f"API key required for model {model!r}",  # pflow framing (WHAT)
    model=model,
    kind="missing_key",
    provider_message=str(exc),  # raw provider text (WHY)
)
```
Don't cram both purposes into one string. Wrapping makes the diagnostic readable; raw form makes it actionable.

**Pattern 10 — `__double_dunder__` shared keys for cross-cutting state, single-`_underscore` for per-node.**
```python
shared["__trace_collector__"] = collector  # bypasses NamespacedSharedStore → root
shared["_diagnostic_context"] = ctx       # routes to parent[node_id]["_diagnostic_context"]
```
This is enforced by `NamespacedSharedStore.__setitem__` routing rules. Picking the wrong convention leads to "this key isn't where I expected" bugs (the rename of `_trace_collector` → `__trace_collector__` fixed exactly this).

### Anti-patterns to avoid

| Anti-pattern | Why it bites | Use this instead |
|---|---|---|
| `import litellm.exceptions` outside `core/llm_client.py` | Breaks the architectural seal. Future LiteLLM additions silently leak past the adapter. | Catch `LLMCallError` from `pflow.core.exceptions` |
| `if "missing_prefix" in str(e):` | Adapter rewording silently breaks consumer logic | Add a structured `reason`/`kind` attribute to the exception |
| Substring-match provider exception message | Cross-version drift, locale rewording | The adapter classifies once; consumer branches on the typed attribute |
| Eager `import litellm` in any module on the CLI startup path | +700ms per CLI invocation, multiplied through subprocess tests | Lazy-import inside the function that actually needs it |
| Catch `Exception` (broad) | Programming bugs (`AttributeError`, `KeyError`) silently degrade UX instead of surfacing as test failures | Narrow tuple matching the actual contract |
| Encode provider metadata in 3 places | Inevitable drift (`o4-*` was the canonical example) | Add to `llm_providers.PROVIDERS` |
| `shared.pop("_some_key")` for save/restore | `NamespacedSharedStore` doesn't implement `pop()` — crashes in sub-workflow context | Unconditional write-back: `shared[key] = saved_value` even when saved is None |
| Add a field to an internal dict without surfacing it | Dead field — never reaches JSON output | Trace consumers; add explicit forwarding at boundaries |
| `from pflow.core.llm_client import complete` then `monkeypatch.setattr` in a test | Autouse mock already replaced `complete`; your patch hits the mock, not the real code | `@patch("litellm.completion")` (one layer below) |

## Breaking Changes

### API/Interface changes (within the codebase — no public users)

- `AdapterResponse` has NO `error: str | None` or `status: Literal["ok", "error"]` fields. Successful response only. Catch `LLMCallError` instead of checking `response.status == "error"`.
- `parse_structured_response()` now raises `LLMResponseParseError` on Pydantic validation failure (was: log warning, return raw invalid dict).
- `WorkflowTraceCollector` no longer has `_active_collectors`, `_thread_local`, `_llm_lock`, `_llm_interceptor_installed`, `register_for_llm_call`, `unregister_from_llm_call`, `enable_llm_interception`. The remaining public surface: `events`, `llm_prompts`, `record_node_execution`, `get_trace_hook(node_id)`, `save_to_file`.
- Removed `get_llm_cli_default_model()` and `_has_llm_key()` from `core/llm_config.py` (subprocess paths gone). Resolution chain: env → settings (was env → settings → llm CLI).
- `parse_structured_response(response, schema, *, model=None)` — added kwarg-only `model` param for `LLMResponseParseError.model`. Existing 2-arg calls still work; tests with mocks may need signature updates.
- Help-text strings: `'llm models'` → `'pflow settings llm show'`; `'llm keys set <provider>'` → `'pflow settings set-env'`.

### Behavioral changes

- `event["llm_prompt"]` now actually populates in trace JSON for every non-batch LLM call (was missing pre-§31 — the monkey-patch fix).
- Cost from LiteLLM. Old workflows with cached `llm_usage` lacking `cost_usd` will surface as `cost_basis: upper_bound` / `estimated_cost_usd: null` in dry-run plans for ~24h post-upgrade until cache TTL flushes. Self-healing.
- Bare model names auto-prefix at write time (settings) and call time (adapter). Unknown bare names pass through unchanged (no behavior change for custom/self-hosted models).
- Empty-response detection now fires for `content_filter`, `stop`-with-empty-content, and unrecognized `finish_reason` cases (was: only `length`/`max_tokens`).

## Future Considerations

### Extension points (where Task 159 caching plugs in)

1. **`AdapterResponse.usage` already normalizes cache tokens** (`cache_creation_input_tokens` / `cache_read_input_tokens`) across providers. Phase 0 spike confirmed Anthropic vs Gemini/OpenAI reporting paths. Caching feature surfaces cost/savings via these fields with no contract change.
2. **`_build_messages` is where `cache_control` markers go.** The cache rendering (Task 159 Phase C) must split the rendered prompt into content blocks at this layer — `prep_res["prompt"]` arrives as a flat string today.
3. **`shared["__trace_collector__"]` save/restore** is the seam for sub-workflow tracing. Cache events for nested workflows already flow through this.
4. **`category="llm_failure"` precedent** — cache-rendering errors should follow the `LLMCallError → to_diagnostics() → _FAILURE_CATEGORY_MAP entry → _enrich_error_from_node_output branch` chain. Add a `CacheRenderError(LLMCallError)` subclass with its own structured discriminator.
5. **Trace format 2.1.0 cache fields** (deferred to Task 159) plug into existing `_attach_llm_call_to_event` writer.
6. **`pflow analyze-cache`** can lazy-import `llm_client.py` if it needs `complete()` for prewarming; otherwise the command is fast (no litellm cost) when reading cache plans from memo.

### Scalability concerns

- `LLM_FAILURE_CATEGORY` is currently a string constant. If category-specific routing grows, consider a `Category` enum. Out of scope until `shell_failure`/`http_failure`/`mcp_failure` parity is justified.
- Provider registry (`llm_providers.PROVIDERS`) is a 3-element tuple. Adding OpenRouter, Bedrock, Azure, Vertex, Mistral, Cohere etc. — one line each. **Prefix matching is exact `startswith()` by design** (`openrouter/anthropic/...` is NOT Anthropic). When pflow supports OpenRouter explicitly, add as a separate registry entry; don't relax the matching to substring.
- `_classify_litellm_error` catches via the `_SEAL_CONTRACT_CASES` map. Future LiteLLM exception classes get the safe `InvalidRequestError` default until classified explicitly. The `TestAdapterSealContract` parametrized test catches it.

## AI Agent Guidance

### Quick start for related tasks (especially Task 159 — Caching)

**Read first, in this order:**
1. `src/pflow/core/llm_client.py` (top docstring + `complete()` signature + `AdapterResponse` dataclass) — the seam.
2. `src/pflow/core/exceptions.py:130-227` — `LLMCallError` base + `provider_message` field + `diagnostic_context()` invariant.
3. `src/pflow/core/llm_providers.py` — full file (78 lines, dependency-free).
4. `src/pflow/nodes/llm/llm.py:1-100` — module imports + helpers + the typed-catch chain in `_call_llm`.
5. `tests/test_core/test_llm_client.py` `TestAdapterSealContract` — the contract pinned by parametrized tests.
6. `.taskmaster/tasks/task_158/implementation/progress-log.md` §27 (Phase 0 spike) and §38 (end-to-end verification) for concrete LiteLLM behavior.
7. `.taskmaster/tasks/task_159/task-159.md` — caching feature spec.

**Key files to grep when in doubt:**
- `grep -n "LLM_FAILURE_CATEGORY\|llm_failure" src/pflow/` — the failure-category propagation chain.
- `grep -rn '__trace_collector__' src/pflow/ tests/` — trace seam consumers.
- `grep -n "to_diagnostics" src/pflow/core/exceptions.py` — diagnostic override map.

### Common pitfalls (do these wrong, the change will silently break)

1. **DON'T import `litellm.exceptions` outside `core/llm_client.py`.** Breaks the architectural seal. Verify after every change: `grep -rn 'litellm\.exceptions\|^import openai' src/pflow/` should return hits ONLY in `core/llm_client.py` (plus incidental docstrings).

2. **DON'T import `core/llm_client.py` from engine modules** (`runtime/engine/instrumentation.py`, `batch_executor.py`, `engine.py`). Re-introduces 700ms litellm cost into eager CLI startup. Cost-key normalization belongs at the producer (LLMNode/ClaudeCodeNode writes `cost_usd` directly).

3. **DON'T encode discriminators in exception message text.** If you need a sub-case, add a structured attribute (e.g., `reason: str`, `kind: str`). Consumers branch on attributes; the message is for humans.

4. **DON'T relax provider-prefix matching to substring.** `openrouter/anthropic/...` is NOT Anthropic for pflow's purposes. The `startswith(provider_prefix)` exact match is intentional.

5. **DON'T patch `pflow.core.llm_client.complete` then expect real-adapter behavior.** That's exactly what the autouse mock does. If you need to test `complete()` itself: `@patch("litellm.completion")` (one layer below) — see `TestAdapterSealContract` for the template.

6. **DON'T use `shared.pop()` for save/restore on keys visible to sub-workflows.** `NamespacedSharedStore` doesn't implement `pop`. Use unconditional write-back (`shared[key] = saved_value`, where `saved_value` may be `None`).

7. **DON'T add provider metadata to `llm_client.py`, `llm_reasoning_map.py`, or `exceptions.py` directly.** Add to `llm_providers.PROVIDERS`. The `o4-*` drift is the cautionary tale — same prefix needed in 3 files; only got 1 right pre-§39.

8. **DON'T assume `cost_usd` is always populated.** LiteLLM returns `None` for unknown-pricing models (custom endpoints, brand-new models, Ollama). All consumers use `.get("cost_usd")`. The trace JSON tri-state (`total_cost_usd`/`partial_cost_usd`/`unavailable_models`/`pricing_available: False`) handles partial pricing.

9. **DON'T drop `provider_message=str(exc)` from any new `_classify_litellm_error` branch.** The seal-contract parametrized test (`test_seam_threads_provider_message_to_every_classification`) catches it, but if you bypass the test it's a real UX regression — agents lose the WHY for that error path.

10. **DON'T mistake a clean test pass for production correctness when the change is in `complete()`.** The autouse mock at `pflow.core.llm_client.complete` bypasses real validation. Add a `TestAdapterSealContract`-style test that patches `litellm.completion` to exercise the real seam. (Two regressions in this branch — smart_filter validation, trace_hook thread-id mismatch — slipped past unit tests for exactly this reason.)

### Test-first recommendations when modifying

1. **Run `tests/test_execution/test_plan_drift.py` first** before any change. 32 tests; sacred. If it ever fails on a change in this area, STOP and investigate.
2. **For adapter changes**: run `tests/test_core/test_llm_client.py` first, with focus on `TestAdapterSealContract`. If the contract test fails, your change leaks raw LiteLLM exceptions.
3. **For exception changes**: run `tests/test_execution/test_executor_service_llm.py`. End-to-end pipeline coverage; failure here means `_diagnostic_context` propagation broke.
4. **For trace changes**: run `tests/test_runtime/test_trace_integration.py`. `TestLLMTraceHookCapture` + `TestSubWorkflowTraceCollector` + `TestParallelBatchSubWorkflowTrace` pin the seam end-to-end.
5. **For provider/reasoning changes**: run `tests/test_core/test_llm_reasoning_map.py` + `tests/test_core/test_llm_providers.py`. `o4-*` regressions and OpenRouter false-positives are caught here.
6. **Final gate**: `make test && make check`. Architectural seal verification:
   ```bash
   grep -rn 'litellm\.exceptions\|^import openai\|^from openai' src/pflow/  # only core/llm_client.py
   grep -rn '^import llm$\|^from llm import' src/pflow/ tests/             # zero hits
   python -X importtime $(which pflow) --version 2>&1 | grep -c litellm    # zero
   ```

### Anti-patterns from review history (each was a real bug we shipped past tests)

- §31's `trace_hook` was wired correctly but never invoked because `_active_collectors[main_thread_id] != worker.thread_id`. Tests existed; they patched at a level that didn't exercise the threading.
- §32's `error_class` field was added to internal dict but `LLMNode.post()` didn't surface it to `shared`. Tests called the internal function and passed; the user-facing JSON never carried the field.
- §34's same pattern recursive: `error_class` set in `shared` but `executor_service._enrich_error_from_node_output` had no LLM branch. Same bug class, one layer up.
- §40's `_validate_model_options` rejected what `smart_filter` was actually passing. Autouse mock bypassed validation; production would have crashed on the first Gemini-3 filtering call.

The lesson across all four: **a test on the boundary you changed is necessary but not sufficient.** Trace where the new contract is consumed; if any layer drops it silently, the test passes and the user-facing behavior breaks. The end-to-end pinning test (`test_real_litellm_exception_provider_message_reaches_runner_diagnostics`) is the explicit guard against this for the LLM error pipeline.

---

*Generated from implementation context of Task 158. Companion to `implementation/progress-log.md` (the session-by-session narrative) and `task-158.md` (the spec). For agents implementing Task 159 (caching), this review + the progress log §27 spike findings + §38 end-to-end verification are the authoritative reference.*
