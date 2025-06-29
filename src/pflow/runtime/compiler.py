"""IR to PocketFlow compiler for pflow workflows.

This module provides the foundation for compiling JSON IR representations
into executable pocketflow.Flow objects. The current implementation provides
the infrastructure (error handling, validation, logging) with actual
compilation logic to be added in future subtasks.
"""

import importlib
import json
import logging
from typing import Any, Optional, Union, cast

from pflow.registry import Registry
from pocketflow import BaseNode, Flow

# Set up module logger
logger = logging.getLogger(__name__)


class CompilationError(Exception):
    """Error during IR compilation with rich context.

    This exception provides detailed information about compilation failures
    to help users quickly identify and fix issues in their workflow IR.

    Attributes:
        phase: The compilation phase where the error occurred
        node_id: ID of the node being compiled (if applicable)
        node_type: Type of the node being compiled (if applicable)
        details: Additional context about the error
        suggestion: Helpful suggestion for fixing the error
    """

    def __init__(
        self,
        message: str,
        phase: str = "unknown",
        node_id: Optional[str] = None,
        node_type: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        suggestion: Optional[str] = None,
    ):
        """Initialize compilation error with context.

        Args:
            message: The error message
            phase: Compilation phase (e.g., "parsing", "validation", "node_creation")
            node_id: ID of the problematic node
            node_type: Type of the problematic node
            details: Additional error context
            suggestion: Helpful suggestion for resolution
        """
        self.phase = phase
        self.node_id = node_id
        self.node_type = node_type
        self.details = details or {}
        self.suggestion = suggestion

        # Build comprehensive error message
        parts = [f"compiler: {message}"]
        if phase != "unknown":
            parts.append(f"Phase: {phase}")
        if node_id:
            parts.append(f"Node ID: {node_id}")
        if node_type:
            parts.append(f"Node Type: {node_type}")
        if suggestion:
            parts.append(f"Suggestion: {suggestion}")

        super().__init__("\n".join(parts))


def _parse_ir_input(ir_json: Union[str, dict[str, Any]]) -> dict[str, Any]:
    """Parse IR from string or pass through dict.

    Args:
        ir_json: JSON string or dict representing the workflow IR

    Returns:
        Parsed IR dictionary

    Raises:
        json.JSONDecodeError: If string input contains invalid JSON
    """
    if isinstance(ir_json, str):
        logger.debug("Parsing IR from JSON string", extra={"phase": "parsing"})
        return json.loads(ir_json)  # type: ignore[no-any-return]

    logger.debug("IR provided as dictionary", extra={"phase": "parsing"})
    return ir_json


def _validate_ir_structure(ir_dict: dict[str, Any]) -> None:
    """Validate basic IR structure (nodes, edges arrays).

    This performs minimal structural validation to ensure the IR has
    the required top-level keys. Full validation should be done by
    the IR schema validator before compilation.

    Args:
        ir_dict: The IR dictionary to validate

    Raises:
        CompilationError: If required keys are missing or have wrong types
    """
    logger.debug("Validating IR structure", extra={"phase": "validation"})

    # Check for required 'nodes' key
    if "nodes" not in ir_dict:
        raise CompilationError(
            "Missing 'nodes' key in IR", phase="validation", suggestion="IR must contain 'nodes' array"
        )

    # Check nodes is a list
    if not isinstance(ir_dict["nodes"], list):
        raise CompilationError(
            f"'nodes' must be an array, got {type(ir_dict['nodes']).__name__}",
            phase="validation",
            suggestion="Ensure 'nodes' is an array of node objects",
        )

    # Check for required 'edges' key
    if "edges" not in ir_dict:
        raise CompilationError(
            "Missing 'edges' key in IR", phase="validation", suggestion="IR must contain 'edges' array (can be empty)"
        )

    # Check edges is a list
    if not isinstance(ir_dict["edges"], list):
        raise CompilationError(
            f"'edges' must be an array, got {type(ir_dict['edges']).__name__}",
            phase="validation",
            suggestion="Ensure 'edges' is an array of edge objects",
        )

    logger.debug(
        "IR structure validated",
        extra={"phase": "validation", "node_count": len(ir_dict["nodes"]), "edge_count": len(ir_dict["edges"])},
    )


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
                suggestion=f"Ensure '{class_name}' inherits from pocketflow.BaseNode or pocketflow.Node",
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


def _instantiate_nodes(ir_dict: dict[str, Any], registry: Registry) -> dict[str, BaseNode]:
    """Instantiate node objects from IR node definitions.

    This function creates pocketflow node instances for each node in the IR,
    using the registry to look up node classes and setting any provided parameters.

    Args:
        ir_dict: The IR dictionary containing nodes array
        registry: Registry instance for node class lookup

    Returns:
        Dictionary mapping node_id to instantiated node objects

    Raises:
        CompilationError: If node instantiation fails
    """
    logger.debug("Starting node instantiation", extra={"phase": "node_instantiation"})
    nodes: dict[str, BaseNode] = {}

    for node_data in ir_dict["nodes"]:
        node_id = node_data["id"]
        node_type = node_data["type"]

        logger.debug(
            "Creating node instance",
            extra={"phase": "node_instantiation", "node_id": node_id, "node_type": node_type},
        )

        try:
            # Get the node class using our import function
            node_class = import_node_class(node_type, registry)

            # Instantiate the node (no parameters to constructor)
            node_instance = node_class()

            # Set parameters if provided
            if node_data.get("params"):
                logger.debug(
                    "Setting node parameters",
                    extra={"phase": "node_instantiation", "node_id": node_id, "param_count": len(node_data["params"])},
                )
                node_instance.set_params(node_data["params"])

            nodes[node_id] = node_instance

        except CompilationError as e:
            # Add node_id context if not already present
            if not e.node_id:
                e.node_id = node_id
            raise

    logger.debug(
        "Node instantiation complete",
        extra={"phase": "node_instantiation", "node_count": len(nodes)},
    )

    return nodes


def _wire_nodes(nodes: dict[str, BaseNode], edges: list[dict[str, Any]]) -> None:
    """Wire nodes together based on edge definitions.

    This function connects nodes using PocketFlow's >> operator for default
    connections and - operator for action-based routing.

    Args:
        nodes: Dictionary of instantiated nodes keyed by node_id
        edges: List of edge definitions from IR

    Raises:
        CompilationError: If edge references non-existent nodes
    """
    logger.debug("Starting node wiring", extra={"phase": "flow_wiring", "edge_count": len(edges)})

    for edge in edges:
        source_id = edge["source"]
        target_id = edge["target"]
        action = edge.get("action", "default")

        logger.debug(
            "Wiring nodes",
            extra={"phase": "flow_wiring", "source": source_id, "target": target_id, "action": action},
        )

        # Look up source node
        if source_id not in nodes:
            raise CompilationError(
                f"Edge references non-existent source node '{source_id}'",
                phase="flow_wiring",
                node_id=source_id,
                details={"edge": edge, "available_nodes": list(nodes.keys())},
                suggestion=f"Available nodes: {', '.join(sorted(nodes.keys()))}",
            )

        # Look up target node
        if target_id not in nodes:
            raise CompilationError(
                f"Edge references non-existent target node '{target_id}'",
                phase="flow_wiring",
                node_id=target_id,
                details={"edge": edge, "available_nodes": list(nodes.keys())},
                suggestion=f"Available nodes: {', '.join(sorted(nodes.keys()))}",
            )

        source = nodes[source_id]
        target = nodes[target_id]

        # Wire the nodes based on action
        if action == "default":
            source >> target
        else:
            source - action >> target

    logger.debug("Node wiring complete", extra={"phase": "flow_wiring"})


def _get_start_node(nodes: dict[str, BaseNode], ir_dict: dict[str, Any]) -> BaseNode:
    """Identify the start node for the flow.

    This function determines which node should be the entry point for the flow.
    Currently uses the first node in the nodes array as a simple fallback.

    Args:
        nodes: Dictionary of instantiated nodes
        ir_dict: The IR dictionary (for future start_node field support)

    Returns:
        The node to use as flow start

    Raises:
        CompilationError: If no nodes exist to start from
    """
    logger.debug("Identifying start node", extra={"phase": "start_detection"})

    # Check if we have any nodes at all
    if not nodes:
        raise CompilationError(
            "Cannot create flow with no nodes",
            phase="start_detection",
            suggestion="Add at least one node to the workflow",
        )

    # Future: Check for explicit start_node field
    start_node_id = ir_dict.get("start_node")

    # Fallback: Use first node in the nodes array
    if not start_node_id and ir_dict.get("nodes"):
        start_node_id = ir_dict["nodes"][0]["id"]
        logger.debug(
            "Using first node as start (no explicit start_node specified)",
            extra={"phase": "start_detection", "start_node_id": start_node_id},
        )

    if not start_node_id or start_node_id not in nodes:
        # This shouldn't happen with valid IR, but handle gracefully
        raise CompilationError(
            "Could not determine start node",
            phase="start_detection",
            details={"start_node_id": start_node_id, "available_nodes": list(nodes.keys())},
            suggestion="Ensure at least one node exists in the workflow",
        )

    logger.debug(
        "Start node identified",
        extra={"phase": "start_detection", "start_node_id": start_node_id},
    )

    return nodes[start_node_id]


def compile_ir_to_flow(ir_json: Union[str, dict[str, Any]], registry: Registry) -> Flow:
    """Compile JSON IR to executable pocketflow.Flow object.

    This is the main entry point for the compiler. It takes a workflow
    IR (as JSON string or dict) and produces an executable Flow object
    that can be run by the pflow runtime.

    Note: This is a traditional function implementation, not a PocketFlow-based
    compiler. We transform IR → Flow objects directly.

    Args:
        ir_json: JSON string or dict representing the workflow IR
        registry: Registry instance for node metadata lookup

    Returns:
        Executable pocketflow.Flow object

    Raises:
        CompilationError: With rich context about what failed
        json.JSONDecodeError: If JSON string is malformed
    """
    logger.debug("Starting IR compilation", extra={"phase": "init"})

    # Step 1: Parse input (string → dict)
    try:
        ir_dict = _parse_ir_input(ir_json)
    except json.JSONDecodeError:
        # Let JSONDecodeError bubble up as specified
        logger.exception("JSON parsing failed", extra={"phase": "parsing"})
        raise

    # Step 2: Validate structure
    try:
        _validate_ir_structure(ir_dict)
    except CompilationError:
        # Re-raise compilation errors with proper context
        logger.exception("IR validation failed", extra={"phase": "validation"})
        raise

    # Step 3: Log compilation steps
    logger.info(
        "IR validated, ready for compilation",
        extra={
            "phase": "pre-compilation",
            "nodes": len(ir_dict.get("nodes", [])),
            "edges": len(ir_dict.get("edges", [])),
        },
    )

    # Step 4: Instantiate nodes
    try:
        nodes = _instantiate_nodes(ir_dict, registry)
    except CompilationError:
        logger.exception("Node instantiation failed", extra={"phase": "node_instantiation"})
        raise

    # Step 5: Wire nodes together
    try:
        _wire_nodes(nodes, ir_dict.get("edges", []))
    except CompilationError:
        logger.exception("Node wiring failed", extra={"phase": "flow_wiring"})
        raise

    # Step 6: Get start node
    try:
        start_node = _get_start_node(nodes, ir_dict)
    except CompilationError:
        logger.exception("Start node detection failed", extra={"phase": "start_detection"})
        raise

    # Step 7: Create and return Flow
    logger.debug("Creating Flow object", extra={"phase": "flow_creation"})
    flow = Flow(start=start_node)

    logger.info(
        "Compilation successful",
        extra={
            "phase": "complete",
            "node_count": len(nodes),
            "edge_count": len(ir_dict.get("edges", [])),
        },
    )

    return flow
