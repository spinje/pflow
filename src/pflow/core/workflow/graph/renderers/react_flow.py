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
from dataclasses import asdict, dataclass
from typing import Any

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


def render_react_flow(graph: GraphModel) -> RFGraph:
    """Translate a workflow graph model into a React Flow-native payload."""
    return _ReactFlowRenderer(graph).render()


@dataclass
class _ReactFlowRenderer:
    graph: GraphModel

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
        # Per-decision-node memo for fail-closed condition extraction (one AST
        # parse per decision node, not per branch edge).
        self._conditions_by_node: dict[NodeId, dict[str, str]] = {}

    def render(self) -> RFGraph:
        return RFGraph(
            nodes=[self._node(node) for node in self._kept_nodes],
            edges=self._resolve_edges(),
            groups=[self._group(container) for container in self._kept_containers],
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
            io=asdict(node.io) if node.io is not None else None,
            loop=asdict(node.loop) if node.loop is not None else None,
            batch=asdict(node.batch) if node.batch is not None else None,
            parent=self._group_id_map.get(node.parent) if node.parent is not None else None,
            source=asdict(node.source) if node.source is not None else None,
            is_decision=self.graph.is_decision(node.id),
            is_terminal=self.graph.is_terminal(node.id),
            is_group_host=self._is_group_host(node),
            is_transform=self._is_transform(node),
            unexpanded=node.unexpanded,
            annotations=dict(node.annotations),
        )

    def _is_transform(self, node: Node) -> bool:
        code = node.params.get("code") if node.kind == "code" else None
        return _is_transform_code(code) if isinstance(code, str) else False

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
        (output-source / batch-items / multi-role-dedup), which attach at node level.
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
            key = (source, target, edge.kind, edge.label, output_field, input_name)
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
        literal batch (item boxes) or an expanded sub-workflow (incl. a dynamic
        batch's representative body). Dynamic-batch / unexpanded hosts have no
        expanded body, so they stay leaf boxes with a badge. The loop/batch badge is
        always read off the host node, so ``host`` is intentionally not 1:1 with a
        single group (a dynamic-batch-of-subworkflow hosts both a batch and a
        workflow container).
        """
        if node.batch is not None and not node.batch.dynamic:
            return True
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
    (the value itself if a string, else a dict's string values — one level,
    mirroring build.py's ``_params_strings`` so this can never disagree with the
    DATA_FLOW edges). Using the extractor rather than a raw ``${`` substring check
    means literal operands like ``${5}`` correctly read as NOT dynamic.
    """
    return any(source_refs_in(leaf) for leaf in _string_leaves(value))


def _string_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [leaf for leaf in value.values() if isinstance(leaf, str)]
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
    assigns_result = False
    for n in ast.walk(tree):
        if _transform_disqualifies(n, bound):
            return False
        assigned = _assigned_names(n)
        if "next" in assigned:
            return False  # routing — a decider, not a transform
        assigns_result = assigns_result or "result" in assigned
    return assigns_result
