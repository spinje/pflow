"""Core pflow modules for workflow representation and validation."""

from .exceptions import PflowError
from .ir_schema import BATCH_CONFIG_SCHEMA, FLOW_IR_SCHEMA, ValidationError, normalize_ir, validate_ir
from .llm_pricing import MODEL_PRICING, PRICING_VERSION, calculate_llm_cost, get_model_pricing
from .param_coercion import coerce_to_declared_type
from .shell_integration import (
    StdinData,
    detect_binary_content,
    detect_stdin,
    read_stdin,
    read_stdin_enhanced,
    read_stdin_with_limit,
    stdin_has_data,
)

__all__ = [
    "BATCH_CONFIG_SCHEMA",
    "FLOW_IR_SCHEMA",
    "MODEL_PRICING",
    "PRICING_VERSION",
    "PflowError",
    "StdinData",
    "ValidationError",
    "calculate_llm_cost",
    "coerce_to_declared_type",
    "detect_binary_content",
    "detect_stdin",
    "get_model_pricing",
    "normalize_ir",
    "read_stdin",
    "read_stdin_enhanced",
    "read_stdin_with_limit",
    "stdin_has_data",
    "validate_ir",
]
