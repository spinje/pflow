"""Anthropic SDK wrapper that implements the llm library Model interface.

This allows us to use Anthropic SDK features (caching, thinking) while maintaining
compatibility with the existing llm.get_model() pattern used throughout the codebase.
"""

import os
from typing import Any, Optional, Union

from pydantic import BaseModel

from pflow.planning.utils.anthropic_structured_client import AnthropicStructuredClient


class AnthropicLLMModel:
    """Wrapper that makes AnthropicStructuredClient look like an llm.Model.

    This allows the Anthropic SDK to be used transparently through the standard
    llm.get_model() interface, maintaining consistency across all nodes.
    """

    def __init__(self, model_name: str = "claude-sonnet-4-20250514"):
        """Initialize the Anthropic model wrapper.

        Args:
            model_name: Model identifier (for compatibility, actual model is fixed)
        """
        self.model_name = model_name
        self.model_id = model_name  # For compatibility with llm library
        # Get API key using llm's key management
        api_key = self._get_api_key()
        self.client = AnthropicStructuredClient(api_key=api_key)

    def _get_api_key(self) -> Optional[str]:
        """Get Anthropic API key using llm's key management."""

        # First check environment variable
        api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not api_key:
            # Use llm's key management
            try:
                import llm

                api_key = llm.get_key("", "anthropic", "ANTHROPIC_API_KEY")
            except Exception:
                pass

        return api_key

    def prompt(
        self,
        prompt: Union[str, list],
        schema: Optional[type[BaseModel]] = None,
        temperature: float = 0.0,
        cache_blocks: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> "AnthropicResponse":
        """Execute a prompt using the Anthropic SDK.

        This method mimics the llm library's Model.prompt() interface but uses
        the Anthropic SDK underneath for caching and structured output.

        Args:
            prompt: The prompt text or messages (instructions only when cache_blocks provided)
            schema: Optional Pydantic model for structured output
            temperature: Sampling temperature
            cache_blocks: Optional list of cache blocks for multi-block prompt caching
            **kwargs: Additional arguments (model added for debug tracking)

        Returns:
            AnthropicResponse object that mimics llm.Response
        """
        # Handle both cached and non-cached paths
        if cache_blocks is not None:
            # Optimized path with cache blocks provided
            return self._prompt_with_cache_blocks(
                prompt=prompt,
                schema=schema,
                temperature=temperature,
                cache_blocks=cache_blocks,
                **kwargs,
            )
        else:
            # Fallback path without cache blocks - pass None to structured client
            return self._prompt_without_cache(
                prompt=prompt,
                schema=schema,
                temperature=temperature,
                **kwargs,
            )

    def _prompt_with_cache_blocks(
        self,
        prompt: Union[str, list],
        schema: Optional[type[BaseModel]],
        temperature: float,
        cache_blocks: list[dict[str, Any]],
        **kwargs: Any,
    ) -> "AnthropicResponse":
        """Execute prompt with provided cache blocks (optimized path).
        
        This is the new optimized path where cache blocks are provided directly,
        avoiding regex extraction and enabling multi-block caching.
        
        Args:
            prompt: Instructions only (not the full context)
            schema: Optional Pydantic model for structured output
            temperature: Temperature for response generation
            cache_blocks: List of cache blocks with cache_control markers
            **kwargs: Additional arguments
            
        Returns:
            AnthropicResponse wrapping the result
        """
        # Convert prompt to string if needed
        prompt_str = prompt if isinstance(prompt, str) else str(prompt)
        
        # Add model to kwargs for debug wrapper tracking
        kwargs["model"] = self.model_id
        
        if schema:
            # Structured output with provided blocks
            result, usage = self.client.generate_with_schema_text_mode(
                prompt=prompt_str,  # Instructions only
                response_model=schema,
                temperature=temperature,
                cache_blocks=cache_blocks,  # Use provided blocks
                force_text_output=False,
            )
        else:
            # Text output with provided blocks (PlanningNode path)
            # Use the tool-choice hack for cache sharing
            from pflow.planning.ir_models import FlowIR
            
            result, usage = self.client.generate_with_schema_text_mode(
                prompt=prompt_str,  # Instructions only
                response_model=FlowIR,  # Tool definition for cache sharing
                temperature=temperature,
                cache_blocks=cache_blocks,  # Use provided blocks
                force_text_output=True,  # Get text output despite tool
            )
        
        # Log cache metrics for debugging
        if usage:
            cache_creation = usage.get("cache_creation_input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            if cache_creation > 0 or cache_read > 0:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(
                    f"Cache metrics: created={cache_creation} tokens, "
                    f"read={cache_read} tokens, blocks={len(cache_blocks)}"
                )
        
        return AnthropicResponse(result, usage, is_structured=bool(schema))

    def _prompt_without_cache(
        self,
        prompt: Union[str, list],
        schema: Optional[type[BaseModel]],
        temperature: float,
        **kwargs: Any,
    ) -> "AnthropicResponse":
        """Execute prompt without cache blocks (fallback path for non-cached nodes).
        
        Args:
            prompt: The full prompt text
            schema: Optional Pydantic model for structured output
            temperature: Temperature for response generation
            **kwargs: Additional arguments
            
        Returns:
            AnthropicResponse wrapping the result
        """
        # Convert prompt to string if needed
        prompt_str = prompt if isinstance(prompt, str) else str(prompt)
        
        # Add model to kwargs for debug wrapper tracking
        kwargs["model"] = self.model_id
        
        if schema:
            # Structured output without caching - pass None for cache_blocks
            result, usage = self.client.generate_with_schema_text_mode(
                prompt=prompt_str,
                response_model=schema,
                temperature=temperature,
                cache_blocks=None,  # No caching for this path
                force_text_output=False,
            )
        else:
            # Text output without caching - still use FlowIR tool for consistency
            # This maintains compatibility with any future caching scenarios
            from pflow.planning.ir_models import FlowIR
            
            result, usage = self.client.generate_with_schema_text_mode(
                prompt=prompt_str,
                response_model=FlowIR,  # Tool definition for consistency
                temperature=temperature,
                cache_blocks=None,  # No caching for this path
                force_text_output=True,  # Get text output despite tool
            )
        
        return AnthropicResponse(result, usage, is_structured=bool(schema))


class AnthropicResponse:
    """Response wrapper that mimics llm.Response interface."""

    def __init__(self, content: Any, usage: dict[str, Any], is_structured: bool = False):
        """Initialize the response wrapper.

        Args:
            content: The response content (Pydantic model or text)
            usage: Usage metadata from Anthropic SDK
            is_structured: Whether this is a structured response
        """
        self.content = content
        self._usage_data = usage  # Store as private to avoid conflicts
        self.is_structured = is_structured

    def text(self) -> str:
        """Get response as text (for compatibility)."""
        if self.is_structured:
            # Convert Pydantic model to string
            if hasattr(self.content, "model_dump_json"):
                return self.content.model_dump_json()
            return str(self.content)
        return str(self.content)

    def json(self) -> Any:
        """Get response as JSON (for structured output).

        Returns the response in a format compatible with parse_structured_response,
        which expects Claude/Anthropic format: {'content': [{'input': <data>}]}
        """
        if self.is_structured:
            # Return in Claude/Anthropic format for parse_structured_response
            # CRITICAL: Use by_alias=True to ensure EdgeIR uses "from"/"to" not "from_node"/"to_node"
            if hasattr(self.content, "model_dump"):
                data = self.content.model_dump(by_alias=True, exclude_none=True)
            else:
                data = self.content
            return {"content": [{"input": data, "type": "tool_use"}]}
        return self.content

    def usage(self) -> dict[str, Any]:
        """Get usage metadata."""
        return self._usage_data

    # Make the response itself act like the structured object for compatibility
    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the content for structured responses."""
        if self.is_structured and hasattr(self.content, name):
            return getattr(self.content, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")


def install_anthropic_model() -> None:
    """Install the Anthropic model wrapper for planning nodes.

    This monkey-patches llm.get_model to return our Anthropic SDK wrapper
    for planning-specific models, which gives us caching and better performance.
    """
    import llm

    # Store original get_model
    original_get_model = llm.get_model

    def get_model_with_anthropic(model_name: Optional[str] = None) -> Any:
        """Replacement for llm.get_model that uses Anthropic SDK for planning models."""
        # Always use Anthropic SDK for planning models (better caching, thinking)
        # Planning nodes use "anthropic/claude-sonnet-4-0" by default
        is_planning_model = model_name and (
            "claude-sonnet-4" in model_name or model_name == "anthropic/claude-sonnet-4-0"
        )

        if is_planning_model:
            # Use our Anthropic SDK wrapper for planning models
            return AnthropicLLMModel(model_name)
        else:
            # Use original llm library for everything else
            return original_get_model(model_name)

    # Replace llm.get_model
    llm.get_model = get_model_with_anthropic
