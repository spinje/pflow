"""Unified workflow execution."""

from typing import Any, Optional

from .executor_service import ExecutionResult, WorkflowExecutorService
from .null_output import NullOutput
from .output_interface import OutputInterface


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
    """Execute a pre-validated workflow.

    Callers are responsible for running WorkflowValidator.validate()
    before calling this function. The compiler still runs its own
    structural and template validation as defense-in-depth.

    Returns ExecutionResult in all cases — compilation errors are
    wrapped rather than propagated.

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

    try:
        result = executor.execute_workflow(
            workflow_ir=workflow_ir,
            execution_params=execution_params,
            shared_store={},
            workflow_name=workflow_name,
            stdin_data=stdin_data,
            output_key=output_key,
            metrics_collector=metrics_collector,
            trace_collector=trace_collector,
            validate=True,  # Compiler-level template validation (separate from WorkflowValidator)
        )
    except Exception as e:
        # CompilationError, MaxNodeVisitsError, and other exceptions from the
        # compiler/runtime are wrapped in ExecutionResult so callers always get
        # the declared return type.
        from pflow.core.exceptions import MaxNodeVisitsError
        from pflow.core.workflow.status import WorkflowStatus
        from pflow.runtime import CompilationError

        if isinstance(e, CompilationError):
            return ExecutionResult(
                success=False,
                status=WorkflowStatus.FAILED,
                errors=[
                    {
                        "source": "compilation",
                        "category": "compilation",
                        "message": getattr(e, "raw_message", str(e)),
                        "phase": getattr(e, "phase", None),
                        "node_id": getattr(e, "node_id", None),
                        "node_type": getattr(e, "node_type", None),
                        "suggestion": getattr(e, "suggestion", None),
                        "sub_workflow_path": (getattr(e, "details", None) or {}).get("sub_workflow_path"),
                    }
                ],
            )

        if isinstance(e, MaxNodeVisitsError):
            return ExecutionResult(
                success=False,
                status=WorkflowStatus.FAILED,
                errors=[
                    {
                        "source": "runtime",
                        "category": "max_visits",
                        "message": str(e),
                        "node_id": e.node_id,
                        "visit_count": e.visit_count,
                        "max_visits": e.max_visits,
                    }
                ],
            )

        raise

    return result
