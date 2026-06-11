# Braindump: Task 170 — the session that produced the spec, ADR-0006, and the plan

Written by the agent that ran the architecture review, the design exploration, and the plan
authoring (2026-06-11). Everything procedural is in
`implementation/implementation-plan.md` — this captures what is NOT written down.

## Where I Am

Plan approved by the user in plan mode, copied to
`.taskmaster/tasks/task_170/implementation/implementation-plan.md`. Zero implementation has
happened. ADR-0006 and the CONTEXT.md vocabulary (Template/Reference/Coalesce/Operand)
already landed on branch `chore/audit-followup-hardening` (uncommitted as of this writing —
check `git status` before assuming they're committed).

## User's Mental Model — use their words

- The whole task came from "find the biggest win possible" (architecture review). Candidate 2
  (planner/engine parity) lost to this only on evidence-vs-cost; the user cares about
  **leverage**, not completeness.
- The directive that shaped every design decision, verbatim: *"We should prioritize
  simplicity of the FINAL code, not how easy it is to get there. When in doubt we should ask
  ourselves whats the right solution that the top 10% of codebases similar to this one would
  implement, have we considered it yet?"* — and the qualifier: *"this is about more simple
  code that is optimized for AI agents to understand and add features to"*, explicitly NOT
  about impressing anyone with architecture.
- Their closing priority, verbatim: *"the important thing is that we move in the right
  direction and can extend later and that this will be high leverage for stopping bugs and
  making the code more extendable and understandable for ai agents like you."* Translation I
  operated under: **if forced to trade, choose drift-bug prevention and agent legibility over
  scope completeness; stopping after an early phase is an acceptable outcome, shipping a
  clever abstraction is not.**
- Process preferences they stated: phases, NOT separate PRs ("we dont need to split it into
  prs but it should be split into PHASES"); task spec is what/why only, plan owns the how;
  use `pflow-codebase-searcher` subagents for verification, **never Explore** (they repeated
  this — it's also in CLAUDE.md).
- They grilled the "9 files → 1 edit site" claim and I conceded it was an overclaim. The
  honest framing we settled on, which they accepted: **the win is that forgetting a consumer
  becomes loud instead of silent**, not that edit counts drop to one. If you find yourself
  justifying work by edit-count arithmetic, you're off their map.

## Design genealogy the ADR doesn't capture

Four competing interface designs were produced by parallel forks: A (minimal 3-entry-point),
B (two-world ports & adapters with HIT/MISS/UNKNOWABLE), C (evolve-in-place staging),
D (AST-as-interface). The final shape = D's AST + A's interface discipline + C's sequencing,
with B **rejected entirely**. ADR-0006 records the rejection, but the argument that actually
killed B — useful if anyone re-proposes sharing the walk: B's headline claim was
"type-forced correspondence" (a new runtime capability forces a validator-side stance via
the type system). We debunked it: a new behavior lands in one adapter's *body*; nothing in
the types forces the other adapter to react. The drift protection was always coming from the
shared AST + parity tests, which the chosen design keeps. Also: CEL (checker/interpreter),
actionlint, and JMESPath were the "top 10%" precedents — all share the AST and conformance
tests, none share the walk.

C's lasting contribution: tests land BEFORE production changes, and it corrected two of my
own claims (the "private reaches" actually *import* the attribute, so they auto-sync; the
double-walk is worse than I'd said — `_resolve_complex_match` pays it too).

## Hard-won knowledge / things that surprised me

- **Reviewers who EXECUTED code beat reviewers who read code.** Five review agents ran over
  the plan (1 structural + 4 lenses). The highest-value findings came from live execution:
  my DynamicIndex "leaves text unchanged" description was flat wrong (2 of 3 failure modes
  partially SUBSTITUTE text and pass through silently); `${first.stdout.}` is silent at
  every layer today. **When you hit a behavior question during implementation, run the
  resolver in a REPL — do not reason from the regexes.** Several "obvious" descriptions in
  earlier drafts were wrong.
- Three of the six historical regression tests as originally specced would have been green
  with their bugs reverted (test_460 wrong code path, test_d5a1af8c wrong validator,
  test_8535ed9b wrong commit — it's 4516cd72). The plan now has the corrections, but the
  meta-lesson stands: **for each 1c test, first revert-check mentally: "would this fail if
  the fix were undone?"**
- The `resolvable: bool` two-tier rule on Expr (permissive-shaped acceptance, strict
  resolvability) is MY synthesis to resolve a real conflict found late (the permissive∖strict
  grammar gap: `${a..b}` must stay a pass-5 path error, not become a malformed error). It is
  specified in the plan but was never prototyped. NEEDS VERIFICATION: that the
  empty-segment-dropping rule reproduces `split_template_path` exactly for the gap shapes —
  the phase-1 corpus rows are the arbiter.
- Counts drifted between searcher passes (33 vs 28 importer files, 16 vs 15 core files).
  The plan now says "trust the grep, not the count" — take that seriously.

## Assumptions & Uncertainties

- ASSUMPTION: implementation happens on a fresh branch off `main`, not on
  `chore/audit-followup-hardening`. The ADR/CONTEXT/spec/plan files in the task folder need
  to ride along (they may still be uncommitted — verify, and ask the user where to commit
  them if unclear; remember the project rule: NEVER commit without explicit instruction).
- ASSUMPTION (unconfirmed by user): `lru_cache(maxsize=4096)` is fine because workflows hold
  a few dozen distinct template strings. Never measured. Don't optimize; just don't shrink it.
- UNCLEAR: whether the user wants the root `CLAUDE.md` updated (Task 170 isn't in its
  roadmap list, and the list still carries the stale Task 133 "Unified Per-Node Storage"
  title — flagged twice in the session, never fixed). Surface it at the end, don't do it
  unprompted mid-task.
- NEEDS VERIFICATION at phase 4: the cache_analysis tests monkeypatch
  `TemplateResolver.resolve_template` as a CLASS attribute (3 sites, listed in the plan).
  The facade reimplementation must keep those methods as the genuine call path for the
  analysis stack, or the monkeypatches silently stop intercepting (the patch would hit a
  method nothing calls). Check this when reimplementing the facade.

## Unexplored Territory

- UNEXPLORED: `architecture/reference/template-variables.md` (922+ lines) likely documents
  template behaviors with examples nobody cross-checked against the phase-1 corpus. Cheap
  win: skim it while building the corpus; it may contain documented edge cases the session
  never surfaced — and it needs path updates in phase 3 anyway.
- CONSIDER: the corpus rows that pin "silent garbage pass-through" (dynamic-index case 1,
  trailing-dot) are pinning behavior that is arguably BAD. The user never saw those
  specific cases. If during implementation one feels intolerable to pin, that's a legitimate
  stop-and-ask — frame it as "pin or sanctioned delta #N", same mechanism the plan already
  uses for the scope.py/escaped-visibility deltas.
- MIGHT MATTER: `make check` runs ruff/mypy — the new module is the first heavily
  frozen-dataclass + pattern-matching code in `core/`; if the repo's Python floor (3.10)
  matters for `match` exhaustiveness checking via mypy, verify early rather than after
  writing all interpreters.

## What I'd Tell Myself

- Phase 1 is the whole ballgame. Budget real care there; everything after is mechanical
  BECAUSE phase 1 is good. If a corpus row's expected value surprises you, that's signal,
  not friction.
- Resist every "while I'm here" improvement. The plan's accepted-survivors list and the
  do-NOT-touch pair-caller list exist because reviewers kept (correctly) finding adjacent
  mess — the user explicitly scoped it out. The sanctioned deltas are enumerated; the count
  is closed. Anything new = stop and surface.
- The guardrail hierarchy when instructions seem to conflict: phase-1 corpus > "TODAY WINS"
  > plan prose. The plan was edited many times by review findings; if two sentences disagree,
  the corpus + the verified truth tables win, and the conflict is worth reporting back.

## Relevant Files & References

- `implementation/implementation-plan.md` — THE document; read fully before anything.
- `task-170.md`, `context/adr/0006-template-language-no-shared-walk.md`,
  `context/CONTEXT.md` (new terms near the Retry cluster).
- Review idioms to mirror: `tests/test_execution/test_plan_drift.py` (mutation docstrings),
  `tests/test_core/test_litellm_runtime.py:837-920` (AST scan),
  `tests/test_runtime/test_template_validation/test_validator.py:12-127` (mock registry).
- The session's architecture review HTML lived in $TMPDIR — ephemeral, nothing load-bearing
  in it that isn't in the task spec.

## For the Next Agent

Start by reading the plan end-to-end, then `template_resolver.py` end-to-end (884 lines),
THEN write the phase-1 corpus — in that order. Don't parallelize phase 1 across subagents;
the corpus's value is one mind holding all the edge cases at once. Use
`pflow-codebase-searcher` (never Explore) for verification questions, `test-writer-fixer`
for test-file authoring with the corpus handed over as data, `code-implementer` only for
the mechanical phases (3, parts of 5). The user reads progress through behavior: show
expected before/after output when a decision point arises, per CLAUDE.md.

> **Note to next agent**: Read this document fully before taking any action. When ready,
> confirm you've read and understood by summarizing the key points, then state you're ready
> to proceed.
