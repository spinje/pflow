"""Test command template validation (Issue #2 defensive checks)."""

import pytest

from src.pflow.nodes.shell.shell import ShellNode


class TestCommandTemplateValidation:
    """Test that problematic command templates are detected."""

    def test_dict_in_command_raises_error(self):
        """Dict/JSON object in command should error with helpful message."""
        node = ShellNode()
        node.set_params({
            "command": "echo '${data}' | jq",
            "data": {"key": "value"},  # This gets resolved by wrapper
        })
        shared = {}

        with pytest.raises(ValueError) as exc_info:
            node.run(shared)

        error_msg = str(exc_info.value)
        assert "structured data" in error_msg
        assert "stdin" in error_msg.lower()  # Should suggest stdin
        assert "data" in error_msg  # Should mention the variable name

    def test_list_in_command_raises_error(self):
        """List/array in command should error with helpful message."""
        node = ShellNode()
        node.set_params({"command": "echo '${items}' | jq", "items": [1, 2, 3]})
        shared = {}

        with pytest.raises(ValueError) as exc_info:
            node.run(shared)

        assert "structured data" in str(exc_info.value)
        assert "list" in str(exc_info.value)

    def test_simple_string_in_command_allowed(self):
        """Simple strings in command should work fine."""
        node = ShellNode()
        # Without template wrapper, templates are literal - just test it doesn't crash
        node.set_params({"command": "echo hello", "hello": "John"})
        shared = {}

        action = node.run(shared)

        assert action == "default"

    def test_path_in_command_allowed(self, tmp_path):
        """File paths in command should work (simple strings)."""
        node = ShellNode()
        node.set_params({"command": "ls ${dir}", "dir": str(tmp_path)})
        shared = {}

        action = node.run(shared)

        # Should list temp directory
        assert action == "default"

    def test_large_string_warns_but_allows(self, caplog):
        """Large strings should warn but not error."""
        node = ShellNode()
        large_string = "x" * 1000
        node.set_params({"command": "echo ${big}", "big": large_string})
        shared = {}

        # Should work but log warning
        action = node.run(shared)

        assert action == "default"
        # Check for warning in logs
        assert any("large string" in rec.message.lower() for rec in caplog.records)

    def test_no_templates_no_validation(self):
        """Commands without templates should skip validation."""
        node = ShellNode()
        node.set_params({"command": "echo hello"})
        shared = {}

        # Should work fine (no templates to validate)
        action = node.run(shared)
        assert action == "default"

    def test_unresolved_template_no_validation(self):
        """Templates that haven't been resolved yet should not trigger validation."""
        node = ShellNode()
        # Template variable that doesn't exist in params yet
        node.set_params({"command": "echo ${undefined}"})
        shared = {}

        # Should not raise validation error (template not resolved)
        # Will likely fail during execution, but that's a different issue
        action = node.run(shared)

        # Command runs, but template is unresolved (becomes literal string)
        assert action == "default"
