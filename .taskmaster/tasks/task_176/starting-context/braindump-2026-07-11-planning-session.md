# Braindump: Task 176 planning session → implementing agent

_2026-07-11, written by the planning agent at commit `0b33f845` (nothing implemented yet — Phase 0
has NOT been run). The plan (`implementation/implementation-plan.md`) is the build contract; the
spec carries a corrections block dated today. This file holds only what is NOT written there._

## Where I am

Planning is 100% done and deep-reviewed (4 agents: plan-structure, validation-consistency,
silent-failures, impact-completeness — zero Criticals; every confirmed finding is already folded
into the plan text, none are outstanding). The plan was built from 8 searcher audits whose raw
reports are gone with my context — but every load-bearing fact from them was transcribed into the
plan with file:line, so treat the plan as verified, not aspirational. I personally re-verified the
two findings that changed the design (missing `hash_known` attribute; compile-before-meta-flush at
`runner.py:318`) before accepting them.

## User's mental model (their words matter — reuse them)

- **"We should prioritize simplicity of the FINAL code, not how easy it is to get there."** And:
  *"whats the right solution that the top 10% of codebases similar to this one would implement,
  have we considered it yet?"* — immediately qualified both times with: this is NOT about
  over-engineering, it's about **"more simple code that is optimized for AI agents to understand
  and add features to."** When you face a judgment call, that pair is the tiebreak: consolidate
  behind one rule/home, but never add a seam with one consumer.
- They interrupted me mid-write with **"stop before starting to write the plan"** — they want
  discussion/verification BEFORE artifacts, not after. If implementation surfaces something that
  contradicts the plan, surface it and pause; don't patch around silently.
- **"The plan should be made so another ai agent can implement it in isolation without any
  ambiguity"** — deviations from the plan are therefore *events to report*, not judgment calls.
- Subagent discipline (explicit instructions): use **`pflow-codebase-searcher`** for verification,
  never Explore/general-purpose; read the canonical task reviews **yourself** (they corrected me
  on this mid-session when I delegated them); for deep-review, **"deploy only the most relevant
  subagents."**
- Decision style: both open UX/API calls were settled fast via a recommended-option question
  (ledger #4/#5). They accept recommendations when grounded — bring a recommendation, not a menu.

## Reasoning that lives only here (rejected paths — don't re-derive)

- **Pre-flight via spawning `pflow resume --dry-run --output-format json`** — rejected: a full
  child process + compile per validation, and dry-run's side-effect-confirm skip makes its refusal
  set differ from the real spawn's. In-process `preflight_resume` is both faster and exact.
- **Serving the gate payload off the POST's 409 `answer_required` error** (it already carries the
  masked gate in `context["gate"]`) — rejected: a read API implemented as an error path; the
  GET is honest and matches the read → render → answer flow of ADR-0009.
- **A third gate-panel entry point** (an "Answer…" button on the paused banner) — cut for
  simplicity; auto-show + ⏸-node click are the two that ship.
- **Client-side "already answered" pre-check** (inverse `resumed_from` scan) — rejected as
  plumbing without a consumer; the POST's superseded 409 is authoritative (edge ledger #5).

## Suspicions / instincts not proven

- **NodeCallout may be cramped for the escalation form** (options + free text). The plan marks
  CSS-fit as the one presentation assumption. If it genuinely doesn't fit after a real screenshot,
  the fallback the user already saw (and ranked second) is the RunPanel-style side panel — that
  would be a ledger-#5 amendment, so ask before switching.
- **Two callouts render simultaneously for a pinned paused run**: the existing run callout
  (anchored at the inputs card / first step — `runAnchorId`, GraphView.tsx:338) AND the new
  GateCallout (anchored at the ⏸ node). Different anchors so probably fine, but nobody has seen
  it. MIGHT MATTER: check overlap in the first real-browser pass, especially TD direction + small
  workflows where the anchors are close.
- **`GateRequest.options` element shape**: I typed it `Array<Record<string, unknown>>` with
  `option.label` (mirroring `option_labels`' `.get("label")` fallback). NEEDS VERIFICATION:
  transcribe the real option dict shape from an actual escalation payload before finalizing the
  TS type — options may carry more than `label`.

## Hard-won connections

- **Build server tests on REAL paused traces**, not hand-crafted JSONL. The 164 review's
  twice-bitten anti-pattern (synthetic fixtures encoding shapes production never writes) applies
  directly to the new `TestGateEndpoint`/`TestResumeEndpoint`: produce traces by running the
  `test_paused_cli.py` fixtures' gated workflows (its `escalating_registry` injection only works
  inside pytest — never run it standalone). The `_write_trace` helper in `test_ui.py:884` is fine
  for the *projection* tests (it mirrors producer shape), but answer-flow tests should come from
  the real producer.
- **GateCallout anchor re-resolution is free if you mirror `sayAnchorIdFor`** — the say bubbles
  re-derive flat ids every render precisely because flat ids renumber on canvas rebuild
  (auto-update mid-open). Don't cache the anchorId.
- The frontend tests assert badges via `getByLabelText("run status: <label>")` — the `paused` arm
  of `runStatusLabel` is user-visible AND test-visible; pick the label string once ("paused —
  awaiting answer" per plan) and keep it.
- The five searcher reports named exact vitest templates per component (GraphView.test.tsx:287
  for synthesis, RunPanel.test.tsx:9-22 for client mocking, RunProgress.test.tsx:142 for the
  paused banner) — these are in the plan's test sections; copy structure, don't invent harnesses.

## Assumptions & uncertainties

- ASSUMPTION: `CliRunner`/`monkeypatch.setenv` delivers `PFLOW_EXECUTION_ID` into `os.environ`
  for the P2-T4 pin test (standard technique; run.py pops from `os.environ` directly).
- UNCLEAR: `/api/gate` response naming is "name-final at build" per plan — just pick `/api/gate`
  and update `ui/CLAUDE.md`; don't bikeshed.
- NEEDS VERIFICATION (mechanical, at build): the exact `compile_workflow` kwargs for the server
  wrapper — mirror `_preflight` (server.py:1011-1027) which the plan cites; my
  `initial_params=dict(pf.source.inputs or {})` is the intended shape but check `_preflight`'s
  param handling for the authoritative form.
- The old 171-era counts (vitest 727, `make test` 8662) are stale — Phase 0 captures fresh ones;
  don't diff against these.

## Unexplored territory

- UNEXPLORED: throttling/debounce if the user double-clicks Approve (two POSTs → second gets
  superseded/still-running 409 — harmless but a `submitting` disable-while-in-flight flag is the
  cheap guard; the plan's GateCallout state includes `submitting`, use it).
- UNEXPLORED: what the RunSelector shows *while* the resumed attempt is mid-flight (source run ⏸ +
  new live run) — believed fine (shipped 171 rendering), never visually confirmed with the bridge
  flow. Part of the Phase-5 screenshot pass naturally.
- CONSIDER: `review-agent-ux` as a fifth reviewer at the Phase-5 code review — the 409
  `refusal` vocabulary and diagnostics are agent-facing surfaces and that agent's exact domain;
  I skipped it at plan stage (shapes weren't final), it earns a slot once they are.

## For the next agent

- Start with Phase 0 (baseline), then Phase 1 — the phases are strictly ordered and the plan says
  why. Don't start the frontend before the P2 checkpoint deep-review.
- **Kill stale `pflow ui` processes before ANY browser verification** — the reuse-if-up probe
  serves old code; this burned the 171 implementer and is easy to forget mid-flow.
- The spec now contains a corrections block; where spec prose and plan disagree, **the plan wins**
  (the spec says so itself).
- The user is the owner for: anything touching ledger decisions, panel-placement changes, and any
  discovery that the 125/171 contracts don't hold (the spec's escalate clause).

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points, then state you're ready to proceed.
