# Task 26: GitHub and Git Operation Nodes

## ID
26

## Title
GitHub and Git Operation Nodes

## Description
Create GitHub and Git operation nodes using GitHub CLI (gh) for GitHub operations and native git commands for version control automation. These nodes are critical for unblocking Task 17 (Natural Language Planner), enabling the canonical "fix github issue 1234" workflow example that demonstrates pflow's real-world value beyond simple file operations.

## Status
not started

## Dependencies
- Task 5: Node Discovery and Registry - The registry scanner must be able to discover and register the new GitHub/Git nodes
- Task 7: Extract Node Metadata from Docstrings - The metadata extractor must parse the Interface docstrings with nested structure for issue_data fields
- Task 11: Implement File Operation Nodes - Provides the node implementation patterns and testing approaches to follow
- Task 12: Implement LLM Node - Provides the pattern for wrapping external tools via subprocess and handling retries

## Priority
high

## Details
This task implements six essential nodes that enable GitHub and Git automation workflows. The implementation has been thoroughly researched and all GitHub CLI behavior has been verified through documentation analysis.

### Nodes to Implement

**GitHub Nodes (using gh CLI):**
- `github-get-issue`: Fetches issue details with verified JSON structure including author, labels, assignees
- `github-list-issues`: Lists repository issues with filtering options
- `github-create-pr`: Creates pull requests (two-step process: create returns URL, then fetch full data)

**Git Nodes (using native git commands):**
- `git-status`: Parses `git status --porcelain=v2` output to structured JSON
- `git-commit`: Stages files and creates commits using native git commands
- `git-push`: Pushes commits to remote repository

### Key Implementation Decisions

**Field Names (Verified):**
- Use native gh field names without transformation: `author` (not `user`), `createdAt` (not `created_at`)
- Task 17 will be updated to use correct paths like `$issue_data.author.login`
- All field structures have been verified against GitHub CLI documentation

**Technical Approach:**
- Subprocess execution with `shell=False` for security
- 30-second timeout for all subprocess calls
- Parameter fallback pattern: shared → params → defaults
- No try/catch in exec() - let exceptions bubble for retry mechanism
- Transform errors in exec_fallback() to user-friendly messages

**PR Creation Workflow:**
Since `gh pr create` returns only a URL (not JSON), implementation requires:
1. Create PR and capture URL from stdout
2. Parse PR number from URL using regex
3. Call `gh pr view` with JSON flag to get full PR data

**Git Status Parsing:**
Git doesn't support JSON output, so parse porcelain format:
```
1 .M N... 100644 100644 100644 abc123 def456 file.py
```
Into structured format:
```json
{
  "modified": ["file.py"],
  "untracked": [],
  "staged": [],
  "branch": "main",
  "ahead": 0,
  "behind": 0
}
```

### Interface Docstring Format
Use verified nested structure format for the metadata parser:
```python
"""
Interface:
- Writes: shared["issue_data"]: dict  # Complete issue details
    - number: int  # Issue number
    - author: dict  # Issue author information
      - login: str  # Username
      - name: str  # Full name
"""
```

### Directory Structure
```
src/pflow/nodes/
├── github/
│   ├── __init__.py
│   ├── get_issue.py
│   ├── list_issues.py
│   └── create_pr.py
└── git/
    ├── __init__.py
    ├── status.py
    ├── commit.py
    └── push.py
```

## Test Strategy
Following the patterns from Task 12 (LLM node), comprehensive testing will include:

**Unit Tests (Mocked Subprocess):**
- Mock subprocess.run for all gh and git commands
- Test successful command execution with verified JSON structures
- Test all error conditions (auth failures, not found, rate limits)
- Test retry behavior for transient failures
- Test parameter fallback (shared → params)
- Verify exact command construction

**Error Scenarios:**
- gh not authenticated: "Run 'gh auth login' first"
- Repository not found: stderr contains "Could not resolve"
- Issue not found: stderr contains "Could not find issue"
- Network timeout: subprocess.TimeoutExpired
- Invalid JSON: json.JSONDecodeError
- Not in git repository: "not a git repository"

**Integration Tests (Optional):**
- Skip by default with pytest markers
- Enable with RUN_GITHUB_TESTS=1 environment variable
- Use safe read-only commands like `gh auth status`
- Test with real gh CLI when available

**Key Test Patterns:**
- Use Mock and patch from unittest.mock
- Set wait=0.01 for fast retry testing
- Verify subprocess called with correct arguments
- Test command injection protection
- Validate native field names preserved (no transformation)
