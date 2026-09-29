# Session INDEX — routing table

_One entry per session, appended at close (a close-skill step). ROUTING-GRADE ONLY: enough for an
orchestrator or fork to decide WHICH old sessions to read for the problem at hand — never a
summary. Entry bar: 1–3 wrapped lines — ships/rulings by NUMBER, no narrative, plus one
"Read for:" clause naming the arcs that should route a reader here; anything more belongs in
the session log. Never a boot read: grep it when work touches an old arc, then read THAT session —
targeted reads replace range fork-mining. Sessions 01–07 predate the per-session `## Braindump`
(ORCHESTRATION.md "Artifacts and ownership"); their residue lives in `STANDING-KNOWLEDGE.md`.
DECISIONS numbers in entries are the rows as they stood at that session — the ledger was since
pruned to the rows that pass its bar; git history holds the removed ones._

- 01 (2026-07-11) — converted pre-restructure log (history 2026-06-16→07-11); Tasks 125/164/171/
  174/116 shipped (#554/#559/#563/#560/#564); DECISIONS #1, #6; worktree sweep; Task 176 spec
  refresh. Read for: resume/HITL arc history, trace/overlay arc, Task 176 decision ledger,
  squash-merge misread.
- 02 (2026-07-11) — nothing shipped; DECISIONS #1–#7 seeded, #8–#11; orchestration system ported.
  Read for: agent-hierarchy genesis, web-UI→Fable routing, lane-B model policy, close-ritual port.
- 03 (2026-07-12) — #565 (PR #583), #581 (PR #584), #585 (PR #586); DECISIONS #3, #12, #13; Codex
  lane-B shakedown. Read for: lane-B first live run, Codex relayed-authority boundary,
  `[skip review]` marker.
- 04 (2026-07-13) — #413 (PR #587), #497 (PR #588); #183 closed, #516 rescoped, #357 verified
  closed; DECISIONS #3 amended. Read for: #183 secret-masking step-back, standing merge authority.
- 05 (2026-07-15) — #590 (PR #596); reconciled PRs #591/#593/#595 (Task 177); DECISIONS #3, #5;
  Tasks 46/142 parked. Read for: commit-authority correction, managed-approval commit rejection,
  #592 pick.
- 06 (2026-07-15) — #592 (PR #597); DECISIONS #3 amended (the Fable/Sonnet ban, since superseded by
  #24); Task 94 spec rewrite. Read for: Chocolatey CI outage, retriable P1 regression, Task 94
  design lock, session grading.
- 07 (2026-08-14) — PR #610 (merged after close); #608/#609 filed; DECISIONS #15–#22; falsifier +
  lane-implementer landed. Read for: cross-repo fold, fresh-eyes re-audit P0–P8, merge-readiness
  lesson; outside-session tails 2026-09-21 (#615–#618 audit), 2026-09-27 (#620–#625 browser
  eval), 2026-09-27 (sibling-system comparison → DECISIONS #23–#28, `scripts/worktree`,
  the worktree `make install` trap) and 2026-09-28 (parity fold: sibling standard adopted in
  full, DECISIONS pruned to five rows, knowledge base retired → code homes + ADR 0014,
  Codex runner model → `gpt-6-astra`, #616 fixed on the PR branch; handover in
  `scratchpads/handoffs/`).
- 08 (2026-09-28) — shipped #631/#632/#633/#637/#638/#640/#641/#642/#645/#646/#647/#649 (lane B ×12:
  #620 #622-bug #623 #624 #625 #628 #629 #634 #635 #636 #639 #644-p1); filed #629 #630 #634 #635
  #636 #639 #643 #644 #648; #551 closed dup. Task 170 spec rewritten after a six-lens SPEC battery +
  ADR-0006 amendment + ADR-0015; Task 170 plan committed (first Fable-planner run), build parked;
  Task 118 → then (blocked by 170). Read for: #620 escape ruling and #630/#621/#550 deferral, the
  Task 170 spec-battery ledger, MCP stateless-standard research (#624/#644), cost-summary
  subscription labelling (#634), the worktree script's first live runs and `rm -f` semantics.
