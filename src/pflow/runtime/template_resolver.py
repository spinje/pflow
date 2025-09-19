"""Template variable detection and resolution with path support.

This module provides the core functionality for detecting and resolving
template variables in node parameters. Template variables use the format
${identifier} with optional path traversal (${data.field.subfield}).
"""

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TemplateResolver:
    """Handles template variable detection and resolution with path support."""

    # Pattern supports ${var} format with paths
    # Matches: ${identifier} or ${identifier.field.subfield}
    # Groups: (identifier.field.subfield)
    # Must not be preceded by $ (to avoid $${var} escapes)
    # Identifiers must start with letter or underscore
    # Supports hyphens in variable names
    TEMPLATE_PATTERN = re.compile(r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:\.[a-zA-Z_][\w-]*)*)\}")

    @staticmethod
    def has_templates(value: Any) -> bool:
        """Check if value contains template variables.

        Recursively checks nested dictionaries and lists for template strings.

        Args:
            value: The value to check for templates (string, dict, list, or any)

        Returns:
            True if value contains template variables anywhere in its structure
        """
        if isinstance(value, str):
            return "${" in value
        elif isinstance(value, dict):
            return any(TemplateResolver.has_templates(v) for v in value.values())
        elif isinstance(value, list):
            return any(TemplateResolver.has_templates(item) for item in value)
        else:
            return False

    @staticmethod
    def extract_variables(value: str) -> set[str]:
        """Extract all template variable names (including paths).

        Args:
            value: String that may contain template variables

        Returns:
            Set of variable names found (e.g., {'url', 'data.field'})
        """
        return set(TemplateResolver.TEMPLATE_PATTERN.findall(value))

    @staticmethod
    def variable_exists(var_name: str, context: dict[str, Any]) -> bool:
        """Check if a variable exists in context, regardless of its value.

        This method distinguishes between "variable doesn't exist" and
        "variable exists but has None value".

        Args:
            var_name: Variable name with optional path (e.g., 'data.field')
            context: Dictionary containing values to check

        Returns:
            True if variable exists (even if None), False if not found
        """
        if "." in var_name:
            # Handle path traversal
            parts = var_name.split(".")
            current = context

            for i, part in enumerate(parts):
                if not isinstance(current, dict):
                    return False  # Can't traverse non-dict

                if part not in current:
                    return False  # Key doesn't exist

                if i < len(parts) - 1:
                    # Not the last part - need to continue traversing
                    current = current[part]
                    if current is None:
                        return False  # Can't traverse through None
                # For the last part, we just check existence, not value

            return True
        else:
            # Simple variable - just check if key exists
            return var_name in context

    @staticmethod
    def resolve_value(var_name: str, context: dict[str, Any]) -> Optional[Any]:
        """Resolve a variable name (possibly with path) from context.

        Handles path traversal for nested data access:
        - 'url' -> context['url']
        - 'data.field' -> context['data']['field']
        - 'data.field.subfield' -> context['data']['field']['subfield']

        Args:
            var_name: Variable name with optional path (e.g., 'data.field')
            context: Dictionary containing values to resolve from

        Returns:
            Resolved value or None if path cannot be resolved
        """
        if "." in var_name:
            # Handle path traversal like data.field.subfield
            parts = var_name.split(".")
            value = context

            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    # Path cannot be resolved (non-dict or missing key)
                    logger.debug(
                        f"Cannot resolve path '{var_name}': '{part}' not found or parent not a dict",
                        extra={"var_name": var_name, "failed_at": part},
                    )
                    return None
            return value
        else:
            # Simple variable lookup
            return context.get(var_name)

    @staticmethod
    def _convert_to_string(value: Any) -> str:
        """Convert any value to string following specified rules.

        Conversion rules:
        - None -> ""
        - "" -> ""
        - 0 -> "0"
        - False -> "False"
        - [] -> "[]"
        - {} -> "{}"
        - Everything else -> str(value)

        Args:
            value: Value to convert

        Returns:
            String representation of the value
        """
        if value is None or value == "":
            return ""
        # Check for boolean BEFORE checking for 0 (since False == 0 in Python)
        elif value is False:
            return "False"
        elif value is True:
            return "True"
        elif value == 0:
            return "0"
        elif value == []:
            return "[]"
        elif value == {}:
            return "{}"
        else:
            return str(value)

    @staticmethod
    def resolve_string(template: str, context: dict[str, Any]) -> str:
        """Resolve all template variables in a string.

        Template variables that cannot be resolved are left unchanged
        for debugging visibility.

        Args:
            template: String containing template variables
            context: Dictionary containing values to resolve from

        Returns:
            String with resolved template variables

        Examples:
            >>> context = {"url": "https://example.com", "data": {"title": "Test"}}
            >>> TemplateResolver.resolve_string("Visit ${url}", context)
            'Visit https://example.com'
            >>> TemplateResolver.resolve_string("Title: ${data.title}", context)
            'Title: Test'
            >>> TemplateResolver.resolve_string("Missing: ${undefined}", context)
            'Missing: ${undefined}'
        """
        result = template

        # Find all template variables in the string
        for match in TemplateResolver.TEMPLATE_PATTERN.finditer(template):
            var_name = match.group(1)  # Get the variable name without ${}
            resolved_value = TemplateResolver.resolve_value(var_name, context)

            # Note: We need to distinguish between:
            # 1. "value not found" (template should remain)
            # 2. "value is None at the end of path" (convert to empty string)
            # 3. "None in middle of path" (can't traverse, template should remain)

            if "." in var_name:
                # Path traversal - check if we successfully resolved
                base_var = var_name.split(".")[0]
                if base_var in context:
                    # Base exists, check if path resolved successfully
                    # resolve_value returns None both for "not found" and "value is None"
                    # We need to check if the full path is valid
                    parts = var_name.split(".")
                    current = context
                    path_valid = True

                    for i, part in enumerate(parts):
                        if isinstance(current, dict) and part in current:
                            current = current[part]
                            # If we hit None before the last part, path is invalid
                            if current is None and i < len(parts) - 1:
                                path_valid = False
                                break
                        else:
                            path_valid = False
                            break

                    if path_valid:
                        # Path fully resolved (even if final value is None)
                        value_str = TemplateResolver._convert_to_string(resolved_value)
                        result = result.replace(f"${{{var_name}}}", value_str)
                        logger.debug(
                            f"Resolved template variable '${{{var_name}}}' -> '{value_str}'",
                            extra={"var_name": var_name, "value_type": type(resolved_value).__name__},
                        )
                        continue
            else:
                # Simple variable - check if it exists
                if var_name in context:
                    # Variable exists, convert whatever value it has (including None)
                    value_str = TemplateResolver._convert_to_string(resolved_value)
                    result = result.replace(f"${{{var_name}}}", value_str)
                    logger.debug(
                        f"Resolved template variable '${{{var_name}}}' -> '{value_str}'",
                        extra={"var_name": var_name, "value_type": type(resolved_value).__name__},
                    )
                    continue

            # Variable doesn't exist - leave template as-is for debugging
            logger.debug(f"Template variable '${{{var_name}}}' could not be resolved", extra={"var_name": var_name})

        return result

    @staticmethod
    def resolve_nested(value: Any, context: dict[str, Any]) -> Any:
        """Recursively resolve template variables in nested structures.

        Handles dictionaries, lists, and nested combinations while preserving
        the original structure and types of non-template values.

        Args:
            value: The value to resolve (can be string, dict, list, or any type)
            context: Dictionary containing values to resolve from

        Returns:
            The value with all template variables resolved, maintaining structure

        Examples:
            >>> context = {"token": "abc123", "channel": "C123"}
            >>> params = {"headers": {"Authorization": "Bearer ${token}"}}
            >>> TemplateResolver.resolve_nested(params, context)
            {'headers': {'Authorization': 'Bearer abc123'}}
        """
        if isinstance(value, str):
            # Resolve string templates
            if "${" in value:
                return TemplateResolver.resolve_string(value, context)
            return value
        elif isinstance(value, dict):
            # Recursively resolve dictionary values
            return {k: TemplateResolver.resolve_nested(v, context) for k, v in value.items()}
        elif isinstance(value, list):
            # Recursively resolve list items
            return [TemplateResolver.resolve_nested(item, context) for item in value]
        else:
            # Return other types unchanged (int, float, bool, None, etc.)
            return value
