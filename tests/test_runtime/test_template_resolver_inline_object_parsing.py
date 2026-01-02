"""Tests for JSON auto-parsing in inline objects.

When a simple template resolves to a JSON string inside an inline object,
it should be automatically parsed to enable structured data access.

Escape hatch: Use complex templates ("prefix ${var}") to keep raw strings.
"""

from pflow.runtime.template_resolver import TemplateResolver


class TestInlineObjectJsonParsing:
    """Core behavior tests for auto-parsing JSON strings in inline objects."""

    def test_parses_json_object(self):
        """Main use case: JSON object string is parsed to dict."""
        context = {"source": {"stdout": '{"items": [1, 2, 3]}'}}
        result = TemplateResolver.resolve_nested({"data": "${source.stdout}"}, context)
        assert result["data"] == {"items": [1, 2, 3]}

    def test_parses_json_array(self):
        """JSON array string is parsed to list."""
        context = {"source": {"stdout": '[1, 2, {"id": 3}]'}}
        result = TemplateResolver.resolve_nested({"items": "${source.stdout}"}, context)
        assert result["items"] == [1, 2, {"id": 3}]

    def test_parses_json_primitives(self):
        """JSON primitives (number, boolean, null, string) are all parsed."""
        context = {
            "num": {"stdout": "42"},
            "bool": {"stdout": "true"},
            "null": {"stdout": "null"},
            "str": {"stdout": '"hello"'},
        }
        result = TemplateResolver.resolve_nested(
            {
                "num": "${num.stdout}",
                "bool": "${bool.stdout}",
                "null": "${null.stdout}",
                "str": "${str.stdout}",
            },
            context,
        )
        assert result["num"] == 42
        assert result["bool"] is True
        assert result["null"] is None
        assert result["str"] == "hello"

    def test_strips_whitespace_before_parsing(self):
        """Shell output with trailing newlines still parses (real shell behavior)."""
        context = {"source": {"stdout": '{"status": "ok"}\n'}}
        result = TemplateResolver.resolve_nested({"data": "${source.stdout}"}, context)
        assert result["data"] == {"status": "ok"}

    def test_invalid_json_stays_as_string(self):
        """Invalid JSON gracefully stays as string."""
        context = {"source": {"stdout": "not valid json"}}
        result = TemplateResolver.resolve_nested({"data": "${source.stdout}"}, context)
        assert result["data"] == "not valid json"

    def test_already_parsed_value_unchanged(self):
        """Values that are already dicts/lists stay unchanged (no double-parse)."""
        context = {"source": {"data": {"already": "parsed"}}}
        result = TemplateResolver.resolve_nested({"info": "${source.data}"}, context)
        assert result["info"] == {"already": "parsed"}


class TestEscapeHatch:
    """Complex templates (prefix/suffix) bypass JSON parsing."""

    def test_trailing_space_prevents_parsing(self):
        """Trailing space makes template complex → stays string."""
        context = {"source": {"stdout": '{"items": [1, 2, 3]}'}}
        result = TemplateResolver.resolve_nested({"data": "${source.stdout} "}, context)
        assert isinstance(result["data"], str)
        assert result["data"] == '{"items": [1, 2, 3]} '

    def test_prefix_prevents_parsing(self):
        """Prefix makes template complex → stays string."""
        context = {"source": {"stdout": '{"a": 1}'}}
        result = TemplateResolver.resolve_nested({"data": "json: ${source.stdout}"}, context)
        assert result["data"] == 'json: {"a": 1}'


class TestStructure:
    """Tests for nested structures and multiple templates."""

    def test_top_level_template_also_parses(self):
        """Top-level template (not in object) also parses JSON.

        Important: shows parsing works at any level of resolve_nested(),
        not just for values inside inline objects.
        """
        context = {"source": {"stdout": '{"key": "value"}'}}
        result = TemplateResolver.resolve_nested("${source.stdout}", context)
        assert result == {"key": "value"}

    def test_mixed_valid_and_invalid_json(self):
        """Valid JSON parses while invalid JSON stays as string in same object."""
        context = {
            "valid": {"stdout": '{"parsed": true}'},
            "invalid": {"stdout": "not json"},
        }
        result = TemplateResolver.resolve_nested({"good": "${valid.stdout}", "bad": "${invalid.stdout}"}, context)
        assert result["good"] == {"parsed": True}  # Parsed
        assert result["bad"] == "not json"  # Stays string

    def test_deeply_nested_inline_objects(self):
        """Parsing works at all nesting levels."""
        context = {"source": {"stdout": '{"inner": "value"}'}}
        result = TemplateResolver.resolve_nested({"level1": {"level2": {"level3": "${source.stdout}"}}}, context)
        assert result["level1"]["level2"]["level3"] == {"inner": "value"}

    def test_multiple_templates_in_same_object(self):
        """Multiple templates in same inline object all parse."""
        context = {
            "source1": {"stdout": '{"a": 1}'},
            "source2": {"stdout": '{"b": 2}'},
        }
        result = TemplateResolver.resolve_nested({"first": "${source1.stdout}", "second": "${source2.stdout}"}, context)
        assert result["first"] == {"a": 1}
        assert result["second"] == {"b": 2}

    def test_templates_in_array_parse(self):
        """Templates as array elements also parse (tests list recursion path).

        Important: resolve_nested has separate code paths for dict and list.
        This ensures the list path also triggers JSON parsing.
        """
        context = {
            "a": {"stdout": '{"id": 1}'},
            "b": {"stdout": '{"id": 2}'},
        }
        result = TemplateResolver.resolve_nested(["${a.stdout}", "${b.stdout}"], context)
        assert result == [{"id": 1}, {"id": 2}]

    def test_unresolved_template_stays_as_template(self):
        """Templates that can't be resolved stay as template strings."""
        context = {}
        result = TemplateResolver.resolve_nested({"data": "${nonexistent.var}"}, context)
        assert result["data"] == "${nonexistent.var}"


class TestNoDoubleParsing:
    """Parsed results don't get double-parsed."""

    def test_inner_json_strings_not_recursively_parsed(self):
        """Parsed results with JSON string values don't get double-parsed."""
        context = {"source": {"stdout": '{"outer": "{\\"inner\\": 1}"}'}}
        result = TemplateResolver.resolve_nested({"data": "${source.stdout}"}, context)

        # Outer is parsed, but inner stays as string
        assert result["data"]["outer"] == '{"inner": 1}'
        assert isinstance(result["data"]["outer"], str)


class TestRealWorldScenarios:
    """Integration-style tests with realistic shell → jq patterns."""

    def test_curl_response_in_stdin(self):
        """Typical pattern: curl output → process with jq."""
        context = {"api-call": {"stdout": '{"status": "ok", "data": {"users": [{"id": 1}, {"id": 2}]}}\n'}}
        result = TemplateResolver.resolve_nested({"stdin": {"response": "${api-call.stdout}"}}, context)
        assert result["stdin"]["response"]["status"] == "ok"
        assert result["stdin"]["response"]["data"]["users"][0]["id"] == 1

    def test_multiple_shell_outputs_combined(self):
        """Combine multiple JSON outputs into one object."""
        context = {
            "users": {"stdout": '[{"name": "Alice"}, {"name": "Bob"}]'},
            "config": {"stdout": '{"debug": true, "limit": 100}'},
        }
        result = TemplateResolver.resolve_nested(
            {"stdin": {"users": "${users.stdout}", "settings": "${config.stdout}"}},
            context,
        )
        assert result["stdin"]["users"] == [{"name": "Alice"}, {"name": "Bob"}]
        assert result["stdin"]["settings"]["debug"] is True

    def test_github_cli_json_output(self):
        """GitHub CLI outputs JSON that needs to be combined."""
        context = {
            "issues": {"stdout": '[{"number": 1, "title": "Bug"}]\n'},
            "prs": {"stdout": '[{"number": 10, "title": "Fix"}]\n'},
        }
        result = TemplateResolver.resolve_nested(
            {"data": {"issues": "${issues.stdout}", "prs": "${prs.stdout}"}},
            context,
        )
        assert result["data"]["issues"][0]["number"] == 1
        assert result["data"]["prs"][0]["number"] == 10


class TestNestedAndRootAccessComposition:
    """Test that nested path access and root-level access both work in inline objects."""

    def test_nested_path_extracts_value_into_inline_object(self):
        """Nested path access extracts parsed value into inline object."""
        context = {"api": {"stdout": '{"data": {"users": [{"name": "Alice"}, {"name": "Bob"}]}}'}}

        result = TemplateResolver.resolve_nested({"users": "${api.stdout.data.users}"}, context)

        assert result["users"] == [{"name": "Alice"}, {"name": "Bob"}]
        assert isinstance(result["users"], list)

    def test_nested_path_and_root_access_in_same_object(self):
        """Both nested path and root access work together in same inline object."""
        context = {
            "shell1": {"stdout": '{"items": [1, 2, 3], "meta": {"count": 3}}'},
            "shell2": {"stdout": '{"status": "ok"}'},
        }

        result = TemplateResolver.resolve_nested(
            {
                "count": "${shell1.stdout.meta.count}",  # nested path
                "status_obj": "${shell2.stdout}",  # root access
            },
            context,
        )

        assert result["count"] == 3
        assert result["status_obj"] == {"status": "ok"}
