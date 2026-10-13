"""Failed-step stdout/stderr previews keep the head AND the tail (#755).

Tools write the cause last — a traceback's exception line, ``error:`` after progress
noise — so ``head_tail_preview`` is the one window every text preview of a step's
stdout/stderr goes through: the error headline, the ``Shell details`` block, a failed
upstream reference's block, and the engine's upstream-stderr context.
"""

from __future__ import annotations

from typing import Any

import pytest

from pflow.core.diagnostic_render import (
    PREVIEW_HEAD_CHARS,
    PREVIEW_TAIL_CHARS,
    format_diagnostic,
    head_tail_preview,
)
from pflow.core.templates import resolve
from pflow.runtime.engine.template_errors import build_template_error_diagnostic
from pflow.runtime.node_state import FAILURE_CATEGORY_SHELL, mark_node_failed

WINDOW = PREVIEW_HEAD_CHARS + PREVIEW_TAIL_CHARS


@pytest.mark.parametrize("length", [0, 1, WINDOW], ids=["empty", "short", "exactly-the-window"])
def test_text_within_the_window_is_unchanged(length: int) -> None:
    text = "x" * length
    assert head_tail_preview(text) == text


@pytest.mark.parametrize("omitted", [1, 1_234])
def test_longer_text_keeps_exact_head_and_tail_and_names_the_omitted_count(omitted: int) -> None:
    head, middle, tail = "H" * PREVIEW_HEAD_CHARS, "m" * omitted, "T" * PREVIEW_TAIL_CHARS

    assert head_tail_preview(head + middle + tail) == f"{head} … [{omitted:,} chars omitted] … {tail}"


@pytest.mark.parametrize(
    ("head", "tail", "expected"), [(3, 4, "HHH … [2 chars omitted] … TTTT"), (3, 0, "HHH … [6 chars omitted] … ")]
)
def test_a_caller_window_sets_the_head_and_tail(head: int, tail: int, expected: str) -> None:
    assert head_tail_preview("HHHmmTTTT", head=head, tail=tail) == expected


def test_failed_reference_shell_block_shows_the_stderr_tail() -> None:
    """``${build.stdout}`` after ``build`` failed: the block under the reference ends with the cause."""
    stderr = "noise line\n" * 100 + "fatal: CAUSE-AT-TAIL"
    shared: dict[str, Any] = {
        "build": {"stdout": "", "stderr": stderr, "exit_code": 2, "command": "make"},
    }
    mark_node_failed(shared, "build", category=FAILURE_CATEGORY_SHELL, error="Command failed with exit code 2")
    template = "${build.stdout}"
    diagnostic = build_template_error_diagnostic("X", template, shared, resolve(template, shared), node_id="report")

    rendered = format_diagnostic(diagnostic)

    assert "        Stderr: noise line\n" in rendered  # the head stays
    assert "chars omitted]" in rendered
    assert "fatal: CAUSE-AT-TAIL" in rendered  # the tail stays — nothing else in the block carries it
