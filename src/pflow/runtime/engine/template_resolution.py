"""Standalone template resolution functions for the execution engine.

Extracted from template_wrapper.py. These functions handle template variable
resolution, type validation, and parameter splitting — all without instance
state. The engine calls these directly instead of delegating to a wrapper.

Key difference from the old wrapper: _build_resolution_context is eliminated.
context = dict(shared) — NO initial_params override. The shared store is the
single source of runtime data.
"""

import logging
from typing import Any, Optional

from pflow.core.json_utils import try_parse_json
from pflow.core.param_coercion import coerce_to_declared_type
from pflow.runtime.template_resolver import TemplateResolver

from .template_errors import (
    build_json_parse_error_message,
    build_template_error_diagnostic,
    build_type_error_message,
)
from .types import TemplateConfig

logger = logging.getLogger(__name__)


def build_type_cache(interface_metadata: Optional[dict[str, Any]]) -> dict[str, str]:
    """Extract param_key -> expected_type from registry interface metadata.

    Args:
        interface_metadata: Node interface metadata from registry

    Returns:
        Dictionary mapping parameter keys to their expected types.
        Empty dict if no interface metadata available.
    """
    if not interface_metadata:
        return {}

    types: dict[str, str] = {}

    # Extract types from inputs
    inputs = interface_metadata.get("inputs", [])
    if isinstance(inputs, list):
        for input_spec in inputs:
            if isinstance(input_spec, dict):
                key = input_spec.get("key")
                type_str = input_spec.get("type")
                if key and type_str:
                    types[key] = type_str

    # Extract types from params
    params = interface_metadata.get("params", [])
    if isinstance(params, list):
        for param_spec in params:
            if isinstance(param_spec, dict):
                key = param_spec.get("key")
                type_str = param_spec.get("type")
                if key and type_str:
                    types[key] = type_str

    return types


def split_params(
    params: dict[str, Any],
    expected_types: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate params into template_params and static_params.

    Static params get type coercion via coerce_to_declared_type.
    _source_line keys are kept in static_params (nodes read them for error
    reporting, e.g. python_code.py uses _code_source_line for line numbers).
    They are filtered out later by compute_node_config() for cache hashing.

    Args:
        params: Node parameters to classify
        expected_types: param_key -> expected type mapping

    Returns:
        (template_params, static_params)
    """
    template_params: dict[str, Any] = {}
    static_params: dict[str, Any] = {}

    for key, value in params.items():
        if TemplateResolver.has_templates(value):
            template_params[key] = value
        else:
            expected_type = expected_types.get(key)
            coerced_value = coerce_to_declared_type(value, expected_type)
            static_params[key] = coerced_value

    return template_params, static_params


def validate_resolved_type(
    param_key: str,
    resolved_value: Any,
    template_str: str,
    expected_types: dict[str, str],
    resolution_mode: str,
) -> Optional[str]:
    """Validate that resolved value type matches expected parameter type.

    Returns error message string on type mismatch, None on success.
    In strict mode, the caller should raise ValueError with the returned message.
    In permissive mode, the caller should store the error and continue.

    The __PERMISSIVE_TYPE_ERROR__ prefix protocol is eliminated.

    Args:
        param_key: Parameter name being validated
        resolved_value: Value after template resolution
        template_str: Original template string (for error message)
        expected_types: param_key -> expected type mapping
        resolution_mode: "strict" or "permissive"

    Returns:
        Error message string if type mismatch detected, None otherwise
    """
    expected_type = expected_types.get(param_key)
    if not expected_type or expected_type == "any":
        return None

    # String parameters receiving dicts/lists
    if expected_type == "str" and isinstance(resolved_value, (dict, list)):
        actual_type = type(resolved_value).__name__
        return build_type_error_message(param_key, resolved_value, template_str, expected_type, actual_type)

    # Correct type matches
    if expected_type in ("dict", "object") and isinstance(resolved_value, dict):
        return None
    if expected_type in ("list", "array") and isinstance(resolved_value, list):
        return None

    # dict/list parameters receiving strings — likely failed JSON parse
    if expected_type in ("dict", "list", "object", "array") and isinstance(resolved_value, str):
        trimmed = resolved_value.strip()
        if trimmed and trimmed[0] in ("{", "["):
            return build_json_parse_error_message(param_key, resolved_value, template_str, expected_type, trimmed)

    return None


def resolve_template_parameter(key: str, template: Any, context: dict[str, Any]) -> tuple[Any, bool]:
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
        return resolved_value, False

    # Handle string templates
    if isinstance(template, str) and "${" in template:
        is_simple = TemplateResolver.is_simple_template(template)
        resolved_value = TemplateResolver.resolve_template(template, context)
        return resolved_value, is_simple

    # No template variables present, preserve original type
    return template, False


def contains_unresolved_template(resolved_value: Any, original_template: Any, _depth: int = 0) -> bool:
    """Check if a resolved value contains unresolved templates.

    Handles strings, lists, dicts. Avoids false positives from resolved MCP
    data containing ${...} by comparing against original template.

    Args:
        resolved_value: The value after template resolution
        original_template: The original template before resolution
        _depth: Current recursion depth

    Returns:
        True if contains unresolved templates, False otherwise
    """
    MAX_DEPTH = 100
    if _depth > MAX_DEPTH:
        return False

    if isinstance(resolved_value, str) and isinstance(original_template, str):
        return _check_string_unresolved(resolved_value, original_template)

    if isinstance(resolved_value, list) and isinstance(original_template, list):
        if len(resolved_value) != len(original_template):
            return False
        return any(contains_unresolved_template(r, t, _depth + 1) for r, t in zip(resolved_value, original_template))

    if isinstance(resolved_value, dict) and isinstance(original_template, dict):
        if set(resolved_value.keys()) != set(original_template.keys()):
            return False
        return any(
            contains_unresolved_template(resolved_value[k], original_template[k], _depth + 1) for k in resolved_value
        )

    return False


def _check_string_unresolved(resolved_value: str, original_template: str) -> bool:
    """Check if a string contains unresolved templates."""
    # Completely unresolved
    if resolved_value == original_template:
        return "${" in resolved_value

    # Partially resolved — check if original variables remain
    if "${" in resolved_value:
        original_vars = TemplateResolver.extract_variables(original_template)
        remaining_vars = TemplateResolver.extract_variables(resolved_value)
        if original_vars & remaining_vars:
            return True

    return False


def all_variables_from_absent_nodes(template_str: str, context: dict[str, Any]) -> bool:
    """Check if ALL template variables reference nodes that are absent or failed.

    Uses all() not any() — critical for coalesce correctness. After the
    failed-node invariant fix, "absent from context" naturally covers
    both "did not execute" and "executed and failed" because failed
    nodes are moved out of the main namespace.
    """
    from pflow.runtime.template_resolver import TemplateResolver

    variables = TemplateResolver.extract_variables(template_str)
    if not variables:
        return False
    return all(TemplateResolver.extract_root_node_id(var) not in context for var in variables)


def inject_none_for_optional_inputs(
    key: str,
    resolved_value: Any,
    template: Any,
    context: dict[str, Any],
    optional_input_keys: set[str],
) -> Any:
    """Replace unresolved optional input templates with None.

    For code nodes with optional input annotations, when the source node
    didn't execute, inject None instead of leaving unresolved ${...}.
    """
    if key != "inputs" or not optional_input_keys:
        return resolved_value

    if not isinstance(resolved_value, dict) or not isinstance(template, dict):
        return resolved_value

    modified = dict(resolved_value)
    for input_key in optional_input_keys:
        if input_key not in modified or input_key not in template:
            continue

        input_value = modified[input_key]
        input_template = template[input_key]

        if not isinstance(input_value, str) or "${" not in input_value:
            continue
        if not isinstance(input_template, str) or input_value != input_template:
            continue

        if all_variables_from_absent_nodes(input_template, context):
            modified[input_key] = None

    return modified


def resolve_templates(  # noqa: C901
    template_config: TemplateConfig,
    shared: dict[str, Any],
    node_id: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Resolve all template params against shared store.

    Returns (merged_params, last_resolutions, template_errors).
    - merged_params: static + resolved template params (ready to set on node)
    - last_resolutions: {key: {template, resolved}} for trace capture
    - template_errors: list of error dicts for permissive mode (empty in strict — raises instead)

    ORDERING CONTRACT: The 'inputs' key is ALWAYS processed first.

    CONTEXT BUILDING: context = dict(shared) — NO initial_params override.

    Raises ValueError in strict mode on unresolved templates or type mismatches.

    ON ERROR IN STRICT MODE: last_resolutions contains all params resolved so far.
    """
    if not template_config.template_params:
        return dict(template_config.static_params), {}, []

    # Build resolution context: shared store only — no initial_params override
    context = dict(shared)

    # Enrich context with static inputs so other params can reference them
    static_inputs = template_config.static_params.get("inputs")
    if isinstance(static_inputs, dict):
        context.update(static_inputs)

    # Process 'inputs' before other params
    param_keys = list(template_config.template_params.keys())
    if "inputs" in param_keys:
        param_keys.remove("inputs")
        param_keys.insert(0, "inputs")

    resolved_params: dict[str, Any] = {}
    last_resolutions: dict[str, Any] = {}
    template_errors: list[dict[str, Any]] = []

    for key in param_keys:
        template = template_config.template_params[key]
        resolved_value, is_simple_template = resolve_template_parameter(key, template, context)

        # Auto-parse JSON strings for structured parameters (only simple templates)
        if is_simple_template and isinstance(resolved_value, str):
            expected_type = template_config.expected_types.get(key)
            if expected_type in ("dict", "list", "object", "array"):
                success, parsed = try_parse_json(resolved_value)
                type_matches = (expected_type in ("dict", "object") and isinstance(parsed, dict)) or (
                    expected_type in ("list", "array") and isinstance(parsed, list)
                )
                if success and type_matches:
                    resolved_value = parsed

        # Reverse: serialize dict/list -> str when expected type is str
        if isinstance(resolved_value, (dict, list)):
            expected_type = template_config.expected_types.get(key)
            resolved_value = coerce_to_declared_type(resolved_value, expected_type)

        # Type validation for simple templates
        if is_simple_template:
            type_error = validate_resolved_type(
                key,
                resolved_value,
                str(template),
                template_config.expected_types,
                template_config.resolution_mode,
            )
            if type_error:
                if template_config.resolution_mode == "strict":
                    # Store partial resolutions on exception for trace capture
                    partial = {
                        k: {"template": template_config.template_params[k], "resolved": resolved_params[k]}
                        for k in resolved_params
                    }
                    # Enrich with upstream stderr context
                    from .error_context import get_upstream_stderr

                    upstream_context = get_upstream_stderr(str(template), context)
                    if upstream_context:
                        type_error += upstream_context
                    exc = ValueError(type_error)
                    exc._partial_resolutions = partial  # type: ignore[attr-defined]
                    raise exc
                else:
                    template_errors.append({
                        "message": type_error,
                        "type": "type_validation",
                        "param": key,
                    })

        # Inject None for optional inputs from non-executed branches
        if key == "inputs" and template_config.optional_input_keys:
            resolved_value = inject_none_for_optional_inputs(
                key, resolved_value, template, context, template_config.optional_input_keys
            )

        resolved_params[key] = resolved_value

        # Check if template was fully resolved
        is_unresolved = contains_unresolved_template(resolved_value, template)

        if is_unresolved:
            diagnostic = build_template_error_diagnostic(
                key,
                template,
                context,
                node_id=node_id,
                source_file=_extract_source_file(shared),
                source_line=_extract_source_line(template_config, key),
            )

            if template_config.resolution_mode == "strict":
                from pflow.core.diagnostic import format_diagnostic

                # Store partial resolutions on exception for trace capture
                partial = {
                    k: {"template": template_config.template_params[k], "resolved": resolved_params[k]}
                    for k in resolved_params
                }
                exc = ValueError(format_diagnostic(diagnostic))
                exc._partial_resolutions = partial  # type: ignore[attr-defined]
                exc._pflow_template_diagnostic = diagnostic  # type: ignore[attr-defined]
                raise exc
            else:
                template_errors.append({
                    "message": diagnostic.message,
                    "unresolved": [key],
                    "template": template,
                    "diagnostic": diagnostic,
                })

        # After resolving 'inputs', enrich context for subsequent params
        if key == "inputs" and isinstance(resolved_value, dict):
            context.update(resolved_value)

    # Build final resolutions for trace capture
    last_resolutions = {
        key: {"template": template_config.template_params[key], "resolved": resolved_params[key]}
        for key in resolved_params
    }

    merged_params = {**template_config.static_params, **resolved_params}
    return merged_params, last_resolutions, template_errors


def _extract_source_file(shared: dict[str, Any]) -> Optional[str]:
    """Extract the workflow source file path for error messages."""
    return shared.get("_pflow_workflow_file")


def _extract_source_line(template_config: TemplateConfig, key: str) -> Optional[int]:
    """Extract the source line for a template parameter, if tracked.

    The compiler stores _<key>_source_line in static_params for parameters
    written via code blocks. For inline params, this is None.
    """
    line_key = f"_{key}_source_line"
    line = template_config.static_params.get(line_key)
    return int(line) if isinstance(line, int) else None
