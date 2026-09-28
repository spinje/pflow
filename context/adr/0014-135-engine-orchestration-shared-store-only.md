# Runtime concerns live in the engine over bare nodes; the shared store is the only runtime data carrier

Status: accepted

Task 135 replaced the four-layer wrapper chain (template, namespace, batch, instrumented wrappers
around PocketFlow's `Flow._orch()`) with direct orchestration: `compile_workflow()` returns a
`CompiledWorkflow` of **bare** `BaseNode`/`Node` instances plus per-node `NodeConfig`, and
`WorkflowEngine` walks the graph and applies every runtime concern — template resolution,
namespacing, caching, tracing, batch iteration, progress — itself, as plain functions with
explicit parameters (`runtime/engine/template_resolution.py`, `runtime/engine/instrumentation.py`,
`runtime/engine/batch_executor.py`). Wrappers are the pattern for adding behavior to code you
cannot modify; pflow owns the node contract, the compiler, the execution loop and every node, so
the indirection bought nothing and cost chain-traversal coupling and `copy.copy()` gotchas.

The same task made the **shared store the single source of runtime data**. The old wrapper built
its resolution context as `dict(shared)` overlaid with `initial_params`, so compile-time params
always beat runtime values; that conflation of compiled structure with runtime state was the root
of every prior hack (the `_orch()` param-overwrite patch, `PflowBatchNode` re-implementing
BatchFlow, per-item sub-workflow recompilation). Now `resolve_templates()` reads `dict(shared)`
only, the runner seeds CLI params and then `workflow.resolved_defaults` into the shared store
(`WorkflowRunner` in `execution/runner.py`), and a child seeds its absent defaults and then its
per-item params into `child_storage` (`WorkflowExecutor.exec`). The workflow compiles once and a
sub-workflow compiles once per path (`WorkflowExecutor._compile_sub_workflow`). `compile_workflow`
still accepts `initial_params`, but only for input preparation (`prepare_inputs`), the workflow
file's base directory (`_pflow_workflow_file`) and the `__template_resolution_mode__` flag —
never as values that templates resolve against.

## Considered options

1. **Fix the data model only** — drop the `initial_params` override, keep the wrappers. Smallest
   change and it unblocks compile-once, but leaves ~3,900 lines of wrappers with their
   cross-wrapper coupling. Rejected.
2. **Slim PocketFlow and fix the data model** (with or without decomposing batch out of the
   wrappers). Cleaner primitives, but the wrapper complexity is unchanged; every option that kept
   the wrapper chain was rejected for the same reason.
3. **Full execution-engine rewrite, node lifecycle included.** Cleanest linear execution, but it
   changes the `BaseNode` contract and every node with it — massive risk for no gain, since every
   node already follows one contract (read `self.params` in `prep()`, write `shared` in `post()`).
   Rejected.
4. **Orchestration-level concerns in the engine, `BaseNode`/`Node` unchanged** (chosen). Linear
   execution, nodes untouched, and compile-once falls out naturally because nothing runtime is
   baked into the compiled graph. It subsumed Task 140 (wrapper refactoring), which targeted the
   same code.

## Consequences

- **No per-node state on the engine instance.** Parallel batch hands `_execute_single_node` to
  `execute_batch`, whose worker threads share one engine, so a field like
  `self._last_resolutions` is a data race; a per-node result travels in the method's return value
  instead (operational rule: "Parameters, reuse, and templates" in
  `src/pflow/runtime/engine/CLAUDE.md`).
- **Do not reintroduce `initial_params` (or any compile-time channel) as a runtime data carrier.**
  It is the conflation this decision removed; a value a template needs belongs in the shared store.
- **Per-item input coercion is lost (#188).** The old model ran `prepare_inputs()` per batch item
  via recompilation, coercing `"7"` to `7` for int-typed inputs. Under compile-once a cached child
  reuses the first item's `resolved_defaults`, which `WorkflowExecutor.exec` seeds only for keys
  absent from `child_params` (so one item's coerced values never leak into the next), and
  `child_params` arrive uncoerced. Declared numeric sub-workflow inputs fed per item can therefore
  reach the child as strings.
- Tests that asserted `initial_params` priority described removed behavior; their replacements
  assert that defaults flow through the shared store.
