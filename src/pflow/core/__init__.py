"""Core pflow modules for workflow representation and validation."""

from .ir_schema import FLOW_IR_SCHEMA, ValidationError, validate_ir
from .shell_integration import (
    detect_stdin,
    determine_stdin_mode,
    populate_shared_store,
    read_stdin,
)

__all__ = [
    "FLOW_IR_SCHEMA",
    "ValidationError",
    "detect_stdin",
    "determine_stdin_mode",
    "populate_shared_store",
    "read_stdin",
    "validate_ir",
]
