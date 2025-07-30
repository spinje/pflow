"""Tests for WorkflowManager."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.core.exceptions import WorkflowExistsError, WorkflowNotFoundError, WorkflowValidationError
from pflow.core.workflow_manager import WorkflowManager


@pytest.fixture
def temp_workflows_dir():
    """Create a temporary directory for workflows."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def workflow_manager(temp_workflows_dir):
    """Create a WorkflowManager with temporary directory."""
    return WorkflowManager(workflows_dir=temp_workflows_dir)


@pytest.fixture
def sample_ir():
    """Sample workflow IR for testing."""
    return {
        "ir_version": "0.1.0",
        "inputs": {"text": {"type": "str", "description": "Input text"}},
        "outputs": {"result": {"type": "str", "description": "Processed result"}},
        "nodes": [{"id": "node1", "type": "echo", "config": {"message": "Hello"}}],
        "edges": [],
    }


class TestWorkflowManager:
    """Test WorkflowManager functionality."""

    def test_init_creates_directory(self, temp_workflows_dir):
        """Test that initialization creates the workflows directory."""
        # Create subdirectory that doesn't exist
        workflows_dir = temp_workflows_dir / "subdir" / "workflows"
        assert not workflows_dir.exists()

        manager = WorkflowManager(workflows_dir=workflows_dir)
        assert workflows_dir.exists()
        # Compare resolved paths to handle symlinks
        assert manager.workflows_dir == workflows_dir.resolve()

    def test_init_default_directory(self):
        """Test default directory is ~/.pflow/workflows/."""
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            manager = WorkflowManager()
            expected_path = Path("~/.pflow/workflows").expanduser().resolve()
            assert manager.workflows_dir == expected_path
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_save_workflow(self, workflow_manager, sample_ir):
        """Test saving a workflow with metadata."""
        name = "test-workflow"
        description = "A test workflow"

        # Mock datetime to have consistent timestamps
        mock_time = "2025-01-29T10:00:00+00:00"
        with patch("pflow.core.workflow_manager.datetime") as mock_dt:
            mock_dt.now.return_value.isoformat.return_value = mock_time

            path = workflow_manager.save(name, sample_ir, description)

        # Verify file was created
        assert Path(path).exists()
        assert path == str(workflow_manager.workflows_dir / f"{name}.json")

        # Verify metadata structure
        with open(path) as f:
            saved_data = json.load(f)

        assert saved_data == {
            "name": name,
            "description": description,
            "ir": sample_ir,
            "created_at": mock_time,
            "updated_at": mock_time,
            "version": "1.0.0",
        }

    def test_save_workflow_no_description(self, workflow_manager, sample_ir):
        """Test saving a workflow without description."""
        name = "test-workflow"
        path = workflow_manager.save(name, sample_ir)

        with open(path) as f:
            saved_data = json.load(f)

        assert saved_data["description"] == ""

    def test_save_workflow_already_exists(self, workflow_manager, sample_ir):
        """Test error when saving workflow that already exists."""
        name = "existing-workflow"
        workflow_manager.save(name, sample_ir)

        with pytest.raises(WorkflowExistsError, match=f"Workflow '{name}' already exists"):
            workflow_manager.save(name, sample_ir)

    def test_save_workflow_invalid_name(self, workflow_manager, sample_ir):
        """Test validation of workflow names."""
        # Empty name
        with pytest.raises(WorkflowValidationError, match="Workflow name cannot be empty"):
            workflow_manager.save("", sample_ir)

        # Name too long
        with pytest.raises(WorkflowValidationError, match="cannot exceed 50 characters"):
            workflow_manager.save("a" * 51, sample_ir)

        # Name with path separator
        with pytest.raises(WorkflowValidationError, match="cannot contain path separators"):
            workflow_manager.save("my/workflow", sample_ir)

        # Name with invalid characters
        with pytest.raises(WorkflowValidationError, match="can only contain"):
            workflow_manager.save("my workflow!", sample_ir)

    def test_save_workflow_valid_names(self, workflow_manager, sample_ir):
        """Test that valid names are accepted."""
        valid_names = [
            "simple",
            "kebab-case-name",
            "snake_case_name",
            "with.dots",
            "MixedCase",
            "name123",
            "123name",
            "a-b_c.d",
        ]

        for name in valid_names:
            path = workflow_manager.save(name, sample_ir)
            assert Path(path).exists()

    def test_load_workflow(self, workflow_manager, sample_ir):
        """Test loading a workflow with metadata."""
        name = "load-test"
        description = "Load test workflow"

        # Save workflow
        workflow_manager.save(name, sample_ir, description)

        # Load it back
        loaded = workflow_manager.load(name)

        assert loaded["name"] == name
        assert loaded["description"] == description
        assert loaded["ir"] == sample_ir
        assert "created_at" in loaded
        assert "updated_at" in loaded
        assert loaded["version"] == "1.0.0"

    def test_load_workflow_not_found(self, workflow_manager):
        """Test error when loading non-existent workflow."""
        with pytest.raises(WorkflowNotFoundError, match="Workflow 'missing' not found"):
            workflow_manager.load("missing")

    def test_load_ir(self, workflow_manager, sample_ir):
        """Test loading just the IR from a workflow."""
        name = "ir-test"
        workflow_manager.save(name, sample_ir)

        loaded_ir = workflow_manager.load_ir(name)
        assert loaded_ir == sample_ir

    def test_load_ir_not_found(self, workflow_manager):
        """Test error when loading IR from non-existent workflow."""
        with pytest.raises(WorkflowNotFoundError):
            workflow_manager.load_ir("missing")

    def test_get_path(self, workflow_manager):
        """Test getting absolute path for a workflow."""
        name = "path-test"
        expected_path = str((workflow_manager.workflows_dir / f"{name}.json").resolve())

        assert workflow_manager.get_path(name) == expected_path

    def test_list_all_empty(self, workflow_manager):
        """Test listing workflows when directory is empty."""
        workflows = workflow_manager.list_all()
        assert workflows == []

    def test_list_all_multiple(self, workflow_manager, sample_ir):
        """Test listing multiple workflows."""
        # Save several workflows
        names = ["workflow-c", "workflow-a", "workflow-b"]
        for name in names:
            workflow_manager.save(name, sample_ir, f"Description for {name}")

        # List all
        workflows = workflow_manager.list_all()

        # Should be sorted by name
        assert len(workflows) == 3
        assert [w["name"] for w in workflows] == ["workflow-a", "workflow-b", "workflow-c"]

        # Each should have full metadata
        for workflow in workflows:
            assert "name" in workflow
            assert "description" in workflow
            assert "ir" in workflow
            assert "created_at" in workflow
            assert "updated_at" in workflow
            assert "version" in workflow

    def test_list_all_skip_invalid(self, workflow_manager, sample_ir):
        """Test that invalid files are skipped with warning."""
        # Save a valid workflow
        workflow_manager.save("valid", sample_ir)

        # Create an invalid JSON file
        invalid_path = workflow_manager.workflows_dir / "invalid.json"
        with open(invalid_path, "w") as f:
            f.write("not valid json")

        # List should skip invalid and return only valid
        with patch("logging.Logger.warning") as mock_warning:
            workflows = workflow_manager.list_all()

        assert len(workflows) == 1
        assert workflows[0]["name"] == "valid"
        mock_warning.assert_called_once()

    def test_exists(self, workflow_manager, sample_ir):
        """Test checking if workflow exists."""
        name = "exists-test"

        # Should not exist initially
        assert not workflow_manager.exists(name)

        # Save workflow
        workflow_manager.save(name, sample_ir)

        # Should exist now
        assert workflow_manager.exists(name)

    def test_delete_workflow(self, workflow_manager, sample_ir):
        """Test deleting a workflow."""
        name = "delete-test"

        # Save workflow
        path = workflow_manager.save(name, sample_ir)
        assert Path(path).exists()

        # Delete it
        workflow_manager.delete(name)
        assert not Path(path).exists()
        assert not workflow_manager.exists(name)

    def test_delete_workflow_not_found(self, workflow_manager):
        """Test error when deleting non-existent workflow."""
        with pytest.raises(WorkflowNotFoundError, match="Workflow 'missing' not found"):
            workflow_manager.delete("missing")

    def test_atomic_save(self, workflow_manager, sample_ir):
        """Test that save is atomic (no partial files on failure)."""
        name = "atomic-test"

        # Mock json.dump to fail
        with (
            patch("json.dump", side_effect=Exception("Write failed")),
            pytest.raises(WorkflowValidationError, match="Failed to save workflow"),
        ):
            workflow_manager.save(name, sample_ir)

        # No file should exist
        assert not workflow_manager.exists(name)

        # No temp files should remain
        temp_files = list(workflow_manager.workflows_dir.glob(f".{name}.*.tmp"))
        assert len(temp_files) == 0

    def test_concurrent_saves_to_same_workflow(self, workflow_manager):
        """Test that concurrent saves to the same workflow are properly handled.

        With the atomic save implementation using os.link(), only one thread
        should succeed in creating the workflow, and all others should get
        WorkflowExistsError.
        """
        import threading

        results = {"errors": [], "successes": 0}

        def save_workflow(name, index):
            try:
                ir = {"ir_version": "0.1.0", "nodes": [{"id": f"node_{index}"}]}
                workflow_manager.save(name, ir, f"Version {index}")
                results["successes"] += 1
            except WorkflowExistsError as e:
                results["errors"].append(e)

        # Start multiple threads trying to save the same workflow
        threads = []
        for i in range(5):
            t = threading.Thread(target=save_workflow, args=("concurrent-test", i))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # With atomic save, exactly one thread should succeed
        # This demonstrates that WorkflowManager is now thread-safe
        assert results["successes"] == 1  # Exactly one succeeded
        assert len(results["errors"]) == 4  # Four threads should fail with WorkflowExistsError
        assert workflow_manager.exists("concurrent-test")

        # The saved workflow should be valid and complete
        loaded = workflow_manager.load("concurrent-test")
        assert "nodes" in loaded["ir"]

        # Clean up for other tests
        workflow_manager.delete("concurrent-test")

    def test_file_permission_error(self, tmp_path):
        """Test handling of file permission errors."""
        import stat

        # Create read-only directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # Read + execute only

        workflow_manager = WorkflowManager(readonly_dir)

        # Should handle permission error gracefully
        with pytest.raises(PermissionError):
            workflow_manager.save("test", {"ir_version": "0.1.0", "nodes": []})

        # Restore permissions for cleanup
        readonly_dir.chmod(stat.S_IRWXU)

    def test_corrupted_workflow_file(self, workflow_manager, tmp_path, caplog):
        """Test handling of corrupted workflow files."""
        import logging

        # Create a corrupted JSON file
        corrupted_file = workflow_manager.workflows_dir / "corrupted.json"
        corrupted_file.write_text('{"name": "corrupted", "description": "test", "ir": {"nodes": [')  # Incomplete JSON

        # list_all should skip it with warning
        with caplog.at_level(logging.WARNING):
            workflows = workflow_manager.list_all()

        assert any("corrupted.json" in record.message for record in caplog.records)
        assert not any(w["name"] == "corrupted" for w in workflows)

        # load should fail with clear validation error
        with pytest.raises(WorkflowValidationError, match="Invalid JSON"):
            workflow_manager.load("corrupted")

    def test_large_workflow_performance(self, workflow_manager):
        """Test performance with large workflows."""
        import time

        # Create a large workflow with many nodes
        large_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": f"node_{i}", "type": "test", "params": {"data": "x" * 1000}} for i in range(100)],
            "edges": [{"from": f"node_{i}", "to": f"node_{i + 1}"} for i in range(99)],
        }

        # Save should complete in reasonable time
        start = time.time()
        workflow_manager.save("large-workflow", large_ir, "Large workflow test")
        save_time = time.time() - start
        assert save_time < 1.0  # Should save in under 1 second

        # Load should also be fast
        start = time.time()
        loaded = workflow_manager.load_ir("large-workflow")
        load_time = time.time() - start
        assert load_time < 0.1  # Should load in under 100ms

        # Verify integrity
        assert len(loaded["nodes"]) == 100
        assert len(loaded["edges"]) == 99

    def test_atomic_save_with_real_disk_failure(self, workflow_manager, tmp_path):
        """Test that atomic save doesn't leave partial files on real failures."""
        import os

        name = "atomic-test-failure"
        ir = {"ir_version": "0.1.0", "nodes": []}

        # Mock os.link to simulate disk failure during atomic link creation
        def failing_link(src, dst):
            # Delete the temp file to simulate it being lost
            os.unlink(src)
            raise OSError("Disk full")

        with (
            patch("os.link", side_effect=failing_link),
            pytest.raises(WorkflowValidationError, match="Failed to save workflow"),
        ):
            workflow_manager.save(name, ir)

        # No partial file should exist
        assert not (workflow_manager.workflows_dir / f"{name}.json").exists()
        assert not workflow_manager.exists(name)

    def test_disk_full_during_write(self, workflow_manager):
        """Test handling when disk is full during write operation."""
        name = "disk-full-test"
        ir = {"ir_version": "0.1.0", "nodes": [{"id": "test"}]}

        # Mock json.dump to simulate disk full error
        def failing_dump(*args, **kwargs):
            raise OSError("No space left on device")

        with (
            patch("json.dump", side_effect=failing_dump),
            pytest.raises(WorkflowValidationError, match="Failed to save workflow"),
        ):
            workflow_manager.save(name, ir)

        # No file should exist
        assert not workflow_manager.exists(name)

        # No temp files should remain
        temp_files = list(workflow_manager.workflows_dir.glob(f".{name}.*.tmp"))
        assert len(temp_files) == 0
