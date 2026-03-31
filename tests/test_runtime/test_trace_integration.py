"""Integration tests for trace event capture through the execution engine.

These tests verify the integration seams between the engine, trace collectors,
and batch processing — areas where silent data loss occurs when template
resolution, namespacing, or trace recording breaks.

Migrated from wrapper-based tests to compile_workflow + WorkflowEngine
tests after the wrappers were replaced by the engine (Task 135/138).
"""

from typing import Any

import pytest

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
    collector.enable_llm_interception = False

    registry = Registry()
    workflow = compile_workflow(ir_json=ir, registry=registry, initial_params=initial_params)

    shared: dict[str, Any] = {"_trace_collector": collector}
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
                    "type": "echo",
                    "params": {"message": "Hello ${name}"},
                },
            ],
            "edges": [],
            "inputs": {"name": {"type": "str", "description": "Name input"}},
        }

        shared, collector = _run_with_trace(ir, initial_params={"name": "World"})

        assert len(collector.events) == 1
        event = collector.events[0]

        assert event["success"] is True
        assert event["node_type"] == "EchoNode"

        # Template resolutions should be captured
        assert "template_resolutions" in event, (
            "template_resolutions missing from trace event — engine may not be passing last_resolutions to record_trace"
        )
        resolutions = event["template_resolutions"]
        assert "message" in resolutions
        assert resolutions["message"]["template"] == "Hello ${name}"
        assert resolutions["message"]["resolved"] == "Hello World"

        # Node output should be namespaced
        assert "node_output" in event
        assert event["node_output"]["echo"] == "Hello World"

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
                    "type": "echo",
                    "params": {"message": "${item}"},
                    "batch": {"items": "${data}", "as": "item"},
                },
            ],
            "edges": [],
        }

        shared, collector = _run_with_trace(ir, extra_shared={"data": ["a", "b", "c"]})

        assert len(collector.events) == 1
        event = collector.events[0]

        assert event["success"] is True
        assert event["node_type"] == "EchoNode"

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
            assert item_trace["success"] is True
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
                    "type": "echo",
                    "params": {"message": "${item}"},
                    "batch": {"items": "${data}", "as": "item"},
                },
            ],
            "edges": [],
        }

        shared, collector = _run_with_trace(ir, extra_shared={"data": ["alpha", "beta"]})

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

        # Summary should reference the batch
        summary_md = (report_dir / "summary.md").read_text()
        assert "processor" in summary_md


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
                    "type": "echo",
                    "params": {"message": "${item}"},
                    "batch": {"items": "${data}", "as": "item", "parallel": True},
                },
            ],
            "edges": [],
        }

        shared, collector = _run_with_trace(ir, extra_shared={"data": ["alice", "bob"]})

        assert len(collector.events) == 1
        event = collector.events[0]
        assert "batch_items" in event
        batch_items = event["batch_items"]
        assert len(batch_items) == 2

        # Parallel batch items may complete in any order — match by content
        resolved_messages = set()
        for item in batch_items:
            assert item["success"] is True
            # Template resolutions captured from per-item resolution
            resolutions = item.get("template_resolutions", {})
            assert "message" in resolutions, (
                "template_resolutions missing 'message' — "
                "per-item template resolution may not be captured in batch trace"
            )
            resolved_messages.add(resolutions["message"]["resolved"])
        assert resolved_messages == {"alice", "bob"}


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

        shared, collector = _run_with_trace(ir, extra_shared={"data": ["good", "bad", "good"]})

        assert len(collector.events) == 1
        event = collector.events[0]
        batch_items = event["batch_items"]
        assert len(batch_items) == 3

        # Item 0 and 2: success
        assert batch_items[0]["success"] is True
        assert batch_items[0]["item"] == "good"
        assert batch_items[2]["success"] is True

        # Item 1: failure
        assert batch_items[1]["success"] is False
        assert batch_items[1]["item"] == "bad"


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
        collector.enable_llm_interception = False

        registry = Registry()
        workflow = compile_workflow(ir_json=parent_ir, registry=registry)

        shared: dict[str, Any] = {"_trace_collector": collector}
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
                    "type": "echo",
                    "params": {"message": "Summarize ${fetch.result.messages}"},
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
        up to the error point are included via _partial_resolutions on the ValueError.
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
        collector.enable_llm_interception = False

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
        assert event["success"] is False
        assert "error" in event
        assert "does not exist" in event["error"]
