# Braindump: planner-mirror refactor session → what it means for Task 164

Written 2026-06-12, at the end of the session that produced issue #504 / PR #505
("lift the planner's engine-mirror into shared runtime functions") and the
"Engine/planner parity plan" section now in `task-164.md`. The spec sections are
written; this captures what is NOT written anywhere.

## Where I Am

PR #505 is **OPEN, not merged** (https://github.com/spinje/pflow/pull/505, closes #504,
branch `refactor/planner-engine-shared-layer` cut from main). Task 164 work MUST start
after it merges (or rebase onto it) — it moves/renames the exact functions 164 touches
(`validate_only_target`, `route_action`, walk loop now `while curr is not None` dispatching
on `RouteKind`). The `file:line` refs in task-164.md "Reuse"/"The delta" were verified
pre-#505 and WILL be stale post-merge (caveat noted in spec, repeated here because it's
the first trap).

Also uncommitted on `chore/audit-followup-hardening` at session end: the new spec sections
in task-164.md / task-125.md, the new task-171.md (durable tokens — split from 125's durable
phase so each task is one PR), and the root CLAUDE.md roadmap reorder (build order
125 → 164 → 171). If you don't see them, they weren't committed.

## User's Mental Model (their words, load-bearing)

- **"Prioritize simplicity of the FINAL code, not how easy it is to get there. When in
  doubt ask: what's the right solution that the top 10% of codebases similar to this one
  would implement — have we considered it yet?"** Immediately followed by the guard: this
  does NOT mean overfitting to "top 10%" / overengineering — it's about **"simple code
  that is optimized for AI agents to understand and add features to."** Apply this to the
  Phase-0 helper design: the top-10% answer for "three walk modes over one graph" is
  shared *rule* functions, not a walk-mode abstraction.
- **"The bar isn't 'passing', it's 'passing the right thing'."** Said about tests. This led
  to the mutation experiment (below) — the single highest-value discovery of the session.
  The user explicitly does NOT want coverage-optimizing tests and asked me to audit my own
  tests for shallowness; they will ask you the same.
- **Tasks ship as ONE BIG PR.** Exact words: "tasks are not implemented as separate prs
  though, its all one BIG pr." So "Phase 0" in the spec = first commits/milestone *inside*
  the 164 PR, not a separate PR. (I had it wrong; user corrected.)
- **Where knowledge lives**: design reasoning/phasing → task dirs; GH issues → closeable
  problem statements **written at PR time** (user had me write #504 "as if written BEFORE
  this implementation" when the work was done). For 164's PR, expect to write the issue
  retroactively in the same style.
- User cares about **branch hygiene** (chose a clean branch off main over piggybacking) and
  wants the one-behavior-change-per-PR visible in history.

## The Mutation Experiment (do this for 164, it's the whole point)

The proof that motivated the spec's "parity test first": I re-forked the planner's batch
shape into a drifted inline literal (`errors: None` — the exact #484 regression — plus 3
dropped `batch_metadata` keys). **All 43 pre-existing batch/drift tests passed.** Only the
new call-site parity test (`test_plan_batch_sub_workflow_output_shape_matches_engine`,
in `test_plan_drift.py`, landed in #505) failed. Recipe to copy for walk-entry parity:
write test → mutate one side (re-fork) → confirm fail → revert. The test's docstring
documents the recipe and rationale — read it before writing 164's version.

Key nuance: unit tests on a shared function CANNOT catch a re-fork (they test the function,
not that callers use it). Only call-site parity tests do. Extraction A/B/D in #505 didn't
need one (both callers invoke the same function on the same path); C did (different
surrounding logic per caller). **164's walk-entry helper is a C-shaped case** — engine and
planner will wrap it differently — so it needs the call-site parity pin, not just unit tests.

## The Seam Shape I'd Start From (tacit — argued but not written down)

Three consumers of "enter the walk mid-graph": `--only` = seed + run ONE node + stop;
resume = seed + continue walking; planner `_resolve_walk_start` = seed + walk without
executing. The shared part is **seed + locate-entry only**. The *continuation policy* is
where they genuinely differ — do NOT try to share it (that's the walker-merge ADR-0001/0006
forbids). If during design the helper starts growing a `mode` parameter or callbacks,
that's the overengineering smell; back off to seed+locate.

From the probe that mapped `create_planner_shared` (findings not persisted anywhere):
the asymmetries that killed a fuller "walk environment" extraction were (1) engine does
save/restore-in-place for nested sub-workflows while the planner builds a fresh store per
child, (2) resource keys (`__trace_collector__`/`__mcp_pool__`/`__progress_callback__`)
are deliberately absent on the plan path. Resume's helper will meet the same asymmetries —
they're intentional, not accidents to "fix".

## Dead Ends / Disproven Suspicions (don't re-derive)

- **`clear_node_failure` for K is NOT needed (probably).** I suspected resume must clear
  `__failures__[K]` (get_node_status checks failures first; visit-count reset means
  `enforce_loop_guard`'s clear never fires for visit 1). Disproven: resume builds a FRESH
  shared store and seeds only upstream `node_output`s from the trace — the old run's
  failure record never enters the new store. NEEDS VERIFICATION once the resume loader
  exists: if it ever seeds failure/warning state, this comes back.
- **Cost-parity in the drift suite is a KNOWN blind spot, deliberately out of scope** of
  #505 (it pins control flow, not cost — `task_162/task-review.md:30`; the Task 162
  under-report passed the whole suite and was caught in a manual review session, NOT by
  tests). If 164 adds `--dry-run --resume`, its cost predictions inherit this blind spot.
- **`None` placeholders in batch `results` under parallel fail-fast** pass through
  `build_batch_output` verbatim (documented in its docstring) — pre-existing, deliberately
  preserved, one-line fix if ever wanted. Not 164's problem; just don't "fix" it in passing.

## Hard-Won Trivia (cost me real time)

- Hand-authoring `.pflow.md`: fences are ` ```shell command ` / ` ```yaml batch ` /
  ` ```python code ` (info string = language + param name); code nodes are module-level
  statements with annotated inputs (`n: int` on its own line) and `result: dict = ...` —
  NOT a `def run()`. Loop `while:` must be a bare `${...}` truthiness template — comparisons
  like `${x} < 3` are rejected by schema; compute the boolean inside the node.
- `echo "EXIT=$?"` after a pipe captures `tail`'s exit code. Redirect to a file instead.
- The review-agent pairing that paid off: `review-silent-failures` + `review-impact-completeness`
  on the plan caught the `--only ""` engine/planner divergence that five other verification
  passes missed. Every finding was confirmed (zero false positives). Worth repeating for
  164's plan; the `--only ""` class to look for is "the two copies already disagree on an
  edge — unification must pick one and the 'zero behavior change' claim breaks there."

## Unexplored Territory

- UNEXPLORED: **`--resume` × `--only` interaction.** Both are walk-entry modes; what does
  `pflow wf --resume --only K2` mean? Probably reject loudly, but nobody has thought about it.
- UNEXPLORED: **resume × loop nodes.** If failed node K has `loop_config`, what iteration
  does resume re-enter at? `__iteration__`/`loop_counts` are not in the trace. Likely answer:
  K restarts at iteration 1 (loop state is intentionally ephemeral) — but decide explicitly.
- CONSIDER: **memo-cache interplay is mostly free** — restored upstream means K's resolved
  params match the failed run, so K's memo lookup behaves as if mid-run. But the `--only`
  limitation transfers: sanitized (binary/dunder) upstream values change K's cache_key vs
  the live run (documented in ADR-0002 Limitations). Same caveat, new surface.
- MIGHT MATTER: **Task 170 (template language) is the sibling refactor** likely to land in
  the same window — it touches plan.py heavily. Coordinate merge order; expect conflicts in
  plan.py imports/regions if both are in flight.

## For the Next Agent

1. Confirm PR #505 merged; rebase/branch from main after it. Re-verify spec line numbers.
2. Read `task-164.md` fully — especially "Engine/planner parity plan" (the phasing) and
   "Known Hard Problems". The spec is GOOD; the grilling gap is the snapshot-fidelity
   decision (loud-caveat vs ADR-0002's dedicated-store escape hatch) — that's a USER
   decision, get it before writing the implementation plan.
3. Build order is fixed in root CLAUDE.md: 125 (blocking gates) ships first, then this task,
   then 171 (durable tokens — your substrate's second consumer; its purpose-built checkpoint
   file means your restore reader should handle two sources). Check whether 125 has shipped —
   if it landed, its gate/pause code may have touched `_execute_node` placement you care about.
4. The user will hold you to: final-code simplicity over implementation convenience,
   mutation-verified tests over green tests, and showing expected output before implementing.

> **Note to next agent**: Read this document fully before taking any action. When ready,
> confirm you've read and understood by summarizing the key points, then state you're
> ready to proceed.
