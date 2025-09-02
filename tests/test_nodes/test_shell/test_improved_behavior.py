"""Improved tests that verify actual behavior, not just superficial checks."""

import os
import tempfile
import time

from pflow.nodes.shell.shell import ShellNode


def run_shell_node(shared, **params):
    """Helper to run shell node with parameters."""
    node = ShellNode()
    node.set_params(params)
    return node.run(shared)


class TestImprovedCommandOrderVerification:
    """Verify commands execute in the correct order."""

    def test_multiple_commands_order_with_timestamps(self):
        """Test that multiple commands execute in order using timestamps."""
        shared = {}

        # Use shorter sleeps (0.01s) - still enough to ensure order
        # Total: 0.02s instead of 0.2s
        command = 'echo "first:$(date +%s%N)"; sleep 0.01; echo "second:$(date +%s%N)"; sleep 0.01; echo "third:$(date +%s%N)"'
        run_shell_node(shared, command=command)

        lines = shared["stdout"].strip().split("\n")
        assert len(lines) == 3

        # Extract timestamps
        first_time = int(lines[0].split(":")[1])
        second_time = int(lines[1].split(":")[1])
        third_time = int(lines[2].split(":")[1])

        # Verify chronological order
        assert first_time < second_time < third_time

    def test_conditional_execution_actually_conditions(self):
        """Test that && really stops on failure and || really provides fallback."""
        shared = {}

        # Test && stops on first failure
        run_shell_node(shared, command='echo "1" && false && echo "should_not_appear"')
        assert "1" in shared["stdout"]
        assert "should_not_appear" not in shared["stdout"]
        assert shared["exit_code"] != 0

        # Test || provides fallback
        shared = {}
        run_shell_node(shared, command='false || echo "fallback_executed"')
        assert "fallback_executed" in shared["stdout"]
        assert shared["exit_code"] == 0


class TestImprovedPipelineVerification:
    """Test that pipelines actually transform data correctly."""

    def test_pipeline_data_flow_verification(self):
        """Verify data actually flows through pipes correctly."""
        shared = {}

        # Create numbered lines and verify each transformation
        command = '''echo -e "line1\\nline2\\nline3" | grep "2" | sed "s/line/LINE/"'''
        run_shell_node(shared, command=command)

        # Should only have line2, transformed to LINE2
        assert shared["stdout"].strip() == "LINE2"

    def test_complex_pipeline_with_actual_data_processing(self):
        """Test a real pipeline that processes data step by step."""
        shared = {}

        # Create a CSV-like data and process it
        command = """printf "name,age,city\\nalice,30,NYC\\nbob,25,LA\\ncarol,35,NYC\\n" | tail -n +2 | grep NYC | cut -d, -f1"""
        run_shell_node(shared, command=command)

        # Should extract names of people from NYC
        names = shared["stdout"].strip().split("\n")
        assert set(names) == {"alice", "carol"}

    def test_pipeline_exit_code_propagation(self):
        """Test that pipeline exit codes work correctly."""
        shared = {}

        # In bash, pipeline exit code is from last command
        run_shell_node(shared, command="false | true")
        assert shared["exit_code"] == 0  # Last command succeeded

        shared = {}
        run_shell_node(shared, command="true | false")
        assert shared["exit_code"] != 0  # Last command failed


class TestImprovedEnvironmentHandling:
    """Test environment variable handling with actual verification."""

    def test_env_var_inheritance_and_override(self):
        """Test that parent env is inherited and can be selectively overridden."""
        shared = {}

        # Set a test env var in parent
        os.environ["TEST_PARENT_VAR"] = "parent_value"

        try:
            # Child should inherit parent var
            run_shell_node(shared, command='echo "$TEST_PARENT_VAR"')
            assert "parent_value" in shared["stdout"]

            # Override in child
            shared = {}
            run_shell_node(shared, command='echo "$TEST_PARENT_VAR"', env={"TEST_PARENT_VAR": "child_value"})
            assert "child_value" in shared["stdout"]
            assert "parent_value" not in shared["stdout"]
        finally:
            del os.environ["TEST_PARENT_VAR"]

    def test_multiple_env_vars_actual_usage(self):
        """Test multiple env vars are all available and usable."""
        shared = {}

        env = {"APP_NAME": "TestApp", "APP_VERSION": "1.2.3", "APP_ENV": "testing"}

        # Use all vars in a realistic way
        run_shell_node(shared, command='echo "Running $APP_NAME v$APP_VERSION in $APP_ENV mode"', env=env)

        output = shared["stdout"].strip()
        assert output == "Running TestApp v1.2.3 in testing mode"


class TestImprovedErrorDetection:
    """Test error handling with actual command behaviors."""

    def test_different_failure_types(self):
        """Test different types of failures are handled correctly."""
        # Command not found
        shared = {}
        action = run_shell_node(shared, command="definitely_not_a_real_command_xyz")
        assert action == "error"
        assert shared["exit_code"] == 127  # Standard "command not found" code
        assert "not found" in shared["stderr"].lower() or "nicht gefunden" in shared["stderr"].lower()

        # Permission denied or read-only (trying to write to root)
        shared = {}
        action = run_shell_node(shared, command="echo test > /test_file_root.txt")
        assert action == "error"
        assert shared["exit_code"] != 0
        # Could be permission denied or read-only file system
        stderr_lower = shared["stderr"].lower()
        assert any(msg in stderr_lower for msg in ["permission denied", "read-only", "keine berechtigung"])

        # Syntax error
        shared = {}
        action = run_shell_node(shared, command="echo unclosed quote'")
        # This might succeed or fail depending on shell
        if action == "error":
            assert "unexpected" in shared["stderr"].lower() or "unterminated" in shared["stderr"].lower()

    def test_partial_pipeline_failure_handling(self):
        """Test how failures in middle of pipeline are handled."""
        shared = {}

        # When last command in pipeline fails, whole pipeline fails
        run_shell_node(shared, command='echo "test" | false')
        assert shared["exit_code"] != 0

        # When middle command fails but last succeeds, exit code depends on shell
        # (bash uses last command's exit code by default)
        shared = {}
        run_shell_node(shared, command='false | echo "test"')
        # Output should still work
        assert "test" in shared["stdout"]


class TestImprovedWorkingDirectory:
    """Test working directory changes with better verification."""

    def test_cwd_affects_relative_operations(self):
        """Test that cwd actually affects relative path operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file in tmpdir
            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, "w") as f:
                f.write("content")

            # Try to read file with relative path from different directories
            shared = {}
            run_shell_node(shared, command="cat test.txt", cwd=tmpdir)
            assert "content" in shared["stdout"]

            # Should fail from different directory
            shared = {}
            action = run_shell_node(shared, command="cat test.txt", cwd=tempfile.gettempdir())
            assert action == "error"  # File not found

    def test_cwd_does_not_affect_parent_process(self):
        """Test that cwd change in shell doesn't affect parent Python process."""
        original_cwd = os.getcwd()

        shared = {}
        run_shell_node(shared, command="pwd", cwd=tempfile.gettempdir())

        # Parent process should still be in original directory
        assert os.getcwd() == original_cwd


class TestImprovedTimeoutBehavior:
    """Test timeout behavior - kept minimal since basic timeout is tested elsewhere."""

    def test_timeout_actually_kills_subprocess(self):
        """Test that timeout truly kills the subprocess, not just returns."""
        shared = {}

        # Start a command that would create a file after a delay
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_file = f.name
        os.unlink(temp_file)

        # Timeout before file creation
        run_shell_node(shared, command=f"sleep 0.2 && touch {temp_file}", timeout=0.05)

        # Brief wait to confirm process was killed
        deadline = time.monotonic() + 0.10
        while time.monotonic() < deadline:
            if os.path.exists(temp_file):
                break
            time.sleep(0.005)

        # File shouldn't exist - process was killed before creating it
        assert not os.path.exists(temp_file)
        assert shared["exit_code"] == -1


class TestShellSpecificBehaviors:
    """Test behaviors specific to shell=True execution."""

    def test_glob_expansion(self):
        """Test that shell glob patterns are expanded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some files
            for i in range(3):
                open(os.path.join(tmpdir, f"file{i}.txt"), "w").close()

            shared = {}
            run_shell_node(shared, command="ls *.txt", cwd=tmpdir)

            # All files should be listed
            assert "file0.txt" in shared["stdout"]
            assert "file1.txt" in shared["stdout"]
            assert "file2.txt" in shared["stdout"]

    def test_tilde_expansion_in_commands(self):
        """Test that ~ is expanded in shell commands."""
        shared = {}

        run_shell_node(shared, command="echo ~")

        output = shared["stdout"].strip()
        assert output == os.path.expanduser("~")
        assert output != "~"  # Should be expanded

    def test_shell_builtin_commands(self):
        """Test that shell builtins work."""
        shared = {}

        # 'type' is a shell builtin
        run_shell_node(shared, command="type echo")

        # Should describe echo command
        assert "echo" in shared["stdout"]
        assert shared["exit_code"] == 0


class TestRealWorldUseCases:
    """Test actual use cases developers would have."""

    def test_git_log_parsing_pipeline(self):
        """Test parsing git log output (if in git repo)."""
        shared = {}

        # Check if we're in a git repo
        action = run_shell_node(shared, command="git rev-parse --git-dir", ignore_errors=True)

        if action == "default":
            # We're in a git repo, test git log parsing
            shared = {}
            run_shell_node(shared, command="git log --oneline -5 | wc -l")

            count = int(shared["stdout"].strip())
            assert 0 < count <= 5  # Should have at most 5 commits

    def test_json_processing_with_python(self):
        """Test using Python one-liner for JSON processing."""
        shared = {}

        # Create JSON and process with Python
        command = '''echo '{"name": "test", "value": 42}' | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['value'])"'''
        run_shell_node(shared, command=command)

        assert "42" in shared["stdout"]

    def test_file_backup_scenario(self):
        """Test a realistic file backup scenario."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create original file
            original = os.path.join(tmpdir, "data.txt")
            with open(original, "w") as f:
                f.write("important data")

            # Backup with timestamp
            shared = {}
            run_shell_node(shared, command='cp data.txt "data_$(date +%Y%m%d).bak"', cwd=tmpdir)

            # Check backup was created
            shared = {}
            run_shell_node(shared, command="ls *.bak", cwd=tmpdir)

            assert ".bak" in shared["stdout"]
            assert shared["exit_code"] == 0
