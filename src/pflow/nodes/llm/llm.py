"""General-purpose LLM node for text processing."""

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

import llm

from pflow.pocketflow import Node

logger = logging.getLogger(__name__)

# OpenRouter-style effort-to-token-budget ratios
EFFORT_RATIOS: dict[str, float] = {
    "xhigh": 0.95,
    "high": 0.80,
    "medium": 0.50,
    "low": 0.20,
    "minimal": 0.10,
}

# Default base for token budget calculation when max_tokens is not set
DEFAULT_MAX_TOKENS_BASE = 16000


def _map_direct_budget(option_fields: set[str], reasoning_max_tokens: int) -> dict[str, Any]:
    """Map reasoning_max_tokens to provider-specific token budget param."""
    if "thinking_budget" in option_fields:
        kwargs: dict[str, Any] = {"thinking_budget": reasoning_max_tokens}
        if "thinking" in option_fields:
            kwargs["thinking"] = True
        return kwargs
    if "reasoning_max_tokens" in option_fields:
        return {"reasoning_max_tokens": reasoning_max_tokens}
    return {}


def _map_effort(option_fields: set[str], effort: str, max_tokens: Optional[int]) -> dict[str, Any]:
    """Map effort level string to provider-specific reasoning params.

    Provider detection order matters — Anthropic Opus 4.5 has thinking_effort,
    thinking, AND thinking_budget, so thinking_effort must be checked first.
    """
    # Anthropic Opus 4.5 — thinking_effort natively
    if "thinking_effort" in option_fields:
        mapped = {"xhigh": "high", "minimal": "low"}.get(effort, effort)
        return {"thinking_effort": mapped}
    # OpenAI / OpenRouter — reasoning_effort natively
    if "reasoning_effort" in option_fields:
        return {"reasoning_effort": effort}
    # Gemini 3 — thinking_level natively
    if "thinking_level" in option_fields:
        mapped = {"xhigh": "high"}.get(effort, effort)
        return {"thinking_level": mapped}
    # Anthropic older / Gemini 2.5 — needs token budget calculation
    if "thinking_budget" in option_fields:
        base = max_tokens or DEFAULT_MAX_TOKENS_BASE
        ratio = EFFORT_RATIOS.get(effort, 0.50)
        budget = max(min(int(base * ratio), 128000), 1024)
        kwargs: dict[str, Any] = {"thinking_budget": budget}
        if "thinking" in option_fields:
            kwargs["thinking"] = True
        return kwargs
    # Thinking-only (no budget control)
    if "thinking" in option_fields:
        return {"thinking": True}
    return {}


def _map_reasoning_options(
    model: llm.Model,
    reasoning_effort: Optional[str],
    reasoning_max_tokens: Optional[int],
    max_tokens: Optional[int],
) -> dict[str, Any]:
    """Map unified reasoning params to provider-specific model options.

    Follows OpenRouter's approach: introspect the model's Options class
    to determine which params it accepts, then map accordingly.

    Args:
        model: The llm Model instance (with Options class already set)
        reasoning_effort: xhigh/high/medium/low/minimal/none
        reasoning_max_tokens: Direct token budget (mutually exclusive with effort)
        max_tokens: The max response tokens, used as base for budget formula
    """
    if not reasoning_effort and reasoning_max_tokens is None:
        return {}

    option_fields = set(model.Options.model_fields.keys())

    # Direct token budget takes precedence over effort
    if reasoning_max_tokens is not None:
        return _map_direct_budget(option_fields, reasoning_max_tokens)

    effort = reasoning_effort.lower()  # type: ignore[union-attr]

    if effort == "none":
        if "thinking" in option_fields:
            return {"thinking": False}
        if "thinking_budget" in option_fields:
            return {"thinking_budget": 0}
        return {}

    return _map_effort(option_fields, effort, max_tokens)


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
        - cost_usd: float  # Estimated cost in USD (None if model not in pricing table)
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

        # Build attachments list
        attachments = []
        for img in images:
            if not isinstance(img, str):
                raise TypeError(f"Image must be a string (URL or path), got: {type(img).__name__}")

            # Detect URL vs file path
            if img.startswith(("http://", "https://")):
                # URL - let llm library handle validation/fetching
                attachments.append(llm.Attachment(url=img))
            else:
                # File path - validate existence now
                path = Path(img)
                if not path.exists():
                    raise ValueError(
                        f"Image file not found: {img}\nPlease ensure the file exists at the specified path."
                    )
                attachments.append(llm.Attachment(path=str(path)))

        # Validate reasoning_effort early (deterministic error, not worth retrying)
        reasoning_effort = self.params.get("reasoning_effort")
        valid_efforts = {*EFFORT_RATIOS.keys(), "none"}
        if reasoning_effort and reasoning_effort.lower() not in valid_efforts:
            valid_list = ", ".join(sorted(valid_efforts))
            raise ValueError(f"Invalid reasoning_effort: '{reasoning_effort}'. Must be one of: {valid_list}")

        return {
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
            "timeout": self.params.get("timeout", 120),
        }

    def _call_llm(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute the actual LLM API call. Extracted for timeout wrapping."""
        model = llm.get_model(prep_res["model"])

        kwargs = {"stream": False, "temperature": prep_res["temperature"]}

        if prep_res["system"] is not None:
            kwargs["system"] = prep_res["system"]
        if prep_res["max_tokens"] is not None:
            kwargs["max_tokens"] = prep_res["max_tokens"]

        if prep_res["attachments"]:
            kwargs["attachments"] = prep_res["attachments"]

        if prep_res["output_schema"] is not None:
            kwargs["schema"] = prep_res["output_schema"]

        reasoning_kwargs = _map_reasoning_options(
            model,
            prep_res.get("reasoning_effort"),
            prep_res.get("reasoning_max_tokens"),
            prep_res.get("max_tokens"),
        )
        kwargs.update(reasoning_kwargs)

        kwargs.update(prep_res.get("model_options") or {})

        # PATTERN EXCEPTION: try/except in exec() is normally an anti-pattern (prevents
        # retries), but ValidationError from Pydantic Options is deterministic — retrying
        # won't help. We catch it here to avoid 3 wasted attempts on bad model_options.
        # Long-term fix: add NonRetriableError support to PocketFlow's _exec loop (#100).
        try:
            response = model.prompt(prep_res["prompt"], **kwargs)
        except ValidationError as e:
            return {
                "response": "",
                "error": f"Invalid model options for '{prep_res['model']}': {e}",
                "model": prep_res["model"],
                "usage": {},
                "status": "error",
            }

        text = response.text()
        usage_obj = response.usage()

        return {
            "response": text,
            "usage": usage_obj,
            "model": prep_res["model"],
            "has_schema": prep_res["output_schema"] is not None,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute LLM call with timeout protection."""
        timeout = prep_res.get("timeout", 120)

        # IMPORTANT: Do NOT use `with ThreadPoolExecutor` — its __exit__ calls
        # shutdown(wait=True) which blocks until the thread finishes, defeating
        # the timeout for stuck API calls (same pattern as python_code.py).
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._call_llm, prep_res)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            logger.warning(
                f"LLM call timed out after {timeout}s, orphan thread may continue running",
                extra={"model": prep_res["model"], "timeout": timeout},
            )
            raise TimeoutError(f"LLM call timed out after {timeout}s (model: {prep_res['model']})") from None
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
        # captured even if output_schema JSON parsing fails below
        usage_obj = exec_res.get("usage")
        if usage_obj:
            # Handle both object (with .input attribute) and dict (with ["input"] key)
            if isinstance(usage_obj, dict):
                # Dict format (some models return this)
                input_tokens = usage_obj.get("input", usage_obj.get("input_tokens", 0))
                output_tokens = usage_obj.get("output", usage_obj.get("output_tokens", 0))
                # Extract cache metrics from dict
                cache_creation = usage_obj.get("cache_creation_input_tokens", 0)
                cache_read = usage_obj.get("cache_read_input_tokens", 0)
            else:
                # Object format (standard llm library)
                input_tokens = usage_obj.input
                output_tokens = usage_obj.output
                # Extract cache metrics from details if available
                details = getattr(usage_obj, "details", {}) or {}
                cache_creation = details.get("cache_creation_input_tokens", 0)
                cache_read = details.get("cache_read_input_tokens", 0)

            # Ensure tokens are integers (handle None values)
            input_tokens = input_tokens or 0
            output_tokens = output_tokens or 0

            shared["llm_usage"] = {
                "model": exec_res.get("model", "unknown"),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            }
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
        exc_type = type(exc).__name__

        # Timeout check first — isinstance is more reliable than string matching
        if isinstance(exc, (TimeoutError, FuturesTimeoutError)):
            timeout = prep_res.get("timeout", 120)
            error_detail = (
                f"LLM call timed out after {timeout}s. "
                f"Model: {prep_res['model']}. "
                f"Increase timeout or check API connectivity."
            )
        elif exc_type == "UnknownModelError" or "UnknownModelError" in error_msg or "Unknown model" in error_msg:
            # Try to suggest a working model based on configured API keys
            from pflow.core.llm_config import get_default_llm_model

            detected_model = get_default_llm_model()
            if detected_model:
                error_detail = (
                    f"Unknown model: {prep_res['model']}. "
                    f"Tip: Your API key supports '{detected_model}'. "
                    f"Run 'llm models' to see all available models."
                )
            else:
                error_detail = f"Unknown model: {prep_res['model']}. Run 'llm models' to see available models."
        elif exc_type == "NeedsKeyException" or "NeedsKeyException" in error_msg:
            error_detail = (
                f"API key required for model: {prep_res['model']}. "
                f"Set up with 'llm keys set <provider>' or environment variable."
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
