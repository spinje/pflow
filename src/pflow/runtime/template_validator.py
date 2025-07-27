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
    def validate_workflow_templates(
        workflow_ir: dict[str, Any], available_params: dict[str, Any], registry: Registry
    ) -> list[str]:
        """
        Validates all template variables in a workflow.

        Uses the registry to determine which variables are written by nodes
        and validates that all template paths exist in the node outputs.

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

        if not all_templates:
            # No templates to validate
            logger.debug("No template variables found in workflow")
            return errors

        logger.debug(
            f"Found {len(all_templates)} template variables to validate", extra={"templates": sorted(all_templates)}
        )

        # Get full output structure from nodes
        node_outputs = TemplateValidator._extract_node_outputs(workflow_ir, registry)

        logger.debug(
            f"Extracted outputs from {len(node_outputs)} node variables", extra={"outputs": sorted(node_outputs.keys())}
        )

        # Validate each template path
        for template in sorted(all_templates):
            if not TemplateValidator._validate_template_path(template, available_params, node_outputs):
                # Check if it's a base variable or a path
                if "." in template:
                    base_var = template.split(".")[0]
                    if base_var in available_params:
                        errors.append(
                            f"Template path ${template} cannot be validated - initial_params values are runtime-dependent"
                        )
                    else:
                        # Extract the path component after the base variable
                        path_component = template[len(base_var) + 1 :] if "." in template else template
                        errors.append(
                            f"Template variable ${template} has no valid source - "
                            f"not provided in initial_params and path '{path_component}' "
                            f"not found in outputs from any node in the workflow"
                        )
                else:
                    # Simple variable not found
                    errors.append(
                        f"Template variable ${template} has no valid source - "
                        f"not provided in initial_params and not written by any node"
                    )

        if errors:
            logger.warning(
                f"Template validation found {len(errors)} errors", extra={"error_count": len(errors), "errors": errors}
            )
        else:
            logger.info("Template validation passed")

        return errors

    # More permissive pattern to catch malformed templates for validation
    _PERMISSIVE_PATTERN = re.compile(r"\$([a-zA-Z_]\w*(?:\.\w*)*)")

    @staticmethod
    def _extract_node_outputs(workflow_ir: dict[str, Any], registry: Registry) -> dict[str, Any]:
        """Extract full output structures from nodes using interface metadata.

        Returns:
            Dict mapping variable names to their full structure/type info
        """
        node_outputs = {}

        for node in workflow_ir.get("nodes", []):
            node_type = node.get("type")
            if not node_type:
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
                    node_outputs[output] = {"type": "any"}
                else:
                    # Rich format: includes type and structure
                    key = output["key"]
                    node_outputs[key] = {"type": output.get("type", "any"), "structure": output.get("structure", {})}

        return node_outputs

    @staticmethod
    def _validate_template_path(template: str, initial_params: dict[str, Any], node_outputs: dict[str, Any]) -> bool:
        """Validate a template path exists in available sources.

        For example, if template is "api_config.endpoint.url":
        1. Check if "api_config" exists in initial_params or node_outputs
        2. If from node_outputs, traverse the structure to verify path exists
        3. If from initial_params, check runtime value (if dict) or return True

        Args:
            template: Template string like "var" or "var.field.subfield"
            initial_params: Parameters provided by planner
            node_outputs: Full structure info from node interfaces

        Returns:
            True if the path is valid, False otherwise
        """
        parts = template.split(".")
        base_var = parts[0]

        # Check initial_params first (higher priority)
        if base_var in initial_params:
            # For nested paths in initial_params, we can't validate at compile time
            # since values are runtime-dependent. This is a limitation.
            return True

        # Check node outputs with full structure validation
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
