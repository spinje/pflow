"""Tests for JSON parsing utilities.

Focus on high-value tests that verify real behavior:
1. Valid JSON parsing (the main use case)
2. Invalid JSON graceful fallback (user experience)
3. Whitespace handling (shell output reality)
4. Size limit enforcement (security)
5. Distinguishing parsed-None vs parse-failure (API correctness)
"""

from pflow.core.json_utils import try_parse_json


class TestTryParseJson:
    """Tests for try_parse_json() function."""

    def test_parses_valid_json_object(self):
        """Main use case: parse JSON object strings."""
        success, result = try_parse_json('{"name": "Alice", "age": 30}')

        assert success is True
        assert result == {"name": "Alice", "age": 30}

    def test_parses_valid_json_array(self):
        """Main use case: parse JSON array strings."""
        success, result = try_parse_json('[1, 2, {"id": 3}]')

        assert success is True
        assert result == [1, 2, {"id": 3}]

    def test_invalid_json_returns_original(self):
        """Critical: invalid JSON should return original string, not raise."""
        original = "this is not json"
        success, result = try_parse_json(original)

        assert success is False
        assert result is original  # Same object, not just equal

    def test_partial_json_returns_original(self):
        """Malformed JSON should fail gracefully."""
        original = '{"incomplete": '
        success, result = try_parse_json(original)

        assert success is False
        assert result is original

    def test_strips_whitespace_before_parsing(self):
        """Shell commands often output JSON with trailing newlines."""
        # This is the exact format shell commands produce
        shell_output = '{"status": "ok", "count": 42}\n'
        success, result = try_parse_json(shell_output)

        assert success is True
        assert result == {"status": "ok", "count": 42}

    def test_handles_multiline_json_with_whitespace(self):
        """JSON with leading/trailing whitespace and internal newlines."""
        json_with_whitespace = """
        {
            "items": [1, 2, 3],
            "nested": {"key": "value"}
        }
        """
        success, result = try_parse_json(json_with_whitespace)

        assert success is True
        assert result == {"items": [1, 2, 3], "nested": {"key": "value"}}

    def test_size_limit_prevents_large_json_parsing(self):
        """Security: don't parse strings exceeding size limit."""
        # Create string larger than limit
        large_json = '{"data": "' + "x" * 100 + '"}'
        small_limit = 50

        success, result = try_parse_json(large_json, max_size=small_limit)

        assert success is False
        assert result is large_json  # Original returned unchanged

    def test_distinguishes_parsed_none_from_parse_failure(self):
        """The tuple return lets callers distinguish null vs invalid."""
        # Valid JSON null
        success_null, result_null = try_parse_json("null")
        assert success_null is True
        assert result_null is None

        # Invalid JSON
        success_invalid, result_invalid = try_parse_json("not valid")
        assert success_invalid is False
        assert result_invalid == "not valid"

        # This distinction matters for template resolution:
        # - null means "value exists but is None"
        # - failure means "couldn't parse, try something else"

    def test_empty_string_returns_original(self):
        """Empty string is not valid JSON."""
        success, result = try_parse_json("")
        assert success is False
        assert result == ""

        success, result = try_parse_json("   ")  # Whitespace only
        assert success is False
        assert result == "   "


class TestRealWorldScenarios:
    """Integration-style tests with realistic data."""

    def test_curl_api_response(self):
        """Typical curl command output."""
        # curl -s https://api.example.com/user/123
        api_response = '{"id": 123, "name": "Alice", "active": true}\n'

        success, result = try_parse_json(api_response)

        assert success is True
        assert result["id"] == 123
        assert result["name"] == "Alice"
        assert result["active"] is True

    def test_jq_formatted_output(self):
        """Output from jq with formatting."""
        jq_output = """{
  "date": "2026-01-01",
  "items": [
    {"id": 1, "name": "first"},
    {"id": 2, "name": "second"}
  ]
}
"""
        success, result = try_parse_json(jq_output)

        assert success is True
        assert result["date"] == "2026-01-01"
        assert len(result["items"]) == 2
        assert result["items"][0]["name"] == "first"

    def test_nested_json_string_parses_outer_only(self):
        """JSON containing a JSON string field - only outer is parsed."""
        # This is the recursive case: stdout contains JSON with an inner JSON string
        outer_json = '{"data": "{\\"inner\\": 1}", "status": "ok"}'

        success, result = try_parse_json(outer_json)

        assert success is True
        assert result["status"] == "ok"
        # Inner JSON is still a string - caller must parse again if needed
        assert result["data"] == '{"inner": 1}'
        assert isinstance(result["data"], str)
