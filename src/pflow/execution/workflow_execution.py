"""Unified workflow execution."""

import logging
from typing import Any, Optional

from .executor_service import ExecutionResult, WorkflowExecutorService
from .null_output import NullOutput
from .output_interface import OutputInterface

logger = logging.getLogger(__name__)


def execute_workflow(
    workflow_ir: dict,
    execution_params: dict,
    output: Optional[OutputInterface] = None,
    workflow_manager: Optional[Any] = None,
    workflow_name: Optional[str] = None,
    stdin_data: Optional[Any] = None,
    output_key: Optional[str] = None,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
) -> ExecutionResult:
    """Execute a workflow with validation.

    1. Validate workflow (fail fast on errors)
    2. Execute directly
    3. Return result

    Args:
        workflow_ir: The workflow IR to execute
        execution_params: Parameters for template resolution
        output: Output interface for display
        workflow_manager: For metadata updates
        workflow_name: Name of workflow being executed
        stdin_data: Data from stdin
        output_key: Key to extract from shared store
        metrics_collector: For metrics tracking
        trace_collector: For execution tracing

    Returns:
        ExecutionResult with success status and execution details
    """
    if output is None:
        output = NullOutput()

    executor = WorkflowExecutorService(output_interface=output, workflow_manager=workflow_manager)

    # Validate
    from pflow.core.workflow.validator import WorkflowValidator
    from pflow.registry import Registry

    registry = Registry()
    validation_errors, _warnings = WorkflowValidator.validate(
        workflow_ir, extracted_params=execution_params or {}, registry=registry, skip_node_types=False
    )

    if validation_errors:
        from pflow.core.workflow.status import WorkflowStatus

        return ExecutionResult(
            success=False,
            status=WorkflowStatus.FAILED,
            errors=[{"source": "validation", "message": err} for err in validation_errors[:3]],
            shared_after={},
            action_result="validation_failed",
        )

    # Execute
    result = executor.execute_workflow(
        workflow_ir=workflow_ir,
        execution_params=execution_params,
        shared_store={},
        workflow_name=workflow_name,
        stdin_data=stdin_data,
        output_key=output_key,
        metrics_collector=metrics_collector,
        trace_collector=trace_collector,
        validate=True,
    )

    return result
