"""Test shell node stdin parameter handling.

Tests verify that the ShellNode correctly handles stdin from params,
including template-resolved values (set directly as resolved params).
"""

from src.pflow.nodes.shell.shell import ShellNode


class TestShellStdinParameterFallback:
    """Test that stdin follows parameter fallback pattern."""

    def test_stdin_from_params_only(self):
        """Stdin should work when provided via params."""
        node = ShellNode()
        node.set_params({"command": "cat", "stdin": "hello from params"})
        shared = {}

        action = node.run(shared)

        assert action == "default"
        assert shared["stdout"] == "hello from params"

    def test_stdin_not_read_from_shared_store(self):
        """Stdin in shared store should NOT be read by node (removed fallback)."""
        node = ShellNode()
        node.set_params({"command": "cat"})
        shared = {"stdin": "hello from shared"}

        action = node.run(shared)

        # Node should NOT read stdin from shared store
        assert action == "default"
        assert shared["stdout"] == ""  # No stdin provided to cat

    def test_stdin_from_params_not_overridden_by_shared(self):
        """Stdin from params should be used (shared store is ignored)."""
        node = ShellNode()
        node.set_params({"command": "cat", "stdin": "from params"})
        shared = {"stdin": "from shared"}  # This should be ignored

        action = node.run(shared)

        assert action == "default"
        assert shared["stdout"] == "from params"  # Params value used

    def test_stdin_with_resolved_template_value(self):
        """Resolved template values in stdin should work correctly.

        Simulates the result of template resolution (e.g., ${input_data} -> "resolved template value")
        by setting the resolved value directly as a param.
        """
        node = ShellNode()
        node.set_params({
            "command": "cat",
            "stdin": "resolved template value",
        })
        shared = {}

        action = node.run(shared)

        assert action == "default"
        assert shared["stdout"] == "resolved template value"

    def test_stdin_with_json_data(self):
        """JSON data via stdin should work, including special characters."""
        node = ShellNode()

        json_data = '{"key": "value with \'quotes\' and special $chars"}'

        node.set_params({"command": "jq -r '.key'", "stdin": json_data})

        shared = {}

        action = node.run(shared)

        assert action == "default"
        assert "quotes" in shared["stdout"]
        assert "special" in shared["stdout"]

    def test_stdin_empty_string_is_valid(self):
        """Empty string should be valid stdin value."""
        node = ShellNode()
        node.set_params({
            "command": "wc -c",
            "stdin": "",  # Count characters
        })
        shared = {}

        action = node.run(shared)

        assert action == "default"
        assert shared["stdout"].strip() == "0"  # Zero bytes

    def test_stdin_none_means_no_input(self):
        """None stdin should mean no input to command."""
        node = ShellNode()
        node.set_params({
            "command": "cat"  # Will output nothing if no stdin
        })
        shared = {}  # No stdin

        action = node.run(shared)

        assert action == "default"
        assert shared["stdout"] == ""  # No output


class TestShellStdinWithComplexData:
    """Test stdin handles complex data correctly (real-world scenarios)."""

    def test_mcp_json_response_via_stdin(self):
        """Simulate MCP node output piped to shell for processing."""
        node = ShellNode()

        # Simulated MCP response (JSON string with nested data)
        mcp_result = '{"successful":true,"data":{"url":"https://open.spotify.com/track/xyz"}}'

        node.set_params({"stdin": mcp_result, "command": "jq -r '.data.url'"})

        shared = {}

        action = node.run(shared)

        assert action == "default"
        assert "https://open.spotify.com/track/xyz" in shared["stdout"]

    def test_multiline_text_via_stdin(self):
        """Multiline text should pass through stdin correctly."""
        node = ShellNode()

        multiline_text = """Line 1: normal
Line 2: with 'quotes'
Line 3: with "double quotes"
Line 4: with $variables
Line 5: with `backticks`"""

        node.set_params({
            "stdin": multiline_text,
            "command": "grep -c 'quotes'",  # Count lines with 'quotes'
        })

        shared = {}

        action = node.run(shared)

        assert action == "default"
        assert shared["stdout"].strip() == "2"  # Lines 2 and 3
