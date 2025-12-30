"""Test DeleteFileNode functionality."""

import os
import tempfile

import pytest

from src.pflow.nodes.file import DeleteFileNode


class TestDeleteFileNode:
    """Test DeleteFileNode functionality."""

    def test_successful_delete(self):
        """Test successful file deletion with confirmation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w") as f:
                f.write("Test content")

            node = DeleteFileNode()
            node.set_params({"file_path": file_path})
            shared = {"confirm_delete": True}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert "deleted" in shared
            # Check semantic meaning rather than exact string
            success_msg = shared["deleted"]
            assert "delet" in success_msg.lower()  # Covers "delete" or "deleted"
            assert file_path in success_msg  # Shows actual file path

            # Verify file no longer exists
            assert not os.path.exists(file_path)

    def test_delete_without_confirmation(self):
        """Test delete fails without confirmation as a safety feature.

        FIX HISTORY:
        - Removed dual testing approach (exception testing + behavior testing)
        - Fixed string assertion fragility with semantic checking
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w") as f:
                f.write("Test content")

            node = DeleteFileNode()
            node.set_params({"file_path": file_path})
            shared = {"confirm_delete": False}

            # BEHAVIOR: Should fail for safety and preserve file
            action = node.run(shared)

            assert action == "error"
            error_msg = shared["error"]
            # Check semantic meaning rather than exact string
            assert "confirm" in error_msg.lower() or "confirmation" in error_msg.lower()

            # BEHAVIOR: File should remain untouched
            assert os.path.exists(file_path)

    def test_delete_missing_confirmation_flag(self):
        """Test delete fails when confirmation flag is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w") as f:
                f.write("Test content")

            node = DeleteFileNode()
            node.set_params({"file_path": file_path})
            shared = {}  # No confirm_delete

            with pytest.raises(ValueError, match="Missing required 'confirm_delete'"):
                node.prep(shared)

    def test_delete_nonexistent_file(self):
        """Test delete succeeds for non-existent file (idempotent)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "missing.txt")

            node = DeleteFileNode()
            node.set_params({"file_path": file_path})
            shared = {"confirm_delete": True}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert "deleted" in shared
            # Check semantic meaning - operation succeeded even though file was missing
            success_msg = shared["deleted"]
            assert (
                "not exist" in success_msg.lower()
                or "already" in success_msg.lower()
                or "missing" in success_msg.lower()
            )
            assert file_path in success_msg  # Shows which file was checked

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
