# PocketFlow — Minimal Node Framework

pflow is built on **PocketFlow** (~85-line Python library in `src/pflow/pocketflow/__init__.py`).

PocketFlow provides `BaseNode` and `Node` — the lifecycle (prep/exec/post) and wiring (>>, -) primitives. The `WorkflowEngine` (in `pflow.runtime.engine`) handles graph traversal and all runtime concerns.

## What PocketFlow Provides

1. **`BaseNode`**: The building block. Operates in three steps:
   - `prep(shared)`: Read from shared store
   - `exec(prep_res)`: Execute core logic (retryable)
   - `post(shared, prep_res, exec_res)`: Write results, return action string

2. **`Node(BaseNode)`**: Adds retry logic (`max_retries`, `wait`, `exec_fallback`)

3. **Wiring operators**: `node_a >> node_b` (default edge), `node_a - "action" >> node_b` (conditional edge)

4. **Shared Store**: In-memory dict that all nodes read/write. The only communication channel.

## What PocketFlow Does NOT Provide

- **Graph traversal** — `WorkflowEngine` walks the node graph
- **Template resolution** — `engine/template_resolution.py`
- **Batch processing** — `engine/batch_executor.py`
- **Instrumentation** — `engine/instrumentation.py`
- **Namespacing** — `engine/namespaced_store.py`

These were previously in PocketFlow's `Flow` class and a 4-layer wrapper chain. Task 135 extracted them into the engine.

## Repository Structure

```
src/pflow/pocketflow/
├── __init__.py              # ~85 lines: BaseNode, _ConditionalTransition, Node
├── CLAUDE.md                # This file
├── LICENSE                  # MIT License
├── PFLOW_MODIFICATIONS.md   # History of pflow-specific changes
└── docs/                    # Upstream PocketFlow documentation (historical)
```

## All pflow nodes inherit from `Node`

```python
from pflow.pocketflow import Node  # NOT BaseNode!

class MyNode(Node):
    def prep(self, shared): ...
    def exec(self, prep_res): ...
    def post(self, shared, prep_res, exec_res): ...
```

Exception: `WorkflowExecutor` inherits from `BaseNode` (no retry — sub-workflow errors propagate directly).
