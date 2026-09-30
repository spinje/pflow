"""The ``${…}`` template language: detection, path walk, and resolution.

Template variables use the format ${identifier} with optional path traversal
(${data.field.subfield}). ``resolve()`` returns a ``Resolution`` — the value plus
what stayed literal — the single judge of "unresolved" for every runtime consumer.
Lives in ``core/`` so the validator and the runtime share one module; it imports
only ``pflow.core`` (pinned by ``tests/test_core/test_templates_module.py``).
"""

import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

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
    # Must not be preceded by $: `$${` is the escape for a literal `${`.
    TEMPLATE_PATTERN = re.compile(rf"(?<!\$)\$\{{({_COALESCE_EXPR_PATTERN})\}}")

    # Single-pass interpolation: each match is an escape (`$${` -> `${`), a template,
    # or an Issue — an unescaped `${` that opens no template (kept verbatim; only its
    # `${` is consumed, so a template nested after it still resolves). One
    # left-to-right pass means resolved values are never re-scanned.
    _INTERPOLATION_PATTERN = re.compile(
        rf"(?P<escape>\$\$\{{)|(?<!\$)\$\{{(?P<expr>{_COALESCE_EXPR_PATTERN})\}}|(?P<issue>(?<!\$)\$\{{)"
    )

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

    # The opening of a dynamic-index reference (`${a[${` …) — a template the pre-pass
    # could not rewrite (inner absent / non-int), never an Issue.
    _DYNAMIC_INDEX_OPEN = re.compile(r"\$\{" + _VAR_NAME_PATTERN + r"\[\$\{")
    # One dynamic index inside its outer reference: group 1 is `${outer` up to the `[`.
    _DYNAMIC_INDEX = re.compile(r"(\$\{" + _VAR_NAME_PATTERN + r")\[\$\{" + _VAR_NAME_PATTERN + r"\}\]")

    @staticmethod
    def has_templates(value: Any) -> bool:
        """Check if value contains template syntax that resolution rewrites.

        That is a template variable or a `$${` escape — an escape-only value still
        needs resolving to become its literal `${...}`. Recursively checks nested
        dictionaries and lists.

        Args:
            value: The value to check for templates (string, dict, list, or any)

        Returns:
            True if value contains template syntax anywhere in its structure
        """
        if isinstance(value, str):
            return "$${" in value or bool(TemplateResolver.TEMPLATE_PATTERN.search(value))
        elif isinstance(value, dict):
            return any(TemplateResolver.has_templates(v) for v in value.values())
        elif isinstance(value, list):
            return any(TemplateResolver.has_templates(item) for item in value)
        else:
            return False

    @staticmethod
    def resolve_nested_index_templates(template: str, context: Mapping[str, Any]) -> str:
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
    def resolve_coalesce(expr: str, context: Mapping[str, Any]) -> tuple[Any, str]:
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

            # Root absent (branch didn't run) OR field/path absent — either way
            # "not there": try the next operand (issue #441). A bare reference
            # with no fallback falls out of the loop as "unresolved" below.
            found, value = TemplateResolver._walk(TemplateResolver._split_raw_path(operand), context)
            if found:
                return (value, "resolved")

        return (None, "unresolved")

    @staticmethod
    def extract_simple_template_var(value: str) -> str | None:
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

    # Raw-path lexer: split on dots outside brackets, then peel a trailing
    # `[N][M]…` chain off each part. No identifier grammar — user-typed paths
    # (`-o result.@type`, `read-fields result.dc:title`) walk as written.
    _RAW_DOT_SPLIT = re.compile(r"\.(?![^\[]*\])")
    _RAW_INDEXED_PART = re.compile(r"^([^[]+)((?:\[\d+\])+)$")

    @staticmethod
    def _split_raw_path(path: str) -> list[tuple[str, tuple[int, ...]]]:
        """Split a raw path into ``(key, indices)`` parts: ``"a.b[1][2].c"`` ->
        ``[("a", ()), ("b", (1, 2)), ("c", ())]``."""
        parts: list[tuple[str, tuple[int, ...]]] = []
        for part in TemplateResolver._RAW_DOT_SPLIT.split(path):
            match = TemplateResolver._RAW_INDEXED_PART.match(part)
            if match:
                indices = tuple(int(i) for i in re.findall(r"\d+", match.group(2)))
                parts.append((match.group(1), indices))
            else:
                parts.append((part, ()))
        return parts

    @staticmethod
    def _walk(parts: list[tuple[str, tuple[int, ...]]], context: Mapping[str, Any]) -> tuple[bool, Any]:
        """The one path walk: ``(found, value)``.

        Found means the walk reached a value — possibly ``None`` (a found ``None``
        is not "missing"). A key reads a Mapping, auto-parsing a JSON-container
        string first; an index chain needs a list (a JSON-array string is parsed
        once, before the chain) and ``0 <= N < len``. Anything else — including
        walking on through a ``None`` — is not found.
        """
        current: Any = context
        for key, indices in parts:
            found, current = TemplateResolver._get_dict_value(current, key)
            if not found:
                return False, None
            if indices:
                current = TemplateResolver._try_parse_json_for_traversal(current)
            for index in indices:
                if not isinstance(current, list) or index >= len(current):
                    return False, None
                current = current[index]
        return True, current

    @staticmethod
    def variable_exists(var_name: str, context: Mapping[str, Any]) -> bool:
        """Check if a variable exists in context, regardless of its value.

        This method distinguishes between "variable doesn't exist" and
        "variable exists but has None value".

        Args:
            var_name: Variable name with optional path and array indices
            context: Mapping containing values to check

        Returns:
            True if variable exists (even if None), False if not found
        """
        return TemplateResolver._walk(TemplateResolver._split_raw_path(var_name), context)[0]

    @staticmethod
    def resolve_value(var_name: str, context: Mapping[str, Any]) -> Any | None:
        """Resolve a variable name (possibly with path and array indices) from context.

        Handles path traversal for nested data access:
        - 'url' -> context['url']
        - 'data.field' -> context['data']['field']
        - 'data.field.subfield' -> context['data']['field']['subfield']
        - 'data.items[0]' -> context['data']['items'][0]
        - 'data.items[0].name' -> context['data']['items'][0]['name']

        Args:
            var_name: Variable name with optional path and array indices
            context: Mapping containing values to resolve from

        Returns:
            Resolved value or None if path cannot be resolved (use
            ``variable_exists`` to tell a found ``None`` from a miss)
        """
        return TemplateResolver._walk(TemplateResolver._split_raw_path(var_name), context)[1]

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
    def resolve_template(template: str, context: Mapping[str, Any]) -> Any:
        """Resolve a template string to its value (``resolve(template, context).value``).

        For simple templates (entire string is "${var}"), preserves the original type.
        For complex templates (text around variables), returns a string.
        Template variables that cannot be resolved are left unchanged for debugging.
        Each `$${` escape becomes a literal `${`.

        Args:
            template: String containing template variables
            context: Mapping containing values to resolve from

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
        return resolve(template, context).value

    @staticmethod
    def _lookup_expression(expr: str, context: Mapping[str, Any]) -> tuple[bool, Any]:
        """Resolve one template expression (the text inside ``${…}``): ``(found, value)``.

        A coalesce takes its first operand that resolves; a bare literal is its
        JSON value (a literal that does not parse is not found — the validator
        reports it); anything else is one walk.
        """
        if TemplateResolver.is_coalesce_expression(expr):
            value, status = TemplateResolver.resolve_coalesce(expr, context)
            return status == "resolved", value
        if TemplateResolver.is_literal_operand(expr):
            return try_parse_json(expr)
        return TemplateResolver._walk(TemplateResolver._split_raw_path(expr), context)

    @staticmethod
    def _resolve_string(template: str, context: Mapping[str, Any], auto_parse: bool) -> "Resolution":
        """``resolve()`` for one string; see ``resolve``."""
        # Pre-process nested index templates: ${outer[${inner}]} -> ${outer[0]}
        source = TemplateResolver.resolve_nested_index_templates(template, context)

        # Simple template: the whole string is one expression — preserve its type
        var_name = TemplateResolver.extract_simple_template_var(source)
        if var_name is not None:
            found, value = TemplateResolver._lookup_expression(var_name, context)
            if not found:
                logger.debug(f"Template '${{{var_name}}}' could not be resolved", extra={"var_name": var_name})
                return Resolution(source, unresolved=frozenset({var_name}))
            # resolve_nested's leaf rule: a simple template's JSON-container string is
            # parsed (numeric strings stay strings — Discord snowflake IDs). Gated on the
            # AUTHOR text being simple, so a rewritten dynamic index is not parsed.
            if auto_parse and isinstance(value, str) and TemplateResolver.is_simple_template(template):
                success, parsed = try_parse_json(value)
                if success and isinstance(parsed, (dict, list)):
                    return Resolution(parsed)
            return Resolution(value)

        # Complex template: one left-to-right pass — substituted values are never re-scanned
        unresolved: set[str] = set()
        issues: set[str] = set()
        changed = source != template  # the nested-index pre-pass rewrote an index

        def interpolate(match: re.Match[str]) -> str:
            nonlocal changed
            if match.group("escape"):
                changed = True
                return "${"
            if match.group("issue"):
                if not TemplateResolver._DYNAMIC_INDEX_OPEN.match(source, match.start()):
                    close = source.find("}", match.start())
                    issues.add(source[match.start() :] if close == -1 else source[match.start() : close + 1])
                return match.group(0)
            expr = match.group("expr")
            found, value = TemplateResolver._lookup_expression(expr, context)
            if found:
                changed = True
                return TemplateResolver._convert_to_string(value)
            unresolved.add(expr)
            TemplateResolver._log_unresolved_inline(expr)
            return match.group(0)

        text = TemplateResolver._INTERPOLATION_PATTERN.sub(interpolate, source)
        # Interim rule (Task 170 phase 2; the typed parse reports every Issue): an Issue
        # counts only in a string resolution left untouched — the class the old
        # "value echoes its template" check caught. Beside a resolved expression or an
        # escape it rides along silently, as before (`source: prefix ${n.x}`). An
        # un-rewritten dynamic index is judged by its inner reference alone, as before.
        return Resolution(text, unresolved=frozenset(unresolved), issues=frozenset() if changed else frozenset(issues))

    @staticmethod
    def _log_unresolved_inline(var_expr: str) -> None:
        if ".response." in var_expr:
            logger.warning(
                f"Template variable '${{{var_expr}}}' could not be resolved. "
                f"This often indicates the LLM node didn't generate the expected JSON structure. "
                f"Check that the LLM response contains the field '{var_expr.split('.')[-1]}'"
            )
        else:
            logger.debug(f"Template variable '${{{var_expr}}}' could not be resolved", extra={"var_name": var_expr})

    @staticmethod
    def resolve_nested(value: Any, context: Mapping[str, Any]) -> Any:
        """Recursively resolve template variables in nested structures
        (``resolve(value, context, auto_parse=True).value``).

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
            context: Mapping containing values to resolve from

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
        return resolve(value, context, auto_parse=True).value


@dataclass(frozen=True, slots=True)
class Resolution:
    """A resolved value plus what resolution had to leave literal.

    ``unresolved`` holds the text inside ``${…}`` of every expression that stayed
    literal (for a dynamic index, the rewritten ``a[0].x``); ``issues`` holds each
    unescaped ``${`` that opens no template, from the ``${`` to its first ``}`` (for
    now only in a string resolution left untouched — see ``_resolve_string``).
    Both span the whole value. Text that came FROM a resolved value is never in
    either — only the author's template is judged (#630). The channels stay
    distinct so a surface can tolerate Issues without tolerating misses (#621).
    """

    value: Any
    unresolved: frozenset[str] = frozenset()
    issues: frozenset[str] = frozenset()

    @property
    def ok(self) -> bool:
        return not self.unresolved and not self.issues

    @staticmethod
    def combine(value: Any, parts: Iterable["Resolution"]) -> "Resolution":
        """``value`` carrying the union of ``parts``' channels (a container's resolution)."""
        parts = tuple(parts)
        return Resolution(
            value,
            unresolved=frozenset().union(*(p.unresolved for p in parts)),
            issues=frozenset().union(*(p.issues for p in parts)),
        )


def resolve(value: Any, context: Mapping[str, Any], *, auto_parse: bool = False) -> Resolution:
    """Resolve every template in ``value`` against ``context``.

    A string resolves exactly as ``resolve_template`` (no top-level JSON auto-parse);
    dicts and lists recurse, keys untouched. ``auto_parse=True`` adds
    ``resolve_nested``'s leaf rule at every string leaf, the top-level one included:
    a simple template's resolved JSON-container string is parsed. Other values pass
    through unchanged.
    """
    if isinstance(value, str):
        if "${" not in value:
            return Resolution(value)
        return TemplateResolver._resolve_string(value, context, auto_parse)
    if isinstance(value, dict):
        entries = {key: resolve(item, context, auto_parse=auto_parse) for key, item in value.items()}
        return Resolution.combine({key: r.value for key, r in entries.items()}, entries.values())
    if isinstance(value, list):
        items = [resolve(item, context, auto_parse=auto_parse) for item in value]
        return Resolution.combine([r.value for r in items], items)
    return Resolution(value)
