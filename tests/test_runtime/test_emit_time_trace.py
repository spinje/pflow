"""Task 172 — emit-time trace producer: the live-engine → JSONL → reader equivalence gate.

The existing trace suite proves *no regression*, but it mostly exercises the OLD nested buffer path or
in-memory readers that go through ``tree()``. These tests drive the Phase-D contract directly: run a real
workflow through the unified run-scoped collector, then assert the load-bearing invariant for a COMPLETE
run — the in-memory ``tree()`` view, the on-disk ``reconstruct()`` nested dict, and the
cost / ``final_status`` / ``failed_node_ids`` derived from each are all consistent. Cost is asserted as a
**hardcoded literal**, never a value recomputed by the same reader over both structures (so a missed
``cached``→``status`` reader can't leave the two "equal but wrong").

These are marked ``trace_files`` so ``save_to_file`` actually writes; ``Path.home`` is redirected to
``tmp_path`` so the debug + cache dirs are isolated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pflow.core.trace_io import load_trace_file
from pflow.execution import WorkflowRunner
from pflow.execution.result import RunnerConfig
from pflow.runtime.workflow_trace import WorkflowTraceCollector

MODEL = "anthropic/claude-sonnet-4-5"


def _run(workflow_path: Path, *, cache_enabled: bool = True):
    return WorkflowRunner().run(str(workflow_path), {}, config=RunnerConfig(cache_enabled=cache_enabled))


@pytest.mark.trace_files
def test_emit_equivalence_subworkflow_fresh(tmp_path, mock_llm_client, monkeypatch):
    """Live engine → JSONL → reader equivalence for a sub-workflow (NEW flat path), fresh run.

    The sub-workflow child records FLAT into the one run collector with emit-time correlation; the
    nested view is reconstructed identically on read. Asserts ``tree() == reconstruct(disk)`` AND a
    hardcoded cost literal, AND that the child nests under its host via ``parent_id == host.id``.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mock_llm_client.set_response(MODEL, None, {"response": "ok"}, cost_usd=0.01)

    child = tmp_path / "child.pflow.md"
    child.write_text(
        "# Child\n\nChild workflow with one LLM node.\n\n## Steps\n\n"
        "### child-llm\n\nGenerate child text.\n\n- type: llm\n- model: "
        + MODEL
        + "\n- prompt: child please respond\n",
        encoding="utf-8",
    )
    parent = tmp_path / "parent.pflow.md"
    parent.write_text(
        "# Parent\n\nParent with a top LLM then a sub-workflow.\n\n## Steps\n\n"
        "### top-llm\n\nGenerate top text.\n\n- type: llm\n- model: " + MODEL + "\n- prompt: top please respond\n\n"
        "### call-child\n\nDelegate to the child workflow.\n\n- type: workflow\n- workflow: " + str(child) + "\n",
        encoding="utf-8",
    )

    result = _run(parent)
    assert result.success
    collector = result.trace
    assert collector is not None and collector.is_run_scoped

    # The store is FLAT with emit-time correlation: top-llm + call-child host at top level,
    # child-llm flat with parent_id == the host's reserved seq.
    events = collector.events
    by_node = {e["node_id"]: e for e in events}
    host = by_node["call-child"]
    child_llm = by_node["child-llm"]
    assert child_llm["parent_id"] == host["id"], "child must nest under its sub-workflow host (emit-time parent_id)"
    assert host["parent_id"] is None and by_node["top-llm"]["parent_id"] is None
    assert child_llm["ancestor_path"] == [{"node_id": "call-child", "batch_index": None}]

    # Equivalence: in-memory tree() == on-disk reconstruct(). Both run through the same
    # _rebuild_event_tree, so a JSON-native round-trip is exact.
    disk_path = collector.save_to_file()
    disk = load_trace_file(disk_path)
    assert collector.tree() == disk["nodes"]

    # Cost as a hardcoded literal (top-llm + child-llm, both fresh @ 0.01). Asserted on the
    # SAVED trace's summary, computed by the production reader — not recomputed here.
    assert disk["llm_summary"]["total_cost_usd"] == pytest.approx(0.02)
    assert disk["final_status"] == "success"
    assert disk["failed_node_ids"] == []
    # nodes_executed counts top-level only (host + top-llm), not the flat sub-workflow child.
    assert disk["nodes_executed"] == 2


@pytest.mark.trace_files
def test_emit_equivalence_cached_node_inside_subworkflow(tmp_path, mock_llm_client, monkeypatch):
    """THE load-bearing case: a CACHED node nested INSIDE a sub-workflow (two reviewers converged on it).

    Run the workflow twice against a shared memo cache. On run 2 the child's LLM node is a memo HIT
    (``status == "cached"``) while the top LLM stays fresh (``cache: false``). Asserts the cached child
    still nests under its host (``parent_id == host.id``) — it did NOT escape to ``parent_id=None`` — and
    that the run-2 cost literal EXCLUDES the cached child (only the fresh top LLM contributes). The
    independent cost literal is what catches a missed ``cached``→``status`` reader that would otherwise
    leave ``tree()`` and ``reconstruct(disk)`` "equal but wrong".
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mock_llm_client.set_response(MODEL, None, {"response": "ok"}, cost_usd=0.01)

    child = tmp_path / "child.pflow.md"
    child.write_text(
        "# Child\n\nChild workflow with one cacheable LLM node.\n\n## Steps\n\n"
        "### child-llm\n\nGenerate child text.\n\n- type: llm\n- model: "
        + MODEL
        + "\n- prompt: child please respond\n",
        encoding="utf-8",
    )
    parent = tmp_path / "parent.pflow.md"
    parent.write_text(
        "# Parent\n\nParent with an uncacheable top LLM then a sub-workflow.\n\n## Steps\n\n"
        "### top-llm\n\nGenerate top text.\n\n- type: llm\n- model: "
        + MODEL
        + "\n- prompt: top please respond\n- cache: false\n\n"
        "### call-child\n\nDelegate to the child workflow.\n\n- type: workflow\n- workflow: " + str(child) + "\n",
        encoding="utf-8",
    )

    # Run 1 populates the memo cache; assert on run 2 (caching ON by default).
    first = _run(parent)
    assert first.success
    second = _run(parent)
    assert second.success

    collector = second.trace
    by_node = {e["node_id"]: e for e in collector.events}
    host = by_node["call-child"]
    child_llm = by_node["child-llm"]

    assert child_llm["status"] == "cached", "run-2 child LLM must be a memo cache hit"
    assert by_node["top-llm"]["status"] == "success", "top LLM is cache:false → fresh every run"
    assert child_llm["parent_id"] == host["id"], (
        "the cached child must STILL nest under its host, not escape to top level"
    )

    disk_path = collector.save_to_file()
    disk = load_trace_file(disk_path)
    assert collector.tree() == disk["nodes"]
    # Run-2 cost EXCLUDES the cached child → only the fresh top LLM (0.01). Hardcoded literal.
    assert disk["llm_summary"]["total_cost_usd"] == pytest.approx(0.01)
    assert disk["final_status"] == "success"


@pytest.mark.trace_files
def test_old_path_parallel_batch_of_subworkflows_stays_nested(tmp_path, mock_llm_client, monkeypatch):
    """OLD-path preservation — the highest-risk SILENT regression.

    A parallel batch whose items are sub-workflows MUST keep the OLD buffer-and-embed path: each item's
    sub-workflow events nest under ``batch_items[*].events`` and carry NO correlation keys (buffer
    collectors don't stamp ``id``/``seq``/``parent_id``). A misrouted ``use_run_collector`` would
    flatten them into top-level ``parent_id`` lines — caught discriminatingly here.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mock_llm_client.set_response(MODEL, None, {"response": "ok"}, cost_usd=0.01)

    child = tmp_path / "bchild.pflow.md"
    child.write_text(
        "# BChild\n\nBatched child.\n\n## Inputs\n\n### topic\n\nThe topic to respond about.\n\n- type: string\n\n## Steps\n\n"
        "### bchild-llm\n\nRespond about the topic.\n\n- type: llm\n- model: "
        + MODEL
        + "\n- prompt: respond about ${topic}\n",
        encoding="utf-8",
    )
    parent = tmp_path / "bparent.pflow.md"
    parent.write_text(
        f"""\
# BParent

Parallel batch of sub-workflows.

## Steps

### fanout

Run the child per item.

- type: workflow
- workflow: {child}
- inputs:
    topic: ${{item}}

```yaml batch
items:
  - a
  - b
as: item
parallel: true
```
""",
        encoding="utf-8",
    )

    result = _run(parent, cache_enabled=False)
    assert result.success
    collector = result.trace

    # Only the batch HOST is a top-level event; its items (and their sub-workflow events) stay inline.
    top = collector._top_level_events()
    assert [e["node_id"] for e in top] == ["fanout"], "only the batch host is top level; items are inline"
    assert len(collector.events) == 1, "no flat sub-workflow children leaked into the run collector"

    host = collector.events[0]
    batch_items = host.get("batch_items") or []
    assert len(batch_items) == 2, "both batch items captured inline"
    for item in batch_items:
        # OLD path: buffer collector stamps NO correlation keys on the item or its sub-workflow events.
        assert "id" not in item and "seq" not in item and "parent_id" not in item
        sub_events = item.get("events") or []
        assert sub_events, "each item's sub-workflow events nest under batch_items[*].events"
        for ev in sub_events:
            assert "id" not in ev and "seq" not in ev and "parent_id" not in ev, (
                "batch sub-workflow events must NOT carry emit-time correlation (OLD buffer path)"
            )
            assert ev["node_id"] == "bchild-llm"

    # tree() == reconstruct(disk) still holds with inline batch_items (neither promotes them).
    disk_path = collector.save_to_file()
    disk = load_trace_file(disk_path)
    assert collector.tree() == disk["nodes"]


def test_looped_subworkflow_re_descends_distinct_seq_balanced_stack():
    """Looped sub-workflow (issue #445): a looped ``WorkflowExecutor`` re-descends each iteration.

    The engine's loop re-entry re-runs ``exec()`` per visit, so the collector ``descend``/``ascend`` once
    per iteration. Each visit must get a DISTINCT host ``seq`` (distinct ``id``) with the SAME
    ``node_id``/``ancestor_path``, the stack must stay balanced, and each iteration's children must nest
    under THAT iteration's host. Driven directly against the collector (the engine wiring for a single
    descent is already covered by the live equivalence tests; this pins the per-iteration invariant).
    """
    c = WorkflowTraceCollector("t", is_run_scoped=True)
    for visit in range(2):
        frame = c.descend("loop-host")
        c.record_node_execution(f"inner-{visit}", "LLMNode", 1.0, True)
        c.ascend()
        c.record_node_execution("loop-host", "WorkflowExecutor", 2.0, True, frame=frame)

    hosts = [e for e in c.events if e["node_id"] == "loop-host"]
    assert len(hosts) == 2
    assert hosts[0]["seq"] != hosts[1]["seq"], "each loop visit reserves a distinct host seq"
    assert all(h["ancestor_path"] == [] for h in hosts), "same (top-level) ancestor_path across visits"
    assert c._host_stack == [], "descend/ascend stayed balanced"

    inners = {e["node_id"]: e for e in c.events if e["node_id"].startswith("inner")}
    assert inners["inner-0"]["parent_id"] == hosts[0]["id"]
    assert inners["inner-1"]["parent_id"] == hosts[1]["id"], "each iteration's child nests under THAT visit's host"


@pytest.mark.trace_files
def test_adr0008_checkpoint_subworkflow_and_parallel_batch_end_to_end(tmp_path, mock_llm_client, monkeypatch):
    """ADR-0008 intermediate checkpoint: ONE run exercising a sequential sub-workflow (NEW flat path)
    AND a parallel batch of sub-workflows (OLD buffer path) end-to-end through the unified collector.

    Asserts correct ``parent_id``/``ancestor_path``/``seq`` on the flat side, inline (uncorrelated)
    batch items on the OLD side, the cost literal, and ``failed_node_ids`` — plus the whole-trace
    ``tree() == reconstruct(disk)`` equivalence with both shapes present.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mock_llm_client.set_response(MODEL, None, {"response": "ok"}, cost_usd=0.01)

    seq_child = tmp_path / "seqchild.pflow.md"
    seq_child.write_text(
        "# SeqChild\n\nSequential child.\n\n## Steps\n\n"
        "### seq-llm\n\nGenerate.\n\n- type: llm\n- model: " + MODEL + "\n- prompt: sequential child respond\n",
        encoding="utf-8",
    )
    batch_child = tmp_path / "batchchild.pflow.md"
    batch_child.write_text(
        "# BatchChild\n\nBatched child.\n\n## Inputs\n\n### topic\n\nThe topic.\n\n- type: string\n\n## Steps\n\n"
        "### batch-llm\n\nRespond.\n\n- type: llm\n- model: " + MODEL + "\n- prompt: respond about ${topic}\n",
        encoding="utf-8",
    )
    parent = tmp_path / "checkpoint.pflow.md"
    parent.write_text(
        f"""\
# Checkpoint

A sequential sub-workflow and a parallel batch of sub-workflows.

## Steps

### call-seq

Sequential sub-workflow (NEW flat path).

- type: workflow
- workflow: {seq_child}

### fanout

Parallel batch of sub-workflows (OLD buffer path).

- type: workflow
- workflow: {batch_child}
- inputs:
    topic: ${{item}}

```yaml batch
items:
  - x
  - y
as: item
parallel: true
```
""",
        encoding="utf-8",
    )

    result = WorkflowRunner().run(str(parent), {}, config=RunnerConfig(cache_enabled=False))
    assert result.success
    collector = result.trace
    by_node = {e["node_id"]: e for e in collector.events}

    # Sequential side: flat, emit-time correlated.
    assert by_node["call-seq"]["parent_id"] is None
    assert by_node["seq-llm"]["parent_id"] == by_node["call-seq"]["id"]
    assert by_node["seq-llm"]["ancestor_path"] == [{"node_id": "call-seq", "batch_index": None}]

    # Batch side: OLD path — the host is top level, items inline and UNcorrelated.
    fanout = by_node["fanout"]
    assert fanout["parent_id"] is None
    assert "batch-llm" not in by_node, "batch sub-workflow children must NOT leak flat into the run collector"
    batch_items = fanout.get("batch_items") or []
    assert len(batch_items) == 2
    for item in batch_items:
        for ev in item.get("events") or []:
            assert "seq" not in ev and "parent_id" not in ev

    # Top-level count = the two host nodes only.
    assert {e["node_id"] for e in collector._top_level_events()} == {"call-seq", "fanout"}

    disk_path = collector.save_to_file()
    disk = load_trace_file(disk_path)
    assert collector.tree() == disk["nodes"]
    # call-seq's seq-llm (fresh) + 2 fresh batch items = 3 fresh LLM calls @ 0.01.
    assert disk["llm_summary"]["total_cost_usd"] == pytest.approx(0.03)
    assert disk["failed_node_ids"] == []
    assert disk["final_status"] == "success"


@pytest.mark.trace_files
def test_only_on_subworkflow_does_not_clobber_only_node(tmp_path, mock_llm_client, monkeypatch):
    """Regression (Task 172): ``--only <sub-workflow-node>`` must keep the trace's ``only_node`` marker.

    The sub-workflow target descends into the run collector (NEW path), and its child engine's
    ``run()`` would otherwise re-stamp the shared collector's ``only_node`` to its own ``None`` — wiping
    the root's ``--only`` marker and turning the trace into a poison full-run snapshot source (issue
    #443). Only the OWNING engine stamps ``only_node``.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mock_llm_client.set_response(MODEL, None, {"response": "ok"}, cost_usd=0.01)

    child = tmp_path / "ochild.pflow.md"
    child.write_text(
        "# OChild\n\nChild.\n\n## Steps\n\n### ochild-llm\n\nGen.\n\n- type: llm\n- model: "
        + MODEL
        + "\n- prompt: hi\n",
        encoding="utf-8",
    )
    parent = tmp_path / "oparent.pflow.md"
    parent.write_text(
        "# OParent\n\nParent.\n\n## Steps\n\n### top-llm\n\nGen.\n\n- type: llm\n- model: "
        + MODEL
        + "\n- prompt: hi\n\n"
        "### call-child\n\nDelegate.\n\n- type: workflow\n- workflow: " + str(child) + "\n",
        encoding="utf-8",
    )

    # Full run first to lay down the snapshot the --only run restores upstream from.
    full = _run(parent)
    assert full.success
    full.trace.save_to_file()

    # --only the sub-workflow node: it descends into the run collector but must not clobber only_node.
    only = WorkflowRunner().run(str(parent), {}, config=RunnerConfig(only_node="call-child"))
    assert only.success
    assert only.trace.only_node == "call-child", "child engine must not clobber the root's --only marker"


def test_host_recorded_after_ascend_with_frame_keeps_children_linked():
    """api-warning timing (Task 172): a sub-workflow host's completion event can be recorded AFTER its
    descent frame is popped — api-warning fires at engine step 10, by which point exec()'s finally has
    already ascended. The host MUST reuse its reserved frame (not take a fresh seq), or its
    already-recorded children orphan and ``reconstruct`` raises on a COMPLETE trace (all three readers
    then skip it). This pins the reconstruct-survives invariant; the engine achieves it by threading
    ``frame=host_frame`` into ``handle_api_warning`` (confirmed correct by review + the live equivalence
    tests — this collector-level test locks the mechanic the wiring exists to protect).
    """
    from pflow.core.trace_io import emit_flat_events_to_lines, reconstruct_trace_from_lines

    c = WorkflowTraceCollector("t", workflow_path="wf", is_run_scoped=True)
    frame = c.descend("host")
    c.record_node_execution("child", "LLMNode", 1.0, True)  # child seq is AFTER the host's reserved seq
    c.ascend()  # frame popped (exec's finally) BEFORE the host records (mirrors the step-10 api-warning)
    c.record_node_execution("host", "WorkflowExecutor", 2.0, False, error="api warning", frame=frame)
    assert c._host_stack == [], "balanced descend/ascend"

    by_node = {e["node_id"]: e for e in c.events}
    assert by_node["child"]["parent_id"] == by_node["host"]["id"], "child must still link to the host's reserved id"

    trace_data = {
        "format_version": "2.5.0",
        "execution_id": c.execution_id,
        "workflow_name": "t",
        "workflow_path": "wf",
        "start_time": "2026-06-22T00:00:00",
        "only_node": None,
        "nodes": c.events,
    }
    reconstructed = reconstruct_trace_from_lines(emit_flat_events_to_lines(trace_data))  # must NOT raise
    host_node = reconstructed["nodes"][0]
    assert host_node["node_id"] == "host"
    assert [e["node_id"] for e in host_node.get("sub_workflow_events", [])] == ["child"]


@pytest.mark.trace_files
def test_old_path_sequential_batch_of_subworkflows_stays_nested(tmp_path, mock_llm_client, monkeypatch):
    """OLD-path preservation for a SEQUENTIAL batch (distinct instance-reuse path from parallel).

    A sequential batch reuses the SAME WorkflowExecutor instance across items, so the ``_host_frame``
    reset at exec() top is load-bearing against leakage. Items take the OLD buffer path (no correlation
    keys), nesting under ``batch_items[*].events``; the run collector's host stack stays balanced (the OLD
    path never descends).
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mock_llm_client.set_response(MODEL, None, {"response": "ok"}, cost_usd=0.01)

    child = tmp_path / "schild.pflow.md"
    child.write_text(
        "# SChild\n\nBatched child.\n\n## Inputs\n\n### topic\n\nThe topic.\n\n- type: string\n\n## Steps\n\n"
        "### schild-llm\n\nRespond.\n\n- type: llm\n- model: " + MODEL + "\n- prompt: respond about ${topic}\n",
        encoding="utf-8",
    )
    parent = tmp_path / "sparent.pflow.md"
    parent.write_text(
        f"""\
# SParent

Sequential batch of sub-workflows.

## Steps

### fanout

Run the child per item, sequentially.

- type: workflow
- workflow: {child}
- inputs:
    topic: ${{item}}

```yaml batch
items:
  - a
  - b
as: item
parallel: false
```
""",
        encoding="utf-8",
    )

    result = _run(parent, cache_enabled=False)
    assert result.success
    collector = result.trace
    assert collector._host_stack == [], "OLD batch path never descends → stack stays balanced"
    assert [e["node_id"] for e in collector._top_level_events()] == ["fanout"]
    assert len(collector.events) == 1, "no flat sub-workflow children leaked into the run collector"
    batch_items = collector.events[0].get("batch_items") or []
    assert len(batch_items) == 2
    for item in batch_items:
        assert "id" not in item and "seq" not in item and "parent_id" not in item
        for ev in item.get("events") or []:
            assert "seq" not in ev and "parent_id" not in ev
            assert ev["node_id"] == "schild-llm"
    disk_path = collector.save_to_file()
    disk = load_trace_file(disk_path)
    assert collector.tree() == disk["nodes"]
