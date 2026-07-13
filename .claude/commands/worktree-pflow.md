---
description: Create a git worktree for a user driven agent.
argument-hint: [task description, or a task/issue number]
---
Create an isolated git worktree for the user's task and launch a coding agent in it. Your job: turn the request below into ONE command by choosing the flags, run it, then report back.

The user's request:

$ARGUMENTS

Current branch (used by the base-branch rule):
!`git branch --show-current`

## Command

```bash
uv run pflow examples/real-workflows/git-worktree-task-creator/workflow.pflow.md <args>
```

`<args>` is always `task_description=...` plus any flags from the tables below.
Quote a prose description; a bare task/issue number needs no quotes.

## Examples — map the request to `<args>`

```bash
# "set up a worktree to add retry logic to the http node"
task_description='Add retry logic to the HTTP node'

# "start task 177"   (default: explore + write a plan first)
task_description=177

# "implement task 177 directly / the plan already exists"
task_description=177 mode=implement

# "implement phase 1 and 2 of task 177"   ← spoken phases become a digit range/list
task_description=177 mode=implement phases=1-2

# "work on github issue 443 with codex"
task_description=443 work_type=issue agent=codex

# "task 88 off main (I'm on a feature branch), copy my notes, don't open cursor"
task_description=88 base_branch=main copy_folder=scratchpads/notes open_cursor=false
```

## Flags — add when the user asks for it

| Flag | Add when the user… |
|------|--------------------|
| `work_type=issue` | refers to a GitHub issue — a number, an issue URL, or says "issue" — so the number isn't taken as a task id (default `task`) |
| `agent=codex` | wants Codex instead of Claude Code (default `claude`) |
| `mode=implement` | says "implement directly" / a plan already exists → points the agent at `/implement-plan` instead of the default `explore` → `/start-work`. Pass the bare task/issue number as `task_description` so the plan resolves |
| `phases=<spec>` | scopes the work to phases (**requires** `mode=implement`). Spoken phases → digits: "phase 1 and 2" → `phases=1-2`, "just phase 3" → `phases=3` |
| `model=<model>` | names a model — an alias (`opus`, `sonnet`) or a full id (`claude-opus-4-8`). Omit for the agent's own default |
| `copy_folder=<path>` | wants a folder/scratchpad copied into the fresh worktree (repo-root-relative, e.g. `scratchpads/notes`) |
| `open_cli=false` / `open_cursor=false` | asks NOT to open the coding agent / Cursor (both default `true`) |

If a value is malformed, the workflow rejects it with an actionable error — fix the arg and rerun rather than guessing at the constraint.

## Rules — decisions that aren't a simple flag

- **No task given** (arguments empty) → ask the user what task or issue to create a worktree for. Don't guess.
- **Not on `main`** (see the current branch above) → add `base_branch=main` so the worktree branches off main, not unmerged work. To *deliberately* branch off the current feature branch, pass its name explicitly (`base_branch=<current-branch>`) — omitting `base_branch` on a non-main branch is an error, not a shortcut.
- **Branch/worktree already exists** → the workflow refuses to clobber it. Add `overwrite=true` ONLY to re-run the *same* task and discard the old one. A collision with a *different* task means the name was too vague — give a more specific `task_description` instead of forcing it.

## After it runs

Report the worktree path from the output. Unless `open_cli`/`open_cursor` were disabled, also tell the user that Cursor and the selected agent (Claude Code, or Codex when `agent=codex`) opened in the new worktree.
