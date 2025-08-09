"""Utility functions for LLM integration in planning nodes.

This module provides shared utilities for working with LLM responses,
particularly for parsing structured output from Anthropic's API.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_structured_response(response: Any, expected_type: type) -> dict[str, Any]:
    """Parse structured LLM response with Anthropic's nested format.

    Anthropic's API returns structured data nested in response['content'][0]['input'].
    This utility handles the extraction and validation.

    Args:
        response: LLM response object with json() method
        expected_type: Expected Pydantic model type for logging

    Returns:
        Parsed response data as dictionary

    Raises:
        ValueError: If response parsing fails or structure is invalid
    """
    try:
        response_data = response.json() if hasattr(response, "json") else response

        if response_data is None:
            raise ValueError("LLM returned None response")

        # Handle Anthropic's nested response structure
        content = response_data.get("content")
        if not content or not isinstance(content, list) or len(content) == 0:
            raise ValueError(f"Invalid LLM response structure: {response_data}")

        # Extract from nested structure
        result = content[0].get("input")
        if result is None:
            raise ValueError("No 'input' field in LLM response")

        logger.debug(f"Successfully parsed {expected_type.__name__} from LLM response")

        # Convert Pydantic model to dict if needed
        if hasattr(result, "model_dump"):
            model_dict: dict[str, Any] = result.model_dump(by_alias=True, exclude_none=True)
            return model_dict
        return dict(result)

    except Exception as e:
        logger.exception("Failed to parse LLM response")
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
