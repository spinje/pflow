# Task 158: Replace `llm` Library with LiteLLM via pflow-Owned Adapter

## Description

Replace Simon Willison's `llm` library with a pflow-owned adapter (`src/pflow/core/llm_client.py`) backed by LiteLLM. The migration introduces a typed exception hierarchy (`LLMCallError` and structured subclasses), a diagnostic-driven error pipeline (LLM failures flow through `Diagnostic` with `category="llm_failure"` and structured `_diagnostic_context`), and a tracing redesign (replaces the `llm.get_model` monkey-patch with a `shared["__trace_collector__"]` save/restore seam read by the adapter). Drops the `llm` / `llm-anthropic` / `llm-gemini` runtime dependencies. Lazy-imports `litellm` to keep CLI startup fast.

This work was originally Phase 0 + Phase A of [Task 159 (Prompt Caching)](../task_159/task-159.md). It became its own task once implementation revealed the scope was larger than a library swap — the architectural changes (typed exceptions, diagnostic pipeline, tracing) are independently valuable and warrant their own review attention. Task 159 builds on this foundation.

## Status

done

## Completed

2026-04-26

## Priority

high

## Why

**Caching is the motivating use case (Task 159), but the migration ships independently because:**

1. **Substrate, not feature.** Every LLM-using path in pflow now flows through one adapter. Future work (caching, new providers, structured-output evolution, tool use) plugs into a single seam instead of monkey-patching a third-party library.
2. **`llm-anthropic==0.25` blocks caching.** The plugin's `cache: bool` only marks `cache_control` on attachments / last prior user message. System prompts and first-turn user content (where the savings live) cannot be cached. `llm.models.Options` is `extra="forbid"` — no kwarg passthrough or `extra_body` escape hatch. Keeping `llm` and monkey-patching is fragile across plugin upgrades.
3. **LiteLLM is the right substrate.** Unified `cache_control` syntax for Anthropic / Gemini / OpenAI through a single library; Ollama and other local-model runtimes still supported for non-caching use; provider pricing data is comprehensive and up-to-date (LiteLLM's `completion_cost()` replaces the manually-maintained `core/llm_pricing.py` MODEL_PRICING table that was already drifting).
4. **The architectural work is real.** Once the `llm` library was removed, the `model.Options.model_fields` introspection, the `llm.get_model` monkey-patch tracing, the Pydantic `ValidationError` PATTERN EXCEPTION, the per-instance `model.prompt` interception, and the eager `llm` CLI subprocess for key discovery all had to go. Each replacement (hardcoded reasoning-options map, adapter `trace_hook` + `shared["__trace_collector__"]` seam, typed `LLMCallError` hierarchy, env-var-only key discovery) is independently architectural.

## Solution

Three coupled changes shipped together because the migration touches all of them simultaneously:

1. **`src/pflow/core/llm_client.py` — pflow-owned adapter.** Wraps `litellm.completion`. Single seam for every LLM call in pflow. Public API: `complete(*, model, prompt, system, temperature, max_tokens, attachments, schema, reasoning_kwargs, model_options, timeout, trace_hook) -> AdapterResponse`. The `AdapterResponse` dataclass exposes a stable `usage` dict (matching what cost-tracking and trace consumers already expect) and normalizes provider-specific quirks (Anthropic's `cache_*_input_tokens` vs Gemini/OpenAI's `prompt_tokens_details.cached_tokens`, etc.). Cost via LiteLLM's `_hidden_params["response_cost"]` — the deleted `llm_pricing.py` was duplicating data LiteLLM maintains comprehensively.

2. **Typed exception hierarchy + diagnostic pipeline.** `LLMCallError(PflowError)` with structured subclasses: `UnknownModelError(reason: "unknown_name" | "missing_prefix")`, `MissingApiKeyError(kind: "missing_key" | "lacks_permission")`, `InvalidRequestError`, `LLMTransientError`, `LLMResponseParseError`. Each overrides `to_diagnostics()` to produce a `Diagnostic` with `category="llm_failure"`, structured context (`error_class`, `model`, `reason`/`kind`, `provider_message`), and remediation suggestions. The adapter is the SINGLE place that catches LiteLLM exceptions; consumers branch on structured attributes, never on message text. Catches `openai.OpenAIError` (the structural base — `litellm.exceptions.OpenAIError` is a sibling class, not a parent).

3. **Tracing redesign.** Deletes the `llm.get_model` monkey-patch (`runtime/workflow_trace.py:520-599` originally). Replaces it with `shared["__trace_collector__"]` save/restore around `engine.run`'s graph walk; LLMNode reads the collector from shared and passes `collector.get_trace_hook(node_id)` to the adapter. Survives the LLMNode worker-thread boundary (the original implementation broke because `_active_collectors[main_thread_id]` didn't match the inner `ThreadPoolExecutor` worker id). The `llm_prompts` capture mechanism is preserved end-to-end.

## Design Decisions

1. **LiteLLM, not direct SDKs.** Direct SDKs would require two code paths (Anthropic + Gemini); LiteLLM speaks 100+ providers through one surface. Already covers everything pflow needs.

2. **pflow-owned adapter, not direct LiteLLM calls scattered across the codebase.** Single seam = single place to translate exceptions, normalize response shape, fire trace hooks, manage cost extraction. Consumer code (LLMNode, registry/discovery, registry/smart_filter, core/workflow/discovery) never touches LiteLLM directly.

3. **Typed exception hierarchy with structured discriminators, not message-text parsing.** Past the adapter, consumers branch on `e.reason` / `e.kind` attributes. Substring matching across the seam loses signal silently (e.g., when a future LiteLLM message changes wording). The `UnknownModelError(reason="missing_prefix")` pattern is the template — when adding sub-cases, use a structured attribute.

4. **Diagnostic pipeline integration.** LLM failures emit Diagnostics with `category="llm_failure"` (its own category, not generic `"execution_failure"`) because the remediation surface is uniquely structured (auth/permission/model-name discrimination, env-var hints, provider docs links). Cost-gating and retry-gating policies are LLM-specific; agents filter on the category.

5. **`shared["__trace_collector__"]` save/restore, not a per-thread global.** The original Phase A.6 trace_hook design used `_active_collectors[thread_id]` — empirically non-functional because LLMNode runs in an inner `ThreadPoolExecutor` and the worker thread's id never matched the registered main-thread id. The shared-store seam reuses the existing `_PROPAGATED_KEYS` mechanism and survives the threading boundary.

6. **Lazy `import litellm` inside `complete()` and `_classify_litellm_error()`.** Eager top-level import added ~700ms to every CLI invocation (multiplied across subprocess tests, ~30s of suite time). Lazy import keeps non-LLM CLI commands (`--version`, `validate`, non-LLM workflow runs, `--dry-run` on cached workflows) fast. Tradeoff: first LLM call in a process pays the import cost — recorded duration of the first LLM node is inflated by ~700ms. Acceptable for typical multi-call workflows; documented.

7. **Cost from `litellm.completion_cost()`, not from a pflow-maintained pricing table.** The deleted `core/llm_pricing.py` had 41 entries (claimed "46+" — drifted) with hardcoded `2.0` cache-write multiplier (Anthropic only — silently wrong for OpenAI 0.5×, Gemini 0.25×). LiteLLM's pricing data is comprehensive (2,678 entries), per-provider correct, updated per release. New-model-released-but-pricing-missing failures degrade gracefully (`cost_usd: None`, `pricing_available: False` flag in summaries).

8. **Key discovery: env vars only (via existing `inject_settings_env_vars`).** The `llm` CLI subprocess for `llm keys get <provider>` is gone. LiteLLM reads from `os.environ` natively; pflow's existing settings → env-var pipeline still works. Direct read of `~/.config/io.datasette.llm/keys.json` for migrating users is deferred (manual migration via `pflow settings set-env`).

9. **Reasoning-options via hardcoded provider map (`src/pflow/core/llm_reasoning_map.py`).** LiteLLM has no equivalent of `model.Options.model_fields` introspection. Provider/model → reasoning-kwarg mapping by model-name string sniffing. Anthropic Opus 4.5 `thinking_effort` precedence preserved (encoded in the original `_map_reasoning_options` and load-bearing for Opus reasoning quality).

10. **Bare model names auto-prefixed.** Settings CLI normalizes at write time with user-visible feedback (`gemini-3-flash-preview` → `gemini/gemini-3-flash-preview`); adapter normalizes as a safety net for model names from workflow files. Mapping: `claude-*` → `anthropic/`, `gemini-*` → `gemini/`, `gpt-*`/`o1-*`/`o3-*`/`o4-*` → `openai/`. Unknown bare names pass through unchanged.

11. **`APIConnectionError` from missing SDK is permanent, not transient.** Walks the `__cause__` chain for `ImportError`. Without this, missing-Vertex-SDK errors (when a user has `gemini-3-flash-preview` bare which routes to Vertex AI) burn 3 retries on a permanent failure.

12. **LiteLLM ERROR logger silenced.** `logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)` inside `complete()`. The adapter's typed exception system is the single error surface; LiteLLM's logged tracebacks are redundant noise that reaches stderr before the adapter can produce a clean message.

## Out of Scope

Caching syntax (`## Cache` block, `prompt_cache:`, `prewarm:`, `pflow analyze-cache`, MCP `analyze_cache` tool, trace format 2.1.0 cache fields, deterministic serialization, `--dry-run` cache nudge) → all in Task 159.

ClaudeCodeNode caching → out of scope for both tasks; the `claude_agent_sdk` handles cache transparently.

## Verification

- `make test` — full suite green (5325+ tests as of HEAD).
- `make check` — ruff, ruff-format, mypy, deptry all green.
- `tests/test_execution/test_plan_drift.py` — 32 sacred parity tests green throughout the migration.
- Architectural seal: `grep -rn 'import litellm.exceptions\|from litellm.exceptions' src/pflow/` returns exactly 1 match (`core/llm_client.py`); `grep -rn 'import openai\|from openai' src/pflow/` returns exactly 1 match (same file). No consumer outside the adapter imports either.
- `grep -rn '^import llm$\|^from llm import' src/pflow/ tests/` returns zero hits (no live `llm` library references).
- `uv pip list | grep -iE '^(llm|llm-)'` returns empty (only `litellm` present).
- Performance: `pflow --version` < 350ms (was ~1.2s pre-perf-fix); `pflow run` of cached workflow < 350ms; `make test` parallel run ~18-20s.
- End-to-end smoke test against real Gemini-3-flash-preview confirms `event["llm_prompt"]`, `event["llm_response"]`, `event["llm_call"]` all populate in trace JSON; `cost_usd` matches LiteLLM's `_hidden_params["response_cost"]`; `total_cost_usd` rolls up correctly.
- All current LLM workflows (lyrics-generator and others) run identically to pre-migration behavior.

## Implementation Status

Implementation complete in this branch. See `implementation/progress-log.md` for the full session-by-session narrative (sessions §27 through §37 cover Phase 0 spike, Phase A.1–A.12, three rounds of code review, perf fix, and end-to-end verification).

The implementation plan (`implementation/implementation-plan.md`) documented the original Phase 0 + Phase A scope; the actual implementation grew beyond it as architectural needs surfaced. The progress log is the authoritative record of what shipped and why each scope expansion was justified.

Six follow-up GitHub issues (#347-#352) capture non-blocking review findings deferred from this branch:

- #347 — standardize node prep validation diagnostics
- #348 — centralize LiteLLM provider metadata for UX hints
- #349 — clarify reasoning option edge cases and observability
- #350 — normalize zero and partial LLM cost display
- #351 — improve batch LLM trace and warning aggregation
- #352 — polish secondary LLM diagnostic context

## References

### Related Tasks

- **Task 159 — Prompt Caching via Declarative `## Cache` Block** (downstream — uses this adapter as its substrate).
- Task 95 — Unified LLM Usage via Simon Willison's `llm` Library (the work being replaced).
- Task 66 — Structured Output for LLM Node (preserved through the adapter; `response_format` continues to work).
- Task 108 — Smart Trace Debug Output (trace format 2.0.0; this task does not change format version, but Task 159 will bump to 2.1.0).
- Task 143/144/147 — Unified Diagnostic System (Diagnostic class extended with `LLMCallError.to_diagnostics()` overrides in this task).
- Task 152 — MCP Server CLI Surface Parity.

### Provider Documentation

- LiteLLM: https://docs.litellm.ai/docs/
- LiteLLM exception types: https://docs.litellm.ai/docs/exception_mapping
- LiteLLM providers list: https://docs.litellm.ai/docs/providers
