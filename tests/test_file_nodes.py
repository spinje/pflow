"""Test file nodes implementation."""

import os
import tempfile

import pytest

from src.pflow.nodes.file import ReadFileNode, WriteFileNode


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
            assert "Encoding error" in shared["error"]
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
