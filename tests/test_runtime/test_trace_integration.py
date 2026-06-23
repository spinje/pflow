"""Integration tests for trace event capture through the execution engine.

These tests verify the integration seams between the engine, trace collectors,
and batch processing — areas where silent data loss occurs when template
resolution, namespacing, or trace recording breaks.

Migrated from wrapper-based tests to compile_workflow + WorkflowEngine
tests after the wrappers were replaced by the engine (Task 135/138).
"""

from typing import Any

import pytest

from pflow.core.trace_io import BLOB_SENTINEL, intern_blobs
from pflow.runtime.engine.batch_executor import _capture_item_trace
from pflow.runtime.workflow_trace import WorkflowTraceCollector


def _run_with_trace(
    ir: dict[str, Any],
    initial_params: dict[str, Any] | None = None,
    extra_shared: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], WorkflowTraceCollector]:
    """Compile and run a workflow, returning (shared, trace_collector)."""
    from pflow.registry import Registry
    from pflow.runtime import compile_workflow
    from pflow.runtime.engine import WorkflowEngine

    collector = WorkflowTraceCollector("test-trace")

    registry = Registry()
    workflow = compile_workflow(ir_json=ir, registry=registry, initial_params=initial_params)

    shared: dict[str, Any] = {"__trace_collector__": collector}
    if initial_params:
        shared.update({k: v for k, v in initial_params.items() if not k.startswith("__")})
    shared.update(workflow.resolved_defaults)
    if extra_shared:
        shared.update(extra_shared)

    engine = WorkflowEngine(trace_collector=collector)
    engine.run(workflow, shared)
    return shared, collector


class TestTemplateResolutionsInTrace:
    """Test that template resolutions appear in trace events.

    Verifies the full pipeline: engine resolves templates, passes
    last_resolutions to record_trace, trace event captures them.
    """

    def test_template_resolutions_propagate_to_trace(self) -> None:
        """When a template param is resolved, the trace event captures
        the before/after mapping."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "echo",
                    "type": "shell",
                    "params": {"command": "printf '%s' 'Hello ${name}'"},
                },
            ],
            "edges": [],
            "inputs": {"name": {"type": "string", "description": "Name input"}},
        }

        _shared, collector = _run_with_trace(ir, initial_params={"name": "World"})

        assert len(collector.events) == 1
        event = collector.events[0]

        assert event["status"] == "success"
        assert event["node_type"] == "ShellNode"

        # Template resolutions should be captured
        assert "template_resolutions" in event, (
            "template_resolutions missing from trace event — engine may not be passing last_resolutions to record_trace"
        )
        resolutions = event["template_resolutions"]
        assert "command" in resolutions
        assert resolutions["command"]["template"] == "printf '%s' 'Hello ${name}'"
        assert resolutions["command"]["resolved"] == "printf '%s' 'Hello World'"

        # Node output should be namespaced
        assert "node_output" in event
        assert event["node_output"]["stdout"] == "Hello World"

        # Mutations should include the echo node's namespace
        assert "mutations" in event
        assert "echo" in event["mutations"]["added"]


class TestBatchNodeTraceEvents:
    """Test batch node trace events through the engine."""

    def test_batch_items_appear_in_trace_event(self) -> None:
        """When a batch node processes items, per-item trace data appears
        nested inside the parent trace event."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "processor",
                    "type": "shell",
                    "params": {"command": "printf '%s' '${item}'"},
                    "batch": {"items": "${data}", "as": "item"},
                },
            ],
            "edges": [],
        }

        _shared, collector = _run_with_trace(ir, extra_shared={"data": ["a", "b", "c"]})

        assert len(collector.events) == 1
        event = collector.events[0]

        assert event["status"] == "success"
        assert event["node_type"] == "ShellNode"

        # Batch items should be captured
        assert "batch_items" in event, (
            "batch_items missing from trace event — batch executor may not be returning trace items"
        )
        batch_items = event["batch_items"]
        assert len(batch_items) == 3

        # Verify per-item structure
        for i, expected_item in enumerate(["a", "b", "c"]):
            item_trace = batch_items[i]
            assert item_trace["index"] == i
            assert item_trace["item"] == expected_item
            assert item_trace["status"] == "success"
            assert "duration_ms" in item_trace
            assert isinstance(item_trace["duration_ms"], (int, float))


class TestTraceToReportFormatCompatibility:
    """Verify the trace collector's output is readable by the report generator.

    Both sides have unit tests with synthetic data. This test catches format
    drift: if a field name changes in record_trace() but not in the report
    generator (or vice versa), reports silently produce empty content.

    Uses a real workflow → real trace → real report generation.
    """

    def test_batch_trace_produces_valid_report(self, tmp_path: "Any") -> None:
        """Run a batch through real engine, save trace, generate report,
        verify the report has real content from execution."""
        import json

        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "processor",
                    "type": "shell",
                    "params": {"command": "printf '%s' '${item}'"},
                    "batch": {"items": "${data}", "as": "item"},
                },
            ],
            "edges": [],
        }

        _shared, collector = _run_with_trace(ir, extra_shared={"data": ["alpha", "beta"]})

        # Build trace dict from REAL collector data (same structure as save_to_file)
        trace_data = {
            "format_version": "2.0.0",
            "execution_id": collector.execution_id,
            "workflow_name": collector.workflow_name,
            "start_time": collector.start_time.isoformat(),
            "end_time": collector.start_time.isoformat(),
            "duration_ms": 100.0,
            "final_status": "success",
            "nodes_executed": len(collector.events),
            "nodes_failed": 0,
            "nodes": collector.events,
        }
        trace_path = tmp_path / "trace.json"
        trace_path.write_text(json.dumps(trace_data, default=str))

        # Generate report from the real trace
        from pflow.core.trace_report import generate_report

        report_dir = generate_report(str(trace_path), str(tmp_path / "report"))

        assert report_dir is not None, "Report generation failed on real trace data"
        assert (report_dir / "summary.md").exists()

        # Batch node should create a directory (not a flat file)
        batch_dir = report_dir / "01-processor"
        assert batch_dir.is_dir(), "Batch node should produce a directory, not a file"
        assert (batch_dir / "summary.md").exists()
        assert (batch_dir / "item-0-alpha.md").exists()
        assert (batch_dir / "item-1-beta.md").exists()

        # Summary should reference the batch and explode items into per-item rows
        summary_md = (report_dir / "summary.md").read_text()
        assert "processor" in summary_md
        # New Tokens column header is always present, even when no LLM ran.
        assert "| # | Node | Type | Status | Time | Tokens | Cost |" in summary_md
        # Pin column order at the producer→renderer boundary. Allow only the
        # duration cell to vary (real wall-clock time); the (label) tail
        # comes from _extract_item_label rendering `(alpha)`/`(beta)` for
        # string batch items. Catches drift between WorkflowTraceCollector
        # field names and renderer expectations.
        import re

        for idx, label in ((0, "alpha"), (1, "beta")):
            row_pattern = rf"\| 1 \| processor\[{idx}\] \({label}\) \| shell \| success \| \S+ \| — \| — \|"
            assert re.search(row_pattern, summary_md), (
                f"Expected exploded batch row for processor[{idx}] ({label}) with full column order; got:\n{summary_md}"
            )


class TestParallelBatchTraceCapture:
    """Verify parallel batch items capture template_resolutions correctly.

    The parallel path deep-copies the node per thread. Each copy must
    independently resolve templates and capture resolutions.
    """

    def test_parallel_batch_captures_per_item_template_resolutions(self) -> None:
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "greeter",
                    "type": "shell",
                    "params": {"command": "printf '%s' '${item}'"},
                    "batch": {"items": "${data}", "as": "item", "parallel": True},
                },
            ],
            "edges": [],
        }

        _shared, collector = _run_with_trace(ir, extra_shared={"data": ["alice", "bob"]})

        assert len(collector.events) == 1
        event = collector.events[0]
        assert "batch_items" in event
        batch_items = event["batch_items"]
        assert len(batch_items) == 2

        # Parallel batch items may complete in any order — match by content
        resolved_commands = set()
        for item in batch_items:
            assert item["status"] == "success"
            # Template resolutions captured from per-item resolution
            resolutions = item.get("template_resolutions", {})
            assert "command" in resolutions, (
                "template_resolutions missing 'command' — "
                "per-item template resolution may not be captured in batch trace"
            )
            resolved_commands.add(resolutions["command"]["resolved"])
        assert resolved_commands == {"printf '%s' 'alice'", "printf '%s' 'bob'"}


class TestFailedBatchItemsInTrace:
    """Verify failed batch items appear with error data in trace."""

    def test_failed_item_has_error_in_trace(self) -> None:
        """Shell node processes items, one fails. The failure should appear in trace."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "processor",
                    "type": "shell",
                    "params": {"command": "test '${item}' != 'bad' && echo ok || exit 1"},
                    "batch": {"items": "${data}", "as": "item", "error_handling": "continue"},
                },
            ],
            "edges": [],
        }

        _shared, collector = _run_with_trace(ir, extra_shared={"data": ["good", "bad", "good"]})

        assert len(collector.events) == 1
        event = collector.events[0]
        batch_items = event["batch_items"]
        assert len(batch_items) == 3

        # Item 0 and 2: success
        assert batch_items[0]["status"] == "success"
        assert batch_items[0]["item"] == "good"
        assert batch_items[2]["status"] == "success"

        # Item 1: failure
        assert batch_items[1]["status"] == "failed"
        assert batch_items[1]["item"] == "bad"

    def test_failed_batch_with_completed_nested_llm_persists_to_trace(
        self,
        tmp_path: "Any",
    ) -> None:
        """When a batch sub-workflow fails AFTER completing an LLM call, the
        completed nested LLM event MUST appear in the parent's batch_items trace.

        Pre-fix shape (Bug B): ``execute_batch`` popped batch trace items into a
        local before raising for ``fail_fast`` with errors. The engine's except
        handler then passed ``batch_trace_items=None`` to ``record_trace``, so
        completed-before-failure work vanished from the trace. ``analyze-cache``
        downstream reported ``calls=0 [unexecuted]`` for nodes that actually ran.

        Post-fix: producer (``execute_batch``) leaves items in
        ``shared["_batch_trace"]``; the engine drains them on both success and
        exception paths. The recovery channel is the shared store, not a
        return-tuple that gets discarded on raise.

        Mutation contract:
          - Revert ``execute_batch`` to call ``_collect_batch_trace`` itself and
            pack into a return tuple → ``batch_items`` becomes ``None`` on the
            engine's except path → this test fails because the completed-nested
            shell event is missing.
          - Drop the except-path drain in ``engine._execute_node`` → same
            failure mode.
        """
        from tests.shared.markdown_utils import write_workflow_file

        # Child workflow: ``before-failure`` succeeds, ``fail-after`` raises.
        # Mirrors repro-06-failing-child.pflow.md, but uses shell nodes to
        # keep the test offline. The "completed nested work" signal is the
        # presence of ``before-failure``'s event in the trace.
        child_ir = {
            "nodes": [
                {
                    "id": "before-failure",
                    "type": "shell",
                    "params": {"command": "echo completed"},
                    "purpose": "Step that runs before the failing step.",
                },
                {
                    "id": "fail-after",
                    "type": "shell",
                    "params": {"command": "exit 1"},
                    "purpose": "Step that fails to terminate the child workflow.",
                },
            ],
            "edges": [],
        }
        child_path = tmp_path / "child.pflow.md"
        write_workflow_file(child_ir, child_path)

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "child-batch",
                    "type": "workflow",
                    "params": {"workflow": str(child_path)},
                    "batch": {"items": "${labels}", "as": "label", "parallel": False},
                    "purpose": "Batch over labels, invoking the failing child once per label.",
                },
            ],
            "edges": [],
        }

        with pytest.raises(RuntimeError):
            _run_with_trace(parent_ir, extra_shared={"labels": ["alpha", "beta"]})

        # The trace must record the failed batch node WITH its completed nested work.
        # Engine's except-path drain populates batch_items even when the batch raises.
        # (Re-running here with no exception assertion is awkward; rely on the
        # collector snapshot above — the run raised but record_trace fired first.)
        # Build a fresh collector and re-run to grab the trace events.
        from pflow.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        collector = WorkflowTraceCollector("failed-batch-test")
        registry = Registry()
        workflow = compile_workflow(ir_json=parent_ir, registry=registry, initial_params={})
        shared: dict[str, Any] = {
            "__trace_collector__": collector,
            "labels": ["alpha", "beta"],
        }
        shared.update(workflow.resolved_defaults)
        engine = WorkflowEngine(trace_collector=collector)
        with pytest.raises(RuntimeError):
            engine.run(workflow, shared)

        assert len(collector.events) == 1
        event = collector.events[0]
        assert event["node_id"] == "child-batch"
        batch_items = event.get("batch_items")
        assert batch_items is not None, "batch_items must persist on failed batches"
        # Default error_handling=fail_fast stops after the first failing item.
        # The load-bearing assertion is not the item count — it's that the
        # completed nested work BEFORE the failure point is present.
        assert len(batch_items) >= 1

        # Item ran the child workflow's `before-failure` step successfully
        # before `fail-after` raised. That successful step MUST appear in the
        # item's nested events list — that's the Bug B regression signal.
        first_item = batch_items[0]
        sub_events = first_item.get("events") or []
        before_failure_events = [e for e in sub_events if e.get("node_id") == "before-failure"]
        assert len(before_failure_events) == 1, (
            f"completed nested 'before-failure' event missing from batch item: {first_item!r}"
        )
        assert before_failure_events[0].get("status") == "success"

    def test_succeeded_batch_persists_items_when_post_exec_step_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """W1 regression: a successful ``execute_batch`` followed by an
        exception in a later step (e.g. ``write_memo_cache``) must still
        preserve batch trace items in the trace.

        Pre-fix shape: ``engine._execute_node`` drained the per-item buffer
        immediately after ``execute_batch`` returned (line 576). If anything
        between that drain and ``record_trace`` raised — memo cache SQLite
        IO, ``detect_api_warning``, metrics — the except handler's drain
        popped an already-empty buffer and ``record_trace`` got
        ``batch_trace_items=[]``. Items silently lost.

        Post-fix: the drain happens at exactly one site per branch (right
        before ``record_trace``). The buffer sits in the shared store until
        the consumer reads it on whichever branch wins.

        Mutation contract: revert the W1 fix (drain immediately after
        ``execute_batch`` returns) and this test fails — batch_items would
        be ``[]`` on the except path.
        """
        from pflow.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine, instrumentation

        # Make ``write_memo_cache`` raise — this is a step between the
        # successful ``execute_batch`` call and ``record_trace`` in the engine.
        call_count = {"n": 0}

        def _failing_write_memo_cache(*_args: Any, **_kwargs: Any) -> None:
            call_count["n"] += 1
            raise RuntimeError("simulated SQLite IO error mid-execute_node")

        monkeypatch.setattr(instrumentation, "write_memo_cache", _failing_write_memo_cache)
        # The engine imports write_memo_cache via "from .instrumentation import ..."
        # so we need to patch it at the import site too.
        from pflow.runtime.engine import engine as engine_module

        monkeypatch.setattr(engine_module, "write_memo_cache", _failing_write_memo_cache)

        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch-node",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": "echo ok-${item}"},
                    "batch": {"items": "${data}", "as": "item"},
                },
            ],
            "edges": [],
        }
        collector = WorkflowTraceCollector("post-exec-raise-test")
        registry = Registry()
        workflow = compile_workflow(ir_json=ir, registry=registry, initial_params={})
        shared: dict[str, Any] = {
            "__trace_collector__": collector,
            "data": ["one", "two"],
        }
        shared.update(workflow.resolved_defaults)
        engine = WorkflowEngine(trace_collector=collector)

        with pytest.raises(RuntimeError, match="simulated SQLite IO error"):
            engine.run(workflow, shared)

        assert call_count["n"] >= 1, "write_memo_cache must have been called"
        assert len(collector.events) == 1
        event = collector.events[0]
        assert event["node_id"] == "batch-node"
        batch_items = event.get("batch_items") or []
        assert len(batch_items) == 2, (
            f"both completed batch items must persist to the trace even when "
            f"a post-exec step raised; got: {batch_items!r}"
        )


class TestSubWorkflowTraceTree:
    """Verify sub-workflow internal nodes appear as sub_workflow_events.

    Uses compile_workflow + WorkflowEngine to build a real parent workflow
    with a child sub-workflow. The child's nodes should appear nested in
    the parent's trace event under sub_workflow_events.
    """

    def test_sub_workflow_events_in_parent_trace(self, tmp_path: "Any") -> None:
        from tests.shared.markdown_utils import write_workflow_file

        # Create child workflow: single shell node
        child_ir = {
            "nodes": [
                {
                    "id": "inner-step",
                    "type": "shell",
                    "params": {"command": "echo hello"},
                    "purpose": "Simple inner step for sub-workflow test",
                },
            ],
        }
        child_path = tmp_path / "child.pflow.md"
        write_workflow_file(child_ir, child_path)

        # Create parent workflow: calls child sub-workflow
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {"workflow": str(child_path)},
                    "purpose": "Call child sub-workflow for trace test",
                },
            ],
            "edges": [],
        }

        from pflow.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        collector = WorkflowTraceCollector("test-sub-workflow")

        registry = Registry()
        workflow = compile_workflow(ir_json=parent_ir, registry=registry)

        shared: dict[str, Any] = {"__trace_collector__": collector}
        shared.update(workflow.resolved_defaults)

        engine = WorkflowEngine(trace_collector=collector)
        engine.run(workflow, shared)

        # Parent trace should have one event (call-child)
        assert len(collector.events) >= 1
        parent_event = collector.events[0]
        assert parent_event["node_id"] == "call-child"

        # That event should contain sub_workflow_events from the child
        sub_events = parent_event.get("sub_workflow_events")
        assert sub_events is not None, (
            "sub_workflow_events missing — child trace collector may not be created "
            "or _child_trace_events may not be read by the engine"
        )
        assert len(sub_events) >= 1

        # Child's inner-step should be present
        child_node_ids = [e["node_id"] for e in sub_events]
        assert "inner-step" in child_node_ids


class TestTemplateResolutionsOnError:
    """Verify template resolution errors are raised with useful info."""

    def test_unresolved_template_raises_with_context(self) -> None:
        """When strict template resolution fails, the ValueError should
        contain actionable information about what was unresolved."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "broken-node",
                    "type": "shell",
                    "params": {"command": "echo Summarize ${fetch.result.messages}"},
                },
            ],
            "edges": [],
        }

        from pflow.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        registry = Registry()
        workflow = compile_workflow(ir_json=ir, registry=registry)

        # Provide upstream data that resolves "fetch" but NOT "fetch.result.messages"
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        shared["fetch"] = {"result": {"issues": [1, 2, 3], "total_count": 3}}

        engine = WorkflowEngine()

        with pytest.raises(ValueError, match="Unresolved") as exc_info:
            engine.run(workflow, shared)

        # Error message should contain the unresolved template reference
        error_msg = str(exc_info.value)
        assert "fetch.result.messages" in error_msg

    def test_execution_error_captured_in_trace(self) -> None:
        """When a node raises during execution (not template resolution),
        the trace event should capture the error with template_resolutions.

        Note: Template resolution errors ARE also captured in trace events
        (resolution runs inside the engine's try/except). Partial resolutions
        up to the error point are included via _pflow_partial_resolutions on the ValueError.
        """
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "failing-node",
                    "type": "shell",
                    "params": {"command": "echo hi", "cwd": "/nonexistent/path/xyz"},
                },
            ],
            "edges": [],
        }

        collector = WorkflowTraceCollector("test-exec-error")

        from pflow.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        registry = Registry()
        workflow = compile_workflow(ir_json=ir, registry=registry)

        shared: dict[str, Any] = dict(workflow.resolved_defaults)

        engine = WorkflowEngine(trace_collector=collector)

        with pytest.raises(ValueError, match="does not exist"):
            engine.run(workflow, shared)

        # Trace event should be recorded for execution errors
        assert len(collector.events) == 1
        event = collector.events[0]
        assert event["status"] == "failed"
        assert "error" in event
        assert "does not exist" in event["error"]

    def test_template_resolution_error_captured_in_trace_with_partial_resolutions(self) -> None:
        """When template resolution fails in strict mode, the trace event should
        capture partial resolutions (params resolved up to the error point).

        This tests the _pflow_partial_resolutions mechanism: resolve_templates()
        attaches partial resolutions to the ValueError, and the engine's except
        handler extracts them for trace recording. Without this, template errors
        produce trace events with empty template_resolutions — losing debug
        information.
        """
        # Two template params: first resolves, second fails.
        # The trace should show the first param's resolution.
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "producer",
                    "type": "shell",
                    "params": {"command": "echo hello"},
                },
                {
                    "id": "consumer",
                    "type": "shell",
                    "params": {
                        "command": "${producer.stdout}",  # resolves
                        "cwd": "${nonexistent.path}",  # fails
                    },
                },
            ],
            "edges": [{"source": "producer", "target": "consumer"}],
        }

        collector = WorkflowTraceCollector("test-partial-resolutions")

        from pflow.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        registry = Registry()
        workflow = compile_workflow(ir_json=ir, registry=registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)

        engine = WorkflowEngine(trace_collector=collector)

        with pytest.raises(ValueError, match="Unresolved"):
            engine.run(workflow, shared)

        # Should have 2 events: producer (success) + consumer (error)
        assert len(collector.events) == 2

        # Consumer's trace event should have partial template_resolutions
        consumer_event = collector.events[1]
        assert consumer_event["node_id"] == "consumer"
        assert consumer_event["status"] == "failed"
        assert "template_resolutions" in consumer_event
        resolutions = consumer_event["template_resolutions"]
        # The 'command' param should be resolved (it was processed before 'cwd' failed)
        assert "command" in resolutions
        assert resolutions["command"]["template"] == "${producer.stdout}"


# --------------------------------------------------------------------------
# LLM trace_hook plumbing (Task 158 Phase A item 3 — regression guards for
# the worker-thread mismatch fix and sub-workflow trace flow).
# --------------------------------------------------------------------------


class TestLLMTraceHookCapture:
    """The trace_hook fires through LLMNode's inner ThreadPoolExecutor.

    Pre-fix bug: the engine's `register_for_llm_call` registered the
    collector against the MAIN thread's id, but `_call_llm` runs in a
    worker thread spawned by `LLMNode.exec`'s inner pool. The lookup at
    `_active_trace_hook` returned None for the worker thread, so the
    adapter's `trace_hook` never fired and `collector.llm_prompts` stayed
    empty. Trace events lost `event["llm_prompt"]` for every literal-prompt
    LLM call. Smoke-verified pre-fix on Gemini-3.

    The new design (`shared["__trace_collector__"]` + LLMNode.prep resolves
    the hook BEFORE pool.submit) survives the worker-thread boundary
    because the hook is a closure passed as an explicit arg, not a
    thread-local lookup.
    """

    def test_llm_prompt_captured_via_trace_hook(self, mock_llm_client):
        # Configure the mock so the trace_hook receives a known prompt
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "ask",
                    "type": "llm",
                    "params": {
                        "prompt": "Say hello to the world.",
                        "system": "Be concise.",
                        "model": "anthropic/claude-sonnet-4-5",
                    },
                },
            ],
            "edges": [],
        }

        _, collector = _run_with_trace(ir)

        # The trace_hook fired and the rendered prompt reached the EVENT (asserted below) — the contract
        # downstream consumers (`pflow report`) read. The internal llm_prompts capture is CONSUMED on
        # record (popped, Task 172 C4 fix) so a later node sharing this id can't inherit it, so the dict
        # is empty again post-run.
        assert collector.llm_prompts == {}

        # And the trace event must surface it (downstream consumers like
        # `pflow report` read this field).
        ask_event = next(e for e in collector.events if e["node_id"] == "ask")
        assert ask_event.get("llm_prompt") == "Say hello to the world."
        assert ask_event.get("llm_system") == "Be concise."
        assert "prompt" not in ask_event.get("node_output", {})
        assert "system" not in ask_event.get("node_output", {})
        assert "prompt" not in ask_event.get("template_resolutions", {})
        assert "system" not in ask_event.get("template_resolutions", {})
        assert "prompt" not in ask_event.get("node_params", {})
        assert ask_event.get("node_params", {}).get("system") == "Be concise."


class TestSubWorkflowTraceCollector:
    """Sub-workflow LLM prompts land in the CHILD collector, not the parent.

    Pre-fix bug (concurrency-safety review Finding 2 / feature-interactions
    C3): the parent's `_thread_local.current_node` stayed set to the
    WorkflowExecutor's id; child LLM calls would have been mis-attributed
    to the parent's WorkflowExecutor event under that stale id. (In
    practice the lookup never fired due to the worker-thread mismatch, so
    nothing was captured at all.)

    The new design installs the child collector into `shared["__trace_collector__"]`
    via the child engine's save/restore — child's LLMNode.prep finds the
    child collector and writes to `child.llm_prompts[child_node_id]`.
    """

    def test_sub_workflow_llm_prompt_in_child_collector(self, tmp_path, mock_llm_client):
        from pathlib import Path

        # Child workflow with one LLM step
        child_md = Path(tmp_path) / "child.pflow.md"
        child_md.write_text(
            "# Child\n\nA child workflow.\n\n"
            "## Steps\n\n"
            "### child-llm\n\nLLM call inside the child.\n\n"
            "- type: llm\n"
            "- model: anthropic/claude-sonnet-4-5\n"
            "- prompt: Hello from the child.\n",
            encoding="utf-8",
        )

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "child-wf",
                    "type": "workflow",
                    "params": {"workflow": str(child_md)},
                },
            ],
            "edges": [],
        }

        _, parent_collector = _run_with_trace(parent_ir)

        # The PARENT collector saw the WorkflowExecutor event but does NOT
        # have the child LLM prompt — that lives in the child collector.
        assert "child-llm" not in parent_collector.llm_prompts

        # The parent's WorkflowExecutor event should have nested
        # sub_workflow_events from the child collector with the LLM event
        # carrying the captured prompt.
        wf_exec_event = next(e for e in parent_collector.events if e["node_id"] == "child-wf")
        sub_events = wf_exec_event.get("sub_workflow_events", [])
        child_llm_event = next((e for e in sub_events if e.get("node_id") == "child-llm"), None)
        assert child_llm_event is not None, f"child-llm event missing from sub_workflow_events: {sub_events}"
        assert child_llm_event.get("llm_prompt") == "Hello from the child."


class TestParallelBatchSubWorkflowTrace:
    """Parallel batch where each item is a sub-workflow containing an LLM.

    The most complex nested case the design has to handle:
    - Each batch worker deepcopies the batch node and gets its own item_shared
    - Each worker's WorkflowExecutor.exec creates its own child_trace
    - Each worker's child engine.run installs the child_trace into the
      child storage via save/restore
    - Each child's LLMNode.prep resolves the hook from the child collector

    Per the plan-review and concurrency-safety reviewers: this combination
    is exactly where the previous thread-local design would have regressed.
    """

    def test_each_batch_item_subworkflow_captures_own_llm_prompt(self, tmp_path, mock_llm_client):
        from pathlib import Path

        # Child workflow with one LLM step that uses the per-item input
        child_md = Path(tmp_path) / "child.pflow.md"
        child_md.write_text(
            "# Child\n\nProcesses one item.\n\n"
            "## Inputs\n\n"
            "### item\n\nThe input item.\n\n"
            "- type: string\n\n"
            "## Steps\n\n"
            "### child-llm\n\nLLM call inside the child.\n\n"
            "- type: llm\n"
            "- model: anthropic/claude-sonnet-4-5\n"
            "- prompt: Process item ${item}.\n",
            encoding="utf-8",
        )

        # Parent workflow with a batched sub-workflow over a list of items
        parent_ir = {
            "ir_version": "0.1.0",
            "inputs": {"items": {"type": "array", "description": "items to fan out over"}},
            "nodes": [
                {
                    "id": "fanout",
                    "type": "workflow",
                    "params": {
                        "workflow": str(child_md),
                        "inputs": {"item": "${item}"},
                    },
                    "batch": {
                        "items": "${items}",
                        "as": "item",
                        "parallel": True,
                    },
                },
            ],
            "edges": [],
        }

        _, parent_collector = _run_with_trace(parent_ir, initial_params={"items": ["A", "B", "C"]})

        # The fanout event should have batch_items, each with its own
        # nested events from a separate child collector.
        fanout_event = next(e for e in parent_collector.events if e["node_id"] == "fanout")
        batch_items = fanout_event.get("batch_items", [])
        assert len(batch_items) == 3, f"expected 3 batch items, got {len(batch_items)}"

        # Each item's nested LLM event must carry its own per-item prompt
        # (rendered with that item's value substituted in). If save/restore
        # leaked between workers, prompts would be cross-contaminated.
        seen_prompts = []
        for item in batch_items:
            sub_events = item.get("events", [])
            child_llm_event = next((e for e in sub_events if e.get("node_id") == "child-llm"), None)
            assert child_llm_event is not None
            seen_prompts.append(child_llm_event.get("llm_prompt"))

        # Each worker resolved its own item; prompts must all differ
        assert sorted(seen_prompts) == ["Process item A.", "Process item B.", "Process item C."]

    def test_dynamic_subworkflow_batch_records_canonical_workflow_path(self, tmp_path):
        """Dynamic workflow batches keep raw template resolution and canonical child path.

        ``template_resolutions["workflow"]["resolved"]`` is the generic
        template result, so it may be relative. The batch item event needs the
        canonical path from ``resolve_sub_workflow`` for analyzers to match the
        child trace back to the statically analyzed child workflow row.
        """
        from pathlib import Path

        child_md = Path(tmp_path) / "child.pflow.md"
        child_md.write_text(
            "# Child\n\nProcesses one item.\n\n"
            "## Inputs\n\n"
            "### value\n\nThe input value.\n\n"
            "- type: string\n\n"
            "## Steps\n\n"
            "### child-shell\n\nShell call inside the child.\n\n"
            "- type: shell\n"
            "- command: printf '%s' '${value}'\n",
            encoding="utf-8",
        )
        parent_path = Path(tmp_path) / "parent.pflow.md"
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "fanout",
                    "type": "workflow",
                    "params": {
                        "workflow": "${item.workflow}",
                        "inputs": {"value": "${item.value}"},
                    },
                    "batch": {
                        "items": [
                            {"workflow": "./child.pflow.md", "value": "A"},
                            {"workflow": "./child.pflow.md", "value": "B"},
                        ],
                        "as": "item",
                    },
                },
            ],
            "edges": [],
        }

        _, parent_collector = _run_with_trace(
            parent_ir,
            extra_shared={"_pflow_workflow_file": str(parent_path)},
        )

        fanout_event = next(e for e in parent_collector.events if e["node_id"] == "fanout")
        batch_items = fanout_event.get("batch_items", [])
        assert len(batch_items) == 2
        for batch_item in batch_items:
            assert batch_item["template_resolutions"]["workflow"]["resolved"] == "./child.pflow.md"
            assert batch_item["workflow_path"] == str(child_md.resolve())
            assert any(event.get("node_id") == "child-shell" for event in batch_item.get("events", []))

    def test_llm_failure_in_one_item_does_not_corrupt_siblings(self, tmp_path, monkeypatch):
        """The failure-path complement to the success test above.

        The §31 worker-thread bug had the same shape on both success and
        failure: workers run inside ``ThreadPoolExecutor`` and the trace
        seam must work for both. The success path is pinned above; this
        pins the failure path.

        A regression in the per-worker save/restore could:
          (a) silently drop the failure (the typed exception escapes
              without ``__failures__`` recording it),
          (b) cross-contaminate siblings (the failing worker's trace
              state leaks into a sibling's collector), or
          (c) bury the LLM error under a generic engine error, losing
              the structured ``_diagnostic_context`` (``category``,
              ``error_class``, ``model``) the JSON output contract needs.

        Configuration: parallel batch + sub-workflow + LLM. One item
        ("FAIL") raises ``MissingApiKeyError``; the other two succeed.
        ``error_handling: continue`` lets the batch complete so we can
        inspect every worker's outcome.
        """
        from pathlib import Path

        from pflow.core.exceptions import MissingApiKeyError
        from pflow.core.llm_client import AdapterResponse

        def fake_complete(*, model, prompt, **kwargs):
            # Simulate a typed seam exception for the "FAIL" item only.
            # Sibling workers must still get a successful AdapterResponse.
            if "FAIL" in prompt:
                raise MissingApiKeyError(
                    f"API key required for model {model!r}",
                    model=model,
                    kind="missing_key",
                    provider_message="Quota exceeded for free tier",
                )
            return AdapterResponse(
                text="ok",
                usage={
                    "model": model,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "total_tokens": 2,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "thinking_tokens": 0,
                    "thinking_budget": 0,
                    "cost_usd": None,
                },
                model=model,
                has_schema=False,
                warnings=[],
            )

        # Override the autouse mock_llm_client at the LLMNode binding so the
        # real LLMNode failure path runs end-to-end (typed exception ->
        # _propagate_error_to_shared -> __failures__ -> trace).
        monkeypatch.setattr("pflow.nodes.llm.llm.complete", fake_complete)

        child_md = Path(tmp_path) / "child.pflow.md"
        child_md.write_text(
            "# Child\n\nProcesses one item.\n\n"
            "## Inputs\n\n"
            "### item\n\nThe input item.\n\n"
            "- type: string\n\n"
            "## Steps\n\n"
            "### child-llm\n\nLLM call inside the child.\n\n"
            "- type: llm\n"
            "- model: anthropic/claude-sonnet-4-5\n"
            "- prompt: Process item ${item}.\n",
            encoding="utf-8",
        )

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "fanout",
                    "type": "workflow",
                    "params": {
                        "workflow": str(child_md),
                        "inputs": {"item": "${item}"},
                    },
                    "batch": {
                        "items": ["A", "FAIL", "B"],
                        "as": "item",
                        "parallel": True,
                        "error_handling": "continue",
                    },
                },
            ],
            "edges": [],
        }

        shared, parent_collector = _run_with_trace(parent_ir)

        # Batch summary reflects the per-item outcomes — failure didn't
        # crash the batch, didn't poison sibling results.
        batch_output = shared["fanout"]
        assert batch_output["count"] == 3
        assert batch_output["success_count"] == 2
        assert batch_output["error_count"] == 1
        assert batch_output["errors"][0]["item"] == "FAIL"

        # Each child's trace event survives independently. The failing
        # item's child-llm event must carry the typed error context;
        # successful items must carry their resolved prompts (no
        # cross-contamination from the failing worker).
        fanout_event = next(e for e in parent_collector.events if e["node_id"] == "fanout")
        batch_items = fanout_event.get("batch_items", [])
        assert len(batch_items) == 3

        outcomes_by_item = {}
        for batch_item in batch_items:
            sub_events = batch_item.get("events", [])
            llm_event = next((e for e in sub_events if e.get("node_id") == "child-llm"), None)
            outcomes_by_item[batch_item.get("item")] = (batch_item, llm_event)

        # Successful siblings: each item has its own resolved prompt
        # captured via the trace seam (the §31 fix). The two surviving
        # workers must have run their full success path through the
        # save/restore boundary.
        a_batch_item, a_llm = outcomes_by_item["A"]
        b_batch_item, b_llm = outcomes_by_item["B"]
        assert a_batch_item["status"] == "success"
        assert b_batch_item["status"] == "success"
        assert a_llm is not None and a_llm.get("llm_prompt") == "Process item A."
        assert b_llm is not None and b_llm.get("llm_prompt") == "Process item B."

        # Failing item: success=False at the batch-item boundary; child's
        # internal child-llm trace event records the failure.
        fail_batch_item, fail_llm = outcomes_by_item["FAIL"]
        assert fail_batch_item["status"] == "failed"
        assert fail_llm is not None
        assert fail_llm.get("status") == "failed"

        # The structured ``_diagnostic_context`` (category="llm_failure",
        # error_class, model) is what JSON output consumers filter on.
        # It travels from the typed exception through
        # _propagate_error_to_shared into the child's namespaced
        # _diagnostic_context, which the runtime archives. Inspect both
        # the trace event's node_output and the parent-side errors list
        # — either path carrying the structured fields satisfies the
        # contract.
        node_output = fail_llm.get("node_output", {})
        ctx = node_output.get("_diagnostic_context", {}) if isinstance(node_output, dict) else {}
        item_errors = batch_output.get("errors", [])
        # Locate the failing item's recorded error.
        fail_error = next((e for e in item_errors if e.get("item") == "FAIL"), {})
        # The category lives on either the per-item trace's
        # _diagnostic_context (the LLMNode-side write) OR on the
        # batch-item's recorded error (the parent-side surface). At
        # least one path must carry the typed discriminator.
        carries_llm_category = (
            ctx.get("category") == "llm_failure"
            or ctx.get("error_class") == "MissingApiKeyError"
            or fail_error.get("error_class") == "MissingApiKeyError"
            or "MissingApiKeyError" in str(fail_error.get("error", ""))
        )
        assert carries_llm_category, (
            "Typed LLM failure context must propagate through the worker "
            "boundary into the user-facing surface — neither the trace's "
            "_diagnostic_context nor the batch error surfaces "
            f"MissingApiKeyError. ctx={ctx}; fail_error={fail_error}"
        )


class TestParallelBatchOfLLMs:
    """Parallel batch where each item is a direct LLM call (no sub-workflow wrapper).

    Pre-fix: WorkflowTraceCollector.llm_prompts is keyed by node_id only, so all
    parallel workers writing to the same batch wrapper id overwrote each other.
    Per-item llm_prompt was either missing or non-deterministic (last-write-wins).

    Fix (LLMNode.post writes shared["prompt"]): each item's NamespacedSharedStore
    routes the rendered prompt to ``shared[node_id]["prompt"]``. The batch
    executor's _capture_item_trace now promotes either structured
    user_message_blocks or that flat prompt into the canonical ``llm_prompt``.
    """

    def test_each_batch_item_llm_captures_own_rendered_prompt(self, mock_llm_client):
        ir = {
            "ir_version": "0.1.0",
            "inputs": {"items": {"type": "array", "description": "items to fan out over"}},
            "nodes": [
                {
                    "id": "scorer",
                    "type": "llm",
                    "params": {
                        "model": "anthropic/claude-sonnet-4-5",
                        "prompt": "Score this: ${item}",
                    },
                    "batch": {
                        "items": "${items}",
                        "as": "item",
                        "parallel": True,
                    },
                },
            ],
            "edges": [],
        }

        _, collector = _run_with_trace(ir, initial_params={"items": ["red", "green", "blue"]})

        scorer_event = next(e for e in collector.events if e["node_id"] == "scorer")
        batch_items = scorer_event.get("batch_items", [])
        assert len(batch_items) == 3, f"expected 3 batch items, got {len(batch_items)}"

        seen_prompts = sorted(item.get("llm_prompt") for item in batch_items)
        assert seen_prompts == ["Score this: blue", "Score this: green", "Score this: red"]
        for item in batch_items:
            assert "prompt" not in item.get("node_output", {})
            assert "system" not in item.get("node_output", {})
            assert "prompt" not in item.get("template_resolutions", {})
            assert "system" not in item.get("template_resolutions", {})

        # The aggregate batch wrapper stores only one representative prompt
        # because WorkflowTraceCollector.llm_prompts is keyed by node_id. In
        # parallel mode this is last-writer-wins by design; the per-item
        # prompts above are the authoritative data.
        assert scorer_event.get("llm_prompt") in seen_prompts

    def test_prewarm_batch_items_capture_user_message_blocks_for_interning(self, mock_llm_client):
        static_prefix = "stable rubric " * 1200
        prompt_template = f"{static_prefix}Score this: ${{item}}"
        expected_static_block = f"{static_prefix}Score this: "
        ir = {
            "ir_version": "0.1.0",
            "inputs": {"items": {"type": "array", "description": "items to fan out over"}},
            "nodes": [
                {
                    "id": "scorer",
                    "type": "llm",
                    "params": {
                        "model": "anthropic/claude-sonnet-4-5",
                        "prompt": prompt_template,
                    },
                    "batch": {
                        "items": "${items}",
                        "as": "item",
                        "parallel": True,
                    },
                    "prewarm": True,
                },
            ],
            "edges": [],
        }

        mock_llm_client.set_response("*", None, "ok")
        shared, collector = _run_with_trace(ir, initial_params={"items": ["red", "blue"]})

        scorer_event = next(e for e in collector.events if e["node_id"] == "scorer")
        real_items = [
            item for item in scorer_event.get("batch_items", []) if not item.get("llm_call", {}).get("is_warmup")
        ]
        assert len(real_items) == 2

        prompts = [item.get("llm_prompt") for item in real_items]
        assert all(isinstance(prompt, list) and len(prompt) == 2 for prompt in prompts)
        assert {prompt[0]["text"] for prompt in prompts if isinstance(prompt, list)} == {expected_static_block}
        assert {prompt[1]["text"] for prompt in prompts if isinstance(prompt, list)} == {"red", "blue"}
        for item in real_items:
            assert "user_message_blocks" not in item.get("node_output", {})
            assert "prompt" not in item.get("node_output", {})

        # B3 regression: user_message_blocks is a trace-capture-only seam and
        # must NOT leak into the user-facing batch output (shared[node_id]
        # ["results"]) — it would re-inject the large cache-rendered blocks into
        # downstream/displayed output that the trace shrink is meant to avoid.
        batch_results = shared["scorer"]["results"]
        assert len(batch_results) == 2
        for result in batch_results:
            assert "user_message_blocks" not in result

        interned = intern_blobs({"format_version": "2.5.0", "nodes": [scorer_event]})
        interned_real_items = [
            item
            for item in interned["nodes"][0].get("batch_items", [])
            if not item.get("llm_call", {}).get("is_warmup")
        ]
        static_refs = [item["llm_prompt"][0]["text"] for item in interned_real_items]
        assert len(static_refs) == 2
        assert static_refs[0] == static_refs[1]
        assert isinstance(static_refs[0], dict)
        digest = static_refs[0][BLOB_SENTINEL]
        assert interned["blobs"][digest] == expected_static_block
        assert {item["llm_prompt"][1]["text"] for item in interned_real_items} == {"red", "blue"}


def test_llm_batch_item_trace_strips_without_mutating_last_resolutions() -> None:
    """Batch LLM canonicalization must copy before stripping aliased resolutions."""
    parent_shared: dict[str, Any] = {"_batch_trace": {"scorer": []}}
    item_shared = {
        "scorer": {
            "prompt": "Score this: red",
            "system": "System",
            "response": "ok",
            "llm_usage": {"model": "m", "total_tokens": 1},
        }
    }
    last_resolutions = {
        "prompt": {"template": "Score this: ${item}", "resolved": "Score this: red"},
        "system": {"template": "System", "resolved": "System"},
        "workflow": {"template": "./child.pflow.md", "resolved": "./child.pflow.md"},
    }

    _capture_item_trace(
        parent_shared,
        "scorer",
        "LLMNode",
        item_shared,
        0,
        "red",
        12.0,
        None,
        last_resolutions,
    )

    item_event = parent_shared["_batch_trace"]["scorer"][0]
    assert item_event["llm_prompt"] == "Score this: red"
    assert item_event["llm_system"] == "System"
    assert item_event["template_resolutions"] == {
        "workflow": {"template": "./child.pflow.md", "resolved": "./child.pflow.md"}
    }
    assert "prompt" not in item_event["node_output"]
    assert "system" not in item_event["node_output"]
    assert "prompt" in last_resolutions
    assert "system" in last_resolutions
    assert "workflow" in last_resolutions


def test_llm_batch_item_trace_prefers_user_message_blocks_and_drops_stored_copy() -> None:
    """Block-shaped prewarm prompts must be the single canonical prompt copy."""
    blocks = [
        {"type": "text", "text": "Shared prefix", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "red"},
    ]
    parent_shared: dict[str, Any] = {"_batch_trace": {"scorer": []}}
    item_shared = {
        "scorer": {
            "prompt": "Shared prefixred",
            "user_message_blocks": blocks,
            "response": "ok",
        }
    }

    _capture_item_trace(
        parent_shared,
        "scorer",
        "LLMNode",
        item_shared,
        0,
        "red",
        12.0,
        None,
        {},
    )

    item_event = parent_shared["_batch_trace"]["scorer"][0]
    assert item_event["llm_prompt"] is blocks
    assert "user_message_blocks" not in item_event["node_output"]
    assert "prompt" not in item_event["node_output"]
    # B3: the trace-only field is also dropped from the LIVE per-item output
    # (item_shared[node_id]) so it can't leak into the aggregated batch results.
    assert "user_message_blocks" not in item_shared["scorer"]


class TestCachedSystemEndToEnd:
    """End-to-end: ``## Cache`` block → trace event → generated report.

    Exercises the full pipeline that gives an agent visibility into the
    cached prefix the LLM saw. Without this, `pflow ... --report` shows
    only the user prompt, leaving the cached system content invisible
    except via raw JSON inspection.
    """

    def test_cached_system_reaches_report_for_llm_node_with_cache_block(
        self, tmp_path: "Any", monkeypatch: "Any"
    ) -> None:
        """Run a workflow with a ## Cache block; verify the trace records
        ``llm_system`` AND the generated report has a ``## Cached System``
        section with the cache_control marker visible.
        """
        import json

        # Bypass the runtime pre-dispatch strip so the tiny fixture content
        # ("Reference doc body") doesn't get its marker stripped. The strip
        # is exercised in tests/test_nodes/test_llm/test_prompt_cache_below_min_runtime.py.
        monkeypatch.setattr("pflow.nodes.llm.llm._count_text_tokens", lambda text, model: 10_000)

        ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "context": {
                    "type": "string",
                    "required": False,
                    "default": "Reference doc body",
                },
            },
            "cache": {
                "items": [
                    {"name": "context", "var": "context", "prose_before": ""},
                ],
            },
            "nodes": [
                {
                    "id": "answer",
                    "type": "llm",
                    "params": {
                        "model": "anthropic/claude-sonnet-4-5",
                        "prompt": "Question: what is the answer?",
                    },
                    "prompt_cache": ["context"],
                },
            ],
            "edges": [],
        }

        _, collector = _run_with_trace(ir)

        event = next(e for e in collector.events if e["node_id"] == "answer")
        assert "llm_system" in event, "llm_system missing from trace event — cache prefix not surfaced"
        # Cache-rendered system is a list[dict] with cache_control on the
        # last block.
        llm_system = event["llm_system"]
        assert isinstance(llm_system, list)
        assert any("cache_control" in block for block in llm_system if isinstance(block, dict))

        # Build a complete trace dict + persist + render
        from pflow.runtime.workflow_trace import TRACE_FORMAT_VERSION

        trace_data = {
            "format_version": TRACE_FORMAT_VERSION,
            "execution_id": collector.execution_id,
            "workflow_name": collector.workflow_name,
            "workflow_path": None,
            "start_time": collector.start_time.isoformat(),
            "end_time": collector.start_time.isoformat(),
            "duration_ms": 100.0,
            "final_status": "success",
            "nodes_executed": len(collector.events),
            "nodes_failed": 0,
            "failed_node_ids": [],
            "nodes": collector.events,
        }
        trace_path = tmp_path / "trace.json"
        trace_path.write_text(json.dumps(trace_data, default=str))

        from pflow.core.trace_report import generate_report

        report_dir = generate_report(str(trace_path), str(tmp_path / "report"))
        assert report_dir is not None
        node_md = (report_dir / "01-answer.md").read_text()
        assert "## Cached System" in node_md
        assert "```json" in node_md
        assert "cache_control" in node_md
