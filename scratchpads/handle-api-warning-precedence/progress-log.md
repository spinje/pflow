# Progress Log — handle_api_warning short-circuit precedence trio

**Plan:** `scratchpads/handle-api-warning-precedence/PLAN.md`
**Issues:** #301 (control-flow), #474 (display), #249 (progress callback); folds in #235 (api_warning slice), #437 (no-successor hint demotion)
**Branch:** `fix/fix-handle-api-warning-precedence`

---

## Pre-implementation verification (trust boundary)

Before touching code I verified every load-bearing claim in the plan against the source. All **Verified**:

- `engine.py:65` `_NODE_TYPE_FAILURE_CATEGORY` dict; `:1108-1109` step-10 detect; `:1110-1128` `if warning:` block; `action` bound at step 9 (batch `:1084` / single `:1102`), both inside the try. [V: read]
- `engine.py:921-981` `_handle_no_successor` — block to replace is `:939-972`, trace-flip `:973-981` stays. [V: read]
- `instrumentation.py:610` `call_completion_callback` (same module, in scope); `:765` computes `duration_ms`; `record_trace` ends `:797`, `# LAST STEP` comment `:799`; `mark_node_failed` runs LAST (`:825`) so `shared[node_id]` is still at root when a `node_complete` callback would read it. [V: read]
- `instrumentation.py:813-823` Diagnostic with the two old suggestion strings. [V: read]
- `mcp/node.py:413-416` stale comment; `executor_service.py:149-152` historical comment. [V: read]
- `copy_file.py`: missing source → `FileNotFoundError` raised from `exec` (retriable) → retries exhaust → `exec_fallback` returns `"Error: Source file '...' does not exist..."` → `post` returns `"error"`. Matches "does not exist" detector pattern. [V: read copy_file.py:72-76, 189-228]
- IR retry config shape is `retry: {max: N, wait: W}`. [V: compiler.py:337 `retry_data.get("max", ...)`]
- `route_action("continue", {})` → `is_clean_termination` returns `all([]) == True` → CLEAN_STOP, NOT routing error. So a sub-workflow `error_action: continue` with no `continue` edge clean-terminates with `result == "continue"` and no `__failures__` entry — this is exactly the existing `test_circular_reference_dispatches_error_action` pattern. Confirms the §3.1 flip. [V: engine.py:424-486]
- `test_mcp_result_api_warning_with_error_successor_marks_warning_recovered` uses MCP action `"default"` (clean-success) → detector STILL fires after E1. [V: test_engine_behavior.py:516]

**Baseline (pre-change):** `108 passed` across the 6 directly-edited test files (on_error_recovery, instrumented_wrapper, prep_error_action, engine_behavior, api_warning_system, failed_node_invariant).

---

## Implementation log

### 2026-06-16 — full implementation (E1–E6, T1–T6, §3.1–3.5)

**All plan steps executed. No steps skipped.** Source edits E1–E6 and the doc edits landed verbatim against the verified anchors. Tests T1–T6 added; existing tests §3.1–3.5 migrated.

**Verification done:**
- `make check` clean: ruff, ruff-format, mypy (0 issues / 230 files), deptry.
- Full suite: **7836 passed, 0 failed** (baseline for the 6 edited files was 108 → 257 with the new tests + untouched files).
- **Mutation tests** (guard against synthetic-green per tests/CLAUDE.md #19): reverting E1's gate → 4 core tests fail (T1, both §3.1 tests, §3.3); re-adding E4's routing-hint write → T4(a) + §3.5 fail; removing E2's `call_completion_callback` → T2 fails. All restored.
- **Manual smoke** (§4.4): `pflow examples/error-handling/retry-with-backoff.pflow.md` now renders `⚠ [copy-missing-file] Node ... failed — on-error → 'retry-exhausted'` (on_error_recovery), NOT `⚠️ API error`. Confirms #474 end-to-end.

**Key learnings / insights:**
- The whole control-flow fix is one gate (`action is None or str(action) in _CLEAN_SUCCESS_ACTIONS`). The detector's contract is "upgrade a SILENT success"; an error action or custom route is a deliberate verdict, so gating on clean-success actions is the precise expression of the precedence principle — no marker flag needed.
- E4's `is_node_failure` conditional was provably dead (the branch is reachable iff `last_action.startswith("error")`), so collapsing it removed a branch rather than moving complexity — passes the deletion test.
- `_check_graphql_errors` returns the literal `"GraphQL error"` (not `None`) for a batch aggregate's `errors[]` (records lack a `message` key), but `_warning_from_message("GraphQL error")` then returns `None` (matches neither validation nor resource patterns). T6 pins this accidental-safety chain so a future `message`-key addition fails loudly.

**Deviations from plan:** none of substance. The E3 ternary's `else` clause was written inline (`else "..."`) rather than `else` on its own line as drafted in the plan; ruff-format normalized it. Semantically identical.

**Trust boundary:** all behavioral claims **Verified** by mutation test + full suite + smoke run. Doc edits (CLAUDE.md ×2, two source comments) are descriptive, not load-bearing.

### Post-implementation review (2 parallel reviewers, sonnet)

**review-simplicity:** no critical/warning findings — "final code is as simple as the problem allows." Confirmed `action is None or str(action) in _CLEAN_SUCCESS_ACTIONS` is the minimal correct form (`node._run()` returns `Optional[str]`; `str(None)` is `"None"`, not in the set, so the `is None` short-circuit is load-bearing), and the `_handle_no_successor` collapse left no dead code. **Applied** its one take-or-leave suggestion: a sentence explaining why `"end"` is a clean-success action (intentional-termination directive, not a failure acknowledgement).

**review-impact-completeness:** no critical issues, no missed consumer that breaks. Two flagged items, both **deliberately not actioned** (with rationale):

1. *Pre-existing:* `runner._extract_runtime_warnings` (runner.py:622) defaults non-Diagnostic `__warnings__` strings to `type:"api_warning"`. After Change B the only such string left is the custom-action routing-bug message (semantically routing_error). This mislabeling **predates** this work and my change strictly REDUCED its surface (removed the error-action routing-hint write). Fixing it = touching `_extract_runtime_warnings`, which the plan §5 explicitly scopes out as the larger #235 job. Workflow is FAILED (not DEGRADED) so the secondary warning isn't the headline. **Left as-is, out of scope.**
2. *Coverage:* no full-`WorkflowRunner` test for clean-success-node + silent api_warning + on-error → DEGRADED. Verified the path IS engine-driven by the must-stay-green `test_mcp_result_api_warning_with_error_successor_marks_warning_recovered`, and the recovered-Diagnostic→DEGRADED chain is pinned by `test_on_error_recovery.py`. A faithful outer-runner test needs MCP/HTTP mock scaffolding (the detector only inspects the `result` wrapper for MCP nodes — a code node's nested `result` is NOT inspected, verified in api_warning_detector.py), which would be clever, not boring. **Not added — adjacent layers cover it.**

Re-verified clean after the comment edit (ruff + ruff-format pass; 38 affected tests pass).

### End-to-end CLI verification (real `pflow` runs, adversarial)

Built 9 `.pflow.md` workflows and ran them through the real CLI (full `WorkflowRunner` pipeline, not `engine.run()` directly). All behaviors confirmed end-to-end:

| # | Scenario | Result |
|---|----------|--------|
| T1 | #474 error-action + on-error handler (copy-file "does not exist") | DEGRADED, `on-error → 'recover'` (NOT "⚠️ API error"), exit 0 ✓ |
| T2 | #474 error-action, NO handler | FAILED, headline = real `Source file ... does not exist` (NOT relabeled), no routing hint, exit 1; JSON category=`execution_failure` (NOT `api_validation`) ✓ |
| T3b | #301 dynamic `workflow: ${child}` missing, `error_action: continue` | NOT hijacked — node `✓`, run SUCCESS exit 0, "not found" text honored as `continue` ✓ |
| T4b | #437 runtime custom-action routing bug (computed `next`) | hint STILL fires: `...no successor edge matches... Use next: str = "end"`, exit 1 ✓ |
| T5 | **Silent success** (HTTP 200 + GraphQL errors body, action `default`) | detector STILL fires → `API error: Repository not found`, exit 1 — core purpose preserved ✓; E3 non-recovered suggestions render ✓ |
| T6 | **Recovered silent success** (T5 + on-error) | DEGRADED exit 0; node line closes cleanly (#249); E3 recovered suggestion (NO "add on-error"); JSON `type=api_warning, recovered=True` ✓ — closes the reviewer-flagged coverage gap |
| T7 | `error_action: default` (clean-success value) + missing child | detector STILL applies → api_warning (BOUNDARY, see below) |
| T8 | batch partial failure, `error_handling: continue` | DEGRADED via **batch** warning path (NOT api_warning), no crash, exit 0 ✓ — accidental-safety confirmed live |
| T9 | happy-path pipeline with "error" in plain output | SUCCESS, no false api_warning, exit 0 ✓ |

**Reachability findings (the unit-test vs real-pipeline gap):**
- A *static* missing-child path is caught at **validation** (T3 original), and a *literal* `next: "nowhere"` at **parse** (T4 original) — so the runtime #301/#437 paths are only reachable via **dynamic** refs (`workflow: ${var}`, computed `next`). The unit tests reach them by calling `engine.run()` directly. Both runtime paths verified correct via the dynamic forms (T3b/T4b). Static pre-emption is correct defense-in-depth, not a defect.

**Two findings (neither a regression; both pre-existing or by-design):**
1. **`error_action: default`/`end`/`""` is NOT protected by the #301 fix** (T7). These values ARE clean-success actions, so the detector still applies — consistent with the precedence principle (the user opted into "clean success"; the detector un-masks silent clean-success failures). The fix protects custom-route error_action values (`continue`), which is what the issue/plan target. **By design; documented boundary.**
2. **Custom-action routing-bug warnings (T4b) and batch warnings (T8) still render the old canned suggestions** ("Inspect upstream inputs / add error handling") because they flow through `runner._extract_runtime_warnings`'s legacy non-Diagnostic string/dict path (`type:"api_warning"` default). **Pre-existing**, untouched by this diff (my E3 changed only `handle_api_warning`'s Diagnostic). My E4 strictly *reduced* this surface (removed the error-action routing-hint write). Fixing it = the deferred #235 `_extract_runtime_warnings` generalization (plan §5, out of scope). The primary error message already carries the correct fix; only the secondary suggestions are stale.

**Full suite re-run after all work: 7836 passed.** Verdict: the fix works end-to-end across all five issues; the detector's core purpose (silent-success upgrade) is preserved, not disabled; no regression found.

### High-value test added (test-fidelity gap closed)

The CLI verification exposed one real fidelity gap: the #301 engine-level tests
(`TestErrorActionDefersApiWarning`) call `engine.run()` directly, **bypassing the runner's
validation**. In production a STATIC missing-child path is caught at validation and never
reaches runtime error_action dispatch — the fix only fires via a DYNAMIC `workflow: ${var}`
ref (opaque to the validator). So no automated test covered the actual production-reachable
cross-layer path (tests/CLAUDE.md gotcha #20).

Added `TestErrorActionDefersApiWarningEndToEnd::test_dynamic_missing_child_continue_routes_through_full_pipeline`
(test_prep_error_action.py): runs a dynamic-child + `error_action: continue` + a real
`continue` edge through the **full `WorkflowRunner` pipeline** (validate→compile→execute),
hermetic (missing file under tmp_path). Asserts the run SUCCEEDS, the continue route is
FOLLOWED (`after` node ran), and the WorkflowExecutor node is not archived. The single
`result.success is True` assert guards BOTH layers — it flips to False if validation ever
eager-resolves dynamic refs OR the detector gate regresses. **Mutation-verified:** reverting
the gate fails it with the exact hijack (`API error: WorkflowExecutor failed...`).

Considered but deliberately NOT added (would be coverage-padding, not unique value):
- A terminal copy-file #474 end-to-end — the gate is already caught by T1 (recovered,
  end-to-end + mutation), and the terminal unprefixed-error category is pinned by §3.3
  (MCP, engine-level). No unique failure mode.
- An automated HTTP-200-GraphQL silent-success test — needs a live server (non-hermetic);
  the path is covered by direct detector tests + the engine-level recovery test + T5/T6 manual.

Reviewed my own tests for shallowness: none are circular or happy-path-only; the §3.x
migrations removed assertions only for removed behavior (§3.5 was *strengthened* to assert
hint absence). All core-behavior tests are mutation-confirmed.

**Final: 7837 passed; make check clean.**
