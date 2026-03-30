"""Compilation package — transforms workflow IR into executable PocketFlow Flow objects."""

from .compiler import CompilationError, compile_ir_to_flow, compile_workflow, inject_special_parameters
from .ir_preparation import prepare_inputs, validate_ir_structure
from .node_loader import import_node_class

__all__ = [
    "CompilationError",
    "compile_ir_to_flow",
    "compile_workflow",
    "import_node_class",
    "inject_special_parameters",
    "prepare_inputs",
    "validate_ir_structure",
]
