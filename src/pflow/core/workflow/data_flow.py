"""Data flow validation for workflow execution order and dependencies.

This module ensures that workflows have correct execution order and that
all data dependencies are satisfied before nodes execute.
"""

import logging
import re
from typing import Any, Optional

from pflow.core.cache_ttl import (
    build_unsupported_cache_ttl_diagnostic,
    is_cache_ttl_supported_by_provider,
    parse_cache_ttl,
)
from pflow.core.diagnostic import (
    CACHE_FAILURE_CATEGORY,
    CACHE_WARNING_CATEGORY,
    Diagnostic,
    Severity,
)
from pflow.core.suggestion_utils import find_similar_items
from pflow.core.types import is_template_reserved_internal_key
from pflow.runtime.template_resolver import TemplateResolver

logger = logging.getLogger(__name__)

# Positive match for pflow variable paths (e.g., "node", "node.field", "node[0].field").
# Uses TemplateResolver._VAR_NAME_PATTERN as the canonical definition of valid pflow
# variable names. This is a private attribute — if the pattern changes there, it must
# change here too.
_PFLOW_VAR_RE = re.compile(rf"^{TemplateResolver._VAR_NAME_PATTERN}$")


class CycleError(Exception):
    """Raised when circular dependency is detected in workflow."""

    def __init__(self, nodes_in_cycle: set[str]) -> None:
        self.nodes_in_cycle = sorted(nodes_in_cycle)
        super().__init__(f"Circular dependency detected involving nodes: {', '.join(self.nodes_in_cycle)}")


def build_execution_order(workflow_ir: dict[str, Any]) -> list[str]:
    """Build the execution order of nodes based on edges using topological sort.

    Args:
        workflow_ir: The workflow IR containing nodes and edges

    Returns:
        List of node IDs in execution order

    Raises:
        CycleError: If circular dependency is detected
    """
    edges = workflow_ir.get("edges", [])
    node_list = workflow_ir.get("nodes", [])
    nodes = {node["id"] for node in node_list}

    # Node positions for determining edge direction
    node_positions = {node["id"]: i for i, node in enumerate(node_list)}

    # Build adjacency list
    graph: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    in_degree: dict[str, int] = dict.fromkeys(nodes, 0)

    for edge in edges:
        if edge.get("from") and edge.get("to"):
            # Skip edges referencing nodes not in the graph (caught by wiring step later)
            if edge["from"] not in nodes or edge["to"] not in nodes:
                continue

            action = edge.get("action")
            source_pos = node_positions.get(edge["from"], -1)
            target_pos = node_positions.get(edge["to"], -1)

            # Include edge if:
            # - No action (document-order edges — always forward)
            # - Any edge going forward (branch targets, error handlers, skip-ahead)
            # Exclude backward edges (retry loops, error-to-earlier) to avoid cycles.
            if action is None or source_pos < target_pos:
                graph[edge["from"]].append(edge["to"])
                in_degree[edge["to"]] += 1

    # Topological sort using Kahn's algorithm.
    # Use document order (node_positions) as tiebreaker for equal in-degree
    # to give deterministic results and honor the author's intended order
    # for disconnected components (e.g., branch targets with no incoming edges).
    queue = sorted(
        [node for node in nodes if in_degree[node] == 0],
        key=lambda n: node_positions.get(n, 0),
    )
    order = []

    while queue:
        node = queue.pop(0)
        order.append(node)
        new_ready = []
        for neighbor in graph.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                new_ready.append(neighbor)
        # Insert newly ready nodes in document order
        if new_ready:
            new_ready.sort(key=lambda n: node_positions.get(n, 0))
            queue.extend(new_ready)

    # Check for cycles
    if len(order) != len(nodes):
        # Find nodes involved in cycle
        remaining = nodes - set(order)
        raise CycleError(remaining)

    return order


def _check_forward_reference(
    node_id: str,
    param_name: str,
    ref_node_id: str,
    node_position: int,
    node_positions: dict[str, int],
    loop_forward_limits: dict[str, int],
    loop_node_ids: set[str],
) -> Optional[Diagnostic]:
    """Check if a node reference is a disallowed forward reference.

    Returns error diagnostic if ref_node_id comes after node_id in execution order
    and is not part of a valid loop pattern. Returns None if the reference is valid.
    """
    # Loop self-reference carve-out (issue #445): a ``loop:`` node's ``while:``
    # condition (and any self-referencing param) legitimately reads its own
    # just-completed output via engine re-entry — it is NOT a forward reference.
    # Scoped to ``ref_node_id == node_id`` so a ``while:`` pointing at a DIFFERENT
    # downstream node is still rejected.
    if ref_node_id == node_id and node_id in loop_node_ids:
        return None
    if ref_node_id not in node_positions:
        return None
    ref_position = node_positions[ref_node_id]
    if ref_position < node_position:
        return None
    # Allow forward references for loop targets — backward edges with actions
    # indicate valid PocketFlow retry/loop patterns.
    max_allowed = loop_forward_limits.get(node_id)
    if max_allowed is not None and ref_position <= max_allowed:
        return None
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' references '{ref_node_id}' in parameter '{param_name}', "
            f"but '{ref_node_id}' comes after this node in execution order "
            f"(position {ref_position} >= {node_position})."
        ),
        suggestions=[f"Reorder nodes so '{ref_node_id}' appears before '{node_id}'."],
        context={
            "category": "validation",
            "path": f"nodes[id={node_id}].params.{param_name}",
            "referenced_node": ref_node_id,
        },
    )


def _reserved_internal_key_diagnostic(
    ref: str,
    ref_node_id: str,
    node_id: str,
    param_name: str,
    *,
    has_path: bool,
) -> Optional[Diagnostic]:
    """Targeted error for ``${__execution__}`` / ``${__index__.x}`` references.

    Catches reserved double-underscore keys in BOTH bare (``${__cache_hits__}``)
    and path (``${__execution__.x}``) forms. The ``__index__`` path-access error
    only fires when ``has_path`` — bare ``${__index__}`` is the one valid
    reserved reference (the current batch item index).

    Returns None when ``ref_node_id`` is not a reserved internal key (the caller
    then falls through to the generic "non-existent node" path).

    Validator-only by design: at runtime ``TemplateResolver`` resolves against
    ``dict(shared)``, which DOES contain ``__execution__`` — so a workflow that
    skipped validation could observe the back door. That is intentional: all
    production ``compile_workflow`` callers route through
    ``_validate_data_flow_at_compile_time``, so an invalid workflow never reaches
    runtime. One source of truth beats a duplicate runtime guard.
    """
    path = f"nodes[id={node_id}].params.{param_name}"

    if is_template_reserved_internal_key(ref_node_id):
        return Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Validation Error",
            node_id=node_id,
            message=(
                f"Template '${{{ref_node_id}}}' in node '{node_id}' "
                f"(parameter '{param_name}') is not available. "
                f"Names starting and ending with double-underscore are reserved by pflow."
            ),
            suggestions=[
                "Only `${__index__}` (the current batch item index) is available in templates.",
                "To track iteration count across loop visits, maintain a counter explicitly: "
                "a checker node returns `prior + 1`, seeded from `${checker.result ?? 0}` "
                "on the first visit. See `pflow guide branching` -> Loops for a worked example.",
            ],
            context={"category": "validation", "path": path},
        )

    if ref_node_id == "__index__" and has_path:
        path_remainder = ref[len(ref_node_id) :].lstrip(".")
        return Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Validation Error",
            node_id=node_id,
            message=(
                f"Template '${{__index__.{path_remainder}}}' in node '{node_id}' "
                f"(parameter '{param_name}') accesses fields on `__index__`, "
                f"which is an integer (the current batch item index)."
            ),
            suggestions=[
                "Use bare `${__index__}` for the item position number.",
                "For batch item data, use `${item}` or `${item.field}` on a batch node.",
            ],
            context={"category": "validation", "path": path},
        )

    if ref_node_id == "__iteration__" and has_path:
        path_remainder = ref[len(ref_node_id) :].lstrip(".")
        return Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Validation Error",
            node_id=node_id,
            message=(
                f"Template '${{__iteration__.{path_remainder}}}' in node '{node_id}' "
                f"(parameter '{param_name}') accesses fields on `__iteration__`, "
                f"which is an integer (the 1-based loop iteration count)."
            ),
            suggestions=[
                "Use bare `${__iteration__}` for the current loop iteration number.",
            ],
            context={"category": "validation", "path": path},
        )

    return None


def _validate_template_reference(  # noqa: C901
    ref: str,
    node_id: str,
    param_name: str,
    node_position: int,
    nodes_by_id: dict[str, Any],
    node_positions: dict[str, int],
    declared_inputs: set[str],
    loop_forward_limits: dict[str, int],
    loop_node_ids: set[str],
    check_inputs: bool,
) -> Optional[Diagnostic]:
    """Validate a single template reference.

    Args:
        ref: The template reference (e.g., "node1.output" or "input_param")
        node_id: ID of the node containing the reference
        param_name: Parameter name containing the reference
        node_position: Position of the current node in execution order
        nodes_by_id: Mapping of node IDs to node objects
        node_positions: Mapping of node IDs to execution positions
        declared_inputs: All valid simple refs for this node context
            (workflow inputs + batch aliases + node-level params.inputs keys)
        loop_forward_limits: For loop targets, the max position they can reference
        check_inputs: Whether to validate undefined input references

    Returns:
        Error diagnostic if invalid, None if valid
    """
    # Only validate refs that match pflow variable syntax. Non-matching refs
    # are bash syntax (${#count}, ${var:-default}, ${array[@]}), or truncated
    # nested templates (${results[${__index__}) — skip them.
    if not _PFLOW_VAR_RE.match(ref):
        return None

    # Extract root identifier (before first . or [)
    root = TemplateResolver.extract_root_node_id(ref)
    has_path = root != ref

    # Reserved internal keys (e.g. ${__execution__} or ${__execution__.x}) get a
    # targeted error before any other branch — both bare and path forms, so a bare
    # ${__cache_hits__} doesn't fall through to the generic "undefined input"
    # message. The __index__ path-access error stays inside the has_path branch
    # (bare ${__index__} is valid). Validator-only by design — see
    # _reserved_internal_key_diagnostic for the runtime-asymmetry note.
    reserved = _reserved_internal_key_diagnostic(ref, root, node_id, param_name, has_path=has_path)
    if reserved is not None:
        return reserved

    if has_path:  # Node output reference like ${node1.output} or ${data[0].field}
        ref_node_id = root

        # Check if referenced node exists (also allow batch aliases like "item")
        if ref_node_id not in nodes_by_id and ref_node_id not in declared_inputs:
            if not check_inputs:
                return None  # Could be a runtime param — compiler lacks context
            candidates = sorted(set(nodes_by_id.keys()) | declared_inputs)
            similar = find_similar_items(ref_node_id, candidates, max_results=3, method="fuzzy")
            context: dict[str, Any] = {
                "category": "validation",
                "path": f"nodes[id={node_id}].params.{param_name}",
                "available_fields": sorted(nodes_by_id.keys()),
                "available_fields_total": len(nodes_by_id),
                "available_fields_label": "nodes",
            }
            if similar:
                context["similar_names"] = similar
            return Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="Validation Error",
                node_id=node_id,
                message=f"Node '{node_id}' references non-existent node '{ref_node_id}' in parameter '{param_name}'.",
                suggestions=[f"Did you mean '{similar[0]}'?"] if similar else None,
                context=context,
            )
        # Check if referenced node comes before this node
        return _check_forward_reference(
            node_id,
            param_name,
            ref_node_id,
            node_position,
            node_positions,
            loop_forward_limits,
            loop_node_ids,
        )

    # Input parameter reference like ${repo_name}
    if not check_inputs:
        return None
    if ref not in declared_inputs:
        close_matches = [inp for inp in declared_inputs if inp.lower() == ref.lower()]
        if close_matches:
            return Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="Validation Error",
                node_id=node_id,
                message=f"Node '{node_id}' references undefined input '${{{ref}}}' in parameter '{param_name}'.",
                suggestions=[f"Did you mean '${{{close_matches[0]}}}'?"],
                context={
                    "category": "validation",
                    "path": f"nodes[id={node_id}].params.{param_name}",
                    "template": f"${{{ref}}}",
                    "similar_names": [f"${{{match}}}" for match in close_matches[:3]],
                },
            )
        if not declared_inputs:
            return Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="Validation Error",
                node_id=node_id,
                message=(
                    f"Node '{node_id}' references '${{{ref}}}' in parameter '{param_name}' "
                    f"but no inputs are declared in this workflow."
                ),
                suggestions=[
                    f"Declare '{ref}' under '## Inputs' or use a node output reference like ${{node_id.field}}."
                ],
                context={
                    "category": "validation",
                    "path": f"nodes[id={node_id}].params.{param_name}",
                    "template": f"${{{ref}}}",
                },
            )
        sorted_inputs = sorted(declared_inputs)
        return Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Validation Error",
            node_id=node_id,
            message=f"Node '{node_id}' references undefined input '${{{ref}}}' in parameter '{param_name}'.",
            context={
                "category": "validation",
                "path": f"nodes[id={node_id}].params.{param_name}",
                "template": f"${{{ref}}}",
                "available_fields": sorted_inputs,
                "available_fields_total": len(sorted_inputs),
                "available_fields_label": "inputs",
            },
        )
    return None


def validate_data_flow(
    workflow_ir: dict[str, Any],
    check_inputs: bool = True,
    workflow_path: Optional[str] = None,
) -> list[Diagnostic]:
    """Validate that data flows correctly between nodes.

    This function checks:
    - Circular dependencies in the workflow (always)
    - Forward references to nodes that come later in execution order (always)
    - References to non-existent nodes (always when check_inputs=True;
      skips ambiguous refs when False — they could be runtime params)
    - References to undefined input parameters (only when check_inputs=True)

    The check_inputs parameter controls semantic checks that depend on knowing
    all available variable sources. The compiler passes False because it has
    initial_params that legitimately contain variables not declared in IR inputs.
    The pre-execution WorkflowValidator passes True (default) because it runs
    after all variable sources are known.

    Args:
        workflow_ir: The workflow IR to validate
        check_inputs: Whether to validate undefined input references
        workflow_path: Path to the workflow file being validated. Threaded into
            cache.* diagnostics that route through ``make_diagnostic`` (which
            requires ``affected_workflow`` for workflow-scope correctness when
            same-id nodes appear in multiple workflows). When ``None`` the new
            cache.prompt-body-* checks fall back to a stable placeholder string
            so synthetic-IR tests still get coverage.

    Returns:
        List of validation diagnostics (empty if valid)
    """
    diagnostics: list[Diagnostic] = []

    nodes_by_id = {node["id"]: node for node in workflow_ir.get("nodes", [])}
    declared_inputs = set(workflow_ir.get("inputs", {}).keys())

    # Extract batch item aliases - these are valid variable references within batch nodes
    # Note: This is a permissive check - we allow batch aliases globally rather than
    # tracking which node each template belongs to. Runtime will catch invalid usage.
    batch_item_aliases: set[str] = set()
    has_batch_nodes = False
    for node in workflow_ir.get("nodes", []):
        batch_config = node.get("batch")
        if batch_config:
            has_batch_nodes = True
            item_alias = batch_config.get("as", "item")
            batch_item_aliases.add(item_alias)

    # Loop nodes (issue #445): node ids carrying a top-level ``loop:`` block.
    # Used for the self-reference carve-out in ``_check_forward_reference`` and
    # to gate ``__iteration__`` registration.
    loop_node_ids: set[str] = {
        node["id"] for node in workflow_ir.get("nodes", []) if node.get("loop") and node.get("id")
    }

    # Combine declared inputs with batch item aliases for validation
    valid_simple_refs = declared_inputs | batch_item_aliases

    # __index__ is auto-injected in batch contexts (0-based batch item index)
    if has_batch_nodes:
        valid_simple_refs.add("__index__")

    # __iteration__ is auto-injected in loop bodies (1-based iteration count).
    # Registered globally (like __index__) when any loop node exists.
    if loop_node_ids:
        valid_simple_refs.add("__iteration__")

    diagnostics.extend(_validate_loop_node_combos(workflow_ir))

    # Build execution order
    try:
        node_order = build_execution_order(workflow_ir)
        node_positions = {node_id: i for i, node_id in enumerate(node_order)}
    except CycleError as e:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="Validation Error",
                message=f"Circular dependency detected involving nodes: {', '.join(e.nodes_in_cycle)}",
                suggestions=["Remove or reorder edges to break the cycle."],
                context={
                    "category": "validation",
                    "cycle_nodes": e.nodes_in_cycle,
                },
            )
        )
        return diagnostics

    # Compute loop forward limits: for each backward edge B→A (with action),
    # node A can reference nodes up to B's position (valid in subsequent iterations).
    loop_forward_limits: dict[str, int] = {}
    for edge in workflow_ir.get("edges", []):
        if edge.get("from") and edge.get("to"):
            action = edge.get("action")
            source_pos = node_positions.get(edge["from"], -1)
            target_pos = node_positions.get(edge["to"], -1)
            if action is not None and source_pos >= target_pos:
                target = edge["to"]
                loop_forward_limits[target] = max(loop_forward_limits.get(target, 0), source_pos)

    # Check each node's parameter references
    for node in workflow_ir.get("nodes", []):
        node_id = node.get("id")
        node_position = node_positions.get(node_id, -1)
        _validate_node_params(
            node,
            node_id,
            node_position,
            nodes_by_id,
            node_positions,
            valid_simple_refs,
            loop_forward_limits,
            loop_node_ids,
            check_inputs,
            diagnostics,
        )

    # Cache-block validation (Task 159): ## Cache references, prompt_cache: order,
    # invalid-on-non-llm, unused chunks, batch-scoped rejection, prompt-body
    # overlap with cached chunks. Runs at the SAME tier as the per-node template
    # validation so both validation entry points (WorkflowValidator +
    # compile_validation) pick it up via the shared call site.
    _validate_cache_block(
        workflow_ir,
        nodes_by_id,
        declared_inputs,
        batch_item_aliases,
        diagnostics,
        workflow_path=workflow_path,
    )

    # LLM parameter-composition validation (Task 159 Stage 2 follow-up):
    # Anthropic temperature=1.0 + extended thinking constraint. Catches the
    # workflow-level error class before it crashes at runtime. See
    # llm.thinking-temperature-mismatch in CACHE_WARNING_CATALOG.
    _validate_thinking_temperature_compatibility(
        workflow_ir,
        diagnostics,
        workflow_path=workflow_path,
    )

    return diagnostics


def _validate_loop_node_combos(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
    """Reject unsupported `loop:` combinations (issue #445).

    - **`loop:` + `enable_namespacing: false`** — the `while:` condition reads the
      loop node's OWN output via `${node.field}`, which only resolves when outputs
      are namespaced under `shared[node_id]`. With namespacing off a node writes to
      root, so the self-reference never resolves and the loop would silently run a
      single pass. Reject up front rather than letting it surface as a confusing
      generic "no valid source".
    - **`loop:` + `storage_mode: shared`** — shared storage writes the child's
      output (and the engine's `__iteration__` / `__execution__` keys) straight to
      the parent root, so loop re-entry would collide.
    """
    # Deferred import: the literal-cap check below compares against the live,
    # env-overridable MAX_NODE_VISITS module attribute (so a test monkeypatching it
    # affects this path too), and a function-local import avoids any module-load
    # cycle from core -> runtime.engine.
    from pflow.runtime.engine import instrumentation

    diagnostics: list[Diagnostic] = []
    namespacing_on = workflow_ir.get("enable_namespacing", True)
    for node in workflow_ir.get("nodes", []):
        loop_data = node.get("loop")
        if not loop_data:
            continue
        node_id = node.get("id")
        if not namespacing_on:
            diagnostics.append(_make_loop_namespacing_diagnostic(node_id))
        params = node.get("params")
        if isinstance(params, dict) and params.get("storage_mode") == "shared":
            diagnostics.append(_make_loop_shared_storage_diagnostic(node_id))
        # batch + loop are mutually exclusive. The compiler enforces this fail-fast in
        # _build_loop_config, but that only runs on the run path — duplicate it here so
        # `pflow save` / --validate-only (which never compile) catch it too.
        if node.get("batch"):
            diagnostics.append(_make_loop_batch_exclusion_diagnostic(node_id))
        # Literal max_iterations over the hard visit cap. The compiler bounds this for
        # the run path; mirror it here so the validate path agrees (the ${template}
        # branch is bounded at runtime in resolve_loop_cap). Schema already enforces the
        # >= 1 lower bound and integer-ness of the literal branch. `type(...) is int`
        # excludes bool (a bool cap is a separate schema concern, not an over-cap one).
        if isinstance(loop_data, dict):
            raw_max = loop_data.get("max_iterations")
            if type(raw_max) is int and raw_max > instrumentation.MAX_NODE_VISITS:
                diagnostics.append(_make_loop_cap_diagnostic(node_id, raw_max, instrumentation.MAX_NODE_VISITS))
    return diagnostics


def _make_loop_namespacing_diagnostic(node_id: Optional[str]) -> Diagnostic:
    """Reject `loop:` when `enable_namespacing: false` (issue #445).

    The `while:` self-reference (`${node.output}`) only resolves under namespacing;
    without it the loop silently single-passes. Surface the real cause up front.
    """
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' uses `loop:` but the workflow sets `enable_namespacing: false`. "
            f"A loop's `while:` condition reads the node's own output (${{{node_id}.field}}), which "
            f"only resolves when outputs are namespaced — otherwise the loop would silently run once."
        ),
        suggestions=[
            "Remove `enable_namespacing: false` (namespacing is on by default), or express the "
            "iteration with a manual backward-edge worker/checker pair instead of `loop:`.",
        ],
        context={"category": "validation", "path": f"nodes[id={node_id}].loop"},
    )


def _make_loop_shared_storage_diagnostic(node_id: Optional[str]) -> Diagnostic:
    """Reject the unsupported ``loop:`` + ``storage_mode: shared`` combination (issue #445)."""
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' combines `loop:` with `storage_mode: shared`, which is not supported. "
            f"Shared storage writes the child's output and pflow's loop bookkeeping to the parent root, "
            f"so re-entry collides."
        ),
        suggestions=[
            "Remove `storage_mode: shared` (the default `mapped` mode isolates the child's storage), "
            "or drop the `loop:` block and express iteration in the parent.",
        ],
        context={"category": "validation", "path": f"nodes[id={node_id}].params.storage_mode"},
    )


def _make_loop_batch_exclusion_diagnostic(node_id: Optional[str]) -> Diagnostic:
    """Reject a node declaring both `batch:` and `loop:` (issue #445).

    Mirrors the compiler's fail-fast check (`_build_loop_config`) so the save /
    `--validate-only` path — which never compiles — rejects the combination too.
    """
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' declares both `batch:` and `loop:` — they are mutually exclusive. "
            f"`batch:` fans out over a fixed-count list; `loop:` repeats one node until a condition."
        ),
        suggestions=[
            "Keep `batch:` for fixed-count fan-out, or `loop:` for stop-on-condition repetition — not both.",
        ],
        context={"category": "validation", "path": f"nodes[id={node_id}].loop"},
    )


def _make_loop_cap_diagnostic(node_id: Optional[str], cap: int, max_visits: int) -> Diagnostic:
    """Reject a literal `max_iterations` over the hard visit cap (issue #445).

    Mirrors the compiler's `_validate_loop_cap` upper-bound check so the validate
    path agrees with the run path.
    """
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(f"Node '{node_id}' `loop: max_iterations` ({cap}) exceeds the hard visit cap of {max_visits}."),
        suggestions=[
            f"Lower max_iterations to <= {max_visits}, or raise the cap via the "
            "PFLOW_MAX_NODE_VISITS environment variable.",
        ],
        context={"category": "validation", "path": f"nodes[id={node_id}].loop.max_iterations"},
    )


def _check_param_value(
    param_name: str,
    value: Any,
    node_id: str,
    node_position: int,
    nodes_by_id: dict[str, Any],
    node_positions: dict[str, int],
    valid_simple_refs: set[str],
    loop_forward_limits: dict[str, int],
    loop_node_ids: set[str],
    check_inputs: bool,
    errors: list[Diagnostic],
) -> None:
    """Recursively validate template references in a parameter value."""
    if isinstance(value, str) and "${" in value:
        for match in TemplateResolver.TEMPLATE_EXTRACT_PATTERN.finditer(value):
            for operand in TemplateResolver.split_coalesce_operands(match.group(1)):
                # Literal operands (Optional A) are values, not node/input refs.
                # Filter BEFORE _validate_template_reference — keyword literals
                # (null/true/false) match _PFLOW_VAR_RE and would otherwise
                # produce false "undefined input" errors.
                if TemplateResolver.is_literal_operand(operand):
                    continue
                error = _validate_template_reference(
                    operand,
                    node_id,
                    param_name,
                    node_position,
                    nodes_by_id,
                    node_positions,
                    valid_simple_refs,
                    loop_forward_limits,
                    loop_node_ids,
                    check_inputs,
                )
                if error:
                    errors.append(error)
    elif isinstance(value, dict):
        # Thread the dict key into param_name so diagnostics for nested values
        # report the deepest path (e.g. ``headers.Authorization`` instead of
        # just ``headers``).
        for key, val in value.items():
            _check_param_value(
                f"{param_name}.{key}",
                val,
                node_id,
                node_position,
                nodes_by_id,
                node_positions,
                valid_simple_refs,
                loop_forward_limits,
                loop_node_ids,
                check_inputs,
                errors,
            )
    elif isinstance(value, list):
        # Thread the list index into param_name so diagnostics for list items
        # report the deepest path (e.g. ``commands[1]`` instead of just
        # ``commands``).
        for index, item in enumerate(value):
            _check_param_value(
                f"{param_name}[{index}]",
                item,
                node_id,
                node_position,
                nodes_by_id,
                node_positions,
                valid_simple_refs,
                loop_forward_limits,
                loop_node_ids,
                check_inputs,
                errors,
            )


def _validate_node_params(
    node: dict[str, Any],
    node_id: str,
    node_position: int,
    nodes_by_id: dict[str, Any],
    node_positions: dict[str, int],
    valid_simple_refs: set[str],
    loop_forward_limits: dict[str, int],
    loop_node_ids: set[str],
    check_inputs: bool,
    errors: list[Diagnostic],
) -> None:
    """Validate template references in a single node's parameters."""
    # If node has 'inputs' mapping, its keys are valid template references
    # for other params in the same node (inputs-as-context pattern)
    node_refs = valid_simple_refs
    inputs_param = node.get("params", {}).get("inputs")
    if isinstance(inputs_param, dict):
        node_refs = valid_simple_refs | set(inputs_param.keys())

    for param_name, param_value in node.get("params", {}).items():
        _check_param_value(
            param_name,
            param_value,
            node_id,
            node_position,
            nodes_by_id,
            node_positions,
            node_refs,
            loop_forward_limits,
            loop_node_ids,
            check_inputs,
            errors,
        )

    # Validate the loop condition source (issue #445). `loop:` is a top-level
    # node field, so it bypasses the params walk above — thread it in explicitly
    # so a `while: ${typo.x}` (non-existent node) or a forward reference to a
    # different downstream node is still caught. The self-reference carve-out in
    # `_check_forward_reference` allows `while: ${this_node.output}`.
    loop_block = node.get("loop")
    if isinstance(loop_block, dict):
        while_template = loop_block.get("while")
        if isinstance(while_template, str):
            _check_param_value(
                "loop.while",
                while_template,
                node_id,
                node_position,
                nodes_by_id,
                node_positions,
                node_refs,
                loop_forward_limits,
                loop_node_ids,
                check_inputs,
                errors,
            )
        max_it = loop_block.get("max_iterations")
        if isinstance(max_it, str) and "${" in max_it:
            _check_param_value(
                "loop.max_iterations",
                max_it,
                node_id,
                node_position,
                nodes_by_id,
                node_positions,
                node_refs,
                loop_forward_limits,
                loop_node_ids,
                check_inputs,
                errors,
            )


# ------------------------------------------------------------------------------
# Cache-block validation (Task 159 B2.3)
# ------------------------------------------------------------------------------


def _format_chunk_list(names: list[str]) -> str:
    """Format a list of chunk identifiers for the order-mismatch error message.

    Bare-identifier bracketed form: ``[a, b, c]`` (NOT Python ``repr`` quoted form).
    The agent-facing contract for ``cache.order-mismatch`` mandates this exact
    rendering — ``str(list)`` would produce ``"['a', 'b', 'c']"`` which differs
    byte-for-byte and breaks the spec-locked message format.
    """
    return "[" + ", ".join(names) + "]"


def _validate_cache_block(  # noqa: C901
    workflow_ir: dict[str, Any],
    nodes_by_id: dict[str, Any],
    declared_inputs: set[str],
    batch_item_aliases: set[str],
    diagnostics: list[Diagnostic],
    *,
    workflow_path: Optional[str] = None,
) -> None:
    """Validate cache-related declarations: per-node ``prompt_cache:`` and ``prewarm:``,
    plus the workflow-level ``## Cache`` block's chunk references.

    Step ordering (load-bearing per Round 5 plan + V5 fix):
      1. Non-LLM-rejection (shape-agnostic) — runs FIRST so a malformed
         ``prompt_cache: 5`` on a ``type: shell`` node still fires
         ``cache.invalid-on-non-llm`` rather than silently log-skipping.
      2. Defensive shape skip — for surviving LLM nodes, log a warning and
         skip semantic checks if shape is wrong. The schema-validator path
         catches shape errors at step 1 (``WorkflowValidator``) and
         short-circuits; the compile path bypasses jsonschema and falls
         through here. Per V5: schema is single source for shape; data_flow
         emits ZERO Diagnostics for shape errors — the deeper compile error
         (``CompilationError`` on ``CacheBlockIR`` construction) surfaces.
      3. Top-level cache block validation — only when shape is well-formed.
         Walk chunk references for resolution + batch-scoped rejection.
         Walk per-node ``prompt_cache:`` for declaration-order check + chunk
         resolution + unused-chunk warnings.

    Schema is the single source of truth for SHAPE (per V5 fix); this function
    does ONLY semantic checks. It emits no diagnostics for malformed shapes —
    those produce a single jsonschema diagnostic at step 1 of WorkflowValidator
    OR a CompilationError on the compile path. No double-emit.
    """
    # STEP 1: non-LLM-rejection (shape-agnostic; runs FIRST — see V5 fix in
    # core/CLAUDE.md and the plan's Round 5 ordering note). The check is pure
    # key-presence + node-type-string discrimination — it does not inspect
    # the values of ``prompt_cache`` or ``prewarm``, so a malformed shape
    # on a non-LLM node still emits the structured "wrong target type"
    # error rather than silently logger.warning-skipping into a confusing
    # downstream NodeConfig failure.
    rejected_node_ids: set[str] = set()
    for node in workflow_ir.get("nodes", []):
        node_type = node.get("type")
        # ``isinstance(..., str)`` is load-bearing: ``type: ["llm"]`` (list — a
        # structural error caught by schema) would satisfy ``["llm"] != "llm"``
        # and incorrectly fire cache.invalid-on-non-llm against a node whose
        # REAL problem is the type-must-be-string failure. The isinstance gate
        # restricts cache.invalid-on-non-llm to well-formed-but-wrong-target types.
        if not isinstance(node_type, str) or not node_type:
            continue
        if node_type == "llm":
            continue
        invalid_fields: list[str] = [k for k in ("prompt_cache", "prewarm") if k in node]
        if not invalid_fields:
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        diagnostics.append(_make_invalid_on_non_llm_diagnostic(node_id, node_type, invalid_fields))
        rejected_node_ids.add(node_id)

    # Resolve top-level ``cache`` block defensively (compile path may bypass schema).
    cache_block = workflow_ir.get("cache")
    cache_items: list[dict[str, Any]] = []
    cache_item_names: list[str] = []
    cache_block_well_formed = False
    if cache_block is not None:
        if not isinstance(cache_block, dict) or not isinstance(cache_block.get("items"), list):
            logger.warning(
                "cache validation skipped top-level cache block: malformed shape (%s); "
                "schema-validator path catches this at step 1; compile path catches at "
                "CompilationError on CacheBlockIR construction",
                type(cache_block).__name__,
            )
        else:
            cache_block_well_formed = True
            for item in cache_block["items"]:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    cache_items.append(item)
                    cache_item_names.append(item["name"])

    # STEP 2 + 3: walk LLM nodes for shape skip + semantic checks.
    referenced_chunks: set[str] = set()
    for node in workflow_ir.get("nodes", []):
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        if node_id in rejected_node_ids:
            continue
        if node.get("type") != "llm":
            continue

        # STEP 2: defensive shape skip. The schema-validator path catches these
        # at step 1 and short-circuits; the compile path bypasses jsonschema
        # so we MUST guard here to avoid a TypeError on ``list(prompt_cache)``.
        prompt_cache_val = node.get("prompt_cache")
        if prompt_cache_val is not None and (
            not isinstance(prompt_cache_val, list) or not all(isinstance(item, str) for item in prompt_cache_val)
        ):
            logger.warning(
                "cache validation skipped node %s: malformed prompt_cache shape (%s); "
                "schema-validator path catches this at step 1; compile path catches at "
                "NodeConfig construction (CompilationError)",
                node_id,
                type(prompt_cache_val).__name__,
            )
            continue
        prewarm_val = node.get("prewarm")
        # ``bool`` is a subclass of ``int``; ``isinstance(True, int)`` is True.
        # Use ``isinstance(x, bool)`` to reject ``prewarm: 1`` as malformed.
        if prewarm_val is not None and not isinstance(prewarm_val, bool):
            logger.warning(
                "cache validation skipped node %s: malformed prewarm shape (%s); "
                "schema-validator path catches this at step 1; compile path catches at "
                "NodeConfig construction (CompilationError)",
                node_id,
                type(prewarm_val).__name__,
            )
            continue

        # STEP 3a: per-node ``prompt_cache:`` semantic checks.
        prompt_cache: list[str] = list(prompt_cache_val) if prompt_cache_val else []
        has_batch = isinstance(node.get("batch"), dict)
        should_validate_provider_ttl = bool(prompt_cache) or (prewarm_val is True and has_batch)
        if should_validate_provider_ttl and cache_block_well_formed and isinstance(cache_block, dict):
            cache_ttl = cache_block.get("ttl")
            _emit_unsupported_provider_ttl_diagnostic(
                node=node,
                node_id=node_id,
                cache_ttl=cache_ttl,
                diagnostics=diagnostics,
            )
        if not prompt_cache:
            continue

        # Duplicate-detection mirrors the parser's per-block rule (each ${var}
        # can appear once in ## Cache); a node's prompt_cache: [a, a] would
        # otherwise render the chunk twice in the system prompt — wasted tokens
        # AND a silent semantic shift the author likely didn't intend.
        seen: set[str] = set()
        duplicates: list[str] = []
        for name in prompt_cache:
            if name in seen and name not in duplicates:
                duplicates.append(name)
            seen.add(name)
        if duplicates:
            diagnostics.append(_make_duplicate_chunk_diagnostic(node_id, duplicates, prompt_cache))

        # Check each chunk name resolves to a declared cache item. The
        # resolution check uses ``seen`` so a chunk listed twice produces ONE
        # resolution diagnostic at most (the duplicate diagnostic is the
        # actionable error in that case).
        all_resolved = True
        for chunk_name in seen:
            if chunk_name in cache_item_names:
                referenced_chunks.add(chunk_name)
            else:
                all_resolved = False
                similar = find_similar_items(chunk_name, cache_item_names, max_results=3, method="fuzzy")
                diagnostics.append(_make_undeclared_chunk_diagnostic(node_id, chunk_name, cache_item_names, similar))

        # Order-match check (only when all chunks resolve AND no duplicates —
        # otherwise the order error would be confusing on top of the actionable
        # one).
        if all_resolved and not duplicates:
            indices = [cache_item_names.index(c) for c in prompt_cache]
            if indices != sorted(indices):
                expected_order = [c for c in cache_item_names if c in prompt_cache]
                diagnostics.append(_make_order_mismatch_diagnostic(node_id, expected_order, prompt_cache))

        # Prompt-body overlap check (Task 159 follow-up): when a chunk is
        # both declared cached AND referenced inline in the prompt body,
        # the body sends the value at 1.0x rate every call — nullifying
        # the cache savings. ERROR for full-path duplicates; WARNING for
        # sub-path overlap (cache parent + body child, or vice versa).
        # Only fires when all chunks resolve so we don't compound a more
        # actionable cache.undeclared-chunk error.
        if all_resolved:
            _emit_prompt_body_overlap_diagnostics(
                node=node,
                node_id=node_id,
                prompt_cache=prompt_cache,
                cache_item_names=set(cache_item_names),
                workflow_path=workflow_path,
                diagnostics=diagnostics,
            )

    # STEP 3b: top-level chunk-var resolution + batch-scoped rejection +
    # unused-chunk warning. Only runs if the cache block is well-formed.
    if cache_block_well_formed:
        for item in cache_items:
            var_expr = item.get("var")
            if not isinstance(var_expr, str):
                continue
            chunk_name = item.get("name", "")
            chunk_line = item.get("_source_line")
            root = TemplateResolver.extract_root_node_id(var_expr)
            # Batch-scoped rejection: chunks that vary across calls referencing
            # the same chunk are invalid. ``${item.X}`` and any descendants of
            # batch aliases fail this check.
            if root in batch_item_aliases:
                diagnostics.append(_make_batch_scoped_rejection_diagnostic(chunk_name, var_expr, chunk_line))
                continue
            # Resolution check: root must be a declared input or an existing node id.
            if root not in declared_inputs and root not in nodes_by_id:
                candidates = sorted(set(nodes_by_id.keys()) | declared_inputs)
                similar = find_similar_items(root, candidates, max_results=3, method="fuzzy")
                diagnostics.append(_make_chunk_resolution_diagnostic(chunk_name, var_expr, root, similar, chunk_line))

        # Unused-chunk warning: declared but not referenced by any node's
        # prompt_cache. Excludes chunks belonging to nodes that were rejected
        # at STEP 1 — those errors take precedence, the unused warning would
        # be noise. Iterate the full ``cache_items`` (not just names) so we
        # can thread ``_source_line`` through the producer — required by the
        # catalog spec for ``cache.unused-chunk`` per warning_catalog.py.
        for item in cache_items:
            chunk_name = item.get("name", "")
            if not chunk_name or chunk_name in referenced_chunks:
                continue
            chunk_line = item.get("_source_line")
            diagnostics.append(_make_unused_chunk_diagnostic(chunk_name, chunk_line))


def _make_invalid_on_non_llm_diagnostic(node_id: str, node_type: str, invalid_fields: list[str]) -> Diagnostic:
    """V6 combined-diagnostic shape: ONE diagnostic per node listing ALL invalid
    fields, not one per field. Identity tuple uses ``id`` so two diagnostics
    on the same node with the same id collapse correctly even if message
    enrichment differs.
    """
    fields_csv = ", ".join(invalid_fields)
    is_or_are = "is" if len(invalid_fields) == 1 else "are"
    plural_s = "" if len(invalid_fields) == 1 else "s"
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Cache Failure",
        node_id=node_id,
        id="cache.invalid-on-non-llm",
        message=(
            f"Node '{node_id}' is type: {node_type} but declares {fields_csv} — "
            f"{'this field is' if len(invalid_fields) == 1 else 'these fields are'} only valid on type: llm nodes."
        ),
        suggestions=[
            f"Remove the invalid declaration{plural_s} ({fields_csv}) from {node_id}, "
            f"OR move the LLM logic into a type: llm node."
        ],
        context={
            "category": CACHE_FAILURE_CATEGORY,
            "invalid_fields": invalid_fields,
            "invalid_fields_csv": fields_csv,
            "is_or_are": is_or_are,
            "plural_s": plural_s,
            "node_type": node_type,
            "path": f"nodes[id={node_id}]",
        },
        see_also=["prompt-caching"],
    )


def _emit_unsupported_provider_ttl_diagnostic(
    *,
    node: dict[str, Any],
    node_id: str,
    cache_ttl: Any,
    diagnostics: list[Diagnostic],
) -> None:
    """Reject literal provider/TTL combinations pflow cannot honor.

    Templated or omitted models defer to runtime, where the compiler has
    resolved templates and default model injection has already happened.
    """
    if cache_ttl is not None and not isinstance(cache_ttl, str):
        return
    try:
        parse_cache_ttl(cache_ttl)
    except ValueError:
        return

    params = node.get("params")
    if not isinstance(params, dict):
        return
    model = params.get("model")
    if not isinstance(model, str) or _is_templated(model):
        return

    from pflow.core.llm_providers import detect_provider

    provider = detect_provider(model)
    provider_name = provider.name if provider else None
    if is_cache_ttl_supported_by_provider(provider_name, cache_ttl):
        return

    diagnostics.append(
        build_unsupported_cache_ttl_diagnostic(
            node_id=node_id,
            provider_name=provider_name,
            ttl=cache_ttl,
            model=model,
        )
    )


def _make_order_mismatch_diagnostic(node_id: str, declared: list[str], actual: list[str]) -> Diagnostic:
    """Spec-locked four-line message format with bare-identifier bracketed lists.

    The ``expected:`` line shows the node's selected subset reordered to match
    ``## Cache`` declaration order — i.e. the exact replacement the agent
    should write. (Earlier label was ``declared:``; renamed for clarity since
    the line shows the subset, not the full ``## Cache`` block.)
    """
    declared_str = _format_chunk_list(declared)
    actual_str = _format_chunk_list(actual)
    message = (
        f"Node '{node_id}' prompt_cache order doesn't match ## Cache declaration\n"
        f"  expected:  {declared_str}\n"
        f"  you wrote: {actual_str}\n"
        f"  fix:       reorder the `prompt_cache:` field to match ## Cache declaration order"
    )
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Cache Failure",
        node_id=node_id,
        id="cache.order-mismatch",
        message=message,
        context={
            "category": CACHE_FAILURE_CATEGORY,
            "declared": declared,
            "actual": actual,
            "declared_str": declared_str,
            "actual_str": actual_str,
            "path": f"nodes[id={node_id}].prompt_cache",
        },
        see_also=["prompt-caching"],
    )


def _make_duplicate_chunk_diagnostic(node_id: str, duplicates: list[str], prompt_cache: list[str]) -> Diagnostic:
    """Per-node ``prompt_cache:`` lists each chunk twice or more.

    No catalog id — flows through the existing validation diagnostic machinery
    (per spec § Stable Warning ID Catalog: prompt_cache reference errors
    reuse pflow's general validation pipeline). Mirrors the parser's
    ``Duplicate cache chunk identifier`` rule for ``## Cache`` itself.
    """
    duplicates_csv = ", ".join(duplicates)
    plural = "" if len(duplicates) == 1 else "s"
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' lists cache chunk{plural} '{duplicates_csv}' more than once "
            f"in prompt_cache:. Each chunk renders once into the system prompt; "
            f"duplicate references waste tokens and produce ambiguous order semantics."
        ),
        suggestions=[f"Remove the duplicate '{duplicates[0]}' entry from prompt_cache: on '{node_id}'."],
        context={
            "category": "validation",
            "path": f"nodes[id={node_id}].prompt_cache",
            "duplicates": duplicates,
            "prompt_cache": prompt_cache,
        },
    )


def _make_undeclared_chunk_diagnostic(
    node_id: str, chunk_name: str, declared_names: list[str], similar: list[str]
) -> Diagnostic:
    """Reference-resolution error: prompt_cache references a chunk not in ## Cache items.

    No catalog id — flows through the existing validation diagnostic machinery
    (per spec § Stable Warning ID Catalog: reference-resolution errors reuse
    pflow's general validation pipeline, not a cache-namespaced id).
    """
    suggestions = [f"Did you mean '{similar[0]}'?"] if similar else None
    context: dict[str, Any] = {
        "category": "validation",
        "path": f"nodes[id={node_id}].prompt_cache",
        "available_fields": sorted(declared_names),
        "available_fields_total": len(declared_names),
        "available_fields_label": "cache chunks",
    }
    if similar:
        context["similar_names"] = similar
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(f"Node '{node_id}' references undeclared cache chunk '{chunk_name}' in prompt_cache:."),
        suggestions=suggestions,
        context=context,
    )


def _make_chunk_resolution_diagnostic(
    chunk_name: str, var_expr: str, root: str, similar: list[str], chunk_line: int | None
) -> Diagnostic:
    """``${var}`` in a cache chunk that doesn't resolve to an input or node output.

    No catalog id — flows through the existing validation diagnostic machinery.
    """
    suggestions = [f"Did you mean '${{{similar[0]}}}'?"] if similar else None
    context: dict[str, Any] = {
        "category": "validation",
        "path": f"cache.items[name={chunk_name}].var",
    }
    if chunk_line is not None:
        context["line"] = chunk_line
    if similar:
        context["similar_names"] = similar
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        message=(
            f"Cache chunk '{chunk_name}' references '${{{var_expr}}}' but '{root}' is not "
            "a declared input or an existing node output."
        ),
        suggestions=suggestions,
        context=context,
    )


def _make_batch_scoped_rejection_diagnostic(chunk_name: str, var_expr: str, chunk_line: int | None) -> Diagnostic:
    """Cache chunks must reference values that are stable across calls — batch-scoped
    references (``${item.X}`` and any descendants of a batch alias) vary per call
    and are explicitly rejected per spec.

    No catalog id — flows through the existing validation diagnostic machinery.
    """
    context: dict[str, Any] = {
        "category": "validation",
        "path": f"cache.items[name={chunk_name}].var",
        "var_expr": var_expr,
    }
    if chunk_line is not None:
        context["line"] = chunk_line
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        message=(
            f"Cache chunk '{chunk_name}' references '${{{var_expr}}}', which is batch-scoped "
            "(varies across calls referencing the same chunk). batch references like "
            "${item.X} and any descendants are not valid in '## Cache' — only stable values "
            "(workflow inputs and step outputs) may be cached."
        ),
        suggestions=[
            "Remove the batch-scoped reference from '## Cache' and put the dynamic value "
            "directly in the node's prompt instead."
        ],
        context=context,
    )


def _emit_prompt_body_overlap_diagnostics(
    *,
    node: dict[str, Any],
    node_id: str,
    prompt_cache: list[str],
    cache_item_names: set[str],
    workflow_path: Optional[str],
    diagnostics: list[Diagnostic],
) -> None:
    """Detect prompt-body / prompt_cache overlap and emit consolidated diagnostics.

    Calls into the shared :func:`pflow.core.cache_overlap.compute_overlaps`
    so the validator's enforcement matches the analyzer's recommendation
    byte-for-byte. Emits AT MOST one ERROR diagnostic (full-path duplicates)
    and one WARNING diagnostic (sub-path overlap) per node — the
    consolidated-per-node shape mirrors ``cache.invalid-on-non-llm`` and
    works around ``Diagnostic.__hash__`` collapsing same-id diagnostics
    on the same node into a single entry that loses per-pair detail.
    """
    # Lazy import: cache_overlap → template_resolver is the same dependency
    # already loaded at module top, but the lazy form keeps this module's
    # import surface unchanged for callers that don't exercise the cache
    # validation path.
    from pflow.core.cache_overlap import _batch_aliases, compute_overlaps
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    prompt_text = node.get("params", {}).get("prompt", "")
    if not isinstance(prompt_text, str) or not prompt_text:
        return

    overlaps = compute_overlaps(
        prompt_text=prompt_text,
        prompt_cache=prompt_cache,
        cache_item_names=cache_item_names,
        batch_aliases=_batch_aliases(node),
    )
    if not overlaps:
        return

    duplicates = [o for o in overlaps if o.kind == "duplicate"]
    shadows = [o for o in overlaps if o.kind != "duplicate"]

    # ``make_diagnostic`` requires a non-empty ``affected_workflow`` whenever
    # ``node_id`` is set so the renderer can scope per-row warnings when the
    # same node id appears in parent and child workflows. When this validator
    # entry doesn't know the path (synthetic-IR tests, compiler path that
    # didn't thread it), fall back to a stable placeholder so the diagnostic
    # still fires — the failure mode that matters most is the agent missing
    # the duplicate-bytes pattern, not the workflow-scope label.
    affected_workflow = workflow_path or "<unknown>"

    if duplicates:
        overlap_lines = "\n".join(
            f"  - cached `${{{o.chunk_name}}}` AND inline `${{{o.body_ref}}}`" for o in duplicates
        )
        diagnostics.append(
            make_diagnostic(
                "cache.prompt-body-duplicates-cache",
                node_id=node_id,
                overlapping_pairs=[{"chunk_name": o.chunk_name, "body_ref": o.body_ref} for o in duplicates],
                affected_workflow=affected_workflow,
                overlap_lines=overlap_lines,
            )
        )

    if shadows:
        overlap_lines = "\n".join(
            f"  - cached `${{{o.chunk_name}}}` overlaps inline `${{{o.body_ref}}}` ({o.kind})" for o in shadows
        )
        diagnostics.append(
            make_diagnostic(
                "cache.prompt-body-shadows-cache",
                node_id=node_id,
                shadowing_pairs=[
                    {"chunk_name": o.chunk_name, "body_ref": o.body_ref, "direction": o.kind} for o in shadows
                ],
                affected_workflow=affected_workflow,
                overlap_lines=overlap_lines,
            )
        )


# Reasoning-effort values that enable thinking on Anthropic. Mirrors
# ``llm_reasoning_map.EFFORT_RATIOS`` keys; ``"none"`` (or unset) disables
# thinking and is excluded.
_REASONING_EFFORT_ENABLES_THINKING = frozenset({"xhigh", "high", "medium", "low", "minimal"})


def _is_templated(value: Any) -> bool:
    """Return True if a param value is a templated string (defer-to-runtime)."""
    return isinstance(value, str) and "${" in value


def _literal_non_one_temperature(temperature: Any) -> Optional[float]:
    """Return the temperature as a float if it's a literal numeric ≠ 1.0,
    otherwise None. Filters: None (default → 1.0), bools (subclass of int),
    non-numeric, and exactly 1.0.
    """
    if temperature is None or isinstance(temperature, bool):
        return None
    if not isinstance(temperature, (int, float)):
        return None
    value = float(temperature)
    if value == 1.0:
        return None
    return value


def _extract_thinking_temp_violation(node: dict[str, Any]) -> Optional[tuple[str, str, str, float]]:
    """Return ``(node_id, model, reasoning_effort, temperature)`` if the node
    is an Anthropic LLM node with reasoning_effort enabled AND a literal
    temperature ≠ 1.0; otherwise ``None``.

    Skips templated values (``${...}``) and absent fields — those defer to
    runtime. The ``LLMNode`` default temperature is 1.0, so omitting
    ``temperature`` is silently safe.
    """
    from pflow.core.llm_providers import detect_provider

    if node.get("type") != "llm":
        return None
    node_id = node.get("id")
    if not isinstance(node_id, str):
        return None

    params = node.get("params")
    if not isinstance(params, dict):
        return None

    model = params.get("model")
    if not isinstance(model, str) or _is_templated(model):
        return None
    provider = detect_provider(model)
    if provider is None or provider.name != "anthropic":
        return None

    reasoning_effort = params.get("reasoning_effort")
    if not isinstance(reasoning_effort, str) or _is_templated(reasoning_effort):
        return None
    if reasoning_effort not in _REASONING_EFFORT_ENABLES_THINKING:
        return None

    temperature = _literal_non_one_temperature(params.get("temperature"))
    if temperature is None:
        return None

    return (node_id, model, reasoning_effort, temperature)


def _validate_thinking_temperature_compatibility(
    workflow_ir: dict[str, Any],
    diagnostics: list[Diagnostic],
    *,
    workflow_path: Optional[str] = None,
) -> None:
    """Emit ``llm.thinking-temperature-mismatch`` ERROR for Anthropic LLM nodes
    that combine ``reasoning_effort`` (which pflow translates to
    ``thinking: enabled``) with an explicit ``temperature`` other than 1.0.

    Anthropic's API rejects every such request — verified empirically across
    Opus 4.1/4.5/4.7, Sonnet 4.5/4.6, Haiku 4.5 (uniform behavior). Catching
    this at validate-time spares the agent the runtime BadRequestError and
    surfaces the actionable workflow-level fix (set temperature to 1.0 OR
    set reasoning_effort to none).
    """
    # Lazy import: keeps catalog import out of the validator hot path
    # (``data_flow.py`` runs on every workflow validation including
    # ones that never touch LLM nodes).
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    affected_workflow = workflow_path or "<unknown>"

    for node in workflow_ir.get("nodes", []):
        violation = _extract_thinking_temp_violation(node)
        if violation is None:
            continue
        node_id, model, reasoning_effort, temperature = violation
        diagnostics.append(
            make_diagnostic(
                "llm.thinking-temperature-mismatch",
                node_id=node_id,
                model=model,
                reasoning_effort=reasoning_effort,
                temperature=temperature,
                affected_workflow=affected_workflow,
            )
        )


def _make_unused_chunk_diagnostic(chunk_name: str, source_line: int | None = None) -> Diagnostic:
    """Declared chunk that no node references via prompt_cache:.

    Catalog id ``cache.unused-chunk``, severity WARNING. Helps the author keep
    the cache block lean and surfaces dead code (per spec). ``source_line``
    is the chunk's line in the source file (from ``cache.items[i]["_source_line"]``)
    — included in ``context`` per the catalog's ``required_context_keys`` so
    agents can navigate to the offending chunk; ``None`` is tolerated for
    programmatic IR construction paths that may not have line metadata.
    """
    context: dict[str, Any] = {
        "category": CACHE_WARNING_CATEGORY,
        "chunk_name": chunk_name,
        "path": f"cache.items[name={chunk_name}]",
    }
    if source_line is not None:
        context["source_line"] = source_line
    return Diagnostic(
        severity=Severity.WARNING,
        source="validator",
        title="Cache Warning",
        id="cache.unused-chunk",
        message=(f"Cache chunk '{chunk_name}' is declared in ## Cache but no node references it via prompt_cache:."),
        suggestions=[
            f"Remove '{chunk_name}' from ## Cache, OR reference it from a node's `- prompt_cache: [{chunk_name}]`."
        ],
        context=context,
        see_also=["prompt-caching"],
    )
