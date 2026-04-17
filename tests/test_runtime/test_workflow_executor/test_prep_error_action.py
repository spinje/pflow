"""Regression guard: prep-time failures dispatch through error_action (GH #284).

Before this fix, raises inside ``WorkflowExecutor.prep()`` bypassed the
node's ``error_action`` dispatch entirely — the engine's except handler
caught them, archived as ``exception`` category, and re-raised. Users
setting ``error_action: continue`` or other non-error action strings
reasonably expected input-shape errors (the most common failure mode for
sub-workflow calls in heterogeneous batches) to route through their chosen
action. They didn't.

These tests run the full engine pipeline and confirm that prep-time
failures now flow through ``error_action`` — matching the behavior that
exec-time failures already had.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pflow.core.node import BaseNode
from pflow.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine
from pflow.runtime.node_state import get_node_failure
from pflow.runtime.workflow_executor import WorkflowExecutor
from tests.shared.markdown_utils import write_workflow_file


def _write_child(tmp_path: Path, ir: dict, name: str = "child") -> Path:
    path = tmp_path / f"{name}.pflow.md"
    write_workflow_file(ir, path)
    return path


@pytest.fixture
def mock_registry(tmp_path):
    """Registry that knows about the workflow executor and a trivial test node."""
    registry = Registry(tmp_path / "test_registry.json")
    registry.save({
        "tests.shared.mock_nodes": {
            "module": "tests.shared.mock_nodes",
            "class_name": "ExampleNode",
            "docstring": "test",
            "file_path": "/mock/path/test_node.py",
            "interface": {
                "inputs": [],
                "outputs": [{"key": "test_output", "type": "string"}],
                "parameters": [],
            },
        },
        "pflow.runtime.workflow_executor": {
            "module": "pflow.runtime.workflow_executor",
            "class_name": "WorkflowExecutor",
            "docstring": "sub-workflow executor",
            "file_path": "/mock/path/workflow_executor.py",
            "interface": {
                "inputs": [],
                "outputs": [],
                "parameters": [
                    {"key": "workflow", "type": "string", "required": False},
                    {"key": "inputs", "type": "dict", "required": False},
                    {"key": "storage_mode", "type": "string", "required": False},
                    {"key": "max_depth", "type": "integer", "required": False},
                    {"key": "error_action", "type": "string", "required": False},
                ],
            },
        },
    })
    return registry


def _setup_mock_imports():
    """Patch importlib so compile_workflow can resolve 'tests.shared.mock_nodes'."""

    class MockExampleNode(BaseNode):
        def prep(self, shared):
            return shared.get("test_input", "no input")

        def exec(self, prep_res):
            return f"Processed: {prep_res}"

        def post(self, shared, prep_res, exec_res):
            shared["test_output"] = exec_res
            return "default"

    mock_module = Mock()
    mock_module.ExampleNode = MockExampleNode
    mock_module.WorkflowExecutor = WorkflowExecutor

    def side_effect(module_path):
        if module_path == "pflow.runtime.workflow_executor":
            import pflow.runtime.workflow_executor

            return pflow.runtime.workflow_executor
        return mock_module

    return patch("importlib.import_module", side_effect=side_effect)


def _parent_ir(child_path: Path, error_action: str, inputs: dict) -> dict:
    """Build a parent IR with a single sub-workflow node."""
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "sub",
                "type": "pflow.runtime.workflow_executor",
                "params": {
                    "workflow": str(child_path),
                    "error_action": error_action,
                    "inputs": inputs,
                },
            }
        ],
        "edges": [],
    }


class TestPrepFailureRoutesThroughErrorAction:
    """Regression guards for GH #284."""

    def test_missing_required_input_dispatches_error_action(self, mock_registry, tmp_path):
        """Prep raises on missing-required → post() dispatches error_action."""
        child = _write_child(
            tmp_path,
            {
                "ir_version": "0.1.0",
                "inputs": {"required_field": {"type": "string", "required": True}},
                "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo hi"}}],
                "edges": [],
            },
            "missing_required_child",
        )
        # Use __validator_bypass IR shape: compile directly, skip parse-time validator
        # by running the IR through compile_workflow which doesn't invoke WorkflowValidator
        # (the validator runs upstream in the CLI). This simulates the heterogeneous-batch
        # scenario where ${item.inputs} is opaque at parse time.
        parent_ir = _parent_ir(child, error_action="continue", inputs={"WRONG_KEY": "oops"})

        with _setup_mock_imports():
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

        # Action string comes from error_action — routes like any other action.
        assert result == "continue"
        # Failure signal is still preserved via shared[node_id]["error"] (the
        # post() write goes through NamespacedSharedStore). error_action
        # renames the routing label; it does not suppress the failure signal.
        sub_error = shared.get("sub", {}).get("error", "")
        assert "missing required inputs" in sub_error
        # Invariant: error_action != "error" means the node is routable,
        # not hard-failed. Step 17.5 archives only when action starts with
        # "error". If anyone adds mark_node_failed to the non-error path,
        # this guard fires.
        assert get_node_failure(shared, "sub") is None

    def test_non_dict_inputs_shape_dispatches_error_action(self, mock_registry, tmp_path):
        """Prep raises on non-dict inputs (template resolved to wrong shape) → error_action."""
        child = _write_child(
            tmp_path,
            {
                "ir_version": "0.1.0",
                "inputs": {"x": {"type": "string"}},
                "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo hi"}}],
                "edges": [],
            },
            "shape_child",
        )
        # Inputs is a list, not a dict. prep's _extract_child_inputs raises.
        parent_ir = _parent_ir(child, error_action="fallback", inputs={})
        # Override inputs to a list after-the-fact (simulates a template resolving wrong)
        parent_ir["nodes"][0]["params"]["inputs"] = ["not", "a", "dict"]

        with _setup_mock_imports():
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

        assert result == "fallback"
        assert "resolved to list" in shared.get("sub", {}).get("error", "")
        # Non-error action → not archived in __failures__ (see invariant
        # note in test_missing_required_input_dispatches_error_action).
        assert get_node_failure(shared, "sub") is None

    def test_undeclared_extras_dispatches_error_action(self, mock_registry, tmp_path):
        """Prep raises on undeclared extras → error_action dispatched."""
        child = _write_child(
            tmp_path,
            {
                "ir_version": "0.1.0",
                "inputs": {"declared": {"type": "string"}},
                "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo hi"}}],
                "edges": [],
            },
            "extras_child",
        )
        parent_ir = _parent_ir(
            child,
            error_action="skip",
            inputs={"declared": "ok", "extra_key": "nope"},
        )

        with _setup_mock_imports():
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

        assert result == "skip"
        assert "undeclared input(s)" in shared.get("sub", {}).get("error", "")
        assert get_node_failure(shared, "sub") is None

    def test_circular_reference_dispatches_error_action(self, mock_registry, tmp_path):
        """Prep raises ValueError on circular workflow reference → error_action.

        Note: prep-time failures whose error text matches the engine's
        api_warning_detector patterns (e.g. "not found", "403", "401") get
        hijacked back to action="error" regardless of error_action. That's
        pre-existing engine behavior (GH #301), pinned separately by
        ``TestApiWarningDetectorHijackIsPinned``. "Circular workflow
        reference" doesn't match any detector pattern, so error_action
        routes cleanly here.
        """
        child = _write_child(
            tmp_path,
            {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo hi"}}],
                "edges": [],
            },
            "cycle_child",
        )
        parent_ir = _parent_ir(child, error_action="continue", inputs={})

        with _setup_mock_imports():
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["__registry__"] = mock_registry
            # Seed the execution stack so the child's path is already present —
            # simulates a deeper cycle detection at runtime.
            shared["_pflow_stack"] = [str(child)]
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

        assert result == "continue"
        assert "Circular workflow reference" in shared.get("sub", {}).get("error", "")
        assert get_node_failure(shared, "sub") is None

    def test_default_error_action_still_fails_hard(self, mock_registry, tmp_path):
        """Regression guard: with default error_action="error", prep failures still
        archive as failures and return "error" action — same observable outcome as
        before the fix, just via a different code path.
        """
        child = _write_child(
            tmp_path,
            {
                "ir_version": "0.1.0",
                "inputs": {"required_field": {"type": "string", "required": True}},
                "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo hi"}}],
                "edges": [],
            },
            "default_error_child",
        )
        parent_ir = _parent_ir(child, error_action="error", inputs={"WRONG": "oops"})

        with _setup_mock_imports():
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

        assert result == "error"
        failure = get_node_failure(shared, "sub")
        assert failure is not None
        assert "missing required inputs" in str(failure.get("error", ""))

    def test_batch_continue_past_prep_error(self, tmp_path):
        """The original GH #284 scenario: batch with one bad item + one good item,
        error_handling: continue on the batch. Before the fix the batch aborted on
        item [0]'s prep ValueError; after the fix the batch completes with a
        partial result and the failed item in the errors list.
        """
        good_child = _write_child(
            tmp_path,
            {
                "ir_version": "0.1.0",
                "inputs": {"lyrics": {"type": "string", "required": True}},
                "nodes": [{"id": "echo", "type": "shell", "params": {"command": "echo ${lyrics}"}}],
                "edges": [],
                "outputs": {"out": {"source": "${echo.stdout}"}},
            },
            "good_child",
        )
        bad_child = good_child  # Same child — difference is the inputs per item
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "reviews",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow": "${item.workflow}",
                        "inputs": "${item.inputs}",
                        "error_action": "continue",
                    },
                    "batch": {
                        "items": [
                            {"workflow": str(bad_child), "inputs": {"WRONG_KEY": "oops"}},
                            {"workflow": str(good_child), "inputs": {"lyrics": "fine"}},
                        ],
                        "error_handling": "continue",
                        "parallel": False,
                    },
                }
            ],
            "edges": [],
        }

        # Use the real (isolated) Registry so shell node in the child is resolvable.
        registry = Registry()
        workflow = compile_workflow(parent_ir, registry=registry)
        shared = dict(workflow.resolved_defaults)
        shared["__registry__"] = registry
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # The batch produced one successful item and one failure.
        batch_result = shared.get("reviews", {})
        assert batch_result.get("success_count") == 1, (
            f"Expected 1 successful item, got {batch_result.get('success_count')}"
        )
        assert batch_result.get("error_count") == 1, f"Expected 1 errored item, got {batch_result.get('error_count')}"
        # Good item's output survived — assert index correctness too so
        # an aggregator bug that shuffled items would be caught.
        results = batch_result.get("results", [])
        assert len(results) == 1
        assert results[0].get("out") == "fine"
        assert results[0]["original_index"] == 1  # good item was index 1
        assert results[0]["item"] == {"workflow": str(good_child), "inputs": {"lyrics": "fine"}}
        # Failed item's diagnostic is preserved + indexed correctly.
        errors = batch_result.get("errors", [])
        assert len(errors) == 1
        assert errors[0]["index"] == 0  # bad item was index 0
        assert errors[0]["item"] == {"workflow": str(bad_child), "inputs": {"WRONG_KEY": "oops"}}
        assert "missing required inputs" in errors[0].get("error", "")

    def test_parallel_batch_continue_past_prep_error(self, tmp_path):
        """Regression guard for the pre-warm compile cache x prep-error interaction.

        Before fixing `_pre_warm_compile_cache`, this test crashed with
        `KeyError: 'child_ir'` — pre-warm ran prep() on item[0] (which
        returned a _prep_error marker), the cache-populated check passed
        (load succeeded), then pre-warm tried to read child_ir from the
        marker dict. The parallel batch aborted entirely instead of
        routing item[0] through error_action and running item[1].
        """
        child = _write_child(
            tmp_path,
            {
                "ir_version": "0.1.0",
                "inputs": {"lyrics": {"type": "string", "required": True}},
                "nodes": [{"id": "echo", "type": "shell", "params": {"command": "echo ${lyrics}"}}],
                "edges": [],
                "outputs": {"out": {"source": "${echo.stdout}"}},
            },
            "parallel_child",
        )
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "reviews",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow": str(child),
                        "inputs": "${item.inputs}",
                        "error_action": "continue",
                    },
                    "batch": {
                        "items": [
                            {"inputs": {"WRONG_KEY": "oops"}},  # item[0] fails prep
                            {"inputs": {"lyrics": "fine"}},  # item[1] ok
                        ],
                        "error_handling": "continue",
                        "parallel": True,
                    },
                }
            ],
            "edges": [],
        }

        registry = Registry()
        workflow = compile_workflow(parent_ir, registry=registry)
        shared = dict(workflow.resolved_defaults)
        shared["__registry__"] = registry
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        batch_result = shared.get("reviews", {})
        assert batch_result.get("success_count") == 1
        assert batch_result.get("error_count") == 1

    def test_sequential_batch_prep_error_does_not_inherit_prior_item_trace(self, tmp_path):
        """Regression guard for `_child_trace_events` stale-state leak.

        Sequential batch reuses the same WorkflowExecutor instance across
        items. Before fixing this, exec() reset `_child_trace_events = None`
        AFTER the `_prep_error` early return — so item[0] populating the
        attribute then item[1] prep-failing meant item[1]'s trace inherited
        item[0]'s child events via `getattr(node, "_child_trace_events")`.
        Parallel batch was unaffected (workers deep-copy the node).

        Order matters: the good item must come FIRST so `_child_trace_events`
        is populated before the prep-failing item runs.
        """
        child = _write_child(
            tmp_path,
            {
                "ir_version": "0.1.0",
                "inputs": {"lyrics": {"type": "string", "required": True}},
                "nodes": [{"id": "echo", "type": "shell", "params": {"command": "echo ${lyrics}"}}],
                "edges": [],
                "outputs": {"out": {"source": "${echo.stdout}"}},
            },
            "trace_leak_child",
        )
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "reviews",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow": str(child),
                        "inputs": "${item.inputs}",
                        "error_action": "continue",
                    },
                    "batch": {
                        "items": [
                            {"inputs": {"lyrics": "first"}},  # good — populates _child_trace_events
                            {"inputs": {"WRONG_KEY": "oops"}},  # bad — would inherit the leak
                        ],
                        "error_handling": "continue",
                        "parallel": False,
                    },
                }
            ],
            "edges": [],
        }

        # Trace collection requires a trace collector in shared before run().
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        registry = Registry()
        workflow = compile_workflow(parent_ir, registry=registry)
        shared = dict(workflow.resolved_defaults)
        shared["__registry__"] = registry
        trace = WorkflowTraceCollector(workflow_name="parent")
        shared["_trace_collector"] = trace
        engine = WorkflowEngine(trace_collector=trace)
        engine.run(workflow, shared)

        # Find the two batch item trace events. Item 0 should have child
        # events from the echo shell node; item 1 should have NONE because
        # prep failed before any child execution ran.
        reviews_event = next(e for e in trace.events if e.get("node_id") == "reviews")
        batch_items = reviews_event.get("batch_items") or []
        assert len(batch_items) == 2

        item_0 = next(b for b in batch_items if b.get("index") == 0)
        item_1 = next(b for b in batch_items if b.get("index") == 1)

        # Item 0 ran its child workflow successfully — batch_executor stores
        # child trace events under the "events" key on the batch item (see
        # batch_executor._capture_item_trace). The echo shell node's execution
        # should appear there.
        item_0_events = item_0.get("events") or []
        assert len(item_0_events) > 0, (
            f"Item 0 (good) should have child trace events from the echo node. Got keys: {list(item_0.keys())}"
        )

        # Item 1 failed in prep — no child workflow ever ran. Its trace
        # must NOT inherit item 0's child events via the stale
        # `_child_trace_events` instance attribute.
        item_1_events = item_1.get("events") or []
        assert len(item_1_events) == 0, (
            f"Item 1 (prep-failed) inherited item 0's child trace events. "
            f"Expected no 'events' key (or empty list), got {len(item_1_events)} events."
        )


class TestApiWarningDetectorHijackIsPinned:
    """Pins the pre-existing api_warning_detector hijack behavior (GH #301).

    When a node's error text matches api_warning_detector patterns
    ("not found", "403", "401", etc), the detector overrides the action
    back to "error" regardless of the node's error_action — pre-existing
    engine behavior that applies to ALL node types, not specific to this
    fix. Documented in src/pflow/runtime/CLAUDE.md.

    This test PINS that behavior so any future fix to GH #301 forces an
    explicit re-evaluation (test fails → update docs → unhijack). Without
    this pin, the CLAUDE.md caveat is unfalsifiable documentation that
    could silently drift from reality.
    """

    def test_file_not_found_hijacked_despite_error_action_continue(self, tmp_path):
        """FileNotFoundError text matches "not found" → detector overrides → action="error".

        When GH #301 is fixed, this test fails. The fix should:
        1. Update src/pflow/runtime/CLAUDE.md (remove the "not found" caveat from
           the error_action bullet, reference GH #301 as closed)
        2. Flip this test to assert result == "continue" (the intended semantic)
        3. Update the docstring on test_circular_reference_dispatches_error_action
           (remove the "chose circular because 'not found' hijacks" note)
        """
        registry = Registry()
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "missing_child",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow": str(tmp_path / "does_not_exist.pflow.md"),
                        "error_action": "continue",
                        "inputs": {},
                    },
                }
            ],
            "edges": [],
        }
        workflow = compile_workflow(parent_ir, registry=registry)
        shared = dict(workflow.resolved_defaults)
        shared["__registry__"] = registry
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

        # Pre-existing engine hijack: api_warning_detector sees "not found"
        # in the error text and overrides error_action="continue" → "error".
        # If this assertion starts failing, GH #301 was fixed — follow the
        # docstring's migration steps.
        assert result == "error", (
            "api_warning_detector hijack behavior changed — see GH #301. "
            "Update src/pflow/runtime/CLAUDE.md and flip this test's assertion."
        )
        # Failure is archived as api_warning category (hijack path), NOT as
        # node_action_error (which is what error_action dispatch would archive).
        failure = get_node_failure(shared, "missing_child")
        assert failure is not None
        assert failure.get("category") == "api_warning"
