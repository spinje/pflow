"""General-purpose LLM node for text processing."""

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pflow.core.exceptions import LLMCallError, LLMTransientError
from pflow.core.llm_client import Attachment, TraceHook, complete
from pflow.core.llm_reasoning_map import (
    DEFAULT_MAX_TOKENS_BASE,
    EFFORT_RATIOS,
    map_reasoning_options,
)
from pflow.core.node import Node

logger = logging.getLogger(__name__)

# Re-exported for backward compatibility with code that imported these names
# from pflow.nodes.llm.llm. The canonical home is pflow.core.llm_reasoning_map.
__all__ = [
    "DEFAULT_MAX_TOKENS_BASE",
    "EFFORT_RATIOS",
    "LLMNode",
]


def _error_dict_from_exception(exc: LLMCallError) -> dict[str, Any]:
    """Build the standard error-dict shape from a typed LLMCallError.

    Reads the rich diagnostic produced by ``exc.to_diagnostics()`` — which
    is the single source of truth for the user-facing message and the
    structured context (``error_class``, ``model``, ``reason``/``kind``).
    The ``_diagnostic_context`` field is lifted by
    ``executor_service._enrich_error_from_node_output`` so the runtime
    Diagnostic that reaches JSON output carries the same structured fields
    the override produced — no duplication, no drift.

    Suggestions from the override are joined into the ``error`` prose so
    text-mode consumers (CLI summaries, log-style readers) get the
    actionable remediation in the same string they'd see today.
    """
    diagnostic = exc.to_diagnostics()[0]
    message = diagnostic.message
    if diagnostic.suggestions:
        message = message + "\n\n" + "\n".join(diagnostic.suggestions)
    return {
        "response": "",
        "error": message,
        "error_class": type(exc).__name__,
        "model": exc.model or "unknown",
        "usage": {},
        "status": "error",
        "_diagnostic_context": dict(diagnostic.context or {}),
    }


def _error_dict_for_timeout(model: str, message: str) -> dict[str, Any]:
    """Build the error-dict for the in-thread FuturesTimeoutError path.

    Distinct from LiteLLM's ``Timeout`` (which is now ``LLMTransientError``).
    This path fires only for the inner ``ThreadPoolExecutor`` per-call
    timeout — when the LiteLLM call itself hung beyond ``timeout`` seconds.
    The orphan worker thread is still holding the connection open, so we
    do NOT retry (would create duplicate in-flight requests).
    """
    from pflow.core.diagnostic import LLM_FAILURE_CATEGORY

    return {
        "response": "",
        "error": message,
        "error_class": "TimeoutError",
        "model": model,
        "usage": {},
        "status": "error",
        "_diagnostic_context": {
            "category": LLM_FAILURE_CATEGORY,
            "error_class": "TimeoutError",
            "model": model,
            "kind": "pool_timeout",
        },
    }


def _error_dict_for_generic_failure(model: str, exc: Exception, attempts: int) -> dict[str, Any]:
    """Build the error-dict for ``exec_fallback`` after retry exhaustion.

    Catches non-deterministic failures that escaped ``_call_llm`` AND any
    ``LLMTransientError`` whose retry budget was exhausted.
    """
    from pflow.core.diagnostic import LLM_FAILURE_CATEGORY

    if isinstance(exc, LLMTransientError):
        diagnostic = exc.to_diagnostics()[0]
        message = f"LLM call failed after {attempts} attempts. Model: {model}. Error: {exc}"
        context = dict(diagnostic.context or {})
        context["kind"] = "retry_exhausted"
        context["transient_kind"] = exc.kind
        return {
            "response": "",
            "error": message,
            "error_class": type(exc).__name__,
            "model": model,
            "usage": {},
            "status": "error",
            "_diagnostic_context": context,
        }

    if "timed out" in str(exc).lower():
        message = (
            f"LLM call timed out after {attempts} attempts. Model: {model}. Increase timeout or check API connectivity."
        )
        error_class = "TimeoutError"
        kind = "retry_exhausted_timeout"
    else:
        message = f"LLM call failed after {attempts} attempts. Model: {model}. Error: {exc}"
        error_class = type(exc).__name__
        kind = "retry_exhausted"
    return {
        "response": "",
        "error": message,
        "error_class": error_class,
        "model": model,
        "usage": {},
        "status": "error",
        "_diagnostic_context": {
            "category": LLM_FAILURE_CATEGORY,
            "error_class": error_class,
            "model": model,
            "kind": kind,
        },
    }


class LLMNode(Node):
    """
    General-purpose LLM node for text processing and AI reasoning or data transformation.
    When using this node, you should always only have it do ONE task. If you need to do multiple AI tasks, you should use multiple LLM nodes.
    For example, if you need to create both unstructured and structured data, you should use two different LLM nodes not one node that does both.

    Interface:
    - Params: prompt: str  # Text prompt to send to model
    - Params: system: str  # System prompt (optional)
    - Params: images: list[str]  # Image URLs or file paths (optional)
    - Params: output_schema: dict  # JSON Schema for structured output (optional)
    - Params: reasoning_effort: str  # Reasoning depth: xhigh/high/medium/low/minimal/none (optional, mapped to provider-specific params)
    - Params: reasoning_max_tokens: int  # Direct reasoning token budget, mutually exclusive with reasoning_effort (optional)
    - Params: model_options: dict  # Additional provider-specific model options passed as kwargs (optional; reasoning keys must use reasoning_effort/reasoning_max_tokens)
    - Writes: shared["response"]: str|dict  # Text (str), parsed JSON (dict) when output_schema is set, or raw text on parse failure
    - Writes: shared["error"]: str  # Error message if LLM call or JSON parsing failed
    - Writes: shared["prompt"]: str  # Rendered prompt actually sent to the model (populated for tracing/audit, including per-item batch traces)
    - Writes: shared["llm_usage"]: dict  # Token usage metrics (empty dict {} if unavailable)
        - model: str  # Model identifier used
        - input_tokens: int  # Number of input tokens consumed
        - output_tokens: int  # Number of output tokens generated
        - total_tokens: int  # Total tokens (input + output)
        - cache_creation_input_tokens: int  # Tokens used for cache creation
        - cache_read_input_tokens: int  # Tokens read from cache
        - thinking_tokens: int  # Reasoning/thinking tokens consumed (0 for non-reasoning models)
        - thinking_budget: int  # Reasoning token budget set on the request (0 when not configured or provider uses categorical levels)
        - cost_usd: float  # Estimated cost in USD (None when LiteLLM has no pricing data — e.g. Ollama, custom endpoints, brand-new models)
    - Params: model: str  # Model to use (optional - always use smart default unless user requests specific model)
    - Params: temperature: float  # Sampling temperature (default: 1.0)
    - Params: max_tokens: int  # Max response tokens (optional)
    - Params: timeout: int  # Execution timeout in seconds for LLM API call (default: 120)
    - Actions: default (success), error (failure)
    """

    name = "llm"  # CRITICAL: Required for registry discovery

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        """Initialize the LLM node with retry support."""
        super().__init__(max_retries=max_retries, wait=wait)

    def _validate_timeout(self) -> float:
        """Extract and validate the timeout parameter."""
        timeout = self.params.get("timeout", 120)
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            raise ValueError(f"Timeout must be a positive number, got {timeout!r}") from None
        if timeout <= 0:
            raise ValueError(f"Timeout must be a positive number, got {timeout}")
        return timeout

    @staticmethod
    def _strip_code_block(response: str) -> str:
        """Strip markdown code block fences from LLM responses.

        LLMs commonly wrap their output in code fences (```json ... ```) as a
        transport artifact. This method strips those fences when the entire
        response is a single code block, returning the inner content as a string.

        Only strips when the response both starts AND ends with code fences
        (after whitespace). Responses with trailing text after the closing
        fence are returned unchanged — we never silently discard content.

        No JSON parsing is performed — the return value is always a string.
        Downstream consumers use the template system (dot notation, type
        coercion) to parse JSON on demand.

        Args:
            response: The raw LLM response string

        Returns:
            The response with outer code block fences stripped, still as a string
        """
        trimmed = response.strip()

        if not trimmed.startswith("```") or not trimmed.endswith("```"):
            return response

        # Find the end of the opening fence line
        first_newline = trimmed.find("\n")
        if first_newline == -1:
            return response

        # Find the closing fence (last occurrence)
        closing = trimmed.rfind("```")
        if closing <= first_newline:
            return response

        # Extract content between fences
        return trimmed[first_newline + 1 : closing].strip()

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Extract and prepare inputs from parameters."""
        # Extract from params (template resolution handles shared store wiring)
        prompt = self.params.get("prompt")

        if not prompt:
            raise ValueError(
                "LLM node requires 'prompt' parameter. "
                "Use template syntax like '- prompt: ${previous_node.output}' "
                "to wire data from other nodes."
            )

        # System prompt from params
        system = self.params.get("system")

        # Temperature with clamping
        temperature = self.params.get("temperature", 1.0)
        temperature = max(0.0, min(2.0, temperature))

        # Process images from params
        images = self.params.get("images", [])

        # Ensure images is a list
        if not isinstance(images, list):
            images = [images]  # Wrap single value in list

        # Build attachments list (typed dataclass; the adapter encodes
        # local paths to data-URLs at the API boundary).
        attachments: list[Attachment] = []
        for img in images:
            if not isinstance(img, str):
                raise TypeError(f"Image must be a string (URL or path), got: {type(img).__name__}")

            # Detect URL vs file path
            if img.startswith(("http://", "https://")):
                attachments.append(Attachment(kind="image_url", value=img))
            else:
                # Image paths are inputs (not workflow assets) — stored verbatim.
                # Relative paths are resolved against the current working
                # directory at file-open time by the adapter (Python's open()
                # semantics). This contrasts with code-block file refs
                # (`code: @./helper.py`) which resolve relative to the workflow
                # file because they're part of the workflow definition.
                path = Path(img)
                if not path.exists():
                    raise ValueError(
                        f"Image file not found: {img}\nPlease ensure the file exists at the specified path."
                    )
                attachments.append(Attachment(kind="image_path", value=str(path)))

        # Validate reasoning_effort early (deterministic error, not worth retrying)
        reasoning_effort = self.params.get("reasoning_effort")
        valid_efforts = {*EFFORT_RATIOS.keys(), "none"}
        if reasoning_effort and reasoning_effort.lower() not in valid_efforts:
            valid_list = ", ".join(sorted(valid_efforts))
            raise ValueError(f"Invalid reasoning_effort: '{reasoning_effort}'. Must be one of: {valid_list}")

        # Model is required. The compiler injects ``model`` for every LLM
        # node (compilation/compiler.py: it either reads the user's value,
        # falls back to settings/auto-detect via ``get_default_workflow_model``,
        # or raises ``CompilationError`` when no source is available). Any
        # path that reaches here without a model has bypassed compilation
        # — typically a unit test that constructs ``LLMNode()`` directly
        # and forgot to set ``model`` in its params. Fail loudly instead
        # of silently substituting a hardcoded default.
        model = self.params.get("model")
        if not model:
            raise ValueError(
                "LLM node requires a 'model' parameter. The compiler injects this from "
                "the workflow YAML, settings.default_model, or auto-detected provider keys; "
                "if you are calling LLMNode directly (e.g. in a unit test), set "
                "'model' explicitly via node.set_params({'model': '<provider>/<model>'})."
            )

        prep_res = {
            "prompt": prompt,
            "model": model,
            "temperature": temperature,
            "system": system,
            "max_tokens": self.params.get("max_tokens"),
            "attachments": attachments,
            "output_schema": self.params.get("output_schema"),
            "reasoning_effort": reasoning_effort,
            "reasoning_max_tokens": self.params.get("reasoning_max_tokens"),
            "model_options": self.params.get("model_options", {}),
            "timeout": self._validate_timeout(),
        }

        # Resolve the per-call trace hook on the engine thread BEFORE
        # exec() submits to the inner ThreadPoolExecutor. The hook is then
        # passed explicitly through the pool boundary as a function arg —
        # unlike the previous monkey-patched lookup which read thread-local
        # state from the worker thread (where it was never registered).
        # See plan: /Users/andfal/.claude/plans/magical-swinging-taco.md
        collector = shared.get("__trace_collector__")
        node_id = getattr(self, "node_id", None)
        if collector is not None and node_id is not None:
            prep_res["_trace_hook"] = collector.get_trace_hook(node_id)

        return prep_res

    def _call_llm(self, prep_res: dict[str, Any], trace_hook: TraceHook | None = None) -> dict[str, Any]:
        """Execute the actual LLM API call. Extracted for timeout wrapping.

        The ``trace_hook`` is captured by ``exec()`` from ``prep_res`` BEFORE
        the inner pool.submit, then passed through the pool boundary as an
        explicit arg. Default ``None`` keeps the function callable directly
        in tests that don't care about tracing.
        """
        reasoning_kwargs = map_reasoning_options(
            prep_res["model"],
            prep_res.get("reasoning_effort"),
            prep_res.get("reasoning_max_tokens"),
            prep_res.get("max_tokens"),
        )

        # The adapter raises typed LLMCallError subclasses for deterministic
        # provider failures and LLMTransientError for transient ones. We
        # catch the deterministic ones at this single boundary (preventing
        # the Node retry loop from burning three attempts on a permanent
        # failure) and re-raise transient ones so the retry loop fires.
        # The exception's own to_diagnostics() override produces the rich
        # user-facing message + structured context — the LLMNode just
        # consumes it. See pflow.core.llm_client.complete docstring and
        # pflow.core.exceptions for the typed hierarchy.
        model = prep_res["model"]
        try:
            adapter_response = complete(
                model=model,
                prompt=prep_res["prompt"],
                system=prep_res["system"],
                temperature=prep_res["temperature"],
                max_tokens=prep_res["max_tokens"],
                attachments=prep_res["attachments"] or None,
                schema=prep_res["output_schema"],
                reasoning_kwargs=reasoning_kwargs,
                model_options=prep_res.get("model_options") or None,
                timeout=prep_res.get("timeout"),
                trace_hook=trace_hook,
            )
        except LLMTransientError:
            # Transient: re-raise so the Node retry loop catches it and
            # retries. exec_fallback will fire if all retries are exhausted.
            raise
        except LLMCallError as e:
            # Deterministic: catch at single boundary, build error dict from
            # the exception's own to_diagnostics() override. Covers
            # UnknownModelError, MissingApiKeyError, InvalidRequestError, and
            # any future deterministic subclass automatically.
            return _error_dict_from_exception(e)

        return {
            "response": adapter_response.text,
            "usage": adapter_response.usage,
            "model": adapter_response.model,
            "has_schema": adapter_response.has_schema,
            # Pass adapter warnings through to post() so they can be lifted
            # into shared["__warnings__"] for JSON-output visibility.
            "warnings": adapter_response.warnings,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute LLM call with timeout protection."""
        timeout = prep_res.get("timeout", 120)
        # Capture the trace hook on the engine thread (resolved by prep)
        # BEFORE handing off to the pool. The hook is a closure over the
        # collector + node_id — passing it as an explicit arg makes it
        # survive the thread boundary regardless of which worker runs the
        # call. (The previous design tried to look up the active collector
        # via thread-local state on the worker thread, which always failed
        # because the worker wasn't the registered thread.)
        trace_hook = prep_res.get("_trace_hook")

        # IMPORTANT: Do NOT use `with ThreadPoolExecutor` — its __exit__ calls
        # shutdown(wait=True) which blocks until the thread finishes, defeating
        # the timeout for stuck API calls (same pattern as python_code.py).
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._call_llm, prep_res, trace_hook)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            logger.warning(
                f"LLM call timed out after {timeout}s, orphan thread may continue running",
                extra={"model": prep_res["model"], "timeout": timeout},
            )
            # Return error dict instead of raising — prevents PocketFlow retry.
            # Retrying timeouts is harmful: the orphan thread from this attempt
            # is still running the API call, so retry would create duplicate
            # in-flight requests (wasting money and adding rate-limit pressure).
            # Distinct from LiteLLM's Timeout (now LLMTransientError) — that
            # path does retry; this one explicitly does not.
            return _error_dict_for_timeout(
                prep_res["model"],
                f"LLM call timed out after {timeout}s. "
                f"Model: {prep_res['model']}. "
                f"Increase timeout or check API connectivity.",
            )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store results in shared store."""
        # Surface the rendered prompt for tracing/audit. Critical for per-item
        # batch traces: WorkflowTraceCollector keys llm_prompts by node_id only,
        # so parallel batch workers all overwrite the same slot. The batch
        # executor's _capture_item_trace falls back to node_output["prompt"]
        # for per-item visibility — populating it here is the seam.
        rendered_prompt = prep_res.get("prompt")
        if isinstance(rendered_prompt, str):
            shared["prompt"] = rendered_prompt

        # Check for error first
        if isinstance(exec_res, dict) and exec_res.get("status") == "error":
            self._propagate_error_to_shared(shared, exec_res)
            return "error"  # Return error action so workflow error handling can respond

        raw_response = exec_res["response"]

        # Store usage metrics BEFORE response parsing — ensures usage is
        # captured even if output_schema JSON parsing fails below.
        # The adapter normalizes usage into a stable dict shape (matching keys
        # below), so post() reads them directly with no object-path fallback.
        usage_dict = exec_res.get("usage")
        if usage_dict:
            llm_usage = {
                "model": usage_dict.get("model", exec_res.get("model", "unknown")),
                "input_tokens": usage_dict.get("input_tokens", 0) or 0,
                "output_tokens": usage_dict.get("output_tokens", 0) or 0,
                "total_tokens": usage_dict.get("total_tokens", 0) or 0,
                "cache_creation_input_tokens": usage_dict.get("cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": usage_dict.get("cache_read_input_tokens", 0) or 0,
                "thinking_tokens": usage_dict.get("thinking_tokens", 0) or 0,
                "thinking_budget": usage_dict.get("thinking_budget", 0) or 0,
            }
            # Adapter populates cost_usd from LiteLLM's response_cost (None
            # when LiteLLM has no pricing data for the model).
            if "cost_usd" in usage_dict:
                llm_usage["cost_usd"] = usage_dict["cost_usd"]
            shared["llm_usage"] = llm_usage
        else:
            # Empty dict per spec when usage unavailable
            shared["llm_usage"] = {}

        # Surface adapter warnings (e.g. empty-response trap on reasoning
        # models) into __warnings__ so JSON consumers see them and the
        # workflow status shifts to DEGRADED. setdefault routes __*__ keys
        # to root via the NamespacedSharedStore proxy contract; subscript
        # write hits the returned root dict. (See namespaced_store.py
        # __setitem__ rules — direct write precedent at batch_executor.py
        # ~812-814.) Each warning is a dict with `kind`/`text`/`context`.
        # Consumers normalize it with core.diagnostic.normalize_runtime_warning
        # so legacy string warnings and structured LLM warnings can coexist.
        warnings_list = exec_res.get("warnings") or []
        # node_id is a compiler-set dynamic attribute (compilation/compiler.py:299).
        node_id = getattr(self, "node_id", None)
        if warnings_list and node_id is not None:
            # In v1 the adapter emits at most one warning per call. If a
            # future case needs multiple, change the contract to a list value.
            shared.setdefault("__warnings__", {})[node_id] = warnings_list[0]

        # Parse response — schema mode or plain text. Schema mode goes
        # through json.loads first (today's contract); LLMResponseParseError
        # would also be raisable here in a future version that uses
        # parse_structured_response, but right now LLMNode's schema path is
        # the inline json.loads. We catch the typed exception to surface
        # error_class consistently with the _call_llm path.
        if exec_res["has_schema"]:
            try:
                shared["response"] = json.loads(raw_response)
            except json.JSONDecodeError as e:
                # Build the same error dict shape as _call_llm so the runtime
                # path produces the same structured Diagnostic. Use
                # LLMResponseParseError so the override produces the right
                # remediation suggestions.
                from pflow.core.exceptions import LLMResponseParseError

                err = LLMResponseParseError(
                    f"Structured output JSON parse failed: {e}",
                    model=exec_res.get("model"),
                )
                error_dict = _error_dict_from_exception(err)
                # Preserve raw response for downstream fallback parsing —
                # contract preserved from the previous behavior. Usage was
                # captured above (the call succeeded; only parsing failed),
                # so preserve_usage=True keeps shared["llm_usage"] intact.
                shared["response"] = raw_response
                self._propagate_error_to_shared(shared, error_dict, response_already_set=True, preserve_usage=True)
                return "error"
        else:
            # Unstructured output: strip code block fences (LLM transport artifact), keep as string
            shared["response"] = self._strip_code_block(raw_response)

        return "default"

    def _propagate_error_to_shared(
        self,
        shared: dict[str, Any],
        exec_res: dict[str, Any],
        *,
        response_already_set: bool = False,
        preserve_usage: bool = False,
    ) -> None:
        """Write the error-dict fields to shared store.

        Single seam for every error path's shared-store mutation:
        ``_call_llm`` typed-exception catches, the FuturesTimeoutError path
        in ``exec``, ``exec_fallback`` after retry exhaustion, and the
        JSON-parse failure path in ``post``. Surfaces the structured fields
        an agent needs to discriminate failure modes:

        - ``shared["error"]`` — the user-facing prose
        - ``shared["error_class"]`` — type(exc).__name__ for programmatic branching
        - ``shared["_diagnostic_context"]`` — full structured context dict
          lifted by ``executor_service._enrich_error_from_node_output`` into
          the runtime Diagnostic that reaches JSON output

        ``preserve_usage=True`` keeps ``shared["llm_usage"]`` intact for
        the JSON-parse path (the call itself succeeded; usage was captured
        before parsing). All other error paths zero it out.
        """
        shared["error"] = exec_res.get("error", "Unknown error")
        error_class = exec_res.get("error_class")
        if error_class is not None:
            shared["error_class"] = error_class
        diagnostic_context = exec_res.get("_diagnostic_context")
        if diagnostic_context:
            shared["_diagnostic_context"] = diagnostic_context
        if not response_already_set:
            shared["response"] = ""
        if not preserve_usage:
            shared["llm_usage"] = {}

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle errors after all retries exhausted.

        Fires for ``LLMTransientError`` whose retry budget was exhausted
        AND any non-deterministic failure that escaped ``_call_llm``.
        Deterministic provider errors (``UnknownModelError``,
        ``MissingApiKeyError``, ``InvalidRequestError``) are caught and
        converted to error dicts at the ``_call_llm`` boundary, so they
        never reach this path.

        The timeout case keeps its specific "Increase timeout or check API
        connectivity" hint because that's the actionable remediation —
        without it, an agent retrying the workflow would just hit the same
        wall. Substring detection avoids re-importing ``litellm.exceptions``
        for what's already a string-typed concept across providers.
        """
        model = prep_res.get("model", "unknown")
        return _error_dict_for_generic_failure(model, exc, self.max_retries)
