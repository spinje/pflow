"""Tests for template variable resolution with path support."""

from pflow.runtime.template_resolver import TemplateResolver


class TestTemplateDetection:
    """Test template detection in various value types."""

    def test_detects_templates_in_strings(self):
        """Test that templates are detected in string values."""
        assert TemplateResolver.has_templates("Hello ${name}")
        assert TemplateResolver.has_templates("${url}")
        assert TemplateResolver.has_templates("Path: ${data.field}")

    def test_ignores_non_string_values(self):
        """Test that non-string/collection values are ignored, but collections are checked recursively."""
        # Non-collection types should return False
        assert not TemplateResolver.has_templates(42)
        assert not TemplateResolver.has_templates(True)
        assert not TemplateResolver.has_templates(None)

        # Collections with templates should now return True (new behavior)
        assert TemplateResolver.has_templates(["${item}"])  # Now detects templates in lists
        assert TemplateResolver.has_templates({"key": "${value}"})  # Now detects templates in dicts

        # Collections without templates should return False
        assert not TemplateResolver.has_templates(["item"])
        assert not TemplateResolver.has_templates({"key": "value"})

    def test_detects_absence_of_templates(self):
        """Test that strings without templates are not flagged."""
        assert not TemplateResolver.has_templates("Hello world")
        assert not TemplateResolver.has_templates("")
        assert not TemplateResolver.has_templates("price: 100")
        assert not TemplateResolver.has_templates("$oldstyle")  # Old $var syntax not detected
        assert not TemplateResolver.has_templates("$${escaped}")  # Escaped templates are not templates
        assert not TemplateResolver.has_templates("prefix $${var} suffix")


class TestVariableExtraction:
    """Test extraction of template variable names."""

    def test_extracts_simple_variables(self):
        """Test extraction of simple variable names."""
        assert TemplateResolver.extract_variables("${url}") == {"url"}
        assert TemplateResolver.extract_variables("Hello ${name}") == {"name"}
        assert TemplateResolver.extract_variables("${var1} and ${var2}") == {"var1", "var2"}

    def test_extracts_path_variables(self):
        """Test extraction of variables with paths."""
        assert TemplateResolver.extract_variables("${data.field}") == {"data.field"}
        assert TemplateResolver.extract_variables("${a.b.c.d}") == {"a.b.c.d"}
        assert TemplateResolver.extract_variables("${user.info.name}") == {"user.info.name"}

    def test_extracts_multiple_variables(self):
        """Test extraction of multiple variables from one string."""
        template = "User ${user.name} from ${user.company} at ${location}"
        expected = {"user.name", "user.company", "location"}
        assert TemplateResolver.extract_variables(template) == expected

    def test_extracts_coalesce_operands(self):
        """Coalesce expressions are split into individual variable names."""
        assert TemplateResolver.extract_variables("${a ?? b.field}") == {"a", "b.field"}
        assert TemplateResolver.extract_variables("${a ?? b ?? c}") == {"a", "b", "c"}

    def test_handles_malformed_templates(self):
        """Test that malformed templates are not extracted."""
        # Valid template should be extracted
        assert TemplateResolver.extract_variables("${var}") == {"var"}  # Valid new syntax
        # These malformed patterns should not match
        assert TemplateResolver.extract_variables("${var") == set()  # Unclosed
        assert TemplateResolver.extract_variables("$${var}") == set()  # Escaped
        assert TemplateResolver.extract_variables("${}") == set()  # Empty
        assert TemplateResolver.extract_variables("${123}") == set()  # Can't start with digit
        # Variables with hyphens are now valid
        assert TemplateResolver.extract_variables("${user-id}") == {"user-id"}


class TestValueResolution:
    """Test resolution of variable values from context."""

    def test_resolves_simple_variables(self):
        """Test resolution of simple variables."""
        context = {"url": "https://example.com", "name": "Alice"}
        assert TemplateResolver.resolve_value("url", context) == "https://example.com"
        assert TemplateResolver.resolve_value("name", context) == "Alice"
        assert TemplateResolver.resolve_value("missing", context) is None

    def test_resolves_nested_paths(self):
        """Test resolution of nested data paths."""
        context = {"user": {"name": "Bob", "info": {"age": 30, "city": "NYC"}}}
        assert TemplateResolver.resolve_value("user.name", context) == "Bob"
        assert TemplateResolver.resolve_value("user.info.age", context) == 30
        assert TemplateResolver.resolve_value("user.info.city", context) == "NYC"

    def test_handles_missing_paths(self):
        """Test handling of missing paths."""
        context = {"data": {"field": "value"}}
        assert TemplateResolver.resolve_value("data.missing", context) is None
        assert TemplateResolver.resolve_value("missing.field", context) is None
        assert TemplateResolver.resolve_value("data.field.sub", context) is None

    def test_handles_non_dict_traversal(self):
        """Test that traversal stops at non-dict values."""
        context = {"string": "hello", "number": 42, "list": [1, 2, 3]}
        assert TemplateResolver.resolve_value("string.field", context) is None
        assert TemplateResolver.resolve_value("number.field", context) is None
        assert TemplateResolver.resolve_value("list.0", context) is None  # No array indexing


class TestTypeConversion:
    """Test conversion of values to strings."""

    def test_none_conversion(self):
        """Test None converts to empty string."""
        assert TemplateResolver._convert_to_string(None) == ""

    def test_empty_string_conversion(self):
        """Test empty string stays empty."""
        assert TemplateResolver._convert_to_string("") == ""

    def test_zero_conversion(self):
        """Test zero converts to "0"."""
        assert TemplateResolver._convert_to_string(0) == "0"
        # 0.0 == 0 in Python, so _convert_to_string(0.0) returns "0"
        assert TemplateResolver._convert_to_string(0.0) == "0"

    def test_boolean_conversion(self):
        """Test boolean conversion."""
        assert TemplateResolver._convert_to_string(False) == "False"
        assert TemplateResolver._convert_to_string(True) == "True"

    def test_empty_collection_conversion(self):
        """Test empty collections convert to string representation."""
        assert TemplateResolver._convert_to_string([]) == "[]"
        assert TemplateResolver._convert_to_string({}) == "{}"

    def test_regular_value_conversion(self):
        """Test regular values use str() or JSON serialization."""
        assert TemplateResolver._convert_to_string("hello") == "hello"
        assert TemplateResolver._convert_to_string(42) == "42"
        # Lists and dicts should serialize as valid JSON (double quotes, not Python repr)
        assert TemplateResolver._convert_to_string([1, 2, 3]) == "[1, 2, 3]"
        assert TemplateResolver._convert_to_string({"a": 1}) == '{"a": 1}'


class TestTemplateResolution:
    """Test complete template resolution."""

    def test_resolves_single_template(self):
        """Test resolution of single template in string."""
        context = {"url": "https://example.com"}
        # Complex template (text around variable) - returns string
        assert TemplateResolver.resolve_template("Visit ${url}", context) == "Visit https://example.com"
        # Simple template - preserves type (string in this case)
        assert TemplateResolver.resolve_template("${url}", context) == "https://example.com"

    def test_resolves_multiple_templates(self):
        """Test resolution of multiple templates."""
        context = {"name": "Alice", "age": 30}
        template = "${name} is ${age} years old"
        assert TemplateResolver.resolve_template(template, context) == "Alice is 30 years old"

    def test_resolves_path_templates(self):
        """Test resolution of templates with paths."""
        context = {"user": {"name": "Bob", "email": "bob@example.com"}, "status": "active"}
        template = "User ${user.name} (${user.email}) - Status: ${status}"
        expected = "User Bob (bob@example.com) - Status: active"
        assert TemplateResolver.resolve_template(template, context) == expected

    def test_preserves_unresolved_templates(self):
        """Test that unresolved templates remain unchanged."""
        context = {"found": "yes"}
        template = "Found: ${found}, Missing: ${missing}"
        assert TemplateResolver.resolve_template(template, context) == "Found: yes, Missing: ${missing}"

    def test_handles_type_conversions_in_complex_templates(self):
        """Test type conversions when values are embedded in strings (complex templates)."""
        context = {"none_val": None, "zero": 0, "false": False, "empty_list": [], "data": {"count": 42}}
        # Complex templates always return strings - values get converted
        assert TemplateResolver.resolve_template("[${none_val}]", context) == "[]"
        assert TemplateResolver.resolve_template("Count: ${zero}", context) == "Count: 0"
        assert TemplateResolver.resolve_template("Flag: ${false}", context) == "Flag: False"
        assert TemplateResolver.resolve_template("Items: ${empty_list}", context) == "Items: []"
        assert TemplateResolver.resolve_template("Total: ${data.count}", context) == "Total: 42"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_malformed_template_syntax(self):
        """Test that malformed templates are left unchanged."""
        context = {"var": "value", "data": {"field": "test"}}

        # Valid template should work
        assert TemplateResolver.resolve_template("${var}", context) == "value"  # Valid new syntax

        # These malformed templates should remain as-is
        assert TemplateResolver.resolve_template("${var", context) == "${var"  # Unclosed
        assert TemplateResolver.resolve_template("$${var}", context) == "$${var}"  # Escaped
        assert TemplateResolver.resolve_template("${}", context) == "${}"  # Empty

        # Variables with hyphens now work
        context["user-id"] = "123"
        assert TemplateResolver.resolve_template("${user-id}", context) == "123"

    def test_path_traversal_with_null(self):
        """Test path traversal when encountering null/None."""
        context = {"parent": {"child": None}}
        # Should not be able to traverse through None
        assert TemplateResolver.resolve_template("${parent.child.field}", context) == "${parent.child.field}"

    def test_adjacent_templates(self):
        """Test templates with no spacing between them (complex template - returns string)."""
        context = {"a": "A", "b": "B", "c": "C"}
        # Multiple templates = complex template = string result
        assert TemplateResolver.resolve_template("${a}${b}${c}", context) == "ABC"
        assert TemplateResolver.resolve_template("${a}-${b}-${c}", context) == "A-B-C"

    def test_template_in_larger_text(self):
        """Test templates embedded in larger text blocks."""
        context = {"repo": "pflow", "issue": "123", "user": {"name": "Alice"}}
        template = """
        Working on repository ${repo}
        Fixing issue #${issue}
        Assigned to: ${user.name}
        Missing: ${undefined.field}
        """
        expected = """
        Working on repository pflow
        Fixing issue #123
        Assigned to: Alice
        Missing: ${undefined.field}
        """
        assert TemplateResolver.resolve_template(template, context) == expected


class TestRealWorldScenarios:
    """Test scenarios from actual pflow usage."""

    def test_planner_parameter_flow(self):
        """Test parameters extracted by planner from natural language."""
        # Simulating planner extraction from "fix github issue 1234"
        planner_params = {"issue_number": "1234", "repo": "pflow"}

        template = "Working on issue ${issue_number} in ${repo}"
        result = TemplateResolver.resolve_template(template, planner_params)
        assert result == "Working on issue 1234 in pflow"

    def test_shared_store_path_access(self):
        """Test accessing nested data in shared store."""
        # Nodes write directly to shared store keys
        context = {
            "transcript_data": {
                "video_id": "xyz",
                "title": "Learning Python",
                "metadata": {"author": "CodeTeacher", "duration": 3600},
            },
            "summary": "Python is a versatile language...",
        }

        template = "Video: ${transcript_data.title} by ${transcript_data.metadata.author}"
        result = TemplateResolver.resolve_template(template, context)
        assert result == "Video: Learning Python by CodeTeacher"

    def test_youtube_workflow_example(self):
        """Test template resolution from youtube summarization workflow."""
        context = {
            "url": "https://youtube.com/watch?v=xyz",
            "transcript_data": {
                "video_id": "xyz",
                "title": "How to Learn Programming",
                "text": "In this video, we'll explore...",
                "metadata": {"author": "TechChannel", "views": 50000},
            },
            "summary": "• Start with fundamentals\n• Practice daily\n• Build projects",
        }

        # Template from example workflow
        template = "Summary of '${transcript_data.title}' by ${transcript_data.metadata.author}"
        result = TemplateResolver.resolve_template(template, context)
        assert result == "Summary of 'How to Learn Programming' by TechChannel"


class TestExtractFirstFieldSegment:
    """Test TemplateResolver.extract_first_field_segment.

    Used by template error helpers to locate the first field segment of
    a path so peer-node lookup and typo correction can target it.
    """

    def test_simple_field(self):
        assert TemplateResolver.extract_first_field_segment("node.field") == "field"

    def test_nested_field_returns_first_segment(self):
        assert TemplateResolver.extract_first_field_segment("node.field.nested") == "field"

    def test_indexed_field_strips_bracket(self):
        assert TemplateResolver.extract_first_field_segment("node.field[0]") == "field"

    def test_indexed_nested_field_strips_bracket(self):
        assert TemplateResolver.extract_first_field_segment("node.field[0].nested") == "field"

    def test_bare_root_returns_none(self):
        assert TemplateResolver.extract_first_field_segment("node") is None

    def test_root_with_index_only_returns_none(self):
        assert TemplateResolver.extract_first_field_segment("data[0]") is None

    def test_indexed_root_with_field(self):
        # Root carries the `[0]` — `.split(".", 1)` gives `["node[0]", "field"]`
        # and we return the first segment after the dot.
        assert TemplateResolver.extract_first_field_segment("node[0].field") == "field"


class TestResolveTemplateThroughDictLikeProxy:
    """Regression tests for Bug #2 (Task 159 verification, 2026-04-30).

    ``LLMNode.prep`` receives ``shared`` as a ``NamespacedSharedStore`` (engine
    wraps in ``engine.py:471`` for the ``node._run`` call). Pre-fix,
    ``TemplateResolver._get_dict_value`` checked ``isinstance(value, dict)``
    which excluded the proxy — so ``${node.field}`` resolved against the proxy
    silently echoed the literal template, breaking the cache-rendering byte
    identity invariant (DD#19) for every dotted-path chunk.

    After fix: NamespacedSharedStore inherits ``MutableMapping`` and
    ``_get_dict_value`` checks ``isinstance(value, Mapping)``, so dotted-path
    resolution works through any dict-like proxy.
    """

    def test_simple_var_resolves_through_namespaced_proxy(self):
        from pflow.runtime.engine.namespaced_store import NamespacedSharedStore

        shared = {"topic": "hello", "node-x": {}}
        store = NamespacedSharedStore(shared, "node-x")
        assert TemplateResolver.resolve_template("${topic}", store) == "hello"

    def test_dotted_path_resolves_through_namespaced_proxy(self):
        from pflow.runtime.engine.namespaced_store import NamespacedSharedStore

        shared = {"upstream": {"stdout": "from upstream", "exit_code": 0}, "consumer": {}}
        store = NamespacedSharedStore(shared, "consumer")
        assert TemplateResolver.resolve_template("${upstream.stdout}", store) == "from upstream"

    def test_dotted_path_yields_identical_bytes_for_dict_and_proxy(self):
        """Hash side (raw dict) and prep side (NamespacedSharedStore) must
        produce byte-identical results for the same logical state. This is
        the load-bearing DD#19 invariant; any divergence is a silent stale-
        cache regression class."""
        from pflow.runtime.engine.namespaced_store import NamespacedSharedStore

        shared = {"upstream": {"stdout": "abc"}, "consumer": {}}
        store = NamespacedSharedStore(shared, "consumer")
        from_dict = TemplateResolver.resolve_template("${upstream.stdout}", shared)
        from_proxy = TemplateResolver.resolve_template("${upstream.stdout}", store)
        assert from_dict == from_proxy == "abc"

    def test_namespaced_store_is_a_mapping(self):
        """NamespacedSharedStore must declare itself a ``Mapping`` so consumers
        using duck-typed isinstance checks recognize it as dict-like."""
        from collections.abc import Mapping, MutableMapping

        from pflow.runtime.engine.namespaced_store import NamespacedSharedStore

        store = NamespacedSharedStore({"k": "v"}, "k")
        assert isinstance(store, Mapping)
        assert isinstance(store, MutableMapping)

    def test_unresolvable_path_through_proxy_echoes_template(self):
        """Permissive-mode contract: unresolvable refs leave the ``${var}``
        literal in place (consumed by `_resolve_chunk_value`'s permissive-
        echo branch which collapses to ``_CHUNK_ABSENT``)."""
        from pflow.runtime.engine.namespaced_store import NamespacedSharedStore

        store = NamespacedSharedStore({"consumer": {}}, "consumer")
        assert TemplateResolver.resolve_template("${unknown.field}", store) == "${unknown.field}"


class TestLiteralOperands:
    """Optional A: ?? accepts JSON literal operands, plus bare-literal templates.

    Note: variable names ``true``, ``false``, ``null`` are reserved as literal
    keywords; use other identifiers (the WorkflowValidator rejects them loudly).
    """

    def test_literal_number_fallback(self):
        assert TemplateResolver.resolve_template("${node.x ?? 0}", {}) == 0

    def test_literal_string_fallback(self):
        assert TemplateResolver.resolve_template('${node.x ?? "default"}', {}) == "default"

    def test_literal_null_fallback(self):
        assert TemplateResolver.resolve_template("${node.x ?? null}", {}) is None

    def test_literal_bool_fallback_returns_python_true(self):
        assert TemplateResolver.resolve_template("${node.x ?? true}", {}) is True

    def test_literal_negative_number(self):
        assert TemplateResolver.resolve_template("${node.x ?? -5}", {}) == -5

    def test_literal_float(self):
        assert TemplateResolver.resolve_template("${node.x ?? 3.5}", {}) == 3.5

    def test_literal_empty_array(self):
        assert TemplateResolver.resolve_template("${node.x ?? []}", {}) == []

    def test_literal_empty_object(self):
        assert TemplateResolver.resolve_template("${node.x ?? {}}", {}) == {}

    def test_literal_as_chain_terminal(self):
        assert TemplateResolver.resolve_template('${a ?? b ?? "fallback"}', {}) == "fallback"

    def test_literal_at_left_short_circuits(self):
        # ${0 ?? a} — literal always resolves, never reaches `a`.
        assert TemplateResolver.resolve_template("${0 ?? a}", {"a": "ignored"}) == 0

    def test_present_value_wins_over_literal(self):
        ctx = {"node": {"x": "present"}}
        assert TemplateResolver.resolve_template("${node.x ?? 0}", ctx) == "present"

    def test_present_but_falsy_left_value_wins_over_literal(self):
        # Coalesce uses existence, NOT truthiness — a present-but-falsy left value
        # must win over the literal fallback. A naive truthiness reimplementation
        # would regress here (and test_present_value_wins_over_literal, using a
        # truthy string, would not catch it).
        assert TemplateResolver.resolve_template("${node.x ?? 5}", {"node": {"x": 0}}) == 0
        assert TemplateResolver.resolve_template("${node.x ?? 5}", {"node": {"x": ""}}) == ""
        assert TemplateResolver.resolve_template("${node.x ?? 5}", {"node": {"x": False}}) is False

    def test_leading_zero_literal_does_not_resolve_as_a_literal(self):
        # 007 is not valid JSON, so the grammar excludes it — the bare template
        # is not a recognized literal and is left unchanged (the validator rejects
        # it at parse time; this just pins the runtime non-resolution).
        assert TemplateResolver.resolve_template("${007}", {}) == "${007}"

    def test_number_fallback_preserves_int_type(self):
        result = TemplateResolver.resolve_template("${node.x ?? 0}", {})
        assert result == 0
        assert isinstance(result, int) and not isinstance(result, bool)

    def test_bare_literal_number(self):
        assert TemplateResolver.resolve_template("${0}", {}) == 0

    def test_bare_literal_string(self):
        assert TemplateResolver.resolve_template('${"hello"}', {}) == "hello"

    def test_bare_literal_null(self):
        assert TemplateResolver.resolve_template("${null}", {}) is None

    def test_bare_literal_true_reserved(self):
        # Variable named `true` is unreachable — resolves to the literal.
        assert TemplateResolver.resolve_template("${true}", {"true": "x"}) is True

    def test_inline_literal_stringifies(self):
        assert TemplateResolver.resolve_template("Hello ${0}", {}) == "Hello 0"

    def test_extract_variables_skips_literal_fallback(self):
        assert TemplateResolver.extract_variables("${node.x ?? 0}") == {"node.x"}

    def test_extract_variables_skips_left_literal(self):
        assert TemplateResolver.extract_variables("${0 ?? a}") == {"a"}

    def test_extract_variables_skips_middle_literal(self):
        assert TemplateResolver.extract_variables("${a ?? 0 ?? b}") == {"a", "b"}

    def test_extract_variables_bare_literal_is_empty(self):
        assert TemplateResolver.extract_variables("${0}") == set()

    def test_disambiguation_truthy_prefix_is_variable(self):
        # `truthy_value` must NOT be parsed as literal `true` + garbage.
        ctx = {"truthy_value": "TV"}
        assert TemplateResolver.resolve_template("${truthy_value ?? 0}", ctx) == "TV"

    def test_disambiguation_falsey_prefix_is_variable(self):
        ctx = {"falsey_check": "FC"}
        assert TemplateResolver.resolve_template("${falsey_check ?? 0}", ctx) == "FC"

    def test_disambiguation_null_prefix_is_variable(self):
        ctx = {"null_node": "NN"}
        assert TemplateResolver.resolve_template("${null_node ?? 0}", ctx) == "NN"

    def test_whitespace_tolerance(self):
        assert TemplateResolver.resolve_template("${a??0}", {}) == 0
        assert TemplateResolver.resolve_template("${a ?? 0}", {}) == 0
        assert TemplateResolver.resolve_template("${a  ??  0}", {}) == 0

    def test_is_literal_operand_predicate(self):
        assert TemplateResolver.is_literal_operand("0") is True
        assert TemplateResolver.is_literal_operand('"x"') is True
        assert TemplateResolver.is_literal_operand("true") is True
        assert TemplateResolver.is_literal_operand("null") is True
        assert TemplateResolver.is_literal_operand("[]") is True
        assert TemplateResolver.is_literal_operand("-5") is True
        assert TemplateResolver.is_literal_operand("node.field") is False
        assert TemplateResolver.is_literal_operand("truthy_value") is False
        assert TemplateResolver.is_literal_operand("") is False
