"""Tests for template variable validation."""

from pathlib import Path
from unittest.mock import Mock

from pflow.core.diagnostic import Severity
from pflow.runtime.template_validation import validate_workflow_templates
from pflow.runtime.template_validation.validator import _extract_all_templates
from tests.shared.diagnostic_helpers import split_template_diagnostics


def create_mock_registry():
    """Create a mock registry with test node metadata."""
    registry = Mock()

    # Define node metadata with interface information
    nodes_metadata = {
        "youtube-transcript": {
            "interface": {
                "inputs": [{"key": "url", "type": "str", "description": "YouTube URL"}],
                "outputs": [
                    {
                        "key": "transcript_data",
                        "type": "dict",
                        "description": "Transcript data",
                        "structure": {
                            "title": {"type": "str", "description": "Video title"},
                            "text": {"type": "str", "description": "Transcript text"},
                        },
                    }
                ],
                "params": [],
                "actions": ["default", "error"],
            }
        },
        "write-file": {
            "interface": {
                "inputs": [
                    {"key": "file_path", "type": "str", "description": "Path to file"},
                    {"key": "content", "type": "str", "description": "File content"},
                ],
                "outputs": [],
                "params": [],
                "actions": ["default", "error"],
            }
        },
        "llm": {
            "interface": {
                "inputs": [{"key": "prompt", "type": "str", "description": "LLM prompt"}],
                "outputs": [
                    {"key": "response", "type": "any", "description": "Model's response"},
                    {
                        "key": "llm_usage",
                        "type": "dict",
                        "description": "Token usage metrics",
                        "structure": {
                            "model": {"type": "str", "description": "Model identifier"},
                            "input_tokens": {"type": "int", "description": "Input tokens"},
                            "output_tokens": {"type": "int", "description": "Output tokens"},
                        },
                    },
                ],
                "params": [],
                "actions": ["default", "error"],
            }
        },
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
    }

    nodes_metadata["shell"] = {
        "interface": {
            "inputs": [{"key": "command", "type": "str", "description": "Shell command"}],
            "outputs": [
                {"key": "stdout", "type": "str", "description": "Standard output"},
                {"key": "stderr", "type": "str", "description": "Standard error"},
                {"key": "returncode", "type": "int", "description": "Exit code"},
            ],
            "params": [],
            "actions": ["default", "error"],
        }
    }
    nodes_metadata["code"] = {
        "interface": {
            "inputs": [],
            "outputs": [
                {"key": "result", "type": "any", "description": "Code result"},
            ],
            "params": [],
            "actions": ["default", "error"],
        }
    }

    # Add some generic test nodes
    for i in range(1, 4):
        node_type = f"t{i}"
        nodes_metadata[node_type] = {"interface": {"inputs": [], "outputs": [], "params": [], "actions": ["default"]}}

    def get_nodes_metadata(node_types):
        """Mock implementation of get_nodes_metadata."""
        result = {}
        for node_type in node_types:
            if node_type in nodes_metadata:
                result[node_type] = nodes_metadata[node_type]
        return result

    registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata)
    return registry


class TestTemplateExtraction:
    """Test extraction of templates from workflow IR."""

    def test_extracts_templates_from_single_node(self):
        """Test extraction from a single node with templates."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "fetch",
                    "type": "youtube-transcript",
                    "params": {
                        "url": "${url}",
                        "format": "text",  # Static param
                    },
                }
            ],
            "edges": [],
        }

        templates = _extract_all_templates(workflow_ir)
        assert templates == {"url"}

    def test_extracts_templates_from_multiple_nodes(self):
        """Test extraction from multiple nodes."""
        workflow_ir = {
            "nodes": [
                {"id": "n1", "type": "t1", "params": {"a": "${var1}"}},
                {"id": "n2", "type": "t2", "params": {"b": "${var2}", "c": "${var3}"}},
                {"id": "n3", "type": "t3", "params": {"d": "static"}},
            ],
            "edges": [],
        }

        templates = _extract_all_templates(workflow_ir)
        assert templates == {"var1", "var2", "var3"}

    def test_extracts_path_templates(self):
        """Test extraction of templates with paths."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "summarize",
                    "type": "llm",
                    "params": {"prompt": "Title: ${data.title} by ${data.metadata.author}"},
                }
            ],
            "edges": [],
        }

        templates = _extract_all_templates(workflow_ir)
        assert templates == {"data.title", "data.metadata.author"}

    def test_handles_nodes_without_params(self):
        """Test handling nodes that don't have params."""
        workflow_ir = {
            "nodes": [
                {"id": "n1", "type": "t1"},  # No params
                {"id": "n2", "type": "t2", "params": {}},  # Empty params
            ],
            "edges": [],
        }

        templates = _extract_all_templates(workflow_ir)
        assert templates == set()

    def test_deduplicates_templates(self):
        """Test that duplicate templates are deduplicated."""
        workflow_ir = {
            "nodes": [
                {"id": "n1", "type": "t1", "params": {"a": "${url}", "b": "${url}"}},
                {"id": "n2", "type": "t2", "params": {"c": "${url}"}},
            ],
            "edges": [],
        }

        templates = _extract_all_templates(workflow_ir)
        assert templates == {"url"}


class TestWorkflowValidation:
    """Test complete workflow validation."""

    def test_valid_workflow_no_errors(self):
        """Test validation passes when all params provided."""
        workflow_ir = {
            "nodes": [
                {"id": "fetch", "type": "youtube-transcript", "params": {"url": "${url}"}},
                {"id": "summarize", "type": "llm", "params": {"prompt": "Summarize: ${transcript_data.text}"}},
                {
                    "id": "save",
                    "type": "write-file",
                    "params": {
                        "file_path": "summary.txt",
                        "content": "${response}",  # From llm node
                    },
                },
            ],
            "edges": [],
        }

        # All CLI params provided
        params = {"url": "https://youtube.com/watch?v=xyz"}
        registry = create_mock_registry()

        errors, _warnings = split_template_diagnostics(workflow_ir, params, registry)
        assert len(errors) == 0

    def test_missing_cli_parameter(self):
        """Test validation catches missing CLI parameters."""
        workflow_ir = {
            "nodes": [
                {"id": "fetch", "type": "youtube-transcript", "params": {"url": "${url}"}},
                {"id": "analyze", "type": "llm", "params": {"prompt": "Analyze ${url}"}},
            ],
            "edges": [],
        }

        # Missing 'url' parameter
        params = {}

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, params, registry)
        assert len(errors) == 1
        assert "Template variable ${url} has no valid source" in errors[0].message

    def test_multiple_missing_parameters(self):
        """Test validation reports multiple missing params."""
        workflow_ir = {
            "nodes": [
                {"id": "n1", "type": "t1", "params": {"a": "${param1}", "b": "${param2}"}},
                {"id": "n2", "type": "t2", "params": {"c": "${param3}"}},
            ],
            "edges": [],
        }

        # No parameters provided
        params = {}

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, params, registry)
        assert len(errors) == 3
        assert any("${param1}" in d.message for d in errors)
        assert any("${param2}" in d.message for d in errors)
        assert any("${param3}" in d.message for d in errors)

    def test_distinguishes_cli_from_shared_store(self):
        """Test validation correctly identifies CLI params vs shared store."""
        workflow_ir = {
            "nodes": [
                {"id": "fetch", "type": "youtube-transcript", "params": {"url": "${url}"}},
                {
                    "id": "analyze",
                    "type": "llm",
                    "params": {
                        "prompt": "Summarize: ${transcript_data.title}"  # From shared store
                    },
                },
            ],
            "edges": [],
        }

        # Only CLI param provided
        params = {"url": "https://youtube.com/watch?v=xyz"}

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, params, registry)
        assert len(errors) == 0  # No errors - transcript_data is from shared store

    def test_invalid_syntax_in_shared_vars(self):
        """Test validation catches invalid syntax in shared store variables."""
        workflow_ir = {
            "nodes": [
                {"id": "n1", "type": "t1", "params": {"a": "${data..field}"}}  # Invalid syntax
            ],
            "edges": [],
        }

        params = {}
        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, params, registry)
        assert len(errors) == 1
        assert "Template variable ${data..field} has no valid source" in errors[0].message

    def test_partial_parameter_match(self):
        """Test base variable matching for CLI params."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "n1",
                    "type": "t1",
                    "params": {
                        "a": "${config.setting}",  # Base var 'config' needs to be provided
                        "b": "${config.other}",
                    },
                }
            ],
            "edges": [],
        }

        # Provide base parameter
        params = {"config": {"setting": "value1", "other": "value2"}}

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, params, registry)
        assert len(errors) == 0  # config is provided

    def test_no_templates_in_workflow(self):
        """Test validation of workflow with no templates."""
        workflow_ir = {
            "nodes": [
                {"id": "n1", "type": "t1", "params": {"static": "value"}},
                {"id": "n2", "type": "t2", "params": {"another": 123}},
            ],
            "edges": [],
        }

        params = {}
        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, params, registry)
        assert len(errors) == 0  # No templates, no errors


class TestRealWorldScenarios:
    """Test validation with real-world workflow examples."""

    def test_youtube_workflow_validation(self):
        """Test validation of youtube summarization workflow."""
        workflow_ir = {
            "nodes": [
                {"id": "fetch", "type": "youtube-transcript", "params": {"url": "${url}"}},
                {
                    "id": "summarize",
                    "type": "llm",
                    "params": {"prompt": "Summarize: ${transcript_data.title}\n\n${transcript_data.text}"},
                },
                {
                    "id": "save",
                    "type": "write-file",
                    "params": {"file_path": "summary.md", "content": "# ${transcript_data.title}\n\n${response}"},
                },
            ],
            "edges": [{"from": "fetch", "to": "summarize"}, {"from": "summarize", "to": "save"}],
        }

        # Test with missing URL
        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
        assert len(errors) == 1
        assert "Template variable ${url} has no valid source" in errors[0].message

        # Test with URL provided
        errors, _warnings = split_template_diagnostics(workflow_ir, {"url": "https://youtube.com"}, registry)
        assert len(errors) == 0  # transcript_data and summary are from shared store

    def test_github_issue_workflow(self):
        """Test validation of github issue workflow."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "fetch_issue",
                    "type": "github-issue",
                    "params": {"repo": "${repo}", "issue_number": "${issue_number}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "params": {"prompt": "Analyze issue: ${issue_data.title}\n\n${issue_data.body}"},
                },
            ],
            "edges": [{"from": "fetch_issue", "to": "analyze"}],
        }

        # Test with no params
        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
        assert len(errors) == 2
        assert any("${repo}" in d.message for d in errors)
        assert any("${issue_number}" in d.message for d in errors)

        # Test with partial params
        errors, _warnings = split_template_diagnostics(workflow_ir, {"repo": "pflow"}, registry)
        assert len(errors) == 1
        assert "${issue_number}" in errors[0].message

        # Test with all params
        params = {"repo": "pflow", "issue_number": "123"}
        errors, _warnings = split_template_diagnostics(workflow_ir, params, registry)
        assert len(errors) == 0


class TestBatchTemplateValidation:
    """Tests for batch processing template validation."""

    def test_batch_item_alias_default_recognized(self):
        """${item} should be valid when node has batch config."""
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${items}", "parallel": True},
                    "params": {"prompt": "Process: ${item}"},
                }
            ],
            "edges": [],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a", "b", "c"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_batch_item_alias_custom_recognized(self):
        """Custom alias via batch.as should be valid."""
        workflow_ir = {
            "inputs": {"records": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${records}", "as": "record"},
                    "params": {"prompt": "Process record: ${record}"},
                }
            ],
            "edges": [],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"records": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_batch_outputs_recognized(self):
        """${node.results}, ${node.count}, etc. should be valid for batch nodes."""
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "combine",
                    "type": "llm",
                    "params": {"prompt": "Combine ${process.count} results: ${process.results}"},
                },
            ],
            "edges": [{"from": "process", "to": "combine"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_all_batch_outputs_available(self):
        """All batch outputs should be available: results, count, success_count, error_count, errors, batch_metadata."""
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "batch-node",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "${item}"},
                },
                {
                    "id": "report",
                    "type": "llm",
                    "params": {
                        "prompt": (
                            "Results: ${batch-node.results}\n"
                            "Count: ${batch-node.count}\n"
                            "Success: ${batch-node.success_count}\n"
                            "Errors: ${batch-node.error_count}\n"
                            "Error details: ${batch-node.errors}\n"
                            "Metadata: ${batch-node.batch_metadata}"
                        )
                    },
                },
            ],
            "edges": [{"from": "batch-node", "to": "report"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": []}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_batch_items_template_validated(self):
        """Templates in batch.items should be extracted and validated."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "${item}"},
                }
            ],
            "edges": [],
        }

        registry = create_mock_registry()

        # With data provided - should pass (data is used in batch.items)
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_batch_items_invalid_template_fails(self):
        """Invalid template in batch.items should fail validation."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${nonexistent_array}"},
                    "params": {"prompt": "${item}"},
                }
            ],
            "edges": [],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
        assert len(errors) > 0
        assert any("nonexistent_array" in d.message for d in errors)

    def test_batch_does_not_expose_inner_outputs(self):
        """${node.response} should NOT be valid for batch node (it's wrapped in results)."""
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "${item}"},
                },
                {
                    "id": "use-wrong-output",
                    "type": "llm",
                    # Trying to use inner node output directly (wrong!)
                    "params": {"prompt": "Response: ${process.response}"},
                },
            ],
            "edges": [{"from": "process", "to": "use-wrong-output"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a"]}, registry)

        # Should fail with batch-specific error message
        assert len(errors) == 1, f"Expected exactly 1 error, got {len(errors)}: {errors}"
        error = errors[0].message

        # Error should mention batch processing
        assert "batch processing" in error.lower(), f"Error should mention batch processing: {error}"

        diagnostic = errors[0]
        assert diagnostic.suggestions
        assert any("process.results[0].response" in suggestion for suggestion in diagnostic.suggestions)

        # Error should show actual batch outputs (now in structured context)
        available = (diagnostic.context or {}).get("available_fields", [])
        assert any("process.results" in field for field in available), (
            f"Error should show batch outputs in available_fields: {diagnostic}"
        )

        # Error should NOT show the invalid path with a checkmark (no contradiction)
        assert "✓ ${process.response}" not in error, f"Error should not show invalid path with checkmark: {error}"

    def test_batch_error_shows_correct_path_for_llm_usage(self):
        """Accessing ${batch-node.llm_usage} should show corrected path with batch processing message."""
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "generate",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "${item}"},
                },
                {
                    "id": "cost-calc",
                    "type": "llm",
                    "params": {"prompt": "Usage: ${generate.llm_usage}"},
                },
            ],
            "edges": [{"from": "generate", "to": "cost-calc"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a", "b"]}, registry)

        # Should have exactly one error
        assert len(errors) == 1, f"Expected exactly 1 error, got {len(errors)}: {errors}"
        error = errors[0].message

        # Error should mention batch processing
        assert "batch processing" in error.lower(), f"Error should mention batch processing: {error}"

        diagnostic = errors[0]
        assert diagnostic.suggestions
        assert any("generate.results[0].llm_usage" in suggestion for suggestion in diagnostic.suggestions)

        # Error should show the top-level batch reference (now in structured context)
        available = (diagnostic.context or {}).get("available_fields", [])
        assert any("generate.results" in field for field in available), (
            f"Error should show top-level batch reference in available_fields: {diagnostic}"
        )

        # Error should NOT show the invalid path with a checkmark (no contradiction)
        assert "✓ ${generate.llm_usage}" not in error, f"Error should not show invalid path with checkmark: {error}"

    def test_batch_error_for_nonexistent_field(self):
        """Accessing ${batch-node.foobar} where foobar doesn't exist in inner LLM interface."""
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "${item}"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "Data: ${process.foobar}"},
                },
            ],
            "edges": [{"from": "process", "to": "consumer"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a", "b"]}, registry)

        # Should have exactly one error
        assert len(errors) == 1, f"Expected exactly 1 error, got {len(errors)}: {errors}"
        error = errors[0]

        # Error should say field does not exist
        assert "does not output 'foobar'" in error.message, f"Error should mention field not found: {error}"

        # Error should indicate this is a batch node
        assert "batch" in error.message.lower(), f"Error should indicate batch node: {error}"

        # Error should show actual batch outputs (now in structured context)
        available = (error.context or {}).get("available_fields", [])
        assert any("process.results" in field for field in available), (
            f"Error should show actual batch outputs in available_fields: {error}"
        )

        # Error should NOT suggest results[0].foobar (since foobar isn't a real inner output)
        suggestions = error.suggestions or []
        assert not any("results[0].foobar" in s for s in suggestions), (
            f"Error should not suggest invalid nested path: {error}"
        )

    def test_batch_error_for_nested_inner_path(self):
        """${batch-node.llm_usage.input_tokens} should still identify llm_usage as inner field."""
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "generate",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "${item}"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "Tokens: ${generate.llm_usage.input_tokens}"},
                },
            ],
            "edges": [{"from": "generate", "to": "consumer"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a"]}, registry)

        assert len(errors) == 1, f"Expected exactly 1 error, got {len(errors)}: {errors}"
        error = errors[0].message

        # Should still detect batch and identify llm_usage as the inner field
        assert "batch processing" in error.lower(), f"Error should mention batch processing: {error}"
        diagnostic = errors[0]
        assert diagnostic.suggestions
        assert any("${generate.results[0].llm_usage}" in suggestion for suggestion in diagnostic.suggestions)

    def test_non_batch_error_message_uses_node_outputs(self):
        """Regression test: non-batch error messages should still work correctly."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "analyze",
                    "type": "llm",
                    "params": {"prompt": "Analyze: ${input_text}"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "Data: ${analyze.foobar}"},
                },
            ],
            "edges": [{"from": "analyze", "to": "consumer"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        # Should have errors (missing input_text and invalid foobar)
        assert len(errors) >= 1, f"Expected at least 1 error, got {len(errors)}: {errors}"

        # Find the error about foobar
        foobar_errors = [d for d in errors if "foobar" in d.message]
        assert len(foobar_errors) == 1, f"Expected exactly 1 foobar error, got {len(foobar_errors)}: {foobar_errors}"
        error = foobar_errors[0]

        # Error should say field does not exist
        assert "does not output 'foobar'" in error.message, f"Error should mention field not found: {error}"

        # Error should show actual LLM outputs (now in structured context)
        available = (error.context or {}).get("available_fields", [])
        assert any("${analyze.response}" in field for field in available), (
            f"Error should show actual outputs in available_fields: {error}"
        )
        assert error.context is not None
        assert error.context.get("available_fields")
        assert error.context.get("available_fields_label") == "outputs"

        # Error should NOT mention batch
        assert "batch" not in error.message.lower(), f"Error should not mention batch for non-batch node: {error}"

    def test_non_batch_node_unchanged(self):
        """Non-batch nodes should work exactly as before."""
        workflow_ir = {
            "nodes": [
                {"id": "fetch", "type": "youtube-transcript", "params": {"url": "${url}"}},
                {
                    "id": "summarize",
                    "type": "llm",
                    "params": {"prompt": "Summarize: ${transcript_data.text}"},
                },
            ],
            "edges": [{"from": "fetch", "to": "summarize"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"url": "https://youtube.com"}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_mixed_batch_and_non_batch_nodes(self):
        """Workflow with both batch and non-batch nodes should validate correctly."""
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                # Non-batch node first
                {"id": "fetch", "type": "youtube-transcript", "params": {"url": "${url}"}},
                # Batch node
                {
                    "id": "process-each",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "Process ${item} with context: ${transcript_data.title}"},
                },
                # Non-batch node using batch output
                {
                    "id": "combine",
                    "type": "llm",
                    "params": {"prompt": "Combined ${process-each.count} results: ${process-each.results}"},
                },
            ],
            "edges": [
                {"from": "fetch", "to": "process-each"},
                {"from": "process-each", "to": "combine"},
            ],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(
            workflow_ir, {"url": "https://youtube.com", "items": ["a", "b"]}, registry
        )
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_batch_results_nested_access_validated(self):
        """Nested access to batch results like ${node.results[0].response} should validate."""
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process-batch",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "use-first-result",
                    "type": "llm",
                    "params": {
                        # Access nested field in batch results - THIS is the key test
                        "prompt": "First response was: ${process-batch.results[0].response}"
                    },
                },
            ],
            "edges": [{"from": "process-batch", "to": "use-first-result"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a", "b"]}, registry)
        # Should NOT produce an error - results[0].response is valid
        assert len(errors) == 0, f"Unexpected errors for nested batch access: {errors}"

    def test_batch_results_item_field_validated(self):
        """Access to ${node.results[0].item} should validate (original batch input)."""
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process-batch",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "correlate-results",
                    "type": "llm",
                    "params": {
                        # Access item field in batch results - correlate input with output
                        "prompt": "Input was: ${process-batch.results[0].item}, Output was: ${process-batch.results[0].response}"
                    },
                },
            ],
            "edges": [{"from": "process-batch", "to": "correlate-results"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a", "b"]}, registry)
        # Should NOT produce an error - results[0].item is valid (original batch input)
        assert len(errors) == 0, f"Unexpected errors for batch item field access: {errors}"

    def test_batch_results_nested_llm_usage_validated(self):
        """Deeply nested access like ${node.results[0].llm_usage.input_tokens} should validate."""
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process-batch",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "report-usage",
                    "type": "llm",
                    "params": {
                        # Access deeply nested field - results[0].llm_usage.input_tokens
                        "prompt": "Tokens used: ${process-batch.results[0].llm_usage.input_tokens}"
                    },
                },
            ],
            "edges": [{"from": "process-batch", "to": "report-usage"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a", "b"]}, registry)
        # Should NOT produce an error - deeply nested path is valid
        assert len(errors) == 0, f"Unexpected errors for deeply nested batch access: {errors}"

    def test_batch_results_invalid_nested_path_rejected(self):
        """Invalid nested path like ${node.results[0].nonexistent} should fail validation."""
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process-batch",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "use-result",
                    "type": "llm",
                    "params": {
                        # 'typo_field' does not exist in llm outputs (response, llm_usage)
                        "prompt": "Result: ${process-batch.results[0].typo_field}"
                    },
                },
            ],
            "edges": [{"from": "process-batch", "to": "use-result"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a", "b"]}, registry)
        # Should produce an error - typo_field is not a valid output
        assert len(errors) == 1, f"Expected 1 error for invalid path, got: {errors}"
        assert "typo_field" in errors[0].message or "results[0]" in errors[0].message

        # Structural assertion (task 147): the highest-value producer rewrite
        # (_build_enhanced_node_diagnostic) must preserve available_fields (the
        # node's actual outputs with types). Without this, the producer could
        # regress to bare-message form and the substring assertion above would
        # still pass.
        diagnostics = validate_workflow_templates(workflow_ir, {"items": ["a", "b"]}, registry)
        diag = next(d for d in diagnostics if d.severity.value == "error")
        assert diag.context.get("available_fields_label") == "outputs"
        available = diag.context["available_fields"]
        assert available, "available_fields must list the node's outputs"
        # Verify the known real outputs of the llm batch node are present as
        # structured entries — these are what a future regression to bare-string
        # form would drop.
        assert any("response" in entry for entry in available)
        assert any("llm_usage" in entry for entry in available)

    def test_nested_index_template_not_flagged_as_malformed(self):
        """${results[${__index__}]} should not be flagged as malformed syntax."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "first-batch",
                    "type": "shell",
                    "batch": {"items": "${items}"},
                    "params": {"command": "echo ${item}"},
                },
                {
                    "id": "second-batch",
                    "type": "shell",
                    "batch": {"items": "${items}"},
                    "params": {
                        # Nested index template - should not be flagged as malformed
                        "command": "echo ${first-batch.results[${__index__}].stdout}"
                    },
                },
            ],
            "edges": [{"from": "first-batch", "to": "second-batch"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a", "b", "c"]}, registry)
        # Should NOT produce any "malformed template" errors
        malformed_errors = [d for d in errors if "Malformed template" in d.message]
        assert len(malformed_errors) == 0, f"Unexpected malformed template errors: {malformed_errors}"

    def test_nested_item_field_in_array_index_validated(self):
        """REGRESSION: ${results[${item.draft_index}]} should validate correctly.

        Bug: Validator used template.split(".") which broke ${item.draft_index}
        into ['item', 'draft_index}]', causing validation error:
        "Node 'drafts' does not output 'results[${item'"

        Fix: Use _split_template_path() which preserves dots inside ${...}.
        """
        workflow_ir = {
            "nodes": [
                {
                    "id": "drafts",
                    "type": "llm",
                    "batch": {
                        "items": [
                            {"platform": "slack"},
                            {"platform": "discord"},
                            {"platform": "x"},
                        ],
                        "parallel": True,
                    },
                    "params": {"prompt": "Write draft for ${item.platform}"},
                },
                {
                    "id": "critiques",
                    "type": "llm",
                    "batch": {
                        "items": [
                            {"platform": "slack", "draft_index": 0},
                            {"platform": "discord", "draft_index": 1},
                            {"platform": "x", "draft_index": 2},
                        ],
                        "parallel": True,
                    },
                    "params": {
                        # THE BUG: This template failed validation because the dot in
                        # ${item.draft_index} was treated as a path separator
                        "prompt": "Critique ${item.platform}: ${drafts.results[${item.draft_index}].response}"
                    },
                },
            ],
            "edges": [{"from": "drafts", "to": "critiques"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        # CRITICAL: Should NOT fail with "does not output 'results[${item'"
        bad_errors = [d for d in errors if "results[${item" in d.message]
        assert len(bad_errors) == 0, f"Regression: nested item.field incorrectly parsed: {bad_errors}"


class TestBatchWorkflowNodeValidation:
    """Tests for batch processing on workflow nodes (bug: validator blocked batch+workflow)."""

    @staticmethod
    def _write_child_with_outputs(tmp_path: Path, name: str, output_keys: list[str]) -> Path:
        """Write a child workflow file declaring the given output keys.

        Used by tests asserting ``${node.results[N].<key>}`` validates. Outputs
        are declared with simple ``source:`` refs — semantics don't matter;
        only the names need to match the assertions so the template validator's
        ``_resolve_child_workflow_outputs`` can see them.
        """
        path = tmp_path / f"{name}.pflow.md"
        outputs_md = "\n".join(f"### {key}\n\nOutput {key}.\n\n- source: ${{step.stdout}}\n" for key in output_keys)
        path.write_text(
            f"# Child {name}\n\nChild workflow for template validation tests.\n\n"
            f"## Inputs\n\n### text\n\nInput text.\n\n- type: string\n- required: true\n\n"
            f"## Steps\n\n### step\n\nEcho input.\n\n"
            f"- type: shell\n\n```shell command\necho ${{text}}\n```\n\n"
            f"## Outputs\n\n{outputs_md}\n",
            encoding="utf-8",
        )
        return path

    def test_workflow_batch_outputs_recognized(self, tmp_path: Path):
        """${node.results}, ${node.count}, etc. should be valid for batched workflow nodes."""
        child_path = self._write_child_with_outputs(tmp_path, "child", ["content"])
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process-all",
                    "type": "workflow",
                    "batch": {"items": "${items}", "parallel": True},
                    "params": {"workflow": str(child_path), "inputs": {"text": "${item}"}},
                },
                {
                    "id": "summarize",
                    "type": "llm",
                    "params": {"prompt": "Results: ${process-all.results}, Count: ${process-all.count}"},
                },
            ],
            "edges": [{"from": "process-all", "to": "summarize"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_workflow_batch_all_outputs_available(self, tmp_path: Path):
        """All batch outputs should be available on batched workflow nodes."""
        child_path = self._write_child_with_outputs(tmp_path, "child", ["summary"])
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "batch-wf",
                    "type": "workflow",
                    "batch": {"items": "${items}"},
                    "params": {"workflow": str(child_path), "inputs": {"text": "${item}"}},
                },
                {
                    "id": "report",
                    "type": "llm",
                    "params": {
                        "prompt": (
                            "Results: ${batch-wf.results} "
                            "Count: ${batch-wf.count} "
                            "Success: ${batch-wf.success_count} "
                            "Errors: ${batch-wf.error_count} "
                            "Error details: ${batch-wf.errors} "
                            "Metadata: ${batch-wf.batch_metadata}"
                        )
                    },
                },
            ],
            "edges": [{"from": "batch-wf", "to": "report"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": []}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_workflow_batch_inner_outputs_in_results(self, tmp_path: Path):
        """Child workflow outputs should be accessible inside results array items.

        Regression guard (post-task-153): the mutation check ``${process-all.results[0].BOGUS}``
        MUST fail here. Before the file-backed migration this test passed trivially because
        ``_resolve_child_workflow_outputs`` returned None for ``workflow_ir``-only nodes.
        """
        child_path = self._write_child_with_outputs(tmp_path, "child", ["content"])
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process-all",
                    "type": "workflow",
                    "batch": {"items": "${items}"},
                    "params": {"workflow": str(child_path), "inputs": {"text": "${item}"}},
                },
                {
                    "id": "use-results",
                    "type": "llm",
                    "params": {
                        "prompt": "First: ${process-all.results[0].content}, Item: ${process-all.results[0].item}"
                    },
                },
            ],
            "edges": [{"from": "process-all", "to": "use-results"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_workflow_batch_blocks_direct_child_outputs(self, tmp_path: Path):
        """Direct child output access should fail when batch is configured."""
        child_path = self._write_child_with_outputs(tmp_path, "child", ["content"])
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process-all",
                    "type": "workflow",
                    "batch": {"items": "${items}"},
                    "params": {"workflow": str(child_path), "inputs": {"text": "${item}"}},
                },
                {
                    "id": "wrong",
                    "type": "llm",
                    "params": {"prompt": "Got: ${process-all.content}"},
                },
            ],
            "edges": [{"from": "process-all", "to": "wrong"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a"]}, registry)
        # Should fail because 'content' is inside results, not at top level
        assert len(errors) > 0, "Should reject direct child output access on batched workflow"
        assert any("content" in d.message for d in errors), f"Error should mention 'content': {errors}"

    def test_workflow_batch_item_alias_recognized(self, tmp_path: Path):
        """${item} should be valid inside batched workflow node params."""
        child_path = self._write_child_with_outputs(tmp_path, "child", ["content"])
        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process-all",
                    "type": "workflow",
                    "batch": {"items": "${items}", "as": "thing"},
                    "params": {"workflow": str(child_path), "inputs": {"text": "${thing}"}},
                },
            ],
            "edges": [],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"items": ["a"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_workflow_batch_unresolvable_child_dynamic(self):
        """Batched workflow with unresolvable child should still register batch outputs."""
        workflow_ir = {
            "inputs": {
                "items": {"type": "array", "required": True},
                "wf_path": {"type": "string", "required": True},
            },
            "nodes": [
                {
                    "id": "dynamic-wf",
                    "type": "workflow",
                    "batch": {"items": "${items}"},
                    "params": {"workflow": "${wf_path}", "text": "${item}"},
                },
                {
                    "id": "use-it",
                    "type": "llm",
                    "params": {"prompt": "Results: ${dynamic-wf.results}, Count: ${dynamic-wf.count}"},
                },
            ],
            "edges": [{"from": "dynamic-wf", "to": "use-it"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(
            workflow_ir, {"items": ["a"], "wf_path": "./child.pflow.md"}, registry
        )
        # Should pass — batch outputs are known even if child outputs aren't
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_workflow_batch_unresolvable_child_deep_access(self):
        """Deep results access should work on batched workflow with unresolvable child."""
        workflow_ir = {
            "inputs": {
                "items": {"type": "array", "required": True},
                "wf_path": {"type": "string", "required": True},
            },
            "nodes": [
                {
                    "id": "dynamic-wf",
                    "type": "workflow",
                    "batch": {"items": "${items}"},
                    "params": {"workflow": "${wf_path}", "text": "${item}"},
                },
                {
                    "id": "use-deep",
                    "type": "llm",
                    "params": {"prompt": "Got: ${dynamic-wf.results[0].content}"},
                },
            ],
            "edges": [{"from": "dynamic-wf", "to": "use-deep"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(
            workflow_ir, {"items": ["a"], "wf_path": "./child.pflow.md"}, registry
        )
        # Should pass — unknown inner outputs should be permissive, not strict
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_workflow_without_batch_still_works(self, tmp_path: Path):
        """Non-batched workflow nodes should still resolve child outputs normally.

        Regression guard (post-task-153): this exercises the non-batch path of
        ``_resolve_child_workflow_outputs``. Before the file-backed migration the
        child's outputs were not resolvable (no ``workflow:`` ref), so ``${single.BOGUS}``
        would pass. File fixture restores proper coverage.
        """
        child_path = self._write_child_with_outputs(tmp_path, "child", ["content"])
        workflow_ir = {
            "inputs": {"text": {"type": "string", "required": True}},
            "nodes": [
                {
                    "id": "single",
                    "type": "workflow",
                    "params": {"workflow": str(child_path), "inputs": {"text": "${text}"}},
                },
                {
                    "id": "use-it",
                    "type": "llm",
                    "params": {"prompt": "Got: ${single.content}"},
                },
            ],
            "edges": [{"from": "single", "to": "use-it"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"text": "hello"}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_unused_inputs_diagnostic_preserves_list(self):
        """Unused-input diagnostics should keep their sorted input list in context."""
        workflow_ir = {
            "inputs": {
                "used_one": {"type": "string"},
                "unused_one": {"type": "string"},
                "unused_two": {"type": "string"},
            },
            "nodes": [
                {
                    "id": "n1",
                    "type": "llm",
                    "params": {"prompt": "echo ${used_one}"},
                }
            ],
            "edges": [],
        }

        diagnostics = validate_workflow_templates(workflow_ir, {"used_one": "x"}, create_mock_registry())
        errors = [d for d in diagnostics if d.severity == Severity.ERROR]

        assert len(errors) == 1
        diagnostic = errors[0]
        assert diagnostic.context is not None
        assert diagnostic.context.get("path") == "inputs"
        assert diagnostic.context.get("unused_inputs") == ["unused_one", "unused_two"]
        assert diagnostic.suggestions

    def test_malformed_template_diagnostic_preserves_template_text(self):
        """Malformed-template diagnostics should keep the raw malformed string."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "n1",
                    "type": "llm",
                    "params": {"prompt": "echo ${unclosed"},
                }
            ],
            "edges": [],
        }

        diagnostics = validate_workflow_templates(workflow_ir, {}, create_mock_registry())
        errors = [d for d in diagnostics if d.severity == Severity.ERROR]

        assert len(errors) == 1
        diagnostic = errors[0]
        assert diagnostic.title == "Template Error"
        assert diagnostic.context is not None
        assert diagnostic.context.get("template") == "echo ${unclosed"
        assert diagnostic.context.get("path") == "nodes[id=n1].params.prompt"


# ---------------------------------------------------------------------------
# Inputs-as-context template validation
# ---------------------------------------------------------------------------


class TestInputsContextTemplateValidation:
    """Tests for inputs-as-context template validation.

    When a node declares ``- inputs: {key: ${source}}``, the key becomes a valid
    template root within that node.  Both bare (``${key}``) and dotted
    (``${key.field}``) references must pass validation.
    """

    def test_inputs_key_bare_recognized(self):
        """${key} should be valid when node has inputs: {key: ...}."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "upstream",
                    "type": "llm",
                    "params": {"prompt": "Hello"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {
                        "inputs": {"concept_brief": "${upstream.response}"},
                        "prompt": "Write about ${concept_brief}",
                    },
                },
            ],
            "edges": [{"from": "upstream", "to": "consumer"}],
        }
        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_inputs_key_dotted_path_recognized(self):
        """${key.field} should be valid when key is in the node's inputs mapping."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "build-item",
                    "type": "code",
                    "params": {"code": "result: dict = {'concept_md': 'test'}"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {
                        "inputs": {"item": "${build-item.result}"},
                        "prompt": "Repeat: ${item.concept_md}",
                    },
                },
            ],
            "edges": [{"from": "build-item", "to": "consumer"}],
        }
        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_inputs_key_deeply_nested_path_recognized(self):
        """${key.a.b.c} should be valid when key is in the node's inputs mapping."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "upstream",
                    "type": "code",
                    "params": {"code": "result: dict = {'a': {'b': {'c': 1}}}"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {
                        "inputs": {"data": "${upstream.result}"},
                        "prompt": "Value: ${data.a.b.c}",
                    },
                },
            ],
            "edges": [{"from": "upstream", "to": "consumer"}],
        }
        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_inputs_key_on_non_code_node(self):
        """inputs-as-context works on any node type, not just code nodes."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "upstream",
                    "type": "shell",
                    "params": {"command": "echo hello"},
                },
                {
                    "id": "consumer",
                    "type": "shell",
                    "params": {
                        "inputs": {"output": "${upstream.stdout}"},
                        "command": "echo ${output}",
                    },
                },
            ],
            "edges": [{"from": "upstream", "to": "consumer"}],
        }
        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"
