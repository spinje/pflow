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

    def test_str_int_union_allows_nested_access_with_warning(self):
        """Test that str|int union allows nested access (str supports JSON auto-parsing).

        Since str types support JSON auto-parsing at runtime, nested access is allowed
        but generates a warning to inform the user it can't be verified statically.
        """
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

        # No errors - str allows nested access via JSON auto-parsing
        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        # Warning about runtime validation
        assert len(warnings) == 1, "Expected warning for str|int nested access"
        assert "requires valid JSON" in warnings[0].reason

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

    def test_any_str_union_no_warning(self):
        """Test that any|str union does NOT generate warning (any is trusted)."""
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
        # any is trusted (explicit declaration) - no warning even with str in union
        assert len(warnings) == 0, "any|str union should NOT generate warning (any is trusted)"

    def test_dict_any_union_no_warning(self):
        """Test that dict|any union does NOT generate warning (both are trusted)."""
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
        # dict and any are both trusted - no warning
        assert len(warnings) == 0, "dict|any union should NOT generate warning"

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

    def test_pure_any_type_no_warning(self):
        """Test that pure 'any' type does NOT generate warning (trusted, explicit declaration)."""
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
        # any is an explicit declaration - node author knows what they're doing
        assert len(warnings) == 0, "Pure 'any' type should NOT generate warning (trusted)"

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
                    "type": "string-consumer",
                    "params": {"text": "${node1.data}"},  # No nested access
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
            "string-consumer": {
                "interface": {
                    "inputs": [],
                    "outputs": [],
                    "params": [{"key": "text", "type": "str"}],
                },
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # No nested access, so no warnings even for union types
        # dict|str is compatible with str (auto-serialization)
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
                    "type": "string-consumer",
                    "params": {"text": "${node1.response}"},  # No nesting
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
            "string-consumer": {
                "interface": {
                    "inputs": [],
                    "outputs": [],
                    "params": [{"key": "text", "type": "str"}],
                },
            },
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # dict|str is compatible with str (auto-serialization)
        assert len(errors) == 0, f"Expected no errors but got: {errors}"
        assert len(warnings) == 0, "Base access should work without warnings"
