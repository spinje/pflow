"""Test WriteFileNode functionality."""

import os
import tempfile

import pytest

from src.pflow.nodes.file import WriteFileNode


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
            # Check semantic meaning rather than exact string
            success_msg = shared["written"]
            assert "wrote" in success_msg.lower() or "written" in success_msg.lower()
            assert file_path in success_msg  # Shows actual file path

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
            # Check semantic meaning rather than exact string
            success_msg = shared["written"]
            assert "append" in success_msg.lower()
            assert temp_path in success_msg  # Shows actual file path

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
