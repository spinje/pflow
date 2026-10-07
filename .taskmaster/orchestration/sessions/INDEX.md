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
- **session-09** (2026-09-29 → 10-01) — SHIPPED Task 170 (one template language, PR #673) and Task 94 (`settings llm models`, PR #670); lane B #617 #618 #615 #606 #654 #652 #643 #658 #657 #650. User's final-code lens put verbatim into root CLAUDE.md; lane gates bound to the deep-review rubric (falsifier). Specs Task 178 (MCP SDK 2.x) + Task 179 (durable loop position, overturns Task 164 restart-at-1). First end-to-end scope GRANT with commit authority. Read for: the lens and how it flipped recommendations; the "real fix" correction; stdio reservation seam (#652/#657 → 178); in-grant escalation handling.
- **session-10** (2026-10-05 → 10-06) — SHIPPED Task 179 (durable loop position, PR #713, trace 2.8.0, lossy-seed refusal) and lanes #678 (#704), #521+#389 (#705), #627 (#707 `NodeError` ratchet). First full open-issue audit (143) + a fresh-eyes DOGFOOD pass (17 issues, ~$0) + KEEP-biased triage (15 closed); 26 issues filed (#684–#712). Deep-review skill rewritten with the user: triggers not size, floors, per-seam targets, spec mode, standing dogfood. Task 118 ruled (shell bodies untemplated, `env:` binding — ADR-0016, context-free-reviewed and corrected); Task 111 demoted; 120 promoted; 99/121 "spec rewrite required". Second end-to-end GRANT. Read for: the interim-without-final-shape correction (n=2 → role prompt); fail-closed preconditions stopping a guess (the 4th lossy transformation); "the code body is literal" refuted; kill-by-name n=4 → defs; the GitHub Actions outage day; what the user did NOT answer (release ×3).
- **session-11** (2026-10-06 → 10-07) — SHIPPED Task 118 Part 1 (`env:` binding channel, PR #723) and lanes #696+#697 (#715), #714 (#718), #690 no-format half (#719, Refs). Task 118 spec rewritten from an 8-lens SPEC battery + two context-free re-reads; 118 split → new Tasks 181 (MCP code params, `${x|json}` — rule tightened: bare `${…}` always JS) and 182 (linting); new 180 (resume step identity, governed by #690) and 183 (loop gates "of up to M" + approve-all); 120 rewritten from an executed investigation (13 breaks, 7 user decisions). Four planners run (118 Fable, 180 Fable, 181/183 Opus by capacity grant); three plans parked on user checkpoints. Third end-to-end GRANT; main orchestrator swapped Fable → Opus mid-session. Read for: the spec-battery-then-reread pattern; `set -u` rejected on evidence; fail-closed preconditions stopping #690 twice (batched host has no `node.start`); "of M" refuted (no loop is fixed-count); collapsed checkpoints under a grant.
