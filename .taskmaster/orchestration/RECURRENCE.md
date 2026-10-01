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
- a subagent-authored durable doc (ADR-0015) carried a mechanism that did not exist (a "prose
  interpolator") because I wrote it from a lens's summary instead of the code — the context-free
  ADR review caught it; recognition would make "read the cited function before writing its
  mechanism into an ADR/spec" a checklist line. s09: the Task 170 spec's "prose-wrap: recorded, not
  fixed" freeze line (written from a battery summary, before the plan) was contradicted by the plan's own
  normalizer | s08, s09 | n=2 → PROPOSED
- a lane ran `git stash push`/`pop` in a worktree and popped the USER's shared `stash@{0}` (Task 125 WIP) —
  stashes are repo-wide across worktrees; recognition would add "never `git stash`" to every implementing
  role's def (packets carried it ad hoc after) | s09 | n=1 → PROPOSED (severity override)
- a falsifier cleaned up its probe with `pkill -x sleep -f` (kill by NAME) — can kill the user's unrelated
  processes; ORCHESTRATION already scopes dev-server kills to owned PIDs, the falsifier def doesn't |
  s09 | n=1 → PROPOSED (severity override)
- I proposed an interim (UI approve-all button) without stating the final shape or whether the interim
  survives into it — the user asked "why are we not doing the real fix?"; recognition would make
  "final shape is X; this interim is/isn't part of it" a required line in any interim proposal | s09 | n=1
