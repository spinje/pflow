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

        shared, collector = _run_with_trace(ir, initial_params={"name": "World"})

        assert len(collector.events) == 1
        event = collector.events[0]

        assert event["success"] is True
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

        shared, collector = _run_with_trace(ir, extra_shared={"data": ["a", "b", "c"]})

        assert len(collector.events) == 1
        event = collector.events[0]

        assert event["success"] is True
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
                    "type": "shell",
                    "params": {"command": "printf '%s' '${item}'"},
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
                    "type": "shell",
                    "params": {"command": "printf '%s' '${item}'"},
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
        resolved_commands = set()
        for item in batch_items:
            assert item["success"] is True
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
        assert event["success"] is False
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
        assert consumer_event["success"] is False
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
                        "model": "anthropic/claude-sonnet-4-5",
                    },
                },
            ],
            "edges": [],
        }

        _, collector = _run_with_trace(ir)

        # The trace_hook must have fired AND written the rendered prompt
        # under this node's id. Pre-fix this dict was always empty.
        assert collector.llm_prompts == {"ask": "Say hello to the world."}

        # And the trace event must surface it (downstream consumers like
        # `pflow report` read this field).
        ask_event = next(e for e in collector.events if e["node_id"] == "ask")
        assert ask_event.get("llm_prompt") == "Say hello to the world."


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

    def test_storage_mode_shared_does_not_pollute_parent_collector(self, tmp_path, mock_llm_client):
        """storage_mode=shared sub-workflow must not leave child's collector
        installed in the parent's shared store after it returns.

        With `child_storage IS parent_shared`, the child engine.run swaps
        in child_trace via save/restore. After the child completes, the
        parent's collector must be reinstated for any subsequent parent-
        level reads. Identity check (``is``) verifies it's the SAME object,
        not just an equal one.
        """
        from pathlib import Path

        from pflow.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        child_md = Path(tmp_path) / "child.pflow.md"
        child_md.write_text(
            "# Child\n\nA child workflow.\n\n"
            "## Steps\n\n"
            "### echo\n\nEcho a value.\n\n"
            "- type: shell\n"
            "- command: echo shared_works\n",
            encoding="utf-8",
        )

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "child-wf",
                    "type": "workflow",
                    "params": {"workflow": str(child_md), "storage_mode": "shared"},
                },
            ],
            "edges": [],
        }

        parent_collector = WorkflowTraceCollector("parent")
        registry = Registry()
        workflow = compile_workflow(ir_json=parent_ir, registry=registry)
        shared: dict[str, Any] = {"__trace_collector__": parent_collector}
        shared.update(workflow.resolved_defaults)

        engine = WorkflowEngine(trace_collector=parent_collector)
        engine.run(workflow, shared)

        # After the run, parent's collector must be back in shared — the
        # child engine's save/restore must have reinstated it. Identity check
        # (`is`) catches any case where save/restore returned an equal-but-
        # different object (e.g. a copy).
        assert shared["__trace_collector__"] is parent_collector


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


class TestParallelBatchOfLLMs:
    """Parallel batch where each item is a direct LLM call (no sub-workflow wrapper).

    Pre-fix: WorkflowTraceCollector.llm_prompts is keyed by node_id only, so all
    parallel workers writing to the same batch wrapper id overwrote each other.
    Per-item llm_prompt was either missing or non-deterministic (last-write-wins).

    Fix (LLMNode.post writes shared["prompt"]): each item's NamespacedSharedStore
    routes the rendered prompt to ``shared[node_id]["prompt"]``, which the batch
    executor's _capture_item_trace mapping ``("prompt", "llm_prompt")`` already
    expects. Each batch_items[i] now carries its own resolved prompt.
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

        # The aggregate batch wrapper stores only one representative prompt
        # because WorkflowTraceCollector.llm_prompts is keyed by node_id. In
        # parallel mode this is last-writer-wins by design; the per-item
        # prompts above are the authoritative data.
        assert scorer_event.get("llm_prompt") in seen_prompts
