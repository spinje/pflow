"""Reusable workflow execution service extracted from CLI."""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from pflow.core.workflow_manager import WorkflowManager

from .output_interface import OutputInterface

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of workflow execution."""

    success: bool
    shared_after: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    action_result: Optional[str] = None
    node_count: int = 0
    duration: float = 0.0
    output_data: Optional[str] = None
    metrics_summary: Optional[dict[str, Any]] = None
    repaired_workflow_ir: Optional[dict] = None  # Repaired workflow IR if repair occurred


class WorkflowExecutorService:
    """Reusable workflow execution service.

    Extracted from CLI to enable use by repair service and future interfaces.
    This service encapsulates all the execution logic that was previously
    embedded in the CLI, making it reusable and testable.
    """

    def __init__(
        self,
        output_interface: Optional[OutputInterface] = None,
        workflow_manager: Optional[WorkflowManager] = None,
    ):
        """Initialize executor service.

        Args:
            output_interface: For progress display (optional)
            workflow_manager: For metadata updates (optional)
        """
        self.output = output_interface
        self.workflow_manager = workflow_manager

    def execute_workflow(
        self,
        workflow_ir: dict[str, Any],
        execution_params: dict[str, Any],
        shared_store: Optional[dict[str, Any]] = None,
        workflow_name: Optional[str] = None,
        stdin_data: Optional[Any] = None,
        output_key: Optional[str] = None,
        metrics_collector: Optional[Any] = None,
        trace_collector: Optional[Any] = None,
        validate: bool = True,
    ) -> ExecutionResult:
        """Execute a workflow and return structured result.

        This method encapsulates all the execution logic currently in CLI:
        - Registry creation and validation
        - Workflow compilation
        - Shared store preparation
        - Execution with error handling
        - Result extraction
        - Metadata updates

        Args:
            workflow_ir: The workflow IR to execute
            execution_params: Parameters for template resolution
            shared_store: Optional pre-existing shared store
            workflow_name: Optional name for metadata updates
            stdin_data: Optional stdin data to inject
            output_key: Optional key to extract from shared store
            metrics_collector: Optional metrics collector
            trace_collector: Optional trace collector

        Returns:
            ExecutionResult with success status and execution details
        """
        from pflow.registry import Registry
        from pflow.runtime.compiler import compile_ir_to_flow

        start_time = time.time()

        # Initialize shared store and registry
        shared_store = self._initialize_shared_store(shared_store, execution_params, stdin_data, metrics_collector)
        registry = Registry()

        try:
            # Compile and execute workflow
            flow = compile_ir_to_flow(
                ir_json=workflow_ir,
                registry=registry,
                initial_params=execution_params,
                validate=validate,
                metrics_collector=metrics_collector,
                trace_collector=trace_collector,
            )
            action_result = flow.run(shared_store)

            # Process execution results
            success = self._is_execution_successful(action_result)
            output_data = self._extract_output_data(shared_store, workflow_ir, output_key, success)
            errors = self._build_error_list(success, action_result, shared_store)

            # Update metadata if successful
            self._update_workflow_metadata(success, workflow_name, execution_params)

        except Exception as e:
            result = self._handle_execution_exception(e)
            success = result["success"]
            errors = result["errors"]
            action_result = result["action_result"]
            output_data = result["output_data"]

        finally:
            if metrics_collector:
                metrics_collector.record_workflow_end()

        duration = time.time() - start_time

        return self._build_execution_result(
            success=success,
            shared_store=shared_store,
            errors=errors,
            action_result=action_result,
            workflow_ir=workflow_ir,
            duration=duration,
            output_data=output_data,
            metrics_collector=metrics_collector,
        )

    def _initialize_shared_store(
        self,
        shared_store: Optional[dict[str, Any]],
        execution_params: dict[str, Any],
        stdin_data: Optional[Any],
        metrics_collector: Optional[Any],
    ) -> dict[str, Any]:
        """Initialize and prepare the shared store.

        Args:
            shared_store: Optional pre-existing shared store
            execution_params: Parameters for template resolution
            stdin_data: Optional stdin data to inject
            metrics_collector: Optional metrics collector

        Returns:
            Initialized shared store
        """
        from pflow.core.shell_integration import populate_shared_store

        if shared_store is None:
            shared_store = {}

        # Add execution parameters
        if execution_params:
            shared_store.update(execution_params)

        # Add stdin data
        if stdin_data:
            populate_shared_store(shared_store, stdin_data)

        # Initialize metrics tracking
        if metrics_collector:
            shared_store["__llm_calls__"] = []
            metrics_collector.record_workflow_start()

        # Add progress callback
        if self.output and self.output.create_node_callback():
            shared_store["__progress_callback__"] = self.output.create_node_callback()

        return shared_store

    def _is_execution_successful(self, action_result: Optional[str]) -> bool:
        """Determine if execution was successful based on action result.

        Args:
            action_result: The action result from flow execution

        Returns:
            True if successful, False otherwise
        """
        return not (action_result and isinstance(action_result, str) and action_result.startswith("error"))

    def _extract_output_data(
        self,
        shared_store: dict[str, Any],
        workflow_ir: dict[str, Any],
        output_key: Optional[str],
        success: bool,
    ) -> Optional[str]:
        """Extract output data from shared store.

        Args:
            shared_store: The shared store after execution
            workflow_ir: The workflow IR specification
            output_key: Optional specific key to extract
            success: Whether execution was successful

        Returns:
            The extracted output as a string, or None
        """
        if output_key and output_key in shared_store:
            return str(shared_store[output_key])
        elif success:
            return self._extract_default_output(shared_store, workflow_ir)
        return None

    def _build_error_list(
        self, success: bool, action_result: Optional[str], shared_store: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Build error list if execution failed.

        Args:
            success: Whether execution was successful
            action_result: The action result from flow execution
            shared_store: The shared store containing error details

        Returns:
            List of error dictionaries
        """
        if success:
            return []

        # Extract error information
        error_info = self._extract_error_info(action_result, shared_store)

        # Determine error category
        category = self._determine_error_category(error_info["message"] or "")

        return [
            {
                "source": "runtime",
                "category": category,
                "message": error_info["message"],
                "action": action_result,
                "node_id": error_info["failed_node"],
                "fixable": True,  # Assume fixable for repair
            }
        ]

    def _extract_error_info(
        self, action_result: Optional[str], shared_store: dict[str, Any]
    ) -> dict[str, Optional[str]]:
        """Extract error message and failed node from shared store.

        Args:
            action_result: The action result from flow execution
            shared_store: The shared store containing error details

        Returns:
            Dictionary with 'message' and 'failed_node' keys
        """
        error_message = f"Workflow failed with action: {action_result}"
        failed_node = self._get_failed_node_from_execution(shared_store)

        # Try multiple sources for error message
        root_error = self._extract_root_level_error(shared_store)
        if root_error:
            error_message = root_error["message"]
            if not failed_node:
                failed_node = root_error.get("node")
        else:
            # Try node-level error
            node_error = self._extract_node_level_error(failed_node, shared_store)
            if node_error:
                error_message = node_error

        return {"message": error_message, "failed_node": failed_node}

    def _get_failed_node_from_execution(self, shared_store: dict[str, Any]) -> Optional[str]:
        """Get failed node from execution checkpoint.

        Args:
            shared_store: The shared store

        Returns:
            Failed node ID or None
        """
        if "__execution__" in shared_store:
            execution_data = shared_store.get("__execution__", {})
            failed_node = execution_data.get("failed_node")
            return failed_node if isinstance(failed_node, str) else None
        return None

    def _extract_root_level_error(self, shared_store: dict[str, Any]) -> Optional[dict[str, str]]:
        """Extract error from root level of shared store.

        Args:
            shared_store: The shared store

        Returns:
            Dictionary with error details or None
        """
        if "error" not in shared_store:
            return None

        result = {"message": str(shared_store["error"])}

        # Try to extract node from error_details
        if "error_details" in shared_store:
            error_details = shared_store.get("error_details", {})
            if isinstance(error_details, dict) and "server" in error_details and "tool" in error_details:
                result["node"] = f"{error_details['server']}_{error_details['tool']}"

        return result

    def _extract_node_level_error(self, failed_node: Optional[str], shared_store: dict[str, Any]) -> Optional[str]:
        """Extract error from failed node's output.

        Args:
            failed_node: The failed node ID
            shared_store: The shared store

        Returns:
            Error message or None
        """
        if not failed_node or failed_node not in shared_store:
            return None

        node_output = shared_store.get(failed_node, {})
        if not isinstance(node_output, dict):
            return None

        # Check direct error field
        if "error" in node_output:
            return str(node_output["error"])

        # Check MCP result format
        if "result" in node_output:
            return self._extract_error_from_mcp_result(node_output["result"])

        return None

    def _extract_error_from_mcp_result(self, result: Any) -> Optional[str]:
        """Extract error from MCP result format.

        Args:
            result: The MCP result field

        Returns:
            Error message or None
        """
        if not isinstance(result, str):
            return None

        import json

        try:
            result_data = json.loads(result)
            if isinstance(result_data, dict) and "error" in result_data:
                error = result_data["error"]
                return error if isinstance(error, str) else str(error)
        except (json.JSONDecodeError, TypeError):
            pass

        return None

    def _determine_error_category(self, error_message: str) -> str:
        """Determine error category based on message content.

        Args:
            error_message: The error message

        Returns:
            Error category string
        """
        error_lower = error_message.lower()

        # Check for API validation errors
        api_patterns = [
            "input should be",
            "field required",
            "invalid request data",
            "following fields are missing",
            "validation error",
            "parameter `",
        ]

        if any(pattern in error_lower for pattern in api_patterns):
            return "api_validation"

        # Check for template errors
        if "${" in error_message or "template" in error_lower:
            return "template_error"

        return "execution_failure"

    def _update_workflow_metadata(
        self,
        success: bool,
        workflow_name: Optional[str],
        execution_params: dict[str, Any],
    ) -> None:
        """Update workflow metadata if successful.

        Args:
            success: Whether execution was successful
            workflow_name: Optional workflow name
            execution_params: Execution parameters
        """
        if success and self.workflow_manager and workflow_name:
            self.workflow_manager.update_metadata(
                workflow_name,
                {
                    "last_execution_timestamp": datetime.now().isoformat(),
                    "last_execution_success": True,
                    "last_execution_params": execution_params,
                    "execution_count": 1,  # Will be incremented by manager
                },
            )

    def _handle_execution_exception(self, exception: Exception) -> dict[str, Any]:
        """Handle exceptions during workflow execution.

        Args:
            exception: The exception that occurred

        Returns:
            Dictionary with execution result details
        """
        from pflow.runtime.compiler import CompilationError

        # Re-raise certain exceptions
        if isinstance(exception, (CompilationError, RuntimeError)):
            raise

        logger.exception("Workflow execution failed with exception")

        return {
            "success": False,
            "errors": [
                {
                    "source": "runtime",
                    "category": "exception",
                    "message": str(exception),
                    "exception_type": type(exception).__name__,
                    "fixable": self._is_fixable_error(exception),
                }
            ],
            "action_result": "error",
            "output_data": None,
        }

    def _build_execution_result(
        self,
        success: bool,
        shared_store: dict[str, Any],
        errors: list[dict[str, Any]],
        action_result: Optional[str],
        workflow_ir: dict[str, Any],
        duration: float,
        output_data: Optional[str],
        metrics_collector: Optional[Any],
    ) -> ExecutionResult:
        """Build the final execution result.

        Args:
            success: Whether execution was successful
            shared_store: The shared store after execution
            errors: List of errors if any
            action_result: The action result from flow execution
            workflow_ir: The workflow IR specification
            duration: Execution duration
            output_data: Extracted output data
            metrics_collector: Optional metrics collector

        Returns:
            ExecutionResult instance
        """
        metrics_summary = None
        if metrics_collector:
            llm_calls = shared_store.get("__llm_calls__", [])
            metrics_summary = metrics_collector.get_summary(llm_calls)

        return ExecutionResult(
            success=success,
            shared_after=shared_store,
            errors=errors,
            action_result=action_result,
            node_count=len(workflow_ir.get("nodes", [])),
            duration=duration,
            output_data=output_data,
            metrics_summary=metrics_summary,
        )

    def _extract_default_output(self, shared: dict[str, Any], workflow_ir: dict[str, Any]) -> Optional[str]:
        """Extract output using workflow declarations or common patterns.

        This method tries multiple strategies to find output:
        1. Check declared outputs in workflow IR
        2. Look for common output keys (result, output, response, data)
        3. Check the last node's output

        Args:
            shared: The shared store after execution
            workflow_ir: The workflow IR specification

        Returns:
            The extracted output as a string, or None if not found
        """
        # Try declared outputs
        output = self._extract_declared_outputs(shared, workflow_ir)
        if output is not None:
            return output

        # Try common output patterns
        output = self._extract_common_outputs(shared)
        if output is not None:
            return output

        # Try last node's output
        return self._extract_last_node_output(shared, workflow_ir)

    def _extract_declared_outputs(self, shared: dict[str, Any], workflow_ir: dict[str, Any]) -> Optional[str]:
        """Extract output from declared workflow outputs.

        Args:
            shared: The shared store after execution
            workflow_ir: The workflow IR specification

        Returns:
            The extracted output as a string, or None if not found
        """
        if "outputs" not in workflow_ir:
            return None

        for output_name in workflow_ir["outputs"]:
            if output_name in shared:
                return str(shared[output_name])

        return None

    def _extract_common_outputs(self, shared: dict[str, Any]) -> Optional[str]:
        """Extract output from common output keys.

        Args:
            shared: The shared store after execution

        Returns:
            The extracted output as a string, or None if not found
        """
        common_keys = ["result", "output", "response", "data"]
        for key in common_keys:
            if key in shared:
                return str(shared[key])
        return None

    def _extract_last_node_output(self, shared: dict[str, Any], workflow_ir: dict[str, Any]) -> Optional[str]:
        """Extract output from the last node's namespace.

        Args:
            shared: The shared store after execution
            workflow_ir: The workflow IR specification

        Returns:
            The extracted output as a string, or None if not found
        """
        nodes = workflow_ir.get("nodes", [])
        if not nodes:
            return None

        last_node_id = nodes[-1].get("id")
        if not last_node_id or last_node_id not in shared:
            return None

        node_output = shared[last_node_id]
        if not isinstance(node_output, dict):
            return None

        output_keys = ["result", "output", "response"]
        for key in output_keys:
            if key in node_output:
                return str(node_output[key])

        return None

    def _is_fixable_error(self, exception: Exception) -> bool:
        """Determine if an error can be fixed by repair.

        This method categorizes errors into fixable and non-fixable based
        on the error message content. Infrastructure and auth issues are
        generally not fixable, while template and field errors often are.

        Args:
            exception: The exception to analyze

        Returns:
            True if the error is potentially fixable, False otherwise
        """
        error_msg = str(exception).lower()

        # Non-fixable infrastructure/auth issues
        non_fixable_keywords = [
            "api key",
            "authentication",
            "unauthorized",
            "forbidden",
            "rate limit",
            "quota",
            "connection refused",
            "timeout",
            "permission denied",
            "out of memory",
        ]

        for keyword in non_fixable_keywords:
            if keyword in error_msg:
                return False

        # Template and field errors are usually fixable
        fixable_keywords = [
            "template",
            "field",
            "not found",
            "missing",
            "undefined",
            "key error",
            "attribute",
            "type error",
            "value error",
        ]

        for keyword in fixable_keywords:
            if keyword in error_msg:
                return True

        # Default to optimistically fixable
        return True
