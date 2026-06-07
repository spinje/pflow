#!/usr/bin/env python3
"""Validate the ``## Status`` field of every taskmaster task file.

The task browser (``scripts/tasks``) and the roadmap counts both match a task's
``## Status`` value *exactly* against a fixed set of states. Anything outside
that set is silently dropped: it vanishes from the banner counts and from every
list, so an active task can disappear from the roadmap entirely. (This is how
Tasks 117/133/163 went missing — their Status held prose like ``partially
completed (...)`` or a multi-paragraph decision narrative instead of a keyword.)

This hook makes the vocabulary a hard constraint. A task's Status must be one of:

    not started  ->  in progress  ->  done        (plus: deprecated)

The narrative that used to live in the Status field belongs in the body
(``## Problem``, ``## Decision``, a notes section) — not in the one line the
tooling treats as an enum.

Usage:
    python3 scripts/check_task_status.py [FILE ...]

With no arguments, scans every ``.taskmaster/tasks/task_*/task-*.md``. Pre-commit
passes the staged task files as arguments. Exits non-zero (and prints
``file:line: ...`` for each offender) when any Status is missing or invalid.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# The closed vocabulary. Keep in sync with scripts/tasks (count_tasks /
# list_by_status) — the script's buckets and this validator must agree, or a
# "valid" status could still be dropped from the roadmap.
VALID_STATUSES = ("not started", "in progress", "done", "deprecated")

TASKS_GLOB = ".taskmaster/tasks/task_*/task-*.md"

# The canonical task-definition file is task_<N>/task-<N>.md — the only file
# scripts/tasks ever reads. A dir holds other markdown too (task-review.md,
# task-<N>-spec.md, …); those have no Status and must not be validated. Match
# requires the dir number and file number to be equal.
CANONICAL_TASK_FILE = re.compile(r"task_(\d+)/task-(\d+)\.md$")


def is_canonical_task_file(path: Path) -> bool:
    m = CANONICAL_TASK_FILE.search(path.as_posix())
    return m is not None and m.group(1) == m.group(2)


def find_status(path: Path) -> tuple[str, int, str]:
    """Locate a task file's Status. Returns ``(kind, line_number, value)``.

    Mirrors ``get_section_value`` in scripts/tasks: the value is the first
    non-blank, non-heading line after the ``## Status`` heading, tolerant of a
    blank line between the heading and its value. ``kind`` is one of:

    - ``"value"``   — a Status value was found (``line_number``/``value`` set)
    - ``"empty"``   — a ``## Status`` heading exists but has no value
                      (``line_number`` points at the heading)
    - ``"missing"`` — no ``## Status`` heading at all (``line_number`` is 1)
    """
    heading_lineno = 0
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if line == "## Status":
            heading_lineno = lineno
            continue
        if heading_lineno:
            if not line:
                continue
            if line.startswith("## "):
                return "empty", heading_lineno, ""
            return "value", lineno, line
    if heading_lineno:
        return "empty", heading_lineno, ""
    return "missing", 1, ""


def check_file(path: Path) -> str | None:
    """Return a single-line, actionable error for a bad Status, or None if valid.

    Each line is self-contained (carries the allowed vocabulary and the fix) so
    it is greppable and reads on its own in a CI log.
    """
    allowed = " | ".join(VALID_STATUSES)
    kind, lineno, value = find_status(path)
    if kind == "value":
        if value in VALID_STATUSES:
            return None
        return (
            f"{path}:{lineno}: invalid ## Status {value!r} — "
            f"set it to exactly one of: {allowed} (put any explanation in the task body)"
        )
    if kind == "empty":
        return f"{path}:{lineno}: empty ## Status section — set its value to one of: {allowed}"
    return f"{path}:{lineno}: missing ## Status section — add one with a value of: {allowed}"


def iter_task_files(args: list[str]) -> list[Path]:
    candidates = [Path(a) for a in args] if args else sorted(Path(".").glob(TASKS_GLOB))
    # Validate only canonical task-<N>.md files; silently skip review/spec/etc.
    return [p for p in candidates if is_canonical_task_file(p)]


def main(argv: list[str]) -> int:
    files = iter_task_files(argv)
    errors = [msg for path in files if path.is_file() if (msg := check_file(path))]

    if errors:
        print("\n".join(errors), file=sys.stderr)
        n = len(errors)
        plural = "" if n == 1 else "s"
        print(
            f"\n✗ {n} task file{plural} with an invalid ## Status. "
            "A Status must be a single keyword from the closed set above; any "
            "narrative belongs in the task body. "
            "See scripts/check_task_status.py for the vocabulary and why it is enforced.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
