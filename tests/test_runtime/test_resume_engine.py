"""Engine resume re-entry + self-contained attempt trace (Task 164, Phase 2).

End-to-end through ``WorkflowRunner().run(..., resume_source=...)`` on REAL trace
files (pitfall #20): a failing run's trace is loaded via ``load_resume_source``
and resumed; assertions cover walk re-entry at K, upstream-not-re-executed,
Decision 6 self-containment (restored events re-recorded → resume-of-a-resume
and later ``--only`` runs seed from the newest attempt alone — the poisoning
regression), aggregate/cost exclusion of restored events, ``resumed_from``
lineage on the meta line, success-path visibility (text indicator + JSON
fields), the branch/coalesce scenario, and the empty-output ``is not None``
re-record stamp.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest

from pflow.core.exceptions import InvalidRequestError
from pflow.core.trace_io import load_trace_file
from pflow.execution.formatters.success_formatter import (
    format_execution_success,
    format_resume_indicator,
    format_success_as_text,
)
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.execution.workflow_resolver import resolve_workflow
from pflow.runtime.engine import WorkflowEngine
from pflow.runtime.workflow_trace import (
    ResumeSource,
    WorkflowTraceCollector,
    load_resume_source,
    seed_snapshot_into_shared,
)
from tests.shared.markdown_utils import write_workflow_file

pytestmark = pytest.mark.trace_files

MODEL = "test/resume-model"

# The autouse MockLLMClient serializes its default dict response to JSON text;
# that text IS what ${step.response} resolves to downstream.
MOCK_RESPONSE_TEXT = '{"response": "mock response"}'
EXPECTED_STDOUT = f"{MOCK_RESPONSE_TEXT}|{MOCK_RESPONSE_TEXT}"

# The step-2 llm prompt carries this marker; the flaky adapter keys failure
# injection off it (prompts are what cross the adapter seam, not node ids).
_STEP2_MARKER = "step-two refine"


def _write_three_step_workflow(tmp_path: Path, *, step3_suffix: str = "") -> Path:
    """llm → llm → shell; step3 references BOTH llm steps.

    The double reference is load-bearing for the poisoning-regression tests:
    a later seed that lost step1 (attempt trace not self-contained) fails
    step3's template resolution instead of silently passing.
    """
    ir = {
        "nodes": [
            {"id": "step1", "type": "llm", "params": {"model": MODEL, "prompt": "step-one summarize"}},
            {
                "id": "step2",
                "type": "llm",
                "params": {"model": MODEL, "prompt": f"{_STEP2_MARKER}: ${{step1.response}}"},
            },
            {
                "id": "step3",
                "type": "shell",
                "params": {"command": "printf '%s|%s' '${step1.response}' '${step2.response}'" + step3_suffix},
            },
        ],
    }
    wf = tmp_path / "wf.pflow.md"
    write_workflow_file(ir, wf)
    return wf


@pytest.fixture()
def flaky_step2(mock_llm_client, monkeypatch) -> dict[str, Any]:
    """Make the step-2 llm call fail (deterministic 4xx — no retry burn) while the flag is set."""
    state = {"fail": True}
    real_complete = mock_llm_client.complete

    def flaky(*, model: str, prompt: str, **kwargs: Any) -> Any:
        if state["fail"] and _STEP2_MARKER in prompt:
            raise InvalidRequestError("injected step-two failure", model=model)
        return real_complete(model=model, prompt=prompt, **kwargs)

    monkeypatch.setattr("pflow.nodes.llm.llm.complete", flaky)
    return state


def _fail_then_load(wf: Path, flaky_state: dict[str, Any]) -> tuple[Any, ResumeSource]:
    """Run to failure at step2, load the trace as a ResumeSource, clear the failure flag."""
    result = WorkflowRunner().run(str(wf), {}, RunnerConfig())
    assert not result.success, "run 1 was supposed to fail at step2"
    trace_path = result.trace.save_to_file()
    assert trace_path is not None
    flaky_state["fail"] = False
    source = load_resume_source(execution_id=result.trace.execution_id, debug_dir=trace_path.parent)
    assert source.entry_node_id == "step2"
    return result, source


def _resume(wf: Path, source: ResumeSource) -> Any:
    return WorkflowRunner().run(str(wf), dict(source.inputs or {}), RunnerConfig(), resume_source=source)


# --- Walk re-entry -----------------------------------------------------------


def test_resume_reenters_at_failed_node_and_skips_upstream(tmp_path, flaky_step2, mock_llm_client) -> None:
    """Upstream is restored (NOT re-executed), K + tail run, outputs correct."""
    wf = _write_three_step_workflow(tmp_path)
    run1, source = _fail_then_load(wf, flaky_step2)

    result = _resume(wf, source)

    assert result.success
    # step1's llm call happened exactly ONCE across both runs (mock call count).
    step1_calls = [c for c in mock_llm_client.call_history_full if "step-one" in c.get("prompt", "")]
    assert len(step1_calls) == 1, "resume must not re-execute the restored upstream llm step"
    # Only K and its tail executed this run; step1 was seeded, never walked.
    exec_state = result.shared_after["__execution__"]
    assert exec_state["completed_nodes"] == ["step2", "step3"]
    assert exec_state["restored_nodes"] == ["step1"]
    assert exec_state["resumed_from"] == run1.trace.execution_id
    assert exec_state["resume_entry_node"] == "step2"
    # Downstream templates resolved against BOTH the restored and the fresh value.
    assert result.shared_after["step3"]["stdout"] == EXPECTED_STDOUT


def test_engine_rejects_resume_from_with_only_node() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        WorkflowEngine(resume_from="a", only_node="b")


def test_runner_rejects_unresolved_entry_node(tmp_path) -> None:
    """A between-nodes source (entry None) must be resolved by the CLI before run()."""
    source = ResumeSource(
        path=tmp_path / "t.json",
        workflow_path=str(tmp_path / "wf.pflow.md"),
        execution_id="e1",
        entry_node_id=None,
        last_completed_node_id="a",
        events=[],
        inputs=None,
        content_hash=None,
    )
    with pytest.raises(ValueError, match="entry_node_id"):
        WorkflowRunner().run(
            {"nodes": [{"id": "a", "type": "shell", "params": {"command": "true"}}]},
            {},
            RunnerConfig(),
            resume_source=source,
        )


def test_planner_rejects_unresolved_entry_node(tmp_path) -> None:
    """plan() mirrors run()'s guard: an unresolved between-nodes source would
    otherwise plan the whole workflow while the header claims a resume (S2)."""
    source = ResumeSource(
        path=tmp_path / "t.json",
        workflow_path=str(tmp_path / "wf.pflow.md"),
        execution_id="e1",
        entry_node_id=None,
        last_completed_node_id="a",
        events=[],
        inputs=None,
        content_hash=None,
    )
    with pytest.raises(ValueError, match="entry_node_id"):
        WorkflowRunner().plan(
            {"nodes": [{"id": "a", "type": "shell", "params": {"command": "true"}}]},
            {},
            RunnerConfig(),
            resume_source=source,
        )


def test_resume_after_entry_node_removed_is_a_typed_refusal(tmp_path, flaky_step2) -> None:
    """K renamed/removed since the failed run → ResumeNotResumableError naming K,
    never find_node_by_id's misattributed "compiler bug" CompilationError."""
    wf = _write_three_step_workflow(tmp_path)
    _, source = _fail_then_load(wf, flaky_step2)

    # Edit the workflow: rename K. (The CLI's content-hash gate would refuse
    # first; this pins the engine's own guard for --force / library callers.)
    wf.write_text(wf.read_text(encoding="utf-8").replace("step2", "step2-renamed"), encoding="utf-8")
    result = _resume(wf, source)

    assert not result.success
    messages = " ".join(str(d.message) for d in result.diagnostics)
    assert "'step2' no longer exists" in messages
    assert "compiler bug" not in messages.lower()


# --- Self-contained attempt trace (Decision 6) -------------------------------


def test_attempt_trace_restored_events_and_aggregates(tmp_path, flaky_step2, mock_llm_client) -> None:
    """Restored events: status cached + restored flag + zero duration; excluded from
    nodes_executed and cost; ``resumed_from`` rides the meta line; source untouched."""
    mock_llm_client.set_response(MODEL, None, {"response": "mock response"}, cost_usd=0.5)
    wf = _write_three_step_workflow(tmp_path)
    run1, source = _fail_then_load(wf, flaky_step2)
    source_bytes = source.path.read_bytes()

    result = _resume(wf, source)
    assert result.success
    attempt_path = result.trace.save_to_file()
    trace = load_trace_file(attempt_path)

    assert trace["resumed_from"] == run1.trace.execution_id
    events_by_id = {e["node_id"]: e for e in trace["nodes"]}
    restored_event = events_by_id["step1"]
    assert restored_event["status"] == "cached"
    assert restored_event["restored"] is True
    assert restored_event["duration_ms"] == 0.0
    assert restored_event["node_output"]["response"] == MOCK_RESPONSE_TEXT
    for fresh in ("step2", "step3"):
        assert "restored" not in events_by_id[fresh]
        assert events_by_id[fresh]["status"] == "success"
    # Aggregates: restored excluded from nodes_executed; cost counts ONLY this
    # run's llm call (step2 @ 0.5) — the restored step1's 0.5 is a cached boundary.
    assert trace["nodes_executed"] == 2
    assert trace["final_status"] == "success"
    assert trace["llm_summary"]["total_cost_usd"] == 0.5
    # Lineage is a new trace, never an append: the source is byte-identical.
    assert source.path.read_bytes() == source_bytes


def test_only_after_successful_resume_seeds_from_attempt_trace(tmp_path, flaky_step2) -> None:
    """The --only poisoning regression: a successful resumed attempt becomes the
    newest success trace; --only must seed cleanly from it — which only works
    because the attempt re-recorded the restored upstream events (Decision 6)."""
    wf = _write_three_step_workflow(tmp_path)
    _, source = _fail_then_load(wf, flaky_step2)
    resume_result = _resume(wf, source)
    assert resume_result.success
    assert resume_result.trace.save_to_file() is not None

    only_result = WorkflowRunner().run(str(wf), {}, RunnerConfig(only_node="step3"))

    assert only_result.success, [str(d) for d in only_result.diagnostics]
    # step3 resolved ${step1.response} (a RESTORED event in the attempt trace)
    # and ${step2.response} (a fresh one) — the attempt trace is a coherent
    # full-run snapshot source.
    assert only_result.shared_after["step3"]["stdout"] == EXPECTED_STDOUT
    assert set(only_result.shared_after["__execution__"]["restored_nodes"]) == {"step1", "step2"}


def test_resume_of_a_resume_seeds_from_newest_attempt_alone(tmp_path, flaky_step2) -> None:
    """Chain: run1 fails at step2 → attempt A fails at step3 → attempt B resumes
    from A's trace ALONE (upstream present via A's re-recorded restored events)."""
    exit_file = tmp_path / "step3-exit"
    exit_file.write_text("1")
    wf = _write_three_step_workflow(tmp_path, step3_suffix=f"; exit $(cat {exit_file})")
    _, source_1 = _fail_then_load(wf, flaky_step2)

    attempt_a = _resume(wf, source_1)
    assert not attempt_a.success, "attempt A was supposed to fail at step3"
    a_path = attempt_a.trace.save_to_file()

    exit_file.write_text("0")
    source_a = load_resume_source(execution_id=attempt_a.trace.execution_id, debug_dir=a_path.parent)
    # Decision 6 direct pin: A's trace alone carries the restored step1 event.
    assert source_a.entry_node_id == "step3"
    assert [e["node_id"] for e in source_a.events] == ["step1", "step2", "step3"]

    attempt_b = _resume(wf, source_a)

    assert attempt_b.success
    exec_state = attempt_b.shared_after["__execution__"]
    assert exec_state["completed_nodes"] == ["step3"]
    assert exec_state["restored_nodes"] == ["step1", "step2"]
    assert exec_state["resumed_from"] == attempt_a.trace.execution_id
    assert attempt_b.shared_after["step3"]["stdout"] == EXPECTED_STDOUT


def test_restored_large_output_reinterns_blob_and_round_trips(tmp_path, flaky_step2, mock_llm_client) -> None:
    """A restored node's LARGE output (≥ INTERN_MIN_BYTES) must be re-interned as an
    inline ``blob`` line in the ATTEMPT trace (fresh per-run declared set), and a
    second resume must resolve it back to the full value — the braindump's open
    'restored re-record + blob interning' verification item.
    """
    import json

    from pflow.core.trace_io import BLOB_SENTINEL, INTERN_MIN_BYTES

    big_response = "A" * (2 * INTERN_MIN_BYTES)
    mock_llm_client.set_response(MODEL, None, {"response": big_response})
    expected_text = json.dumps({"response": big_response})

    exit_file = tmp_path / "step3-exit"
    exit_file.write_text("1")
    wf = _write_three_step_workflow(tmp_path, step3_suffix=f"; exit $(cat {exit_file})")
    _, source_1 = _fail_then_load(wf, flaky_step2)

    attempt_a = _resume(wf, source_1)
    assert not attempt_a.success
    a_path = attempt_a.trace.save_to_file()

    # On disk, attempt A's RESTORED step1 event carries a blob REF (not the body),
    # with the body declared once in a preceding inline blob line — interning
    # fired again on re-record, with a fresh per-run declared set.
    lines = [json.loads(ln) for ln in a_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    blob_bodies = [ln["value"] for ln in lines if ln.get("kind") == "blob"]
    assert expected_text in blob_bodies, "restored large output was not re-interned in the attempt trace"
    step1_line = next(ln for ln in lines if ln.get("kind") == "event" and ln.get("node_id") == "step1")
    assert step1_line.get("restored") is True
    # The on-disk restored event must carry the sentinel REF dict, never the body.
    assert isinstance(step1_line["node_output"]["response"], dict)
    assert set(step1_line["node_output"]["response"]) == {BLOB_SENTINEL}

    # A second resume resolves the blob back to the FULL value and seeds it.
    exit_file.write_text("0")
    source_a = load_resume_source(execution_id=attempt_a.trace.execution_id, debug_dir=a_path.parent)
    step1_event = next(e for e in source_a.events if e["node_id"] == "step1")
    assert step1_event["node_output"]["response"] == expected_text

    attempt_b = _resume(wf, source_a)
    assert attempt_b.success
    assert attempt_b.shared_after["step3"]["stdout"] == f"{expected_text}|{expected_text}"


def test_resuming_a_superseded_attempt_is_refused(tmp_path, flaky_step2) -> None:
    """Once attempt A exists (meta.resumed_from = run1), resuming run1 again refuses
    — pins that Phase 2's META_KEYS routing feeds the Phase-1 superseded scan."""
    from pflow.core.exceptions import ResumeSupersededError

    wf = _write_three_step_workflow(tmp_path)
    run1, source_1 = _fail_then_load(wf, flaky_step2)
    attempt_a = _resume(wf, source_1)
    assert attempt_a.success
    assert attempt_a.trace.save_to_file() is not None

    with pytest.raises(ResumeSupersededError, match=attempt_a.trace.execution_id):
        load_resume_source(execution_id=run1.trace.execution_id, debug_dir=source_1.path.parent)


def test_refused_attempt_does_not_wedge_the_chain(tmp_path, flaky_step2) -> None:
    """A resume attempt that dies BEFORE K executes must not poison the chain.

    Its trace streams meta (with ``resumed_from``) then records zero events. Two
    honest behaviors pin the fix: (a) writer — the zero-event run.complete says
    ``failed``, never ``success``; (b) chain policy — a zero-work attempt does not
    supersede its source, so the original failed run stays resumable. Without
    both, the chain wedged permanently: the source read "superseded" while the
    empty attempt read "the newest run succeeded"."""
    from pflow.core.exceptions import ResumeNotResumableError

    wf = _write_three_step_workflow(tmp_path)
    original_text = wf.read_text(encoding="utf-8")
    run1, source_1 = _fail_then_load(wf, flaky_step2)

    # A pre-K failure: rename K and resume (the library-caller / --force path).
    wf.write_text(original_text.replace("step2", "step2-renamed"), encoding="utf-8")
    refused = _resume(wf, source_1)
    assert not refused.success
    refused_path = refused.trace.save_to_file()

    # (a) Writer honesty: the refused attempt's trace never claims success.
    refused_trace = load_trace_file(refused_path)
    assert refused_trace["nodes"] == []
    assert refused_trace["final_status"] == "failed"
    assert refused_trace["resumed_from"] == run1.trace.execution_id

    # (b) Chain policy: the zero-work attempt does not supersede — the original
    # run is still the frontier and resumes cleanly once the workflow is restored.
    wf.write_text(original_text, encoding="utf-8")
    source_again = load_resume_source(execution_id=run1.trace.execution_id, debug_dir=refused_path.parent)
    assert source_again.entry_node_id == "step2"
    result = _resume(wf, source_again)
    assert result.success, [str(d) for d in result.diagnostics]

    # The refused attempt itself refuses honestly (no falsely-successful frontier).
    with pytest.raises(ResumeNotResumableError):
        load_resume_source(execution_id=refused.trace.execution_id, debug_dir=refused_path.parent)


# --- Empty-output fidelity (§C step 4 `is not None` stamp) -------------------


def test_has_resumable_step_agrees_with_the_loader_on_common_cases(tmp_path) -> None:
    """C2 SOUND-direction drift pin: drive BOTH the writer-side gate and the real loader on the
    SAME real runs and assert they agree for the cases the resume hint must get right.

    ``has_resumable_step()`` is a sound suppressor — ``False`` MUST mean
    ``load_resume_source`` refuses, else the hint vanishes on a resumable run. This runs the
    two workflows the C2 report named — a normal node failure (resumable) and an
    all-steps-succeed-but-output-unbuildable failure (not) — and asserts the predicate equals
    'the loader accepts'. If the two ever drift on these, this fails. (``True`` is only
    necessary-not-sufficient — the rarer seed-scope refusals are out of scope by design; see
    ``has_resumable_step``'s docstring.)
    """
    from pflow.core.exceptions import ResumeSourceError
    from tests.shared.markdown_utils import ir_to_markdown

    def loader_accepts(result: Any) -> bool:
        trace_path = result.trace.save_to_file()
        try:
            load_resume_source(execution_id=result.trace.execution_id, debug_dir=trace_path.parent)
            return True
        except ResumeSourceError:
            return False

    def run(ir: dict[str, Any], name: str) -> Any:
        path = tmp_path / f"{name}.pflow.md"
        path.write_text(ir_to_markdown(ir, title=name, description=f"{name} workflow for the parity pin."))
        return WorkflowRunner().run(str(path), {}, RunnerConfig())

    # (a) A normal node failure → resumable on BOTH surfaces.
    r_fail = run(
        {
            "nodes": [
                {"id": "step1", "type": "shell", "purpose": "emit a ready marker", "params": {"command": "echo ready"}},
                {"id": "step2", "type": "shell", "purpose": "fail on purpose here", "params": {"command": "exit 7"}},
            ]
        },
        "normal_fail",
    )
    assert r_fail.success is False
    assert r_fail.trace.has_resumable_step() == loader_accepts(r_fail) == True  # noqa: E712

    # (b) Every step succeeds but a declared output can't be built → resumable on NEITHER.
    r_out = run(
        {
            "nodes": [
                {"id": "step1", "type": "shell", "purpose": "emit a ready marker", "params": {"command": "echo ready"}}
            ],
            "outputs": {"result": {"description": "references a key step1 never wrote", "source": "${step1.nope}"}},
        },
        "output_fail",
    )
    assert r_out.success is False
    assert r_out.trace.has_resumable_step() == loader_accepts(r_out) == False  # noqa: E712

    # A crash before the first step (no events) is not easily produced by a real run; pin the
    # zero-step branch directly — the loader refuses this too (nothing/ before-first-step).
    assert WorkflowTraceCollector(workflow_name="t").has_resumable_step() is False


def test_restored_empty_output_survives_rerecord_and_reseeds() -> None:
    """An upstream node whose real output was ``{}`` must re-record ``{}`` (not
    absent) so a SECOND resume seeds ``{}`` — a downstream coalesce distinguishes
    those. Non-restored events keep the truthy-only stamp."""
    collector = WorkflowTraceCollector(workflow_name="t")
    collector.record_node_execution("a", "ShellNode", 0.0, True, node_output={}, cached=True, restored=True)
    collector.record_node_execution("b", "ShellNode", 1.0, True, node_output={})

    restored_event, fresh_event = collector.events
    assert restored_event["node_output"] == {}
    assert restored_event["restored"] is True
    assert "node_output" not in fresh_event  # pre-existing truthy stamp unchanged

    shared: dict[str, Any] = {}
    seed_snapshot_into_shared(shared, collector.events, exclude="b")
    assert shared["a"] == {}


# --- Success-path visibility (§C step 7) --------------------------------------


def test_resumed_run_visibility_json_and_text(tmp_path, flaky_step2) -> None:
    """JSON carries resumed_from + nodes_restored; text carries the ⤷ indicator;
    restored upstream is relabeled not_executed; a normal run carries neither."""
    wf = _write_three_step_workflow(tmp_path)
    run1, source = _fail_then_load(wf, flaky_step2)
    result = _resume(wf, source)
    assert result.success
    ir = resolve_workflow(str(wf)).ir

    formatted = format_execution_success(result.shared_after, ir, result.metrics)
    execution = formatted["execution"]
    assert execution["resumed_from"] == run1.trace.execution_id
    assert execution["nodes_restored"] == 1
    assert execution["resume_entry_node"] == "step2"
    # restored_nodes display relabel (execution_state path): step1 did not run this attempt.
    statuses = {s["node_id"]: s["status"] for s in execution["steps"]}
    assert statuses == {"step1": "not_executed", "step2": "completed", "step3": "completed"}

    text = format_success_as_text(formatted)
    assert f"⤷ Resumed from {run1.trace.execution_id} at 'step2' — 1 upstream step restored" in text

    # A NON-resumed run carries neither the JSON fields nor the indicator.
    normal = WorkflowRunner().run(str(wf), {}, RunnerConfig())
    assert normal.success
    formatted_normal = format_execution_success(normal.shared_after, ir, normal.metrics)
    assert "resumed_from" not in formatted_normal["execution"]
    assert "nodes_restored" not in formatted_normal["execution"]
    assert "⤷ Resumed" not in format_success_as_text(formatted_normal)


class TestFormatResumeIndicator:
    """The shared resume indicator formatter (single source: CLI summary, CLI -p, MCP text)."""

    def test_plural_form(self) -> None:
        line = format_resume_indicator("abc-123", "deploy", 3)
        assert line == "  ⤷ Resumed from abc-123 at 'deploy' — 3 upstream steps restored"

    def test_singular_form(self) -> None:
        assert format_resume_indicator("abc-123", "deploy", 1).endswith("1 upstream step restored")

    def test_zero_restored_still_announces_mode(self) -> None:
        assert format_resume_indicator("abc-123", "deploy", 0) == "  ⤷ Resumed from abc-123 at 'deploy'"


# --- Branch scenario ----------------------------------------------------------


_BRANCH_WORKFLOW = """\
# Branch Resume

Resume on a conditional branch; the converged coalesce output reads the
restored branch value.

## Steps

### router

Route to branch A or B.

- type: code
- inputs: {{ choice: "a" }}

```python code
choice: str
if choice == "a":
    next: str = "a1"
else:
    next: str = "b1"
result: str = choice
```

### a1

First step on branch A.

- type: shell
- next: a2

```shell command
printf left-value
```

### a2

Flaky step on branch A.

- type: shell
- next: done

```shell command
exit $(cat {exit_file})
```

### b1

Branch B step.

- type: shell
- next: done

```shell command
printf right-value
```

### done

Converge.

- type: shell

```shell command
printf converged
```

## Outputs

### final

The taken branch's value.

- source: ${{a1.stdout ?? b1.stdout}}
"""


def test_branch_resume_converged_coalesce_reads_restored_value(tmp_path) -> None:
    """K sits on one conditional branch; after resume the converged ``??`` output
    resolves from the RESTORED branch node (a1), with the untaken branch absent."""
    exit_file = tmp_path / "a2-exit"
    exit_file.write_text("1")
    wf = tmp_path / "branch.pflow.md"
    wf.write_text(textwrap.dedent(_BRANCH_WORKFLOW).format(exit_file=exit_file), encoding="utf-8")

    run1 = WorkflowRunner().run(str(wf), {}, RunnerConfig())
    assert not run1.success
    trace_path = run1.trace.save_to_file()

    exit_file.write_text("0")
    source = load_resume_source(execution_id=run1.trace.execution_id, debug_dir=trace_path.parent)
    assert source.entry_node_id == "a2"

    result = _resume(wf, source)

    assert result.success, [str(d) for d in result.diagnostics]
    exec_state = result.shared_after["__execution__"]
    assert exec_state["restored_nodes"] == ["router", "a1"]
    assert exec_state["completed_nodes"] == ["a2", "done"]
    # The declared coalesce output resolved from the restored a1; b1 never ran.
    assert result.shared_after["final"] == "left-value"
    assert "b1" not in result.shared_after


# --- Feature interactions: hosts in the restored set, loop-K -------------------


def test_restored_subworkflow_and_batch_hosts_are_childless_and_reseed(tmp_path) -> None:
    """Sub-workflow + batch hosts upstream of K: re-record drops their children
    (``sub_workflow_events``/``batch_items``) by design — the attempt trace must
    still reconstruct cleanly (childless cached host) and a SECOND resume must
    seed both hosts' outputs from the attempt trace alone (Decision 6 under the
    two composite node types, not just leaves)."""
    child = tmp_path / "child.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "inner", "type": "shell", "params": {"command": "printf child-value"}}],
            "outputs": {"final": {"description": "The child's value.", "source": "${inner.stdout}"}},
        },
        child,
    )
    exit_file = tmp_path / "k-exit"
    exit_file.write_text("1")
    wf = tmp_path / "parent.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {"id": "sub", "type": "workflow", "params": {"workflow": str(child)}},
                {
                    "id": "fan",
                    "type": "shell",
                    "params": {"command": "printf 'item-%s' '${item}'"},
                    "batch": {"items": ["a", "b"], "parallel": False},
                },
                {
                    "id": "k",
                    "type": "shell",
                    "params": {
                        "command": f"printf '%s|%s' '${{sub.final}}' '${{fan.results[0].stdout}}'; exit $(cat {exit_file})"
                    },
                },
            ],
        },
        wf,
    )

    run1 = WorkflowRunner().run(str(wf), {}, RunnerConfig())
    assert not run1.success
    p1 = run1.trace.save_to_file()
    source_1 = load_resume_source(execution_id=run1.trace.execution_id, debug_dir=p1.parent)
    assert source_1.entry_node_id == "k"

    # Attempt A: hosts restored, K fails again — A's trace is the chain's newest.
    attempt_a = _resume(wf, source_1)
    assert not attempt_a.success
    a_path = attempt_a.trace.save_to_file()
    a_trace = load_trace_file(a_path)  # reconstruct itself must not choke on childless hosts
    a_events = {e["node_id"]: e for e in a_trace["nodes"]}
    for host in ("sub", "fan"):
        assert a_events[host]["status"] == "cached"
        assert a_events[host]["restored"] is True
        assert "sub_workflow_events" not in a_events[host]
        assert "batch_items" not in a_events[host]
    assert a_events["sub"]["node_output"]["final"] == "child-value"
    assert [r["stdout"] for r in a_events["fan"]["node_output"]["results"]] == ["item-a", "item-b"]

    # Attempt B seeds BOTH hosts from A's childless events alone.
    exit_file.write_text("0")
    source_a = load_resume_source(execution_id=attempt_a.trace.execution_id, debug_dir=a_path.parent)
    attempt_b = _resume(wf, source_a)
    assert attempt_b.success, [str(d) for d in attempt_b.diagnostics]
    assert attempt_b.shared_after["__execution__"]["restored_nodes"] == ["sub", "fan"]
    assert attempt_b.shared_after["k"]["stdout"] == "child-value|item-a"


def test_resume_at_a_sub_workflow_host_reruns_the_whole_host(tmp_path) -> None:
    """The product stance: a failure INSIDE a sub-workflow makes K the top-level HOST,
    and resume re-runs the whole host (top-level granularity). Upstream of the host is
    restored, the host re-executes (its inner step now succeeds), the tail continues."""
    child = tmp_path / "child.pflow.md"
    write_workflow_file(
        {
            "inputs": {"mode": {"type": "string", "required": True}},
            "nodes": [
                {"id": "inner", "type": "shell", "params": {"command": "test '${mode}' = ok && printf inner-ok"}}
            ],
            "outputs": {"out": {"description": "The child's value.", "source": "${inner.stdout}"}},
        },
        child,
    )
    wf = tmp_path / "parent.pflow.md"
    write_workflow_file(
        {
            "inputs": {"mode": {"type": "string", "required": True}},
            "nodes": [
                {"id": "pre", "type": "shell", "params": {"command": "printf pre-done"}},
                {"id": "host", "type": "workflow", "params": {"workflow": str(child), "inputs": {"mode": "${mode}"}}},
                {"id": "post", "type": "shell", "params": {"command": "printf 'post %s' '${host.out}'"}},
            ],
        },
        wf,
    )

    run1 = WorkflowRunner().run(str(wf), {"mode": "bad"}, RunnerConfig())
    assert not run1.success
    p1 = run1.trace.save_to_file()
    source = load_resume_source(execution_id=run1.trace.execution_id, debug_dir=p1.parent)
    # K is the top-level HOST (not the inner node) — top-level granularity.
    assert source.entry_node_id == "host"

    resumed = WorkflowRunner().run(str(wf), {"mode": "ok"}, RunnerConfig(), resume_source=source)
    assert resumed.success, [str(d) for d in resumed.diagnostics]
    # `pre` restored (not re-run); the host re-executed with the fix; the tail ran.
    assert resumed.shared_after["__execution__"]["restored_nodes"] == ["pre"]
    assert resumed.shared_after["post"]["stdout"] == "post inner-ok"


def test_loop_k_restarts_at_iteration_one(tmp_path) -> None:
    """Decision 9 pin: a resumed loop-node K restarts at iteration 1 — loop state
    (``loop_counts``/``__iteration__``) is engine-ephemeral, never traced or seeded."""
    iter_file = tmp_path / "iterations"
    fail_flag = tmp_path / "k-fail"
    fail_flag.write_text("1")
    wf = tmp_path / "loop.pflow.md"
    wf.write_text(
        textwrap.dedent(
            f"""\
            # Loop Resume

            A loop step that fails on its first run and resumes from scratch.

            ## Steps

            ### prep

            Upstream step.

            - type: shell

            ```shell command
            printf ready
            ```

            ### k

            Condition-looped step; records each iteration number.

            - type: code
            - inputs: {{ iteration: ${{__iteration__}} }}
            - loop:
                while: ${{k.result}}
                max_iterations: 3

            ```python code
            iteration: int
            from pathlib import Path

            with Path("{iter_file}").open("a") as fh:
                fh.write(f"{{iteration}}\\n")
            if Path("{fail_flag}").read_text().strip() == "1":
                raise RuntimeError("injected loop failure")
            result: bool = True
            ```
            """
        ),
        encoding="utf-8",
    )

    run1 = WorkflowRunner().run(str(wf), {}, RunnerConfig())
    assert not run1.success, [str(d) for d in run1.diagnostics]
    p1 = run1.trace.save_to_file()
    assert iter_file.read_text().splitlines() == ["1"], "run 1 was supposed to fail on iteration 1"

    fail_flag.write_text("0")
    source = load_resume_source(execution_id=run1.trace.execution_id, debug_dir=p1.parent)
    assert source.entry_node_id == "k"
    result = _resume(wf, source)

    assert result.success, [str(d) for d in result.diagnostics]
    assert result.shared_after["__execution__"]["restored_nodes"] == ["prep"]
    # The resume's iterations are 1,2,3 (restart), never 2,3 (continuation).
    assert iter_file.read_text().splitlines() == ["1", "1", "2", "3"]


def test_both_primary_and_fallback_fail_resumes_at_the_primary_e2e(tmp_path) -> None:
    """REAL on-error double-failure (Decision 9 / ADR-0010): primary K fails → on-error → fallback F
    also fails. Resume must enter at the PRIMARY (the root of the terminal failure), and fixing the
    primary's cause makes it succeed and follow its SUCCESS edge, bypassing the fallback entirely.

    This is the production shape the (previously fictional) synthetic loader tests could not model —
    real routing tags the primary with an ``on_error_recovery`` warning, which is exactly what the
    old `_unrecovered_failed_node_ids`-only entry logic (wrongly) filtered out."""
    wf = tmp_path / "wf.pflow.md"
    wf.write_text(
        textwrap.dedent(
            """\
            # Both fail

            Primary + fallback both fail.

            ## Inputs

            ### mode

            Gate for the primary.

            - type: string
            - required: true

            ## Steps

            ### primary

            Primary — fails unless mode=ok; on error routes to the fallback.

            - type: shell
            - on-error: fallback
            - next: done

            ```shell command
            test "${mode}" = "ok" && echo primary-ok
            ```

            ### fallback

            Fallback — always fails.

            - type: shell
            - next: done

            ```shell command
            exit 7
            ```

            ### done

            End.

            - type: shell

            ```shell command
            echo done
            ```
            """
        ),
        encoding="utf-8",
    )

    run1 = WorkflowRunner().run(str(wf), {"mode": "bad"}, RunnerConfig())
    assert not run1.success
    p1 = run1.trace.save_to_file()
    source = load_resume_source(execution_id=run1.trace.execution_id, debug_dir=p1.parent)
    # Root of the terminal failure — the PRIMARY, not the fallback that stopped the run.
    assert source.entry_node_id == "primary"

    resumed = WorkflowRunner().run(str(wf), {"mode": "ok"}, RunnerConfig(), resume_source=source)
    assert resumed.success, [str(d) for d in resumed.diagnostics]
    completed = resumed.shared_after["__execution__"]["completed_nodes"]
    # Fixed primary succeeds → follows its success edge to `done`; the fallback never runs.
    assert completed == ["primary", "done"]
    assert "fallback" not in completed


def test_non_interactive_gate_stop_refuses_naming_the_gate_e2e(tmp_path) -> None:
    """REAL non-interactive approval-gate stop (Decision 8): the run fails with EMPTY failed_node_ids
    (the gated node never ran), and resume refuses — naming the gate — rather than treating it as a
    resumable failure. Validates the whole chain against production, not a spliced synthetic trace."""
    from pflow.core.exceptions import ResumeGateStoppedError

    wf = tmp_path / "wf.pflow.md"
    wf.write_text(
        textwrap.dedent(
            """\
            # Gated

            A gated step with no resolver -> non-interactive stop.

            ## Steps

            ### prep

            Plain upstream step.

            - type: shell

            ```shell command
            echo ready
            ```

            ### guarded

            Gated step (never runs — no resolver to approve it).

            - type: shell
            - approval: required

            ```shell command
            echo do-it
            ```
            """
        ),
        encoding="utf-8",
    )

    # No gate_resolver installed → GateNotInteractiveError at the gate.
    run1 = WorkflowRunner().run(str(wf), {}, RunnerConfig())
    assert not run1.success
    p1 = run1.trace.save_to_file()
    trace = load_trace_file(p1)
    assert trace.get("final_status") == "failed"
    assert trace.get("failed_node_ids") == []  # the gated node produced zero events

    with pytest.raises(ResumeGateStoppedError) as exc:
        load_resume_source(execution_id=run1.trace.execution_id, debug_dir=p1.parent)
    assert exc.value.node_id == "guarded"


# ── Review fixes (2026-07-04): seed fidelity + incomplete tails ending in a failure ──

WF_RECOVERED_COALESCE = textwrap.dedent(
    """\
    # Recovered coalesce

    Coalesce over a recovered failure.

    ## Inputs

    ### mode

    Primary gate.

    - type: string
    - required: true

    ### flag

    Use gate.

    - type: string
    - required: true

    ## Steps

    ### primary

    Fails unless mode=ok; on error routes to the fallback.

    - type: shell
    - on-error: fallback
    - next: use

    ```shell command
    test "${mode}" = "ok" && printf primary-data
    ```

    ### fallback

    Always succeeds.

    - type: shell
    - next: use

    ```shell command
    printf fallback-data
    ```

    ### use

    Consumes the coalesce; fails unless flag=ok.

    - type: shell

    ```shell command
    test "${flag}" = "ok" && printf 'used=%s' '${primary.stdout ?? fallback.stdout}'
    ```
    """
)


def _truncate_trace(path: Path, *, first_dropped_node: str | None) -> None:
    """Simulate a SIGKILL tail: keep lines before `first_dropped_node`'s first line,
    always dropping the run.complete trailer (the reader then synthesizes `incomplete`)."""
    kept: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = json.loads(raw)
        if line.get("kind") == "run.complete":
            break
        if first_dropped_node is not None and line.get("node_id") == first_dropped_node:
            break
        kept.append(raw)
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def test_recovered_failure_upstream_is_not_seeded(tmp_path) -> None:
    """Seed fidelity (review fix 2026-07-04): a RECOVERED failure upstream of K is not
    seeded — its data lived in ``__failures__`` in the source run, never the store — so a
    ``${primary.x ?? fallback.x}`` coalesce in the resumed tail falls through to the
    fallback exactly as the original run did. It is also neither listed as restored nor
    re-recorded into the attempt trace (the old behavior seeded the failed output, and the
    coalesce silently resolved to it: ``used=`` instead of ``used=fallback-data``)."""
    wf = tmp_path / "wf.pflow.md"
    wf.write_text(WF_RECOVERED_COALESCE, encoding="utf-8")
    run1 = WorkflowRunner().run(str(wf), {"mode": "bad", "flag": "bad"}, RunnerConfig())
    assert not run1.success
    p1 = run1.trace.save_to_file()
    source = load_resume_source(execution_id=run1.trace.execution_id, debug_dir=p1.parent)
    assert source.entry_node_id == "use"

    resumed = WorkflowRunner().run(str(wf), {"mode": "bad", "flag": "ok"}, RunnerConfig(), resume_source=source)
    assert resumed.success, [str(d) for d in resumed.diagnostics]
    # Original-run semantics preserved: the coalesce falls through to the fallback.
    assert resumed.shared_after["use"]["stdout"] == "used=fallback-data"
    # The failed-recovered primary is not restored...
    assert resumed.shared_after["__execution__"]["restored_nodes"] == ["fallback"]
    # ...and not re-recorded into the attempt trace (no flipped cached-success event).
    attempt_node_ids = [e.get("node_id") for e in resumed.trace.events]
    assert "primary" not in attempt_node_ids
    assert "fallback" in attempt_node_ids


def test_incomplete_tail_ending_in_unrecovered_failure_reenters_at_the_failure(tmp_path) -> None:
    """Incomplete-tail fix (review 2026-07-04): killed AFTER an unrecovered failure flushed
    but BEFORE the trailer — the old between-nodes rule continued to the failure's default
    successor, resuming past an unhandled failure as if it had succeeded. The terminal-failure
    root rule re-enters at the failure itself."""
    wf = tmp_path / "wf.pflow.md"
    wf.write_text(
        textwrap.dedent(
            """\
            # Two step

            Unrecovered failure then a tail step.

            ## Inputs

            ### mode

            Gate.

            - type: string
            - required: true

            ## Steps

            ### boom

            Fails unless mode=ok.

            - type: shell
            - next: after

            ```shell command
            test "${mode}" = "ok" && printf boom-ok
            ```

            ### after

            Tail.

            - type: shell

            ```shell command
            printf after-ran
            ```
            """
        ),
        encoding="utf-8",
    )
    run1 = WorkflowRunner().run(str(wf), {"mode": "bad"}, RunnerConfig())
    assert not run1.success
    p1 = run1.trace.save_to_file()
    _truncate_trace(p1, first_dropped_node=None)  # drop only the trailer

    source = load_resume_source(execution_id=run1.trace.execution_id, debug_dir=p1.parent)
    assert source.entry_node_id == "boom"
    assert source.last_completed_node_id is None

    resumed = WorkflowRunner().run(str(wf), {"mode": "ok"}, RunnerConfig(), resume_source=source)
    assert resumed.success, [str(d) for d in resumed.diagnostics]
    assert resumed.shared_after["__execution__"]["completed_nodes"] == ["boom", "after"]


def test_incomplete_tail_killed_before_the_error_handler_reenters_at_the_recovered_primary(tmp_path) -> None:
    """Incomplete-tail fix (review 2026-07-04): killed between a RECOVERED failure and its
    on-error handler's start — the taken route was the ERROR edge, so the old rule's single
    DEFAULT successor was provably the wrong branch (it skipped the fallback entirely).
    Re-entering at the primary re-fires it (at-least-once) and its error edge re-routes to
    the fallback, reproducing the interrupted run's actual path."""
    wf = tmp_path / "wf.pflow.md"
    wf.write_text(WF_RECOVERED_COALESCE, encoding="utf-8")
    run1 = WorkflowRunner().run(str(wf), {"mode": "bad", "flag": "bad"}, RunnerConfig())
    assert not run1.success
    p1 = run1.trace.save_to_file()
    # Kill between primary's (failed, recovered) event and the fallback's start.
    _truncate_trace(p1, first_dropped_node="fallback")

    source = load_resume_source(execution_id=run1.trace.execution_id, debug_dir=p1.parent)
    assert source.entry_node_id == "primary"
    assert source.last_completed_node_id is None

    resumed = WorkflowRunner().run(str(wf), {"mode": "bad", "flag": "ok"}, RunnerConfig(), resume_source=source)
    # primary fails again → error edge re-taken → fallback runs → use reads the fallback.
    assert resumed.shared_after["__execution__"]["completed_nodes"] == ["fallback", "use"]
    assert resumed.shared_after["use"]["stdout"] == "used=fallback-data"


# --- Escalation-gate resume (review fix 2026-07-04) ---------------------------


def test_resolved_escalation_upstream_resumes_end_to_end(tmp_path) -> None:
    """The escalation false-refusal fix, driven through the REAL collector: the agent's
    event freezes the marker UNDECIDED (engine step 16 records it before step 17.7 writes
    the human's decision into the LIVE store), and the decision is persisted only as a
    disk-only gate resolution line. The loader must fold that resolution back into the
    event — refusing here ("unresolved escalation") would contradict what happened and
    make resume unusable for every escalation-gated workflow with a later failure."""
    from pflow.core.gate import GateResolution

    def resolver(request: Any, *, allow_prompt: bool) -> GateResolution:
        return GateResolution(approved=True, resolved_via="prompt", chosen="ship", notes="looks good")

    flag = tmp_path / "flag.txt"
    ir = {
        "nodes": [
            {
                "id": "agent",
                "type": "code",
                "params": {"code": "result: dict = {'escalation': {'question': 'Ship it?'}, 'work': 'done'}"},
            },
            {"id": "boom", "type": "shell", "params": {"command": f"cat {flag}"}},
        ],
    }
    wf = tmp_path / "wf.pflow.md"
    write_workflow_file(ir, wf)

    run1 = WorkflowRunner().run(str(wf), {}, RunnerConfig(), gate_resolver=resolver)
    assert not run1.success, "run 1 was supposed to fail at boom (flag file absent)"
    trace_path = run1.trace.save_to_file()
    assert trace_path is not None

    # The loader folds the recorded resolution into the frozen marker instead of refusing.
    source = load_resume_source(execution_id=run1.trace.execution_id, debug_dir=trace_path.parent)
    assert source.entry_node_id == "boom"
    agent_event = next(e for e in source.events if e["node_id"] == "agent")
    assert agent_event["node_output"]["result"]["escalation"]["decision"] == {
        "chosen": "ship",
        "notes": "looks good",
    }

    flag.write_text("ready\n", encoding="utf-8")
    resumed = WorkflowRunner().run(str(wf), {}, RunnerConfig(), resume_source=source)
    assert resumed.success, [str(d) for d in resumed.diagnostics]
    assert resumed.shared_after["__execution__"]["completed_nodes"] == ["boom"]
    # The seeded store carries the DECIDED marker, and the attempt trace re-records it —
    # a resume-of-a-resume seeds the decision without re-joining gate lines.
    assert resumed.shared_after["agent"]["result"]["escalation"]["decision"]["chosen"] == "ship"
    attempt_path = resumed.trace.save_to_file()
    assert attempt_path is not None
    attempt = load_trace_file(attempt_path)
    restored_agent = next(e for e in attempt["nodes"] if e["node_id"] == "agent")
    assert restored_agent["restored"] is True
    assert restored_agent["node_output"]["result"]["escalation"]["decision"]["chosen"] == "ship"
