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

Analyze the task description and git status to create a worktree with automated Claude launch.

### CRITICAL: Handling Uncommitted Changes

**FIRST, analyze the uncommitted changes from git status above:**

1. **ONLY use --bring-changes flag if ALL of these conditions are met:**
   - The changes are DIRECTLY RELATED to the task (e.g., PRD files, planning docs, scratchpads for THIS specific feature)
   - The files contain: task descriptions, requirements, or planning for the exact feature being worked on
   - Example VALID cases:
     - Task: "implement github-list-prs" and changes include "scratchpads/github-list-prs/*" or "docs/prd-github-list-prs.md"
     - Task: "fix validation bug" and changes include "tests/test_validation_bug.py" (a failing test for the bug)
   
2. **NEVER use --bring-changes if:**
   - Changes are unrelated to the task
   - Changes include work on OTHER features
   - Changes include general project files (configs, other nodes, unrelated tests)
   - You're not 100% certain the changes belong in the new branch

3. **When in doubt, STOP and ask:**
   ```
   I see uncommitted changes:
   [list the changes]
   
   Should I:
   a) Bring these changes to the new worktree (they're part of this feature)
   b) Leave them in main (they're unrelated)
   c) You should commit or stash them first
   ```

### After analyzing changes, proceed:

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
# WITHOUT bringing changes (default):
./.claude/commands/scripts/worktree-claude.sh <BRANCH_TYPE> <BRANCH_NAME> "$ARGUMENTS"

# WITH bringing changes (ONLY if conditions above are met):
./.claude/commands/scripts/worktree-claude.sh <BRANCH_TYPE> <BRANCH_NAME> "$ARGUMENTS" --bring-changes
```

**Concrete examples:**

**Scenario 1: Related changes - BRING them**
- Task: "implement github-list-prs node"
- Git status shows: `?? scratchpads/github-list-prs/`, `?? docs/prd-github-list-prs.md`
- → Run: `./.claude/commands/scripts/worktree-claude.sh feat github-list-prs "implement github-list-prs node" --bring-changes`

**Scenario 2: Unrelated changes - DON'T bring them**
- Task: "fix validation error in compiler"
- Git status shows: `M src/nodes/github/list_issues.py`, `?? docs/unrelated-feature.md`
- → Run: `./.claude/commands/scripts/worktree-claude.sh fix validation-compiler "fix validation error in compiler"`
- → (No --bring-changes flag!)

**Scenario 3: Mixed/unclear - ASK the user**
- Task: "add documentation for API"
- Git status shows: Various changed files
- → STOP and ask user what to do with the changes

4. **After executing, report:**
   - Whether the script succeeded
   - The branch name created
   - Worktree location
   - Whether terminal opened automatically (macOS/Linux) or manual steps needed

The script will handle git status checks, existing worktree conflicts, and terminal launching automatically.