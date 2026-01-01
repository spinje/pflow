"""Tests for JSON auto-parsing during template path traversal.

Focus on high-value tests that verify real behavior:
1. Basic nested access on JSON strings (the main use case)
2. Array access on JSON strings
3. Invalid JSON graceful fallback
4. Validation consistency (variable_exists agrees with resolve_value)
5. Recursive JSON parsing (JSON-in-JSON)
"""

from pflow.runtime.template_resolver import TemplateResolver


class TestJsonNestedAccess:
    """Tests for accessing nested properties on JSON strings."""

    def test_basic_nested_access_on_json_string(self):
        """Main use case: ${node.stdout.field} when stdout is JSON."""
        context = {"node": {"stdout": '{"status": "success", "count": 42}'}}

        result = TemplateResolver.resolve_value("node.stdout.status", context)
        assert result == "success"

        result = TemplateResolver.resolve_value("node.stdout.count", context)
        assert result == 42  # Type preserved

    def test_json_primitives_null_and_bool(self):
        """JSON null, true, false are correctly parsed and typed."""
        context = {"api": {"stdout": '{"field": null, "active": true, "disabled": false}'}}

        # null → Python None
        result = TemplateResolver.resolve_value("api.stdout.field", context)
        assert result is None

        # true → Python True (not string "true")
        result = TemplateResolver.resolve_value("api.stdout.active", context)
        assert result is True
        assert isinstance(result, bool)

        # false → Python False
        result = TemplateResolver.resolve_value("api.stdout.disabled", context)
        assert result is False
        assert isinstance(result, bool)

    def test_deep_nested_access(self):
        """Deep nesting: ${node.stdout.a.b.c}."""
        context = {"node": {"stdout": '{"a": {"b": {"c": "deep value"}}}'}}

        result = TemplateResolver.resolve_value("node.stdout.a.b.c", context)
        assert result == "deep value"

    def test_shell_output_with_trailing_newline(self):
        """Shell commands produce JSON with trailing newlines."""
        context = {
            "shell": {
                "stdout": '{"result": "ok"}\n'  # Common shell output format
            }
        }

        result = TemplateResolver.resolve_value("shell.stdout.result", context)
        assert result == "ok"

    def test_terminal_access_returns_raw_string(self):
        """${node.stdout} without further path returns raw string, not parsed."""
        context = {"node": {"stdout": '{"field": "value"}'}}

        result = TemplateResolver.resolve_value("node.stdout", context)
        # Should return the raw string, NOT the parsed object
        assert result == '{"field": "value"}'
        assert isinstance(result, str)


class TestJsonArrayAccess:
    """Tests for array access on JSON strings."""

    def test_array_access_on_json_array_string(self):
        """${node.stdout[0]} when stdout is JSON array."""
        context = {"node": {"stdout": "[1, 2, 3]"}}

        result = TemplateResolver.resolve_value("node.stdout[0]", context)
        assert result == 1

        result = TemplateResolver.resolve_value("node.stdout[2]", context)
        assert result == 3

    def test_array_with_objects(self):
        """${node.stdout[0].id} when stdout is JSON array of objects."""
        context = {"node": {"stdout": '[{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]'}}

        result = TemplateResolver.resolve_value("node.stdout[0].id", context)
        assert result == 1

        result = TemplateResolver.resolve_value("node.stdout[1].name", context)
        assert result == "second"

    def test_mixed_object_and_array_access(self):
        """Complex path: ${node.result.items[0].name}."""
        context = {"node": {"result": '{"items": [{"name": "Alice"}, {"name": "Bob"}], "count": 2}'}}

        result = TemplateResolver.resolve_value("node.result.items[0].name", context)
        assert result == "Alice"

        result = TemplateResolver.resolve_value("node.result.count", context)
        assert result == 2


class TestInvalidJsonFallback:
    """Tests for graceful handling of invalid JSON."""

    def test_invalid_json_returns_none(self):
        """${node.stdout.field} when stdout is not valid JSON."""
        context = {"node": {"stdout": "this is not json"}}

        result = TemplateResolver.resolve_value("node.stdout.field", context)
        assert result is None  # Cannot resolve

    def test_partial_json_returns_none(self):
        """Malformed JSON fails gracefully."""
        context = {"node": {"stdout": '{"incomplete": '}}

        result = TemplateResolver.resolve_value("node.stdout.incomplete", context)
        assert result is None

    def test_json_without_requested_field_returns_none(self):
        """Valid JSON but field doesn't exist."""
        context = {"node": {"stdout": '{"status": "ok"}'}}

        result = TemplateResolver.resolve_value("node.stdout.nonexistent", context)
        assert result is None


class TestValidationConsistency:
    """Tests that variable_exists agrees with resolve_value."""

    def test_exists_agrees_with_resolve_for_valid_json(self):
        """variable_exists and resolve_value should agree."""
        context = {"node": {"stdout": '{"field": "value"}'}}

        # Both should agree that node.stdout.field exists
        exists = TemplateResolver.variable_exists("node.stdout.field", context)
        resolved = TemplateResolver.resolve_value("node.stdout.field", context)

        assert exists is True
        assert resolved == "value"

    def test_exists_agrees_with_resolve_for_invalid_json(self):
        """Both should agree when JSON is invalid."""
        context = {"node": {"stdout": "not json"}}

        exists = TemplateResolver.variable_exists("node.stdout.field", context)
        resolved = TemplateResolver.resolve_value("node.stdout.field", context)

        assert exists is False
        assert resolved is None

    def test_exists_agrees_for_array_access(self):
        """Both should agree for array access on JSON strings."""
        context = {"node": {"stdout": '[{"id": 1}]'}}

        exists = TemplateResolver.variable_exists("node.stdout[0].id", context)
        resolved = TemplateResolver.resolve_value("node.stdout[0].id", context)

        assert exists is True
        assert resolved == 1


class TestRecursiveJsonParsing:
    """Tests for JSON-in-JSON (recursive parsing)."""

    def test_nested_json_string_is_parsed_at_each_level(self):
        """${node.stdout.data.inner} when data is also a JSON string."""
        context = {"node": {"stdout": '{"data": "{\\"inner\\": \\"deep value\\"}"}'}}

        # First level: stdout is parsed to {"data": "{\"inner\": \"deep value\"}"}
        # Second level: data is parsed to {"inner": "deep value"}
        # Third level: access inner
        result = TemplateResolver.resolve_value("node.stdout.data.inner", context)
        assert result == "deep value"


class TestTemplateResolution:
    """Tests for full template resolution with JSON parsing."""

    def test_simple_template_resolves_with_json_parsing(self):
        """${node.stdout.field} in template resolution."""
        context = {"node": {"stdout": '{"field": "value"}'}}

        result = TemplateResolver.resolve_template("${node.stdout.field}", context)
        assert result == "value"

    def test_complex_template_interpolates_json_value(self):
        """ "Status: ${node.stdout.status}" works with JSON."""
        context = {"node": {"stdout": '{"status": "success"}'}}

        result = TemplateResolver.resolve_template("Status: ${node.stdout.status}", context)
        assert result == "Status: success"

    def test_unresolved_json_path_stays_as_template(self):
        """Invalid path leaves template unchanged for debugging."""
        context = {"node": {"stdout": '{"status": "ok"}'}}

        result = TemplateResolver.resolve_template("${node.stdout.nonexistent}", context)
        # Unresolved templates stay unchanged
        assert result == "${node.stdout.nonexistent}"


class TestRealWorldScenarios:
    """Integration-style tests with realistic data."""

    def test_curl_api_response(self):
        """Typical curl command output pattern."""
        context = {"api-call": {"stdout": '{"data": {"user": {"id": 123, "name": "Alice"}}, "status": "ok"}\n'}}

        assert TemplateResolver.resolve_value("api-call.stdout.status", context) == "ok"
        assert TemplateResolver.resolve_value("api-call.stdout.data.user.name", context) == "Alice"
        assert TemplateResolver.resolve_value("api-call.stdout.data.user.id", context) == 123

    def test_jq_formatted_output(self):
        """Output from jq command."""
        context = {"jq-node": {"stdout": '{\n  "items": [\n    {"id": 1},\n    {"id": 2}\n  ]\n}\n'}}

        assert TemplateResolver.resolve_value("jq-node.stdout.items[0].id", context) == 1
        assert TemplateResolver.resolve_value("jq-node.stdout.items[1].id", context) == 2

    def test_github_cli_output(self):
        """GitHub CLI JSON output pattern."""
        context = {"gh-issue": {"stdout": '{"number": 42, "title": "Fix bug", "labels": [{"name": "bug"}]}\n'}}

        assert TemplateResolver.resolve_value("gh-issue.stdout.number", context) == 42
        assert TemplateResolver.resolve_value("gh-issue.stdout.labels[0].name", context) == "bug"
