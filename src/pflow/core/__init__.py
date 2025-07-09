"""Core pflow modules for workflow representation and validation."""

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
)

__all__ = [
    "FLOW_IR_SCHEMA",
    "StdinData",
    "ValidationError",
    "detect_binary_content",
    "detect_stdin",
    "determine_stdin_mode",
    "populate_shared_store",
    "read_stdin",
    "read_stdin_enhanced",
    "read_stdin_with_limit",
    "validate_ir",
]
