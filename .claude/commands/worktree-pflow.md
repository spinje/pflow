---
description: Create a git worktree
argument-hint: [description of task]
---
Run this bash command to create a git worktree for pflow:

```bash
uv run pflow git-worktree-task-creator task_description='$ARGUMENTS'
```

The task_description has been prefilled for you. Just run the command as is. If the task_description is empty, ask the user to clarify what task they want to create a worktree for.

Let the user know if the worktree was created successfully and display the path to the worktree.

Also let the user know that cursor and claude code have been opened in the new worktree (if using default values for open_claude and open_cursor).

---

Note: if the user specifically askes NOT to open cursor or claude use these additional fields: open_claude=false, open_cursor=false