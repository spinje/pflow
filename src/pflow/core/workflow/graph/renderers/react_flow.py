"""Render a GraphModel as a React Flow-native payload (Task 168).

A second renderer alongside ``render_mermaid``. It consumes only the
``GraphModel`` and its derived views and emits a typed, React-Flow-native
payload (``RFGraph``) that ``asdict`` + ``json.dumps`` round-trips. Unlike raw
``asdict(GraphModel)`` it flattens the nested ``NodeId`` into a stable string
``id`` (while keeping the structural ``ref`` as the future runtime-overlay join
key), maps containers to ``parentNode``-style group ids, and bakes the model's
derived predicates (``is_decision`` / ``is_terminal`` / ``shadowed``) as facts so
the frontend never re-implements model semantics.

The payload carries **no positions and no colors/shapes** — layout and styling
are the frontend's. Predicates ship as facts; the frontend owns visual policy
(e.g. how to treat ``shadowed`` per density mode) — this renderer must NOT copy
Mermaid's narrower render-time shadowing rule.
"""

from __future__ import annotations

import ast
import dataclasses
from dataclasses import asdict, dataclass
from typing import Any

from pflow.core.security_utils import is_sensitive_parameter
from pflow.core.workflow.graph.model import (
    AncestorStep,
    Container,
    EdgeKind,
    GraphModel,
    Node,
    NodeId,
)
from pflow.core.workflow.graph.scope import source_refs_in


@dataclass(frozen=True)
class RFRef:
    """Structural join key — the identity a future runtime overlay joins onto.

    Mirrors ``NodeId``: body-node identity is ``(node_id, ancestor_path)``;
    ``port`` is set only on the never-traced synthetic IO nodes (``None`` for body
    nodes). ``ancestor_path`` carries ``batch_index`` explicitly (``None`` for
    dynamic batches) so the join key stays stable.
    """

    node_id: str
    ancestor_path: list[dict[str, Any]]
    port: str | None


@dataclass(frozen=True)
class RFParam:
    name: str
    value: Any
    is_dynamic: bool
    source: dict[str, Any] | None


@dataclass(frozen=True)
class RFResultKey:
    name: str
    data_type: str | None


@dataclass(frozen=True)
class RFOutputShape:
    """What a node's structured output provably looks like (the authored shape).

    ``field`` names the output port the shape describes — where the node
    actually WRITES: ``"result"`` for code (AST-extracted) and structured
    claude-code (``output_schema`` → parsed value in ``result``), ``"response"``
    for structured llm (its parsed value lands in ``response``, never
    ``result``). ``data_type`` is the authored annotation / schema type (None
    when not provable). ``keys`` are the authored keys with best-effort value
    types — None whenever not statically certain (multiple assignments,
    mutations, empty/non-literal dicts, non-object schemas). FAIL-CLOSED at
    every step: never a partial keys list — a shape row that lies is worse
    than no row. A non-None shape with data_type AND keys None is a valid
    state: it asserts only "this code provably assigns ``result``" (e.g.
    ``result = compute()``) with nothing further provable.
    """

    field: str
    data_type: str | None
    keys: list[RFResultKey] | None


@dataclass(frozen=True)
class RFNode:
    id: str
    ref: RFRef
    kind: str
    purpose: str
    params: list[RFParam]
    io: dict[str, Any] | None
    loop: dict[str, Any] | None
    batch: dict[str, Any] | None
    parent: str | None
    source: dict[str, Any] | None
    is_decision: bool
    is_terminal: bool
    is_group_host: bool
    # A pure data TRANSFORM: a code node whose AST provably only reshapes its
    # inputs into ``result`` — no external effects, no ``next`` routing (a pure
    # decider is a CONDITION, never both). Classified FAIL-CLOSED by
    # ``_is_transform_code``: anything unrecognized stays plain code. Like the
    # other ``is_*`` facts the frontend must not re-derive this — unlike them it
    # CANNOT (it needs the AST).
    is_transform: bool
    # The authored shape of the node's structured output (annotation/schema +
    # keys), extracted fail-closed; `shape.field` names the port it describes
    # (code/claude-code → "result", structured llm → "response"). Ships for ALL
    # code nodes (D9 — run-validate's annotation is just as true as a
    # transform's; display policy is the frontend's) and for schema'd
    # claude-code/llm. None whenever nothing is provable.
    output_shape: RFOutputShape | None
    # The node's cached system prefix as authored TEMPLATE text (the model's
    # ``Node.cached_prefix``): per consumed ``## Cache`` chunk, declaration
    # order, ``prose_before + ${var}`` — display-ready for "what will the
    # prompt look like". None when the node consumes no chunks.
    cached_prefix: str | None
    unexpanded: str | None
    annotations: dict[str, Any]


@dataclass(frozen=True)
class RFEdge:
    id: str
    source: str
    target: str
    kind: str
    label: str | None
    output_field: str | None
    input_name: str | None
    shadowed: bool
    # The source-code condition that selects this branch outcome (e.g.
    # "if len(items) > 5", "else"), extracted fail-closed from the decision
    # node's code by ``_branch_conditions``. ``None`` on non-branch edges and
    # whenever extraction could not be done SAFELY — absent beats wrong.
    condition: str | None = None
    # The ref's sub-path below ``output_field``: ``${gen.result.ok}`` ships
    # ["ok"]. Cleared with ``output_field`` on truncation re-anchoring (a
    # re-anchored endpoint no longer names a real port).
    output_path: list[str] = dataclasses.field(default_factory=list)


@dataclass(frozen=True)
class RFGroup:
    id: str
    kind: str
    parent: str | None
    host: str | None
    members: list[str]
    nesting_depth: int
    annotations: dict[str, Any]


@dataclass(frozen=True)
class RFGraph:
    nodes: list[RFNode]
    edges: list[RFEdge]
    groups: list[RFGroup]
    # kind -> output field -> declared type, for kinds present in this graph.
    # PLATFORM facts (the registry's parsed docstring interfaces), injected by
    # the caller — the renderer never reads the registry itself, and the model
    # never carries them (they are not workflow-authored data). The frontend
    # uses them as the LAST type fallback on output rows that already exist;
    # they never create a row. Per-node authored shapes always win.
    kind_output_types: dict[str, dict[str, str]] = dataclasses.field(default_factory=dict)


def render_react_flow(graph: GraphModel, *, kind_output_types: dict[str, dict[str, str]] | None = None) -> RFGraph:
    """Translate a workflow graph model into a React Flow-native payload.

    ``kind_output_types`` is the registry's kind -> output field -> type map
    (``Registry.output_types_by_kind()``); the renderer ships only the kinds
    actually present in the graph.
    """
    return _ReactFlowRenderer(graph, kind_output_types or {}).render()


@dataclass
class _ReactFlowRenderer:
    graph: GraphModel
    kind_output_types: dict[str, dict[str, str]] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        self.nodes_by_id: dict[NodeId, Node] = {node.id: node for node in self.graph.nodes}
        self._workflow_host_ids = {
            container.host
            for container in self.graph.containers
            if container.kind == "workflow" and container.host is not None
        }
        # Bound the inline-all-params payload against batch-x-depth fan-out: a child
        # under a 50-item literal batch would otherwise inline its prompts 50x.
        # Mirror Mermaid's representative-item truncation — keep nodes under the
        # first ≤2 hidden-batch items only; the full per-item descriptors still ride
        # the host's ``batch.items`` (small) and the count via ``batch.count``.
        self._kept_nodes = [node for node in self.graph.nodes if not self._path_hidden(node.id.ancestor_path)]
        self._kept_containers = [
            container for container in self.graph.containers if not self._path_hidden(_container_level_path(container))
        ]
        self._node_id_map: dict[NodeId, str] = {node.id: f"n{i}" for i, node in enumerate(self._kept_nodes)}
        self._group_id_map: dict[str, str] = {c.id: f"g{j}" for j, c in enumerate(self._kept_containers)}
        # Literal-batch hosts whose batch container actually holds expanded item
        # containers (sub-workflow items). A literal batch of a LEAF creates a batch
        # container with NO members and NO child containers (leaf items are
        # BatchSpec.items data, never nodes) — such a host has no body to draw and
        # must stay a leaf box (deck + xN chip), not a suppressed group host.
        kept_parents = {c.parent for c in self._kept_containers if c.parent is not None}
        self._literal_batch_hosts_with_items = {
            c.host for c in self._kept_containers if c.kind == "batch" and c.host is not None and c.id in kept_parents
        }
        # Per-decision-node memo for fail-closed condition extraction (one AST
        # parse per decision node, not per branch edge).
        self._conditions_by_node: dict[NodeId, dict[str, str]] = {}

    def render(self) -> RFGraph:
        kinds_present = {node.kind for node in self._kept_nodes}
        return RFGraph(
            nodes=[self._node(node) for node in self._kept_nodes],
            edges=self._resolve_edges(),
            groups=[self._group(container) for container in self._kept_containers],
            kind_output_types={
                kind: fields for kind, fields in self.kind_output_types.items() if kind in kinds_present
            },
        )

    def _node(self, node: Node) -> RFNode:
        return RFNode(
            id=self._node_id_map[node.id],
            ref=RFRef(
                node_id=node.id.node_id,
                ancestor_path=[
                    {"node_id": step.node_id, "batch_index": step.batch_index} for step in node.id.ancestor_path
                ],
                port=node.id.port,
            ),
            kind=node.kind,
            purpose=node.purpose,
            params=[self._param(node, name, value) for name, value in node.params.items()],
            io=self._io(node),
            loop=asdict(node.loop) if node.loop is not None else None,
            batch=asdict(node.batch) if node.batch is not None else None,
            parent=self._group_id_map.get(node.parent) if node.parent is not None else None,
            source=asdict(node.source) if node.source is not None else None,
            is_decision=self.graph.is_decision(node.id),
            is_terminal=self.graph.is_terminal(node.id),
            is_group_host=self._is_group_host(node),
            is_transform=self._is_transform(node),
            output_shape=self._output_shape(node),
            cached_prefix=node.cached_prefix,
            unexpanded=node.unexpanded,
            annotations=dict(node.annotations),
        )

    def _is_transform(self, node: Node) -> bool:
        code = node.params.get("code") if node.kind == "code" else None
        return _is_transform_code(code) if isinstance(code, str) else False

    def _output_shape(self, node: Node) -> RFOutputShape | None:
        # A BATCHED node's output is NOT its per-item shape. The engine
        # overwrites shared[node_id] with the 6-key batch aggregate
        # ({results, count, success_count, error_count, errors, batch_metadata}
        # — batch_executor.build_batch_output); the per-item `result`/`response`
        # lives INSIDE each `results` element, never at the top level
        # (`${node.response}` would not resolve). Emitting the per-item shape
        # would name a port that does not exist. Fail closed (absent beats
        # wrong) — a real `${node.results}` read still surfaces a `results` row
        # via the observed-reads path.
        if node.batch is not None:
            return None
        if node.kind == "code":
            code = node.params.get("code")
            return _result_shape_from_code(code) if isinstance(code, str) else None
        # Structured-output nodes: the output_schema IS the authored shape. The
        # FIELD differs per kind — and must match where the node actually
        # writes, or the rows would describe a port that doesn't exist:
        # claude-code parses into `result` (claude_code.py "Writes:"), llm
        # into `response` (llm.py "Writes:").
        if node.kind == "claude-code":
            return _llm_kind_shape(node, field="result")
        if node.kind == "llm":
            return _llm_kind_shape(node, field="response")
        return None

    def _io(self, node: Node) -> dict[str, Any] | None:
        """The node's ``io`` payload, with the ``sensitive`` fact for INPUT nodes.

        ``sensitive`` is attached HERE (the renderer seam), for ``kind == "input"``
        nodes ONLY — not on the ``IOPort`` dataclass: that model is
        renderer-agnostic, and since the wire ships ``asdict(node.io)`` putting the
        flag on the dataclass would also leak it onto OUTPUT nodes. It drives the
        run form's "provided from settings/env" hint (Task 175); the client reads
        it only as a hint and never re-derives the redaction rule.
        ``is_sensitive_parameter`` is the single word-boundary rule (security_utils).
        """
        if node.io is None:
            return None
        io = asdict(node.io)
        if node.kind == "input":
            io["sensitive"] = is_sensitive_parameter(node.id.node_id)
        return io

    def _param(self, node: Node, name: str, value: Any) -> RFParam:
        source = node.param_sources.get(name)
        return RFParam(
            name=name,
            value=value,
            is_dynamic=_param_is_dynamic(value),
            source=asdict(source) if source is not None else None,
        )

    def _resolve_edges(self) -> list[RFEdge]:
        """Emit every edge, re-anchoring any endpoint hidden by batch truncation.

        Edges are **additive** — including DATA_FLOW edges with ``input_name=None``
        (output-source / batch-items / truncation re-anchoring), which attach at
        node level. ``input_name="prompt_cache"`` is reserved: a ``## Cache``
        chunk dependency (no param row exists for it — present it as the cached
        prompt prefix, never a binding).
        Truncation removes hidden batch-item bodies, but the batch **host** stands in
        for the collapsed remainder: an edge crossing the truncation boundary (one
        kept endpoint, one hidden) re-attaches to the hidden side's host rather than
        being silently dropped — the same "degrade to node level, never omit"
        principle the contract already applies to ``input_name=None``, and the parity
        of Mermaid's arrow into the ``xN`` procs box. The re-anchored endpoint's role
        label (``input_name``/``output_field``) is cleared, since it no longer names a
        real port of the host. Edges whose two endpoints collapse to the same anchor
        (both under one hidden item) become self-loops and are dropped; re-anchoring
        then dedupes the N identical host-level edges down to one.
        """
        seen: set[tuple[Any, ...]] = set()
        resolved: list[RFEdge] = []
        for edge in self.graph.edges:
            source = self._visible_anchor(edge.source)
            target = self._visible_anchor(edge.target)
            if source is None or target is None or source == target:
                continue
            output_field = edge.output_field if source == edge.source else None
            input_name = edge.input_name if target == edge.target else None
            # Same rule as output_field: a re-anchored source no longer names a
            # real port, so the sub-path is cleared with it.
            output_path = list(edge.output_path) if source == edge.source else []
            # output_path is part of identity here: two sub-key refs in ONE
            # output `source:` expression (site 2 never dedups at build) must
            # keep both edges — collapsing them would render the second key as
            # quiet-unread. Re-anchored edges clear the path above, so the
            # truncation dedup (N item edges -> one host edge) is unaffected.
            key = (source, target, edge.kind, edge.label, output_field, input_name, tuple(output_path))
            if key in seen:
                continue
            seen.add(key)
            resolved.append(
                RFEdge(
                    id=f"e{len(resolved)}",
                    source=self._node_id_map[source],
                    target=self._node_id_map[target],
                    kind=edge.kind.value,
                    label=edge.label,
                    output_field=output_field,
                    input_name=input_name,
                    shadowed=self.graph.shadowed(edge),
                    condition=self._branch_condition(edge.source, edge.kind, edge.label),
                    output_path=output_path,
                )
            )
        return resolved

    def _branch_condition(self, source: NodeId, kind: EdgeKind, label: str | None) -> str | None:
        """The source-code condition selecting this branch outcome, or None.

        Keyed off the edge's ORIGINAL source (a re-anchored branch edge still
        describes the same decision). Only decision code nodes are analyzed; the
        kind gate is defensive (multi-way routing is code-only today).

        A decision's END edge is the "end" OUTCOME (a dynamic ``next="end"`` arm
        becomes an END edge, never a BRANCH), so it gets the condition extracted
        for ``"end"``. The ``is_decision`` gate keeps a static ``- next: end``
        route condition-free — single-outcome routing decides nothing.
        """
        if kind == EdgeKind.BRANCH and label is not None:
            outcome = label
        elif kind == EdgeKind.END and self.graph.is_decision(source):
            outcome = "end"
        else:
            return None
        if source not in self._conditions_by_node:
            node = self.nodes_by_id.get(source)
            code = node.params.get("code") if node is not None and node.kind == "code" else None
            self._conditions_by_node[source] = _branch_conditions(code) if isinstance(code, str) else {}
        return self._conditions_by_node[source].get(outcome)

    def _group(self, container: Container) -> RFGroup:
        return RFGroup(
            id=self._group_id_map[container.id],
            kind=container.kind,
            parent=self._group_id_map.get(container.parent) if container.parent is not None else None,
            host=self._node_id_map.get(container.host) if container.host is not None else None,
            members=[self._node_id_map[member] for member in container.members if member in self._node_id_map],
            nesting_depth=container.nesting_depth,
            annotations=dict(container.annotations),
        )

    def _is_group_host(self, node: Node) -> bool:
        """Whether the frontend suppresses this node's leaf box and draws a group.

        A node is materialized as a group when it hosts an expanded child body — a
        literal batch with expanded ITEM CONTAINERS (sub-workflow items) or an
        expanded sub-workflow (incl. a dynamic batch's representative body). A
        literal-batched LEAF has no item containers (leaf items are data, not
        nodes), so it stays a leaf box — like dynamic-batch / unexpanded hosts,
        which have no expanded body either. The loop/batch badge is always read off
        the host node, so ``host`` is intentionally not 1:1 with a single group (a
        dynamic-batch-of-subworkflow hosts both a batch and a workflow container).
        """
        if node.batch is not None and not node.batch.dynamic:
            return node.id in self._literal_batch_hosts_with_items
        return node.id in self._workflow_host_ids and node.unexpanded is None

    def _path_hidden(self, ancestor_path: tuple[AncestorStep, ...]) -> bool:
        """Whether a node/container lives under a truncated literal-batch item."""
        prefix: tuple[AncestorStep, ...] = ()
        for step in ancestor_path:
            if step.batch_index is not None and self._is_hidden_index(NodeId(step.node_id, prefix), step.batch_index):
                return True
            prefix = (*prefix, step)
        return False

    def _visible_anchor(self, node_id: NodeId) -> NodeId | None:
        """Resolve a node to the kept node that represents it on-canvas.

        A kept node resolves to itself. A node hidden by batch truncation resolves to
        the host of the **outermost** hidden batch step in its path — the batch host
        stands in for its collapsed items. That host lives at a level with no hidden
        steps above it, so it is always kept; ``None`` is a defensive fallback only.
        """
        if node_id in self._node_id_map:
            return node_id
        prefix: tuple[AncestorStep, ...] = ()
        for step in node_id.ancestor_path:
            if step.batch_index is not None:
                host = NodeId(step.node_id, prefix)
                if self._is_hidden_index(host, step.batch_index):
                    return host if host in self._node_id_map else None
            prefix = (*prefix, step)
        return None

    def _is_hidden_index(self, host: NodeId, batch_index: int) -> bool:
        """Whether ``batch_index`` falls outside ``host``'s representative window.

        All items are visible when ≤4, else only the first 2 — matching Mermaid's
        ``_visible_batch_indexes``. Dynamic batches carry ``batch_index=None`` and
        never reach here (one representative body, never hidden).
        """
        host_node = self.nodes_by_id.get(host)
        if host_node is None or host_node.batch is None or host_node.batch.count is None:
            return False
        visible = host_node.batch.count if host_node.batch.count <= 4 else 2
        return batch_index >= visible


def _container_level_path(container: Container) -> tuple[AncestorStep, ...]:
    """The ancestor path a container lives at (for batch-truncation visibility)."""
    if container.members:
        return container.members[0].ancestor_path
    if container.host is not None:
        return (*container.host.ancestor_path, AncestorStep(container.host.node_id))
    return ()


def _param_is_dynamic(value: Any) -> bool:
    """Whether an authored param value carries a runtime template ref.

    Runs the shared ``source_refs_in`` extractor over the value's string leaves
    (recursing dicts AND lists to any depth, mirroring build.py's
    ``_params_strings`` so this can never disagree with the DATA_FLOW edges:
    ``is_dynamic=True`` ⟺ a DATA_FLOW edge exists for this param's refs). Using
    the extractor rather than a raw ``${`` substring check means literal
    operands like ``${5}`` correctly read as NOT dynamic.
    """
    return any(source_refs_in(leaf) for leaf in _string_leaves(value))


def _string_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [leaf for nested in value.values() for leaf in _string_leaves(nested)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _string_leaves(item)]
    return []


# ── Branch-condition extraction (fail-closed) ─────────────────────────────────
#
# A decision code node selects its outcome by assigning `next` — the condition
# that picks each outcome exists only inside that Python code (unlike loops,
# whose condition is declared on LoopSpec). We recover it by AST analysis,
# FAIL-CLOSED: anything not provably one of the supported shapes yields {} and
# the edge ships condition=None — absent labels beat wrong labels.
#
# Supported shapes (validated against the full example corpus, 2026-06-10):
#   - one if/elif/else chain whose arms assign `next` a string literal
#   - an unconditional default before the chain (the uncovered outcome → "else")
#   - ternaries, normalized into chain arms:
#       top level / else slot:  next = "a" if t else "b"  →  if t: a / else: b
#       inside an arm (kw test): → "kw test and t" / "kw test and <negated t>"
#   - the same outcome in ADJACENT plain arms, joined: "if t1 or t2" (adjacency
#     keeps the elif guard semantics exact; non-adjacent duplicates bail)

_COMPARE_FLIPS: dict[type[ast.cmpop], str] = {
    ast.Eq: "!=",
    ast.NotEq: "==",
    ast.Lt: ">=",
    ast.Gt: "<=",
    ast.LtE: ">",
    ast.GtE: "<",
}


class _ConditionBail(Exception):
    """The code is not provably one of the supported shapes — emit no conditions."""


def _assigned_next(stmt: ast.AST) -> ast.expr | None:
    """The value expression if ``stmt`` assigns the name ``next``, else None."""
    targets: list[ast.expr]
    value: ast.expr | None
    if isinstance(stmt, ast.Assign):
        targets, value = stmt.targets, stmt.value
    elif isinstance(stmt, ast.AnnAssign):
        targets, value = [stmt.target], stmt.value
    else:
        return None
    if value is not None and any(isinstance(t, ast.Name) and t.id == "next" for t in targets):
        return value
    return None


def _str_const(expr: ast.expr) -> str | None:
    return expr.value if isinstance(expr, ast.Constant) and isinstance(expr.value, str) else None


def _negated(test: ast.expr) -> str:
    """Readable negation: flip a single simple comparison, else ``not (...)``."""
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and type(test.ops[0]) in _COMPARE_FLIPS:
        op = _COMPARE_FLIPS[type(test.ops[0])]
        return f"{ast.unparse(test.left)} {op} {ast.unparse(test.comparators[0])}"
    return f"not ({ast.unparse(test)})"


# One normalized chain arm: (test_source | None for the else arm, outcome).
_Arm = tuple[str | None, str]


def _expand_arm(value: ast.expr, arm_test: str | None) -> list[_Arm]:
    """Normalize one ``next = ...`` value into arms, composed with the arm's test."""
    if isinstance(value, ast.IfExp):
        body, orelse = _str_const(value.body), _str_const(value.orelse)
        if body is None or orelse is None or body == orelse:
            raise _ConditionBail("non-literal or degenerate ternary")
        test = ast.unparse(value.test)
        if arm_test is None:  # else slot (or top level): the ternary EXTENDS the chain
            return [(test, body), (None, orelse)]
        return [(f"{arm_test} and {test}", body), (f"{arm_test} and {_negated(value.test)}", orelse)]
    literal = _str_const(value)
    if literal is None:
        raise _ConditionBail("non-literal next")
    return [(arm_test, literal)]


def _sole_assignment(body: list[ast.stmt]) -> ast.expr:
    """The arm's single top-level ``next`` assignment; bail on 0, >1, or nested."""
    top = [v for s in body for v in [_assigned_next(s)] if v is not None]
    deep = [n for s in body for n in ast.walk(s) if _assigned_next(n) is not None]
    if len(top) != 1 or len(deep) != 1:
        raise _ConditionBail("arm needs exactly one top-level next assignment")
    return top[0]


def _branch_conditions(code: str) -> dict[str, str]:
    """Outcome -> condition text (e.g. ``"if len(items) > 5"``); {} when unsafe."""
    try:
        return _extract_conditions(code)
    except (_ConditionBail, SyntaxError):
        return {}


def _extract_conditions(code: str) -> dict[str, str]:
    tree = ast.parse(code)
    total = sum(1 for n in ast.walk(tree) if _assigned_next(n) is not None)
    if total == 0:
        raise _ConditionBail("no next assignment")
    arms, default, modeled = _collect_arms(tree)
    if modeled != total:
        raise _ConditionBail("unaccounted next assignments")
    return _render_conditions(arms, default)


def _collect_arms(tree: ast.Module) -> tuple[list[_Arm], str | None, int]:
    """Walk the module body into normalized chain arms + an optional default.

    Returns ``(arms, default, modeled)`` where ``modeled`` counts the
    next-assignments structurally understood — the caller checks it against the
    whole-tree total so an assignment hiding anywhere unexpected bails.
    """
    arms: list[_Arm] = []
    default: str | None = None
    modeled = 0
    for stmt in tree.body:
        value = _assigned_next(stmt)
        if value is not None:
            if arms or default is not None:
                raise _ConditionBail("second default / assignment after the chain")
            modeled += 1
            if isinstance(value, ast.IfExp):
                arms.extend(_expand_arm(value, None))  # a top-level ternary IS the chain
            else:
                literal = _str_const(value)
                if literal is None:
                    raise _ConditionBail("non-literal next")
                default = literal
        elif isinstance(stmt, ast.If) and any(_assigned_next(n) is not None for n in ast.walk(stmt)):
            if arms:
                raise _ConditionBail("two chains")
            chain_arms, chain_count = _walk_chain(stmt)
            arms.extend(chain_arms)
            modeled += chain_count
        elif any(_assigned_next(n) is not None for n in ast.walk(stmt)):
            raise _ConditionBail("next assigned inside another block")
    return arms, default, modeled


def _walk_chain(stmt: ast.If) -> tuple[list[_Arm], int]:
    """Normalize one if/elif/else chain into arms; count its next-assignments."""
    arms: list[_Arm] = []
    count = 0
    cursor: ast.stmt | None = stmt
    while isinstance(cursor, ast.If):
        arms.extend(_expand_arm(_sole_assignment(cursor.body), ast.unparse(cursor.test)))
        count += 1
        if len(cursor.orelse) == 1 and isinstance(cursor.orelse[0], ast.If):
            cursor = cursor.orelse[0]  # elif
        elif cursor.orelse:
            arms.extend(_expand_arm(_sole_assignment(cursor.orelse), None))
            count += 1
            cursor = None
        else:
            cursor = None
    return arms, count


def _arm_text(arms: list[_Arm], i: int) -> str:
    """One arm rendered with its own chain keyword — the file's verbatim text."""
    test = arms[i][0]
    if test is None:
        return "else"
    return ("if " if i == 0 else "elif ") + test


def _render_conditions(arms: list[_Arm], default: str | None) -> dict[str, str]:
    by_outcome: dict[str, list[int]] = {}
    for i, (_, outcome) in enumerate(arms):
        by_outcome.setdefault(outcome, []).append(i)

    mapping: dict[str, str] = {}
    for outcome, positions in by_outcome.items():
        if len(positions) == 1:
            mapping[outcome] = _arm_text(arms, positions[0])
            continue
        # Duplicate outcome, ADJACENT plain arms (no else / and-composed): a plain
        # `or` join is exact under the elif guard semantics.
        tests = [arms[i][0] for i in positions]
        if positions == list(range(positions[0], positions[0] + len(positions))) and not any(
            t is None or " and " in t for t in tests
        ):
            keyword = "if" if positions[0] == 0 else "elif"
            mapping[outcome] = f"{keyword} " + " or ".join(t for t in tests if t is not None)
            continue
        # Other duplicates — non-adjacent arms or an else/composed arm (the
        # continue-or-stop gate `if ok: end / elif …: fix / else: end` is the
        # canonical case) — LIST each selecting arm verbatim, " · "-joined. No
        # inferred disjunction: every fragment is the file's own text, so the
        # label cannot mis-attribute (the fail-closed bar), only abbreviate.
        mapping[outcome] = " · ".join(_arm_text(arms, i) for i in positions)

    # The default survives only when no else arm always overrides it; with an
    # else arm the default is dead code — omit it, don't guess.
    if default is not None and default not in mapping and all(test is not None for test, _ in arms):
        mapping[default] = "else"
    return mapping


# ── TRANSFORM classification (fail-closed purity test) ─────────────────────────
#
# A code node is a pure data TRANSFORM when its AST provably only reshapes inputs
# into ``result``: every construct is from a recognized-pure set, it assigns
# ``result``, and it never assigns ``next`` (a pure decider presents as CONDITION
# — by excluding deciders here, the two roles can never both claim a node).
# FAIL-CLOSED: any import outside the whitelist, any call we can't classify, any
# REFERENCE to an effectful builtin (not just a direct call — ``o = open`` then
# ``o(...)`` must not slip through), or any unrecognized statement shape means the
# node stays plain CODE. A wrong TRANSFORM label would falsely promise "no
# external effects"; absent beats wrong.

_TRANSFORM_MODULES = frozenset({
    "json",
    "re",
    "math",
    "datetime",
    "collections",
    "itertools",
    "textwrap",
    "string",
    "copy",
    "functools",
    "base64",
    "hashlib",
    "statistics",
    "difflib",
})

# Builtins a reshape legitimately calls. Exception constructors are included:
# ``raise ValueError(...)`` is a pure failure path (the engine handles the raise),
# not an external effect. ``next`` here is the ITERATOR builtin — an ASSIGNMENT to
# the name ``next`` is routing and disqualifies separately below.
_TRANSFORM_BUILTINS = frozenset({
    "len",
    "str",
    "int",
    "float",
    "bool",
    "list",
    "dict",
    "set",
    "tuple",
    "sorted",
    "reversed",
    "enumerate",
    "zip",
    "range",
    "min",
    "max",
    "sum",
    "abs",
    "round",
    "any",
    "all",
    "repr",
    "format",
    "isinstance",
    "filter",
    "map",
    "divmod",
    "hash",
    "frozenset",
    "ord",
    "chr",
    "print",
    "next",
    "iter",
    "type",
    "Exception",
    "ValueError",
    "TypeError",
    "RuntimeError",
    "KeyError",
    "IndexError",
    "ZeroDivisionError",
    "StopIteration",
    "AssertionError",
})

# Effectful/dynamic builtins: ANY reference (ast.Name) disqualifies — aliasing,
# passing as an argument, and direct calls all read the name first. Pure
# introspection names (``type``, ``isinstance``) and annotation types
# (``impl: object`` — the code-node input convention) are NOT effects and must
# stay off this list (``object`` here cost two real corpus transforms).
_TRANSFORM_FORBIDDEN_NAMES = frozenset({
    "open",
    "eval",
    "exec",
    "compile",
    "__import__",
    "input",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
    "exit",
    "quit",
})

# Statement shapes that imply effects or dynamism beyond a reshape.
_TRANSFORM_FORBIDDEN_NODES = (
    ast.With,
    ast.AsyncWith,
    ast.AsyncFor,
    ast.AsyncFunctionDef,
    ast.Await,
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
)


def _assigned_names(n: ast.AST) -> set[str]:
    """Names an assignment statement binds (incl. tuple-unpack leaves)."""
    if not isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return set()
    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
    return {leaf.id for t in targets for leaf in ast.walk(t) if isinstance(leaf, ast.Name)}


def _module_scope_walk(tree: ast.Module) -> list[ast.AST]:
    """Every AST node in MODULE scope — never descending into def/class/lambda.

    A ``result`` bound inside a nested ``def`` is that function's LOCAL variable,
    not the node's output; counting it would ship an ``output_shape`` describing a
    port the node never writes (quiet rows that LIE) and could present a
    helper-bearing node as TRANSFORM. Top-level compound statements (if/try/for)
    ARE walked — ``result`` bound there is the module-level name. Comprehensions
    are walked too: a walrus inside one binds in the CONTAINING scope (PEP 572);
    a walrus inside a lambda binds in the lambda's own scope, so lambdas are
    skipped with the other nested scopes.
    """
    found: list[ast.AST] = []
    stack: list[ast.AST] = list(tree.body)
    while stack:
        n = stack.pop()
        found.append(n)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(n))
    return found


def _bound_names(tree: ast.Module) -> set[str]:
    """Every name the code itself binds (assignments, defs, loops, comprehensions,
    imports, walrus, except-as) — calls to these are the author's own pure-checked
    code, not unknown externals."""
    bound: set[str] = set()
    for n in ast.walk(tree):
        bound.update(_assigned_names(n))
        if isinstance(n, (ast.NamedExpr, ast.For, ast.comprehension)):
            bound.update(leaf.id for leaf in ast.walk(n.target) if isinstance(leaf, ast.Name))
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            bound.add(n.name)
        elif isinstance(n, ast.ExceptHandler):
            # `except E as x` — n.name is Optional, so the body must differ from the
            # def/class arm above or ruff SIM114 re-merges them and mypy fails.
            bound.update({n.name} if n.name else ())
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            bound.update(alias.asname or alias.name.split(".")[0] for alias in n.names)
    return bound


def _transform_disqualifies(n: ast.AST, bound: set[str]) -> bool:
    """One AST node that proves the code is NOT a pure transform."""
    if isinstance(n, _TRANSFORM_FORBIDDEN_NODES):
        return True
    if isinstance(n, ast.Name):
        return n.id in _TRANSFORM_FORBIDDEN_NAMES
    if isinstance(n, ast.Import):
        return any(alias.name.split(".")[0] not in _TRANSFORM_MODULES for alias in n.names)
    if isinstance(n, ast.ImportFrom):
        return (n.module or "").split(".")[0] not in _TRANSFORM_MODULES
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
        # A Name call must be a whitelisted builtin or the author's own code
        # (imports are gated above; attribute calls — x.strip(), json.loads —
        # ride the import gate / operate on already-pure values).
        return n.func.id not in _TRANSFORM_BUILTINS and n.func.id not in bound
    return False


def _is_transform_code(code: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    bound = _bound_names(tree)
    for n in ast.walk(tree):
        if _transform_disqualifies(n, bound):
            return False
        if "next" in _assigned_names(n):
            return False  # routing — a decider, not a transform
    # The purity/routing gates above stay WHOLE-tree (fail-closed: a forbidden
    # name anywhere disqualifies), but ``result`` must be assigned at MODULE
    # level — a helper's local ``result`` is not the node's output.
    return any("result" in _assigned_names(n) for n in _module_scope_walk(tree))


# ── Result-shape extraction (fail-closed) ──────────────────────────────────────
#
# What a code node PRODUCES: the authored `result:` annotation plus — when the
# code assigns `result` exactly once, as a non-empty literal dict — its keys
# with best-effort value types. FAIL-CLOSED at every step: anything not
# statically certain ships as None, never a partial keys list. Ships for ALL
# code nodes, not just transforms (D9) — display policy is the frontend's.


def _input_annotations(tree: ast.Module) -> dict[str, str]:
    """Top-level valueless ``name: type`` AnnAssigns — the code-node INPUT
    declaration convention (an AnnAssign WITH a value is an assignment, not a
    declaration — see ``_is_transform_code``'s F10 precedent)."""
    return {
        stmt.target.id: ast.unparse(stmt.annotation)
        for stmt in tree.body
        if isinstance(stmt, ast.AnnAssign) and stmt.value is None and isinstance(stmt.target, ast.Name)
    }


def _result_assignments(tree: ast.Module) -> list[ast.AST]:
    """Every MODULE-scope construct that assigns or mutates ``result``.

    Deliberately the target WALK, not just direct Name targets, so the
    subscript mutation ``result["k"] = v`` counts: a literal dict followed by a
    mutation must ship ``keys=None`` (a strict Name-target reading would ship a
    keys list missing ``k`` — quiet rows that LIE). A walrus counts too. A
    valueless ``result:`` AnnAssign is an INPUT declaration by the code-node
    convention — neither an assignment nor an annotation source. Scoped via
    ``_module_scope_walk``: a ``result`` inside a nested ``def`` is a local, not
    the node's output (review-caught 2026-06-11).
    """
    found: list[ast.AST] = []
    for n in _module_scope_walk(tree):
        if isinstance(n, ast.AnnAssign) and n.value is None:
            continue
        if "result" in _assigned_names(n) or (
            isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name) and n.target.id == "result"
        ):
            found.append(n)
    return found


def _name_in_target(target: ast.AST, name: str) -> bool:
    return any(isinstance(leaf, ast.Name) and leaf.id == name for leaf in ast.walk(target))


def _result_shape_uncertain(tree: ast.Module) -> bool:
    """Mutation/rebinding channels OUTSIDE plain assignments.

    Any of these makes a literal keys list unreliable, so ``keys`` ships None
    (the annotation still ships): a method call or ANY attribute access on
    ``result`` (``result.update(...)`` / ``.pop()`` — distinguishing mutating
    from pure methods would need a whitelist; absent beats wrong), ``del
    result[...]``, and rebinding via ``for``/``with``/comprehension/``match
    ... as``. Aliasing (``r = result; r.update(...)``) is statically invisible
    — accepted residual.
    """
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "result":
            return True
        if isinstance(n, ast.Delete) and any(_name_in_target(t, "result") for t in n.targets):
            return True
        if isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)) and _name_in_target(n.target, "result"):
            return True
        if isinstance(n, (ast.With, ast.AsyncWith)) and any(
            item.optional_vars is not None and _name_in_target(item.optional_vars, "result") for item in n.items
        ):
            return True
        if isinstance(n, ast.MatchAs) and n.name == "result":
            return True
    return False


def _result_annotation(assignments: list[ast.AST]) -> str | None:
    """The authored ``result: T = ...`` annotation, as its authored text
    (``ast.unparse`` — same vocabulary rule as ``_input_annotations``)."""
    for n in assignments:
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "result":
            return ast.unparse(n.annotation)
    return None


# Builtin calls whose return type is a language fact, not an inference. Gated on
# the name not being rebound by the code itself (see _TypeScope.shadowed).
_BUILTIN_RETURNS = {
    "len": "int",
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "list": "list",
    "dict": "dict",
    "set": "set",
    "tuple": "tuple",
    "sorted": "list",
    "repr": "str",
}

# str methods that return str — only applied when the RECEIVER provably types
# as str (a string literal, f-string, or a str-typed name), so `"sep".join(x)`
# resolves while `unknown.join(x)` stays None.
_STR_METHODS = frozenset({
    "join",
    "strip",
    "lstrip",
    "rstrip",
    "format",
    "replace",
    "upper",
    "lower",
    "title",
    "capitalize",
    "removeprefix",
    "removesuffix",
})


@dataclass(frozen=True)
class _TypeScope:
    """Everything _key_type may resolve a name/call against — all authored or
    language-certain, never inferred-by-guess."""

    names: dict[str, str]  # name -> type certain on EVERY module-scope binding
    returns: dict[str, str]  # module-level `def f(...) -> T` -> authored T text
    shadowed: frozenset[str]  # every name the code binds (gates builtin calls)


def _key_type(value: ast.expr, scope: _TypeScope) -> str | None:  # noqa: C901
    """Best-effort type of one literal-dict value (D8) — never guess.

    Every arm is either authored truth (annotations, helper return types) or a
    Python-semantics certainty (a comparison is always bool; ``len`` always
    returns int; same-type operands stay that type). Anything genuinely
    uncertain — conditionally-bound names, unknown calls, mixed-type operands —
    ships None: absent beats wrong.
    """
    if isinstance(value, ast.Constant):
        # A literal None reads as the value "None", not the class "NoneType".
        return "None" if value.value is None else type(value.value).__name__
    if isinstance(value, ast.JoinedStr):
        return "str"
    if isinstance(value, ast.Name):
        return scope.names.get(value.id)
    if isinstance(value, ast.Dict):
        return "dict"
    if isinstance(value, (ast.List, ast.ListComp)):
        return "list"
    if isinstance(value, ast.DictComp):
        return "dict"
    if isinstance(value, (ast.Set, ast.SetComp)):
        return "set"
    if isinstance(value, ast.Tuple):
        return "tuple"
    if isinstance(value, ast.Compare):
        return "bool"
    if isinstance(value, ast.UnaryOp):
        if isinstance(value.op, ast.Not):
            return "bool"
        if isinstance(value.op, (ast.USub, ast.UAdd)):
            t = _key_type(value.operand, scope)
            return t if t in ("int", "float") else None
    if isinstance(value, ast.BoolOp):
        return _unanimous_type(value.values, scope)
    if isinstance(value, ast.IfExp):
        return _unanimous_type([value.body, value.orelse], scope)
    if isinstance(value, ast.BinOp):
        if isinstance(value.op, ast.Div):
            # True division NEVER preserves int (4/2 == 2.0): float whenever
            # both operands are provably numeric, unknowable otherwise.
            operand_types = {_key_type(value.left, scope), _key_type(value.right, scope)}
            return "float" if operand_types <= {"int", "float"} else None
        if isinstance(value.op, ast.Pow):
            return None  # int ** negative-int is float — not type-preserving
        # Other operators: same-type operands keep their type (str+str,
        # int*int, list+list); mixed pairs (str*int) stay None — fail-closed
        # over operator tables.
        return _unanimous_type([value.left, value.right], scope)
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        if value.func.id in scope.returns:
            return scope.returns[value.func.id]
        if value.func.id not in scope.shadowed:
            return _BUILTIN_RETURNS.get(value.func.id)
        return None
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr in _STR_METHODS
        and _key_type(value.func.value, scope) == "str"
    ):
        return "str"
    return None


def _unanimous_type(values: list[ast.expr], scope: _TypeScope) -> str | None:
    types = {_key_type(v, scope) for v in values}
    return types.pop() if len(types) == 1 and None not in types else None


def _module_def_returns(tree: ast.Module) -> dict[str, str]:
    """Module-level ``def f(...) -> T`` return annotations — authored truth for
    typing calls to the author's own helpers. A name defined twice, or also
    assigned as a variable, is dropped (its call type is no longer certain)."""
    returns: dict[str, str] = {}
    dropped: set[str] = set()
    for n in _module_scope_walk(tree):
        if isinstance(n, ast.FunctionDef):
            if n.name in returns or n.name in dropped or n.returns is None:
                dropped.add(n.name)
                returns.pop(n.name, None)
            else:
                returns[n.name] = ast.unparse(n.returns)
        elif _assigned_names(n) & returns.keys():
            for name in _assigned_names(n) & returns.keys():
                dropped.add(name)
                returns.pop(name)
    return returns


def _untypeable_bound_names(n: ast.AST) -> set[str]:
    """Names a binding form binds whose value type is never certain: tuple
    unpack / multi-target assigns, aug-assign, walrus, loop/with targets,
    def/class names, import aliases. (Single-Name Assign/AnnAssign — the
    typeable forms — are the caller's, not handled here.)"""
    targets: list[ast.AST] = []
    if isinstance(n, ast.Assign):
        targets = list(n.targets)
    elif isinstance(n, (ast.AugAssign, ast.NamedExpr, ast.For, ast.comprehension)):
        targets = [n.target]
    elif isinstance(n, (ast.With, ast.AsyncWith)):
        targets = [item.optional_vars for item in n.items if item.optional_vars is not None]
    elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {n.name}
    elif isinstance(n, (ast.Import, ast.ImportFrom)):
        return {alias.asname or alias.name.split(".")[0] for alias in n.names}
    elif isinstance(n, (ast.ExceptHandler, ast.MatchAs)) and n.name is not None:
        return {n.name}
    return {leaf.id for t in targets for leaf in ast.walk(t) if isinstance(leaf, ast.Name)}


def _binding_sites(tree: ast.Module) -> dict[str, list[str | ast.expr | None]]:
    """Per name, every module-scope binding's type contribution: an authored
    annotation text (str), a value expression to resolve via ``_key_type``
    (ast.expr), or a poison marker (None) for forms whose value type is never
    certain (see ``_untypeable_bound_names``)."""
    sites: dict[str, list[str | ast.expr | None]] = {}
    for n in _module_scope_walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            sites.setdefault(n.targets[0].id, []).append(n.value)
        elif isinstance(n, ast.AnnAssign) and n.value is not None and isinstance(n.target, ast.Name):
            sites.setdefault(n.target.id, []).append(ast.unparse(n.annotation))
        else:
            for name in _untypeable_bound_names(n):
                sites.setdefault(name, []).append(None)
    return sites


def _certain_name_types(tree: ast.Module, inputs: dict[str, str], returns: dict[str, str]) -> dict[str, str]:
    """Names whose type is certain on EVERY module-scope binding.

    Each binding site (see ``_binding_sites``) contributes a type; a name
    resolves only when all its sites carry the SAME non-None type. An
    annotated INPUT that the code rebinds is unanimity-checked against its
    annotation too — so ``text: str`` followed by ``text = text.split()``
    correctly reads None, not the stale ``str`` (a latent mislabel before
    this pass existed).

    Resolution runs to a fixed point so locals may reference each other in
    any order; a cycle simply never resolves (fail-closed).
    """
    sites = _binding_sites(tree)
    # A rebound input must agree with its annotation; an untouched input is
    # certain as authored.
    env = {name: t for name, t in inputs.items() if name not in sites}
    for name, t in inputs.items():
        if name in sites:
            sites[name].append(t)

    shadowed = frozenset(_bound_names(tree))
    changed = True
    while changed:
        changed = False
        for name, site_list in sites.items():
            if name in env or any(s is None for s in site_list):
                continue
            # An annotated input seeds its OWN resolution (induction base: the
            # first binding IS the input value), so `text = text.strip()` on a
            # `text: str` input resolves — unanimity then forces every later
            # rebinding to preserve the type, keeping the seed sound.
            seed = inputs.get(name)
            names = env if seed is None else {**env, name: seed}
            scope = _TypeScope(names=names, returns=returns, shadowed=shadowed)
            types = {s if isinstance(s, str) else _key_type(s, scope) for s in site_list if s is not None}
            resolved = types.pop() if len(types) == 1 else None
            if resolved is not None:
                env[name] = resolved
                changed = True
    return env


def _literal_dict_keys(assignments: list[ast.AST], scope: _TypeScope) -> list[RFResultKey] | None:
    """Keys when EVERY module-scope assignment binds the NAME ``result`` to a
    non-empty literal dict with all-string keys AND all assignments agree on
    the key set — the shape is then certain on every execution path (a
    branch-assigned gate node like ``if ok: result = {...} else: result =
    {...}`` qualifies). Differing key sets, an empty literal (almost always a
    to-be-mutated accumulator), or any non-literal-dict assignment → None.
    A key's type ships only when every arm agrees on it."""
    dicts: list[ast.Dict] = []
    for n in assignments:
        if isinstance(n, ast.Assign):
            named = any(isinstance(t, ast.Name) and t.id == "result" for t in n.targets)
            value: ast.expr | None = n.value
        elif isinstance(n, ast.AnnAssign):
            named = isinstance(n.target, ast.Name) and n.target.id == "result"
            value = n.value
        else:
            return None
        if not named or not isinstance(value, ast.Dict) or not value.keys:
            return None
        dicts.append(value)

    arms: list[dict[str, ast.expr]] = []
    for d in dicts:
        arm: dict[str, ast.expr] = {}
        for k, v in zip(d.keys, d.values, strict=True):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                return None  # **spread or non-string key — the full list is uncertain
            arm[k.value] = v
        arms.append(arm)
    first = arms[0]
    if any(arm.keys() != first.keys() for arm in arms[1:]):
        return None
    return [RFResultKey(name=name, data_type=_unanimous_type([arm[name] for arm in arms], scope)) for name in first]


def _shape_from_output_schema(schema: Any, field: str) -> RFOutputShape | None:
    """The authored shape of a structured-output node (claude-code / llm).

    The ``output_schema`` is authored truth — no inference; ``field`` is where
    that kind actually writes the parsed value. FAIL-CLOSED: anything but a
    top-level ``type: object`` schema with a non-empty dict ``properties``
    ships None (a templated ``${...}`` schema is a string; a non-object schema
    produces a value whose keys aren't rows). Key types are the schema's OWN
    vocabulary ("string"/"number"/…) — the authored text, just as code nodes
    ship their annotation's Python names.
    """
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return None
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return None
    keys: list[RFResultKey] = []
    for name, prop in properties.items():
        if not isinstance(name, str):
            return None  # the full key list is uncertain — never partial
        prop_type = prop.get("type") if isinstance(prop, dict) else None
        keys.append(RFResultKey(name=name, data_type=prop_type if isinstance(prop_type, str) else None))
    return RFOutputShape(field=field, data_type="object", keys=keys)


def _result_shape_from_code(code: str) -> RFOutputShape | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    assignments = _result_assignments(tree)
    if not assignments:
        return None
    if _result_shape_uncertain(tree):
        keys = None
    else:
        returns = _module_def_returns(tree)
        scope = _TypeScope(
            names=_certain_name_types(tree, _input_annotations(tree), returns),
            returns=returns,
            shadowed=frozenset(_bound_names(tree)),
        )
        keys = _literal_dict_keys(assignments, scope)
    return RFOutputShape(
        field="result",
        data_type=_result_annotation(assignments),
        keys=keys,
    )


def _llm_kind_shape(node: Node, field: str) -> RFOutputShape | None:
    """The shape of an llm/claude-code node's output port.

    With an output_schema authored, the schema IS the shape (fail-closed
    parse). With NO schema at all, the kind's own contract makes the type
    certain: the node writes free-form text — ``str`` (llm.py /
    claude_code.py "Writes:" — the ``dict`` arm only occurs WHEN a schema is
    set). A schema that is present but unreadable (a templated ``${...}``
    string, a non-object schema) ships None, NOT "str" — the runtime value
    there is parsed JSON, so claiming text would be wrong."""
    schema = node.params.get("output_schema")
    if schema is None:
        return RFOutputShape(field=field, data_type="str", keys=None)
    return _shape_from_output_schema(schema, field=field)
