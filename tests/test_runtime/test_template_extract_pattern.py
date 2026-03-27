"""Tests for the shared TEMPLATE_EXTRACT_PATTERN and the _build_quoted_templates helper.

Fix 1: TEMPLATE_EXTRACT_PATTERN is a loose extraction regex on TemplateResolver
used by data_flow.py, validator.py, template_errors.py, and trace_report.py
for template discovery (not resolution). It captures everything between ${ and }.

Fix 2: _build_quoted_templates splits coalesce operands so that '${a ?? b}'
correctly exempts both 'a' and 'b' from shell type validation.
"""

import re

from pflow.runtime.template_resolver import TemplateResolver
from pflow.runtime.template_validation.type_validation import _build_quoted_templates

# ---------------------------------------------------------------------------
# Fix 1: TEMPLATE_EXTRACT_PATTERN
# ---------------------------------------------------------------------------


class TestTemplateExtractPatternExists:
    """Verify the constant exists and is a compiled regex on TemplateResolver."""

    def test_pattern_is_class_attribute(self) -> None:
        """TEMPLATE_EXTRACT_PATTERN should be accessible as a class attribute."""
        assert hasattr(TemplateResolver, "TEMPLATE_EXTRACT_PATTERN")

    def test_pattern_is_compiled_regex(self) -> None:
        """The attribute should be a compiled regex, not a raw string."""
        pattern = TemplateResolver.TEMPLATE_EXTRACT_PATTERN
        assert isinstance(pattern, re.Pattern)


class TestTemplateExtractPatternMatching:
    """Verify the extraction pattern matches the expected template forms."""

    def test_matches_simple_variable(self) -> None:
        """Basic ${var} should match and capture 'var'."""
        matches = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall("${var}")
        assert matches == ["var"]

    def test_matches_dotted_path(self) -> None:
        """${node.field} should match and capture 'node.field'."""
        matches = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall("${node.field}")
        assert matches == ["node.field"]

    def test_matches_array_index_path(self) -> None:
        """${data[0].title} should match and capture 'data[0].title'."""
        matches = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall("${data[0].title}")
        assert matches == ["data[0].title"]

    def test_matches_coalesce_expression(self) -> None:
        """${a ?? b} should capture the entire 'a ?? b' as one group."""
        matches = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall("${a ?? b}")
        assert matches == ["a ?? b"]

    def test_does_not_match_escaped_dollar(self) -> None:
        """$${var} (double dollar escape) should NOT match due to negative lookbehind."""
        matches = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall("$${var}")
        assert matches == []

    def test_captures_multiple_templates(self) -> None:
        """Multiple templates in one string should each be captured."""
        matches = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall("${a} and ${b}")
        assert matches == ["a", "b"]

    def test_captures_multiple_with_surrounding_text(self) -> None:
        """Templates embedded in prose should still be captured."""
        text = "echo ${node.stdout} | jq '.${field}'"
        matches = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall(text)
        assert matches == ["node.stdout", "field"]

    def test_escaped_among_real_templates(self) -> None:
        """Only non-escaped templates should match when mixed with escaped ones."""
        text = "${real} and $${escaped} and ${also_real}"
        matches = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall(text)
        assert matches == ["real", "also_real"]

    def test_deeply_nested_path(self) -> None:
        """Deep paths like ${a.b.c.d} should be captured fully."""
        matches = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall("${a.b.c.d}")
        assert matches == ["a.b.c.d"]

    def test_coalesce_with_paths(self) -> None:
        """Coalesce with dotted paths captures entire expression."""
        text = "${branch-a.result ?? branch-b.result}"
        matches = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall(text)
        assert matches == ["branch-a.result ?? branch-b.result"]


# ---------------------------------------------------------------------------
# Fix 2: _build_quoted_templates coalesce splitting
# ---------------------------------------------------------------------------


class TestBuildQuotedTemplatesSimple:
    """Test _build_quoted_templates with non-coalesce templates."""

    def test_simple_quoted_template(self) -> None:
        """Single quoted template: echo '${result}' -> {'result'}."""
        result = _build_quoted_templates("echo '${result}'")
        assert result == {"result"}

    def test_multiple_quoted_templates(self) -> None:
        """Multiple quoted templates: echo '${a}' '${b}' -> {'a', 'b'}."""
        result = _build_quoted_templates("echo '${a}' '${b}'")
        assert result == {"a", "b"}

    def test_non_quoted_template_not_captured(self) -> None:
        """Unquoted template: echo ${var} -> empty set."""
        result = _build_quoted_templates("echo ${var}")
        assert result == set()

    def test_no_templates(self) -> None:
        """String with no templates at all -> empty set."""
        result = _build_quoted_templates("echo hello world")
        assert result == set()


class TestBuildQuotedTemplatesCoalesce:
    """Test that coalesce operands are split so both sides are exempted."""

    def test_coalesce_in_quotes_splits_operands(self) -> None:
        """Coalesce: echo '${a.result ?? b.result}' -> {'a.result', 'b.result'}."""
        result = _build_quoted_templates("echo '${a.result ?? b.result}'")
        assert result == {"a.result", "b.result"}

    def test_triple_coalesce_splits_all(self) -> None:
        """Three-way coalesce: all operands should be in the set."""
        result = _build_quoted_templates("echo '${x ?? y ?? z}'")
        assert result == {"x", "y", "z"}

    def test_mixed_quoted_and_unquoted(self) -> None:
        """Only quoted templates are captured; unquoted are excluded."""
        result = _build_quoted_templates("echo '${a ?? b}' ${c}")
        assert result == {"a", "b"}

    def test_coalesce_with_dotted_paths(self) -> None:
        """Dotted paths in coalesce are split and preserved."""
        result = _build_quoted_templates("jq . '${node-a.stdout ?? node-b.stdout}'")
        assert result == {"node-a.stdout", "node-b.stdout"}

    def test_mixed_simple_and_coalesce_quoted(self) -> None:
        """Mix of simple and coalesce quoted templates."""
        result = _build_quoted_templates("cmd '${simple}' '${a ?? b}'")
        assert result == {"simple", "a", "b"}
