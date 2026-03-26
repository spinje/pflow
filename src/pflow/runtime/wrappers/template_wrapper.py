"""Template-aware node wrapper for transparent template resolution.

This module provides a wrapper that intercepts node execution to resolve
template variables in parameters. It's the runtime proxy that enables
pflow's "Plan Once, Run Forever" philosophy.
"""

import logging
from typing import Any, Optional

from pflow.core.json_utils import try_parse_json
from pflow.core.param_coercion import coerce_to_declared_type

from ..template_resolver import TemplateResolver
from .template_errors import (
    build_enhanced_template_error,
    build_json_parse_error_message,
    build_type_error_message,
)

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
        optional_input_keys: Optional[set[str]] = None,
    ):
        """Initialize the wrapper.

        Args:
            inner_node: The actual node being wrapped
            node_id: Node identifier from IR (for debugging/tracking)
            initial_params: Parameters provided before execution
                          These have higher priority than shared store values
            template_resolution_mode: Template resolution mode ('strict' or 'permissive')
                                     strict: fail immediately on unresolved templates (default)
                                     permissive: warn and continue with unresolved templates
            interface_metadata: Node interface metadata from registry (optional)
                              Contains input/param type information for validation
            optional_input_keys: Set of input keys (within the ``inputs`` dict param)
                               that are annotated as optional in the code node's source.
                               When the source node for these inputs didn't execute,
                               None is injected instead of raising an unresolved error.
        """
        self.inner_node = inner_node
        self.node_id = node_id  # Node ID for debugging purposes only
        self.initial_params = initial_params or {}  # Seeded before execution
        self.template_resolution_mode = template_resolution_mode  # Resolution behavior
        self.interface_metadata = interface_metadata  # Type information for validation
        self.optional_input_keys = optional_input_keys or set()  # Branch convergence
        self.template_params: dict[str, Any] = {}  # Params containing templates
        self.static_params: dict[str, Any] = {}  # Params without templates
        self.last_resolutions: dict[str, Any] = {}  # Template resolutions for trace capture

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
            error_msg = build_type_error_message(param_key, resolved_value, template_str, expected_type, actual_type)

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
                error_msg = build_json_parse_error_message(
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

    @staticmethod
    def _all_variables_from_absent_nodes(template_str: str, context: dict[str, Any]) -> bool:
        """Check if all template variables reference nodes absent from context.

        Uses ``all()`` not ``any()`` — critical for coalesce correctness.
        With ``${a ?? b}``, ``extract_variables`` returns ``{"a.stdout", "b.stdout"}``.
        In normal convergence only ONE root is absent, so ``all()`` returns False
        and injection is skipped — letting coalesce resolution handle it. Only when
        ALL roots are absent (neither branch ran) should we inject None.
        """
        variables = TemplateResolver.extract_variables(template_str)
        if not variables:
            return False
        return all(var.split(".")[0].split("[")[0] not in context for var in variables)

    def _inject_none_for_optional_inputs(
        self,
        key: str,
        resolved_value: Any,
        template: Any,
        context: dict[str, Any],
    ) -> Any:
        """Replace unresolved optional input templates with None.

        For code nodes with optional input annotations (``T | None`` or
        ``Optional[T]``), when the source node didn't execute (its namespace
        is absent from the shared store), inject ``None`` instead of leaving
        the unresolved ``${...}`` template string.

        Preserves error detection for typos: when the source node DID execute
        (root present in context) but the field path is wrong, the template
        stays unresolved and the normal error fires.
        """
        if key != "inputs" or not self.optional_input_keys:
            return resolved_value

        if not isinstance(resolved_value, dict) or not isinstance(template, dict):
            return resolved_value

        modified = dict(resolved_value)
        for input_key in self.optional_input_keys:
            if input_key not in modified or input_key not in template:
                continue

            input_value = modified[input_key]
            input_template = template[input_key]

            # Only process if this value is still an unresolved template string
            if not isinstance(input_value, str) or "${" not in input_value:
                continue
            if not isinstance(input_template, str) or input_value != input_template:
                continue  # Partially resolved or non-string template — don't touch

            if self._all_variables_from_absent_nodes(input_template, context):
                modified[input_key] = None
                logger.debug(
                    f"Injected None for optional input '{input_key}' (source node not executed): {input_template}",
                    extra={"node_id": self.node_id, "input_key": input_key},
                )

        return modified

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

        Combines shared store data with initial parameters provided before execution.
        Initial parameters have higher priority.

        Args:
            shared: The shared store containing runtime data

        Returns:
            Combined context dictionary
        """
        context = dict(shared)  # Start with shared store data
        context.update(self.initial_params)  # Initial parameters override

        # Debug: Log context keys when we have template params
        if self.template_params and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Template resolution context for node '{self.node_id}' has keys: {list(context.keys())[:20]}",
                extra={"node_id": self.node_id, "initial_params_keys": list(self.initial_params.keys())},
            )

        return context

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
            is_simple = TemplateResolver.is_simple_template(template)
            resolved_value = TemplateResolver.resolve_template(template, context)
            return resolved_value, is_simple

        # No template variables present, preserve original type
        return template, False

    def resolve_templates(self, shared: dict[str, Any]) -> dict[str, Any]:  # noqa: C901
        """Resolve all template params against shared store context.

        Returns merged_params (static + resolved template params).
        Side effects: sets self.last_resolutions (for trace capture).

        Args:
            shared: The shared store containing runtime data

        Returns:
            Merged parameters dictionary (static + resolved template params)
        """
        if not self.template_params:
            return dict(self.static_params)

        logger.debug(
            f"Resolving {len(self.template_params)} template parameters for node '{self.node_id}'",
            extra={"node_id": self.node_id},
        )

        # Build resolution context
        context = self._build_resolution_context(shared)

        # Enrich context with inputs values so other params (e.g., prompt)
        # can reference input-mapped variables. Handles both static inputs
        # (no templates) and template inputs (resolved first below).
        static_inputs = self.static_params.get("inputs")
        if isinstance(static_inputs, dict):
            context.update(static_inputs)

        # Process 'inputs' before other params so its resolved values
        # are available as template context (e.g., for prompt resolution)
        param_keys = list(self.template_params.keys())
        if "inputs" in param_keys:
            param_keys.remove("inputs")
            param_keys.insert(0, "inputs")

        # Resolve all template parameters
        resolved_params: dict[str, Any] = {}
        for key in param_keys:
            template = self.template_params[key]
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
                        from .error_context import get_upstream_stderr

                        upstream_context = get_upstream_stderr(str(template), context)
                        # Store resolutions for trace capture before raising
                        # (on error: contains all params resolved so far)
                        self.last_resolutions = {
                            k: {"template": self.template_params[k], "resolved": resolved_params[k]}
                            for k in resolved_params
                        }
                        if upstream_context:
                            raise ValueError(str(e) + upstream_context) from None
                        raise

            # Inject None for optional inputs from non-executed branches
            # (must happen before unresolved check so injected Nones aren't flagged)
            if key == "inputs" and self.optional_input_keys:
                resolved_value = self._inject_none_for_optional_inputs(key, resolved_value, template, context)

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
                error_msg = build_enhanced_template_error(key, template, context)

                if self.template_resolution_mode == "strict":
                    # Strict mode: Fail immediately
                    # Use DEBUG level to avoid duplication in CLI output (error will be shown by CLI)
                    logger.debug(
                        error_msg,
                        extra={"node_id": self.node_id, "param": key, "mode": "strict"},
                    )
                    # Add upstream stderr context if available
                    # Lazy import to keep error path lightweight - only loaded when errors occur
                    from .error_context import get_upstream_stderr

                    upstream_context = get_upstream_stderr(str(template), context)
                    if upstream_context:
                        error_msg += upstream_context
                    # Store resolutions for trace capture before raising
                    # (on error: contains all params resolved so far, including this one's literal ${...})
                    self.last_resolutions = {
                        k: {"template": self.template_params[k], "resolved": resolved_params[k]}
                        for k in resolved_params
                    }
                    # Make template errors fatal so execution stops with a clear error
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

            # After resolving 'inputs', enrich context so subsequent params
            # (e.g., prompt) can reference input-mapped variables
            if key == "inputs" and isinstance(resolved_value, dict):
                context.update(resolved_value)

        # Store resolutions for trace capture (read by InstrumentedNodeWrapper)
        self.last_resolutions = {
            key: {"template": self.template_params[key], "resolved": resolved_params[key]} for key in resolved_params
        }

        merged_params = {**self.static_params, **resolved_params}
        return merged_params

    def _run(self, shared: dict[str, Any]) -> Any:
        """Execute with template resolution.

        This is the key interception point. We resolve templates just
        before execution, using both the shared store (runtime data)
        and initial parameters passed into the workflow.

        Args:
            shared: The shared store containing runtime data

        Returns:
            Result from the inner node's execution
        """
        # Skip resolution if no templates
        if not self.template_params:
            return self.inner_node._run(shared)

        merged_params = self.resolve_templates(shared)

        # Temporarily update inner node params with resolved values
        original_params = self.inner_node.params
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
        wrapper_attrs = {
            "inner_node",
            "node_id",
            "initial_params",
            "template_params",
            "static_params",
            "last_resolutions",
        }

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
