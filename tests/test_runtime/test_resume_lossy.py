"""Task 179 — values the trace cannot round-trip are marked ``lossy`` and never seeded by resume.

The trace stores JSON. What an author's ``code`` step produced survives it only when it is
JSON-native: a non-string key becomes a string, a nested ``__`` key is dropped, bytes become a
placeholder, and a set / date / Decimal / custom object becomes its ``str()``. Each such event
carries ``lossy`` (``WorkflowTraceCollector._sanitize_for_json``), and:

- resume refuses to seed it, naming the step and the place (``ResumeFidelityError``);
- a gate whose resume would seed it does not pause (pause = promise) — the run fails with the
  reason instead of issuing a token the loader would bounce.

Every pin runs real producers (``WorkflowRunner`` + a real trace) and is paired with a
JSON-native twin that still resumes / pauses — the remedy the refusal names.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from pflow.core.exceptions import GateNotInteractiveError, ResumeFidelityError
from pflow.core.gate import GateResolution
from pflow.core.trace_io import load_trace_file
from pflow.execution.result import RunnerConfig, WorkflowStatus
from pflow.execution.runner import WorkflowRunner
from pflow.runtime.resume_source import load_resume_source

pytestmark = pytest.mark.trace_files

REMEDY = (
    "make the step's result JSON-native (dict/list/str/int/float/bool/None) — e.g. `str(dt)` / "
    "`sorted(s)` in the code step — or re-run from the start"
)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / f"{name}.pflow.md"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def _fail_then_load(wf: Path, params: dict[str, Any]) -> Any:
    failed = WorkflowRunner().run(str(wf), params, RunnerConfig())
    assert failed.status is WorkflowStatus.FAILED, [d.message for d in failed.diagnostics]
    path = failed.trace.save_to_file()
    return failed, path


def _upstream_then_failing_down(tmp_path: Path, produce: str) -> Path:
    """``up`` (code, producing ``produce``) → ``down``, which fails while the flag file says 1."""
    return _write(
        tmp_path,
        "upstream",
        f"""\
        # Upstream Value

        An upstream code result consumed by a failing downstream step.

        ## Inputs

        ### flag

        Fail flag file.

        - type: string
        - required: true

        ## Steps

        ### up

        Produce the value.

        - type: code

        ```python code
        import datetime, decimal
        {produce}
        ```

        ### down

        Read it.

        - type: code
        - inputs:
            d: ${{up.result}}
            flag: ${{flag}}

        ```python code
        from pathlib import Path

        d: dict
        flag: str
        if Path(flag).read_text(encoding="utf-8") == "1":
            raise RuntimeError("boom")
        result: str = repr(d)
        ```
        """,
    )


@pytest.mark.parametrize(
    ("produce", "lossy"),
    [
        # falsifier `upstream_lossy` — the non-loop C1 shape
        ('result: dict = {1: "one"}', ["result.1: non-string key (int)"]),
        # probeA — set, date, Decimal, and a nested int key, in one result
        (
            'result: dict = {"s": {1, 2}, "dt": datetime.date(2026, 1, 2), '
            '"dec": decimal.Decimal("1.5"), "nested": {2: "x"}}',
            ["result.s: set", "result.dt: date", "result.dec: Decimal", "result.nested.2: non-string key (int)"],
        ),
    ],
    ids=["int-key", "set-date-decimal-nested-key"],
)
def test_resume_refuses_to_seed_a_lossy_upstream_value(tmp_path, produce, lossy) -> None:
    flag = tmp_path / "flag"
    flag.write_text("1", encoding="utf-8")
    wf = _upstream_then_failing_down(tmp_path, produce)
    failed, path = _fail_then_load(wf, {"flag": str(flag)})
    event = next(e for e in load_trace_file(path)["nodes"] if e["node_id"] == "up")
    assert event["lossy"] == lossy  # the marker, as written to disk

    with pytest.raises(ResumeFidelityError) as exc_info:
        load_resume_source(execution_id=failed.trace.execution_id, debug_dir=path.parent)
    error = exc_info.value
    assert error.node_id == "up"
    assert error.lossy == lossy
    assert f"Step 'up' produced a value the saved run cannot restore faithfully ({'; '.join(lossy)})" in str(error)
    assert error.to_diagnostics()[0].suggestions == [REMEDY]


def test_json_native_upstream_resumes(tmp_path) -> None:
    """The presence twin, shaped by the remedy: `str(dt)`, `sorted(s)`, string keys."""
    flag = tmp_path / "flag"
    flag.write_text("1", encoding="utf-8")
    produce = (
        'result: dict = {"1": "one", "s": sorted({1, 2}), "dt": str(datetime.date(2026, 1, 2)), '
        '"dec": str(decimal.Decimal("1.5")), "t": (1, 2)}'
    )
    wf = _upstream_then_failing_down(tmp_path, produce)
    failed, path = _fail_then_load(wf, {"flag": str(flag)})
    assert all("lossy" not in event for event in failed.trace.events)  # tuple→list is not lossy
    flag.write_text("0", encoding="utf-8")
    source = load_resume_source(execution_id=failed.trace.execution_id, debug_dir=path.parent)
    assert source.entry_node_id == "down"
    resumed = WorkflowRunner().run(str(wf), {"flag": str(flag)}, RunnerConfig(), resume_source=source)
    assert resumed.success, [d.message for d in resumed.diagnostics]
    assert resumed.shared_after["__execution__"]["restored_nodes"] == ["up"]


def _tally_loop(tmp_path: Path, *, key: str, extra: str = "", approval: bool = False) -> Path:
    """The falsifier's tally loop: ``k`` (cap 4) carries ``tally``; it fails at the iteration
    named by the flag file. ``key`` is the tally key expression for this iteration."""
    path = _write(
        tmp_path,
        "tally",
        f"""\
        # Tally Loop

        A loop carrying a tally; fails at a flagged iteration.

        ## Inputs

        ### flag

        Iteration to fail at.

        - type: string
        - required: true

        ## Steps

        ### k

        Tally the iteration.

        - type: code
        - inputs:
            iteration: ${{__iteration__}}
            flag: ${{flag}}
            tally: {{}}
        - loop:
            carry:
              tally: ${{k.result.tally}}
            while: ${{k.result.more}}
            max_iterations: 4

        ```python code
        from pathlib import Path

        iteration: int
        flag: str
        tally: dict
        if Path(flag).read_text(encoding="utf-8").strip() == str(iteration):
            raise RuntimeError("boom")
        new = dict(tally)
        new[{key}] = iteration
        result: dict = {{"tally": new, "more": True{extra}}}
        ```
        """,
    )
    if approval:
        path.write_text(
            path.read_text(encoding="utf-8").replace("- type: code\n", "- type: code\n- approval: required\n"),
            encoding="utf-8",
        )
    return path


def test_failure_resume_refuses_a_lossy_carried_iteration(tmp_path) -> None:
    """Falsifier `lossy2`: K fails at 3; the seed is K's iteration-2 output, whose int-keyed
    tally the trace stored with string keys — continuing would carry different data."""
    flag = tmp_path / "flag"
    flag.write_text("3", encoding="utf-8")
    failed, path = _fail_then_load(_tally_loop(tmp_path, key="iteration"), {"flag": str(flag)})
    with pytest.raises(ResumeFidelityError) as exc_info:
        load_resume_source(execution_id=failed.trace.execution_id, debug_dir=path.parent)
    assert exc_info.value.node_id == "k"
    assert exc_info.value.lossy == ["result.tally.1: non-string key (int)", "result.tally.2: non-string key (int)"]


def test_failure_resume_continues_a_json_native_carried_iteration(tmp_path) -> None:
    flag = tmp_path / "flag"
    flag.write_text("3", encoding="utf-8")
    wf = _tally_loop(tmp_path, key="str(iteration)")
    failed, path = _fail_then_load(wf, {"flag": str(flag)})
    flag.write_text("0", encoding="utf-8")
    source = load_resume_source(execution_id=failed.trace.execution_id, debug_dir=path.parent)
    assert (source.entry_node_id, source.entry_iteration) == ("k", 3)
    resumed = WorkflowRunner().run(str(wf), {"flag": str(flag)}, RunnerConfig(), resume_source=source)
    assert resumed.success, [d.message for d in resumed.diagnostics]
    assert resumed.shared_after["k"]["result"]["tally"] == {"1": 1, "2": 2, "3": 3, "4": 4}


class _ApproveFirst:
    def __init__(self, approvals: int) -> None:
        self.remaining = approvals

    def __call__(self, request: Any, *, allow_prompt: bool = True) -> GateResolution:
        if self.remaining > 0:
            self.remaining -= 1
            return GateResolution(approved=True, resolved_via="flag")
        raise GateNotInteractiveError(request)


def _gate_failure(result: Any) -> list[str]:
    """The no-pause reason the gate error carries (its suggestions)."""
    [diagnostic] = [d for d in result.diagnostics if d.title == "Gate needs a human"]
    return diagnostic.suggestions


@pytest.mark.parametrize(
    ("key", "extra", "lossy"),
    [
        # falsifier `lossy3` — int-keyed tally
        ("iteration", "", "result.tally.1: non-string key (int)"),
        # falsifier `lossy4` — an author `__` key inside the tally
        ("f'__{iteration}'", "", "result.tally.__1: key dropped by the trace"),
        # falsifier `bin_gated` — bytes in the result
        ("str(iteration)", ', "blob": bytes([0, 1, 2])', "result.blob: bytes"),
    ],
    ids=["int-key", "dunder-key", "bytes"],
)
def test_loop_gate_does_not_pause_when_its_resume_would_seed_a_lossy_iteration(tmp_path, key, extra, lossy) -> None:
    """W1: iteration 2's approval would resume seeding iteration 1's lossy output — the loader
    would refuse that token, so the gate must not issue it: the run fails, saying why."""
    flag = tmp_path / "flag"
    flag.write_text("0", encoding="utf-8")
    wf = _tally_loop(tmp_path, key=key, extra=extra, approval=True)
    result = WorkflowRunner().run(str(wf), {"flag": str(flag)}, RunnerConfig(), gate_resolver=_ApproveFirst(1))
    assert result.status is WorkflowStatus.FAILED
    assert result.trace.gate_outcome == "failed"
    assert result.trace.pause_request is None
    [reason] = [s for s in _gate_failure(result) if s.startswith("This gate did not pause")]
    assert f"cannot restore step 'k' faithfully ({lossy}" in reason


def test_loop_gate_pauses_when_its_resume_seed_is_json_native(tmp_path) -> None:
    flag = tmp_path / "flag"
    flag.write_text("0", encoding="utf-8")
    wf = _tally_loop(tmp_path, key="str(iteration)", approval=True)
    result = WorkflowRunner().run(str(wf), {"flag": str(flag)}, RunnerConfig(), gate_resolver=_ApproveFirst(1))
    assert result.status is WorkflowStatus.PAUSED
    assert result.trace.pause_request["gate_request"]["iteration"] == 2


def _upstream_then_gate(tmp_path: Path, produce: str) -> Path:
    return _write(
        tmp_path,
        "up_gate",
        f"""\
        # Upstream Then Gate

        An upstream code result, then a gated step.

        ## Steps

        ### up

        Produce the value.

        - type: code

        ```python code
        {produce}
        ```

        ### g

        Gated.

        - type: shell
        - approval: required

        ```shell command
        echo gated-ran
        ```
        """,
    )


def test_gate_does_not_pause_when_its_resume_would_seed_lossy_upstream(tmp_path) -> None:
    """Falsifier `up_bin_gate`: a NON-loop gate whose resume would seed upstream bytes."""
    result = WorkflowRunner().run(
        str(_upstream_then_gate(tmp_path, "result: bytes = bytes([0, 1])")), {}, RunnerConfig()
    )
    assert result.status is WorkflowStatus.FAILED
    assert result.trace.pause_request is None
    [reason] = [s for s in _gate_failure(result) if s.startswith("This gate did not pause")]
    assert "cannot restore step 'up' faithfully (result: bytes)" in reason


def test_gate_pauses_when_its_resume_seed_is_json_native(tmp_path) -> None:
    result = WorkflowRunner().run(str(_upstream_then_gate(tmp_path, "result: str = 'AAE='")), {}, RunnerConfig())
    assert result.status is WorkflowStatus.PAUSED
    assert result.trace.pause_request["paused_node_id"] == "g"
    assert all("lossy" not in event for event in result.trace.events)


class TestLossyMarkerProvenance:
    """The marker judges what the AUTHOR produced, never what the engine wrote (gate review A)."""

    @staticmethod
    def _lossy(node_output: dict[str, Any], **kwargs: Any) -> Any:
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        collector = WorkflowTraceCollector("t")
        collector.record_node_execution("n", "PythonCodeNode", 1.0, True, node_output=node_output, **kwargs)
        return collector.events[0].get("lossy")

    def test_author_exception_and_top_level_dunder_key_are_marked(self) -> None:
        assert self._lossy({"result": {"exception": ValueError("x")}}) == ["result.exception: ValueError"]
        assert self._lossy({"__foo": 7, "ok": 1}) == ["__foo: key dropped by the trace"]

    def test_engine_written_keys_and_batch_error_exceptions_are_not_marked(self) -> None:
        engine_only = {
            "__pflow_stats__": {"duration_ms": 1.0},
            "__pflow_warnings__": [],
            "__metrics__": {"k": 1},
            "_batch_trace": [],
            "_debug_context": {},
            "errors": [{"index": 0, "error": "boom", "exception": ValueError("boom")}],
            "results": [],
        }
        assert self._lossy(engine_only) is None
        # The same exception one level down is the author's, and marked.
        assert self._lossy({**engine_only, "results": [{"exception": ValueError("x")}]}) == [
            "results[0].exception: ValueError"
        ]

    def test_batch_item_events_carry_the_marker(self) -> None:
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        collector = WorkflowTraceCollector("t")
        collector.record_node_execution(
            "b",
            "PythonCodeNode",
            1.0,
            True,
            node_output={"results": [{"result": "ok"}]},
            batch_items=[
                {"index": 0, "node_output": {"result": {1: "a"}}},
                {"index": 1, "node_output": {"result": {"1": "a"}}},
            ],
        )
        items = collector.events[0]["batch_items"]
        assert [item.get("lossy") for item in items] == [["result.1: non-string key (int)"], None]
