"""Custom exceptions for pflow."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from pflow.core.cache_ttl import build_unsupported_cache_ttl_diagnostic, unsupported_cache_ttl_message
from pflow.core.diagnostic import LLM_FAILURE_CATEGORY, LLM_VALIDATION_CATEGORY, Diagnostic, Severity
from pflow.core.gate import GATE_KIND_APPROVAL, GateRequest
from pflow.core.llm_providers import detect_provider, extract_provider_prefix

# Typed discriminators for LLMCallError subclasses. Carried as Literal so
# typos at construction sites (e.g. ``kind="rate_limt"``) fail mypy at the
# raise site rather than silently falling through to a default branch.
UnknownModelReason = Literal["unknown_name", "missing_prefix"]
MissingApiKeyKind = Literal["missing_key", "lacks_permission"]
LLMTransientKind = Literal["timeout", "rate_limit", "server_error", "connection"]
LLMResponseParseKind = Literal["invalid_json", "schema_mismatch"]

# Canonical list of dynamic attributes the engine/runner attach to exceptions
# for cross-boundary context threading.  Used by copy_pflow_annotations() and
# as the single source of truth for what survives the propagation chain.
_PFLOW_EXCEPTION_ANNOTATIONS = (
    "_pflow_node_id",
    "_pflow_shared_store",
    "_pflow_parser_diagnostics",
    "_pflow_template_diagnostic",
    "_pflow_partial_resolutions",
)


def copy_pflow_annotations(source: BaseException, target: BaseException) -> None:
    """Copy _pflow_* attributes from source to target exception.

    Use when wrapping an annotated exception: the engine/runner attach
    diagnostic context via these attributes, and ``raise X from e``
    creates a new object that loses them.
    """
    for attr in _PFLOW_EXCEPTION_ANNOTATIONS:
        val = getattr(source, attr, None)
        if val is not None:
            setattr(target, attr, val)


class PflowError(Exception):
    """Base exception for all pflow errors."""

    retriable: bool = True

    def to_diagnostics(self) -> list[Diagnostic]:
        """Convert to diagnostic representation. Override in subclasses for rich output."""
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Error",
                source="runtime",
                context={
                    "category": "execution_failure",
                    "exception_type": type(self).__name__,
                },
            )
        ]


class WorkflowExistsError(PflowError):
    """Raised when attempting to save a workflow that already exists."""

    pass


class WorkflowNotFoundError(PflowError):
    """Raised when a workflow cannot be found or has an unsupported format."""

    def __init__(
        self,
        workflow_name: str,
        similar_names: list[str] | None = None,
        hint: str | None = None,
    ):
        self.workflow_name = workflow_name
        self.similar_names = similar_names or []
        self.hint = hint
        super().__init__(hint or f"Workflow '{workflow_name}' not found")

    def to_diagnostics(self) -> list[Diagnostic]:
        # When hint provides specific guidance (e.g., "convert .json to .pflow.md"),
        # don't dilute it with generic "list workflows" suggestion.
        suggestions = None if self.hint else ["Use 'pflow list' to see all available workflows."]
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Workflow Not Found",
                suggestions=suggestions,
                source="runtime",
                context={
                    "category": "not_found",
                    "workflow_name": self.workflow_name,
                    "similar_names": self.similar_names,
                    "hint": self.hint,
                },
            )
        ]


class WorkflowValidationError(PflowError):
    """Raised when workflow validation fails.

    Carries both the blocking errors (``validation_errors``) and any
    warnings produced during the same validation pass (``validation_warnings``).
    The warnings are legitimate diagnostics that the user should still see
    alongside the errors — they're captured at raise time so downstream
    exception-to-result conversion can surface them without needing access
    to the original shared store.
    """

    def __init__(
        self,
        summary: str = "Workflow validation failed",
        validation_errors: list[Diagnostic] | None = None,
        validation_warnings: list[Diagnostic] | None = None,
    ):
        self.summary = summary
        self.validation_errors = validation_errors or []
        self.validation_warnings = validation_warnings or []
        super().__init__(summary)

    def to_diagnostics(self) -> list[Diagnostic]:
        return self.validation_errors or [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.summary,
                title="Validation Error",
                source="validation",
                context={"category": "validation"},
            )
        ]


class UnsupportedCacheTTLError(PflowError):
    """Raised when a resolved LLM provider cannot honor the workflow cache TTL."""

    def __init__(self, *, node_id: str, provider_name: str | None, ttl: str | None, model: str | None = None) -> None:
        self.node_id = node_id
        self.provider_name = provider_name
        self.ttl = ttl
        self.model = model
        super().__init__(unsupported_cache_ttl_message(node_id=node_id, provider_name=provider_name, ttl=ttl))

    def to_diagnostics(self) -> list[Diagnostic]:
        return [
            build_unsupported_cache_ttl_diagnostic(
                node_id=self.node_id,
                provider_name=self.provider_name,
                ttl=self.ttl,
                model=self.model,
            )
        ]


class ReportGenerationError(PflowError):
    """Raised when pflow cannot safely generate a report directory."""

    def __init__(
        self,
        message: str,
        *,
        report_path: str | None = None,
        suggestions: list[str] | None = None,
        reason: str | None = None,
    ) -> None:
        self.report_path = report_path
        self.suggestions = suggestions or []
        self.reason = reason
        super().__init__(message)

    def to_diagnostics(self) -> list[Diagnostic]:
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Report Generation Failed",
                suggestions=self.suggestions or None,
                source="report",
                context={
                    "category": "report_generation",
                    "report_path": self.report_path,
                    "reason": self.reason,
                },
            )
        ]


class NodeError(PflowError):
    """A step failed in a way its author can act on — what node code raises.

    Pass ``param`` when a step param is missing or invalid: the fix is in the
    workflow file, so the diagnostic is a validation error naming that param.
    Omit it for a runtime failure the node translated for the author (a refused
    connection, a timed-out agent): an execution failure. Put the fix in the
    message — batch item errors and sub-workflow failures carry only ``str(exc)``.

    Keeps ``retriable = True`` for the batch reason ``AgentValidationError``
    documents: a non-retriable error aborts a whole batch, even under
    ``error_handling: continue``. The ratchet keeping vanilla exceptions out of
    node code is ``tests/test_nodes/test_node_exception_types.py``.
    """

    def __init__(self, message: str, *, param: str | None = None) -> None:
        self.param = param
        super().__init__(message)

    def to_diagnostics(self) -> list[Diagnostic]:
        if self.param is None:
            title, context = "Execution Failed", {"category": "execution_failure"}
        else:
            title, context = "Validation Error", {"category": "validation", "param": self.param}
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title=title,
                source="runtime",
                context=context,
            )
        ]


class LLMCallError(PflowError):
    """Raised by the LLM adapter for provider errors.

    The adapter (``pflow.core.llm_client``) is the SINGLE place where
    ``litellm.exceptions`` types are translated to typed pflow exceptions.
    All consumers operate on these typed subclasses without importing
    ``litellm.exceptions`` themselves.

    **Deterministic subclasses** (4xx that retrying cannot fix):

    - ``UnknownModelError``: model identifier not recognized
      (``NotFoundError`` or ``BadRequestError`` with the
      "LLM Provider NOT provided" substring).
    - ``MissingApiKeyError``: API key missing or rejected
      (``AuthenticationError``, ``PermissionDeniedError``).
    - ``InvalidRequestError``: any other deterministic 4xx (bad params,
      schema violation, content policy, context-window overflow).
    - ``LLMResponseParseError``: model returned a response that doesn't
      parse against the requested schema (raised post-call by
      ``parse_structured_response``).

    **Transient subclass** (5xx and rate limits — retry may help):

    - ``LLMTransientError``: ``Timeout``, ``RateLimitError``,
      ``InternalServerError``. Carries ``kind`` (``timeout``,
      ``rate_limit``, ``server_error``, ``connection``) so consumers outside
      a retry loop can surface targeted remediation. LLMNode's ``_call_llm``
      re-raises it (rather than catching like the deterministic subclasses)
      so the retry loop can retry the call.

    Consumers outside a retry loop (registry/discovery callers,
    smart_filter) catch the base ``LLMCallError`` for graceful
    degradation — the umbrella covers every subclass.

    The structured ``model`` attribute (set on every instance) carries the
    model identifier as a typed field instead of embedding it in the
    message. The ``provider_message`` attribute carries the raw upstream
    LiteLLM/provider exception text — distinct from ``str(self)`` (which
    is the pflow-wrapped diagnostic framing) — so agents can discriminate
    sub-cases beyond the typed ``reason``/``kind`` (e.g. "Quota exceeded"
    vs "Invalid key" inside the same ``MissingApiKeyError(kind="missing_key")``
    bucket). ``to_diagnostics()`` overrides on each subclass produce rich
    Diagnostics with structured context (``error_class``, ``model``,
    ``reason``/``kind``, ``provider_message``) plus user-facing remediation
    suggestions — the single source of truth for what each error means in
    pflow.
    """

    def __init__(
        self,
        message: str,
        *,
        model: str | None = None,
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.model = model
        # Raw provider/LiteLLM exception text captured at the seam, distinct
        # from ``str(self)`` (the pflow-wrapped diagnostic prose). Carries the
        # actionable WHY ("Quota exceeded", "Region not allowed", "Model
        # retired on 2026-01-01") that the wrapper would otherwise discard.
        # ``None`` when no upstream exception was present (e.g. constructed
        # in-pflow rather than translated from LiteLLM).
        self.provider_message = provider_message

    def diagnostic_context(self, **extra: Any) -> dict[str, Any]:
        """Return invariant structured context for LLM provider errors.

        ``provider_message`` is the raw upstream text when available — distinct
        from ``Diagnostic.message`` (pflow-wrapped framing) and from
        ``error_class``/``model``/``reason``/``kind`` (structured discriminators).
        Agents discriminating sub-cases beyond the typed kind/reason should
        read this field; ``None`` when the error originated inside pflow.
        """
        context = {
            "category": LLM_FAILURE_CATEGORY,
            "error_class": type(self).__name__,
            "model": self.model,
            "provider_message": self.provider_message,
        }
        for key, value in extra.items():
            if value is not None:
                context[key] = value
        return context

    def to_diagnostics(self) -> list[Diagnostic]:
        # Returns a single-element list (PflowError convention; LLMNode
        # indexes [0]). Subclasses override with richer context + suggestions.
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="LLM Call Failed",
                source="runtime",
                context=self.diagnostic_context(),
                see_also=["llm"],
            )
        ]


class UnknownModelError(LLMCallError):
    """Provider doesn't recognize the model identifier.

    ``reason`` discriminates the two sub-cases the adapter detects:

    - ``"unknown_name"``: prefix is recognized, model name is wrong
      (e.g. ``anthropic/claude-foo-99``). User needs a different name.
    - ``"missing_prefix"``: model has no provider prefix
      (e.g. ``gpt-4o-mini``). User needs to add ``openai/`` (or similar).

    Consumers branch on this attribute to construct precise remediation
    messages — substring-matching on the message text would be fragile.
    """

    def __init__(
        self,
        message: str,
        *,
        model: str | None = None,
        reason: UnknownModelReason = "unknown_name",
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message, model=model, provider_message=provider_message)
        self.reason: UnknownModelReason = reason

    def to_diagnostics(self) -> list[Diagnostic]:
        # Returns single-element list (PflowError convention).
        if self.reason == "missing_prefix":
            suggestions = [
                f"Add a provider prefix to the model identifier "
                f"(e.g. 'openai/{self.model}', 'anthropic/claude-sonnet-5', "
                f"'gemini/gemini-2.5-flash').",
                "See https://docs.litellm.ai/docs/providers for the full list of supported providers.",
                "Run 'pflow settings llm show' to see your configured defaults.",
            ]
        else:
            # unknown_name: the provider itself returned 404 for this model.
            # That is NOT proof the name is wrong — providers also 404 when
            # the API key or project lacks access to the model — so the
            # suggestions must keep both readings open and point at the
            # provider's own text (rendered as the "Provider response:" block).
            suggestions = [
                "Check the exact model name against the provider's current catalogue.",
                "A 404 can also mean your API key or project lacks access to this "
                "model — see the provider response shown with this error.",
                "Run 'pflow settings llm show' to see your configured defaults.",
                "See https://docs.litellm.ai/docs/providers for supported models.",
            ]
            import contextlib

            with contextlib.suppress(Exception):
                # Lazy import — keeps llm_config off the exceptions import graph.
                # Suppressing import errors here is intentional: this hint is
                # nice-to-have, not load-bearing. If llm_config can't be imported
                # for any reason, we silently fall back to the generic suggestions.
                from pflow.core.llm_config import get_default_llm_model

                detected = get_default_llm_model()
                if detected:
                    suggestions.append(
                        f"To isolate model-vs-key, retry with '{detected}' "
                        "(a model your configured keys already reach)."
                    )

        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Unknown Model",
                suggestions=suggestions,
                source="runtime",
                context=self.diagnostic_context(reason=self.reason),
                see_also=["llm"],
            )
        ]


class MissingApiKeyError(LLMCallError):
    """API key missing, wrong, or lacks permission for the requested model.

    ``kind`` discriminates the two sub-cases the adapter detects:

    - ``"missing_key"``: ``AuthenticationError`` from the provider
      (no key set, or key rejected as invalid).
    - ``"lacks_permission"``: ``PermissionDeniedError`` from the provider
      (key is valid but doesn't have access to the requested model).

    Consumers branch on this attribute — substring-matching on the
    message text would be fragile to upstream rewording.
    """

    def __init__(
        self,
        message: str,
        *,
        model: str | None = None,
        kind: MissingApiKeyKind = "missing_key",
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message, model=model, provider_message=provider_message)
        self.kind: MissingApiKeyKind = kind

    def to_diagnostics(self) -> list[Diagnostic]:
        # Returns single-element list (PflowError convention).
        env_vars = _derive_env_vars_for_model(self.model)
        likely_env_var: str | None = None
        if self.kind == "lacks_permission":
            suggestions = [
                "Verify the API key has access to this specific model "
                "(some models require explicit access requests on the provider's dashboard).",
                "Check whether your provider tier supports this model.",
                "Try a different model your key is known to support.",
            ]
        elif env_vars:
            # Known provider — registry has precise env-var names.
            canonical = env_vars[0]
            suggestions = [
                f"Set the provider API key as an environment variable (e.g. 'export {canonical}=...').",
                f"Alternatively, run 'pflow settings set-env {canonical} <value>' to store it in pflow settings.",
                "See https://docs.litellm.ai/docs/providers for provider-specific key names "
                "(Bedrock, Azure, Vertex, etc.).",
            ]
            if len(env_vars) > 1:
                aliases = ", ".join(env_vars[1:])
                suggestions.append(f"This provider also accepts: {aliases}.")
        else:
            # Unknown provider — registry has no entry for this model's prefix.
            # The provider's authentication error (rendered above suggestions
            # via ``context['provider_message']``) typically names the expected
            # env var; that is the authoritative signal. Our prefix-uppercase
            # heuristic is a starting point only — multi-key providers (AWS
            # Bedrock, Azure, Vertex AI) need additional credentials beyond a
            # single API key, so we present the candidate as "likely" not
            # authoritative.
            likely_env_var = _likely_env_var_for_unknown_provider(self.model)
            suggestions = [
                "The provider's authentication error above usually names the "
                "expected environment variable — set that in your shell or "
                "store it via 'pflow settings set-env <KEY> <value>'.",
            ]
            if likely_env_var:
                suggestions.append(
                    f"Most LiteLLM providers follow the '<PROVIDER>_API_KEY' "
                    f"convention; for this model that's likely "
                    f"'{likely_env_var}'. Multi-key providers (AWS Bedrock, "
                    f"Azure, Vertex AI) need additional credentials — see "
                    f"the LiteLLM docs for the specific provider."
                )
            suggestions.append(
                "See https://docs.litellm.ai/docs/providers for the full provider list and provider-specific key names."
            )

        ctx = self.diagnostic_context(
            kind=self.kind,
            env_vars=list(env_vars),
            likely_env_var=likely_env_var,
        )

        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="API Key Missing or Insufficient",
                suggestions=suggestions,
                source="runtime",
                context=ctx,
                see_also=["llm"],
            )
        ]


class InvalidRequestError(LLMCallError):
    """Request was rejected by the provider for any other deterministic reason.

    Covers schema violations (response_format mismatch), content-policy
    rejections, context-window overflow, and any other ``BadRequestError``
    that isn't an unknown-model case.
    """

    def to_diagnostics(self) -> list[Diagnostic]:
        # Returns single-element list (PflowError convention).
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Invalid Request",
                suggestions=[
                    "Check the request shape against the provider's documentation. "
                    "The provider's message above typically identifies the offending parameter.",
                ],
                source="runtime",
                context=self.diagnostic_context(),
                see_also=["llm"],
            )
        ]


class LLMTransientError(LLMCallError):
    """Transient LLM provider error (timeout, rate limit, 5xx).

    ``kind`` discriminates the transient sub-case so callers outside a retry
    loop can surface specific remediation instead of a generic LLM failure.
    LLMNode's ``_call_llm`` re-raises this rather than catching it (unlike
    the deterministic ``LLMCallError`` subclasses) so the retry loop sees an
    exception and can retry.

    Translated from LiteLLM's ``Timeout``, ``RateLimitError``, and
    ``InternalServerError`` at the adapter seam (``llm_client.complete``).
    Note: this is distinct from pflow's inner-pool ``FuturesTimeoutError``
    (the LLMNode-level timeout that orphan-protects the worker thread).
    """

    def __init__(
        self,
        message: str,
        *,
        model: str | None = None,
        kind: LLMTransientKind = "connection",
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message, model=model, provider_message=provider_message)
        self.kind: LLMTransientKind = kind

    def to_diagnostics(self) -> list[Diagnostic]:
        suggestions_by_kind = {
            "timeout": [
                "Retry the workflow; provider timeouts are usually transient.",
                "If this repeats, increase the LLM node timeout or reduce prompt/output size.",
                "Check the provider status page for ongoing incidents.",
            ],
            "rate_limit": [
                "Retry later after the provider rate limit resets.",
                "Reduce parallel LLM calls or batch size for this workflow.",
                "Use a lower-throughput model or provider tier if this happens repeatedly.",
            ],
            "server_error": [
                "Retry the workflow; provider 5xx errors are usually transient.",
                "Check the provider status page before repeated retries.",
                "Try a different model or provider if the incident persists.",
            ],
            "connection": [
                "Retry the workflow; network failures are often transient.",
                "Check local network connectivity and provider availability.",
                "If using a custom endpoint, verify the base URL and transport settings.",
            ],
        }
        suggestions = suggestions_by_kind.get(self.kind, suggestions_by_kind["connection"])
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Transient LLM Failure",
                suggestions=suggestions,
                source="runtime",
                context=self.diagnostic_context(kind=self.kind),
                see_also=["llm"],
            )
        ]


class MissingSdkError(LLMCallError):
    """A provider requires an SDK that is not installed in pflow's environment.

    Translated from ``APIConnectionError`` when the exception chain contains
    an ``ImportError`` — a reliable signal that the failure is permanent
    (retrying won't install the package).
    """

    def __init__(
        self,
        message: str,
        *,
        model: str | None = None,
        package: str | None = None,
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message, model=model, provider_message=provider_message)
        self.package = package

    def to_diagnostics(self) -> list[Diagnostic]:
        suggestions = [
            "Most providers (OpenAI, Anthropic, Google AI Studio, Ollama) work "
            "without extra installs — check the model prefix is correct.",
        ]
        if self.package:
            suggestions.insert(
                0,
                f"Install the required package into pflow's environment:\n"
                f"  uv tool install --with '{self.package}' pflow-cli\n"
                f"  pipx inject pflow-cli '{self.package}'",
            )
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=f"Model '{self.model}' requires a provider SDK that is not installed.",
                title="Missing Provider SDK",
                suggestions=suggestions,
                source="runtime",
                context=self.diagnostic_context(package=self.package),
                see_also=["llm"],
            )
        ]


class LLMOutputSchemaError(PflowError):
    """An LLM ``output_schema`` is not safe or valid for execution."""

    retriable = False
    batch_fatal = False

    def __init__(self, message: str, *, schema_path: str | None = None) -> None:
        super().__init__(message)
        self.schema_path = schema_path

    def to_diagnostics(self) -> list[Diagnostic]:
        context: dict[str, Any] = {
            "category": LLM_VALIDATION_CATEGORY,
            "error_class": type(self).__name__,
        }
        if self.schema_path is not None:
            context["schema_path"] = self.schema_path
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="LLM Configuration",
                suggestions=[
                    "Fix `output_schema` so it is a self-contained valid JSON Schema.",
                    "Use only references resolvable within the authored schema; external schema retrieval is disabled.",
                ],
                source="runtime",
                context=context,
                see_also=["llm"],
            )
        ]


class LLMResponseParseError(LLMCallError):
    """Model response could not be parsed against the requested schema.

    Raised by ``parse_structured_response`` when ``output_schema`` is set
    but the model returned text that isn't valid JSON (or doesn't match
    the schema). Treated as deterministic — retrying the same prompt is
    likely to produce the same bad response.
    """

    def __init__(
        self,
        message: str,
        *,
        model: str | None = None,
        provider_message: str | None = None,
        kind: LLMResponseParseKind | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message, model=model, provider_message=provider_message)
        self.kind = kind
        self.path = path

    def to_diagnostics(self) -> list[Diagnostic]:
        # Returns single-element list (PflowError convention).
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title=(
                    "Structured Output Validation Failed" if self.kind == "schema_mismatch" else "Response Parse Failed"
                ),
                suggestions=[
                    "Verify the requested 'output_schema' matches what the model can produce.",
                    "Check the raw response in the trace JSON to see what the model actually returned.",
                    "Consider simplifying the schema if the model consistently fails to match it.",
                ],
                source="runtime",
                context=self.diagnostic_context(kind=self.kind, path=self.path),
                see_also=["llm"],
            )
        ]


def _derive_env_vars_for_model(model: str | None) -> tuple[str, ...]:
    """Best-effort derivation of the provider env-var names for a model.

    Used by ``MissingApiKeyError.to_diagnostics()`` to surface the
    expected env-var names (canonical first; aliases follow). Returns
    an empty tuple when the prefix is unrecognized or absent — caller
    handles that branch via ``_likely_env_var_for_unknown_provider``.
    """
    provider = detect_provider(model)
    return provider.env_vars if provider is not None else ()


def _likely_env_var_for_unknown_provider(model: str | None) -> str | None:
    """Heuristic env-var guess for providers absent from pflow's registry.

    Most LiteLLM providers follow the ``<PROVIDER_UPPER>_API_KEY`` convention
    (Mistral, Cohere, Groq, DeepSeek, Together, OpenRouter, Anyscale, ...).
    The heuristic uppercases the slash-prefix from the model identifier:
    ``together_ai/llama-3-70b`` -> ``TOGETHER_AI_API_KEY``.

    Returns ``None`` when the model has no parseable prefix. The caller
    MUST frame the result as a likely candidate, not authoritative —
    multi-key providers (AWS Bedrock, Azure, Vertex AI) need additional
    credentials beyond a single API key, and the heuristic underspecifies
    them. The authoritative signal for unknown providers is the
    ``provider_message`` field on the exception (the raw upstream text
    LiteLLM produces, which usually names the missing var).
    """
    prefix = extract_provider_prefix(model)
    if prefix is None:
        return None
    return f"{prefix.upper()}_API_KEY"


class TTSSynthesisError(PflowError):
    """TTS synthesis call failed (network, API error, or unparseable response).

    Raised by ``core.tts.synthesize`` for every failure after the API key check
    (a missing key raises ``MissingApiKeyError`` instead). It never reaches the
    engine — the ``pflow ui --say`` path catches it and folds the message into
    the narration report so a synthesis failure degrades to caption-only rather
    than aborting the point. No ``to_diagnostics`` override needed.
    """

    pass


class SchemaValidationError(PflowError):
    """Validation error for IR schema with helpful messages and field paths.

    Attributes:
        message: The validation error message
        path: Dotted path to the invalid field (e.g., "nodes[0].type")
        suggestion: Optional suggestion for fixing the error
        similar_names: Optional fuzzy-match suggestions
        available_fields: Optional list of valid alternatives
        available_fields_label: Optional noun for the alternatives block
        suggestions_list: Optional multi-suggestion list
    """

    def __init__(
        self,
        message: str,
        path: str = "",
        suggestion: str = "",
        *,
        similar_names: list[str] | None = None,
        available_fields: list[str] | None = None,
        available_fields_label: str | None = None,
        suggestions_list: list[str] | None = None,
    ):
        self.message = message
        self.path = path
        self.suggestion = suggestion
        self.similar_names = similar_names or []
        self.available_fields = available_fields or []
        self.available_fields_label = available_fields_label
        self.suggestions_list = suggestions_list or []

        full_message = "Validation error"
        if path:
            full_message += f" at {path}"
        full_message += f": {message}"
        if suggestion:
            full_message += f"\n{suggestion}"

        super().__init__(full_message)

    def to_diagnostics(self) -> list[Diagnostic]:
        ctx: dict[str, Any] = {"category": "validation"}
        if self.path:
            ctx["path"] = self.path
        if self.similar_names:
            ctx["similar_names"] = self.similar_names
        if self.available_fields:
            ctx["available_fields"] = self.available_fields
        if self.available_fields_label:
            ctx["available_fields_label"] = self.available_fields_label

        if self.suggestions_list:
            suggestions = self.suggestions_list
        elif self.suggestion:
            suggestions = [self.suggestion]
        else:
            suggestions = None

        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.message,
                title="Validation Error",
                suggestions=suggestions,
                source="validation",
                context=ctx,
            )
        ]


class MarkdownParseError(PflowError):
    """Error raised when markdown workflow content cannot be parsed.

    Attributes:
        line: Source line number where the error occurred (1-based).
        suggestion: Optional human-readable fix suggestion.
        see_also: Optional list of ``pflow guide`` topics that explain the
            structural pattern behind this error (e.g. ``["branching"]`` for
            routing-target errors).
    """

    def __init__(
        self,
        message: str,
        line: int | None = None,
        suggestion: str | None = None,
        see_also: list[str] | None = None,
    ):
        self.raw_message = message
        self.line = line
        self.suggestion = suggestion
        self.see_also = see_also
        prefix = f"Line {line}: " if line is not None else ""
        full = f"{prefix}{message}"
        if suggestion:
            full += f"\n\n{suggestion}"
        super().__init__(full)

    def to_diagnostics(self) -> list[Diagnostic]:
        ctx: dict[str, Any] = {"category": "parse_error"}
        if self.line is not None:
            ctx["line"] = self.line
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.raw_message,
                title="Parse Error",
                suggestions=[self.suggestion] if self.suggestion else None,
                source="parser",
                context=ctx,
                see_also=self.see_also,
            )
        ]


class CompilationError(PflowError):
    """Error during IR compilation with rich context.

    Attributes:
        phase: The compilation phase where the error occurred
        node_id: ID of the node being compiled (if applicable)
        node_type: Type of the node being compiled (if applicable)
        details: Additional context about the error
        suggestion: Helpful suggestion for fixing the error
        wrapped_diagnostics: Structured diagnostics collected by a sub-validator
            before this exception was raised. When present, ``to_diagnostics()``
            returns them directly so the compile-time path preserves the same
            rich structure (paths, suggestions, similar_names, available_fields)
            that the pre-execution validator produces. Used by
            ``compile_validation.py`` to carry the ``validate_data_flow()`` list
            through the compiler boundary without flattening it to a string.
    """

    retriable = False

    def __init__(
        self,
        message: str,
        phase: str = "unknown",
        node_id: str | None = None,
        node_type: str | None = None,
        details: dict[str, Any] | None = None,
        suggestion: str | None = None,
        wrapped_diagnostics: list[Diagnostic] | None = None,
    ):
        self.raw_message = message
        self.phase = phase
        self.node_id = node_id
        self.node_type = node_type
        self.details = details or {}
        self.suggestion = suggestion
        self.wrapped_diagnostics = wrapped_diagnostics

        parts = [f"compiler: {message}"]
        if phase != "unknown":
            parts.append(f"Phase: {phase}")
        if node_id:
            parts.append(f"Node ID: {node_id}")
        if node_type:
            parts.append(f"Node Type: {node_type}")
        if suggestion:
            parts.append(f"Suggestion: {suggestion}")

        super().__init__("\n".join(parts))

    def to_diagnostics(self) -> list[Diagnostic]:
        if self.wrapped_diagnostics:
            # Wrapped diagnostics carry inner structure (e.g. SchemaValidationError's
            # similar_names / available_fields). This CompilationError contributes
            # container context (sub_workflow_path). Merge the latter into each
            # wrapped diagnostic's context so both render — wrapped context wins
            # on conflict, mirroring dict.setdefault semantics.
            sub_workflow_path = self.details.get("sub_workflow_path")
            if sub_workflow_path is None:
                return list(self.wrapped_diagnostics)
            return [
                replace(
                    d,
                    context={"sub_workflow_path": sub_workflow_path, **(d.context or {})},
                )
                for d in self.wrapped_diagnostics
            ]
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.raw_message,
                title="Compilation Failed",
                suggestions=[self.suggestion] if self.suggestion else None,
                node_id=self.node_id,
                source="compilation",
                context={
                    "category": "compilation",
                    "phase": self.phase,
                    "node_type": self.node_type,
                    "sub_workflow_path": self.details.get("sub_workflow_path"),
                },
            )
        ]


class LoopConditionError(PflowError):
    """Raised at runtime when a ``loop: while:`` condition cannot be evaluated safely (issue #445).

    Two cases:
    - the resolved condition value is a ``str`` (string truthiness is a foot-gun —
      validation rejects known-string sources, but a dynamic/un-inferable output
      may still turn out to be a string at runtime);
    - the resolved ``max_iterations`` template is not a usable positive integer.
    """

    def __init__(self, message: str, *, node_id: str | None = None, suggestion: str | None = None):
        self.raw_message = message
        self.node_id = node_id
        self.suggestion = suggestion
        super().__init__(message)

    def to_diagnostics(self) -> list[Diagnostic]:
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.raw_message,
                title="Loop Condition Error",
                suggestions=[self.suggestion] if self.suggestion else None,
                node_id=self.node_id,
                source="runtime",
                context={"category": "validation", "node_id": self.node_id},
            )
        ]


class LoopCarryError(PflowError):
    """Raised when a carried loop input cannot resolve on a carried iteration."""

    def __init__(self, message: str, *, node_id: str | None = None, suggestion: str | None = None):
        self.raw_message = message
        self.node_id = node_id
        self.suggestion = suggestion
        super().__init__(message)

    def to_diagnostics(self) -> list[Diagnostic]:
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.raw_message,
                title="Loop Carry Error",
                suggestions=[self.suggestion] if self.suggestion else None,
                node_id=self.node_id,
                source="runtime",
                context={"category": "validation", "node_id": self.node_id},
            )
        ]


class OnlySnapshotMissingError(PflowError):
    """Raised when ``--only`` has no prior full-run trace to restore upstream from (issue #443).

    ``--only <node>`` runs the target against a frozen snapshot of the most
    recent full successful run (read from ``~/.pflow/debug/``) instead of
    re-walking the graph — so side-effecting upstream nodes (``gh pr create``)
    don't re-fire on every iteration. When no usable trace exists (the workflow
    was never run fully, was run only with ``--no-trace``, or only ``--only``
    traces exist), there is nothing to restore from. This is a HARD error rather
    than a silent re-walk: re-walking would re-fire upstream side effects, which
    is precisely what #443 set out to stop.
    """

    _DEFAULT_SUGGESTION = (
        "Run the full workflow once (without --no-trace), then retry --only. "
        "Snapshot reuse reads the most recent successful trace from ~/.pflow/debug/."
    )

    def __init__(self, only_node: str, *, suggestion: str | None = None):
        self.only_node = only_node
        self.suggestion = suggestion if suggestion is not None else self._DEFAULT_SUGGESTION
        super().__init__(
            f"--only '{only_node}' needs a prior full run to restore upstream from, "
            f"but no usable trace was found for this workflow."
        )

    def to_diagnostics(self) -> list[Diagnostic]:
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="No snapshot for --only",
                source="runtime",
                suggestions=[self.suggestion] if self.suggestion else None,
                context={"category": "execution_failure"},
            )
        ]


class GateDenied(PflowError):
    """A human denied an approval Gate (Task 125).

    A human verdict, NOT a node failure: the gated node never ran, nothing broke.
    This exception is pure control flow — it must cross every generic
    ``except Exception`` between the gate and the runner UN-converted (engine
    ``_execute_node``, ``WorkflowExecutor.exec``, batch retry loops via
    ``retriable=False``), where the runner maps it to a clean DENIED result.
    Never route it through ``error_action``/on-error edges — a workflow must not
    "handle" a human's no.
    """

    retriable = False

    def __init__(self, request: GateRequest):
        self.request = request
        super().__init__(f"Denied at gate '{request.node_id}'.")

    def to_diagnostics(self) -> list[Diagnostic]:
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Gate denied",
                node_id=self.request.node_id,
                source="runtime",
                context={"category": "gate", "gate": _masked_gate_payload(self.request)},
            )
        ]


class GateNotInteractiveError(PflowError):
    """A Gate fired but this run has no way to ask a human (Task 125).

    Carries the full ``GateRequest`` so the operating agent can show its human
    exactly WHAT was about to happen — approving blind defeats the gate. Like
    ``GateDenied``, it is exempted from every generic exception-conversion
    boundary (``retriable=False`` keeps batch retry loops from re-firing the
    gate); the runner surfaces it as a normal FAILED result with these
    diagnostics intact.
    """

    retriable = False

    def __init__(self, request: GateRequest, *, parallel_batch: bool = False):
        self.request = request
        self.parallel_batch = parallel_batch
        # Task 179: set by the engine when the gate could not pause because a resume
        # would restore ``(step, lossy entries)`` unfaithfully from the saved run.
        self.lossy_seed: tuple[str, list[str]] | None = None
        if parallel_batch:
            cause = "it fired inside a parallel batch item, which cannot host a prompt"
        else:
            cause = "this run is non-interactive (launched from the web UI, MCP, or a pipe — no terminal to prompt on)"
        kind = "approval" if request.kind == GATE_KIND_APPROVAL else "escalation"
        super().__init__(f"Step '{request.node_id}' requires a human {kind} decision, but {cause}.")

    def to_diagnostics(self) -> list[Diagnostic]:
        suggestions = [
            "If you are an AI agent: ask your human before continuing — this gate exists so a person reviews the action."
        ]
        if self.lossy_seed is not None:
            step, lossy = self.lossy_seed
            suggestions.append(
                f"This gate did not pause: answering it later would resume from the saved run, which cannot "
                f"restore step '{step}' faithfully ({'; '.join(lossy)}). Answer it in this run instead — "
                "pre-approve it or run interactively — or make that step's result JSON-native "
                "(dict/list/str/int/float/bool/None) — e.g. `str(dt)` / `sorted(s)` in the code step."
            )
        if self.request.kind == GATE_KIND_APPROVAL:
            suggestions.append(
                f"With their OK, pre-approve ONLY this gate: CLI `--auto-approve={self.request.node_id}`; "
                f'MCP workflow_execute: `auto_approve=["{self.request.node_id}"]`.'
            )
            if self.parallel_batch:
                suggestions.append(
                    "Or restructure: move `approval:` to a step outside the batch, "
                    "or set `parallel: false` on the batch."
                )
        else:
            suggestions.append(
                "Escalations cannot be pre-approved — run interactively, "
                "or re-run with the answer supplied as a workflow input."
            )
        # Task 171: gates normally pause durably (trace = checkpoint, resume by
        # token). Reaching THIS error post-171 means the durable path was
        # unavailable — name --no-trace explicitly as the removable blocker so
        # an agent reads "drop the flag", not "gates don't work here".
        suggestions.append(
            "Gates pause durably when tracing is on (the run exits with a resume token). "
            "This error means tracing was explicitly disabled (--no-trace — drop the flag to pause instead), "
            "the workflow was submitted inline (no source file to resume from — save it and run by name/path "
            "to pause instead), the run targeted a single node with --only (its snapshot trace isn't "
            "resumable — run the full workflow to pause), or the gate is in an unsupported position "
            "(parallel batch item, sub-workflow child, or a code-node/final-step escalation)"
            + (", or its resume could not restore earlier work faithfully (above)." if self.lossy_seed else ".")
        )
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Gate needs a human",
                node_id=self.request.node_id,
                source="runtime",
                suggestions=suggestions,
                context={
                    "category": "gate",
                    "gate": _masked_gate_payload(self.request),
                    "parallel_batch": self.parallel_batch,
                },
            )
        ]


class GateResolverError(PflowError):
    """The installed gate resolver itself failed (Task 125).

    Raised when a resolver raises an unexpected exception or returns the wrong
    type — a bug in the resolver installation, NOT a human verdict and NOT a
    node failure. It shares the gate exceptions' exemptions (``retriable=False``,
    re-raised untouched at every generic boundary) for one reason: the post-exec
    escalation seam runs AFTER the node's success was traced, and the generic
    arm would record a second (error) event for the node and archive its
    genuinely-successful output into ``__failures__``. The run still fails —
    the runner surfaces it as a normal FAILED result.
    """

    retriable = False

    def __init__(self, request: GateRequest, *, detail: str):
        self.request = request
        super().__init__(f"Gate resolver failed at gate '{request.node_id}': {detail}")

    def to_diagnostics(self) -> list[Diagnostic]:
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Gate resolver failed",
                node_id=self.request.node_id,
                source="runtime",
                suggestions=[
                    "This is a bug in the gate resolver installation (CLI, MCP, or a custom surface), "
                    "not in the workflow — the gated step was not silently approved or denied."
                ],
                context={"category": "gate", "gate": _masked_gate_payload(self.request)},
            )
        ]


def _masked_gate_payload(request: GateRequest) -> dict[str, Any]:
    """GateRequest as a dict with secret-named preview values redacted.

    The diagnostic reaches agents/humans through error text and MCP responses —
    secrets don't inform an approval decision, but everything ELSE must survive
    in full (approving blind defeats the gate). The object-form twin of the
    shared dict-form ``masked_gate_dict`` (mask-only, recursive, no truncation):
    ``to_dict()`` then the one shared masking rule. The trace's gate event
    carries the unmasked payload, consistent with ``template_resolutions``.
    """
    from pflow.core.gate import masked_gate_dict

    return masked_gate_dict(request.to_dict())


class MaxNodeVisitsError(RuntimeError):
    """Raised when a node exceeds the maximum allowed visits (loop guard)."""

    def __init__(self, node_id: str, visit_count: int, max_visits: int):
        self.node_id = node_id
        self.visit_count = visit_count
        self.max_visits = max_visits
        super().__init__(
            f"Node '{node_id}' exceeded maximum visits ({visit_count}/{max_visits}). "
            f"This likely indicates an infinite loop in the workflow. "
            f"Set PFLOW_MAX_NODE_VISITS to increase the limit if this is intentional."
        )

    def to_diagnostics(self) -> list[Diagnostic]:
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=(
                    f"Node '{self.node_id}' exceeded maximum visits "
                    f"({self.visit_count}/{self.max_visits}). "
                    f"This likely indicates an infinite loop in the workflow."
                ),
                title="Infinite Loop Detected",
                suggestions=["Set PFLOW_MAX_NODE_VISITS to increase the limit if this is intentional."],
                node_id=self.node_id,
                source="runtime",
                context={
                    "category": "max_visits",
                    "visit_count": self.visit_count,
                    "max_visits": self.max_visits,
                },
            )
        ]


class ResumeSourceError(PflowError):
    """Base for every ``pflow resume`` refusal (Task 164).

    A resume refusal is agent-first: the message says WHAT stopped the resume
    and WHY, the suggestions say HOW to proceed. Every refusal carries the
    source run's ``execution_id`` and its ``trace_path`` in the diagnostic
    context so a programmatic consumer can correlate the refusal with the exact
    attempt it inspected. Modeled on ``OnlySnapshotMissingError`` — a class-level
    default title + a single ``Severity.ERROR`` diagnostic with
    ``context={"category": "execution_failure"}``. All subclasses exit 1 via
    ``PflowCLI.invoke``.

    One class per refusal FAMILY, not per message: ``ResumeNotResumableError``
    carries several distinct messages (denied run, undecided escalation, inline
    source, edited-away step) because they share one remediation shape (re-run).
    """

    _TITLE = "Cannot resume"

    def __init__(
        self,
        message: str,
        *,
        execution_id: str | None = None,
        trace_path: str | None = None,
        suggestions: list[str] | None = None,
        node_id: str | None = None,
    ):
        self.execution_id = execution_id
        self.trace_path = trace_path
        self.suggestions = suggestions or []
        self.node_id = node_id
        super().__init__(message)

    def to_diagnostics(self) -> list[Diagnostic]:
        context: dict[str, Any] = {"category": "execution_failure"}
        if self.execution_id:
            context["execution_id"] = self.execution_id
        if self.trace_path:
            context["trace_path"] = self.trace_path
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title=self._TITLE,
                node_id=self.node_id,
                source="runtime",
                suggestions=self.suggestions or None,
                context=context,
            )
        ]


class ResumeSourceMissingError(ResumeSourceError):
    """No trace was found to resume — the target names no known run (Task 164)."""

    _TITLE = "No run to resume"


class ResumeNothingToResumeError(ResumeSourceError):
    """The newest run already succeeded — there is nothing to resume (Task 164)."""

    _TITLE = "Nothing to resume"


class ResumeNotResumableError(ResumeSourceError):
    """The run exists but cannot be resumed (Task 164).

    The catch-all refusal family whose members share the "re-run instead"
    remediation: a human-denied gate stop, an undecided escalation in the seed
    scope, an ambiguous between-nodes successor, an inline/piped source (no file
    to re-resolve), or a failed step that no longer exists after an edit.
    """

    _TITLE = "Run cannot be resumed"


class ResumeGateStoppedError(ResumeSourceError):
    """The run stopped at a human gate, not at a failed step (Task 164, Decision 8).

    ``final_status:"failed"`` with no unrecovered failed node means a gate
    (recovered from the disk-only ``kind:"gate"`` lines) stopped the run. Task
    171 replaces this refusal arm with a resumable ``paused`` case.
    """

    _TITLE = "Run stopped at a gate"

    def __init__(
        self,
        *,
        node_id: str,
        gate_kind: str | None,
        execution_id: str | None = None,
        trace_path: str | None = None,
    ):
        kind = gate_kind or "approval"
        super().__init__(
            f"This run stopped at a human {kind} gate on step '{node_id}', not at a failed step. "
            "Resume recovers failed steps; a gate stop is a deliberate human checkpoint.",
            execution_id=execution_id,
            trace_path=trace_path,
            node_id=node_id,
            suggestions=["Re-run the workflow and answer the gate, or run it interactively."],
        )


class ResumeStillRunningError(ResumeSourceError):
    """The target run is still in progress — its trace is held by a live writer (Task 164)."""

    _TITLE = "Run still in progress"


class ResumeSupersededError(ResumeSourceError):
    """A newer attempt already resumed this run — resume targets the newest (Task 164)."""

    _TITLE = "A newer attempt exists"

    def __init__(
        self,
        newer_execution_id: str,
        *,
        execution_id: str | None = None,
        trace_path: str | None = None,
    ):
        self.newer_execution_id = newer_execution_id
        super().__init__(
            f"This run was already resumed by a newer attempt '{newer_execution_id}'. "
            "Resume targets the newest attempt in a chain.",
            execution_id=execution_id,
            trace_path=trace_path,
            suggestions=[f"pflow resume {newer_execution_id}"],
        )


class ResumeFidelityError(ResumeSourceError):
    """A value resume would restore did not survive the trace unchanged (Task 164 Decision 5; Task 179).

    The trace stores JSON: bytes become a ``<binary data: N bytes>`` placeholder, a
    non-string key becomes a string, a set/date/Decimal/custom object becomes its
    ``str()``, and nested ``__`` keys are dropped. Seeding such a value would restore
    different data than the step produced — refuse, naming where (``lossy``: the
    trace's ``"<path>: <why>"`` entries).
    """

    _TITLE = "Cannot resume — unrecoverable data"

    def __init__(
        self,
        *,
        node_id: str,
        lossy: list[str],
        execution_id: str | None = None,
        trace_path: str | None = None,
    ):
        self.lossy = lossy
        super().__init__(
            f"Step '{node_id}' produced a value the saved run cannot restore faithfully "
            f"({'; '.join(lossy)}), so resuming would restore different data.",
            execution_id=execution_id,
            trace_path=trace_path,
            node_id=node_id,
            suggestions=[
                "make the step's result JSON-native (dict/list/str/int/float/bool/None) — e.g. `str(dt)` / "
                "`sorted(s)` in the code step — or re-run from the start"
            ],
        )


class ResumeSideEffectConfirmationError(ResumeSourceError):
    """Resume would re-run a side-effecting step without confirmation (Task 164, Decision 4).

    A non-interactive (agent / MCP / pipe) resume whose failed step K
    side-effects (shell / code / agent / file-ops / mcp; http reads
    external state). Resume gives at-least-once execution of K, so its side
    effects MAY fire again — a non-TTY run refuses loudly rather than prompt or
    silently repeat them. Mirrors ``GateNotInteractiveError``'s what/why/how
    shape; ``--force`` bypasses it.
    """

    _TITLE = "Resume needs confirmation"

    def __init__(
        self,
        node_id: str,
        node_type: str,
        *,
        execution_id: str | None = None,
        trace_path: str | None = None,
    ):
        self.node_type = node_type
        super().__init__(
            f"Resuming re-runs step '{node_id}' (a {node_type} step), and its side effects may fire again. "
            "This run is non-interactive (agent/MCP/pipe — no terminal to confirm on), so resume refuses "
            "rather than repeat them silently.",
            execution_id=execution_id,
            trace_path=trace_path,
            node_id=node_id,
            suggestions=[
                "If you are an AI agent: confirm with your human that re-running this step is safe.",
                "With their OK, re-run with --force to bypass this confirmation.",
            ],
        )


Route = tuple[str, str]  # (action, target) — one outgoing edge of a step


def _quoted(names: list[str]) -> str:
    return ", ".join(f"'{name}'" for name in names)


def _routes_text(routes: list[Route]) -> str:
    """``'b'`` for the default route, ``'b' on error`` / ``'b' on 'x'`` for the others."""
    labels = []
    for action, target in routes:
        suffix = "" if action == "default" else " on error" if action == "error" else f" on '{action}'"
        labels.append(f"'{target}'{suffix}")
    return ", ".join(labels)


class ResumeStaleWorkflowError(ResumeSourceError):
    """The workflow changed since the original run in a way this resume would get wrong (Task 164;
    paused resumes Task 171; per step since Task 180).

    The preflight passes each change it found; the message leads with them in a fixed order: removed
    → resume point gone → edited (``cache_edited``: a ``## Cache`` chunk's content changed) → edited
    after approval → now leads elsewhere (``rerouted``: step → (now, recorded) routes) → new start
    step (``new_start``: (now, recorded)). ``skipped`` names the new route targets / start step the
    resume would never run. Then it says what the resume would do instead — restore stale outputs,
    continue into a between-nodes source's new route, or run an approved step as edited. With no
    change given, the trace predates per-step identity: ``hash_known`` says the whole-workflow hash
    differs (an older pflow), ``False`` that not even that is known (a run predating hash tracking) —
    never claiming an edit that may not have happened. The suggestions name what ``--force`` accepts
    and, when ``rerun_node_type`` is given, that it also re-runs a started side-effecting resume
    point. Wording stays neutral ("original run"): this refusal serves failed, interrupted, AND
    paused resumes.
    """

    _TITLE = "Workflow changed since the original run"

    def __init__(
        self,
        *,
        hash_known: bool,
        entry_node_id: str | None,
        removed: list[str] | None = None,
        resume_point_missing: bool = False,
        edited: list[str] | None = None,
        cache_edited: frozenset[str] = frozenset(),
        approved_edited: str | None = None,
        rerouted: dict[str, tuple[list[Route], list[Route]]] | None = None,
        new_start: tuple[str, str | None] | None = None,
        skipped: frozenset[str] = frozenset(),
        entry_iteration: int | None = None,
        after_node_id: str | None = None,
        rerun_node_type: str | None = None,
        execution_id: str | None = None,
        trace_path: str | None = None,
    ):
        removed, edited, rerouted = removed or [], edited or [], rerouted or {}
        self.hash_known = hash_known
        self.resume_point = entry_node_id if entry_node_id is not None else after_node_id
        self.resume_point_missing = resume_point_missing
        self.new_start = new_start[0] if new_start is not None else None
        changed = list(dict.fromkeys([*removed, *edited, *([approved_edited] if approved_edited else []), *rerouted]))
        known = bool(changed or resume_point_missing or new_start)
        # None = unknown (the trace records no per-step identity), never "nothing changed".
        self.changed_steps: list[str] | None = changed if known else None
        leads = _stale_leads(removed, resume_point_missing, self.resume_point, edited, cache_edited, approved_edited)
        leads += [_rerouted_lead(node_id, now, before, skipped) for node_id, (now, before) in rerouted.items()]
        if new_start is not None:
            leads.append(_new_start_lead(*new_start, skipped))
        if not known:
            leads = [
                "This run was recorded by an older pflow version that did not record each step's definition, "
                "so resume cannot tell which step changed."
                if hash_known
                else "Cannot verify the workflow is unchanged — this run predates workflow-hash tracking."
            ]
        where = f"'{entry_node_id}'" if entry_node_id is not None else None
        if where is not None and entry_iteration is not None and entry_iteration > 1:
            where += f" (iteration {entry_iteration})"
        scope = f"before {where}" if where is not None else f"up to and including '{after_node_id}'"
        if resume_point_missing:
            body: list[str] = []
            suggestions = [
                "Re-run the workflow from the start.",
                f"Or restore the step '{self.resume_point}' and resume again.",
            ]
        else:
            # A plain between-nodes source continues at its last step's CURRENT route, so that reroute runs.
            continuing = rerouted.get(after_node_id) if entry_node_id is None and after_node_id else None
            upstream = len(removed) + len(edited) + len(rerouted) - (continuing is not None) + (new_start is not None)
            body = _stale_body(
                scope, upstream if known else None, hash_known, continuing, after_node_id, approved_edited
            )
            if where is not None and entry_iteration is not None and entry_iteration > 1:
                body.append(
                    f"Its iterations before {entry_iteration} are restored too, so an edit to '{entry_node_id}' "
                    f"applies from iteration {entry_iteration} on."
                )
            skipped_names = [name for name in dict.fromkeys(_route_targets(rerouted, new_start)) if name in skipped]
            suggestions = _stale_suggestions(
                scope, upstream if known else None, hash_known, skipped_names, approved_edited, continuing
            )
            if rerun_node_type is not None:
                suggestions[1] += (
                    f" --force also re-runs '{entry_node_id}' (a {rerun_node_type} step that already started in the "
                    "original run), so its side effects may fire again — if you are an AI agent, confirm that "
                    "with your human first."
                )
        named = [*changed, *([self.resume_point] if resume_point_missing and self.resume_point else [])]
        super().__init__(
            " ".join([*leads, *body]),
            execution_id=execution_id,
            trace_path=trace_path,
            suggestions=suggestions,
            node_id=named[0] if len(named) == 1 else None,
        )

    def to_diagnostics(self) -> list[Diagnostic]:
        diagnostics = super().to_diagnostics()
        context = diagnostics[0].context
        if context is not None:
            context["changed_steps"] = self.changed_steps
            context["new_start"] = self.new_start
            context["resume_point"] = self.resume_point
            context["resume_point_missing"] = self.resume_point_missing
        return diagnostics


def _stale_leads(
    removed: list[str],
    resume_point_missing: bool,
    resume_point: str | None,
    edited: list[str],
    cache_edited: frozenset[str],
    approved_edited: str | None,
) -> list[str]:
    leads = [
        f"'{node_id}' is no longer in the workflow (resume would still restore its saved output)."
        for node_id in removed
    ]
    if resume_point_missing:
        leads.append(f"The resume point '{resume_point}' is no longer in the workflow.")
    leads += [
        f"'{node_id}' was edited (a `## Cache` chunk it uses changed)."
        if node_id in cache_edited
        else f"'{node_id}' was edited."
        for node_id in edited
    ]
    if approved_edited is not None:
        leads.append(
            f"'{approved_edited}' was edited after it was approved — the approval covered the earlier version."
        )
    return leads


def _stale_body(
    scope: str,
    upstream: int | None,
    hash_known: bool,
    continuing: tuple[list[Route], list[Route]] | None,
    after_node_id: str | None,
    approved_edited: str | None,
) -> list[str]:
    """What the resume would do instead. ``upstream`` counts the changes upstream of the resume point
    (``None`` = unknown: a trace without per-step identity)."""
    body = []
    if upstream is None:
        effect = (
            "so an edit to them would not take effect"
            if hash_known
            else "so an edit to them, if any, would not take effect"
        )
    elif upstream:
        effect = "so that edit would not take effect" if upstream == 1 else "so those edits would not take effect"
    else:
        effect = ""
    if effect:
        body.append(f"Resume re-runs nothing {scope} — it restores the saved outputs of the steps that ran — {effect}.")
    if continuing is not None:
        body.append(
            f"Resume would continue at {_routes_text(continuing[0]) or 'the end of the workflow'} with the saved "
            f"outputs up to and including '{after_node_id}'."
        )
    if approved_edited is not None:
        body.append(f"Resuming would run the edited '{approved_edited}' under that earlier approval.")
    return body


def _stale_suggestions(
    scope: str,
    upstream: int | None,
    hash_known: bool,
    skipped_names: list[str],
    approved_edited: str | None,
    continuing: tuple[list[Route], list[Route]] | None,
) -> list[str]:
    if upstream or (upstream is None and hash_known):
        rerun = "Re-run the workflow from the start so the edit takes effect."
    elif approved_edited is not None and continuing is None:
        rerun = f"Re-run the workflow from the start so '{approved_edited}' asks for approval again."
    else:
        rerun = "Re-run the workflow from the start."
    force = f"Pass --force to resume anyway: steps {scope} keep their saved outputs and are not re-run"
    if skipped_names:
        force += f" ({_quoted(skipped_names)} {'is' if len(skipped_names) == 1 else 'are'} skipped)"
    elif upstream is None:
        force += " (any inserted step is skipped)"
    if approved_edited is not None:
        force += f", and the edited '{approved_edited}' runs under the earlier approval"
    return [rerun, force + "."]


def _route_targets(
    rerouted: dict[str, tuple[list[Route], list[Route]]], new_start: tuple[str, str | None] | None
) -> list[str]:
    """The targets the leads name, in lead order (reroute targets, then the new start step)."""
    return [*(target for now, _ in rerouted.values() for _, target in now), *([new_start[0]] if new_start else [])]


def _rerouted_lead(node_id: str, now: list[Route], before: list[Route], skipped: frozenset[str]) -> str:
    """The "now continues to" lead: names the new targets resume would skip, else says what the step
    led to before (with the route's action when it is not the default)."""
    before_targets = {target for _, target in before}
    never_ran = list(dict.fromkeys(t for _, t in now if t not in before_targets and t in skipped))
    if never_ran:
        them = "it" if len(never_ran) == 1 else "them"
        return f"'{node_id}' now continues to {_quoted(never_ran)}, which never ran — resume would skip {them}."
    if not now:
        return f"'{node_id}' now ends the workflow instead of continuing to {_routes_text(before)}."
    was = _routes_text(before) if before else "ending the workflow"
    return f"'{node_id}' now continues to {_routes_text(now)} instead of {was}."


def _new_start_lead(now: str, before: str | None, skipped: frozenset[str]) -> str:
    if now in skipped:
        return f"The workflow now starts at '{now}', which never ran — resume would skip it."
    return f"The workflow now starts at '{now}' instead of '{before}'."


class ResumeAnswerRequiredError(ResumeSourceError):
    """A paused gate needs its answer — or an answer flag was given where none applies (Task 171).

    Three modes, one refusal family (the shared remediation is "pass the right
    answer flag"): ``missing_answer`` (a paused source resumed without
    ``--approve``/``--choose``), ``wrong_flag`` (the flag doesn't match the gate
    kind), ``not_paused`` (an answer flag on a source that isn't paused at a
    gate). For the paused modes the MESSAGE carries the rendered gate content
    (question + numbered options, or the secret-masked approval preview) — an
    agent must be able to compose the answer from this error alone, without
    re-reading the pause output — and the suggestion carries the exact,
    kind-correct resume command. Rendering reuses ``format_gate_lines`` /
    ``format_resume_answer_command`` (``execution/gate_prompt.py``, the ONE
    render shape across prompt, pause output, and this error); the import is
    lazy at raise time (core → execution precedent: ``core/trace_report.py``).
    """

    _TITLE = "Paused gate needs an answer"

    def __init__(
        self,
        *,
        mode: Literal["missing_answer", "wrong_flag", "not_paused"],
        gate_request: dict[str, Any] | None = None,
        execution_id: str | None = None,
        trace_path: str | None = None,
        node_id: str | None = None,
    ):
        self.mode = mode
        self.gate_request = gate_request
        if mode == "not_paused":
            self._TITLE = "No paused gate to answer"
            super().__init__(
                "This run is not paused at a gate — resume it without --approve/--choose.",
                execution_id=execution_id,
                trace_path=trace_path,
                suggestions=["Retry the same resume command without the answer flag."],
            )
            return
        from pflow.execution.gate_prompt import format_gate_lines, format_resume_answer_command

        request = gate_request or {}
        is_approval = request.get("kind") == GATE_KIND_APPROVAL
        kind_label = "an approval gate" if is_approval else "a decision escalation"
        if mode == "wrong_flag":
            right_flag = "--approve yes|no" if is_approval else "--choose"
            head = (
                f"This run is paused at {kind_label} on step '{node_id}', "
                f"but that flag does not answer it — use {right_flag}."
            )
        else:
            head = f"This run is paused at {kind_label} on step '{node_id}' and needs an answer."
        content = "\n".join(f"  {line}" for line in format_gate_lines(request))
        command = format_resume_answer_command(execution_id or "<execution-id>", request)
        super().__init__(
            f"{head}\n\n{content}" if content else head,
            execution_id=execution_id,
            trace_path=trace_path,
            node_id=node_id,
            suggestions=[f"Answer with: {command}"],
        )

    def to_diagnostics(self) -> list[Diagnostic]:
        diagnostics = super().to_diagnostics()
        context = diagnostics[0].context
        if self.gate_request is not None and context is not None:
            # Same masked-payload policy as GateNotInteractiveError's context["gate"]:
            # secrets don't inform a decision; everything else survives in full.
            # One shared dict-form masking rule (core/gate.masked_gate_dict).
            from pflow.core.gate import masked_gate_dict

            context["gate"] = masked_gate_dict(self.gate_request)
        return diagnostics
