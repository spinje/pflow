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

from pflow.core.exceptions import CompilationError
from pflow.core.llm_config import get_default_workflow_model, get_model_not_configured_help
from pflow.registry import Registry
from pflow.runtime.engine.types import BatchConfig, CompiledWorkflow, NodeConfig, TemplateConfig

from .compile_validation import _prepare_compilation
from .mcp_resolution import _check_registry_for_mcp, _create_mcp_error_suggestion, _parse_mcp_node_type
from .node_loader import import_node_class

# Set up module logger
logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# New compilation pipeline: compile_workflow() + engine
# ---------------------------------------------------------------------------


def _create_node_and_config(
    node_data: dict[str, Any],
    registry: Registry,
    initial_params: dict[str, Any],
    enable_namespacing: bool,
    template_resolution_mode: str,
) -> tuple[Any, NodeConfig]:
    """Create a bare node instance and its NodeConfig.

    Unlike _create_single_node, this does NOT apply any wrappers.
    The engine handles all runtime concerns directly.

    Returns:
        (bare_node, NodeConfig)
    """
    from pflow.runtime.engine.template_resolution import build_type_cache, split_params

    node_id = node_data["id"]
    node_type = node_data["type"]
    params = node_data.get("params", {})

    # Thread source-line metadata into params
    source_lines = node_data.get("_source_lines")
    if source_lines:
        params = {**params, **{f"_{k}_source_line": v for k, v in source_lines.items()}}

    # Inject default model for LLM nodes
    if node_type == "llm" and "model" not in params:
        default_model = get_default_workflow_model()
        if default_model:
            params = {**params, "model": default_model}
        else:
            raise CompilationError(
                message=f"No model configured for LLM node '{node_id}'",
                phase="node_instantiation",
                node_id=node_id,
                node_type=node_type,
                suggestion=get_model_not_configured_help(node_id),
            )

    # Import and instantiate bare node
    node_class = import_node_class(node_type, registry)
    node_instance: Any = node_class()

    # Set node_id on the bare node (engine needs this for config lookup)
    node_instance.node_id = node_id

    # Extract interface metadata from registry
    nodes = registry.load()
    node_metadata = nodes.get(node_type, {})
    interface_metadata = node_metadata.get("interface")

    # Extract optional input keys for code nodes
    optional_input_keys: set[str] = set()
    if node_type == "code" and "code" in params and isinstance(params.get("inputs"), dict):
        from pflow.nodes.python.python_code import extract_optional_input_keys

        input_keys = set(params["inputs"].keys())
        optional_input_keys = extract_optional_input_keys(params["code"], input_keys) or set()

    # Inject special parameters
    params = inject_special_parameters(node_type, node_id, params, registry)

    # Build type cache and split params
    expected_types = build_type_cache(interface_metadata)
    template_params, static_params = split_params(params, expected_types)

    # Set ONLY static params on bare node at compile time
    if static_params:
        node_instance.set_params(static_params)

    # Build template config (None if no templates)
    template_config = None
    if template_params:
        template_config = TemplateConfig(
            template_params=template_params,
            static_params=static_params,
            expected_types=expected_types,
            resolution_mode=template_resolution_mode,
            optional_input_keys=optional_input_keys,
        )

    # Build batch config (None if not a batch node)
    batch_config = None
    batch_data = node_data.get("batch")
    if batch_data:
        batch_config = BatchConfig(
            items_template=batch_data["items"],
            item_alias=batch_data.get("as", "item"),
            error_handling=batch_data.get("error_handling", "fail_fast"),
            parallel=_coerce_bool(batch_data.get("parallel", False)),
            max_concurrent=_coerce_int(batch_data.get("max_concurrent", 10), default=10),
            max_retries=_coerce_int(batch_data.get("max_retries", 1), default=1),
            retry_wait=_coerce_float(batch_data.get("retry_wait", 0.0), default=0.0),
        )

    # Build NodeConfig
    node_config = NodeConfig(
        node_id=node_id,
        node_type_name=type(node_instance).__name__,
        template_config=template_config,
        batch_config=batch_config,
        namespaced=enable_namespacing,
        interface_metadata=interface_metadata,
    )

    return node_instance, node_config


def _coerce_bool(value: Any) -> bool:
    """Coerce value to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower().strip() in ("true", "1", "yes")
    return bool(value)


def _coerce_int(value: Any, default: int = 0) -> int:
    """Coerce value to integer. Returns default on failure."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    """Coerce value to float. Returns default on failure."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _instantiate_nodes_for_workflow(
    ir_dict: dict[str, Any],
    registry: Registry,
    initial_params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, NodeConfig]]:
    """Instantiate bare nodes and build NodeConfigs.

    Returns:
        (nodes_dict, configs_dict)
    """
    nodes: dict[str, Any] = {}
    configs: dict[str, Any] = {}
    initial_params = initial_params or {}

    enable_namespacing = ir_dict.get("enable_namespacing", True)
    template_resolution_mode = initial_params.get("__template_resolution_mode__", "strict")

    for node_data in ir_dict["nodes"]:
        node_id = node_data["id"]
        try:
            node_instance, node_config = _create_node_and_config(
                node_data,
                registry,
                initial_params,
                enable_namespacing,
                template_resolution_mode,
            )
            nodes[node_id] = node_instance
            configs[node_id] = node_config
        except CompilationError as e:
            if not e.node_id:
                e.node_id = node_id
            raise

    return nodes, configs


def compile_workflow(
    ir_json: Union[str, dict[str, Any]],
    registry: Registry,
    initial_params: Optional[dict[str, Any]] = None,
) -> CompiledWorkflow:
    """Compile IR to CompiledWorkflow. No runtime state baked in.

    Args:
        ir_json: JSON string or dict representing the workflow IR
        registry: Registry instance for node metadata lookup
        initial_params: Parameters provided before execution

    Returns:
        CompiledWorkflow with bare nodes + per-node configs
    """
    initial_params = initial_params or {}

    # Step 1: Parse input
    ir_dict = _parse_ir_input(ir_json)

    # Step 2: Resolve external file references
    import yaml

    from pflow.core.file_resolver import get_base_dir, resolve_file_references

    base_dir = get_base_dir(initial_params)
    try:
        resolve_file_references(ir_dict, base_dir)
    except (FileNotFoundError, yaml.YAMLError) as e:
        raise CompilationError(
            message=str(e),
            phase="file_resolution",
            details={"error": str(e)},
            suggestion="Check that the file path is correct and relative to the workflow file.",
        ) from e

    # Step 3: Prepare compilation (validate, resolve inputs)
    initial_params, _warnings, resolved_defaults, env_param_names = _prepare_compilation(
        ir_dict, registry, initial_params
    )

    template_resolution_mode = initial_params.get("__template_resolution_mode__", "strict")

    # Step 4: Instantiate bare nodes + configs
    nodes, configs = _instantiate_nodes_for_workflow(ir_dict, registry, initial_params)

    # Step 5: Wire nodes together
    _wire_nodes(nodes, ir_dict.get("edges", []))

    # Step 6: Get start node
    start_node = _get_start_node(nodes, ir_dict)

    # Step 7: Build CompiledWorkflow
    return CompiledWorkflow(
        start_node=start_node,
        node_configs=configs,
        outputs=ir_dict.get("outputs", {}),
        resolved_defaults=resolved_defaults,
        env_param_names=env_param_names,
        template_resolution_mode=template_resolution_mode,
    )
