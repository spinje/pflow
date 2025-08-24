---
allowed-tools: Bash(git status:*), Bash(git branch:*), Bash(git log:*), Bash(git diff:*), Bash(git push:*), Bash(gh pr:*), Bash(git rev-parse:*), Bash(git merge-base:*)
argument-hint: [pr-title-or-description]
description: Create a GitHub pull request from current branch
---

## Current Git Context

!`git status --short`
!`git branch --show-current`
!`git rev-parse --abbrev-ref origin/HEAD 2>/dev/null || echo "origin/main"`
!`git log origin/$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null || echo "main")..HEAD --oneline 2>/dev/null | head -10`
!`git diff --stat origin/$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null || echo "main")...HEAD 2>/dev/null || echo "No diff available"`
!`gh pr list --head $(git branch --show-current) --json number,title,state --jq '.[] | "PR #\(.number): \(.title) [\(.state)]"' 2>/dev/null || echo "No existing PR"`

## Task: Create PR - $ARGUMENTS

## Instructions

Create a pull request based on the current branch and recent commits:

1. **Check for session ID (for traceability):**
   - Check if you have access to your Claude session ID
   - This could be in environment variables, session context, or system info
   - If available, save it to include in the PR body for audit trail

2. **Verify prerequisites:**
   - Check for existing PR (see "No existing PR" or PR details above)
   - If existing PR found, ask user if they want to update it or create new one
   - Ensure we're on a feature branch (not on the default branch shown above)
   - Ensure all changes are committed (check git status above)
   - Note the files changed (see diff stat above)

3. **Analyze commits to generate PR details:**
   - Review the commit history shown above
   - If single commit: use its message as PR title (if no user args provided)
   - If multiple commits: synthesize a title from the changes
   - Identify the type of change (feature, fix, refactor, etc.)
   - Look for patterns like "feat:", "fix:", etc. in commit messages

4. **Push branch (handles both new and existing):**
   ```bash
   # This works whether branch exists on remote or not
   git push -u origin $(git branch --show-current)
   ```

5. **Create the PR with appropriate title and body:**

   If user provided arguments, use them as guidance for the title/description.
   
   Otherwise, generate from commits:
   - **Title format:** `<type>: <concise description>`
     - feat: New feature
     - fix: Bug fix
     - docs: Documentation
     - refactor: Code refactoring
     - test: Test additions
   
   - **Body format:**
     ```markdown
     ## Summary
     Brief description of changes
     
     ## Changes
     - Key change 1
     - Key change 2
     
     <!-- Include file stats from diff output if available -->
     
     ## Testing
     Run `make test` to verify all tests pass
     
     ---
     <!-- If you have access to your Claude session ID, include it -->
     🤖 Implemented by Claude (session: <session-id-if-available>)
     ```
     
     **Note:** If you have access to your session ID (check environment variables or session context), always include it at the end of the PR body. This allows reviewers or other agents to reference this specific implementation session for questions or clarifications.

6. **Execute the PR creation and capture the URL:**
   ```bash
   # Create PR and capture the URL that gh outputs
   gh pr create --title "<title>" --body "<body>" --base <default-branch>
   # The command outputs the PR URL which should be captured and displayed
   ```
   
   Or for interactive web-based creation:
   ```bash
   gh pr create --web
   ```
   
   Or to create as draft:
   ```bash
   gh pr create --title "<title>" --body "<body>" --base <default-branch> --draft
   ```
   
   Note: The `gh pr create` command returns the PR URL in its output. Always capture and display this URL prominently for the user.

**Examples:**

For a feature branch with commits about adding a new node:
```bash
gh pr create --title "feat: Add github-list-prs node" --body "## Summary
Implements a new node for listing pull requests from GitHub repositories.

## Changes
- Added github-list-prs node implementation
- Added comprehensive tests
- Updated documentation

## Testing
Run \`make test\` to verify all tests pass.

---
🤖 Implemented by Claude (session: abc123-def456)"
```

For a simple fix:
```bash
gh pr create --title "fix: Resolve validation error in compiler" --body "Fixes validation bug when processing nested workflows

---
🤖 Implemented by Claude (session: xyz789-ghi012)"
```

7. **After PR creation:**
   - Capture the PR URL from the gh command output
   - Display a success message with the clickable PR link
   - Format: "✅ PR created successfully: [URL]"
   - Suggest next steps (request review, add labels, etc.)
   
   Example output to show user:
   ```
   ✅ Pull request created successfully!
   
   PR URL: https://github.com/owner/repo/pull/123
   
   Next steps:
   - Request reviewers if needed
   - Add labels to categorize the PR
   - Link to any related issues
   ```

**Edge cases handled automatically:**
- Existing PR detection (shown in git context above)
- Branch push status (push -u works for both cases)
- Authentication (gh pr create will fail with clear message if not authenticated)
- Uncommitted changes (visible in git status)
- Default branch detection (shown in context)