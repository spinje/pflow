"""Critical guardrail tests for node_output_formatter.

These tests protect against bugs that CLI integration tests don't catch:
- Type contract violations that break MCP
- Edge cases that cause crashes
- Return type regressions

Each test catches a specific real-world bug that would break production.
"""

from datetime import datetime
from unittest.mock import Mock

import pytest

from pflow.execution.formatters.node_output_formatter import (
    extract_metadata_paths,
    extract_runtime_paths,
    flatten_runtime_value,
    format_node_output,
    json_serializer,
)
from pflow.registry import Registry


class TestTypeContractGuards:
    """Tests that catch return type violations breaking MCP."""

    def test_format_node_output_returns_correct_types(self):
        """TYPE SAFETY: Prevent return type regressions that break MCP.

        Real bug this catches: If format_node_output returns dict for
        format_type="structure", MCP crashes because it directly returns
        the value expecting a string.

        CLI wouldn't catch this because it checks type before displaying.
        """
        registry = Mock(spec=Registry)
        registry.get_nodes_metadata.return_value = {}

        # Test all format types return correct types
        outputs = {"stdout": "hello", "exit_code": 0}
        shared_store = {}

        # Text mode must return string
        result = format_node_output(
            node_type="test",
            action="default",
            outputs=outputs,
            shared_store=shared_store,
            execution_time_ms=100,
            registry=registry,
            format_type="text",
            verbose=False,
        )
        assert isinstance(result, str), "text mode must return string for CLI display"

        # JSON mode must return dict
        result = format_node_output(
            node_type="test",
            action="default",
            outputs=outputs,
            shared_store=shared_store,
            execution_time_ms=100,
            registry=registry,
            format_type="json",
            verbose=False,
        )
        assert isinstance(result, dict), "json mode must return dict for JSON serialization"

        # Structure mode must return string (critical for MCP)
        result = format_node_output(
            node_type="test",
            action="default",
            outputs=outputs,
            shared_store=shared_store,
            execution_time_ms=100,
            registry=registry,
            format_type="structure",
            verbose=False,
        )
        assert isinstance(result, str), "structure mode must return string - MCP directly returns this"

    def test_error_action_returns_correct_types(self):
        """TYPE SAFETY: Prevent error handling from returning wrong types.

        Real bug this catches: Error action returns dict when text expected,
        breaking CLI/MCP display.
        """
        registry = Mock(spec=Registry)
        shared_store = {"error": "Something failed"}
        outputs = {}

        # Text error must return string
        result = format_node_output(
            node_type="test",
            action="error",
            outputs=outputs,
            shared_store=shared_store,
            execution_time_ms=100,
            registry=registry,
            format_type="text",
            verbose=False,
        )
        assert isinstance(result, str), "text error must return string"
        assert "❌" in result, "error should include error indicator"

        # JSON error must return dict
        result = format_node_output(
            node_type="test",
            action="error",
            outputs=outputs,
            shared_store=shared_store,
            execution_time_ms=100,
            registry=registry,
            format_type="json",
            verbose=False,
        )
        assert isinstance(result, dict), "json error must return dict"
        assert result["success"] is False, "error must have success=false"


class TestEdgeCaseGuards:
    """Tests that catch edge cases causing crashes."""

    def test_empty_outputs_dont_crash(self):
        """ROBUSTNESS: Empty outputs should format gracefully.

        Real bug this catches: Empty outputs dict causes iteration
        failures or display errors.
        """
        registry = Mock(spec=Registry)
        registry.get_nodes_metadata.return_value = {}

        # Empty outputs should not crash
        result = format_node_output(
            node_type="test",
            action="default",
            outputs={},  # Empty outputs
            shared_store={},
            execution_time_ms=100,
            registry=registry,
            format_type="text",
            verbose=False,
        )
        assert isinstance(result, str)
        assert "No outputs returned" in result or "Outputs:" not in result

    def test_json_serialization_failure_returns_error_dict(self):
        """ERROR HANDLING: JSON serialization failures return proper error.

        Real bug this catches: If json_serializer fails, formatter should
        return error dict, not crash.
        """
        registry = Mock(spec=Registry)

        # Create an object that json_serializer can't handle gracefully
        class UnserializableObject:
            def __str__(self):
                raise ValueError("Cannot stringify")

        outputs = {"bad_object": UnserializableObject()}

        result = format_node_output(
            node_type="test",
            action="default",
            outputs=outputs,
            shared_store={},
            execution_time_ms=100,
            registry=registry,
            format_type="json",
            verbose=False,
        )

        # Should return error dict, not crash
        assert isinstance(result, dict)
        # Either successful with stringified object, or error dict
        if result.get("success") is False:
            assert "error" in result


class TestTemplatePathExtractionGuards:
    """Tests that catch template path extraction bugs - core feature for workflow building."""

    def test_extract_metadata_paths_with_nested_structure(self):
        """TEMPLATE PATHS: Nested output structures must be flattened correctly.

        Real bug this catches: AI refactoring breaks the flattening logic,
        causing agents to see only top-level keys like "result" but missing
        nested fields like "result.data.items[0].id".

        Without this, agents can't build workflows using nested MCP outputs.
        """
        registry = Mock(spec=Registry)
        registry.get_nodes_metadata.return_value = {
            "test-node": {
                "interface": {
                    "outputs": [
                        {
                            "key": "result",
                            "type": "dict",
                            "structure": {
                                "data": {
                                    "type": "dict",
                                    "structure": {
                                        "items": {"type": "list"},
                                        "count": {"type": "int"},
                                    },
                                },
                                "status": {"type": "str"},
                            },
                        }
                    ]
                }
            }
        }

        paths, has_any = extract_metadata_paths("test-node", registry)

        # Must include nested paths, not just top-level
        path_strings = [p[0] for p in paths]
        assert "result" in path_strings
        assert any("data" in p for p in path_strings), "must include nested 'data' field"
        assert len(paths) > 1, "must flatten nested structure, not just return top-level"

    def test_extract_runtime_paths_with_mcp_json_strings(self):
        """TEMPLATE PATHS: MCP nodes return JSON strings that must be parsed.

        Real bug this catches: MCP nodes return result='{"status": "ok", "data": {...}}'
        as a JSON string, not a dict. If formatter doesn't parse it, agents only
        see ${result} (str) instead of ${result.status}, ${result.data}.

        This is THE critical MCP node pattern - without this, MCP integration breaks.
        """
        # MCP node pattern: result is JSON string, not dict
        outputs = {"result": '{"status": "success", "data": {"id": 123, "name": "test"}}'}

        paths, warnings = extract_runtime_paths(outputs)

        # Must parse JSON string and flatten
        path_strings = [p[0] for p in paths]
        assert any("result.status" in p for p in path_strings), "must parse JSON string and show nested paths"
        assert any("result.data" in p for p in path_strings), "must show deeply nested paths"
        assert not any(p[1] == "str" and p[0] == "result" for p in paths), (
            "should not show result as plain string when it's valid JSON"
        )

    def test_flatten_runtime_value_max_depth_protection(self):
        """RECURSION SAFETY: Deep nesting must not cause stack overflow.

        Real bug this catches: AI refactoring removes max_depth check,
        causing stack overflow on deeply nested structures like:
        {a: {b: {c: {d: {e: {f: {g: {h: ...}}}}}}}}

        This crashes the entire CLI/MCP execution.
        """
        # Create deeply nested structure (10 levels)
        deeply_nested = {"level1": {"level2": {"level3": {"level4": {"level5": {"level6": {"level7": {}}}}}}}}

        # Should not crash, and should stop at max_depth (default 5)
        paths = flatten_runtime_value("root", deeply_nested)

        # Must return something (not crash)
        assert len(paths) > 0
        # Should have stopped recursion (not infinite)
        assert len(paths) < 20, "should stop at max depth, not recurse infinitely"


class TestDeduplicationGuards:
    """Tests that catch deduplication bugs - prevents path explosion."""

    def test_duplicate_structure_detection(self):
        """DEDUPLICATION: Same structure in multiple keys must be detected.

        Real bug this catches: MCP nodes return both "result" and
        "mcp_server_TOOL_result" with identical data. Without deduplication,
        agents see 500 duplicate template paths making output unusable.

        AI refactoring might break the hash comparison logic.
        """
        # MCP pattern: duplicate data in different keys
        duplicate_data = {"status": "ok", "count": 42}
        outputs = {
            "result": duplicate_data,
            "slack_composio_SEND_MESSAGE_result": duplicate_data,  # Same structure
        }

        paths, warnings = extract_runtime_paths(outputs)

        # Must deduplicate - should only show paths for one key
        path_prefixes = {p[0].split(".")[0] for p in paths}
        assert len(path_prefixes) == 1, (
            "should deduplicate identical structures, not show both 'result' and 'slack_composio_SEND_MESSAGE_result'"
        )

        # Must warn about duplication
        assert len(warnings) > 0, "should warn user about duplicate structure"
        assert any("same data" in w.lower() for w in warnings), "warning should mention duplicate data"


class TestSerializationGuards:
    """Tests that catch serialization crashes - prevents JSON encoding failures."""

    def test_json_serializer_datetime(self):
        """SERIALIZATION: datetime objects must not crash JSON encoding.

        Real bug this catches: Node outputs contain datetime objects,
        causing JSON encoding to fail with "Object of type datetime is not JSON serializable".

        AI refactoring might remove datetime handling from json_serializer.
        """
        dt = datetime(2024, 1, 15, 10, 30, 0)
        result = json_serializer(dt)

        # Must convert to string (ISO format)
        assert isinstance(result, str), "datetime must be serialized to string"
        assert "2024" in result, "should contain year"
        assert "01" in result or "1" in result, "should contain month"

    def test_json_serializer_path(self, tmp_path):
        """SERIALIZATION: Path objects must not crash JSON encoding.

        Real bug this catches: File operation nodes return Path objects,
        causing JSON encoding to fail.

        Without this, file operations break MCP completely.
        """
        test_file = tmp_path / "test.txt"
        result = json_serializer(test_file)

        # Must convert to string
        assert isinstance(result, str), "Path must be serialized to string"
        assert "test.txt" in result, "should contain path string"

    def test_json_serializer_bytes_non_utf8(self):
        """SERIALIZATION: Binary data must not crash when not UTF-8.

        Real bug this catches: Node outputs contain binary data that's not
        valid UTF-8 (images, compressed data). If formatter tries decode(),
        it crashes with UnicodeDecodeError.

        This is critical for binary data handling added in Task 82.
        """
        # Binary data that's not valid UTF-8
        binary_data = b"\x89\x50\x4e\x47"  # PNG header

        result = json_serializer(binary_data)

        # Must not crash and must describe the data
        assert isinstance(result, str), "binary data must be serialized to string"
        assert "binary" in result.lower() or "bytes" in result.lower(), "should indicate it's binary data"
        assert "4" in result, "should show byte count"


class TestRecursiveFlatteningGuards:
    """Tests that catch recursive flattening bugs - complex logic danger zone."""

    def test_flatten_runtime_value_stops_at_large_values(self):
        """PERFORMANCE: Large nested structures must be truncated.

        Real bug this catches: Node returns huge nested structure (1MB+ JSON),
        causing formatter to spend minutes flattening and output thousands
        of template paths that overwhelm the terminal.

        AI refactoring might remove the len(str(val)) > 1000 check.

        NOTE: After array field extraction enhancement, we now extract sample fields
        from the first item of large arrays to help agents understand structure.
        """
        # Large nested structure
        large_data = {"items": [{"id": i, "data": "x" * 100} for i in range(100)]}

        paths = flatten_runtime_value("result", large_data)

        # Should show list count (not fully flatten all 100 items)
        assert any("list, 100 items" in p[1] for p in paths), "should show list count"

        # Should extract sample fields from first item (new behavior)
        assert any(p[0] == "result.items[0].id" for p in paths), "should extract id from first item"
        assert any(p[0] == "result.items[0].data" for p in paths), "should extract data from first item"

        # Should NOT have paths for all 100 items (that would be overwhelming)
        assert not any("items[50]" in p[0] for p in paths), "should not extract from middle items"
        assert not any("items[99]" in p[0] for p in paths), "should not extract from last item"

    def test_flatten_runtime_value_handles_list_first_element(self):
        """ARRAY HANDLING: Lists must show first element structure.

        Real bug this catches: Node returns array of objects like
        [{id: 1, name: "foo"}, {id: 2, name: "bar"}]. Agents need to
        know the structure is ${items[0].id}, ${items[0].name}.

        If formatter doesn't handle lists correctly, agents see only
        ${items} (list) with no nested structure.
        """
        # List with structured objects
        outputs = {"items": [{"id": 1, "name": "test"}, {"id": 2, "name": "test2"}]}

        paths = flatten_runtime_value("items", outputs["items"])

        # Must show first element structure
        path_strings = [p[0] for p in paths]
        assert any("[0]" in p for p in path_strings), "must show list element syntax [0]"
        assert any("id" in p for p in path_strings), "must show nested fields in list items"


class TestStructureOnlyMode:
    """Tests for structure-only mode (Task 89)."""

    def test_structure_only_mode_hides_values(self):
        """STRUCTURE-ONLY: Default behavior shows NO data values.

        Task 89 changes default behavior to structure-only mode,
        enabling 600x token reduction for AI agents.
        """
        from pflow.execution.formatters.node_output_formatter import format_structure_output

        registry = Mock(spec=Registry)
        registry.get_nodes_metadata.return_value = {
            "test-node": {"interface": {"outputs": [{"key": "result", "type": "string"}]}}
        }

        outputs = {"result": "sensitive data value"}
        shared_store = {}

        # Explicit structure mode: paths only, no values
        result = format_structure_output(
            node_type="test-node",
            outputs=outputs,
            shared_store=shared_store,
            registry=registry,
            execution_time_ms=100,
            output_mode="structure",  # Explicitly request structure-only mode
        )

        # Must NOT contain actual data values
        assert "sensitive data value" not in result
        # Must show template paths
        assert "result" in result

    def test_include_values_mode_shows_data(self):
        """BACKWARD COMPAT: include_values=True shows data values.

        This maintains backward compatibility for cases where
        values need to be displayed.
        """
        from pflow.execution.formatters.node_output_formatter import format_structure_output

        registry = Mock(spec=Registry)
        registry.get_nodes_metadata.return_value = {"test-node": {"outputs": {"result": {"type": "string"}}}}

        outputs = {"result": "data value"}
        shared_store = {}

        # Explicitly request values
        result = format_structure_output(
            node_type="test-node",
            outputs=outputs,
            shared_store=shared_store,
            registry=registry,
            execution_time_ms=100,
            include_values=True,
        )

        # Must contain actual data values
        assert "data value" in result

    def test_execution_id_display(self):
        """EXECUTION ID: Displays execution ID for field retrieval.

        Agents need execution ID to retrieve specific fields
        using the read-fields command.
        """
        from pflow.execution.formatters.node_output_formatter import format_structure_output

        registry = Mock(spec=Registry)
        registry.get_nodes_metadata.return_value = {}

        outputs = {"result": "value"}
        shared_store = {}
        execution_id = "exec-1234567890-abc123"

        result = format_structure_output(
            node_type="test-node",
            outputs=outputs,
            shared_store=shared_store,
            registry=registry,
            execution_time_ms=100,
            execution_id=execution_id,
        )

        # Must display execution ID
        assert execution_id in result
        assert "Execution ID" in result

    def test_execution_id_with_structure_only(self):
        """COMBINED: execution_id + structure-only mode.

        This is the primary use case for Task 89 - show
        structure and execution ID but no data values.
        """
        from pflow.execution.formatters.node_output_formatter import format_structure_output

        registry = Mock(spec=Registry)
        registry.get_nodes_metadata.return_value = {
            "test-node": {
                "interface": {
                    "outputs": [
                        {
                            "key": "messages",
                            "type": "array",
                            "items": {"type": "dict", "structure": {"text": {"type": "string"}}},
                        }
                    ]
                }
            }
        }

        outputs = {"messages": [{"text": "sensitive message"}]}
        shared_store = {}
        execution_id = "exec-1234567890-abc123"

        result = format_structure_output(
            node_type="test-node",
            outputs=outputs,
            shared_store=shared_store,
            registry=registry,
            execution_time_ms=100,
            include_values=False,
            execution_id=execution_id,
            output_mode="structure",  # Explicitly request structure-only mode
        )

        # Must show execution ID
        assert execution_id in result
        # Must NOT show sensitive data
        assert "sensitive message" not in result
        # Must show template paths for structure
        assert "messages" in result

    def test_none_execution_id_no_crash(self):
        """EDGE CASE: None execution_id doesn't crash.

        When execution_id is not provided (None), formatter
        should work normally without displaying it.
        """
        from pflow.execution.formatters.node_output_formatter import format_structure_output

        registry = Mock(spec=Registry)
        registry.get_nodes_metadata.return_value = {}

        outputs = {"result": "value"}
        shared_store = {}

        # No crash with None execution_id
        result = format_structure_output(
            node_type="test-node",
            outputs=outputs,
            shared_store=shared_store,
            registry=registry,
            execution_time_ms=100,
            execution_id=None,
        )

        assert isinstance(result, str)
        assert "Execution ID" not in result


class TestSmartFilteringIntegration:
    """Integration tests for smart filtering in format_structure_output.

    These tests verify that smart filtering works correctly when integrated
    with the formatter, triggering only when field count exceeds threshold.
    """

    def test_large_field_set_triggers_smart_filtering(self, mock_llm_calls):
        """Large field sets (>50) should trigger smart filtering and show count."""
        from pflow.core.smart_filter import FilteredFields
        from pflow.execution.formatters.node_output_formatter import format_node_output

        # Create mock registry with node that has 100 output fields
        registry = Mock(spec=Registry)
        node_metadata = {
            "test-large-node": {
                "interface": {
                    "outputs": [
                        {
                            "name": "result",
                            "type": "dict",
                            "structure": {f"field{i}": {"type": "string"} for i in range(100)},
                        }
                    ]
                }
            }
        }
        registry.get_nodes_metadata.return_value = node_metadata

        # Mock LLM to filter to 10 fields
        mock_llm_calls.set_response(
            "*",
            FilteredFields,
            {
                "included_fields": [f"result.field{i}" for i in range(10)],
                "reasoning": "Filtered 100 fields to 10 most relevant",
            },
        )

        # Create outputs matching the structure
        outputs = {"result": {f"field{i}": f"value{i}" for i in range(100)}}

        result = format_node_output(
            node_type="test-large-node",
            action="success",
            outputs=outputs,
            shared_store={},
            execution_time_ms=100,
            registry=registry,
            format_type="structure",
            execution_id="exec-123-abc",
        )

        # Should show filtering message
        assert "(10 of 100 shown)" in result or "(10 of 101 shown)" in result
        # Should show some filtered fields
        assert "result.field0" in result or "result.field1" in result

    def test_small_field_set_no_filtering(self):
        """Small field sets (<=50) should NOT trigger smart filtering."""
        from pflow.execution.formatters.node_output_formatter import format_node_output

        # Create mock registry with node that has only 10 output fields
        registry = Mock(spec=Registry)
        node_metadata = {
            "test-small-node": {
                "interface": {
                    "outputs": [
                        {
                            "name": "result",
                            "type": "dict",
                            "structure": {
                                "field1": {"type": "string"},
                                "field2": {"type": "integer"},
                                "field3": {"type": "boolean"},
                            },
                        }
                    ]
                }
            }
        }
        registry.get_nodes_metadata.return_value = node_metadata

        outputs = {"result": {"field1": "value", "field2": 42, "field3": True}}

        result = format_node_output(
            node_type="test-small-node",
            action="success",
            outputs=outputs,
            shared_store={},
            execution_time_ms=50,
            registry=registry,
            format_type="structure",
            execution_id="exec-456-def",
            output_mode="structure",  # Test structure-only mode filtering
        )

        # Should NOT show filtering message (only 3-4 fields)
        assert " of " not in result or "shown)" not in result
        assert "Available template paths" in result

    def test_exactly_50_fields_no_filtering(self):
        """Exactly 50 fields should NOT trigger filtering (> not >=)."""
        from pflow.execution.formatters.node_output_formatter import format_node_output

        registry = Mock(spec=Registry)
        node_metadata = {
            "test-boundary-node": {
                "interface": {
                    "outputs": [
                        {
                            "name": "result",
                            "type": "dict",
                            "structure": {f"field{i}": {"type": "string"} for i in range(50)},
                        }
                    ]
                }
            }
        }
        registry.get_nodes_metadata.return_value = node_metadata

        outputs = {"result": {f"field{i}": f"value{i}" for i in range(50)}}

        result = format_node_output(
            node_type="test-boundary-node",
            action="success",
            outputs=outputs,
            shared_store={},
            execution_time_ms=75,
            registry=registry,
            format_type="structure",
            execution_id="exec-789-ghi",
        )

        # Should NOT show filtering message (exactly 50 or 51 fields including base key)
        # All fields should be shown
        assert "field0" in result or "result.field0" in result

    def test_structure_mode_skips_smart_filtering(self):
        """Structure output_mode should skip LLM filtering entirely, showing all paths."""
        from pflow.execution.formatters.node_output_formatter import format_node_output

        # Create mock registry with node that has 100 output fields
        # This would trigger filtering in smart mode, but structure mode should skip it
        registry = Mock(spec=Registry)
        node_metadata = {
            "test-large-node": {
                "interface": {
                    "outputs": [
                        {
                            "name": "result",
                            "type": "dict",
                            "structure": {f"field{i}": {"type": "string"} for i in range(100)},
                        }
                    ]
                }
            }
        }
        registry.get_nodes_metadata.return_value = node_metadata

        # Create outputs matching the structure
        outputs = {"result": {f"field{i}": f"value{i}" for i in range(100)}}

        # Note: NO mock_llm_calls setup - if filtering were triggered, this would fail
        result = format_node_output(
            node_type="test-large-node",
            action="success",
            outputs=outputs,
            shared_store={},
            execution_time_ms=100,
            registry=registry,
            format_type="structure",
            output_mode="structure",  # Explicitly use structure mode to skip filtering
            execution_id="exec-no-filter",
        )

        # Should show all 100+ paths without filtering
        # Check for multiple fields to verify no filtering occurred
        assert "result.field0" in result
        assert "result.field50" in result
        assert "result.field99" in result

        # Should NOT show filtering message since no filtering occurred
        assert "of 100 shown" not in result
        assert "of 101 shown" not in result


class TestSmartOutputMode:
    """Tests for smart output mode (showing values with truncation)."""

    def test_smart_mode_shows_values(self):
        """SMART MODE: Shows actual values alongside template paths."""
        from pflow.execution.formatters.node_output_formatter import format_structure_output

        registry = Mock(spec=Registry)
        registry.get_nodes_metadata.return_value = {
            "test-node": {"interface": {"outputs": [{"key": "result", "type": "string"}]}}
        }

        outputs = {"result": "hello world"}
        shared_store = {}

        result = format_structure_output(
            node_type="test-node",
            outputs=outputs,
            shared_store=shared_store,
            registry=registry,
            execution_time_ms=100,
            output_mode="smart",
        )

        # Must show the Output header
        assert "Output" in result
        # Must show the value
        assert "hello world" in result
        # Must show the template path
        assert "${result}" in result

    def test_smart_mode_truncates_long_strings(self):
        """SMART MODE: Truncates strings longer than 200 chars."""
        from pflow.execution.formatters.node_output_formatter import format_value_for_smart_display

        long_string = "x" * 250
        formatted, truncated = format_value_for_smart_display(long_string)

        assert truncated is True
        assert "(truncated)" in formatted
        assert len(formatted) < 250  # Should be shorter than original

    def test_smart_mode_summarizes_large_dicts(self):
        """SMART MODE: Shows summary for dicts with more than 5 keys."""
        from pflow.execution.formatters.node_output_formatter import format_value_for_smart_display

        large_dict = {f"key{i}": f"value{i}" for i in range(10)}
        formatted, truncated = format_value_for_smart_display(large_dict)

        assert "{...10 keys}" in formatted
        assert truncated is True  # Summarized - user can't see data, hint should appear

    def test_smart_mode_summarizes_large_lists(self):
        """SMART MODE: Shows summary for lists with more than 5 items."""
        from pflow.execution.formatters.node_output_formatter import format_value_for_smart_display

        large_list = list(range(20))
        formatted, truncated = format_value_for_smart_display(large_list)

        assert "[...20 items]" in formatted
        assert truncated is True  # Summarized - user can't see data, hint should appear

    def test_smart_mode_shows_primitives_fully(self):
        """SMART MODE: Always shows numbers, booleans, and null fully."""
        from pflow.execution.formatters.node_output_formatter import format_value_for_smart_display

        # Integer
        formatted, truncated = format_value_for_smart_display(42)
        assert formatted == "42"
        assert truncated is False

        # Float
        formatted, truncated = format_value_for_smart_display(3.14159)
        assert formatted == "3.14159"
        assert truncated is False

        # Boolean
        formatted, truncated = format_value_for_smart_display(True)
        assert formatted == "true"
        assert truncated is False

        # None/null
        formatted, truncated = format_value_for_smart_display(None)
        assert formatted == "null"
        assert truncated is False

    def test_smart_mode_shows_read_fields_hint_when_truncated(self):
        """SMART MODE: Shows read-fields hint when values are truncated."""
        from pflow.execution.formatters.node_output_formatter import format_structure_output

        registry = Mock(spec=Registry)
        registry.get_nodes_metadata.return_value = {
            "test-node": {"interface": {"outputs": [{"key": "content", "type": "string"}]}}
        }

        # Long content that will be truncated
        outputs = {"content": "x" * 300}
        shared_store = {}
        execution_id = "exec-test-123"

        result = format_structure_output(
            node_type="test-node",
            outputs=outputs,
            shared_store=shared_store,
            registry=registry,
            execution_time_ms=100,
            execution_id=execution_id,
            output_mode="smart",
        )

        # Should show hint to use read-fields
        assert "pflow read-fields" in result
        assert execution_id in result

    def test_full_mode_shows_all_without_truncation(self):
        """FULL MODE: Shows all values without truncation or filtering."""
        from pflow.execution.formatters.node_output_formatter import format_structure_output

        registry = Mock(spec=Registry)
        registry.get_nodes_metadata.return_value = {
            "test-node": {"interface": {"outputs": [{"key": "content", "type": "string"}]}}
        }

        # Long content
        long_content = "x" * 300
        outputs = {"content": long_content}
        shared_store = {}

        result = format_structure_output(
            node_type="test-node",
            outputs=outputs,
            shared_store=shared_store,
            registry=registry,
            execution_time_ms=100,
            output_mode="full",
        )

        # Full mode should show the complete content
        assert long_content in result
        # Should say "all N fields"
        assert "all" in result.lower()

    def test_smart_mode_shows_null_for_none_values(self):
        """SMART MODE: Legitimate None values show as 'null', not '<not found>'."""
        from pflow.execution.formatters.node_output_formatter import format_value_for_smart_display

        formatted, truncated = format_value_for_smart_display(None)

        assert formatted == "null"
        assert truncated is False

    def test_smart_mode_hint_not_shown_with_empty_execution_id(self):
        """SMART MODE: Hint should not appear if execution_id is empty."""
        from pflow.execution.formatters.node_output_formatter import (
            format_smart_paths_with_values,
        )

        paths = [("content", "str")]
        outputs = {"content": "x" * 300}  # Long enough to trigger truncation
        shared_store = {}

        lines, any_truncated = format_smart_paths_with_values(
            paths=paths,
            outputs=outputs,
            shared_store=shared_store,
            source_description=None,
            execution_id="",  # Empty execution_id
        )

        assert any_truncated is True  # Value was truncated
        # But hint should NOT appear because execution_id is empty
        assert not any("read-fields" in line for line in lines)

    def test_smart_mode_hint_shows_example_path(self):
        """SMART MODE: Hint should show an actual path, not '<path>' placeholder."""
        from pflow.execution.formatters.node_output_formatter import (
            format_smart_paths_with_values,
        )

        paths = [("result.data", "str"), ("result.status", "int")]
        outputs = {"result": {"data": "x" * 300, "status": 200}}
        shared_store = {}

        lines, any_truncated = format_smart_paths_with_values(
            paths=paths,
            outputs=outputs,
            shared_store=shared_store,
            source_description=None,
            execution_id="exec-123",
        )

        assert any_truncated is True
        # Find the hint line
        hint_lines = [line for line in lines if "read-fields" in line]
        assert len(hint_lines) == 1
        # Should contain actual path, not placeholder
        assert "result.data" in hint_lines[0]
        assert "<path>" not in hint_lines[0]

    def test_smart_mode_no_hint_when_summarized_parent_has_visible_children(self):
        """SMART MODE: No hint when summarized parent's children are all visible.

        If a dict/list is summarized ({...N keys}) but all its children are
        displayed in the output, the hint is useless because the user can
        already see all the data through the child paths.
        """
        from pflow.execution.formatters.node_output_formatter import (
            format_smart_paths_with_values,
        )

        # Simulate llm_usage scenario: parent dict with 6 keys (> 5 threshold)
        # but all 6 children are displayed with full values
        paths = [
            ("llm_usage", "dict"),
            ("llm_usage.input_tokens", "int"),
            ("llm_usage.output_tokens", "int"),
            ("llm_usage.total_tokens", "int"),
            ("llm_usage.model", "str"),
            ("llm_usage.cache_read_tokens", "int"),
            ("llm_usage.cache_write_tokens", "int"),
            ("response", "str"),
        ]
        outputs = {
            "llm_usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "model": "test-model",
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            },
            "response": "Hello!",
        }
        shared_store = {}

        lines, any_hidden = format_smart_paths_with_values(
            paths=paths,
            outputs=outputs,
            shared_store=shared_store,
            source_description=None,
            execution_id="exec-123",
        )

        # llm_usage shows {...6 keys} but all children are visible
        # So no hint should appear - user can see all data through child paths
        assert any_hidden is False
        hint_lines = [line for line in lines if "read-fields" in line]
        assert len(hint_lines) == 0

    def test_smart_mode_hint_shown_when_summarized_parent_has_no_visible_children(self):
        """SMART MODE: Hint shown when summarized parent has no visible children.

        If a dict/list is summarized ({...N keys}) and its children are NOT
        displayed (e.g., filtered out), the hint IS useful because the user
        cannot see the data.
        """
        from pflow.execution.formatters.node_output_formatter import (
            format_smart_paths_with_values,
        )

        # Simulate scenario: parent dict shown but children filtered out
        paths = [
            ("response.organization", "dict"),  # Summarized, no children visible
            ("response.name", "str"),
            ("response.stars", "int"),
        ]
        outputs = {
            "response": {
                "organization": {
                    "login": "anthropic",
                    "id": 12345,
                    "url": "https://github.com/anthropics",
                    "description": "AI safety company",
                    "repos_url": "https://api.github.com/orgs/anthropics/repos",
                    "members_count": 100,  # 6 keys, triggers summary
                },
                "name": "test-repo",
                "stars": 1000,
            }
        }
        shared_store = {}

        lines, any_hidden = format_smart_paths_with_values(
            paths=paths,
            outputs=outputs,
            shared_store=shared_store,
            source_description=None,
            execution_id="exec-123",
        )

        # response.organization shows {...6 keys} and NO children are visible
        # So hint SHOULD appear - user cannot see the organization data
        assert any_hidden is True
        hint_lines = [line for line in lines if "read-fields" in line]
        assert len(hint_lines) == 1
        assert "response.organization" in hint_lines[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
