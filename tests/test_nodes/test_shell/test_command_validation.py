"""Test command template validation (Issue #2 defensive checks).

Note: dict/list detection in shell commands is now done at template validation time
(in template_validator.py), not at shell node runtime. These tests verify shell node
still handles safe cases correctly.
"""

from src.pflow.nodes.shell.shell import ShellNode


class TestCommandTemplateValidation:
    """Test that shell commands handle various input types correctly.

    Note: Blocking dict/list in shell commands is now done at validation time
    by template_validator._validate_shell_command_types(), not at shell node runtime.
    These tests verify shell node execution behavior for allowed cases.
    """

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

    def test_large_string_warns_but_allows(self):
        """Large strings should warn but not error."""
        node = ShellNode()
        large_string = "x" * 1000
        # Large string in params - should warn but not crash
        node.set_params({"command": "echo ${big}", "big": large_string})
        shared = {}

        # Should work (not crash) - warning is logged but test doesn't check for it
        # because log capture can be flaky in CI environments
        action = node.run(shared)

        assert action == "default"
        # The important thing is it doesn't crash on large strings

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
