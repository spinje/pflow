"""Template variable detection and resolution with path support.

This module provides the core functionality for detecting and resolving
template variables in node parameters. Template variables use the format
${identifier} with optional path traversal (${data.field.subfield}).
"""

import json
import logging
import re
from collections.abc import Mapping
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

    # Literal operand sub-grammar for coalesce (Optional A). Matches JSON literals:
    # double-quoted strings (with escapes), word-bounded true/false/null,
    # integers/floats including negatives, and the empty array/object literals.
    # Composite [..]/{..} with content are deliberately excluded — `??` fallbacks
    # are small values; complex literals belong in a code node. Word boundaries on
    # the keyword alternatives prevent `truthy_value` from matching literal `true`.
    #
    # This grammar MUST match only what `try_parse_json` + `split_coalesce_operands`
    # can actually handle at runtime, or a literal validates clean then silently
    # fails to resolve:
    #   - The number branch forbids leading zeros (`-?(?:0|[1-9]\d*)`) because JSON
    #     rejects `007`/`01`; matching them here would pass validation but leave the
    #     template unresolved at runtime.
    #   - The string branch forbids the `??` sequence (`\?(?!\?)` allows a lone `?`)
    #     because the operand splitter splits on `??` and would shred a string
    #     containing it. A single `?` inside a string is fine.
    _LITERAL_PATTERN = (
        r'(?:"(?:[^"\\?]|\\.|\?(?!\?))*"|\btrue\b|\bfalse\b|\bnull\b|-?(?:0|[1-9]\d*)(?:\.\d+)?|\[\]|\{\})'
    )

    # A coalesce operand is a literal OR a variable path. Literal is tried first
    # so keyword literals win over same-spelled identifiers (documented limitation).
    _OPERAND_PATTERN = rf"(?:{_LITERAL_PATTERN}|{_VAR_NAME_PATTERN})"

    # Coalesce expression: one or more operands separated by ??
    # Matches: "a", "a ?? b", "a.field ?? b.field[0] ?? c", "a ?? 0", "0", '"x"'
    _COALESCE_EXPR_PATTERN = rf"{_OPERAND_PATTERN}(?:\s*\?\?\s*{_OPERAND_PATTERN})*"

    # Pattern for finding templates in strings (can match multiple)
    # Must not be preceded by $ (to avoid $${var} escapes)
    TEMPLATE_PATTERN = re.compile(rf"(?<!\$)\$\{{({_COALESCE_EXPR_PATTERN})\}}")

    # Loose extraction pattern for validation/diagnostics code.
    # Captures everything between ${ and } (including coalesce ??).
    # Handles $$ escape but does NOT validate variable name format.
    # Use this for template discovery, NOT for resolution.
    TEMPLATE_EXTRACT_PATTERN = re.compile(r"(?<!\$)\$\{([^}]+)\}")

    # Pattern for detecting simple templates (entire string is exactly one ${var})
    # Used to determine when to preserve type vs stringify
    # Uses same strict variable name pattern as TEMPLATE_PATTERN
    SIMPLE_TEMPLATE_PATTERN = re.compile(rf"^\$\{{({_COALESCE_EXPR_PATTERN})\}}$")

    # Pattern for bracket index templates: [${var}] anywhere in a string.
    # Resolves inner ${var} to a static integer for array indexing.
    # Examples: ${results[${__index__}].field}, ${a[${idx}].x ?? b.x}
    # Captures: (1) the full inner template including ${...}
    _BRACKET_INDEX_PATTERN = re.compile(r"\[(\$\{" + _VAR_NAME_PATTERN + r"\})\]")

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
            return bool(TemplateResolver.TEMPLATE_PATTERN.search(value))
        elif isinstance(value, dict):
            return any(TemplateResolver.has_templates(v) for v in value.values())
        elif isinstance(value, list):
            return any(TemplateResolver.has_templates(item) for item in value)
        else:
            return False

    @staticmethod
    def resolve_nested_index_templates(template: str, context: dict[str, Any]) -> str:
        """Pre-process bracket index templates by resolving [${var}] to [N].

        Finds [${var}] patterns anywhere in the string and replaces them with
        static integer indices. This is context-free — it doesn't need to
        understand the surrounding template structure, so it naturally composes
        with coalesce (${a[${idx}].x ?? b.x}) and any future syntax.

        Examples:
            ${results[${__index__}].field}  ->  ${results[0].field}
            ${a[${idx}].x ?? b.x}           ->  ${a[0].x ?? b.x}
            ${matrix[${row}][${col}]}       ->  ${matrix[0][1]}

        Non-integer inner values or missing variables leave [${var}] unchanged.

        Args:
            template: String that may contain bracket index templates
            context: Dictionary containing values to resolve inner templates from

        Returns:
            Template string with bracket indices resolved to static values
        """
        if "${" not in template or "[${" not in template:
            return template

        # Limit iterations to prevent infinite loops with malformed templates
        max_iterations = 10
        for _ in range(max_iterations):
            match = TemplateResolver._BRACKET_INDEX_PATTERN.search(template)
            if not match:
                break

            inner_template = match.group(1)  # e.g., "${__index__}"

            # Extract variable name from inner template
            inner_var = TemplateResolver.extract_simple_template_var(inner_template)
            if inner_var is None:
                break

            # Resolve inner variable
            resolved_inner = TemplateResolver.resolve_value(inner_var, context)
            if resolved_inner is None:
                break

            # Must resolve to integer for array indexing
            if not isinstance(resolved_inner, int):
                logger.warning(
                    f"Nested index must be integer, got {type(resolved_inner).__name__}",
                    extra={"template": template, "inner_value": resolved_inner},
                )
                break

            # Replace [${var}] with [N] in-place
            template = template[: match.start()] + f"[{resolved_inner}]" + template[match.end() :]

        return template

    @staticmethod
    def extract_variables(value: str) -> set[str]:
        """Extract all template variable names (including paths).

        For coalesce expressions like ${a ?? b}, extracts both 'a' and 'b'.

        Args:
            value: String that may contain template variables

        Returns:
            Set of variable names found (e.g., {'url', 'data.field'})
        """
        raw_matches = set(TemplateResolver.TEMPLATE_PATTERN.findall(value))
        variables: set[str] = set()
        for match in raw_matches:
            for operand in TemplateResolver.split_coalesce_operands(match):
                # Literal operands (Optional A) are values, not dependencies.
                if TemplateResolver.is_literal_operand(operand):
                    continue
                variables.add(operand)
        return variables

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

    # Compiled pattern for splitting coalesce expressions on ??
    _COALESCE_SPLIT_PATTERN = re.compile(r"\s*\?\?\s*")

    # Compiled pattern for extracting root variable name (before first . or [)
    _ROOT_SPLIT_PATTERN = re.compile(r"[\.\[]")

    @staticmethod
    def split_coalesce_operands(expr: str) -> list[str]:
        """Split a coalesce expression on ?? into individual operands.

        Operands may be variable paths or literals. Returns single-element
        list if no ?? present.
        """
        if "??" not in expr:
            return [expr]
        return [op.strip() for op in TemplateResolver._COALESCE_SPLIT_PATTERN.split(expr)]

    @staticmethod
    def is_literal_operand(operand: str) -> bool:
        """Whether a coalesce operand looks like a JSON literal (not a variable).

        This is a COARSE first-char check: literals start with one of ``{ [ " -``
        or a digit, OR are exactly the keywords ``true`` / ``false`` / ``null``;
        variable identifiers always start with ``[a-zA-Z_]``. Identifiers like
        ``truthy_value`` start with ``t`` but are not the bare keyword, so they
        correctly resolve as variables.

        It is intentionally BROADER than ``_LITERAL_PATTERN`` — e.g. it returns
        True for ``01`` and ``[1,2]`` which the regex rejects. The regex is the
        load-bearing gate: ``TEMPLATE_PATTERN`` / ``_PERMISSIVE_PATTERN`` (built
        from it) decide what reaches resolution, so an operand only gets here
        after the regex already classified the whole template as valid. This
        predicate's job is then "given a grammar-accepted operand, is it a literal
        or a path?" — not to re-validate literal shape. Do not assume
        ``is_literal_operand(x)`` implies ``try_parse_json(x)`` succeeds.

        Examples:
            >>> TemplateResolver.is_literal_operand("0")
            True
            >>> TemplateResolver.is_literal_operand('"hello"')
            True
            >>> TemplateResolver.is_literal_operand("true")
            True
            >>> TemplateResolver.is_literal_operand("node.field")
            False
            >>> TemplateResolver.is_literal_operand("truthy_value")
            False
        """
        if not operand:
            return False
        if operand[0] in '{["-0123456789':
            return True
        return operand in ("true", "false", "null")

    @staticmethod
    def is_coalesce_expression(expr: str) -> bool:
        """Check if a template expression contains the coalesce operator ??."""
        return "??" in expr

    @staticmethod
    def extract_root_node_id(template_path: str) -> str:
        """Extract root node ID from a template path.

        Examples:
            >>> TemplateResolver.extract_root_node_id("node")
            'node'
            >>> TemplateResolver.extract_root_node_id("node.field")
            'node'
            >>> TemplateResolver.extract_root_node_id("node.field[0].sub")
            'node'
            >>> TemplateResolver.extract_root_node_id("data[0]")
            'data'
        """
        return TemplateResolver._ROOT_SPLIT_PATTERN.split(template_path, maxsplit=1)[0]

    @staticmethod
    def extract_first_field_segment(var: str) -> str | None:
        """Return the first field segment after the root, bracketless.

        Used by template error helpers to find/suggest field names when a
        variable like ``node.field.sub`` or ``node.field[0]`` fails to
        resolve. Returns ``None`` when the path has no field segment
        (bare root like ``node`` or ``data[0]``).

        Examples:
            >>> TemplateResolver.extract_first_field_segment("node.field")
            'field'
            >>> TemplateResolver.extract_first_field_segment("node.field.sub")
            'field'
            >>> TemplateResolver.extract_first_field_segment("node.field[0]")
            'field'
            >>> TemplateResolver.extract_first_field_segment("node.field[0].nested")
            'field'
            >>> TemplateResolver.extract_first_field_segment("node")

            >>> TemplateResolver.extract_first_field_segment("data[0]")

            >>> TemplateResolver.extract_first_field_segment("node[0].field")
            'field'
        """
        parts = var.split(".", 1)
        if len(parts) != 2:
            return None
        return parts[1].split(".", 1)[0].split("[", 1)[0]

    @staticmethod
    def resolve_coalesce(expr: str, context: dict[str, Any]) -> tuple[Any, str]:
        """Resolve a coalesce expression, trying operands left to right.

        Semantics:
        - For each operand, extract root node (first segment before . or [)
        - If root is ABSENT from context -> skip (branch didn't execute), try next
        - If root is PRESENT and full path resolves -> return resolved value
        - If root is PRESENT but the field/path is absent -> skip, try next

        ``??`` falls through whenever the left side "isn't there" — whether the
        node didn't run OR the field is missing — matching ``??`` / ``//`` /
        ``default()`` in JS, C#, jq, and Jinja (issue #441). A bare
        ``${node.field}`` with no fallback yields "unresolved" below, which
        strict mode surfaces as an error, so genuine typos are still caught.
        (Workflow ``## Outputs`` declarations use a stricter coalesce in
        ``output_resolver._is_all_absent_coalesce`` that does NOT fall through on
        a recovered-node failure — that surface intentionally differs.)

        Returns:
            Tuple of (value, status) where status is:
            - "resolved": value is the successfully resolved result
            - "unresolved": no operand resolved; value is None

        Call only via ``resolve_template`` / ``_resolve_complex_match``. Those
        entry points gate on the strict ``TEMPLATE_PATTERN`` grammar, so by the
        time an operand reaches here it is already a grammar-valid literal or
        variable path. The literal short-circuit below uses the coarse
        ``is_literal_operand`` predicate plus ``try_parse_json`` — calling this
        directly with an operand the grammar would reject (e.g. ``[1,2]``) can
        resolve a literal the validator forbids.
        """
        operands = TemplateResolver.split_coalesce_operands(expr)

        for operand in operands:
            # Literal operand (Optional A): a JSON value used as a fallback.
            # Always "resolves" — short-circuits the chain.
            if TemplateResolver.is_literal_operand(operand):
                ok, value = try_parse_json(operand)
                if ok:
                    return (value, "resolved")
                # Looked like a literal but didn't parse (e.g. unterminated
                # string) — skip; the validator surfaces a targeted error.
                continue

            root = TemplateResolver._ROOT_SPLIT_PATTERN.split(operand)[0]

            if root not in context:
                continue  # Root absent — branch didn't execute, try next

            if TemplateResolver.variable_exists(operand, context):
                return (TemplateResolver.resolve_value(operand, context), "resolved")
            # Root present but field/path absent — treat like "not there" and
            # try the next operand (issue #441). A bare reference with no
            # fallback falls out of the loop as "unresolved" below.

        return (None, "unresolved")

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
            >>> TemplateResolver.extract_simple_template_var("Hello ${name}") is None
            True
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
            # Only use parsed result if it's a container (dict/list) we can traverse.
            # Primitives (int, float, bool) are NOT parsed to preserve numeric strings
            # like Discord snowflake IDs ("1458059302022549698" should stay as string,
            # not become int 1458059302022549698). See bug fix for numeric string coercion.
            logger.debug(
                f"Auto-parsed JSON string for path traversal: {type(parsed).__name__}",
            )
            return parsed
        return value

    @staticmethod
    def _get_dict_value(value: Any, key: str) -> tuple[bool, Any]:
        """Get a key from a dict-like value, with JSON string auto-parsing.

        Tries to access value[key], auto-parsing JSON strings if needed.

        Accepts any ``collections.abc.Mapping`` — not just ``dict`` — so
        dict-like proxies (notably ``runtime/engine/namespaced_store.NamespacedSharedStore``,
        which engine wraps ``shared`` in for ``node._run`` calls) work for
        dotted-path resolution. Without this, every ``${node.field}`` reference
        resolved through such a proxy silently echoes the literal template —
        Task 159 cache rendering hit this on its prep-side re-resolution path.

        Args:
            value: Mapping, JSON string, or other value
            key: Key to access

        Returns:
            Tuple of (success, result) where success indicates if key was found
        """
        # Mapping access (dict, NamespacedSharedStore, MappingProxyType, ...)
        if isinstance(value, Mapping) and key in value:
            return True, value[key]

        # JSON string auto-parsing
        if isinstance(value, str):
            parsed = TemplateResolver._try_parse_json_for_traversal(value)
            if isinstance(parsed, Mapping) and key in parsed:
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
            >>> TemplateResolver.resolve_template("${data}", context)  # dict preserved
            {'name': 'Alice'}
            >>> TemplateResolver.resolve_template("${count}", context)  # int preserved
            42
            >>> TemplateResolver.resolve_template("Visit ${url}", context)  # complex template -> string
            'Visit https://example.com'
            >>> TemplateResolver.resolve_template("Missing: ${undefined}", context)
            'Missing: ${undefined}'
        """
        # Pre-process nested index templates: ${outer[${inner}]} -> ${outer[0]}
        template = TemplateResolver.resolve_nested_index_templates(template, context)

        # Check for simple template first - preserve type
        var_name = TemplateResolver.extract_simple_template_var(template)
        if var_name is not None:
            if TemplateResolver.is_coalesce_expression(var_name):
                value, status = TemplateResolver.resolve_coalesce(var_name, context)
                if status == "resolved":
                    logger.debug(
                        f"Resolved coalesce template '${{{var_name}}}' -> {value!r} (type: {type(value).__name__})",
                        extra={"var_name": var_name, "value_type": type(value).__name__},
                    )
                    return value
                # unresolved (no operand resolved): return template unchanged
                return template
            elif TemplateResolver.is_literal_operand(var_name):
                # Bare literal template (Optional A): ${0}, ${"x"}, ${null}.
                ok, value = try_parse_json(var_name)
                if ok:
                    return value
                # Malformed literal — leave unchanged; validator surfaces it.
                return template
            elif TemplateResolver.variable_exists(var_name, context):
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
        for match in TemplateResolver.TEMPLATE_PATTERN.finditer(template):
            result = TemplateResolver._resolve_complex_match(match.group(1), result, context)
        return result

    @staticmethod
    def _resolve_complex_match(var_expr: str, result: str, context: dict[str, Any]) -> str:
        """Resolve a single template match within a complex template string.

        Args:
            var_expr: The variable expression captured from ${...}
            result: Current result string being built
            context: Resolution context

        Returns:
            Updated result string with this match resolved (or unchanged if unresolvable)
        """
        # Handle coalesce expressions
        if TemplateResolver.is_coalesce_expression(var_expr):
            value, status = TemplateResolver.resolve_coalesce(var_expr, context)
            if status == "resolved":
                value_str = TemplateResolver._convert_to_string(value)
                result = result.replace(f"${{{var_expr}}}", value_str)
                logger.debug(
                    f"Resolved coalesce template '${{{var_expr}}}' -> '{value_str}'",
                    extra={"var_name": var_expr, "value_type": type(value).__name__},
                )
            # unresolved (no operand resolved): leave template as-is
            return result

        # Bare literal in an inline template (Optional A): "Hello ${0}".
        if TemplateResolver.is_literal_operand(var_expr):
            ok, value = try_parse_json(var_expr)
            if ok:
                value_str = TemplateResolver._convert_to_string(value)
                result = result.replace(f"${{{var_expr}}}", value_str)
            return result

        # Non-coalesce: existing resolution logic
        var_name = var_expr
        resolved_value = TemplateResolver.resolve_value(var_name, context)

        if "." in var_name or "[" in var_name:
            # Path traversal - check if we successfully resolved
            base_var = TemplateResolver._ROOT_SPLIT_PATTERN.split(var_name)[0]
            if base_var in context and TemplateResolver.variable_exists(var_name, context):
                value_str = TemplateResolver._convert_to_string(resolved_value)
                result = result.replace(f"${{{var_name}}}", value_str)
                logger.debug(
                    f"Resolved template variable '${{{var_name}}}' -> '{value_str}'",
                    extra={"var_name": var_name, "value_type": type(resolved_value).__name__},
                )
                return result
        elif var_name in context:
            value_str = TemplateResolver._convert_to_string(resolved_value)
            result = result.replace(f"${{{var_name}}}", value_str)
            logger.debug(
                f"Resolved template variable '${{{var_name}}}' -> '{value_str}'",
                extra={"var_name": var_name, "value_type": type(resolved_value).__name__},
            )
            return result

        # Variable doesn't exist - leave template as-is for debugging
        if ".response." in var_name:
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
            >>> TemplateResolver.resolve_nested({"user": "${data}"}, context)  # type preserved
            {'user': {'name': 'Alice'}}
            >>> context = {"shell": {"stdout": '{"items": [1, 2, 3]}'}}
            >>> TemplateResolver.resolve_nested({"data": "${shell.stdout}"}, context)  # JSON auto-parsed
            {'data': {'items': [1, 2, 3]}}
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
