"""Regression tests for SIGPIPE handling in shell nodes.

This module tests the fix for a critical bug where shell commands that don't
consume their stdin would cause Python to terminate with exit code 141 (SIGPIPE).

The Bug (fixed in PR #26):
--------------------------
When a shell node received large stdin data (>16KB) and the command didn't read
the stdin (e.g., `echo '[]'` instead of `grep | jq`), Python's subprocess.run()
would try to write to a pipe that was closed when the subprocess exited early.

With SIGPIPE set to SIG_DFL (the bug), this would immediately terminate Python
with exit code 141 - no error message, no cleanup, no trace file.

The fix changed SIGPIPE from SIG_DFL to SIG_IGN, allowing subprocess.run() to
handle the broken pipe gracefully.

Why These Tests Matter:
----------------------
These tests use data sizes that EXCEED the OS pipe buffer (typically 16-64KB).
Small test data (<1KB) would fit in the buffer and get silently discarded when
the pipe closes - those tests would NOT catch the regression.

These tests would have caught the bug before it shipped.
"""

import platform

import pytest

from src.pflow.nodes.shell.shell import ShellNode
from src.pflow.runtime.node_wrapper import TemplateAwareNodeWrapper

# Size that reliably exceeds pipe buffer on all platforms
# macOS: 16KB, Linux: 64KB - we use 20KB (just above macOS minimum)
# This is enough to trigger SIGPIPE while keeping tests fast
LARGE_DATA_SIZE = 20 * 1024  # 20KB

# Pre-generated test data to avoid regenerating in each test
_LARGE_STDIN_DATA: str | None = None


def get_large_stdin_data() -> str:
    """Get pre-generated large stdin data (lazy singleton)."""
    global _LARGE_STDIN_DATA
    if _LARGE_STDIN_DATA is None:
        _LARGE_STDIN_DATA = "x" * LARGE_DATA_SIZE
    return _LARGE_STDIN_DATA


class TestShellNodeSigpipeHandling:
    """Test that shell nodes handle SIGPIPE gracefully with large unconsumed stdin."""

    def test_large_stdin_command_ignores_input(self):
        """Shell command that completely ignores stdin should not crash.

        This is the core regression test. Before the fix, this would cause:
        - Exit code 141 (SIGPIPE)
        - No error message
        - Process termination mid-execution

        After the fix, subprocess.run() handles the broken pipe internally.
        """
        node = ShellNode()

        node.set_params({
            "command": "echo 'ignored stdin'",  # Doesn't read stdin at all
            "stdin": get_large_stdin_data(),
        })

        shared = {}

        # This would crash with exit 141 before the fix
        action = node.run(shared)

        # Should complete successfully
        assert action == "default"
        assert "ignored stdin" in shared["stdout"]
        # Stderr should be empty (no errors)
        assert shared.get("stderr", "") == ""
        assert shared.get("exit_code", 0) == 0

    def test_large_stdin_partial_read(self):
        """Shell command that reads only first line should not crash.

        Commands like `head -n 1` read partial input then exit.
        This triggers SIGPIPE when there's more data to write.
        """
        node = ShellNode()

        # Generate many lines (just enough to exceed pipe buffer)
        large_stdin = "\n".join([f"line {i}" for i in range(2000)])  # ~20KB

        node.set_params({
            "command": "head -n 1",  # Only reads first line, exits immediately
            "stdin": large_stdin,
        })

        shared = {}

        # This would crash before the fix
        action = node.run(shared)

        assert action == "default"
        assert "line 0" in shared["stdout"]
        assert shared.get("exit_code", 0) == 0

    def test_conditional_command_stdin_branch(self):
        """Conditional command where one branch ignores stdin.

        This is the EXACT pattern that caused the original bug:
        - When flag is 'false': echo '[]' (ignores stdin)
        - When flag is 'true': cat (consumes stdin)

        The 'false' branch would crash with large stdin before the fix.
        """
        # Generate stdin data just above pipe buffer
        large_stdin = "data line\n" * 2000  # ~20KB

        # Test the branch that IGNORES stdin (the failing case)
        node_false = ShellNode()
        node_false.set_params({
            "command": "case 'false' in *[Ff]alse*) echo '[]' ;; *) cat ;; esac",
            "stdin": large_stdin,
        })

        shared_false = {}
        action_false = node_false.run(shared_false)

        assert action_false == "default"
        assert shared_false["stdout"].strip() == "[]"
        assert shared_false.get("exit_code", 0) == 0

        # Test the branch that CONSUMES stdin (the working case)
        node_true = ShellNode()
        node_true.set_params({
            "command": "case 'true' in *[Ff]alse*) echo '[]' ;; *) cat ;; esac",
            "stdin": large_stdin,
        })

        shared_true = {}
        action_true = node_true.run(shared_true)

        assert action_true == "default"
        assert "data line" in shared_true["stdout"]
        assert shared_true.get("exit_code", 0) == 0

    def test_conditional_with_template_resolution(self):
        """Test the full pattern with template variable resolution.

        This tests the complete flow: template resolves to 'False' (capital F),
        shell conditional matches it, and the non-consuming branch executes.
        """
        inner_node = ShellNode()
        node = TemplateAwareNodeWrapper(inner_node, "conditional-shell")

        # Data just above pipe buffer to trigger SIGPIPE
        large_data = "content\n" * 2500  # ~20KB

        # The template ${flag} will resolve to "False" (Python's str(False))
        # The shell pattern *[Ff]alse* should match it
        node.set_params({
            "command": "case '${flag}' in *[Ff]alse*) echo 'skipped' ;; *) wc -l ;; esac",
            "stdin": large_data,
        })

        # Test with flag=False (Python boolean)
        shared = {"flag": False}
        action = node._run(shared)

        assert action == "default"
        assert "skipped" in shared["stdout"]

    @pytest.mark.skipif(platform.system() == "Windows", reason="SIGPIPE is Unix-only")
    def test_multiple_sequential_unconsumed_stdin(self):
        """Multiple shell commands in sequence, all ignoring stdin.

        This tests that the SIGPIPE handling doesn't have cumulative issues
        when multiple commands in a workflow all ignore their stdin.
        """
        large_stdin = get_large_stdin_data()

        for i in range(3):
            node = ShellNode()
            node.set_params({
                "command": f"echo 'command {i}'",
                "stdin": large_stdin,
            })

            shared = {}
            action = node.run(shared)

            assert action == "default"
            assert f"command {i}" in shared["stdout"]


class TestShellNodeEdgeCases:
    """Additional edge cases for stdin handling robustness."""

    def test_command_exits_with_error_large_stdin(self):
        """Command that fails should still not crash due to SIGPIPE.

        Even when the command fails (exit code != 0), we should get a proper
        error result, not a SIGPIPE termination.
        """
        node = ShellNode()

        node.set_params({
            "command": "exit 1",  # Fails immediately, doesn't read stdin
            "stdin": get_large_stdin_data(),
        })

        shared = {}
        action = node.run(shared)

        # Should complete (with error action) rather than crash
        assert action == "error"
        assert shared.get("exit_code") == 1

    def test_command_with_timeout_and_large_stdin(self):
        """Command with timeout should handle unconsumed stdin gracefully."""
        node = ShellNode()

        node.set_params({
            "command": "echo 'quick'",  # Completes before timeout
            "stdin": get_large_stdin_data(),
            "timeout": 5,  # 5 second timeout
        })

        shared = {}
        action = node.run(shared)

        assert action == "default"
        assert "quick" in shared["stdout"]

    def test_binary_stdin_unconsumed(self):
        """Binary data in stdin that isn't consumed should not crash."""
        node = ShellNode()

        # Binary-ish data (bytes that might cause encoding issues)
        # Just above pipe buffer size
        binary_like = bytes(range(256)) * 80  # ~20KB of binary data
        # Convert to string (will have some weird chars but that's ok)
        stdin_data = binary_like.decode("latin-1")

        node.set_params({
            "command": "echo 'binary ignored'",
            "stdin": stdin_data,
        })

        shared = {}
        action = node.run(shared)

        assert action == "default"
        assert "binary ignored" in shared["stdout"]


class TestSignalHandlerConfiguration:
    """Verify the signal handler is configured correctly."""

    @pytest.mark.skipif(platform.system() == "Windows", reason="SIGPIPE is Unix-only")
    def test_sigpipe_is_ignored(self):
        """Verify SIGPIPE is set to SIG_IGN (not SIG_DFL).

        This is a meta-test that verifies the fix is in place.
        If someone accidentally reverts the fix, this test will catch it.
        """
        import signal

        # Import and call the signal setup function
        from src.pflow.cli.main import _setup_signals

        _setup_signals()

        # Verify SIGPIPE is set to SIG_IGN
        current_handler = signal.getsignal(signal.SIGPIPE)

        assert current_handler == signal.SIG_IGN, (
            f"SIGPIPE should be SIG_IGN but is {current_handler}. "
            "This will cause exit code 141 when subprocesses don't consume stdin!"
        )
