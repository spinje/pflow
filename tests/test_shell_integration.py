"""Tests for shell integration utilities."""

import io
import json
from unittest.mock import patch

from pflow.core.shell_integration import (
    StdinData,
    detect_binary_content,
    detect_stdin,
    determine_stdin_mode,
    read_stdin,
    read_stdin_enhanced,
    read_stdin_with_limit,
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

            # Note: stdin is now routed to workflow inputs via stdin: true
            # in the workflow IR, not via populate_shared_store
            assert content == data


class TestBinaryDetection:
    """Test binary content detection."""

    def test_detect_binary_with_null_bytes(self):
        """Test that null bytes are detected as binary."""
        sample = b"Hello\x00World"
        assert detect_binary_content(sample) is True

    def test_detect_text_without_null_bytes(self):
        """Test that text without null bytes is not detected as binary."""
        sample = b"Hello World\nThis is text"
        assert detect_binary_content(sample) is False

    def test_detect_empty_content(self):
        """Test that empty content is not binary."""
        sample = b""
        assert detect_binary_content(sample) is False

    def test_detect_binary_image_header(self):
        """Test detection of common binary file headers."""
        # PNG header
        png_sample = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        assert detect_binary_content(png_sample) is True

        # JPEG header
        jpeg_sample = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        assert detect_binary_content(jpeg_sample) is True


class TestStdinDataClass:
    """Test StdinData dataclass."""

    def test_text_data(self):
        """Test StdinData with text content."""
        data = StdinData(text_data="Hello World")
        assert data.is_text is True
        assert data.is_binary is False
        assert data.is_temp_file is False

    def test_binary_data(self):
        """Test StdinData with binary content."""
        data = StdinData(binary_data=b"Hello\x00World")
        assert data.is_text is False
        assert data.is_binary is True
        assert data.is_temp_file is False

    def test_temp_file_data(self):
        """Test StdinData with temp file path."""
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            temp_path = tf.name
        data = StdinData(temp_path=temp_path)
        assert data.is_text is False
        assert data.is_binary is False
        assert data.is_temp_file is True
        # Clean up
        import os

        os.unlink(temp_path)

    def test_empty_data(self):
        """Test StdinData with no data."""
        data = StdinData()
        assert data.is_text is False
        assert data.is_binary is False
        assert data.is_temp_file is False


class TestReadStdinWithLimit:
    """Test stdin reading with size limits."""

    def test_small_text_data(self):
        """Test reading small text data."""
        test_data = b"Hello World"
        with patch("sys.stdin.buffer.read", side_effect=[test_data, b""]):
            result = read_stdin_with_limit(max_size=1024)
            assert result.is_text is True
            assert result.text_data == "Hello World"

    def test_small_binary_data(self):
        """Test reading small binary data."""
        test_data = b"Hello\x00World"
        with patch("sys.stdin.buffer.read", side_effect=[test_data, b""]):
            result = read_stdin_with_limit(max_size=1024)
            assert result.is_binary is True
            assert result.binary_data == test_data

    def test_text_with_trailing_newline(self):
        """Test that trailing newline is stripped from text."""
        test_data = b"Hello World\n"
        with patch("sys.stdin.buffer.read", side_effect=[test_data, b""]):
            result = read_stdin_with_limit(max_size=1024)
            assert result.is_text is True
            assert result.text_data == "Hello World"

    def test_empty_stdin(self):
        """Test reading empty stdin."""
        with patch("sys.stdin.buffer.read", return_value=b""):
            result = read_stdin_with_limit()
            assert result.is_text is True
            assert result.text_data == ""

    def test_large_file_streaming(self):
        """Test streaming large files to temp storage."""
        # To trigger streaming, we need data larger than 8KB (BINARY_SAMPLE_SIZE)
        # AND larger than our memory limit (500 bytes for this test)

        # Create data that's larger than 8KB
        large_data = b"x" * 10000  # 10KB of data

        # Track read positions
        read_position = [0]

        def mock_read(size):
            start = read_position[0]
            end = min(start + size, len(large_data))
            chunk = large_data[start:end]
            read_position[0] = end
            return chunk

        with patch("sys.stdin.buffer.read", side_effect=mock_read), patch("tempfile.NamedTemporaryFile") as mock_temp:
            # Mock temp file
            mock_file = mock_temp.return_value
            mock_file.name = "test_temp_file"

            result = read_stdin_with_limit(max_size=500)

            assert result.is_temp_file is True
            assert result.temp_path == "test_temp_file"

            # Verify data was written
            mock_file.write.assert_called()
            mock_file.close.assert_called()

    def test_environment_variable_limit(self):
        """Test reading limit from environment variable."""
        with (
            patch.dict("os.environ", {"PFLOW_STDIN_MEMORY_LIMIT": "1000"}),
            patch("sys.stdin.buffer.read", side_effect=[b"x" * 500, b""]),
        ):
            result = read_stdin_with_limit()
            assert result.is_text is True  # Under 1000 byte limit

    def test_invalid_environment_variable(self):
        """Test fallback when env var is invalid."""
        with (
            patch.dict("os.environ", {"PFLOW_STDIN_MEMORY_LIMIT": "invalid"}),
            patch("sys.stdin.buffer.read", side_effect=[b"test", b""]),
        ):
            result = read_stdin_with_limit()
            assert result.is_text is True  # Should use default limit


class TestReadStdinEnhanced:
    """Test enhanced stdin reading."""

    def test_no_stdin_available(self):
        """Test when no stdin is available."""
        with patch("sys.stdin.isatty", return_value=True):
            result = read_stdin_enhanced()
            assert result is None

    def test_empty_stdin_returns_none(self):
        """Test that empty stdin returns None."""
        with patch("sys.stdin.isatty", return_value=False), patch("sys.stdin.buffer.read", return_value=b""):
            result = read_stdin_enhanced()
            assert result is None

    def test_text_stdin(self):
        """Test reading text stdin."""
        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stdin.buffer.read", side_effect=[b"Hello World", b""]),
        ):
            result = read_stdin_enhanced()
            assert result is not None
            assert result.is_text is True
            assert result.text_data == "Hello World"

    def test_binary_stdin(self):
        """Test reading binary stdin."""
        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stdin.buffer.read", side_effect=[b"Hello\x00World", b""]),
        ):
            result = read_stdin_enhanced()
            assert result is not None
            assert result.is_binary is True
            assert result.binary_data == b"Hello\x00World"

    def test_exception_handling(self):
        """Test exception handling returns None."""
        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stdin.buffer.read", side_effect=OSError("Test error")),
        ):
            result = read_stdin_enhanced()
            assert result is None
