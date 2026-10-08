"""Task 180 — resume refuses only when an edit touches a step it restores.

The ruled table (``.taskmaster/tasks/task_180/implementation/show-before-code.md``), row by row,
through the real CLI on REAL failed runs: ``produce`` (shell) → ``shape`` (code) → ``save``
(write-file whose ``${shape.result.txt}`` typo fails template resolution, before it starts). So
``produce`` and ``shape`` are restored and ``save`` is the resume point. ``save`` writes to
``<greeting>.txt``, so the file name shows which input value the resumed tail used.

The loop rows live beside the looping-host fixture (``test_resume_cli.py``), the paused-approval
and escalation rows beside the pause fixtures (``test_paused_cli.py``), and the web endpoint's in
``test_ui_interaction_server.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from pflow.cli.main import cli

pytestmark = pytest.mark.trace_files

_HINT_RE = re.compile(r"pflow resume (\S+)")

_WF = """# Identity Demo

Produce, shape, save — `save` carries a template typo.

## Inputs

### greeting

What to say.

- type: string
- default: hello

## Steps

### produce

Produce the text.

- type: shell
- env:
    GREETING: ${greeting}

```shell command
printf '%s' "$GREETING"
```

### shape

Shape it.

- type: code
- inputs:
    text: ${produce.stdout}

```python code
text: str
result: dict = {"md": "# " + text}
```

### save

Save it.

- type: write-file
- file_path: @DIR@/${greeting}.txt
- content: ${shape.result.txt}
"""

_TYPO, _FIX = "${shape.result.txt}", "${shape.result.md}"


def _step(name: str, marker: Path, extra: str = "") -> str:
    """A shell step that leaves ``marker`` behind when it runs."""
    return f"### {name}\n\nMark that {name} ran.\n\n- type: shell\n{extra}\n```shell command\ntouch {marker.as_posix()}\n```\n\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".pflow" / "debug").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def wf(tmp_path) -> Path:
    path = tmp_path / "identity.pflow.md"
    path.write_text(_WF.replace("@DIR@", tmp_path.as_posix()), encoding="utf-8")
    return path


def _invoke(*args: str) -> Result:
    return CliRunner(mix_stderr=False).invoke(cli, list(args))


def _fail(wf: Path, *args: str) -> str:
    """Run ``wf`` to failure; return the execution id the resume hint names."""
    result = _invoke(str(wf), *args)
    assert result.exit_code == 1, result.stderr
    match = _HINT_RE.search(result.stderr)
    assert match, result.stderr
    return match.group(1)


def _edit(wf: Path, *pairs: tuple[str, str]) -> None:
    text = wf.read_text(encoding="utf-8")
    for old, new in pairs:
        assert old in text, old
        text = text.replace(old, new, 1)
    wf.write_text(text, encoding="utf-8")


def _out(result: Result) -> str:
    return result.stdout + result.stderr


def _refused(exec_id: str, *args: str) -> str:
    result = _invoke("resume", exec_id, *args)
    assert result.exit_code == 1, _out(result)
    combined = _out(result)
    assert "Workflow changed since the original run" in combined
    return combined


def _passes(exec_id: str, *args: str) -> Result:
    result = _invoke("resume", exec_id, *args)
    assert result.exit_code == 0, _out(result)
    assert "Workflow changed" not in _out(result)
    return result


# --- Rows 1-2: the headline — the resume point and prose are free to change ----------------------


def test_row1_fixing_the_resume_point_resumes_without_force(home, tmp_path, wf):
    """#690's loop end to end: fix the typo in the failed step, resume — no --force, no confirmation
    (``save`` never started), the restored upstream is reused, and the run completes."""
    exec_id = _fail(wf)
    _edit(wf, (_TYPO, _FIX))
    dry = _passes(exec_id, "--dry-run")
    assert "Resuming from 'save'" in _out(dry)
    resumed = _passes(exec_id)
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "# hello"
    assert "produce..." not in resumed.stderr  # restored, not re-run


def test_row2_a_prose_edit_on_a_restored_step_passes(home, tmp_path, wf):
    exec_id = _fail(wf)
    _edit(wf, ("Shape it.", "Shape the text."), (_TYPO, _FIX))
    _passes(exec_id)
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "# hello"


# --- Rows 3-6, 12, 13: edits upstream of the resume point refuse, naming what changed -----------


def test_row3_editing_a_restored_step_refuses_naming_only_that_step(home, wf):
    exec_id = _fail(wf)
    _edit(wf, ("printf '%s' \"$GREETING\"", "printf '%s!' \"$GREETING\""))
    combined = _refused(exec_id)
    assert (
        "'produce' was edited. Resume re-runs nothing before 'save' — it restores the saved outputs of the "
        "steps that ran — so that edit would not take effect." in combined
    )
    assert "'shape'" not in combined
    assert "Re-run the workflow from the start so the edit takes effect." in combined
    assert "Pass --force to resume anyway: steps before 'save' keep their saved outputs and are not re-run." in combined
    assert "skipped" not in combined  # nothing was inserted
    assert "fire again" not in combined  # `save` never started — --force re-fires nothing
    # Preview mirrors the real resume.
    assert "'produce' was edited." in _refused(exec_id, "--dry-run")


def test_row4_a_step_inserted_before_the_resume_point_refuses(home, tmp_path, wf):
    marker = tmp_path / "prepare-ran"
    exec_id = _fail(wf)
    _edit(wf, ("### save\n", _step("prepare", marker) + "### save\n"), (_TYPO, _FIX))
    combined = _refused(exec_id)
    assert "'shape' now continues to 'prepare', which never ran — resume would skip it." in combined
    assert "keep their saved outputs and are not re-run ('prepare' is skipped)." in combined
    # Regression guard (passes on the pre-180 code too): --force keeps today's behaviour — the
    # inserted step is skipped, as the refusal says.
    forced = _invoke("resume", exec_id, "--force")
    assert forced.exit_code == 0, _out(forced)
    assert (tmp_path / "hello.txt").exists()
    assert not marker.exists()


def test_row5_a_new_first_step_refuses(home, tmp_path, wf):
    exec_id = _fail(wf)
    _edit(wf, ("### produce\n", _step("banner", tmp_path / "banner-ran") + "### produce\n"), (_TYPO, _FIX))
    combined = _refused(exec_id)
    assert "The workflow now starts at 'banner', which never ran — resume would skip it." in combined


def test_row6_rerouting_a_restored_step_refuses(home, wf):
    exec_id = _fail(wf)
    _edit(wf, ("- type: shell\n", "- type: shell\n- next: save\n"), (_TYPO, _FIX))
    combined = _refused(exec_id)
    assert "'produce' now continues to 'save' instead of 'shape'." in combined


def test_rerouting_to_a_step_the_resume_still_reaches_never_claims_it_is_skipped(home, tmp_path, wf):
    """`notify` never ran, but the resume reaches it (after `save`) — so the reroute refuses with the
    factual "instead of" lead, never "would skip it" (and --force names nothing as skipped)."""
    wf.write_text(wf.read_text(encoding="utf-8") + "\n" + _step("notify", tmp_path / "notify-ran"), encoding="utf-8")
    exec_id = _fail(wf)
    _edit(wf, ("- type: shell\n", "- type: shell\n- next: notify\n"), (_TYPO, _FIX))
    combined = _refused(exec_id)
    assert "'produce' now continues to 'notify' instead of 'shape'." in combined
    assert "never ran" not in combined and "skipped" not in combined


def test_row12_a_removed_resume_point_refuses_without_blaming_its_predecessor(home, wf):
    exec_id = _fail(wf)
    _edit(wf, ("### save\n", "### store\n"))
    combined = _refused(exec_id)
    assert "The resume point 'save' is no longer in the workflow." in combined
    assert "'shape'" not in combined  # its changed `next` is not blamed
    assert "--force" not in combined  # --force cannot resume at a step that is gone


def test_row13_a_removed_restored_step_is_named_as_removed(home, wf):
    exec_id = _fail(wf)
    text = wf.read_text(encoding="utf-8")
    shape_section = text[text.index("### shape\n") : text.index("### save\n")]
    _edit(wf, (shape_section, ""), (_TYPO, "${produce.stdout}"))
    combined = _refused(exec_id)
    assert "'shape' is no longer in the workflow (resume would still restore its saved output)." in combined


# --- Rows 7-9: edits at or after the resume point pass ------------------------------------------


def test_row7_a_step_appended_after_the_resume_point_passes_and_runs(home, tmp_path, wf):
    marker = tmp_path / "notify-ran"
    exec_id = _fail(wf)
    _edit(wf, (_TYPO, _FIX))
    wf.write_text(wf.read_text(encoding="utf-8") + "\n" + _step("notify", marker), encoding="utf-8")
    _passes(exec_id)
    assert marker.exists()
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "# hello"


def test_row8_an_edge_change_downstream_passes(home, tmp_path, wf):
    marker = tmp_path / "notify-ran"
    wf.write_text(wf.read_text(encoding="utf-8") + "\n" + _step("notify", marker), encoding="utf-8")
    exec_id = _fail(wf)
    # `save` (the resume point) now routes to `notify` only on error, and ends otherwise.
    _edit(
        wf,
        (_TYPO, _FIX + "\n- on-error: notify\n- next: end"),
        ("- type: shell\n\n```shell command\ntouch", "- type: shell\n- next: end\n\n```shell command\ntouch"),
    )
    _passes(exec_id)
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "# hello"
    assert not marker.exists()  # `save` succeeded, so its error route never ran


def test_row9_an_edited_input_default_passes_and_the_recorded_value_wins(home, tmp_path, wf):
    """Unchanged semantics, pinned: the resumed tail sees the recorded input; KEY=VALUE overrides it."""
    exec_id = _fail(wf)
    _edit(wf, ("- default: hello", "- default: hi"), (_TYPO, _FIX))
    _passes(exec_id)
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "# hello"
    assert not (tmp_path / "hi.txt").exists()


def test_key_value_still_overrides_the_recorded_input(home, tmp_path, wf):
    exec_id = _fail(wf)
    _edit(wf, (_TYPO, _FIX))
    _passes(exec_id, "greeting=cli")
    assert (tmp_path / "cli.txt").read_text(encoding="utf-8") == "# hello"  # upstream stays restored


# --- Row 10: a `## Cache` chunk is part of the step that uses it ---------------------------------

_LLM_MODEL = "anthropic/claude-haiku-4-5"

_CACHE_WF = f"""# Cache Demo

A restored LLM step reads a `## Cache` chunk; the last step fails.

## Cache

```cache
Background for the summary:

${{produce.stdout}}
```

## Steps

### produce

Produce the text.

- type: shell

```shell command
printf 'facts'
```

### summarize

Summarize it.

- type: llm
- model: {_LLM_MODEL}
- prompt_cache: [produce.stdout]

```prompt
Summarize.
```

### boom

Fail.

- type: shell
- env:
    SUMMARY: ${{summarize.response}}

```shell command
exit 1
```
"""


def test_row10_editing_a_cache_chunk_refuses_naming_the_step_that_uses_it(home, tmp_path, mock_llm_client):
    mock_llm_client.set_response(_LLM_MODEL, None, {"response": "a summary"})
    wf = tmp_path / "cache.pflow.md"
    wf.write_text(_CACHE_WF, encoding="utf-8")
    exec_id = _fail(wf)
    _edit(wf, ("Background for the summary:", "Background for a shorter summary:"))
    combined = _refused(exec_id)
    assert "'summarize' was edited (a `## Cache` chunk it uses changed)." in combined
    assert "'produce'" not in combined


def test_changing_which_cache_chunks_a_step_uses_is_an_edit_to_the_step(home, tmp_path, mock_llm_client):
    """A different selection is not a chunk-content change — the lead must not send the agent to `## Cache`."""
    mock_llm_client.set_response(_LLM_MODEL, None, {"response": "a summary"})
    wf = tmp_path / "cache.pflow.md"
    wf.write_text(_CACHE_WF, encoding="utf-8")
    exec_id = _fail(wf)
    _edit(wf, ("- prompt_cache: [produce.stdout]\n", ""))
    combined = _refused(exec_id)
    assert "'summarize' was edited." in combined
    assert "## Cache" not in combined


# --- Row 15: a sub-workflow's child file is outside both hashes (pre-existing, unchanged) -------


def test_row15_editing_a_sub_workflows_child_file_still_passes(home, tmp_path):
    child = tmp_path / "child.pflow.md"
    child.write_text(
        "# Child\n\nProduce.\n\n## Outputs\n\n### text\n\nThe text.\n\n- source: ${make.stdout}\n\n"
        "## Steps\n\n### make\n\nMake it.\n\n- type: shell\n\n```shell command\nprintf 'child-v1'\n```\n",
        encoding="utf-8",
    )
    wf = tmp_path / "host.pflow.md"
    wf.write_text(
        "# Host\n\nA sub-workflow, then a typo.\n\n## Steps\n\n### produce\n\nRun the child.\n\n"
        "- type: workflow\n- workflow: ./child.pflow.md\n\n### save\n\nSave it.\n\n- type: write-file\n"
        f"- file_path: {(tmp_path / 'out.txt').as_posix()}\n- content: ${{produce.text.missing}}\n",
        encoding="utf-8",
    )
    exec_id = _fail(wf)
    child.write_text(child.read_text(encoding="utf-8").replace("child-v1", "child-v2"), encoding="utf-8")
    _edit(wf, ("${produce.text.missing}", "${produce.text}"))
    _passes(exec_id)
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "child-v1"  # restored, not re-run


# --- Row 16 + D6: a trace without per-step identity keeps the whole-workflow compare ------------


def _age_trace(home: Path, exec_id: str, *, drop_lines: Any = None) -> None:
    """Rewrite the run's real trace into the 2.8.0 shape: no ``step_identity`` on the meta line."""
    for path in (home / ".pflow" / "debug").glob("workflow-trace-*.json"):
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if lines[0].get("execution_id") != exec_id:
            continue
        lines[0].pop("step_identity")
        lines[0]["format_version"] = "2.8.0"
        kept = [line for line in lines if drop_lines is None or not drop_lines(line)]
        path.write_text("".join(json.dumps(line) + "\n" for line in kept), encoding="utf-8")
        return
    raise AssertionError(f"no trace for {exec_id}")


def test_row16_an_older_trace_refuses_any_edit_and_says_why(home, wf):
    exec_id = _fail(wf)
    _age_trace(home, exec_id)
    _edit(wf, ("Shape it.", "Shape the text."), (_TYPO, _FIX))  # row 2's edit, which passes on 2.9.0
    combined = _refused(exec_id)
    assert (
        "This run was recorded by an older pflow version that did not record each step's definition, "
        "so resume cannot tell which step changed." in combined
    )
    assert "Pass --force to resume anyway" in combined


def test_row16_an_older_trace_of_an_unedited_workflow_still_resumes(home, tmp_path, wf):
    exec_id = _fail(wf)
    _age_trace(home, exec_id)
    result = _invoke("resume", exec_id)  # unedited: the same typo fails again, past the gate
    assert result.exit_code == 1
    assert "Workflow changed" not in _out(result)
    assert "Template Resolution Failed" in result.stderr


# --- D1b: a batched sub-workflow host's never-started proof needs a 2.9.0 trace ----------------

_LEDGER_CHILD_WF = """# Ledger Child

Append the tag to a ledger.

## Inputs

### tag

The tag.

- type: string

## Outputs

### out

The output.

- source: ${fire.stdout}

## Steps

### fire

Append.

- type: shell
- env:
    TAG: ${tag}

```shell command
echo "fired $TAG" >> @LEDGER@
```
"""

_BATCHED_HOST_WF = """# Batched Host

A batched sub-workflow host; item [1] fails template resolution after item [0] fired.

## Steps

### produce

Items.

- type: code

```python code
result: list = [{"t": "a"}, {"x": "b"}]
```

### host

Run the child per item.

- type: workflow
- workflow: ./child.pflow.md
- inputs:
    tag: ${item.t}
- batch:
    items: ${produce.result}
    error_handling: fail_fast
"""


def _batched_host_run(home: Path, tmp_path: Path) -> tuple[str, Path]:
    ledger = tmp_path / "ledger.txt"
    (tmp_path / "child.pflow.md").write_text(_LEDGER_CHILD_WF.replace("@LEDGER@", ledger.as_posix()), encoding="utf-8")
    wf = tmp_path / "host.pflow.md"
    wf.write_text(_BATCHED_HOST_WF, encoding="utf-8")
    exec_id = _fail(wf)
    assert ledger.read_text(encoding="utf-8").splitlines() == ["fired a"]  # item [0]'s child fired
    return exec_id, ledger


def _is_host_start(line: dict[str, Any]) -> bool:
    return line.get("kind") == "node.start" and line.get("node_id") == "host" and line.get("parent_id") is None


def test_batched_host_on_an_older_trace_still_needs_confirmation(home, tmp_path):
    """A 2.3-2.8 trace never wrote a batched host's ``node.start``, so its failed event without one
    proves nothing: the confirmation stays (the narrowed carve-out)."""
    exec_id, ledger = _batched_host_run(home, tmp_path)
    _age_trace(home, exec_id, drop_lines=_is_host_start)
    result = _invoke("resume", exec_id)
    assert result.exit_code == 1
    assert "Resuming re-runs step 'host' (a workflow step)" in _out(result)
    assert ledger.read_text(encoding="utf-8").splitlines() == ["fired a"]  # nothing re-fired


def test_batched_host_without_a_start_on_a_current_trace_is_proof_it_never_began(home, tmp_path):
    """Presence twin of the test above: the same start-less host event on a trace that DOES carry
    ``step_identity`` is trusted (every host writes ``node.start`` since 2.9.0) — so the carve-out is
    keyed on the trace's era, not on the step type."""
    exec_id, _ = _batched_host_run(home, tmp_path)
    for path in (home / ".pflow" / "debug").glob("workflow-trace-*.json"):
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        path.write_text("".join(json.dumps(line) + "\n" for line in lines if not _is_host_start(line)), "utf-8")
    result = _invoke("resume", exec_id)
    assert "Resume needs confirmation" not in _out(result)
    assert "Resuming re-runs step 'host'" not in _out(result)


# --- Resume of a resume: the start step is recorded, never derived from events ------------------

_RECOVERED_START_WF = """# Recovered Start

The first step fails and recovers through on-error; the last step has a typo.

## Steps

### flaky

Fail, then recover.

- type: shell
- on-error: recover
- next: save

```shell command
exit 1
```

### save

Save it.

- type: write-file
- file_path: @OUT@
- content: ${recover.stdout.txt}
- next: end

### recover

Recover.

- type: shell
- next: save

```shell command
printf '{"md": "recovered"}'
```
"""


def test_resume_of_a_resume_with_a_failed_recovered_start_step_passes(home, tmp_path):
    """The attempt trace re-records only what it seeded — never the failed-and-recovered start step.
    Its recorded start is still ``flaky``, so resuming the attempt (no edit) passes the gate, and so
    does the final resume after the fix."""
    out = tmp_path / "out.txt"
    wf = tmp_path / "recovered.pflow.md"
    wf.write_text(_RECOVERED_START_WF.replace("@OUT@", out.as_posix()), encoding="utf-8")
    first = _fail(wf)
    again = _invoke("resume", first)  # unedited: the typo fails again, past the gate
    assert again.exit_code == 1 and "Workflow changed" not in _out(again)
    attempt = _HINT_RE.search(again.stderr)
    assert attempt and attempt.group(1) != first
    _edit(wf, ("${recover.stdout.txt}", "${recover.stdout.md}"))
    _passes(attempt.group(1))
    assert out.read_text(encoding="utf-8") == "recovered"
