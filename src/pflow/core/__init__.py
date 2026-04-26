"""Core pflow modules for workflow representation and validation.

Import from specific submodules for symbols not listed here:
    from pflow.core.shell_integration import detect_stdin
    from pflow.core.param_coercion import coerce_param_for_node
    from pflow.core.llm_client import complete, AdapterResponse
"""

from .exceptions import SchemaValidationError
from .ir_schema import FLOW_IR_SCHEMA, normalize_ir, validate_ir
from .shell_integration import StdinData

__all__ = [
    "FLOW_IR_SCHEMA",
    "SchemaValidationError",
    "StdinData",
    "normalize_ir",
    "validate_ir",
]
