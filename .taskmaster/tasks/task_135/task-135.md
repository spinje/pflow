# Task 135: Execution Core Redesign — Orchestration Engine

## Description

Redesign pflow's execution core by replacing the 4-layer wrapper chain with an orchestration engine that handles all runtime concerns (template resolution, namespacing, caching, tracing, batch iteration) directly during graph traversal. Slim PocketFlow to the ~30 lines pflow actually uses. Make shared store the single source of runtime data, eliminating the `initial_params` dual-data-path. Compile-once falls out naturally from this design — compiled workflows are structural and immutable, runtime data flows through the shared store.

This task subsumes Task 140 (Wrapper Chain Refactoring). Both tasks target the same code, solve the same root problem, and the orchestration approach addresses both compile-once and wrapper complexity in a single pass.

## Status

done

## Completed

2026-03-31

## Priority

high

## Depends On

Task 138 (Shared Execution Pipeline) — completed. Created the single compilation callsite and clean Runner contract that makes this redesign safe.

## Problem

pflow's execution core conflates the compiled graph with runtime state. Every hack in the system traces back to this:

### The Hack Chain

1. **`initial_params` bakes runtime data into compiled nodes.** Per-item batch values and CLI inputs are stored in `TemplateAwareNodeWrapper.initial_params` at compile time, making the compiled graph non-reusable.

2. **`_build_resolution_context()` overrides shared store with `initial_params`.** Because runtime data was baked into the compiled graph, template resolution had to prefer `initial_params` over the shared store (`context.update(self.initial_params)`).

3. **`_orch()` hack guards `set_params()`.** Because params were baked at compile time, PocketFlow's orchestration-time `set_params()` had to be disabled (`if params is not None: curr.set_params(p)`) to prevent overwriting them.

4. **`PflowBatchNode` reimplements `BatchFlow`.** Because the `_orch()` hack blocks PocketFlow's `BatchFlow`, pflow built its own batch system from scratch.

5. **Sub-workflows recompile per batch item.** Because `initial_params` contains per-item data, the entire flow graph is rebuilt for every batch item (measured: 20-50ms per compilation, O(N) scaling).

### The Wrapper Chain (3,920 lines wrapping 205 lines of PocketFlow)

Cross-cutting concerns are baked into 4 wrapper layers on each node:

```
InstrumentedNodeWrapper (810 lines, 6+ concerns)
  PflowBatchNode (1,034 lines)
    NamespacedNodeWrapper (94 lines)
      TemplateAwareNodeWrapper (710 lines)
        ActualNode
```

Problems: InstrumentedNodeWrapper is a god class. Cross-wrapper coupling via chain traversal (InstrumentedWrapper reads TemplateWrapper's `last_resolutions` and BatchNode's `_trace_items` by walking the chain). `_exec_single`/`_exec_single_with_node` are 80% duplicated (170 lines). `copy.copy()` in `_orch()` creates shared-inner-wrapper instances. Every new feature must navigate 4 layers of delegation to find where to hook in.

### PocketFlow Underutilization

Of PocketFlow's ~200 lines, pflow uses ~50: `BaseNode` (lifecycle), `Node` (retry), `Flow` (graph traversal). `BatchFlow`, `BatchNode`, all async variants — zero usage. `Flow` is never subclassed, only instantiated once and monkey-patched.

## Solution

### Core Principle

**Separate the compiled graph from the execution engine.**

The compiled graph is pure structure: bare nodes (just prep/exec/post), edges, per-node configuration. Immutable after compilation.

The execution engine walks the graph and handles all runtime concerns: template resolution, namespacing, caching, tracing, batch iteration, progress callbacks.

```
Compilation: IR --> CompiledWorkflow(nodes, edges, node_configs)
                    ^ structural, immutable, reusable

Execution:   CompiledWorkflow + shared_store --> result
              ^ runtime concerns applied by the engine
```

### What Changes

**PocketFlow** (~30 lines): Slim to `BaseNode` (prep/exec/post lifecycle, successors, `>>` and `-` operators), `_ConditionalTransition` (5 lines, required by `-` operator for conditional edge wiring: `source - "action" >> target`), and `Node` (adds retry). Remove `Flow`, `BatchFlow`, `BatchNode`, all async variants, the `_orch()` hack, `copy.copy()` during traversal.

**Compiler** produces a `CompiledWorkflow`:
- Bare node instances (no wrapper chain)
- Per-node config: templates, static params, batch config, namespace flag, interface metadata
- Graph structure: nodes with successors (edges wired as before)

**Execution engine** (`PflowFlow` or similar):
- Walks the graph node-by-node, following successor edges based on action strings returned by `node.post()`
- At each node: check cache, resolve templates, set up namespaced store, handle batch if configured, call `node._run()`, record trace/metrics
- Warns when a node returns an action that doesn't match any successor edge (replicates `Flow.get_next_node()` debug warning — useful for workflows with unexpected action strings)
- All concerns are sequential function calls in the engine, not nested wrapper delegation
- Shared store is the single source of runtime data — no `initial_params` override
- `only_node` is an engine parameter — engine stops traversal after target node (replaces `_apply_only_node_stop` monkey-patch)
- Output resolution is an engine post-execution step — `CompiledWorkflow` carries the outputs section from IR (replaces `_apply_run_hooks` monkey-patch)

**Template resolution** becomes a standalone function called by the engine. `_build_resolution_context()` is just `return dict(shared)` — no override. The engine resolves templates once per node and uses the result for both cache key computation and param setting. This eliminates the current double-call pattern (InstrumentedNodeWrapper calls `resolve_templates()` for the cache key, then TemplateAwareNodeWrapper calls it again for execution — a workaround for shared-wrapper-instance state leakage that doesn't exist in the new model).

**Namespacing** uses the existing `NamespacedSharedStore` proxy, created by the engine per-node instead of by a wrapper.

**Batch iteration** handled by the engine (or a batch executor function). Unifies the duplicated `_exec_single`/`_exec_single_with_node` paths. Sequential: same node, different shared store per item, no deep copy. Parallel: deep copy bare node per thread (cheap — nodes are trivially copyable).

**Instrumentation concerns** (caching, tracing, metrics, progress callbacks, loop guards, API warning detection) are standalone functions called by the engine pre/post node execution.

**`prepare_inputs()` split for compile-once.** Currently `prepare_inputs()` does both structural validation (IR shape, data flow) and input value resolution (5-tier defaults, type coercion, required-input checking) in one pass. For compile-once, these separate: structural validation runs at compile time, input value resolution runs at execution time — in the Runner for top-level workflows, or in WorkflowExecutor for sub-workflows. This is what enables compiling without per-item data.

**Compile-once** is a natural property: `WorkflowExecutor` caches the compiled sub-flow on first call, reruns with different shared stores per batch item.

### What Stays

- `BaseNode` and `Node` — prep/exec/post lifecycle, retry. All 28 production nodes unchanged.
- `NamespacedSharedStore` — proxy class, created by engine instead of wrapper.
- `WorkflowRunner` contract — calls compile + execute, gets `ExecutionResult`.
- Shared store key contract — engine writes the same keys wrappers currently write.
- All node implementations — they read `self.params` in `prep()`, write to `shared` in `post()`. Engine sets `node.params` to resolved values before calling `_run()`.
- Batch features: parallel execution, retry, error handling (fail_fast/continue), tracing.
- The 4 batch error handling fixes: CompilationError propagation, structured error display, all-fail abort, empty batch warning.

## Verified Facts (from exploration phase)

### PocketFlow Usage
- `BaseNode`: inherited by `WorkflowExecutor` and all nodes (via `Node`)
- `Node`: inherited by all 28 production nodes + `PflowBatchNode`
- `Flow`: instantiated once at `compiler.py:768`, never subclassed, monkey-patched twice
- `BatchFlow`, `BatchNode`, async variants: zero application usage

### Node Contract
- Every production node reads `self.params.get(...)` exclusively in `prep()`
- No production node reads `shared` for parameters (only infrastructure keys like `__mcp_pool__`)
- `exec()` receives only `prep_res` — fully decoupled from params and shared store
- All outputs written to `shared` in `post()`

### Deep Copy Safety
- Every node's `__init__` just calls `super().__init__(max_retries=N, wait=N)` plus trivial attributes
- No node holds connections, file handles, or heavy state
- No node overrides `__copy__` or `__deepcopy__`
- Sequential batch: no deep copy needed (nodes effectively stateless)
- Parallel batch: deep copy bare node per thread (sub-millisecond)

### Blast Radius
- Zero wrapper class imports in `cli/`, `execution/`, `mcp_server/` production code
- External coupling is exclusively through shared-store key conventions
- Only 4 test files outside `test_runtime/` import wrapper classes
- Template validation has a `BATCH_OUTPUTS` data shape contract with batch output structure

### Shared Store Contract (engine must maintain)

Keys the engine writes:
| Key | Type | Purpose |
|-----|------|---------|
| `__execution__` | dict | Node completion, failure tracking, visit counts, `--only` metadata |
| `__cache_hits__` | list[str] | Which nodes served from memo cache |
| `__warnings__` | dict[str,str] | API warnings + batch warnings -> DEGRADED status |
| `__template_errors__` | dict[str,dict] | Permissive mode template failures |
| `shared[node_id]` | dict | Namespaced node outputs |
| `_batch_trace` | dict[str,list] | Transient batch item trace events |

Batch-local keys (per-item copies only):
| Key | Purpose |
|-----|---------|
| `shared[item_alias]` | Current batch item value |
| `__index__` | 0-based batch item index |

Keys seeded by Runner (engine reads):
| Key | Purpose |
|-----|---------|
| `__progress_callback__` | Progress reporting |
| `__memoization_cache__` | Cross-run node output cache |
| `_pflow_depth` | Nesting depth for callback indentation |
| `_pflow_workflow_file` | Memo cache metadata |

### InstrumentedNodeWrapper Cross-Wrapper Coupling
- 6 chain traversal methods search inner wrappers by string class name
- Reads `TemplateAwareNodeWrapper.last_resolutions` for trace recording
- Reads `PflowBatchNode._trace_items` for batch trace aggregation
- Reads `WorkflowExecutor._child_trace_events` for sub-workflow traces
- All of this becomes unnecessary when the engine has direct access to all data

### Flow Monkey-Patches
- `_apply_run_hooks`: resets visit counts, populates declared outputs after execution, stores `--only` metadata
- `_apply_only_node_stop`: terminates flow after target node for `--only` flag
- Both close over `ir_dict` — the only place IR survives past compilation
- Both become engine responsibilities in the new model

## Design Decisions

- **Orchestration engine, not wrapper chain.** Wrappers solve "add behavior to components you can't modify." pflow controls everything — framework, compiler, execution loop, nodes. Direct orchestration is the natural pattern.
- **Shared store is the single source of runtime data.** No `initial_params` override. Template resolution reads from shared store only.
- **PocketFlow is slimmed, not removed.** `BaseNode` (lifecycle) and `Node` (retry) stay — all 28 nodes inherit from them. `Flow` and everything above it is replaced by the engine.
- **Nodes don't change.** The engine sets `node.params` to resolved values before calling `_run()`. All existing nodes work as-is.
- **Batch features preserved, implementation simplified.** Parallel execution, retry, error handling, tracing — all stay. The duplicated `_exec_single`/`_exec_single_with_node` paths merge into one.
- **WorkflowExecutor handles its own compile-once caching.** The engine treats it like any other node. WorkflowExecutor caches the compiled sub-flow internally.
- **`CompiledWorkflow` carries output declarations.** Currently `_apply_run_hooks` closes over `ir_dict` for `populate_declared_outputs()`. The engine needs this — the outputs section (and any other IR data needed post-compilation) is stored in `CompiledWorkflow`, not lost after compilation.

## Scope

### In Scope
- Rewrite PocketFlow `__init__.py` to ~30 lines (BaseNode + Node only)
- New execution engine replacing `Flow._orch()` + wrapper chain
- Compiler produces `CompiledWorkflow` (bare nodes + config) instead of wrapped `Flow`
- Remove `initial_params` as runtime data carrier
- Remove all 4 wrapper files (template, namespace, batch, instrumented)
- Extract concern logic from wrappers into standalone functions
- WorkflowExecutor compile-once for sub-workflows
- Unified batch execution (merge duplicated paths)
- Update Runner to use new compilation/execution interface
- Update all affected tests

### Out of Scope
- Async execution (not currently used)
- New features (approval gates, execution preview, etc.)
- Error hierarchy changes (GitHub issue #184)
- Child workflow compilation warning surfacing (can be added to engine later)

## Subsumes

- **Task 140** (Wrapper Chain Refactoring) — the wrapper chain is abolished, not refactored. All Task 140 workstreams are addressed:
  - A (Split InstrumentedNodeWrapper): concerns become engine functions
  - B (Unify batch execution paths): single execution path in engine
  - C (Shared wrapper base): no wrappers, no base needed
  - D (Child workflow warnings): deferred, can be added to engine later

## Constraints

- All existing test assertions on behavior must pass (tests on wrapper internals will be rewritten)
- The 4 batch error handling fixes continue working: CompilationError propagation (#153), structured error display (#154), all-fail abort (#157), empty batch warning (#160)
- `WorkflowRunner` external contract unchanged — callers still get `ExecutionResult`
- Shared store key contract preserved — formatters/display code reads the same keys
- No node implementation changes — `self.params` in `prep()`, `shared` writes in `post()`

## Verification

- Compilation overhead for batched sub-workflows is O(1) not O(N)
- `initial_params` no longer carries runtime data — shared store is the single source
- No wrapper chain — concerns are in the engine
- All existing integration tests pass
- Shared store keys match current contract (same keys, same values, same timing)
- Batch error handling preserved (CompilationError propagation, all-fail abort, empty batch warning)
- Sequential batch: zero deep copies
- Parallel batch: deep copy bare nodes only (measure and verify sub-millisecond)

## Key Files

### To Rewrite
- `src/pflow/pocketflow/__init__.py` — slim to BaseNode + Node (~30 lines)
- `src/pflow/runtime/compilation/compiler.py` — produce CompiledWorkflow instead of wrapped Flow

### To Create
- Execution engine (new file) — graph traversal + all runtime concerns
- `CompiledWorkflow` type — bare nodes + per-node config

### To Remove
- `src/pflow/runtime/wrappers/instrumented_wrapper.py` (810 lines)
- `src/pflow/runtime/wrappers/template_wrapper.py` (710 lines)
- `src/pflow/runtime/wrappers/batch_node.py` (1,034 lines)
- `src/pflow/runtime/wrappers/namespaced_wrapper.py` (94 lines)

### To Extract (logic from wrappers into standalone functions)
- Template resolution logic (from template_wrapper.py)
- Batch execution logic (from batch_node.py), including `resolve_batch_items()` (lines 91-119) — a standalone function also used by InstrumentedNodeWrapper for cache key computation; must survive batch_node.py deletion
- Instrumentation logic: caching, tracing, metrics, progress, loop guards, API warnings (from instrumented_wrapper.py)

### To Update
- `src/pflow/execution/runner.py` — call new compile/execute interface
- `src/pflow/runtime/workflow_executor.py` — add compile-once caching
- `src/pflow/runtime/compilation/compile_validation.py` — split prepare_inputs for compile-once
- `src/pflow/pocketflow/PFLOW_MODIFICATIONS.md` — document the redesign rationale

### To Keep (and relocate from `wrappers/`)
After removing the 4 wrapper files, the `wrappers/` directory name is misleading. These standalone utilities survive the redesign and should move to better homes:
- `namespaced_store.py` — NamespacedSharedStore proxy (used by engine) → `runtime/`
- `api_warning_detector.py` — already standalone functions → `runtime/` or alongside engine
- `template_errors.py` — already standalone functions → `runtime/` or alongside template resolver
- `error_context.py` — already standalone functions → `runtime/`

### To Keep As-Is
- `src/pflow/runtime/template_resolver.py` — template resolution engine
- All node implementations under `src/pflow/nodes/`

## References

- Task 138 review: `.taskmaster/tasks/task_138/task-review.md`
- Task 140 spec: `.taskmaster/tasks/task_140/task-140.md` (subsumed by this task)
- PocketFlow modifications: `src/pflow/pocketflow/PFLOW_MODIFICATIONS.md`
- Wrapper architecture: `src/pflow/runtime/wrappers/CLAUDE.md`
- Batch error handling session: `.taskmaster/tasks/task_135/starting-context/braindump-batch-error-handling-session.md`
- Architectural audit: `.taskmaster/tasks/task_135/starting-context/braindump-architectural-audit-findings.md`
- Task 138 handoff: `.taskmaster/tasks/task_135/starting-context/braindump-task138-handoff.md`
- GitHub issues: #153, #154, #155, #157, #159, #160
