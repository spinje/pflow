"""CLI surface tests for approval gates (Task 125 Phase 3).

Pins the CLI half of the gate contract: exit code 3 + clean rendering on deny
(text AND `--output-format json` — the denied branch bypasses `output_error`,
so JSON mode needs its own document), `--auto-approve` pre-approval with the
visible stderr line, the two pre-flight warnings (unknown flag id with fuzzy
suggestion; non-interactive run with unapproved gates), and `-p` suppression.

CliRunner/pytest stdin is never a TTY (tests/CLAUDE.md pitfall #10), so prompt
flows patch `gate_prompt.can_prompt` → True and answer via a patched
`click.confirm` — the rest of the pipeline (resolver → engine → runner → CLI
display) runs for real.
"""

from __future__ import annotations

import json

import pytest

from tests.test_cli.test_workflow_commands import invoke_cli


@pytest.fixture
def gated_workflow(tmp_path):
    """Two-step workflow: plain step, then a gated step with a side-effect proof file."""
    proof = tmp_path / "proof.txt"
    path = tmp_path / "gated.pflow.md"
    path.write_text(
        "# Gated Demo\n\nDemo.\n\n## Steps\n\n"
        "### make-value\n\nProduce a value.\n\n"
        "- type: shell\n"
        "- command: echo hello\n\n"
        "### guarded-step\n\nPost the value.\n\n"
        "- type: shell\n"
        f"- command: echo posting-${{make-value.stdout}} > {proof}; printf done\n"
        "- approval: required\n"
    )
    return path, proof


def _allow_prompting(monkeypatch, *, answer: bool):
    monkeypatch.setattr("pflow.execution.gate_prompt.can_prompt", lambda oc: True)
    monkeypatch.setattr("pflow.execution.gate_prompt.click.confirm", lambda *a, **k: answer)


class TestDeniedExit:
    def test_denied_gate_exits_3_never_ran_step_no_failure_tag(self, gated_workflow, monkeypatch):
        path, proof = gated_workflow
        _allow_prompting(monkeypatch, answer=False)
        result = invoke_cli(["--no-trace", str(path)])
        assert result.exit_code == 3
        assert "Denied at gate 'guarded-step'" in result.stderr
        assert "stopped cleanly" in result.stderr
        assert not proof.exists(), "denied step must never run"
        # Never the failure rendering — a human's no is not a workflow failure.
        assert "Workflow failed" not in result.stderr
        assert "❌" not in result.stderr

    def test_denied_gate_json_mode_emits_denied_document(self, gated_workflow, monkeypatch):
        path, _ = gated_workflow
        _allow_prompting(monkeypatch, answer=False)
        result = invoke_cli(["--no-trace", "--output-format", "json", str(path)])
        assert result.exit_code == 3
        document = json.loads(result.output)
        assert document["success"] is False
        assert document["status"] == "denied"
        assert document["gate"]["node_id"] == "guarded-step"
        # Superset of the unified failure shape: agents that iterate
        # .diagnostics/.errors on success==false must find the denial there too.
        assert any(d.get("context", {}).get("category") == "gate" for d in document["diagnostics"])
        assert document["errors"] and document["errors"][0]["node_id"] == "guarded-step"
        # The preview shows the RESOLVED action the human said no to — the exact
        # substituted value, so a regression to the raw ${...} template fails here.
        assert "posting-hello" in document["gate"]["preview"]["command"]

    def test_approved_gate_runs_step_and_exits_0(self, gated_workflow, monkeypatch):
        path, proof = gated_workflow
        _allow_prompting(monkeypatch, answer=True)
        result = invoke_cli(["--no-trace", str(path)])
        assert result.exit_code == 0
        assert proof.read_text().strip() == "posting-hello"


class TestAutoApprove:
    def test_auto_approve_skips_prompt_and_is_visible(self, gated_workflow):
        path, proof = gated_workflow
        result = invoke_cli(["--no-trace", "--auto-approve=guarded-step", str(path)])
        assert result.exit_code == 0
        assert proof.exists()
        assert "pre-approved via --auto-approve=guarded-step" in result.stderr

    def test_unmatched_id_notes_nested_possibility_and_closest_match(self, gated_workflow, monkeypatch):
        # The note must NOT read as a confident "typo" verdict: a nested-gate id
        # legitimately matches nothing top-level yet works (flat namespace), and the
        # --dry-run footer names exactly such ids (deep-review find: the old wording
        # contradicted the footer).
        path, _ = gated_workflow
        _allow_prompting(monkeypatch, answer=True)  # keep the run itself green
        result = invoke_cli(["--no-trace", "--auto-approve=guarded_step", str(path)])
        assert result.exit_code == 0
        assert "--auto-approve=guarded_step does not name a top-level step" in result.stderr
        assert "sub-workflow still matches by name" in result.stderr
        assert "closest top-level match is 'guarded-step'" in result.stderr
        assert "Top-level gated steps: guarded-step" in result.stderr


class TestNonInteractive:
    def test_warns_at_start_then_fails_at_gate_exit_1(self, gated_workflow):
        path, proof = gated_workflow
        result = invoke_cli(["--no-trace", str(path)])
        # GateNotInteractiveError is a normal failure (exit 1) — only DENIED gets 3.
        assert result.exit_code == 1
        assert "will fail at approval gate(s) [guarded-step]" in result.stderr
        assert "Gate needs a human" in result.stderr
        assert "ask your human" in result.stderr
        assert not proof.exists()

    def test_print_flag_suppresses_preflight_warnings(self, gated_workflow):
        path, _ = gated_workflow
        result = invoke_cli(["--no-trace", "-p", str(path)])
        assert result.exit_code == 1
        assert "will fail at approval gate" not in result.stderr

    def test_only_on_ungated_target_does_not_warn_about_unreachable_gates(self, gated_workflow):
        # Under --only, only the target executes — a gate elsewhere cannot fire, so
        # the non-interactive pre-flight warning must not cry wolf about it
        # (deep-review find). The run itself errors on the missing snapshot; the
        # assertion is only about the warning's absence.
        path, _ = gated_workflow
        result = invoke_cli(["--no-trace", "--only", "make-value", str(path)])
        assert "will fail at approval gate" not in result.stderr


def test_completion_status_denied_arm_never_renders_checkmark():
    from pflow.cli.workflow_output import _format_workflow_completion_status

    line = _format_workflow_completion_status(1.5, "denied", False)
    assert line.startswith("✗") and "denied at gate" in line
    assert "✓" not in line
