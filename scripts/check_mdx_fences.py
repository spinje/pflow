#!/usr/bin/env python3
"""Catch MDX render-time bugs that `mint validate` misses.

Mintlify compiles every `.mdx` page to JSX. A `${...}` template that leaks out
of a code block becomes a *live JavaScript expression* — e.g. `${input.text}`
compiles to the JS `input.text`, which throws `ReferenceError: input is not
defined` when the page renders and takes the whole page down.

The usual cause is a fenced example that uses the *same* backtick count as a
code block nested inside it: the nested block's bare ``` closes the outer fence
early, dumping the rest of the example into raw MDX prose. `mint validate` does
not catch this — the compiled JS is syntactically valid, so the build passes;
the error only fires at render, which `validate` never does.

This script flags, per file:
  1. `${` appearing in prose *outside* fenced and inline code — a leaked
     template that will compile to an expression and crash the page.
  2. A fenced code block left unclosed at end of file.

Why only `${` and not every `{`: `${...}` is pflow's workflow-template syntax.
Inside a code block it is harmless literal text; in rendered MDX prose it is
always a leak. A bare `{...}` (e.g. `cols={2}`) is legitimate JSX in MDX, so
flagging all braces would drown the signal in false positives.

Usage:
    python3 scripts/check_mdx_fences.py [FILE ...]

With no arguments, scans every `docs/**/*.mdx`. Pre-commit passes the staged
`.mdx` files as arguments. Exits non-zero (and prints `file:line:col` problems)
when anything is found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# A fence line: any leading whitespace, then >= 3 backticks, then an optional
# info string. CommonMark caps fence indent at 3 spaces, but MDX indents fences
# freely inside JSX components (<CodeGroup>, <Accordion>, <Update>) and Mintlify
# renders them, so we allow any indent. A closing fence uses at least as many
# backticks as its opener and never carries an info string.
FENCE_RE = re.compile(r"^\s*(`{3,})(.*)$")
# Inline code span: a run of backticks, content, then a matching run.
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")


def _blank_inline_code(text: str) -> str:
    """Replace inline `code` spans with equal-length runs of spaces.

    Blanking (rather than deleting) hides any ${...} inside inline code from
    the leak check while keeping the string the same length as the original,
    so a column index found here maps straight back to the source line.
    """
    return INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), text)


def check_text(text: str, path: str) -> list[str]:
    """Return human-readable problem strings for one MDX document."""
    problems: list[str] = []
    lines = text.splitlines()

    # Skip YAML frontmatter: a leading `---` block. Its contents are config,
    # not rendered MDX, so ${...} there (rare) is not a render hazard.
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break

    fence_len: int | None = None  # backtick count of the open fence, else None
    fence_open_line = 0
    for offset, raw in enumerate(lines[start:]):
        lineno = start + offset + 1
        match = FENCE_RE.match(raw)
        if fence_len is None:
            # Outside any code block.
            if match:
                fence_len = len(match.group(1))
                fence_open_line = lineno
                continue
            prose = _blank_inline_code(raw)
            idx = prose.find("${")
            if idx != -1:
                # `prose` is the same length as `raw` (inline code blanked to
                # spaces), so this index is the true column even when an earlier
                # ${...} sits inside inline code on the same line.
                col = idx + 1
                problems.append(
                    f"{path}:{lineno}:{col}: leaked `${{...}}` template in prose — "
                    "this compiles to a live JS expression and crashes the page at "
                    "render (mint validate will NOT catch it). Wrap it in a code "
                    "block; if it is already inside one, give the OUTER fence more "
                    f"backticks than the nested block.\n    {raw.strip()}"
                )
        else:
            # Inside a code block: only a bare fence at least as long as the
            # opener closes it. A fence carrying an info string is content.
            if match and len(match.group(1)) >= fence_len and match.group(2).strip() == "":
                fence_len = None

    if fence_len is not None:
        problems.append(f"{path}:{fence_open_line}:1: code fence opened here is never closed.")

    return problems


def _iter_target_files(argv: list[str]) -> list[Path]:
    if argv:
        return [Path(a) for a in argv]
    docs_dir = Path(__file__).resolve().parent.parent / "docs"
    return sorted(docs_dir.rglob("*.mdx"))


def main(argv: list[str]) -> int:
    problems: list[str] = []
    for path in _iter_target_files(argv):
        if path.suffix != ".mdx" or not path.is_file():
            continue
        problems.extend(check_text(path.read_text(encoding="utf-8"), str(path)))

    if problems:
        print("MDX fence/leak check failed:\n", file=sys.stderr)
        for problem in problems:
            print(problem, file=sys.stderr)
        print(
            f"\n{len(problems)} problem(s) found. See scripts/check_mdx_fences.py for why this matters.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
