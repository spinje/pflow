"""Task 171 — the PAUSED CLI surface: exit 4, token emission, gate content, JSON document.

The paused display contract (plan 1d): the resume token is the paused run's DATA
(stdout, even under ``-p``); the gate content + the exact answer command ride
stderr so an agent can compose the answer without a blind resume round-trip.
``--no-trace`` keeps the pre-171 hard failure (exit 1) with the updated message
naming the flag as the removable blocker.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from pflow.cli.main import cli

pytestmark = pytest.mark.trace_files

_TOKEN_RE = re.compile(r"Paused at 'gated'\. Resume token: (\S+) \(exit 4\)")

_GATE_WF = """# Paused Demo

A workflow whose second step needs a human approval.

## Steps

### g1

Upstream value.

- type: shell
- next: gated

```shell command
echo "g1-value"
```

### gated

Requires a human approval decision before running.

- type: shell
- env: { API_KEY: sk-super-secret }
- approval: required

```shell command
echo "gated action"
```
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".pflow" / "debug").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def gate_wf(tmp_path):
    path = tmp_path / "paused_demo.pflow.md"
    path.write_text(_GATE_WF)
    return path


def _runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


def test_paused_run_exits_4_with_token_and_gate_content(home, gate_wf):
    result = _runner().invoke(cli, [str(gate_wf)])
    assert result.exit_code == 4, result.stderr
    # ONE parseable stdout line — the token resolves against a real trace file.
    match = _TOKEN_RE.search(result.stdout)
    assert match, f"stdout must carry the token line; stdout:\n{result.stdout}"
    token = match.group(1)
    traces = list((home / ".pflow" / "debug").glob("workflow-trace-*.json"))
    assert len(traces) == 1
    assert token in traces[0].read_text(encoding="utf-8")
    # stderr renders the gate CONTENT (the approval preview, secret-masked) and
    # the exact answer command.
    assert "command:" in result.stderr
    assert "gated action" in result.stderr
    assert "<REDACTED>" in result.stderr
    assert "sk-super-secret" not in result.stderr
    assert f"To answer: pflow resume {token} --approve yes|no" in result.stderr
    # The pre-flight warning speaks the post-171 outcome (pause, not fail —
    # "fail" stays only for --no-trace, pinned in test_approval_gate_cli).
    assert "will pause at approval gate(s) [gated]" in result.stderr


def test_paused_token_survives_print_mode(home, gate_wf):
    result = _runner().invoke(cli, [str(gate_wf), "-p"])
    assert result.exit_code == 4
    assert _TOKEN_RE.search(result.stdout)
    # The answer hint rides stderr, which -p does not silence for pauses.
    assert "--approve yes|no" in result.stderr


def test_paused_json_document_shape(home, gate_wf):
    result = _runner().invoke(cli, [str(gate_wf), "--output-format", "json"])
    assert result.exit_code == 4, result.stderr
    document = json.loads(result.stdout)
    assert document["success"] is False
    assert document["status"] == "paused"
    assert document["paused_node_id"] == "gated"
    assert document["resume_command"] == f"pflow resume {document['execution_id']} --approve yes|no"
    # REQUIRED keys for generic success:false handlers — present and empty.
    assert document["errors"] == []
    assert document["diagnostics"] == []
    # The gate payload is self-contained but secret-masked (same policy as the
    # denied document's gate payload).
    gate = document["gate_request"]
    assert gate["kind"] == "action_approval"
    assert gate["preview"]["env"]["API_KEY"] == "<REDACTED>"
    assert "gated action" in gate["preview"]["command"]


def test_no_trace_gate_keeps_hard_failure_with_updated_message(home, gate_wf):
    """--no-trace stays an explicit opt-out whose gates keep the hard error —
    and the error must NAME --no-trace as the removable blocker (plan 1f)."""
    result = _runner().invoke(cli, ["--no-trace", str(gate_wf)])
    assert result.exit_code == 1, result.stderr
    assert "Resume token" not in result.stdout
    assert "--no-trace" in result.stderr
    assert "pause durably" in result.stderr.lower() or "Gates pause durably" in result.stderr


# ── Answer flows: --approve / --choose e2e (Task 171 Phase 3) ────────────────

_ANY_TOKEN_RE = re.compile(r"Resume token: (\S+) \(exit 4\)")


def _pause(wf: Path, *extra: str) -> str:
    """Run ``wf`` to a durable pause; return the resume token."""
    result = _runner().invoke(cli, [str(wf), *extra])
    assert result.exit_code == 4, result.stderr
    match = _ANY_TOKEN_RE.search(result.stdout)
    assert match, f"expected a token line; stdout:\n{result.stdout}"
    return match.group(1)


def test_approve_yes_resumes_and_matches_uninterrupted_run(home, gate_wf):
    """★ The approve e2e keystone: pause → `--approve yes` → the gated node runs
    once, upstream is restored (not re-executed), the output equals an
    uninterrupted pre-approved run, and NO side-effect confirmation fires (the
    gated node never ran in the source — the answer IS the consent; without the
    paused-skip this non-TTY resume of a side-effecting shell K would refuse)."""
    token = _pause(gate_wf)
    resumed = _runner().invoke(cli, ["resume", token, "--approve", "yes"])
    assert resumed.exit_code == 0, resumed.stderr
    assert "gated action" in resumed.stdout
    assert "gated..." in resumed.stderr  # executed this attempt
    assert "g1..." not in resumed.stderr  # restored, not re-executed
    assert "⤷ Resumed from" in resumed.stderr
    assert "side effects may fire again" not in resumed.stdout + resumed.stderr

    # Equality with an uninterrupted approved run of the same workflow.
    uninterrupted = _runner().invoke(cli, [str(gate_wf), "--auto-approve", "gated"])
    assert uninterrupted.exit_code == 0, uninterrupted.stderr
    assert uninterrupted.stdout == resumed.stdout


def test_approve_no_denies_cleanly_and_double_deny_is_superseded(home, gate_wf):
    """★ The deny e2e: `--approve no` → denied attempt trace, exit 3, the gated
    node never executes. ★ A second `--approve no` on the same token refuses
    SUPERSEDED — the denied attempt executed ZERO nodes, so this pins the
    verdict-line consumption clause (a) in `_attempt_consumed_work` (without it
    the human's "no" could be re-asked forever)."""
    token = _pause(gate_wf)
    denied = _runner().invoke(cli, ["resume", token, "--approve", "no"])
    assert denied.exit_code == 3, denied.stderr
    assert "Denied at gate 'gated'" in denied.stderr
    assert "gated action" not in denied.stdout

    again = _runner().invoke(cli, ["resume", token, "--approve", "no"])
    assert again.exit_code == 1
    assert "already resumed by a newer attempt" in again.stdout + again.stderr


def test_paused_resume_without_answer_renders_gate_and_exact_command(home, gate_wf):
    """No answer flag → the loader's typed refusal, self-contained: the pending
    (secret-masked) approval preview + the exact kind-correct command."""
    token = _pause(gate_wf)
    result = _runner().invoke(cli, ["resume", token])
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "needs an answer" in combined
    assert "gated action" in combined  # the preview content
    assert "<REDACTED>" in combined and "sk-super-secret" not in combined
    assert f"pflow resume {token} --approve yes|no" in combined


def test_choose_on_approval_refuses_with_the_right_flag(home, gate_wf):
    token = _pause(gate_wf)
    result = _runner().invoke(cli, ["resume", token, "--choose", "2"])
    assert result.exit_code == 1
    assert "--approve yes|no" in result.stdout + result.stderr


def test_both_answer_flags_is_usage_error(home, gate_wf):
    result = _runner().invoke(cli, ["resume", "some-target", "--approve", "yes", "--choose", "x"])
    assert result.exit_code == 2
    assert "mutually exclusive" in result.stdout + result.stderr


def test_approve_no_contradicting_auto_approve_is_usage_error(home, gate_wf):
    token = _pause(gate_wf)
    result = _runner().invoke(cli, ["resume", token, "--approve", "no", "--auto-approve", "gated"])
    assert result.exit_code == 2
    assert "contradicts" in result.stdout + result.stderr


def test_dry_run_without_answer_on_paused_requires_the_answer(home, gate_wf):
    """★ Deliberate behavior pin (deep-review S3): `--dry-run` WITHOUT an answer on
    a paused run refuses — an unanswered escalation's route is genuinely
    unknowable, so the answer requirement applies to previews too."""
    token = _pause(gate_wf)
    result = _runner().invoke(cli, ["resume", token, "--dry-run"])
    assert result.exit_code == 1
    assert "needs an answer" in result.stdout + result.stderr


def test_dry_run_with_answer_plans_the_gated_entry_without_executing(home, gate_wf):
    token = _pause(gate_wf)
    result = _runner().invoke(cli, ["resume", token, "--approve", "yes", "--dry-run"])
    assert result.exit_code == 0, result.stderr
    out = result.stdout + result.stderr
    assert "Resuming from 'gated'" in out
    assert "▸ gated" in out
    # Task 171 wording fix: the gate was just answered by --approve yes, so the
    # dry-run footer must NOT tell the agent to pre-approve it.
    assert "--auto-approve=gated" not in out
    assert "pauses for approval at run time" not in out
    # Nothing executed: still exactly one trace on disk (the paused source).
    assert len(list((home / ".pflow" / "debug").glob("workflow-trace-*.json"))) == 1


def test_only_gate_preflight_warns_fail_not_pause(home, gate_wf):
    """Task 171 wording fix: a gate under --only HARD-FAILS (its snapshot trace is
    not resumable), so the non-interactive pre-flight warning must say 'fail at',
    never 'pause at' — the verb must match `_gate_pausable`'s real outcome."""
    # A prior full run seeds the --only snapshot.
    seed = _runner().invoke(cli, [str(gate_wf), "--auto-approve", "gated"])
    assert seed.exit_code == 0, seed.stderr
    result = _runner().invoke(cli, [str(gate_wf), "--only", "gated"])
    assert result.exit_code == 1
    assert "will fail at approval gate" in result.stderr
    assert "will pause at approval gate" not in result.stderr


def test_stale_hash_refuses_paused_resume_and_force_proceeds(home, gate_wf):
    token = _pause(gate_wf)
    gate_wf.write_text(gate_wf.read_text() + "\n<!-- edited since the pause -->\n")
    refused = _runner().invoke(cli, ["resume", token, "--approve", "yes"])
    assert refused.exit_code == 1
    # Task 171: neutral wording ("original run") — a paused run was not a failure.
    assert "edited since the original run" in refused.stdout + refused.stderr
    forced = _runner().invoke(cli, ["resume", token, "--approve", "yes", "--force"])
    assert forced.exit_code == 0, forced.stderr
    assert "gated action" in forced.stdout


_FIRST_NODE_GATE_WF = """# First Gate

The very first step is gated — a pause with ZERO events.

## Steps

### only-gated

Gated from the start.

- type: shell
- approval: required

```shell command
echo "first-node action"
```
"""


def test_first_node_pause_resumes_by_workflow_path(home, tmp_path):
    """★ By-name/by-path selection of a run paused at its FIRST node (zero events,
    no dangling start) — pins consumption clause (b) inside the selection skip
    rule: without `paused ⇒ consumed`, `_select_resume_trace` calls the trace a
    dead zero-work attempt and `pflow resume <workflow>` misses the pause."""
    wf = tmp_path / "first_gate.pflow.md"
    wf.write_text(_FIRST_NODE_GATE_WF)
    _pause(wf)
    result = _runner().invoke(cli, ["resume", str(wf), "--approve", "yes"])
    assert result.exit_code == 0, result.stderr
    assert "first-node action" in result.stdout


_TWO_GATE_WF = """# Two Gates

Two approval gates in sequence — each pause is a new attempt in the chain.

## Steps

### first

First gated step.

- type: shell
- approval: required
- next: second

```shell command
echo "one"
```

### second

Second gated step.

- type: shell
- approval: required

```shell command
echo "two"
```
"""


def test_multiple_gates_chain_pauses_again_and_supersedes(home, tmp_path):
    """Approving gate 1 runs until gate 2 pauses AGAIN as a NEW attempt (its own
    trace + token); the old token is consumed (answering it → superseded);
    answering the new token completes the run. Three traces in the chain."""
    wf = tmp_path / "two_gates.pflow.md"
    wf.write_text(_TWO_GATE_WF)
    token_a = _pause(wf)

    paused_again = _runner().invoke(cli, ["resume", token_a, "--approve", "yes"])
    assert paused_again.exit_code == 4, paused_again.stderr
    match = _ANY_TOKEN_RE.search(paused_again.stdout)
    assert match, paused_again.stdout
    token_b = match.group(1)
    assert token_b != token_a
    assert "Paused at 'second'" in paused_again.stdout

    stale = _runner().invoke(cli, ["resume", token_a, "--approve", "yes"])
    assert stale.exit_code == 1
    assert "already resumed by a newer attempt" in stale.stdout + stale.stderr

    done = _runner().invoke(cli, ["resume", token_b, "--approve", "yes"])
    assert done.exit_code == 0, done.stderr
    assert "two" in done.stdout
    assert len(list((home / ".pflow" / "debug").glob("workflow-trace-*.json"))) == 3


# ── Escalation answer flows (real EscalatingNode via registry injection) ──────

# Declared output pins stdout to the CONSUMER's line — without it, auto-detect's
# `result > stdout` priority would surface the restored esc marker instead.
_ESC_WF = """# Escalation Demo

An escalating step, then a consumer of the decision.

## Steps

### esc

Raises a decision escalation.

- type: escalating-node
- question: pick a or b
- next: after

### after

Reads the human's decision.

- type: shell

```shell command
echo "picked ${esc.result.escalation.decision.chosen}"
```

## Outputs

### message

The consumer's line.

- source: ${after.stdout}
"""


@pytest.fixture
def escalating_registry():
    """Register the test EscalatingNode in the ISOLATED registry so the real CLI
    pipeline (WorkflowRunner → Registry()) can compile it — the registry-injection
    pattern; safe because isolate_pflow_config redirects Registry to tmp paths."""
    from pflow.registry import Registry
    from tests.test_runtime.test_gate_pause import EscalatingNode

    registry = Registry()
    nodes = registry.load()
    nodes["escalating-node"] = {
        "module": "tests.test_runtime.test_gate_pause",
        "class_name": "EscalatingNode",
        "docstring": EscalatingNode.__doc__ or "",
        "file_path": "tests/test_runtime/test_gate_pause.py",
        "type": "core",
        # The full runner pipeline (unlike bare compile_workflow) reads the
        # scanner-produced interface — provide the minimal real shape.
        "interface": {
            "description": "Test node that raises a decision escalation.",
            "params": [{"key": "question", "type": "str", "description": "The escalation question"}],
            "inputs": [],
            "outputs": [{"key": "result", "type": "dict", "description": "Carries the escalation marker"}],
            "actions": ["default"],
        },
    }
    registry.save(nodes)


@pytest.fixture
def esc_wf(tmp_path, escalating_registry):
    path = tmp_path / "esc_demo.pflow.md"
    path.write_text(_ESC_WF)
    return path


def test_escalation_pause_choose_answers_and_completes(home, esc_wf):
    """★ The escalation e2e keystone through the REAL CLI (the pause-promise
    resume-accepts half, now with the actual --choose flag): a non-TTY
    agent-raised escalation emits a token whose stderr carries the question +
    numbered options; `--choose 2` maps to the shown option label, the
    escalating step is NOT re-executed (never re-paid), and the downstream step
    reads `${esc.result.escalation.decision.chosen}`."""
    paused = _runner().invoke(cli, [str(esc_wf)])
    assert paused.exit_code == 4, paused.stderr
    assert "Paused at 'esc'" in paused.stdout
    assert "pick a or b" in paused.stderr
    assert "1. a" in paused.stderr and "2. b" in paused.stderr
    token = _ANY_TOKEN_RE.search(paused.stdout).group(1)
    assert f'pflow resume {token} --choose "<answer or option number>"' in paused.stderr

    resumed = _runner().invoke(cli, ["resume", token, "--choose", "2"])
    assert resumed.exit_code == 0, resumed.stderr
    assert "picked b" in resumed.stdout  # numeric answer mapped to the shown label
    assert "after..." in resumed.stderr  # the successor executed
    assert "esc..." not in resumed.stderr  # the escalating step was restored, not re-run


def test_approve_on_escalation_refuses_with_the_right_flag(home, esc_wf):
    token = _pause(esc_wf)
    result = _runner().invoke(cli, ["resume", token, "--approve", "yes"])
    assert result.exit_code == 1
    assert "--choose" in result.stdout + result.stderr


_ESC_THEN_GATE_WF = """# Escalation Then Gate

An escalation whose successor is itself approval-gated.

## Steps

### esc

Raises a decision escalation.

- type: escalating-node
- question: pick a or b
- next: gated

### gated

Approval-gated consumer of the decision.

- type: shell
- approval: required

```shell command
echo "acted on ${esc.result.escalation.decision.chosen}"
```

## Outputs

### message

The gated consumer's line.

- source: ${gated.stdout}
"""


def test_restored_only_paused_attempt_supersedes_its_source(home, tmp_path, escalating_registry):
    """★ Chain-fork prevention (consumption clause (b)): answering an escalation
    whose successor is itself gated produces attempt B = restored re-records +
    a pause, ZERO fresh executed events. B must still supersede A — without
    clause (b) both A and B would stay answerable and the chain could fork."""
    wf = tmp_path / "esc_gate.pflow.md"
    wf.write_text(_ESC_THEN_GATE_WF)
    token_a = _pause(wf)

    paused_b = _runner().invoke(cli, ["resume", token_a, "--choose", "1"])
    assert paused_b.exit_code == 4, paused_b.stderr
    token_b = _ANY_TOKEN_RE.search(paused_b.stdout).group(1)
    assert "Paused at 'gated'" in paused_b.stdout

    forked = _runner().invoke(cli, ["resume", token_a, "--choose", "1"])
    assert forked.exit_code == 1
    assert "already resumed by a newer attempt" in forked.stdout + forked.stderr

    done = _runner().invoke(cli, ["resume", token_b, "--approve", "yes"])
    assert done.exit_code == 0, done.stderr
    assert "acted on a" in done.stdout


def test_escalation_on_edited_final_step_gets_paused_specific_refusal(home, tmp_path, escalating_registry):
    """The producer never emits a token for a final-step escalation
    (`_gate_pausable`), so this refusal is reachable only by EDITING the workflow
    between pause and resume — and its message must speak the pause, not claim an
    interruption."""
    wf = tmp_path / "esc_edit.pflow.md"
    wf.write_text(_ESC_WF)
    token = _pause(wf)
    # Edit away the successor: the escalating step becomes the final step.
    wf.write_text(
        "# Escalation Demo\n\nAn escalating step with nothing after it.\n\n"
        "## Steps\n\n### esc\n\nRaises a decision escalation.\n\n"
        "- type: escalating-node\n- question: pick a or b\n"
    )
    result = _runner().invoke(cli, ["resume", token, "--choose", "1", "--force"])
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "was the final step" in combined
    assert "its answer has nothing left to run" in combined
    assert "interrupted" not in combined


def test_stream_fault_pause_falls_through_to_failed(home, gate_wf, monkeypatch):
    """Mid-run disk fault (plan 1d fall-through): the trailer never reached disk,
    so no token may print and the exit-1 error document must NOT claim "paused" —
    the status is normalized to failed. This is the ONE case the display's
    `_stream_failed` check defends (the runner's trace_enabled gate covers
    --no-trace)."""
    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    def _fail_open(self):
        self._disable_streaming(OSError("disk full"))

    monkeypatch.setattr(WorkflowTraceCollector, "_open_stream", _fail_open)
    result = _runner().invoke(cli, [str(gate_wf), "--output-format", "json"])
    assert result.exit_code == 1, result.stderr
    document = json.loads(result.stdout)
    assert document["status"] == "failed"
    assert "Resume token" not in result.stdout
    # No dead-end affordance either: there is no file to resume from, so the
    # error document must not advertise a resume_command the loader would refuse.
    assert "resume_command" not in document
