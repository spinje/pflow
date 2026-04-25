"""pflow-owned LiteLLM adapter — single seam for all LLM calls.

All LiteLLM API-shape complexity stops here. Consumer code (LLMNode,
discovery callsites) operates on `AdapterResponse`, not on
`litellm.ModelResponse`. This module owns:

- Building the LiteLLM `messages` list from system + prompt + attachments
- Translating reasoning kwargs from the provider-neutral shape produced by
  ``llm_reasoning_map`` into LiteLLM-native shapes (e.g. Anthropic's
  ``thinking={"type":"enabled","budget_tokens":N}``)
- Translating every LiteLLM exception we classify (deterministic:
  ``BadRequestError``, ``AuthenticationError``, ``NotFoundError``,
  ``PermissionDeniedError``; transient: ``Timeout``, ``RateLimitError``,
  ``InternalServerError``) into a typed ``LLMCallError`` subclass so
  consumers never import ``litellm.exceptions`` to discriminate
- Normalizing the response shape to a stable ``AdapterResponse``
- Reading ``response_cost`` from LiteLLM's ``_hidden_params`` so consumers
  get cost without a separate pricing computation (Phase 0 outcome A)

The adapter does NOT:
- Parse structured output JSON (consumer's job, see ``parse_structured_response``)
- Implement retries (caller's ``Node`` retry loop)
- Capture or propagate prompt-cache rendering (Phase B-G work)
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from pflow.core.exceptions import (
    InvalidRequestError,
    LLMCallError,
    LLMTransientError,
    MissingApiKeyError,
    UnknownModelError,
)
from pflow.core.llm_reasoning_map import DEFAULT_MAX_TOKENS_BASE, EFFORT_RATIOS

logger = logging.getLogger(__name__)


# `litellm` is lazy-imported inside complete() and _classify_litellm_error
# (the only two call sites that need it). Importing it costs ~700ms because
# LiteLLM eagerly loads handlers and Pydantic types for every provider it
# supports. Keeping the import inside the call sites means CLI invocations
# that never call the LLM (pflow validate, --dry-run, fully-cached runs,
# the future analyze-cache command) skip the cost entirely. The only path
# that pays it is an actual LLM call — and there the cost is amortized.
#
# Side effect: the first complete() call in a process pays ~700ms which
# lands inside the first LLM node's recorded duration. For multi-call
# workflows this affects 1 of N nodes; for single-call workflows the user
# sees one node ~700ms slower than the underlying API call. Cost predictions
# (token-based) and total wall-clock are unaffected.
#
# Tests patch `litellm.completion` (the litellm module path), not
# `pflow.core.llm_client.litellm.completion` — the latter would fail at
# decoration time because `litellm` is no longer a module attribute here.


# Public types ---------------------------------------------------------------


TraceHook = Callable[[dict], None]
"""Callable invoked at LLM call boundaries when a workflow trace is active.

The adapter calls it with two events:

* ``{"event": "before_call", "model": str, "prompt": str}`` — before the API call,
  with the rendered user prompt text. Replaces the prompt-capture half of
  the legacy ``runtime/workflow_trace.py`` monkey-patch.
* ``{"event": "after_call", "model": str, "response": AdapterResponse | None,
  "error": str | None}`` — after the call (success or error). Replaces the
  response-capture half of the legacy monkey-patch.

The hook MUST NOT raise. Exceptions are logged and swallowed so a tracing
bug cannot break user workflows.
"""


@dataclass
class Attachment:
    """An image attachment passed to the adapter.

    ``kind`` selects how the value is interpreted:

    * ``image_url`` — value is an http(s) URL passed verbatim to the provider.
    * ``image_path`` — value is a local filesystem path; the adapter
      base64-encodes it and builds a ``data:...;base64,...`` URL.
    """

    kind: Literal["image_url", "image_path"]
    value: str


@dataclass
class AdapterResponse:
    """Normalized successful LLM response. Stable contract for consumers.

    The adapter ALWAYS returns this on success, NEVER on error. Deterministic
    failures (bad params, unknown model, schema rejection) raise
    ``LLMCallError`` from ``pflow.core.exceptions``; transient failures
    (timeout, rate limit, 5xx) raise ``LLMTransientError`` so the caller's
    retry loop can decide. Other unwrapped exceptions (e.g. arbitrary
    network errors) propagate raw. Either way, an ``AdapterResponse`` is
    by construction a successful response.

    The ``usage`` dict keys are STABLE — do not rename without coordinated
    updates across LLMNode.post(), trace event capture, MCP, and analyze-cache
    output. Stable keys:

    * ``model``: str
    * ``input_tokens``, ``output_tokens``, ``total_tokens``: int
    * ``cache_creation_input_tokens``, ``cache_read_input_tokens``: int
    * ``cost_usd``: float | None  (None when LiteLLM doesn't price the model)

    The ``warnings`` list carries structured warnings the adapter detected
    during normalization (e.g. reasoning-model "tokens consumed but no
    visible text" trap). Each entry is a dict with at least ``kind`` and
    ``text``; ``LLMNode.post()`` lifts them into ``shared["__warnings__"]``
    for surfacing as JSON-output warnings + DEGRADED workflow status.
    """

    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    has_schema: bool = False
    warnings: list[dict[str, Any]] = field(default_factory=list)


# Public API -----------------------------------------------------------------


def complete(
    *,
    model: str,
    prompt: str,
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    attachments: list[Attachment] | None = None,
    schema: dict[str, Any] | None = None,
    reasoning_kwargs: dict[str, Any] | None = None,
    model_options: dict[str, Any] | None = None,
    timeout: float | None = None,
    trace_hook: TraceHook | None = None,
) -> AdapterResponse:
    """Execute an LLM call via LiteLLM and return a normalized response.

    On success, returns an ``AdapterResponse``. On deterministic errors,
    raises a typed ``LLMCallError`` subclass:

    - ``UnknownModelError`` for ``NotFoundError`` and bare-model-name
      ``BadRequestError`` (no provider prefix)
    - ``MissingApiKeyError`` for ``AuthenticationError`` and
      ``PermissionDeniedError``
    - ``InvalidRequestError`` for any other ``BadRequestError`` (schema
      mismatch, content policy, context-window overflow, ...)

    The caller should NOT retry these — they are the LiteLLM-era
    equivalent of the Pydantic ``ValidationError`` PATTERN EXCEPTION at
    the previous ``nodes/llm/llm.py:298-311``. LLMNode catches the typed
    subclasses at its ``_call_llm`` boundary so the Node retry loop
    doesn't burn three attempts on a permanent failure.

    Transient LiteLLM exceptions (timeout, rate limit, internal server)
    are wrapped in ``LLMTransientError`` so consumers can catch the
    ``LLMCallError`` umbrella. Other exceptions (for example, network
    errors outside LiteLLM's typed hierarchy) propagate unwrapped.
    LLMNode re-raises ``LLMTransientError`` so the Node retry loop can
    retry.

    Args:
        model: LiteLLM model identifier, e.g. ``"anthropic/claude-sonnet-4-5"``,
            ``"gpt-4o-mini"``, ``"gemini/gemini-2.5-flash"``.
        prompt: User-message text. Already template-resolved; no further
            substitution happens here.
        system: Optional system-message text.
        temperature: 0.0 to 2.0. NOTE: Anthropic models with thinking enabled
            require temperature=1.0 (LiteLLM/Anthropic enforces; the adapter
            does not pre-validate). Violation surfaces as ``LLMCallError``
            with Anthropic's actionable message and docs link preserved.
        max_tokens: Optional max output tokens.
        attachments: Optional list of ``Attachment`` (images). URL attachments
            pass through; ``image_path`` attachments are base64-encoded.
        schema: Optional JSON Schema dict for structured output. The adapter
            wraps it in LiteLLM's ``response_format={"type": "json_schema",
            "json_schema": {"name": "response", "schema": ..., "strict": True}}``
            envelope.
        reasoning_kwargs: Output of
            ``llm_reasoning_map.map_reasoning_options(...)``. The adapter
            translates Anthropic-specific shapes to LiteLLM-native form;
            other providers pass through.
        model_options: User-provided extra kwargs merged last (overrides
            adapter-built kwargs on key collision).
        timeout: Per-request timeout in seconds. None disables.
        trace_hook: Optional callable; see ``TraceHook`` docstring. Fires
            ``after_call`` with ``error`` set before any ``LLMCallError`` is
            raised, so traces capture the failure.

    Returns:
        AdapterResponse on success.

    Raises:
        UnknownModelError: model identifier not recognized.
        MissingApiKeyError: API key missing, wrong, or insufficient permission.
        InvalidRequestError: any other deterministic 4xx (catches via the
            ``LLMCallError`` base for consumers that don't discriminate).
    """
    messages = _build_messages(system=system, prompt=prompt, attachments=attachments)

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

    # Reasoning kwargs need provider-specific translation; see helper.
    translated_reasoning = _translate_reasoning_for_litellm(model, reasoning_kwargs or {})
    kwargs.update(translated_reasoning)

    # User-provided model_options merged last so they can override anything
    # the adapter built. Matches existing pflow LLMNode behavior.
    if model_options:
        kwargs.update(model_options)

    # Capture the request-side thinking budget so _normalize can include it
    # in the response usage dict. Lets MetricsCollector compute thinking
    # utilization (tokens used / budget) without needing the LLMNode to
    # mirror request kwargs into outputs.
    thinking_budget = _extract_thinking_budget(kwargs)

    _emit_trace(trace_hook, {"event": "before_call", "model": model, "prompt": prompt})

    # Lazy litellm import — see module docstring at top. First call pays
    # ~700ms; subsequent calls resolve from sys.modules instantly.
    # Setting suppress_debug_info every call is idempotent and cheaper
    # than gating on a flag.
    import litellm
    import litellm.exceptions

    litellm.suppress_debug_info = True

    try:
        raw_response = litellm.completion(**kwargs)
    except (
        # Deterministic errors (4xx that retrying cannot fix).
        litellm.exceptions.BadRequestError,
        litellm.exceptions.AuthenticationError,
        litellm.exceptions.NotFoundError,
        litellm.exceptions.PermissionDeniedError,
        # Transient errors (timeout, rate limit, 5xx). Wrapped in
        # LLMTransientError so the architectural seal stays intact:
        # consumers (LLMNode retry loop, smart_filter) catch the
        # LLMCallError umbrella without ever importing litellm.exceptions.
        litellm.exceptions.Timeout,
        litellm.exceptions.RateLimitError,
        litellm.exceptions.InternalServerError,
    ) as e:
        # _classify_litellm_error picks the right typed pflow subclass so
        # consumers can construct precise messages without importing
        # litellm.exceptions themselves. Deterministic subclasses are caught
        # by LLMNode at its _call_llm boundary (preventing the Node retry
        # loop from burning three attempts on a permanent failure);
        # LLMTransientError is re-raised by LLMNode so the retry loop fires.
        typed = _classify_litellm_error(e, model=model)
        _emit_trace(
            trace_hook,
            {"event": "after_call", "model": model, "error": str(typed)},
        )
        raise typed from e

    # Success path: normalize and emit after_call trace
    response = _normalize(
        raw_response,
        model=model,
        has_schema=schema is not None,
        thinking_budget=thinking_budget,
    )
    _emit_trace(trace_hook, {"event": "after_call", "model": model, "response": response})
    return response


# Internals ------------------------------------------------------------------


def _classify_litellm_error(exc: Exception, *, model: str) -> LLMCallError:
    """Translate a LiteLLM exception to a typed pflow subclass.

    The adapter is the single place where ``litellm.exceptions`` types are
    mapped to pflow types. Consumers receive ``UnknownModelError`` /
    ``MissingApiKeyError`` / ``InvalidRequestError`` / ``LLMTransientError``
    and never need to import ``litellm.exceptions`` to discriminate.

    Substring detection on the message text happens ONLY here at the seam
    (the "LLM Provider NOT provided" check). Past this boundary, consumers
    branch on structured attributes (``reason``, ``kind``) — never on text.
    """
    # Lazy import — only called from complete()'s except handler, so litellm
    # is already loaded by this point. The import resolves from sys.modules.
    import litellm.exceptions

    # Transient errors (timeout, rate limit, 5xx). Marker subclass; LLMNode's
    # _call_llm re-raises rather than catching, so the Node retry loop fires.
    if isinstance(
        exc,
        (
            litellm.exceptions.Timeout,
            litellm.exceptions.RateLimitError,
            litellm.exceptions.InternalServerError,
        ),
    ):
        return LLMTransientError(str(exc), model=model)

    # Deterministic errors
    if isinstance(exc, litellm.exceptions.NotFoundError):
        return UnknownModelError(f"Unknown model: {model}", model=model, reason="unknown_name")
    if isinstance(exc, litellm.exceptions.AuthenticationError):
        return MissingApiKeyError(
            f"API key required for model '{model}'",
            model=model,
            kind="missing_key",
        )
    if isinstance(exc, litellm.exceptions.PermissionDeniedError):
        return MissingApiKeyError(
            f"API key for model '{model}' lacks permission for this request",
            model=model,
            kind="lacks_permission",
        )
    # BadRequestError and its subclasses. The "LLM Provider NOT provided"
    # substring fires when a user passes a bare model name with no provider
    # prefix — distinct sub-case of UnknownModelError.
    if "LLM Provider NOT provided" in str(exc):
        return UnknownModelError(
            f"Model '{model}' has no provider prefix",
            model=model,
            reason="missing_prefix",
        )
    return InvalidRequestError(f"Invalid request for model '{model}': {exc}", model=model)


def _build_messages(
    *,
    system: str | None,
    prompt: str,
    attachments: list[Attachment] | None,
) -> list[dict[str, Any]]:
    """Assemble the LiteLLM ``messages`` list."""
    messages: list[dict[str, Any]] = []

    if system is not None:
        messages.append({"role": "system", "content": system})

    if attachments:
        # Build content blocks (image(s) + text). Order: images first, then
        # the prompt text. Mirrors what most providers expect.
        content_blocks: list[dict[str, Any]] = []
        for attachment in attachments:
            content_blocks.append(_attachment_to_content_block(attachment))
        content_blocks.append({"type": "text", "text": prompt})
        messages.append({"role": "user", "content": content_blocks})
    else:
        messages.append({"role": "user", "content": prompt})

    return messages


def _attachment_to_content_block(attachment: Attachment) -> dict[str, Any]:
    """Turn an Attachment into a LiteLLM image-content block."""
    if attachment.kind == "image_url":
        return {"type": "image_url", "image_url": {"url": attachment.value}}
    # image_path
    path = Path(attachment.value)
    data = base64.b64encode(path.read_bytes()).decode()
    mime, _ = mimetypes.guess_type(str(path))
    url = f"data:{mime or 'application/octet-stream'};base64,{data}"
    return {"type": "image_url", "image_url": {"url": url}}


def _translate_reasoning_for_litellm(model: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Translate provider-neutral reasoning kwargs to LiteLLM-native shape.

    The map output (``llm_reasoning_map.map_reasoning_options``) preserves
    the legacy llm-library kwarg shape (e.g. ``{"thinking": True,
    "thinking_budget": 1024}``). LiteLLM's standardized Anthropic interface
    expects ``{"thinking": {"type": "enabled", "budget_tokens": N}}``
    (verified by Phase 0 spike — see progress-log §27).

    Non-Anthropic providers (Gemini, OpenAI) pass through unchanged.
    """
    if not kwargs:
        return {}

    if not _is_anthropic(model):
        # Gemini and OpenAI accept their reasoning kwargs at the top level
        # via LiteLLM passthrough. ``thinking_budget`` for Gemini 2.5,
        # ``thinking_level`` for Gemini 3, ``reasoning_effort`` and
        # ``reasoning_max_tokens`` for OpenAI — all already in native shape.
        return dict(kwargs)

    # Anthropic-specific translation
    out: dict[str, Any] = {}
    leftover = dict(kwargs)

    thinking_effort = leftover.pop("thinking_effort", None)
    thinking_flag = leftover.pop("thinking", None)
    thinking_budget = leftover.pop("thinking_budget", None)

    if thinking_effort is not None:
        # Opus 4.5 path. LiteLLM's standardized ``thinking`` param uses
        # budget_tokens, not effort_level. Derive budget from effort using
        # the same EFFORT_RATIOS the budget-style models use, so
        # behavior is internally consistent across Anthropic models.
        ratio = EFFORT_RATIOS.get(thinking_effort, 0.5)
        budget = max(min(int(DEFAULT_MAX_TOKENS_BASE * ratio), 128000), 1024)
        out["thinking"] = {"type": "enabled", "budget_tokens": budget}
    elif thinking_flag is True and thinking_budget is not None:
        # Older Anthropic path (Sonnet 4.x, Opus 4.0/4.1)
        out["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
    elif thinking_flag is False:
        # Disable: omit thinking entirely (Anthropic default is no thinking).
        # The caller may have other reasoning kwargs we should keep; fall
        # through to merging leftover.
        pass
    elif thinking_budget is not None:
        # No thinking flag, but a budget was provided. Treat as enable
        # request (matches llm-anthropic plugin semantics).
        out["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

    # Merge any non-thinking kwargs (e.g. an exotic Anthropic-specific
    # option a user set via model_options that was routed through the map)
    out.update(leftover)
    return out


def _is_anthropic(model: str) -> bool:
    """Match the same provider-detection used by ``llm_reasoning_map``."""
    name = model.lower()
    return "anthropic/" in name or "claude-" in name or name.startswith("claude")


def _extract_thinking_budget(kwargs: dict[str, Any]) -> int:
    """Return the thinking-token budget set on the request, or 0 if none.

    Anthropic uses ``thinking={"type":"enabled","budget_tokens":N}``;
    Gemini 2.5 uses top-level ``thinking_budget=N``. OpenAI's
    ``reasoning_effort`` and Gemini 3's ``thinking_level`` are categorical
    levels with no token-level budget — we return 0 there so utilization
    metrics simply omit the section for those providers.
    """
    thinking = kwargs.get("thinking")
    if isinstance(thinking, dict):
        return _safe_int(thinking.get("budget_tokens"))
    return _safe_int(kwargs.get("thinking_budget"))


def _normalize(
    raw: Any,
    *,
    model: str,
    has_schema: bool,
    thinking_budget: int = 0,
) -> AdapterResponse:
    """Convert ``litellm.ModelResponse`` to ``AdapterResponse``.

    Normalizes the two different cache-token accounting paths LiteLLM uses
    across providers (per Phase 0 spike findings):

    * Anthropic populates ``usage.cache_creation_input_tokens`` and
      ``usage.cache_read_input_tokens`` directly.
    * Gemini and OpenAI populate ``usage.prompt_tokens_details.cached_tokens``
      (which we surface as ``cache_read_input_tokens``;
      ``cache_creation_input_tokens`` stays 0 — those providers don't
      distinguish creation from reads in the response).

    Reasoning-token surface: LiteLLM standardizes the per-call reasoning
    count to ``usage.completion_tokens_details.reasoning_tokens`` (Anthropic
    extended thinking, OpenAI o1/o3, Gemini 2.5/3). Surfaced as
    ``thinking_tokens``; paired with ``thinking_budget`` mirrored from the
    request kwargs so consumers can compute utilization.
    """
    msg = raw.choices[0].message
    text = msg.content or ""
    # Note: ``msg.reasoning_content`` carries thinking output (the reasoning
    # text itself) separately. We surface only the token COUNT here, not the
    # text — exposing the text is a future enhancement when a consumer needs it.

    usage_obj = raw.usage

    cache_creation = _safe_int(getattr(usage_obj, "cache_creation_input_tokens", None))
    cache_read = _safe_int(getattr(usage_obj, "cache_read_input_tokens", None))
    if cache_read == 0:
        # Gemini/OpenAI fallback: read from prompt_tokens_details.cached_tokens
        details = getattr(usage_obj, "prompt_tokens_details", None)
        if details is not None:
            cache_read = _safe_int(getattr(details, "cached_tokens", None))

    input_tokens = _safe_int(getattr(usage_obj, "prompt_tokens", None))
    output_tokens = _safe_int(getattr(usage_obj, "completion_tokens", None))

    # Reasoning tokens: LiteLLM-standardized field for thinking/reasoning
    # token count. Populated for any reasoning model regardless of provider.
    thinking_tokens = 0
    completion_details = getattr(usage_obj, "completion_tokens_details", None)
    if completion_details is not None:
        thinking_tokens = _safe_int(getattr(completion_details, "reasoning_tokens", None))

    finish_reason = getattr(raw.choices[0], "finish_reason", None)
    warnings_list = _detect_empty_response_warnings(
        text=text,
        model=model,
        output_tokens=output_tokens,
        thinking_tokens=thinking_tokens,
        thinking_budget=thinking_budget,
        finish_reason=finish_reason,
    )

    # LiteLLM populates response_cost on _hidden_params. None when LiteLLM
    # doesn't have pricing for the model — consumers tolerate None already.
    cost_usd: float | None = None
    hidden = getattr(raw, "_hidden_params", None)
    if isinstance(hidden, dict):
        raw_cost = hidden.get("response_cost")
        if isinstance(raw_cost, (int, float)):
            cost_usd = float(raw_cost)

    usage: dict[str, Any] = {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "thinking_tokens": thinking_tokens,
        "thinking_budget": thinking_budget,
        "cost_usd": cost_usd,
    }

    return AdapterResponse(
        text=text,
        usage=usage,
        model=model,
        has_schema=has_schema,
        warnings=warnings_list,
    )


def _detect_empty_response_warnings(
    *,
    text: str,
    model: str,
    output_tokens: int,
    thinking_tokens: int,
    thinking_budget: int,
    finish_reason: str | None,
) -> list[dict[str, Any]]:
    """Build structured warnings for empty-content responses.

    Returns one warning dict per finish_reason case. Each entry has ``kind``
    (machine-parseable discriminator), ``text`` (human-readable remediation),
    and ``context`` (structured fields). LLMNode.post() lifts these into
    ``shared["__warnings__"]`` so JSON consumers see them and the workflow
    status shifts to DEGRADED.

    ``finish_reason="tool_calls"`` is intentionally silent — that's an
    expected LiteLLM shape when the model wanted tools instead of text.
    """
    if text or output_tokens <= 0:
        return []

    if finish_reason in ("length", "max_tokens"):
        is_reasoning_model = thinking_budget > 0 or thinking_tokens > 0
        if is_reasoning_model:
            return [
                {
                    "kind": "llm_empty_response_reasoning",
                    "text": (
                        f"Empty response from {model}: {output_tokens} tokens consumed, "
                        f"finish_reason={finish_reason}. The budget was spent on internal "
                        f"thinking before any visible output could be emitted. "
                        f"Increase max_tokens, or lower reasoning_effort to leave budget for output."
                    ),
                    "context": {
                        "model": model,
                        "finish_reason": finish_reason,
                        "output_tokens": output_tokens,
                        "thinking_budget": thinking_budget,
                        "thinking_tokens": thinking_tokens,
                    },
                }
            ]
        return [
            {
                "kind": "llm_empty_response_max_tokens",
                "text": (
                    f"Empty response from {model}: {output_tokens} tokens consumed, "
                    f"finish_reason={finish_reason}. Increase max_tokens to allow visible output."
                ),
                "context": {
                    "model": model,
                    "finish_reason": finish_reason,
                    "output_tokens": output_tokens,
                },
            }
        ]
    if finish_reason == "content_filter":
        return [
            {
                "kind": "llm_empty_response_content_filter",
                "text": (
                    f"Empty response from {model}: provider blocked the response "
                    f"(finish_reason=content_filter). Adjust prompt to avoid the trigger."
                ),
                "context": {"model": model, "finish_reason": finish_reason},
            }
        ]
    if finish_reason == "stop":
        return [
            {
                "kind": "llm_empty_response_stop",
                "text": (
                    f"Empty response from {model}: model returned no content "
                    f"(finish_reason=stop). Check the prompt — the model chose to stop without output."
                ),
                "context": {"model": model, "finish_reason": finish_reason},
            }
        ]
    if finish_reason is None:
        return [
            {
                "kind": "llm_empty_response_unknown",
                "text": (
                    f"Empty response from {model}: provider did not report a finish_reason "
                    f"and no content was returned. Investigate the response shape."
                ),
                "context": {"model": model, "finish_reason": None},
            }
        ]
    # finish_reason="tool_calls" or any other future case: silent.
    return []


def _safe_int(value: int | float | None) -> int:
    """Coerce token counts to int; treat None / missing as 0."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _emit_trace(hook: TraceHook | None, event: dict[str, Any]) -> None:
    """Invoke a trace hook, swallowing any exception.

    Tracing must never break user workflows. Exceptions are logged at
    DEBUG level and discarded.
    """
    if hook is None:
        return
    try:
        hook(event)
    except Exception as exc:
        logger.debug("trace_hook raised %s: %s", type(exc).__name__, exc)
