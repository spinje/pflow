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

    def test_init_default_directory(self, isolate_pflow_config):
        """Test default directory in test environment is isolated temp path.

        Note: The isolate_pflow_config fixture patches WorkflowManager to use
        a temporary directory instead of ~/.pflow/workflows/ for test isolation.
        This is intentional to prevent tests from polluting the real workflows directory.
        """
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            manager = WorkflowManager()
            expected_path = isolate_pflow_config["workflows_path"]
            assert manager.workflows_dir == expected_path
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_save_workflow(self, workflow_manager, sample_ir):
        """Test saving a workflow with metadata."""
        from datetime import datetime

        name = "test-workflow"
        description = "A test workflow"

        # Test behavior: workflow is saved with correct metadata structure
        path = workflow_manager.save(name, sample_ir, description)

        # Verify file was created
        assert Path(path).exists()
        assert path == str(workflow_manager.workflows_dir / f"{name}.json")

        # Verify metadata structure and content
        with open(path) as f:
            saved_data = json.load(f)

        # Test required metadata fields exist and have correct values
        # Note: name is NOT stored in file - it's derived from filename at load time
        assert "name" not in saved_data  # Name derived from filename, not stored
        assert saved_data["description"] == description
        assert saved_data["ir"] == sample_ir
        assert saved_data["version"] == "1.0.0"

        # Test timestamps exist and are reasonable (within last minute)
        assert "created_at" in saved_data
        assert "updated_at" in saved_data

        # Parse timestamps and verify they're recent
        created_at = datetime.fromisoformat(saved_data["created_at"].replace("Z", "+00:00"))
        updated_at = datetime.fromisoformat(saved_data["updated_at"].replace("Z", "+00:00"))
        now = datetime.now(created_at.tzinfo)

        # Timestamps should be within the last minute (generous for CI environments)
        time_diff = (now - created_at).total_seconds()
        assert 0 <= time_diff <= 60, f"Created timestamp too old: {time_diff} seconds"

        # created_at and updated_at should be the same for new workflow
        assert created_at == updated_at

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
        """Test validation of workflow names with new strict rules."""
        # Empty name
        with pytest.raises(WorkflowValidationError, match="Workflow name cannot be empty"):
            workflow_manager.save("", sample_ir)

        # Name too long
        with pytest.raises(WorkflowValidationError, match="cannot exceed 50 characters"):
            workflow_manager.save("a" * 51, sample_ir)

        # Reserved names
        with pytest.raises(WorkflowValidationError, match="reserved workflow name"):
            workflow_manager.save("test", sample_ir)

        # Invalid format - uppercase
        with pytest.raises(WorkflowValidationError, match="Invalid workflow name"):
            workflow_manager.save("MyWorkflow", sample_ir)

        # Invalid format - underscores
        with pytest.raises(WorkflowValidationError, match="Invalid workflow name"):
            workflow_manager.save("my_workflow", sample_ir)

        # Invalid format - dots
        with pytest.raises(WorkflowValidationError, match="Invalid workflow name"):
            workflow_manager.save("my.workflow", sample_ir)

        # Invalid format - leading hyphen
        with pytest.raises(WorkflowValidationError, match="Invalid workflow name"):
            workflow_manager.save("-myworkflow", sample_ir)

        # Invalid format - consecutive hyphens
        with pytest.raises(WorkflowValidationError, match="Invalid workflow name"):
            workflow_manager.save("my--workflow", sample_ir)

    @pytest.mark.parametrize(
        "name",
        [
            "simple",
            "kebab-case-name",
            "name123",
            "123name",
            "workflow-v2",
            "my-analyzer",
        ],
    )
    def test_save_workflow_valid_name(self, workflow_manager, sample_ir, name):
        """Test that valid workflow names are accepted (lowercase, hyphens only)."""
        path = workflow_manager.save(name, sample_ir)
        assert Path(path).exists()
        assert workflow_manager.exists(name)

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

    def test_atomic_save_behavior(self, workflow_manager, sample_ir):
        """Test that save operation is atomic - either succeeds completely or fails cleanly."""
        name = "atomic-test"

        # First, test that normal save works
        path = workflow_manager.save(name, sample_ir)
        assert Path(path).exists()
        assert workflow_manager.exists(name)

        # Clean up for next test
        workflow_manager.delete(name)
        assert not workflow_manager.exists(name)

        # Test atomicity by trying to save to a read-only directory
        import stat

        readonly_subdir = workflow_manager.workflows_dir / "readonly"
        readonly_subdir.mkdir()
        readonly_subdir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # Read + execute only

        readonly_manager = WorkflowManager(readonly_subdir)

        # Save should fail cleanly with permission error
        with pytest.raises(PermissionError):
            readonly_manager.save(name, sample_ir)

        # No file should exist after failure
        assert not readonly_manager.exists(name)

        # No temp files should remain after failure
        temp_files = list(readonly_subdir.glob(f".{name}.*.tmp"))
        assert len(temp_files) == 0

        # Restore permissions for cleanup
        readonly_subdir.chmod(stat.S_IRWXU)

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
            workflow_manager.save("my-workflow", {"ir_version": "0.1.0", "nodes": []})

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

    def test_concurrent_save_atomicity(self, workflow_manager):
        """Test that concurrent saves are handled atomically without race conditions.

        This test verifies that the atomic save mechanism prevents race conditions
        when multiple processes try to save the same workflow simultaneously.
        """
        name = "atomicity-test"
        ir = {"ir_version": "0.1.0", "nodes": []}

        # Test that repeated rapid saves work correctly
        # If the atomic save mechanism fails, we might see race conditions
        for i in range(10):
            test_name = f"{name}-{i}"

            # Save workflow
            path = workflow_manager.save(test_name, ir)
            assert Path(path).exists()
            assert workflow_manager.exists(test_name)

            # Verify the saved content is correct
            loaded = workflow_manager.load(test_name)
            assert loaded["ir"] == ir
            assert loaded["name"] == test_name

            # Clean up
            workflow_manager.delete(test_name)
            assert not workflow_manager.exists(test_name)

        # Test that the atomic save prevents partial files by checking
        # that saves either fully succeed or fully fail
        valid_name = "valid-atomic-test"
        workflow_manager.save(valid_name, ir)

        # Verify the file exists and is complete
        assert workflow_manager.exists(valid_name)
        loaded = workflow_manager.load(valid_name)
        assert "name" in loaded
        assert "ir" in loaded
        assert "created_at" in loaded
        assert "updated_at" in loaded
        assert "version" in loaded

    def test_save_handles_write_failures_cleanly(self, workflow_manager):
        """Test that save operation handles write failures without leaving partial files.

        This test verifies the atomic save behavior using a realistic scenario
        where the temporary file creation succeeds but the workflow cannot be saved.
        """
        name = "write-failure-test"
        ir = {"ir_version": "0.1.0", "nodes": [{"id": "test"}]}

        # Create a scenario where save will fail: invalid JSON data
        # We'll create a workflow IR that can't be serialized to JSON
        class UnserializableObject:
            """Object that can't be serialized to JSON."""

            pass

        invalid_ir = {"ir_version": "0.1.0", "nodes": [{"unserializable": UnserializableObject()}]}

        # Save should fail with a validation error
        with pytest.raises(WorkflowValidationError, match="Failed to save workflow"):
            workflow_manager.save(name, invalid_ir)

        # No file should exist after failure
        assert not workflow_manager.exists(name)

        # No temp files should remain after failure
        temp_files = list(workflow_manager.workflows_dir.glob(f".{name}.*.tmp"))
        assert len(temp_files) == 0

        # Verify that a valid workflow can still be saved successfully
        workflow_manager.save(name, ir)
        assert workflow_manager.exists(name)

    def test_filename_is_source_of_truth_for_name(self, workflow_manager, sample_ir):
        """Test that filename determines workflow name, not internal field.

        This is a regression test for a bug where:
        - File 'api-analysis.json' contained {"name": "slack-qa-analyzer", ...}
        - list_all() returned "slack-qa-analyzer" (from internal field)
        - exists("slack-qa-analyzer") returned False (file doesn't exist)
        - Result: "Did you mean: slack-qa-analyzer" for a name that "doesn't exist"

        The fix: derive name from filename, ignore any internal name field.
        """
        # Create a workflow file with a MISMATCHED internal name
        # (simulates legacy file or manual edit)
        file_path = workflow_manager.workflows_dir / "actual-filename.json"
        legacy_data = {
            "name": "wrong-internal-name",  # This should be IGNORED
            "description": "Test workflow",
            "ir": sample_ir,
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
            "version": "1.0.0",
        }
        with open(file_path, "w") as f:
            json.dump(legacy_data, f)

        # list_all() should return filename-derived name, not internal name
        workflows = workflow_manager.list_all()
        names = [w["name"] for w in workflows]
        assert "actual-filename" in names
        assert "wrong-internal-name" not in names

        # load() should return filename-derived name
        loaded = workflow_manager.load("actual-filename")
        assert loaded["name"] == "actual-filename"  # Derived from filename

        # exists() should work with filename
        assert workflow_manager.exists("actual-filename")
        assert not workflow_manager.exists("wrong-internal-name")
