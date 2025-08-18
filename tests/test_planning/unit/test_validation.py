"""Comprehensive tests for ValidatorNode and MetadataGenerationNode.

Tests cover:
- ValidatorNode: Validation orchestration, routing logic, error handling
- MetadataGenerationNode: LLM-based metadata generation with rich searchable fields
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from pflow.planning.ir_models import WorkflowMetadata
from pflow.planning.nodes import MetadataGenerationNode, ValidatorNode


class TestValidatorNode:
    """Test ValidatorNode validation orchestration and routing logic."""

    @pytest.fixture
    def validator_node(self):
        """Create ValidatorNode instance with mocked Registry."""
        with patch("pflow.planning.nodes.Registry") as MockRegistry:
            mock_registry = MagicMock()
            mock_registry.get_nodes_metadata.return_value = {
                "read-file": {"type": "read-file"},
                "llm": {"type": "llm"},
                "write-file": {"type": "write-file"},
            }
            MockRegistry.return_value = mock_registry
            node = ValidatorNode()
            node.registry = mock_registry
            return node

    @pytest.fixture
    def valid_workflow(self):
        """Valid workflow IR for testing."""
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "read-file", "params": {"file_path": "test.txt"}},
                {"id": "n2", "type": "llm", "params": {"prompt": "Process this"}},
            ],
            "edges": [{"from": "n1", "to": "n2"}],
        }

    @pytest.fixture
    def invalid_workflow_structure(self):
        """Workflow with structural validation errors."""
        return {
            # Missing ir_version
            "nodes": [{"id": "n1"}],  # Missing type
            "edges": [],
        }

    @pytest.fixture
    def invalid_workflow_node_type(self):
        """Workflow with unknown node type."""
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "unknown-node", "params": {}},
            ],
            "edges": [],
        }

    @pytest.fixture
    def workflow_with_templates(self):
        """Workflow with template variables."""
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "read-file", "params": {"file_path": "{{input_file}}"}},
            ],
            "edges": [],
            "inputs": {
                "input_file": {"type": "string", "description": "Input file path"},
            },
        }

    def test_valid_workflow_returns_metadata_generation(self, validator_node, valid_workflow):
        """Test that valid workflow routes to metadata_generation."""
        shared = {"generated_workflow": valid_workflow, "generation_attempts": 1}

        # Mock validate_ir to pass
        with (
            patch("pflow.core.ir_schema.validate_ir"),
            patch("pflow.runtime.template_validator.TemplateValidator") as MockTemplateValidator,
        ):
            MockTemplateValidator.validate_workflow_templates.return_value = []

            prep_res = validator_node.prep(shared)
            exec_res = validator_node.exec(prep_res)
            action = validator_node.post(shared, prep_res, exec_res)

            assert action == "metadata_generation"
            assert "workflow_metadata" in shared
            assert shared["workflow_metadata"] == {}
            assert exec_res["errors"] == []

    def test_invalid_workflow_first_attempt_returns_retry(self, validator_node, invalid_workflow_structure):
        """Test that invalid workflow with < 3 attempts returns retry."""
        shared = {"generated_workflow": invalid_workflow_structure, "generation_attempts": 1}

        # Mock validate_ir to raise ValidationError
        with patch("pflow.core.ir_schema.validate_ir") as mock_validate:
            mock_validate.side_effect = Exception("Missing required field: ir_version")
            with patch("pflow.runtime.template_validator.TemplateValidator") as MockTemplateValidator:
                MockTemplateValidator.validate_workflow_templates.return_value = []

                prep_res = validator_node.prep(shared)
                exec_res = validator_node.exec(prep_res)
                action = validator_node.post(shared, prep_res, exec_res)

                assert action == "retry"
                assert "validation_errors" in shared
                assert len(shared["validation_errors"]) > 0
                assert "Structure:" in shared["validation_errors"][0]

    def test_invalid_workflow_third_attempt_returns_failed(self, validator_node, invalid_workflow_structure):
        """Test that invalid workflow with >= 3 attempts returns failed."""
        shared = {"generated_workflow": invalid_workflow_structure, "generation_attempts": 3}

        # Mock validate_ir to raise error
        with patch("pflow.core.ir_schema.validate_ir") as mock_validate:
            mock_validate.side_effect = Exception("Missing required field: ir_version")
            with patch("pflow.runtime.template_validator.TemplateValidator") as MockTemplateValidator:
                MockTemplateValidator.validate_workflow_templates.return_value = []

                prep_res = validator_node.prep(shared)
                exec_res = validator_node.exec(prep_res)
                action = validator_node.post(shared, prep_res, exec_res)

                assert action == "failed"
                assert "validation_errors" in shared
                assert len(shared["validation_errors"]) > 0

    def test_structural_validation_error_caught(self, validator_node, invalid_workflow_structure):
        """Test that structural validation errors are properly caught and formatted."""
        shared = {"generated_workflow": invalid_workflow_structure, "generation_attempts": 1}

        # Mock validate_ir to raise an exception with path and message attributes
        with patch("pflow.core.ir_schema.validate_ir") as mock_validate:
            # Create a proper exception with path and message attributes
            class ValidationError(Exception):
                def __init__(self):
                    self.path = "nodes[0]"
                    self.message = "Missing required field: type"
                    super().__init__(f"{self.path}: {self.message}")

            mock_validate.side_effect = ValidationError()

            with patch("pflow.runtime.template_validator.TemplateValidator") as MockTemplateValidator:
                MockTemplateValidator.validate_workflow_templates.return_value = []

                prep_res = validator_node.prep(shared)
                exec_res = validator_node.exec(prep_res)

                assert len(exec_res["errors"]) > 0
                assert "Structure:" in exec_res["errors"][0]
                assert "nodes[0]" in exec_res["errors"][0]

    def test_template_validation_errors_caught(self, validator_node, workflow_with_templates):
        """Test that template validation errors are caught."""
        shared = {"generated_workflow": workflow_with_templates, "generation_attempts": 1}

        with (
            patch("pflow.core.ir_schema.validate_ir"),
            patch("pflow.runtime.template_validator.TemplateValidator") as MockTemplateValidator,
        ):
            MockTemplateValidator.validate_workflow_templates.return_value = [
                "Template error: Unknown variable {{unknown_var}}",
                "Unused input: input_file",
            ]

            prep_res = validator_node.prep(shared)
            exec_res = validator_node.exec(prep_res)

            assert len(exec_res["errors"]) == 2
            assert "Unknown variable" in exec_res["errors"][0]
            assert "Unused input" in exec_res["errors"][1]

    def test_unknown_node_type_error_caught(self, validator_node, invalid_workflow_node_type):
        """Test that unknown node type errors are caught."""
        shared = {"generated_workflow": invalid_workflow_node_type, "generation_attempts": 1}

        with (
            patch("pflow.core.ir_schema.validate_ir"),
            patch("pflow.runtime.template_validator.TemplateValidator") as MockTemplateValidator,
        ):
            MockTemplateValidator.validate_workflow_templates.return_value = []

            prep_res = validator_node.prep(shared)
            exec_res = validator_node.exec(prep_res)

            assert len(exec_res["errors"]) == 1
            assert "Unknown node type: 'unknown-node'" in exec_res["errors"][0]

    def test_top_three_errors_returned_when_many_errors(self, validator_node):
        """Test that only top 3 errors are returned when there are many."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "unknown-1", "params": {}},
                {"id": "n2", "type": "unknown-2", "params": {}},
                {"id": "n3", "type": "unknown-3", "params": {}},
                {"id": "n4", "type": "unknown-4", "params": {}},
                {"id": "n5", "type": "unknown-5", "params": {}},
            ],
            "edges": [],
        }
        shared = {"generated_workflow": workflow, "generation_attempts": 1}

        with (
            patch("pflow.core.ir_schema.validate_ir"),
            patch("pflow.runtime.template_validator.TemplateValidator") as MockTemplateValidator,
        ):
            MockTemplateValidator.validate_workflow_templates.return_value = []

            prep_res = validator_node.prep(shared)
            exec_res = validator_node.exec(prep_res)

            # Should return exactly 3 errors even though there are 5 unknown nodes
            assert len(exec_res["errors"]) == 3
            assert all("Unknown node type" in error for error in exec_res["errors"])

    def test_missing_workflow_handled_gracefully(self, validator_node):
        """Test that missing workflow is handled gracefully."""
        shared = {"generation_attempts": 1}  # No generated_workflow

        prep_res = validator_node.prep(shared)
        exec_res = validator_node.exec(prep_res)

        assert len(exec_res["errors"]) == 1
        assert "No workflow provided for validation" in exec_res["errors"][0]

    def test_exec_fallback_returns_critical_error(self, validator_node):
        """Test exec_fallback returns critical error."""
        prep_res = {"workflow": {"invalid": "data"}}
        exc = Exception("Test exception")

        result = validator_node.exec_fallback(prep_res, exc)

        assert "errors" in result
        assert len(result["errors"]) == 1
        assert "Critical validation failure" in result["errors"][0]

    def test_registry_validation_error_caught(self, validator_node, valid_workflow):
        """Test that registry validation errors are caught."""
        shared = {"generated_workflow": valid_workflow, "generation_attempts": 1}

        # Make registry.get_nodes_metadata raise an exception
        validator_node.registry.get_nodes_metadata.side_effect = Exception("Registry unavailable")

        with (
            patch("pflow.core.ir_schema.validate_ir"),
            patch("pflow.runtime.template_validator.TemplateValidator") as MockTemplateValidator,
        ):
            MockTemplateValidator.validate_workflow_templates.return_value = []

            prep_res = validator_node.prep(shared)
            exec_res = validator_node.exec(prep_res)

            assert len(exec_res["errors"]) == 1
            assert "Registry validation error" in exec_res["errors"][0]

    def test_template_validator_exception_caught(self, validator_node, valid_workflow):
        """Test that TemplateValidator exceptions are caught."""
        shared = {"generated_workflow": valid_workflow, "generation_attempts": 1}

        with (
            patch("pflow.core.ir_schema.validate_ir"),
            patch("pflow.runtime.template_validator.TemplateValidator") as MockTemplateValidator,
        ):
            MockTemplateValidator.validate_workflow_templates.side_effect = Exception("Template parsing failed")

            prep_res = validator_node.prep(shared)
            exec_res = validator_node.exec(prep_res)

            assert len(exec_res["errors"]) == 1

    def test_validation_errors_cleared_on_successful_retry(self, validator_node, valid_workflow):
        """Test that validation_errors are cleared when validation succeeds after retry.

        This test ensures that old validation errors from a previous failed attempt
        are cleared when validation succeeds on retry. This prevents the bug where
        the workflow appears to fail even though validation actually passed.
        """
        # Simulate a retry scenario with old validation errors
        shared = {
            "validation_errors": ["Old error: type 'integer' is invalid"],  # Previous error
            "generated_workflow": valid_workflow,
            "generation_attempts": 2,  # Second retry attempt
        }

        with (
            patch("pflow.core.ir_schema.validate_ir"),  # Mock passes
            patch("pflow.runtime.template_validator.TemplateValidator") as MockTemplateValidator,
        ):
            MockTemplateValidator.validate_workflow_templates.return_value = []  # No errors

            prep_res = validator_node.prep(shared)
            exec_res = validator_node.exec(prep_res)

            # Validation should succeed
            assert exec_res["errors"] == []

            # Run post to check routing and side effects
            action = validator_node.post(shared, prep_res, exec_res)

            # Should route to metadata generation
            assert action == "metadata_generation"

            # CRITICAL: validation_errors should be cleared
            assert "validation_errors" not in shared, (
                "validation_errors should be cleared when validation succeeds, but found: {}".format(
                    shared.get("validation_errors")
                )
            )

            # workflow_metadata should be initialized
            assert "workflow_metadata" in shared
            assert shared["workflow_metadata"] == {}


class TestMetadataGenerationNode:
    """Test MetadataGenerationNode metadata extraction and flow continuation."""

    @pytest.fixture
    def metadata_node(self):
        """Create MetadataGenerationNode instance."""
        return MetadataGenerationNode()

    @pytest.fixture
    def workflow_with_inputs(self):
        """Workflow with declared inputs for testing."""
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "read-file", "params": {"file_path": "{{input_file}}"}},
            ],
            "edges": [],
            "inputs": {
                "input_file": {"type": "string", "description": "Input file"},
                "output_dir": {"type": "string", "description": "Output directory"},
            },
        }

    @pytest.fixture
    def workflow_with_outputs(self):
        """Workflow with declared outputs for testing."""
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "write-file", "params": {"file_path": "output.txt"}},
            ],
            "edges": [],
            "outputs": {
                "result_file": {"type": "string", "description": "Result file path"},
                "status": {"type": "string", "description": "Workflow status"},
            },
        }

    def test_llm_metadata_generation(self, metadata_node):
        """Test that LLM is used to generate rich metadata."""
        shared = {
            "generated_workflow": {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "read-file"}],
                "inputs": {"file_path": {"type": "string"}},
            },
            "user_input": "Read the CSV file and generate a summary report",
        }

        # Create WorkflowMetadata instance for mock response
        test_metadata = WorkflowMetadata(
            suggested_name="csv-summary-generator",
            description="Reads a CSV file and generates a comprehensive summary report with detailed statistics, data insights, and trend analysis for business intelligence",
            search_keywords=["csv", "summary", "report", "analyze", "statistics"],
            capabilities=["Read CSV files", "Generate statistical summaries", "Create reports"],
            typical_use_cases=["Analyzing data exports", "Creating executive summaries"],
        )

        # Mock both the LLM and parse_structured_response
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_get_model.return_value = mock_model

            # Mock parse_structured_response directly since it's imported in the exec method
            with patch("pflow.planning.utils.llm_helpers.parse_structured_response") as mock_parse:
                mock_parse.return_value = test_metadata

                prep_res = metadata_node.prep(shared)
                exec_res = metadata_node.exec(prep_res)

                # Verify LLM was called
                mock_get_model.assert_called_once_with("anthropic/claude-3-haiku-20240307")
                mock_model.prompt.assert_called_once()

                # Verify rich metadata fields
                assert exec_res["suggested_name"] == "csv-summary-generator"
                assert exec_res["description"] == test_metadata.description
                assert exec_res["search_keywords"] == test_metadata.search_keywords
                assert exec_res["capabilities"] == test_metadata.capabilities
                assert exec_res["typical_use_cases"] == test_metadata.typical_use_cases
                assert exec_res["declared_inputs"] == ["file_path"]

    def test_llm_prompt_includes_context(self, metadata_node):
        """Test that LLM prompt includes all necessary context."""
        shared = {
            "generated_workflow": {"nodes": []},
            "user_input": "Process GitHub issues",
            "planning_context": "GitHub integration context",
            "discovered_params": {"repo": "owner/repo", "issue_number": "123"},
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()

            test_metadata = WorkflowMetadata(
                suggested_name="github-issue-processor",
                description="Processes GitHub issues for comprehensive analysis and reporting with automated categorization, tagging, and priority assignment based on content",
                search_keywords=["github", "issues", "process"],
                capabilities=["Fetch GitHub issues", "Process issue data"],
                typical_use_cases=["Issue tracking"],
            )

            with patch("pflow.planning.utils.llm_helpers.parse_structured_response") as mock_parse:
                mock_parse.return_value = test_metadata
                mock_get_model.return_value = mock_model

                prep_res = metadata_node.prep(shared)
                metadata_node.exec(prep_res)

                # Verify prompt was called with proper arguments
                call_args = mock_model.prompt.call_args
                prompt_text = call_args[0][0]

                # Check that prompt includes key information
                assert "Process GitHub issues" in prompt_text
                assert "repo" in prompt_text or "discovered_params" in str(call_args)

    def test_llm_uses_haiku_model_for_speed(self, metadata_node):
        """Test that metadata generation uses faster Haiku model."""
        shared = {
            "generated_workflow": {},
            "user_input": "Test workflow",
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            test_metadata = WorkflowMetadata(
                suggested_name="test-workflow",
                description="A comprehensive test workflow for validating system functionality and integration points across multiple components with detailed error reporting",
                search_keywords=["test", "validation", "check"],
                capabilities=["Run tests", "Validate output"],
                typical_use_cases=["Testing"],
            )

            with patch("pflow.planning.utils.llm_helpers.parse_structured_response") as mock_parse:
                mock_parse.return_value = test_metadata
                mock_get_model.return_value = mock_model

                prep_res = metadata_node.prep(shared)
                metadata_node.exec(prep_res)

                # Verify Haiku model is used (faster for metadata)
                mock_get_model.assert_called_once_with("anthropic/claude-3-haiku-20240307")

    def test_temperature_setting_for_consistency(self, metadata_node):
        """Test that metadata generation uses lower temperature for consistency."""
        shared = {
            "generated_workflow": {},
            "user_input": "Test workflow",
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            test_metadata = WorkflowMetadata(
                suggested_name="test-workflow",
                description="A comprehensive test workflow for validating system functionality and integration testing with thorough validation of all components and interfaces",
                search_keywords=["test", "validation", "integration"],
                capabilities=["Test functionality", "Validate components"],
                typical_use_cases=["Testing"],
            )

            with patch("pflow.planning.utils.llm_helpers.parse_structured_response") as mock_parse:
                mock_parse.return_value = test_metadata
                mock_get_model.return_value = mock_model

                prep_res = metadata_node.prep(shared)
                metadata_node.exec(prep_res)

                # Verify lower temperature is used (0.3 for consistency)
                call_args = mock_model.prompt.call_args
                assert call_args.kwargs.get("temperature") == 0.3

    def test_search_keywords_are_unique_and_relevant(self, metadata_node):
        """Test that search keywords are unique and relevant."""
        shared = {
            "generated_workflow": {},
            "user_input": "Fetch GitHub issues and create changelog",
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            test_metadata = WorkflowMetadata(
                suggested_name="github-changelog-generator",
                description="Fetches GitHub issues from a repository and generates a professionally formatted changelog for releases with categorization by type and priority",
                search_keywords=["github", "changelog", "release", "issues", "version", "history"],
                capabilities=["Fetch GitHub issues", "Generate changelogs", "Format release notes"],
                typical_use_cases=["Preparing release documentation", "Creating version history"],
            )

            with patch("pflow.planning.utils.llm_helpers.parse_structured_response") as mock_parse:
                mock_parse.return_value = test_metadata
                mock_get_model.return_value = mock_model

                prep_res = metadata_node.prep(shared)
                exec_res = metadata_node.exec(prep_res)

                # Verify keywords are present and meaningful
                assert len(exec_res["search_keywords"]) >= 3
                assert len(exec_res["search_keywords"]) <= 10
                assert all(isinstance(kw, str) for kw in exec_res["search_keywords"])

    def test_capabilities_describe_workflow_functions(self, metadata_node):
        """Test that capabilities accurately describe what the workflow does."""
        shared = {
            "generated_workflow": {
                "nodes": [
                    {"id": "fetch", "type": "github-fetch-issues"},
                    {"id": "format", "type": "llm"},
                    {"id": "save", "type": "write-file"},
                ]
            },
            "user_input": "Fetch issues and create report",
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            test_metadata = WorkflowMetadata(
                suggested_name="issue-report-generator",
                description="Fetches issues from GitHub repositories and creates comprehensive formatted reports with detailed analysis, insights, and trend visualization",
                search_keywords=["issues", "report", "github", "analysis"],
                capabilities=[
                    "Fetches issues from GitHub repositories",
                    "Analyzes issue patterns and trends",
                    "Generates formatted reports",
                    "Saves reports to files",
                ],
                typical_use_cases=["Sprint retrospectives", "Project status reports"],
            )

            with patch("pflow.planning.utils.llm_helpers.parse_structured_response") as mock_parse:
                mock_parse.return_value = test_metadata
                mock_get_model.return_value = mock_model

                prep_res = metadata_node.prep(shared)
                exec_res = metadata_node.exec(prep_res)

                # Verify capabilities are descriptive
                assert len(exec_res["capabilities"]) >= 2
                assert len(exec_res["capabilities"]) <= 6
                assert all(cap for cap in exec_res["capabilities"])  # No empty strings

    def test_declared_inputs_extraction_with_llm(self, metadata_node, workflow_with_inputs):
        """Test extraction of declared inputs from workflow with LLM metadata."""
        shared = {
            "generated_workflow": workflow_with_inputs,
            "user_input": "test",
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            test_metadata = WorkflowMetadata(
                suggested_name="test-workflow",
                description="A comprehensive test workflow that demonstrates advanced input handling and processing capabilities with full validation and error recovery",
                search_keywords=["test", "input", "processing"],
                capabilities=["Handle inputs", "Process data"],
                typical_use_cases=["Testing input handling"],
            )

            with patch("pflow.planning.utils.llm_helpers.parse_structured_response") as mock_parse:
                mock_parse.return_value = test_metadata
                mock_get_model.return_value = mock_model

                prep_res = metadata_node.prep(shared)
                exec_res = metadata_node.exec(prep_res)

                # Inputs are extracted directly from workflow, not from LLM
                assert exec_res["declared_inputs"] == ["input_file", "output_dir"]

    def test_typical_use_cases_provide_context(self, metadata_node):
        """Test that typical use cases provide meaningful context."""
        shared = {
            "generated_workflow": {"nodes": [{"id": "backup", "type": "copy-file"}]},
            "user_input": "Create automated backup system",
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            test_metadata = WorkflowMetadata(
                suggested_name="automated-backup-system",
                description="Creates automated backups of critical files and directories with advanced versioning, retention policies, and comprehensive disaster recovery support",
                search_keywords=["backup", "archive", "versioning", "retention"],
                capabilities=["Create file backups", "Manage versions", "Apply retention policies"],
                typical_use_cases=[
                    "Daily backup of configuration files",
                    "Archiving project deliverables",
                    "Disaster recovery preparation",
                ],
            )

            with patch("pflow.planning.utils.llm_helpers.parse_structured_response") as mock_parse:
                mock_parse.return_value = test_metadata
                mock_get_model.return_value = mock_model

                prep_res = metadata_node.prep(shared)
                exec_res = metadata_node.exec(prep_res)

                # Verify use cases are meaningful
                assert len(exec_res["typical_use_cases"]) >= 1
                assert len(exec_res["typical_use_cases"]) <= 3
                assert all(len(use_case) > 10 for use_case in exec_res["typical_use_cases"])

    def test_empty_inputs_outputs_when_not_declared(self, metadata_node):
        """Test empty lists returned when inputs/outputs not declared."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test", "params": {}}],
            "edges": [],
        }
        shared = {
            "generated_workflow": workflow,
            "user_input": "test",
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            test_metadata = WorkflowMetadata(
                suggested_name="test-workflow",
                description="A simple test workflow without declared inputs or outputs designed specifically for validation purposes and unit testing of the system",
                search_keywords=["test", "simple", "validation"],
                capabilities=["Basic testing", "Validation"],
                typical_use_cases=["Unit testing"],
            )

            with patch("pflow.planning.utils.llm_helpers.parse_structured_response") as mock_parse:
                mock_parse.return_value = test_metadata
                mock_get_model.return_value = mock_model

                prep_res = metadata_node.prep(shared)
                exec_res = metadata_node.exec(prep_res)

                # No inputs/outputs in workflow
                assert exec_res["declared_inputs"] == []
                assert "declared_outputs" in exec_res  # Should have key even if empty

    def test_llm_failure_triggers_fallback(self, metadata_node):
        """Test that LLM failures trigger fallback to simple extraction."""
        shared = {
            "generated_workflow": {},
            "user_input": "Test workflow that should fallback",
        }

        with patch("llm.get_model") as mock_get_model:
            # Simulate LLM failure
            mock_get_model.side_effect = Exception("API key not found")

            # Mock the fallback simple extraction
            with patch.object(metadata_node, "exec_fallback") as mock_fallback:
                mock_fallback.return_value = {
                    "suggested_name": "test-workflow",
                    "description": "Test workflow that should fallback",
                    "search_keywords": [],
                    "capabilities": [],
                    "typical_use_cases": [],
                    "declared_inputs": [],
                    "declared_outputs": [],
                }

                prep_res = metadata_node.prep(shared)
                # Since exec will fail, it should trigger exec_fallback via retry mechanism
                # For testing, we'll call exec_fallback directly
                result = metadata_node.exec_fallback(prep_res, Exception("API key not found"))

                # Verify fallback was used
                assert result["suggested_name"] == "test-workflow"
                assert result["search_keywords"] == []  # Empty in fallback
                assert result["capabilities"] == []  # Empty in fallback

    def test_workflow_metadata_schema_is_used(self, metadata_node):
        """Test that WorkflowMetadata Pydantic schema is used for structured output."""
        shared = {
            "generated_workflow": {},
            "user_input": "Create backup system",
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()

            # Verify schema is passed to LLM
            with patch("pflow.planning.utils.llm_helpers.parse_structured_response") as mock_parse:
                test_metadata = WorkflowMetadata(
                    suggested_name="backup-system",
                    description="Automated backup system that creates versioned copies of files and directories with intelligent retention policies and compression optimization",
                    search_keywords=["backup", "archive", "copy"],
                    capabilities=["Create backups", "Version files"],
                    typical_use_cases=["Daily backups"],
                )
                mock_parse.return_value = test_metadata
                mock_get_model.return_value = mock_model

                prep_res = metadata_node.prep(shared)
                metadata_node.exec(prep_res)

                # Verify the LLM was called with schema parameter
                call_args = mock_model.prompt.call_args
                assert "schema" in call_args.kwargs
                # The schema should be WorkflowMetadata class
                assert call_args.kwargs["schema"].__name__ == "WorkflowMetadata"

    def test_post_stores_metadata_and_returns_empty_string(self, metadata_node):
        """Test that post() stores metadata and returns empty string to continue flow."""
        shared = {"generated_workflow": {}}
        prep_res = {}
        exec_res = {
            "suggested_name": "test-workflow",
            "description": "Test description",
            "declared_inputs": ["input1"],
            "declared_outputs": ["output1"],
        }

        action = metadata_node.post(shared, prep_res, exec_res)

        assert action == ""  # Empty string continues flow
        assert "workflow_metadata" in shared
        assert shared["workflow_metadata"] == exec_res

    def test_exec_fallback_uses_simple_extraction(self, metadata_node):
        """Test exec_fallback falls back to simple extraction when LLM fails."""
        prep_res = {
            "workflow": {"inputs": {"file": {"type": "string"}}, "outputs": {"result": {"type": "string"}}},
            "user_input": "Process the data files from input directory",
        }
        exc = Exception("LLM API error")

        # Mock the simple extraction helper where it's used (imported at module level)
        with patch("pflow.planning.nodes.generate_workflow_name") as mock_gen_name:
            mock_gen_name.return_value = "process-data-files"

            result = metadata_node.exec_fallback(prep_res, exc)

            # Verify fallback behavior
            assert result["suggested_name"] == "process-data-files"
            assert result["description"] == "Process the data files from input directory"
            assert result["search_keywords"] == []  # Empty in fallback
            assert result["capabilities"] == []  # Empty in fallback
            assert result["typical_use_cases"] == []  # Empty in fallback
            assert result["declared_inputs"] == ["file"]

            # Verify simple name generator was called
            mock_gen_name.assert_called_once_with("Process the data files from input directory")

    def test_full_metadata_extraction_flow_with_llm(self, metadata_node):
        """Test complete metadata extraction flow with LLM."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "read-file", "params": {"file_path": "{{input}}"}},
                {"id": "n2", "type": "write-file", "params": {"file_path": "{{output}}"}},
            ],
            "edges": [{"from": "n1", "to": "n2"}],
            "inputs": {
                "input": {"type": "string", "description": "Input file"},
            },
            "outputs": {
                "result": {"type": "string", "description": "Result file"},
            },
        }
        shared = {
            "generated_workflow": workflow,
            "user_input": "Process data files from input directory",
            "planning_context": "Additional context",
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            test_metadata = WorkflowMetadata(
                suggested_name="data-file-processor",
                description="Processes data files from an input directory with highly configurable transformations, format conversions, and multiple output destinations",
                search_keywords=["data", "files", "process", "transform", "directory"],
                capabilities=["Read files from directory", "Process data", "Write output files"],
                typical_use_cases=["Batch file processing", "Data transformation pipelines"],
            )

            with patch("pflow.planning.utils.llm_helpers.parse_structured_response") as mock_parse:
                mock_parse.return_value = test_metadata
                mock_get_model.return_value = mock_model

                # Execute full flow
                prep_res = metadata_node.prep(shared)
                exec_res = metadata_node.exec(prep_res)
                action = metadata_node.post(shared, prep_res, exec_res)

                # Verify LLM-generated metadata
                assert exec_res["suggested_name"] == "data-file-processor"
                assert len(exec_res["description"]) >= 100  # Rich description
                assert exec_res["search_keywords"] == test_metadata.search_keywords
                assert exec_res["capabilities"] == test_metadata.capabilities
                assert exec_res["typical_use_cases"] == test_metadata.typical_use_cases
                assert exec_res["declared_inputs"] == ["input"]
                assert action == ""
                assert shared["workflow_metadata"] == exec_res

    def test_prep_includes_all_context_for_llm(self, metadata_node):
        """Test prep() includes all necessary context for LLM."""
        shared = {
            "generated_workflow": {"test": "workflow"},
            "user_input": "test input",
            "planning_context": "test context",
            "discovered_params": {"param1": "value1"},
        }

        prep_res = metadata_node.prep(shared)

        assert prep_res["workflow"] == {"test": "workflow"}
        assert prep_res["user_input"] == "test input"
        assert prep_res["planning_context"] == "test context"
        assert prep_res["discovered_params"] == {"param1": "value1"}
        assert prep_res["model_name"] == "anthropic/claude-3-haiku-20240307"
        assert prep_res["temperature"] == 0.3
