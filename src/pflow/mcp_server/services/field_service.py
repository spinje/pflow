"""Field service for reading cached execution fields.

This service provides field retrieval from cached node executions,
supporting the structure-only mode introduced in Task 89.
"""

import logging
from typing import Any

from pflow.core.execution_cache import ExecutionCache
from pflow.runtime.template_resolver import TemplateResolver

from .base_service import BaseService, ensure_stateless

logger = logging.getLogger(__name__)


class FieldService(BaseService):
    """Service for reading fields from cached node executions.

    This service enables selective data retrieval after structure-only
    registry_run calls, implementing the two-phase approach:
    1. registry_run → structure + execution_id
    2. read_fields → specific field values
    """

    @classmethod
    @ensure_stateless
    def read_fields(cls, execution_id: str, field_paths: list[str]) -> str:
        """Read specific fields from cached execution.

        Args:
            execution_id: Execution ID from previous registry_run call
            field_paths: List of field paths to retrieve (e.g., ["result[0].title"])

        Returns:
            Formatted text showing field paths and their values

        Raises:
            ValueError: If execution_id not found in cache

        Example:
            >>> result = FieldService.read_fields(
            ...     "exec-1705234567-a1b2c3d4",
            ...     ["result[0].title", "result[0].id"]
            ... )
            >>> print(result)
            result[0].title: Fix authentication bug
            result[0].id: 12345
        """
        # Create fresh cache instance (stateless pattern)
        cache = ExecutionCache()

        # Retrieve cached execution
        cache_data = cache.retrieve(execution_id)

        if cache_data is None:
            # Provide helpful error message
            raise ValueError(
                f"Execution '{execution_id}' not found in cache.\n"
                "\n"
                "Run registry_run tool first to execute a node and cache results.",
            )

        # Extract field values using TemplateResolver
        outputs = cache_data["outputs"]
        field_values: dict[str, Any] = {}

        for field_path in field_paths:
            try:
                # Use TemplateResolver for consistent path parsing
                # (same logic as template resolution in workflows)
                value = TemplateResolver.resolve_value(field_path, outputs)
                field_values[field_path] = value
            except Exception:
                # Invalid path or field not found - store None
                # This matches CLI behavior (graceful degradation)
                field_values[field_path] = None

        # Import formatter locally (not at module level)
        # This is the MCP service pattern to avoid circular imports
        from pflow.execution.formatters.field_output_formatter import format_field_output

        # Return formatted text (MCP agents prefer text over JSON)
        # format_field_output with format_type="text" always returns str
        result = format_field_output(field_values, format_type="text")
        # Type narrowing for mypy: format_field_output returns str for text format
        if not isinstance(result, str):
            raise TypeError(f"Expected str from formatter, got {type(result)}")
        return result
