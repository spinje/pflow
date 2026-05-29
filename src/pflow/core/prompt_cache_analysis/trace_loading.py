"""Trace loading and trace-derived indexes for prompt cache analysis."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pflow.core.diagnostic import Diagnostic
from pflow.core.llm_config import get_default_workflow_model
from pflow.core.llm_providers import normalize_model_name

from .sub_workflow_walker import walk_cross_workflow
from .types import PerCallRow, TraceExecutionIndex, TraceListEntry
from .warning_catalog import CACHE_WARNING_CATALOG, make_diagnostic

logger = logging.getLogger(__name__)


def _row_model_drift(
    row: PerCallRow,
    irs_by_workflow: Mapping[str, Mapping[str, Any]],
    default_model: str | None,
) -> tuple[str, str] | None:
    """Return ``(trace_model, ir_model)`` if this row has drift, else ``None``.

    Skip conditions (all return ``None``): heterogeneous row, ambiguous or
    missing trace model, missing workflow_path/IR, templated or absent
    IR-static model, normalized models equal.
    """
    if row.model_is_heterogeneous or len(row.observed_models) != 1:
        return None
    trace_model = normalize_model_name(row.observed_models[0])
    if not trace_model or row.workflow_path is None:
        return None
    ir = irs_by_workflow.get(row.workflow_path)
    if ir is None:
        return None
    ir_node = next(
        (n for n in (ir.get("nodes") or []) if isinstance(n, dict) and n.get("id") == row.node_path),
        None,
    )
    ir_model = _resolve_ir_static_model_for_node(ir_node, default_model)
    if ir_model is None or ir_model == trace_model:
        return None
    return trace_model, ir_model


def _detect_per_node_model_drift(
    per_call_rows: list[PerCallRow] | tuple[PerCallRow, ...],
    irs_by_workflow: Mapping[str, Mapping[str, Any]],
    default_model: str | None,
) -> tuple[str | None, int]:
    """Detect per-node model drift between trace and current IR.

    Compares each per-call row's single trace-observed model against the
    IR-static model for that node. Returns one grouped Notes string when any
    drift is found, else ``None``.

    Why this matters: row model resolution declares "trace wins", so
    downstream projections use trace-side pricing. If the workflow's model
    changed after the trace was recorded, projections silently misprice.
    Actually-paid remains correct because it comes from recorded ``cost_usd``.
    """
    drifts: list[tuple[str, str, str]] = []
    seen: set[tuple[str | None, str]] = set()
    for row in per_call_rows:
        key = (row.workflow_path, row.node_path)
        if key in seen:
            continue
        seen.add(key)
        drift = _row_model_drift(row, irs_by_workflow, default_model)
        if drift is not None:
            drifts.append((row.node_path, drift[0], drift[1]))

    if not drifts:
        return None, 0

    if len(drifts) == 1:
        node_id, trace_model, ir_model = drifts[0]
        return (
            f"Trace was recorded with model `{trace_model}` for node `{node_id}`; "
            f"current workflow declares `{ir_model}`. Actually-paid is correct; "
            f"cost projections use trace-side pricing. Re-record a trace to refresh."
        ), 1

    items = ", ".join(f"`{node_id}` ({trace_model} → {ir_model})" for node_id, trace_model, ir_model in drifts)
    return (
        f"Trace was recorded with different models than current workflow for "
        f"{len(drifts)} nodes: {items}. Actually-paid is correct; "
        f"cost projections use trace-side pricing. Re-record a trace to refresh."
    ), len(drifts)


def _build_call_counts_by_node(ctx: Any, cw_result: Any) -> dict[tuple[str | None, str], int]:
    """Observed LLM call counts keyed like per-call rows."""
    if ctx.trace is None:
        return {}
    counts: dict[tuple[str | None, str], int] = {}
    edges_map = _edge_child_paths(cw_result)
    for leaf in ctx.trace.iter_llm_leaves(edges=edges_map, workflow_path=ctx.workflow_path):
        llm_call = leaf.llm_call
        if llm_call is not None and llm_call.get("is_warmup"):
            continue
        node_id = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id
        key = (leaf.workflow_path, node_id)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _default_memo_cache() -> Any:
    """Construct a read-only ``MemoizationCache`` from the default location.

    Returns ``None`` when ``~/.pflow/cache/cache.db`` doesn't exist (greenfield
    workflow that has never been run) or when construction fails (disk error,
    permissions, corrupted file). Either way the analyzer falls back to the
    ``estimator`` / ``heuristic`` tiers — no surprise SQLite file creation for
    a read-only analyze invocation.

    The existence-check before construction is load-bearing: ``MemoizationCache.__init__``
    creates the parent directory + opens a connection + runs ``_init_db()``
    which CREATES the schema. Skipping construction when the file is absent
    keeps analyze invocations side-effect-free on greenfield workflows.

    See CR-1305 W3 — pre-fix, the memo tier was unreachable from CLI/MCP/dry-run
    because no production caller passed a ``MemoizationCache``. Default-construct
    here unlocks ``data_source: "memo"`` in production at zero plumbing cost.
    """
    cache_path = Path.home() / ".pflow" / "cache" / "cache.db"
    if not cache_path.exists():
        return None
    try:
        from pflow.runtime.cache import MemoizationCache

        return MemoizationCache(db_path=cache_path, read_enabled=True)
    except Exception:
        logger.debug(
            "Failed to construct default memo_cache; analyzer falls back to estimator/heuristic",
            exc_info=True,
        )
        return None


def _load_trace_explicit(path: Path, notes: list[str]) -> dict[str, Any] | None:
    """Load an explicit ``--from-trace`` path.

    Per F3.1 contract: missing path or invalid JSON → caller reports as
    non-zero exit. Here we raise so the CLI layer can format the error.
    Accepts any ``2.x`` trace; future additive minor bumps stay compatible
    via the ``startswith("2.")`` gate.
    """
    del notes  # currently unused; preserved for caller contract symmetry
    if not path.exists():
        raise FileNotFoundError(f"Trace file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Trace file {path} is not a valid pflow trace (JSON parse error).") from exc
    if not isinstance(data, dict) or "format_version" not in data:
        raise ValueError(f"Trace file {path} is not a valid pflow trace (missing format_version field).")
    fv = str(data.get("format_version", ""))
    if not fv.startswith("2."):
        raise ValueError(f"Trace file {path} format_version={fv!r}; analyze-cache requires 2.x.")
    return data


def _format_rejection_note(
    rejected_trace_path: str | None,
    trace_data: dict[str, Any] | None,
) -> str:
    """Compose the Notes line emitted when the post-row-build gate rejects
    an auto-loaded trace.

    Names the rejected file + its run status so the agent can decide
    whether to override with ``--from-trace`` or re-run. Used by the
    rejection branch in ``analyze()``; extracted for C901.
    """
    rejected_name = Path(rejected_trace_path).name if rejected_trace_path else None
    rejected_status = str(trace_data.get("final_status") or "success") if isinstance(trace_data, dict) else "unknown"
    if rejected_name:
        return (
            f"Auto-loaded trace `{rejected_name}` ({rejected_status}) did not "
            f"cover all root LLM nodes (some root LLM nodes have no matching "
            f"events — workflow may have been edited since the trace was "
            f"recorded). Ignored for workflow-wide cache analysis. Pass "
            f"`--from-trace <path>` to inspect a specific trace anyway."
        )
    # Defensive fallback — unreachable under current code paths (``trace_path
    # is None`` here implies autoload ran AND set ``used_trace_path``), but
    # preserve the original wording so any future regression is recognizable.
    return "Auto-loaded trace did not cover all root LLM nodes; ignored for workflow-wide cache analysis."


def _collect_candidate_traces(
    debug_dir: Path,
    workflow_path: str,
) -> tuple[list[tuple[Path, dict[str, Any]]], list[tuple[Path, dict[str, Any]]]]:
    """Walk ``debug_dir`` for 2.x traces matching ``workflow_path``; bucket by run outcome.

    Returned tuple is ``(successful, failed)``, each newest-first by filename
    (which embeds the recording timestamp). Absent ``final_status`` routes to
    the successful bucket — matches the back-compat fallback at
    ``_trace_coverage_for_rows`` and preserves selection for pre-2.1.0 traces.

    Extracted from ``_autoload_trace`` for C901 — the trace-walking +
    health-filter loop is independent of the rank-aware selection policy.
    """
    wf_hash = hashlib.md5(workflow_path.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    pattern = f"workflow-trace-{wf_hash}-*.json"
    successful: list[tuple[Path, dict[str, Any]]] = []
    failed: list[tuple[Path, dict[str, Any]]] = []
    for trace_file in sorted(debug_dir.glob(pattern), reverse=True):
        try:
            data = json.loads(trace_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.debug("Skipping unparseable trace %s", trace_file, exc_info=True)
            continue
        if not isinstance(data, dict):
            continue
        # Hash-collision guard: 8 hex chars = 32 bits → vanishingly unlikely
        # for trace files, but the inner check makes it impossible.
        if data.get("workflow_path") != workflow_path:
            continue
        if not str(data.get("format_version", "")).startswith("2."):
            continue
        status = str(data.get("final_status") or "success")
        bucket = failed if status == "failed" else successful
        bucket.append((trace_file, data))
    return successful, failed


def _autoload_selection_with_disclosure(
    successful: list[tuple[Path, dict[str, Any]]],
    failed: list[tuple[Path, dict[str, Any]]],
) -> tuple[Path | None, str | None]:
    """Return autoload choice plus the disclosure note for non-obvious choices."""
    if successful:
        chosen = successful[0][0]
        if failed and failed[0][0].name > chosen.name:
            return chosen, (
                f"Skipped newer trace `{failed[0][0].name}` (failed run) in "
                f"favor of `{chosen.name}` (success). Pass "
                f"`--from-trace <path>` to override."
            )
        return chosen, None
    if failed:
        chosen = failed[0][0]
        return chosen, (
            f"Auto-loaded `{chosen.name}` (failed run); no successful "
            f"trace exists for this workflow. Trace-dependent recommendations "
            f"may be suppressed. Re-run the workflow to record a successful "
            f"trace, or pass `--from-trace <path>` to use a specific trace."
        )
    return None, None


def list_traces_for_workflow(
    workflow_path: str,
    *,
    debug_dir: Path | None = None,
) -> tuple[list[TraceListEntry], str | None]:
    """Enumerate stored traces for a workflow and mark the autoload choice."""
    debug_dir = debug_dir or (Path.home() / ".pflow" / "debug")
    if not debug_dir.exists():
        return [], None
    successful, failed = _collect_candidate_traces(debug_dir, workflow_path)
    chosen_path, disclosure_note = _autoload_selection_with_disclosure(successful, failed)
    current_models, has_heterogeneous_nodes = _resolve_current_workflow_model_set_for_path(workflow_path)
    entries = [
        _build_trace_list_entry(
            trace_path,
            data,
            would_be_autoloaded=trace_path == chosen_path,
            current_models=current_models,
            has_heterogeneous_nodes=has_heterogeneous_nodes,
        )
        for trace_path, data in [*successful, *failed]
    ]
    entries.sort(key=lambda entry: entry.path.name, reverse=True)
    return entries, disclosure_note


def _autoload_trace(workflow_path: str | None, notes: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    """Find the best matching 2.x trace for ``workflow_path``.

    O(matching-traces) lookup, not O(directory-size): trace filenames encode
    an 8-char md5 hash of ``workflow_path`` at write time (see
    ``runtime/workflow_trace.format_trace_filename``). The reader globs by the
    same hash prefix so we only read files that could match.

    Per DD#34, auto-load is a convenience; explicit loading
    (``--from-trace <path>``) is the contract.

    Selection ranks ``final_status in {"success", "degraded"}`` over
    ``"failed"`` (Bug 10: a newer failed run should not shadow an older
    successful one). Within a tier, newest-by-filename-timestamp wins. Absent
    ``final_status`` is treated as ``"success"`` for backward-compat with
    pre-2.1 traces and synthetic test fixtures — matches the existing
    fallback at ``_trace_coverage_for_rows``.

    Discloses the choice via Notes when ranking caused a non-newest pick, OR
    when only failed traces exist (so the agent knows recommendations may be
    suppressed downstream).

    When auto-load finds no match but other traces exist in the debug dir
    (e.g. the workflow file was renamed/moved since traces were recorded),
    appends a Notes line so the agent knows their evidence is unreachable
    via auto-load and can pass ``--from-trace`` explicitly.
    """
    if workflow_path is None:
        return None, None
    debug_dir = Path.home() / ".pflow" / "debug"
    if not debug_dir.exists():
        return None, None

    successful, failed = _collect_candidate_traces(debug_dir, workflow_path)

    chosen_path, disclosure_note = _autoload_selection_with_disclosure(successful, failed)
    if chosen_path is not None:
        if disclosure_note is not None:
            notes.append(disclosure_note)
        for candidate_path, candidate_data in [*successful, *failed]:
            if candidate_path == chosen_path:
                return candidate_data, str(candidate_path)

    # No hash-scoped match. If the debug dir holds unrelated traces, surface
    # that so the agent doesn't read greenfield output as "no evidence
    # exists" when in fact a rename has hidden it from auto-load.
    if next(iter(debug_dir.glob("workflow-trace-*.json")), None) is not None:
        notes.append(
            "Found other traces in ~/.pflow/debug/ but none matched this "
            "workflow's path (the workflow file may have been renamed or "
            "moved). Pass `--from-trace <path>` to use a specific trace, or "
            "re-run the workflow to record a new one."
        )
    return None, None


def _resolve_trace_data(
    trace_path: Path | None,
    auto_load_trace: bool,
    lookup_path: str,
    notes: list[str],
) -> tuple[dict[str, Any] | None, str | None]:
    """Load trace data via explicit path or autoload, returning ``(data, path)``.

    Trace validity is enforced per-row via ``PerCallRow.data_source`` — rows
    without a matching trace event fall through to memo/estimator/heuristic.
    Per-node model drift (trace recorded with a different model than the
    current IR resolves to) surfaces via the model-drift Notes detector below.
    """
    if trace_path is not None:
        return _load_trace_explicit(trace_path, notes), str(trace_path)
    if auto_load_trace:
        return _autoload_trace(lookup_path, notes)
    return None, None


def _resolve_trace_scope(
    trace_data: dict[str, Any] | None,
    lookup_path: str,
    notes: list[str],
) -> tuple[str, bool, bool]:
    """Determine the trace's root workflow path and whether scope is mismatched.

    Bug 5: when a trace was recorded for a parent workflow that invoked the
    analyzed workflow as a sub-workflow, the trace's ``workflow_path`` is the
    parent's. Top-level events seeded with the analyzed workflow's path
    look like they belong to the analyzed workflow (which they don't), so
    cost summation includes them — producing the bug's nonsense ratios.

    Returns ``(trace_root_workflow_path, scope_mismatch, appears_as_child)``:

    - When the trace's stored path refers to the same workflow as
      ``lookup_path`` (relative vs absolute representations of the same
      file): returns ``(lookup_path, False)``. Walker seed matches row
      workflow_paths byte-exactly so per-row attribution works.
    - When the trace's stored path refers to a different workflow: returns
      ``(trace's stored path, True)``. Walker seed is the trace's actual
      root so top-level events get correctly attributed to the parent
      (not the analyzed child). The ``True`` flag activates per-workflow
      scope filtering in ``compute_actually_paid`` and emits a Notes
      disclosure.

    Path identity uses ``_workflow_paths_refer_to_same`` (resolves relative
    vs absolute via ``os.path.realpath``; ``ir-hash:`` synthetic ids
    compare byte-exact).

    Note wording (S#9): when the analyzed workflow is detected as a
    sub-workflow inside the trace's root, the emitted note becomes a
    redirect hint ("analyze the trace root instead") rather than the
    generic scope disclosure — agents otherwise see "0 of N LLM nodes
    executed" without an obvious next step.
    """
    raw_trace_root = (trace_data.get("workflow_path") if trace_data else None) or lookup_path
    if trace_data is None or _workflow_paths_refer_to_same(raw_trace_root, lookup_path):
        return lookup_path, False, False
    appears_as_child = _workflow_appears_as_child(trace_data, lookup_path, raw_trace_root)
    if appears_as_child:
        notes.append(
            f"`{lookup_path}` appears as a sub-workflow inside the trace `{raw_trace_root}`. "
            f"To see full attribution for this run, analyze the trace root instead: "
            f"`pflow analyze-cache {raw_trace_root} --from-trace <trace-path>`."
        )
    else:
        notes.append(
            f"The trace file references workflow `{raw_trace_root}`, which differs from the "
            f"analyzed workflow `{lookup_path}`; cost figures show only events attributable "
            f"to the analyzed workflow and its sub-workflows."
        )
    return raw_trace_root, True, appears_as_child


def _derive_trace_workflow_relationship(
    *,
    trace_loaded: bool,
    scope_mismatch: bool,
    appears_as_child: bool,
    drift_count: int,
) -> str | None:
    """Single typed signal for how loaded trace evidence relates to the workflow."""
    if not trace_loaded:
        return None
    if appears_as_child:
        return "parent_redirect"
    if scope_mismatch:
        return "different_workflow"
    if drift_count > 0:
        return "same_drifted"
    return "same_fresh"


def _workflow_appears_as_child(
    trace_data: dict[str, Any],
    lookup_path: str,
    trace_root: str,
) -> bool:
    """True iff ``lookup_path`` matches any event's ``workflow_path`` in the trace.

    Used by ``_resolve_trace_scope`` to switch the scope-mismatch note from
    the generic disclosure to an actionable redirect hint. The walker
    threads ``workflow_path`` through every event via the four-tier
    resolution documented at ``TraceTree.walk`` — events from a child
    sub-workflow expose the canonical child path, so a match here proves
    the analyzed workflow ran as a sub-workflow of ``trace_root``.

    Returns ``False`` (silently) on any ``TraceTree`` construction error
    — falls back to the generic note rather than crashing the analyzer.
    """
    from pflow.core.trace_tree import TraceTree

    try:
        tree = TraceTree.from_dict(trace_data)
    except (ValueError, KeyError, TypeError):
        return False
    for we in tree.walk(workflow_path=trace_root):
        if _workflow_paths_refer_to_same(we.workflow_path, lookup_path):
            return True
    return False


def _scope_workflow_paths(
    scope_mismatch: bool,
    lookup_path: str,
    per_call_rows: list[PerCallRow],
) -> frozenset[str] | None:
    """Build the scope set for ``compute_actually_paid``'s event filter.

    Returns ``None`` when trace root matches the analyzed workflow — preserves
    tree-wide sum (today's common-case behavior). Returns the set of workflow
    paths reachable from the analyzed workflow (the analyzed path plus every
    statically-known child's path, derived from per-call rows) when scope
    mismatch was detected; events with paths outside this set get filtered.
    """
    if not scope_mismatch:
        return None
    return frozenset({lookup_path} | {r.workflow_path for r in per_call_rows if r.workflow_path is not None})


def _workflow_paths_refer_to_same(a: str | None, b: str | None) -> bool:
    """Best-effort equality for workflow paths in scope-mismatch detection.

    Handles three shapes:

    - **Same string**: trivially equal.
    - **Synthetic inline ids** (``ir-hash:<md5>``): compared as strings; never
      normalized as filesystem paths.
    - **Filesystem paths**: relative vs absolute can refer to the same file
      (trace stores cwd-relative path; analyzer is called with absolute).
      ``os.path.realpath`` resolves both to canonical absolute form without
      requiring the file to exist.

    Empty / None / mixed-shape values are treated as different.
    """
    if not a or not b:
        return a == b
    if a == b:
        return True
    if a.startswith("ir-hash:") or b.startswith("ir-hash:"):
        return False
    return os.path.realpath(a) == os.path.realpath(b)


def _resolve_ir_static_model_for_node(
    node: Mapping[str, Any] | None,
    default_model: str | None,
) -> str | None:
    """Return the IR-static model for a single LLM node.

    Concrete models return a normalized model string. Templated batch-item
    models return ``""`` to mark declared heterogeneous-model workflows, where
    comparing a trace model set against one current model would be misleading.
    Other templated models return ``None`` because they are unresolvable from
    static IR. Missing explicit model falls back to the workflow default.
    """
    if node is None:
        return None
    explicit = node.get("params", {}).get("model") or node.get("model")
    if isinstance(explicit, str) and "${" in explicit:
        from pflow.runtime.template_resolver import TemplateResolver

        batch_alias = _batch_alias_for_node(node)
        for match in TemplateResolver.TEMPLATE_PATTERN.finditer(explicit):
            for operand in TemplateResolver.split_coalesce_operands(match.group(1)):
                # Literal operands (Optional A) contribute no trace ref.
                if TemplateResolver.is_literal_operand(operand):
                    continue
                root = TemplateResolver.extract_root_node_id(operand)
                if root == batch_alias:
                    return ""
        return None
    if explicit:
        return normalize_model_name(str(explicit))
    if default_model:
        return normalize_model_name(default_model)
    return None


def _batch_alias_for_node(node: Mapping[str, Any]) -> str:
    batch = node.get("batch")
    if not isinstance(batch, Mapping):
        return "item"
    raw_alias = batch.get("as")
    if not isinstance(raw_alias, str):
        raw_alias = batch.get("item_alias")
    return raw_alias if isinstance(raw_alias, str) else "item"


def _resolve_current_workflow_model_set(
    workflow_ir: Mapping[str, Any],
    default_model: str | None,
) -> tuple[frozenset[str], bool]:
    """Resolved static models plus a flag for IR-declared heterogeneous nodes."""
    models: set[str] = set()
    has_heterogeneous = False
    nodes = workflow_ir.get("nodes", []) if isinstance(workflow_ir, Mapping) else []
    for node in nodes:
        if not _is_llm_node(node):
            continue
        model = _resolve_ir_static_model_for_node(node, default_model)
        if model is None:
            continue
        if model == "":
            has_heterogeneous = True
            continue
        normalized = normalize_model_name(model)
        if normalized:
            models.add(normalized)
    return frozenset(models), has_heterogeneous


def _resolve_current_workflow_model_set_for_path(workflow_path: str) -> tuple[frozenset[str], bool]:
    """Load a workflow path and return comparable model data for trace listing."""
    if workflow_path.startswith("ir-hash:"):
        return frozenset(), False
    try:
        from pflow.execution.workflow_resolver import resolve_workflow

        resolved = resolve_workflow(workflow_path)
    except Exception:
        logger.debug("Cannot resolve workflow for trace-list model comparison", exc_info=True)
        return frozenset(), False
    default_model = get_default_workflow_model()
    settings = resolved.ir.get("settings") if isinstance(resolved.ir, Mapping) else None
    if isinstance(settings, Mapping) and isinstance(settings.get("model"), str):
        default_model = str(settings["model"])
    try:
        cw_result = walk_cross_workflow(
            resolved.ir,
            base_path=Path(workflow_path).parent,
            root_workflow_path=workflow_path,
        )
    except Exception:
        logger.debug("Cannot walk nested workflows for trace-list model comparison", exc_info=True)
        return _resolve_current_workflow_model_set(resolved.ir, default_model)
    models: set[str] = set()
    has_heterogeneous = False
    for workflow_ir in getattr(cw_result, "irs_by_workflow", {}).values():
        workflow_models, workflow_has_heterogeneous = _resolve_current_workflow_model_set(workflow_ir, default_model)
        models.update(workflow_models)
        has_heterogeneous = has_heterogeneous or workflow_has_heterogeneous
    return frozenset(models), has_heterogeneous


def _build_trace_list_entry(
    trace_path: Path,
    data: dict[str, Any],
    *,
    would_be_autoloaded: bool,
    current_models: frozenset[str],
    has_heterogeneous_nodes: bool,
) -> TraceListEntry:
    raw_summary = data.get("llm_summary")
    llm_summary: Mapping[str, Any] = raw_summary if isinstance(raw_summary, Mapping) else {}
    trace_models = frozenset(
        normalized
        for raw_model in llm_summary.get("models_used", [])
        if isinstance(raw_model, str)
        for normalized in [normalize_model_name(raw_model)]
        if normalized
    )
    if has_heterogeneous_nodes:
        drift_count: int | None = None
    elif current_models and trace_models:
        drift_count = len(current_models.symmetric_difference(trace_models))
    else:
        drift_count = 0
    start_time_raw = data.get("start_time")
    return TraceListEntry(
        path=trace_path,
        final_status=str(data.get("final_status") or "success"),
        recorded_at=start_time_raw if isinstance(start_time_raw, str) and start_time_raw else None,
        duration_ms=_safe_float(data.get("duration_ms")),
        llm_call_count=_safe_int_from_mapping(llm_summary, "total_calls") or 0,
        total_cost_usd=_safe_float(llm_summary.get("total_cost_usd")),
        models_used=tuple(sorted(trace_models)),
        would_be_autoloaded=would_be_autoloaded,
        model_drift_count=drift_count,
    )


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int_from_mapping(data: Mapping[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _edge_child_paths(cw_result: Any) -> dict[str, str]:
    """Map parent workflow node id to child workflow path for trace threading.

    Used by the trace walker to attribute sub_workflow_events AND homogeneous
    static workflow batches to the resolved absolute child workflow path.
    The walker's ``cw_result.edges`` carry the runtime-resolved absolute
    path on each edge; this helper folds them into the
    ``parent_node_id → resolved_path`` shape that :meth:`TraceTree.walk`
    consumes via its ``edges=`` kwarg.

    **Why this still exists** (the cleanup plan called for deletion). Production
    traces store ``node_params["workflow"]`` as the RAW IR string the user
    wrote — often a relative path like ``./child.pflow.md``. The analyzer's
    ``cw_result.irs_by_workflow`` is keyed by the RESOLVED ABSOLUTE path
    produced by ``resolve_sub_workflow``. Pivoting attribution off
    ``node_params.workflow`` alone would mismatch the keys. This helper
    bridges raw → resolved by going through the walker's edges, which carry
    the resolved path.

    For HETEROGENEOUS workflow batches (one parent_node_id spawning child
    workflows of different paths via ``workflow: ${item.workflow}``), this
    map collapses the N edges into one (last-edge-wins). New traces avoid
    the lossy map by recording per-item ``workflow_path`` after runtime
    sub-workflow resolution; old traces fall back to a normalized
    ``template_resolutions["workflow"]["resolved"]`` value in
    :meth:`TraceTree.walk`. The edge-map fallback remains important for
    HOMOGENEOUS static workflow batches (single child workflow, no template),
    which have no per-item workflow template resolution metadata.
    """
    paths: dict[str, str] = {}
    for edge in getattr(cw_result, "edges", ()) or ():
        parent_node_id = getattr(edge, "parent_node_id", None)
        child_workflow = getattr(edge, "child_workflow", None)
        if parent_node_id and child_workflow:
            paths[str(parent_node_id)] = str(child_workflow)
    return paths


def _build_trace_execution_index(
    trace_data: dict[str, Any] | None,
    root_workflow_path: str,
    edge_child_paths: dict[str, str],
) -> TraceExecutionIndex:
    """Index trace execution and LLM costs by ``(workflow_path, node_id)``.

    ``edge_child_paths`` provides the parent_node_id → resolved-absolute
    child workflow path mapping for sub_workflow_events. Heterogeneous
    workflow batches use per-item ``template_resolutions`` instead — this
    map's collision behaviour for those parents is intentionally bypassed
    inside :meth:`TraceTree.walk`.
    """
    if trace_data is None:
        return _empty_trace_execution_index()
    from pflow.core.trace_tree import TraceTree

    try:
        tree = TraceTree.from_dict(trace_data)
    except ValueError:
        return _empty_trace_execution_index()

    totals: dict[tuple[str | None, str], float] = {}
    workflow_totals: dict[str | None, float] = {}
    workflow_found: set[str | None] = set()
    found: set[tuple[str | None, str]] = set()
    partial: set[tuple[str | None, str]] = set()
    executed_keys, workflows_with_trace, local_counts = _collect_trace_walk_metadata(
        tree,
        root_workflow_path=root_workflow_path,
        edge_child_paths=edge_child_paths,
    )
    # Always populate the historical call index — cached events carry
    # ``input_tokens`` / ``output_tokens`` preserved from the original run,
    # which downstream tier-1 token readers need to project costs for
    # memo-hit-only traces. Current-cost summation happens in the actual-cost
    # pass below.
    llm_call_lists_by_key = _collect_trace_llm_call_lists(
        tree,
        root_workflow_path=root_workflow_path,
        edge_child_paths=edge_child_paths,
        descend_cached_subtrees=True,
    )
    llm_calls_by_key = {key: _aggregate_trace_llm_calls(calls) for key, calls in llm_call_lists_by_key.items()}
    provider_llm_call_lists_by_key = _collect_trace_llm_call_lists(
        tree,
        root_workflow_path=root_workflow_path,
        edge_child_paths=edge_child_paths,
        descend_cached_subtrees=False,
    )
    provider_llm_calls_by_key = {
        key: _aggregate_trace_llm_calls(calls) for key, calls in provider_llm_call_lists_by_key.items()
    }
    for leaf in tree.iter_actual_cost_events(edges=edge_child_paths, workflow_path=root_workflow_path):
        _record_trace_cost_leaf(
            leaf,
            root_workflow_path=root_workflow_path,
            totals=totals,
            workflow_totals=workflow_totals,
            found=found,
            workflow_found=workflow_found,
            partial=partial,
        )
    costs_by_key: dict[tuple[str | None, str], tuple[float | None, str]] = {
        key: (totals.get(key, 0.0), "trace_partial" if key in partial else "trace") for key in found
    }
    cost_by_workflow: dict[str | None, float | None] = {key: workflow_totals.get(key, 0.0) for key in workflow_found}
    return TraceExecutionIndex(
        costs_by_key=costs_by_key,
        llm_calls_by_key=llm_calls_by_key,
        llm_call_lists_by_key={key: tuple(calls) for key, calls in llm_call_lists_by_key.items()},
        provider_llm_calls_by_key=provider_llm_calls_by_key,
        provider_llm_call_lists_by_key={key: tuple(calls) for key, calls in provider_llm_call_lists_by_key.items()},
        outputs_by_key=_collect_trace_outputs_by_key(
            tree,
            root_workflow_path=root_workflow_path,
            edge_child_paths=edge_child_paths,
        ),
        executed_keys=executed_keys,
        workflows_with_trace=workflows_with_trace,
        current_cost_by_workflow=cost_by_workflow,
        provider_llm_call_count=sum(len(calls) for calls in provider_llm_call_lists_by_key.values()),
        local_memo_llm_hit_count=local_counts["memo"],
        local_in_process_llm_hit_count=local_counts["in_process"],
        local_cache_input_tokens=local_counts["input_tokens"],
        provider_cache_creation_input_tokens=_sum_trace_call_int_field(
            provider_llm_call_lists_by_key,
            "cache_creation_input_tokens",
        ),
        provider_cache_read_input_tokens=_sum_trace_call_int_field(
            provider_llm_call_lists_by_key,
            "cache_read_input_tokens",
        ),
        trace_loaded=True,
    )


def _empty_trace_execution_index() -> TraceExecutionIndex:
    return TraceExecutionIndex({}, {}, {}, {}, {}, {}, set(), set(), {}, trace_loaded=False)


def _collect_trace_outputs_by_key(
    tree: Any,
    *,
    root_workflow_path: str,
    edge_child_paths: dict[str, str],
) -> dict[tuple[str | None, str], Any]:
    """Collect non-empty event node outputs keyed by workflow scope and node id."""
    outputs: dict[tuple[str | None, str], Any] = {}
    for walk_event in tree.walk(edges=edge_child_paths, workflow_path=root_workflow_path):
        event = walk_event.event
        output = event.get("node_output")
        if output is None:
            continue
        if isinstance(output, (dict, list, str, tuple, set)) and not output:
            continue
        outputs[(walk_event.workflow_path, walk_event.event_node_id)] = output
    return outputs


def _diagnostics_from_trace_warnings(trace_data: Mapping[str, Any] | None) -> list[Diagnostic]:
    """Rehydrate catalog-backed runtime warnings recorded in a trace.

    Runtime producers write ``Diagnostic.to_display_dict()`` through
    ``WorkflowTraceCollector.set_warnings``. Rebuilding via ``make_diagnostic``
    keeps ``analyze-cache --from-trace`` on the same catalog contract as live
    runtime output while preserving measured runtime evidence such as
    ``cache.below-min-rendered`` token counts.
    """
    raw_warnings = trace_data.get("warnings") if trace_data is not None else None
    if not isinstance(raw_warnings, list):
        return []

    diagnostics: list[Diagnostic] = []
    for raw in raw_warnings:
        if not isinstance(raw, Mapping):
            continue
        warning_id = raw.get("id")
        if not isinstance(warning_id, str) or warning_id not in CACHE_WARNING_CATALOG:
            continue

        context = raw.get("context")
        context_kwargs: dict[str, Any] = dict(context) if isinstance(context, Mapping) else {}
        for key, value in raw.items():
            if key in {"id", "severity", "message", "source", "title", "suggestions", "node_id", "context"}:
                continue
            context_kwargs.setdefault(str(key), value)

        node_id = raw.get("node_id")
        if not isinstance(node_id, str):
            node_id = context_kwargs.pop("node_id", None)
        if not isinstance(node_id, str):
            node_id = None

        try:
            diagnostics.append(make_diagnostic(warning_id, node_id=node_id, **context_kwargs))
        except (KeyError, TypeError, ValueError):
            logger.debug("Skipping malformed catalog warning in trace: %r", raw, exc_info=True)
    return diagnostics


def _collect_trace_walk_metadata(
    tree: Any,
    *,
    root_workflow_path: str,
    edge_child_paths: dict[str, str],
) -> tuple[set[tuple[str | None, str]], set[str | None], dict[str, int]]:
    executed_keys: set[tuple[str | None, str]] = set()
    workflows_with_trace: set[str | None] = set()
    local_counts = {"memo": 0, "in_process": 0, "input_tokens": 0}
    for we in tree.walk(edges=edge_child_paths, workflow_path=root_workflow_path):
        # Batch items typically lack their own node_id; fall back to the
        # owner (the batch parent's id) so they're attributed to the parent.
        node_id = str(we.event.get("node_id", we.owner_node_id))
        executed_keys.add((we.workflow_path, node_id))
        workflows_with_trace.add(we.workflow_path)
        if we.is_cached and we.llm_call is not None:
            cache_source = str(we.llm_call.get("cache_source") or "")
            if cache_source in {"memo", "in_process"}:
                local_counts[cache_source] += 1
                local_counts["input_tokens"] += int(we.llm_call.get("input_tokens") or 0)
    return executed_keys, workflows_with_trace, local_counts


def _collect_trace_llm_call_lists(
    tree: Any,
    *,
    root_workflow_path: str,
    edge_child_paths: dict[str, str],
    descend_cached_subtrees: bool,
) -> dict[tuple[str | None, str], list[dict[str, Any]]]:
    calls_by_key: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
    for leaf in tree.iter_llm_leaves(
        descend_cached_subtrees=descend_cached_subtrees,
        edges=edge_child_paths,
        workflow_path=root_workflow_path,
    ):
        call = leaf.llm_call
        if call is None or call.get("is_warmup"):
            continue
        node_id = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id
        key = (leaf.workflow_path or root_workflow_path, node_id)
        calls_by_key.setdefault(key, []).append(dict(call))
    return calls_by_key


def _sum_trace_call_int_field(
    calls_by_key: dict[tuple[str | None, str], list[dict[str, Any]]],
    field_name: str,
) -> int:
    return sum(int(call.get(field_name) or 0) for calls in calls_by_key.values() for call in calls)


def _aggregate_trace_llm_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse multiple trace calls into row-level telemetry.

    Token integer fields are normalized to per-call by dividing the cohort sum
    by ``len(calls)``. This is the producer-side normalization point for
    ``PerCallRow`` token fields; downstream consumers multiply by
    ``invocation_count_for(row)`` when they need workflow-level totals.

    ``cost_usd`` is deliberately NOT carried through. ``PerCallRow.cost_usd``
    is sourced via a separate ``TraceTree`` cost walker
    (``AnalysisContext.cost_usd_for_node``). Dropping it from the aggregate
    prevents a future consumer from silently reading the first event's cost
    as if it were the row total.
    """
    if not calls:
        return {}
    aggregate = dict(calls[0])
    aggregate.pop("cost_usd", None)
    divisor = max(1, len(calls))
    int_fields = (
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "thinking_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    for field_name in int_fields:
        values = [call.get(field_name) for call in calls]
        if any(value is not None for value in values):
            aggregate[field_name] = round(sum(int(value or 0) for value in values) / divisor)
    models = sorted({str(call.get("model")) for call in calls if call.get("model")})
    aggregate["model"] = models[0] if len(models) == 1 else ""
    skipped: list[str] = []
    for call in calls:
        chunks = call.get("cache_chunks_skipped") or []
        if isinstance(chunks, list):
            skipped.extend(str(chunk) for chunk in chunks)
    if skipped:
        aggregate["cache_chunks_skipped"] = sorted(set(skipped))
    return aggregate


def _record_trace_cost_leaf(
    leaf: Any,
    *,
    root_workflow_path: str,
    totals: dict[tuple[str | None, str], float],
    workflow_totals: dict[str | None, float],
    found: set[tuple[str | None, str]],
    workflow_found: set[str | None],
    partial: set[tuple[str | None, str]],
) -> None:
    node_id = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id
    key = (leaf.workflow_path or root_workflow_path, node_id)
    workflow_key = leaf.workflow_path or root_workflow_path
    if leaf.is_cached:
        # Cached events are observed zero-cost boundaries for this run.
        # Historical llm_call data remains indexed separately for token
        # estimation, but current cost is zero.
        found.add(key)
        workflow_found.add(workflow_key)
        totals.setdefault(key, 0.0)
        workflow_totals.setdefault(workflow_key, 0.0)
        return

    call = leaf.llm_call
    if call is None or "cost_usd" not in call:
        return

    found.add(key)
    workflow_found.add(workflow_key)
    cost = call.get("cost_usd")
    if cost is None:
        partial.add(key)
        totals.setdefault(key, 0.0)
        workflow_totals.setdefault(workflow_key, 0.0)
    else:
        totals[key] = totals.get(key, 0.0) + float(cost)
        workflow_totals[workflow_key] = workflow_totals.get(workflow_key, 0.0) + float(cost)


def _is_llm_node(node: Any) -> bool:
    """Return True for any LLM-typed IR node (regardless of ``prompt_cache:``).

    Discrepancy detection runs on every ``llm_call`` trace leaf — even nodes
    without a declared subset can have a memo ``cache_key`` to compare. The
    runtime cache_key is computed for ALL LLM nodes; restricting prediction
    to ``prompt_cache:``-declared nodes would silently miss memo divergence
    (and break tests that synthesize cache events for non-prompt_cache LLM
    nodes to exercise the consumption path).
    """
    return isinstance(node, dict) and node.get("type") == "llm"
