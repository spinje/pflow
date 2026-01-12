"""Template variable validation for workflow execution.

This module provides validation functionality to ensure all required
template variables have corresponding parameters available before
workflow execution begins.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, ClassVar, Optional

from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver
from pflow.runtime.type_checker import (
    get_parameter_type,
    infer_template_type,
    is_type_compatible,
)


@dataclass
class ValidationWarning:
    """Warning about runtime-validated template access.

    Emitted when static validation cannot verify a template path
    (e.g., accessing nested fields on outputs with type 'Any').
    These templates will be validated at runtime during execution.
    """

    template: str  # Full template with ${}
    node_id: str  # Node producing the output
    node_type: str  # Node type (often MCP)
    output_key: str  # Output key being accessed
    output_type: str  # Type causing runtime validation
    reason: str  # Human-readable explanation
    nested_path: str  # Nested portion: "data.field[0]"


logger = logging.getLogger(__name__)

# Display limits for error messages - balances information vs overwhelming output
MAX_DISPLAYED_FIELDS = 20  # Fits in ~25 terminal lines with formatting
MAX_DISPLAYED_SUGGESTIONS = 3  # Cognitive limit for processing alternatives
MAX_FLATTEN_DEPTH = 5  # Prevent infinite recursion on circular refs

# Pattern to detect templates exactly wrapped in single quotes: '${var}'
# This is an escape hatch for structured types in shell commands.
# Does NOT match: '${a} ${b}', 'prefix ${var}', '$${var}' (escaped)
_QUOTED_TEMPLATE_PATTERN = re.compile(r"'\$\{([^}]+)\}'")

# Types that are safe in shell commands (string-like or unknown type)
# When a union contains one of these, runtime coercion to string is acceptable.
_SHELL_SAFE_TYPES = {"str", "string", "any"}


def _extract_base_type(type_str: str) -> str:
    """Extract base type from generic type string.

    Generic types like list[dict] or dict[str, any] have a base type
    (list, dict) that determines their shell command compatibility.

    Examples:
        list[dict] -> list
        dict[str, any] -> dict
        str -> str
        list -> list

    Args:
        type_str: Type string, possibly with generic parameters

    Returns:
        Base type without generic parameters
    """
    return type_str.split("[")[0]


def _is_shell_safe_type(inferred_type: str, blocked_types: set[str]) -> tuple[bool, str | None]:
    """Check if a type is safe for shell command embedding.

    Args:
        inferred_type: The inferred type string (may be union like "dict|str")
        blocked_types: Set of blocked type names

    Returns:
        Tuple of (is_safe, blocked_type_if_not_safe)
        - (True, None) if type is safe
        - (False, "dict") if blocked, with the first blocked type
    """
    # Split union and get base type for each component
    type_parts = [t.strip() for t in inferred_type.split("|")]
    base_types = [_extract_base_type(t) for t in type_parts]

    # Tier 1: If union contains a safe base type (str, string, any), allow it
    if any(t in _SHELL_SAFE_TYPES for t in base_types):
        return (True, None)

    # Check if any base type is blocked
    blocked_parts = [t for t in base_types if t in blocked_types]
    if blocked_parts:
        return (False, blocked_parts[0])

    return (True, None)


class TemplateValidator:
    """Validates template variables before workflow execution."""

    @staticmethod
    def _get_input_description(variable: str, workflow_ir: dict[str, Any]) -> str:
        """Get description for an input variable if available.

        Args:
            variable: The variable name to look up
            workflow_ir: The workflow IR containing input declarations

        Returns:
            A descriptive string with input info, or empty string if not a declared input
        """
        inputs = workflow_ir.get("inputs", {})
        if variable in inputs:
            input_def = inputs[variable]
            desc = input_def.get("description", "")
            required = input_def.get("required", True)
            default = input_def.get("default")

            parts = []
            if desc:
                parts.append(desc)
            if not required and default is not None:
                parts.append(f"(optional, default: {default})")
            elif required:
                parts.append("(required)")

            return " - " + " ".join(parts) if parts else ""
        return ""

    @staticmethod
    def _get_node_ids(workflow_ir: dict[str, Any]) -> set[str]:
        """Extract all node IDs from the workflow.

        Args:
            workflow_ir: The workflow IR

        Returns:
            Set of all node IDs in the workflow
        """
        return {node.get("id") for node in workflow_ir.get("nodes", []) if node.get("id")}

    @staticmethod
    def validate_workflow_templates(
        workflow_ir: dict[str, Any], available_params: dict[str, Any], registry: Registry
    ) -> tuple[list[str], list[ValidationWarning]]:
        """
        Validates all template variables in a workflow.

        Uses the registry to determine which variables are written by nodes
        and validates that all template paths exist in the node outputs.
        Also validates that all declared inputs are actually used.

        Args:
            workflow_ir: The workflow IR containing nodes with template parameters
            available_params: Parameters available from planner or CLI
            registry: Registry instance with parsed node metadata

        Returns:
            Tuple of (errors, warnings):
            - errors: List of validation errors that prevent execution
            - warnings: List of ValidationWarning objects for runtime-validated templates
        """
        errors: list[str] = []
        warnings: list[ValidationWarning] = []

        # Check for malformed template syntax FIRST
        malformed_errors = TemplateValidator._validate_malformed_templates(workflow_ir)
        errors.extend(malformed_errors)

        # If malformed syntax found, return early with those errors
        if malformed_errors:
            logger.error(f"Found {len(malformed_errors)} malformed template(s)", extra={"errors": malformed_errors})
            return (errors, warnings)

        # Extract all templates from workflow
        all_templates = TemplateValidator._extract_all_templates(workflow_ir)

        if all_templates:
            logger.debug(
                f"Found {len(all_templates)} template variables to validate", extra={"templates": sorted(all_templates)}
            )
        else:
            logger.debug("No template variables found in workflow")

        # Check for unused inputs
        unused_input_errors = TemplateValidator._validate_unused_inputs(workflow_ir, all_templates)
        errors.extend(unused_input_errors)

        # If no templates, we can return early (after checking for unused inputs)
        if not all_templates:
            return (errors, warnings)

        # Get full output structure from nodes
        node_outputs = TemplateValidator._extract_node_outputs(workflow_ir, registry)

        logger.debug(
            f"Extracted outputs from {len(node_outputs)} node variables", extra={"outputs": sorted(node_outputs.keys())}
        )

        # Validate each template path
        for template in sorted(all_templates):
            is_valid, warning = TemplateValidator._validate_template_path(
                template, available_params, node_outputs, workflow_ir, registry
            )

            # Collect warning if present
            if warning:
                warnings.append(warning)

            # Collect error if invalid
            if not is_valid:
                error = TemplateValidator._create_template_error(
                    template, available_params, workflow_ir, node_outputs, registry
                )
                errors.append(error)

        # NEW: Validate template types match parameter expectations
        type_errors = TemplateValidator._validate_template_types(workflow_ir, node_outputs, registry)
        errors.extend(type_errors)

        # Block structured data (dict/list) in shell command parameters
        shell_errors = TemplateValidator._validate_shell_command_types(workflow_ir, node_outputs)
        errors.extend(shell_errors)

        if errors:
            logger.warning(
                f"Template validation found {len(errors)} errors", extra={"error_count": len(errors), "errors": errors}
            )
        elif warnings:
            logger.info(
                f"Template validation passed with {len(warnings)} runtime-validated template(s)",
                extra={"warning_count": len(warnings)},
            )
        else:
            logger.info("Template validation passed")

        return (errors, warnings)

    @staticmethod
    def _validate_unused_inputs(workflow_ir: dict[str, Any], all_templates: set[str]) -> list[str]:
        """Validate that all declared inputs are actually used.

        Args:
            workflow_ir: The workflow IR
            all_templates: Set of all template variables found

        Returns:
            List of error messages for unused inputs
        """
        errors: list[str] = []
        declared_inputs = set(workflow_ir.get("inputs", {}).keys())

        if declared_inputs:
            enable_namespacing = workflow_ir.get("enable_namespacing", True)
            node_ids = TemplateValidator._get_node_ids(workflow_ir) if enable_namespacing else set()

            # Extract base variable names from templates (before any dots)
            # But exclude node IDs when namespacing is enabled
            used_inputs = set()
            for var in all_templates:
                base_var = var.split(".")[0]
                # Only count as used input if it's actually a declared input
                # and not a node ID (when namespacing is enabled)
                if base_var in declared_inputs and (not enable_namespacing or base_var not in node_ids):
                    used_inputs.add(base_var)

            unused_inputs = declared_inputs - used_inputs
            if unused_inputs:
                errors.append(f"Declared input(s) never used as template variable: {', '.join(sorted(unused_inputs))}")
                logger.warning(f"Found {len(unused_inputs)} unused inputs", extra={"unused": sorted(unused_inputs)})

        return errors

    @staticmethod
    def _sanitize_for_display(value: str, max_length: int = 100) -> str:
        """Sanitize string for safe display in error messages.

        Removes control characters and limits length to prevent:
        - Terminal escape sequences
        - Log injection (newlines, carriage returns)
        - Information disclosure

        Args:
            value: String to sanitize (node_id, template variable, etc.)
            max_length: Maximum length before truncation

        Returns:
            Sanitized string safe for error messages
        """
        # Remove non-printable characters AND newlines/carriage returns
        # Allow only printable characters, excluding control chars that enable log injection
        sanitized = "".join(c for c in value if c.isprintable() and c not in ("\n", "\r", "\t", "\x0b", "\x0c"))

        # Truncate if too long
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + "..."

        return sanitized

    @staticmethod
    def _flatten_output_structure(  # noqa: C901
        base_key: str,
        base_type: str,
        structure: dict[str, Any],
        _current_path: str = "",
        _paths: list[tuple[str, str]] | None = None,
        _depth: int = 0,
        _max_depth: int = MAX_FLATTEN_DEPTH,
    ) -> list[tuple[str, str]]:
        """Recursively flatten output structure to list of (path, type) tuples.

        Note: This function has inherent complexity (noqa: C901) due to recursive
        tree traversal of arbitrary nested structures. Refactoring would require
        breaking the recursion pattern, which could reduce readability without
        meaningful benefit. The complexity is managed through:
        - Clear function boundaries (prep/traverse/handle)
        - Depth limiting to prevent infinite recursion
        - Comprehensive docstrings
        - Type hints for all parameters

        Args:
            base_key: The base output key (e.g., "result")
            base_type: Type of the base key (e.g., "dict")
            structure: Nested structure dictionary
            _current_path: Current path during recursion (internal)
            _paths: Accumulated paths (internal)
            _depth: Current recursion depth (internal)
            _max_depth: Maximum recursion depth to prevent infinite loops

        Returns:
            List of (path, type) tuples representing all accessible paths

        Example:
            Input: base_key="result", base_type="dict", structure={
                "messages": {"type": "array", "items": {"type": "dict", "structure": {...}}}
            }
            Output: [
                ("result", "dict"),
                ("result.messages", "array"),
                ("result.messages[0].text", "string"),
                ...
            ]
        """
        if _paths is None:
            _paths = []

        # Prevent infinite recursion on malformed structures
        if _depth > _max_depth:
            return _paths

        # Add the base path first
        if _current_path == "":
            _paths.append((base_key, base_type))
            _current_path = base_key

        # Recursively traverse structure
        if structure and isinstance(structure, dict):
            for field_name, field_info in structure.items():
                field_path = f"{_current_path}.{field_name}"

                if isinstance(field_info, dict):
                    field_type = field_info.get("type", "any")
                    _paths.append((field_path, field_type))

                    # Handle arrays with example index
                    if field_type == "array" and "items" in field_info:
                        items = field_info["items"]
                        if isinstance(items, dict):
                            item_type = items.get("type", "any")
                            item_path = f"{field_path}[0]"
                            _paths.append((item_path, item_type))

                            # Recurse into array item structure
                            if "structure" in items and isinstance(items["structure"], dict):
                                TemplateValidator._flatten_output_structure(
                                    base_key="",  # Not used in recursion
                                    base_type="",
                                    structure=items["structure"],
                                    _current_path=item_path,
                                    _paths=_paths,
                                    _depth=_depth + 1,
                                    _max_depth=_max_depth,
                                )

                    # Recurse into nested dict structure
                    elif "structure" in field_info and isinstance(field_info["structure"], dict):
                        TemplateValidator._flatten_output_structure(
                            base_key="",
                            base_type="",
                            structure=field_info["structure"],
                            _current_path=field_path,
                            _paths=_paths,
                            _depth=_depth + 1,
                            _max_depth=_max_depth,
                        )
                elif isinstance(field_info, str):
                    # Direct type string (legacy format)
                    _paths.append((field_path, field_info))

        return _paths

    @staticmethod
    def _find_similar_paths(attempted_key: str, available_paths: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Find paths similar to the attempted key.

        Uses simple substring matching for MVP.

        Args:
            attempted_key: The key user tried to access (e.g., "msg")
            available_paths: List of (path, type) tuples

        Returns:
            List of (path, type) tuples that match, sorted by relevance

        Example:
            attempted_key="msg"
            available_paths=[("result", "dict"), ("result.messages", "array")]
            returns=[("result.messages", "array")]
        """
        attempted_lower = attempted_key.lower()
        matches = []

        for path, path_type in available_paths:
            # Extract just the last component of the path for matching
            last_component = path.split(".")[-1].split("[")[0]  # Handle array notation

            # Substring match (case-insensitive)
            if attempted_lower in last_component.lower():
                # Calculate match quality (longer substring match = better)
                match_quality = len(attempted_lower) / len(last_component) if last_component else 0
                matches.append((path, path_type, match_quality))

        # Sort by match quality (best matches first), then alphabetically
        matches.sort(key=lambda x: (-x[2], x[0]))

        # Return just the (path, type) tuples, top 3 matches
        return [(path, path_type) for path, path_type, _ in matches[:MAX_DISPLAYED_SUGGESTIONS]]

    @staticmethod
    def _format_enhanced_node_error(
        node_id: str, node_type: str, attempted_key: str, available_paths: list[tuple[str, str]], base_var: str
    ) -> str:
        """Create multi-section error with available outputs and suggestions.

        Args:
            node_id: Node ID where error occurred
            node_type: Type of the node
            attempted_key: The output key that was attempted
            available_paths: List of (path, type) tuples
            base_var: Base variable (node ID) for template construction

        Returns:
            Multi-line error message with sections for problem, available outputs, and suggestions
        """
        # Sanitize all user-controlled values to prevent template injection
        safe_node_id = TemplateValidator._sanitize_for_display(node_id)
        safe_node_type = TemplateValidator._sanitize_for_display(node_type)
        safe_attempted_key = TemplateValidator._sanitize_for_display(attempted_key)
        safe_base_var = TemplateValidator._sanitize_for_display(base_var)

        # Section 1: Problem statement
        lines = [f"Node '{safe_node_id}' (type: {safe_node_type}) does not output '{safe_attempted_key}'"]

        # Section 2: Available outputs (limit to 20 to avoid overwhelming)
        if available_paths:
            lines.append("")
            lines.append(f"Available outputs from '{safe_node_id}':")

            display_paths = available_paths[:MAX_DISPLAYED_FIELDS]  # Limit display
            for path, type_str in display_paths:
                # Sanitize path components for safety
                safe_path = TemplateValidator._sanitize_for_display(path)
                safe_type = TemplateValidator._sanitize_for_display(type_str)

                # Format with checkmark and type
                full_path = f"{safe_base_var}.{safe_path}" if safe_base_var not in safe_path else safe_path
                lines.append(f"  ✓ ${{{full_path}}} ({safe_type})")

            # Show truncation message if needed
            if len(available_paths) > 20:
                remaining = len(available_paths) - 20
                lines.append(f"  ... and {remaining} more outputs")

        # Section 3: Suggestions (find similar paths)
        suggestions = TemplateValidator._find_similar_paths(attempted_key, available_paths)
        if suggestions:
            lines.append("")
            if len(suggestions) == 1:
                sugg_path, _ = suggestions[0]
                safe_sugg_path = TemplateValidator._sanitize_for_display(sugg_path)
                full_sugg = (
                    f"{safe_base_var}.{safe_sugg_path}" if safe_base_var not in safe_sugg_path else safe_sugg_path
                )
                lines.append(f"Did you mean: ${{{full_sugg}}}?")
            else:
                lines.append("Did you mean one of these?")
                for sugg_path, _ in suggestions:
                    safe_sugg_path = TemplateValidator._sanitize_for_display(sugg_path)
                    full_sugg = (
                        f"{safe_base_var}.{safe_sugg_path}" if safe_base_var not in safe_sugg_path else safe_sugg_path
                    )
                    lines.append(f"  - ${{{full_sugg}}}")

        # Section 4: Common fix (use first suggestion if available, otherwise first available path)
        if suggestions:
            fix_path, _ = suggestions[0]
            full_fix = f"{base_var}.{fix_path}" if base_var not in fix_path else fix_path
            lines.append("")
            lines.append(f"Common fix: Change ${{{base_var}.{attempted_key}}} to ${{{full_fix}}}")
        elif available_paths:
            # No suggestions, but we have paths - suggest the first one as generic fix
            first_path, _ = available_paths[0]
            full_first = f"{base_var}.{first_path}" if base_var not in first_path else first_path
            lines.append("")
            lines.append(f"Tip: Try using ${{{full_first}}} instead")

        return "\n".join(lines)

    @staticmethod
    def _get_node_outputs_description(node: dict[str, Any], output_key: str, registry: Registry) -> str:
        """Get error message for missing node output with enhanced suggestions.

        Args:
            node: Node dictionary from workflow IR
            output_key: The output key being accessed
            registry: Registry instance for metadata lookup

        Returns:
            Error message describing what outputs are available with suggestions
        """
        node_type = node.get("type", "unknown")
        base_var = node.get("id")

        try:
            nodes_metadata = registry.get_nodes_metadata([node_type])
            if node_type in nodes_metadata:
                interface = nodes_metadata[node_type]["interface"]

                # Extract all outputs with nested paths
                all_paths = []
                for output in interface["outputs"]:
                    if isinstance(output, str):
                        # Simple output without structure
                        all_paths.append((output, "any"))
                    else:
                        # Rich output with potential structure
                        key = output["key"]
                        output_type = output.get("type", "any")
                        structure = output.get("structure", {})

                        # Add the base output key
                        all_paths.append((key, output_type))

                        # Flatten nested structure if it exists
                        if structure and isinstance(structure, dict):
                            nested_paths = TemplateValidator._flatten_output_structure(
                                base_key=key, base_type=output_type, structure=structure
                            )
                            # Skip the first entry (base key already added)
                            all_paths.extend(nested_paths[1:])

                if all_paths:
                    # Type-safe: base_var comes from node.get("id") which may be None
                    node_id_str = str(base_var) if base_var else "unknown"
                    return TemplateValidator._format_enhanced_node_error(
                        node_id=node_id_str,
                        node_type=node_type,
                        attempted_key=output_key,
                        available_paths=all_paths,
                        base_var=node_id_str,
                    )
                else:
                    return f"Node '{base_var}' (type: {node_type}) does not produce any outputs"
        except Exception as e:
            # Registry lookup failed, skip detailed error message
            logger.debug(f"Failed to get enhanced node metadata for validation: {e}")

        # Fallback if registry lookup failed
        return f"Node '{base_var}' does not output '{output_key}'"

    @staticmethod
    def _create_node_reference_error(
        base_var: str, parts: list[str], template: str, workflow_ir: dict[str, Any], registry: Registry
    ) -> str:
        """Create error for node output references.

        Args:
            base_var: The base variable (node ID)
            parts: Template parts split by dot
            template: Full template string
            workflow_ir: Workflow IR
            registry: Registry instance

        Returns:
            Error message for node reference issues
        """
        # Missing output key
        if len(parts) == 1:
            return f"Invalid template ${{{template}}} - node ID '{base_var}' requires an output key (e.g., ${{{base_var}}}.output_key)"

        output_key = parts[1]

        # Find the node to get better error message
        node = next((n for n in workflow_ir.get("nodes", []) if n.get("id") == base_var), None)
        if node:
            return TemplateValidator._get_node_outputs_description(node, output_key, registry)

        return f"Node '{base_var}' does not output '{output_key}'"

    @staticmethod
    def _create_path_template_error(
        template: str, base_var: str, available_params: dict[str, Any], workflow_ir: dict[str, Any]
    ) -> str:
        """Create error for path templates (with dots) that aren't node references.

        Args:
            template: Full template string
            base_var: Base variable name
            available_params: Available parameters
            workflow_ir: Workflow IR

        Returns:
            Error message for path template issues
        """
        if base_var in available_params:
            return f"Template path ${{{template}}} cannot be validated - initial_params values are runtime-dependent"

        # Check if base variable is a declared input
        input_desc = TemplateValidator._get_input_description(base_var, workflow_ir)
        path_component = template[len(base_var) + 1 :]

        if input_desc:
            return f"Required input '${{{base_var}}}' not provided{input_desc} - attempted to access path '{path_component}'"

        enable_namespacing = workflow_ir.get("enable_namespacing", True)
        if enable_namespacing:
            return (
                f"Template variable ${{{template}}} has no valid source - "
                f"'${{{base_var}}}' is neither a workflow input nor a node ID in this workflow"
            )
        else:
            return (
                f"Template variable ${{{template}}} has no valid source - "
                f"not provided in initial_params and path '{path_component}' "
                f"not found in outputs from any node in the workflow"
            )

    @staticmethod
    def _create_simple_template_error(template: str, workflow_ir: dict[str, Any]) -> str:
        """Create error for simple templates without dots.

        Args:
            template: Template variable name
            workflow_ir: Workflow IR

        Returns:
            Error message for simple template issues
        """
        input_desc = TemplateValidator._get_input_description(template, workflow_ir)

        if input_desc:
            return f"Required input '${{{template}}}' not provided{input_desc}"

        # Check if it might be a node ID used incorrectly
        enable_namespacing = workflow_ir.get("enable_namespacing", True)
        if enable_namespacing:
            node_ids = TemplateValidator._get_node_ids(workflow_ir)
            if template in node_ids:
                return (
                    f"Invalid template ${{{template}}} - this is a node ID. "
                    f"To reference node outputs, use ${{{template}}}.output_key format"
                )

        return (
            f"Template variable ${{{template}}} has no valid source - "
            f"not provided in initial_params and not written by any node"
        )

    @staticmethod
    def _create_template_error(
        template: str,
        available_params: dict[str, Any],
        workflow_ir: dict[str, Any],
        node_outputs: dict[str, Any],
        registry: Registry,
    ) -> str:
        """Create appropriate error message for missing template variable.

        Args:
            template: Template variable name
            available_params: Available parameters
            workflow_ir: The workflow IR
            node_outputs: Full structure info from node interfaces
            registry: Registry instance

        Returns:
            Error message string
        """
        parts = template.split(".")
        base_var = parts[0]
        enable_namespacing = workflow_ir.get("enable_namespacing", True)

        # Check if this is a node ID reference when namespacing is enabled
        if enable_namespacing and "." in template:
            node_ids = TemplateValidator._get_node_ids(workflow_ir)
            if base_var in node_ids:
                return TemplateValidator._create_node_reference_error(base_var, parts, template, workflow_ir, registry)

        # Handle path templates (with dots)
        if "." in template:
            return TemplateValidator._create_path_template_error(template, base_var, available_params, workflow_ir)

        # Handle simple templates
        return TemplateValidator._create_simple_template_error(template, workflow_ir)

    # More permissive pattern to catch malformed templates for validation
    # Now supports array notation: ${node[0].field}, ${node.field[0].subfield}
    _PERMISSIVE_PATTERN = re.compile(r"\$\{([a-zA-Z_][\w-]*(?:(?:\[[\d]+\])?(?:\.[\w-]*(?:\[[\d]+\])?)*)?)\}")

    # Batch output definitions matching PflowBatchNode.post() structure
    _BATCH_OUTPUTS: ClassVar[list[dict[str, str]]] = [
        {"key": "results", "type": "array", "description": "Array of results in input order"},
        {"key": "count", "type": "number", "description": "Total items processed"},
        {"key": "success_count", "type": "number", "description": "Items that succeeded"},
        {"key": "error_count", "type": "number", "description": "Items that failed"},
        {"key": "errors", "type": "array", "description": "Error details (null if none)"},
        {"key": "batch_metadata", "type": "dict", "description": "Execution statistics"},
    ]

    @staticmethod
    def _extract_node_outputs(workflow_ir: dict[str, Any], registry: Registry) -> dict[str, Any]:
        """Extract full output structures from nodes using interface metadata.

        When namespacing is enabled, outputs are registered under both:
        - The original key (for backward compatibility checks)
        - The namespaced path "node_id.output_key"

        For batch nodes, registers batch-specific outputs (results, count, etc.)
        instead of the inner node's normal outputs, and adds the item alias
        as an available variable.

        Returns:
            Dict mapping variable names to their full structure/type info
        """
        node_outputs: dict[str, dict[str, Any]] = {}
        enable_namespacing = workflow_ir.get("enable_namespacing", True)

        for node in workflow_ir.get("nodes", []):
            node_id = node.get("id")
            node_type = node.get("type")
            if not node_type or not node_id:
                continue

            # Check for batch configuration
            batch_config = node.get("batch")

            if batch_config:
                # Batch node: register batch outputs instead of normal outputs
                TemplateValidator._register_batch_outputs(
                    node_outputs, node_id, node_type, enable_namespacing, registry
                )

                # Register the item alias as an available variable
                item_alias = batch_config.get("as", "item")
                node_outputs[item_alias] = {
                    "type": "any",
                    "description": f"Current batch item during iteration (from node '{node_id}')",
                    "node_id": node_id,
                    "node_type": node_type,
                    "is_batch_item": True,
                }
            else:
                # Non-batch node: extract outputs from registry interface
                TemplateValidator._register_node_outputs_from_registry(
                    node_outputs, node_id, node_type, enable_namespacing, registry
                )

        return node_outputs

    @staticmethod
    def _register_batch_outputs(
        node_outputs: dict[str, Any],
        node_id: str,
        node_type: str,
        enable_namespacing: bool,
        registry: Registry,
    ) -> None:
        """Register batch-specific outputs for a node with batch configuration.

        Batch nodes wrap their inner node's outputs in a structured result with:
        - results: Array of per-item results (with inner node's output structure)
        - count: Total items processed
        - success_count/error_count: Success/failure counts
        - errors: Error details if any
        - batch_metadata: Execution statistics
        """
        # Try to get inner node's output structure for results array
        inner_outputs_structure: dict[str, Any] = {}
        try:
            nodes_metadata = registry.get_nodes_metadata([node_type])
            if node_type in nodes_metadata:
                interface = nodes_metadata[node_type]["interface"]
                # Build structure from inner node's outputs
                for output in interface.get("outputs", []):
                    if isinstance(output, str):
                        inner_outputs_structure[output] = {"type": "any"}
                    else:
                        key = output.get("key", "")
                        if key:
                            inner_outputs_structure[key] = {
                                "type": output.get("type", "any"),
                                "description": output.get("description", ""),
                                "structure": output.get("structure", {}),
                            }
        except (ValueError, KeyError):
            # Graceful fallback if node type not found (e.g., during testing)
            pass

        for output in TemplateValidator._BATCH_OUTPUTS:
            key = output["key"]
            output_info: dict[str, Any] = {
                "type": output["type"],
                "description": output["description"],
                "node_id": node_id,
                "node_type": node_type,
                "is_batch_output": True,
            }

            # For 'results' array, add inner node's output structure plus 'item'
            if key == "results":
                # Each result always contains 'item' (original batch input)
                result_structure = {"item": {"type": "any", "description": "Original batch input"}}
                if inner_outputs_structure:
                    result_structure.update(inner_outputs_structure)
                output_info["items"] = {
                    "type": "dict",
                    "structure": result_structure,
                }

            # Register under original key for backward compatibility
            node_outputs[key] = output_info

            # If namespacing is enabled, also register under node_id.output
            if enable_namespacing:
                namespaced_key = f"{node_id}.{key}"
                node_outputs[namespaced_key] = output_info

    @staticmethod
    def _register_node_outputs_from_registry(
        node_outputs: dict[str, Any],
        node_id: str,
        node_type: str,
        enable_namespacing: bool,
        registry: Registry,
    ) -> None:
        """Register outputs from registry interface metadata for non-batch nodes."""
        # Get node metadata from registry
        nodes_metadata = registry.get_nodes_metadata([node_type])
        if node_type not in nodes_metadata:
            raise ValueError(f"Unknown node type: {node_type}")

        interface = nodes_metadata[node_type]["interface"]

        # Extract outputs with full structure
        for output in interface["outputs"]:
            if isinstance(output, str):
                # Simple format: just the key, no structure
                output_info = {"type": "any", "node_id": node_id, "node_type": node_type}

                # Register under original key for backward compatibility
                node_outputs[output] = output_info

                # If namespacing is enabled, also register under node_id.output
                if enable_namespacing:
                    namespaced_key = f"{node_id}.{output}"
                    node_outputs[namespaced_key] = output_info
            else:
                # Rich format: includes type and structure
                key = output["key"]
                output_info = {
                    "type": output.get("type", "any"),
                    "structure": output.get("structure", {}),
                    "node_id": node_id,
                    "node_type": node_type,
                }

                # Register under original key for backward compatibility
                node_outputs[key] = output_info

                # If namespacing is enabled, also register under node_id.output
                if enable_namespacing:
                    namespaced_key = f"{node_id}.{key}"
                    node_outputs[namespaced_key] = output_info

    @staticmethod
    def _validate_namespaced_output(
        parts: list[str],
        base_var: str,
        node_outputs: dict[str, Any],
        template: str,
    ) -> tuple[bool, Optional[ValidationWarning]]:
        """Validate a namespaced node output reference with array index support.

        Handles patterns like:
        - node_id.output_key
        - node_id.results[0]
        - node_id.results[0].field
        """
        if len(parts) == 1:
            # Just the node ID without output key - invalid
            return (False, None)

        # Handle array indexing: parts[1] might be "results[0]" → base="results", index=0
        output_part = parts[1]
        array_index = None
        if "[" in output_part and output_part.endswith("]"):
            bracket_pos = output_part.index("[")
            base_output = output_part[:bracket_pos]
            array_index = output_part[bracket_pos + 1 : -1]
        else:
            base_output = output_part

        node_output_key = f"{base_var}.{base_output}"
        if node_output_key not in node_outputs:
            return (False, None)

        output_info = node_outputs[node_output_key]

        # If array access, check if output has items structure
        if array_index is not None:
            items_info = output_info.get("items", {})
            if items_info:
                # Use items structure for nested validation
                if len(parts) == 2:
                    return (True, None)
                return TemplateValidator._validate_nested_path(
                    parts[2:], items_info, full_template=template, output_key=base_output
                )
            # No items info but array access requested
            output_type = output_info.get("type", "any")
            # Allow if type is array (native array access)
            if output_type == "array":
                return (True, None)
            # Also allow str types - they may contain JSON that gets auto-parsed at runtime
            # This matches the behavior of _check_type_allows_traversal for field access
            if output_type in ["str", "string"]:
                # Generate warning about JSON auto-parsing requirement
                nested_path = f"[{array_index}]" + (".".join(parts[2:]) if len(parts) > 2 else "")
                warning = ValidationWarning(
                    template=template if template.startswith("${") else f"${{{template}}}",
                    node_id=output_info.get("node_id", "unknown"),
                    node_type=output_info.get("node_type", "unknown"),
                    output_key=base_output,
                    output_type=output_type,
                    reason=(
                        f"Array access on '{output_type}' requires valid JSON array at runtime. "
                        f"Non-JSON strings cause 'Unresolved variables' error."
                    ),
                    nested_path=nested_path,
                )
                return (True, warning)
            return (False, None)

        if len(parts) == 2:
            return (True, None)

        # Validate deeper nested path
        return TemplateValidator._validate_nested_path(
            parts[2:], output_info, full_template=template, output_key=base_output
        )

    @staticmethod
    def _validate_template_path(
        template: str,
        initial_params: dict[str, Any],
        node_outputs: dict[str, Any],
        workflow_ir: dict[str, Any],
        registry: Registry,
    ) -> tuple[bool, Optional[ValidationWarning]]:
        """Validate a template path exists in available sources.

        With namespacing enabled, we need to distinguish between:
        1. Node output references (e.g., ${node_id.output_key})
        2. Root-level references (e.g., ${input_file} or ${config.nested.path})

        Args:
            template: Template string like "var" or "var.field.subfield"
            initial_params: Parameters provided by planner
            node_outputs: Full structure info from node interfaces
            workflow_ir: The workflow IR to check for node IDs
            registry: Registry instance (passed through for consistency)

        Returns:
            Tuple of (is_valid, optional_warning)
        """
        parts = template.split(".")
        base_var = parts[0]
        enable_namespacing = workflow_ir.get("enable_namespacing", True)

        # When namespacing is enabled, check if base_var is a node ID
        if enable_namespacing:
            node_ids = TemplateValidator._get_node_ids(workflow_ir)

            if base_var in node_ids:
                # This is a namespaced node output reference
                return TemplateValidator._validate_namespaced_output(parts, base_var, node_outputs, template)

        # Not a node ID reference (or namespacing disabled), check as root-level reference

        # Check initial_params first (higher priority)
        if base_var in initial_params:
            # For nested paths in initial_params, we can't validate at compile time
            # since values are runtime-dependent. This is a limitation.
            return (True, None)

        # Check node outputs (for backward compatibility when namespacing is disabled)
        if base_var in node_outputs:
            if len(parts) == 1:
                return (True, None)

            # Validate nested path in structure
            output_key = base_var  # For non-namespaced, base_var is the output key
            return TemplateValidator._validate_nested_path(
                parts[1:], node_outputs[base_var], full_template=template, output_key=output_key
            )

        return (False, None)

    @staticmethod
    def _check_type_allows_traversal(
        output_type: str, path_parts: list[str], output_info: dict[str, Any], full_template: str, output_key: str
    ) -> tuple[bool, Optional[ValidationWarning]]:
        """Check if output type allows traversal and generate warning if needed.

        Args:
            output_type: The output type string (may be union like "dict|str")
            path_parts: List of path components for warning context
            output_info: Output info dict for warning context
            full_template: Full template string for warning context
            output_key: The output key being accessed

        Returns:
            Tuple of (is_valid, optional_warning)
        """
        # Parse union types (e.g., "dict|str" → ["dict", "str"])
        types_in_union = [t.strip().lower() for t in output_type.split("|")]

        # Check if ANY type in the union allows traversal
        # - dict/object: structured data, traversable (trusted, no warning)
        # - any: explicit "could be anything" declaration (trusted, no warning)
        # - str/string: might contain JSON, defer to runtime via JSON auto-parsing (WARNING)
        traversable_types = [t for t in types_in_union if t in ["dict", "object", "any", "str", "string"]]

        if not traversable_types:
            return (False, None)

        # dict/object and any types are trusted - no warning needed
        # - dict/object: structured data
        # - any: node author explicitly declared "this could be anything"
        trusted_types = [t for t in traversable_types if t in ["dict", "object", "any"]]
        if trusted_types:
            # At least one trusted type - allow without warning
            return (True, None)

        # Only str/string types remain - warn about JSON auto-parsing
        # This is the "surprising" case where nested access works via implicit parsing
        string_types = [t for t in traversable_types if t in ["str", "string"]]
        warning = None

        if string_types and len(path_parts) > 0:
            warning = ValidationWarning(
                template=full_template if full_template.startswith("${") else f"${{{full_template}}}",
                node_id=output_info.get("node_id", "unknown"),
                node_type=output_info.get("node_type", "unknown"),
                output_key=output_key,
                output_type=output_type,
                reason=(
                    f"Nested access on '{output_type}' requires valid JSON at runtime. "
                    f"Non-JSON strings cause 'Unresolved variables' error."
                ),
                nested_path=".".join(path_parts),
            )

        return (True, warning)

    @staticmethod
    def _validate_nested_path(
        path_parts: list[str], output_info: dict[str, Any], full_template: str = "", output_key: str = ""
    ) -> tuple[bool, Optional[ValidationWarning]]:
        """Validate a nested path exists in the output structure.

        Args:
            path_parts: List of path components after the base variable
            output_info: Output info dict with type and structure
            full_template: Full template string for warning context
            output_key: The output key being accessed (for warning)

        Returns:
            Tuple of (is_valid, optional_warning)
        """
        current_structure = output_info.get("structure", {})

        # If no structure info, check if type allows traversal
        if not current_structure:
            output_type = output_info.get("type", "any")
            return TemplateValidator._check_type_allows_traversal(
                output_type, path_parts, output_info, full_template, output_key
            )

        # Traverse the structure
        for i, part in enumerate(path_parts):
            if part not in current_structure:
                return (False, None)

            next_item = current_structure[part]
            if isinstance(next_item, dict):
                # Check if this is a type definition or nested structure
                if "type" in next_item:
                    # This is a field definition
                    if i < len(path_parts) - 1:
                        # More parts to traverse
                        current_structure = next_item.get("structure", {})
                        if not current_structure:
                            # Can't traverse further unless type allows it
                            # str/string allowed for JSON auto-parsing at runtime
                            field_type = next_item.get("type", "any").lower()
                            return (field_type in ["dict", "object", "any", "str", "string"], None)
                    else:
                        # This is the final part - valid
                        return (True, None)
                else:
                    # Direct nested structure
                    current_structure = next_item
            else:
                # Reached a leaf type string, no more traversal possible
                return (i == len(path_parts) - 1, None)

        return (True, None)

    @staticmethod
    def _validate_malformed_templates(workflow_ir: dict[str, Any]) -> list[str]:
        """Detect malformed template syntax by counting ${ vs valid template matches.

        A malformed template is one where we find ${ but it doesn't form a valid template.
        Examples: ${unclosed, ${}, ${ }

        Args:
            workflow_ir: The workflow IR

        Returns:
            List of error messages for malformed templates
        """
        errors: list[str] = []

        for node in workflow_ir.get("nodes", []):
            node_id = node.get("id", "unknown")
            params = node.get("params", {})

            def check_value(value: Any, node_id: str, param_path: str = "") -> None:
                """Recursively check for malformed templates in any value type."""
                if isinstance(value, str) and "${" in value:
                    # Count how many ${ we have
                    dollar_brace_count = value.count("${")

                    # Count how many valid templates we matched
                    valid_matches = TemplateValidator._PERMISSIVE_PATTERN.findall(value)

                    # If mismatch, we have malformed syntax
                    if len(valid_matches) < dollar_brace_count:
                        location = f"node '{node_id}' parameter '{param_path}'" if param_path else f"node '{node_id}'"
                        errors.append(
                            f"Malformed template syntax in {location}: "
                            f"Found {dollar_brace_count} '${{' but only {len(valid_matches)} valid template(s). "
                            f"Check for missing '}}' or empty templates like '${{}}'"
                        )
                elif isinstance(value, dict):
                    for key, val in value.items():
                        check_value(val, node_id, f"{param_path}.{key}" if param_path else key)
                elif isinstance(value, list):
                    for idx, item in enumerate(value):
                        check_value(item, node_id, f"{param_path}[{idx}]")

            for param_key, param_value in params.items():
                check_value(param_value, node_id, param_key)

        return errors

    @staticmethod
    def _extract_all_templates(workflow_ir: dict[str, Any]) -> set[str]:  # noqa: C901
        """Extract all template variables from workflow.

        Scans all node parameters for template variables.
        Uses a more permissive pattern than TemplateResolver to catch
        malformed templates that need syntax validation.

        Args:
            workflow_ir: The workflow IR

        Returns:
            Set of all template variable names found
        """
        templates = set()

        for node in workflow_ir.get("nodes", []):
            node_id = node.get("id", "unknown")
            params = node.get("params", {})

            def extract_from_value(value: Any, node_id: str, path: str = "") -> None:
                """Recursively extract templates from any value type."""
                if isinstance(value, str) and "$" in value:
                    # Use permissive pattern to catch malformed templates
                    matches = TemplateValidator._PERMISSIVE_PATTERN.findall(value)
                    templates.update(matches)

                    if matches:
                        logger.debug(
                            f"Found templates in node '{node_id}' at path '{path}'",
                            extra={"node_id": node_id, "path": path, "templates": sorted(matches)},
                        )
                elif isinstance(value, dict):
                    for key, val in value.items():
                        extract_from_value(val, node_id, f"{path}.{key}" if path else key)
                elif isinstance(value, list):
                    for idx, item in enumerate(value):
                        extract_from_value(item, node_id, f"{path}[{idx}]")

            for param_key, param_value in params.items():
                extract_from_value(param_value, node_id, param_key)

            # Also extract templates from batch.items if present
            batch_config = node.get("batch")
            if batch_config:
                items_template = batch_config.get("items")
                if items_template:
                    extract_from_value(items_template, node_id, "batch.items")

        return templates

    @staticmethod
    def _is_valid_syntax(template: str) -> bool:
        """Check if template syntax is valid.

        Validates:
        - No double dots (..)
        - No leading/trailing dots
        - Valid identifier characters

        Args:
            template: Template variable name (without $)

        Returns:
            True if syntax is valid
        """
        # Check for empty template
        if not template:
            return False

        # Check for double dots
        if ".." in template:
            return False

        # Check for leading/trailing dots
        if template.startswith(".") or template.endswith("."):
            return False

        # Check that all parts are valid identifiers
        parts = template.split(".")
        for part in parts:
            if not part:  # Empty part between dots
                return False
            # Check valid identifier characters (alphanumeric + underscore)
            if not all(c.isalnum() or c == "_" for c in part):
                return False
            # Identifiers shouldn't start with a digit
            if part[0].isdigit():
                return False

        return True

    @staticmethod
    def _validate_template_types(
        workflow_ir: dict[str, Any], node_outputs: dict[str, Any], registry: Registry
    ) -> list[str]:
        """Validate template variable types match parameter expectations.

        Args:
            workflow_ir: Workflow IR
            node_outputs: Node output metadata from registry
            registry: Registry instance

        Returns:
            List of type mismatch errors
        """
        errors = []

        for node in workflow_ir.get("nodes", []):
            node_type = node.get("type")
            node_id = node.get("id")
            params = node.get("params", {})

            for param_name, param_value in params.items():
                # Skip non-template parameters
                if not isinstance(param_value, str) or not TemplateResolver.has_templates(param_value):
                    continue

                # Get expected type for this parameter
                expected_type = get_parameter_type(node_type, param_name, registry)
                if not expected_type or expected_type == "any":
                    # No type constraint or accepts any type
                    continue

                # Extract templates from parameter value
                templates = TemplateResolver.extract_variables(param_value)

                for template in templates:
                    # Infer template type
                    inferred_type = infer_template_type(template, workflow_ir, node_outputs)

                    # Skip if cannot infer (will be caught by path validation)
                    if not inferred_type:
                        continue

                    # Skip if inferred type is 'any' (runtime validation)
                    if inferred_type == "any":
                        continue

                    # Check compatibility
                    if not is_type_compatible(inferred_type, expected_type):
                        error_msg = (
                            f"Type mismatch in node '{node_id}' parameter '{param_name}': "
                            f"template ${{{template}}} has type '{inferred_type}' "
                            f"but parameter expects '{expected_type}'"
                        )

                        # Add helpful suggestions with actual available fields
                        if inferred_type in ["dict", "list", "object"] and expected_type in ["str", "string"]:
                            error_msg += TemplateValidator._generate_type_fix_suggestion(
                                template, node_outputs, expected_type
                            )

                        errors.append(error_msg)

        return errors

    @staticmethod
    def _validate_shell_command_types(workflow_ir: dict[str, Any], node_outputs: dict[str, Any]) -> list[str]:
        """Block dict/list types in shell command parameters.

        Shell commands cannot safely handle JSON embedded in command strings
        due to shell escaping issues. This check runs BEFORE template resolution
        to catch the problem at validation time rather than runtime.

        The general type checker allows dict/list → str (for LLM prompts, HTTP bodies),
        but shell commands are special - embedded JSON breaks shell parsing.

        Validation has three tiers:
        1. Fix 0: Extract base types from generics (list[dict] → list) before checking
        2. Tier 1: Auto-allow unions containing safe types (str, string, any)
        3. Tier 2: Allow templates wrapped in single quotes '${var}' as an escape hatch

        Args:
            workflow_ir: Workflow IR
            node_outputs: Node output metadata from registry

        Returns:
            List of errors for structured data in shell commands
        """
        errors = []
        # Types that cannot be safely embedded in shell command strings.
        # Includes both Python type names (dict, list) and JSON Schema names (object, array)
        # since workflow IR may use either convention.
        SHELL_BLOCKED_TYPES = {"dict", "object", "list", "array"}

        for node in workflow_ir.get("nodes", []):
            node_type = node.get("type")
            node_id = node.get("id")

            # Only check shell nodes
            if node_type != "shell":
                continue

            params = node.get("params", {})
            command = params.get("command", "")

            # Skip if command has no templates
            if not isinstance(command, str) or not TemplateResolver.has_templates(command):
                continue

            # Tier 2: Find templates exactly wrapped in single quotes (escape hatch)
            # Pattern '${var}' signals user accepts runtime coercion to string
            quoted_templates = {match.group(1) for match in _QUOTED_TEMPLATE_PATTERN.finditer(command)}

            # Check each template in the command and collect blocked ones
            templates = TemplateResolver.extract_variables(command)
            blocked_templates: list[tuple[str, str]] = []  # (template, type)

            for template in templates:
                # Tier 2: Skip if template is quoted (user accepts coercion)
                if template in quoted_templates:
                    continue

                inferred_type = infer_template_type(template, workflow_ir, node_outputs)

                # Skip if cannot infer type (will be caught by path validation)
                if not inferred_type:
                    continue

                # Check if type is safe (handles Fix 0 and Tier 1)
                is_safe, blocked_type = _is_shell_safe_type(inferred_type, SHELL_BLOCKED_TYPES)
                if not is_safe and blocked_type:
                    blocked_templates.append((template, blocked_type))

            # Generate a single consolidated error if any templates are blocked
            if blocked_templates:
                display_cmd = command if len(command) <= 60 else command[:57] + "..."

                if len(blocked_templates) == 1:
                    # Single template - simple case
                    template, blocked_type = blocked_templates[0]
                    errors.append(
                        f"Shell node '{node_id}': cannot use ${{{template}}} (type: {blocked_type}) "
                        f"in command parameter.\n\n"
                        f"PROBLEM: {blocked_type} data embedded in shell commands breaks parsing "
                        f"(quotes, backticks, $() cause errors).\n\n"
                        f"CURRENT (breaks):\n"
                        f'  "command": "{display_cmd}"\n\n'
                        f"FIX OPTIONS:\n\n"
                        f"1. Access specific fields (if they're strings/numbers):\n"
                        f"   ${{{template}.fieldname}}, ${{{template}.count}}, etc.\n\n"
                        f"2. Use stdin for the whole object:\n"
                        f'   {{"stdin": "${{{template}}}", "command": "jq \'.field\'"}}\n\n'
                        f"3. Quote the template to accept JSON coercion (if you've verified it's safe):\n"
                        f"   '${{{template}}}' - wrapping in single quotes signals you accept runtime coercion"
                    )
                else:
                    # Multiple templates - need different approach
                    template_list = ", ".join(f"${{{t}}} ({typ})" for t, typ in blocked_templates)
                    errors.append(
                        f"Shell node '{node_id}': multiple structured data templates in command: "
                        f"{template_list}\n\n"
                        f"PROBLEM: Shell commands can only receive ONE data source via stdin.\n\n"
                        f"CURRENT (breaks):\n"
                        f'  "command": "{display_cmd}"\n\n'
                        f"FIX OPTIONS:\n\n"
                        f"1. Use temp files - write each data source to a file, then read in shell:\n"
                        f'   {{"id": "save-a", "type": "write-file", "params": {{"path": "/tmp/a.json", "content": "${{data-a}}"}}}}\n'
                        f'   {{"id": "save-b", "type": "write-file", "params": {{"path": "/tmp/b.json", "content": "${{data-b}}"}}}}\n'
                        f'   {{"id": "process", "type": "shell", "params": {{"command": "jq -s \'.[0] * .[1]\' /tmp/a.json /tmp/b.json"}}}}\n\n'
                        f"2. Process each data source in separate shell nodes, combine results after\n\n"
                        f"3. Pass one via stdin, reference another via file\n\n"
                        f"4. Quote templates to accept JSON coercion (if you've verified they're safe):\n"
                        f"   '${{template}}' - wrapping in single quotes signals you accept runtime coercion"
                    )

        return errors

    @staticmethod
    def _generate_type_fix_suggestion(  # noqa: C901
        template: str, node_outputs: dict[str, Any], expected_type: str
    ) -> str:
        """Generate helpful suggestions for type mismatches with actual available fields.

        Args:
            template: The template variable that has the wrong type
            node_outputs: Node output metadata from registry
            expected_type: The type that was expected

        Returns:
            Suggestion string with available fields
        """
        # For nested templates like node.output.field, we need to traverse to find structure
        # Find the structure for this template by traversing
        structure = None
        for key in node_outputs:
            if template.startswith(key + ".") or template == key:
                output_info = node_outputs[key]
                remaining_path = template[len(key) :].lstrip(".")

                if not remaining_path:
                    # This IS the base output
                    structure = output_info.get("structure", {})
                    break
                else:
                    # Need to traverse nested structure
                    structure = TemplateValidator._traverse_to_structure(
                        output_info.get("structure", {}), remaining_path
                    )
                    if structure:
                        break

        if not structure:
            # Generic fallback
            return f"\n  💡 Suggestion: Access a specific field (e.g., ${{{template}.field}}) or serialize to JSON"

        # Find fields that match the expected type
        matching_fields = []
        for field_name, field_info in structure.items():
            if isinstance(field_info, dict) and "type" in field_info:
                field_type = field_info["type"]
                # Check if this field matches the expected type
                if field_type in [expected_type, "str", "string"] and expected_type in ["str", "string"]:
                    matching_fields.append(field_name)

        if matching_fields:
            suggestion = "\n  💡 Available fields with correct type:"
            for field in matching_fields[:5]:  # Show up to 5
                suggestion += f"\n     - ${{{template}.{field}}}"
            if len(matching_fields) > 5:
                suggestion += f"\n     ... and {len(matching_fields) - 5} more"
            return suggestion
        else:
            return "\n  💡 Suggestion: Access a nested field or serialize to JSON"

    @staticmethod
    def _traverse_to_structure(structure: dict[str, Any], path: str) -> Optional[dict[str, Any]]:
        """Traverse nested structure to find the structure at a given path.

        Args:
            structure: The structure dict to traverse
            path: Dot-separated path like "author.login"

        Returns:
            The structure dict at that path, or None if not found
        """
        if not path or not structure:
            return structure

        path_parts = path.split(".")
        current = structure

        for part in path_parts:
            if part in current:
                field_info = current[part]
                if isinstance(field_info, dict):
                    current = field_info.get("structure", {})
                    if not current:
                        return None
                else:
                    return None
            else:
                return None

        return current
