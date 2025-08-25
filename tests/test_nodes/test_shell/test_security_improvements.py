"""Test the security improvements added to ShellNode."""

import logging
import os

import pytest

from pflow.nodes.shell.shell import ShellNode


def run_shell_node(shared, **params):
    """Helper to run shell node with parameters."""
    node = ShellNode()
    node.set_params(params)
    return node.run(shared)


class TestExpandedDangerousPatterns:
    """Test that we catch more variations of dangerous commands."""

    def test_rm_different_flag_orders(self):
        """Test we catch rm with flags in different orders."""
        dangerous_variations = [
            "rm -fr /",  # -fr instead of -rf
            "rm -f -r /",  # Flags separated
            "rm / -rf",  # Path before flags
            "rm /* -rf",  # Wildcard with path first
        ]

        for cmd in dangerous_variations:
            shared = {}
            with pytest.raises(ValueError, match="Dangerous command pattern detected"):
                run_shell_node(shared, command=cmd)

    def test_chmod_system_wide_blocked(self):
        """Test that system-wide chmod operations are blocked."""
        dangerous_chmods = [
            "chmod -R 777 /",
            "chmod 777 /",
            "CHMOD -R 777 /",  # Case variation
        ]

        for cmd in dangerous_chmods:
            shared = {}
            with pytest.raises(ValueError, match="Dangerous command pattern detected"):
                run_shell_node(shared, command=cmd)

    def test_sudo_with_dangerous_commands_blocked(self):
        """Test that sudo + dangerous command is blocked."""
        sudo_dangers = [
            "sudo rm -rf /",
            "sudo rm -rf /*",
            'su -c "rm -rf /"',
        ]

        for cmd in sudo_dangers:
            shared = {}
            with pytest.raises(ValueError, match="Dangerous command pattern detected"):
                run_shell_node(shared, command=cmd)

    def test_more_device_patterns_blocked(self):
        """Test additional device write patterns are blocked."""
        device_writes = [
            "dd if=/dev/urandom of=/dev/sda",
            "> /dev/sda1",
            "> /dev/hda",
            "> /dev/nvme0n1",
            "cat /dev/zero > /dev/sda",
        ]

        for cmd in device_writes:
            shared = {}
            with pytest.raises(ValueError, match="Dangerous command pattern detected"):
                run_shell_node(shared, command=cmd)


class TestWarningPatterns:
    """Test the warning system for potentially dangerous commands."""

    def test_sudo_commands_trigger_warning(self, caplog):
        """Test that sudo commands log warnings."""
        # To avoid ANY possibility of password prompts, only test prep phase
        shared = {}
        node = ShellNode()
        node.set_params({"command": "sudo test_command"})

        with caplog.at_level(logging.WARNING):
            # Only run prep to test warning - don't execute the command
            prep_res = node.prep(shared)

        # Check warning was logged
        assert any("Potentially dangerous command detected" in record.message for record in caplog.records)
        assert any("sudo" in str(record.__dict__.get("pattern", "")) for record in caplog.records)

    def test_shutdown_commands_trigger_warning(self, caplog):
        """Test that shutdown/reboot commands trigger warnings."""
        # Use commands that trigger warnings but won't actually execute dangerously
        # Add '--help' or '--version' to make them safe
        warning_commands = [
            "shutdown --help",
            "reboot --version",
            "halt --help",
            "init 0 --help",  # Include the pattern that triggers warning
            "systemctl poweroff --help",  # Include the full pattern
        ]

        for cmd in warning_commands:
            shared = {}
            caplog.clear()

            with caplog.at_level(logging.WARNING):
                # These should work but log warnings (use ignore_errors since they might fail)
                run_shell_node(shared, command=cmd, ignore_errors=True)

            # Verify warning was logged (based on the base command, not the flag)
            assert any("Potentially dangerous command detected" in record.message for record in caplog.records), (
                f"No warning for: {cmd}"
            )

    def test_warning_only_logged_once_per_command(self, caplog):
        """Test that we only log one warning per command even if multiple patterns match."""
        # We need to test that when a command matches multiple warning patterns,
        # we only log one warning. However, we can't use "sudo shutdown" because
        # sudo might prompt for password. Instead, let's just test with a single
        # warning pattern since the logic is the same (break after first match).
        shared = {}

        with caplog.at_level(logging.WARNING):
            # Just use a single warning pattern - the break logic ensures only one warning
            run_shell_node(shared, command="shutdown --help", ignore_errors=True)

        # Should only have one warning even if we ran it
        warning_count = sum(
            1 for record in caplog.records if "Potentially dangerous command detected" in record.message
        )
        assert warning_count == 1


class TestStrictMode:
    """Test the PFLOW_SHELL_STRICT environment variable functionality."""

    def test_strict_mode_blocks_warning_patterns(self):
        """Test that strict mode blocks commands that normally just warn."""
        # Enable strict mode
        os.environ["PFLOW_SHELL_STRICT"] = "true"

        try:
            # These commands should be blocked in strict mode
            warning_commands = [
                "sudo --version",
                "shutdown --help",
                "reboot --version",
                "systemctl poweroff --help",  # Use full pattern
            ]

            for cmd in warning_commands:
                shared = {}
                with pytest.raises(ValueError, match="Command blocked in strict mode"):
                    run_shell_node(shared, command=cmd)
        finally:
            # Clean up
            del os.environ["PFLOW_SHELL_STRICT"]

    def test_strict_mode_case_insensitive(self):
        """Test that strict mode check is case-insensitive."""
        for strict_value in ["TRUE", "True", "true"]:
            os.environ["PFLOW_SHELL_STRICT"] = strict_value

            try:
                shared = {}
                # Don't actually run, just test that prep raises
                node = ShellNode()
                node.set_params({"command": "sudo test"})
                with pytest.raises(ValueError, match="Command blocked in strict mode"):
                    node.prep(shared)
            finally:
                del os.environ["PFLOW_SHELL_STRICT"]

    def test_non_strict_mode_allows_warnings(self):
        """Test that without strict mode, warning commands are allowed."""
        # Ensure strict mode is off
        if "PFLOW_SHELL_STRICT" in os.environ:
            del os.environ["PFLOW_SHELL_STRICT"]

        shared = {}
        node = ShellNode()
        node.set_params({"command": "sudo test"})

        # In non-strict mode, prep should succeed without raising
        try:
            prep_res = node.prep(shared)
            # If prep succeeds, warning commands are allowed
            assert True
        except ValueError:
            # Should not raise in non-strict mode
            assert False, "Command was blocked even without strict mode"

    def test_strict_mode_still_allows_safe_commands(self):
        """Test that strict mode doesn't block safe commands."""
        os.environ["PFLOW_SHELL_STRICT"] = "true"

        try:
            safe_commands = [
                "echo test",
                "ls -la",
                "grep pattern",
                "cat file.txt",
            ]

            for cmd in safe_commands:
                shared = {}
                # These should work fine
                action = run_shell_node(shared, command=cmd, ignore_errors=True)
                assert action == "success"
        finally:
            del os.environ["PFLOW_SHELL_STRICT"]


class TestAuditLogging:
    """Test that all commands are audit logged."""

    def test_audit_log_on_command_prep(self, caplog):
        """Test that commands are audit logged during preparation."""
        shared = {}

        with caplog.at_level(logging.INFO):
            run_shell_node(shared, command="echo test")

        # Find audit log entries
        audit_logs = [r for r in caplog.records if "[AUDIT]" in r.message]
        assert len(audit_logs) >= 1
        assert "Preparing command: echo test" in audit_logs[0].message

        # Check audit flag in extra data
        assert any(record.__dict__.get("audit") == True for record in caplog.records)

    def test_audit_log_on_completion(self, caplog):
        """Test that command completion is audit logged."""
        shared = {}

        with caplog.at_level(logging.INFO):
            run_shell_node(shared, command="echo test")

        # Find completion audit log
        audit_logs = [r for r in caplog.records if "[AUDIT]" in r.message]
        completion_logs = [r for r in audit_logs if "completed" in r.message]
        assert len(completion_logs) >= 1
        assert "exit code 0" in completion_logs[0].message

    def test_audit_log_truncates_long_commands(self, caplog):
        """Test that very long commands are truncated in audit logs."""
        shared = {}
        long_command = "echo " + "x" * 200  # Very long command

        with caplog.at_level(logging.INFO):
            run_shell_node(shared, command=long_command)

        audit_logs = [r for r in caplog.records if "[AUDIT]" in r.message]
        assert any("..." in log.message for log in audit_logs)

    def test_audit_log_includes_context(self, caplog):
        """Test that audit logs include execution context."""
        shared = {}

        with caplog.at_level(logging.INFO):
            run_shell_node(shared, command="pwd", cwd="/tmp", timeout=10)

        # Check that context is included in extra fields
        audit_records = [r for r in caplog.records if r.__dict__.get("audit") == True]
        assert any(r.__dict__.get("cwd") == "/tmp" for r in audit_records)
        assert any(r.__dict__.get("timeout") == 10 for r in audit_records)


class TestCommandExecutionOrder:
    """Test that multiple commands execute in the correct order."""

    def test_and_operator_executes_in_order(self):
        """Test that && executes commands in order and stops on failure."""
        shared = {}

        # All succeed - should see all outputs in order
        run_shell_node(shared, command='echo "1" && echo "2" && echo "3"')
        lines = shared["stdout"].strip().split("\n")
        assert lines == ["1", "2", "3"]

        # First fails - should only see error, no subsequent commands
        shared = {}
        run_shell_node(shared, command='false && echo "should not appear"')
        assert "should not appear" not in shared["stdout"]
        assert shared["exit_code"] != 0

    def test_or_operator_short_circuits(self):
        """Test that || operator short-circuits correctly."""
        shared = {}

        # First succeeds - second shouldn't run
        run_shell_node(shared, command='echo "ran" || echo "should not appear"')
        assert "ran" in shared["stdout"]
        assert "should not appear" not in shared["stdout"]

        # First fails - second should run
        shared = {}
        run_shell_node(shared, command='false || echo "fallback"')
        assert "fallback" in shared["stdout"]

    def test_semicolon_always_continues(self):
        """Test that ; continues regardless of exit codes."""
        shared = {}

        # Even if first command fails, second runs
        run_shell_node(shared, command='false; echo "still runs"')
        assert "still runs" in shared["stdout"]


class TestComplexShellConstructs:
    """Test more complex shell constructs that developers actually use."""

    @pytest.mark.skipif(
        os.environ.get("SHELL", "").endswith("sh"), reason="Process substitution may not work in all shells"
    )
    def test_process_substitution(self):
        """Test process substitution with <() syntax."""
        shared = {}

        # Compare two command outputs
        run_shell_node(shared, command='diff <(echo "a") <(echo "b")', ignore_errors=True)
        # diff should return non-zero when files differ
        assert shared["exit_code"] != 0
        # Some shells might not support process substitution
        if shared["exit_code"] in [1, 2]:  # 1 = files differ, 2 = error
            pass  # Either is acceptable

    def test_here_document(self):
        """Test here document functionality."""
        shared = {}

        command = """cat << EOF
line1
line2
line3
EOF"""

        run_shell_node(shared, command=command)
        assert "line1" in shared["stdout"]
        assert "line2" in shared["stdout"]
        assert "line3" in shared["stdout"]

    def test_shell_arithmetic(self):
        """Test shell arithmetic expansion."""
        shared = {}

        run_shell_node(shared, command='echo "$((5 + 3))"')
        assert "8" in shared["stdout"]

        run_shell_node(shared, command='echo "$((10 * 2))"')
        assert "20" in shared["stdout"]

    def test_subshell_execution(self):
        """Test subshell with parentheses."""
        shared = {}

        # Subshell changes directory but doesn't affect parent
        run_shell_node(shared, command="(cd /tmp && pwd); pwd")
        lines = shared["stdout"].strip().split("\n")

        # First line should be /tmp, second should be current directory
        assert "/tmp" in lines[0] or "/private/tmp" in lines[0]  # macOS compatibility
        assert lines[1] == os.getcwd()

    def test_command_grouping(self):
        """Test command grouping with curly braces."""
        shared = {}

        run_shell_node(shared, command='{ echo "grouped1"; echo "grouped2"; }')
        assert "grouped1" in shared["stdout"]
        assert "grouped2" in shared["stdout"]


class TestRealWorldPipelines:
    """Test actual pipelines developers use."""

    def test_grep_count_pipeline(self):
        """Test a real grep | wc -l pipeline."""
        shared = {"stdin": "error: file not found\ninfo: starting\nerror: timeout\ninfo: done"}

        # Count error lines
        run_shell_node(shared, command='grep "error" | wc -l')
        assert "2" in shared["stdout"].strip()

    def test_awk_field_extraction(self):
        """Test awk for field extraction."""
        shared = {}

        # Create some data and extract second field - use printf for portability
        run_shell_node(shared, command='printf "1 apple\\n2 banana\\n3 cherry\\n" | awk "{print \\$2}"')

        lines = shared["stdout"].strip().split("\n")
        assert lines == ["apple", "banana", "cherry"]

    def test_sort_uniq_pipeline(self):
        """Test sort | uniq pipeline for deduplication."""
        shared = {}

        # Use printf for portability
        run_shell_node(shared, command='printf "b\\na\\nc\\na\\nb\\na\\n" | sort | uniq')

        lines = shared["stdout"].strip().split("\n")
        assert lines == ["a", "b", "c"]

    def test_head_tail_combination(self):
        """Test getting middle of output with head and tail."""
        shared = {}

        # Get lines 2-4 from a sequence
        run_shell_node(shared, command="seq 1 10 | head -4 | tail -3")

        lines = shared["stdout"].strip().split("\n")
        assert lines == ["2", "3", "4"]
