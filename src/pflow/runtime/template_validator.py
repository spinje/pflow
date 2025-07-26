"""Template variable validation for workflow execution.

This module provides validation functionality to ensure all required
template variables have corresponding parameters available before
workflow execution begins.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class TemplateValidator:
    """Validates template variables before workflow execution."""

    @staticmethod
    def validate_workflow_templates(workflow_ir: dict[str, Any], available_params: dict[str, Any]) -> list[str]:
        """
        Validates all template variables in a workflow.

        Checks that:
        1. All template variables have valid syntax
        2. Required CLI parameters are available
        3. Distinguishes between CLI params and shared store variables

        Args:
            workflow_ir: The workflow IR containing nodes with template parameters
            available_params: Parameters available from planner or CLI

        Returns:
            List of error messages (empty if valid)

        Note:
            CLI parameters (those matching available_params keys) MUST be provided.
            Shared store variables (from node execution) are validated at runtime only.
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

        # Separate CLI params from potential shared store vars
        cli_params, shared_vars = TemplateValidator._categorize_templates(all_templates, available_params)

        logger.debug(
            f"Categorized templates - CLI params: {len(cli_params)}, Shared store vars: {len(shared_vars)}",
            extra={"cli_params": sorted(cli_params), "shared_vars": sorted(shared_vars)},
        )

        # Note: In v2.0+, workflows will include metadata with expected inputs:
        # {"inputs": ["url", "issue_number"], "ir": {...}}
        # This will make validation more precise than the current heuristic

        # Validate CLI parameters - these MUST be provided
        missing_params = cli_params - set(available_params.keys())
        for param in sorted(missing_params):  # Sort for consistent error order
            errors.append(f"Missing required parameter: --{param}")

        # For shared store variables, we can't validate until runtime
        # But we can check syntax
        for var in shared_vars:
            if not TemplateValidator._is_valid_syntax(var):
                errors.append(f"Invalid template syntax: ${var}")

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
    def _categorize_templates(all_templates: set[str], available_params: dict[str, Any]) -> tuple[set[str], set[str]]:
        """Categorize templates into CLI params vs shared store variables.

        Uses heuristics to determine which templates are CLI parameters
        (that must be provided) vs shared store variables (validated at runtime).

        Args:
            all_templates: Set of all template variable names
            available_params: Available parameters from planner/CLI

        Returns:
            Tuple of (cli_params, shared_vars)
        """
        cli_params = set()
        shared_vars = set()

        # Common variable names that are typically outputs from nodes
        common_outputs = {
            "result",
            "output",
            "summary",
            "content",
            "response",
            "data",
            "text",
            "error",
            "status",
            "report",
            "analysis",
        }

        for template in all_templates:
            base_var = template.split(".")[0]

            if "." in template:
                # Dotted variable - check if base is a known CLI param
                if base_var in available_params:
                    cli_params.add(base_var)
                else:
                    shared_vars.add(template)
            else:
                # Simple variable - use heuristics
                if base_var in available_params:
                    cli_params.add(base_var)
                elif base_var in common_outputs:
                    shared_vars.add(template)
                else:
                    cli_params.add(base_var)

        return cli_params, shared_vars

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
