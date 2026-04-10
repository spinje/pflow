"""Tests for batch execution functions in pflow.runtime.engine.batch_executor.

These tests verify the standalone batch execution functions that replaced PflowBatchNode.
The core behavior under test:
- Sequential and parallel item execution
- Error handling (fail_fast vs continue)
- Retry logic
- CompilationError propagation
- Batch output shape (results, count, success_count, error_count, errors, batch_metadata)
- _detect_empty_output_items
- Progress callbacks
- Shallow-copy semantics for special keys
"""

import threading
import time

import pytest

from pflow.runtime.engine.batch_executor import (
    _detect_empty_output_items,
    _extract_error,
    _normalize_result,
    execute_batch,
    resolve_batch_items,
)
from pflow.runtime.engine.types import BatchConfig, NodeConfig

# =============================================================================
# Test helpers
# =============================================================================


def _make_node_config(
    node_id: str = "test_node",
    batch_config: BatchConfig | None = None,
    node_type_name: str = "MockNode",
) -> NodeConfig:
    """Create a NodeConfig for testing."""
    return NodeConfig(
        node_id=node_id,
        node_type_name=node_type_name,
        template_config=None,
        batch_config=batch_config,
        namespaced=True,
        interface_metadata=None,
    )


def _simple_execute_single_fn(node, config, item_shared):
    """Default execute_single_fn: runs node._run() and returns (action, {}, [])."""
    action = node._run(item_shared)
    return (action or "default", {}, [])


def _run_batch(
    node,
    shared: dict,
    items_template="${data}",
    item_alias: str = "item",
    error_handling: str = "fail_fast",
    parallel: bool = False,
    max_concurrent: int = 10,
    max_retries: int = 1,
    retry_wait: float = 0.0,
    node_id: str = "test_node",
    execute_single_fn=None,
) -> tuple[str, list[dict]]:
    """Helper to run execute_batch with convenient defaults."""
    batch_config = BatchConfig(
        items_template=items_template,
        item_alias=item_alias,
        error_handling=error_handling,
        parallel=parallel,
        max_concurrent=max_concurrent,
        max_retries=max_retries,
        retry_wait=retry_wait,
    )
    config = _make_node_config(node_id=node_id, batch_config=batch_config)
    fn = execute_single_fn or _simple_execute_single_fn
    return execute_batch(node, config, shared, fn)


# =============================================================================
# Mock nodes
# =============================================================================


class MockInnerNode:
    """Mock node that simulates pflow node behavior.

    Writes results to shared[node_id] to mimic namespaced behavior.
    """

    def __init__(self, node_id: str, behavior: str = "echo"):
        """Initialize mock node.

        Args:
            node_id: Node identifier for namespacing
            behavior: One of:
                - "echo": Return item value as response
                - "transform": Double numeric values
                - "error_on_index": Raise exception on specific index
                - "error_in_result": Write error key to result
                - "return_none": Return None (valid success)
        """
        self.node_id = node_id
        self.behavior = behavior
        self.error_index: int | None = None
        self.call_count = 0

    def _run(self, shared: dict) -> str:
        """Execute mock node logic."""
        self.call_count += 1

        # Get item from shared store (injected by batch executor)
        item = shared.get("item") or shared.get("file") or shared.get("record")

        result = {}

        if self.behavior == "echo":
            result = {"response": item}
        elif self.behavior == "transform":
            result = {"response": item * 2 if isinstance(item, (int, float)) else item}
        elif self.behavior == "error_on_index":
            # Error on specific item index (set externally)
            if self.error_index is not None and self.call_count - 1 == self.error_index:
                raise ValueError(f"Intentional error on item {self.error_index}")
            result = {"response": item}
        elif self.behavior == "error_in_result":
            # Write error to result dict
            if self.error_index is not None and self.call_count - 1 == self.error_index:
                result = {"error": f"Error: Processing failed for item {item}"}
            else:
                result = {"response": item}
        elif self.behavior == "return_none":
            result = {"response": None}

        # Write to namespace (simulating namespaced behavior)
        shared[self.node_id] = result
        return "default"


class ParallelMockInnerNode:
    """Enhanced mock node for parallel testing with delays and thread tracking.

    Note: This node is designed to be deep-copied in parallel execution.
    It uses __getstate__/__setstate__ to handle the threading.Lock which
    cannot be pickled.
    """

    def __init__(self, node_id: str, delay: float = 0, behavior: str = "echo"):
        self.node_id = node_id
        self.delay = delay
        self.behavior = behavior
        self.error_index: int | None = None
        self.call_count = 0
        self.thread_ids: list[int] = []
        self._lock = threading.Lock()

    def __getstate__(self):
        state = self.__dict__.copy()
        del state["_lock"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._lock = threading.Lock()

    def _get_item(self, shared: dict):
        for key in ("item", "file", "record"):
            if key in shared:
                return shared[key]
        return None

    def _apply_delay(self, item):
        if self.behavior == "variable_delay" and isinstance(item, dict):
            time.sleep(item.get("delay", 0))
        elif self.delay > 0:
            time.sleep(self.delay)

    def _run(self, shared: dict) -> str:
        with self._lock:
            self.call_count += 1
            current_call = self.call_count - 1
            self.thread_ids.append(threading.current_thread().ident)

        item = self._get_item(shared)
        self._apply_delay(item)

        result = self._compute_result(item, current_call)
        shared[self.node_id] = result
        return "default"

    def _compute_result(self, item, current_call: int) -> dict:
        if self.behavior == "echo":
            return {"response": item}
        if self.behavior == "echo_with_id":
            return {"response": item, "thread_id": threading.current_thread().ident}
        if self.behavior == "variable_delay":
            return {"response": item.get("id") if isinstance(item, dict) else item}
        if self.behavior == "error_on_index":
            if self.error_index is not None and current_call == self.error_index:
                raise ValueError(f"Intentional error on item {self.error_index}")
            return {"response": item}
        if self.behavior == "error_in_result":
            if self.error_index is not None and current_call == self.error_index:
                return {"error": f"Error: Processing failed for item {item}"}
            return {"response": item}
        return {"response": item}


# =============================================================================
# Basic batch tests
# =============================================================================


class TestBatchExecutionBasic:
    """Basic batch processing tests."""

    def test_batch_empty_items(self):
        """Empty array produces empty results with zero counts."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": []}

        _run_batch(inner, shared)

        assert shared["test_node"]["results"] == []
        assert shared["test_node"]["count"] == 0
        assert shared["test_node"]["success_count"] == 0
        assert shared["test_node"]["error_count"] == 0
        assert shared["test_node"]["errors"] is None

    def test_batch_single_item(self):
        """Single item processed correctly."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["hello"]}

        _run_batch(inner, shared)

        assert len(shared["test_node"]["results"]) == 1
        assert shared["test_node"]["results"][0]["response"] == "hello"
        assert shared["test_node"]["results"][0]["item"] == "hello"
        assert shared["test_node"]["count"] == 1
        assert shared["test_node"]["success_count"] == 1
        assert shared["test_node"]["error_count"] == 0

    def test_batch_multiple_items_in_order(self):
        """Multiple items processed in input order."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a", "b", "c"]}

        _run_batch(inner, shared)

        assert shared["test_node"]["count"] == 3
        assert shared["test_node"]["success_count"] == 3
        assert shared["test_node"]["results"][0]["response"] == "a"
        assert shared["test_node"]["results"][0]["item"] == "a"
        assert shared["test_node"]["results"][1]["response"] == "b"
        assert shared["test_node"]["results"][1]["item"] == "b"
        assert shared["test_node"]["results"][2]["response"] == "c"
        assert shared["test_node"]["results"][2]["item"] == "c"


class TestItemInResult:
    """Tests for the `item` field being included in each batch result."""

    def test_item_included_when_result_has_error_key(self):
        """Error items are filtered from results; error details in errors list."""
        inner = MockInnerNode("test_node", behavior="error_in_result")
        inner.error_index = 1

        shared: dict = {"data": ["success", "will_fail", "success"]}
        _run_batch(inner, shared, error_handling="continue")

        # results contains only successful items
        results = shared["test_node"]["results"]
        assert len(results) == 2
        assert results[0]["response"] == "success"
        assert results[0]["item"] == "success"
        assert results[1]["response"] == "success"
        assert results[1]["item"] == "success"

        # Error details are in the errors list with original item
        assert shared["test_node"]["error_count"] == 1
        assert shared["test_node"]["errors"][0]["item"] == "will_fail"

    def test_item_overwrite_warning_logged(self, caplog):
        """Warning is logged when node output already has 'item' key."""
        import logging

        class ItemOutputNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                shared[self.node_id] = {"response": item, "item": "node_provided"}
                return "default"

        inner = ItemOutputNode("test_node")
        shared: dict = {"data": ["test_value"]}

        with caplog.at_level(logging.WARNING, logger="pflow.runtime.engine.batch_executor"):
            _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0]["item"] == "test_value"
        assert results[0]["response"] == "test_value"
        assert "already has 'item' key" in caplog.text


class TestInlineArrayItems:
    """Tests for inline array items support (batch.items as literal array)."""

    def test_inline_array_with_templates(self):
        """Inline array with templates inside elements resolves correctly."""
        inner = MockInnerNode("test_node")

        shared: dict = {"source": {"content": "hello world"}}
        items_template = [
            {"style": "summary", "data": "${source}"},
            {"style": "detailed", "data": "${source}"},
        ]

        _run_batch(inner, shared, items_template=items_template)

        results = shared["test_node"]["results"]
        # The items should have the resolved templates
        assert results[0]["item"] == {"style": "summary", "data": {"content": "hello world"}}
        assert results[1]["item"] == {"style": "detailed", "data": {"content": "hello world"}}

    def test_inline_array_preserves_types(self):
        """Inline array preserves types of resolved templates (Task 103)."""
        shared: dict = {"num": 42, "bool_val": True, "list_val": [1, 2, 3]}
        items_template = [
            {"count": "${num}", "flag": "${bool_val}", "items": "${list_val}"},
        ]

        # Verify resolve_batch_items preserves types
        items = resolve_batch_items(items_template, shared)

        assert items[0]["count"] == 42
        assert items[0]["flag"] is True
        assert items[0]["items"] == [1, 2, 3]


class TestItemAliasInjection:
    """Tests for item alias injection into isolated context."""

    def test_default_item_alias(self):
        """Default alias 'item' is available in context."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["value1"]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0]["response"] == "value1"
        assert results[0]["item"] == "value1"

    def test_custom_item_alias(self):
        """Custom alias is used when 'as' is specified."""

        class AliasAwareNode:
            def __init__(self, node_id: str, expected_alias: str):
                self.node_id = node_id
                self.expected_alias = expected_alias

            def _run(self, shared: dict) -> str:
                item = shared.get(self.expected_alias)
                shared[self.node_id] = {"response": item, "alias_used": self.expected_alias}
                return "default"

        inner = AliasAwareNode("test_node", "file")
        shared: dict = {"files": ["doc1.txt", "doc2.txt"]}

        _run_batch(inner, shared, items_template="${files}", item_alias="file")

        results = shared["test_node"]["results"]
        assert results[0]["response"] == "doc1.txt"
        assert results[0]["alias_used"] == "file"
        assert results[0]["item"] == "doc1.txt"
        assert results[1]["response"] == "doc2.txt"
        assert results[1]["alias_used"] == "file"
        assert results[1]["item"] == "doc2.txt"


class TestIsolatedContext:
    """Tests for isolated shared store context per item."""

    def test_items_dont_pollute_each_other(self):
        """Each item execution has isolated context."""

        class AccumulatorNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                prev_item = shared.get("previous_item")
                current = shared.get("item")
                shared["previous_item"] = current
                shared[self.node_id] = {"response": current, "saw_previous": prev_item}
                return "default"

        inner = AccumulatorNode("test_node")
        shared: dict = {"data": [1, 2, 3]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        # Each item should NOT see previous item due to isolation
        assert results[0]["saw_previous"] is None
        assert results[1]["saw_previous"] is None
        assert results[2]["saw_previous"] is None

    def test_original_shared_unchanged_during_iteration(self):
        """Original shared store does not get 'item' alias injected."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a", "b"], "original_key": "original_value"}

        _run_batch(inner, shared)

        # Alias was only in isolated copies
        assert "item" not in shared

    def test_special_keys_shared_across_items(self):
        """Special dunder keys are shared across items via shallow copy behavior."""

        class TrackingNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                if "__warnings__" not in shared:
                    shared["__warnings__"] = {}
                item = shared.get("item", "unknown")
                shared["__warnings__"][f"warn_{item}"] = f"warning for {item}"
                shared[self.node_id] = {"response": "ok"}
                return "default"

        inner = TrackingNode("test_node")
        shared: dict = {"data": ["a", "b", "c"], "__warnings__": {}}

        _run_batch(inner, shared)

        # All 3 items should have written to the SAME dict (shallow copy shares it)
        assert len(shared["__warnings__"]) >= 3


class TestErrorHandling:
    """Tests for error handling modes."""

    def test_fail_fast_stops_on_exception(self):
        """fail_fast mode stops execution on first exception."""
        inner = MockInnerNode("test_node", behavior="error_on_index")
        inner.error_index = 1

        shared: dict = {"data": ["a", "b", "c"]}

        with pytest.raises(ValueError, match="Intentional error on item 1"):
            _run_batch(inner, shared, error_handling="fail_fast")

        # Only first item was processed before error
        assert inner.call_count == 2

    def test_continue_processes_all_items(self):
        """continue mode processes all items even after errors."""
        inner = MockInnerNode("test_node", behavior="error_on_index")
        inner.error_index = 1

        shared: dict = {"data": ["a", "b", "c"]}
        _run_batch(inner, shared, error_handling="continue")

        # All 3 items attempted
        assert inner.call_count == 3
        assert shared["test_node"]["count"] == 3
        assert shared["test_node"]["success_count"] == 2
        assert shared["test_node"]["error_count"] == 1

        # results contains only successful items (failed items filtered out)
        results = shared["test_node"]["results"]
        assert len(results) == 2
        assert results[0]["response"] == "a"
        assert results[0]["item"] == "a"
        assert results[1]["response"] == "c"
        assert results[1]["item"] == "c"

        assert len(shared["test_node"]["errors"]) == 1
        assert shared["test_node"]["errors"][0]["index"] == 1
        assert shared["test_node"]["errors"][0]["item"] == "b"
        assert "Intentional error" in shared["test_node"]["errors"][0]["error"]

    def test_fail_fast_on_error_in_result(self):
        """fail_fast mode triggers on error key in result dict."""
        inner = MockInnerNode("test_node", behavior="error_in_result")
        inner.error_index = 0

        shared: dict = {"data": ["a", "b"]}

        with pytest.raises(RuntimeError, match=r"Batch 'test_node' failed at item \[0\]"):
            _run_batch(inner, shared, error_handling="fail_fast")

    def test_continue_records_error_in_result(self):
        """continue mode records error from result dict."""
        inner = MockInnerNode("test_node", behavior="error_in_result")
        inner.error_index = 1

        shared: dict = {"data": ["a", "b", "c"]}
        _run_batch(inner, shared, error_handling="continue")

        # results contains only successful items — error item filtered out
        results = shared["test_node"]["results"]
        assert len(results) == 2
        assert results[0]["response"] == "a"
        assert results[1]["response"] == "c"

        assert shared["test_node"]["success_count"] == 2
        assert shared["test_node"]["error_count"] == 1
        assert shared["test_node"]["errors"][0]["index"] == 1
        assert shared["test_node"]["errors"][0]["error"] == "Error: Processing failed for item b"


class TestResultStructure:
    """Tests for output result structure."""

    def test_result_structure_complete(self):
        """Result has all required fields."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a", "b"]}

        _run_batch(inner, shared)

        result = shared["test_node"]
        assert "results" in result
        assert "count" in result
        assert "success_count" in result
        assert "error_count" in result
        assert "errors" in result

    def test_errors_none_when_no_errors(self):
        """errors field is None when all items succeed."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a", "b"]}

        _run_batch(inner, shared)

        assert shared["test_node"]["errors"] is None

    def test_none_is_valid_success(self):
        """None result from node is treated as success, not error."""
        inner = MockInnerNode("test_node", behavior="return_none")
        shared: dict = {"data": ["a", "b"]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0]["response"] is None
        assert results[0]["item"] == "a"
        assert results[1]["response"] is None
        assert results[1]["item"] == "b"
        assert shared["test_node"]["success_count"] == 2
        assert shared["test_node"]["error_count"] == 0


class TestFilteredResultsContract:
    """Tests for the filtered results contract: results = successes only."""

    def test_results_only_contains_successes(self):
        """With continue mode and partial failure, results excludes failed items."""
        inner = MockInnerNode("test_node", behavior="error_on_index")
        inner.error_index = 1

        shared: dict = {"data": ["a", "b", "c"]}
        _run_batch(inner, shared, error_handling="continue")

        output = shared["test_node"]
        assert len(output["results"]) == output["success_count"]
        assert output["success_count"] + output["error_count"] == output["count"]
        assert all(r is not None for r in output["results"])
        assert all(r.get("error") is None for r in output["results"])

        # Each result carries its original batch index for provenance
        assert output["results"][0]["original_index"] == 0
        assert output["results"][1]["original_index"] == 2

    def test_results_unaffected_when_all_succeed(self):
        """When no errors, results equals all items (filtering is a no-op)."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a", "b", "c"]}
        _run_batch(inner, shared)

        output = shared["test_node"]
        assert len(output["results"]) == 3
        assert output["count"] == 3
        assert output["success_count"] == 3
        assert output["error_count"] == 0

    def test_parallel_filtered_results_contract(self):
        """Parallel mode also filters results to successes only."""

        class FailOnB:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def __getstate__(self):
                return self.__dict__.copy()

            def __setstate__(self, state):
                self.__dict__.update(state)

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                if item == "b":
                    raise ValueError("Error on b")
                shared[self.node_id] = {"response": item}
                return "default"

        inner = FailOnB("test_node")
        shared: dict = {"data": ["a", "b", "c"]}
        _run_batch(inner, shared, parallel=True, error_handling="continue")

        output = shared["test_node"]
        assert len(output["results"]) == 2
        assert output["success_count"] == 2
        assert output["error_count"] == 1
        assert output["count"] == 3
        assert output["results"][0]["response"] == "a"
        assert output["results"][1]["response"] == "c"

    def test_original_index_disambiguates_duplicate_items(self):
        """original_index distinguishes results when input items are duplicates."""
        inner = MockInnerNode("test_node", behavior="error_on_index")
        inner.error_index = 1

        shared: dict = {"data": ["x", "x", "x"]}
        _run_batch(inner, shared, error_handling="continue")

        output = shared["test_node"]
        assert len(output["results"]) == 2
        # Both results have item="x" — only original_index tells them apart
        assert output["results"][0]["item"] == "x"
        assert output["results"][1]["item"] == "x"
        assert output["results"][0]["original_index"] == 0
        assert output["results"][1]["original_index"] == 2


class TestItemsResolution:
    """Tests for items template resolution."""

    def test_items_from_simple_path(self):
        """Items resolved from simple variable path."""
        items = resolve_batch_items("${files}", {"files": ["a.txt", "b.txt"]})
        assert items == ["a.txt", "b.txt"]

    def test_items_from_nested_path(self):
        """Items resolved from nested path."""
        items = resolve_batch_items("${list_files.output}", {"list_files": {"output": ["x", "y", "z"]}})
        assert items == ["x", "y", "z"]

    def test_items_not_array_raises(self):
        """TypeError raised when items doesn't resolve to array."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": "not_an_array"}

        with pytest.raises(TypeError, match="batch items must be an array"):
            _run_batch(inner, shared)

    def test_items_none_raises(self):
        """ValueError raised when items resolves to None."""
        inner = MockInnerNode("test_node")
        shared: dict = {}

        with pytest.raises(ValueError, match="resolved to None"):
            _run_batch(inner, shared, items_template="${missing}")

    def test_items_dict_raises(self):
        """TypeError raised when items resolves to dict."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": {"not": "array"}}

        with pytest.raises(TypeError, match="got dict"):
            _run_batch(inner, shared)


class TestItemsCoalesce:
    """Tests for coalesce (??) operator in batch items template."""

    def test_items_coalesce_first_branch(self):
        """Batch items resolved via coalesce when first branch executed."""
        items = resolve_batch_items(
            "${source_a.items ?? source_b.items}",
            {"source_a": {"items": ["x", "y"]}},
        )
        assert items == ["x", "y"]

    def test_items_coalesce_second_branch(self):
        """Batch items resolved via coalesce when second branch executed."""
        items = resolve_batch_items(
            "${source_a.items ?? source_b.items}",
            {"source_b": {"items": ["a", "b", "c"]}},
        )
        assert items == ["a", "b", "c"]

    def test_items_coalesce_all_absent_raises(self):
        """ValueError when all coalesce operands are absent."""
        inner = MockInnerNode("test_node")
        shared: dict = {}

        with pytest.raises(ValueError, match="resolved to None"):
            _run_batch(inner, shared, items_template="${source_a.items ?? source_b.items}")


class TestItemsJsonAutoParsing:
    """Tests for JSON string auto-parsing in batch.items.

    Shell nodes output text to stdout. When that text is valid JSON,
    batch processing should auto-parse it to enable shell -> batch patterns.
    """

    def test_json_array_string_parsed(self):
        """JSON array string is auto-parsed to list."""
        items = resolve_batch_items("${shell.stdout}", {"shell": {"stdout": '["item1", "item2", "item3"]'}})
        assert items == ["item1", "item2", "item3"]

    def test_json_array_with_trailing_newline(self):
        """JSON string with trailing newline (common shell output) is parsed."""
        items = resolve_batch_items("${cmd.stdout}", {"cmd": {"stdout": '["a", "b"]\n'}})
        assert items == ["a", "b"]

    def test_json_array_with_whitespace(self):
        """JSON string with leading/trailing whitespace is parsed."""
        items = resolve_batch_items("${data}", {"data": '  \n  ["x", "y", "z"]  \n  '})
        assert items == ["x", "y", "z"]

    def test_json_complex_objects_parsed(self):
        """JSON array of objects is parsed correctly."""
        json_str = '[{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]'
        items = resolve_batch_items("${split.sections}", {"split": {"sections": json_str}})
        assert items == [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]

    def test_invalid_json_fails_with_type_error(self):
        """Invalid JSON string fails at type check with clear error."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": '["item1", "item2"'}

        with pytest.raises(TypeError, match="batch items must be an array, got str"):
            _run_batch(inner, shared)

    def test_json_object_fails_with_type_error(self):
        """JSON object string (not array) fails at type check."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": '{"key": "value"}'}

        with pytest.raises(TypeError, match="batch items must be an array, got str"):
            _run_batch(inner, shared)

    def test_non_json_string_fails_with_type_error(self):
        """Non-JSON string fails at type check."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": "just a plain string"}

        with pytest.raises(TypeError, match="batch items must be an array, got str"):
            _run_batch(inner, shared)

    def test_already_list_not_affected(self):
        """Already-parsed list is not affected by JSON parsing logic."""
        items = resolve_batch_items("${data}", {"data": ["already", "a", "list"]})
        assert items == ["already", "a", "list"]

    def test_empty_json_array_parsed(self):
        """Empty JSON array string is parsed correctly."""
        items = resolve_batch_items("${data}", {"data": "[]"})
        assert items == []

    def test_nested_json_arrays_parsed(self):
        """Nested JSON arrays are parsed correctly."""
        items = resolve_batch_items("${data}", {"data": "[[1, 2], [3, 4], [5, 6]]"})
        assert items == [[1, 2], [3, 4], [5, 6]]


class TestComplexItems:
    """Tests with complex item objects."""

    def test_complex_object_items(self):
        """Items can be complex objects with nested fields."""

        class FieldAccessNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                name = item.get("name") if isinstance(item, dict) else None
                shared[self.node_id] = {"response": name}
                return "default"

        inner = FieldAccessNode("test_node")
        shared: dict = {
            "records": [
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25},
            ]
        }

        _run_batch(inner, shared, items_template="${records}")

        results = shared["test_node"]["results"]
        assert results[0]["response"] == "Alice"
        assert results[0]["item"] == {"name": "Alice", "age": 30}
        assert results[1]["response"] == "Bob"
        assert results[1]["item"] == {"name": "Bob", "age": 25}

    def test_items_with_none_values(self):
        """Array containing None values is processed."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": [None, "value", None]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert shared["test_node"]["count"] == 3
        assert results[0]["response"] is None
        assert results[0]["item"] is None
        assert results[1]["response"] == "value"
        assert results[1]["item"] == "value"
        assert results[2]["response"] is None
        assert results[2]["item"] is None


class TestInputOutputFormats:
    """Tests for various input item types and output formats."""

    def test_number_items(self):
        """Numeric items are processed correctly."""
        inner = MockInnerNode("test_node", behavior="transform")
        shared: dict = {"data": [1, 2, 3]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0]["response"] == 2
        assert results[0]["item"] == 1
        assert results[1]["response"] == 4
        assert results[1]["item"] == 2
        assert results[2]["response"] == 6
        assert results[2]["item"] == 3

    def test_float_items(self):
        """Float items are processed correctly."""
        inner = MockInnerNode("test_node", behavior="transform")
        shared: dict = {"data": [1.5, 2.5, 3.5]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0]["response"] == 3.0
        assert results[0]["item"] == 1.5
        assert results[1]["response"] == 5.0
        assert results[1]["item"] == 2.5
        assert results[2]["response"] == 7.0
        assert results[2]["item"] == 3.5

    def test_mixed_type_items(self):
        """Mixed type items (strings, numbers, dicts, None) are processed."""
        inner = MockInnerNode("test_node", behavior="echo")
        shared: dict = {"data": [1, "two", {"three": 3}, None, True]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0]["response"] == 1
        assert results[0]["item"] == 1
        assert results[1]["response"] == "two"
        assert results[1]["item"] == "two"
        assert results[2]["response"] == {"three": 3}
        assert results[2]["item"] == {"three": 3}
        assert results[3]["response"] is None
        assert results[3]["item"] is None
        assert results[4]["response"] is True
        assert results[4]["item"] is True
        assert shared["test_node"]["count"] == 5
        assert shared["test_node"]["success_count"] == 5

    def test_nested_array_items(self):
        """Nested array items are processed correctly."""
        inner = MockInnerNode("test_node", behavior="echo")
        shared: dict = {"data": [[1, 2], [3, 4], [5, 6]]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0]["response"] == [1, 2]
        assert results[0]["item"] == [1, 2]
        assert results[1]["response"] == [3, 4]
        assert results[1]["item"] == [3, 4]
        assert results[2]["response"] == [5, 6]
        assert results[2]["item"] == [5, 6]

    def test_boolean_items(self):
        """Boolean items are processed correctly."""

        class BooleanEchoNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                shared[self.node_id] = {"response": item}
                return "default"

        inner = BooleanEchoNode("test_node")
        shared: dict = {"data": [True, False, True]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0]["response"] is True
        assert results[0]["item"] is True
        assert results[1]["response"] is False
        assert results[1]["item"] is False
        assert results[2]["response"] is True
        assert results[2]["item"] is True

    def test_string_output_wrapped_in_dict(self):
        """When node writes string directly to namespace, it's wrapped in {'value': ...}."""

        class StringOutputNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                shared[self.node_id] = f"processed_{item}"  # String, not dict
                return "default"

        inner = StringOutputNode("test_node")
        shared: dict = {"data": ["a", "b"]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0]["value"] == "processed_a"
        assert results[0]["item"] == "a"
        assert results[1]["value"] == "processed_b"
        assert results[1]["item"] == "b"

    def test_number_output_wrapped_in_dict(self):
        """When node writes number directly to namespace, it's wrapped in {'value': ...}."""

        class NumberOutputNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                shared[self.node_id] = item * 10  # Number, not dict
                return "default"

        inner = NumberOutputNode("test_node")
        shared: dict = {"data": [1, 2, 3]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0]["value"] == 10
        assert results[0]["item"] == 1
        assert results[1]["value"] == 20
        assert results[1]["item"] == 2
        assert results[2]["value"] == 30
        assert results[2]["item"] == 3

    def test_list_output_wrapped_in_dict(self):
        """When node writes list directly to namespace, it's wrapped in {'value': ...}."""

        class ListOutputNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                shared[self.node_id] = [item, item]  # List, not dict
                return "default"

        inner = ListOutputNode("test_node")
        shared: dict = {"data": ["x", "y"]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0]["value"] == ["x", "x"]
        assert results[0]["item"] == "x"
        assert results[1]["value"] == ["y", "y"]
        assert results[1]["item"] == "y"

    def test_empty_dict_output(self):
        """When node writes empty dict to namespace, result has item + original_index."""

        class EmptyDictNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                shared[self.node_id] = {}
                return "default"

        inner = EmptyDictNode("test_node")
        shared: dict = {"data": ["a", "b"]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0] == {"item": "a", "original_index": 0}
        assert results[1] == {"item": "b", "original_index": 1}
        assert shared["test_node"]["success_count"] == 2

    def test_node_writes_nothing(self):
        """When node doesn't write to namespace, result is empty dict + metadata."""

        class SilentNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                return "default"

        inner = SilentNode("test_node")
        shared: dict = {"data": ["a", "b"]}

        _run_batch(inner, shared)

        results = shared["test_node"]["results"]
        assert results[0] == {"item": "a", "original_index": 0}
        assert results[1] == {"item": "b", "original_index": 1}
        assert shared["test_node"]["success_count"] == 2


class TestExtractError:
    """Tests for _extract_error helper function."""

    def test_extract_error_from_dict(self):
        """Error extracted from dict with error key."""
        assert _extract_error({"error": "Something failed"}) == "Something failed"
        assert _extract_error({"error": "Error: Bad input"}) == "Error: Bad input"

    def test_extract_error_none_for_success(self):
        """None returned for successful results."""
        assert _extract_error({"response": "ok"}) is None
        assert _extract_error({"data": 123}) is None
        assert _extract_error({}) is None

    def test_extract_error_none_for_non_dict(self):
        """None returned for non-dict results."""
        assert _extract_error("string") is None
        assert _extract_error(123) is None
        assert _extract_error(None) is None
        assert _extract_error([1, 2, 3]) is None

    def test_extract_error_falsy_error_key(self):
        """Falsy error values are not treated as errors."""
        assert _extract_error({"error": ""}) is None
        assert _extract_error({"error": None}) is None
        assert _extract_error({"error": False}) is None
        assert _extract_error({"error": 0}) is None


class TestNormalizeResult:
    """Tests for _normalize_result helper function."""

    def test_none_returns_empty_dict(self):
        assert _normalize_result(None) == {}

    def test_dict_returned_as_is(self):
        assert _normalize_result({"key": "val"}) == {"key": "val"}

    def test_non_dict_wrapped_in_value(self):
        assert _normalize_result("hello") == {"value": "hello"}
        assert _normalize_result(42) == {"value": 42}
        assert _normalize_result([1, 2]) == {"value": [1, 2]}


class TestBatchConfigDefaults:
    """Tests for BatchConfig default values."""

    def test_default_alias_is_item(self):
        """Default alias is 'item' when 'as' not specified."""
        config = BatchConfig(items_template="${x}")
        assert config.item_alias == "item"

    def test_default_error_handling_is_fail_fast(self):
        """Default error handling is 'fail_fast' when not specified."""
        config = BatchConfig(items_template="${x}")
        assert config.error_handling == "fail_fast"

    def test_custom_alias_preserved(self):
        config = BatchConfig(items_template="${x}", item_alias="record")
        assert config.item_alias == "record"

    def test_continue_error_handling_preserved(self):
        config = BatchConfig(items_template="${x}", error_handling="continue")
        assert config.error_handling == "continue"

    def test_default_parallel_is_false(self):
        config = BatchConfig(items_template="${x}")
        assert config.parallel is False

    def test_default_max_concurrent_is_10(self):
        config = BatchConfig(items_template="${x}")
        assert config.max_concurrent == 10

    def test_default_max_retries_is_1(self):
        config = BatchConfig(items_template="${x}")
        assert config.max_retries == 1

    def test_default_retry_wait_is_0(self):
        config = BatchConfig(items_template="${x}")
        assert config.retry_wait == 0.0


class TestConfigTypeCoercion:
    """Tests for type coercion of batch config values.

    These coercion functions now live in the compiler (pflow.runtime.compilation.compiler).
    Testing them directly ensures defense-in-depth for invalid types.
    """

    def test_coerce_bool_string_true(self):
        """String 'true' is coerced to boolean True."""
        from pflow.runtime.compilation.compiler import _coerce_bool

        assert _coerce_bool("true") is True
        assert _coerce_bool("TRUE") is True
        assert _coerce_bool("True") is True

    def test_coerce_bool_string_false(self):
        """String 'false' is coerced to boolean False."""
        from pflow.runtime.compilation.compiler import _coerce_bool

        assert _coerce_bool("false") is False
        assert _coerce_bool("FALSE") is False

    def test_coerce_bool_string_yes(self):
        """String 'yes' is coerced to boolean True."""
        from pflow.runtime.compilation.compiler import _coerce_bool

        assert _coerce_bool("YES") is True
        assert _coerce_bool("yes") is True

    def test_coerce_bool_string_invalid(self):
        """Invalid string for bool raises CompilationError."""
        import pytest

        from pflow.core.exceptions import CompilationError
        from pflow.runtime.compilation.compiler import _coerce_bool

        with pytest.raises(CompilationError, match="not a valid boolean"):
            _coerce_bool("invalid", "parallel")

    def test_coerce_bool_int_1(self):
        """Integer 1 is coerced to boolean True."""
        from pflow.runtime.compilation.compiler import _coerce_bool

        assert _coerce_bool(1) is True

    def test_coerce_bool_int_0(self):
        """Integer 0 is coerced to boolean False."""
        from pflow.runtime.compilation.compiler import _coerce_bool

        assert _coerce_bool(0) is False

    def test_coerce_int_string(self):
        """String '5' is coerced to integer 5."""
        from pflow.runtime.compilation.compiler import _coerce_int

        assert _coerce_int("5", "max_retries", 1) == 5

    def test_coerce_int_float(self):
        """Float 5.9 is coerced to integer 5."""
        from pflow.runtime.compilation.compiler import _coerce_int

        assert _coerce_int(5.9, "max_retries", 1) == 5

    def test_coerce_int_invalid_raises(self):
        """Invalid string for int raises CompilationError."""
        import pytest

        from pflow.core.exceptions import CompilationError
        from pflow.runtime.compilation.compiler import _coerce_int

        with pytest.raises(CompilationError, match="not a valid integer"):
            _coerce_int("invalid", "max_retries", 1)

    def test_coerce_float_string(self):
        """String '1.5' is coerced to float 1.5."""
        from pflow.runtime.compilation.compiler import _coerce_float

        assert _coerce_float("1.5", "retry_wait", 0.0) == 1.5

    def test_coerce_float_int(self):
        """Integer 2 is coerced to float 2.0."""
        from pflow.runtime.compilation.compiler import _coerce_float

        assert _coerce_float(2, "retry_wait", 0.0) == 2.0

    def test_coerce_float_invalid_raises(self):
        """Invalid string for float raises CompilationError."""
        import pytest

        from pflow.core.exceptions import CompilationError
        from pflow.runtime.compilation.compiler import _coerce_float

        with pytest.raises(CompilationError, match="not a valid number"):
            _coerce_float("invalid", "retry_wait", 0.0)


# =============================================================================
# Phase 2 Tests: Parallel Execution
# =============================================================================


class TestParallelExecution:
    """Tests for parallel batch execution."""

    def test_parallel_execution_basic(self):
        """Items execute in parallel and all results collected."""
        inner = ParallelMockInnerNode("test_node", delay=0.01)
        shared: dict = {"data": ["a", "b", "c", "d", "e"]}

        _run_batch(inner, shared, parallel=True, max_concurrent=10)

        results = shared["test_node"]["results"]
        assert len(results) == 5
        assert shared["test_node"]["count"] == 5
        assert shared["test_node"]["success_count"] == 5

    def test_parallel_faster_than_sequential(self):
        """Parallel execution should be significantly faster than sequential."""
        delay_per_item = 0.05
        items_data = ["a", "b", "c", "d", "e"]

        inner = ParallelMockInnerNode("test_node", delay=delay_per_item)
        shared: dict = {"data": items_data}

        start = time.time()
        _run_batch(inner, shared, parallel=True, max_concurrent=10)
        elapsed = time.time() - start

        assert elapsed < 0.20, f"Parallel took {elapsed:.3f}s, expected < 0.20s (sequential would be ~0.25s)"

    def test_parallel_uses_multiple_threads(self):
        """Parallel execution uses multiple threads."""
        inner = ParallelMockInnerNode("test_node", delay=0.02)

        shared: dict = {"data": ["a", "b", "c", "d", "e"], "_thread_ids": []}

        original_run = inner._run

        def tracking_run(s):
            s["_thread_ids"].append(threading.current_thread().ident)
            return original_run(s)

        inner._run = tracking_run

        _run_batch(inner, shared, parallel=True, max_concurrent=10)

        unique_threads = set(shared["_thread_ids"])
        assert len(unique_threads) > 1, f"Expected multiple threads, got {unique_threads}"

    def test_max_concurrent_limits_workers(self):
        """max_concurrent limits the number of parallel workers."""
        delay_per_item = 0.05
        items_data = ["a", "b", "c", "d"]

        inner = ParallelMockInnerNode("test_node", delay=delay_per_item)
        shared: dict = {"data": items_data}

        start = time.time()
        _run_batch(inner, shared, parallel=True, max_concurrent=2)
        elapsed = time.time() - start

        assert elapsed >= 0.08, f"Expected batched execution (>80ms), got {elapsed:.3f}s"


class TestParallelResultOrdering:
    """Tests for result ordering in parallel execution."""

    def test_result_order_preserved(self):
        """Results are in input order regardless of completion order."""
        items_data = [
            {"id": 0, "delay": 0.06},
            {"id": 1, "delay": 0.04},
            {"id": 2, "delay": 0.02},
        ]

        inner = ParallelMockInnerNode("test_node", behavior="variable_delay")
        shared: dict = {"data": items_data}

        _run_batch(inner, shared, parallel=True, max_concurrent=10)

        results = shared["test_node"]["results"]
        assert results[0]["response"] == 0
        assert results[1]["response"] == 1
        assert results[2]["response"] == 2

    def test_result_order_with_many_items(self):
        """Result ordering works with more items."""
        items_data = [{"id": i, "delay": 0.01 * (5 - i)} for i in range(5)]

        inner = ParallelMockInnerNode("test_node", behavior="variable_delay")
        shared: dict = {"data": items_data}

        _run_batch(inner, shared, parallel=True, max_concurrent=10)

        results = shared["test_node"]["results"]
        for i in range(5):
            assert results[i]["response"] == i, f"Result {i} has wrong id"


class TestParallelTemplateIsolation:
    """Tests for template isolation in parallel execution."""

    def test_each_thread_gets_own_item(self):
        """Each thread should see its own item, not another thread's."""
        items_data = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]

        inner = ParallelMockInnerNode("test_node", delay=0.02)
        shared: dict = {"data": items_data}

        _run_batch(inner, shared, parallel=True, max_concurrent=10)

        results = shared["test_node"]["results"]
        for i, result in enumerate(results):
            expected_id = i + 1
            actual_item = result["response"]
            assert actual_item["id"] == expected_id, (
                f"Result {i} has wrong item: expected id={expected_id}, got {actual_item}"
            )

    def test_custom_alias_isolated(self):
        """Custom item alias is isolated per thread."""
        inner = ParallelMockInnerNode("test_node", delay=0.02)

        shared: dict = {"data": ["alpha", "beta", "gamma"], "_seen_values": []}

        original_run = inner._run

        def tracking_run(s):
            record = s.get("record")
            s["_seen_values"].append(record)
            s["item"] = record
            return original_run(s)

        inner._run = tracking_run

        _run_batch(inner, shared, items_template="${data}", item_alias="record", parallel=True, max_concurrent=10)

        assert set(shared["_seen_values"]) == {"alpha", "beta", "gamma"}
        results = shared["test_node"]["results"]
        assert results[0]["response"] == "alpha"
        assert results[1]["response"] == "beta"
        assert results[2]["response"] == "gamma"


class TestParallelErrorHandling:
    """Tests for error handling in parallel execution."""

    def test_parallel_fail_fast_raises(self):
        """fail_fast mode raises on first error in parallel."""

        class FailOnValueNode:
            def __init__(self, node_id: str, fail_value: str):
                self.node_id = node_id
                self.fail_value = fail_value

            def __getstate__(self):
                return self.__dict__.copy()

            def __setstate__(self, state):
                self.__dict__.update(state)

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                time.sleep(0.01)
                if item == self.fail_value:
                    raise ValueError(f"Intentional error on {item}")
                shared[self.node_id] = {"response": item}
                return "default"

        inner = FailOnValueNode("test_node", fail_value="c")
        shared: dict = {"data": ["a", "b", "c", "d", "e"]}

        with pytest.raises(ValueError, match="Intentional error"):
            _run_batch(inner, shared, parallel=True, error_handling="fail_fast")

    def test_parallel_continue_collects_all_errors(self):
        """continue mode processes all items and collects errors."""

        class FailOnValuesNode:
            def __init__(self, node_id: str, fail_values: set):
                self.node_id = node_id
                self.fail_values = fail_values

            def __getstate__(self):
                return self.__dict__.copy()

            def __setstate__(self, state):
                self.__dict__.update(state)

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                time.sleep(0.01)
                if item in self.fail_values:
                    raise ValueError(f"Error on item {item}")
                shared[self.node_id] = {"response": item}
                return "default"

        inner = FailOnValuesNode("test_node", fail_values={"b", "d"})
        shared: dict = {"data": ["a", "b", "c", "d", "e"]}

        _run_batch(inner, shared, parallel=True, error_handling="continue")

        assert shared["test_node"]["count"] == 5
        assert shared["test_node"]["success_count"] == 3
        assert shared["test_node"]["error_count"] == 2

    def test_parallel_continue_preserves_successful_results(self):
        """Successful results are preserved even when some items fail."""

        class FailOnValueNode:
            def __init__(self, node_id: str, fail_value: str):
                self.node_id = node_id
                self.fail_value = fail_value

            def __getstate__(self):
                return self.__dict__.copy()

            def __setstate__(self, state):
                self.__dict__.update(state)

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                time.sleep(0.01)
                if item == self.fail_value:
                    raise ValueError(f"Error on {item}")
                shared[self.node_id] = {"response": item}
                return "default"

        inner = FailOnValueNode("test_node", fail_value="b")
        shared: dict = {"data": ["a", "b", "c"]}

        _run_batch(inner, shared, parallel=True, error_handling="continue")

        # results contains only successful items (failed items filtered out)
        results = shared["test_node"]["results"]
        assert len(results) == 2
        assert results[0]["response"] == "a"
        assert results[0]["item"] == "a"
        assert results[1]["response"] == "c"
        assert results[1]["item"] == "c"


class TestParallelRetry:
    """Tests for retry logic in parallel execution."""

    def test_parallel_retry_succeeds_after_failure(self):
        """Item succeeds on retry in parallel mode."""

        class RetryNode:
            def __init__(self, node_id: str, fail_times: int):
                self.node_id = node_id
                self.fail_times = fail_times

            def __getstate__(self):
                return self.__dict__.copy()

            def __setstate__(self, state):
                self.__dict__.update(state)

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                item_key = str(item)
                attempts = shared.get("_attempts", {})
                attempts[item_key] = attempts.get(item_key, 0) + 1
                shared["_attempts"] = attempts
                attempt = attempts[item_key]

                if attempt <= self.fail_times:
                    raise ValueError(f"Temporary failure for {item}")

                shared[self.node_id] = {"response": item, "attempts": attempt}
                return "default"

        inner = RetryNode("test_node", fail_times=2)
        shared: dict = {"data": ["x"], "_attempts": {}}

        _run_batch(inner, shared, parallel=True, max_retries=3, retry_wait=0)

        results = shared["test_node"]["results"]
        assert results[0]["response"] == "x"
        assert results[0]["attempts"] == 3
        assert results[0]["item"] == "x"
        assert shared["test_node"]["success_count"] == 1

    def test_parallel_retry_exhausted(self):
        """Error returned when all retries exhausted in parallel."""

        class AlwaysFailNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def __getstate__(self):
                return self.__dict__.copy()

            def __setstate__(self, state):
                self.__dict__.update(state)

            def _run(self, shared: dict) -> str:
                shared["_attempts"].append(1)
                raise ValueError("Permanent failure")

        inner = AlwaysFailNode("test_node")
        shared: dict = {"data": ["x"], "_attempts": []}

        # All items failed -> all-fail abort raises RuntimeError
        with pytest.raises(RuntimeError, match="all 1 items failed"):
            _run_batch(inner, shared, parallel=True, max_retries=3, retry_wait=0, error_handling="continue")

        # Should have tried 3 times
        assert len(shared["_attempts"]) == 3

    def test_parallel_retry_resets_namespace(self):
        """Namespace is reset between retries in parallel mode.

        This prevents partial writes from failed attempts polluting retry attempts.
        """

        class WriteBeforeFailNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def __deepcopy__(self, memo):
                return WriteBeforeFailNode(self.node_id)

            def _run(self, shared: dict) -> str:
                shared["_retries"].append(1)
                retry_num = len(shared["_retries"])

                namespace = shared.get(self.node_id, {})
                had_previous_marker = "marker" in namespace

                shared["_observations"].append({"retry": retry_num, "had_previous_marker": had_previous_marker})

                if self.node_id not in shared:
                    shared[self.node_id] = {}
                shared[self.node_id]["marker"] = f"written_on_retry_{retry_num}"

                if retry_num == 1:
                    raise ValueError("Intentional failure on first attempt")

                shared[self.node_id]["result"] = "success"
                return "default"

        inner = WriteBeforeFailNode("test_node")
        shared: dict = {"data": ["item_a"], "_retries": [], "_observations": []}

        _run_batch(inner, shared, parallel=True, max_retries=2, error_handling="continue")

        assert len(shared["_observations"]) == 2
        assert shared["_observations"][0]["had_previous_marker"] is False
        assert shared["_observations"][1]["had_previous_marker"] is False

        results = shared["test_node"]["results"]
        assert results[0]["result"] == "success"


class TestParallelThreadSafety:
    """Tests for thread safety in parallel execution."""

    def test_llm_trace_accumulated_parallel(self):
        """_batch_trace accumulates trace items from all parallel items."""

        class LLMTrackingNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                time.sleep(0.01)
                shared[self.node_id] = {
                    "response": item,
                    "llm_usage": {"model": "test", "input_tokens": 10, "output_tokens": 5},
                }
                return "default"

        inner = LLMTrackingNode("test_node")
        shared: dict = {"data": ["a", "b", "c", "d", "e"]}

        _, batch_trace_items = _run_batch(inner, shared, parallel=True, max_concurrent=10)

        # All 5 items should have trace entries with llm_call data
        assert len(batch_trace_items) == 5
        tracked_items = {entry["item"] for entry in batch_trace_items}
        assert tracked_items == {"a", "b", "c", "d", "e"}
        for entry in batch_trace_items:
            assert "llm_call" in entry
            assert entry["llm_call"]["model"] == "test"

    def test_batch_captures_inner_node_llm_usage_sequential(self):
        """LLM usage from inner nodes is captured via batch trace in sequential mode."""

        class MockLLMNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                shared[self.node_id] = {
                    "response": f"processed: {item}",
                    "llm_usage": {
                        "model": "test-model",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "total_tokens": 150,
                    },
                }
                return "default"

        inner = MockLLMNode("test_node")
        shared: dict = {"data": ["a", "b", "c"]}

        _, trace_items = _run_batch(inner, shared, parallel=False)

        assert len(trace_items) == 3
        for i, entry in enumerate(trace_items):
            assert entry["index"] == i
            assert entry["success"] is True
            assert "llm_call" in entry
            assert entry["llm_call"]["model"] == "test-model"
            assert entry["llm_call"]["input_tokens"] == 100
            assert entry["llm_call"]["output_tokens"] == 50

    def test_batch_captures_inner_node_llm_usage_parallel(self):
        """LLM usage from inner nodes is captured in parallel mode."""

        class MockLLMNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                time.sleep(0.01)
                shared[self.node_id] = {
                    "response": f"processed: {item}",
                    "llm_usage": {
                        "model": "parallel-model",
                        "input_tokens": 200,
                        "output_tokens": 100,
                    },
                }
                return "default"

        inner = MockLLMNode("test_node")
        shared: dict = {"data": ["x", "y", "z", "w", "v"]}

        _, trace_items = _run_batch(inner, shared, parallel=True, max_concurrent=5)

        assert len(trace_items) == 5
        assert all(entry["llm_call"]["model"] == "parallel-model" for entry in trace_items)
        indices = {entry["index"] for entry in trace_items}
        assert indices == {0, 1, 2, 3, 4}

    def test_batch_captures_namespaced_llm_usage(self):
        """LLM usage is captured from namespaced node output."""

        class NamespacedMockLLMNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                if self.node_id not in shared:
                    shared[self.node_id] = {}
                shared[self.node_id]["llm_usage"] = {
                    "model": "namespaced-model",
                    "input_tokens": 50,
                    "output_tokens": 25,
                }
                shared[self.node_id]["response"] = f"processed: {item}"
                return "default"

        inner = NamespacedMockLLMNode("test_node")
        shared: dict = {"data": [1, 2]}

        _, trace_items = _run_batch(inner, shared, parallel=False)

        assert len(trace_items) == 2
        assert all(entry["llm_call"]["model"] == "namespaced-model" for entry in trace_items)

    def test_batch_initializes_and_collects_batch_trace(self):
        """execute_batch initializes _batch_trace and returns trace items after execution."""

        class MockLLMNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                shared[self.node_id] = {
                    "response": "ok",
                    "llm_usage": {"model": "test", "input_tokens": 10, "output_tokens": 5},
                }
                return "default"

        inner = MockLLMNode("test_node")
        shared: dict = {"data": ["a", "b"]}
        assert "_batch_trace" not in shared

        _, trace_items = _run_batch(inner, shared, parallel=False)

        # After execution, trace items are returned and shared store is cleaned up
        assert len(trace_items) == 2
        assert "_batch_trace" not in shared  # Cleaned up

    def test_batch_no_llm_usage_no_crash(self):
        """Batch handles inner nodes that don't write llm_usage."""

        class NonLLMNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                shared[self.node_id] = {"response": item}
                return "default"

        inner = NonLLMNode("test_node")
        shared: dict = {"data": ["a", "b", "c"]}

        _, trace_items = _run_batch(inner, shared, parallel=False)

        assert len(trace_items) == 3
        for entry in trace_items:
            assert "llm_call" not in entry

        assert len(shared["test_node"]["results"]) == 3

    def test_batch_trace_llm_call_contains_fields_for_cost_calculation(self):
        """Trace llm_call records contain all fields needed for cost calculation."""

        class MockLLMNodeWithFullUsage:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                shared[self.node_id] = {
                    "response": f"processed: {item}",
                    "llm_usage": {
                        "model": "anthropic/claude-sonnet-4-0",
                        "input_tokens": 500,
                        "output_tokens": 150,
                        "total_tokens": 650,
                        "cache_creation_input_tokens": 100,
                        "cache_read_input_tokens": 50,
                        "total_cost_usd": 0.0123,
                    },
                }
                return "default"

        inner = MockLLMNodeWithFullUsage("summarize")
        shared: dict = {"items": ["doc1", "doc2", "doc3"]}

        _, trace_items = _run_batch(inner, shared, node_id="summarize", items_template="${items}", parallel=False)

        assert len(trace_items) == 3

        for i, entry in enumerate(trace_items):
            llm_call = entry["llm_call"]
            assert llm_call["model"] == "anthropic/claude-sonnet-4-0"
            assert llm_call["input_tokens"] == 500
            assert llm_call["output_tokens"] == 150
            assert llm_call["total_tokens"] == 650
            assert llm_call["cache_creation_input_tokens"] == 100
            assert llm_call["cache_read_input_tokens"] == 50
            assert llm_call["total_cost_usd"] == 0.0123
            assert llm_call["cost_usd"] == 0.0123
            assert entry["index"] == i

        total_cost = sum(entry["llm_call"]["cost_usd"] for entry in trace_items)
        assert total_cost == pytest.approx(0.0123 * 3)

        total_tokens = sum(entry["llm_call"]["total_tokens"] for entry in trace_items)
        assert total_tokens == 650 * 3

    def test_no_race_on_results_array(self):
        """Results array is not corrupted by parallel writes."""
        inner = ParallelMockInnerNode("test_node", delay=0.01)
        items_data = list(range(20))
        shared: dict = {"data": items_data}

        _run_batch(inner, shared, parallel=True, max_concurrent=10)

        results = shared["test_node"]["results"]
        assert len(results) == 20
        for i, result in enumerate(results):
            assert result is not None, f"Result {i} is None"
            assert result["response"] == i, f"Result {i} has wrong value"


class TestParallelEdgeCases:
    """Edge case tests for parallel execution."""

    def test_parallel_empty_list(self):
        """Empty input returns empty results in parallel mode."""
        inner = ParallelMockInnerNode("test_node")
        shared: dict = {"data": []}

        _run_batch(inner, shared, parallel=True)

        assert shared["test_node"]["results"] == []
        assert shared["test_node"]["count"] == 0

    def test_parallel_single_item(self):
        """Single item works in parallel mode."""
        inner = ParallelMockInnerNode("test_node", delay=0.01)
        shared: dict = {"data": ["only_one"]}

        _run_batch(inner, shared, parallel=True)

        results = shared["test_node"]["results"]
        assert len(results) == 1
        assert results[0]["response"] == "only_one"
        assert results[0]["item"] == "only_one"
        assert shared["test_node"]["success_count"] == 1

    def test_parallel_vs_sequential_same_results(self):
        """Parallel and sequential produce identical results."""
        items_data = ["a", "b", "c", "d", "e"]

        inner_seq = ParallelMockInnerNode("test_node")
        shared_seq: dict = {"data": items_data.copy()}
        _run_batch(inner_seq, shared_seq, parallel=False)

        inner_par = ParallelMockInnerNode("test_node")
        shared_par: dict = {"data": items_data.copy()}
        _run_batch(inner_par, shared_par, parallel=True, max_concurrent=10)

        results_seq = shared_seq["test_node"]["results"]
        results_par = shared_par["test_node"]["results"]
        assert results_seq == results_par
        assert shared_seq["test_node"]["count"] == shared_par["test_node"]["count"]
        assert shared_seq["test_node"]["success_count"] == shared_par["test_node"]["success_count"]


class TestBatchMetadata:
    """Tests for batch_metadata in output (tracing enhancement)."""

    def test_batch_metadata_present_in_output(self):
        """batch_metadata field is present in output."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a", "b", "c"]}

        _run_batch(inner, shared)

        assert "batch_metadata" in shared["test_node"]

    def test_batch_metadata_sequential_mode(self):
        """batch_metadata shows sequential execution details."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a", "b"]}

        _run_batch(inner, shared, parallel=False, max_retries=2, retry_wait=0.5)

        metadata = shared["test_node"]["batch_metadata"]
        assert metadata["parallel"] is False
        assert metadata["execution_mode"] == "sequential"
        assert metadata["max_concurrent"] is None
        assert metadata["max_retries"] == 2
        assert metadata["retry_wait"] == 0.5

    def test_batch_metadata_parallel_mode(self):
        """batch_metadata shows parallel execution details."""
        inner = ParallelMockInnerNode("test_node")
        shared: dict = {"data": ["a", "b", "c"]}

        _run_batch(inner, shared, parallel=True, max_concurrent=5, max_retries=3)

        metadata = shared["test_node"]["batch_metadata"]
        assert metadata["parallel"] is True
        assert metadata["execution_mode"] == "parallel"
        assert metadata["max_concurrent"] == 5
        assert metadata["max_retries"] == 3

    def test_batch_metadata_timing_stats(self):
        """batch_metadata includes timing statistics."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a", "b", "c"]}

        _run_batch(inner, shared)

        timing = shared["test_node"]["batch_metadata"]["timing"]
        assert timing is not None
        assert "total_items_ms" in timing
        assert "avg_item_ms" in timing
        assert "min_item_ms" in timing
        assert "max_item_ms" in timing

        assert timing["total_items_ms"] >= 0
        assert timing["avg_item_ms"] >= 0
        assert timing["min_item_ms"] >= 0
        assert timing["max_item_ms"] >= 0
        assert timing["min_item_ms"] <= timing["avg_item_ms"]
        assert timing["avg_item_ms"] <= timing["max_item_ms"]

    def test_batch_metadata_timing_stats_parallel(self):
        """batch_metadata timing works in parallel mode."""
        inner = ParallelMockInnerNode("test_node", delay=0.01)
        shared: dict = {"data": ["a", "b", "c", "d", "e"]}

        _run_batch(inner, shared, parallel=True, max_concurrent=3)

        timing = shared["test_node"]["batch_metadata"]["timing"]
        assert timing is not None
        assert timing["total_items_ms"] > 0
        assert len(shared["test_node"]["results"]) == 5

    def test_batch_metadata_empty_list(self):
        """batch_metadata timing is None for empty list."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": []}

        _run_batch(inner, shared)

        timing = shared["test_node"]["batch_metadata"]["timing"]
        assert timing is None

    def test_batch_metadata_retry_wait_omitted_when_zero(self):
        """retry_wait is None when set to 0 (default)."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a"]}

        _run_batch(inner, shared, retry_wait=0)

        metadata = shared["test_node"]["batch_metadata"]
        assert metadata["retry_wait"] is None

    def test_batch_metadata_retry_wait_present_when_nonzero(self):
        """retry_wait is present when > 0."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a"]}

        _run_batch(inner, shared, retry_wait=1.5)

        metadata = shared["test_node"]["batch_metadata"]
        assert metadata["retry_wait"] == 1.5

    def test_batch_metadata_captured_in_trace(self):
        """batch_metadata is captured in workflow traces via node_output."""
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        inner = ParallelMockInnerNode("batch_node")
        shared: dict = {"data": ["a", "b", "c"]}

        _run_batch(inner, shared, parallel=True, max_concurrent=3, node_id="batch_node")

        # Extract node_output (like the engine does)
        node_output = dict(shared.get("batch_node", {}))

        collector = WorkflowTraceCollector(workflow_name="test-batch")
        collector.record_node_execution(
            node_id="batch_node",
            node_type="ShellNode",
            duration_ms=100.0,
            success=True,
            node_output=node_output,
        )

        assert len(collector.events) == 1
        event = collector.events[0]
        assert "node_output" in event
        assert "batch_metadata" in event["node_output"]

        metadata = event["node_output"]["batch_metadata"]
        assert metadata["parallel"] is True
        assert metadata["max_concurrent"] == 3
        assert metadata["execution_mode"] == "parallel"
        assert metadata["timing"] is not None


class TestBatchProgressCallbacks:
    """Test progress callback invocation during batch execution."""

    def test_sequential_batch_calls_progress_callback(self):
        """Progress callback called after each item in sequential mode."""
        events: list[dict] = []

        def track_callback(
            node_id: str,
            event: str,
            duration_ms: float | None = None,
            depth: int = 0,
            **kwargs,
        ):
            events.append({
                "node_id": node_id,
                "event": event,
                "duration_ms": duration_ms,
                "depth": depth,
                "batch_current": kwargs.get("batch_current"),
                "batch_total": kwargs.get("batch_total"),
                "batch_success": kwargs.get("batch_success"),
            })

        inner = MockInnerNode("test_node")
        shared: dict = {
            "data": ["a", "b", "c"],
            "__progress_callback__": track_callback,
        }

        _run_batch(inner, shared)

        progress_events = [e for e in events if e["event"] == "batch_progress"]
        assert len(progress_events) == 3

        assert progress_events[0]["batch_current"] == 1
        assert progress_events[0]["batch_total"] == 3
        assert progress_events[0]["batch_success"] is True
        assert progress_events[0]["node_id"] == "test_node"

        assert progress_events[2]["batch_current"] == 3
        assert progress_events[2]["batch_total"] == 3

    def test_sequential_batch_shows_item_failure(self):
        """Progress callback shows batch_success=False for failed items."""
        events: list[dict] = []

        def track_callback(node_id, event, duration_ms=None, depth=0, **kwargs):
            if event == "batch_progress":
                events.append({
                    "batch_current": kwargs.get("batch_current"),
                    "batch_success": kwargs.get("batch_success"),
                })

        inner = MockInnerNode("test_node", behavior="error_in_result")
        inner.error_index = 1

        shared: dict = {
            "data": ["a", "b", "c"],
            "__progress_callback__": track_callback,
        }

        _run_batch(inner, shared, error_handling="continue")

        assert len(events) == 3
        assert events[0]["batch_success"] is True
        assert events[1]["batch_success"] is False
        assert events[2]["batch_success"] is True

    def test_parallel_batch_calls_progress_callback(self):
        """Progress callback called as items complete in parallel mode."""
        events: list[dict] = []

        def track_callback(node_id, event, duration_ms=None, depth=0, **kwargs):
            if event == "batch_progress":
                events.append({
                    "batch_current": kwargs.get("batch_current"),
                    "batch_total": kwargs.get("batch_total"),
                    "batch_success": kwargs.get("batch_success"),
                })

        inner = ParallelMockInnerNode("test_node", delay=0.01)
        shared: dict = {
            "data": ["a", "b", "c", "d", "e"],
            "__progress_callback__": track_callback,
        }

        _run_batch(inner, shared, parallel=True, max_concurrent=3)

        assert len(events) == 5
        currents = sorted([e["batch_current"] for e in events])
        assert currents == [1, 2, 3, 4, 5]
        assert all(e["batch_total"] == 5 for e in events)
        assert all(e["batch_success"] is True for e in events)

    def test_callback_exception_ignored(self):
        """Exceptions in progress callback don't break batch execution."""
        call_count = 0

        def broken_callback(node_id, event, duration_ms=None, depth=0, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Callback error")

        inner = MockInnerNode("test_node")
        shared: dict = {
            "data": ["a", "b", "c"],
            "__progress_callback__": broken_callback,
        }

        _run_batch(inner, shared)

        assert call_count == 3
        assert shared["test_node"]["success_count"] == 3

    def test_no_callback_when_not_provided(self):
        """Batch works correctly when no callback is provided."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a", "b", "c"]}

        _run_batch(inner, shared)

        assert shared["test_node"]["success_count"] == 3

    def test_callback_receives_depth(self):
        """Progress callback receives correct depth from shared store."""
        events: list[dict] = []

        def track_callback(node_id, event, duration_ms=None, depth=0, **kwargs):
            if event == "batch_progress":
                events.append({"depth": depth})

        inner = MockInnerNode("test_node")
        shared: dict = {
            "data": ["a", "b"],
            "__progress_callback__": track_callback,
            "_pflow_depth": 2,
        }

        _run_batch(inner, shared)

        assert len(events) == 2
        assert all(e["depth"] == 2 for e in events)


class IndexCapturingMockNode:
    """Mock node that captures __index__ from shared store."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.captured_indices: list[int | None] = []

    def _run(self, shared: dict) -> str:
        index = shared.get("__index__")
        item = shared.get("item")
        self.captured_indices.append(index)
        shared[self.node_id] = {"response": item, "captured_index": index}
        return "default"


class TestBatchIndexInjection:
    """High-value tests for __index__ system variable injection."""

    def test_index_injected_sequential(self):
        """__index__ is injected in sequential batch execution."""
        inner = IndexCapturingMockNode("test_node")
        shared: dict = {"data": ["a", "b", "c"]}

        _run_batch(inner, shared)

        assert inner.captured_indices == [0, 1, 2]

    def test_index_injected_parallel(self):
        """__index__ is injected in parallel batch execution."""
        inner = IndexCapturingMockNode("test_node")
        shared: dict = {"data": ["x", "y", "z"]}

        _run_batch(inner, shared, parallel=True, max_concurrent=10)

        # In parallel mode, inner node is deep-copied per thread.
        # Results are stored at their original index position.
        for i, result in enumerate(shared["test_node"]["results"]):
            assert result["captured_index"] == i, f"Result at position {i} has wrong index"

    def test_index_zero_not_falsy(self):
        """Index 0 is injected correctly (critical edge case)."""
        inner = IndexCapturingMockNode("test_node")
        shared: dict = {"data": ["only_item"]}

        _run_batch(inner, shared)

        assert inner.captured_indices == [0]


class TestBatchPostErrorRouting:
    """Tests that batch returns 'default' and pushes warnings in continue mode."""

    def test_continue_mode_returns_default_with_errors(self):
        """continue mode with item errors still returns 'default'."""
        inner = MockInnerNode("test_node", behavior="error_on_index")
        inner.error_index = 1

        shared: dict = {"data": ["a", "b", "c"]}
        action, _ = _run_batch(inner, shared, error_handling="continue")

        assert action == "default"

    def test_continue_mode_pushes_warning(self):
        """continue mode with errors pushes a warning to shared['__warnings__']."""
        inner = MockInnerNode("test_node", behavior="error_on_index")
        inner.error_index = 1

        shared: dict = {"data": ["a", "b", "c"]}
        _run_batch(inner, shared, error_handling="continue")

        assert "test_node" in shared["__warnings__"]
        assert "error" in shared["__warnings__"]["test_node"]

    def test_continue_no_errors_no_warning(self):
        """continue mode with all items succeeding does not create __warnings__."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a", "b", "c"]}

        _run_batch(inner, shared, error_handling="continue")

        assert "__warnings__" not in shared

    def test_continue_mode_initializes_warnings_dict(self):
        """continue mode with errors creates __warnings__ when not present."""
        inner = MockInnerNode("test_node", behavior="error_on_index")
        inner.error_index = 0

        shared: dict = {"data": ["a", "b"]}
        assert "__warnings__" not in shared

        _run_batch(inner, shared, error_handling="continue")

        assert "__warnings__" in shared
        assert "test_node" in shared["__warnings__"]

    def test_fail_fast_still_raises(self):
        """fail_fast mode raises on first error (unchanged behavior)."""
        inner = MockInnerNode("test_node", behavior="error_on_index")
        inner.error_index = 1

        shared: dict = {"data": ["a", "b", "c"]}

        with pytest.raises(ValueError, match="Intentional error on item 1"):
            _run_batch(inner, shared, error_handling="fail_fast")


class TestBatchActionFallbackErrorDetection:
    """Tests for fallback error detection via action string from inner node's _run().

    When inner_node._run() returns an action string starting with "error" but the
    result dict has no "error" key, the batch node should detect this as an error.
    """

    class ErrorActionNode:
        """Node that returns 'error' action but writes no error key to result."""

        def __init__(self, node_id: str):
            self.node_id = node_id

        def _run(self, shared: dict) -> str:
            shared[self.node_id] = {"response": "partial output"}
            return "error"

        def __getstate__(self) -> dict:
            return self.__dict__.copy()

        def __setstate__(self, state: dict) -> None:
            self.__dict__.update(state)

    def test_exec_single_detects_error_via_action_string(self):
        """When _run() returns 'error' but result dict has no error key, all-fail abort fires."""
        inner = self.ErrorActionNode("test_node")
        shared: dict = {"data": ["a", "b"]}

        # All items return error action → success_count = 0 → all-fail abort
        with pytest.raises(RuntimeError, match="all 2 items failed"):
            _run_batch(inner, shared, error_handling="continue")

        # Batch output is written to shared store BEFORE the abort raise
        assert shared["test_node"]["error_count"] == 2
        assert shared["test_node"]["success_count"] == 0
        assert shared["test_node"]["results"] == []

    def test_exec_single_prefers_extract_error_over_action(self):
        """When both _extract_error finds an error AND action is 'error', _extract_error message wins."""

        class ErrorBothPathsNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                shared[self.node_id] = {"error": "Specific error from node", "response": "data"}
                return "error"

        inner = ErrorBothPathsNode("test_node")
        shared: dict = {"data": ["a"]}

        # All items failed -> all-fail abort raises RuntimeError.
        # The specific error message from _extract_error (not the generic action fallback)
        # should appear in the RuntimeError's error summary.
        with pytest.raises(RuntimeError, match="Specific error from node"):
            _run_batch(inner, shared, error_handling="continue")

    def test_exec_single_no_error_when_default_action(self):
        """When _run() returns 'default' and no error in result, item succeeds."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": ["a", "b"]}

        _run_batch(inner, shared)

        assert shared["test_node"]["error_count"] == 0
        assert shared["test_node"]["success_count"] == 2
        assert shared["test_node"]["errors"] is None

    def test_exec_single_no_error_when_none_action(self):
        """When _run() returns None, item succeeds (no false positive)."""

        class NoneActionNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> None:
                shared[self.node_id] = {"response": "ok"}
                return None

        inner = NoneActionNode("test_node")
        shared: dict = {"data": ["a"]}

        _run_batch(inner, shared)

        assert shared["test_node"]["error_count"] == 0
        assert shared["test_node"]["success_count"] == 1
        assert shared["test_node"]["errors"] is None

    def test_exec_single_with_node_detects_error_via_action(self):
        """Parallel path: all error-action items → all-fail abort."""
        inner = self.ErrorActionNode("test_node")
        shared: dict = {"data": ["a", "b", "c"]}

        # All items return error action → success_count = 0 → all-fail abort
        with pytest.raises(RuntimeError, match="all 3 items failed"):
            _run_batch(inner, shared, parallel=True, error_handling="continue")

        # Batch output is written to shared store BEFORE the abort raise
        assert shared["test_node"]["error_count"] == 3
        assert shared["test_node"]["success_count"] == 0
        assert shared["test_node"]["results"] == []

    def test_mixed_error_via_action_filters_correctly(self):
        """Some items succeed, some fail via action — success_count and results are correct."""

        class MixedActionNode:
            """Succeeds on even indices, returns error action on odd indices."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                idx = shared.get("__index__", 0)
                shared[self.node_id] = {"response": f"output-{idx}"}
                return "error" if idx % 2 == 1 else "default"

        inner = MixedActionNode("test_node")
        shared: dict = {"data": ["a", "b", "c", "d"]}

        _run_batch(inner, shared, error_handling="continue")

        output = shared["test_node"]
        # Items at indices 1 and 3 fail via action — filtered from results
        assert output["count"] == 4
        assert output["success_count"] == 2
        assert output["error_count"] == 2
        assert len(output["results"]) == 2
        assert output["results"][0]["response"] == "output-0"
        assert output["results"][1]["response"] == "output-2"
        # Invariant holds
        assert output["success_count"] + output["error_count"] == output["count"]

    def test_exec_single_fail_fast_raises_on_action_error(self):
        """fail_fast mode raises RuntimeError when action-string fallback detects error."""
        inner = self.ErrorActionNode("test_node")
        shared: dict = {"data": ["a"]}

        with pytest.raises(RuntimeError, match="Node returned error action"):
            _run_batch(inner, shared, error_handling="fail_fast")


class TestBatchSubWorkflowErrorPropagationIntegration:
    """Integration test: batch -> workflow node -> failing child workflow.

    Exercises the REAL propagation chain (compile_workflow + WorkflowEngine ->
    WorkflowExecutor -> batch _extract_error) with no mocking of the error path.
    """

    def test_batch_workflow_child_error_detected_as_batch_error(self):
        """A batch calling a sub-workflow where the child fails should report errors, not success."""
        from pflow.registry.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        registry = Registry()

        child_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "fail",
                    "type": "shell",
                    "params": {"command": "exit 1"},
                    "purpose": "Shell node that always fails with non-zero exit code",
                }
            ],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch-call",
                    "type": "workflow",
                    "params": {
                        "workflow_ir": child_ir,
                    },
                    "batch": {
                        "items": ["a", "b"],
                        "error_handling": "continue",
                    },
                    "purpose": "Batch calling a sub-workflow that always fails",
                }
            ],
            "edges": [],
        }

        workflow = compile_workflow(parent_ir, registry=registry)
        shared: dict = dict(workflow.resolved_defaults)

        with pytest.raises(RuntimeError, match="all 2 items failed"):
            engine = WorkflowEngine()
            engine.run(workflow, shared)

    def test_batch_workflow_partial_failure_with_continue(self):
        """Partial batch failure: some child sub-workflows succeed, some fail."""
        from pflow.registry.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        registry = Registry()

        child_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "check",
                    "type": "shell",
                    "params": {
                        "command": 'if [ "${item}" = "fail-b" ]; then exit 1; fi; echo "${item}"',
                    },
                    "purpose": "Shell node that fails when item is fail-b, otherwise echoes it",
                }
            ],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch-call",
                    "type": "workflow",
                    "params": {
                        "workflow_ir": child_ir,
                    },
                    "batch": {
                        "items": ["good-a", "fail-b", "good-c"],
                        "error_handling": "continue",
                    },
                    "purpose": "Batch calling a sub-workflow with partial failures expected",
                }
            ],
            "edges": [],
        }

        workflow = compile_workflow(parent_ir, registry=registry)
        shared: dict = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        batch_output = shared["batch-call"]

        assert batch_output["count"] == 3
        assert batch_output["success_count"] == 2
        assert batch_output["error_count"] == 1

        assert batch_output["errors"] is not None
        assert len(batch_output["errors"]) == 1
        assert batch_output["errors"][0]["index"] == 1
        assert batch_output["errors"][0]["item"] == "fail-b"

        # results contains only successful items — failed sub-workflow filtered out
        results = batch_output["results"]
        assert len(results) == 2

        assert results[0]["item"] == "good-a"
        assert results[0].get("error") is None

        assert results[1]["item"] == "good-c"
        assert results[1].get("error") is None

    def test_batch_workflow_partial_failure_parallel(self):
        """Parallel variant of partial-fail: exercises the parallel code path."""
        from pflow.registry.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        registry = Registry()

        child_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "check",
                    "type": "shell",
                    "params": {
                        "command": 'if [ "${item}" = "fail-b" ]; then exit 1; fi; echo "${item}"',
                    },
                    "purpose": "Shell node that fails when item is fail-b, otherwise echoes it",
                }
            ],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch-call",
                    "type": "workflow",
                    "params": {
                        "workflow_ir": child_ir,
                    },
                    "batch": {
                        "items": ["good-a", "fail-b", "good-c"],
                        "error_handling": "continue",
                        "parallel": True,
                    },
                    "purpose": "Parallel batch calling a sub-workflow with partial failures",
                }
            ],
            "edges": [],
        }

        workflow = compile_workflow(parent_ir, registry=registry)
        shared: dict = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        batch_output = shared["batch-call"]

        assert batch_output["count"] == 3
        assert batch_output["success_count"] == 2
        assert batch_output["error_count"] == 1

        assert len(batch_output["errors"]) == 1
        assert batch_output["errors"][0]["item"] == "fail-b"

        # results contains only successful items — failed sub-workflow filtered out
        results = batch_output["results"]
        assert len(results) == 2

        assert results[0]["item"] == "good-a"
        assert results[0].get("error") is None

        assert results[1]["item"] == "good-c"
        assert results[1].get("error") is None

    def test_batch_workflow_all_fail_with_continue(self):
        """All items fail with error_handling: continue -- aborts with RuntimeError."""
        from pflow.registry.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        registry = Registry()

        child_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "always-fail",
                    "type": "shell",
                    "params": {"command": "exit 1"},
                    "purpose": "Shell node that always fails with exit code 1",
                }
            ],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch-call",
                    "type": "workflow",
                    "params": {"workflow_ir": child_ir},
                    "batch": {
                        "items": ["a", "b", "c"],
                        "error_handling": "continue",
                    },
                    "purpose": "Batch where every item fails -- continue mode still aborts",
                }
            ],
            "edges": [],
        }

        workflow = compile_workflow(parent_ir, registry=registry)
        shared: dict = dict(workflow.resolved_defaults)

        with pytest.raises(RuntimeError, match="all 3 items failed"):
            engine = WorkflowEngine()
            engine.run(workflow, shared)

    def test_downstream_batch_iterates_only_successes(self):
        """Full pipeline: partial-failure batch → downstream batch iterates filtered results.

        This is the core use case from GH #159. Tests the full integration:
        _aggregate_batch_results filtering → shared store write → template resolution
        of ${step1.results} → downstream batch receiving only successes.
        """
        from pflow.registry.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        registry = Registry()

        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "step1",
                    "type": "shell",
                    "params": {
                        "command": 'if [ "${item}" = "bad" ]; then exit 1; fi; echo "s1-${item}"',
                    },
                    "batch": {
                        "items": ["ok-a", "bad", "ok-c"],
                        "error_handling": "continue",
                    },
                    "purpose": "Batch with partial failure to produce filtered results",
                },
                {
                    "id": "step2",
                    "type": "shell",
                    "params": {
                        "command": 'echo "s2-${item.stdout}"',
                    },
                    "batch": {
                        "items": "${step1.results}",
                    },
                    "purpose": "Downstream batch iterating only successful results from step1",
                },
            ],
            "edges": [{"from": "step1", "to": "step2"}],
        }

        workflow = compile_workflow(ir, registry=registry)
        shared: dict = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # Step 1: 3 attempted, 2 succeeded, 1 failed
        s1 = shared["step1"]
        assert s1["count"] == 3
        assert s1["success_count"] == 2
        assert s1["error_count"] == 1

        # Step 2: received only 2 items (the successes from step1)
        s2 = shared["step2"]
        assert s2["count"] == 2
        assert s2["success_count"] == 2
        assert s2["error_count"] == 0

        # Verify the data flowed correctly through the chain
        outputs = sorted([r["stdout"] for r in s2["results"]])
        assert outputs == ["s2-s1-ok-a", "s2-s1-ok-c"]


class TestDetectEmptyOutputItems:
    """Unit tests for _detect_empty_output_items function."""

    def test_returns_empty_when_all_items_have_content(self):
        """All items have non-empty content keys -- returns empty list."""
        exec_res = [
            {"response": "hello", "item": "a"},
            {"result": "world", "item": "b"},
            {"stdout": "output", "item": "c"},
            {"output": "data", "item": "d"},
        ]
        assert _detect_empty_output_items(exec_res, []) == []

    def test_detects_items_with_empty_string_content(self):
        """Items where all content keys are empty strings are detected."""
        exec_res = [
            {"response": "good", "item": "a"},
            {"response": "", "result": "", "stdout": "", "output": "", "item": "b"},
            {"response": "good", "item": "c"},
        ]
        result = _detect_empty_output_items(exec_res, [])
        assert result == [1]

    def test_detects_items_with_only_meta_keys(self):
        """Items with only batch meta keys (item, _-prefixed) are detected as empty."""
        exec_res = [
            {"response": "good", "item": "a"},
            {"item": "b", "_trace_id": "abc"},
        ]
        result = _detect_empty_output_items(exec_res, [])
        assert result == [1]

    def test_skips_none_results(self):
        """None results (exception failures) are skipped, not counted as empty."""
        exec_res = [
            {"response": "good", "item": "a"},
            None,
            {"response": "good", "item": "c"},
        ]
        result = _detect_empty_output_items(exec_res, [])
        assert result == []

    def test_skips_items_in_error_list(self):
        """Items whose indices appear in the errors list are skipped."""
        exec_res = [
            {"response": "good", "item": "a"},
            {"item": "b"},
            {"response": "good", "item": "c"},
        ]
        errors = [{"index": 1, "item": "b", "error": "something failed"}]
        result = _detect_empty_output_items(exec_res, errors)
        assert result == []

    def test_skips_items_with_error_key(self):
        """Items with an 'error' key in their result dict are skipped."""
        exec_res = [
            {"response": "good", "item": "a"},
            {"error": "Processing failed", "item": "b"},
            {"response": "good", "item": "c"},
        ]
        result = _detect_empty_output_items(exec_res, [])
        assert result == []

    def test_detects_items_with_none_content_values(self):
        """Items where content keys have None values are detected as empty."""
        exec_res = [
            {"response": None, "result": None, "item": "a"},
            {"response": "good", "item": "b"},
        ]
        result = _detect_empty_output_items(exec_res, [])
        assert result == [0]

    def test_non_standard_output_keys_not_flagged(self):
        """Nodes writing to non-standard keys are NOT false positives."""
        exec_res = [
            {"content": "file data", "path": "output/foo.txt", "item": "foo.txt"},
            {"branch": "main", "changes": ["file.py"], "item": "repo1"},
            {"analysis": {"score": 0.8}, "item": "doc1"},
        ]
        result = _detect_empty_output_items(exec_res, [])
        assert result == [], "Non-standard output keys should count as content"


class TestEmptyOutputWarnings:
    """Tests for empty output warnings via _push_batch_warnings."""

    def test_empty_output_pushes_warning(self):
        """Batch items that succeed with empty output push a warning to __warnings__."""

        class EmptyOutputNode:
            def __init__(self, node_id: str, empty_indices: set[int]):
                self.node_id = node_id
                self._empty_indices = empty_indices

            def _run(self, shared: dict) -> str:
                idx = shared.get("__index__", 0)
                if idx in self._empty_indices:
                    shared[self.node_id] = {"result": ""}
                else:
                    shared[self.node_id] = {"response": f"content-{idx}"}
                return "default"

        inner = EmptyOutputNode("test_node", empty_indices={0, 2})
        shared: dict = {"data": ["a", "b", "c"]}

        _run_batch(inner, shared)

        assert "__warnings__" in shared
        assert "test_node" in shared["__warnings__"]
        warning = shared["__warnings__"]["test_node"]
        assert "2 item(s) produced empty output" in warning
        assert "items 0, 2" in warning

    def test_empty_output_combined_with_errors(self):
        """Both errors AND empty output are combined in a single warning message."""

        class MixedResultNode:
            def __init__(self, node_id: str):
                self.node_id = node_id
                self._call_count = 0

            def _run(self, shared: dict) -> str:
                idx = shared.get("__index__", 0)
                self._call_count += 1
                if idx == 0:
                    raise ValueError("Intentional error")
                elif idx == 1:
                    shared[self.node_id] = {"result": ""}
                else:
                    shared[self.node_id] = {"response": "good"}
                return "default"

        inner = MixedResultNode("test_node")
        shared: dict = {"data": ["a", "b", "c"]}

        _run_batch(inner, shared, error_handling="continue")

        assert "__warnings__" in shared
        warning = shared["__warnings__"]["test_node"]
        assert "error" in warning.lower()
        assert "empty output" in warning

    def test_empty_input_list_pushes_warning(self):
        """When batch receives an empty input list, a warning about 0 items is pushed."""
        inner = MockInnerNode("test_node")
        shared: dict = {"data": []}

        _run_batch(inner, shared, error_handling="continue")

        assert "test_node" in shared.get("__warnings__", {})
        assert "0 items" in shared["__warnings__"]["test_node"]
