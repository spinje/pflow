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
import math
from typing import Any

from pflow.core.exceptions import CompilationError
from pflow.core.llm_config import get_default_workflow_model, get_model_not_configured_help
from pflow.core.node import Node
from pflow.core.prompt_cache import CacheBlockIR, CacheChunkIR
from pflow.core.workflow.gate_validation import check_approval_allowed
from pflow.core.workflow.loop_validation import check_loop_polarity
from pflow.registry import Registry
from pflow.runtime.engine import instrumentation
from pflow.runtime.engine.types import BatchConfig, CompiledWorkflow, LoopConfig, NodeConfig, TemplateConfig

from .compile_validation import _prepare_compilation
from .mcp_resolution import _check_registry_for_mcp, _create_mcp_error_suggestion, _parse_mcp_node_type
from .node_loader import import_node_class

# Set up module logger
logger = logging.getLogger(__name__)

# Keep direct-compile retry validation in lockstep with core.ir_schema's
# RETRY_CONFIG_SCHEMA; this path protects callers that bypass schema validation.
_RETRY_CONFIG_KEYS = frozenset({"max", "wait", "backoff"})


def _parse_ir_input(ir_json: str | dict[str, Any]) -> dict[str, Any]:
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

    retry_data = _validate_retry_config(node_data.get("retry"), node_id, node_type)
    if retry_data and isinstance(node_instance, Node):
        node_instance.max_retries = _coerce_retry_int(
            retry_data.get("max", node_instance.max_retries), "max", node_id, node_type
        )
        node_instance.wait = _coerce_retry_float(retry_data.get("wait", node_instance.wait), "wait", node_id, node_type)
        node_instance.backoff = _coerce_retry_backoff(retry_data.get("backoff", "fixed"), node_id, node_type)

    # Build batch config (None if not a batch node)
    batch_config = None
    batch_data = node_data.get("batch")
    if batch_data:
        batch_config = BatchConfig(
            items_template=batch_data["items"],
            item_alias=batch_data.get("as", "item"),
            error_handling=batch_data.get("error_handling", "fail_fast"),
            parallel=_coerce_bool(batch_data.get("parallel", False), "parallel"),
            max_concurrent=_coerce_int(batch_data.get("max_concurrent", 10), "max_concurrent", 10),
            max_retries=_coerce_int(batch_data.get("max_retries", 1), "max_retries", 1),
            retry_wait=_coerce_float(batch_data.get("retry_wait", 0.0), "retry_wait", 0.0),
        )

    # Build loop config (None if not a loop node). batch/loop are mutually exclusive.
    loop_config = _build_loop_config(node_data, batch_config is not None)

    # Build template config (None if no templates). A carry loop needs a
    # TemplateConfig even when round-1 inputs are all static literals, because
    # round 2+ swaps carried inputs into template_params before resolution.
    template_config = None
    if template_params or (loop_config is not None and loop_config.carry):
        template_config = TemplateConfig(
            template_params=template_params,
            static_params=static_params,
            expected_types=expected_types,
            resolution_mode=template_resolution_mode,
            optional_input_keys=optional_input_keys,
        )

    # Build NodeConfig
    node_config = NodeConfig(
        node_id=node_id,
        node_type_name=type(node_instance).__name__,
        template_config=template_config,
        batch_config=batch_config,
        namespaced=enable_namespacing,
        interface_metadata=interface_metadata,
        cache_enabled=node_data.get("cache", _default_cache_for_node_type(node_type)),
        prompt_cache_items=_extract_prompt_cache_items(node_data),
        prewarm=_extract_prewarm(node_data),
        loop_config=loop_config,
        approval=_extract_approval(node_data),
    )

    return node_instance, node_config


def _build_loop_config(node_data: dict[str, Any], has_batch: bool) -> LoopConfig | None:
    """Build a ``LoopConfig`` from the node's top-level ``loop:`` block (issue #445).

    Returns None when no ``loop:`` is declared. Enforces:
    - batch/loop mutual exclusion (both set → ``CompilationError``),
    - exactly one of ``while:`` / ``until:``,
    - literal ``max_iterations`` coerced to int and bounded to ``[1, MAX_NODE_VISITS]``;
      a ``${template}`` ``max_iterations`` is deferred to runtime (resolved at loop entry).
    """
    loop_data = node_data.get("loop")
    if loop_data is None:
        return None

    node_id = node_data.get("id")
    node_type = node_data.get("type")

    if has_batch:
        raise CompilationError(
            f"Node '{node_id}' declares both `batch:` and `loop:` — they are mutually exclusive.",
            phase="loop_config",
            node_id=node_id,
            node_type=node_type,
            suggestion="Use `batch:` for fixed-count fan-out, or `loop:` for stop-on-condition repetition — not both.",
        )

    if not isinstance(loop_data, dict):
        raise CompilationError(
            f"Node '{node_id}' `loop:` must be a mapping with a `while:` or `until:` condition.",
            phase="loop_config",
            node_id=node_id,
            node_type=node_type,
            suggestion=(
                "Declare `- loop:` with `while: ${node.output}` to continue while truthy, "
                "or `until: ${node.output}` to continue until truthy."
            ),
        )

    while_template, until_template = _extract_loop_polarity(loop_data, node_id, node_type)
    carry = _extract_loop_carry(loop_data, node_id, node_type)

    max_iterations: int | None = None
    max_iterations_template: str | None = None
    raw_max = loop_data.get("max_iterations")
    if isinstance(raw_max, str) and "${" in raw_max:
        max_iterations_template = raw_max
    elif raw_max is not None:
        max_iterations = _validate_loop_cap(_coerce_loop_cap_int(raw_max, node_id, node_type), node_id, node_type)

    return LoopConfig(
        # while_template / until_template are already `... or None` from _extract_loop_polarity.
        while_template=while_template,
        max_iterations=max_iterations,
        max_iterations_template=max_iterations_template,
        until_template=until_template,
        carry=dict(carry),
    )


def _extract_loop_polarity(
    loop_data: dict[str, Any], node_id: str | None, node_type: str | None
) -> tuple[str | None, str | None]:
    polarity_error = check_loop_polarity(loop_data)
    if polarity_error is not None:
        raise CompilationError(
            f"Node '{node_id}' {polarity_error}",
            phase="loop_config",
            node_id=node_id,
            node_type=node_type,
            suggestion=("Use exactly one polarity: `while: ${node.should_continue}` or `until: ${node.done}`."),
        )

    while_template = loop_data.get("while")
    until_template = loop_data.get("until")
    if while_template is not None and not isinstance(while_template, str):
        raise CompilationError(
            f"Node '{node_id}' `loop: while` must be a non-empty string template.",
            phase="loop_config",
            node_id=node_id,
            node_type=node_type,
            suggestion="Set `while: ${node.output}` — a single ${...} reference to this node's typed output.",
        )
    if until_template is not None and not isinstance(until_template, str):
        raise CompilationError(
            f"Node '{node_id}' `loop: until` must be a non-empty string template.",
            phase="loop_config",
            node_id=node_id,
            node_type=node_type,
            suggestion="Set `until: ${node.output}` — a single ${...} reference to this node's typed output.",
        )
    return while_template or None, until_template or None


def _extract_loop_carry(loop_data: dict[str, Any], node_id: str | None, node_type: str | None) -> dict[str, str]:
    carry = loop_data.get("carry") or {}
    if not isinstance(carry, dict):
        raise CompilationError(
            f"Node '{node_id}' `loop: carry` must be a mapping of input name to ${{node.output}} reference.",
            phase="loop_config",
            node_id=node_id,
            node_type=node_type,
            suggestion="Use `carry: {input_name: ${this-node.output_name}}`.",
        )
    for key, value in carry.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise CompilationError(
                f"Node '{node_id}' `loop: carry` entries must be string keys and string ${{...}} references.",
                phase="loop_config",
                node_id=node_id,
                node_type=node_type,
                suggestion="Use `carry: {input_name: ${this-node.output_name}}`.",
            )
    return dict(carry)


def _coerce_loop_cap_int(value: Any, node_id: str | None, node_type: str | None) -> int:
    """Coerce a literal ``max_iterations`` to int (bool/int/float/numeric-string).

    Loop-specific sibling of ``_coerce_int`` so the error message speaks ``loop:``
    rather than ``batch config``. Fails fast on non-numeric values.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            pass
    raise CompilationError(
        f"Node '{node_id}' `loop: max_iterations` must be a positive integer; got {value!r}.",
        phase="loop_config",
        node_id=node_id,
        node_type=node_type,
        suggestion="Set max_iterations to a positive integer (e.g., `max_iterations: 5`) or a ${template}.",
    )


def _validate_loop_cap(value: int, node_id: str | None, node_type: str | None) -> int:
    """Bound a resolved loop cap to ``[1, MAX_NODE_VISITS]``; raise ``CompilationError`` otherwise.

    Shared by the literal (compile-time) branch and — at runtime — the template
    branch, so a ``max_iterations: ${cap}`` resolving to 0/negative/over-cap fails
    the same way a literal would.
    """
    if value < 1:
        raise CompilationError(
            f"Node '{node_id}' `loop: max_iterations` must be >= 1; got {value}.",
            phase="loop_config",
            node_id=node_id,
            node_type=node_type,
            suggestion="Set max_iterations to a positive integer (the iteration cap).",
        )
    if value > instrumentation.MAX_NODE_VISITS:
        raise CompilationError(
            f"Node '{node_id}' `loop: max_iterations` ({value}) exceeds the hard visit cap "
            f"of {instrumentation.MAX_NODE_VISITS}.",
            phase="loop_config",
            node_id=node_id,
            node_type=node_type,
            suggestion=(
                f"Lower max_iterations to <= {instrumentation.MAX_NODE_VISITS}, or raise the cap via the "
                "PFLOW_MAX_NODE_VISITS environment variable."
            ),
        )
    return value


def _validate_retry_config(value: Any, node_id: str, node_type: str) -> dict[str, Any] | None:
    """Validate direct-compile retry config before optional application to Node instances."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CompilationError(
            f"Node '{node_id}' `retry:` must be a mapping.",
            phase="retry_config",
            node_id=node_id,
            node_type=node_type,
            suggestion="Declare `- retry:` with optional `max:`, `wait:`, and `backoff:` fields.",
        )

    unknown_keys = sorted(str(key) for key in value if key not in _RETRY_CONFIG_KEYS)
    if unknown_keys:
        keys = ", ".join(repr(key) for key in unknown_keys)
        raise CompilationError(
            f"Node '{node_id}' `retry:` contains unknown field(s): {keys}.",
            phase="retry_config",
            node_id=node_id,
            node_type=node_type,
            suggestion="Use only `max`, `wait`, and `backoff` under `retry:`.",
        )

    if "max" in value:
        _coerce_retry_int(value["max"], "max", node_id, node_type)
    if "wait" in value:
        _coerce_retry_float(value["wait"], "wait", node_id, node_type)
    if "backoff" in value:
        _coerce_retry_backoff(value["backoff"], node_id, node_type)
    return value


def _coerce_retry_int(value: Any, field: str, node_id: str, node_type: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CompilationError(
            f"Invalid retry config '{field}': expected an integer, got {value!r}",
            phase="retry_config",
            node_id=node_id,
            node_type=node_type,
        )
    coerced: int = value
    if coerced < 1 or coerced > 10:
        raise CompilationError(
            f"Invalid retry config '{field}': expected an integer from 1 to 10, got {value!r}",
            phase="retry_config",
            node_id=node_id,
            node_type=node_type,
        )
    return coerced


def _coerce_retry_float(value: Any, field: str, node_id: str, node_type: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompilationError(
            f"Invalid retry config '{field}': expected a number, got {value!r}",
            phase="retry_config",
            node_id=node_id,
            node_type=node_type,
        )
    coerced = float(value)
    if coerced < 0 or not math.isfinite(coerced):
        raise CompilationError(
            f"Invalid retry config '{field}': expected a finite non-negative number, got {value!r}",
            phase="retry_config",
            node_id=node_id,
            node_type=node_type,
        )
    return coerced


def _coerce_retry_backoff(value: Any, node_id: str, node_type: str) -> str:
    if value in ("fixed", "exponential"):
        return str(value)
    raise CompilationError(
        f"Invalid retry config 'backoff': expected 'fixed' or 'exponential', got {value!r}",
        phase="retry_config",
        node_id=node_id,
        node_type=node_type,
    )


def is_side_effecting(node_type: str) -> bool:
    """Whether re-running this node type may repeat an external effect (Task 164, Decision 4).

    The inverse of "safe to memo-cache by default": only ``llm`` is pure (its
    output is a deterministic-enough function of its inputs, and caching it is
    the default). Every other registry type either side-effects (shell, code,
    agent, file ops, mcp) or reads external state that may have changed
    (http) — so a resume that re-runs such a node K gives at-least-once
    execution of its effect, which the confirm/``--force`` policy governs.

    Public predicate (spec Decision 9): CLI resume code calls THIS, never
    imports the cache-default helper. Consumes IR REGISTRY type names
    (``"llm"``/``"shell"``/...), NOT trace-event Python class names
    (``"LLMNode"``) — see the ResumeSource vocabulary rule.
    """
    return node_type != "llm"


def _default_cache_for_node_type(node_type: str) -> bool:
    """Whether a node defaults to memo-cache-on when no `cache:` field is set.

    Only `llm` caches by default. Every other node type is either side-effecting
    (shell, code, agent, file ops, mcp) or reads external state (http),
    and silently caching their output across runs is unsafe — especially in
    iteration loops where declared inputs may not change but external state has.
    """
    return not is_side_effecting(node_type)


def _extract_prompt_cache_items(node_data: dict[str, Any]) -> tuple[str, ...]:
    """Coerce the per-node ``prompt_cache:`` field into an immutable tuple of strings.

    Schema validation catches malformed shape via the WorkflowValidator path,
    but ``compile_workflow(ir_dict, registry)`` can be called directly bypassing
    schema. Round-6 hardening: explicit ``isinstance`` precondition rejects the
    iterable-but-wrong-shape case (``"concept"`` would silently splat into 7
    single-character chunks via ``tuple(str)``).
    """
    raw = node_data.get("prompt_cache")
    if raw is None or raw == []:
        return ()
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise CompilationError(
            f"prompt_cache must be a list of strings; got {type(raw).__name__}: {raw!r}",
            phase="validation",
            node_id=node_data.get("id"),
            node_type=node_data.get("type"),
            suggestion="Set prompt_cache to a list of cache chunk identifiers (e.g., `prompt_cache: [concept, concept_brief]`).",
        )
    return tuple(raw)


def _extract_prewarm(node_data: dict[str, Any]) -> bool:
    """Coerce ``prewarm:`` into a strict bool. Rejects truthy ints (1/0) since
    ``isinstance(True, int)`` is True — the explicit ``bool`` check is required."""
    raw = node_data.get("prewarm")
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise CompilationError(
            f"prewarm must be a bool; got {type(raw).__name__}: {raw!r}",
            phase="validation",
            node_id=node_data.get("id"),
            node_type=node_data.get("type"),
            suggestion="Set prewarm to true or false (e.g., `prewarm: true`).",
        )
    return raw


def _extract_approval(node_data: dict[str, Any]) -> bool:
    """Coerce ``approval:`` into a bool. Only the literal string ``"required"`` is
    accepted (schema enforces the enum; this is the compile-path mirror for
    programmatic IRs that skip schema validation). Also enforces the batch
    exclusion via the shared ``check_approval_allowed`` rule so the run path
    fails fast even when validation was bypassed."""
    raw = node_data.get("approval")
    if raw is None:
        return False
    if raw != "required":
        raise CompilationError(
            f"approval must be the string 'required'; got {type(raw).__name__}: {raw!r}",
            phase="validation",
            node_id=node_data.get("id"),
            node_type=node_data.get("type"),
            suggestion="The only supported value is `approval: required`.",
        )
    batch_error = check_approval_allowed(node_data)
    if batch_error is not None:
        raise CompilationError(
            batch_error,
            phase="validation",
            node_id=node_data.get("id"),
            node_type=node_data.get("type"),
            suggestion="Move `approval: required` to the step before or after the batch.",
        )
    return True


def _build_cache_block(ir_dict: dict[str, Any]) -> CacheBlockIR | None:
    """Build the workflow-level ``CacheBlockIR`` from the IR's top-level ``cache`` field.

    Returns None when no ``## Cache`` block was declared. Schema enforces shape
    upstream; this builder assumes well-formed input but still copes gracefully
    with absent ``ttl`` / ``items`` keys.
    """
    cache_ir = ir_dict.get("cache")
    if cache_ir is None:
        return None
    if not isinstance(cache_ir, dict):
        raise CompilationError(
            f"Top-level `cache` must be a mapping; got {type(cache_ir).__name__}: {cache_ir!r}",
            phase="validation",
            suggestion="Declare ## Cache with `- ttl:` and a ```cache code block (see pflow guide prompt-caching).",
        )
    items = tuple(_build_cache_chunk(item) for item in cache_ir.get("items", []))
    return CacheBlockIR(
        ttl=cache_ir.get("ttl"),
        items=items,
        source_line=int(cache_ir.get("_source_line", 0) or 0),
    )


def _build_cache_chunk(item: dict[str, Any]) -> CacheChunkIR:
    """Build one frozen ``CacheChunkIR`` from a parsed cache-block item dict."""
    return CacheChunkIR(
        name=item["name"],
        var_expr=item["var"],
        prose_before=item["prose_before"],
        source_line=int(item.get("_source_line", 0) or 0),
    )


def _coerce_bool(value: Any, field: str = "parallel") -> bool:
    """Coerce value to boolean. Accepts bool, common string patterns, int 0/1."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        lower = value.lower().strip()
        if lower in ("true", "1", "yes"):
            return True
        if lower in ("false", "0", "no", ""):
            return False
        raise CompilationError(
            f"Invalid batch config '{field}': '{value}' is not a valid boolean",
            phase="batch_config",
            suggestion="Use true/false, yes/no, or 1/0",
        )
    raise CompilationError(
        f"Invalid batch config '{field}': expected boolean, got {type(value).__name__}",
        phase="batch_config",
        suggestion="Use true or false",
    )


def _coerce_int(value: Any, field: str, default: int) -> int:
    """Coerce to int. Accepts int, float (truncates), numeric strings. Fails on garbage."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            raise CompilationError(
                f"Invalid batch config '{field}': '{value}' is not a valid integer",
                phase="batch_config",
                suggestion=f"Use an integer value (default is {default})",
            ) from None
    raise CompilationError(
        f"Invalid batch config '{field}': expected integer, got {type(value).__name__}",
        phase="batch_config",
        suggestion=f"Use an integer value (default is {default})",
    )


def _coerce_float(value: Any, field: str, default: float) -> float:
    """Coerce to float. Accepts int, float, numeric strings. Fails on garbage."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            raise CompilationError(
                f"Invalid batch config '{field}': '{value}' is not a valid number",
                phase="batch_config",
                suggestion=f"Use a numeric value (default is {default})",
            ) from None
    raise CompilationError(
        f"Invalid batch config '{field}': expected number, got {type(value).__name__}",
        phase="batch_config",
        suggestion=f"Use a numeric value (default is {default})",
    )


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
    configs: dict[str, NodeConfig] = {}
    initial_params = initial_params or {}

    enable_namespacing = ir_dict.get("enable_namespacing", True)
    template_resolution_mode = initial_params.get("__template_resolution_mode__", "strict")

    for node_data in ir_dict["nodes"]:
        node_id = node_data["id"]
        try:
            node_instance, node_config = _create_node_and_config(
                node_data,
                registry,
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
    ir_json: str | dict[str, Any],
    registry: Registry,
    initial_params: dict[str, Any] | None = None,
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
        cache_block=_build_cache_block(ir_dict),
    )
