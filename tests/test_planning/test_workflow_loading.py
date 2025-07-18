"""Tests for workflow loading functionality in context builder."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.planning.context_builder import _load_saved_workflows


class TestWorkflowLoading:
    """Test suite for _load_saved_workflows function."""

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
            "inputs": ["input1", "input2"],
            "outputs": ["output1"],
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
        assert workflows[0]["inputs"] == ["input1", "input2"]
        assert workflows[0]["outputs"] == ["output1"]
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
                "inputs": [f"input{i}"],
                "outputs": [f"output{i}"],
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
            "inputs": [],
            "outputs": [],
            "ir": {"nodes": []},
        }
        valid_file = workflow_dir / "valid.json"
        valid_file.write_text(json.dumps(valid_workflow))

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
        missing_name = {"description": "Missing name", "inputs": [], "outputs": [], "ir": {}}
        (workflow_dir / "missing-name.json").write_text(json.dumps(missing_name))

        # Create workflow missing 'ir' field
        missing_ir = {"name": "missing-ir", "description": "Missing IR", "inputs": [], "outputs": []}
        (workflow_dir / "missing-ir.json").write_text(json.dumps(missing_ir))

        # Create valid workflow
        valid = {"name": "valid", "description": "Valid", "inputs": [], "outputs": [], "ir": {}}
        (workflow_dir / "valid.json").write_text(json.dumps(valid))

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
        wrong_inputs = {
            "name": "wrong-inputs",
            "description": "Wrong inputs type",
            "inputs": "should be a list",  # Wrong type
            "outputs": [],
            "ir": {},
        }
        (workflow_dir / "wrong-inputs.json").write_text(json.dumps(wrong_inputs))

        # Create workflow with wrong type for 'ir' (should be dict)
        wrong_ir = {
            "name": "wrong-ir",
            "description": "Wrong ir type",
            "inputs": [],
            "outputs": [],
            "ir": [],  # Wrong type
        }
        (workflow_dir / "wrong-ir.json").write_text(json.dumps(wrong_ir))

        # Load workflows
        workflows = _load_saved_workflows()

        # Should not load any
        assert len(workflows) == 0

        # Should log warnings
        assert "Invalid 'inputs' type in wrong-inputs.json: expected list" in caplog.text
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
        valid_workflow = {"name": "valid", "description": "Valid", "inputs": [], "outputs": [], "ir": {}}
        (workflow_dir / "valid.json").write_text(json.dumps(valid_workflow))

        # Load workflows
        workflows = _load_saved_workflows()

        # Should only load the valid JSON file
        assert len(workflows) == 1
        assert workflows[0]["name"] == "valid"

    @pytest.mark.skipif(os.name == "nt", reason="Permission tests unreliable on Windows")
    def test_handles_permission_error(self, tmp_path, monkeypatch, caplog):
        """Test handling of permission errors when reading files."""
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create workflow directory
        workflow_dir = fake_home / ".pflow" / "workflows"
        workflow_dir.mkdir(parents=True)

        # Create a file and make it unreadable
        protected_file = workflow_dir / "protected.json"
        protected_file.write_text('{"name": "test"}')
        protected_file.chmod(0o000)

        try:
            # Load workflows
            workflows = _load_saved_workflows()

            # Should return empty list and log warning
            assert len(workflows) == 0
            assert "Permission denied reading protected.json" in caplog.text
        finally:
            # Restore permissions for cleanup
            protected_file.chmod(0o644)

    def test_handles_directory_creation_failure(self, tmp_path, monkeypatch, caplog):
        """Test handling when directory creation fails."""
        # Setup temporary home
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Make parent directory read-only to prevent subdirectory creation
        fake_home.mkdir()
        pflow_dir = fake_home / ".pflow"
        pflow_dir.mkdir()

        # Make .pflow directory read-only on Unix
        if os.name != "nt":
            pflow_dir.chmod(0o444)

        try:
            # Mock os.makedirs to raise an exception
            with patch("os.makedirs", side_effect=PermissionError("No permission")):
                workflows = _load_saved_workflows()

                # Should return empty list
                assert workflows == []
                assert "Failed to create workflow directory" in caplog.text
        finally:
            # Restore permissions
            if os.name != "nt":
                pflow_dir.chmod(0o755)

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
            "inputs": ["input1"],
            "outputs": ["output1"],
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
