---
allowed-tools: Bash(git status:*), Bash(git branch:*), Bash(git log:*), Bash(git diff:*), Bash(git push:*), Bash(gh pr:*), Bash(git remote:*), Bash(git rev-parse:*), Bash(gh auth:*)
argument-hint: [pr-title-or-description]
description: Create a GitHub pull request from current branch
---

## Current Git Context

!`git status --short`
!`git branch --show-current`
!`git log --oneline -10`
!`git remote -v | head -1`
!`git rev-parse --abbrev-ref origin/HEAD 2>/dev/null || echo "origin/main"`
!`git rev-list --count @{u}..HEAD 2>/dev/null || echo "Branch not tracked remotely"`
!`gh auth status 2>&1 | head -3`

## Task: Create PR - $ARGUMENTS

## Instructions

Create a pull request based on the current branch and recent commits:

1. **Verify prerequisites:**
   - Confirm `gh` CLI is authenticated (check auth status output above)
   - Check if we're on a feature branch (not on the default branch)
   - Ensure all changes are committed (no modified files in git status)
   - Determine the default branch from git output (usually main or master)

2. **Analyze commits to generate PR details:**
   - Review the commit history shown above
   - Identify the type of change (feature, fix, refactor, etc.)
   - Extract key changes for PR description
   - Look for patterns like "feat:", "fix:", etc. in commit messages

3. **Push branch if needed:**
   ```bash
   # First check if remote tracking exists
   git branch -vv | grep $(git branch --show-current)
   
   # If no remote tracking, push the branch
   git push -u origin $(git branch --show-current)
   ```

4. **Create the PR with appropriate title and body:**

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
     
     ## Testing
     - How to test these changes
     ```

5. **Execute the PR creation and capture the URL:**
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
Run \`make test\` to verify all tests pass."
```

For a simple fix:
```bash
gh pr create --title "fix: Resolve validation error in compiler" --body "Fixes validation bug when processing nested workflows"
```

6. **After PR creation:**
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

**Important checks:**
- If current branch equals default branch, refuse to create PR (explain that PRs must be from feature branches)
- If gh auth fails, provide instructions to run `gh auth login`
- If no commits differ from default branch, explain there's nothing to PR
- If uncommitted changes exist, ask user to commit or stash first