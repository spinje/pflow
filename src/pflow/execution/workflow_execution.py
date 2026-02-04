"""Unified workflow execution with automatic repair capability."""

import copy
import logging
from typing import Any, Optional

from .display_manager import DisplayManager
from .executor_service import ExecutionResult, WorkflowExecutorService
from .null_output import NullOutput
from .output_interface import OutputInterface
from .repair_service import repair_workflow_with_validation
from .workflow_diff import compute_workflow_diff

logger = logging.getLogger(__name__)


def _normalize_error_message(msg: str) -> str:
    """Remove dynamic parts from error messages for comparison.

    Args:
        msg: Error message to normalize

    Returns:
        Normalized message with timestamps, IDs removed
    """
    import re

    # Remove timestamps (10:45:23, 2024-01-29, etc.)
    msg = re.sub(r"\b\d{1,2}:\d{2}(:\d{2})?\b", "TIME", msg)
    msg = re.sub(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", "DATE", msg)

    # Remove UUIDs and hex IDs
    msg = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "UUID", msg, flags=re.I)
    msg = re.sub(r"\b[0-9a-f]{8,}\b", "HEX_ID", msg, flags=re.I)

    # Remove request IDs and long numbers
    msg = re.sub(r"request[-_]?\d+", "request_ID", msg, flags=re.I)
    msg = re.sub(r"\b\d{6,}\b", "NUM_ID", msg)

    # Remove file line numbers
    msg = re.sub(r"line \d+", "line N", msg)
    msg = re.sub(r":\d+:\d+", ":N:N", msg)

    # Normalize case and whitespace
    msg = msg.lower().strip()
    msg = " ".join(msg.split())  # Collapse multiple spaces

    return msg


def _get_error_signature(errors: list) -> str:
    """Create signature including node ID and normalized error.

    Args:
        errors: List of error dictionaries

    Returns:
        Stable signature string for comparison
    """
    if not errors:
        return "no_errors"

    signatures = []

    # Sort errors by node_id for consistent ordering
    sorted_errors = sorted(errors, key=lambda e: (e.get("node_id", ""), e.get("category", ""), e.get("message", "")))

    # Include up to 5 errors for good coverage
    for e in sorted_errors[:5]:
        node_id = e.get("node_id") or e.get("failed_node") or "unknown"
        message = _normalize_error_message(e.get("message", ""))
        category = e.get("category", "unknown")

        # Include category for more context
        sig = f"{node_id}|{category}|{message[:40]}"
        signatures.append(sig)

    return "||".join(signatures)


def _handle_validation_phase(
    workflow_ir: dict,
    execution_params: dict,
    original_request: Optional[str],
    output: OutputInterface,
    display: DisplayManager,
    resume_state: Optional[dict],
    trace_collector: Optional[Any] = None,
    repair_model: str = "anthropic/claude-sonnet-4-5",
) -> tuple[bool, dict, Optional[dict]]:
    """Handle the validation phase with repair if needed.

    Args:
        workflow_ir: The workflow to validate
        execution_params: Parameters for validation
        original_request: Original request for repair context
        output: Output interface
        display: Display manager for UI
        resume_state: Resume state for shared store updates
        trace_collector: Optional trace collector
        repair_model: LLM model to use for repairs

    Returns:
        Tuple of (was_repaired, workflow_ir, original_workflow_ir)
    """
    from pflow.core.workflow_validator import WorkflowValidator
    from pflow.registry import Registry

    registry = Registry()
    validation_errors, validation_warnings = WorkflowValidator.validate(
        workflow_ir, extracted_params=execution_params or {}, registry=registry, skip_node_types=False
    )

    if not validation_errors:
        return False, workflow_ir, None

    if output.is_interactive():
        display.show_progress("🔍 Validation errors detected, attempting repair...")

    # Validation failed, attempt repair
    success, repaired_ir, remaining_errors = repair_workflow_with_validation(
        workflow_ir=workflow_ir,
        errors=validation_errors,  # Pass validation errors (list of strings)
        original_request=original_request,
        shared_store=None,  # No execution state yet
        execution_params=execution_params,
        max_attempts=3,
        trace_collector=trace_collector,
        repair_model=repair_model,
    )

    if not success or not repaired_ir:
        # Could not repair validation errors
        logger.error("Failed to repair validation errors")
        if remaining_errors:
            for error in remaining_errors[:3]:
                logger.error(f"Validation error: {error.get('message', 'Unknown')}")
        # Return empty dict for workflow_ir to signal validation failure
        return False, {}, None

    # Store original for diff
    original_workflow_ir = copy.deepcopy(workflow_ir) if output.is_interactive() else None

    if output.is_interactive():
        display.show_progress("✅ Workflow repaired and validated")

        # Store modifications in shared store for display layer to use
        if original_workflow_ir:
            modifications = compute_workflow_diff(original_workflow_ir, repaired_ir)
            if modifications and resume_state is not None:
                # Track all modified nodes for display
                resume_state["__modified_nodes__"] = list(modifications.keys())

    return True, repaired_ir, original_workflow_ir


def _prepare_shared_store(
    resume_state: Optional[dict],
    workflow_was_repaired: bool,
    original_workflow_ir: Optional[dict],
    workflow_ir: dict,
    output: OutputInterface,
    display: DisplayManager,
) -> dict:
    """Prepare the shared store for execution.

    Args:
        resume_state: Existing state if resuming
        workflow_was_repaired: Whether workflow was repaired in validation
        original_workflow_ir: Original workflow before repair
        workflow_ir: Current workflow
        output: Output interface
        display: Display manager

    Returns:
        Prepared shared store dictionary
    """
    if resume_state:
        shared_store = resume_state
        if output.is_interactive():
            display.show_execution_start(len(workflow_ir.get("nodes", [])), context="resume")
    else:
        shared_store = {}
        # If we repaired during validation, mark those nodes as modified
        if workflow_was_repaired and original_workflow_ir:
            modifications = compute_workflow_diff(original_workflow_ir, workflow_ir)
            if modifications:
                shared_store["__modified_nodes__"] = list(modifications.keys())

    return shared_store


def _handle_non_repairable_error(
    result: ExecutionResult,
) -> ExecutionResult:
    """Handle non-repairable errors like API failures.

    Args:
        result: The execution result with errors

    Returns:
        Updated result with warning details included
    """
    logger.info("Non-repairable API error detected, skipping repair attempts")

    # Include warning details in result for visibility
    warnings = result.shared_after.get("__warnings__", {})
    if warnings:
        # Add warnings to errors list for user feedback
        for node_id, warning_msg in warnings.items():
            result.errors.append({
                "source": "api",
                "category": "non_repairable",
                "node_id": node_id,
                "message": warning_msg,
                "fixable": False,
            })

    return result


def _handle_stuck_repair_loop(
    result: ExecutionResult,
) -> ExecutionResult:
    """Handle when repair is stuck in a loop with same error.

    Args:
        result: The execution result with errors

    Returns:
        Updated result with repair attempt context
    """
    primary_error = result.errors[0] if result.errors else {}
    node_id = primary_error.get("node_id", "unknown")
    message = primary_error.get("message", "Unknown error")

    logger.info(f"Repair made no progress on {node_id}. Manual intervention needed for: {message[:100]}")

    # Add context to result for better user feedback
    if result.errors and len(result.errors) > 0:
        result.errors[0]["repair_attempted"] = True
        result.errors[0]["repair_reason"] = "Could not automatically fix this issue"

    return result


def _update_shared_store_with_modifications(
    shared_store: dict,
    original_workflow_ir: Optional[dict],
    repaired_ir: dict,
) -> None:
    """Update shared store with workflow modifications.

    Args:
        shared_store: The shared store to update
        original_workflow_ir: Original workflow before repair
        repaired_ir: Repaired workflow
    """
    if original_workflow_ir:
        modifications = compute_workflow_diff(original_workflow_ir, repaired_ir)
        if modifications:
            # Add to the list of modified nodes (append, don't replace)
            if "__modified_nodes__" not in shared_store:
                shared_store["__modified_nodes__"] = []
            for node_id in modifications:
                if node_id not in shared_store["__modified_nodes__"]:
                    shared_store["__modified_nodes__"].append(node_id)


def _attempt_repair(
    current_workflow_ir: dict,
    result: ExecutionResult,
    original_request: Optional[str],
    execution_params: dict,
    output: OutputInterface,
    display: DisplayManager,
    runtime_attempt: int,
    trace_collector: Optional[Any] = None,
    repair_model: str = "anthropic/claude-sonnet-4-5",
) -> tuple[bool, Optional[dict]]:
    """Attempt to repair a failed workflow execution.

    Args:
        current_workflow_ir: Current workflow IR
        result: Failed execution result
        original_request: Original user request
        execution_params: Execution parameters
        output: Output interface
        display: Display manager
        runtime_attempt: Current attempt number
        trace_collector: Optional trace collector
        repair_model: LLM model to use for repairs

    Returns:
        Tuple of (success, repaired_ir)
    """
    # Show repair progress in interactive mode
    if output.is_interactive():
        if runtime_attempt == 1:
            display.show_repair_start()  # Shows "🔧 Auto-repairing workflow..."
        else:
            display.show_progress(f"Runtime repair attempt {runtime_attempt}/3...")

    # Capture repair attempt in trace if available
    if trace_collector and hasattr(trace_collector, "record_repair_attempt"):
        trace_collector.record_repair_attempt(
            attempt_number=runtime_attempt, errors=result.errors, workflow_before=current_workflow_ir
        )

    # Repair with validation
    success, repaired_ir, validation_errors = repair_workflow_with_validation(
        workflow_ir=current_workflow_ir,
        errors=result.errors,  # Runtime errors (list of dicts)
        original_request=original_request,
        shared_store=result.shared_after,  # Pass checkpoint state
        execution_params=execution_params,
        max_attempts=3,
        trace_collector=trace_collector,
        repair_model=repair_model,
    )

    if not success or not repaired_ir:
        logger.warning(f"Runtime repair failed at attempt {runtime_attempt}")
        # Record failed repair attempt in trace
        if trace_collector and hasattr(trace_collector, "record_repair_attempt"):
            trace_collector.record_repair_attempt(
                attempt_number=runtime_attempt,
                errors=result.errors,
                workflow_before=current_workflow_ir,
                workflow_after=None,
                success=False,
                validation_errors=validation_errors,
            )
        return False, None

    # Record successful repair in trace
    if trace_collector and hasattr(trace_collector, "record_repair_attempt"):
        trace_collector.record_repair_attempt(
            attempt_number=runtime_attempt,
            errors=result.errors,
            workflow_before=current_workflow_ir,
            workflow_after=repaired_ir,
            success=True,
        )

    return True, repaired_ir


def _execute_with_repair_loop(
    workflow_ir: dict,
    execution_params: dict,
    shared_store: dict,
    executor: WorkflowExecutorService,
    original_request: Optional[str],
    output: OutputInterface,
    display: DisplayManager,
    workflow_name: Optional[str],
    stdin_data: Optional[Any],
    output_key: Optional[str],
    metrics_collector: Optional[Any],
    trace_collector: Optional[Any],
    workflow_was_repaired: bool,
    repair_model: str = "anthropic/claude-sonnet-4-5",
) -> tuple[ExecutionResult, dict, bool]:
    """Execute workflow with runtime repair loop.

    Args:
        workflow_ir: The workflow to execute
        execution_params: Execution parameters
        shared_store: The shared store
        executor: The workflow executor service
        original_request: Original request for repair
        output: Output interface
        display: Display manager
        workflow_name: Name of workflow
        stdin_data: Input data from stdin
        output_key: Key to extract from result
        metrics_collector: Metrics collector
        trace_collector: Trace collector
        workflow_was_repaired: Whether workflow was already repaired
        repair_model: LLM model to use for repairs

    Returns:
        Tuple of (result, final_workflow_ir, was_repaired)
    """
    max_runtime_attempts = 3
    runtime_attempt = 0
    original_result = None
    last_error_signature = None
    current_workflow_ir = workflow_ir
    was_runtime_repaired = workflow_was_repaired

    while runtime_attempt < max_runtime_attempts:
        # Execute workflow (no validation since we already validated)
        result = executor.execute_workflow(
            workflow_ir=current_workflow_ir,
            execution_params=execution_params,
            shared_store=shared_store,
            workflow_name=workflow_name,
            stdin_data=stdin_data,
            output_key=output_key,
            metrics_collector=metrics_collector,
            trace_collector=trace_collector,
            validate=False,  # Already validated above
        )

        # Store first failure for fallback
        if runtime_attempt == 0 and not result.success:
            original_result = result

        if result.success:
            return result, current_workflow_ir, was_runtime_repaired

        # Runtime execution failed
        runtime_attempt += 1

        # Check for non-repairable errors
        if result.shared_after.get("__non_repairable_error__"):
            return _handle_non_repairable_error(result), current_workflow_ir, was_runtime_repaired

        # Check if we're stuck in a loop with same error
        current_error_signature = _get_error_signature(result.errors)
        if current_error_signature == last_error_signature:
            return _handle_stuck_repair_loop(result), current_workflow_ir, was_runtime_repaired

        last_error_signature = current_error_signature

        if runtime_attempt >= max_runtime_attempts:
            # Max attempts reached
            logger.warning(f"Runtime repair failed after {max_runtime_attempts} attempts")
            break

        # Attempt runtime repair
        success, repaired_ir = _attempt_repair(
            current_workflow_ir=current_workflow_ir,
            result=result,
            original_request=original_request,
            execution_params=execution_params,
            output=output,
            display=display,
            runtime_attempt=runtime_attempt,
            trace_collector=trace_collector,
            repair_model=repair_model,
        )

        if not success:
            break

        # Success guarantees repaired_ir is not None (see _attempt_repair logic)
        if repaired_ir is None:
            # This shouldn't happen based on _attempt_repair logic, but handle it gracefully
            logger.error("Unexpected: repaired_ir is None when success is True")
            break

        # Update for next iteration
        original_workflow_ir = copy.deepcopy(current_workflow_ir) if output.is_interactive() else None
        current_workflow_ir = repaired_ir
        was_runtime_repaired = True  # Mark that runtime repair occurred
        shared_store = result.shared_after  # CRITICAL: Preserve checkpoint for resume!

        if output.is_interactive():
            # Store modifications in shared store for display
            _update_shared_store_with_modifications(shared_store, original_workflow_ir, repaired_ir)
            display.show_progress("Executing repaired workflow...")

    # Return the last result we have
    return original_result or result, current_workflow_ir, was_runtime_repaired


def execute_workflow(
    workflow_ir: dict,
    execution_params: dict,
    enable_repair: bool = True,
    resume_state: Optional[dict] = None,
    original_request: Optional[str] = None,
    output: Optional[OutputInterface] = None,
    workflow_manager: Optional[Any] = None,
    workflow_name: Optional[str] = None,
    stdin_data: Optional[Any] = None,
    output_key: Optional[str] = None,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
    repair_model: Optional[str] = None,
) -> ExecutionResult:
    """
    Unified workflow execution function with automatic repair capability.

    When repair is ENABLED (default):
    1. Validate workflow first, repair if needed (validation loop)
    2. Execute workflow, repair if fails (runtime loop)
    3. Resume from checkpoint on runtime repairs

    When repair is DISABLED (--no-repair):
    1. Validate workflow (fail fast on errors, no repair attempted)
    2. Execute directly
    3. Fail fast on any runtime error

    Args:
        workflow_ir: The workflow IR to execute
        execution_params: Parameters for template resolution
        enable_repair: Whether to attempt repair on failure (default: True)
        resume_state: Shared store from previous execution for resume
        original_request: Original user request for repair context
        output: Output interface for display
        workflow_manager: For metadata updates
        workflow_name: Name of workflow being executed
        stdin_data: Data from stdin
        output_key: Key to extract from shared store
        metrics_collector: For metrics tracking
        trace_collector: For execution tracing
        repair_model: LLM model to use for repairs (default: auto-detect)

    Returns:
        ExecutionResult with success status and execution details
    """
    # Default output if not provided
    if output is None:
        output = NullOutput()

    # Default repair model if not provided
    if repair_model is None:
        repair_model = "anthropic/claude-sonnet-4-5"

    # Create display manager for UI messages
    display = DisplayManager(output=output)

    # Create executor service
    executor = WorkflowExecutorService(output_interface=output, workflow_manager=workflow_manager)

    if enable_repair:
        # =================================================================
        # REPAIR ENABLED: Validate first, then execute with repair support
        # =================================================================

        # Phase 1: Static Validation with Repair Loop
        was_repaired, validated_ir, original_ir = _handle_validation_phase(
            workflow_ir=workflow_ir,
            execution_params=execution_params,
            original_request=original_request,
            output=output,
            display=display,
            resume_state=resume_state,
            trace_collector=trace_collector,
            repair_model=repair_model,
        )

        # Check if validation failed completely
        if not validated_ir:
            # Return failure result with validation errors
            from pflow.core.workflow_validator import WorkflowValidator
            from pflow.registry import Registry

            registry = Registry()
            validation_errors, validation_warnings = WorkflowValidator.validate(
                workflow_ir, extracted_params=execution_params or {}, registry=registry, skip_node_types=False
            )

            return ExecutionResult(
                success=False,
                errors=[{"source": "validation", "message": err} for err in validation_errors[:3]],
                shared_after={},
                action_result="validation_failed",
            )

        workflow_ir = validated_ir

        # Phase 2: Prepare shared store for execution
        shared_store = _prepare_shared_store(
            resume_state=resume_state,
            workflow_was_repaired=was_repaired,
            original_workflow_ir=original_ir,
            workflow_ir=workflow_ir,
            output=output,
            display=display,
        )

        # Phase 3: Execute with runtime repair loop
        result, final_workflow_ir, workflow_was_repaired = _execute_with_repair_loop(
            workflow_ir=workflow_ir,
            execution_params=execution_params,
            shared_store=shared_store,
            executor=executor,
            original_request=original_request,
            output=output,
            display=display,
            workflow_name=workflow_name,
            stdin_data=stdin_data,
            output_key=output_key,
            metrics_collector=metrics_collector,
            trace_collector=trace_collector,
            workflow_was_repaired=was_repaired,
            repair_model=repair_model,
        )

        # Add repaired workflow to result if repair occurred
        if workflow_was_repaired and result.success:
            result.repaired_workflow_ir = final_workflow_ir
            logger.info("Workflow was successfully repaired and will be saved")

        return result

    else:
        # =================================================================
        # REPAIR DISABLED: Validate first, fail fast on errors, no repair
        # =================================================================
        from pflow.core.workflow_validator import WorkflowValidator
        from pflow.registry import Registry

        registry = Registry()
        validation_errors, _warnings = WorkflowValidator.validate(
            workflow_ir, extracted_params=execution_params or {}, registry=registry, skip_node_types=False
        )

        if validation_errors:
            from pflow.core.workflow_status import WorkflowStatus

            return ExecutionResult(
                success=False,
                status=WorkflowStatus.FAILED,
                errors=[{"source": "validation", "message": err} for err in validation_errors[:3]],
                shared_after={},
                action_result="validation_failed",
            )

        # Prepare shared store (with checkpoint if resuming)
        shared_store = resume_state if resume_state else {}

        # Execute with template validation enabled
        result = executor.execute_workflow(
            workflow_ir=workflow_ir,
            execution_params=execution_params,
            shared_store=shared_store,
            workflow_name=workflow_name,
            stdin_data=stdin_data,
            output_key=output_key,
            metrics_collector=metrics_collector,
            trace_collector=trace_collector,
            validate=True,
        )

        return result
