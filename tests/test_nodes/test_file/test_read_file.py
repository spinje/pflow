"""Test ReadFileNode functionality."""

import os
import tempfile

import pytest

from src.pflow.nodes.file import ReadFileNode


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

        # Method 1: Test that exec raises FileNotFoundError
        with pytest.raises(FileNotFoundError):
            node.exec(prep_res)

        # Method 2: Test full lifecycle with node.run()
        action = node.run(shared)
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

            # Method 1: Test that exec raises UnicodeDecodeError
            with pytest.raises(UnicodeDecodeError):
                node.exec(prep_res)

            # Method 2: Test full lifecycle
            action = node.run(shared)
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
