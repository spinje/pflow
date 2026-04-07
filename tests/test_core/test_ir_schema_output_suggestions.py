"""Essential tests for output schema validation error suggestions.

These tests catch REAL bugs that would break agents:
1. Schema suggestions removed → agents stuck
2. Example formatting broken → agents confused
3. False positives → valid workflows blocked
"""

import pytest

from pflow.core.exceptions import SchemaValidationError
from pflow.core.ir_schema import validate_ir


class TestOutputSchemaSuggestions:
    """Test that output validation errors provide helpful suggestions."""

    def test_wrong_field_shows_correction(self):
        """CRITICAL: Agent using 'value' or 'from' gets suggestion to use 'source'.

        Bug prevented: Someone removes output-specific error handling.
        Without this test: Generic error "Remove unknown properties" instead of
        helpful "Did you mean 'source'?" suggestion.
        """
        # Test both common mistakes: 'value' and 'from'
        for wrong_field in ["value", "from"]:
            ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "llm", "params": {}}],
                "outputs": {"result": {wrong_field: "${n1.output}"}},
            }

            with pytest.raises(SchemaValidationError) as exc_info:
                validate_ir(ir)

            error_msg = str(exc_info.value)

            # Should suggest correct field
            assert "source" in error_msg.lower()
            # Should show it's a replacement
            assert "did you mean" in error_msg.lower() or "instead of" in error_msg.lower()

    def test_wrong_type_shows_wrapping(self):
        """CRITICAL: Agent using string instead of object gets wrapping example.

        Bug prevented: Example formatting removed from error message.
        Without this test: Error says "must be object" but doesn't show HOW.
        """
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "llm", "params": {}}],
            "outputs": {"result": "${node.output}"},  # Should be object
        }

        with pytest.raises(SchemaValidationError) as exc_info:
            validate_ir(ir)

        error_msg = str(exc_info.value)

        # Should show both wrong and right examples
        assert "object" in error_msg.lower() or "section" in error_msg.lower()
        assert "wrong" in error_msg.lower() or "right" in error_msg.lower()
        # Should show markdown source param syntax
        assert "- source:" in error_msg

    def test_valid_schema_passes(self):
        """SANITY: Valid output structure passes without errors.

        Bug prevented: False positives (overly strict validation).
        Without this test: Valid workflows get rejected.
        """
        ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "generate_story", "type": "llm", "params": {}}],
            "outputs": {
                "story": {
                    "description": "Generated story",
                    "type": "string",
                    "source": "${generate_story.response}",
                }
            },
        }

        # Should not raise
        validate_ir(ir)


class TestFormatPath:
    """Regression tests for ir_schema._format_path.

    Bug: when an int component preceded a string component, the dot separator
    was suppressed because ``formatted.endswith(']')`` was True. Result: paths
    like ``nodes[0]batch`` instead of ``nodes[0].batch``. The malformed path
    surfaced in every schema validation error that mixed array indices and
    object keys (e.g., batch field type errors).
    """

    def test_int_followed_by_string_inserts_dot(self):
        from pflow.core.ir_schema import _format_path

        assert _format_path([0, "batch"]) == "[0].batch"
        assert _format_path(["nodes", 0, "batch"]) == "nodes[0].batch"
        assert _format_path(["nodes", 0, "params", "command"]) == "nodes[0].params.command"

    def test_string_followed_by_string_inserts_dot(self):
        from pflow.core.ir_schema import _format_path

        assert _format_path(["nodes", "type"]) == "nodes.type"

    def test_consecutive_ints_have_no_dot(self):
        from pflow.core.ir_schema import _format_path

        assert _format_path(["matrix", 0, 1]) == "matrix[0][1]"

    def test_empty_path_renders_root(self):
        from pflow.core.ir_schema import _format_path

        assert _format_path([]) == "root"

    def test_single_int_renders_bracketed(self):
        from pflow.core.ir_schema import _format_path

        assert _format_path([0]) == "[0]"

    def test_real_batch_field_path(self):
        """End-to-end: triggering the bug via validate_ir on a malformed batch field."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "n",
                    "type": "shell",
                    "params": {"command": "echo"},
                    "batch": "${items}",  # batch must be object — this triggers schema error
                }
            ],
        }
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_ir(ir)
        # The path must contain the dot separator between [0] and 'batch'
        assert exc_info.value.path == "nodes[0].batch"
