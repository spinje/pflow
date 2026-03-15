"""Tests for the ?? coalesce operator in template syntax.

The coalesce operator enables branch-convergence patterns where only one of
several upstream branches executes. Syntax: ${branch-a.output ?? branch-b.output}

Semantics:
- Try each operand left to right
- If an operand's root node is ABSENT from context (didn't execute), skip it
- If an operand's root node is PRESENT but the nested path fails, that's a typo -> path_error
- First operand whose root is present and path resolves wins
- If no operand resolves, the template is returned unchanged (existing unresolved behavior)
"""

from pflow.runtime.template_resolver import TemplateResolver


class TestCoalesceRegex:
    """Test that regex patterns correctly match coalesce expressions."""

    def test_template_pattern_matches_simple_coalesce(self):
        """TEMPLATE_PATTERN should match ${a ?? b} in a string."""
        matches = TemplateResolver.TEMPLATE_PATTERN.findall("${a ?? b}")
        assert len(matches) == 1
        assert matches[0] == "a ?? b"

    def test_template_pattern_matches_coalesce_with_paths(self):
        """TEMPLATE_PATTERN should match ${a.field ?? b.field[0] ?? c}."""
        matches = TemplateResolver.TEMPLATE_PATTERN.findall("${a.field ?? b.field[0] ?? c}")
        assert len(matches) == 1
        assert matches[0] == "a.field ?? b.field[0] ?? c"

    def test_template_pattern_matches_coalesce_with_hyphens(self):
        """TEMPLATE_PATTERN should match node names with hyphens (common in pflow)."""
        matches = TemplateResolver.TEMPLATE_PATTERN.findall("${branch-high.stdout ?? branch-low.stdout}")
        assert len(matches) == 1
        assert matches[0] == "branch-high.stdout ?? branch-low.stdout"

    def test_template_pattern_does_not_match_trailing_coalesce(self):
        """TEMPLATE_PATTERN should NOT match ${a ?? } (no valid var after ??)."""
        matches = TemplateResolver.TEMPLATE_PATTERN.findall("${a ?? }")
        # The regex requires a valid variable name after ??, so this should not match
        # the full expression. It might match just "a" depending on the regex.
        for m in matches:
            assert "??" not in m, f"Should not match incomplete coalesce: {m!r}"

    def test_template_pattern_does_not_match_leading_coalesce(self):
        """TEMPLATE_PATTERN should NOT match ${ ?? b} (no valid var before ??)."""
        matches = TemplateResolver.TEMPLATE_PATTERN.findall("${ ?? b}")
        for m in matches:
            assert "??" not in m, f"Should not match incomplete coalesce: {m!r}"

    def test_template_pattern_matches_coalesce_in_surrounding_text(self):
        """TEMPLATE_PATTERN should find coalesce expression embedded in text."""
        matches = TemplateResolver.TEMPLATE_PATTERN.findall("Result: ${a.out ?? b.out} done")
        assert len(matches) == 1
        assert matches[0] == "a.out ?? b.out"

    def test_template_pattern_matches_multiple_coalesce_in_string(self):
        """TEMPLATE_PATTERN should find multiple coalesce expressions in one string."""
        matches = TemplateResolver.TEMPLATE_PATTERN.findall("${a ?? b} and ${c ?? d}")
        assert len(matches) == 2
        assert "a ?? b" in matches
        assert "c ?? d" in matches

    def test_simple_template_pattern_matches_coalesce(self):
        """SIMPLE_TEMPLATE_PATTERN should match when entire string is ${a ?? b}."""
        match = TemplateResolver.SIMPLE_TEMPLATE_PATTERN.match("${a ?? b}")
        assert match is not None
        assert match.group(1) == "a ?? b"

    def test_simple_template_pattern_matches_triple_coalesce(self):
        """SIMPLE_TEMPLATE_PATTERN should match ${a ?? b ?? c}."""
        match = TemplateResolver.SIMPLE_TEMPLATE_PATTERN.match("${a ?? b ?? c}")
        assert match is not None
        assert match.group(1) == "a ?? b ?? c"

    def test_simple_template_pattern_rejects_coalesce_with_surrounding_text(self):
        """SIMPLE_TEMPLATE_PATTERN should NOT match when there's text around the expression."""
        match = TemplateResolver.SIMPLE_TEMPLATE_PATTERN.match("text ${a ?? b}")
        assert match is None

    def test_is_simple_template_with_coalesce(self):
        """is_simple_template should return True for ${a ?? b}."""
        assert TemplateResolver.is_simple_template("${a ?? b}") is True

    def test_is_simple_template_coalesce_with_paths(self):
        """is_simple_template should return True for ${a.x ?? b.y}."""
        assert TemplateResolver.is_simple_template("${a.x ?? b.y}") is True

    def test_is_simple_template_rejects_coalesce_in_text(self):
        """is_simple_template should return False when coalesce is part of larger string."""
        assert TemplateResolver.is_simple_template("prefix ${a ?? b}") is False
        assert TemplateResolver.is_simple_template("${a ?? b} suffix") is False


class TestSplitCoalesceOperands:
    """Test splitting coalesce expressions into operands."""

    def test_two_operands(self):
        """Split 'a ?? b.field' into ['a', 'b.field']."""
        result = TemplateResolver.split_coalesce_operands("a ?? b.field")
        assert result == ["a", "b.field"]

    def test_single_operand_no_coalesce(self):
        """Single variable without ?? returns single-element list."""
        result = TemplateResolver.split_coalesce_operands("a")
        assert result == ["a"]

    def test_single_operand_with_path(self):
        """Single variable with path and no ?? returns single-element list."""
        result = TemplateResolver.split_coalesce_operands("a.field")
        assert result == ["a.field"]

    def test_three_operands(self):
        """Split 'a ?? b ?? c.x[0]' into three operands."""
        result = TemplateResolver.split_coalesce_operands("a ?? b ?? c.x[0]")
        assert result == ["a", "b", "c.x[0]"]

    def test_extra_whitespace_is_stripped(self):
        """Whitespace around ?? should be stripped from operands."""
        result = TemplateResolver.split_coalesce_operands("a  ??  b.field")
        assert result == ["a", "b.field"]

    def test_hyphenated_node_names(self):
        """Hyphenated node names (common in pflow) should be preserved."""
        result = TemplateResolver.split_coalesce_operands("branch-high.stdout ?? branch-low.stdout")
        assert result == ["branch-high.stdout", "branch-low.stdout"]


class TestIsCoalesceExpression:
    """Test detection of coalesce operator."""

    def test_coalesce_expression_detected(self):
        """'a ?? b' should be detected as coalesce."""
        assert TemplateResolver.is_coalesce_expression("a ?? b") is True

    def test_single_variable_not_coalesce(self):
        """'a' is not a coalesce expression."""
        assert TemplateResolver.is_coalesce_expression("a") is False

    def test_path_variable_not_coalesce(self):
        """'a.field' is not a coalesce expression."""
        assert TemplateResolver.is_coalesce_expression("a.field") is False

    def test_triple_coalesce_detected(self):
        """'a ?? b ?? c' should be detected as coalesce."""
        assert TemplateResolver.is_coalesce_expression("a ?? b ?? c") is True

    def test_array_path_not_coalesce(self):
        """'a[0].field' is not a coalesce expression (no ??)."""
        assert TemplateResolver.is_coalesce_expression("a[0].field") is False


class TestExtractVariablesCoalesce:
    """Test extract_variables with coalesce expressions."""

    def test_coalesce_extracts_both_operands(self):
        """${a ?? b.field} should extract both 'a' and 'b.field'."""
        result = TemplateResolver.extract_variables("${a ?? b.field}")
        assert result == {"a", "b.field"}

    def test_coalesce_and_regular_in_same_string(self):
        """'${a ?? b} and ${c}' should extract all three variables."""
        result = TemplateResolver.extract_variables("${a ?? b} and ${c}")
        assert result == {"a", "b", "c"}

    def test_single_variable_unchanged(self):
        """${x} extracts just {'x'} — no regression from coalesce support."""
        result = TemplateResolver.extract_variables("${x}")
        assert result == {"x"}

    def test_triple_coalesce_extracts_all(self):
        """${a ?? b ?? c} should extract all three operands."""
        result = TemplateResolver.extract_variables("${a ?? b ?? c}")
        assert result == {"a", "b", "c"}

    def test_coalesce_with_paths_extracts_full_paths(self):
        """${node-a.stdout ?? node-b.stdout} extracts full path strings."""
        result = TemplateResolver.extract_variables("${node-a.stdout ?? node-b.stdout}")
        assert result == {"node-a.stdout", "node-b.stdout"}

    def test_multiple_coalesce_expressions_in_one_string(self):
        """Multiple coalesce expressions in one string extract all operands."""
        result = TemplateResolver.extract_variables("${a ?? b} then ${c ?? d.x}")
        assert result == {"a", "b", "c", "d.x"}


class TestResolveCoalesce:
    """Test resolve_coalesce method directly."""

    def test_resolved_when_first_root_present(self):
        """When first operand's root is in context, resolve it."""
        context = {"a": {"stdout": "hello"}}
        value, status = TemplateResolver.resolve_coalesce("a.stdout ?? b.stdout", context)
        assert status == "resolved"
        assert value == "hello"

    def test_resolved_when_second_root_present(self):
        """When first root absent, second root present, resolve second."""
        context = {"b": {"stdout": "world"}}
        value, status = TemplateResolver.resolve_coalesce("a.stdout ?? b.stdout", context)
        assert status == "resolved"
        assert value == "world"

    def test_first_wins_when_both_present(self):
        """When both roots are in context, first operand wins."""
        context = {
            "a": {"stdout": "first"},
            "b": {"stdout": "second"},
        }
        value, status = TemplateResolver.resolve_coalesce("a.stdout ?? b.stdout", context)
        assert status == "resolved"
        assert value == "first"

    def test_path_error_when_root_present_but_path_invalid(self):
        """When root exists but nested path fails, return path_error (typo detection)."""
        context = {"a": {"stdout": "hello"}}
        # 'a' is present but 'a.typo' doesn't exist — this is a typo, not a missing branch
        value, status = TemplateResolver.resolve_coalesce("a.typo ?? b.stdout", context)
        assert status == "path_error"
        assert value == "a.typo"  # Returns the failing operand string

    def test_path_error_on_second_operand(self):
        """path_error can occur on the second operand if first root is absent."""
        context = {"b": {"stdout": "hello"}}
        # 'a' absent (skip), 'b' present but 'b.typo' fails
        value, status = TemplateResolver.resolve_coalesce("a.stdout ?? b.typo", context)
        assert status == "path_error"
        assert value == "b.typo"

    def test_unresolved_when_all_roots_absent(self):
        """When no operand's root is in context, return unresolved."""
        context = {"c": {"data": 1}}
        value, status = TemplateResolver.resolve_coalesce("a.stdout ?? b.stdout", context)
        assert status == "unresolved"
        assert value is None

    def test_unresolved_with_empty_context(self):
        """Empty context means all roots absent — unresolved."""
        value, status = TemplateResolver.resolve_coalesce("a ?? b", {})
        assert status == "unresolved"
        assert value is None

    def test_chain_three_operands_first_resolves(self):
        """In a ?? b ?? c, first match wins when first root is present."""
        context = {"a": {"val": 1}, "c": {"val": 3}}
        value, status = TemplateResolver.resolve_coalesce("a.val ?? b.val ?? c.val", context)
        assert status == "resolved"
        assert value == 1

    def test_chain_three_operands_middle_resolves(self):
        """In a ?? b ?? c, middle operand resolves when first root absent."""
        context = {"b": {"val": 2}, "c": {"val": 3}}
        value, status = TemplateResolver.resolve_coalesce("a.val ?? b.val ?? c.val", context)
        assert status == "resolved"
        assert value == 2

    def test_chain_three_operands_last_resolves(self):
        """In a ?? b ?? c, last operand resolves when first two roots absent."""
        context = {"c": {"val": 3}}
        value, status = TemplateResolver.resolve_coalesce("a.val ?? b.val ?? c.val", context)
        assert status == "resolved"
        assert value == 3

    def test_simple_root_variable_resolves(self):
        """Coalesce with simple root variables (no path) resolves correctly."""
        context = {"b": "direct-value"}
        value, status = TemplateResolver.resolve_coalesce("a ?? b", context)
        assert status == "resolved"
        assert value == "direct-value"

    def test_root_present_as_empty_dict_counts_as_present(self):
        """Root key exists with empty dict — root IS present, but path will fail."""
        context = {"a": {}}
        # 'a' is present (the node ran, but produced no output), path 'a.stdout' fails
        value, status = TemplateResolver.resolve_coalesce("a.stdout ?? b.stdout", context)
        assert status == "path_error"
        assert value == "a.stdout"

    def test_root_present_with_none_value(self):
        """Root key exists with None value — root IS present for simple variable."""
        context = {"a": None}
        # 'a' is present and is a simple variable (no path), so it resolves to None
        value, status = TemplateResolver.resolve_coalesce("a ?? b", context)
        assert status == "resolved"
        assert value is None

    def test_resolved_value_preserves_integer(self):
        """Resolved coalesce value should preserve integer type."""
        context = {"node": {"count": 42}}
        value, status = TemplateResolver.resolve_coalesce("node.count ?? other.count", context)
        assert status == "resolved"
        assert value == 42
        assert isinstance(value, int)

    def test_resolved_value_preserves_dict(self):
        """Resolved coalesce value should preserve dict type."""
        context = {"node": {"data": {"key": "value", "nested": [1, 2]}}}
        value, status = TemplateResolver.resolve_coalesce("node.data ?? other.data", context)
        assert status == "resolved"
        assert value == {"key": "value", "nested": [1, 2]}
        assert isinstance(value, dict)

    def test_resolved_value_preserves_list(self):
        """Resolved coalesce value should preserve list type."""
        context = {"node": {"items": [1, 2, 3]}}
        value, status = TemplateResolver.resolve_coalesce("node.items ?? other.items", context)
        assert status == "resolved"
        assert value == [1, 2, 3]
        assert isinstance(value, list)

    def test_resolved_value_preserves_boolean(self):
        """Resolved coalesce value should preserve boolean type."""
        context = {"node": {"flag": False}}
        value, status = TemplateResolver.resolve_coalesce("node.flag ?? other.flag", context)
        assert status == "resolved"
        assert value is False

    def test_array_index_in_operand(self):
        """Coalesce operand with array index should resolve correctly."""
        context = {"node": {"items": ["first", "second"]}}
        value, status = TemplateResolver.resolve_coalesce("node.items[0] ?? other.items[0]", context)
        assert status == "resolved"
        assert value == "first"


class TestResolveTemplateCoalesce:
    """Test resolve_template with coalesce expressions."""

    def test_simple_coalesce_preserves_int_type(self):
        """Simple template ${a ?? b} should preserve integer type of resolved operand."""
        context = {"b": {"count": 42}}
        result = TemplateResolver.resolve_template("${a.count ?? b.count}", context)
        assert result == 42
        assert isinstance(result, int)

    def test_simple_coalesce_preserves_dict_type(self):
        """Simple template ${a ?? b} should preserve dict type of resolved operand."""
        context = {"node": {"data": {"key": "val"}}}
        result = TemplateResolver.resolve_template("${node.data ?? other.data}", context)
        assert result == {"key": "val"}
        assert isinstance(result, dict)

    def test_simple_coalesce_preserves_list_type(self):
        """Simple template ${a ?? b} should preserve list type of resolved operand."""
        context = {"node": {"items": [1, 2, 3]}}
        result = TemplateResolver.resolve_template("${node.items ?? other.items}", context)
        assert result == [1, 2, 3]
        assert isinstance(result, list)

    def test_simple_coalesce_preserves_none(self):
        """Simple template ${a ?? b} should preserve None when that's the resolved value."""
        context = {"node": {"value": None}}
        result = TemplateResolver.resolve_template("${node.value ?? other.value}", context)
        assert result is None

    def test_simple_coalesce_preserves_boolean(self):
        """Simple template ${a ?? b} should preserve boolean False."""
        context = {"node": {"flag": False}}
        result = TemplateResolver.resolve_template("${node.flag ?? other.flag}", context)
        assert result is False

    def test_complex_coalesce_does_string_interpolation(self):
        """Complex template 'text ${a ?? b} more' converts resolved value to string."""
        context = {"b": {"stdout": "world"}}
        result = TemplateResolver.resolve_template("Hello ${a.stdout ?? b.stdout}!", context)
        assert result == "Hello world!"
        assert isinstance(result, str)

    def test_complex_coalesce_int_to_string(self):
        """Complex template with int-valued coalesce converts to string."""
        context = {"node": {"count": 42}}
        result = TemplateResolver.resolve_template("Count: ${node.count ?? other.count}", context)
        assert result == "Count: 42"

    def test_all_absent_returns_template_unchanged(self):
        """When no operand resolves, template string is returned as-is."""
        context = {"unrelated": {"data": 1}}
        result = TemplateResolver.resolve_template("${a.out ?? b.out}", context)
        assert result == "${a.out ?? b.out}"

    def test_path_error_returns_template_unchanged(self):
        """When root is present but path is invalid (typo), template returned unchanged."""
        context = {"a": {"stdout": "hello"}}
        result = TemplateResolver.resolve_template("${a.typo ?? b.stdout}", context)
        assert result == "${a.typo ?? b.stdout}"

    def test_mixed_coalesce_and_regular_in_complex_template(self):
        """Mixed coalesce + regular templates in one string resolve independently."""
        context = {
            "b": {"stdout": "coalesced"},
            "c": "regular",
        }
        result = TemplateResolver.resolve_template("${a.stdout ?? b.stdout} and ${c}", context)
        assert result == "coalesced and regular"

    def test_two_coalesce_expressions_in_complex_template(self):
        """Two different coalesce expressions in one complex template."""
        context = {
            "b": {"x": "first"},
            "d": {"y": "second"},
        }
        result = TemplateResolver.resolve_template("${a.x ?? b.x} then ${c.y ?? d.y}", context)
        assert result == "first then second"

    def test_complex_coalesce_unresolved_leaves_expression(self):
        """In complex template, unresolved coalesce expression stays as-is."""
        context = {"c": "known"}
        result = TemplateResolver.resolve_template("${a ?? b} and ${c}", context)
        assert result == "${a ?? b} and known"

    def test_complex_coalesce_path_error_leaves_expression(self):
        """In complex template, path_error coalesce expression stays as-is."""
        context = {"a": {"stdout": "hello"}, "c": "known"}
        # a.typo is a path_error — template for that expression stays unchanged
        result = TemplateResolver.resolve_template("${a.typo ?? b.stdout} and ${c}", context)
        assert result == "${a.typo ?? b.stdout} and known"

    def test_coalesce_with_string_value(self):
        """Simple coalesce that resolves to a string returns the string."""
        context = {"node": {"stdout": "hello world"}}
        result = TemplateResolver.resolve_template("${node.stdout ?? other.stdout}", context)
        assert result == "hello world"
        assert isinstance(result, str)

    def test_coalesce_first_root_present_resolves_immediately(self):
        """When first root is present and path is valid, second operand is never tried."""
        context = {
            "branch-high": {"stdout": "high-result"},
            "branch-low": {"stdout": "low-result"},
        }
        result = TemplateResolver.resolve_template("${branch-high.stdout ?? branch-low.stdout}", context)
        assert result == "high-result"

    def test_coalesce_realistic_branch_convergence(self):
        """Realistic scenario: conditional branching where only one branch ran."""
        # Only the 'branch-low' branch executed
        context = {
            "branch-low": {"stdout": "handled by low-priority path"},
        }
        result = TemplateResolver.resolve_template("${branch-high.stdout ?? branch-low.stdout}", context)
        assert result == "handled by low-priority path"


class TestResolveNestedCoalesce:
    """Test resolve_nested with coalesce expressions in nested structures."""

    def test_coalesce_in_dict_value(self):
        """Coalesce in a dict value preserves type via resolve_nested."""
        context = {"b": {"count": 42}}
        params = {"result": "${a.count ?? b.count}"}
        resolved = TemplateResolver.resolve_nested(params, context)
        assert resolved["result"] == 42
        assert isinstance(resolved["result"], int)

    def test_coalesce_in_list_item(self):
        """Coalesce in a list item resolves correctly."""
        context = {"b": {"val": "found"}}
        params = ["${a.val ?? b.val}", "static"]
        resolved = TemplateResolver.resolve_nested(params, context)
        assert resolved == ["found", "static"]

    def test_coalesce_in_nested_dict(self):
        """Coalesce in deeply nested dict structure resolves correctly."""
        context = {"node": {"data": {"key": "deep-value"}}}
        params = {"outer": {"inner": "${node.data ?? other.data}"}}
        resolved = TemplateResolver.resolve_nested(params, context)
        assert resolved["outer"]["inner"] == {"key": "deep-value"}
