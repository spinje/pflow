# Execution Module

CLI and MCP share `WorkflowRunner` for resolution, validation, compilation,
execution, resource cleanup, and structured results.

## Find the owner

| Task or symptom | File / symbol |
|---|---|
| Run, validate, or plan a workflow | `runner.py::WorkflowRunner` |
| File/library/markdown/dict source resolution | `workflow_resolver.py::resolve_workflow` |
| Configuration/result/plan data types | `result.py` |
| Wrong failure diagnostic/category | `executor_service.py::build_error_list`, `determine_error_category` |
| Wrong per-node summary status | `execution_state.py::build_execution_steps` |
| Dry-run cache/cost/routing prediction | `plan.py`; see Dry-Run Planner below |
| Resume refused before execution | `resume_preflight.py::preflight_resume` |
| Gate prompt or answer rendering | `gate_prompt.py::build_gate_resolver`, `can_prompt`, `format_gate_lines` |
| Text/JSON/MCP presentation | `formatters/CLAUDE.md` |

CLI integration is in `cli/commands/run.py`; MCP integration is in
`mcp_server/services/execution_service.py` (paths relative to `src/pflow/`).

## Runner and resolver boundaries

`ResolvedWorkflow.ir` is already file-resolved. The runner does not resolve it
again. Inline sources (dict or markdown content) reject file references because
there is no source directory; `_check_inline_file_references` lives in the
resolver, not the runner. See `tests/test_execution/test_workflow_resolver_contract.py`.

Keep resources in `run` scope so its `finally` can always clean them up, including
MCP subprocesses. `run` converts exceptions into `ExecutionResult`, while
KeyboardInterrupt/SystemExit propagate. Planning shares resolve/validate/compile
but does not create execution resources or invoke nodes.

`_compile_and_execute` annotates exceptions with the shared store, and
`_exception_to_result` transfers it to `ExecutionResult.shared_after`. Losing this
chain hides failed-node/batch details from every consumer. `OutputResolutionError`
is excluded from stale failed-node attribution: its Diagnostic has `node_id=None`
because an output declaration failed after execution.

`_extract_runtime_warnings` passes existing `Diagnostic` objects through intact,
including permissive template errors with per-reference structure. Do not replace
them with regex classifications or canned suggestions. `executor_service` uses
structured failure categories first; message regexes are legacy fallback.

`workflow_path_id` gives file/library runs a resolved path and inline runs an
`ir-hash:` identity. Keep this identity on cache-history writes/lookups. Absent
identity requests an unscoped history lookup and can mix unrelated nodes;
a scoped miss does not fall back to unscoped history.

## Gate and resume adapters

Runner/planner/runtime remain presentation-independent; `gate_prompt.py` is the
intentional Click adapter. `can_prompt` requires stdin and stderr TTYs and no
print mode. Stdout need not be a TTY, so piping workflow output must not disable
an otherwise answerable prompt. Parallel workers inherit the no-prompt flag.

Pause eligibility belongs to `runtime/engine/engine.py::_execute_node` and
`_gate_pausable`, documented in `runtime/engine/CLAUDE.md` → Gate control flow.
Tracing alone does not make a gate resumable. Denial, resolver failure, and durable
pause have different result statuses; a usable token also requires persistence.

`preflight_resume` owns load/staleness/entry checks and returns a side-effect
refusal for the caller to enforce. Dry-run still checks stale workflow identity
but must not require side-effect confirmation. Callers own settings-env injection
and compilation; preflight does neither.

## Dry-Run Planner

`plan.py::build_plan` describes cached versus would-execute work without invoking
node side effects. Start with its module invariants and this routing map:

| Change | Owner |
|---|---|
| Per-node cache verdict, resolution, hash inputs | `runtime/engine/plan_node.py::plan_node` (shared with runtime) |
| Follow/stop/boundary/routing-error decision | `plan.py::_classify`; shared `runtime/engine/engine.py::route_action` |
| Execute-entry historical stats | `_execute_entry`, `_lookup_last_run_stats` |
| Child workflow/batch planning | `_plan_sub_workflow`, `_plan_batch_sub_workflow` |
| Approval/loop metadata on entries | `_annotate_entry` |
| Cross-item synthetic entries | `_aggregate_batch_child_plans` |
| Cost/duration/nested totals | `_summarize` |
| Rendering | `formatters/plan_formatter.py` |

The planner hydrates its own scratch store on memo hits and uses the engine's
loop guard before planning a node. Omitting either changes downstream resolution
or revisit cache verdicts. After the first miss it explores **all non-error
successors**, not only default routes; a cached action with no valid route must
surface an error. Keep these semantics aligned through
`tests/test_execution/test_plan_drift.py` and `test_plan_classify.py`.

`--only` shares target validation and snapshot seeding with runtime and plans just
the flat target; missing snapshots fail loudly. Resume uses the same seed/entry
composition but plans the whole resumed tail. Seed scope and failed-final-node
exclusion are owned by `runtime/resume_source.py::seed_snapshot_into_shared`.

After a miss, ordinary child workflows still recurse in force-downstream mode;
making them leaves hides nested cost. Keep first-miss and BFS execute entries on
`_execute_entry` so downstream history is not lost.

Preserve these estimation limits when changing recursion/aggregation:

- A downstream batch sub-workflow is opaque when its item count cannot be known;
  one child traversal would silently underestimate the batch. Normal child input
  absence is an error; type-shaped placeholders are downstream-only.
- Batch child entries group by node ID, not list position, since items can take
  different branches. Counts use items that actually traversed each node.
  A synthetic entry's nested `sub_plan` is the first traversing item's view;
  its aggregate summary has broader coverage than the displayed nested tree.
- `_annotate_entry` skips approval on cache hits because runtime does not gate
  those hits. Synthetic entries are newly constructed, so flags such as approval
  must be forwarded explicitly by `_aggregate_batch_child_plans`.
- Loops are planned once then costed using their resolved iteration cap as an
  upper bound. Consumers gating on cost/time need `*_including_nested` totals
  when present, not just the current level.

Historical duration comes from engine-owned cache metadata; see
`runtime/engine/CLAUDE.md` → Engine-injected output metadata. Do not duplicate
cache-key computation or batch output shape in planner branches.

## Summary data is not display text

`build_execution_steps` uses `node_state` for status and failed output, not the
singular `failed_node` pointer that loses earlier failures. Restored snapshot
nodes are relabelled not-executed here while remaining successful for data lookup.
In-process step rows can contain full failed inputs; external formatters must use
`formatters/batch_errors.py` summaries rather than print raw batch items.
