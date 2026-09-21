# Runtime Module

Compiles workflow IR into bare nodes plus `NodeConfig`, then executes it through
`WorkflowEngine`. Normal application entry points live in `execution/runner.py`.

## Find the owner

| Task or symptom | Start here |
|---|---|
| Compilation, node loading, input defaults | `compilation/CLAUDE.md` |
| Routing, batching, caching, gates, loop execution | `engine/CLAUDE.md` |
| Template rejected before execution | `template_validation/CLAUDE.md` |
| Template resolves to the wrong value/type | `template_resolver.py::TemplateResolver` |
| Failed node appears successful or loses its output | `node_state.py` |
| Nested workflow inputs, isolation, or output exposure | `workflow_executor.py::WorkflowExecutor` |
| Persistent cache lookup/history | `cache.py::MemoizationCache` |
| Missing trace event or persistence failure | `workflow_trace.py::WorkflowTraceCollector` |
| Read a trace file | `core/trace_io.py::load_trace_file` |
| Snapshot restoration or resume refusal | `resume_source.py`; snapshot selection in `workflow_trace.py` |
| Declared output cannot resolve | `output_resolver.py::populate_declared_outputs` |
| Dry-run differs from execution | `engine/plan_node.py::plan_node`, then `execution/CLAUDE.md` → Dry-Run Planner |

Bare filenames are local. Package paths such as `core/`, `execution/`, and
`runtime/` start at `src/pflow/`; `tests/` and `architecture/` start at the repo root.

## Shared state and reserved keys

A successful node has `shared[node_id]`; a failed node has an entry in
`shared["__failures__"]` instead; neither means absent. Use `node_state`:
`get_node_status`, `get_node_output` (live OR archived data), and
`get_node_failure`. Reading only the live namespace loses failed-batch detail.

`mark_node_failed` owns failure archival and its related execution/warning
bookkeeping. Do not write parallel failure records. `clear_node_failure` is
used on loop re-entry; there is no loop-commit transaction. Initialize execution
state through `new_execution_state`, not a copied dictionary literal.

| Boundary | Owner and constraint |
|---|---|
| Execution/cache-hit state | `engine/instrumentation.py::initialize_execution_state`; engine stamps mode-specific fields |
| Runtime warnings | `core.diagnostic.normalize_runtime_warning` handles legacy shapes; `runner._extract_runtime_warnings` preserves existing `Diagnostic` objects |
| Services propagated into children | `WorkflowExecutor._PROPAGATED_KEYS`; inspect this list before adding a cross-workflow service |
| Child-local state | Execution, cache-hit, failure, template-error, and prompt-cache maps must not leak from parent to child |
| Prompt-cache render context | `engine/engine.py::build_prompt_cache_dict` and `WorkflowEngine.run` install/save/restore `__pflow_prompt_cache__` per workflow; absent restores to an empty frozen map, not `None` |

Internal `__*__` keys are reserved. The child propagation list deliberately
excludes `__failures__` and `__pflow_prompt_cache__`: parent node IDs and cache
chunks are not valid in the child's scope.

## Template resolution

`TemplateResolver` preserves values' types for simple `${var}` templates and
nested object values; complex interpolation such as `"Hello ${name}"` always
produces a string. Resolution uses the shared store. Path traversal auto-parses
JSON containers, but keeps numeric identifier strings intact. See
`architecture/core-concepts/data-type-coercion.md` for the coercion boundaries.

`$${var}` prevents resolution but retains the extra `$` in the result. Nested
index templates such as `${results[${item.index}].response}` resolve the inner
expression first; one nesting level is supported. Unresolved references remain
literal at the resolver layer; engine strict/permissive handling is separate.

Carried loop inputs must affect both resolution and cache hashing. Their shared
entry is `engine/plan_node.py::plan_node`, using
`engine/loop_control.py::carry_effective_config`; do not apply carry only at execution.

## Nested workflows

`WorkflowExecutor` owns the child boundary. Consult `ALLOWED_PARAMS` for the
accepted host parameters and `_validate_child_params` for declared-input checks.
`workflow` accepts a path or saved name; relative paths use the parent workflow
file. `_pflow_stack` and `_pflow_depth` guard cycles/depth.

Children always receive isolated storage. Declared child outputs are exposed
back through the host namespace; without declarations,
`is_exposable_child_key` governs fallback exposure, excluding internal keys and
child inputs. There is no shared-storage mode.

The compile-once cache is keyed by resolved child path, so heterogeneous batches
can reuse each distinct child. Supplied registries are intentionally reused.
Recoverable prep and exec failures honor `error_action`; `_PREP_RECOVERABLE`
excludes `CompilationError`. Broken definitions are not routable failures.
The engine's API-warning detector respects deliberate non-clean actions; see
`engine/engine.py::_CLEAN_SUCCESS_ACTIONS` before changing that boundary.

## Persistent cache

`compilation/compiler.py::_default_cache_for_node_type` owns the per-node default: LLM nodes opt
in by default; other types require `cache: true`. `MemoizationCache` stores
cross-run entries; `read_enabled=False` disables reads while allowing writes.
Engine cache application and loop exclusions are documented in the engine guide.

History lookups must carry workflow identity. `execution/runner.py::workflow_path_id`
uses the resolved file path or a synthetic `ir-hash:` identity for inline runs.
`get_latest_for_node_with_cache_key` uses an explicitly unscoped lookup when
identity is absent, which can pool unrelated nodes' history. A scoped miss does
not fall back to unscoped history.

## Traces, snapshots, and resume

Use `core.trace_io.load_trace_file` to reconstruct current marker-bearing JSONL
traces and blobs. Consumers checking the reconstructed format accept major
version 2 (`startswith("2.")`), not an exact minor version. Automatic discovery
can skip unreadable candidates; explicit `analyze-cache --from-trace` input
raises a load error instead. Do not invent a universal catch-and-skip policy.

`workflow_trace._iter_workflow_traces` excludes `only_node` traces but must not
filter `final_status`: snapshot loading and cache analysis own different status
policies, including analysis fallback to non-successful runs.

Trace disk I/O is best-effort: `_disable_streaming` retains in-memory events and
prevents persistence faults from changing execution outcomes. `finalize` closes
the stream and returns no path when persistence is disabled or has failed.
A truncated final line can reconstruct as `incomplete`; resume eligibility and
full-run snapshot eligibility are separate policies.

`WorkflowExecutor._open_child_trace` shares the run-scoped collector outside
batch items; batch items and already-buffered descendants use child buffers.
Keep that distinction when changing correlation or worker-thread tracing.

LLM trace content is canonical in `llm_prompt`/`llm_system`; redundant prompt and
system copies are stripped from persisted node output. The memo blob retains
full node output, so memo restoration and trace-based snapshot restoration are
not interchangeable. A snapshot cannot restore `${node.prompt}`/`${node.system}`
from the stripped node-output fields. See `_strip_redundant_llm_trace_fields`
and `_add_llm_data`; do not infer identical type handling for every capture path.

`final_events_by_node` owns final-state aggregation under loops. Executed counts
are per visit (excluding restored events); failed counts are per final failed
node. Synthetic warmup cost/count treatment is canonical in `engine/CLAUDE.md`
→ Synthetic Cache Warmup Item.

`load_snapshot_or_raise` selects a reusable full run for `--only` and fails loudly
when none exists. A degraded snapshot carries a warning advisory; do not restore
potentially partial upstream data silently. `resume_source.load_resume_source` owns resume selection,
gate-resolution folding, and refusal checks. `seed_snapshot_into_shared` never
seeds the target or failed-final nodes: it uses eligible events before the target
when present, otherwise all eligible captured nodes. Derive restored-node lists
from its returned map, not a second event scan. Restored nodes are successful for
data lookup but relabelled not-executed by `execution_state.build_execution_steps`.

`engine/engine.py::_prepare_resume` re-records restored upstream events as
`cached=True, restored=True`, preserving even `{}` outputs. Later resumes and
`--only` must seed from the newest eligible attempt alone; `resumed_from` is
lineage, not a data dependency.

## Declared outputs and API warnings

`output_resolver._is_all_absent_coalesce` skips a declared coalesce only when
all operands are absent. Failed/path-error operands must remain visible errors.

`engine/api_warning_detector.py::detect_api_warning` owns output classification.
Validation patterns win when they overlap resource patterns. Pass the node type:
MCP `result` wrapper inspection is type-gated for both dict and JSON-string
payloads; top-level explicit failure flags remain type-agnostic.
