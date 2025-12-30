"""Test CopyFileNode functionality."""

import os
import tempfile

from src.pflow.nodes.file import CopyFileNode


class TestCopyFileNode:
    """Test CopyFileNode functionality."""

    def test_successful_copy(self):
        """Test successful file copy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create source file
            source_path = os.path.join(tmpdir, "source.txt")
            with open(source_path, "w") as f:
                f.write("Test content")

            dest_path = os.path.join(tmpdir, "dest.txt")

            node = CopyFileNode()
            node.set_params({"source_path": source_path, "dest_path": dest_path})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert "copied" in shared
            assert "Successfully copied" in shared["copied"]

            # Verify both files exist
            assert os.path.exists(source_path)
            assert os.path.exists(dest_path)

            # Verify content matches
            with open(dest_path) as f:
                assert f.read() == "Test content"

    def test_copy_with_directory_creation(self):
        """Test copy creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.txt")
            with open(source_path, "w") as f:
                f.write("Test content")

            # Destination in non-existent subdirectory
            dest_path = os.path.join(tmpdir, "subdir", "nested", "dest.txt")

            node = CopyFileNode()
            node.set_params({"source_path": source_path, "dest_path": dest_path})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert os.path.exists(dest_path)

    def test_copy_overwrite_protection(self):
        """Test copy fails when destination exists without overwrite.

        FIX HISTORY:
        - Removed dual testing approach (exception testing + behavior testing)
        - Focus on behavior: what does user observe when copy is attempted?
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.txt")
            dest_path = os.path.join(tmpdir, "dest.txt")

            # Create both files
            with open(source_path, "w") as f:
                f.write("Source content")
            with open(dest_path, "w") as f:
                f.write("Existing content")

            node = CopyFileNode()
            node.set_params({"source_path": source_path, "dest_path": dest_path})
            shared = {}

            # BEHAVIOR: Copy should fail and preserve existing content
            action = node.run(shared)

            assert action == "error"
            assert "exists" in shared["error"].lower()

            # BEHAVIOR: Destination should not be overwritten
            with open(dest_path) as f:
                assert f.read() == "Existing content"

    def test_copy_with_overwrite(self):
        """Test copy succeeds with overwrite=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.txt")
            dest_path = os.path.join(tmpdir, "dest.txt")

            # Create both files
            with open(source_path, "w") as f:
                f.write("New content")
            with open(dest_path, "w") as f:
                f.write("Old content")

            node = CopyFileNode()
            node.set_params({"source_path": source_path, "dest_path": dest_path, "overwrite": True})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"

            # Verify destination was overwritten
            with open(dest_path) as f:
                assert f.read() == "New content"

    def test_copy_source_not_found(self):
        """Test behavior when source file doesn't exist.

        FIX HISTORY:
        - Removed dual testing approach (exception testing + behavior testing)
        - Focus on behavior: what error message does user receive?
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "missing.txt")
            dest_path = os.path.join(tmpdir, "dest.txt")

            node = CopyFileNode()
            node.set_params({"source_path": source_path, "dest_path": dest_path})
            shared = {}

            # BEHAVIOR: Should provide helpful error message
            action = node.run(shared)

            assert action == "error"
            assert "does not exist" in shared["error"]

            # BEHAVIOR: Destination should not be created
            assert not os.path.exists(dest_path)
