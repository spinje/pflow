# Task 176 Review: Web-UI Approval Bridge

## Metadata
Implemented 2026-07-11/12 on `feat/web-ui-approval-bridge`. Server half committed (`b9a47ac7`
feature + `0bc6bf1c` checkpoint fixes); frontend half + docs in the branch's later commits. Not
merged at time of writing. Journey: `implementation/progress-log.md` (two sessions + two
deep-review passes). Verified end-to-end in a real browser with real producers, including one
live human approval.

## Read First — the load-bearing block

**What exists now:** the browser answers what 125/171 could only show — a paused gate gets a
kind-switched answer panel at the ⏸ node (Approve/Deny, or escalation options + free text), a
failed/interrupted pinned run gets a Resume button, both delivered by spawning `pflow resume`
via `POST /api/resume` after an in-process pre-flight. Plus the ⏸ frontier badge and un-run
greying on terminal replays.

**Read these first:**
- `src/pflow/ui/CLAUDE.md` — the HTTP contracts (`GET /api/gate`, `POST /api/resume`, refusal
  vocabulary). The frontend codes against THIS, not against server internals.
- `src/pflow/execution/resume_preflight.py::preflight_resume` — the CLI's exact click-free
  refusal gates; CLI (`cli/commands/resume.py`, now a thin shell) and the server are its two
  consumers.
- `src/pflow/ui/server.py::resume` + `_resume_refusal_response` + `_spawn_detached_cli`.
- `web/src/components/resumeAnswer.tsx::useResumeAnswer` — the ONE frontend refusal machine
  (GateCallout + ResumeControl are content-only on top of it).
- `web/src/views/GraphView.tsx` — `pausedEntry` (badge synthesis), the gate-panel wiring
  (`gateDismissed`, `gateAnchorId`), and `web/src/graph/focus.ts::applyReplayDim`.

**Invariants that must NOT break:**
- **Pre-flight before spawn, always.** The spawn is detached + DEVNULL; a refusal after spawn is
  invisible. Every `ResumeSourceError` subclass MUST have a `refusal` literal
  (`_RESUME_REFUSALS`) — the completeness-net test fails loudly if you add one without.
- **`--force` is user-ack-only.** The server never adds it; the client sends it only from the
  "Resume anyway" ack. Breaking this silently re-fires side effects / resumes against an edited
  workflow.
- **`gate_request` never rides the light wires** (`_RUN_COMPLETE_FIELDS`, `/api/runs`) — only
  the small `paused_node_id` string. The payload is on-demand (`/api/gate`) and ALWAYS through
  `masked_gate_dict` — skipping it leaks real secrets (the on-disk trailer is unmasked).
- **`paused` never arrives as a per-node RunEvent.** `events.ts` `RUN_STATUSES` stays untouched;
  the badge is synthesized from the banner in BOTH `runComplete` and `runSnapshot`. The join ref
  is always `{node_id, [], null}` (171 producer conjuncts guarantee top-level).
- **Escalation answers send the option LABEL, never the number** (`option_labels` falsy-fallback
  mirrored in `GateCallout.optionLabel`). Numbers are a terminal-only convenience.
- **Trailer keys are FLAT, never `META_KEYS`**, and every reader change must survive the
  oversized (>64KB) full-re-read branch — a paused trailer carries the whole gate payload.
- **`preflight_resume`'s gate ORDER mirrors the CLI** (load → hash → between-nodes entry →
  side-effect verdict) and deliberately does NOT inject settings env vars or compile — the
  server wrapper compiles (the child-exact compile), the CLI compiles in-process later.

## What Was Built (actual vs. planned)

Ledger decisions held: ONE `POST /api/resume` (not approve+trigger), gate panel as a
`NodeCallout` at the ⏸ node (not a side panel), `resolved_via:"ui"` OUT. The spec's "one CLI
change" evaporated — `PFLOW_EXECUTION_ID` already worked on the resume path; the deliverable
became a pin test. Post-plan deviations that stuck (each review-driven, reasons in the log):
the paused banner's outcome badge uses the new ⏸ arm instead of the plan-era "stopped" square;
the two panels' refusal handling folded into `resumeAnswer.tsx` and now renders each
diagnostic's `suggestions`; `gateDismissed` re-arms on `run-reset` (follow-newest would
otherwise mute every later gate after one dismissal); `parseErrorBody`/`resumeRun` surface the
singular `{"error": …}` house shape. `ruff` C901 forced the resume handler into
`_parse_resume_body` / `_resume_cli_args` / `_resume_refusal_response`.

## Patterns & Anti-Patterns

**Patterns to propagate:**
- **Extract on the second consumer, verbatim.** `resume_preflight.py`, `_spawn_detached_cli`,
  and `resumeAnswer.tsx` all appeared exactly when their second consumer did — never before.
- **Client-synthesized `NodeStatus`** (third of its kind after `stopped`/`unrecorded`): derive
  per-node state from run-level facts in the SSE handlers, never widen the per-node event
  vocabulary.
- **Pure restyle pass** (third of its kind): `applyReplayDim` mirrors `applyStatus` — identity-
  stable (unchanged objects keep identity for memo), idempotent, inactive = pass-through.
- **Machine-readable refusals, never string-parsing**: 4xx bodies carry a `refusal` literal +
  kind extras on `ApiError.body`; panels switch on it.
- **Single-read rule**: one `response.json()` derives both `errors` and `body` — a second read
  throws and silently collapses every refusal to the generic arm (test-pinned).
- **Server tests on REAL producer traces** (pause runs through the actual CLI with the
  `trace_files` marker); synthetic `_write_paused_trace` only for shapes the producer can't emit.

**Anti-patterns (tried/considered and rejected — don't re-derive):**
- Consolidating the twin trailer readers across the `runtime/` ↔ `ui/` boundary (layering rule;
  they stay duplicated on purpose).
- Compiling inside `preflight_resume` (the CLI would pay the compile twice).
- A client-side "already answered" pre-check (inverse `resumed_from` scan) — the POST's
  superseded 409 is authoritative.
- A third gate-panel entry point; a `"ui"` `resolved_via` marker (spoofable, no consumer).

## Gotchas & Non-Obvious Coupling

- **A `code` node's escalation cannot pause durably** (`_gate_pausable` excludes dynamic
  routers) — it hard-errors exit 1, which LOOKS like a bridge bug. Any escalation demo/test
  workflow must use a `claude-code` step (`output_schema` requires `max_turns >= 2`).
- **Two node_type vocabularies, both correct**: `GateRequest.node_type` is the Python class name
  (`ShellNode` — TTY-prompt parity); the side-effect refusal's `node_type` is the registry name
  (`shell` — what `is_side_effecting` speaks). Don't "unify" without an owner decision.
- **The `edgesUnchanged` setEdges-skip in `useWorkflowGraph` eats edge restyles**: it keys on
  `(laid, focus, paintedDimRef)`. Any NEW pass that writes edge classes must join that conjunct
  or its styling silently never paints on a status-only tick (this exact bug was caught at
  build time for `applyReplayDim`).
- **`pflow ui`'s reuse-if-up probe serves the OLD bundle** — kill the server AND `make ui-build`
  before any browser verification (burned two tasks now).
- **Mutation-testing files with uncommitted fixes**: snapshot to scratchpad and restore —
  `git checkout --` reverts your fixes with the mutation (burned once, recorded in the log).
- A **non-uuid unknown resume target** maps to the 400 arm WITHOUT a `refusal` literal
  (`WorkflowNotFoundError` is not a `ResumeSourceError`) — the frontend's fallback arm covers it.
- **`/api/run`'s pre-flight requires a declared input even when it has a default** (unless
  `required: false`) — the RunPanel form prefills so browsers never see it; bare curl must pass
  it.
- The gate callout and run callout **stack at the same anchor** when a no-input workflow's FIRST
  step is the gate (gate renders after → on top; dismissing reveals the run box). Accepted, same
  as the say-bubble precedent.
- Re-clicking an **already-selected** ⏸ node doesn't reopen a dismissed panel (selection didn't
  change); click elsewhere then back.

## Integration Points

- `ui/ → execution/` gained the `resume_preflight` edge (sanctioned direction; `runtime/ ↛ ui/`
  stays pinned by `test_import_hygiene`). `cli/commands/resume.py` is now a click shell — the
  refusal POLICY lives in `execution/resume_preflight.py`; edit it there for both consumers.
- `core/exceptions.py::ResumeStaleWorkflowError` now stores `self.hash_known` — the 409 body
  depends on it.
- `RunInfo.paused_node_id` is a REQUIRED wire field — any new `RunInfo` test factory needs it.
- Issues **#546** (pinned-run resolve race — the resumed-attempt pin inherits it, tolerated) and
  **#568** (detached-run lifecycle) live on these exact surfaces — serialize behind this task's
  merge. **#542** (trace retention) must treat `paused` traces as un-prunable live obligations.
- Next external bridge (Slack/email): the pattern is proven — read (`/api/gate`-equivalent) →
  render `GateRequest` → answer via `preflight_resume` + spawn. Bridges own their authn;
  `on_pause` hook is additive-later (task-171.md "Consumers & synergies").

## Tests That Matter

- `tests/test_cli/test_ui_interaction_server.py::TestResumeEndpoint` — the five
  no-silent-no-op pins (each asserts `popen.assert_not_called()`); **mutation-verified**: moving
  the spawn above the pre-flight fails all five. Plus
  `test_refusal_literal_map_covers_every_resume_source_error` (the completeness net).
- `TestGateEndpoint::test_real_paused_run_serves_the_masked_payload…` — a real CLI-paused run;
  **mutation-verified**: removing `masked_gate_dict` leaks the secret and fails.
- `tests/test_cli/test_run_tailer.py` oversized-trailer pins — **mutation-verified** against
  deleting the full-re-read branch; plus the `_SCAN_CACHE` second-scan pin (cached-path slot
  transposition passed every fresh-scan test).
- `web/src/views/GraphView.test.tsx` "approval bridge" block — the `runSnapshot` synthesis pin
  and the `runReset` re-arm pin are both **mutation-verified** (each fails ALONE when its line
  is removed).
- `web/src/api/client.test.ts` — the single-read pin (mock body throws on second `json()`).
- `web/src/cssOrder.test.ts` — `.node.unrun` before `.node.dimmed`/`.hover-mark` (source order
  IS the behavior; jsdom can't see it).
- When touching resume/gate surfaces run: `test_resume_cli.py`, `test_paused_cli.py`,
  `test_resume_source.py`, `test_gate_pause.py`, `test_resume_preflight.py`, plus vitest.

## Open follow-up (owner's call, not filed)

Validator-only pre-trace deaths on `--force` resume (and any `/api/run` launch): both spawn
pre-flights are compile-only, so a workflow edited to carry a validator-only ERROR dies before
its meta line → a misleading `run-not-found` ~15s later. Unreachable without `force` (content-
hash gate). One issue should cover both endpoints: "run `WorkflowValidator` in the spawn
pre-flights, or accept the residual."

---
*Distilled from the implementation context of Task 176. The chronological journey — every
deviation with its reason, both deep-review outcomes, and the browser-verification evidence —
lives in `implementation/progress-log.md`; this review is the durable forward-reference.*
