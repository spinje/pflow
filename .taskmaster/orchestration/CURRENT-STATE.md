# CURRENT-STATE.md (last verified: 2026-10-01, session-09 close — main @ 48072699)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Rewritten at close/park (ORCHESTRATION "Artifacts and ownership"); work done outside a
numbered session appends a dated `## Outside-session — folded at next rewrite` block at the top,
which the next boot folds. How-it-got-here: latest `sessions/session-NN.md` (+ the previous three
braindumps); routing: `sessions/INDEX.md`. Every claim here is a pointer to verify, not a fact._

## Process

- Root `CLAUDE.md` Code Quality carries the user's governing lens VERBATIM; quote it in every packet.
  Lane gates bind to the deep-review rubric's floors (`lane-implementer.md`).
- Session-09's end-to-end scope grant is CLOSED — a grant never carries to the next session.
- The user switched the orchestrator model Fable → Opus 5.5 near session-09's end.

## In flight

- Nothing. No worktrees besides main, no open PRs, no live agents. `origin/main == main == 48072699`.

## Recently shipped (session-09, 2026-09-29 → 10-01)

- **Task 170** (one template language, PR #673; closes #630, #262) · **Task 94** (`pflow settings llm
  models`, PR #670).
- Lane B: #617 (#651) · #618 (#653) · #615 (#655) · #606 (#661) · #654 (#662) · #652 (#663) · #643 (#664)
  · #658 (#667) · #657 (#668) · #650 (#671).
- Specs written, not started: **Task 179** (durable loop position — `next`), **Task 178** (MCP SDK 2.x —
  `then`). User-marked open questions: 179 Q1 scope, Q2 failure default; 178 Q1 client era, Q3 HTTP
  diagnostics, Q5 server error text (show-before-code).

## Next session, recommended order (NOT yet user-agreed)

1. **#665** (lane B, destructive): `pflow save --force` deletes the saved workflow before bundling.
2. **Task 179** (lane A, Fable planner): unblocked by 170; #659 is its phase 1; overturns Task 164's
   restart-at-1 stance by user ruling. Engine + trace → serialize; plan-mode deep-review mandatory.
3. Lane-B fill disjoint from 179's engine/trace seam: **#675** (batch memo cache stale — correctness)
   · #674 (scanner skips nodes under a `pflow` dir) · #678 (output-source field check) · #660 · #669.
4. Unblocked by 170, needs ONE user language ruling: #621 / #550 (Task 170 spec "Deferred by design"),
   then Task 118, #648.
5. Task 178 after 179 (178 deletes the two MCP stdio shims).

## Filed this session, open (re-scan at pick)

- #659 (→179) · #660 · #665 · #666 (`< file` routing — reconsider documented pipe-only detection) ·
  #669 · #672 (UI, Fable) · #674–#683 (Task 170 follow-ups; #683 web TS grammar copies — Fable).
- Candidates NOT filed (in PR bodies): `--output-format json <wf> --help` on stdout (#667); runtime
  "Unknown model" → point at `settings llm models` (#670); CLI broken-pipe exit 1 (`| head`); symlinked
  parent validate-vs-run disagreement (#664); code node can't signal intentional failure (#671).
- Older carried (~85 open, not re-read): #627 · #608 · #609 · #589 · #542/#562 (trace — serialize with
  179) · #546 · #568 · #538 · #544 · #549 · #528 · #552 · #580 · #553 · #520/#521 · #566/#567/#572/#574/
  #575 · #601 · #602 (upstream) · #644 (p2 = Task 178).

## Do not re-raise (declined, with the trigger that reopens each)

- pr-closer / RELEASE-BLOCK / batched releases / docs-PR lane / automatic PR review / cross-task
  knowledge base — never (DECISIONS #5/#31).
- #624 shape 2 (pflow-managed session holder) — reopens per the trigger recorded on #624.
- #656 UI "approve all remaining rounds" — folded into Task 179's UI pass (decided once there).
- Retired gemini ids in `settings llm models` — documented limitation; reopens with v2 curation.
- Shell lint, H1-as-name check, PR-title gate, searcher eval harness, `Blocked by:` field, DECISIONS
  index split, agent-file fact checker beyond `test_agent_references.py` — triggers unchanged.

## Regime facts (dated — re-measure, never inherit)

- 2026-10-01: `make test` ~10.2k passed on the 170 merged result; CI ~14 jobs incl. 3 Windows;
  `tests-windows-mcp-smoke` flaked once on an npx timeout (rerun green). Boot set: `./scripts/tasks --boot`.

## Watch list (non-obvious, easy to miss)

- Next hot seam = engine + trace: Task 179 (`_run_inner` loop counters, `_gate_pausable`, gate branch,
  `resume_source`/`resume_preflight`, trace schema) — serialize #542/#562/#659 and any engine lane.
- MCP stdio shims (`core/stdio_reservation.py`; `PflowMCP.run_stdio_async` touches private
  `_mcp_server`) and the `anyio>=4.5` dependency exist only for them — Task 178 deletes, never ports.
- The screenshot suite now FAILS loudly when the page doesn't settle (`allow_empty` opt-in) — a red
  screenshot run is signal, not flake. `chrome-devtools` local registration pinned `@1.10.1`.
- `stash@{0}` (Task 125 WIP) is the user's — lanes never `git stash` (stashes are repo-wide).
