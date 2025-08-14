"""Template variable validation for workflow execution.

This module provides validation functionality to ensure all required
template variables have corresponding parameters available before
workflow execution begins.
"""

import logging
import re
from typing import Any

from pflow.registry import Registry

logger = logging.getLogger(__name__)


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
    ) -> list[str]:
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
            List of error messages (empty if valid)
        """
        errors: list[str] = []

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
            return errors

        # Get full output structure from nodes
        node_outputs = TemplateValidator._extract_node_outputs(workflow_ir, registry)

        logger.debug(
            f"Extracted outputs from {len(node_outputs)} node variables", extra={"outputs": sorted(node_outputs.keys())}
        )

        # Validate each template path
        for template in sorted(all_templates):
            if not TemplateValidator._validate_template_path(
                template, available_params, node_outputs, workflow_ir, registry
            ):
                error = TemplateValidator._create_template_error(
                    template, available_params, workflow_ir, node_outputs, registry
                )
                errors.append(error)

        if errors:
            logger.warning(
                f"Template validation found {len(errors)} errors", extra={"error_count": len(errors), "errors": errors}
            )
        else:
            logger.info("Template validation passed")

        return errors

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
                # This should be a namespaced node output reference
                if len(parts) == 1:
                    return f"Invalid template ${template} - node ID '{base_var}' requires an output key (e.g., ${base_var}.output_key)"

                output_key = parts[1]

                # Get the node type to provide better error message
                node = next((n for n in workflow_ir.get("nodes", []) if n.get("id") == base_var), None)
                if node:
                    node_type = node.get("type", "unknown")

                    # Check what outputs this node type actually has
                    try:
                        nodes_metadata = registry.get_nodes_metadata([node_type])
                        if node_type in nodes_metadata:
                            interface = nodes_metadata[node_type]["interface"]
                            available_outputs = []
                            for output in interface["outputs"]:
                                if isinstance(output, str):
                                    available_outputs.append(output)
                                else:
                                    available_outputs.append(output["key"])

                            if available_outputs:
                                return (
                                    f"Node '{base_var}' (type: {node_type}) does not output '{output_key}'. "
                                    f"Available outputs: {', '.join(available_outputs)}"
                                )
                            else:
                                return f"Node '{base_var}' (type: {node_type}) does not produce any outputs"
                    except:
                        pass

                return f"Node '{base_var}' does not output '{output_key}'"

        # Not a node reference, treat as root-level variable
        if "." in template:
            if base_var in available_params:
                return f"Template path ${template} cannot be validated - initial_params values are runtime-dependent"

            # Check if base variable is a declared input
            input_desc = TemplateValidator._get_input_description(base_var, workflow_ir)
            path_component = template[len(base_var) + 1 :]

            if input_desc:
                return (
                    f"Required input '${base_var}' not provided{input_desc} - "
                    f"attempted to access path '{path_component}'"
                )
            else:
                # For namespacing mode, be clearer about what's wrong
                if enable_namespacing:
                    return (
                        f"Template variable ${template} has no valid source - "
                        f"'${base_var}' is neither a workflow input nor a node ID in this workflow"
                    )
                else:
                    return (
                        f"Template variable ${template} has no valid source - "
                        f"not provided in initial_params and path '{path_component}' "
                        f"not found in outputs from any node in the workflow"
                    )
        else:
            # Simple variable not found
            input_desc = TemplateValidator._get_input_description(template, workflow_ir)

            if input_desc:
                return f"Required input '${template}' not provided{input_desc}"
            else:
                # Check if it might be a node ID used incorrectly
                if enable_namespacing:
                    node_ids = TemplateValidator._get_node_ids(workflow_ir)
                    if template in node_ids:
                        return (
                            f"Invalid template ${template} - this is a node ID. "
                            f"To reference node outputs, use ${template}.output_key format"
                        )

                return (
                    f"Template variable ${template} has no valid source - "
                    f"not provided in initial_params and not written by any node"
                )

    # More permissive pattern to catch malformed templates for validation
    _PERMISSIVE_PATTERN = re.compile(r"\$([a-zA-Z_]\w*(?:\.\w*)*)")

    @staticmethod
    def _extract_node_outputs(workflow_ir: dict[str, Any], registry: Registry) -> dict[str, Any]:
        """Extract full output structures from nodes using interface metadata.

        When namespacing is enabled, outputs are registered under both:
        - The original key (for backward compatibility checks)
        - The namespaced path "node_id.output_key"

        Returns:
            Dict mapping variable names to their full structure/type info
        """
        node_outputs = {}
        enable_namespacing = workflow_ir.get("enable_namespacing", True)

        for node in workflow_ir.get("nodes", []):
            node_id = node.get("id")
            node_type = node.get("type")
            if not node_type or not node_id:
                continue

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

        return node_outputs

    @staticmethod
    def _validate_template_path(
        template: str,
        initial_params: dict[str, Any],
        node_outputs: dict[str, Any],
        workflow_ir: dict[str, Any],
        registry: Registry,
    ) -> bool:
        """Validate a template path exists in available sources.

        With namespacing enabled, we need to distinguish between:
        1. Node output references (e.g., $node_id.output_key)
        2. Root-level references (e.g., $input_file or $config.nested.path)

        Args:
            template: Template string like "var" or "var.field.subfield"
            initial_params: Parameters provided by planner
            node_outputs: Full structure info from node interfaces
            workflow_ir: The workflow IR to check for node IDs
            registry: Registry instance (passed through for consistency)

        Returns:
            True if the path is valid, False otherwise
        """
        parts = template.split(".")
        base_var = parts[0]
        enable_namespacing = workflow_ir.get("enable_namespacing", True)

        # When namespacing is enabled, check if base_var is a node ID
        if enable_namespacing:
            node_ids = TemplateValidator._get_node_ids(workflow_ir)

            if base_var in node_ids:
                # This is a namespaced node output reference
                # The full path should be in node_outputs as "node_id.output_key"
                if len(parts) == 1:
                    # Just the node ID without output key - invalid
                    return False

                # Check if the namespaced path exists in node_outputs
                node_output_key = f"{base_var}.{parts[1]}"
                if node_output_key in node_outputs:
                    if len(parts) == 2:
                        # Just node_id.output_key - valid
                        return True
                    # Validate deeper nested path
                    return TemplateValidator._validate_nested_path(parts[2:], node_outputs[node_output_key])
                return False

        # Not a node ID reference (or namespacing disabled), check as root-level reference

        # Check initial_params first (higher priority)
        if base_var in initial_params:
            # For nested paths in initial_params, we can't validate at compile time
            # since values are runtime-dependent. This is a limitation.
            return True

        # Check node outputs (for backward compatibility when namespacing is disabled)
        if base_var in node_outputs:
            if len(parts) == 1:
                return True

            # Validate nested path in structure
            return TemplateValidator._validate_nested_path(parts[1:], node_outputs[base_var])

        return False

    @staticmethod
    def _validate_nested_path(path_parts: list[str], output_info: dict[str, Any]) -> bool:
        """Validate a nested path exists in the output structure.

        Args:
            path_parts: List of path components after the base variable
            output_info: Output info dict with type and structure

        Returns:
            True if the path is valid, False otherwise
        """
        current_structure = output_info.get("structure", {})

        # If no structure info, check if type allows traversal
        if not current_structure:
            output_type = output_info.get("type", "any")
            return output_type in ["dict", "object", "any"]

        # Traverse the structure
        for i, part in enumerate(path_parts):
            if part not in current_structure:
                return False

            next_item = current_structure[part]
            if isinstance(next_item, dict):
                # Check if this is a type definition or nested structure
                if "type" in next_item:
                    # This is a field definition
                    if i < len(path_parts) - 1:
                        # More parts to traverse
                        current_structure = next_item.get("structure", {})
                        if not current_structure:
                            # Can't traverse further into a non-dict type
                            return next_item.get("type", "any") in ["dict", "object", "any"]
                    else:
                        # This is the final part - valid
                        return True
                else:
                    # Direct nested structure
                    current_structure = next_item
            else:
                # Reached a leaf type string, no more traversal possible
                return i == len(path_parts) - 1

        return True

    @staticmethod
    def _extract_all_templates(workflow_ir: dict[str, Any]) -> set[str]:
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

            for param_key, param_value in params.items():
                if isinstance(param_value, str) and "$" in param_value:
                    # Use permissive pattern to catch malformed templates
                    matches = TemplateValidator._PERMISSIVE_PATTERN.findall(param_value)
                    templates.update(matches)

                    if matches:
                        logger.debug(
                            f"Found templates in node '{node_id}' param '{param_key}'",
                            extra={"node_id": node_id, "param_key": param_key, "templates": sorted(matches)},
                        )

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
