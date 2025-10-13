"""Unified workflow validation system.

This module provides the single source of truth for all workflow validation,
ensuring consistency between production, tests, and any other consumers.
"""

import logging
from typing import Any, Optional

from pflow.registry import Registry

logger = logging.getLogger(__name__)


class WorkflowValidator:
    """Orchestrates all workflow validation checks.

    This class provides a unified interface for all workflow validation,
    consolidating structural, template, node type, and data flow validation
    into a single source of truth.
    """

    @staticmethod
    def validate(
        workflow_ir: dict[str, Any],
        extracted_params: Optional[dict[str, Any]] = None,
        registry: Optional[Registry] = None,
        skip_node_types: bool = False,
    ) -> tuple[list[str], list[Any]]:
        """Run complete workflow validation.

        Performs multiple validation checks:
        1. Structural validation - IR schema compliance
        2. Data flow validation - Execution order and dependencies
        3. Template validation - Variable resolution
        4. Node type validation - Registry verification
        5. Output source validation - Output node references

        Args:
            workflow_ir: Workflow to validate
            extracted_params: Parameters extracted from user input
            registry: Node registry (uses default if None)
            skip_node_types: Skip node type validation (for mock nodes in tests)

        Returns:
            Tuple of (errors, warnings):
            - errors: List of validation errors that prevent execution
            - warnings: List of ValidationWarning objects for runtime-validated templates
        """
        errors = []
        warnings = []

        # 1. Structural validation (ALWAYS run)
        struct_errors = WorkflowValidator._validate_structure(workflow_ir)
        errors.extend(struct_errors)

        # 2. Data flow validation (NEW - ALWAYS run)
        flow_errors = WorkflowValidator._validate_data_flow(workflow_ir)
        errors.extend(flow_errors)

        # 3. Template validation (if params provided)
        if extracted_params is not None:
            if registry is None:
                registry = Registry()
            template_errors, template_warnings = WorkflowValidator._validate_templates(
                workflow_ir, extracted_params, registry
            )
            errors.extend(template_errors)
            warnings.extend(template_warnings)

        # 4. Node type validation (if not skipped)
        if not skip_node_types:
            if registry is None:
                registry = Registry()
            type_errors = WorkflowValidator._validate_node_types(workflow_ir, registry)
            errors.extend(type_errors)

        # 5. Output source validation (ALWAYS run - validate output references)
        output_errors, output_warnings = WorkflowValidator._validate_output_sources(workflow_ir, registry)
        errors.extend(output_errors)
        warnings.extend(output_warnings)

        if errors:
            logger.debug(f"Validation found {len(errors)} errors")
        elif warnings:
            logger.debug(f"Validation passed with {len(warnings)} runtime-validated template(s)")
        else:
            logger.debug("Validation passed")

        return (errors, warnings)

    @staticmethod
    def _validate_structure(workflow_ir: dict[str, Any]) -> list[str]:
        """Validate IR structure and schema compliance.

        Args:
            workflow_ir: Workflow to validate

        Returns:
            List of structural validation errors
        """
        from pflow.core.ir_schema import validate_ir

        try:
            validate_ir(workflow_ir)
            return []
        except Exception as e:
            # Handle both ValidationError and other exceptions
            if hasattr(e, "path") and hasattr(e, "message"):
                # ValidationError with path
                error_msg = f"{e.path}: {e.message}" if e.path else str(e.message)
            else:
                # Other exceptions or ValidationError without path
                error_msg = str(e)
            return [f"Structure: {error_msg}"]

    @staticmethod
    def _validate_data_flow(workflow_ir: dict[str, Any]) -> list[str]:
        """Validate execution order and data dependencies.

        Args:
            workflow_ir: Workflow to validate

        Returns:
            List of data flow validation errors
        """
        from pflow.core.workflow_data_flow import validate_data_flow

        try:
            return validate_data_flow(workflow_ir)
        except Exception as e:
            return [f"Data flow validation error: {e!s}"]

    @staticmethod
    def _validate_templates(
        workflow_ir: dict[str, Any], extracted_params: dict[str, Any], registry: Registry
    ) -> tuple[list[str], list[Any]]:
        """Validate template variables and parameters.

        Args:
            workflow_ir: Workflow to validate
            extracted_params: Parameters extracted from user input
            registry: Node registry

        Returns:
            Tuple of (errors, warnings):
            - errors: List of template validation errors
            - warnings: List of ValidationWarning objects
        """
        from pflow.runtime.template_validator import TemplateValidator

        try:
            errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, extracted_params, registry)
            return (errors, warnings)
        except Exception as e:
            return ([f"Template validation error: {e!s}"], [])

    @staticmethod
    def _validate_node_types(workflow_ir: dict[str, Any], registry: Registry) -> list[str]:
        """Validate all node types exist in registry.

        Args:
            workflow_ir: Workflow to validate
            registry: Node registry

        Returns:
            List of unknown node type errors
        """
        errors = []

        try:
            # Extract all node types from the workflow
            node_types = {node.get("type") for node in workflow_ir.get("nodes", []) if node.get("type")}

            if node_types:
                # Get metadata for these specific node types
                metadata = registry.get_nodes_metadata(node_types)

                # Check if any are unknown
                for node_type in node_types:
                    if node_type not in metadata:
                        errors.append(f"Unknown node type: '{node_type}'")
        except Exception as e:
            errors.append(f"Registry validation error: {e!s}")

        return errors

    @staticmethod
    def _validate_output_sources(
        workflow_ir: dict[str, Any], registry: Optional[Registry] = None
    ) -> tuple[list[str], list[Any]]:
        """Validate that workflow outputs reference valid nodes and output keys.

        This validation ensures that output source fields (when specified) point to
        existing nodes in the workflow. The source field can use two formats:
        - "node_id" - References entire node output
        - "node_id.output_key" - References specific output key

        Template variables (${...}) are skipped as they cannot be validated statically.

        Args:
            workflow_ir: Workflow to validate
            registry: Optional registry for enhanced validation (not used in v1)

        Returns:
            Tuple of (errors, warnings):
            - errors: List of validation errors (non-existent node references)
            - warnings: List of warnings (template variables, etc.)
        """
        errors: list[str] = []
        warnings: list[Any] = []

        # Early return if no outputs defined
        outputs = workflow_ir.get("outputs", {})
        if not outputs:
            return (errors, warnings)

        # Build nodes map for O(1) lookup
        nodes_map = {node["id"]: node for node in workflow_ir.get("nodes", [])}

        # Validate each output's source field
        for output_name, output_def in outputs.items():
            source = output_def.get("source")

            # Skip if no source specified (outputs without source are valid)
            if source is None:
                continue

            # Validate source is non-empty string
            if not isinstance(source, str) or not source.strip():
                errors.append(
                    f"Output '{output_name}' has empty source field. Use 'node_id' or 'node_id.output_key' format."
                )
                continue

            # Skip template variables (cannot validate statically)
            if "${" in source:
                # Optional: Add debug log for template variables
                logger.debug(f"Output '{output_name}' uses template variable in source - skipping static validation")
                continue

            # Parse source format: "node_id.output_key" or "node_id"
            if "." in source:
                # Split on first dot only (supports nested keys like "node.a.b.c")
                node_id, _output_key = source.split(".", 1)
            else:
                # Reference to entire node output
                node_id = source

            # Validate node exists
            if node_id not in nodes_map:
                # Build helpful error with available nodes
                available_nodes = sorted(nodes_map.keys())
                if available_nodes:
                    suggestion = f" Available nodes: {', '.join(available_nodes)}"
                else:
                    suggestion = " Workflow has no nodes."

                errors.append(f"Output '{output_name}' references non-existent node '{node_id}'.{suggestion}")
                continue

            # Note: Output key validation skipped in v1
            # We don't have reliable node output metadata at validation time
            # This could be added in future versions when registry has full interface specs

        return (errors, warnings)
