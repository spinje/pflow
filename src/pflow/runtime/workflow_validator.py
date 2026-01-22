"""Workflow validation functions for pflow runtime.

This module contains validation functions extracted from the compiler to improve
code organization and separation of concerns. These functions validate workflow
IR structure and prepare inputs with defaults.

Key functions:
- validate_ir_structure: Validates basic IR structure (nodes, edges arrays)
- prepare_inputs: Validates inputs and returns defaults to apply
"""

import logging
import os
from typing import Any

from pflow.core.validation_utils import get_parameter_validation_error, is_valid_parameter_name

logger = logging.getLogger(__name__)


def validate_ir_structure(ir_dict: dict[str, Any]) -> None:
    """Validate basic IR structure (nodes, edges arrays).

    This performs minimal structural validation to ensure the IR has
    the required top-level keys. Full validation should be done by
    the IR schema validator before compilation.

    Args:
        ir_dict: The IR dictionary to validate

    Raises:
        CompilationError: If required keys are missing or have wrong types
    """
    from .compiler import CompilationError

    logger.debug("Validating IR structure", extra={"phase": "validation"})

    # Check for required 'nodes' key
    if "nodes" not in ir_dict:
        raise CompilationError(
            "Missing 'nodes' key in IR", phase="validation", suggestion="IR must contain 'nodes' array"
        )

    # Check nodes is a list
    if not isinstance(ir_dict["nodes"], list):
        raise CompilationError(
            f"'nodes' must be an array, got {type(ir_dict['nodes']).__name__}",
            phase="validation",
            suggestion="Ensure 'nodes' is an array of node objects",
        )

    # Check for required 'edges' key
    if "edges" not in ir_dict:
        raise CompilationError(
            "Missing 'edges' key in IR", phase="validation", suggestion="IR must contain 'edges' array (can be empty)"
        )

    # Check edges is a list
    if not isinstance(ir_dict["edges"], list):
        raise CompilationError(
            f"'edges' must be an array, got {type(ir_dict['edges']).__name__}",
            phase="validation",
            suggestion="Ensure 'edges' is an array of edge objects",
        )

    logger.debug(
        "IR structure validated",
        extra={"phase": "validation", "node_count": len(ir_dict["nodes"]), "edge_count": len(ir_dict["edges"])},
    )


def prepare_inputs(
    workflow_ir: dict[str, Any], provided_params: dict[str, Any], settings_env: dict[str, str] | None = None
) -> tuple[list[tuple[str, str, str]], dict[str, Any], set[str]]:
    """Validate workflow inputs and return defaults to apply.

    This function validates that all required inputs are present in provided_params,
    determines default values for missing optional inputs, and validates input names
    are valid Python identifiers. Unlike the original _validate_inputs, this function
    does NOT mutate provided_params - it returns defaults to be applied by the caller.

    Args:
        workflow_ir: The workflow IR dictionary containing input declarations
        provided_params: Parameters provided for workflow execution (NOT modified)
        settings_env: Environment variables from settings.env (optional)

    Returns:
        tuple: (errors, defaults_to_apply, env_param_names) where:
            - errors: List of (message, path, suggestion) tuples for ValidationError
            - defaults_to_apply: Dict of default values to apply for missing optional inputs
            - env_param_names: Set of parameter names that came from settings.env

    Precedence order:
        1. provided_params (CLI arguments) - highest priority
        2. Shell environment variables (os.environ)
        3. settings_env (from settings.json)
        4. workflow input defaults (from IR)
        5. Error if required and not provided

    Note:
        This function was renamed from _validate_inputs to prepare_inputs to better
        reflect its dual purpose of validation and default preparation.
    """
    errors: list[tuple[str, str, str]] = []
    defaults: dict[str, Any] = {}
    env_param_names: set[str] = set()
    settings_env = settings_env or {}

    # Extract input declarations (backward compatible with workflows without inputs)
    inputs = workflow_ir.get("inputs", {})

    # If no inputs declared, nothing to validate
    if not inputs:
        logger.debug("No inputs declared for workflow", extra={"phase": "input_validation"})
        return errors, defaults, env_param_names

    # Check for multiple stdin: true inputs (only one allowed)
    stdin_inputs = [name for name, spec in inputs.items() if spec.get("stdin") is True]
    if len(stdin_inputs) > 1:
        errors.append((
            f'Multiple inputs marked with "stdin": true: {", ".join(stdin_inputs)}',
            "inputs",
            "Only one input can receive piped stdin",
        ))

    logger.debug(
        "Validating workflow inputs", extra={"phase": "input_validation", "declared_inputs": list(inputs.keys())}
    )

    # Validate each declared input
    for input_name, input_spec in inputs.items():
        # Validate the input name (now more permissive than Python identifiers)
        if not is_valid_parameter_name(input_name):
            error_msg = get_parameter_validation_error(input_name, "input")
            errors.append((
                error_msg,
                f"inputs.{input_name}",
                "Avoid shell special characters like $, |, >, <, &, ;",
            ))
            continue

        # Check if input is required
        is_required = input_spec.get("required", True)  # Default to required if not specified

        # Check if input is provided
        if input_name not in provided_params:
            # Check shell environment variables first (transient session values)
            if input_name in os.environ:
                defaults[input_name] = os.environ[input_name]
                logger.debug(
                    f"Using shell environment variable for input '{input_name}'",
                    extra={"phase": "input_validation", "input": input_name},
                )
                continue  # Skip settings.env, workflow default, and error handling

            # Check settings.env (persistent configuration)
            if input_name in settings_env:
                defaults[input_name] = settings_env[input_name]
                env_param_names.add(input_name)  # Track that this came from env
                logger.debug(
                    f"Using value from settings.env for input '{input_name}'",
                    extra={"phase": "input_validation", "input": input_name},
                )
                continue  # Skip workflow default and error handling

            if is_required:
                # Required input is missing
                description = input_spec.get("description", "No description provided")
                errors.append((
                    f"Workflow requires input '{input_name}': {description}",
                    f"inputs.{input_name}",
                    "",  # No suggestion needed - agent knows how to pass parameters
                ))
            else:
                # Optional input is missing, prepare default
                if "default" in input_spec:
                    # Has explicit default (including None/null)
                    default_value = input_spec.get("default")
                    logger.debug(
                        f"Applying default value for optional input '{input_name}'",
                        extra={"phase": "input_validation", "input": input_name, "default": default_value},
                    )
                    defaults[input_name] = default_value
                else:
                    # Optional inputs without explicit default resolve to None.
                    # Rationale: "required: false" means "can be omitted", and omitted
                    # values should still be available in context (as None) so templates
                    # like ${optional_param} can resolve rather than fail validation.
                    # Note: Nested access like ${optional_param.field} will still fail
                    # at runtime since you can't traverse into None - this is intentional.
                    logger.debug(
                        f"Optional input '{input_name}' not provided, using None as default",
                        extra={"phase": "input_validation", "input": input_name},
                    )
                    defaults[input_name] = None
        else:
            # Input is provided
            logger.debug(f"Input '{input_name}' provided", extra={"phase": "input_validation", "input": input_name})

    logger.debug(
        "Input validation complete", extra={"phase": "input_validation", "final_params": list(provided_params.keys())}
    )

    return errors, defaults, env_param_names
