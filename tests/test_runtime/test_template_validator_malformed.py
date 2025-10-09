"""Test malformed template syntax detection.

This module tests that the template validator catches malformed template syntax
like unclosed braces, empty templates, etc.
"""

from unittest.mock import Mock

from pflow.registry import Registry
from pflow.runtime.template_validator import TemplateValidator


def create_mock_registry(nodes_metadata):
    """Helper to create a properly mocked registry."""
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


class TestMalformedTemplateDetection:
    """Test detection of malformed template syntax."""

    def test_unclosed_template(self):
        """Test that unclosed template ${var is detected."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "echo ${variable"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 1, f"Expected 1 error but got {len(errors)}: {errors}"
        assert "Malformed template syntax" in errors[0]
        assert "test-node" in errors[0]
        assert "Found 1 '${' but only 0 valid template(s)" in errors[0]

    def test_empty_template(self):
        """Test that empty template ${} is detected."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "echo ${}"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "Malformed template syntax" in errors[0]
        assert "Found 1 '${' but only 0 valid template(s)" in errors[0]

    def test_whitespace_only_template(self):
        """Test that whitespace-only template ${ } is detected."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "echo ${ }"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "Malformed template syntax" in errors[0]

    def test_multiple_templates_one_malformed(self):
        """Test detection when there are multiple templates and one is malformed."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "shell",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.result} and ${unclosed"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "shell": {"interface": {"inputs": [], "outputs": [{"key": "result", "type": "str"}], "params": []}}
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should detect the malformed template
        assert any("Malformed template syntax" in err for err in errors)
        assert any("Found 2 '${' but only 1 valid template(s)" in err for err in errors)

    def test_valid_templates_no_false_positives(self):
        """Test that valid templates don't trigger false positives."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "shell",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.result}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "shell": {"interface": {"inputs": [], "outputs": [{"key": "result", "type": "str"}], "params": []}}
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should NOT have malformed template errors
        assert not any("Malformed template syntax" in err for err in errors)

    def test_nested_templates_valid(self):
        """Test that nested field access doesn't trigger false positives."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "http",
                    "params": {"url": "https://example.com"},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo ${node1.response.field.nested}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "http": {"interface": {"inputs": [], "outputs": [{"key": "response", "type": "dict|str"}], "params": []}},
            "shell": {"interface": {"inputs": [], "outputs": [], "params": []}},
        })

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should NOT have malformed template errors
        assert not any("Malformed template syntax" in err for err in errors)

    def test_malformed_in_nested_params(self):
        """Test detection of malformed templates in nested parameter structures."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "http",
                    "params": {"url": "https://example.com", "headers": {"Authorization": "Bearer ${token"}},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"http": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "Malformed template syntax" in errors[0]
        assert "headers" in errors[0]  # Should mention the nested parameter path

    def test_malformed_in_list_params(self):
        """Test detection of malformed templates in list parameters."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"commands": ["echo ${valid}", "echo ${invalid"]},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should detect malformed template in the list
        malformed_errors = [err for err in errors if "Malformed template syntax" in err]
        assert len(malformed_errors) == 1
        assert "commands[1]" in malformed_errors[0]

    def test_no_dollar_brace_no_error(self):
        """Test that strings without ${ don't trigger errors."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "echo hello world"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should have no errors
        assert len(errors) == 0


class TestMalformedTemplateEdgeCases:
    """Test edge cases for malformed template detection."""

    def test_double_dollar_brace(self):
        """Test detection of ${{ which is likely a mistake."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "echo ${{node.field}}"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Double ${{ means 2 ${, but only 1 valid template
        assert any("Malformed template syntax" in err for err in errors)

    def test_multiple_malformed_in_same_string(self):
        """Test detection of multiple malformed templates in same string."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "echo ${first ${second"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "Found 2 '${' but only 0 valid template(s)" in errors[0]
