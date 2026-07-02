# Task 125 Review: Human-in-the-Loop Approval Gates (blocking mode)

## Metadata

- Implemented 2026-07-02, branch `feat/human-loop-approval-gates`, PR #554 (open, not yet merged).
- Commits: `2e533e2f` (phases 1-2, engine substrate), `301a002c` (phase 1-2 test pins), `2593884c`
  (phases 3-7: resolver, DENIED status, `--auto-approve`, dry-run parity, docs), `9fe66c96`
  (5 code-review fixes post-PR).
- Chronological journey (plan, deviations, deep-review findings, day-by-day): see
  `implementation/progress-log.md` — this review does not re-narrate it.
- Project stakes: pflow is MVP-feature-complete on PyPI but explicitly has "no users yet — no
  external compatibility to preserve" (root CLAUDE.md). Read this task's integration points as
  load-bearing for the CODEBASE'S OWN forward development (Tasks 164/171/176 build directly on
  this substrate), not as production-outage risk.

## Read First — the load-bearing block

**What exists now**: any `.pflow.md` step can declare `approval: required` (pauses for a
terminal yes/no before it runs) or a `claude-code`/`code` step can raise a decision
**escalation** via `result.escalation` (pauses for a choice). Both are one payload
(`GateRequest`) resolved by one pluggable function (`__gate_resolver__`). Denial is a clean
stop (`WorkflowStatus.DENIED`, exit 3), not a failure. Durable/non-TTY gates are **out of
scope** — Task 171 builds on this substrate without changing the payload shape.

**Read these first**:
- `src/pflow/core/gate.py` — `GateRequest`/`GateResolution` (the payload IS the seam, ADR-0009).
- `src/pflow/runtime/engine/gate.py` — `resolve_gate`, `run_approval_gate`, `detect_escalation`,
  `run_escalation_gate`, `scan_batch_escalations` (the engine-side "when").
- `src/pflow/runtime/engine/engine.py:994` `_execute_node` — seams at step 7.5 (pre-exec
  approval), 10.5/17.7 (post-exec escalation detect/pause), and the
  `except (GateDenied, GateNotInteractiveError)` handler (~line 1324) — the ONLY place a gate
  verdict is distinguished from a node failure.
- `src/pflow/execution/gate_prompt.py` — `build_gate_resolver` (the "how" — CLI TTY / MCP /
  parallel-worker, ONE function).
- `src/pflow/execution/plan.py::_annotate_entry` (renamed from `_annotate_loop_entry`) — the
  single funnel stamping `PlanEntry.approval` for dry-run parity.

**Invariants that must NOT break**:
- **Gate trace lines (`kind: "gate"`) must stay DISK-ONLY** — never appended to
  `collector.events`. Violating this makes a gate line the node's "final event" in
  `final_events_by_node`, and `--only` snapshot seeding silently skips that node.
- **`GateDenied`/`GateNotInteractiveError`/`GateResolverError` must be re-raised UN-converted at
  every generic `except Exception`** between the gate and the runner (engine `_execute_node`,
  `WorkflowExecutor.exec`, batch retry loops via `retriable=False`). Losing this exemption at
  any ONE of these four boundaries makes a human's "no" become error-routable —
  `error_action: continue` would silently run past a denial. (`GateResolverError` — a resolver
  bug, added post-review — needs the same exemption for a different reason: at the post-exec
  escalation seam the node's success is already traced, and the generic arm would archive a
  successful node into `__failures__` with a duplicate error event.)
- **A sub-workflow host's own trace event must be recorded even on a gate stop** (see Gotchas
  below) — skipping this orphans any sibling event recorded before the gate fired, and
  `finalize()`/`tree()` raise in-memory, silently losing the run's trace file.
- **Any new `PlanEntry` field that should affect dry-run parity must be forwarded in BOTH**
  `_annotate_entry` (single-item path) **and** `_aggregate_batch_child_plans` (batch-of-workflow
  path) — the second site already dropped `approval` once; it builds fresh `PlanEntry` objects
  and does not inherit fields by default.
- **`sorted()` on the parser IR at `_prepare_gate_resolver` must filter falsy node ids first** —
  the IR hasn't been schema-validated yet at that call site.

## What Was Built (actual vs. planned)

The full plan (7 phases) is in `implementation/implementation-plan.md`; the real build tracked
it closely but diverged in a few places worth knowing:

- **`GateRequest`/`GateResolution` live in `core/gate.py`, not `runtime/engine/gate.py`** as
  originally planned — `core/exceptions.py` needs to carry the payload on `GateDenied`/
  `GateNotInteractiveError`, and `core/` cannot import `runtime/`. The engine-side *behavior*
  (when to gate) still lives in `runtime/engine/gate.py`; only the payload dataclasses moved.
- **Parallel-batch worker isolation is a boolean flag (`__gate_prompt_allowed__` →
  `allow_prompt` kwarg), not resolver substitution.** The reviewed plan called for swapping in a
  non-prompting resolver inside the worker's `item_shared`, mirroring the progress-callback
  buffer pattern — rejected at implementation because building that resolver requires
  `execution.gate_prompt.build_gate_resolver`, and `batch_executor.py` lives in `runtime/`,
  which cannot import `execution/` (layering violation). The flag-plus-kwarg shape gets the
  same guarantee (auto-approve works, prompting never does) without the cross-layer call.
- **No `RunnerConfig.auto_approve` field.** The resolver travels as a `WorkflowRunner.run(...,
  gate_resolver=...)` keyword argument, mirroring `progress_callback` end-to-end — CLI and MCP
  each build their own via `build_gate_resolver`. `RunnerConfig` stayed execution-config-only.
- **No dedicated `except GateDenied`/`except GateNotInteractiveError` arms in the runner.** The
  plan assumed the generic `_exception_to_result` would need new arms; verification showed it
  already preserves payload diagnostics correctly via `exception_to_diagnostics()`. `DENIED` vs
  `FAILED` is now a one-line `isinstance` check inside the existing generic path.
- **Escalation is in scope** (a mid-implementation owner decision, not in the original spec) —
  the trigger is a reserved `result.escalation` key (works for any node type, not a new node
  type), with a lenient-but-loud shape ladder (dict/string/malformed/schema-soft-fail-adjacent)
  that never silently drops an escalation attempt without at least a degrading warning.
- **`approval` is explicitly NOT stamped on `cached` `PlanEntry`s** (added during the deep-review
  pass, not the original plan) — the engine's gate seam sits after the cache-hit early-return, so
  a cache hit never gates; stamping it would make the dry-run footer/JSON promise a pause that
  never happens.
- **Guide topic hook deferred from Phase 1 to Phase 6** — it needed `guide/features/approval.md`
  to exist first.

## Patterns & Anti-Patterns

**The payload-is-the-seam pattern (ADR-0009) paid off repeatedly** — one `GateRequest.to_dict()`
feeds the TTY prompt, the `gate` trace event, the masked `GateNotInteractiveError` diagnostic,
and (unchanged) will feed Task 171's persistence. When a review flagged masking as broken, the
fix touched exactly the two render sites, not the payload itself. **Reuse this for any future
human-decision or cross-surface payload**: one JSON-native dataclass, resolved by a plain
function, never an ABC/strategy hierarchy (`ApprovalSurface` was explicitly proposed and
rejected — "one adapter is a hypothetical seam" per project language).

**One resolver builder, N configurations** (`build_gate_resolver(auto_approve,
output_controller)` → CLI passes a real controller, MCP passes `None`, parallel workers pass
`allow_prompt=False`) beats three parallel resolver implementations. `can_prompt` is reused for
both the resolver's internal gate AND the CLI's pre-flight warning — no re-derivation.

**Cross-cutting compile-time flags belong in ONE shared planner funnel.** `_annotate_entry`
(the renamed `_annotate_loop_entry`) is the single place a `NodeConfig` fact gets projected onto
a `PlanEntry`, covering both dispatch paths (standard node, sub-workflow). The lesson from the
`_aggregate_batch_child_plans` bug: **a third path exists for batch-of-workflow aggregation,
and it does NOT automatically inherit funnel-stamped fields** — it builds fresh `PlanEntry`
objects from scratch. Any future NodeConfig flag needing dry-run visibility must explicitly
check this third site too.

**Anti-pattern, tried and reverted twice this session**: `git stash` to mutation-verify a fix.
Untracked files don't stash, and in an earlier session this accidentally applied an unrelated
stash from another branch. **Mutation-verify with a temporary `Edit` + revert instead** — used
successfully 7 times across this task's two review-fix rounds, every time confirming the new
test actually fails against the un-fixed code before trusting it.

## Gotchas & Non-Obvious Coupling

**The orphaned-trace-event bug (found by code review, not the original test suite) is the
sharpest gotcha in this codebase.** `WorkflowExecutor.exec()` reserves a trace seq via
`trace.descend()` before running a sub-workflow; the host's OWN completion event is normally
written at engine step 16 (`record_trace`, reusing that reserved seq) — but only when
`node._run()` *returns*. The Task 125 design deliberately makes gate exceptions `raise` instead
of returning (so a denial can't be error-routed) — which means step 16 never runs, and the
reserved seq gets no event. If a SIBLING step inside that sub-workflow already recorded before
the gate fired, its event is now orphaned. The failure mode is NOT what it looks like: it's not
a later "corrupt trace file" read error — `WorkflowTraceCollector.finalize()` itself calls
`tree()` **in-memory** and raises there, *before* the `run.complete` trailer is ever written.
`runner.py`'s `contextlib.suppress` swallows this silently, so a perfectly normal-looking denied
run silently has no trace file at all (one easy-to-miss log line). The fix
(`engine.py`'s gate-exception handler reading `getattr(node, "_host_frame", None)` and calling
`record_trace(..., success=True, frame=host_frame)` before re-raising) is a genuinely
non-obvious cross-file coupling: **`engine.py` now reaches into a `WorkflowExecutor`-instance
attribute (`_host_frame`) that only exists because that specific node type happens to set it.**
If `_host_frame`'s name or set-timing ever changes in `workflow_executor.py`, this silently
regresses — the two mutation-verified tests in `test_gate_trace.py`
(`test_denied_nested_gate_after_sibling_event_does_not_orphan_trace` and its non-interactive
sibling) are the only thing that would catch it.

**`resolved_via` disambiguates prompt vs. flag, but there's no `ui` value yet** — Task 176
(web bridge) is expected to add it; don't be surprised the enum looks incomplete.

**Escalation only fires on a CLEAN-SUCCESS action** (`""`/`"default"`/`"end"`/`None`) — a `code`
node using dynamic `next:` routing cannot escalate from the same execution (its action IS the
route target, and the detector defers to a node's own routing verdict, mirroring the existing
api-warning-detector rule). Escalate from the agent step; route on the decision downstream.

**The masking fix lives in two independent call sites** (`gate_prompt.py::_format_preview` and
`exceptions.py::_masked_gate_payload`), both now calling `sanitize_parameters()` for non-string
values but as separate, hand-written call expressions — there is no single shared "mask a gate
preview" function. If the masking policy changes again, both sites need editing; nothing
enforces they stay in sync beyond code review.

**`sanitize_parameters()` truncates long strings to 100 chars** — a side effect of reusing it
for nested-value masking that's more aggressive than `_format_preview`'s own 200-char
truncation. Deliberately left as-is (applies only to previously-untruncated nested dict/list
values, not top-level strings, which keep their existing 200-char path) — but if a preview ever
looks unexpectedly short, this is why.

**Batch-item gate events do not reach the trace** (deliberately NOT fixed — a known v1
limitation, documented in `guide/features/approval.md`). A gate answered inside a `batch:`
item's sub-workflow is honored correctly but leaves no audit trail, because batch-item children
run under buffered (non-run-scoped) trace collectors. Flagged as Task 171's problem, since that
task reworks how gate records persist anyway.

## Integration Points

**Depends on** (pre-existing, unmodified by this task): the `--only` snapshot machinery
(`seed_snapshot_into_shared`, the loader's status allowlist — extended to reject `"denied"` too,
same shape as `"failed"`), the `_PROPAGATED_KEYS` shared-store propagation mechanism (gained two
new keys: `__gate_resolver__`, `__gate_prompt_allowed__`), `sanitize_parameters()` (a third
consumer added), the streamed-trace disk-only-line convention (`node.start` was the only
precedent; `gate` is the second).

**Now depended on by** (forward): Task 171 (durable/non-TTY gates) persists `GateRequest`/
`GateResolution` **unchanged** — do not casually restructure either dataclass without checking
that task's plan. Task 176 (web approval bridge) will add a third `resolved_via` value (`"ui"`)
and a tailer/SSE arm for the `gate` event kind (deliberately NOT built here — the event is
observe-only in v1). Task 164 (failure-resume) shares the same checkpoint/restore/continue
substrate conceptually but was not touched by this task.

**Contract/shape changes**: `WorkflowStatus` gained `DENIED` (additive `str` enum value — every
consumer verified to handle or safely degrade on it: CLI text/JSON, trace trailer via
`gate_outcome`, three separate web status-render surfaces). `PlanEntry` gained `approval: bool
= False`. New CLI flag `--auto-approve=<node-id>` (repeatable). New MCP `workflow_execute`
parameter `auto_approve`. New exit code `3` (denied; click still owns `2`).

## Tests That Matter

- `tests/test_runtime/test_gate_trace.py::test_denied_nested_gate_after_sibling_event_does_not_orphan_trace`
  + its non-interactive sibling — **mutation-verified**, reproduces the exact
  `orphan event: parent_id ... not found` `JSONDecodeError` when the host-frame recording fix
  is reverted. Run these whenever touching `WorkflowExecutor.exec`'s `_host_frame` handling or
  the engine's gate-exception arm.
- `tests/test_execution/test_plan_drift.py::test_plan_would_pause_matches_engine_gate_pauses` —
  the parity pin (plan-side gated-id set vs. real engine gate-pause events from a streamed run),
  covering standard/sub-workflow/loop shapes; separately
  `test_plan_batch_sub_workflow_preserves_child_approval_flag` for the batch-aggregation path
  specifically (the one that already dropped `approval` once — **mutation-verified**).
- `tests/test_execution/test_gate_prompt.py::test_flag_echo_suppressed_on_worker_thread_with_real_output_controller`
  — the ONLY test using the real `build_gate_resolver` with a real-shaped `OutputController` in
  a worker-thread configuration; the pre-existing parallel-batch test used a test-double
  resolver and could never have caught the echo race. **Mutation-verified.**
- `tests/test_runtime/test_approval_gate.py::test_secret_nested_in_dict_value_masked_in_diagnostic`
  + `test_gate_prompt.py`'s nested-secret tests — **mutation-verified**, guard the
  credential-disclosure surface specifically (not just "masking exists," but "masking recurses").
- `tests/test_runtime/test_approval_gate.py::TestRunnerBoundary` class — end-to-end through
  `WorkflowRunner().run()` (not just the engine), pins that `GateDenied` → `WorkflowStatus.DENIED`
  and `GateNotInteractiveError` → `FAILED` with intact payload diagnostics survive the full
  runner conversion, and that `__gate_resolver__` propagates into nested child engines.

---
*Distilled from the implementation context of Task 125. The chronological journey — plan-stage
verification, the 7-agent and 6-agent deep-review batteries, session-by-session deviations —
lives in `implementation/progress-log.md`.*
