# DECISIONS — settled programme & process decisions

_The numbered decision ledger: settled decisions **below the ADR bar** but above task level —
process rules, programme-shaping calls, standing conventions. **Settled decisions are not
re-litigated**; new information contradicting one is a user escalation, and when a decision
changes, this ledger is updated in the same breath. Task-level decisions stay in their task
specs; ADR-bar decisions get an ADR (`context/adr/`) AND a row here pointing at it. Write side:
the main orchestrator._

_Format: one `###` heading per decision (`<N> — <short title> (date)`), a short wrapped body, and
a `Home:` pointer — link the durable home, don't restate it. New decisions append a heading + a
few short lines. Lifecycle vocabulary: a row may be marked **SPENT** (executed, historical),
**softened/clarified** (amended in place, dated), or carry a **CURRENT OVERRIDE** (a temporary
ruling supersedes the underlying policy, which stays written as **dormant**, not deleted)._

### 1 — Adopt the agent-hierarchy orchestration system (2026-07-11)

Ported from the user's sibling orchestration systems, adapted to pflow. `ORCHESTRATION.md` is the canonical
process contract; roles = main orchestrator / task-planner / task-orchestrator / phase-implementer;
hierarchy exactly two levels. The main orchestrator shifts from brief-writer-for-user-guided-builds
to dispatcher: it never writes/reads plans, never runs deep-review — agents own their quality.

Home: `ORCHESTRATION.md`

### 2 — Three lanes (2026-07-11)

A full task procedure · B GH-issue lane · C manual lane (the pre-restructure user-guided worktree
flow, kept for open-ended or taste-verified work). User: manual lane stays for tasks needing live
guidance to the goal, "but these tasks will be less and less common."

Home: `ORCHESTRATION.md` "Lanes"

### 3 — Model routing (2026-07-12; amended 2026-07-13, 2026-07-14, 2026-07-15) — SUPERSEDED by #24 (2026-09-27)

Historical. The 2026-07-15 override ("Fable BANNED for all subagents; Opus for everything, never
Sonnet") ran ten weeks and was replaced by the standing policy in #24. The text below is kept as
the record of what the override sat on; the live launch-mechanics sentences (runner-specific
model, Codex `reasoning_effort`, forks cannot override) still hold and live at the Home.

Underlying (then-dormant) policy: Opus = default for judgment, **including task planners** (moved
Fable→Opus 2026-07-13, `647d86f9`); Fable = ALL web-UI implementation phases (#8) + opt-in with a
one-line justification; Sonnet = zero-ambiguity mechanical. Every dynamic launch passes the
runner-specific model; **Codex launches also pass explicit `reasoning_effort`** — both overrides
are accepted and persisted in child `turn_context` (verified via PR #595) even though the displayed
schema omits them. Full-history forks cannot override either field. Root `AGENTS.md` is the
launch-level contract. Supersedes both 2026-07-03 rulings ("never fable for research subagents";
"fable for the worktree builder" — scoped to lane C + justified opt-ins). User may override any
launch.

Home: `ORCHESTRATION.md` "Model routing"

### 4 — Merge authority is the main orchestrator's (2026-07-11)

Squash-merge after CI green on the merged result, then teardown (squash-safe prune check) +
reconcile. Previously merges were user-only; user ruling ("yes we adopt it"). Lane B agents merge
their own PR after CI green.

Home: `ORCHESTRATION.md` "Worktree & git flow"

### 5 — Role-scoped commit authority (2026-07-11; amended 2026-07-15, 2026-08-14, 2026-08-15)

Implementing agents may commit and push on their feature branches as required by task/issue
execution. The main orchestrator commits to `main` only with explicit user approval, except for a
minimal local commit strictly necessary immediately before provisioning an approved worktree so
the launched agent can see required tracked context. **That exception covers ONLY repo-tracked
inputs the producer must inherit (freshness-corrected specs, material instruction/tracker
corrections); if nothing producer-facing changed, make no prep commit and branch from verified
`origin/main`** (#21). Routine reconciliation, roadmap/state/session
updates, and session close do not qualify. Pushing `main` always requires explicit user approval.
**Amended 2026-08-15 (re-audit, #22): the approval that authorizes a prep commit covers pushing
it in the same act** — worktrees branch from verified `origin/main`, so an unpushed prep commit
is invisible to the very producer it exists to serve.
User correction after the session-05 reconciliation: approval to edit or reconcile is not approval
to commit.

Home: this row (referenced from `ORCHESTRATION.md` and the role prompt)

### 6 — Orchestration state layout (2026-07-11)

`orchestrator-progress-log.md` replaced by `CURRENT-STATE.md` (~80-line living header) +
`sessions/session-NN.md` (append-only per session). Old log converted to `sessions/session-01.md`;
full history also in git.

Home: `ORCHESTRATION.md` "Artifacts and ownership"

### 7 — Lane-B exclusions (2026-07-11)

Work touching `runtime/engine/`/`workflow_executor` or the trace format always takes the full task
procedure, regardless of size — pflow's highest-risk seams (the analog of the sibling
programme's live-production migrations); they also carry the standing serialization rules.

Home: `ORCHESTRATION.md` "Lanes"

### 8 — ALL web-UI implementation phases route to Fable (2026-07-11)

Every phase that writes UI (`web/` → `src/pflow/ui`) routes to a Fable `task-phase-implementer` —
never implemented inline by the task orchestrator, never a lower tier — with deliberate design/UX
care: the plan states the phase's use case + look/feel intent, and visual quality/UX are
acceptance criteria. **UI work ALWAYS invokes the `screenshot-pflow-web-ui` skill and verifies
everything changed** — green component tests never close a UI phase. User ruling (correcting the
initial port, which had skipped the sibling system's equivalent rule on the wrong premise that pflow's web
UI is a mere dev tool). Was dormant under #3's override 2026-07-15 → 2026-09-27; **active again
under #24** (the screenshot-verification half stood regardless of tier). **Clarified 2026-08-15 (re-audit, #22;
adopting the sibling programme's later ruling on the same rule): the trigger is TASTE — a
look/feel judgment the spec cannot settle, not the file location.** If there is no look/feel
intent for the plan to state, the phase was never this rule's target; fixing a broken
interaction is not designing one. Frontend work with no such judgment routes Opus like any other
implementation.

Home: `ORCHESTRATION.md` "Model routing"

### 9 — Lane-B model policy (2026-07-11)

The main orchestrator assesses the issue's complexity at pick time. **Opus is the floor — never
lower** for the end-to-end agent. Genuinely complex issues (hard debugging, subtle root cause)
warrant **Fable — but only with the user's per-launch approval**; never deploy Fable to lane B
unasked. Scoped to lane B: lane A's standing Fable rule (#8) needs no per-launch ask.

Home: `ORCHESTRATION.md` "Lanes"

### 10 — Session-read rule (2026-07-11)

A booting main orchestrator reads the latest session file; if it's thin (short check-in, aborted
session), it reads one further back until it hits a substantive one. Older files stay on-demand
forensics. User ruling (chose this over a fixed last-2 window) — preserves the forcing function:
anything with forward value must reach CURRENT-STATE/a durable home before a session closes;
session files are color, not state.

Home: `ORCHESTRATION.md` "Artifacts and ownership"; the role prompt boot sequence

### 11 — Session close is a ritual, not a filing chore (2026-07-12; amended 2026-07-15, 2026-09-27)

Drain — nothing closes hot; retrospect; make state true; **reconcile `RECURRENCE.md`; promotions +
process evolution (small edits applied per #25, the rest proposed); append the `sessions/INDEX.md`
entry; write the session `## Braindump`** (amended 2026-09-27 under #23 — replaces "refresh the
rolling braindump"); verify boot-readiness (print the boot-set size); hand off. Session close does
not authorize a commit; commit authority remains governed by #5. Ported from the sibling system at
the user's ask; pflow adaptations: lane-C terminal agents don't drain (record their state in
CURRENT-STATE).

Home: `.claude/skills/close-orchestrator-session/SKILL.md`

### 12 — PR commit review marker (2026-07-13)

The first commit on a PR branch uses a normal message; every subsequent commit on that branch must
include the exact marker `[skip review]` in its commit message. Prevents redundant automated
review cycles after the first PR commit while preserving the initial review trigger.

Home: `ORCHESTRATION.md` "Worktree & git flow"

### 13 — 15-minute default waits on running children (2026-07-13)

Use 15-minute waits as the default while child agents run. Child completion and user messages
still interrupt immediately. User ruling after observing that every wait timeout reinvokes the
main agent; reduces wasteful polling.

Home: `ORCHESTRATION.md` "Agent economics"

### 14 — Auto-reviewer comments are a merge gate (2026-07-13)

The implementing agent must read and act on the automatic PR review comments (`claude-review` /
Codex) before a PR is merge-ready; the orchestrator verifies this at the merge seam. Reaffirms
#4's standing merge authority — the orchestrator merges when fully ready, no per-merge user go.
User ruling ("authorized to merge when PRs are fully ready … make sure the subagents have read and
acted on the automatic code reviewers"). The `[skip review]`-on-follow-ups half is #12.

Home: `ORCHESTRATION.md` "Worktree & git flow" (merge seam)

### 15 — A gap your change is about to widen is yours to close (2026-08-14)

When a change makes a pre-existing flaw bite harder, closing that flaw belongs to the change, not
to a filed issue. Narrow, checkable trigger: the defect is live before your diff AND your diff
extends it to a new surface or larger blast radius; not a licence to fix adjacent bugs; the
producer states the extension and keeps it cleanly revertible. Imported via the 2026-08-14
cross-repo fold (#19; source ledger row #44).

Home: `ORCHESTRATION.md` "New tasks (scope changes)"

### 16 — State docs are handoff artifacts, not a journal (2026-08-14)

Orchestration state docs serve the NEXT main orchestrator only — not crash resilience. Write at
real state transitions (ruling/launch/ship/course-change), one-line entries, batch the rest to
session close; CURRENT-STATE is rewritten at close/park, never patched incrementally (work done
OUTSIDE a numbered session appends a dated top block that the next boot folds — added 2026-09-27,
see ORCHESTRATION "Artifacts"); the tacit layer (`STANDING-KNOWLEDGE.md` since #23) is touched
ONLY at session close. The orchestrator's working state lives in its
context window. **Supersedes the prior "written as events land" text** in the role prompt.
Imported via the fold (#19; source ledger row #30), user-approved.

Home: `ORCHESTRATION.md` "Artifacts and ownership"; role prompt loop 6 + session end

### 17 — Review labour leaves the task orchestrator (2026-08-14)

Evaluating findings and applying fixes at the completion gate and mid-task reviews go to the
implementer that built the phases (window healthy) or a fresh review-evaluator; the task
orchestrator keeps deciding a gate is due, reading the outcome, and dispositioning what remains.
Dispatch runs through the pflow fan-out (`workflows/review/run-review-lenses.pflow.md`, provider
codex — model-family diversity), waited on IN-TURN, so the whole gate is one job owned by the
gate-runner; direct Agent-tool lens launches are a logged one-off. Imported via the fold (#19;
source ledger rows #37 + #29). **Amended 2026-08-15 (re-audit, #22): "in the FOREGROUND" →
waited on IN-TURN** — a battery outruns the 600s Bash cap, past which a foreground call
auto-backgrounds into the wake trap; the mechanism is a backgrounded call writing a declared
output file, watched by Monitor/foreground polls, never an ended turn.

Home: `ORCHESTRATION.md` "Review policy"; `.claude/agents/task-orchestrator.md`

### 18 — Effort routing: high is earned by ambiguity (2026-08-14)

Effort tracks the residual ambiguity the agent must absorb: spelled-out phases route `medium`;
`high` only for self-designed steps, design-bearing UI, subtle seams, gnarly debugging; agents
authoring their own plan of attack route `high`. Pass explicit `effort` on every launch; the
def's frontmatter is the contract — the per-agent values live there, not here.
Imported via the fold (#19; source ledger row #48).

Home: `ORCHESTRATION.md` "Model routing"

### 19 — Cross-repo fold from the sibling programme (2026-08-14)

User-approved import of the sibling orchestration programme's post-fork general doctrine (Tier 1 + Tier 2 of
the 2026-08-14 audit). Landed in this pass: this ledger's format; constraint-not-incident +
verified-or-dropped (ORCHESTRATION "Write discipline"); absence-needs-presence (Definition of
done); autonomy grants, relay craft, question discipline, failure modes 9–11 (role prompt);
theme-organized braindump doctrine + session-file spent-category cut (close skill; the braindump
file — now `STANDING-KNOWLEDGE.md`, #23 — restructured to match); ADR adversarial review (`context/adr/ADR-FORMAT.md`); the
`review-falsifier` execution lens (`.claude/agents/review-falsifier.md`); the pflow-fan-out
review dispatch + codex searcher offload (`workflows/review/`, `workflows/search/`, wired into
the `deep-review` skill); rows #15–#18. **Standing user ruling from the same session: the sibling
programme's repo name (and its predecessor's) appears NOWHERE in this repo** — refer to "the
sibling repo/programme"; scrubbed repo-wide 2026-08-14, and new writing holds the ban.
**Imported rules are imported-not-earned**: one that
fails against a pflow instance is a user escalation, not a silent keep — and not a silent delete.

Home: `scratchpads/cross-repo-knowledge-transfer/plan.md` (local-only); the homes named per item

### 20 — Lane B runs on the lane-implementer agent; second def sweep (2026-08-14)

**Lanes run on `.claude/agents/lane-implementer.md`** — the stable evaluate/build/PR protocol has
ONE home there (critical evaluation first; escalation above importance 2/5; proportionate
completion gate with a floor of one lens on shared tooling/CI/security diffs; merges its own PR
after CI green + auto-reviewer action); packets carry only variables. The task orchestrator's
issue mode is retired. Lanes may delegate MECHANICAL execution to leaf subagents —
`code-implementer` is the designated leaf; judgment never delegates. Same user approval also
landed the def sweep: planner cross-task board scan + lens-assignment rule; test-reflect
RESOLVES logging; background-Bash wake-trap + monitor/relay rules; REVIEW-PROTOCOL
refute-not-confirm / re-verify-before-report / partial-coverage-reportable. Imported via the
fold (#19; source ledger rows #12, #17, #18, #40, #41, #55).

Home: `.claude/agents/lane-implementer.md`; `ORCHESTRATION.md` "Lanes", "Roles", "Review policy"

### 21 — Fold tail: lean audits, capacity grants, guard-crash heuristic, prep-commit refinement (2026-08-14)

Third user-approved batch from the cross-repo fold (#19): **architecture passes run LEAN** (one
orchestrator + parallel searchers, never a wide multi-agent workflow) **and disposition through
the leverage filter** (standalone slot needs ≥2 real remaining consumers, or 1 + a live defect
class; measured against the remaining roadmap, never aesthetics); **capacity grants** are
confirmed-at-grant, applied per-role visibly, snapped back on close — a restoration arrives with
a scope, not a budget; **a guard proposed to avoid a crash means the crash is the finding**; and
the #5 prep-commit refinement (no producer-facing change ⇒ no prep commit). "Every task gets a
planner" (source ledger #31) was considered and HELD here — **the hold was lifted by #24
(2026-09-27)**. Source ledger rows #53, #28, #52, #2/#35.

Home: `improve-codebase-architecture` skill "Process"; role prompt "Interpreting an autonomy
grant"; `lane-implementer.md` (evaluate step); row #5

### 22 — Re-audit follow-up batch: second fold import, user-approved (2026-08-15)

User ruling on the re-audit report ("go ahead and fix all issues"): proposals P0–P8 applied per
the report's recommendations, on the PR #610 branch. Amendments in place: #17 (in-turn wait),
#8 (taste trigger), #5 (prep commit includes its push). Applied: limit-recovery second half;
shared-worktree/parallel hazards; agent-economics rotation doctrine; verification kernels in the
DoD; lens-drift ports + REVIEW-PROTOCOL floor-not-ceiling; spec-review carve-out; lane packet
hand-back lever; test-reflect rebuilt from its seed; create-task/start-work/worktree upgrades;
curated braindump themes. HELD per the same report: producer-reconciles-own-status (#32 analog)
— revisit if reconcile labour bites; probe-spend and bad-history postures recorded as braindump
lines, promoted only on a real pflow instance. All imports remain imported-not-earned (#19).

Home: `scratchpads/cross-repo-knowledge-transfer/re-audit-report.md` (local-only); the homes
named per item

### 23 — Three-tier memory: session braindump → RECURRENCE → STANDING-KNOWLEDGE (2026-09-27)

User ruling on the sibling-comparison forks (*"a. yes"* to the memory architecture, then *"you
will fix everything else right, like STANDING knowledge etc"* — the full shape, not a reduced
one). Per-session residue lives in the session file's `## Braindump`; `RECURRENCE.md` counts
recurrences and promotes at threshold; `BRAINDUMP.md` becomes `STANDING-KNOWLEDGE.md` with
**entry by promotion only** (pre-existing lines grandfathered, drained via the close skill's
downward exit); `sessions/INDEX.md` routes to old sessions and is never a boot read. The
mechanics — entry bar, ramps, formats, boot stack — live at the Homes. **Declined with triggers:**
the DECISIONS index/archive split (revisit at ~60 rows or when this file outweighs CURRENT-STATE);
an agent-file fact checker beyond `tests/test_docs/test_agent_references.py` (revisit when a
searcher def crosses ~30 KB). The 20-session decay is inherited, unmeasured here (#19).

Home: `ORCHESTRATION.md` "Artifacts and ownership"; `RECURRENCE.md` header;
`STANDING-KNOWLEDGE.md` header; close skill steps 3–6

### 24 — Model routing policy: Fable by role, Opus everything else, Sonnet retired (2026-09-27)

**User ruling, verbatim:** *"fable is for main orch, planning, and ui / taste, everything else is
opus, never sonnet"* · *"fable planner is for task planning, not lanes"*. Supersedes #3's override
(2026-07-15) as standing policy: the main orchestrator (the user's session) and **every task
planner** run Fable; design-bearing UI/taste phases route Fable per #8 (active again); lanes,
task orchestrators, implementers, searchers and lenses run Opus; **Sonnet is retired — never
launched, never pinned** (mechanical phases route Opus; the zero-ambiguity bar is plan
discipline). Consequence, ruled in the same breath: **every task gets a planner** — Fable
`task-planner` → Opus `task-orchestrator`, sequentially in one worktree; the planner may offer to
implement a small task itself; too small for a planner ⇒ lane B. Lifts the #21 hold on the
source's #31. Lane B stays Opus with #9's per-launch-approval Fable exception.

Home: `ORCHESTRATION.md` "Model routing", "Lanes", "Roles"; `.claude/agents/task-planner.md`
frontmatter

### 25 — Small instruction edits at importance ≤2 are APPLIED at close, not proposed (2026-09-27)

User ruling (*"d. yes apply"*) adopting the sibling's rule: at the close ritual, an instruction
edit that is BOTH ≤2/5 AND sentence-sized (adding or modifying a sentence or clause) is applied
directly and named in the session log. Everything above that bar still goes to the user with a
recommendation: a 3+/5 call, a rule changing what a role may DO (routing, gates, authority,
destructive-op boundaries), a deletion of standing guidance, or a multi-paragraph rewrite.
Retires "editing your own role definition is never a unilateral act" for this class only.
Mirror sync (`scripts/sync_claude_assets.py --write`) is part of applying.

Home: `.claude/skills/close-orchestrator-session/SKILL.md` step 4

### 26 — A point-fix-shaped issue gets a step-back before it gets a fix (2026-09-27)

Adopted from the sibling (its #66) on the user's "go ahead". Before building, the lane asks
whether the issue is ONE INSTANCE of a wider class, enumerates what it finds, and hands back a
genuinely bigger class rather than growing the lane around it; the answer is recorded in the PR
body either way — "I looked and it is a point fix" is itself the finding. Binds the main
orchestrator at filing/pick time too: **an issue names the CLASS it closes and the closing
mechanism** (ratchet / compile-time / parity / convention); instances are evidence; unsure
whether it is a class ⇒ targeted investigation first, and a proven not-closable verdict is itself
the durable artifact. Sharpens #20's critical-evaluation step and #21's crash-is-the-finding.

Home: `.claude/agents/lane-implementer.md` (evaluate step); role prompt "GH-issue lane"

### 27 — State docs land per #5; no docs-PR lane (2026-09-27)

User ruling (*"we keep this as simple as possible for this repo (no docs prs)"*). The sibling's
pure-docs self-merge, "CLOSED means the state PR is merged", and one-close-PR batching were
considered and declined: pflow's `main` takes the main orchestrator's commits under #5 (the
user's word), and orchestration state does not ride a PR. Re-raise only if #5's stall (session
05/07: state waiting on a merge word) recurs — a `RECURRENCE.md` candidate, not a rule.

Home: row #5

### 28 — Worktrees are provisioned by `scripts/worktree`; the pre-task commands are retired (2026-09-27)

User ruling ("go ahead" on the replacement plan, after asking for the sibling's shape). The
LLM-driven worktree workflow is replaced by a bash script + a slash command in which the agent
derives the branch name itself — the calling agent is already an LLM, the launch quoting is
kept inside one runfile, and teardown (the squash-safe merged-PR check, the rooted-process
refusal) lives in code where a rule violated twice belongs. Kept from pflow's version: the
base-ref guard in code. Retired with it, each superseded under #24: `start-work` (the pre-task
session is the main orchestrator's freshness check + spec review; its glossary discipline moved
to `create-task`), `implement-plan` (every task gets a planner → orchestrator), `manual-
verification` (`review-falsifier` + the real-surface DoD), `test-writer-fixer` (implementers
write their own tests; `code-implementer` takes test-only briefs), the `create-plan` skill (the
planner def owns plan doctrine). The `git-worktree-task-creator` example stays as an example
only, decoupled from process vocabulary (it is also a Task-159 baseline fixture).

Home: `scripts/worktree` header; `.claude/commands/worktree.md`; `ORCHESTRATION.md` "Worktree &
git flow" steps 1 and 6
