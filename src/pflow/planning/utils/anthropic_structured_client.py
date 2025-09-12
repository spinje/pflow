"""AnthropicStructuredClient - Wrapper for Anthropic SDK with structured output and caching.

This module provides a clean interface to the Anthropic SDK specifically for the
planning pipeline's needs:
- Structured output via tool calling
- Prompt caching for cost optimization
- Thinking/reasoning capabilities
- Consistent error handling
"""

import os
from typing import Any, Optional

from pydantic import BaseModel, ValidationError

from pflow.core.exceptions import PflowError as PlannerException


class AnthropicStructuredClient:
    """Wrapper for Anthropic SDK providing structured output with caching and thinking.

    This client encapsulates the Anthropic SDK for the planning pipeline, providing:
    - Tool calling for structured output generation
    - Prompt caching to reduce retry costs by 90%
    - Thinking/reasoning capabilities for better planning
    - Consistent error handling and debug logging
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Anthropic client.

        Args:
            api_key: Optional API key. Falls back to ANTHROPIC_API_KEY env var
                    or llm library key storage.
        """
        try:
            from anthropic import Anthropic
        except ImportError:
            raise PlannerException("Anthropic SDK not installed. Please install with: pip install anthropic>=0.40.0")

        # Get API key with fallback chain
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not api_key:
            # Try to get from llm library storage
            try:
                import llm

                api_key = llm.get_key("", "anthropic", "ANTHROPIC_API_KEY")
            except Exception as e:
                # Log the error for debugging
                import logging

                logging.debug(f"Failed to get key from llm library: {e}")
                pass

        if not api_key:
            raise PlannerException(
                "No Anthropic API key found. Set ANTHROPIC_API_KEY environment variable "
                "or configure with: llm keys set anthropic"
            )

        self.client = Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-20250514"  # Model specified in requirements

    def generate_with_schema_text_mode(
        self,
        prompt: str,
        response_model: type[BaseModel],
        max_tokens: int = 8192,
        temperature: float = 0.0,
        cache_blocks: Optional[list[dict[str, Any]]] = None,
        force_text_output: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        """Generate output with tools defined but optionally force text output.

        This enables cache sharing between nodes that use tools and those that don't.

        Args:
            prompt: The user prompt to send
            response_model: Pydantic model (used for tool definition)
            max_tokens: Maximum tokens for the response
            temperature: Sampling temperature
            cache_blocks: Optional cache control blocks
            force_text_output: If True, use tool_choice='none' for text output

        Returns:
            Tuple of (text_response, usage_metadata)
        """
        # Build the tool definition (same as generate_with_schema)
        tool_name = response_model.__name__.lower()
        tool_schema = response_model.model_json_schema()
        tool = {"name": tool_name, "description": f"Generate {response_model.__name__}", "input_schema": tool_schema}

        # Build messages with cache control if provided
        if cache_blocks:
            system_parts = []
            for block in cache_blocks:
                if block.get("cache_control"):
                    system_parts.append({
                        "type": "text",
                        "text": block["text"],
                        "cache_control": block["cache_control"],
                    })
                else:
                    system_parts.append({"type": "text", "text": block["text"]})
            messages = [{"role": "user", "content": prompt}]
            system = system_parts
        else:
            messages = [{"role": "user", "content": prompt}]
            system = None

        # Build kwargs
        kwargs = {
            "model": self.model,
            "messages": messages,
            "tools": [tool],  # Include tools for cache compatibility
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Add tool_choice based on force_text_output
        if force_text_output:
            # Force text output (for PlanningNode)
            kwargs["tool_choice"] = {"type": "none"}
        else:
            # Force tool use (for WorkflowGeneratorNode)
            kwargs["tool_choice"] = {"type": "tool", "name": tool_name}

        if system is not None:
            kwargs["system"] = system

        try:
            response = self.client.messages.create(**kwargs)

            # Extract response based on output type
            if force_text_output:
                # Text output expected
                text_content = response.content[0].text if response.content else ""
                result = text_content
            else:
                # Tool output expected
                tool_use = None
                for content in response.content:
                    if content.type == "tool_use" and content.name == tool_name:
                        tool_use = content
                        break
                if not tool_use:
                    raise PlannerException("No tool response found")
                result = response_model.model_validate(tool_use.input)

            # Extract usage metadata
            usage = response.usage
            usage_metadata = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
                "model": self.model,
                "temperature": temperature,
            }

            return (result, usage_metadata)

        except Exception as e:
            if "anthropic" in str(type(e).__module__):
                error_msg = str(e)
                if "rate_limit" in error_msg.lower():
                    raise PlannerException("Anthropic rate limit exceeded. Please wait and try again.") from e
                elif "invalid_api_key" in error_msg.lower():
                    raise PlannerException("Invalid Anthropic API key. Please check your configuration.") from e
                else:
                    raise PlannerException(f"Anthropic API error: {error_msg}") from e
            else:
                raise

    def generate_with_schema(
        self,
        prompt: str,
        response_model: type[BaseModel],
        max_tokens: int = 8192,
        temperature: float = 0.0,
        cache_blocks: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[BaseModel, dict[str, Any]]:
        """Generate structured output using Anthropic's tool calling.

        Args:
            prompt: The user prompt to send
            response_model: Pydantic model defining the expected response structure
            max_tokens: Maximum tokens for the response
            temperature: Sampling temperature (0.0 for deterministic)
            cache_blocks: Optional list of cache control blocks for prompt caching

        Returns:
            Tuple of (parsed_response, usage_metadata)

        Raises:
            PlannerException: On API errors or validation failures
        """
        # Build the tool definition from the Pydantic model
        tool_name = response_model.__name__.lower()
        tool_schema = response_model.model_json_schema()

        # Create the tool definition
        tool = {"name": tool_name, "description": f"Generate {response_model.__name__}", "input_schema": tool_schema}

        # Build messages with cache control if provided
        messages = []

        if cache_blocks:
            # When using cache blocks, they contain the cacheable context
            # The prompt parameter contains the non-cacheable instructions
            # We'll put cache blocks in system and instructions in user message
            system_parts = []
            for block in cache_blocks:
                if block.get("cache_control"):
                    system_parts.append({
                        "type": "text",
                        "text": block["text"],
                        "cache_control": block["cache_control"],
                    })
                else:
                    system_parts.append({"type": "text", "text": block["text"]})

            # The main prompt goes as user message (instructions)
            messages = [{"role": "user", "content": prompt}]
            system = system_parts  # Cacheable context goes in system
        else:
            # Simple message without caching
            messages = [{"role": "user", "content": prompt}]
            system = None

        try:
            # Make the API call
            # Note: Thinking is enabled via model selection, not metadata
            kwargs = {
                "model": self.model,
                "messages": messages,
                "tools": [tool],
                "tool_choice": {"type": "tool", "name": tool_name},
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            # Only add system if it's not None
            if system is not None:
                kwargs["system"] = system

            response = self.client.messages.create(**kwargs)

            # Extract the tool response
            tool_use = None
            for content in response.content:
                if content.type == "tool_use" and content.name == tool_name:
                    tool_use = content
                    break

            if not tool_use:
                raise PlannerException(f"No tool response found in Anthropic response. Got: {response.content}")

            # Parse the response with the Pydantic model
            try:
                parsed_response = response_model.model_validate(tool_use.input)
            except ValidationError as e:
                raise PlannerException(f"Failed to validate Anthropic response: {e}") from e

            # Extract usage metadata
            usage = response.usage
            usage_metadata = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
                "model": self.model,
                "temperature": temperature,
            }

            return parsed_response, usage_metadata

        except Exception as e:
            if "anthropic" in str(type(e).__module__):
                # Anthropic SDK error - wrap it
                error_msg = str(e)
                if "rate_limit" in error_msg.lower():
                    raise PlannerException("Anthropic rate limit exceeded. Please wait and try again.") from e
                elif "invalid_api_key" in error_msg.lower():
                    raise PlannerException("Invalid Anthropic API key. Please check your configuration.") from e
                else:
                    raise PlannerException(f"Anthropic API error: {error_msg}") from e
            else:
                # Re-raise other exceptions
                raise
