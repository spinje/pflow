---
name: close-orchestrator-session
description: "End-of-session ritual for the pflow MAIN ORCHESTRATOR. Invoke when the user closes a session or the context window nears its end."
---

# Close Orchestrator Session

The main orchestrator's session close is a **retrospection event, not a filing chore**. Session-file
entries capture real transitions; `CURRENT-STATE.md` is rewritten at close/park (DECISIONS #16).
This moment also adds the look BACK across the whole session — the corrections, overturned calls,
improvised mechanisms, and the user's exact words — before they age out with your context window.
A successor boots on `ORCHESTRATION.md + DECISIONS.md → CURRENT-STATE.md → the latest session
file in full (thin-file rule, DECISIONS #10) + the previous three sessions' braindumps →
STANDING-KNOWLEDGE.md → RECURRENCE.md` (INDEX.md is grepped when an arc surfaces, never skimmed),
plus its own reality verification; this ritual makes that stack sufficient.

**Ground rule: verify, then write.** Every claim entering a durable file gets checked against
reality first (`git log`, `gh`, `./scripts/tasks`, `git worktree list`, the filesystem) — a
braindump line that's false is worse than a missing one.

## 0. Drain — nothing closes hot (user rule, 2026-07-11)

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
   EVERYWHERE it appears (CURRENT-STATE, STANDING-KNOWLEDGE, RECURRENCE, session file) — a
   survived stale line re-litigates itself next boot.
7. **What almost broke, and why didn't it?** Near-misses are the purest tacit knowledge — no
   log records the disaster that was narrowly avoided.
8. **What cross-task connections or seams did I notice that aren't recorded anywhere?** Seams
   are this role's core value; the ones that didn't force an action yet are exactly the ones
   that evaporate.
9. **What would I do differently if starting over?** This question GENERATES step 4's
   process-evolution proposals — answer it before you get there.
10. **What would I be furious at a successor for not knowing?**

## 2. Make the state true

Rewrite `CURRENT-STATE.md` from verified current reality; audit the other ledgers below:

- **CURRENT-STATE.md** — as-of line current; In flight / candidates / Watch reflect reality;
  closed items struck (`~~…~~` with a one-line verdict), not silently deleted. No session digest —
  the session file boundary does that job. Respect the ~80-line budget: every line a pointer to
  verify, not a fact. **Apply the tier test at the rewrite**: a line that is KNOWLEDGE rather
  than resume state (a gotcha, a mechanism, a standing fact) goes to its trigger-point home, to
  STANDING-KNOWLEDGE by promotion, or to RECURRENCE as a counter — never rides the rewrite.
  CURRENT-STATE is not the overflow home for knowledge that lacks one. Any
  `## Outside-session` block at the top is folded into the body here and removed.
- **Session file** — entries were appended as events landed; add nothing at close except what
  step 1 surfaced that belongs to the journey (an overturned call, a ruling). No summary rewrite.
  Then **reread it once and CUT the three spent categories**: post-ship evidence (SHAs beyond the
  squash, test counts, teardown confirmations — the PR and task-review own it), per-phase build
  narration (the task's progress-log owns it, and it merges with the code), and launch-packet
  enumerations (they die with the task). The next orchestrators read this file in full — deletion
  of spent narration, never a digest. What survives: rulings and their reasoning,
  corrections/overturns, cross-task seams, escalations, and the user's own words.
- **Trackers** — task spec Status lines and spec decision ledgers were
  reconciled at each ship; spot-check the ones this session moved.
- **DECISIONS.md** — every settled-decision-grade user ruling from this session has a row
  (same-breath rule); if one is missing, that's a discipline failure to note AND fix.

## 3. Reconcile RECURRENCE.md (mechanical, never optional)

Walk this session's incidents, overturned calls, and observations against the ledger and apply
its header's exit ramps — increment / add / decay / propose, including the `→ wait n=3` marker.
**The header owns the mechanics AND the entry bar; do not re-derive them here** (the bar: a
plausible recurrence mechanism AND recognition-would-change-something — never merely that it
happened). Substance stays in the session braindump (step 6); the ledger holds only the counter
+ pointer. The exit ramps are what keep the ledger from becoming a second braindump — apply them
every close, mechanically.

## 4. Promotions + process evolution (never silent; self-applied only below the bar)

**Small edits at importance ≤2 — adding or modifying a sentence or clause — are APPLIED here, not
proposed (DECISIONS #25), and the session log names each one.** Everything above that bar goes to
the user with a recommendation: a 3+/5 call, a rule changing what a role may DO (routing, gates,
authority, destructive-op boundaries), a deletion of standing guidance, or a multi-paragraph
rewrite. After editing any `.claude/` asset, run the mirror sync:
`uv run python scripts/sync_claude_assets.py --write`.

Take the rest to the user, with a recommendation each:

- **`→ PROPOSED` ledger entries and any severity-override n=1**: propose the durable home per
  RECURRENCE.md's promotion ramp (trigger-point homes — a skill or agent def read at the moment
  of use — always preferred when one exists). On ruling, write the rule at its home and apply the
  ramp's disposition.
- **Process evolution**: if the session changed how this role operates — a new failure mode, a
  mechanism worth standardizing, a rule the user stated — edit `start-orchestration` or
  `ORCHESTRATION.md` directly when it clears #25's bar (≤2 and sentence-sized, logged);
  otherwise propose it and let the user rule.

**STANDING-KNOWLEDGE.md hygiene rides this step.** It only ever holds the user model, recurred
patterns with their tells, and standing gotchas with no trigger-point home; it must SHRINK as
knowledge becomes durable elsewhere. Line by line, on PROOF, not impression:

- **Migrated** — it now lives in ORCHESTRATION / DECISIONS / a skill / the code. *Proof: open the
  destination and confirm it says so.* Delete.
- **Resolved** — a marked `ASSUMPTION:` / `UNCLEAR:` / `ASKED-NOT-ANSWERED:` that got answered,
  or a sharp edge fixed at its source. *Proof: the answer, or the fix.* Delete.
- **HARMFUL — the sharpest category and the easiest to miss.** A line that is false, or
  true-but-scoped-so-narrowly that it models the wrong thing. It reads as helpful for exactly as
  long as nobody tests it. *Proof: check it against the SYSTEM, never against your memory of
  writing it.* Delete or rewrite in place — never leave an old bad habit standing next to its
  correction.
- **Restatement** — the same lesson stated elsewhere in the file. **Merge, don't delete**: where
  two lines share a lesson and differ in the TELL (what made it detectable), the tells are the
  transferable part and both survive as sub-bullets.
- **The downward exit** — an entry that turns out to be a single-instance process observation
  (no recurrence, no ruling, not an environmental fact) is DEMOTED to a `RECURRENCE.md` counter
  line; the substance stays findable via the session log and INDEX. This is how content that
  entered under the older, ungated bar drains out instead of squatting as precedent.

Additions go into the section that owns the theme, tagged `(sNN)`, as `trigger → action; why:
mechanism` — never a dated section, never a line beside one that says the same thing (prefer
EDITING the existing line). **The proof bar is deliberately ASYMMETRIC.** Cutting a restatement is
cheap and git-recoverable; cutting a DISTINCT lesson loses tacit knowledge nobody can
reconstruct — and merged lessons look exactly like restatements until you check. So merge freely,
delete a lesson only with proof of its durable home, and **after any large cut, verify what
actually survived instead of trusting your intent**: extract the user quotations from the
pre-edit copy and grep the new file for each, whitespace-normalized — quotes wrap across lines,
and a naive line-based grep reports losses that never happened.

## 5. Append the session's INDEX entry

One routing-grade entry (1–3 lines) to `sessions/INDEX.md`: what shipped (task/PR/issue numbers),
what was ruled (DECISIONS numbers), major arcs/incidents, and a "Read for:" clause. Enough for a
future agent to decide WHETHER to read this session — never a summary.

## 6. Write the session braindump (the LAST content step)

Append a `## Braindump` section to your own `sessions/session-NN.md`. It comes last
deliberately: your context window is ending, and this is the capture of what only it holds. It
is read for free by the next three boots, then stays findable via INDEX.md. This is a knowledge
transfer to yourself, returning with no memory.

**What belongs** (from step 1's retrospective): the user's mental model in their exact words this
session — phrasing for key concepts, sensitivities observed (what they hard-stopped, what they
waved through), the direction their trust/rules are moving; overturned diagnoses with the lesson
shape, owned plainly; mechanisms that worked, specific enough to reuse; dead ends with the exact
reason; local-only artifacts a successor cannot discover (gitignored briefs in `scratchpads/`,
machine state, unpushed commits, pending external steps) — with where they live and what to do
if missing; promotion nominations you already raised in step 4; markers — `UNCLEAR:` ·
`ASSUMPTION:` · `ASKED-NOT-ANSWERED:` · `NEEDS VERIFICATION:` — explicit uncertainty beats
implied confidence.

**What does NOT belong**: what shipped, task status, PR numbers, board state (CURRENT-STATE /
the session log's own entries / reviews own those); process rules and rulings (link, never
restate); generic advice; anything re-derivable from the repo. The test: "could the next agent
find this by reading files?" If yes — skip it.

**No quota, no floor.** Nothing here repeats what exists anywhere else — and a session that left
no genuine residue writes `## Braindump — nothing beyond the log` and stops. Padding is worse
than absence: length is earned by content (rarely ~200 lines, often ~30, sometimes 0). This
section is tacit residue, not a digest — the role prompt's "no session-end digest" rule is about
summarizing the session's events, which this must not do.

## 7. Boot-readiness and handoff

- **Boot-readiness check, the final gate:** re-read your last state as a cold successor would —
  ORCHESTRATION + DECISIONS → CURRENT-STATE → this session file (braindump included) → the
  previous three sessions' braindumps → STANDING-KNOWLEDGE → RECURRENCE. If acting correctly
  would require a fact that exists only in your head, it isn't written yet; go back to step 6.
- **Measure the boot set and print the total in your closing message** — `./scripts/tasks --boot`.
  It prints a per-file lines/bytes/est-tokens table and a TOTAL, and caps nothing: the judgement
  is yours, not a threshold's. Name the file that grew most since the last close. A total that
  climbs two closes running is a finding for step 4, not a shrug. The same command lints the
  newest session log for bare SHAs, and THAT can fail.
- Session close does not authorize a commit. Report the exact uncommitted files; any commit or
  push follows DECISIONS #5.
- Tell the user the session is closed and what the successor will pick up first.
