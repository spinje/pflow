"""Tests for nested template resolution and __index__ batch injection.

High-value tests covering:
1. Core nested index resolution: ${outer[${inner}]} -> ${outer[0]}
2. Critical edge cases (index 0, missing variables)
3. Regression: static indices still work
"""

from pflow.runtime.template_resolver import TemplateResolver


class TestNestedIndexTemplates:
    """Test ${outer[${inner}]} resolution pattern."""

    def test_nested_index_with_dunder_index(self):
        """${results[${__index__}]} - the primary use case."""
        context = {"__index__": 1, "results": ["a", "b", "c"]}
        result = TemplateResolver.resolve_template("${results[${__index__}]}", context)
        assert result == "b"

    def test_nested_index_with_path_and_rest(self):
        """${node.results[${__index__}].field} - full path before and after bracket."""
        context = {
            "__index__": 0,
            "node": {"results": [{"field": "correct"}, {"field": "wrong"}]},
        }
        result = TemplateResolver.resolve_template("${node.results[${__index__}].field}", context)
        assert result == "correct"

    def test_index_zero_not_falsy(self):
        """Index 0 resolves correctly (critical edge case)."""
        context = {"__index__": 0, "items": ["first", "second"]}
        result = TemplateResolver.resolve_template("${items[${__index__}]}", context)
        assert result == "first"

    def test_multiple_nested_in_one_string(self):
        """Multiple nested templates resolve independently."""
        context = {"i": 0, "j": 1, "a": ["x", "y"], "b": ["p", "q"]}
        result = TemplateResolver.resolve_template("${a[${i}]} ${b[${j}]}", context)
        assert result == "x q"

    def test_missing_inner_variable_preserves_template(self):
        """Missing inner variable leaves template for debugging."""
        context = {"results": ["a", "b", "c"]}
        result = TemplateResolver.resolve_template("${results[${item.index}]}", context)
        assert "${results[${item.index}]}" in str(result)

    def test_static_index_still_works(self):
        """Regression: static ${results[0]} unaffected by new feature."""
        context = {"results": [{"val": "first"}, {"val": "second"}]}
        result = TemplateResolver.resolve_template("${results[0].val}", context)
        assert result == "first"

    def test_non_integer_index_partial_resolve(self):
        """Non-integer index produces partial resolution (documents behavior)."""
        context = {"item": {"index": "str"}, "results": ["a", "b", "c"]}
        result = TemplateResolver.resolve_template("${results[${item.index}]}", context)
        # Inner template resolves, outer can't - produces malformed but debuggable output
        assert result == "${results[str]}"
