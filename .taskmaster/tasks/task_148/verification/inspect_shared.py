"""Verification harness: run a workflow file and dump the final shared store.

Used to verify the Task 148 invariant that:
    shared[node_id]            ↔ node_id ran successfully
    shared["__failures__"][id] ↔ node_id executed and failed
    neither                    ↔ node_id did not execute
"""

from __future__ import annotations

import sys

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


def run_and_dump(path: str) -> None:
    runner = WorkflowRunner()
    config = RunnerConfig(cache_enabled=False, trace_enabled=False)
    result = runner.run(path, params={}, config=config)

    print("=" * 60)
    print(f"WORKFLOW: {path}")
    print("=" * 60)
    print(f"final_status: {getattr(result, 'status', '?')}")
    print()
    shared = result.shared_after
    print("=== Top-level shared keys ===")
    print(sorted(shared.keys()))
    print()
    print("=== __failures__ ===")
    failures = shared.get("__failures__", {})
    for node_id, record in failures.items():
        print(f"  [{node_id}]")
        print(f"    category: {record.get('category')}")
        print(f"    error: {record.get('error', '<none>')[:120] if record.get('error') else '<none>'}")
        data = record.get("data", {})
        if isinstance(data, dict):
            print(f"    data keys: {list(data.keys())}")
            for k, v in data.items():
                sv = repr(v)[:100]
                print(f"      {k}: {sv}")
    print()
    print("=== Per-node presence ===")
    exec_state = shared.get("__execution__", {})
    completed = set(exec_state.get("completed_nodes", []))
    failed_node = exec_state.get("failed_node")
    print(f"  completed_nodes: {sorted(completed)}")
    print(f"  failed_node: {failed_node}")
    print()
    print("=== Invariant check ===")
    user_keys = [k for k in shared if not (k.startswith("__") and k.endswith("__"))]
    for k in user_keys:
        in_failures = k in failures
        print(f"  {k}: in shared (top-level), in __failures__={in_failures}")
        if in_failures:
            print("    *** INVARIANT VIOLATION: node in BOTH shared and __failures__")
    for k in failures:
        if k in shared and not (k.startswith("__") and k.endswith("__")):
            pass  # Already reported above
        else:
            print(f"  {k}: ONLY in __failures__ (correct for failed node)")


if __name__ == "__main__":
    run_and_dump(sys.argv[1])
