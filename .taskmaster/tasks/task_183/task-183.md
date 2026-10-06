# Task 183: Approval Gates in Loops — Show "Iteration N of up to M" and Offer "Approve All Remaining"

## Description

A gated loop pauses once per iteration. The web UI's gate panel shows which iteration is waiting
but not how many there are, and its only action approves one. Show the iteration together with
the loop's limit on every pause surface, and add an opt-in "Approve all remaining" action in the
web UI so a gated loop can be finished from the browser in one click.

## Status
not started

## Priority

medium

## Roadmap

next

## Problem

- Since Task 179 the ordinary **Approve** finishes a gated loop one iteration at a time; a
  30-iteration loop is 30 clicks. The CLI has `pflow resume <token> --approve yes --auto-approve
  <step>`; the browser has nothing equivalent (`/api/resume` has no auto-approve field).
- The panel reads "iteration 2" with no limit, so a user cannot tell how many approvals remain —
  and a bulk action would approve a count they cannot see.

## Design Decisions

- **DECIDED (user, 2026-09-30: *"yes lets do this"*; reopened 2026-10-06)** — the button is
  built. The earlier "not built" call was the orchestrator's under a session grant; the user
  reviewed the checkpoint page and asked *"im not sure I undertstand why we dont want an accept
  all button?"*. The three reasons given did not hold: per-round Approve stays for anyone who
  wants it; the CLI flag does not help someone in the browser; and "the panel doesn't show the
  limit" argues for showing the limit.
- **Show the limit wherever the iteration is shown, always as an upper bound: `iteration 1 of up
  to 3`.** (Refreshed 2026-10-06 against `eecbcd5d` — the earlier "`of 3` for a fixed-cap loop"
  split rested on a wrong premise: no loop is fixed-count. Every `loop:` declares `while:` or
  `until:` (`runtime/compilation/compiler.py:428`, `runtime/engine/loop_control.py:262-271`) and
  the condition is checked before the cap, so `max_iterations` is always a ceiling. The user's
  intent — show the limit — is unchanged; the wording is the accurate one.) When the author set no
  `max_iterations`, the cap is the engine's safety limit (`MAX_NODE_VISITS`, 100, env-overridable,
  `runtime/engine/instrumentation.py:24`) — omit the clause then rather than show "of up to 100".
- **One field, every surface — and one renderer.** Today the iteration text has four renderers,
  not one: `format_gate_lines` (`core/gate_prompt.py:216` — non-TTY run output, MCP, resume's
  answer-required error), `_iteration_suffix` (`gate_prompt.py:126-128` — TTY prompt and flag
  echo), `pflow resume list` text and JSON (`cli/commands/resume.py:439, 459` — its JSON
  `iteration` key is an agent contract, and the cap joins it under the same field name), and the
  web panel (`web/src/components/GateCallout.tsx:105`). One Python helper renders loop position
  and the three Python sites call it; the web copy is pinned by a test against the same fixture.
- **"Approve all remaining" appears on approval gates raised by a loop step only** (escalation
  gates also carry `iteration`, `runtime/engine/gate.py:163`, but `--auto-approve` covers approval
  gates only, `core/gate_prompt.py:90`), beside Approve, and maps 1:1 to the
  CLI's existing behaviour: `POST /api/resume` gains `auto_approve: bool` (a 400 when combined with
  `approve: no`), which becomes `--approve yes --auto-approve <paused step>`. The CLI stays the
  single source of behaviour; the server only maps the answer to argv. The label never names a count
  — the engine promises no count, only a ceiling.
- **The written design is the starting point, not a contract**: Task 179's
  `implementation/implementation-plan.md` §4 P4b (line ~650). Re-verify it against the merged code.

## Constraints

- **Engine contact — and the cap is not available where the gate is built today.** The gate
  payload carries only `iteration` (`core/gate.py:53`); the gate builder
  (`runtime/engine/gate.py:82-89`) receives only config, params, shared and trace. The resolved
  cap (`loop_caps`) is a local of the engine walk (`engine.py:936`), filled lazily in
  `should_reenter` AFTER iteration 1 has run (`loop_control.py:273-276`), and empty again on
  resume; a templated `max_iterations` may reference the node's own output
  (`loop_control.py:242-243`), so resolving it at iteration 1's gate can fail. The plan states
  where the cap is written once (at loop entry) and how the gate reads it, with "unknown" a legal
  value. The field is display-only — never read by resume — mirroring `iteration`'s contract
  (`core/gate.py:51-52`), so Task 179's "one reader of position" stays intact. Plan-mode
  deep-review is mandatory; the build serializes with every other engine change.
- **It is a trace-format change.** `gate_request` is trace content twice — the trailer
  (`runtime/workflow_trace.py:1094-1095`) and the gate pause line (`:677-678`) — and 2.8.0 exists
  because Task 179 added `iteration` there (`:40-41`). Additive minor bump (Task 180 also bumps
  the trace format; the builds serialize, whichever lands second takes the next number), the
  comment block extended, the Task-159 baseline as the outer net. Old records without the field
  render today's text (every renderer guards with an `int` check — `gate_prompt.py:229`,
  `GateCallout.tsx:105`, `resume.py:459`); pin that with a test on a trace that lacks it.
- **Field shape (orchestrator's default, 2/5 — the planner may argue otherwise at hand-back):** a
  flat sibling of `iteration`, named after the authoring key (`max_iterations: int | None`, absent
  for non-loop gates). Rejected: a nested `loop: {iteration, cap}` object — it would move Task 179's
  top-level `iteration`, already in 2.8.0 traces, the gate lines and resume-list JSON.
- **A new field on the pause payload is an agent-facing contract** (CLI JSON, MCP response,
  `/api/gate`): name it once, state what it is for a `while:` loop and for a non-loop gate
  (absent, not zero), and whether a paused-run record written before this task still renders.
- **UI/taste phase — show-before-code.** The panel change is a design-bearing UI phase: the plan
  states the look/feel intent and acceptance criteria, the `screenshot-pflow-web-ui` skill
  verifies it, and the user sees before/after screenshots before merge. Builds on #714 (the
  action row is pinned to the panel's foot and must stay reachable with a second action in it,
  at a narrow window too).
- **Pre-flight parity.** `/api/resume` already mirrors the CLI verb with strict body validation
  and "no silent no-ops"; the combined answer is refused or accepted exactly as the CLI does.
- **`/api/resume` contract** (planner-level; state it): `auto_approve: true` requires
  `approve: "yes"` and is a 400 otherwise, including with `choose`; on a non-loop approval gate it
  is accepted as the CLI accepts it ("loop gates only" is a UI rule). The CLI's `--approve no` +
  `--auto-approve` contradiction lives in `resume.py::_approval_answer` (`:122-123`), not in
  `preflight_resume`, so the server needs its own check; `_resume_cli_args` (`ui/server.py:1281`)
  needs the paused step id from pre-flight to build `--auto-approve <step>`.
- **#720** (gate strings ≥1 KB reach `/api/gate` as unresolved blob references): verification
  fixtures keep gate previews under 1 KB, or this task sequences after #720.

## Dependencies

None blocking once #714 has merged. Read first: `.taskmaster/tasks/task_179/task-review.md`
(loop position, one reader of position, the one-field-all-surfaces rule), Task 176's review
(web-UI approval bridge), issues #656 and #714 in full (body + comments).

## Verification

- Real browser run: a gated 3-iteration loop is finished with ONE click on "Approve all
  remaining" — exactly 3 side effects are written (presence: the effects file has 3 lines) and the
  run completes; single Approve still advances one iteration.
- A loop with `max_iterations: 3` shows "iteration 1 of up to 3"; a loop with no `max_iterations`
  shows "iteration 1" (no engine safety limit); a non-loop gate is unchanged and offers no bulk
  action — identical text on the TTY prompt, the non-TTY pause output, the MCP pause response,
  `pflow resume list` (text and JSON) and the web panel. Iteration 1's gate shows the cap (the
  cap exists before the loop body has run once).
- `POST /api/resume` with `auto_approve: true` + `approve: no`, or a malformed body, is a 400
  before anything is spawned.
- Before/after screenshots for: a loop gate with an author cap, a loop gate without one, a
  non-loop gate, an escalation inside a loop (no bulk action), the narrow window.

## References

- Issue #656 (governing; closes with this task) · #714 · #615 / PR #655 (the one-answer rule).
- `web/src/components/GateCallout.tsx`, `ResumeControl.tsx`, `resumeAnswer.tsx`;
  `src/pflow/ui/server.py` (`_parse_resume_body`, `_resume_cli_args`).
