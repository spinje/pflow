"""General-purpose LLM node for text processing.

Interface:
- Reads: shared["prompt"]: str  # Text prompt to send to model
- Reads: shared["system"]: str  # System prompt (optional)
- Writes: shared["response"]: str  # Model's text response
- Writes: shared["llm_usage"]: dict  # Token usage metrics (empty dict {} if unavailable)
- Params: model: str  # Model to use (default: claude-sonnet-4-20250514)
- Params: temperature: float  # Sampling temperature (default: 0.7)
- Params: max_tokens: int  # Max response tokens (optional)
- Actions: default (always)
"""

import sys
from pathlib import Path
from typing import Any

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

import llm

from pocketflow import Node


class LLMNode(Node):
    """
    General-purpose LLM node for text processing.

    Interface:
    - Reads: shared["prompt"]: str  # Text prompt to send to model
    - Reads: shared["system"]: str  # System prompt (optional)
    - Writes: shared["response"]: str  # Model's text response
    - Writes: shared["llm_usage"]: dict  # Token usage metrics (empty dict {} if unavailable)
        - model: str  # Model identifier used
        - input_tokens: int  # Number of input tokens consumed
        - output_tokens: int  # Number of output tokens generated
        - total_tokens: int  # Total tokens (input + output)
        - cache_creation_input_tokens: int  # Tokens used for cache creation
        - cache_read_input_tokens: int  # Tokens read from cache
    - Params: model: str  # Model to use (default: gpt-4o-mini)
    - Params: temperature: float  # Sampling temperature (default: 0.7)
    - Params: max_tokens: int  # Max response tokens (optional)
    - Actions: default (always)
    """

    name = "llm"  # CRITICAL: Required for registry discovery

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        """Initialize the LLM node with retry support."""
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Extract and prepare inputs from shared store with parameter fallback."""
        # Extract from shared store with parameter fallback
        prompt = shared.get("prompt") or self.params.get("prompt")

        if not prompt:
            raise ValueError(
                "LLM node requires 'prompt' in shared store or parameters. "
                "Please ensure previous nodes set shared['prompt'] "
                "or provide --prompt parameter."
            )

        # System also uses fallback pattern
        system = shared.get("system") or self.params.get("system")

        # Temperature with clamping
        temperature = self.params.get("temperature", 0.7)
        temperature = max(0.0, min(2.0, temperature))

        return {
            "prompt": prompt,
            "model": self.params.get("model", "gpt-4o-mini"),  # Default to OpenAI's default model
            "temperature": temperature,
            "system": system,
            "max_tokens": self.params.get("max_tokens"),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute LLM call - NO try/except blocks! Let exceptions bubble up."""
        # Use llm library directly - NO try/except! Let exceptions bubble up
        model = llm.get_model(prep_res["model"])

        kwargs = {"temperature": prep_res["temperature"]}

        # Only add optional parameters if not None
        if prep_res["system"] is not None:
            kwargs["system"] = prep_res["system"]
        if prep_res["max_tokens"] is not None:
            kwargs["max_tokens"] = prep_res["max_tokens"]

        # Let exceptions bubble up for retry mechanism
        response = model.prompt(prep_res["prompt"], **kwargs)

        # CRITICAL: Force evaluation with text()
        text = response.text()

        # Capture usage data (may return None)
        usage_obj = response.usage()

        return {
            "response": text,
            "usage": usage_obj,  # Pass raw object or None
            "model": prep_res["model"],
        }

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store results in shared store."""
        shared["response"] = exec_res["response"]

        # Store usage metrics matching spec structure exactly
        usage_obj = exec_res.get("usage")
        if usage_obj:
            # Extract cache metrics from details if available
            details = getattr(usage_obj, "details", {}) or {}
            cache_creation = details.get("cache_creation_input_tokens", 0)
            cache_read = details.get("cache_read_input_tokens", 0)

            shared["llm_usage"] = {
                "model": exec_res.get("model", "unknown"),
                "input_tokens": usage_obj.input,
                "output_tokens": usage_obj.output,
                "total_tokens": usage_obj.input + usage_obj.output,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            }
        else:
            # Empty dict per spec when usage unavailable
            shared["llm_usage"] = {}

        return "default"  # Always return "default"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> None:
        """Handle errors after all retries exhausted."""
        # Enhanced error messages
        error_msg = str(exc)

        if "UnknownModelError" in error_msg:
            raise ValueError(
                f"Unknown model: {prep_res['model']}. Run 'llm models' to see available models. Original error: {exc}"
            )
        elif "NeedsKeyException" in error_msg:
            raise ValueError(
                f"API key required for model: {prep_res['model']}. "
                f"Set up with 'llm keys set <provider>' or environment variable. "
                f"Original error: {exc}"
            )
        else:
            raise ValueError(
                f"LLM call failed after {self.max_retries} attempts. Model: {prep_res['model']}, Error: {exc}"
            )
