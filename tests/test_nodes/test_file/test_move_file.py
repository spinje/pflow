"""Test MoveFileNode functionality."""

import os
import tempfile

from src.pflow.nodes.file import MoveFileNode


class TestMoveFileNode:
    """Test MoveFileNode functionality."""

    def test_successful_move(self):
        """Test successful file move."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create source file
            source_path = os.path.join(tmpdir, "source.txt")
            with open(source_path, "w") as f:
                f.write("Test content")

            dest_path = os.path.join(tmpdir, "dest.txt")

            node = MoveFileNode()
            node.set_params({"source_path": source_path, "dest_path": dest_path})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert "moved" in shared
            assert "Successfully moved" in shared["moved"]

            # Verify source no longer exists
            assert not os.path.exists(source_path)
            # Verify destination exists
            assert os.path.exists(dest_path)

            # Verify content
            with open(dest_path) as f:
                assert f.read() == "Test content"

    def test_move_with_directory_creation(self):
        """Test move creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.txt")
            with open(source_path, "w") as f:
                f.write("Test content")

            # Destination in non-existent subdirectory
            dest_path = os.path.join(tmpdir, "subdir", "nested", "dest.txt")

            node = MoveFileNode()
            node.set_params({"source_path": source_path, "dest_path": dest_path})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert not os.path.exists(source_path)
            assert os.path.exists(dest_path)

    def test_move_overwrite_protection(self):
        """Test move fails when destination exists without overwrite.

        FIX HISTORY:
        - Removed dual testing approach (exception testing + behavior testing)
        - Focus on behavior: what happens when move is attempted with existing destination?
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.txt")
            dest_path = os.path.join(tmpdir, "dest.txt")

            # Create both files
            with open(source_path, "w") as f:
                f.write("Source content")
            with open(dest_path, "w") as f:
                f.write("Existing content")

            node = MoveFileNode()
            node.set_params({"source_path": source_path, "dest_path": dest_path})
            shared = {}

            # BEHAVIOR: Move should fail and preserve both files
            action = node.run(shared)

            assert action == "error"
            assert "exists" in shared["error"].lower()

            # BEHAVIOR: Source should remain untouched
            assert os.path.exists(source_path)
            with open(source_path) as f:
                assert f.read() == "Source content"

            # BEHAVIOR: Destination should not be overwritten
            with open(dest_path) as f:
                assert f.read() == "Existing content"

    def test_move_source_not_found(self):
        """Test behavior when source file doesn't exist.

        FIX HISTORY:
        - Removed dual testing approach (exception testing + behavior testing)
        - Focus on behavior: what error message does user receive?
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "missing.txt")
            dest_path = os.path.join(tmpdir, "dest.txt")

            node = MoveFileNode()
            node.set_params({"source_path": source_path, "dest_path": dest_path})
            shared = {}

            # BEHAVIOR: Should provide helpful error message
            action = node.run(shared)

            assert action == "error"
            assert "does not exist" in shared["error"]

            # BEHAVIOR: Destination should not be created
            assert not os.path.exists(dest_path)
