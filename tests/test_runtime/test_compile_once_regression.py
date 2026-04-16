"""Regression tests for compile-once caching in WorkflowExecutor.

WorkflowExecutor._compile_sub_workflow() caches the CompiledWorkflow on the
instance via ``_compiled_workflow_cache`` (dict keyed by workflow_path).
For both sequential and parallel batch processing over a homogeneous child
workflow, compile_workflow should be called EXACTLY ONCE.

Sequential: the same WorkflowExecutor instance handles all items, caching
on first call. Parallel: the batch executor pre-warms the compile cache on
the original node before deep-copying for thread dispatch, so each deep
copy inherits ``_compiled_workflow_cache``.

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


def _write_static_child(tmp_path: Path) -> Path:
    """Write a minimal static child workflow file."""
    child = tmp_path / "static-child.pflow.md"
    child.write_text(
        "# Static Child\n\nA static child.\n\n"
        "## Steps\n\n### step\n\nEcho hello.\n\n- type: shell\n- command: echo hello\n",
        encoding="utf-8",
    )
    return child


def _write_dynamic_child(tmp_path: Path) -> Path:
    """Write a child workflow that consumes the ${item} input via child-side template."""
    child = tmp_path / "dynamic-child.pflow.md"
    child.write_text(
        "# Dynamic Child\n\nConsumes input text.\n\n"
        "## Inputs\n\n### text\n\nThe per-item text.\n\n- type: string\n- required: true\n\n"
        "## Steps\n\n### echo\n\nEcho the text with markers.\n\n"
        "- type: shell\n- command: echo MARKER_${text}_END\n",
        encoding="utf-8",
    )
    return child


def _make_parent_ir_static_child(child_path: Path) -> dict[str, Any]:
    """Parent workflow with a batch workflow node referencing a file-based child.

    Structure:
      source (shell, emits JSON array) -> process (workflow, batch)

    The child reference is a static file path, so the compile-once cache
    hits on item 2+ across sequential batch iterations.
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
                    "workflow": str(child_path),
                },
            },
        ],
        "edges": [{"from": "source", "to": "process"}],
    }


def _make_parent_ir_dynamic_child(child_path: Path) -> dict[str, Any]:
    """Parent workflow that passes a per-item ``text`` input to a file-based child.

    Structure:
      source (shell, emits JSON array) -> process (workflow, batch)

    Each iteration passes ``inputs: {text: ${item}}``. Since the child itself
    is static (same file path per iteration), compile-once still applies —
    per-item differentiation happens inside the child's template resolution.
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
                    "workflow": str(child_path),
                    "inputs": {"text": "${item}"},
                },
            },
        ],
        "edges": [{"from": "source", "to": "process"}],
    }


def test_compile_workflow_called_once_for_static_child(tmp_path: Path) -> None:
    """compile_workflow is invoked exactly once for N sequential batch items
    when the child workflow is a file reference (static path).

    The ``_compiled_workflow_cache`` keys compiled workflows by resolved path,
    so a homogeneous batch (same path per iteration) hits the cache on item 2+.
    """
    from pflow.runtime.compilation.compiler import compile_workflow as real_compile_workflow

    call_count = 0

    def counting_compile_workflow(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        return real_compile_workflow(*args, **kwargs)

    child = _write_static_child(tmp_path)
    parent_ir = _make_parent_ir_static_child(child)
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
    assert call_count == 1, (
        f"Expected compile_workflow called once (path-keyed compile cache), "
        f"but it was called {call_count} time(s). "
        f"This suggests _compiled_workflow_cache is not recognizing the same "
        f"resolved workflow path across batch iterations."
    )

    # Verify all 3 items produced results (compilation was valid)
    process_data = shared.get("process", {})
    results = process_data.get("results", [])
    assert len(results) == 3, f"Expected 3 batch results, got {len(results)}"


def test_compile_workflow_called_once_for_parallel_batch(tmp_path: Path):
    """compile_workflow is invoked exactly once for parallel batch over file-based sub-workflows.

    The batch executor pre-warms the compile cache on the original node before
    deep-copying for parallel dispatch. Each deep-copied WorkflowExecutor inherits
    ``_compiled_workflow_cache`` (populated only when the IR came from a file/name
    source, as signalled by a non-empty ``_loaded_ir_cache``), so no thread recompiles.

    This is the key parallel performance improvement: O(1) compilation instead of O(N).
    Without pre-warming, each of the N deep-copied threads starts with an empty
    compile cache and independently calls compile_workflow().

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
    the WorkflowExecutor (including ``_compiled_workflow_cache``) per thread. If
    the deep copy somehow shares node instances (params dict references, successor
    references), threads clobber each other's resolved params and items get wrong output.

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
                    "inputs": {"text": "${item}"},
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


def test_each_batch_item_produces_distinct_output(tmp_path: Path) -> None:
    """Each batch item produces output containing its own text, not stale data.

    This test uses ``inputs: {text: ${item}}`` at the parent node level. The
    parent resolver resolves ``${item}`` per batch iteration, and the child's
    template ``${text}`` (inside its shell command) produces distinct output
    per item — even though the child itself compiles only once (static path).
    """
    child = _write_dynamic_child(tmp_path)
    parent_ir = _make_parent_ir_dynamic_child(child)
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


def test_parallel_batch_workflow_resolves_child_file_refs(tmp_path: Path):
    """File references in child workflows resolve correctly under parallel batch.

    Regression test for GH-225: when a workflow node is in a parallel batch,
    _pre_warm_compile_cache() compiles the sub-workflow. If _compile_sub_workflow()
    doesn't inject _pflow_workflow_file, file references in the child resolve
    relative to CWD instead of the child's directory.
    """
    # Create child workflow in a subdirectory with a sibling script
    child_dir = tmp_path / "child"
    child_dir.mkdir()
    (child_dir / "greet.sh").write_text('echo "hello from child dir"')

    child_md = child_dir / "child.pflow.md"
    child_md.write_text(
        "# Child\n\nA child workflow.\n\n## Steps\n\n### greet\n\nRun greeting.\n\n"
        "- type: shell\n- command: ./greet.sh\n"
    )

    # Parent workflow: workflow node in a parallel batch
    parent_ir: dict[str, Any] = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "run-children",
                "type": "workflow",
                "params": {"workflow": str(child_md)},
                "batch": {
                    "items": [{"name": "a"}, {"name": "b"}],
                    "parallel": True,
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

    assert result == "default", f"Workflow failed: {shared}"
    results = shared.get("run-children", {}).get("results", [])
    assert len(results) == 2
    for item_result in results:
        greet_output = item_result.get("greet", {})
        assert greet_output.get("stdout") == "hello from child dir"


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
                    "inputs": {"text": "${item}"},  # Per-item — must NOT leak between items
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
