"""Comprehensive tests for the rerun command display feature.

This test module validates the rerun command display functionality, ensuring:
1. Type conversions work correctly (bool, int, float, list, dict, str)
2. Shell escaping handles edge cases properly
3. Command formatting produces correct output
4. Round-trip compatibility (displayed command parses back to same params)
5. Display output format matches specification
"""

from unittest.mock import patch

import pytest

from pflow.cli.main import infer_type, parse_workflow_params
from pflow.cli.rerun_display import (
    display_rerun_commands,
    format_param_value,
    format_rerun_command,
)


class TestFormatParamValue:
    """Test the format_param_value function that converts Python values to CLI strings."""

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            # Booleans - must be lowercase strings
            (True, "true"),
            (False, "false"),
            # Integers
            (0, "0"),
            (42, "42"),
            (-999, "-999"),
            (1234567890, "1234567890"),
            # Floats
            (3.14, "3.14"),
            (0.0, "0.0"),
            (-2.5, "-2.5"),
            (1.23e10, "12300000000.0"),  # Scientific notation converts to regular
            # Lists - compact JSON (no spaces)
            ([], "[]"),
            ([1], "[1]"),
            ([1, 2, 3], "[1,2,3]"),
            (["a", "b"], '["a","b"]'),
            ([True, False], "[true,false]"),  # Booleans in JSON are lowercase
            ([1, "two", 3.0], '[1,"two",3.0]'),
            # Dicts - compact JSON (no spaces after colons)
            ({}, "{}"),
            ({"key": "value"}, '{"key":"value"}'),
            ({"a": 1, "b": 2}, '{"a":1,"b":2}'),
            ({"nested": {"inner": "value"}}, '{"nested":{"inner":"value"}}'),
            ({"bool": True, "num": 42}, '{"bool":true,"num":42}'),
            # Strings - pass through as-is
            ("", ""),
            ("hello", "hello"),
            ("hello world", "hello world"),
            ("with\nnewlines", "with\nnewlines"),
            ('with "quotes"', 'with "quotes"'),
            ("with 'single' quotes", "with 'single' quotes"),
            ("special$chars&here;|", "special$chars&here;|"),
            ("path/to/file.txt", "path/to/file.txt"),
        ],
    )
    def test_type_conversions(self, input_value, expected):
        """Test that all Python types convert to correct CLI strings."""
        result = format_param_value(input_value)
        assert result == expected

    def test_none_handling(self):
        """Test that None values are handled (though typically filtered out)."""
        # None should fallback to string representation
        assert format_param_value(None) == "None"

    def test_unsupported_type_fallback(self):
        """Test that unsupported types fall back to str()."""

        class CustomObject:
            def __str__(self):
                return "custom_object"

        obj = CustomObject()
        assert format_param_value(obj) == "custom_object"


class TestFormatRerunCommand:
    """Test the format_rerun_command function that builds complete CLI commands."""

    def test_no_parameters(self):
        """Test command with no parameters."""
        result = format_rerun_command("my-workflow", None)
        assert result == "pflow my-workflow"

        # Also test with empty dict
        result = format_rerun_command("my-workflow", {})
        assert result == "pflow my-workflow"

    def test_single_parameter(self):
        """Test command with a single parameter."""
        params = {"name": "Alice"}
        result = format_rerun_command("greeting", params)
        assert result == "pflow greeting name=Alice"

    def test_multiple_parameters_order_preserved(self):
        """Test that parameter order is preserved."""
        # Using dict with insertion order (Python 3.7+)
        params = {"first": "1", "second": "2", "third": "3"}
        result = format_rerun_command("test", params)
        assert result == "pflow test first=1 second=2 third=3"

    def test_none_values_skipped(self):
        """Test that None values in params dict are skipped."""
        params = {"keep": "value", "skip": None, "another": "test"}
        result = format_rerun_command("workflow", params)
        assert result == "pflow workflow keep=value another=test"
        assert "skip=" not in result

    def test_no_run_prefix(self):
        """Test that 'run' is NOT included in the command (per spec)."""
        result = format_rerun_command("workflow", {"key": "value"})
        assert result.startswith("pflow workflow")
        assert " run " not in result

    @pytest.mark.parametrize(
        "value,expected_quoted",
        [
            # Simple values that don't need quoting
            ("hello", "hello"),
            ("123", "123"),
            ("true", "true"),
            # Values that need quoting due to spaces
            ("hello world", "'hello world'"),
            ("multiple word string", "'multiple word string'"),
            # Values with quotes that need escaping
            ('She said "hi"', """'She said "hi"'"""),
            ("it's fine", "'it'\"'\"'s fine'"),  # shlex.quote escapes single quotes specially
            # Empty string needs quoting
            ("", "''"),
            # Newlines need escaping
            ("line1\nline2", "'line1\nline2'"),
            # Shell metacharacters
            ("$HOME", "'$HOME'"),
            ("cmd1 && cmd2", "'cmd1 && cmd2'"),
            ("pipe|here", "'pipe|here'"),
            ("semi;colon", "'semi;colon'"),
            ("background&", "'background&'"),
            # JSON strings with special chars
            ('{"key":"value"}', """'{"key":"value"}'"""),
            ("[1,2,3]", "'[1,2,3]'"),
        ],
    )
    def test_shell_escaping(self, value, expected_quoted):
        """Test that shell escaping works correctly for various edge cases."""
        params = {"param": value}
        result = format_rerun_command("test", params)

        # Extract the parameter value from the command
        # Format: "pflow test param=<escaped_value>"
        prefix = "pflow test param="
        assert result.startswith(prefix)
        actual_escaped = result[len(prefix) :]

        assert actual_escaped == expected_quoted

    def test_complex_json_escaping(self):
        """Test escaping of complex JSON with nested quotes."""
        params = {"config": {"message": 'Hello "World"', "count": 42}}
        result = format_rerun_command("workflow", params)

        # The JSON should be compact and properly escaped
        assert "pflow workflow config=" in result
        # Check that the JSON is properly quoted for shell
        assert '\'{"message":"Hello \\"World\\"","count":42}\'' in result


class TestRoundTripCompatibility:
    """Test that displayed commands parse back to the same parameters."""

    @pytest.mark.parametrize(
        "original_params",
        [
            # Simple types
            {"name": "Alice"},
            {"count": 42},
            {"pi": 3.14},
            {"enabled": True},
            {"disabled": False},
            # Complex types
            {"items": [1, 2, 3]},
            {"config": {"key": "value"}},
            # Mixed types
            {
                "name": "test",
                "count": 10,
                "rate": 0.5,
                "active": True,
                "tags": ["a", "b", "c"],
                "settings": {"debug": False, "level": 3},
            },
            # Edge cases
            {"empty_string": ""},
            {"with_spaces": "hello world"},
            {"with_quotes": 'say "hello"'},
            {"with_newline": "line1\nline2"},
            {"shell_chars": "$HOME && echo test"},
            # Complex nested structures
            {
                "nested": {
                    "array": [1, {"inner": "value"}, True],
                    "string": "complex",
                }
            },
            # Deeply nested structure (test depth handling)
            {
                "deep": {
                    "level1": {
                        "level2": {
                            "level3": {"level4": {"value": "deep_value", "items": [1, 2, {"nested_list": ["a", "b"]}]}}
                        }
                    }
                }
            },
        ],
    )
    def test_round_trip(self, original_params):
        """Test that format_rerun_command output can be parsed back to original params.

        This is the most critical test - it ensures that when users copy and paste
        the displayed command, it will execute with exactly the same parameters.

        The test flow:
        1. Start with Python dict of parameters
        2. Format as CLI command using format_rerun_command()
        3. Parse the command as a shell would (using shlex)
        4. Parse the arguments using the actual CLI parser
        5. Verify we get back the exact same parameters
        """
        # Step 1-2: Generate the command from parameters
        command = format_rerun_command("test-workflow", original_params)

        # Step 3: Split command into parts (simulating shell parsing)
        parts = command.split(maxsplit=2)
        assert parts[0] == "pflow"
        assert parts[1] == "test-workflow"

        if len(parts) > 2:
            # Step 3 continued: Parse arguments as shell would
            import shlex

            args_str = parts[2] if len(parts) > 2 else ""
            shell_args = shlex.split(args_str)  # This handles quoted strings properly

            # Step 4: Parse using actual CLI parameter parser
            parsed_params = parse_workflow_params(tuple(shell_args))

            # Step 5: Verify round-trip succeeded
            # Note: Filter out None values as they're skipped in formatting
            filtered_original = {k: v for k, v in original_params.items() if v is not None}

            assert parsed_params == filtered_original, (
                f"Round-trip failed!\nOriginal: {filtered_original}\nParsed:   {parsed_params}\nCommand:  {command}"
            )
        else:
            # No parameters case - verify original had no non-None values
            assert not original_params or all(v is None for v in original_params.values())

    def test_round_trip_with_none_values(self):
        """Test round trip with None values (which should be filtered out)."""
        original = {"keep": "value", "remove": None, "number": 42}
        command = format_rerun_command("workflow", original)

        # Parse back
        import shlex

        parts = command.split(maxsplit=2)
        if len(parts) > 2:
            shell_args = shlex.split(parts[2])
            parsed = parse_workflow_params(tuple(shell_args))

            # Should only have non-None values
            expected = {"keep": "value", "number": 42}
            assert parsed == expected


class TestDisplayRerunCommands:
    """Test the display_rerun_commands function output."""

    @patch("click.echo")
    def test_display_format_no_params(self, mock_echo):
        """Test display output format with no parameters."""
        display_rerun_commands("my-workflow", None)

        # Verify the calls to click.echo
        calls = mock_echo.call_args_list
        assert len(calls) == 4

        # Check the output format
        assert calls[0][0][0] == "\n✨ Run again with:"
        assert calls[1][0][0] == "  $ pflow my-workflow"
        assert calls[2][0][0] == "\n📖 Learn more:"
        assert calls[3][0][0] == "  $ pflow workflow describe my-workflow"

    @patch("click.echo")
    def test_display_format_with_params(self, mock_echo):
        """Test display output format with parameters."""
        params = {"name": "Alice", "count": 42}
        display_rerun_commands("greeting", params)

        calls = mock_echo.call_args_list
        assert len(calls) == 4

        assert calls[0][0][0] == "\n✨ Run again with:"
        assert calls[1][0][0] == "  $ pflow greeting name=Alice count=42"
        assert calls[2][0][0] == "\n📖 Learn more:"
        assert calls[3][0][0] == "  $ pflow workflow describe greeting"

    @patch("click.echo")
    def test_display_with_complex_params(self, mock_echo):
        """Test display with complex parameters requiring escaping."""
        params = {"message": "Hello World", "config": {"debug": True, "level": 3}}
        display_rerun_commands("complex-workflow", params)

        calls = mock_echo.call_args_list
        rerun_line = calls[1][0][0]

        # Should have proper escaping
        assert "  $ pflow complex-workflow" in rerun_line
        assert "'Hello World'" in rerun_line  # Space requires quoting
        assert "'{" in rerun_line  # JSON requires quoting

    @patch("click.echo")
    def test_display_with_realistic_workflow(self, mock_echo):
        """Test display with realistic pflow workflow names and parameters."""
        # Using actual pflow-style workflow name and realistic parameters
        params = {
            "repository": "spinje/pflow",
            "since_date": "2024-01-01",
            "output_file": "CHANGELOG.md",
            "include_prs": True,
            "max_items": 50,
        }
        display_rerun_commands("github-changelog-generator", params)

        calls = mock_echo.call_args_list
        rerun_line = calls[1][0][0]

        # Verify realistic workflow name is used
        assert "github-changelog-generator" in rerun_line
        # Verify all parameters are present
        assert "repository=spinje/pflow" in rerun_line
        assert "since_date=2024-01-01" in rerun_line
        assert "output_file=CHANGELOG.md" in rerun_line
        assert "include_prs=true" in rerun_line  # Boolean lowercase
        assert "max_items=50" in rerun_line


class TestSecurityAndStress:
    """Test security scenarios and stress conditions."""

    def test_command_injection_attempts(self):
        """Test that command injection attempts are properly escaped.

        This is critical for security - ensures malicious parameter values
        cannot execute arbitrary commands.
        """
        injection_attempts = {
            # Attempt to chain commands (using echo instead of rm for safety)
            "cmd_chain": "value; echo malicious",
            "pipe": "value | cat /etc/hosts",
            "background": "value & malicious_command",
            "and_chain": "value && evil_command",
            "or_chain": "value || fallback_attack",
            # Attempt to use shell variables
            "env_var": "$PATH",
            "home_expansion": "~/.ssh/config",
            "command_sub": "$(whoami)",
            "backticks": "`date`",
            # Attempt to break out of quotes
            "quote_escape": "'; echo 'hacked",
            "double_quote": '" ; echo "hacked',
        }

        command = format_rerun_command("secure-workflow", injection_attempts)

        # Verify all dangerous characters are safely escaped
        # The semicolon should be inside quotes, not executable
        assert "'; echo malicious'" in command or "'value; echo malicious'" in command

        # Test round-trip to ensure escaped values don't execute
        import shlex

        parts = shlex.split(command)
        # If escaping works, we should get exactly the parameter count + 2 (pflow, workflow-name)
        assert len(parts) == len(injection_attempts) + 2

        # Parse back and verify values are preserved but safe
        param_args = parts[2:]
        parsed = parse_workflow_params(tuple(param_args))

        # All injection attempts should be treated as literal strings
        assert parsed["cmd_chain"] == "value; echo malicious"
        assert parsed["env_var"] == "$PATH"  # Not expanded
        assert parsed["command_sub"] == "$(whoami)"  # Not executed

    def test_stress_many_parameters(self):
        """Test command formatting with many parameters (stress test).

        Ensures the system handles workflows with numerous parameters
        without performance degradation or formatting issues.
        """
        # Create 100 parameters with various types
        many_params = {}
        for i in range(100):
            if i % 5 == 0:
                many_params[f"param_{i}"] = f"string_value_{i}"
            elif i % 5 == 1:
                many_params[f"param_{i}"] = i
            elif i % 5 == 2:
                many_params[f"param_{i}"] = float(i) / 3.14
            elif i % 5 == 3:
                many_params[f"param_{i}"] = i % 2 == 0
            else:
                many_params[f"param_{i}"] = [i, i + 1, i + 2]

        # Should handle formatting without issues
        command = format_rerun_command("stress-test-workflow", many_params)

        # Verify command is well-formed
        assert command.startswith("pflow stress-test-workflow")

        # Verify round-trip works even with many parameters
        import shlex

        parts = shlex.split(command)
        param_args = parts[2:]
        parsed = parse_workflow_params(tuple(param_args))

        # All parameters should round-trip correctly
        assert len(parsed) == 100
        assert parsed["param_0"] == "string_value_0"
        assert parsed["param_1"] == 1
        assert parsed["param_50"] == "string_value_50"
        assert parsed["param_99"] == [99, 100, 101]


class TestSecurityFeatures:
    """Test security-related features like secret masking."""

    def test_sensitive_parameter_masking(self):
        """Test that sensitive parameters are masked in display."""
        sensitive_params = {
            "api_key": "sk-1234567890abcdef",
            "password": "supersecret123",
            "token": "ghp_abcdefghijklmnop",
            "normal_param": "visible_value",
        }
        result = format_rerun_command("secure-workflow", sensitive_params)

        # Sensitive values should be masked
        assert "api_key=<REDACTED>" in result
        assert "password=<REDACTED>" in result
        assert "token=<REDACTED>" in result

        # Normal params should be visible
        assert "normal_param=visible_value" in result

        # Actual secrets should NOT appear
        assert "sk-1234567890abcdef" not in result
        assert "supersecret123" not in result
        assert "ghp_abcdefghijklmnop" not in result

    def test_case_insensitive_secret_detection(self):
        """Test that secret detection is case-insensitive."""
        params = {"API_KEY": "secret1", "Password": "secret2", "TOKEN": "secret3"}
        result = format_rerun_command("test", params)

        # All should be masked regardless of case
        assert "API_KEY=<REDACTED>" in result
        assert "Password=<REDACTED>" in result
        assert "TOKEN=<REDACTED>" in result

        # No actual secrets visible
        assert "secret1" not in result
        assert "secret2" not in result
        assert "secret3" not in result

    def test_common_secret_patterns(self):
        """Test various common secret parameter names."""
        secret_keys = [
            "password",
            "passwd",
            "pwd",
            "token",
            "api_token",
            "access_token",
            "auth_token",
            "api_key",
            "apikey",
            "api-key",
            "secret",
            "client_secret",
            "private_key",
            "ssh_key",
            "secret_key",
        ]

        for key in secret_keys:
            params = {key: "sensitive_value"}
            result = format_rerun_command("test", params)
            assert f"{key}=<REDACTED>" in result
            assert "sensitive_value" not in result


class TestEdgeCases:
    """Test edge cases and potential bugs."""

    def test_workflow_name_with_special_chars(self):
        """Test workflow names that might need escaping."""
        # Workflow names should be valid identifiers, but test anyway
        result = format_rerun_command("my-workflow-v2", {"key": "value"})
        assert result == "pflow my-workflow-v2 key=value"

    def test_very_long_parameter_values(self):
        """Test handling of very long parameter values."""
        long_string = "x" * 1000
        params = {"data": long_string}
        result = format_rerun_command("test", params)

        assert f"pflow test data={long_string}" == result

    def test_unicode_in_parameters(self):
        """Test Unicode characters in parameter values."""
        params = {"emoji": "🎉🎊", "chinese": "你好世界", "mixed": "Hello 世界 🌍"}
        result = format_rerun_command("international", params)

        # Should handle Unicode correctly
        assert "🎉🎊" in result
        assert "你好世界" in result
        assert "Hello 世界 🌍" in result

    def test_parameter_key_with_underscore(self):
        """Test parameter keys with underscores (common pattern)."""
        params = {"output_file": "output/test.txt", "max_retries": 3}
        result = format_rerun_command("workflow", params)

        assert "output_file=output/test.txt" in result
        assert "max_retries=3" in result

    def test_internal_parameters_filtered(self):
        """Test that internal parameters starting with __ are filtered out."""
        params = {
            "user_param": "value1",
            "count": 42,
            "__verbose__": False,
            "__planner_cache_chunks__": ["chunk1", "chunk2"],
            "__internal_flag__": True,
            "normal_param": "normal_value",
        }

        result = format_rerun_command("my-workflow", params)

        # Should include normal parameters
        assert "user_param=value1" in result
        assert "count=42" in result
        assert "normal_param=normal_value" in result

        # Should NOT include internal parameters
        assert "__verbose__" not in result
        assert "__planner_cache_chunks__" not in result
        assert "__internal_flag__" not in result
        assert "chunk1" not in result  # Content from internal params

    def test_real_world_internal_params_bug(self):
        """Test the specific bug where __verbose__ and __planner_cache_chunks__ were shown."""
        # This reproduces the exact scenario from the bug report
        params = {
            "message_count": 10,
            "slack_channel_id": "C09C16NAU5B",
            "google_sheets_id": "1rWrTSw0XT1D-e5XsrerWgupqEs-1Mtj-fT6e_kKYjek",
            "sheet_name": "Sheet1",
            "date_format": "%Y-%m-%d",
            "time_format": "%H:%M:%S",
            "__verbose__": False,
            "__planner_cache_chunks__": [
                {"text": "# Workflow System Overview\n\nYou are a specialized workflow planner..."},
            ],
        }

        result = format_rerun_command("slack-ai-qa-logger", params)

        # Should include user parameters
        assert "message_count=10" in result
        assert "slack_channel_id=C09C16NAU5B" in result
        assert "google_sheets_id=1rWrTSw0XT1D-e5XsrerWgupqEs-1Mtj-fT6e_kKYjek" in result
        assert "sheet_name=Sheet1" in result
        assert "%Y-%m-%d" in result  # Date format
        assert "%H:%M:%S" in result  # Time format

        # Should NOT include internal parameters
        assert "__verbose__" not in result
        assert "__planner_cache_chunks__" not in result
        assert "false" not in result  # __verbose__ value
        assert "Workflow System Overview" not in result  # Content from cache chunks

    def test_float_precision(self):
        """Test that float precision is preserved."""
        params = {"pi": 3.14159265359, "large": 1234567.89}
        result = format_rerun_command("math", params)

        # Check precision is maintained
        assert "pi=3.14159265359" in result
        assert "large=1234567.89" in result

        # Note: Very small floats may use scientific notation (Python's str() behavior)
        # This is acceptable as it parses back correctly
        params_with_small = {"small": 0.000001}
        result_small = format_rerun_command("test", params_with_small)
        # Python's str() may output as 1e-06 for very small numbers
        assert "small=" in result_small  # Just verify it's there

    def test_boolean_in_json_structures(self):
        """Test that booleans in JSON structures are lowercase."""
        params = {"flags": [True, False, True], "config": {"enabled": True, "debug": False}}
        result = format_rerun_command("test", params)

        # Booleans in JSON should be lowercase
        assert "[true,false,true]" in result
        assert '"enabled":true' in result
        assert '"debug":false' in result

    def test_empty_json_structures(self):
        """Test empty lists and dicts."""
        params = {"empty_list": [], "empty_dict": {}, "not_empty": "value"}
        result = format_rerun_command("test", params)

        # Empty JSON structures get quoted by shlex.quote
        assert "empty_list='[]'" in result
        assert "empty_dict='{}'" in result
        assert "not_empty=value" in result


class TestIntegrationWithCLI:
    """Integration tests verifying the display works with actual CLI functions."""

    def test_infer_type_compatibility(self):
        """Test that format_param_value output is compatible with infer_type."""
        test_cases = [
            (True, "true"),
            (False, "false"),
            (42, "42"),
            (3.14, "3.14"),
            ([1, 2, 3], "[1,2,3]"),
            ({"key": "value"}, '{"key":"value"}'),
            ("hello", "hello"),
        ]

        for original_value, cli_string in test_cases:
            # Format the value for CLI
            formatted = format_param_value(original_value)
            assert formatted == cli_string

            # Parse it back
            parsed = infer_type(formatted)
            assert parsed == original_value

    def test_parse_workflow_params_compatibility(self):
        """Test that generated commands work with parse_workflow_params."""
        original_params = {
            "string": "hello world",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
        }

        # Generate command
        command = format_rerun_command("test", original_params)

        # Simulate shell parsing
        import shlex

        parts = shlex.split(command)

        # Skip "pflow" and "test" to get just the params
        param_args = parts[2:]  # Everything after "pflow test"

        # Parse back
        parsed = parse_workflow_params(tuple(param_args))

        assert parsed == original_params

    def test_special_characters_full_cycle(self):
        """Test full cycle with special characters."""
        tricky_params = {
            "path": "/home/user/my files/test.txt",
            "command": "echo 'hello' && ls",
            "json": {"msg": 'Say "Hi"'},
        }

        # Generate command
        command = format_rerun_command("workflow", tricky_params)

        # Parse back through shell
        import shlex

        parts = shlex.split(command)
        param_args = parts[2:]
        parsed = parse_workflow_params(tuple(param_args))

        assert parsed == tricky_params
