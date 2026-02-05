"""Template variable detection and resolution with path support.

This module provides the core functionality for detecting and resolving
template variables in node parameters. Template variables use the format
${identifier} with optional path traversal (${data.field.subfield}).
"""

import json
import logging
import re
from typing import Any, Optional

from pflow.core.json_utils import try_parse_json

logger = logging.getLogger(__name__)


class TemplateResolver:
    """Handles template variable detection and resolution with path support."""

    # Shared pattern for valid variable names with optional path and array indices
    # Matches: identifier, identifier.field, identifier[0].field, etc.
    # - Must start with letter or underscore
    # - Can contain word characters and hyphens
    # - Supports dot notation for nested access
    # - Supports bracket notation for array indices
    _VAR_NAME_PATTERN = r"[a-zA-Z_][\w-]*(?:(?:\[\d+\])?(?:\.[a-zA-Z_][\w-]*(?:\[\d+\])?)*)?"

    # Pattern for finding templates in strings (can match multiple)
    # Must not be preceded by $ (to avoid $${var} escapes)
    TEMPLATE_PATTERN = re.compile(rf"(?<!\$)\$\{{({_VAR_NAME_PATTERN})\}}")

    # Pattern for detecting simple templates (entire string is exactly one ${var})
    # Used to determine when to preserve type vs stringify
    # Uses same strict variable name pattern as TEMPLATE_PATTERN
    SIMPLE_TEMPLATE_PATTERN = re.compile(rf"^\$\{{({_VAR_NAME_PATTERN})\}}$")

    # Pattern for nested index templates: ${outer[${inner}]} or ${outer.path[${inner}].rest}
    # Captures: (1) outer_var with optional dot path, (2) inner_template, (3) rest_of_path
    # Examples: ${results[${item.index}]}, ${node.data[${__index__}].field}
    # Inner template uses same strict variable naming as _VAR_NAME_PATTERN for defense-in-depth
    NESTED_INDEX_PATTERN = re.compile(
        r"\$\{([a-zA-Z_][\w-]*(?:\.[a-zA-Z_][\w-]*)*)\[(\$\{"
        + _VAR_NAME_PATTERN
        + r"\})\]((?:\.[a-zA-Z_][\w-]*(?:\[\d+\])?)*)\}"
    )

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
    def resolve_nested_index_templates(template: str, context: dict[str, Any]) -> str:
        """Pre-process nested index templates by resolving inner ${...} first.

        Transforms templates like ${results[${item.index}].response} into
        ${results[0].response} (if item.index resolves to 0).

        This enables dynamic array indexing in batch processing where the index
        comes from a variable like ${__index__} or ${item.index}.

        Note: This is called automatically at the start of resolve_template()
        for all templates. Only ONE level of nesting is supported:
        - ${outer[${inner}]} works
        - ${outer[${inner[${deep}]}]} is NOT supported (inner nesting ignored)

        Handles array index patterns [${...}] only. Non-integer inner values
        or missing variables leave the template unchanged for debugging.

        Performance: Iterates up to 10 times per template (for multiple nested
        patterns). Early exits when no nested pattern found or can't resolve.

        Args:
            template: String that may contain nested index templates
            context: Dictionary containing values to resolve inner templates from

        Returns:
            Template string with inner index templates resolved to static values
        """
        if "${" not in template or "[${" not in template:
            return template

        # Limit iterations to prevent infinite loops with malformed templates
        max_iterations = 10
        for _ in range(max_iterations):
            match = TemplateResolver.NESTED_INDEX_PATTERN.search(template)
            if not match:
                break

            outer_var = match.group(1)  # e.g., "results" or "node.results"
            inner_template = match.group(2)  # e.g., "${item.index}"
            rest_path = match.group(3)  # e.g., ".response"

            # Extract variable name from inner template
            inner_var = TemplateResolver.extract_simple_template_var(inner_template)
            if inner_var is None:
                logger.debug(
                    "Nested template resolution skipped: inner template not simple",
                    extra={"template": template, "inner": inner_template},
                )
                break

            # Resolve inner variable
            resolved_inner = TemplateResolver.resolve_value(inner_var, context)
            if resolved_inner is None:
                logger.debug(
                    "Nested template resolution skipped: inner variable not found",
                    extra={"template": template, "inner_var": inner_var},
                )
                break

            # Must resolve to integer for array indexing
            if not isinstance(resolved_inner, int):
                logger.warning(
                    f"Nested index must be integer, got {type(resolved_inner).__name__}",
                    extra={"template": template, "inner_value": resolved_inner},
                )
                break

            # Build the resolved template with static index
            resolved = f"${{{outer_var}[{resolved_inner}]{rest_path}}}"
            template = template[: match.start()] + resolved + template[match.end() :]

        return template

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
    def is_simple_template(value: str) -> bool:
        """Check if string is exactly one template variable reference.

        Simple templates like "${var}" preserve the original type when resolved.
        Complex templates like "Hello ${name}" always return strings.

        Args:
            value: String to check

        Returns:
            True if the entire string is a single template reference

        Examples:
            >>> TemplateResolver.is_simple_template("${var}")
            True
            >>> TemplateResolver.is_simple_template("${data.field}")
            True
            >>> TemplateResolver.is_simple_template("Hello ${name}")
            False
            >>> TemplateResolver.is_simple_template("${a}${b}")
            False
        """
        return bool(TemplateResolver.SIMPLE_TEMPLATE_PATTERN.match(value))

    @staticmethod
    def extract_simple_template_var(value: str) -> Optional[str]:
        """Extract variable name from a simple template.

        Args:
            value: String that may be a simple template

        Returns:
            Variable name (with path if present), or None if not a simple template

        Examples:
            >>> TemplateResolver.extract_simple_template_var("${data}")
            'data'
            >>> TemplateResolver.extract_simple_template_var("${user.name}")
            'user.name'
            >>> TemplateResolver.extract_simple_template_var("Hello ${name}")
            None
        """
        match = TemplateResolver.SIMPLE_TEMPLATE_PATTERN.match(value)
        return match.group(1) if match else None

    @staticmethod
    def _try_parse_json_for_traversal(value: Any) -> Any:
        """Attempt to parse a string value as JSON for path traversal.

        Called when we need to access a property on a value that is a string.
        If the string is valid JSON object/array, returns the parsed value.
        Otherwise returns the original value unchanged.

        This enables patterns like ${node.stdout.field} when stdout
        contains a JSON string like '{"field": "value"}'.

        Args:
            value: Current value in path traversal (may be string or other type)

        Returns:
            Parsed JSON if value was a JSON string, otherwise original value
        """
        if not isinstance(value, str):
            return value

        success, parsed = try_parse_json(value)
        if success and isinstance(parsed, (dict, list)):
            # Only use parsed result if it's a container we can traverse
            logger.debug(
                f"Auto-parsed JSON string for path traversal: {type(parsed).__name__}",
            )
            return parsed
        return value

    @staticmethod
    def _get_dict_value(value: Any, key: str) -> tuple[bool, Any]:
        """Get a key from a dict, with JSON string auto-parsing.

        Tries to access value[key], auto-parsing JSON strings if needed.

        Args:
            value: Dict, JSON string, or other value
            key: Key to access

        Returns:
            Tuple of (success, result) where success indicates if key was found
        """
        # Direct dict access
        if isinstance(value, dict) and key in value:
            return True, value[key]

        # JSON string auto-parsing
        if isinstance(value, str):
            parsed = TemplateResolver._try_parse_json_for_traversal(value)
            if isinstance(parsed, dict) and key in parsed:
                return True, parsed[key]

        return False, None

    @staticmethod
    def _check_array_indices(
        current: Any, indices_str: str, is_last_element: bool, part_index: int, total_parts: int
    ) -> tuple[bool, Any]:
        """Check array indices and return validity status and current value.

        Args:
            current: Current value to check indices against
            indices_str: String containing indices like "[0][1]"
            is_last_element: Whether this is the last element to check
            part_index: Index of current part in the path
            total_parts: Total number of parts in the path

        Returns:
            Tuple of (is_valid, new_current) where is_valid indicates if indices are valid
        """
        indices = re.findall(r"\[(\d+)\]", indices_str)
        for idx, index_str in enumerate(indices):
            index = int(index_str)
            if not isinstance(current, list) or index >= len(current):
                return False, current

            # Check if we need to traverse further
            need_to_traverse = part_index < total_parts - 1 or idx < len(indices) - 1
            if need_to_traverse:
                current = current[index]
                if current is None:
                    return False, current  # Can't traverse through None

        return True, current

    @staticmethod
    def _traverse_path_part(current: Any, part: str, part_index: int, total_parts: int) -> tuple[bool, Any]:
        """Traverse a single path part and return validity status and new current value.

        Args:
            current: Current value in the traversal
            part: Path part to traverse (may include array indices)
            part_index: Index of current part in the path
            total_parts: Total number of parts in the path

        Returns:
            Tuple of (is_valid, new_current) where is_valid indicates if traversal succeeded
        """
        # Check if this part has array indices
        array_match = re.match(r"^([^[]+)((?:\[\d+\])+)$", part)

        if array_match:
            base_name = array_match.group(1)
            indices_str = array_match.group(2)

            # Get base value (with JSON auto-parsing)
            found, current = TemplateResolver._get_dict_value(current, base_name)
            if not found:
                return False, current

            # Parse JSON string if needed before array access
            current = TemplateResolver._try_parse_json_for_traversal(current)

            # Check array indices
            is_last = part_index == total_parts - 1
            return TemplateResolver._check_array_indices(current, indices_str, is_last, part_index, total_parts)

        # Regular property access (with JSON auto-parsing)
        found, value = TemplateResolver._get_dict_value(current, part)
        if not found:
            return False, current

        if part_index < total_parts - 1:
            # Not the last part - check for None
            if value is None:
                return False, value
            return True, value

        return True, current

    @staticmethod
    def variable_exists(var_name: str, context: dict[str, Any]) -> bool:
        """Check if a variable exists in context, regardless of its value.

        This method distinguishes between "variable doesn't exist" and
        "variable exists but has None value".

        Args:
            var_name: Variable name with optional path and array indices
            context: Dictionary containing values to check

        Returns:
            True if variable exists (even if None), False if not found
        """
        if "." in var_name or "[" in var_name:
            # Split on dots, but not dots inside brackets
            parts = re.split(r"\.(?![^\[]*\])", var_name)
            current = context

            for i, part in enumerate(parts):
                valid, current = TemplateResolver._traverse_path_part(current, part, i, len(parts))
                if not valid:
                    return False

            return True
        else:
            # Simple variable - just check if key exists
            return var_name in context

    @staticmethod
    def resolve_value(var_name: str, context: dict[str, Any]) -> Optional[Any]:
        """Resolve a variable name (possibly with path and array indices) from context.

        Handles path traversal for nested data access:
        - 'url' -> context['url']
        - 'data.field' -> context['data']['field']
        - 'data.field.subfield' -> context['data']['field']['subfield']
        - 'data.items[0]' -> context['data']['items'][0]
        - 'data.items[0].name' -> context['data']['items'][0]['name']

        Args:
            var_name: Variable name with optional path and array indices
            context: Dictionary containing values to resolve from

        Returns:
            Resolved value or None if path cannot be resolved
        """
        if "." in var_name or "[" in var_name:
            # Split on dots, but not dots inside brackets
            # This regex splits on dots that are not followed by ] without [
            parts = re.split(r"\.(?![^\[]*\])", var_name)
            value = context

            for part in parts:
                # Check if this part has array indices
                # Match: name[0] or name[0][1]
                array_match = re.match(r"^([^[]+)((?:\[\d+\])+)$", part)

                if array_match:
                    base_name = array_match.group(1)
                    indices_str = array_match.group(2)  # e.g., "[0][1]"

                    # Get the base value (with JSON auto-parsing)
                    found, value = TemplateResolver._get_dict_value(value, base_name)
                    if not found:
                        logger.debug(
                            f"Cannot resolve path '{var_name}': '{base_name}' not found",
                            extra={"var_name": var_name, "failed_at": base_name},
                        )
                        return None

                    # Parse JSON string if needed before array access
                    value = TemplateResolver._try_parse_json_for_traversal(value)

                    # Extract and apply all indices
                    indices = re.findall(r"\[(\d+)\]", indices_str)
                    for index_str in indices:
                        index = int(index_str)
                        if isinstance(value, list) and 0 <= index < len(value):
                            value = value[index]
                        else:
                            logger.debug(
                                f"Cannot resolve path '{var_name}': index {index} out of bounds or not a list",
                                extra={"var_name": var_name, "failed_at": f"{part}[{index}]"},
                            )
                            return None
                else:
                    # Regular property access (with JSON auto-parsing)
                    found, value = TemplateResolver._get_dict_value(value, part)
                    if not found:
                        logger.debug(
                            f"Cannot resolve path '{var_name}': '{part}' not found",
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
        - dict/list -> JSON serialized (for valid JSON in templates)
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
        elif isinstance(value, (dict, list)):
            # Use JSON serialization for dicts/lists to produce valid JSON
            # (not Python repr with single quotes)
            try:
                return json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                # Fallback for non-serializable objects
                return str(value)
        else:
            return str(value)

    @staticmethod
    def resolve_template(template: str, context: dict[str, Any]) -> Any:
        """Resolve a template string to its value.

        For simple templates (entire string is "${var}"), preserves the original type.
        For complex templates (text around variables), returns a string.
        Template variables that cannot be resolved are left unchanged for debugging.

        Args:
            template: String containing template variables
            context: Dictionary containing values to resolve from

        Returns:
            - For simple templates: The resolved value with original type preserved
            - For complex templates: String with variables interpolated
            - For unresolved templates: The template string unchanged

        Examples:
            >>> context = {"data": {"name": "Alice"}, "count": 42, "url": "https://example.com"}
            >>> TemplateResolver.resolve_template("${data}", context)
            {'name': 'Alice'}  # Dict preserved
            >>> TemplateResolver.resolve_template("${count}", context)
            42  # Int preserved
            >>> TemplateResolver.resolve_template("Visit ${url}", context)
            'Visit https://example.com'  # String (complex template)
            >>> TemplateResolver.resolve_template("Missing: ${undefined}", context)
            'Missing: ${undefined}'
        """
        # Pre-process nested index templates: ${outer[${inner}]} -> ${outer[0]}
        template = TemplateResolver.resolve_nested_index_templates(template, context)

        # Check for simple template first - preserve type
        var_name = TemplateResolver.extract_simple_template_var(template)
        if var_name is not None:
            if TemplateResolver.variable_exists(var_name, context):
                resolved = TemplateResolver.resolve_value(var_name, context)
                logger.debug(
                    f"Resolved simple template '${{{var_name}}}' -> {resolved!r} (type: {type(resolved).__name__})",
                    extra={"var_name": var_name, "value_type": type(resolved).__name__},
                )
                return resolved
            else:
                # Variable doesn't exist - return template unchanged for debugging
                logger.debug(
                    f"Simple template variable '${{{var_name}}}' could not be resolved",
                    extra={"var_name": var_name},
                )
                return template

        # Complex template - do string interpolation
        result = template

        # Find all template variables in the string
        for match in TemplateResolver.TEMPLATE_PATTERN.finditer(template):
            var_name = match.group(1)  # Get the variable name without ${}
            resolved_value = TemplateResolver.resolve_value(var_name, context)

            # Note: We need to distinguish between:
            # 1. "value not found" (template should remain)
            # 2. "value is None at the end of path" (convert to empty string)
            # 3. "None in middle of path" (can't traverse, template should remain)

            if "." in var_name or "[" in var_name:
                # Path traversal - check if we successfully resolved
                # Extract base variable (before first dot or bracket)
                base_var = re.split(r"[\.\[]", var_name)[0]
                # Base exists and full path is valid - combine the conditions
                if base_var in context and TemplateResolver.variable_exists(var_name, context):
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
            # Provide more helpful warnings for common patterns
            if ".response." in var_name:
                # This pattern often indicates LLM didn't generate expected JSON structure
                logger.warning(
                    f"Template variable '${{{var_name}}}' could not be resolved. "
                    f"This often indicates the LLM node didn't generate the expected JSON structure. "
                    f"Check that the LLM response contains the field '{var_name.split('.')[-1]}'"
                )
            else:
                logger.debug(f"Template variable '${{{var_name}}}' could not be resolved", extra={"var_name": var_name})

        return result

    @staticmethod
    def resolve_nested(value: Any, context: dict[str, Any]) -> Any:
        """Recursively resolve template variables in nested structures.

        Handles dictionaries, lists, and nested combinations while preserving
        the original structure and types. Simple templates (${var}) preserve
        their original type, while complex templates return strings.

        For simple templates that resolve to JSON strings, the JSON is automatically
        parsed in two contexts:
        1. Path traversal (Task 105): ${node.stdout.field} - parses to access nested paths
        2. Inline objects (this feature): {"data": "${node.stdout}"} - parses for structured data

        This enables patterns like {"data": "${shell.stdout}"} where stdout contains JSON.
        Complex templates (e.g., "prefix ${var}") are the escape hatch for keeping raw
        JSON strings.

        Args:
            value: The value to resolve (can be string, dict, list, or any type)
            context: Dictionary containing values to resolve from

        Returns:
            The value with all template variables resolved, maintaining structure

        Examples:
            >>> context = {"token": "abc123", "data": {"name": "Alice"}}
            >>> params = {"headers": {"Authorization": "Bearer ${token}"}}
            >>> TemplateResolver.resolve_nested(params, context)
            {'headers': {'Authorization': 'Bearer abc123'}}
            >>> TemplateResolver.resolve_nested({"user": "${data}"}, context)
            {'user': {'name': 'Alice'}}  # Type preserved
            >>> context = {"shell": {"stdout": '{"items": [1, 2, 3]}'}}
            >>> TemplateResolver.resolve_nested({"data": "${shell.stdout}"}, context)
            {'data': {'items': [1, 2, 3]}}  # JSON auto-parsed
        """
        if isinstance(value, str):
            # Resolve string templates (preserves type for simple templates)
            if "${" in value:
                resolved = TemplateResolver.resolve_template(value, context)

                # Auto-parse JSON strings from simple templates
                # This enables: {"data": "${shell.stdout}"} where stdout is JSON
                # Escape hatch: complex templates like "prefix ${var}" stay as strings
                #
                # IMPORTANT: Only use parsed result if it's dict/list (containers).
                # json.loads("1458059302022549698") returns int, but we want to preserve
                # numeric strings as strings (e.g., Discord snowflake IDs).
                #
                # Tech debt note (see Task 105): Same JSON string may be parsed multiple
                # times if used in multiple templates. Acceptable for MVP since parsing
                # is <1ms vs node execution 100-1000ms. Consider caching if profiling
                # shows this as a bottleneck.
                if isinstance(resolved, str) and TemplateResolver.is_simple_template(value):
                    success, parsed = try_parse_json(resolved)
                    if success and isinstance(parsed, (dict, list)):
                        logger.debug(
                            f"Auto-parsed JSON from template '{value}': {type(parsed).__name__}",
                        )
                        return parsed

                return resolved
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
