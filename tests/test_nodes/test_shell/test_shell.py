"""Tests for ShellNode - verifying actual shell command execution behavior."""

import os
import platform
import tempfile
import time
from pathlib import Path

import pytest

from pflow.nodes.shell.shell import ShellNode


def run_shell_node(shared, **params):
    """Helper function to run a shell node with parameters."""
    node = ShellNode()
    node.set_params(params)
    return node.run(shared)


class TestShellNodeBasicExecution:
    """Test basic command execution functionality."""

    def test_simple_echo_command(self):
        """Test that echo command actually executes and returns output."""
        shared = {}

        run_shell_node(shared, command="echo hello")

        assert shared["stdout"].strip() == "hello"
        assert shared["stderr"] == ""
        assert shared["exit_code"] == 0

    def test_echo_with_arguments(self):
        """Test echo with multiple words and quotes."""
        shared = {}

        run_shell_node(shared, command='echo "hello world"')

        assert shared["stdout"].strip() == "hello world"
        assert shared["exit_code"] == 0

    def test_pwd_command_returns_current_directory(self):
        """Test that pwd returns the actual current directory."""
        shared = {}

        run_shell_node(shared, command="pwd")

        # The output should be the current working directory
        assert shared["stdout"].strip() == os.getcwd()
        assert shared["exit_code"] == 0

    def test_date_command_executes(self):
        """Test that date command runs and produces output."""
        shared = {}

        run_shell_node(shared, command="date")

        # Date output should contain the current year
        assert str(time.localtime().tm_year) in shared["stdout"]
        assert shared["exit_code"] == 0

    def test_command_with_stdin_input(self):
        """Test passing data through stdin to commands."""
        shared = {}

        # Use cat to echo stdin
        run_shell_node(shared, command="cat", stdin="hello from stdin")

        assert shared["stdout"] == "hello from stdin"
        assert shared["exit_code"] == 0

    def test_multiline_stdin_input(self):
        """Test passing multiline data through stdin."""
        # Add trailing newline to ensure wc counts all lines
        shared = {}

        # Count lines using wc
        run_shell_node(shared, command="wc -l", stdin="line1\nline2\nline3\n")

        # wc -l should return 3 (with possible leading/trailing spaces)
        output = shared["stdout"].strip()
        assert output == "3"
        assert shared["exit_code"] == 0


class TestShellNodeShellFeatures:
    """Test shell-specific features that require shell=True."""

    def test_pipe_command_works(self):
        """Test that shell pipes actually work."""
        # node = ShellNode()
        shared = {}

        # Pipe echo output to grep
        run_shell_node(shared, command='echo "hello world" | grep world')

        assert "world" in shared["stdout"]
        assert shared["exit_code"] == 0

    def test_multiple_commands_with_and_operator(self):
        """Test running multiple commands with && operator."""
        # node = ShellNode()
        shared = {}

        run_shell_node(shared, command='echo "first" && echo "second"')

        assert "first" in shared["stdout"]
        assert "second" in shared["stdout"]
        assert shared["exit_code"] == 0

    def test_semicolon_command_separator(self):
        """Test running multiple commands with semicolon."""
        # node = ShellNode()
        shared = {}

        run_shell_node(shared, command='echo "one"; echo "two"; echo "three"')

        assert "one" in shared["stdout"]
        assert "two" in shared["stdout"]
        assert "three" in shared["stdout"]
        assert shared["exit_code"] == 0

    def test_environment_variable_expansion(self):
        """Test that shell expands environment variables."""
        # node = ShellNode()
        shared = {}

        # HOME should be set in any Unix environment
        run_shell_node(shared, command="echo $HOME")

        output = shared["stdout"].strip()
        assert output != "$HOME"  # Should be expanded
        assert output == os.environ.get("HOME", "")
        assert shared["exit_code"] == 0

    def test_shell_for_loop(self):
        """Test that shell loops work."""
        # node = ShellNode()
        shared = {}

        run_shell_node(shared, command='for i in 1 2 3; do echo "number $i"; done')

        assert "number 1" in shared["stdout"]
        assert "number 2" in shared["stdout"]
        assert "number 3" in shared["stdout"]
        assert shared["exit_code"] == 0

    def test_command_substitution(self):
        """Test shell command substitution with backticks or $()."""
        # node = ShellNode()
        shared = {}

        run_shell_node(shared, command='echo "Current dir: $(pwd)"')

        assert "Current dir:" in shared["stdout"]
        assert os.getcwd() in shared["stdout"]
        assert shared["exit_code"] == 0

    def test_output_redirection_to_file(self):
        """Test shell output redirection."""
        # node = ShellNode()
        shared = {}

        with tempfile.NamedTemporaryFile(mode="r", delete=False) as f:
            temp_file = f.name

        try:
            # Redirect echo output to file
            run_shell_node(shared, command=f'echo "test content" > {temp_file}')
            assert shared["exit_code"] == 0

            # Verify file was created with content
            with open(temp_file) as f:
                assert f.read().strip() == "test content"
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)


class TestShellNodeErrorHandling:
    """Test error handling and failure scenarios."""

    def test_nonexistent_command_fails(self):
        """Test that non-existent commands return non-zero exit code."""
        # node = ShellNode()
        shared = {}

        # Use a command that definitely doesn't exist
        action = run_shell_node(shared, command="this_command_does_not_exist_123456")

        assert shared["exit_code"] != 0
        assert action == "error"
        # stderr should contain error message
        assert shared["stderr"] != ""

    def test_grep_no_match_returns_exit_code_1(self):
        """Test that grep with no match is auto-handled as success."""
        # node = ShellNode()
        shared = {}

        # grep returns exit code 1 when no match found, but this is auto-handled
        action = run_shell_node(shared, command='echo "hello" | grep "xyz"')

        assert shared["exit_code"] == 1  # Original exit code preserved
        assert shared["stdout"] == ""  # No match, no output
        assert action == "default"  # Auto-handled as success (no match is valid)

    def test_timeout_functionality(self):
        """Test that timeout works correctly - combines multiple timeout tests."""
        shared = {}

        # Test 1: Timeout kills long-running commands and returns error
        start_time = time.time()
        action = run_shell_node(shared, command="sleep 10", timeout=0.1)
        elapsed = time.time() - start_time

        assert elapsed < 0.3  # Should timeout quickly
        assert shared["exit_code"] == -1  # Timeout convention
        assert action == "error"
        assert "timed out" in shared.get("error", "").lower()

        # Test 2: Commands that complete before timeout succeed
        shared = {}
        action = run_shell_node(shared, command="echo quick", timeout=1)
        assert action == "default"
        assert shared["exit_code"] == 0

    def test_ignore_errors_allows_continuation_on_failure(self):
        """Test that ignore_errors parameter allows continuing on failures."""
        # node = ShellNode()
        shared = {}

        # Command that will fail
        action = run_shell_node(shared, command='grep "xyz" /dev/null', ignore_errors=True)

        assert shared["exit_code"] == 1  # grep returns 1 for no match
        assert action == "default"  # But we return success due to ignore_errors

    def test_ignore_errors_with_nonexistent_command(self):
        """Test ignore_errors with command that doesn't exist."""
        # node = ShellNode()
        shared = {}

        action = run_shell_node(shared, command="nonexistent_command_789", ignore_errors=True)

        assert shared["exit_code"] != 0
        assert action == "default"  # Still returns default

    def test_false_command_returns_exit_code_1(self):
        """Test using the 'false' command which always returns exit code 1."""
        # node = ShellNode()
        shared = {}

        action = run_shell_node(shared, command="false")

        assert shared["exit_code"] == 1
        assert action == "error"

    def test_true_command_returns_exit_code_0(self):
        """Test using the 'true' command which always returns exit code 0."""
        # node = ShellNode()
        shared = {}

        action = run_shell_node(shared, command="true")

        assert shared["exit_code"] == 0
        assert action == "default"


class TestShellNodeConfiguration:
    """Test configuration options like cwd, env, timeout."""

    def test_cwd_changes_working_directory(self):
        """Test that cwd parameter actually changes the working directory."""
        # node = ShellNode()
        shared = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            # Run pwd in the temp directory
            run_shell_node(shared, command="pwd", cwd=tmpdir)

            # On macOS, /var may be symlinked to /private/var
            actual_path = shared["stdout"].strip()
            expected_path = os.path.realpath(tmpdir)
            assert actual_path in (expected_path, tmpdir)
            assert shared["exit_code"] == 0

    def test_cwd_with_tilde_expansion(self):
        """Test that ~ is expanded in cwd path."""
        # node = ShellNode()
        shared = {}

        # Use ~ for home directory
        run_shell_node(shared, command="pwd", cwd="~")

        assert shared["stdout"].strip() == os.path.expanduser("~")
        assert shared["exit_code"] == 0

    def test_cwd_nonexistent_directory_raises_error(self):
        """Test that using non-existent directory for cwd raises error."""
        # node = ShellNode()
        shared = {}

        with pytest.raises(ValueError, match="Working directory does not exist"):
            run_shell_node(shared, command="pwd", cwd="/this/directory/does/not/exist/123456")

    def test_custom_environment_variables(self):
        """Test setting custom environment variables."""
        # node = ShellNode()
        shared = {}

        # Set a custom environment variable
        run_shell_node(shared, command='echo "$MY_CUSTOM_VAR"', env={"MY_CUSTOM_VAR": "test_value"})

        assert shared["stdout"].strip() == "test_value"
        assert shared["exit_code"] == 0

    def test_multiple_environment_variables(self):
        """Test setting multiple custom environment variables."""
        # node = ShellNode()
        shared = {}

        env = {"VAR1": "value1", "VAR2": "value2", "VAR3": "value3"}

        run_shell_node(shared, command='echo "$VAR1 $VAR2 $VAR3"', env=env)

        assert "value1 value2 value3" in shared["stdout"]
        assert shared["exit_code"] == 0

    def test_env_vars_override_existing(self):
        """Test that custom env vars can override existing ones."""
        # node = ShellNode()
        shared = {}

        # Override PATH temporarily
        run_shell_node(shared, command='echo "$PATH"', env={"PATH": "/custom/path"})

        assert shared["stdout"].strip() == "/custom/path"
        assert shared["exit_code"] == 0

    def test_invalid_timeout_raises_error(self):
        """Test that invalid timeout values raise errors."""
        # node = ShellNode()
        shared = {}

        with pytest.raises(ValueError, match="Invalid timeout value"):
            run_shell_node(shared, command="echo test", timeout=0)

        with pytest.raises(ValueError, match="Invalid timeout value"):
            run_shell_node(shared, command="echo test", timeout=-5)

        with pytest.raises(ValueError, match="Invalid timeout value"):
            run_shell_node(shared, command="echo test", timeout="not a number")


class TestShellNodeSecurity:
    """Test security checks for dangerous commands."""

    def test_rm_rf_root_is_blocked(self):
        """Test that 'rm -rf /' is blocked."""
        # node = ShellNode()
        shared = {}

        with pytest.raises(ValueError, match="Dangerous command pattern detected"):
            run_shell_node(shared, command="rm -rf /")

    def test_rm_rf_root_wildcard_is_blocked(self):
        """Test that 'rm -rf /*' is blocked."""
        # node = ShellNode()
        shared = {}

        with pytest.raises(ValueError, match="Dangerous command pattern detected"):
            run_shell_node(shared, command="rm -rf /*")

    def test_fork_bomb_is_blocked(self):
        """Test that fork bomb pattern is blocked."""
        # node = ShellNode()
        shared = {}

        with pytest.raises(ValueError, match="Dangerous command pattern detected"):
            run_shell_node(shared, command=":(){ :|:& };:")

    def test_dd_to_device_is_blocked(self):
        """Test that dd commands to devices are blocked."""
        # node = ShellNode()
        shared = {}

        with pytest.raises(ValueError, match="Dangerous command pattern detected"):
            run_shell_node(shared, command="dd if=/dev/zero of=/dev/sda")

    def test_normal_rm_command_works(self):
        """Test that normal rm commands are allowed."""
        # node = ShellNode()
        shared = {}

        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_file = f.name

        # Normal rm should work
        run_shell_node(shared, command=f"rm {temp_file}")

        assert shared["exit_code"] == 0
        assert not os.path.exists(temp_file)

    def test_security_check_is_case_insensitive(self):
        """Test that security checks work regardless of case."""
        # node = ShellNode()
        shared = {}

        with pytest.raises(ValueError, match="Dangerous command pattern detected"):
            run_shell_node(shared, command="RM -RF /")

        with pytest.raises(ValueError, match="Dangerous command pattern detected"):
            run_shell_node(shared, command="Rm -Rf /")


class TestShellNodeFlowControl:
    """Test action returns for flow control."""

    def test_successful_command_returns_success_action(self):
        """Test that successful commands return 'success' action."""
        # node = ShellNode()
        shared = {}

        action = run_shell_node(shared, command="echo test")

        assert action == "default"
        assert shared["exit_code"] == 0

    def test_failed_command_returns_error_action(self):
        """Test that failed commands return 'error' action."""
        # node = ShellNode()
        shared = {}

        action = run_shell_node(shared, command="false")  # Always fails

        assert action == "error"
        assert shared["exit_code"] == 1

    def test_ignore_errors_returns_success_on_failure(self):
        """Test that ignore_errors makes failed commands return 'success'."""
        # node = ShellNode()
        shared = {}

        action = run_shell_node(shared, command="false", ignore_errors=True)

        assert action == "default"  # Returns success despite failure
        assert shared["exit_code"] == 1  # But exit code is still 1


class TestShellNodePracticalScenarios:
    """Test practical real-world command scenarios."""

    def test_create_and_list_files(self):
        """Test creating files and listing them."""
        # node = ShellNode()
        shared = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple files
            run_shell_node(shared, command="touch file1.txt file2.txt file3.txt", cwd=tmpdir)
            assert shared["exit_code"] == 0

            # List files
            run_shell_node(shared, command="ls", cwd=tmpdir)
            assert "file1.txt" in shared["stdout"]
            assert "file2.txt" in shared["stdout"]
            assert "file3.txt" in shared["stdout"]

    def test_grep_from_stdin(self):
        """Test using grep with stdin input."""
        # node = ShellNode()
        shared = {}

        # Grep for lines containing 'a'
        run_shell_node(shared, command='grep "a"', stdin="apple\nbanana\ncherry\napricot")

        assert "apple" in shared["stdout"]
        assert "banana" in shared["stdout"]
        assert "apricot" in shared["stdout"]
        assert "cherry" not in shared["stdout"]
        assert shared["exit_code"] == 0

    def test_word_count_pipeline(self):
        """Test a practical pipeline: echo | tr | wc."""
        # node = ShellNode()
        shared = {}

        # Count words after converting spaces to newlines
        run_shell_node(shared, command='echo "one two three four five" | tr " " "\\n" | wc -l')

        output = shared["stdout"].strip()
        assert "5" in output  # Should count 5 words
        assert shared["exit_code"] == 0

    def test_file_content_manipulation(self):
        """Test reading, modifying, and writing file content."""
        # node = ShellNode()
        shared = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, "input.txt")
            output_file = os.path.join(tmpdir, "output.txt")

            # Create input file
            with open(input_file, "w") as f:
                f.write("hello world")

            # Use sed to replace 'world' with 'universe' and save to new file
            run_shell_node(shared, command=f'sed "s/world/universe/g" {input_file} > {output_file}', cwd=tmpdir)
            assert shared["exit_code"] == 0

            # Verify output file content
            with open(output_file) as f:
                assert f.read() == "hello universe"

    def test_find_files_by_pattern(self):
        """Test finding files with specific patterns."""
        # node = ShellNode()
        shared = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files with different extensions
            Path(tmpdir, "file1.txt").touch()
            Path(tmpdir, "file2.py").touch()
            Path(tmpdir, "file3.txt").touch()
            Path(tmpdir, "file4.md").touch()

            # Find all .txt files
            run_shell_node(shared, command='find . -name "*.txt"', cwd=tmpdir)

            assert "file1.txt" in shared["stdout"]
            assert "file3.txt" in shared["stdout"]
            assert "file2.py" not in shared["stdout"]
            assert "file4.md" not in shared["stdout"]
            assert shared["exit_code"] == 0

    @pytest.mark.skipif(platform.system() == "Windows", reason="curl might not be available on Windows")
    def test_curl_command(self):
        """Test that curl can be executed (if available)."""
        # node = ShellNode()
        shared = {}

        # Try to get curl version
        action = run_shell_node(shared, command="curl --version")

        if action == "default":
            assert "curl" in shared["stdout"].lower()
            assert shared["exit_code"] == 0
        else:
            # curl might not be installed, that's okay
            pytest.skip("curl not available on this system")


class TestShellNodeEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_command_raises_error(self):
        """Test that empty command raises ValueError."""
        # node = ShellNode()
        shared = {}

        with pytest.raises(ValueError, match="Missing required 'command' parameter"):
            run_shell_node(shared, command="")

        with pytest.raises(ValueError, match="Missing required 'command' parameter"):
            run_shell_node(shared)  # No command at all

    def test_very_long_output(self):
        """Test handling of commands with very long output."""
        # node = ShellNode()
        shared = {}

        # Generate 1000 lines of output
        if platform.system() == "Windows":
            pytest.skip("seq command not available on Windows")

        run_shell_node(shared, command="seq 1 1000")

        lines = shared["stdout"].strip().split("\n")
        assert len(lines) == 1000
        assert lines[0] == "1"
        assert lines[-1] == "1000"
        assert shared["exit_code"] == 0

    def test_binary_output_handling(self):
        """Test that binary output doesn't crash the node."""
        # node = ShellNode()
        shared = {}

        # Generate some binary data (random bytes)
        if platform.system() == "Windows":
            pytest.skip("dd command not available on Windows")

        # Create small binary output
        run_shell_node(shared, command="dd if=/dev/urandom bs=100 count=1 2>/dev/null | base64")

        # Should handle binary data (converted to base64 for safety)
        assert len(shared["stdout"]) > 0
        assert shared["exit_code"] == 0

    def test_special_characters_in_command(self):
        """Test commands with special characters."""
        # node = ShellNode()
        shared = {}

        # Test with various special characters
        # Note: $# expands to number of arguments (0), so we test differently
        run_shell_node(shared, command='echo "Special chars: @! & | > <"')

        assert "Special chars:" in shared["stdout"]
        assert "@!" in shared["stdout"]
        assert "&" in shared["stdout"]
        assert shared["exit_code"] == 0

    def test_newlines_in_command(self):
        """Test multi-line commands."""
        # node = ShellNode()
        shared = {}

        # Multi-line command with line continuation
        command = """echo "line1" && \\
echo "line2" && \\
echo "line3\""""

        run_shell_node(shared, command=command)

        assert "line1" in shared["stdout"]
        assert "line2" in shared["stdout"]
        assert "line3" in shared["stdout"]
        assert shared["exit_code"] == 0

    def test_exit_command(self):
        """Test using exit with specific codes."""
        # node = ShellNode()
        shared = {}

        # Exit with code 42
        run_shell_node(shared, command="exit 42")

        assert shared["exit_code"] == 42
        assert shared["stdout"] == ""

    def test_stderr_output_capture(self):
        """Test that stderr is properly captured."""
        # node = ShellNode()
        shared = {}

        # Command that writes to stderr
        run_shell_node(shared, command='echo "error message" >&2')

        assert shared["stderr"].strip() == "error message"
        assert shared["stdout"] == ""
        assert shared["exit_code"] == 0

    def test_both_stdout_and_stderr(self):
        """Test commands that produce both stdout and stderr."""
        # node = ShellNode()
        shared = {}

        # Write to both stdout and stderr
        run_shell_node(shared, command='echo "stdout message" && echo "stderr message" >&2')

        assert "stdout message" in shared["stdout"]
        assert "stderr message" in shared["stderr"]
        assert shared["exit_code"] == 0


class TestShellNodeRetryBehavior:
    """Test the retry behavior of ShellNode."""

    def test_node_has_retry_configured(self):
        """Test that ShellNode is configured with retry support."""
        node = ShellNode()

        # Check that max_retries is set to 1 (as per __init__)
        assert node.max_retries == 1
        assert node.wait == 0


class TestStripNewline:
    """Test strip_newline parameter behavior.

    Shell commands typically add trailing newlines (echo, date, hostname).
    By default, these are stripped to match bash $() convention.
    Users can opt-out with strip_newline=false.
    """

    def test_default_strips_trailing_newline(self):
        """Default behavior: echo output has no trailing newline.

        This is the core fix - using ${shell.stdout} in file paths
        should not create filenames with embedded newlines.
        """
        shared = {}
        run_shell_node(shared, command="echo hello")

        # No trailing newline - can safely use in file paths
        assert shared["stdout"] == "hello"
        assert not shared["stdout"].endswith("\n")

    def test_opt_out_preserves_trailing_newline(self):
        """With strip_newline=false, trailing newline is preserved.

        Edge case for users who need exact raw output.
        """
        shared = {}
        run_shell_node(shared, command="echo hello", strip_newline=False)

        # Trailing newline preserved
        assert shared["stdout"] == "hello\n"

    def test_multiline_preserves_internal_newlines(self):
        """Internal newlines are preserved, only trailing stripped.

        Critical: multi-line output must not lose internal structure.
        """
        shared = {}
        run_shell_node(shared, command="printf 'line1\\nline2\\n'")

        # Internal newline preserved, trailing stripped
        assert shared["stdout"] == "line1\nline2"
        assert shared["stdout"].count("\n") == 1

    def test_multiple_trailing_newlines_all_stripped(self):
        """Multiple trailing newlines are all stripped (matches bash).

        bash: x=$(printf 'data\\n\\n\\n') results in x='data'
        """
        shared = {}
        run_shell_node(shared, command="printf 'data\\n\\n\\n'")

        # All trailing newlines stripped
        assert shared["stdout"] == "data"

    def test_empty_stdout_unchanged(self):
        """Empty stdout remains empty after stripping.

        Common scenario: commands with conditional output or no matches.
        """
        shared = {}
        run_shell_node(shared, command="printf ''")  # Empty output

        assert shared["stdout"] == ""
        assert shared["stdout_is_binary"] is False
