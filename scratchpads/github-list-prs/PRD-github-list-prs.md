# PRD: GitHub List Pull Requests Node (`github-list-prs`)

## Executive Summary

Implement a `github-list-prs` node to list pull requests from GitHub repositories using the GitHub CLI. This node is critical for the "Weekly Project Summary" north star example and complements the existing `github-list-issues` node.

## Problem Statement

The north star example "Create Weekly Project Summary" requires listing both issues AND pull requests. Currently, we can list issues but not PRs, blocking this workflow from being fully functional.

## Goals

1. **Enable PR listing** with filtering by state, author, assignee, base/head branches
2. **Follow established patterns** from existing GitHub nodes exactly
3. **Provide structured PR data** in native GitHub field names
4. **Support comprehensive filtering** for real-world use cases

## Implementation Specification

### Node Identity

- **File**: `src/pflow/nodes/github/list_prs.py`
- **Class**: `ListPRsNode`
- **Registry Name**: `github-list-prs`
- **Node Type**: GitHub operation node

### Interface Definition

```python
"""
List GitHub repository pull requests.

Interface:
- Reads: shared["repo"]: str  # Repository in owner/repo format (optional, default: current repo)
- Reads: shared["state"]: str  # PR state: open, closed, merged, all (optional, default: open)
- Reads: shared["limit"]: int  # Maximum PRs to return (optional, default: 30)
- Reads: shared["author"]: str  # Filter by author username (optional)
- Reads: shared["assignee"]: str  # Filter by assignee username (optional)
- Reads: shared["base"]: str  # Filter by base branch (optional)
- Reads: shared["head"]: str  # Filter by head branch (optional)
- Reads: shared["draft"]: bool  # Include only draft PRs (optional)
- Writes: shared["prs"]: list[dict]  # Array of PR objects
    - number: int  # PR number
    - title: str  # PR title
    - state: str  # PR state (OPEN, CLOSED, MERGED)
    - author: dict  # PR author information
        - login: str  # Username
    - isDraft: bool  # Whether PR is a draft
    - baseRefName: str  # Base branch name
    - headRefName: str  # Head branch name
    - labels: list[dict]  # PR labels
        - name: str  # Label name
    - assignees: list[dict]  # PR assignees
        - login: str  # Username
    - reviewDecision: str  # Review status (APPROVED, CHANGES_REQUESTED, etc.)
    - createdAt: str  # Creation timestamp
    - updatedAt: str  # Last update timestamp
    - mergedAt: str  # Merge timestamp (if merged)
    - closedAt: str  # Close timestamp (if closed)
- Actions: default (always)
"""
```

### Core Implementation

#### 1. Initialization
```python
def __init__(self, max_retries: int = 3, wait: float = 1.0):
    """Initialize with retry support matching other GitHub nodes."""
    super().__init__(max_retries=max_retries, wait=wait)
```

#### 2. Prep Method
```python
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    # 1. Check authentication FIRST
    auth_result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
        timeout=10
    )
    if auth_result.returncode != 0:
        raise ValueError("GitHub CLI not authenticated. Please run 'gh auth login'")

    # 2. Parameter extraction with fallback pattern
    repo = shared.get("repo") or self.params.get("repo")
    state = shared.get("state") or self.params.get("state", "open")
    limit = shared.get("limit") or self.params.get("limit", 30)
    author = shared.get("author") or self.params.get("author")
    assignee = shared.get("assignee") or self.params.get("assignee")
    base = shared.get("base") or self.params.get("base")
    head = shared.get("head") or self.params.get("head")
    draft = shared.get("draft") or self.params.get("draft")

    # 3. Validation
    valid_states = ["open", "closed", "merged", "all"]
    if state not in valid_states:
        raise ValueError(f"Invalid PR state '{state}'. Must be one of: {', '.join(valid_states)}")

    # Clamp limit to valid range
    try:
        limit = int(limit)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid limit value '{limit}'. Must be an integer between 1 and 100.") from e

    limit = max(1, min(100, limit))  # Clamp to 1-100

    return {
        "repo": repo,
        "state": state,
        "limit": limit,
        "author": author,
        "assignee": assignee,
        "base": base,
        "head": head,
        "draft": draft
    }
```

#### 3. Exec Method (NO try/except!)
```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    """Execute gh pr list - NO exception handling! Let errors bubble for retry."""

    # Build command
    cmd = ["gh", "pr", "list", "--json",
           "number,title,state,author,isDraft,baseRefName,headRefName,"
           "labels,assignees,reviewDecision,createdAt,updatedAt,mergedAt,closedAt"]

    # Add optional parameters
    if prep_res["repo"]:
        cmd.extend(["--repo", prep_res["repo"]])

    cmd.extend(["--state", prep_res["state"]])
    cmd.extend(["--limit", str(prep_res["limit"])])

    if prep_res["author"]:
        cmd.extend(["--author", prep_res["author"]])
    if prep_res["assignee"]:
        cmd.extend(["--assignee", prep_res["assignee"]])
    if prep_res["base"]:
        cmd.extend(["--base", prep_res["base"]])
    if prep_res["head"]:
        cmd.extend(["--head", prep_res["head"]])
    if prep_res["draft"]:
        cmd.append("--draft")

    # Execute - NO try/except!
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        shell=False,  # CRITICAL: Security
        timeout=30
    )

    if result.returncode != 0:
        # Check for specific errors in stderr
        if "Could not resolve to a Repository" in result.stderr:
            repo = prep_res["repo"] or "current repository"
            raise ValueError(f"Repository '{repo}' not found or you don't have access.")
        elif "authentication required" in result.stderr.lower():
            raise ValueError("GitHub authentication required. Run 'gh auth login'.")
        else:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )

    # Parse JSON response
    prs = json.loads(result.stdout) if result.stdout.strip() else []

    return {"prs": prs}
```

#### 4. Post Method
```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    """Store PRs in shared store and return action."""
    shared["prs"] = exec_res["prs"]
    return "default"
```

#### 5. Exec Fallback Method
```python
def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
    """Transform errors to user-friendly messages after retries exhausted."""
    error_msg = str(exc)

    if "gh: command not found" in error_msg:
        return {
            "prs": [],
            "error": "Error: GitHub CLI not installed. Install with: brew install gh"
        }
    elif "authentication required" in error_msg.lower():
        return {
            "prs": [],
            "error": "Error: Not authenticated. Run 'gh auth login' to authenticate."
        }
    elif "Could not resolve to a Repository" in error_msg:
        repo = prep_res.get("repo", "current repository")
        return {
            "prs": [],
            "error": f"Error: Repository '{repo}' not found or no access."
        }
    elif "API rate limit exceeded" in error_msg:
        return {
            "prs": [],
            "error": "Error: GitHub API rate limit exceeded. Please wait before retrying."
        }
    else:
        return {
            "prs": [],
            "error": f"Error: Failed to list PRs after {self.max_retries} retries: {error_msg}"
        }
```

### GitHub CLI Command Details

**Base Command**:
```bash
gh pr list --json number,title,state,author,isDraft,baseRefName,headRefName,labels,assignees,reviewDecision,createdAt,updatedAt,mergedAt,closedAt
```

**Available Filters**:
- `--state {open|closed|merged|all}` - Filter by PR state
- `--limit N` - Limit number of results (max 100)
- `--author USERNAME` - Filter by author
- `--assignee USERNAME` - Filter by assignee
- `--base BRANCH` - Filter by base branch
- `--head BRANCH` - Filter by head branch
- `--draft` - Show only draft PRs
- `--repo OWNER/REPO` - Target specific repository

### Test Strategy

#### Unit Tests Required

File: `tests/test_nodes/test_github/test_list_prs.py`

1. **Authentication Tests**:
   - Test auth check failure raises ValueError
   - Test successful auth check continues

2. **Parameter Tests**:
   - Test fallback order: shared → params → defaults
   - Test state validation (valid and invalid)
   - Test limit clamping (0→1, 150→100, negative→1)
   - Test optional parameter handling

3. **Command Building Tests**:
   - Test base command structure
   - Test with all filters applied
   - Test security flags (shell=False, timeout=30)

4. **Execution Tests**:
   - Test successful execution with PRs
   - Test empty response handling
   - Test error bubbling (no try/except)

5. **Error Handling Tests**:
   - Test repository not found
   - Test authentication errors
   - Test rate limiting
   - Test exec_fallback transformations

6. **Retry Tests**:
   - Test transient failure retry
   - Test exhaustion after max_retries

#### Test Pattern Example
```python
@patch('subprocess.run')
def test_exec_success(mock_run):
    """Test successful PR listing."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout='[{"number": 123, "title": "Fix bug", "state": "OPEN", "author": {"login": "user"}}]',
        stderr=""
    )

    node = ListPRsNode()
    result = node.exec({"state": "open", "limit": 30})

    assert result["prs"][0]["number"] == 123
    assert result["prs"][0]["author"]["login"] == "user"  # Native field name!

    # Verify command structure
    call_args = mock_run.call_args[0][0]
    assert "gh" in call_args[0]
    assert "pr" in call_args[1]
    assert "list" in call_args[2]
    assert "--json" in call_args
```

### Critical Patterns to Follow

1. **NO Field Name Transformation**: Keep GitHub's native names (`createdAt`, not `created_at`)
2. **NO Exception Handling in exec()**: Let exceptions bubble for retry mechanism
3. **Parameter Fallback Pattern**: `shared.get("key") or self.params.get("key", default)`
4. **Security**: Always use `shell=False`, appropriate timeouts
5. **Auth Check First**: Always verify authentication in prep()
6. **Native Field Names**: Preserve GitHub's field names exactly as returned

### Key Differences from `github-list-issues`

| Aspect | list-issues | list-prs |
|--------|------------|----------|
| State values | open, closed, all | open, closed, **merged**, all |
| Output key | shared["issues"] | shared["prs"] |
| Unique fields | - | isDraft, baseRefName, headRefName, reviewDecision, mergedAt |
| Additional filters | - | --base, --head, --draft |
| Default fields | Standard issue fields | Extended PR fields including review status |

### Success Criteria

1. ✅ Node successfully lists PRs with various filters
2. ✅ Follows all established GitHub node patterns
3. ✅ Passes all unit tests
4. ✅ Integrates with registry and CLI
5. ✅ Enables "Weekly Project Summary" north star example
6. ✅ Preserves native GitHub field names
7. ✅ Handles errors gracefully with user-friendly messages
8. ✅ Supports all PR-specific filters (base, head, draft)
9. ✅ Returns comprehensive PR metadata including review status

### Usage Examples

```bash
# List open PRs
github-list-prs --state=open --limit=10

# List merged PRs by author
github-list-prs --state=merged --author=octocat

# List PRs for specific base branch
github-list-prs --base=main --state=all

# Filter draft PRs
github-list-prs --draft --state=open

# Target specific repository
github-list-prs --repo=owner/repo --state=merged --limit=50

# Weekly summary workflow (North Star Example)
github-list-issues --state=closed --limit=50 >>
github-list-prs --state=merged --limit=50 >>
llm --prompt="Create weekly summary: Issues: ${issues}, PRs: ${prs}"
```

### Implementation Notes

1. **Boolean Flag**: The `--draft` flag is boolean (present/absent), not a value flag
2. **Merged State**: PRs have a MERGED state that issues don't have
3. **Review Decision**: The `reviewDecision` field is unique to PRs and provides review status
4. **JSON Support**: Unlike `gh pr create`, `gh pr list` DOES support `--json` directly
5. **Null Fields**: Fields like `mergedAt` will be null for non-merged PRs
6. **Auth Requirement**: GitHub CLI must be authenticated before any operations
7. **Rate Limits**: Be aware of GitHub API rate limits (5000/hour authenticated)

### File Structure

```
src/pflow/nodes/github/
├── __init__.py
├── CLAUDE.md         # GitHub nodes documentation
├── create_pr.py      # Existing PR creation node
├── get_issue.py      # Existing issue fetching node
├── list_issues.py    # Existing issues listing node
└── list_prs.py       # NEW: PR listing node

tests/test_nodes/test_github/
├── __init__.py
├── test_create_pr.py
├── test_get_issue.py
├── test_list_issues.py
└── test_list_prs.py  # NEW: PR listing tests
```

### Timeline & Priority

- **Priority**: HIGH - Blocks north star example
- **Estimated Effort**: 4-6 hours
- **Dependencies**: None (uses existing patterns)
- **Testing**: 2-3 hours for comprehensive unit tests

This implementation will complete the GitHub node suite and enable comprehensive GitHub workflow automation within pflow, particularly enabling the "Weekly Project Summary" north star example.