---
name: "close-orchestrator-session"
description: "End-of-session ritual for the pflow MAIN ORCHESTRATOR. Invoke when the user closes a session or the context window nears its end."
---

# Close Orchestrator Session

The main orchestrator's session close is a **retrospection event, not a filing chore**. The state
docs should already be true (you update them as events land); what this moment adds is the look
BACK across the whole session — the corrections, overturned calls, improvised mechanisms, and the
user's exact words — before they age out with your context window. A successor boots on
`ORCHESTRATION.md + DECISIONS.md → CURRENT-STATE.md → latest session file (thin-file rule,
DECISIONS #10) → BRAINDUMP.md` and nothing else; this ritual makes that stack sufficient.

**Ground rule: verify, then write.** Every claim entering a durable file gets checked against
reality first (`git log`, `gh`, `./scripts/tasks`, `git worktree list`, the filesystem) — a
braindump line that's false is worse than a missing one.

## 0. Drain — nothing closes hot

If anything is in flight, the close has not started yet: **let all running agents and tasks run
to the end, fix all loose ends, THEN close out.** Keep doing the job — relay handbacks, nudge
stalled lanes, merge what reaches CI-green, tear down merged worktrees — until the board is
quiescent. Two exceptions:

- A task parked on an external gate (a user ruling that can't happen now, an upstream dependency):
  park it properly per ORCHESTRATION.md — a FULL resume-state entry in its progress log — because
  **your subagent handles die with this session**; a successor can only launch a replacement from
  spec + plan + progress log, never resume your subagents.
- **Lane-C terminal agents live outside your session** and keep running — they don't drain.
  Record their state (worktree, what they're building, what to verify on merge) in
  CURRENT-STATE instead.

## 1. Retrospect (think before touching any file)

Walk the session start-to-end and answer, honestly:

1. **What did the user correct?** Each correction generalizes to a rule — capture the rule, in
   their words where possible. Their interjections are surgical (wrong facts, scope, sensitivity);
   the correction is always more general than the instance.
2. **Which of my assertions were overturned** — by the user, by a searcher, by a probe? Own each
   one explicitly, with the lesson shape ("I trusted X over the primary source").
3. **What did I improvise that worked?** A mechanism a successor should reuse needs enough
   specificity to be reusable (the exact command shape, the trap it avoids).
4. **What dead ends did I hit, and why exactly?** A one-line "don't bother with X because Y"
   saves a successor the whole detour.
5. **What is ASKED-NOT-ANSWERED, UNCLEAR, or ASSUMED — and what did I mean to ask the user but
   never did?** Mark them as such — an unmarked assumption reads as fact to a successor.
6. **Did any standing watch item / open thread close this session?** Closed means struck
   EVERYWHERE it appears (CURRENT-STATE, braindump, session file) — a survived stale line
   re-litigates itself next boot.
7. **What almost broke, and why didn't it?** Near-misses are the purest tacit knowledge — no
   log records the disaster that was narrowly avoided.
8. **What cross-task connections or seams did I notice that aren't recorded anywhere?** Seams
   are this role's core value; the ones that didn't force an action yet are exactly the ones
   that evaporate.
9. **What would I do differently if starting over?** This question GENERATES step 4's
   process-evolution proposals — answer it before you get there.
10. **What would I be furious at a successor for not knowing?**

## 2. Make the state true

Should be near-no-ops if you kept discipline; audit, don't rewrite:

- **CURRENT-STATE.md** — as-of line current; In flight / candidates / Watch reflect reality;
  closed items struck (`~~…~~` with a one-line verdict), not silently deleted. No session digest —
  the session file boundary does that job. Respect the ~80-line budget: every line a pointer to
  verify, not a fact.
- **Session file** — entries were appended as events landed; add nothing at close except what
  step 1 surfaced that belongs to the journey (an overturned call, a ruling). No summary rewrite.
- **Trackers** — the CLAUDE.md roadmap, task spec Status lines, and spec decision ledgers were
  reconciled at each ship; spot-check the ones this session moved.
- **DECISIONS.md** — every settled-decision-grade user ruling from this session has a row
  (same-breath rule); if one is missing, that's a discipline failure to note AND fix.

## 3. Refresh the braindump (the introspection core)

Update the **rolling tacit layer** — the top section of
`.taskmaster/orchestration/BRAINDUMP.md`, above the `---` that precedes the frozen **Genesis**
section (2026-07-02; never refreshed) — **in place, minimal deltas**, extending its header with
this session's marker. This is a knowledge transfer to yourself, returning
with no memory. The doctrine, customized for this role:

**The one test, applied line by line to the EXISTING file first:**
> "Could the next agent find this by reading files?" If yes — cut it.

Knowledge migrates: what was tacit last session may now live in a skill, a task-review, a
DECISIONS row, or a gotcha that got fixed in code. **The braindump must shrink as knowledge
becomes durable elsewhere** — pruning stale lines is as important as adding new ones. Delete
verified "needs verification" items; rewrite bullets whose advice was superseded (never leave an
old bad habit standing next to its correction).

**What belongs (add from step 1):**
- The **user's mental model in their exact words** — phrasing for key concepts, sensitivities
  observed (what they hard-stopped, what they waved through), the direction their trust/rules are
  moving.
- **Overturned diagnoses** with the lesson shape, owned plainly.
- **Mechanisms that worked**, specific enough to reuse; dead ends with the exact reason.
- **Local-only artifacts** a successor cannot discover (gitignored briefs in `scratchpads/`,
  machine state, unpushed commits, pending external steps) — with where they live and what to do
  if missing.
- Markers: `UNCLEAR:` · `ASSUMPTION:` · `ASKED-NOT-ANSWERED:` · `NEEDS VERIFICATION:` — explicit
  uncertainty beats implied confidence.

**What does NOT belong:**
- What shipped, task status, PR numbers, board state (CURRENT-STATE / session files / reviews).
- Process rules and rulings (ORCHESTRATION.md / DECISIONS.md — link, never restate).
- Generic advice, summaries, anything re-derivable from the repo.

Keep the closing note-to-next-agent line intact (read fully → summarize → proceed).

## 4. Propose process evolution (never silent)

If the session changed how this role operates — a new failure mode hit, a mechanism worth
standardizing, a rule the user stated — **propose** the edit to `start-orchestration` (the role
prompt) or `ORCHESTRATION.md` and let the user rule. Editing your own role definition is never a
unilateral act. (A skill/tooling gap you can fix in-repo — a script hardening, a stale agent def —
is normal work, not this. Remember the mirror sync: `uv run python
scripts/sync_claude_assets.py --write` after editing any `.claude/` asset.)

## 5. Boot-readiness and handoff

- **Boot-readiness check, the final gate:** re-read your last state as a cold successor would —
  ORCHESTRATION → CURRENT-STATE → session file → braindump. If acting correctly would require a
  fact that exists only in your head, it isn't written yet; go back to step 3.
  (Boot stack: ORCHESTRATION + DECISIONS → CURRENT-STATE → session file → BRAINDUMP.)
- Session close does not authorize a commit. Report the exact uncommitted files; any commit or
  push follows DECISIONS #5.
- Tell the user the session is closed and what the successor will pick up first.
