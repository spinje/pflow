"""Critical guardrail tests for workflow_save_formatter.

These tests protect against bugs that CLI integration tests don't catch:
- MCP-specific parameter combinations (None metadata)
- Edge cases with empty inputs
- Type hint generation bugs

Each test catches a specific real-world bug that would break production.
"""

from pflow.execution.formatters.workflow_save_formatter import (
    format_execution_hint,
    format_save_success,
)


class TestMCPIntegrationGuards:
    """Tests that catch MCP-specific bugs CLI tests don't cover."""

    def test_format_save_success_handles_none_metadata(self):
        """MCP INTEGRATION: Prevent crash when metadata is None (MCP default).

        Real bug this catches: MCP always passes metadata=None, but if
        formatter expects dict and calls metadata.get(), it crashes.

        CLI either generates metadata or omits the parameter entirely,
        so CLI tests won't catch this.
        """
        # MCP call pattern
        result = format_save_success(
            name="test-workflow",
            saved_path="/path/to/workflow.json",
            workflow_ir={"inputs": {"param": {"required": True, "type": "string"}}},
            metadata=None,  # MCP always passes None
        )

        assert isinstance(result, str)
        assert "test-workflow" in result
        assert "✓ Saved workflow" in result
        # Should not crash, and should not include "Discoverable by" line
        assert "Discoverable by" not in result


class TestEdgeCaseGuards:
    """Tests that catch edge cases causing crashes."""

    def test_format_execution_hint_handles_empty_inputs(self):
        """EDGE CASE: Prevent crashes on workflows with no parameters.

        Real bug this catches: Workflow with empty inputs dict causes
        iteration failure if not handled properly.

        CLI tests would catch this eventually, but unit test gives
        immediate feedback (10ms vs 2s).
        """
        # Empty inputs - should return just base command
        result = format_execution_hint(
            name="no-params-workflow",
            workflow_ir={"inputs": {}},  # Empty inputs
        )

        assert result == "pflow no-params-workflow"
        assert "=" not in result  # No parameters

    def test_format_execution_hint_handles_missing_inputs_key(self):
        """EDGE CASE: Handle workflow IR with no inputs key at all.

        Real bug this catches: Some workflows might not have inputs
        key defined, causing KeyError.
        """
        result = format_execution_hint(
            name="no-inputs-key",
            workflow_ir={},  # No inputs key
        )

        assert result == "pflow no-inputs-key"

    def test_format_save_success_handles_empty_inputs(self):
        """EDGE CASE: Save success with no parameters should work.

        Real bug this catches: Empty inputs might cause issues in
        optional params detection.
        """
        result = format_save_success(
            name="simple-workflow",
            saved_path="/path/to/workflow.json",
            workflow_ir={"inputs": {}},
            metadata=None,
        )

        assert "simple-workflow" in result
        assert "Optional params:" not in result  # No optional params


class TestTypePlaceholderGuards:
    """Tests that catch type hint mapping bugs."""

    def test_execution_hint_uses_correct_type_placeholders(self):
        """TYPE HINTS: Ensure correct placeholders for each parameter type.

        Real bug this catches: Boolean param shows <value> instead of
        <true/false>, confusing users about expected input format.
        """
        result = format_execution_hint(
            name="typed-workflow",
            workflow_ir={
                "inputs": {
                    "flag": {"required": True, "type": "boolean"},
                    "count": {"required": True, "type": "number"},
                    "name": {"required": True, "type": "string"},
                }
            },
        )

        # Check each type maps correctly (focus on most important ones)
        assert "flag=<true/false>" in result
        assert "count=<number>" in result
        assert "name=<value>" in result

        # Ensure all params are present
        assert "typed-workflow" in result
        assert "flag=" in result and "count=" in result and "name=" in result

    def test_execution_hint_orders_required_before_optional(self):
        """PARAMETER ORDER: Required params must come before optional.

        Real bug this catches: Optional params shown before required
        params, breaking command structure expectations.
        """
        result = format_execution_hint(
            name="mixed-params",
            workflow_ir={
                "inputs": {
                    "optional_param": {"required": False, "type": "string"},
                    "required_param": {"required": True, "type": "string"},
                }
            },
        )

        # Required must appear before optional
        required_pos = result.find("required_param=")
        optional_pos = result.find("optional_param=")
        assert required_pos < optional_pos, "required params must come before optional"
