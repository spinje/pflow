"""Execution service for MCP server.

This service handles workflow execution, validation, saving,
and node testing operations.
"""

import logging
from pathlib import Path
from typing import Any, Optional

from pflow.core.exceptions import WorkflowNotFoundError
from pflow.core.workflow.manager import WorkflowManager
from pflow.execution.workflow_resolver import resolve_workflow as _unified_resolve
from pflow.registry import Registry

from ..utils.validation import (
    validate_execution_parameters,
)
from .base_service import BaseService, ensure_stateless

logger = logging.getLogger(__name__)


def _format_success_result(
    result: Any,
    resolved: Any,
    workflow_name_display: str | None,
) -> dict[str, Any]:
    """Format successful execution result for MCP text output.

    Args:
        result: ExecutionResult from WorkflowRunner
        resolved: ResolvedWorkflow from resolver
        workflow_name_display: User-facing name (e.g., "my-workflow"), not file path

    Returns:
        Formatted success dictionary
    """
    from pflow.execution.formatters.success_formatter import format_execution_success

    # Build workflow metadata from resolution source
    # Note: "name" must be user-facing (e.g., "my-workflow"), NOT file_path
    # (which is an absolute path like /Users/.../my-workflow.pflow.md).
    # The formatter displays "{name} was executed" in MCP output.
    if resolved.source == "library":
        workflow_metadata: dict[str, Any] | None = {
            "action": "reused",
            "name": workflow_name_display or str(resolved.file_path),
        }
    elif resolved.source == "file":
        workflow_metadata = {
            "action": "unsaved",
            "name": workflow_name_display or str(resolved.file_path),
        }
    else:
        workflow_metadata = {"action": "unsaved"}

    # Derive trace path from trace collector
    trace_path = ""
    if result.trace and hasattr(result.trace, "trace_path"):
        trace_path = str(result.trace.trace_path)

    formatted = format_execution_success(
        shared_storage=result.shared_after,
        workflow_ir=resolved.ir,
        metrics_collector=result.metrics,
        workflow_metadata=workflow_metadata,
        trace_path=trace_path,
        status=result.status,
        warnings=result.warnings + result.validation_warnings,
    )

    return formatted


def _format_error_result(
    result: Any,
    workflow_ir: dict[str, Any],
) -> dict[str, Any]:
    """Format failed execution result for MCP error text.

    Args:
        result: ExecutionResult from WorkflowRunner
        workflow_ir: Workflow IR dictionary

    Returns:
        Formatted error dictionary
    """
    from pflow.execution.formatters.error_formatter import format_execution_errors

    formatted = format_execution_errors(
        result,
        shared_storage=result.shared_after,
        ir_data=workflow_ir,
        metrics_collector=result.metrics,
        sanitize=True,
    )

    # Build error response
    error_details: dict[str, Any] = {
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

        for key, value in first_error.items():
            if key not in ["message", "node_id", "category"]:
                error_details[key] = value

    # Derive trace path
    trace_path = ""
    if result.trace and hasattr(result.trace, "trace_path"):
        trace_path = str(result.trace.trace_path)

    return {
        "success": False,
        "error": error_details,
        "errors": formatted["errors"],
        "execution": formatted.get("execution"),
        "metrics": formatted.get("metrics"),
        "trace_path": trace_path,
    }


def _build_error_text(error_dict: dict[str, Any]) -> str:
    """Build detailed error text from error dict for MCP agent consumption.

    Args:
        error_dict: Formatted error dictionary from _format_error_result

    Returns:
        Human-readable error text with shell details for agent diagnosis
    """
    error_msg = error_dict.get("error", {}).get("message", "Workflow execution failed")
    lines = [f"❌ {error_msg}"]

    if error_dict.get("errors"):
        lines.append("\nError details:")
        for err in error_dict["errors"][:3]:
            node_id = err.get("node_id", "unknown")
            msg = err.get("message", "Unknown error")
            lines.append(f"  • {node_id}: {msg}")
            if err.get("shell_command"):
                cmd = err["shell_command"]
                cmd_display = cmd[:200] + "..." if len(cmd) > 200 else cmd
                lines.append(f"    Command: {cmd_display}")
            if err.get("shell_stderr"):
                stderr = err["shell_stderr"]
                stderr_display = stderr[:300] + "..." if len(stderr) > 300 else stderr
                lines.append(f"    Stderr: {stderr_display}")

    trace_path = error_dict.get("trace_path", "")
    if trace_path and Path(trace_path).exists():
        lines.append(f"\nTrace: {trace_path}")

    return "\n".join(lines)


class ExecutionService(BaseService):
    """Service for workflow execution and related operations.

    Handles workflow execution, validation, saving, and node testing
    while maintaining stateless pattern.
    """

    @classmethod
    @ensure_stateless
    def execute_workflow(cls, workflow: Any, parameters: dict[str, Any] | None = None) -> str:
        """Execute a workflow with agent-optimized defaults.

        Args:
            workflow: Workflow name, path, or IR dict
            parameters: Execution parameters

        Returns:
            Formatted text output matching CLI (success or error)

        Raises:
            ValueError: If workflow not found (with suggestions) or parameters fail security validation
            RuntimeError: All other failures (validation, compilation, execution)
        """
        from pflow.execution.result import RunnerConfig
        from pflow.execution.runner import WorkflowRunner

        # Validate parameters at system boundary (security check stays in MCP)
        validated_params: dict[str, Any] = {}
        if parameters:
            is_valid, error = validate_execution_parameters(parameters)
            if not is_valid:
                raise ValueError(f"Invalid parameters: {error}")
            validated_params = dict(parameters)

        # Pre-resolve to get source/file_path for metadata
        try:
            resolved = _unified_resolve(workflow)
        except WorkflowNotFoundError as e:
            hint = str(e)
            if e.similar_names:
                hint += f"\nDid you mean: {', '.join(e.similar_names[:5])}"
            raise ValueError(hint) from e
        except Exception as e:
            raise ValueError(str(e)) from e

        # Inject file path for sub-workflow relative path resolution
        if resolved.file_path:
            validated_params["_pflow_workflow_file"] = resolved.file_path

        workflow_name = str(workflow) if resolved.source == "library" else None
        wm = WorkflowManager()

        # Execute via Runner — pass resolved.ir (dict) to avoid double-resolution
        runner = WorkflowRunner()
        result = runner.run(
            resolved.ir,
            validated_params,
            RunnerConfig(),
            workflow_manager=wm,
            workflow_name=workflow_name,
        )

        try:
            if result.success:
                success_dict = _format_success_result(result, resolved, str(workflow))
                from pflow.execution.formatters.success_formatter import format_success_as_text

                return format_success_as_text(success_dict)
            else:
                error_dict = _format_error_result(result, resolved.ir)
                raise RuntimeError(_build_error_text(error_dict))
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}", exc_info=True)
            raise RuntimeError(f"❌ Workflow execution failed: {e}") from e

    @classmethod
    @ensure_stateless
    def validate_workflow(cls, workflow: Any) -> str:
        """Validate workflow structure without execution.

        Args:
            workflow: Workflow name, path, or IR dict

        Returns:
            Formatted text with validation results (same as CLI output)
        """
        from pflow.execution.runner import WorkflowRunner

        runner = WorkflowRunner()
        vresult = runner.validate(workflow, {})

        if vresult.valid:
            from pflow.execution.formatters.validation_formatter import format_validation_success

            msg = format_validation_success()
            if vresult.warnings:
                warning_text = "\n".join(
                    f"  ⚠ {w.get('template', '?')}: {w.get('message', '')}" for w in vresult.warnings
                )
                msg += f"\n\nWarnings:\n{warning_text}"
            return msg
        else:
            from pflow.execution.formatters.validation_formatter import format_validation_failure

            return format_validation_failure(vresult.errors)

    @classmethod
    @ensure_stateless
    def save_workflow(cls, workflow: str, name: str, force: bool = False) -> str:
        """Save workflow to global library.

        Accepts raw .pflow.md content or a file path. Does NOT use
        resolve_workflow() — save needs to preserve the original markdown
        content for storage (not just the parsed IR).

        Args:
            workflow: Raw markdown content (string with newlines) or path to .pflow.md file
            name: Workflow name (lowercase-with-hyphens)
            force: If True, overwrite existing workflow

        Returns:
            Formatted success message (text) matching CLI output

        Raises:
            ValueError: If workflow name is invalid, content is invalid, or validation fails
            FileExistsError: If workflow exists and force=False
        """
        from pflow.core.exceptions import WorkflowValidationError
        from pflow.core.markdown_parser import MarkdownParseError, parse_markdown
        from pflow.core.workflow.save_service import (
            load_and_validate_workflow,
            validate_workflow_name,
        )

        # Validate workflow name
        is_valid, error = validate_workflow_name(name)
        if not is_valid:
            raise ValueError(f"Invalid workflow name: {error}")

        # Determine markdown content from input
        if "\n" in workflow:
            # Raw markdown content
            markdown_content = workflow
        elif workflow.lower().endswith(".pflow.md") or Path(workflow).expanduser().exists():
            # File path — read content
            file_path = Path(workflow).expanduser()
            if not file_path.exists():
                raise ValueError(f"Workflow file not found: {workflow}")
            markdown_content = file_path.read_text(encoding="utf-8")
        else:
            raise ValueError(f"Cannot save '{workflow}'. Pass raw .pflow.md content or a file path.")

        # Parse and validate — parse once, use IR for display, content for save
        try:
            result = parse_markdown(markdown_content)
        except MarkdownParseError as e:
            raise ValueError(f"Invalid workflow: {e}") from e

        # Validate the parsed IR
        try:
            load_and_validate_workflow(result.ir, auto_normalize=True)
        except (ValueError, WorkflowValidationError) as e:
            raise ValueError(f"Invalid workflow: {e}") from e

        # Determine source path for dependency discovery (file-based saves only)
        source_path: Optional[Path] = None
        if "\n" not in workflow:
            candidate = Path(workflow).expanduser()
            if candidate.exists():
                source_path = candidate

        # Save and format result
        return cls._save_and_format_result(name, markdown_content, result.ir, force, source_path)

    @classmethod
    def _save_and_format_result(
        cls,
        name: str,
        markdown_content: str,
        workflow_ir: dict[str, Any],
        force: bool,
        source_path: Optional[Path] = None,
    ) -> str:
        """Save workflow and format success message.

        Args:
            name: Workflow name
            markdown_content: Original markdown content (preserved for save)
            workflow_ir: Parsed workflow IR (used for display formatting)
            force: Whether to overwrite existing workflow
            source_path: Optional source file path for dependency discovery

        Returns:
            Formatted success message

        Raises:
            FileExistsError: If workflow exists and force=False
            ValueError: If save fails
        """
        from pflow.core.exceptions import WorkflowValidationError
        from pflow.core.workflow.save_service import save_workflow_with_options
        from pflow.execution.formatters.workflow_save_formatter import format_save_success

        try:
            saved_path, bundled_files = save_workflow_with_options(
                name=name,
                markdown_content=markdown_content,
                force=force,
                source_path=source_path,
            )

            success_message = format_save_success(
                name=name,
                saved_path=str(saved_path),
                workflow_ir=workflow_ir,
                metadata=None,
                bundled_files=bundled_files,
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
    def _cache_execution_result(
        cls,
        execution_id: str,
        node_type: str,
        parameters: dict[str, Any] | None,
        outputs: dict[str, Any],
        action: str | None,
    ) -> None:
        """Cache execution results for structure-only mode (Task 89).

        Args:
            execution_id: Unique execution identifier
            node_type: Node type identifier
            parameters: Parameters used for execution
            outputs: Outputs from execution
            action: Action result from node execution
        """
        # Only cache successful executions
        if action != "error":
            from pflow.core.execution_cache import ExecutionCache

            cache = ExecutionCache()
            try:
                cache.store(execution_id=execution_id, node_type=node_type, params=parameters or {}, outputs=outputs)
            except Exception as cache_error:
                # Log warning but don't fail execution
                logger.warning(f"Failed to cache execution {execution_id}: {cache_error}")

    @classmethod
    @ensure_stateless
    def run_registry_node(cls, node_type: str, parameters: dict[str, Any] | None = None) -> str:
        """Execute a single node via synthetic IR through the Runner.

        Args:
            node_type: Node type to run
            parameters: Optional parameters for the node

        Returns:
            Formatted string with node output structure or error message
        """
        from pflow.execution.result import RunnerConfig
        from pflow.execution.runner import WorkflowRunner

        # Check registry first (before Runner, for fast "not found" response)
        registry = Registry()
        nodes = registry.load()
        if node_type not in nodes:
            from pflow.execution.formatters.registry_run_formatter import format_node_not_found_error

            return format_node_not_found_error(node_type, list(nodes.keys()))

        # Validate parameters at system boundary (MCP concern)
        node_params: dict[str, Any] = {}
        if parameters:
            is_valid, error = validate_execution_parameters(parameters)
            if not is_valid:
                return f"❌ Invalid parameters: {error}"
            node_params = dict(parameters)

        # Generate execution_id for read_fields two-phase pattern
        from pflow.core.execution_cache import ExecutionCache

        cache = ExecutionCache()
        execution_id = cache.generate_execution_id()

        try:
            # Resolve ${ENV_VAR} from os.environ and settings.json
            # (the compiler's template resolver only resolves from shared store)
            if node_params:
                from pflow.mcp.auth_utils import expand_env_vars_nested

                node_params = expand_env_vars_nested(node_params, include_settings=True, raise_on_missing=True)

            # Build synthetic single-node IR
            synthetic_ir: dict[str, Any] = {
                "nodes": [{"id": node_type, "type": node_type, "params": node_params}],
                "edges": [],
            }
            # Execute via Runner with cache disabled (registry run is for discovery)
            # Pass {} as Runner params — all user params are in node.params only.
            # Passing them as Runner params causes WorkflowValidator Step 7
            # to flag all node params as "unknown workflow inputs".
            runner = WorkflowRunner()
            result = runner.run(synthetic_ir, {}, RunnerConfig(cache_enabled=False))

            if result.success:
                # Extract node output from shared store
                outputs = result.shared_after.get(node_type, {})
                if not isinstance(outputs, dict):
                    outputs = {"result": outputs}

                # Cache for read_fields pattern
                cls._cache_execution_result(
                    execution_id=execution_id,
                    node_type=node_type,
                    parameters=parameters,
                    outputs=outputs,
                    action=None,
                )

                # Extract execution time from metrics
                exec_time_ms = 0
                if result.metrics:
                    total_ms, _wf_ms = result.metrics._calculate_durations()
                    exec_time_ms = int(total_ms)

                # Format output
                from pflow.core.settings import SettingsManager
                from pflow.execution.formatters.node_output_formatter import format_node_output

                settings = SettingsManager().load()
                output_mode = settings.registry.output_mode

                formatted = format_node_output(
                    node_type=node_type,
                    action="default",
                    outputs=outputs,
                    shared_store=result.shared_after,
                    execution_time_ms=exec_time_ms,
                    registry=registry,
                    format_type="structure",
                    verbose=True,
                    execution_id=execution_id,
                    output_mode=output_mode,
                )

                if not isinstance(formatted, str):
                    raise TypeError(f"Expected str from structure format, got {type(formatted)}")
                return formatted
            else:
                # Format through _format_error_result (same shape _build_error_text expects)
                formatted_error = _format_error_result(result, synthetic_ir)
                error_text = _build_error_text(formatted_error)
                from pflow.execution.formatters.registry_run_formatter import format_execution_error

                return format_execution_error(node_type, RuntimeError(error_text), verbose=False)

        except Exception as e:
            logger.error(f"Failed to run node {node_type}: {e}", exc_info=True)
            from pflow.execution.formatters.registry_run_formatter import format_execution_error

            return format_execution_error(node_type, e, verbose=False)
