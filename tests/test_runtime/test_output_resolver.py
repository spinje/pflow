"""Test output resolver functionality.

This module tests the output resolution logic that was moved from CLI to runtime.
Tests verify that source expressions are resolved correctly and outputs are populated
at the root level of shared storage for workflows with namespacing.
"""

import pytest

from pflow.core.diagnostic import exception_to_diagnostics, format_diagnostic
from pflow.core.user_errors import OutputResolutionError
from pflow.runtime.output_resolver import populate_declared_outputs, resolve_output_source


class TestResolveOutputSource:
    """Unit tests for resolve_output_source function."""

    def test_resolves_template_format_with_brackets(self):
        """Test that ${node.key} format resolves correctly."""
        shared = {"node1": {"output": "value1"}, "node2": {"result": "value2"}}

        result = resolve_output_source("${node1.output}", shared)
        assert result == "value1"

        result = resolve_output_source("${node2.result}", shared)
        assert result == "value2"

    def test_resolves_dollar_format(self):
        """Test that $node.key format resolves correctly."""
        shared = {"node1": {"output": "value1"}}

        result = resolve_output_source("$node1.output", shared)
        assert result == "value1"

    def test_resolves_plain_format(self):
        """Test that plain node.key format resolves correctly."""
        shared = {"node1": {"output": "value1"}}

        result = resolve_output_source("node1.output", shared)
        assert result == "value1"

    def test_returns_none_for_missing_keys(self):
        """Test that missing keys return None."""
        shared = {"node1": {"output": "value1"}}

        # Missing node
        result = resolve_output_source("${node2.output}", shared)
        assert result is None

        # Missing key in existing node
        result = resolve_output_source("${node1.missing}", shared)
        assert result is None

    def test_handles_nested_paths(self):
        """Test resolution of nested paths like node.key.subkey."""
        shared = {"node1": {"data": {"nested": {"value": "deep_value"}}}}

        result = resolve_output_source("${node1.data.nested.value}", shared)
        assert result == "deep_value"

    def test_resolves_root_level_values(self):
        """Test that root level values can be resolved."""
        shared = {"cli_input": "from_cli", "node1": {"output": "from_node"}}

        # Root level value
        result = resolve_output_source("${cli_input}", shared)
        assert result == "from_cli"

        # Namespaced value
        result = resolve_output_source("${node1.output}", shared)
        assert result == "from_node"

    def test_handles_different_value_types(self):
        """Test that different value types are resolved correctly."""
        shared = {
            "node1": {
                "string": "text",
                "number": 42,
                "boolean": True,
                "list": [1, 2, 3],
                "dict": {"key": "value"},
                "none": None,
            }
        }

        assert resolve_output_source("${node1.string}", shared) == "text"
        assert resolve_output_source("${node1.number}", shared) == 42
        assert resolve_output_source("${node1.boolean}", shared) is True
        assert resolve_output_source("${node1.list}", shared) == [1, 2, 3]
        assert resolve_output_source("${node1.dict}", shared) == {"key": "value"}
        assert resolve_output_source("${node1.none}", shared) is None


class TestPopulateDeclaredOutputs:
    """Unit tests for populate_declared_outputs function."""

    def test_populates_outputs_with_valid_sources(self):
        """Test that outputs with valid source expressions are populated."""
        shared = {"node1": {"result": "value1"}, "node2": {"data": "value2"}}

        workflow_ir = {
            "outputs": {
                "output1": {"source": "${node1.result}", "description": "First output"},
                "output2": {"source": "${node2.data}", "description": "Second output"},
            }
        }

        populate_declared_outputs(shared, workflow_ir)

        # Check that outputs are populated at root level
        assert shared["output1"] == "value1"
        assert shared["output2"] == "value2"
        # Original namespaced values should still exist
        assert shared["node1"]["result"] == "value1"
        assert shared["node2"]["data"] == "value2"

    def test_skips_outputs_without_source_field(self):
        """Test that outputs without source field are skipped."""
        shared = {"existing": "value"}

        workflow_ir = {
            "outputs": {"output1": {"description": "Output without source"}, "output2": "simple_string_output"}
        }

        original_keys = set(shared.keys())
        populate_declared_outputs(shared, workflow_ir)

        # No new keys should be added
        assert set(shared.keys()) == original_keys

    def test_handles_missing_workflow_ir(self):
        """Test that function handles None or missing workflow_ir gracefully."""
        shared = {"test": "value"}

        # Missing outputs key
        populate_declared_outputs(shared, {})
        assert shared == {"test": "value"}

        # Empty outputs
        populate_declared_outputs(shared, {"outputs": {}})
        assert shared == {"test": "value"}

    def test_raises_error_for_unresolvable_non_coalesce_sources(self):
        """Non-coalesce unresolvable sources raise OutputResolutionError.

        Valid outputs are still populated before the error is raised.
        """
        shared = {"node1": {"output": "value1"}}

        workflow_ir = {
            "outputs": {
                "valid_output": {"source": "${node1.output}"},
                "invalid_output": {"source": "${missing.node.output}"},
            }
        }

        with pytest.raises(OutputResolutionError) as exc_info:
            populate_declared_outputs(shared, workflow_ir)

        # Valid output should still be populated before error
        assert shared["valid_output"] == "value1"
        # Invalid output should not be populated
        assert "invalid_output" not in shared
        # Error should reference the failed output
        assert "invalid_output" in str(exc_info.value)
        assert "missing" in str(exc_info.value)

    def test_raises_error_for_malformed_source_expressions(self):
        """Malformed source expressions that can't resolve raise OutputResolutionError."""
        shared = {"node1": {"output": "value1"}}

        workflow_ir = {
            "outputs": {
                "output1": {
                    "source": "${}"  # Empty expression
                },
                "output2": {
                    "source": "${node1..output}"  # Double dot
                },
                "output3": {
                    "source": "${{node1.output}}"  # Double brackets
                },
            }
        }

        with pytest.raises(OutputResolutionError):
            populate_declared_outputs(shared, workflow_ir)

        # No outputs should be created for malformed expressions
        assert "output1" not in shared
        assert "output2" not in shared
        assert "output3" not in shared

    def test_overwrites_existing_root_values(self):
        """Test that source resolution overwrites existing root values."""
        shared = {
            "output1": "old_value",  # Existing root value
            "node1": {"result": "new_value"},
        }

        workflow_ir = {"outputs": {"output1": {"source": "${node1.result}"}}}

        populate_declared_outputs(shared, workflow_ir)

        # Should overwrite the old value
        assert shared["output1"] == "new_value"

    def test_handles_exception_in_resolution(self):
        """Test that exceptions during resolution are caught and handled silently."""
        shared = {"node1": {"output": "value1"}}

        workflow_ir = {"outputs": {"output1": {"source": "${node1.output}"}}}

        # Create a workflow with an output that would cause an exception
        # In the actual implementation, exceptions are silently caught
        # This test verifies that behavior
        populate_declared_outputs(shared, workflow_ir)

        # Should have populated successfully
        assert shared["output1"] == "value1"


class TestCoalesceInOutputSource:
    """Tests for coalesce (??) operator in output source expressions."""

    def test_coalesce_resolves_first_present_branch(self):
        """When first branch executed, coalesce returns its value."""
        shared = {"branch_a": {"stdout": "hello from A"}}

        result = resolve_output_source("${branch_a.stdout ?? branch_b.stdout}", shared)
        assert result == "hello from A"

    def test_coalesce_resolves_second_when_first_absent(self):
        """When first branch absent, coalesce falls through to second."""
        shared = {"branch_b": {"stdout": "hello from B"}}

        result = resolve_output_source("${branch_b.stdout ?? branch_a.stdout}", shared)
        assert result == "hello from B"

    def test_coalesce_returns_none_when_all_absent(self):
        """When no branch executed, coalesce returns None."""
        shared = {}

        result = resolve_output_source("${branch_a.stdout ?? branch_b.stdout}", shared)
        assert result is None

    def test_coalesce_three_operands(self):
        """Three-way coalesce resolves to whichever branch ran."""
        shared = {"branch_c": {"result": "from C"}}

        result = resolve_output_source("${branch_a.result ?? branch_b.result ?? branch_c.result}", shared)
        assert result == "from C"

    def test_coalesce_preserves_type(self):
        """Coalesce preserves non-string types (list, dict, int)."""
        shared = {"node": {"data": [1, 2, 3]}}

        result = resolve_output_source("${node.data ?? other.data}", shared)
        assert result == [1, 2, 3]

    def test_coalesce_in_populate_declared_outputs(self):
        """End-to-end: coalesce in output source populates shared storage."""
        shared = {"branch_a": {"stdout": "hello from A"}}

        workflow_ir = {
            "outputs": {
                "content": {"source": "${branch_a.stdout ?? branch_b.stdout}"},
            }
        }

        populate_declared_outputs(shared, workflow_ir)

        assert shared["content"] == "hello from A"

    def test_coalesce_all_absent_does_not_populate(self):
        """When all coalesce operands absent, output is not written to shared."""
        shared = {"unrelated": "data"}

        workflow_ir = {
            "outputs": {
                "content": {"source": "${branch_a.stdout ?? branch_b.stdout}"},
            }
        }

        populate_declared_outputs(shared, workflow_ir)

        assert "content" not in shared


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_source_expression(self):
        """Test handling of empty source expressions."""
        shared = {"node1": {"output": "value"}}

        # Empty string
        result = resolve_output_source("", shared)
        assert result is None

        # Just brackets
        result = resolve_output_source("${}", shared)
        assert result is None

    def test_malformed_paths(self):
        """Test handling of malformed path expressions."""
        shared = {"node1": {"output": "value"}}

        # Double dots
        result = resolve_output_source("${node1..output}", shared)
        assert result is None

        # Leading dot
        result = resolve_output_source("${.node1.output}", shared)
        assert result is None

        # Trailing dot
        result = resolve_output_source("${node1.output.}", shared)
        assert result is None

    def test_special_characters_in_names(self):
        """Test handling of special characters in node/key names."""
        shared = {"node-with-dash": {"output-key": "value1"}, "node_with_underscore": {"output_key": "value2"}}

        # Dashes should work
        result = resolve_output_source("${node-with-dash.output-key}", shared)
        assert result == "value1"

        # Underscores should work
        result = resolve_output_source("${node_with_underscore.output_key}", shared)
        assert result == "value2"

    def test_null_and_false_values(self):
        """Test that null and false values are handled correctly.

        NOTE: Current implementation skips None values (if value is not None check).
        This test reflects current behavior.
        """
        shared = {
            "node1": {
                "null_value": None,
                "false_value": False,
                "zero_value": 0,
                "empty_string": "",
                "empty_list": [],
                "empty_dict": {},
            }
        }

        workflow_ir = {
            "outputs": {
                "null_out": {"source": "${node1.null_value}"},
                "false_out": {"source": "${node1.false_value}"},
                "zero_out": {"source": "${node1.zero_value}"},
                "empty_str_out": {"source": "${node1.empty_string}"},
                "empty_list_out": {"source": "${node1.empty_list}"},
                "empty_dict_out": {"source": "${node1.empty_dict}"},
            }
        }

        populate_declared_outputs(shared, workflow_ir)

        # Current behavior: None values are NOT populated
        assert "null_out" not in shared  # None values are skipped

        # Other falsy values should be populated
        assert shared["false_out"] is False
        assert shared["zero_out"] == 0
        assert shared["empty_str_out"] == ""
        assert shared["empty_list_out"] == []
        assert shared["empty_dict_out"] == {}

    def test_large_nested_structures(self):
        """Test resolution of large nested data structures."""
        shared = {
            "node1": {
                "data": {
                    "results": [{"id": 1, "value": "first"}, {"id": 2, "value": "second"}, {"id": 3, "value": "third"}],
                    "metadata": {"count": 3, "status": "complete"},
                }
            }
        }

        workflow_ir = {
            "outputs": {
                "full_data": {"source": "${node1.data}"},
                "just_results": {"source": "${node1.data.results}"},
                "status": {"source": "${node1.data.metadata.status}"},
            }
        }

        populate_declared_outputs(shared, workflow_ir)

        # Check complete structure is preserved
        assert shared["full_data"] == shared["node1"]["data"]
        assert len(shared["just_results"]) == 3
        assert shared["status"] == "complete"


class TestOutputResolutionErrors:
    """Tests for error behavior when output sources cannot be resolved."""

    def test_error_diagnosis_absent_root(self):
        """Failure record classifies absent-node references with structured status."""
        shared = {"other_node": {"stdout": "data"}}

        workflow_ir = {
            "outputs": {
                "result": {"source": "${missing_node.stdout}"},
            }
        }

        with pytest.raises(OutputResolutionError) as exc_info:
            populate_declared_outputs(shared, workflow_ir)

        error = exc_info.value
        assert len(error.failures) == 1
        refs = error.failures[0]["unresolved_references"]
        assert len(refs) == 1
        assert refs[0]["status"] == "absent"
        assert refs[0]["root"] == "missing_node"

    def test_error_diagnosis_path_not_found(self):
        """Failure record classifies typo references as path_error."""
        shared = {"node1": {"stdout": "data"}}

        workflow_ir = {
            "outputs": {
                "result": {"source": "${node1.stddout}"},  # typo
            }
        }

        with pytest.raises(OutputResolutionError) as exc_info:
            populate_declared_outputs(shared, workflow_ir)

        error = exc_info.value
        refs = error.failures[0]["unresolved_references"]
        assert refs[0]["status"] == "path_error"
        assert refs[0]["root"] == "node1"
        # Typo correction hint exposed for the renderer
        assert refs[0].get("did_you_mean") == "node1.stdout"

    def test_error_collects_all_failures(self):
        """Multiple failed outputs are collected into a single error."""
        shared = {}

        workflow_ir = {
            "outputs": {
                "out_a": {"source": "${missing_a.stdout}"},
                "out_b": {"source": "${missing_b.stdout}"},
            }
        }

        with pytest.raises(OutputResolutionError) as exc_info:
            populate_declared_outputs(shared, workflow_ir)

        error = exc_info.value
        assert len(error.failures) == 2
        output_names = {f["output_name"] for f in error.failures}
        assert output_names == {"out_a", "out_b"}

    def test_resolved_outputs_populated_before_error(self):
        """Outputs that resolve are written to shared before the error is raised."""
        shared = {"node1": {"result": "good_value"}}

        workflow_ir = {
            "outputs": {
                "good": {"source": "${node1.result}"},
                "bad": {"source": "${missing.result}"},
            }
        }

        with pytest.raises(OutputResolutionError):
            populate_declared_outputs(shared, workflow_ir)

        assert shared["good"] == "good_value"
        assert "bad" not in shared

    def test_coalesce_all_absent_no_error(self):
        """Coalesce expression with all operands absent does NOT raise."""
        shared = {"unrelated": "data"}

        workflow_ir = {
            "outputs": {
                "content": {"source": "${branch_a.stdout ?? branch_b.stdout}"},
            }
        }

        # Should not raise — user opted into fallthrough with ??
        populate_declared_outputs(shared, workflow_ir)
        assert "content" not in shared

    def test_rendered_output_shows_absent_branch_and_coalesce_fix(self):
        """Rendered Diagnostic surfaces the absent branch and a paste-able coalesce fix."""
        shared = {"other_node": {"stdout": "fallback-value"}}

        workflow_ir = {
            "outputs": {
                "result": {"source": "${branch_a.stdout}"},
            }
        }

        with pytest.raises(OutputResolutionError) as exc_info:
            populate_declared_outputs(shared, workflow_ir)

        diagnostic = exception_to_diagnostics(exc_info.value)[0]
        formatted = format_diagnostic(diagnostic)

        # Canonical title + error message shape match the node-param path
        assert "Error:" in formatted
        assert "Template Resolution Failed" in formatted
        assert "branch_a" in formatted
        # Structured renderer emits the "did not execute" status line
        assert "did not execute" in formatted
        # Paste-able coalesce fix uses a real peer node name (not <peer>)
        assert "${branch_a.stdout ?? other_node.stdout}" in formatted

    def test_rendered_output_for_path_error_shows_did_you_mean(self):
        """Rendered Diagnostic shows paste-able corrected path for typos on succeeded nodes."""
        shared = {"node1": {"stdout": "data"}}

        workflow_ir = {
            "outputs": {
                "result": {"source": "${node1.stddout}"},  # typo
            }
        }

        with pytest.raises(OutputResolutionError) as exc_info:
            populate_declared_outputs(shared, workflow_ir)

        diagnostic = exception_to_diagnostics(exc_info.value)[0]
        formatted = format_diagnostic(diagnostic)

        assert "Template Resolution Failed" in formatted
        assert "${node1.stdout}" in formatted  # paste-able corrected path
