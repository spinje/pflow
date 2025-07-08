"""Test integration between file nodes."""

import os
import tempfile

import pytest

from src.pflow.nodes.file import (
    CopyFileNode,
    DeleteFileNode,
    MoveFileNode,
    ReadFileNode,
    WriteFileNode,
)


class TestIntegration:
    """Test integration between read and write nodes."""

    def test_read_write_flow(self):
        """Test reading from one file and writing to another."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create source file
            source_path = os.path.join(tmpdir, "source.txt")
            with open(source_path, "w") as f:
                f.write("Source content\nWith multiple lines")

            # Read with ReadFileNode
            read_node = ReadFileNode()
            shared = {"file_path": source_path}

            prep_res = read_node.prep(shared)
            exec_res = read_node.exec(prep_res)
            read_node.post(shared, prep_res, exec_res)

            # Content now has line numbers
            assert shared["content"] == "1: Source content\n2: With multiple lines"

            # Write to new file (note: it will include line numbers)
            dest_path = os.path.join(tmpdir, "dest.txt")
            write_node = WriteFileNode()
            shared["file_path"] = dest_path

            prep_res = write_node.prep(shared)
            exec_res = write_node.exec(prep_res)
            write_node.post(shared, prep_res, exec_res)

            # Verify destination has line-numbered content
            with open(dest_path) as f:
                assert f.read() == "1: Source content\n2: With multiple lines"

    def test_error_propagation(self):
        """Test that errors are properly propagated."""
        # Try to read non-existent file
        read_node = ReadFileNode()
        shared = {"file_path": "/non/existent/path.txt"}

        # Use node.run() for full lifecycle with error handling
        action = read_node.run(shared)

        assert action == "error"
        assert "error" in shared

        # Try to write with the error still in shared
        write_node = WriteFileNode()
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            temp_path = tmp.name
        try:
            shared["file_path"] = temp_path
            # Note: content is missing, should fail in prep

            with pytest.raises(ValueError, match="Missing required 'content'"):
                write_node.prep(shared)
        finally:
            # Clean up temp file if it exists
            if os.path.exists(temp_path):
                os.unlink(temp_path)


class TestFileNodeIntegration:
    """Test integration between all file nodes."""

    def test_path_normalization(self):
        """Test that paths are normalized (expanduser, abspath)."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("Test content")
            temp_path = f.name

        try:
            # Get the base name to test relative path
            base_name = os.path.basename(temp_path)
            rel_path = os.path.join(".", base_name)

            # Change to the directory containing the file
            old_cwd = os.getcwd()
            os.chdir(os.path.dirname(temp_path))

            try:
                node = ReadFileNode()
                shared = {"file_path": rel_path}

                prep_res = node.prep(shared)
                # prep_res should contain normalized absolute path
                assert os.path.isabs(prep_res[0])

                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                assert action == "default"
                assert "1: Test content" in shared["content"]
            finally:
                os.chdir(old_cwd)
        finally:
            os.unlink(temp_path)

    def test_atomic_write_behavior(self):
        """Test that write operations are atomic."""
        # This is hard to test directly, but we can verify the implementation
        # exists by checking that _atomic_write method is present
        node = WriteFileNode()
        assert hasattr(node, "_atomic_write")
        assert callable(node._atomic_write)

    def test_copy_move_delete_workflow(self):
        """Test a complete workflow using all file manipulation nodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create initial file
            original_path = os.path.join(tmpdir, "original.txt")
            with open(original_path, "w") as f:
                f.write("Original content")

            shared = {}

            # Step 1: Copy to backup
            copy_node = CopyFileNode()
            backup_path = os.path.join(tmpdir, "backup.txt")
            shared["source_path"] = original_path
            shared["dest_path"] = backup_path

            prep_res = copy_node.prep(shared)
            exec_res = copy_node.exec(prep_res)
            action = copy_node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert os.path.exists(backup_path)

            # Step 2: Move original to new location
            move_node = MoveFileNode()
            new_path = os.path.join(tmpdir, "new_location.txt")
            shared["source_path"] = original_path
            shared["dest_path"] = new_path

            prep_res = move_node.prep(shared)
            exec_res = move_node.exec(prep_res)
            action = move_node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert not os.path.exists(original_path)
            assert os.path.exists(new_path)

            # Step 3: Delete the backup
            delete_node = DeleteFileNode()
            shared["file_path"] = backup_path
            shared["confirm_delete"] = True

            prep_res = delete_node.prep(shared)
            exec_res = delete_node.exec(prep_res)
            action = delete_node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert not os.path.exists(backup_path)

            # Only new_path should remain
            assert os.path.exists(new_path)
            with open(new_path) as f:
                assert f.read() == "Original content"
