"""``core/text_format.py``: the count-noun and labelled-value rules, and the ratchet that keeps
renderers from re-deriving them inline (#806)."""

from __future__ import annotations

import ast
from collections import Counter
from itertools import pairwise
from pathlib import Path

import pytest

from pflow.core.text_format import count_noun, labelled_lines


@pytest.mark.parametrize(
    ("count", "noun", "plural", "expected"),
    [
        (1, "node", None, "1 node"),
        (0, "node", None, "0 nodes"),
        (2, "warning", None, "2 warnings"),
        (1, "entry", "entries", "1 entry"),
        (3, "entry", "entries", "3 entries"),
        (1204, "token", None, "1,204 tokens"),
    ],
)
def test_count_noun_agrees_with_its_count(count: int, noun: str, plural: str | None, expected: str) -> None:
    assert count_noun(count, noun, plural) == expected


def test_labelled_lines_hangs_continuation_lines_under_the_value() -> None:
    assert labelled_lines("Command: ", "echo one\n\necho two") == ["Command: echo one", "", "         echo two"]


def test_labelled_lines_single_line_value_is_one_line() -> None:
    assert labelled_lines("code: ", "x = 1\n") == ["code: x = 1"]


# --- Ratchet --------------------------------------------------------------------------------
# Three inline idioms re-derive what text_format.py owns. Each scan reads the AST, so comments and
# docstrings never trip it. A ratchet, not a proof: a hard-coded plural after a count
# (f"{n} nodes") has no reliable syntactic shape — the n=1 render tests at each site pin those.
#
# - plural: a conditional choosing between "s" and "" (`'s' if n != 1 else ''`) → count_noun.
# - indent: `.replace("\n", "\n    ")` / `.replace("\n", "\\n")` on a value → labelled_lines.
# - article: an f-string that writes "a " / "an " straight before an interpolated word guesses
#   the article from spelling ("a http", "a agent") → name the noun without one.

_SRC = Path(__file__).resolve().parents[2] / "src" / "pflow"

# Sites that predate the helpers, outside the run/resume/describe presentation path. The counts
# may only fall: migrate a site, then lower (or drop) its entry.
_GRANDFATHERED: dict[tuple[str, str], int] = {
    ("plural", "core/workflow/data_flow.py"): 2,
    ("plural", "execution/formatters/discovery_formatter.py"): 1,
    ("plural", "execution/formatters/node_output_formatter.py"): 2,
    ("plural", "runtime/compilation/compile_validation.py"): 1,
    ("indent", "nodes/shell/env_binding.py"): 1,
    ("indent", "runtime/engine/error_context.py"): 1,
    ("article", "cli/workflow_output.py"): 1,
    ("article", "nodes/shell/env_binding.py"): 1,
    ("article", "runtime/engine/template_errors.py"): 2,
    ("article", "runtime/template_validation/validator.py"): 1,
}


def _is_str(node: ast.AST, *values: str) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in values


def _idioms(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.IfExp) and (
            (_is_str(node.body, "s") and _is_str(node.orelse, ""))
            or (_is_str(node.body, "") and _is_str(node.orelse, "s"))
        ):
            found.append("plural")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "replace"
            and len(node.args) == 2
            and _is_str(node.args[0], "\n")
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and (
                node.args[1].value == "\\n"
                or (node.args[1].value.startswith("\n") and node.args[1].value[1:].isspace())
            )
        ):
            found.append("indent")
        elif isinstance(node, ast.JoinedStr):
            parts = node.values
            found.extend(
                "article"
                for before, after in pairwise(parts)
                if isinstance(before, ast.Constant)
                and isinstance(before.value, str)
                and before.value.endswith((" a ", "(a ", " an ", "(an "))
                and isinstance(after, ast.FormattedValue)
            )
    return found


def test_no_inline_plural_indent_or_article_idioms() -> None:
    counts: Counter[tuple[str, str]] = Counter()
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        for idiom in _idioms(ast.parse(path.read_text(encoding="utf-8"))):
            counts[(idiom, rel)] += 1
    assert dict(counts) == _GRANDFATHERED, (
        "Use pflow.core.text_format (count_noun / labelled_lines) instead of the inline idiom, or name "
        "the noun without a guessed article. A migrated grandfathered site lowers its count in _GRANDFATHERED."
    )
