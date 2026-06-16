"""Tests for safe_load_preserving_templates (issue #482).

The helper shields pflow ``${...}`` templates from PyYAML's flow tokenizer so an
unquoted template inside a flow map/sequence parses like the block form. These
unit tests own the mechanism; integration through the parser and file_resolver is
covered in test_markdown_parser.py and test_file_resolver.py.
"""

from __future__ import annotations

import pytest
import yaml

from pflow.core.yaml_utils import safe_load_preserving_templates as load


class TestHappyPath:
    def test_unquoted_template_in_flow_map(self) -> None:
        assert load("{ x: ${y} }") == {"x": "${y}"}

    def test_unquoted_template_in_flow_sequence(self) -> None:
        assert load("[${a}, ${b}, literal]") == ["${a}", "${b}", "literal"]

    def test_multiple_templates(self) -> None:
        assert load("{ a: ${one}, b: ${two} }") == {"a": "${one}", "b": "${two}"}

    def test_template_embedded_in_scalar(self) -> None:
        assert load("{ url: ${base}/path/${id} }") == {"url": "${base}/path/${id}"}

    def test_nested_flow_collections(self) -> None:
        assert load("{ n: { deep: ${v} }, l: [${i}] }") == {"n": {"deep": "${v}"}, "l": ["${i}"]}

    def test_template_as_key(self) -> None:
        assert load("{ ${k}: v }") == {"${k}": "v"}

    def test_quoted_and_unquoted_are_equivalent(self) -> None:
        assert load("{ x: ${y} }") == load('{ x: "${y}" }')

    def test_block_form_unchanged(self) -> None:
        assert load("x: ${y}\nz: 3") == {"x": "${y}", "z": 3}


class TestNoOpForTemplateFreeContent:
    """No template → identical to a plain yaml.safe_load (no masking happens)."""

    def test_scalars_still_coerce(self) -> None:
        assert load("{ a: 1, b: true, c: hi, d: null }") == {"a": 1, "b": True, "c": "hi", "d": None}

    def test_matches_plain_safe_load(self) -> None:
        text = "{ list: [1, 2, 3], nested: { k: v } }"
        assert load(text) == yaml.safe_load(text)


class TestQuotedScalarEscaping:
    """Issue #518 review (finding A): templates inside quoted scalars are NOT masked.

    Masking inside a quoted scalar strips YAML's escape processing, so
    ``"${a ?? \\"x\\"}"`` would restore with literal backslashes and the resolver
    would reject it. Quoted scalars are YAML's job — leave them alone.
    """

    def test_escaped_string_literal_in_quoted_flow_value(self) -> None:
        # Outer double-quotes force ``\"``; YAML must unescape so the resolver sees a
        # valid coalesce string literal (``"DEF"``), not ``\"DEF\"``.
        assert load('{ fb: "${a ?? \\"DEF\\"}" }') == {"fb": '${a ?? "DEF"}'}

    def test_quoted_equals_unquoted_for_escaped_literal(self) -> None:
        assert load('{ fb: "${a ?? \\"DEF\\"}" }') == load('{ fb: ${a ?? "DEF"} }')

    def test_quoted_scalar_alongside_bare_template(self) -> None:
        # The quoted scalar (with a ``:`` that would otherwise confuse flow parsing)
        # is left for YAML; the bare template is still shielded.
        assert load('{ a: "hi: there", b: ${y} }') == {"a": "hi: there", "b": "${y}"}

    def test_single_quoted_template_preserved(self) -> None:
        assert load("{ fb: '${a ?? 1}' }") == {"fb": "${a ?? 1}"}


class TestBraceAwareTemplates:
    """C2: a coalesce operand with an object/array literal is captured whole.

    This is parser-level capture only — the masking regex tolerates one level of
    nested ``{}`` so the inline flow form parses these rather than truncating at the
    first ``}``. ``${a ?? {}}`` / ``${a ?? []}`` are valid runtime templates;
    ``${a ?? {"k": 1}}`` is captured here but rejected at runtime as a malformed
    literal operand (the regex is intentionally broader than the resolver grammar).
    """

    def test_empty_object_literal_operand(self) -> None:
        assert load("{ x: ${a ?? {}} }") == {"x": "${a ?? {}}"}

    def test_empty_array_literal_operand(self) -> None:
        assert load("{ x: ${a ?? []} }") == {"x": "${a ?? []}"}

    def test_object_literal_operand_with_content(self) -> None:
        # Captured whole at parse time (broader than the runtime grammar); the
        # resolver rejects it later as a malformed literal operand.
        assert load('{ x: ${a ?? {"k": 1}} }') == {"x": '${a ?? {"k": 1}}'}

    def test_inline_matches_block_for_object_operand(self) -> None:
        assert load("{ x: ${a ?? {}} }") == load("x: ${a ?? {}}")


class TestCollisionResistance:
    """W1: authored text that looks like a placeholder must not be corrupted."""

    def test_literal_placeholder_text_is_preserved(self) -> None:
        # The 'a' value literally spells an old-style placeholder; it must survive
        # untouched even though the same value also contains a real template.
        assert load("{ a: __pflow_tpl_0__, b: ${y} }") == {"a": "__pflow_tpl_0__", "b": "${y}"}


class TestErrorDeMasking:
    """C1: a YAML error must quote the author's ${...}, never the placeholder."""

    def test_malformed_template_bearing_flow_shows_source_not_placeholder(self) -> None:
        with pytest.raises(yaml.YAMLError) as excinfo:
            load("{ x: ${y}")  # missing closing brace
        message = str(excinfo.value)
        assert "__pflow_tpl_" not in message
        assert "${y}" in message

    def test_long_line_truncation_does_not_leak_placeholder(self) -> None:
        """A long/indented malformed flow must not leak a truncated placeholder.

        PyYAML truncates its error snippet (``...``) around the error column; the
        placeholder is longer than ``${...}``, so a realistically-indented line gets
        truncated *through* a placeholder. De-masking the formatted string alone would
        leave a fragment (``__pflow_tpl_ab12 ...``) — de-masking the structured marks
        renders the snippet from author text, so no fragment can survive.
        """
        with pytest.raises(yaml.YAMLError) as excinfo:
            load("  - { contender: ${candidate}")  # unclosed flow map, indented
        message = str(excinfo.value)
        assert "pflow_tpl" not in message
        assert "${candidate}" in message

    def test_malformed_template_free_flow_still_raises(self) -> None:
        with pytest.raises(yaml.YAMLError):
            load("{invalid: [unclosed")
