# Engine Module

`WorkflowEngine` owns graph traversal and per-node orchestration. Read
`engine.py::_execute_node` for the authoritative lifecycle; do not maintain a
second numbered pipeline here.

## Find the owner

| Task or symptom | File / symbol |
|---|---|
| Wrong successor, `--only`, or resume entry | `engine.py::route_action`, `validate_only_target`, `seed_walk_entry` |
| Cache verdict differs between plan and run | `plan_node.py::plan_node` |
| Cache application, metrics, trace, progress | `instrumentation.py` |
| Batch failure, item retries, aggregation | `batch_executor.py::execute_batch`, `_execute_batch_item`, `build_batch_output` |
| Loop conditions, caps, carried inputs | `loop_control.py` |
| Approval/escalation | `gate.py`; pause eligibility in `engine.py::_gate_pausable` and `_execute_node` |
| Parameter resolution/type conversion | `template_resolution.py::resolve_templates` |
| Structured unresolved-reference diagnostic | `template_errors.py`; upstream stderr in `error_context.py` |
| Output mistaken for an API error | `api_warning_detector.py::detect_api_warning` |
| Writes land in the wrong namespace | `namespaced_store.py::NamespacedSharedStore` |
| Compiled configuration shape | `types.py` |

## Execution and failure boundaries

State initialization and the loop guard precede the exception boundary;
planning/template resolution occur inside it so failures are traced. Escalation
detection precedes cache writes; duration must be available to cache/history
writers. Trace and completion callbacks read output before failure archival
moves it into `__failures__`. Later readers use `node_state.get_node_output`.
Recovered failures carry a warning so the runner can report DEGRADED.

Keep `record_trace(success=...)` explicit: returning an error action without
raising is still a failed event. Exception paths must complete progress as well
as record trace/metrics, or the failed node remains displayed as running.
`_handle_no_successor` must preserve an existing failure record instead of
replacing its category/data with a generic routing error.

Exception annotations cross engine → runner → formatter boundaries.
`core/exceptions.py::_PFLOW_EXCEPTION_ANNOTATIONS` lists them; use
`copy_pflow_annotations` when wrapping. `raise X from e` alone does not copy them.
Strict template failures carry partial resolutions; unresolved-reference failures
also carry a structured diagnostic. The runner preserves the shared store for
exception-path summaries.

### Gate control flow

Cache hits return before approval. On a cache miss, approval precedes the start
callback and `node.start` trace marker, so denied nodes never appear as started.

Gate exceptions bypass ordinary failure archival. A sub-workflow host must still
close the correlation frame reserved at descent. Resolver bugs are errors, not
pauses. The escalation gate runs after trace/completion and before loop re-entry.

Pause eligibility is deliberately narrow; `_execute_node` and `_gate_pausable`
are the authorities. It requires the originating `GateNotInteractiveError`, a
root/non-nested engine, no parallel batch, no `--only`, a real workflow identity
(not `ir-hash:`), and a collector. Approval is pausable; escalation additionally
requires no loop, a non-code node, a non-`end` action, and a default successor.
The runner requires tracing enabled before returning PAUSED. A usable resume
token additionally requires successful persistence; an in-memory paused stamp
alone is insufficient.

## Parameters, reuse, and templates

A `CompiledWorkflow` can be reused sequentially but is **not safe for concurrent
`engine.run()` calls**: execution mutates `node.params`. Keep per-node transient
resolution state in return values, not on the engine. `_execute_single_node`
returns `(action, last_resolutions, template_errors)` to the batch executor.

`resolve_templates` processes `inputs` first and merges their resolved values
into context before other params; static inputs also enter context. Shared
storage is the runtime source of values. Batch nodes skip top-level template
resolution so `${item}` resolves only in each item's context. Preserve source-line
metadata through `split_params`; only cache hashing filters those keys.

Strict-mode resolution attaches partial resolutions; the unresolved-reference path
also attaches a Diagnostic, while strict type mismatches do not. Permissive errors
must carry a `diagnostic` entry: `runner._extract_runtime_warnings`
skips and logs entries without one. Preserve structured per-reference data.

`--only` is snapshot execution of a flat target, not a walk through upstream
side effects. Engine and planner share target validation and seed/entry helpers.
See the parent runtime guide for seed scope and missing-snapshot behavior; resume
continues a tail whereas `--only` executes just its target. Restored data's
successful lookup status must not be changed to fix display counts. A loop target
under `--only` runs one iteration.

## Batch boundaries

`execute_batch` aggregates partial output **before** fail-fast raises. It leaves
item traces in `shared["_batch_trace"][node_id]`; the engine drains them on the
winning success or exception path. Draining inside the batch function loses
completed items when a later operation raises.

Direct batch hosts have no per-item escalation gate. Keep
`gate.scan_batch_escalations` after execution: undecided item markers fail loudly;
already-decided markers from nested workflows may pass.

`build_batch_output` is the shared runtime/planner output-shape authority.
`results` contains only successes; `errors` is the authoritative failure list
(always a list). Keep original-index attribution rather than treating filtered
result positions as original item indices. Shape coverage:
`tests/test_runtime/test_batch_output_shape.py`.

Full failed input remains in `errors[].item` internally. External renderers use
`item_summary` through `execution/formatters/batch_errors.py`, never the raw item.
Provider diagnosis can arrive as an exception attribute OR an error-shaped
result: `_build_batch_error` and `_extract_provider_message` preserve both.
`CompilationError` is fatal and never swallowed/retried by item retry handling.

Parallel execution deep-copies the bare node. Pending futures can be cancelled,
but running LLM/HTTP calls cannot be interrupted by cancelling their futures.
A ThreadPoolExecutor context manager waits for running work on exit; preserve
the explicit shutdown behavior. Shared trace-list append relies on CPython's
GIL, not a general guarantee of thread-safe shared state.

### Per-worker progress buffer

Parallel workers must not write through the shared `OutputController`: locking
individual writes cannot preserve ownership of an open partial node line.
`process_item` buffers callback transcripts locally;
`_collect_parallel_results` drains each through `_drain_worker_buffer` before
reporting item completion. Nested buffers compose until the outer calling thread
reaches the real callback. Keep the parallel no-prompt flag propagated into
nested workflows as well.

## Cache and trace integration

`plan_node` owns the shared runtime/dry-run cache verdict, including resolution
and hash inputs. Carried loop inputs enter there before resolution/hash via
`carry_effective_config`. Planner traversal is documented in
`execution/CLAUDE.md` → Dry-Run Planner; parity tests are
`tests/test_execution/test_plan_drift.py`.

`enforce_loop_guard` invalidates in-process state and clears failures on
re-entry. Memo reads skip revisited nodes, workflow hosts, and active loop scope
(including nested child nodes); error results must
not be cached. Workflow hosts' children retain their own cache opportunities.

Cache-hit traces need the same resolved `node_params` and template resolutions
as fresh traces; preserve these arguments to `handle_cached_execution`.
`instrumentation._should_write_cache_metadata` intentionally includes LLMNode
but excludes AgentNode: backend context-cache tokens describe a different cache
layer from pflow's memo keys/sources.

### Engine-injected output metadata

`instrumentation.write_memo_cache` writes historical duration in
`__pflow_stats__`; `execution/plan.py::_read_stats_from_output` reads it and must
tolerate absence. Keep the dunder name: `cache._make_serializable` replaces
dunder-keyed contents with type markers for hashing, so changing duration within
the stats dictionary does not change cache identity. The keys themselves are not
simply omitted.

`apply_memo_hit` strips stats/warning metadata from live node output and restores
warnings through their root channel. Otherwise fresh and cached shared stores
differ. Nodes must not write the engine-owned metadata keys.

### Synthetic Cache Warmup Item

`batch_executor._execute_synthetic_warmup` records real provider usage as a
synthetic item with `llm_call.is_warmup=True`. Include it in cost/token totals;
exclude it from ordinary call counts, per-call averages, and discrepancy checks.
For consumers, start at `WorkflowTraceCollector.collect_llm_calls`,
`core/metrics.py`, and `core/prompt_cache_analysis/trace_loading.py`; preserve the
flag when flattening traces. Do not treat a warmup as free because it is not a
user item.

## Namespace and import boundaries

`NamespacedSharedStore` eagerly creates the node namespace; a failure before any
write legitimately archives `{}`. Special `__*__` keys bypass namespacing.
Mapping mixins route `update/get/pop/setdefault` through the proxy primitives;
do not add a bypass for convenience.

### Cross-Module Dependencies

Keep the engine → LLM adapter edge lazy. A function needing
`core.llm_client` may import it locally; module-level imports are constrained by
`tests/test_import_hygiene.py::test_module_level_llm_client_imports_are_allowlisted`.
Use that test for the current allowlist rather than copying it here.
