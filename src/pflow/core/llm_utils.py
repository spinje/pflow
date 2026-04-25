"""Utility functions for LLM integration.

Shared utilities for working with LLM responses, particularly for parsing
structured output from any provider (Anthropic, OpenAI, Gemini, etc.).
"""

import logging
from typing import Any

from pydantic import BaseModel

from pflow.core.exceptions import LLMCallError, LLMResponseParseError

logger = logging.getLogger(__name__)


def parse_structured_response(
    response: Any,
    expected_type: type[BaseModel],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Parse a structured LLM response into a validated dict.

    Reads the ``text`` string attribute from the adapter response. For
    structured output (schema-based), the text contains JSON matching the
    schema. The result is validated against ``expected_type`` (a Pydantic
    model) and dumped with aliases so canonical field names are returned.

    Args:
        response: Adapter response object exposing a string ``text`` attribute.
        expected_type: Pydantic model class used to validate the parsed JSON.
        model: Optional model identifier used to enrich the typed exception's
            ``model`` attribute. Callers that have model context should pass
            it so ``to_diagnostics()`` can surface ``context.model`` in JSON
            output. Defaults to ``None`` for callers without that context.

    Returns:
        Parsed and (best-effort) validated response data as a dictionary.

    Raises:
        LLMResponseParseError: If the response shape is invalid, the text is
            empty, or the JSON cannot be parsed. The base ``LLMCallError``
            still catches it for callers that don't discriminate.
        LLMCallError: For any other deterministic parsing failure. Provider-side
            API errors are re-raised unwrapped.
    """
    import json

    try:
        # AdapterResponse.text is a plain string; for structured output it
        # contains JSON matching the schema.
        if not hasattr(response, "text"):
            raise LLMResponseParseError("Response object has no 'text' attribute", model=model)

        text_output = response.text

        if not text_output:
            raise LLMResponseParseError("LLM returned empty response", model=model)

        # Parse the JSON
        try:
            result = json.loads(text_output)
            logger.debug(f"Parsed structured response for {expected_type.__name__}")
        except json.JSONDecodeError as e:
            raise LLMResponseParseError(
                f"Response text is not valid JSON: {text_output[:200]}",
                model=model,
            ) from e

        # CRITICAL: Validate through Pydantic model and dump with aliases
        # This ensures "from_node"/"to_node" get converted to "from"/"to"
        if isinstance(result, dict):
            # Validate through the expected Pydantic model
            try:
                model_obj = expected_type.model_validate(result)
                # Dump with aliases to get correct format
                validated_result: dict[str, Any] = model_obj.model_dump(by_alias=True, exclude_none=True)
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

    except LLMCallError:
        # Already a typed parsing error — let it propagate without re-wrapping.
        raise
    except Exception as e:
        # Log at debug level to avoid showing stack traces in normal operation
        logger.debug(f"Failed to parse LLM response: {type(e).__name__}: {e}")

        # Preserve API errors for intelligent downstream handling
        error_type_name = type(e).__name__
        if "API" in error_type_name or "api" in error_type_name.lower():
            raise  # Re-raise original API errors with full context

        # Only wrap actual parsing errors
        raise LLMResponseParseError(f"Response parsing failed: {e}", model=model) from e
