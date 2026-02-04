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
        2. Stdin input validation - Only one stdin: true allowed
        3. Data flow validation - Execution order and dependencies
        4. Template validation - Variable resolution
        5. Node type validation - Registry verification
        6. Output source validation - Output node references
        7. Unknown param warnings - Flags params not in node interface

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

        # 2. Stdin input validation (ALWAYS run - only one stdin: true allowed)
        stdin_errors = WorkflowValidator._validate_stdin_inputs(workflow_ir)
        errors.extend(stdin_errors)

        # 3. Data flow validation (ALWAYS run)
        flow_errors = WorkflowValidator._validate_data_flow(workflow_ir)
        errors.extend(flow_errors)

        # 4. Template validation (if params provided)
        if extracted_params is not None:
            if registry is None:
                registry = Registry()
            template_errors, template_warnings = WorkflowValidator._validate_templates(
                workflow_ir, extracted_params, registry
            )
            errors.extend(template_errors)
            warnings.extend(template_warnings)

        # 5. Node type validation (if not skipped)
        if not skip_node_types:
            if registry is None:
                registry = Registry()
            type_errors = WorkflowValidator._validate_node_types(workflow_ir, registry)
            errors.extend(type_errors)

        # 6. Output source validation (ALWAYS run - validate output references)
        output_errors, output_warnings = WorkflowValidator._validate_output_sources(workflow_ir, registry)
        errors.extend(output_errors)
        warnings.extend(output_warnings)

        # 7. Unknown param warnings
        # Only run if registry available (need interface metadata for param keys)
        if registry is not None:
            unknown_param_warnings = WorkflowValidator._validate_unknown_params(workflow_ir, registry)
            warnings.extend(unknown_param_warnings)

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
            # Use str(e) to get full error including suggestions
            # ValidationError.__str__() includes path, message, and suggestions
            error_msg = str(e)
            return [f"Structure: {error_msg}"]

    @staticmethod
    def _validate_stdin_inputs(workflow_ir: dict[str, Any]) -> list[str]:
        """Validate that at most one input has stdin: true.

        Args:
            workflow_ir: Workflow to validate

        Returns:
            List of stdin validation errors
        """
        inputs = workflow_ir.get("inputs", {})
        if not inputs:
            return []

        stdin_inputs = [name for name, spec in inputs.items() if spec.get("stdin") is True]

        if len(stdin_inputs) > 1:
            return [
                f'Multiple inputs marked with "stdin": true: {", ".join(stdin_inputs)}. '
                "Only one input can receive piped stdin."
            ]

        return []

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

        # Types handled specially by the compiler, not registered in the node registry
        compiler_special_types = {"workflow", "pflow.runtime.workflow_executor"}

        try:
            # Extract all node types from the workflow
            node_types = {node.get("type") for node in workflow_ir.get("nodes", []) if node.get("type")}

            # Filter out compiler-handled special types
            registry_types = node_types - compiler_special_types

            if registry_types:
                # Get metadata for these specific node types
                metadata = registry.get_nodes_metadata(registry_types)

                # Check if any are unknown
                for node_type in registry_types:
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
            # Skip if output_def is not a dict (schema validation should catch this)
            if not isinstance(output_def, dict):
                continue

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

            # Validate templates instead of skipping
            if "${" in source:
                template_errors = WorkflowValidator._validate_template_in_source(output_name, source, nodes_map)
                errors.extend(template_errors)
                continue

            # Parse source format: "node_id.output_key" or "node_id"
            if "." in source:
                # Split on first dot only (supports nested keys like "node.a.b.c")
                node_id, output_key = source.split(".", 1)
            else:
                # Reference to entire node output
                node_id = source

            # Validate node exists
            if node_id not in nodes_map:
                error_msg = WorkflowValidator._format_node_not_found_error(output_name, node_id, nodes_map)
                errors.append(error_msg)
                continue

            # Note: Output key validation skipped in v1
            # We don't have reliable node output metadata at validation time
            # This could be added in future versions when registry has full interface specs

        return (errors, warnings)

    @staticmethod
    def _validate_template_in_source(output_name: str, source: str, nodes_map: dict[str, Any]) -> list[str]:
        """Validate template variable references in output source.

        Validates that ${node.key} templates reference existing nodes.
        Provides "Did you mean?" suggestions for typos.

        Args:
            output_name: Name of output being validated
            source: Source value with template (e.g., "${node.key}")
            nodes_map: Map of node IDs to definitions

        Returns:
            List of error messages (empty if valid)
        """
        import re

        errors = []

        # Extract template variables: ${...}
        template_pattern = r"\$\{([^}]+)\}"
        matches = re.findall(template_pattern, source)

        if not matches:
            # Has ${ but malformed
            errors.append(
                f"Output '{output_name}' has malformed template: '{source}'\n"
                f"Use format: ${{variable}} or ${{node.output_key}}"
            )
            return errors

        # Validate each template
        for template_var in matches:
            # Skip if not a node reference (no dot)
            if "." not in template_var:
                continue  # Could be workflow input

            # Parse node.key
            node_id = template_var.split(".", 1)[0]
            output_key = template_var.split(".", 1)[1] if "." in template_var else None

            # Validate node exists
            if node_id not in nodes_map:
                error_msg = WorkflowValidator._format_template_node_error(
                    output_name, source, node_id, output_key, nodes_map
                )
                errors.append(error_msg)

        return errors

    @staticmethod
    def _format_node_not_found_error(output_name: str, node_id: str, nodes_map: dict[str, Any]) -> str:
        """Format error for plain reference to non-existent node."""
        available = sorted(nodes_map.keys())

        lines = [f"Output '{output_name}' references non-existent node '{node_id}'."]

        if available:
            lines.append(f"\nAvailable nodes: {', '.join(available)}")

            # Fuzzy match suggestions
            from pflow.core.suggestion_utils import find_similar_items

            similar = find_similar_items(node_id, available, max_results=3, method="fuzzy")

            if similar:
                lines.append("\nDid you mean?")
                for suggestion in similar:
                    lines.append(f"  - {suggestion}")
        else:
            lines.append("\nWorkflow has no nodes.")

        return "\n".join(lines)

    @staticmethod
    def _format_template_node_error(
        output_name: str,
        source: str,
        node_id: str,
        output_key: str | None,
        nodes_map: dict[str, Any],
    ) -> str:
        """Format enhanced error for template reference (follows template_validator pattern).

        This provides the "gold standard" error format:
        - Problem statement
        - Available options
        - Suggestions with fuzzy matching
        - Concrete fix
        """
        available = sorted(nodes_map.keys())

        # Section 1: Problem
        lines = [
            f"Output '{output_name}' source references non-existent node '{node_id}'",
            f"Template: {source}",
        ]

        # Section 2: Available nodes
        if available:
            lines.append("\nAvailable nodes in workflow:")
            for node in available[:10]:
                lines.append(f"  ✓ {node}")
            if len(available) > 10:
                lines.append(f"  ... and {len(available) - 10} more")
        else:
            lines.append("\nWorkflow has no nodes.")
            return "\n".join(lines)

        # Section 3: Suggestions (fuzzy match)
        from pflow.core.suggestion_utils import find_similar_items

        similar = find_similar_items(node_id, available, max_results=3, method="fuzzy")

        if similar:
            lines.append("\nDid you mean one of these?")
            for suggestion in similar:
                # Reconstruct template with correct node
                corrected = f"${{{suggestion}.{output_key}}}" if output_key else f"${{{suggestion}}}"
                lines.append(f"  - {corrected}")

            # Section 4: Concrete fix
            best = similar[0]
            corrected = f"${{{best}.{output_key}}}" if output_key else f"${{{best}}}"

            lines.append("\nSuggested fix:")
            lines.append(f'  Change: "{source}"')
            lines.append(f'  To:     "{corrected}"')

        return "\n".join(lines)

    # =========================================================================
    # Unknown Param Warnings (Step 7)
    # =========================================================================

    @staticmethod
    def _extract_known_keys(interface: dict[str, Any]) -> set[str]:
        """Extract known parameter keys from a node's interface metadata."""
        known_keys: set[str] = set()
        for param in interface.get("params", []):
            if isinstance(param, dict) and param.get("key"):
                known_keys.add(param["key"])
        for inp in interface.get("inputs", []):
            if isinstance(inp, dict) and inp.get("key"):
                known_keys.add(inp["key"])
        return known_keys

    @staticmethod
    def _validate_unknown_params(
        workflow_ir: dict[str, Any],
        registry: Registry,
    ) -> list[Any]:
        """Warn about parameters not recognized by the node's interface.

        Compares each node's params keys against the known params from registry
        interface metadata. Unknown params produce warnings (not errors) since
        they don't break execution but may indicate typos or documentation
        bullets accidentally parsed as params.

        Args:
            workflow_ir: Workflow to validate
            registry: Node registry for interface metadata

        Returns:
            List of warning strings for unknown parameters
        """
        from pflow.core.suggestion_utils import find_similar_items

        warning_list: list[Any] = []

        try:
            node_types = {node.get("type") for node in workflow_ir.get("nodes", []) if node.get("type")}
            nodes_metadata = registry.get_nodes_metadata(node_types) if node_types else {}
        except Exception as e:
            logger.debug(f"Could not load registry metadata for unknown param validation: {e}")
            return warning_list

        for node in workflow_ir.get("nodes", []):
            node_id = node.get("id", "unknown")
            node_type = node.get("type", "")
            params = node.get("params", {})

            if not params:
                continue

            interface = nodes_metadata.get(node_type, {}).get("interface", {})
            known_keys = WorkflowValidator._extract_known_keys(interface)

            if not known_keys:
                continue

            for param_key in params:
                if param_key not in known_keys:
                    msg = f"Node '{node_id}' ({node_type}): unknown parameter '{param_key}'."
                    similar = find_similar_items(param_key, sorted(known_keys), max_results=2, method="fuzzy")
                    if similar:
                        suggestions = ", ".join(f"'{s}'" for s in similar)
                        msg += f" Did you mean {suggestions}?"
                    warning_list.append(msg)

        return warning_list
