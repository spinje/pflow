"""Anthropic SDK wrapper that implements the llm library Model interface.

This allows us to use Anthropic SDK features (caching, thinking) while maintaining
compatibility with the existing llm.get_model() pattern used throughout the codebase.
"""

import os
import re
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
        **kwargs: Any,
    ) -> "AnthropicResponse":
        """Execute a prompt using the Anthropic SDK.

        This method mimics the llm library's Model.prompt() interface but uses
        the Anthropic SDK underneath for caching and structured output.

        Args:
            prompt: The prompt text or messages
            schema: Optional Pydantic model for structured output
            temperature: Sampling temperature
            **kwargs: Additional arguments (model added for debug tracking)

        Returns:
            AnthropicResponse object that mimics llm.Response
        """
        # Add model to kwargs for debug wrapper tracking
        kwargs["model"] = self.model_id
        if schema:
            # Use structured output with tool calling - also needs caching!
            prompt_str = prompt if isinstance(prompt, str) else str(prompt)

            # Build cacheable blocks for structured output
            cache_blocks = self._build_cache_blocks_for_structured(prompt_str)

            # If we have cache blocks, we need to remove the cached content from the prompt
            # so it's not duplicated (cache blocks go in system, rest goes in user message)
            if cache_blocks:
                # Remove the cached workflow overview from the prompt
                workflow_pattern = r"(# Workflow System Overview.*?)(?=\n## (?:Requirements Analysis|User Request|Available|Planning Instructions|Workflow Generation)|\Z)"
                workflow_match = re.search(workflow_pattern, prompt_str, re.DOTALL)
                if workflow_match:
                    # Remove the workflow overview from the prompt
                    remaining_prompt = prompt_str.replace(workflow_match.group(1), "").strip()
                else:
                    remaining_prompt = prompt_str
            else:
                remaining_prompt = prompt_str

            # Use the unified method with force_text_output=False for structured output
            result, usage = self.client.generate_with_schema_text_mode(
                prompt=remaining_prompt,  # Send only non-cached content as user message
                response_model=schema,
                temperature=temperature,
                cache_blocks=cache_blocks if cache_blocks else None,
                force_text_output=False,  # This will use tool_choice={'type': 'tool'}
            )
            return AnthropicResponse(result, usage, is_structured=True)
        else:
            # Non-structured output - BUT we need to use the same tools as structured
            # to enable cache sharing. We'll use tool_choice='none' to get text output.
            prompt_str = prompt if isinstance(prompt, str) else str(prompt)

            # Extract workflow overview for caching (same as structured path)
            workflow_pattern = r"(# Workflow System Overview.*?)(?=\n## (?:Requirements Analysis|User Request|Available|Planning Instructions|Workflow Generation)|\Z)"
            workflow_match = re.search(workflow_pattern, prompt_str, re.DOTALL)

            cache_blocks = None
            if workflow_match and len(workflow_match.group(1)) > 3000:
                # Extract workflow overview for system parameter
                workflow_overview = workflow_match.group(1).strip()
                # Everything else goes in user message
                user_content = prompt_str.replace(workflow_match.group(0), "").strip()

                # Build cache blocks for system parameter
                cache_blocks = [{"text": workflow_overview, "cache_control": {"type": "ephemeral"}}]
            else:
                # No workflow overview found
                user_content = prompt_str

            # CRITICAL: Use the same tool definition as structured output
            # but with tool_choice='none' to get text output
            # This enables cache sharing between PlanningNode and WorkflowGeneratorNode
            from pflow.planning.ir_models import FlowIR

            # Create a dummy FlowIR tool (same as WorkflowGeneratorNode uses)
            # But we won't actually use it (tool_choice='none')
            dummy_response_model = FlowIR

            # Use the structured client with tool_choice='none' for text output
            result_text, usage = self.client.generate_with_schema_text_mode(
                prompt=user_content,
                response_model=dummy_response_model,
                temperature=temperature,
                cache_blocks=cache_blocks,
                force_text_output=True,  # This will set tool_choice='none'
            )

            return AnthropicResponse(result_text, usage, is_structured=False)

    def _build_cache_blocks_for_structured(self, prompt: str) -> Optional[list[dict[str, Any]]]:
        """Build cache blocks for structured output (WorkflowGenerator).

        For structured output, we need to extract the cacheable context
        and return it as blocks that will be passed to the system parameter.

        Args:
            prompt: The full prompt string

        Returns:
            List of cache blocks or None if no caching opportunity
        """
        # Extract ONLY the workflow system overview for caching
        # This ensures it matches exactly what PlanningNode cached
        # The overview ends at "## Requirements Analysis" or similar context sections
        workflow_pattern = r"(# Workflow System Overview.*?)(?=\n## (?:Requirements Analysis|User Request|Available|Planning Instructions|Workflow Generation)|\Z)"
        workflow_match = re.search(workflow_pattern, prompt, re.DOTALL)

        if workflow_match and len(workflow_match.group(1)) > 3000:
            # Found the workflow overview - cache ONLY this part
            workflow_content = workflow_match.group(1).strip()

            # Return just the workflow overview with cache control
            # Everything else (plan output, instructions) will be in the user message
            return [{"text": workflow_content, "cache_control": {"type": "ephemeral"}}]

        return None

    def _build_cacheable_blocks(self, prompt: str) -> list[dict[str, Any]]:
        """Split prompt into cacheable blocks for optimal caching.

        The planner prompt typically contains:
        1. Introduction and user request
        2. Workflow System Overview (static, highly cacheable)
        3. Requirements/components (semi-dynamic)
        4. Instructions (dynamic)

        We want to cache the static parts (especially the workflow overview)
        which is typically 1800+ tokens and doesn't change between calls.

        Args:
            prompt: The full prompt string

        Returns:
            List of content blocks with cache_control where appropriate
        """
        import re

        # Look for the workflow system overview section which is our best caching candidate
        # The overview ends at "## Requirements Analysis" or similar context sections
        workflow_pattern = r"(# Workflow System Overview.*?)(?=\n## (?:Requirements Analysis|User Request|Available|Planning Instructions|Workflow Generation)|\Z)"
        workflow_match = re.search(workflow_pattern, prompt, re.DOTALL)

        if workflow_match and len(workflow_match.group(1)) > 3000:  # ~1000 tokens minimum
            # Found a substantial workflow overview section
            workflow_content = workflow_match.group(1).strip()

            # CRITICAL: Put workflow overview FIRST with cache control
            # This ensures it's in the exact same position for all nodes
            blocks = [{"type": "text", "text": workflow_content, "cache_control": {"type": "ephemeral"}}]

            # Add everything else as a single non-cached block
            # Remove the workflow overview from the prompt to avoid duplication
            remaining = prompt.replace(workflow_match.group(0), "").strip()
            if remaining:
                blocks.append({"type": "text", "text": remaining})

            return blocks

        # Alternative: Try to find other cacheable sections
        # Look for the separator pattern used by PlannerContextBuilder
        separator_pattern = r"={60}"
        if re.search(separator_pattern, prompt):
            # Split by major sections
            sections = re.split(r"\n={60}\n", prompt)

            if len(sections) > 1:
                blocks = []
                for i, section in enumerate(sections):
                    if not section.strip():
                        continue

                    # Cache the first major section if it's substantial
                    # (likely contains static context)
                    if i == 0 and len(section) > 3000:
                        blocks.append({"type": "text", "text": section.strip(), "cache_control": {"type": "ephemeral"}})
                    else:
                        blocks.append({"type": "text", "text": section.strip()})

                if blocks:
                    return blocks

        # Fallback: If we can't identify clear sections, try to cache the first
        # substantial portion of the prompt (if it's large enough)
        if len(prompt) > 6000:  # ~2000 tokens
            # Find a natural break point around 2/3 of the content
            break_point = int(len(prompt) * 0.66)
            # Look for a paragraph break near the break point
            newline_idx = prompt.find("\n\n", break_point)
            if newline_idx > 0:
                return [
                    {"type": "text", "text": prompt[:newline_idx].strip(), "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": prompt[newline_idx:].strip()},
                ]

        # No caching opportunity found - return as single block
        return [{"type": "text", "text": prompt}]


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
