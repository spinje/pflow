"""Unified agent node with pluggable coding-agent backends."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from pflow.core.node import Node
from pflow.nodes.agent.backend import AgentBackend, AgentResult
from pflow.nodes.agent.schema_validation import (
    CODEX_PARAMS,
    SHARED_PARAMS,
    TopLevelObjectViolation,
    is_legacy_python_alias_schema,
    top_level_object_violation,
)

logger = logging.getLogger(__name__)
RESTRICTED_DIRECTORIES = ["/", "/etc", "/usr", "/bin", "/sbin", "/lib", "/sys", "/proc"]


class _UnavailableCodexBackend:
    """Phase-1 placeholder that preserves the final backend enum."""

    default_model: str | None = None

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        invalid = sorted(set(params) - (SHARED_PARAMS | CODEX_PARAMS))
        if invalid:
            raise ValueError(f"{invalid[0]!r} is not valid for backend 'codex'")
        raise RuntimeError("codex backend is not available yet; it will be added in Task 177 Phase 3")

    def run(self, prompt: str, options: dict[str, Any]) -> AgentResult:
        raise RuntimeError("codex backend is not available yet; it will be added in Task 177 Phase 3")

    def continuation_options(self, previous: AgentResult, options: dict[str, Any]) -> dict[str, Any] | None:
        return None

    def translate_error(self, exc: Exception, options: dict[str, Any]) -> Exception:
        return exc

    def build_warning_context(self, options: dict[str, Any], result: AgentResult) -> dict[str, Any]:
        return {"node_type": "agent", "backend": "codex"}


class AgentNode(Node):
    """Run an agentic coding backend with optional structured output.

    Interface:
    - Params: backend: str  # Required backend: claude or codex
    - Params: prompt: str  # Prompt to send to the agent (required)
    - Params: inputs: dict  # Named values available to file-backed prompt templates (optional)
    - Params: output_schema: dict  # Top-level object JSON Schema (optional)
    - Params: cwd: str  # Working directory (default: current directory)
    - Params: model: str  # Backend model override (optional)
    - Params: timeout: int  # Execution timeout in seconds (default: 300)
    - Params: system_prompt: str  # Backend system instructions (optional)
    - Params: resume: str  # Session/thread ID to resume (optional)
    - Params: schema_retries: int  # Corrective structured-output retries (default: 1; max: 5)
    - Params: allowed_tools: list  # Claude-only permitted tools (optional)
    - Params: disallowed_tools: list  # Claude-only denied tools (optional)
    - Params: max_turns: int  # Claude-only maximum turns (default: 50)
    - Params: max_thinking_tokens: int  # Claude-only reasoning budget (default: 8000)
    - Params: use_api_key: bool  # Claude-only opt-in to Anthropic API-key billing
    - Params: approval_policy: str  # Codex-only approval policy override (optional)
    - Params: add_dir: list  # Codex-only additional writable directories (optional)
    - Params: profile: str  # Codex-only CLI profile (optional)
    - Params: config: dict  # Codex-only CLI configuration overrides (optional)
    - Params: sandbox: dict|str  # Claude dict or Codex sandbox mode, depending on backend
    - Writes: shared["result"]: str|dict  # Text or parsed structured output
    - Writes: shared["_schema_error"]: str  # Structured-output soft-failure detail (optional)
    - Writes: shared["llm_usage"]: dict  # Normalized token/session metadata
    """

    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1.0)

    @staticmethod
    def _validate_backend(value: Any) -> str:
        if value is None:
            raise ValueError("Agent node requires 'backend'. Valid values: claude, codex.")
        if not isinstance(value, str) or value not in {"claude", "codex"}:
            raise ValueError(f"Invalid backend: {value!r}. Valid values: claude, codex.")
        return value

    @staticmethod
    def _load_backend(name: str) -> AgentBackend:
        if name == "claude":
            from pflow.nodes.agent.claude_backend import ClaudeBackend

            return ClaudeBackend()
        return _UnavailableCodexBackend()

    def _validate_prompt(self, prompt: Any) -> str:
        """Validate prompt parameter."""
        if not prompt:
            raise ValueError(
                "Agent node requires a 'prompt' parameter. "
                "Use template syntax like '- prompt: ${previous_node.output}' "
                "to wire data from other nodes."
            )
        if not isinstance(prompt, str):
            raise TypeError(f"Prompt must be a string, got {type(prompt).__name__}")
        if len(prompt) > 10000:
            raise ValueError(f"Prompt too long ({len(prompt)} chars). Maximum 10000 characters allowed.")
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty or whitespace only.")
        return prompt

    def _validate_schema(self, output_schema: Any) -> dict | None:
        """Validate output_schema parameter.

        - None: no schema requested (returns None)
        - {} (empty): likely a typo; raises with guidance
        - Non-dict: TypeError
        - Legacy Python-alias format: raises with migration guidance
        - Missing or non-"object" top-level type: raises (Anthropic API tool-use limitation)
        - Otherwise: returns as-is; SDK/CLI enforces remaining JSON Schema validity

        The top-level-type check covers both `type: array`/primitives AND schemas
        that omit `type` entirely (top-level oneOf/anyOf/allOf/enum). All four
        return HTTP 400 from the Anthropic API when wrapped as a tool's
        input_schema, verified by Phase 0 (`type: array`/primitives) and the
        oneOf follow-up probe.

        Note on schema typos (e.g. type: "intger"): the Anthropic API silently accepts
        them. Schema typos will result in a soft-fail at runtime (structured_output is
        None) until centralized JSON Schema validation lands in issue #398.
        """
        if output_schema is None:
            return None
        if not isinstance(output_schema, dict):
            raise TypeError(f"output_schema must be a dict (JSON Schema), got {type(output_schema).__name__}")
        if not output_schema:
            raise ValueError(
                "output_schema is an empty dict. Did you forget to populate the schema body? "
                'Use a real JSON Schema (e.g. {"type": "object", "properties": {...}}) '
                "or remove the output_schema field entirely."
            )
        if is_legacy_python_alias_schema(output_schema):
            raise ValueError(
                "output_schema appears to use the legacy Python-alias format "
                '({"field": {"type": "str", ...}}). '
                'Use JSON Schema instead: {"type": "object", "properties": {...}, "required": [...]}. '
                "See docs/reference/nodes/agent.mdx for an example."
            )
        # Claude API limitation (verified in Phase 0 + oneOf follow-up): the SDK wraps
        # output_format as a tool's input_schema, and the API rejects any top-level
        # schema that isn't `type: object` with a 400. The shared predicate covers
        # non-"object" types AND combinator-only schemas (oneOf/anyOf/allOf/enum
        # without a top-level type).
        violation = top_level_object_violation(output_schema)
        if violation is not None:
            raise ValueError(self._top_level_object_error(violation))
        return output_schema

    @staticmethod
    def _top_level_object_error(violation: TopLevelObjectViolation) -> str:
        """Format the "top-level type: object" error with case-specific guidance."""
        wrapper_example = (
            'Wrap in an object, e.g. {"type": "object", '
            '"properties": {"result": <your schema>}, "required": ["result"]}. '
            "(The LLM node has no such restriction.)"
        )
        if violation.kind == "missing_type":
            return (
                "output_schema on agent nodes must declare top-level type: object "
                f"({violation.cause}). Agent backends rejects schemas without a top-level "
                "type:object when the SDK wraps output_format as a tool input_schema — "
                "combinators like oneOf/anyOf/allOf/enum must live inside an object "
                f"wrapper. {wrapper_example}"
            )
        return (
            "output_schema on agent nodes must have top-level type: object "
            f"({violation.cause}). "
            "Agent backends rejects non-object top-level schemas in tool input_schema "
            f"wrappers. {wrapper_example}"
        )

    def _emit_schema_resolved_null_warning(self, shared: dict[str, Any]) -> None:
        """Warn when ``output_schema`` was declared but resolved to ``None``.

        Same channel as soft-fail warnings — ``shared["__warnings__"][node_id]``
        triggers DEGRADED workflow status. Falls back to ``shared["_schema_error"]``
        when no ``node_id`` is bound (test paths, uncompiled nodes) so the signal
        is never fully lost.
        """
        node_id = getattr(self, "node_id", None)
        msg = (
            "output_schema was declared but resolved to None — the agent is running "
            "in free-form mode. If the schema came from an upstream node "
            "(e.g. `output_schema: ${node.schema}`), verify that node produced a "
            "JSON Schema dict. Remove `output_schema:` entirely to silence this warning."
        )
        if node_id is not None:
            shared.setdefault("__warnings__", {})[node_id] = {
                "kind": "agent.output_schema_resolved_to_null",
                "text": msg,
                "context": {"node_type": "agent"},
            }
        else:
            shared.setdefault("_schema_error", msg)

    def _validate_cwd(self, cwd: str | None) -> str:
        """Validate and normalize working directory."""
        if not cwd:
            return os.getcwd()

        cwd = os.path.expanduser(cwd)
        cwd = os.path.abspath(cwd)

        if not os.path.exists(cwd):
            raise ValueError(f"Working directory does not exist: {cwd}")
        if not os.path.isdir(cwd):
            raise ValueError(f"Working directory is not a directory: {cwd}")

        # Check for restricted directories
        normalized_path = os.path.normpath(cwd)
        if normalized_path in RESTRICTED_DIRECTORIES:
            raise ValueError(f"Restricted directory: {cwd}")
        return cwd

    def _validate_timeout(self, timeout: Any) -> int:
        """Validate and convert timeout parameter."""
        default_timeout = 300  # 5 minutes default
        if timeout is None:
            return default_timeout
        try:
            timeout_int = int(timeout)
            if timeout_int < 30 or timeout_int > 3600:
                raise ValueError
            return timeout_int
        except (ValueError, TypeError):
            raise ValueError(f"Invalid timeout: {timeout}. Must be integer between 30 and 3600 seconds.") from None

    def _validate_resume(self, resume: Any) -> str | None:
        """Validate resume session ID parameter."""
        if not resume:
            return None
        if not isinstance(resume, str):
            raise TypeError(f"resume must be a string (session ID), got {type(resume).__name__}")
        return resume

    def _validate_schema_retries(self, schema_retries: Any) -> int:
        """Validate and convert the schema_retries parameter.

        Only the int() conversion is wrapped in try/except; the range checks live
        OUTSIDE it. The previous version re-classified its own ValueErrors by
        substring-matching their messages ("cannot"/"requires"), which silently
        misfires the moment a message is reworded.

        It also deliberately does NOT couple schema_retries to max_turns. The retry
        loop only runs when an output_schema is set, and prep() already enforces
        max_turns >= 2 in that case — so a max_turns check here was redundant for the
        schema path and wrongly rejected valid no-schema nodes that intentionally cap
        an agent to one turn (where the retry would never fire).

        Args:
            schema_retries: Schema retry attempts parameter (None → default of 1)

        Returns:
            Validated schema_retries count (0-5)

        Raises:
            ValueError: If not an integer in the range 0-5
        """
        default_schema_retries = 1
        if schema_retries is None:
            return default_schema_retries
        try:
            retries_int = int(schema_retries)
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid schema_retries: {schema_retries!r}. Must be an integer between 0 and 5."
            ) from None
        if retries_int < 0:
            raise ValueError(f"schema_retries cannot be negative (got {retries_int}).")
        if retries_int > 5:
            raise ValueError(f"schema_retries cannot exceed 5 (cap to prevent runaway costs; got {retries_int}).")
        return retries_int

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        backend_name = self._validate_backend(self.params.get("backend"))
        backend = self._load_backend(backend_name)
        prompt = self._validate_prompt(self.params.get("prompt"))
        raw_output_schema = self.params.get("output_schema")
        output_schema = self._validate_schema(raw_output_schema)
        if output_schema is None and "output_schema" in self.params and raw_output_schema is None:
            self._emit_schema_resolved_null_warning(shared)
        model = self.params.get("model")
        if model is None:
            model = backend.default_model
        prepared = {
            "backend": backend_name,
            "prompt": prompt,
            "output_schema": output_schema,
            "cwd": self._validate_cwd(self.params.get("cwd")),
            "model": model,
            "system_prompt": self.params.get("system_prompt", ""),
            "resume": self._validate_resume(self.params.get("resume")),
            "timeout": self._validate_timeout(self.params.get("timeout")),
            "schema_retries": self._validate_schema_retries(self.params.get("schema_retries")),
            "_backend": backend,
        }
        prepared.update(backend.validate_params(self.params))
        logger.info("Prepared agent execution with backend %s for prompt: %s...", backend_name, prompt[:100])
        return prepared

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        backend: AgentBackend = prep_res["_backend"]
        result = backend.run(prep_res["prompt"], prep_res)
        output_schema = prep_res.get("output_schema")
        schema_retries = prep_res.get("schema_retries", 1)
        attempts = 0
        coerced_fields_all: list[str] = []
        retry_usages: list[dict[str, Any]] = []
        conforming = False
        if output_schema is not None and schema_retries > 0:
            if result.structured_output is not None:
                coerced, conforming, coerced_fields = self._coerce_structured_output(
                    result.structured_output, output_schema
                )
                result.structured_output = coerced
                coerced_fields_all.extend(coerced_fields)
            while not conforming and attempts < schema_retries:
                continuation = backend.continuation_options(result, prep_res)
                if continuation is None:
                    logger.warning("Cannot retry schema mismatch: no session_id available")
                    break
                attempts += 1
                corrective_prompt = (
                    "Your previous response did not produce output matching the required schema. "
                    f"Reply with ONLY a JSON object matching this schema:\n\n{json.dumps(output_schema, indent=2)}\n\n"
                    "No prose before or after. Only the JSON object."
                )
                try:
                    retry_result = backend.run(corrective_prompt, continuation)
                    outgoing = self._usage_record_from(result, prep_res.get("model"))
                    if outgoing:
                        retry_usages.append(outgoing)
                    result = retry_result
                    if result.structured_output is not None:
                        coerced, conforming, coerced_fields = self._coerce_structured_output(
                            result.structured_output, output_schema
                        )
                        result.structured_output = coerced
                        coerced_fields_all.extend(coerced_fields)
                    else:
                        conforming = False
                except Exception as exc:
                    logger.warning("Schema retry attempt %d failed: %s. Keeping original result.", attempts, exc)
                    conforming = False
                    break
        exec_res = {
            "result_text": result.result_text,
            "tool_uses": result.tool_uses,
            "metadata": result.metadata,
            "progress_events": result.progress_events,
            "structured_output": result.structured_output,
            "is_error": result.is_error,
            "error_text": result.error_text,
            "retry_metadata": {"attempts": attempts, "coerced_fields": coerced_fields_all, "conforming": conforming},
        }
        if retry_usages:
            exec_res["retry_usages"] = retry_usages
        exec_res["warning_context"] = backend.build_warning_context(prep_res, result)
        return exec_res

    @staticmethod
    def _usage_record_from(result: AgentResult, model: str | None) -> dict[str, Any] | None:
        metadata = result.metadata
        if not metadata.get("usage_available"):
            return None
        return {
            "input_tokens": metadata.get("input_tokens", 0) or 0,
            "uncached_input_tokens": metadata.get("uncached_input_tokens", 0) or 0,
            "cache_creation_input_tokens": metadata.get("cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": metadata.get("cache_read_input_tokens", 0) or 0,
            "input_token_accounting": metadata.get("input_token_accounting"),
            "output_tokens": metadata.get("output_tokens", 0) or 0,
            "cost_usd": metadata.get("cost_usd"),
            "duration_ms": metadata.get("duration_ms"),
            "num_turns": metadata.get("num_turns"),
            "session_id": metadata.get("session_id"),
            "model": model,
        }

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        self._store_results(shared, prep_res, exec_res, getattr(self, "node_id", None))
        return "default"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> None:
        backend: AgentBackend = prep_res["_backend"]
        raise backend.translate_error(exc, prep_res) from None

    @staticmethod
    def _coerce_structured_output(  # noqa: C901 - Legitimate complexity for multi-type coercion
        structured_output: Any, schema: dict[str, Any]
    ) -> tuple[dict[str, Any], bool, list[str]]:
        """Coerce scalar fields in structured output to match schema types.

        This handles Shape B failures where the agent returns structurally-valid
        output but a scalar field has the wrong type (e.g., {"continue": "false"}
        for a declared boolean). Applies canonical coercion only:
        - boolean: "true"/"false" (case-insensitive, stripped) → True/False
        - integer/number: numeric strings ("3", "3.0") → int/float
        - string: non-string scalar → str()

        Args:
            structured_output: The output to coerce (must be a dict)
            schema: JSON Schema dict with 'properties' and optionally 'required'

        Returns:
            Tuple of (coerced_output, conforming, coerced_fields):
            - coerced_output: New dict with coerced scalar values
            - conforming: True if all top-level scalar types match the schema AND every
              enum/const constraint is satisfied
            - coerced_fields: List of field names that were coerced

        Edge cases (defensive — coerce nothing, never raise):
        - Schema missing 'properties' → unconstrained object: conforming as-is, no coercion
        - Nested/array fields → not coerced; enum/const on them is still checked
        - Extra fields (not in schema) → ignore
        - Missing required fields → mark as non-conforming
        - enum / const → value must be in the allowed set / equal the const, else non-conforming
        - type: ["string", "null"] → coerce only if result matches after coercion
        """
        # Guard: structured_output must be a dict
        if not isinstance(structured_output, dict):
            return structured_output, False, []

        # An object schema without a 'properties' dict is unconstrained (JSON Schema
        # permits it): there are no declared scalar fields to coerce or judge, so a dict
        # output conforms as-is. Returning False here would wrongly mark valid generic-object
        # output non-conforming, trigger a pointless retry, and then drop it to raw text. The
        # non-dict guard above still rejects a genuinely wrong-shaped (non-dict) output.
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return structured_output, True, []

        required = schema.get("required", [])
        coerced = structured_output.copy()  # Shallow copy at top level
        coerced_fields = []
        all_conform = True

        for field_name, field_schema in properties.items():
            if not isinstance(field_schema, dict):
                continue

            runtime_value = coerced.get(field_name)
            declared_type = field_schema.get("type")

            # Missing required field → non-conforming (cannot coerce what isn't there)
            if field_name not in coerced and field_name in required:
                all_conform = False
                continue

            # Field not present and not required → skip
            if field_name not in coerced:
                continue

            # Handle type as array (e.g., ["string", "null"])
            type_list = (
                [declared_type]
                if isinstance(declared_type, str)
                else (declared_type if isinstance(declared_type, list) else [])
            )

            # Only recognized SCALAR types are coerced (v1). A field whose declared type is
            # array/object/unknown is accepted as-is — we never reject the whole output for a
            # non-scalar field we don't coerce (a genuine nested mismatch is a Shape-A soft-fail
            # the retry handles). Without this guard, ANY schema with an array/object field would
            # be marked non-conforming and the valid output dropped to a raw-string soft-fail.
            is_scalar_field = any(t in ("boolean", "integer", "number", "string") for t in type_list)

            # If "null" is in type list and runtime is None, accept as conforming
            if (None in type_list or "null" in type_list) and runtime_value is None:
                continue  # Conforming

            # Try to coerce for each type in the list
            coerced_value = runtime_value
            coercion_succeeded = False

            for target_type in type_list:
                if target_type == "null":
                    continue  # Already handled above

                # Boolean coercion
                if target_type == "boolean":
                    if isinstance(runtime_value, bool):
                        coercion_succeeded = True
                        break
                    if isinstance(runtime_value, str):
                        normalized = runtime_value.strip().lower()
                        if normalized == "true":
                            coerced_value = True
                            coercion_succeeded = True
                            break
                        elif normalized == "false":
                            coerced_value = False
                            coercion_succeeded = True
                            break

                # Integer coercion
                elif target_type == "integer":
                    if isinstance(runtime_value, int) and not isinstance(runtime_value, bool):
                        coercion_succeeded = True
                        break
                    # Coerce float to int if it's an integer value (e.g., 5.0 → 5)
                    if isinstance(runtime_value, float) and runtime_value.is_integer():
                        coerced_value = int(runtime_value)
                        coercion_succeeded = True
                        break
                    if isinstance(runtime_value, str):
                        try:
                            # Accept "3" or "3.0" as integers
                            float_val = float(runtime_value)
                            if float_val.is_integer():
                                coerced_value = int(float_val)
                                coercion_succeeded = True
                                break
                        except (ValueError, OverflowError):
                            pass

                # Number coercion
                elif target_type == "number":
                    if isinstance(runtime_value, (int, float)) and not isinstance(runtime_value, bool):
                        coercion_succeeded = True
                        break
                    if isinstance(runtime_value, str):
                        try:
                            coerced_value = float(runtime_value)
                            coercion_succeeded = True
                            break
                        except (ValueError, OverflowError):
                            pass

                # String coercion
                elif target_type == "string":
                    if isinstance(runtime_value, str):
                        coercion_succeeded = True
                        break
                    # Coerce non-string scalars to string (but NOT None - that's non-conforming)
                    # Converting None to "None" string is silent corruption
                    if isinstance(runtime_value, (bool, int, float)):
                        coerced_value = str(runtime_value)
                        coercion_succeeded = True
                        break

            # Apply coercion if it succeeded and value/type changed
            # Note: 5 != 5.0 is False (numerically equal), so also check type
            if coercion_succeeded:
                if coerced_value != runtime_value or type(coerced_value) is not type(runtime_value):
                    coerced[field_name] = coerced_value
                    coerced_fields.append(field_name)
            elif is_scalar_field:
                # A recognized scalar field we could NOT coerce → genuinely non-conforming
                # (triggers retry). Non-scalar/unknown fields fall through as conforming, since
                # scalar coercion is the only thing this pass judges in v1.
                all_conform = False

            # enum / const are the common constrained-string patterns (e.g.
            # risk_level: {enum: [...]}). Type coercion alone can't judge them: a value of
            # the right TYPE but outside the allowed set must be non-conforming so the retry
            # can re-prompt. Checked against the post-coercion value. Scope is deliberately
            # enum + const ONLY — this is not a general JSON Schema validator.
            final_value = coerced.get(field_name)
            field_enum = field_schema.get("enum")
            if (isinstance(field_enum, list) and field_enum and final_value not in field_enum) or (
                "const" in field_schema and final_value != field_schema["const"]
            ):
                all_conform = False

        return coerced, all_conform, coerced_fields

    def _store_results(
        self,
        shared: dict[str, Any],
        prep_res: dict[str, Any],
        exec_res: dict[str, Any],
        node_id: str | None,
    ) -> None:
        """Store results in shared store.

        Result placement rules:
        - No schema: shared["result"] = raw text (str)
        - Schema + structured_output present: shared["result"] = parsed JSON
        - Schema + structured_output missing: soft-fail with raw text, _schema_error, and __warnings__
        - is_error=True + structured_output present: structured_output wins; _schema_error
          set as a soft-fail signal and __warnings__ written (when node_id is bound)

        Lifecycle action: post() always returns "default". Soft-fail signals
        (`_schema_error`, `__warnings__`) communicate the issue without
        triggering on-error routing — a workflow's `- on-error:` edge does
        NOT fire on schema misses or SDK soft-errors.
        """
        result_text = exec_res.get("result_text", "")
        structured_output = exec_res.get("structured_output")
        is_error_from_backend = exec_res.get("is_error", False)
        has_schema = prep_res.get("output_schema") is not None
        metadata = exec_res.get("metadata", {})
        tool_uses = exec_res.get("tool_uses", [])
        progress_events = exec_res.get("progress_events", [])
        warning_context = exec_res.get("warning_context", {})

        # Store progress events for trace visibility (if any)
        if progress_events:
            shared["_agent_progress"] = progress_events
            logger.debug(f"Stored {len(progress_events)} progress events for tracing")

        # Backends normalize token and lifecycle fields at their producer boundary.
        if metadata:
            input_tokens = metadata.get("input_tokens", 0) or 0
            output_tokens = metadata.get("output_tokens", 0) or 0
            shared["llm_usage"] = {
                "model": prep_res.get("model"),
                "input_tokens": input_tokens,
                "uncached_input_tokens": metadata.get("uncached_input_tokens", 0) or 0,
                "cache_creation_input_tokens": metadata.get("cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": metadata.get("cache_read_input_tokens", 0) or 0,
                "input_token_accounting": metadata.get("input_token_accounting"),
                "output_tokens": output_tokens,
                "total_tokens": metadata.get("total_tokens", input_tokens + output_tokens) or 0,
                "cost_usd": metadata.get("cost_usd"),
                "duration_ms": metadata.get("duration_ms"),
                "num_turns": metadata.get("num_turns"),
                "session_id": metadata.get("session_id"),
            }
            retry_usages = exec_res.get("retry_usages", [])
            if retry_usages:
                shared["llm_usage"]["retries"] = retry_usages
                logger.debug("Stored %d schema retry attempts in llm_usage", len(retry_usages))
            if metadata.get("cost_usd"):
                logger.info("Agent execution cost: $%s", metadata["cost_usd"])
        else:
            shared["llm_usage"] = {}

        # Store tool usage for trace visibility
        if tool_uses:
            shared["_agent_tools"] = [
                {
                    "name": tool["name"],
                    "input_summary": str(tool.get("input", ""))[:500],  # Truncated for storage
                }
                for tool in tool_uses
            ]
            logger.debug(f"Stored {len(tool_uses)} tool uses for tracing")

        # If no schema, store text directly
        if not has_schema:
            shared["result"] = result_text
            return

        # Extract retry metadata for soft-fail signaling
        retry_metadata = exec_res.get("retry_metadata", {})
        retry_attempts = retry_metadata.get("attempts", 0)
        conforming = retry_metadata.get("conforming", True)  # Default True when no schema or no retries
        validation_attempted = prep_res.get("schema_retries", 1) > 0

        self._store_schema_result(
            shared,
            node_id,
            result_text=result_text,
            structured_output=structured_output,
            is_error_from_backend=is_error_from_backend,
            warning_context=warning_context,
            retry_attempts=retry_attempts,
            conforming=conforming,
            validation_attempted=validation_attempted,
        )

    def _store_schema_result(
        self,
        shared: dict[str, Any],
        node_id: str | None,
        *,
        result_text: str,
        structured_output: Any,
        is_error_from_backend: bool,
        warning_context: dict[str, Any],
        retry_attempts: int = 0,
        conforming: bool = True,
        validation_attempted: bool = False,
    ) -> None:
        """Place result + soft-fail signals on the schema path.

        Branches:
        - structured_output present + no backend error → success (result only).
        - structured_output present + backend error → use structured_output but
          record a soft-fail signal so the backend error isn't silently dropped.
        - structured_output missing → raw text fallback + soft-fail signal.

        Soft-fail signals use ``setdefault("_schema_error", ...)`` (so any
        prior write — like ``_emit_schema_resolved_null_warning`` — wins)
        plus an ``__warnings__[node_id]`` write when ``node_id`` is bound.

        Args:
            retry_attempts: Number of schema retry attempts made (0 = no retries)
            conforming: Whether structured output conforms to schema (Shape B detection)
            validation_attempted: Whether schema retry mode checked structured output
        """
        backend_display = warning_context.get("backend_display", "Agent backend")
        backend_error_details = warning_context.get("backend_error_details", "backend error details")

        # Shape B silent failure: structured_output is present but non-conforming.
        # This can happen after exhausted retries or before any corrective retry when
        # the backend did not return a resumable session.
        if structured_output is not None and validation_attempted and not conforming:
            shared["result"] = result_text
            if retry_attempts > 0:
                kind = "agent.schema_not_satisfied_after_retries"
                msg = (
                    f"Model returned non-conforming structured output after {retry_attempts} "
                    f"{'retry' if retry_attempts == 1 else 'retries'} "
                    "(Shape B: uncoercible scalar types). Raw text stored in result. "
                    "Check JSON Schema type spelling and field values."
                )
            else:
                kind = "agent.schema_not_satisfied"
                msg = (
                    "Model returned non-conforming structured output, but no resumable session was "
                    "available for a corrective retry (Shape B: uncoercible scalar types). "
                    "Raw text stored in result. Check JSON Schema type spelling and field values."
                )
            self._emit_soft_fail_signal(
                shared,
                node_id,
                kind=kind,
                msg=msg,
                warning_context=warning_context,
                retry_attempts=retry_attempts,
            )
            return

        if structured_output is not None:
            shared["result"] = structured_output
            if is_error_from_backend:
                self._emit_soft_fail_signal(
                    shared,
                    node_id,
                    kind="agent.sdk_error_with_structured_output",
                    msg=(
                        f"{backend_display} reported is_error=True but structured_output was produced. "
                        "Using structured_output as result; check provider for partial-response details."
                    ),
                    warning_context=warning_context,
                    retry_attempts=retry_attempts,
                )
            return

        shared["result"] = result_text
        if is_error_from_backend:
            msg = (
                f"{backend_display} reported an error and did not produce structured output. "
                f"Raw text stored in result. Check {backend_error_details} and the output_schema."
            )
            kind = "agent.sdk_error_no_structured_output"
        else:
            # Base message for schema not satisfied
            # If retry was attempted, adjust the kind and message
            if retry_attempts > 0:
                kind = "agent.schema_not_satisfied_after_retries"
                msg = (
                    f"Model did not return structured output matching the schema after {retry_attempts} "
                    f"{'retry' if retry_attempts == 1 else 'retries'}. Raw text stored in result. "
                    "Check JSON Schema type spelling, required fields, and impossible enum/const constraints."
                )
            else:
                kind = "agent.schema_not_satisfied"
                msg = (
                    "Model did not return structured output matching the schema. "
                    "Raw text stored in result. Check JSON Schema type spelling, required fields, "
                    "and impossible enum/const constraints."
                )
        self._emit_soft_fail_signal(
            shared, node_id, kind=kind, msg=msg, warning_context=warning_context, retry_attempts=retry_attempts
        )

    @staticmethod
    def _emit_soft_fail_signal(
        shared: dict[str, Any],
        node_id: str | None,
        *,
        kind: str,
        msg: str,
        warning_context: dict[str, Any],
        retry_attempts: int = 0,
    ) -> None:
        """Centralized soft-fail signaling for structured-output mode.

        Writes ``_schema_error`` (via ``setdefault`` so an earlier writer wins)
        and a structured ``__warnings__[node_id]`` entry when ``node_id`` is
        bound. The ``__warnings__`` entry is what flips workflow status to
        ``DEGRADED``; ``_schema_error`` is the fallback signal that survives
        when ``node_id`` is unbound (test paths).

        Args:
            retry_attempts: Number of schema retry attempts made (0 = no retries)
        """
        shared.setdefault("_schema_error", msg)
        if node_id is not None:
            warning_entry: dict[str, Any] = {
                "kind": kind,
                "text": msg,
                "context": warning_context,
            }
            # Include retry attempts in the warning entry if > 0
            if retry_attempts > 0:
                warning_entry["retry_attempts"] = retry_attempts
            shared.setdefault("__warnings__", {})[node_id] = warning_entry
