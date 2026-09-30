"""The ``${…}`` template language: one parse, one path walk, one resolution.

``parse(source)`` turns author text into an immutable ``Template`` of ``Text``,
``Expression`` and ``Issue`` segments. Every unescaped ``${`` is an Expression
or an Issue, never Text. ``resolve()`` walks a value against a context and
returns a ``Resolution``: the value plus what stayed literal. It is the single
judge of "unresolved" for every runtime consumer.

``parse`` is cached, so it runs on AUTHOR TEXT only. ``has_templates`` /
``has_references`` are uncached scans, the only helpers that may run on resolved
runtime values. Never decide unresolved-ness by re-scanning resolved text; read
the ``Resolution`` channels (#630).

Lives in ``core/`` so the validator and the runtime share one module; it imports
only ``pflow.core`` (pinned by ``tests/test_core/test_templates_module.py``).
"""

from __future__ import annotations

import functools
import json
import logging
import re
import typing
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from pflow.core.json_utils import try_parse_json

logger = logging.getLogger(__name__)


# ── Rules ────────────────────────────────────────────────────────────────────

CONTAINER_TYPES = frozenset({"dict", "object", "list", "array"})  # JSON auto-parse targets
LIST_TYPES = frozenset({"list", "array"})  # index access targets


# ── Grammar (regex strings; the tokenizer and the public patterns share them) ──

_IDENT = r"[a-zA-Z_][\w-]*"
# A static reference path: `a`, `a.b`, `a[0].b[1]` — one index per segment. It is
# also the grammar of a dynamic index's inner reference (one level, no `??`).
_VAR_NAME_PATTERN = rf"{_IDENT}(?:(?:\[\d+\])?(?:\.{_IDENT}(?:\[\d+\])?)*)?"
# One path segment: a name with at most one index, `[N]` or `[${static ref}]`.
_SEGMENT = rf"{_IDENT}(?:\[(?:\d+|\$\{{{_VAR_NAME_PATTERN}\}})\])?"
_PATH = rf"{_SEGMENT}(?:\.{_SEGMENT})*"

# Literal operand grammar: JSON values that `json.loads` accepts and the `??`
# splitter cannot shred — double-quoted strings with JSON escapes only (no raw
# control characters, no `??` inside), word-bounded true/false/null, numbers
# without leading zeros, and the empty `[]` / `{}`. Composite literals are out:
# complex defaults belong in a code node.
_LITERAL_PATTERN = (
    r'(?:"(?:[^"\\?\x00-\x1f]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4}|\?(?!\?))*"'
    r"|\btrue\b|\bfalse\b|\bnull\b|-?(?:0|[1-9]\d*)(?:\.\d+)?|\[\]|\{\})"
)
# Literal first: keyword literals win over same-spelled identifiers.
_OPERAND = rf"(?:{_LITERAL_PATTERN}|{_PATH})"
_EXPRESSION = rf"{_OPERAND}(?:\s*\?\?\s*{_OPERAND})*"

_EXPRESSION_AT = re.compile(rf"\$\{{({_EXPRESSION})\}}")
_LITERAL_FULL = re.compile(_LITERAL_PATTERN)
_PATH_FULL = re.compile(_PATH)
_SEGMENT_AT = re.compile(rf"({_IDENT})(?:\[(?:(\d+)|\$\{{({_VAR_NAME_PATTERN})\}})\])?")
_COALESCE_SPLIT = re.compile(r"\s*\?\?\s*")
# One left-to-right scan: an escape `$${…}` (brace-balanced body, one nesting
# level; without a balanced close only `$${` is consumed) or an unescaped `${`.
_SCAN = re.compile(r"(?P<escape>\$\$\{(?:[^{}]|\{[^{}]*\})*\}|\$\$\{)|(?<!\$)\$\{")


# ── AST (frozen, slotted, tuples never lists) ────────────────────────────────


@dataclass(frozen=True, slots=True)
class Text:
    text: str  # unescaped literal text (`$${` already `${`)


@dataclass(frozen=True, slots=True)
class Field:
    name: str


@dataclass(frozen=True, slots=True)
class Index:
    value: int


@dataclass(frozen=True, slots=True)
class DynamicIndex:
    ref: Reference  # a plain static Reference: no `??`, no nesting


Segment = Field | Index | DynamicIndex


@dataclass(frozen=True, slots=True)
class Reference:
    root: str
    path: tuple[Segment, ...]
    raw: str  # the operand's source text

    @property
    def references(self) -> tuple[Reference, ...]:
        """This reference, then its dynamic-index inner references."""
        return (self, *(seg.ref for seg in self.path if isinstance(seg, DynamicIndex)))

    def first_field(self) -> tuple[int, str] | None:
        """``(offset in raw of the "." before it, name)`` of the first field after the
        root — past a root index (``a[${i.j}].x`` → ``(9, "x")``); ``None`` if none."""
        offset = len(self.root)
        for seg in self.path:
            if isinstance(seg, Field):
                return offset, seg.name
            offset += len(f"[{seg.value}]" if isinstance(seg, Index) else f"[${{{seg.ref.raw}}}]")
        return None


@dataclass(frozen=True, slots=True)
class Literal:
    raw: str  # a JSON literal per the literal grammar

    @property
    def value(self) -> Any:
        # Computed fresh on every access: a cached `[]` / `{}` would be shared
        # across resolutions (and batch threads) through the parse cache.
        return json.loads(self.raw)


Operand = Reference | Literal


@dataclass(frozen=True, slots=True)
class Expression:
    operands: tuple[Operand, ...]  # more than one ⇔ coalesce
    raw: str  # the text inside `${…}`
    span: tuple[int, int]  # [start of `${`, end after `}`)

    @property
    def references(self) -> tuple[Reference, ...]:
        """Every Reference, dynamic-index inner ones included: the DEPENDENCY view."""
        return tuple(ref for op in self.operands if isinstance(op, Reference) for ref in op.references)


IssueKind = typing.Literal["malformed", "bad_literal"]


@dataclass(frozen=True, slots=True)
class Issue:
    """An unescaped ``${`` that opens no Expression, through its first ``}`` (or EOS)."""

    raw: str
    span: tuple[int, int]
    kind: IssueKind


@dataclass(frozen=True, slots=True)
class Template:
    source: str
    segments: tuple[Text | Expression | Issue, ...]
    escaped: bool  # a `$${` escape was consumed

    @property
    def expressions(self) -> tuple[Expression, ...]:
        return tuple(seg for seg in self.segments if isinstance(seg, Expression))

    @property
    def issues(self) -> tuple[Issue, ...]:
        return tuple(seg for seg in self.segments if isinstance(seg, Issue))

    @property
    def references(self) -> tuple[Reference, ...]:
        return tuple(ref for expr in self.expressions for ref in expr.references)

    @property
    def is_simple(self) -> bool:
        """The whole source is one Expression: resolution preserves its value's type."""
        return len(self.segments) == 1 and isinstance(self.segments[0], Expression)

    @property
    def needs_resolution(self) -> bool:
        return self.escaped or any(isinstance(seg, Expression) for seg in self.segments)


# ── Parse ────────────────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=4096)
def parse(source: str) -> Template:
    """Parse author template text. Pure, total (never raises), context-free."""
    return _tokenize(source)


def parse_path(path: str) -> Reference | None:
    """The bare path grammar (``node.f[0].g``, ``a[${i}].x``); ``None`` if invalid."""
    if not _PATH_FULL.fullmatch(path):
        return None
    segments: list[Segment] = []
    pos = 0
    while pos < len(path):
        match = _SEGMENT_AT.match(path, pos)
        if match is None:  # pragma: no cover — unreachable after the fullmatch
            return None
        name, index, inner = match.groups()
        segments.append(Field(name))
        if index is not None:
            segments.append(Index(int(index)))
        elif inner is not None:
            inner_ref = parse_path(inner)
            if inner_ref is None:  # pragma: no cover — the inner grammar is a subset
                return None
            segments.append(DynamicIndex(inner_ref))
        pos = match.end() + 1  # skip the `.` separator
    root = segments[0]
    assert isinstance(root, Field)  # noqa: S101 — the path grammar starts with a name
    return Reference(root.name, tuple(segments[1:]), path)


def _tokenize(source: str) -> Template:
    segments: list[Text | Expression | Issue] = []
    text: list[str] = []
    escaped = False
    pos = 0
    while (match := _SCAN.search(source, pos)) is not None:
        start = match.start()
        text.append(source[pos:start])
        if match.group("escape"):
            text.append(match.group(0)[1:])
            escaped = True
            pos = match.end()
            continue
        if text_so_far := "".join(text):
            segments.append(Text(text_so_far))
        text = []
        token = _expression_at(source, start) or _issue_at(source, start)
        segments.append(token)
        pos = token.span[1]
    text.append(source[pos:])
    if tail := "".join(text):
        segments.append(Text(tail))
    return Template(source, tuple(segments), escaped)


def _expression_at(source: str, start: int) -> Expression | None:
    match = _EXPRESSION_AT.match(source, start)
    if match is None:
        return None
    operands: list[Operand] = []
    for operand in _COALESCE_SPLIT.split(match.group(1)):
        if _LITERAL_FULL.fullmatch(operand):
            operands.append(Literal(operand))
        elif (ref := parse_path(operand)) is not None:
            operands.append(ref)
        else:  # pragma: no cover — the expression grammar admits only these two
            return None
    return Expression(tuple(operands), match.group(1), match.span())


def _issue_at(source: str, start: int) -> Issue:
    close = source.find("}", start)
    end = len(source) if close == -1 else close + 1
    raw = source[start:end]
    inner = raw[2:-1] if raw.endswith("}") else raw[2:]
    bad_literal = "??" in inner and any(
        _looks_like_literal(op) and not _LITERAL_FULL.fullmatch(op) for op in _COALESCE_SPLIT.split(inner.strip())
    )
    return Issue(raw, (start, end), "bad_literal" if bad_literal else "malformed")


def _looks_like_literal(operand: str) -> bool:
    """A coarse first-char check: ``{ [ " -`` or a digit, or exactly true/false/null."""
    return bool(operand) and (operand[0] in '{["-0123456789' or operand in ("true", "false", "null"))


# ── Walk ─────────────────────────────────────────────────────────────────────

_MISS: tuple[bool, Any] = (False, None)


def _json_container(value: Any) -> Any:
    """A JSON-object/array string parsed for traversal; anything else unchanged.

    Primitives are NOT parsed, so numeric strings like Discord snowflake IDs
    ("1458059302022549698") stay strings.
    """
    if not isinstance(value, str):
        return value
    success, parsed = try_parse_json(value)
    if success and isinstance(parsed, (dict, list)):
        logger.debug(f"Auto-parsed JSON string for path traversal: {type(parsed).__name__}")
        return parsed
    return value


def _get_key(value: Any, key: str) -> tuple[bool, Any]:
    """``(found, value[key])`` for any ``Mapping`` (``NamespacedSharedStore`` and
    ``MappingProxyType`` included), auto-parsing a JSON-object string first."""
    if isinstance(value, Mapping) and key in value:
        return True, value[key]
    if isinstance(value, str):
        parsed = _json_container(value)
        if isinstance(parsed, Mapping) and key in parsed:
            return True, parsed[key]
    return _MISS


def lookup(ref: Reference, context: Mapping[str, Any]) -> tuple[bool, Any]:
    """Walk ``ref`` through ``context``: ``(found, value)``; see ``_walk``."""
    return _walk(ref.root, ref.path, context)


def _walk(root: str, path: Iterable[Segment], context: Mapping[str, Any]) -> tuple[bool, Any]:
    """The one path walk.

    Found means the walk reached a value — possibly ``None`` (a found ``None`` is
    not "missing"). A name reads a Mapping, auto-parsing a JSON-container string
    first; an index needs a list (a JSON-array string is parsed first) and
    ``0 <= N < len``. A dynamic index must resolve to an ``int`` (``bool``
    excluded). Anything else — including walking on through ``None`` — is a miss.
    """
    found, current = _get_key(context, root)
    if not found:
        return _MISS
    for segment in path:
        match segment:
            case Field(name):
                found, current = _get_key(current, name)
                if not found:
                    return _MISS
                continue
            case Index(value):
                index: int | None = value
            case DynamicIndex(inner):
                index = _dynamic_index(inner, context)
        current = _json_container(current)
        if index is None or not isinstance(current, list) or not 0 <= index < len(current):
            return _MISS
        current = current[index]
    return True, current


def _dynamic_index(inner: Reference, context: Mapping[str, Any]) -> int | None:
    found, value = lookup(inner, context)
    if not found:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        # Kept loud: under `??` a bad index would otherwise fall through invisibly.
        logger.warning(
            f"Nested index must be integer, got {type(value).__name__}",
            extra={"template": inner.raw, "inner_value": value},
        )
        return None
    return int(value)


def _evaluate(expression: Expression, context: Mapping[str, Any]) -> tuple[bool, Any]:
    """The first operand that resolves: a Literal always does; a Reference iff found.

    ``??`` falls through whenever the left side "isn't there" — the node did not
    run OR the field is missing (#441, like ``??`` in JS/C#). A found ``None`` ends
    the chain. (Declared outputs use a stricter all-absent rule in
    ``output_resolver._is_all_absent_coalesce``.)
    """
    for operand in expression.operands:
        if isinstance(operand, Literal):
            return True, operand.value
        found, value = lookup(operand, context)
        if found:
            return True, value
    return _MISS


# Raw-path lexer for USER-TYPED paths (`-o result.@type`, `read-fields result.dc:title`):
# split on dots outside brackets, then peel a trailing `[N][M]…` chain off each part.
# No identifier grammar — the path walks as written.
_RAW_DOT_SPLIT = re.compile(r"\.(?![^\[]*\])")
_RAW_INDEXED_PART = re.compile(r"^([^[]+)((?:\[\d+\])+)$")


def _split_raw_path(path: str) -> tuple[str, tuple[Segment, ...]]:
    """``"a.b[1][2].c"`` → ``("a", (Field("b"), Index(1), Index(2), Field("c")))``."""
    segments: list[Segment] = []
    for part in _RAW_DOT_SPLIT.split(path):
        match = _RAW_INDEXED_PART.match(part)
        if match:
            segments.append(Field(match.group(1)))
            segments.extend(Index(int(i)) for i in re.findall(r"\d+", match.group(2)))
        else:
            segments.append(Field(part))
    root = segments[0]
    assert isinstance(root, Field)  # noqa: S101 — every raw part starts with a key
    return root.name, tuple(segments[1:])


# ── Resolution ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Resolution:
    """A resolved value plus what resolution had to leave literal.

    ``unresolved`` holds ``Expression.raw`` of every expression left literal;
    ``issues`` holds ``Issue.raw`` of every Issue routed through resolution (kept
    verbatim). Both span the whole value. Text that came FROM a resolved value is
    never in either — only the author's template is judged (#630). The channels
    stay distinct so a surface can tolerate Issues without tolerating misses (#621).
    """

    value: Any
    unresolved: frozenset[str] = frozenset()
    issues: frozenset[str] = frozenset()

    @property
    def ok(self) -> bool:
        return not self.unresolved and not self.issues

    @staticmethod
    def combine(value: Any, parts: Iterable[Resolution]) -> Resolution:
        """``value`` carrying the union of ``parts``' channels (a container's resolution)."""
        parts = tuple(parts)
        return Resolution(
            value,
            unresolved=frozenset().union(*(p.unresolved for p in parts)),
            issues=frozenset().union(*(p.issues for p in parts)),
        )


def resolve(value: Any, context: Mapping[str, Any], *, auto_parse: bool = False) -> Resolution:
    """Resolve every template in ``value`` against ``context``.

    A string: a simple template yields its value, type preserved; otherwise one
    left-to-right pass — Text as written (unescaped), each Expression stringified
    or left as its raw ``${…}``, each Issue verbatim; substituted values are never
    re-scanned. No top-level JSON auto-parse. Dicts and lists recurse, keys
    untouched. ``auto_parse=True`` adds ``resolve_nested``'s leaf rule at every
    string leaf, the top-level one included: a simple template's resolved
    JSON-container string is parsed. Other values pass through unchanged.
    """
    if isinstance(value, str):
        if "${" not in value:
            return Resolution(value)
        return _resolve_string(parse(value), context, auto_parse)
    if isinstance(value, dict):
        entries = {key: resolve(item, context, auto_parse=auto_parse) for key, item in value.items()}
        return Resolution.combine({key: r.value for key, r in entries.items()}, entries.values())
    if isinstance(value, list):
        items = [resolve(item, context, auto_parse=auto_parse) for item in value]
        return Resolution.combine([r.value for r in items], items)
    return Resolution(value)


def _resolve_string(template: Template, context: Mapping[str, Any], auto_parse: bool) -> Resolution:
    if template.is_simple:
        expression = template.expressions[0]
        found, value = _evaluate(expression, context)
        if not found:
            logger.debug(f"Template '{template.source}' could not be resolved", extra={"var_name": expression.raw})
            return Resolution(template.source, unresolved=frozenset({expression.raw}))
        # resolve_nested's leaf rule; numeric strings stay strings (Discord snowflake IDs).
        if auto_parse and isinstance(value, str):
            success, parsed = try_parse_json(value)
            if success and isinstance(parsed, (dict, list)):
                return Resolution(parsed)
        return Resolution(value)

    parts: list[str] = []
    unresolved: set[str] = set()
    for segment in template.segments:
        match segment:
            case Text(text):
                parts.append(text)
            case Issue(raw):
                parts.append(raw)
            case Expression():
                found, value = _evaluate(segment, context)
                if found:
                    parts.append(_to_string(value))
                else:
                    unresolved.add(segment.raw)
                    _log_unresolved_inline(segment.raw)
                    parts.append(template.source[segment.span[0] : segment.span[1]])
    return Resolution(
        "".join(parts), unresolved=frozenset(unresolved), issues=frozenset(i.raw for i in template.issues)
    )


def _to_string(value: Any) -> str:
    """Stringify for complex interpolation.

    ``None``/``""`` → ``""``; ``False``/``True`` → ``"False"``/``"True"``;
    ``0`` → ``"0"``; ``[]``/``{}`` → ``"[]"``/``"{}"``; dict/list → JSON (not
    Python repr); everything else → ``str(value)``.
    """
    if value is None or value == "":
        return ""
    # Check for boolean BEFORE checking for 0 (since False == 0 in Python)
    elif value is False:
        return "False"
    elif value is True:
        return "True"
    elif value == 0:
        return "0"
    elif value == []:
        return "[]"
    elif value == {}:
        return "{}"
    elif isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    else:
        return str(value)


def _log_unresolved_inline(var_expr: str) -> None:
    if ".response." in var_expr:
        logger.warning(
            f"Template variable '${{{var_expr}}}' could not be resolved. "
            f"This often indicates the LLM node didn't generate the expected JSON structure. "
            f"Check that the LLM response contains the field '{var_expr.split('.')[-1]}'"
        )
    else:
        logger.debug(f"Template variable '${{{var_expr}}}' could not be resolved", extra={"var_name": var_expr})


def _strings(value: Any) -> Iterator[str]:
    """Every string in ``value``, recursing into dicts (values) and lists."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


# ── The string-helper facade (the permanent interface of the long tail) ──────


class TemplateResolver:
    """String-in/string-out helpers over ``parse`` / ``resolve`` / the walk."""

    # Kept by name: composed by symbol in `template_validation/validator.py`,
    # `data_flow.py`, `cache_overlap.py`, `graph/scope.py` until they consume `parse()`.
    _VAR_NAME_PATTERN = _VAR_NAME_PATTERN
    _LITERAL_PATTERN = _LITERAL_PATTERN

    # Static-discovery views built from the tokenizer's grammar (dynamic index
    # included). They cannot see escape CONSUMPTION (`$${a[${i}]}` still shows
    # `${i}`), so discovery over text that may hold escapes uses ``parse()``.
    TEMPLATE_PATTERN = re.compile(rf"(?<!\$)\$\{{({_EXPRESSION})\}}")
    SIMPLE_TEMPLATE_PATTERN = re.compile(rf"^\$\{{({_EXPRESSION})\}}$")

    # Loose extraction for validation/diagnostics discovery: everything between an
    # unescaped `${` and the next `}`. Does NOT validate the grammar.
    TEMPLATE_EXTRACT_PATTERN = re.compile(r"(?<!\$)\$\{([^}]+)\}")

    _COALESCE_SPLIT_PATTERN = _COALESCE_SPLIT
    # Root variable name: everything before the first `.` or `[`.
    _ROOT_SPLIT_PATTERN = re.compile(r"[\.\[]")

    @staticmethod
    def has_templates(value: Any) -> bool:
        """Whether resolution rewrites ``value``: an Expression or a ``$${`` escape
        anywhere (an escape-only value still resolves to its literal ``${…}``;
        an Issue-only value is static). Uncached — safe on resolved values."""
        return any("${" in s and _tokenize(s).needs_resolution for s in _strings(value))

    @staticmethod
    def has_references(value: Any) -> bool:
        """Whether ``value`` holds an Expression anywhere (escape-only → False).
        Uncached — safe on resolved values."""
        return any("${" in s and bool(_tokenize(s).expressions) for s in _strings(value))

    @staticmethod
    def extract_variables(value: str) -> set[str]:
        """The value-position References of every Expression, by source text.

        ``${a ?? b}`` → ``{"a", "b"}``; literal operands are values, not
        dependencies; ``${a[${i}].x}`` → ``{"a[${i}].x"}`` (the inner ``i`` is an
        index key, not a value — see ``Expression.references`` for dependencies).
        """
        return {op.raw for expr in parse(value).expressions for op in expr.operands if isinstance(op, Reference)}

    @staticmethod
    def is_simple_template(value: str) -> bool:
        """Whether the whole string is one Expression (its value's type is preserved).

        Examples:
            >>> TemplateResolver.is_simple_template("${data.field}")
            True
            >>> TemplateResolver.is_simple_template("Hello ${name}")
            False
        """
        return parse(value).is_simple

    @staticmethod
    def split_coalesce_operands(expr: str) -> list[str]:
        """Split an expression on ``??`` (lexical); one element when there is none."""
        if "??" not in expr:
            return [expr]
        return [op.strip() for op in TemplateResolver._COALESCE_SPLIT_PATTERN.split(expr)]

    @staticmethod
    def is_literal_operand(operand: str) -> bool:
        """Whether an operand LOOKS like a JSON literal (a coarse first-char check).

        Literals start with one of ``{ [ " -`` or a digit, or are exactly
        ``true`` / ``false`` / ``null``; identifiers start with ``[a-zA-Z_]``. It is
        BROADER than the literal grammar (``01``, ``[1,2]`` pass): it classifies an
        operand the grammar already accepted, it does not validate literal shape.

        Examples:
            >>> TemplateResolver.is_literal_operand('"hello"')
            True
            >>> TemplateResolver.is_literal_operand("truthy_value")
            False
        """
        return _looks_like_literal(operand)

    @staticmethod
    def is_coalesce_expression(expr: str) -> bool:
        """Check if a template expression contains the coalesce operator ??."""
        return "??" in expr

    @staticmethod
    def extract_root_node_id(template_path: str) -> str:
        """The root of a path (lexical): ``"node.field[0].sub"`` → ``"node"``, ``"data[0]"`` → ``"data"``."""
        return TemplateResolver._ROOT_SPLIT_PATTERN.split(template_path, maxsplit=1)[0]

    @staticmethod
    def extract_first_field_segment(var: str) -> str | None:
        """The first field segment after the root; ``None`` for a bare root.

        Examples:
            >>> TemplateResolver.extract_first_field_segment("node.field[0].nested")
            'field'
            >>> TemplateResolver.extract_first_field_segment("a[${item.i}].x")
            'x'
            >>> TemplateResolver.extract_first_field_segment("data[0]") is None
            True
        """
        ref = parse_path(var)
        if ref is not None:
            return next((seg.name for seg in ref.path if isinstance(seg, Field)), None)
        # A raw user-typed path (`result.@type`): split lexically.
        parts = var.split(".", 1)
        if len(parts) != 2:
            return None
        return parts[1].split(".", 1)[0].split("[", 1)[0]

    @staticmethod
    def resolve_coalesce(expr: str, context: Mapping[str, Any]) -> tuple[Any, str]:
        """Resolve an expression (the text inside ``${…}``): ``(value, "resolved")``
        from the first operand that resolves, else ``(None, "unresolved")`` —
        also when ``expr`` is not in the expression grammar."""
        expression = _expression_at("${" + expr + "}", 0)
        if expression is not None and expression.raw == expr:
            found, value = _evaluate(expression, context)
            if found:
                return value, "resolved"
        return None, "unresolved"

    @staticmethod
    def extract_simple_template_var(value: str) -> str | None:
        """The expression text of a simple template (``"${a[${i}].x}"`` → ``"a[${i}].x"``), else ``None``.

        Examples:
            >>> TemplateResolver.extract_simple_template_var("${user.name}")
            'user.name'
            >>> TemplateResolver.extract_simple_template_var("Hello ${name}") is None
            True
        """
        template = parse(value)
        return template.expressions[0].raw if template.is_simple else None

    # Kept: the direct-test surface of `test_template_resolver.py`.
    _convert_to_string = staticmethod(_to_string)

    @staticmethod
    def variable_exists(var_name: str, context: Mapping[str, Any]) -> bool:
        """Whether a RAW path reaches a value (``None`` included) — the walk's ``found``."""
        return _walk(*_split_raw_path(var_name), context)[0]

    @staticmethod
    def resolve_value(var_name: str, context: Mapping[str, Any]) -> Any | None:
        """The value at a RAW path, or ``None`` on a miss (``variable_exists`` tells
        a found ``None`` from a miss). ``data.items[0].name`` →
        ``context['data']['items'][0]['name']``."""
        return _walk(*_split_raw_path(var_name), context)[1]

    @staticmethod
    def resolve_template(template: str, context: Mapping[str, Any]) -> Any:
        """``resolve(template, context).value``: a simple template keeps its value's
        type, a complex one is a string, an unresolved expression stays literal,
        each ``$${`` escape becomes ``${``.

        Examples:
            >>> TemplateResolver.resolve_template("${count}", {"count": 42})
            42
            >>> TemplateResolver.resolve_template("Missing: ${undefined}", {})
            'Missing: ${undefined}'
        """
        return resolve(template, context).value

    @staticmethod
    def resolve_nested(value: Any, context: Mapping[str, Any]) -> Any:
        """``resolve(value, context, auto_parse=True).value``: nested dicts/lists
        resolved in place, and a simple template's JSON-container string parsed
        (``{"data": "${shell.stdout}"}`` gets structured data; ``"prefix ${var}"``
        is the escape hatch that keeps the raw string).

        Examples:
            >>> TemplateResolver.resolve_nested({"data": "${s.out}"}, {"s": {"out": '{"a": 1}'}})
            {'data': {'a': 1}}
        """
        return resolve(value, context, auto_parse=True).value
