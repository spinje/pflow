"""Batch processing node with sequential and parallel execution.

This module provides PflowBatchNode, which wraps any pflow node to process
multiple items. Supports both sequential and parallel execution modes.

Key Design Decisions:
- **Inherits from Node (not BatchNode)**: Cleaner design, avoids MRO tricks
- **Thread-safe retry**: Uses local `retry` variable instead of `self.cur_retry`
- **Deep copy for parallel**: Each thread gets its own node chain copy to avoid
  TemplateAwareNodeWrapper race condition on `inner_node.params`
- **Isolated context per item**: Each item gets `item_shared = dict(shared)`

IR Syntax:
    ```json
    {
      "id": "summarize",
      "type": "llm",
      "batch": {
        "items": "${list_files.files}",
        "as": "file",
        "parallel": true,
        "max_concurrent": 5,
        "max_retries": 3,
        "retry_wait": 1.0,
        "error_handling": "continue"
      },
      "params": {"prompt": "Summarize: ${file}"}
    }
    ```

Output Structure:
    ```python
    shared["summarize"] = {
        "results": [...],      # Array of results in input order
        "count": 3,            # Total items processed
        "success_count": 2,    # Items without errors
        "error_count": 1,      # Items with errors
        "errors": [...],       # Error details (or None if no errors)
        "batch_metadata": {    # Execution metadata for tracing/debugging
            "parallel": True,
            "max_concurrent": 5,    # Only when parallel=True
            "max_retries": 3,
            "retry_wait": 1.0,      # Only when > 0
            "execution_mode": "parallel",
            "timing": {
                "total_items_ms": 234.56,
                "avg_item_ms": 78.19,
                "min_item_ms": 45.23,
                "max_item_ms": 123.45,
            },
        },
    }
    ```

Thread Safety:
    - Sequential mode: Single-threaded, no concerns
    - Parallel mode:
      - Each thread gets deep copy of node chain (isolates TemplateAwareNodeWrapper)
      - Shallow copy of shared store (shares __llm_calls__ list, GIL-protected)
      - Local retry counter (avoids self.cur_retry race condition)
"""

import contextlib
import copy
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from pflow.runtime.template_resolver import TemplateResolver
from pocketflow import Node

logger = logging.getLogger(__name__)


class PflowBatchNode(Node):
    """Batch node using PocketFlow's prep/exec/post lifecycle with isolated contexts.

    This class wraps any pflow node to process multiple items. Each item gets an
    isolated shallow copy of the shared store, ensuring items don't pollute each
    other while preserving references to mutable tracking objects like `__llm_calls__`.

    Inherits from Node directly (not BatchNode) to avoid the `self.cur_retry` race
    condition in parallel execution. Implements thread-safe retry with local variables.

    Attributes:
        inner_node: The wrapped node to execute for each item
        node_id: Node identifier for namespacing outputs
        items_template: Template string to resolve items array (e.g., "${node.files}")
        item_alias: Variable name for current item in templates (default: "item")
        error_handling: Error mode - "fail_fast" or "continue"
        parallel: Whether to execute items concurrently (default: False)
        max_concurrent: Maximum concurrent workers when parallel=True (default: 10)
        max_retries: Maximum retry attempts per item (default: 1, no retry)
        retry_wait: Seconds to wait between retries (default: 0)
    """

    def __init__(self, inner_node: Any, node_id: str, batch_config: dict[str, Any]):
        """Initialize batch node wrapper.

        Args:
            inner_node: The wrapped pflow node (already wrapped with Template/Namespace)
            node_id: Unique identifier for this node (used for namespacing results)
            batch_config: Batch configuration dict with keys:
                - items (required): Template reference to items array
                - as (optional): Variable name for current item (default: "item")
                - error_handling (optional): "fail_fast" or "continue" (default: "fail_fast")
                - parallel (optional): Enable concurrent execution (default: False)
                - max_concurrent (optional): Max workers when parallel (default: 10)
                - max_retries (optional): Max retry attempts per item (default: 1)
                - retry_wait (optional): Seconds between retries (default: 0)
        """
        super().__init__()  # Initialize params, successors from BaseNode
        self.inner_node = inner_node
        self.node_id = node_id

        # Batch configuration
        self.items_template = batch_config["items"]
        self.item_alias = batch_config.get("as", "item")
        self.error_handling = batch_config.get("error_handling", "fail_fast")

        # Phase 2: Parallel execution config (with type coercion for robustness)
        self.parallel = self._coerce_bool(batch_config.get("parallel", False), "parallel", default=False)
        self.max_concurrent = self._coerce_int(batch_config.get("max_concurrent", 10), "max_concurrent", default=10)
        self.max_retries = self._coerce_int(batch_config.get("max_retries", 1), "max_retries", default=1)
        self.retry_wait = self._coerce_float(batch_config.get("retry_wait", 0), "retry_wait", default=0.0)

        # Instance state for current batch execution
        self._shared: dict[str, Any] = {}
        self._errors: list[dict[str, Any]] = []
        self._item_timings: list[float] = []  # Per-item execution times in ms

    def _coerce_bool(self, value: Any, field: str, default: bool) -> bool:
        """Coerce value to boolean with proper string handling.

        Handles JSON-style boolean strings ("true"/"false") correctly,
        unlike Python's bool() which treats any non-empty string as True.
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lower = value.lower().strip()
            if lower in ("true", "1", "yes"):
                logger.warning(
                    f"Batch config '{field}' is string '{value}', coercing to True. "
                    "Use boolean type in IR for correctness.",
                    extra={"node_id": self.node_id, "field": field, "value": value},
                )
                return True
            if lower in ("false", "0", "no", ""):
                logger.warning(
                    f"Batch config '{field}' is string '{value}', coercing to False. "
                    "Use boolean type in IR for correctness.",
                    extra={"node_id": self.node_id, "field": field, "value": value},
                )
                return False
            # Unknown string - log and use default
            logger.warning(
                f"Batch config '{field}' has invalid string '{value}', using default {default}",
                extra={"node_id": self.node_id, "field": field, "value": value},
            )
            return default
        # Other types (int, etc.) - use Python's truthiness
        return bool(value)

    def _coerce_int(self, value: Any, field: str, default: int) -> int:
        """Coerce value to integer with warning on type mismatch."""
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                result = int(value)
                logger.warning(
                    f"Batch config '{field}' is string '{value}', coercing to {result}. "
                    "Use integer type in IR for correctness.",
                    extra={"node_id": self.node_id, "field": field, "value": value},
                )
                return result
            except ValueError:
                logger.warning(
                    f"Batch config '{field}' has invalid value '{value}', using default {default}",
                    extra={"node_id": self.node_id, "field": field, "value": value},
                )
                return default
        return default

    def _coerce_float(self, value: Any, field: str, default: float) -> float:
        """Coerce value to float with warning on type mismatch."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                result = float(value)
                logger.warning(
                    f"Batch config '{field}' is string '{value}', coercing to {result}. "
                    "Use numeric type in IR for correctness.",
                    extra={"node_id": self.node_id, "field": field, "value": value},
                )
                return result
            except ValueError:
                logger.warning(
                    f"Batch config '{field}' has invalid value '{value}', using default {default}",
                    extra={"node_id": self.node_id, "field": field, "value": value},
                )
                return default
        return default

    def set_params(self, params: dict[str, Any]) -> None:
        """Forward params to inner node chain.

        This is critical: params must reach the TemplateAwareNodeWrapper
        so template variables like ${item} can be properly resolved at runtime.
        """
        super().set_params(params)  # Store on self for any direct access
        if hasattr(self.inner_node, "set_params"):
            self.inner_node.set_params(params)

    def prep(self, shared: dict[str, Any]) -> list[Any]:
        """Resolve items template and return items list.

        Args:
            shared: The workflow's shared store

        Returns:
            List of items to process

        Raises:
            ValueError: If items template doesn't resolve to a list
        """
        # Store shared reference for use in _exec methods
        self._shared = shared

        # Ensure __llm_calls__ exists before batch execution starts.
        # This is critical: shallow copy in item contexts will share this list reference,
        # allowing _capture_item_llm_usage to append LLM usage data that persists
        # after each item's context is discarded.
        if "__llm_calls__" not in shared:
            shared["__llm_calls__"] = []

        # Handle inline array vs template reference
        if isinstance(self.items_template, list):
            # Inline array - resolve templates inside each element
            # Task 103's resolve_nested() preserves types in nested structures
            items = TemplateResolver.resolve_nested(self.items_template, shared)
        else:
            # Template reference - extract variable path: "${x.y}" -> "x.y"
            var_path = self.items_template.strip()[2:-1]
            items = TemplateResolver.resolve_value(var_path, shared)

            # Auto-parse JSON strings (enables shell → batch patterns)
            # Shell nodes output text; if that text is valid JSON array, parse it
            if isinstance(items, str):
                trimmed = items.strip()  # Handle shell output newlines

                # Security: Prevent memory exhaustion from large JSON
                MAX_JSON_SIZE = 10 * 1024 * 1024  # 10MB limit
                if len(trimmed) > MAX_JSON_SIZE:
                    logger.warning(
                        f"Batch items string is {len(trimmed)} bytes, "
                        f"exceeding {MAX_JSON_SIZE} byte limit. Keeping as string.",
                        extra={"node_id": self.node_id, "size": len(trimmed)},
                    )
                elif trimmed.startswith("["):  # Quick check: looks like JSON array?
                    try:
                        parsed = json.loads(trimmed)
                        if isinstance(parsed, list):
                            items = parsed
                            logger.debug(
                                "Auto-parsed JSON string to list for batch.items",
                                extra={"node_id": self.node_id, "item_count": len(items)},
                            )
                    except (json.JSONDecodeError, ValueError):
                        # Not valid JSON - will fail at type check with clear error
                        logger.debug(
                            "Failed to parse batch.items as JSON, keeping as string",
                            extra={"node_id": self.node_id},
                        )

        if items is None:
            raise ValueError(
                f"Batch items template '{self.items_template}' resolved to None. "
                f"Ensure the referenced node output exists."
            )

        if not isinstance(items, list):
            raise TypeError(
                f"Batch items must be an array, got {type(items).__name__}. "
                f"Template '{self.items_template}' resolved to: {items!r}"
            )

        logger.debug(
            f"Batch node '{self.node_id}' processing {len(items)} items",
            extra={"node_id": self.node_id, "item_count": len(items)},
        )

        return items

    def _extract_error(self, result: Any) -> str | None:
        """Extract error message from result dict if present.

        Nodes signal errors in two ways:
        1. Exceptions (caught by retry logic)
        2. Error key in result dict (e.g., {"error": "Could not read file..."})

        Args:
            result: The result from execution - typically a dict containing node outputs

        Returns:
            Error message string if error detected, None otherwise
        """
        if not isinstance(result, dict):
            return None
        error = result.get("error")
        if error:
            return str(error)
        return None

    def _capture_item_llm_usage(self, item_shared: dict[str, Any], idx: int) -> None:
        """Capture llm_usage from item context and append to shared __llm_calls__.

        When batch executes an inner LLM node, the node writes llm_usage to the
        item's isolated context. This method captures that data before the context
        is discarded, appending it to the shared __llm_calls__ list for cost tracking.

        Args:
            item_shared: The isolated shared store for this batch item
            idx: The index of this item in the batch (for tracing)
        """
        llm_usage = None

        # Check root level (for non-namespaced inner nodes)
        if "llm_usage" in item_shared:
            llm_usage = item_shared["llm_usage"]
        # Check namespaced location (when inner node uses namespacing)
        elif self.node_id in item_shared and isinstance(item_shared[self.node_id], dict):
            llm_usage = item_shared[self.node_id].get("llm_usage")

        if llm_usage and isinstance(llm_usage, dict):
            # Copy the usage data and add batch context
            llm_call_data = llm_usage.copy()
            llm_call_data["node_id"] = self.node_id
            llm_call_data["batch_item_index"] = idx

            # Append to shared __llm_calls__ list (GIL-protected for thread safety)
            llm_calls = self._shared.get("__llm_calls__")
            if isinstance(llm_calls, list):
                llm_calls.append(llm_call_data)

    def _exec_single(self, idx: int, item: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None, float]:
        """Execute single item with thread-safe retry logic.

        Uses local `retry` variable instead of `self.cur_retry` to avoid race conditions
        when multiple threads execute concurrently.

        Args:
            idx: Index of item in original list (for error reporting)
            item: The item to process

        Returns:
            Tuple of (result, error_info, duration_ms):
            - On success: (result_dict, None, duration_ms)
            - On error: (None or partial_result, {"index": idx, "item": item, "error": str, "exception": Exception|None}, duration_ms)
        """
        start_time = time.perf_counter()
        last_exception: Exception | None = None

        for retry in range(self.max_retries):
            try:
                # Create isolated context for this item
                item_shared = dict(self._shared)
                item_shared[self.node_id] = {}
                item_shared[self.item_alias] = item

                # Execute inner node
                self.inner_node._run(item_shared)

                # Capture LLM usage from item context before it's discarded
                self._capture_item_llm_usage(item_shared, idx)

                # Capture result from inner node's namespace
                result = item_shared.get(self.node_id)
                if result is None:
                    result = {}
                elif not isinstance(result, dict):
                    result = {"value": result}

                # Check for error in result dict
                error_msg = self._extract_error(result)
                duration_ms = (time.perf_counter() - start_time) * 1000
                if error_msg:
                    # Error in result dict - no exception to preserve
                    return (result, {"index": idx, "item": item, "error": error_msg, "exception": None}, duration_ms)

                return (result, None, duration_ms)

            except Exception as e:
                last_exception = e
                if retry < self.max_retries - 1:
                    if self.retry_wait > 0:
                        time.sleep(self.retry_wait)
                    logger.debug(
                        f"Batch item {idx} retry {retry + 1}/{self.max_retries}: {e}",
                        extra={
                            "node_id": self.node_id,
                            "item_index": idx,
                            "retry": retry + 1,
                        },
                    )
                    continue
                break

        # All retries exhausted - store the original exception for fail_fast re-raise
        duration_ms = (time.perf_counter() - start_time) * 1000
        return (
            None,
            {"index": idx, "item": item, "error": str(last_exception), "exception": last_exception},
            duration_ms,
        )

    def _exec_single_with_node(
        self, idx: int, item: Any, item_shared: dict[str, Any], thread_node: Any
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, float]:
        """Execute single item with provided node (for parallel execution with deep copy).

        This is similar to _exec_single() but uses a pre-created isolated shared store
        and a deep-copied node chain. Used by _exec_parallel() to avoid race conditions.

        Args:
            idx: Index of item in original list (for error reporting)
            item: The item to process
            item_shared: Pre-created isolated shared store for this item
            thread_node: Deep-copied node chain for thread isolation

        Returns:
            Tuple of (result, error_info, duration_ms)
        """
        start_time = time.perf_counter()
        last_exception: Exception | None = None

        for retry in range(self.max_retries):
            try:
                # Reset namespace for this retry (matches _exec_single behavior)
                # This ensures partial writes from failed attempts don't persist
                item_shared[self.node_id] = {}

                # Execute the thread-local node copy
                thread_node._run(item_shared)

                # Capture LLM usage from item context before it's discarded
                # Note: self._capture_item_llm_usage appends to self._shared["__llm_calls__"]
                # which is the same list object referenced by item_shared (shallow copy)
                self._capture_item_llm_usage(item_shared, idx)

                # Capture result from node's namespace
                result = item_shared.get(self.node_id)
                if result is None:
                    result = {}
                elif not isinstance(result, dict):
                    result = {"value": result}

                # Check for error in result dict
                error_msg = self._extract_error(result)
                duration_ms = (time.perf_counter() - start_time) * 1000
                if error_msg:
                    return (result, {"index": idx, "item": item, "error": error_msg, "exception": None}, duration_ms)

                return (result, None, duration_ms)

            except Exception as e:
                last_exception = e
                if retry < self.max_retries - 1:
                    if self.retry_wait > 0:
                        time.sleep(self.retry_wait)
                    logger.debug(
                        f"Batch item {idx} retry {retry + 1}/{self.max_retries}: {e}",
                        extra={
                            "node_id": self.node_id,
                            "item_index": idx,
                            "retry": retry + 1,
                        },
                    )
                    continue
                break

        duration_ms = (time.perf_counter() - start_time) * 1000
        return (
            None,
            {"index": idx, "item": item, "error": str(last_exception), "exception": last_exception},
            duration_ms,
        )

    def _exec_sequential(self, items: list[Any]) -> list[dict[str, Any] | None]:
        """Execute items sequentially using _exec_single.

        Args:
            items: List of items to process

        Returns:
            List of results in same order as input
        """
        results: list[dict[str, Any] | None] = []
        total = len(items)

        # Get progress callback from shared store for batch progress reporting
        callback = self._shared.get("__progress_callback__")
        depth = self._shared.get("_pflow_depth", 0)

        for idx, item in enumerate(items):
            result, error, duration_ms = self._exec_single(idx, item)
            results.append(result)
            self._item_timings.append(duration_ms)

            # Report batch progress after each item
            if callable(callback):
                with contextlib.suppress(Exception):
                    callback(
                        self.node_id,
                        "batch_progress",
                        duration_ms,
                        depth,
                        batch_current=idx + 1,
                        batch_total=total,
                        batch_success=(error is None),
                    )

            if error:
                self._errors.append(error)
                if self.error_handling == "fail_fast":
                    # Re-raise original exception if available, otherwise wrap in RuntimeError
                    if error.get("exception") is not None:
                        raise error["exception"]
                    else:
                        raise RuntimeError(f"Batch '{self.node_id}' failed at item [{idx}]: {error['error']}")

        return results

    def _exec(self, items: list[Any]) -> list[dict[str, Any] | None]:
        """Execute batch processing - dispatches to sequential or parallel.

        Args:
            items: List of items from prep()

        Returns:
            List of results in same order as input
        """
        self._errors = []
        self._item_timings = []

        if not items:
            return []

        if self.parallel:
            logger.debug(
                f"Batch node '{self.node_id}' executing {len(items)} items in parallel "
                f"(max_concurrent={self.max_concurrent})",
                extra={
                    "node_id": self.node_id,
                    "parallel": True,
                    "max_concurrent": self.max_concurrent,
                },
            )
            return self._exec_parallel(items)
        else:
            logger.debug(
                f"Batch node '{self.node_id}' executing {len(items)} items sequentially",
                extra={"node_id": self.node_id, "parallel": False},
            )
            return self._exec_sequential(items)

    def _collect_parallel_results(  # noqa: C901
        self,
        future_to_idx: dict,
        items: list[Any],
        results: list,
        timings: list,
        pending_errors: list,
        should_stop: bool,
    ) -> bool:
        """Collect results from parallel futures as they complete.

        Args:
            future_to_idx: Mapping of futures to item indices
            items: Original items list (for error reporting)
            results: Results list to populate (modified in place)
            timings: Timings list to populate (modified in place)
            pending_errors: Errors list to populate (modified in place)
            should_stop: Whether we're already stopping

        Returns:
            Updated should_stop flag
        """
        # Get progress callback for batch progress reporting
        callback = self._shared.get("__progress_callback__")
        depth = self._shared.get("_pflow_depth", 0)
        total = len(future_to_idx)
        completed_count = 0

        for future in as_completed(future_to_idx):
            if should_stop:
                # Already stopping, just collect remaining results
                try:
                    idx, result, error, duration_ms = future.result()
                    results[idx] = result
                    timings[idx] = duration_ms
                    completed_count += 1
                    if error:
                        pending_errors.append(error)
                    # Still report progress even when stopping
                    if callable(callback):
                        with contextlib.suppress(Exception):
                            callback(
                                self.node_id,
                                "batch_progress",
                                duration_ms,
                                depth,
                                batch_current=completed_count,
                                batch_total=total,
                                batch_success=(error is None),
                            )
                except Exception as e:
                    logger.debug(f"Exception collecting result during stop: {e}")
                    completed_count += 1
                continue

            try:
                idx, result, error, duration_ms = future.result()
                results[idx] = result
                timings[idx] = duration_ms
                completed_count += 1

                # Report batch progress after each item completes
                if callable(callback):
                    with contextlib.suppress(Exception):
                        callback(
                            self.node_id,
                            "batch_progress",
                            duration_ms,
                            depth,
                            batch_current=completed_count,
                            batch_total=total,
                            batch_success=(error is None),
                        )

                if error:
                    pending_errors.append(error)
                    if self.error_handling == "fail_fast":
                        should_stop = True
                        for f in future_to_idx:
                            f.cancel()

            except Exception as e:
                idx = future_to_idx[future]
                pending_errors.append({
                    "index": idx,
                    "item": items[idx],
                    "error": f"Executor error: {e}",
                    "exception": e,
                })
                # For executor errors, we don't have timing - use 0
                timings[idx] = 0.0
                completed_count += 1
                # Report progress for executor errors too
                if callable(callback):
                    with contextlib.suppress(Exception):
                        callback(
                            self.node_id,
                            "batch_progress",
                            0.0,
                            depth,
                            batch_current=completed_count,
                            batch_total=total,
                            batch_success=False,
                        )
                if self.error_handling == "fail_fast":
                    should_stop = True
                    for f in future_to_idx:
                        f.cancel()

        return should_stop

    def _exec_parallel(self, items: list[Any]) -> list[dict[str, Any] | None]:
        """Execute items in parallel using ThreadPoolExecutor.

        Each thread gets:
        - Shallow copy of shared store (shares __llm_calls__ list for tracking)
        - Deep copy of node chain (avoids TemplateAwareNodeWrapper race condition)

        The deep copy is critical: TemplateAwareNodeWrapper mutates inner_node.params
        during execution. Without isolation, threads would overwrite each other's params.

        Args:
            items: List of items to process

        Returns:
            List of results in same order as input (preserves ordering)

        Note:
            fail_fast cancellation only prevents new items from starting.
            Already-running items will complete (LLM/HTTP calls can't be interrupted).
        """
        results: list[dict[str, Any] | None] = [None] * len(items)
        timings: list[float] = [0.0] * len(items)
        pending_errors: list[dict[str, Any]] = []
        should_stop = False

        def process_item(idx: int, item: Any) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None, float]:
            """Process single item in thread. Returns (index, result, error, duration_ms)."""
            # Create isolated shared store (shallow copy shares __llm_calls__)
            item_shared = dict(self._shared)
            item_shared[self.node_id] = {}
            item_shared[self.item_alias] = item

            # CRITICAL: Deep copy node chain to avoid TemplateAwareNodeWrapper race condition
            # Each thread gets its own copy of the wrapper chain
            thread_node = copy.deepcopy(self.inner_node)

            # Execute with thread-local node
            result, error, duration_ms = self._exec_single_with_node(idx, item, item_shared, thread_node)
            return (idx, result, error, duration_ms)

        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            # Submit all items
            future_to_idx = {executor.submit(process_item, idx, item): idx for idx, item in enumerate(items)}

            # Collect results as they complete
            should_stop = self._collect_parallel_results(
                future_to_idx, items, results, timings, pending_errors, should_stop
            )

        # Store timings for batch metadata
        self._item_timings = timings

        # Merge errors (single-threaded, safe)
        self._errors.extend(pending_errors)

        # Raise first error if fail_fast mode
        if self.error_handling == "fail_fast" and pending_errors:
            first_error = pending_errors[0]
            if first_error.get("exception") is not None:
                raise first_error["exception"]
            else:
                raise RuntimeError(
                    f"Batch '{self.node_id}' failed at item [{first_error['index']}]: {first_error['error']}"
                )

        return results

    def exec(self, prep_res: Any) -> Any:
        """Execute method required by Node interface.

        Note: This is not used by our implementation. We override _exec() directly
        to handle the full batch processing logic. This stub exists to satisfy
        the Node interface if called directly.
        """
        # This should not be called - we override _exec() for batch processing
        raise NotImplementedError(
            "PflowBatchNode.exec() should not be called directly. Use _run() or _exec() for batch processing."
        )

    def post(self, shared: dict[str, Any], prep_res: list, exec_res: list) -> str:
        """Aggregate results into shared store.

        Counts successes by excluding:
        - None results (from exceptions with continue mode)
        - Results with error key (from nodes that wrote errors)

        Args:
            shared: The workflow's shared store
            prep_res: Items list from prep() (unused here but part of PocketFlow interface)
            exec_res: List of results from _exec()

        Returns:
            Action string ("default") for flow control
        """
        # Count successes: non-None results without error keys
        success_count = sum(1 for r in exec_res if r is not None and not self._extract_error(r))

        # Calculate timing statistics
        timing_stats: dict[str, float] | None = None
        if self._item_timings:
            timing_stats = {
                "total_items_ms": round(sum(self._item_timings), 2),
                "avg_item_ms": round(sum(self._item_timings) / len(self._item_timings), 2),
                "min_item_ms": round(min(self._item_timings), 2),
                "max_item_ms": round(max(self._item_timings), 2),
            }

        # Write aggregated results to shared store
        shared[self.node_id] = {
            "results": exec_res,
            "count": len(exec_res),
            "success_count": success_count,
            "error_count": len(self._errors),
            "errors": self._errors if self._errors else None,
            # Batch execution metadata for tracing/debugging
            "batch_metadata": {
                "parallel": self.parallel,
                "max_concurrent": self.max_concurrent if self.parallel else None,
                "max_retries": self.max_retries,
                "retry_wait": self.retry_wait if self.retry_wait > 0 else None,
                "execution_mode": "parallel" if self.parallel else "sequential",
                "timing": timing_stats,
            },
        }

        logger.debug(
            f"Batch node '{self.node_id}' completed: {success_count}/{len(exec_res)} successful",
            extra={
                "node_id": self.node_id,
                "success_count": success_count,
                "error_count": len(self._errors),
                "parallel": self.parallel,
            },
        )

        return "default"
