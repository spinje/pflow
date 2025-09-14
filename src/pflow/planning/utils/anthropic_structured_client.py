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
        except ImportError as e:
            raise PlannerException(
                "Anthropic SDK not installed. Please install with: pip install anthropic>=0.40.0"
            ) from e

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

    def _build_tool_definition(self, response_model: type[BaseModel]) -> tuple[str, dict[str, Any]]:
        """Build tool definition from a Pydantic model.

        Args:
            response_model: Pydantic model defining the expected response structure

        Returns:
            Tuple of (tool_name, tool_definition)
        """
        tool_name = response_model.__name__.lower()
        tool_schema = response_model.model_json_schema()
        tool = {"name": tool_name, "description": f"Generate {response_model.__name__}", "input_schema": tool_schema}
        return tool_name, tool

    def _build_messages_with_cache(
        self, prompt: str, cache_blocks: Optional[list[dict[str, Any]]] = None
    ) -> tuple[list[dict[str, str]], Optional[list[dict[str, Any]]]]:
        """Build messages and system content with cache control.

        Args:
            prompt: The user prompt to send
            cache_blocks: Optional cache control blocks

        Returns:
            Tuple of (messages, system_content)
        """
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
            return messages, system_parts
        else:
            messages = [{"role": "user", "content": prompt}]
            return messages, None

    def _extract_usage_metadata(self, response: Any, temperature: float) -> dict[str, Any]:
        """Extract usage metadata from API response.

        Args:
            response: Anthropic API response
            temperature: Temperature used in the request

        Returns:
            Dictionary containing usage metadata
        """
        usage = response.usage
        return {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
            "model": self.model,
            "temperature": temperature,
        }

    def _handle_anthropic_exception(self, e: Exception) -> None:
        """Handle Anthropic-specific exceptions.

        Args:
            e: The exception to handle

        Raises:
            PlannerException: Always raises with appropriate error message
        """
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

    def _extract_tool_response(
        self, response_content: list, tool_name: str, response_model: type[BaseModel]
    ) -> BaseModel:
        """Extract and validate tool response from API response.

        Args:
            response_content: Response content from API
            tool_name: Expected tool name
            response_model: Pydantic model for validation

        Returns:
            Validated response model instance

        Raises:
            PlannerException: If tool response not found or validation fails
        """
        tool_use = None
        for content in response_content:
            if content.type == "tool_use" and content.name == tool_name:
                tool_use = content
                break

        if not tool_use:
            raise PlannerException(f"No tool response found in Anthropic response. Got: {response_content}")

        try:
            return response_model.model_validate(tool_use.input)
        except ValidationError as e:
            raise PlannerException(f"Failed to validate Anthropic response: {e}") from e

    def _extract_text_response(self, response: Any) -> str:
        """Extract text content from response.

        Args:
            response: Anthropic API response

        Returns:
            Text content from response
        """
        return response.content[0].text if response.content else ""

    def generate_with_schema_text_mode(
        self,
        prompt: str,
        response_model: type[BaseModel],
        max_tokens: int = 8192,
        temperature: float = 0.0,
        cache_blocks: Optional[list[dict[str, Any]]] = None,
        force_text_output: bool = False,
    ) -> tuple[Any, dict[str, Any]]:
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
            Tuple of (text_response or model_instance, usage_metadata)
        """
        # Build the tool definition
        tool_name, tool = self._build_tool_definition(response_model)

        # Build messages with cache control
        messages, system = self._build_messages_with_cache(prompt, cache_blocks)

        # Determine tool_choice based on force_text_output
        tool_choice = {"type": "none"} if force_text_output else {"type": "tool", "name": tool_name}

        try:
            # Call the API with or without system content
            if system is not None:
                response = self.client.messages.create(  # type: ignore[call-overload]
                    model=self.model,
                    messages=messages,
                    tools=[tool],
                    tool_choice=tool_choice,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                )
            else:
                response = self.client.messages.create(  # type: ignore[call-overload]
                    model=self.model,
                    messages=messages,
                    tools=[tool],
                    tool_choice=tool_choice,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

            # Extract response based on output type
            result: Any
            if force_text_output:
                result = self._extract_text_response(response)
            else:
                result = self._extract_tool_response(response.content, tool_name, response_model)

            # Extract usage metadata
            usage_metadata = self._extract_usage_metadata(response, temperature)

            return (result, usage_metadata)

        except Exception as e:
            self._handle_anthropic_exception(e)
            # This line should never be reached as _handle_anthropic_exception always raises
            raise  # Make mypy happy

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
        # Build the tool definition
        tool_name, tool = self._build_tool_definition(response_model)

        # Build messages with cache control
        messages, system = self._build_messages_with_cache(prompt, cache_blocks)

        try:
            # Make the API call
            if system is not None:
                response = self.client.messages.create(  # type: ignore[call-overload]
                    model=self.model,
                    messages=messages,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool_name},
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                )
            else:
                response = self.client.messages.create(  # type: ignore[call-overload]
                    model=self.model,
                    messages=messages,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool_name},
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

            # Extract and validate the tool response
            parsed_response = self._extract_tool_response(response.content, tool_name, response_model)

            # Extract usage metadata
            usage_metadata = self._extract_usage_metadata(response, temperature)

            return parsed_response, usage_metadata

        except Exception as e:
            self._handle_anthropic_exception(e)
            # This line should never be reached as _handle_anthropic_exception always raises
            raise  # Make mypy happy
