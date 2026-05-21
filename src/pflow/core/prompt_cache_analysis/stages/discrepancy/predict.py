"""Cache-key prediction helpers for discrepancy diagnostics."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from pflow.core.exceptions import CompilationError, MarkdownParseError, SchemaValidationError, WorkflowValidationError
from pflow.core.validation_utils import generate_dummy_parameters

from ...context import _PREDICTION_SKIPPED, AnalysisContext
from ...cross_workflow import DynamicBatchInfo
from ...trace_loading import _is_llm_node

logger = logging.getLogger(__name__)


def _template_resolver() -> Any:
    from pflow.runtime.template_resolver import TemplateResolver

    return TemplateResolver


_PREDICTION_RECOVERABLE_EXCEPTIONS: Final[tuple[type[Exception], ...]] = (
    CompilationError,
    MarkdownParseError,
    SchemaValidationError,
    WorkflowValidationError,
    FileNotFoundError,
    ValueError,
    KeyError,
    RecursionError,
    OSError,
)

# ---------------------------------------------------------------------------
# Trace discrepancy detection
# ---------------------------------------------------------------------------


def _predict_cache_keys(
    cw_result: Any,
    ctx: AnalysisContext,
) -> tuple[dict[tuple[str | None, str], str], list[str]]:
    """Predict the runtime cache_key for every LLM node, scoped per workflow.

    Walks every workflow's IR independently (root + descendants from
    ``cw_result.irs_by_workflow``) and computes the byte-identical
    cache_key the runtime would compute via ``plan_node`` — the same
    canonical site the engine and the dry-run planner consume. This
    bypasses ``build_plan``'s BFS-downstream mode (which sets
    ``cache_key=None`` for child nodes whose parent took the downstream
    path), the source of Bug 5 in the verification report.

    ``compile_workflow`` + ``create_planner_shared`` are hoisted to the
    per-workflow loop — N LLM nodes in one workflow incur ONE compile, not
    N. ``plan_node`` is then invoked per LLM node against the shared
    compiled+shared scaffold.

    Per-node skip reasons replace the catch-all silent-skip count that the
    legacy implementation produced — agents see exactly which node's
    prediction failed and why.

    Returns ``(predicted_keys, notes)`` where ``predicted_keys`` keys
    ``(workflow_path, node_id) -> cache_key``. The contract matches the
    legacy implementation; only the production path changes.
    """
    notes: list[str] = []
    if ctx.memo_cache is None:
        notes.append(
            "Cache fidelity check skipped: this is a first run "
            "(no prior runs to compare cached vs uncached against). "
            "On later runs, specific cache misfires (TTL expired, chunks skipped) will appear here."
        )
        return {}, notes

    irs_by_workflow = getattr(cw_result, "irs_by_workflow", None) or {}
    if not irs_by_workflow:
        # Defensive fallback: no cross-workflow walker output. Use the root
        # IR alone (analyzer never calls _predict_cache_keys without the root).
        irs_by_workflow = {ctx.workflow_path: dict(ctx.workflow_ir)}

    predicted_keys: dict[tuple[str | None, str], str] = {}
    skipped_input_workflows: list[str] = []
    for workflow_path, ir in irs_by_workflow.items():
        _predict_one_workflow(
            workflow_path=workflow_path,
            ir=ir,
            ctx=ctx,
            predicted_keys=predicted_keys,
            notes=notes,
            skipped_input_workflows=skipped_input_workflows,
        )
    if skipped_input_workflows:
        notes.append(_format_skipped_workflows_note(skipped_input_workflows))
    return predicted_keys, notes


def _format_dynamic_batches_note(batches: tuple[DynamicBatchInfo, ...]) -> str | None:
    """Aggregate runtime-template batches into ONE Note (B-4).

    Workflow-type nodes whose ``batch.items`` is a ``${...}`` template can't
    have their per-item children enumerated statically. Pre-B-4 rendering
    emitted ~150 chars of near-identical prose per occurrence — lyrics-
    generator's 3 batches blew up to ~500 chars of repeated content in
    ``## Notes``. The aggregated form lists each batch's ``node_id`` +
    ``items_expression`` once and shares the explanatory prose.

    Single-batch case keeps the original phrasing for continuity with
    pre-B-4 baselines and the existing substring-only test
    (``test_template_items_gap_note_uses_real_analyze_cache_cli_param_wording``).
    """
    if not batches:
        return None
    if len(batches) == 1:
        b = batches[0]
        return (
            f"Workflow batch {b.node_id} in {b.parent_workflow} uses items: {b.items_expression}; sub-workflow "
            "rows for these runtime items are not in the per-call table. The displayed cost is measured from "
            "trace events, not estimated. Pass the resolved list as a CLI parameter, or use inline static batch "
            "items, to enable static child enumeration."
        )
    listing = ", ".join(f"`{b.node_id}` (items: `{b.items_expression}`)" for b in batches)
    return (
        f"{len(batches)} dynamic batches not in per-call table: {listing}. Batch items are computed at runtime, "
        "so per-item rows can't be enumerated statically. Pass items as a CLI parameter or use inline static "
        "items to list them. (Cost shown is measured from the trace, not estimated.)"
    )


def _format_fidelity_skip_note(target: str, reason: str, *, applicable: bool = True) -> str:
    """Single SSoT for the "we couldn't verify cache fidelity here" notes.

    Every skip-note in the discrepancy stage describes the same shape: the
    analyzer wanted to compare predicted cache_keys against trace evidence
    for a specific target (workflow or workflow.node), couldn't, and falls
    back to reporting explicit skipped-chunk events from the trace. The
    framing is jargon-free and consistent across all
    9 emit sites so an agent reading the Notes section never has to map
    "Discrepancy detection: predicted-key matching" → "cache fidelity
    check" by themselves.

    ``applicable=False`` switches the prefix for cases like ``cache: false``
    on a node — the check isn't unavailable; it doesn't apply at all.

    Mutation contract: if a producer ever bypasses this helper and emits
    the old "Discrepancy detection: ..." prefix directly, the jargon
    returns. The wording lives in this one place to prevent that drift.
    """
    prefix = "Cache fidelity check skipped for" if applicable else "Cache fidelity check not applicable to"
    return f"{prefix} {target}: {reason}. Chunk-skip detection still applies."


def _format_skipped_workflows_note(paths: list[str]) -> str:
    """Aggregate per-sub-workflow skip notes into one summary (L-4).

    Single-workflow case keeps the per-workflow detail. Multi-workflow case
    lists up to 5 basenames; overflow as ``+N more``. Real lyrics-generator
    runs emit 15 of these — pre-L-4 rendering blew ~4KB of repeated prose
    into the Notes section.
    """
    if len(paths) == 1:
        return _format_fidelity_skip_note(
            paths[0],
            "that sub-workflow declares inputs which weren't supplied as parameters",
        )
    shown = [Path(p).name if p and p != "<root>" else "<root>" for p in paths[:5]]
    suffix = "" if len(paths) <= 5 else f" + {len(paths) - 5} more"
    return _format_fidelity_skip_note(
        f"{len(paths)} sub-workflows ({', '.join(shown)}{suffix})",
        "they declare inputs which weren't supplied as parameters. "
        "Pass concrete `<input>=<value>` parameters via CLI to enable per-workflow checks",
    )


def _attach_predicted_cache_keys(
    ctx: AnalysisContext,
    cw_result: Any,
) -> tuple[AnalysisContext, dict[tuple[str | None, str], str], list[str]]:
    """Run cache-key prediction once and store the result on the context."""
    predicted_cache_keys: dict[tuple[str | None, str], str] = {}
    prediction_fidelity_notes: list[str] = []
    try:
        predicted_cache_keys, prediction_fidelity_notes = _predict_cache_keys(cw_result, ctx)
    except _PREDICTION_RECOVERABLE_EXCEPTIONS as exc:
        logger.debug("memo freshness prediction disabled: %s", exc, exc_info=True)
        _mark_all_prediction_skipped(predicted_cache_keys, cw_result, ctx)
    return (
        replace(
            ctx,
            predicted_cache_keys=predicted_cache_keys,
            prediction_fidelity_notes=tuple(prediction_fidelity_notes),
        ),
        predicted_cache_keys,
        prediction_fidelity_notes,
    )


def _predict_one_workflow(
    *,
    workflow_path: str | None,
    ir: Mapping[str, Any],
    ctx: AnalysisContext,
    predicted_keys: dict[tuple[str | None, str], str],
    notes: list[str],
    skipped_input_workflows: list[str],
) -> None:
    """Compute predictions for every LLM node in one workflow IR.

    Mutates ``predicted_keys``, ``notes``, and ``skipped_input_workflows``
    in place. Extracted from ``_predict_cache_keys`` to keep that function
    under the cyclomatic-complexity budget; the per-workflow body has its
    own classification branches (input-gate, no-LLM-shortcut, scaffold
    build, per-node loop) that naturally cluster together.
    """
    params = ctx.parameters_for_workflow(workflow_path)
    declared_inputs_raw = ir.get("inputs")
    declared_inputs: Mapping[str, Any] | None = (
        declared_inputs_raw if isinstance(declared_inputs_raw, Mapping) else None
    )
    # Truly cold case: walker resolved NOTHING and the workflow declares
    # inputs. Skip the whole workflow and aggregate to a single Notes
    # summary at the caller level (L-4). Distinct from the partial-params
    # case below where some inputs were resolved and we want to predict
    # what we can on a per-node basis.
    llm_nodes = [node for node in ir.get("nodes", []) if _is_llm_node(node)]
    if not params and declared_inputs:
        skipped_input_workflows.append(workflow_path or "<root>")
        _mark_prediction_skipped(predicted_keys, workflow_path, llm_nodes)
        return
    if not llm_nodes:
        return
    # Partial-params case: walker resolved some inputs but not all (e.g.,
    # a child input that flows from an upstream sub-workflow output the
    # walker can't reach statically). Pad the missing slots with the
    # standard placeholder so compile succeeds; then skip prediction per
    # node for any node whose templates or referenced cache chunks touch
    # a padded slot — its predicted cache_key would be placeholder-
    # tainted and never match the trace. Per-node skip is silent;
    # skipped-chunk attribution covers real branch-absent misses on those
    # nodes.
    padded_params, dummied_keys = _pad_inputs_for_prediction(params, declared_inputs)
    dummied_chunks = _dummied_cache_chunks(ir, dummied_keys)
    scaffold = _build_predict_scaffold(ir, padded_params, ctx.memo_cache, workflow_path)
    if scaffold is None:
        _mark_prediction_skipped(predicted_keys, workflow_path, llm_nodes)
        return
    for node in llm_nodes:
        if _node_references_any(node, dummied_keys, dummied_chunks):
            predicted_keys[(workflow_path, str(node["id"]))] = _PREDICTION_SKIPPED
            continue
        cache_key, skip_reason = _predict_node_with_scaffold(node, scaffold, workflow_path)
        if cache_key is not None:
            predicted_keys[(workflow_path, str(node["id"]))] = cache_key
        elif skip_reason:
            predicted_keys[(workflow_path, str(node["id"]))] = _PREDICTION_SKIPPED
            notes.append(skip_reason)


def _mark_prediction_skipped(
    predicted_keys: dict[tuple[str | None, str], str],
    workflow_path: str | None,
    nodes: Iterable[Mapping[str, Any]],
) -> None:
    for node in nodes:
        node_id = node.get("id")
        if isinstance(node_id, str):
            predicted_keys[(workflow_path, node_id)] = _PREDICTION_SKIPPED


def _mark_all_prediction_skipped(
    predicted_keys: dict[tuple[str | None, str], str],
    cw_result: Any,
    ctx: AnalysisContext,
) -> None:
    """Mark every known LLM node as attempted-but-uncheckable after prediction outage."""
    irs_by_workflow = getattr(cw_result, "irs_by_workflow", None) or {ctx.workflow_path: dict(ctx.workflow_ir)}
    for workflow_path, workflow_ir in irs_by_workflow.items():
        nodes = workflow_ir.get("nodes", []) if isinstance(workflow_ir, Mapping) else []
        _mark_prediction_skipped(
            predicted_keys,
            workflow_path,
            (node for node in nodes if isinstance(node, Mapping) and _is_llm_node(node)),
        )


def _pad_inputs_for_prediction(
    known_params: Mapping[str, Any],
    declared_inputs: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], frozenset[str]]:
    """Merge walker-resolved params with placeholders for missing inputs.

    The discrepancy stage compiles every sub-workflow to predict runtime
    cache_keys, but the cross-workflow walker can only resolve inputs
    whose values flow statically from the parent. For inputs that come
    from upstream node outputs (e.g. ``${upstream.results}``) the walker
    leaves the slot empty — and ``compile_workflow`` would reject the
    incomplete params dict with ``SchemaValidationError`` before any
    per-node prediction could run, emitting a misleading "workflow failed
    to compile" Note for workflows that run fine end-to-end.

    Padding the missing slots with ``"__validation_placeholder__"`` lets
    compile succeed (same idiom ``WorkflowValidator._validate_one_child_call``
    uses for structural validation). The returned ``dummied_keys`` set
    lets ``_predict_one_workflow`` skip prediction for any node whose
    templates touch a placeholder; those predictions would never match
    the trace's real values.
    """
    padded: dict[str, Any] = dict(known_params)
    if not declared_inputs:
        return padded, frozenset()
    dummies = generate_dummy_parameters(dict(declared_inputs))
    dummied: set[str] = set()
    for key, placeholder in dummies.items():
        if key not in padded:
            padded[key] = placeholder
            dummied.add(key)
    return padded, frozenset(dummied)


def _node_references_any(
    node: Mapping[str, Any],
    dummied_keys: frozenset[str],
    dummied_chunks: frozenset[str],
) -> bool:
    """True iff ``node``'s cache_key would be placeholder-tainted.

    Used by the discrepancy stage to skip cache_key prediction for nodes
    whose inputs depend on dummied (un-walker-resolved) workflow inputs.
    A node is tainted if EITHER:

    - it declares ``prompt_cache: [name]`` referencing a chunk whose
      ``var`` traces back to a dummied input (``dummied_chunks``), OR
    - any ``${var}`` ref in the node's IR has a root in ``dummied_keys``.

    Conservative on coalesce: if ANY operand of ``${a ?? b}`` has a root
    in ``dummied_keys``, returns True. The alternative (only skip when
    ALL operands are dummied) risks producing placeholder-tainted
    predictions when the resolver happens to pick the dummied operand
    first.
    """
    if not isinstance(node, Mapping):
        return False
    if _node_prompt_cache_touches(node, dummied_chunks):
        return True
    return _node_templates_touch(node, dummied_keys)


def _node_prompt_cache_touches(node: Mapping[str, Any], dummied_chunks: frozenset[str]) -> bool:
    """True iff the node's ``prompt_cache:`` lists any dummied chunk name."""
    if not dummied_chunks:
        return False
    prompt_cache = node.get("prompt_cache")
    if not isinstance(prompt_cache, list):
        return False
    return any(isinstance(name, str) and name in dummied_chunks for name in prompt_cache)


def _node_templates_touch(node: Mapping[str, Any], dummied_keys: frozenset[str]) -> bool:
    """True iff any ``${var}`` ref in the node's IR has a root in ``dummied_keys``.

    Walks every nested string value in the node dict — broader than
    ``_collect_llm_nodes_referencing_path`` (which only inspects
    ``params.prompt``) because cache_key inputs come from any templated
    field on the node (``params``, ``inputs``, ``batch``, nested
    code-block inputs, etc.).
    """
    if not dummied_keys:
        return False
    for text in _walk_strings(node):
        for match in _template_resolver().TEMPLATE_PATTERN.finditer(text):
            for operand in _template_resolver().split_coalesce_operands(match.group(1)):
                root = _template_resolver().extract_root_node_id(operand)
                if root and root in dummied_keys:
                    return True
    return False


def _dummied_cache_chunks(
    workflow_ir: Mapping[str, Any],
    dummied_keys: frozenset[str],
) -> frozenset[str]:
    """Cache chunk names whose ``var`` traces back to a dummied input.

    A ``## Cache`` block declares chunks with ``var: <ref>``; when a
    node's ``prompt_cache:`` references such a chunk, the runtime
    resolves ``var`` against parameters to produce the chunk's content.
    If ``var``'s root is dummied, the chunk content carries the
    placeholder and any node consuming it via ``prompt_cache`` would
    produce a placeholder-tainted cache_key — same outcome as a direct
    template ref to a dummied input.

    Pre-computed once per workflow so the per-node check stays O(1) in
    the number of chunks.
    """
    if not dummied_keys:
        return frozenset()
    cache = workflow_ir.get("cache") if isinstance(workflow_ir, Mapping) else None
    if not isinstance(cache, Mapping):
        return frozenset()
    items = cache.get("items")
    if not isinstance(items, list):
        return frozenset()
    tainted: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        var = item.get("var")
        if not isinstance(var, str):
            continue
        root = _template_resolver().extract_root_node_id(var)
        if root and root in dummied_keys:
            name = item.get("name")
            if isinstance(name, str):
                tainted.add(name)
    return frozenset(tainted)


def _walk_strings(value: Any) -> Iterable[str]:
    """Yield every string value reachable from ``value`` via dict/list nesting."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for inner in value.values():
            yield from _walk_strings(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _walk_strings(inner)


@dataclass(frozen=True)
class _PredictScaffold:
    """Per-workflow scaffold reused across all LLM nodes in one workflow."""

    compiled: Any
    shared: dict[str, Any]
    bare_nodes_by_id: dict[str, Any]


def _build_predict_scaffold(
    workflow_ir: Mapping[str, Any],
    params: Mapping[str, Any],
    memo_cache: Any,
    workflow_path: str | None,
) -> _PredictScaffold | None:
    """Compile + planner-shared once per workflow.

    Returns the scaffold, or ``None`` if compile/planner setup fails. The
    unified validator (``_run_full_validation``) runs strictly earlier in
    ``analyze()`` and surfaces structural errors via ``blocking_errors[]``
    /``other_blocking_errors[]``, so this catch only fires for compiler-
    internal failures the validator missed. Those degrade silently with
    a debug log — the agent already has the actionable structural signal
    from the validator pass, and a misleading "workflow failed to compile
    (SchemaValidationError)" Note (the Bug 3 symptom) is worse than no
    Note at all.

    Callers inject ``_pflow_workflow_file`` so relative ``@./file.ext``
    refs resolve against the workflow's own directory instead of CWD —
    matches ``WorkflowValidator._validate_one_child_call``'s pattern.

    Lazy imports keep the analyzer package import-cheap (mirrors
    ``token_estimation.py``'s LiteLLM lazy-import).
    """
    from pflow.execution.plan import create_planner_shared
    from pflow.registry import Registry
    from pflow.runtime import compile_workflow

    compile_params: dict[str, Any] = dict(params)
    if workflow_path is not None:
        compile_params.setdefault("_pflow_workflow_file", str(workflow_path))
    try:
        compiled = compile_workflow(dict(workflow_ir), Registry(), dict(compile_params))
        shared = create_planner_shared(compiled, dict(compile_params), memo_cache, workflow_path)
    except _PREDICTION_RECOVERABLE_EXCEPTIONS as exc:
        logger.debug(
            "predict-stage setup failed for %s: %s",
            workflow_path or "<root>",
            exc,
            exc_info=True,
        )
        return None
    bare_nodes_by_id = _enumerate_compiled_bare_nodes(compiled)
    return _PredictScaffold(compiled=compiled, shared=shared, bare_nodes_by_id=bare_nodes_by_id)


def _predict_node_with_scaffold(
    node: dict[str, Any],
    scaffold: _PredictScaffold,
    workflow_path: str | None,
) -> tuple[str | None, str | None]:
    """Compute the cache_key for one node against a pre-built scaffold.

    Returns ``(cache_key, skip_reason)`` — same shape as ``_predict_node_cache_key``
    but doesn't recompile the workflow. Suitable for the per-workflow loop in
    ``_predict_cache_keys``; tests that want a self-contained per-node call
    use ``_predict_node_cache_key`` instead (it builds its own scaffold).
    """
    from pflow.runtime.engine.plan_node import plan_node

    node_id = str(node.get("id", "?"))
    workflow_label = workflow_path or "<root>"
    target = f"{workflow_label}.{node_id}"
    config = scaffold.compiled.node_configs.get(node_id)
    if config is None:
        return None, _format_fidelity_skip_note(target, "node missing from the compiled workflow (parser/IR mismatch)")
    bare_node = scaffold.bare_nodes_by_id.get(node_id)
    if bare_node is None:
        return None, _format_fidelity_skip_note(target, "node not reachable from the workflow's start")
    try:
        plan = plan_node(bare_node, config, scaffold.shared)
    except Exception as exc:
        logger.debug("plan_node raised for %s.%s", workflow_label, node_id, exc_info=True)
        return None, _format_fidelity_skip_note(target, f"planner raised {type(exc).__name__} during prediction")

    if plan.cache_key is not None:
        return plan.cache_key, None
    if plan.template_exception is not None:
        return None, _format_fidelity_skip_note(
            target,
            "a template reference couldn't be resolved at analysis time (depends on a runtime value)",
        )
    if plan.status == "cache_disabled":
        return None, _format_fidelity_skip_note(target, "this node has `cache: false`", applicable=False)
    return None, _format_fidelity_skip_note(target, f"planner returned no cache key (status={plan.status})")


def _predict_node_cache_key(
    *,
    node: dict[str, Any],
    workflow_ir: Mapping[str, Any],
    params: Mapping[str, Any],
    memo_cache: Any,
    workflow_path: str | None,
) -> tuple[str | None, str | None]:
    """Self-contained per-node prediction — builds its own scaffold.

    Production callers should use ``_predict_cache_keys`` (which hoists the
    compile + shared per workflow, applies dummy padding for partial
    walker params, and skips nodes whose templates touch a padded slot).
    This helper is kept for direct test callers that want a single-node
    prediction without setting up a ``cw_result`` / ``AnalysisContext``;
    they pass real (already-resolved) params, so no padding is needed.
    Returns ``(None, None)`` on scaffold failure — the silent-skip
    contract matches production.
    """
    scaffold = _build_predict_scaffold(workflow_ir, params, memo_cache, workflow_path)
    if scaffold is None:
        return None, None
    return _predict_node_with_scaffold(node, scaffold, workflow_path)


def _enumerate_compiled_bare_nodes(compiled: Any) -> dict[str, Any]:
    """BFS from ``compiled.start_node`` collecting node_id → bare-node."""
    bare_nodes_by_id: dict[str, Any] = {}
    start = getattr(compiled, "start_node", None)
    if start is None:
        return bare_nodes_by_id
    queue: list[Any] = [start]
    while queue:
        bare = queue.pop(0)
        bare_id = getattr(bare, "node_id", None)
        if not isinstance(bare_id, str) or bare_id in bare_nodes_by_id:
            continue
        bare_nodes_by_id[bare_id] = bare
        successors = getattr(bare, "successors", None) or {}
        for succ in successors.values():
            if succ is not None:
                queue.append(succ)
    return bare_nodes_by_id
