"""Dynamic node class importing for the compilation pipeline.

Handles loading node classes from registry metadata, supporting 4 import paths:
core nodes (standard importlib), user nodes (file-based), MCP nodes (virtual),
and workflow nodes (special-cased).
"""

import importlib
import importlib.util
import logging
from typing import cast

from pflow.core.node import BaseNode
from pflow.registry import Registry

logger = logging.getLogger(__name__)


def import_node_class(node_type: str, registry: Registry) -> type[BaseNode]:
    """Import and validate a node class from registry metadata.

    This function dynamically imports a node class based on the metadata
    stored in the registry. It performs validation to ensure the imported
    class properly inherits from BaseNode.

    Args:
        node_type: The node type identifier (e.g., "read-file", "llm")
        registry: Registry instance containing node metadata

    Returns:
        The node class (not instance) ready for instantiation

    Raises:
        CompilationError: With specific error context for various failure modes:
            - node_type not found in registry (phase: "node_resolution")
            - Module import failure (phase: "node_import")
            - Class not found in module (phase: "node_import")
            - Class doesn't inherit from BaseNode (phase: "node_validation")
    """
    from .compiler import CompilationError

    # Special handling for workflow execution
    if node_type == "workflow" or node_type == "pflow.runtime.workflow_executor":
        from pflow.runtime.workflow_executor import WorkflowExecutor

        return WorkflowExecutor

    logger.debug("Looking up node in registry", extra={"phase": "node_resolution", "node_type": node_type})

    # Step 1: Load registry and check if node exists
    nodes = registry.load()
    if node_type not in nodes:
        available_nodes = list(nodes.keys())
        raise CompilationError(
            f"Node type '{node_type}' not found in registry",
            phase="node_resolution",
            node_type=node_type,
            details={"available_nodes": available_nodes},
            suggestion=f"Available node types: {', '.join(sorted(available_nodes))}",
        )

    node_metadata = nodes[node_type]
    module_path = node_metadata["module"]
    class_name = node_metadata["class_name"]

    logger.debug(
        "Found node metadata",
        extra={
            "phase": "node_resolution",
            "node_type": node_type,
            "module_path": module_path,
            "class_name": class_name,
        },
    )

    # Step 2: Import the module
    logger.debug("Importing module", extra={"phase": "node_import", "module_path": module_path})

    # Check if this is a user node that needs special import handling
    node_type_info = node_metadata.get("type", "core")
    file_path = node_metadata.get("file_path", "")

    if node_type_info == "user" and file_path and file_path != "virtual://mcp":
        # User node: Import directly from file path
        logger.debug(f"Importing user node from file: {file_path}")
        try:
            spec = importlib.util.spec_from_file_location(module_path, file_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            else:
                raise ImportError(f"Could not load spec from {file_path}")
        except Exception as e:
            raise CompilationError(
                f"Failed to import user node from '{file_path}'",
                phase="node_import",
                node_type=node_type,
                details={"file_path": file_path, "import_error": str(e)},
                suggestion=f"Ensure the file '{file_path}' exists and contains valid Python code",
            ) from e
    else:
        # Core/MCP node: Use standard import
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            raise CompilationError(
                f"Failed to import module '{module_path}'",
                phase="node_import",
                node_type=node_type,
                details={"module_path": module_path, "import_error": str(e)},
                suggestion=f"Ensure the module '{module_path}' exists and is on the Python path",
            ) from e

    # Step 3: Get the class from the module
    logger.debug("Extracting class from module", extra={"phase": "node_import", "class_name": class_name})
    try:
        node_class = getattr(module, class_name)
    except AttributeError:
        raise CompilationError(
            f"Class '{class_name}' not found in module '{module_path}'",
            phase="node_import",
            node_type=node_type,
            details={"module_path": module_path, "class_name": class_name},
            suggestion=f"Check that '{class_name}' is defined in '{module_path}'",
        ) from None

    # Step 4: Validate inheritance from BaseNode
    logger.debug("Validating node inheritance", extra={"phase": "node_validation", "class_name": class_name})
    try:
        if not issubclass(node_class, BaseNode):
            # Get the actual base classes for better error message
            base_classes = [base.__name__ for base in node_class.__bases__]
            raise CompilationError(
                f"Class '{class_name}' does not inherit from BaseNode",
                phase="node_validation",
                node_type=node_type,
                details={"class_name": class_name, "actual_bases": base_classes},
                suggestion=f"Ensure '{class_name}' inherits from pflow.core.node.BaseNode or pflow.core.node.Node",
            )
    except TypeError:
        # Handle case where node_class is not actually a class
        raise CompilationError(
            f"'{class_name}' is not a class",
            phase="node_validation",
            node_type=node_type,
            details={"class_name": class_name, "actual_type": type(node_class).__name__},
            suggestion=f"Ensure '{class_name}' is a class definition, not an instance or function",
        ) from None

    logger.debug(
        "Node class imported successfully",
        extra={"phase": "node_validation", "node_type": node_type, "class_name": class_name},
    )

    return cast(type[BaseNode], node_class)
