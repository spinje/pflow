"""Essential tests for output schema validation error suggestions.

These tests catch REAL bugs that would break agents:
1. Schema suggestions removed → agents stuck
2. Example formatting broken → agents confused
3. False positives → valid workflows blocked
"""

import pytest

from pflow.core.ir_schema import ValidationError, validate_ir


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

            with pytest.raises(ValidationError) as exc_info:
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

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir)

        error_msg = str(exc_info.value)

        # Should show both wrong and right examples
        assert "object" in error_msg.lower()
        assert "wrong" in error_msg.lower() or "right" in error_msg.lower()
        # Should show wrapped version with "source"
        assert '"source"' in error_msg

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
