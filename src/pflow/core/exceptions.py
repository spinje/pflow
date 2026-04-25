"""Custom exceptions for pflow."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pflow.core.diagnostic import LLM_FAILURE_CATEGORY, Diagnostic, Severity

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


class CriticalDiscoveryError(PflowError):
    """Raised when a critical discovery call fails and cannot provide meaningful fallback.

    This error indicates discovery should abort immediately as continuing
    would produce nonsensical or invalid results.
    """

    def __init__(self, node_name: str, reason: str, original_error: Exception | None = None):
        self.node_name = node_name
        self.reason = reason
        self.original_error = original_error

        message = f"{node_name} encountered a critical failure: {reason}"
        if original_error:
            message = f"{message}\nOriginal error: {original_error!s}"

        super().__init__(message)


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
      ``InternalServerError``. Marker subclass — its presence signals
      "the Node retry loop should retry; smart_filter / discovery callers
      should swallow." LLMNode's ``_call_llm`` re-raises it (rather than
      catching like the deterministic subclasses) so the retry loop can
      retry the call.

    Consumers outside a retry loop (registry/discovery callers,
    smart_filter) catch the base ``LLMCallError`` for graceful
    degradation — the umbrella covers every subclass.

    The structured ``model`` attribute (set on every instance) carries the
    model identifier as a typed field instead of embedding it in the
    message. ``to_diagnostics()`` overrides on each subclass produce rich
    Diagnostics with structured context (``error_class``, ``model``,
    ``reason``/``kind``) plus user-facing remediation suggestions — the
    single source of truth for what each error means in pflow.
    """

    def __init__(self, message: str, *, model: str | None = None) -> None:
        super().__init__(message)
        self.model = model

    def to_diagnostics(self) -> list[Diagnostic]:
        # Returns a single-element list (PflowError convention; LLMNode
        # indexes [0]). Subclasses override with richer context + suggestions.
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="LLM Call Failed",
                source="runtime",
                context={
                    "category": LLM_FAILURE_CATEGORY,
                    "error_class": type(self).__name__,
                    "model": self.model,
                },
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

    def __init__(self, message: str, *, model: str | None = None, reason: str = "unknown_name") -> None:
        super().__init__(message, model=model)
        self.reason = reason

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
                context={
                    "category": LLM_FAILURE_CATEGORY,
                    "error_class": type(self).__name__,
                    "model": self.model,
                    "reason": self.reason,
                },
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
        kind: str = "missing_key",
    ) -> None:
        super().__init__(message, model=model)
        self.kind = kind

    def to_diagnostics(self) -> list[Diagnostic]:
        # Returns single-element list (PflowError convention).
        env_var = _derive_env_var_for_model(self.model)
        if self.kind == "lacks_permission":
            suggestions = [
                "Verify the API key has access to this specific model "
                "(some models require explicit access requests on the provider's dashboard).",
                "Check whether your provider tier supports this model.",
                "Try a different model your key is known to support.",
            ]
        else:
            # missing_key
            example_var = env_var or "ANTHROPIC_API_KEY"
            suggestions = [
                f"Set the provider API key as an environment variable (e.g. 'export {example_var}=...').",
                f"Alternatively, run 'pflow settings set-env {example_var} <value>' to store it in pflow settings.",
                "See https://docs.litellm.ai/docs/providers for provider-specific key names "
                "(Bedrock, Azure, Vertex, etc.).",
            ]

        ctx: dict[str, Any] = {
            "category": LLM_FAILURE_CATEGORY,
            "error_class": type(self).__name__,
            "model": self.model,
            "kind": self.kind,
        }
        if env_var is not None:
            ctx["env_var"] = env_var

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
                context={
                    "category": LLM_FAILURE_CATEGORY,
                    "error_class": type(self).__name__,
                    "model": self.model,
                    "provider_message": str(self),
                },
                see_also=["llm"],
            )
        ]


class LLMTransientError(LLMCallError):
    """Transient LLM provider error (timeout, rate limit, 5xx).

    Marker subclass — no extra attributes. Its presence signals "the Node
    retry loop should retry this; consumers outside a retry loop should
    swallow it gracefully." LLMNode's ``_call_llm`` re-raises this rather
    than catching it (unlike the deterministic ``LLMCallError`` subclasses)
    so the retry loop sees an exception and can retry.

    Translated from LiteLLM's ``Timeout``, ``RateLimitError``, and
    ``InternalServerError`` at the adapter seam (``llm_client.complete``).
    Note: this is distinct from pflow's inner-pool ``FuturesTimeoutError``
    (the LLMNode-level timeout that orphan-protects the worker thread).
    """


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
                context={
                    "category": LLM_FAILURE_CATEGORY,
                    "error_class": type(self).__name__,
                    "model": self.model,
                },
                see_also=["llm"],
            )
        ]


def _derive_env_var_for_model(model: str | None) -> str | None:
    """Best-effort derivation of the provider env-var name from a model identifier.

    Used by ``MissingApiKeyError.to_diagnostics()`` to surface the
    expected env-var name. Returns None when the prefix is unrecognized
    or absent — caller falls back to a generic example.
    """
    if not model:
        return None
    name = model.lower()
    if name.startswith("anthropic/") or name.startswith("claude-"):
        return "ANTHROPIC_API_KEY"
    if name.startswith("openai/") or name.startswith("gpt-") or name.startswith("o1") or name.startswith("o3"):
        return "OPENAI_API_KEY"
    if name.startswith("gemini/") or name.startswith("gemini-"):
        return "GEMINI_API_KEY"
    return None


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
