"""Tests for enhanced template error messages with input descriptions."""

from unittest.mock import Mock

from pflow.core.diagnostic import Severity
from pflow.runtime.template_validation import validate_workflow_templates
from tests.shared.diagnostic_helpers import split_template_diagnostics


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
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert (
            errors[0].message
            == "Required input '${issue_number}' not provided - GitHub issue number to fix (required)."
        )

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
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert (
            errors[0].message
            == "Required input '${model}' not provided - LLM model to use (optional, default: gpt-3.5-turbo)."
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
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "Required input '${config}' not provided - API configuration object (required)" in errors[0].message
        assert "attempted to access path 'endpoint'" in errors[0].message

        # Structural assertion (task 147): the path_validation producer for
        # the declared-input-with-path-access case must preserve the offending
        # template in context["template"] and the error category. Without this,
        # the producer could regress to bare-message form and the substring
        # assertions above would still pass — a downstream JSON consumer would
        # lose the ability to programmatically identify which template failed.
        diagnostics = validate_workflow_templates(workflow_ir, {}, registry)
        err_diag = next(d for d in diagnostics if d.severity.value == "error")
        assert err_diag.context.get("template") == "${config.endpoint}"
        assert err_diag.context.get("category") == "template_error"

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
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        # Should have 2 errors: one for missing required input, one for undeclared variable
        assert len(errors) == 2

        # Find the error about the undeclared variable
        undeclared_error = next((d for d in errors if "undeclared_var" in d.message), None)
        assert undeclared_error is not None
        assert "Template variable ${undeclared_var} has no valid source" in undeclared_error.message
        assert "not provided in initial_params and not written by any node" in undeclared_error.message

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
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "Template variable ${some_var} has no valid source" in errors[0].message

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
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert len(errors) == 2
        # Check both errors are present (order not guaranteed)
        error_messages = {d.message for d in errors}
        assert any(
            message == "Required input '${repo}' not provided - GitHub repository name (required)."
            for message in error_messages
        )
        assert any(
            message == "Required input '${issue_number}' not provided - Issue number to process (required)."
            for message in error_messages
        )

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
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert errors[0].message == "Required input '${my_input}' not provided - (required)."

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
        errors, _warnings = split_template_diagnostics(workflow_ir, {"issue_number": "123"}, registry)

        assert len(errors) == 0

    def test_unknown_node_type_downstream_ref_no_stderr_warning(self, caplog):
        """PR #244 Round 9 regression guard.

        When a workflow has an unknown node type AND a downstream template
        reference to that node's output, the defensive fallback in
        ``_get_node_outputs_from_registry`` is reached (because Fix [1] silently
        skips unknown types in ``_register_node_outputs_from_registry``). The
        old fallback logged ``WARNING: node_outputs fallback reached for node
        'X' — this is unexpected``, which leaked to user-visible stderr. This
        test locks in that:
          (a) the fallback still produces a Template Error diagnostic (behavior),
          (b) it no longer emits a WARNING-level log record (UX),
          (c) it emits a DEBUG-level record instead (observability preserved).
        """
        caplog.set_level("DEBUG", logger="pflow.runtime.template_validation.path_validation")

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "unknown-source", "type": "shel", "params": {"command": "echo hi"}},
                {
                    "id": "downstream",
                    "type": "llm",
                    "params": {"prompt": "saw: ${unknown-source.stdout}"},
                },
            ],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        # (a) template error still produced for the downstream ref
        fallback_errors = [d for d in errors if "unknown-source" in d.message and "does not output" in d.message]
        assert len(fallback_errors) == 1

        # (b) no WARNING-level log record from the fallback path
        warning_records = [r for r in caplog.records if r.levelname == "WARNING" and "fallback reached" in r.message]
        assert not warning_records, f"Expected no WARNING from fallback, got: {warning_records}"

        # (c) DEBUG-level log still fires for observability
        debug_records = [r for r in caplog.records if r.levelname == "DEBUG" and "fallback reached" in r.message]
        assert debug_records, "Expected DEBUG log from fallback for observability"


def test_undeclared_variable_preserves_template_context() -> None:
    """Simple template errors should keep template and suggestion structure."""
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "node1",
                "type": "llm",
                "params": {"prompt": "Using ${undeclared_var}"},
            }
        ],
    }

    registry = create_mock_registry()
    diagnostics = validate_workflow_templates(workflow_ir, {}, registry)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]

    assert len(errors) == 1
    diagnostic = errors[0]
    assert diagnostic.title == "Template Error"
    assert diagnostic.context is not None
    assert diagnostic.context.get("template") == "${undeclared_var}"
    assert diagnostic.suggestions
