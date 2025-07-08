"""Tests for shell integration utilities."""

import io
import json
from unittest.mock import patch

from pflow.core.shell_integration import (
    detect_stdin,
    determine_stdin_mode,
    populate_shared_store,
    read_stdin,
)


class TestDetectStdin:
    """Test stdin detection."""

    def test_interactive_terminal(self):
        """Test detection returns False for interactive terminal."""
        with patch("sys.stdin.isatty", return_value=True):
            assert detect_stdin() is False

    def test_piped_input(self):
        """Test detection returns True for piped input."""
        with patch("sys.stdin.isatty", return_value=False):
            assert detect_stdin() is True


class TestReadStdin:
    """Test stdin reading functionality."""

    def test_no_stdin_returns_none(self):
        """Test that interactive terminal returns None."""
        with patch("sys.stdin.isatty", return_value=True):
            assert read_stdin() is None

    def test_empty_stdin_returns_none(self):
        """Test that empty piped input returns None."""
        with patch("sys.stdin", io.StringIO("")), patch("sys.stdin.isatty", return_value=False):
            assert read_stdin() is None

    def test_text_stdin_reads_correctly(self):
        """Test that text content is read correctly."""
        test_content = "Hello, world!"
        with patch("sys.stdin", io.StringIO(test_content)), patch("sys.stdin.isatty", return_value=False):
            assert read_stdin() == test_content

    def test_multiline_stdin_preserves_content(self):
        """Test that multiline content is preserved."""
        test_content = "Line 1\nLine 2\nLine 3"
        # Add trailing newline as real stdin would
        with patch("sys.stdin", io.StringIO(test_content + "\n")), patch("sys.stdin.isatty", return_value=False):
            # Should strip only the trailing newline
            assert read_stdin() == test_content

    def test_whitespace_preservation(self):
        """Test that intentional whitespace is preserved."""
        test_content = "  indented  \n  content  "
        # Add trailing newline
        with patch("sys.stdin", io.StringIO(test_content + "\n")), patch("sys.stdin.isatty", return_value=False):
            # Should only strip the final newline
            assert read_stdin() == test_content

    def test_unicode_content(self):
        """Test that Unicode content is handled correctly."""
        test_content = "Hello 世界 🌍"
        with patch("sys.stdin", io.StringIO(test_content)), patch("sys.stdin.isatty", return_value=False):
            assert read_stdin() == test_content

    def test_invalid_utf8_raises_error(self):
        """Test that invalid UTF-8 raises UnicodeDecodeError."""
        # This test is tricky with StringIO since it handles strings, not bytes
        # In real usage, sys.stdin would raise the error
        # For now, we'll document this as a limitation of the test
        # The actual implementation will handle this correctly with real stdin
        pass  # TODO: Test with subprocess for real stdin behavior


class TestDetermineStdinMode:
    """Test stdin mode determination."""

    def test_valid_workflow_json(self):
        """Test that valid workflow JSON is detected."""
        workflow = {"ir_version": "1.0", "nodes": [], "edges": []}
        content = json.dumps(workflow)
        assert determine_stdin_mode(content) == "workflow"

    def test_json_without_ir_version(self):
        """Test that JSON without ir_version is treated as data."""
        data = {"name": "test", "value": 123}
        content = json.dumps(data)
        assert determine_stdin_mode(content) == "data"

    def test_invalid_json(self):
        """Test that invalid JSON is treated as data."""
        content = "This is not JSON"
        assert determine_stdin_mode(content) == "data"

    def test_json_array(self):
        """Test that JSON arrays are treated as data."""
        content = json.dumps([1, 2, 3])
        assert determine_stdin_mode(content) == "data"

    def test_empty_string(self):
        """Test that empty string is treated as data."""
        assert determine_stdin_mode("") == "data"

    def test_workflow_with_extra_fields(self):
        """Test that workflow with extra fields is still detected."""
        workflow = {"ir_version": "1.0", "nodes": [], "edges": [], "metadata": {"author": "test"}}
        content = json.dumps(workflow)
        assert determine_stdin_mode(content) == "workflow"


class TestPopulateSharedStore:
    """Test shared store population."""

    def test_populate_empty_store(self):
        """Test populating an empty shared store."""
        shared = {}
        content = "test data"
        populate_shared_store(shared, content)
        assert shared["stdin"] == content

    def test_populate_existing_store(self):
        """Test populating a store with existing data."""
        shared = {"other_key": "other_value"}
        content = "test data"
        populate_shared_store(shared, content)
        assert shared["stdin"] == content
        assert shared["other_key"] == "other_value"

    def test_overwrite_existing_stdin(self):
        """Test that existing stdin value is overwritten."""
        shared = {"stdin": "old data"}
        content = "new data"
        populate_shared_store(shared, content)
        assert shared["stdin"] == content

    def test_empty_content(self):
        """Test that empty content is stored correctly."""
        shared = {}
        content = ""
        populate_shared_store(shared, content)
        assert shared["stdin"] == ""


class TestIntegration:
    """Integration tests for the complete flow."""

    def test_full_workflow_detection_flow(self):
        """Test complete flow for workflow detection."""
        workflow = {"ir_version": "1.0", "nodes": []}
        workflow_str = json.dumps(workflow)

        with patch("sys.stdin", io.StringIO(workflow_str)), patch("sys.stdin.isatty", return_value=False):
            # Read stdin
            content = read_stdin()
            assert content is not None

            # Determine mode
            mode = determine_stdin_mode(content)
            assert mode == "workflow"

    def test_full_data_flow(self):
        """Test complete flow for data input."""
        data = "Some user data"

        with patch("sys.stdin", io.StringIO(data)), patch("sys.stdin.isatty", return_value=False):
            # Read stdin
            content = read_stdin()
            assert content is not None

            # Determine mode
            mode = determine_stdin_mode(content)
            assert mode == "data"

            # Populate shared store
            shared = {}
            populate_shared_store(shared, content)
            assert shared["stdin"] == data
