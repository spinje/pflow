"""Task 170 grammar table (1a) and walk-pair consistency rows (1f).

Pure-function rows over today's template language: for each template, what the
strict runtime grammar (``TEMPLATE_PATTERN``) finds, what the discovery view
finds (``parse()`` Expressions since phase 4a; ``_PERMISSIVE_PATTERN`` before —
only the column's FUNCTION changed, and the expected cells only on the rows that
flipped in 4a), ``has_templates``,
``is_simple_template``, ``extract_variables`` and ``resolve_template`` on one
small context. Every cell was measured by running the code, not derived.

Row discipline matches ``tests/test_integration/test_template_parity.py``: the
``today`` item passes; a row with ``after`` gets a second item asserting the
post-flip columns under ``xfail(strict=True, raises=AssertionError)``.

If a row fails, fix the divergence, never the row (from phase 2 on).
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

import pytest

from pflow.core.json_utils import try_parse_json
from pflow.core.templates import Expression, Issue, Literal, TemplateResolver, Text, parse

CTX: Mapping[str, Any] = MappingProxyType({
    "a": [{"x": "v"}],
    "i": 0,
    "j": {"k": 0},
    "name": "Al",
    "x": "hi",
    "b": "fb",
    "bar": "B",
    "none_val": None,
    "node": {"field": "F", "items": [{"n": 1}]},
    "my-node": {"out": "H"},
    "data": {"result": "R"},
    "c": {"result": "C"},
    "m": [[1, 2]],
    "FOO": "foo",
    "arr": [1, 2],
})

_COLUMNS = ("strict", "discovery", "has", "simple", "variables", "resolved")


@dataclass(frozen=True)
class G:
    """One grammar row: today's six columns, plus the columns a phase flips."""

    template: str
    strict: tuple[str, ...]
    discovery: tuple[str, ...]
    has: bool
    simple: bool
    variables: frozenset[str]
    resolved: Any
    after: Mapping[str, Any] = field(default_factory=dict)
    flips_in: str | None = None
    why: str = ""

    def __post_init__(self) -> None:
        if bool(self.after) != (self.flips_in is not None) or not set(self.after) <= set(_COLUMNS):
            raise TypeError(f"bad after/flips_in on {self.template!r}")

    def flipped(self) -> G:
        return replace(self, **self.after)


def discovery_view(template: str) -> tuple[str, ...]:
    """Template discovery: the source text of every ``parse()`` Expression."""
    return tuple(template[start:end] for start, end in (e.span for e in parse(template).expressions))


def observe(template: str) -> dict[str, Any]:
    return {
        "strict": tuple(m.group(0) for m in TemplateResolver.TEMPLATE_PATTERN.finditer(template)),
        "discovery": discovery_view(template),
        "has": TemplateResolver.has_templates(template),
        "simple": TemplateResolver.is_simple_template(template),
        "variables": frozenset(TemplateResolver.extract_variables(template)),
        "resolved": TemplateResolver.resolve_template(template, dict(CTX)),
    }


def _same(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b)


def assert_row(row: G) -> None:
    observed = observe(row.template)
    wrong = {col: (getattr(row, col), observed[col]) for col in _COLUMNS if not _same(getattr(row, col), observed[col])}
    assert not wrong, f"{row.template!r}: column (expected, observed) {wrong}"


# fmt: off
GRAMMAR_ROWS: tuple[G, ...] = (
    G('${a}', ('${a}',), ('${a}',), True, True, frozenset({'a'}), [{'x': 'v'}]),
    G('${node.field}', ('${node.field}',), ('${node.field}',), True, True, frozenset({'node.field'}), 'F'),
    G('${node.items[0].n}', ('${node.items[0].n}',), ('${node.items[0].n}',), True, True, frozenset({'node.items[0].n'}), 1),
    G('${my-node.out}', ('${my-node.out}',), ('${my-node.out}',), True, True, frozenset({'my-node.out'}), 'H'),
    G('${-x}', (), (), False, False, frozenset(), '${-x}'),
    G('${a-}', ('${a-}',), ('${a-}',), True, True, frozenset({'a-'}), '${a-}'),
    G('${_x}', ('${_x}',), ('${_x}',), True, True, frozenset({'_x'}), '${_x}'),
    G('${x1}', ('${x1}',), ('${x1}',), True, True, frozenset({'x1'}), '${x1}'),
    G('${1x}', (), (), False, False, frozenset(), '${1x}'),
    G('${c.result.0}', (), (), False, False, frozenset(), '${c.result.0}',
      why='delta 2: an Issue, not an Expression: the discovery view drops it'),
    G('${data.result.}', (), (), False, False, frozenset(), '${data.result.}',
      why='delta 2: an Issue, not an Expression: the discovery view drops it'),
    G('${data..result.x}', (), (), False, False, frozenset(), '${data..result.x}',
      why='delta 2: an Issue, not an Expression: the discovery view drops it'),
    G('${m[0][1]}', (), (), False, False, frozenset(), '${m[0][1]}'),
    G('${m[0]}', ('${m[0]}',), ('${m[0]}',), True, True, frozenset({'m[0]'}), [1, 2]),
    G('${node.field[0]}', ('${node.field[0]}',), ('${node.field[0]}',), True, True, frozenset({'node.field[0]'}), '${node.field[0]}'),
    G('[${a}]', ('${a}',), ('${a}',), True, False, frozenset({'a'}), '[[{"x": "v"}]]'),
    G('[${none_val}]', ('${none_val}',), ('${none_val}',), True, False, frozenset({'none_val'}), '[]'),
    G('${none_val}', ('${none_val}',), ('${none_val}',), True, True, frozenset({'none_val'}), None),
    G('prefix ${name} suffix', ('${name}',), ('${name}',), True, False, frozenset({'name'}), 'prefix Al suffix'),
    G('${name}${x}', ('${name}', '${x}'), ('${name}', '${x}'), True, False, frozenset({'name', 'x'}), 'Alhi'),
    G('${}', (), (), False, False, frozenset(), '${}'),
    G('${ }', (), (), False, False, frozenset(), '${ }'),
    G('${ a }', (), (), False, False, frozenset(), '${ a }'),
    G('${a', (), (), False, False, frozenset(), '${a'),
    G('${unclosed', (), (), False, False, frozenset(), '${unclosed'),
    G('${a.b', (), (), False, False, frozenset(), '${a.b'),
    G('$${var}', (), (), True, False, frozenset(), '${var}'),
    G('$${}', (), (), True, False, frozenset(), '${}'),
    G('$${unclosed', (), (), True, False, frozenset(), '${unclosed'),
    G('$$${x}', (), (), True, False, frozenset(), '$${x}'),
    G('$$', (), (), False, False, frozenset(), '$$'),
    G('$', (), (), False, False, frozenset(), '$'),
    G('Type $${ to open. Hi ${name}', ('${name}',), ('${name}',), True, False, frozenset({'name'}), 'Type ${ to open. Hi Al'),
    G('$${a[${i}]}', ('${i}',), (), True, False, frozenset(), '${a[${i}]}',
      why='delta 4: the escape consumes through the balanced `}`'),
    G('$${FOO:-${bar}}', ('${bar}',), (), True, False, frozenset(), '${FOO:-${bar}}',
      why='delta 4: the escape consumes through the balanced `}`'),
    G('${VAR:-x}', (), (), False, False, frozenset(), '${VAR:-x}'),
    G('${#x}', (), (), False, False, frozenset(), '${#x}'),
    G('${a[${i}]}', ('${a[${i}]}',), ('${a[${i}]}',), True, True, frozenset({'a[${i}]'}), {'x': 'v'},
      why='delta 3: a dynamic-index template is one simple Reference'),
    G('${a[${i}].x}', ('${a[${i}].x}',), ('${a[${i}].x}',), True, True, frozenset({'a[${i}].x'}), 'v',
      why='delta 3: one Reference; inner refs are not variables'),
    G('${a[${i}].x ?? b}', ('${a[${i}].x ?? b}',), ('${a[${i}].x ?? b}',), True, True, frozenset({'a[${i}].x', 'b'}), 'v',
      why='delta 3'),
    G('${a[${i ?? 0}]}', ('${i ?? 0}',), (), False, False, frozenset(), '${a[${i ?? 0}]}',
      why='delta 2: a `??` inner index is an Issue (static, verbatim)'),
    G('${a[${i.j}]}', ('${a[${i.j}]}',), ('${a[${i.j}]}',), True, True, frozenset({'a[${i.j}]'}), '${a[${i.j}]}',
      why='delta 3: a dotted inner is a plain static Reference'),
    G('${a[${j.k}].x}', ('${a[${j.k}].x}',), ('${a[${j.k}].x}',), True, True, frozenset({'a[${j.k}].x'}), 'v',
      why='delta 3'),
    G('${a[${b[${c}]}]}', ('${b[${c}]}',), (), False, False, frozenset(), '${a[${b[${c}]}]}',
      why='delta 2: nested dynamic indices are an Issue'),
    G('${a ?? "${b}"}', ('${a ?? "${b}"}',), ('${a ?? "${b}"}',), True, True, frozenset({'a'}), [{'x': 'v'}]),
    G('${x ?? 0}', ('${x ?? 0}',), ('${x ?? 0}',), True, True, frozenset({'x'}), 'hi'),
    G('${x ?? 007}', (), (), False, False, frozenset(), '${x ?? 007}'),
    G('${missing ?? 007}', (), (), False, False, frozenset(), '${missing ?? 007}'),
    G('${missing ?? [1,2]}', (), (), False, False, frozenset(), '${missing ?? [1,2]}'),
    G('${missing ?? "a??b"}', (), (), False, False, frozenset(), '${missing ?? "a??b"}'),
    G('${missing ?? "a?b"}', ('${missing ?? "a?b"}',), ('${missing ?? "a?b"}',), True, True, frozenset({'missing'}), 'a?b'),
    G('${missing ?? "\\q"}', (), (), False, False, frozenset(), '${missing ?? "\\q"}',
      why='the literal grammar tightens to JSON-valid escapes: a `bad_literal` Issue'),
    G('${missing ?? "\\u12"}', (), (), False, False, frozenset(), '${missing ?? "\\u12"}',
      why='the literal grammar tightens to JSON-valid escapes: a `bad_literal` Issue'),
    G('${missing ?? "a\tb"}', (), (), False, False, frozenset(), '${missing ?? "a\tb"}',
      why='the literal grammar tightens to JSON-valid escapes: a `bad_literal` Issue'),
    G('${missing ?? true}', ('${missing ?? true}',), ('${missing ?? true}',), True, True, frozenset({'missing'}), True),
    G('${missing ?? truthy}', ('${missing ?? truthy}',), ('${missing ?? truthy}',), True, True, frozenset({'missing', 'truthy'}), '${missing ?? truthy}'),
    G('${missing ?? null}', ('${missing ?? null}',), ('${missing ?? null}',), True, True, frozenset({'missing'}), None),
    G('${missing ?? -1.5}', ('${missing ?? -1.5}',), ('${missing ?? -1.5}',), True, True, frozenset({'missing'}), -1.5),
    G('${missing ?? []}', ('${missing ?? []}',), ('${missing ?? []}',), True, True, frozenset({'missing'}), []),
    G('${missing ?? {}}', ('${missing ?? {}}',), ('${missing ?? {}}',), True, True, frozenset({'missing'}), {}),
    G('${0}', ('${0}',), ('${0}',), True, True, frozenset(), 0),
    G('${"v1"}', ('${"v1"}',), ('${"v1"}',), True, True, frozenset(), 'v1'),
    G('${null}', ('${null}',), ('${null}',), True, True, frozenset(), None),
    G('${true}', ('${true}',), ('${true}',), True, True, frozenset(), True),
    G('${-0}', ('${-0}',), ('${-0}',), True, True, frozenset(), 0),
    G('${1.}', (), (), False, False, frozenset(), '${1.}'),
    G('${missing}', ('${missing}',), ('${missing}',), True, True, frozenset({'missing'}), '${missing}'),
    G('hi ${missing}', ('${missing}',), ('${missing}',), True, False, frozenset({'missing'}), 'hi ${missing}'),
    G('${missing ?? b}', ('${missing ?? b}',), ('${missing ?? b}',), True, True, frozenset({'b', 'missing'}), 'fb'),
    G('${missing.f ?? missing2 ?? b}', ('${missing.f ?? missing2 ?? b}',), ('${missing.f ?? missing2 ?? b}',), True, True, frozenset({'b', 'missing.f', 'missing2'}), 'fb'),
    G('${x} $${x}', ('${x}',), ('${x}',), True, False, frozenset({'x'}), 'hi ${x}'),
    G('${a[${missing}].x}', ('${a[${missing}].x}',), ('${a[${missing}].x}',), True, True, frozenset({'a[${missing}].x'}), '${a[${missing}].x}',
      why='delta 3'),
    G('${arr[${idx ?? 0}]}', ('${idx ?? 0}',), (), False, False, frozenset(), '${arr[${idx ?? 0}]}',
      why='delta 2: a `??` inner index is an Issue (static, verbatim)'),
    G('${x??b}', ('${x??b}',), ('${x??b}',), True, True, frozenset({'b', 'x'}), 'hi'),
    G('${ x ?? b }', (), (), False, False, frozenset(), '${ x ?? b }'),
    # Rows the table grew while measuring (not in the first probe list).
    G('${x} ${missing} ${x}', ('${x}', '${missing}', '${x}'), ('${x}', '${missing}', '${x}'), True, False,
      frozenset({'x', 'missing'}), 'hi ${missing} hi'),
)
# fmt: on


def _items() -> list[Any]:
    items: list[Any] = []
    for row in GRAMMAR_ROWS:
        items.append(pytest.param(row, id=f"{row.template!r}-today"))
        if row.flips_in is not None:
            items.append(
                pytest.param(
                    row.flipped(),
                    id=f"{row.template!r}-after-{row.flips_in}",
                    marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=f"{row.flips_in}: {row.why}"),
                )
            )
    return items


@pytest.mark.parametrize("row", _items())
def test_grammar_row(row: G) -> None:
    assert_row(row)


def test_grammar_table_size_and_uniqueness() -> None:
    templates = [row.template for row in GRAMMAR_ROWS]
    assert len(templates) == len(set(templates))
    assert len(templates) == 76
    # All 17 pending rows flipped in 4a (their `today` items deleted).
    assert sum(row.flips_in is not None for row in GRAMMAR_ROWS) == 0


_OPEN = re.compile(r"(?<!\$)\$\{")
_ESCAPE = re.compile(r"\$\$\{(?:[^{}]|\{[^{}]*\})*\}|\$\$\{")


def _unescape(gap: str) -> str:
    return _ESCAPE.sub(lambda m: m.group(0)[1:], gap)


def test_parse_covers_every_open_and_reassembles_losslessly() -> None:
    """Every unescaped ``${`` that survives escape consumption lies in exactly one
    Expression/Issue span, every span starts at one, and the source is the spans
    plus the Text segments (re-escaped gaps) — nothing lost, nothing invented.

    The surviving openings are counted independently of the tokenizer: blank out
    every escape match (left to right) and find the ``${`` left.
    """
    covered = 0
    for row in GRAMMAR_ROWS:
        source = row.template
        template = parse(source)
        tokens = [seg for seg in template.segments if isinstance(seg, (Expression, Issue))]
        spans = [tok.span for tok in tokens]
        assert all(a[1] <= b[0] for a, b in itertools.pairwise(spans)), source  # ordered, disjoint
        blanked = _ESCAPE.sub(lambda m: " " * len(m.group(0)), source)
        opens = [m.start() for m in _OPEN.finditer(blanked)]
        assert all(any(start <= at < end for start, end in spans) for at in opens), source
        assert all(start in opens for start, _ in spans), source
        # Reassembly: the gaps between spans, unescaped, are exactly the Text segments.
        edges = [0, *(x for span in spans for x in span), len(source)]
        gaps = [_unescape(source[edges[i] : edges[i + 1]]) for i in range(0, len(edges), 2)]
        texts = [seg.text for seg in template.segments if isinstance(seg, Text)]
        assert [g for g in gaps if g] == texts, source
        for tok in tokens:
            expected = f"${{{tok.raw}}}" if isinstance(tok, Expression) else tok.raw
            assert source[tok.span[0] : tok.span[1]] == expected, source
        covered += len(opens)
    assert covered == 82


# ---------------------------------------------------------------------------
# Literal grammar: every full match must round-trip `try_parse_json`
# ---------------------------------------------------------------------------

LITERALS_OK: tuple[str, ...] = (
    '"x"',
    '"a?b"',
    '""',
    r'"\\"',
    r'"\"q"',
    "true",
    "false",
    "null",
    "0",
    "-0",
    "7",
    "-1.5",
    "10.25",
    "[]",
    "{}",
    r'"\u00e9"',
    r'"\n"',
)
LITERALS_REJECTED: tuple[str, ...] = ("007", "01", "[1,2]", '{"a":1}', '"a??b"', "1.", "truthy", '"unterminated')
# Look like literals but are not JSON: the grammar rejects them (tightened in 4a).
LITERALS_BAD_JSON: tuple[str, ...] = (r'"\q"', r'"\u12"', '"a\tb"')


def _is_literal(text: str) -> bool:
    """Whether ``${text}`` parses as one Literal operand (the literal grammar, through ``parse``)."""
    template = parse("${" + text + "}")
    return template.is_simple and isinstance(template.expressions[0].operands[0], Literal)


def test_literal_grammar_matches_round_trip_json() -> None:
    matched = [text for text in LITERALS_OK if _is_literal(text)]
    assert matched == list(LITERALS_OK)
    assert all(try_parse_json(text)[0] for text in matched), [t for t in matched if not try_parse_json(t)[0]]
    assert len(matched) == 17


def test_literal_grammar_rejects_non_literals() -> None:
    assert [text for text in LITERALS_REJECTED + LITERALS_BAD_JSON if _is_literal(text)] == []
    assert not any(try_parse_json(text)[0] for text in LITERALS_BAD_JSON)


# ---------------------------------------------------------------------------
# 1f. Walk pair: `variable_exists` / `resolve_value` vs the template reader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class W:
    path: str
    context: Mapping[str, Any]
    exists: bool
    value: Any
    # ``resolve_template("${path}")``; ``None`` when the grammar rejects the path.
    template_value: Any


_UNCHANGED = object()  # the template reader returned its input unchanged

WALK_ROWS: tuple[W, ...] = (
    W("x[0]", {"x": [None]}, True, None, None),
    W("x.k", {"x": {"k": None}}, True, None, None),
    W("x.k.j", {"x": {"k": '{"j": 1}'}}, True, 1, 1),
    W("x.k.j", {"x": {"k": None}}, False, None, _UNCHANGED),
    W("x.k[0]", {"x": {"k": "s"}}, False, None, _UNCHANGED),
    W("x.k[0].z", {"x": {"k": [None]}}, False, None, _UNCHANGED),
    W("x.k[0]", {"x": {"k": "[5]"}}, True, 5, 5),
    W("x[0]", {"x": "[5]"}, True, 5, 5),
    W("x.k", {"x": {"k": "12345678901234567890"}}, True, "12345678901234567890", "12345678901234567890"),
    W("x[1]", {"x": [0]}, False, None, _UNCHANGED),
    W("x", {"x": None}, True, None, None),
    W("x", {}, False, None, _UNCHANGED),
)


@pytest.mark.parametrize("row", WALK_ROWS, ids=lambda r: f"{r.path}@{dict(r.context)}")
def test_walk_pair(row: W) -> None:
    context = dict(row.context)
    assert TemplateResolver.variable_exists(row.path, context) is row.exists
    assert _same(TemplateResolver.resolve_value(row.path, context), row.value)
    # Found <=> reached a value (possibly None): the two raw readers never disagree.
    if not row.exists:
        assert TemplateResolver.resolve_value(row.path, context) is None


@pytest.mark.parametrize("row", WALK_ROWS, ids=lambda r: f"{r.path}@{dict(r.context)}")
def test_walk_pair_agrees_with_template_reader(row: W) -> None:
    template = "${" + row.path + "}"
    resolved = TemplateResolver.resolve_template(template, dict(row.context))
    expected = template if row.template_value is _UNCHANGED else row.template_value
    assert _same(resolved, expected)
    assert (resolved != template) is row.exists


def test_raw_reader_cannot_walk_a_dynamic_index() -> None:
    """Why ``loop_control`` migrates with the facade in 4a: the raw reader is lexical."""
    context = {"n": {"items": [7]}, "idx": 0}
    assert TemplateResolver.variable_exists("n.items[${idx}]", context) is False
    assert TemplateResolver.resolve_template("${n.items[${idx}]}", context) == 7


def test_coalesce_over_array_none_returns_none() -> None:
    """A found ``None`` ends a ``??`` chain (array variant of test_template_coalesce.py:299)."""
    assert TemplateResolver.resolve_template('${x[0] ?? "f"}', {"x": [None]}) is None
    assert TemplateResolver.resolve_template('${x[1] ?? "f"}', {"x": [None]}) == "f"
