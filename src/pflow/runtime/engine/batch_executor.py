"""Standalone batch execution functions for the execution engine.

Extracted from batch_node.py. Handles sequential and parallel batch processing
with retry, error handling, progress callbacks, and trace capture.

Key differences from the old PflowBatchNode:
- _exec_single and _exec_single_with_node merged into one _execute_batch_item
- No wrapper chain traversal for trace data — engine has direct access
- execute_single_fn callback replaces inner_node._run() delegation
"""

import contextlib
import copy
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

from pflow.core.exceptions import CompilationError
from pflow.core.json_utils import try_parse_json
from pflow.runtime.template_resolver import TemplateResolver

from .types import BatchConfig, NodeConfig

logger = logging.getLogger(__name__)

# Keys injected by the batch framework, not by the inner node.
_BATCH_META_KEYS = frozenset({"item", "original_index", "error", "exception"})


def resolve_batch_items(items_template: Any, shared: dict[str, Any]) -> Any:
    """Resolve a batch items template to its runtime value.

    Args:
        items_template: Template string (e.g., "${node.files}") or inline list
        shared: The shared store to resolve against

    Returns:
        Resolved value (list on success, None if unresolved).
    """
    if isinstance(items_template, list):
        return TemplateResolver.resolve_nested(items_template, shared)

    resolved = TemplateResolver.resolve_template(items_template.strip(), shared)
    if resolved == items_template.strip():
        return None

    # Auto-parse JSON strings (enables shell -> batch patterns)
    if isinstance(resolved, str):
        success, parsed = try_parse_json(resolved)
        if success and isinstance(parsed, list):
            return parsed

    return resolved


def _resolve_and_validate_items(batch_config: BatchConfig, shared: dict[str, Any], node_id: str) -> list[Any]:
    """Resolve batch items template and validate the result is a list.

    Raises ValueError if items resolve to None, TypeError if not a list.
    """
    items = resolve_batch_items(batch_config.items_template, shared)

    if items is None:
        base_error = (
            f"Node '{node_id}': batch items template '{batch_config.items_template}' resolved to None. "
            f"Ensure the referenced node output exists."
        )
        raise ValueError(_enrich_with_upstream_stderr(base_error, batch_config.items_template, shared))

    if not isinstance(items, list):
        base_error = (
            f"Node '{node_id}': batch items must be an array, got {type(items).__name__}. "
            f"Template '{batch_config.items_template}' resolved to: {items!r}"
        )
        raise TypeError(_enrich_with_upstream_stderr(base_error, batch_config.items_template, shared))

    return items


def _enrich_with_upstream_stderr(base_error: str, items_template: Any, shared: dict[str, Any]) -> str:
    """Append upstream stderr context to error message if available."""
    if isinstance(items_template, str):
        from .error_context import get_upstream_stderr

        upstream_context = get_upstream_stderr(items_template, shared)
        if upstream_context:
            return base_error + upstream_context
    return base_error


def _collect_batch_trace(shared: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    """Transfer batch trace items from shared store accumulator, clean up."""
    batch_trace_dict = shared.get("_batch_trace")
    if not isinstance(batch_trace_dict, dict):
        return []
    batch_trace_items: list[dict[str, Any]] = batch_trace_dict.pop(node_id, [])
    if not batch_trace_dict:
        shared.pop("_batch_trace", None)
    return batch_trace_items


def _pre_warm_compile_cache(
    node: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    execute_single_fn: Callable,
    batch_config: BatchConfig,
    first_item: Any,
) -> None:
    """Pre-compile sub-workflows so parallel deep copies inherit the cache.

    Only useful for WorkflowExecutor nodes (which have _compile_sub_workflow).
    For regular nodes, this is a no-op.

    Runs prep() + _compile_sub_workflow() on the original node instance without
    executing the sub-workflow. After this, deepcopy(node) inherits both the
    IR load cache (``_loaded_ir_cache``) and the compiled-workflow cache
    (``_compiled_workflow_cache``).

    Defensive bail-out: if prep() leaves ``_loaded_ir_cache`` empty (which
    today only happens when ``_load_workflow`` itself raised), skip the compile
    step — pre-warming a broken state would just hide the real error.
    """
    if not hasattr(node, "_compile_sub_workflow"):
        return  # Not a WorkflowExecutor — nothing to pre-warm

    # Create a temporary item context with the first item
    temp_shared = dict(shared)
    temp_shared[config.node_id] = {}
    temp_shared[batch_config.item_alias] = first_item
    temp_shared["__index__"] = 0

    # Resolve templates to get concrete params (like the engine does per-item)
    original_params = node.params
    try:
        if config.template_config:
            from .template_resolution import resolve_templates

            merged_params, _, _ = resolve_templates(config.template_config, temp_shared, config.node_id)
            node.params = merged_params

        # Run prep() to populate _loaded_ir_cache. Pre-warm's job is to do
        # this load-and-compile work ONCE on the original node, so each
        # parallel worker's deepcopy inherits the cache instead of all
        # racing to load/compile independently.
        prep_res = node.prep(temp_shared)

        # Prep captured a recoverable failure for item[0] (bad input shape,
        # circular ref, etc — see WorkflowExecutor._PREP_RECOVERABLE). The
        # marker prep_res lacks child_ir/child_params so the compile step
        # would KeyError. Skip compile and let the per-item batch loop
        # surface the failure through error_action — other items may have
        # valid inputs. GH #302 tracks decoupling pre-warm from prep()
        # internals so this defensive check isn't needed.
        if "_prep_error" in prep_res:
            return

        # Only proceed if the workflow came from a file/name source
        # (_loaded_ir_cache has an entry). Defensive: if _load_workflow raised,
        # the cache stays empty and pre-warming would just hide the real error.
        if not getattr(node, "_loaded_ir_cache", None):
            return

        # Run _compile_sub_workflow() to populate _compiled_workflow_cache
        node._compile_sub_workflow(
            prep_res["child_ir"],
            prep_res["workflow_path"],
            prep_res["child_params"],
        )

        logger.debug(
            f"Pre-warmed compile cache for parallel batch node '{config.node_id}'",
            extra={"node_id": config.node_id},
        )
    finally:
        node.params = original_params


def execute_batch(
    node: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    execute_single_fn: Callable,
) -> tuple[str, list[dict]]:
    """Execute a batch node: resolve items, iterate, aggregate results.

    Args:
        node: Bare node instance
        config: NodeConfig with batch_config and template_config
        shared: Parent shared store
        execute_single_fn: Callback (node, config, item_shared) -> (action, last_resolutions, template_errors)

    Returns:
        (action, batch_trace_items)
    """
    batch_config = config.batch_config
    if batch_config is None:
        raise ValueError("execute_batch called without batch_config")

    items = _resolve_and_validate_items(batch_config, shared, config.node_id)

    # Initialize batch trace accumulator
    if "_batch_trace" not in shared:
        shared["_batch_trace"] = {}
    shared["_batch_trace"][config.node_id] = []

    # Ensure __template_errors__ exists so item shallow copies share the reference.
    # Without this, permissive-mode errors written to item_shared via setdefault()
    # create a new dict in the copy — lost when the copy is discarded.
    if "__template_errors__" not in shared:
        shared["__template_errors__"] = {}

    # Execute items
    if not items:
        exec_res: list[dict[str, Any] | None] = []
        errors: list[dict[str, Any]] = []
        item_timings: list[float] = []
    elif batch_config.parallel:
        # Pre-warm compile cache for WorkflowExecutor nodes so deep copies inherit it.
        # Without this, each thread independently compiles the sub-workflow (O(N)).
        # With this, compilation happens once and deep copies get the cached result (O(1)).
        _pre_warm_compile_cache(node, config, shared, execute_single_fn, batch_config, items[0])
        exec_res, errors, item_timings = _execute_parallel(items, node, config, shared, execute_single_fn, batch_config)
    else:
        exec_res, errors, item_timings = _execute_sequential(
            items, node, config, shared, execute_single_fn, batch_config
        )

    action = _aggregate_batch_results(exec_res, errors, item_timings, batch_config, config.node_id, shared)
    batch_trace_items = _collect_batch_trace(shared, config.node_id)
    _push_batch_warnings(shared, exec_res, errors, config.node_id, batch_config)

    # fail_fast: raise AFTER aggregation so shared[node_id] has the partial
    # batch_metadata/errors list that step 17.5 will archive into __failures__.
    if batch_config.error_handling == "fail_fast" and errors:
        first_error = errors[0]
        if first_error.get("exception") is not None:
            raise first_error["exception"]
        raise RuntimeError(
            f"Batch '{config.node_id}' failed at item [{first_error['index']}] "
            f"(value: {first_error['item']!r}): {first_error['error']}"
        )

    return action, batch_trace_items


def _execute_batch_item(
    idx: int,
    item: Any,
    node: Any,
    config: NodeConfig,
    parent_shared: dict[str, Any],
    execute_single_fn: Callable,
    batch_config: BatchConfig,
    item_shared: Optional[dict[str, Any]] = None,
) -> tuple[dict | None, dict | None, float, dict, list]:
    """Execute single batch item with retry. Unified path for seq and parallel.

    Args:
        idx: Item index
        item: The batch item value
        node: Node instance (may be deep-copied for parallel)
        config: NodeConfig
        parent_shared: Parent shared store (for _batch_trace access)
        execute_single_fn: (node, config, item_shared) -> (action, last_resolutions, template_errors)
        batch_config: Batch configuration
        item_shared: Pre-created isolated store (for parallel). None = create here.

    Returns:
        (result, error_info, duration_ms, last_resolutions, template_errors)
    """
    start_time = time.perf_counter()
    last_exception: Exception | None = None
    last_resolutions: dict = {}
    template_errors: list = []

    if item_shared is None:
        item_shared = dict(parent_shared)

    for retry in range(batch_config.max_retries):
        try:
            # Reset namespace for this attempt
            item_shared[config.node_id] = {}
            item_shared[batch_config.item_alias] = item
            item_shared["__index__"] = idx

            # Execute via callback
            action, last_resolutions, template_errors = execute_single_fn(node, config, item_shared)

            # Extract child trace events from WorkflowExecutor (sub-workflow in batch)
            item_child_trace_events: list[dict[str, Any]] | None = getattr(node, "_child_trace_events", None)

            # Normalize result
            raw_result = item_shared.get(config.node_id)
            result = _normalize_result(raw_result)

            # Include original item
            if "item" in result:
                logger.warning(
                    "Batch result already has 'item' key, overwriting with original batch item",
                    extra={"node_id": config.node_id, "existing_item": result["item"]},
                )
            result["item"] = item
            result["original_index"] = idx

            # Check for error in result dict
            error_msg = _extract_error(result)

            # Fallback: detect error via action string
            if not error_msg and isinstance(action, str) and action.startswith("error"):
                error_msg = "Node returned error action"

            duration_ms = (time.perf_counter() - start_time) * 1000
            if error_msg:
                error_info = {"index": idx, "item": item, "error": error_msg, "exception": None}
                _capture_item_trace(
                    parent_shared,
                    config.node_id,
                    item_shared,
                    idx,
                    item,
                    duration_ms,
                    error_info,
                    last_resolutions,
                    child_trace_events=item_child_trace_events,
                )
                return result, error_info, duration_ms, last_resolutions, template_errors

            _capture_item_trace(
                parent_shared,
                config.node_id,
                item_shared,
                idx,
                item,
                duration_ms,
                None,
                last_resolutions,
                child_trace_events=item_child_trace_events,
            )
            return result, None, duration_ms, last_resolutions, template_errors

        except CompilationError:
            raise  # Workflow definition is broken — never swallow, never retry
        except Exception as e:
            last_exception = e
            if retry < batch_config.max_retries - 1:
                if batch_config.retry_wait > 0:
                    time.sleep(batch_config.retry_wait)
                continue
            break

    # All retries exhausted
    duration_ms = (time.perf_counter() - start_time) * 1000
    error_info = {"index": idx, "item": item, "error": str(last_exception), "exception": last_exception}
    _capture_item_trace(
        parent_shared,
        config.node_id,
        item_shared,
        idx,
        item,
        duration_ms,
        error_info,
        last_resolutions,
        child_trace_events=getattr(node, "_child_trace_events", None),
    )
    return None, error_info, duration_ms, last_resolutions, template_errors


def _execute_sequential(
    items: list[Any],
    node: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    execute_single_fn: Callable,
    batch_config: BatchConfig,
) -> tuple[list, list, list]:
    """Execute items sequentially. Returns (results, errors, timings)."""
    results: list[dict[str, Any] | None] = []
    errors: list[dict[str, Any]] = []
    timings: list[float] = []
    total = len(items)

    callback = shared.get("__progress_callback__")
    depth = shared.get("_pflow_depth", 0)

    for idx, item in enumerate(items):
        result, error, duration_ms, _, _ = _execute_batch_item(
            idx, item, node, config, shared, execute_single_fn, batch_config
        )
        results.append(result)
        timings.append(duration_ms)

        _report_batch_progress(callback, config.node_id, duration_ms, depth, idx + 1, total, error is None)

        if error:
            errors.append(error)
            # fail_fast: stop iterating but DO NOT raise here — let
            # execute_batch() call _aggregate_batch_results first so the
            # partial state reaches shared[node_id] and survives into
            # __failures__.
            if batch_config.error_handling == "fail_fast":
                break

    return results, errors, timings


def _report_batch_progress(
    callback: Any,
    node_id: str,
    duration_ms: float,
    depth: int,
    completed: int,
    total: int,
    success: bool,
) -> None:
    """Call batch progress callback if present."""
    if callable(callback):
        with contextlib.suppress(Exception):
            callback(
                node_id,
                "batch_progress",
                duration_ms,
                depth,
                batch_current=completed,
                batch_total=total,
                batch_success=success,
            )


def _drain_worker_buffer(callback: Any, buffered_events: list[tuple[tuple, dict]]) -> None:
    """Drain a worker's buffered progress events through the real callback.

    Called from the main thread inside ``_collect_parallel_results``. Each
    worker accumulates its sub-workflow's child engine events into a
    per-thread buffer; this helper plays them back through the real
    ``OutputController`` callback as one atomic block per item.
    Single-threaded by construction (only the main thread reaches here,
    one item at a time via ``as_completed``), so the OutputController
    never sees concurrent calls and each item's transcript renders as a
    coherent contiguous block.

    Suppression matches the patterns in ``instrumentation.py``
    (``call_start_callback`` etc.) so a rendering exception cannot crash
    workflow execution.

    **Memory scaling**: per-worker buffer size is O(events_per_item). Total
    peak buffer usage is O(events_per_item x max_concurrent) across all
    active workers. For typical batches (4-16 items x 5-20 child nodes
    per sub-workflow, ~4 events per node) this is a few thousand tuples,
    negligible. Pathological workloads with thousands of child nodes per
    item would see proportional growth. If this becomes a real concern
    in practice, introduce ``_MAX_BUFFERED_EVENTS_PER_ITEM`` with a
    drop-and-warn fallback that records the drop in ``shared["__warnings__"]``
    so agents can still see that output was truncated. Not implemented
    today — no known workload hits the limit, and a silent drop would be
    worse than the current unbounded-but-small behavior.
    """
    if not buffered_events or not callable(callback):
        return
    for args, kwargs in buffered_events:
        with contextlib.suppress(Exception):
            callback(*args, **kwargs)


def _collect_parallel_results(
    future_to_idx: dict,
    items: list[Any],
    results: list,
    timings: list,
    pending_errors: list,
    config: NodeConfig,
    batch_config: BatchConfig,
    callback: Any,
    depth: int,
) -> None:
    """Collect results from parallel futures as they complete.

    Modifies results, timings, pending_errors in place. Drains each
    worker's buffered progress events (see ``_drain_worker_buffer``)
    before reporting batch progress, producing atomic per-item
    transcripts in completion order.
    """
    should_stop = False
    completed_count = 0
    total = len(future_to_idx)

    for future in as_completed(future_to_idx):
        try:
            idx, result, error, duration_ms, buffered_events = future.result()
            results[idx] = result
            timings[idx] = duration_ms
            completed_count += 1

            _drain_worker_buffer(callback, buffered_events)
            _report_batch_progress(callback, config.node_id, duration_ms, depth, completed_count, total, error is None)

            if error:
                pending_errors.append(error)
                if batch_config.error_handling == "fail_fast" and not should_stop:
                    should_stop = True
                    for f in future_to_idx:
                        f.cancel()

        except CompilationError:
            raise
        except Exception as e:
            idx = future_to_idx[future]
            pending_errors.append({
                "index": idx,
                "item": items[idx],
                "error": f"Executor error: {e}",
                "exception": e,
            })
            timings[idx] = 0.0
            completed_count += 1
            _report_batch_progress(callback, config.node_id, 0.0, depth, completed_count, total, False)
            if batch_config.error_handling == "fail_fast" and not should_stop:
                should_stop = True
                for f in future_to_idx:
                    f.cancel()


def _execute_parallel(
    items: list[Any],
    node: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    execute_single_fn: Callable,
    batch_config: BatchConfig,
) -> tuple[list, list, list]:
    """Execute items in parallel. Returns (results, errors, timings)."""
    results: list[dict[str, Any] | None] = [None] * len(items)
    timings: list[float] = [0.0] * len(items)
    pending_errors: list[dict[str, Any]] = []

    callback = shared.get("__progress_callback__")
    depth = shared.get("_pflow_depth", 0)

    def process_item(
        idx: int, item: Any
    ) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None, float, list[tuple[tuple, dict]]]:
        """Process single item in thread.

        Buffers progress callback events from the sub-workflow's child engine
        into a per-thread list. Events accumulate locally with no shared
        state contention. The main thread drains the list through the real
        callback when this future completes (see ``_collect_parallel_results``)
        so each item's child node transcript renders as one atomic block.

        This preserves per-child node visibility, smart-handled tags,
        warnings, and cache-hit indicators in the live progress stream
        while avoiding races on the shared ``OutputController`` state that
        would otherwise occur when multiple worker threads concurrently
        fire ``node_start``/``node_complete`` events from a sub-workflow's
        child engine.
        """
        # THREADING: shallow copy — nested dicts (_batch_trace, __execution__)
        # are shared across threads. Writes to nested keys are GIL-protected (CPython).
        item_shared = dict(shared)
        item_shared[config.node_id] = {}
        item_shared[batch_config.item_alias] = item
        item_shared["__index__"] = idx

        # Replace the inherited progress callback with a per-worker buffer.
        # The sub-workflow's child engine will fire its events into this
        # buffer instead of touching the shared OutputController. The main
        # thread drains the buffer atomically when the future completes.
        buffered_events: list[tuple[tuple, dict]] = []
        if callable(callback):

            def buffer_callback(*args: Any, **kwargs: Any) -> None:
                buffered_events.append((args, kwargs))

            item_shared["__progress_callback__"] = buffer_callback

        thread_node = copy.deepcopy(node)

        result, error, duration_ms, _, _ = _execute_batch_item(
            idx,
            item,
            thread_node,
            config,
            shared,
            execute_single_fn,
            batch_config,
            item_shared=item_shared,
        )
        return idx, result, error, duration_ms, buffered_events

    pool = ThreadPoolExecutor(max_workers=batch_config.max_concurrent)
    try:
        future_to_idx = {pool.submit(process_item, idx, item): idx for idx, item in enumerate(items)}
        _collect_parallel_results(
            future_to_idx,
            items,
            results,
            timings,
            pending_errors,
            config,
            batch_config,
            callback,
            depth,
        )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    # fail_fast: DO NOT raise here — let execute_batch() call
    # _aggregate_batch_results first so the partial state reaches
    # shared[node_id] and survives into __failures__.
    return results, pending_errors, timings


def _normalize_result(result: Any) -> dict[str, Any]:
    """Normalize node output to a dict."""
    if result is None:
        return {}
    if not isinstance(result, dict):
        return {"value": result}
    return result


def _extract_error(result: Any) -> str | None:
    """Extract error message from result dict if present."""
    if not isinstance(result, dict):
        return None
    error = result.get("error")
    if error:
        return str(error)
    return None


def _capture_item_trace(
    parent_shared: dict[str, Any],
    node_id: str,
    item_shared: dict[str, Any],
    idx: int,
    item: Any,
    duration_ms: float,
    error: dict[str, Any] | None,
    last_resolutions: dict,
    child_trace_events: list[dict[str, Any]] | None = None,
) -> None:
    """Capture per-item trace event. Appends to parent_shared._batch_trace."""
    trace_list = parent_shared.get("_batch_trace", {}).get(node_id)
    if trace_list is None:
        return

    item_event: dict[str, Any] = {
        "index": idx,
        "item": item,
        "success": error is None,
        "duration_ms": round(duration_ms, 2) if duration_ms else 0,
    }
    if error:
        item_event["error"] = error.get("error", str(error))

    # Capture item's node output
    node_output = item_shared.get(node_id)
    if isinstance(node_output, dict):
        item_event["node_output"] = dict(node_output)

    # Template resolutions — received directly, no chain traversal
    if last_resolutions:
        item_event["template_resolutions"] = last_resolutions

    # LLM data from item output
    if isinstance(node_output, dict):
        llm_usage = node_output.get("llm_usage")
        if isinstance(llm_usage, dict):
            item_event["llm_call"] = llm_usage
        for src_key, dst_key in [("response", "llm_response"), ("prompt", "llm_prompt")]:
            value = node_output.get(src_key)
            if isinstance(value, str):
                item_event[dst_key] = value

    # Sub-workflow trace events (from WorkflowExecutor batch items).
    # Stored as "events" so collect_llm_calls() can recurse into them.
    if child_trace_events:
        item_event["events"] = child_trace_events

    trace_list.append(item_event)  # GIL-protected for parallel


def _aggregate_batch_results(
    exec_res: list[dict[str, Any] | None],
    errors: list[dict[str, Any]],
    item_timings: list[float],
    batch_config: BatchConfig,
    node_id: str,
    shared: dict[str, Any],
) -> str:
    """Aggregate batch results into shared store. Returns action string.

    On all-failed abort: writes the aggregated state to ``shared[node_id]``
    BEFORE raising so step 17.5 in ``engine._execute_node`` captures the full
    ``batch_metadata`` / ``errors`` list into ``__failures__[node_id].data``.
    Without this, ``build_execution_steps`` could not surface batch error
    details for the failing batch node (spec acceptance criterion).
    """
    # Filter results to successes only — errors list is the authoritative failure record.
    # Using error_indices (not _extract_error) fixes the error-via-action edge case where
    # the result dict has no "error" key but IS in the errors list.
    error_indices = {e["index"] for e in errors}
    successful_results = [r for idx, r in enumerate(exec_res) if idx not in error_indices]
    success_count = len(successful_results)

    # Timing stats — computed once, used by both the normal and error path
    timing_stats: dict[str, float] | None = None
    if item_timings:
        timing_stats = {
            "total_items_ms": round(sum(item_timings), 2),
            "avg_item_ms": round(sum(item_timings) / len(item_timings), 2),
            "min_item_ms": round(min(item_timings), 2),
            "max_item_ms": round(max(item_timings), 2),
        }

    # Write to shared store — results contains only successful items.
    # errors list is the authoritative record of failures (with index, item, error).
    # Happens BEFORE any abort-raise so the failure archive captures the data.
    shared[node_id] = {
        "results": successful_results,
        "count": len(exec_res),
        "success_count": success_count,
        "error_count": len(errors),
        "errors": errors if errors else None,
        "batch_metadata": {
            "parallel": batch_config.parallel,
            "max_concurrent": batch_config.max_concurrent if batch_config.parallel else None,
            "max_retries": batch_config.max_retries,
            "retry_wait": batch_config.retry_wait if batch_config.retry_wait > 0 else None,
            "execution_mode": "parallel" if batch_config.parallel else "sequential",
            "timing": timing_stats,
        },
    }

    # All items failed -> abort. Raised AFTER the shared store write so
    # step 17.5's mark_node_failed captures the rich batch metadata.
    if batch_config.error_handling == "continue" and success_count == 0 and errors:
        error_summary = "; ".join(f"[{e['index']}] {e['error']}" for e in errors[:3])
        if len(errors) > 3:
            error_summary += f" (+{len(errors) - 3} more)"
        raise RuntimeError(
            f"Batch '{node_id}': all {len(errors)} items failed, "
            f"no successful results to continue with. Errors: {error_summary}"
        )

    return "default"


def _detect_empty_output_items(
    exec_res: list[dict[str, Any] | None],
    errors: list[dict[str, Any]],
) -> list[int]:
    """Find batch items that succeeded but produced empty output."""
    error_indices = {e["index"] for e in errors if "index" in e}
    empty: list[int] = []
    for idx, result in enumerate(exec_res):
        if result is None or idx in error_indices:
            continue
        if not isinstance(result, dict):
            continue
        if result.get("error"):
            continue
        has_content = False
        for key, val in result.items():
            if key in _BATCH_META_KEYS or key.startswith("_"):
                continue
            if val is not None and val != "" and val != [] and val != {}:
                has_content = True
                break
        if not has_content:
            empty.append(idx)
    return empty


def _push_batch_warnings(
    shared: dict[str, Any],
    exec_res: list,
    errors: list,
    node_id: str,
    batch_config: BatchConfig,
) -> None:
    """Push warnings for DEGRADED status when batch had issues."""
    empty_indices = _detect_empty_output_items(exec_res, errors)

    # Under --only, suppress empty-output warnings workflow-wide. The common
    # case is that the target sub-workflow batch has empty items because the
    # child's declared outputs couldn't resolve against skipped nodes. A rare
    # false negative: an upstream batch (not the target) with legitimately
    # empty items would also have its warning suppressed here. Scoping to the
    # target subtree requires threading the target node id into the batch
    # executor; the complexity isn't worth it for a debugging-mode flag.
    only_node = shared.get("__execution__", {}).get("only_node")
    if only_node:
        empty_indices = []

    warning_parts: list[str] = []
    if not exec_res:
        warning_parts.append("0 items to process (input list was empty)")
    if batch_config.error_handling == "continue" and errors:
        warning_parts.append(f"{len(errors)} error(s) out of {len(exec_res)} items")
    if empty_indices:
        indices_str = ", ".join(str(i) for i in empty_indices[:5])
        if len(empty_indices) > 5:
            indices_str += f" (+{len(empty_indices) - 5} more)"
        warning_parts.append(f"{len(empty_indices)} item(s) produced empty output (items {indices_str})")

    if warning_parts:
        if "__warnings__" not in shared:
            shared["__warnings__"] = {}
        shared["__warnings__"][node_id] = f"Batch '{node_id}': " + "; ".join(warning_parts)
