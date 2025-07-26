"""Tests for template variable validation."""

from pflow.runtime.template_validator import TemplateValidator


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
                        "url": "$url",
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
                {"id": "n1", "type": "t1", "params": {"a": "$var1"}},
                {"id": "n2", "type": "t2", "params": {"b": "$var2", "c": "$var3"}},
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
                {"id": "summarize", "type": "llm", "params": {"prompt": "Title: $data.title by $data.metadata.author"}}
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
                {"id": "n1", "type": "t1", "params": {"a": "$url", "b": "$url"}},
                {"id": "n2", "type": "t2", "params": {"c": "$url"}},
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
                {"id": "fetch", "type": "youtube-transcript", "params": {"url": "$url"}},
                {
                    "id": "save",
                    "type": "write-file",
                    "params": {
                        "file_path": "summary.txt",
                        "content": "$summary",  # From shared store
                    },
                },
            ],
            "edges": [],
        }

        # All CLI params provided
        params = {"url": "https://youtube.com/watch?v=xyz"}

        errors = TemplateValidator.validate_workflow_templates(workflow_ir, params)
        assert len(errors) == 0

    def test_missing_cli_parameter(self):
        """Test validation catches missing CLI parameters."""
        workflow_ir = {
            "nodes": [
                {"id": "fetch", "type": "youtube-transcript", "params": {"url": "$url"}},
                {"id": "analyze", "type": "llm", "params": {"prompt": "Analyze $url"}},
            ],
            "edges": [],
        }

        # Missing 'url' parameter
        params = {}

        errors = TemplateValidator.validate_workflow_templates(workflow_ir, params)
        assert len(errors) == 1
        assert "Missing required parameter: --url" in errors[0]

    def test_multiple_missing_parameters(self):
        """Test validation reports multiple missing params."""
        workflow_ir = {
            "nodes": [
                {"id": "n1", "type": "t1", "params": {"a": "$param1", "b": "$param2"}},
                {"id": "n2", "type": "t2", "params": {"c": "$param3"}},
            ],
            "edges": [],
        }

        # No parameters provided
        params = {}

        errors = TemplateValidator.validate_workflow_templates(workflow_ir, params)
        assert len(errors) == 3
        assert any("--param1" in e for e in errors)
        assert any("--param2" in e for e in errors)
        assert any("--param3" in e for e in errors)

    def test_distinguishes_cli_from_shared_store(self):
        """Test validation correctly identifies CLI params vs shared store."""
        workflow_ir = {
            "nodes": [
                {"id": "fetch", "type": "youtube-transcript", "params": {"url": "$url"}},
                {
                    "id": "analyze",
                    "type": "llm",
                    "params": {
                        "prompt": "Summarize: $transcript_data.title"  # From shared store
                    },
                },
            ],
            "edges": [],
        }

        # Only CLI param provided
        params = {"url": "https://youtube.com/watch?v=xyz"}

        errors = TemplateValidator.validate_workflow_templates(workflow_ir, params)
        assert len(errors) == 0  # No errors - transcript_data is from shared store

    def test_invalid_syntax_in_shared_vars(self):
        """Test validation catches invalid syntax in shared store variables."""
        workflow_ir = {
            "nodes": [
                {"id": "n1", "type": "t1", "params": {"a": "$data..field"}}  # Invalid syntax
            ],
            "edges": [],
        }

        params = {}
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, params)
        assert len(errors) == 1
        assert "Invalid template syntax: $data..field" in errors[0]

    def test_partial_parameter_match(self):
        """Test base variable matching for CLI params."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "n1",
                    "type": "t1",
                    "params": {
                        "a": "$config.setting",  # Base var 'config' needs to be provided
                        "b": "$config.other",
                    },
                }
            ],
            "edges": [],
        }

        # Provide base parameter
        params = {"config": {"setting": "value1", "other": "value2"}}

        errors = TemplateValidator.validate_workflow_templates(workflow_ir, params)
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
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, params)
        assert len(errors) == 0  # No templates, no errors


class TestRealWorldScenarios:
    """Test validation with real-world workflow examples."""

    def test_youtube_workflow_validation(self):
        """Test validation of youtube summarization workflow."""
        workflow_ir = {
            "nodes": [
                {"id": "fetch", "type": "youtube-transcript", "params": {"url": "$url"}},
                {
                    "id": "summarize",
                    "type": "llm",
                    "params": {"prompt": "Summarize: $transcript_data.title\n\n$transcript_data.text"},
                },
                {
                    "id": "save",
                    "type": "write-file",
                    "params": {"file_path": "summary.md", "content": "# $transcript_data.title\n\n$summary"},
                },
            ],
            "edges": [{"from": "fetch", "to": "summarize"}, {"from": "summarize", "to": "save"}],
        }

        # Test with missing URL
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, {})
        assert len(errors) == 1
        assert "Missing required parameter: --url" in errors[0]

        # Test with URL provided
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, {"url": "https://youtube.com"})
        assert len(errors) == 0  # transcript_data and summary are from shared store

    def test_github_issue_workflow(self):
        """Test validation of github issue workflow."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "fetch_issue",
                    "type": "github-issue",
                    "params": {"repo": "$repo", "issue_number": "$issue_number"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "params": {"prompt": "Analyze issue: $issue_data.title\n\n$issue_data.body"},
                },
            ],
            "edges": [{"from": "fetch_issue", "to": "analyze"}],
        }

        # Test with no params
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, {})
        assert len(errors) == 2
        assert any("--repo" in e for e in errors)
        assert any("--issue_number" in e for e in errors)

        # Test with partial params
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, {"repo": "pflow"})
        assert len(errors) == 1
        assert "--issue_number" in errors[0]

        # Test with all params
        params = {"repo": "pflow", "issue_number": "123"}
        errors = TemplateValidator.validate_workflow_templates(workflow_ir, params)
        assert len(errors) == 0
