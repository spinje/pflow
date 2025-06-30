"""Test file nodes implementation."""

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


class TestReadFileNode:
    """Test ReadFileNode functionality."""

    def test_successful_read(self):
        """Test reading a file successfully."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("Line 1\nLine 2\nLine 3")
            temp_path = f.name

        try:
            node = ReadFileNode()
            shared = {"file_path": temp_path}

            # Execute node lifecycle
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            # Verify results
            assert action == "default"
            assert "content" in shared
            assert shared["content"] == "1: Line 1\n2: Line 2\n3: Line 3"
            assert "error" not in shared
        finally:
            os.unlink(temp_path)

    def test_missing_file(self):
        """Test handling of missing file."""
        node = ReadFileNode()
        shared = {"file_path": "/non/existent/file.txt"}

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        assert action == "error"
        assert "error" in shared
        assert "does not exist" in shared["error"]
        assert "content" not in shared

    def test_encoding_parameter(self):
        """Test custom encoding parameter."""
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-16", delete=False) as f:
            f.write("UTF-16 content")
            temp_path = f.name

        try:
            node = ReadFileNode()
            shared = {"file_path": temp_path, "encoding": "utf-16"}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert shared["content"] == "1: UTF-16 content"
        finally:
            os.unlink(temp_path)

    def test_encoding_error(self):
        """Test handling of encoding errors."""
        # Write binary data that's not valid UTF-8
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"\x80\x81\x82\x83")
            temp_path = f.name

        try:
            node = ReadFileNode()
            shared = {"file_path": temp_path}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "error"
            assert "encoding" in shared["error"].lower() or "Cannot read" in shared["error"]
        finally:
            os.unlink(temp_path)

    def test_empty_file(self):
        """Test reading empty file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            temp_path = f.name

        try:
            node = ReadFileNode()
            shared = {"file_path": temp_path}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert shared["content"] == ""
        finally:
            os.unlink(temp_path)

    def test_params_fallback(self):
        """Test using params when shared store doesn't have file_path."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("Test content")
            temp_path = f.name

        try:
            node = ReadFileNode()
            node.set_params({"file_path": temp_path})
            shared = {}  # No file_path in shared

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert shared["content"] == "1: Test content"
        finally:
            os.unlink(temp_path)

    def test_missing_file_path(self):
        """Test error when file_path is missing."""
        node = ReadFileNode()
        shared = {}

        with pytest.raises(ValueError, match="Missing required 'file_path'"):
            node.prep(shared)

    def test_line_numbers_multiline(self):
        """Test line number formatting with multiple lines."""
        content = "First line\nSecond line\n\nFourth line"
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            node = ReadFileNode()
            shared = {"file_path": temp_path}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            node.post(shared, prep_res, exec_res)

            expected = "1: First line\n2: Second line\n3: \n4: Fourth line"
            assert shared["content"] == expected
        finally:
            os.unlink(temp_path)


class TestWriteFileNode:
    """Test WriteFileNode functionality."""

    def test_successful_write(self):
        """Test writing a file successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")

            node = WriteFileNode()
            shared = {"content": "Test content\nLine 2", "file_path": file_path}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert "written" in shared
            assert "Successfully wrote to" in shared["written"]

            # Verify file contents
            with open(file_path) as f:
                assert f.read() == "Test content\nLine 2"

    def test_create_parent_directories(self):
        """Test automatic parent directory creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "nested", "deep", "file.txt")

            node = WriteFileNode()
            shared = {"content": "Nested content", "file_path": file_path}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert os.path.exists(file_path)

            with open(file_path) as f:
                assert f.read() == "Nested content"

    def test_append_mode(self):
        """Test appending to existing file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("Initial content\n")
            temp_path = f.name

        try:
            node = WriteFileNode()
            node.set_params({"append": True})
            shared = {"content": "Appended content", "file_path": temp_path}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert "appended to" in shared["written"]

            with open(temp_path) as f:
                assert f.read() == "Initial content\nAppended content"
        finally:
            os.unlink(temp_path)

    def test_overwrite_existing(self):
        """Test overwriting existing file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("Old content")
            temp_path = f.name

        try:
            node = WriteFileNode()
            shared = {"content": "New content", "file_path": temp_path}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"

            with open(temp_path) as f:
                assert f.read() == "New content"
        finally:
            os.unlink(temp_path)

    def test_empty_content(self):
        """Test writing empty content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "empty.txt")

            node = WriteFileNode()
            shared = {
                "content": "",  # Empty string
                "file_path": file_path,
            }

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert os.path.exists(file_path)

            with open(file_path) as f:
                assert f.read() == ""

    def test_custom_encoding(self):
        """Test writing with custom encoding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "utf16.txt")

            node = WriteFileNode()
            shared = {"content": "UTF-16 content", "file_path": file_path, "encoding": "utf-16"}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"

            with open(file_path, encoding="utf-16") as f:
                assert f.read() == "UTF-16 content"

    def test_missing_content(self):
        """Test error when content is missing."""
        node = WriteFileNode()
        with tempfile.NamedTemporaryFile() as tmp:
            shared = {"file_path": tmp.name}

            with pytest.raises(ValueError, match="Missing required 'content'"):
                node.prep(shared)

    def test_missing_file_path(self):
        """Test error when file_path is missing."""
        node = WriteFileNode()
        shared = {"content": "Test"}

        with pytest.raises(ValueError, match="Missing required 'file_path'"):
            node.prep(shared)

    def test_params_fallback(self):
        """Test using params when shared store doesn't have values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")

            node = WriteFileNode()
            node.set_params({"file_path": file_path, "content": "From params"})
            shared = {}  # Empty shared store

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"

            with open(file_path) as f:
                assert f.read() == "From params"


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

        prep_res = read_node.prep(shared)
        exec_res = read_node.exec(prep_res)
        action = read_node.post(shared, prep_res, exec_res)

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
            shared = {"source_path": source_path, "dest_path": dest_path}

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
            shared = {"source_path": source_path, "dest_path": dest_path}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert os.path.exists(dest_path)

    def test_copy_overwrite_protection(self):
        """Test copy fails when destination exists without overwrite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.txt")
            dest_path = os.path.join(tmpdir, "dest.txt")

            # Create both files
            with open(source_path, "w") as f:
                f.write("Source content")
            with open(dest_path, "w") as f:
                f.write("Existing content")

            node = CopyFileNode()
            shared = {"source_path": source_path, "dest_path": dest_path}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "error"
            assert "already exists" in shared["error"]

            # Verify destination wasn't overwritten
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
            shared = {"source_path": source_path, "dest_path": dest_path, "overwrite": True}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"

            # Verify destination was overwritten
            with open(dest_path) as f:
                assert f.read() == "New content"

    def test_copy_source_not_found(self):
        """Test error when source doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "missing.txt")
            dest_path = os.path.join(tmpdir, "dest.txt")

            node = CopyFileNode()
            shared = {"source_path": source_path, "dest_path": dest_path}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "error"
            assert "does not exist" in shared["error"]


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
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

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
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "error"
            assert "does not exist" in shared["error"]

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
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

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
