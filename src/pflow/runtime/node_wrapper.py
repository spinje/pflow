"""Template-aware node wrapper for transparent template resolution.

This module provides a wrapper that intercepts node execution to resolve
template variables in parameters. It's the runtime proxy that enables
pflow's "Plan Once, Run Forever" philosophy.
"""

import logging
from typing import Any, Optional

from pflow.core.json_utils import try_parse_json
from pflow.core.param_coercion import coerce_to_declared_type

from .template_resolver import TemplateResolver

logger = logging.getLogger(__name__)


class TemplateAwareNodeWrapper:
    """Wraps nodes to provide transparent template resolution.

    This wrapper intercepts the node's _run() method to resolve template
    variables just before execution. It maintains complete transparency
    to the rest of the system - the wrapper behaves exactly like the
    wrapped node except for template resolution.

    This is the runtime proxy that enables "Plan Once, Run Forever".

    Defensive Measures:
    - Recursion depth limit (100 levels) prevents theoretical stack overflow
      from maliciously crafted deeply nested structures. Real workflows
      never approach this depth, but the limit ensures robustness.
    """

    def __init__(
        self,
        inner_node: Any,
        node_id: str,
        initial_params: Optional[dict[str, Any]] = None,
        template_resolution_mode: str = "strict",
        interface_metadata: Optional[dict[str, Any]] = None,
    ):
        """Initialize the wrapper.

        Args:
            inner_node: The actual node being wrapped
            node_id: Node identifier from IR (for debugging/tracking)
            initial_params: Parameters extracted by planner from natural language
                          These have higher priority than shared store values
            template_resolution_mode: Template resolution mode ('strict' or 'permissive')
                                     strict: fail immediately on unresolved templates (default)
                                     permissive: warn and continue with unresolved templates
            interface_metadata: Node interface metadata from registry (optional)
                              Contains input/param type information for validation
        """
        self.inner_node = inner_node
        self.node_id = node_id  # Node ID for debugging purposes only
        self.initial_params = initial_params or {}  # From planner extraction
        self.template_resolution_mode = template_resolution_mode  # Resolution behavior
        self.interface_metadata = interface_metadata  # Type information for validation
        self.template_params: dict[str, Any] = {}  # Params containing templates
        self.static_params: dict[str, Any] = {}  # Params without templates

        # Build type cache for performance (one-time cost)
        self._expected_types = self._build_type_cache()

    def set_params(self, params: dict[str, Any]) -> None:
        """Separate template params from static params.

        Called by PocketFlow when setting node parameters. We separate
        parameters containing templates from static ones for efficient
        resolution later.

        Args:
            params: Parameters to set on the node
        """
        self.template_params.clear()
        self.static_params.clear()

        for key, value in params.items():
            if TemplateResolver.has_templates(value):
                self.template_params[key] = value
                logger.debug(
                    f"Node '{self.node_id}' param '{key}' contains templates",
                    extra={"node_id": self.node_id, "param": key},
                )
            else:
                # Apply type coercion for static params (dict/list → str when expected)
                # This mirrors the coercion applied to template params at runtime
                expected_type = self._expected_types.get(key)
                coerced_value = coerce_to_declared_type(value, expected_type)
                self.static_params[key] = coerced_value

        # Set only static params on inner node for now
        self.inner_node.set_params(self.static_params)

        logger.debug(
            f"Node '{self.node_id}' params categorized",
            extra={
                "node_id": self.node_id,
                "template_param_count": len(self.template_params),
                "static_param_count": len(self.static_params),
            },
        )

    def _build_type_cache(self) -> dict[str, str]:
        """Build param_key -> expected_type mapping for performance.

        This is called once during initialization to avoid repeated
        lookups during template resolution.

        Returns:
            Dictionary mapping parameter keys to their expected types.
            Empty dict if no interface metadata available.
        """
        if not self.interface_metadata:
            return {}

        types = {}

        # Extract types from inputs (defensive: handle both array and dict formats)
        inputs = self.interface_metadata.get("inputs", [])
        if isinstance(inputs, list):
            for input_spec in inputs:
                if isinstance(input_spec, dict):
                    key = input_spec.get("key")
                    type_str = input_spec.get("type")
                    if key and type_str:
                        types[key] = type_str

        # Extract types from params (defensive: handle both array and dict formats)
        params = self.interface_metadata.get("params", [])
        if isinstance(params, list):
            for param_spec in params:
                if isinstance(param_spec, dict):
                    key = param_spec.get("key")
                    type_str = param_spec.get("type")
                    if key and type_str:
                        types[key] = type_str

        logger.debug(
            f"Built type cache for node '{self.node_id}'",
            extra={"node_id": self.node_id, "type_count": len(types), "types": types},
        )

        return types

    def _build_type_error_message(
        self,
        param_key: str,
        resolved_value: Any,
        template_str: str,
        expected_type: str,
        actual_type: str,
    ) -> str:
        """Build detailed, actionable error message for type mismatch.

        Args:
            param_key: Parameter name
            resolved_value: The resolved value (wrong type)
            template_str: Original template string
            expected_type: Expected type from metadata
            actual_type: Actual type of resolved value

        Returns:
            Formatted multi-section error message with fix suggestions
        """
        import re

        # Extract variable name from template for suggestions
        var_match = re.search(r"\$\{([^}]+)\}", template_str)
        var_name = var_match.group(1) if var_match else "variable"

        # Build base error
        error_msg = (
            f"Parameter '{param_key}' expects {expected_type} but received {actual_type}\n\n"
            f"Template used: {template_str}\n"
            f"Resolved to: {actual_type} object\n"
        )

        # Add fix suggestions
        error_msg += "\n💡 Common fixes:\n"

        # Fix 1: Serialize to JSON (works for dict/list)
        error_msg += "  1. Serialize to JSON (recommended):\n"
        error_msg += f'     {param_key}: "{template_str}"\n\n'

        # Fix 2: Access specific field (for dicts) or item (for lists)
        if isinstance(resolved_value, dict):
            error_msg += "  2. Access a specific field:\n"
            error_msg += f"     {param_key}: ${{{var_name}.field_name}}\n\n"
        elif isinstance(resolved_value, list):
            error_msg += "  2. Access a specific item:\n"
            error_msg += f"     {param_key}: ${{{var_name}[0]}}\n\n"

        # Fix 3: Combine with text
        error_msg += "  3. Combine with text:\n"
        error_msg += f'     {param_key}: "Summary: {template_str}"\n'

        # Show available fields/items for dicts
        if isinstance(resolved_value, dict) and resolved_value:
            keys = list(resolved_value.keys())[:10]  # Limit to 10 keys
            error_msg += f"\n\nAvailable fields in {var_name}:\n"
            for key in keys:
                error_msg += f"  - {key}\n"

            if len(resolved_value) > 10:
                remaining = len(resolved_value) - 10
                error_msg += f"  ... and {remaining} more\n"

        # Show item count for lists
        elif isinstance(resolved_value, list):
            error_msg += f"\n\n{var_name} contains {len(resolved_value)} items\n"
            if len(resolved_value) > 0:
                error_msg += f"Access items with: ${{{var_name}[0]}}, ${{{var_name}[1]}}, etc.\n"

        return error_msg

    def _build_json_parse_error_message(
        self,
        param_key: str,
        resolved_value: str,
        template_str: str,
        expected_type: str,
        trimmed: str,
    ) -> str:
        """Build detailed error message for failed JSON parsing.

        Args:
            param_key: Parameter name
            resolved_value: The malformed JSON string
            template_str: Original template string
            expected_type: Expected type (dict/list/object/array)
            trimmed: Trimmed version of resolved_value

        Returns:
            Formatted error message with suggestions
        """
        # Preview of malformed JSON (limit to 200 chars)
        preview = trimmed[:200]
        if len(trimmed) > 200:
            preview += "..."

        # Detect common JSON issues
        issues = []
        if "'" in trimmed:
            issues.append("Single quotes detected (use double quotes: \"key\" not 'key')")
        if trimmed.count("{") != trimmed.count("}"):
            issues.append("Mismatched braces { }")
        if trimmed.count("[") != trimmed.count("]"):
            issues.append("Mismatched brackets [ ]")
        if ",}" in trimmed or ",]" in trimmed:
            issues.append("Trailing comma before closing brace/bracket")

        error_lines = [
            f"Parameter '{param_key}' expects {expected_type} but received malformed JSON string.",
            "",
            f"Template: {template_str}",
            f"Value preview: {preview}",
            "",
            f"The string starts with '{trimmed[0]}' suggesting JSON, but failed to parse.",
        ]

        if issues:
            error_lines.append("")
            error_lines.append("Detected issues:")
            for issue in issues:
                error_lines.append(f"  - {issue}")

        error_lines.extend([
            "",
            "Common JSON formatting issues:",
            "  - Missing closing brace/bracket",
            "  - Single quotes instead of double quotes",
            "  - Trailing commas in arrays/objects",
            "  - Unescaped special characters",
            "  - Missing quotes around object keys",
            "",
            "Fix: Ensure the source outputs valid JSON.",
            f"Test with: echo '{template_str}' | jq '.'",
        ])

        return "\n".join(error_lines)

    def _validate_resolved_type(self, param_key: str, resolved_value: Any, template_str: str) -> None:
        """Validate that resolved value type matches expected parameter type.

        This prevents type mismatches like passing a dict to a string parameter,
        which would result in Python repr garbage being sent to external APIs.

        Args:
            param_key: Parameter name being validated
            resolved_value: Value after template resolution
            template_str: Original template string (for error message)

        Raises:
            ValueError: If type mismatch detected in strict mode
                       Prefixed with __PERMISSIVE_TYPE_ERROR__: in permissive mode
        """
        # Skip if no type information available (graceful degradation)
        expected_type = self._expected_types.get(param_key)
        if not expected_type:
            logger.debug(
                f"No type info for param '{param_key}' in node '{self.node_id}', skipping validation",
                extra={"node_id": self.node_id, "param": param_key},
            )
            return

        # Only skip validation for truly polymorphic "any" type
        if expected_type == "any":
            logger.debug(
                f"Param '{param_key}' has polymorphic type 'any', accepting any value",
                extra={"node_id": self.node_id, "param": param_key},
            )
            return

        # Only validate string parameters receiving dicts/lists
        # (other type mismatches can be added later)
        if expected_type == "str" and isinstance(resolved_value, (dict, list)):
            actual_type = type(resolved_value).__name__

            # Build enhanced error message with fix suggestions
            error_msg = self._build_type_error_message(
                param_key, resolved_value, template_str, expected_type, actual_type
            )

            logger.error(
                error_msg,
                extra={
                    "node_id": self.node_id,
                    "param": param_key,
                    "expected": expected_type,
                    "actual": actual_type,
                },
            )

            # In strict mode: fail immediately
            # In permissive mode: prefix with special marker for handling in _run()
            if self.template_resolution_mode == "strict":
                raise ValueError(error_msg)
            else:
                # Raise ValueError with special marker for permissive mode handling
                logger.warning(
                    f"Type validation failed in permissive mode (node: {self.node_id}, param: {param_key})",
                    extra={"node_id": self.node_id, "param": param_key},
                )
                raise ValueError(f"__PERMISSIVE_TYPE_ERROR__:{error_msg}")

        # Positive checks: dict/list parameters receiving correct types → OK
        if expected_type in ("dict", "object") and isinstance(resolved_value, dict):
            return  # Correct type match

        if expected_type in ("list", "array") and isinstance(resolved_value, list):
            return  # Correct type match

        # dict/list parameters receiving strings → likely failed JSON parse
        if expected_type in ("dict", "list", "object", "array") and isinstance(resolved_value, str):
            trimmed = resolved_value.strip()

            # Check if it looks like JSON (starts with { or [)
            if trimmed and trimmed[0] in ("{", "["):
                # Looks like JSON but is still string → parsing must have failed
                error_msg = self._build_json_parse_error_message(
                    param_key, resolved_value, template_str, expected_type, trimmed
                )

                logger.error(
                    error_msg,
                    extra={
                        "node_id": self.node_id,
                        "param": param_key,
                        "expected": expected_type,
                        "actual": "str (malformed JSON)",
                    },
                )

                if self.template_resolution_mode == "strict":
                    raise ValueError(error_msg)
                else:
                    logger.warning(
                        f"JSON parse validation failed in permissive mode (node: {self.node_id}, param: {param_key})",
                        extra={"node_id": self.node_id, "param": param_key},
                    )
                    raise ValueError(f"__PERMISSIVE_TYPE_ERROR__:{error_msg}")

    def _check_string_unresolved(self, resolved_value: str, original_template: str) -> bool:
        """Check if a string contains unresolved templates.

        Args:
            resolved_value: The resolved string
            original_template: The original template string

        Returns:
            True if contains unresolved templates, False otherwise
        """
        # Case 1: Completely unresolved (no change at all)
        if resolved_value == original_template:
            return "${" in resolved_value

        # Case 2: Partially resolved - check if any original variables remain
        if "${" in resolved_value:
            # Extract variables from both original and resolved strings
            original_vars = TemplateResolver.extract_variables(original_template)
            remaining_vars = TemplateResolver.extract_variables(resolved_value)

            # If any original variable is still present, it's unresolved
            if original_vars & remaining_vars:  # Set intersection
                logger.debug(
                    f"Partial template resolution detected. Original vars: {original_vars}, "
                    f"Remaining vars: {remaining_vars}",
                    extra={"node_id": self.node_id},
                )
                return True

        return False

    def _check_list_unresolved(self, resolved_value: list, original_template: list, _depth: int = 0) -> bool:
        """Check if a list contains unresolved templates.

        Args:
            resolved_value: The resolved list
            original_template: The original template list
            _depth: Current recursion depth

        Returns:
            True if contains unresolved templates, False otherwise
        """
        # If lengths differ, something was resolved
        if len(resolved_value) != len(original_template):
            return False

        # Check each item - if any item is unchanged and contains ${...}, it's unresolved
        for resolved_item, template_item in zip(resolved_value, original_template):
            if self._contains_unresolved_template(resolved_item, template_item, _depth + 1):
                return True
        return False

    def _check_dict_unresolved(self, resolved_value: dict, original_template: dict, _depth: int = 0) -> bool:
        """Check if a dict contains unresolved templates.

        Args:
            resolved_value: The resolved dict
            original_template: The original template dict
            _depth: Current recursion depth

        Returns:
            True if contains unresolved templates, False otherwise
        """
        # If keys differ, something changed
        if set(resolved_value.keys()) != set(original_template.keys()):
            return False

        # Check each value
        for key in resolved_value:
            if self._contains_unresolved_template(resolved_value[key], original_template[key], _depth + 1):
                return True
        return False

    def _contains_unresolved_template(self, resolved_value: Any, original_template: Any, _depth: int = 0) -> bool:
        """Check if a resolved value contains unresolved templates.

        This handles the complexity of:
        1. String templates that didn't resolve
        2. Lists/dicts with unresolved templates inside
        3. Avoiding false positives from resolved MCP data containing ${...}
        4. Partial resolution detection (some variables resolved, others not)

        Args:
            resolved_value: The value after template resolution
            original_template: The original template before resolution
            _depth: Current recursion depth (internal parameter for defensive limits)

        Returns:
            True if contains unresolved templates, False otherwise
        """
        # Defensive depth limit to prevent theoretical stack overflow
        # No real workflow would have 100+ levels of nesting, but this prevents
        # malicious or corrupted data from causing issues
        MAX_DEPTH = 100
        if _depth > MAX_DEPTH:
            logger.debug(
                f"Template validation depth limit ({MAX_DEPTH}) reached for node '{self.node_id}'. "
                "Assuming resolved to prevent stack overflow.",
                extra={"node_id": self.node_id, "depth": _depth},
            )
            return False  # Assume resolved to continue execution

        # Strategy: If resolved_value != original_template, then resolution changed something
        # So even if it contains ${...}, that's from resolved data, not an unresolved template
        # Only flag as unresolved if the value is UNCHANGED and contains ${...}

        # For strings: Check both complete and partial resolution
        if isinstance(resolved_value, str) and isinstance(original_template, str):
            return self._check_string_unresolved(resolved_value, original_template)

        # For lists: Check if unchanged (failed to resolve templates inside)
        if isinstance(resolved_value, list) and isinstance(original_template, list):
            return self._check_list_unresolved(resolved_value, original_template, _depth)

        # For dicts: Check if unchanged (failed to resolve templates inside)
        if isinstance(resolved_value, dict) and isinstance(original_template, dict):
            return self._check_dict_unresolved(resolved_value, original_template, _depth)

        # For any other type: If it's not a string/list/dict, it can't contain templates
        return False

    def _build_resolution_context(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Build the context for template resolution.

        Combines shared store data with initial parameters from planner.
        Planner parameters have higher priority.

        Args:
            shared: The shared store containing runtime data

        Returns:
            Combined context dictionary
        """
        context = dict(shared)  # Start with shared store data
        context.update(self.initial_params)  # Planner parameters override

        # Debug: Log context keys when we have template params
        if self.template_params and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Template resolution context for node '{self.node_id}' has keys: {list(context.keys())[:20]}",
                extra={"node_id": self.node_id, "initial_params_keys": list(self.initial_params.keys())},
            )

        return context

    def _resolve_simple_template(self, template: str, context: dict[str, Any]) -> tuple[Any, bool]:
        """Resolve a simple template variable like '${var}'.

        Uses shared helper from TemplateResolver for consistent simple template detection.

        Args:
            template: Template string to resolve
            context: Resolution context

        Returns:
            Tuple of (resolved_value, was_simple_template)
        """
        # Use shared helper for simple template detection
        var_name = TemplateResolver.extract_simple_template_var(template)
        if var_name is None:
            return None, False

        # Check if variable exists (even if its value is None)
        if TemplateResolver.variable_exists(var_name, context):
            # Variable exists - resolve and preserve its type (including None)
            resolved_value = TemplateResolver.resolve_value(var_name, context)
            logger.debug(
                f"Resolved simple template: ${{{var_name}}} -> {resolved_value!r} "
                f"(type: {type(resolved_value).__name__})",
                extra={"node_id": self.node_id},
            )
            return resolved_value, True
        else:
            # Variable doesn't exist - keep template as-is for debugging
            logger.debug(
                f"Template variable '${{{var_name}}}' not found in context, keeping template as-is",
                extra={"node_id": self.node_id},
            )
            return template, True

    def _resolve_template_parameter(self, key: str, template: Any, context: dict[str, Any]) -> tuple[Any, bool]:
        """Resolve a single template parameter.

        Args:
            key: Parameter name
            template: Template value to resolve
            context: Resolution context

        Returns:
            Tuple of (resolved_value, is_simple_template)
        """
        # Handle nested structures (dict or list)
        if isinstance(template, (dict, list)):
            resolved_value = TemplateResolver.resolve_nested(template, context)
            logger.debug(
                f"Resolved nested template param '{key}' (type: {type(template).__name__})",
                extra={"node_id": self.node_id, "param": key},
            )
            return resolved_value, False

        # Handle string templates
        if isinstance(template, str) and "${" in template:
            # Try simple template first
            resolved_value, is_simple = self._resolve_simple_template(template, context)
            if is_simple:
                return resolved_value, True

            # Complex template with text around it, must be string
            resolved_value = TemplateResolver.resolve_template(template, context)
            return resolved_value, False

        # No template variables present, preserve original type
        return template, False

    def _format_template_display(self, template: Any) -> str:
        """Format template value for display.

        Args:
            template: Template value to format

        Returns:
            Formatted string representation
        """
        if isinstance(template, list):
            # For list parameters, show the actual values cleanly
            return " ".join(str(item) for item in template)
        elif isinstance(template, dict):
            # For dict parameters, show as clean JSON
            import json

            return json.dumps(template, indent=2)
        else:
            # For strings and other types, show as-is
            return str(template)

    def _format_available_keys(self, available_display: list[str], context: dict[str, Any]) -> list[str]:
        """Format available keys section with type information.

        Args:
            available_display: List of keys to display (may include "... and N more")
            context: Resolution context

        Returns:
            List of formatted key lines
        """
        lines = ["Available context keys:"]

        for key in available_display:
            if key.startswith("... and"):
                lines.append(f"  {key}")
            else:
                value = context.get(key)
                value_type = type(value).__name__
                # Show preview for simple types
                if isinstance(value, (str, int, float, bool)) and not isinstance(value, bool):
                    preview = str(value)[:50]
                    if len(str(value)) > 50:
                        preview += "..."
                    lines.append(f"  • {key} ({value_type}): {preview}")
                else:
                    lines.append(f"  • {key} ({value_type})")

        return lines

    def _generate_suggestions(self, variables: set[str], available_keys: list[str]) -> list[str]:
        """Generate suggestions for close matches.

        Args:
            variables: Set of unresolved variable names
            available_keys: Available context keys

        Returns:
            List of suggestion strings
        """
        suggestions = []
        for var in variables:
            # For nested paths like "mynode.stdout", check if the first part
            # (node ID) is similar to any available key
            parts = var.split(".")
            node_id = parts[0]
            rest_of_path = ".".join(parts[1:]) if len(parts) > 1 else ""

            node_id_lower = node_id.lower()
            node_id_normalized = node_id.replace("_", "-").replace("-", "")

            for key in available_keys[:20]:
                if not isinstance(key, str):
                    continue

                key_lower = key.lower()
                key_normalized = key.replace("_", "-").replace("-", "")

                # Check for similar node IDs (handles typos like mynode vs my-node)
                is_similar = (
                    node_id_lower == key_lower
                    or node_id_normalized == key_normalized
                    or node_id_lower in key_lower
                    or key_lower in node_id_lower
                )

                if is_similar and node_id != key:
                    # Build the corrected variable path
                    corrected = f"{key}.{rest_of_path}" if rest_of_path else key
                    suggestions.append(f"Did you mean '${{{corrected}}}'? (instead of '${{{var}}}')")
                    break

        return suggestions[:3]  # Limit to 3 suggestions

    def _detect_json_parse_hints(self, variables: set[str], context: dict[str, Any]) -> list[str]:
        """Detect if unresolved variables failed due to JSON parsing issues.

        When a variable like ${node.stdout.field} fails to resolve, check if
        node.stdout exists and is a string (not valid JSON). This helps users
        understand why nested access failed.

        Args:
            variables: Set of unresolved variable names
            context: Resolution context

        Returns:
            List of hint strings explaining JSON parse failures
        """
        hints = []

        for var in variables:
            parts = var.split(".")
            if len(parts) < 3:
                # Not a nested path like node.output.field
                continue

            # Check if parent path exists and is a string
            # e.g., for "node.stdout.field", check if "node.stdout" is a string
            node_id = parts[0]
            output_key = parts[1]

            if node_id in context and isinstance(context[node_id], dict):
                node_data = context[node_id]
                if output_key in node_data:
                    value = node_data[output_key]
                    if isinstance(value, str):
                        # Found it - the parent is a string, not parsed JSON
                        preview = value[:60] + "..." if len(value) > 60 else value
                        # Clean up preview for display (escape newlines)
                        preview = preview.replace("\n", "\\n")
                        hints.append(
                            f"${{{node_id}.{output_key}}} is a string, not JSON. "
                            f"Nested access (.{'.'.join(parts[2:])}) requires valid JSON."
                        )
                        hints.append(f'  Actual value: "{preview}"')
                        break  # One hint is enough

        return hints

    def _build_enhanced_template_error(self, param_key: str, template: str, context: dict[str, Any]) -> str:
        """Build detailed error message for unresolved template.

        Args:
            param_key: Parameter name
            template: Original template string
            context: Resolution context (shared store + initial params)

        Returns:
            Formatted error message with context and suggestions
        """
        # Extract variable names from template
        all_variables = TemplateResolver.extract_variables(str(template))

        # Filter to only actually unresolved variables (not in context)
        # This prevents misleading errors like "${provided}, ${missing}" when only ${missing} failed
        variables = {v for v in all_variables if not TemplateResolver.variable_exists(v, context)}

        # Build available keys section
        available_keys = [k for k in context if not k.startswith("__")]
        available_keys.sort()

        # Limit to 20 keys for readability
        if len(available_keys) > 20:
            available_display = available_keys[:20]
            available_display.append(f"... and {len(available_keys) - 20} more")
        else:
            available_display = available_keys

        # Simplified single-line error message (removes redundancy)
        # Only report actually unresolved variables
        error_parts = [f"Unresolved variables in parameter '{param_key}': {', '.join(f'${{{v}}}' for v in variables)}"]

        # Add available keys section (only if there are keys to show)
        if available_keys:
            error_parts.append("")
            error_parts.extend(self._format_available_keys(available_display, context))

        # Check for JSON parsing failures (most actionable hint for this feature)
        json_hints = self._detect_json_parse_hints(variables, context)
        if json_hints:
            error_parts.append("")
            error_parts.append("⚠️ JSON parsing issue:")
            for hint in json_hints:
                error_parts.append(f"  {hint}")
            error_parts.append("  Fix: Ensure upstream node outputs valid JSON.")

        # Add suggestions for close matches (only if no JSON hints - avoid confusion)
        if not json_hints:
            suggestions = self._generate_suggestions(variables, available_keys)
            if suggestions:
                error_parts.append("")
                error_parts.append("💡 Suggestions:")
                for s in suggestions:
                    error_parts.append(f"  {s}")

        return "\n".join(error_parts)

    def _run(self, shared: dict[str, Any]) -> Any:  # noqa: C901
        """Execute with template resolution.

        This is the key interception point. We resolve templates just
        before execution, using both the shared store (runtime data)
        and initial parameters (from planner).

        Args:
            shared: The shared store containing runtime data

        Returns:
            Result from the inner node's execution
        """
        # Skip resolution if no templates
        if not self.template_params:
            return self.inner_node._run(shared)

        logger.debug(
            f"Resolving {len(self.template_params)} template parameters for node '{self.node_id}'",
            extra={"node_id": self.node_id},
        )

        # Build resolution context
        context = self._build_resolution_context(shared)

        # Resolve all template parameters
        resolved_params = {}
        for key, template in self.template_params.items():
            resolved_value, is_simple_template = self._resolve_template_parameter(key, template, context)

            # Auto-parse JSON strings for structured parameters (only simple templates)
            # This enables shell+jq → MCP patterns without requiring LLM intermediate steps
            if is_simple_template and isinstance(resolved_value, str):
                expected_type = self._expected_types.get(key)
                if expected_type in ("dict", "list", "object", "array"):
                    success, parsed = try_parse_json(resolved_value)
                    # Type-safe: only use if parsed type matches expected
                    type_matches = (expected_type in ("dict", "object") and isinstance(parsed, dict)) or (
                        expected_type in ("list", "array") and isinstance(parsed, list)
                    )
                    if success and type_matches:
                        resolved_value = parsed
                        logger.debug(
                            f"Auto-parsed JSON string to {type(parsed).__name__} for param '{key}'",
                            extra={"node_id": self.node_id, "param": key},
                        )

            # REVERSE: Serialize dict/list → str when expected type is str
            # This enables MCP tools that declare `param: str` but expect JSON content
            # Applies to both simple templates (${var} → dict) and inline objects ({"key": "${var}"})
            if isinstance(resolved_value, (dict, list)):
                expected_type = self._expected_types.get(key)
                resolved_value = coerce_to_declared_type(resolved_value, expected_type)

            # NEW: Validate type for simple templates (before storing in resolved_params)
            # Complex templates are already stringified, so no type mismatch possible
            if is_simple_template:
                try:
                    self._validate_resolved_type(key, resolved_value, str(template))
                except ValueError as e:
                    # Check if permissive mode error
                    if str(e).startswith("__PERMISSIVE_TYPE_ERROR__:"):
                        # Extract actual message and store as warning
                        actual_msg = str(e).replace("__PERMISSIVE_TYPE_ERROR__:", "")
                        if "__template_errors__" not in shared:
                            shared["__template_errors__"] = {}
                        shared["__template_errors__"][self.node_id] = {
                            "message": actual_msg,
                            "type": "type_validation",
                            "param": key,
                        }
                        # Continue execution in permissive mode
                    else:
                        # Strict mode - enrich with upstream stderr context before re-raising
                        # Lazy import to keep error path lightweight - only loaded when errors occur
                        from pflow.runtime.error_context import get_upstream_stderr

                        upstream_context = get_upstream_stderr(str(template), context)
                        if upstream_context:
                            raise ValueError(str(e) + upstream_context) from None
                        raise

            resolved_params[key] = resolved_value

            # Check if template was fully resolved (for BOTH simple and complex templates)
            # We need to check differently for strings vs nested structures:
            #
            # For STRINGS: Check if unchanged AND contains ${...}
            #   - This catches actual unresolved templates
            #   - Avoids false positives from resolved strings that happen to contain ${...}
            #
            # For LISTS/DICTS: Recursively check if any string inside contains ${...}
            #   - BUT only if the template itself contained ${...}
            #   - This catches unresolved templates in nested structures
            #   - Avoids false positives from resolved MCP data containing ${...}
            is_unresolved = self._contains_unresolved_template(resolved_value, template)

            if is_unresolved:
                # Template failed to resolve - still contains ${...}
                # This happens when variable doesn't exist in context
                # Build enhanced error message with context and suggestions
                error_msg = self._build_enhanced_template_error(key, template, context)

                if self.template_resolution_mode == "strict":
                    # Strict mode: Fail immediately
                    # Use DEBUG level to avoid duplication in CLI output (error will be shown by CLI)
                    logger.debug(
                        error_msg,
                        extra={"node_id": self.node_id, "param": key, "mode": "strict"},
                    )
                    # Add upstream stderr context if available
                    # Lazy import to keep error path lightweight - only loaded when errors occur
                    from pflow.runtime.error_context import get_upstream_stderr

                    upstream_context = get_upstream_stderr(str(template), context)
                    if upstream_context:
                        error_msg += upstream_context
                    # Make template errors fatal to trigger repair
                    raise ValueError(error_msg)
                else:
                    # Permissive mode: Warn and continue with unresolved template
                    # Use DEBUG level to avoid showing timestamps/file paths
                    # The warning is displayed in the summary section at the end
                    logger.debug(
                        f"{error_msg}\n(permissive mode: continuing with unresolved template)",
                        extra={"node_id": self.node_id, "param": key, "mode": "permissive"},
                    )
                    # Store error in shared store for workflow status (DEGRADED)
                    if "__template_errors__" not in shared:
                        shared["__template_errors__"] = {}
                    shared["__template_errors__"][self.node_id] = {
                        "message": error_msg,
                        "unresolved": [key],
                        "template": template,
                    }
                    # Continue execution with unresolved template (literal ${...} passed to node)
            elif resolved_value != template:
                # Successfully resolved - log for debugging
                logger.debug(
                    f"Resolved param '{key}': '{template}' -> '{resolved_value}'",
                    extra={"node_id": self.node_id, "param": key},
                )

        # Temporarily update inner node params with resolved values
        original_params = self.inner_node.params
        merged_params = {**self.static_params, **resolved_params}
        self.inner_node.params = merged_params

        try:
            # Execute with resolved params
            result = self.inner_node._run(shared)
            return result
        finally:
            # Restore original params (though node copy will be discarded)
            # This is defensive programming in case the node is reused
            self.inner_node.params = original_params

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attributes to inner node.

        This makes the wrapper transparent - any attribute access
        not handled by the wrapper goes to the inner node.

        Args:
            name: Attribute name to access

        Returns:
            Attribute value from inner node
        """
        # Prevent infinite recursion during copy operations
        if name in ("__setstate__", "__getstate__", "__getnewargs__", "__getnewargs_ex__"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        # Get inner_node without triggering __getattr__ again
        inner = object.__getattribute__(self, "inner_node")
        return getattr(inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Handle attribute setting to maintain proxy transparency.

        We need to distinguish between wrapper's own attributes and
        attributes that should be set on the inner node.

        Args:
            name: Attribute name to set
            value: Value to set
        """
        # Define proxy's own attributes
        wrapper_attrs = {"inner_node", "node_id", "initial_params", "template_params", "static_params"}

        if name in wrapper_attrs:
            # Set on wrapper itself
            super().__setattr__(name, value)
        else:
            # Delegate to inner node
            setattr(self.inner_node, name, value)

    def __repr__(self) -> str:
        """String representation for debugging."""
        inner_repr = repr(self.inner_node)
        return f"TemplateAwareNodeWrapper({inner_repr}, node_id='{self.node_id}')"

    # Delegate PocketFlow operators
    def __rshift__(self, other: Any) -> Any:
        """Delegate >> operator to inner node."""
        return self.inner_node >> other

    def __sub__(self, action: str) -> Any:
        """Delegate - operator to inner node."""
        return self.inner_node - action
