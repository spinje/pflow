# session-07 — 2026-08-14

## [2026-08-14] main orchestrator — cross-repo knowledge-transfer fold (user-approved, all tiers)

- User commissioned an audit of the sibling orchestration programme (the more mature installation
  of this same system) for transferable general doctrine; approved Tier 1 + Tier 2 in full.
- Fold executed across phases 1–9 (plan: `scratchpads/cross-repo-knowledge-transfer/plan.md`,
  local-only): DECISIONS.md converted to heading format (#1–#14 preserved); Write-discipline,
  effort-routing, review-labour, absence-needs-presence, verified-or-dropped into ORCHESTRATION;
  autonomy-grant + relay-craft + question-discipline + failure modes 9–11 into the role prompt;
  braindump theme doctrine + session-file spent-category cut into the close skill; BRAINDUMP
  restructured by theme (quotation-grep verified, zero losses); ADR adversarial review into
  ADR-FORMAT. Rows #15–#19 record it.
- **User ruling: repo names of the sibling programme (and its predecessor) appear NOWHERE in this
  repo** — scrubbed repo-wide including historical session logs, one release note, and the
  sandbox-testing codex skill; verified zero matches. A verbatim user quote in the braindump was
  bracket-edited to comply.
- **User ruling: state-doc cadence flipped (DECISIONS #16)** — supersedes "written as events
  land"; CURRENT-STATE rewritten at close/park; braindump only at close.
- Effort re-pins applied (#18): implementers + 4 heaviest lenses → medium; planner/orchestrator
  high; searcher low.

## [2026-08-14] main orchestrator — review dispatch + falsifier shipped and shaken down

- `workflows/review/run-review-lenses.pflow.md` + `workflows/search/run-searcher.pflow.md` ported
  (dry-run validated); deep-review skill: codex fan-out = FOREGROUND default, direct launches a
  logged fallback, plan-mode always direct. **DECISIONS #17 completed**: dispatch is
  Bash-drivable, so the whole completion gate is one job owned by the gate-runner
  (task-orchestrator + task-phase-implementer rewired).
- `review-falsifier` authored (execution lens; never in the read-only fan-out) and registered.
- **Fan-out shakedown PASS** (1 lens on `573718cb`, ~3.5 min): correct merged report, honest
  coverage. Known cosmetic gap: pflow has no pricing data for `gpt-5.6-sol` — fan-out runs show
  "cost unavailable".
- **Falsifier shakedown PASS with real findings** (~19 executed attacks, 10 entry surfaces;
  PATH-shadowed fake `codex` binary enabled a real batch attack with zero paid calls): #592's
  three headline promises HOLD; two edge promises FALSIFIED → issues **#608** (templated
  `float("inf")` → `Type: OverflowError`; catch tuples not widened) and **#609** (exec-path
  `AgentValidationError` stripped to class name and retried). Correcting comment posted on PR
  #597 (its body claims `retriable=False`; shipped code is `retriable=True`, execution confirms
  the code). Stale-docstring finding converged across BOTH shakedowns independently.
  Falsifier's shakedown notes folded into its own def (external-binary double as a first-class
  vehicle; legal-envelope test; arsenal conditional on surface).

## [2026-08-14] main orchestrator — lane-implementer adopted (DECISIONS #20) + def sweep

- User ruling: lane B moves to a dedicated `lane-implementer` (evaluate-first, escalation >2/5,
  proportionate gate with floor-of-one, merges own PR per #4/#14); task-orchestrator's issue mode
  retired; `code-implementer` kept as the designated mechanical leaf (user probed substitution —
  they're different altitudes: lane owns judgment, leaf performs decided work).
- Def sweep imports: planner cross-task board scan + lens-assignment rule; test-reflect RESOLVES
  logging; background-Bash wake-trap + monitor/relay rules (pflow had NO such rule anywhere);
  REVIEW-PROTOCOL refute-not-confirm / re-verify-before-report / partial-coverage-reportable;
  plan-mode-never-via-fan-out fix to my own Phase-8 wiring.
- **Fold tail (DECISIONS #21, user: "go ahead")**: lean audit shape + leverage filter into the
  architecture skill; capacity-grant protocol into the role prompt; guard-crash heuristic into
  lane-implementer; #5 prep-commit refinement. "Every task gets a planner" considered and HELD.
- Issues #608/#609 filed + PR #597 correcting comment posted (user-approved). Session-07 file +
  CURRENT-STATE rewrite done same day (state layer had recorded nothing of the fold).
- Verification at close of work: `make check` green; `./scripts/tasks --check` clean; all
  `DECISIONS #N` citations resolve through #21; asset mirrors in sync; name-ban grep zero.
- **Everything UNCOMMITTED per DECISIONS #5** (37 files + new workflows/ and lane-implementer/
  falsifier defs). Deliberately unported: pr-closer + release-block machinery; appsec /
  architecture-fit / error-surfaces lenses (flagged follow-up); migration/tenant lenses.
