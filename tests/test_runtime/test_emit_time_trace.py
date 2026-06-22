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

import json
from pathlib import Path

import pytest

from pflow.core.trace_io import load_trace_file
from pflow.execution import WorkflowRunner
from pflow.execution.result import RunnerConfig
from pflow.runtime.workflow_trace import WorkflowTraceCollector


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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


@pytest.mark.trace_files
def test_host_recorded_after_ascend_with_frame_keeps_children_linked(tmp_path, monkeypatch):
    """api-warning timing (Task 172): a sub-workflow host's completion event can be recorded AFTER its
    descent frame is popped — api-warning fires at engine step 10, by which point exec()'s finally has
    already ascended. The host MUST reuse its reserved frame (not take a fresh seq), or its
    already-STREAMED children orphan and ``reconstruct`` raises on a COMPLETE trace (all three readers
    then skip it). Driven through the REAL streaming writer + ``finalize()`` + ``load_trace_file`` — the
    production path — so the reconstruct-survives invariant is pinned on-disk, not via a hand-built emit.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    c = WorkflowTraceCollector("t", workflow_path="wf", is_run_scoped=True, stream_to_disk=True)
    frame = c.descend("host")
    c.record_node_execution("child", "LLMNode", 1.0, True)  # child seq is AFTER the host's reserved seq; flushed first
    c.ascend()  # frame popped (exec's finally) BEFORE the host records (mirrors the step-10 api-warning)
    c.record_node_execution("host", "WorkflowExecutor", 2.0, False, error="api warning", frame=frame)
    assert c._host_stack == [], "balanced descend/ascend"

    by_node = {e["node_id"]: e for e in c.events}
    assert by_node["child"]["parent_id"] == by_node["host"]["id"], "child must still link to the host's reserved id"

    disk = load_trace_file(c.finalize())  # COMPLETE streamed trace; reconstruct must NOT raise
    host_node = disk["nodes"][0]
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


# --- Task 172 step 3: per-event streaming (incremental flush + finalize + dead-end re-flush + gate) ---


@pytest.mark.trace_files
def test_streaming_flushes_incrementally_then_finalize_caps_with_run_complete(tmp_path, mock_llm_client, monkeypatch):
    """Per-event streaming: events land on disk DURING the run (incremental flush), run.complete only at
    finalize(). Proven by reading the still-open stream BEFORE finalize — events present, no run.complete —
    then re-reading after finalize."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mock_llm_client.set_response(MODEL, None, {"response": "ok"}, cost_usd=0.01)
    wf = tmp_path / "stream.pflow.md"
    wf.write_text(
        "# Stream\n\nTwo LLM nodes.\n\n## Steps\n\n"
        "### one\n\nGen.\n\n- type: llm\n- model: " + MODEL + "\n- prompt: one\n\n"
        "### two\n\nGen.\n\n- type: llm\n- model: " + MODEL + "\n- prompt: two\n",
        encoding="utf-8",
    )

    result = _run(wf, cache_enabled=False)
    assert result.success
    collector = result.trace
    assert collector.is_run_scoped and collector._stream_path is not None

    # BEFORE finalize: meta + both event lines already flushed; the run.complete trailer is NOT yet written.
    pre = _read_lines(collector._stream_path)
    pre_kinds = [ln["kind"] for ln in pre]
    assert pre_kinds[0] == "meta"
    assert [ln["node_id"] for ln in pre if ln["kind"] == "event"] == ["one", "two"], "one event line per node"
    assert "run.complete" not in pre_kinds, "run.complete is written only at finalize(), not per-event"

    # finalize() caps the stream with run.complete and closes; the path is the same streamed file.
    path = collector.finalize()
    assert path == collector._stream_path
    post = _read_lines(path)
    assert post[-1]["kind"] == "run.complete"
    assert sum(1 for ln in post if ln["kind"] == "event") == 2
    disk = load_trace_file(path)
    assert disk["final_status"] == "success"
    assert collector.tree() == disk["nodes"]
    assert disk["llm_summary"]["total_cost_usd"] == pytest.approx(0.02)


@pytest.mark.trace_files
def test_streaming_finalize_is_idempotent(tmp_path, monkeypatch):
    """finalize() is guarded across the two CLI call sites (text-success + the finally block) — calling it
    twice writes run.complete once and returns the same path."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    c = WorkflowTraceCollector("t", workflow_path="wf", is_run_scoped=True, stream_to_disk=True)
    c.record_node_execution("a", "ShellNode", 1.0, True, node_output={"v": 1})
    first = c.finalize()
    second = c.finalize()
    assert first == second
    lines = _read_lines(first)
    assert sum(1 for ln in lines if ln["kind"] == "run.complete") == 1, "run.complete written exactly once"


@pytest.mark.trace_files
def test_streaming_blob_shared_across_events_declared_once(tmp_path, monkeypatch):
    """Streaming dedups blobs ACROSS per-event flushes via the persistent ``_declared_blobs`` set: two
    nodes emitting the SAME >1KB payload produce ONE ``blob`` line (declared on the first flush, a
    backward ref on the second). The whole-file ``_inline_blobs`` path dedups within a single call; this
    pins the streaming cross-flush accumulation (a distinct never-run path — a bug that reset
    ``_declared_blobs`` per event would re-emit the blob)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    big = "SHARED-" + ("q" * 2000)
    c = WorkflowTraceCollector("t", workflow_path="wf", is_run_scoped=True, stream_to_disk=True)
    c.record_node_execution("a", "ShellNode", 1.0, True, node_output={"r": big})
    c.record_node_execution("b", "ShellNode", 1.0, True, node_output={"r": big})
    path = c.finalize()

    raw = _read_lines(path)
    blob_lines = [ln for ln in raw if ln["kind"] == "blob"]
    assert len(blob_lines) == 1, "the shared payload is declared exactly once across the two event flushes"
    assert blob_lines[0]["value"] == big
    disk = load_trace_file(path)  # both events resolve the ref back to the full payload
    assert disk["nodes"][0]["node_output"]["r"] == big and disk["nodes"][1]["node_output"]["r"] == big


@pytest.mark.trace_files
def test_streaming_dead_end_re_flush_corrects_on_disk(tmp_path, monkeypatch):
    """Piece 5.4 — the routing dead-end re-flush, the ONLY path where an event flushes (status=success)
    BEFORE its correction. mark_last_event_failed re-flushes the SAME id with status=failed; the two-pass
    reconstruct dedups by id (last-wins) so the corrected line wins on disk → tree() == reconstruct(disk).
    Driven at the collector to exercise re-flush + dedup precisely (engine wiring is covered by
    test_failed_node_invariant)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    c = WorkflowTraceCollector("t", workflow_path="wf", is_run_scoped=True, stream_to_disk=True)
    c.record_node_execution("a", "ShellNode", 1.0, True, node_output={"v": 1})  # flushed status=success
    c.mark_last_event_failed("a", error="no successor edge matches")  # re-flushes the corrected line
    path = c.finalize()

    raw = _read_lines(path)
    a_lines = [ln for ln in raw if ln["kind"] == "event" and ln["node_id"] == "a"]
    assert [ln["status"] for ln in a_lines] == ["success", "failed"], "the correction was re-flushed as a 2nd line"

    disk = load_trace_file(path)
    assert len(disk["nodes"]) == 1, "dedup-by-id collapses the original + correction to one node"
    assert disk["nodes"][0]["status"] == "failed" and disk["nodes"][0]["error"] == "no successor edge matches"
    assert c.tree() == disk["nodes"], "in-memory mutated tree matches the deduped disk reconstruct"
    assert disk["final_status"] == "failed" and disk["failed_node_ids"] == ["a"]


@pytest.mark.trace_files
def test_streaming_gated_off_when_stream_to_disk_false(tmp_path, monkeypatch):
    """The production gate: stream_to_disk=False (the MCP path and --no-trace) writes NOTHING, even with the
    trace_files marker (so the real _open_stream runs and the gate — not the conftest patch — is under test).
    The in-memory collector still works for the cost summary; only disk streaming is suppressed."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    c = WorkflowTraceCollector("t", workflow_path="wf", is_run_scoped=True, stream_to_disk=False)
    c.record_node_execution("a", "ShellNode", 1.0, True)
    assert c.finalize() is None, "stream_to_disk=False must not write a trace file"
    debug = tmp_path / ".pflow" / "debug"
    assert not debug.exists() or not list(debug.glob("*.json"))


@pytest.mark.trace_files
def test_streamed_trace_is_read_by_all_disk_consumers(tmp_path, mock_llm_client, monkeypatch):
    """Every post-hoc consumer of ``~/.pflow/debug`` must read a STREAMED trace end-to-end — not just the
    legacy single-object traces the analyze-cache unit tests hand-build. The three real consumers all
    funnel through ``load_trace_file``: ``generate_report`` (``pflow report`` / ``--report``), the shared
    ``_iter_workflow_traces`` autoload (analyze-cache **and** the ``--only`` snapshot loader), and the full
    ``analyze()`` autoload. Drives a real LLM run → streamed trace → each consumer, on the production
    loaders. (The ``--only`` engine path itself is also covered by ``test_only_snapshot.py``'s
    ``@trace_files`` real-run tests, which now read streamed snapshots.)"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mock_llm_client.set_response(MODEL, None, {"response": "ok"}, cost_usd=0.01)
    wf = tmp_path / "consumed.pflow.md"
    wf.write_text(
        "# Consumed\n\nOne LLM node.\n\n## Steps\n\n### ask\n\nAsk.\n\n- type: llm\n- model: "
        + MODEL
        + "\n- prompt: hi\n",
        encoding="utf-8",
    )

    result = _run(wf, cache_enabled=False)
    assert result.success
    streamed_path = result.trace.finalize()
    assert streamed_path is not None and streamed_path.exists()
    wf_path = result.trace.workflow_path

    # Consumer 1 — generate_report reads the streamed JSONL trace into a report directory.
    from pflow.core.trace_report import generate_report

    generate_report(str(streamed_path), str(tmp_path / "report"), None, None)
    assert "ask" in (tmp_path / "report" / "summary.md").read_text(encoding="utf-8")

    # Consumer 2 — the shared autoload iterator (analyze-cache + --only snapshot) finds + parses it.
    from pflow.runtime.workflow_trace import _iter_workflow_traces, load_full_run_events

    debug_dir = tmp_path / ".pflow" / "debug"
    found = list(_iter_workflow_traces(debug_dir, wf_path))
    assert any(p == streamed_path for p, _ in found), "autoload must find the streamed trace"
    assert all(d.get("final_status") == "success" for _, d in found)
    # --only snapshot loader returns the streamed run's nodes (the engine seeds upstream from this).
    loaded = load_full_run_events(wf_path, debug_dir=debug_dir)
    assert loaded is not None and [n["node_id"] for n in loaded[0]] == ["ask"] and loaded[1] == "success"

    # Consumer 3 — analyze-cache autoload reads the streamed trace via the real analyze() entry point.
    from pflow.core.prompt_cache_analysis.analyze import analyze
    from pflow.execution.workflow_resolver import resolve_workflow

    analysis = analyze(resolve_workflow(str(wf)).ir, workflow_path=wf_path, auto_load_trace=True)
    assert analysis.trace_path == str(streamed_path), "analyze-cache autoload must consume the STREAMED trace"


def test_non_trace_files_run_does_not_stream_to_disk(tmp_path, monkeypatch):
    """The conftest gate: a NON-trace_files run (no marker) no-ops _open_stream, so a streamed run-scoped
    collector writes nothing — the I/O-timing safety net the braindump flagged. (No @trace_files marker.)"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    wf = tmp_path / "g.pflow.md"
    wf.write_text(
        "# G\n\nOne shell node.\n\n## Steps\n\n### s\n\nEcho.\n\n- type: shell\n- command: echo hi\n",
        encoding="utf-8",
    )
    result = WorkflowRunner().run(str(wf), {}, config=RunnerConfig(cache_enabled=False))
    assert result.success
    debug = tmp_path / ".pflow" / "debug"
    assert not debug.exists() or not list(debug.glob("*.json")), "non-trace_files run must not stream to disk"
