"""Test DeleteFileNode functionality."""

import os
import tempfile

import pytest

from src.pflow.nodes.file import DeleteFileNode, NonRetriableError


class TestDeleteFileNode:
    """Test DeleteFileNode functionality."""

    def test_successful_delete(self):
        """Test successful file deletion with confirmation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w") as f:
                f.write("Test content")

            node = DeleteFileNode()
            shared = {"file_path": file_path, "confirm_delete": True}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert "deleted" in shared
            assert "Successfully deleted" in shared["deleted"]

            # Verify file no longer exists
            assert not os.path.exists(file_path)

    def test_delete_without_confirmation(self):
        """Test delete fails without confirmation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w") as f:
                f.write("Test content")

            node = DeleteFileNode()
            shared = {"file_path": file_path, "confirm_delete": False}

            prep_res = node.prep(shared)

            # Method 1: Test that exec raises NonRetriableError
            with pytest.raises(NonRetriableError):
                node.exec(prep_res)

            # Method 2: Test full lifecycle
            action = node.run(shared)
            assert action == "error"
            assert "not confirmed" in shared["error"]

            # Verify file still exists
            assert os.path.exists(file_path)

    def test_delete_missing_confirmation_flag(self):
        """Test delete fails when confirmation flag is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w") as f:
                f.write("Test content")

            node = DeleteFileNode()
            shared = {"file_path": file_path}  # No confirm_delete

            with pytest.raises(ValueError, match="Missing required 'confirm_delete'"):
                node.prep(shared)

    def test_delete_nonexistent_file(self):
        """Test delete succeeds for non-existent file (idempotent)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "missing.txt")

            node = DeleteFileNode()
            shared = {"file_path": file_path, "confirm_delete": True}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert "deleted" in shared
            assert "did not exist" in shared["deleted"]

    def test_delete_with_params_safety(self):
        """Test that confirm_delete cannot come from params."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w") as f:
                f.write("Test content")

            node = DeleteFileNode()
            node.set_params({"file_path": file_path, "confirm_delete": True})
            shared = {}  # Empty shared store

            # Should fail because confirm_delete must be in shared
            with pytest.raises(ValueError, match="Missing required 'confirm_delete'"):
                node.prep(shared)
