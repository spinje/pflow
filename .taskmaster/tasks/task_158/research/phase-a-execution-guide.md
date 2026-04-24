# Phase A — Execution Guide

**Audience:** the agent picking up Task 158 at the start of Phase A.
**Prerequisites already satisfied:** Phase 0 spike executed and reported (progress-log §27). All five spike concerns have passed, outcomes decided.
**This document is forward-looking.** History, rationale, and design journey live in the braindumps and progress log — read those first if you haven't. This document is the **operational contract** for executing Phase A: what's decided, what changed vs the plan, what to do, what not to do, and how to verify.

---

## Table of contents

1. [Orientation — files and references](#1-orientation--files-and-references)
2. [Phase 0 outcomes applied — deltas to the plan](#2-phase-0-outcomes-applied--deltas-to-the-plan)
3. [Adapter API contract — concrete spec](#3-adapter-api-contract--concrete-spec)
4. [Exception translation reference](#4-exception-translation-reference)
5. [Test infrastructure transition — concrete recipe](#5-test-infrastructure-transition--concrete-recipe)
6. [Tracing redesign mechanic](#6-tracing-redesign-mechanic)
7. [Per-step execution deltas — A.1 through A.12](#7-per-step-execution-deltas--a1-through-a12)
8. [What NOT to touch / anti-patterns](#8-what-not-to-touch--anti-patterns)
9. [Verification playbook — commands at each checkpoint](#9-verification-playbook--commands-at-each-checkpoint)
10. [Quick-reference commands and snippets](#10-quick-reference-commands-and-snippets)

---

## 1. Orientation — files and references

### Where the design material lives

| Path | Purpose | When to read |
|---|---|---|
| `.taskmaster/tasks/task_158/task-158.md` | The spec — what and why | If you need the feature's *purpose* or design rationale |
| `.taskmaster/tasks/task_158/implementation/implementation-plan.md` | The original Phase 0+A plan | The canonical step list (this guide supplements, not replaces) |
| `.taskmaster/tasks/task_158/implementation/progress-log.md` | Design history + Phase 0 report | §27 has the Phase 0 spike report with pass/fail and outcomes |
| `.taskmaster/tasks/task_158/starting-context/braindump-design-complete.md` | Tacit knowledge, 2026-04-23 | User-principle phrases, what to avoid, unstated priorities |
| `.taskmaster/tasks/task_158/starting-context/braindump-phase-0-and-A-handoff-2026-04-24.md` | Tacit knowledge, 2026-04-24 | What changed in the last session, design shifts since the first braindump |
| `.taskmaster/tasks/task_158/research/phase-a-execution-guide.md` | **This document** | Start here once you've read the above |

### Where the spike artifacts live

| Path | Purpose |
|---|---|
| `scratchpads/task-158-spike/_common.py` | Key-loading + context-block helpers (not committed) |
| `scratchpads/task-158-spike/spike_{1..5}_*.py` | Five spike scripts (not committed) |
| `scratchpads/task-158-spike/spike_{1..5}_output.txt` | Raw outputs (not committed) |
| `scratchpads/task-158-spike/dep_audit.txt` | Clean-venv LiteLLM dep audit |

The spike scripts are throwaway. Feel free to delete them when Phase A lands. They are useful as runnable documentation if you want to re-verify any finding.

### Current git state (worktree, branch `feat/prompt-caching-lite-llm`)

- Base: commit `8349df88 ready for phase 0 + a`
- Uncommitted changes at Phase A start: progress-log.md update (Phase 0 report) + this file + the spike scripts
- Nothing has been committed yet for Phase A itself.

---

## 2. Phase 0 outcomes applied — deltas to the plan

Read `progress-log.md` §27 for the full Phase 0 report. Short list of decisions that change the plan:

### Locked decisions

1. **Outcome A confirmed — delete `core/llm_pricing.py` entirely in A.10.** No conditional branch. No "keep as fallback". The plan's A.10 reduces to a one-step cleanup.
2. **LiteLLM version pinned: `litellm==1.83.7`.** Use this exact string in `pyproject.toml`. The `v1.83.7-stable.patch.1` Docker tag is not on PyPI; `1.83.7` is the closest canonical release and Gemini PR #15226 is present. If anything breaks that only the `.patch.1` tag fixes, switch to a git-URL pin at that point — unlikely.
3. **Pattern Exception handling: port-in-place, do NOT introduce new retry infrastructure.** Replace the current `ValidationError` catch at `llm.py:298-311` with a catch for `litellm.exceptions.BadRequestError` at the same site, returning the same error dict. See §4 for exact code sketch. Rationale:
   - pflow's Node retry loop (`core/node.py:83-91`) does NOT respect `NonRetriableError` — it catches `Exception` and retries everything.
   - The existing PATTERN EXCEPTION local try/except is the actual mechanism. The comment in `llm.py:301` already says "Long-term fix: add NonRetriableError support to PocketFlow's _exec loop (#100)" — this is someone else's problem, not Phase A's.
   - Minimal diff = minimal risk. Matches existing pflow code patterns.
4. **`pflow settings env` is the A.9 help-text target for "set API keys via pflow".** Not `pflow settings llm`. User confirmed this pre-Phase-A. Verify the subcommand exists (`pflow settings env --help`) before writing help copy.
5. **Logger silencing: belt-and-suspenders approach.** `litellm==1.83.7` is quiet by default, but set `litellm.suppress_debug_info = True` at `llm_client.py` module import. Do not bother with the other knobs the plan listed (`set_verbose`, `_turn_on_debug`, logger-level muting) — they had no effect in the spike.
6. **Legacy `~/.config/io.datasette.llm/keys.json` direct-read is deferred to v1.x.** Do NOT add this in Phase A. Migration path for existing `llm`-stored keys is in the CHANGELOG note (A.12).

### Plan simplifications because of Outcome A

**A.10 used to be (3 branches):**
- A.10 Outcome A: delete `llm_pricing.py`, use `completion_cost()`
- A.10 Outcome B: LiteLLM primary, `llm_pricing.py` fallback for edge models
- A.10 Outcome C: vendor LiteLLM's `model_prices_and_context_window.json`, keep pflow math

**A.10 is now:**
- Delete `src/pflow/core/llm_pricing.py` entirely (189 lines gone)
- Rewrite `enrich_llm_usage_with_cost` as a 3-line function that reads `cost_usd` straight from `llm_usage` (the adapter already populated it)
- Update `src/pflow/core/__init__.py` exports (remove `calculate_llm_cost`, `enrich_llm_usage_with_cost`, `MODEL_PRICING`, etc. — verify which are exported)
- Grep for all `from pflow.core.llm_pricing import ...` call sites and rewire
- Fix `core/CLAUDE.md:198` drift ("46+ models" → remove the llm_pricing section entirely)

### Spec findings that affect implementation

1. **Two different token-accounting paths across providers.** The adapter must normalize both into one stable `usage` dict shape:
   - Anthropic: `usage.cache_creation_input_tokens` + `usage.cache_read_input_tokens` (both non-None).
   - Gemini/OpenAI: `usage.prompt_tokens_details.cached_tokens` (single field). Map this to `cache_read_input_tokens`.
   - `usage.cache_creation_input_tokens` should be `0` (not `None`) for non-Anthropic to keep downstream arithmetic simple.
2. **Anthropic requires `temperature=1` when thinking is enabled.** This is enforced by Anthropic's server. The adapter does not need to enforce it pre-request, but the error surface is `litellm.exceptions.BadRequestError` with a specific message. Current pflow code via `llm` library already hits this; the new adapter should propagate cleanly.
3. **Opus 4.5 cache behavior with thinking is unresolved** — not Phase A scope, flagged for Phase C. Both Opus thinking+cache calls in the spike showed zero cache writes and zero reads. Hypotheses: higher Opus cache minimum OR thinking silently disables cache_control. Verify in Phase C when cache rendering actually lands.
4. **The spec's plan for `## Cache` syntax, `prompt_cache:`, rendering, analyze-cache, etc. is out of scope for Phase A.** Do not touch any of that. Phase A preserves existing behavior only.

### Hidden Phase A work the plan downplayed

- **Translation from Pydantic-class schema to JSON-schema dict.** Two discovery callers (`registry/discovery.py:89` and `core/workflow/discovery.py:85`) currently pass a Pydantic class directly to `model.prompt(schema=Class)`. The adapter accepts only JSON-schema dicts. **Callers must convert:** `schema=Class.model_json_schema()`. A.7 lists this but it's easy to forget.
- **The `parse_structured_response` contract changes.** Current implementation at `core/llm_utils.py:40` reads `response.text()` (callable). Adapter returns `AdapterResponse.text` (attribute). Adjust in A.7.
- **`MockLLMModel`'s `_default_responses` mechanism for known schemas** (WorkflowDecision, ComponentSelection, etc.) is load-bearing — discovery tests depend on it. Preserve in `MockLLMClient`. Don't delete.

---

## 3. Adapter API contract — concrete spec

This section is the load-bearing one. If the adapter's shape is wrong, everything downstream breaks. Follow closely.

### File layout

**New files (created in A.2 and A.3):**

```
src/pflow/core/
├── llm_client.py          # The adapter — wraps litellm.completion
└── llm_reasoning_map.py   # Provider→reasoning-kwarg map (replaces live introspection)
```

### `llm_reasoning_map.py` shape (A.2)

Replaces the live introspection at `nodes/llm/llm.py:35-114` (`_map_reasoning_options`). Under the `llm` library, reasoning-option names were discovered by reading `model.Options.model_fields`. LiteLLM has no equivalent contract, so we hardcode a map.

```python
# src/pflow/core/llm_reasoning_map.py
from __future__ import annotations
from typing import Any

# MOVE FROM nodes/llm/llm.py:22-32
EFFORT_RATIOS = {"low": 0.2, "medium": 0.5, "high": 0.8}
DEFAULT_MAX_TOKENS_BASE = 4096


def map_reasoning_options(
    model: str,
    reasoning_effort: str | None,
    reasoning_max_tokens: int | None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Return the LiteLLM kwargs for reasoning/thinking based on model family.

    Provider detection by model-name string sniffing.

    CRITICAL ORDER INVARIANT: for Anthropic Opus 4.5 which exposes BOTH
    thinking_effort AND thinking_budget, thinking_effort MUST be checked first.
    Getting this wrong silently degrades Opus 4.5 reasoning. This precedence
    is preserved from nodes/llm/llm.py:53-56 in the current codebase.
    """
    if reasoning_effort is None and reasoning_max_tokens is None:
        return {}

    lower = model.lower()

    # Anthropic — thinking support
    if "anthropic/" in lower or lower.startswith("claude"):
        # ... compute budget_tokens from effort or explicit ...
        # Return: {"thinking": {"type": "enabled", "budget_tokens": N}}
        # Also note: temperature must be 1.0 when thinking is enabled, but
        # that's the caller's responsibility (LLMNode will handle it).
        ...

    # OpenAI — reasoning_effort support
    if "gpt" in lower or "openai/" in lower:
        # Return: {"reasoning_effort": "low" | "medium" | "high"}
        ...

    # Gemini — thinking_budget for 2.5 (not lite), thinking_level for 3
    if "gemini" in lower:
        # Mirror smart_filter.py:175-180 logic:
        # - gemini-2.5-*, NOT lite: thinking_budget=0 (by default) or mapped value
        # - gemini-3-*: thinking_level="minimal"|"low"|"medium"|"high"
        ...

    # Unknown provider → empty (graceful no-op)
    return {}
```

**Reading order for the existing code before writing this:**
1. `src/pflow/nodes/llm/llm.py:22-32` — `EFFORT_RATIOS` + `DEFAULT_MAX_TOKENS_BASE` (move verbatim)
2. `src/pflow/nodes/llm/llm.py:35-114` — `_map_reasoning_options` (translate logic; don't copy-paste, rewrite for the hardcoded-map approach)
3. `src/pflow/registry/smart_filter.py:169-180` — Gemini-variant sniffing precedent; reuse the same string patterns in your map
4. `src/pflow/nodes/llm/llm.py:52-56` — the "thinking_effort must be checked first" comment; encode this in your tests

**Tests:** `tests/test_core/test_llm_reasoning_map.py` — unit tests per provider/model, no network. Must explicitly cover Anthropic Opus 4.5 precedence (Opus 4.5 with `reasoning_effort="low"` emits `thinking.budget_tokens=<low-value>`, NOT `thinking.budget_tokens=<explicit-max>`).

### `llm_client.py` shape (A.3)

The adapter. Single seam for all LLM calls across pflow. Four callers will use this: `nodes/llm/llm.py`, `registry/discovery.py`, `registry/smart_filter.py`, `core/workflow/discovery.py`.

```python
# src/pflow/core/llm_client.py
"""pflow-owned LiteLLM adapter.

All the LiteLLM API-shape complexity stops here. Consumer code operates on
AdapterResponse, not litellm.ModelResponse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import litellm
import litellm.exceptions

# Belt-and-suspenders — LiteLLM 1.83.7 is quiet by default, but this is
# harmless and future-proofs against future chatter.
litellm.suppress_debug_info = True


TraceHook = Callable[[dict], None]
"""Called with a dict {'event': 'before_call' | 'after_call', 'prompt': str,
'model': str, 'response': AdapterResponse | None, 'error': str | None}.
Used by WorkflowTraceCollector to capture LLM prompts/responses into the trace
without a global monkey-patch. See §6."""


@dataclass
class Attachment:
    """An image attachment — either a local file path or a URL."""
    kind: Literal["image_path", "image_url"]
    value: str


@dataclass
class AdapterResponse:
    """Normalized LLM response shape. LLMNode.post() operates on this.

    Usage dict keys are STABLE — do not rename without coordinated updates
    across all consumers (llm_usage enrichment, trace format, MCP).
    """
    text: str                       # attribute, NOT callable (different from llm library)
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    has_schema: bool = False
    # When the adapter determines a deterministic error and returns instead of raising
    error: str | None = None
    status: Literal["ok", "error"] = "ok"


def complete(
    *,
    model: str,
    prompt: str,
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    attachments: list[Attachment] | None = None,
    schema: dict | None = None,            # JSON Schema dict, NOT Pydantic class
    reasoning_kwargs: dict | None = None,  # from llm_reasoning_map.map_reasoning_options
    model_options: dict | None = None,     # user-provided extra kwargs
    timeout: float | None = None,
    trace_hook: TraceHook | None = None,
) -> AdapterResponse:
    """Execute an LLM call via LiteLLM.

    Returns AdapterResponse. On deterministic errors (bad params, bad model,
    auth), returns an error-marked AdapterResponse so caller can handle without
    retrying. On other errors (timeout, network, rate limit), raises — caller's
    retry loop handles those.

    Design note: caller's retry loop at core/node.py:83-91 catches Exception and
    retries. For deterministic errors, returning (not raising) prevents 3
    wasted attempts. This preserves the PATTERN EXCEPTION pattern currently at
    nodes/llm/llm.py:298-311.
    """
    # 1. Build messages list
    messages: list[dict] = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    if attachments:
        # Inline user content as content blocks (image + text)
        content_blocks: list[dict] = []
        for a in attachments:
            if a.kind == "image_url":
                content_blocks.append({"type": "image_url", "image_url": {"url": a.value}})
            elif a.kind == "image_path":
                # Encode local file as data-url
                import base64, mimetypes
                with open(a.value, "rb") as fh:
                    data = base64.b64encode(fh.read()).decode()
                mime, _ = mimetypes.guess_type(a.value)
                url = f"data:{mime or 'application/octet-stream'};base64,{data}"
                content_blocks.append({"type": "image_url", "image_url": {"url": url}})
        content_blocks.append({"type": "text", "text": prompt})
        messages.append({"role": "user", "content": content_blocks})
    else:
        messages.append({"role": "user", "content": prompt})

    # 2. Build kwargs
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if timeout is not None:
        kwargs["timeout"] = timeout
    if schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": schema, "strict": True},
        }
    if reasoning_kwargs:
        kwargs.update(reasoning_kwargs)
    if model_options:
        kwargs.update(model_options)

    # 3. Trace hook — before call (captures the rendered prompt for
    #    trace format compatibility)
    if trace_hook is not None:
        trace_hook({"event": "before_call", "prompt": prompt, "model": model})

    # 4. Call LiteLLM, handling deterministic errors vs retriable errors
    try:
        response = litellm.completion(**kwargs)
    except litellm.exceptions.BadRequestError as e:
        # PATTERN EXCEPTION: deterministic server-side rejection. Retrying
        # the same bad request will produce the same error. Return an error-
        # marked response instead of raising, so the retry loop doesn't burn
        # N attempts. This preserves the pattern from nodes/llm/llm.py:
        # 298-311 that existed under the `llm` library with Pydantic
        # ValidationError.
        err = AdapterResponse(
            text="",
            model=model,
            has_schema=schema is not None,
            error=f"Invalid request for model '{model}': {e}",
            status="error",
        )
        if trace_hook is not None:
            trace_hook({"event": "after_call", "model": model, "response": err,
                        "error": err.error})
        return err
    # All other exceptions (Timeout, AuthenticationError, NotFoundError,
    # RateLimitError, InternalServerError, network) propagate — the caller's
    # retry loop may want to retry them.

    # 5. Normalize
    out = _normalize(response, model=model, has_schema=schema is not None)
    if trace_hook is not None:
        trace_hook({"event": "after_call", "model": model, "response": out})
    return out


def _normalize(response, *, model: str, has_schema: bool) -> AdapterResponse:
    """Convert litellm.ModelResponse → AdapterResponse with stable usage shape."""
    msg = response.choices[0].message
    text = msg.content or ""
    # Note: when reasoning is on, msg.reasoning_content carries thinking.
    # For Phase A, we ignore it (maintaining existing pflow behavior — the
    # `llm` library didn't surface this). If we want to expose it later,
    # extend AdapterResponse.

    usage_obj = response.usage

    # Normalize usage across providers.
    cache_creation = getattr(usage_obj, "cache_creation_input_tokens", None) or 0
    cache_read = getattr(usage_obj, "cache_read_input_tokens", None) or 0
    # Fallback to prompt_tokens_details.cached_tokens for Gemini/OpenAI
    if cache_read == 0:
        details = getattr(usage_obj, "prompt_tokens_details", None)
        if details is not None:
            cache_read = getattr(details, "cached_tokens", 0) or 0

    input_tokens = getattr(usage_obj, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage_obj, "completion_tokens", 0) or 0

    # Response cost — LiteLLM populates this on _hidden_params for most
    # providers. This replaces pflow's llm_pricing.py entirely.
    hidden = getattr(response, "_hidden_params", {}) or {}
    cost_usd = hidden.get("response_cost") if isinstance(hidden, dict) else None

    usage_dict = {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "cost_usd": cost_usd,
    }

    return AdapterResponse(
        text=text,
        usage=usage_dict,
        model=model,
        has_schema=has_schema,
    )
```

**Tests:** `tests/test_core/test_llm_client.py`. Cover via `unittest.mock.patch("litellm.completion")`:
- text-only call (minimal path)
- call with system prompt
- call with schema (assert `response_format` built correctly)
- call with attachments (image_url, image_path — assert content-block shape)
- call with reasoning_kwargs (assert pass-through)
- call with model_options (assert merged)
- BadRequestError → error-marked response, caller can check `.status == "error"`
- Timeout → raises (retriable)
- AuthenticationError → raises (retriable, but caller's fallback will show good message)
- Provider-specific usage normalization: patch Anthropic-shape response, Gemini-shape response, OpenAI-shape response — all three produce the stable usage dict with expected values.
- `trace_hook` invocation: before_call fires with prompt, after_call fires with response

---

## 4. Exception translation reference

Current pflow code at `nodes/llm/llm.py:422-465` detects two exception classes by string matching. Replace as below.

### Current code (A.5 will rewrite this block)

```python
# llm.py:435-452 (excerpt)
elif exc_type == "UnknownModelError" or "UnknownModelError" in error_msg or "Unknown model" in error_msg:
    ...
elif exc_type == "NeedsKeyException" or "NeedsKeyException" in error_msg:
    ...
```

### Replacement in A.5

```python
import litellm.exceptions as lex

# ... in exec_fallback(self, prep_res, exc):

if isinstance(exc, (TimeoutError, FuturesTimeoutError, lex.Timeout)):
    # existing behavior — user-friendly timeout message
    ...

elif isinstance(exc, lex.NotFoundError):
    # was UnknownModelError — model exists but unknown to the provider
    from pflow.core.llm_config import get_default_llm_model
    detected_model = get_default_llm_model()
    if detected_model:
        error_detail = (
            f"Unknown model: {prep_res['model']}. "
            f"Tip: Your API key supports '{detected_model}'. "
            f"Run 'pflow settings llm show' to see configured models."
        )
    else:
        error_detail = (
            f"Unknown model: {prep_res['model']}. "
            f"Run 'pflow settings llm show' to see available models."
        )

elif isinstance(exc, lex.AuthenticationError):
    # was NeedsKeyException — wrong or missing key
    error_detail = (
        f"API key required for model: {prep_res['model']}. "
        f"Set the appropriate environment variable "
        f"(e.g., ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY) "
        f"or configure via 'pflow settings env set'."
    )

elif isinstance(exc, lex.BadRequestError) and "LLM Provider NOT provided" in str(exc):
    # Unknown provider prefix — also effectively "unknown model" to the user
    error_detail = (
        f"Unknown model/provider: {prep_res['model']}. "
        f"Use provider prefix (e.g., 'anthropic/claude-sonnet-4-5', "
        f"'openai/gpt-4o-mini', 'gemini/gemini-2.5-flash')."
    )

else:
    error_detail = (
        f"LLM call failed after {self.max_retries} attempts. "
        f"Model: {prep_res['model']}. Error: {error_msg}"
    )
```

### BadRequestError PATTERN EXCEPTION handling

**Already described in §3 (`llm_client.py` code sketch).** It is handled INSIDE the adapter, not in `exec_fallback`. When the adapter catches `BadRequestError`, it returns an `AdapterResponse` with `status="error"` and a non-empty `error` field. `LLMNode._call_llm` unpacks this into the error dict as before; `post()` routes to the error branch. No retry burned.

Note: if a `BadRequestError` surfaces in `exec_fallback` anyway (e.g. caught at a higher layer), the last branch in the `exec_fallback` table above catches it with the generic message. That's the safety net.

---

## 5. Test infrastructure transition — concrete recipe

### The problem with a hard cutover

`tests/conftest.py:11-35` installs `mock_llm_calls` as a **class-autouse** fixture. Every test across the suite gets it. If you delete this fixture while rewiring LLMNode, you fail hundreds of tests simultaneously.

### The coexistence plan (A.4 → A.8)

Two fixtures live side-by-side during A.4–A.7. Cleanup happens in A.8.

**A.4: add, don't replace.**
- Add `MockLLMClient` class to `tests/shared/llm_mock.py` (keep `MockLLMModel` and `MockGetModel` in place).
- Add `mock_llm_client` autouse fixture to `tests/conftest.py` that patches `pflow.core.llm_client.complete` with a method on `MockLLMClient`. Same `/llm/` path skip.
- Both fixtures coexist — tests that don't touch the adapter still work via `mock_llm_calls`.

**A.5: callers start migrating.**
- Rewire `LLMNode._call_llm` to call `llm_client.complete(...)` instead of `llm.get_model(...).prompt(...)`.
- Tests in `tests/test_nodes/test_llm/test_llm.py` start asserting against `MockLLMClient.call_history` instead of `Mock()`-built responses.

**A.7: remaining callers migrate.**
- `registry/discovery.py`, `registry/smart_filter.py`, `core/workflow/discovery.py` — same rewire. Their tests move to `mock_llm_client`.

**A.8: cleanup.**
- Delete `MockLLMModel`, `MockGetModel`, `create_mock_get_model` from `tests/shared/llm_mock.py`.
- Delete `mock_llm_calls` fixture from `tests/conftest.py`.
- Any test that still imported `MockLLMModel` directly gets updated.
- Run `make test` — green.

### `MockLLMClient` shape

Mirror the public surface of `MockLLMModel`, but emit `AdapterResponse` dataclass instances (not `Mock()` objects with callable attributes).

```python
# tests/shared/llm_mock.py (add — do NOT delete MockLLMModel yet)
from dataclasses import dataclass, field
from typing import Any, Callable
from pflow.core.llm_client import AdapterResponse


DEFAULT_RESPONSES_BY_SCHEMA = {
    # Migrate MockLLMModel._default_responses here — these are what make
    # workflow-discovery tests work without explicit setup. Preserve verbatim.
    "WorkflowDecision": {...},
    "ComponentSelection": {...},
    # ... etc
}


@dataclass
class MockLLMClient:
    call_history: list[dict] = field(default_factory=list)
    call_history_full: list[dict] = field(default_factory=list)  # untruncated — new
    responses: dict[str, AdapterResponse] = field(default_factory=dict)
    default_response_text: str = "OK"

    def set_response(self, key: str, response: AdapterResponse | dict) -> None:
        """key is a schema name OR a prompt substring for matching."""
        ...

    def get_response(self, prompt: str, schema: dict | None = None) -> AdapterResponse:
        # 1. If schema is set and schema.title matches a DEFAULT key, emit default
        # 2. Else check self.responses for a match
        # 3. Else emit a plain-text response
        ...

    def reset(self) -> None:
        self.call_history.clear()
        self.call_history_full.clear()
        self.responses.clear()

    # The actual patch target
    def complete(
        self, *, model: str, prompt: str, system: str | None = None,
        schema: dict | None = None, **kwargs
    ) -> AdapterResponse:
        # Record call
        self.call_history.append({
            "model": model,
            # 500-char truncation to match legacy behavior (llm_mock.py:30)
            "prompt": prompt[:500],
            "system": (system or "")[:500],
            "has_schema": schema is not None,
            "kwargs": kwargs,
        })
        self.call_history_full.append({
            "model": model,
            "prompt": prompt,
            "system": system,
            "schema": schema,
            "kwargs": kwargs,
        })
        return self.get_response(prompt, schema=schema)
```

**Critical preservation:** the 500-char truncation on `call_history[i]["prompt"]`. Several existing tests assert against this (e.g., `tests/test_integration/test_metrics_integration.py`, plus Gemini-smart-filter tests). Keep it as the default. `call_history_full` is the new untruncated path added for Phase B/C cache-structure tests — but **do not require tests to use it in Phase A**.

**`tests/conftest.py` (A.4) — the new fixture:**

```python
# tests/conftest.py (additions — do NOT remove mock_llm_calls yet)
import pytest
from tests.shared.llm_mock import MockLLMClient


@pytest.fixture(autouse=True)
def mock_llm_client(monkeypatch, request):
    """Autouse fixture patching llm_client.complete with MockLLMClient.complete.

    Skip when the test path contains /llm/ — those are integration tests that
    want the real adapter (which hits real APIs under RUN_LLM_TESTS=1).
    """
    if "/llm/" in str(request.fspath):
        yield None
        return
    mock = MockLLMClient()
    # Patch all import sites — each consumer imports `complete` separately
    monkeypatch.setattr("pflow.core.llm_client.complete", mock.complete)
    # Nodes/discovery/smart_filter import it — patch their namespace too
    for module_path in (
        "pflow.nodes.llm.llm.complete",
        "pflow.registry.discovery.complete",
        "pflow.registry.smart_filter.complete",
        "pflow.core.workflow.discovery.complete",
    ):
        try:
            monkeypatch.setattr(module_path, mock.complete, raising=False)
        except Exception:
            pass
    yield mock
```

If a test module imports `from pflow.core import llm_client` and then calls `llm_client.complete(...)`, patching `pflow.core.llm_client.complete` is sufficient. If callers do `from pflow.core.llm_client import complete` and call `complete(...)` at module scope, patch their namespace too. Err on the side of patching both.

---

## 6. Tracing redesign mechanic

### Why this is the riskiest step

The current monkey-patch at `runtime/workflow_trace.py:520-599` has sophistication the task spec's "function-call replacement" phrasing hid:
- **Two layers** of interception: replaces `llm.get_model` (returns wrapped model), then per-instance replaces `model.prompt` (captures args).
- **Reference-counted** via class-level `_llm_interception_count` for nested workflows.
- **Per-thread state**: `_thread_local.current_node` (which node is currently executing) + `_active_collectors[thread_id]` (which trace collector is active).
- **Lock-protected** via `_llm_lock` (threading.Lock).
- **Lazy install/teardown** — only patches when at least one collector is active.
- **Sub-workflow collectors** set `enable_llm_interception=False` to inherit parent's interception (avoids double-wrapping).

If A.6 breaks any of this, `test_plan_drift.py` fails AND trace JSON files lose their `llm_prompt`/`llm_response` fields. Both would block PR merge.

### The replacement design — trace_hook pattern

The adapter takes an optional `trace_hook: Callable[[dict], None]` parameter. When a workflow is being traced, LLMNode passes `trace_hook=collector.get_trace_hook(self.cur_node_id)` to the adapter.

**Inside LLMNode._call_llm:**

```python
trace_hook = None
thread_id = threading.get_ident()
collector = WorkflowTraceCollector._active_collectors.get(thread_id)
if collector is not None:
    trace_hook = collector.get_trace_hook(self.cur_node_id)

adapter_response = llm_client.complete(
    ...,
    trace_hook=trace_hook,
)
```

**Inside WorkflowTraceCollector:**

```python
def get_trace_hook(self, node_id: str) -> Callable[[dict], None]:
    """Return a callable that the adapter invokes with event dicts.

    Captures the rendered prompt and response into self.llm_prompts[node_id]
    and self.llm_responses[node_id] — same keys as the monkey-patch populated.
    """
    def hook(event: dict) -> None:
        if event["event"] == "before_call":
            self.llm_prompts[node_id] = event["prompt"]
        elif event["event"] == "after_call":
            resp = event.get("response")
            if resp is not None:
                self.llm_responses[node_id] = resp.text
                # also self.llm_usages[node_id], etc. — match current shape
    return hook
```

**What stays:**
- `_active_collectors[thread_id]` registry — still needed. Consumption moves from "inside the patched `prompt` function" to "inside LLMNode._call_llm".
- `_thread_local.current_node` — still needed for nested-workflow isolation.
- `_llm_lock` protecting the registry mutations — still needed.

**What goes:**
- `setup_llm_interception` / `cleanup_llm_interception` (class methods) — DELETE.
- The monkey-patch of `llm.get_model` — DELETE.
- Reference counting via `_llm_interception_count` — DELETE (no lifecycle to manage).
- Lazy `import llm` calls — DELETE.

### The 3 non-LLMNode call sites

`registry/discovery.py`, `registry/smart_filter.py`, `core/workflow/discovery.py` historically got traced through the monkey-patch. Per the plan: **they pass `trace_hook=None` after A.6**. These callers don't run inside a workflow trace context anyway.

**Pre-emptive sanity check in A.6 (takes 2 minutes):** grep for tests that assert on smart_filter or discovery prompts in trace output. If any exist, they document behavior we're dropping. Currently there are no such tests based on codebase patterns, but verify:

```bash
grep -rn "llm_prompts.*smart_filter\|llm_prompts.*discovery" tests/
```

### The sacred test

`tests/test_execution/test_plan_drift.py` has 32 tests asserting planner↔runtime parity. After A.6 lands, run this test in isolation BEFORE anything else. If it fails, the tracing redesign affected execution semantics — stop, investigate, fix.

```bash
uv run pytest tests/test_execution/test_plan_drift.py -x -v
```

### Manual verification after A.6

Run any workflow that exercises LLM nodes. Inspect the trace file at `~/.pflow/debug/workflow-trace-*.json`. Confirm:
- `event["llm_prompt"]` populates (the rendered prompt for that node)
- `event["llm_response"]` populates (the response text)
- `event["llm_call"]` populates (the usage dict with cached/non-cached tokens)

If any of these is missing or empty, the trace_hook wiring is wrong somewhere.

---

## 7. Per-step execution deltas — A.1 through A.12

**The plan's ordered step list is authoritative. This section only lists deltas** — what Phase 0 changed, what gotchas to watch for, and where §3-§6 apply.

### A.1 — Install LiteLLM

- `pyproject.toml`: add exact pin `"litellm==1.83.7"` to `[project] dependencies`. **Do NOT remove** `llm`/`llm-anthropic`/`llm-gemini` yet.
- `uv.lock`: regenerate via `uv sync`.
- **Verification:** `uv pip list | grep litellm` shows 1.83.7 exactly. `uv run pytest tests/test_core/` still passes (no production code changed yet).
- Commit: one commit.

### A.2 — `llm_reasoning_map.py`

See §3 for the module shape. Key preservation points:
- Move `EFFORT_RATIOS` and `DEFAULT_MAX_TOKENS_BASE` constants verbatim from `nodes/llm/llm.py:22-32`.
- **Order invariant test:** Opus 4.5 with `reasoning_effort` MUST emit `thinking.budget_tokens`, not defer to `thinking_budget` kwarg if also set. Explicit test required.
- Gemini string-sniffing: reuse patterns from `registry/smart_filter.py:169-180`.
- **Not yet used by production code** — this file is imported by `llm_client.py` in A.3. Tests stand alone.

### A.3 — `llm_client.py`

See §3 for the full module sketch. Specific points:
- **Do not import Pydantic.** The adapter returns a plain `dataclasses.dataclass`. Don't add `BaseModel`.
- **Do not attempt to detect token thresholds** (1024 / 2048) in Phase A. That belongs in Phase C.
- **Do not implement cache rendering** — no `cache_control` markers, no `## Cache` parsing. Phase A is pure library migration.
- Tests are critical here — this is the load-bearing contract. Full `test_llm_client.py` with mocked `litellm.completion`.

### A.4 — Test infrastructure rewrite

See §5 for the full recipe. The pattern is **coexistence, not replacement** — both old and new fixtures active during A.4–A.7.

### A.5 — Rewire LLMNode to the adapter

**The PATTERN EXCEPTION decision (from §2.3) applies here.** The block at `llm.py:298-311` becomes:

```python
# BEFORE (llm.py:298-311, to be deleted)
try:
    response = model.prompt(prep_res["prompt"], **kwargs)
except ValidationError as e:
    return {"response": "", "error": f"...", "model": ..., "usage": {}, "status": "error"}
text = response.text()
usage_obj = response.usage()
return {"response": text, "usage": usage_obj, ...}

# AFTER
adapter_response = llm_client.complete(
    model=prep_res["model"],
    prompt=prep_res["prompt"],
    system=prep_res.get("system"),
    temperature=prep_res["temperature"],
    max_tokens=prep_res.get("max_tokens"),
    attachments=_build_attachment_list(prep_res),  # new helper
    schema=prep_res.get("output_schema"),
    reasoning_kwargs=map_reasoning_options(
        prep_res["model"],
        prep_res.get("reasoning_effort"),
        prep_res.get("reasoning_max_tokens"),
        prep_res.get("max_tokens"),
    ),
    model_options=prep_res.get("model_options"),
    timeout=prep_res.get("timeout"),
    trace_hook=_get_trace_hook(self.cur_node_id),  # see §6
)
if adapter_response.status == "error":
    # adapter caught a deterministic BadRequestError — no retry needed
    return {
        "response": "",
        "error": adapter_response.error,
        "model": adapter_response.model,
        "usage": {},
        "status": "error",
    }
return {
    "response": adapter_response.text,
    "usage": adapter_response.usage,  # already-dict; no object path
    "model": adapter_response.model,
    "has_schema": adapter_response.has_schema,
}
```

**Delete:** the `ValidationError` import. The `model = llm.get_model(...)` call. The `_map_reasoning_options` function (moved to `llm_reasoning_map`). The constants at lines 22-32. The `from pydantic import ValidationError` import.

**`post()` simplification:** the current `llm_usage` extraction at `llm.py:370-405` has two paths — dict vs object with `.input`/`.output`/`.details`. Since the adapter normalizes to a dict, **delete the object-path branch entirely.** Single dict-read code path.

**Tests to re-shape:** `tests/test_nodes/test_llm/test_llm.py` has ~20 inline `Mock()` assertions with `.text.return_value = "..."`. Reshape these to use `MockLLMClient.set_response(...)` with `AdapterResponse` instances. Tests that asserted on `mock_response.text.assert_called_once()` switch to `MockLLMClient.call_history[n]["prompt"]` assertions.

### A.6 — Tracing redesign

See §6 for the full mechanic. Non-negotiable rules:
- Do NOT delete `_active_collectors[thread_id]` or `_thread_local.current_node` — these are reused.
- Do NOT touch `test_plan_drift.py` — if it fails, the change is wrong.
- Keep the two mechanisms overlapping briefly: adapter calls already have `trace_hook` plumbed by end of A.5 (you wire that up in A.5 already). A.6 deletes the monkey-patch only.

### A.7 — 3 other call sites

Mechanical. Same pattern as A.5 but shallower. Gotcha: **Pydantic class → JSON Schema dict translation.**

```python
# BEFORE (registry/discovery.py:88, workflow/discovery.py:85, etc.)
response = model.prompt(prompt, schema=ComponentSelectionSchema)

# AFTER
adapter_response = llm_client.complete(
    model=...,
    prompt=prompt,
    schema=ComponentSelectionSchema.model_json_schema(),  # ← .model_json_schema()!
)
```

**`core/llm_utils.py::parse_structured_response` adjustment:** current code reads `response.text()` (callable). Adapter returns `AdapterResponse.text` (attribute). Adjust to `response.text`.

### A.8 — Mass test migration

Follow the A.4-§5 cleanup plan. Delete `MockLLMModel`, `MockGetModel`, `create_mock_get_model`. Delete `mock_llm_calls`. Run `make test`. Green or stop and fix.

### A.9 — `llm_config.py` and `settings.py` cleanup

Detailed in the plan; the only Phase 0 delta is "use `pflow settings env`" in help text instead of the circular self-reference. Specific deletions from `llm_config.py`:

- `_has_llm_key()` (53-99) — DELETE
- `get_llm_cli_default_model()` (348-387) — DELETE
- `LLM_COMMAND` (23) — DELETE
- `_LLM_KEYS_SUBCOMMAND` (37) — DELETE

Update `_has_provider_key()` to remove the `_has_llm_key()` fallback (two sources only: env + pflow settings).

Update `_detect_default_model()` — remove the `PYTEST_CURRENT_TEST` subprocess guard at lines 164-166 (no subprocess to guard).

Update `get_llm_setup_help()` — replace `llm keys set anthropic`/etc. with:
```
Set provider API keys via environment variables:
  export ANTHROPIC_API_KEY=...
  export OPENAI_API_KEY=...
  export GEMINI_API_KEY=...

Or configure them in pflow settings:
  pflow settings env set <KEY_NAME> <value>
```

Update `get_model_not_configured_help()` — replace `llm models default`/`llm models list` references with pflow equivalents (`pflow settings llm show`).

**`pyproject.toml` cleanup:** remove the `S603` ignore for `llm_config.py` at line 178 if no subprocesses remain in the file. Verify with `grep -n subprocess src/pflow/core/llm_config.py`.

**`inject_settings_env_vars()` UNCHANGED.** LiteLLM reads from `os.environ` natively; existing pipeline still works.

### A.10 — Pricing cleanup (SIMPLIFIED)

Per Outcome A:

- **DELETE** `src/pflow/core/llm_pricing.py` entirely.
- **Rewrite** `enrich_llm_usage_with_cost(llm_usage)` as a tiny replacement (probably move to `core/llm_client.py` or inline in callers):
  ```python
  def enrich_llm_usage_with_cost(llm_usage: dict) -> None:
      """The adapter already populates cost_usd. This wrapper preserves the
      public API for migration; may be deleted once consumers are updated."""
      if "cost_usd" in llm_usage:
          return
      # Fallback for llm_usage dicts from non-adapter sources (e.g., Claude Code SDK)
      if "total_cost_usd" in llm_usage and llm_usage["total_cost_usd"] is not None:
          llm_usage["cost_usd"] = llm_usage["total_cost_usd"]
      else:
          llm_usage["cost_usd"] = None
  ```
- **Grep** for all `from pflow.core.llm_pricing import` call sites. Likely in:
  - `core/__init__.py` — remove exports
  - `core/metrics.py` — uses pricing
  - `nodes/claude/claude_code.py` — reads `total_cost_usd` from SDK, check
  - tests
- **Fix docs:** `core/CLAUDE.md:198` ("46+ models") — update the `llm_pricing.py` entry to reflect the deletion. Remove the `🐛 Broken aliases` callout for `claude-3.5-haiku` and `claude-4-opus` — those aliases are gone with the table.
- **Cost dict behavior:** `cost_usd` may be `None` when LiteLLM doesn't know the model (e.g., custom-endpoint models, unknown Ollama models). Consumers MUST handle `None`. Current code that reads `cost_usd` already tolerates this.

### A.11 — Remove old deps

- `pyproject.toml`: delete `llm>=0.29`, `llm-anthropic==0.25`, `llm-gemini>=0.30`.
- `pyproject.toml:184` `DEP002`: trim to just `["PyYAML"]` (remove `llm-anthropic`, `llm-gemini`).
- `uv.lock`: regenerate via `uv sync`.
- **Verification:** `uv pip list | grep -E '^(llm|llm-)'` returns nothing. `make check` green.
- **Gotcha:** `deptry` may flag newly-unused or newly-transitive deps. Address by updating `DEP002` or per its diagnostic output.

### A.12 — Documentation and CHANGELOG

Update:
- `pflow guide` LLM-node doc: remove any `llm keys` / `llm models` references, point to env vars + `pflow settings env set`.
- `src/pflow/core/CLAUDE.md`: remove the `llm_pricing.py` section entirely; update `llm_config.py` section to remove subprocess mentions.
- `src/pflow/nodes/llm/CLAUDE.md`: update to mention the adapter, not the `llm` library.
- Mintlify docs under `docs/reference/cli/` and settings pages — grep for `llm keys`.
- **CHANGELOG note** (user-facing):
  ```
  v0.X — removed Simon Willison's `llm` library dependency. pflow now uses
  LiteLLM directly for provider connectivity. API keys must be set via
  environment variables (ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY)
  or configured via `pflow settings env set <KEY_NAME> <value>`. Existing keys
  stored via `llm keys set ...` will not be picked up automatically — transfer
  them to env vars or pflow settings manually. Direct read of legacy
  keys.json is planned for a future release.
  ```

---

## 8. What NOT to touch / anti-patterns

### Files / behavior preservation

- **`tests/test_execution/test_plan_drift.py`** — 32 sacred parity tests. Do not weaken or delete. If it goes red, stop.
- **Lyrics-generator workflows at `/Users/andfal/projects/music-generation/workflows/lyrics-generator/`** — user's project, do not modify.
- **Example workflows under `examples/`** — 7 of them use `- cache: false` (the pflow memoization field). These must continue working untouched.
- **`core/llm_config.py::inject_settings_env_vars()`** — UNCHANGED. Same signature, same behavior.
- **`MockLLMModel._default_responses`** — move to `MockLLMClient.DEFAULT_RESPONSES_BY_SCHEMA` (or similar); do not delete. Discovery tests depend on it.
- **The 500-char truncation on `call_history[n]["prompt"]`** — several tests assert against this. New `call_history_full` is additive.

### Behaviors to preserve EXACTLY

- **User-facing error messages close to current text.** Users have muscle memory. Keep the "Unknown model: X. Tip: ... Run 'pflow settings llm show'" shape. The only change is `llm models` → `pflow settings llm show`.
- **Anthropic Opus 4.5 reasoning precedence.** `thinking_effort` checked BEFORE `thinking_budget`. Explicit test in `test_llm_reasoning_map.py`.
- **`AdapterResponse.usage` dict keys.** They match what `llm_usage` currently has (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `total_tokens`, `model`, `cost_usd`). Don't rename.

### Anti-patterns to actively avoid

- **Don't add `NonRetriableError` plumbing to the Node retry loop.** That's a separate refactor; the PATTERN EXCEPTION pattern is the correct Phase A approach. See §2.3.
- **Don't preemptively implement anything for Phase B+.** No `## Cache` parsing. No `prompt_cache:` field. No `cache_control` markers. No `analyze-cache`. No trace format bump. Phase A is pure library migration.
- **Don't use `litellm[proxy]` extras.** Plain `litellm` is sufficient — spike confirmed no boto3/azure/google-cloud bloat in the default.
- **Don't delete `llm` / `llm-anthropic` / `llm-gemini` from `pyproject.toml` before A.11.** Keeping them active until all callers migrate means tests can validate incrementally.
- **Don't commit Phase A as one PR.** Follow the 12-commit sequence. Green at every step.
- **Don't `git commit` or `git push` without explicit user permission.** Auto-memory rule. Make changes locally, let user review.

---

## 9. Verification playbook — commands at each checkpoint

### At every step

```bash
# Quick sanity — runs under 10 seconds:
uv run pytest tests/test_core/ -x -q

# Moderate — 30-60 seconds:
make test

# Full — 2-3 minutes; gate on quality:
make check   # ruff + mypy + deptry + pre-commit
```

### After A.1 (install LiteLLM)

```bash
uv pip list | grep -E '^(litellm|llm)'   # both present; litellm==1.83.7
uv run pytest -q                          # all tests still green (no prod changes)
```

### After A.2 (llm_reasoning_map.py)

```bash
uv run pytest tests/test_core/test_llm_reasoning_map.py -v
```

Explicit test expectations:
- Opus 4.5 + reasoning_effort=low → `{"thinking": {"type": "enabled", "budget_tokens": ~820}}` (0.2 * 4096)
- Opus 4.5 + reasoning_max_tokens=8000 → `{"thinking": {..., "budget_tokens": 8000}}`
- Opus 4.5 + BOTH → thinking_effort wins (budget derived from effort ratio)
- Gemini-2.5-flash + reasoning_effort=low → `{"thinking_budget": <low value>}` (NOT `-lite` variant)
- Gemini-2.5-flash-lite + reasoning_effort=low → `{}` (lite variant has no thinking)
- Gemini-3 + reasoning_effort=medium → `{"thinking_level": "medium"}`
- OpenAI gpt-5-mini + reasoning_effort=high → `{"reasoning_effort": "high"}`
- Unknown model → `{}` (graceful no-op)

### After A.3 (llm_client.py)

```bash
uv run pytest tests/test_core/test_llm_client.py -v
```

### After A.5 (LLMNode rewired)

```bash
# First: plan-drift test — MUST be green
uv run pytest tests/test_execution/test_plan_drift.py -v

# Then: LLMNode tests
uv run pytest tests/test_nodes/test_llm/ -x -v

# Then: broader test suite
make test
```

### After A.6 (tracing redesign)

```bash
# Sacred — in isolation:
uv run pytest tests/test_execution/test_plan_drift.py -x -v

# Full trace tests:
uv run pytest tests/test_runtime/ -v
uv run pytest tests/test_execution/ -v

# Manual: run a trivial workflow, inspect trace:
echo 'Test cache' | uv run pflow examples/cat.pflow.md
ls -lt ~/.pflow/debug/workflow-trace-*.json | head -1
# open the newest trace; grep for llm_prompt, llm_response, llm_call events
```

### After A.7 (3 other call sites)

```bash
uv run pytest tests/test_registry/ -v
uv run pytest tests/test_core/test_workflow_discovery.py -v
```

### After A.8 (mass migration)

```bash
make test
make check
# Should be fully green with only the new adapter path active.
```

### After A.9 (llm_config cleanup)

```bash
uv run pytest tests/test_core/ -k 'llm_config' -v
uv run pflow settings llm show   # confirm output sensible, no `llm` binary refs
```

### After A.10 (pricing cleanup)

```bash
uv run pytest tests/ -k 'cost or pricing or llm_usage' -v
# Smoke test with a real API call if keys are available:
uv run pflow examples/cat.pflow.md <<<'Hello'   # should run, trace should have cost_usd
```

### After A.11 (remove old deps)

```bash
uv pip list | grep -E '^(llm|llm-)'   # expect NO MATCHES
uv pip list | grep litellm             # expect 1.83.7
make check                             # deptry, etc.
```

### After A.12 (docs)

```bash
# Sanity: no residual `llm keys` references in production code:
grep -rn "llm keys\|llm models" src/pflow/ docs/ .taskmaster/
# (Should only appear in historical docs like .taskmaster/tasks/task_95/ — historical is fine.)
```

### End-of-Phase-A smoke tests (before PR)

```bash
# 1. Integration tests with real API keys
RUN_LLM_TESTS=1 uv run pytest tests/test_nodes/test_llm/test_llm_integration.py -v

# 2. Full matrix
make test && make check

# 3. Workflow smoke test — run the user's lyrics-generator? DON'T (it's their money).
#    Use a cheap 3-step workflow:
cat > /tmp/smoke.pflow.md << 'EOF'
# Smoke Test

Minimal workflow to verify LLM node works post-LiteLLM migration.

## Steps

### greet
- type: llm
- model: gemini/gemini-2.5-flash
- prompt: Reply with exactly the words "SMOKE TEST OK".

## Outputs
- result:
  - source: greet.response
EOF

uv run pflow /tmp/smoke.pflow.md

# 4. Confirm trace
ls -lt ~/.pflow/debug/workflow-trace-*.json | head -1 | awk '{print $NF}' | xargs cat | python -m json.tool | grep -E 'llm_prompt|llm_response|llm_call|cost_usd'
```

### What "green" means per step

`make test` = 0 failures, 0 errors. All existing tests pass. No new XFail. Deprecation warnings are tolerable.

`make check` = ruff clean, mypy clean, deptry clean, pre-commit clean. Any new warning gets addressed in that same step, not deferred.

If ANY verification fails at step N, **resolve before commit**. Do not defer past the step that introduced the break.

---

## 10. Quick-reference commands and snippets

### Key-loading for integration tests

```bash
# Fetch provider API keys into the shell (as used by the Phase 0 spike)
export ANTHROPIC_API_KEY=$(uv run llm keys get anthropic)
export OPENAI_API_KEY=$(uv run llm keys get openai)
export GEMINI_API_KEY=$(uv run llm keys get gemini)

# Run integration tests
RUN_LLM_TESTS=1 uv run pytest tests/test_nodes/test_llm/test_llm_integration.py -v
```

### Re-running any Phase 0 spike

```bash
# All spikes land under scratchpads/task-158-spike/
uv run --with litellm==1.83.7 python scratchpads/task-158-spike/spike_1_cache_mechanics.py
uv run --with litellm==1.83.7 python scratchpads/task-158-spike/spike_3_pricing.py
# ... etc
```

### Quick-inspect LiteLLM's model data

```python
import litellm
litellm.model_cost["claude-sonnet-4-5"]
# → {'max_tokens': ..., 'input_cost_per_token': 3e-06, 'output_cost_per_token': 1.5e-05, 'cache_read_input_token_cost': 3e-07, ...}

litellm.cost_per_token(model="gemini/gemini-2.5-flash", prompt_tokens=1000, completion_tokens=100, cache_read_input_tokens=800)
# → (input_cost, output_cost) tuple of floats
```

### Bisection help

If a test passes after A.5 but fails after A.6:
```bash
git diff HEAD~1 -- src/pflow/runtime/workflow_trace.py
# Focus on the tracing redesign
```

If `test_plan_drift.py` goes red:
```bash
uv run pytest tests/test_execution/test_plan_drift.py::test_NAME -x -v -s
# -s flag shows print() output — useful for debugging
```

### Useful greps during migration

```bash
# Find all remaining `llm` library imports after A.7:
grep -rn 'import llm$\|from llm import' src/pflow/
# Expect: zero matches by end of A.7

# Find all `llm.get_model` references:
grep -rn 'llm\.get_model' src/pflow/ tests/

# Find `response.text()` callable pattern (must become `.text` attribute):
grep -rn 'response\.text()' src/pflow/

# Find `response.usage()` callable pattern:
grep -rn 'response\.usage()' src/pflow/
```

### Config files you'll touch

- `pyproject.toml` — A.1 (add litellm), A.11 (remove llm trio)
- `uv.lock` — A.1, A.11 (`uv sync` regenerates)
- `src/pflow/core/__init__.py` — A.10 (remove pricing exports)
- `tests/conftest.py` — A.4 (add mock_llm_client), A.8 (remove mock_llm_calls)
- `src/pflow/core/CLAUDE.md` — A.10, A.12 (update llm_config + llm_pricing sections)
- `src/pflow/nodes/llm/CLAUDE.md` — A.12 (update library references)

### Questions to ask the user if you hit

- **Test that was passing in main but fails after my changes, and I can't see how** — don't silently weaken the test. Ask.
- **An external workflow (not a test) breaks when I run it manually** — don't commit. Ask.
- **LiteLLM returns a surprising exception type I didn't plan for** — don't catch-all. Ask.
- **You want to add a feature not in this guide** — don't. Phase A is pure migration; features are later phases.

### Staying oriented during long steps

Use `TaskCreate` / `TaskUpdate` to track the 12 steps as a checklist. Mark each `in_progress` when you start and `completed` when verified. Tests green = step completed. Anything else = the step is still in progress.

---

## Appendix A — A one-page sanity check before starting

Before writing a line of code, answer:

1. Have I read `task-158.md`, `progress-log.md`, `implementation-plan.md`, both braindumps, and this guide?
2. Do I have all three API keys set (or loaded via `uv run llm keys get`)?
3. Is the git tree clean except for the expected Phase 0 artifacts (progress-log update, scratchpads/, this file)?
4. Do I understand that commits are ONLY made with explicit user permission?
5. Do I know which step I'm on, and what "green" means for that step?
6. Do I have a reason to deviate from the plan? (If yes, surface and discuss first.)

If all yes → start A.1.

---

## Appendix B — After Phase A lands

Next steps (NOT to be done in this session — just so you know where things go):

1. Open PR for Phase A. User reviews.
2. After merge, write `implementation/plan-phase-B-through-G.md` informed by the concrete LiteLLM behavior observed during Phase A.
3. That plan covers: `## Cache` parsing (B), cache rendering (C), auto batch-prefix + prewarm (D), trace format 2.1.0 (E), `pflow analyze-cache` + MCP parity + dry-run nudge (F), deterministic serialization + docs (G).
4. The Opus cache behavior with thinking (flagged in Phase 0 report) gets properly investigated in Phase C when cache rendering lands.

You are not responsible for Phases B–G. Phase A ending is a clean stopping point.
