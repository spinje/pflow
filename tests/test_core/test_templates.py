"""The typed parse of ``pflow.core.templates``: AST shapes, spans, immutability,
boundedness, totality, and the path grammar (Task 170 phase 4a).

The corpus (``test_template_grammar.py``, ``test_template_parity.py``) pins what
consumers observe; this file pins the structure they read.
"""

from __future__ import annotations

import dataclasses
import itertools
import logging
from typing import Any

import pytest

from pflow.core.templates import (
    DynamicIndex,
    Expression,
    Field,
    Index,
    Issue,
    Literal,
    Reference,
    Resolution,
    Template,
    TemplateResolver,
    Text,
    lookup,
    parse,
    parse_path,
    resolve,
)


def ref(raw: str) -> Reference:
    parsed = parse_path(raw)
    assert parsed is not None, raw
    return parsed


# ---------------------------------------------------------------------------
# AST shapes and spans
# ---------------------------------------------------------------------------

SHAPES: tuple[tuple[str, tuple[Any, ...], bool], ...] = (
    ("", (), False),
    ("plain", (Text("plain"),), False),
    ("${a}", (Expression((Reference("a", (), "a"),), "a", (0, 4)),), False),
    (
        "${node.items[0].n}",
        (
            Expression(
                (Reference("node", (Field("items"), Index(0), Field("n")), "node.items[0].n"),),
                "node.items[0].n",
                (0, 18),
            ),
        ),
        False,
    ),
    (
        '${a[${i.j}].x ?? "d"}',
        (
            Expression(
                (
                    Reference("a", (DynamicIndex(Reference("i", (Field("j"),), "i.j")), Field("x")), "a[${i.j}].x"),
                    Literal('"d"'),
                ),
                'a[${i.j}].x ?? "d"',
                (0, 21),
            ),
        ),
        False,
    ),
    ("[${a}]", (Text("["), Expression((Reference("a", (), "a"),), "a", (1, 5)), Text("]")), False),
    (
        "${a}${b}",
        (Expression((Reference("a", (), "a"),), "a", (0, 4)), Expression((Reference("b", (), "b"),), "b", (4, 8))),
        False,
    ),
    ("Hi $${x} ${y}!", (Text("Hi ${x} "), Expression((Reference("y", (), "y"),), "y", (9, 13)), Text("!")), True),
    ("$$${x}", (Text("$${x}"),), True),
    ("$${a[${i}]}", (Text("${a[${i}]}"),), True),
    ("$${unclosed ${b}", (Text("${unclosed "), Expression((Reference("b", (), "b"),), "b", (12, 16))), True),
    ("${c.result.0} tail", (Issue("${c.result.0}", (0, 13), "malformed"), Text(" tail")), False),
    ("${a", (Issue("${a", (0, 3), "malformed"),), False),
    ("${a[${i ?? 0}]}", (Issue("${a[${i ?? 0}", (0, 13), "malformed"), Text("]}")), False),
    ('${a ?? "\\q"}', (Issue('${a ?? "\\q"}', (0, 12), "bad_literal"),), False),
    ("${a ?? 007}", (Issue("${a ?? 007}", (0, 11), "bad_literal"),), False),
    ("${0}", (Expression((Literal("0"),), "0", (0, 4)),), False),
    ("${true}", (Expression((Literal("true"),), "true", (0, 7)),), False),
    ("${truthy}", (Expression((Reference("truthy", (), "truthy"),), "truthy", (0, 9)),), False),
)


@pytest.mark.parametrize(("source", "segments", "escaped"), SHAPES, ids=[s[0] or "<empty>" for s in SHAPES])
def test_parse_shape(source: str, segments: tuple[Any, ...], escaped: bool) -> None:
    assert parse(source) == Template(source, segments, escaped)


def test_views() -> None:
    template = parse("pre ${a[${i}].x ?? b} ${c.x.0} $${esc}")
    assert [e.raw for e in template.expressions] == ["a[${i}].x ?? b"]
    assert [i.raw for i in template.issues] == ["${c.x.0}"]
    # Dependency view: outer references, then each dynamic index's inner one.
    assert [r.raw for r in template.references] == ["a[${i}].x", "i", "b"]
    # Value view: only value-position operands.
    assert [op.raw for op in template.expressions[0].operands] == ["a[${i}].x", "b"]
    assert template.escaped and template.needs_resolution and not template.is_simple
    assert parse("${a[${i}].x}").is_simple
    assert not parse("${c.x.0}").needs_resolution  # an Issue-only value is static
    assert parse("$${x}").needs_resolution and not parse("$${x}").expressions


# ---------------------------------------------------------------------------
# Immutability and boundedness (a cached AST is shared across runs and threads)
# ---------------------------------------------------------------------------


def test_ast_is_frozen_and_uses_tuples() -> None:
    template = parse("${a[${i}].x ?? []} ${b}")
    assert parse("${a[${i}].x ?? []} ${b}") is template  # cached: one shared object
    expression = template.expressions[0]
    reference = expression.operands[0]
    assert isinstance(reference, Reference)
    for node, attr in ((template, "source"), (expression, "raw"), (reference, "root"), (reference.path[0], "ref")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(node, attr, "mutated")
    assert all(type(seq) is tuple for seq in (template.segments, expression.operands, reference.path))


def test_literal_value_is_fresh_on_every_resolution() -> None:
    first = resolve("${missing ?? []}", {}).value
    first.append("leak")
    second = resolve("${missing ?? []}", {}).value
    assert second == [] and second is not first


def test_parse_cache_is_bounded() -> None:
    assert parse.cache_info().maxsize is not None


# ---------------------------------------------------------------------------
# Totality: parse and resolve never raise
# ---------------------------------------------------------------------------

_TOKENS = ("$", "{", "}", "${", "$${", "a", ".", "[", "]", "??", "0", '"', " ", "é")
_FIXED = (
    "${a[${i}].x}",
    "${a[${i}].x ?? b}",
    "${r[${i}]}",
    "$${a[${i}]}",
    "$${FOO:-${bar}}",
    "Type $${ to open. Hi ${name}",
    "${x} $${x}",
    "${arr[${idx ?? 0}]}",
    "${a[${b[${c}]}]}",
    '${a ?? "${b}"}',
    "[${none_val}]",
    "${m[0][1]}",
    "${data.result.}",
    "${data..result.x}",
    "${c.result.0}",
    "${ a }",
    "${#x}",
    "${VAR:-x}",
    "$",
    "${",
    "}",
    "$$",
    "${\u00e9}",
    "\u00e9 ${a} \u2603",
    "${a\n}",
    '${a ?? "\\u12"}',
    '${a ?? "a\tb"}',
    "$${",
    "$${}",
    "${}}",
    "{{${a}}}",
    "${a[${i}]",
    "${a[${}]}",
    "${a[${ i }]}",
    "${a[-1]}",
    "${a[01]}",
    "$$$$${a}",
    "${" * 20,
    "}" * 20,
    "${a}" * 50,
)
FUZZ: tuple[str, ...] = tuple("".join(p) for p in itertools.product(_TOKENS, repeat=2)) + _FIXED


def test_fuzz_set_size() -> None:
    assert len(FUZZ) == 14 * 14 + 40


@pytest.mark.parametrize("source", FUZZ)
def test_parse_and_resolve_never_raise(source: str) -> None:
    template = parse(source)
    assert isinstance(template, Template)
    assert isinstance(resolve(source, {"a": [1], "i": 0, "b": "B"}), Resolution)
    # The uncached scans agree with the cached parse.
    assert TemplateResolver.has_templates(source) is template.needs_resolution
    assert TemplateResolver.has_references(source) is bool(template.expressions)


# ---------------------------------------------------------------------------
# The path grammar (the eight ``TestSplitTemplatePath`` expectations, re-homed)
# ---------------------------------------------------------------------------

PATHS: tuple[tuple[str, Reference | None], ...] = (
    ("node.field", Reference("node", (Field("field"),), "node.field")),
    ("a.b.c", Reference("a", (Field("b"), Field("c")), "a.b.c")),
    ("node", Reference("node", (), "node")),
    (
        "drafts.results[${item.draft_index}].response",
        Reference(
            "drafts",
            (Field("results"), DynamicIndex(ref("item.draft_index")), Field("response")),
            "drafts.results[${item.draft_index}].response",
        ),
    ),
    (
        "node.data[${__index__}].field",
        Reference(
            "node", (Field("data"), DynamicIndex(ref("__index__")), Field("field")), "node.data[${__index__}].field"
        ),
    ),
    (
        "a[${x.y}].b[${z.w}].c",
        Reference(
            "a", (DynamicIndex(ref("x.y")), Field("b"), DynamicIndex(ref("z.w")), Field("c")), "a[${x.y}].b[${z.w}].c"
        ),
    ),
    (
        "node.results[${item.data.index}].value",
        Reference(
            "node",
            (Field("results"), DynamicIndex(ref("item.data.index")), Field("value")),
            "node.results[${item.data.index}].value",
        ),
    ),
    ("", None),
    ("node.data[${idx}]", Reference("node", (Field("data"), DynamicIndex(ref("idx"))), "node.data[${idx}]")),
    # Outside the grammar: multi-index, `??` or nesting in an index, digit/empty segments.
    ("m[0][1]", None),
    ("a[${i ?? 0}]", None),
    ("a[${b[${c}]}]", None),
    ("c.result.0", None),
    ("data..x", None),
    ("result.@type", None),
)


@pytest.mark.parametrize(("path", "expected"), PATHS, ids=[p[0] or "<empty>" for p in PATHS])
def test_parse_path(path: str, expected: Reference | None) -> None:
    assert parse_path(path) == expected


def test_inner_reference_is_static() -> None:
    inner = ref("a[${i.j[0]}]").path[0]
    assert inner == DynamicIndex(Reference("i", (Field("j"), Index(0)), "i.j[0]"))


# ---------------------------------------------------------------------------
# The walk: one Reference, whatever fails inside it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("index", "found"),
    [(0, True), (1, True), (2, False), (-1, False), (True, False), (None, False), ("1", False), (1.0, False)],
)
def test_dynamic_index_must_be_an_in_range_int(index: Any, found: bool) -> None:
    context = {"a": [{"x": "v0"}, {"x": "v1"}], "i": index}
    assert lookup(ref("a[${i}].x"), context)[0] is found
    result = resolve("${a[${i}].x}", context)
    assert result.ok is found
    if not found:
        assert result == Resolution("${a[${i}].x}", unresolved=frozenset({"a[${i}].x"}))


def test_non_int_index_warns_and_coalesce_falls_through(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="pflow.core.templates")
    assert resolve("${a[${i}].x ?? b}", {"a": [{"x": "v"}], "i": "s", "b": "fb"}) == Resolution("fb")
    assert "Nested index must be integer, got str" in caplog.text


def test_dynamic_index_over_json_string_list() -> None:
    assert resolve("${a[${i}].x}", {"a": '[{"x": 7}]', "i": 0}) == Resolution(7)


def test_raw_path_reader_chains_indices_through_json_strings() -> None:
    """The raw reader and the template walk share one walk: every index step parses a
    JSON-array string (before Task 170 4a the raw reader parsed only before the chain)."""
    context = {"x": ["[1, 2]"]}
    assert TemplateResolver.variable_exists("x[0][1]", context) is True
    assert TemplateResolver.resolve_value("x[0][1]", context) == 2


# ---------------------------------------------------------------------------
# Facade helpers that read the parse
# ---------------------------------------------------------------------------


def test_extract_first_field_segment_reads_the_path_grammar() -> None:
    assert TemplateResolver.extract_first_field_segment("a[${item.i}].x") == "x"
    assert TemplateResolver.extract_first_field_segment("node[0].field") == "field"
    assert TemplateResolver.extract_first_field_segment("data[0]") is None
    assert TemplateResolver.extract_first_field_segment("result.@type") == "@type"  # raw fallback


def test_resolve_coalesce_speaks_the_expression_grammar() -> None:
    context = {"b": {"x": 1}, "i": 0, "a": [{"x": 2}]}
    assert TemplateResolver.resolve_coalesce("missing ?? b.x", context) == (1, "resolved")
    assert TemplateResolver.resolve_coalesce("a[${i}].x", context) == (2, "resolved")
    assert TemplateResolver.resolve_coalesce("b.x.0", context) == (None, "unresolved")  # not an expression


def test_extract_variables_is_the_value_view() -> None:
    assert TemplateResolver.extract_variables('${a[${i}].x ?? b ?? "d"} $${e} ${c.0}') == {"a[${i}].x", "b"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [("a.x", (1, "x")), ("a[0].x.y", (4, "x")), ("a[${i.j}].x", (9, "x")), ("a", None), ("a[${i}]", None)],
)
def test_first_field_offset_skips_the_root_index(path: str, expected: tuple[int, str] | None) -> None:
    reference = ref(path)
    assert reference.first_field() == expected
    if expected is not None:
        assert path[expected[0]] == "." and path[expected[0] + 1 :].startswith(expected[1])
