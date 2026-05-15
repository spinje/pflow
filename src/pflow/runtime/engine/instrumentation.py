"""Standalone instrumentation functions for the execution engine.

Extracted from instrumented_wrapper.py. These functions handle execution state,
caching (in-process + memoization), tracing, metrics, progress callbacks,
loop guards, and API warning handling — all without instance state or
wrapper chain traversal.
"""

import contextlib
import hashlib
import logging
import os
import time
from typing import Any, Optional

from pflow.core.exceptions import MaxNodeVisitsError

from .types import BatchConfig

try:
    MAX_NODE_VISITS = int(os.environ.get("PFLOW_MAX_NODE_VISITS", "100"))
except ValueError:
    MAX_NODE_VISITS = 100

logger = logging.getLogger(__name__)


# --- Execution State ---


def initialize_execution_state(shared: dict) -> None:
    """Ensure __execution__ and __cache_hits__ exist in shared store."""
    if "__execution__" not in shared:
        shared["__execution__"] = {
            "completed_nodes": [],
            "node_actions": {},
            "node_hashes": {},
            "failed_node": None,
            "node_visit_counts": {},
        }
    else:
        if "node_hashes" not in shared["__execution__"]:
            shared["__execution__"]["node_hashes"] = {}
        if "node_visit_counts" not in shared["__execution__"]:
            shared["__execution__"]["node_visit_counts"] = {}

    if "__cache_hits__" not in shared:
        shared["__cache_hits__"] = []


def enforce_loop_guard(node_id: str, shared: dict) -> dict[str, int]:
    """Increment visit count, raise MaxNodeVisitsError if exceeded.

    Invalidates in-process cache AND clears any stale __failures__ record
    for revisited nodes. Without the failures clear, a node that failed on
    visit 1 and succeeds on visit 2 would still show as FAILED in
    get_node_status() because failures are checked first.

    Returns:
        The visit_counts dict for use by memoization checks.
    """
    visit_counts: dict[str, int] = shared["__execution__"]["node_visit_counts"]
    visit_counts[node_id] = visit_counts.get(node_id, 0) + 1
    if visit_counts[node_id] > MAX_NODE_VISITS:
        raise MaxNodeVisitsError(node_id, visit_counts[node_id], MAX_NODE_VISITS)

    # Invalidate cache + failure record for revisited nodes — both are
    # snapshots of a previous attempt; the new attempt starts fresh.
    if visit_counts[node_id] > 1:
        completed = shared["__execution__"]["completed_nodes"]
        if node_id in completed:
            completed.remove(node_id)
            shared["__execution__"]["node_actions"].pop(node_id, None)
            shared["__execution__"]["node_hashes"].pop(node_id, None)

        from pflow.runtime.node_state import clear_node_failure

        clear_node_failure(shared, node_id)

    return visit_counts


# --- In-Process Cache (Checkpoint/Resume) ---


def check_cache_validity(node_id: str, config_hash: str, shared: dict) -> tuple[bool, Any]:
    """Backwards-compatible wrapper: lookup + invalidate-on-mismatch."""
    valid, cached_action = in_process_cache_lookup(node_id, config_hash, shared)
    if valid:
        return True, cached_action

    execution = shared.get("__execution__", {})
    completed_nodes = execution.get("completed_nodes", [])
    if node_id in completed_nodes:
        invalidate_cache(node_id, shared)
    return False, None


def cache_result(node_id: str, config_hash: str, action: str, shared: dict) -> None:
    """Record node as completed with its config hash.

    For error actions this is a no-op — step 17.5 in ``engine._execute_node``
    runs ``mark_node_failed`` which is the single write site for ``failed_node``.
    """
    action_str = str(action) if action else "default"
    if not action_str.startswith("error"):
        shared["__execution__"]["completed_nodes"].append(node_id)
        shared["__execution__"]["node_actions"][node_id] = action_str
        shared["__execution__"]["node_hashes"][node_id] = config_hash


def invalidate_cache(node_id: str, shared: dict) -> None:
    """Remove node from all cache structures."""
    execution = shared.setdefault("__execution__", {})
    completed = execution.setdefault("completed_nodes", [])
    if node_id in completed:
        completed.remove(node_id)
    execution.setdefault("node_actions", {}).pop(node_id, None)
    execution.setdefault("node_hashes", {}).pop(node_id, None)


# --- Memoization Cache (Cross-Run SQLite) ---


def in_process_cache_lookup(node_id: str, config_hash: str, shared: dict) -> tuple[bool, Any]:
    """Pure read: check in-process cache state without mutating."""
    execution = shared.get("__execution__", {})
    completed_nodes = execution.get("completed_nodes", [])
    if node_id not in completed_nodes:
        return False, None

    cached_hash = execution.get("node_hashes", {}).get(node_id)
    if config_hash == cached_hash:
        cached_action = execution.get("node_actions", {}).get(node_id, "default")
        return True, cached_action
    return False, None


def compute_node_config(
    node_type_name: str,
    static_params: dict,
    template_params: dict,
    batch_config: Optional[BatchConfig],
    *,
    prompt_cache_content: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Build config dict for cache key.

    Reads directly from config, no chain traversal.
    MUST include template_params (raw template strings) in the hash.
    MUST exclude _source_line keys from static_params.

    Task 159 B3.4: ``prompt_cache_content`` is the rendered cache prefix
    (list of ``{"name": ..., "prose": ..., "value": ...}`` dicts in declaration
    order, ABSENT chunks already filtered). Included CONDITIONALLY (truthy
    list only) so workflows without ``prompt_cache:`` produce identical
    hashes pre- and post-task (DD#19 — silent stale cache is the #1 risk).
    Empty list ``[]`` falls through, byte-identical to ``None``.
    """
    config: dict[str, Any] = {"type": node_type_name, "params": {}}

    # Static params (filtered)
    if static_params:
        config["params"] = dict(sorted((k, v) for k, v in static_params.items() if not k.endswith("_source_line")))

    # Template params (raw templates, not resolved)
    if template_params:
        config["template_params"] = dict(sorted(template_params.items()))

    # Semantic batch config
    if batch_config:
        config["batch"] = {
            "items_template": batch_config.items_template,
            "item_alias": batch_config.item_alias,
            "error_handling": batch_config.error_handling,
            "max_retries": batch_config.max_retries,
        }

    # Task 159 B3.4: rendered prompt-cache content (conditional inclusion).
    if prompt_cache_content:
        config["prompt_cache"] = prompt_cache_content

    return config


def compute_config_hash(config: dict[str, Any]) -> str:
    """MD5 of deterministic JSON config."""
    from pflow.runtime.cache import _deterministic_json

    config_json = _deterministic_json(config)
    return hashlib.md5(config_json.encode()).hexdigest()  # noqa: S324


def memo_cache_lookup(
    node_id: str,
    node_type_name: str,
    config_hash: str,
    batch_config: Optional[BatchConfig],
    shared: dict,
    visit_counts: dict,
    resolved_params: Optional[dict] = None,
) -> tuple[bool, Optional[str], Optional[tuple[str, dict, Optional[float]]]]:
    """Pure read: check SQLite memo cache without mutating shared state.

    Task 159 E.1: the success-shape third element is now a 3-tuple
    ``(action, output, created_at_epoch)``. ``created_at_epoch`` is the
    SQLite ``created_at`` column from the memo cache row — callers compute
    ``cache_age_sec = time.time() - created_at`` for trace 2.1.0. The age
    surfaces only when the lookup goes through ``MemoizationCache.get_with_age``;
    callers that don't care can ignore the third element.
    """
    memo_cache = shared.get("__memoization_cache__")
    if not memo_cache or visit_counts.get(node_id, 0) > 1:
        return False, None, None

    if node_type_name == "WorkflowExecutor":
        return False, None, None

    from pflow.runtime.cache import compute_node_cache_key

    if batch_config:
        from pflow.runtime.cache import compute_batch_cache_key

        from .batch_executor import resolve_batch_items

        items_template = batch_config.items_template
        if items_template is None:
            return False, None, None

        try:
            resolved_items = resolve_batch_items(items_template, shared)
            if not isinstance(resolved_items, list):
                return False, None, None
        except Exception:
            logger.debug("Failed to resolve batch items for memo cache key", exc_info=True)
            return False, None, None

        semantic_config = {
            "items_template": items_template,
            "item_alias": batch_config.item_alias,
            "error_handling": batch_config.error_handling,
            "max_retries": batch_config.max_retries,
        }
        cache_key = compute_batch_cache_key(config_hash, semantic_config, resolved_items)
    elif resolved_params is not None:
        cache_key = compute_node_cache_key(config_hash, resolved_params)
    else:
        cache_key = compute_node_cache_key(config_hash)

    if not cache_key:
        return False, None, None

    # Task 159 E.1: ``get_with_age`` returns ``(action, output, created_at)``
    # so callers can compute ``cache_age_sec`` for trace 2.1.0. The age lookup
    # is the same SQLite row the legacy ``.get`` reads — no extra query.
    cached_with_age = memo_cache.get_with_age(cache_key)
    if cached_with_age is None:
        return False, cache_key, None

    cached_action, cached_output, created_at = cached_with_age
    cached_action = cached_action or "default"
    return True, cache_key, (cached_action, cached_output, created_at)


def _should_write_cache_metadata(node_type_name: str) -> bool:
    """Allowlist semantics for trace 2.1.0 cache-metadata fields.

    Returns ``True`` only for node types that participate in pflow's memo
    cache layer with explicit ``cache_key`` / ``cache_source`` /
    ``cache_age_sec`` semantics. Currently only ``LLMNode``. Adding a new
    LLM-producing node type that participates requires extending this gate
    alongside the new node type's ``post()`` implementation.

    ``ClaudeCodeNode`` is intentionally NOT in the allowlist: its
    ``cache_creation_input_tokens`` / ``cache_read_input_tokens`` come from
    the Claude SDK and reflect SDK-side caching (a different cache layer).
    Adding pflow's memo ``cache_key`` / ``cache_source`` to ClaudeCodeNode's
    ``llm_usage`` would conflate two distinct cache layers and mislead
    agents reading the trace.
    """
    return node_type_name == "LLMNode"


def _log_skipped_cache_metadata(node_type_name: str, sample_output: Any) -> None:
    """Emit a debug signal when cache-metadata writes are skipped for a
    node type that DID produce an ``llm_usage`` payload.

    Most non-LLM node types never write ``llm_usage``, so the gate's
    silent-skip is a no-op for them. But a future LLM-producing node type
    (e.g., a hypothetical ``OllamaNode`` / ``BedrockNode`` / ``GroqNode``)
    would silently lose trace-2.1.0 cache fields with no signal to the
    producer. This debug log gives them a hook: when the test author or
    runtime observer sees ``llm_usage`` populated AND the gate returning
    False, they know they need to extend the allowlist.

    Debug-level (not warning) so production logs aren't noisy for the
    common ClaudeCodeNode case (which is intentionally excluded).
    """
    if isinstance(sample_output, dict) and sample_output.get("llm_usage"):
        logger.debug(
            "cache metadata gate: skipping non-allowlisted LLM-producing node "
            "type %r; trace 2.1.0 cache fields will be absent. To enable, add "
            "%r to _should_write_cache_metadata.",
            node_type_name,
            node_type_name,
        )


def _augment_llm_usage_with_cache_metadata(
    shared: dict,
    node_id: str,
    *,
    cache_source: Optional[str],
    cache_key: Optional[str],
    cache_age_sec: Optional[float],
) -> None:
    """Write cache-metadata fields into ``shared[node_id]['llm_usage']``.

    Trace 2.1.0 surfaces these per-event via the existing
    ``llm_usage`` channel that ``_add_llm_data`` already reads (no new
    sidecar). Caller is responsible for the ``_should_write_cache_metadata``
    gate; this helper assumes the gate has fired.
    """
    node_output = shared.get(node_id)
    if not isinstance(node_output, dict):
        return
    llm_usage = node_output.get("llm_usage")
    if not isinstance(llm_usage, dict):
        return
    if cache_source is not None:
        llm_usage["cache_source"] = cache_source
    if cache_key is not None:
        llm_usage["cache_key"] = cache_key
    if cache_age_sec is not None:
        llm_usage["cache_age_sec"] = cache_age_sec


def apply_memo_hit(
    node_id: str,
    shared: dict,
    cached_action: str,
    cached_output: dict,
    config_hash: str,
    *,
    node_type_name: str,
    cache_key: Optional[str] = None,
    created_at: Optional[float] = None,
) -> None:
    """Apply a memoization cache hit to shared state.

    `__pflow_stats__` and `__pflow_warnings__` are engine-injected metadata
    that live in the stored blob but must NOT leak into `shared[node_id]`.
    Stats feed --dry-run historical estimates; warnings are rehydrated to the
    root `shared["__warnings__"]` channel so cached degraded executions retain
    the same status as fresh executions.

    Task 159 E.1: when ``_should_write_cache_metadata(node_type_name)``
    fires, augment the restored ``llm_usage`` dict with ``cache_source =
    "memo"``, ``cache_key`` (the matching key), and ``cache_age_sec``
    (computed as ``time.time() - created_at``). Trace 2.1.0 surfaces these
    fields via the existing ``_add_llm_data`` integration site — no new
    sidecar dict required. ``node_type_name`` is keyword-only so future
    positional-arg drift can't accidentally bypass the gate.
    """
    execution = shared.setdefault("__execution__", {})
    completed_nodes = execution.setdefault("completed_nodes", [])
    node_actions = execution.setdefault("node_actions", {})
    node_hashes = execution.setdefault("node_hashes", {})

    reserved_keys = {"__pflow_stats__", "__pflow_warnings__"}
    restored = {k: v for k, v in cached_output.items() if k not in reserved_keys}
    cached_warning = cached_output.get("__pflow_warnings__")
    if cached_warning is not None:
        shared.setdefault("__warnings__", {})[node_id] = cached_warning
    shared[node_id] = restored
    completed_nodes.append(node_id)
    node_actions[node_id] = cached_action
    node_hashes[node_id] = config_hash

    if _should_write_cache_metadata(node_type_name):
        cache_age_sec = (time.time() - created_at) if created_at is not None else None
        _augment_llm_usage_with_cache_metadata(
            shared,
            node_id,
            cache_source="memo",
            cache_key=cache_key,
            cache_age_sec=cache_age_sec,
        )
    else:
        # Future LLM-producing node types: surface a debug signal so the
        # producer knows to extend the allowlist if their llm_usage should
        # carry cache_key / cache_source / cache_age_sec.
        _log_skipped_cache_metadata(node_type_name, cached_output)


def check_memo_cache(
    node_id: str,
    node_type_name: str,
    config_hash: str,
    batch_config: Optional[BatchConfig],
    shared: dict,
    visit_counts: dict,
    resolved_params: Optional[dict] = None,
) -> tuple[bool, Any, Optional[str]]:
    """Backwards-compatible wrapper: lookup + apply memo hit."""
    hit, cache_key, cached_data = memo_cache_lookup(
        node_id=node_id,
        node_type_name=node_type_name,
        config_hash=config_hash,
        batch_config=batch_config,
        shared=shared,
        visit_counts=visit_counts,
        resolved_params=resolved_params,
    )
    if hit and cached_data is not None:
        cached_action, cached_output, created_at = cached_data
        apply_memo_hit(
            node_id,
            shared,
            cached_action,
            cached_output,
            config_hash,
            node_type_name=node_type_name,
            cache_key=cache_key,
            created_at=created_at,
        )
        return True, cached_action, None
    return False, None, cache_key


def write_memo_cache(
    node_id: str,
    shared: dict,
    cache_key: Optional[str],
    action: str = "default",
    *,
    duration_ms: Optional[float] = None,
    node_type_name: str,
) -> None:
    """Write to SQLite cache after successful execution. Skips error results.

    Optionally records execution metadata (currently `duration_ms`) under the
    reserved output key `__pflow_stats__` so `--dry-run` can surface historical
    duration estimates via `MemoizationCache.get_latest_for_node`.

    Dunder naming is load-bearing: `cache.py::_make_serializable` collapses
    dunder-keyed values to their type name for deterministic hashing, so
    stats deltas don't invalidate cache identity. A single-underscore key
    would feed stats into the hash — silent cache-breakage bug.

    Task 159 E.1: when ``_should_write_cache_metadata(node_type_name)``
    fires, augment ``shared[node_id]['llm_usage']['cache_key']`` with the
    key the entry was stored under BEFORE persisting to disk. The trace
    event for THIS run records the key the entry was written with;
    subsequent memo-hit runs round-trip the same key via
    ``apply_memo_hit``.
    """
    if not cache_key or str(action).startswith("error"):
        return
    memo_cache = shared.get("__memoization_cache__")
    if not memo_cache:
        return
    node_output = shared.get(node_id)
    if node_output is not None:
        if _should_write_cache_metadata(node_type_name):
            _augment_llm_usage_with_cache_metadata(
                shared,
                node_id,
                cache_source=None,  # write events have no source label
                cache_key=cache_key,
                cache_age_sec=None,
            )
            # Re-read after augmentation so the persisted blob carries the key.
            node_output = shared.get(node_id)
        else:
            _log_skipped_cache_metadata(node_type_name, node_output)
        workflow_path = shared.get("_pflow_workflow_file")
        output_dict = dict(node_output) if isinstance(node_output, dict) else {"value": node_output}
        node_warning = shared.get("__warnings__", {}).get(node_id)
        if node_warning is not None:
            output_dict["__pflow_warnings__"] = node_warning
        if duration_ms is not None:
            output_dict["__pflow_stats__"] = {"duration_ms": float(duration_ms)}
        memo_cache.put(cache_key, node_id, workflow_path, action or "default", output_dict)


# --- Metrics & Tracing ---


def record_trace(
    node_id: str,
    node_type_name: str,
    shared: dict,
    start_time: float,
    shared_keys_before: set,
    last_resolutions: dict,
    batch_trace_items: Optional[list],
    child_trace_events: Optional[list],
    node_params: dict,
    trace_collector: Any,
    cached: bool = False,
    error: Optional[Exception | str] = None,
    success: Optional[bool] = None,
) -> None:
    """Record trace event. Receives data directly, no chain traversal.

    The ``error`` parameter accepts either an ``Exception`` (from raised-exception
    failure paths) or a ``str`` (from action="error" happy-path failures where no
    exception was raised — e.g., shell exit 1 with ``- on-error:`` routing). Both
    are coerced to a string for the trace event's ``error`` field so downstream
    consumers (``--report``, ``runtime/workflow_trace.save_to_file``) can surface
    the actual failure message instead of falling back to "Unknown error".
    """
    if not trace_collector:
        return

    duration_ms = (time.perf_counter() - start_time) * 1000

    # Get node output
    node_output = shared.get(node_id)
    if isinstance(node_output, dict):
        node_output = dict(node_output)
    elif node_output is not None:
        node_output = {"value": node_output}
    else:
        node_output = {}

    # Compute mutations
    shared_keys_after = set(shared.keys())
    added = shared_keys_after - shared_keys_before if shared_keys_before else set()
    removed = shared_keys_before - shared_keys_after if shared_keys_before else set()
    mutations = {
        "added": sorted(
            k
            for k in added
            if not k.startswith("__")
            and not k.startswith("_pflow")
            and not k.startswith("_trace")
            and not k.startswith("_batch")
        ),
        "removed": sorted(
            k
            for k in removed
            if not k.startswith("__")
            and not k.startswith("_pflow")
            and not k.startswith("_trace")
            and not k.startswith("_batch")
        ),
        "modified": [],
    }

    trace_collector.record_node_execution(
        node_id=node_id,
        node_type=node_type_name,
        duration_ms=duration_ms,
        success=success if success is not None else (error is None),
        error=str(error) if error else None,
        node_params=node_params,
        template_resolutions=last_resolutions,
        node_output=node_output,
        mutations=mutations,
        batch_items=batch_trace_items if batch_trace_items else None,
        sub_workflow_events=child_trace_events,
        cached=cached,
    )


# --- Progress Callbacks ---


def call_start_callback(node_id: str, shared: dict) -> None:
    """Call progress callback with node_start."""
    callback = shared.get("__progress_callback__")
    if callable(callback):
        depth = shared.get("_pflow_depth", 0)
        with contextlib.suppress(Exception):
            callback(node_id, "node_start", None, depth)


def call_completion_callback(
    node_id: str,
    shared: dict,
    action: str,
    duration_ms: float,
    error: Optional[Exception] = None,
    ignore_errors: bool = False,
) -> None:
    """Call progress callback with node_complete."""
    callback = shared.get("__progress_callback__")
    if not callable(callback):
        return

    depth = shared.get("_pflow_depth", 0)

    # Get exit code if available
    exit_code = shared.get(node_id, {}).get("exit_code") if isinstance(shared.get(node_id), dict) else None
    error_msg = None

    action_str = str(action) if action else "default"
    if action_str.startswith("error"):
        error_msg = f"Command failed with exit code {exit_code}" if exit_code else "Failed"
    elif exit_code and exit_code != 0 and ignore_errors:
        error_msg = f"Command failed with exit code {exit_code}"

    # Detect batch node
    node_output = shared.get(node_id, {})
    is_batch = isinstance(node_output, dict) and "batch_metadata" in node_output
    batch_total = None
    batch_success_count = None
    if is_batch:
        batch_total = node_output.get("count", 0)
        batch_success_count = node_output.get("success_count", 0)

    smart_handled = False
    smart_handled_reason = None
    if isinstance(node_output, dict):
        smart_handled = bool(node_output.get("smart_handled", False))
        smart_handled_reason = node_output.get("smart_handled_reason")

    with contextlib.suppress(Exception):
        callback(
            node_id,
            "node_complete",
            duration_ms,
            depth,
            error_message=error_msg,
            ignore_errors=ignore_errors,
            is_error=action_str.startswith("error"),
            is_batch=is_batch,
            batch_total=batch_total,
            batch_success_count=batch_success_count,
            smart_handled=smart_handled,
            smart_handled_reason=smart_handled_reason,
        )


def handle_cached_execution(
    node_id: str,
    shared: dict,
    cached_action: Any,
    shared_keys_before: set,
    node_type_name: str,
    node_params: dict,
    trace_collector: Any,
    *,
    cache_source: Optional[str] = None,
) -> Any:
    """Handle cached node execution: record trace, call callbacks.

    The two cache paths that reach this function (memo cache + in-process
    cache) are both unreachable for nodes that have a stale ``__failures__``
    record: memo cache is skipped on revisits (``visit_count > 1``) and the
    loop guard's ``clear_node_failure`` runs before any cache check on the
    second visit. Error results are never cached either. Any defensive
    ``clear_node_failure`` call here is dead code — if future work makes it
    load-bearing (e.g. checkpoint-resume seeding a shared store with both
    ``shared[id]`` and ``__failures__[id]``), add it back with a test that
    exercises the reaching path, not as speculative defense.

    Task 159 E.1 ``cache_source`` keyword-only parameter: caller specifies the
    label (e.g., ``"in_process"`` for the in-process branch). The memo branch
    omits it — ``apply_memo_hit`` already wrote ``"memo"`` along with the
    matching key + age. Without this, both branches funnelled through here
    would silently overwrite the memo augment with ``"in_process"`` (DD#22
    distinguishes memo from in-process; that distinction is load-bearing for
    ``analyze-cache --from-trace``). Keyword-only so positional drift can't
    accidentally re-introduce the overwrite.
    """
    if "__cache_hits__" not in shared:
        shared["__cache_hits__"] = []
    shared["__cache_hits__"].append(node_id)

    # Task 159 E.1: augment llm_usage with the caller-specified cache_source.
    # No-op when ``cache_source is None`` so the memo path (already augmented
    # by ``apply_memo_hit`` with ``"memo"``) is never overwritten.
    if cache_source is not None:
        if _should_write_cache_metadata(node_type_name):
            _augment_llm_usage_with_cache_metadata(
                shared,
                node_id,
                cache_source=cache_source,
                cache_key=None,
                cache_age_sec=None,
            )
        else:
            _log_skipped_cache_metadata(node_type_name, shared.get(node_id))

    # Record trace for cached node
    record_trace(
        node_id,
        node_type_name,
        shared,
        time.perf_counter(),
        shared_keys_before,
        {},
        None,
        None,
        node_params,
        trace_collector,
        cached=True,
    )

    # Call progress callbacks
    callback = shared.get("__progress_callback__")
    if callable(callback):
        depth = shared.get("_pflow_depth", 0)
        with contextlib.suppress(Exception):
            callback(node_id, "node_start", None, depth)
            callback(node_id, "node_cached", None, depth)

    return cached_action


# --- API Warning ---


def handle_api_warning(
    node_id: str,
    shared: dict,
    warning: str,
    metrics: Any,
    trace_collector: Any,
    start_time: float,
    shared_keys_before: set,
    node_type_name: str,
    node_params: dict,
) -> str:
    """Handle API warning: record trace/metrics, archive via ``mark_node_failed``.

    Writes to ``__warnings__`` and ``__execution__['failed_node']`` happen inside
    ``mark_node_failed`` at the end of this function (the canonical single write
    site). Don't duplicate those writes here.
    """
    duration_ms = (time.perf_counter() - start_time) * 1000

    if metrics:
        metrics.record_node_execution(node_id, duration_ms)

    # Call progress callback with warning. Pass `warning` via the
    # `error_message` kwarg so the OutputController callback closure
    # receives the warning text in a properly-named parameter (the
    # earlier positional convention abused the `duration_ms` slot to
    # smuggle a string through, which forced an ``isinstance`` type
    # check on the receiving end and made the parameter name lie about
    # what it held).
    callback = shared.get("__progress_callback__")
    if callable(callback):
        depth = shared.get("_pflow_depth", 0)
        with contextlib.suppress(Exception):
            callback(node_id, "node_warning", depth=depth, error_message=warning)

    # Record trace BEFORE the data move so the trace event has the full
    # node output (stdout/stderr/exit_code/etc.).
    record_trace(
        node_id,
        node_type_name,
        shared,
        start_time,
        shared_keys_before,
        {},
        None,
        None,
        node_params,
        trace_collector,
        error=Exception(warning),
    )

    # LAST STEP: archive the node's data to __failures__.
    #
    # The post-detector warning text (``warning``) is the authoritative
    # top-line error for api_warning failures. It is the message the
    # detector extracted out of the raw node output via error-code
    # classification (``API error (404): Repository not found``). The raw
    # node ``error`` field is often a less-actionable pre-detection artifact
    # (``HTTP request failed``) and is preserved inside ``failure.data``
    # (the archived node namespace) for anyone who needs the raw form.
    #
    # This keeps ``failure.error`` the single authoritative source regardless
    # of category — ``_extract_error_info`` in the runner just reads it.
    from pflow.runtime.node_state import FAILURE_CATEGORY_API_WARNING, mark_node_failed

    mark_node_failed(
        shared,
        node_id,
        category=FAILURE_CATEGORY_API_WARNING,
        error=warning,
        warning=warning,
    )

    return "error"
