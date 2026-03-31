"""Regression tests for compile-once caching in WorkflowExecutor.

WorkflowExecutor._compile_sub_workflow() caches the CompiledWorkflow on the
instance via _cached_workflow. For both sequential and parallel batch processing,
compile_workflow should be called EXACTLY ONCE.

Sequential: the same WorkflowExecutor instance handles all items, caching on first call.
Parallel: the batch executor pre-warms the compile cache on the original node before
deep-copying for thread dispatch, so each deep copy inherits _cached_workflow.

These tests verify:
1. compile_workflow is called once for N sequential batch items
2. compile_workflow is called once for N parallel batch items (pre-warm)
3. Each batch item still produces distinct output (cache does not cause stale data)
4. File-based sub-workflows also get compile-once (IR cached in prep())
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from pflow.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine


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
        workflow = compile_workflow(parent_ir, registry=registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

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


def test_compile_workflow_called_once_for_parallel_batch(tmp_path: Path):
    """compile_workflow is invoked exactly once for parallel batch over file-based sub-workflows.

    The batch executor pre-warms the compile cache on the original node before
    deep-copying for parallel dispatch. Each deep-copied WorkflowExecutor inherits
    _cached_workflow (via _cached_loaded_ir which signals non-inline source),
    so no thread recompiles.

    This is the key parallel performance improvement: O(1) compilation instead of O(N).
    Without pre-warming, each of the N deep-copied threads starts with _cached_workflow=None
    and independently calls compile_workflow().

    Uses a file-based child workflow (not inline IR) because pre-warm only works for
    file/name sources. Inline IR can't survive deepcopy's id() change, and inline IR
    with templates (${item}) MUST recompile per item anyway.
    """
    from pflow.runtime.compilation.compiler import compile_workflow as real_compile_workflow

    # Write child workflow to a file
    child_md = tmp_path / "child.pflow.md"
    child_md.write_text(
        "# Child\n\nA child workflow.\n\n## Steps\n\n### echo\n\nRun echo.\n\n- type: shell\n- command: echo hello\n",
        encoding="utf-8",
    )

    call_count = 0

    def counting_compile_workflow(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        return real_compile_workflow(*args, **kwargs)

    parent_ir: dict[str, Any] = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "source",
                "type": "shell",
                "params": {"command": 'echo \'["alpha", "beta", "gamma"]\''},
            },
            {
                "id": "process",
                "type": "workflow",
                "batch": {
                    "items": "${source.stdout}",
                    "as": "item",
                    "parallel": True,
                    "max_concurrent": 3,
                },
                "params": {"workflow": str(child_md)},
            },
        ],
        "edges": [{"from": "source", "to": "process"}],
    }

    registry = Registry()

    with patch(
        "pflow.runtime.workflow_executor.compile_workflow",
        side_effect=counting_compile_workflow,
    ):
        workflow = compile_workflow(parent_ir, registry=registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

    assert result == "default", (
        f"Parallel batch workflow failed with result: {result}. "
        f"Error: {shared.get('process', {}).get('error', shared.get('error', 'N/A'))}"
    )

    # The sub-workflow should be compiled exactly once (pre-warm), not 3 times.
    assert call_count == 1, (
        f"Expected compile_workflow called once (pre-warm before parallel dispatch), "
        f"but it was called {call_count} time(s). "
        f"The batch executor's _pre_warm_compile_cache may not be working."
    )

    # Verify all 3 items produced results
    process_data = shared.get("process", {})
    results = process_data.get("results", [])
    assert len(results) == 3, f"Expected 3 parallel batch results, got {len(results)}"


def test_parallel_batch_items_produce_distinct_output(tmp_path: Path):
    """Each parallel batch item gets its own resolved params — no cross-thread contamination.

    This is the correctness complement to compile-once. The pre-warm deep-copies
    the WorkflowExecutor (including _cached_workflow) per thread. If the deep copy
    somehow shares node instances (params dict references, successor references),
    threads clobber each other's resolved params and items get wrong output.

    The failure mode is SILENT: no crash, just item A's text appearing in item B's
    result. This test catches it by verifying each result contains its own unique marker.
    """
    child_md = tmp_path / "child.pflow.md"
    child_md.write_text(
        "# Child\n\nA child workflow.\n\n"
        "## Inputs\n\n### text\n\nText input.\n\n- type: str\n- required: true\n\n"
        "## Steps\n\n### echo\n\nEcho the text.\n\n- type: shell\n- command: echo MARKER_${text}_END\n",
        encoding="utf-8",
    )

    parent_ir: dict[str, Any] = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "source",
                "type": "shell",
                "params": {"command": 'echo \'["alpha", "beta", "gamma", "delta", "epsilon"]\''},
            },
            {
                "id": "process",
                "type": "workflow",
                "batch": {
                    "items": "${source.stdout}",
                    "as": "item",
                    "parallel": True,
                    "max_concurrent": 5,
                },
                "params": {
                    "workflow": str(child_md),
                    "text": "${item}",
                },
            },
        ],
        "edges": [{"from": "source", "to": "process"}],
    }

    registry = Registry()
    workflow = compile_workflow(parent_ir, registry=registry)
    shared: dict[str, Any] = dict(workflow.resolved_defaults)
    engine = WorkflowEngine()
    result = engine.run(workflow, shared)

    assert result == "default", f"Workflow failed: {shared.get('error', 'N/A')}"

    results = shared["process"]["results"]
    assert len(results) == 5, f"Expected 5 results, got {len(results)}"

    # Each result must contain its OWN unique marker, not another item's
    expected = ["alpha", "beta", "gamma", "delta", "epsilon"]
    for i, text in enumerate(expected):
        stdout = results[i]["echo"]["stdout"].strip()
        assert f"MARKER_{text}_END" == stdout, (
            f"Item {i}: expected 'MARKER_{text}_END', got '{stdout}'. "
            f"If another item's marker appears, deep-copied compiled workflows share state between threads."
        )


def test_each_batch_item_produces_distinct_output():
    """Each batch item produces output containing its own text, not stale data.

    This test uses ${item} inside workflow_ir, which the parent resolver
    resolves per batch iteration. Each child gets a different literal command
    ("echo MARKER_alpha_END", "echo MARKER_beta_END", "echo MARKER_gamma_END"),
    producing distinct output per item.
    """
    parent_ir = _make_parent_ir_dynamic_child()
    registry = Registry()
    workflow = compile_workflow(parent_ir, registry=registry)
    shared: dict[str, Any] = dict(workflow.resolved_defaults)
    engine = WorkflowEngine()
    result = engine.run(workflow, shared)

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


def test_compile_once_for_file_based_sub_workflow(tmp_path: Path):
    """File-based sub-workflows compile once per batch, not once per item.

    prep() caches the loaded IR for non-inline sources so the same dict
    object is reused across batch items. This makes id(workflow_ir) stable,
    allowing the compile-once cache in _compile_sub_workflow to hit.

    Without the IR caching in prep(), each batch item would re-parse the
    file, producing a new dict object with a different id() — O(N) compiles.
    """
    from pflow.runtime.compilation.compiler import compile_workflow as real_compile_workflow

    # Write child workflow to a file
    child_md = tmp_path / "child.pflow.md"
    child_md.write_text(
        "# Child\n\nA child workflow.\n\n## Steps\n\n### echo\n\nRun echo.\n\n- type: shell\n- command: echo hello\n",
        encoding="utf-8",
    )

    parent_ir: dict[str, Any] = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "source",
                "type": "shell",
                "params": {"command": 'echo \'["a", "b", "c"]\''},
            },
            {
                "id": "process",
                "type": "workflow",
                "batch": {"items": "${source.stdout}", "as": "item"},
                "params": {"workflow": str(child_md)},
            },
        ],
        "edges": [{"from": "source", "to": "process"}],
    }

    call_count = 0

    def counting_compile(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        return real_compile_workflow(*args, **kwargs)

    registry = Registry()

    with patch(
        "pflow.runtime.workflow_executor.compile_workflow",
        side_effect=counting_compile,
    ):
        workflow = compile_workflow(parent_ir, registry=registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

    assert result == "default", f"Workflow failed: {shared.get('error', 'N/A')}"
    assert call_count == 1, (
        f"File-based sub-workflow compiled {call_count} time(s), expected 1. "
        f"prep() IR caching may not be working for file sources."
    )
    results = shared.get("process", {}).get("results", [])
    assert len(results) == 3, f"Expected 3 batch results, got {len(results)}"


def test_resolved_defaults_do_not_leak_between_batch_items(tmp_path: Path):
    """Cached resolved_defaults must not leak per-item coerced values between items.

    Scenario: file-based child workflow declares input 'text' (required) and 'prefix'
    (optional, default: "DEFAULT"). Parent passes 'text' per-item via ${item}. The
    child echoes both. Each item should get its own 'text' and the shared default 'prefix'.

    Bug this catches: if resolved_defaults seeding doesn't filter keys present in
    child_params, item 1's coerced 'text' value leaks to item 2 via the cached
    resolved_defaults dict. The fix: only seed resolved_defaults keys NOT in child_params.

    Uses a file-based child so child-level templates (${text}, ${prefix}) are isolated
    from the parent's template resolver — the parent only sees the file path.
    """
    # Write child workflow with declared inputs + defaults
    child_md = tmp_path / "child.pflow.md"
    child_md.write_text(
        "# Child\n\nA child workflow.\n\n"
        "## Inputs\n\n"
        "### text\n\nThe text to echo.\n\n"
        "- type: str\n"
        "- required: true\n\n"
        "### prefix\n\nOptional prefix.\n\n"
        "- type: str\n"
        "- required: false\n"
        "- default: DEFAULT\n\n"
        "## Steps\n\n"
        "### echo\n\nEcho with prefix.\n\n"
        "- type: shell\n"
        "- command: echo ${prefix}_${text}\n",
        encoding="utf-8",
    )

    parent_ir: dict[str, Any] = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "source",
                "type": "shell",
                "params": {"command": 'echo \'["aaa", "bbb", "ccc"]\''},
            },
            {
                "id": "process",
                "type": "workflow",
                "batch": {"items": "${source.stdout}", "as": "item"},
                "params": {
                    "workflow": str(child_md),
                    "text": "${item}",  # Per-item — must NOT leak between items
                    # prefix NOT passed — child should use default "DEFAULT"
                },
            },
        ],
        "edges": [{"from": "source", "to": "process"}],
    }

    registry = Registry()
    workflow = compile_workflow(parent_ir, registry=registry)
    shared: dict[str, Any] = dict(workflow.resolved_defaults)
    engine = WorkflowEngine()
    result = engine.run(workflow, shared)

    assert result == "default", f"Workflow failed: {shared.get('error', 'N/A')}"

    results = shared["process"]["results"]
    assert len(results) == 3

    # Each item should have its OWN text value and the DEFAULT prefix
    for i, expected_text in enumerate(["aaa", "bbb", "ccc"]):
        stdout = results[i]["echo"]["stdout"].strip()
        assert stdout == f"DEFAULT_{expected_text}", (
            f"Item {i}: expected 'DEFAULT_{expected_text}', got '{stdout}'. "
            f"If prefix is wrong, defaults leaked. If text is wrong, per-item values leaked."
        )


def test_storage_mode_shared_through_engine(tmp_path: Path):
    """storage_mode: shared works through the full engine path with namespacing.

    Bug this catches: NamespacedSharedStore didn't implement update(), so
    child_storage.update(resolved_defaults) crashed with AttributeError when
    the workflow node received a NamespacedSharedStore (namespacing default=True).

    This test runs a workflow node with storage_mode: shared through the real
    compile→engine pipeline, not just _create_child_storage() in isolation.
    """
    child_md = tmp_path / "child.pflow.md"
    child_md.write_text(
        "# Child\n\nA child workflow.\n\n"
        "## Steps\n\n"
        "### echo\n\nEcho shared data.\n\n"
        "- type: shell\n"
        "- command: echo shared_works\n",
        encoding="utf-8",
    )

    parent_ir: dict[str, Any] = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "child",
                "type": "workflow",
                "params": {
                    "workflow": str(child_md),
                    "storage_mode": "shared",
                },
            },
        ],
        "edges": [],
    }

    registry = Registry()
    workflow = compile_workflow(parent_ir, registry=registry)
    shared: dict[str, Any] = dict(workflow.resolved_defaults)
    engine = WorkflowEngine()
    result = engine.run(workflow, shared)

    assert result == "default", (
        f"Workflow with storage_mode: shared failed: {result}. "
        f"If AttributeError on 'update', NamespacedSharedStore is missing update()."
    )
