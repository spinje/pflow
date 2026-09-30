"""Behavioral tests for the screenshot-pflow-web-ui settle seam's pass/fail judgment.

The browser half (``settle``'s evaluate_script) needs a live Chrome; the judgment is the
committed ``settled`` code step, run here through the real code node on the report shapes
the browser half returns (GH #650: a timeout used to come back as a result).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pflow.core.markdown_parser import parse_markdown
from pflow.nodes.python.python_code import PythonCodeNode

SETTLE_WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / "examples/real-workflows/screenshot-pflow-web-ui/shared/open-and-settle.pflow.md"
)

SETTLED_REPORT = {"settled": True, "transform": "translate(10px, 20px) scale(0.7)", "nodes": 7, "waited_ms": 900}
ERROR_PAGE_REPORT = {"settled": False, "transform": "", "nodes": 0, "waited_ms": 8040}
UNFRAMED_REPORT = {"settled": False, "transform": "translate(0px, 0px) scale(1)", "nodes": 7, "waited_ms": 8036}


def run_settled_step(report: dict[str, Any], *, allow_empty: bool | None = None) -> tuple[str, dict[str, Any]]:
    """Run the workflow's ``settled`` step on a settle report; return (action, shared).

    ``allow_empty=None`` uses the workflow's declared default — what every caller that
    doesn't opt in gets.
    """
    ir = parse_markdown(SETTLE_WORKFLOW.read_text(encoding="utf-8")).ir
    if allow_empty is None:
        allow_empty = ir["inputs"]["allow_empty"]["default"]
    step = next(n for n in ir["nodes"] if n["id"] == "settled")
    assert step["params"]["inputs"] == {"report": "${settle.result}", "allow_empty": "${allow_empty}"}
    node = PythonCodeNode()
    node.set_params({"code": step["params"]["code"], "inputs": {"report": report, "allow_empty": allow_empty}})
    shared: dict[str, Any] = {}
    return node.run(shared), shared


def test_settled_report_passes_through() -> None:
    action, shared = run_settled_step(SETTLED_REPORT)

    assert action == "default"
    assert shared["result"] == SETTLED_REPORT


@pytest.mark.parametrize(
    ("report", "seen"),
    [
        (ERROR_PAGE_REPORT, "no canvas on the page"),
        (UNFRAMED_REPORT, "7 nodes rendered, viewport transform 'translate(0px, 0px) scale(1)'"),
    ],
)
def test_timeout_fails_the_run_by_default_naming_what_the_page_showed(report: dict[str, Any], seen: str) -> None:
    action, shared = run_settled_step(report)

    assert action == "error"
    assert "result" not in shared
    assert "canvas did not settle within" in shared["error"]
    assert seen in shared["error"]
    assert "allow_empty=true" in shared["error"]


def test_allow_empty_returns_the_unsettled_report() -> None:
    action, shared = run_settled_step(ERROR_PAGE_REPORT, allow_empty=True)

    assert action == "default"
    assert shared["result"] == ERROR_PAGE_REPORT
