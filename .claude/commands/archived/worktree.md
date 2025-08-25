---
allowed-tools: Bash(git worktree:*), Bash(git branch:*), Bash(cd:*), Bash(pwd), Bash(claude:*), Bash(open:*), Bash(code:*), Bash(cursor:*)
argument-hint: [task-description]
description: Create git worktree for new feature/task and open in new Claude instance
---

## Current Git Status

The following commands are automatically executed to provide context:
!`git status --short`
!`git branch --show-current`

## Task Description

Task to work on: $ARGUMENTS

## Instructions

First, review the git status output above:
- If there are uncommitted changes (M, A, or ?? files), warn the user they should commit or stash first
- Note the current branch to determine if we should branch from it or from main
- If status is clean and on main, proceed directly to creating the worktree

Based on the task description and git status, execute these exact commands:

1. First, determine the branch name based on the task:
   - For new features: `feat/feature-name`
   - For bug fixes: `fix/bug-description`
   - For documentation: `docs/doc-topic`
   - For refactoring: `refactor/component-name`
   - For tests: `test/test-description`
   - Use kebab-case for the name part

2. Execute these commands in sequence:

```bash
# Create the worktree with a new branch
git worktree add ../pflow-BRANCH_NAME -b BRANCH_NAME

# Navigate to the new worktree
cd ../pflow-BRANCH_NAME

# Launch Claude Code in the new worktree
claude
```

Replace BRANCH_NAME with the actual branch name you determined (e.g., `feat/authentication-system`, `fix/validation-bug`).

Example for task "add authentication system":
```bash
git worktree add ../pflow-feat-authentication-system -b feat/authentication-system
cd ../pflow-feat-authentication-system
claude
```

Example for task "fix validation bug":
```bash
git worktree add ../pflow-fix-validation-bug -b fix/validation-bug
cd ../pflow-fix-validation-bug
claude
```

3. After executing, provide a summary showing:
   - Branch created: [branch name]
   - Worktree location: [full path]
   - Claude Code launched: Yes/No

## Important Notes

- **Git Status Check**: The command automatically runs `git status` and `git branch` first to check if you have uncommitted work that needs to be saved
- **Isolation**: Each worktree is completely isolated - you can work on multiple features simultaneously without conflicts
- **Branching**: New branches are created from your current HEAD position (usually main, but could be another branch if that's where you are)