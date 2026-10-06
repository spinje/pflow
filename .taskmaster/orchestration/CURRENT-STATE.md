# CURRENT-STATE.md (last verified: 2026-10-06, session-10 close — main @ 3b342ce9)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Rewritten at close/park (ORCHESTRATION "Artifacts and ownership"); work done outside a
numbered session appends a dated `## Outside-session — folded at next rewrite` block at the top,
which the next boot folds. How-it-got-here: latest `sessions/session-NN.md` (+ the previous three
braindumps); routing: `sessions/INDEX.md`. Every claim here is a pointer to verify, not a fact._

## Process

- Root `CLAUDE.md` Code Quality carries the user's governing lens VERBATIM; quote it in every packet.
- Lens selection is by TRIGGER, never diff size (deep-review skill, rewritten s10 with the user); spec-review
  mode and the standing dogfood pass are the main orchestrator's (ORCHESTRATION "Review policy").
- `docs/` is a required stale-surface sweep for every lane/task (root CLAUDE.md:184, lane def, spec-conformance).
- Session-10's end-to-end grant is CLOSED — a grant never carries to the next session.

## In flight

- Nothing live. No worktrees besides main, no open PRs, no live agents. `origin/main == main == 3b342ce9`;
  the push CI for it was in progress at close (GitHub Actions had an open incident all day — read the failing
  step's log before calling a red run a regression).

## Committed by the user

- The session-10 doc set (skill rewrite, defs, CLAUDE.md, ADR-0016, specs, state files) landed as the user's own
  commit `0d935987` "docs: session 10 docs". The 118 spec + ADR-0016 are therefore on main — the next session's
  118 planner needs NO prep commit, only a push check (`git status -sb` vs `origin/main`).

## Recently shipped (session-10, 2026-10-05 → 10-06)

- **Task 179** (durable loop position, PR #713; closes #659; trace format 2.8.0; resume refuses lossy seeds).
- Lane B: #678 (#704) · #521+#389 (#705) · #627 (#707, `NodeError` + ratchet).
- Issue hygiene: 19 closed (4 verified-fixed in the morning, 15 by the KEEP-biased triage), 11 narrowing/evidence
  comments, 26 filed (#684–#712 — dogfood + lane follow-ups). Open: 145.

## Next session, recommended order (NOT yet user-agreed)

1. **Task 118 planner** (lane A, Fable; spec + ADR-0016 committed in `0d935987`):
   shell `env:` binding, bodies untemplated, `|json` filter — its trigger (#678 merged) is met.
2. Engine seam is QUIET now → the lanes serialized behind 179 are free: **#690** (fix-then-resume refused
   twice) · **#458** (`--only` inputs ignored, re-observed) · **#503** + `batch_executor.py:1190` (engine vanilla
   raises; extend #627's ratchet) · **#710** · **#711**. Launch at most 3 lanes + 1 planner (host load).
3. **Task 120** (strict input types; `next`, observed via dogfood) — small, no engine contact; pairs with #297.
4. Lane-B fill, disjoint: **#696/#697** (security: unmasked `<X>_KEY`; `report` renders secrets) · **#685** (MCP
   `Error: Error` + Windows smoke flake root cause) · **#684** (structured node suggestions — show-before-code)
   · **#520/#681** (validator seam, now free) · **#706** (fan-out `target` — a QUIET moment, shared tooling).
   · **#714 then #656** (web UI, Fable, screenshots before ship): #714 pins Approve/Deny out of the gate panel's
   scroll; #656 (REOPENED by the user post-close) adds "iteration N of M" + "Approve all remaining" — the limit
   needs a `GateRequest` field from `runtime/engine/gate.py` → engine contact, route as a small task or a scoped
   engine exception (precedent #615).
5. **Release v0.16.0** — ASKED THREE TIMES, NOT ANSWERED (s10). 43+ commits since v0.15.1. Do not nag; surface
   once with the dogfood pass as the pre-release gate (release skill now requires it).
6. Task 178 (MCP SDK 2.x; refresh its research — PyPI is at 2.3.0, research pinned 2.2.0).

## Decisions pending the user

- **#692** product question: no command deletes a saved workflow (rec. `pflow delete <name>`).
- **#684** render shape for node-failure suggestions (lane hands back BEFORE/AFTER first).
- Specs 99 and 121 carry "SPEC REWRITE REQUIRED" blocks — no planner launches on them until rewritten.
- RECURRENCE promotions applied at s10 close (ratify or revert): kill-by-PID mechanism in two defs; the interim
  sentence in the role prompt; the `gh run list --branch` line in STANDING-KNOWLEDGE. n=3 "read the cited
  function before writing a mechanism" → PROPOSED home: ADR-FORMAT.md review rule + create-task skill.

## Do not re-raise (declined, with the trigger that reopens each)

- pr-closer / RELEASE-BLOCK / batched releases / docs-PR lane / automatic PR review / cross-task knowledge
  base — never (DECISIONS #5/#31).
- **#665** (`save --force` data loss) — user: *"save isnt a top tier feature right now all uses ive had myself
  has been in a local repo"*; reopens when saved-library use becomes real (external users, or the user saves).
- Task 179 final-step loop escalation pause — ruled (b); (c) via `resume_after` is its own future ruling.
- #624 shape 2 · retired gemini ids · shell lint / H1 check / PR-title gate / searcher eval harness /
  `Blocked by:` field / DECISIONS index split / agent-file fact checker — triggers unchanged.
- Task 111 default-3 batch limit — WITHDRAWN (breaks the review fan-out and a shipped test); opt-in only, `then`.

## Regime facts (dated — re-measure, never inherit)

- 2026-10-06: `make test-all-local` ~10.4k on main; Task-159 baseline = 12 pre-existing drifts (#680, re-record
  pending); a dogfood pass costs ~$0.00004 (8 calls, gemini flash-lite); 143→145 open issues.

## Watch list (non-obvious, easy to miss)

- **Resume fidelity is strict per EVENT** (179): a `datetime` beside the data a step reads blocks failure-resume
  and stops a later gate from pausing; remedy printed. Revisit only on an observed complaint. `--only` still
  seeds lossy values (ADR-0002's limit) — not covered.
- Task 118 changes what `${…}` means in a shell body (ADR-0016) — the guide's `$VAR`-not-`${VAR}` rule and every
  inline-templated shell example flip; the `env:` limits (strings, ~128 KiB, Windows case) go in the guide.
- MCP stdio shims + `anyio>=4.5` exist only for Task 178 to delete — never port them.
- Screenshot suite fails loudly on no-settle (`allow_empty` opt-in) — a red run is signal. `chrome-devtools` pinned `@1.10.1`.
- `stash@{0}` (Task 125 WIP) is the user's — lanes never `git stash`.
- Agent defs/skills in the MAIN checkout are read live by agents launched from the session (ORCHESTRATION
  "Collision analysis") — committed or not.
