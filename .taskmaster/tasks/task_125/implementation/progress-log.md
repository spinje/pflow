# Task 125 — Implementation Progress Log

> Companion to `implementation-plan.md` (same dir). Records decisions, deviations,
> and discoveries as they happen. Baseline before any change: 8283 tests passed,
> `make check` fully green (2026-07-02).

## 2026-07-02 — Session 1: plan + deep-review + Phases 1–2

### Plan-stage (before code)

- Spec verified by 4 parallel searchers; two spec corrections found (batch/loop combo
  rules live in `data_flow.py` not validator Step 9; Task 166 loop parity was NOT
  zero-plan.py-edits — rendering precedent is `_tag_from_entry`'s `cache: false` tag).
- Owner decisions locked: escalation IN scope (schema-retry self-heal de-risks the
  marker trigger); decisions 4 (fail at gate + warn at start) and 5 (clean denial,
  exit 3, DENIED status) confirmed as recommended.
- 7-agent deep-review (plan mode): 4 criticals, ~10 warnings, 0 disputed — ALL folded
  into the plan. Criticals: trace reader raises on unknown line kinds (gate needs a
  known-but-ignored arm); `WorkflowExecutor.exec` generic except converts gate
  exceptions into error-routable child failures; batch retry loop re-prompts/swallows
  denials (`retriable=False` fixes); blanket main-thread guard would break MCP
  auto-approve (MCP runs the engine via `asyncio.to_thread`).

### OWNER DIRECTIVE: implement Phases 1–2 ONLY, then stop for human review.

### Phases 1–2 implemented (this session)

New files:
- `src/pflow/core/gate.py` — `GateRequest`/`GateResolution` (payload IS the seam,
  ADR-0009), `build_approval_request`/`build_escalation_request`, `json_safe`.
- `src/pflow/runtime/engine/gate.py` — engine-side seam helpers: `resolve_gate`,
  `run_approval_gate`, `detect_escalation` (lenient-but-loud shape ladder),
  `run_escalation_gate` (decision written INTO the marker), `scan_batch_escalations`.
- `src/pflow/core/workflow/gate_validation.py` — `check_approval_allowed` (shared
  batch-host rule, two call sites: data_flow diagnostic + compiler CompilationError).

Modified:
- `core/exceptions.py` — `GateDenied`, `GateNotInteractiveError` (both
  `retriable=False`; payload-carrying `to_diagnostics()` with the surface-aware,
  ask-your-human remediation ladder; preview secrets masked via
  `mask_sensitive_value` in diagnostics only).
- `core/markdown_parser.py:1610` — `"approval"` added to the hoist tuple.
- `core/ir_schema.py` — `approval` enum property + `_get_suggestion` approval arm.
- `core/workflow/data_flow.py` — `_validate_approval_node_combos` wired into
  `validate_data_flow` (covers --validate-only, save, --dry-run, compile-path
  wrapped diagnostics, recursive child validation, MCP).
- `runtime/compilation/compiler.py` — `_extract_approval` (strict value + batch
  check, prewarm pattern) → `NodeConfig.approval` (`engine/types.py`).
- `runtime/engine/engine.py` — step 7.5 approval gate (before start callback /
  node.start → denied node never in trace); step 9 batch escalation scan; step 10.5
  escalation detect (clean-success, non-batch) gating BOTH cache writes; step 17.7
  escalation pause (after completion trace, before loop re-entry reads the store);
  gate-exception re-raise arm stamping `trace.gate_outcome`.
- `runtime/workflow_executor.py` — `__gate_resolver__` + `__gate_prompt_allowed__`
  in `_PROPAGATED_KEYS`; gate-exception re-raise arm before the generic child-failure
  conversion.
- `runtime/engine/batch_executor.py` — parallel workers get
  `item_shared["__gate_prompt_allowed__"] = False` (next to the progress-buffer swap).
- `runtime/workflow_trace.py` — `record_gate` (DISK-ONLY like node.start; never in
  `self.events`), `gate_outcome` field, `_determine_trace_status` gate arms
  (denied→"denied", non_interactive→"failed" — without this a gate-stopped run's
  trailer would read "success").
- `core/trace_io.py` — `gate` known-but-ignored reader arm (mirrors node.start).
- engine/runtime CLAUDE.md sections updated (seam steps, propagated keys).

Tests (+47, all green; full suite 8330 passed / 0 failed):
- `tests/test_core/test_approval_field.py` (13) — hoist, schema enum + suggestion,
  validator + compiler batch rejection, recursive child validation, NodeConfig,
  cache-hash unchanged.
- `tests/test_runtime/test_approval_gate.py` (29) — approve/deny/non-interactive,
  masked diagnostics, cached-never-gates, per-iteration loop prompts, escalation
  ladder (dict/decided/string/malformed/schema-softfail), never-cached escalations,
  batch scan with item context, gate-before-batch pattern, sub-workflow boundary
  (deny crosses unconverted, error_action:continue can't route it, sequential-batch
  deny with no retry re-prompt, parallel-batch stub + flag approval works).
- `tests/test_runtime/test_gate_trace.py` (5) — pause/resolution lines, payload
  round-trip, disk-only invariant, reader tolerance (`pflow report`/`--only` source
  works for approved runs), denied/failed trailers, escalation event ordering.

### Deviations from the reviewed plan (both simplifications, record for review)

1. **`GateRequest`/`GateResolution` live in `core/gate.py`, not `runtime/engine/gate.py`**
   — `core/exceptions.py` must carry the payload and core cannot import runtime.
   The engine-side helpers stay in `runtime/engine/gate.py` as planned.
2. **Parallel-worker isolation = `__gate_prompt_allowed__` flag + `allow_prompt`
   resolver arg, NOT resolver substitution** — substitution would need batch_executor
   (runtime) to build a Phase-3 resolver (execution layer): a layering violation.
   Same guarantees: auto-approve works in workers (flag lookup is thread-safe),
   `parallel_batch=True` is truthful (its only source is `allow_prompt=False`),
   no thread-identity heuristics (MCP's `asyncio.to_thread` unaffected).
3. **Guide topic hook (`_node_topics`) deferred to Phase 6** — the plan had it in
   Phase 1, but the hook would point at a not-yet-written `features/approval.md`.

### Known intermediate state (Phase 3 closes these — deliberate, not loose ends)

- `GateDenied` reaching the runner is converted by the GENERIC `_exception_to_result`
  → result FAILED / exit 1, while the trace trailer correctly says "denied". Phase 3
  adds the dedicated runner arms + `WorkflowStatus.DENIED` + exit 3 + denied JSON doc.
- No resolver is installed anywhere yet (CLI/MCP Phase 3) — every gated run today
  fails loudly at the gate with the payload-carrying error. Correct pre-Phase-3
  behavior (never hangs, never silently approves).
- Dry-run shows gated nodes as plain execute until Phase 5 (PlanEntry stamp + tag +
  drift pin).

### Final verification (session 1 close)

- `make test`: 8330 passed / 0 failed (baseline 8283 → +47, zero regressions).
- `make test-e2e`: 43 passed.
- `make check`: fully green (ruff, ruff-format, mypy 242 files, deptry, pre-commit hooks).
- Three C901 limits tripped by one-added-branch each; fixed by folding, not `noqa`:
  `_partition_trace_lines` merged the `node.start`/`gate` known-but-ignored arms;
  `WorkflowExecutor.exec` extracted the duplicated child-buffer stash into
  `_stash_child_buffer` (also removed pre-existing duplication); `_get_suggestion`
  extracted the validator-keyword fallback chain into `_suggest_for_general_error`.
- `GATE_KIND_*` constants typed as `Literal[...]` for mypy.
- CLAUDE.md updated where code changed: core (exceptions hierarchy + gate.py),
  core/workflow (gate_validation.py), runtime (reserved keys), runtime/engine
  (seam step diagram + gate except arm).

### Post-review audit (owner asked "fully happy? loose ends?")

- **Found + fixed one real leak**: engine bookkeeping keys in params (e.g.
  `_python_source_line` on code-block params) leaked into the approval preview.
  `build_approval_request` now filters `_`-prefixed keys (the display-surface
  convention). Pinned by a MUTATION-VERIFIED test (fails with the filter removed):
  `test_markdown_parsed_gate_preview_has_no_bookkeeping_keys`. Suite: 8331 passed.
- **Real-CLI end-to-end verification performed** (uv run pflow, no mocks):
  `--validate-only` accepts a gated workflow and rejects a batch-host gate with the
  restructure message; running a gated workflow non-interactively executes upstream,
  then fails AT the gate with the full ask-your-human ladder (exit 1 — becomes 3 only
  for DENIED in Phase 3); the streamed trace carries the gate pause line (resolved
  preview) + `non_interactive` resolution + `final_status: "failed"` trailer; and
  `pflow report` renders the gated trace (pre-fix this failed as unknown-kind
  corruption).
- Process incident, resolved with no data loss: a `git stash -- <untracked>` +
  `pop` mistake briefly applied a pre-existing stash (`commit3-wip`, other branch)
  into the tree; all 12 affected paths were disjoint from Task 125 work and were
  restored from HEAD; the stash list is intact (pop-on-conflict never drops).
  Lesson recorded: never mutation-verify via git stash on untracked files.

### Session 1 committed

- **Commit `2e533e2f`** on `feat/human-loop-approval-gates` (owner-instructed):
  phases 1–2 substrate + tests + plan/progress-log/handoff-braindump. 26 files,
  +2544/−37. Working tree clean after commit.
- Pre-commit caught two `Optional[str]` annotations (UP007) and one unused unpack
  (RUF059) in the new test file + reformatted two files — fixed, all hooks green
  on the committing run.
- Handoff artifacts for the next agent (all committed):
  `starting-context/braindump-2026-07-02-phase12-handoff.md` (read FIRST — carries
  the standing-order changes: NO fable for subagents; phased human-review cadence),
  then `implementation/implementation-plan.md`, then this log. The 48 tests are the
  substrate's behavior spec.
- Still uncommitted anywhere: nothing. Still unpushed: everything (no push
  instruction given).

### High-value test audit (owner: "the bar isn't passing, it's passing the right thing")

Stepped back and asked: where do the existing tests verify a CLAIM I made by reading
code rather than BEHAVIOR I proved? Four gaps found, four tests added (+4, suite 8335):

1. `test_escalation_decision_feeds_loop_carry_reentry` — the escalate → decide →
   carry re-entry round trip (the continue mechanism, i.e. the reason escalation
   exists) had NEVER been executed; the decision-before-loop-eval and
   decision-before-carry-resolution orderings were line-number reasoning until now.
2. `test_parallel_batch_child_gate_with_live_collector_never_crashes` — the traceless
   parallel test could not see the worker-thread `record_gate` path; if a parallel
   child ever got the run collector instead of a buffer, `_assert_owner_thread` would
   CRASH production runs. Now pinned with a real streaming collector.
3. `test_nested_child_gate_events_land_in_run_stream` — the plan's pending Phase 4
   item: child gates (the harness's primary shape) share the run collector, gate
   lines land in the stream, trace stays readable.
4. `test_noninteractive_gate_through_runner_keeps_payload_diagnostics` — first test
   through `WorkflowRunner` (tests/CLAUDE.md pitfall #20): the gate diagnostic
   survives runner conversion with its payload, is JSON-serializable, and the run
   fails as a RESULT not a propagated exception. Explicitly documents that Phase 3
   must consciously update the denied half of this contract.

Shallowness audit verdict: no existing test asserts the wrong thing; none removed.
The one under-asserting test (traceless parallel gate) is kept for its resolver-level
pins and superseded on the trace dimension by #2.

### Behavioral note discovered while implementing

Escalation detection requires a CLEAN-SUCCESS action (`""`/`"default"`/`"end"`/None),
mirroring the api-warning detector's "the node's verdict stands" rule — so a `code`
node using dynamic `next:` routing cannot escalate from the same execution (its action
is the route target). The escalating step should be the agent step (action "default"),
with routing decided downstream. Document in the guide (Phase 6); add to the plan's
edge ledger if the owner wants it surfaced earlier.
