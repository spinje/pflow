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
reconcile is not approval to commit, and closing a session authorizes none. Sole exception: a
minimal prep commit of producer-facing tracked inputs immediately before provisioning an approved
worktree; that approval covers its push; nothing producer-facing changed ⇒ no prep commit, branch
from verified `origin/main`. Orchestration state never rides a PR — user: *"we keep this as
simple as possible for this repo (no docs prs)"*.

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
lane B runs Opus and gets Fable only on the user's per-launch word.

Home: `ORCHESTRATION.md` "Model routing", "Lanes"; `.claude/agents/task-planner.md` frontmatter

### 31 — No cross-task knowledge base

`.taskmaster/knowledge/` is retired: a fact lives where its constraint binds — the code, or the
CLAUDE.md / agent def that owns the rule — never in a patterns / pitfalls / decisions store.

Home: root `CLAUDE.md` "Code Quality" (the grep-before-restating rule)
