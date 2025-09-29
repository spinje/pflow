"""Tests for WorkflowManager.update_ir() method."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.core.workflow_manager import WorkflowManager, WorkflowNotFoundError, WorkflowValidationError


@pytest.fixture
def workflow_manager():
    """Create a WorkflowManager with a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        wm = WorkflowManager()
        wm.workflows_dir = Path(tmpdir)
        yield wm


@pytest.fixture
def sample_workflow():
    """Sample workflow data with metadata."""
    return {
        "name": "test-workflow",
        "description": "Test workflow for testing",
        "created_at": "2024-01-01T10:00:00Z",
        "updated_at": "2024-01-01T10:00:00Z",
        "execution_count": 5,
        "last_execution_timestamp": "2024-01-01T11:00:00Z",
        "last_execution_success": True,
        "average_duration_ms": 1234.5,
        "ir": {
            "ir_version": "1.0",
            "nodes": [{"id": "old-node", "type": "echo", "params": {"message": "Old message"}}],
            "edges": [],
        },
    }


@pytest.fixture
def new_ir():
    """New IR to replace the existing one."""
    return {
        "ir_version": "1.0",
        "nodes": [
            {"id": "new-node", "type": "echo", "params": {"message": "New repaired message"}},
            {"id": "another-node", "type": "echo", "params": {"message": "Additional node"}},
        ],
        "edges": [{"from": "new-node", "to": "another-node"}],
    }


class TestWorkflowManagerUpdateIR:
    """Test the update_ir method of WorkflowManager."""

    def test_update_ir_success(self, workflow_manager, sample_workflow, new_ir):
        """Test successful IR update preserves metadata."""
        # Create the workflow file
        workflow_file = workflow_manager.workflows_dir / "test-workflow.json"
        with open(workflow_file, "w") as f:
            json.dump(sample_workflow, f, indent=2)

        # Update the IR
        with patch("pflow.core.workflow_manager.datetime") as mock_dt:
            mock_dt.now.return_value.isoformat.return_value = "2024-01-02T12:00:00Z"
            workflow_manager.update_ir("test-workflow", new_ir)

        # Load and verify
        with open(workflow_file) as f:
            updated = json.load(f)

        # IR should be updated
        assert updated["ir"] == new_ir

        # Metadata should be preserved
        assert updated["name"] == "test-workflow"
        assert updated["description"] == "Test workflow for testing"
        assert updated["created_at"] == "2024-01-01T10:00:00Z"
        assert updated["execution_count"] == 5
        assert updated["last_execution_timestamp"] == "2024-01-01T11:00:00Z"
        assert updated["last_execution_success"] is True
        assert updated["average_duration_ms"] == 1234.5

        # Only updated_at should change
        assert updated["updated_at"] == "2024-01-02T12:00:00Z"

    def test_update_ir_workflow_not_found(self, workflow_manager, new_ir):
        """Test that updating non-existent workflow raises error."""
        with pytest.raises(WorkflowNotFoundError, match="Workflow 'nonexistent' does not exist"):
            workflow_manager.update_ir("nonexistent", new_ir)

    def test_update_ir_atomic_operation(self, workflow_manager, sample_workflow, new_ir):
        """Test that update is atomic using temp file."""
        # Create the workflow file
        workflow_file = workflow_manager.workflows_dir / "test-workflow.json"
        with open(workflow_file, "w") as f:
            json.dump(sample_workflow, f, indent=2)

        # Mock an error during write to test atomicity
        with patch("json.dump", side_effect=Exception("Write failed")), pytest.raises(WorkflowValidationError):
            workflow_manager.update_ir("test-workflow", new_ir)

        # Original file should remain unchanged
        with open(workflow_file) as f:
            data = json.load(f)
        assert data["ir"]["nodes"][0]["id"] == "old-node"

        # No temp files should remain
        temp_files = list(workflow_manager.workflows_dir.glob(".test-workflow.*.tmp"))
        assert len(temp_files) == 0

    def test_update_ir_preserves_formatting(self, workflow_manager, sample_workflow, new_ir):
        """Test that JSON formatting is preserved (2-space indent)."""
        # Create the workflow file
        workflow_file = workflow_manager.workflows_dir / "test-workflow.json"
        with open(workflow_file, "w") as f:
            json.dump(sample_workflow, f, indent=2)

        # Update the IR
        workflow_manager.update_ir("test-workflow", new_ir)

        # Check formatting
        content = workflow_file.read_text()
        # Should have 2-space indentation
        assert '  "name"' in content
        assert '    "id"' in content
        # Should be properly formatted JSON
        assert content.count("\n") > 10

    def test_update_ir_with_minimal_workflow(self, workflow_manager):
        """Test updating a workflow with minimal metadata."""
        minimal_workflow = {"name": "minimal", "ir": {"ir_version": "1.0", "nodes": [], "edges": []}}

        # Create the workflow file
        workflow_file = workflow_manager.workflows_dir / "minimal.json"
        with open(workflow_file, "w") as f:
            json.dump(minimal_workflow, f, indent=2)

        # Update with new IR
        new_ir = {"ir_version": "1.0", "nodes": [{"id": "test", "type": "echo", "params": {}}], "edges": []}

        workflow_manager.update_ir("minimal", new_ir)

        # Verify update
        with open(workflow_file) as f:
            updated = json.load(f)

        assert updated["ir"] == new_ir
        assert updated["name"] == "minimal"
        assert "updated_at" in updated

    def test_update_ir_handles_complex_ir(self, workflow_manager):
        """Test updating with complex nested IR structure."""
        # Create a workflow with simple IR
        simple_workflow = {"name": "complex-test", "ir": {"ir_version": "1.0", "nodes": [], "edges": []}}

        workflow_file = workflow_manager.workflows_dir / "complex-test.json"
        with open(workflow_file, "w") as f:
            json.dump(simple_workflow, f, indent=2)

        # Update with complex IR
        complex_ir = {
            "ir_version": "1.0",
            "nodes": [
                {
                    "id": "node1",
                    "type": "llm",
                    "params": {
                        "prompt": "Complex prompt with ${template.variables}",
                        "model": "gpt-4",
                        "temperature": 0.7,
                        "max_tokens": 1000,
                    },
                },
                {
                    "id": "node2",
                    "type": "mcp-tool",
                    "params": {
                        "server": "google-sheets",
                        "tool": "update",
                        "values": [["row1", "data1"], ["row2", "data2"]],
                        "sheet_id": "abc123",
                        "range": "A1:B10",
                    },
                },
            ],
            "edges": [{"from": "node1", "to": "node2", "condition": "success"}],
            "inputs": {"api_key": {"type": "string", "required": True}, "limit": {"type": "number", "default": 10}},
            "outputs": {"result": {"source": "${node2.result}"}},
        }

        workflow_manager.update_ir("complex-test", complex_ir)

        # Verify complex structure is preserved
        with open(workflow_file) as f:
            updated = json.load(f)

        assert updated["ir"] == complex_ir
        assert len(updated["ir"]["nodes"]) == 2
        assert updated["ir"]["nodes"][1]["params"]["values"] == [["row1", "data1"], ["row2", "data2"]]

    def test_update_ir_concurrent_safety(self, workflow_manager, sample_workflow, new_ir):
        """Test that concurrent updates don't corrupt the file."""
        import threading

        # Create the workflow file
        workflow_file = workflow_manager.workflows_dir / "concurrent-test.json"
        sample_workflow["name"] = "concurrent-test"
        with open(workflow_file, "w") as f:
            json.dump(sample_workflow, f, indent=2)

        # Create different IRs for concurrent updates
        ir1 = {"ir_version": "1.0", "nodes": [{"id": "update1", "type": "echo", "params": {}}], "edges": []}
        ir2 = {"ir_version": "1.0", "nodes": [{"id": "update2", "type": "echo", "params": {}}], "edges": []}

        errors = []

        def update_workflow(ir_data):
            try:
                workflow_manager.update_ir("concurrent-test", ir_data)
            except Exception as e:
                errors.append(e)

        # Run concurrent updates
        t1 = threading.Thread(target=update_workflow, args=(ir1,))
        t2 = threading.Thread(target=update_workflow, args=(ir2,))

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        # Should have no errors
        assert len(errors) == 0

        # File should be valid JSON
        with open(workflow_file) as f:
            final_data = json.load(f)

        # Should have one of the IRs (atomic replacement ensures no corruption)
        assert final_data["ir"] in [ir1, ir2]

    def test_update_ir_permission_error(self, workflow_manager, sample_workflow, new_ir):
        """Test handling of permission errors."""
        # Create the workflow file
        workflow_file = workflow_manager.workflows_dir / "readonly-test.json"
        with open(workflow_file, "w") as f:
            json.dump(sample_workflow, f, indent=2)

        # Make directory read-only to prevent temp file creation
        workflow_manager.workflows_dir.chmod(0o555)

        try:
            with pytest.raises(WorkflowValidationError, match="Failed to update workflow IR"):
                workflow_manager.update_ir("readonly-test", new_ir)
        finally:
            # Restore permissions for cleanup
            workflow_manager.workflows_dir.chmod(0o755)

    def test_update_ir_with_exists_check(self, workflow_manager, sample_workflow, new_ir):
        """Test that exists() method works correctly with update_ir."""
        # Should not exist initially
        assert not workflow_manager.exists("test-workflow")

        # Try to update non-existent workflow
        with pytest.raises(WorkflowNotFoundError):
            workflow_manager.update_ir("test-workflow", new_ir)

        # Create the workflow
        workflow_file = workflow_manager.workflows_dir / "test-workflow.json"
        with open(workflow_file, "w") as f:
            json.dump(sample_workflow, f, indent=2)

        # Now should exist
        assert workflow_manager.exists("test-workflow")

        # Update should work
        workflow_manager.update_ir("test-workflow", new_ir)

        # Should still exist
        assert workflow_manager.exists("test-workflow")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
