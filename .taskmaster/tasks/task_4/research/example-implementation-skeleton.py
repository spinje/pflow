# Example Implementation Skeleton for Task 4
# This is NOT the actual implementation, just a reference skeleton
# ruff: noqa - This is example code with intentional TODOs and unused variables

"""
IR-to-PocketFlow compiler that transforms JSON IR into executable Flow objects.

This module is responsible for:
1. Loading node classes from registry metadata using dynamic imports
2. Instantiating nodes with parameters
3. Connecting nodes according to edges
4. Creating and returning an executable Flow
"""

import importlib
from typing import Any, Dict

import pocketflow


class CompilationError(Exception):
    """Raised when IR compilation fails with contextual information."""

    def __init__(self, message: str, node_id: str = None, node_type: str = None):
        self.node_id = node_id
        self.node_type = node_type
        if node_id and node_type:
            message = f"Node '{node_id}' (type: {node_type}) - {message}"
        elif node_id:
            message = f"Node '{node_id}' - {message}"
        super().__init__(message)


def compile_ir_to_flow(ir_json: Dict[str, Any], registry: Dict[str, Dict[str, str]]) -> pocketflow.Flow:
    """
    Compile JSON IR into an executable PocketFlow Flow object.

    Args:
        ir_json: Validated IR dictionary with nodes, edges, and optional start_node
        registry: Registry metadata mapping node types to module/class information

    Returns:
        pocketflow.Flow: Ready-to-execute Flow object

    Raises:
        CompilationError: If compilation fails with detailed context
    """
    # Validate inputs
    if not ir_json or "nodes" not in ir_json:
        raise CompilationError("Invalid IR: missing nodes")

    if not registry:
        raise CompilationError("Empty registry provided")

    # Create nodes
    nodes = {}

    for node_spec in ir_json["nodes"]:
        node_id = node_spec["id"]
        node_type = node_spec["type"]

        # TODO: Implement node creation
        # 1. Look up in registry
        # 2. Dynamic import
        # 3. Validate inheritance
        # 4. Instantiate and set params
        # 5. Store in nodes dict
        pass

    # Connect nodes
    for edge in ir_json.get("edges", []):
        from_id = edge["from"]
        to_id = edge["to"]
        action = edge.get("action", "default")

        # TODO: Implement edge connections
        # 1. Verify nodes exist
        # 2. Use >> or - action >> based on action value
        pass

    # Create flow
    start_node_id = ir_json.get("start_node")
    if not start_node_id and ir_json["nodes"]:
        start_node_id = ir_json["nodes"][0]["id"]

    if not start_node_id:
        raise CompilationError("No start node specified and no nodes in IR")

    # TODO: Create and return Flow
    # start_node = nodes[start_node_id]
    # return pocketflow.Flow(start=start_node)
    pass


# Example of what the error handling might look like:
def _import_node_class(metadata: Dict[str, str], node_type: str, node_id: str):
    """Helper to import a node class with proper error handling."""
    module_path = metadata.get("module")
    class_name = metadata.get("class_name")

    if not module_path or not class_name:
        raise CompilationError(
            "Invalid registry metadata: missing module or class_name", node_id=node_id, node_type=node_type
        )

    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise CompilationError(f"Cannot import module '{module_path}': {e}", node_id=node_id, node_type=node_type)

    try:
        NodeClass = getattr(module, class_name)
    except AttributeError:
        raise CompilationError(
            f"Module '{module_path}' has no class '{class_name}'", node_id=node_id, node_type=node_type
        )

    # Verify inheritance
    if not issubclass(NodeClass, (pocketflow.BaseNode, pocketflow.Node)):
        raise CompilationError(
            f"Class {class_name} must inherit from pocketflow.BaseNode or pocketflow.Node",
            node_id=node_id,
            node_type=node_type,
        )

    return NodeClass
