"""End-to-end CLI/MCP parity tests for output routing (Issue #400 fixes).

The unit tests in ``tests/test_cli/test_workflow_output_handling.py`` exercise
``_handle_text_output`` directly with hand-built shared dicts. This file
runs the same scenarios through ``WorkflowRunner().run()`` so a real batch
node populates ``shared_after``, then routes the result through the CLI's
output handler to verify the compact summary, dotted ``-o``, and dotted
JSON-mode resolution all survive the full pipeline.

Per ``tests/CLAUDE.md`` Pitfall #20: when a feature crosses runner →
formatter → display, at least one test must walk the real pipeline rather
than mocking the boundary.
"""

from __future__ import annotations

from typing import Any

import pytest

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


@pytest.fixture
def batch_shell_workflow_ir() -> dict[str, Any]:
    """Minimal batch shell workflow — 2 echo items, no external dependencies."""
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "echo-items",
                "type": "shell",
                "purpose": "Batch echo two items so the run produces a real batch aggregate.",
                "params": {"command": "echo ${item}"},
                "batch": {
                    "items": ["alpha", "beta"],
                    "error_handling": "continue",
                    "parallel": False,
                },
            },
        ],
        "edges": [],
        "start_node": "echo-items",
    }


def _run_with_only(ir: dict[str, Any], only_node: str) -> dict[str, Any]:
    """Run ``ir`` with ``--only`` targeting ``only_node`` and return ``shared_after``."""
    result = WorkflowRunner().run(ir, {}, RunnerConfig(only_node=only_node))
    assert result.success, f"workflow failed: {[d.message for d in result.diagnostics]}"
    return result.shared_after


def test_only_batch_node_compact_summary_end_to_end(batch_shell_workflow_ir, capsys):
    """Real batch via ``WorkflowRunner``: ``--only`` triggers the compact summary,
    full payload is suppressed, the hint line points at a resolvable ``-o`` path.
    """
    from pflow.cli.workflow_output import _handle_text_output

    shared = _run_with_only(batch_shell_workflow_ir, only_node="echo-items")
    aggregate = shared.get("echo-items")
    assert isinstance(aggregate, dict)
    assert "batch_metadata" in aggregate, (
        "real batch node must produce the batch_metadata marker the compact summary path keys off"
    )
    assert aggregate["count"] == 2
    assert aggregate["success_count"] == 2

    _handle_text_output(shared, output_key=None, workflow_ir=None, verbose=False)
    captured = capsys.readouterr()
    out_lines = captured.out.strip().split("\n")

    assert out_lines[0].startswith("batch echo-items: 2/2 items succeeded"), captured.out
    assert out_lines[1] == "  use `-o echo-items.results` for full payload"
    assert "alpha" not in captured.out
    assert "beta" not in captured.out


def test_dotted_output_key_resolves_end_to_end(batch_shell_workflow_ir, capsys):
    """Real batch via ``WorkflowRunner``: ``-o echo-items.success_count`` resolves
    to the nested integer through the real shared store the engine wrote.
    """
    from pflow.cli.workflow_output import _handle_text_output

    result = WorkflowRunner().run(batch_shell_workflow_ir, {}, RunnerConfig())
    assert result.success
    shared = result.shared_after

    _handle_text_output(shared, output_key="echo-items.success_count", workflow_ir=None, verbose=False)
    captured = capsys.readouterr()
    assert captured.out.strip() == "2"
    assert "Warning" not in captured.err


def test_dotted_output_key_json_mode_end_to_end(batch_shell_workflow_ir):
    """Real batch via ``WorkflowRunner`` → ``_collect_outputs`` JSON path:
    dotted resolution lands the integer in the outputs dict (CLI/MCP parity).
    """
    from pflow.execution.formatters.success_formatter import _collect_outputs

    result = WorkflowRunner().run(batch_shell_workflow_ir, {}, RunnerConfig())
    assert result.success

    outputs = _collect_outputs(result.shared_after, workflow_ir={}, output_key="echo-items.success_count")
    assert outputs == {"echo-items.success_count": 2}


def test_only_batch_node_runtime_empty_items_emits_compact_summary(capsys):
    """The compact summary's ``count == 0`` branch is reachable in real
    workflows — not just defensively in unit tests.

    Pflow's IR validator rejects static ``items: []`` at parse time, so an
    inline-empty batch can't reach runtime. But ``items: ${upstream.list}``
    where ``upstream`` produces ``[]`` at runtime DOES reach
    ``_aggregate_batch_results`` with ``count == 0`` — observed during
    end-to-end verification (probe 27).

    Without this test, the count==0 unit test in
    ``test_workflow_output_handling.py`` could be argued as defensive-only
    (validator blocks all empty batches). Real reachability is what makes
    the ``ran with no items`` wording load-bearing rather than dead code.
    """
    from pflow.cli.workflow_output import _handle_text_output

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "produce-empty",
                "type": "code",
                "purpose": "Emit an empty list so the downstream batch has nothing to do.",
                "params": {"code": "result: list = []"},
            },
            {
                "id": "consume",
                "type": "shell",
                "purpose": "Batch over the runtime-empty upstream list.",
                "params": {"command": "echo ${item}"},
                "batch": {"items": "${produce-empty.result}", "parallel": False},
            },
        ],
        "edges": [{"from": "produce-empty", "to": "consume", "action": "default"}],
        "start_node": "produce-empty",
    }

    result = WorkflowRunner().run(ir, {}, RunnerConfig(only_node="consume"))
    assert result.success, [d.message for d in result.diagnostics]

    aggregate = result.shared_after.get("consume")
    assert isinstance(aggregate, dict)
    assert aggregate["count"] == 0, (
        "runtime-empty batch must reach _aggregate_batch_results with count=0 — "
        "this is the reachability proof for the compact summary's empty branch"
    )
    assert "batch_metadata" in aggregate

    _handle_text_output(result.shared_after, output_key=None, workflow_ir=None, verbose=False)
    captured = capsys.readouterr()
    assert "batch consume: ran with no items" in captured.out
    # The undefined '0/0 succeeded' wording must NOT appear.
    assert "0/0" not in captured.out
