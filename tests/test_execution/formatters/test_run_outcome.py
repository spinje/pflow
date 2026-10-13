"""Run outcome guards: one document for every way a run ends, and the sections that render it.

The document tests drive REAL in-process runs (``WorkflowRunner().run``) to each ending and build
the outcome from the ``ExecutionResult`` the runner returned. Unit tests of a single rule (cost
wording, redaction, step compaction) build an ``ExecutionResult`` directly with real collectors.
``COMMON_KEYS`` / ``IDENTITY_KEYS`` / ``METRICS_KEYS`` are the spec's key tables — the CLI-JSON
adapter test imports them so the builder and the channel are held to one definition.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.metrics import MetricsCollector
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.formatters.batch_errors import _truncate_error_message, format_batch_errors_section
from pflow.execution.formatters.run_outcome import (
    EXIT_CODES,
    EXIT_REJECTED,
    RunOutcome,
    _append_outputs,
    _collect_outputs,
    answer_lines,
    build_run_outcome,
    completion_line,
    diagnostic_sections,
    errors_block,
    format_cost_summary_lines,
    format_error_text,
    format_only_indicator,
    format_stderr_warnings,
    gate_lines,
    identity_lines,
    mode_lines,
    render_cli_stderr,
    render_mcp_text,
    resolved_outputs_note,
)
from pflow.execution.gate_prompt import build_gate_resolver
from pflow.execution.result import ExecutionResult, RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.execution.workflow_resolver import resolve_workflow
from pflow.runtime.resume_source import load_resume_source
from pflow.runtime.workflow_trace import WorkflowTraceCollector

COMMON_KEYS = frozenset({"success", "status", "workflow", "errors", "warnings", "advisories", "diagnostics"})
IDENTITY_KEYS = frozenset({"execution_id", "trace_path"})
METRICS_KEYS = frozenset({"duration_ms", "total_cost_usd", "metrics", "execution"})

# The outcome's own optional keys: absent when the run has no value, never present as null.
OPTIONAL_KEYS = (
    "execution_id",
    "trace_path",
    "result",
    "error",
    "gate",
    "resume_command",
    "duration_ms",
    "metrics",
    "execution",
)
OPTIONAL_EXECUTION_KEYS = ("duration_ms", "resumed_from", "nodes_restored", "resume_entry_node", "only_node")


# --- Real runs to every ending -------------------------------------------------------------------

_OK_IR: dict[str, Any] = {
    "nodes": [
        {"id": "one", "type": "shell", "params": {"command": "echo one-value"}},
        {"id": "two", "type": "shell", "params": {"command": "echo two-value"}},
    ],
    "edges": [{"from": "one", "to": "two"}],
}
# Strict template resolution raises out of the engine → the runner's exception return path (#699).
_EXCEPTION_IR: dict[str, Any] = {
    "nodes": [
        {"id": "first", "type": "shell", "params": {"command": "echo '{\"a\": 1}'"}},
        {"id": "second", "type": "shell", "params": {"command": 'echo "$X"', "env": {"X": "${first.stdout.b}"}}},
    ],
    "edges": [{"from": "first", "to": "second"}],
}
# A non-zero shell exit is an error ACTION → the runner's normal return path.
_ACTION_IR: dict[str, Any] = {
    "nodes": [
        {"id": "one", "type": "shell", "params": {"command": "echo one-value"}},
        {"id": "two", "type": "shell", "params": {"command": "echo boom >&2; exit 1"}},
    ],
    "edges": [{"from": "one", "to": "two"}],
}
# Every step succeeds, one declared output can't resolve: a failure with no step to resume (#754).
_OUTPUT_FAILURE_IR: dict[str, Any] = {
    "nodes": [{"id": "one", "type": "shell", "params": {"command": "echo '{\"a\": 1}'"}}],
    "edges": [],
    "outputs": {
        "good": {"source": "${one.stdout.a}"},
        "nul": {"source": "${one.stdout.b ?? null}"},
        "bad": {"source": "${one.stdout.zzz}"},
    },
}

_GATE_WORKFLOW = """# Gate

Three steps; the third needs a human approval.

## Steps

### one

First.

- type: shell

```shell command
echo one-value
```

### two

Second.

- type: shell

```shell command
echo two-value
```

### three

Third, gated.

- type: shell
- approval: required{gate_params}

```shell command
{third}
```
"""


def _gate_workflow(
    tmp_path: Path, *, third: str = "echo three-value", gate_params: str = ""
) -> tuple[Path, dict[str, Any]]:
    path = tmp_path / "gate.pflow.md"
    path.write_text(_GATE_WORKFLOW.format(third=third, gate_params=gate_params), encoding="utf-8")
    return path, resolve_workflow(str(path)).ir


def _run(workflow: Path | dict[str, Any], config: RunnerConfig | None = None, **kwargs: Any) -> ExecutionResult:
    target = str(workflow) if isinstance(workflow, Path) else workflow
    return WorkflowRunner().run(target, {}, config or RunnerConfig(), **kwargs)


def _pause(workflow: Path) -> ExecutionResult:
    """Non-interactive (the MCP resolver): an unanswered gate pauses durably."""
    result = _run(workflow, gate_resolver=build_gate_resolver(frozenset(), None))
    assert result.status is WorkflowStatus.PAUSED, [str(d) for d in result.diagnostics]
    return result


def _resume(workflow: Path, paused: ExecutionResult, *, approve: bool) -> ExecutionResult:
    """``pflow resume <token> --approve yes|no``, in process."""
    source = load_resume_source(
        execution_id=paused.trace.execution_id,
        debug_dir=paused.trace.trace_path.parent,
        gate_answer={"approve": approve},
    )
    return WorkflowRunner().run(
        str(workflow),
        dict(source.inputs or {}),
        RunnerConfig(),
        gate_resolver=build_gate_resolver(frozenset(), None, approval_answer=("three", approve)),
        resume_source=source,
    )


def _outcome(result: ExecutionResult, ir: dict[str, Any]) -> RunOutcome:
    return build_run_outcome(result, ir, workflow_metadata=None)


def _success(tmp_path: Path) -> tuple[ExecutionResult, dict[str, Any]]:
    return _run(_OK_IR), _OK_IR


def _failed_by_exception(tmp_path: Path) -> tuple[ExecutionResult, dict[str, Any]]:
    return _run(_EXCEPTION_IR), _EXCEPTION_IR


def _failed_by_action(tmp_path: Path) -> tuple[ExecutionResult, dict[str, Any]]:
    return _run(_ACTION_IR), _ACTION_IR


def _paused(tmp_path: Path) -> tuple[ExecutionResult, dict[str, Any]]:
    workflow, ir = _gate_workflow(tmp_path)
    return _pause(workflow), ir


def _denied_after_resume(tmp_path: Path) -> tuple[ExecutionResult, dict[str, Any]]:
    workflow, ir = _gate_workflow(tmp_path)
    return _resume(workflow, _pause(workflow), approve=False), ir


Ending = Callable[[Path], tuple[ExecutionResult, dict[str, Any]]]

# ending → (builder, status, the by-status keys its document carries beyond COMMON | IDENTITY | METRICS)
ENDINGS: dict[str, tuple[Ending, WorkflowStatus, frozenset[str]]] = {
    "success": (_success, WorkflowStatus.SUCCESS, frozenset({"result"})),
    "failed_by_exception": (_failed_by_exception, WorkflowStatus.FAILED, frozenset({"error", "resume_command"})),
    "failed_by_action": (_failed_by_action, WorkflowStatus.FAILED, frozenset({"error", "resume_command"})),
    "paused": (_paused, WorkflowStatus.PAUSED, frozenset({"gate", "resume_command"})),
    "denied": (_denied_after_resume, WorkflowStatus.DENIED, frozenset({"gate", "error"})),
}


@pytest.mark.trace_files
class TestEveryEndingHasOneShape:
    """P1-T1: one key table, asserted on all five real endings — presence and absence by exact set."""

    @pytest.mark.parametrize("ending", list(ENDINGS))
    def test_document_key_set(self, tmp_path: Path, ending: str) -> None:
        build, status, by_status = ENDINGS[ending]
        result, ir = build(tmp_path)

        outcome = _outcome(result, ir)
        document = outcome.document

        assert document.keys() == COMMON_KEYS | IDENTITY_KEYS | METRICS_KEYS | by_status
        assert outcome.status is status
        assert document["status"] == status.value
        assert outcome.exit_code == EXIT_CODES[status]
        assert document["success"] is (status is WorkflowStatus.SUCCESS)
        assert document["workflow"] == {"action": "unsaved"}
        assert document["execution_id"] == result.trace.execution_id
        assert document["trace_path"] == str(result.trace.trace_path)
        assert Path(document["trace_path"]).is_file()

    def test_identity_is_absent_without_a_trace_file(self, tmp_path: Path) -> None:
        traced = _outcome(_run(_ACTION_IR), _ACTION_IR).document
        untraced = _outcome(_run(_ACTION_IR, RunnerConfig(trace_enabled=False)), _ACTION_IR).document

        assert {"execution_id", "trace_path", "resume_command"} <= traced.keys()
        assert untraced.keys() == COMMON_KEYS | METRICS_KEYS | {"error"}
        assert untraced["status"] == "failed"

    def test_a_failure_with_no_step_to_resume_carries_no_resume_command(self, tmp_path: Path) -> None:
        resumable = _outcome(_run(_ACTION_IR), _ACTION_IR).document
        output_failure = _outcome(_run(_OUTPUT_FAILURE_IR), _OUTPUT_FAILURE_IR).document

        assert resumable["resume_command"] == f"pflow resume {resumable['execution_id']}"
        assert output_failure["status"] == "failed"
        assert output_failure.keys() >= IDENTITY_KEYS
        assert "resume_command" not in output_failure
        # #754: the outputs that DID resolve ride the failure document.
        assert output_failure["result"] == {"good": 1, "nul": None}

    def test_errors_is_a_list_on_every_ending(self, tmp_path: Path) -> None:
        documents: dict[str, dict[str, Any]] = {}
        for name, (build, _, _) in ENDINGS.items():
            (tmp_path / name).mkdir()
            documents[name] = _outcome(*build(tmp_path / name)).document

        assert documents["success"]["errors"] == []
        assert documents["paused"]["errors"] == []
        assert [error["node_id"] for error in documents["failed_by_action"]["errors"]] == ["two"]
        assert [error["node_id"] for error in documents["failed_by_exception"]["errors"]] == ["second"]
        assert [error["title"] for error in documents["denied"]["errors"]] == ["Gate denied"]
        assert documents["denied"]["error"] == "Denied at gate 'three'."


@pytest.mark.trace_files
class TestAbsentNeverNull:
    """P1-T2: the outcome's own optional keys are omitted, never null — and producers' nulls survive."""

    @pytest.mark.parametrize("ending", list(ENDINGS))
    def test_no_optional_key_is_null(self, tmp_path: Path, ending: str) -> None:
        document = _outcome(*ENDINGS[ending][0](tmp_path)).document

        assert [key for key in OPTIONAL_KEYS if key in document and document[key] is None] == []
        execution = document["execution"]
        assert [key for key in OPTIONAL_EXECUTION_KEYS if key in execution and execution[key] is None] == []

    def test_no_collector_means_no_metrics_keys_and_no_step_duration(self) -> None:
        ir = {"nodes": [{"id": "one", "type": "shell"}]}
        bare = ExecutionResult(success=True, shared_after={"one": {"stdout": "x"}})
        measured = dataclasses.replace(bare, metrics=MetricsCollector())

        assert "duration_ms" in _outcome(measured, ir).document["execution"]
        document = _outcome(bare, ir).document
        assert METRICS_KEYS & document.keys() == {"execution"}
        assert document["execution"] == {
            "nodes_executed": 1,
            "nodes_total": 1,
            "steps": [{"node_id": "one", "status": "completed", "duration_ms": 0, "cached": False}],
        }

    def test_producer_nulls_survive(self, tmp_path: Path) -> None:
        workflow, ir = _gate_workflow(tmp_path)
        gate = _outcome(_pause(workflow), ir).document["gate"]
        output_failure = _outcome(_run(_OUTPUT_FAILURE_IR), _OUTPUT_FAILURE_IR).document
        subscription = _llm_outcome([
            {"model": "gpt-4o", "cost_usd": 0.42},
            {"model": "gpt-6-astra", "cost_usd": None, "api_equivalent_cost_usd": 5.95, "num_turns": 1},
        ]).document

        # The canonical GateRequest payload: an approval gate has no question.
        assert gate["question"] is None
        assert gate["recommendation"] is None
        assert gate["node_id"] == "three"
        # A `?? null` output resolves to null and stays.
        assert "nul" in output_failure["result"]
        assert output_failure["result"]["nul"] is None
        # The pricing tri-state: a null paid total explained by its discriminators beside it.
        assert subscription["total_cost_usd"] is None
        assert subscription["subscription"] == {"calls": 1, "api_equivalent_cost_usd": 5.95}
        assert subscription["partial_cost_usd"] == 0.42
        assert "pricing_available" not in subscription


@pytest.mark.trace_files
def test_nodes_executed_has_one_meaning(tmp_path: Path) -> None:
    """P1-T3: completed steps of this attempt, named once — the attempted count lives in node_timings."""
    document = _outcome(_run(_ACTION_IR), _ACTION_IR).document

    assert document["execution"]["nodes_executed"] == 1
    assert json.dumps(document).count('"nodes_executed"') == 1
    assert set(document["metrics"]["workflow"]["node_timings"]) == {"one", "two"}
    assert "nodes_executed" not in document["metrics"]["workflow"]


@pytest.mark.trace_files
class TestPausedCarriesNoError:
    """P1-T4."""

    def test_the_gate_error_stays_on_the_result_and_off_the_document(self, tmp_path: Path) -> None:
        workflow, ir = _gate_workflow(tmp_path)
        paused = _pause(workflow)
        warning = Diagnostic(severity=Severity.WARNING, message="upstream warned", node_id="one", source="runtime")
        advisory = Diagnostic(severity=Severity.INFO, message="an advisory", node_id="two", source="runtime")
        result = dataclasses.replace(paused, diagnostics=[*paused.diagnostics, warning, advisory])

        outcome = _outcome(result, ir)

        assert [error.title for error in result.errors] == ["Gate needs a human"]
        assert outcome.errors == []
        assert outcome.document["errors"] == []
        assert "error" not in outcome.document
        assert outcome.document["diagnostics"] == [warning.to_output_dict(), advisory.to_output_dict()]
        assert outcome.document["warnings"] == [warning.to_output_dict()]
        assert outcome.document["advisories"] == [advisory.to_output_dict()]

    def test_a_pause_whose_trace_never_reached_disk_ends_as_a_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workflow, ir = _gate_workflow(tmp_path)
        durable = _outcome(_pause(workflow), ir)

        def _fail_open(self: WorkflowTraceCollector) -> None:
            self._disable_streaming(OSError("disk full"))

        monkeypatch.setattr(WorkflowTraceCollector, "_open_stream", _fail_open)
        result = _run(workflow, gate_resolver=build_gate_resolver(frozenset(), None))
        outcome = _outcome(result, ir)

        assert durable.status is WorkflowStatus.PAUSED
        assert {"execution_id", "trace_path", "resume_command", "gate"} <= durable.document.keys()
        assert result.status is WorkflowStatus.PAUSED
        assert outcome.status is WorkflowStatus.FAILED
        assert outcome.exit_code == 1
        assert outcome.document["status"] == "failed"
        assert [error["title"] for error in outcome.document["errors"]] == ["Gate needs a human"]
        assert not ({"execution_id", "trace_path", "resume_command", "gate"} & outcome.document.keys())


@pytest.mark.trace_files
class TestLineageOnEveryEnding:
    """P1-T5: a resumed attempt carries its lineage whatever its ending (#737)."""

    def test_resumed_then_denied(self, tmp_path: Path) -> None:
        workflow, ir = _gate_workflow(tmp_path)
        paused = _pause(workflow)

        outcome = _outcome(_resume(workflow, paused, approve=False), ir)

        source_id = paused.trace.execution_id
        execution = outcome.document["execution"]
        assert outcome.status is WorkflowStatus.DENIED
        assert execution["resumed_from"] == source_id
        assert execution["nodes_restored"] == 2
        assert execution["resume_entry_node"] == "three"
        assert execution["nodes_executed"] == 0
        assert completion_line(outcome) == [
            "✗ Denied at gate 'three'. Workflow stopped cleanly before the step ran. Steps completed: 0 of 3. (exit 3)"
        ]
        assert mode_lines(outcome.document) == [f"  ⤷ Resumed from {source_id} at 'three' — 2 upstream steps restored"]

    def test_resumed_then_failed(self, tmp_path: Path) -> None:
        workflow, ir = _gate_workflow(tmp_path, third="exit 1")
        paused = _pause(workflow)

        outcome = _outcome(_resume(workflow, paused, approve=True), ir)

        source_id = paused.trace.execution_id
        execution = outcome.document["execution"]
        assert outcome.status is WorkflowStatus.FAILED
        assert execution["resumed_from"] == source_id
        assert execution["nodes_restored"] == 2
        assert execution["nodes_executed"] == 0
        resumed = f"  ⤷ Resumed from {source_id} at 'three' — 2 upstream steps restored"
        assert mode_lines(outcome.document) == [resumed]
        # P3-T6: MCP has no resume entry, so its renderer's lineage is pinned here, on the same outcome.
        mcp_lines = render_mcp_text(outcome).splitlines()
        assert mcp_lines[0].startswith("❌ Workflow failed after ")
        assert mcp_lines[1] == resumed
        assert f"execution_id: {outcome.document['execution_id']}" in mcp_lines

    def test_a_fresh_denial_counts_its_completed_steps_and_has_no_lineage(self, tmp_path: Path) -> None:
        workflow, ir = _gate_workflow(tmp_path)

        result = _run(workflow, gate_resolver=build_gate_resolver(frozenset(), None, approval_answer=("three", False)))
        outcome = _outcome(result, ir)

        assert outcome.status is WorkflowStatus.DENIED
        assert outcome.document["execution"]["nodes_executed"] == 2
        assert "resumed_from" not in outcome.document["execution"]
        assert mode_lines(outcome.document) == []
        assert completion_line(outcome) == [
            "✗ Denied at gate 'three'. Workflow stopped cleanly before the step ran. Steps completed: 2 of 3. (exit 3)"
        ]


@pytest.mark.trace_files
class TestOnlyTarget:
    """P1-T9: ``--only`` counts the OTHER nodes, and says so truthfully when the target never ran."""

    @pytest.fixture
    def seeded(self, tmp_path: Path) -> tuple[Path, dict[str, Any]]:
        workflow, ir = _gate_workflow(tmp_path)
        seed = _run(workflow, gate_resolver=build_gate_resolver(frozenset({"three"}), None))
        assert seed.status is WorkflowStatus.SUCCESS
        return workflow, ir

    def test_a_gate_stopped_target_did_not_run(self, seeded: tuple[Path, dict[str, Any]]) -> None:
        workflow, ir = seeded

        result = _run(workflow, RunnerConfig(only_node="three"), gate_resolver=build_gate_resolver(frozenset(), None))
        outcome = _outcome(result, ir)

        execution = outcome.document["execution"]
        assert outcome.status is WorkflowStatus.FAILED
        assert [step["status"] for step in execution["steps"]] == ["not_executed"] * 3
        assert execution["only_node"] == "three"
        assert execution["nodes_skipped"] == 2
        assert mode_lines(outcome.document) == [
            "  ⤷ Only 'three' was selected (--only); it did not run, 2 other nodes not executed"
        ]

    def test_a_completed_target_ran(self, seeded: tuple[Path, dict[str, Any]]) -> None:
        workflow, ir = seeded

        result = _run(
            workflow, RunnerConfig(only_node="three"), gate_resolver=build_gate_resolver(frozenset({"three"}), None)
        )
        outcome = _outcome(result, ir)

        assert outcome.status is WorkflowStatus.SUCCESS
        assert outcome.document["execution"]["nodes_skipped"] == 2
        assert mode_lines(outcome.document) == ["  ⤷ Ran only 'three' (--only), 2 other nodes not executed"]


class TestTolerance:
    """P1-T6: a bare result (no trace, no metrics, empty store) — the shape mocked CLI runs depend on."""

    def test_bare_success_document(self) -> None:
        outcome = build_run_outcome(ExecutionResult(success=True), {}, workflow_metadata=None)

        assert outcome.document == {
            "success": True,
            "status": "success",
            "workflow": {"action": "unsaved"},
            "result": {},
            "errors": [],
            "warnings": [],
            "advisories": [],
            "diagnostics": [],
        }
        assert outcome.exit_code == 0

    def test_sections_render_a_bare_outcome_without_raising(self) -> None:
        outcome = build_run_outcome(ExecutionResult(success=True), {}, workflow_metadata=None)

        assert completion_line(outcome) == []  # no collector → no duration → no completion line
        assert mode_lines(outcome.document) == []
        assert gate_lines(outcome) == []
        assert answer_lines(outcome) == []
        assert resolved_outputs_note(outcome.document) == []
        assert format_cost_summary_lines(outcome.document) == []
        assert identity_lines(outcome.document) == ["status: success"]

    def test_success_is_derived_from_the_status(self) -> None:
        """``success``, ``status`` and the exit code are one fact: the status decides, ``result.success`` never does."""
        error = Diagnostic(severity=Severity.ERROR, message="boom", source="runtime")
        incoherent = ExecutionResult(success=True, status=WorkflowStatus.FAILED, diagnostics=[error])

        failed = build_run_outcome(incoherent, {}, workflow_metadata=None)
        succeeded = build_run_outcome(ExecutionResult(success=True), {}, workflow_metadata=None)

        assert failed.document["success"] is False
        assert failed.document["status"] == "failed"
        assert failed.exit_code == 1
        assert succeeded.document["success"] is True
        assert succeeded.document["status"] == "success"
        assert succeeded.exit_code == 0

    def test_a_failure_before_the_engine_exits_rejected_and_keeps_its_document(self) -> None:
        """The phase changes the exit code only (#815): the document of a refused run is a failure's."""
        error = Diagnostic(severity=Severity.ERROR, message="boom", source="validator")
        refused = ExecutionResult(
            success=False, status=WorkflowStatus.FAILED, diagnostics=[error], engine_started=False
        )
        ran = dataclasses.replace(refused, engine_started=True)

        refused_outcome = build_run_outcome(refused, {}, workflow_metadata=None)
        ran_outcome = build_run_outcome(ran, {}, workflow_metadata=None)

        assert EXIT_REJECTED == 2
        assert refused_outcome.exit_code == EXIT_REJECTED
        assert ran_outcome.exit_code == EXIT_CODES[WorkflowStatus.FAILED] == 1
        assert refused_outcome.document == ran_outcome.document


# --- Redaction and integrity of the printed diagnostics -----------------------------------------


def _error(message: str, node_id: str | None = None, **context: object) -> Diagnostic:
    return Diagnostic(
        severity=Severity.ERROR,
        message=message,
        node_id=node_id,
        source="runtime",
        context=dict(context) if context else None,
    )


def _failed(*diagnostics: Diagnostic, shared: dict[str, Any] | None = None) -> ExecutionResult:
    return ExecutionResult(
        success=False, status=WorkflowStatus.FAILED, diagnostics=list(diagnostics), shared_after=shared or {}
    )


class TestPrintedDiagnosticsAreRedacted:
    """P1-T7: every diagnostic in the document is ``Diagnostic.to_output_dict()``."""

    def test_secrets_in_error_context_are_redacted_with_no_raw_copy(self) -> None:
        result = _failed(
            _error(
                "API validation failed",
                raw_response={"api_key": "sk-secret123456", "error": "Invalid request", "apikey": "another"},
                response_headers={"Authorization": "Bearer secret-token", "Content-Type": "application/json"},
                nested={"error": {"details": {"password": "user-password-123", "message": "Auth failed"}}},
            )
        )

        document = _outcome(result, {}).document

        error = document["errors"][0]
        assert error["context"]["raw_response"] == {
            "api_key": "<REDACTED>",
            "error": "Invalid request",
            "apikey": "<REDACTED>",
        }
        assert error["context"]["response_headers"] == {
            "Authorization": "<REDACTED>",
            "Content-Type": "application/json",
        }
        assert error["context"]["nested"]["error"]["details"] == {"password": "<REDACTED>", "message": "Auth failed"}
        assert "raw_response" not in error
        assert document["diagnostics"] == [error]
        assert "sk-secret123456" not in json.dumps(document)

    def test_warnings_are_redacted_and_split_from_advisories(self) -> None:
        warning = Diagnostic(
            severity=Severity.WARNING,
            message="Shell node has no template inputs",
            suggestions=["Use '- cache: true' only if output is purely a function of declared inputs."],
            node_id="run-shell",
            source="validator",
            context={"category": "cache", "headers": {"Authorization": "Bearer abc"}},
        )
        advisory = Diagnostic(
            severity=Severity.INFO, message="Batch 'b' ran with 0 items.", node_id="b", source="runtime"
        )

        document = _outcome(ExecutionResult(success=True, diagnostics=[warning, advisory]), {}).document

        expected_warning = {
            "severity": "warning",
            "message": "Shell node has no template inputs",
            "source": "validator",
            "suggestions": ["Use '- cache: true' only if output is purely a function of declared inputs."],
            "node_id": "run-shell",
            "context": {"category": "cache", "headers": {"Authorization": "<REDACTED>"}},
        }
        assert document["warnings"] == [expected_warning]
        assert [advisory["message"] for advisory in document["advisories"]] == ["Batch 'b' ran with 0 items."]
        assert document["diagnostics"] == [expected_warning, advisory.to_output_dict()]

    def test_the_diagnostic_itself_keeps_its_raw_value(self) -> None:
        diagnostic = _error("Test error", raw_response={"api_key": "secret", "data": "value"})

        _outcome(_failed(diagnostic), {})

        assert diagnostic.context == {"raw_response": {"api_key": "secret", "data": "value"}}

    def test_every_error_is_printed_and_summarized_by_count(self) -> None:
        result = _failed(
            *(_error(f"Error {n}", node_id=f"node{n}", raw_response={"secret": f"s{n}"}) for n in (1, 2, 3))
        )

        document = _outcome(result, {}).document

        assert [error["message"] for error in document["errors"]] == ["Error 1", "Error 2", "Error 3"]
        assert [error["context"]["raw_response"]["secret"] for error in document["errors"]] == ["<REDACTED>"] * 3
        assert document["error"] == "Workflow execution failed (3 errors)"


@pytest.mark.trace_files
def test_a_paused_gate_preview_is_masked(tmp_path: Path) -> None:
    workflow, ir = _gate_workflow(tmp_path, gate_params="\n- env: { API_KEY: sk-super-secret }")

    document = _outcome(_pause(workflow), ir).document

    assert document["gate"]["preview"] == {"command": "echo three-value", "env": {"API_KEY": "<REDACTED>"}}
    assert "sk-super-secret" not in json.dumps(document)


# --- The step table --------------------------------------------------------------------------------


_PAYLOAD = "PAYLOAD-START " + " ".join(f"token{i}" for i in range(200)) + " PAYLOAD-END"
_ITEM_SUMMARY = {
    "summary_version": 1,
    "type": "dict",
    "label": "oversized-item",
    "size_chars": len(_PAYLOAD),
    "sha256": "123456789abc",
    "summary": "label='oversized-item'; payload=<str 1909 chars sha256=123456789abc>",
    "truncated": True,
}


def _batch_output(*, failed_items: int, succeeded: int = 0) -> dict[str, Any]:
    return {
        "count": failed_items + succeeded,
        "success_count": succeeded,
        "error_count": failed_items,
        "results": [{"item": "ok", "response": "ok"}] * succeeded,
        "errors": [
            {
                "index": index,
                "item": {"label": "oversized-item", "payload": _PAYLOAD},
                "item_summary": _ITEM_SUMMARY,
                "error": "forced batch failure",
                "exception": RuntimeError("boom"),
            }
            for index in range(failed_items)
        ],
        "batch_metadata": {"execution_mode": "sequential"},
    }


def _assert_compacted(detail: dict[str, Any]) -> None:
    assert detail["item_summary"] == _ITEM_SUMMARY
    assert detail["item_ref"] == "123456789abc"
    assert detail["has_full_item"] is True
    assert "item" not in detail
    assert "exception" not in detail


class TestExecutionBlock:
    def test_step_statuses_follow_the_shared_store(self) -> None:
        shared = {
            "fetch": {"result": "ok"},
            "process": {"result": "ok"},
            "__failures__": {"send": {"data": {"error": "Send failed"}, "category": "node_action_error"}},
            "__execution__": {"completed_nodes": ["fetch", "process"], "failed_node": "send"},
            "__cache_hits__": ["fetch"],
        }
        ir = {"nodes": [{"id": "fetch"}, {"id": "process"}, {"id": "send"}]}

        execution = _outcome(_failed(_error("Send failed"), shared=shared), ir).document["execution"]

        assert [(step["node_id"], step["status"], step["cached"]) for step in execution["steps"]] == [
            ("fetch", "completed", True),
            ("process", "completed", False),
            ("send", "failed", False),
        ]
        assert execution["nodes_executed"] == 2
        assert execution["nodes_total"] == 3
        assert execution["cache_hits"] == 1

    def test_no_nodes_means_no_execution_block(self) -> None:
        document = _outcome(_failed(_error("Error")), {"nodes": []}).document

        assert "execution" not in document
        assert "execution" in _outcome(_failed(_error("Error")), {"nodes": [{"id": "n"}]}).document

    def test_failed_batch_details_are_compacted(self) -> None:
        shared = {
            "__failures__": {"batch": {"data": _batch_output(failed_items=1), "category": "node_action_error"}},
            "__execution__": {"completed_nodes": [], "failed_node": "batch"},
        }

        document = _outcome(
            _failed(_error("forced batch failure", node_id="batch"), shared=shared), {"nodes": [{"id": "batch"}]}
        ).document

        _assert_compacted(document["execution"]["steps"][0]["batch_error_details"][0])
        serialized = json.dumps(document, default=str)
        assert "PAYLOAD-START" not in serialized
        assert "token199" not in serialized

    def test_degraded_batch_details_and_result_are_compacted(self) -> None:
        shared = {
            "__execution__": {"completed_nodes": ["process"]},
            "process": _batch_output(failed_items=1, succeeded=1),
        }
        result = ExecutionResult(
            success=True, status=WorkflowStatus.DEGRADED, shared_after=shared, metrics=MetricsCollector()
        )

        document = _outcome(result, {"nodes": [{"id": "process"}]}).document

        _assert_compacted(document["execution"]["steps"][0]["batch_error_details"][0])
        _assert_compacted(document["result"]["process"]["errors"][0])
        assert document["result"]["process"]["results"][0]["item"] == "ok"


# --- Section functions -----------------------------------------------------------------------------


def _measured(
    shared: dict[str, Any],
    ir: dict[str, Any],
    *,
    status: WorkflowStatus = WorkflowStatus.SUCCESS,
    diagnostics: list[Diagnostic] | None = None,
) -> RunOutcome:
    """An outcome with a real metrics collector, so duration-bearing sections render."""
    result = ExecutionResult(
        success=status in (WorkflowStatus.SUCCESS, WorkflowStatus.DEGRADED),
        status=status,
        shared_after=shared,
        diagnostics=diagnostics or [],
        metrics=MetricsCollector(),
    )
    return _outcome(result, ir)


def _completed(*node_ids: str, cached: tuple[str, ...] = ()) -> tuple[dict[str, Any], dict[str, Any]]:
    shared: dict[str, Any] = {node_id: {"stdout": node_id} for node_id in node_ids}
    shared["__execution__"] = {"completed_nodes": list(node_ids)}
    shared["__cache_hits__"] = list(cached)
    return shared, {"nodes": [{"id": node_id} for node_id in node_ids]}


class TestCompletionLine:
    def test_clean_success(self) -> None:
        line = completion_line(_measured(*_completed("a")))

        assert len(line) == 1
        assert line[0].startswith("✓ Workflow completed in ")

    def test_degraded_reads_completed_with_warnings(self) -> None:
        line = completion_line(_measured(*_completed("a"), status=WorkflowStatus.DEGRADED))

        assert line[0].startswith("⚠️ Workflow completed with warnings in ")

    def test_a_warning_counts_and_an_advisory_does_not(self) -> None:
        warning = Diagnostic(severity=Severity.WARNING, message="real warning", source="runtime")
        advisory = Diagnostic(severity=Severity.INFO, message="ran with 0 items", source="runtime")

        warned = completion_line(_measured(*_completed("a"), diagnostics=[warning, advisory]))
        advised = completion_line(_measured(*_completed("a"), diagnostics=[advisory]))

        assert warned[0].startswith("⚠️ Workflow completed with 1 warning in ")
        assert advised[0].startswith("✓ Workflow completed in ")

    def test_failed_names_its_warnings(self) -> None:
        warning = Diagnostic(severity=Severity.WARNING, message="real warning", source="runtime")

        plain = completion_line(_measured(*_completed("a"), status=WorkflowStatus.FAILED))
        warned = completion_line(_measured(*_completed("a"), status=WorkflowStatus.FAILED, diagnostics=[warning]))

        assert plain[0].startswith("❌ Workflow failed after ")
        assert warned[0].startswith("❌ Workflow failed (1 warning) after ")

    @pytest.mark.parametrize(
        ("node_ids", "cached", "suffix"),
        [
            (("a", "b", "c", "d", "e"), ("a", "b", "c"), " (3 cached, 2 executed)"),
            (("a", "b", "c"), ("a", "b", "c"), " (3 cached, 0 executed)"),
        ],
    )
    def test_cache_stats_suffix(self, node_ids: tuple[str, ...], cached: tuple[str, ...], suffix: str) -> None:
        line = completion_line(_measured(*_completed(*node_ids, cached=cached)))

        assert line[0].startswith("✓ Workflow completed in ")
        assert line[0].endswith(suffix)

    def test_no_cache_suffix_without_hits(self) -> None:
        line = completion_line(_measured(*_completed("a", "b")))

        assert "cached" not in line[0]
        assert line[0].endswith("s")

    def test_degraded_keeps_the_cache_suffix(self) -> None:
        line = completion_line(
            _measured(*_completed("a", "b", "c", "d", cached=("a", "b")), status=WorkflowStatus.DEGRADED)
        )

        assert line[0].startswith("⚠️ Workflow completed with warnings in ")
        assert line[0].endswith(" (2 cached, 2 executed)")

    @pytest.mark.trace_files
    def test_paused_names_the_step(self, tmp_path: Path) -> None:
        workflow, ir = _gate_workflow(tmp_path)

        line = completion_line(_outcome(_pause(workflow), ir))

        assert line == ["⏸ Workflow paused at 'three' — a human decision is required."]


@pytest.mark.trace_files
def test_shell_stderr_upgrades_the_glyph_and_its_preview_keeps_the_cause(tmp_path: Path) -> None:
    """#755: a long stderr whose cause comes last — the preview keeps the tail, not just the head."""
    noise = "progress " * 120
    ir = {
        "nodes": [
            {
                "id": "noisy",
                "type": "shell",
                "params": {"command": f"echo '{noise}' >&2; echo 'error: the real cause' >&2; echo ok"},
            }
        ],
        "edges": [],
    }
    outcome = _outcome(_run(ir), ir)
    clean = _outcome(_run(_OK_IR), _OK_IR)

    block = format_stderr_warnings(outcome.document["execution"]["steps"])

    assert completion_line(outcome)[0].startswith("⚠️ Workflow completed in ")
    assert block[:2] == ["", "⚠️  Shell stderr (exit code 0):"]
    assert block[2].startswith("  • noisy: progress progress")
    assert "chars omitted]" in block[2]
    assert block[-1] == " " * len("  • noisy: ") + "error: the real cause"
    assert completion_line(clean)[0].startswith("✓ Workflow completed in ")
    assert format_stderr_warnings(clean.document["execution"]["steps"]) == []
    # The MCP response composes the same sections: an agent there sees the glyph and the cause too.
    noisy_text = render_mcp_text(outcome)
    clean_text = render_mcp_text(clean)
    assert noisy_text.startswith("⚠️ Workflow completed in ")
    assert "\n⚠️  Shell stderr (exit code 0):\n" in noisy_text
    assert "\n" + "\n".join(block[2:]) + "\n" in noisy_text
    assert clean_text.startswith("✓ Workflow completed in ")
    assert "Shell stderr" not in clean_text


class TestStderrWarnings:
    def test_no_stderr_renders_nothing(self) -> None:
        assert format_stderr_warnings([{"node_id": "clean", "has_stderr": False, "stderr": ""}, {"node_id": "x"}]) == []

    def test_a_stale_flag_with_empty_stderr_renders_nothing(self) -> None:
        assert format_stderr_warnings([{"node_id": "flagged", "has_stderr": True, "stderr": ""}]) == []

    def test_short_stderr_is_kept_whole(self) -> None:
        lines = format_stderr_warnings([
            {"node_id": "grep_pipe", "has_stderr": True, "stderr": "grep: foo: No such file"}
        ])

        assert lines == ["", "⚠️  Shell stderr (exit code 0):", "  • grep_pipe: grep: foo: No such file"]

    def test_multiline_stderr_is_indented(self) -> None:
        lines = format_stderr_warnings([{"node_id": "multi", "has_stderr": True, "stderr": "first line\nsecond line"}])

        # #806: further lines hang under the value column, each its own line.
        assert lines[2:] == ["  • multi: first line", " " * len("  • multi: ") + "second line"]


class TestModeLines:
    def _only(self, statuses: dict[str, str], only_node: str) -> dict[str, Any]:
        shared: dict[str, Any] = {node: {"stdout": node} for node, status in statuses.items() if status == "completed"}
        shared["__execution__"] = {
            "only_node": only_node,
            "restored_nodes": [node for node, status in statuses.items() if status == "restored"],
        }
        return _outcome(
            ExecutionResult(success=True, shared_after=shared), {"nodes": [{"id": n} for n in statuses]}
        ).document

    def test_only_counts_the_other_nodes(self) -> None:
        document = self._only({"fetch": "restored", "process": "completed", "save": "restored"}, "process")

        assert mode_lines(document) == ["  ⤷ Ran only 'process' (--only), 2 other nodes not executed"]

    def test_one_other_node_is_singular(self) -> None:
        document = self._only({"fetch": "completed", "save": "restored"}, "fetch")

        assert mode_lines(document) == ["  ⤷ Ran only 'fetch' (--only), 1 other node not executed"]

    def test_nothing_else_restored_is_the_short_form(self) -> None:
        document = self._only({"target_c": "completed"}, "target_c")

        assert mode_lines(document) == ["  ⤷ Ran only 'target_c' (--only)"]

    def test_a_full_run_has_no_mode_line(self) -> None:
        shared, ir = _completed("fetch", "broken")

        assert mode_lines(_outcome(ExecutionResult(success=True, shared_after=shared), ir).document) == []


class TestFormatOnlyIndicator:
    def test_long_form(self) -> None:
        assert (
            format_only_indicator("target_b", 2, ran=True)
            == "  ⤷ Ran only 'target_b' (--only), 2 other nodes not executed"
        )

    def test_short_form(self) -> None:
        assert format_only_indicator("target_c", 0, ran=True) == "  ⤷ Ran only 'target_c' (--only)"

    def test_singular(self) -> None:
        assert format_only_indicator("target_a", 1, ran=True).endswith("1 other node not executed")

    def test_not_ran_forms(self) -> None:
        assert format_only_indicator("three", 2, ran=False) == (
            "  ⤷ Only 'three' was selected (--only); it did not run, 2 other nodes not executed"
        )
        assert format_only_indicator("solo", 0, ran=False) == "  ⤷ Only 'solo' was selected (--only); it did not run"

    def test_node_id_quoted_verbatim(self) -> None:
        assert "'my-node.with.dots'" in format_only_indicator("my-node.with.dots", 3, ran=True)


class TestErrorsAndDiagnosticSections:
    def test_one_error_is_one_unnumbered_diagnostic(self) -> None:
        error = Diagnostic(
            severity=Severity.ERROR,
            message="Shell command failed",
            title="Execution Failed",
            node_id="run-tests",
            source="runtime",
        )

        lines = errors_block([error], [])

        assert len(lines) == 1
        assert "Execution Failed" in lines[0]
        assert "run-tests" in lines[0]
        assert "Error 1" not in lines[0]

    def test_every_error_is_numbered_under_a_counted_header(self) -> None:
        errors = [_error(f"failure number {n}", node_id=f"n{n}") for n in range(1, 5)]
        warning = Diagnostic(severity=Severity.WARNING, message="w", source="runtime")

        text = "\n".join(errors_block(errors, [warning]))

        assert text.startswith("❌ Workflow execution failed (4 errors, 1 warning)")
        for n in range(1, 5):
            assert f"Error {n}: Error\n\nfailure number {n}\n  At: node 'n{n}'" in text

    def test_warnings_then_advisories(self) -> None:
        warning = Diagnostic(
            severity=Severity.WARNING, message="API error: Rate limit exceeded", node_id="send-alert", source="runtime"
        )
        advisory = Diagnostic(severity=Severity.INFO, message="Batch 'consume' ran with 0 items.", source="runtime")

        lines = diagnostic_sections([warning], [advisory])

        assert lines[0] == "⚠️ Warnings:"
        assert "[send-alert] API error: Rate limit exceeded" in lines[1]
        assert lines[2:4] == ["", "\N{INFORMATION SOURCE}\N{VARIATION SELECTOR-16} Advisories:"]
        assert "ran with 0 items" in lines[4]
        assert diagnostic_sections([], [advisory])[0] == "\N{INFORMATION SOURCE}\N{VARIATION SELECTOR-16} Advisories:"
        assert diagnostic_sections([], []) == []


@pytest.mark.trace_files
class TestGateAnswerAndIdentityLines:
    def test_a_pause_renders_its_gate_and_answer_a_denial_renders_neither(self, tmp_path: Path) -> None:
        workflow, ir = _gate_workflow(tmp_path)
        paused = _pause(workflow)
        paused_outcome = _outcome(paused, ir)
        denied_outcome = _outcome(_resume(workflow, paused, approve=False), ir)

        token = paused.trace.execution_id
        assert gate_lines(paused_outcome) == ["command:  echo three-value"]
        assert answer_lines(paused_outcome) == [f"To answer: pflow resume {token} --approve yes|no"]
        assert "gate" in denied_outcome.document
        assert gate_lines(denied_outcome) == []
        assert answer_lines(denied_outcome) == []
        # Same rule on MCP's renderer: the pause shows its gate, the denial only its denied line.
        assert "\nGate:\n  command:  echo three-value" in render_mcp_text(paused_outcome)
        denied_text = render_mcp_text(denied_outcome)
        assert denied_text.splitlines()[0].startswith("✗ Denied at gate 'three'.")
        assert "Gate:" not in denied_text
        assert "Error: " not in denied_text

    def test_identity_lines_name_present_keys_only(self, tmp_path: Path) -> None:
        workflow, ir = _gate_workflow(tmp_path)
        paused = _outcome(_pause(workflow), ir).document
        untraced = _outcome(_run(_OK_IR, RunnerConfig(trace_enabled=False)), _OK_IR).document

        assert identity_lines(paused) == [
            "status: paused",
            f"execution_id: {paused['execution_id']}",
            f"trace_path: {paused['trace_path']}",
            f"resume_command: {paused['resume_command']}",
        ]
        assert identity_lines(untraced) == ["status: success"]

    def test_resolved_outputs_note_only_on_a_failure(self, tmp_path: Path) -> None:
        failed = _outcome(_run(_OUTPUT_FAILURE_IR), _OUTPUT_FAILURE_IR).document
        succeeded = _outcome(_run(_OK_IR), _OK_IR).document

        assert resolved_outputs_note(failed) == [
            "Outputs that resolved before the failure:",
            '{\n  "good": 1,\n  "nul": null\n}',
        ]
        assert succeeded["result"]
        assert resolved_outputs_note(succeeded) == []


class TestFormatErrorText:
    """P1-T8: the ``registry_run`` probe's errors + warnings text."""

    def test_errors_then_warnings_and_advisories(self) -> None:
        error = _error("exit 1", node_id="build")
        warning = Diagnostic(severity=Severity.WARNING, message="watch out", node_id="build", source="runtime")
        advisory = Diagnostic(severity=Severity.INFO, message="for the record", source="validator")

        text = format_error_text([error], [warning, advisory])

        assert text.startswith("Error: Error\n\nexit 1\n  At: node 'build'\n\n⚠️ Warnings:\n")
        assert "watch out" in text
        assert "Advisories:" in text
        assert text.endswith("for the record")

    def test_no_errors_still_says_it_failed_and_keeps_the_warnings(self) -> None:
        warning = Diagnostic(severity=Severity.WARNING, message="watch out", source="runtime")

        assert format_error_text([], []) == "❌ Workflow execution failed — no error details were recorded"
        assert format_error_text([], [warning]).startswith(
            "❌ Workflow execution failed — no error details were recorded\n\n⚠️ Warnings:"
        )

    def test_shell_details_are_shown(self) -> None:
        error = _error(
            "exit 1",
            node_id="build",
            category="execution_failure",
            shell_command="npm run build",
            shell_stderr="Error: Cannot find module 'webpack'",
        )

        text = format_error_text([error], [])

        assert "npm run build" in text
        assert "Cannot find module 'webpack'" in text

    def test_long_shell_values_are_cut(self) -> None:
        error = _error(
            "exit 1", node_id="run", category="execution_failure", shell_command="x" * 250, shell_stderr="y" * 500
        )

        text = format_error_text([error], [])

        assert f"Command: {'x' * 200}...\n" in text
        assert f"Stderr: {'y' * 100} … [100 chars omitted] … {'y' * 300}" in text


class TestRenderCliStderr:
    """The tier table's cells on built outcomes (the CLI adapter's real runs: ``test_run_outcome_cli.py``)."""

    @staticmethod
    def _render(outcome: RunOutcome, *, text_mode: bool = True, print_flag: bool = False) -> list[str]:
        return render_cli_stderr(outcome, text_mode=text_mode, print_flag=print_flag, verbose=False)

    def test_an_advisory_never_degrades_the_completion_line(self) -> None:
        advisory = Diagnostic(severity=Severity.INFO, message="Batch 'consume' ran with 0 items.", source="runtime")
        warning = Diagnostic(severity=Severity.WARNING, message="something genuinely off", source="runtime")

        advised = self._render(_measured(*_completed("a"), diagnostics=[advisory]))
        warned = self._render(_measured(*_completed("a"), diagnostics=[warning]))

        assert advised[1].startswith("✓ Workflow completed in ")
        assert "\N{INFORMATION SOURCE}\N{VARIATION SELECTOR-16} Advisories:" in advised
        assert "⚠️ Warnings:" not in advised
        assert warned[1].startswith("⚠️ Workflow completed with 1 warning in ")
        assert "⚠️ Warnings:" in warned

    def test_a_failure_renders_warnings_then_its_error(self) -> None:
        advisory = Diagnostic(severity=Severity.INFO, message="'## Input' looks like a typo.", source="parser")
        result = dataclasses.replace(_failed(_error("workflow failed"), advisory), metrics=MetricsCollector())

        lines = self._render(_outcome(result, {}))

        advisories_at = lines.index("\N{INFORMATION SOURCE}\N{VARIATION SELECTOR-16} Advisories:")
        error_at = next(i for i, line in enumerate(lines) if line.startswith("Error: "))
        assert lines[1].startswith("❌ Workflow failed after ")
        assert advisories_at < error_at
        assert "⚠️ Warnings:" not in lines

    def test_a_failure_with_no_recorded_error_still_says_it_failed(self) -> None:
        lines = self._render(_outcome(_failed(), {}))

        assert lines == ["", "❌ Workflow execution failed — no error details were recorded"]

    def test_json_mode_prints_no_must_act_block_and_print_leaves_only_mode_lines(self) -> None:
        shared, ir = _completed("a", "b")
        shared["__execution__"] = {"completed_nodes": ["a", "b"], "resumed_from": "src-1", "restored_nodes": ["a"]}
        result = ExecutionResult(
            success=False,
            status=WorkflowStatus.FAILED,
            shared_after=shared,
            diagnostics=[_error("boom", node_id="b")],
            metrics=MetricsCollector(),
        )
        outcome = _outcome(result, ir)
        resumed = "  ⤷ Resumed from src-1 — 1 upstream step restored"

        text = self._render(outcome)
        json_mode = self._render(outcome, text_mode=False)
        json_print = self._render(outcome, text_mode=False, print_flag=True)

        assert any(line.startswith("Error: ") for line in text)
        assert not any(line.startswith("Error: ") for line in json_mode)
        assert json_mode[1].startswith("❌ Workflow failed after ")
        assert resumed in json_mode
        assert json_print == [resumed]

    def test_subscription_cost_reaches_stderr(self) -> None:
        outcome = _llm_outcome([
            {"model": "gpt-6-astra", "cost_usd": None, "api_equivalent_cost_usd": 5.9507, "num_turns": 1}
        ])

        assert "💰 Cost: subscription (1 agent call) · API-equivalent: $5.9507" in self._render(outcome)


# --- Cost lines (real metrics + trace collectors) --------------------------------------------------


def _llm_outcome(calls: list[dict[str, Any]]) -> RunOutcome:
    """A success whose trace recorded these LLM calls — the builder reads them via ``trace.collect_llm_calls``."""
    trace = WorkflowTraceCollector("cost")
    metrics = MetricsCollector()
    for index, call in enumerate(calls):
        node_id = f"llm{index}"
        trace.record_node_execution(node_id, "LLMNode", 10.0, True, node_output={"llm_usage": call})
        metrics.record_node_execution(node_id, 10.0)
    return _outcome(ExecutionResult(success=True, trace=trace, metrics=metrics), {})


def _priced(n: int, *, cost: float, tokens: int = 10) -> list[dict[str, Any]]:
    return [{"model": "gpt-4o", "cost_usd": cost / n, "input_tokens": tokens // n, "output_tokens": 0}] * n


class TestCostLines:
    def test_unpriced_model_names_it_with_the_call_count(self) -> None:
        lines = format_cost_summary_lines(_llm_outcome([{"model": "my-custom-model", "cost_usd": None}] * 5).document)

        assert lines == [
            "⚠️  Cost unavailable — pricing data missing for: my-custom-model (5 calls)",
            "   Total LLM calls: 5",
        ]

    def test_partial_cost(self) -> None:
        calls = [{"model": "gpt-4o", "cost_usd": 0.03}, *[{"model": "unknown-model", "cost_usd": None}] * 2]
        outcome = _llm_outcome(calls)
        document = outcome.document

        lines = format_cost_summary_lines(document)

        # The JSON explains its null total with the discriminators beside it, not only in metrics.total.
        assert document["total_cost_usd"] is None
        assert document["partial_cost_usd"] == 0.03
        assert document["pricing_available"] is False
        assert document["unavailable_models"] == [{"name": "unknown-model", "calls": 2}]
        assert lines == [
            "💰 Cost: $0.0300+ (partial — pricing unavailable for: unknown-model (2 calls))",
            "   Total LLM calls: 3",
        ]
        assert render_mcp_text(outcome).splitlines()[1:3] == lines

    def test_priced_cost_carries_calls_and_tokens(self) -> None:
        priced = _llm_outcome(_priced(2, cost=0.05, tokens=28000))

        assert format_cost_summary_lines(priced.document) == ["💰 Cost: $0.0500 (2 calls, 28,000 tokens)"]
        assert "pricing_available" not in priced.document
        assert "\n💰 Cost: $0.0500 (2 calls, 28,000 tokens)\n" in render_mcp_text(priced)
        assert format_cost_summary_lines(_llm_outcome(_priced(1, cost=0.05, tokens=2137122)).document) == [
            "💰 Cost: $0.0500 (1 call, 2,137,122 tokens)"
        ]

    def test_unrecorded_models_render_as_a_count(self) -> None:
        unnamed = format_cost_summary_lines(_llm_outcome([{"cost_usd": None}] * 2).document)
        mixed = format_cost_summary_lines(
            _llm_outcome([
                {"model": "known", "cost_usd": 0.0234},
                *[{"model": "gpt-5", "cost_usd": None}] * 3,
                {"cost_usd": None},
            ]).document
        )

        assert unnamed == [
            "⚠️  Cost unavailable — pricing data missing for: 2 calls without recorded model",
            "   Total LLM calls: 2",
        ]
        assert "gpt-5 (3 calls); 1 call without recorded model" in mixed[0]
        assert mixed[1] == "   Total LLM calls: 5"

    def test_subscription_estimate_is_labelled_not_reported_missing(self) -> None:
        lines = format_cost_summary_lines(
            _llm_outcome([
                {"model": "gpt-4o", "cost_usd": 0.42},
                {"model": "gpt-6-astra", "cost_usd": None, "api_equivalent_cost_usd": 5.95, "num_turns": 1},
            ]).document
        )

        assert lines[0] == "💰 Cost: $0.4200 + subscription (1 agent call) · API-equivalent total: $6.3700"
        assert not any("pricing data missing" in line for line in lines)

    def test_no_llm_calls_no_cost_lines(self) -> None:
        document = _llm_outcome([]).document

        assert document["total_cost_usd"] == 0.0
        assert format_cost_summary_lines(document) == []


# --- Moved unchanged: output selection and value rendering -----------------------------------------


class TestAppendOutputsCliMcpParity:
    """``_append_outputs`` renders a value exactly as CLI ``safe_output`` does."""

    def _render(self, value: object) -> list[str]:
        lines: list[str] = []
        _append_outputs(lines, {"value": value})
        return lines

    def test_string_passes_through_verbatim(self) -> None:
        assert self._render("hello world") == ["hello world"]

    def test_structured_values_are_json(self) -> None:
        assert json.loads(self._render({"key": "value", "n": 42})[0]) == {"key": "value", "n": 42}
        assert json.loads(self._render(["a", "b", "c"])[0]) == ["a", "b", "c"]
        assert self._render(True) == ["true"]
        assert self._render(None) == ["null"]

    def test_unserializable_value_uses_default_str(self) -> None:
        from datetime import datetime

        assert self._render(datetime(2026, 4, 7, 12, 0, 0)) == ['"2026-04-07 12:00:00"']

    def test_nan_falls_back_to_repr(self) -> None:
        assert self._render({"x": float("nan")}) == ["{'x': nan}"]

    def test_dotted_output_key_value(self) -> None:
        shared = {
            "batch-llm": {"results": [{"r": "a"}], "count": 1, "success_count": 1, "error_count": 0, "errors": []}
        }

        outputs = _collect_outputs(shared, workflow_ir={}, output_key="batch-llm.success_count")
        lines: list[str] = []
        _append_outputs(lines, outputs)

        assert outputs == {"batch-llm.success_count": 1}
        assert lines == ["1"]


class TestCollectOutputsDottedPath:
    def test_resolves_dotted_output_key(self) -> None:
        shared = {"batch-llm": {"success_count": 2, "count": 2, "errors": []}}
        assert _collect_outputs(shared, workflow_ir={}, output_key="batch-llm.success_count") == {
            "batch-llm.success_count": 2
        }

    def test_resolved_none_emits_null(self) -> None:
        shared = {"node": {"value": None, "success_count": 1, "count": 1}}
        assert _collect_outputs(shared, workflow_ir={}, output_key="node.value") == {"node.value": None}

    def test_resolved_batch_errors_emits_empty_list(self) -> None:
        shared = {"batch-llm": {"errors": [], "success_count": 1, "count": 1}}
        assert _collect_outputs(shared, workflow_ir={}, output_key="batch-llm.errors") == {"batch-llm.errors": []}

    def test_missing_key_returns_empty(self) -> None:
        assert _collect_outputs({"batch-llm": {"success_count": 2}}, workflow_ir={}, output_key="nonexistent.foo") == {}

    def test_list_index_path(self) -> None:
        shared = {"batch-llm": {"results": [{"r": "alpha"}, {"r": "beta"}]}}
        assert _collect_outputs(shared, workflow_ir={}, output_key="batch-llm.results[1].r") == {
            "batch-llm.results[1].r": "beta"
        }


class TestOutputSelection:
    """The document's ``result`` selection (``find_auto_output``'s own rules: ``test_output_utils.py``)."""

    def _result(self, shared: dict[str, Any], ir: dict[str, Any]) -> Any:
        return _outcome(ExecutionResult(success=True, shared_after=shared), ir).document["result"]

    def test_only_uses_target_scoped_output_selection(self) -> None:
        shared = {
            "__execution__": {"only_node": "fetch"},
            "result": "unrelated root result",
            "fetch": {"stdout": "target stdout", "exit_code": 0},
        }
        assert self._result(shared, {"outputs": {"result": {"source": "${downstream.stdout}"}}}) == {
            "stdout": "target stdout"
        }

    def test_full_run_emits_every_declared_output(self) -> None:
        shared = {"alpha": "A", "beta": "B", "fetch": {"stdout": "raw node stdout"}}
        ir = {"outputs": {"alpha": {"source": "${fetch.stdout}"}, "beta": {"source": "${other.stdout}"}}}
        assert self._result(shared, ir) == {"alpha": "A", "beta": "B"}

    def test_dotted_only_returns_the_target_namespace(self) -> None:
        """GH #344: the explicit target wins over a shadowing declared output at root."""
        shared = {
            "__execution__": {"only_node": "process-all.echo"},
            "result": ["upstream", "data"],
            "process-all": {"results": [{"result": "hello", "item": "hello"}], "count": 1},
        }
        outputs = self._result(shared, {"outputs": {"result": {"source": "${upstream.stdout}"}}})
        assert outputs == {"process-all": {"results": [{"result": "hello", "item": "hello"}], "count": 1}}


class TestBatchErrorsSection:
    """``format_batch_errors_section`` — the batch item failures a failed run must show."""

    def _step(self, details: list[dict[str, Any]], *, errors: int | None = None, truncated: int = 0) -> dict[str, Any]:
        return {
            "node_id": "process",
            "is_batch": True,
            "batch_errors": len(details) if errors is None else errors,
            "batch_error_details": details,
            "batch_errors_truncated": truncated,
        }

    def test_header_indices_and_messages(self) -> None:
        lines = format_batch_errors_section([
            self._step([{"index": 1, "error": "Error at 1"}, {"index": 4, "error": "Error at 4"}])
        ])

        assert lines == ["\nBatch 'process' errors:", "  [1] Error at 1", "  [4] Error at 4"]

    def test_capped_with_a_remainder_line(self) -> None:
        details = [{"index": i, "error": f"Error {i}"} for i in range(5)]

        lines = format_batch_errors_section([self._step(details, errors=8, truncated=3)])

        assert lines[-1] == "  ...and 3 more errors"

    def test_nothing_for_a_clean_batch_or_a_plain_step(self) -> None:
        assert format_batch_errors_section([self._step([], errors=0)]) == []
        assert format_batch_errors_section([{"node_id": "regular", "status": "failed"}]) == []

    def test_large_item_is_summarized_not_dumped(self) -> None:
        detail = {
            "index": 0,
            "item": {"label": "oversized-item", "payload": _PAYLOAD},
            "item_summary": {"summary": _ITEM_SUMMARY["summary"], "sha256": "123456789abc"},
            "error": "forced batch failure",
        }

        rendered = "\n".join(format_batch_errors_section([self._step([detail])]))

        assert "[0] forced batch failure" in rendered
        assert "item: label='oversized-item'; payload=<str" in rendered
        assert "PAYLOAD-START" not in rendered
        assert "'payload':" not in rendered


class TestErrorMessageTruncation:
    def test_short_message_unchanged(self) -> None:
        assert _truncate_error_message("Command failed with exit code 1") == "Command failed with exit code 1"

    def test_long_message_cut_at_200_keeping_its_start(self) -> None:
        result = _truncate_error_message("Important error: " + "x" * 300)

        assert len(result) == 200
        assert result.startswith("Important error:")
        assert result.endswith("...")

    def test_multiline_message_uses_its_headline(self) -> None:
        message = "RuntimeError: forced batch failure\n  Location: line 45\nSuggestions:\n  - Fix it"

        assert _truncate_error_message(message) == "RuntimeError: forced batch failure"
