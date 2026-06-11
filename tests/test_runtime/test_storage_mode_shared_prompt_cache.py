"""Parent prompt-cache isolation under `storage_mode: shared` x parallel batch.

History: `runtime/CLAUDE.md` documented this combination as a benign RACE —
"two parallel batch items each running a `storage_mode: shared` sub-workflow
with its own `## Cache` block both invoke WorkflowEngine.run's save/restore
on the SAME parent root... last-finished worker wins" — and a skip-marked
test here waited for a guard (GH #379) that never landed.

The 2026-06 audit follow-up traced the actual write path and found the race
cannot reach the parent root: every batch item (parallel AND sequential) runs
against a per-item shallow copy (`item_shared = dict(shared)` in
`batch_executor.py`), the child engine's save/restore goes through a
`NamespacedSharedStore` whose `_parent` IS that discarded copy, and the value
is an immutable `MappingProxyType` that is only ever rebound — so child
restores can't leak into the parent's binding.

This test pins that isolation at runtime with the real pipeline. If it ever
fails, batch items have stopped copying the shared store — at which point the
documented race becomes real and a guard (or the copy) must be restored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pflow.core.markdown_parser import parse_markdown
from pflow.core.node import BaseNode
from pflow.registry.registry import Registry
from pflow.runtime.compilation.compiler import compile_workflow
from pflow.runtime.engine.engine import WorkflowEngine, build_prompt_cache_dict
from pflow.runtime.engine.types import BatchConfig, CompiledWorkflow, NodeConfig
from pflow.runtime.workflow_executor import WorkflowExecutor

_CHILD_MARKDOWN = """\
# Child

Child sub-workflow with its own prompt-cache block.

## Inputs

### brief

The shared brief.

- type: string

## Cache

```cache
The brief:

${brief}
```

## Steps

### child-llm

Child LLM step (mocked by the autouse fixture).

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Say hello.
```
"""


class _CachePrefixProbe(BaseNode):
    """Reads the parent root's prompt-cache binding AFTER the batch node."""

    def exec(self, prep_res: Any) -> Any:
        return None

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        cache_map = shared.get("__pflow_prompt_cache__") or {}
        shared["cache_keys"] = sorted(cache_map.keys())
        return "default"


def test_parallel_shared_subworkflow_child_cache_does_not_leak_into_parent(tmp_path: Path) -> None:
    """The parent's `__pflow_prompt_cache__` binding survives a parallel batch
    of `storage_mode: shared` children that each install their own cache map.

    Discriminator: the parent map is keyed {"parent-llm"} (a prewarm-declaring
    LLM node), the child maps are keyed {"child-llm"} (via the child's
    `## Cache` block). A leaked child restore would surface as "child-llm" —
    or an empty map — at the probe.
    """
    child_path = tmp_path / "child.pflow.md"
    child_path.write_text(_CHILD_MARKDOWN, encoding="utf-8")
    registry = Registry()

    # Vacuity guard: the child genuinely installs a non-empty cache map of its
    # own (otherwise a "no leak" assertion below would be meaningless).
    child_compiled = compile_workflow(parse_markdown(child_path.read_text()).ir, registry, {"brief": "x"})
    assert sorted(build_prompt_cache_dict(child_compiled, {})) == ["child-llm"]

    fanout = WorkflowExecutor()
    fanout.node_id = "fanout"
    fanout.set_params({
        "workflow": str(child_path),
        "storage_mode": "shared",
        "inputs": {"brief": "static-brief"},
    })

    probe = _CachePrefixProbe()
    probe.node_id = "probe"

    fanout >> probe

    node_configs = {
        "fanout": NodeConfig(
            node_id="fanout",
            node_type_name="WorkflowExecutor",
            template_config=None,
            batch_config=BatchConfig(
                items_template=["a", "b", "c", "d"],
                parallel=True,
                max_concurrent=4,
            ),
            namespaced=True,
            interface_metadata=None,
        ),
        "probe": NodeConfig(
            node_id="probe",
            node_type_name="_CachePrefixProbe",
            template_config=None,
            batch_config=None,
            namespaced=True,
            interface_metadata=None,
        ),
        # Never executed (not wired into the graph) — exists so the PARENT's
        # prompt-cache map is non-empty and keyed distinctly from the child's.
        "parent-llm": NodeConfig(
            node_id="parent-llm",
            node_type_name="LLMNode",
            template_config=None,
            batch_config=None,
            namespaced=True,
            interface_metadata=None,
            prewarm=True,
        ),
    }
    workflow = CompiledWorkflow(start_node=fanout, node_configs=node_configs)
    shared: dict[str, Any] = {"__registry__": registry}

    WorkflowEngine().run(workflow, shared)

    # All four shared-storage children ran their cache-block child to success.
    assert shared["fanout"]["success_count"] == 4, shared["fanout"].get("errors")
    # The probe (after the batch, same engine run) saw the PARENT's map —
    # not a child's {"child-llm"} map, not an empty leak.
    assert shared["probe"]["cache_keys"] == ["parent-llm"]
