"""Test shell node binary data handling.

Each test catches ONE specific real bug that would break binary workflows.
"""

import base64
from unittest.mock import Mock, patch

from pflow.nodes.shell.shell import ShellNode


class TestBinaryStdoutDetection:
    """Test binary stdout detection and encoding."""

    def test_binary_stdout_detected_and_encoded(self):
        """
        Bug: Binary stdout not detected → corruption in downstream nodes.

        Real scenario: Command outputs PNG header → write-file receives corrupted mojibake.
        """
        node = ShellNode()
        node.set_params({"command": "cat image.png"})

        with patch("subprocess.run") as mock_run:
            # Mock binary output (PNG header)
            mock_result = Mock()
            mock_result.stdout = b"\x89PNG\r\n\x1a\n"
            mock_result.stderr = b""
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            shared = {}
            action = node.run(shared)

            # Binary detected and encoded
            assert action == "default"
            assert shared["stdout_is_binary"] is True
            expected_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
            assert shared["stdout"] == expected_b64, "Binary stdout not base64 encoded"

    def test_text_stdout_unchanged(self):
        """
        Bug: Text commands broken by binary changes → backward compatibility break.

        Real scenario: echo "hello" suddenly fails after binary support added.
        """
        node = ShellNode()
        node.set_params({"command": 'echo "hello world"'})

        with patch("subprocess.run") as mock_run:
            # Mock text output
            mock_result = Mock()
            mock_result.stdout = b"hello world\n"
            mock_result.stderr = b""
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            shared = {}
            action = node.run(shared)

            # Text decoded correctly
            assert action == "default"
            assert shared["stdout_is_binary"] is False
            assert shared["stdout"] == "hello world\n", "Text stdout corrupted"

    def test_empty_binary_handled(self):
        """
        Bug: Empty bytes cause decode to succeed → false negative on binary detection.

        Real scenario: Empty file cat'd → treated as text when should be binary doesn't matter.
        """
        node = ShellNode()
        node.set_params({"command": "cat empty.bin"})

        with patch("subprocess.run") as mock_run:
            # Empty bytes decode as empty string
            mock_result = Mock()
            mock_result.stdout = b""
            mock_result.stderr = b""
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            shared = {}
            action = node.run(shared)

            # Empty bytes correctly treated as text (decode succeeds)
            assert action == "default"
            assert shared["stdout_is_binary"] is False
            assert shared["stdout"] == ""


class TestBinaryStderrDetection:
    """Test binary stderr detection and encoding."""

    def test_binary_stderr_detected_and_encoded(self):
        """
        Bug: Binary stderr not detected → error messages corrupted.

        Real scenario: Binary command writes progress to stderr → monitoring breaks.
        """
        node = ShellNode()
        node.set_params({"command": "binary_tool", "ignore_errors": True})

        with patch("subprocess.run") as mock_run:
            # Binary error output (invalid UTF-8)
            mock_result = Mock()
            mock_result.stdout = b""
            mock_result.stderr = b"\xff\xfe\xfd\xfc"  # Invalid UTF-8 bytes
            mock_result.returncode = 1
            mock_run.return_value = mock_result

            shared = {}
            action = node.run(shared)

            # Binary stderr encoded
            assert action == "default"
            assert shared["stderr_is_binary"] is True
            expected_b64 = base64.b64encode(b"\xff\xfe\xfd\xfc").decode("ascii")
            assert shared["stderr"] == expected_b64


class TestMixedBinaryTextOutput:
    """Test independent handling of stdout and stderr."""

    def test_binary_stdout_text_stderr(self):
        """
        Bug: Binary stdout forces stderr to binary → text error messages corrupted.

        Real scenario: tar outputs archive to stdout, progress to stderr → stderr unreadable.
        """
        node = ShellNode()
        node.set_params({"command": "tar -czf - dir/"})

        with patch("subprocess.run") as mock_run:
            # Binary stdout, text stderr
            mock_result = Mock()
            mock_result.stdout = b"\x1f\x8b\x08"  # gzip header
            mock_result.stderr = b"Warning: file changed\n"
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            shared = {}
            node.run(shared)

            # Independent handling
            assert shared["stdout_is_binary"] is True
            assert shared["stderr_is_binary"] is False
            assert shared["stderr"] == "Warning: file changed\n"

    def test_text_stdout_binary_stderr(self):
        """
        Bug: Binary stderr forces stdout to binary → text output corrupted.

        Real scenario: Command outputs text but binary progress bar to stderr.
        """
        node = ShellNode()
        node.set_params({"command": "command"})

        with patch("subprocess.run") as mock_run:
            # Text stdout, binary stderr (invalid UTF-8)
            mock_result = Mock()
            mock_result.stdout = b"Success\n"
            mock_result.stderr = b"\x80\x81\x82"  # Invalid UTF-8 continuation bytes
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            shared = {}
            node.run(shared)

            # Independent handling
            assert shared["stdout_is_binary"] is False
            assert shared["stderr_is_binary"] is True
            assert shared["stdout"] == "Success\n"


class TestSafePatternsWithBinary:
    """Test safe pattern detection skipped for binary."""

    def test_grep_safe_pattern_not_applied_to_binary(self):
        """
        Bug: Safe pattern check on binary output → string operations crash.

        Real scenario: grep exits 1, binary stdout → "string in binary" crashes.
        """
        node = ShellNode()
        node.set_params({"command": "grep binary_pattern file.bin"})

        with patch("subprocess.run") as mock_run:
            # Binary output with exit code 1 (looks like grep no-match) - invalid UTF-8
            mock_result = Mock()
            mock_result.stdout = b"\xff\xfe"  # Invalid UTF-8
            mock_result.stderr = b""
            mock_result.returncode = 1
            mock_run.return_value = mock_result

            shared = {}
            action = node.run(shared)

            # Binary detected → safe patterns skipped → error returned
            assert action == "error", "Binary should not trigger safe patterns"
            assert shared["exit_code"] == 1

    def test_text_grep_safe_pattern_still_works(self):
        """
        Bug: Binary changes break safe pattern detection → text grep fails.

        Real scenario: grep "pattern" file.txt returns 1 → should be auto-handled.
        """
        node = ShellNode()
        node.set_params({"command": "grep pattern file.txt"})

        with patch("subprocess.run") as mock_run:
            # Text output, grep pattern not found
            mock_result = Mock()
            mock_result.stdout = b""
            mock_result.stderr = b""
            mock_result.returncode = 1
            mock_run.return_value = mock_result

            shared = {}
            action = node.run(shared)

            # Safe pattern still works for text
            assert action == "default", "Grep safe pattern should still work"
            assert shared["exit_code"] == 1


class TestStdinEncoding:
    """Test stdin encoding for text=False mode."""

    def test_text_stdin_encoded_to_bytes(self):
        """
        Bug: String stdin not encoded → subprocess.run crashes.

        Real scenario: echo "data" piped to stdin → TypeError: expected bytes.
        """
        node = ShellNode()
        node.set_params({"command": "cat"})

        with patch("subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.stdout = b"processed\n"
            mock_result.stderr = b""
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            shared = {"stdin": "input data"}
            action = node.run(shared)

            # Verify stdin was encoded
            assert action == "default"
            call_args = mock_run.call_args
            assert call_args[1]["input"] == b"input data", "stdin not encoded to bytes"

    def test_none_stdin_handled(self):
        """
        Bug: None stdin causes encode error → commands with no stdin crash.

        Real scenario: ls command → stdin.encode('utf-8') fails on None.
        """
        node = ShellNode()
        node.set_params({"command": "ls"})

        with patch("subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.stdout = b"file.txt\n"
            mock_result.stderr = b""
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            shared = {}
            action = node.run(shared)

            # None stdin handled
            assert action == "default"
            call_args = mock_run.call_args
            assert call_args[1]["input"] is None


class TestTimeoutHandling:
    """Test timeout with binary commands."""

    def test_timeout_with_binary_command(self):
        """
        Bug: Timeout on binary command → partial binary output crashes.

        Real scenario: Large file download times out → decode fails on partial bytes.
        """
        import subprocess

        node = ShellNode()
        node.set_params({"command": "download file.bin"})

        with patch("subprocess.run") as mock_run:
            # Simulate timeout with partial binary output
            timeout_exc = subprocess.TimeoutExpired(
                cmd="download",
                timeout=30,
                output=b"\x89PNG\x00\x01",  # Partial binary
                stderr=b"",
            )
            mock_run.side_effect = timeout_exc

            shared = {}
            action = node.run(shared)

            # Timeout uses lossy decode → readable error
            assert action == "error"
            assert shared["stdout_is_binary"] is False  # Lossy decode
            assert "�" in shared["stdout"] or shared["stdout"] != "", "Timeout should decode with replacement"


class TestBackwardCompatibility:
    """Test that existing text workflows still work."""

    def test_json_output_unchanged(self):
        """
        Bug: JSON output treated as binary → jq workflows break.

        Real scenario: Command outputs JSON → base64 encoded breaks parsing.
        """
        node = ShellNode()
        node.set_params({"command": 'jq "." data.json'})

        with patch("subprocess.run") as mock_run:
            # JSON is valid UTF-8
            json_output = b'{"result": "success"}\n'
            mock_result = Mock()
            mock_result.stdout = json_output
            mock_result.stderr = b""
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            shared = {}
            node.run(shared)

            # JSON decoded as text
            assert shared["stdout_is_binary"] is False
            assert shared["stdout"] == '{"result": "success"}\n'

    def test_multiline_text_unchanged(self):
        """
        Bug: Multiline text corrupted → logs and output unreadable.

        Real scenario: ls -la output → base64 encoded instead of text.
        """
        node = ShellNode()
        node.set_params({"command": "ls"})

        with patch("subprocess.run") as mock_run:
            # Multiline text output
            mock_result = Mock()
            mock_result.stdout = b"file1.txt\nfile2.txt\nfile3.txt\n"
            mock_result.stderr = b""
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            shared = {}
            node.run(shared)

            # Multiline text preserved
            assert shared["stdout_is_binary"] is False
            assert "file1.txt" in shared["stdout"]
            assert "file2.txt" in shared["stdout"]


class TestPartialUTF8Sequences:
    """Test detection of invalid UTF-8 sequences."""

    def test_invalid_utf8_detected_as_binary(self):
        """
        Bug: Invalid UTF-8 crashes decode → command fails instead of binary handling.

        Real scenario: Binary file has byte sequence that looks like UTF-8 start → decode fails.
        """
        node = ShellNode()
        node.set_params({"command": "cat invalid.bin"})

        with patch("subprocess.run") as mock_run:
            # Invalid UTF-8 sequence (incomplete multi-byte)
            mock_result = Mock()
            mock_result.stdout = b"\xc3\x28"  # Invalid UTF-8
            mock_result.stderr = b""
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            shared = {}
            node.run(shared)

            # Invalid UTF-8 detected as binary
            assert shared["stdout_is_binary"] is True
            expected_b64 = base64.b64encode(b"\xc3\x28").decode("ascii")
            assert shared["stdout"] == expected_b64
