# Task 158 — Phase 0 + Phase A Implementation Plan

## Context

Task 158 adds prompt caching to pflow workflows. The full design is in `.taskmaster/tasks/task_158/task-158.md`; design rationale and pivots are in `.taskmaster/tasks/task_158/implementation/progress-log.md`. Implementation work is split into seven phases (0, A, B, C, D, E, F, G). This plan covers **only Phase 0 and Phase A** because we cannot write a credible plan for B–G without first verifying LiteLLM behavior end-to-end. Once Phase A lands, a separate plan for Phases B–G will be written informed by concrete LiteLLM behavior.

**Phase 0** is a verification spike (a few hours, ~$0.10 of API calls). It de-risks the LiteLLM bet before we touch production code.

**Phase A** is the LiteLLM library migration: replace Simon Willison's `llm` library with a pflow-owned adapter backed by LiteLLM. **Phase A introduces no caching syntax and no `cache_control` markers.** It preserves all current LLM-node external behavior. Outcome: every existing workflow continues to work identically; the only observable difference is what's on disk and what shows up in `pyproject.toml`.

This plan is the contract for the work; the spec is the contract for the feature.

---

## Phase 0 — LiteLLM verification spike

Cheap to run, decisive in outcome. Run before any production-code changes.

### Spike scope

Write a small set of throwaway `spike_*.py` scripts under `scratchpads/task-158-spike/` (gitignored or not committed). Five concerns:

1. **Cache mechanics across providers.** Fire `litellm.completion(...)` against Anthropic, Gemini, and OpenAI with `cache_control: {type: ephemeral}` on the system message. Confirm:
   - Message structure that LiteLLM accepts: `{"role": "system", "content": [{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]}`. Verify on each provider.
   - `response.usage.cache_creation_input_tokens` populates on the first call and `cache_read_input_tokens` on the second identical call.
   - Anthropic-specific: cache hits at ≥1024 tokens (sonnet/opus) or ≥2048 (haiku).
   - Gemini: confirm only the last `cache_control` marker is honored (single-cached-block architectural limit), and that this fails silently (cache simply doesn't fire on earlier markers) rather than corrupting the response.
   - OpenAI: confirm `cache_control` is treated as a no-op (auto-caching at ≥1024); optionally test `prompt_cache_key` for parallel-batch routing consistency.

2. **Composition matrix.** Critical for our use case. Test at minimum these combinations on Anthropic Opus (the most reasoning-heavy provider):
   - cache_control + extended thinking (`thinking_budget` and `thinking_effort`)
   - cache_control + structured output (`response_format` with a JSON schema)
   - cache_control + extended thinking + structured output (all three)
   - Confirm the response shape on each (does `response.choices[0].message.content` come back as str, list of blocks, or wrapper object?).

3. **Pricing authority decision.** Compare `litellm.completion_cost(response)` against `core/llm_pricing.py::calculate_llm_cost()` across all 41 entries in `MODEL_PRICING`. Acceptance bands:
   - Non-cached calls: ≤2% disagreement.
   - Cached calls (write + read tokens): ≤5% disagreement.
   - Special: confirm Gemini double-counting bug fix (LiteLLM PR #15226, 2025-10-07) is present in the pinned version. Run two identical Gemini calls with `cache_control`; compare LiteLLM's reported cost to a hand calculation. If they agree, fix is present.
   - **Outcome decides downstream work**:
     - **A — LiteLLM accurate + comprehensive across all 41 models:** delete `llm_pricing.py` in Phase A, use `completion_cost()` directly. (Best outcome — eliminates the maintenance-lag burden where new model releases show $0 cost.)
     - **B — LiteLLM mostly accurate, edge bugs on a few models:** use LiteLLM `response_cost` as primary, keep `llm_pricing.py` as thin fallback for known-bad-edge models or unknown-model cases. (Most likely outcome.)
     - **C — Material bugs we can't trust on multiple providers:** import LiteLLM's `model_prices_and_context_window.json` as the data source, keep pflow's calculation code on top. (Conservative fallback.)

4. **Operational checks.**
   - **Logger silencing.** LiteLLM is chatty by default. Find the right knob (`litellm.suppress_debug_info = True`, `litellm.set_verbose = False`, `litellm._turn_on_debug = False`, or env var). Confirm test output is clean.
   - **Thread safety.** Fire 5 concurrent `litellm.completion(...)` calls with a `ThreadPoolExecutor` (mirrors how pflow's LLMNode runs today). Confirm no shared-state corruption, no `httpx`/`anthropic` client races.
   - **Env-var key resolution.** Set only `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`GEMINI_API_KEY`. Confirm `litellm.completion(model="anthropic/claude-...")` picks them up cleanly without any config files.
   - **Hidden config files.** Run a clean-environment test (`HOME=/tmp/empty`) to confirm LiteLLM doesn't try to read `~/.litellm/...` or other surprises.
   - **Transitive dep audit.** `uv pip install litellm` in a scratch venv, then `uv pip list --tree`. Capture: total install size, any `boto3` / `google-cloud-*` / `azure-*` deps, security-surface concerns. Decide whether `litellm[proxy]` extras are needed (probably not).

5. **Exception detection.**
   - LiteLLM raises `litellm.exceptions.AuthenticationError`, `litellm.exceptions.BadRequestError`, etc. Identify the equivalents of the current `UnknownModelError` and `NeedsKeyException` detection in `nodes/llm/llm.py:435-452`.
   - Confirm exception messages are stable enough to detect via `isinstance` (preferred over class-name string matching).

### Phase 0 deliverable

A short markdown report appended to `progress-log.md` with:
- Pass/fail per spike concern
- Pricing outcome (A/B/C) with evidence
- LiteLLM version pinned and rationale
- Confirmed message structure for cache_control across providers
- Composition matrix results
- Logger-silencing approach chosen
- Any spec adjustments required (especially around pricing)

If outcome A fires, update spec to drop `llm_pricing.py` references; if B, note the fallback contract. Update before proceeding to Phase A.

---

## Phase A — LiteLLM migration (no caching yet)

The largest phase. Goal: every existing workflow runs identically on LiteLLM. Zero new features. Mass test update is part of the phase, not deferred.

### A.1 — Install LiteLLM and add adapter scaffolding

**Files touched:**
- `pyproject.toml` — add `litellm>=<pinned-version>` to `[project] dependencies`. Do NOT remove `llm`/`llm-anthropic`/`llm-gemini` yet (we want a clean swap, not a transitional dependency state).
- `uv.lock` — regenerate via `uv sync`.

**Verification:** `uv pip list | grep litellm` shows it installed; existing tests still pass (no behavioral change yet).

### A.2 — `src/pflow/core/llm_reasoning_map.py` (new file)

Replaces the live introspection at `nodes/llm/llm.py:35-114` (`_map_reasoning_options`, which reads `model.Options.model_fields` from the llm-library's plugin model classes — a contract LiteLLM does not provide).

**Module shape:**
- A function `map_reasoning_options(model: str, reasoning_effort: str | None, reasoning_max_tokens: int | None) -> dict[str, Any]` that returns the kwargs LiteLLM should receive.
- Provider detection by model-name string sniffing (matches the current `registry/smart_filter.py:175-180` approach for Gemini variants).
- Hardcoded provider/model → reasoning kwarg precedence map. **Critical to preserve**: Anthropic Opus 4.5 has BOTH `thinking_effort` and `thinking_budget` available — `thinking_effort` MUST be checked first (encoded in current `nodes/llm/llm.py:53-56`). Getting precedence wrong silently degrades Opus 4.5 reasoning.
- Same `EFFORT_RATIOS` and `DEFAULT_MAX_TOKENS_BASE` constants from current `nodes/llm/llm.py:22-32` move here.

**Tests:** `tests/test_core/test_llm_reasoning_map.py` — unit tests per provider/model with known reasoning_effort inputs. No network calls.

### A.3 — `src/pflow/core/llm_client.py` (new file — the adapter)

The single seam pflow uses for all LLM calls. Wraps `litellm.completion`. All the LiteLLM API-shape complexity stops here.

**Public API (concrete proposal — adjust based on Phase 0 findings):**

```python
def complete(
    *,
    model: str,
    prompt: str,
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    attachments: list[Attachment] | None = None,
    schema: dict | None = None,
    reasoning_kwargs: dict | None = None,
    model_options: dict | None = None,
    timeout: float | None = None,
    trace_hook: TraceHook | None = None,
) -> AdapterResponse:
    ...
```

Where:
- `AdapterResponse` is a thin dataclass exposing `.text` (str), `.usage` (dict), `.model` (str), `.has_schema` (bool). The `usage` dict has stable keys: `model`, `input_tokens`, `output_tokens`, `total_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` (matching what `core/llm_pricing.py:enrich_llm_usage_with_cost` already expects). LiteLLM's `usage.prompt_tokens`/`completion_tokens` and `prompt_tokens_details.cached_tokens` are normalized here — LLMNode.post() should not need changes.
- `Attachment` is `{type: "image_url" | "image_path", value: str}`. Internally the adapter encodes images to LiteLLM's content-block format (`{"type": "image_url", "image_url": {"url": "data:..."} }` for paths; `{"type": "image_url", "image_url": {"url": "https://..."}}` for URLs).
- `schema` is a JSON Schema dict (current pflow contract). Adapter renders it as LiteLLM's `response_format={"type": "json_schema", "json_schema": ...}` (Phase 0 confirms the exact key shape for OpenAI vs Anthropic).
- `trace_hook` is an optional callable that gets invoked with the rendered prompt text before the API call and the response after. Replaces the monkey-patch (see A.6).

**Internal responsibilities:**
- Build LiteLLM `messages` list from `system` + `prompt` + attachments.
- Call `litellm.completion(...)` with built kwargs and provider-specific reasoning args from `reasoning_kwargs`.
- On exception, classify (auth / bad model / timeout / generic) and either raise a typed pflow error OR return an error-marked response (TBD — match current LLMNode behavior which returns error dicts in some cases and raises in others).
- Normalize the response to `AdapterResponse`. Cached-token fields populate from `response.usage.cache_creation_input_tokens` / `cache_read_input_tokens` if present, else from `prompt_tokens_details.cached_tokens` (provider-dependent — Phase 0 confirms).
- Suppress LiteLLM verbose logging at module import (knob TBD from Phase 0).

**Tests:** `tests/test_core/test_llm_client.py` — adapter unit tests using `unittest.mock.patch("litellm.completion")` to inject canned responses. Cover: text-only, structured (with schema), with images, with reasoning_kwargs, error paths (auth, bad model, timeout), trace_hook invocation.

### A.4 — Test infrastructure rewrite (BEFORE rewiring callers)

Doing this before the LLMNode rewrite means we can validate adapter behavior against existing tests as we go.

**`tests/shared/llm_mock.py`:**
- Add a new `MockLLMClient` class that mirrors `MockLLMModel`'s public surface (`call_history`, `set_response`, `get_response`, `reset`, `_default_responses` for known schemas) but emits `AdapterResponse` instances directly from `MockLLMClient.complete(...)`.
- **Keep `MockLLMModel` and `MockGetModel` in place during A.4–A.7** so we can roll callers over one at a time without breaking existing tests.
- Preserve the 500-char `call_history[i]["prompt"]` truncation by default. Add a parallel `call_history_full` field (or untruncated mode flag) for cache-structure tests in later phases — mention in plan but the new field can wait until Phase B/C actually needs it.
- New factory `create_mock_llm_client() -> MockLLMClient`.

**`tests/conftest.py`:**
- Add a NEW autouse fixture `mock_llm_client(monkeypatch, request)` that patches `pflow.core.llm_client.complete` with `MockLLMClient`'s `complete` method. Same `/llm/` path skip pattern. Same teardown reset.
- **Keep the existing `mock_llm_calls` fixture in place** during A.4–A.7. Both autouse fixtures coexist; tests that haven't been migrated still get `llm.get_model` mocked.

**Tests:** the autouse fixture is itself the test bed. Run `pytest tests/test_core/test_llm_client.py` to confirm the mock wiring works.

### A.5 — Rewire LLMNode to use the adapter

**Files touched:**
- `src/pflow/nodes/llm/llm.py` — substantive rewrite of:
  - `prep()` (lines 205–269): build an `Attachment` list (the new dataclass) instead of `llm.Attachment(...)`; preserve all parameter parsing, validation, defaults.
  - `_call_llm()` (lines 271–321): replace `model = llm.get_model(...)`/`response = model.prompt(...)` with `adapter_response = llm_client.complete(...)`. Returned dict shape unchanged so `post()` doesn't need to change.
  - `_map_reasoning_options()` (lines 35–114): delete; replace with a call to `llm_reasoning_map.map_reasoning_options(...)`. The `EFFORT_RATIOS` and `DEFAULT_MAX_TOKENS_BASE` constants move with it.
  - `exec_fallback()` (lines 422–465): adjust exception detection. Replace class-name string matching for `UnknownModelError`/`NeedsKeyException` with detection of the LiteLLM exceptions identified in Phase 0. **Keep the user-facing error message strings as close as possible** to the current text — users have muscle memory:
    - "Unknown model: {model}. Tip: Your API key supports '{detected}'. Run 'pflow settings llm show' to see configured models." (replaces the `llm models` reference)
    - "API key required for model: {model}. Set the appropriate environment variable (e.g., ANTHROPIC_API_KEY)." (replaces `llm keys set`)
  - The Pydantic `ValidationError` catch (lines 298–311) labeled "PATTERN EXCEPTION" — this was tied to the `llm` library's Options Pydantic validation. Under LiteLLM the Pydantic validation surface doesn't apply the same way. Likely this catch is removed; if LiteLLM has its own deterministic-error pattern (e.g., `litellm.exceptions.BadRequestError` for bad params), redirect there.
  - `post()` (lines 357–420): the `llm_usage` extraction logic at lines 370–405 has dual paths (dict or object with `.input`/`.output`/`.details`). Since the adapter normalizes to a dict, the object path can be removed. Simplify to a single dict-read code path.

**Tests:** run `tests/test_nodes/test_llm/test_llm.py` — many tests build inline `Mock()` responses with `.text.return_value = "..."` (~20 sites). These need reshaping to either (a) use `MockLLMClient.set_response(...)` with the new `AdapterResponse` shape, or (b) build inline `AdapterResponse` instances. Pick (a) where possible — most tests only care about the response text and shared-store output, not the mock contract. For tests that explicitly assert `mock_response.text.assert_called_once()` or similar, switch to asserting on `MockLLMClient.call_history`.

### A.6 — Tracing redesign

This is the riskiest part of Phase A. The current monkey-patch at `runtime/workflow_trace.py:520-599` is sophisticated:
- Two-layer interception (replaces `llm.get_model`, then per-instance `model.prompt`)
- Reference-counted via `_llm_interception_count` (handles nested workflows)
- Per-thread state via `_thread_local.current_node` and `_active_collectors[thread_id]`
- Lock-protected via `_llm_lock`
- Lazy install/teardown

**Replacement design:**
- The adapter's `trace_hook` parameter (added in A.3) is the new seam.
- A new function `WorkflowTraceCollector.get_trace_hook(node_id) -> TraceHook` returns a callable that, when invoked by the adapter, captures the prompt text into `collector.llm_prompts[node_id]` (preserving current behavior).
- `LLMNode._call_llm` passes `trace_hook=collector.get_trace_hook(self.cur_node_id)` to the adapter when a collector is active. The "is a collector active" check uses the same `_active_collectors[thread_id]` registry the monkey-patch uses today — but instead of consulting it from inside the patched `prompt`, we consult it from inside `LLMNode._call_llm`.
- The other 3 production call sites (`registry/discovery.py`, `registry/smart_filter.py`, `core/workflow/discovery.py`) historically rely on the monkey-patch to capture their prompts too. After A.6, they pass `trace_hook=None` (they don't run inside a workflow trace context anyway, so prompt capture wasn't useful for them). Confirm this is a real non-loss before merging — quick grep for tests that assert on smart_filter or discovery prompts in trace output.

**Files touched:**
- `src/pflow/runtime/workflow_trace.py` — DELETE `setup_llm_interception` and `cleanup_llm_interception` (lines 520–599) including the lazy `import llm` calls. Class-level state (`_llm_lock`, `_llm_interception_count`, `_original_get_model`) DELETE. Keep `_active_collectors` and `_thread_local.current_node` — these are reused by the new mechanism. Add `get_trace_hook` method.
- `src/pflow/nodes/llm/llm.py` — `_call_llm` now passes `trace_hook` to the adapter.

**Sacred test:** `tests/test_execution/test_plan_drift.py` — 32 tests asserting planner ↔ runtime parity. After A.6, run this in isolation. If it fails, STOP — the tracing redesign has affected execution semantics, which it must not.

**Manual verification:** run a workflow with the new tracing, inspect the resulting trace JSON, confirm `event["llm_prompt"]`, `event["llm_response"]`, and `event["llm_call"]` all populate as before.

### A.7 — Update other call sites (3 files)

Mechanical replacement, same pattern as A.5 but smaller scope.

**Files touched:**
- `src/pflow/registry/discovery.py:88` — replace `llm.get_model(...)` + `.prompt(..., schema=...)` with `llm_client.complete(...schema=ComponentSelectionSchema's JSON schema...)`. Note the schema parameter — current code passes a Pydantic class directly; under the adapter it must be a JSON Schema dict (use `Schema.model_json_schema()`).
- `src/pflow/registry/smart_filter.py:169` — same pattern. Note the model-name-based reasoning heuristic at lines 173–180; it stays in this file (caller-side) — the adapter only handles what's passed to it.
- `src/pflow/core/workflow/discovery.py:85` — same pattern.

**Update `src/pflow/core/llm_utils.py::parse_structured_response`** — current implementation reads `response.text()` (callable) at line 40. Adapter returns `AdapterResponse` with `.text` (attribute, not callable). Adjust accordingly.

**Tests:** existing tests for these modules (`tests/test_registry/test_smart_filter.py`, `tests/test_registry/test_component_discovery.py`, `tests/test_core/test_workflow_discovery.py`) use `mock_llm_calls` fixture. Migrate them to use the new `mock_llm_client` fixture instead. Mostly mechanical — replace `mock_llm_calls.set_response(...)` calls with the new fixture's equivalent.

### A.8 — Mass test suite migration

Once A.5 + A.7 are done, the `llm.get_model` autouse fixture can be removed.

**Files touched** (9 files using `llm.get_model` per the agent's grep):
- `tests/conftest.py:11-35` — DELETE the `mock_llm_calls` autouse fixture entirely (the new `mock_llm_client` fixture supersedes it).
- `tests/test_nodes/test_llm/test_llm.py` — already addressed in A.5.
- `tests/test_nodes/test_llm/test_llm_reasoning.py` — likely uses inline mocks. Migrate to adapter shape.
- `tests/test_nodes/test_llm/test_llm_integration.py` — real-API integration tests. Update model-call paths to use adapter.
- `tests/test_nodes/test_llm/test_llm_images.py` — image-attachment tests. Confirm Attachment shape works through the adapter.
- `tests/test_registry/test_smart_filter.py` — already addressed in A.7's tests.
- `tests/test_cli/test_dry_run.py` — uses `llm.get_model` in some test setup. Migrate.
- `tests/test_integration/test_metrics_integration.py` — uses `MockLLMModel`. Switch to `MockLLMClient`.
- `tests/test_execution/formatters/test_node_output_formatter.py`, `tests/test_cli/test_nested_workflow_cli.py`, `tests/test_core/test_workflow_discovery.py` — use `mock_llm_calls`. Migrate to `mock_llm_client`.

**Test infrastructure cleanup** (`tests/shared/llm_mock.py`) — once all callers migrated, DELETE `MockLLMModel` and `MockGetModel` and `create_mock_get_model`. The new `MockLLMClient` is the only mock left.

**Run after each migration step:** `make test` — green or stop.

### A.9 — `llm_config.py` and `settings.py` cleanup

**Files touched:**
- `src/pflow/core/llm_config.py`:
  - DELETE `_has_llm_key()` (lines 53–99) — no more `llm` CLI subprocess.
  - DELETE `get_llm_cli_default_model()` (lines 348–387) — no more subprocess for default model.
  - Update `_has_provider_key()` (lines 102–149) — remove the third source (`_has_llm_key()` fallback). Now only env vars + pflow settings via `SettingsManager`.
  - Update `_detect_default_model()` (lines 152–184) — remove the test-env subprocess guard at lines 164–166 (no subprocess to guard).
  - Update `get_llm_setup_help()` (lines 220–237) — replace `llm keys set anthropic`/`llm keys set gemini`/`llm keys set openai` with environment-variable instructions:
    ```
    Set provider API keys via environment variables:
      export ANTHROPIC_API_KEY=...
      export OPENAI_API_KEY=...
      export GEMINI_API_KEY=...
    Or configure them in pflow settings:
      pflow settings llm set-key <provider> <key>
    ```
    (The latter requires confirming `pflow settings llm set-key` exists or noting it as a v1.x follow-up if not.)
  - Update `get_model_not_configured_help()` (lines 433–465) — replace `llm models default`/`llm models list` references with pflow-equivalents.
  - Constants to delete: `LLM_COMMAND` (line 23), `_LLM_KEYS_SUBCOMMAND` (line 37). Constants to keep: `ALLOWED_PROVIDERS` (line 26), `PROVIDER_ENV_VARS` (lines 30–34).
  - `inject_settings_env_vars()` (lines 250–286) — UNCHANGED. LiteLLM reads from `os.environ` natively, so this still works.

- **NOTE — spec correction**: the spec says "optionally read `~/.config/io.datasette.llm/keys.json` for users migrating from `llm`". pflow does NOT currently read this file (verified by codebase grep). Adding read support is NEW functionality, not a migration of existing behavior. **Defer this to a v1.x follow-up.** Phase A's migration story for users who have keys in Simon's keys.json: "set the equivalent env var or use `pflow settings`". Document in the migration note.

- `src/pflow/cli/commands/settings.py`:
  - Update `pflow settings llm` group docstring (lines 39–41) — remove "via Simon Willison's llm tool" reference; point to env vars + `pflow settings`.
  - Update help text strings at lines 411, 451, 555 — remove all "llm CLI default" / "llm cli" phrasing.
  - **Avoid the spec's circularity** ("point users at env vars and `pflow settings llm` itself"). Suggested phrasing: point at env vars and `pflow settings env` for inline credential storage; do not self-reference.

- `src/pflow/cli/commands/run.py:718` — `inject_settings_env_vars` call unchanged; verify no fallout.

- `src/pflow/mcp_server/main.py:40` — same.

**Tests:** existing tests for `llm_config` (find via grep) — update to no longer expect the subprocess path. Add a test confirming env-only key resolution works.

### A.10 — Pricing decision + cleanup (outcome-dependent)

Outcome from Phase 0 spike determines work here:

- **Outcome A (LiteLLM accurate + comprehensive):**
  - DELETE `src/pflow/core/llm_pricing.py` entirely.
  - Replace `enrich_llm_usage_with_cost(llm_usage)` callers with a thin wrapper around `litellm.completion_cost(response)` — plumbed through the adapter so `AdapterResponse` carries `cost_usd` directly.
  - Update CLAUDE.md references to the deleted module.
  - Update `core/__init__.py` exports.

- **Outcome B (LiteLLM mostly accurate, edge bugs):**
  - Adapter calls `litellm.completion_cost(response)` first; on disagreement-known models or when LiteLLM returns `None`, fall back to `core/llm_pricing.py::calculate_llm_cost()`.
  - Trim `MODEL_PRICING` to only the known-bad-edge models (likely a subset of Gemini variants + any custom-endpoint models).

- **Outcome C (material bugs we can't trust):**
  - Import `litellm/model_prices_and_context_window.json` as the data source (could vendor it or read at install time).
  - Replace `MODEL_PRICING` table contents with this data; keep `calculate_llm_cost()` calculation code on top.

In all outcomes: fix the CLAUDE.md drift (`core/CLAUDE.md:198` claims "46+ models"; actual count is 41). Update with the correct number or remove the count.

### A.11 — Remove old dependencies

**Files touched:**
- `pyproject.toml`:
  - DELETE `llm>=0.29` (line 28).
  - DELETE `llm-anthropic==0.25` (line 29).
  - DELETE `llm-gemini>=0.30` (line 37).
  - Update `DEP002 = ["llm-anthropic", "llm-gemini", "PyYAML"]` (line 184) — remove `llm-anthropic` and `llm-gemini`. `PyYAML` stays.
  - Confirm `pyproject.toml:39-41` (commented-out optional-dependencies stub) is still relevant or delete.
- `uv.lock` — regenerate via `uv sync`.

**Verification:** `uv pip list | grep -E '^(llm|llm-)'` returns nothing. `make check` passes (deptry doesn't flag missing deps). Smoke test against a real workflow.

### A.12 — Documentation and final polish

- `pflow guide` — find any LLM node docs referencing `llm keys` / `llm models` setup; rewrite to env vars.
- CLAUDE.md files — `core/CLAUDE.md`, `nodes/llm/CLAUDE.md` — update LLM library references.
- Mintlify docs — `docs/reference/cli/index.mdx` and any settings/setup pages.
- Migration note in CHANGELOG (or wherever pflow tracks user-facing changes): "v0.X removes the dependency on Simon Willison's `llm` library. API keys must now be set via environment variables (or `pflow settings env`). Existing keys stored via `llm keys set ...` will not be picked up automatically; transfer them to env vars manually. (Direct read of legacy keys.json deferred to v1.x.)"

---

## Critical files (Phase A modifies these)

**Production source:**
- `src/pflow/nodes/llm/llm.py` — main rewrite
- `src/pflow/runtime/workflow_trace.py` — tracing redesign
- `src/pflow/core/llm_config.py` — drop subprocess paths
- `src/pflow/core/llm_utils.py` — adapter response shape
- `src/pflow/cli/commands/settings.py` — copy update
- `src/pflow/registry/discovery.py` — adapter callsite
- `src/pflow/registry/smart_filter.py` — adapter callsite
- `src/pflow/core/workflow/discovery.py` — adapter callsite
- `src/pflow/core/llm_pricing.py` — outcome-dependent (delete or trim)

**New files:**
- `src/pflow/core/llm_client.py` — pflow-owned LiteLLM adapter
- `src/pflow/core/llm_reasoning_map.py` — explicit provider/model reasoning kwarg map

**Test infrastructure:**
- `tests/shared/llm_mock.py` — add MockLLMClient, eventually delete MockLLMModel
- `tests/conftest.py` — add `mock_llm_client` autouse fixture, eventually delete `mock_llm_calls`

**Existing utilities to reuse:**
- `core/llm_pricing.py::enrich_llm_usage_with_cost` — keep semantics (mutates llm_usage to add `cost_usd`); pricing source determined by Phase 0 outcome
- `core/llm_config.py::inject_settings_env_vars` — UNCHANGED, still pushes pflow settings into `os.environ` for LiteLLM to find
- `core/llm_config.py::_has_provider_key` — keep but trim to two sources (env + settings)
- `core/llm_config.py::SettingsManager` integration — UNCHANGED
- `core/llm_utils.py::parse_structured_response` — keep, adjust for adapter shape
- `runtime/engine/instrumentation.py::compute_node_config` — UNCHANGED in Phase A (Phase C will add conditional `prompt_cache` inclusion)
- `runtime/engine/types.py::NodeConfig` — UNCHANGED in Phase A (Phase B/C will add `prompt_cache_items` and `prewarm` fields)

**Dependency manifest:**
- `pyproject.toml` — add litellm, eventually remove llm trio
- `uv.lock` — regenerate

---

## Spec corrections discovered during research

Two findings contradict the current spec; flag them but defer fixes to either Phase 0 outcome or post-Phase A spec touch-up:

1. **`~/.config/io.datasette.llm/keys.json` direct read.** Spec says "optionally read … for users migrating from `llm`". Codebase grep confirms pflow does NOT currently read this file — all key discovery is via the `llm keys get` subprocess. Adding direct read is NEW functionality, not migration. **Plan defers this to v1.x follow-up.** Migration story for Phase A: env vars only.

2. **Cache-write multiplier.** Spec assumes Anthropic-style 1.25× (5-min TTL) and 2× (1-hour TTL) write multipliers. Current `core/llm_pricing.py:168` has a hardcoded `2.0` only — no per-TTL distinction exists. This becomes load-bearing in Phase E (when 1h TTL becomes selectable in `## Cache` blocks), not Phase A. Note in Phase 0 outcome but no Phase A change needed.

Also drift, not spec-vs-code: `core/CLAUDE.md:198` says "46+ models"; actual count is 41. Fix during A.10 documentation pass.

---

## Verification

### After Phase 0
- Spike report appended to progress-log.md with pass/fail per concern
- Pricing outcome (A/B/C) documented with evidence
- LiteLLM version pinned with rationale
- Spec updated if outcomes shift cache pricing or `llm_pricing.py` fate

### After Phase A
- `make test` — full suite green (zero failures)
- `make check` — lint, type check, deptry all green
- `tests/test_execution/test_plan_drift.py` — all 32 tests green (sacred parity invariant intact)
- `pytest tests/test_nodes/test_llm/test_llm_integration.py` with `RUN_LLM_TESTS=1` and Anthropic + Gemini + OpenAI keys — all integration tests pass (real API calls)
- `uv pip list | grep -E '^(llm|llm-)'` — no matches (old deps gone)
- `uv pip list | grep litellm` — present
- `grep -rn 'import llm$\|from llm import' src/pflow/` — no matches
- Manual smoke test: run `lyrics-generator.pflow.md` end-to-end against Anthropic. Expect identical observable behavior to pre-task baseline (response text, llm_usage shape, trace contents).
- Manual smoke test: run a workflow with `--no-cache` flag — confirm memo cache disabled, behavior identical.
- Trace inspection: open the most recent trace JSON; confirm `event["llm_call"]`, `event["llm_prompt"]`, `event["llm_response"]` all populate as before.
- `pflow settings llm show` — confirm output is sensible without referencing Simon's `llm` binary.

---

## Suggested commit sequence (Phase A)

Each step is a separate commit. Tests pass at every step.

1. Add LiteLLM to `pyproject.toml`, `uv sync`. (A.1)
2. Add `llm_reasoning_map.py` + tests. (A.2)
3. Add `llm_client.py` adapter + tests with mocked LiteLLM. (A.3)
4. Add `MockLLMClient` + new autouse fixture (existing fixture coexists). (A.4)
5. Rewire LLMNode to use adapter; reshape `test_llm.py` mocks. (A.5)
6. Tracing redesign; verify `test_plan_drift.py` green. (A.6)
7. Rewire `discovery.py` × 2 + `smart_filter.py` to use adapter. (A.7)
8. Mass-migrate remaining tests to new fixture; delete old fixture and `MockLLMModel`. (A.8)
9. Drop `llm` CLI subprocess from `llm_config.py`; update `settings.py` copy. (A.9)
10. Pricing decision + `llm_pricing.py` work (outcome-dependent). (A.10)
11. Remove `llm`/`llm-anthropic`/`llm-gemini` from `pyproject.toml`. (A.11)
12. Documentation pass + CHANGELOG note. (A.12)

If any step fails verification, stop and resolve before proceeding. Do NOT defer test failures past the step that introduced them.

---

## Risks and mitigations

**Tracing redesign (A.6) is the highest-risk single step.** Mitigation: implement the trace_hook plumbing in A.3 (adapter) and A.5 (LLMNode) first; only delete the monkey-patch in A.6 once we confirm the new path is fully wired. This means a brief overlap window where both mechanisms coexist (the monkey-patch on legacy `llm.get_model` calls plus the new trace_hook on adapter calls) — that overlap is fine and safer than a hard cutover.

**Reasoning-options precedence regression.** Mitigation: the `llm_reasoning_map.py` unit tests must explicitly cover Anthropic Opus 4.5 (thinking_effort precedence) and the OpenAI/Gemini distinctions. Mirror the test cases that cover the current `_map_reasoning_options` behavior.

**Test mock shape divergence.** Mitigation: the adapter's response shape is the ONE invariant. Document it clearly in `llm_client.py`. If a downstream test breaks because it asserts on the wrong attribute (`.text()` vs `.text`), fix the test to use the right shape — do not adjust the adapter to placate the test.

**LiteLLM logger spam.** Mitigation: silence at `llm_client.py` import. If it leaks into test output, add the silencing to `tests/conftest.py` as well.

**Provider detection regression.** Mitigation: model-name string sniffing in `llm_reasoning_map.py` is less robust than the current Pydantic introspection. Mitigated by: (a) explicit unit tests per known-model, (b) graceful fallback (no reasoning kwargs sent if model not in map — same as today's "no Options field matches"), (c) easy to extend (add model name → strategy entry).

**Phase 0 spike outcome shifts the plan.** Mitigation: pricing-decision branch is explicit (A/B/C) and only affects A.10. Other phases are outcome-independent.

**LiteLLM dependency footprint.** Mitigation: dep audit in Phase 0. If `litellm` brings unexpected baggage (boto3, google-cloud-*), evaluate whether `litellm-proxy-extras=False` or similar suppresses them. Worst case, vendor a slimmer subset.

**Backwards compatibility for existing `cache: false` workflows.** Should be unaffected (Phase A doesn't touch cache_enabled semantics). Mitigation: existing tests for `cache: false` continue to pass.

---

## Out of scope for Phase 0 + Phase A

Explicitly NOT in this plan (deferred to Phases B–G or follow-up tasks):

- `## Cache` block parsing
- `prompt_cache:` / `prewarm:` per-node fields
- Cache rendering with `cache_control` markers
- Auto batch-prefix caching
- Trace format 2.1.0 (new fields)
- `pflow analyze-cache` command
- MCP `analyze_cache` tool
- `--dry-run` cache nudge
- `compute_node_config` conditional `prompt_cache` inclusion
- `NodeConfig` field additions (`prompt_cache_items`, `prewarm`)
- Direct read of `~/.config/io.datasette.llm/keys.json` (deferred to v1.x)
- Per-TTL cache-write pricing (deferred until 1h TTL feature lands)
- ClaudeCodeNode caching (out of scope per spec)

Phase B–G plan will be written after Phase A merges, informed by concrete LiteLLM behavior observed during Phase 0 + Phase A.
