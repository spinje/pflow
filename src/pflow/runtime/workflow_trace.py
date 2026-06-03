"""Detailed trace collection for workflow debugging."""

import hashlib
import json
import logging
import re
import uuid
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from pflow.core.diagnostic import Diagnostic
from pflow.core.exceptions import OnlySnapshotMissingError
from pflow.core.trace_io import intern_blobs, load_trace_file
from pflow.core.validation_utils import VALIDATION_PLACEHOLDER
from pflow.runtime.engine.instrumentation import is_llm_node_type

logger = logging.getLogger(__name__)

# Trace format version. 2.5.0 adds the top-level ``blobs`` map with
# ``{"$pflow_blob": hash}`` refs for large string leaves, and canonicalizes
# LLM prompt/system into ``llm_prompt``/``llm_system`` by removing redundant
# LLM copies from node_output/template_resolutions/node_params. Consumers gate
# on ``startswith("2.")``; old traces remain readable.
TRACE_FORMAT_VERSION = "2.5.0"


def format_trace_filename(workflow_path: str | None, workflow_name: str, timestamp: str) -> str:
    """Compose a trace filename whose hash prefix encodes ``workflow_path``.

    Filename schema: ``workflow-trace-{wf_hash}-{safe_name}-{timestamp}.json``
    where ``wf_hash`` is the first 8 hex chars of ``md5(workflow_path or "")``.
    The production caller (``save_to_file``) passes a microsecond-granular
    ``timestamp`` (``%Y%m%d-%H%M%S-%f``) so two writes in the same wall-clock
    second don't collide — load-bearing for ``--only`` snapshots (issue #443),
    where a same-second ``--only`` trace would otherwise overwrite the full-run
    snapshot it depends on. The glob keys on the hash prefix, so the timestamp
    format is free to vary; callers passing their own timestamp are unaffected.

    The hash makes ``analyze-cache`` autoload O(matching-traces) instead of
    O(directory-size): the reader globs by the same hash prefix to narrow
    candidates before reading any file's contents. Filename collisions across
    distinct workflows are guarded by a contents-level ``workflow_path``
    re-check at read time.

    Collision class for ``workflow_path=None``/empty: ``wf_hash`` is
    ``d41d8cd9`` (md5 of empty string), so all None-path traces share that
    prefix. Production paths always pass a real value (file path or
    ``ir-hash:<md5>`` for inline runs); test fixtures and report-generation
    tools doing prefix-based discovery should expect this collision class
    and use the contents-level re-check as the discriminator.
    """
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "-", workflow_name)[:30]
    safe_name = re.sub(r"-+", "-", safe_name).strip("-")

    wf_hash = hashlib.md5((workflow_path or "").encode("utf-8"), usedforsecurity=False).hexdigest()[:8]

    if safe_name and safe_name != "workflow":
        return f"workflow-trace-{wf_hash}-{safe_name}-{timestamp}.json"
    return f"workflow-trace-{wf_hash}-{timestamp}.json"


def _trace_recency_key(path: Path) -> tuple[str, str]:
    """Sort key ranking trace files newest-first (under ``reverse=True``).

    The filename is ``workflow-trace-{wf_hash}-{safe_name}-{timestamp}.json`` —
    the ``{safe_name}`` segment sits BEFORE the timestamp, so sorting the whole
    filename ranks the name prefix first. The SAME ``workflow_path`` can produce
    different ``safe_name``s (a saved-library run vs the same file run directly,
    or after a rename — see ``format_trace_filename``), so a whole-filename sort
    could rank an older run above a newer one and let ``--only`` restore STALE
    upstream. Sort on the trailing ``YYYYMMDD-HHMMSS[-ffffff]`` timestamp instead
    (filename as a deterministic tiebreak for same-microsecond writes). Files
    without a parseable timestamp sort last (oldest). PR #459 review (CODEX-1).
    """
    match = re.search(r"(\d{8}-\d{6}(?:-\d+)?)\.json$", path.name)
    return (match.group(1) if match else "", path.name)


def _iter_workflow_traces(debug_dir: Path, workflow_path: str) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Yield ``(path, trace_data)`` for this workflow's reusable traces, newest-first.

    The single candidate iterator shared by every trace-snapshot consumer (the
    ``--only`` snapshot loader below AND ``analyze-cache``'s autoload via
    ``prompt_cache_analysis.trace_loading._collect_candidate_traces``) so their
    selection scaffolding cannot drift. Applies, in order:

    - glob by the same 8-char md5 hash prefix ``format_trace_filename`` embeds
      (O(matching-traces), not O(directory-size));
    - parse, skipping unparseable / non-dict files;
    - a contents-level ``workflow_path`` collision guard (the hash prefix can
      collide; the stored path is the discriminator);
    - the ``format_version.startswith("2.")`` gate;
    - exclusion of ``--only`` traces (``only_node is not None``) — an ``--only``
      run records ONLY its target, so it must never masquerade as a full-run
      snapshot source nor poison ``analyze-cache`` autoload.

    INVARIANT (load-bearing): this iterator MUST NOT filter on ``final_status``.
    Each consumer owns its own status policy — the cache-analysis loader relies
    on a ``failed``-bucket fallback that silently breaks if status filtering
    moves in here. Keep status decisions in the callers.
    """
    wf_hash = hashlib.md5(workflow_path.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    pattern = f"workflow-trace-{wf_hash}-*.json"
    for trace_file in sorted(debug_dir.glob(pattern), key=_trace_recency_key, reverse=True):
        try:
            data = load_trace_file(trace_file)
        except (json.JSONDecodeError, OSError):
            logger.debug("Skipping unparseable trace %s", trace_file, exc_info=True)
            continue
        if not isinstance(data, dict):
            continue
        if data.get("workflow_path") != workflow_path:
            continue
        if not str(data.get("format_version", "")).startswith("2."):
            continue
        if data.get("only_node") is not None:
            continue
        yield trace_file, data


def _trace_warnings_provably_benign(data: dict[str, Any]) -> bool:
    """Whether a degraded trace's warnings PROVE the degradation lost no data.

    Returns True only when there IS a readable ``warnings`` array AND every entry
    is provably non-degrading — INFO severity, or a parser/validator source
    (input-quality, not runtime data loss; mirrors the trace-level status
    blacklist and the result-level ``_is_degrading_warning`` severity rule). An
    INFO-only advisory (empty-input batch, loop-cap) is benign → no snapshot
    advisory; a WARNING/ERROR runtime warning (e.g. a batch host with
    ``error_handling: continue`` that dropped failed items) is NOT benign → the
    caller warns.

    Crucially returns False when the array is missing/empty/unreadable: we cannot
    PROVE a degraded run lost no data, so the caller keeps the (fail-safe)
    degraded status rather than silently restoring possibly-partial upstream. A
    degraded run with no usable warning detail (older/generated trace) must still
    warn. PR #459 review (CODEX-3).
    """
    warnings = data.get("warnings")
    if not isinstance(warnings, list) or not warnings:
        return False
    return all(
        isinstance(warning, dict)
        and (str(warning.get("severity", "")).lower() == "info" or warning.get("source") in ("parser", "validator"))
        for warning in warnings
    )


def _strip_redundant_llm_trace_fields(event: dict[str, Any]) -> None:
    """Keep LLM prompt/system content only in canonical ``llm_*`` fields.

    Parent/non-batch path only. We do NOT strip ``user_message_blocks`` here
    (unlike ``_capture_item_trace``) because prewarm is batch-only, so a
    non-batch ``node_output`` never carries it. The batch path owns that strip.
    """
    for container_key in ("node_output", "template_resolutions"):
        container = event.get(container_key)
        if isinstance(container, dict):
            container.pop("prompt", None)
            container.pop("system", None)

    node_params = event.get("node_params")
    if isinstance(node_params, dict):
        node_params.pop("prompt", None)


def load_full_run_events(
    workflow_path: str | None,
    *,
    debug_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], str] | None:
    """Return ``(nodes, status)`` from the most recent reusable full run.

    Scans ``~/.pflow/debug`` (override via ``debug_dir``) newest-first through
    ``_iter_workflow_traces`` and returns the first trace whose ``final_status``
    is ``"success"`` or ``"degraded"`` (absent → ``"success"`` for pre-2.4 and
    synthetic fixtures); ``"failed"`` runs are skipped.

    The returned ``status`` is ``"degraded"`` when the trace's ``final_status``
    is ``"degraded"`` UNLESS its warnings prove the degradation was benign — see
    ``_trace_warnings_provably_benign``. A trace marked ``"degraded"`` solely by
    an INFO advisory (empty batch, loop cap) loses no data and is reported
    ``"success"`` here, so the caller's loud "partial upstream" advisory doesn't
    false-fire on benign runs. But a degraded trace with NO usable warning detail
    (older/generated trace) stays ``"degraded"`` (fail-safe) so the caller warns
    before seeding possibly-incomplete upstream rather than silently restoring it.

    Returns ``None`` when ``workflow_path`` is falsy, the debug dir is missing,
    or no usable trace exists. An empty ``nodes`` list is treated as NO match
    (a zero-event success trace can't seed a usable snapshot), so callers can
    distinguish "no usable snapshot" from "empty snapshot".
    """
    if not workflow_path:
        return None
    debug_dir = debug_dir if debug_dir is not None else (Path.home() / ".pflow" / "debug")
    if not debug_dir.exists():
        return None
    for _path, data in _iter_workflow_traces(debug_dir, workflow_path):
        final_status = str(data.get("final_status") or "success")
        if final_status not in ("success", "degraded"):
            continue
        nodes = data.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            continue
        status = "success" if (final_status != "degraded" or _trace_warnings_provably_benign(data)) else "degraded"
        return nodes, status
    return None


def load_snapshot_or_raise(
    workflow_path: str | None,
    only_node: str,
    *,
    snapshot_events: list[dict[str, Any]] | None = None,
    debug_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Resolve the upstream snapshot for an ``--only`` run, or hard-error.

    The single home for the "no usable snapshot → hard error" decision, called
    by BOTH the engine (``_run_only_snapshot``) and the dry-run planner so
    neither can silently fall back to re-walking the graph (which would re-fire
    side-effecting upstream — the whole point of issue #443).

    ``snapshot_events`` (when truthy) short-circuits the on-disk lookup — used
    by tests to inject synthetic events — and is treated as a ``"success"``
    source. Otherwise the most recent reusable full run is loaded from disk.

    Raises ``OnlySnapshotMissingError`` when the result is falsy. The falsy
    check (not ``is not None``) is load-bearing: an EMPTY events list must raise,
    not seed an empty store.
    """
    if snapshot_events:
        return snapshot_events, "success"
    loaded = load_full_run_events(workflow_path, debug_dir=debug_dir)
    if not loaded:
        raise OnlySnapshotMissingError(only_node)
    return loaded


@dataclass
class _LLMSummaryAccumulator:
    """Accumulator for ``WorkflowTraceCollector._collect_llm_summary``.

    Lives at module level to keep the recursive collector small (ruff C901).
    Mirrors ``MetricsCollector.calculate_costs`` semantics: when any leaf
    has ``cost_usd: None``, ``total_cost_usd`` becomes ``None`` and we surface
    ``partial_cost_usd`` + ``unavailable_models`` + ``pricing_available: False``.
    """

    total_calls: int = 0
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_num_turns: int = 0
    agent_calls: int = 0
    priced_cost: float = 0.0
    models: set[str] = field(default_factory=set)
    unavailable_models: Counter[str] = field(default_factory=Counter)
    unavailable_models_unnamed_count: int = 0

    def add_leaf(self, call: dict[str, Any]) -> None:
        is_warmup = call.get("is_warmup", False)
        if not is_warmup:
            self.total_calls += 1
        self.total_tokens += call.get("total_tokens", 0)
        self.total_input_tokens += call.get("input_tokens", 0)
        self.total_output_tokens += call.get("output_tokens", 0)
        self.total_cache_creation_tokens += call.get("cache_creation_input_tokens", 0) or 0
        self.total_cache_read_tokens += call.get("cache_read_input_tokens", 0) or 0
        # num_turns is claude-code-only — its presence marks an AGENT call (one
        # invocation = many internal turns), distinct from a single-shot llm call.
        turns = call.get("num_turns")
        if turns is not None and not is_warmup:
            self.agent_calls += 1
            if isinstance(turns, int) and turns > 0:
                self.total_num_turns += turns
        cost = call.get("cost_usd")
        model = call.get("model") or ""
        is_real_model = bool(model) and model != VALIDATION_PLACEHOLDER
        if cost is None:
            if is_real_model and not is_warmup:
                self.unavailable_models[model] += 1
            elif not is_real_model and not is_warmup:
                self.unavailable_models_unnamed_count += 1
        else:
            self.priced_cost += cost
        if is_real_model and not is_warmup:
            self.models.add(model)

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "total_calls": self.total_calls,
            "total_tokens": self.total_tokens,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "models_used": sorted(self.models),
        }
        # Additive within trace 2.x — omitted when zero so older readers and
        # non-caching/non-agent runs stay unchanged. ``total_input_tokens`` is
        # the UNCACHED slice; renderers add the two cache tiers for the true total.
        if self.total_cache_creation_tokens:
            result["total_cache_creation_tokens"] = self.total_cache_creation_tokens
        if self.total_cache_read_tokens:
            result["total_cache_read_tokens"] = self.total_cache_read_tokens
        if self.agent_calls:
            result["agent_calls"] = self.agent_calls
        if self.total_num_turns:
            result["total_num_turns"] = self.total_num_turns
        if self.unavailable_models or self.unavailable_models_unnamed_count:
            result["total_cost_usd"] = None
            result["partial_cost_usd"] = round(self.priced_cost, 6) if self.priced_cost > 0 else None
            # Bundle 7 / F#17 deferred: emit per-model call counts so renderers
            # can render "model (N calls)" without rebuilding the count from
            # individual call events. Additive within trace 2.x — consumers
            # gate on ``format_version.startswith("2.")``.
            result["unavailable_models"] = [
                {"name": name, "calls": calls} for name, calls in sorted(self.unavailable_models.items())
            ]
            result["unavailable_models_unnamed_count"] = self.unavailable_models_unnamed_count
            result["pricing_available"] = False
        else:
            result["total_cost_usd"] = round(self.priced_cost, 6)
            result["pricing_available"] = True
        return result


def final_events_by_node(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Last event per node_id — represents each node's terminal state.

    Single source of truth for the "last event per node_id = final state"
    aggregation rule. Used by WorkflowTraceCollector at write time (status
    determination, failed_node_ids derivation) and by ``trace_report._collect_errors``
    at read time (Errors-section rendering, fallback for legacy traces without
    ``failed_node_ids``). If this rule ever evolves, it evolves here.

    Loop recovery records multiple events for the same node_id; only the most
    recent reflects the node's final outcome.

    Keyed by node_id — batch items (which carry ``index``, not ``node_id``)
    and nested sub-workflow events are intentionally ignored.

    **Assumes ``events`` is in chronological append order** (as produced by
    ``record_node_execution``). The function takes the LAST occurrence of
    each node_id as the final state — callers must not pre-sort or merge
    out-of-order events, or loop-recovery aggregation will silently report
    the wrong final state.
    """
    final: dict[str, dict[str, Any]] = {}
    for event in events:
        nid = event.get("node_id")
        if nid:
            final[nid] = event
    return final


# The EXACT engine-injected reserved keys that ``apply_memo_hit`` strips when
# restoring a cached blob to ``shared[node_id]`` (instrumentation.py). Using the
# exact set — NOT a broad ``startswith("__")`` — is load-bearing: a fresh run's
# ``shared[node_id]`` keeps ``__metrics__`` (which ``apply_memo_hit`` also keeps),
# so a snapshot restore must keep it too or restored vs fresh state would differ.
_SNAPSHOT_RESERVED = {"__pflow_stats__", "__pflow_warnings__"}


def seed_snapshot_into_shared(
    shared: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    exclude: str,
) -> dict[str, dict[str, Any]]:
    """Seed the target's UPSTREAM outputs from a snapshot into ``shared``.

    Mirrors ``apply_memo_hit``'s restore shape: each in-scope node's terminal
    ``node_output`` is written to ``shared[node_id]`` with the engine-injected
    reserved keys (``_SNAPSHOT_RESERVED``) filtered out. Nodes with no captured
    output are skipped (a failed node forces the trace to ``"failed"`` → already
    rejected by the loader, so the only no-output case here is a node that
    genuinely produced nothing).

    Scope = nodes that executed BEFORE ``exclude`` (the ``--only`` target) in the
    snapshot's execution order. pflow templates can only reference EARLIER steps,
    so this slice provably contains every node the target can read — while
    excluding DOWNSTREAM nodes, whose stale output would otherwise be addressable
    via ``-o <downstream>`` / ``shared_after`` despite not having run this
    invocation (PR #459 CODEX-2). Loop-safe: the pre-target slice yields each
    node's value AS OF when the target first ran. If the target is absent from
    the snapshot (it ran on a branch the snapshot didn't take, or was added
    since), fall back to seeding every node so its references still resolve — a
    genuinely missing one then surfaces as the normal loud unresolved-reference
    error.

    NEVER seeds ``exclude`` itself — the target must execute fresh, never read a
    stale copy of itself. Returns the ``final_events_by_node`` map (restricted to
    the seeded scope) so callers can derive ``restored_nodes`` without a second pass.
    """
    target_idx = next((i for i, e in enumerate(events) if e.get("node_id") == exclude), None)
    in_scope = events if target_idx is None else events[:target_idx]
    final = final_events_by_node(in_scope)
    for nid, ev in final.items():
        if nid == exclude:
            continue
        output = ev.get("node_output")
        if output is None:
            continue
        shared[nid] = {k: v for k, v in output.items() if k not in _SNAPSHOT_RESERVED}
    return final


class WorkflowTraceCollector:
    """Collects detailed execution traces for workflow debugging.

    Captures node execution data, template resolutions, per-node outputs,
    and LLM interactions. Saves traces to ~/.pflow/debug/ for analysis.

    Format ``2.x`` shape:

    - Tree-structured events with ``node_params``, ``template_resolutions``,
      ``node_output``, ``batch_items``, ``sub_workflow_events``.
    - No value truncation (only internal key filtering and binary replacement).
    - Top-level ``workflow_path`` (resolved file path or ``ir-hash:<md5>``
      for inline runs).
    - Per-event cache-correlation fields on LLM events: ``cache_key``,
      ``cache_source``, ``cache_age_sec``, ``cache_chunks_skipped``,
      ``cache_skipped_reason`` (``"below_min"`` when a runtime cache marker
      strip fired), and ``prewarm_disabled_reason`` (``"below_min"`` when
      workflow-entry pre-flight disabled prewarm for the node). These flow
      through ``llm_call`` via the ``llm_usage`` channel.
    - Per-event ``llm_system`` capturing the effective system content
      the LLM saw — ``str`` for plain system params, ``list[dict]`` for
      cache-rendered prefixes (with provider-specific ``cache_control``
      markers), absent when no system content was provided. Captured via
      the adapter's ``trace_hook`` ``before_call`` event; sourced from
      ``prep_res["system_blocks"]`` when prep built one, else
      ``prep_res["system"]``.
    - 2.5.0 on disk: large string leaves may be replaced by
      ``{"$pflow_blob": hash}`` refs with plaintext bodies in the top-level
      ``blobs`` trailer. All content readers resolve these through
      ``pflow.core.trace_io.load_trace_file`` before consumers inspect events.
    - 2.5.0 LLM events: the rendered prompt/effective system live in
      canonical ``llm_prompt`` / ``llm_system`` fields. Redundant LLM copies
      are stripped from ``node_output`` / ``template_resolutions`` and
      ``node_params.prompt``; ``node_params.system`` stays as the configured
      system line for reports.

    Consumer rule: gate on ``format_version.startswith("2.")``. Old 2.x
    traces still render; current readers are updated together for newer
    non-additive-but-compatible shape changes.
    """

    def __init__(
        self,
        workflow_name: str = "workflow",
        *,
        workflow_path: str | None = None,
    ):
        """Initialize the trace collector.

        Args:
            workflow_name: Name of the workflow being traced (display label;
                used for the trace filename and the saved trace's
                ``workflow_name`` field).
            workflow_path: Canonical path identifier for the workflow (Task
                159 trace 2.1.0). For file-based runs, the resolved file
                path. For inline runs, the synthetic
                ``"ir-hash:<32-char-md5>"`` from
                ``execution/runner._synthesize_inline_workflow_id`` —
                symmetric with how ``MemoizationCache.workflow_path``
                already scopes inline-run rows. Defaults to ``None`` so
                existing test fixtures continue to construct without
                changes; production paths set it from
                ``shared["_pflow_workflow_file"]`` / inline-id synthesis.
                The saved trace JSON always emits ``workflow_path``
                unconditionally (``null`` when not set).
        """
        self.workflow_name = workflow_name
        self.workflow_path = workflow_path
        self.execution_id = str(uuid.uuid4())
        self.start_time = datetime.now()
        self.events: list[dict[str, Any]] = []
        self.llm_prompts: dict[str, str] = {}  # populated by trace_hook fired from the adapter; keyed by node_id
        # 2.2.0: effective system content (cache-rendered prefix or plain
        # system string) captured by the same trace_hook on before_call.
        # ``None``/missing system params produce no entry.
        self.llm_systems: dict[str, str | list[dict[str, Any]]] = {}
        self.json_output: dict[str, Any] | None = None  # Store final JSON output if generated
        self.execution_warnings: list[dict[str, Any]] | None = None  # Runtime warnings
        # 2.4.0: the ``--only`` target this run executed (full path if dotted),
        # or ``None`` for a full run. The engine stamps it at run start
        # (engine.run). Only the ROOT collector's value is saved — children
        # embed as ``sub_workflow_events`` and are never written standalone.
        # A full run writes ``null``; an ``--only`` run writes the target name,
        # which excludes the trace as a snapshot source (it records only the
        # target, not a coherent full-run upstream).
        self.only_node: str | None = None

    def record_node_execution(
        self,
        node_id: str,
        node_type: str,
        duration_ms: float,
        success: bool,
        error: Optional[str] = None,
        node_params: Optional[dict[str, Any]] = None,
        template_resolutions: Optional[dict[str, Any]] = None,
        node_output: Optional[dict[str, Any]] = None,
        mutations: Optional[dict[str, list[str]]] = None,
        batch_items: Optional[list[dict[str, Any]]] = None,
        sub_workflow_events: Optional[list[dict[str, Any]]] = None,
        cached: bool = False,
    ) -> None:
        """Record detailed node execution data.

        Args:
            node_id: Unique identifier for the node
            node_type: Type/class name of the node
            duration_ms: Execution duration in milliseconds
            success: Whether the node executed successfully
            error: Error message if execution failed
            node_params: Original node parameters (before template resolution)
            template_resolutions: Template variables resolved during execution
            node_output: This node's output from the shared store (namespaced)
            mutations: Key-level changes to shared store (added/removed/modified)
            batch_items: Per-item trace events for batch nodes
            sub_workflow_events: Child workflow trace events for nested workflows
            cached: Whether this node used cached results (skipped execution)
        """
        event: dict[str, Any] = {
            "node_id": node_id,
            "node_type": node_type,
            "duration_ms": round(duration_ms, 2),
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }

        if cached:
            event["cached"] = True
        if error:
            event["error"] = error
        if node_params:
            event["node_params"] = self._sanitize_for_json(node_params)
        if template_resolutions:
            event["template_resolutions"] = self._sanitize_for_json(template_resolutions)
        if node_output:
            event["node_output"] = self._sanitize_for_json(node_output)
        if mutations:
            event["mutations"] = mutations
        if batch_items:
            event["batch_items"] = self._sanitize_batch_items(batch_items)
        if sub_workflow_events:
            event["sub_workflow_events"] = sub_workflow_events  # Already sanitized by child collector

        # Add LLM-specific data if present
        self._add_llm_data(event, node_id, node_output or {})
        if is_llm_node_type(node_type):
            _strip_redundant_llm_trace_fields(event)

        self.events.append(event)

    @staticmethod
    def aggregate_llm_usage_with_retries(llm_usage: dict[str, Any]) -> dict[str, Any]:
        """Aggregate tokens/cost/turns from main llm_usage + retries array.

        When llm_usage has a 'retries' field (schema retry attempts from claude-code node),
        returns a new dict with summed tokens/cost/turns. Otherwise returns the input unchanged.

        Args:
            llm_usage: Raw llm_usage dict (may contain retries[] field)

        Returns:
            Aggregated dict (if retries present) or original dict (if no retries)
        """
        retries = llm_usage.get("retries", [])
        if not retries:
            return llm_usage

        # Create aggregated llm_usage with summed tokens/cost/turns
        aggregated = dict(llm_usage)  # Shallow copy

        # Sum input/output tokens (None-safe: use `or 0` to coerce explicit None to 0)
        aggregated["input_tokens"] = llm_usage.get("input_tokens") or 0
        aggregated["output_tokens"] = llm_usage.get("output_tokens") or 0

        # Sum cache tokens (None-safe)
        for cache_key in ["cache_creation_input_tokens", "cache_read_input_tokens"]:
            aggregated[cache_key] = llm_usage.get(cache_key) or 0

        # Sum cost (handle None for models without pricing like Ollama)
        # If all costs are None, result is None. If any cost is numeric, sum only numeric ones.
        main_cost = llm_usage.get("cost_usd")
        retry_costs = [r.get("cost_usd") for r in retries if r.get("cost_usd") is not None]
        if main_cost is not None or retry_costs:
            aggregated["cost_usd"] = (main_cost or 0) + sum(retry_costs)
        else:
            aggregated["cost_usd"] = None

        # Sum turns (None-safe: .get() with default only handles absent keys, not explicit None)
        # Use `or 0` to coerce None to 0 for aggregation
        aggregated["num_turns"] = llm_usage.get("num_turns") or 0
        for retry in retries:
            aggregated["num_turns"] += retry.get("num_turns") or 0

        # Aggregate retry contributions to tokens (None-safe)
        for retry in retries:
            aggregated["input_tokens"] += retry.get("input_tokens") or 0
            aggregated["output_tokens"] += retry.get("output_tokens") or 0
            for cache_key in ["cache_creation_input_tokens", "cache_read_input_tokens"]:
                aggregated[cache_key] += retry.get(cache_key) or 0

        # Recompute total_tokens after aggregation (was stale from main-only shallow copy)
        aggregated["total_tokens"] = aggregated["input_tokens"] + aggregated["output_tokens"]

        return aggregated

    def _add_llm_data(
        self,
        event: dict[str, Any],
        node_id: str,
        node_output: dict[str, Any],
    ) -> None:
        """Add LLM usage and response data to the event if present.

        Aggregates tokens/cost across main usage + retries for claude-code schema retry.

        Args:
            event: Event dictionary to update
            node_id: Node ID for prompt lookup
            node_output: This node's output from the shared store
        """
        # Look for llm_usage directly in node_output
        llm_usage = node_output.get("llm_usage") if isinstance(node_output, dict) else None
        if isinstance(llm_usage, dict):
            # Aggregate tokens/cost across main usage + retries (if present)
            event["llm_call"] = self.aggregate_llm_usage_with_retries(llm_usage)

        # Look for prompt via the trace_hook capture first, then node_output.
        # The LLM adapter calls collector.get_trace_hook(node_id) to get a
        # writer that populates self.llm_prompts[node_id] on before_call.
        # Sub-workflow LLM events end up in their own collector's
        # llm_prompts dict (each engine.run installs its own collector into
        # shared["__trace_collector__"]); the parent's WorkflowExecutor event
        # then aggregates child events via sub_workflow_events.
        # LLMNode.post writes "prompt" to shared; the trace_hook capture wins
        # for normal non-batch calls, while the node_output fallback covers
        # batch workers and legacy/external callers.
        prompt = self.llm_prompts.get(node_id)
        if not prompt and isinstance(node_output, dict):
            prompt = node_output.get("prompt")
        if isinstance(prompt, str):
            event["llm_prompt"] = prompt  # No truncation

        # 2.2.0: surface the effective system content. Lookup mirrors prompt:
        # trace_hook capture wins; node_output fallback covers parallel batch
        # workers (LLMNode.post writes shared["system"] per item).
        system = self.llm_systems.get(node_id)
        if system is None and isinstance(node_output, dict):
            candidate = node_output.get("system")
            if isinstance(candidate, (str, list)):
                system = candidate
        if system is not None:
            event["llm_system"] = system  # No truncation

        # Look for response in node_output
        response = node_output.get("response") if isinstance(node_output, dict) else None
        if isinstance(response, str):
            event["llm_response"] = response  # No truncation

    def collect_llm_calls(self) -> list[dict[str, Any]]:
        """Walk event tree recursively and return flat list of llm_call dicts.

        Collects from top-level events, batch_items, and sub_workflow_events.

        Returns:
            Flat list of llm_call dicts (each containing model, tokens, cost, etc.)
        """
        return self._collect_llm_calls_from_events(self.events)

    def _collect_llm_calls_from_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Recursively collect llm_call dicts from tree-structured events.

        Skips cached events at every tier (top-level, batch_items,
        sub_workflow_events) via
        ``TraceTree.iter_llm_leaves(descend_cached_subtrees=False)``. This is
        more aggressive than the pre-1fabde31 hand-rolled walker, which only
        filtered top-level cached events. The new behavior is correct for
        cost-summary purposes: cached items contributed $0 this run regardless
        of nesting tier.
        """
        from pflow.core.trace_tree import TraceTree

        tree = TraceTree(events=tuple(events), format_version=TRACE_FORMAT_VERSION)
        calls: list[dict[str, Any]] = []
        for leaf in tree.iter_llm_leaves(descend_cached_subtrees=False):
            if leaf.llm_call is None:
                continue
            call = dict(leaf.llm_call)
            call["node_id"] = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id
            call["duration_ms"] = leaf.event.get("duration_ms", 0)
            if leaf.tier == "batch_item":
                call["batch_item_index"] = leaf.event.get("index", 0)
            calls.append(call)
        return calls

    def _sanitize_for_json(self, data: Any) -> Any:
        """Make data JSON-serializable. No truncation — just hygiene.

        Filters internal keys (__ prefixed except __metrics__)
        and replaces binary data with a placeholder.

        Args:
            data: Data to sanitize

        Returns:
            Sanitized data suitable for JSON serialization
        """
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                # Skip internal keys
                if isinstance(key, str) and key.startswith("__") and key not in ("__metrics__",):
                    continue
                if key in ("__trace_collector__", "_debug_context", "_batch_trace"):
                    continue
                result[key] = self._sanitize_for_json(value)
            return result
        elif isinstance(data, bytes):
            return f"<binary data: {len(data)} bytes>"
        elif isinstance(data, (list, tuple)):
            return [self._sanitize_for_json(item) for item in data]
        else:
            return data

    def _sanitize_batch_items(self, batch_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sanitize batch item trace data. Items are built by _capture_item_trace
        which doesn't sanitize node_output — we do it here at the collector level."""
        sanitized = []
        for item in batch_items:
            clean_item = dict(item)
            if "node_output" in clean_item:
                clean_item["node_output"] = self._sanitize_for_json(clean_item["node_output"])
            if "template_resolutions" in clean_item:
                clean_item["template_resolutions"] = self._sanitize_for_json(clean_item["template_resolutions"])
            # Recurse into nested events (sub-workflow batch items)
            if "events" in clean_item:
                # Child events from sub-workflow collectors are already sanitized,
                # but events from _capture_item_trace may not be
                clean_item["events"] = [
                    self._sanitize_for_json(e) if isinstance(e, dict) else e for e in clean_item["events"]
                ]
            sanitized.append(clean_item)
        return sanitized

    def set_json_output(self, json_output: dict[str, Any]) -> None:
        """Store the JSON output that was sent to stdout.

        Args:
            json_output: The JSON data that was output to the user
        """
        self.json_output = json_output

    def set_warnings(self, warnings: list[Diagnostic] | list[dict[str, Any]]) -> None:
        """Store warning diagnostics from execution.

        Args:
            warnings: List of warning diagnostics or legacy warning dicts
        """
        if not warnings:
            self.execution_warnings = None
            return
        self.execution_warnings = [
            warning.to_display_dict() if isinstance(warning, Diagnostic) else warning for warning in warnings
        ]

    def mark_last_event_failed(self, node_id: str, *, error: str) -> None:
        """Flip the most recent event for node_id to failed.

        Used by the engine when a node's failure is detected AFTER its trace
        event has been recorded — specifically, routing failures on custom
        non-error actions (GH #250). Without this, the trace event says
        success=True while __failures__[node_id] says the node failed.

        No-op if no event for node_id exists. Today the only caller is
        _handle_no_successor, which runs AFTER step 16 trace recording in
        the engine walk — so the no-op path is unreachable under current
        engine semantics. The guard is defensive for future engine paths
        that might call this before trace recording.

        `category` is intentionally NOT accepted: trace events don't carry
        a category field today; the canonical category lives in
        __failures__[node_id]["category"]. A future migration that upgrades
        `success: bool` → `status: enum` would read category from
        __failures__ at migration time.

        The flipped event retains its original `node_output` from the
        successful execution (captured at step 16 before __failures__
        archival). This is intentional: the node DID produce output, and
        then routing failed. Per-node report files show both the output
        and the failed status — this is semantically correct.
        """
        for event in reversed(self.events):
            if event.get("node_id") == node_id:
                event["success"] = False
                event["error"] = error
                return

    def _determine_trace_status(self, final_events: dict[str, dict[str, Any]] | None = None) -> str:
        """Determine status from per-node final state and warnings.

        Uses last-event-per-node_id (via ``final_events_by_node``) so loop
        recovery that ends in success is reported as success — see GH #240.

        Args:
            final_events: optional pre-computed dict. ``save_to_file`` already
                computes this to derive ``failed_node_ids`` and passes it in
                to avoid a second pass over ``self.events``. Callers that
                don't need the dict elsewhere can omit the argument.

        Returns:
            Status string: "success", "degraded", or "failed"
        """
        if final_events is None:
            final_events = final_events_by_node(self.events)
        if any(not e.get("success", True) for e in final_events.values()):
            return "failed"
        if self.execution_warnings and any(
            self._warning_changes_status(warning) for warning in self.execution_warnings
        ):
            return "degraded"
        return "success"

    @staticmethod
    def _warning_changes_status(warning: dict[str, Any]) -> bool:
        """Return whether a warning should mark the trace as degraded.

        Blacklist (not whitelist) is intentional: unknown sources default to
        degrading, so new source types are fail-closed rather than silently
        ignored.  Only parser and validator warnings are excluded — they
        indicate input quality issues, not runtime degradation.
        """
        return warning.get("source") not in {"parser", "validator"}

    def _collect_llm_summary(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Recursively collect LLM call data from tree-structured events.

        Cached events are filtered at every tier via
        ``TraceTree.iter_llm_leaves(descend_cached_subtrees=False)`` — top-level
        cached events AND cached batch_items / sub_workflow_events are excluded
        from the summary. Pre-1fabde31 the hand-rolled walker only filtered
        top-level cached events; the new behavior is correct because cached
        items paid $0 this run regardless of nesting tier.
        """
        from pflow.core.trace_tree import TraceTree

        agg = _LLMSummaryAccumulator()
        tree = TraceTree(events=tuple(events), format_version=TRACE_FORMAT_VERSION)
        for leaf in tree.iter_llm_leaves(descend_cached_subtrees=False):
            if leaf.llm_call is not None:
                agg.add_leaf(dict(leaf.llm_call))
        return agg.as_dict()

    def save_to_file(self) -> Path:
        """Save trace to JSON file in ~/.pflow/debug/.

        Returns:
            Path to the saved trace file
        """
        # Create directory if it doesn't exist
        trace_dir = Path.home() / ".pflow" / "debug"
        trace_dir.mkdir(parents=True, exist_ok=True)

        # Microsecond granularity (issue #443): a full run followed within the
        # SAME second by an ``--only`` run would otherwise write the same filename,
        # and the ``--only`` trace (excluded as a snapshot source) would overwrite
        # the full-run snapshot — breaking every subsequent ``--only`` until the
        # next full run. ``%f`` keeps the two filenames distinct; ordering still
        # sorts correctly (``_trace_recency_key`` parses this timestamp) and the
        # autoload glob keys on the hash prefix, not the timestamp.
        # Caveat (PR #459 S5): ``%f`` is unique within ONE process, but two
        # concurrent processes running the SAME workflow could in principle write
        # the same microsecond filename and have one overwrite the other.
        # Vanishingly unlikely under normal (sequential) agent use; a high-throughput
        # orchestrator sharing ~/.pflow/debug should not assume per-write uniqueness.
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        filename = format_trace_filename(self.workflow_path, self.workflow_name, timestamp)
        filepath = trace_dir / filename

        # Calculate total duration
        duration_ms = (datetime.now() - self.start_time).total_seconds() * 1000

        # Per-node final state — drives BOTH final_status AND failed_node_ids.
        # Loop recovery: last event per node_id wins (visit 2 success overwrites
        # visit 1 failure) so nodes_failed reflects UNIQUE failed nodes, not
        # total failed invocations. nodes_executed still counts per-visit.
        # Computed once and passed to _determine_trace_status so the events
        # list is walked once per save. See GH #240.
        final_events = final_events_by_node(self.events)
        final_status = self._determine_trace_status(final_events)
        failed_node_ids = sorted(nid for nid, e in final_events.items() if not e.get("success", True))

        # Prepare trace data with format version
        trace_data: dict[str, Any] = {
            "format_version": TRACE_FORMAT_VERSION,
            "execution_id": self.execution_id,
            "workflow_name": self.workflow_name,
            # Task 159 trace 2.1.0: emitted unconditionally. None when the
            # caller didn't set it (test fixtures, legacy harnesses); the
            # production paths (``execution/runner.py``,
            # ``runtime/workflow_executor.py``) always provide a value.
            "workflow_path": self.workflow_path,
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now().isoformat(),
            "duration_ms": round(duration_ms, 2),
            "final_status": final_status,
            # 2.4.0: ``None`` for a full run; the ``--only`` target name for an
            # ``--only`` run. The snapshot loader (``_iter_workflow_traces``)
            # excludes any trace where this is non-null — an ``--only`` run is
            # not a coherent full-run snapshot.
            "only_node": self.only_node,
            "nodes_executed": len(self.events),
            "nodes_failed": len(failed_node_ids),
            "failed_node_ids": failed_node_ids,
            "nodes": self.events,
        }

        # Add LLM summary by recursively scanning tree-structured events
        llm_summary = self._collect_llm_summary(self.events)
        if llm_summary["total_calls"] > 0:
            trace_data["llm_summary"] = llm_summary

        # Add runtime warnings (e.g., API warnings, batch degradation)
        if self.execution_warnings:
            trace_data["warnings"] = self.execution_warnings

        # Add JSON output if it was generated (e.g., when --output-format json was used)
        if self.json_output is not None:
            trace_data["json_output"] = self.json_output

        # Write to file with proper formatting
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(intern_blobs(trace_data), f, indent=2, default=str)

        return filepath

    def get_trace_hook(self, node_id: str) -> Callable[[dict[str, Any]], None]:
        """Return a callable that the LLM adapter invokes around its API call.

        The new pflow-owned LiteLLM adapter (`pflow.core.llm_client.complete`)
        accepts a `trace_hook` parameter. When a workflow trace is active, the
        LLMNode passes `collector.get_trace_hook(node_id)` to the adapter.
        On `before_call` the hook captures the rendered prompt into
        `self.llm_prompts[node_id]` — same destination the legacy
        ``llm.get_model`` monkey-patch wrote to before Task 158 Phase A.6
        replaced it with this hook. Same downstream consumer
        (`_attach_llm_call_to_event` at line 168 of this file).
        """

        def hook(event: dict[str, Any]) -> None:
            if event.get("event") == "before_call":
                prompt = event.get("prompt")
                if isinstance(prompt, str):
                    self.llm_prompts[node_id] = prompt
                # 2.2.0: capture the effective system content (cache-rendered
                # list[dict] when prep built one, else plain string). ``None``
                # — i.e. caller passed no system — produces no entry, so the
                # event omits ``llm_system`` rather than carrying null.
                system = event.get("system")
                if isinstance(system, (str, list)):
                    self.llm_systems[node_id] = system

        return hook
