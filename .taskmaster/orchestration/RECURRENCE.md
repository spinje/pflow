# RECURRENCE — the counting ledger

_One job: recognize recurrence whose period exceeds the read window of the last few sessions'
braindumps. Read IN FULL at boot (bounded small by construction); written ONLY at session close.
Entries are counters with pointers — the substance lives in the pointed-at sessions' logs (their
`## Braindump` sections from session 08 on; plain log entries or `STANDING-KNOWLEDGE.md` before
that), routed via `sessions/INDEX.md`. Never write substance here._

_Format: `- <one recognizable entry> | sNN[, sNN…] | n=K` (append `→ PROPOSED` at threshold). One
entry is one bullet, but it may wrap across indented continuation lines (two spaces, ≤100
characters each) — the `| sNN | n=K` tail may land on a continuation line._

**Entry bar — having happened is not enough.** Two write-time tests, both required: (1) a
**plausible mechanism for recurrence** — a standing condition or shared cause, not a coincidence;
(2) **recognizing the repeat would CHANGE something** — a rule gets proposed, a tool fixed, a
signal distrusted. An incident failing either belongs in its session's braindump only. Decay
mops up honest misjudgments; this bar exists for the write-time no.

**Exit ramps — MECHANICAL close steps, never optional** (if these become optional, this file is
the old braindump growing back):

- **Promotion:** at n=2 the entry is marked `→ PROPOSED` and taken to the user (STANDING-KNOWLEDGE
  entry, DECISIONS row, role-prompt fold, or trigger-point home — a skill or agent def read at the
  moment of use, always preferred when one exists) **with a per-entry recommendation — promote
  now, or wait for n=3 — judged by the entry's TYPE**: a sharp behavioral/process pattern earns
  promotion at two; a noisy environmental observation earns a third look. On approval, the line
  is DELETED — the destination is the record. On a "wait for a third" ruling, replace the marker
  with `→ wait n=3 (sNN)` — it is not re-proposed until the count grows.
- **Decay:** ANY un-promoted entry (whatever its count) last-seen more than 20 sessions ago →
  DELETED at close (git history is the archive). The 20 is inherited from a sibling programme's
  measured recurrence gaps (DECISIONS #19: imported-not-earned) — re-measure here once the
  ledger has history of its own.
- **Severity override:** an n=1 whose second occurrence would be expensive or irreversible may be
  proposed for promotion immediately — a visible call, ratified at close.

**Close reconciliation:** walk this session's incidents/observations against the list — increment
matches (append your sNN), add genuinely new n=1 one-liners, apply decay, propose threshold-hits.
**Counters are evidence-governed:** a line refuted by verification is deleted at close with the
proof.

---

- "pflow searcher" is ambiguous in packets and prose — `pflow-codebase-searcher` (the NATIVE
  Agent-tool default) vs the codex SEARCHER OFFLOAD (`workflows/search/run-searcher.pflow.md`);
  say "native searcher" / "searcher offload". Rename of the agent considered and held (churn
  across many files). Flip condition: an agent launches the wrong channel, or the user trips on
  it again | s07 | n=1
- a mid-session USER edit to a tracked file read as a subagent overstepping its brief and was
  reverted without asking (the searcher's `effort` value) — an uncommitted change with no author
  is indistinguishable from a leaf's; ask before reverting anything you did not make | s07 | n=1
- host load from many parallel agents on one machine (lanes + lenses + planner; load average
  140–217 measured) makes timing-benchmark tests flake (`test_real_compilation_performance…`
  203 ms/200, another 166/150) and produced one unidentified first-run `make test` failure —
  recognition would cap concurrent local lanes or exempt benchmarks under load | s08 | n=1
- a lane squash-merged after `origin/main` moved past its last merge-of-main without
  re-gating (CI on the push to main caught it green) — the lane def's merged-result gate runs
  before the PR, not again before the merge click; recognition would add "re-check origin/main
  right before merging; if it moved, repeat the gate" | s08 | n=1
- a durable doc carried a mechanism written from a SUMMARY instead of the cited code — s08 ADR-0015 ("prose
  interpolator"), s09 Task 170 spec freeze line, s10 ADR-0016 ("the code body is literal Python" — it is
  templated; the guide line is an authoring rule); each caught by a context-free review; recognition
  would make "read the cited function before writing its mechanism into an ADR/spec" a checklist line
  in ADR-FORMAT.md's review rule and the create-task skill | s08, s09, s10 | n=3 → PROPOSED (promote now)
- a lane ran `git stash push`/`pop` in a worktree and popped the USER's shared `stash@{0}` (Task 125 WIP) —
  stashes are repo-wide across worktrees; recognition would add "never `git stash`" to every implementing
  role's def (packets carried it ad hoc after; no repeat in s10 under the packet line) | s09 | n=1 → PROPOSED
  (severity override)
- a reviewer or lane killed a process by NAME (`pkill -f`) — s09 falsifier (`sleep`), s10 falsifier
  (`sleep 30`, machine-wide), s10 lanes #678 and #627 (their own backgrounded `gh pr checks` pollers);
  mechanism: a backgrounded poller/sleeper the agent then has to stop; APPLIED at s10 close — PID-only +
  "never background a poller you will need to kill" written into `review-falsifier.md` and
  `lane-implementer.md` (trigger-point homes) | s09, s10 | n=4 → promoted (defs edited; ratify or revert)
- ~~I proposed an interim without stating the final shape~~ — s09 UI approve-all button; s10 template
  tolerance (option 2) for shell/code bodies that option 4 then deletes — user: *"isnt the real fix to do
  4?"*; APPLIED at s10 close as a role-prompt sentence (start-orchestration "Working with the user") |
  s09, s10 | n=2 → promoted (ratify or revert)
- an issue AUDIT judged "still open" from the body alone while an owner COMMENT on the issue said the
  symptom was fixed (#437 → PR #519) — the brief said read bodies; recognition would make "every issue
  read is TWO calls, body + `--comments`" (already the planner rule) the rule for every agent that
  classifies issues | s10 | n=1
- `gh run list --branch main` returned stale/unrelated runs while the real push run existed (s08 misread
  "no push CI"; s10 saw September runs for today's commit) — APPLIED at s10 close as a STANDING-KNOWLEDGE
  §6 line | s08, s10 | n=2 → promoted (ratify or revert)
- a task orchestrator ran two phase implementers IN PARALLEL in one worktree (179: P3 + P4) to shorten a
  checkpoint wait, against ORCHESTRATION step 2; the predicted side effect occurred (one implementer's
  `make check` regenerated the other's `.agents/` copy), no damage; recognition would add the rule to
  `task-orchestrator.md` where the agent-assignment choice is made | s10 | n=1
- the main orchestrator edited MAIN's copy of a task spec while a live branch owned that spec (179 #690
  note) → the post-merge `git merge --ff-only origin/main` aborted on the local change; the branch already
  carried the note. Recognition: once a task's worktree exists, its spec is edited ONLY on the branch
  (or relayed to the producer) | s10 | n=1
- `pflow-codebase-searcher` agents REFUSE to write report files (their def forbids it) while the orchestrator's
  brief asked for one — four briefs in s10 asked, four returned inline; recognition: briefs to searchers ask
  for an inline report, never a file | s10 | n=1
- the main orchestrator's claim "F1 string→dict is Task 120's problem" was written into the Task 120 spec
  from the dogfood summary and refuted by the verifier (mis-coercion at template resolution, #686) — same
  family as the n=3 entry above but for a SPEC EVIDENCE block written from a producer's summary before the
  verification pass | s10 | n=1
