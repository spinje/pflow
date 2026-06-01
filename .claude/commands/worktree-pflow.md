---
description: Create a git worktree
argument-hint: [description of task]
---
Create a git worktree for pflow development.

!`git branch --show-current`

Build and run the command:
```bash
uv run pflow git-worktree-task-creator task_description='$ARGUMENTS'
```

**Parameter rules:**
- If `$ARGUMENTS` is empty, ask the user to clarify what task they want to create a worktree for.
- **If the work is a GitHub issue (the user gives an issue number, an issue URL, or says "issue"), add `work_type=issue`.** This labels it as a GitHub issue (not a pflow `.taskmaster` task) when the launched Claude session opens, so a bare issue number like `443` isn't mistaken for a task id and no task scaffolding is created. Omit it (defaults to `work_type=task`) for ordinary `.taskmaster` tasks.
- If the current branch is NOT `main`, add `base_branch=main` to the command (unless the user explicitly wants to branch from the current branch).
- If the user mentions a folder or scratchpad to copy into the worktree, add `copy_folder=<relative-path>` (path relative to repo root, e.g. `copy_folder=scratchpads/my-research`).
- If the user specifically asks NOT to open cursor or claude, add `open_claude=false` and/or `open_cursor=false`.

Let the user know if the worktree was created successfully and display the path to the worktree.

Also let the user know that cursor and claude code have been opened in the new worktree (if using default values for open_claude and open_cursor).
