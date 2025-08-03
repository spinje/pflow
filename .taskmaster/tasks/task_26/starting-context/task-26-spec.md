# Task 26: GitHub and Git Operation Nodes

## Objective

Create GitHub and Git operation nodes using GitHub CLI (gh) wrapper for workflow automation.

## Prerequisites

- GitHub CLI (gh) version 2.0+ installed on system
- User authenticated via `gh auth login`
- PocketFlow Node base class available
- Registry scanner functional for node discovery
- Shared store pattern established

## Requirements

- Must wrap gh CLI commands via subprocess
- Must parse JSON output to Python dictionaries
- Must integrate with shared store pattern (read inputs, write outputs)
- Must have name class attribute for registry discovery
- Must handle subprocess errors and return codes
- Must follow PocketFlow lifecycle (prep/exec/post/exec_fallback)

## Scope

### Included:
- `github-get-issue` node
- `github-list-issues` node
- `github-create-pr` node
- `git-status` node
- `git-commit` node
- `git-push` node

### Excluded:
- GitHub Actions workflow management
- Release management
- Repository creation/deletion
- Team/organization management
- GraphQL API operations
- Webhook management

## Inputs

### For all nodes:
- `shared`: dict - Shared store containing node-specific inputs
- `params`: dict - Node parameters via `set_params()`

### Node-specific inputs in shared/params:

#### `github-get-issue`:
- `issue_number`: str|int - Issue number to fetch
- `repo`: str - Repository in "owner/repo" format (optional, uses current if omitted)

#### `github-list-issues`:
- `repo`: str - Repository in "owner/repo" format (optional)
- `state`: str - Issue state: "open", "closed", "all" (default: "open")
- `limit`: int - Maximum issues to return (default: 30)

#### `github-create-pr`:
- `title`: str - PR title
- `body`: str - PR description
- `head`: str - Head branch name
- `base`: str - Base branch name (default: "main")
- `repo`: str - Repository (optional)

#### `git-status`:
- No required inputs (uses current directory)

#### `git-commit`:
- `message`: str - Commit message
- `files`: list[str] - Files to add (optional, uses "." if omitted)

#### `git-push`:
- `branch`: str - Branch name (optional, uses current)
- `remote`: str - Remote name (default: "origin")

## Outputs

### `github-get-issue`:
- Writes `issue_data` to shared: dict containing issue details from gh CLI JSON output
- Expected to include fields like number, title, body, state, and nested author/labels data
- ⚠️ VERIFY actual gh output structure and transform as needed for Task 17 compatibility

### `github-list-issues`:
- Writes `issues` to shared: array of issue objects from gh CLI JSON output

### `github-create-pr`:
- Writes `pr_data` to shared: dict containing PR details from gh CLI JSON output
- Expected to include PR number and URL at minimum

### `git-status`:
- Writes `git_status` to shared: dict containing repository status information
- Structure depends on gh/git command output format

### `git-commit`:
- Writes `commit_sha` to shared: string
- Writes `commit_message` to shared: string

### `git-push`:
- Writes `push_result` to shared: dict containing push operation results

All nodes return action string: `"default"`

**Note**: Exact output structures depend on gh CLI version and must be verified during implementation

## Structured Formats

```json
{
  "node_classes": {
    "github-get-issue": {
      "name": "github-get-issue",
      "location": "src/pflow/nodes/github/get_issue.py",
      "class_name": "GitHubGetIssueNode"
    },
    "github-list-issues": {
      "name": "github-list-issues",
      "location": "src/pflow/nodes/github/list_issues.py",
      "class_name": "GitHubListIssuesNode"
    },
    "github-create-pr": {
      "name": "github-create-pr",
      "location": "src/pflow/nodes/github/create_pr.py",
      "class_name": "GitHubCreatePRNode"
    },
    "git-status": {
      "name": "git-status",
      "location": "src/pflow/nodes/git/status.py",
      "class_name": "GitStatusNode"
    },
    "git-commit": {
      "name": "git-commit",
      "location": "src/pflow/nodes/git/commit.py",
      "class_name": "GitCommitNode"
    },
    "git-push": {
      "name": "git-push",
      "location": "src/pflow/nodes/git/push.py",
      "class_name": "GitPushNode"
    }
  }
}
```

## State/Flow Changes

- None

## Constraints

- gh CLI must be installed and authenticated
- Repository operations require appropriate permissions
- Rate limits apply (5000 requests/hour for authenticated users)
- JSON output from gh must be parseable
- Subprocess timeout: 30 seconds default

## Rules

1. All nodes must have name class attribute matching their command name
2. If subprocess returns non-zero exit code, raise ValueError with stderr content
3. Parse JSON output using `json.loads()` in `exec()` method
4. If JSON parsing fails, raise ValueError with original output
5. Store parsed data in shared store using documented key names in `post()`
6. Return `"default"` from `post()` method
7. Use `subprocess.run()` with `capture_output=True` and `text=True`
8. Set `timeout=30` for `subprocess.run()` calls
9. If repo parameter is omitted, let gh use current directory
10. For `github-list-issues`, limit parameter must be between 1 and 100
11. For `git-commit`, if files parameter is omitted, use `["."]` as default
12. For `git-push`, if branch is omitted, use current branch via `"HEAD"`
13. All string parameters must be non-empty when provided
14. Issue numbers must be positive integers or numeric strings
15. Repository format must match "owner/repo" pattern when provided
16. Branch names must not contain spaces or special characters except dash and underscore
17. Parse gh JSON output and store in shared with appropriate transformations
18. Transform field names as needed for Task 17 compatibility (e.g., author → user)
19. Log subprocess command before execution at debug level
20. Include gh command in error messages for debugging

## Edge Cases

- gh not installed → `subprocess.FileNotFoundError`
- gh not authenticated → stderr contains "not authenticated"
- Repository not found → stderr contains "Could not resolve"
- Issue not found → stderr contains "Could not find issue"
- Network timeout → `subprocess.TimeoutExpired`
- Invalid JSON from gh → `json.JSONDecodeError`
- Rate limit exceeded → stderr contains "rate limit"
- No git repository → stderr contains "not a git repository"
- Nothing to commit → git-commit returns exit code 1
- Push rejected → stderr contains "rejected"
- Branch doesn't exist → stderr contains "unknown revision"

## Error Handling

- `FileNotFoundError` → "GitHub CLI (gh) not found. Install from https://cli.github.com"
- "not authenticated" in stderr → "Not authenticated. Run 'gh auth login' first"
- "Could not resolve" in stderr → "Repository '{repo}' not found"
- "Could not find issue" in stderr → "Issue #{issue_number} not found"
- `TimeoutExpired` → "Command timed out after 30 seconds"
- `JSONDecodeError` → "Failed to parse JSON output: {output}"
- "rate limit" in stderr → "GitHub API rate limit exceeded"
- "not a git repository" in stderr → "Not in a git repository"
- Exit code 1 from git-commit → "Nothing to commit"
- "rejected" in stderr → "Push rejected: {stderr}"
- "unknown revision" in stderr → "Branch '{branch}' not found"

## Non-Functional Criteria

- Subprocess execution completes within 30 seconds
- Memory usage under 50MB per node execution
- Support concurrent node execution (subprocess isolation)
- Debug logging includes full command and timing

## Examples

### `github-get-issue`

```python
node = GitHubGetIssueNode()
node.set_params({"repo": "owner/repo"})
shared = {"issue_number": "123"}
node.run(shared)
# shared["issue_data"] = {"number": 123, "title": "Bug", ...}
```

### `git-commit`

```python
node = GitCommitNode()
shared = {"message": "Fix: Update auth logic", "files": ["auth.py"]}
node.run(shared)
# shared["commit_sha"] = "abc123..."
# shared["commit_message"] = "Fix: Update auth logic"
```

### `github-create-pr`

```python
node = GitHubCreatePRNode()
shared = {
    "title": "Feature: Add OAuth",
    "body": "Implements OAuth 2.0",
    "head": "feature-oauth",
    "base": "main"
}
node.run(shared)
# shared["pr_data"] = {"number": 456, "url": "...", ...}
```

## Test Criteria

1. Node has name attribute → verify `class.name` exists
2. Subprocess error handling → mock `subprocess.run` with `returncode=1`
3. JSON parsing → verify `json.loads` called on stdout
4. JSON parse error → mock `json.loads` to raise `JSONDecodeError`
5. Shared store write → verify `shared[key]` set in `post()`
6. Default action return → verify `post()` returns `"default"`
7. Timeout handling → mock `subprocess.run` to raise `TimeoutExpired`
8. Missing gh binary → mock `subprocess.run` to raise `FileNotFoundError`
9. Auth error detection → mock stderr with "not authenticated"
10. Repository parameter → verify `--repo` flag added when provided
11. Default repo behavior → verify no `--repo` flag when omitted
12. Issue number string → verify "123" converted correctly
13. Issue number integer → verify 123 handled correctly
14. List limit validation → verify limit clamped to 1-100
15. Git files default → verify `["."]` used when files omitted
16. Push branch default → verify `"HEAD"` used when branch omitted
17. Empty string parameter → verify `ValueError` raised
18. Invalid repo format → verify "invalid-format" raises error
19. Branch name validation → verify "my branch" raises error
20. Field transformation → verify field name transformations work correctly
21. Command logging → verify debug log contains command
22. Error message includes command → verify `ValueError` contains gh command

## Notes (Why)

- GitHub CLI chosen for MVP speed over API libraries (1-2 hours per node vs 2-3 hours)
- JSON output provides structured data without API client complexity
- Subprocess approach enables quick iteration and testing
- Rate limiting handled by gh automatically with clear errors
- Authentication managed externally via gh auth for security
- Six nodes provide sufficient GitHub/Git operations for Task 17 examples

## Compliance Matrix

| Rule # | Test Criteria # | Notes                       |
|--------|-----------------|-----------------------------|
| 1      | 1               | Name attribute verification |
| 2      | 2               | Subprocess error handling   |
| 3      | 3               | JSON parsing                |
| 4      | 4               | JSON parse error            |
| 5      | 5               | Shared store write          |
| 6      | 6               | Default action              |
| 7      | 2, 3            | Subprocess configuration    |
| 8      | 7               | Timeout handling            |
| 9      | 10, 11          | Repository parameter        |
| 10     | 14              | List limit validation       |
| 11     | 15              | Git files default           |
| 12     | 16              | Push branch default         |
| 13     | 17              | Empty string check          |
| 14     | 12, 13          | Issue number types          |
| 15     | 18              | Repo format validation      |
| 16     | 19              | Branch name validation      |
| 17     | 3               | Parse and transform output  |
| 18     | 20              | Field transformations       |
| 19     | 21              | Command logging             |
| 20     | 22              | Error messages              |

## Versioning & Evolution

- v1.0.0 — Initial implementation with 6 core nodes
- v2.0.0 — Add workflow dispatch, release management
- v3.0.0 — GraphQL support for complex queries
- v4.0.0 — MCP server integration option

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes gh CLI v2.0+ JSON output format stability
- Unknown if gh handles all GitHub Enterprise endpoints identically
- Assumes subprocess isolation sufficient for concurrent execution
- Unknown optimal timeout value for slow network conditions

### Conflicts & Resolutions

- No conflicts identified with existing codebase

### Decision Log / Tradeoffs

- Chose subprocess over API library: Speed of implementation (1 day) vs performance overhead (50-100ms)
- Chose 30-second timeout: Balance between slow networks and hanging processes
- Chose JSON-only output: Structured data vs human-readable format flexibility
- Chose external auth: Security (no tokens in code) vs setup complexity

### Ripple Effects / Impact Map

- Registry will discover 6 new nodes automatically
- Task 17 planner can generate GitHub workflows
- Template variables get rich nested data structures
- CLI users can automate GitHub operations
- Test suite needs gh mock fixtures

### Residual Risks & Confidence

- Risk: gh CLI breaking changes; Mitigation: Pin version in docs
- Risk: Network timeouts in CI; Mitigation: Configurable timeout
- Risk: Rate limiting during tests; Mitigation: Mock subprocess calls
- Confidence: High for core operations, Medium for error edge cases

### Epistemic Audit (Checklist Answers)

1. Assumed gh JSON format stability without version checking
2. JSON parsing would fail silently if format changes
3. No, chose robustness (subprocess isolation) over elegance
4. Yes, all 20 rules map to tests, all 22 tests map to rules/edges
5. Registry scanning, Task 17 workflows, template validation
6. Optimal timeout value uncertain; Confidence: High for MVP functionality
