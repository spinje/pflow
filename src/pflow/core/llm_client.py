"""pflow-owned LiteLLM adapter — single seam for all LLM calls.

All LiteLLM API-shape complexity stops here. Consumer code (LLMNode,
discovery callsites) operates on ``AdapterResponse``, not on
``litellm.ModelResponse``. This module owns:

- Building the LiteLLM ``messages`` list from system + prompt + attachments
- Translating reasoning kwargs from the provider-neutral shape produced by
  ``llm_reasoning_map`` into LiteLLM-native shapes (e.g. Anthropic's
  ``thinking={"type":"enabled","budget_tokens":N}``)
- Translating every LiteLLM exception into a typed ``LLMCallError`` subclass
  so consumers never import ``litellm.exceptions`` to discriminate. The
  catch is structural: ``openai.OpenAIError`` is the actual base of every
  HTTP-level / connection / rate-limit / auth / model exception LiteLLM
  raises (LiteLLM's exception classes inherit from the OpenAI SDK base
  rather than from ``litellm.exceptions.OpenAIError``, which is a sibling
  class — confirmed by introspection on litellm 1.82.6). A single catch
  on ``openai.OpenAIError`` covers all current and future subclasses.
  (LiteLLM's proxy/guardrail-only errors — ``BlockedPiiEntityError``,
  ``BudgetExceededError``, ``Guardrail*`` — inherit from plain
  ``Exception`` and are unreachable in pflow because we don't enable
  proxy or guardrail mode.) The ``openai`` package is guaranteed installed
  whenever ``litellm`` is — it's a transitive runtime dependency LiteLLM
  declares.
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
    LLMResponseParseError,
    LLMTransientError,
    MissingApiKeyError,
    MissingSdkError,
    UnknownModelError,
)
from pflow.core.llm_providers import detect_provider, normalize_model_name
from pflow.core.llm_reasoning_map import DEFAULT_MAX_TOKENS_BASE, EFFORT_RATIOS

logger = logging.getLogger(__name__)

_REASONING_MODEL_OPTION_KEYS = frozenset({
    "thinking",
    "thinking_budget",
    "thinking_effort",
    "reasoning_effort",
    "reasoning_max_tokens",
    "thinking_level",
})


def _normalize_model_name(model: str) -> str:
    """Add a provider prefix to bare model names when the provider is unambiguous."""
    normalized = normalize_model_name(model)
    if normalized != model:
        logger.debug("Normalized bare model name %r to %r", model, normalized)
    return normalized


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

    - ``UnknownModelError`` for ``NotFoundError``, ``LiteLLMUnknownProvider``,
      and bare-model-name ``BadRequestError`` (no provider prefix)
    - ``MissingApiKeyError`` for ``AuthenticationError`` and
      ``PermissionDeniedError``
    - ``LLMResponseParseError`` for ``APIResponseValidationError`` and its
      subclasses (e.g. ``JSONSchemaValidationError``)
    - ``InvalidRequestError`` for any other ``BadRequestError`` and any
      unrecognized ``OpenAIError`` subclass (schema mismatch, content
      policy, context-window overflow, ...)

    The caller should NOT retry these — they are the LiteLLM-era
    equivalent of the Pydantic ``ValidationError`` PATTERN EXCEPTION at
    the previous ``nodes/llm/llm.py:298-311``. LLMNode catches the typed
    subclasses at its ``_call_llm`` boundary so the Node retry loop
    doesn't burn three attempts on a permanent failure.

    Transient LiteLLM exceptions (timeout, rate limit, connection error,
    5xx) are wrapped in ``LLMTransientError`` so consumers can catch the
    ``LLMCallError`` umbrella. The catch is over ``openai.OpenAIError``
    (the OpenAI SDK base), so every HTTP-level / connection / rate-limit
    / auth / model error LiteLLM raises is wrapped — there is no
    "unknown LiteLLM exception" leakage past the seam. LLMNode re-raises
    ``LLMTransientError`` so the Node retry loop can retry.

    Args:
        model: LiteLLM model identifier with provider prefix, e.g.
            ``"anthropic/claude-sonnet-4-5"``, ``"openai/gpt-4o-mini"``,
            ``"gemini/gemini-2.5-flash"``. Bare names (no prefix) route
            inconsistently across providers; prefer explicit prefixes.
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
        model_options: User-provided extra kwargs merged last. Reasoning
            keys are rejected here because pflow has dedicated
            ``reasoning_effort`` / ``reasoning_max_tokens`` channels; letting
            raw model options bypass that path silently drops provider-specific
            validation and translation.
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
    model = _normalize_model_name(model)
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

    if model_options:
        _validate_model_options(model, model_options)
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
    #
    # ``openai`` is litellm's own transitive runtime dep — guaranteed to
    # be in sys.modules by the time litellm is imported. We import its
    # exception base directly because litellm's exception classes inherit
    # from it (NOT from ``litellm.exceptions.OpenAIError`` — that is a
    # separate sibling class). See module docstring.
    import litellm
    import openai

    litellm.suppress_debug_info = True
    # LiteLLM's ERROR logger writes tracebacks to stderr (e.g. Vertex
    # credential failures) before the exception reaches our handler.
    # The adapter's typed exception system is the single error surface;
    # redundant logs just produce noise. CRITICAL lets truly fatal
    # messages through while suppressing the redundant ERROR tracebacks.
    logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)

    try:
        raw_response = litellm.completion(**kwargs)
    except openai.OpenAIError as e:
        # OpenAIError is the LiteLLM/OpenAI SDK base class. Catching it
        # covers every HTTP-level, connection, rate-limit, auth, and model
        # error LiteLLM raises in the call path pflow uses — both the
        # known subclasses and any future additions. The architectural
        # seal stays intact: consumers (LLMNode retry loop, smart_filter,
        # discovery callers) catch the LLMCallError umbrella without ever
        # importing litellm.exceptions.
        #
        # _classify_litellm_error picks the right typed pflow subclass.
        # Deterministic subclasses are caught by LLMNode at its _call_llm
        # boundary (preventing the Node retry loop from burning three
        # attempts on a permanent failure); LLMTransientError is re-raised
        # by LLMNode so the retry loop fires.
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
    ``MissingApiKeyError`` / ``LLMResponseParseError`` /
    ``InvalidRequestError`` / ``LLMTransientError`` and never need to
    import ``litellm.exceptions`` to discriminate.

    Substring detection on the message text happens ONLY here at the seam
    (the "LLM Provider NOT provided" fallback for older LiteLLM versions
    that don't raise the typed ``LiteLLMUnknownProvider``). Past this
    boundary, consumers branch on structured attributes (``reason``,
    ``kind``) — never on text.

    Two class hierarchies to know about:

    * Most LiteLLM exceptions are *thin wrappers* whose first base is the
      OpenAI SDK class with the same name (e.g.
      ``litellm.exceptions.BadRequestError`` IS-A ``openai.BadRequestError``).
      For these, ``isinstance(exc, openai.X)`` matches both LiteLLM-wrapped
      and raw OpenAI instances, which makes the dispatch immune to LiteLLM
      one day raising a sibling class instead.
    * A few LiteLLM-only classes don't have an OpenAI-side mirror at all:
      ``ServiceUnavailableError``, ``BadGatewayError``,
      ``LiteLLMUnknownProvider``. They inherit from ``openai.APIStatusError``
      / ``openai.BadRequestError`` (so the outer ``openai.OpenAIError``
      catch in ``complete()`` still wraps them), but the matching dispatch
      branch must reference them via ``litellm.exceptions``.

    Dispatch order matters for correctness:

    1. **Auth** (``AuthenticationError``, ``PermissionDeniedError``) —
       most specific; check before other status-code-based classifications.
    2. **Model name issues** — ``LiteLLMUnknownProvider`` IS-A
       ``BadRequestError``, so it must be checked before the generic
       ``BadRequestError`` branch. Same for the substring fallback for
       older LiteLLM versions that don't raise the typed class.
       ``NotFoundError`` is the typical "model name unrecognized" case.
    3. **Transient** — ``APIConnectionError`` (which covers ``Timeout``
       via inheritance — ``Timeout`` IS-A ``openai.APITimeoutError`` IS-A
       ``openai.APIConnectionError``), ``RateLimitError``,
       ``InternalServerError``, plus the LiteLLM-only
       ``ServiceUnavailableError`` and ``BadGatewayError``.
    4. **Response validation** — ``APIResponseValidationError`` and its
       subclasses (``JSONSchemaValidationError``) are LiteLLM-side
       complaints about provider responses; semantically these are
       "model returned something unparseable" rather than "request was
       bad", so they map to ``LLMResponseParseError``.
    5. **Bad request** — generic ``BadRequestError`` covers schema
       violations, content-policy rejections, context-window overflow,
       etc. ``ContextWindowExceededError``, ``ContentPolicyViolationError``,
       ``UnsupportedParamsError``, ``ImageFetchError``,
       ``RejectedRequestError`` all flow through here.
    6. **Default** — any unrecognized ``OpenAIError`` subclass is treated
       as deterministic ``InvalidRequestError`` so we fail-fast rather
       than infinite-retry an unknown server condition. Future transient
       subclasses can be added explicitly to the transient branch above.
    """
    # Lazy imports — only called from complete()'s except handler, so both
    # modules are already in sys.modules by the time we reach here.
    import litellm.exceptions as le
    import openai

    # Capture the raw provider/LiteLLM exception text once so every typed
    # subclass below carries it as ``provider_message``. This is the WHY
    # (provider's own diagnosis: "Quota exceeded", "Region not allowed",
    # "Model retired") that pflow's wrapped message would otherwise discard.
    # Diagnostic.message stays as the pflow-wrapped framing (the WHAT);
    # provider_message exposes the raw detail for agents that need to
    # discriminate sub-cases beyond the typed kind/reason.
    raw = str(exc)

    # 1. Auth (specific status-code classes; check before other 4xx).
    if isinstance(exc, openai.AuthenticationError):
        return MissingApiKeyError(
            f"API key required for model '{model}'",
            model=model,
            kind="missing_key",
            provider_message=raw,
        )
    if isinstance(exc, openai.PermissionDeniedError):
        return MissingApiKeyError(
            f"API key for model '{model}' lacks permission for this request",
            model=model,
            kind="lacks_permission",
            provider_message=raw,
        )

    # 2. Model name issues (must check before the generic BadRequestError
    # branch — LiteLLMUnknownProvider IS-A BadRequestError).
    if isinstance(exc, le.LiteLLMUnknownProvider) or "LLM Provider NOT provided" in raw:
        return UnknownModelError(
            f"Model '{model}' has no provider prefix",
            model=model,
            reason="missing_prefix",
            provider_message=raw,
        )
    if isinstance(exc, openai.NotFoundError):
        return UnknownModelError(
            f"Unknown model: {model}",
            model=model,
            reason="unknown_name",
            provider_message=raw,
        )

    # 3. Transient (network, rate-limit, 5xx). LLMTransientError carries a
    # kind discriminator; LLMNode's _call_llm re-raises rather than catching,
    # so the Node retry loop fires.
    # APIConnectionError covers Timeout (Timeout IS-A APITimeoutError IS-A
    # APIConnectionError). ServiceUnavailableError / BadGatewayError have
    # no openai-side mirror — referenced via litellm.exceptions.
    #
    # Exception: APIConnectionError caused by a missing SDK install (e.g.
    # "Google Cloud SDK not found. Install it with: pip install ...") is
    # permanent — retrying won't install the package. Detect via the
    # exception chain: ImportError in __cause__ is the reliable signal.
    if isinstance(
        exc,
        (
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.InternalServerError,
            le.ServiceUnavailableError,
            le.BadGatewayError,
        ),
    ):
        if isinstance(exc, openai.APIConnectionError) and _has_import_error_cause(exc):
            return MissingSdkError(
                raw,
                model=model,
                package=_extract_missing_package(exc),
                provider_message=raw,
            )
        return LLMTransientError(
            raw,
            model=model,
            kind=_classify_transient_kind(exc),
            provider_message=raw,
        )

    # 4. Response validation — LiteLLM rejected the provider's response
    # shape (e.g. ``JSONSchemaValidationError`` against an output schema).
    # Semantically a parse failure, not a bad request.
    if isinstance(exc, openai.APIResponseValidationError):
        return LLMResponseParseError(
            f"Provider response failed validation for model '{model}': {exc}",
            model=model,
            provider_message=raw,
        )

    # 5. Bad request (covers schema, content policy, context window,
    # unsupported params, image fetch, rejected request).
    if isinstance(exc, openai.BadRequestError):
        return InvalidRequestError(
            f"Invalid request for model '{model}': {exc}",
            model=model,
            provider_message=raw,
        )

    # 6. Default: unrecognized OpenAIError subclass. Treat as deterministic
    # so we don't infinite-retry an unknown server condition. Add explicit
    # branches above as new subclasses surface in real workloads.
    return InvalidRequestError(
        f"Unrecognized LiteLLM error for model '{model}' ({type(exc).__name__}): {exc}",
        model=model,
        provider_message=raw,
    )


def _has_import_error_cause(exc: BaseException) -> bool:
    """Detect a missing SDK install in the exception chain.

    LiteLLM wraps provider errors without ``raise from``, so the
    ``ImportError`` lands on ``__context__`` (implicit chaining), not
    ``__cause__`` (explicit). We walk both chains.
    """
    for attr in ("__cause__", "__context__"):
        current = getattr(exc, attr, None)
        while current is not None:
            if isinstance(current, (ImportError, ModuleNotFoundError)):
                return True
            current = getattr(current, attr, None)
    return False


def _extract_missing_package(exc: BaseException) -> str | None:
    """Extract the package name from LiteLLM's 'pip install <pkg>' hint."""
    import re

    match = re.search(r"pip install ['\"]?([^'\";\s]+)['\"]?", str(exc))
    return match.group(1) if match else None


def _classify_transient_kind(exc: Exception) -> str:
    """Return a stable discriminator for retryable LiteLLM failures."""
    import litellm.exceptions as le
    import openai

    if isinstance(exc, le.Timeout):
        return "timeout"
    if isinstance(exc, openai.RateLimitError):
        return "rate_limit"
    if isinstance(exc, (openai.InternalServerError, le.ServiceUnavailableError, le.BadGatewayError)):
        return "server_error"
    return "connection"


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


def _validate_model_options(model: str, model_options: dict[str, Any]) -> None:
    """Reject reasoning kwargs from the raw provider-options escape hatch."""
    reasoning_keys = sorted(set(model_options).intersection(_REASONING_MODEL_OPTION_KEYS))
    if not reasoning_keys:
        return

    joined = ", ".join(reasoning_keys)
    raise InvalidRequestError(
        f"Invalid model_options for model '{model}': reasoning option keys "
        f"({joined}) must use pflow's dedicated reasoning_effort or "
        f"reasoning_max_tokens parameters instead of model_options.",
        model=model,
    )


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
    elif thinking_flag is True:
        raise InvalidRequestError(
            f"Invalid reasoning options for model '{model}': thinking=True requires "
            "thinking_budget or thinking_effort. Use reasoning_effort or "
            "reasoning_max_tokens on the LLM node instead of raw model_options.",
            model=model,
        )
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
    provider = detect_provider(model)
    return provider is not None and provider.name == "anthropic"


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

    Gate is intentionally simple:

    * If the model produced visible text → no warning (success).
    * If ``finish_reason == "tool_calls"`` → no warning (expected LiteLLM
      shape when the model wanted tools instead of text).
    * Every other empty-text case is an anomaly worth surfacing — including
      cases with ``output_tokens == 0``. Provider refusals (``content_filter``)
      and unexpected stops can fire at zero token counts; gating those out
      silently would drop the very signal the warning system exists for.

    Returns one warning dict per finish_reason case. Each entry has
    ``kind`` (machine-parseable discriminator), ``text`` (human-readable
    remediation), and ``context`` (structured fields). LLMNode.post()
    lifts these into ``shared["__warnings__"]`` so JSON consumers see
    them and the workflow status shifts to DEGRADED.
    """
    if text or finish_reason == "tool_calls":
        return []

    if finish_reason in ("length", "max_tokens"):
        is_reasoning_model = thinking_budget > 0 or thinking_tokens > 0
        if is_reasoning_model:
            return [
                {
                    "kind": "llm_empty_response_reasoning",
                    "text": (
                        f"Empty response from {model} (finish_reason={finish_reason}, "
                        f"{output_tokens} tokens consumed). The budget was spent on internal "
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
                    f"Empty response from {model} (finish_reason={finish_reason}, "
                    f"{output_tokens} tokens consumed). Increase max_tokens to allow visible output."
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
    return [
        {
            "kind": "llm_empty_response_unrecognized_finish_reason",
            "text": (
                f"Empty response from {model}: provider returned an unrecognized "
                f"finish_reason={finish_reason!r} with no content. Investigate the response shape."
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

    Tracing must never break user workflows. Exceptions are logged and
    discarded.
    """
    if hook is None:
        return
    try:
        hook(event)
    except Exception as exc:
        logger.warning("trace_hook raised %s: %s", type(exc).__name__, exc)
