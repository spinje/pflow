"""English text rules for human-facing output: a count with its noun, a multi-line value under a label.

Every renderer calls these instead of re-deriving the rule inline — an inline copy is how
"1 nodes" and a multi-line command spilling to column 0 happened (#806).
``tests/test_core/test_text_format.py`` pins the rules and ratchets the inline idioms out of ``src/pflow``.
"""

from __future__ import annotations


def count_noun(count: int, noun: str, plural: str | None = None) -> str:
    """``count`` and its noun in agreement: ``1 node``, ``0 nodes``, ``1,204 tokens``.

    ``plural`` is for a noun that doesn't take a plain ``s`` (``count_noun(n, "entry", "entries")``).
    """
    return f"{count:,} {noun if count == 1 else plural or f'{noun}s'}"


def labelled_lines(label: str, value: str) -> list[str]:
    """``label`` followed by ``value``'s first line, then each further line indented to the value's column.

    A multi-line value keeps its own line breaks and reads as one block under its label, never as
    lines starting at column 0 or as one line with escaped ``\\n``. Blank lines stay empty; trailing
    line breaks are dropped.
    """
    first, *rest = value.rstrip("\n").split("\n")
    pad = " " * len(label)
    return [f"{label}{first}", *(f"{pad}{line}" if line.strip() else "" for line in rest)]
