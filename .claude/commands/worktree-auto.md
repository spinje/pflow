---
allowed-tools: Bash(./.claude/commands/scripts/worktree-claude.sh:*), Bash(git status:*), Bash(git branch:*), Bash(pwd)
argument-hint: [task-description]
description: Create git worktree and auto-open Claude in new terminal
---

## Current Git Status

!`git status --short`
!`git branch --show-current`

## Task: $ARGUMENTS

## Instructions

Analyze the task description and create a worktree with automated Claude launch:

1. **Parse the task to determine branch type and name:**
   - If task contains "implement", "add", "create", "build" → use `feat/`
   - If task contains "fix", "bug", "repair", "resolve" → use `fix/`
   - If task contains "document", "docs", "readme" → use `docs/`
   - If task contains "refactor", "restructure", "reorganize" → use `refactor/`
   - If task contains "test", "testing", "spec" → use `test/`
   - Default to `feat/` if unclear

2. **Extract a branch name from the task:**
   - Take key words from the task description
   - Convert to kebab-case (lowercase, hyphens instead of spaces)
   - Remove articles (a, an, the) and prepositions
   - Keep it concise (2-4 words max)

3. **Execute the worktree script with these exact parameters:**

```bash
# Run this command with the determined values:
./.claude/commands/scripts/worktree-claude.sh <BRANCH_TYPE> <BRANCH_NAME> "$ARGUMENTS"
```

**Concrete examples:**
- Task: "implement github-list-prs node"
  → Run: `./.claude/commands/scripts/worktree-claude.sh feat github-list-prs "implement github-list-prs node"`
  
- Task: "fix validation error in compiler"
  → Run: `./.claude/commands/scripts/worktree-claude.sh fix validation-compiler "fix validation error in compiler"`
  
- Task: "add documentation for new API endpoints"
  → Run: `./.claude/commands/scripts/worktree-claude.sh docs api-endpoints "add documentation for new API endpoints"`

4. **After executing, report:**
   - Whether the script succeeded
   - The branch name created
   - Worktree location
   - Whether terminal opened automatically (macOS/Linux) or manual steps needed

The script will handle git status checks, existing worktree conflicts, and terminal launching automatically.