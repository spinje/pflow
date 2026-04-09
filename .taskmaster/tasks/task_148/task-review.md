# Task 148 Review: Failed-Node Invariant Fix and Template Error UX Consolidation

## Metadata

- **Implementation date**: 2026-04-06 (original implementation) → 2026-04-07 (five review passes)
- **Branch**: `fix/resolve-coalesce-empty-string`
- **Original bug**: [GH #208](https://github.com/spinje/pflow/issues/208) — `??` coalesce operator silently resolved to empty string instead of falling through
- **Follow-up issues filed**: spinje/pflow#233, #234, #235, #240, #241, #246, #247, #248, #249, #250
- **Commits**: `0629df6a` (full implementation), `0ea3642d` (post-implementation regressions). Five review passes are uncommitted.

## Executive Summary

Task 148 corrected pflow's shared-store invariant so failed nodes no longer leak data into downstream template resolution. It moved failed-node data from `shared[node_id]` to `shared["__failures__"][node_id]`, unified scattered failure bookkeeping behind `runtime/node_state.py`, and rewrote the template error pipeline to produce structured `Diagnostic` objects with per-reference classification and paste-able fix suggestions. Five post-implementation review passes then found and fixed 15 additional bugs — most of them failures at layer boundaries where one component's output became the next component's input.

## Implementation Overview

### What Was Built

**Core invariant change** — the single load-bearing primitive:

```
shared[node_id]            ↔  node executed successfully
shared["__failures__"][id] ↔  node executed and failed
neither key present        ↔  node did not execute
```

A node is NEVER in both places simultaneously. The move happens at a new "step 17.5" in `WorkflowEngine._execute_node`, running AFTER `record_trace`, `call_completion_callback`, and `enrich_llm_cost` so those consumers see the data in its original location before it's archived.

**New module `runtime/node_state.py`** (184 lines, zero external deps beyond the enum):

```python
class NodeStatus(Enum): ABSENT | SUCCEEDED | FAILED
FAILURE_CATEGORY_SHELL = "shell_failure"
FAILURE_CATEGORY_NODE_ERROR = "node_action_error"
FAILURE_CATEGORY_API_WARNING = "api_warning"
FAILURE_CATEGORY_ROUTING = "routing_error"
FAILURE_CATEGORY_EXCEPTION = "exception"
FAILURE_CATEGORY_TEMPLATE = "template_error"

get_node_status(shared, node_id) -> NodeStatus  # failures wins over shared
get_node_output(shared, node_id) -> Optional[dict]  # succeeded OR failed data
get_node_failure(shared, node_id) -> Optional[dict]  # full failure record
node_succeeded(shared, node_id) -> bool
mark_node_failed(shared, node_id, *, category, error=None, warning=None)  # SINGLE WRITE SITE
clear_node_failure(shared, node_id)  # loop re-entry
```

**All 5 failure paths now funnel through `mark_node_failed`**:
1. `cache_result` when node returned action starting with `"error"` — handled at step 17.5 in `engine.py:326-347`
2. `handle_api_warning` when API warning detector triggered — `instrumentation.py:469-520`
3. `_handle_no_successor` when action has no matching edge — `engine.py:111-152` (with post-review Fix #2 guard)
4. `_execute_node` except block when node raised — `engine.py:351-398`
5. Exception propagation into `_exception_to_result` now threads `shared_store` via `_pflow_shared_store` annotation (post-review Fix #5)

**Template error rewrite** — replaced the text-blob `build_enhanced_template_error` with `build_template_error_diagnostic` returning a fully-structured `Diagnostic`. The rich data lives in `context.unresolved_references` as a list of per-variable dicts with `status` (absent/succeeded/failed/path_error), `failure` (category/error/data), `peer_suggestions`, `secondary_hint`, `did_you_mean`. The renderer in `core/diagnostic.py` produces agent-actionable text; JSON/MCP consumers get the same structure via `Diagnostic.to_dict()`.

**Source line tracking end-to-end** — markdown parser tracks `yaml_item_lines` parallel list during output parsing → `_build_output_dict` records `_source_line` → schema allows it → `output_resolver._record_output_failure` propagates it → `OutputResolutionError.to_diagnostics` threads it into context → `_format_location` renders `file:line`.

### Implementation Approach

The original Task 148 braindump captures four reframing rounds before the approach crystallized. The critical insight: **fix the invariant, don't patch the symptom**. Earlier drafts had `resolve_coalesce` consult `__execution__["completed_nodes"]` directly, which leaves the broken invariant in place and requires every future consumer to know about the side channel. Fixing the invariant once is simpler than patching every consumer forever.

Second critical insight from the post-review passes: **fix the layer, not the surface**. Almost every bug found in the review was at a boundary where one layer's output became another layer's input without a consistency check. The pattern:
- Fix #1: `OutputResolutionError.to_diagnostics` produced legacy prose AND new structured context AND canned suggestions → triple-rendered
- Fix #2: Step 17.5 archived, then `_handle_no_successor` archived again, silently overwriting
- Fix #5: Exception path produced rich `__failures__` data, `_exception_to_result` dropped it
- Fix #6 / Test B: Pass-through structured diagnostic to permissive warnings, renderer silently ignored for WARNING severity
- A2: Batch `_aggregate_batch_results` raised before writing `shared[node_id]` → step 17.5 archived empty data

Every one of these is "component A produces X, component B silently ignores or overwrites X". The tests that caught them were all end-to-end through the public `WorkflowRunner` API — unit tests that mocked the boundary in question passed while the real pipeline broke.

## Files Modified/Created

### Core Changes

**New**:
- `src/pflow/runtime/node_state.py` — canonical primitive for node state queries and failure bookkeeping. The `mark_node_failed` function is the **single write path** for `__failures__`. Any code that writes to `__failures__[node_id]`, `failed_node`, or `__warnings__[node_id]` directly is a contract violation.

**Engine orchestration** (`src/pflow/runtime/engine/`):
- `engine.py` — step 17.5 archive hook at line 326-347; exception path archive at 378-398; `_handle_no_successor` has post-review guard at 111-152 that preserves existing failure records instead of double-archiving
- `instrumentation.py` — `handle_api_warning` archives via `mark_node_failed` at end; `enforce_loop_guard` clears stale `__failures__` on revisit (lines 77-79); `cache_result` is a no-op for error actions post-B5 cleanup (line 106-115); `handle_cached_execution` defensively clears `__failures__` before restoring cached output (post-review D4)
- `template_errors.py` — FULL REWRITE. New functions: `classify_unresolved_references`, `build_template_error_diagnostic`, `_classify_one_reference`, `_extract_failure_display_data`, `_find_peer_nodes_with_field`, `_suggest_field_correction`. Kept `build_type_error_message` and `build_json_parse_error_message` for non-template-error cases.
- `template_resolution.py` — `resolve_templates` attaches `_pflow_template_diagnostic` to `ValueError` for strict-mode trace capture; uses `extract_root_node_id` everywhere
- `error_context.py` — uses `get_node_output` (reads both succeeded AND failed data); uses `extract_root_node_id`
- `batch_executor.py` — `_aggregate_batch_results` writes `shared[node_id]` BEFORE raising on all-failed (post-review A2); `_execute_sequential` and `_execute_parallel` break-not-raise on fail_fast so the raise happens in `execute_batch` after aggregation

**Template and template resolver**:
- `src/pflow/runtime/template_resolver.py` — new public `TemplateResolver.extract_root_node_id()` static method (was private `_ROOT_SPLIT_PATTERN.split`); replaces 5+ ad-hoc implementations across the codebase

**Output resolution**:
- `src/pflow/runtime/output_resolver.py` — `_diagnose_unresolved_output` stripped to structured-only (post-review Fix #1 dropped legacy `diagnostics`/`raw_diagnostics` lists); `_is_all_absent_coalesce` helper distinguishes legitimate Task 128 branch-convergence fallthrough from FAILED operands that must error; `_record_output_failure` extracts source_file/source_line

**Core diagnostic**:
- `src/pflow/core/diagnostic.py` — `_format_template_error_lines` handles single and multi-output cases; `_format_output_block` renders per-output blocks for multi-output failures; `_format_all_unavailable_coalesce_summary` handles ALL-failed and mixed absent+failed coalesce; `_format_context_keys_block` always renders succeeded + failed peer nodes; `_format_warning_template_error` extends the structured renderer to WARNING severity for template_error warnings (post-review Test B); `_truncate_error_text` normalizes multi-line error truncation; `_format_location` uses universal `file:line` format

**User-facing errors**:
- `src/pflow/core/user_errors.py` — `OutputResolutionError.to_diagnostics` FULL REWRITE (post-review Fix #1). One-line summary message, structured `output_failures` list in context, `node_id=None` explicitly, no legacy canned suggestions. `_build_output_error_summary` helper matches `build_template_error_diagnostic` format.

**Executor service**:
- `src/pflow/execution/executor_service.py` — reads category from `__failures__` record first via `_FAILURE_CATEGORY_MAP`, falls back to legacy regex only for legacy entries; uses `get_node_output` and `get_node_failure`

**Execution state / display**:
- `src/pflow/execution/execution_state.py` — `build_execution_steps` uses `get_node_status` (post-completion BUG #2 fix) with `_STATUS_MAP`; reads batch metadata via `get_node_output`

**Runner (post-review fixes)**:
- `src/pflow/execution/runner.py` — `_compile_and_execute` exception handler skips `_pflow_node_id` annotation for `OutputResolutionError` (Fix #3) and attaches `_pflow_shared_store` via annotation pattern (Fix #5); `_exception_to_result` reads `_pflow_shared_store` and populates `ExecutionResult.shared_after`; `_extract_runtime_warnings` passes through structured `Diagnostic` for permissive-mode template errors (Fix #6) instead of building canned hints

**Workflow executor**:
- `src/pflow/runtime/workflow_executor.py` — `_extract_child_error` reads `get_node_failure` first, then `get_node_output`; `__failures__` NOT in `_PROPAGATED_KEYS` (per-workflow scoping)

**Schema**:
- `src/pflow/core/ir_schema.py` — allows internal `_source_line` metadata on output definitions (required by Phase 6 source line tracking)

**Markdown parser**:
- `src/pflow/core/markdown_parser.py` — added `yaml_item_lines` parallel list tracking and `yaml_item_keys` parsed-key tracking to `_Entity`; `_build_output_dict` records `_source_line` from yaml items and code blocks

**Validator**:
- `src/pflow/core/workflow/validator.py` — uses `TemplateResolver.extract_root_node_id()` (with post-review `.lstrip(".")` cleanup for bracket syntax)

**Core workflow**:
- `src/pflow/core/workflow/data_flow.py` — swapped from `_ROOT_SPLIT_PATTERN` reach to public `extract_root_node_id`

**Node output formatter**:
- `src/pflow/execution/formatters/node_output_formatter.py` — migrated from `path.split(".")[0].split("[")[0]` to `TemplateResolver.extract_root_node_id` (B4 cleanup)

**Documentation**:
- `src/pflow/runtime/CLAUDE.md` — node execution state invariant, `__failures__` key reference, lifetime note
- `src/pflow/runtime/engine/CLAUDE.md` — `mark_node_failed` and loop re-entry cleanup documented

### Test Files

**New**:
- `tests/test_runtime/test_node_state.py` — 160 lines unit tests for all `node_state` helpers
- `tests/test_integration/test_failed_node_invariant.py` — 650+ lines of integration tests. **Load-bearing**: the `#208` repro, `_shell_error_without_on_error_preserves_shell_data_in_failure_record`, `test_output_resolution_error_does_not_inherit_stale_failed_node`, `test_failed_batch_surfaces_error_details_in_execution_steps` (end-to-end 4-layer pipeline guard).
- `tests/test_runtime/test_template_error_messages.py` — snapshot-style tests for Cases 1-5 from the spec; `TestPermissiveModeWarningRendering` guards Fix #6 + Test B renderer fix against regression

**Modified**:
- `tests/test_integration/test_branch_convergence.py` — migrated off legacy wording; new `test_child_failures_do_not_leak_into_parent_failures_dict` invariant guard for sub-workflow `__failures__` isolation
- `tests/test_runtime/test_output_resolver.py` — migrated assertions from legacy `diagnostics` lists to structured `unresolved_references`
- `tests/test_runtime/test_checkpoint_tracking.py::test_failed_node_tracking` — updated to match post-B5 contract (`cache_result` for error actions is a no-op; `mark_node_failed` is the single write site)
- `tests/test_execution/test_runner.py::test_extract_runtime_warnings_preserves_structured_diagnostic` — unit test for Fix #6 structured diagnostic pass-through

## Integration Points & Dependencies

### Shared Store Keys

| Key | Owner | Purpose |
|---|---|---|
| `shared[node_id]` | engine + `mark_node_failed` | Successful node output. Presence ⟺ node succeeded. **Never coexists with `__failures__[node_id]`.** |
| `shared["__failures__"][node_id]` | `mark_node_failed` (single writer) | Failed node archive: `{data, category, error, warning}` |
| `shared["__execution__"]["failed_node"]` | `mark_node_failed` | Singular pointer to most-recent failure. Pre-existing; Task 148 spec defers migration to `failed_nodes` list |
| `shared["__warnings__"][node_id]` | `mark_node_failed` (when `warning=` passed) + `_handle_no_successor` guard path | DEGRADED status detection |
| `shared["__template_errors__"][node_id]` | `resolve_templates` permissive mode | Attached Diagnostic consumed by `_extract_runtime_warnings` |

**Reserved shape of a failure record** (from `node_state.py` docstring):
```python
{
    "data": {...},        # what was at shared[node_id] before the move (may be {})
    "category": "shell_failure" | "node_action_error" | "api_warning" | ...
    "error": "...",       # human-readable error (optional)
    "warning": "...",     # api_warning category only (optional)
}
```

### Exception Annotation Pattern (load-bearing)

The engine/runner use a non-standard "attach data to exception" pattern to thread context through Python's exception machinery:

- `e._pflow_node_id` — engine attaches the failing node id; `exception_to_diagnostics` reads it to annotate diagnostics. **Post-review Fix #3**: `_compile_and_execute` skips this for `OutputResolutionError` so stale `failed_node` doesn't lie about location.
- `e._pflow_shared_store` — **post-review Fix #5**: `_compile_and_execute` attaches the full shared store; `_exception_to_result` reads it to populate `ExecutionResult.shared_after`. Without this, exception-path failures had empty `shared_after`, silently breaking the CLI/MCP failure display.
- `e._pflow_parser_diagnostics` — accumulated parser warnings
- `e._pflow_template_diagnostic` — `resolve_templates` attaches the structured Diagnostic to strict-mode ValueErrors so `_builtin_exception_diagnostic` can return it directly
- `e._partial_resolutions` — template resolution partial state for trace capture

**Do NOT wrap or replace exceptions in ways that lose these attributes** (no `raise NewError(...) from e` that forgets to copy). The `exception_to_diagnostics` fallback chain in `core/diagnostic.py` checks several of these attributes; all must survive to the error boundary in `_exception_to_result`.

### Sub-Workflow Propagation

`WorkflowExecutor._PROPAGATED_KEYS` deliberately EXCLUDES `__execution__`, `__cache_hits__`, `__template_errors__`, AND `__failures__` — each workflow has its own. Enforced by test `test_child_failures_do_not_leak_into_parent_failures_dict` (Test C).

## Architectural Decisions & Tradeoffs

### Key Decisions

**Move data, don't delete** — failed-node data moves to `__failures__` instead of being dropped. Preserves diagnostics, error enrichment, and trace enrichment while making the membership check on `shared[id]` semantically correct.

**Single write path through `mark_node_failed`** — all 5 failure paths funnel through one function. Previously: 5 write sites with slightly different combinations of `failed_node` / `__warnings__` / `invalidate_cache`. Rejected alternative: leave direct writes, just add a helper. Reason: drift-proof. Any future change to the failure record shape only needs one edit.

**Category set at source, not regex-guessed later** — each failure site passes its known category to `mark_node_failed`. `executor_service._FAILURE_CATEGORY_MAP` consults the failure record's category before falling back to the legacy regex-on-message detection. Replaces the fragile `"${" in error_message` pattern with authoritative data.

**`__failures__` is internal (double-underscore)** — NOT exposed in user templates. Spec decision: if a pattern emerges (e.g., wanting `${primary.error}` from a fallback), add first-class syntax later rather than let users reach into `__failures__`.

**Step 17.5 is the LAST thing before return** — runs AFTER `record_trace`, `call_completion_callback`, `enrich_llm_cost`. Those consumers still read `shared[node_id]` directly; only `build_execution_steps` and post-engine consumers use `get_node_output`. Rationale: keep the hot path free of helper indirection, centralize the move at a single spot.

**Structured context, not prose in `Diagnostic.message`** — rich per-reference data lives in `context.unresolved_references`; message is a one-line summary for identity/dedup. JSON/MCP consumers get the structure directly. Text rendering is a pure function of the structure via `_format_template_error_lines`.

**`_is_all_absent_coalesce` distinguishes "branch not taken" from "recovery failed"** — a coalesce with all ABSENT operands is the legitimate Task 128 fallthrough (silent skip). A coalesce with any FAILED or PATH_ERROR operand is a real error (raise). This fixed the post-completion BUG #1 silent swallow.

**`corrected_var` field for typo-on-failed paste-able fixes** — when a reference has BOTH a failure AND a typo, compute the corrected path, use it for peer search AND for the fix template. The primary ref line still shows the original typo (so the agent sees what they wrote). Post-review Fix #5.

**Exception annotation pattern over explicit parameter threading** — adding `shared_store` as a parameter to `_exception_to_result` would have required restructuring several error paths. Attaching it via `e._pflow_shared_store` matches the existing `_pflow_node_id` convention and is minimally invasive. Trade-off: non-standard Python, but consistent with how pflow already threads context through exceptions.

### Technical Debt Intentionally Incurred

- **Singular `__execution__["failed_node"]`** — pre-existing single-value quirk, orthogonal to the invariant fix. Spec explicitly defers the `failed_node → failed_nodes` list refactor.
- **Sub-workflow Diagnostic flattening** (GH #233) — child errors still flatten to strings at the WorkflowExecutor boundary. The new rich rendering doesn't propagate through sub-workflows. Acceptable for Task 148.
- **Loop recovery `--report` aggregation** (GH #240) — trace uses `any(not event.success for event in events)` which is monotonic over the full event list. Visit 1's failure persists forever in the trace aggregation even after visit 2 succeeds.
- **`__failures__` unbounded growth** — documented in `runtime/CLAUDE.md`, no cleanup mechanism.
- **Runtime DEGRADED status** (GH #246) — `_determine_status` doesn't consult `__failures__`. A workflow recovered via on-error reports SUCCESS with no diagnostic signal.

## Testing Implementation

### Test Strategy

**End-to-end over unit tests for multi-layer pipelines**. Every post-review bug was found because I wrote an end-to-end test that exercised the full chain. Unit tests that mocked the boundary being tested passed while the real pipeline broke. Specific examples:

- **A2 + Fix #5** (batch metadata surviving through exception-path failure display): unit tests for `_aggregate_batch_results`, unit tests for `build_execution_steps`, unit tests for `_exception_to_result` — all three passed individually, but the integration was broken because `_exception_to_result` threw away `shared_store`. The regression test `test_failed_batch_surfaces_error_details_in_execution_steps` runs the full chain through `WorkflowRunner().run()` and asserts the final formatter output.

- **Test B** (permissive-mode template error rendering): unit test for `_extract_runtime_warnings` asserting the returned Diagnostic has the right context PASSED. But rendering that Diagnostic produced a one-line summary because `_format_warning_or_info_diagnostic` never called the structured renderer for warnings. Only a test that actually rendered the Diagnostic caught it.

### Critical Test Cases

**Load-bearing regression guards** (delete these and you will re-introduce real bugs):

| Test | Catches |
|---|---|
| `test_coalesce_falls_through_to_fallback_on_primary_failure` | GH #208 repro |
| `test_shell_error_without_on_error_preserves_shell_data_in_failure_record` | Fix #2 routing double-archive |
| `test_output_resolution_error_does_not_inherit_stale_failed_node` | Fix #3 stale node_id annotation |
| `test_output_resolution_error_does_not_triple_render` | Fix #1 triple-render |
| `test_failed_batch_surfaces_error_details_in_execution_steps` | A2 + #5 4-layer pipeline |
| `test_all_failed_batch_preserves_batch_metadata_in_failures` | A2 raise-before-write |
| `test_fail_fast_batch_preserves_batch_metadata_in_failures` | A2 fail_fast variant |
| `test_multi_output_resolution_error_renders_per_output_blocks` | Fix #1 multi-output structure |
| `test_mixed_absent_and_failed_coalesce_emits_summary_fix` | Fix #4 mixed coalesce gate |
| `test_fix_template_uses_corrected_field_and_real_peer` | Fix #5 corrected_var plumbing |
| `TestPermissiveModeWarningRendering::test_warning_severity_template_error_renders_structured_block` | Test B rendering gap |
| `test_child_failures_do_not_leak_into_parent_failures_dict` | `_PROPAGATED_KEYS` invariant |
| `test_loop_reentry_clears_stale_failure_record` | Loop re-entry clearing |
| `test_extract_runtime_warnings_preserves_structured_diagnostic` | Fix #6 structured pass-through |
| `test_multi_failure_all_show_failed_status` | Post-completion BUG #2 |

**Coverage-only tests that matter less**: most of the unit tests in `test_node_state.py` just verify the enum dispatch of `get_node_status`. These are fine but wouldn't catch the boundary bugs above.

## Unexpected Discoveries

### Gotchas Encountered

**`NamespacedSharedStore.__init__` eagerly creates `parent[namespace] = {}`** (`namespaced_store.py:39-41`). This was one of the two root causes of #208 — a failed node that wrote nothing still had an empty dict in `shared` because the namespaced store allocated one at construction. The fix doesn't touch `namespaced_store.py`; the step 17.5 move catches both "wrote data" and "wrote nothing" cases.

**`shell.post()` writes outputs BEFORE returning the action** (`shell.py:613-639`). The other root cause of #208. Shell writes `stdout/stderr/exit_code/error` to the shared store, then returns `"error"`. The old invariant assumed "returned error ⟹ don't write data", but the data was already there. Again, fix doesn't touch shell.py; the post-execution move handles both cases.

**`record_trace` and `enrich_llm_cost` are UNCHANGED** — they read `shared[node_id]` directly because step 17.5 runs AFTER them. An earlier draft migrated them to `get_node_output`, which would have been unnecessary indirection. If someone moves step 17.5 earlier, these functions must be updated to use helpers.

**`_handle_no_successor` is called AFTER `_execute_node` returned successfully**. By then step 17.5 may have archived the node. The post-review Fix #2 guard checks `get_node_failure` first and preserves existing records instead of re-popping empty data.

**`ExecutionResult.shared_after` is empty on exception paths** (until Fix #5 added `_pflow_shared_store` threading). Consumers of the runner's error path got no partial state. This was discovered while writing a regression test for A2 — the test had to run at engine level, not runner level, which was a smell that led to the real fix.

**Permissive-mode warnings silently lost structured context in rendering** (until Test B fix). The data flow was correct after Fix #6, but `_format_warning_or_info_diagnostic` always rendered warnings as one-liners regardless of category. Same Diagnostic object, two severities, radically different output. ERROR → 12-line structured block, WARNING → one line.

**`OutputResolutionError` triple-rendered the same error**: legacy prose in `message` + structured context block + legacy canned `suggestions`. The fix required refactoring the error class AND stripping `_diagnose_unresolved_output` of legacy fields AND updating `user_errors.py` to match. Any one of the three left in place would have preserved the bug.

**`_format_all_failed_coalesce_summary` gate required `status == "failed"` for ALL refs**. A mixed absent+failed coalesce (`${never_run.x ?? fails.y}`) hit neither the summary block nor the per-ref fixes (per-ref suppresses when `in_coalesce=True`) → agent got zero fix suggestions. Post-review Fix #4 widened the gate to `status in ("failed", "absent")`.

**`validator.py` had a latent `${data[0].x}` syntax bug**. The pre-task `operand.split(".", 1)[0]` split on dots and yielded `"data[0]"` including the bracket. B4 migration to `extract_root_node_id` silently fixed this.

**The parser's source line tracking uses parallel lists** (`yaml_items`, `yaml_item_lines`, `yaml_item_keys` on `_Entity`). Adding an item to one without updating the others corrupts the index. Fragile — the only thing keeping it honest is that `_parse_yaml_items` is the sole writer.

### Edge Cases Found

1. **Shell exit without on-error + `- next: other`** — triggers `_handle_no_successor` for an already-archived node. Pre-Fix #2 overwrote the shell data with routing_error. The fix: check `get_node_failure` first.

2. **Workflow recovers via on-error, then output references an absent branch** — OutputResolutionError inherits the stale `failed_node` pointer, diagnostic `At:` line points at the (recovered) original failure location. Fix #3 excludes OutputResolutionError from the inheritance.

3. **Python code node raises multi-line error** — truncated mid-word in the rendered output, breaking layout. Fix B1 normalizes truncation at first newline + `(more)`.

4. **Workflow where all referenced peer nodes also failed** — "Available nodes in context:" block was empty and silently skipped. Fix B3 includes failed peers with `(failed)` marker.

5. **All-failed batch with `error_handling: continue`** — `_aggregate_batch_results` raised before writing shared store. Step 17.5 archived empty data. Display showed no batch metadata. Fix A2 moved the write before the raise.

6. **Sub-workflow in batch item fails** — child's `__failures__` is isolated per `_PROPAGATED_KEYS`. Invariant guard via Test C.

## Patterns Established

### Reusable Patterns

**1. Single-write-site helper for cross-cutting state**

When N sites in an engine/runtime write to the same structure, establish one helper as the canonical writer and audit every write site:

```python
# Before: 5 sites each setting shared["__execution__"]["failed_node"] + writing __warnings__
# After: all sites call mark_node_failed(shared, id, category=..., error=..., warning=...)
```

Audit discipline: add a regression test (`test_failed_node_tracking`) that asserts the canonical writer is the only path. Detect drift.

**2. Exception annotation for threading context**

When an exception has to carry data across a boundary that doesn't take parameters, attach attributes with a consistent `_pflow_*` prefix. Current attributes:

```python
e._pflow_node_id            # which node failed
e._pflow_shared_store       # post-review Fix #5
e._pflow_parser_diagnostics
e._pflow_template_diagnostic
e._partial_resolutions      # non-prefixed legacy
```

Readers should use `getattr(e, "_pflow_*", None)` with a sentinel. Writers must not lose attributes on `raise X from e` — always copy.

**3. Structured context in Diagnostic, thin message**

Rich per-item data in `Diagnostic.context.unresolved_references`. `Diagnostic.message` is a one-line summary that preserves identity/dedup. Text rendering is a pure function of the structure:

```python
context = {
    "category": "template_error",
    "unresolved_references": [
        {"var": "...", "root": "...", "status": "failed" | "absent" | "path_error",
         "failure": {...}, "peer_suggestions": [...], "secondary_hint": "...",
         "did_you_mean": "...", "corrected_var": "...", "in_coalesce": bool,
         "coalesce_expr": "..."},
        ...
    ],
    "available_context_keys": [...],
    "failed_context_keys": [...],
    "output_failures": [...],  # multi-output case
    "is_output_resolution": bool,
    "source_file": "...",
    "source_line": int,
}
```

JSON/MCP consumers read this directly via `Diagnostic.to_dict()`; text consumers render via `_format_template_error_lines`.

**4. Category-aware failure data extraction**

`_extract_failure_display_data(category, data)` dispatches on category to extract only the relevant fields (shell: command/exit_code/stderr; HTTP: status_code/url/response; MCP: server/tool/error_details; generic fallback). Downstream renderers can assume the shape.

**5. "Fix the layer, not the surface"**

When a bug appears at a layer boundary, ask: "what is component A silently dropping or ignoring?" Most of the post-review bugs were not algorithmic errors — they were missing consistency checks between layers. The fix is at the producer (write the right shape) or the consumer (read the full shape), not in the middle.

**6. Verify review findings before accepting**

When reviewing a plan or code, reproduce each critical claim with an actual script or test before writing the fix. Half-believed claims lead to wrong fixes. Two review-round examples from this work:
- "Is the permissive-mode rendering hypothesis real?" → 20-line reproducer → confirmed → fix
- "Does the validator reject `${input.field}`?" → 20-line reproducer → confirmed → issue filed with verified repro

### Anti-Patterns to Avoid

**1. Direct writes to `__failures__` / `__warnings__` / `failed_node`**

These bypass `mark_node_failed` and drift from the canonical shape. Every one of the 2 direct-write sites found during B5 cleanup was dead code anyway (also-writes-via-mark_node_failed). Delete, don't add.

**2. `root in context` / `shared_store[node_id]` checks**

Use `get_node_status`, `node_succeeded`, or `get_node_output`. A raw `in` check doesn't know about `__failures__`. Any place that reads `shared[node_id]` directly is now suspect unless it's `record_trace`/`enrich_llm_cost`/`call_completion_callback` which are documented exceptions that run BEFORE step 17.5.

**3. Ad-hoc root node ID extraction**

Use `TemplateResolver.extract_root_node_id()`. Do NOT use `path.split(".")[0]` or `re.split(...)[0]`. The ad-hoc forms miss bracket syntax (`data[0].x`) and create drift.

**4. Canned suggestion strings in Diagnostics**

Agents read these and get zero actionable signal. Either surface real structured context (pass the Diagnostic through), or emit no suggestions (let the renderer's per-ref fixes do the work). Issue #235 is an open tracking bug for the last canned-suggestion site (API warnings).

**5. Assuming warning-severity renders the same as error-severity**

They don't, by default. The `format_diagnostic` dispatch sends warnings to `_format_warning_or_info_diagnostic` which is one-line-only unless specifically extended (Test B added the template_error dispatch). If you add structured warning categories, extend the warning renderer explicitly.

**6. Raising before writing partial state**

If a function builds state that a post-execution hook will read from `shared[node_id]`, write the state BEFORE raising. Step 17.5 only captures what's there at the moment it runs. This was the A2 bug.

**7. Wrapping exceptions without preserving annotations**

`raise RuntimeError(...) from e` loses any attributes attached to `e` unless explicitly copied. The `exception_to_diagnostics` chain depends on these attributes surviving to the error boundary.

## Breaking Changes

### API/Interface Changes

- **`shared[failed_node]` no longer exists** after execution — consumers must use `get_node_output`. Caught several pre-Task-148 tests that asserted on failed-node data at root level; they were migrated to read from `__failures__[id].data`.
- **`OutputResolutionError.__init__` signature preserved**, but `explanation` is now a one-line summary; `suggestions` defaults to `None`; `failures` dict no longer contains `diagnostics` or `raw_diagnostics` lists.
- **`_diagnose_unresolved_output` return shape** shrank: `{source_expr, template, unresolved_references, available_context_keys}`. Legacy `diagnostics` and `raw_diagnostics` removed.
- **`cache_result` for action="error" is a no-op** post-B5 cleanup. Callers must use `mark_node_failed` for failure recording.
- **`record_trace` error parameter** now accepts `Exception | str` (loosened from `Optional[Exception]`) so the happy-path action="error" case can pass the error text directly (post-completion BUG #3 fix).
- **`_exception_to_result` now populates `ExecutionResult.shared_after`** from `_pflow_shared_store` annotation. Consumers that assumed empty `shared_after` on exception paths will now see the full shared store. Nothing in the codebase asserted empty, but external consumers might observe the change.

### Behavioral Changes

- **Template errors render with per-reference structure** — dramatically different text output vs pre-Task-148. Agents relying on the old "node X did not execute" text pattern in errors will need to parse the structured `unresolved_references` or match the new "did not execute" / "executed but FAILED" / "executed but does not produce field" variants.
- **Coalesce with any failed operand errors loudly** in output declarations (was silently skipped). BUG #1 post-completion fix.
- **Multi-failure workflows show all failed nodes** in the execution summary (was hiding all but the last). BUG #2 post-completion fix.
- **`--report` shows real error text** for action="error" failures (was "Unknown error"). BUG #3 post-completion fix.
- **Permissive-mode template warnings render the structured block in CLI text** (was one-line only). Test B fix.
- **`At: file:line`** (universal editor-click format) instead of `At: file, line N`. C3 format change.

## Future Considerations

### Extension Points

**Adding new failure categories**: Extend `FAILURE_CATEGORY_*` constants in `node_state.py`, add a description in `_describe_failure_category` in `diagnostic.py`, add a branch in `_FAILURE_CATEGORY_MAP` in `executor_service.py`, add a renderer in `_render_failure_data_block` if the category has custom fields. Test via `TestWarning9CategoryAwareFailureRendering` pattern.

**Adding new Diagnostic context fields for template errors**: Add to the dict built by `build_template_error_diagnostic` and render in `_format_template_error_lines`. Keep backward compat — if a field is absent, the renderer should skip its block.

**Adding new propagated keys for sub-workflows**: Add to `WorkflowExecutor._PROPAGATED_KEYS`. Verify the per-workflow scoping invariant by running `test_child_failures_do_not_leak_into_parent_failures_dict`-style tests for the new key.

**Adding new exception annotations**: Use `_pflow_*` prefix, document in the progress log, add to the error boundary reader in `_exception_to_result` or `exception_to_diagnostics` as appropriate.

### Open Follow-Ups (filed)

- **#246 DEGRADED status** — runtime status should consult `__failures__` after recovery
- **#247 Validator `${input.field}` rejection** — blocks valid workflow input field access
- **#248 Multi-output dedup** — template errors repeat failure block for multiple outputs on the same root
- **#249 `handle_api_warning` missing `call_completion_callback`** — progress display inconsistency
- **#250 Trace routing success=True** — routing failure for custom non-error actions has wrong trace event
- **#235 (partially addressed)** — API warning half still has canned suggestions
- **#233** — sub-workflow Diagnostic propagation flattens to plain string
- **#234** — distinguish "not declared" from "branch not taken" in absent-node wording
- **#240** — trace aggregation reports workflow failed after loop recovery
- **#241** — invariant doesn't hold for `enable_namespacing=false`

## AI Agent Guidance

### Quick Start for Related Tasks

**If you're touching node execution state**, read in this order:
1. `src/pflow/runtime/node_state.py` (184 lines — read in full)
2. `src/pflow/runtime/CLAUDE.md` "Node Execution State Invariant" + "Reserved Shared Store Keys" sections
3. `src/pflow/runtime/engine/CLAUDE.md` "Error path details" in `_execute_node` section
4. `src/pflow/runtime/engine/engine.py` lines 111-398 (`_handle_no_successor`, `_execute_node` step 17.5 + exception path)
5. `src/pflow/runtime/engine/instrumentation.py` (`mark_node_failed` callers: `cache_result`, `enforce_loop_guard`, `handle_api_warning`, `handle_cached_execution`)
6. `.taskmaster/tasks/task_148/task-148.md` — spec (for the "what" and "why")
7. `.taskmaster/tasks/task_149/implementation/progress-log.md` — full history including all 5 review passes and the reasoning behind each fix

**If you're touching template errors or Diagnostics**, read:
1. `src/pflow/runtime/engine/template_errors.py` — full file (350 lines)
2. `src/pflow/core/diagnostic.py` — `_format_template_error_lines`, `_format_output_block`, `_format_all_unavailable_coalesce_summary`, `_format_context_keys_block`, `_format_warning_template_error` (~200 lines)
3. `src/pflow/core/user_errors.py` — `OutputResolutionError` class
4. `src/pflow/runtime/output_resolver.py` — `_diagnose_unresolved_output`, `_is_all_absent_coalesce`, `_record_output_failure`
5. `src/pflow/execution/runner.py` — `_extract_runtime_warnings` (template_error vs api_warning branches)

**If you're touching batch execution**, understand the 4-layer pipeline:
1. `_aggregate_batch_results` writes `shared[node_id]` (must happen before any raise)
2. Step 17.5 archives to `__failures__[id].data`
3. `_exception_to_result` threads `shared_store` via annotation
4. `build_execution_steps` reads via `get_node_output` and emits batch_error_details

Break any link → spec acceptance criterion silently fails. Guard with `test_failed_batch_surfaces_error_details_in_execution_steps`.

**If you're touching sub-workflows**, verify:
- `__failures__` stays OUT of `_PROPAGATED_KEYS`
- `_extract_child_error` reads via `get_node_failure` then `get_node_output`
- Run `test_child_failures_do_not_leak_into_parent_failures_dict` before and after your change

### Common Pitfalls

1. **Don't add `__failures__` to `_PROPAGATED_KEYS`** — it's per-workflow. Same for `__execution__`, `__cache_hits__`, `__template_errors__`.

2. **Don't assume `ExecutionResult.shared_after` is empty on failure paths** — it's populated via Fix #5's annotation. If you need partial state after an exception, it's there.

3. **Don't render warning-severity template errors as one-liners** — they carry the same structured context as errors. Extend `_format_warning_or_info_diagnostic` (or its dispatchers) if you add new structured warning categories.

4. **Don't use `shared[node_id]` directly in post-execution consumers** — use `get_node_output` or `get_node_failure`. The few pre-step-17.5 readers (`record_trace`, `enrich_llm_cost`, `call_completion_callback`) are exceptions and should stay that way.

5. **Don't raise in batch aggregation before writing state** — the write MUST precede the raise, otherwise step 17.5 archives empty data.

6. **Don't add canned suggestions to Diagnostics** — emit real context or no suggestions. Agents read canned text and waste turns on vacuous hints.

7. **Don't use `operand.split(".", 1)[0]` to extract a root node ID** — use `TemplateResolver.extract_root_node_id()`. The split form misses bracket syntax.

8. **Don't let exception annotations die on wrap-and-rethrow** — `raise X from e` loses them unless copied explicitly. The `_pflow_*` annotations are load-bearing.

9. **Don't test only at the unit level for multi-layer features** — write at least one end-to-end test through `WorkflowRunner().run()`. Unit tests that mock the boundary will pass while the real pipeline breaks.

10. **Don't wire `clear_node_failure` into general cleanup** — it's specifically for loop re-entry (and defensive in `handle_cached_execution`). Calling it in other contexts can corrupt the invariant.

### Test-First Recommendations

Before modifying any of these files, run their critical tests:

- `src/pflow/runtime/node_state.py` → `pytest tests/test_runtime/test_node_state.py`
- `src/pflow/runtime/engine/engine.py` → `pytest tests/test_runtime/test_engine_behavior.py tests/test_integration/test_failed_node_invariant.py`
- `src/pflow/runtime/engine/template_errors.py` → `pytest tests/test_runtime/test_template_error_messages.py`
- `src/pflow/runtime/engine/batch_executor.py` → `pytest tests/test_runtime/test_batch_node.py tests/test_integration/test_failed_node_invariant.py::test_all_failed_batch_preserves_batch_metadata_in_failures tests/test_integration/test_failed_node_invariant.py::test_fail_fast_batch_preserves_batch_metadata_in_failures`
- `src/pflow/core/diagnostic.py` → `pytest tests/test_core/test_diagnostic.py tests/test_runtime/test_template_error_messages.py`
- `src/pflow/core/user_errors.py` → `pytest tests/test_runtime/test_output_resolver.py tests/test_runtime/test_template_error_messages.py::TestWarning10OutputResolutionStructured`
- `src/pflow/execution/runner.py` → `pytest tests/test_execution/test_runner.py tests/test_integration/test_failed_node_invariant.py`

See repro example in the GH #208 issue.
