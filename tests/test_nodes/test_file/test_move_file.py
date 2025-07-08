"""Test MoveFileNode functionality."""

import os
import tempfile

import pytest

from src.pflow.nodes.file import MoveFileNode, NonRetriableError


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
            shared = {"source_path": source_path, "dest_path": dest_path}

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
            shared = {"source_path": source_path, "dest_path": dest_path}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert not os.path.exists(source_path)
            assert os.path.exists(dest_path)

    def test_move_overwrite_protection(self):
        """Test move fails when destination exists without overwrite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.txt")
            dest_path = os.path.join(tmpdir, "dest.txt")

            # Create both files
            with open(source_path, "w") as f:
                f.write("Source content")
            with open(dest_path, "w") as f:
                f.write("Existing content")

            node = MoveFileNode()
            shared = {"source_path": source_path, "dest_path": dest_path}

            prep_res = node.prep(shared)

            # Method 1: Test that exec raises NonRetriableError
            with pytest.raises(NonRetriableError):
                node.exec(prep_res)

            # Method 2: Test full lifecycle
            action = node.run(shared)
            assert action == "error"
            assert "already exists" in shared["error"]

            # Verify source still exists
            assert os.path.exists(source_path)
            # Verify destination wasn't overwritten
            with open(dest_path) as f:
                assert f.read() == "Existing content"

    def test_move_source_not_found(self):
        """Test error when source doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "missing.txt")
            dest_path = os.path.join(tmpdir, "dest.txt")

            node = MoveFileNode()
            shared = {"source_path": source_path, "dest_path": dest_path}

            prep_res = node.prep(shared)

            # Method 1: Test that exec raises FileNotFoundError
            with pytest.raises(FileNotFoundError):
                node.exec(prep_res)

            # Method 2: Test full lifecycle
            action = node.run(shared)
            assert action == "error"
            assert "does not exist" in shared["error"]
