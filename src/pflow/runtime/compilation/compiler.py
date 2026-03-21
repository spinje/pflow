"""IR to PocketFlow compiler for pflow workflows.

This module is the core orchestrator of the compilation pipeline: it parses IR,
delegates validation, instantiates nodes with wrapper chains, wires edges, and
builds the executable PocketFlow Flow object.

Supporting concerns are in sibling modules:
- compile_validation.py — pre-compilation validation orchestration
- mcp_resolution.py — MCP node type parsing and error suggestions
- node_loader.py — dynamic node class importing
- ir_preparation.py — IR structure validation and input preparation
"""

import json
import logging
from typing import Any, Optional, Union

from pflow.core.llm_config import get_default_workflow_model, get_model_not_configured_help
from pflow.pocketflow import BaseNode, Flow
from pflow.registry import Registry

from ..template_resolver import TemplateResolver
from ..wrappers.namespaced_wrapper import NamespacedNodeWrapper
from ..wrappers.template_wrapper import TemplateAwareNodeWrapper
from .compile_validation import _validate_workflow
from .mcp_resolution import _check_registry_for_mcp, _create_mcp_error_suggestion, _parse_mcp_node_type
from .node_loader import import_node_class

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


def _apply_template_wrapping(
    node_instance: Union[BaseNode, TemplateAwareNodeWrapper, NamespacedNodeWrapper],
    node_id: str,
    params: dict[str, Any],
    initial_params: dict[str, Any],
    template_resolution_mode: str = "strict",
    interface_metadata: Optional[dict[str, Any]] = None,
    optional_input_keys: Optional[set[str]] = None,
) -> Union[BaseNode, TemplateAwareNodeWrapper, NamespacedNodeWrapper]:
    """Apply template wrapping to a node if it has template parameters.

    Args:
        node_instance: The node instance to potentially wrap
        node_id: The ID of the node
        params: The node's parameters
        initial_params: Initial parameters for template resolution
        template_resolution_mode: Template resolution mode ('strict' or 'permissive')
        interface_metadata: Node interface metadata from registry (optional)
                          Contains input/param type information for validation
        optional_input_keys: Set of input keys annotated as optional in code node
                           source. Enables None injection for branch convergence.

    Returns:
        The original node or a wrapped version if templates are detected
    """
    # Check if any parameters contain templates (including nested structures)
    has_templates = any(TemplateResolver.has_templates(value) for value in params.values())

    if has_templates:
        # Wrap node for template support (runtime proxy)
        logger.debug(
            f"Wrapping node '{node_id}' for template resolution (mode: {template_resolution_mode})",
            extra={
                "phase": "node_instantiation",
                "node_id": node_id,
                "mode": template_resolution_mode,
                "has_metadata": bool(interface_metadata),
            },
        )
        return TemplateAwareNodeWrapper(
            node_instance,
            node_id,
            initial_params,
            template_resolution_mode,
            interface_metadata,
            optional_input_keys,
        )

    return node_instance


def inject_special_parameters(
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
    template_resolution_mode: str,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
) -> Any:  # Can be any wrapper type
    """Create and configure a single node instance.

    Args:
        node_data: Node definition from IR
        registry: Registry instance for node class lookup
        initial_params: Parameters for template resolution
        enable_namespacing: Whether to apply namespace wrapping
        template_resolution_mode: Template resolution mode ('strict' or 'permissive')
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

    # Thread source-line metadata from the markdown parser into params so
    # nodes can reference the .pflow.md file line in error messages.
    source_lines = node_data.get("_source_lines")
    if source_lines:
        params = {**params, **{f"_{k}_source_line": v for k, v in source_lines.items()}}

    # Inject default model for LLM nodes if not specified
    if node_type == "llm" and "model" not in params:
        default_model = get_default_workflow_model()

        if default_model:
            # Inject the configured default (create new dict to avoid mutating IR)
            params = {**params, "model": default_model}
            logger.info(
                f"Injecting default model '{default_model}' for LLM node '{node_id}'",
                extra={
                    "phase": "node_instantiation",
                    "node_id": node_id,
                    "default_model": default_model,
                    "source": "settings_or_llm_default",
                },
            )
        else:
            # No model configured anywhere - fail with helpful message
            raise CompilationError(
                message=f"No model configured for LLM node '{node_id}'",
                phase="node_instantiation",
                node_id=node_id,
                node_type=node_type,
                suggestion=get_model_not_configured_help(node_id),
            )

    logger.debug(
        "Creating node instance",
        extra={"phase": "node_instantiation", "node_id": node_id, "node_type": node_type},
    )

    # Get the node class using our import function
    node_class = import_node_class(node_type, registry)

    # Instantiate the node (no parameters to constructor)
    # Use Any type since we'll be wrapping with various wrapper types
    node_instance: Any = node_class()

    # NEW: Extract interface metadata from registry for type validation
    nodes = registry.load()
    node_metadata = nodes.get(node_type, {})
    interface_metadata = node_metadata.get("interface")

    logger.debug(
        f"Extracted interface metadata for node '{node_id}'",
        extra={
            "phase": "node_instantiation",
            "node_id": node_id,
            "has_metadata": bool(interface_metadata),
            "input_count": len(interface_metadata.get("inputs", [])) if interface_metadata else 0,
            "param_count": len(interface_metadata.get("params", [])) if interface_metadata else 0,
        },
    )

    # Extract optional input keys for code nodes (enables branch convergence)
    # When a code node declares inputs as Optional[T] or T | None, the template
    # wrapper injects None instead of erroring when the source node didn't execute.
    optional_input_keys: Optional[set[str]] = None
    if node_type == "code" and "code" in params and isinstance(params.get("inputs"), dict):
        from pflow.nodes.python.python_code import extract_optional_input_keys

        input_keys = set(params["inputs"].keys())
        optional_input_keys = extract_optional_input_keys(params["code"], input_keys) or None
        if optional_input_keys:
            logger.debug(
                f"Code node '{node_id}' has optional inputs: {optional_input_keys}",
                extra={"phase": "node_instantiation", "node_id": node_id},
            )

    # Apply template wrapping if needed (pass metadata for type validation)
    node_instance = _apply_template_wrapping(
        node_instance,
        node_id,
        params,
        initial_params,
        template_resolution_mode,
        interface_metadata,
        optional_input_keys,
    )

    # Apply namespace wrapping if enabled
    if enable_namespacing:
        logger.debug(
            f"Wrapping node '{node_id}' for namespace isolation",
            extra={"phase": "node_instantiation", "node_id": node_id},
        )
        node_instance = NamespacedNodeWrapper(node_instance, node_id)

    # Apply batch wrapping if configured
    # CRITICAL: Batch must be OUTSIDE namespace wrapper (between Namespace and Instrumented)
    # This ensures item alias injection writes to root level: shared["item"] = x
    # NOT to namespace: shared["node_id"]["item"] = x
    batch_config = node_data.get("batch")
    if batch_config:
        from pflow.runtime.wrappers.batch_node import PflowBatchNode

        logger.debug(
            f"Wrapping node '{node_id}' for batch processing",
            extra={
                "phase": "node_instantiation",
                "node_id": node_id,
                "items_template": batch_config.get("items"),
                "item_alias": batch_config.get("as", "item"),
                "error_handling": batch_config.get("error_handling", "fail_fast"),
            },
        )
        node_instance = PflowBatchNode(node_instance, node_id, batch_config)

    # Always apply instrumentation wrapper to support all features:
    # - Progress callbacks (if __progress_callback__ is in shared storage)
    # - Metrics collection (if metrics_collector is provided)
    # - Trace collection (if trace_collector is provided)
    # The wrapper is lightweight and only adds overhead when features are actually used
    from pflow.runtime.wrappers.instrumented_wrapper import InstrumentedNodeWrapper

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
    params = inject_special_parameters(node_type, node_id, params, registry)

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
        initial_params: Parameters provided before execution (for template resolution)
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

    # Get template resolution mode from initial_params (set in _validate_workflow)
    template_resolution_mode = initial_params.get("__template_resolution_mode__", "strict")

    for node_data in ir_dict["nodes"]:
        node_id = node_data["id"]

        try:
            node_instance = _create_single_node(
                node_data,
                registry,
                initial_params,
                enable_namespacing,
                template_resolution_mode,
                metrics_collector,
                trace_collector,
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
        initial_params: Parameters provided before execution
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
        logger.debug("JSON parsing failed", extra={"phase": "parsing"}, exc_info=True)
        raise

    # Step 1b: Resolve external file references before validation
    from pflow.core.file_resolver import get_base_dir, resolve_file_references

    base_dir = get_base_dir(initial_params)
    try:
        resolve_file_references(ir_dict, base_dir)
    except FileNotFoundError as e:
        raise CompilationError(
            message=str(e),
            phase="file_resolution",
            details={"error": str(e)},
            suggestion="Check that the file path is correct and relative to the workflow file.",
        ) from e

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
        logger.debug("Node instantiation failed", extra={"phase": "node_instantiation"}, exc_info=True)
        raise

    # Step 8: Wire nodes together
    try:
        _wire_nodes(nodes, ir_dict.get("edges", []))
    except CompilationError:
        logger.debug("Node wiring failed", extra={"phase": "flow_wiring"}, exc_info=True)
        raise

    # Step 9: Get start node
    try:
        start_node = _get_start_node(nodes, ir_dict)
    except CompilationError:
        logger.debug("Start node detection failed", extra={"phase": "start_detection"}, exc_info=True)
        raise

    # Step 10: Create and return Flow
    logger.debug("Creating Flow object", extra={"phase": "flow_creation"})
    flow = Flow(start=start_node)

    # Step 11: Wrap flow.run for per-execution setup and output population
    has_outputs = bool(ir_dict.get("outputs"))
    if has_outputs:
        from pflow.runtime.output_resolver import populate_declared_outputs

    original_run = flow.run

    def run_with_hooks(shared_storage: dict[str, Any]) -> str:
        """Run flow with per-execution setup and optional output population."""
        # Reset node visit counts for this execution cycle.
        # Visit counts track revisits WITHIN a single flow.run() (for loop
        # detection and cache invalidation). They must reset between runs
        # so that workflow resume state doesn't confuse cross-run revisits
        # with in-run loops.
        if "__execution__" in shared_storage and "node_visit_counts" in shared_storage["__execution__"]:
            shared_storage["__execution__"]["node_visit_counts"] = {}

        result = original_run(shared_storage)

        # Populate declared outputs on successful execution
        if has_outputs and not (result and isinstance(result, str) and result.startswith("error")):
            populate_declared_outputs(shared_storage, ir_dict)

        return str(result)

    flow.run = run_with_hooks  # type: ignore[method-assign]

    logger.info(
        "Compilation successful",
        extra={
            "phase": "complete",
            "node_count": len(nodes),
            "edge_count": len(ir_dict.get("edges", [])),
        },
    )

    return flow
