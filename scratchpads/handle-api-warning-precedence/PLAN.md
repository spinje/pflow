# Implementation Plan — handle_api_warning short-circuit precedence trio

**Issues:** #301 (control-flow), #474 (display), #249 (progress callback)
**Folded in (user-approved):** #235 api_warning-suggestion slice, #437 no-successor routing-hint demotion
**Branch/worktree:** `fix/fix-handle-api-warning-precedence`

This plan is self-contained. An implementer should be able to execute it end-to-end without
re-deriving anything. Every edit has an exact file + anchor + before/after. Every affected test
is enumerated with its exact change. Verified facts are marked `[V: <evidence>]`.

---

## 0. Background: the shared root cause

Engine step 10 (`src/pflow/runtime/engine/engine.py:1108-1128`) runs `detect_api_warning` on EVERY
non-cache node **regardless of the action the node returned**, and `handle_api_warning`
short-circuits (`return "error"`) before steps 11–17.5. That one unconditional short-circuit
produces all three symptoms:

- **#301**: `WorkflowExecutor.post()` (`workflow_executor.py:417-424`) writes
  `shared[id]["error"]="WorkflowExecutor failed ...: ...not found"` AND returns the `error_action`
  value (e.g. `"continue"`). The detector matches `"not found"` → overrides `"continue"`→`"error"`.
  [V: searcher traced post→detector→handle_api_warning; pinned by the test we flip in §3.1]
- **#474**: `copy-file` returns action `"error"` (via `exec_fallback`→`post`, NOT raise, after
  retries — `copy_file.py:189-225`) with `error="...does not exist"`. Detector matches → api_warning
  display, never reaching step 17.5's `on_error_recovery`.
- **#249**: `handle_api_warning` emits `node_warning` but never `node_complete`.

## 0.1 The precedence principle (the whole fix in one sentence)

> The api_warning detector exists to **upgrade a SILENT success** (action `default`/`None`/`end`
> whose output betrays an API failure — Slack `ok:false` in a 200, MCP application-level
> `status:error`). Once a node returns a **deliberate verdict** — an `error` action, OR a custom
> route like `error_action: continue` — that verdict is authoritative; the detector must neither
> override the routing (#301) nor relabel the display (#474).

## 0.2 Verified non-consequences (do NOT "fix" these — they are correct)

- **Workflow status is unchanged.** `_determine_status` (`runner.py:594`) returns FAILED iff the
  final action starts with `"error"`. An MCP/HTTP `error`-action failure ends FAILED (no handler)
  or DEGRADED (handler) identically with or without the detector. The change is display + failure
  category ONLY. [V: runner.py:585-601]
- **Silent-failure detection is preserved.** A node that returns `"default"` while its output is a
  silent API failure (the detector's real purpose) STILL fires. [V: gate admits `"default"`; the
  L516 MCP test uses action `"default"` and stays green — see §3 "unaffected".]
- **`detect_api_warning` isolation tests are unaffected** — they call the detector directly with no
  action. [V: `tests/test_execution/test_api_warning_system.py` makes direct calls.]
- **Batch behavior is UNCHANGED by this plan.** `execute_batch` returns `"default"` for success AND
  partial-continue-failure (fail_fast raises → except path). Since the gate ADMITS `"default"`, the
  detector runs on the batch aggregate exactly as it does today — E1 changes nothing for batch.
  (Separately, the detector returns `None` on a partial-failure batch aggregate today, but NOT for
  the reason a first reading suggests: the aggregate `{results, count, success_count, error_count,
  errors, batch_metadata}` HAS a top-level `errors` list, which DOES enter `_check_graphql_errors`
  (`api_warning_detector.py:289`). It's harmless only because that function reads `errors[0].get(
  "message", "GraphQL error")` and batch error records have no `"message"` key (they use `"error"`),
  so it falls to the non-matching `"GraphQL error"` default → `_warning_from_message` returns `None`.
  This is an accidental-safety property, pinned by T6. [V: read `api_warning_detector.py:276-299`;
  searcher read `batch_executor.py:964-1068`.])

---

## 1. Source edits

### E1 — Action-gate the detector (#301 + #474)

**File:** `src/pflow/runtime/engine/engine.py`

**(a)** Add a module-level constant. Place it next to `_NODE_TYPE_FAILURE_CATEGORY`
(defined at `engine.py:65`); add immediately after that dict's closing brace:

```python
# Actions that represent a clean-success verdict — the node made no failure or
# routing decision of its own. The api_warning detector only UPGRADES these into
# failures (a node that returned "default" but whose output betrays a silent API
# error, e.g. Slack ok:false in a 200). Any other action — an "error", or a
# deliberate custom route like error_action's "continue" — is the node speaking
# for itself, and must not be second-guessed by the detector. See GH #301 / #474.
_CLEAN_SUCCESS_ACTIONS = frozenset({"", "default", "end"})
```

**(b)** Replace the step-10 block. CURRENT (`engine.py:1108-1109`):
```python
            # 10. API warning detection
            warning = detect_api_warning(config.node_id, shared, node_type_name=config.node_type_name)
```
NEW:
```python
            # 10. API warning detection. Only run it on a clean-success verdict — see
            # _CLEAN_SUCCESS_ACTIONS. A node that returned an error action (GH #474) or a
            # deliberate custom route like error_action's "continue" (GH #301) has already
            # spoken; the detector must not override its routing or relabel its failure.
            # error-action failures fall through to step 17.5, which writes the on_error_recovery
            # diagnostic (with handler) or a plain node failure (terminal) — consistent across
            # all node types, independent of whether the error text matches a pattern.
            warning = None
            if action is None or str(action) in _CLEAN_SUCCESS_ACTIONS:
                warning = detect_api_warning(config.node_id, shared, node_type_name=config.node_type_name)
```
The existing `if warning:` block (engine.py:1110-1128, incl. the batch-trace drain) is UNCHANGED —
it already guards on `warning` truthiness, and `warning` is now `None` for non-clean actions.

**Edge cases [all V]:**
- `action` is always bound at line 1108 (set at step 9: batch `engine.py:1084`, single `:1102`),
  both inside the same `try`. The `except` path never reaches step 10.
- Non-string action (e.g. `None`, or an int) → `action is None` short-circuits, else `str(action)`
  coerces safely.
- WorkflowExecutor SUCCESS may return a child custom action (`workflow_executor.py:430-433`) → not
  clean → detector skipped, but a successful sub-workflow's output has no error field so the
  detector would return `None` anyway. No behavior change.

### E2 — Emit `node_complete` from `handle_api_warning` (#249)

**File:** `src/pflow/runtime/engine/instrumentation.py`

Insert a `call_completion_callback` call AFTER `record_trace(...)` (ends at `instrumentation.py:797`)
and BEFORE the `# LAST STEP: archive ...` comment (`:799`). This mirrors the happy path's
step-16 → step-17 → step-17.5 ordering, and runs while `shared[node_id]` is still at the root
(`call_completion_callback` reads `exit_code`/`batch_metadata` from it).

Insert:
```python
    # Emit node_complete so progress UIs stop showing this node as still running
    # (GH #249). Must run BEFORE mark_node_failed moves the data into __failures__,
    # matching the happy path's step-17 → step-17.5 order. node_warning (above) +
    # node_complete render as two clean lines in OutputController.
    call_completion_callback(node_id, shared, "error", duration_ms)
```

**Edge cases [all V]:**
- `call_completion_callback` is defined in the SAME module (`instrumentation.py:610`) — in scope, no import.
- Its `error=` parameter is **vestigial** (never read; `error_message` derives only from
  `exit_code`/`action`). So we pass NO `error` kwarg. [V: searcher read full function body.]
- `node_warning` then `node_complete(is_error=True)` renders cleanly: `_handle_node_warning`
  (`output_controller.py:311-329`) closes the partial line; `_handle_node_complete` (`:250-303`)
  calls `_ensure_node_line_open` (`:209-221`) which re-emits a fresh `node_id...` lead-in. Output:
  `node_id... ⚠️ <warning>` then `node_id... ✗ Failed`. No corruption, no dangling partial. [V]
- No existing test asserts `handle_api_warning`'s callback events, so adding `node_complete`
  breaks no callback-sequence test. [V: searcher inventory.]

### E3 — Actionable, recovered-aware suggestions (#235 api_warning slice)

**File:** `src/pflow/runtime/engine/instrumentation.py`
**Scope guard:** ONLY the `handle_api_warning` producer. Do NOT touch
`runner._extract_runtime_warnings` (that is the separate, larger #235 job).

`handle_api_warning` now fires ONLY for SILENT failures (action clean-success but output matches an
API-error shape). The current suggestions (`instrumentation.py:816-819`) misframe it as an upstream
problem. Replace the `Diagnostic(...)` construction (`:813-823`) with recovered-aware suggestions.

CURRENT (`:813-823`):
```python
    warning_diagnostic = Diagnostic(
        severity=Severity.WARNING,
        message=warning,
        suggestions=[
            f"Inspect '{node_id}' upstream inputs and output to verify the warning is expected.",
            "If unintended, fix the upstream data or add error handling to this node.",
        ],
        node_id=node_id,
        source="runtime",
        context={"type": "api_warning", "recovered": recovered},
    )
```
NEW:
```python
    # Suggestions name the SILENT nature (the node reported success; the failure was
    # detected from its output) and stay recovered-aware: never advise "add on-error"
    # when the node already HAS one (recovered=True) — that is the same misdirection
    # #437 removes on the no-successor path.
    detected = (
        f"'{node_id}' returned a success action, but its output matched an API-error "
        "response — the engine flagged a failure the node itself did not report."
    )
    follow_up = (
        "It was routed to the on-error handler; inspect that handler's result to confirm "
        "the recovery is what you want."
        if recovered
        else
        "If the call really failed, add '- on-error: <handler>' to route it, or fix the "
        "upstream request. If the output is valid data the detector misread (a heuristic "
        "false positive), route past it with '- on-error:'."
    )
    warning_diagnostic = Diagnostic(
        severity=Severity.WARNING,
        message=warning,
        suggestions=[detected, follow_up],
        node_id=node_id,
        source="runtime",
        context={"type": "api_warning", "recovered": recovered},
    )
```
[V: no test pins the old suggestion strings — grep returned nothing.]

### E4 — Suppress the generic routing hint for node-failures (#437)

**File:** `src/pflow/runtime/engine/engine.py`, function `_handle_no_successor` (`:921-981`).

**Verified simplification basis:** the branch `if get_node_failure(shared, node_id) is not None:`
(`:959`) is reachable **iff** `last_action.startswith("error")`. [V: searcher proved the
equivalence — step-17.5 archive is guarded by `action.startswith("error")`; `handle_api_warning`
archives then returns `"error"`; the exception path re-raises and never reaches `_handle_no_successor`;
the loop guard clears stale failures on re-entry.] Therefore `is_node_failure` is ALWAYS `True` in
that branch, the `warning_msg` built with the "Add on-error" suggestion is consumed ONLY there, and
removing that write makes the `is_node_failure` conditional dead.

Replace lines `939-972` (from the `# Unmatched action` comment through the `mark_node_failed(...)`
call) — i.e. collapse the conditional and move `warning_msg` into the only branch that still uses it.

CURRENT (`:939-972`):
```python
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

        # If step 17.5 already archived this node (action started with "error"),
        # the failure record holds the real failure data and category (e.g.
        # shell_failure with exit_code/stderr/command). Don't overwrite it —
        # just surface the routing hint via __warnings__. Without this guard,
        # mark_node_failed's shared.pop() returns None, replacing rich data
        # with an empty-data routing_error record.
        if get_node_failure(shared, node_id) is not None:
            shared.setdefault("__warnings__", {})[node_id] = warning_msg
            return "error"

        # Non-error action with no matching successor: roll back success
        # bookkeeping added by cache_result and archive as a routing failure.
        invalidate_cache(node_id, shared)
        mark_node_failed(
            shared,
            node_id,
            category=FAILURE_CATEGORY_ROUTING,
            error=warning_msg,
            warning=warning_msg,
        )
```
NEW:
```python
        # A node that FAILED (action="error") is already archived in __failures__ with
        # its real error + remedy (engine step 17.5 / handle_api_warning). Emitting a
        # generic "add on-error" routing hint here would visually outrank that real fix
        # and train agents to route the failure instead of fixing its cause (GH #437).
        # The failure already stands on its own; just propagate "error". (This branch is
        # reachable only for action="error" — only that path archives into __failures__.)
        if get_node_failure(shared, node_id) is not None:
            return "error"

        # A custom (non-error) action with no matching successor IS a genuine routing
        # bug — surface it. Roll back the success bookkeeping cache_result added and
        # archive as a routing failure.
        warning_msg = (
            f"Node '{node_id}' returned action '{last_action}' "
            f"but no successor edge matches. Available: {list(curr.successors)}. "
            'Use next: str = "end" to terminate intentionally.'
        )
        invalidate_cache(node_id, shared)
        mark_node_failed(
            shared,
            node_id,
            category=FAILURE_CATEGORY_ROUTING,
            error=warning_msg,
            warning=warning_msg,
        )
```
The trailing trace-flip block (`:973-981`, `if self.trace is not None: self.trace.mark_last_event_failed(...)`)
is UNCHANGED — it stays after the `mark_node_failed` call in the routing-bug branch.

**Verified safe [all V]:**
- Terminal-failure error display reads `__failures__[id].error` first (`executor_service._extract_error_info`
  path 1, `:156-171`); `__warnings__[id]` is only a last-resort fallback for records whose
  `error is None`. Removing the routing hint does NOT lose the real error.
- `WorkflowExecutor._extract_child_error`'s `__warnings__` fallback path remains in the code; its
  unit test builds a synthetic store and is unaffected (§3 lists it as untouched).

### E5 — Update the stale MCP comment

**File:** `src/pflow/nodes/mcp/node.py:413-416`. The comment documents the old "api_warning may
upgrade tool errors" reliance, which E1 ends (MCP tool errors return action `"error"` → detector
skipped → plain `mcp_failure`). Replace:
```python
            # Return "error" so workflow error handling can respond
            # API warning detection in InstrumentedNodeWrapper may upgrade clear
            # resource failures into user-facing warnings before execution stops.
            return "error"
```
with:
```python
            # Return "error" so workflow error handling can respond. (A tool error is a
            # deliberate failure verdict — the engine's api_warning detector defers to it
            # and routes/records it as a normal mcp_failure; it is not relabeled "API
            # error". See engine _CLEAN_SUCCESS_ACTIONS / GH #474.)
            return "error"
```

### E6 — Update CLAUDE.md docs

- `src/pflow/runtime/CLAUDE.md` — the `error_action` bullet (under WorkflowExecutor) currently
  states the api_warning layer overrides `error_action` for pattern-matching text "as pre-existing
  engine behavior ... Tracked as GH #301." Replace with: the detector now defers to a node's
  deliberate verdict (error action or custom route); GH #301 closed. Remove the caveat.
- `src/pflow/runtime/engine/CLAUDE.md` — THREE edits:
  - step-10 bullet (`detect_api_warning → handle_api_warning if found`): note it only runs for
    clean-success actions.
  - `handle_api_warning` bullet: note it now also emits `node_complete` (#249).
  - the `_handle_no_successor` description (currently `engine/CLAUDE.md:85`: "...preserves the
    existing failure record and **only writes a routing hint to `__warnings__`**"): replace the
    bolded clause with "returns `'error'` without writing any hint (the real failure data is already
    in `__failures__`)". [impact-review W1]
- `src/pflow/execution/executor_service.py:149-152` — the historical comment ("`_handle_no_successor`'s
  routing hint (written via `__warnings__` ...) masked the real `Command failed...` message")
  describes behavior E4 removes. Reword to past tense / note the hint is no longer written for
  error-action nodes (the `__warnings__`-priority reordering it documents is still valid). [impact-review W2]

---

## 2. New regression tests

### T1 — #474 recovered resource-pattern failure renders as recovery (NOT api_warning)
**File:** `tests/test_execution/test_on_error_recovery.py` (end-to-end via `WorkflowRunner`, the
right layer per tests/CLAUDE.md gotcha #20). Mirror the structure of the existing
`test_on_error_recovery_reports_degraded_status` (`:41`), but use a node whose failure text MATCHES
an api_warning pattern. Use `copy-file` with a guaranteed-missing source (its `exec_fallback`
yields `"Error: Source file '...' does not exist..."`, action `"error"` — matches "does not exist").
- Build inline IR: node `copy-missing` type `copy-file`, params `source_path` = a path under
  `tmp_path` that does not exist, `dest_path` = `tmp_path/"dest.txt"`, `retry: {max: 1, wait: 0}`;
  node `handler` type `shell` `command: echo recovered`; on-error edge `copy-missing -error-> handler`.
  (Construct the on-error edge the same way the sibling tests in this file do.)
- Assert: `result.status == WorkflowStatus.DEGRADED`; the `__warnings__["copy-missing"]` Diagnostic
  has `context["type"] == "on_error_recovery"` (NOT `"api_warning"`); assert
  `__failures__["copy-missing"]["category"] == "node_action_error"` (copy-file is absent from
  `_NODE_TYPE_FAILURE_CATEGORY` → falls back to `FAILURE_CATEGORY_NODE_ERROR`) — a positive assertion
  of the real category, stronger than just "not api_warning". [feature-review S2]

### T2 — #249 handle_api_warning fires node_warning AND node_complete
**File:** `tests/test_runtime/test_instrumented_wrapper.py` (alongside the existing
`call_*_callback` tests). **Add `handle_api_warning` to the import block (`:20-25`)** — it is not
currently imported and the test calls it directly. [plan-review S1] Register a recording progress
callback in `shared["__progress_callback__"]`, call `handle_api_warning(node_id, shared,
"API error: x", metrics=None, trace_collector=None, start_time=..., shared_keys_before=set(),
node_type_name="HTTPNode", node_params={})`, and assert the recorded events include BOTH
`("node", "node_warning", ...)` and `("node", "node_complete", ...)`. (This is a focused
callback-event test matching #249's stated test ask; the OutputController's clean rendering of the
`node_warning → node_complete` sequence is verified by inspection — see E2.)

### T3 — #301 error_action: continue with a "not found" child routes to the continue successor
**File:** `tests/test_runtime/test_workflow_executor/test_prep_error_action.py` (new test in the
flipped class from §3.1). WorkflowExecutor `error_action: continue` referencing a missing child
(prep error text contains "not found"), WITH a `continue` successor node. Assert the continue
successor RAN (its output present) and the WorkflowExecutor node is NOT archived in `__failures__`.

### T4 — #437 terminal node-failure emits no routing hint; routing bug still does
**File:** `tests/test_runtime/test_engine_behavior.py`.
- (a) A node returns `"error"`, no error successor → `__warnings__` does NOT contain a
  `"no successor edge matches"` entry for it; the real error is in `__failures__[id].error`.
- (b) A node returns a CUSTOM action with no matching successor (the routing-bug case) → STILL
  archived `routing_error` with a `"no successor edge matches"` message containing
  `'Use next: str = "end"'`. (Mirror the existing `test_custom_action_routing_failure_flips_trace_event`.)

### T6 — batch partial-failure aggregate does NOT trigger an api_warning (pins accidental safety)
**File:** `tests/test_execution/test_api_warning_system.py` (direct detector call). Build a
batch-shaped aggregate with a non-empty `errors` list using the real shape
(`{"results": [...], "count": 2, "success_count": 1, "error_count": 1, "errors": [{"index": 0,
"item": ..., "error": "channel not found"}], "batch_metadata": {...}}`) and assert
`detect_api_warning("fanout", {"fanout": <aggregate>}) is None`. This pins the accidental-safety
property §0.2 documents: the top-level `errors` list enters `_check_graphql_errors` but yields the
non-matching `"GraphQL error"` default. If a future change gives batch error records a `"message"`
key (or changes the fallback), this test fails loudly. [feature-review W1]

### T5 — #235 suggestions are recovered-aware
**File:** `tests/test_execution/test_api_warning_system.py` (it already imports `handle_api_warning`).
Call `handle_api_warning` twice (once with an error successor present → `recovered=True`, once
without → `recovered=False`) and assert: the recovered diagnostic's suggestions do NOT contain
`"add '- on-error"`, while the non-recovered diagnostic's suggestions DO. (Assert behavioral
markers, not full strings.)

---

## 3. Existing tests to change (exhaustive — verified)

### 3.1 FLIP — `tests/test_runtime/test_workflow_executor/test_prep_error_action.py`
Class `TestApiWarningDetectorHijackIsPinned` (`:500`) + `test_file_not_found_hijacked_despite_error_action_continue`
(`:515`). The test's OWN docstring (`:518-524`) lists the migration. Do all of it:
- Rename class → e.g. `TestErrorActionDefersApiWarning`; rename test →
  `test_file_not_found_routes_via_error_action_continue`; rewrite both docstrings (the behavior is
  now CORRECT, not "pinned hijack").
- Flip `assert result == "error"` (`:551`) → `assert result == "continue"`.
- Replace the failure-archived assertions (`:555-558`) with
  `assert get_node_failure(shared, "missing_child") is None` (error_action routed cleanly — matches
  the `test_circular_reference_dispatches_error_action` pattern at `:253`).

### 3.2 EDIT docstring — same file, `test_circular_reference_dispatches_error_action` (`:220`)
Remove the obsolete note (`:225-231` docstring lines about "not found"/"403"/"401" being hijacked
and `TestApiWarningDetectorHijackIsPinned`). The detector no longer hijacks any error_action text.

### 3.3 REWRITE — `tests/test_runtime/test_engine_behavior.py::test_mcp_protocol_resource_message_routes_as_api_warning` (`:612`)
This test encodes the OLD inconsistency (a "repository not found" MCP protocol error → api_warning,
while "connection refused" → mcp_failure). After E1 both are `mcp_failure`. Update:
- Rename → e.g. `test_mcp_protocol_resource_message_routes_as_plain_failure`.
- `failure["category"]` (`:652`): `"api_warning"` → `"mcp_failure"`.
- `failure["error"]` (`:653`): `"API error: MCP tool failed: repository not found"` →
  `"MCP tool failed: repository not found"`.
- Remove the `__warnings__` routing-hint assertions AND their preceding comment (`:661-666` as a
  unit — the comment at `:661-663` "...the public runtime warning ... is the routing hint" describes
  behavior E4 removes). [plan-review W1]
- Keep `result == "error"`, `"poll" not in shared`, and the `failure["data"]` assertions (`:654-659`).

### 3.4 EDIT — `tests/test_runtime/test_engine_behavior.py::test_unhandled_mcp_protocol_error_stops_before_default_successor` (`:559`)
Remove the `__warnings__` routing-hint assertions (`:608-610`). Keep everything else (this test's
"connection refused" message never matched a pattern, so its `mcp_failure` category is unchanged by
E1). Update the comment at `:598-599` (no longer "pinned below").

### 3.5 EDIT — `tests/test_integration/test_failed_node_invariant.py::test_shell_error_without_on_error_preserves_shell_data_in_failure_record`
Remove the `__warnings__` routing-hint assertions (`:349-352`: `"broken" in warnings` /
`"no successor edge matches" in warnings["broken"]`). KEEP the core invariant (`:341-347` rich shell
data preserved) and the primary-error assertions (`:354-368`, including the anti-assertion at `:366`
which still holds). **Treat the comment block at `:349-368` as a unit needing review** — both the
`:349` comment ("Routing warning is still surfaced via `__warnings__`") and the `:355-358` "Pre-fix"
historical note describe the routing-hint behavior E4 removes; rewrite them to say the real shell
failure is the only signal now (no routing hint is written). [plan-review W2]

### 3.6 UNAFFECTED — must stay green (do NOT touch)
- `tests/test_runtime/test_engine_behavior.py::TestApiWarningRecovery::test_mcp_result_api_warning_with_error_successor_marks_warning_recovered` (`:516`)
  — MCP action `"default"` (application-level result error) → detector still fires. [V]
- `tests/test_runtime/test_engine_behavior.py::test_handled_mcp_protocol_error_routes_to_on_error_handler` (`:668`)
  — "connection refused" + handler → mcp_failure + on_error_recovery. [V: unaffected by E1/E4]
- `tests/test_runtime/test_engine_behavior.py::test_custom_action_routing_failure_flips_trace_event` (`:829`)
  and `test_error_action_routing_does_not_double_mark_trace` (`:897`) — read TRACE events, not
  `__warnings__`. [V]
- ALL of `tests/test_execution/test_api_warning_system.py` — direct `detect_api_warning` calls. [V]
- `tests/test_execution/test_on_error_recovery.py::test_api_warning_not_classified_as_recovery` (`:169`)
  — synthetic `__failures__` fed to `_extract_runtime_warnings`; not engine-gated. [V]
- `tests/test_execution/test_runner.py:161` — LLM-node `__warnings__` write, not the detector. [V]
- `tests/test_execution/formatters/test_success_formatter.py:400` — synthetic `Diagnostic`. [V]
- `tests/test_runtime/test_workflow_executor/test_workflow_executor.py::test_extract_child_error_from_warnings` (`:389`)
  — synthetic store, exercises the surviving fallback code. [V]

---

## 4. Verification

1. Baseline (pre-change, already captured): 205 passed across the 9 affected files.
2. After edits: `make test` and `make check` (ruff, ruff-format, mypy, deptry) must be clean.
3. Report the delta. Any NEW failure outside the §3.1–3.5 set is unexpected — investigate; do not
   blindly update a test to green.
4. Manual smoke (optional but recommended): run `examples/error-handling/retry-with-backoff.pflow.md`
   and confirm the recovered copy-file failure now renders the on-error-recovery message, not
   `⚠️ API error`.

## 5. Out of scope (do NOT do)
- Runner-wide `_extract_runtime_warnings` generalization (the full #235).
- Node-type scoping of the detector (rejected: would regress #508's top-level-flag behavior).
- A `_pflow_routed_via_error_action` marker (rejected in favor of the action gate).
- `#437` Option 2+ (per-error-class suggestion catalog) — only the minimal hint-suppression here.
