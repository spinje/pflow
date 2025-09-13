"""Core pflow modules for workflow representation and validation."""

from .exceptions import (
    CircularWorkflowReferenceError,
    PflowError,
    WorkflowExecutionError,
)
from .ir_schema import FLOW_IR_SCHEMA, ValidationError, validate_ir
from .shell_integration import (
    StdinData,
    detect_binary_content,
    detect_stdin,
    determine_stdin_mode,
    populate_shared_store,
    read_stdin,
    read_stdin_enhanced,
    read_stdin_with_limit,
    stdin_has_data,
)
from .workflow_data_flow import CycleError, build_execution_order, validate_data_flow
from .workflow_validator import WorkflowValidator

__all__ = [
    "FLOW_IR_SCHEMA",
    "CircularWorkflowReferenceError",
    "CycleError",
    "PflowError",
    "StdinData",
    "ValidationError",
    "WorkflowExecutionError",
    "WorkflowValidator",
    "build_execution_order",
    "detect_binary_content",
    "detect_stdin",
    "determine_stdin_mode",
    "populate_shared_store",
    "read_stdin",
    "read_stdin_enhanced",
    "read_stdin_with_limit",
    "stdin_has_data",
    "validate_data_flow",
    "validate_ir",
]
