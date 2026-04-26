"""Custom exceptions for pflow."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from pflow.core.diagnostic import LLM_FAILURE_CATEGORY, Diagnostic, Severity
from pflow.core.llm_providers import detect_provider, extract_provider_prefix

# Typed discriminators for LLMCallError subclasses. Carried as Literal so
# typos at construction sites (e.g. ``kind="rate_limt"``) fail mypy at the
# raise site rather than silently falling through to a default branch.
UnknownModelReason = Literal["unknown_name", "missing_prefix"]
MissingApiKeyKind = Literal["missing_key", "lacks_permission"]
LLMTransientKind = Literal["timeout", "rate_limit", "server_error", "connection"]

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
                f"(e.g. 'openai/{self.model}', 'anthropic/claude-sonnet-4-5', "
                f"'gemini/gemini-2.5-flash').",
                "See https://docs.litellm.ai/docs/providers for the full list of supported providers.",
                "Run 'pflow settings llm show' to see your configured defaults.",
            ]
        else:
            # unknown_name: prefix is recognized; the model name doesn't exist there.
            suggestions = [
                "Check the model name against the provider's current model catalogue.",
                "Run 'pflow settings llm show' to see your configured defaults.",
                "See https://docs.litellm.ai/docs/providers for supported models.",
            ]
            # Append "your key supports X" hint when a default is detected.
            # Lazy import keeps llm_config off the exceptions import graph.
            import contextlib

            with contextlib.suppress(Exception):
                # Lazy import — keeps llm_config off the exceptions import graph.
                # Suppressing import errors here is intentional: this hint is
                # nice-to-have, not load-bearing. If llm_config can't be imported
                # for any reason, we silently fall back to the generic suggestions.
                from pflow.core.llm_config import get_default_llm_model

                detected = get_default_llm_model()
                if detected:
                    suggestions.append(f"Your configured API key supports '{detected}'.")

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


class LLMResponseParseError(LLMCallError):
    """Model response could not be parsed against the requested schema.

    Raised by ``parse_structured_response`` when ``output_schema`` is set
    but the model returned text that isn't valid JSON (or doesn't match
    the schema). Treated as deterministic — retrying the same prompt is
    likely to produce the same bad response.
    """

    def to_diagnostics(self) -> list[Diagnostic]:
        # Returns single-element list (PflowError convention).
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Response Parse Failed",
                suggestions=[
                    "Verify the requested 'output_schema' matches what the model can produce.",
                    "Check the raw response in the trace JSON to see what the model actually returned.",
                    "Consider simplifying the schema if the model consistently fails to match it.",
                ],
                source="runtime",
                context=self.diagnostic_context(),
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
