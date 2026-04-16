"""Tests for the IR load cache on WorkflowExecutor.

The cache (``_loaded_ir_cache``) is keyed by the raw workflow reference string
(the value of ``self.params["workflow"]``). This is what makes heterogeneous
batches correct: different ``${item.workflow}`` resolutions produce different
keys, so each child workflow loads independently. Homogeneous batches hit the
cache from item 2 onward.
"""

from pathlib import Path
from typing import Any

from tests.shared.markdown_utils import write_workflow_file


def _write_child(tmp_path: Path, name: str, command: str) -> Path:
    """Write a minimal child workflow file and return its path."""
    path = tmp_path / f"{name}.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "step", "type": "shell", "params": {"command": command}}],
            "edges": [],
        },
        path,
    )
    return path


def test_ir_cache_hits_on_same_ref(tmp_path: Path) -> None:
    """Two prep() calls with the same raw ref reuse the cached IR."""
    from pflow.runtime.workflow_executor import WorkflowExecutor

    child = _write_child(tmp_path, "child", "echo hi")
    node = WorkflowExecutor()
    node.set_params({"workflow": str(child)})

    # Each prep() gets its own disposable ``shared`` dict. ``prep()`` mutates
    # ``shared["__parser_diagnostics__"]`` via ``_propagate_child_parser_warnings``;
    # keeping the dicts separate ensures no double-propagation across calls.
    first = node.prep({"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")})
    second = node.prep({"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")})

    assert first["child_ir"] is second["child_ir"], (
        "Same workflow ref should produce the same IR dict from the cache. "
        "Cache miss on identical key suggests the cache is not actually keyed by raw ref."
    )
    assert str(child) in node._loaded_ir_cache


def test_ir_cache_miss_on_different_ref(tmp_path: Path) -> None:
    """Changing the raw ref between prep() calls loads a fresh IR.

    This is the heterogeneous-batch invariant: ``${item.workflow}`` resolves to
    different strings per iteration, which must yield different cache keys.
    If this test fails, the heterogeneous batch case will silently reuse the
    wrong child IR (as it did before commit 1 — see Bug B in
    scratchpads/undeclared-workflow-input-drop/bug-report.md).
    """
    from pflow.runtime.workflow_executor import WorkflowExecutor

    child_a = _write_child(tmp_path, "child-a", "echo A")
    child_b = _write_child(tmp_path, "child-b", "echo B")

    node = WorkflowExecutor()
    shared: dict[str, Any] = {"_pflow_workflow_file": str(tmp_path / "parent.pflow.md")}

    node.set_params({"workflow": str(child_a)})
    prep_a = node.prep(shared)

    node.set_params({"workflow": str(child_b)})
    prep_b = node.prep(shared)

    assert prep_a["child_ir"] is not prep_b["child_ir"], (
        "Different workflow refs must produce different IRs. "
        "If they're identical, the cache is accidentally reusing the first child's "
        "IR for the second call — the heterogeneous-batch bug."
    )
    # Both entries should coexist in the cache
    assert str(child_a) in node._loaded_ir_cache
    assert str(child_b) in node._loaded_ir_cache

    # Sanity: the actual shell commands differ
    assert prep_a["child_ir"]["nodes"][0]["params"]["command"] == "echo A"
    assert prep_b["child_ir"]["nodes"][0]["params"]["command"] == "echo B"


def test_heterogeneous_batch_loads_correct_child_ir(tmp_path: Path) -> None:
    """End-to-end: parallel batch over two different child workflows, each with
    its own inputs dict, produces both children's distinct output.

    Before commit 1, this failed with "missing required input a … you provided: b"
    because item 2 loaded item 1's cached IR but received item 2's inputs
    (reproduced at ``/tmp/pflow-repro-batch/`` per the plan).
    """
    from pflow.registry import Registry
    from pflow.runtime import compile_workflow
    from pflow.runtime.engine import WorkflowEngine

    # Child A: declares input `a`
    child_a = tmp_path / "child-a.pflow.md"
    child_a.write_text(
        "# Child A\n\nA child that needs input a.\n\n"
        "## Inputs\n\n### a\n\nInput a.\n\n- type: string\n- required: true\n\n"
        "## Steps\n\n### echo\n\nEcho a.\n\n- type: shell\n- command: echo a_is_${a}\n",
        encoding="utf-8",
    )

    # Child B: declares input `b`
    child_b = tmp_path / "child-b.pflow.md"
    child_b.write_text(
        "# Child B\n\nA child that needs input b.\n\n"
        "## Inputs\n\n### b\n\nInput b.\n\n- type: string\n- required: true\n\n"
        "## Steps\n\n### echo\n\nEcho b.\n\n- type: shell\n- command: echo b_is_${b}\n",
        encoding="utf-8",
    )

    parent_ir: dict[str, Any] = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "call-many",
                "type": "workflow",
                "batch": {
                    "items": [
                        {"workflow": str(child_a), "inputs": {"a": "ALPHA"}},
                        {"workflow": str(child_b), "inputs": {"b": "BETA"}},
                    ],
                    "as": "item",
                    "parallel": False,  # sequential first — simpler to diagnose
                },
                "params": {
                    "workflow": "${item.workflow}",
                    "inputs": "${item.inputs}",
                },
            },
        ],
        "edges": [],
    }

    registry = Registry()
    workflow = compile_workflow(parent_ir, registry=registry)
    shared: dict[str, Any] = dict(workflow.resolved_defaults)
    result = WorkflowEngine().run(workflow, shared)

    assert result == "default", (
        f"Heterogeneous batch failed with result={result!r}. "
        f"Error: {shared.get('call-many', {}).get('error', shared.get('error', 'N/A'))}"
    )

    results = shared["call-many"]["results"]
    assert len(results) == 2, f"Expected 2 results, got {len(results)}: {results!r}"
    # Each child received its own correctly-keyed input
    stdouts = [r["echo"]["stdout"].strip() for r in results]
    assert stdouts == ["a_is_ALPHA", "b_is_BETA"], (
        f"Each child should produce its own output. Got: {stdouts!r}. "
        "If item 1's command appears twice, the IR cache is sticky across heterogeneous items."
    )


def test_heterogeneous_batch_parallel(tmp_path: Path) -> None:
    """Same as test_heterogeneous_batch_loads_correct_child_ir but parallel=True.

    Before commit 1, the parallel path pre-warmed the compile cache using only
    item 0, then deep-copied that state into every worker. Item 2's thread
    inherited child-a's cached IR. The fix: cache keyed by workflow_path so
    each worker naturally cache-misses and loads its own child.
    """
    from pflow.registry import Registry
    from pflow.runtime import compile_workflow
    from pflow.runtime.engine import WorkflowEngine

    child_a = tmp_path / "child-a.pflow.md"
    child_a.write_text(
        "# Child A\n\nA child.\n\n"
        "## Inputs\n\n### a\n\nInput a.\n\n- type: string\n- required: true\n\n"
        "## Steps\n\n### echo\n\nEcho.\n\n- type: shell\n- command: echo a_is_${a}\n",
        encoding="utf-8",
    )
    child_b = tmp_path / "child-b.pflow.md"
    child_b.write_text(
        "# Child B\n\nA child.\n\n"
        "## Inputs\n\n### b\n\nInput b.\n\n- type: string\n- required: true\n\n"
        "## Steps\n\n### echo\n\nEcho.\n\n- type: shell\n- command: echo b_is_${b}\n",
        encoding="utf-8",
    )

    parent_ir: dict[str, Any] = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "call-many",
                "type": "workflow",
                "batch": {
                    "items": [
                        {"workflow": str(child_a), "inputs": {"a": "ALPHA"}},
                        {"workflow": str(child_b), "inputs": {"b": "BETA"}},
                    ],
                    "as": "item",
                    "parallel": True,
                    "max_concurrent": 2,
                },
                "params": {
                    "workflow": "${item.workflow}",
                    "inputs": "${item.inputs}",
                },
            },
        ],
        "edges": [],
    }

    registry = Registry()
    workflow = compile_workflow(parent_ir, registry=registry)
    shared: dict[str, Any] = dict(workflow.resolved_defaults)
    result = WorkflowEngine().run(workflow, shared)

    assert result == "default", (
        f"Parallel heterogeneous batch failed: {shared.get('call-many', {}).get('error', 'N/A')}"
    )

    results = shared["call-many"]["results"]
    assert len(results) == 2
    stdouts = sorted(r["echo"]["stdout"].strip() for r in results)
    assert stdouts == ["a_is_ALPHA", "b_is_BETA"], (
        f"Each parallel worker should produce its own child's output. Got: {stdouts!r}."
    )
