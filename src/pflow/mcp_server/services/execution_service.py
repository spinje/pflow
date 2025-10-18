"""Execution service for MCP server.

This service handles workflow execution, validation, saving,
and node testing operations.
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pflow.core.ir_schema import normalize_ir
from pflow.core.metrics import MetricsCollector
from pflow.core.workflow_manager import WorkflowManager
from pflow.core.workflow_validator import WorkflowValidator
from pflow.execution.null_output import NullOutput
from pflow.execution.workflow_execution import execute_workflow
from pflow.registry import Registry
from pflow.runtime.compiler import import_node_class

from ..utils.resolver import resolve_workflow
from ..utils.validation import (
    generate_dummy_parameters,
    validate_execution_parameters,
)
from .base_service import BaseService, ensure_stateless

logger = logging.getLogger(__name__)


def _resolve_and_validate_workflow(
    workflow: Any, parameters: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    """Resolve workflow to IR and validate parameters.

    Args:
        workflow: Workflow name, path, or IR dict
        parameters: Execution parameters

    Returns:
        Tuple of (workflow_ir, error_response, validated_parameters)
        If error_response is not None, workflow_ir will be None
    """
    # Resolve workflow to IR
    workflow_ir, error, source = resolve_workflow(workflow)
    if error or workflow_ir is None:
        return (
            None,
            {
                "success": False,
                "error": {
                    "type": "not_found",
                    "message": error or "Workflow not found",
                },
            },
            {},
        )

    # Normalize the workflow IR
    normalize_ir(workflow_ir)  # Modifies in-place

    # Validate parameters
    validated_params = parameters or {}
    if parameters:
        is_valid, error = validate_execution_parameters(parameters)
        if not is_valid:
            return (
                None,
                {
                    "success": False,
                    "error": {
                        "type": "validation",
                        "message": f"Invalid parameters: {error}",
                    },
                },
                {},
            )

    return workflow_ir, None, validated_params


def _build_workflow_metadata(
    workflow_ir: dict[str, Any], workflow: Any, source: str, workflow_manager: Any
) -> dict[str, Any] | None:
    """Build workflow metadata from execution context.

    Args:
        workflow_ir: Workflow IR dictionary (not used, kept for API compatibility)
        workflow: Original workflow parameter
        source: Workflow source type (file, library, direct)
        workflow_manager: Workflow manager instance

    Returns:
        Workflow metadata dictionary or None
    """
    # Determine workflow status based on source
    # Note: IR should never contain metadata field (violates schema)
    if source == "library":
        # Workflow loaded from library - mark as reused
        return {"action": "reused", "name": str(workflow)}
    elif source == "file":
        # Workflow loaded from file - mark as unsaved
        return {"action": "unsaved", "name": str(workflow)}
    else:
        # Direct IR dict - unsaved
        return {"action": "unsaved"}


def _format_success_result(
    result: Any,
    workflow_ir: dict[str, Any],
    workflow: Any,
    source: str,
    workflow_manager: Any,
    metrics_collector: Any,
    trace_path: Path,
) -> dict[str, Any]:
    """Format successful execution result.

    Args:
        result: Execution result object
        workflow_ir: Workflow IR dictionary
        workflow: Original workflow parameter
        source: Workflow source type
        workflow_manager: Workflow manager instance
        metrics_collector: Metrics collector instance
        trace_path: Path to trace file

    Returns:
        Formatted success dictionary
    """
    from pflow.execution.formatters.success_formatter import format_execution_success

    workflow_metadata = _build_workflow_metadata(workflow_ir, workflow, source, workflow_manager)

    formatted = format_execution_success(
        shared_storage=result.shared_after,
        workflow_ir=workflow_ir,
        metrics_collector=metrics_collector,
        workflow_metadata=workflow_metadata,
        trace_path=str(trace_path),
    )

    return formatted


def _format_error_result(
    result: Any, workflow_ir: dict[str, Any], metrics_collector: Any, trace_path: Path
) -> dict[str, Any]:
    """Format failed execution result.

    Args:
        result: Execution result object
        workflow_ir: Workflow IR dictionary
        metrics_collector: Metrics collector instance
        trace_path: Path to trace file

    Returns:
        Formatted error dictionary
    """
    from pflow.execution.formatters.error_formatter import format_execution_errors

    formatted = format_execution_errors(
        result,
        shared_storage=result.shared_after,
        ir_data=workflow_ir,
        metrics_collector=metrics_collector,
        sanitize=True,
    )

    # Build error response
    error_details = {
        "type": "execution",
        "message": "Workflow execution failed",
        "checkpoint": formatted["checkpoint"],
    }

    # Add first error details for backward compatibility
    if formatted["errors"]:
        first_error = formatted["errors"][0]
        error_details["message"] = first_error.get("message", "Unknown error")
        error_details["node"] = first_error.get("node_id")
        error_details["category"] = first_error.get("category")

        # Include all other fields from first error
        for key, value in first_error.items():
            if key not in ["message", "node_id", "category"]:
                error_details[key] = value

    return {
        "success": False,
        "error": error_details,
        "errors": formatted["errors"],
        "execution": formatted.get("execution"),
        "metrics": formatted.get("metrics"),
        "trace_path": str(trace_path),
    }


class ExecutionService(BaseService):
    """Service for workflow execution and related operations.

    Handles workflow execution, validation, saving, and node testing
    while maintaining stateless pattern.
    """

    @classmethod
    @ensure_stateless
    def execute_workflow(cls, workflow: Any, parameters: dict[str, Any] | None = None) -> str:
        """Execute a workflow with agent-optimized defaults.

        Built-in behaviors (no flags needed):
        - Text output format (LLMs parse better than JSON)
        - No auto-repair (explicit errors)
        - Trace saved to ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json
        - Auto-normalization of workflow IR

        Args:
            workflow: Workflow name, path, or IR dict
            parameters: Execution parameters

        Returns:
            Formatted text output matching CLI (success or error)

        Raises:
            ValueError: If workflow not found or parameters invalid
            RuntimeError: If execution fails
        """
        # Resolve and validate workflow
        workflow_ir, error_response, validated_params = _resolve_and_validate_workflow(workflow, parameters)
        if error_response or workflow_ir is None:
            # Extract error message and raise
            error_msg = (
                error_response.get("error", {}).get("message", "Unknown error") if error_response else "Unknown error"
            )
            raise ValueError(error_msg)

        # Setup execution environment
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        trace_path = Path.home() / ".pflow" / "debug" / f"workflow-trace-{timestamp}.json"

        try:
            # Get source info for metadata
            _, _, source = resolve_workflow(workflow)

            # Create fresh instances
            workflow_manager = WorkflowManager()
            metrics_collector = MetricsCollector()

            # Execute with agent defaults (mypy now knows workflow_ir is not None)
            # Note: workflow_name derived from source, not IR metadata (which violates schema)
            workflow_name = str(workflow) if source == "library" else None
            result = execute_workflow(
                workflow_ir=workflow_ir,
                execution_params=validated_params,
                enable_repair=False,  # Always False for agents
                output=NullOutput(),  # Silent execution
                workflow_manager=workflow_manager,
                workflow_name=workflow_name,
                metrics_collector=metrics_collector,
            )

            if result.success:
                # Format success as text (LLMs parse this better)
                success_dict = _format_success_result(
                    result, workflow_ir, workflow, source, workflow_manager, metrics_collector, trace_path
                )

                from pflow.execution.formatters.success_formatter import format_success_as_text

                return format_success_as_text(success_dict)
            else:
                # Format error as text and raise
                error_dict = _format_error_result(result, workflow_ir, metrics_collector, trace_path)
                error_msg = error_dict.get("error", {}).get("message", "Workflow execution failed")

                # Build detailed error text
                lines = [f"❌ {error_msg}"]

                # Add error details if available
                if error_dict.get("errors"):
                    lines.append("\nError details:")
                    for err in error_dict["errors"][:3]:  # Show first 3 errors
                        node_id = err.get("node_id", "unknown")
                        msg = err.get("message", "Unknown error")
                        lines.append(f"  • {node_id}: {msg}")

                # Add trace path
                if trace_path.exists():
                    lines.append(f"\nTrace: {trace_path}")

                error_text = "\n".join(lines)
                raise RuntimeError(error_text)

        except RuntimeError:
            # Re-raise our formatted errors
            raise
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}", exc_info=True)
            error_msg = f"❌ Workflow execution failed: {e}"
            if trace_path.exists():
                error_msg += f"\nTrace: {trace_path}"
            raise RuntimeError(error_msg) from e

    @classmethod
    @ensure_stateless
    def validate_workflow(cls, workflow: Any) -> str:
        """Validate workflow structure without execution.

        Args:
            workflow: Workflow name, path, or IR dict

        Returns:
            Formatted text with validation results (same as CLI output)
        """
        # Resolve workflow to IR
        workflow_ir, error, source = resolve_workflow(workflow)
        if error or workflow_ir is None:
            return f"✗ Workflow not found: {error or 'Unknown error'}"

        # Normalize the workflow IR (mypy now knows workflow_ir is not None)
        normalize_ir(workflow_ir)  # Modifies in-place

        # Generate dummy parameters for validation
        inputs = workflow_ir.get("inputs", {})
        dummy_params = generate_dummy_parameters(inputs)

        # Use comprehensive validator (same as CLI)
        try:
            registry = Registry()

            # Run all 4 validation checks:
            # 1. Structural validation (IR schema compliance)
            # 2. Data flow validation (execution order, cycles)
            # 3. Template validation (${variable} resolution)
            # 4. Node type validation (registry verification)
            errors, warnings = WorkflowValidator.validate(
                workflow_ir=workflow_ir,
                extracted_params=dummy_params,
                registry=registry,
                skip_node_types=False,
            )

            # Use shared formatter for validation display
            from pflow.execution.formatters.validation_formatter import (
                format_validation_failure,
                format_validation_success,
            )

            if errors:
                # Return formatted text (auto-generates suggestions)
                return format_validation_failure(errors)
            else:
                # Return simple success message
                return format_validation_success()

        except Exception as e:
            logger.error(f"Validation failed: {e}", exc_info=True)
            return f"✗ Validation error: {e!s}"

    @classmethod
    @ensure_stateless
    def save_workflow(
        cls, workflow: Any, name: str, description: str, force: bool = False, generate_metadata: bool = False
    ) -> str:
        """Save workflow to global library.

        Args:
            workflow: Workflow path or IR dict
            name: Workflow name (lowercase-with-hyphens)
            description: Workflow description
            force: If True, overwrite existing workflow
            generate_metadata: If True, generate rich metadata (keywords, capabilities, use cases) using AI

        Returns:
            Formatted success message (text) matching CLI output

        Raises:
            ValueError: If workflow name is invalid, workflow not found, or validation fails
            FileExistsError: If workflow exists and force=False
        """
        from pflow.core.workflow_save_service import (
            validate_workflow_name,
        )

        # Validate workflow name
        is_valid, error = validate_workflow_name(name)
        if not is_valid:
            raise ValueError(f"Invalid workflow name: {error}")

        # Load and validate workflow IR
        workflow_ir = cls._load_and_validate_workflow_for_save(workflow)

        # Generate rich metadata if requested (same as CLI)
        # Note: name/description passed directly to save function, NOT embedded in IR
        metadata_dict = cls._generate_metadata_if_requested(workflow_ir, generate_metadata)

        # Save workflow and return success message
        return cls._save_and_format_result(name, workflow_ir, description, force, metadata_dict)

    @classmethod
    def _load_and_validate_workflow_for_save(cls, workflow: Any) -> dict[str, Any]:
        """Load and validate workflow IR for saving.

        Args:
            workflow: Workflow path or IR dict

        Returns:
            Validated workflow IR

        Raises:
            ValueError: If workflow not found or validation fails
        """
        from pflow.core.exceptions import WorkflowValidationError
        from pflow.core.workflow_save_service import load_and_validate_workflow

        # Resolve workflow to IR (MCP accepts dict/name/path)
        workflow_ir, error, source = resolve_workflow(workflow)
        if error or workflow_ir is None:
            raise ValueError(error or "Workflow not found")

        # Validate and normalize IR (mypy now knows workflow_ir is not None)
        try:
            workflow_ir = load_and_validate_workflow(workflow_ir, auto_normalize=True)
        except (ValueError, WorkflowValidationError) as e:
            raise ValueError(f"Invalid workflow: {e}") from e

        return workflow_ir

    @classmethod
    def _generate_metadata_if_requested(
        cls, workflow_ir: dict[str, Any], generate_metadata: bool
    ) -> dict[str, Any] | None:
        """Generate rich metadata if requested.

        Args:
            workflow_ir: Workflow IR dictionary
            generate_metadata: Whether to generate metadata

        Returns:
            Generated metadata dict or None
        """
        from pflow.core.workflow_save_service import generate_workflow_metadata

        if not generate_metadata:
            return None

        try:
            return generate_workflow_metadata(workflow_ir)
        except Exception as e:
            logger.warning(f"Failed to generate metadata: {e}")
            return None

    @classmethod
    def _save_and_format_result(
        cls,
        name: str,
        workflow_ir: dict[str, Any],
        description: str,
        force: bool,
        metadata_dict: dict[str, Any] | None,
    ) -> str:
        """Save workflow and format success message.

        Args:
            name: Workflow name
            workflow_ir: Workflow IR dictionary
            description: Workflow description
            force: Whether to overwrite existing workflow
            metadata_dict: Optional rich metadata

        Returns:
            Formatted success message

        Raises:
            FileExistsError: If workflow exists and force=False
            ValueError: If save fails
        """
        from pflow.core.exceptions import WorkflowValidationError
        from pflow.core.workflow_save_service import save_workflow_with_options
        from pflow.execution.formatters.workflow_save_formatter import format_save_success

        try:
            saved_path = save_workflow_with_options(
                name=name,
                workflow_ir=workflow_ir,
                description=description,
                force=force,
                metadata=metadata_dict,
            )

            success_message = format_save_success(
                name=name,
                saved_path=str(saved_path),
                workflow_ir=workflow_ir,
                metadata=metadata_dict,
            )

            return success_message

        except FileExistsError as e:
            raise FileExistsError(
                f"Workflow '{name}' already exists. Use force=true to overwrite or choose a different name."
            ) from e
        except WorkflowValidationError as e:
            logger.error(f"Failed to save workflow: {e}", exc_info=True)
            raise ValueError(f"Failed to save workflow: {e}") from e
        except Exception as e:
            logger.error(f"Failed to save workflow: {e}", exc_info=True)
            raise ValueError(f"Failed to save workflow: {e}") from e

    @classmethod
    @ensure_stateless
    def run_registry_node(cls, node_type: str, parameters: dict[str, Any] | None = None) -> str:
        """Execute a single node to reveal output structure.

        This is critical for MCP nodes where documentation shows "Any"
        but actual output is deeply nested.

        Args:
            node_type: Node type to run
            parameters: Optional parameters for the node

        Returns:
            Formatted string with node output structure or error message
        """
        # Create fresh registry
        registry = Registry()
        nodes = registry.load()

        if node_type not in nodes:
            # Use shared formatter for CLI/MCP parity
            from pflow.execution.formatters.registry_run_formatter import format_node_not_found_error

            return format_node_not_found_error(node_type, list(nodes.keys()))

        # Node exists in registry
        try:
            # Import node class using CLI's proven logic (reuses single source of truth)
            node_class = import_node_class(node_type, registry)

            # Create node instance
            node_instance = node_class()

            # Check if this is an MCP node and inject special parameters
            # MCP nodes require __mcp_server__ and __mcp_tool__ to be set
            # (normally injected by compiler during workflow compilation)
            if node_type.startswith("mcp-"):
                # Import the parser function (same logic as compiler uses)
                from pflow.runtime.compiler import _parse_mcp_node_type

                # Parse node type to extract server and tool names
                # This will raise CompilationError if format is invalid or server not found
                server_name, tool_name = _parse_mcp_node_type(node_type)

                # Inject special parameters (same as compiler does)
                if parameters is None:
                    parameters = {}

                # These special parameters tell MCPNode which server/tool to execute
                parameters["__mcp_server__"] = server_name
                parameters["__mcp_tool__"] = tool_name

                logger.debug(
                    f"Injected MCP metadata for {node_type}",
                    extra={"server": server_name, "tool": tool_name},
                )

            # Resolve ${var} templates from environment and settings.json
            # This allows agents to use ${API_KEY} without exposing actual tokens
            # Checks both os.environ and settings.json (where `pflow settings set-env` stores values)
            if parameters:
                from pflow.mcp.auth_utils import expand_env_vars_nested

                parameters = expand_env_vars_nested(
                    parameters,
                    include_settings=True,
                    raise_on_missing=True,
                )

                logger.debug(
                    f"Resolved environment variables in parameters for {node_type}",
                    extra={"param_keys": list(parameters.keys()) if isinstance(parameters, dict) else None},
                )

            # Set parameters (now includes __mcp_server__ and __mcp_tool__ for MCP nodes,
            # and all ${var} templates resolved from environment)
            if parameters:
                node_instance.set_params(parameters)

            # Run node with test shared store and timing
            shared: dict[str, Any] = {}
            start_time = time.perf_counter()
            action = node_instance.run(shared)
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)

            # Extract outputs (same logic as CLI)
            outputs = shared.get(node_type, {})
            if not outputs:
                # Fallback: collect any non-input keys as outputs
                param_keys = set(parameters.keys()) if parameters else set()
                outputs = {k: v for k, v in shared.items() if k not in param_keys and not k.startswith("__")}

            # Format result using shared formatter (CLI's structure mode)
            from pflow.execution.formatters.node_output_formatter import format_node_output

            result = format_node_output(
                node_type=node_type,
                action=action,
                outputs=outputs,
                shared_store=shared,
                execution_time_ms=execution_time_ms,
                registry=registry,
                format_type="structure",  # CLI's --show-structure mode
                verbose=True,
            )

            # format_node_output with format_type="structure" always returns str
            # Verify type and return (mypy needs this check)
            if not isinstance(result, str):
                raise TypeError(f"Expected str from structure format, got {type(result)}")
            return result

        except Exception as e:
            logger.error(f"Failed to run node {node_type}: {e}", exc_info=True)

            # Use shared formatter for CLI/MCP parity
            from pflow.execution.formatters.registry_run_formatter import format_execution_error

            return format_execution_error(node_type, e, verbose=False)
