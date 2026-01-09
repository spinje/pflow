"""Tests for template variable validation."""

from unittest.mock import Mock

from pflow.runtime.template_validator import TemplateValidator


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

        templates = TemplateValidator._extract_all_templates(workflow_ir)
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

        templates = TemplateValidator._extract_all_templates(workflow_ir)
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

        templates = TemplateValidator._extract_all_templates(workflow_ir)
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

        templates = TemplateValidator._extract_all_templates(workflow_ir)
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

        templates = TemplateValidator._extract_all_templates(workflow_ir)
        assert templates == {"url"}


class TestSyntaxValidation:
    """Test template syntax validation."""

    def test_valid_syntax(self):
        """Test valid template syntax."""
        assert TemplateValidator._is_valid_syntax("url")
        assert TemplateValidator._is_valid_syntax("issue_number")
        assert TemplateValidator._is_valid_syntax("data.field")
        assert TemplateValidator._is_valid_syntax("a.b.c.d")
        assert TemplateValidator._is_valid_syntax("user_info.name_field")

    def test_invalid_syntax_double_dots(self):
        """Test that double dots are invalid."""
        assert not TemplateValidator._is_valid_syntax("data..field")
        assert not TemplateValidator._is_valid_syntax("a...b")

    def test_invalid_syntax_leading_trailing_dots(self):
        """Test that leading/trailing dots are invalid."""
        assert not TemplateValidator._is_valid_syntax(".field")
        assert not TemplateValidator._is_valid_syntax("field.")
        assert not TemplateValidator._is_valid_syntax(".field.subfield.")

    def test_invalid_syntax_empty_parts(self):
        """Test that empty parts are invalid."""
        assert not TemplateValidator._is_valid_syntax("")
        assert not TemplateValidator._is_valid_syntax("a..b")  # Empty part between dots

    def test_invalid_syntax_bad_characters(self):
        """Test that invalid characters are rejected."""
        assert not TemplateValidator._is_valid_syntax("var-name")  # Hyphen
        assert not TemplateValidator._is_valid_syntax("var name")  # Space
        assert not TemplateValidator._is_valid_syntax("var@field")  # Special char
        assert not TemplateValidator._is_valid_syntax("123var")  # Starts with digit

    def test_valid_identifiers(self):
        """Test valid identifier patterns."""
        assert TemplateValidator._is_valid_syntax("_private")
        assert TemplateValidator._is_valid_syntax("var123")
        assert TemplateValidator._is_valid_syntax("CONSTANT")
        assert TemplateValidator._is_valid_syntax("camelCase")
        assert TemplateValidator._is_valid_syntax("snake_case")


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

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, params, registry)
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, params, registry)
        assert len(errors) == 1
        assert "Template variable ${url} has no valid source" in errors[0]

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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, params, registry)
        assert len(errors) == 3
        assert any("${param1}" in e for e in errors)
        assert any("${param2}" in e for e in errors)
        assert any("${param3}" in e for e in errors)

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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, params, registry)
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, params, registry)
        assert len(errors) == 1
        assert "Template variable ${data..field} has no valid source" in errors[0]

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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, params, registry)
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, params, registry)
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)
        assert len(errors) == 1
        assert "Template variable ${url} has no valid source" in errors[0]

        # Test with URL provided
        errors, warnings = TemplateValidator.validate_workflow_templates(
            workflow_ir, {"url": "https://youtube.com"}, registry
        )
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)
        assert len(errors) == 2
        assert any("${repo}" in e for e in errors)
        assert any("${issue_number}" in e for e in errors)

        # Test with partial params
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {"repo": "pflow"}, registry)
        assert len(errors) == 1
        assert "${issue_number}" in errors[0]

        # Test with all params
        params = {"repo": "pflow", "issue_number": "123"}
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, params, registry)
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
        errors, warnings = TemplateValidator.validate_workflow_templates(
            workflow_ir, {"items": ["a", "b", "c"]}, registry
        )
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {"records": ["a", "b"]}, registry)
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {"items": ["a", "b"]}, registry)
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {"items": []}, registry)
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {"data": ["a", "b"]}, registry)
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, registry)
        assert len(errors) > 0
        assert any("nonexistent_array" in e for e in errors)

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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {"items": ["a"]}, registry)
        # Should fail because batch node doesn't expose 'response' directly
        assert len(errors) > 0
        assert any("response" in e for e in errors)

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
        errors, warnings = TemplateValidator.validate_workflow_templates(
            workflow_ir, {"url": "https://youtube.com"}, registry
        )
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
        errors, warnings = TemplateValidator.validate_workflow_templates(
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {"items": ["a", "b"]}, registry)
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {"items": ["a", "b"]}, registry)
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {"items": ["a", "b"]}, registry)
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
        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {"items": ["a", "b"]}, registry)
        # Should produce an error - typo_field is not a valid output
        assert len(errors) == 1, f"Expected 1 error for invalid path, got: {errors}"
        assert "typo_field" in errors[0] or "results[0]" in errors[0]
