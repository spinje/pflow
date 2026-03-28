"""Tests for template feature combinations with ZERO prior coverage.

Each test verifies the interaction between two or more template features
(coalesce, JSON auto-parse, nested index, type preservation, inline objects).
Single-feature behavior is already tested in:
- test_template_coalesce.py
- test_template_resolver_json_parsing.py
- test_nested_templates.py

These combination tests catch integration bugs where individual features
work in isolation but fail when composed — a common real-world pattern
in branch-convergence workflows with JSON shell output.
"""

from pflow.runtime.template_resolver import TemplateResolver


class TestCoalesceWithJsonAutoparse:
    """Coalesce (${a ?? b}) + JSON auto-parse during path traversal.

    Real workflow pattern: conditional branches where one branch runs a
    shell command producing JSON stdout, and a downstream node accesses
    a field from whichever branch executed.
    """

    def test_coalesce_fallback_resolves_json_string_via_resolve_template(self):
        """When coalesce falls back and the resolved value is a JSON string,
        resolve_template returns the raw string (auto-parse only happens
        in resolve_nested or during path traversal).

        Pattern: ${a.stdout ?? b.stdout} where b.stdout is '{"name": "test"}'
        """
        shared = {
            "b": {"stdout": '{"name": "test"}'},
        }
        result = TemplateResolver.resolve_template("${a.stdout ?? b.stdout}", shared)
        # resolve_template preserves raw type — JSON string stays as string
        assert result == '{"name": "test"}'
        assert isinstance(result, str)

    def test_coalesce_first_operand_resolves_json_string(self):
        """When the first coalesce operand resolves to a JSON string,
        resolve_template returns the raw string (same as fallback case).
        """
        shared = {
            "a": {"stdout": '{"status": "ok", "count": 42}'},
            "b": {"stdout": '{"status": "fallback"}'},
        }
        result = TemplateResolver.resolve_template("${a.stdout ?? b.stdout}", shared)
        assert result == '{"status": "ok", "count": 42}'
        assert isinstance(result, str)

    def test_coalesce_with_path_traversal_into_json_picks_first_available(self):
        """Coalesce with path traversal into JSON: ${a.stdout.name ?? b.stdout.name}.

        The resolver auto-parses the JSON string during path traversal
        (via _try_parse_json_for_traversal) before accessing the nested field.
        This is the primary workflow pattern for branch convergence with
        JSON-producing shell commands.
        """
        shared = {
            "b": {"stdout": '{"name": "from-fallback", "version": 2}'},
        }
        result = TemplateResolver.resolve_template("${a.stdout.name ?? b.stdout.name}", shared)
        assert result == "from-fallback"

    def test_coalesce_with_path_traversal_into_json_first_wins(self):
        """When both branches exist, first operand's JSON path wins."""
        shared = {
            "a": {"stdout": '{"name": "first-branch", "version": 1}'},
            "b": {"stdout": '{"name": "second-branch", "version": 2}'},
        }
        result = TemplateResolver.resolve_template("${a.stdout.name ?? b.stdout.name}", shared)
        assert result == "first-branch"

    def test_coalesce_with_deep_json_path_traversal(self):
        """Coalesce with multi-level JSON path: ${a.stdout.data.user.id ?? b.stdout.data.user.id}.

        Tests that JSON auto-parse composes with deep path traversal
        after coalesce selects the operand.
        """
        shared = {
            "b": {"stdout": '{"data": {"user": {"id": 42, "name": "Alice"}}}'},
        }
        result = TemplateResolver.resolve_template("${a.stdout.data.user.id ?? b.stdout.data.user.id}", shared)
        assert result == 42
        assert isinstance(result, int)

    def test_coalesce_json_path_preserves_integer_type(self):
        """Coalesce + JSON path resolving to an integer preserves type."""
        shared = {
            "api": {"stdout": '{"count": 99}\n'},  # trailing newline from shell
        }
        result = TemplateResolver.resolve_template("${missing.stdout.count ?? api.stdout.count}", shared)
        assert result == 99
        assert isinstance(result, int)


class TestCoalesceJsonAutoparseInlineObjects:
    """Triple combination: coalesce + JSON auto-parse + inline objects (resolve_nested).

    Real workflow pattern: a downstream node receives structured params
    like {"config": "${branch-a.output ?? branch-b.output}"} where the
    resolved value is a JSON string from shell output. resolve_nested
    should auto-parse the JSON into a dict/list.
    """

    def test_resolve_nested_autoparses_json_from_coalesce_fallback(self):
        """resolve_nested auto-parses JSON string resolved via coalesce fallback.

        Pattern: {"config": "${a.stdout ?? b.stdout}"} where b.stdout is JSON.
        The coalesce picks b.stdout (a is absent), then resolve_nested
        auto-parses the JSON string into a dict.
        """
        shared = {
            "b": {"stdout": '{"host": "localhost", "port": 8080}'},
        }
        template = {"config": "${a.stdout ?? b.stdout}"}
        result = TemplateResolver.resolve_nested(template, shared)

        assert isinstance(result["config"], dict)
        assert result["config"] == {"host": "localhost", "port": 8080}
        assert result["config"]["port"] == 8080

    def test_resolve_nested_autoparses_json_array_from_coalesce(self):
        """resolve_nested auto-parses a JSON array string resolved via coalesce."""
        shared = {
            "b": {"stdout": '["alpha", "beta", "gamma"]'},
        }
        template = {"items": "${a.stdout ?? b.stdout}"}
        result = TemplateResolver.resolve_nested(template, shared)

        assert isinstance(result["items"], list)
        assert result["items"] == ["alpha", "beta", "gamma"]

    def test_multi_field_inline_object_with_coalesce_and_json(self):
        """Multiple fields in an inline object, each using coalesce with JSON values.

        Pattern: a downstream node needs both config and name from whichever
        branch executed — both produce JSON output.
        """
        shared = {
            "b": {
                "output": '{"host": "db.example.com", "port": 5432}',
                "name": "production",
            },
        }
        template = {
            "config": "${a.output ?? b.output}",
            "name": "${a.name ?? b.name}",
        }
        result = TemplateResolver.resolve_nested(template, shared)

        # config should be auto-parsed from JSON string to dict
        assert isinstance(result["config"], dict)
        assert result["config"]["host"] == "db.example.com"
        assert result["config"]["port"] == 5432

        # name is a plain string, not JSON — stays as string
        assert result["name"] == "production"
        assert isinstance(result["name"], str)

    def test_resolve_nested_coalesce_first_operand_with_json(self):
        """When first coalesce operand resolves and its value is JSON,
        resolve_nested auto-parses it. Both branches present, first wins.
        """
        shared = {
            "a": {"stdout": '{"priority": "high"}'},
            "b": {"stdout": '{"priority": "low"}'},
        }
        template = {"result": "${a.stdout ?? b.stdout}"}
        result = TemplateResolver.resolve_nested(template, shared)

        assert isinstance(result["result"], dict)
        assert result["result"]["priority"] == "high"


class TestCoalesceWithNestedIndex:
    """Coalesce (${a ?? b}) + nested index (${results[${idx}]}).

    Real workflow pattern: batch processing with conditional fallback —
    access an element by dynamic index, with a fallback if the primary
    source didn't produce results.
    """

    def test_nested_index_resolves_then_coalesce_picks_first(self):
        """${results[${idx}] ?? fallback.value} — index resolves to valid position,
        coalesce picks first operand (results[N] exists).

        The nested index template [${idx}] is resolved first (pre-processing),
        then coalesce evaluates the static-index operand.
        """
        shared = {
            "idx": 1,
            "results": ["zero", "one", "two"],
            "fallback": {"value": "default"},
        }
        result = TemplateResolver.resolve_template("${results[${idx}] ?? fallback.value}", shared)
        assert result == "one"

    def test_nested_index_coalesce_falls_back_when_source_absent(self):
        """${primary[${idx}] ?? backup.value} — primary is absent,
        coalesce falls back to backup.value.
        """
        shared = {
            "idx": 0,
            "backup": {"value": "fallback-used"},
        }
        result = TemplateResolver.resolve_template("${primary[${idx}] ?? backup.value}", shared)
        assert result == "fallback-used"

    def test_nested_index_with_coalesce_index_zero(self):
        """Edge case: index 0 should not be treated as falsy.

        ${items[${idx}] ?? other} with idx=0 — must resolve items[0],
        not fall through to coalesce.
        """
        shared = {
            "idx": 0,
            "items": ["first-item", "second-item"],
            "other": "should-not-use",
        }
        result = TemplateResolver.resolve_template("${items[${idx}] ?? other}", shared)
        assert result == "first-item"


class TestNestedIndexWithJsonAutoparse:
    """Nested index (${node.stdout[${idx}]}) + JSON auto-parse.

    Real workflow pattern: a shell command outputs a JSON array, and
    batch processing needs to access elements by dynamic index.
    """

    def test_json_array_string_with_dynamic_index(self):
        """${node.stdout[${idx}]} where stdout is a JSON array string.

        The resolver should auto-parse the JSON array, then use the
        dynamic index to access an element.
        """
        shared = {
            "idx": 1,
            "node": {"stdout": '["alpha", "beta", "gamma"]'},
        }
        result = TemplateResolver.resolve_template("${node.stdout[${idx}]}", shared)
        assert result == "beta"

    def test_json_array_string_with_dynamic_index_zero(self):
        """Index 0 into a JSON array string resolves correctly."""
        shared = {
            "idx": 0,
            "node": {"stdout": '["first", "second", "third"]'},
        }
        result = TemplateResolver.resolve_template("${node.stdout[${idx}]}", shared)
        assert result == "first"

    def test_json_array_of_objects_with_dynamic_index_and_path(self):
        """${node.stdout[${idx}].name} where stdout is a JSON array of objects.

        Combines: nested index resolution → JSON auto-parse → array access → property access.
        """
        shared = {
            "idx": 1,
            "node": {"stdout": '[{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]'},
        }
        result = TemplateResolver.resolve_template("${node.stdout[${idx}].name}", shared)
        assert result == "Bob"

    def test_json_object_with_array_field_and_dynamic_index(self):
        """${node.stdout.items[${idx}]} where stdout is a JSON object containing an array.

        Tests JSON auto-parse at object level, then array access with dynamic index.
        """
        shared = {
            "idx": 2,
            "node": {"stdout": '{"items": ["x", "y", "z"], "count": 3}'},
        }
        result = TemplateResolver.resolve_template("${node.stdout.items[${idx}]}", shared)
        assert result == "z"


class TestNestedIndexWithTypePreservation:
    """Nested index (${results[${idx}]}) + type preservation.

    When an array element is a non-string type (dict, list, int, bool),
    the resolved value should preserve its original type, not stringify it.
    """

    def test_dict_element_preserves_type(self):
        """${results[${idx}]} where the element is a dict — type preserved."""
        shared = {
            "idx": 0,
            "results": [
                {"key": "value", "nested": [1, 2, 3]},
                {"key": "other"},
            ],
        }
        result = TemplateResolver.resolve_template("${results[${idx}]}", shared)
        assert isinstance(result, dict)
        assert result == {"key": "value", "nested": [1, 2, 3]}

    def test_list_element_preserves_type(self):
        """${results[${idx}]} where the element is a list — type preserved."""
        shared = {
            "idx": 1,
            "results": ["plain-string", [10, 20, 30], "another"],
        }
        result = TemplateResolver.resolve_template("${results[${idx}]}", shared)
        assert isinstance(result, list)
        assert result == [10, 20, 30]

    def test_integer_element_preserves_type(self):
        """${results[${idx}]} where the element is an integer — type preserved."""
        shared = {
            "idx": 2,
            "results": ["a", "b", 42],
        }
        result = TemplateResolver.resolve_template("${results[${idx}]}", shared)
        assert isinstance(result, int)
        assert result == 42

    def test_boolean_element_preserves_type(self):
        """${results[${idx}]} where the element is a boolean — type preserved."""
        shared = {
            "idx": 0,
            "results": [False, True, "text"],
        }
        result = TemplateResolver.resolve_template("${results[${idx}]}", shared)
        assert result is False
        assert isinstance(result, bool)


class TestCoalesceArrayAccessJsonAutoparse:
    """Coalesce + array access + JSON auto-parse.

    Real workflow pattern: a shell node outputs a JSON array, and a
    downstream node accesses the first element with a fallback if
    the primary branch didn't run.
    """

    def test_coalesce_with_static_array_index_on_json_array(self):
        """${a.data[0] ?? b.data[0]} where data is a JSON array string.

        Each coalesce operand includes a static array index. The resolver
        should auto-parse the JSON array string, then access element [0].
        """
        shared = {
            "b": {"data": '["fallback-first", "fallback-second"]'},
        }
        result = TemplateResolver.resolve_template("${a.data[0] ?? b.data[0]}", shared)
        assert result == "fallback-first"

    def test_coalesce_array_index_first_operand_wins(self):
        """When both branches have JSON arrays, first operand's element wins."""
        shared = {
            "a": {"data": '["alpha", "beta"]'},
            "b": {"data": '["gamma", "delta"]'},
        }
        result = TemplateResolver.resolve_template("${a.data[0] ?? b.data[0]}", shared)
        assert result == "alpha"

    def test_coalesce_array_index_on_json_object_array_field(self):
        """${a.stdout.items[0] ?? b.stdout.items[0]} — JSON object with array field.

        Combines: coalesce branch selection → JSON auto-parse → object field access
        → array index access. A realistic API response pattern.
        """
        shared = {
            "b": {"stdout": '{"items": [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]}'},
        }
        result = TemplateResolver.resolve_template("${a.stdout.items[0].name ?? b.stdout.items[0].name}", shared)
        assert result == "first"
