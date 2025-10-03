"""Tests for workflow loading functionality in context builder.

These tests focus on behavior validation and use real filesystem operations
where possible to ensure robust testing of workflow loading capabilities.

IMPORTANT: Tests that check log output using caplog MUST explicitly set the log level
for the pflow.planning.context_builder logger. This is required because earlier tests
in the full test suite may modify logger configuration, preventing caplog from capturing
logs by default. Use: caplog.set_level("WARNING", logger="pflow.planning.context_builder")
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.planning.context_builder import (
    _load_saved_workflows,
    build_discovery_context,
    build_planning_context,
)


@pytest.fixture(autouse=True)
def isolate_planning_state():
    """Automatically isolate global state that affects planning context.

    This fixture prevents test pollution by ensuring each test starts with
    clean global state, especially important when running with the full test suite.
    """
    # Import here to avoid circular imports
    import pflow.planning.context_builder
    import pflow.registry.scanner

    # Save original values
    original_workflow_manager = getattr(pflow.planning.context_builder, "_workflow_manager", None)
    original_metadata_extractor = getattr(pflow.registry.scanner, "_metadata_extractor", None)
    original_process_nodes = getattr(pflow.planning.context_builder, "_process_nodes", None)

    # Reset to None before each test
    pflow.planning.context_builder._workflow_manager = None
    pflow.registry.scanner._metadata_extractor = None

    # Remove any patches from previous tests
    if (
        hasattr(pflow.planning.context_builder._process_nodes, "_mock_name")
        and original_process_nodes
        and not hasattr(original_process_nodes, "_mock_name")
    ):
        pflow.planning.context_builder._process_nodes = original_process_nodes

    yield

    # Restore original values after test
    pflow.planning.context_builder._workflow_manager = original_workflow_manager
    pflow.registry.scanner._metadata_extractor = original_metadata_extractor
    if original_process_nodes and not hasattr(original_process_nodes, "_mock_name"):
        pflow.planning.context_builder._process_nodes = original_process_nodes


class TestWorkflowLoading:
    """Test suite for workflow loading functionality.

    These tests validate behavior using real filesystem operations and temporary directories
    to ensure reliable testing without excessive mocking.
    """

    def test_creates_directory_if_missing(self, tmp_path, monkeypatch):
        """Test that _load_saved_workflows creates the directory if it doesn't exist."""
        # Use a temporary directory as home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        workflow_dir = fake_home / ".pflow" / "workflows"
        assert not workflow_dir.exists()

        # Call the function
        workflows = _load_saved_workflows()

        # Directory should now exist
        assert workflow_dir.exists()
        assert workflow_dir.is_dir()
        assert workflows == []

    def test_empty_directory_returns_empty_list(self, tmp_path, monkeypatch):
        """Test that an empty directory returns an empty list."""
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create empty directory
        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        workflows = _load_saved_workflows()
        assert workflows == []

    def test_loads_valid_workflow(self, tmp_path, monkeypatch):
        """Test loading a valid workflow JSON file."""
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create workflow directory
        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        # Create valid workflow file
        valid_workflow = {
            "name": "test-workflow",
            "description": "A test workflow",
            "ir": {"nodes": [{"id": "node1", "type": "test-node"}], "edges": []},
            "version": "1.0.0",  # Optional field
            "tags": ["test", "example"],  # Optional field
        }

        workflow_file = workflow_dir / "test-workflow.json"
        workflow_file.write_text(json.dumps(valid_workflow, indent=2))

        # Load workflows
        workflows = _load_saved_workflows()

        assert len(workflows) == 1
        assert workflows[0]["name"] == "test-workflow"
        assert workflows[0]["description"] == "A test workflow"
        assert workflows[0]["ir"]["nodes"][0]["id"] == "node1"
        # Optional fields should be preserved
        assert workflows[0]["version"] == "1.0.0"
        assert workflows[0]["tags"] == ["test", "example"]

    def test_loads_multiple_workflows(self, tmp_path, monkeypatch):
        """Test loading multiple valid workflow files."""
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create workflow directory
        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        # Create multiple workflow files
        for i in range(3):
            workflow = {
                "name": f"workflow-{i}",
                "description": f"Workflow {i}",
                "ir": {"nodes": [{"id": f"node{i}", "type": "test-node"}]},
            }
            workflow_file = workflow_dir / f"workflow-{i}.json"
            workflow_file.write_text(json.dumps(workflow))

        # Load workflows
        workflows = _load_saved_workflows()

        assert len(workflows) == 3
        names = [w["name"] for w in workflows]
        assert "workflow-0" in names
        assert "workflow-1" in names
        assert "workflow-2" in names

    def test_skips_invalid_json(self, tmp_path, monkeypatch, caplog):
        """Test that invalid JSON files are skipped with warning."""
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create workflow directory
        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        # Create invalid JSON file
        invalid_file = workflow_dir / "invalid.json"
        invalid_file.write_text("{invalid json content")

        # Create valid file
        valid_workflow = {
            "name": "valid-workflow",
            "description": "Valid workflow",
            "ir": {"nodes": []},
        }
        valid_file = workflow_dir / "valid.json"
        valid_file.write_text(json.dumps(valid_workflow))

        # Ensure caplog captures WARNING level logs from the context_builder module
        # This is necessary because earlier tests may have modified logger configuration
        caplog.set_level("WARNING", logger="pflow.planning.context_builder")

        # Load workflows
        workflows = _load_saved_workflows()

        # Should only load the valid one
        assert len(workflows) == 1
        assert workflows[0]["name"] == "valid-workflow"

        # Should log warning about invalid JSON
        assert "Failed to parse JSON from invalid.json" in caplog.text

    def test_skips_missing_required_fields(self, tmp_path, monkeypatch, caplog):
        """Test that files missing required fields are skipped."""
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create workflow directory
        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        # Create workflow missing 'name' field
        missing_name = {"description": "Missing name", "ir": {}}
        (workflow_dir / "missing-name.json").write_text(json.dumps(missing_name))

        # Create workflow missing 'ir' field
        missing_ir = {"name": "missing-ir", "description": "Missing IR"}
        (workflow_dir / "missing-ir.json").write_text(json.dumps(missing_ir))

        # Create valid workflow
        valid = {"name": "valid", "description": "Valid", "ir": {}}
        (workflow_dir / "valid.json").write_text(json.dumps(valid))

        # Ensure caplog captures WARNING level logs from the context_builder module
        caplog.set_level("WARNING", logger="pflow.planning.context_builder")

        # Load workflows
        workflows = _load_saved_workflows()

        # Should only load the valid one
        assert len(workflows) == 1
        assert workflows[0]["name"] == "valid"

        # Should log warnings
        assert "missing required fields: ['name']" in caplog.text
        assert "missing required fields: ['ir']" in caplog.text

    def test_skips_wrong_field_types(self, tmp_path, monkeypatch, caplog):
        """Test that files with wrong field types are skipped."""
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create workflow directory
        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        # Create workflow with wrong type for 'inputs' (should be list)
        # This should now load since we don't validate metadata-level inputs
        wrong_inputs = {
            "name": "wrong-inputs",
            "description": "Wrong inputs type",
            "inputs": "should be a list",  # Wrong type - but ignored now
            "ir": {},
        }
        (workflow_dir / "wrong-inputs.json").write_text(json.dumps(wrong_inputs))

        # Create workflow with wrong type for 'ir' (should be dict)
        wrong_ir = {
            "name": "wrong-ir",
            "description": "Wrong ir type",
            "ir": [],  # Wrong type
        }
        (workflow_dir / "wrong-ir.json").write_text(json.dumps(wrong_ir))

        # Ensure caplog captures WARNING level logs from the context_builder module
        caplog.set_level("WARNING", logger="pflow.planning.context_builder")

        # Load workflows
        workflows = _load_saved_workflows()

        # Should load the one with wrong inputs (since we don't validate metadata inputs)
        # But not the one with wrong ir type
        assert len(workflows) == 1
        assert workflows[0]["name"] == "wrong-inputs"

        # Should only log warning about ir type
        assert "Invalid 'ir' type in wrong-ir.json: expected dict" in caplog.text

    def test_skips_empty_files(self, tmp_path, monkeypatch, caplog):
        """Test that empty files are skipped with warning."""
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create workflow directory
        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        # Create empty file
        empty_file = workflow_dir / "empty.json"
        empty_file.write_text("")

        # Create whitespace-only file
        whitespace_file = workflow_dir / "whitespace.json"
        whitespace_file.write_text("   \n\t  \n")

        # Ensure caplog captures WARNING level logs from the context_builder module
        caplog.set_level("WARNING", logger="pflow.planning.context_builder")

        # Load workflows
        workflows = _load_saved_workflows()

        assert len(workflows) == 0
        assert "Workflow file is empty: empty.json" in caplog.text
        assert "Workflow file is empty: whitespace.json" in caplog.text

    def test_ignores_non_json_files(self, tmp_path, monkeypatch):
        """Test that non-JSON files are ignored."""
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create workflow directory
        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        # Create non-JSON files
        (workflow_dir / "README.txt").write_text("This is a readme")
        (workflow_dir / "workflow.yaml").write_text("yaml: content")
        (workflow_dir / ".hidden.json").write_text('{"hidden": true}')

        # Create valid JSON file
        valid_workflow = {"name": "valid", "description": "Valid", "ir": {}}
        (workflow_dir / "valid.json").write_text(json.dumps(valid_workflow))

        # Load workflows
        workflows = _load_saved_workflows()

        # Should only load the valid JSON file
        assert len(workflows) == 1
        assert workflows[0]["name"] == "valid"

    def test_handles_permission_error_gracefully(self, tmp_path, monkeypatch, caplog):
        """Test handling of permission errors when reading files.

        This test works on all platforms by using proper permission handling.
        """
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create workflow directory
        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        # Create a file and make it unreadable (cross-platform approach)
        protected_file = workflow_dir / "protected.json"
        protected_file.write_text('{"name": "test"}')

        # Ensure caplog captures WARNING level logs from the context_builder module
        caplog.set_level("WARNING", logger="pflow.planning.context_builder")

        try:
            # Make file unreadable - handle platform differences
            if os.name != "nt":  # Unix-like systems
                protected_file.chmod(0o000)
            else:  # Windows - simulate permission error differently
                # On Windows, we'll mock the file reading to simulate permission error
                original_read_text = Path.read_text

                def mock_read_text(self, *args, **kwargs):
                    if self.name == "protected.json":
                        raise PermissionError("Permission denied")
                    return original_read_text(self, *args, **kwargs)

                with patch.object(Path, "read_text", mock_read_text):
                    workflows = _load_saved_workflows()
                    assert len(workflows) == 0
                    assert "Permission denied reading protected.json" in caplog.text
                return  # Skip the Unix-specific part

            # Unix-specific permission test
            workflows = _load_saved_workflows()
            assert len(workflows) == 0
            assert "Permission denied reading protected.json" in caplog.text

        finally:
            # Restore permissions for cleanup
            if os.name != "nt":
                protected_file.chmod(0o644)

    def test_handles_directory_creation_failure_gracefully(self, tmp_path, monkeypatch, caplog):
        """Test handling when directory creation fails due to permissions.

        This test works across platforms by mocking the directory creation failure.
        """
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Ensure caplog captures WARNING level logs from the context_builder module
        caplog.set_level("WARNING", logger="pflow.planning.context_builder")

        # Simulate directory creation failure using mocking
        # This is appropriate here because we're testing error handling, not filesystem behavior
        with patch("os.makedirs", side_effect=PermissionError("No permission")):
            workflows = _load_saved_workflows()

            # Should handle the error gracefully
            assert workflows == []
            assert "Failed to create workflow directory" in caplog.text

    def test_preserves_all_workflow_fields(self, tmp_path, monkeypatch):
        """Test that all workflow fields are preserved, not just required ones."""
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create workflow directory
        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        # Create workflow with all possible fields
        full_workflow = {
            "name": "full-workflow",
            "description": "A complete workflow",
            "ir": {"nodes": []},
            "ir_version": "0.1.0",
            "version": "2.0.0",
            "tags": ["example", "complete"],
            "created_at": "2024-01-15T10:30:00Z",
            "updated_at": "2024-01-15T14:45:00Z",
            "custom_field": "preserved",  # Even non-standard fields
        }

        workflow_file = workflow_dir / "full-workflow.json"
        workflow_file.write_text(json.dumps(full_workflow, indent=2))

        # Load workflows
        workflows = _load_saved_workflows()

        assert len(workflows) == 1
        loaded = workflows[0]

        # All fields should be preserved
        assert loaded["name"] == "full-workflow"
        assert loaded["ir_version"] == "0.1.0"
        assert loaded["version"] == "2.0.0"
        assert loaded["tags"] == ["example", "complete"]
        assert loaded["created_at"] == "2024-01-15T10:30:00Z"
        assert loaded["updated_at"] == "2024-01-15T14:45:00Z"
        assert loaded["custom_field"] == "preserved"


class TestWorkflowLoadingIntegration:
    """Integration tests for workflow loading with context building.

    These tests validate end-to-end behavior of workflow loading in context building scenarios.
    """

    def test_workflow_loading_integrates_with_discovery_context(self, tmp_path, monkeypatch):
        """Test workflow loading works correctly with discovery context building."""

        # Setup temporary home with workflows
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        # Create test workflows
        workflow1 = {"name": "data-processor", "description": "Process data files", "ir": {"nodes": [], "edges": []}}
        workflow2 = {
            "name": "report-generator",
            "description": "Generate reports from data",
            "ir": {"nodes": [], "edges": []},
        }

        (workflow_dir / "data-processor.json").write_text(json.dumps(workflow1))
        (workflow_dir / "report-generator.json").write_text(json.dumps(workflow2))

        # Mock _load_saved_workflows to use our test data
        with patch("pflow.planning.context_builder._load_saved_workflows", return_value=[workflow1, workflow2]):
            # Test discovery context includes loaded workflows
            context = build_discovery_context(registry_metadata={})

        assert "## Available Workflows" in context
        assert "data-processor (workflow)" in context
        assert "report-generator (workflow)" in context
        assert "Process data files" in context
        assert "Generate reports from data" in context

    def test_workflow_loading_handles_mixed_valid_invalid_files(self, tmp_path, monkeypatch, caplog):
        """Test workflow loading gracefully handles mixed valid and invalid files."""
        # Setup temporary home with mixed files
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        # Create valid workflow
        valid_workflow = {
            "name": "valid-workflow",
            "description": "This workflow is valid",
            "ir": {"nodes": [], "edges": []},
        }
        (workflow_dir / "valid.json").write_text(json.dumps(valid_workflow))

        # Create invalid JSON file
        (workflow_dir / "invalid.json").write_text("{invalid json}")

        # Create workflow missing required fields
        (workflow_dir / "incomplete.json").write_text(json.dumps({"name": "incomplete"}))

        # Create non-JSON file
        (workflow_dir / "readme.txt").write_text("This is not a workflow")

        # Ensure caplog captures WARNING level logs from the context_builder module
        caplog.set_level("WARNING", logger="pflow.planning.context_builder")

        # Load workflows
        workflows = _load_saved_workflows()

        # Should only load the valid workflow
        assert len(workflows) == 1
        assert workflows[0]["name"] == "valid-workflow"

        # Should log appropriate warnings for invalid files
        assert "Failed to parse JSON from invalid.json" in caplog.text
        assert "missing required fields" in caplog.text


class TestLLMPlanningIntegration:
    """Tests for LLM integration in planning system.

    These tests provide the foundation for testing LLM-based planning functionality.
    """

    def test_context_building_provides_llm_ready_format(self):
        """Test that context building produces format suitable for LLM consumption."""

        # Mock minimal registry for testing
        registry_metadata = {
            "simple-node": {
                "module": "pflow.nodes.simple",
                "class_name": "SimpleNode",
                "file_path": "src/pflow/nodes/simple.py",
                "interface": {
                    "description": "A simple test node",
                    "inputs": [{"key": "input_data", "type": "str", "description": "Input data"}],
                    "outputs": [{"key": "output_data", "type": "str", "description": "Processed data"}],
                    "params": [{"key": "param1", "type": "bool", "description": "A parameter"}],
                    "actions": ["default"],
                },
            }
        }

        # Mock workflow data
        workflow = {"name": "test-workflow", "description": "Test workflow for LLM", "ir": {"nodes": [], "edges": []}}

        # Mock _load_saved_workflows to return our test workflow
        with patch("pflow.planning.context_builder._load_saved_workflows", return_value=[workflow]):
            # Test discovery context format
            discovery_context = build_discovery_context(registry_metadata=registry_metadata)

        # Should be well-structured markdown suitable for LLM
        assert discovery_context.startswith("## Available Nodes")
        assert "simple-node" in discovery_context
        assert "A simple test node" in discovery_context
        assert "## Available Workflows" in discovery_context
        assert "test-workflow (workflow)" in discovery_context

    def test_planning_context_structure_supports_llm_workflow_generation(self):
        """Test that planning context structure supports LLM workflow generation.

        This test demonstrates how the context structure is suitable for LLM integration.
        """
        # Test registry for context
        registry_metadata = {
            "simple-node": {
                "module": "pflow.nodes.simple",
                "class_name": "SimpleNode",
                "file_path": "src/pflow/nodes/simple.py",
                "interface": {
                    "description": "A simple test node",
                    "inputs": [{"key": "input_data", "type": "str"}],
                    "outputs": [{"key": "output_data", "type": "str"}],
                    "params": [{"key": "param1", "type": "bool"}],
                    "actions": ["default"],
                },
            }
        }

        # Build planning context (this would be sent to LLM)
        planning_context = build_planning_context(
            selected_node_ids=["simple-node"],
            selected_workflow_names=[],
            registry_metadata=registry_metadata,
            saved_workflows=[],
        )

        # Verify the context contains the information needed for LLM workflow generation
        assert isinstance(planning_context, str)
        assert "simple-node" in planning_context
        assert "param1" in planning_context
        assert "bool" in planning_context
        # New format: all parameters in one section, clearer output access
        assert "**Parameters**:" in planning_context
        assert "**Outputs**:" in planning_context
        # Note: Removed universal example generation as it was deemed unnecessary

        # Context should be well-structured markdown
        assert planning_context.startswith("## Selected Components")

        # Simulate how an LLM would parse this context
        # The context contains structured information about:
        # - Node descriptions
        # - Input/output types and descriptions
        # - Parameter types and descriptions
        # - This enables LLM to generate valid workflow IR
        assert "A simple test node" in planning_context
        assert "input_data" in planning_context
        assert "output_data" in planning_context
