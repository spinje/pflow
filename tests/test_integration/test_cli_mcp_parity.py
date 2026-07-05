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

from pflow.execution.result import RunnerConfig, WorkflowStatus
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


def _seed_snapshot(ir: dict[str, Any]) -> None:
    """Run the full workflow and persist its trace so ``--only`` can restore upstream.

    Snapshot ``--only`` (issue #443) reads the most recent full-run trace from
    ``~/.pflow/debug``. ``WorkflowRunner().run`` builds the trace but (unlike the
    CLI) never saves it, so callers persist it explicitly. Requires the test to
    be marked ``trace_files``.
    """
    full = WorkflowRunner().run(ir, {}, RunnerConfig())
    assert full.success, f"seed run failed: {[d.message for d in full.diagnostics]}"
    full.trace.save_to_file()


def _run_with_only(ir: dict[str, Any], only_node: str) -> dict[str, Any]:
    """Run ``ir`` with ``--only`` targeting ``only_node`` and return ``shared_after``."""
    _seed_snapshot(ir)
    result = WorkflowRunner().run(ir, {}, RunnerConfig(only_node=only_node))
    assert result.success, f"workflow failed: {[d.message for d in result.diagnostics]}"
    return result.shared_after


@pytest.mark.trace_files
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

    # Data line on stdout; hint line on stderr (stream-discipline parity).
    assert captured.out.strip().startswith("batch echo-items: 2/2 items succeeded"), captured.out
    assert "use `-o echo-items.results` for full payload" in captured.err, captured.err
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


@pytest.mark.trace_files
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

    # Snapshot --only restores 'produce-empty' (its [] result) from a prior full run.
    _seed_snapshot(ir)
    result = WorkflowRunner().run(ir, {}, RunnerConfig(only_node="consume"))
    assert result.success, [d.message for d in result.diagnostics]
    # An empty-input batch is a legitimate terminal state (drained loop / empty
    # filter), so it must NOT degrade the workflow — it emits a non-degrading
    # INFO advisory instead. Regression guard for the empty-input advisory.
    assert result.status == WorkflowStatus.SUCCESS

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


def test_empty_input_batch_emits_non_degrading_info_advisory():
    """End-to-end: a runtime-empty batch surfaces an INFO advisory in
    ``result.diagnostics`` but NOT in ``result.warnings``, and the workflow
    stays SUCCESS (cross-layer guard per tests/CLAUDE.md #20).

    The advisory rides the ``__warnings__`` channel as a ``Severity.INFO``
    Diagnostic; ``result.warnings`` is WARNING-only, so it must be absent there
    while present in the full ``result.diagnostics`` list.
    """
    from pflow.core.diagnostic import Severity

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

    result = WorkflowRunner().run(ir, {}, RunnerConfig())

    assert result.success
    assert result.status == WorkflowStatus.SUCCESS
    # No WARNING-severity diagnostics (the advisory is INFO).
    assert result.warnings == []
    # The INFO advisory IS present in the full diagnostics list.
    advisories = [
        d
        for d in result.diagnostics
        if d.severity == Severity.INFO and d.node_id == "consume" and "0 items" in d.message
    ]
    assert len(advisories) == 1, [(d.severity, d.message) for d in result.diagnostics]


# ---------------------------------------------------------------------------
# Task 125/171: MCP is the production non-TTY gate surface (split-session braindump).
# Parity contract: a gated workflow through ExecutionService now pauses DURABLY
# (Task 171) — the response carries the resume token + gate content instead of a
# raised error — and `auto_approve` pre-approves per-node exactly like
# `--auto-approve`, including when the engine runs off the main thread
# (asyncio.to_thread, the real MCP tool bridge), which pins the no-thread-guard
# design (a main-thread check would break MCP here).
# ---------------------------------------------------------------------------


def _gated_ir() -> dict[str, Any]:
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "make-value",
                "type": "shell",
                "purpose": "Produce a value first.",
                "params": {"command": "echo hello"},
            },
            {
                "id": "guarded-step",
                "type": "shell",
                "purpose": "Side-effecting step behind an approval gate.",
                "params": {"command": "echo posting-${make-value.stdout}"},
                "approval": "required",
            },
        ],
        "edges": [{"from": "make-value", "to": "guarded-step"}],
        "start_node": "make-value",
    }


def test_mcp_gated_workflow_pauses_by_path_but_fails_inline(tmp_path):
    """Task 171 (+ owner decision 2026-07-05, option a): a FILE-based MCP gated
    run pauses durably with a token; the SAME workflow submitted INLINE (dict IR
    — workflow_path is the synthesized ir-hash, no source file to re-resolve)
    keeps the remediation-ladder hard error, whose text names the inline cause.
    Pause is a promise: resume would ALWAYS refuse an inline token, so none is
    issued (the follow-up — workflow content in the trace — flips this pin)."""
    from pflow.mcp_server.services.execution_service import ExecutionService
    from tests.shared.markdown_utils import write_workflow_file

    wf = tmp_path / "gated_parity.pflow.md"
    write_workflow_file(_gated_ir(), wf)
    text = ExecutionService.execute_workflow(str(wf), {})
    assert "status: paused" in text
    assert "paused_node_id: guarded-step" in text
    assert "resume_command: pflow resume" in text
    # The gate content is self-contained (resolved preview, not the template).
    assert "posting-hello" in text

    with pytest.raises(RuntimeError) as exc:
        ExecutionService.execute_workflow(_gated_ir(), {})
    assert "submitted inline" in str(exc.value)
    assert "status: paused" not in str(exc.value)


def test_mcp_auto_approve_pre_approves_off_main_thread():
    import asyncio

    from pflow.mcp_server.services.execution_service import ExecutionService

    text = asyncio.run(asyncio.to_thread(ExecutionService.execute_workflow, _gated_ir(), {}, ["guarded-step"]))
    assert "posting-hello" in text
