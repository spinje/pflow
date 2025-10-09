"""IR to PocketFlow compiler for pflow workflows.

This module provides the foundation for compiling JSON IR representations
into executable pocketflow.Flow objects. The current implementation provides
the infrastructure (error handling, validation, logging) with actual
compilation logic to be added in future subtasks.
"""

import importlib
import importlib.util
import json
import logging
import sys
from typing import Any, Optional, Union, cast

from pflow.core.ir_schema import ValidationError
from pflow.core.validation_utils import get_parameter_validation_error, is_valid_parameter_name
from pflow.registry import Registry
from pocketflow import BaseNode, Flow

from .namespaced_wrapper import NamespacedNodeWrapper
from .node_wrapper import TemplateAwareNodeWrapper
from .template_resolver import TemplateResolver
from .template_validator import TemplateValidator, ValidationWarning
from .workflow_validator import prepare_inputs, validate_ir_structure

# Set up module logger
logger = logging.getLogger(__name__)

# Display limits for warning output
MAX_DISPLAYED_WARNINGS_PER_NODE = 10  # Limit to avoid overwhelming terminal output


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


def _display_validation_warnings(warnings: list[ValidationWarning]) -> None:
    """Display validation warnings in a user-friendly format.

    Warnings are grouped by node for cleaner output and displayed to stderr
    so they don't interfere with JSON output mode.

    Args:
        warnings: List of validation warnings to display
    """
    # Group warnings by node for cleaner output
    by_node: dict[str, list[ValidationWarning]] = {}
    for w in warnings:
        if w.node_id not in by_node:
            by_node[w.node_id] = []
        by_node[w.node_id].append(w)

    # Display grouped warnings
    print(file=sys.stderr)  # Blank line for separation
    print(f"Note: {len(warnings)} template(s) use runtime validation:", file=sys.stderr)
    print(file=sys.stderr)

    for node_id, node_warnings in by_node.items():
        # Show node context once
        first = node_warnings[0]

        # Format node type (shorten MCP types)
        node_type_display = first.node_type
        if node_type_display.startswith("mcp-"):
            # Remove 'mcp-' prefix and replace first '-composio-' with '/'
            node_type_display = node_type_display[4:]  # Remove 'mcp-'
            if "-composio-" in node_type_display:
                node_type_display = node_type_display.replace("-composio-", "/", 1)

        print(f"  Node '{node_id}' ({node_type_display}):", file=sys.stderr)
        print(f"    Output type: {first.output_type} (structure unknown at validation time)", file=sys.stderr)
        print(file=sys.stderr)

        # Show each template (limit to avoid overwhelming)
        display_count = min(len(node_warnings), MAX_DISPLAYED_WARNINGS_PER_NODE)
        for w in node_warnings[:display_count]:
            print(f"    • {w.template}", file=sys.stderr)
            print(f"      Accessing: {w.output_key}.{w.nested_path}", file=sys.stderr)
            print(file=sys.stderr)

        if len(node_warnings) > MAX_DISPLAYED_WARNINGS_PER_NODE:
            remaining = len(node_warnings) - MAX_DISPLAYED_WARNINGS_PER_NODE
            print(f"    ... and {remaining} more template(s)", file=sys.stderr)
            print(file=sys.stderr)

    print("  These templates will be validated during workflow execution.", file=sys.stderr)
    print("  If the nested paths don't exist, the workflow will fail at runtime.", file=sys.stderr)
    print(file=sys.stderr)


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


def _apply_template_wrapping(
    node_instance: Union[BaseNode, TemplateAwareNodeWrapper, NamespacedNodeWrapper],
    node_id: str,
    params: dict[str, Any],
    initial_params: dict[str, Any],
) -> Union[BaseNode, TemplateAwareNodeWrapper, NamespacedNodeWrapper]:
    """Apply template wrapping to a node if it has template parameters.

    Args:
        node_instance: The node instance to potentially wrap
        node_id: The ID of the node
        params: The node's parameters
        initial_params: Initial parameters for template resolution

    Returns:
        The original node or a wrapped version if templates are detected
    """
    # Check if any parameters contain templates (including nested structures)
    has_templates = any(TemplateResolver.has_templates(value) for value in params.values())

    if has_templates:
        # Wrap node for template support (runtime proxy)
        logger.debug(
            f"Wrapping node '{node_id}' for template resolution",
            extra={"phase": "node_instantiation", "node_id": node_id},
        )
        return TemplateAwareNodeWrapper(node_instance, node_id, initial_params)

    return node_instance


def _check_registry_for_mcp(
    registry: Registry,
) -> tuple[bool, list[str]]:
    """Check if registry supports MCP validation.

    Args:
        registry: Registry instance to check

    Returns:
        Tuple of (should_validate, available_nodes)
    """
    try:
        # Try to get nodes from registry
        if hasattr(registry, "load"):
            nodes = registry.load()
            if nodes and isinstance(nodes, dict):
                available_nodes = list(nodes.keys())
                # Only validate if we have a real registry with actual nodes
                # Don't validate for test/mock registries
                return len(available_nodes) > 0, available_nodes
    except Exception:
        # If registry doesn't support load() or fails, skip validation
        # This happens in tests with mock registries
        logger.debug(
            "Registry does not support MCP validation",
            extra={"phase": "node_resolution"},
        )

    return False, []


def _create_mcp_error_suggestion(
    node_type: str,
    mcp_nodes: list[str],
) -> str:
    """Create helpful error suggestion for missing MCP node.

    Args:
        node_type: The MCP node type that wasn't found
        mcp_nodes: List of available MCP nodes

    Returns:
        Suggestion string for the error
    """
    if not mcp_nodes:
        # No MCP tools registered at all
        return (
            "No MCP tools are registered. You need to sync them first.\n\n"
            "Steps to enable MCP tools:\n"
            "  1. Check configured servers: pflow mcp list\n"
            "  2. Sync tools: pflow mcp sync --all\n"
            "  3. Verify registration: pflow registry list | grep mcp\n"
            "  4. Run your workflow again"
        )

    # MCP tools exist but not this one - suggest alternatives
    from difflib import get_close_matches

    similar = get_close_matches(node_type, mcp_nodes, n=3, cutoff=0.4)

    if similar:
        suggestion_parts = [f"MCP tool '{node_type}' not found.\n\nDid you mean one of these?"]
        for s in similar:
            # Extract tool name for display
            tool_parts = s.split("-", 2)
            if len(tool_parts) >= 3:
                suggestion_parts.append(f"  • {s} ({tool_parts[1]} server: {tool_parts[2]})")
            else:
                suggestion_parts.append(f"  • {s}")
        return "\n".join(suggestion_parts)

    # No similar tools found - list available servers
    servers = set()
    for node in mcp_nodes:
        node_parts = node.split("-", 2)
        if len(node_parts) >= 2:
            servers.add(node_parts[1])

    return (
        f"MCP tool '{node_type}' not found.\n\n"
        f"Available MCP servers: {', '.join(sorted(servers))}\n"
        f"Total MCP tools: {len(mcp_nodes)}\n\n"
        f"Use 'pflow registry list' to see all available MCP tools."
    )


def _parse_mcp_node_type(node_type: str) -> tuple[str, str]:
    """Parse an MCP node type into server and tool names.

    Handles server names that contain dashes by checking against known MCP servers.
    Format: mcp-<server-name>-<tool-name>

    Args:
        node_type: Full node type like "mcp-local-test-echo"

    Returns:
        Tuple of (server_name, tool_name)

    Raises:
        CompilationError: If the server cannot be determined unambiguously
    """
    parts = node_type.split("-")

    if len(parts) < 3:
        raise CompilationError(
            f"Invalid MCP node type format: {node_type}",
            phase="node_resolution",
            suggestion="MCP node types must be in format: mcp-<server>-<tool>",
        )

    try:
        from pflow.mcp.manager import MCPServerManager

        manager = MCPServerManager()
        servers = manager.list_servers()
    except Exception as e:
        # If we can't load servers, we can't parse reliably
        raise CompilationError(
            f"Failed to load MCP servers for parsing: {e}",
            phase="node_resolution",
            node_type=node_type,
            suggestion="Check MCP server configuration",
        ) from e

    # Try progressively longer server names to find the longest match
    # This ensures we get "test-with-dashes" instead of "test"
    best_match = None
    best_match_length = 0

    for i in range(2, len(parts) + 1):
        possible_server = "-".join(parts[1:i])
        # Keep track of the longest matching server name
        if possible_server in servers and i - 1 > best_match_length:
            best_match = (possible_server, "-".join(parts[i:]) if i < len(parts) else "")
            best_match_length = i - 1

    if best_match:
        server_name, tool_name = best_match
        if not tool_name:
            raise CompilationError(
                f"Invalid MCP node type: {node_type} - no tool name after server '{server_name}'",
                phase="node_resolution",
                suggestion=f"Format should be: mcp-{server_name}-<tool-name>",
            )
        return server_name, tool_name

    # No matching server found
    raise CompilationError(
        f"MCP server not found for node type: {node_type}",
        phase="node_resolution",
        node_type=node_type,
        suggestion=f"Could not find MCP server from: {parts[1]}. Available servers: {', '.join(sorted(servers))}",
    )


def _inject_special_parameters(
    node_type: str,
    node_id: str,
    params: dict[str, Any],
    registry: Registry,
) -> dict[str, Any]:
    """Inject special parameters for workflow and MCP nodes.

    Args:
        node_type: The type of the node
        node_id: The ID of the node
        params: Original node parameters
        registry: Registry instance for workflow nodes

    Returns:
        Updated parameters dictionary (copy of original with injections)
    """
    # For workflow type, inject registry as special parameter
    if node_type == "workflow" or node_type == "pflow.runtime.workflow_executor":
        params = params.copy()  # Don't modify original
        params["__registry__"] = registry
        logger.debug(
            "Injecting registry for WorkflowExecutor",
            extra={"phase": "node_instantiation", "node_id": node_id},
        )
        return params

    # For MCP virtual nodes, inject server and tool metadata
    if node_type.startswith("mcp-"):
        parts = node_type.split("-", 2)  # Split into ["mcp", "server", "tool-name"]

        # Check if MCP node format is valid (must have at least server and tool)
        if len(parts) < 3:
            # Malformed MCP node type - don't inject metadata, just return params unchanged
            # This handles edge cases like "mcp-" or "mcp-server" without tool
            # Tests expect these to be handled gracefully without errors
            return params

        # Check if this MCP node actually exists in registry
        # Only validate if registry has real nodes (not in test environment)
        should_validate_mcp, available_nodes = _check_registry_for_mcp(registry)

        if should_validate_mcp and node_type not in available_nodes:
            # MCP node not found - check if ANY MCP nodes exist
            mcp_nodes = [n for n in available_nodes if n.startswith("mcp-")]
            suggestion = _create_mcp_error_suggestion(node_type, mcp_nodes)

            raise CompilationError(
                f"MCP tool '{node_type}' not found" if not mcp_nodes else "MCP tool not found",
                phase="node_resolution",
                node_type=node_type,
                suggestion=suggestion,
            )

        # Node exists - inject parameters (copy first to avoid mutating original)
        params = params.copy()  # Create a new dict to avoid mutating the original

        # Parse server and tool names correctly, handling server names with dashes
        # The format is mcp-<server-name>-<tool-name> where server-name can contain dashes
        # We need to find the correct split point by checking known MCP servers
        server_name, tool_name = _parse_mcp_node_type(node_type)

        params["__mcp_server__"] = server_name
        params["__mcp_tool__"] = tool_name
        logger.debug(
            "Injecting MCP metadata for virtual node",
            extra={
                "phase": "node_instantiation",
                "node_id": node_id,
                "mcp_server": server_name,
                "mcp_tool": tool_name,
            },
        )
        return params

    return params


def _create_single_node(
    node_data: dict[str, Any],
    registry: Registry,
    initial_params: dict[str, Any],
    enable_namespacing: bool,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
) -> Any:  # Can be any wrapper type
    """Create and configure a single node instance.

    Args:
        node_data: Node definition from IR
        registry: Registry instance for node class lookup
        initial_params: Parameters for template resolution
        enable_namespacing: Whether to apply namespace wrapping
        metrics_collector: Optional MetricsCollector for cost tracking
        trace_collector: Optional WorkflowTraceCollector for debugging

    Returns:
        Configured node instance

    Raises:
        CompilationError: If node instantiation fails
    """
    node_id = node_data["id"]
    node_type = node_data["type"]
    params = node_data.get("params", {})

    logger.debug(
        "Creating node instance",
        extra={"phase": "node_instantiation", "node_id": node_id, "node_type": node_type},
    )

    # Get the node class using our import function
    node_class = import_node_class(node_type, registry)

    # Instantiate the node (no parameters to constructor)
    # Use Any type since we'll be wrapping with various wrapper types
    node_instance: Any = node_class()

    # Apply template wrapping if needed
    node_instance = _apply_template_wrapping(node_instance, node_id, params, initial_params)

    # Apply namespace wrapping if enabled
    if enable_namespacing:
        logger.debug(
            f"Wrapping node '{node_id}' for namespace isolation",
            extra={"phase": "node_instantiation", "node_id": node_id},
        )
        node_instance = NamespacedNodeWrapper(node_instance, node_id)

    # Always apply instrumentation wrapper to support all features:
    # - Progress callbacks (if __progress_callback__ is in shared storage)
    # - Metrics collection (if metrics_collector is provided)
    # - Trace collection (if trace_collector is provided)
    # The wrapper is lightweight and only adds overhead when features are actually used
    from pflow.runtime.instrumented_wrapper import InstrumentedNodeWrapper

    logger.debug(
        f"Wrapping node '{node_id}' for instrumentation",
        extra={
            "phase": "node_instantiation",
            "node_id": node_id,
            "has_metrics": bool(metrics_collector),
            "has_trace": bool(trace_collector),
        },
    )
    node_instance = InstrumentedNodeWrapper(node_instance, node_id, metrics_collector, trace_collector)

    # Inject special parameters for workflow and MCP nodes
    params = _inject_special_parameters(node_type, node_id, params, registry)

    # Set parameters (wrapper will separate template vs static)
    if params:
        logger.debug(
            "Setting node parameters",
            extra={"phase": "node_instantiation", "node_id": node_id, "param_count": len(params)},
        )
        node_instance.set_params(params)

    return node_instance


def _instantiate_nodes(
    ir_dict: dict[str, Any],
    registry: Registry,
    initial_params: Optional[dict[str, Any]] = None,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
) -> dict[str, Any]:  # Can return nodes with various wrapper types
    """Instantiate node objects from IR node definitions with template and namespace support.

    This function creates pocketflow node instances for each node in the IR,
    using the registry to look up node classes and setting any provided parameters.
    Nodes with template parameters are wrapped for runtime resolution.
    If namespacing is enabled, nodes are additionally wrapped to isolate their outputs.
    If collectors are provided, nodes are also wrapped for instrumentation.

    Args:
        ir_dict: The IR dictionary containing nodes array and optional enable_namespacing flag
        registry: Registry instance for node class lookup
        initial_params: Parameters extracted by planner (for template resolution)
        metrics_collector: Optional MetricsCollector for cost tracking
        trace_collector: Optional WorkflowTraceCollector for debugging

    Returns:
        Dictionary mapping node_id to instantiated node objects

    Raises:
        CompilationError: If node instantiation fails
    """
    logger.debug("Starting node instantiation", extra={"phase": "node_instantiation"})
    nodes: dict[str, Any] = {}  # Can contain various wrapper types
    initial_params = initial_params or {}

    # Check if namespacing is enabled in the workflow (default: True for MVP)
    enable_namespacing = ir_dict.get("enable_namespacing", True)
    if enable_namespacing:
        logger.debug("Automatic namespacing enabled for workflow", extra={"phase": "node_instantiation"})

    for node_data in ir_dict["nodes"]:
        node_id = node_data["id"]

        try:
            node_instance = _create_single_node(
                node_data, registry, initial_params, enable_namespacing, metrics_collector, trace_collector
            )
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


def _wire_nodes(nodes: dict[str, Any], edges: list[dict[str, Any]]) -> None:
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
        # Support both edge field formats for compatibility
        source_id = edge.get("source") or edge.get("from")
        target_id = edge.get("target") or edge.get("to")
        action = edge.get("action", "default")

        # Validate we have both IDs
        if not source_id or not target_id:
            raise CompilationError(
                "Edge missing source or target node ID",
                phase="flow_wiring",
                details={"edge": edge},
                suggestion="Ensure edges have 'source'/'target' or 'from'/'to' fields",
            )

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


def _get_start_node(nodes: dict[str, Any], ir_dict: dict[str, Any]) -> Any:
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


def _validate_workflow(
    ir_dict: dict[str, Any], registry: Registry, initial_params: dict[str, Any], validate_templates: bool
) -> dict[str, Any]:
    """Validate workflow IR and prepare parameters.

    This function consolidates all validation steps to reduce complexity
    in the main compile_ir_to_flow function.

    Args:
        ir_dict: The workflow IR dictionary
        registry: Registry instance for node metadata lookup
        initial_params: Initial parameters for the workflow
        validate_templates: Whether to validate template variables

    Returns:
        Updated initial_params with defaults applied

    Raises:
        CompilationError: If structure validation fails
        ValidationError: If input/output validation fails
        ValueError: If template validation fails
    """
    # Step 2: Validate structure
    try:
        validate_ir_structure(ir_dict)
    except CompilationError:
        logger.exception("IR validation failed", extra={"phase": "validation"})
        raise

    # Step 3: Validate inputs and apply defaults
    try:
        errors, defaults = prepare_inputs(ir_dict, initial_params)
        if errors:
            if len(errors) == 1:
                # Single error - keep current behavior for backward compatibility
                message, path, suggestion = errors[0]
                raise ValidationError(message, path=path, suggestion=suggestion)
            else:
                # Multiple errors - aggregate them for better UX
                error_lines = []
                for msg, path, _ in errors:  # Ignore individual suggestions
                    # Extract just the input name from path like "inputs.api_key"
                    input_name = path.split(".")[-1] if "." in path else path
                    error_lines.append(f"  • '{input_name}' - {msg}")

                combined_message = f"Found {len(errors)} input validation errors:\n" + "\n".join(error_lines)
                raise ValidationError(
                    message=combined_message,
                    path="inputs",
                    suggestion="Fix all validation errors above before compiling the workflow",
                )
        initial_params.update(defaults)  # Explicit mutation
    except ValidationError:
        logger.exception("Input validation failed", extra={"phase": "input_validation"})
        raise

    # Step 4: Validate outputs
    try:
        _validate_outputs(ir_dict, registry)
    except ValidationError:
        logger.exception("Output validation failed", extra={"phase": "output_validation"})
        raise

    # Step 5: Validate templates if requested
    if validate_templates:
        logger.debug("Validating template variables", extra={"phase": "template_validation"})
        template_errors, template_warnings = TemplateValidator.validate_workflow_templates(
            ir_dict, initial_params, registry
        )

        # Display warnings if present (non-blocking)
        if template_warnings:
            _display_validation_warnings(template_warnings)

        # Fail only on errors
        if template_errors:
            error_msg = "Template validation failed:\n" + "\n".join(f"  - {e}" for e in template_errors)
            logger.error(
                "Template validation failed",
                extra={"phase": "template_validation", "error_count": len(template_errors), "errors": template_errors},
            )
            raise ValueError(error_msg)

    return initial_params


def _validate_outputs(workflow_ir: dict[str, Any], registry: Registry) -> None:
    """Validate declared workflow outputs can be produced by nodes.

    This function validates that declared outputs CAN be produced by nodes in the workflow.
    Since nodes may write dynamic keys at runtime, this only issues warnings, not errors.

    Args:
        workflow_ir: The workflow IR dictionary containing output declarations
        registry: Registry instance for accessing node metadata

    Raises:
        ValidationError: If output names are invalid identifiers
    """
    # Extract output declarations (backward compatible with workflows without outputs)
    outputs = workflow_ir.get("outputs", {})

    # If no outputs declared, nothing to validate
    if not outputs:
        logger.debug("No outputs declared for workflow", extra={"phase": "output_validation"})
        return

    logger.debug(
        "Validating workflow outputs", extra={"phase": "output_validation", "declared_outputs": list(outputs.keys())}
    )

    # First validate all output names are valid Python identifiers
    for output_name, _output_spec in outputs.items():
        if not is_valid_parameter_name(output_name):
            error_msg = get_parameter_validation_error(output_name, "output")
            raise ValidationError(
                message=error_msg,
                path=f"outputs.{output_name}",
                suggestion="Avoid shell special characters like $, |, >, <, &, ;",
            )

    # Get all possible outputs from nodes in the workflow
    all_node_outputs = TemplateValidator._extract_node_outputs(workflow_ir, registry)

    # For nested workflows, we need to also consider their output_mapping
    for node in workflow_ir.get("nodes", []):
        if node.get("type") in ["workflow", "pflow.runtime.workflow_executor"]:
            # Get the output_mapping parameter if present
            output_mapping = node.get("params", {}).get("output_mapping", {})
            # The values in output_mapping become available outputs in parent workflow
            for _child_key, parent_key in output_mapping.items():
                all_node_outputs[parent_key] = {"type": "any"}

    logger.debug(
        f"Found {len(all_node_outputs)} possible outputs from nodes",
        extra={"phase": "output_validation", "available_outputs": sorted(all_node_outputs.keys())},
    )

    # Validate each declared output can be produced
    for output_name, output_spec in outputs.items():
        # If output has a 'source' field, it will be resolved from that expression
        if isinstance(output_spec, dict) and "source" in output_spec:
            logger.debug(
                f"Output '{output_name}' uses source expression: {output_spec['source']}",
                extra={"phase": "output_validation", "output": output_name},
            )
            continue  # Skip validation for outputs with source field

        # Check if output can be traced to any node
        if output_name not in all_node_outputs:
            # Issue warning, not error, since nodes may write dynamic keys
            logger.warning(
                f"Declared output '{output_name}' cannot be traced to any node in the workflow. "
                f"This may be fine if nodes write dynamic keys.",
                extra={
                    "phase": "output_validation",
                    "output": output_name,
                    "available_outputs": sorted(all_node_outputs.keys()),
                },
            )
        else:
            logger.debug(
                f"Output '{output_name}' can be produced by workflow nodes",
                extra={"phase": "output_validation", "output": output_name},
            )

    logger.debug("Output validation complete", extra={"phase": "output_validation"})


def compile_ir_to_flow(
    ir_json: Union[str, dict[str, Any]],
    registry: Registry,
    initial_params: Optional[dict[str, Any]] = None,
    validate: bool = True,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
) -> Flow:
    """Compile JSON IR to executable pocketflow.Flow object with template support.

    This is the main entry point for the compiler. It takes a workflow
    IR (as JSON string or dict) and produces an executable Flow object
    that can be run by the pflow runtime. Supports template variables
    that are resolved at runtime.

    Note: This is a traditional function implementation, not a PocketFlow-based
    compiler. We transform IR → Flow objects directly.

    Args:
        ir_json: JSON string or dict representing the workflow IR
        registry: Registry instance for node metadata lookup
        initial_params: Parameters extracted by planner from natural language
                       Example: {"issue_number": "1234", "repo": "pflow"}
                       from user saying "fix github issue 1234 in pflow repo"
        validate: Whether to validate templates (default: True)
                 Set to False only for testing template resolution in isolation
        metrics_collector: Optional MetricsCollector for cost tracking
        trace_collector: Optional WorkflowTraceCollector for debugging

    Returns:
        Executable pocketflow.Flow object

    Raises:
        CompilationError: With rich context about what failed
        ValueError: If template validation fails
        json.JSONDecodeError: If JSON string is malformed
    """
    logger.debug("Starting IR compilation", extra={"phase": "init"})
    initial_params = initial_params or {}

    # Step 1: Parse input (string → dict)
    try:
        ir_dict = _parse_ir_input(ir_json)
    except json.JSONDecodeError:
        # Let JSONDecodeError bubble up as specified
        logger.exception("JSON parsing failed", extra={"phase": "parsing"})
        raise

    # Steps 2-5: Validate workflow and prepare parameters
    initial_params = _validate_workflow(ir_dict, registry, initial_params, validate)

    # Step 6: Log compilation steps
    logger.info(
        "IR validated, ready for compilation",
        extra={
            "phase": "pre-compilation",
            "nodes": len(ir_dict.get("nodes", [])),
            "edges": len(ir_dict.get("edges", [])),
            "has_initial_params": bool(initial_params),
        },
    )

    # Step 7: Instantiate nodes with template support
    try:
        nodes = _instantiate_nodes(ir_dict, registry, initial_params, metrics_collector, trace_collector)
    except CompilationError:
        logger.exception("Node instantiation failed", extra={"phase": "node_instantiation"})
        raise

    # Step 8: Wire nodes together
    try:
        _wire_nodes(nodes, ir_dict.get("edges", []))
    except CompilationError:
        logger.exception("Node wiring failed", extra={"phase": "flow_wiring"})
        raise

    # Step 9: Get start node
    try:
        start_node = _get_start_node(nodes, ir_dict)
    except CompilationError:
        logger.exception("Start node detection failed", extra={"phase": "start_detection"})
        raise

    # Step 10: Create and return Flow
    logger.debug("Creating Flow object", extra={"phase": "flow_creation"})
    flow = Flow(start=start_node)

    # Step 11: Wrap flow.run to populate outputs if declared
    if ir_dict.get("outputs"):
        from pflow.runtime.output_resolver import populate_declared_outputs

        original_run = flow.run

        def run_with_outputs(shared_storage: dict[str, Any]) -> str:
            """Run flow and populate declared outputs."""
            result = original_run(shared_storage)
            # Only populate outputs on successful execution
            if not (result and isinstance(result, str) and result.startswith("error")):
                populate_declared_outputs(shared_storage, ir_dict)
            return str(result)

        flow.run = run_with_outputs  # type: ignore[method-assign]

    logger.info(
        "Compilation successful",
        extra={
            "phase": "complete",
            "node_count": len(nodes),
            "edge_count": len(ir_dict.get("edges", [])),
        },
    )

    return flow
