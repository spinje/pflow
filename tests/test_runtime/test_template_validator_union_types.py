"""Test template validator with union type outputs.

This module tests that the template validator correctly handles union types
like 'dict|str' in node output declarations, allowing nested template access
when at least one type in the union supports traversal.

Related to Issue #66: Validator should allow nested template access for typed dict outputs.
"""

from unittest.mock import Mock

from pflow.registry import Registry
from pflow.runtime.template_validator import TemplateValidator


def create_mock_registry(nodes_metadata):
    """Helper to create a properly mocked registry.

    Args:
        nodes_metadata: Dict mapping node_type to metadata dict

    Returns:
        Mock Registry with get_nodes_metadata properly configured
    """
    registry = Registry()

    def get_nodes_metadata(node_types):
        """Mock implementation of get_nodes_metadata."""
        result = {}
        for node_type in node_types:
            if node_type in nodes_metadata:
                result[node_type] = nodes_metadata[node_type]
        return result

    registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata)
    return registry


class TestUnionTypeValidation:
    """Test template validation with union types in node outputs."""

    def test_dict_str_union_allows_nested_access(self):
        """Test that dict|str union type allows nested template access."""
        # Create workflow with node that has dict|str output
        workflow_ir = {
            "nodes": [
                {
                    "id": "http-call",
                    "type": "http",
                    "params": {"url": "https://api.example.com"},
                },
                {
                    "id": "process",
                    "type": "shell",
                    "params": {"command": "echo ${http-call.response.data}"},
                },
            ],
            "enable_namespacing": True,
        }

        # Mock registry with HTTP node having dict|str response
        registry = create_mock_registry({
            "http": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "response", "type": "dict|str"}],
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        # Validate - should pass without errors
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        assert len(warnings) == 0, "dict|str union should not generate warnings"

    def test_str_int_union_rejects_nested_access(self):
        """Test that str|int union type rejects nested template access."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.output.field}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "test-node": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "output", "type": "str|int"}],
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 1, "Expected 1 error for str|int union with nested access"
        assert "does not output 'output'" in errors[0] or "field" in errors[0]

    def test_dict_object_union_allows_nested_access(self):
        """Test that dict|object union allows nested access (both types traversable)."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.data.field}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "test-node": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "data", "type": "dict|object"}],
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        assert len(warnings) == 0, "dict|object union should not generate warnings"

    def test_dict_str_int_union_allows_nested_access(self):
        """Test that dict|str|int union allows nested access (dict part allows it)."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.result.nested}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "test-node": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "result", "type": "dict|str|int"}],
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        assert len(warnings) == 0, "dict|str|int union should not generate warnings"

    def test_any_str_union_generates_warning(self):
        """Test that unions containing 'any' generate warnings for nested access."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.data.field}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "test-node": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "data", "type": "any|str"}],
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        assert len(warnings) == 1, "any|str union should generate warning"
        assert warnings[0].output_type == "any|str"
        assert warnings[0].nested_path == "field"

    def test_dict_any_union_generates_warning(self):
        """Test that dict|any union generates warning (any part triggers it)."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.data.field}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "test-node": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "data", "type": "dict|any"}],
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        assert len(warnings) == 1, "dict|any union should generate warning"

    def test_case_insensitive_union_types(self):
        """Test that Dict|Str works (case-insensitive matching)."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.data.field}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "test-node": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "data", "type": "Dict|Str"}],  # Mixed case
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        assert len(warnings) == 0, "Case-insensitive Dict|Str should work"

    def test_whitespace_in_union_types(self):
        """Test that 'dict | str' works (handles whitespace around pipes)."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.data.field}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "test-node": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "data", "type": "dict | str"}],  # Whitespace
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        assert len(warnings) == 0, "Whitespace handling should work"

    def test_single_type_backward_compatibility(self):
        """Test that single types (non-union) still work exactly as before."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.data.field}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "test-node": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "data", "type": "dict"}],  # Single type
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Single dict type should allow nested access without warnings
        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        assert len(warnings) == 0, "Single dict type should not generate warnings"

    def test_pure_any_type_still_generates_warning(self):
        """Test that pure 'any' type (not in union) still generates warnings."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.data.field}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "test-node": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "data", "type": "any"}],  # Pure any
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        assert len(warnings) == 1, "Pure 'any' type should still generate warning"
        assert warnings[0].output_type == "any"

    def test_union_without_nested_access_no_warning(self):
        """Test that union types without nested access don't generate warnings."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.data}"},  # No nested access
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "test-node": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "data", "type": "dict|str"}],
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # No nested access, so no warnings even for union types
        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        assert len(warnings) == 0, "No warnings without nested access"


class TestUnionTypeEdgeCases:
    """Test edge cases and special scenarios for union type validation."""

    def test_empty_union_component(self):
        """Test handling of malformed union with empty component (e.g., 'dict||str')."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.data.field}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "test-node": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "data", "type": "dict||str"}],  # Double pipe
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should still work - empty string after strip is ignored
        assert len(errors) == 0, f"Expected no errors but got: {errors}"

    def test_base_access_on_union_type(self):
        """Test that accessing just the base key (no nesting) works for union types."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.response}"},  # No nesting
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "test-node": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "response", "type": "dict|str"}],
                    "params": [],
                },
            },
            "shell": {
                "interface": {"inputs": [], "outputs": [], "params": []},
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        assert len(warnings) == 0, "Base access should work without warnings"
