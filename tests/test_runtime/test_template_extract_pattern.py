"""Tests for the shared TEMPLATE_EXTRACT_PATTERN.

TEMPLATE_EXTRACT_PATTERN is a loose extraction regex on TemplateResolver
used by data_flow.py, validator.py, template_errors.py, and trace_report.py
for template discovery (not resolution). It captures everything between ${ and }.
"""

import re

from pflow.core.templates import TemplateResolver

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
