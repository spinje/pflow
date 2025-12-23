"""Tests for PflowBatchNode batch processing."""

import pytest

from pflow.runtime.batch_node import PflowBatchNode


class MockInnerNode:
    """Mock node that simulates pflow node behavior.

    Writes results to shared[node_id] to mimic NamespacedNodeWrapper behavior.
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

        # Get item from shared store (injected by batch node)
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

        # Write to namespace (simulating NamespacedNodeWrapper)
        shared[self.node_id] = result
        return "default"


class TestPflowBatchNodeBasic:
    """Basic batch processing tests."""

    def test_batch_empty_items(self):
        """Empty array produces empty results with zero counts."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": []}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        assert shared["test_node"]["results"] == []
        assert shared["test_node"]["count"] == 0
        assert shared["test_node"]["success_count"] == 0
        assert shared["test_node"]["error_count"] == 0
        assert shared["test_node"]["errors"] is None

    def test_batch_single_item(self):
        """Single item processed correctly."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["hello"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        assert len(shared["test_node"]["results"]) == 1
        assert shared["test_node"]["results"][0] == {"response": "hello"}
        assert shared["test_node"]["count"] == 1
        assert shared["test_node"]["success_count"] == 1
        assert shared["test_node"]["error_count"] == 0

    def test_batch_multiple_items_in_order(self):
        """Multiple items processed in input order."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["a", "b", "c"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        assert shared["test_node"]["count"] == 3
        assert shared["test_node"]["success_count"] == 3
        assert shared["test_node"]["results"][0] == {"response": "a"}
        assert shared["test_node"]["results"][1] == {"response": "b"}
        assert shared["test_node"]["results"][2] == {"response": "c"}


class TestItemAliasInjection:
    """Tests for item alias injection into isolated context."""

    def test_default_item_alias(self):
        """Default alias 'item' is available in context."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["value1"]}
        items = batch.prep(shared)
        results = batch._exec(items)

        # Inner node received item via "item" alias
        assert results[0] == {"response": "value1"}

    def test_custom_item_alias(self):
        """Custom alias is used when 'as' is specified."""

        class AliasAwareNode:
            """Node that checks for specific alias."""

            def __init__(self, node_id: str, expected_alias: str):
                self.node_id = node_id
                self.expected_alias = expected_alias

            def _run(self, shared: dict) -> str:
                item = shared.get(self.expected_alias)
                shared[self.node_id] = {"response": item, "alias_used": self.expected_alias}
                return "default"

        inner = AliasAwareNode("test_node", "file")
        batch = PflowBatchNode(inner, "test_node", {"items": "${files}", "as": "file"})

        shared = {"files": ["doc1.txt", "doc2.txt"]}
        items = batch.prep(shared)
        results = batch._exec(items)

        assert results[0] == {"response": "doc1.txt", "alias_used": "file"}
        assert results[1] == {"response": "doc2.txt", "alias_used": "file"}


class TestIsolatedContext:
    """Tests for isolated shared store context per item."""

    def test_items_dont_pollute_each_other(self):
        """Each item execution has isolated context."""

        class AccumulatorNode:
            """Node that would accumulate if contexts were shared."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                # Try to read previous item's value (should not exist)
                prev_item = shared.get("previous_item")
                current = shared.get("item")

                # Store current as "previous" for next iteration (in isolated context)
                shared["previous_item"] = current
                shared[self.node_id] = {"response": current, "saw_previous": prev_item}
                return "default"

        inner = AccumulatorNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": [1, 2, 3]}
        items = batch.prep(shared)
        results = batch._exec(items)

        # Each item should NOT see previous item due to isolation
        assert results[0]["saw_previous"] is None
        assert results[1]["saw_previous"] is None
        assert results[2]["saw_previous"] is None

    def test_original_shared_unchanged_during_iteration(self):
        """Original shared store is not modified during batch iteration."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["a", "b"], "original_key": "original_value"}
        items = batch.prep(shared)

        # Check that "item" alias doesn't exist in original shared before post
        batch._exec(items)
        # Note: We can't easily check mid-iteration, but we verify alias isn't in original after
        assert "item" not in shared  # Alias was only in isolated copies

    def test_special_keys_shared_across_items(self):
        """Special keys like __llm_calls__ are shared (shallow copy behavior)."""

        class LLMTrackingNode:
            """Node that appends to __llm_calls__."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                # Append to __llm_calls__ (should be the SAME list across items)
                if "__llm_calls__" not in shared:
                    shared["__llm_calls__"] = []
                shared["__llm_calls__"].append({"model": "test", "tokens": 100})
                shared[self.node_id] = {"response": "ok"}
                return "default"

        inner = LLMTrackingNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["a", "b", "c"], "__llm_calls__": []}
        items = batch.prep(shared)
        batch._exec(items)

        # All 3 items should have appended to the SAME list
        assert len(shared["__llm_calls__"]) == 3


class TestErrorHandling:
    """Tests for error handling modes."""

    def test_fail_fast_stops_on_exception(self):
        """fail_fast mode stops execution on first exception."""
        inner = MockInnerNode("test_node", behavior="error_on_index")
        inner.error_index = 1  # Error on second item

        batch = PflowBatchNode(
            inner, "test_node", {"items": "${data}", "error_handling": "fail_fast"}
        )

        shared = {"data": ["a", "b", "c"]}
        items = batch.prep(shared)

        with pytest.raises(ValueError, match="Intentional error on item 1"):
            batch._exec(items)

        # Only first item was processed
        assert inner.call_count == 2  # Called for item 0 and 1 (error on 1)

    def test_continue_processes_all_items(self):
        """continue mode processes all items even after errors."""
        inner = MockInnerNode("test_node", behavior="error_on_index")
        inner.error_index = 1  # Error on second item

        batch = PflowBatchNode(
            inner, "test_node", {"items": "${data}", "error_handling": "continue"}
        )

        shared = {"data": ["a", "b", "c"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # All 3 items attempted
        assert inner.call_count == 3
        assert shared["test_node"]["count"] == 3
        assert shared["test_node"]["success_count"] == 2
        assert shared["test_node"]["error_count"] == 1

        # Failed item has None result
        assert results[0] == {"response": "a"}
        assert results[1] is None
        assert results[2] == {"response": "c"}

        # Error recorded
        assert len(shared["test_node"]["errors"]) == 1
        assert shared["test_node"]["errors"][0]["index"] == 1
        assert shared["test_node"]["errors"][0]["item"] == "b"
        assert "Intentional error" in shared["test_node"]["errors"][0]["error"]

    def test_fail_fast_on_error_in_result(self):
        """fail_fast mode triggers on error key in result dict."""
        inner = MockInnerNode("test_node", behavior="error_in_result")
        inner.error_index = 0  # First item returns error

        batch = PflowBatchNode(
            inner, "test_node", {"items": "${data}", "error_handling": "fail_fast"}
        )

        shared = {"data": ["a", "b"]}
        items = batch.prep(shared)

        with pytest.raises(RuntimeError, match="Item 0 failed"):
            batch._exec(items)

    def test_continue_records_error_in_result(self):
        """continue mode records error from result dict."""
        inner = MockInnerNode("test_node", behavior="error_in_result")
        inner.error_index = 1  # Second item returns error

        batch = PflowBatchNode(
            inner, "test_node", {"items": "${data}", "error_handling": "continue"}
        )

        shared = {"data": ["a", "b", "c"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # Error-containing result is still in results (not None)
        assert results[1] == {"error": "Error: Processing failed for item b"}

        # But it's counted as error and recorded
        assert shared["test_node"]["success_count"] == 2
        assert shared["test_node"]["error_count"] == 1
        assert shared["test_node"]["errors"][0]["index"] == 1


class TestResultStructure:
    """Tests for output result structure."""

    def test_result_structure_complete(self):
        """Result has all required fields."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["a", "b"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        result = shared["test_node"]
        assert "results" in result
        assert "count" in result
        assert "success_count" in result
        assert "error_count" in result
        assert "errors" in result  # None when no errors

    def test_errors_none_when_no_errors(self):
        """errors field is None when all items succeed."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["a", "b"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        assert shared["test_node"]["errors"] is None

    def test_none_is_valid_success(self):
        """None result from node is treated as success, not error."""
        inner = MockInnerNode("test_node", behavior="return_none")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["a", "b"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # None in response is valid (node returned None as legitimate value)
        assert results[0] == {"response": None}
        assert results[1] == {"response": None}
        assert shared["test_node"]["success_count"] == 2
        assert shared["test_node"]["error_count"] == 0


class TestItemsResolution:
    """Tests for items template resolution."""

    def test_items_from_simple_path(self):
        """Items resolved from simple variable path."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${files}"})

        shared = {"files": ["a.txt", "b.txt"]}
        items = batch.prep(shared)

        assert items == ["a.txt", "b.txt"]

    def test_items_from_nested_path(self):
        """Items resolved from nested path."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${list_files.output}"})

        shared = {"list_files": {"output": ["x", "y", "z"]}}
        items = batch.prep(shared)

        assert items == ["x", "y", "z"]

    def test_items_not_array_raises(self):
        """ValueError raised when items doesn't resolve to array."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": "not_an_array"}

        with pytest.raises(ValueError, match="Batch items must be an array"):
            batch.prep(shared)

    def test_items_none_raises(self):
        """ValueError raised when items resolves to None."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${missing}"})

        shared = {}

        with pytest.raises(ValueError, match="resolved to None"):
            batch.prep(shared)

    def test_items_dict_raises(self):
        """ValueError raised when items resolves to dict."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": {"not": "array"}}

        with pytest.raises(ValueError, match="got dict"):
            batch.prep(shared)


class TestComplexItems:
    """Tests with complex item objects."""

    def test_complex_object_items(self):
        """Items can be complex objects with nested fields."""

        class FieldAccessNode:
            """Node that accesses item.name field."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                name = item.get("name") if isinstance(item, dict) else None
                shared[self.node_id] = {"response": name}
                return "default"

        inner = FieldAccessNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${records}"})

        shared = {
            "records": [
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25},
            ]
        }
        items = batch.prep(shared)
        results = batch._exec(items)

        assert results[0] == {"response": "Alice"}
        assert results[1] == {"response": "Bob"}

    def test_items_with_none_values(self):
        """Array containing None values is processed."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": [None, "value", None]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        assert shared["test_node"]["count"] == 3
        assert results[0] == {"response": None}
        assert results[1] == {"response": "value"}
        assert results[2] == {"response": None}


class TestExtractError:
    """Tests for _extract_error helper method."""

    def test_extract_error_from_dict(self):
        """Error extracted from dict with error key."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}"})

        assert batch._extract_error({"error": "Something failed"}) == "Something failed"
        assert batch._extract_error({"error": "Error: Bad input"}) == "Error: Bad input"

    def test_extract_error_none_for_success(self):
        """None returned for successful results."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}"})

        assert batch._extract_error({"response": "ok"}) is None
        assert batch._extract_error({"data": 123}) is None
        assert batch._extract_error({}) is None

    def test_extract_error_none_for_non_dict(self):
        """None returned for non-dict results."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}"})

        assert batch._extract_error("string") is None
        assert batch._extract_error(123) is None
        assert batch._extract_error(None) is None
        assert batch._extract_error([1, 2, 3]) is None

    def test_extract_error_falsy_error_key(self):
        """Falsy error values are not treated as errors."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}"})

        # Empty string, None, False, 0 are falsy
        assert batch._extract_error({"error": ""}) is None
        assert batch._extract_error({"error": None}) is None
        assert batch._extract_error({"error": False}) is None
        assert batch._extract_error({"error": 0}) is None


class TestDefaultValues:
    """Tests for default configuration values."""

    def test_default_alias_is_item(self):
        """Default alias is 'item' when 'as' not specified."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}"})
        assert batch.item_alias == "item"

    def test_default_error_handling_is_fail_fast(self):
        """Default error handling is 'fail_fast' when not specified."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}"})
        assert batch.error_handling == "fail_fast"

    def test_custom_alias_preserved(self):
        """Custom alias from config is used."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "as": "record"})
        assert batch.item_alias == "record"

    def test_continue_error_handling_preserved(self):
        """Continue error handling from config is used."""
        batch = PflowBatchNode(
            MockInnerNode("n"), "n", {"items": "${x}", "error_handling": "continue"}
        )
        assert batch.error_handling == "continue"
