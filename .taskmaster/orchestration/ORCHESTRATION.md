# ORCHESTRATION.md — how implementation runs

Canonical process spec for implementing pflow tasks and issues via the agent hierarchy.
Established 2026-07-11 with the user (ported from the loudkult/Nora orchestration systems —
DECISIONS #1). Every orchestrating or implementing agent reads this file first. Layers ON TOP of
`CLAUDE.md` (read automatically) and repeats nothing from it — domain, dev commands, code quality,
testing directives, decision ownership, and the epistemic rules all live there.

## Roles

| Role | Model | Definition | Job |
|------|-------|-----------|-----|
| **Main orchestrator** | user's session | `/start-orchestration` command | Cross-task view: pick lane + work, verify spec freshness (fix staleness itself — spec accuracy is its job; implementation detail is not), provision the worktree, launch planners/task-orchestrators with a context packet, handle handbacks/escalations, talk to the user, **merge the PR and reconcile**, keep `CURRENT-STATE.md` + its session file + the ledgers current. **Never writes plans, never reads plans, never runs deep-review — trust the agents' gates** |
| **Task planner** | **Opus** (Claude enforces; Codex inherits runtime route) | `.claude/agents/task-planner.md` | Investigate ONE task (via searchers) IN the task's worktree + write `implementation/implementation-plan.md`, **self-review it** (plan-mode `/deep-review` — mandatory when the plan touches the engine or the trace format, its judgment otherwise), commit it on the feature branch, then STOP. May offer to implement small tasks itself (see Model routing) |
| **Task orchestrator** | Opus intent by default; Fable opt-in where the runner exposes routing | `.claude/agents/task-orchestrator.md` | One task end to end in the same worktree: (plan +) delegate phases → per-phase self-checks → when FULLY happy: code-mode `/deep-review` + apply fixes → `/create-task-review` → `/create-pr` → minimal handback |
| **Phase implementer** | per launch (routing table) | `.claude/agents/task-phase-implementer.md` | Implement exactly the assigned phase(s); tests as it goes; substance to the progress-log; minimal handback; stop on ambiguity |
| **Searcher** | pinned (opus) | `pflow-codebase-searcher` | Read-only investigation, cited findings. Never the generic `Explore` or `general-purpose` |
| **Review battery** | per lens | `.claude/agents/review-*.md` via the `/deep-review` skill | The pflow specialists (selection rubric in the skill + `REVIEW-PROTOCOL.md`). Plan gate + completion gate (see Review policy) |

**Hierarchy is exactly two levels deep**: only the main orchestrator launches planners and task
orchestrators; only those launch implementers/searchers/review agents. Implementers never spawn
agents. The planner→orchestrator split is a SEQUENCE, not a third level. **Small tasks don't
split**: one task orchestrator plans and implements (or the planner implements itself — Model
routing).

## Lanes — which procedure a piece of work gets

The main orchestrator picks the lane at pick time and states the call. When in doubt between A and
B, pick A; between A and C, ask the user.

- **Lane A — full task procedure** (the default for `.taskmaster` tasks): split shape (a
  dedicated Opus planner → Opus task orchestrator) when the task's PLANNING needs its own top-tier
  pass — hard architecture, subtle seam design, a high-complexity spec; single task-orchestrator
  that plans and implements for ordinary tasks. The shape is a stated judgment call, made visibly.
- **Lane B — GH-issue lane** (bug fixes & small self-contained tasks — DECISIONS #7): these do NOT
  become tasks. Write a GH issue if none exists (correct root cause, verified against code), then
  launch ONE subagent end to end in a provisioned worktree — a `task-orchestrator` in issue
  mode: the issue is the spec, it implements directly (no plan file, no implementers), but the
  Definition of done and UI routing (DECISIONS #8) still govern — implement → `/create-pr` with
  a `Closes #N` body → CI green → **merge it itself**. **Model by assessed complexity
  (DECISIONS #9): the main orchestrator assesses at pick time; Opus is the floor — never lower
  for an end-to-end agent; genuinely complex issues (hard debugging, subtle root cause) warrant
  Fable, but ONLY with the user's per-launch approval.** No task folder, no task-review — the
  issue and PR body are the record. The main orchestrator still provisions/tears down, relays any
  escalation, and reconciles. **Excluded regardless of size** (always lane A): anything touching
  `runtime/engine/`/`workflow_executor` or the trace format.
- **Lane C — manual lane** (kept deliberately — DECISIONS #2): the goal itself is open-ended and
  will be discovered through iteration with the user, or verification is inherently
  interactive/taste-based. The pre-restructure flow, unchanged: decision session + kickoff brief
  in `scratchpads/<subject>/`, worktree launched WITH the terminal agent (workflow defaults), the
  user guides it directly. Mechanics live in the `/start-orchestration` command. Expected to get
  rarer over time.

## Artifacts and ownership

Per task, `.taskmaster/tasks/task_N/`:

- **Spec** (`task-N.md`) — what & why; stays true if the plan is thrown away. Owned by the main
  orchestrator for freshness; a planner/task orchestrator may correct it when investigation proves
  it stale, UNLESS the correction contradicts an ADR, a `DECISIONS.md` row, or another task's spec
  (those go up).
- **Plan** (`implementation/implementation-plan.md`) — how, in phases. Written by the task planner
  or task orchestrator, **never by the main orchestrator**. Per phase: goal, files touched, every
  decision resolved (ALL of them for Sonnet-routed phases), model tier, **agent assignment**
  (Agent economics), handoff point (what is true/verified when the phase ends), the concrete
  failure scenarios the phase's tests must catch, **whether it triggers a mid-task review**
  (Review policy), and **every embedded user checkpoint flagged** so the orchestrator plans it as
  a handback. pflow specifics a plan states explicitly where applicable: engine-contact phases
  (serialization + review trigger), trace-format changes (version bump + the Task-159 baseline
  `task_159/baseline/verify.sh` as the outer regression net), platform-sensitive code (the
  blocking `tests-windows` gate; ADR-0013 governs shell semantics), and how user-facing surfaces
  get exercised (Definition of done).
- **Log** (`implementation/progress-log.md`) — append-only audit trail and crash recovery (the
  `/create-progress-log` skill scaffolds it; entry format below). Any successor reads spec →
  plan → log and knows where reality is.
- **`starting-context/`** — briefs/braindumps, newest last (tacit layer; the spec is the truth).
- **Review** (`task-review.md`) — the completion contract, below.

**Orchestration state** — `.taskmaster/orchestration/CURRENT-STATE.md` (living header, ~80-line
budget, the ONE mandatory session-start read; updated when the RESUME PICTURE changes —
launch/park/completion/ruling — the test: *would a successor resuming from a crash act differently
because of this event?*) + `sessions/session-NN.md` (the main orchestrator's per-session
append-only log; a new session creates its own file and reads the latest predecessor — **if that
file is thin** (a short check-in, an aborted session), **read one further back until you hit a
substantive one** (DECISIONS #10); older files are on-demand forensics; NO session-end digest —
the file boundary does that job; session-01 is the converted pre-restructure log).

**`BRAINDUMP.md`** — the main-orchestrator role's rolling tacit layer (user's exact words,
overturned calls, mechanisms, marked uncertainties), refreshed in place at each session close via
the `/close-orchestrator-session` skill; part of the boot stack. Its top section is the live
layer; a frozen **Genesis** section below the `---` holds the 2026-07-02 founding rationale
(on-demand forensics, never refreshed).

**`DECISIONS.md`** — the numbered ledger of settled programme/process decisions below the ADR bar.
Not re-litigated; contradicting information is a user escalation; when a decision changes, the row
is updated in the same breath. ADR-bar decisions get an ADR AND a row pointing at it.

### task-review.md — the completion contract

Written ONCE by the task orchestrator at full completion via the **`/create-task-review`** skill
(user-level; format and knowledge-transfer doctrine live there — don't restate them). pflow
preconditions before running it: all deep-review findings dispositioned, `make check` +
`make test-all-local` green, user-facing behavior exercised on the real surface (Definition of
done). **No review file = not done; the main orchestrator rejects the handback.** Future
planners/orchestrators read the task-reviews of their dependency tasks FIRST — they are the
integration contracts. The check cuts both ways: **a missing dependency review at packet-assembly
time means that dependency isn't actually done** — resolve before launching. (Rare exception: a
dependency shipped before this system existed and never got a review — verify done-ness via its
merged PR and point the packet there instead; almost all recent tasks have reviews.)

### Progress-log entry format (task logs)

```md
## [2026-07-11 14:32] <role> — <phase/event>
- Did: <one line>
- Changed: <files/areas>
- Verified: <command/observation + result>  |  Assumed: <what wasn't>
- Deviations/surprises: <vs plan/spec — the signal line; never "none" by reflex>
- Self-checks: <"fully happy?" outcome — doubts raised + fixed, or "clean">; <test-reflect:
  deepened/deleted which, or "not run — reason">
- Next: <one line>
```

## Worktree & git flow

1. **Docs commit first:** before a worktree is created, the main orchestrator commits its
   spec-freshness edits and any orchestration-doc changes to `main` — a worktree is a checkout of
   `main`; uncommitted docs don't follow. (The PLAN is not in this set — it is authored inside the
   worktree and rides the feature branch.) DECISIONS #5 scopes this commit authority; pushes of
   `main` remain user-gated.
2. **Provision:** the main orchestrator runs the worktree workflow with the terminal agent
   suppressed (that agent is lane C's tool, not this lane's):
   ```
   uv run pflow examples/real-workflows/git-worktree-task-creator/workflow.pflow.md \
     task_description='<Task N — title | #NNN — title>' \
     open_cli=false open_cursor=false \
     [work_type=issue] [copy_folder=scratchpads/<subject>] [base_branch=main]
   ```
   → creates `~/projects/pflow-worktrees/<branch-slug>/` on a feature branch. NEVER the Agent
   tool's `isolation: "worktree"` — an unmanaged tree with no packet, whose auto-cleanup fights
   this process. Create worktrees sequentially, never in one parallel shot.
3. **Launch:** planner and task orchestrator are Agent-tool subagents pointed at the worktree's
   ABSOLUTE path; they work only there — **sequentially, never two agents concurrently in one
   worktree**. First acts of each: verify the base ref (`git log -1` vs `origin/main` — a stale
   base misses the newest contracts) and `make install` (fast — uv's cache is shared).
4. **Commits:** the planner commits its plan (+ spec corrections) on the feature branch; the task
   orchestrator commits as phases complete (deliberate staging, never blanket `-A`;
   scratchpads/briefs are gitignored and stay out). Never to `main`. Task docs merge to `main`
   WITH the code, via the PR. Pre-commit hooks enforce repo conventions (including the task-Status
   vocabulary) — never bypass with `--no-verify`. **PR review marker (DECISIONS #12):** the first
   commit on each PR branch uses a normal message; EVERY later commit on that branch (follow-up,
   review fix, CI fix, or merge-base update) includes the exact marker `[skip review]`.
5. **PR:** the task orchestrator runs `/create-pr` (which pushes the feature branch —
   process-authorized) and hands back minimal. **Merge authority is the main orchestrator's**
   (DECISIONS #4): squash-merge (the repo convention) after CI green.
6. **The gate must pass on the merged result:** if `main` moved while the task was in flight,
   merge main into the branch and re-run `make check` + `make test` before the PR — a
   branch-green / merge-red gap is exactly what this catches.
7. **Teardown:** after merge, the main orchestrator prunes worktree + branch. **Squash merges make
   commit-id checks LIE** (`git branch --merged` / `git cherry` mark merged branches unmerged; this
   trap has bitten twice): the reliable check is `gh pr list --state merged --head <branch>` and
   compare its `headRefOid` to the branch tip — equal + clean tree = safe to prune. Never `-f`
   blind.
8. **Parallel tasks** require the collision analysis below; at most one in-flight task may need a
   live `pflow ui` server; prefer a no-checkpoint task as the parallel companion (checkpoints
   serialize on the user's attention).

## Collision analysis (before any parallel launch — two dimensions, both verified, never assumed)

1. **File surfaces**: grep what each piece of work actually touches; disjoint trees → parallel-safe.
2. **Semantic collisions**: disjoint files still collide through shared state — e.g. one task
   regenerates a fixture set that another task's format change invalidates. Whoever merges second
   destroys the other's work. When found: **order them and say why in the packet.**

Standing rules: **serialize anything that touches the engine** (`runtime/engine/`,
`workflow_executor`) — parallel engine edits collide semantically even when diffs merge cleanly.
**Serialize anything that touches the trace format** (version, trailer, event semantics). That
static pair is the floor; **CURRENT-STATE's watch list is the live extension — check it before
any parallel launch** (hot seams shift as arcs progress). Never
fan out multiple consumers against a DRAFT contract — skeleton-first, pin the contract against the
first real consumer, then parallelize. Contracts get pinned **in-task at the seam that forces
them**, not in up-front documents.

## Model routing (supersedes the 2026-07-03 rulings — DECISIONS #3; user may override any launch)

| Tier | Use for | Rule |
|------|---------|------|
| **Sonnet** | Mechanical phases: scaffolding from an exact spec, config wiring, repetitive table-driven tests. Also grep-shaped searcher lookups | Phase text must contain ZERO ambiguity. A Sonnet phase requiring judgment is a planning bug — fix the plan, not the routing |
| **Opus** | **The default for everything with real judgment**: task planners, task orchestrators, most implementer phases, searchers (pinned) | Plans state decisions; bounded judgment may be left to the implementer |
| **Fable** | **ALL web-UI implementation phases — always** (user ruling 2026-07-11, DECISIONS #8): every phase that writes UI (`web/` → `src/pflow/ui`) routes to a Fable `task-phase-implementer` — never implemented inline by the task orchestrator, never a lower tier — and is built with **deliberate design/UX care**: the plan states the phase's use case + look/feel intent, and visual quality/UX are acceptance criteria verified by driving the UI. Otherwise opt-in where runner routing exists, with a one-line justification: hard architecture, subtle seam design (engine, trace, resume/gate semantics), gnarly debugging. Codex records this as intent but inherits the runtime route. Lane C's terminal builder is the historical Fable home and stays one | Never an ambient default for non-UI implementation |

Runner model names are an execution detail; plans continue to use the tier names above. The
Codex names below apply to generated static agent configuration, not dynamic-launch overrides:

| Contract tier | Claude launch model | Codex launch model |
|---------------|---------------------|--------------------|
| Sonnet | `sonnet` | `gpt-5.6-terra` |
| Opus | `opus` | `gpt-5.6-sol` |
| Fable | `fable` | `gpt-5.6-sol` |

Claude agent `effort` maps directly to the same Codex reasoning level: `low` → `low`, `medium` →
`medium`, `high` → `high`. Generated agent TOML uses `model_reasoning_effort`.
`scripts/sync_claude_assets.py` applies the same model and effort mapping to generated
`.codex/agents/*.toml`; an unknown source value is a generation error.

- **Claude dynamic launches:** pass the explicit `model` param on EVERY launch — agent
  frontmatter is cached per session; the param is the live lever.
- **Codex dynamic launches:** NEVER pass model or reasoning-effort overrides; the API does not
  expose them. Children inherit the runtime route. Keep the plan's tier label as intent and make
  the inability to enforce it visible; never claim a tier was selected.
- **Lane B**: Opus floor, never lower; Fable for complex/hard-debugging issues only with the
  user's per-launch approval (DECISIONS #9).
- **Planner-implements exception:** when a planner finds the implementation small, it may offer in
  its handback to implement directly (itself, in-context — NOT by spawning implementers). The main
  orchestrator decides using the handback's token-usage report: ample headroom → resume the
  planner to implement (it keeps its investigation context, and the task-orchestrator close-out —
  self-checks, code-mode review, `/create-task-review`, `/create-pr` — becomes its); tight →
  launch an Opus task orchestrator on the finished plan.
- **Limit recovery** (empirical, inherited from the Nora system's Fable exhaustion): NEVER
  SendMessage-resume an agent whose model tier is exhausted — it re-dies on its next inference
  call. Recovery = a REPLACEMENT at an available tier launched into the SAME worktree (absolute
  path, no isolation flag), explicitly RESUMING from spec + plan + progress log. Tier capped with
  a lower option → re-route the plan down; capped with none → the task waits. **Never `fork` to
  force a model** — a fork inherits the main orchestrator's whole context (breaking the two-level
  design) and ignores the `model` param anyway.

## Agent economics — phases ≠ agents

Phase boundaries exist for verification gates and model routing, NOT one-agent-per-phase. A fresh
implementer pays a real context-rebuild tax. The plan's agent assignment defaults to continuity:

- **Bundle** consecutive same-tier phases into one launch when the next builds on the previous.
  A lower-tier phase may ride in a higher-tier dispatch only when genuinely small (low LOC); never
  route a phase DOWN a tier because its neighbors are cheap.
- **Resume the same implementer** (SendMessage) with its next phase after verifying the handback.
- **Bundle-vs-resume litmus:** stop between phases ONLY when the gate's outcome can change the next
  instruction. If you'd send "continue as planned" regardless, the stop is overhead — bundle.
- **Fresh launch** only for a stated reason: tier change, parallel disjoint work, a huge/degrading
  window, or fresh eyes (which are the review battery's job, not an implementer's).
- Synthesis/doc phases belong to whoever already holds the content.
- Main-orchestrator waits on running children default to 15 minutes (DECISIONS #13); child
  completion and user messages still interrupt immediately.

## Review policy (the pflow battery, two gates)

The `review-*` specialists + `/deep-review` skill (selection rubric, tiers, severity — in the
skill and `REVIEW-PROTOCOL.md`). **The main orchestrator never runs deep-review and never reads
plans — the agents own their own quality:**

- **Plan self-review — the PLAN AUTHOR's duty** (the planner in the split shape; the task
  orchestrator itself when it plans-and-implements) on its own finished plan (plan-mode
  `/deep-review`, scaled to the plan): **mandatory when the plan touches `runtime/engine/`/
  `workflow_executor` or the trace format** — pflow's highest-risk seams; the author's judgment
  otherwise (big/risky plans get the battery; small ones skip). The author verifies Critical
  findings against code itself and folds confirmed fixes in before building on the plan. (If the
  Skill tool is unavailable in a subagent context, read `.claude/skills/deep-review/SKILL.md` and
  follow it — it is instructions + Agent launches.)
- **Completion gate — run by the TASK orchestrator** when it is FULLY happy, before
  `/create-task-review`: code-mode `/deep-review` on the full branch diff. It applies the correct
  fixes and logs EVERY finding with disposition — fixed, or skipped with a reason.
- **Mid-task phase review** at the task orchestrator's judgment after an especially risky phase
  (engine contact, trace-format change, resume/gate semantics — anything later phases build upon):
  one or two targeted specialists on that phase's diff, not the full battery. The plan marks
  candidate phases ("triggers review").
- **Focused seam/area review** on demand — when a shared pattern or a hot seam changed, regardless
  of which task did it. The main orchestrator may also commission cross-task area reviews.
- Never review Sonnet mechanical output alone — if it seems to need review, the routing was wrong.

## Definition of done

`CLAUDE.md`'s testing directives govern (tests ship with the implementation; the interface is the
test surface; never mock what you can test directly). Process additions:

- **The per-phase gate is `make check` + `make test`** (or the plan's narrower per-phase command)
  green at every handback — green is table stakes. Completion adds **`make test-all-local`**. New
  lint/type suppressions need a coded reason at the site.
- The plan lists, per phase, the concrete failure scenarios its tests must catch — scenarios, not
  coverage. A test earns its place only if it would FAIL when the behavior it guards breaks. Bug
  fix ⇒ regression test on the exact buggy path. Shallow tests in your working area get deepened
  or deleted (and logged).
- **"Verified" means you exercised the real surface**: CLI/behavior changes → run a real workflow
  (`uv run pflow ...`) and observe the output. **Web-UI changes ALWAYS invoke the
  `screenshot-pflow-web-ui` skill and verify EVERYTHING changed** (screenshot/measure every
  affected surface; if the Skill tool is unavailable, read
  `.claude/skills/screenshot-pflow-web-ui/SKILL.md` and follow it) — green component tests alone
  never close UI work. Kill stale `pflow ui` servers first (the reuse-if-up probe serves old
  code — recorded gotcha).
- Platform-sensitive code (subprocess, encoding, paths, `fcntl`) must clear the blocking
  `tests-windows` CI job; ADR-0013 governs shell semantics.
- Per-phase verification is NOT a conformance diff-audit: the implementer writes substance
  (deviations, insights, self-checks) to the progress-log and hands back a minimal pointer; the
  orchestrator reads the log entry and resumes the implementer with *"Are you FULLY happy with the
  implementation? Any loose ends?"* on every phase (context live, nearly free — honest doubts
  surface on request far cheaper than a reviewer re-derives them). **Only when a phase's tests
  were plausibly hard to write / easy to cheat** (subtle logic, non-deterministic edges, a
  behavior a shallow test could fake-pass), additionally direct the implementer to read
  `.claude/commands/test-reflect.md` and apply it (deepen or delete, log which) — skip it for
  scaffolding/config phases. The completion-gate battery is the correctness backstop.

## Checkpoints, escalations, park/resume

Subagents cannot talk to the user — the main orchestrator is the channel.

- **User checkpoint** ("Show Before You Code", design forks, anything the spec marks): the task
  orchestrator/planner pauses at a clean point, writes a progress-log entry capturing state +
  exact resume point, and hands back with the artifacts/options + its recommendation. The main
  orchestrator surfaces it to the user, then **resumes the SAME agent via SendMessage** with the
  ruling — context intact.
- **Checkpoint artifacts travel by file path** — the user works locally and can open files, run
  the CLI, or use the worktree's `pflow ui` directly. For comparisons the main orchestrator may
  publish an Artifact page; **publishing and user conversation never delegate down.**
- **Escalation ownership** follows `CLAUDE.md`: importance 1–2 reversible calls the resolving
  orchestrator makes visibly in the log; **importance 3+ goes to the user** with options + ONE
  recommendation. A decision meeting the ADR bar is automatically an escalation; on ruling, the
  main orchestrator writes the ADR and the `DECISIONS.md` row in the same breath.
- Before ANY parking handback, write the progress-log entry capturing state + exact resume point —
  it is the disaster-recovery record if the session is lost while parked. Finish
  decision-independent work first; bundle pending questions into ONE handback.
- **Never launch a fresh agent to "continue" a parked task** — it re-derives everything and
  drifts. Sole exception: the parked agent is unrecoverable (SendMessage fails, no transcript) —
  launch a REPLACEMENT into the SAME worktree, explicitly resuming from spec + plan + progress log.
- A task parked on the user doesn't block other lanes.

## The context packet (what a planner / task orchestrator is launched with)

- The task folder path (or issue number for lane B) + instruction to read the spec fully,
  including `starting-context/`.
- The **worktree's absolute path** (all work happens there) + the entry mode
  (plan-and-implement / implement-from-plan / plan-only).
- The `task-review.md` paths of every dependency task (a missing one means that dependency isn't
  actually done — resolve before launching).
- Pointers: this file, `context/CONTEXT.md`,
  `.claude/skills/improve-codebase-architecture/LANGUAGE.md`.
- One paragraph from the main orchestrator: current repo state, what neighboring merges just
  changed, collision/serialization notes, anything the spec doesn't know yet.
- The runner reminder: Claude passes the explicit `model`; Codex omits model/reasoning overrides
  and inherits the runtime route.

## Write discipline (all logs)

Lean by construction: **point, don't restate** (anything in a durable artifact is referenced,
never paraphrased); full sentences only for the EXCEPTIONAL (deviations, doubts, honest unknowns —
never "none" by reflex); choreography is one line — with ONE exception: **pre-park resume-state
entries stay FULL** (proven disaster recovery). Anything with forward value must reach a durable
home (or CURRENT-STATE) before its session closes — everything else is deliberately allowed to age
out with its session file. Two agents never write the same log concurrently — parallel
implementers put entries in their final report; the orchestrator appends in order.

## New tasks (scope changes)

The task list is not frozen: a new task enters when the **user asks**, **changed circumstances**
invalidate a plan, or an orchestrator **notices** a real gap (a carve-out, a "done task with an
unmet DoD"). Always a **suggestion to the user first — never self-approved**, gated on
`CLAUDE.md`'s observed-problems rule: what/why, where it slots (dependencies), rough size. On
approval the main orchestrator writes the spec (`/create-task` conventions) and updates the
CLAUDE.md roadmap (short task names only). Small/bug-shaped work goes to lane B instead.

## Living documentation

`context/CONTEXT.md` gets new domain nouns as they crystallize (proposed in handbacks, written by
the main orchestrator; format per `CONTEXT-FORMAT.md`). ADRs on `ADR-FORMAT.md`'s three-part bar —
task files archive and go stale; ADRs are the durable layer. Instruction files (CLAUDE.mds, agent
defs, skills) are updated by the task that makes them stale — the completion gate checks. Settled
decisions (`DECISIONS.md` rows, ADRs, a spec's locked decision ledger) are **not re-litigated** —
new information that contradicts one is a user escalation, not a quiet rewrite; the main
orchestrator owns the `DECISIONS.md` write side.
