"""End-to-end tests for the failed-node invariant fix (GH #208)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner

EXAMPLES_ERROR_HANDLING = Path(__file__).parent.parent.parent / "examples" / "error-handling"


def _coalesce_repro_ir() -> dict:
    """Build the GH #208 reproduction IR."""
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "primary",
                "type": "shell",
                "purpose": "Primary node that fails by design.",
                "params": {"command": "exit 1"},
            },
            {
                "id": "fallback",
                "type": "shell",
                "purpose": "Fallback node providing alternative output.",
                "params": {"command": 'echo "fallback-content"'},
            },
        ],
        "edges": [
            {"from": "primary", "to": "fallback", "action": "error"},
        ],
        "start_node": "primary",
        "outputs": {
            "content": {
                "description": "Whichever path produced output.",
                "source": "${primary.stdout ?? fallback.stdout}",
            },
        },
    }


def test_coalesce_falls_through_to_fallback_on_primary_failure():
    runner = WorkflowRunner()
    result = runner.run(_coalesce_repro_ir(), {}, config=RunnerConfig())

    assert result.success, f"Workflow should succeed via on-error fallback: {result.diagnostics}"
    assert result.shared_after.get("content") == "fallback-content"


def test_failed_primary_data_is_archived_to_failures():
    runner = WorkflowRunner()
    result = runner.run(_coalesce_repro_ir(), {}, config=RunnerConfig())

    shared = result.shared_after
    assert "primary" not in shared
    assert "__failures__" in shared
    assert "primary" in shared["__failures__"]
    record = shared["__failures__"]["primary"]
    assert record["category"] in ("shell_failure", "node_action_error")
    assert record["data"]["exit_code"] == 1


def test_direct_reference_to_failed_node_produces_structured_error():
    ir = _coalesce_repro_ir()
    ir["outputs"]["content"]["source"] = "${primary.stdout}"

    runner = WorkflowRunner()
    result = runner.run(ir, {}, config=RunnerConfig())

    error_diags = [diag for diag in result.diagnostics if diag.severity.value == "error"]
    assert error_diags, f"Should have at least one error diagnostic. Got: {result.diagnostics}"

    combined_text = " ".join(f"{diag.message} {diag.context or ''}" for diag in error_diags).lower()
    assert "primary" in combined_text
    assert any(diag.context and diag.context.get("category") == "template_error" for diag in error_diags)


def test_trace_captures_failed_node_data():
    runner = WorkflowRunner()
    result = runner.run(_coalesce_repro_ir(), {}, config=RunnerConfig())

    assert result.trace is not None
    events = result.trace.events
    primary_event = next((event for event in events if event.get("node_id") == "primary"), None)
    assert primary_event is not None
    assert primary_event.get("success") is False
    output = primary_event.get("node_output") or {}
    assert output.get("exit_code") == 1
    assert output.get("command") == "exit 1"


def _all_failed_coalesce_ir() -> dict:
    """IR where an output coalesce references TWO failed nodes.

    primary fails → routes via on-error to fallback. fallback also fails →
    routes via on-error to soak so the workflow completes and output
    resolution runs. The output declaration ``${primary.stdout ?? fallback.stdout}``
    has both operands in ``__failures__`` when populate_declared_outputs runs.
    Pre-fix, the gate in output_resolver.py:168-172 silently skipped this case
    (workflow "succeeded" with no output); post-fix it raises a structured
    OutputResolutionError.
    """
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "primary",
                "type": "shell",
                "purpose": "Primary fails with exit 7.",
                "params": {"command": "exit 7"},
            },
            {
                "id": "fallback",
                "type": "shell",
                "purpose": "Fallback also fails with exit 5.",
                "params": {"command": "exit 5"},
            },
            {
                "id": "soak",
                "type": "shell",
                "purpose": "Soak absorbs the second failure so outputs run.",
                "params": {"command": 'echo "soaked"'},
            },
        ],
        "edges": [
            {"from": "primary", "to": "fallback", "action": "error"},
            {"from": "fallback", "to": "soak", "action": "error"},
        ],
        "start_node": "primary",
        "outputs": {
            "content": {
                "description": "Coalesced output — should error when both fail.",
                "source": "${primary.stdout ?? fallback.stdout}",
            },
        },
    }


def test_all_failed_coalesce_in_output_raises_structured_error():
    """Regression for BUG #1: output_resolver.py silently skipped all-failed coalesce.

    Spec requirement (task-148.md): "${primary.stdout ?? fallback.stdout} where
    both failed produces a structured error". Pre-fix the gate skipped any
    unresolved coalesce, conflating "all absent (branch not taken)" with "all
    failed (recovery failed)".
    """
    runner = WorkflowRunner()
    result = runner.run(_all_failed_coalesce_ir(), {}, config=RunnerConfig())

    # Must NOT silently succeed
    assert not result.success, "All-failed coalesce in output must error, not silently drop the output"
    assert "content" not in result.shared_after, "Output must not be populated when all coalesce operands failed"

    # Must have a structured template_error diagnostic
    error_diags = [d for d in result.diagnostics if d.severity.value == "error"]
    assert error_diags, f"Expected template error diagnostic, got: {result.diagnostics}"

    template_errors = [d for d in error_diags if d.context and d.context.get("category") == "template_error"]
    assert template_errors, (
        f"Expected category='template_error', got categories: "
        f"{[d.context.get('category') if d.context else None for d in error_diags]}"
    )

    # Structured refs must classify BOTH operands as failed, preserving
    # category/exit_code/command so agents can diagnose without parsing strings.
    diag = template_errors[0]
    refs = diag.context.get("unresolved_references") or []
    assert len(refs) == 2, f"Expected 2 unresolved refs (both operands), got {len(refs)}"
    statuses = {ref.get("var"): ref.get("status") for ref in refs}
    assert statuses.get("primary.stdout") == "failed"
    assert statuses.get("fallback.stdout") == "failed"

    # Per-operand failure details must be present for agent consumption
    for ref in refs:
        failure = ref.get("failure") or {}
        assert failure.get("category") == "shell_failure"
        assert failure.get("exit_code") in (5, 7)


def test_mixed_absent_and_failed_coalesce_in_output_raises_error():
    """Regression: mixed absent+failed coalesce must not be silently skipped.

    ``${absent.x ?? failed.y}`` — one operand is ABSENT (branch not taken),
    the other is FAILED. Pre-fix, the gate skipped ALL unresolved coalesce
    and treated this the same as all-absent. Post-fix, any FAILED operand
    forces an error.
    """
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "chooser",
                "type": "shell",
                "purpose": "Branches to fails, not to never_run.",
                "params": {"command": 'echo "go"'},
            },
            {
                "id": "never_run",
                "type": "shell",
                "purpose": "Never executes — branch not taken.",
                "params": {"command": 'echo "never"'},
            },
            {
                "id": "fails",
                "type": "shell",
                "purpose": "Fails with exit 9.",
                "params": {"command": "exit 9"},
            },
            {
                "id": "soak",
                "type": "shell",
                "purpose": "Absorbs the failure so outputs run.",
                "params": {"command": 'echo "soaked"'},
            },
        ],
        "edges": [
            {"from": "chooser", "to": "fails"},
            {"from": "fails", "to": "soak", "action": "error"},
        ],
        "start_node": "chooser",
        "outputs": {
            "content": {
                "description": "Coalesce across an absent and a failed node.",
                "source": "${never_run.stdout ?? fails.stdout}",
            },
        },
    }

    runner = WorkflowRunner()
    result = runner.run(ir, {}, config=RunnerConfig())

    assert not result.success, (
        "Mixed absent+failed coalesce must error; one failed operand is not "
        "a legitimate Task 128 branch-convergence fallthrough"
    )
    error_diags = [d for d in result.diagnostics if d.severity.value == "error"]
    template_errors = [d for d in error_diags if d.context and d.context.get("category") == "template_error"]
    assert template_errors, "Expected a template_error diagnostic"

    refs = template_errors[0].context.get("unresolved_references") or []
    statuses = {ref.get("var"): ref.get("status") for ref in refs}
    assert statuses.get("never_run.stdout") == "absent"
    assert statuses.get("fails.stdout") == "failed"


def test_all_absent_coalesce_in_output_is_silently_skipped():
    """Positive regression: Task 128 all-absent coalesce must still silently skip.

    This is the branch-convergence use-case the gate was originally intended to
    serve. The BUG #1 fix preserves it — only all-ABSENT skips silently, while
    any FAILED or PATH_ERROR forces an error.
    """
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "chooser",
                "type": "shell",
                "purpose": "Routes to branch_a only.",
                "params": {"command": 'echo "choose"'},
            },
            {
                "id": "branch_a",
                "type": "shell",
                "purpose": "Taken branch.",
                "params": {"command": 'echo "a-result"'},
            },
            {
                "id": "branch_b",
                "type": "shell",
                "purpose": "Untaken branch — legitimately absent.",
                "params": {"command": 'echo "b-result"'},
            },
        ],
        "edges": [
            {"from": "chooser", "to": "branch_a"},
        ],
        "start_node": "chooser",
        "outputs": {
            "only_b": {
                "description": "References only the untaken branch via coalesce.",
                "source": "${branch_b.stdout ?? branch_b.other}",
            },
        },
    }

    runner = WorkflowRunner()
    result = runner.run(ir, {}, config=RunnerConfig())

    # All-absent coalesce → silent skip → workflow succeeds, output missing
    assert result.success, f"All-absent coalesce should silently skip, not error. Diagnostics: {result.diagnostics}"
    assert "only_b" not in result.shared_after


def test_shell_error_without_on_error_preserves_shell_data_in_failure_record():
    """Regression for post-review Fix #2: routing double-archive was losing shell data.

    A shell node that returns "error" action with no matching error successor
    edge is handled by ``_handle_no_successor``. Pre-fix, that path called
    ``mark_node_failed`` a second time, which popped an already-empty
    ``shared[node_id]`` and overwrote the full shell failure record
    (exit_code, stderr, command, category=shell_failure) with an empty-data
    ``routing_error`` record. Post-fix, the existing record is preserved and
    only the routing warning is added to ``__warnings__``.
    """
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "broken",
                "type": "shell",
                "purpose": "Shell that fails with exit 1 and no on-error handler.",
                "params": {"command": 'echo "from stderr" >&2; exit 1'},
            },
            {
                "id": "next_step",
                "type": "shell",
                "purpose": "Downstream step that should not run.",
                "params": {"command": 'echo "should-not-run"'},
            },
        ],
        "edges": [{"from": "broken", "to": "next_step"}],
        "start_node": "broken",
    }

    runner = WorkflowRunner()
    result = runner.run(ir, {}, config=RunnerConfig())

    assert not result.success, "Workflow should fail when shell exits 1 without on-error"
    shared = result.shared_after
    failure = shared["__failures__"]["broken"]

    # Rich shell data must survive the _handle_no_successor second pass
    assert failure["category"] == "shell_failure", (
        f"Expected shell_failure, got {failure['category']!r} — routing path overwrote category"
    )
    data = failure["data"]
    assert data.get("exit_code") == 1, f"Expected exit_code=1 in preserved data, got: {data}"
    assert data.get("command") == 'echo "from stderr" >&2; exit 1'
    assert "from stderr" in data.get("stderr", "")

    # No routing hint is written for a terminal node failure (GH #437): the real
    # shell failure already stands on its own in __failures__, so a generic
    # "add on-error" hint would only outrank the real fix and train agents to route
    # the failure instead of fixing its cause.
    warnings = shared.get("__warnings__", {})
    assert "broken" not in warnings, (
        f"Terminal node failure should not emit a routing hint, got: {warnings.get('broken')!r}"
    )

    # The user-visible top-line error message must be the authoritative shell
    # failure. (Historically _handle_no_successor wrote a "no successor edge
    # matches" routing hint to __warnings__ that, when given priority, masked the
    # real "Command failed with exit code 1"; GH #437 stopped writing that hint
    # for error-action nodes, so the shell failure is now the only signal.)
    errors = [d for d in result.diagnostics if d.severity == Severity.ERROR]
    assert errors, "Expected at least one ERROR diagnostic for the failed workflow"
    primary_error = errors[0]
    assert "exit code 1" in primary_error.message.lower() or "command failed" in primary_error.message.lower(), (
        f"Primary error message should surface the shell failure, got: {primary_error.message!r}"
    )
    assert "no successor edge matches" not in primary_error.message, (
        f"Primary error message should not be the routing hint, got: {primary_error.message!r}"
    )


def test_output_resolution_error_does_not_inherit_stale_failed_node():
    """Regression for post-review Fix #3: OutputResolutionError used to inherit the
    stale ``__execution__["failed_node"]`` pointer from an already-handled failure,
    causing the diagnostic ``At:`` line to point at the wrong node.

    Setup: a router branches to branch-a, leaving branch-b absent at runtime.
    The output references branch-b via a non-coalesce source — populates_declared_outputs
    raises OutputResolutionError at the end of the engine. Pre-fix, the runner's
    exception handler would attach ``__execution__['failed_node']`` (which is None
    here, but in a more complex scenario could be stale from a prior on-error
    recovery). Post-fix, OutputResolutionError is explicitly excluded from the
    stale-pointer annotation.
    """
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "router",
                "type": "code",
                "purpose": "Route to branch-a so branch-b stays absent at runtime.",
                "params": {"code": 'next: str = "branch-a"'},
            },
            {
                "id": "branch-a",
                "type": "shell",
                "purpose": "The taken branch.",
                "params": {"command": 'echo "a-ran"'},
            },
            {
                "id": "branch-b",
                "type": "shell",
                "purpose": "The untaken branch — absent at runtime.",
                "params": {"command": 'echo "b-ran"'},
            },
        ],
        "edges": [
            {"from": "router", "to": "branch-a", "action": "branch-a"},
            {"from": "router", "to": "branch-b", "action": "branch-b"},
        ],
        "start_node": "router",
        # Non-coalesce reference to branch-b (absent at runtime) triggers
        # OutputResolutionError in populate_declared_outputs. Validation lets
        # this through because branch-b is a declared node.
        "outputs": {"content": {"source": "${branch-b.stdout}"}},
    }

    runner = WorkflowRunner()
    result = runner.run(ir, {}, config=RunnerConfig())

    assert not result.success
    error_diags = [d for d in result.diagnostics if d.severity.value == "error"]
    assert error_diags, f"Expected at least one error diagnostic, got: {result.diagnostics}"

    output_err = next(
        (d for d in error_diags if d.context and d.context.get("is_output_resolution")),
        None,
    )
    assert output_err is not None, (
        f"Expected an output-resolution error diagnostic, got: {[(d.source, d.title) for d in error_diags]}"
    )
    # Must not inherit stale failed_node (this is the regression being guarded)
    assert output_err.node_id is None, (
        f"Output error must not inherit stale failed_node, got node_id={output_err.node_id!r}"
    )
    # The real culprit (branch-b) appears in structured refs
    refs = output_err.context.get("unresolved_references") or []
    assert any(r.get("root") == "branch-b" for r in refs)


def test_output_resolution_error_does_not_triple_render():
    """Regression for post-review Fix #1: OutputResolutionError rendered the same
    error 3x (legacy prose + structured block + canned suggestions). Post-fix,
    the rendered text has one structured block, no canned trailing suggestion,
    and a one-line summary message (no multi-line legacy prose).
    """
    from pflow.core.diagnostic import exception_to_diagnostics
    from pflow.core.diagnostic_render import format_diagnostic
    from pflow.core.user_errors import OutputResolutionError

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "primary",
                "type": "shell",
                "purpose": "Primary fails so the output-source reference fails to resolve.",
                "params": {"command": 'echo "err" >&2; exit 7'},
            },
            {
                "id": "fallback",
                "type": "shell",
                "purpose": "Peer node for paste-able fix suggestion.",
                "params": {"command": 'echo "ok"'},
            },
        ],
        "edges": [{"from": "primary", "to": "fallback", "action": "error"}],
        "start_node": "primary",
        "outputs": {"content": {"source": "${primary.stdout}"}},
    }

    runner = WorkflowRunner()
    result = runner.run(ir, {}, config=RunnerConfig())

    # The runner converts the exception to a diagnostic; pull it back out.
    output_err = next(
        (d for d in result.diagnostics if d.context and d.context.get("is_output_resolution")),
        None,
    )
    assert output_err is not None

    # Message is a one-line summary, not multi-line legacy prose
    assert "\n" not in output_err.message
    assert output_err.message.startswith("Unresolved variables in output")

    # No canned suggestions — the structured renderer provides per-ref fixes
    assert output_err.suggestions is None

    rendered = format_diagnostic(output_err)
    # Legacy prose line must NOT appear
    assert "Output 'content' (source: " not in rendered
    # Legacy canned suggestion must NOT appear
    assert "Check that source expressions reference nodes" not in rendered
    # Structured block IS present
    assert "In output 'content':" in rendered
    assert "${primary.stdout}" in rendered
    # Paste-able peer suggestion uses a real node name
    assert "${primary.stdout ?? fallback.stdout}" in rendered

    # Also verify the direct construction path (unit-level)
    failures = [
        {
            "output_name": "content",
            "source_expr": "${primary.stdout}",
            "template": "${primary.stdout}",
            "unresolved_references": [
                {
                    "var": "primary.stdout",
                    "root": "primary",
                    "status": "absent",
                    "in_coalesce": False,
                    "coalesce_expr": None,
                    "peer_suggestions": [],
                }
            ],
            "available_context_keys": [],
        }
    ]
    err = OutputResolutionError(failures=failures)
    diags = exception_to_diagnostics(err)
    assert len(diags) == 1
    assert diags[0].node_id is None
    assert diags[0].suggestions is None


def test_all_failed_batch_preserves_batch_metadata_in_failures():
    """Regression for Fix A2: ``_aggregate_batch_results`` used to raise BEFORE
    writing ``shared[node_id]``, so step 17.5 archived an empty-data failure
    record and ``build_execution_steps`` couldn't surface ``batch_error_details``
    for the failing batch node. Post-fix, the shared store write happens first
    so step 17.5 captures the full ``batch_metadata`` + ``errors`` list.

    Also exercises the shared_store threading fix: ``_exception_to_result`` now
    surfaces ``__failures__`` via ``ExecutionResult.shared_after`` so this test
    can inspect the failure record through the public ``WorkflowRunner`` API.
    """
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "all_fail",
                "type": "shell",
                "purpose": "Batch node where every item exits non-zero.",
                "params": {"command": "exit 1"},
                "batch": {
                    "items": [1, 2, 3],
                    "error_handling": "continue",
                },
            },
        ],
        "edges": [],
        "start_node": "all_fail",
    }

    result = WorkflowRunner().run(ir, {}, config=RunnerConfig())

    assert not result.success
    # Shared store is now threaded through the exception path
    failure = result.shared_after.get("__failures__", {}).get("all_fail")
    assert failure is not None, (
        "Expected failed batch node to have a __failures__ record in shared_after "
        "(regression: runner's exception path used to drop shared_store)"
    )

    data = failure.get("data") or {}
    # Pre-fix this was {}. Post-fix it has the full batch output shape.
    assert "batch_metadata" in data, (
        f"Expected batch_metadata to survive the failure archive, got data keys: {list(data.keys())}"
    )
    assert data.get("count") == 3
    assert data.get("error_count") == 3
    assert data.get("success_count") == 0
    assert data.get("errors") is not None, "errors list must be preserved for display"
    assert len(data["errors"]) == 3


def test_fail_fast_batch_preserves_batch_metadata_in_failures():
    """Regression for Fix A2 fail_fast path: ``_execute_sequential`` and
    ``_execute_parallel`` used to raise on first failure BEFORE aggregation.
    Post-fix, the loops break-not-raise and ``execute_batch`` owns the
    fail_fast raise AFTER ``_aggregate_batch_results`` writes the shared store.
    The partial batch metadata (items 0..first_failure + the failure itself)
    must survive into ``__failures__`` so the CLI summary can show it.
    """
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "fail_fast_batch",
                "type": "shell",
                "purpose": "Batch where item 1 fails; fail_fast stops at first failure.",
                # Use item value in the command so each item executes differently.
                # Items 0 and 2 succeed; item 1 fails with exit 9.
                "params": {"command": 'test "${item}" != "boom" || exit 9'},
                "batch": {
                    "items": ["ok0", "boom", "ok2"],
                    "error_handling": "fail_fast",
                },
            },
        ],
        "edges": [],
        "start_node": "fail_fast_batch",
    }

    result = WorkflowRunner().run(ir, {}, config=RunnerConfig())

    assert not result.success
    failure = result.shared_after.get("__failures__", {}).get("fail_fast_batch")
    assert failure is not None, "fail_fast batch must archive a failure record"

    data = failure.get("data") or {}
    assert "batch_metadata" in data, (
        f"fail_fast must preserve batch_metadata in the failure record, got: {list(data.keys())}"
    )
    # Sequential fail_fast stops at the failing item, so we expect 2 items
    # processed: ok0 (success) + boom (error). Subsequent items are skipped.
    assert data.get("count") == 2
    assert data.get("error_count") == 1
    assert data.get("errors") is not None
    assert len(data["errors"]) == 1
    # The failing item's error details are preserved
    failing_error = data["errors"][0]
    assert failing_error.get("index") == 1
    assert "boom" in str(failing_error.get("item", ""))


def test_large_item_fail_fast_batch_preserves_full_item_with_compact_summary():
    payload = "PAYLOAD-START " + " ".join(f"token{i}" for i in range(200)) + " PAYLOAD-END"
    large_item = {"label": "oversized-item", "payload": payload}
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "fail_fast_batch",
                "type": "shell",
                "purpose": "Fail one oversized batch item.",
                "params": {"command": 'echo "forced batch failure for ${item.label}" >&2; exit 1'},
                "batch": {
                    "items": [large_item],
                    "error_handling": "fail_fast",
                },
            },
        ],
        "edges": [],
        "start_node": "fail_fast_batch",
    }

    result = WorkflowRunner().run(ir, {}, config=RunnerConfig())

    assert result.success is False
    failure = result.shared_after["__failures__"]["fail_fast_batch"]
    error = failure["data"]["errors"][0]
    assert error["item"] == large_item
    assert error["item_summary"]["label"] == "oversized-item"
    assert "payload=<str" in error["item_summary"]["summary"]
    assert "PAYLOAD-START" not in result.errors[0].message
    assert "PAYLOAD-END" not in result.errors[0].message
    assert "token199" not in result.errors[0].message


def test_failed_batch_surfaces_error_details_in_execution_steps():
    """End-to-end spec acceptance test — guards the 4-layer pipeline that
    produces ``batch_error_details`` in the CLI/MCP execution summary for a
    failing batch. Each of these layers has broken at some point in this work:

    1. ``_aggregate_batch_results`` writes ``shared[node_id]`` BEFORE raising (A2)
    2. Step 17.5 archives to ``__failures__[id].data`` via ``mark_node_failed``
    3. ``_exception_to_result`` threads ``shared_store`` into ``ExecutionResult.shared_after`` (#5)
    4. ``build_execution_steps`` reads via ``get_node_output`` and emits ``batch_error_details``
       (BUG #2 post-completion — had used stale singular ``failed_node`` pointer)

    A regression in ANY link silently breaks the task-148 acceptance criterion
    *"Failed batch nodes show batch_error_details in execution summary"*.
    Tests the entire chain through the public ``WorkflowRunner`` API, which is
    what CLI and MCP consumers actually use.
    """
    from pflow.execution.execution_state import build_execution_steps

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "failing_batch",
                "type": "shell",
                "purpose": "Batch where every item exits non-zero.",
                "params": {"command": "exit 1"},
                "batch": {
                    "items": ["alpha", "beta", "gamma"],
                    "error_handling": "continue",
                },
            },
        ],
        "edges": [],
        "start_node": "failing_batch",
    }

    result = WorkflowRunner().run(ir, {}, config=RunnerConfig())
    assert not result.success

    # Run the CLI/MCP formatter entry point against the actual ExecutionResult
    metrics_summary = result.metrics.get_summary() if result.metrics else None
    steps = build_execution_steps(ir, result.shared_after, metrics_summary)

    assert len(steps) == 1, "Expected one step row for the batch node"
    step = steps[0]

    # Status comes from get_node_status which reads __failures__
    assert step["node_id"] == "failing_batch"
    assert step["status"] == "failed", f"Expected status='failed' from get_node_status, got: {step['status']}"

    # Batch metadata must survive the exception path → shared_after → get_node_output chain
    assert step.get("is_batch") is True, (
        f"Expected is_batch=True — failure archive dropped batch_metadata. Step: {step}"
    )
    assert step.get("batch_total") == 3
    assert step.get("batch_success") == 0
    assert step.get("batch_errors") == 3

    # Error details list is the agent-facing payload — must be populated
    error_details = step.get("batch_error_details")
    assert error_details, (
        f"Expected batch_error_details to be populated — this is the spec acceptance criterion. "
        f"Step keys: {list(step.keys())}"
    )
    assert len(error_details) == 3
    # Each error has index + item identifying which batch item failed
    assert {e.get("index") for e in error_details} == {0, 1, 2}


def test_template_error_shows_both_succeeded_and_failed_peers_in_context():
    """Regression for Fix B3: the "Available nodes in context:" block must
    render BOTH succeeded and failed peers (with ``(failed)`` marker) so an
    agent reading the error can distinguish "node doesn't exist" from "node
    failed and was archived to __failures__".
    """
    from pflow.core.diagnostic_render import format_diagnostic
    from pflow.runtime.engine.template_errors import build_template_error_diagnostic
    from pflow.runtime.node_state import FAILURE_CATEGORY_SHELL, mark_node_failed

    shared = {
        "alpha": {"stdout": "ok"},  # succeeded peer
        "beta": {"stdout": ""},  # another succeeded peer
        "gamma_failed": {"stdout": "", "exit_code": 2, "command": "exit 2"},
        "__execution__": {
            "completed_nodes": ["alpha", "beta"],
            "node_actions": {"alpha": "default", "beta": "default"},
            "node_hashes": {},
            "failed_node": None,
            "node_visit_counts": {},
        },
    }
    # Archive gamma_failed via the canonical helper
    mark_node_failed(
        shared,
        "gamma_failed",
        category=FAILURE_CATEGORY_SHELL,
        error="Command failed with exit code 2",
    )

    # Build a diagnostic referencing a completely missing node
    diag = build_template_error_diagnostic(
        "command",
        "${missing_ref.stdout}",
        shared,
    )

    # Structured context exposes both lists
    assert "alpha" in diag.context["available_context_keys"]
    assert "beta" in diag.context["available_context_keys"]
    assert "gamma_failed" in diag.context["failed_context_keys"]
    assert "gamma_failed" not in diag.context["available_context_keys"]

    rendered = format_diagnostic(diag)
    # Succeeded peers render cleanly
    assert "- alpha" in rendered
    assert "- beta" in rendered
    # Failed peer renders with the (failed) marker so agents know to look at
    # the failure detail block above the context-keys list.
    assert "- gamma_failed (failed" in rendered
    # The user-facing text must NOT leak the internal __failures__ key name.
    assert "__failures__" not in rendered


def test_multi_output_resolution_error_renders_per_output_blocks():
    """Regression: multi-output OutputResolutionError must render one structured
    block per failing output (not join templates with '; ').

    Pre-fix, OutputResolutionError joined failing templates with ``"; "`` (invalid
    pflow syntax) and only propagated source_line/source_file from the first
    failure. Post-fix, each output renders its own ``In output 'X':`` block.
    """
    from pflow.core.diagnostic_render import format_diagnostic
    from pflow.core.user_errors import OutputResolutionError

    workflow_file = "workspace/ws.pflow.md"

    # Hand-built failures mimicking what populate_declared_outputs produces
    # for a two-output workflow where both sources reference absent branches.
    failures = [
        {
            "output_name": "first",
            "source_expr": "${never_a.x}",
            "template": "${never_a.x}",
            "source_file": workflow_file,
            "source_line": 10,
            "unresolved_references": [
                {
                    "var": "never_a.x",
                    "root": "never_a",
                    "status": "absent",
                    "in_coalesce": False,
                    "coalesce_expr": None,
                    "peer_suggestions": [],
                }
            ],
            "available_context_keys": ["taken"],
        },
        {
            "output_name": "second",
            "source_expr": "${never_b.y}",
            "template": "${never_b.y}",
            "source_file": workflow_file,
            "source_line": 20,
            "unresolved_references": [
                {
                    "var": "never_b.y",
                    "root": "never_b",
                    "status": "absent",
                    "in_coalesce": False,
                    "coalesce_expr": None,
                    "peer_suggestions": [],
                }
            ],
            "available_context_keys": ["taken"],
        },
    ]
    err = OutputResolutionError(failures=failures)
    diags = err.to_diagnostics()
    assert len(diags) == 1
    diagnostic = diags[0]

    # Context has one per-output block for each failure
    output_blocks = diagnostic.context.get("output_failures") or []
    assert len(output_blocks) == 2
    assert output_blocks[0]["output_name"] == "first"
    assert output_blocks[0]["source_line"] == 10
    assert output_blocks[1]["output_name"] == "second"
    assert output_blocks[1]["source_line"] == 20

    # Neither source_expr should be joined with "; " in the message
    assert "; " not in diagnostic.message

    rendered = format_diagnostic(diagnostic)
    # Both per-output headers appear
    assert "In output 'first':" in rendered
    assert "In output 'second':" in rendered
    # Both templates rendered separately, not joined
    assert "${never_a.x}" in rendered
    assert "${never_b.y}" in rendered
    # Both source lines visible via the per-output source hint
    assert f"{workflow_file}:10" in rendered
    assert f"{workflow_file}:20" in rendered


def test_step_17_5_maps_http_node_type_to_http_failure_category():
    """Engine step 17.5 maps ``config.node_type_name`` to a failure category
    via a compile-time dict — no data-shape heuristic. Verify the mapping
    exists and the category flows through display extraction and rendering.
    """
    from pflow.core.diagnostic_render import _render_failure_data_block
    from pflow.execution.executor_service import _map_failure_category_to_diagnostic
    from pflow.runtime.engine.engine import _NODE_TYPE_FAILURE_CATEGORY
    from pflow.runtime.engine.template_errors import _extract_failure_display_data
    from pflow.runtime.node_state import FAILURE_CATEGORY_HTTP

    assert _NODE_TYPE_FAILURE_CATEGORY["HttpNode"] == FAILURE_CATEGORY_HTTP

    http_data = {
        "status_code": 503,
        "url": "https://example.test/api",
        "method": "GET",
        "response": "Service Unavailable",
        "error": "HTTP 503",
    }

    display = _extract_failure_display_data(FAILURE_CATEGORY_HTTP, http_data)
    assert display["status_code"] == 503
    assert display["url"] == "https://example.test/api"
    assert display["method"] == "GET"

    rendered = "\n".join(_render_failure_data_block(FAILURE_CATEGORY_HTTP, http_data))
    assert "Status: 503" in rendered
    assert "URL: https://example.test/api" in rendered
    assert "Response: Service Unavailable" in rendered

    assert _map_failure_category_to_diagnostic(FAILURE_CATEGORY_HTTP) == "execution_failure"


def test_step_17_5_maps_mcp_node_type_to_mcp_failure_category():
    """MCP tool errors get ``mcp_failure`` category via the node-type mapping
    so the renderer shows server/tool/details without sniffing data keys."""
    from pflow.core.diagnostic_render import _render_failure_data_block
    from pflow.execution.executor_service import _map_failure_category_to_diagnostic
    from pflow.runtime.engine.engine import _NODE_TYPE_FAILURE_CATEGORY
    from pflow.runtime.engine.template_errors import _extract_failure_display_data
    from pflow.runtime.node_state import FAILURE_CATEGORY_MCP

    assert _NODE_TYPE_FAILURE_CATEGORY["MCPNode"] == FAILURE_CATEGORY_MCP

    mcp_data = {
        "error": "Tool execution failed",
        "error_details": {
            "server": "github",
            "tool": "search_code",
            "is_tool_error": True,
        },
        "server": "github",
        "tool": "search_code",
    }

    display = _extract_failure_display_data(FAILURE_CATEGORY_MCP, mcp_data)
    assert display["server"] == "github"
    assert display["tool"] == "search_code"
    assert display["error_details"]["is_tool_error"] is True

    rendered = "\n".join(_render_failure_data_block(FAILURE_CATEGORY_MCP, mcp_data))
    assert "Server: github" in rendered
    assert "Tool: search_code" in rendered
    assert "Details: {'is_tool_error': True}" in rendered
    assert "Details: {'server':" not in rendered

    protocol_rendered = "\n".join(
        _render_failure_data_block(
            FAILURE_CATEGORY_MCP,
            {
                "error": "MCP tool failed: connection refused",
                "error_details": {
                    "server": "notebooklm",
                    "tool": "studio_create",
                    "timeout": False,
                },
            },
        )
    )
    assert "Server: notebooklm" in protocol_rendered
    assert "Tool: studio_create" in protocol_rendered
    assert "Timeout: False" in protocol_rendered
    assert "Details:" not in protocol_rendered

    diagnostic = Diagnostic(
        severity=Severity.ERROR,
        message="MCP tool failed: Connection closed",
        source="runtime",
        title="Execution Failed",
        node_id="create-audio",
        context={
            "category": "execution_failure",
            "mcp_error_details": {
                "server": "local",
                "tool": "echo_payload",
                "timeout": False,
            },
        },
    )
    runtime_rendered = format_diagnostic(diagnostic)
    assert "MCP Tool:" in runtime_rendered
    assert "Server: local" in runtime_rendered
    assert "Tool: echo_payload" in runtime_rendered

    assert _map_failure_category_to_diagnostic(FAILURE_CATEGORY_MCP) == "execution_failure"


def test_render_failure_data_block_ignores_data_shape_when_category_is_generic():
    """Regression guard: a success output that happens to contain
    ``status_code`` MUST NOT render as an HTTP failure. Dispatch is purely
    by category now — not by data-key sniffing. This is the behavior
    correctness fix that motivated C3.
    """
    from pflow.core.diagnostic_render import _render_failure_data_block

    # Some random node wrote status_code for its own reasons. Category is
    # generic node_action_error (code node that returned "error" action).
    data = {"status_code": 200, "something": "value", "error": "Custom failure"}
    rendered = "\n".join(_render_failure_data_block("node_action_error", data))

    # Renders via the generic path, NOT the HTTP-specific path.
    assert "Status: 200" not in rendered
    assert "URL:" not in rendered
    # The generic renderer surfaces the status_code as a plain key:value pair.
    assert "status_code: 200" in rendered
    assert "something: value" in rendered


def test_loop_reentry_clears_stale_failure_record():
    from pflow.runtime.engine.instrumentation import enforce_loop_guard
    from pflow.runtime.node_state import (
        FAILURE_CATEGORY_SHELL,
        NodeStatus,
        get_node_status,
        mark_node_failed,
    )

    shared = {
        "loopy": {"stdout": "first attempt"},
        "__execution__": {
            "completed_nodes": [],
            "node_actions": {},
            "node_hashes": {},
            "failed_node": None,
            "node_visit_counts": {"loopy": 1},
        },
    }
    mark_node_failed(shared, "loopy", category=FAILURE_CATEGORY_SHELL, error="boom")
    assert get_node_status(shared, "loopy") == NodeStatus.FAILED

    enforce_loop_guard("loopy", shared)
    assert "loopy" not in shared.get("__failures__", {})
    assert get_node_status(shared, "loopy") == NodeStatus.ABSENT


def test_loop_reentry_after_api_warning_reports_success_not_degraded():
    """Regression for code-review finding: loop recovery left stale ``__warnings__``.

    Pre-fix, ``enforce_loop_guard`` cleared ``__failures__`` but not
    ``__warnings__``. A node that failed via an api_warning on visit 1 and
    succeeded on visit 2 would leave its warning mirror behind, and
    ``_determine_status`` would report ``DEGRADED`` even though the workflow
    recovered cleanly. Post-fix, ``clear_node_failure`` clears both dicts.
    """
    from pflow.runtime.engine.instrumentation import enforce_loop_guard
    from pflow.runtime.node_state import FAILURE_CATEGORY_API_WARNING, mark_node_failed

    shared: dict = {
        "api_node": {"error": "Rate limited", "status_code": 429},
        "__execution__": {
            "completed_nodes": [],
            "node_actions": {},
            "node_hashes": {},
            "failed_node": None,
            "node_visit_counts": {"api_node": 1},
        },
    }
    mark_node_failed(
        shared,
        "api_node",
        category=FAILURE_CATEGORY_API_WARNING,
        error="Rate limited",
        warning="API error (429): Rate limited",
    )
    assert "api_node" in shared["__warnings__"]

    # Loop re-entry (visit 2) clears stale state...
    enforce_loop_guard("api_node", shared)
    assert "api_node" not in shared.get("__failures__", {})
    assert "api_node" not in shared.get("__warnings__", {}), (
        "Loop re-entry must clear the stale warning mirror — otherwise the "
        "workflow reports DEGRADED after a clean recovery."
    )

    # ...then visit 2 succeeds.
    shared["api_node"] = {"stdout": "recovered"}

    # _determine_status must now report SUCCESS.
    runner = WorkflowRunner()
    success, status = runner._determine_status("default", shared)
    assert success
    assert status == WorkflowStatus.SUCCESS


def test_output_resolution_error_with_empty_refs_still_renders_output_block():
    """Regression guard for the silent-render gap uncovered during task-148
    simplification review.

    When ``OutputResolutionError`` is constructed with a failure whose
    ``unresolved_references`` list is empty (classifier returned nothing
    but resolution still failed — e.g. a literal self-reference like
    ``shared["foo"] = "${foo}"``), the renderer must still emit the
    structured block with the output name and template — not silently
    collapse to just the one-line Diagnostic.message.

    Caught by the verification pass before deleting
    ``_format_legacy_template_error_lines``.
    """
    from pflow.core.diagnostic_render import format_diagnostic
    from pflow.core.user_errors import OutputResolutionError

    err = OutputResolutionError(
        failures=[
            {
                "output_name": "content",
                "source_expr": "${something}",
                "template": "${something}",
                "unresolved_references": [],
                "available_context_keys": ["foo", "bar"],
                "source_line": 42,
                "source_file": "workflow.pflow.md",
            }
        ]
    )
    rendered = format_diagnostic(err.to_diagnostics()[0])

    # The structured block must appear — the output name and the
    # template the agent tried to resolve.
    assert "In output 'content':" in rendered, f"missing structured block in:\n{rendered}"
    assert "${something}" in rendered, f"missing template preview in:\n{rendered}"
    # Source location must render for agent navigation.
    assert "workflow.pflow.md:42" in rendered, f"missing source location in:\n{rendered}"


# ---------------------------------------------------------------------------
# End-to-end fixtures under examples/error-handling/
# ---------------------------------------------------------------------------
#
# These tests load real ``.pflow.md`` files via the public ``WorkflowRunner``
# API and assert on the rendered diagnostic text an AI agent would see. They
# close three coverage gaps that inline-IR tests cannot hit:
#
# 1. **Markdown parser → source_line → rendered file:line** — the parser's
#    ``yaml_item_lines`` / ``yaml_item_keys`` tracking only runs when a file
#    is parsed. Inline IR dicts with ``_source_line`` keys mock this out.
# 2. **Rendered stderr text, not just structured data** — agents read rendered
#    output; the inline-IR tests verify ``context['unresolved_references']``
#    shape but never the final text surface.
# 3. **Full pipeline including ``parse_markdown`` and IR normalization** —
#    the file-based tests exercise the validator + normalizer + runner chain
#    that inline-IR tests skip.
#
# The fixtures are also validated at the IR schema level by
# ``tests/test_docs/test_example_validation.py``, which ``rglob``s everything
# under ``examples/``. Keep the fixtures schema-valid.
# ---------------------------------------------------------------------------


def _run_fixture(filename: str):
    """Load and execute a fixture under ``examples/error-handling/``."""
    path = EXAMPLES_ERROR_HANDLING / filename
    return WorkflowRunner().run(str(path), {}, config=RunnerConfig(cache_enabled=False))


def _only_template_error(result) -> str:
    """Return the rendered text of the single template_error diagnostic."""
    errors = [
        d
        for d in result.diagnostics
        if d.severity == Severity.ERROR and (d.context or {}).get("category") == "template_error"
    ]
    assert len(errors) == 1, f"expected exactly one template_error, got {len(errors)}: {result.diagnostics}"
    return format_diagnostic(errors[0])


def test_example_failed_node_direct_reference_renders_pasteable_fix():
    """Direct reference to a failed node must render:
    - the real failure details (exit_code, command)
    - the source line from the markdown parser
    - a paste-able coalesce fix using a real peer node name
    """
    result = _run_fixture("failed-node-direct-reference.pflow.md")
    assert result.status == WorkflowStatus.FAILED

    rendered = _only_template_error(result)
    # Source line 38 from the fixture — comes from the markdown parser, not inline.
    assert "failed-node-direct-reference.pflow.md:38" in rendered, rendered
    # Real failure details must surface, not "Unknown error" or "did not execute".
    assert "Exit code: 42" in rendered, rendered
    assert "executed but FAILED" in rendered, rendered
    # Paste-able fix must use the real peer node name, not a placeholder.
    assert "${primary.stdout ?? fallback.stdout}" in rendered, rendered


def test_example_typo_on_failed_node_surfaces_failure_and_corrected_fix():
    """When a reference has BOTH a typo AND the node failed, the error must:
    - surface the failure as the PRIMARY signal (not "did not execute")
    - surface the typo as a SECONDARY hint ("Did you mean: stdout?")
    - render the paste-able fix with the CORRECTED field + real peer name
      (``${primary.stdout ?? fallback.stdout}`` — not ``${primary.stddout ??...}``)

    This is Fix #5's regression guard — the ``corrected_var`` field must
    flow from ``_classify_one_reference`` into ``_format_failed_reference_fixes``.
    """
    result = _run_fixture("typo-on-failed-node.pflow.md")
    assert result.status == WorkflowStatus.FAILED

    rendered = _only_template_error(result)
    assert "typo-on-failed-node.pflow.md:38" in rendered, rendered
    # Primary signal: the failure, not the typo.
    assert "executed but FAILED" in rendered, rendered
    assert "Exit code: 7" in rendered, rendered
    # Secondary hint: the typo correction.
    assert "Did you mean: ${primary.stdout}" in rendered, rendered
    # Paste-able fix MUST use corrected field (stdout, not stddout) + real peer.
    assert "${primary.stdout ?? fallback.stdout}" in rendered, rendered
    # The uncorrected form must NOT appear in the fix suggestion.
    assert "${primary.stddout ??" not in rendered, rendered


def test_example_loop_recovery_final_state_is_succeeded():
    """A node fails on visit 1, then succeeds on visit 2. After the loop:
    - the workflow's status is SUCCESS
    - the node lives in ``shared_after[node_id]`` (top level = succeeded)
    - the node is NOT in ``__failures__`` (stale record cleared by loop guard)
    - the final output is the visit-2 data

    Guards the ``clear_node_failure`` wiring in ``enforce_loop_guard``. If the
    stale failure record survived across loop re-entry, ``get_node_status``
    would report FAILED and downstream template resolution would break.

    Uses ``/tmp/pflow-task148-marker`` as a cross-visit signal — the fixture's
    ``setup`` step removes any stale marker so repeated runs are idempotent.
    """
    result = _run_fixture("loop-recovery.pflow.md")
    assert result.status == WorkflowStatus.SUCCESS
    assert "maybe-fail" in result.shared_after
    assert "maybe-fail" not in result.shared_after.get("__failures__", {})
    assert result.shared_after["maybe-fail"].get("stdout") == "succeeded-on-retry"


def test_example_source_line_multi_output_tracks_first_output_line():
    """When multiple outputs are declared at different lines and the first one
    fails, the diagnostic's ``At:`` line must point at the failing output's
    exact source line — not the last output, not the top of the file.

    Proves the markdown parser's parallel ``yaml_item_lines`` tracking
    correctly indexes into the YAML items list by key position.
    """
    result = _run_fixture("source-line-multi-output.pflow.md")
    assert result.status == WorkflowStatus.FAILED

    rendered = _only_template_error(result)
    # Only the first output should be reported as failed.
    assert "In output 'first_output':" in rendered, rendered
    assert "In output 'second_output':" not in rendered, rendered
    # Line 37 is the failing output's ``- source:`` line in the fixture.
    assert "source-line-multi-output.pflow.md:37" in rendered, rendered


def test_example_source_line_heavy_offsets_tracks_correct_line():
    """A fixture with heavy blank-line padding and prose before the output
    section stresses the parser's line offset tracking. The rendered ``At:``
    line must point at the correct absolute line (48 in this fixture), not
    the relative position within the Outputs section.

    Guards the parser's ``yaml_current_item_start_line`` assignment against
    off-by-N errors that only surface with real file offsets.
    """
    result = _run_fixture("source-line-heavy-offsets.pflow.md")
    assert result.status == WorkflowStatus.FAILED

    rendered = _only_template_error(result)
    assert "source-line-heavy-offsets.pflow.md:48" in rendered, rendered


def test_example_coalesce_mixed_absent_failed_emits_summary_fix():
    """A coalesce with one absent operand and one failed operand must:
    - error loudly (not silently skip, which was the Task 128 bug class)
    - classify the absent one as ABSENT and the failed one as FAILED
    - emit the "All coalesce operands are unavailable" summary block
    - suggest adding another fallback using a REAL peer node name

    Fix #4 regression guard — the gate in
    ``_format_all_unavailable_coalesce_summary`` must widen to
    ``status in ('failed', 'absent')``, not only ``'failed'``.
    """
    result = _run_fixture("coalesce-mixed-absent-failed.pflow.md")
    assert result.status == WorkflowStatus.FAILED

    rendered = _only_template_error(result)
    assert "coalesce-mixed-absent-failed.pflow.md:59" in rendered, rendered
    # Both classifications must render.
    assert "Node 'never_run' did not execute" in rendered, rendered
    assert "Node 'fails' executed but FAILED" in rendered, rendered
    # Summary block must appear with paste-able extended fallback using a real peer.
    assert "All coalesce operands are unavailable" in rendered, rendered
    # The extended-fallback suggestion must substitute a real peer (selector or soak),
    # not a placeholder like ``<peer>``.
    assert "<peer>" not in rendered, rendered
    # The summary suggestion should reference one of the surviving peer nodes.
    assert ("selector.stdout" in rendered) or ("soak.stdout" in rendered), rendered


# --- GH #240 + #250 end-to-end regression tests ---


@pytest.mark.trace_files
def test_loop_recovery_trace_reports_success_end_to_end(tmp_path):
    """GH #240 — loop recovery: visit 1 fails, visit 2 succeeds → trace aggregation
    reports Status: success and failed_node_ids is empty.

    Runs through the full WorkflowRunner → engine → trace → save_to_file pipeline
    and asserts on the SERIALIZED trace JSON — what agents and the report
    generator actually consume.
    """
    result = _run_fixture("loop-recovery.pflow.md")

    # Runtime invariant (Task 148) — unchanged: workflow succeeded, no failures left
    assert result.status == WorkflowStatus.SUCCESS

    # Trace aggregation — #240 fix: read via the serialized JSON path, the same
    # path `--report` and external consumers take.
    assert result.trace is not None, "trace collector must exist under default RunnerConfig"
    with patch("pathlib.Path.home", return_value=tmp_path):
        trace_path = result.trace.save_to_file()
    trace_data = json.loads(trace_path.read_text())

    assert trace_data["final_status"] == "success"
    assert trace_data["failed_node_ids"] == []
    assert trace_data["nodes_failed"] == 0
    assert trace_data["nodes_executed"] == 4  # setup, maybe-fail(fail), retry, maybe-fail(ok)

    # Audit history preserved in the events list — BOTH visits of maybe-fail present
    maybe_fail_events = [e for e in trace_data["nodes"] if e.get("node_id") == "maybe-fail"]
    assert len(maybe_fail_events) == 2
    assert maybe_fail_events[0]["success"] is False  # visit 1
    assert maybe_fail_events[1]["success"] is True  # visit 2


def test_routing_failure_in_sub_workflow_propagates_to_parent_trace(tmp_path):
    """GH #250 sub-workflow variant — when a routing failure happens INSIDE a
    sub-workflow, the child engine's ``_handle_no_successor`` calls
    ``mark_last_event_failed`` on the CHILD collector. The flipped event is
    embedded in the parent's ``sub_workflow_events`` list, and the parent's
    own trace event for the sub-workflow node shows success=False because
    the child engine returned "error".

    Pins the child-engine → child-collector → parent-sub_workflow_events wiring.
    """
    child_file = tmp_path / "child.pflow.md"
    child_file.write_text(
        """\
# Child

Child workflow whose router returns a custom action with no matching edge.

## Steps

### child-router

Emit a custom action at runtime that the parser can't statically verify.

- type: code
- next: child-default

```python code
import os
result: str = "child-routed"
next: str = os.environ.get("PFLOW_CHILD_ROUTE", "child-default")
```

### child-default

Unreachable default-edge target — only exists to make the router's action unmatched.

- type: shell
- next: end

```shell command
echo "child default"
```
""",
        encoding="utf-8",
    )

    parent_file = tmp_path / "parent.pflow.md"
    parent_file.write_text(
        f"""\
# Parent

Parent invokes the child workflow that triggers an internal routing failure.

## Steps

### invoke-child

Delegate to the child workflow.

- type: workflow
- workflow: {child_file}
""",
        encoding="utf-8",
    )

    import os

    os.environ["PFLOW_CHILD_ROUTE"] = "child_custom_route"
    try:
        runner = WorkflowRunner()
        result = runner.run(str(parent_file), {}, config=RunnerConfig(cache_enabled=False))
    finally:
        os.environ.pop("PFLOW_CHILD_ROUTE", None)

    # Parent-level: the WorkflowExecutor node failed (child returned "error"
    # from its own routing failure → parent's error_action="error" by default).
    assert not result.success
    assert result.trace is not None

    parent_events = [e for e in result.trace.events if e.get("node_id") == "invoke-child"]
    assert len(parent_events) == 1
    parent_event = parent_events[0]
    assert parent_event["success"] is False, "parent sub-workflow event must reflect child failure"

    # Child-level: the child collector flipped the router event. That event
    # lives inside parent_event["sub_workflow_events"].
    sub_events = parent_event.get("sub_workflow_events") or []
    child_router_events = [e for e in sub_events if e.get("node_id") == "child-router"]
    assert len(child_router_events) == 1, (
        f"expected exactly one child-router event in sub_workflow_events, got {sub_events}"
    )
    child_router = child_router_events[0]
    assert child_router["success"] is False, (
        "child engine's _handle_no_successor must flip the child collector's event — "
        "otherwise trace says success=True while __failures__ says routing_error"
    )
    assert "child_custom_route" in (child_router.get("error") or "")
    assert "no successor edge matches" in (child_router.get("error") or "")


def test_routing_failure_on_custom_action_propagates_to_trace():
    """GH #250 — a code node returning a custom non-error action with no matching
    successor produces a trace event with success=False (not success=True silently
    disagreeing with __failures__).

    End-to-end: constructs an inline workflow, runs through WorkflowRunner, then
    inspects the collected trace.
    """
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "router",
                "type": "code",
                "purpose": "Return a custom non-error action that has no matching edge.",
                "params": {"code": 'result: str = "routed"\nnext: str = "custom_route"'},
            },
            {
                "id": "default_path",
                "type": "shell",
                "purpose": "Unreachable default-edge target — provides a non-error successor.",
                "params": {"command": 'echo "default"'},
            },
        ],
        "edges": [
            {"from": "router", "to": "default_path", "action": "default"},
        ],
        "start_node": "router",
    }

    runner = WorkflowRunner()
    result = runner.run(ir, {}, config=RunnerConfig(cache_enabled=False))

    # Runtime invariant: router archived as routing failure
    assert not result.success
    failures = result.shared_after.get("__failures__", {})
    assert "router" in failures
    assert failures["router"]["category"] == "routing_error"

    # Trace invariant: the router event agrees with __failures__
    assert result.trace is not None
    router_events = [e for e in result.trace.events if e.get("node_id") == "router"]
    assert len(router_events) == 1
    event = router_events[0]
    assert event["success"] is False, (
        "Trace event for router must show success=False even though action='custom_route' "
        "did not literally start with 'error'. This was the GH #250 bug."
    )
    assert "custom_route" in (event.get("error") or "")


# ===========================================================================
# PR 1: failure-archival invariant across the sub-workflow boundary (#252 + #233)
#
# A failed sub-workflow must reach the parent's __failures__ with the child's
# STRUCTURED per-node failure (category + data) and provenance, not a flattened
# string — across the non-batch, batch, and nested boundaries — while never
# leaking child node IDs into the parent's top-level __failures__ keys (#254).
# ===========================================================================


def _write_child_shell_fail(tmp_path, name="child.pflow.md", *, command='echo "boom" >&2; exit 7'):
    """Write a child workflow whose single shell step always fails. Returns the path."""
    path = tmp_path / name
    path.write_text(
        f"""\
# Child

A child workflow whose inner shell step always fails.

## Steps

### inner

Run a shell command that always fails.

- type: shell

```shell command
{command}
```
""",
        encoding="utf-8",
    )
    return path


def _subworkflow_node(child_path, *, node_id="sub", **extra):
    node = {
        "id": node_id,
        "type": "workflow",
        "purpose": "Delegate to a child workflow that fails.",
        "params": {"workflow": str(child_path), **extra},
    }
    return node


def test_subworkflow_shell_failure_propagates_structured_to_parent(tmp_path):
    """#233 — a non-batch sub-workflow shell failure surfaces the child's structured
    record (category, command, exit_code, stderr) at the parent, with provenance, and
    NO child node ID leaks into the parent's top-level __failures__ (#254)."""
    child = _write_child_shell_fail(tmp_path, command='echo "out"; echo "err" >&2; exit 1')
    parent_ir = {
        "ir_version": "0.1.0",
        "nodes": [_subworkflow_node(child)],
        "start_node": "sub",
    }

    result = WorkflowRunner().run(parent_ir, {}, RunnerConfig(cache_enabled=False))

    assert result.status == WorkflowStatus.FAILED
    failures = result.shared_after.get("__failures__", {})
    # The executor node is archived; the child's inner node is NOT a top-level key.
    assert "sub" in failures
    assert "inner" not in failures, "child node IDs must stay nested (no #254 regression)"

    # Structured child failure carried in the executor's archived data.
    child_failure = failures["sub"]["data"]["_pflow_child_failure"]
    assert child_failure["failed_node"] == "inner"
    assert child_failure["failures"]["inner"]["category"] == "shell_failure"

    # The reconstructed diagnostic renders byte-identical to a top-level shell
    # failure, wrapped with provenance.
    assert len(result.errors) == 1
    diag = result.errors[0]
    assert diag.node_id == "inner"
    assert diag.message.startswith("In step 'sub' sub-workflow:")
    ctx = diag.context or {}
    assert ctx.get("sub_workflow_step") == "sub"
    assert ctx.get("shell_exit_code") == 1
    assert "exit 1" in (ctx.get("shell_command") or "")
    rendered = format_diagnostic(diag)
    assert "In step 'sub' sub-workflow:" in rendered
    assert "Shell details:" in rendered
    assert "err" in rendered  # child stderr survives to the parent's rendered error
    assert "__failures__" not in rendered  # no internal-vocabulary leak


def test_subworkflow_failure_state_is_json_serializable(tmp_path):
    """The carried bundle must be plain JSON (no Diagnostic/Exception objects) so it
    survives the trace + MCP/JSON serialization paths (review W-b)."""
    child = _write_child_shell_fail(tmp_path)
    parent_ir = {"ir_version": "0.1.0", "nodes": [_subworkflow_node(child)], "start_node": "sub"}

    result = WorkflowRunner().run(parent_ir, {}, RunnerConfig(cache_enabled=False))

    failures = result.shared_after.get("__failures__", {})
    dumped = json.dumps(failures)  # raises TypeError if a Diagnostic/Exception leaked
    assert "_pflow_child_failure" in dumped
    # Result diagnostics serialize cleanly too (no dataclass repr fallbacks).
    diag_json = json.dumps([d.to_dict() for d in result.errors])
    assert "Diagnostic(" not in diag_json


def test_batch_subworkflow_shell_failure_carries_structured_per_item(tmp_path):
    """#252 — a sub-workflow run as a batch item carries the child's structured
    failure into the parent batch node's errors[], not just a flat string."""
    child = _write_child_shell_fail(tmp_path)  # exit 7
    parent_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "fan",
                "type": "workflow",
                "purpose": "Run the failing child once per batch item.",
                "params": {"workflow": str(child)},
                "batch": {"items": ["a"], "as": "item"},
            }
        ],
        "start_node": "fan",
    }

    result = WorkflowRunner().run(parent_ir, {}, RunnerConfig(cache_enabled=False))

    assert result.status == WorkflowStatus.FAILED
    failures = result.shared_after.get("__failures__", {})
    assert "fan" in failures
    assert "inner" not in failures  # no #254 regression through the batch path
    errors = failures["fan"]["data"]["errors"]
    assert len(errors) == 1
    child_failure = errors[0]["child_failure"]
    assert child_failure["failed_node"] == "inner"
    inner = child_failure["failures"]["inner"]
    assert inner["category"] == "shell_failure"
    assert inner["data"]["exit_code"] == 7


def test_parallel_batch_subworkflow_failures_attributed_per_item(tmp_path):
    """Review W-c — in a PARALLEL batch, each item's child failure must be attributed
    to its own item (the bundle is sourced from per-item-isolated __failures__, never
    the reference-shared __warnings__)."""
    child = tmp_path / "child.pflow.md"
    child.write_text(
        """\
# Child

Echo the per-item message, then fail.

## Inputs

### msg

The per-item message.

- type: string

## Steps

### inner

Echo the message and fail so the value is captured in the failure record.

- type: shell

```shell command
echo "got:${msg}"; exit 3
```
""",
        encoding="utf-8",
    )
    parent_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "fan",
                "type": "workflow",
                "purpose": "Fan a failing child over distinguishable items in parallel.",
                "params": {"workflow": str(child), "inputs": {"msg": "${item}"}},
                "batch": {
                    "items": ["alpha", "beta"],
                    "as": "item",
                    "error_handling": "continue",
                    "parallel": True,
                },
            }
        ],
        "start_node": "fan",
    }

    result = WorkflowRunner().run(parent_ir, {}, RunnerConfig(cache_enabled=False))

    failures = result.shared_after.get("__failures__", {})
    errors = failures["fan"]["data"]["errors"]
    assert len(errors) == 2
    # Map each item's index → the stdout captured in ITS OWN child failure record.
    by_item = {}
    for err in errors:
        cf = err["child_failure"]
        stdout = cf["failures"]["inner"]["data"].get("stdout", "")
        by_item[str(err["item"])] = stdout
    assert "got:alpha" in by_item["alpha"], by_item
    assert "got:beta" in by_item["beta"], by_item


def test_nested_subworkflow_failure_chains_provenance(tmp_path):
    """Nested >1 level — provenance chains outermost-first across depth, and the
    reconstructed diagnostic names the deepest failing node."""
    grandchild = _write_child_shell_fail(tmp_path, "grandchild.pflow.md", command="exit 1")
    child = tmp_path / "child.pflow.md"
    child.write_text(
        f"""\
# Child

A child whose only step is a deeper sub-workflow that fails.

## Steps

### subsub

Delegate to the grandchild workflow.

- type: workflow
- workflow: {grandchild}
""",
        encoding="utf-8",
    )
    parent_ir = {
        "ir_version": "0.1.0",
        "nodes": [_subworkflow_node(child, node_id="sub")],
        "start_node": "sub",
    }

    result = WorkflowRunner().run(parent_ir, {}, RunnerConfig(cache_enabled=False))

    assert result.status == WorkflowStatus.FAILED
    assert len(result.errors) == 1
    diag = result.errors[0]
    # Outermost-first chain: parent step 'sub' wraps child step 'subsub' wraps inner.
    assert diag.message.startswith("In step 'sub' sub-workflow: In step 'subsub' sub-workflow:")
    assert diag.node_id == "inner"  # deepest failing node


def test_subworkflow_error_action_continue_does_not_leak_child_failure(tmp_path):
    """Review W-d — a custom non-error route (error_action: continue) is NOT archived
    by step 17.5, so the child_failure bundle must NOT be written (it would linger in
    the success namespace and leak as ${node.child_failure})."""
    child = _write_child_shell_fail(tmp_path)
    parent_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            _subworkflow_node(child, node_id="sub", error_action="continue"),
            {
                "id": "after",
                "type": "shell",
                "purpose": "Continue past the failed sub-workflow.",
                "params": {"command": 'echo "after"'},
            },
        ],
        "edges": [{"from": "sub", "to": "after", "action": "continue"}],
        "start_node": "sub",
    }

    result = WorkflowRunner().run(parent_ir, {}, RunnerConfig(cache_enabled=False))

    from pflow.runtime.workflow_executor import WorkflowExecutor

    # The run continued past the handled failure (continue route, not archived).
    assert "sub" not in result.shared_after.get("__failures__", {})
    sub_namespace = result.shared_after.get("sub", {})
    assert isinstance(sub_namespace, dict)
    # The carry rides a reserved `_pflow_` key so it is filtered from agent-visible
    # output and never exposed as a ${sub.child_failure} workflow output. Any key
    # carrying the bundle in the (succeeded-via-continue) namespace must be
    # non-exposable — never the plain `child_failure` key.
    assert "child_failure" not in sub_namespace
    for key in sub_namespace:
        if "child_failure" in key:
            assert not WorkflowExecutor.is_exposable_child_key(key, set()), (
                f"child_failure carried on exposable key {key!r} would leak as a workflow output"
            )


def test_child_template_diagnostic_survives_reconstruction():
    """A strict-mode child template error carries its structured Diagnostic
    (unresolved_references, peer suggestions) only on the child exception. Pin that it
    round-trips through the bundle and reconstruction with provenance, fields intact."""
    from pflow.execution.executor_service import build_subworkflow_diagnostics

    template_diag = Diagnostic(
        severity=Severity.ERROR,
        source="runtime",
        message="Template error: '${ghost.value}' could not be resolved",
        node_id="inner",
        context={
            "category": "template_error",
            "unresolved_references": [{"var": "ghost.value", "status": "absent"}],
        },
    )
    bundle = {
        "workflow_path": "./child.pflow.md",
        "failed_node": "inner",
        "failures": {"inner": {"data": {}, "category": "template_error", "error": "Template error"}},
        "template_diagnostic": template_diag.to_dict(),
    }

    diags = build_subworkflow_diagnostics(bundle, "sub")

    assert len(diags) == 1
    d = diags[0]
    assert d.message == "In step 'sub' sub-workflow: Template error: '${ghost.value}' could not be resolved"
    assert d.node_id == "inner"
    assert (d.context or {}).get("unresolved_references") == [{"var": "ghost.value", "status": "absent"}]
    assert (d.context or {}).get("sub_workflow_step") == "sub"
    assert (d.context or {}).get("sub_workflow_path") == "./child.pflow.md"


def test_real_mcp_node_protocol_error_archived_as_mcp_failure():
    """#253 end-to-end: a REAL MCPNode hitting a transport error flows through
    exec_fallback → post → engine step 17.5 and is archived as mcp_failure, with
    get_node_status reporting FAILED (never SUCCEEDED).

    #491 fixed and tested the ROUTING with a BaseNode mock that mimics MCPNode.post();
    this drives the real node through its own exec_fallback path — the integration gap
    the issue flagged ("zero MCP integration tests for the failure archival path").
    """
    from unittest.mock import patch

    from pflow.nodes.mcp.node import MCPNode
    from pflow.runtime.engine import CompiledWorkflow, NodeConfig, WorkflowEngine
    from pflow.runtime.node_state import NodeStatus, get_node_failure, get_node_status

    node = MCPNode()
    node.node_id = "call_tool"
    node.set_params({"__mcp_server__": "demo", "__mcp_tool__": "do_thing"})

    async def boom(_prep_res):
        raise ConnectionError("connection refused")

    configs = {
        "call_tool": NodeConfig(
            node_id="call_tool",
            node_type_name="MCPNode",
            template_config=None,
            batch_config=None,
            namespaced=True,
            interface_metadata=None,
        )
    }
    workflow = CompiledWorkflow(start_node=node, node_configs=configs)
    shared: dict = {}

    with (
        patch.object(MCPNode, "_load_server_config", return_value={"command": "x"}),
        patch.object(MCPNode, "_exec_async", side_effect=boom),
    ):
        result = WorkflowEngine().run(workflow, shared)

    assert result == "error"
    failure = get_node_failure(shared, "call_tool")
    assert failure is not None
    assert failure["category"] == "mcp_failure"
    assert get_node_status(shared, "call_tool") == NodeStatus.FAILED


@pytest.mark.trace_files
def test_subworkflow_failure_trace_json_has_no_diagnostic_repr(tmp_path):
    """Review W-b — the saved trace serializes via _sanitize_for_json + default=str
    (no Diagnostic-aware converter). Assert the trace JSON for a failed sub-workflow
    carries the structured child_failure as data, never a stringified 'Diagnostic('."""
    child = _write_child_shell_fail(tmp_path, command='echo "boom" >&2; exit 1')
    parent_ir = {"ir_version": "0.1.0", "nodes": [_subworkflow_node(child)], "start_node": "sub"}

    result = WorkflowRunner().run(parent_ir, {}, RunnerConfig(cache_enabled=False))

    assert result.trace is not None
    with patch("pathlib.Path.home", return_value=tmp_path):
        trace_path = result.trace.save_to_file()
    raw = trace_path.read_text()
    assert "_pflow_child_failure" in raw, "structured child failure must reach the saved trace"
    assert "Diagnostic(" not in raw, "no Diagnostic object may be stringified into the trace"


def test_strict_template_error_in_child_surfaces_unresolved_references(tmp_path):
    """Review W1 (test-fidelity) — a RUNTIME strict-mode template error inside a child
    (a failed-node reference, which the validator can't catch statically) carries its
    structured Diagnostic only on the child exception. Pin the full capture chain:
    child raises → `_pflow_template_diagnostic` → bundle → reconstruction, so
    `unresolved_references` survive to the parent with provenance."""
    child = tmp_path / "tmpl-child.pflow.md"
    child.write_text(
        """\
# Template Child

A child where a recovered node references a failed node's output at runtime.

## Steps

### producer

Fail by design so its output is unavailable at runtime.

- type: shell
- on-error: consumer

```shell command
exit 1
```

### consumer

Reference the failed producer's stdout — unresolved at runtime in strict mode.

- type: shell
- next: end

```shell command
echo "${producer.stdout}"
```
""",
        encoding="utf-8",
    )
    parent_ir = {"ir_version": "0.1.0", "nodes": [_subworkflow_node(child)], "start_node": "sub"}

    result = WorkflowRunner().run(parent_ir, {}, RunnerConfig(cache_enabled=False))

    assert result.status == WorkflowStatus.FAILED
    # The strict-mode template Diagnostic was captured from the child exception.
    cf = result.shared_after["__failures__"]["sub"]["data"]["_pflow_child_failure"]
    assert "template_diagnostic" in cf
    # ...and reconstructed with unresolved_references + provenance at the parent.
    assert len(result.errors) == 1
    diag = result.errors[0]
    assert diag.message.startswith("In step 'sub' sub-workflow:")
    ctx = diag.context or {}
    assert ctx.get("category") == "template_error"
    assert ctx.get("unresolved_references"), "structured per-reference detail must survive the boundary"
    assert ctx.get("sub_workflow_step") == "sub"


def test_jsonable_converts_diagnostic_and_exception():
    """Review S1 — `_jsonable` is the serialization isolation boundary for the carry
    bundle: it must convert Diagnostic → dict and Exception → str (recursively) so the
    archived bundle never holds objects the trace / MCP-JSON serializers would drop."""
    from pflow.runtime.workflow_executor import WorkflowExecutor

    diag = Diagnostic(severity=Severity.ERROR, source="x", message="m", context={"k": "v"})
    value = {"a": diag, "b": [ValueError("boom")], "c": {"nested": diag}, "plain": "s", "n": 7}

    out = WorkflowExecutor._jsonable(value)

    json.dumps(out)  # must not raise — proves no Diagnostic/Exception object survived
    assert out["a"] == diag.to_dict()
    assert out["b"][0] == "boom"
    assert out["c"]["nested"] == diag.to_dict()
    assert out["plain"] == "s"
    assert out["n"] == 7


def test_child_batch_failure_strips_raw_item_from_carried_bundle(tmp_path):
    """Review (codex A) — when the failed child node is itself a batch, the carried
    bundle must NOT expose raw child batch item inputs in the parent's archived data;
    it honors the same display-safety compaction the top-level batch path applies."""
    child = tmp_path / "child.pflow.md"
    child.write_text(
        """\
# Child

Child whose batch step fails per item with sensitive inputs.

## Steps

### faninner

Fail per item so the child batch archives raw item inputs.

- type: shell
- batch:
    items: ["SENSITIVE-AAA", "SENSITIVE-BBB"]
    as: it
    error_handling: continue

```shell command
echo "${it}"; exit 1
```
""",
        encoding="utf-8",
    )
    parent_ir = {"ir_version": "0.1.0", "nodes": [_subworkflow_node(child)], "start_node": "sub"}

    result = WorkflowRunner().run(parent_ir, {}, RunnerConfig(cache_enabled=False))

    bundle = result.shared_after["__failures__"]["sub"]["data"]["_pflow_child_failure"]
    inner_errors = bundle["failures"]["faninner"]["data"]["errors"]
    assert inner_errors
    # The raw `item` input is stripped (replaced by the display-safe summary +
    # has_full_item), exactly as the top-level batch compaction does — so raw child
    # batch inputs don't ride into the parent's trace / JSON output.
    assert "item" not in inner_errors[0], "raw child batch item leaked into the carried bundle"
    assert inner_errors[0].get("has_full_item") is True
    assert "item_summary" in inner_errors[0]
    json.dumps(bundle)  # still JSON-serializable


def test_batch_subworkflow_continue_route_still_carries_structured_failure(tmp_path):
    """Review (codex C) — a batched sub-workflow with a non-error `error_action`
    (e.g. `continue`) is still recorded as a failed item by the batch, so its
    structured child failure must survive (not regress to a flat string)."""
    child = _write_child_shell_fail(tmp_path, command='echo "x"; exit 5')
    parent_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "fan",
                "type": "workflow",
                "purpose": "Batch a continue-routed failing child once per item.",
                "params": {"workflow": str(child), "error_action": "continue"},
                "batch": {"items": ["a", "b"], "as": "item", "error_handling": "continue"},
            }
        ],
        "start_node": "fan",
    }

    result = WorkflowRunner().run(parent_ir, {}, RunnerConfig(cache_enabled=False))

    errors = result.shared_after["__failures__"]["fan"]["data"]["errors"]
    assert len(errors) == 2
    for err in errors:
        cf = err.get("child_failure")
        assert cf is not None, "continue-routed batch item must still carry structured child failure"
        assert cf["failures"]["inner"]["category"] == "shell_failure"
        assert cf["failures"]["inner"]["data"]["exit_code"] == 5
