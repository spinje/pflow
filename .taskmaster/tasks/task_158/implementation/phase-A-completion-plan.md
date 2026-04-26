# Phase A Completion — Typed-Exception Architecture + Sweeps

## Context

Phase A migrated pflow from Simon Willison's `llm` library to LiteLLM (see `progress-log.md` §27–§33). After §31's first review and §32's adapter-seal commit, a follow-up `/code-review` (4 agents in parallel: review-concurrency-safety, review-impact-completeness, review-silent-failures, review-agent-ux) surfaced 3 critical issues, 7 high-value, and 6 polish.

**The pattern across critical and high findings:** §32 fixed the discriminator-loss / dead-field bugs at the **adapter→LLMNode** seam (e.g. `UnknownModelError(reason="missing_prefix")` survives via structured attribute, not message text). The new findings show **the same pattern recurring at the LLMNode→executor→JSON-output seam**: `error_class` is set in shared but never reaches the JSON output an agent reads; rich error remediation lives only in `LLMNode._call_llm` and is duplicated/lost by every other adapter caller; `smart_filter`'s narrow except tuple was sized to a LiteLLM exception ladder it can't actually reach (verified: `litellm.exceptions.Timeout` is NOT a `TimeoutError` subclass).

This plan completes the typed-exception architecture so the same pattern doesn't need a third closure cycle.

## Architectural rationale

> "Simplicity of the FINAL code, not how easy it is to get there. What's the right solution that the top 10% of codebases similar to this one would implement?" — user load-bearing principles

**End-state architecture (the goal):**

1. **The exception is the source of truth** for what an LLM error means. Each `LLMCallError` subclass overrides `to_diagnostics()` to emit a rich `Diagnostic` with structured context (`error_class`, `model`, `reason`/`kind`) and remediation suggestions. The override is the single place that knows the prose.
2. **The adapter is the single seam** that translates LiteLLM exceptions to typed pflow exceptions. ALL deterministic and transient LiteLLM exceptions are translated — nothing leaks raw past the adapter. The architectural seal (`grep` returns exactly one `import litellm.exceptions`) stays intact.
3. **One catch at the LLMNode boundary** consumes the typed exception and produces a structured error dict. The `_diagnostic_context` from the exception's own `to_diagnostics()` flows through shared store into the runtime Diagnostic, so JSON output carries the same structured fields the exception's override produced.
4. **smart_filter and discovery callers catch the umbrella `LLMCallError`** — one clause covers every subclass (deterministic + transient). They get the same rich Diagnostic for free via `e.to_diagnostics()` if they need to render.
5. **Empty-response warnings flow through the existing `__warnings__` infrastructure** — agents see them as JSON `warnings` entries and the workflow shifts to `DEGRADED` status. No new infrastructure invented; `logger.warning` is replaced by structured emission.

This deletes ~80 lines of duplication (`_error_dict`, `_api_key_tip`, the typed-catch chain in `_call_llm`, three discovery callers' implicit error handling) and replaces them with ~60 lines of `to_diagnostics()` overrides that every consumer benefits from.

## Design decisions

### D1. `LLMTransientError(LLMCallError)` is added.

The adapter currently translates 4 deterministic LiteLLM exceptions and lets `Timeout`/`RateLimitError`/`InternalServerError` propagate raw. This is the gap that broke smart_filter. **Decision: extend the seam to translate these too.** `LLMTransientError` is a marker subclass — its presence signals "transient; the retry loop should retry; smart_filter should swallow." LLMNode's `_call_llm` adds one line — `except LLMTransientError: raise` — ahead of the typed-error catch chain, so the retry loop's existing behavior is preserved (catches `Exception`, retries 3×, falls to `exec_fallback`).

`JSONSchemaValidationError` and `APIResponseValidationError` stay outside the translation set — they're arguably-transient (different sample might succeed) but **deterministic in shape** (the model is bad at the schema); `parse_structured_response` already surfaces them as `LLMCallError` on the post-response path. Don't pre-empt.

### D2. `to_diagnostics()` overrides go on each `LLMCallError` subclass.

The PflowError pattern is established (`SchemaValidationError`, `WorkflowNotFoundError`, `MarkdownParseError`, `CompilationError`, `MaxNodeVisitsError`, `OutputResolutionError`, `UserFriendlyError` all override). Each LLMCallError subclass produces a `Diagnostic(severity=ERROR, source="runtime", category="llm_failure", context={...}, suggestions=[...], see_also=...)` with structured fields plus user-facing prose. New CATEGORY_TITLES entry: `"llm_failure": "LLM Call Failed"`.

### D3. `LLMCallError` gains `model: str` constructor arg.

Currently the model name is shoved into the message text. **Promote it to a structured attribute** so every `to_diagnostics()` override has it without parsing. Adapter passes `model=model` explicitly when raising. Mirrors the `reason` attribute pattern §32 introduced on `UnknownModelError`.

### D4. `MissingApiKeyError` gains `kind: Literal["missing_key", "lacks_permission"]`.

Mirrors `UnknownModelError.reason`. Today the discriminator survives only via `Detail: {e}` line append — fragile to upstream message rewording. Structured attribute is the §32 lesson applied symmetrically.

### D5. Rich error info flows through `node_output["_diagnostic_context"]`.

`LLMNode._call_llm` catches typed `LLMCallError`, calls `e.to_diagnostics()[0]` once, stores `diagnostic.context` (a dict) in the error dict under `"_diagnostic_context"`. `LLMNode.post()` propagates the entire error dict to `shared[node_id]` (which lands in `__failures__[id]["data"]` via `mark_node_failed`'s archive). `executor_service._enrich_error_from_node_output` adds an LLM branch that reads `_diagnostic_context` from `node_output` and merges it into the runtime `Diagnostic.context`.

Net: the runtime Diagnostic that reaches JSON output has the SAME context fields the exception's `to_diagnostics()` override produced. One source of truth for structured info; no duplication between LLMNode hand-built dicts and exception overrides.

The leading `_` on `_diagnostic_context` is a value-side convention (private/intermediate) — it has no effect on `NamespacedSharedStore` namespacing (that only routes shared-store KEYS).

### D6. `_error_dict` and `_api_key_tip` helpers are deleted.

Their job — building rich prose with model name, API-key-tip detection, docs URLs — moves entirely into `MissingApiKeyError.to_diagnostics()` and `UnknownModelError.to_diagnostics()`. The detected-model lookup (`get_default_llm_model()` for the "your key supports X" tip) moves with it. LLMNode just consumes `e.to_diagnostics()[0].message`.

### D7. Empty-response warning flows through `__warnings__`, not `logger.warning`.

`_normalize` in `core/llm_client.py` populates a new `AdapterResponse.warnings: list[str]` field with structured warning text. `LLMNode.post()` reads `prep_res["adapter_response"].warnings` and writes each to `shared.setdefault("__warnings__", {})[self.node_id] = warning_text` (precedent: `batch_executor.py:812-814` does this idiom; runtime/CLAUDE.md notes direct writes are usually contract violations, but batch's existing direct-write is documented intent — same applies here).

The detection covers all empty-content `finish_reason` cases: `"length"|"max_tokens"` (token budget exhausted), `"content_filter"` (provider blocked), `"tool_calls"` (model called tools, no content), `"stop"` with empty content (model chose to stop with nothing), `None` (provider didn't report). Each emits remediation appropriate to the case. Reasoning-model trap (`output_tokens > 0 and not text and finish_reason in ("length", "max_tokens")`) gets BOTH remediations: "increase max_tokens OR lower reasoning_effort" — the second one was missing per review-agent-ux #2.

### D8. `_trace_collector` → `__trace_collector__` rename.

Aligns with the existing `__failures__`/`__warnings__`/`__progress_callback__`/`__sub_workflow_events__` convention. `NamespacedSharedStore.__setitem__` routes `__*__` keys to the root parent dict deterministically (vs. the current behavior where `_trace_collector` lands inside `parent[child_namespace]["_trace_collector"]` because `_x` matches the "user data → namespaced" rule). Today this works because reads and writes both pass through the proxy; tomorrow's debugger or new formatter iterating the root dict would silently miss it.

Mechanical rename across consumers: `runner.py`, `workflow_executor.py:_PROPAGATED_KEYS`, `engine.py` save/restore, `nodes/llm/llm.py::prep`, formatters (`success_formatter.py:64`, `error_formatter.py:84`, `cli/error_output.py:134`), tests.

### D9. New failure category `FAILURE_CATEGORY_LLM`.

`runtime/node_state.py`'s failure-category constants map node failures to taxonomy. LLMNode failures currently archive as `FAILURE_CATEGORY_NODE_ERROR` and surface in JSON as `category="execution_failure"` (a generic catch-all). Adding `FAILURE_CATEGORY_LLM` → mapped to `"llm_failure"` in `_FAILURE_CATEGORY_MAP` lets agents filter on category alone. Engine's `_NODE_TYPE_FAILURE_CATEGORY` registers `LLMNode → FAILURE_CATEGORY_LLM`.

### D10. Top-level cost tri-state mirroring.

`success_formatter.py:70` writes top-level `result["total_cost_usd"]` directly. When pricing is unavailable, this is bare `null` — agents can't distinguish "no LLM calls" from "calls happened, pricing missing." Mirror `partial_cost_usd` and `pricing_available` to top level when present, so the discriminator is at the level agents are most likely to read.

## Implementation steps

Each step is a separate commit. `make test` and `make check` green at every step. `tests/test_execution/test_plan_drift.py` (32 tests, sacred parity invariant) green throughout.

### Step 1 — Extend exception hierarchy (`src/pflow/core/exceptions.py`)

- Modify `LLMCallError.__init__` to accept `model: str | None = None` (positional after message). Store as `self.model`.
- Add `LLMTransientError(LLMCallError)` — marker subclass, no extra attributes. Docstring documents semantics (transient; let retry loop handle).
- Modify `MissingApiKeyError.__init__` to accept `kind: Literal["missing_key", "lacks_permission"] = "missing_key"`. Store as `self.kind`.
- Override `to_diagnostics()` on each subclass:
  - `LLMCallError` (base): `Diagnostic(severity=ERROR, source="runtime", message=str(self), title=CATEGORY_TITLES["llm_failure"], context={"category": "llm_failure", "error_class": type(self).__name__, "model": self.model})`. No suggestions (subclasses fill in).
  - `LLMTransientError`: inherits base; suggestions list mentions retry/backoff.
  - `UnknownModelError`: branches on `self.reason`. For `"missing_prefix"`: suggestions about provider prefix syntax + LiteLLM provider list URL + `pflow settings llm show`. For `"unknown_name"`: suggestions about checking model availability for the configured key. Context adds `reason` and (when known) `suggested_prefix`.
  - `MissingApiKeyError`: branches on `self.kind`. For `"missing_key"`: suggestions for `pflow settings set-env <KEY>` and shell `export`. For `"lacks_permission"`: suggestions about provider tier/access. Context adds `kind` and (when derivable) `env_var`.
  - `InvalidRequestError`: suggestions surface the provider message verbatim ("This is typically caused by an invalid parameter; check the request shape against your provider's docs"). Context adds `provider_message=str(self)`.
- Add `"llm_failure": "LLM Call Failed"` to `CATEGORY_TITLES` in `src/pflow/core/diagnostic.py`.

**Tests** (new file `tests/test_core/test_exceptions_llm_diagnostics.py`):
- One test per subclass × variant (5+ tests) asserting `to_diagnostics()[0]` returns a Diagnostic with expected `category`, `error_class`, `model`, `reason`/`kind`, and a non-empty `suggestions` list. Verify the context dict is JSON-serializable.

### Step 2 — Adapter translation + warnings (`src/pflow/core/llm_client.py`)

- Extend the catch tuple in `complete()` from 4 classes to 7: add `litellm.exceptions.Timeout`, `RateLimitError`, `InternalServerError`. Update `_classify_litellm_error` to translate these to `LLMTransientError(message=str(exc), model=model)`.
- Pass `model=model` to every typed exception constructor (`UnknownModelError`, `MissingApiKeyError`, `InvalidRequestError`, `LLMTransientError`).
- For `MissingApiKeyError`, set `kind="missing_key"` from `AuthenticationError` and `kind="lacks_permission"` from `PermissionDeniedError`.
- Add `warnings: list[str] = field(default_factory=list)` to `AdapterResponse`.
- In `_normalize`, replace the `logger.warning(...)` empty-content emission with `warnings.append(...)`. Cover the full finish_reason matrix (case-by-case messages):
  - `length` / `max_tokens` + `output_tokens > 0` + reasoning model: dual remediation ("Increase max_tokens or lower reasoning_effort"). Pass thinking_budget context to detect.
  - `length` / `max_tokens` + non-reasoning: single remediation ("Increase max_tokens").
  - `content_filter`: "Provider blocked the response (content filter). Adjust prompt to avoid the trigger."
  - `tool_calls`: silent (this is an expected LiteLLM shape; no warning needed unless we surface it later).
  - `stop` with empty content: "Model returned no content. Check prompt; the model chose to stop without output."
  - `None`: "Provider did not report a finish_reason; response is empty. Investigate the response shape."

**Tests** (extend `tests/test_core/test_llm_client.py`):
- `Timeout` / `RateLimitError` / `InternalServerError` translation → `LLMTransientError` (3 tests).
- `model` attribute populated on every typed exception (covered via existing parametrized tests).
- `MissingApiKeyError.kind == "missing_key"` from `AuthenticationError`; `kind == "lacks_permission"` from `PermissionDeniedError`.
- `AdapterResponse.warnings` populated for each finish_reason case (5 tests, parametrized).

### Step 3 — Simplify LLMNode (`src/pflow/nodes/llm/llm.py`)

- DELETE module-level helpers: `_error_dict`, `_api_key_tip` (~50 lines).
- Rewrite `_call_llm` exception block:
  ```python
  except LLMTransientError:
      raise  # let retry loop handle
  except LLMCallError as e:
      diagnostic = e.to_diagnostics()[0]
      return {
          "status": "error",
          "error": diagnostic.message,
          "error_class": type(e).__name__,
          "model": e.model,
          "response": "",
          "_diagnostic_context": dict(diagnostic.context or {}),
      }
  ```
  All three previous typed-catch branches collapse into the single `except LLMCallError as e`. Rich text comes from the override.
- `exec_fallback` keeps the timeout substring detection (Phase A's accepted seal-preserving pattern) but the message construction now reads from a shared util OR builds inline. Keep the simple form.
- `post()` propagates `_diagnostic_context` through to shared (along with `error`, `error_class`, `model`, `response`). Add JSON-parse error path: when schema parsing fails, ALSO populate `error_class="LLMResponseParseError"` (or mirror exception type if we add a typed exception for it; otherwise use string label). This closes critical #3.
- `post()` reads `adapter_response.warnings` and emits to `__warnings__`:
  ```python
  for warning_text in adapter_response.warnings:
      shared.setdefault("__warnings__", {})[self.node_id] = warning_text
  ```
  (Direct write — precedent at `batch_executor.py:812-814`. Document in inline comment.)

**Tests** (rewrite affected tests in `tests/test_nodes/test_llm/test_llm.py`):
- Existing typed-catch tests (`test_unknown_model_surfaces_error_class`, `test_missing_prefix_branch_message`, `test_needs_key_exception_handling`, `test_permission_denied_preserves_lacks_permission_detail`) updated: assertions now check `shared["_diagnostic_context"]` structure (or `shared[node_id]["_diagnostic_context"]`) instead of substring-matching the prose `shared["error"]`. **Tighten** to assert `_diagnostic_context["reason"]` / `_diagnostic_context["kind"]` directly.
- New: `test_llm_transient_error_propagates_to_retry_loop` — patch adapter to raise `LLMTransientError`, assert `node.run()` triggers retry (uses Node's `cur_retry` increment).
- New: `test_post_writes_warnings_to_shared` — mock adapter response with warnings, assert `shared["__warnings__"]` populated.
- New: `test_json_parse_failure_surfaces_error_class` — schema mode with malformed JSON response, assert `shared["error_class"]` is set.

### Step 4 — Wire LLM branch into executor (`src/pflow/execution/executor_service.py`)

- Add LLM branch in `_enrich_error_from_node_output(context, node_output, category)` (after the existing shell/HTTP/MCP/template branches):
  ```python
  if "_diagnostic_context" in node_output:
      # LLM failure: lift the structured context produced by the exception's to_diagnostics().
      llm_ctx = node_output["_diagnostic_context"]
      if isinstance(llm_ctx, dict):
          for key, value in llm_ctx.items():
              context.setdefault(key, value)
  ```
- Add mapping in `_FAILURE_CATEGORY_MAP`: `FAILURE_CATEGORY_LLM → "llm_failure"`.

**Tests** (`tests/test_execution/test_executor_service.py` or similar — create if absent):
- LLM failure end-to-end: mock LLMNode failure, run through Runner, assert `format_error_json()` output's `errors[0].context` contains `error_class`, `model`, `reason`/`kind`.

### Step 5 — Engine failure routing (`src/pflow/runtime/engine/engine.py` + `node_state.py`)

- Add `FAILURE_CATEGORY_LLM = "llm_failure"` constant in `runtime/node_state.py`.
- Add `LLMNode → FAILURE_CATEGORY_LLM` to `_NODE_TYPE_FAILURE_CATEGORY` in `engine.py` (verify this dict's exact location during implementation).

**Tests:**
- Run a failing LLM workflow, inspect `__failures__[node_id]["category"]`, assert `"llm_failure"`.
- `test_plan_drift.py` MUST stay green (sacred). Adding a new category should not affect plan-vs-runtime hash equality, but verify after the change.

### Step 6 — Simplify smart_filter + discovery (`src/pflow/registry/`)

- `smart_filter.py`: replace `except (LLMCallError, ConnectionError, TimeoutError, OSError):` with `except LLMCallError:` (umbrella catches deterministic + transient subclasses; `LLMTransientError` is now a `LLMCallError` subclass). Add a separate `except (ConnectionError, OSError):` clause if cold network errors (DNS, etc.) are still expected to degrade. **Keep programming errors propagating** (the §31 lesson).
- Update related tests (`test_smart_filter.py`):
  - Existing `test_llm_failure_returns_original` assertions keep working (LLMCallError still caught).
  - **Add** `test_transient_error_returns_original` — patch `complete` to raise `LLMTransientError`, assert smart_filter degrades gracefully.
  - **Add** test verifying programming errors still propagate (regression guard for §31's narrow-except contract).
- `registry/discovery.py` and `core/workflow/discovery.py`: review their `complete()` calls. With `to_diagnostics()` overrides, propagated `LLMCallError` exceptions now produce rich Diagnostics via the pre-execution path (`cli/error_output.py::_format_from_exception` → `exception_to_diagnostics`). This is automatic; no code changes needed in discovery itself, BUT the `cli/find_errors.py:35` branch (review-impact-completeness #1) needs updating: catch `MissingApiKeyError`/`UnknownModelError` and surface their `to_diagnostics()` Diagnostic instead of the generic "report a bug" branch.

### Step 7 — Rename `_trace_collector` → `__trace_collector__`

Mechanical, all consumers in one commit:
- `src/pflow/runtime/engine/engine.py` (save/restore in `run()`)
- `src/pflow/execution/runner.py:490` (initial set)
- `src/pflow/runtime/workflow_executor.py:118-126` (`_PROPAGATED_KEYS`)
- `src/pflow/nodes/llm/llm.py::prep` (the read site; reads `shared.get("__trace_collector__")`)
- `src/pflow/execution/formatters/success_formatter.py:64` (the read)
- `src/pflow/execution/formatters/error_formatter.py:84`
- `src/pflow/cli/error_output.py:134`
- All test files (grep `_trace_collector`)
- The deleted `enable_llm_interception` setter / class state — already gone post-§31; just confirm no resurrection.

**Verification:** `grep -rn '"_trace_collector"\|"_trace_collector"' src/pflow/ tests/` returns zero hits after the rename.

### Step 8 — Top-level cost tri-state (`success_formatter.py` + `workflow_trace.py`)

- `success_formatter.py:60-77`: when `metrics_summary["pricing_available"] is False`, mirror these to top level alongside `total_cost_usd: null`:
  - `result["partial_cost_usd"]`
  - `result["pricing_available"] = False`
  - `result["unavailable_models"] = [...]`
- Document in `docs/changelog.mdx` Unreleased entry.

**Tests:**
- Success formatter test: workflow with mixed priced/unpriced models, assert top-level mirrored fields.

### Step 9 — Hardcoded model fallback prefix (`src/pflow/core/llm_config.py`)

- Line 103: `"gpt-5.2"` → `"openai/gpt-5.2"`.
- `get_model_not_configured_help()`: prefix every example model name (`gpt-5.2` → `openai/gpt-5.2`, etc.).

**Tests:**
- Update existing tests for `_detect_default_model` to assert the prefix.

### Step 10 — Mechanical doc/example sweep

15+ files identified by review-impact-completeness #5. Provider-prefix every bare model name. List:

- `src/pflow/guide/nodes/llm.md:24`
- `src/pflow/guide/features/batch.md:109,112`
- `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md:785`
- `src/pflow/mcp_server/resources/instructions/mcp-sandbox-agent-instructions.md:782`
- `docs/quickstart.mdx:58`
- `docs/guides/debugging.mdx:115`
- `docs/reference/cli/settings.mdx:366,372`
- `docs/reference/configuration.mdx:86`
- `docs/how-it-works/batch-processing.mdx:333,359`
- `docs/how-it-works/template-variables.mdx:227`
- `docs/reference/nodes/llm.mdx:147`
- `examples/test_llm_templates.pflow.md:38`
- `examples/test-worktree.pflow.md:75`
- `examples/real-workflows/release-announcements/workflow.pflow.md:69,103,156`
- `examples/real-workflows/vision-scraper/workflow.pflow.md:79`

Plus stale CLAUDE.md text fixes:
- `src/pflow/core/CLAUDE.md:186` (deleted `BadRequestError → error-marked response` contract description)
- `src/pflow/cli/commands/CLAUDE.md` (settings section still describes deleted `llm CLI default` resolution tier)

Plus the README example: `src/pflow/nodes/llm/README.md` references a non-existent `pflow llm --prompt=...` CLI command (review-impact-completeness #7) — defer if pre-existing, fix if Phase A introduced; verify during step.

## Test strategy

**New test files:**
- `tests/test_core/test_exceptions_llm_diagnostics.py` — `to_diagnostics()` overrides per subclass.
- `tests/test_execution/test_executor_service_llm.py` (or extend existing) — `_enrich_error_from_node_output` LLM branch.

**Extended test files:**
- `tests/test_core/test_llm_client.py` — `LLMTransientError` translation, `model`/`kind` attributes, `AdapterResponse.warnings` population.
- `tests/test_nodes/test_llm/test_llm.py` — error-path assertions tightened to read `_diagnostic_context` instead of substring-matching prose; new tests for transient propagation, warnings emission, JSON-parse error_class.
- `tests/test_registry/test_smart_filter.py` — `LLMTransientError` graceful degradation.
- `tests/test_runtime/test_workflow_trace.py` — `__trace_collector__` rename verification.
- `tests/test_execution/formatters/` — top-level cost tri-state.

**Pinned invariants:**
- `tests/test_execution/test_plan_drift.py` — 32 sacred tests, must stay green at every commit.
- Architectural seal: `grep -rn 'import litellm\.exceptions\|from litellm\.exceptions' src/pflow/` returns exactly 1 match (`core/llm_client.py:35`).
- All `pflow guide` content + example workflow files run successfully (mechanical sweep didn't introduce typos).

## Verification

### After Step 6 (architectural completion)

- `make test` green
- `make check` green (ruff, ruff-format, mypy, deptry)
- `tests/test_execution/test_plan_drift.py` 32/32 green
- `grep -rn 'import litellm\.exceptions' src/pflow/` returns 1 match
- LLMNode line count reduction: ~80 lines of `_error_dict`/`_api_key_tip`/typed-catch branches replaced with single `except LLMCallError` block. Verify by running `wc -l src/pflow/nodes/llm/llm.py` pre/post.

### After Step 10 (sweeps)

- All `pflow guide` snippets contain provider-prefixed model names.
- `pflow run examples/real-workflows/release-announcements/workflow.pflow.md` doesn't fail with `UnknownModelError(reason="missing_prefix")`.

### Real-API smoke tests (~$0.001 total)

1. **Empty-response trap.** Run a workflow with `model: gemini/gemini-3-flash-preview`, `max_tokens: 16`, low `reasoning_effort`. Verify:
   - Workflow status: `DEGRADED` (not SUCCESS).
   - `result["warnings"]` contains an entry with the dual remediation message.
   - Trace JSON has the warning in `trace_data["warnings"]`.
2. **Auth failure JSON output.** Run a workflow with a model whose env var isn't set. `pflow --output-format json failing.pflow.md`. Verify:
   - `result["errors"][0]["context"]["error_class"] == "MissingApiKeyError"`
   - `result["errors"][0]["context"]["model"] == "<the model>"`
   - `result["errors"][0]["context"]["kind"] == "missing_key"`
   - `result["errors"][0]["context"]["category"] == "llm_failure"`
3. **Provider-prefix typo.** Run a workflow with `model: gpt-5.2` (no prefix). Verify the JSON shows `error_class: UnknownModelError`, `reason: missing_prefix`, and the suggestion list contains the LiteLLM provider list URL + a corrected example.

## Risks and mitigations

**R1. `_trace_collector` rename ripples through 7+ consumers.** Mitigation: do the rename in a single atomic commit; grep verifies zero stragglers; test_plan_drift catches engine-level regressions immediately.

**R2. `to_diagnostics()` overrides change the user-facing error message text.** Some existing tests assert exact substrings. Mitigation: tighten those tests to assert on structured context fields (`reason`, `kind`, `error_class`) rather than prose. The structured fields are the real contract; prose is rendering.

**R3. `FAILURE_CATEGORY_LLM` addition could affect `_FAILURE_CATEGORY_MAP` hash semantics in `compute_node_config`.** Verify after step 5: existing workflows should hash identically. (Categories aren't in the hash, but defense-in-depth check.)

**R4. Empty-response warnings as a `__warnings__` write from LLMNode.post is technically a "direct write" the runtime CLAUDE.md flags as a contract violation.** Mitigation: `batch_executor.py:812-814` precedent exists; document the call site with an inline comment AND update `runtime/CLAUDE.md:52` to acknowledge LLMNode as a second precedent (or formalize: extend `mark_node_failed` to support warning-only mode without failure — bigger change, deferred unless reviewers push back).

**R5. `LLMTransientError` adds a class to the public exception API.** Anyone catching `LLMCallError` already covers it. Anyone catching `Exception` covers it. The only at-risk pattern is `except (UnknownModelError, MissingApiKeyError, InvalidRequestError):` — which would now miss transient errors. Mitigation: search for this triple-tuple pattern; expect zero hits outside test code.

## Out of scope (deferred to follow-up)

These polish items don't block PR:

- **Polish #12** — `_extract_thinking_budget` returns 0 silently for OpenAI `reasoning_effort` / Gemini-3 `thinking_level` (categorical reasoning). Either add `reasoning_mode: "categorical" | "token_budget" | None` field, or skip the utilization section. Defer to a thinking-metrics polish task.
- **Polish #13** — `exec_fallback` substring detection on `"timed out"` is fragile to non-timeout exceptions whose message contains the substring. Acknowledged trade-off (preserves architectural seal); revisit if a real misclassification surfaces.
- **Polish #14** — `_append_batch_stats` partial-cost drop in `trace_report.py:1049-1052`. Mirror the tri-state from `_collect_llm_summary`. Small, but tangential to the typed-exception completion theme; defer.
- **Polish #15** — `total_cost > 0` cost-hide pattern in 4 sites. Pre-existing Task 108 pattern; defer to a dedicated cost-display fix.
- **Polish #16** — `prep()` `ValueError` for missing image file + `_validate_timeout` bare `ValueError`. Convert to `PflowError` subclasses. Defer to a node-error-consistency follow-up.

## Commit sequence (10 commits)

1. **exc(llm): rich to_diagnostics overrides + LLMTransientError + model attribute** — Step 1.
2. **adapter(llm): translate transient errors + structured warnings field** — Step 2.
3. **node(llm): consume to_diagnostics, drop helper duplication, route warnings to __warnings__** — Step 3.
4. **executor: LLM branch in _enrich_error_from_node_output** — Step 4.
5. **engine: FAILURE_CATEGORY_LLM routing for LLMNode** — Step 5.
6. **registry: smart_filter umbrella catch; cli/find_errors LLMCallError branch** — Step 6.
7. **runtime: rename _trace_collector → __trace_collector__** — Step 7.
8. **formatter: top-level cost tri-state mirroring** — Step 8.
9. **config: provider-prefix the gpt-5.2 default fallback** — Step 9.
10. **docs: provider-prefix model names in 15+ files; CLAUDE.md drift fixes** — Step 10.

If any commit fails verification, stop and resolve before proceeding.

## Definition of done

- All 10 steps committed; `make test` and `make check` green at HEAD.
- `tests/test_execution/test_plan_drift.py` 32/32 green at every commit.
- 3 real-API smoke tests pass (above).
- Critical findings #1, #2, #3 verified resolved by tests + smoke runs.
- High-value findings #4, #5, #6, #7, #8, #9, #10 verified resolved.
- Architectural seal intact: `grep -rn 'import litellm\.exceptions' src/pflow/` returns 1 match.
- Branch ready for an independent code review (separate /code-review pass with 3-4 agents) before PR.

---

## v1.1 Revisions (after plan-review by 3 agents — review-plan, review-impact-completeness, review-validation-consistency)

The original plan above (v1.0) is structurally correct. Plan-review surfaced 6 critical gaps, 7 high-value gaps, and several quality improvements. Each is addressed below. Apply during implementation; v1.0 sections are otherwise still authoritative.

### R-Crit-1. Step 4/5 explicitly names files for category-map updates

**Risk:** Plan v1.0 D9 + Steps 4/5 say "add `FAILURE_CATEGORY_LLM → 'llm_failure'` to `_FAILURE_CATEGORY_MAP`" without naming the file. The map lives in `src/pflow/execution/executor_service.py:29-38`. Without this entry, `_map_failure_category_to_diagnostic("llm_failure")` would default to `"execution_failure"`, silently downgrading the new category and defeating D9.

**Revision:** Step 4 now reads:
> Add LLM branch in `src/pflow/execution/executor_service.py::_enrich_error_from_node_output` (after the existing shell/HTTP/MCP/template branches) AND add `FAILURE_CATEGORY_LLM: "llm_failure"` entry to `_FAILURE_CATEGORY_MAP` in the same file (lines 29-38).

### R-Crit-2. Single-source-of-truth constant for category string

**Risk:** Plan v1.0 has `"llm_failure"` literal in two places: the `to_diagnostics()` overrides (Step 1 — fires on the pre-execution path via `cli/error_output.py::_format_from_exception`) and `_FAILURE_CATEGORY_MAP` (Step 4 — fires on the runtime path via `__failures__`). They MUST stay synchronized; if one drifts, the pre-execution and runtime JSON outputs diverge silently.

**Revision:** Introduce `LLM_FAILURE_CATEGORY = "llm_failure"` constant in `src/pflow/core/diagnostic.py` alongside `CATEGORY_TITLES`. Reference it from both the override and the map. Single source of truth.

### R-Crit-3. `_NODE_TYPE_FAILURE_CATEGORY` routing is partial

**Verified at `src/pflow/runtime/engine/engine.py:55-59` (the dict) and line 493 (the consumer):** the dict is keyed by `config.node_type_name` and consulted ONLY when the node returned an `"error"` action through step 17.5. For LLMNode failures via the `_call_llm` typed-error path, this works (post returns `"error"` action, step 17.5 fires, `LLMNode → FAILURE_CATEGORY_LLM` matches). BUT: any `LLMCallError` that escapes to the engine's exception path (e.g., `parse_structured_response` raising in `post()`) is archived as `FAILURE_CATEGORY_EXCEPTION`, not LLM.

**Revision:** Plan acknowledges this routing asymmetry. Two acceptable resolutions:
- **(a)** Accept it: most LLMCallErrors today come through `_call_llm`, so the rare `post()` escape lands in `execution_failure`. The structured `error_class`/`model`/`reason`/`kind` still flow via `_diagnostic_context`, so agents can still discriminate.
- **(b)** Catch `LLMCallError` in `post()` too, build the same error dict shape, return `"error"` action. This makes routing uniform.

**Decision: (b)** — `post()` catches `LLMCallError` from `parse_structured_response`, builds the error dict (same helper as `_call_llm`), returns `"error"`. Preserves uniform `category="llm_failure"` for ALL LLM failures.

### R-Crit-4. `_trace_collector` rename — exhaustive consumer enumeration

**Verified by grep against current branch:** the rename radius is 14+ production sites + ~10 test sites, including a load-bearing filter at `src/pflow/runtime/workflow_trace.py:313` (`if key in ("_trace_collector", "_debug_context", "_batch_trace"): continue`) AND a test at `tests/test_runtime/test_workflow_trace.py:174` asserting `"_trace_collector" not in filtered_output`. Plan v1.0 listed only 8 sites.

**Revision:** Step 7 expanded to:
- **Production sites (14):**
  - `src/pflow/runtime/engine/engine.py` — lines 161, 175, 180, 182, 186, 323 (impl + docstrings + save/restore)
  - `src/pflow/runtime/workflow_trace.py` — lines 225, 313 (read site + filter list — CRITICAL: the filter list MUST be updated or the renamed key surfaces in trace output)
  - `src/pflow/runtime/workflow_executor.py` — line 122 (`_PROPAGATED_KEYS`), line 337 (read)
  - `src/pflow/execution/runner.py` — lines 269, 490 (TWO read sites; v1.0 missed line 269)
  - `src/pflow/nodes/llm/llm.py::prep` (the new read site for trace_hook)
  - `src/pflow/execution/formatters/success_formatter.py:64`
  - `src/pflow/execution/formatters/error_formatter.py:84`
  - `src/pflow/cli/error_output.py:134`
  - `src/pflow/runtime/CLAUDE.md` — lines 113, 130, 167 (docstring updates)
  - `src/pflow/runtime/engine/CLAUDE.md` — lines 25, 30, 253 (docstring updates)
- **Test sites (~10):** `tests/test_runtime/test_workflow_trace.py:166,174`, `tests/test_runtime/test_trace_integration.py:33,330,513,558,646,656`, `tests/test_runtime/test_workflow_executor/test_metrics_propagation.py` (~13 hits including a `test_trace_collector_reference_identity` test name), `tests/test_runtime/test_workflow_executor/test_prep_error_action.py:467`, `tests/test_integration/test_metrics_integration.py:583`.

Verification command after Step 7: `grep -rn '"_trace_collector"\|'\''_trace_collector'\''' src/pflow/ tests/` returns zero hits.

### R-Crit-5. Empty-response warnings via `__warnings__` are misclassified

**Verified at `src/pflow/execution/runner.py:540-580`:** entries in `__warnings__` without a matching `__failures__` entry fall into the `api_warning` branch (lines 567-580), tagged `context={"type": "api_warning"}` with canned suggestions like "Inspect upstream inputs that may be misshapen for the API." This is the wrong remediation for an LLM empty-response warning. Plan v1.0's D7 / Step 3 doesn't address this.

**Revision:** Extend `__warnings__` to support BOTH the existing `str` shape (current contract) AND a new `dict` shape with a `kind` discriminator:
- Existing callers (batch_executor.py:812-814, mark_node_failed) keep writing strings — their entries route through the existing `api_warning`/`on_error_recovery` paths unchanged.
- LLMNode writes a dict: `{"text": warning_text, "kind": "llm_empty_response", "context": {"finish_reason": ..., "output_tokens": ..., "model": ...}}`.
- Update `runner.py::_extract_runtime_warnings` to detect dict values (via `isinstance(warning, dict) and "kind" in warning`) and dispatch to a new `_build_diagnostic_for_kind(kind, text, context)` helper that builds Diagnostic with the right category/suggestions/see_also per kind.
- For `kind == "llm_empty_response"`: produces `Diagnostic(severity=WARNING, source="runtime", message=text, title=CATEGORY_TITLES.get("llm_warning", "LLM Warning"), context={**context, "category": "llm_warning", "kind": "llm_empty_response"}, see_also=["llm"])`.
- Add `"llm_warning": "LLM Warning"` to CATEGORY_TITLES.

This is backward-compatible (the existing dict-vs-str check is one isinstance), surfaces structured info to JSON consumers, and avoids inventing a new shared-store key.

### R-Crit-6. `parse_structured_response` ripple

**Verified at `src/pflow/core/llm_utils.py:43,48,55,92`:** raises `LLMCallError("...")` with no model arg. After Step 1 changes `LLMCallError.__init__` to take `model: str | None = None`, all four call sites would default to `model=None`, making `Diagnostic.context["model"]` null on JSON-parse failures.

**Revision:** Step 1 also updates `core/llm_utils.py::parse_structured_response`:
- Function signature gets a `model: str | None = None` parameter.
- All `raise LLMCallError(...)` calls inside become `raise LLMCallError(..., model=model)`.
- Callers that have model context pass it through; LLMNode's call site (`nodes/llm/llm.py:218`) already has access to the resolved model.

### R-Crit-7. `FuturesTimeoutError` is NOT translated to `LLMTransientError`

**Verified at `src/pflow/nodes/llm/llm.py:355-370`:** the inner ThreadPoolExecutor's per-call timeout produces a `concurrent.futures.TimeoutError` (the class, not the LiteLLM exception), and the existing comment explicitly says "we do NOT retry — the orphaned worker thread is still holding the LiteLLM call open." This semantics differs from `LLMTransientError` (which says "retry me").

**Revision:** Step 3 explicit clause:
- `FuturesTimeoutError` (alias for `concurrent.futures.TimeoutError`) handling in `_call_llm` is UNCHANGED. It still builds an error dict with `error_class="TimeoutError"` and returns `"error"` (no retry — orphan-thread protection).
- The error dict gains `_diagnostic_context = {"error_class": "TimeoutError", "model": resolved_model, "category": "llm_failure", "kind": "pool_timeout"}` so the runtime path produces a structured Diagnostic.
- Plan v1.0's mention of substring detection on `"timed out"` in `exec_fallback` stays — that path catches retry-loop exhaustion of `LLMTransientError` (LiteLLM Timeout) where retries did happen.

Two distinct timeout sources, two distinct diagnostic kinds, no conflation.

### R-High-1. Multi-warnings overwriting

**Verified:** `__warnings__[node_id]` is a single string slot (or, post-R-Crit-5, single dict slot). If `AdapterResponse.warnings` has multiple entries, the loop `for w in adapter_response.warnings: shared["__warnings__"][node_id] = w` overwrites each iteration.

**Revision:** Step 3 — when `len(adapter_response.warnings) > 1`, join with `\n\n` separators OR change the contract to `list[str]`. Decision: in v1, the adapter emits at most one warning per call (reasoning trap is single, content_filter is single, etc.), so the simple `[0]` write works. Add an inline assertion + comment noting the one-warning-per-call invariant. If a future case needs multiple, change the contract then.

### R-High-2. JSON-parse error class — typed exception decision

**Plan v1.0 said "use string label `LLMResponseParseError` or add a typed exception."** Decide now:

**Decision:** Add `LLMResponseParseError(LLMCallError)` typed subclass in `core/exceptions.py`. Override `to_diagnostics()` with structured context (`category="llm_failure"`, `kind="response_parse"`, `model`, `raw_response_excerpt`). `parse_structured_response` raises this instead of bare `LLMCallError`. R-Crit-3's decision (`post()` catches `LLMCallError`) covers this naturally — the typed subclass goes through the same path with richer metadata.

### R-High-3. Retry mid-attempt classification semantics

**Plan v1.0 was silent on:** what happens if attempts 1+2 raise `LLMTransientError` and attempt 3 raises a deterministic `LLMCallError`?

**Documented behavior:**
- `Node._exec` (`src/pflow/core/node.py:69-91`) catches `Exception` for retry, no type discrimination. So `LLMTransientError` → retry; deterministic `LLMCallError` from `_call_llm` is caught BY `_call_llm` and converted to error dict (no exception escapes the inner call), so the loop sees a normal return and exits cleanly with `status="error"`.
- Net: transient failures retry up to `max_retries=3`; deterministic failures end the loop on first occurrence regardless of attempt number. This is the desired behavior. Plan adds a one-line note to Step 3.

### R-High-4. Alternative design rejection rationale

**Plan v1.0 omitted:** rationale for choosing `_diagnostic_context: dict` over storing the exception object directly in `__failures__["exception"]`.

**Documented rejection:**
- **Alternative A — store exception object in `__failures__[id]["exception"]`, call `e.to_diagnostics()` from `build_error_list`.** Rejected because: (1) the exception object adds reference complexity (lifetime spans node execution → Runner serialization → JSON output, increasing the chance of holding stale state); (2) Diagnostic.context is already serialization-clean (json-friendly types only); (3) the dict-passing pattern keeps `_enrich_error_from_node_output` symmetric with how shell/HTTP/MCP enrich today (those don't have an exception object — they read structured fields from node_output). Architectural symmetry > saving one method call.
- **Alternative B — store the diagnostic itself in `__failures__[id]["diagnostic"]`.** Rejected because: it crosses the typed-vs-dict serialization boundary in storage. Storing dicts everywhere is simpler and grep-friendlier.

The chosen design (`_diagnostic_context: dict`) is the simplest end-state with maximal symmetry.

### R-High-5. `see_also` slug correction

**Plan v1.0 vague on `see_also`. Verified slugs:** `branching`, `batch`, `sub-workflows`, `code`, `file`, `http`, `llm`, `mcp`, `shell` (per `src/pflow/guide/`). `api-keys` is NOT a valid slug (no guide topic exists; would fail `Diagnostic.__post_init__` slug-safety check at `core/diagnostic.py:67`).

**Revision:** All `LLMCallError.to_diagnostics()` overrides use `see_also=["llm"]`. Plan should not propose `api-keys`.

### R-High-6. CHANGELOG must enumerate all JSON-shape additions

**Plan v1.0:** Step 8 mentions CHANGELOG entry for cost mirroring only.

**Revision:** Step 8/10 CHANGELOG bullet-list ALL user-visible JSON-shape changes:
- New `category="llm_failure"` for LLM error contexts.
- New `error_class`, `model`, `reason`/`kind` fields in `errors[i].context` for LLM failures.
- New `warnings[i]` entries for empty-response cases (workflow status shifts to DEGRADED).
- New top-level `partial_cost_usd`, `pricing_available`, `unavailable_models` fields when pricing data is incomplete.
- `_trace_collector` shared-store key renamed to `__trace_collector__` (internal; downstream impact: any external consumer reading shared-store JSON from a debugger would need to update).

### R-High-7. Documentation rationale for new `llm_failure` category

**Plan v1.0:** D9 added `FAILURE_CATEGORY_LLM` without justifying why LLM gets its own category vs. shell/http/mcp (which all map to the generic `execution_failure`).

**Documented rationale (added to D9):**
> LLM failures are categorically distinct from other node failures because: (a) agents most commonly cost-gate or retry-gate on LLM specifically (cost-cap workflows, key-rotation policies); (b) LLM failures have unusually structured remediations (model name + env var + provider URL) that benefit from a typed category for filterability; (c) the agent UX for "API key for X is missing" is fundamentally different from "shell command exited with code 1" — distinct categories let agent-side rendering specialize. Promoting `shell_failure`, `http_failure`, `mcp_failure` to similarly-specific categories is a possible follow-up if the agent UX justifies it; not in v1 scope.

### R-Sug-1. NamespacedSharedStore routing comment

**Verified at `src/pflow/runtime/engine/namespaced_store.py`:** `setdefault("__warnings__", {})` returns the root dict because `__*__` keys bypass namespacing; the subsequent `[self.node_id] = warning_text` writes to that root dict. So the v1.0 D7 implementation is correct, but non-obvious.

**Revision:** Inline comment at the LLMNode call site:
```python
# setdefault routes __*__ keys to root via NamespacedSharedStore proxy contract;
# subscript write hits the returned root dict. (See namespaced_store.py:115-130.)
shared.setdefault("__warnings__", {})[self.node_id] = warning_dict
```

### R-Sug-2. Smart_filter umbrella narrowness

**Plan v1.0 R5:** acknowledged that catching `Exception` would silently swallow `KeyboardInterrupt`/`SystemExit`/programming errors.

**Revision:** Add an inline comment to smart_filter's narrowed `except LLMCallError` clause: `# Umbrella catch must remain LLMCallError-narrow; broadening to Exception would swallow KeyboardInterrupt/SystemExit/programming bugs.` Catches future drift.

### R-Sug-3. `to_diagnostics` non-empty list invariant

**Verified at `src/pflow/core/exceptions.py:38`:** `PflowError.to_diagnostics()` returns `list[Diagnostic]` always non-empty. All existing overrides return single-element lists.

**Revision:** Each new LLMCallError override comment: `# Returns single-element list (PflowError convention; LLMNode.post indexes [0]).` Catches a footgun where a future override might return `[]` and crash `LLMNode._call_llm`.

### R-Sug-4. CLAUDE.md updates for the typed-exception hierarchy

**Verified:** `src/pflow/core/CLAUDE.md:65-71` documents the exception hierarchy. With `LLMTransientError` and `LLMResponseParseError` additions, this section needs updating.

**Revision:** Step 10 doc-sweep adds: update `core/CLAUDE.md:65-71` (exception hierarchy table) and `core/CLAUDE.md:186` (the stale "BadRequestError → error-marked response" claim — that contract is gone).

### R-Sug-5. MockLLMClient warnings emission

**Plan v1.0:** new `AdapterResponse.warnings` field. `MockLLMClient` (in `tests/shared/llm_mock.py`) constructs `AdapterResponse` instances; need a knob to emit warnings for the new test (`test_post_writes_warnings_to_shared`).

**Revision:** Step 3 (test infrastructure subsection) adds: extend `MockLLMClient.set_response(...)` with optional `warnings: list[str] = None` kwarg. Default empty.

### Summary of v1.1 revisions

The architectural plan is correct — typed-exception completion via `to_diagnostics()` overrides + structured `_diagnostic_context` lift + LLMTransientError + warnings infrastructure. The revisions above tighten the **mechanical contract** (the empty-response warning routing, the shared category constant, the rename radius, the parse_structured_response ripple, the FuturesTimeoutError semantics) so the implementation can proceed without surprises.

After implementation, the verification chain stays the same as v1.0:
- `make test` + `make check` green at every commit
- `tests/test_execution/test_plan_drift.py` 32/32 throughout
- 3 real-API smoke tests
- Architectural seal grep returns 1 match

Adjusted commit count: still 10 commits (R-Crit-1, R-Crit-2, R-Crit-3, R-Crit-6 fold into Steps 1-4; R-Crit-4 + R-Crit-5 expand Step 7 + Step 3; R-Sug-* are inline polish).

End of v1.1 revisions.
