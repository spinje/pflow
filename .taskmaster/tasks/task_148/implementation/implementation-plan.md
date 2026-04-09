# Task 148: Failed-Node Invariant Fix and Template Error UX Consolidation

## Context

**The bug (GH #208)**: `${primary.stdout ?? fallback.stdout}` resolves to `primary`'s empty string instead of `fallback`'s output when `primary` failed and was routed via `on-error`. Expected: `fallback-content`. Actual: empty.

**The root cause**: Task 128's `??` operator was built on the invariant *"node ran ↔ present in shared store"*. But the system has three states (didn't run, succeeded, **failed via on-error**). `NamespacedSharedStore.__init__` eagerly creates `shared[node_id] = {}`, and `shell.post()` writes `stdout/stderr/exit_code/error` BEFORE returning `"error"`. Failed nodes leak garbage into `shared[node_id]`. `resolve_coalesce`'s `root not in context` check sees them as "successful" → bug.

**Why fix the invariant, not patch coalesce**: The wrong invariant has metastasized into ~15 scattered "is node present?" checks, 5 separate "mark node failed" sites, 5 root-extraction implementations, 4 "did not execute" message wordings, two parallel template-error rendering paths that don't overlap correctly, and ~12 Diagnostic context fields that are written but never rendered. Patching `resolve_coalesce` alone leaves the invariant broken; every future consumer would re-discover it.

**What this task delivers**:
1. **Tier 1** — Fix the invariant by moving failed-node data from `shared[node_id]` to `shared["__failures__"][node_id]`. Funnel all 5 failure write sites through one helper. Replace ~15 scattered reads with helpers from a new `runtime/node_state.py` module. Centralize root extraction. Eliminate the four "did not execute" wording variants.
2. **Tier 2** — Replace the raw-string `build_enhanced_template_error` with structured Diagnostic context. Render failed-upstream details in error messages with the actual error, exit code, command, stderr. Add three states ("absent", "succeeded with path error", **"failed"**) to coalesce diagnostics. Track output `source:` line numbers in the parser so error messages show `At: workflow.pflow.md:23`. Fix `OutputResolutionError` category bug. Eliminate ~12 dead Diagnostic context fields.

**Out of scope** (Tier 3 — separate GH issues to file): transactional `NamespacedSharedStore`, richer `get_upstream_stderr` showing command+exit+stdout, consolidating `path_validation.py` enhanced errors with runtime errors. Also out: backward-compat shims (no users yet), surfacing `__failures__` to user templates, validation message changes.

**Pre-existing work (already done in task setup)**:
- Task file: `.taskmaster/tasks/task_148/task-148.md` — read this BEFORE starting; it captures all the design discussion.
- Reproducer: `scratchpads/issue-208/repro.pflow.md` — verify it produces `fallback-content` after the fix.

---

## Architectural Decisions (DO NOT REVISIT)

1. **Move failed data, don't delete it**. `shared.pop(node_id)` → `shared["__failures__"][node_id]`. Preserves data for diagnostics, error enrichment, and trace.
2. **Move happens at the END of `_execute_node`**, after `record_trace` (step 16) and `call_completion_callback` (step 17). This applies uniformly to ALL three failure paths: returned-error action, api warning, raised exception. The intermediate helpers (`cache_result`, `handle_api_warning`) only update `__execution__["failed_node"]` bookkeeping at their original positions; the actual data move via `mark_node_failed` happens at step 17.5 in a single canonical place. This means `record_trace` and `enrich_llm_cost` read `shared[node_id]` directly (data still there) — no `get_node_output` indirection in trace recording. `mark_node_failed` is the LAST thing that runs for any failing node, regardless of which path triggered it.
3. **No backward compatibility**. Pre-1.0, no users. Every consumer migrates. Tests that asserted on `shared[failed_node]` data are wrong and must be updated.
4. **`__failures__` is internal**. Double-underscore convention like `__execution__`. NOT user-facing. NOT exposed to templates.
5. **Helpers live at `src/pflow/runtime/node_state.py`** (not under `engine/`) so `template_resolver.py` can import them without an upward dependency.
6. **Failure category is set at the source** (engine knows it's a template/shell/api error), stored on the failure record, read by the formatter. Replaces fragile `executor_service.determine_error_category` regex on the message string.
7. **Structured Diagnostic context for template errors**, not raw strings. JSON/MCP consumers get programmatic access. Text rendering happens in `_format_*_block` functions in `diagnostic.py`, not by stuffing multi-line strings into `Diagnostic.message`.
8. **`Diagnostic.__eq__/__hash__` constraint**: identity is `severity + source + node_id + message`. Two diagnostics with the same message dedupe. The new template error builder MUST keep enough specificity in `message` (e.g., include the param key + a short variable summary) to distinguish per-error instances.
9. **`file:line` format** for source references. Editor-clickable, AI-agent-parseable.
10. **Three-state coalesce diagnosis**: ABSENT (didn't run), SUCCEEDED (path error / typo), **FAILED** (with error preview). Each gets a different message with concrete fix suggestions.

---

## Critical Files To Read Before Modifying

The implementer MUST read these in full before making changes. Each entry says what to look for.

| File | Why |
|---|---|
| `.taskmaster/tasks/task_148/task-148.md` | Full task specification, design history, error message format examples, requirements list. Read first. |
| `src/pflow/runtime/template_resolver.py` (724 lines) | The `resolve_coalesce` function (lines 198-228), `_ROOT_SPLIT_PATTERN` (line 181), `variable_exists` (lines 384-411), `extract_variables` (lines 133-150), `_resolve_complex_match` (lines 593-652), and the `resolve_template` function (lines 528-591). |
| `src/pflow/runtime/engine/template_errors.py` (389 lines) | Read in full. Contains `build_enhanced_template_error`, `diagnose_coalesce`, `_append_error_context`, `format_available_keys`, `generate_suggestions`, `detect_json_parse_hints`, `build_type_error_message`, `build_json_parse_error_message`. The Tier 2 rewrite replaces most of this. |
| `src/pflow/runtime/engine/template_resolution.py` (414 lines) | The `resolve_templates` function (lines 274-413) and the `all_variables_from_absent_nodes` (lines 226-234) and `inject_none_for_optional_inputs` (lines 237-271) helpers. The error-raising sections at lines 357-365 and 379-400 will change to populate Diagnostic context. |
| `src/pflow/runtime/output_resolver.py` (153 lines) | Full file. Update `_diagnose_unresolved_output` and `populate_declared_outputs` to use the new helpers and pass source-line info. |
| `src/pflow/runtime/engine/engine.py` (363 lines) | The `_execute_node` method (lines 144-341): five exit paths where failure cleanup goes — happy-path return after step 17, `handle_api_warning` early return at line 250-260, `_handle_no_successor` at lines 111-142, exception path at lines 306-341. |
| `src/pflow/runtime/engine/instrumentation.py` (502 lines) | `cache_result` (lines 98-106), `handle_api_warning` (lines 455-500), `enrich_llm_cost` (lines 326-334), `call_completion_callback` (lines 363-409). Also `initialize_execution_state` (lines 32-49). |
| `src/pflow/runtime/engine/namespaced_store.py` (191 lines) | The eager namespace creation at lines 39-41. NO CHANGES — but understand the invariant. |
| `src/pflow/runtime/engine/error_context.py` (92 lines) | `get_upstream_stderr` (lines 45-92). Update to read from `__failures__` via the new helper. |
| `src/pflow/core/diagnostic.py` (416 lines) | Full file. Especially `format_diagnostic` (line 102), `_format_all_context_blocks` (line 194), `_format_template_error_lines` (line 246), `_format_shell_error_lines` (line 307), `_CATEGORY_TITLES` (line 322), `exception_to_diagnostics` (line 338), `_builtin_exception_diagnostic` (line 361), and the `Diagnostic` class (lines 19-79) including the identity constraint. |
| `src/pflow/core/user_errors.py` (152 lines) | `OutputResolutionError` (lines 96-151). The `category="runtime"` typo is at line 131. |
| `src/pflow/execution/executor_service.py` (230 lines) | Full file. `build_error_list`, `determine_error_category`, `_extract_node_level_error`, `_extract_root_level_error`, `_enrich_error_from_node_output`, `_get_failed_node`. |
| `src/pflow/execution/runner.py` lines 200-218, 467-509 | The post-engine error build at lines 215-218; defensive failure annotation at lines 204-213; `_build_errors` at 467-471; `_extract_runtime_warnings` at 473-509 (the canned suggestions to improve). |
| `src/pflow/runtime/workflow_executor.py` lines 370-389 | `_extract_child_error` — sub-workflow error extraction reads child's `failed_node`. |
| `src/pflow/core/markdown_parser.py` lines 175-260, 820-1018, 1333-1361 | The `_Entity` dataclass (~180), main parser state machine (~232), `_parse_yaml_items` (~820), `_route_code_blocks_to_node` (~1001), `_build_output_dict` (~1333). The parser does NOT track per-yaml-item line numbers today; this task adds that for output `source:` lines. |
| `src/pflow/runtime/compilation/compiler.py` line 276-278 | How `_source_lines` from parser becomes `_<key>_source_line` in node params. |
| `src/pflow/execution/execution_state.py` | `build_execution_steps` reads failed-node data for batch metadata + shell stderr display. Used by both success and error formatters in CLI and MCP. |
| `tests/test_runtime/test_template_coalesce.py` | The existing 67 coalesce tests. Pattern for new tests. |
| `tests/shared/markdown_utils.py` | `ir_to_markdown`, `write_workflow_file` helpers. **Note**: per `tests/CLAUDE.md` "Gotchas with ir_to_markdown", `ir_to_markdown` does NOT emit `edges`, `start_node`, or `ir_version`. Tests for on-error scenarios MUST pass IR dicts directly to `WorkflowRunner.run()` instead of roundtripping through markdown. |
| `tests/CLAUDE.md` | Read the "Gotchas with `ir_to_markdown`" section and the autouse fixture documentation. |
| `tests/conftest.py` | `mock_llm_calls` and `isolate_pflow_config` autouse fixtures. |
| `scratchpads/issue-208/repro.pflow.md` | The reproducer to verify the fix. |
| `src/pflow/runtime/CLAUDE.md` | Documentation to update: "Reserved Shared Store Keys" section. Add `__failures__`. Document the new invariant. |
| `src/pflow/runtime/engine/CLAUDE.md` | Document `mark_node_failed` and `node_state.py`. |

---

## Verification Script (run after every phase)

```bash
# Repro #208 — must produce 'fallback-content'
cd /Users/andfal/projects/pflow-fix-resolve-coalesce-empty-string
uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace

# Lint + types
make check

# Tests
make test
```

The repro is the canonical "did the fix work" check.

---

## Phase 1 — Helpers and root-extraction consolidation

### Goal
Single source of truth for "what's the state of this node?" and "mark it failed", PLUS the public `extract_root_node_id` helper. These ship together so Phase 3's read-site migration has all the helpers it needs.

### Action 1 — Create `src/pflow/runtime/node_state.py`

Create the file with the EXACT content below. Do NOT add anything else.

```python
"""Node execution state queries and failure bookkeeping.

This module is the single source of truth for "did this node succeed,
fail, or never run?". It also owns the move of failed-node data from
the main shared store namespace into shared["__failures__"][node_id].

The invariant this module enforces:
    shared[node_id]            ↔ node_id ran successfully
    shared["__failures__"][id] ↔ node_id executed and failed
    neither                    ↔ node_id did not execute

Failed-node data is preserved (not deleted) so error enrichment,
diagnostics, and traces can still surface it. The move means the
template resolver and every other consumer that asks "is this node's
output usable?" can use the simple check ``node_id in shared`` and
get the right answer.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class NodeStatus(Enum):
    """Three execution states a node can be in."""

    ABSENT = "absent"        # Did not execute (branch not taken)
    SUCCEEDED = "succeeded"  # Ran, produced authoritative output
    FAILED = "failed"        # Ran, failed (on-error routed, api warning, exception)


# Categories used by mark_node_failed. Set at the failure site so the
# formatter doesn't have to regex the error message to guess the type.
FAILURE_CATEGORY_SHELL = "shell_failure"
FAILURE_CATEGORY_NODE_ERROR = "node_action_error"
FAILURE_CATEGORY_API_WARNING = "api_warning"
FAILURE_CATEGORY_ROUTING = "routing_error"
FAILURE_CATEGORY_EXCEPTION = "exception"
FAILURE_CATEGORY_TEMPLATE = "template_error"


def get_node_status(shared: dict[str, Any], node_id: str) -> NodeStatus:
    """Return the execution state of a node.

    Order of checks matters: __failures__ is checked first because a
    revisited (loop) node may temporarily appear in both during the
    transition; FAILED wins until the new run commits.
    """
    if node_id in shared.get("__failures__", {}):
        return NodeStatus.FAILED
    if node_id in shared and not (node_id.startswith("__") and node_id.endswith("__")):
        return NodeStatus.SUCCEEDED
    return NodeStatus.ABSENT


def node_succeeded(shared: dict[str, Any], node_id: str) -> bool:
    """True if and only if the node ran successfully and has output."""
    return get_node_status(shared, node_id) == NodeStatus.SUCCEEDED


def get_node_output(shared: dict[str, Any], node_id: str) -> Optional[Any]:
    """Return node output regardless of success/failure.

    Used by consumers that need the data either way (trace, error
    enrichment, get_upstream_stderr). Returns None only when the node
    did not execute.

    For failed nodes, returns the ``data`` field of the failure record
    (NOT the wrapping record itself), so callers see the same shape
    they would have seen before the move.
    """
    if node_id in shared.get("__failures__", {}):
        record = shared["__failures__"][node_id]
        if isinstance(record, dict) and "data" in record:
            return record["data"]
        return record
    return shared.get(node_id)


def get_node_failure(shared: dict[str, Any], node_id: str) -> Optional[dict[str, Any]]:
    """Return the failure record for a failed node, or None.

    The failure record has shape::

        {
            "data": {...},        # what was at shared[node_id] before the move
            "category": "...",    # one of the FAILURE_CATEGORY_* constants
            "error": "...",       # human-readable error message (optional)
            "warning": "...",     # for api_warning category only (optional)
        }
    """
    failures = shared.get("__failures__")
    if not isinstance(failures, dict):
        return None
    record = failures.get(node_id)
    if not isinstance(record, dict):
        return None
    return record


def mark_node_failed(
    shared: dict[str, Any],
    node_id: str,
    *,
    category: str,
    error: Optional[str] = None,
    warning: Optional[str] = None,
) -> None:
    """Archive a failed node's output and update execution state.

    This is the SINGLE write site for "this node failed". All five
    failure paths in the engine funnel through this function:

    1. ``cache_result`` when the node returned an action starting with "error"
    2. ``handle_api_warning`` when the API warning detector triggered
    3. ``_handle_no_successor`` when the action has no matching edge
    4. ``_execute_node`` except block when the node raised
    5. Defensive paths in the runner

    Effects:
    - Moves ``shared[node_id]`` to ``shared["__failures__"][node_id]``
      wrapped in a failure record. The original namespace key is removed.
    - Sets ``shared["__execution__"]["failed_node"] = node_id``.
    - If a warning is given, also writes it to ``shared["__warnings__"]``
      (used for DEGRADED status detection).
    - Removes the node from ``__execution__["completed_nodes"]`` and
      ``node_actions`` if it was previously recorded there (loop case).

    The data field of the failure record is whatever was at
    ``shared[node_id]`` (an empty dict if nothing was written before
    failure). The category and error fields are set from arguments.
    """
    if "__execution__" not in shared:
        shared["__execution__"] = {
            "completed_nodes": [],
            "node_actions": {},
            "node_hashes": {},
            "failed_node": None,
            "node_visit_counts": {},
        }

    # Capture data before popping. Don't pop __* keys.
    if node_id.startswith("__") and node_id.endswith("__"):
        data: dict[str, Any] = {}
    else:
        popped = shared.pop(node_id, None)
        data = popped if isinstance(popped, dict) else ({} if popped is None else {"value": popped})

    record: dict[str, Any] = {
        "data": data,
        "category": category,
    }
    if error is not None:
        record["error"] = str(error)
    if warning is not None:
        record["warning"] = str(warning)

    shared.setdefault("__failures__", {})[node_id] = record
    shared["__execution__"]["failed_node"] = node_id

    # Loop case: a node that previously succeeded is being marked failed
    # on re-entry. Strip its successful bookkeeping.
    completed = shared["__execution__"].get("completed_nodes", [])
    if node_id in completed:
        completed.remove(node_id)
    shared["__execution__"].get("node_actions", {}).pop(node_id, None)
    shared["__execution__"].get("node_hashes", {}).pop(node_id, None)

    if warning is not None:
        shared.setdefault("__warnings__", {})[node_id] = warning


def clear_node_failure(shared: dict[str, Any], node_id: str) -> None:
    """Remove a node from __failures__ if present.

    Used when a previously-failed node is being re-executed (loop case).
    The new execution will populate ``shared[node_id]`` if it succeeds,
    or call ``mark_node_failed`` again if it fails.
    """
    failures = shared.get("__failures__")
    if isinstance(failures, dict):
        failures.pop(node_id, None)
```

### Action 2 — Add `TemplateResolver.extract_root_node_id`

In `src/pflow/runtime/template_resolver.py`, add this static method to the `TemplateResolver` class. Place it immediately after `is_coalesce_expression` (around line 196). The existing `_ROOT_SPLIT_PATTERN` at line 181 stays — internal callers can continue to use it directly.

```python
    @staticmethod
    def extract_root_node_id(template_path: str) -> str:
        """Extract root node ID from a template path.

        Examples:
            >>> TemplateResolver.extract_root_node_id("node")
            'node'
            >>> TemplateResolver.extract_root_node_id("node.field")
            'node'
            >>> TemplateResolver.extract_root_node_id("node.field[0].sub")
            'node'
            >>> TemplateResolver.extract_root_node_id("data[0]")
            'data'
        """
        return TemplateResolver._ROOT_SPLIT_PATTERN.split(template_path, maxsplit=1)[0]
```

This is needed up-front because Phase 3 read-site migrations call it.

### Verification

```bash
uv run python -c "
from pflow.runtime.node_state import (
    NodeStatus, get_node_status, node_succeeded, get_node_output,
    get_node_failure, mark_node_failed, clear_node_failure,
    FAILURE_CATEGORY_SHELL,
)
from pflow.runtime.template_resolver import TemplateResolver
shared = {'a': {'stdout': 'ok'}, 'b': 1}
assert get_node_status(shared, 'a') == NodeStatus.SUCCEEDED
assert node_succeeded(shared, 'a')
assert get_node_status(shared, 'missing') == NodeStatus.ABSENT
mark_node_failed(shared, 'a', category=FAILURE_CATEGORY_SHELL, error='boom')
assert 'a' not in shared
assert get_node_status(shared, 'a') == NodeStatus.FAILED
assert get_node_failure(shared, 'a')['category'] == 'shell_failure'
assert get_node_output(shared, 'a') == {'stdout': 'ok'}
assert TemplateResolver.extract_root_node_id('node.field[0].sub') == 'node'
assert TemplateResolver.extract_root_node_id('data[0]') == 'data'
print('OK')
"
```

---

## Phase 2 — Engine Failure Path Funneling

### Goal
All failure paths funnel through `mark_node_failed` AS THE LAST STEP. `cache_result` and `handle_api_warning` only update `__execution__` bookkeeping at their existing positions; the data move happens at step 17.5 of `_execute_node` (and at the end of `_handle_no_successor` and the except block).

This means `record_trace`, `enrich_llm_cost`, `call_completion_callback` all read `shared[node_id]` directly — the data is still there when they run. They do NOT need migration to `get_node_output` for the main flow. The only consumers that need `get_node_output` are those running AFTER `mark_node_failed` (post-engine error display, sub-workflow extraction, output resolution).

Loop re-entry correctness: when a previously-failed node is revisited, `enforce_loop_guard` calls `clear_node_failure` to strip the stale failure record before the new execution starts.

### Action 1 — `instrumentation.py::enforce_loop_guard`

Located at lines 52-73. Add a `clear_node_failure` call alongside the existing revisit cleanup. Replace:

```python
def enforce_loop_guard(node_id: str, shared: dict) -> dict[str, int]:
    """Increment visit count, raise MaxNodeVisitsError if exceeded.

    Invalidates in-process cache for revisited nodes.

    Returns:
        The visit_counts dict for use by memoization checks.
    """
    visit_counts: dict[str, int] = shared["__execution__"]["node_visit_counts"]
    visit_counts[node_id] = visit_counts.get(node_id, 0) + 1
    if visit_counts[node_id] > MAX_NODE_VISITS:
        raise MaxNodeVisitsError(node_id, visit_counts[node_id], MAX_NODE_VISITS)

    # Invalidate cache for revisited nodes — cache is for workflow resume, not loops
    if visit_counts[node_id] > 1:
        completed = shared["__execution__"]["completed_nodes"]
        if node_id in completed:
            completed.remove(node_id)
            shared["__execution__"]["node_actions"].pop(node_id, None)
            shared["__execution__"]["node_hashes"].pop(node_id, None)

    return visit_counts
```

with:

```python
def enforce_loop_guard(node_id: str, shared: dict) -> dict[str, int]:
    """Increment visit count, raise MaxNodeVisitsError if exceeded.

    Invalidates in-process cache AND clears any stale __failures__ record
    for revisited nodes. Without the failures clear, a node that failed on
    visit 1 and succeeds on visit 2 would still show as FAILED in
    get_node_status() because failures are checked first.

    Returns:
        The visit_counts dict for use by memoization checks.
    """
    visit_counts: dict[str, int] = shared["__execution__"]["node_visit_counts"]
    visit_counts[node_id] = visit_counts.get(node_id, 0) + 1
    if visit_counts[node_id] > MAX_NODE_VISITS:
        raise MaxNodeVisitsError(node_id, visit_counts[node_id], MAX_NODE_VISITS)

    # Invalidate cache + failure record for revisited nodes — both are
    # snapshots of a previous attempt; the new attempt starts fresh.
    if visit_counts[node_id] > 1:
        completed = shared["__execution__"]["completed_nodes"]
        if node_id in completed:
            completed.remove(node_id)
            shared["__execution__"]["node_actions"].pop(node_id, None)
            shared["__execution__"]["node_hashes"].pop(node_id, None)

        from pflow.runtime.node_state import clear_node_failure

        clear_node_failure(shared, node_id)

    return visit_counts
```

### Action 2 — `instrumentation.py::cache_result`

**No change.** Reverts to current pre-plan behavior. It only updates `__execution__["failed_node"]` for the error branch; the actual data move happens at step 17.5 of `_execute_node` (Action 4 below).

The existing function at lines 98-106 stays as-is:

```python
def cache_result(node_id: str, config_hash: str, action: str, shared: dict) -> None:
    """Record node as completed with its config hash."""
    action_str = str(action) if action else "default"
    if not action_str.startswith("error"):
        shared["__execution__"]["completed_nodes"].append(node_id)
        shared["__execution__"]["node_actions"][node_id] = action_str
        shared["__execution__"]["node_hashes"][node_id] = config_hash
    else:
        shared["__execution__"]["failed_node"] = node_id
```

### Action 3 — `instrumentation.py::handle_api_warning`

Located at lines 455-500. Add `mark_node_failed` as the LAST step (after `record_trace` and the progress callback). Do NOT remove the existing `__warnings__` write or `failed_node` assignment near the top — they stay so consumers running mid-function still see the failure state.

Find the function's existing return statement at the bottom (`return "error"`). Replace the entire body with:

```python
def handle_api_warning(
    node_id: str,
    shared: dict,
    warning: str,
    metrics: Any,
    trace_collector: Any,
    start_time: float,
    shared_keys_before: set,
    node_type_name: str,
    node_params: dict,
) -> str:
    """Handle API warning: record failure, return 'error'."""
    if "__warnings__" not in shared:
        shared["__warnings__"] = {}
    shared["__warnings__"][node_id] = warning

    shared["__execution__"]["failed_node"] = node_id

    duration_ms = (time.perf_counter() - start_time) * 1000

    if metrics:
        metrics.record_node_execution(node_id, duration_ms)

    # Call progress callback with warning
    callback = shared.get("__progress_callback__")
    if callable(callback):
        depth = shared.get("_pflow_depth", 0)
        with contextlib.suppress(Exception):
            callback(node_id, "node_warning", warning, depth)

    # Record trace BEFORE the data move so the trace event has the full
    # node output (stdout/stderr/exit_code/etc.).
    record_trace(
        node_id,
        node_type_name,
        shared,
        start_time,
        shared_keys_before,
        {},
        None,
        None,
        node_params,
        trace_collector,
        error=Exception(warning),
    )

    # LAST STEP: archive the node's data to __failures__. Read the node's
    # own error before moving so it's preserved on the failure record.
    from pflow.runtime.node_state import FAILURE_CATEGORY_API_WARNING, mark_node_failed

    node_data = shared.get(node_id, {})
    node_error = node_data.get("error") if isinstance(node_data, dict) else warning
    mark_node_failed(
        shared,
        node_id,
        category=FAILURE_CATEGORY_API_WARNING,
        error=node_error or warning,
        warning=warning,
    )

    return "error"
```

`mark_node_failed` writes to `__warnings__` again with the same value — that's idempotent and harmless.

### Action 4 — `engine.py::_execute_node` happy-path data archive

The HAPPY path of `_execute_node` (lines 175-304) currently ends at `return action`. After step 17 (`call_completion_callback`), if the action is an error string, we need to call `mark_node_failed` to archive the failed data. Find the code immediately before `return action` at line 304:

```python
            ignore_errors = node.params.get("ignore_errors", False) if isinstance(node.params, dict) else False
            call_completion_callback(
                config.node_id,
                shared,
                action,
                duration_ms,
                ignore_errors=ignore_errors,
            )

            return action
```

Replace with:

```python
            ignore_errors = node.params.get("ignore_errors", False) if isinstance(node.params, dict) else False
            call_completion_callback(
                config.node_id,
                shared,
                action,
                duration_ms,
                ignore_errors=ignore_errors,
            )

            # Step 17.5: archive failed node data to __failures__.
            # Runs AFTER trace, metrics, and completion callback so they
            # all see the data in shared[node_id]. After this, the node
            # is in __failures__ and consumers must use get_node_output.
            if str(action).startswith("error"):
                from pflow.runtime.node_state import (
                    FAILURE_CATEGORY_NODE_ERROR,
                    mark_node_failed,
                )

                node_data = shared.get(config.node_id, {})
                node_error = node_data.get("error") if isinstance(node_data, dict) else None
                mark_node_failed(
                    shared,
                    config.node_id,
                    category=FAILURE_CATEGORY_NODE_ERROR,
                    error=node_error,
                )

            return action
```

### Action 5 — `instrumentation.py::record_trace`, `enrich_llm_cost`, `call_completion_callback`

**No changes.** Because `mark_node_failed` now runs at step 17.5 (AFTER all of these), `shared[node_id]` is still populated when they run. The existing `shared.get(node_id)` reads work correctly.

The ONLY exception is loop-retry edge cases where a previous-iteration failure is in `__failures__` while the current iteration hasn't yet written `shared[node_id]`. This is handled by `enforce_loop_guard`'s `clear_node_failure` call (Action 1).

### Action 6 — `engine.py::_execute_node` exception path

Located in `_execute_node` (lines 144-341). Replace the entire except block (lines 306-341) with:

```python
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            if self.metrics:
                self.metrics.record_node_execution(config.node_id, duration_ms)

            enrich_llm_cost(config.node_id, shared)

            error_resolutions = getattr(e, "_partial_resolutions", None) or last_resolutions

            record_trace(
                config.node_id,
                config.node_type_name,
                shared,
                start_time,
                shared_keys_before,
                error_resolutions,
                batch_trace_items,
                child_trace_events,
                node.params,
                self.trace,
                error=e,
            )

            call_completion_callback(config.node_id, shared, "error", duration_ms, error=e)

            # LAST STEP: archive the failed node's data to __failures__.
            # All trace/metrics/callback have already read shared[node_id].
            from pflow.runtime.node_state import (
                FAILURE_CATEGORY_EXCEPTION,
                FAILURE_CATEGORY_TEMPLATE,
                mark_node_failed,
            )

            # Categorize template-resolution ValueErrors specifically so the
            # formatter can render them as template errors, not generic exceptions.
            is_template_error = (
                isinstance(e, ValueError)
                and getattr(e, "_partial_resolutions", None) is not None
            )
            category = FAILURE_CATEGORY_TEMPLATE if is_template_error else FAILURE_CATEGORY_EXCEPTION

            node_data = shared.get(config.node_id, {})
            node_error = node_data.get("error") if isinstance(node_data, dict) else None
            mark_node_failed(
                shared,
                config.node_id,
                category=category,
                error=node_error or str(e),
            )

            if not hasattr(e, "_pflow_node_id"):
                e._pflow_node_id = config.node_id  # type: ignore[attr-defined]

            raise
```

### Action 7 — `engine.py::_handle_no_successor`

Located at lines 111-142. This runs AFTER `_execute_node` has already returned successfully (because the action didn't match any edge). The node has already been added to `completed_nodes` via `cache_result`. We need to roll that back AND archive the data. Replace the entire method with:

```python
    def _handle_no_successor(
        self, last_action: Optional[str], node_id: str, curr: Any, shared: dict[str, Any]
    ) -> Optional[str]:
        """Handle case where no successor matches the current action.

        Distinguishes intentional termination from routing errors:
        - "end" action or no forward (non-error) edges → clean termination
        - Unmatched action with forward edges present → routing failure
        """
        if last_action == "end" or all(k == "error" for k in curr.successors):
            return last_action  # Intentional termination or no forward path

        # Unmatched action — either a node failure with no error handler,
        # or a routing error (code returned action not in declared targets)
        is_node_failure = isinstance(last_action, str) and last_action.startswith("error")
        suggestion = (
            "Add '- on-error: <handler-node>' to handle errors."
            if is_node_failure
            else 'Use next: str = "end" to terminate intentionally.'
        )
        warning_msg = (
            f"Node '{node_id}' returned action '{last_action}' "
            f"but no successor edge matches. Available: {list(curr.successors)}. "
            f"{suggestion}"
        )

        from pflow.runtime.node_state import FAILURE_CATEGORY_ROUTING, mark_node_failed

        # Roll back the success bookkeeping that happened during _execute_node
        # (cache_result added this node to completed_nodes before we noticed
        # the routing failure). Then archive the data.
        invalidate_cache(node_id, shared)
        mark_node_failed(
            shared,
            node_id,
            category=FAILURE_CATEGORY_ROUTING,
            error=warning_msg,
            warning=warning_msg,
        )
        return "error"
```

The `warning=warning_msg` passes the message to both `__warnings__` (so it appears in the warnings list) AND the failure record's `error` field.

### Action 8 — `runner.py` defensive failure annotation (lines 202-213)

No code change. The defensive `failed_node = shared_store.get("__execution__", {}).get("failed_node")` read is fine — `mark_node_failed` already set it before the exception bubbled.

### Verification (Phase 2)

```bash
make check
uv run pytest tests/test_runtime/ -x --tb=short
```

Many tests will fail at this point because consumers still read `shared[failed_node]`. That's expected; Phase 3 fixes them.

---

## Phase 3 — Read-Site Migration

### Goal
All consumers of failed-node data go through `get_node_output` / `get_node_failure`. The coalesce check `root in context` becomes correct without modification.

### Action 1 — `executor_service.py`

Replace the function bodies in this file. Key changes:

**`_extract_node_level_error`** (lines 140-157). The current `if not failed_node or failed_node not in shared_store: return None` no longer triggers because failed nodes aren't in `shared_store` directly. Replace:

```python
def _extract_node_level_error(failed_node: Optional[str], shared_store: dict[str, Any]) -> Optional[str]:
    """Extract error from failed node's output."""
    if not failed_node or failed_node not in shared_store:
        return None

    node_output = shared_store.get(failed_node, {})
    if not isinstance(node_output, dict):
        return None

    # Direct error field (skip None/falsy — MCP responses have "error": null)
    if node_output.get("error"):
        return str(node_output["error"])

    # MCP result format
    if "result" in node_output:
        return _extract_error_from_mcp_result(node_output["result"])

    return None
```

with:

```python
def _extract_node_level_error(failed_node: Optional[str], shared_store: dict[str, Any]) -> Optional[str]:
    """Extract error from failed node's output (succeeded namespace OR __failures__)."""
    if not failed_node:
        return None

    from pflow.runtime.node_state import get_node_failure, get_node_output

    # Prefer the failure record's explicit error field if present
    failure = get_node_failure(shared_store, failed_node)
    if failure and failure.get("error"):
        return str(failure["error"])

    node_output = get_node_output(shared_store, failed_node)
    if not isinstance(node_output, dict):
        return None

    if node_output.get("error"):
        return str(node_output["error"])

    if "result" in node_output:
        return _extract_error_from_mcp_result(node_output["result"])

    return None
```

**`build_error_list`** (lines 18-56). Replace:

```python
    failed_node = error_info.get("failed_node")
    if failed_node:
        node_output = shared_store.get(failed_node, {})
        if isinstance(node_output, dict):
            _enrich_error_from_node_output(context, node_output, category)
```

with:

```python
    failed_node = error_info.get("failed_node")
    if failed_node:
        from pflow.runtime.node_state import get_node_failure, get_node_output

        node_output = get_node_output(shared_store, failed_node) or {}
        if isinstance(node_output, dict):
            _enrich_error_from_node_output(context, node_output, category)

        # Use the explicitly-recorded category from the failure record
        # when available (set at the failure site by mark_node_failed),
        # falling back to the legacy regex-based detection.
        failure = get_node_failure(shared_store, failed_node)
        if failure and failure.get("category"):
            context["category"] = _map_failure_category_to_diagnostic(failure["category"])
```

Add this helper at the top of the module (after imports):

```python
def _map_failure_category_to_diagnostic(failure_category: str) -> str:
    """Map node_state.FAILURE_CATEGORY_* values to Diagnostic context categories.

    The node_state categories are precise ("shell_failure", "api_warning", etc.).
    The Diagnostic categories are coarser ("execution_failure", "template_error", etc.)
    and drive _CATEGORY_TITLES lookup. Some node_state categories collapse to the
    same Diagnostic category.
    """
    return _FAILURE_CATEGORY_MAP.get(failure_category, "execution_failure")


_FAILURE_CATEGORY_MAP: dict[str, str] = {
    "shell_failure": "execution_failure",
    "node_action_error": "execution_failure",
    "api_warning": "api_validation",
    "routing_error": "execution_failure",
    "exception": "execution_failure",
    "template_error": "template_error",
}
```

**`_get_failed_node`** (lines 116-122). No change needed — it reads `__execution__["failed_node"]` which is set by `mark_node_failed`.

**`determine_error_category`** (lines 59-85). Keep as a fallback for callers without a failure record. No change.

### Action 2 — `error_context.py::get_upstream_stderr`

Replace the body from line 67 onwards (`node_ids = ...` through the end of the for-loop):

```python
    node_ids = extract_node_ids_from_template(template)

    stderr_contexts = []
    for node_id in sorted(node_ids):  # Sort for deterministic output
        node_output = shared.get(node_id, {})
        if not isinstance(node_output, dict):
            continue

        stderr = node_output.get("stderr", "")
        ...
```

Replace `node_output = shared.get(node_id, {})` with:

```python
        from pflow.runtime.node_state import get_node_output

        node_output = get_node_output(shared, node_id) or {}
```

Same logic, but reads from either succeeded or failed namespace. Now this function correctly finds upstream stderr from a failed node.

### Action 3 — `extract_node_ids_from_template` in `error_context.py`

Replace lines 17-42 to use the centralized root extraction. Replace:

```python
def extract_node_ids_from_template(template: str) -> set[str]:
    """..."""
    variables = TemplateResolver.extract_variables(template)
    node_ids = set()
    for var in variables:
        # Split on '.' or '[' to get base node ID
        base_id = re.split(r"[\.\[]", var)[0]
        node_ids.add(base_id)
    return node_ids
```

with:

```python
def extract_node_ids_from_template(template: str) -> set[str]:
    """..."""
    variables = TemplateResolver.extract_variables(template)
    return {TemplateResolver.extract_root_node_id(var) for var in variables}
```

(`extract_root_node_id` is added to TemplateResolver in Phase 4.) Then delete the unused `import re` from the file if no other usages remain (verify with grep).

### Action 4 — `workflow_executor.py::_extract_child_error`

Located at lines 370-389. Replace:

```python
        failed_node = child_storage.get("__execution__", {}).get("failed_node")
        if failed_node:
            # Check namespaced node error (e.g., node's own post() set shared["error"])
            node_data = child_storage.get(failed_node)
            if isinstance(node_data, dict):
                error = node_data.get("error")
                if error:
                    return f"Sub-workflow failed at {workflow_path} (node '{failed_node}'): {error}"
            # Check warnings (e.g., routing failures, API warnings)
            warning = child_storage.get("__warnings__", {}).get(failed_node)
            if warning:
                return f"Sub-workflow failed at {workflow_path} (node '{failed_node}'): {warning}"
        return f"Sub-workflow failed at {workflow_path} (returned error action)"
```

with:

```python
        from pflow.runtime.node_state import get_node_failure, get_node_output

        failed_node = child_storage.get("__execution__", {}).get("failed_node")
        if failed_node:
            failure = get_node_failure(child_storage, failed_node)
            if failure and failure.get("error"):
                return f"Sub-workflow failed at {workflow_path} (node '{failed_node}'): {failure['error']}"
            node_data = get_node_output(child_storage, failed_node)
            if isinstance(node_data, dict):
                error = node_data.get("error")
                if error:
                    return f"Sub-workflow failed at {workflow_path} (node '{failed_node}'): {error}"
            warning = child_storage.get("__warnings__", {}).get(failed_node)
            if warning:
                return f"Sub-workflow failed at {workflow_path} (node '{failed_node}'): {warning}"
        return f"Sub-workflow failed at {workflow_path} (returned error action)"
```

### Action 5 — `template_resolution.py::all_variables_from_absent_nodes`

Located at lines 226-234. The current implementation uses `var.split(".")[0].split("[")[0] not in context`. After Phase 2, failed nodes are not in `context` (because they've been moved out of `shared`). So the check is automatically correct for the new invariant **with one important nuance**: a FAILED node should ALSO be treated as absent for optional input injection (because the user wrote `x: int | None = ${a.field ?? b.field}` expecting None when the source isn't usable).

After Phase 2's invariant change, `var.split(".")[0].split("[")[0] not in context` correctly returns True for failed nodes (they're not in `shared`), so the existing logic is right by accident. But to make this explicit, replace with:

```python
def all_variables_from_absent_nodes(template_str: str, context: dict[str, Any]) -> bool:
    """Check if ALL template variables reference nodes that are absent or failed.

    Uses all() not any() — critical for coalesce correctness. After the
    failed-node invariant fix, "absent from context" naturally covers
    both "did not execute" and "executed and failed" because failed
    nodes are moved out of the main namespace.
    """
    from pflow.runtime.template_resolver import TemplateResolver

    variables = TemplateResolver.extract_variables(template_str)
    if not variables:
        return False
    return all(TemplateResolver.extract_root_node_id(var) not in context for var in variables)
```

This eliminates the duplicate root-extraction logic and makes the comment accurate.

### Action 6 — `output_resolver.py` cleanup and structured-reference enrichment

Located in full at `src/pflow/runtime/output_resolver.py`. Three changes:

1. **Delete the duplicate `_ROOT_SPLIT` regex** at lines 17-18:

```python
# Split "node.path[0]" → "node" to extract root node ID
_ROOT_SPLIT = re.compile(r"[.\[]")
```

Delete these lines AND the `import re` if no other usages remain in the file (there are none after this delete).

2. **Update `_diagnose_unresolved_output`** (lines 60-92) to emit three states AND populate structured `unresolved_references` (used by `OutputResolutionError.to_diagnostics` to route through the same template-error renderer as node-param errors):

```python
def _diagnose_unresolved_output(
    source_expr: str,
    normalized: str,
    shared_storage: dict[str, Any],
) -> dict[str, Any]:
    """Diagnose why an output source expression could not be resolved.

    Returns both legacy fields (diagnostics, raw_diagnostics) AND the
    structured unresolved_references list consumed by the new
    template-error rendering pipeline in diagnostic.py.
    """
    from pflow.runtime.engine.template_errors import classify_unresolved_references
    from pflow.runtime.node_state import NodeStatus, get_node_failure, get_node_status
    from pflow.runtime.template_resolver import TemplateResolver

    variables = TemplateResolver.extract_variables(normalized)
    diagnostics: list[str] = []
    raw_diagnostics: list[dict[str, Any]] = []

    for var in sorted(variables):
        root = TemplateResolver.extract_root_node_id(var)
        status = get_node_status(shared_storage, root)

        if status == NodeStatus.ABSENT:
            msg = f"Variable '{var}': node '{root}' did not execute"
            diagnostics.append(msg)
            raw_diagnostics.append({
                "variable": var,
                "root": root,
                "status": "absent",
                "root_absent": True,
            })
        elif status == NodeStatus.FAILED:
            failure = get_node_failure(shared_storage, root) or {}
            err_preview = failure.get("error") or "(no error message)"
            msg = f"Variable '{var}': node '{root}' executed but failed: {err_preview}"
            diagnostics.append(msg)
            raw_diagnostics.append({
                "variable": var,
                "root": root,
                "status": "failed",
                "root_absent": False,
                "failure_category": failure.get("category"),
                "failure_error": failure.get("error"),
                "failure_data": failure.get("data"),
            })
        else:  # SUCCEEDED but path failed
            msg = f"Variable '{var}': node '{root}' executed but path '{var}' not found in its output"
            diagnostics.append(msg)
            raw_diagnostics.append({
                "variable": var,
                "root": root,
                "status": "path_error",
                "root_absent": False,
            })

    # Build structured references using the same classifier as node-param
    # template errors, so OutputResolutionError can route through the same
    # rich rendering pipeline (warning #10 fix).
    structured_refs = classify_unresolved_references(normalized, shared_storage)

    available_keys = sorted(
        k for k in shared_storage
        if not (str(k).startswith("__") and str(k).endswith("__"))
    )

    return {
        "source_expr": source_expr,
        "diagnostics": diagnostics,
        "raw_diagnostics": raw_diagnostics,
        "unresolved_references": structured_refs,
        "template": normalized,
        "available_context_keys": available_keys,
    }
```

3. **Update `populate_declared_outputs`** (lines 95-153) to also pass `_source_line` from `output_config` and `_pflow_workflow_file` from `shared_storage` into the failure dict (used by Phase 6 source-line tracking):

```python
        # Non-coalesce source that can't resolve — record failure with diagnosis
        failure = _diagnose_unresolved_output(source_expr, normalized, shared_storage)
        failure["output_name"] = output_name
        if isinstance(output_config, dict) and "_source_line" in output_config:
            failure["source_line"] = output_config["_source_line"]
        source_file = shared_storage.get("_pflow_workflow_file")
        if source_file:
            failure["source_file"] = source_file
        failures.append(failure)
```

### Action 7 — `execution_state.py` migration

`src/pflow/execution/execution_state.py::build_execution_steps` reads `shared_storage.get(node_id, {})` at line 143 to detect batch metadata and at line 155 (via `_add_shell_node_metadata`) to read shell exit_code/stderr/smart_handled. After the invariant change, failed batch nodes lose their `is_batch`/`batch_total`/`batch_error_details` display, and failed shell nodes lose `has_stderr`/`stderr`/`smart_handled` display in CLI and MCP error formatters.

This file is called by both `success_formatter.py` and `error_formatter.py` — it's the primary path for failed-node display in execution summaries.

In `src/pflow/execution/execution_state.py`, replace the `node_output = shared_storage.get(node_id, {})` line at line 143 with:

```python
        # Add batch metadata if this is a batch node
        # Batch nodes write to shared[node_id] with batch_metadata key.
        # Use get_node_output to read from succeeded OR failed namespace.
        from pflow.runtime.node_state import get_node_output

        node_output = get_node_output(shared_storage, node_id) or {}
        if isinstance(node_output, dict) and "batch_metadata" in node_output:
```

The downstream `_add_shell_node_metadata(step, node_output, status)` call at line 155 receives the same `node_output` variable — no further changes needed. `_add_shell_node_metadata`'s stderr-warning detection is gated to `status == "completed"` (line 30 of that file), so failed nodes naturally don't trigger stderr-warning surfacing — but the `smart_handled` detection at line 35 has no status guard, which is correct because a smart-handled node never reaches the failed branch (it returns "default", not "error").

### Verification (Phase 3)

```bash
make check
uv run pytest tests/test_runtime/test_template_coalesce.py -x
uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace
```

The repro should now print `fallback-content`. Existing template coalesce tests should still pass (none of them set `__failures__` in their hand-built contexts).

---

## Phase 4 — Replace remaining `_ROOT_SPLIT_PATTERN` consumers

### Goal
`extract_root_node_id` was added in Phase 1 (Action 2). Now sweep the remaining direct reaches into the private `_ROOT_SPLIT_PATTERN` from outside `template_resolver.py`.

### Action 1 — `core/workflow/data_flow.py`

Lines 161-162 currently reach into the private `TemplateResolver._ROOT_SPLIT_PATTERN`. Replace with `TemplateResolver.extract_root_node_id(ref)`.

### Action 2 — `engine/template_errors.py`

Line 301 currently uses `TemplateResolver._ROOT_SPLIT_PATTERN.split(operand)[0]`. This file is rewritten wholesale in Phase 5; the new code uses `extract_root_node_id`. No separate change needed here.

### Verification (Phase 4)

```bash
uv run python -c "
from pflow.runtime.template_resolver import TemplateResolver as T
assert T.extract_root_node_id('node') == 'node'
assert T.extract_root_node_id('node.field') == 'node'
assert T.extract_root_node_id('node.field[0].sub') == 'node'
assert T.extract_root_node_id('data[0]') == 'data'
print('OK')
"
make check
```

---

## Phase 5 — Structured Template Error Diagnostics

### Goal
Replace `build_enhanced_template_error` (returns raw multi-line string) with `build_template_error_diagnostic` (returns a `Diagnostic` with structured `context`). Render template errors via context blocks in `diagnostic.py`. Eliminate the four "did not execute" wording variants.

### Background — what gets rendered today

`diagnostic.py::_format_error_diagnostic` renders in this order:
1. Title (line 142): `"Error N: <title>"`
2. Empty line
3. Message (line 146)
4. Location `At: <node>, <path>, line <N>` (line 151)
5. Context blocks via `_format_all_context_blocks` (line 154)
6. Suggestions (lines 159-167)
7. Verbose hint (lines 169-177)

The new template-error block plugs into `_format_all_context_blocks` (line 194-213) which already dispatches on `category == "template_error"`. We replace the existing `_format_template_error_lines` (line 246-265) with one that consumes the new structured fields.

### Action 1 — Define the structured context shape

The Diagnostic context for a template error will have these fields:

```python
context = {
    "category": "template_error",
    "param_key": "command",                      # str — the parameter that failed
    "template": "wc -l ${primary.stdout}",       # str — the original template
    "source_file": "workflow.pflow.md",          # Optional[str]
    "source_line": 23,                            # Optional[int] — set by Phase 6
    "unresolved_references": [
        {
            "var": "primary.stdout",              # str — the variable expression
            "root": "primary",                    # str — the root node id
            "status": "failed",                   # "absent" | "failed" | "path_error"
            "in_coalesce": True,                  # bool — was this an operand of ${a ?? b}?
            "coalesce_expr": "primary.stdout ?? fallback.stdout",  # Optional[str]
            "failure": {                          # Optional[dict] — only for status="failed"
                "category": "shell_failure",
                "error": "Command failed with exit code 1",
                "exit_code": 1,
                "command": "exit 1",
                "stdout": "",
                "stderr": "",
            },
            "available_fields": ["stdout", "stderr", "exit_code"],  # Optional, only for status="path_error"
            "did_you_mean": "primary.stdout",     # Optional, only when path_error has a typo match
        },
        ...
    ],
    "available_context_keys": ["fallback", "primary", ...],   # list[str], filtered, sorted
}
```

### Action 2 — Rewrite `template_errors.py`

Replace the entire content of `src/pflow/runtime/engine/template_errors.py` with the following. This deletes `build_enhanced_template_error`, `diagnose_coalesce`, `_append_error_context`, `format_available_keys`, `generate_suggestions`, `detect_json_parse_hints` (but keeps `build_type_error_message` and `build_json_parse_error_message` since they handle a different error class — type mismatches — which is unrelated to the failed-node fix).

```python
"""Template error message formatting.

Builds detailed, actionable error messages for template resolution failures:
- Type mismatches (dict/list where str expected, malformed JSON)
- Unresolved template variables — produces a structured Diagnostic with
  per-reference status (absent / failed / path_error)
- Coalesce expression diagnostics

The unresolved-template path produces a Diagnostic whose context contains
structured ``unresolved_references`` data. The Diagnostic context blocks
in ``core/diagnostic.py`` render this into the agent-actionable format.
"""

from __future__ import annotations

from typing import Any, Optional

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.runtime.node_state import NodeStatus, get_node_failure, get_node_status
from pflow.runtime.template_resolver import TemplateResolver


def build_type_error_message(
    param_key: str,
    resolved_value: Any,
    template_str: str,
    expected_type: str,
    actual_type: str,
) -> str:
    """Build detailed, actionable error message for type mismatch.

    Returns a plain string used in a ValueError. Type mismatch errors are
    a different class from unresolved-template errors and don't need the
    structured Diagnostic treatment.
    """
    var_match = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.search(template_str)
    var_name = var_match.group(1) if var_match else "variable"

    error_msg = (
        f"Parameter '{param_key}' expects {expected_type} but received {actual_type}\n\n"
        f"Template used: {template_str}\n"
        f"Resolved to: {actual_type} object\n"
    )
    error_msg += "\n\U0001f4a1 Common fixes:\n"
    error_msg += "  1. Serialize to JSON (recommended):\n"
    error_msg += f'     {param_key}: "{template_str}"\n\n'
    if isinstance(resolved_value, dict):
        error_msg += "  2. Access a specific field:\n"
        error_msg += f"     {param_key}: ${{{var_name}.field_name}}\n\n"
    elif isinstance(resolved_value, list):
        error_msg += "  2. Access a specific item:\n"
        error_msg += f"     {param_key}: ${{{var_name}[0]}}\n\n"
    error_msg += "  3. Combine with text:\n"
    error_msg += f'     {param_key}: "Summary: {template_str}"\n'

    if isinstance(resolved_value, dict) and resolved_value:
        keys = list(resolved_value.keys())[:10]
        error_msg += f"\n\nAvailable fields in {var_name}:\n"
        for key in keys:
            error_msg += f"  - {key}\n"
        if len(resolved_value) > 10:
            remaining = len(resolved_value) - 10
            error_msg += f"  ... and {remaining} more\n"
    elif isinstance(resolved_value, list):
        error_msg += f"\n\n{var_name} contains {len(resolved_value)} items\n"
        if len(resolved_value) > 0:
            error_msg += f"Access items with: ${{{var_name}[0]}}, ${{{var_name}[1]}}, etc.\n"

    return error_msg


def build_json_parse_error_message(
    param_key: str,
    resolved_value: str,
    template_str: str,
    expected_type: str,
    trimmed: str,
) -> str:
    """Build detailed error message for failed JSON parsing.

    Same plain-string approach as build_type_error_message — JSON parse
    errors are a different class from unresolved-template errors.
    """
    preview = trimmed[:200]
    if len(trimmed) > 200:
        preview += "..."

    issues = []
    if "'" in trimmed:
        issues.append("Single quotes detected (use double quotes: \"key\" not 'key')")
    if trimmed.count("{") != trimmed.count("}"):
        issues.append("Mismatched braces { }")
    if trimmed.count("[") != trimmed.count("]"):
        issues.append("Mismatched brackets [ ]")
    if ",}" in trimmed or ",]" in trimmed:
        issues.append("Trailing comma before closing brace/bracket")

    error_lines = [
        f"Parameter '{param_key}' expects {expected_type} but received malformed JSON string.",
        "",
        f"Template: {template_str}",
        f"Value preview: {preview}",
        "",
        f"The string starts with '{trimmed[0]}' suggesting JSON, but failed to parse.",
    ]
    if issues:
        error_lines.append("")
        error_lines.append("Detected issues:")
        for issue in issues:
            error_lines.append(f"  - {issue}")
    error_lines.extend([
        "",
        "Common JSON formatting issues:",
        "  - Missing closing brace/bracket",
        "  - Single quotes instead of double quotes",
        "  - Trailing commas in arrays/objects",
        "  - Unescaped special characters",
        "  - Missing quotes around object keys",
        "",
        "Fix: Ensure the source outputs valid JSON.",
        f"Test with: echo '{template_str}' | jq '.'",
    ])
    return "\n".join(error_lines)


# ---------------------------------------------------------------------------
# Structured unresolved-template diagnostic
# ---------------------------------------------------------------------------


def classify_unresolved_references(
    template_str: str,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Classify every variable reference in a template by execution status.

    Returns a list of dicts (one per unique variable) with the structured
    fields described in the Task 148 plan: var, root, status, in_coalesce,
    coalesce_expr, failure, available_fields, did_you_mean.

    Variables that resolve successfully are NOT included.
    """
    references: list[dict[str, Any]] = []
    seen_vars: set[str] = set()

    for match in TemplateResolver.TEMPLATE_PATTERN.finditer(template_str):
        expr = match.group(1)
        operands = TemplateResolver.split_coalesce_operands(expr)
        is_coalesce = len(operands) > 1

        for operand in operands:
            if operand in seen_vars:
                continue
            seen_vars.add(operand)

            ref = _classify_one_reference(
                operand,
                context,
                in_coalesce=is_coalesce,
                coalesce_expr=expr if is_coalesce else None,
            )
            if ref is not None:
                references.append(ref)

    return references


def _classify_one_reference(
    var: str,
    context: dict[str, Any],
    *,
    in_coalesce: bool,
    coalesce_expr: Optional[str],
) -> Optional[dict[str, Any]]:
    """Classify a single variable reference. Returns None if it resolves OK."""
    root = TemplateResolver.extract_root_node_id(var)
    status = get_node_status(context, root)

    if status == NodeStatus.SUCCEEDED:
        if TemplateResolver.variable_exists(var, context):
            return None  # resolves OK, skip
        return {
            "var": var,
            "root": root,
            "status": "path_error",
            "in_coalesce": in_coalesce,
            "coalesce_expr": coalesce_expr,
            "available_fields": _get_available_fields(root, context),
            "did_you_mean": _suggest_field_correction(var, root, context),
            "peer_suggestions": _find_peer_nodes_with_field(root, var, context),
        }

    if status == NodeStatus.FAILED:
        failure = get_node_failure(context, root) or {}
        data = failure.get("data") or {}
        # Even though the node failed, its data dict may have a known shape
        # (shell nodes always have stdout/stderr/exit_code keys). If the
        # variable's field doesn't exist in that shape, AND a close match
        # does, surface as a SECONDARY hint — primary status stays "failed"
        # because that's the dominant issue. This eliminates a wasted
        # iteration cycle for AI agents that have both a typo AND a failure.
        secondary_hint = _suggest_field_correction(var, root, {root: data}) if isinstance(data, dict) else None
        return {
            "var": var,
            "root": root,
            "status": "failed",
            "in_coalesce": in_coalesce,
            "coalesce_expr": coalesce_expr,
            "failure": {
                "category": failure.get("category"),
                "error": failure.get("error"),
                "data": _extract_failure_display_data(failure.get("category"), data),
            },
            "peer_suggestions": _find_peer_nodes_with_field(root, var, context),
            "secondary_hint": secondary_hint,
        }

    # ABSENT
    return {
        "var": var,
        "root": root,
        "status": "absent",
        "in_coalesce": in_coalesce,
        "coalesce_expr": coalesce_expr,
        "peer_suggestions": _find_peer_nodes_with_field(root, var, context),
    }


def _get_available_fields(node_id: str, context: dict[str, Any]) -> list[str]:
    """Return the dict keys of a node's output, sorted."""
    output = context.get(node_id)
    if isinstance(output, dict):
        return sorted(str(k) for k in output.keys() if not str(k).startswith("_"))
    return []


def _find_peer_nodes_with_field(
    root: str, var: str, context: dict[str, Any], max_results: int = 3
) -> list[str]:
    """Find sibling nodes whose output dict contains the same field path.

    Used to suggest concrete fallback candidates in coalesce fix suggestions.
    Without this, fix messages contain placeholders like ``<fallback>`` that
    AI agents cannot paste-and-go.
    """
    parts = var.split(".", 1)
    field_name: Optional[str] = None
    if len(parts) == 2:
        field_name = parts[1].split(".", 1)[0].split("[", 1)[0]

    candidates: list[str] = []
    for key, value in context.items():
        if key == root:
            continue
        key_str = str(key)
        if key_str.startswith("__") and key_str.endswith("__"):
            continue
        if field_name is None:
            if isinstance(value, dict):
                candidates.append(key_str)
        elif isinstance(value, dict) and field_name in value:
            candidates.append(key_str)
        if len(candidates) >= max_results:
            break
    return candidates


def _extract_failure_display_data(
    category: Optional[str], data: Any
) -> dict[str, Any]:
    """Extract a display-relevant subset of failure data based on category.

    Different node types write different fields to their namespace. Hardcoding
    shell fields would lose HTTP/MCP/LLM diagnostic info. Dispatch on category
    and pick the most useful fields per type.
    """
    if not isinstance(data, dict):
        return {}

    if category == "shell_failure":
        return {
            k: data[k]
            for k in ("exit_code", "command", "stdout", "stderr")
            if data.get(k) is not None
        }

    # HTTP-like (api_warning often comes from http nodes)
    if "status_code" in data or "response" in data:
        return {
            k: data[k]
            for k in (
                "status_code", "url", "method", "response", "response_body",
                "response_headers",
            )
            if data.get(k) is not None
        }

    # MCP node — server/tool/error_details shape
    if "error_details" in data or ("server" in data and "tool" in data):
        return {
            k: data[k]
            for k in ("server", "tool", "error_details", "result")
            if data.get(k) is not None
        }

    # Generic fallback: include scalar fields with reasonable size
    return {
        k: v
        for k, v in data.items()
        if not str(k).startswith("_")
        and isinstance(v, (str, int, float, bool))
        and len(str(v)) < 500
    }


def _suggest_field_correction(var: str, root: str, context: dict[str, Any]) -> Optional[str]:
    """Suggest a field name correction using close-string matching."""
    output = context.get(root)
    if not isinstance(output, dict):
        return None
    parts = var.split(".", 1)
    if len(parts) != 2:
        return None
    field_path = parts[1]
    field_name = field_path.split(".", 1)[0].split("[", 1)[0]
    available = list(output.keys())
    if field_name in available:
        return None  # Not a typo
    import difflib

    matches = difflib.get_close_matches(field_name, [str(k) for k in available], n=1, cutoff=0.6)
    if matches:
        corrected_path = field_path.replace(field_name, matches[0], 1)
        return f"{root}.{corrected_path}"
    return None


def build_template_error_diagnostic(
    param_key: str,
    template: Any,
    context: dict[str, Any],
    *,
    node_id: Optional[str] = None,
    source_file: Optional[str] = None,
    source_line: Optional[int] = None,
) -> Diagnostic:
    """Build a fully-structured Diagnostic for an unresolved template.

    The Diagnostic.message is a one-line summary (kept short for identity-hash
    distinctness). All rich data lives in context.unresolved_references and
    is rendered by diagnostic.py::_format_template_error_lines.
    """
    template_str = str(template)
    references = classify_unresolved_references(template_str, context)

    available_keys = sorted(
        k for k in context if not (str(k).startswith("__") and str(k).endswith("__"))
    )

    # Build a one-line message specific enough that two distinct template
    # errors don't dedupe via Diagnostic.__eq__/__hash__.
    if references:
        ref_summary = ", ".join(f"${{{r['var']}}}" for r in references[:3])
        if len(references) > 3:
            ref_summary += f" (+{len(references) - 3} more)"
        message = f"Cannot resolve template in '{param_key}': {ref_summary}"
    else:
        message = f"Cannot resolve template in '{param_key}'"

    context_dict: dict[str, Any] = {
        "category": "template_error",
        "param_key": param_key,
        "template": template_str,
        "unresolved_references": references,
        "available_context_keys": available_keys,
    }
    if source_file is not None:
        context_dict["source_file"] = source_file
    if source_line is not None:
        context_dict["source_line"] = source_line

    return Diagnostic(
        severity=Severity.ERROR,
        message=message,
        title="Template Resolution Failed",
        node_id=node_id,
        source="runtime",
        context=context_dict,
    )
```

### Action 3 — Update `template_resolution.py` to raise structured diagnostics

In `src/pflow/runtime/engine/template_resolution.py`:

1. Update the import at line 19-23 from:

```python
from .template_errors import (
    build_enhanced_template_error,
    build_json_parse_error_message,
    build_type_error_message,
)
```

to:

```python
from .template_errors import (
    build_json_parse_error_message,
    build_template_error_diagnostic,
    build_type_error_message,
)
```

2. Update the unresolved-template raise block at lines 378-400. Replace:

```python
        if is_unresolved:
            error_msg = build_enhanced_template_error(key, template, context)

            if template_config.resolution_mode == "strict":
                from .error_context import get_upstream_stderr

                upstream_context = get_upstream_stderr(str(template), context)
                if upstream_context:
                    error_msg += upstream_context
                # Store partial resolutions on exception for trace capture
                partial = {
                    k: {"template": template_config.template_params[k], "resolved": resolved_params[k]}
                    for k in resolved_params
                }
                exc = ValueError(error_msg)
                exc._partial_resolutions = partial  # type: ignore[attr-defined]
                raise exc
            else:
                template_errors.append({
                    "message": error_msg,
                    "unresolved": [key],
                    "template": template,
                })
```

with:

```python
        if is_unresolved:
            diagnostic = build_template_error_diagnostic(
                key,
                template,
                context,
                node_id=node_id,
                source_file=_extract_source_file(shared),
                source_line=_extract_source_line(template_config, key),
            )

            if template_config.resolution_mode == "strict":
                # Store partial resolutions on exception for trace capture
                partial = {
                    k: {"template": template_config.template_params[k], "resolved": resolved_params[k]}
                    for k in resolved_params
                }
                exc = ValueError(diagnostic.message)
                exc._partial_resolutions = partial  # type: ignore[attr-defined]
                exc._pflow_template_diagnostic = diagnostic  # type: ignore[attr-defined]
                raise exc
            else:
                template_errors.append({
                    "message": diagnostic.message,
                    "unresolved": [key],
                    "template": template,
                    "diagnostic": diagnostic,
                })
```

Then add these helpers at module bottom:

```python
def _extract_source_file(shared: dict[str, Any]) -> Optional[str]:
    """Extract the workflow source file path for error messages."""
    return shared.get("_pflow_workflow_file")


def _extract_source_line(template_config: TemplateConfig, key: str) -> Optional[int]:
    """Extract the source line for a template parameter, if tracked.

    The compiler stores _<key>_source_line in static_params for parameters
    written via code blocks. For inline params, this is None.
    """
    line_key = f"_{key}_source_line"
    line = template_config.static_params.get(line_key)
    return int(line) if isinstance(line, int) else None
```

Note: `_pflow_template_diagnostic` is read in Phase 5 Action 5 to surface the structured Diagnostic through `exception_to_diagnostics`.

### Action 4 — Update `diagnostic.py::_format_template_error_lines`

Replace the function at lines 246-265 with the new structured renderer:

```python
def _format_template_error_lines(context: dict[str, Any]) -> list[str]:
    """Render structured unresolved_references for template errors.

    Reads context.unresolved_references built by template_errors.classify_unresolved_references.
    Each reference becomes a block with status-specific format and fix suggestions.

    Also handles the "all coalesce operands failed" case (warning #6) by emitting
    a summary fix block AFTER the per-reference loop.
    """
    refs = context.get("unresolved_references")
    if not refs:
        # Backward path: legacy template errors with available_fields
        return _format_legacy_template_error_lines(context)

    template = context.get("template", "")
    param_key = context.get("param_key", "<unknown>")

    lines: list[str] = ["", f"  In parameter '{param_key}':", f"    {template}", ""]

    for ref in refs:
        lines.extend(_format_one_reference(ref))
        lines.append("")

    # Case 2 fix: all operands of one coalesce expression failed.
    # The per-reference loop's "To fix" suggestions are skipped for
    # in_coalesce refs (each individual fix would just say "use coalesce"
    # which is what we already did). Surface a single summary block here.
    all_in_one_failed_coalesce = (
        len(refs) >= 2
        and all(r.get("in_coalesce") and r.get("status") == "failed" for r in refs)
        and len({r.get("coalesce_expr") for r in refs}) == 1
    )
    if all_in_one_failed_coalesce:
        coalesce_expr = refs[0].get("coalesce_expr") or ""
        # Pick a peer suggestion from any ref's peer_suggestions
        peer_pool: list[str] = []
        for r in refs:
            for p in r.get("peer_suggestions") or []:
                if p not in peer_pool:
                    peer_pool.append(p)
        sample_field = _extract_field_name(refs[0].get("var", "field"))
        peer_example = peer_pool[0] if peer_pool else "<another-node>"
        lines.append("  All coalesce operands failed. To fix:")
        lines.append(f"    • Add another fallback: ${{{coalesce_expr} ?? {peer_example}.{sample_field}}}")
        lines.append("    • Investigate the underlying failures (see Error/Stderr above)")
        lines.append("    • If aggregate failure is acceptable, add `- on-error: <handler>`")
        lines.append("      on the node that consumes this output")
        lines.append("")

    # Available context keys (always show if any unresolved refs — agents need
    # this to write coalesce fixes regardless of whether the ref was absent,
    # failed, or path_error)
    keys = context.get("available_context_keys") or []
    if refs and keys:
        display = keys[:20]
        lines.append("  Available nodes in context:")
        for key in display:
            lines.append(f"    - {key}")
        if len(keys) > 20:
            lines.append(f"    ... and {len(keys) - 20} more")

    return lines


def _format_one_reference(ref: dict[str, Any]) -> list[str]:
    """Render one reference block based on its status."""
    var = ref.get("var", "")
    root = ref.get("root", "")
    status = ref.get("status", "")
    in_coalesce = ref.get("in_coalesce", False)
    peers = ref.get("peer_suggestions") or []

    bullet = "✗" if status != "succeeded" else "✓"
    header = f"  {bullet} ${{{var}}}"

    if status == "absent":
        lines = [
            header,
            f"      → Node '{root}' did not execute (branch not taken or not declared)",
        ]
        if not in_coalesce and peers:
            field = _extract_field_name(var)
            lines.append("")
            lines.append("        To fix:")
            lines.append(f"          • Use coalesce: ${{{var} ?? {peers[0]}.{field}}}")
        return lines

    if status == "failed":
        failure = ref.get("failure") or {}
        category = failure.get("category", "")
        error = failure.get("error") or "(no error message)"
        data = failure.get("data") or {}

        lines = [
            header,
            f"      → Node '{root}' executed but FAILED ({_describe_failure_category(category)})",
            f"        Error: {error}",
        ]
        lines.extend(_render_failure_data_block(category, data))

        # Secondary hint: typo on a failed node (warning #8)
        secondary_hint = ref.get("secondary_hint")
        if secondary_hint:
            lines.append("")
            lines.append(
                f"      ⚠ Additional issue: field '{_extract_field_name(var)}' may also be a typo"
            )
            lines.append(f"        Did you mean: ${{{secondary_hint}}}?")
            lines.append("        (this won't resolve even if the failure is fixed)")

        # "To fix" block — only when not already inside a coalesce
        # (Case 2 emits a summary block at the parent level instead)
        if not in_coalesce:
            field = _extract_field_name(var)
            lines.append("")
            lines.append("        To fix:")
            if peers:
                primary_peer = peers[0]
                fix_template = f"${{{var} ?? {primary_peer}.{field}}}"
                lines.append(f"          • Use coalesce: {fix_template}")
                if len(peers) > 1:
                    other_peers = ", ".join(peers[1:])
                    lines.append(f"            (other peers with this field: {other_peers})")
            else:
                lines.append(
                    f"          • Use coalesce with a peer node: ${{{var} ?? <peer>.{field}}}"
                )
            lines.append(
                f"          • Add `- on-error: <handler>` to node '{root}' so the workflow"
            )
            lines.append("            routes to a handler on failure")
        return lines

    if status == "path_error":
        available = ref.get("available_fields") or []
        suggestion = ref.get("did_you_mean")
        lines = [
            header,
            f"      → Node '{root}' executed but does not produce field '{_extract_field_name(var)}'",
        ]
        if available:
            display = available[:8]
            field_list = ", ".join(display)
            if len(available) > 8:
                field_list += f", ... ({len(available) - 8} more)"
            lines.append(f"        Available fields: {field_list}")
        if suggestion:
            lines.append("")
            lines.append("        To fix:")
            lines.append(f"          • Did you mean: ${{{suggestion}}}")
        return lines

    return [header, f"      → unknown status: {status}"]


def _render_failure_data_block(category: str, data: dict[str, Any]) -> list[str]:
    """Render the failure detail block, dispatched by category.

    Different node types write different diagnostic fields. Hardcoding shell
    fields (the original plan) loses HTTP/MCP/LLM diagnostic info entirely.
    """
    if not isinstance(data, dict):
        return []
    if category == "shell_failure":
        return _render_shell_failure_block(data)
    if "status_code" in data or "response" in data:
        return _render_http_failure_block(data)
    if "server" in data and "tool" in data:
        return _render_mcp_failure_block(data)
    return _render_generic_failure_block(data)


def _render_shell_failure_block(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if (command := data.get("command")):
        cmd_preview = command[:200] + "..." if len(command) > 200 else command
        lines.append(f"        Command: {cmd_preview}")
    if (exit_code := data.get("exit_code")) is not None:
        lines.append(f"        Exit code: {exit_code}")
    if (stderr := data.get("stderr")):
        stderr_preview = stderr[:200] + "..." if len(stderr) > 200 else stderr
        lines.append(f"        Stderr: {stderr_preview}")
    return lines


def _render_http_failure_block(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if (status_code := data.get("status_code")) is not None:
        lines.append(f"        Status: {status_code}")
    if (url := data.get("url")):
        lines.append(f"        URL: {url}")
    if (method := data.get("method")):
        lines.append(f"        Method: {method}")
    if (response := data.get("response") or data.get("response_body")):
        resp_preview = str(response)[:300]
        if len(str(response)) > 300:
            resp_preview += "..."
        lines.append(f"        Response: {resp_preview}")
    return lines


def _render_mcp_failure_block(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if (server := data.get("server")):
        lines.append(f"        Server: {server}")
    if (tool := data.get("tool")):
        lines.append(f"        Tool: {tool}")
    if (details := data.get("error_details")):
        lines.append(f"        Details: {details}")
    return lines


def _render_generic_failure_block(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in list(data.items())[:6]:
        if str(key).startswith("_") or value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            preview = str(value)[:200]
            lines.append(f"        {key}: {preview}")
    return lines


def _describe_failure_category(category: str) -> str:
    """Map node_state failure categories to human-readable descriptions."""
    return {
        "shell_failure": "shell command failed",
        "node_action_error": "node returned error action",
        "api_warning": "API warning",
        "routing_error": "no matching successor",
        "exception": "raised exception",
        "template_error": "template error",
    }.get(category, category or "unknown")


def _extract_field_name(var: str) -> str:
    """Extract the leaf field name from a variable path."""
    if "." not in var:
        return var
    return var.split(".", 1)[1]


def _format_legacy_template_error_lines(context: dict[str, Any]) -> list[str]:
    """Legacy format kept for fallback/compat with non-template-error categories.

    The original _format_template_error_lines logic — only fires when
    unresolved_references is not present (e.g., for executor_service-built
    template errors that still use available_fields directly).
    """
    available = context.get("available_fields")
    if not available:
        return []

    total = context.get("available_fields_total", len(available))
    lines = [
        "",
        f"  Available fields in node (showing {min(len(available), 5)} of {total}):",
    ]
    for field_name in available[:5]:
        lines.append(f"    - {field_name}")
    if len(available) > 5:
        lines.append(f"    ... and {len(available) - 5} more (in error details)")
    if context.get("available_fields_truncated"):
        lines.append("")
        lines.append("  📁 Complete field list available in trace file")
        lines.append("     ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json")
    return lines
```

### Action 5 — Update `diagnostic.py::_builtin_exception_diagnostic` to surface template diagnostics

The existing ValueError branch (lines 394-404) builds a generic execution_failure Diagnostic. When the ValueError carries `_pflow_template_diagnostic`, we should return THAT instead. Replace lines 394-404:

```python
    if isinstance(exception, ValueError):
        category = "execution_failure" if annotated_node_id else "validation"
        title = "Execution Failed" if annotated_node_id else "Validation Error"
        return Diagnostic(
            severity=Severity.ERROR,
            message=str(exception),
            title=title,
            node_id=annotated_node_id,
            source="runtime",
            context={"category": category},
        )
```

with:

```python
    if isinstance(exception, ValueError):
        # Template resolution errors carry a pre-built structured Diagnostic.
        attached = getattr(exception, "_pflow_template_diagnostic", None)
        if isinstance(attached, Diagnostic):
            return attached

        category = "execution_failure" if annotated_node_id else "validation"
        title = "Execution Failed" if annotated_node_id else "Validation Error"
        return Diagnostic(
            severity=Severity.ERROR,
            message=str(exception),
            title=title,
            node_id=annotated_node_id,
            source="runtime",
            context={"category": category},
        )
```

### Action 6 — Update `diagnostic.py::_format_location` to surface source_file/line

The existing `_format_location` (lines 182-191) reads `context["path"]` and `context["line"]`. Add fallback to `source_file` / `source_line` so the new template-error context keys are rendered. Replace:

```python
def _format_location(diagnostic: Diagnostic, context: dict[str, Any]) -> str | None:
    """Build the At: location line from node_id, path, and line."""
    parts: list[str] = []
    if diagnostic.node_id:
        parts.append(f"node '{diagnostic.node_id}'")
    if (path := context.get("path")) and path != "root":
        parts.append(path)
    if (line := context.get("line")) is not None:
        parts.append(f"line {line}")
    return ", ".join(parts) if parts else None
```

with:

```python
def _format_location(diagnostic: Diagnostic, context: dict[str, Any]) -> str | None:
    """Build the At: location line from node_id, path, and line."""
    parts: list[str] = []
    if diagnostic.node_id:
        parts.append(f"node '{diagnostic.node_id}'")
    path = context.get("path") or context.get("source_file")
    if path and path != "root":
        parts.append(str(path))
    line = context.get("line")
    if line is None:
        line = context.get("source_line")
    if line is not None:
        parts.append(f"line {line}")
    return ", ".join(parts) if parts else None
```

### Action 7 — Rewrite `OutputResolutionError.to_diagnostics` for structured rendering

This addresses warning #10: today output-source resolution errors render through the legacy plain-string `explanation` path, while node-param template errors render through the new structured `unresolved_references` block. Same underlying bug class, two quality tiers. Fix: convert the `failures` list into a `unresolved_references` shape and emit `category="template_error"` so the same renderer applies.

In `src/pflow/core/user_errors.py`, replace the entire `to_diagnostics` method (lines 129-151) with:

```python
    def to_diagnostics(self) -> list[Diagnostic]:
        # Aggregate structured references across all failures so the new
        # _format_template_error_lines renderer can produce the rich format.
        # Also keep the legacy fields for backward compat with consumers
        # that read context.failures directly.
        all_refs: list[dict[str, Any]] = []
        for f in self.failures:
            structured = f.get("unresolved_references") or []
            for ref in structured:
                # Inject is_output_resolution marker so the renderer can adapt
                # the "To fix" wording for output sources vs node params.
                enriched = dict(ref)
                enriched.setdefault("is_output_source", True)
                all_refs.append(enriched)

        # Build a combined template string for the header (one line per output)
        templates = [f.get("source_expr", "") for f in self.failures]
        combined_template = "; ".join(t for t in templates if t)

        # Param key summary
        if len(self.failures) == 1:
            param_key = f"output '{self.failures[0]['output_name']}'"
        else:
            names = ", ".join(f"'{f['output_name']}'" for f in self.failures)
            param_key = f"outputs {names}"

        # Build the structured context
        output_context: dict[str, Any] = {
            "category": "template_error",
            "param_key": param_key,
            "template": combined_template,
            "unresolved_references": all_refs,
            "available_context_keys": (
                self.failures[0].get("available_context_keys", []) if self.failures else []
            ),
            "explanation": self.explanation,
            "technical_details": self.technical_details,
            "failures": self.failures,  # legacy field, preserved for any direct readers
            "is_output_resolution": True,  # marker for renderer/consumers
        }
        if self.failures:
            first = self.failures[0]
            if first.get("output_name"):
                output_context["output_name"] = first["output_name"]
            if first.get("source_expr"):
                output_context["source_expr"] = first["source_expr"]
            if first.get("source_line") is not None:
                output_context["source_line"] = first["source_line"]
            if first.get("source_file"):
                output_context["source_file"] = first["source_file"]

        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.explanation,
                title=self.title,
                suggestions=self.suggestions or None,
                source="runtime",
                context=output_context,
            )
        ]
```

This makes output-source resolution failures use the SAME renderer as node-param template errors. The category change from `"runtime"` to `"template_error"` also fixes the original `_CATEGORY_TITLES` bug — `"runtime"` wasn't a valid category and fell back to generic `"Error"`.

**Required import**: at the top of `user_errors.py`, add `from typing import Any` to the existing typing import if not already present.

### Action 8 — Improve `runner._extract_runtime_warnings` canned suggestions

In `src/pflow/execution/runner.py` at lines 480-483, replace:

```python
                    suggestions=[
                        "Inspect this node's output and upstream inputs to determine whether the warning is expected."
                    ],
```

with:

```python
                    suggestions=[
                        f"Inspect '{node_id}' upstream inputs and output to verify the warning is expected.",
                        "If unintended, fix the upstream data or add error handling to this node.",
                    ],
```

And at lines 495-497, replace:

```python
                    suggestions=[
                        "Fix unresolved template references, or use ?? fallback for branch-dependent outputs."
                    ],
```

with:

```python
                    suggestions=[
                        f"Fix unresolved template references in '{node_id}' or use the ?? fallback "
                        "for branch-dependent outputs (e.g. ${a.field ?? b.field})."
                    ],
```

### Verification (Phase 5)

```bash
make check
uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace
# expected: fallback-content (output)

# Test the new error path: edit repro to remove the coalesce
cat > /tmp/repro-no-coalesce.pflow.md <<'EOF'
# Coalesce Fallback Bug

Primary fails, fallback runs. Output references primary directly.

## Steps

### primary

Primary fails.

- type: shell
- on-error: fallback
- next: end

```shell command
exit 1
```

### fallback

Fallback succeeds.

- type: shell
- next: end

```shell command
echo "fallback-content"
```

## Outputs

### content

Whichever path produced output.

- source: ${primary.stdout}
EOF

uv run pflow /tmp/repro-no-coalesce.pflow.md --no-cache --no-trace
# expected: structured error showing primary FAILED with shell exit 1
```

---

## Phase 6 — Source Line Tracking for Output Declarations

### Goal
Parser tracks the line number where each output `source:` is declared. Template errors render `At: workflow.pflow.md:23` for output sources.

### Action 1 — Track per-yaml-item line numbers in `_Entity`

In `src/pflow/core/markdown_parser.py`, modify the `_Entity` dataclass (lines 179-188):

```python
@dataclass
class _Entity:
    """A collected ### entity (input, node, or output)."""

    id: str
    heading_line: int
    prose_parts: list[str] = field(default_factory=list)
    yaml_items: list[str] = field(default_factory=list)  # Raw YAML item strings
    yaml_item_lines: list[int] = field(default_factory=list)  # Parallel: source line of each item's first '- '
    code_blocks: list[_CodeBlock] = field(default_factory=list)
    section_type: _SectionType = _SectionType.NONE
```

### Action 2 — Populate `yaml_item_lines` during parsing

Locate the YAML item flush in `parse_markdown` (around lines 249-256). The current `_flush_yaml_item` reads:

```python
    def _flush_yaml_item() -> None:
        """Flush the current YAML item to the current entity."""
        nonlocal in_yaml_continuation, yaml_current_item_lines
        if yaml_current_item_lines and current_entity is not None:
            current_entity.yaml_items.append("\n".join(yaml_current_item_lines))
        yaml_current_item_lines = []
```

Add a `yaml_current_item_start_line` tracking variable. In `parse_markdown` near where `yaml_current_item_lines = []` is initialized (around line 245), add:

```python
    yaml_current_item_start_line = 0
```

Then update `_flush_yaml_item` to record the start line when flushing:

```python
    def _flush_yaml_item() -> None:
        """Flush the current YAML item to the current entity."""
        nonlocal in_yaml_continuation, yaml_current_item_lines, yaml_current_item_start_line
        if yaml_current_item_lines and current_entity is not None:
            current_entity.yaml_items.append("\n".join(yaml_current_item_lines))
            current_entity.yaml_item_lines.append(yaml_current_item_start_line)
        yaml_current_item_lines = []
        yaml_current_item_start_line = 0
```

**Where to set `yaml_current_item_start_line`**: The new-item creation is **NOT** an `.append()` (the `append` calls in the loop are for continuation lines). The new-item creation is the line at **`markdown_parser.py:374`** that does:

```python
        yaml_current_item_lines = [line.rstrip()]
```

This is an ASSIGNMENT (replacing the list with a single-element list). The loop variable counting lines is `line_idx` (0-based) and the human-readable line number is `line_num = line_idx + 1` already computed earlier in the loop body (around line 259). Add the line tracking IMMEDIATELY after that assignment:

```python
        yaml_current_item_lines = [line.rstrip()]
        yaml_current_item_start_line = line_num
```

**Verification**: after the change, grep `markdown_parser.py` for `yaml_current_item_start_line` — should appear in three places: the initialization, the new-item creation site at line 374, and `_flush_yaml_item`.

**Limitation to document**: this only tracks single-line YAML items via `_parse_yaml_items` first-pass parsing. For multi-line items that span continuation lines, the start_line still points to the first `- ` line. For output declarations (which almost always use single-line `- source: ${...}`), this is sufficient.

### Action 3 — Surface line numbers from `_parse_yaml_items`

The parser's `_parse_yaml_items` function (line 820) returns a flat dict mapping key → value. It needs to also return line info per key. Two options:

**Option A (preferred — minimal API change)**: Have `_parse_yaml_items` write line numbers into a parallel dict on the entity. Add a `yaml_item_keys: list[str] = field(default_factory=list)` to `_Entity` and populate it as items are parsed. Then `_build_output_dict` can correlate.

**Option B**: Return a tuple `(values_dict, line_dict)`. More invasive but cleaner.

Use **Option A**. Modify `_Entity`:

```python
    yaml_item_keys: list[str] = field(default_factory=list)  # Parallel to yaml_items: top-level key parsed from each item
```

In `_parse_yaml_items` (find the location where it parses each YAML item and extracts the key), append the parsed top-level key to `entity.yaml_item_keys`. The function currently parses items via `_coerce_yaml_scalar` or `yaml.safe_load`. After determining the key, do `entity.yaml_item_keys.append(key)`.

### Action 4 — Use line numbers in `_build_output_dict`

Located at lines 1333-1360. Modify to record source_line for `source`:

```python
def _build_output_dict(entity: _Entity) -> dict[str, Any]:
    """Build an output definition dict from an entity.

    Outputs get flat dicts (no params wrapper).
    Valid fields: description, type, source.
    The source's line number (if any) is recorded as _source_line for
    runtime error messages.
    """
    _validate_description(entity)
    _validate_code_blocks(entity)

    result: dict[str, Any] = {}

    # Description from prose
    prose = _get_prose(entity)
    if prose:
        result["description"] = prose

    # Parse YAML params — flat
    params = _parse_yaml_items(entity)
    result.update(params)

    # Track source line for `source:` (used by template errors)
    if "source" in params:
        for idx, key in enumerate(entity.yaml_item_keys):
            if key == "source" and idx < len(entity.yaml_item_lines):
                result["_source_line"] = entity.yaml_item_lines[idx]
                break

    # Code blocks — source goes directly to output
    for block in entity.code_blocks:
        if block.param_name == "source":
            result["source"] = block.content
            result["_source_line"] = block.start_line + 1
        elif block.param_name:
            result[block.param_name] = block.content

    return result
```

### Action 5 — Source-line propagation through output_resolver and OutputResolutionError

**Already specified earlier in the plan** — Phase 3 Action 6 updates `output_resolver.py::populate_declared_outputs` to copy `_source_line` from `output_config` into the failure dict, and Phase 5 Action 7 updates `OutputResolutionError.to_diagnostics` to surface it in the Diagnostic context (alongside the structured `unresolved_references` rendering).

The Phase 5 Action 6 change to `_format_location` (which adds source_file/source_line fallback to the `At:` line) will then render `At: workflow.pflow.md, line 23` automatically.

No additional Phase 6 work is required for this.

### Verification (Phase 6)

Edit repro to use direct reference (no coalesce) and verify the error message shows `At: workflow.pflow.md:N`.

---

## Phase 7 — Documentation Updates

### Action 1 — `runtime/CLAUDE.md`

In `src/pflow/runtime/CLAUDE.md`, find the "Reserved Shared Store Keys" section. Add `__failures__` to the canonical list:

```python
# Failure archive (managed by runtime/node_state.py::mark_node_failed)
shared["__failures__"] = {
    "node_id": {
        "data": {...},        # what was at shared[node_id] before the move
        "category": "shell_failure" | "api_warning" | "routing_error" | "exception" | "template_error",
        "error": "...",       # human-readable error (optional)
        "warning": "...",     # for api_warning category only (optional)
    }
}
```

Add a new section "Node Execution State Invariant" near the top:

```markdown
### Node Execution State Invariant

The shared store enforces this invariant for every executed node:

```
shared[node_id]            ↔ node executed successfully
shared["__failures__"][id] ↔ node executed and failed
neither                    ↔ node did not execute
```

Failed nodes never leak data into the main namespace. To query node state,
use `pflow.runtime.node_state`:

- `get_node_status(shared, node_id) → NodeStatus` (ABSENT/SUCCEEDED/FAILED)
- `get_node_output(shared, node_id) → Optional[dict]` — succeeded OR failed data
- `get_node_failure(shared, node_id) → Optional[dict]` — failure record only
- `node_succeeded(shared, node_id) → bool`
- `mark_node_failed(shared, node_id, *, category, error=None, warning=None)`

The five engine failure paths (returned-error action, api_warning, routing
error, exception, defensive runner) all funnel through `mark_node_failed`.
```

### Action 2 — `runtime/engine/CLAUDE.md`

Add a brief note in the "Instrumentation" section about `mark_node_failed` being the unified failure write path.

---

## Phase 8 — Tests

### Test File 1 — `tests/test_runtime/test_node_state.py` (NEW)

Create with:

```python
"""Unit tests for runtime/node_state.py — failure bookkeeping helpers."""

import pytest

from pflow.runtime.node_state import (
    FAILURE_CATEGORY_API_WARNING,
    FAILURE_CATEGORY_EXCEPTION,
    FAILURE_CATEGORY_NODE_ERROR,
    FAILURE_CATEGORY_ROUTING,
    FAILURE_CATEGORY_SHELL,
    FAILURE_CATEGORY_TEMPLATE,
    NodeStatus,
    clear_node_failure,
    get_node_failure,
    get_node_output,
    get_node_status,
    mark_node_failed,
    node_succeeded,
)


class TestGetNodeStatus:
    def test_absent(self):
        assert get_node_status({}, "node") == NodeStatus.ABSENT

    def test_succeeded(self):
        shared = {"node": {"stdout": "ok"}}
        assert get_node_status(shared, "node") == NodeStatus.SUCCEEDED

    def test_failed(self):
        shared = {"__failures__": {"node": {"data": {}, "category": "shell_failure"}}}
        assert get_node_status(shared, "node") == NodeStatus.FAILED

    def test_failed_takes_priority_over_succeeded(self):
        # Pathological case: data in both. Failed should win.
        shared = {
            "node": {"stdout": "stale"},
            "__failures__": {"node": {"data": {}, "category": "exception"}},
        }
        assert get_node_status(shared, "node") == NodeStatus.FAILED

    def test_internal_keys_are_absent(self):
        # __execution__ is not a "node"
        shared = {"__execution__": {"failed_node": None}}
        assert get_node_status(shared, "__execution__") == NodeStatus.ABSENT


class TestNodeSucceeded:
    def test_yes(self):
        assert node_succeeded({"node": {}}, "node") is True

    def test_no_for_failed(self):
        shared = {"__failures__": {"node": {"data": {}, "category": "exception"}}}
        assert node_succeeded(shared, "node") is False

    def test_no_for_absent(self):
        assert node_succeeded({}, "missing") is False


class TestGetNodeOutput:
    def test_succeeded_returns_data(self):
        shared = {"node": {"stdout": "x"}}
        assert get_node_output(shared, "node") == {"stdout": "x"}

    def test_failed_returns_data_field(self):
        shared = {
            "__failures__": {
                "node": {"data": {"stdout": "", "exit_code": 1}, "category": "shell_failure"}
            }
        }
        assert get_node_output(shared, "node") == {"stdout": "", "exit_code": 1}

    def test_absent_returns_none(self):
        assert get_node_output({}, "missing") is None


class TestGetNodeFailure:
    def test_failed_returns_record(self):
        shared = {
            "__failures__": {
                "node": {"data": {}, "category": "shell_failure", "error": "boom"}
            }
        }
        record = get_node_failure(shared, "node")
        assert record["category"] == "shell_failure"
        assert record["error"] == "boom"

    def test_succeeded_returns_none(self):
        assert get_node_failure({"node": {}}, "node") is None

    def test_absent_returns_none(self):
        assert get_node_failure({}, "missing") is None


class TestMarkNodeFailed:
    def _initial_shared(self):
        return {
            "node": {"stdout": "", "exit_code": 1, "command": "exit 1"},
            "__execution__": {
                "completed_nodes": [],
                "node_actions": {},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }

    def test_moves_data(self):
        shared = self._initial_shared()
        mark_node_failed(shared, "node", category=FAILURE_CATEGORY_SHELL, error="boom")
        assert "node" not in shared
        assert shared["__failures__"]["node"]["category"] == "shell_failure"
        assert shared["__failures__"]["node"]["error"] == "boom"
        assert shared["__failures__"]["node"]["data"] == {
            "stdout": "",
            "exit_code": 1,
            "command": "exit 1",
        }

    def test_sets_failed_node(self):
        shared = self._initial_shared()
        mark_node_failed(shared, "node", category=FAILURE_CATEGORY_EXCEPTION, error="boom")
        assert shared["__execution__"]["failed_node"] == "node"

    def test_writes_warning_only_when_given(self):
        shared = self._initial_shared()
        mark_node_failed(
            shared, "node", category=FAILURE_CATEGORY_API_WARNING, warning="API failed"
        )
        assert shared["__warnings__"]["node"] == "API failed"

    def test_no_warning_if_not_given(self):
        shared = self._initial_shared()
        mark_node_failed(shared, "node", category=FAILURE_CATEGORY_SHELL, error="boom")
        assert "__warnings__" not in shared

    def test_loop_case_strips_completed_bookkeeping(self):
        shared = self._initial_shared()
        shared["__execution__"]["completed_nodes"].append("node")
        shared["__execution__"]["node_actions"]["node"] = "default"
        shared["__execution__"]["node_hashes"]["node"] = "abc"
        mark_node_failed(shared, "node", category=FAILURE_CATEGORY_NODE_ERROR)
        assert "node" not in shared["__execution__"]["completed_nodes"]
        assert "node" not in shared["__execution__"]["node_actions"]
        assert "node" not in shared["__execution__"]["node_hashes"]

    def test_creates_execution_state_if_missing(self):
        shared = {"node": {}}
        mark_node_failed(shared, "node", category=FAILURE_CATEGORY_EXCEPTION)
        assert "__execution__" in shared
        assert shared["__execution__"]["failed_node"] == "node"

    def test_handles_missing_node_data(self):
        shared = {"__execution__": {"failed_node": None, "completed_nodes": [],
                                    "node_actions": {}, "node_hashes": {}, "node_visit_counts": {}}}
        mark_node_failed(shared, "missing", category=FAILURE_CATEGORY_EXCEPTION, error="boom")
        assert shared["__failures__"]["missing"]["data"] == {}


class TestClearNodeFailure:
    def test_removes_record(self):
        shared = {"__failures__": {"node": {"data": {}, "category": "exception"}}}
        clear_node_failure(shared, "node")
        assert "node" not in shared["__failures__"]

    def test_no_op_if_absent(self):
        shared = {}
        clear_node_failure(shared, "node")
        assert shared == {}
```

### Test File 2 — `tests/test_runtime/test_template_coalesce.py` additions

Append these tests to the existing file (do not modify existing tests):

```python
class TestCoalesceWithFailedNodes:
    """Regression tests for GH #208 — coalesce must skip failed nodes."""

    def test_coalesce_skips_failed_root(self):
        """Failed node moved to __failures__ is treated as absent by coalesce."""
        from pflow.runtime.node_state import FAILURE_CATEGORY_SHELL, mark_node_failed
        from pflow.runtime.template_resolver import TemplateResolver

        shared = {
            "primary": {"stdout": "", "exit_code": 1, "command": "exit 1"},
            "fallback": {"stdout": "fallback-content"},
            "__execution__": {
                "completed_nodes": ["fallback"],
                "node_actions": {"fallback": "default"},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        mark_node_failed(shared, "primary", category=FAILURE_CATEGORY_SHELL, error="exit 1")
        # primary is now in __failures__, not in shared
        assert "primary" not in shared
        # Coalesce should skip primary and resolve to fallback's stdout
        value, status = TemplateResolver.resolve_coalesce(
            "primary.stdout ?? fallback.stdout", shared
        )
        assert status == "resolved"
        assert value == "fallback-content"

    def test_coalesce_skips_failed_when_using_resolve_template(self):
        """End-to-end through resolve_template: ${a ?? b} skips failed a."""
        from pflow.runtime.node_state import FAILURE_CATEGORY_SHELL, mark_node_failed
        from pflow.runtime.template_resolver import TemplateResolver

        shared = {
            "primary": {"stdout": ""},
            "fallback": {"stdout": "fallback-content"},
            "__execution__": {
                "completed_nodes": ["fallback"],
                "node_actions": {"fallback": "default"},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        mark_node_failed(shared, "primary", category=FAILURE_CATEGORY_SHELL)
        assert TemplateResolver.resolve_template(
            "${primary.stdout ?? fallback.stdout}", shared
        ) == "fallback-content"

    def test_succeeded_node_with_empty_output_still_resolves(self):
        """A successful node with empty stdout is NOT treated as failed.

        ignore_errors:true scenarios put the node in completed_nodes/shared
        with possibly-empty data. Coalesce must NOT skip those.
        """
        from pflow.runtime.template_resolver import TemplateResolver

        shared = {
            "primary": {"stdout": ""},
            "fallback": {"stdout": "fallback-content"},
            "__execution__": {
                "completed_nodes": ["primary", "fallback"],
                "node_actions": {"primary": "default", "fallback": "default"},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        # primary succeeded with empty stdout — coalesce uses primary's value (empty)
        result = TemplateResolver.resolve_template(
            "${primary.stdout ?? fallback.stdout}", shared
        )
        assert result == ""
```

### Test File 3 — `tests/test_integration/test_failed_node_invariant.py` (NEW)

**Critical**: Pass the IR dict directly to `WorkflowRunner.run()` (not via `write_workflow_file` markdown roundtrip). `tests/shared/markdown_utils.py::ir_to_markdown` does NOT emit `edges` or `on-error` directives — see `tests/CLAUDE.md` "Gotchas with `ir_to_markdown`". Roundtripping would lose the on-error routing and these tests would fail for the wrong reason.

Also pass `RunnerConfig()` (not `None`) — `WorkflowRunner.run()` reads `config.cache_enabled`, `config.verbose`, `config.only_node` and crashes on None.

Create the file with:

```python
"""End-to-end tests for the failed-node invariant fix (GH #208).

These tests pass IR dicts directly to WorkflowRunner to avoid the
``ir_to_markdown`` roundtrip, which drops on-error routing. See
``tests/CLAUDE.md`` "Gotchas with ir_to_markdown".
"""

import pytest

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


def _coalesce_repro_ir() -> dict:
    """Build the GH #208 reproduction IR.

    primary fails (exit 1) → on-error → fallback (echo) → end.
    Output references both via coalesce.
    """
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "primary",
                "type": "shell",
                "purpose": "Primary node that fails by design.",
                "params": {"command": "exit 1"},
            },
            {
                "id": "fallback",
                "type": "shell",
                "purpose": "Fallback node providing alternative output.",
                "params": {"command": 'echo "fallback-content"'},
            },
        ],
        "edges": [
            {"from": "primary", "to": "fallback", "action": "error"},
        ],
        "start_node": "primary",
        "outputs": {
            "content": {
                "description": "Whichever path produced output.",
                "source": "${primary.stdout ?? fallback.stdout}",
            },
        },
    }


def test_coalesce_falls_through_to_fallback_on_primary_failure():
    """GH #208 repro: ${primary.stdout ?? fallback.stdout} → fallback-content."""
    runner = WorkflowRunner()
    result = runner.run(_coalesce_repro_ir(), {}, config=RunnerConfig())

    assert result.success, f"Workflow should succeed via on-error fallback: {result.diagnostics}"
    assert result.shared_after.get("content") == "fallback-content"


def test_failed_primary_data_is_archived_to_failures():
    """After execution, primary's data lives in __failures__, not shared[primary]."""
    runner = WorkflowRunner()
    result = runner.run(_coalesce_repro_ir(), {}, config=RunnerConfig())

    shared = result.shared_after
    assert "primary" not in shared, "Failed node should not be in main namespace"
    assert "__failures__" in shared
    assert "primary" in shared["__failures__"]
    record = shared["__failures__"]["primary"]
    assert record["category"] in ("shell_failure", "node_action_error")
    assert record["data"]["exit_code"] == 1


def test_direct_reference_to_failed_node_produces_structured_error():
    """Without coalesce, ${primary.stdout} on failed primary errors with rich context."""
    ir = _coalesce_repro_ir()
    ir["outputs"]["content"]["source"] = "${primary.stdout}"

    runner = WorkflowRunner()
    result = runner.run(ir, {}, config=RunnerConfig())

    # Workflow's RUNTIME succeeded (fallback ran), but output resolution fails.
    # The failure manifests as an error diagnostic with structured failure context.
    error_diags = [d for d in result.diagnostics if d.severity.value == "error"]
    assert error_diags, f"Should have at least one error diagnostic. Got: {result.diagnostics}"

    # The diagnostic should mention 'primary' and surface the failure context.
    combined_text = " ".join(
        f"{d.message} {d.context or ''}" for d in error_diags
    ).lower()
    assert "primary" in combined_text
    # Structured rendering should include the failure category
    assert any(
        d.context and d.context.get("category") == "template_error"
        for d in error_diags
    ), "OutputResolutionError should produce category=template_error after Phase 5"


def test_trace_captures_failed_node_data():
    """Trace events should still contain stdout/stderr/exit_code from failed primary."""
    runner = WorkflowRunner()
    result = runner.run(_coalesce_repro_ir(), {}, config=RunnerConfig())

    assert result.trace is not None
    events = result.trace.events
    primary_event = next((e for e in events if e.get("node_id") == "primary"), None)
    assert primary_event is not None
    assert primary_event.get("success") is False
    output = primary_event.get("node_output") or {}
    assert output.get("exit_code") == 1
    assert output.get("command") == "exit 1"


def test_loop_reentry_clears_stale_failure_record():
    """Regression test for warning #2: clear_node_failure must be wired into enforce_loop_guard.

    A node that fails on visit 1 then succeeds on visit 2 must NOT show as
    FAILED in get_node_status() — its stale failure record must be cleared.
    """
    from pflow.runtime.node_state import (
        FAILURE_CATEGORY_SHELL,
        NodeStatus,
        get_node_status,
        mark_node_failed,
    )
    from pflow.runtime.engine.instrumentation import enforce_loop_guard

    shared = {
        "loopy": {"stdout": "first attempt"},
        "__execution__": {
            "completed_nodes": [],
            "node_actions": {},
            "node_hashes": {},
            "failed_node": None,
            "node_visit_counts": {"loopy": 1},
        },
    }
    mark_node_failed(shared, "loopy", category=FAILURE_CATEGORY_SHELL, error="boom")
    assert get_node_status(shared, "loopy") == NodeStatus.FAILED

    # Simulate visit 2 — enforce_loop_guard should clear the failure record
    enforce_loop_guard("loopy", shared)
    assert "loopy" not in shared.get("__failures__", {}), (
        "enforce_loop_guard must call clear_node_failure for revisited nodes"
    )
    assert get_node_status(shared, "loopy") == NodeStatus.ABSENT
```

### Test File 4 — `tests/test_runtime/test_template_error_messages.py` (NEW)

Snapshot tests for the three error message cases. Use plain string assertions (no snapshot library):

```python
"""Snapshot-style tests for the rewritten template error messages."""

import pytest

from pflow.core.diagnostic import format_diagnostic
from pflow.runtime.engine.template_errors import build_template_error_diagnostic
from pflow.runtime.node_state import (
    FAILURE_CATEGORY_SHELL,
    mark_node_failed,
)


def _shared_with_failed_primary():
    shared = {
        "primary": {
            "stdout": "",
            "stderr": "",
            "exit_code": 1,
            "command": "exit 1",
            "error": "Command failed with exit code 1",
        },
        "fallback": {"stdout": "fallback-content"},
        "__execution__": {
            "completed_nodes": ["fallback"],
            "node_actions": {"fallback": "default"},
            "node_hashes": {},
            "failed_node": None,
            "node_visit_counts": {},
        },
    }
    mark_node_failed(
        shared,
        "primary",
        category=FAILURE_CATEGORY_SHELL,
        error="Command failed with exit code 1",
    )
    return shared


class TestCase1NonCoalesceFailedRef:
    """${primary.stdout} where primary failed, no coalesce."""

    def test_diagnostic_has_failed_status_reference(self):
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stdout}",
            shared,
            node_id=None,
        )
        refs = diag.context["unresolved_references"]
        assert len(refs) == 1
        assert refs[0]["status"] == "failed"
        assert refs[0]["root"] == "primary"
        assert refs[0]["failure"]["exit_code"] == 1

    def test_rendered_includes_failed_label(self):
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic("content", "${primary.stdout}", shared)
        rendered = format_diagnostic(diag)
        assert "FAILED" in rendered
        assert "primary" in rendered
        assert "Exit code: 1" in rendered or "exit code 1" in rendered.lower()

    def test_rendered_suggests_coalesce_fix(self):
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic("content", "${primary.stdout}", shared)
        rendered = format_diagnostic(diag)
        assert "??" in rendered  # coalesce suggestion


class TestCase2AllCoalesceOperandsFailed:
    """${primary.stdout ?? fallback.stdout} where both fail."""

    def test_diagnostic_marks_both_as_failed(self):
        shared = _shared_with_failed_primary()
        # Now fail fallback too
        mark_node_failed(
            shared,
            "fallback",
            category=FAILURE_CATEGORY_SHELL,
            error="curl: (6) Could not resolve host",
        )
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stdout ?? fallback.stdout}",
            shared,
        )
        refs = diag.context["unresolved_references"]
        assert len(refs) == 2
        assert all(r["status"] == "failed" for r in refs)

    def test_rendered_shows_both_failures(self):
        shared = _shared_with_failed_primary()
        mark_node_failed(shared, "fallback", category=FAILURE_CATEGORY_SHELL, error="boom")
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stdout ?? fallback.stdout}",
            shared,
        )
        rendered = format_diagnostic(diag)
        assert "primary" in rendered
        assert "fallback" in rendered


class TestCase3TypoOnFailedNode:
    """${primary.stddout} (typo) on a failed primary.

    Warning #8: even though the node is FAILED (dominant issue), we ALSO
    detect the typo against the failure record's data shape and surface
    it as a secondary hint. This eliminates a wasted iteration cycle for
    AI agents that have both a typo and a failure.
    """

    def test_status_is_failed_with_secondary_typo_hint(self):
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stddout}",
            shared,
        )
        refs = diag.context["unresolved_references"]
        assert refs[0]["status"] == "failed"
        # Secondary hint detects the typo against failure data shape
        assert refs[0]["secondary_hint"] == "primary.stdout"

    def test_rendered_shows_both_failure_and_typo_hint(self):
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stddout}",
            shared,
        )
        rendered = format_diagnostic(diag)
        # Primary issue: failure
        assert "FAILED" in rendered
        # Secondary issue: typo hint
        assert "Additional issue" in rendered or "typo" in rendered.lower()
        assert "primary.stdout" in rendered  # the corrected variable


class TestCase4SucceededNodeFieldTypo:
    """${succeeded_node.stddout} where node succeeded with stdout."""

    def test_diagnostic_marks_path_error(self):
        shared = {
            "node": {"stdout": "ok", "stderr": "", "exit_code": 0},
            "__execution__": {
                "completed_nodes": ["node"],
                "node_actions": {"node": "default"},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        diag = build_template_error_diagnostic(
            "content",
            "${node.stddout}",
            shared,
        )
        refs = diag.context["unresolved_references"]
        assert refs[0]["status"] == "path_error"
        assert refs[0]["did_you_mean"] == "node.stdout"

    def test_rendered_shows_did_you_mean(self):
        shared = {
            "node": {"stdout": "ok"},
            "__execution__": {
                "completed_nodes": ["node"],
                "node_actions": {"node": "default"},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        diag = build_template_error_diagnostic(
            "content",
            "${node.stddout}",
            shared,
        )
        rendered = format_diagnostic(diag)
        assert "did you mean" in rendered.lower() or "Did you mean" in rendered
        assert "node.stdout" in rendered


class TestCase5AbsentNode:
    """${missing.field} where missing was never executed."""

    def test_diagnostic_marks_absent(self):
        shared = {
            "__execution__": {
                "completed_nodes": [],
                "node_actions": {},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        diag = build_template_error_diagnostic(
            "content",
            "${missing.field}",
            shared,
        )
        refs = diag.context["unresolved_references"]
        assert refs[0]["status"] == "absent"

    def test_rendered_says_did_not_execute(self):
        shared = {
            "__execution__": {
                "completed_nodes": [],
                "node_actions": {},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        diag = build_template_error_diagnostic("content", "${missing.field}", shared)
        rendered = format_diagnostic(diag)
        assert "did not execute" in rendered


def test_diagnostic_message_is_specific_per_param():
    """Two template errors on different params should NOT dedupe (different messages)."""
    shared = _shared_with_failed_primary()
    d1 = build_template_error_diagnostic("command", "${primary.stdout}", shared)
    d2 = build_template_error_diagnostic("script", "${primary.stdout}", shared)
    assert d1 != d2  # Different param keys → different messages → not equal


class TestWarning7PeerSuggestions:
    """Warning #7: fix suggestions should use actual peer node names, not <fallback>."""

    def test_failed_ref_includes_peer_with_same_field(self):
        """When a failed node has a sibling with the same field, suggest it by name."""
        shared = _shared_with_failed_primary()
        # _shared_with_failed_primary() has 'fallback' with stdout
        diag = build_template_error_diagnostic("content", "${primary.stdout}", shared)
        refs = diag.context["unresolved_references"]
        assert "fallback" in refs[0]["peer_suggestions"]

    def test_rendered_substitutes_actual_peer_in_fix(self):
        """Rendered fix should be paste-able: ${primary.stdout ?? fallback.stdout}."""
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic("content", "${primary.stdout}", shared)
        rendered = format_diagnostic(diag)
        # Should NOT contain the placeholder
        assert "<fallback>" not in rendered
        # SHOULD contain the actual peer name in the fix template
        assert "${primary.stdout ?? fallback.stdout}" in rendered


class TestWarning9CategoryAwareFailureRendering:
    """Warning #9: HTTP/MCP/exception failures should render their relevant fields."""

    def test_http_failure_renders_status_code_not_shell_fields(self):
        from pflow.runtime.node_state import (
            FAILURE_CATEGORY_API_WARNING,
            mark_node_failed,
        )

        shared = {
            "api": {
                "status_code": 503,
                "url": "https://api.example.com/data",
                "response": "Service Unavailable",
            },
            "fallback": {"stdout": "fallback-content"},
            "__execution__": {
                "completed_nodes": ["fallback"],
                "node_actions": {"fallback": "default"},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        mark_node_failed(
            shared,
            "api",
            category=FAILURE_CATEGORY_API_WARNING,
            error="503 Service Unavailable",
        )
        diag = build_template_error_diagnostic("content", "${api.body}", shared)
        rendered = format_diagnostic(diag)
        assert "503" in rendered
        assert "https://api.example.com/data" in rendered
        # Should NOT show "Exit code" (a shell-specific field) for HTTP failures
        assert "Exit code" not in rendered


class TestWarning6Case2AllCoalesceFailed:
    """Warning #6: when all coalesce operands fail, emit a summary fix block."""

    def test_summary_block_emitted(self):
        from pflow.runtime.node_state import (
            FAILURE_CATEGORY_SHELL,
            mark_node_failed,
        )

        shared = _shared_with_failed_primary()
        # Make fallback fail too
        mark_node_failed(
            shared,
            "fallback",
            category=FAILURE_CATEGORY_SHELL,
            error="curl: (6) Could not resolve host",
        )
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stdout ?? fallback.stdout}",
            shared,
        )
        rendered = format_diagnostic(diag)
        # Summary block must appear after the per-reference details
        assert "All coalesce operands failed" in rendered
        # Must include a paste-able pattern with another fallback
        assert "?? " in rendered  # the additional-operand suggestion


class TestWarning10OutputResolutionStructured:
    """Warning #10: OutputResolutionError uses category=template_error rendering."""

    def test_to_diagnostics_uses_template_error_category(self):
        from pflow.core.user_errors import OutputResolutionError

        # Build a failure dict matching what _diagnose_unresolved_output produces
        failures = [{
            "output_name": "content",
            "source_expr": "${primary.stdout}",
            "diagnostics": ["Variable 'primary.stdout': node 'primary' executed but failed: boom"],
            "raw_diagnostics": [{
                "variable": "primary.stdout",
                "root": "primary",
                "status": "failed",
                "root_absent": False,
                "failure_category": "shell_failure",
                "failure_error": "boom",
            }],
            "unresolved_references": [{
                "var": "primary.stdout",
                "root": "primary",
                "status": "failed",
                "in_coalesce": False,
                "coalesce_expr": None,
                "failure": {
                    "category": "shell_failure",
                    "error": "boom",
                    "data": {"exit_code": 1, "command": "exit 1"},
                },
                "peer_suggestions": [],
                "secondary_hint": None,
            }],
            "available_context_keys": ["fallback"],
        }]
        err = OutputResolutionError(failures=failures)
        diags = err.to_diagnostics()
        assert len(diags) == 1
        assert diags[0].context["category"] == "template_error"
        assert "unresolved_references" in diags[0].context
```

### Existing test updates

These tests are KNOWN to break because they encode the old "failed node leaks into shared[node_id]" invariant. Update them as part of Phase 8.

1. **`tests/test_integration/test_branch_convergence.py:740-743`** — reads `shared["child"].get("error", "")` for a failed sub-workflow. Update to use `get_node_failure(shared, "child")`.

2. **`tests/test_runtime/test_workflow_executor/test_integration.py:283-285`** — same pattern: `assert "sub" in shared; assert "error" in shared["sub"]`. Update to use `get_node_failure(shared, "sub")`.

3. **`tests/test_integration/test_user_nodes.py:267-270`** — reads `shared["calc1"]["error"]` for a failed user node. Update to read from `__failures__["calc1"]["data"]["error"]` or use `get_node_failure`.

4. **`tests/test_runtime/test_workflow_executor/test_workflow_executor.py:304-340`** — four `_extract_child_error` tests build hand-crafted `child_storage` dicts placing failed-node data at `child_storage[failed_node]`. After the fix, the `_extract_child_error` function falls back to that location for backward compat (Phase 3 Action 4), so these tests will SILENTLY pass via the fallback path. Update them to use `mark_node_failed` so they exercise the new `__failures__`-based path.

5. **`tests/test_cli/test_agent_ux_fixes.py:285-315`** — same pattern as #4 for CLI error display. Update to use `mark_node_failed`.

6. **`tests/test_runtime/test_checkpoint_tracking.py:90-100 (test_failed_node_tracking)`** — calls `cache_result(...)` directly with an error action. After Phase 2, `cache_result` no longer archives data (it only sets `failed_node`). The test will pass but covers different internals. Augment with assertions that data is in `__failures__` after the engine completes a failure path.

7. **`tests/test_runtime/test_engine_behavior.py:211-216`** — checks `__execution__["failed_node"]` only. Augment with assertions on `__failures__` to exercise the new invariant.

8. **`tests/test_runtime/test_engine_behavior.py:241`** — checks `shared["__execution__"]["failed_node"] == "failing"`. Still works (mark_node_failed sets this). No change needed.

9. **`tests/test_execution/test_runner.py:201-237`** — tests `result.errors[0].context.shell_command` etc. After Phase 3, `executor_service` reads via `get_node_output` which reads from `__failures__`. Should still pass — verify all rich context fields (`shell_command`, `shell_stdout`, `shell_stderr`, `shell_exit_code`) are populated.

10. **`tests/test_runtime/test_node_wrapper_template_validation.py`** — optional input injection tests. Failed nodes are now treated as absent for `inject_none_for_optional_inputs`. Update any test that expects a failed node to NOT inject None.

11. **`tests/test_integration/test_branch_convergence.py`** existing branch convergence tests — these should all still pass; the invariant change is invisible to them because they test non-taken branches (which were never in `shared`), not on-error fallback.

12. **`tests/test_integration/test_conditional_branching.py:463, 626`** — these read `shared["primary"]["stdout"]` in SUCCESS scenarios (primary succeeded). After the fix they still work — verify.

For each break, update the test to:
- Use the new helpers (`mark_node_failed`, `get_node_failure`, `get_node_output`)
- Read failed-node data from `__failures__[node_id]["data"]` instead of `shared[node_id]`
- Optionally use `from pflow.runtime.node_state import ...` at the top

After fixing the listed tests, run `make test` to discover any additional unexpected breakages and update them following the same pattern.

### Verification (Phase 8)

```bash
make check
make test
uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace
```

All tests pass. Repro produces `fallback-content`.

---

## Phase 9 — File GH Issues for Tier 3

After the implementation passes all checks, file three GH issues:

### Issue 1 — Transactional `NamespacedSharedStore`

Title: `Refactor: NamespacedSharedStore should be transactional`
Body:
```
Follow-up from Task 148 (failed-node invariant fix). Today the namespaced
store eagerly creates `parent[namespace] = {}` in `__init__`, then nodes
write through it. Failures are cleaned up post-hoc by `mark_node_failed`.

A cleaner model: buffer writes locally, commit to parent on success,
archive to `__failures__` on failure. The invariant becomes
"enforced by construction" instead of "enforced by helper".

Scope:
- NamespacedSharedStore buffers writes in self._local
- engine._execute_node calls store.commit() on success, store.rollback_to_failures() on failure
- mark_node_failed becomes the rollback target rather than a separate cleanup
- Existing get/contains semantics preserved (local first, then parent)

Out of scope: any user-visible behavior change. Internal refactor only.
```

### Issue 2 — Richer `get_upstream_stderr`

Title: `Improve: get_upstream_stderr should show command/exit/error, not just stderr`
Body:
```
Follow-up from Task 148. `get_upstream_stderr` currently only surfaces
the stderr field of upstream nodes when enriching template errors. This
fires for ANY node with stderr (including successful nodes that just
warned), and it misses the most useful info: the command that ran, the
exit code, and the error message.

Scope:
- Use FailureRecord from __failures__ to surface category + error + command + exit_code + stderr
- Only fire for FAILED upstreams, not for SUCCEEDED ones with stderr noise
- Format: structured block similar to _format_failed_upstream_block in diagnostic.py

Existing behavior: stderr only, fires for any non-empty stderr.
New behavior: rich block, only fires when upstream actually failed.
```

### Issue 3 — Consolidate validation and runtime template error formats

Title: `Consolidate path_validation enhanced errors with runtime template errors`
Body:
```
Follow-up from Task 148. `runtime/template_validation/path_validation.py`
has the highest-quality error format in the codebase
(`format_enhanced_node_error`, `_format_batch_inner_field_error`). It
shows available outputs with type info, did-you-mean suggestions, and
paste-able fix templates.

The runtime template error path (`template_errors.py::build_template_error_diagnostic`,
added in Task 148) does similar work but in a different style. They
should share a single builder.

Scope:
- Extract a common builder from path_validation.format_enhanced_node_error
- Have runtime template_errors call into it
- Both paths produce identical output for identical errors
- Tests verify validation-time and runtime-time errors look the same
```

---

## Verification — Final End-to-End

After all phases complete, run:

```bash
cd /Users/andfal/projects/pflow-fix-resolve-coalesce-empty-string

# 1. Repro produces fallback-content
uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace

# 2. Lint and type checks
make check

# 3. Full test suite
make test

# 4. Manual: edit repro to use direct reference (no ??), verify rich error
sed 's/\${primary.stdout ?? fallback.stdout}/${primary.stdout}/' \
    scratchpads/issue-208/repro.pflow.md > /tmp/no-coalesce.pflow.md
uv run pflow /tmp/no-coalesce.pflow.md --no-cache --no-trace
# Expect: structured error with "FAILED" label, exit code 1, suggestion to use ??

# 5. Manual: typo on succeeded node
cat > /tmp/typo.pflow.md <<'EOF'
# Typo Test

## Steps

### node

Successful node.

- type: shell
- next: end

```shell command
echo "ok"
```

## Outputs

### content

Output with typo.

- source: ${node.stddout}
EOF
uv run pflow /tmp/typo.pflow.md --no-cache --no-trace
# Expect: "Did you mean: ${node.stdout}" suggestion

# 6. JSON output mode shows structured context
uv run pflow /tmp/no-coalesce.pflow.md --output-format json --no-cache --no-trace 2>&1 | python -m json.tool
# Expect: errors[0].context.unresolved_references list with status="failed"

# 7. --report works
uv run pflow scratchpads/issue-208/repro.pflow.md --report --no-cache 2>&1 | head -20
# Expect: report directory created, primary marked failed, fallback succeeded
```

All seven checks pass → task complete.

---

## Critical Files To Modify (Summary Index)

| Phase | File | Change |
|---|---|---|
| 1 | `src/pflow/runtime/node_state.py` | NEW — helpers, constants, `clear_node_failure` |
| 1 | `src/pflow/runtime/template_resolver.py` | Add `extract_root_node_id` static method (used by Phase 3) |
| 2 | `src/pflow/runtime/engine/instrumentation.py` | `enforce_loop_guard` calls `clear_node_failure`; `handle_api_warning` rewrite (mark_node_failed at end); `cache_result` UNCHANGED |
| 2 | `src/pflow/runtime/engine/engine.py` | `_execute_node` happy-path archive at step 17.5; `_execute_node` except block; `_handle_no_successor` |
| 3 | `src/pflow/execution/executor_service.py` | `_extract_node_level_error`, `build_error_list`, add `_FAILURE_CATEGORY_MAP` |
| 3 | `src/pflow/runtime/engine/error_context.py` | `get_upstream_stderr`, `extract_node_ids_from_template` |
| 3 | `src/pflow/runtime/workflow_executor.py` | `_extract_child_error` |
| 3 | `src/pflow/runtime/engine/template_resolution.py` | `all_variables_from_absent_nodes` |
| 3 | `src/pflow/runtime/output_resolver.py` | Delete duplicate `_ROOT_SPLIT`, rewrite `_diagnose_unresolved_output` (with `unresolved_references` for warning #10), pass `source_line` and `source_file` through `populate_declared_outputs` |
| 3 | `src/pflow/execution/execution_state.py` | `build_execution_steps` uses `get_node_output` for batch_metadata + shell stderr (covers failed batch/shell nodes in display) |
| 4 | `src/pflow/core/workflow/data_flow.py` | Use `extract_root_node_id` instead of reaching into `_ROOT_SPLIT_PATTERN` |
| 5 | `src/pflow/runtime/engine/template_errors.py` | Replace `build_enhanced_template_error`/`diagnose_coalesce` with `build_template_error_diagnostic`/`classify_unresolved_references`. Includes `_find_peer_nodes_with_field` (warning #7), `secondary_hint` typo detection (warning #8), `_extract_failure_display_data` category-aware (warning #9) |
| 5 | `src/pflow/runtime/engine/template_resolution.py` | Use `build_template_error_diagnostic`, attach `_pflow_template_diagnostic` |
| 5 | `src/pflow/core/diagnostic.py` | Rewrite `_format_template_error_lines` with Case 2 summary block (warning #6); add `_format_one_reference`, `_render_failure_data_block`, `_render_shell_failure_block`, `_render_http_failure_block`, `_render_mcp_failure_block`, `_render_generic_failure_block` (warning #9); update `_format_location`; update `_builtin_exception_diagnostic` ValueError branch |
| 5 | `src/pflow/core/user_errors.py` | Rewrite `OutputResolutionError.to_diagnostics` to use `category="template_error"` and structured `unresolved_references` (warning #10) |
| 5 | `src/pflow/execution/runner.py` | Improve `_extract_runtime_warnings` canned suggestions |
| 6 | `src/pflow/core/markdown_parser.py` | `_Entity.yaml_item_lines`, `yaml_item_keys`, line tracking at line 374 (assignment, not append), `_build_output_dict` records `_source_line` |
| 7 | `src/pflow/runtime/CLAUDE.md` | Document `__failures__` key, document invariant, document `node_state.py` |
| 7 | `src/pflow/runtime/engine/CLAUDE.md` | Document `mark_node_failed` |
| 8 | `tests/test_runtime/test_node_state.py` | NEW — unit tests for helpers |
| 8 | `tests/test_runtime/test_template_coalesce.py` | Append `TestCoalesceWithFailedNodes` class |
| 8 | `tests/test_integration/test_failed_node_invariant.py` | NEW — end-to-end repro tests |
| 8 | `tests/test_runtime/test_template_error_messages.py` | NEW — error message snapshot tests |
| 8 | Various existing tests | Update reads of `shared[failed_node]` to use helpers |
| 9 | GitHub | File 3 follow-up issues |

## Key Functions/Helpers To Reuse (Summary Index)

| Helper | Where | Used by |
|---|---|---|
| `NodeStatus`, `get_node_status`, `get_node_output`, `get_node_failure`, `node_succeeded`, `mark_node_failed`, `clear_node_failure` | NEW `runtime/node_state.py` | Engine, instrumentation (`enforce_loop_guard`, `handle_api_warning`), executor_service, error_context, workflow_executor, template_errors, output_resolver, execution_state |
| `TemplateResolver.extract_root_node_id` | NEW method on existing class | template_errors, output_resolver, error_context, template_resolution, data_flow |
| `FAILURE_CATEGORY_*` constants | NEW in node_state | All `mark_node_failed` callers |
| `_FAILURE_CATEGORY_MAP` + `_map_failure_category_to_diagnostic` | NEW in executor_service | `build_error_list` |
| `classify_unresolved_references`, `build_template_error_diagnostic` | NEW in template_errors | template_resolution (replaces `build_enhanced_template_error` callers), output_resolver (`_diagnose_unresolved_output` for warning #10) |
| `_find_peer_nodes_with_field` | NEW in template_errors | `_classify_one_reference` (warning #7 — peer suggestions in fix messages) |
| `_extract_failure_display_data` | NEW in template_errors | `_classify_one_reference` (warning #9 — category-aware failure data) |
| `_format_one_reference`, `_describe_failure_category`, `_extract_field_name`, `_format_legacy_template_error_lines` | NEW in diagnostic.py | `_format_template_error_lines` |
| `_render_failure_data_block`, `_render_shell_failure_block`, `_render_http_failure_block`, `_render_mcp_failure_block`, `_render_generic_failure_block` | NEW in diagnostic.py | `_format_one_reference` FAILED branch (warning #9) |

## Implementation Order

Strict order — earlier phases create dependencies for later ones:

1. **Phase 1** — Create `node_state.py` (Action 1) AND add `extract_root_node_id` to `template_resolver.py` (Action 2). Both are self-contained and required by Phase 3 read-site migrations.
2. **Phase 2** — Funnel failure paths through `mark_node_failed` at step 17.5; wire `clear_node_failure` into `enforce_loop_guard` for loop re-entry correctness; rewrite `handle_api_warning` to put the move at the END. `cache_result` stays unchanged (it only sets `failed_node`). Tests will start failing here; that's expected — Phase 3 fixes them.
3. **Phase 3** — Read sites migrate to `get_node_output` / `get_node_failure`. Includes `execution_state.py` (failed batch/shell display). After this phase, the #208 repro should produce `fallback-content`.
4. **Phase 4** — Sweep remaining `_ROOT_SPLIT_PATTERN` consumers in `data_flow.py` (`extract_root_node_id` is already in place from Phase 1 Action 2).
5. **Phase 5** — Structured Diagnostics with all warning fixes:
   - Case 2 summary block (warning #6)
   - Peer node suggestions (warning #7)
   - Failed-node typo detection as secondary hint (warning #8)
   - Category-aware failure rendering (warning #9)
   - `OutputResolutionError` structured rendering (warning #10)
   - Improved canned suggestions
6. **Phase 6** — Source-line tracking in parser; output_resolver and OutputResolutionError already updated in Phases 3 and 5 to consume it.
7. **Phase 7** — Documentation updates (`runtime/CLAUDE.md`, `engine/CLAUDE.md`).
8. **Phase 8** — Add new tests, fix existing test breakages (12-test list), verify everything passes.
9. **Phase 9** — File follow-up GH issues for Tier 3.

After EVERY phase: run `uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace`. The repro should produce `fallback-content` starting from Phase 3 (after the read-site migration finishes the path). Before Phase 3 it might still be empty (the bug) — that's expected.

**Recommended checkpoint**: after Phase 2 and before Phase 3, run a focused code review (`/code-review`). Phase 2 is the largest cross-cutting change and merits an isolated review before doubling the diff with the consumer migration.
