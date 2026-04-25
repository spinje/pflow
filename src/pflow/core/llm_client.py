"""pflow-owned LiteLLM adapter — single seam for all LLM calls.

All LiteLLM API-shape complexity stops here. Consumer code (LLMNode,
discovery callsites) operates on `AdapterResponse`, not on
`litellm.ModelResponse`. This module owns:

- Building the LiteLLM `messages` list from system + prompt + attachments
- Translating reasoning kwargs from the provider-neutral shape produced by
  ``llm_reasoning_map`` into LiteLLM-native shapes (e.g. Anthropic's
  ``thinking={"type":"enabled","budget_tokens":N}``)
- Raising ``LLMCallError`` on deterministic ``BadRequestError`` (preserves
  the PATTERN EXCEPTION pattern that was previously in
  ``nodes/llm/llm.py:298-311`` for Pydantic ``ValidationError``)
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

import litellm
import litellm.exceptions

from pflow.core.exceptions import LLMCallError
from pflow.core.llm_reasoning_map import DEFAULT_MAX_TOKENS_BASE, EFFORT_RATIOS

logger = logging.getLogger(__name__)


# Belt-and-suspenders: LiteLLM 1.82.6 is quiet by default, but this guards
# against future verbosity regressions and ensures clean test output.
litellm.suppress_debug_info = True


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
    ``LLMCallError`` from ``pflow.core.exceptions``; non-deterministic
    failures (timeout, auth, network) propagate the underlying LiteLLM
    exception. Either way, an ``AdapterResponse`` is by construction a
    successful response.

    The ``usage`` dict keys are STABLE — do not rename without coordinated
    updates across LLMNode.post(), trace event capture, MCP, and analyze-cache
    output. Stable keys:

    * ``model``: str
    * ``input_tokens``, ``output_tokens``, ``total_tokens``: int
    * ``cache_creation_input_tokens``, ``cache_read_input_tokens``: int
    * ``cost_usd``: float | None  (None when LiteLLM doesn't price the model)
    """

    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    has_schema: bool = False


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

    On success, returns an ``AdapterResponse``. On deterministic errors
    (bad params, bad model, schema rejection, content policy — anything
    LiteLLM raises as ``BadRequestError`` or a subclass), raises
    ``LLMCallError``. The caller should NOT retry — these are the
    LiteLLM-era equivalent of the Pydantic ``ValidationError`` PATTERN
    EXCEPTION at the previous ``nodes/llm/llm.py:298-311``. LLMNode catches
    ``LLMCallError`` at its ``_call_llm`` boundary so the Node retry loop
    doesn't burn three attempts on a permanent failure.

    Other exceptions (timeout, auth, network, rate limit, internal server
    error) propagate unwrapped. The caller's retry loop decides.

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
        LLMCallError: deterministic provider error (4xx that retrying won't fix).
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

    _emit_trace(trace_hook, {"event": "before_call", "model": model, "prompt": prompt})

    try:
        raw_response = litellm.completion(**kwargs)
    except litellm.exceptions.BadRequestError as e:
        # PATTERN EXCEPTION: deterministic server-side rejection. Retrying
        # the same bad request will produce the same error, so we raise a
        # typed pflow exception that LLMNode catches at its _call_llm
        # boundary (preventing the Node retry loop from burning three
        # attempts). Mirrors the behavior at the previous
        # nodes/llm/llm.py:298-311 (which caught Pydantic ValidationError
        # under the llm-library path) but at a single, typed seam.
        err_msg = f"Invalid request for model '{model}': {e}"
        _emit_trace(
            trace_hook,
            {"event": "after_call", "model": model, "error": err_msg},
        )
        raise LLMCallError(err_msg) from e

    # Success path: normalize and emit after_call trace
    response = _normalize(raw_response, model=model, has_schema=schema is not None)
    _emit_trace(trace_hook, {"event": "after_call", "model": model, "response": response})
    return response


# Internals ------------------------------------------------------------------


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


def _normalize(
    raw: Any,
    *,
    model: str,
    has_schema: bool,
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
    """
    msg = raw.choices[0].message
    text = msg.content or ""
    # Note: ``msg.reasoning_content`` carries thinking output separately when
    # reasoning is enabled. We do not surface it in AdapterResponse (matches
    # legacy LLMNode behavior); a future enhancement could expose it.

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

    # Detect the reasoning-model trap: tokens consumed but no visible text.
    # Phase 0 surfaced this on gemini-3-flash-preview with max_tokens=16 —
    # the entire budget went to internal thinking, leaving content=None.
    # Without this warning the workflow surfaces an empty result with no clue.
    if not text and output_tokens > 0:
        finish_reason = getattr(raw.choices[0], "finish_reason", None)
        if finish_reason in ("length", "max_tokens"):
            logger.warning(
                "Empty response from %s: %d tokens consumed, finish_reason=%s. "
                "Likely cause: max_tokens too low for a reasoning model — the "
                "budget was spent on internal thinking before any visible "
                "output could be emitted. Try increasing max_tokens.",
                model,
                output_tokens,
                finish_reason,
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
        "cost_usd": cost_usd,
    }

    return AdapterResponse(
        text=text,
        usage=usage,
        model=model,
        has_schema=has_schema,
    )


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


def enrich_llm_usage_with_cost(llm_usage: dict[str, Any]) -> None:
    """Ensure ``llm_usage`` has a ``cost_usd`` key (may be ``None``).

    Cost determination is LiteLLM's responsibility — the adapter populates
    ``cost_usd`` from ``response._hidden_params['response_cost']`` when
    LiteLLM has pricing data for the model, and leaves it absent (or sets
    it to ``None``) when LiteLLM doesn't know the model.

    This wrapper exists for two cases the adapter doesn't cover:

    1. ClaudeCodeNode produces ``total_cost_usd`` (from the SDK) instead of
       ``cost_usd``; mirror it into ``cost_usd`` so downstream consumers
       have a single key to read.
    2. Defensive programming: any ``llm_usage`` dict that reaches the
       runtime without ``cost_usd`` set (e.g. older cached entries, custom
       node implementations) gets ``None`` so consumers can rely on the
       key being present.

    Modifies ``llm_usage`` in place.
    """
    if "cost_usd" in llm_usage:
        return
    total_cost = llm_usage.get("total_cost_usd")
    if total_cost is not None:
        llm_usage["cost_usd"] = total_cost
        return
    llm_usage["cost_usd"] = None
