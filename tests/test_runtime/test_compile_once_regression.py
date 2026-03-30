"""Regression tests for compile-once caching in WorkflowExecutor.

WorkflowExecutor._compile_sub_workflow() caches the CompiledWorkflow on the
instance via _cached_workflow. For sequential batch processing, compile_workflow
should be called EXACTLY ONCE -- subsequent batch items reuse the cached result.

These tests verify:
1. compile_workflow is called once (not N times) for N sequential batch items
2. Each batch item still produces distinct output (cache does not cause stale data)

Implementation context:
  The compile-once cache uses id(workflow_ir) to detect whether the same
  IR dict is passed. For this to work, workflow_ir must be a STATIC param
  (no ${...} templates inside it). When workflow_ir IS static, split_params
  puts it in static_params, and the template resolver preserves the same
  dict reference across batch iterations.

  When workflow_ir DOES contain templates (e.g., ${item} for parent-level
  resolution), resolve_nested creates a new dict each time, producing a
  different id() per item. In that case, recompilation is correct because
  the child workflow structure differs per item.
"""

from typing import Any
from unittest.mock import patch

from pflow.registry import Registry
from pflow.runtime import compile_ir_to_flow


def _make_static_child_ir() -> dict[str, Any]:
    """A static child workflow IR with no template expressions.

    The shell command is fixed -- per-item differentiation comes from
    the batch item value being passed as a child param and the child
    reading it from its shared store at execution time.

    This child workflow is COMPLETELY STATIC from the parent resolver's
    perspective, which means split_params classifies workflow_ir as a
    static param, preserving the same dict reference across batch items.
    """
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "step",
                "type": "shell",
                "params": {"command": "echo hello"},
            }
        ],
        "edges": [],
    }


def _make_parent_ir_static_child() -> dict[str, Any]:
    """Parent workflow with a batch workflow node using a static child IR.

    Structure:
      source (shell, emits JSON array) -> process (workflow, batch)

    The child workflow_ir is entirely static (no templates), so the
    compile-once cache works: same dict object reference on each call.
    """
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "source",
                "type": "shell",
                "params": {
                    "command": 'echo \'["alpha", "beta", "gamma"]\'',
                },
            },
            {
                "id": "process",
                "type": "workflow",
                "batch": {"items": "${source.stdout}", "as": "item"},
                "params": {
                    "workflow_ir": _make_static_child_ir(),
                },
            },
        ],
        "edges": [{"from": "source", "to": "process"}],
    }


def _make_parent_ir_dynamic_child() -> dict[str, Any]:
    """Parent workflow where the child IR contains ${item} templates.

    Structure:
      source (shell, emits JSON array) -> process (workflow, batch)

    The child's shell command uses ${item} which the PARENT resolver
    resolves per batch iteration (batch executor injects 'item' into shared).
    This creates a new workflow_ir dict per item, enabling distinct output.
    """
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "source",
                "type": "shell",
                "params": {
                    "command": 'echo \'["alpha", "beta", "gamma"]\'',
                },
            },
            {
                "id": "process",
                "type": "workflow",
                "batch": {"items": "${source.stdout}", "as": "item"},
                "params": {
                    "workflow_ir": {
                        "ir_version": "0.1.0",
                        "nodes": [
                            {
                                "id": "echo",
                                "type": "shell",
                                "params": {"command": "echo MARKER_${item}_END"},
                            }
                        ],
                        "edges": [],
                    },
                },
            },
        ],
        "edges": [{"from": "source", "to": "process"}],
    }


def test_compile_workflow_called_once_for_static_child_ir():
    """compile_workflow is invoked exactly once for 3 sequential batch items
    when workflow_ir is a static param (no templates inside it).

    When workflow_ir has no template expressions, split_params classifies it
    as a static param. The template resolver preserves the same dict reference
    across batch iterations, so id(workflow_ir) remains constant and the
    compile-once cache in _compile_sub_workflow returns the cached result.
    """
    from pflow.runtime.compilation.compiler import compile_workflow as real_compile_workflow

    call_count = 0

    def counting_compile_workflow(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        return real_compile_workflow(*args, **kwargs)

    parent_ir = _make_parent_ir_static_child()
    registry = Registry()

    with patch(
        "pflow.runtime.workflow_executor.compile_workflow",
        side_effect=counting_compile_workflow,
    ):
        flow = compile_ir_to_flow(parent_ir, registry=registry)
        shared: dict[str, Any] = {}
        result = flow.run(shared)

    assert result == "default", (
        f"Workflow failed with result: {result}. "
        f"Shared keys: {list(shared.keys())}. "
        f"Error: {shared.get('process', {}).get('error', shared.get('error', 'N/A'))}"
    )

    # The sub-workflow should have been compiled exactly once, not 3 times.
    # This is the core performance improvement: O(1) compilation for batch.
    assert call_count == 1, (
        f"Expected compile_workflow to be called once (compile-once cache), "
        f"but it was called {call_count} time(s). "
        f"This suggests the id()-based cache is not recognizing the same "
        f"workflow_ir dict across batch iterations."
    )

    # Verify all 3 items produced results (compilation was valid)
    process_data = shared.get("process", {})
    results = process_data.get("results", [])
    assert len(results) == 3, f"Expected 3 batch results, got {len(results)}"


def test_each_batch_item_produces_distinct_output():
    """Each batch item produces output containing its own text, not stale data.

    This test uses ${item} inside workflow_ir, which the parent resolver
    resolves per batch iteration. Each child gets a different literal command
    ("echo MARKER_alpha_END", "echo MARKER_beta_END", "echo MARKER_gamma_END"),
    producing distinct output per item.
    """
    parent_ir = _make_parent_ir_dynamic_child()
    registry = Registry()
    flow = compile_ir_to_flow(parent_ir, registry=registry)
    shared: dict[str, Any] = {}
    result = flow.run(shared)

    assert result == "default", (
        f"Workflow failed with result: {result}. "
        f"Shared keys: {list(shared.keys())}. "
        f"Error: {shared.get('process', {}).get('error', shared.get('error', 'N/A'))}"
    )

    # The batch node writes results under shared["process"]
    assert "process" in shared, f"Expected 'process' key in shared store. Keys: {list(shared.keys())}"
    process_data = shared["process"]
    assert "results" in process_data, f"Expected 'results' in process data. Keys: {list(process_data.keys())}"

    results = process_data["results"]
    assert len(results) == 3, f"Expected 3 batch results, got {len(results)}"

    # Each result should contain the corresponding text value.
    # The parent template resolver resolves ${item} to the literal string
    # ("alpha", "beta", "gamma") before the child compiles, so the child's
    # shell command becomes "echo MARKER_alpha_END" etc.
    expected_texts = ["alpha", "beta", "gamma"]
    for i, expected_text in enumerate(expected_texts):
        item_result = results[i]
        assert item_result is not None, f"Batch item {i} result is None"

        # Search the entire result structure for the expected marker.
        result_str = str(item_result)
        assert f"MARKER_{expected_text}_END" in result_str, (
            f"Batch item {i}: expected 'MARKER_{expected_text}_END' in output, got: {item_result}"
        )
