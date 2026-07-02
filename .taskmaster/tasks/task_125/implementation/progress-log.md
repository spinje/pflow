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

## 2026-07-02 — Session 2: Phases 3–4 (OWNER DIRECTIVE: implement 3+4, then STOP for human review)

Baseline re-captured at session start: 8335 passed (matches session-1 close), check green.

### Phase 4 gap check — already complete, nothing added

Every Phase 4 bullet verified shipped by session 1: `record_gate` (disk-only, gate_outcome
trailer channel, `workflow_trace.py:650`), `trace_io._partition_trace_lines` gate arm,
pause-before-prompt / resolution-before-raise ordering (in `runtime/engine/gate.py`),
`resolved_via` on resolutions, round-trip + child-stream + trailer pins (test_gate_trace.py
+ commit 301a002c). Phase 4 required zero session-2 code.

### Phase 3 implemented

New file:
- `src/pflow/execution/gate_prompt.py` — `build_gate_resolver` (ONE builder, every surface:
  CLI interactive / MCP `output_controller=None` / parallel-batch via `allow_prompt=False`),
  `can_prompt` (stdin+stderr TTY, NOT `is_interactive()` — Decision 14, verified live:
  JSON mode with stdout piped still prompts), TTY renderers (aligned masked truncated
  preview; escalation numbered options + `(rec)` + free text), click `Abort` →
  `KeyboardInterrupt` (the engine-archives-Abort-as-node-failure trap).

Modified:
- `core/workflow/status.py` — `WorkflowStatus.DENIED = "denied"`.
- `execution/runner.py` — `run(gate_resolver=...)` kwarg mirroring `progress_callback`
  end-to-end (→ `_initialize_shared_store` → `shared["__gate_resolver__"]`);
  `_exception_to_result` derives DENIED from `isinstance(exception, GateDenied)`.
- `core/output_controller.py` — `prepare_for_prompt()` public seam (closes the partial
  line; batch `\r` counters ride the same physical line, so no extra state).
- `cli/commands/run.py` — `--auto-approve` (multiple, in `_PFLOW_FLAGS`);
  `_prepare_gate_resolver` (builds resolver + two pre-flight warnings: unknown flag id
  with fuzzy suggestion via `find_similar_items`, non-interactive-with-unapproved-gates;
  both scan TOP-LEVEL ir_data nodes only — documented limitation — and are `-p`-suppressed);
  `_display_execution_result` DENIED first-branch → `_display_denied_result` (text prose
  with steps-completed count, or JSON document `{success:false, status:"denied", error,
  gate:{...masked payload}}` — the denied branch bypasses `output_error`, so JSON mode
  needed its own emitter) → `ctx.exit(3)`.
- `cli/workflow_output.py` — `denied` arm in `_format_workflow_completion_status`
  (the ✓-fallthrough silent-misbehavior site).
- `mcp_server/tools/execution_tools.py` + `services/execution_service.py` —
  `auto_approve` param on `workflow_execute` → `build_gate_resolver(frozenset(...), None)`
  → `runner.run(gate_resolver=...)`; docstring tells agents to ask their human.
- Web: `RunProgress.tsx` `runBadgeStatus` denied arm (amber "stopped" badge, never green ✓);
  `index.css` `.run-banner.run-denied` + `.run-progress-outcome.run-denied` (amber family).
  GraphView banner + outcome-line classes are template-derived (`run-${final_status}`) —
  no TSX change needed there, CSS only.
- CLAUDE.md updates: cli (exit-code contract + flags list), execution (gate_prompt.py entry).

### Deviations from the reviewed plan (all simplifications, record for review)

1. **No `RunnerConfig.auto_approve` field.** The resolver travels as a `run()` kwarg
   (mirroring `progress_callback` exactly — the plan's own installation section); CLI and
   MCP each build their own resolver, and the CLI's pre-flight warnings scan `ir_data`
   CLI-side. RunnerConfig stays execution-only config; nothing needed the tuple.
2. **No dedicated runner `except GateDenied/GateNotInteractiveError` arms.** The generic
   `_exception_to_result` already preserves payload diagnostics via `to_diagnostics()`
   (pinned in session 1); DENIED is a one-line status derivation inside it.
   `GateNotInteractiveError` needed zero runner changes.
3. **`prepare_for_prompt` closes only the partial line** — the plan's separate
   batch-`\r`-counter concern is moot: batch progress rewrites the SAME physical line
   opened by `node_start` (`_partial_line_open` stays true until completion).

### Verification (session 2 close)

- `make test`: **8362 passed / 0 failed** (session-1 close 8335 → +27, zero regressions).
- `make test-e2e`: 43 passed. `make check`: fully green (fresh run post-format; mypy 243 files).
- Web: `tsc --noEmit` clean; `npx vitest run` 693 passed.
- **Live CLI verification (real pty via `script`, no mocks):** deny → exit 3 + amber
  "stopped cleanly" line + steps-completed count; approve → exit 0, step runs; JSON deny →
  the denied document with resolved preview; `--auto-approve=guarded-step` → exit 0 with
  the visible "pre-approved" stderr line; typo'd id → fuzzy "Did you mean" warning;
  non-interactive → run-start warning then loud fail at gate (exit 1) with the
  ask-your-human ladder; resolved preview shows the actual substituted command.
- New tests (+27): `tests/test_execution/test_gate_prompt.py` (15 — resolver contract,
  Decision-14 TTY rule, Abort→KI, masking/truncation/options rendering);
  `tests/test_cli/test_approval_gate_cli.py` (8 — exit 3, JSON document, auto-approve,
  fuzzy warning, non-interactive warn+fail, `-p` suppression, completion-status arm);
  `tests/test_runtime/test_approval_gate.py` (+2 — runner DENIED contract, resolver
  reaches nested child engines); `tests/test_integration/test_cli_mcp_parity.py` (+2 —
  MCP loud-fail with remediation ladder, `auto_approve` off-main-thread via
  `asyncio.to_thread`, pinning the no-thread-guard design).

### Open at the review boundary (all CLOSED later this session — see Phases 5–7 below)

- Web denied-state screenshot → taken (Phases 5–7 section).
- Phases 5–6 + remaining pins → implemented (below).
- Accepted cosmetics carried forward (prompt_cache_analysis denied-trace labels;
  run-start warning is top-level-only).

## 2026-07-02 — Session 2 (continued): Phases 5–7 + loose-ends audit (owner: "continue, fully happy, then /deep-review → fix → /create-pr")

### Phase 5 — dry-run parity

- `PlanEntry.approval: bool = False` (`execution/result.py`).
- **`_annotate_loop_entry` renamed `_annotate_entry`** (the plan's own instruction — the
  name stays honest) and stamps `approval` from NodeConfig BEFORE the loop early-return.
  All three call sites updated; `execution/CLAUDE.md` gained a "Cross-cutting entry
  stamps" section.
- Render: `_tag_from_entry` appends `approval` (→ `[shell, approval]`); explicit
  `, approval` suffix on the sub-workflow and opaque lines (they bypass the tag helper);
  `_entry_to_dict` emits sparse `"approval": true`; new `_append_gate_footer` (extracted
  to keep `format_plan_text` under C901 — fold, not noqa) renders
  `⏸ N step(s) pause for approval … non-interactive runs need --auto-approve=…`,
  collecting gated ids RECURSIVELY through nested sub_plans (first-seen dedup).
- **Drift pin** `test_plan_would_pause_matches_engine_gate_pauses`
  (tests/test_execution/test_plan_drift.py): plan-side flattened gated-id set ⟺ engine
  gate PAUSE events from a real streamed run, across all allowed shapes (standard node,
  gated workflow-type node, gate INSIDE the child, gated loop node). Compared by node-id
  SET; an explicit count assert proves the loop node pauses per iteration (2) while being
  one entry. **Mutation-verified BOTH sides** (plan-side stamp disabled → fail; engine-side
  pause event suppressed → fail; reverted, green). Plus
  `test_dry_run_renders_approval_tag_and_footer` (text tag, sub-workflow tag, footer, JSON).
- **Bug found by the pin: `tests/shared/markdown_utils.ir_to_markdown` silently DROPPED
  the `approval` field** — a gated fixture written through it tested nothing. Fixed
  (emits `- approval: <value>` beside `cache`); this is the shared utility 30+ test files
  use, so future gated fixtures can't silently de-gate.

### Phase 6 — docs

- `src/pflow/guide/features/approval.md` (new): both gate kinds, declaration rules,
  the agent-operator playbook (dry-run discovery → ask your human → scoped
  `--auto-approve`), the escalation `result.escalation` contract (`output_schema`
  REQUIRED on claude-code escalators; string-marker form; decision write-back +
  idempotency), the loop+carry re-fork recipe, calibration guidance, batch restrictions,
  clean-success-action rule, observability (resolved_via audit, exit 3, denied trace).
- Topic wiring per guide/CLAUDE.md's checklist: `_node_topics` hook (+
  `test_detect_approval_gate`), `entry.md` features row, `approval` in
  `RESERVED_WORKFLOW_NAMES` (save_service.py), `guide/core.md` node-fields line.
- `docs/how-it-works/approval-gates.mdx` (+ `docs.json` nav), `--auto-approve` row in
  `docs/reference/cli/index.mdx`.
- `d1-event-schema.md`: reserved `gate` kind marked SHIPPED with the disk-only pointer.
- Root `CLAUDE.md`: Task 125 → Recently Completed; removed from Next.

### Phase 7 / loose ends closed

- **Web denied-state verified visually** (screenshot-pflow-web-ui, headless Chrome, real
  denied trace `final_status: "denied"` + 2 gate lines): amber "Run denied · 1 nodes"
  banner, amber outcome + stopped-badge in the run callout, gated step shows *pending*
  (never failed), zero green ✓. Screenshot at scratchpad
  `gated-db73b1c8-…-t125-….png`.
- Frontend pin added: `RunProgress.test.tsx` denied arm (amber badge + `run-denied` class,
  never the success fallthrough).
- Live CLI: dry-run text shows `[shell, approval]` + the ⏸ footer; JSON carries
  `"approval": true` (verified against a real workflow).

### Final verification (Phases 5–7 close)

- `make test`: **8365 passed** (session-2 midpoint 8362 → +3: drift pin, render test,
  guide detection; net +30 over session-1 close). `make test-e2e`: 43. `make check`:
  fully green (fresh run). Web: `tsc --noEmit` clean, **694 vitest passed** (+1).
- One C901 trip (`format_plan_text` 11>10) fixed by folding the footer into
  `_append_gate_footer` — the braindump's predicted boundary, handled per house rule.
- Still uncommitted: everything from session 2. Next: /deep-review → fix verified
  findings → update this log → /create-pr (owner instruction).

### Deep-review (Phases 3–7 diff, 6 agents) — 6 confirmed findings, all fixed

Battery: silent-failures + impact-completeness (the owner-mandated pairing) +
feature-interactions + agent-ux + test-fidelity + simplicity. Zero criticals; zero
disputed. Fixes (each pinned by a test unless noted):

1. **Denied JSON ≠ unified failure shape** (agent-ux) → `_display_denied_result` now
   emits `errors` + `diagnostics` arrays (superset of `format_error_json`'s contract)
   alongside `gate`.
2. **Unmatched `--auto-approve` id phrased as a typo verdict** (agent-ux) —
   contradicted the dry-run footer for legitimate nested-gate ids (flat namespace).
   Reworded to a neutral note: nested-match possibility first, closest top-level
   match second. Test + cli/CLAUDE.md updated.
3. **Cached-but-gated entries stamped `approval: true`** (silent-failures) — plan
   promised a pause a cache hit never makes. `_annotate_entry` skips `cached`
   entries; new two-sided pin `test_cached_gated_node_not_stamped_and_engine_skips_gate`.
4. **`runMark` denied fallthrough** (impact-completeness) — the third web status
   surface (RunSelector + CatalogView) rendered denied as grey "stale". Amber
   `run-denied` arm + CSS; stale status-enum comments refreshed.
5. **Non-interactive `--only` warned about unreachable gates** (feature-interactions)
   — gate scan now scopes to the `--only` target (+ None-id guard); new test.
6. **Gate events inside batch-item sub-workflows don't reach the trace**
   (feature-interactions) — CONFIRMED, DIFFERENT FIX: buffered child events must not
   carry gate lines (that recreates the --only-seeding hazard the disk-only invariant
   prevents), and Task 171 reworks gate records; documented as a v1 audit limitation
   in guide/features/approval.md ("gate outside the batch if you need the record").
   Flag for Task 171: batch-item gate records.

Suggestion applied: denied-JSON preview assertion tightened to the exact resolved
value (test-fidelity). Deliberately NOT acted on: `GateResolution.notes` (forward-shape
for 171/176), masking rule in two render surfaces (different media) — both simplicity
take-or-leave notes.

Post-fix gates: `make test` **8367** (+2 pins) / e2e 43 / `make check` green /
web tsc + **694** vitest green.

## 2026-07-02 — Session 3: GitHub PR review evaluation + fixes (`/evaluate-review`)

Two real reviews on PR #554: a `claude[bot]` comment (1 Warning + 2 Suggestions,
seam-focused: concurrency, cross-boundary control flow, validation↔runtime parity)
and a Codex inline review (4 findings across 4 files). Evaluated with 4 parallel
`pflow-codebase-searcher` verification agents + direct reads of the two most
consequential fix sites (engine.py gate-exception handler, workflow_trace.py
`descend()`/`tree()`) before proposing a plan. **5 confirmed, 1 disputed, 0
needs-investigation** — user approved the full plan; all 5 implemented and
mutation-verified (temporary Edit + revert per fix, never git stash).

### 1. Orphaned trace event on a nested gate stop — CONFIRMED, different fix (most severe)

Real bug, but the reviewer's mechanism was subtly off. Root cause: `WorkflowExecutor.
descend()` reserves a seq for a sub-workflow host; children record with `parent_id` =
that seq; the host's OWN completion event is normally written at engine step 16
(`record_trace`, reusing `node._host_frame` — read only AFTER `node._run()` returns).
But the Task 125 gate-exception arm `raise`s instead of returning (by design — a
denial can't be error-routed), so step 16 never runs and the reserved seq gets no
event. If an earlier SIBLING step inside that sub-workflow already recorded, its
event orphans. **Actual impact (verified live, not the reviewer's framing): NOT a
later disk-read crash** — `finalize()` itself calls `tree()` in-memory and raises
*before* writing the `run.complete` trailer; `runner.py`'s `contextlib.suppress`
silently swallows it, so the run exits with the right code but **the trace file is
silently lost** (one easy-to-miss log line). Also a **latent hard-crash surface**:
`error_formatter.py:85-88`'s `collect_llm_calls()` → `tree()` raises outright for
any caller threading `metrics_collector` + `shared_storage` together.

Fix (`runtime/engine/engine.py`, the `except (GateDenied, GateNotInteractiveError)`
handler): `host_frame = getattr(node, "_host_frame", None)`; if set, call
`record_trace(..., success=True, frame=host_frame)` before re-raising — the *node*
itself didn't error, the run's denied/failed verdict is already carried
independently by `gate_outcome`. Fires once per nesting level for free (the same
exception re-raises through each ancestor's own `_execute_node`, each checking its
own node's `_host_frame`) — no `workflow_executor.py` change needed.

Tests (`tests/test_runtime/test_gate_trace.py`, both mutation-verified — reverting
the fix reproduces the exact `orphan event: parent_id ... not found`
`JSONDecodeError`): `test_denied_nested_gate_after_sibling_event_does_not_orphan_trace`,
`test_noninteractive_nested_gate_after_sibling_event_does_not_orphan_trace` — a
sub-workflow with an earlier sibling step then a gated step; assert `run.complete`
IS written, `final_status` is `denied`/`failed` (not silently `incomplete`), and
`tree()` rebuilds without raising.

### 2. Gate preview masking doesn't recurse into dict/list values — CONFIRMED

`claude[bot]` (Suggestion) and Codex (P1) independently flagged the same gap:
`gate_prompt.py::_format_preview` and `exceptions.py::_masked_gate_payload` both
masked only `isinstance(value, str)` — a nested secret (`headers: {Authorization:
"Bearer ..."}`) rendered/serialized verbatim, reaching the TTY prompt AND
`GateNotInteractiveError.to_diagnostics()` (→ `--output-format json` / MCP tool
responses). Fix: reuse the existing recursive `sanitize_parameters()`
(`core/security_utils.py`) for non-string preview values in both sites — top-level
string masking (`mask_sensitive_value`) unchanged, so the existing 200-char preview
truncation behavior isn't disturbed. Tests (both mutation-verified): nested-dict and
nested-list-of-dicts cases in `test_gate_prompt.py`
(`test_nested_secret_in_dict_value_is_redacted`,
`test_nested_secret_in_list_of_dicts_is_redacted`) and
`test_approval_gate.py::test_secret_nested_in_dict_value_masked_in_diagnostic`
(diagnostic masked, in-memory `request.preview` stays unmasked — trace-consistent).

### 3. Auto-approve echo races a parallel-batch worker thread — CONFIRMED

`claude[bot]` (Warning). `_echo_auto_approved` fired unconditionally on `auto_approve`
match, ignoring `allow_prompt` — but `__gate_resolver__` propagates into worker
`item_shared` UNCHANGED (only `__gate_prompt_allowed__`/the progress callback are
swapped/buffered), so a flagged nested gate inside a parallel-batch sub-workflow item
called `output_controller.prepare_for_prompt()` + `click.echo(err=True)` on the
WORKER thread — exactly the race the per-worker progress buffer exists to prevent.
The existing parallel-batch test used a `RecordingResolver` test double with no
`OutputController`, so this was genuinely uncovered. Fix: gate the echo on
`allow_prompt` in the resolver closure (worker output is buffered anyway; the flag
was already an explicit human pre-approval). Tests (mutation-verified):
`test_flag_echo_suppressed_on_worker_thread_with_real_output_controller` (real
`build_gate_resolver` + fake-but-real-shaped `OutputController`, `allow_prompt=False`
→ zero `prepare_for_prompt()` calls, zero stderr) +
`test_flag_echo_still_fires_on_main_thread` (positive case).

### 4. Batch-of-sub-workflow dry-run drops the child's `approval` flag — CONFIRMED

Codex (P2). `_aggregate_batch_child_plans` (`execution/plan.py`) builds fresh
synthetic `PlanEntry` objects per node-id when collapsing per-item batch-of-workflow
plans — `approval` wasn't in the copied-fields list, silently defaulting to `False`
even though the child gates correctly at runtime (resolver namespace is flat).
Fix: `approval=any(entry.approval for entry in entries_for_node)`. Test
(mutation-verified): `test_plan_batch_sub_workflow_preserves_child_approval_flag`
in `test_plan_drift.py` — batch-of-workflow whose child has a gated step; assert the
aggregated entry shows `approval=True`.

### 5. `sorted()` on a set that could contain `None` — CONFIRMED (unreachable today, cheap fix)

`claude[bot]` (Suggestion). `_prepare_gate_resolver`'s `node_ids` set could contain
`None` if a node dict lacked `"id"`, crashing `sorted()` with a mixed-type
`TypeError`. Verified unreachable in practice (the markdown parser always sets
`"id"`; no CLI path passes a bare dict IR that skips it) but the guard costs
nothing. Fix: filter falsy ids at construction. Test (mutation-verified,
reproduces the exact `TypeError`):
`test_prepare_gate_resolver_tolerates_node_missing_id`.

### Disputed

**Docs example flag placement** (Codex P2) — claimed `pflow my-workflow
--auto-approve=notify-slack` wouldn't work (flag after the workflow name). Verified
empirically wrong: `run`'s `allow_interspersed_args=True` + `--auto-approve` being a
*recognized* Click option means position doesn't matter (tested all 4 orderings by
parsing the real command). No doc change.

### Post-fix verification

`make test`: **8376 passed** (session-2 close 8367 → +9: 2 orphan-trace tests, 2
nested-secret masking tests (gate_prompt) + 1 (exceptions/approval_gate), 2
worker-echo tests, 1 batch-approval-plan test, 1 sorted-None test). `make test-e2e`:
43. `make check`: fully green (one RUF012 lint on the new test's fake-ctx class,
fixed by switching to `types.SimpleNamespace`). Web: `tsc --noEmit` clean, 694
vitest passed (untouched by this session — web wasn't in scope for any confirmed
finding). All 5 fixes mutation-verified via temporary Edit + revert (never git
stash, per the session-1 lesson).

Next: update this log (done) → `/create-pr` follow-up (push + note on the existing
PR #554, since it already exists — no new PR).

## 2026-07-02 — Session 4: post-implementation verification sweep + fixes

Owner asked for an independent plan-vs-code verification of the whole task
(6 parallel searcher agents + direct confirmation of the consequential claims).
Verdict: all 7 phases, all 14 locked decisions, and all recorded deviations
check out against the code; the four criticals from the plan review all landed.
The sweep surfaced 6 new findings (none critical); owner said fix all — all
fixed this session:

1. **Batch-escalation error named the wrong item number** (real bug, message-only):
   `scan_batch_escalations` indexed the success-filtered `results` list, so with
   an earlier failed item the escalating item's reported position was off.
   Fixed by reconstructing original indices from the authoritative `errors[].index`
   set. Test (mutation-verified — old `i+1` math fails it):
   `test_batch_escalation_reports_original_item_index_when_earlier_item_failed`.
2. **Unexpected resolver exception corrupted the node record** (design smell →
   hardened): a resolver bug at the post-exec escalation seam fell to the
   generic except arm — duplicate error trace event + a genuinely successful
   node archived into `__failures__`. The wrong-return-type case raised a plain
   `PflowError` with the same conversion hazard. New `GateResolverError`
   (`retriable=False`, carries the request, payload-masked diagnostics) raised
   by `resolve_gate` for both cases; added to BOTH boundary re-raise tuples
   (engine gate arm — which also gives it the host-frame orphan fix + the
   `gate_outcome="failed"` stamp — and `WorkflowExecutor.exec`); gate seams emit
   a `resolution: "error"` gate line before it escapes; `record_gate` maps
   `"error"` → trailer `"failed"`. Tests (mutation-verified — removing the
   exception from the engine tuple fails both): `TestGateResolverFailure` (node
   success record stands, no `__failures__` entry) +
   `test_resolver_crash_emits_error_resolution_and_trailer_says_failed`.
3. **Escalation cost trap undocumented**: non-interactive escalation aborts
   AFTER the step ran and the escalating result is (correctly — Decision 10)
   never cached, so a re-run re-pays the whole agent step. Verified Decision 10
   is the right side of the tradeoff (a cached escalation would replay as
   resolved-without-a-decision because the cache-hit early-return precedes the
   detect seam); the gap was documentation only. `guide/features/approval.md`
   now states the discarded-work cost explicitly.
4. **Latent denied→✓ fallthrough in `format_success_as_text`** (unreachable
   today): defensive `denied` arm added + pin
   (`TestDeniedStatusRendering`) so a future routing change can't render a
   denied run as success.
5. **Missing end-to-end Ctrl-C-at-gate pin**: added
   `test_ctrl_c_at_gate_prompt_exits_130_and_step_never_runs` (CliRunner,
   Abort at the prompt → exit 130, step never runs) — pins the resolver→engine→
   runner→CLI interrupt seam whose halves were only unit-tested.
6. **Stale docs**: `core/workflow/CLAUDE.md` + `core/CLAUDE.md` still called
   `WorkflowStatus` tri-state (now four states incl. DENIED); `guide/CLAUDE.md`
   features inventory was missing `approval.md`/`ui.md`; task-review invariant
   updated for the third gate exception. CLAUDE.md exception tree + engine seam
   diagram updated for `GateResolverError`.

Also verified and left as-is: worker gate-line drop (documented v1 audit
limitation), `__gate_prompt_allowed__` cannot leak to the parent store,
nested denial trailers, warning/resolver `can_prompt` consistency (same
function by construction), no double-prompt under node retries.

Process note: repeated the session-1 git lesson the hard way — a
`git checkout -- <file>` used to revert a mutation also wiped the session's
uncommitted edits to that file (re-applied immediately; later mutations used
temporary Edit + revert as the log already prescribes).

## 2026-07-02 — Session 4 (continued): PR-review warning fix — gate-preview masking rework

Evaluated claude[bot]'s review of 9fe66c96 (PR #554): no blockers, 1 Warning,
2 optional suggestions. Actions:

- **Warning CONFIRMED and fixed** (the earlier "accepted as-is" call was made on
  a wrong premise): `sanitize_parameters` cuts nested strings >100 chars to
  **20 chars** (`value[:20] + "...<truncated>"`, security_utils.py:138-139) —
  the task-review had recorded it as "truncates to 100 chars". A gated http
  `json:` body or sub-workflow `inputs:` field showed the approver 20 chars, on
  BOTH decision surfaces (TTY prompt + MCP/JSON diagnostic). Fix: new shared
  `core/gate.py::masked_preview` — recursive redaction of secret-NAMED keys via
  `is_sensitive_parameter`, NO truncation (truncation stays renderer-only: the
  TTY 200-char step; diagnostics carry full masked values, per the plan's
  untruncated-payload rule). Both render sites now delegate — this also closes
  the task-review's "two hand-written masking call sites" wart. Tests
  (mutation-verified against the old sanitize path):
  `test_long_nonsecret_nested_value_survives_to_display_budget` (gate_prompt) +
  `test_long_nonsecret_nested_value_intact_in_diagnostic` (approval_gate).
  Behavior delta accepted knowingly: nested non-secret values are no longer
  length-limited in diagnostics (the trace already carried them in full).
- **Suggestion 1 (batch-host edge note)**: added the one-line comment in the
  engine gate-arm (batch hosts never set `_host_frame` — batch-item children
  use buffered collectors, no `descend()`). No new test — the guard is
  defensive and the path is exercised by existing sequential-batch deny pins.
- **Suggestion 2 (comment density)**: reviewer requested no change; none made.
- **Task-review accuracy pass** (owner request): commit list extended
  (5f161e4e + this fix); the two stale masking paragraphs replaced with the
  masked_preview invariant + its history; added GateResolverError and the
  non-interactive-escalation cost trap to Gotchas (flagged for Task 171
  designers); "allowlist extended to reject denied" corrected (the allowlist
  naturally excludes it — no code change existed); integration point corrected
  from `sanitize_parameters` to `is_sensitive_parameter`; engine handler tuple
  and Read First list updated for GateResolverError/masked_preview.
