"""CLI integration tests for --dry-run."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from tests.shared.markdown_utils import write_workflow_file
from tests.test_cli.test_validate_only import make_agent_workflow
from tests.test_cli.test_workflow_commands import invoke_cli


def test_dry_run_does_not_execute_shell_node(tmp_path) -> None:
    """Dry-run must not trigger shell side effects."""
    proof = tmp_path / "proof.txt"
    workflow_path = tmp_path / "dry-run.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "touch-proof",
                    "type": "shell",
                    "params": {"command": f"echo touched > {proof}; printf done"},
                }
            ],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 0
    # The canary file is the actual proof; message check would just restate
    # the contract that --dry-run already promises.
    assert not proof.exists()


def test_dry_run_with_loop_carry_plans_seed_iteration_only(tmp_path) -> None:
    """Dry-run must not resolve carry refs that only exist after iteration 1."""
    child = tmp_path / "child.pflow.md"
    child.write_text(
        """# Child

## Inputs

### state

Current state.

- type: integer

## Outputs

### state

Next state.

- type: integer
- source: ${step.result.state}

### more

Whether to continue.

- type: boolean
- source: ${step.result.more}

## Steps

### step

Advance state.

- type: code
- inputs:
    state: ${state}

```python code
state: int
result: dict = {"state": state + 1, "more": False}
```
""",
        encoding="utf-8",
    )
    workflow_path = tmp_path / "carry-dry-run.pflow.md"
    workflow_path.write_text(
        f"""# Carry Dry Run

## Steps

### run

Loop child with carried state.

- type: workflow
- workflow: {child}
- inputs:
    state: 0
- loop:
    carry:
      state: ${{run.state}}
    while: ${{run.more}}
    max_iterations: 3
""",
        encoding="utf-8",
    )

    result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 0
    assert "Summary" in result.output
    assert "would execute" in result.output


def test_dry_run_json_output_is_valid_json(tmp_path) -> None:
    """Dry-run JSON output should be a single JSON document."""
    workflow_path = tmp_path / "dry-run-json.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", "--output-format", "json", str(workflow_path)])
    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert set(payload) == {"workflow", "plan", "summary", "diagnostics"}


def test_dry_run_json_includes_cache_opportunity_diagnostic(tmp_path) -> None:
    """Dry-run JSON should surface cache nudges from the CLI path."""
    workflow_path = tmp_path / "dry-run-cache-nudge.pflow.md"
    write_workflow_file(
        {
            "inputs": {"article": {"type": "string", "required": True}},
            "nodes": [
                {
                    "id": "summarize",
                    "type": "llm",
                    "params": {
                        "model": "anthropic/claude-haiku-4-5",
                        "prompt": "Summarize ${article}",
                    },
                },
                {
                    "id": "classify",
                    "type": "llm",
                    "params": {
                        "model": "anthropic/claude-haiku-4-5",
                        "prompt": "Classify ${article}",
                    },
                },
            ],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli([
        "--dry-run",
        "--output-format",
        "json",
        str(workflow_path),
        "article=shared stable article context",
    ])
    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert any(diagnostic.get("id") == "cache.opportunities-available" for diagnostic in payload["diagnostics"])


def test_dry_run_exits_zero_on_success(tmp_path) -> None:
    """Successful dry-run exits 0."""
    workflow_path = tmp_path / "dry-run-success.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 0


def test_dry_run_exits_one_on_missing_required_input(tmp_path) -> None:
    """Planning failures should exit 1."""
    workflow_path = tmp_path / "dry-run-missing-input.pflow.md"
    write_workflow_file(
        {
            "inputs": {"name": {"type": "string", "required": True, "description": "Required name"}},
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf ${name}"}}],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 1


def test_dry_run_rejects_agent_invalid_schema_before_plan(tmp_path) -> None:
    """Dry-run must share validation-only's agent schema checks."""
    workflow_path = tmp_path / "agent-invalid-schema-dry-run.pflow.md"
    write_workflow_file(
        make_agent_workflow(
            output_schema={"type": "array", "items": {"type": "string"}},
            prompt="Return an array.",
        ),
        workflow_path,
    )

    result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 1
    assert "top-level type: object" in result.stderr


def test_dry_run_classifies_agent_for_cost_and_display(tmp_path) -> None:
    """AgentNode keeps the former agentic cost/duration planning behavior."""
    workflow_path = tmp_path / "agent-plan.pflow.md"
    write_workflow_file(make_agent_workflow(output_schema=None), workflow_path)

    result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 0, result.output
    assert "review  [agent]" in result.output
    assert "≈ $? (no history)" in result.output
    assert "1 agent" in result.output


def test_dry_run_codex_with_unpriced_model_degrades_to_unknown_cost(tmp_path) -> None:
    """An unpriced Codex model is still a valid plan, with unknown cost."""
    workflow = make_agent_workflow(output_schema=None)
    params = workflow["nodes"][0]["params"]
    params["backend"] = "codex"
    params["model"] = "future-codex-model-not-in-pricing-map"
    params.pop("max_turns")
    workflow_path = tmp_path / "codex-agent-plan.pflow.md"
    write_workflow_file(workflow, workflow_path)

    result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 0, result.output
    assert "review  [agent]" in result.output
    assert "≈ $? (no history)" in result.output
    assert "1 agent" in result.output


def test_dry_run_exits_one_when_plan_contains_error_diagnostic(tmp_path) -> None:
    """Plans that build but carry an ERROR-severity diagnostic must exit 1.

    Mirrors `validate()`'s `len(errors) == 0` convention — any ERROR-severity
    diagnostic (template_error, sub-workflow compile failure, etc.) is
    surfaced via CLI exit code, not silently folded into a "successful" plan.

    Strict-mode template failures are caught by validation upstream today,
    so this contract is exercised by patching `WorkflowRunner.plan()` to
    return a Plan with an injected ERROR diagnostic. That pins the CLI
    exit-code contract independently of which planner path produced the
    error — if a future planner emits an ERROR-severity diagnostic, this
    test guarantees the CLI honors it.
    """
    from pflow.core.diagnostic import Diagnostic, Severity
    from pflow.execution.result import Plan, PlanSummary

    workflow_path = tmp_path / "dry-run-error-diag.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}],
            "edges": [],
        },
        workflow_path,
    )

    error_plan = Plan(
        workflow=str(workflow_path),
        entries=[],
        summary=PlanSummary(
            total=0,
            cached_count=0,
            execute_count=0,
            cache_boundary=None,
            execute_by_type={},
            estimated_cost_usd=0.0,
            nodes_without_history=0,
        ),
        diagnostics=[
            Diagnostic(
                severity=Severity.ERROR,
                message="Synthetic template error",
                source="planner",
                context={"category": "template_error"},
            )
        ],
    )

    with patch("pflow.execution.runner.WorkflowRunner.plan", return_value=error_plan):
        result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 1


def test_dry_run_circular_subworkflow_exits_one(tmp_path) -> None:
    """Broken sub-workflow topology (cycle) must exit 1.

    Before the severity fix, `_sub_workflow_error_entry` emitted WARNING
    and `_display_plan_result` only exits 1 on ERROR — so cycles, max-depth,
    unresolvable refs, and bad `inputs:` shapes all silently exited 0.
    Agents cost-gating via `exit != 0` missed these broken workflows.

    This test pins the user-facing exit-code contract at the CLI boundary;
    `test_build_plan_circular_subworkflow_emits_error_diagnostic` pins the
    library severity it depends on.
    """
    parent_path = tmp_path / "circular-dry-run.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {"id": "self-call", "type": "workflow", "params": {"workflow": str(parent_path), "inputs": {}}},
            ],
            "edges": [],
        },
        parent_path,
    )

    result = invoke_cli(["--dry-run", str(parent_path)])

    assert result.exit_code == 1, (
        f"Circular sub-workflow should exit 1 (was 0 before the severity fix). Output: {result.output}"
    )


def test_dry_run_text_output_contains_boundary_divider(tmp_path) -> None:
    """Fresh dry-run text output should include a cache divider."""
    workflow_path = tmp_path / "dry-run-text.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "printf a"}},
                {"id": "b", "type": "shell", "params": {"command": "printf ${a.stdout}"}},
            ],
            "edges": [{"from": "a", "to": "b"}],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 0
    assert "─── nothing cached — full run ───" in result.output


def test_dry_run_plus_validate_only_exits_one_with_clear_error(tmp_path) -> None:
    """--dry-run and --validate-only are mutually exclusive."""
    workflow_path = tmp_path / "dry-run-conflict.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", "--validate-only", str(workflow_path)])

    assert result.exit_code == 1
    # Error messages go to stderr per pflow's convention — tightening the
    # assertion to stderr-only catches regressions where the message
    # accidentally lands on stdout (would break `pflow ... -f json 2>/dev/null`).
    assert "Cannot combine --dry-run and --validate-only" in result.stderr


def test_dry_run_plus_report_exits_one_with_clear_error(tmp_path) -> None:
    """--dry-run and --report are mutually exclusive."""
    workflow_path = tmp_path / "dry-run-report.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", "--report", str(workflow_path)])

    assert result.exit_code == 1
    assert "Cannot combine --dry-run and --report" in result.stderr


def test_dry_run_plus_no_trace_is_silent_accept(tmp_path) -> None:
    """--no-trace is accepted as a no-op for dry-run."""
    workflow_path = tmp_path / "dry-run-no-trace.pflow.md"
    write_workflow_file(
        {"nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}], "edges": []},
        workflow_path,
    )

    result = invoke_cli(["--dry-run", "--no-trace", str(workflow_path)])

    assert result.exit_code == 0


def test_dry_run_plus_print_is_silent_accept(tmp_path) -> None:
    """-p must not suppress the plan itself."""
    workflow_path = tmp_path / "dry-run-print.pflow.md"
    write_workflow_file(
        {"nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}], "edges": []},
        workflow_path,
    )

    result = invoke_cli(["--dry-run", "-p", str(workflow_path)])

    assert result.exit_code == 0
    assert "Dry-run for" in result.output


@pytest.mark.trace_files
def test_dry_run_composes_with_only_node(tmp_path) -> None:
    """--only plans only the target node, against a snapshot from a prior full run.

    Snapshot --only (issue #443) restores upstream from the most recent full run's
    trace; the dry-run planner mirrors that, so it needs a prior full run first.
    """
    workflow_path = tmp_path / "dry-run-only.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "printf a"}},
                {"id": "b", "type": "shell", "params": {"command": "printf b"}},
            ],
            "edges": [{"from": "a", "to": "b"}],
        },
        workflow_path,
    )

    # Record a full-run trace the snapshot loader can restore from.
    full = invoke_cli([str(workflow_path)])
    assert full.exit_code == 0

    result = invoke_cli(["--dry-run", "--output-format", "json", "--only", "a", str(workflow_path)])
    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert [entry["node_id"] for entry in payload["plan"]] == ["a"]


def test_dry_run_only_without_prior_run_errors(tmp_path) -> None:
    """--only --dry-run with no prior full run surfaces OnlySnapshotMissingError."""
    workflow_path = tmp_path / "dry-run-only-fresh.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "printf a"}},
                {"id": "b", "type": "shell", "params": {"command": "printf b"}},
            ],
            "edges": [{"from": "a", "to": "b"}],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", "--output-format", "json", "--only", "b", str(workflow_path)])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    messages = " ".join(d.get("message", "") for d in payload.get("diagnostics", []))
    assert "needs a prior full run" in messages


def test_dry_run_no_network_calls(tmp_path) -> None:
    """Planner must not execute HTTP or LLM nodes."""
    workflow_path = tmp_path / "dry-run-no-network.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "http-step",
                    "type": "http",
                    "params": {"url": "https://example.com", "method": "GET"},
                },
                {
                    "id": "llm-step",
                    "type": "llm",
                    "params": {"prompt": "hello", "model": "gpt-4"},
                },
            ],
            "edges": [{"from": "http-step", "to": "llm-step"}],
        },
        workflow_path,
    )

    # The dry-run path must not invoke real adapters — patch both the
    # `complete` binding LLMNode imports (Task 158 Phase A.5) AND the
    # legacy http call to verify zero invocations.
    with (
        patch("requests.request") as mock_request,
        patch("pflow.nodes.llm.llm.complete") as mock_complete,
    ):
        result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 0
    assert mock_request.call_count == 0
    assert mock_complete.call_count == 0
