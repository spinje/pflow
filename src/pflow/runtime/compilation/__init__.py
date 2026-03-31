"""Compilation package — transforms workflow IR into CompiledWorkflow objects."""

from .compiler import CompilationError, compile_workflow, inject_special_parameters
from .ir_preparation import prepare_inputs, validate_ir_structure
from .node_loader import import_node_class

__all__ = [
    "CompilationError",
    "compile_workflow",
    "import_node_class",
    "inject_special_parameters",
    "prepare_inputs",
    "validate_ir_structure",
]
