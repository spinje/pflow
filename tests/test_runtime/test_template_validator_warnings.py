"""Tests for validation warning system.

Warning behavior:
- str type with nested access → WARNING (JSON auto-parsing is implicit/magical)
- any type with nested access → NO WARNING (explicit declaration by node author)
- dict type with nested access → NO WARNING (trusted structured data)
"""

from unittest.mock import Mock

from pflow.runtime.template_validator import TemplateValidator, ValidationWarning


def create_mock_registry_with_str_output():
    """Create a mock registry with str output type (triggers warning for nested access)."""
    registry = Mock()

    nodes_metadata = {
        "shell-node": {
            "interface": {
                "inputs": [],
                "outputs": [
                    {
                        "key": "stdout",
                        "type": "str",  # str type - nested access triggers warning
                        "description": "Command output",
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


def create_mock_registry_with_any_output():
    """Create a mock registry with any output type (NO warning - explicit declaration)."""
    registry = Mock()

    nodes_metadata = {
        "mcp-node": {
            "interface": {
                "inputs": [],
                "outputs": [
                    {
                        "key": "result",
                        "type": "any",  # any type - no warning (explicit)
                        "description": "Tool result",
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

    def test_str_nested_template_generates_warning(self):
        """str output with nested template should warn (JSON auto-parsing)."""
        workflow_ir = {
            "ir_version": "1.0.0",
            "nodes": [
                {
                    "id": "shell",
                    "type": "shell-node",
                    "params": {},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "Data: ${shell.stdout.field}"},
                },
            ],
            "edges": [{"from": "shell", "to": "consumer", "label": "default"}],
            "start_node": "shell",
        }

        registry = create_mock_registry_with_str_output()
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should NOT error - str allows nested access via JSON auto-parsing
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

        # Should warn about JSON auto-parsing
        assert len(warnings) == 1
        warning = warnings[0]
        assert "shell" in warning.node_id
        assert warning.output_type == "str"
        assert "field" in warning.nested_path
        assert "requires valid JSON" in warning.reason

    def test_any_nested_template_no_warning(self):
        """any output with nested template should NOT warn (explicit declaration)."""
        workflow_ir = {
            "ir_version": "1.0.0",
            "nodes": [
                {
                    "id": "mcp",
                    "type": "mcp-node",
                    "params": {},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "Data: ${mcp.result.data.field}"},
                },
            ],
            "edges": [{"from": "mcp", "to": "consumer", "label": "default"}],
            "start_node": "mcp",
        }

        registry = create_mock_registry_with_any_output()
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should NOT error
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

        # Should NOT warn - any is an explicit declaration
        assert len(warnings) == 0, f"any type should not warn, got: {warnings}"

    def test_no_warning_for_direct_access(self):
        """Direct output access should not warn (no nesting)."""
        workflow_ir = {
            "ir_version": "1.0.0",
            "nodes": [
                {
                    "id": "shell",
                    "type": "shell-node",
                    "params": {},
                },
                {"id": "consumer", "type": "llm", "params": {"prompt": "Data: ${shell.stdout}"}},
            ],
            "edges": [{"from": "shell", "to": "consumer", "label": "default"}],
            "start_node": "shell",
        }

        registry = create_mock_registry_with_str_output()
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should not error or warn - direct access, no nesting
        assert len(errors) == 0
        assert len(warnings) == 0

    def test_warning_dataclass_structure(self):
        """ValidationWarning should have all required fields."""
        warning = ValidationWarning(
            template="${test.stdout.data}",
            node_id="test-node",
            node_type="shell",
            output_key="stdout",
            output_type="str",
            reason="Test reason",
            nested_path="data",
        )

        assert warning.template == "${test.stdout.data}"
        assert warning.node_id == "test-node"
        assert warning.nested_path == "data"
        assert warning.output_type == "str"
        assert warning.output_key == "stdout"

    def test_multiple_nested_templates_generate_multiple_warnings(self):
        """Multiple nested accesses on str type should generate multiple warnings."""
        workflow_ir = {
            "ir_version": "1.0.0",
            "nodes": [
                {
                    "id": "shell",
                    "type": "shell-node",
                    "params": {},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    # Two nested accesses on str output
                    "params": {"prompt": "${shell.stdout.field1} and ${shell.stdout.field2}"},
                },
            ],
            "edges": [{"from": "shell", "to": "consumer", "label": "default"}],
            "start_node": "shell",
        }

        registry = create_mock_registry_with_str_output()
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 0, f"Expected no errors, got: {errors}"
        assert len(warnings) == 2, f"Expected 2 warnings, got: {warnings}"

    def test_warning_includes_correct_node_metadata(self):
        """Warning should include correct node and output metadata."""
        workflow_ir = {
            "ir_version": "1.0.0",
            "nodes": [
                {
                    "id": "my-shell",
                    "type": "shell-node",
                    "params": {},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "${my-shell.stdout.nested.path}"},
                },
            ],
            "edges": [{"from": "my-shell", "to": "consumer", "label": "default"}],
            "start_node": "my-shell",
        }

        registry = create_mock_registry_with_str_output()
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 0
        assert len(warnings) == 1

        warning = warnings[0]
        assert warning.node_id == "my-shell"
        assert warning.node_type == "shell-node"
        assert warning.output_key == "stdout"
        assert warning.output_type == "str"
        assert "nested.path" in warning.nested_path


class TestWarningEdgeCases:
    """Test edge cases in warning system."""

    def test_warnings_preserved_with_errors(self):
        """Warnings should be returned even when errors exist."""
        workflow_ir = {
            "ir_version": "1.0.0",
            "nodes": [
                {
                    "id": "shell",
                    "type": "shell-node",
                    "params": {},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {
                        # One valid nested access (warning) + one invalid reference (error)
                        "prompt": "${shell.stdout.field} ${nonexistent.value}"
                    },
                },
            ],
            "edges": [{"from": "shell", "to": "consumer", "label": "default"}],
            "start_node": "shell",
        }

        registry = create_mock_registry_with_str_output()
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should have error for nonexistent node
        assert len(errors) >= 1

        # Should still have warning for str nested access
        assert len(warnings) == 1
        assert "requires valid JSON" in warnings[0].reason
