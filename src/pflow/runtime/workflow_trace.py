"""Detailed trace collection for workflow debugging."""

import contextlib
import hashlib
import json
import logging
import re
import threading
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from pflow.core.diagnostic import Diagnostic, warning_degrades_status
from pflow.core.exceptions import OnlySnapshotMissingError
from pflow.core.node_type_display import is_llm_node_type
from pflow.core.trace_io import (
    RESERVED_LINE_KEYS,
    TRACE_JSONL_MARKER,
    _rebuild_event_tree,
    intern_event_leaves,
    load_trace_file,
)
from pflow.core.validation_utils import VALIDATION_PLACEHOLDER

logger = logging.getLogger(__name__)

# Trace format version. 2.5.0 introduced large-string-leaf interning (now written as inline
# ``{"$pflow_blob": hash}`` refs with the bodies in inline ``blob`` lines per Task 172 — originally a
# top-level ``blobs`` map) and canonicalized LLM prompt/system into ``llm_prompt``/``llm_system`` by
# removing redundant LLM copies from node_output/template_resolutions/node_params. 2.6.0 (Task 164,
# additive) adds ``resumed_from`` to the meta line (attempt-chain lineage) and ``restored: true`` on
# cached-status events a resumed run re-recorded from its source trace. Consumers gate on
# ``startswith("2.")``; old traces remain readable.
TRACE_FORMAT_VERSION = "2.6.0"


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


def _lock_trace_handle(handle: TextIO) -> None:
    """Task 173: take a best-effort advisory lock on the open trace handle, held for the run's lifetime.

    The live-overlay server probes this lock to tell a RUNNING run from a CRASHED one EXACTLY — the kernel
    releases it on ANY process exit (clean finish, crash, ``kill -9``), so "lock held" == "the run's process
    is alive". The lock rides the already-open streaming handle (acquired here, released when the handle
    closes in ``_close_stream`` or the process dies). Unix-only (``fcntl``); a no-op on Windows or any
    failure (e.g. a filesystem without ``flock``) — liveness then degrades to the consumer's fallback, and
    the run is NEVER affected (trace persistence is a side-channel)."""
    try:
        import fcntl
    except ImportError:
        return  # no fcntl (Windows) — degrade to the consumer's heuristic
    # Suppress ANY failure (lock unavailable on this FS, or a wrapped/non-fd handle e.g. the I/O-fault
    # test's stub) — same best-effort posture as _close_stream; never let it touch the run.
    with contextlib.suppress(Exception):
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


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
    (input-quality, not runtime data loss; mirrors ``warning_degrades_status``). An
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
    return all(not warning_degrades_status(warning) for warning in warnings)


def _unrecovered_failed_node_ids(
    final_events: dict[str, dict[str, Any]],
    execution_warnings: list[dict[str, Any]] | None,
) -> set[str]:
    failed_node_ids = {node_id for node_id, event in final_events.items() if event.get("status") == "failed"}
    recovered_node_ids: set[str] = set()
    for warning in execution_warnings or []:
        node_id = warning.get("node_id") if isinstance(warning, dict) else None
        if not isinstance(node_id, str):
            continue
        if warning.get("type") == "on_error_recovery":
            recovered_node_ids.add(node_id)
        if warning.get("type") == "api_warning" and warning.get("recovered") is True:
            recovered_node_ids.add(node_id)
    return failed_node_ids - recovered_node_ids


def _node_status(success: bool, cached: bool) -> str:
    """Per-node outcome enum for a trace event: ``"success" | "cached" | "failed"``.

    The single ``success``/``cached`` → ``status`` mapping site (Task 172): the
    engine and instrumentation keep speaking booleans into ``record_node_execution``;
    only the recorded event shape is the enum. ``cached`` wins over ``failed``
    because a cached node always succeeded *this* run (error results are never
    cached); a routing dead-end detected AFTER recording flips the event to
    ``"failed"`` via ``mark_last_event_failed``, so the old ``(cached, !success)``
    ambiguity collapses into one field. ``degraded`` is intentionally absent — it
    is a RUN outcome (``final_status``), not a per-node one.
    """
    if cached:
        return "cached"
    return "success" if success else "failed"


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
        # the cache-inclusive total (every producer emits inclusive input_tokens;
        # see core/llm_usage.py); the cache tiers are emitted as a subset breakdown.
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


@dataclass
class _HostFrame:
    """Correlation reserved at sub-workflow descent so a host span's ``seq`` precedes its children's.

    A sub-workflow host's completion event is recorded AFTER its children (engine step 16), but
    reconstruct needs ``parent.seq < child.seq`` (DFS pre-order). So the run-scoped collector reserves
    the host's ``seq`` (and captures its own ``parent_id``/``ancestor_path``) at descent, pushes this
    frame, and the host event reuses it at completion. ``batch_index`` is always ``None`` in v1 (only
    sub-workflow descents push frames); kept for forward-compat + exact ``ancestor_path`` shape parity
    with ``AncestorStep`` / ``sameRef`` (web/src/graph/remap.ts).
    """

    seq: int
    node_id: str
    parent_id: int | None
    ancestor_path: list[dict[str, Any]]
    batch_index: int | None = None


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
    - On disk: large string leaves may be replaced by ``{"$pflow_blob": hash}``
      refs with plaintext bodies in inline-first-occurrence ``blob`` lines
      (Task 172; originally a top-level ``blobs`` trailer). All content readers
      resolve these through ``pflow.core.trace_io.load_trace_file`` before
      consumers inspect events.
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
        is_run_scoped: bool = False,
        stream_to_disk: bool = False,
        content_hash: str | None = None,
        execution_id: str | None = None,
        resumed_from: str | None = None,
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
            is_run_scoped: Whether this is THE single run-scoped collector for the
                whole execution (Task 172). The runner/CLI constructs the root with
                ``True``; per-sub-workflow buffer collectors (``WorkflowExecutor``)
                keep the ``False`` default. Run-scoped collectors expose the nested
                ``tree()`` via ``_rebuild_event_tree``; buffer collectors stay
                tree-shaped.
            stream_to_disk: Whether the run-scoped collector flushes one JSONL line
                per node AS the run executes (Task 172 step 3 — so a live overlay can
                tail it). The runner sets this from ``RunnerConfig.trace_enabled``: the
                CLI persists traces (``True``); the MCP path reads cost from the
                in-memory collector and never persists (``False``); ``--no-trace`` is
                ``False``. Only meaningful when ``is_run_scoped`` (buffer collectors
                never stream). Default ``False`` so bare-constructed collectors don't
                write files. A second, test-only gate lives in ``tests/conftest.py``
                (``_open_stream`` is no-op'd unless the test is marked ``trace_files``).
            content_hash: Task 173 replay version fingerprint — the
                ``workflow_content_hash`` of the resolved IR (``canonical_ir_digest``
                with source-line provenance stripped, so a comment/whitespace-only
                edit isn't flagged stale), stamped into the ``meta`` line. At replay
                the server compares it to the current file's digest to flag a stale
                (different-version) run.
                Defaults to ``None`` so the per-sub-workflow buffer collector and
                all test fixtures construct unchanged; an old trace (or a run
                that didn't supply it) simply has no fingerprint → "can't verify".
            execution_id: Force the run's id instead of minting a fresh UUID (Task
                175). The ``pflow ui`` ▶ launch mints the id server-side and threads
                it here (via ``RunnerConfig`` ← ``PFLOW_EXECUTION_ID``) so the browser
                can PIN the overlay to the exact run it just spawned — otherwise the
                detached child mints its own id and the form can only follow-newest
                (which reverts to an older still-live run when the new one finishes).
                Defaults to ``None`` → mint a UUID (every other run path).
            resumed_from: Task 164 attempt-chain lineage — the SOURCE run's
                ``execution_id`` when this run is a resume of a prior failed
                attempt; ``None`` for every normal run. Pure lineage, never a
                data dependency (Decision 6: an attempt trace is self-contained
                via re-recorded ``restored`` events). Rides the ``meta`` line
                (``_meta_fields``), so it MUST be set at construction — before
                ``start_streaming`` flushes the meta line.
        """
        self.workflow_name = workflow_name
        self.workflow_path = workflow_path
        self.content_hash = content_hash
        self.resumed_from = resumed_from
        self.is_run_scoped = is_run_scoped
        self.execution_id = execution_id or str(uuid.uuid4())
        self.start_time = datetime.now()
        self.events: list[dict[str, Any]] = []
        # Task 172 step 3: per-event streaming state (run-scoped + stream_to_disk only). The stream opens
        # lazily on the first flush (writing the meta line), one event line is appended as each node
        # records, and finalize() writes the run.complete trailer + closes. _declared_blobs tracks
        # first-occurrence interning so a blob is written once, before its first (backward-only) ref.
        self._stream_to_disk = stream_to_disk and is_run_scoped
        self._stream: TextIO | None = None
        self._stream_path: Path | None = None
        self._declared_blobs: set[str] = set()
        self._finalized = False
        # First disk I/O fault disables streaming for the rest of the run: the streamed file is a
        # best-effort tail of the in-memory trace (the source of truth), so a write fault must never
        # propagate into execution. Keeps trace persistence a pure side-channel.
        self._stream_failed = False
        # Task 172: emit-time correlation state (run-scoped only). Children record
        # flat into one run collector; ``seq`` is reserved at descent so a host span
        # precedes its children in DFS pre-order. Assigned only on the owner thread
        # (no lock) — workers route to buffer collectors instead, never here.
        self._seq_counter: int = 0
        self._host_stack: list[_HostFrame] = []
        self._owner_thread: int | None = threading.get_ident() if is_run_scoped else None
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
        # Task 175: the run's resolved top-level input values, known at run start
        # (the values seeded into the shared store before any node executes). The
        # Runner stamps this on the ROOT collector BEFORE ``engine.run()`` so the
        # eager ``meta`` line carries it. Stored RAW on disk (same exposure class
        # as ``node_params``); redaction happens on read. ``None`` until stamped,
        # ``{}`` for a no-input workflow.
        self.inputs: dict[str, Any] | None = None
        # Task 125: terminal gate outcome for the trailer. _determine_trace_status
        # derives from node events only, and a gated stop leaves NO failed node
        # event (a denied node never ran; a non-interactive escalation's node
        # succeeded) — without this channel a gate-stopped run's own trace would
        # read "success". "denied" → trailer "denied"; "failed" → trailer
        # "failed". Set by record_gate AND by the engine's gate-exception
        # re-raise arm (which covers gates fired under buffered child collectors).
        self.gate_outcome: str | None = None

    def record_gate(
        self,
        node_id: str,
        *,
        phase: str,
        gate_kind: str,
        request: Any = None,
        resolution: str | None = None,
        resolved_via: str | None = None,
        decision: dict[str, Any] | None = None,
    ) -> None:
        """Task 125: stream one ``gate`` line (``phase="pause"`` carrying the
        GateRequest payload, or ``phase="resolution"`` carrying the verdict).

        DISK-ONLY, exactly like ``node.start``: never appended to ``self.events``
        — a gate line in the event stream would become the node's "final event"
        in ``final_events_by_node`` and (having no ``node_output``) make
        ``seed_snapshot_into_shared`` silently skip seeding that node for
        ``--only``. The reconstruct reader ignores the kind
        (``trace_io._partition_trace_lines``); Task 171 reads gate lines with
        its own explicit reader.
        """
        if resolution == "denied":
            self.gate_outcome = "denied"
        elif resolution in ("non_interactive", "error"):
            self.gate_outcome = "failed"
        self._assert_owner_thread()
        self._open_stream()
        line: dict[str, Any] = {"kind": "gate", "node_id": node_id, "phase": phase, "gate_kind": gate_kind}
        if request is not None:
            line["request"] = request.to_dict()
        if resolution is not None:
            line["resolution"] = resolution
        if resolved_via is not None:
            line["resolved_via"] = resolved_via
        if decision is not None:
            line["decision"] = decision
        self._flush_line(line)

    def record_node_execution(
        self,
        node_id: str,
        node_type: str,
        duration_ms: float,
        success: bool,
        error: str | None = None,
        node_params: dict[str, Any] | None = None,
        template_resolutions: dict[str, Any] | None = None,
        node_output: dict[str, Any] | None = None,
        mutations: dict[str, list[str]] | None = None,
        batch_items: list[dict[str, Any]] | None = None,
        sub_workflow_events: list[dict[str, Any]] | None = None,
        cached: bool = False,
        restored: bool = False,
        frame: _HostFrame | None = None,
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
            restored: Task 164 (Decision 6) — this event re-records an upstream
                node's final event from a resumed run's SOURCE trace, so the
                attempt trace is self-contained (resume-of-a-resume and later
                ``--only`` runs seed from it alone). Always passed with
                ``cached=True``: ``status: "cached"`` keeps every cost/UI
                consumer correct with zero change; ``restored: true`` is the
                honest marker on top. Excluded from ``nodes_executed``.
        """
        event: dict[str, Any] = {
            "node_id": node_id,
            "node_type": node_type,
            "duration_ms": round(duration_ms, 2),
            "status": _node_status(success, cached),
            "timestamp": datetime.now().isoformat(),
        }
        if restored:
            event["restored"] = True

        if error:
            event["error"] = error
        if node_params:
            event["node_params"] = self._sanitize_for_json(node_params)
        if template_resolutions:
            event["template_resolutions"] = self._sanitize_for_json(template_resolutions)
        # Restored events stamp on ``is not None`` (not truthiness): an upstream node whose
        # real output was ``{}`` must survive re-record so a SECOND resume seeds ``{}`` rather
        # than absent — a downstream coalesce distinguishes those (Task 164 §C step 4).
        if node_output or (restored and node_output is not None):
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

        self._stamp_correlation(event, node_id, frame)

        self.events.append(event)
        # Task 172 step 3: stream this event as a JSONL line the instant it's recorded (run-scoped +
        # stream_to_disk only; a no-op otherwise, and under the pytest gate). Buffer collectors never
        # stream — their children embed and the whole nested tree is written at save_to_file.
        self._flush_event(event)

    def _stamp_correlation(self, event: dict[str, Any], node_id: str, frame: _HostFrame | None) -> None:
        """Task 172: stamp emit-time correlation on the run-scoped collector.

        A ``frame`` (sub-workflow host) reuses its reserved seq/parent_id/
        ancestor_path; every other record — leaf, cache hit
        (``handle_cached_execution``), api-warning (``handle_api_warning``) —
        takes the next seq and nests under the current host
        (``_host_stack[-1]``) or top level. Buffer collectors stamp nothing;
        their children embed as ``sub_workflow_events``.
        """
        if not self.is_run_scoped:
            return
        seq = frame.seq if frame is not None else self._next_seq()
        parent_id = frame.parent_id if frame is not None else (self._host_stack[-1].seq if self._host_stack else None)
        ancestor_path = frame.ancestor_path if frame is not None else self._current_ancestor_path()
        self._check_reserved_collision(event, node_id)
        event |= {
            "id": seq,
            "seq": seq,
            "parent_id": parent_id,
            "run_id": self.execution_id,
            "ancestor_path": ancestor_path,
            "port": None,
        }

    def tree(self) -> list[dict[str, Any]]:
        """Nested event view over the store — the derived projection (Task 172).

        A run-scoped collector holds a FLAT event list (each event carries
        ``id``/``seq``/``parent_id`` once step 2 lands emit-time correlation); the
        nested tree is rebuilt on demand via the disk reader's
        ``_rebuild_event_tree``. Buffer / test collectors (``is_run_scoped=False``)
        hold events that are already tree-shaped (children embedded as
        ``sub_workflow_events``) and carry no correlation keys —
        ``_rebuild_event_tree`` would raise on them — so they return
        ``self.events`` unchanged. Both shapes feed the same ``TraceTree``, so cost
        readers must walk ``tree()`` (not raw ``self.events``) to recurse
        sub-workflow LLM cost. No-op until step 2 flips ``is_run_scoped`` on.
        """
        return _rebuild_event_tree(self.events) if self.is_run_scoped else self.events

    def _top_level_events(self) -> list[dict[str, Any]]:
        """Root events only — those with no enclosing event (Task 172).

        Status / count aggregations (``final_status``, ``failed_node_ids``,
        ``nodes_executed``) key on ``node_id``; on a flat store (step 2) a
        sub-workflow child's ``node_id`` could overwrite a top-level node's, so they
        MUST scope to roots. An event with no ``parent_id`` key is top level —
        which is every event until the store goes flat, so this is a no-op for now.
        """
        return [event for event in self.events if event.get("parent_id") is None]

    @staticmethod
    def _check_reserved_collision(event: dict[str, Any], node_id: str) -> None:
        """Loud guard (Task 172): a producer must never pre-set a reserved correlation key — the writer
        derives them and the reader strips them. ``if/raise`` (not ``assert``) so it survives ``python -O``."""
        collision = RESERVED_LINE_KEYS.intersection(event)
        if collision:
            raise RuntimeError(
                f"trace event {node_id!r} already carries reserved correlation key(s) {sorted(collision)}; "
                "the writer derives these and the reader strips them, so a producer must not pre-set them"
            )

    def _assert_owner_thread(self) -> None:
        """Loud guard for the no-lock ``seq`` rule (Task 172).

        The run collector's ``seq``/host-stack mutate without a lock, valid ONLY because they run on
        one thread (the main thread that created the run-scoped collector). A worker reaching here means
        the routing rule was violated — fail loud, not silently with a non-deterministic ``seq`` gap.
        """
        # `if/raise` (not `assert`) so the no-lock guard still fires under `python -O`.
        if self._owner_thread is not None and threading.get_ident() != self._owner_thread:
            raise RuntimeError(
                "run-scoped collector seq/host-stack methods must run on the owner thread only; "
                "a worker thread must route to a buffer collector (Task 172 no-lock invariant)"
            )

    def _next_seq(self) -> int:
        self._assert_owner_thread()
        seq = self._seq_counter
        self._seq_counter += 1
        return seq

    def _current_ancestor_path(self) -> list[dict[str, Any]]:
        """The ordered host descents enclosing the current point — the overlay graph-join field.

        Mirrors ``NodeId.ancestor_path`` (``[{node_id, batch_index}]``); ``batch_index`` is ``None`` in
        v1 (only sub-workflow descents push frames). Excludes the host being entered — ``descend``
        captures this BEFORE pushing the new frame.
        """
        return [{"node_id": f.node_id, "batch_index": f.batch_index} for f in self._host_stack]

    def descend(self, node_id: str) -> _HostFrame:
        """Enter a sub-workflow host: reserve its ``seq``, push its frame, and (when streaming) emit a
        disk-only ``node.start`` so the overlay lights the host ``running`` as its body executes.

        Captures the host's OWN ``parent_id``/``ancestor_path`` BEFORE pushing, so the host nests under
        its enclosing host (if any) while its children nest under it. The reserved ``seq`` is reused by
        the host's completion event (engine step 16), giving DFS pre-order — and the ``node.start`` shares
        that ``seq``, so the reader's last-wins dedup collapses start→completion (the marker is itself
        dropped by ``_partition_trace_lines``, leaving on-disk ``event`` seqs byte-identical). ``begin_node``
        does the same for leaf nodes; hosts reserve HERE (pre-order) rather than at engine step 8.5.
        Balance with ``ascend``.
        """
        self._assert_owner_thread()
        parent_id = self._host_stack[-1].seq if self._host_stack else None
        ancestor_path = self._current_ancestor_path()
        seq = self._next_seq()
        frame = _HostFrame(seq=seq, node_id=node_id, parent_id=parent_id, ancestor_path=ancestor_path)
        self._host_stack.append(frame)
        if self._stream_to_disk:  # host node.start: disk-only, reuses the frame's seq (Task 173)
            self._emit_node_start(node_id, "WorkflowExecutor", seq, parent_id, ancestor_path)
        return frame

    def ascend(self) -> None:
        """Leave a sub-workflow host (pop its frame). Balanced with ``descend`` via try/finally."""
        self._assert_owner_thread()
        self._host_stack.pop()

    def _emit_node_start(
        self, node_id: str, node_type: str, seq: int, parent_id: int | None, ancestor_path: list[dict[str, Any]]
    ) -> None:
        """Flush a disk-only ``node.start`` running marker — the overlay's in-flight signal (Task 173).

        The SINGLE writer of the ``node.start`` wire shape, shared by ``begin_node`` (leaf nodes, which
        reserve their ``seq`` here) and ``descend`` (sub-workflow hosts, which reuse the host frame's
        ``seq``). DISK-ONLY — never appended to ``self.events``; the reader (``_partition_trace_lines``)
        drops the line, so the node's terminal ``event`` (reusing this ``seq``) is what lands in the
        reconstructed trace and on-disk ``event`` seqs stay byte-identical to a no-``node.start`` run.
        ``intern=False``: a running marker carries no large leaves, so it never needs a ``blob`` line."""
        self._open_stream()
        self._flush_line(
            {
                "kind": "node.start",
                "node_id": node_id,
                "node_type": node_type,
                "status": "running",
                "timestamp": datetime.now().isoformat(),
                "id": seq,
                "seq": seq,
                "parent_id": parent_id,
                "run_id": self.execution_id,
                "ancestor_path": ancestor_path,
                "port": None,
            },
            intern=False,
        )

    def begin_node(self, node_id: str, node_type: str) -> _HostFrame | None:
        """Task 173 (``node.start``): flush a live in-flight marker as a LEAF node BEGINS, and reserve its
        ``seq`` so the node's completion event reuses it.

        The marker is a DISK-ONLY line (``kind: "node.start"``, via ``_emit_node_start``) — NOT appended
        to ``self.events`` and DELIBERATELY IGNORED by the post-hoc reader (``_partition_trace_lines``
        skips it). It exists solely so a live overlay tailing the file can light the in-flight node
        ``running`` before any completion line lands. The terminal ``event`` reuses this frame's ``seq``
        (the caller threads the returned frame into ``record_node_execution``), so on-disk ``event`` seqs
        stay byte-identical to a run without ``node.start`` and the ``tree()``/``reconstruct`` equivalence
        is untouched.

        Run-scoped + ``stream_to_disk`` only (returns ``None`` otherwise). Owner-thread only (``_next_seq``
        asserts). The caller MUST pass the returned frame into the node's completion record on EVERY path
        (success / api-warning / exception) so the reserved ``seq`` is reused, never re-taken. NOT called
        for sub-workflow hosts — they reserve (and emit their own ``node.start``) via ``descend``."""
        if not (self.is_run_scoped and self._stream_to_disk):
            return None
        seq = self._next_seq()  # asserts owner thread
        parent_id = self._host_stack[-1].seq if self._host_stack else None
        ancestor_path = self._current_ancestor_path()
        self._emit_node_start(node_id, node_type, seq, parent_id, ancestor_path)
        return _HostFrame(seq=seq, node_id=node_id, parent_id=parent_id, ancestor_path=ancestor_path)

    # --- Task 172 step 3: per-event streaming to disk -----------------------------------------------

    def _open_stream(self) -> None:
        """Open the streamed trace file and write the ``meta`` line — lazy, idempotent, run-scoped only.

        The SINGLE entry point the pytest gate patches to a no-op
        (``tests/conftest.py::disable_trace_file_writes_by_default``): when patched, ``self._stream``
        stays ``None``, so per-event flush and finalize both short-circuit → zero disk writes for
        non-``trace_files`` tests. Returns early when streaming is disabled (``stream_to_disk=False`` — the
        MCP path / ``--no-trace``), already open, already finalized (never re-open a closed stream), or
        disabled after an I/O fault (``_stream_failed``). An ``open``/``mkdir`` fault disables streaming
        rather than propagating, so a bad ``~/.pflow/debug`` can't fail the run.
        Uses ``self.start_time`` (microsecond-granular) for the filename so the name is stable from the
        first flush and the #443 ``--only``-collision entropy is preserved (separate processes start at
        distinct microseconds)."""
        if self._stream is not None or not self._stream_to_disk or self._finalized or self._stream_failed:
            return
        try:
            trace_dir = Path.home() / ".pflow" / "debug"
            trace_dir.mkdir(parents=True, exist_ok=True)
            timestamp = self.start_time.strftime("%Y%m%d-%H%M%S-%f")
            self._stream_path = trace_dir / format_trace_filename(self.workflow_path, self.workflow_name, timestamp)
            self._stream = open(self._stream_path, "w", encoding="utf-8")  # noqa: SIM115 — closed in finalize()
            _lock_trace_handle(self._stream)  # Task 173: hold the lock for the run's lifetime (overlay liveness)
        except OSError as exc:
            self._disable_streaming(exc)
            return
        # Meta is written WITHOUT interning: its ``pflow_trace`` marker must be the file's first line, and
        # interning could emit a ``blob`` line ahead of it (if a meta field ever exceeds the threshold),
        # hiding the marker and making the trace fall back to whole-file parse → unreadable (Codex #530).
        self._flush_line(self._meta_line(), intern=False)

    def start_streaming(self) -> None:
        """Task 173 (A1 — eager ``meta``): open the streamed trace at run start so the file + its ``meta``
        line exist from t=0. A live overlay can then discover an in-flight run BEFORE the first node
        completes (today the file opens lazily on the first completion, hiding a still-running first node
        — e.g. a 30s LLM call); a crash mid-first-node also leaves a findable (meta-only) file instead of
        nothing. Idempotent and fully gated — a no-op when not run-scoped/streaming, already open,
        finalized, disabled after an I/O fault, or under the pytest ``trace_files`` gate (which patches
        ``_open_stream``). MUST be called AFTER ``only_node`` is stamped so ``meta`` records the correct
        ``--only`` target (issue #443)."""
        self._open_stream()

    def _flush_line(self, line: dict[str, Any], *, intern: bool = True) -> None:
        """Intern the line's large leaves (emitting each first-seen ``blob`` line FIRST, so refs are
        backward-only), write the line, and flush so a live tailer/crash sees a self-consistent prefix.

        ``intern=False`` writes the line verbatim — used for the ``meta`` line so its marker can never be
        preceded by a ``blob`` declaration (which would make the whole trace unreadable).

        The streamed file is a best-effort tail of the in-memory trace: an I/O fault here disables
        streaming (``_disable_streaming``) instead of propagating, so a disk-full / read-only
        ``~/.pflow/debug`` can never turn a successful node into a failure or mask a real node error."""
        if self._stream is None:
            return
        try:
            payload = intern_event_leaves(line, self._declared_blobs, self._emit_blob_line) if intern else line
            self._stream.write(json.dumps(payload, default=str))
            self._stream.write("\n")
            self._stream.flush()
        except OSError as exc:
            self._disable_streaming(exc)

    def _emit_blob_line(self, digest: str, value: str) -> None:
        if self._stream is not None:
            self._stream.write(json.dumps({"kind": "blob", "md5": digest, "value": value}, default=str))
            self._stream.write("\n")

    def _flush_event(self, event: dict[str, Any]) -> None:
        """Stream one ``event`` line (run-scoped + ``stream_to_disk``). Opens the stream lazily on the
        first call. Builds a ``kind``-tagged copy — never mutates ``event`` (the live ``self.events``
        entry stays plain; interning is a disk-only transform). A no-op when streaming is off / gated /
        disabled-after-I/O-fault; never raises into the engine's per-node path (``_open_stream`` and
        ``_flush_line`` isolate every disk fault)."""
        # The shared file handle is main-thread-only (workers route to buffer collectors). The assert
        # stays OUTSIDE the I/O isolation: a worker reaching here is a routing bug that must fail loud,
        # not a tolerable I/O fault (no-op for buffer collectors — owner is None).
        self._assert_owner_thread()
        self._open_stream()
        self._flush_line({**event, "kind": "event"})

    def _meta_line(self) -> dict[str, Any]:
        line: dict[str, Any] = {"kind": "meta", "pflow_trace": TRACE_JSONL_MARKER}
        line.update(self._meta_fields())
        return line

    def _meta_fields(self) -> dict[str, Any]:
        """The run-identity keys (``META_KEYS``), all knowable at run start — the ``meta`` line payload."""
        return {
            "format_version": TRACE_FORMAT_VERSION,
            "execution_id": self.execution_id,
            "workflow_name": self.workflow_name,
            "workflow_path": self.workflow_path,
            "start_time": self.start_time.isoformat(),
            "only_node": self.only_node,
            "content_hash": self.content_hash,
            "inputs": self.inputs,
            "resumed_from": self.resumed_from,
        }

    def _aggregates(self) -> dict[str, Any]:
        """The end-of-run ``run.complete`` payload, scoped to ``_top_level_events()`` (NOT raw
        ``self.events``) so a flat store's sub-workflow child can't overwrite a top-level node's
        status/count. Shared by the streaming ``finalize`` and the buffer-collector whole-file
        ``save_to_file`` so the two writers can never drift on what an aggregate means."""
        duration_ms = (datetime.now() - self.start_time).total_seconds() * 1000
        final_events = final_events_by_node(self._top_level_events())
        final_status = self._determine_trace_status(final_events)
        failed_node_ids = sorted(_unrecovered_failed_node_ids(final_events, self.execution_warnings))
        agg: dict[str, Any] = {
            "end_time": datetime.now().isoformat(),
            "duration_ms": round(duration_ms, 2),
            # The run's id on the run.complete trailer too (it's on the meta line as well) — so a live-overlay
            # consumer tailing only the trailer learns which run finished without re-reading the head (Task 175
            # run callout shows it). Small string; unlike json_output/warnings it's wire-safe.
            "execution_id": self.execution_id,
            "final_status": final_status,
            # Restored events (Task 164: re-recorded from a resume's source trace) did not
            # execute this run — the ONE aggregate their cached status doesn't already fix.
            "nodes_executed": sum(1 for e in self._top_level_events() if not e.get("restored")),
            "nodes_failed": len(failed_node_ids),
            "failed_node_ids": failed_node_ids,
        }
        llm_summary = self._collect_llm_summary(self.tree())
        if llm_summary["total_calls"] > 0:
            agg["llm_summary"] = llm_summary
        if self.execution_warnings:
            agg["warnings"] = self.execution_warnings
        if self.json_output is not None:
            agg["json_output"] = self.json_output
        return agg

    def _disable_streaming(self, exc: OSError) -> None:
        """Give up on disk streaming after the first I/O fault — log once, drop the handle, and never
        reopen (``_stream_failed`` blocks ``_open_stream``). The in-memory trace stays complete (it's the
        source of truth); the file just stops growing. ``_stream_path`` is cleared so ``finalize`` returns
        no path to a partial file. This keeps trace persistence a pure side-channel that can never alter
        execution outcome."""
        logger.warning("trace streaming disabled after I/O error (in-memory trace retained): %s", exc)
        self._stream_failed = True
        self._close_stream()
        self._stream_path = None

    def _close_stream(self) -> None:
        """Close and drop the stream handle — best-effort and idempotent (a no-op once closed)."""
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.close()
            self._stream = None

    def finalize(self) -> Path | None:
        """Close a streamed run: write the ``run.complete`` trailer (its aggregates), flush, and close.

        The run-scoped counterpart of ``save_to_file`` (events were flushed per-node DURING the run; this
        only caps the file). Opens the stream first so a zero-event run still produces ``meta`` +
        ``run.complete``. Idempotent — the CLI calls it from both the text-success path and the ``finally``
        block (``_save_trace_file`` is the guard, this is belt-and-suspenders). Always leaves the stream
        CLOSED: the ``finally`` runs even if computing or writing the trailer raises, so a finalize fault
        can never leak the handle. Returns the trace path, or ``None`` when streaming is off / gated / was
        disabled mid-run by an I/O fault (so the CLI renders no trace line, exactly as before)."""
        if self._finalized:
            return self._stream_path
        self._open_stream()  # BEFORE _finalized: _open_stream guards on it, so the meta line writes first
        self._finalized = True
        if self._stream is None:  # gated off, or disabled mid-run by an I/O fault
            return None
        try:
            self._flush_line({**self._aggregates(), "kind": "run.complete"})
        finally:
            self._close_stream()
        return self._stream_path

    def __del__(self) -> None:
        """Defensively close a still-open stream (no run.complete) so a collector that streamed but was
        never ``finalize()``d doesn't leak its file handle. In production the CLI always finalizes (which
        closes + nulls ``self._stream``), so this only fires for a GC'd test collector that ran a workflow
        without saving. Best-effort and shutdown-safe — ``getattr`` survives partial ``__init__``."""
        stream = getattr(self, "_stream", None)
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.close()

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
        # uncached_input_tokens is summed alongside input_tokens so the aggregated dict
        # keeps the invariant input_tokens == uncached + cache_creation + cache_read for
        # retried claude-code calls (#492). Producers that omit it (and never retry)
        # default to 0.
        aggregated["uncached_input_tokens"] = llm_usage.get("uncached_input_tokens") or 0

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
            aggregated["uncached_input_tokens"] += retry.get("uncached_input_tokens") or 0
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
        # The LLM adapter calls collector.get_trace_hook(node_id) to get a writer that populates
        # self.llm_prompts[node_id] on before_call. On the Task 172 NEW path a sub-workflow REUSES the
        # one run-scoped collector, so child LLM prompts share this dict keyed by BARE node_id. We POP
        # (consume) on read so a captured prompt belongs ONLY to the node execution that triggered the
        # hook: a later node sharing the same node_id — e.g. a parent non-LLM node named like a child
        # LLM node, or a cached same-id parent — finds nothing and can't inherit the child's stale prompt
        # (Codex review of PR #530). Pre-172 each sub-workflow had its own buffer dict so the collision
        # couldn't arise; loops re-fire the hook each visit, so pop is safe across revisits.
        # LLMNode.post writes "prompt" to shared; the trace_hook capture wins for normal non-batch calls,
        # while the node_output fallback covers batch workers and legacy/external callers.
        prompt = self.llm_prompts.pop(node_id, None)
        if not prompt and isinstance(node_output, dict):
            prompt = node_output.get("prompt")
        if isinstance(prompt, str):
            event["llm_prompt"] = prompt  # No truncation

        # 2.2.0: surface the effective system content. Lookup mirrors prompt (pop-on-consume too, same
        # cross-workflow-collision reason): trace_hook capture wins; node_output fallback covers parallel
        # batch workers (LLMNode.post writes shared["system"] per item).
        system = self.llm_systems.pop(node_id, None)
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
        return self._collect_llm_calls_from_events(self.tree())

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

        Scans ALL events (not just top-level): a routing dead-end INSIDE a
        sub-workflow (GH #250) targets a child event whose `parent_id` is
        set, which top-level scoping would miss. The most-recent match is
        unambiguous (it's the just-dead-ended node), so scanning all events
        carries no overwrite risk.

        Streaming (Task 172 step 3): the event's line was already flushed
        (status="success") DURING the run. This is the ONLY post-flush
        correction, so it RE-FLUSHES the corrected line (same id/seq, now
        status="failed"). The two-pass reconstruct dedups by id (last-wins),
        so the corrected line wins on disk → reconstruct(disk) matches the
        mutated tree(). Flush order is immaterial (reconstruct sorts by seq).
        A no-op flush when streaming is off/gated.
        """
        for event in reversed(self.events):
            if event.get("node_id") == node_id:
                event["status"] = "failed"
                event["error"] = error
                self._flush_event(event)  # re-flush the correction (same id/seq) for the open stream
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
        # Task 125: a gate-stopped run leaves no failed node event — the gate
        # outcome channel is the only honest signal (see gate_outcome in __init__).
        if self.gate_outcome == "denied":
            return "denied"
        if self.gate_outcome == "failed":
            return "failed"
        if final_events is None:
            final_events = final_events_by_node(self._top_level_events())
        if not final_events:
            # A run.complete with ZERO node events means nothing executed — the run
            # crashed or was refused before its first step (every workflow has ≥1
            # node; gate stops are already handled above). Reporting "success" would
            # lie to every consumer: the UI run list, resume's status arms, and
            # analyze-cache's status buckets (Task 164 discovery — previously
            # "success", which let a refused resume attempt masquerade as a
            # successful run).
            return "failed"
        execution_warnings = self.execution_warnings or []
        unrecovered_failures = _unrecovered_failed_node_ids(final_events, execution_warnings)
        if unrecovered_failures:
            return "failed"
        if execution_warnings and any(warning_degrades_status(warning) for warning in execution_warnings):
            return "degraded"
        return "success"

    def has_resumable_step(self) -> bool:
        """Whether this run has a failed step to resume from — the failure surface's resume gate (C2).

        A SOUND SUPPRESSOR of the common dead-ends, NOT a full oracle: ``False`` means
        ``load_resume_source`` will DEFINITELY refuse (so the resume hint / JSON
        ``resume_command`` must stay silent), while ``True`` is
        necessary-but-not-sufficient (resume usually works). It answers only the
        loader's STATUS arm on the IN-MEMORY events — ``_determine_trace_status(...) ==
        "failed"`` AND a non-empty unrecovered set — which catches every case the C2
        report named: a zero-step crash (nothing ran), an all-steps-succeed-but-
        declared-output-unbuildable failure (status is then ``success``/``degraded``),
        and a gate-stopped run (``failed`` with no unrecovered step).

        It DELIBERATELY does not replicate the loader's seed-scope guards (lossy-binary,
        undecided-escalation): those can only be evaluated against the disk-only
        gate-resolution lines (``_apply_gate_resolutions``), and replaying that fold in
        memory would FALSE-refuse a resolved escalation — a false negative that would
        hide the hint on a genuinely resumable run (the dangerous direction). So a rare
        lossy-upstream failure may still show a hint that then refuses — an actionable
        refusal, not a dead crash. Computed in memory so it holds on the JSON path,
        which runs BEFORE the trace is finalized.
        """
        final_events = final_events_by_node(self._top_level_events())
        if self._determine_trace_status(final_events) != "failed":
            return False
        return bool(_unrecovered_failed_node_ids(final_events, self.execution_warnings or []))

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

    def save_to_file(self) -> Path | None:
        """Thin alias for :meth:`finalize` — the run-scoped streaming writer is the ONE trace writer (#531).

        Events were streamed per-node during the run; this writes the ``run.complete`` trailer and closes.
        Returns ``None`` when streaming was off/gated (``stream_to_disk=False`` / the pytest ``trace_files``
        gate) or disabled mid-run by an I/O fault. No production caller — the CLI calls ``finalize()``
        directly; this alias is kept for the run-scoped collector tests that call it.
        """
        return self.finalize()

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
