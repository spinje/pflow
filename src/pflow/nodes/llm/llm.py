"""General-purpose LLM node for text processing."""

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any

import litellm.exceptions

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pflow.core.exceptions import LLMCallError
from pflow.core.llm_client import Attachment, TraceHook, complete, enrich_llm_usage_with_cost
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
    - Params: model_options: dict  # Additional provider-specific model options passed as kwargs (optional, overrides reasoning params if keys overlap)
    - Writes: shared["response"]: str|dict  # Text (str), parsed JSON (dict) when output_schema is set, or raw text on parse failure
    - Writes: shared["error"]: str  # Error message if LLM call or JSON parsing failed
    - Writes: shared["llm_usage"]: dict  # Token usage metrics (empty dict {} if unavailable)
        - model: str  # Model identifier used
        - input_tokens: int  # Number of input tokens consumed
        - output_tokens: int  # Number of output tokens generated
        - total_tokens: int  # Total tokens (input + output)
        - cache_creation_input_tokens: int  # Tokens used for cache creation
        - cache_read_input_tokens: int  # Tokens read from cache
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
                'Use template syntax like "prompt": "${previous_node.output}" '
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

        prep_res = {
            "prompt": prompt,
            "model": self.params.get("model", "gemini-3-flash-preview"),  # Default to reliable JSON-capable model
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
        collector = shared.get("_trace_collector")
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

        # The adapter handles the PATTERN EXCEPTION (deterministic
        # BadRequestError → error-marked response, no retry burned).
        # See pflow.core.llm_client.complete docstring.
        try:
            adapter_response = complete(
                model=prep_res["model"],
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
        except LLMCallError as e:
            # PATTERN EXCEPTION: deterministic provider error (bad params,
            # bad model, schema rejection). Convert to error-marked output
            # at this single boundary so the Node retry loop sees a normal
            # return and doesn't burn three attempts. The adapter raised a
            # typed exception precisely so this conversion lives here, with
            # the one consumer that needs it, not inside the adapter.
            return {
                "response": "",
                "error": str(e),
                "model": prep_res["model"],
                "usage": {},
                "status": "error",
            }

        return {
            "response": adapter_response.text,
            "usage": adapter_response.usage,
            "model": adapter_response.model,
            "has_schema": adapter_response.has_schema,
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
            # is still running model.prompt(), so retry would create duplicate
            # in-flight API calls (wasting money and adding rate-limit pressure).
            return {
                "response": "",
                "error": (
                    f"LLM call timed out after {timeout}s. "
                    f"Model: {prep_res['model']}. "
                    f"Increase timeout or check API connectivity."
                ),
                "model": prep_res["model"],
                "usage": {},
                "status": "error",
            }
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store results in shared store."""
        # Check for error first
        if isinstance(exec_res, dict) and exec_res.get("status") == "error":
            shared["error"] = exec_res.get("error", "Unknown error")
            shared["response"] = ""
            shared["llm_usage"] = {}
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
            }
            # Adapter populates cost_usd from LiteLLM's response_cost. Carry it
            # through if present so enrich_llm_usage_with_cost can no-op.
            if "cost_usd" in usage_dict:
                llm_usage["cost_usd"] = usage_dict["cost_usd"]
            enrich_llm_usage_with_cost(llm_usage)
            shared["llm_usage"] = llm_usage
        else:
            # Empty dict per spec when usage unavailable
            shared["llm_usage"] = {}

        # Parse response — schema mode or plain text
        if exec_res["has_schema"]:
            try:
                shared["response"] = json.loads(raw_response)
            except json.JSONDecodeError as e:
                # Preserve raw response for downstream fallback parsing
                shared["response"] = raw_response
                shared["error"] = f"Structured output JSON parse failed: {e}"
                return "error"
        else:
            # Unstructured output: strip code block fences (LLM transport artifact), keep as string
            shared["response"] = self._strip_code_block(raw_response)

        return "default"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle errors after all retries exhausted."""
        error_msg = str(exc)

        # Timeout check first — isinstance is more reliable than string matching
        if isinstance(exc, (TimeoutError, FuturesTimeoutError, litellm.exceptions.Timeout)):
            timeout = prep_res.get("timeout", 120)
            error_detail = (
                f"LLM call timed out after {timeout}s. "
                f"Model: {prep_res['model']}. "
                f"Increase timeout or check API connectivity."
            )
        elif isinstance(exc, litellm.exceptions.NotFoundError):
            # Was UnknownModelError under the llm library — model exists but
            # provider doesn't recognize it.
            from pflow.core.llm_config import get_default_llm_model

            detected_model = get_default_llm_model()
            if detected_model:
                error_detail = (
                    f"Unknown model: {prep_res['model']}. "
                    f"Tip: Your API key supports '{detected_model}'. "
                    f"See https://docs.litellm.ai/docs/providers for valid model strings, "
                    f"or run 'pflow settings llm show' to see your configured defaults."
                )
            else:
                error_detail = (
                    f"Unknown model: {prep_res['model']}. "
                    f"See https://docs.litellm.ai/docs/providers for valid model strings, "
                    f"or run 'pflow settings llm show' to see your configured defaults."
                )
        elif isinstance(exc, litellm.exceptions.AuthenticationError):
            # Was NeedsKeyException under the llm library — wrong or missing key.
            error_detail = (
                f"API key required for model: {prep_res['model']}. "
                f"Set the appropriate environment variable "
                f"(e.g., ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY) "
                f"or run 'pflow settings set-env <KEY> <value>'."
            )
        elif isinstance(exc, litellm.exceptions.BadRequestError) and "LLM Provider NOT provided" in error_msg:
            # Unknown provider prefix — looks like an unknown model to the user.
            error_detail = (
                f"Unknown model/provider: {prep_res['model']}. "
                f"Use a provider prefix (e.g., 'anthropic/claude-sonnet-4-5', "
                f"'openai/gpt-4o-mini', 'gemini/gemini-2.5-flash')."
            )
        else:
            error_detail = (
                f"LLM call failed after {self.max_retries} attempts. Model: {prep_res['model']}. Error: {error_msg}"
            )

        # Return error dict instead of raising
        return {
            "response": "",
            "error": error_detail,
            "model": prep_res.get("model", "unknown"),
            "usage": {},
            "status": "error",
        }
