# DECISIONS — the rulings a future session cannot infer

_The bar for a row: the ruling impacts future sessions hard AND is not inferable from its Home
(the file where the rule operates). A rule that lives at its Home stays there; it earns a row
only as a user authority ruling or a standing ban that is worth repeating. Settled rulings are not
re-litigated — new information contradicting one is a user escalation, and a change lands here in
the same breath. Task-level decisions stay in task specs; ADR-bar decisions get an ADR
(`context/adr/`), and a row here only if they also pass this bar. Write side: the main
orchestrator._

_Format: `### <N> — <title>`, the ruling (the user's words verbatim where they exist), a `Home:`
pointer. No dates, no history — git holds both. Numbers are stable identifiers: the gaps are rows
removed once their Home carried them; never renumber._

### 4 — Merge authority is the main orchestrator's

User: *"authorized to merge when PRs are fully ready"* — squash-merge after CI green on the merged
result, no per-merge user go. Lane implementers merge their own PR after CI green.

Home: `ORCHESTRATION.md` "Worktree & git flow"

### 5 — Commit authority is role-scoped

Implementing agents commit and push on their feature branches. The main orchestrator commits to
`main` only on the user's explicit word, and pushing `main` always needs it — approval to edit or
reconcile is not approval to commit. Two standing exceptions: (1) a minimal prep commit of
producer-facing tracked inputs immediately before provisioning an approved worktree; that approval
covers its push; nothing producer-facing changed ⇒ no prep commit, branch from verified
`origin/main`. (2) **The close ritual commits and pushes the orchestration state set itself** —
`.taskmaster/orchestration/` only (CURRENT-STATE, RECURRENCE, STANDING-KNOWLEDGE, DECISIONS,
`sessions/`), by pathspec, never `-A` — user: *"we should probably add this to a step in the close
orchestration skill to commit when closing session?"*, ruled for that set only; producer-facing edits
(specs, ADRs, CONTEXT.md, skills, agent defs) still wait for the word or ride exception (1).
Orchestration state never rides a PR — user: *"we keep this as simple as possible for this repo (no
docs prs)"*.

Home: this row (cited from the role prompt and the close skill)

### 19 — The sibling programme's name is banned; its rules are imported, not earned

User ruling: the sibling orchestration programme's repo name (and its predecessor's) appears
NOWHERE in this repo — write "the sibling repo/programme". Rules imported from it are
imported-not-earned: one that fails against a pflow instance is a user escalation, never a silent
keep or a silent delete.

Home: this row

### 24 — Model routing: Fable by role, Opus everything else, Sonnet never

User, verbatim: *"fable is for main orch, planning, and ui / taste, everything else is opus, never
sonnet"* · *"fable planner is for task planning, not lanes"*. So every task gets a Fable planner →
Opus task orchestrator (too small for a planner ⇒ lane B); Sonnet is never launched, never pinned;
lane B runs Opus and gets Fable only on the user's per-launch word. A UI *fix* is not a taste
trigger — user: *"fable is not needed when its just fixes, fable is for taste and designining"*.

Home: `ORCHESTRATION.md` "Model routing", "Lanes"; `.claude/agents/task-planner.md` frontmatter

### 31 — No cross-task knowledge base

`.taskmaster/knowledge/` is retired: a fact lives where its constraint binds — the code, or the
CLAUDE.md / agent def that owns the rule — never in a patterns / pitfalls / decisions store.

Home: root `CLAUDE.md` "Code Quality" (the grep-before-restating rule)

### 32 — Review rounds: astra by default, verified Criticals only, lean per-lens rounds, at most three

User, verbatim: *"we shouldnt hold out on compute when something needs it, a sign we need more reviews is that we are still
finding criticals"* · *"a critical reported by subagents is not the same as a verified critical, and in most cases it will be
clear when diminishing returns are kicking in, very often by round 2 or at most round 3"* · *"we should prefer astra for
reviews, unless there is a very good reason to do claude"* · *"the second family is astra since claude is building, so using
claude should be avoided if the stakes are not unusually high and we for example has already ran 2 astra passes"*. So: review
lenses run on astra; a Claude lens only when stakes are unusually high and astra has hit diminishing returns (reason logged).
A round with a VERIFIED Critical is followed by another; later rounds rerun only lenses still finding verified Criticals or
important warnings, or whose surface the fixes materially changed — clean lenses retire, an unrun lens joins when a fix opens
its dimension. The falsifier counts as a round; new surface does not reset the count; a verified Critical at round 3 ⇒ hand back.

Home: `ORCHESTRATION.md` "Review policy" + `lane-implementer.md` + `task-orchestrator.md` + the deep-review skill (fold PROPOSED
at s16 close — until it lands, every packet states this row)
