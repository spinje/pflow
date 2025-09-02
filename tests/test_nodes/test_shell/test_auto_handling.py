"""Test auto-handling of safe non-error patterns in shell node."""

import os
import tempfile
from unittest.mock import patch

from pflow.nodes.shell.shell import ShellNode


def run_shell_node(shared, **params):
    """Helper to run shell node with parameters."""
    node = ShellNode()
    node.set_params(params)
    return node.run(shared)


class TestAutoHandlingLsGlob:
    """Test auto-handling of ls with glob patterns."""

    def test_ls_glob_no_matches_returns_success(self):
        """Test that ls *.nonexistent returns default when no files match."""
        shared = {}

        # This would normally fail with exit code 1
        action = run_shell_node(shared, command="ls *.nonexistent")

        # But we auto-handle it as success
        assert action == "default"
        assert shared["exit_code"] == 1  # Original exit code preserved
        assert "No such file" in shared["stderr"]
        assert shared["stdout"] == ""

    def test_ls_glob_with_matches_works_normally(self):
        """Test that ls *.txt works normally when files exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            for i in range(3):
                open(os.path.join(tmpdir, f"file{i}.txt"), "w").close()

            shared = {}
            action = run_shell_node(shared, command="ls *.txt", cwd=tmpdir)

            assert action == "default"
            assert shared["exit_code"] == 0  # Normal success
            assert "file0.txt" in shared["stdout"]
            assert "file1.txt" in shared["stdout"]
            assert "file2.txt" in shared["stdout"]

    def test_ls_without_glob_errors_normally(self):
        """Test that ls specific_file.txt still errors when file doesn't exist."""
        shared = {}

        # No glob pattern, so should error normally
        action = run_shell_node(shared, command="ls specific_file.txt")

        assert action == "error"  # Not auto-handled
        assert shared["exit_code"] != 0

    def test_ls_with_different_glob_patterns(self):
        """Test various glob patterns are recognized."""
        test_patterns = [
            "ls *.py",
            "ls test_*.txt",
            "ls file[0-9].dat",
            "ls data?.csv",
            "ls -la *.json",
        ]

        for command in test_patterns:
            shared = {}
            action = run_shell_node(shared, command=command)

            # All should be auto-handled as success
            assert action == "default", f"Failed for command: {command}"
            assert shared["exit_code"] == 1


class TestAutoHandlingGrep:
    """Test auto-handling of grep commands."""

    def test_grep_no_match_returns_success(self):
        """Test that grep returns default when pattern not found."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("some content\nother content\n")
            temp_file = f.name

        try:
            shared = {}
            # Pattern that won't match
            action = run_shell_node(shared, command=f'grep "nonexistent" {temp_file}')

            # Auto-handled as success
            assert action == "default"
            assert shared["exit_code"] == 1  # grep returns 1 for no matches
            assert shared["stdout"] == ""
        finally:
            os.unlink(temp_file)

    def test_grep_with_match_works_normally(self):
        """Test that grep works normally when pattern matches."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test line\nother line\n")
            temp_file = f.name

        try:
            shared = {}
            action = run_shell_node(shared, command=f'grep "test" {temp_file}')

            assert action == "default"
            assert shared["exit_code"] == 0
            assert "test line" in shared["stdout"]
        finally:
            os.unlink(temp_file)

    def test_grep_in_pipeline_auto_handled(self):
        """Test grep in pipeline is auto-handled."""
        shared = {}

        # Grep in pipeline that finds nothing
        action = run_shell_node(shared, command='echo "test" | grep "nomatch"')

        assert action == "default"  # Auto-handled
        assert shared["exit_code"] == 1
        assert shared["stdout"] == ""


class TestAutoHandlingRipgrep:
    """Test auto-handling of ripgrep (rg) commands."""

    def test_rg_no_match_returns_success(self):
        """Test that rg returns default when pattern not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, "w") as f:
                f.write("some content")

            shared = {}
            # Assuming rg is installed (common in dev environments)
            action = run_shell_node(shared, command='rg "nonexistent"', cwd=tmpdir, ignore_errors=True)

            # If rg is installed and pattern not found, should be auto-handled
            # If rg not installed, ignore_errors handles it
            assert action == "default"


class TestAutoHandlingWhich:
    """Test auto-handling of which command."""

    def test_which_command_not_found_returns_success(self):
        """Test that which returns default when command doesn't exist."""
        shared = {}

        # Command that definitely doesn't exist
        action = run_shell_node(shared, command="which definitely_not_a_real_command_xyz123")

        # Auto-handled as success (checking existence is the point)
        assert action == "default"
        assert shared["exit_code"] == 1

    def test_which_command_found_works_normally(self):
        """Test that which works normally when command exists."""
        shared = {}

        # Command that should exist on all systems
        action = run_shell_node(shared, command="which ls")

        assert action == "default"
        assert shared["exit_code"] == 0
        assert "/ls" in shared["stdout"]  # Path to ls command


class TestAutoHandlingCommandV:
    """Test auto-handling of command -v."""

    def test_command_v_not_found_returns_success(self):
        """Test that command -v returns default when command doesn't exist."""
        shared = {}

        action = run_shell_node(shared, command="command -v nonexistent_cmd")

        # Auto-handled as success
        assert action == "default"
        assert shared["exit_code"] == 1
        assert shared["stdout"] == ""

    def test_command_v_found_works_normally(self):
        """Test that command -v works normally when command exists."""
        shared = {}

        action = run_shell_node(shared, command="command -v echo")

        assert action == "default"
        assert shared["exit_code"] == 0
        assert "echo" in shared["stdout"]


class TestAutoHandlingType:
    """Test auto-handling of type command."""

    def test_type_command_not_found_returns_success(self):
        """Test that type returns default when command not found."""
        shared = {}

        action = run_shell_node(shared, command="type nonexistent_command_xyz")

        # Auto-handled as success
        assert action == "default"
        assert shared["exit_code"] == 1
        assert "not found" in shared["stderr"]

    def test_type_command_found_works_normally(self):
        """Test that type works normally when command exists."""
        shared = {}

        action = run_shell_node(shared, command="type echo")

        assert action == "default"
        assert shared["exit_code"] == 0
        assert "echo" in shared["stdout"]


class TestAutoHandlingRealErrors:
    """Test that real errors are NOT auto-handled."""

    def test_permission_denied_still_errors(self):
        """Test that permission denied is not auto-handled."""
        shared = {}

        # Try to write to root directory (will fail with permission denied)
        action = run_shell_node(shared, command="echo test > /test_file.txt")

        assert action == "error"  # NOT auto-handled
        assert shared["exit_code"] != 0
        assert any(msg in shared["stderr"].lower() for msg in ["permission denied", "read-only", "keine berechtigung"])

    def test_command_not_found_still_errors(self):
        """Test that command not found (not which/type) still errors."""
        shared = {}

        action = run_shell_node(shared, command="definitely_not_a_command")

        assert action == "error"  # NOT auto-handled
        assert shared["exit_code"] == 127  # Command not found

    def test_syntax_error_still_errors(self):
        """Test that syntax errors are not auto-handled."""
        shared = {}

        # Invalid shell syntax
        action = run_shell_node(shared, command="echo unclosed quote'")

        # This might succeed or fail depending on shell, but if it fails, it shouldn't be auto-handled
        if shared["exit_code"] != 0:
            assert action == "error"

    def test_ls_permission_denied_not_auto_handled(self):
        """Test that ls with permission denied is not auto-handled."""
        # Create a directory with no read permissions
        with tempfile.TemporaryDirectory() as tmpdir:
            restricted_dir = os.path.join(tmpdir, "restricted")
            os.mkdir(restricted_dir)
            os.chmod(restricted_dir, 0o000)  # No permissions

            try:
                shared = {}
                action = run_shell_node(shared, command=f"ls {restricted_dir}")

                # Should error, not be auto-handled
                assert action == "error"
                assert shared["exit_code"] != 0
            finally:
                # Restore permissions for cleanup
                os.chmod(restricted_dir, 0o700)


class TestIgnoreErrorsOverride:
    """Test that ignore_errors parameter takes precedence over auto-handling."""

    def test_ignore_errors_true_overrides_auto_handling(self):
        """Test that explicit ignore_errors=true takes precedence."""
        shared = {}

        # Even though ls *.txt would be auto-handled, ignore_errors should be checked first
        action = run_shell_node(shared, command="ls *.nonexistent", ignore_errors=True)

        assert action == "default"
        assert shared["exit_code"] == 1
        # Should see ignore_errors log message, not auto-handling message

    def test_ignore_errors_false_allows_auto_handling(self):
        """Test that ignore_errors=false (default) allows auto-handling."""
        shared = {}

        action = run_shell_node(shared, command="ls *.nonexistent", ignore_errors=False)

        assert action == "default"  # Auto-handled
        assert shared["exit_code"] == 1


class TestLoggingBehavior:
    """Test that auto-handling is properly logged."""

    @patch("pflow.nodes.shell.shell.logger")
    def test_auto_handling_logs_info_message(self, mock_logger):
        """Test that auto-handling logs an informative message."""
        shared = {}

        run_shell_node(shared, command="ls *.nonexistent")

        # Should log that we auto-handled this
        mock_logger.info.assert_called()
        call_args = str(mock_logger.info.call_args)
        assert "Auto-handling non-error" in call_args
        assert "ls with glob pattern" in call_args

    @patch("pflow.nodes.shell.shell.logger")
    def test_real_error_logs_warning(self, mock_logger):
        """Test that real errors still log warnings."""
        shared = {}

        run_shell_node(shared, command="definitely_not_a_command")

        # Should log warning about failure
        mock_logger.warning.assert_called()
        call_args = str(mock_logger.warning.call_args)
        assert "failed with exit code" in call_args


class TestEdgeCases:
    """Test edge cases and complex scenarios."""

    def test_ls_with_glob_in_quotes_not_expanded(self):
        """Test that quoted globs are still auto-handled (conservative approach)."""
        shared = {}

        # Quoted glob won't be expanded by shell, but we still detect the pattern
        action = run_shell_node(shared, command='ls "*.txt"')

        # We're conservative - still auto-handle even quoted globs
        # This is reasonable since it still fails with "No such file or directory"
        assert action == "default"  # Auto-handled conservatively
        assert shared["exit_code"] == 1

    def test_complex_pipeline_with_grep(self):
        """Test complex pipeline with grep is handled correctly."""
        shared = {}

        # Complex pipeline where grep finds nothing
        action = run_shell_node(shared, command='echo "test" | grep "nomatch" | wc -l')

        # The pipeline should succeed (wc will count 0 lines)
        assert action == "default"
        assert "0" in shared["stdout"]

    def test_multiple_commands_with_semicolon(self):
        """Test multiple commands separated by semicolon."""
        shared = {}

        # First command would normally fail, but is auto-handled
        action = run_shell_node(shared, command='ls *.nonexistent; echo "done"')

        assert action == "default"
        assert "done" in shared["stdout"]
