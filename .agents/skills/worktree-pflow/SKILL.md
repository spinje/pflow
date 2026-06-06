---
name: worktree-pflow
description: Create an isolated git worktree for a development task in this repo. Use when the user wants to start work on a new task, GitHub issue, feature, or bugfix in a separate worktree and branch — e.g. "create a worktree for X", "start work on issue 484", "set up a branch for this task". Runs the saved pflow workflow git-worktree-task-creator, which generates a conventional branch name, creates the worktree, and opens an editor plus a coding agent session pointed at it. Do not use for committing, pushing, or ordinary in-place edits.
---

# Worktree (pflow)

Create a git worktree for development by running the saved pflow workflow
`git-worktree-task-creator`. It generates a conventional branch name
(feat/fix/docs/refactor/test), creates a sibling-folder worktree
(`<repo-root>-worktrees/...`), and — by default — opens Cursor and a coding
agent session pointed at the new worktree.

## How to run

1. Check the current branch (needed for the base-branch rule below):

   ```bash
   git branch --show-current
   ```

2. Build and run the command, substituting the user's task description:

   ```bash
   uv run pflow git-worktree-task-creator task_description='THE TASK DESCRIPTION' agent=codex
   ```

   `agent=codex` launches a new **Codex** session in the worktree (matching this
   session). Pass `agent=claude` instead if the user wants Claude Code.

## Parameter rules

- **Empty description**: if the user hasn't said what the task is, ask them to
  clarify before running — don't guess.
- **GitHub issue**: if the work is a GitHub issue (the user gives an issue
  number, an issue URL, or says "issue"), add `work_type=issue`. This labels it
  as a GitHub issue (not a pflow `.taskmaster` task) so a bare number like `484`
  isn't mistaken for a task id and no task scaffolding is created. Omit it
  (defaults to `work_type=task`) for ordinary `.taskmaster` tasks.
- **Base branch**: if the current branch is NOT `main`, add `base_branch=main`
  (unless the user explicitly wants to branch from the current branch). The
  workflow errors if you're on a feature branch without an explicit
  `base_branch`, to prevent building on unmerged work.
- **Copy a folder**: if the user mentions a folder or scratchpad to carry into
  the worktree, add `copy_folder=<relative-path>` (relative to repo root, e.g.
  `copy_folder=scratchpads/my-research`). Useful for gitignored notes that
  wouldn't exist in a fresh checkout.
- **Which agent**: defaults to `agent=codex` from this skill. Pass
  `agent=claude` if the user asks for Claude Code.
- **Don't open things**: `open_claude=false` skips launching the coding agent
  entirely (this gate applies to whichever `agent` is selected);
  `open_cursor=false` skips opening Cursor.

After it runs, tell the user whether the worktree was created and show the
worktree path. Mention that Cursor and the selected coding agent (Codex by
default, or Claude Code if `agent=claude`) have been opened in the new worktree,
unless those were disabled.
