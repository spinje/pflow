"""General-purpose LLM node for text processing.

Interface:
- Reads: shared["prompt"]: str  # Text prompt to send to model
- Reads: shared["system"]: str  # System prompt (optional)
- Reads: shared["images"]: list[str]  # Image URLs or file paths (optional)
- Writes: shared["response"]: Any  # Model's response (auto-parsed JSON or string)
- Writes: shared["llm_usage"]: dict  # Token usage metrics (empty dict {} if unavailable)
- Params: model: str  # Model to use (optional - use default unless user requests specific model)
- Params: temperature: float  # Sampling temperature (default: 1.0)
- Params: max_tokens: int  # Max response tokens (optional)
- Actions: default (always)

Note on model parameter:
    Always use the default model unless the user explicitly requests a specific model.

    In pflow context, the compiler auto-detects the model from:
    1. settings.llm.default_model (if configured)
    2. llm CLI default (llm models default)
    3. Auto-detect from API keys (Anthropic → Gemini → OpenAI)
    If nothing is configured, compilation fails with setup instructions.

    When using this node standalone (outside pflow), falls back to gemini-3-flash-preview.
"""

import json
import sys
from pathlib import Path
from typing import Any, Union

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

import llm

from pocketflow import Node


class LLMNode(Node):
    """
    General-purpose LLM node for text processing and AI reasoning or data transformation.
    When using this node, you should always only have it do ONE task. If you need to do multiple AI tasks, you should use multiple LLM nodes.
    For example, if you need to create both unstructured and structured data, you should use two different LLM nodes not one node that does both.

    Interface:
    - Reads: shared["prompt"]: str  # Text prompt to send to model
    - Reads: shared["system"]: str  # System prompt (optional)
    - Reads: shared["images"]: list[str]  # Image URLs or file paths (optional)
    - Writes: shared["response"]: any  # Model's response (auto-parsed JSON or string)
    - Writes: shared["llm_usage"]: dict  # Token usage metrics (empty dict {} if unavailable)
        - model: str  # Model identifier used
        - input_tokens: int  # Number of input tokens consumed
        - output_tokens: int  # Number of output tokens generated
        - total_tokens: int  # Total tokens (input + output)
        - cache_creation_input_tokens: int  # Tokens used for cache creation
        - cache_read_input_tokens: int  # Tokens read from cache
    - Params: model: str  # Model to use (optional - always use smart default unless user requests specific model)
    - Params: temperature: float  # Sampling temperature (default: 1.0)
    - Params: max_tokens: int  # Max response tokens (optional)
    - Actions: default (always)
    """

    name = "llm"  # CRITICAL: Required for registry discovery

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        """Initialize the LLM node with retry support."""
        super().__init__(max_retries=max_retries, wait=wait)

    @staticmethod
    def parse_json_response(response: str) -> Union[Any, str]:
        """Parse JSON from LLM response if possible.

        Handles:
        - Plain JSON strings
        - JSON wrapped in markdown code blocks
        - Regular text (returns as-is)

        Args:
            response: The raw LLM response string

        Returns:
            Parsed JSON object/array if valid JSON, otherwise original string
        """
        if not isinstance(response, str):
            return response

        trimmed = response.strip()

        # Extract from markdown code blocks if present
        if "```" in trimmed:
            start = trimmed.find("```json") + 7 if "```json" in trimmed else trimmed.find("```") + 3
            end = trimmed.find("```", start)
            if end > start:
                trimmed = trimmed[start:end].strip()

        # Try to parse as JSON
        try:
            return json.loads(trimmed)
        except (json.JSONDecodeError, ValueError):
            # Not valid JSON, return original string
            return response

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
        temperature = self.params.get("temperature", 1.0)
        temperature = max(0.0, min(2.0, temperature))

        # Process images with parameter fallback
        # Use explicit key check to handle empty list correctly
        images = shared.get("images") if "images" in shared else self.params.get("images", [])

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

        return {
            "prompt": prompt,
            "model": self.params.get("model", "gemini-3-flash-preview"),  # Default to reliable JSON-capable model
            "temperature": temperature,
            "system": system,
            "max_tokens": self.params.get("max_tokens"),
            "attachments": attachments,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute LLM call - NO try/except blocks! Let exceptions bubble up."""
        # Use llm library directly - NO try/except! Let exceptions bubble up
        model = llm.get_model(prep_res["model"])

        kwargs = {"stream": False, "temperature": prep_res["temperature"]}

        # Only add optional parameters if not None
        if prep_res["system"] is not None:
            kwargs["system"] = prep_res["system"]
        if prep_res["max_tokens"] is not None:
            kwargs["max_tokens"] = prep_res["max_tokens"]

        # Add attachments if present
        if prep_res["attachments"]:
            kwargs["attachments"] = prep_res["attachments"]

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
        # Check for error first
        if isinstance(exec_res, dict) and exec_res.get("status") == "error":
            shared["error"] = exec_res.get("error", "Unknown error")
            shared["response"] = ""
            shared["llm_usage"] = {}
            return "error"  # Return error to trigger repair

        raw_response = exec_res["response"]

        # Parse JSON if possible
        parsed_response = self.parse_json_response(raw_response)

        # Store the parsed response
        shared["response"] = parsed_response

        # Store usage metrics matching spec structure exactly
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

        return "default"  # Always return "default"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle errors after all retries exhausted."""
        # Enhanced error messages
        error_msg = str(exc)

        if "UnknownModelError" in error_msg:
            error_detail = f"Unknown model: {prep_res['model']}. Run 'llm models' to see available models."
        elif "NeedsKeyException" in error_msg:
            error_detail = (
                f"API key required for model: {prep_res['model']}. "
                f"Set up with 'llm keys set <provider>' or environment variable."
            )
        else:
            error_detail = f"LLM call failed after {self.max_retries} attempts. Model: {prep_res['model']}"

        # Return error dict instead of raising
        return {
            "response": "",
            "error": error_detail,
            "model": prep_res.get("model", "unknown"),
            "usage": {},
            "status": "error",
        }
