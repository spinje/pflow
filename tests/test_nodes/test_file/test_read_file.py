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
            node.set_params({"file_path": temp_path})
            shared = {}

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
        """Test behavior when file doesn't exist.

        FIX HISTORY:
        - Removed dual testing approach (exception testing + behavior testing)
        - Fixed string assertion fragility by checking semantic meaning
        """
        node = ReadFileNode()
        node.set_params({"file_path": "/non/existent/file.txt"})
        shared = {}

        # BEHAVIOR: Should provide helpful error message
        action = node.run(shared)

        assert action == "error"
        assert "error" in shared
        error_msg = shared["error"]
        assert "exist" in error_msg.lower()  # More robust than exact string match
        assert "/non/existent/file.txt" in error_msg  # Shows actual path
        assert "content" not in shared

    def test_encoding_parameter(self):
        """Test custom encoding parameter."""
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-16", delete=False) as f:
            f.write("UTF-16 content")
            temp_path = f.name

        try:
            node = ReadFileNode()
            node.set_params({"file_path": temp_path, "encoding": "utf-16"})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert shared["content"] == "1: UTF-16 content"
        finally:
            os.unlink(temp_path)

    def test_encoding_error(self):
        """Test behavior when file has encoding issues.

        FIX HISTORY:
        - Removed dual testing approach (exception testing + behavior testing)
        - Fixed string assertion fragility with more robust checking
        - UPDATED for Task 82: Binary files now fallback instead of error

        BEHAVIOR CHANGE (Task 82): Files that fail UTF-8 decoding now fallback
        to binary mode instead of returning an error. This test now verifies
        the fallback works correctly.
        """
        # Write binary data that's not valid UTF-8
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"\x80\x81\x82\x83")
            temp_path = f.name

        try:
            node = ReadFileNode()
            node.set_params({"file_path": temp_path})
            shared = {}

            # NEW BEHAVIOR: Should fallback to binary, not error
            action = node.run(shared)

            assert action == "default", "Should fallback to binary, not error"
            assert "content" in shared
            assert "error" not in shared, "Binary fallback should succeed"

            # Should be base64 encoded binary
            assert "content_is_binary" in shared
            assert shared["content_is_binary"] is True
        finally:
            os.unlink(temp_path)

    def test_empty_file(self):
        """Test reading empty file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            temp_path = f.name

        try:
            node = ReadFileNode()
            node.set_params({"file_path": temp_path})
            shared = {}

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

        with pytest.raises(ValueError, match="Missing required 'file_path' parameter"):
            node.prep(shared)

    def test_line_numbers_multiline(self):
        """Test line number formatting with multiple lines."""
        content = "First line\nSecond line\n\nFourth line"
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            node = ReadFileNode()
            node.set_params({"file_path": temp_path})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            node.post(shared, prep_res, exec_res)

            expected = "1: First line\n2: Second line\n3: \n4: Fourth line"
            assert shared["content"] == expected
        finally:
            os.unlink(temp_path)
