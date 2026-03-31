# PocketFlow Modifications for pflow

This file documents modifications made to PocketFlow for pflow's use case.

## Task 135: Execution Core Redesign

PocketFlow was slimmed from ~200 lines (10 classes) to ~85 lines (3 classes):

**Kept**: `BaseNode`, `_ConditionalTransition`, `Node`
**Removed**: `Flow`, `BatchNode`, `BatchFlow`, `AsyncNode`, `AsyncBatchNode`, `AsyncParallelBatchNode`, `AsyncFlow`, `AsyncBatchFlow`, `AsyncParallelBatchFlow`

### Why Flow was removed

pflow's execution was built on a 4-layer wrapper chain (3,920 lines) wrapping PocketFlow's ~200-line core. The wrapper chain handled template resolution, namespacing, batch processing, and instrumentation via nested `_run()` delegation. This caused:

- Sub-workflows recompiling per batch item (O(N) at 20-50ms each)
- `initial_params` dual-data-path hacks in template resolution
- Cross-wrapper coupling via chain traversal (6 methods walking `inner_node` chains)
- 80% code duplication between sequential and parallel batch paths

The redesign replaced this with:
- **`WorkflowEngine`** (`runtime/engine/engine.py`) — handles graph traversal and all runtime concerns
- **`CompiledWorkflow`** (`runtime/engine/types.py`) — structural compilation result with per-node configs
- **`compile_workflow()`** (`runtime/compilation/compiler.py`) — produces bare nodes + configs, no wrappers

PocketFlow's `Flow._orch()` loop was the graph walker. The engine replaces it with a simpler `while curr:` loop that reads `NodeConfig` metadata instead of chain-traversing wrapper attributes. The `_orch()` hack (`if params is not None: curr.set_params(p)`) is no longer needed — the engine sets params directly.

### What nodes still use

All pflow nodes inherit from `Node` (which extends `BaseNode`). They use:
- `prep(shared)` / `exec(prep_res)` / `post(shared, prep_res, exec_res)` lifecycle
- `self.params` for configuration
- `_run(shared)` called by the engine
- `>>` and `-` operators for wiring (during compilation)
- `max_retries` / `wait` / `exec_fallback` for retry logic

### Thread safety note

`Node._exec()` uses `self.cur_retry` (instance state) for retry tracking. This is NOT thread-safe, but is safe in pflow because:
1. Sequential batch does not parallelize
2. Parallel batch deep-copies the node per thread (in `batch_executor.py`)
