"""CLI surface for ``pflow resume`` (Task 164, Phase 3).

End-to-end through the real ``cli`` group on REAL trace files (pitfall #20):
a failing run streams its trace to ``Path.home()/.pflow/debug`` (redirected to
``tmp_path``), then ``pflow resume`` loads it, applies the side-effect + stale-
workflow gates, merges inputs, and re-enters the walk at K. Pins: by-exec-id and
by-path targeting, the side-effect confirm/refuse policy (TTY yes/no + non-TTY
hard error + ``--force`` bypass + ``llm`` silent), the stale-hash refusal (both
messages) + override, uuid-shaped disambiguation (existence precedence), the
key=value override, refusal exit codes / JSON shape, the resume indicator, and
the failed-run resume hint (present with a trace, omitted under ``--no-trace``).

CliRunner stdin is never a TTY (pitfall #10), so the TTY-confirm flow patches
``gate_prompt.can_prompt`` → True and answers via a patched ``click.confirm``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from pflow.cli.main import cli

pytestmark = pytest.mark.trace_files

_HINT_RE = re.compile(r"pflow resume (\S+)")

# step1 (shell) -> step2 (shell, fails unless mode=ok) -> step3 (shell).
# step2 is side-effecting, so a resume at K exercises the confirm/--force policy.
_SHELL_WF = """# Resume Shell Demo

A tiny side-effecting workflow for resume CLI tests.

## Inputs

### mode

Gate value; step2 fails unless "ok".

- type: string
- required: true

## Steps

### step1

Emit upstream value.

- type: shell
- next: step2

```shell command
echo "upstream-value"
```

### step2

Fails unless mode=ok.

- type: shell
- next: step3

```shell command
test "${mode}" = "ok" && echo "step2-ran"
```

### step3

Final step, reads step2 and step1.

- type: shell

```shell command
echo "done ${step1.stdout} ${step2.stdout}"
```
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Redirect ``Path.home()`` so trace writes AND resume's default debug dir align."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".pflow" / "debug").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def shell_wf(tmp_path):
    path = tmp_path / "wf.pflow.md"
    path.write_text(_SHELL_WF)
    return path


def _runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


def _run_to_failure(wf: Path, *, mode: str = "bad") -> str:
    """Run the workflow to failure via the real run path; return the streamed run's execution id."""
    result = _runner().invoke(cli, [str(wf), f"mode={mode}"])
    assert result.exit_code == 1, result.stderr
    match = _HINT_RE.search(result.stderr)
    assert match, f"failed run should print the resume hint; stderr:\n{result.stderr}"
    return match.group(1)


# --- Targeting ---------------------------------------------------------------


def test_resume_by_execution_id_reenters_and_completes(home, shell_wf):
    exec_id = _run_to_failure(shell_wf)
    result = _runner().invoke(cli, ["resume", exec_id, "mode=ok", "--force"])
    assert result.exit_code == 0, result.stderr
    # Upstream restored (step1 NOT re-run), K + tail executed with the override.
    assert "step2..." in result.stderr and "step3..." in result.stderr
    assert "step1..." not in result.stderr
    assert "done upstream-value step2-ran" in result.stdout
    # Resume mode indicator surfaces (Phase-2 wiring, reached only via this CLI).
    assert "⤷ Resumed from" in result.stderr


def test_resume_by_workflow_path(home, shell_wf):
    _run_to_failure(shell_wf)
    result = _runner().invoke(cli, ["resume", str(shell_wf), "mode=ok", "--force"])
    assert result.exit_code == 0, result.stderr
    assert "done upstream-value step2-ran" in result.stdout


def test_key_value_overrides_meta_inputs(home, shell_wf):
    """The original run recorded mode=bad; the resume's mode=ok wins and step2 succeeds."""
    exec_id = _run_to_failure(shell_wf, mode="bad")
    result = _runner().invoke(cli, ["resume", exec_id, "mode=ok", "--force"])
    assert result.exit_code == 0, result.stderr
    assert "step2-ran" in result.stdout
    # A genuine resume: step1 (mode-independent upstream) is restored, not re-run.
    assert "step1..." not in result.stderr


# --- Side-effect policy (Decision 4 / §E step 5) -----------------------------


def test_side_effect_non_tty_hard_error_names_node_type_and_force(home, shell_wf):
    exec_id = _run_to_failure(shell_wf)
    result = _runner().invoke(cli, ["resume", exec_id, "mode=ok"])
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "step2" in combined
    assert "shell" in combined
    assert "--force" in combined
    assert "side effects may fire again" in combined


def test_side_effect_force_bypass_runs(home, shell_wf):
    exec_id = _run_to_failure(shell_wf)
    result = _runner().invoke(cli, ["resume", exec_id, "mode=ok", "--force"])
    assert result.exit_code == 0, result.stderr


def test_side_effect_tty_confirm_yes_runs(home, shell_wf, monkeypatch):
    exec_id = _run_to_failure(shell_wf)
    monkeypatch.setattr("pflow.execution.gate_prompt.can_prompt", lambda oc: True)
    monkeypatch.setattr("pflow.cli.commands.resume.click.confirm", lambda *a, **k: True)
    result = _runner().invoke(cli, ["resume", exec_id, "mode=ok"])
    assert result.exit_code == 0, result.stderr
    assert "step2-ran" in result.stdout


def test_side_effect_tty_confirm_no_cancels(home, shell_wf, monkeypatch):
    exec_id = _run_to_failure(shell_wf)
    monkeypatch.setattr("pflow.execution.gate_prompt.can_prompt", lambda oc: True)
    monkeypatch.setattr("pflow.cli.commands.resume.click.confirm", lambda *a, **k: False)
    result = _runner().invoke(cli, ["resume", exec_id, "mode=ok"])
    assert result.exit_code == 1
    assert "Resume cancelled" in result.stderr
    # A user's "no" is a clean stop, not the failure rendering.
    assert "❌" not in result.stderr


# --- llm K resumes silently (IR-type vocabulary pin) -------------------------


def _write_llm_wf(tmp_path: Path) -> Path:
    from tests.shared.markdown_utils import write_workflow_file

    ir = {
        "nodes": [
            {"id": "prep", "type": "shell", "params": {"command": "echo ready"}},
            {"id": "gen", "type": "llm", "params": {"model": "test/resume", "prompt": "refine ${prep.stdout}"}},
            {"id": "tail", "type": "shell", "params": {"command": "echo '${gen.response}'"}},
        ],
    }
    wf = tmp_path / "llm_wf.pflow.md"
    write_workflow_file(ir, wf)
    return wf


def test_llm_failed_node_resumes_without_confirmation(home, tmp_path, mock_llm_client, monkeypatch):
    """A failed ``llm`` K is idempotent — resume runs with NO --force and NO confirm prompt."""
    state = {"fail": True}
    real = mock_llm_client.complete

    def flaky(*, model: str, prompt: str, **kwargs: Any) -> Any:
        if state["fail"] and "refine" in prompt:
            from pflow.core.exceptions import InvalidRequestError

            raise InvalidRequestError("injected llm failure", model=model)
        return real(model=model, prompt=prompt, **kwargs)

    monkeypatch.setattr("pflow.nodes.llm.llm.complete", flaky)
    # If resume ever tried to prompt/confirm for an llm K, this would fire (it must not).
    monkeypatch.setattr(
        "pflow.cli.commands.resume.click.confirm",
        lambda *a, **k: pytest.fail("llm K must not prompt for confirmation"),
    )

    wf = _write_llm_wf(tmp_path)
    exec_id = _run_to_failure_llm(wf)
    state["fail"] = False
    result = _runner().invoke(cli, ["resume", exec_id])  # no --force
    assert result.exit_code == 0, result.stderr
    assert "⤷ Resumed from" in result.stderr


def _run_to_failure_llm(wf: Path) -> str:
    result = _runner().invoke(cli, [str(wf)])
    assert result.exit_code == 1, result.stderr
    match = _HINT_RE.search(result.stderr)
    assert match, result.stderr
    return match.group(1)


# --- Stale-workflow gate (§E step 3) -----------------------------------------


def test_stale_hash_refusal_after_edit(home, shell_wf):
    exec_id = _run_to_failure(shell_wf)
    shell_wf.write_text(shell_wf.read_text() + "\n<!-- edited since the failed run -->\n")
    result = _runner().invoke(cli, ["resume", exec_id, "mode=ok"])
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "edited since the failed run" in combined
    assert "--force" in combined


def test_stale_hash_force_override_runs(home, shell_wf):
    exec_id = _run_to_failure(shell_wf)
    shell_wf.write_text(shell_wf.read_text() + "\n<!-- edited -->\n")
    result = _runner().invoke(cli, ["resume", exec_id, "mode=ok", "--force"])
    assert result.exit_code == 0, result.stderr


def test_stale_unverifiable_message_when_hash_absent(tmp_path):
    """A source predating hash tracking (content_hash=None) says so, never claims an edit."""
    from pflow.cli.commands.resume import _check_content_hash
    from pflow.core.exceptions import ResumeStaleWorkflowError
    from pflow.execution.result import ResolvedWorkflow
    from pflow.runtime.workflow_trace import ResumeSource

    resolved = ResolvedWorkflow(
        ir={"nodes": [{"id": "a", "type": "shell", "params": {"command": "true"}}]}, source="file"
    )
    source = ResumeSource(
        path=tmp_path / "t.json",
        workflow_path="/x/wf.pflow.md",
        execution_id="e1",
        entry_node_id="a",
        last_completed_node_id=None,
        events=[],
        inputs=None,
        content_hash=None,
        final_status="failed",
    )
    with pytest.raises(ResumeStaleWorkflowError) as exc:
        _check_content_hash(resolved, source, force=False)
    assert "predates" in str(exc.value)
    # --force bypasses even the unverifiable case.
    _check_content_hash(resolved, source, force=True)


# --- Disambiguation (existence precedence, §E step 2) ------------------------


def test_mistyped_uuid_yields_combined_missing_error(home):
    result = _runner().invoke(cli, ["resume", "00000000-0000-0000-0000-000000000000"])
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "No run with execution id" in combined
    assert "no workflow by that name" in combined
    # Never leak resolve_workflow's wrong-namespace "did you mean" suggestions.
    assert "did you mean" not in combined.lower()


def test_uuid_shaped_saved_name_resolves_as_workflow(home):
    """A saved workflow whose NAME is uuid-shaped resumes by name (existence precedence)."""
    from pflow.core.workflow.manager import WorkflowManager

    uuid_name = "12345678-1234-1234-1234-123456789abc"
    saved_path = WorkflowManager().save(uuid_name, _SHELL_WF)
    assert Path(saved_path).exists()

    _run_to_failure(Path(saved_path))
    result = _runner().invoke(cli, ["resume", uuid_name, "mode=ok", "--force"])
    assert result.exit_code == 0, result.stderr
    assert "step2-ran" in result.stdout


# --- Nothing to resume / JSON shape / usage ----------------------------------


def test_nothing_to_resume_when_run_succeeded(home, shell_wf):
    ok = _runner().invoke(cli, [str(shell_wf), "mode=ok"])
    assert ok.exit_code == 0, ok.stderr
    result = _runner().invoke(cli, ["resume", str(shell_wf)])
    assert result.exit_code == 1
    assert "already succeeded" in (result.stdout + result.stderr)


def test_json_refusal_shape(home, shell_wf):
    exec_id = _run_to_failure(shell_wf)
    result = _runner().invoke(cli, ["resume", exec_id, "mode=ok", "--output-format", "json"])
    assert result.exit_code == 1
    import json

    doc = json.loads(result.stdout)
    assert doc["success"] is False
    assert doc["status"] == "failed"
    assert doc["errors"][0]["context"]["execution_id"] == exec_id


def test_bare_resume_is_usage_error(home):
    result = _runner().invoke(cli, ["resume"])
    assert result.exit_code == 2
    assert "Missing TARGET" in (result.stdout + result.stderr)


def test_failed_run_with_no_trace_is_a_clear_missing_error(home, shell_wf):
    """GH #255 close-out: a run that wrote no trace (--no-trace / pre-engine) → clear refusal, never a silent re-run."""
    failed = _runner().invoke(cli, ["--no-trace", str(shell_wf), "mode=bad"])
    assert failed.exit_code == 1
    result = _runner().invoke(cli, ["resume", str(shell_wf), "mode=ok"])
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "No resumable run" in combined or "No run" in combined
    # It must NOT have silently executed the workflow.
    assert "step2..." not in result.stderr


def test_stray_flag_after_target_is_usage_error(home, shell_wf):
    _run_to_failure(shell_wf)
    result = _runner().invoke(cli, ["resume", str(shell_wf), "--frobnicate"])
    assert result.exit_code == 2


def test_dash_token_target_after_separator_is_rejected(home):
    """`--` forwards a dash token to our arg splitter (past Click); it must reject it, not treat it as a workflow."""
    result = _runner().invoke(cli, ["resume", "--", "--foo"])
    assert result.exit_code == 2
    assert "key=value" in (result.stdout + result.stderr)


# --- Failed-run resume hint (§E step 10) -------------------------------------


def test_failed_run_prints_resume_hint(home, shell_wf):
    result = _runner().invoke(cli, [str(shell_wf), "mode=bad"])
    assert result.exit_code == 1
    assert "To resume from the failed step: pflow resume " in result.stderr


def test_failed_run_omits_hint_under_no_trace(home, shell_wf):
    result = _runner().invoke(cli, ["--no-trace", str(shell_wf), "mode=bad"])
    assert result.exit_code == 1
    assert "pflow resume" not in result.stderr


def test_failed_run_hint_survives_print_mode(home, shell_wf):
    """Agent-UX (review 2026-07-04): ``-p`` suppresses the trace-location line but NOT
    the resume hint — a ``-p`` agent otherwise has no way to learn the resume target.
    stdout stays data-only; the hint rides stderr."""
    result = _runner().invoke(cli, [str(shell_wf), "mode=bad", "-p"])
    assert result.exit_code == 1
    assert "To resume from the failed step: pflow resume " in result.stderr
    assert "pflow resume" not in result.stdout


def test_failed_run_json_document_carries_resume_fields(home, shell_wf):
    """Agent-UX (review 2026-07-04): the JSON failure document carries the resume target
    (``execution_id`` + literal ``resume_command``) so a stdout-only JSON consumer can act
    without scraping the stderr prose hint."""
    result = _runner().invoke(cli, [str(shell_wf), "mode=bad", "--output-format", "json"])
    assert result.exit_code == 1
    document = json.loads(result.stdout)
    assert document["success"] is False
    exec_id = document["execution_id"]
    assert document["resume_command"] == f"pflow resume {exec_id}"
    # The id is real: the stderr hint names the same run.
    assert f"pflow resume {exec_id}" in result.stderr


def test_failed_run_json_document_omits_resume_fields_under_no_trace(home, shell_wf):
    """No trace on disk → nothing to resume → the JSON document must not advertise one."""
    result = _runner().invoke(cli, ["--no-trace", str(shell_wf), "mode=bad", "--output-format", "json"])
    assert result.exit_code == 1
    document = json.loads(result.stdout)
    assert "execution_id" not in document
    assert "resume_command" not in document


# --- --dry-run (Decision 2) --------------------------------------------------


def test_dry_run_plans_the_tail_only(home, shell_wf):
    """The plan covers K onward — the resume header names K, entries start at K, no side effect."""
    exec_id = _run_to_failure(shell_wf)
    # No --force needed: --dry-run never runs K, so the side-effect confirm is skipped.
    result = _runner().invoke(cli, ["resume", exec_id, "mode=ok", "--dry-run"])
    assert result.exit_code == 0, result.stderr
    out = result.stdout + result.stderr
    assert "Resuming from 'step2'" in out
    assert "1 upstream step restored" in out
    # step1 is restored, not planned; the plan is step2 → step3.
    assert "▸ step2" in out and "▸ step3" in out
    assert "▸ step1" not in out


def test_dry_run_json_carries_resume_block(home, shell_wf):
    exec_id = _run_to_failure(shell_wf)
    result = _runner().invoke(cli, ["resume", exec_id, "mode=ok", "--dry-run", "--output-format", "json"])
    assert result.exit_code == 0, result.stderr
    import json

    doc = json.loads(result.stdout)
    assert [e["node_id"] for e in doc["plan"]] == ["step2", "step3"]
    assert doc["resume"] == {
        "entry_node": "step2",
        "restored_nodes": ["step1"],
        "execution_id": exec_id,
    }


def test_dry_run_still_refuses_stale_workflow(home, shell_wf):
    """Preview mirrors the real resume: a stale workflow refuses without --force even for --dry-run."""
    exec_id = _run_to_failure(shell_wf)
    shell_wf.write_text(shell_wf.read_text() + "\n<!-- edited -->\n")
    result = _runner().invoke(cli, ["resume", exec_id, "mode=ok", "--dry-run"])
    assert result.exit_code == 1
    assert "edited since the failed run" in (result.stdout + result.stderr)


# --- Incomplete-run between-nodes resolution (Decision 7 / §E step 4) ---------


def _resolved(ir: dict) -> Any:
    from pflow.execution.result import ResolvedWorkflow

    return ResolvedWorkflow(ir=ir, source="file", file_path="/x/wf.pflow.md")


def _between_source(last_completed: str) -> Any:
    from pflow.runtime.workflow_trace import ResumeSource

    return ResumeSource(
        path=Path("/x/t.json"),
        workflow_path="/x/wf.pflow.md",
        execution_id="inc-1",
        entry_node_id=None,
        last_completed_node_id=last_completed,
        events=[],
        inputs=None,
        content_hash=None,
        final_status="incomplete",
    )


def test_between_nodes_single_default_successor_is_entry():
    from pflow.cli.commands.resume import _resolve_between_nodes_entry

    ir = {
        "nodes": [
            {"id": "step1", "type": "shell", "params": {"command": "echo a"}},
            {"id": "step2", "type": "shell", "params": {"command": "echo b"}},
        ],
        "edges": [{"from": "step1", "to": "step2"}],
    }
    result = _resolve_between_nodes_entry(_resolved(ir), _between_source("step1"))
    assert result.entry_node_id == "step2"


def test_between_nodes_dynamic_code_router_refused():
    from pflow.cli.commands.resume import _resolve_between_nodes_entry
    from pflow.core.exceptions import ResumeNotResumableError

    ir = {
        "nodes": [
            {"id": "router", "type": "code", "params": {"code": "next = 'a'"}},
            {"id": "a", "type": "shell", "params": {"command": "echo a"}},
        ],
        "edges": [{"from": "router", "to": "a", "action": "a"}],
    }
    with pytest.raises(ResumeNotResumableError, match="dynamically"):
        _resolve_between_nodes_entry(_resolved(ir), _between_source("router"))


def test_between_nodes_terminal_node_refused():
    from pflow.cli.commands.resume import _resolve_between_nodes_entry
    from pflow.core.exceptions import ResumeNotResumableError

    ir = {"nodes": [{"id": "only", "type": "shell", "params": {"command": "echo x"}}], "edges": []}
    with pytest.raises(ResumeNotResumableError, match="ambiguous"):
        _resolve_between_nodes_entry(_resolved(ir), _between_source("only"))


def test_between_nodes_missing_last_completed_refused():
    from pflow.cli.commands.resume import _resolve_between_nodes_entry
    from pflow.core.exceptions import ResumeNotResumableError

    ir = {"nodes": [{"id": "other", "type": "shell", "params": {"command": "echo x"}}], "edges": []}
    with pytest.raises(ResumeNotResumableError, match="no longer exists"):
        _resolve_between_nodes_entry(_resolved(ir), _between_source("gone"))


def _write_incomplete_trace_for(wf: Path, *, completed: list[dict], killed_node: str | None = None) -> None:
    """Craft an incomplete (no run.complete) trace on disk for a real workflow path (e2e helper)."""
    import json as _json

    from pflow.execution.runner import workflow_path_id
    from pflow.execution.workflow_resolver import resolve_workflow
    from pflow.runtime.workflow_trace import format_trace_filename
    from tests.shared.trace_jsonl import flatten_trace_to_lines

    wf_path = workflow_path_id(resolve_workflow(str(wf)))
    data = {
        "format_version": "2.5.0",
        "execution_id": "inc-e2e",
        "workflow_name": "wf",
        "workflow_path": wf_path,
        "only_node": None,
        "content_hash": "stale-hash",  # resume uses --force to bypass the hash gate
        "inputs": {"mode": "bad"},
        "nodes": completed,
    }
    lines = [line for line in flatten_trace_to_lines(data) if line.get("kind") != "run.complete"]
    if killed_node is not None:
        next_id = max((line["id"] for line in lines if line.get("kind") == "event"), default=-1) + 1
        lines.append({
            "kind": "node.start",
            "id": next_id,
            "seq": next_id,
            "parent_id": None,
            "node_id": killed_node,
            "node_type": "ShellNode",
            "run_id": "inc-e2e",
        })
    debug = Path.home() / ".pflow" / "debug"
    path = debug / format_trace_filename(wf_path, "wf", "20260101-000000")
    path.write_text("\n".join(_json.dumps(line) for line in lines) + "\n")


def test_incomplete_between_nodes_resumes_at_successor_e2e(home, shell_wf):
    """A killed-between-nodes trace resumes at step1's successor (step2); step1 is restored."""
    _write_incomplete_trace_for(
        shell_wf,
        completed=[
            {
                "node_id": "step1",
                "node_type": "ShellNode",
                "status": "success",
                "node_output": {"stdout": "upstream-value"},
            }
        ],
    )
    result = _runner().invoke(cli, ["resume", str(shell_wf), "mode=ok", "--force"])
    assert result.exit_code == 0, result.stderr
    assert "step2..." in result.stderr and "step1..." not in result.stderr
    assert "done upstream-value step2-ran" in result.stdout


def test_incomplete_killed_mid_node_resumes_at_that_node_e2e(home, shell_wf):
    """A dangling node.start for step2 resumes AT step2 (killed mid-node)."""
    _write_incomplete_trace_for(
        shell_wf,
        completed=[
            {
                "node_id": "step1",
                "node_type": "ShellNode",
                "status": "success",
                "node_output": {"stdout": "upstream-value"},
            }
        ],
        killed_node="step2",
    )
    result = _runner().invoke(cli, ["resume", str(shell_wf), "mode=ok", "--force"])
    assert result.exit_code == 0, result.stderr
    assert "step2..." in result.stderr and "step1..." not in result.stderr


# --- is_side_effecting vocabulary (the class-name trap) ----------------------


@pytest.mark.parametrize(
    ("node_type", "expected"),
    [
        ("llm", False),
        ("shell", True),
        ("code", True),
        ("http", True),
        ("mcp-github-create_issue", True),
        ("claude-code", True),
        ("read-file", True),
        ("write-file", True),
        # The trap: a trace event's node_type is the Python CLASS name, which the
        # CLI must NEVER feed to this predicate — "LLMNode" would wrongly gate llm.
        ("LLMNode", True),
    ],
)
def test_is_side_effecting_speaks_registry_vocabulary(node_type, expected):
    from pflow.runtime.compilation import is_side_effecting

    assert is_side_effecting(node_type) is expected
