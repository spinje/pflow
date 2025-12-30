"""Tests for PflowBatchNode batch processing."""

import threading
import time

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

        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "error_handling": "fail_fast"})

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

        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "error_handling": "continue"})

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

        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "error_handling": "fail_fast"})

        shared = {"data": ["a", "b"]}
        items = batch.prep(shared)

        with pytest.raises(RuntimeError, match=r"Batch 'test_node' failed at item \[0\]"):
            batch._exec(items)

    def test_continue_records_error_in_result(self):
        """continue mode records error from result dict."""
        inner = MockInnerNode("test_node", behavior="error_in_result")
        inner.error_index = 1  # Second item returns error

        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "error_handling": "continue"})

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
        """TypeError raised when items doesn't resolve to array."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": "not_an_array"}

        with pytest.raises(TypeError, match="Batch items must be an array"):
            batch.prep(shared)

    def test_items_none_raises(self):
        """ValueError raised when items resolves to None."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${missing}"})

        shared = {}

        with pytest.raises(ValueError, match="resolved to None"):
            batch.prep(shared)

    def test_items_dict_raises(self):
        """TypeError raised when items resolves to dict."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": {"not": "array"}}

        with pytest.raises(TypeError, match="got dict"):
            batch.prep(shared)


class TestItemsJsonAutoParsing:
    """Tests for JSON string auto-parsing in batch.items.

    Shell nodes output text to stdout. When that text is valid JSON,
    batch processing should auto-parse it to enable shell → batch patterns.
    """

    def test_json_array_string_parsed(self):
        """JSON array string is auto-parsed to list."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${shell.stdout}"})

        # Shell node outputs JSON as a string
        shared = {"shell": {"stdout": '["item1", "item2", "item3"]'}}
        items = batch.prep(shared)

        assert items == ["item1", "item2", "item3"]
        assert len(items) == 3

    def test_json_array_with_trailing_newline(self):
        """JSON string with trailing newline (common shell output) is parsed."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${cmd.stdout}"})

        # Shell output typically has trailing newline
        shared = {"cmd": {"stdout": '["a", "b"]\n'}}
        items = batch.prep(shared)

        assert items == ["a", "b"]

    def test_json_array_with_whitespace(self):
        """JSON string with leading/trailing whitespace is parsed."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": '  \n  ["x", "y", "z"]  \n  '}
        items = batch.prep(shared)

        assert items == ["x", "y", "z"]

    def test_json_complex_objects_parsed(self):
        """JSON array of objects is parsed correctly."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${split.sections}"})

        json_str = '[{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]'
        shared = {"split": {"sections": json_str}}
        items = batch.prep(shared)

        assert items == [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]
        assert items[0]["name"] == "first"

    def test_invalid_json_fails_with_type_error(self):
        """Invalid JSON string fails at type check with clear error."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        # Invalid JSON - missing closing bracket
        shared = {"data": '["item1", "item2"'}

        with pytest.raises(TypeError, match="Batch items must be an array, got str"):
            batch.prep(shared)

    def test_json_object_fails_with_type_error(self):
        """JSON object string (not array) fails at type check."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        # Valid JSON but not an array
        shared = {"data": '{"key": "value"}'}

        with pytest.raises(TypeError, match="Batch items must be an array, got str"):
            batch.prep(shared)

    def test_non_json_string_fails_with_type_error(self):
        """Non-JSON string fails at type check."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": "just a plain string"}

        with pytest.raises(TypeError, match="Batch items must be an array, got str"):
            batch.prep(shared)

    def test_already_list_not_affected(self):
        """Already-parsed list is not affected by JSON parsing logic."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        # Already a Python list (not a JSON string)
        shared = {"data": ["already", "a", "list"]}
        items = batch.prep(shared)

        assert items == ["already", "a", "list"]

    def test_empty_json_array_parsed(self):
        """Empty JSON array string is parsed correctly."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": "[]"}
        items = batch.prep(shared)

        assert items == []

    def test_nested_json_arrays_parsed(self):
        """Nested JSON arrays are parsed correctly."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": "[[1, 2], [3, 4], [5, 6]]"}
        items = batch.prep(shared)

        assert items == [[1, 2], [3, 4], [5, 6]]


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


class TestInputOutputFormats:
    """Tests for various input item types and output formats."""

    def test_number_items(self):
        """Numeric items are processed correctly."""
        inner = MockInnerNode("test_node", behavior="transform")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": [1, 2, 3]}
        items = batch.prep(shared)
        results = batch._exec(items)

        assert results[0] == {"response": 2}  # 1 * 2
        assert results[1] == {"response": 4}  # 2 * 2
        assert results[2] == {"response": 6}  # 3 * 2

    def test_float_items(self):
        """Float items are processed correctly."""
        inner = MockInnerNode("test_node", behavior="transform")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": [1.5, 2.5, 3.5]}
        items = batch.prep(shared)
        results = batch._exec(items)

        assert results[0] == {"response": 3.0}
        assert results[1] == {"response": 5.0}
        assert results[2] == {"response": 7.0}

    def test_mixed_type_items(self):
        """Mixed type items (strings, numbers, dicts, None) are processed."""
        inner = MockInnerNode("test_node", behavior="echo")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": [1, "two", {"three": 3}, None, True]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        assert results[0] == {"response": 1}
        assert results[1] == {"response": "two"}
        assert results[2] == {"response": {"three": 3}}
        assert results[3] == {"response": None}
        assert results[4] == {"response": True}
        assert shared["test_node"]["count"] == 5
        assert shared["test_node"]["success_count"] == 5

    def test_nested_array_items(self):
        """Nested array items are processed correctly."""
        inner = MockInnerNode("test_node", behavior="echo")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": [[1, 2], [3, 4], [5, 6]]}
        items = batch.prep(shared)
        results = batch._exec(items)

        assert results[0] == {"response": [1, 2]}
        assert results[1] == {"response": [3, 4]}
        assert results[2] == {"response": [5, 6]}

    def test_boolean_items(self):
        """Boolean items are processed correctly."""

        class BooleanEchoNode:
            """Node that correctly handles boolean items (including False)."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                # Use get with explicit default to handle False correctly
                item = shared.get("item")  # Returns None if missing, False if False
                shared[self.node_id] = {"response": item}
                return "default"

        inner = BooleanEchoNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": [True, False, True]}
        items = batch.prep(shared)
        results = batch._exec(items)

        assert results[0] == {"response": True}
        assert results[1] == {"response": False}
        assert results[2] == {"response": True}

    def test_string_output_wrapped_in_dict(self):
        """When node writes string directly to namespace, it's wrapped in {'value': ...}."""

        class StringOutputNode:
            """Node that writes a string directly to namespace."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                shared[self.node_id] = f"processed_{item}"  # String, not dict
                return "default"

        inner = StringOutputNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["a", "b"]}
        items = batch.prep(shared)
        results = batch._exec(items)

        # String output should be wrapped in {"value": ...}
        assert results[0] == {"value": "processed_a"}
        assert results[1] == {"value": "processed_b"}

    def test_number_output_wrapped_in_dict(self):
        """When node writes number directly to namespace, it's wrapped in {'value': ...}."""

        class NumberOutputNode:
            """Node that writes a number directly to namespace."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                shared[self.node_id] = item * 10  # Number, not dict
                return "default"

        inner = NumberOutputNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": [1, 2, 3]}
        items = batch.prep(shared)
        results = batch._exec(items)

        assert results[0] == {"value": 10}
        assert results[1] == {"value": 20}
        assert results[2] == {"value": 30}

    def test_list_output_wrapped_in_dict(self):
        """When node writes list directly to namespace, it's wrapped in {'value': ...}."""

        class ListOutputNode:
            """Node that writes a list directly to namespace."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                shared[self.node_id] = [item, item]  # List, not dict
                return "default"

        inner = ListOutputNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["x", "y"]}
        items = batch.prep(shared)
        results = batch._exec(items)

        assert results[0] == {"value": ["x", "x"]}
        assert results[1] == {"value": ["y", "y"]}

    def test_empty_dict_output(self):
        """When node writes empty dict to namespace, it's returned as-is."""

        class EmptyDictNode:
            """Node that writes empty dict to namespace."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                shared[self.node_id] = {}  # Empty dict
                return "default"

        inner = EmptyDictNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["a", "b"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        assert results[0] == {}
        assert results[1] == {}
        # Empty dict is not an error, just no output
        assert shared["test_node"]["success_count"] == 2

    def test_node_writes_nothing(self):
        """When node doesn't write to namespace, result is empty dict."""

        class SilentNode:
            """Node that writes nothing to namespace."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                # Does nothing - doesn't write to shared[self.node_id]
                return "default"

        inner = SilentNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["a", "b"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # Result is None from namespace, converted to {}
        assert results[0] == {}
        assert results[1] == {}
        assert shared["test_node"]["success_count"] == 2


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
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "error_handling": "continue"})
        assert batch.error_handling == "continue"


# =============================================================================
# Phase 2 Tests: Parallel Execution
# =============================================================================


class ParallelMockInnerNode:
    """Enhanced mock node for parallel testing with delays and thread tracking.

    Note: This node is designed to be deep-copied in parallel execution.
    It uses __getstate__/__setstate__ to handle the threading.Lock which
    cannot be pickled.
    """

    def __init__(self, node_id: str, delay: float = 0, behavior: str = "echo"):
        """Initialize parallel mock node.

        Args:
            node_id: Node identifier for namespacing
            delay: Seconds to sleep during execution (for timing tests)
            behavior: One of:
                - "echo": Return item value as response
                - "echo_with_id": Return item with thread info
                - "error_on_index": Raise exception on specific index
                - "error_in_result": Write error key to result on specific index
                - "variable_delay": Delay based on item value
        """
        self.node_id = node_id
        self.delay = delay
        self.behavior = behavior
        self.error_index: int | None = None
        self.call_count = 0
        self.thread_ids: list[int] = []
        self._lock = threading.Lock()

    def __getstate__(self):
        """Return state for pickling, excluding the lock."""
        state = self.__dict__.copy()
        del state["_lock"]
        return state

    def __setstate__(self, state):
        """Restore state from pickling, recreating the lock."""
        self.__dict__.update(state)
        self._lock = threading.Lock()

    def _get_item(self, shared: dict):
        """Extract item from shared store, handling falsy values."""
        for key in ("item", "file", "record"):
            if key in shared:
                return shared[key]
        return None

    def _apply_delay(self, item):
        """Apply configured or variable delay."""
        if self.behavior == "variable_delay" and isinstance(item, dict):
            time.sleep(item.get("delay", 0))
        elif self.delay > 0:
            time.sleep(self.delay)

    def _run(self, shared: dict) -> str:
        """Execute mock node logic with thread tracking."""
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
        """Compute result based on behavior."""
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


class TestPhase2ConfigDefaults:
    """Tests for Phase 2 configuration defaults."""

    def test_default_parallel_is_false(self):
        """Default parallel is False (sequential execution)."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}"})
        assert batch.parallel is False

    def test_default_max_concurrent_is_10(self):
        """Default max_concurrent is 10."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}"})
        assert batch.max_concurrent == 10

    def test_default_max_retries_is_1(self):
        """Default max_retries is 1 (no retry)."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}"})
        assert batch.max_retries == 1

    def test_default_retry_wait_is_0(self):
        """Default retry_wait is 0."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}"})
        assert batch.retry_wait == 0

    def test_custom_parallel_true(self):
        """Custom parallel=True from config is used."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "parallel": True})
        assert batch.parallel is True

    def test_custom_max_concurrent(self):
        """Custom max_concurrent from config is used."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "max_concurrent": 5})
        assert batch.max_concurrent == 5

    def test_custom_max_retries(self):
        """Custom max_retries from config is used."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "max_retries": 3})
        assert batch.max_retries == 3

    def test_custom_retry_wait(self):
        """Custom retry_wait from config is used."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "retry_wait": 1.5})
        assert batch.retry_wait == 1.5


class TestConfigTypeCoercion:
    """Tests for type coercion of batch config values.

    Defense-in-depth: if invalid types bypass schema validation,
    batch config should still work with sensible coercion and warnings.
    """

    def test_parallel_string_true_coerced(self):
        """String 'true' is coerced to boolean True."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "parallel": "true"})
        assert batch.parallel is True

    def test_parallel_string_false_coerced(self):
        """String 'false' is coerced to boolean False."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "parallel": "false"})
        assert batch.parallel is False

    def test_parallel_string_yes_coerced(self):
        """String 'yes' is coerced to boolean True."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "parallel": "YES"})
        assert batch.parallel is True

    def test_parallel_string_invalid_uses_default(self):
        """Invalid string for parallel uses default (False)."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "parallel": "invalid"})
        assert batch.parallel is False

    def test_parallel_int_1_coerced_to_true(self):
        """Integer 1 is coerced to boolean True."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "parallel": 1})
        assert batch.parallel is True

    def test_parallel_int_0_coerced_to_false(self):
        """Integer 0 is coerced to boolean False."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "parallel": 0})
        assert batch.parallel is False

    def test_max_concurrent_string_coerced(self):
        """String '5' is coerced to integer 5."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "max_concurrent": "5"})
        assert batch.max_concurrent == 5

    def test_max_concurrent_float_coerced(self):
        """Float 5.9 is coerced to integer 5."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "max_concurrent": 5.9})
        assert batch.max_concurrent == 5

    def test_max_concurrent_invalid_uses_default(self):
        """Invalid string for max_concurrent uses default (10)."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "max_concurrent": "invalid"})
        assert batch.max_concurrent == 10

    def test_max_retries_string_coerced(self):
        """String '3' is coerced to integer 3."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "max_retries": "3"})
        assert batch.max_retries == 3

    def test_max_retries_invalid_uses_default(self):
        """Invalid string for max_retries uses default (1)."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "max_retries": "invalid"})
        assert batch.max_retries == 1

    def test_retry_wait_string_coerced(self):
        """String '1.5' is coerced to float 1.5."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "retry_wait": "1.5"})
        assert batch.retry_wait == 1.5

    def test_retry_wait_int_coerced(self):
        """Integer 2 is coerced to float 2.0."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "retry_wait": 2})
        assert batch.retry_wait == 2.0

    def test_retry_wait_invalid_uses_default(self):
        """Invalid string for retry_wait uses default (0.0)."""
        batch = PflowBatchNode(MockInnerNode("n"), "n", {"items": "${x}", "retry_wait": "invalid"})
        assert batch.retry_wait == 0.0

    def test_native_types_not_warned(self, caplog):
        """Native types (bool, int, float) don't trigger warnings."""
        import logging

        with caplog.at_level(logging.WARNING):
            batch = PflowBatchNode(
                MockInnerNode("n"),
                "n",
                {"items": "${x}", "parallel": True, "max_concurrent": 5, "max_retries": 3, "retry_wait": 1.5},
            )

        # No warnings should be logged for correct types
        assert batch.parallel is True
        assert batch.max_concurrent == 5
        assert batch.max_retries == 3
        assert batch.retry_wait == 1.5
        assert len([r for r in caplog.records if "coercing" in r.message.lower()]) == 0


class TestParallelExecution:
    """Tests for parallel batch execution."""

    def test_parallel_execution_basic(self):
        """Items execute in parallel and all results collected."""
        inner = ParallelMockInnerNode("test_node", delay=0.01)
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True, "max_concurrent": 10})

        shared = {"data": ["a", "b", "c", "d", "e"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        assert len(results) == 5
        assert shared["test_node"]["count"] == 5
        assert shared["test_node"]["success_count"] == 5
        # Note: can't check inner.call_count because each thread gets a copy

    def test_parallel_faster_than_sequential(self):
        """Parallel execution should be significantly faster than sequential."""
        delay_per_item = 0.05  # 50ms each
        items_data = ["a", "b", "c", "d", "e"]  # 5 items

        # Sequential would be: 5 * 50ms = 250ms minimum
        # Parallel (5 concurrent): ~50ms minimum

        inner = ParallelMockInnerNode("test_node", delay=delay_per_item)
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True, "max_concurrent": 10})

        shared = {"data": items_data}
        items = batch.prep(shared)

        start = time.time()
        batch._exec(items)
        elapsed = time.time() - start

        # Parallel should be well under sequential time (250ms)
        # Using 150ms as threshold (generous margin for OS scheduling)
        assert elapsed < 0.15, f"Parallel took {elapsed:.3f}s, expected < 0.15s"

    def test_parallel_uses_multiple_threads(self):
        """Parallel execution uses multiple threads."""
        # Track thread IDs in shared store (which is shallow-copied)
        inner = ParallelMockInnerNode("test_node", delay=0.02)
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True, "max_concurrent": 10})

        # Use shared store to track thread IDs (shallow copy preserves list reference)
        shared = {"data": ["a", "b", "c", "d", "e"], "_thread_ids": []}

        # Modify the inner node to track via shared store
        original_run = inner._run

        def tracking_run(s):
            s["_thread_ids"].append(threading.current_thread().ident)
            return original_run(s)

        inner._run = tracking_run

        items = batch.prep(shared)
        batch._exec(items)

        # Should have used multiple threads (not all same thread ID)
        unique_threads = set(shared["_thread_ids"])
        assert len(unique_threads) > 1, f"Expected multiple threads, got {unique_threads}"

    def test_max_concurrent_limits_workers(self):
        """max_concurrent limits the number of parallel workers."""
        delay_per_item = 0.05  # 50ms each
        items_data = ["a", "b", "c", "d"]  # 4 items

        # With max_concurrent=2:
        #   Batch 1 (a,b): 50ms
        #   Batch 2 (c,d): 50ms
        #   Total: ~100ms
        # With max_concurrent=4:
        #   All at once: ~50ms

        inner = ParallelMockInnerNode("test_node", delay=delay_per_item)
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True, "max_concurrent": 2})

        shared = {"data": items_data}
        items = batch.prep(shared)

        start = time.time()
        batch._exec(items)
        elapsed = time.time() - start

        # With max_concurrent=2, should take closer to 100ms than 50ms
        # Using 80ms as lower threshold
        assert elapsed >= 0.08, f"Expected batched execution (>80ms), got {elapsed:.3f}s"


class TestParallelResultOrdering:
    """Tests for result ordering in parallel execution."""

    def test_result_order_preserved(self):
        """Results are in input order regardless of completion order."""
        # Create items where later items complete first
        # Item 0: slow (60ms), Item 1: medium (40ms), Item 2: fast (20ms)
        items_data = [
            {"id": 0, "delay": 0.06},
            {"id": 1, "delay": 0.04},
            {"id": 2, "delay": 0.02},
        ]

        inner = ParallelMockInnerNode("test_node", behavior="variable_delay")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True, "max_concurrent": 10})

        shared = {"data": items_data}
        items = batch.prep(shared)
        results = batch._exec(items)

        # Results should be in INPUT order, not completion order
        assert results[0]["response"] == 0  # Slowest, but first in results
        assert results[1]["response"] == 1
        assert results[2]["response"] == 2  # Fastest, but last in results

    def test_result_order_with_many_items(self):
        """Result ordering works with more items."""
        items_data = [{"id": i, "delay": 0.01 * (5 - i)} for i in range(5)]
        # Items: id=0 slow, id=4 fast

        inner = ParallelMockInnerNode("test_node", behavior="variable_delay")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True, "max_concurrent": 10})

        shared = {"data": items_data}
        items = batch.prep(shared)
        results = batch._exec(items)

        # Verify all results in correct order
        for i in range(5):
            assert results[i]["response"] == i, f"Result {i} has wrong id"


class TestParallelTemplateIsolation:
    """Tests for template isolation in parallel execution."""

    def test_each_thread_gets_own_item(self):
        """Each thread should see its own item, not another thread's."""
        items_data = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]

        inner = ParallelMockInnerNode("test_node", delay=0.02)
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True, "max_concurrent": 10})

        shared = {"data": items_data}
        items = batch.prep(shared)
        results = batch._exec(items)

        # Each result should have its OWN item's id
        for i, result in enumerate(results):
            expected_id = i + 1
            actual_item = result["response"]
            assert actual_item["id"] == expected_id, (
                f"Result {i} has wrong item: expected id={expected_id}, got {actual_item}"
            )

    def test_custom_alias_isolated(self):
        """Custom item alias is isolated per thread."""
        # Track seen values in shared store (shallow copy shares list)
        inner = ParallelMockInnerNode("test_node", delay=0.02)
        batch = PflowBatchNode(
            inner,
            "test_node",
            {"items": "${data}", "as": "record", "parallel": True, "max_concurrent": 10},
        )

        # Use shared store to track values (shallow copy preserves list reference)
        shared = {"data": ["alpha", "beta", "gamma"], "_seen_values": []}

        # Modify the inner node to track via shared store
        original_run = inner._run

        def tracking_run(s):
            record = s.get("record")
            s["_seen_values"].append(record)
            # Temporarily set item from record for the original run
            s["item"] = record
            return original_run(s)

        inner._run = tracking_run

        items = batch.prep(shared)
        results = batch._exec(items)

        # All three values should have been seen (order may vary due to threading)
        assert set(shared["_seen_values"]) == {"alpha", "beta", "gamma"}
        # Results should be in order
        assert results[0]["response"] == "alpha"
        assert results[1]["response"] == "beta"
        assert results[2]["response"] == "gamma"


class TestParallelErrorHandling:
    """Tests for error handling in parallel execution."""

    def test_parallel_fail_fast_raises(self):
        """fail_fast mode raises on first error in parallel."""

        # Use a simple node that fails on a specific item value
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
        batch = PflowBatchNode(
            inner,
            "test_node",
            {"items": "${data}", "parallel": True, "error_handling": "fail_fast"},
        )

        shared = {"data": ["a", "b", "c", "d", "e"]}
        items = batch.prep(shared)

        with pytest.raises(ValueError, match="Intentional error"):
            batch._exec(items)

    def test_parallel_continue_collects_all_errors(self):
        """continue mode processes all items and collects errors."""

        # Node that fails on specific item values
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
        batch = PflowBatchNode(
            inner,
            "test_node",
            {"items": "${data}", "parallel": True, "error_handling": "continue"},
        )

        shared = {"data": ["a", "b", "c", "d", "e"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # All 5 items attempted
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
        batch = PflowBatchNode(
            inner,
            "test_node",
            {"items": "${data}", "parallel": True, "error_handling": "continue"},
        )

        shared = {"data": ["a", "b", "c"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # First and third items succeeded
        assert results[0] == {"response": "a"}
        assert results[1] is None  # Failed
        assert results[2] == {"response": "c"}


class TestParallelRetry:
    """Tests for retry logic in parallel execution."""

    def test_parallel_retry_succeeds_after_failure(self):
        """Item succeeds on retry in parallel mode."""

        # Track attempts in shared store (shallow copy shares dict)
        class RetryNode:
            """Node that fails first N times then succeeds."""

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

                # Track attempts in shared store (survives across retries within same thread)
                attempts = shared.get("_attempts", {})
                attempts[item_key] = attempts.get(item_key, 0) + 1
                shared["_attempts"] = attempts
                attempt = attempts[item_key]

                if attempt <= self.fail_times:
                    raise ValueError(f"Temporary failure for {item}")

                shared[self.node_id] = {"response": item, "attempts": attempt}
                return "default"

        inner = RetryNode("test_node", fail_times=2)
        batch = PflowBatchNode(
            inner,
            "test_node",
            {
                "items": "${data}",
                "parallel": True,
                "max_retries": 3,
                "retry_wait": 0,  # No wait for faster tests
            },
        )

        shared = {"data": ["x"], "_attempts": {}}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # Should succeed on 3rd attempt
        assert results[0]["response"] == "x"
        assert results[0]["attempts"] == 3
        assert shared["test_node"]["success_count"] == 1

    def test_parallel_retry_exhausted(self):
        """Error returned when all retries exhausted in parallel."""

        class AlwaysFailNode:
            """Node that always fails."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def __getstate__(self):
                return self.__dict__.copy()

            def __setstate__(self, state):
                self.__dict__.update(state)

            def _run(self, shared: dict) -> str:
                # Track attempts using a list (mutable, works with shallow copy)
                shared["_attempts"].append(1)
                raise ValueError("Permanent failure")

        inner = AlwaysFailNode("test_node")
        batch = PflowBatchNode(
            inner,
            "test_node",
            {
                "items": "${data}",
                "parallel": True,
                "max_retries": 3,
                "retry_wait": 0,
                "error_handling": "continue",
            },
        )

        shared = {"data": ["x"], "_attempts": []}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # Should have tried 3 times (tracked in shared list)
        assert len(shared["_attempts"]) == 3
        assert results[0] is None
        assert shared["test_node"]["error_count"] == 1

    def test_parallel_retry_resets_namespace(self):
        """Namespace is reset between retries in parallel mode (matches sequential behavior).

        This prevents partial writes from failed attempts polluting retry attempts.
        Regression test for bug where parallel mode didn't reset namespace on retry.
        """

        class WriteBeforeFailNode:
            """Node that writes to namespace before potentially failing."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def __deepcopy__(self, memo):
                return WriteBeforeFailNode(self.node_id)

            def _run(self, shared: dict) -> str:
                # Track retries via mutable list (shallow copy shares it)
                shared["_retries"].append(1)
                retry_num = len(shared["_retries"])

                # Check if namespace has data from previous attempt
                namespace = shared.get(self.node_id, {})
                had_previous_marker = "marker" in namespace

                # Record observation
                shared["_observations"].append({"retry": retry_num, "had_previous_marker": had_previous_marker})

                # Write marker BEFORE potentially failing
                if self.node_id not in shared:
                    shared[self.node_id] = {}
                shared[self.node_id]["marker"] = f"written_on_retry_{retry_num}"

                # Fail on first attempt
                if retry_num == 1:
                    raise ValueError("Intentional failure on first attempt")

                # Succeed on second attempt
                shared[self.node_id]["result"] = "success"
                return "default"

        inner = WriteBeforeFailNode("test_node")
        batch = PflowBatchNode(
            inner,
            "test_node",
            {
                "items": "${data}",
                "parallel": True,
                "max_retries": 2,
                "error_handling": "continue",
            },
        )

        # Pre-initialize mutable containers so shallow copy shares them
        shared = {"data": ["item_a"], "_retries": [], "_observations": []}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # Verify retry happened
        assert len(shared["_observations"]) == 2

        # On retry 2, namespace should NOT have marker from retry 1
        # (namespace should be reset between retries)
        retry1_obs = shared["_observations"][0]
        retry2_obs = shared["_observations"][1]

        assert retry1_obs["had_previous_marker"] is False, "Retry 1 should start clean"
        assert retry2_obs["had_previous_marker"] is False, (
            "Retry 2 should NOT see marker from retry 1 - namespace should be reset"
        )

        # Verify success
        assert results[0]["result"] == "success"


class TestParallelThreadSafety:
    """Tests for thread safety in parallel execution."""

    def test_llm_calls_accumulated(self):
        """__llm_calls__ list accumulates from all parallel items."""

        class LLMTrackingNode:
            """Node that appends to __llm_calls__."""

            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                # Simulate LLM call tracking
                if "__llm_calls__" in shared:
                    shared["__llm_calls__"].append({"model": "test", "item": item})
                time.sleep(0.01)  # Ensure overlap
                shared[self.node_id] = {"response": item}
                return "default"

        inner = LLMTrackingNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True, "max_concurrent": 10})

        shared = {"data": ["a", "b", "c", "d", "e"], "__llm_calls__": []}
        items = batch.prep(shared)
        batch._exec(items)

        # All 5 items should have tracked their LLM calls
        assert len(shared["__llm_calls__"]) == 5
        tracked_items = {call["item"] for call in shared["__llm_calls__"]}
        assert tracked_items == {"a", "b", "c", "d", "e"}

    def test_batch_captures_inner_node_llm_usage_sequential(self):
        """LLM usage from inner nodes is captured in sequential mode.

        This tests the fix for the bug where llm_usage written by inner LLM nodes
        to item_shared was lost when the context was discarded. The batch node
        should capture this data and append it to __llm_calls__.
        """

        class MockLLMNode:
            """Mock node that simulates real LLM node behavior.

            Real LLM nodes write llm_usage to shared store, expecting
            InstrumentedNodeWrapper to capture it. In batch mode, this data
            was previously lost because the isolated item_shared context
            was discarded after execution.
            """

            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                # Simulates what real LLM node does - writes llm_usage
                shared["llm_usage"] = {
                    "model": "test-model",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                }
                shared[self.node_id] = {"response": f"processed: {item}"}
                return "default"

        inner = MockLLMNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": False})

        shared = {"data": ["a", "b", "c"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # Should have captured 3 LLM calls
        assert "__llm_calls__" in shared
        assert len(shared["__llm_calls__"]) == 3

        # Verify each call has correct data
        for i, call in enumerate(shared["__llm_calls__"]):
            assert call["model"] == "test-model"
            assert call["input_tokens"] == 100
            assert call["output_tokens"] == 50
            assert call["node_id"] == "test_node"
            assert call["batch_item_index"] == i

    def test_batch_captures_inner_node_llm_usage_parallel(self):
        """LLM usage from inner nodes is captured in parallel mode.

        Same as sequential test but verifies thread-safe capture in parallel mode.
        """

        class MockLLMNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                time.sleep(0.01)  # Ensure some overlap
                shared["llm_usage"] = {
                    "model": "parallel-model",
                    "input_tokens": 200,
                    "output_tokens": 100,
                }
                shared[self.node_id] = {"response": f"processed: {item}"}
                return "default"

        inner = MockLLMNode("test_node")
        batch = PflowBatchNode(
            inner,
            "test_node",
            {"items": "${data}", "parallel": True, "max_concurrent": 5},
        )

        shared = {"data": ["x", "y", "z", "w", "v"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # Should have captured 5 LLM calls
        assert "__llm_calls__" in shared
        assert len(shared["__llm_calls__"]) == 5

        # All calls should have correct model
        assert all(call["model"] == "parallel-model" for call in shared["__llm_calls__"])
        assert all(call["node_id"] == "test_node" for call in shared["__llm_calls__"])

        # Verify all indices are captured (order may vary in parallel)
        indices = {call["batch_item_index"] for call in shared["__llm_calls__"]}
        assert indices == {0, 1, 2, 3, 4}

    def test_batch_captures_namespaced_llm_usage(self):
        """LLM usage is captured from namespaced location.

        When inner node uses namespacing, llm_usage is written to
        shared[node_id]["llm_usage"]. The batch node should capture this too.
        """

        class NamespacedMockLLMNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                # Write to namespaced location (simulates NamespacedNodeWrapper)
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
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": False})

        shared = {"data": [1, 2]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # Should have captured 2 LLM calls from namespaced location
        assert len(shared["__llm_calls__"]) == 2
        assert all(call["model"] == "namespaced-model" for call in shared["__llm_calls__"])

    def test_batch_initializes_llm_calls_list(self):
        """Batch node initializes __llm_calls__ if not present.

        Critical for the fix: if __llm_calls__ doesn't exist before batch starts,
        the shallow copy won't share the list reference. The batch node must
        initialize it in prep() to ensure captures work correctly.
        """

        class MockLLMNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                shared["llm_usage"] = {"model": "test", "input_tokens": 10, "output_tokens": 5}
                shared[self.node_id] = {"response": "ok"}
                return "default"

        inner = MockLLMNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": False})

        # Start WITHOUT __llm_calls__ - batch should initialize it
        shared = {"data": ["a", "b"]}
        assert "__llm_calls__" not in shared

        items = batch.prep(shared)
        # After prep, __llm_calls__ should exist
        assert "__llm_calls__" in shared
        assert isinstance(shared["__llm_calls__"], list)

        results = batch._exec(items)
        batch.post(shared, items, results)

        # And captures should have worked
        assert len(shared["__llm_calls__"]) == 2

    def test_batch_no_llm_usage_no_crash(self):
        """Batch node handles inner nodes that don't write llm_usage.

        Non-LLM nodes don't write llm_usage. The capture logic should
        gracefully handle this case without errors.
        """

        class NonLLMNode:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                shared[self.node_id] = {"response": item}
                return "default"

        inner = NonLLMNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": False})

        shared = {"data": ["a", "b", "c"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # __llm_calls__ should exist but be empty
        assert "__llm_calls__" in shared
        assert len(shared["__llm_calls__"]) == 0

        # Results should still work
        assert len(shared["test_node"]["results"]) == 3

    def test_llm_calls_contain_all_required_fields_for_metrics(self):
        """LLM call records contain all fields needed for cost calculation.

        The MetricsCollector and trace system expect specific fields
        to calculate costs and display usage. Verify all are present.
        """

        class MockLLMNodeWithFullUsage:
            def __init__(self, node_id: str):
                self.node_id = node_id

            def _run(self, shared: dict) -> str:
                item = shared.get("item")
                # Simulates full LLM usage data as written by real LLM node
                shared["llm_usage"] = {
                    "model": "anthropic/claude-sonnet-4-0",
                    "input_tokens": 500,
                    "output_tokens": 150,
                    "total_tokens": 650,
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 50,
                    "total_cost_usd": 0.0123,
                }
                shared[self.node_id] = {"response": f"processed: {item}"}
                return "default"

        inner = MockLLMNodeWithFullUsage("summarize")
        batch = PflowBatchNode(inner, "summarize", {"items": "${items}", "parallel": False})

        shared = {"items": ["doc1", "doc2", "doc3"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # Verify all 3 calls captured
        assert len(shared["__llm_calls__"]) == 3

        # Verify each call has all required fields
        for i, call in enumerate(shared["__llm_calls__"]):
            # Original LLM usage fields (for MetricsCollector)
            assert call["model"] == "anthropic/claude-sonnet-4-0"
            assert call["input_tokens"] == 500
            assert call["output_tokens"] == 150
            assert call["total_tokens"] == 650
            assert call["cache_creation_input_tokens"] == 100
            assert call["cache_read_input_tokens"] == 50
            assert call["total_cost_usd"] == 0.0123

            # Batch context fields (added by _capture_item_llm_usage)
            assert call["node_id"] == "summarize"
            assert call["batch_item_index"] == i

        # Verify total cost would be correctly calculated
        total_cost = sum(call["total_cost_usd"] for call in shared["__llm_calls__"])
        assert total_cost == 0.0123 * 3  # 0.0369

        total_tokens = sum(call["total_tokens"] for call in shared["__llm_calls__"])
        assert total_tokens == 650 * 3  # 1950

    def test_no_race_on_results_array(self):
        """Results array is not corrupted by parallel writes."""
        inner = ParallelMockInnerNode("test_node", delay=0.01)
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True, "max_concurrent": 10})

        # Run many items to increase chance of race condition
        items_data = list(range(20))
        shared = {"data": items_data}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # All results should be present and in order
        assert len(results) == 20
        for i, result in enumerate(results):
            assert result is not None, f"Result {i} is None"
            assert result["response"] == i, f"Result {i} has wrong value"


class TestParallelEdgeCases:
    """Edge case tests for parallel execution."""

    def test_parallel_empty_list(self):
        """Empty input returns empty results in parallel mode."""
        inner = ParallelMockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True})

        shared = {"data": []}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        assert results == []
        assert shared["test_node"]["count"] == 0

    def test_parallel_single_item(self):
        """Single item works in parallel mode."""
        inner = ParallelMockInnerNode("test_node", delay=0.01)
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True})

        shared = {"data": ["only_one"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        assert len(results) == 1
        assert results[0] == {"response": "only_one"}
        assert shared["test_node"]["success_count"] == 1

    def test_parallel_vs_sequential_same_results(self):
        """Parallel and sequential produce identical results."""
        items_data = ["a", "b", "c", "d", "e"]

        # Sequential execution
        inner_seq = ParallelMockInnerNode("test_node")
        batch_seq = PflowBatchNode(inner_seq, "test_node", {"items": "${data}", "parallel": False})
        shared_seq = {"data": items_data.copy()}
        items_seq = batch_seq.prep(shared_seq)
        results_seq = batch_seq._exec(items_seq)
        batch_seq.post(shared_seq, items_seq, results_seq)

        # Parallel execution
        inner_par = ParallelMockInnerNode("test_node")
        batch_par = PflowBatchNode(inner_par, "test_node", {"items": "${data}", "parallel": True, "max_concurrent": 10})
        shared_par = {"data": items_data.copy()}
        items_par = batch_par.prep(shared_par)
        results_par = batch_par._exec(items_par)
        batch_par.post(shared_par, items_par, results_par)

        # Results should be identical
        assert results_seq == results_par
        assert shared_seq["test_node"]["count"] == shared_par["test_node"]["count"]
        assert shared_seq["test_node"]["success_count"] == shared_par["test_node"]["success_count"]


class TestBatchMetadata:
    """Tests for batch_metadata in output (tracing enhancement)."""

    def test_batch_metadata_present_in_output(self):
        """batch_metadata field is present in output."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["a", "b", "c"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        assert "batch_metadata" in shared["test_node"]

    def test_batch_metadata_sequential_mode(self):
        """batch_metadata shows sequential execution details."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(
            inner,
            "test_node",
            {"items": "${data}", "parallel": False, "max_retries": 2, "retry_wait": 0.5},
        )

        shared = {"data": ["a", "b"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        metadata = shared["test_node"]["batch_metadata"]
        assert metadata["parallel"] is False
        assert metadata["execution_mode"] == "sequential"
        assert metadata["max_concurrent"] is None  # Not applicable for sequential
        assert metadata["max_retries"] == 2
        assert metadata["retry_wait"] == 0.5

    def test_batch_metadata_parallel_mode(self):
        """batch_metadata shows parallel execution details."""
        inner = ParallelMockInnerNode("test_node")
        batch = PflowBatchNode(
            inner,
            "test_node",
            {"items": "${data}", "parallel": True, "max_concurrent": 5, "max_retries": 3},
        )

        shared = {"data": ["a", "b", "c"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        metadata = shared["test_node"]["batch_metadata"]
        assert metadata["parallel"] is True
        assert metadata["execution_mode"] == "parallel"
        assert metadata["max_concurrent"] == 5
        assert metadata["max_retries"] == 3

    def test_batch_metadata_timing_stats(self):
        """batch_metadata includes timing statistics."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["a", "b", "c"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        timing = shared["test_node"]["batch_metadata"]["timing"]
        assert timing is not None
        assert "total_items_ms" in timing
        assert "avg_item_ms" in timing
        assert "min_item_ms" in timing
        assert "max_item_ms" in timing

        # Timing values should be non-negative
        assert timing["total_items_ms"] >= 0
        assert timing["avg_item_ms"] >= 0
        assert timing["min_item_ms"] >= 0
        assert timing["max_item_ms"] >= 0

        # min <= avg <= max
        assert timing["min_item_ms"] <= timing["avg_item_ms"]
        assert timing["avg_item_ms"] <= timing["max_item_ms"]

    def test_batch_metadata_timing_stats_parallel(self):
        """batch_metadata timing works in parallel mode."""
        inner = ParallelMockInnerNode("test_node", delay=0.01)
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True, "max_concurrent": 3})

        shared = {"data": ["a", "b", "c", "d", "e"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        timing = shared["test_node"]["batch_metadata"]["timing"]
        assert timing is not None
        assert timing["total_items_ms"] > 0  # Should have measurable time
        assert len(results) == 5

    def test_batch_metadata_empty_list(self):
        """batch_metadata timing is None for empty list."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": []}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        timing = shared["test_node"]["batch_metadata"]["timing"]
        assert timing is None  # No items processed

    def test_batch_metadata_retry_wait_omitted_when_zero(self):
        """retry_wait is None when set to 0 (default)."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "retry_wait": 0})

        shared = {"data": ["a"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        metadata = shared["test_node"]["batch_metadata"]
        assert metadata["retry_wait"] is None

    def test_batch_metadata_retry_wait_present_when_nonzero(self):
        """retry_wait is present when > 0."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "retry_wait": 1.5})

        shared = {"data": ["a"]}
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        metadata = shared["test_node"]["batch_metadata"]
        assert metadata["retry_wait"] == 1.5

    def test_batch_metadata_captured_in_trace(self):
        """batch_metadata is captured in workflow traces via shared_after.

        This simulates what InstrumentedNodeWrapper does: it captures dict(shared)
        after node execution and passes it to WorkflowTraceCollector.record_node_execution().
        The batch_metadata should appear in the trace's shared_after field.
        """
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        inner = ParallelMockInnerNode("batch_node")
        batch = PflowBatchNode(
            inner,
            "batch_node",
            {"items": "${data}", "parallel": True, "max_concurrent": 3},
        )

        # Simulate workflow execution with trace collector
        collector = WorkflowTraceCollector(workflow_name="test-batch")
        shared = {"data": ["a", "b", "c"]}

        # Capture shared_before (like InstrumentedNodeWrapper does)
        shared_before = dict(shared)

        # Execute batch node
        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # Capture shared_after (like InstrumentedNodeWrapper does)
        shared_after = dict(shared)

        # Record trace event (simulating InstrumentedNodeWrapper._record_trace)
        collector.record_node_execution(
            node_id="batch_node",
            node_type="ShellNode",  # Inner node type, not PflowBatchNode
            duration_ms=100.0,
            shared_before=shared_before,
            shared_after=shared_after,
            success=True,
        )

        # Verify batch_metadata appears in trace
        assert len(collector.events) == 1
        event = collector.events[0]

        # The batch_metadata should be in shared_after under the node's namespace
        assert "batch_node" in event["shared_after"]
        assert "batch_metadata" in event["shared_after"]["batch_node"]

        metadata = event["shared_after"]["batch_node"]["batch_metadata"]
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
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {
            "data": ["a", "b", "c"],
            "__progress_callback__": track_callback,
        }

        items = batch.prep(shared)
        batch._exec(items)

        # Verify progress events
        progress_events = [e for e in events if e["event"] == "batch_progress"]
        assert len(progress_events) == 3

        # Check first item
        assert progress_events[0]["batch_current"] == 1
        assert progress_events[0]["batch_total"] == 3
        assert progress_events[0]["batch_success"] is True
        assert progress_events[0]["node_id"] == "test_node"

        # Check last item
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
        inner.error_index = 1  # Second item will have error in result
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "error_handling": "continue"})

        shared = {
            "data": ["a", "b", "c"],
            "__progress_callback__": track_callback,
        }

        items = batch.prep(shared)
        batch._exec(items)

        # Verify failure is reported
        assert len(events) == 3
        assert events[0]["batch_success"] is True  # Item 0 succeeded
        assert events[1]["batch_success"] is False  # Item 1 failed (error in result)
        assert events[2]["batch_success"] is True  # Item 2 succeeded

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
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}", "parallel": True, "max_concurrent": 3})

        shared = {
            "data": ["a", "b", "c", "d", "e"],
            "__progress_callback__": track_callback,
        }

        items = batch.prep(shared)
        batch._exec(items)

        # All items should be reported
        assert len(events) == 5

        # batch_current should be incremented (1, 2, 3, 4, 5 - order may vary)
        currents = sorted([e["batch_current"] for e in events])
        assert currents == [1, 2, 3, 4, 5]

        # All should have same total
        assert all(e["batch_total"] == 5 for e in events)

        # All should succeed
        assert all(e["batch_success"] is True for e in events)

    def test_callback_exception_ignored(self):
        """Exceptions in progress callback don't break batch execution."""
        call_count = 0

        def broken_callback(node_id, event, duration_ms=None, depth=0, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Callback error")

        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {
            "data": ["a", "b", "c"],
            "__progress_callback__": broken_callback,
        }

        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # Callback was called despite raising exceptions
        assert call_count == 3

        # Batch completed successfully
        assert shared["test_node"]["success_count"] == 3

    def test_no_callback_when_not_provided(self):
        """Batch works correctly when no callback is provided."""
        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {"data": ["a", "b", "c"]}  # No __progress_callback__

        items = batch.prep(shared)
        results = batch._exec(items)
        batch.post(shared, items, results)

        # Should complete without errors
        assert shared["test_node"]["success_count"] == 3

    def test_callback_receives_depth(self):
        """Progress callback receives correct depth from shared store."""
        events: list[dict] = []

        def track_callback(node_id, event, duration_ms=None, depth=0, **kwargs):
            if event == "batch_progress":
                events.append({"depth": depth})

        inner = MockInnerNode("test_node")
        batch = PflowBatchNode(inner, "test_node", {"items": "${data}"})

        shared = {
            "data": ["a", "b"],
            "__progress_callback__": track_callback,
            "_pflow_depth": 2,  # Simulate nested workflow
        }

        items = batch.prep(shared)
        batch._exec(items)

        # All events should have depth=2
        assert len(events) == 2
        assert all(e["depth"] == 2 for e in events)
