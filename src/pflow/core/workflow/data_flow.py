"""Data flow validation for workflow execution order and dependencies.

This module ensures that workflows have correct execution order and that
all data dependencies are satisfied before nodes execute.
"""

import ast
import keyword
import logging
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

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
from pflow.core.templates import (
    Expression,
    Field,
    Issue,
    Reference,
    Template,
    TemplateResolver,
    Text,
    parse,
    parse_path,
)
from pflow.core.types import is_template_reserved_internal_key
from pflow.core.workflow.gate_validation import check_approval_allowed
from pflow.core.workflow.loop_validation import check_loop_polarity
from pflow.core.workflow.template_surfaces import BodyLanguage, code_bodies, iter_node_surfaces

logger = logging.getLogger(__name__)


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
) -> Diagnostic | None:
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
) -> Diagnostic | None:
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


def _validate_template_reference(
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
) -> Diagnostic | None:
    """Validate a single template reference.

    Args:
        ref: A parsed Reference's source text (e.g., "node1.output", "input_param",
            "a[${i}].x") — never an Issue: bash syntax (``${var:-default}``) opens no
            Expression and is the Issue pass's to report
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
    workflow_path: str | None = None,
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
    diagnostics.extend(_validate_approval_node_combos(workflow_ir))

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
        diagnostics.extend(_validate_bodies(workflow_ir, node))

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

    (The former `storage_mode: shared` combo no longer needs a check here — the
    whole `storage_mode` param was removed, so any value is now an unknown param
    caught by the validator's unknown-param step. See issues #254/#231.)
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
        if loop_data is None:
            continue
        node_id = node.get("id")
        if not namespacing_on:
            diagnostics.append(_make_loop_namespacing_diagnostic(node_id))
        # batch + loop are mutually exclusive. The compiler enforces this fail-fast in
        # _build_loop_config, but that only runs on the run path — duplicate it here so
        # `pflow save` / --validate-only (which never compile) catch it too.
        if node.get("batch"):
            diagnostics.append(_make_loop_batch_exclusion_diagnostic(node_id))
        # Literal max_iterations over the hard visit cap. The compiler bounds this for
        # the run path; mirror it here so the validate path agrees (the ${template}
        # branch is bounded at runtime in resolve_loop_cap). Schema already enforces the
        # >= 1 lower bound and integer-ness of the literal branch. Exclude bool (a bool
        # cap is a separate schema concern, not an over-cap one) — bool is an int subclass.
        if isinstance(loop_data, dict):
            diagnostics.extend(_validate_loop_dict_rules(node, loop_data, instrumentation.MAX_NODE_VISITS))
    return diagnostics


def _validate_loop_dict_rules(node: dict[str, Any], loop_data: dict[str, Any], max_visits: int) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    node_id = node.get("id")
    polarity_error = check_loop_polarity(loop_data)
    if polarity_error is not None:
        return [_make_loop_polarity_diagnostic(node_id, polarity_error)]

    raw_max = loop_data.get("max_iterations")
    if isinstance(raw_max, int) and not isinstance(raw_max, bool) and raw_max > max_visits:
        diagnostics.append(_make_loop_cap_diagnostic(node_id, raw_max, max_visits))
    diagnostics.extend(_validate_loop_carry_shape(node, loop_data))
    return diagnostics


def _validate_loop_carry_shape(node: dict[str, Any], loop_data: dict[str, Any]) -> list[Diagnostic]:
    carry = loop_data.get("carry")
    if not isinstance(carry, dict):
        return []
    node_id = node.get("id")
    inputs = node.get("params", {}).get("inputs")
    input_keys = set(inputs) if isinstance(inputs, dict) else set()
    diagnostics: list[Diagnostic] = []
    for key, value in carry.items():
        if isinstance(key, str) and key not in input_keys:
            diagnostics.append(_make_loop_carry_seed_diagnostic(node_id, key))
        if isinstance(value, str):
            diagnostics.extend(_validate_loop_carry_value_self_ref(node_id, key, value))
    return diagnostics


def _validate_loop_carry_value_self_ref(node_id: str | None, key: Any, value: str) -> list[Diagnostic]:
    """A carry value is one reference whose (first operand's) root is the loop node itself."""
    template = parse(value)
    first = template.expressions[0].operands[0] if template.is_simple else None
    if isinstance(first, Reference) and first.root == node_id:
        return []
    return [_make_loop_carry_self_ref_diagnostic(node_id, key, value)]


def _validate_approval_node_combos(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
    """Reject unsupported ``approval:`` combinations (Task 125).

    Mirrors the compiler's fail-fast check so the save / ``--validate-only`` path —
    which never compiles — rejects them too (same dual as the batch/loop exclusion).
    """
    diagnostics: list[Diagnostic] = []
    for node in workflow_ir.get("nodes", []):
        error = check_approval_allowed(node)
        if error is not None:
            node_id = node.get("id")
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    node_id=node_id,
                    message=f"Node '{node_id}': {error}",
                    suggestions=[
                        "Move `approval: required` to the step before or after the batch — "
                        "that is where a whole-batch review belongs.",
                    ],
                    context={"category": "validation", "path": f"nodes[id={node_id}].approval"},
                )
            )
    return diagnostics


def _make_loop_namespacing_diagnostic(node_id: str | None) -> Diagnostic:
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


def _make_loop_batch_exclusion_diagnostic(node_id: str | None) -> Diagnostic:
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


def _make_loop_polarity_diagnostic(node_id: str | None, message: str) -> Diagnostic:
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=f"Node '{node_id}' {message}",
        suggestions=[
            "Use exactly one polarity: `while: ${node.should_continue}` or `until: ${node.done}`.",
        ],
        context={"category": "validation", "path": f"nodes[id={node_id}].loop"},
    )


def _make_loop_carry_seed_diagnostic(node_id: str | None, key: str) -> Diagnostic:
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' carries input '{key}' but does not seed it in `inputs:`. "
            "A carried input needs a round-1 value before carry overrides it on later iterations."
        ),
        suggestions=[
            f"Add `{key}: <initial value>` under the node's `inputs:` mapping.",
        ],
        context={"category": "validation", "path": f"nodes[id={node_id}].loop.carry.{key}"},
    )


def _make_loop_carry_self_ref_diagnostic(node_id: str | None, key: Any, value: str) -> Diagnostic:
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' `loop: carry:` entry '{key}' references '{value}', but carry values "
            "must reference this loop node's own latest output."
        ),
        suggestions=[
            f"Use `{key}: ${{{node_id}.output_name}}` so round N+1 reads round N's output.",
        ],
        context={"category": "validation", "path": f"nodes[id={node_id}].loop.carry.{key}"},
    )


def _make_loop_cap_diagnostic(node_id: str | None, cap: int, max_visits: int) -> Diagnostic:
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
    """Validate every reference in a node's params, ``batch.items`` and loop fields
    (a dynamic index's inner references included; a carry value's own outer
    reference has its self-reference check, its inner ones are checked here).
    ``loop:`` is a top-level node field, so a
    ``while: ${typo.x}`` or a forward reference to a different downstream node is
    caught here too; ``_check_forward_reference`` allows ``while: ${this_node.output}``.
    """
    # If node has 'inputs' mapping, its keys are valid template references
    # for other params in the same node (inputs-as-context pattern)
    node_refs = valid_simple_refs
    inputs_param = node.get("params", {}).get("inputs")
    if isinstance(inputs_param, dict):
        node_refs = valid_simple_refs | set(inputs_param.keys())

    for surface in iter_node_surfaces(node):
        # ``location`` names the value in diagnostics: ``headers.Authorization``,
        # ``commands[1]``, ``batch.items``, ``loop.while``
        for location, template in surface.templates():
            for ref in _checked_references(surface.kind, template):
                error = _validate_template_reference(
                    ref.raw,
                    node_id,
                    location,
                    node_position,
                    nodes_by_id,
                    node_positions,
                    node_refs,
                    loop_forward_limits,
                    loop_node_ids,
                    check_inputs,
                )
                if error:
                    errors.append(error)


def _checked_references(kind: str, template: Template) -> tuple[Reference, ...]:
    """The references this pass checks. A carry value's own reference has the carry
    self-reference check (one diagnostic per mistake); its dynamic-index sources are
    ordinary reads, so they are checked here."""
    if kind != "carry":
        return template.references
    return tuple(
        source
        for expression in template.expressions
        for operand in expression.operands
        if isinstance(operand, Reference)
        for source in operand.index_sources
    )


# ------------------------------------------------------------------------------
# Code bodies (ADR-0016): a shell command or code block is plain code. A ${…} the
# runtime resolved there before is a leftover; a $${ escape has nothing to escape.
# ------------------------------------------------------------------------------

_INPUTS_KEY_OWNER = "a key of this step's inputs:"
_BATCH_ITEM_OWNER = "this step's batch item"
_SHELL_IS_PLAIN = "A shell command is plain sh: pflow never fills in ${…} there."
_CODE_IS_PLAIN = "A code step's code is plain Python: pflow never fills in ${…} there."
_KEEP_FOREIGN = "If the text belongs to another program inside the command, leave it."
_PATH_CHARS = frozenset("_-.[]")
_CODE_OUTPUT_NAMES = frozenset({"result", "next"})
_GUIDE_TOPIC: dict[BodyLanguage, str] = {"sh": "shell", "python": "code"}


@dataclass(frozen=True, slots=True)
class StepScope:
    """The pflow names a ``${…}`` in one step could mean: what the runtime resolved for
    that step while bodies were Templates. A step id counts only with a path —
    ``${fetch.stdout}``, never a bare ``${fetch}`` (that is ordinary sh)."""

    names: Mapping[str, str]  # name -> its owner, as diagnostics phrase it
    step_ids: frozenset[str]

    def owner(self, root: str, *, has_path: bool) -> str | None:
        """Who ``root`` names in this step (``"step 'fetch'"``); ``None`` if pflow never knew it."""
        if root in self.names:
            return self.names[root]
        if has_path and root in self.step_ids:
            return f"step '{root}'"
        return None


def step_scope(workflow_ir: dict[str, Any], node: dict[str, Any]) -> StepScope:
    """One step's scope: the workflow's inputs, the step's own ``inputs:`` keys and — on a
    batched or looped step only — its batch alias, ``__index__``, ``__iteration__`` (a later
    source shadows an earlier one, as at run time); every step id, with a path."""
    declared = workflow_ir.get("inputs")
    names = {str(name): f"workflow input '{name}'" for name in (declared if isinstance(declared, dict) else {})}
    params = node.get("params")
    own_inputs = params.get("inputs") if isinstance(params, dict) else None
    if isinstance(own_inputs, dict):
        names.update(dict.fromkeys(map(str, own_inputs), _INPUTS_KEY_OWNER))
    batch = node.get("batch")
    if isinstance(batch, dict):
        alias = batch.get("as")
        names[alias if isinstance(alias, str) and alias else "item"] = _BATCH_ITEM_OWNER
        names["__index__"] = "this step's batch index"
    if isinstance(node.get("loop"), dict):
        names["__iteration__"] = "this step's loop iteration"
    nodes = workflow_ir.get("nodes", [])
    step_ids = frozenset(other["id"] for other in nodes if isinstance(other, dict) and isinstance(other.get("id"), str))
    return StepScope(names, step_ids)


@dataclass(frozen=True, slots=True)
class BodyReference:
    """A ``${…}`` in a code body whose root is in its step's scope — a leftover."""

    param: str  # ``command`` / ``code``
    language: BodyLanguage
    written: str  # as in the body: ``${item}``, ``${limit:-10}``
    reference: str  # the pflow reference it names: ``item``, ``limit``, ``fetch.stdout``
    root: str  # the root ``owner`` describes
    owner: str
    line: int  # 0-based, within the body
    is_expression: bool  # False: a shell expansion form (``${limit:-10}``) on an in-scope name
    roots: tuple[str, ...]  # every in-scope root it names (``${a ?? b}`` → a, b) — for accounting


def body_references(node: dict[str, Any], scope: StepScope) -> list[BodyReference]:
    """Every leftover in a node's bodies, in body order. A shell command is read whole, a
    code block's string literals only. An Expression is a leftover when any reference in it
    (dependency view) is in ``scope``; an Issue when the name it starts with is, or a
    ``${…}`` nested inside it (``${UNSET:-${item}}`` — the Issue ends at the first ``}``)."""
    found: list[BodyReference] = []
    for param, language, text in code_bodies(node):
        if "${" not in text:
            continue
        for piece, first_line in _readable_texts(language, text):
            for start, written, segment in _segments(piece):
                if (leftover := _leftover(segment, scope)) is None:
                    continue
                reference, owner, roots, is_expression = leftover
                line = first_line + piece.count("\n", 0, start)
                found.append(
                    BodyReference(param, language, written, reference, roots[0], owner, line, is_expression, roots)
                )
    return found


def _segments(text: str, offset: int = 0) -> Iterator[tuple[int, str, Expression | Issue]]:
    """``(offset, written, segment)`` per ``${`` the parser sees in ``text``, an Issue's
    interior re-read for the ``${…}`` it swallowed."""
    for segment in parse(text).segments:
        if isinstance(segment, Text):
            continue
        start, end = segment.span
        yield offset + start, text[start:end], segment
        if isinstance(segment, Issue):
            yield from _segments(segment.raw[2:], offset + start + 2)


def body_reference_roots(workflow_ir: dict[str, Any]) -> set[str]:
    """The roots of every leftover in a workflow. The unused-input pass counts them as used:
    an input read only through a leftover gets the leftover ERROR alone."""
    return {
        root
        for node in workflow_ir.get("nodes", [])
        if isinstance(node, dict)
        for ref in body_references(node, step_scope(workflow_ir, node))
        for root in ref.roots
    }


def _leftover(segment: Expression | Issue, scope: StepScope) -> tuple[str, str, tuple[str, ...], bool] | None:
    """``(reference, owner, in-scope roots, is_expression)`` when ``segment`` names something in scope."""
    if isinstance(segment, Expression):
        owned = [(ref.root, owner) for ref in segment.references if (owner := _owner(scope, ref))]
        if owned:
            return segment.raw, owned[0][1], tuple(dict.fromkeys(root for root, _ in owned)), True
        first = segment.operands[0]
        leading = first if isinstance(first, Reference) else None
    else:
        leading = _issue_reference(segment.raw)
        if leading is not None and (owner := _owner(scope, leading)):
            return leading.raw, owner, (leading.root,), False
    # sh reads ``${limit-10}`` / ``${limit-a:b}`` as ``$limit`` with a default (sh names hold no
    # ``-``); pflow's grammar reads one name, ``limit-10``. A shell expansion form on ``limit``.
    if leading is not None and "-" in leading.root:
        name = leading.root.split("-", 1)[0]
        if owner := scope.owner(name, has_path=False):
            return name, owner, (name,), False
    return None


def _owner(scope: StepScope, ref: Reference) -> str | None:
    return scope.owner(ref.root, has_path=bool(ref.path))


def _issue_reference(raw: str) -> Reference | None:
    """The pflow path an Issue starts with, after ``${`` and an optional ``#``/``!``:
    ``limit`` in ``${limit:-10}``, ``item`` in ``${#item}``; ``None`` for ``${}``, ``${1:-x}``."""
    text = raw[2:]
    if text[:1] in ("#", "!"):
        text = text[1:]
    end = 0
    while end < len(text) and (text[end].isalnum() or text[end] in _PATH_CHARS):
        end += 1
    for length in range(end, 0, -1):
        if (ref := parse_path(text[:length])) is not None:
            return ref
    return None


def _readable_texts(language: BodyLanguage, text: str) -> list[tuple[str, int]]:
    """``(text, 0-based body line it starts on)`` for what the rule reads: a shell command
    whole; a code block's string and bytes literals, an f-string's constant parts included
    (so ``f"Total: ${total}"`` is ``$`` and an interpolation, never a reference). A code
    block Python cannot parse yields nothing — the markdown parser reports it.

    A literal is read as its own source, not its value: adjacent literals stay apart (the
    ``"$$" "{X}"`` repair is no escape) and a line count holds through ``\\n`` escapes. An
    f-string's parts keep their value (their positions are unreliable before Python 3.12)."""
    if language == "sh":
        return [(text, 0)]
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    in_fstrings = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in node.values}
    strings: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str | bytes):
            continue
        piece = node.value if id(node) in in_fstrings else ast.get_source_segment(text, node)
        if isinstance(piece, str) and "$" in piece:
            strings.append((node.lineno, node.col_offset, piece))
    return [(piece, lineno - 1) for lineno, _, piece in sorted(strings)]


def _escapes(text: str) -> Iterator[tuple[int, str]]:
    """``(offset, written)`` per ``$${…}`` escape — never ``$$${…}``, sh's pid then ``${…}``."""
    start = text.find("$${")
    while start != -1:
        if start == 0 or text[start - 1] != "$":
            close = text.find("}", start)
            yield start, text[start : close + 1 if close != -1 else start + 3]
        start = text.find("$${", start + 1)


def _validate_bodies(workflow_ir: dict[str, Any], node: dict[str, Any]) -> list[Diagnostic]:
    """The body rule for one step: its leftovers (one ERROR per body), each ``$${`` escape
    (an ERROR), and — shell only — a pflow-only shape naming nothing pflow knows (one WARNING)."""
    bodies = [(param, language, text) for param, language, text in code_bodies(node) if "${" in text]
    if not bodies:
        return []
    scope = step_scope(workflow_ir, node)
    leftovers = body_references(node, scope)
    diagnostics: list[Diagnostic] = []
    for param, language, text in bodies:
        if refs := [ref for ref in leftovers if ref.param == param]:
            diagnostics.append(_leftover_diagnostic(node, refs, text))
        for piece, first_line in _readable_texts(language, text):
            for start, written in _escapes(piece):
                body_line = first_line + piece.count("\n", 0, start)
                diagnostics.append(_escape_diagnostic(node, param, language, written, body_line, scope))
        if language == "sh":
            diagnostics.extend(_foreign_shape_warning(node, param, text, scope))
    return diagnostics


# — where a body diagnostic points —


def _location(node: dict[str, Any], param: str, body_line: int) -> tuple[str | None, int | None]:
    """``(script path, its line)`` for a file-loaded body, else ``(None, workflow-file line)``;
    ``(None, None)`` when the IR carries no source lines (a dict IR)."""
    source_files = node.get("_source_files")
    if isinstance(source_files, dict) and isinstance(source_files.get(param), str):
        return source_files[param], body_line + 1
    source_lines = node.get("_source_lines")
    first = source_lines.get(param) if isinstance(source_lines, dict) else None
    return (None, first + body_line) if isinstance(first, int) else (None, None)


def _where(location: tuple[str | None, int | None], *, in_list: bool = False) -> str | None:
    """``line 13 of the workflow file`` (``line 13`` inside a list) / ``line 4 of ./cmd.sh``."""
    script, line = location
    if line is None:
        return None
    if script is not None:
        return f"line {line} of {script}"
    return f"line {line}" if in_list else f"line {line} of the workflow file"


def _body_diagnostic(
    severity: Severity,
    node: dict[str, Any],
    param: str,
    location: tuple[str | None, int | None],
    message: str,
    suggestions: list[str],
    guide_topic: str | None = None,
    **context: Any,
) -> Diagnostic:
    full_context: dict[str, Any] = {"category": "validation", "path": f"nodes[id={node.get('id')}].params.{param}"}
    script, line = location
    if script is None and line is not None:
        full_context["source_line"] = line
    full_context.update(context)
    return Diagnostic(
        severity=severity,
        source="validator",
        title="Validation Error" if severity is Severity.ERROR else "Validation Warning",
        node_id=str(node.get("id")),
        message=message,
        suggestions=suggestions,
        context=full_context,
        see_also=[guide_topic] if guide_topic else None,
    )


# — the fixes the messages offer —


def _binding_phrase(node: dict[str, Any], param: str, entries: list[tuple[str, str]]) -> str:
    """How to add ``entries`` — ``(name, pflow reference)`` — to the step's ``env:`` or
    ``inputs:``: a new bullet, or keys under the map the step already has."""
    params = node.get("params")
    existing = params.get(param) if isinstance(params, dict) else None
    pairs = ", ".join(f"{name}: ${{{reference}}}" for name, reference in entries)
    if isinstance(existing, dict) and existing:
        return f"add {pairs} under the step's existing {param}:"
    return f"add `- {param}: {{{pairs}}}` to the step"


def _env_name(reference: str) -> str:
    from pflow.nodes.shell.env_binding import suggest_env_name

    return suggest_env_name(reference)


def _code_name(reference: str) -> str:
    """A Python variable for a pflow reference: lower_snake, ``_value`` on a keyword or an output name."""
    name = "_".join("".join(char if char.isalnum() else " " for char in reference).split()).lower() or "value"
    if name[0].isdigit():
        name = f"var_{name}"
    return f"{name}_value" if keyword.iskeyword(name) or name in _CODE_OUTPUT_NAMES else name


def _distinct_names(refs: list[BodyReference], namer: Callable[[str], str]) -> dict[str, str]:
    """``written -> binding name`` per distinct leftover; a clash gets a numeric suffix."""
    names: dict[str, str] = {}
    for ref in refs:
        if ref.written in names:
            continue
        base = namer(ref.reference)
        name, suffix = base, 2
        while name in names.values():
            name, suffix = f"{base}_{suffix}", suffix + 1
        names[ref.written] = name
    return names


def _shell_replacement(ref: BodyReference, name: str) -> str:
    """What replaces a leftover in sh: ``"$ITEM"``; an expansion form keeps its operator (``"${LIMIT:-10}"``)."""
    if ref.is_expression:
        return f'"${name}"'
    return '"' + ref.written.replace(ref.reference, name, 1) + '"'


# — the leftover ERROR —


def _leftover_diagnostic(node: dict[str, Any], refs: list[BodyReference], text: str) -> Diagnostic:
    param, language = refs[0].param, refs[0].language
    distinct = list({ref.written: ref for ref in refs}.values())
    if language == "sh":
        whole_body = len(refs) == 1 and refs[0].is_expression and text.strip() == refs[0].written
        names = {refs[0].written: "CMD"} if whole_body else _distinct_names(distinct, _env_name)
        suggestions = _shell_leftover_fixes(node, distinct, names, whole_body=whole_body)
    else:
        names = _distinct_names(distinct, _code_name)
        suggestions = _code_leftover_fixes(node, distinct, names)
    listed = [
        {
            "reference": ref.written,
            "owner": ref.owner,
            "line": _location(node, param, ref.line)[1],
            "binding": names[ref.written],
        }
        for ref in distinct
    ]
    message = _leftover_message(node, refs, distinct)
    location = _location(node, param, refs[0].line)
    return _body_diagnostic(
        Severity.ERROR, node, param, location, message, suggestions, _GUIDE_TOPIC[language], body_references=listed
    )


def _leftover_message(node: dict[str, Any], refs: list[BodyReference], distinct: list[BodyReference]) -> str:
    """``Step 'x': the command contains ${item} (line 13 of the workflow file) — a pflow
    reference (this step's batch item). …`` — or the list form for several."""
    is_sh = refs[0].language == "sh"
    quote = "" if is_sh else '"'
    places = {ref.written: sum(other.written == ref.written for other in refs) for ref in distinct}

    def details(ref: BodyReference, *, in_list: bool) -> list[str]:
        count = [f"{places[ref.written]} places"] if places[ref.written] > 1 else []
        where = _where(_location(node, ref.param, ref.line), in_list=in_list)
        return count + ([where] if where else [])

    head = f"Step '{node.get('id')}': the {'command' if is_sh else 'code'} contains"
    if len(distinct) == 1:
        ref = distinct[0]
        detail = details(ref, in_list=False)
        located = f"{quote}{ref.written}{quote}" + (f" ({', '.join(detail)})" if detail else "")
        inside = "" if is_sh else " inside a Python string"
        return f"{head} {located} — a pflow reference ({ref.owner}){inside}. {_SHELL_IS_PLAIN if is_sh else _CODE_IS_PLAIN}"
    listed = ", ".join(
        f"{quote}{ref.written}{quote} ({', '.join([*details(ref, in_list=True), ref.owner])})" for ref in distinct
    )
    inside = "" if is_sh else " inside Python strings"
    return f"{head} {len(distinct)} pflow references{inside} — {listed}. {_SHELL_IS_PLAIN if is_sh else _CODE_IS_PLAIN}"


def _shell_leftover_fixes(
    node: dict[str, Any], distinct: list[BodyReference], names: dict[str, str], *, whole_body: bool
) -> list[str]:
    from pflow.nodes.shell.env_binding import AMBIENT_NAMES

    entries = [(names[ref.written], ref.reference) for ref in distinct]
    add = _binding_phrase(node, "env", entries)
    if whole_body:
        return [
            f'The whole command is one pflow reference — bind it and run it: {add} and make the command eval "$CMD".'
        ]
    if len(distinct) > 1:
        replacements = ", ".join(_shell_replacement(ref, names[ref.written]) for ref in distinct)
        return [
            f"Bind them: {add}, then replace each with {replacements} (${{NAME}} where a letter, digit or _ "
            "follows; inside single quotes sh expands nothing — close them around each)."
        ]
    ref = distinct[0]
    name = names[ref.written]
    replacement = _shell_replacement(ref, name)
    braced = f"${{{name}}} where a letter, digit or _ follows; " if ref.is_expression else ""
    bind = (
        f"Bind the value and read it as a shell variable: {add}, then replace {ref.written} with {replacement} "
        f"({braced}inside single quotes sh expands nothing — close them around it: '…'{replacement}'…')."
    )
    if ref.reference != ref.root:
        other = (
            f"If {ref.written} belongs to another program inside the command (a JavaScript template literal, "
            f"say), it collides with {ref.owner} — rename the name in that program."
        )
    elif not ref.is_expression:
        other = f"Only if the command itself assigns `{ref.root}` (a shell variable of your own): rename it."
    elif ref.root in AMBIENT_NAMES:
        other = f"If you meant the shell's own ${ref.root}: write ${ref.root} without braces."
    else:
        example = f", e.g. `for {ref.root} in …`" if ref.owner == _BATCH_ITEM_OWNER else ""
        other = (
            f"Only if the command itself assigns `{ref.root}` (a shell variable of your own{example}): "
            f"write ${ref.root} without braces, or rename it."
        )
    return [bind, other]


def _code_leftover_fixes(node: dict[str, Any], distinct: list[BodyReference], names: dict[str, str]) -> list[str]:
    bound = [ref for ref in distinct if ref.owner == _INPUTS_KEY_OWNER]
    unbound = [ref for ref in distinct if ref.owner != _INPUTS_KEY_OWNER]
    fixes: list[str] = []
    if len(unbound) == 1:
        name = names[unbound[0].written]
        add = _binding_phrase(node, "inputs", [(name, unbound[0].reference)])
        fixes.append(
            f"Declare it in inputs: — {add}, declare its type in the code (`{name}: str`), "
            f"and use the variable `{name}` in place of the string."
        )
    elif unbound:
        add = _binding_phrase(node, "inputs", [(names[ref.written], ref.reference) for ref in unbound])
        fixes.append(
            f"Declare them in inputs: — {add}, declare their types in the code, "
            "and use the variables in place of the strings."
        )
    fixes.extend(
        f"'{ref.root}' is already bound by inputs: — use the variable {ref.root} instead of the string "
        f'"{ref.written}".'
        for ref in bound
    )
    return fixes


# — the $${ ERROR —


def _escape_diagnostic(
    node: dict[str, Any], param: str, language: BodyLanguage, written: str, body_line: int, scope: StepScope
) -> Diagnostic:
    location = _location(node, param, body_line)
    where = _where(location)
    located = f"{written} ({where})" if where else written
    escaped = written[2:]  # ``{PRICE}``
    inner = parse_path(escaped[1:-1]) if escaped.endswith("}") and len(escaped) > 2 else None
    in_scope = inner if inner is not None and _owner(scope, inner) else None
    if language == "sh":
        message = (
            f"Step '{node.get('id')}': the command contains the escape {located}. A shell command is plain sh, "
            f"so there is nothing to escape — sh would run $$ as its process id, followed by {escaped}."
        )
        if in_scope is not None:
            name = _env_name(in_scope.raw)
            add = _binding_phrase(node, "env", [(name, in_scope.raw)])
            fix = (
                f"For a dollar sign followed by the value: {add} and write \\$${name} inside double quotes "
                f'— e.g. "value: \\$${name}".'
            )
        else:
            fix = f"Write ${escaped} for a shell expansion."
    else:
        message = (
            f"Step '{node.get('id')}': the code contains the escape {located} inside a Python string. A code "
            "step's code is plain Python, so there is nothing to escape — the string keeps both dollar signs."
        )
        if in_scope is not None:
            name = _code_name(in_scope.raw)
            add = _binding_phrase(node, "inputs", [(name, in_scope.raw)])
            fix = f'For a dollar sign followed by the value: {add} and write f"${{{name}}}".'
        else:
            fix = (
                f"Python needs no escape: write ${escaped} as plain text. For the literal characters $${{ "
                f'split the string: "$$" "{escaped}".'
            )
    return _body_diagnostic(Severity.ERROR, node, param, location, message, [fix], _GUIDE_TOPIC[language])


# — ruling 2: a pflow-only shape naming nothing pflow knows (WARNING, shell only) —


def _foreign_shape_warning(node: dict[str, Any], param: str, text: str, scope: StepScope) -> list[Diagnostic]:
    """``${fecth.stdout}`` — sh cannot expand a field or a ``??``, so it is most likely a
    misspelled step; it may also be another program's own syntax, hence a warning."""
    known = set(scope.names) | scope.step_ids
    shapes = [
        expression
        for expression in parse(text).expressions
        if expression.references
        and not any(ref.root in known for ref in expression.references)
        and (
            len(expression.operands) > 1
            or any(isinstance(segment, Field) for ref in expression.references for segment in ref.path)
        )
    ]
    if not shapes:
        return []
    first = shapes[0]
    ref = first.references[0]
    more = f" (and {len(shapes) - 1} more like it)" if len(shapes) > 1 else ""
    message = (
        f"Step '{node.get('id')}': {text[first.span[0] : first.span[1]]}{more} in the command is not something sh "
        f"can expand, and '{ref.root}' is not a step or input in this workflow. "
        "pflow never fills in ${…} in a command."
    )
    # Stricter than difflib's default: the text may be another language's, and a far-off
    # suggestion (``user`` → ``s``) misleads more than none.
    match = find_similar_items(ref.root, sorted(known), max_results=1, method="fuzzy", cutoff=0.6)
    if match:
        corrected = match[0] + ref.raw[len(ref.root) :]
        name = _env_name(corrected)
        add = _binding_phrase(node, "env", [(name, corrected)])
        fix = f"Did you mean '{match[0]}'? Bind it: {add} and read \"${name}\". {_KEEP_FOREIGN}"
    else:
        fix = f'To use a pflow value, bind it in env: and read "$NAME". {_KEEP_FOREIGN}'
    location = _location(node, param, text.count("\n", 0, first.span[0]))
    return [_body_diagnostic(Severity.WARNING, node, param, location, message, [fix])]


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
    workflow_path: str | None = None,
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
    # STEP 1: non-LLM rejection is shape-agnostic and runs first (see the ordering contract
    # in _validate_cache_block's docstring above). The check is pure
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
            # Dict IR skips the ## Cache parser, so its coalesce rule is restated here.
            if _is_coalesce_var(var_expr):
                diagnostics.append(_make_chunk_coalesce_diagnostic(chunk_name, var_expr, chunk_line))
                continue
            roots = _cache_var_roots(var_expr)
            # Batch-scoped rejection: chunks that vary across calls referencing
            # the same chunk are invalid. ``${item.X}`` and any descendants of
            # batch aliases (a dynamic index's inner reference included) fail this check.
            if any(root in batch_item_aliases for root in roots):
                diagnostics.append(_make_batch_scoped_rejection_diagnostic(chunk_name, var_expr, chunk_line))
                continue
            # Resolution check: every root must be a declared input or an existing node id.
            for root in roots:
                if root not in declared_inputs and root not in nodes_by_id:
                    candidates = sorted(set(nodes_by_id.keys()) | declared_inputs)
                    similar = find_similar_items(root, candidates, max_results=3, method="fuzzy")
                    diagnostics.append(
                        _make_chunk_resolution_diagnostic(chunk_name, var_expr, root, similar, chunk_line)
                    )
                    break

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


def _cache_var_roots(var_expr: str) -> list[str]:
    """The roots a chunk var reads: each root of its one Reference, dynamic-index inner
    references included. An Issue has none (the Issue pass reports it: one diagnostic
    per mistake). Any other var — a literal (``${42}``) — can never render as a chunk,
    so the whole var is its (unresolvable) root.
    """
    template = parse("${" + var_expr + "}")
    if template.issues:
        return []
    expressions = template.expressions
    operands = expressions[0].operands if expressions and expressions[0].raw == var_expr else ()
    if len(operands) == 1 and isinstance(operands[0], Reference):
        return [ref.root for ref in operands[0].references]
    return [var_expr]


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


def _is_coalesce_var(var_expr: str) -> bool:
    expressions = parse("${" + var_expr + "}").expressions
    return bool(expressions) and len(expressions[0].operands) > 1


def _make_chunk_coalesce_diagnostic(chunk_name: str, var_expr: str, chunk_line: int | None) -> Diagnostic:
    """The ``## Cache`` parser's coalesce rule, for dict IR (which skips the parser)."""
    context: dict[str, Any] = {"category": "validation", "path": f"cache.items[name={chunk_name}].var"}
    if chunk_line is not None:
        context["line"] = chunk_line
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        message=f"coalesce is not supported in a ## Cache chunk: '${{{var_expr}}}'.",
        suggestions=["Reference one value per chunk; compute a fallback in an upstream step and cache its output."],
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
    workflow_path: str | None,
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
    # Lazy import: cache_overlap → core.templates is the same dependency
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


def _literal_non_one_temperature(temperature: Any) -> float | None:
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


def _extract_thinking_temp_violation(node: dict[str, Any]) -> tuple[str, str, str, float] | None:
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
    workflow_path: str | None = None,
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
