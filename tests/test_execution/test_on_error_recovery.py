"""Tests for on-error recovery status and diagnostics (GH #246).

When a node fails and is recovered via on-error routing, the workflow
must report DEGRADED status (not SUCCESS) with a WARNING diagnostic
describing the recovery. Tests run through WorkflowRunner().run() to
exercise the full pipeline: engine step 17.5 → mark_node_failed →
__warnings__ → _determine_status → _extract_runtime_warnings.
"""

from pflow.core.diagnostic import Diagnostic, Severity, normalize_runtime_warning
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


def _on_error_recovery_ir() -> dict:
    """Shell node that fails, recovered by an on-error handler."""
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "will-fail",
                "type": "shell",
                "purpose": "Node that always fails by design.",
                "params": {"command": "exit 1"},
            },
            {
                "id": "recovery",
                "type": "shell",
                "purpose": "Error handler that recovers the failure.",
                "params": {"command": 'echo "recovered"'},
            },
        ],
        "edges": [
            {"from": "will-fail", "to": "recovery", "action": "error"},
        ],
        "start_node": "will-fail",
    }


def test_on_error_recovery_reports_degraded_status():
    """A workflow that recovers via on-error must report DEGRADED, not SUCCESS."""
    result = WorkflowRunner().run(_on_error_recovery_ir(), {}, config=RunnerConfig())

    assert result.success is True, "Workflow should still be successful"
    assert result.status == WorkflowStatus.DEGRADED, f"Expected DEGRADED for on-error recovery, got {result.status}"


def test_recovered_resource_pattern_failure_renders_as_recovery_not_api_warning(tmp_path):
    """GH #474: a recovered failure whose error text matches an api_warning pattern
    must render as on_error_recovery, not api_warning.

    copy-file with a missing source fails with "...does not exist..." (matches the
    detector's "not found"/"does not exist" pattern) and returns action "error".
    Pre-fix, the detector hijacked it into an api_warning, never reaching step 17.5's
    on_error_recovery handling. After action-gating the detector, the error action is
    the node's authoritative verdict → recovery via the on-error handler.
    """
    missing = tmp_path / "nope.txt"  # never created
    dest = tmp_path / "dest.txt"
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "copy-missing",
                "type": "copy-file",
                "purpose": "Copy a file whose source is missing, to trigger a failure.",
                "params": {"source_path": str(missing), "dest_path": str(dest)},
                "retry": {"max": 1, "wait": 0},
            },
            {
                "id": "handler",
                "type": "shell",
                "purpose": "On-error handler that recovers the copy failure.",
                "params": {"command": "echo recovered"},
            },
        ],
        "edges": [{"from": "copy-missing", "to": "handler", "action": "error"}],
        "start_node": "copy-missing",
    }

    result = WorkflowRunner().run(ir, {}, config=RunnerConfig())

    assert result.status == WorkflowStatus.DEGRADED, f"Expected DEGRADED recovery, got {result.status}"
    shared = result.shared_after

    # The recovered failure is classified as recovery, NOT api_warning.
    _message, context = normalize_runtime_warning(shared["__warnings__"]["copy-missing"])
    assert context["type"] == "on_error_recovery", (
        f"Expected on_error_recovery, got {context['type']!r} — detector relabelled the failure"
    )

    # Positive category assertion: copy-file is absent from _NODE_TYPE_FAILURE_CATEGORY,
    # so it falls back to node_action_error (stronger than just "not api_warning").
    assert shared["__failures__"]["copy-missing"]["category"] == "node_action_error"


def test_on_error_recovery_produces_warning_diagnostic():
    """The recovery diagnostic must name the failed node and handler."""
    result = WorkflowRunner().run(_on_error_recovery_ir(), {}, config=RunnerConfig())

    recovery_diags = [
        d
        for d in result.diagnostics
        if d.severity == Severity.WARNING and d.context and d.context.get("type") == "on_error_recovery"
    ]
    assert len(recovery_diags) == 1, (
        f"Expected exactly one recovery diagnostic, got {len(recovery_diags)}: {result.diagnostics}"
    )

    diag = recovery_diags[0]
    assert diag.node_id == "will-fail"
    assert "will-fail" in diag.message
    assert "recovery" in diag.message
    assert diag.context["category"] == "shell_failure"


def test_recovery_diagnostic_has_no_misleading_suggestions():
    """Recovery diagnostics must not suggest 'add error handling' — it already has it."""
    result = WorkflowRunner().run(_on_error_recovery_ir(), {}, config=RunnerConfig())

    recovery_diags = [d for d in result.diagnostics if d.context and d.context.get("type") == "on_error_recovery"]
    assert recovery_diags, "Should have at least one recovery diagnostic"

    for diag in recovery_diags:
        assert not diag.suggestions, f"Recovery diagnostic should have no suggestions, got: {diag.suggestions}"


def test_clean_workflow_still_reports_success():
    """Regression guard: a workflow with no failures must report SUCCESS."""
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "greet",
                "type": "shell",
                "purpose": "Simple echo that always succeeds.",
                "params": {"command": 'echo "hello"'},
            },
        ],
        "start_node": "greet",
    }
    result = WorkflowRunner().run(ir, {}, config=RunnerConfig())

    assert result.success is True
    assert result.status == WorkflowStatus.SUCCESS


def test_node_failure_without_on_error_still_fails():
    """Regression guard: a node failure with no handler must report FAILED."""
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "will-fail",
                "type": "shell",
                "purpose": "Node that always fails, no error handler.",
                "params": {"command": "exit 1"},
            },
        ],
        "start_node": "will-fail",
    }
    result = WorkflowRunner().run(ir, {}, config=RunnerConfig())

    assert result.success is False
    assert result.status == WorkflowStatus.FAILED


def test_multiple_on_error_recoveries_all_surface():
    """When two nodes fail and recover via separate handlers, both produce diagnostics."""
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "fail-a",
                "type": "shell",
                "purpose": "First node that fails by design.",
                "params": {"command": "exit 1"},
            },
            {
                "id": "handler-a",
                "type": "shell",
                "purpose": "Error handler for fail-a node.",
                "params": {"command": 'echo "recovered-a"'},
            },
            {
                "id": "fail-b",
                "type": "shell",
                "purpose": "Second node that fails by design.",
                "params": {"command": "exit 2"},
            },
            {
                "id": "handler-b",
                "type": "shell",
                "purpose": "Error handler for fail-b node.",
                "params": {"command": 'echo "recovered-b"'},
            },
        ],
        "edges": [
            {"from": "fail-a", "to": "handler-a", "action": "error"},
            {"from": "handler-a", "to": "fail-b", "action": "default"},
            {"from": "fail-b", "to": "handler-b", "action": "error"},
        ],
        "start_node": "fail-a",
    }
    result = WorkflowRunner().run(ir, {}, config=RunnerConfig())

    assert result.success is True
    assert result.status == WorkflowStatus.DEGRADED

    recovery_diags = [d for d in result.diagnostics if d.context and d.context.get("type") == "on_error_recovery"]
    assert len(recovery_diags) == 2, f"Expected 2 recovery diagnostics, got {len(recovery_diags)}: {result.diagnostics}"

    recovered_nodes = {d.node_id for d in recovery_diags}
    assert recovered_nodes == {"fail-a", "fail-b"}


def test_api_warning_not_classified_as_recovery():
    """Regression guard: api_warning entries must retain api_warning type, not on_error_recovery."""
    runner = WorkflowRunner()
    shared = {
        "__warnings__": {"api-node": "API error (404): Not Found"},
        "__failures__": {
            "api-node": {
                "data": {},
                "category": "api_warning",
                "error": "API error (404): Not Found",
                "warning": "API error (404): Not Found",
            },
        },
    }
    diagnostics = runner._extract_runtime_warnings(shared)

    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.context["type"] == "api_warning", (
        f"api_warning should keep api_warning type, got {diag.context['type']}"
    )
    assert diag.suggestions, "api_warning should have suggestions"


def test_sub_workflow_recovery_classified_correctly_without_failures():
    """When a child sub-workflow recovers via on-error, __warnings__ propagates
    to the parent as a producer-built Diagnostic while __failures__ stays in
    child scope."""
    runner = WorkflowRunner()
    recovery_warning = Diagnostic(
        severity=Severity.WARNING,
        message="Node 'child-node' failed \u2014 on-error \u2192 'handler'",
        node_id="child-node",
        source="runtime",
        context={"type": "on_error_recovery", "category": "node_action_error"},
    )
    shared = {
        "__warnings__": {
            "child-node": recovery_warning,
        },
        # No __failures__ entry — child's __failures__ didn't propagate
    }
    diagnostics = runner._extract_runtime_warnings(shared)

    recovery_diags = [d for d in diagnostics if d.context and d.context.get("type") == "on_error_recovery"]
    assert len(recovery_diags) == 1, f"Sub-workflow recovery should preserve propagated Diagnostic, got: {diagnostics}"
    assert recovery_diags[0].node_id == "child-node"
    assert recovery_diags[0].context.get("category") == "node_action_error"
    assert not recovery_diags[0].suggestions, "Recovery diagnostic should have no suggestions"
