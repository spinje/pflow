"""Utility functions for LLM integration in planning nodes.

This module provides shared utilities for working with LLM responses,
particularly for parsing structured output from Anthropic's API.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_structured_response(response: Any, expected_type: type) -> dict[str, Any]:  # noqa: C901
    """Parse structured LLM response from both Claude and GPT models.

    Handles two response formats:
    - Claude/Anthropic: Nested in response['content'][0]['input']
    - GPT/OpenAI: Direct JSON string in response['content']

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

        # Get content field
        content = response_data.get("content")
        if content is None:
            raise ValueError(f"No 'content' field in LLM response: {response_data}")

        result = None

        # Try Claude/Anthropic format first (nested structure)
        if isinstance(content, list) and len(content) > 0:
            # Claude format: content[0]['input']
            first_item = content[0]
            if isinstance(first_item, dict) and "input" in first_item:
                result = first_item["input"]
                logger.debug(f"Parsed Claude format response for {expected_type.__name__}")

        # Try GPT/OpenAI format (direct JSON string or dict)
        if result is None:
            if isinstance(content, str):
                # GPT often returns JSON as a string that needs parsing
                try:
                    import json

                    result = json.loads(content)
                    logger.debug(f"Parsed GPT string format response for {expected_type.__name__}")
                except json.JSONDecodeError as e:
                    # Not JSON, might be plain text response
                    raise ValueError(f"Content is not valid JSON: {content[:200]}") from e
            elif isinstance(content, dict):
                # Sometimes it's already a dict
                result = content
                logger.debug(f"Parsed GPT dict format response for {expected_type.__name__}")
            else:
                raise ValueError(f"Unexpected content type: {type(content)}")

        if result is None:
            raise ValueError(f"Could not parse response in either Claude or GPT format: {response_data}")

        logger.debug(f"Successfully parsed {expected_type.__name__} from LLM response")

        # Convert Pydantic model to dict if needed
        if hasattr(result, "model_dump"):
            model_dict: dict[str, Any] = result.model_dump(by_alias=True, exclude_none=True)
            return model_dict
        return dict(result)

    except Exception as e:
        # Log at debug level to avoid showing stack traces in normal operation
        # Stack traces are only useful for debugging, not for handled errors
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
