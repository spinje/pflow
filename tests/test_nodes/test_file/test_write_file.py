"""Test WriteFileNode functionality."""

import base64
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
            node.set_params({"content": "Test content\nLine 2", "file_path": file_path})
            shared = {}

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
            node.set_params({"content": "Nested content", "file_path": file_path})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert os.path.exists(file_path)

            with open(file_path) as f:
                assert f.read() == "Nested content"

    def test_tilde_path_expansion_with_directory_creation(self, monkeypatch):
        """Test ~/ path expansion combined with automatic directory creation.

        This test verifies the scenario from GitHub issue #91:
        - Paths starting with ~/ should be expanded to the user's home directory
        - Parent directories should be created automatically
        """
        with tempfile.TemporaryDirectory() as fake_home:
            # Set up a fake home directory
            monkeypatch.setenv("HOME", fake_home)

            # Use ~/ path with non-existent subdirectory
            tilde_path = "~/stories/cat_story.md"

            node = WriteFileNode()
            node.set_params({"content": "Once upon a time, there was a clever cat...", "file_path": tilde_path})
            shared = {}

            # Run the node
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            # Verify success
            assert action == "default"
            assert "written" in shared

            # Verify the file was created at the expanded path
            expected_path = os.path.join(fake_home, "stories", "cat_story.md")
            assert os.path.exists(expected_path)

            # Verify the directory was created
            stories_dir = os.path.join(fake_home, "stories")
            assert os.path.isdir(stories_dir)

            # Verify content
            with open(expected_path) as f:
                assert f.read() == "Once upon a time, there was a clever cat..."

    def test_append_mode(self):
        """Test appending to existing file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("Initial content\n")
            temp_path = f.name

        try:
            node = WriteFileNode()
            node.set_params({"append": True, "content": "Appended content", "file_path": temp_path})
            shared = {}

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
            node.set_params({"content": "New content", "file_path": temp_path})
            shared = {}

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
            node.set_params({
                "content": "",  # Empty string
                "file_path": file_path,
            })
            shared = {}

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
            node.set_params({"content": "UTF-16 content", "file_path": file_path, "encoding": "utf-16"})
            shared = {}

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
            node.set_params({"file_path": tmp.name})
            shared = {}

            with pytest.raises(ValueError, match="Missing required 'content' parameter"):
                node.prep(shared)

    def test_missing_file_path(self):
        """Test error when file_path is missing."""
        node = WriteFileNode()
        node.set_params({"content": "Test"})
        shared = {}

        with pytest.raises(ValueError, match="Missing required 'file_path' parameter"):
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

    # Binary data support tests

    def test_write_binary_with_flag_preserves_data(self):
        """
        Guards against: Data corruption from using text mode for binary data.

        Tests that binary data written with content_is_binary=True flag is
        preserved byte-for-byte. If this test fails, binary data is being
        corrupted (wrong write mode, encoding issues, etc.).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "binary.png")

            # Known binary data (PNG header)
            binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            base64_content = base64.b64encode(binary_data).decode("ascii")

            node = WriteFileNode()
            node.set_params({"content": base64_content, "content_is_binary": True, "file_path": file_path})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"

            # Verify exact byte-for-byte match
            with open(file_path, "rb") as f:
                written_data = f.read()

            assert written_data == binary_data, "Binary data was corrupted during write"

    def test_write_binary_append_mode(self):
        """
        Guards against: Wrong append mode ('a' instead of 'ab') for binary data.

        Tests that binary append uses 'ab' mode. If this test fails, append
        mode is incorrectly using text mode for binary data.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "binary_append.dat")

            # First write
            chunk1 = b"\x89PNG\r\n"
            base64_chunk1 = base64.b64encode(chunk1).decode("ascii")

            node = WriteFileNode()
            node.set_params({"content": base64_chunk1, "content_is_binary": True, "file_path": file_path})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            node.post(shared, prep_res, exec_res)

            # Second write (append)
            chunk2 = b"\x1a\n\x00\x00"
            base64_chunk2 = base64.b64encode(chunk2).decode("ascii")

            node_append = WriteFileNode()
            node_append.set_params({
                "append": True,
                "content": base64_chunk2,
                "content_is_binary": True,
                "file_path": file_path,
            })
            shared_append = {}

            prep_res = node_append.prep(shared_append)
            exec_res = node_append.exec(prep_res)
            action = node_append.post(shared_append, prep_res, exec_res)

            assert action == "default"
            assert "append" in shared_append["written"].lower()

            # Verify both chunks are present
            with open(file_path, "rb") as f:
                written_data = f.read()

            assert written_data == chunk1 + chunk2, "Binary append mode corrupted data"

    def test_backward_compat_text_without_flag(self):
        """
        Guards against: Breaking existing text workflows.

        Tests that text writing without content_is_binary flag works exactly
        as before. If this test fails, backward compatibility is broken.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "text.txt")

            node = WriteFileNode()
            node.set_params({
                "content": "Plain text content\nLine 2",
                "file_path": file_path,
                # No content_is_binary flag - should default to text mode
            })
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"

            # Verify text mode was used
            with open(file_path) as f:
                content = f.read()

            assert content == "Plain text content\nLine 2", "Text mode should work without flag"

    def test_invalid_base64_clear_error(self):
        """
        Guards against: Unclear error messages for invalid base64.

        Tests that invalid base64 with binary flag gives a clear ValueError.
        If this test fails, error messages are unclear for AI agents.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "invalid.bin")

            node = WriteFileNode()
            node.set_params({"content": "not-valid-base64!@#$%", "content_is_binary": True, "file_path": file_path})
            shared = {}

            with pytest.raises(ValueError, match="Invalid base64 content"):
                node.prep(shared)

    def test_flag_false_writes_base64_as_text(self):
        """
        Guards against: Binary flag not being respected when explicitly False.

        Tests that content_is_binary=False writes the base64 STRING as text,
        not decoded binary. If this test fails, the flag is being ignored.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "base64_text.txt")

            base64_string = base64.b64encode(b"test data").decode("ascii")

            node = WriteFileNode()
            node.set_params({
                "content": base64_string,
                "content_is_binary": False,  # Explicitly False
                "file_path": file_path,
            })
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"

            # Should write the base64 STRING, not decoded bytes
            with open(file_path) as f:
                content = f.read()

            assert content == base64_string, "Explicit False flag should write base64 as text"

    def test_integration_http_output_format(self):
        """
        Guards against: Integration issues with HTTP node output format.

        Tests the exact output format from HTTP node (base64 string + flag)
        to ensure template resolution and integration works. If this test
        fails, the HTTP→Write-File pipeline is broken.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "downloaded.png")

            # Simulate exact HTTP node output format
            binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00d"
            http_response = base64.b64encode(binary_data).decode("ascii")
            http_flag = True

            node = WriteFileNode()
            node.set_params({
                "content": http_response,  # From ${download.response}
                "content_is_binary": http_flag,  # From ${download.response_is_binary}
                "file_path": file_path,
            })
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"

            # Verify exact byte match (MD5 would work but overkill for test)
            with open(file_path, "rb") as f:
                written_data = f.read()

            assert written_data == binary_data, "HTTP→Write-File integration produced wrong bytes"

    def test_write_dict_as_json(self):
        """
        Guards against: Dicts being written as Python repr instead of valid JSON.

        Tests that dict content is automatically serialized to valid JSON
        with double quotes. If this test fails, dict content is using str()
        instead of json.dumps().
        """
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "data.json")

            test_dict = {"name": "John", "age": 30, "active": True, "tags": ["dev", "python"]}

            node = WriteFileNode()
            node.set_params({"content": test_dict, "file_path": file_path})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"

            # Read and verify it's valid JSON
            with open(file_path) as f:
                content = f.read()

            # Should be valid JSON (not Python repr)
            parsed = json.loads(content)
            assert parsed == test_dict

            # Verify proper JSON format (double quotes)
            assert '"name"' in content
            assert "'name'" not in content  # No Python repr single quotes

    def test_write_list_as_json(self):
        """
        Guards against: Lists being written as Python repr instead of valid JSON.

        Tests that list content is automatically serialized to valid JSON.
        """
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "items.json")

            test_list = ["item1", "item2", {"nested": "value"}]

            node = WriteFileNode()
            node.set_params({"content": test_list, "file_path": file_path})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"

            # Verify valid JSON
            with open(file_path) as f:
                content = f.read()

            parsed = json.loads(content)
            assert parsed == test_list

    def test_write_string_unchanged(self):
        """
        Guards against: JSON serialization affecting plain strings.

        Tests that regular string content is written unchanged (backward compat).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "text.txt")

            test_string = "Just a plain string with some text"

            node = WriteFileNode()
            node.set_params({"content": test_string, "file_path": file_path})
            shared = {}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"

            # Verify unchanged
            with open(file_path) as f:
                content = f.read()

            assert content == test_string
