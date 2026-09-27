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
- Windows CI installs GNU Make via Chocolatey with no retry/cache (`main.yml`, the
  `tests-windows` job); a feed outage reads as a red gate. Top-10% fix = take the feed off the
  critical path — gated on the flake recurring | s06, s07 | n=1
- a mid-session USER edit to a tracked file read as a subagent overstepping its brief and was
  reverted without asking (the searcher's `effort` value) — an uncommitted change with no author
  is indistinguishable from a leaf's; ask before reverting anything you did not make | s07 | n=1
