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
- a lane squash-merged after `origin/main` moved past its last merge-of-main without
  re-gating (CI on the push to main caught it green) — the lane def's merged-result gate runs
  before the PR, not again before the merge click; recognition would add "re-check origin/main
  right before merging; if it moved, repeat the gate" (s15: #817 raced #814's merge; gate ran
  after, green) | s08, s15 | n=2 → PROPOSED (one sentence in `lane-implementer.md`'s merge step)
- an issue AUDIT judged "still open" from the body alone while an owner COMMENT on the issue said the
  symptom was fixed (#437 → PR #519) — the brief said read bodies; recognition would make "every issue
  read is TWO calls, body + `--comments`" (already the planner rule) the rule for every agent that
  classifies issues | s10 | n=1
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
- a `gh` WRITE with stderr suppressed failed silently (`gh issue comment … -q 2>/dev/null` — `-q` is not a flag; both
  comments never posted, caught only by reading them back); recognition: never suppress stderr on a write, and read
  back every external write | s12 | n=1
- `tests-windows` wall-clock flakes — distinct timing failures each green on one re-run: `test_stdin_no_hang_integration`
  and `test_cache.py::test_concurrent_access` (s12), `tests-windows-mcp-smoke` 60 s request timeout on main `f0b39c5c` and
  PR #764 (s13; #685 family); recognition: the third distinct one has now happened → file one de-flake issue for timing
  assertions on shared runners | s12, s13, s16 | n=3 → PROPOSED (file the de-flake issue; s16: `test_cache.py::test_concurrent_access`
  again on PR #863)
- I tore down a worktree whose gitignored scratch held the only evidence a producer cited (181's `*.corrupt.json`
  before-images) — recognition: before `./scripts/worktree rm`, copy any scratch path a hand-back cites into the session
  scratchpad | s13 | n=1
- an upstream issue number beside a closing keyword in a PR body ("fixes agronholm/anyio#816") parsed by GitHub as a phantom
  closing reference to THIS repo's #816 (nonexistent, no effect) — the "never place a closing keyword next to a number the PR
  must not close" trap in a cross-repo form; recognition would extend that ORCHESTRATION sentence to upstream references | s14 | n=1
- host load far above the ~40 launch ceiling with only 1 build + 3 lanes, because offload runs and verification/execution agents
  run beside them (s14 peak 86; s15 70–183) — recognition: count offload runs and verification agents toward the cap
  | s14, s15 | n=2 → PROPOSED (one sentence in ORCHESTRATION step 7)
- the user waived the lane-B `runtime/engine/` exclusion for exactly one line per launch (#799 call site s14; #755 constant s15)
  — recognition: a standing rule "a one-line engine constant/call-site may be waived per launch by the user; logic never"
  | s14, s15 | n=2 → PROPOSED (a DECISIONS row; Home ORCHESTRATION "Lanes")
- a lane's hand-back message never reached the orchestrator; only a later follow-up notification referencing "the three rulings" did
  (#811) — kin of s11's "notification before the message"; recognition: when a notification references questions not seen, ask the
  agent to restate them (done, worked) | s11, s15 | n=2 → PROPOSED (wait n=3 recommended — runner behaviour, cheap workaround)
- agents' leftovers in places the orchestrator owns: an abandoned falsifier probe shell (hung `ugrep` on stdin) blocked
  `./scripts/worktree rm`; 15 probe `.pflow.md` files written at the MAIN checkout root — recognition: packets say "kill your probe
  processes; never write outside your worktree / scratch" (the first half went into s15's last packets) | s15 | n=1
- `( … ) &` inside a `run_in_background` Bash: the child dies with the tool shell and nothing runs (three astra offloads, s16) —
  recognition: each offload is its own background Bash with the work in the foreground | s16 | n=1
- a pointer/mechanism stated to the user from a glance at one artifact, refuted by the verification it then commissioned ("the trace
  filename already carries the run id") — kin of the promoted "mechanism is a hypothesis" rule, but in user-facing recommendations,
  not issue bodies | s16 | n=1
- a lane's local gate ran `make test` (no e2e) while CI runs e2e; a merged sibling's new e2e test turned the PR red (#801) —
  recognition: packets and the lane def name `make test-all-local` | s16 | n=1 → applied in later s16 packets (fold proposed)
- review rounds overran the ≤3 bound because the falsifier was not counted and a round on new surface was treated as round 1
  (#858 ran R1–R5 + falsifier; #846 R1–R5) — DECISIONS #32 now states both | s16 | n=1
- a subagent's action blocked by the permission classifier (a lane's PR merge; a real-directory sweep) was handed up for the parent
  to perform — never performed by the parent without the user's word (laundering) | s16 | n=1
