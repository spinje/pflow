"""Tests for validation warning system."""

from unittest.mock import Mock

from pflow.runtime.template_validator import TemplateValidator, ValidationWarning


def create_mock_registry_with_mcp():
    """Create a mock registry with MCP node metadata."""
    registry = Mock()

    nodes_metadata = {
        "mcp-googlesheets-composio-GOOGLESHEETS_BATCH_GET": {
            "interface": {
                "inputs": [{"key": "spreadsheet_id", "type": "str", "description": "Spreadsheet ID"}],
                "outputs": [
                    {
                        "key": "result",
                        "type": "Any",  # Capital A - triggers warning
                        "description": "Tool execution result",
                    }
                ],
                "params": [],
                "actions": ["default", "error"],
            }
        },
        "llm": {
            "interface": {
                "inputs": [{"key": "prompt", "type": "str", "description": "LLM prompt"}],
                "outputs": [{"key": "response", "type": "str", "description": "LLM response"}],
                "params": [],
                "actions": ["default", "error"],
            }
        },
    }

    def get_nodes_metadata(node_types):
        result = {}
        for node_type in node_types:
            if node_type in nodes_metadata:
                result[node_type] = nodes_metadata[node_type]
        return result

    registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata)
    return registry


class TestValidationWarnings:
    """Test validation warning generation."""

    def test_mcp_nested_template_generates_warning(self):
        """MCP node with nested template should warn, not error."""
        workflow_ir = {
            "ir_version": "1.0.0",
            "nodes": [
                {
                    "id": "mcp-node",
                    "type": "mcp-googlesheets-composio-GOOGLESHEETS_BATCH_GET",
                    "params": {"spreadsheet_id": "test"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "Data: ${mcp-node.result.data.valueRanges[0].values}"},
                },
            ],
            "edges": [{"from": "mcp-node", "to": "consumer", "label": "default"}],
            "start_node": "mcp-node",
        }

        registry = create_mock_registry_with_mcp()
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should NOT error
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

        # Should warn
        assert len(warnings) == 1
        warning = warnings[0]
        assert "mcp-node" in warning.node_id
        assert warning.output_type == "Any"
        assert "data.valueRanges[0].values" in warning.nested_path

    def test_no_warning_for_direct_access(self):
        """Direct output access should not warn."""
        workflow_ir = {
            "ir_version": "1.0.0",
            "nodes": [
                {
                    "id": "mcp-node",
                    "type": "mcp-googlesheets-composio-GOOGLESHEETS_BATCH_GET",
                    "params": {"spreadsheet_id": "test"},
                },
                {"id": "consumer", "type": "llm", "params": {"prompt": "Data: ${mcp-node.result}"}},
            ],
            "edges": [{"from": "mcp-node", "to": "consumer", "label": "default"}],
            "start_node": "mcp-node",
        }

        registry = create_mock_registry_with_mcp()
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should not error or warn
        assert len(errors) == 0
        assert len(warnings) == 0  # Direct access, no nesting

    def test_warning_dataclass_structure(self):
        """ValidationWarning should have all required fields."""
        warning = ValidationWarning(
            template="${test.result.data}",
            node_id="test-node",
            node_type="mcp-test",
            output_key="result",
            output_type="Any",
            reason="Test reason",
            nested_path="data",
        )

        assert warning.template == "${test.result.data}"
        assert warning.node_id == "test-node"
        assert warning.nested_path == "data"
        assert warning.output_type == "Any"
        assert warning.output_key == "result"

    def test_multiple_nested_templates_generate_multiple_warnings(self):
        """Multiple nested accesses should generate multiple warnings."""
        workflow_ir = {
            "ir_version": "1.0.0",
            "nodes": [
                {
                    "id": "mcp-node",
                    "type": "mcp-googlesheets-composio-GOOGLESHEETS_BATCH_GET",
                    "params": {"spreadsheet_id": "test"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {
                        "prompt": "Data: ${mcp-node.result.data.valueRanges[0].values} and ${mcp-node.result.data.range}"
                    },
                },
            ],
            "edges": [{"from": "mcp-node", "to": "consumer", "label": "default"}],
            "start_node": "mcp-node",
        }

        registry = create_mock_registry_with_mcp()
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should NOT error
        assert len(errors) == 0

        # Should warn for both templates
        assert len(warnings) == 2
        warning_paths = {w.nested_path for w in warnings}
        assert "data.valueRanges[0].values" in warning_paths
        assert "data.range" in warning_paths

    def test_warning_includes_correct_node_metadata(self):
        """Warning should include correct node ID and type."""
        workflow_ir = {
            "ir_version": "1.0.0",
            "nodes": [
                {
                    "id": "my-sheets-node",
                    "type": "mcp-googlesheets-composio-GOOGLESHEETS_BATCH_GET",
                    "params": {"spreadsheet_id": "test"},
                },
                {"id": "consumer", "type": "llm", "params": {"prompt": "Data: ${my-sheets-node.result.nested.field}"}},
            ],
            "edges": [{"from": "my-sheets-node", "to": "consumer", "label": "default"}],
            "start_node": "my-sheets-node",
        }

        registry = create_mock_registry_with_mcp()
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(warnings) == 1
        warning = warnings[0]
        assert warning.node_id == "my-sheets-node"
        assert warning.node_type == "mcp-googlesheets-composio-GOOGLESHEETS_BATCH_GET"
        assert warning.output_key == "result"
        assert warning.template == "${my-sheets-node.result.nested.field}"


class TestWarningEdgeCases:
    """Test edge cases in warning generation."""

    def test_no_warnings_for_empty_workflow(self):
        """Empty workflow should not generate warnings."""
        workflow_ir = {"ir_version": "1.0.0", "nodes": [], "edges": []}

        registry = create_mock_registry_with_mcp()
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 0
        assert len(warnings) == 0

    def test_warnings_preserved_with_errors(self):
        """Warnings should still be returned even when errors exist."""
        workflow_ir = {
            "ir_version": "1.0.0",
            "nodes": [
                {
                    "id": "mcp-node",
                    "type": "mcp-googlesheets-composio-GOOGLESHEETS_BATCH_GET",
                    "params": {"spreadsheet_id": "test"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {
                        # Warning: nested access on Any type
                        "prompt": "Data: ${mcp-node.result.data} and ${missing_variable}"  # Error: undefined
                    },
                },
            ],
            "edges": [{"from": "mcp-node", "to": "consumer", "label": "default"}],
            "start_node": "mcp-node",
        }

        registry = create_mock_registry_with_mcp()
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should have both error and warning
        assert len(errors) == 1  # Missing variable
        assert len(warnings) == 1  # Nested access on Any type
        assert "missing_variable" in errors[0]
        assert warnings[0].nested_path == "data"
