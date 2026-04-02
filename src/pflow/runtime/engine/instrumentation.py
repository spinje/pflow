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
from pflow.core.llm_pricing import enrich_llm_usage_with_cost

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

    Invalidates in-process cache for revisited nodes.

    Returns:
        The visit_counts dict for use by memoization checks.
    """
    visit_counts: dict[str, int] = shared["__execution__"]["node_visit_counts"]
    visit_counts[node_id] = visit_counts.get(node_id, 0) + 1
    if visit_counts[node_id] > MAX_NODE_VISITS:
        raise MaxNodeVisitsError(node_id, visit_counts[node_id], MAX_NODE_VISITS)

    # Invalidate cache for revisited nodes — cache is for workflow resume, not loops
    if visit_counts[node_id] > 1:
        completed = shared["__execution__"]["completed_nodes"]
        if node_id in completed:
            completed.remove(node_id)
            shared["__execution__"]["node_actions"].pop(node_id, None)
            shared["__execution__"]["node_hashes"].pop(node_id, None)

    return visit_counts


# --- In-Process Cache (Checkpoint/Resume) ---


def check_cache_validity(node_id: str, config_hash: str, shared: dict) -> tuple[bool, Any]:
    """Check if node is in completed list with matching hash.

    Returns:
        (valid, cached_action)
    """
    if node_id not in shared["__execution__"]["completed_nodes"]:
        return False, None

    cached_hash = shared["__execution__"]["node_hashes"].get(node_id)
    if config_hash == cached_hash:
        cached_action = shared["__execution__"]["node_actions"].get(node_id, "default")
        return True, cached_action
    else:
        # Cache invalid — config changed
        invalidate_cache(node_id, shared)
        return False, None


def cache_result(node_id: str, config_hash: str, action: str, shared: dict) -> None:
    """Record node as completed with its config hash."""
    action_str = str(action) if action else "default"
    if not action_str.startswith("error"):
        shared["__execution__"]["completed_nodes"].append(node_id)
        shared["__execution__"]["node_actions"][node_id] = action_str
        shared["__execution__"]["node_hashes"][node_id] = config_hash
    else:
        shared["__execution__"]["failed_node"] = node_id


def invalidate_cache(node_id: str, shared: dict) -> None:
    """Remove node from all cache structures."""
    completed = shared["__execution__"]["completed_nodes"]
    if node_id in completed:
        completed.remove(node_id)
    shared["__execution__"]["node_actions"].pop(node_id, None)
    shared["__execution__"]["node_hashes"].pop(node_id, None)


# --- Memoization Cache (Cross-Run SQLite) ---


def compute_node_config(
    node_type_name: str,
    static_params: dict,
    template_params: dict,
    batch_config: Optional[BatchConfig],
) -> dict[str, Any]:
    """Build config dict for cache key.

    Reads directly from config, no chain traversal.
    MUST include template_params (raw template strings) in the hash.
    MUST exclude _source_line keys from static_params.
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

    return config


def compute_config_hash(config: dict[str, Any]) -> str:
    """MD5 of deterministic JSON config."""
    from pflow.runtime.cache import _deterministic_json

    config_json = _deterministic_json(config)
    return hashlib.md5(config_json.encode()).hexdigest()  # noqa: S324


def check_memo_cache(
    node_id: str,
    node_type_name: str,
    config_hash: str,
    batch_config: Optional[BatchConfig],
    shared: dict,
    visit_counts: dict,
    resolved_params: Optional[dict] = None,
) -> tuple[bool, Any, Optional[str]]:
    """Check SQLite memo cache.

    Returns:
        (hit, result, cache_key):
        - hit=True, result=action, cache_key=None on cache hit
        - hit=False, result=None, cache_key=str on cache miss (key for later write)
        - hit=False, result=None, cache_key=None when memoization is skipped
    """
    memo_cache = shared.get("__memoization_cache__")
    if not memo_cache or visit_counts.get(node_id, 0) > 1:
        return False, None, None

    # Skip for WorkflowExecutor — sub-workflow files may change
    if node_type_name == "WorkflowExecutor":
        return False, None, None

    # Compute cache key
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

    cached = memo_cache.get(cache_key)
    if cached is None:
        return False, None, cache_key

    cached_action, cached_output = cached
    cached_action = cached_action or "default"  # Normalize None from SQLite
    # Restore output for downstream template resolution
    shared[node_id] = cached_output
    # Record in in-process execution state
    shared["__execution__"]["completed_nodes"].append(node_id)
    shared["__execution__"]["node_actions"][node_id] = cached_action
    shared["__execution__"]["node_hashes"][node_id] = config_hash

    return True, cached_action, None


def write_memo_cache(node_id: str, shared: dict, cache_key: Optional[str], action: str = "default") -> None:
    """Write to SQLite cache after successful execution. Skips error results."""
    if not cache_key or str(action).startswith("error"):
        return
    memo_cache = shared.get("__memoization_cache__")
    if not memo_cache:
        return
    node_output = shared.get(node_id)
    if node_output is not None:
        workflow_path = shared.get("_pflow_workflow_file")
        output_dict = dict(node_output) if isinstance(node_output, dict) else {"value": node_output}
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
    error: Optional[Exception] = None,
    success: Optional[bool] = None,
) -> None:
    """Record trace event. Receives data directly, no chain traversal."""
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


def enrich_llm_cost(node_id: str, shared: dict) -> None:
    """Add cost data to llm_usage. Checks both root and namespaced locations."""
    llm_usage = None
    if "llm_usage" in shared:
        llm_usage = shared["llm_usage"]
    elif node_id in shared and isinstance(shared[node_id], dict):
        llm_usage = shared[node_id].get("llm_usage")
    if isinstance(llm_usage, dict):
        enrich_llm_usage_with_cost(llm_usage)


def setup_llm_interception(node_id: str, node_type_name: str, node_params: dict, trace_collector: Any) -> None:
    """Set up LLM prompt/response capture if trace collector present."""
    if not trace_collector or not hasattr(trace_collector, "setup_llm_interception"):
        return

    node_type_lower = node_type_name.lower()
    is_llm_node = "llm" in node_type_lower
    has_prompt_param = "prompt" in node_params
    has_model_param = "model" in node_params

    if is_llm_node or has_prompt_param or has_model_param:
        trace_collector.setup_llm_interception(node_id)


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
        )


def handle_cached_execution(
    node_id: str,
    shared: dict,
    cached_action: Any,
    shared_keys_before: set,
    node_type_name: str,
    node_params: dict,
    trace_collector: Any,
) -> Any:
    """Handle cached node execution: record trace, call callbacks."""
    if "__cache_hits__" not in shared:
        shared["__cache_hits__"] = []
    shared["__cache_hits__"].append(node_id)

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
    """Handle API warning: record failure, return 'error'."""
    if "__warnings__" not in shared:
        shared["__warnings__"] = {}
    shared["__warnings__"][node_id] = warning

    shared["__execution__"]["failed_node"] = node_id

    duration_ms = (time.perf_counter() - start_time) * 1000

    if metrics:
        metrics.record_node_execution(node_id, duration_ms)

    # Call progress callback with warning
    callback = shared.get("__progress_callback__")
    if callable(callback):
        depth = shared.get("_pflow_depth", 0)
        with contextlib.suppress(Exception):
            callback(node_id, "node_warning", warning, depth)

    # Record trace
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

    return "error"
