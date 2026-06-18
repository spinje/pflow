"""Build a renderer-agnostic graph model from workflow IR."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from pflow.core.workflow.graph.model import (
    AncestorStep,
    BatchSpec,
    Container,
    Edge,
    EdgeKind,
    GraphModel,
    IOPort,
    LoopSpec,
    Node,
    NodeId,
    SourceRef,
    UnexpandedReason,
)
from pflow.core.workflow.graph.scope import refs_in, refs_with_path_in
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult
from pflow.core.workflow_id import synthesize_inline_workflow_id

logger = logging.getLogger(__name__)

_WORKFLOW_TYPES = {"workflow", "pflow.runtime.workflow_executor"}
_END_NODE = "__end__"


ResolveChild = Callable[[dict[str, Any], Path | None], SubWorkflowResult | None]


def build_graph(
    ir: dict[str, Any],
    *,
    resolve_child: ResolveChild | None = None,
    base_path: Path | None = None,
    source_file: Path | None = None,
    max_depth: int = 1,
) -> GraphModel:
    """Build a pure structural graph model from a workflow IR."""
    builder = _GraphBuilder(resolve_child=resolve_child, max_depth=max_depth)
    builder.build_level(
        ir,
        ancestor_path=(),
        parent_container=None,
        current_depth=0,
        source_file=source_file,
        base_path=base_path,
    )
    return GraphModel(nodes=builder.nodes, edges=builder.edges, containers=builder.containers)


@dataclass
class _LevelResult:
    inputs: dict[str, NodeId] = field(default_factory=dict)
    outputs: dict[str, NodeId] = field(default_factory=dict)
    nodes: dict[str, NodeId] = field(default_factory=dict)
    produces: dict[NodeId, dict[str, NodeId]] = field(default_factory=dict)
    incoming: dict[NodeId, dict[str, NodeId]] = field(default_factory=dict)
    batch_item_incoming: dict[NodeId, dict[int, dict[str, NodeId]]] = field(default_factory=dict)


@dataclass
class _GraphBuilder:
    resolve_child: ResolveChild | None
    max_depth: int
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    containers: list[Container] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    _container_index: dict[str, Container] = field(default_factory=dict)

    def build_level(
        self,
        ir: dict[str, Any],
        *,
        ancestor_path: tuple[AncestorStep, ...],
        parent_container: str | None,
        current_depth: int,
        source_file: Path | None,
        base_path: Path | None,
    ) -> _LevelResult:
        result = _LevelResult()
        nodes = ir.get("nodes", [])
        raw_edges = ir.get("edges", [])

        result.inputs = self._add_inputs(ir, ancestor_path, parent_container)

        # Pass A: create all node identities, containers, child models, and local
        # routing maps before any data-flow resolution reads them.
        level_nodes: dict[str, Node] = {}
        for raw_node in nodes:
            node_id = NodeId(str(raw_node["id"]), ancestor_path)
            result.nodes[node_id.node_id] = node_id
            node = Node(
                id=node_id,
                kind=str(raw_node.get("type", "unknown")),
                purpose=str(raw_node.get("purpose", "")),
                parent=parent_container,
                loop=_build_loop(raw_node.get("loop"), node_id.node_id),
                batch=_build_batch(raw_node.get("batch")),
                source=_source_ref(raw_node, source_file),
                param_sources=_param_source_refs(raw_node, source_file),
                params=_node_params(raw_node),
            )
            self._add_node(node)
            level_nodes[node_id.node_id] = node

            if parent_container is not None:
                self._container_index[parent_container].members.append(node_id)

        for raw_node in nodes:
            node = level_nodes[str(raw_node["id"])]
            if node.batch is not None:
                self._build_batch_container(
                    raw_node, node, ancestor_path, parent_container, current_depth, source_file, base_path, result
                )
            elif node.kind in _WORKFLOW_TYPES:
                self._try_build_workflow_node(
                    raw_node, node, ancestor_path, parent_container, current_depth, source_file, base_path, result
                )

        # Pass B: all sibling node ids, child input maps, and output maps now
        # exist, so structural and data-flow edges resolve against complete state.
        for raw_edge in _deduplicate_edges(raw_edges):
            source = result.nodes.get(str(raw_edge["from"]))
            target = result.nodes.get(str(raw_edge["to"]))
            if source is None or target is None:
                continue
            self.edges.append(_structural_edge(source, target, raw_edge))

        self._add_routes_to_end(nodes, result, ancestor_path, parent_container)
        self._add_child_input_data_flow(nodes, result)
        self._add_input_consumer_edges(nodes, result)
        self._add_cache_edges(ir, nodes, level_nodes, result)

        result.outputs = self._add_outputs(ir, ancestor_path, parent_container, result, source_file)
        return result

    def _add_node(self, node: Node) -> None:
        self.nodes.append(node)

    def _add_container(self, container: Container) -> Container:
        self.containers.append(container)
        self._container_index[container.id] = container
        return container

    def _add_inputs(
        self,
        ir: dict[str, Any],
        ancestor_path: tuple[AncestorStep, ...],
        parent_container: str | None,
    ) -> dict[str, NodeId]:
        inputs = ir.get("inputs", {})
        if not inputs:
            return {}
        container = self._add_container(
            Container(
                id=_container_id(ancestor_path, "inputs"),
                kind="input_wrapper",
                nesting_depth=len(ancestor_path),
                parent=parent_container,
                annotations=_start_node_annotation(ir),
            )
        )
        result: dict[str, NodeId] = {}
        for name, config in inputs.items():
            node_id = _input_node_id(str(name), ancestor_path)
            result[str(name)] = node_id
            cfg = config if isinstance(config, dict) else {}
            self._add_node(
                Node(
                    id=node_id,
                    kind="input",
                    parent=container.id,
                    purpose=str(cfg.get("description", "")),
                    io=IOPort(
                        data_type=str(cfg.get("type")) if cfg.get("type") else None,
                        # An input that omits `required:` IS required — the
                        # ir_schema-documented default every runtime reader
                        # (validator/executor/context) already applies.
                        required=bool(cfg.get("required", True)),
                        default=cfg.get("default"),
                    ),
                )
            )
            container.members.append(node_id)
        return result

    def _add_outputs(
        self,
        ir: dict[str, Any],
        ancestor_path: tuple[AncestorStep, ...],
        parent_container: str | None,
        level: _LevelResult,
        source_file: Path | None,
    ) -> dict[str, NodeId]:
        outputs = ir.get("outputs", {})
        if not outputs:
            return {}
        container = self._add_container(
            Container(
                id=_container_id(ancestor_path, "outputs"),
                kind="output_wrapper",
                nesting_depth=len(ancestor_path),
                parent=parent_container,
            )
        )
        result: dict[str, NodeId] = {}
        for name, config in outputs.items():
            node_id = _output_node_id(str(name), ancestor_path)
            result[str(name)] = node_id
            self._add_node(
                Node(
                    id=node_id,
                    kind="output",
                    parent=container.id,
                    purpose=str(config.get("description", "")) if isinstance(config, dict) else "",
                    io=IOPort(
                        data_type=str(config.get("type")) if isinstance(config, dict) and config.get("type") else None
                    ),
                    source=_source_ref(config if isinstance(config, dict) else {}, source_file),
                )
            )
            container.members.append(node_id)
            source = config.get("source", "") if isinstance(config, dict) else ""
            self._connect_source_expression(source, node_id, level)
        return result

    def _try_build_workflow_node(
        self,
        raw_node: dict[str, Any],
        node: Node,
        ancestor_path: tuple[AncestorStep, ...],
        parent_container: str | None,
        current_depth: int,
        source_file: Path | None,
        base_path: Path | None,
        level: _LevelResult,
    ) -> None:
        reason, child_result = self._resolve_child_for_node(raw_node, current_depth, base_path)
        if reason is not None:
            node.unexpanded = reason
            return
        if child_result is None or not child_result.ir.get("nodes"):
            node.unexpanded = "unresolved"
            return

        child_key = _child_key(child_result)
        if child_key in self.seen:
            node.unexpanded = "cycle"
            return

        container = self._add_container(
            Container(
                id=_container_id(ancestor_path, f"workflow:{node.id.node_id}"),
                kind="workflow",
                nesting_depth=current_depth + 1,
                host=node.id,
                parent=parent_container,
                annotations=_warnings_annotation(child_result),
            )
        )
        child_base = child_result.path.parent if child_result.path else base_path
        child_file = child_result.path or source_file
        child_path = (*ancestor_path, AncestorStep(node.id.node_id))
        self.seen.add(child_key)
        try:
            child_level = self.build_level(
                child_result.ir,
                ancestor_path=child_path,
                parent_container=container.id,
                current_depth=current_depth + 1,
                source_file=child_file,
                base_path=child_base,
            )
        finally:
            self.seen.discard(child_key)
        level.produces[node.id] = child_level.outputs
        level.incoming[node.id] = child_level.inputs

    def _build_batch_container(
        self,
        raw_node: dict[str, Any],
        node: Node,
        ancestor_path: tuple[AncestorStep, ...],
        parent_container: str | None,
        current_depth: int,
        source_file: Path | None,
        base_path: Path | None,
        level: _LevelResult,
    ) -> None:
        container = self._add_container(
            Container(
                id=_container_id(ancestor_path, f"batch:{node.id.node_id}"),
                kind="batch",
                nesting_depth=current_depth + 1,
                host=node.id,
                parent=parent_container,
            )
        )
        batch = node.batch
        if batch is None or node.kind not in _WORKFLOW_TYPES:
            return

        if batch.dynamic:
            self._build_dynamic_batch_workflow(
                raw_node, node, container, ancestor_path, current_depth, source_file, base_path, level
            )
            return

        for index, item in enumerate(batch.items or []):
            if not isinstance(item, dict):
                continue
            workflow_path = item.get("workflow")
            if not isinstance(workflow_path, str):
                continue  # genuine leaf item, not a sub-workflow expansion
            if workflow_path.startswith("${"):
                _record_unexpanded_item(container, index, "dynamic_path")
                continue
            reason, child_result = self._resolve_literal_batch_item(workflow_path, current_depth, base_path)
            if reason is not None or child_result is None:
                # Mirror the regular/dynamic expansion paths: record WHY this item did
                # not expand so a failed sub-workflow item is distinguishable from a
                # genuine leaf item in the model (the "no information loss" bar).
                _record_unexpanded_item(container, index, reason or "unresolved")
                continue
            child_key = _child_key(child_result)
            if child_key in self.seen:
                # Check the recursion stack BEFORE creating the container so a cycle
                # does not leave an empty workflow container behind (parity with the
                # regular/dynamic paths).
                _record_unexpanded_item(container, index, "cycle")
                continue
            item_path = (*ancestor_path, AncestorStep(node.id.node_id, index))
            item_container = self._add_container(
                Container(
                    id=_container_id(item_path, "item"),
                    kind="workflow",
                    nesting_depth=current_depth + 1,
                    parent=container.id,
                    annotations=_warnings_annotation(child_result),
                )
            )
            self.seen.add(child_key)
            try:
                child_level = self.build_level(
                    child_result.ir,
                    ancestor_path=item_path,
                    parent_container=item_container.id,
                    current_depth=current_depth + 1,
                    source_file=child_result.path or source_file,
                    base_path=child_result.path.parent if child_result.path else base_path,
                )
            finally:
                self.seen.discard(child_key)
            level.batch_item_incoming.setdefault(node.id, {})[index] = child_level.inputs

    def _build_dynamic_batch_workflow(
        self,
        raw_node: dict[str, Any],
        node: Node,
        container: Container,
        ancestor_path: tuple[AncestorStep, ...],
        current_depth: int,
        source_file: Path | None,
        base_path: Path | None,
        level: _LevelResult,
    ) -> None:
        reason, child_result = self._resolve_child_for_node(raw_node, current_depth, base_path)
        if reason is not None:
            node.unexpanded = reason
            return
        if child_result is None or not child_result.ir.get("nodes"):
            node.unexpanded = "unresolved"
            return
        batch_path = (*ancestor_path, AncestorStep(node.id.node_id, None))
        child_key = _child_key(child_result)
        if child_key in self.seen:
            node.unexpanded = "cycle"
            return
        workflow_container = self._add_container(
            Container(
                id=_container_id(batch_path, "dynamic-item"),
                kind="workflow",
                nesting_depth=current_depth + 1,
                host=node.id,
                parent=container.id,
                annotations=_warnings_annotation(child_result),
            )
        )
        self.seen.add(child_key)
        try:
            child_level = self.build_level(
                child_result.ir,
                ancestor_path=batch_path,
                parent_container=workflow_container.id,
                current_depth=current_depth + 1,
                source_file=child_result.path or source_file,
                base_path=child_result.path.parent if child_result.path else base_path,
            )
        finally:
            self.seen.discard(child_key)
        level.produces[node.id] = child_level.outputs
        level.incoming[node.id] = child_level.inputs

    def _resolve_child_for_node(
        self, raw_node: dict[str, Any], current_depth: int, base_path: Path | None
    ) -> tuple[UnexpandedReason | None, SubWorkflowResult | None]:
        if current_depth >= self.max_depth:
            return "depth_limit", None
        params = raw_node.get("params", {})
        workflow_ref = params.get("workflow") if isinstance(params, dict) else None
        if isinstance(workflow_ref, str) and "${" in workflow_ref:
            return "dynamic_path", None
        if self.resolve_child is None:
            return "unresolved", None
        try:
            return None, self.resolve_child(params if isinstance(params, dict) else {}, base_path)
        except Exception:
            logger.debug("Failed to resolve sub-workflow for node '%s'", raw_node.get("id", "?"), exc_info=True)
            return "unresolved", None

    def _resolve_literal_batch_item(
        self, workflow_path: str, current_depth: int, base_path: Path | None
    ) -> tuple[UnexpandedReason | None, SubWorkflowResult | None]:
        if current_depth >= self.max_depth:
            return "depth_limit", None
        if self.resolve_child is None:
            return "unresolved", None
        try:
            result = self.resolve_child({"workflow": workflow_path}, base_path)
        except Exception:
            logger.debug("Failed to resolve batch item workflow '%s'", workflow_path, exc_info=True)
            return "unresolved", None
        if result is None or not result.ir.get("nodes"):
            return "unresolved", None
        return None, result

    def _add_routes_to_end(
        self,
        raw_nodes: list[dict[str, Any]],
        level: _LevelResult,
        ancestor_path: tuple[AncestorStep, ...],
        parent_container: str | None,
    ) -> None:
        end_id: NodeId | None = None
        for raw_node in raw_nodes:
            if raw_node.get("_routes_to_end") is not True:
                continue
            source = level.nodes.get(str(raw_node["id"]))
            if source is None:
                continue
            if end_id is None:
                end_id = NodeId(_END_NODE, ancestor_path)
                self._add_node(Node(id=end_id, kind="end", parent=parent_container))
                if parent_container is not None:
                    self._container_index[parent_container].members.append(end_id)
            self.edges.append(Edge(source=source, target=end_id, kind=EdgeKind.END))

    def _add_child_input_data_flow(self, raw_nodes: list[dict[str, Any]], level: _LevelResult) -> None:
        for raw_node in raw_nodes:
            node_id = level.nodes.get(str(raw_node["id"]))
            if node_id is None:
                continue
            target_inputs = level.incoming.get(node_id, {})
            params = raw_node.get("params")
            inputs_dict = params.get("inputs") if isinstance(params, dict) else None
            if not isinstance(inputs_dict, dict):
                continue
            if node_id in level.batch_item_incoming:
                self._add_literal_batch_item_input_edges(raw_node, node_id, level)
                continue
            for input_name, binding in inputs_dict.items():
                self._add_ref_edges(
                    str(input_name),
                    binding,
                    target_inputs,
                    node_id,
                    level,
                    batch_source=self._resolve_batch_source(raw_node, level),
                    batch_alias=_batch_alias(raw_node),
                )

    def _add_literal_batch_item_input_edges(
        self,
        raw_node: dict[str, Any],
        node_id: NodeId,
        level: _LevelResult,
    ) -> None:
        params = raw_node.get("params")
        inputs_dict = params.get("inputs") if isinstance(params, dict) else None
        if not isinstance(inputs_dict, dict):
            return
        for _index, target_inputs in level.batch_item_incoming.get(node_id, {}).items():
            for input_name, binding in inputs_dict.items():
                if not isinstance(binding, str) or _binding_uses_batch_alias(binding, _batch_alias(raw_node)):
                    continue
                self._add_ref_edges(str(input_name), binding, target_inputs, node_id, level)

    def _add_input_consumer_edges(self, raw_nodes: list[dict[str, Any]], level: _LevelResult) -> None:
        for raw_node in raw_nodes:
            self._add_one_input_consumer_edges(raw_node, level)

    def _add_ref_edges(
        self,
        input_name: str | None,
        binding: Any,
        target_inputs: dict[str, NodeId],
        node_id: NodeId,
        level: _LevelResult,
        batch_source: tuple[NodeId, str | None] | None = None,
        batch_alias: str = "item",
    ) -> None:
        """Emit one DATA_FLOW edge per resolvable ``${ref}`` in authored text.

        THE general-purpose emitter: every resolvable ref — workflow inputs and
        siblings alike, via ``_resolve_ref``'s inputs-first resolution — is one
        edge, deduped by full edge equality. (``_connect_source_expression``
        stays a separate emitter: its no-dedup is load-bearing for sub-key
        output edges.)
        """
        target = target_inputs.get(input_name, node_id) if input_name is not None else node_id
        if not isinstance(binding, str) or "${" not in binding:
            return
        for root, ref_field, ref_path in refs_with_path_in(binding):
            # The batch alias takes precedence over a same-named top-level input: when
            # `as: data` collides with an input also named `data`, an item binding's
            # `${data.x}` must resolve to the batch source, not the input node.
            resolved = batch_source if root == batch_alias else self._resolve_ref(root, ref_field, level)
            if resolved is None:
                continue
            source, output_field = resolved
            if source == target:
                continue
            # The ref's sub-path below the resolved output port: `${gen.result.ok}`
            # carries ("ok",). Only when the first segment IS the resolved port —
            # and NEVER through the batch alias: with `as: item` over
            # `items: ${prep.rows}`, a binding `${item.rows.x}` has first segment
            # "rows" == the batch source's output_field, but attaching ("x",)
            # would describe an edge whose source is prep — the wrong node.
            output_path = ref_path if root != batch_alias and output_field == ref_field else ()
            edge = Edge(
                source=source,
                target=target,
                kind=EdgeKind.DATA_FLOW,
                output_field=output_field,
                input_name=input_name,
                output_path=output_path,
            )
            if edge not in self.edges:
                self.edges.append(edge)

    def _resolve_batch_source(self, raw_node: dict[str, Any], level: _LevelResult) -> tuple[NodeId, str | None] | None:
        batch = raw_node.get("batch")
        items = batch.get("items") if isinstance(batch, dict) else None
        if not isinstance(items, str):
            return None
        for root, ref_field in refs_in(items):
            resolved = self._resolve_ref(root, ref_field, level)
            if resolved is not None:
                return resolved
        return None

    def _add_one_input_consumer_edges(
        self,
        raw_node: dict[str, Any],
        level: _LevelResult,
    ) -> None:
        node_id = level.nodes.get(str(raw_node["id"]))
        if node_id is None:
            return
        # Literal-batch hosts with expanded items already get per-item edges from
        # _add_literal_batch_item_input_edges (mirroring _add_child_input_data_flow's
        # arm) — a host-level duplicate here would sit beside the per-item edges.
        if node_id in level.batch_item_incoming:
            return
        target_inputs = level.incoming.get(node_id, {})
        alias = _batch_alias(raw_node) if isinstance(raw_node.get("batch"), dict) else "item"
        for param_name, ref_value, shallow in _params_strings(raw_node.get("params", {})):
            # Only a binding-level (shallow) name may target a child-input port —
            # a depth-2 dict ref must never claim a child input that happens to
            # share its key's name; `{}` forces the host-level fallback.
            self._add_ref_edges(
                param_name,
                ref_value,
                target_inputs if shallow else {},
                node_id,
                level,
                batch_alias=alias,
            )
        self._add_loop_cap_edges(raw_node, node_id, level)

        batch = raw_node.get("batch")
        items = batch.get("items") if isinstance(batch, dict) else None
        if isinstance(items, str):
            # Expanded (workflow) batches capture a sibling-produced items source via the
            # child-input resolution path. A leaf (non-expanded) batch has no child inputs,
            # so resolve the sibling source onto the host here — otherwise `items: ${prep.rows}`
            # on a leaf batch silently drops the prep->host dependency the model exists to carry.
            if node_id not in level.incoming and node_id not in level.batch_item_incoming:
                self._add_ref_edges(None, items, {}, node_id, level)
            # An expanded dynamic batch over `${docs}` with OPAQUE bindings
            # (`inputs: ${item}`) has no other emitter for the input→batch
            # dependency, so input-rooted items refs land on the host
            # unconditionally; sibling-rooted items stay leaf-only (the guard
            # above — a host-level sibling edge would flip Mermaid's
            # structural-arrow suppression). Input edges cannot flip that
            # suppression (its rules are same-source filtered). On leaf
            # batches this duplicates the pass above and dedup absorbs it.
            for root, _field, _path in refs_with_path_in(items):
                if root not in level.inputs:
                    continue
                edge = Edge(source=level.inputs[root], target=node_id, kind=EdgeKind.DATA_FLOW)
                if edge not in self.edges:
                    self.edges.append(edge)

    def _add_loop_cap_edges(
        self,
        raw_node: dict[str, Any],
        node_id: NodeId,
        level: _LevelResult,
    ) -> None:
        raw_loop = raw_node.get("loop")
        cap = raw_loop.get("max_iterations") if isinstance(raw_loop, dict) else None
        if not isinstance(cap, str) or "${" not in cap:
            return
        self._add_ref_edges("max_iterations", cap, {}, node_id, level)

    def _add_cache_edges(
        self,
        ir: dict[str, Any],
        raw_nodes: list[dict[str, Any]],
        body_nodes: dict[str, Node],
        level: _LevelResult,
    ) -> None:
        """One DATA_FLOW edge per ``## Cache`` chunk a node's ``prompt_cache`` consumes.

        A chunk's ref is FORBIDDEN in the consumer's prompt body (the validator's
        cache.prompt-body-duplicates-cache error), so this edge is the only
        visibility that dependency can ever have. ``## Cache`` is strictly
        per-file: only this level's ``ir`` and this level's resolution scope
        participate. Guarded like ``_node_params`` — build_graph assumes
        pre-validated IR; the validator owns ``cache.*`` errors, so malformed
        shapes just emit nothing.

        Also assembles ``Node.cached_prefix`` from the SAME data: per consumed
        chunk (declaration order), ``prose_before + ${var}`` — the runtime's
        block-assembly rule over the authored template instead of resolved
        values, so the model's text reads as the prompt prefix will.
        """
        cache_block = ir.get("cache")
        if not isinstance(cache_block, dict):
            return
        items = cache_block.get("items") or []
        if not isinstance(items, list):
            return
        chunks = {
            item["name"]: item
            for item in items
            if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("var"), str)
        }
        if not chunks:
            return
        for raw_node in raw_nodes:
            node_id = level.nodes.get(str(raw_node["id"]))
            prompt_cache = raw_node.get("prompt_cache")
            if node_id is None or not isinstance(prompt_cache, list):
                continue
            prefix_parts: list[str] = []
            for entry in prompt_cache:
                chunk = chunks.get(entry) if isinstance(entry, str) else None
                if chunk is None:
                    continue
                var = chunk["var"]
                prose = chunk.get("prose_before")
                prefix_parts.append((prose if isinstance(prose, str) else "") + "${" + var + "}")
                # "${var}" is the established re-wrap pattern (core/prompt_cache.py);
                # resolution, output_field/output_path, the self-edge skip (a
                # producer listing its own chunk draws nothing), and dedup all
                # come from the shared emitter.
                self._add_ref_edges("prompt_cache", "${" + var + "}", {}, node_id, level)
            if prefix_parts:
                body_nodes[node_id.node_id].cached_prefix = "".join(prefix_parts)

    def _connect_source_expression(self, source_expr: str, target: NodeId, level: _LevelResult) -> None:
        if not isinstance(source_expr, str) or "${" not in source_expr:
            return
        for root, ref_field, ref_path in refs_with_path_in(source_expr):
            resolved = self._resolve_ref(root, ref_field, level)
            if resolved is None:
                continue
            source, output_field = resolved
            self.edges.append(
                Edge(
                    source=source,
                    target=target,
                    kind=EdgeKind.DATA_FLOW,
                    output_field=output_field,
                    output_path=ref_path if output_field == ref_field else (),
                )
            )

    def _resolve_ref(self, root: str, field: str | None, level: _LevelResult) -> tuple[NodeId, str | None] | None:
        if root in {"item", "__iteration__"}:
            return None
        if root in level.inputs:
            return level.inputs[root], None
        sibling = level.nodes.get(root)
        if sibling is None:
            return None
        outputs = level.produces.get(sibling, {})
        if field and field in outputs:
            return outputs[field], field
        if not field and len(outputs) == 1:
            name, output = next(iter(outputs.items()))
            return output, name
        return sibling, field


def _deduplicate_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    named_pairs = {
        (edge["from"], edge["to"]) for edge in edges if "action" in edge and edge["action"] not in ("default", "error")
    }
    result: list[dict[str, Any]] = []
    for edge in edges:
        pair = (edge["from"], edge["to"])
        if pair in named_pairs:
            if "action" in edge and edge["action"] != "default":
                result.append(edge)
        else:
            result.append(edge)
    return result


def _structural_edge(source: NodeId, target: NodeId, raw_edge: dict[str, Any]) -> Edge:
    action = raw_edge.get("action")
    if action == "error":
        return Edge(source=source, target=target, kind=EdgeKind.ERROR, label="error")
    if action not in (None, "default"):
        return Edge(source=source, target=target, kind=EdgeKind.BRANCH, label=str(action))
    return Edge(source=source, target=target, kind=EdgeKind.SEQUENTIAL)


def _build_loop(raw_loop: Any, node_id: str) -> LoopSpec | None:
    if not isinstance(raw_loop, dict):
        return None
    has_while = "while" in raw_loop
    has_until = "until" in raw_loop
    if has_while == has_until:
        return None
    if has_while:
        polarity: Literal["while", "until"] = "while"
        raw_condition = raw_loop.get("while")
    else:
        polarity = "until"
        raw_condition = raw_loop.get("until")
    if not isinstance(raw_condition, str):
        return None
    cap = raw_loop.get("max_iterations")
    if not isinstance(cap, (int, str)) or isinstance(cap, bool):
        cap = None
    carry = raw_loop.get("carry", {})
    return LoopSpec(
        polarity=polarity,
        condition=raw_condition,
        cap=cap,
        carry={str(k): str(v) for k, v in carry.items()} if isinstance(carry, dict) else {},
    )


def _build_batch(raw_batch: Any) -> BatchSpec | None:
    if not isinstance(raw_batch, dict):
        return None
    items = raw_batch.get("items")
    as_name = str(raw_batch.get("as", "item"))
    parallel = bool(raw_batch.get("parallel", False))
    if isinstance(items, str):
        return BatchSpec(parallel=parallel, dynamic=True, as_name=as_name, source_ref=items)
    if isinstance(items, list):
        return BatchSpec(parallel=parallel, dynamic=False, as_name=as_name, count=len(items), items=items)
    return BatchSpec(parallel=parallel, dynamic=False, as_name=as_name, count=0, items=[])


def _source_ref(raw: dict[str, Any], source_file: Path | None) -> SourceRef | None:
    line = raw.get("_source_line")
    return SourceRef(
        file=str(source_file) if source_file is not None else None, line=line if isinstance(line, int) else None
    )


def _node_params(raw_node: dict[str, Any]) -> dict[str, Any]:
    """Authored param values for click-to-read / the React Flow renderer.

    Stored verbatim (small literals, templates, full prompt/code strings alike);
    the renderer decides what to inline vs truncate. Guarded like every other
    ``raw_node`` read in this module: unvalidated IR may carry ``params: None``
    (or a non-dict), which becomes an empty dict rather than an ``AttributeError``.
    """
    params = raw_node.get("params")
    return params if isinstance(params, dict) else {}


def _param_source_refs(raw: dict[str, Any], source_file: Path | None) -> dict[str, SourceRef]:
    source_lines = raw.get("_source_lines")
    source_files = raw.get("_source_files")
    if not isinstance(source_lines, dict) and not isinstance(source_files, dict):
        return {}

    keys: set[str] = set()
    if isinstance(source_lines, dict):
        keys.update(str(key) for key in source_lines)
    if isinstance(source_files, dict):
        keys.update(str(key) for key in source_files)

    refs: dict[str, SourceRef] = {}
    for key in sorted(keys):
        line = source_lines.get(key) if isinstance(source_lines, dict) else None
        file_ref = source_files.get(key) if isinstance(source_files, dict) else None
        refs[key] = SourceRef(
            file=_param_source_file(file_ref, source_file),
            line=line if isinstance(line, int) else None,
        )
    return refs


def _param_source_file(file_ref: Any, source_file: Path | None) -> str | None:
    if isinstance(file_ref, str) and file_ref:
        path = Path(file_ref)
        if source_file is not None and not path.is_absolute():
            return str((source_file.parent / path).resolve())
        return str(path)
    return str(source_file) if source_file is not None else None


def _batch_alias(raw_node: dict[str, Any]) -> str:
    batch = raw_node.get("batch")
    raw_alias = batch.get("as") if isinstance(batch, dict) else None
    return raw_alias if isinstance(raw_alias, str) and raw_alias else "item"


def _binding_uses_batch_alias(binding: str, alias: str) -> bool:
    return any(root == alias for root, _field in refs_in(binding))


def _params_strings(params: Any) -> list[tuple[str, str, bool]]:
    """Yield ``(name, string_leaf, shallow)`` for every string leaf in params.

    Recurses dicts AND lists to any depth — validator parity (`_check_param_value`
    in core/workflow/data_flow.py walks the same shapes), so every authored
    ``${ref}`` is visited wherever it sits. ``shallow`` marks binding-level names that may
    legitimately target a child-input port: a top-level string param, a depth-1
    dict value, or a direct item of a top-level list param. Deeper leaves keep
    their nearest key (the web UI joins it to a param row when names match) but
    must never claim a child-input port. A ref is never dropped — deep refs
    attach node-level downstream.
    """
    if not isinstance(params, dict):
        return []
    leaves: list[tuple[str, str, bool]] = []
    for name, value in params.items():
        _collect_string_leaves(str(name), value, 0, leaves)
    return leaves


def _collect_string_leaves(name: str, value: Any, depth: int, leaves: list[tuple[str, str, bool]]) -> None:
    if isinstance(value, str):
        leaves.append((name, value, depth <= 1))
    elif isinstance(value, dict):
        for key, nested in value.items():
            _collect_string_leaves(str(key), nested, depth + 1, leaves)
    elif isinstance(value, list):
        for item in value:
            _collect_string_leaves(name, item, depth + 1, leaves)


def _container_id(ancestor_path: tuple[AncestorStep, ...], suffix: str) -> str:
    if not ancestor_path:
        return suffix
    parts = [
        f"{step.node_id}#{step.batch_index}" if step.batch_index is not None else step.node_id for step in ancestor_path
    ]
    return "/".join([*parts, suffix])


def _input_node_id(name: str, ancestor_path: tuple[AncestorStep, ...]) -> NodeId:
    return NodeId(name, ancestor_path, port="in")


def _output_node_id(name: str, ancestor_path: tuple[AncestorStep, ...]) -> NodeId:
    return NodeId(name, ancestor_path, port="out")


def _child_key(child_result: SubWorkflowResult) -> str:
    if child_result.path is not None:
        return str(child_result.path)
    # Inline workflows have no path. Hashing the IR gives a deterministic stack
    # key; an md5 collision would be a false cycle, which is acceptable here.
    return synthesize_inline_workflow_id(child_result.ir)


def _record_unexpanded_item(container: Container, index: int, reason: UnexpandedReason) -> None:
    """Record why a literal-batch sub-workflow item did not expand.

    Stored on the batch Container (not the host Node) because individual items may
    succeed or fail independently. JSON-able: ``{index: reason}``.
    """
    container.annotations.setdefault("unexpanded_items", {})[index] = reason


def _warnings_annotation(child_result: SubWorkflowResult) -> dict[str, Any]:
    if not child_result.warnings:
        return {}
    return {"warnings": [str(warning) for warning in child_result.warnings]}


def _start_node_annotation(ir: dict[str, Any]) -> dict[str, Any]:
    start_node = ir.get("start_node")
    if not isinstance(start_node, str):
        nodes = ir.get("nodes", [])
        start_node = str(nodes[0]["id"]) if nodes else None
    return {"start_node": start_node} if start_node else {}
