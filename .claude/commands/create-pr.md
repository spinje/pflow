---
allowed-tools: Bash(git status:*), Bash(git branch:*), Bash(git log:*), Bash(git diff:*), Bash(git push:*), Bash(gh pr:*), Bash(git rev-parse:*), Bash(sed:*)
argument-hint: [pr-title-or-description]
description: Create a GitHub pull request from current branch
---

## Current Git Context

!`git status --short`
!`git branch --show-current`
!`git log --oneline --max-count=10`

## Task: Create PR - $ARGUMENTS

## Instructions

Create a pull request based on the current branch and recent commits:

1. **Check for session ID (for traceability):**
   - Check if you have access to your Claude session ID
   - This could be in environment variables, session context, or system info
   - If available, save it to include in the PR body for audit trail

2. **Verify prerequisites:**
   - First, determine the default branch:
     ```bash
     git rev-parse --abbrev-ref origin/HEAD 2>/dev/null || echo "origin/main"
     ```
   - Check for existing PR on current branch:
     ```bash
     gh pr list --head $(git branch --show-current) --limit 1
     ```
   - If existing PR found, ask user if they want to update it or create new one
   - Ensure we're on a feature branch (not main/master)
   - Ensure all changes are committed (check git status above)
   - If any commits are necessary, commit them with a good message (include the session id if available)

3. **Analyze commits to generate PR details:**
   - Show commits that will be in the PR:
     ```bash
     # Get default branch first
     DEFAULT_BRANCH=$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's/origin\///' || echo "main")
     # Show commits not in default branch
     git log origin/$DEFAULT_BRANCH..HEAD --oneline
     ```
   - Show file changes:
     ```bash
     git diff --stat origin/$DEFAULT_BRANCH...HEAD
     ```
   - Review the commit history
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
     <!-- If you have access to your Claude session ID, include it, otherwise dont mention claude at all -->
     🤖 Implemented by Claude (Session ID: <session-id-if-available>)
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

**Important Notes:**
- The simple git context shows recent commits and status
- During execution, you'll determine the default branch and show relevant diffs
- Always check for existing PRs before creating new ones
- Include Claude session ID if available for traceability
- The `git push -u` command works whether the branch exists remotely or not