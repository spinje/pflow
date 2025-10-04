"""Utility functions for LLM integration in planning nodes.

This module provides shared utilities for working with LLM responses,
particularly for parsing structured output from Anthropic's API.
"""

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def parse_structured_response(response: Any, expected_type: type[BaseModel]) -> dict[str, Any]:
    """Parse structured LLM response from any model (Anthropic, OpenAI, Gemini, etc).

    Uses the normalized text() method which works consistently across all LLM providers.
    For structured output (schema-based), the text() contains the JSON matching the schema.

    Args:
        response: LLM response object with text() method
        expected_type: Expected Pydantic model type for logging

    Returns:
        Parsed response data as dictionary

    Raises:
        ValueError: If response parsing fails or structure is invalid
    """
    import json

    try:
        # The LLM library normalizes all responses to have a text() method
        # For structured output, this contains the JSON matching the schema
        if not hasattr(response, "text"):
            raise ValueError("Response object has no text() method")

        # Get the text (which is JSON for structured responses)
        text_output = response.text() if callable(response.text) else response.text

        if not text_output:
            raise ValueError("LLM returned empty response")

        # Parse the JSON
        try:
            result = json.loads(text_output)
            logger.debug(f"Parsed structured response for {expected_type.__name__}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Response text is not valid JSON: {text_output[:200]}") from e

        # CRITICAL: Validate through Pydantic model and dump with aliases
        # This ensures "from_node"/"to_node" get converted to "from"/"to"
        if isinstance(result, dict) and expected_type:
            # Validate through the expected Pydantic model
            try:
                model = expected_type.model_validate(result)
                # Dump with aliases to get correct format
                validated_result: dict[str, Any] = model.model_dump(by_alias=True, exclude_none=True)
                return validated_result
            except Exception as e:
                # If validation fails, log and return raw result
                logger.warning(f"Failed to validate result through {expected_type.__name__}: {e}")
                return result
        elif hasattr(result, "model_dump"):
            # Already a Pydantic model (shouldn't happen but handle it)
            pydantic_result: dict[str, Any] = result.model_dump(by_alias=True, exclude_none=True)
            return pydantic_result
        else:
            # Fallback: return as-is
            fallback_result: dict[str, Any] = result
            return fallback_result

    except Exception as e:
        # Log at debug level to avoid showing stack traces in normal operation
        logger.debug(f"Failed to parse LLM response: {type(e).__name__}: {e}")

        # Preserve API errors for intelligent downstream handling
        error_type_name = type(e).__name__
        if "API" in error_type_name or "api" in error_type_name.lower():
            raise  # Re-raise original API errors with full context

        # Only wrap actual parsing errors
        raise ValueError(f"Response parsing failed: {e}") from e


def generate_workflow_name(user_input: str, max_length: int = 30) -> str:
    """Generate a suggested workflow name from user input.

    Simple algorithm: Take first few significant words and kebab-case them.

    Args:
        user_input: Original user request
        max_length: Maximum characters to consider from input

    Returns:
        Suggested workflow name in kebab-case
    """
    if not user_input:
        return "workflow"

    # Simple name generation: lowercase, replace spaces with hyphens
    # Take first max_length chars, clean up
    words = user_input.lower()[:max_length].split()

    # Filter out common words
    stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
    significant_words = [w for w in words if w not in stop_words][:3]

    if not significant_words:
        return "workflow"

    return "-".join(significant_words)
