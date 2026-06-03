# Braindump: Task 163 harness — for the agent who implements it

I designed task 163 with the user across one long session. The **what/why/decisions** are in
`task-163.md`; the **process/ledger/precursor lessons** are in `../implementation/progress-log.md`. This file is
ONLY the tacit stuff — how the user thinks, what nearly went wrong, what's still genuinely open.
Don't expect requirements here; read those two files first.

## Where I am

Spec is written (`task-163.md`, 395 lines), reviewed against verified source facts, untracked
(not committed — user commits, never you). Next step per the user is "exact implementation
details" — i.e. an implementation plan. The design is locked; no decision is still being debated
*except* the small implementation-time verifications listed under Open Threads.

## User's mental model (their words — use them, not synonyms)

- The north star, verbatim: **"the perfect agentic coding workflow harness … automate my process
  for taking an implementation plan and coding it end to end … reviewing and fixing the plan,
  managing context window during planning phases, review at different stages using many parallel
  subagents."** Everything serves *automating THEIR process*, not a generic one.
- **"checkpoint"** = the agent reads the plan + creates the task list, then **STOPS before
  implementing**. Forks resume from this point. This word is load-bearing — it's their term.
- **"wait for human review"** in their manual prompts is a **steering device** (make the agent
  stop + raise quality knowing it'll be scrutinized), NOT a request for human gates. They said
  this explicitly. Don't build HITL.
- **"Are you FULLY happy with the implementation? Any loose ends?"** — their actual follow-up
  prompt. It's a *self-review* that catches a different class than external review. It's in the
  spec as the implement-fork's final step. Keep the phrasing.
- On reviews: **"reviews NEEDS to be done by agents (subagents invoked by a main agent that uses
  checkpoint)."** Capitalized NEEDS in their message. This killed the prompt-caching option (cache
  is llm-only) and settled the fan-out as agent-level. Don't relitigate.
- On the loop: stop on **"diminishing returns on reviews finding only non-critical findings
  (verified to be critical, not just that the reviewer says it is) or findings that are mostly
  false positives."** The adjudication ("verified to be critical, not just that the reviewer says")
  is the heart of it — findings are claims.
- They picked **fresh context per review round** with explicit reasoning: *"fixing a lot of issues
  can use a lot of context … reset and run the verification loop again … lower context window
  equals better results."* This is their core context-management instinct, stated plainly.
- **"prioritize simplicity of the FINAL code, not how easy it is to get there"** — appears in their
  start-work skill AND their manual implement prompt. This is *why* the final whole-system
  code-quality review exists (a per-chunk reviewer can't judge final-code simplicity).

## How to work with this user (this matters as much as the spec)

- **They reason from first principles and correct course constantly — and were right every time
  this session.** I was confidently wrong repeatedly (claimed code-node `raise` hard-stops — false;
  leaned on a "future multi-provider agent node" that doesn't exist; tried to make verify run first;
  proposed the implementer fixes its own review findings). Each time they pushed and were right.
  **Verify before asserting. Reason from PROPERTIES (purity, relational-vs-intrinsic, claim-vs-
  ground-truth), not CATEGORIES ("agentic", "batch is a pflow strength").** Every wrong answer I
  gave came from a category; every right one from a property.
- **They catch hand-waving.** "is it just me or…" / "what are you talking about here?" means
  they've spotted something real OR you were unclear — go verify / explain plainly, don't defend.
- They want **focused, non-bloated, honest**. They file GH issues for real gaps rather than
  gold-plating. Don't build speculative features.
- They like **decisions presented with tradeoffs + a recommendation**, then they decide. The
  AskUserQuestion / "here are options A/B, I rec A because…" cadence worked well.

## Key insights not in the other files

- **The 3-tier reuse architecture came from the user, not me.** They said the issue-swarm and the
  manual plan→code path are "just a variant of executing the same workflow." I formalized it into
  tiers, but the *insight that worktrees are a swarm-only (parallelism) concern and the core must
  be invocation-agnostic* is theirs. Optimize `execute-plan` FOR the swarm from day one (don't bake
  in single-plan assumptions) even though v1 only builds the manual entry.
- **The progress log is the spine, and the user seeds it with design/planning insights, not just
  implementation notes.** They said they "sometimes include the insights from design/planning not
  just the implementer in this progress log." So the log isn't an output log — it's the carried-
  forward *understanding* across forks. The implement prompt MUST enforce a substantive entry or
  the review-fix fork starts blind (it has only the log + `git diff`).
- **The implement-fork, review-fix-fork, and verify-fork are SIBLINGS off the same checkpoint
  baseline** — same {checkpoint, progress log}, role-differing only by a short delta prompt. The
  user described the review-fix agent as "the same checkpoint + progress log as the implementer had
  and similar prompt but it will invoke reviews and fix it instead of implementing phases." That
  symmetry is the elegant core — preserve it.
- **End-stage ordering (final review → verify → ship) has a real reason**, not just taste: the
  final code-quality review MAY refactor for simplicity, and a simplification refactor is exactly
  what silently breaks behavior → verify must run AFTER it and be the last guarantee before ship.

## Assumptions & uncertainties (resolve before/while implementing)

- **NEEDS VERIFICATION (the one I'd run first):** confirm a no-error-edge `code`-node failure yields
  a non-zero CLI exit + surfaced message. The hard-stop searcher verified the engine *walk-break*
  but NOT the engine→Runner→CLI exit-code boundary. The whole preflight depends on this. 5-line
  throwaway `.pflow.md`: a code node that raises, no `on-error` edge → check `$?` ≠ 0. If it does
  NOT exit non-zero, the preflight design needs rework.
- **NEEDS VERIFICATION:** a backward-edge / `loop:` loop whose body accumulates commits on ONE
  shared branch across iterations (each iteration depends on the prior's git writes). The precursor
  loop re-fetched fresh external state each cycle; ours instead *builds on* prior iterations. I'm
  ~80% sure it's fine (revisit clears node memo cache; git is external to the cache key) but it was
  never traced. Skeleton-trace a 2-chunk sequential build before trusting it.
- **ASSUMPTION (unconfirmed with user):** progress_log default path "next to the plan file." Their
  real example used `.taskmaster/tasks/task_N/implementation/progress-log.md`. For a generic plan
  file there's no task_N. I defaulted to "next to the plan"; confirm or let them set the input.
- **RESOLVED:** `loop:` (Task 162) is **committed and verified working** (commit `20202138`;
  live-tested 2026-06-01 — condition-terminates correctly). Use it for the review-fix loop and
  impl-loop instead of the hand-wired backward-edge worker/checker. Authoring gotchas: a `code` node
  outputs only `result`, so a body emitting a value + condition returns a dict and `while:` reads
  `${node.result.<field>}`; use engine-injected `${__iteration__}` (1-based) for the counter, not a
  self-reference to the node's prior output. The spec describes the loop behaviorally; `loop:`
  satisfies it.
- **ASSUMPTION:** the 8 `review-*.md` lens files work as claude-code subagent prompts with light/no
  adaptation. They're agent-*definitions* (frontmatter + "you are a subagent" framing). The review
  fork invokes them as subagents (Claude Task tool) — which is the user's manual pattern — so the
  framing is probably fine as-is, but check one before assuming all.

## Unexplored territory

- **UNEXPLORED: the dynamic-verify recipe is project-specific.** `pflow-sandbox-testing` (in
  `.agents/skills/`) is pflow's "write .pflow.md + run the CLI" recipe. The verify stage should take
  the recipe as an injected input so the harness isn't pflow-only — but v1 ships pflow-specific
  defaults. We didn't design the injection mechanism; it's just "a path input" for now.
- **MIGHT MATTER: cost legibility.** The user tracked every precursor run to the cent (~$1.28 total).
  A multi-stage many-subagent harness will be expensive. Build so each stage's cost is visible via
  `pflow report` / traces from the start. `max_review_rounds: 0` is the cost dial.
- **CONSIDER: the implement-fork spawning its OWN subagents.** The user's manual prompt says
  "utilize code-implementer subagents in parallel … for mechanical tasks … but always code things
  yourself that require deep context." So the implement fork is *one* claude-code node that may
  internally parallelize mechanical work via the Task tool — opaque to pflow, and that's accepted
  (same boundary call as review fan-out). Put this guidance in the implement prompt.
- **MIGHT MATTER: how chunks/phase-groups are actually sized.** `breakdown` (an `llm` node) reads the
  frozen task list and emits chunks. We didn't deeply spec the chunking heuristic — the user's
  `/plan-breakdown` skill is "optimal handoff breakpoints by size and tacit-knowledge dependency."
  The breakdown prompt should draw on that skill's logic. Whether breakdown also recommends *which*
  review lenses per chunk was raised but parked (the user said the deploying agent picks lenses, so
  I did NOT add a lens-recommendation step — don't add machinery they didn't ask for).

## What I'd tell myself starting over

1. Build the **skeleton with `code` stand-ins end-to-end first, for $0**, and trace the FULL
   multi-chunk + multi-round flow. This is the single highest-leverage habit — "validates ≠
   runnable" bit the precursor hard (a single cycle passed while the multi-cycle loop was broken).
2. **Don't template large content into claude-code prompts** — 10k cap is post-interpolation and
   fails only at runtime. Everything large goes by path. (Verified; in the spec.)
3. **Start from the user's existing prompts** (`.claude/agents/review-*.md`, the lifecycle
   commands, `pflow-sandbox-testing`), not a blank page. ~70% wiring, ~30% glue.
4. **Treat every claude-code output as a claim.** The harness chains agents; unverified claims
   compound. Adjudicate review findings; verify the verifier against git/filesystem.

## Open threads (next steps I didn't take)

- The implementation plan itself (the user's stated next step).
- The two NEEDS-VERIFICATION items above (preflight CLI exit; shared-branch sequential loop).
- The precursor example is committed (`7c50b5a1`) but **not pushed**, and lacks its README
  drift-guard test — separate from task 163, but relevant when the v1.1 swarm refactor touches it.
- An **auto-stage hook stages Writes** in this repo — watch it; unstage anything you didn't mean to
  commit (it bit the precursor session).

## Relevant files & references

- `task-163.md` — spec + verified capability facts with file:line citations (DON'T re-verify those).
- `../implementation/progress-log.md` — process, GH issue ledger, precursor lessons.
- `.taskmaster/tasks/task_161/task-review.md` + `task_162/task-review.md` — the loops/cache/`??`/
  iteration groundwork the harness stands on. Read before touching caching or loops.
- `examples/agent-orchestration/parallel-planner-review/` — the precursor; patterns to reuse +
  v1.1 refactor target. Read its `orchestrate.pflow.md` top description (it's the runbook).
- The user's prompts to wire in: `.claude/agents/review-*.md`, `.claude/skills/{plan-breakdown,
  code-review}/SKILL.md`, `.claude/commands/*.md`, `.agents/skills/pflow-sandbox-testing/SKILL.md`.
- pflow guides: `pflow guide core | claude-code | llm | batch | branching | sub-workflows`.

## For the next agent

- **Start by** reading `task-163.md` fully, then `../implementation/progress-log.md`, then this. Then build the
  skeleton ($0 code stand-ins) before any agent spend.
- **The user cares most about** faithfully automating THEIR process (checkpoint + fresh-context
  forks + progress log + adjudicated multi-lens review + adversarial verify), keeping it focused/
  honest/non-drifting, and cost legibility.
- **Don't** build HITL gates, prompt caching for reviews, a lens-recommendation step, or any
  speculative feature. Don't trust agent self-reports. Don't template large artifacts into prompts.
- **Verify everything against source/tests/runs before asserting it** — this user will catch you,
  and reasoning from properties (not categories) is how you stay right.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points, then state you're ready to proceed.
