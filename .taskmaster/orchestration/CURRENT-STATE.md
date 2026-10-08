# CURRENT-STATE.md (last verified: 2026-10-07, session-11 close — main @ 012f358c)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Rewritten at close/park (ORCHESTRATION "Artifacts and ownership"); work done outside a
numbered session appends a dated `## Outside-session — folded at next rewrite` block at the top,
which the next boot folds. How-it-got-here: latest `sessions/session-NN.md` (+ the previous three
braindumps); routing: `sessions/INDEX.md`. Every claim here is a pointer to verify, not a fact._

## Process

- Root `CLAUDE.md` Code Quality carries the user's governing lens VERBATIM; quote it in every packet.
- Session-11's end-to-end grant and its capacity grant (Opus planners for 181/120/183) are CLOSED.
- Main orchestrator ran on **Opus** from mid-session-11 (user `/model`); the routing table is unchanged.

## In flight — nothing live; three PLANNED tasks parked on the user (worktrees kept, branches LOCAL, not pushed)

- **Task 183** (loop gates: "iteration N of up to M" + "Approve all remaining") — `feat/task-183-loop-gate-approve-all`
  @ `d01b9b61`. Rulings needed: R1 (CLI/MCP hint line; default not built) · R2 (button when cap unknown; default
  shown) · P4 web phase tier (Fable design-bearing vs Opus) · `implementation/pause-surfaces-before-after.md`.
- **Task 180** (resume refuses only on a restored-step edit; trace bump) — `feat/task-180-resume-step-identity`
  @ `0f813b2b`. Rulings: `implementation/show-before-code.md` (16 scenarios; row 14 = a paused-approval step edited
  after approval must REFUSE — consent hole). P1 (engine `node.start`) may build before the ruling.
- **Task 181** (MCP code params + `${x|json}`) — `feat/task-181-mcp-code-params-json` @ `924b7d94`. Rulings R1–R6 +
  R8 (nouns "Embedded code" / "JSON insert" — wire contract) in `implementation/diagnostics-checkpoint.md`.
  BUILD-GATED on Task 118 Part 2 merging.
- Each worktree's plan was committed by its planner; the planners' handles are gone — launch a task orchestrator
  on the plan, never a fresh planner.

## Shipped in session-11 (2026-10-06 → 10-07)

- **Task 118 Part 1** (PR #723 → `012f358c`): `env:` is a working binding channel (non-strings via `to_string`, no
  leaf auto-parse, binding errors before spawn) + both tooling workflows converted. Status stays `in progress`.
- Lanes: #696+#697 (PR #715, secrets masked in `settings show` / `pflow report`) · #714 (PR #718, gate panel answer
  row pinned, ✕ reachable) · #690 no-format half (PR #719, `Refs` — #690 OPEN for Task 180).
- Filed: #716 #717 #720 #721 #722 #724. Specs: 118 (rewritten), 120 (rewritten), 180/181/182/183 (new), 101 note.

## Next session, recommended order (NOT yet user-agreed)

1. **Show the user** and take rulings: 183 (R1, R2, P4 tier), 180 (show-before-code), 181 (CP-1 R1–R6, R8),
   **120's seven decisions (a)–(g)** in its spec (planner PARKED on them), the #714 shots in
   `scratchpads/session-11/issue-714/` and 118's ruled checkpoint (`.taskmaster/tasks/task_118/implementation/
   diagnostics-checkpoint.md`) — both collapsed to my review under the grant.
2. **Release v0.16.0 BEFORE Task 118 Part 2 merges** — ask once (asked 4× across s10–s11, unanswered). Part 2 is
   the breaking flip; the release gives a clean last-old-form version. Dogfood pass first (release skill).
3. **Task 118 Part 2** — new worktree from main; Opus task orchestrator on the plan (Part 2 phases). Packet adds two
   requests from the 181 planner: a named helper for the per-step scope rule; an "add to used" hook in the
   unused-input pass. CONTEXT.md nouns (plan §11) written at Part 2's merge. Part 2 PR waits on (2).
4. Engine seam serializes: 118 Part 2 → then 180 / 183 builds (both bump the trace; second takes the next number)
   → 181 → 120. Queued engine lanes behind them: #503, #710, #711, #458.
5. Lane-B fill (disjoint): #720 (gate blob crash, high) · #721 (resume panel drops refusal text) · #724 (trace writer
   masks errors) · #716 · #722 · #685 · #684 (show-before-code) · #717 (docs) · #706 (quiet moment).

## Decisions pending the user

- Above (183, 180, 181, 120, release). Also carried from s10, never answered: **#692** (`pflow delete <name>`).
- Promotions applied at closes, to ratify or revert: s10 — kill-by-PID in two defs, the interim sentence in the
  role prompt, the `gh run list --branch` line; **s11** — ADR-FORMAT.md "re-derive every mechanism" sentence,
  `lane-implementer.md` "kill shells left in the tree" sentence.
- Task 179's "of N" wording for #656 was corrected to "of up to M" (no loop is fixed-count) — flag at next contact.

## Do not re-raise (declined, with the trigger that reopens each)

- pr-closer / RELEASE-BLOCK / batched releases / docs-PR lane / automatic PR review / cross-task knowledge
  base — never (DECISIONS #5/#31).
- **#665** (`save --force` data loss) — user: *"save isnt a top tier feature right now all uses ive had myself
  has been in a local repo"*; reopens when saved-library use becomes real.
- Task 179 final-step loop escalation pause — ruled (b); (c) via `resume_after` is its own future ruling.
- #624 shape 2 · retired gemini ids · shell lint / H1 check / PR-title gate / searcher eval harness /
  `Blocked by:` field / DECISIONS index split / agent-file fact checker — triggers unchanged.
- Task 111 default-3 batch limit — WITHDRAWN; opt-in only, `then`. Task 182 (linting) — `then`, no planner yet.

## Regime facts (dated — re-measure, never inherit)

- 2026-10-07: `make test-all-local` 10536 passed on 118 Part 1's merged result; Task-159 baseline 75 pass / 12 drift
  (the 12 listed in Task 183's progress log); open issues ~150.

## Watch list (non-obvious, easy to miss)

- **After Task 118 Part 2 merges**, old-form shell workflows (`${…}` in a command) fail validation with the fix —
  incl. the user's saved library (`~/.pflow/workflows/`); converting it is THEIR call. Any paused/failed run of the
  two tooling workflows from before PR #723 needs `pflow resume --force`.
- PR #719's `workflow`-type carve-out in resume preflight is temporary — Task 180 NARROWS it to pre-`step_identity`
  traces (accepted delta from my "delete" ruling: unconditional deletion would re-fire batched hosts on old traces).
- Resume fidelity is strict per EVENT (179); `--only` still seeds lossy values (ADR-0002). Revisit on complaint.
- MCP stdio shims + `anyio>=4.5` exist only for Task 178 to delete — never port them.
- `stash@{0}` (Task 125 WIP) is the user's — no agent ever runs `git stash`.
- Agent defs/skills in the MAIN checkout are read live by agents launched from the session — committed or not.
