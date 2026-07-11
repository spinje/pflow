# Task 163: Plan-to-Code Agentic Coding Workflow Harness

## Description

A pflow workflow (a tree of `.pflow.md` files) that takes an implementation plan and
drives it end-to-end to a pull request — plan hardening, context-managed implementation,
multi-lens code review, adversarial verification, and shipping — by encoding the user's
own manual plan→code process as an inspectable, deterministic graph. It is the next step
beyond the `parallel-planner-review` example: that example proved pflow's primitives
compose into agentic orchestration; this turns the *user's actual development process*
into a reusable harness.

## Status

done

## Priority

medium

> **Note on this document.** This spec is kept accurate to what is BUILT. The *why* behind each
> decision, the build journey, the bugs found, and the verified spike results live in
> `implementation/progress-log.md` (the as-built record) and `starting-context/` (the braindumps).
> This file is the current, coherent description of the harness — not a changelog.

## Problem

The user has a refined manual process for taking an implementation plan and coding it
end-to-end: read the plan (+ spec), break it into phases, implement a phase-group at a
time, run AI review with several parallel review-lens subagents, adversarially verify that
the result actually works (not just that tests pass), and fix what's found — all while
**managing the context window** so each step runs lean. Today this is driven by hand,
prompt by prompt, session by session. It is:

- **Not reusable** — the steering knowledge lives in the user's head and in scattered
  prompts; each run is re-driven manually.
- **Context-fragile** — the user manually forks fresh sessions to avoid context bloat
  during implementation; nothing enforces or automates this.
- **Not the same machine as the swarm** — the existing `parallel-planner-review` example
  has its *own* bespoke implement→review→PR body, duplicating logic that should be shared
  with the manual plan→code path.

The deeper problem the harness solves: **"validates ≠ runnable."** AI review reading code
catches a different class of issues than adversarially running the system; the user's
process deliberately uses both, and the harness must too.

## Solution

A **3-tier composition** of `.pflow.md` sub-workflows, shipped as a reference example
(like `parallel-planner-review/`). The whole harness runs on the **Claude subscription** (no
API keys) and is built skeleton-first with `code` stand-ins for $0 before any agent spend.

```
TIER 3 — entry points (thin, trigger-specific)
  run-from-plan.pflow.md      ◄── v1: the manual entry (invoke by hand with a plan)
      resolve-repo → preflight → execute-plan
  run-from-issues.pflow.md    ◄── v1.1 (not built): the "swarm" (refactor of parallel-planner-review)
      find-issues → plan-each → PER ISSUE (parallel, worktree) → execute-plan

TIER 2 — execute-plan/ : the reusable core (invocation-agnostic)
  inputs: { plan, spec?, progress_log?, repo_dir, base_branch, work_branch,
            plan_lenses, review_lenses, simplify_lens, verify_recipe?, max_review_rounds=3 }
  branch-setup → plan-review-fix → breakdown
    → IMPL-LOOP over segments (sequential, shared branch, early-exit if a segment makes 0 commits)
        └─ implement-chunk/  (implement-only; no review here)
    → REVIEW-FIX loop over the WHOLE codebase (≤ max_review_rounds; skipped when 0 — the cost dial)
    → simplify (deploy 1 simplicity lens, adjudicate, FIX; same pattern as the other review stages)
    → adversarial verify (try-to-break + fix + write regression tests)   ← last code-touching stage
    → ship (open PR)
  outputs: { pr_url, summary, segments }

TIER 1 — leaf units (each: own folder + own prompts, runnable/testable in isolation)
  implement-chunk/  (implement.prompt.md)
  execute-plan/prompts/  (plan-review-fix, breakdown, review-fix, simplify, verify, ship)
```

**The baseline + fork model (the core idea):** There is no checkpoint *node* and no
task-list artifact — "checkpoint" is a **property**: the lean baseline every stage starts
from. Each stage is a **fresh fork** (a new `claude-code` process) that re-reads
`{plan, spec, progress log}` from disk plus a short role-specific delta instruction (e.g.
"phases 1-3 are implemented & committed — implement phases 4-5, then stop"). The **plan is
read as REFERENCE** (the agent needs whole-design context); the **delta scopes the work**
("do phases A-B, then STOP") — mirroring the user's real manual prompt ("continue
implementing phase 2 only"). Git commits carry the *code* forward; the **progress log**
carries the *understanding* forward; together they are the only state bridge across forks.
The context window never accumulates — it is reset every fork. **This is how context-window
management is achieved: not by shrinking a context, but by refusing to let it grow.**

**Segmentation is for context management ONLY — not a review boundary.** The plan is broken
into segments so the *implementation* of a large plan never accumulates context; each segment
is a fresh implement fork. **Review does NOT happen per segment.** After all segments are
implemented, ONE review-fix loop runs over the whole codebase. (See "Why review runs once" in
Design Decisions.)

**Why no task list (a foot-gun removed):** an enumerated task list spanning all phases —
whether the internal TodoWrite tool or an external file — intuitively pulls an agent to
complete *all* of it, fighting the "do only your phases, then STOP" discipline. So the plan is
read as reference, never materialized into a phase-spanning checklist. The **reset breakpoints**
(which phases group into one fork) are decided by the `breakdown` step, which emits groupings
only — not a checklist.

**Prompt sourcing rule (provider/portability-aware):**
- **Orchestration** (the loops, fan-out, decomposition) → expressed as the pflow **graph**,
  not delegated to an agent. That is the pflow bet: pull orchestration out of one opaque
  agent into the inspectable graph.
- **Leaf prompts** → external `./prompts/*.md` files the harness owns.
- **Review lenses** are the target repo's own `.claude/agents/review-*.md` subagents. A review
  agent (`plan-review-fix`, `review-fix`, `simplify`) is handed the *available* lens set and
  deploys the relevant subset via the Task tool (`simplify` deploys a single simplicity lens; the
  others a relevant subset). pflow sees one node per round; that is accepted — reviews MUST be
  agents (they read surrounding code), which is the one place orchestration lives inside an agent
  rather than in the graph.

## Design Decisions

Rationale for each is expanded in `implementation/progress-log.md`; the load-bearing summary:

- **Encode the user's *own* process, not a generic one.** The harness is ~70% wiring the
  user's existing prompts (`.claude/agents/review-*.md`, the lifecycle commands) into a graph
  + ~30% glue (baseline forks, loops, preflight). Start from the existing artifacts.

- **Prompt-first, not skill-invocation.** A skill = PROMPT ⊕ INVOCATION ⊕ ORCHESTRATION. Only
  the PROMPT is portable; invocation (slash-commands / Skill tool) is Claude-specific. So:
  orchestration → graph; leaf prompts → files; runtime skill invocation → avoided (the
  review-subagent fan-out via the Task tool is the chosen exception).

- **Artifact-replay forks, NOT session-resume (empirically settled).** Each fork is a fresh
  `claude-code` process that re-reads artifacts from disk. Spike S4 proved `resume` is *linear
  continuation that mutates one growing session*, not a fork from a snapshot — so it accumulates
  context across forks (the opposite of "reset, lower context = better") and cannot return to a
  baseline. The SDK's opt-in `fork_session` flag exists but pflow doesn't expose it; adding it was
  rejected (its only gain — pre-loading the plan in context — is redundant since the plan is re-read
  from disk). Artifact-replay wins on determinism, leanness, reset-ability, and provider-neutrality.
  **No claude-code node change is needed for this task.**

- **3-tier reuse architecture.** The manual plan→code path and the swarm's per-issue execution
  are the *same machine* with different front-ends. `execute-plan` (Tier 2) is **invocation-
  agnostic** — it knows nothing about issues, worktrees, or swarms. Worktree isolation and
  issue→plan adaptation live only in the swarm entry point (Tier 3, v1.1). `repo_dir` is a
  declared input the core never resolves itself.

- **No checkpoint node, no task-list artifact.** "Checkpoint" is a *property* (the lean baseline =
  a fresh agent reading `{plan, spec, progress log}` + a phase-scoped delta), not a stage. Drift
  across forks is prevented by the delta scoping the work + the progress log carrying state — not
  by a frozen list. (An enumerated all-phases task list would pull an agent to overrun its scope.)

- **`breakdown` is a `claude-code` node.** It reads the hardened plan by path and emits ordered
  segment groupings (top-level phase titles only, by size + tacit-knowledge dependency — a
  structured distillation of the `plan-breakdown` skill; groupings, never a task list). It is
  claude-code (not `llm`) so the whole harness runs on the Claude subscription with **zero API-key /
  LiteLLM dependency** — an `llm` node needs a configured model/key and fails to compile in a clean
  env. Its `{segments}` output is consumed downstream, so `group-tick` guards the claude-code
  schema soft-fail (`isinstance(result, dict)`).

- **Plan hardening is ONE agent (`plan-review-fix`).** It deploys plan-review lenses, adjudicates
  findings, and edits the plan file in place — find-and-fix in one context, same pattern as the
  code review-fix stage. (An earlier two-stage review→fix split forced a fragile nested `findings`
  schema across an agent boundary that soft-failed; merging dissolves it.)

- **Review runs ONCE over the whole codebase, after all segments — not per-segment.** Segmentation
  is purely context-window management for *implementation*. Reviewing once over the integrated
  whole avoids re-reviewing overlapping scope and matches the user's intent. *(Deferred extension,
  designed not built: a rare foundational segment could carry a `review_after` flag from breakdown
  to trigger an early per-segment review — add when a real plan needs it.)*

- **Review-fix is a SEPARATE agent from the implementer.** Having the implementer fix its own
  review findings is circular (only works if it implemented everything correctly). The review-fix
  agent forks from the same baseline, with a role-swapped prompt: deploy lenses → adjudicate → fix.

- **The review-fix loop is pflow-wrapped, fresh context per round.** The agent does ONE round per
  invocation, writes the progress log, emits `{continue, reason}`; a `code` checker enforces
  `continue AND round < max_review_rounds`. Reasons: (1) the cap is a *real* enforced limit, not a
  soft prompt instruction; (2) each round is traced; (3) the agent's "I'm done" is a *claim pflow
  bounds*; (4) fresh context per round = lower context = better, cheaper results.

- **Findings are CLAIMS, adjudicated before action.** The review agent verifies each finding is
  real and actually critical (not just that the lens *says* so, and not a false positive) before
  fixing. The loop's normal exit is the agent's diminishing-returns judgment; the cap is a backstop.

- **Adversarial verify is a separate stage that CHANGES code.** A reviewer finds-and-reports; the
  verifier independently tries to break the system, fixes what breaks, and writes regression tests
  so it can't recur. It does NOT implement missing plan features — only hardens what was built.

- **End-stage order: review-fix → simplify → verify → ship.** Verify is the LAST code-TOUCHING
  stage. The `simplify` pass judges the simplicity/quality of the final integrated code (a thing the
  during-implementation review can't fully assess — emergent duplication across segments, an
  interface grown more complex than its use, dead scaffolding) and **fixes** what it finds, using the
  exact same pattern as the other review stages (deploy lens → adjudicate → fix → commit). Because it
  is fix-capable it runs *before* verify, so its simplifications are adversarially verified — verify
  stays the last guarantee before ship. (Superseded design: an earlier topology made this a
  *read-only* gate *after* verify. That made it the lone review stage that finds-but-can't-fix, and
  its "read-only" rested only on the prompt — `Bash` could still edit/commit. Making it a fix-capable
  single-lens review *before* verify removes both: every review stage now finds+fixes, and the
  read-only guarantee no longer needs enforcing because the stage is meant to edit. Its simplicity
  reviewer is a dedicated lens — `simplify_lens`, default `review-simplicity`.)

- **No human-in-the-loop gates; the harness runs continuously.** Task 125 (HITL pause) is unbuilt.
  The user's "wait for human review" phrasing is a *steering device* (make the agent stop + raise
  quality knowing it'll be scrutinized), not a request for mid-run approval. The harness automates
  the review the user does by hand between phases.

- **No prompt caching in v1.** Caching the shared plan/diff prefix would be the cost lever, but
  pflow prompt caching is `llm`-node-only and reviews MUST be agents → mutually exclusive. Quality
  wins; revisit if cost on large plans actually bites.

- **Artifacts pass by PATH, never by template-injected content.** The `claude-code` prompt has a
  10000-char cap applied POST-interpolation, so large content templated in counts toward the cap
  and fails at runtime. Agent prompts say "read the plan at `${plan_path}`", never inline the
  content. Only small scalars (paths, branch, delta) are templated.

- **claude-code `output_schema` only where consumed, and only flat-scalar.** Soft-fail is real:
  agentic, subagent-spawning nodes tend to end on prose and fail a requested schema. So only nodes
  whose structured output is CONSUMED downstream carry a schema, kept flat (`implement.commits_made`,
  `review-fix.continue`, `breakdown.segments`); consumers guard with `isinstance(result, dict)`.
  Review/act nodes that just edit+commit (`plan-review-fix`, `simplify`) OMIT the schema and
  report via the progress log. (If a consumed nested output is ever needed, force it via a final
  "emit ONLY the JSON" instruction or write-to-file — but prefer flat.)

- **Cost is a configurable dial.** `max_review_rounds` defaults to 3 (the safety cap) and may be 0
  to skip the whole-codebase review entirely (lean/cheap mode). Cost is inherently non-deterministic
  (breakdown picks segment count per run); a small 2-phase plan ≈ $4 / ~15-22 min, real plans more.

- **Deliverable is a reference example, not new runtime.** A composition of existing primitives,
  under `examples/agent-orchestration/`. No pflow source changes required by the harness itself
  (though three pflow bugs were found and fixed along the way — see Dependencies).

## Dependencies

No hard blockers (the harness composes existing, verified pflow primitives). Related:

- **pflow fixes made + merged while building (now on `main`):** #455→#457 (claude-code leaked an
  ambient `ANTHROPIC_API_KEY` → API billing silently overrode subscription; fixed with a
  `use_api_key` flag defaulting to subscription); #454→#456 (CLI silently dropped unknown
  `--flag value` args); #443→#459 (`--only` re-fired side-effecting upstream). The harness depends
  on #457's subscription-default behavior.
- **Task 125: Human-in-the-Loop Approval Gates** — NOT built; the harness is designed around its
  absence (continuous run, no mid-run gates).
- **Task 121: Workflow Testability (`pflow test`, mock nodes)** — NOT built; the control-flow
  regression test is hand-rolled with `code` stand-ins (the `test_loop_example.py` pattern).
- **`examples/agent-orchestration/parallel-planner-review/`** — the precursor example; its patterns
  (parallel batch, sub-workflow composition, worktree isolation, generated README) are reused, and
  it becomes the v1.1 swarm refactor target.

## Requirements

Properties the implementation must satisfy.

### Architecture & reuse
- `execute-plan` (Tier 2) MUST be invocation-agnostic: no reference to issues, worktrees, or
  swarms. Its only knowledge of "where" is the `repo_dir` input.
- `repo_dir` MUST be a declared input threaded to every agent node's `cwd:` — `cwd` is rejected on
  `workflow` nodes, so resolution happens once at the entry-point tier and is passed down.
- Each Tier-1 unit and Tier-2 core MUST be independently runnable.
- The core's input contract MUST be enforced (undeclared inputs are rejected at parse + runtime by
  pflow — rely on this; do not duplicate validation).

### Entry point & repo resolution
- `resolve-repo` MUST resolve the TARGET repo as: the explicit `repo_dir` input if given (resolving
  worktrees via `git -C <dir> rev-parse`), else the git root of cwd, else hard-stop with a clear
  message. It MUST NOT silently target pflow's launch directory. The plan's location, the target
  repo, and pflow's launch dir are three independent things.

### Baseline & forks
- There MUST be NO checkpoint node and NO task-list artifact (internal TodoWrite or external). Each
  fork is a fresh `claude-code` node that re-reads `{plan, spec, progress log}` and is scoped by a
  phase-delta instruction. The plan is read as REFERENCE, not a checklist.
- `breakdown` MUST emit phase-grouping breakpoints (top-level phase titles per segment), as
  consumed structured output — groupings only, never an actionable task list.
- Every fork MUST receive large artifacts (plan, spec, progress log, diff) **by file path** and be
  instructed to read them — never via template-injected content (10k cap is post-interpolation).
- Every code-changing agent MUST append a substantive, concise (no-fluff) progress-log entry. The
  review-fix and verify forks depend on this entry + `git diff` to know what was done (this is the
  ONLY state bridge across the reset — a thin entry leaves the next fork blind).

### Implementation loop
- Segments MUST run sequentially on one shared branch (dependent phases; segment N sees segment
  N-1's commits). NOT parallel, NOT worktree-isolated (that is a swarm-tier concern).
- A hard failure (a segment produces 0 commits) MUST early-exit the loop with a clear report of
  which segment broke; remaining dependent segments do not run, and nothing ships.
- The implement fork MUST end with a self-review step ("fully happy? loose ends?") and fix obvious
  self-evident issues before handing off.
- `implement-chunk` MUST NOT review — review is whole-codebase, once, after the loop.

### Review-fix loop (whole-codebase, once)
- Runs ONCE after all segments are implemented, over the entire change — NOT per segment.
- One review round per agent invocation; the agent emits structured `{continue, reason}`.
- A `code` checker MUST enforce `continue AND round < max_review_rounds` — a hard cap.
- `max_review_rounds == 0` MUST skip the review loop entirely (the cost dial) — routing straight to
  verify, running ZERO review rounds (not one).
- Each round MUST re-fork in fresh context, reading the progress log for prior-round state.
- The agent MUST adjudicate findings (real? critical? not false-positive?) before fixing, and exit
  on diminishing returns rather than on the cap in the normal case.
- The review agent MUST deploy lens subagents from the verified-available `review_lenses` set
  (`${repo_dir}/.claude/agents/<name>.md` — reachable only via `repo_dir`/`cwd`).

### End stages
- The `simplify` pass MUST run AFTER the review-fix loop and BEFORE verify. It deploys the
  simplicity lens (`simplify_lens`), adjudicates findings, and FIXES genuine accidental complexity
  (emergent cross-segment duplication, needless interface complexity, dead scaffolding) — the same
  deploy→adjudicate→fix→commit pattern as the other review stages. It MUST NOT add features or fix
  correctness bugs (earlier stages own those) or change external behavior — only reduce complexity.
  It runs before verify so its simplifications are verified.
- Adversarial verify MUST run after `simplify`, try to break the system, fix genuine breaks, and add
  regression tests. It MUST NOT implement missing plan features (verify/harden only). It is the LAST
  code-touching stage — nothing changes code after it, so the shipped code is the verified code.
- `ship` MUST open a PR (never merge to base directly) and surface review/verify concerns into the
  PR body. When no remote is configured it MUST report that honestly (empty `pr_url`), not fake success.

### Preflight (fail-fast, before any agent)
- A preflight `code` node MUST verify (1) every declared `plan_lenses` + `review_lenses` +
  `simplify_lens` exists as `${repo_dir}/.claude/agents/<name>.md`, and (2) the target repo's working tree is clean
  (`git status --porcelain` empty). Either failure HARD-STOPS the run with a clear message. A dirty
  tree is rejected because the harness commits to this repo; a fresh `git worktree` is the
  recommended isolation (and permits dogfooding pflow-on-pflow).
- **The hard-stop is a structural property: the preflight node MUST have NO `- on-error:` edge** — a
  raised exception in a `code` body becomes `action="error"` and only terminates the run when there
  is no error successor (otherwise it routes to a handler and the run continues as DEGRADED).
  Verified by spike S2 (no-error-edge `raise` → CLI exit 1, downstream skipped). pflow prints a
  warning *suggesting* you add `on-error`; the node's description MUST warn that the suggestion is
  wrong here.

### Inputs (workflow inputs with defaults)
- `repo_dir` (optional, default "" → git-root of cwd; the target repo) · `plan` (path) ·
  `spec` (optional, default "") · `progress_log` (optional, default `./progress-log.md`) ·
  `base_branch` (default `main`) · `work_branch` (default `agent/plan-to-code`) ·
  `plan_lenses` (default `review-plan`) · `review_lenses` (default = the repo's general code lenses)
  · `simplify_lens` (default `review-simplicity`; the single lens for the simplify pass)
  · `verify_recipe` (optional, default "" → infer) · `max_review_rounds` (default 3 = the cap;
  0 = skip the review LOOP — `simplify` and verify still run). The entry point forwards all of these
  to `execute-plan`.

## Implementation Notes

### Verified pflow capability constraints (load-bearing — established via source review + spikes)

1. **`claude-code` 10k prompt cap is POST-interpolation and runtime-only.** Resolved length counts;
   fails only at runtime (passes `validate`/save/compile/`--dry-run`). → pass artifacts by path.
   `llm` node has NO length cap. (`src/pflow/nodes/claude/claude_code.py:214-228`; resolve-then-run
   at `runtime/engine/engine.py:704-715,889-909`.)
2. **`claude-code` `output_schema` SOFT-FAILS** — on non-compliance `result` is a raw string,
   `__warnings__` is written (→ workflow DEGRADED), and it does NOT route `on-error`. Discriminator:
   `isinstance(result, str)` means failure. (`claude_code.py:987-1063`.) Empirically, lens-heavy
   agents that end on prose are the ones that soft-fail (plan-review's old nested schema; the
   lens-heavy review/act nodes) — hence "schema only where consumed, and flat" (so `simplify`, like
   `plan-review-fix`, omits a schema).
3. **`claude-code` is Claude-only.** Subscription billing is the default since #457 (`use_api_key:
   false` blanks `ANTHROPIC_API_KEY` for the subprocess). `resume:` is linear continuation, NOT a
   fork (spike S4; SDK `fork_session=False`, unexposed) → unusable for our fork model; we use
   artifact-replay. `permission_mode=bypassPermissions` always. `max_retries=2`.
   (`claude_code.py`; SDK `claude_agent_sdk/types.py:1790`.)
4. **`llm` `output_schema` = real constrained decoding** (`strict:True` via LiteLLM); reliable dict
   at `${node.response.field}`. BUT `llm` needs a configured model/API key (no subscription path) —
   which is why `breakdown` is claude-code, not llm, to keep the harness subscription-only.
   (`src/pflow/nodes/llm/llm.py`; `core/llm_client.py`.)
5. **`code` nodes are unsandboxed** (full `os`/`open`/subprocess) — preflight checks + repo
   resolution are trivially expressible. A `raise` in a `code` body is caught → `action="error"` →
   hard-stop ONLY if no error successor (see Preflight). Sandbox is unbuilt (Task 87).
   (`src/pflow/nodes/python/python_code.py`; routing in `runtime/engine/engine.py:399-489`.)
6. **Sub-workflow contract:** `ALLOWED_PARAMS = {workflow, inputs, error_action, storage_mode,
   max_depth}` (+ top-level `batch`); **`cwd` is REJECTED**; **undeclared inputs REJECTED** at parse
   + runtime (Task 153/#288); a `required: true` input passed an empty string is REJECTED (so
   optional inputs that may be "" must be `required: false, default: ""`); outputs accessed as
   `${node-id.declared-output}`; external prompts (`- prompt: ./x.md`) resolve relative to the
   **workflow file**. (`runtime/workflow_executor.py:75-81,485-508`; `core/file_resolver.py:270-284`.)
7. **There is no repo-relative path resolution.** Bare relative paths resolve against the launch cwd.
   The harness reaches `${repo_dir}/.claude/agents/review-*.md` only because `resolve-repo` computes
   an absolute `repo_dir` and every agent runs with `cwd: ${repo_dir}`. (The precursor used a
   `find-repo` shell node doing `git rev-parse` in cwd — that resolves the LAUNCH dir, which targeted
   pflow itself; this harness uses explicit `repo_dir` instead. See progress log.)
8. **Nested backward-edge loops work** across a sub-workflow boundary, inner loop resets fresh each
   outer iteration, and state accumulates correctly on a shared cwd with revisit re-executing the
   node (spikes S1/S3). The harness's segment loop + review loop rely on this.
9. **Per-item type coercion is LOST** on batch `inputs: ${item}` to a sub-workflow (#188) — a
   **swarm-tier (v1.1)** concern only; does not affect the manual path.

### Authoring gotchas (cost real retries; bake into any new node)
- In `code` nodes, EVERY type annotation declares an INPUT — locals must be unannotated
  (`keep = True`, not `keep: bool = True`).
- Output entities need a description (same as nodes), or parse fails.
- Only ONE workflow output may set `stdout: true`.
- CLI inputs are `param=value` positional (since #456, an unknown `--flag` now errors with a
  suggestion rather than being silently dropped).

### Build approach
- **Skeleton-first, $0.** Build the whole topology with `code` stand-ins (each agent swapped for a
  deterministic `code` node returning the same schema) and trace the FULL multi-segment + multi-round
  flow before any agent spend. Every Phase-3 integration run found a real bug a static check missed —
  "validates ≠ runnable" is literal here.
- **Run the harness under the REAL HOME** (subscription auth needs the macOS Keychain; the
  pflow-sandbox-testing HOME breaks it — that HOME is for pytest only) and pass `repo_dir` explicitly
  (or run from inside the target repo).

### v1 scope vs v1.1
- **v1 (this task):** Tier 1 + Tier 2 (`execute-plan`) + `run-from-plan` manual entry. Delivers the
  north star: invoke by hand with a plan (+ optional spec).
- **v1.1 (not built):** refactor `parallel-planner-review` so its per-issue body *is* `execute-plan`
  (find-issues → plan-each → per-issue worktree → execute-plan) — the proof of reuse. `execute-plan`
  was built invocation-agnostic for exactly this. The #188 coercion caveat lands at this tier.

## Verification

- **Control-flow ($0):** `tests/test_integration/test_plan_to_code_harness.py` (5 tests) reproduces
  the topology with `code` stand-ins and asserts: full-pipeline order; segments implement
  sequentially BEFORE any review (review-once, not per-segment); hard-failure early-exit-no-ship; the
  review loop honors the cap; `max_review_rounds == 0` runs ZERO review rounds (the cost dial). This
  is the CI guard against silent topology breakage.
- **Preflight:** with a declared lens missing OR a dirty working tree, the run hard-stops (CLI
  exit 1) with a clear message and does not proceed.
- **Contract:** an undeclared input to `execute-plan` is rejected at parse time; optional inputs
  (`spec`, `verify_recipe`) omit cleanly via defaults.
- **Live (small, real):** a run against a clean throwaway repo with a tiny 2-phase plan — implement
  every segment → whole-codebase review-fix → simplify (fix-capable) → verify (writes a regression
  test) → PR opened, base branch untouched, pflow untouched. Confirm the progress log
  accumulates a substantive entry per fork and that findings are adjudicated (a planted
  false-positive is dismissed; a planted real bug is fixed). **Status: the OLD per-segment topology
  passed this (run 6); the CURRENT review-once topology is pending a paid live run — see Status.**
- **Real-remote ship:** one run against a throwaway GitHub repo to exercise `gh pr create` through to
  an actual PR (not yet done — local test repos had no remote).
- **Reuse (v1.1 acceptance):** `parallel-planner-review` rewired to call `execute-plan` produces
  equivalent per-issue behavior with its bespoke implement/review body removed.

## References

- **As-built record + journey + bugs:** `implementation/progress-log.md`.
- **Tacit handoff for whoever continues:** `starting-context/braindump-implementation-handoff.md`
  (the three unfixed gaps; how to run the next live test; working style).
- **Design rationale:** `starting-context/braindump-harness-design.md`.
- **Control-flow regression test:** `tests/test_integration/test_plan_to_code_harness.py`.
- **The harness itself:** `examples/agent-orchestration/plan-to-code/` (run-from-plan + execute-plan
  + implement-chunk + prompts; generated README).
- **Precursor example (patterns + v1.1 target):** `examples/agent-orchestration/parallel-planner-review/`.
- **The user's process as reusable prompts:** `.claude/agents/review-*.md` (the lenses),
  `.claude/skills/{plan-breakdown,code-review}/SKILL.md`, `.agents/skills/pflow-sandbox-testing/SKILL.md`.
- **Groundwork tasks:** task_161 (cache defaults), task_162 (`loop:` config) reviews.
- **Key capability source files:** `src/pflow/nodes/claude/claude_code.py`,
  `src/pflow/nodes/llm/llm.py`, `src/pflow/nodes/python/python_code.py`,
  `src/pflow/runtime/workflow_executor.py`, `src/pflow/runtime/engine/engine.py`,
  `src/pflow/core/file_resolver.py`, `src/pflow/core/workflow/validator.py`.
- **pflow authoring guides:** `pflow guide core | claude-code | llm | batch | branching | sub-workflows`.
