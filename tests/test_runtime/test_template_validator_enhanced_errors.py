"""Tests for enhanced template error messages with input descriptions."""

from unittest.mock import Mock

from pflow.runtime.template_validator import TemplateValidator


def create_mock_registry():
    """Create a mock registry with test node metadata."""
    registry = Mock()

    # Define node metadata with interface information
    nodes_metadata = {
        "github-issue": {
            "interface": {
                "inputs": [
                    {"key": "repo", "type": "str", "description": "Repository name"},
                    {"key": "issue_number", "type": "str", "description": "Issue number"},
                ],
                "outputs": [
                    {
                        "key": "issue_data",
                        "type": "dict",
                        "description": "Issue data",
                        "structure": {
                            "title": {"type": "str", "description": "Issue title"},
                            "body": {"type": "str", "description": "Issue body"},
                        },
                    }
                ],
                "params": [],
                "actions": ["default", "error"],
            }
        },
        "llm": {
            "interface": {
                "inputs": [{"key": "prompt", "type": "str", "description": "LLM prompt"}],
                "outputs": [{"key": "summary", "type": "str", "description": "Generated summary"}],
                "params": [],
                "actions": ["default", "error"],
            }
        },
    }

    def get_nodes_metadata(node_types):
        """Mock implementation of get_nodes_metadata."""
        result = {}
        for node_type in node_types:
            if node_type in nodes_metadata:
                result[node_type] = nodes_metadata[node_type]
        return result

    registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata)
    return registry


class TestEnhancedTemplateErrors:
    """Test enhanced error messages for template validation."""

    def test_simple_declared_input_error(self):
        """Test error message for a simple declared input."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "issue_number": {
                    "description": "GitHub issue number to fix",
                    "required": True,
                }
            },
            "nodes": [
                {
                    "id": "fetch",
                    "type": "github-issue",
                    "params": {"repo": "pflow", "issue_number": "${issue_number}"},
                }
            ],
        }

        registry = create_mock_registry()
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert errors[0] == "Required input '${issue_number}' not provided - GitHub issue number to fix (required)"

    def test_optional_input_with_default_error(self):
        """Test error message for optional input with default."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "model": {
                    "description": "LLM model to use",
                    "required": False,
                    "default": "gpt-3.5-turbo",
                }
            },
            "nodes": [
                {
                    "id": "generate",
                    "type": "llm",
                    "params": {"prompt": "Generate using ${model}"},
                }
            ],
        }

        registry = create_mock_registry()
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert (
            errors[0] == "Required input '${model}' not provided - LLM model to use (optional, default: gpt-3.5-turbo)"
        )

    def test_path_access_on_declared_input_error(self):
        """Test error message when accessing path on declared input."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "config": {
                    "description": "API configuration object",
                    "required": True,
                }
            },
            "nodes": [
                {
                    "id": "use_config",
                    "type": "llm",
                    "params": {"prompt": "Using endpoint: ${config.endpoint}"},
                }
            ],
        }

        registry = create_mock_registry()
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "Required input '${config}' not provided - API configuration object (required)" in errors[0]
        assert "attempted to access path 'endpoint'" in errors[0]

    def test_undeclared_variable_keeps_original_error(self):
        """Test that undeclared variables keep original error message."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "declared_var": {
                    "description": "A declared variable",
                    "required": True,
                }
            },
            "nodes": [
                {
                    "id": "node1",
                    "type": "llm",
                    "params": {
                        "prompt": "Using ${declared_var} and ${undeclared_var}"
                    },  # Use both to avoid unused input error
                }
            ],
        }

        registry = create_mock_registry()
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        # Should have 2 errors: one for missing required input, one for undeclared variable
        assert len(errors) == 2

        # Find the error about the undeclared variable
        undeclared_error = next((e for e in errors if "undeclared_var" in e), None)
        assert undeclared_error is not None
        assert "Template variable ${undeclared_var} has no valid source" in undeclared_error
        assert "not provided in initial_params and not written by any node" in undeclared_error

    def test_workflow_without_inputs_field(self):
        """Test that workflows without inputs field work correctly."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "node1",
                    "type": "llm",
                    "params": {"prompt": "Using ${some_var}"},
                }
            ],
        }

        registry = create_mock_registry()
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "Template variable ${some_var} has no valid source" in errors[0]

    def test_multiple_missing_inputs_with_descriptions(self):
        """Test multiple missing inputs with descriptions."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "repo": {
                    "description": "GitHub repository name",
                    "required": True,
                },
                "issue_number": {
                    "description": "Issue number to process",
                    "required": True,
                },
            },
            "nodes": [
                {
                    "id": "fetch",
                    "type": "github-issue",
                    "params": {
                        "repo": "${repo}",
                        "issue_number": "${issue_number}",
                    },
                }
            ],
        }

        registry = create_mock_registry()
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 2
        # Check both errors are present (order not guaranteed)
        error_messages = set(errors)
        assert "Required input '${repo}' not provided - GitHub repository name (required)" in error_messages
        assert "Required input '${issue_number}' not provided - Issue number to process (required)" in error_messages

    def test_no_description_still_shows_required_status(self):
        """Test that inputs without descriptions still show required status."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "my_input": {
                    "required": True,
                    # No description
                }
            },
            "nodes": [
                {
                    "id": "node1",
                    "type": "llm",
                    "params": {"prompt": "Using ${my_input}"},
                }
            ],
        }

        registry = create_mock_registry()
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert errors[0] == "Required input '${my_input}' not provided - (required)"

    def test_provided_inputs_no_error(self):
        """Test that provided inputs don't generate errors."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "issue_number": {
                    "description": "GitHub issue number to fix",
                    "required": True,
                }
            },
            "nodes": [
                {
                    "id": "fetch",
                    "type": "github-issue",
                    "params": {"repo": "pflow", "issue_number": "${issue_number}"},
                }
            ],
        }

        registry = create_mock_registry()
        # Provide the required input
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, {"issue_number": "123"}, registry)

        assert len(errors) == 0
