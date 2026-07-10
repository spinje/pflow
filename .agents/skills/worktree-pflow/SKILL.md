---
name: "worktree-pflow"
description: "Create a git worktree"
---
Create a git worktree for pflow development.

Run this command before proceeding:

```bash
git branch --show-current
```

Build and run the command:
```bash
uv run pflow examples/real-workflows/git-worktree-task-creator/workflow.pflow.md task_description='THE TASK DESCRIPTION'
```

**Parameter rules:**
- If the user has not supplied a task description, ask the user to clarify what task they want to create a worktree for.
- **If the work is a GitHub issue (the user gives an issue number, an issue URL, or says "issue"), add `work_type=issue`.** This labels it as a GitHub issue (not a pflow `.taskmaster` task) when the launched Claude session opens, so a bare issue number like `443` isn't mistaken for a task id and no task scaffolding is created. Omit it (defaults to `work_type=task`) for ordinary `.taskmaster` tasks.
- If the current branch is NOT `main`, add `base_branch=main` to the command (unless the user explicitly wants to branch from the current branch).
- If the user mentions a folder or scratchpad to copy into the worktree, add `copy_folder=<relative-path>` (path relative to repo root, e.g. `copy_folder=scratchpads/my-research`).
- **If the user asks to start the session with codex instead of Claude Code** (e.g. "use codex", "start with codex"), add `agent=codex`. Defaults to `agent=claude` otherwise. `open_cli` remains the on/off gate for launching the agent regardless of which one is selected.
- **If the user specifies a model** for the coding agent (e.g. "use opus", "run it on sonnet"), add `model=<model>` — passed through as `--model` to whichever agent launches (both `claude` and `codex` accept it). Accepts an alias (`opus`, `sonnet`) or a full model id (`claude-opus-4-8`). Omit it to use the agent's own default model.
- If the user specifically asks NOT to open cursor or the coding agent, add `open_cli=false` and/or `open_cursor=false`.
- **The workflow refuses to clobber an existing worktree/branch by default.** If it errors that the branch/worktree already exists and the user wants to re-run the **same** task and discard the old one, add `overwrite=true`. Do NOT add it just to make a collision go away for a *different* task — a collision between different tasks signals the branch name wasn't specific enough, so pass a more descriptive `task_description` instead.

Let the user know if the worktree was created successfully and display the path to the worktree.

Also let the user know that Cursor and the selected coding agent (Claude Code by default, or Codex if `agent=codex`) have been opened in the new worktree (if using default values for open_cli and open_cursor).
