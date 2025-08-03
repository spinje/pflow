# CLAUDE.md - GitHub Node Development Guide

## ⚠️ CRITICAL LIMITATIONS

1. **PR Creation Returns URL Only**: `gh pr create` does NOT support `--json` flag. You MUST parse the URL and make a second call to get data.
2. **Authentication Is External**: Nodes cannot handle auth directly. Users must run `gh auth login` separately.
3. **Not All Commands Have JSON**: Always verify a command supports `--json` before assuming it does.
4. **Rate Limits Are Real**: 5000 requests/hour for authenticated users. Errors appear in stderr.
5. **Field Names Are Immutable**: GitHub CLI returns `author` (not `user`), `createdAt` (not `created_at`). DO NOT transform these.

## 🎯 Core Purpose

These nodes wrap the GitHub CLI (`gh`) to provide GitHub operations within pflow workflows. They enable:
- Fetching issue and PR data
- Creating PRs and issues
- Listing and searching repositories
- Managing GitHub resources

**Key Design Decision**: We use `gh` CLI instead of the GitHub API because:
- Zero Python dependencies
- Authentication handled externally (more secure)
- Consistent with command-line workflow philosophy
- 50-100ms overhead is acceptable for MVP

## 🚨 Common Pitfalls

### 1. Assuming JSON Output Exists
```python
# WRONG - gh pr create doesn't support --json
cmd = ["gh", "pr", "create", "--json", "number,url"]  # WILL FAIL

# RIGHT - Parse URL, then fetch data
result = subprocess.run(["gh", "pr", "create", ...], capture_output=True, text=True)
pr_url = result.stdout.strip()  # Returns: https://github.com/owner/repo/pull/123
pr_number = re.search(r'/pull/(\d+)', pr_url).group(1)
# Now fetch with --json
result = subprocess.run(["gh", "pr", "view", pr_number, "--json", ...])
```

### 2. Transforming Field Names
```python
# WRONG - Don't transform GitHub's field names
issue_data = json.loads(result.stdout)
issue_data["user"] = issue_data.pop("author")  # NO!
issue_data["created_at"] = issue_data.pop("createdAt")  # NO!

# RIGHT - Preserve native field names
issue_data = json.loads(result.stdout)
shared["issue_data"] = issue_data  # Use as-is
```

### 3. Forgetting Authentication Check
```python
# WRONG - No auth check
def prep(self, shared):
    issue = shared.get("issue_number")
    return {"issue": issue}

# RIGHT - Always check auth in prep()
def prep(self, shared):
    # Check authentication first
    result = subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=2)
    if result.returncode != 0:
        raise ValueError("GitHub CLI not authenticated. Run 'gh auth login' first.")

    issue = shared.get("issue_number") or self.params.get("issue_number")
    return {"issue": issue}
```

### 4. Using shell=True
```python
# WRONG - Security vulnerability
subprocess.run(f"gh issue view {issue_number}", shell=True)  # NEVER!

# RIGHT - Always use command array
subprocess.run(["gh", "issue", "view", str(issue_number)], shell=False)
```

## ✅ Required Patterns

### 1. Two-Step PR Creation Pattern
```python
def exec(self, prep_res):
    # Step 1: Create PR (returns URL only)
    cmd = ["gh", "pr", "create", "--title", title, "--body", body, "--base", base, "--head", head]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    # Step 2: Parse URL
    pr_url = result.stdout.strip()
    match = re.search(r'/pull/(\d+)', pr_url)
    if not match:
        raise ValueError(f"Could not parse PR number from URL: {pr_url}")

    # Step 3: Get full data
    pr_number = match.group(1)
    cmd = ["gh", "pr", "view", pr_number, "--json", "number,url,title,state,author"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    return json.loads(result.stdout)
```

### 2. Parameter Fallback Pattern
```python
def prep(self, shared):
    # Automatic fallback: shared → params → error/default
    issue = shared.get("issue_number") or self.params.get("issue_number")
    repo = shared.get("repo") or self.params.get("repo")  # Optional - can be None

    if not issue:
        raise ValueError("Missing required 'issue_number'")

    return {"issue": issue, "repo": repo}
```

### 3. Error Transformation Pattern
```python
def exec_fallback(self, prep_res, exc: Exception):
    error_msg = str(exc)

    # Transform technical errors to user-friendly messages
    if "not authenticated" in error_msg:
        raise ValueError("GitHub CLI not authenticated. Run 'gh auth login' first.")
    elif "Could not resolve" in error_msg:
        repo = prep_res.get("repo", "current")
        raise ValueError(f"Repository '{repo}' not found or you don't have access.")
    elif "rate limit" in error_msg:
        raise ValueError("GitHub API rate limit exceeded. Please wait before retrying.")
    else:
        raise ValueError(f"GitHub operation failed: {error_msg}")
```

### 4. NO Exception Handling in exec()
```python
def exec(self, prep_res):
    # NO try/except! Let exceptions bubble up for retry mechanism
    cmd = ["gh", "issue", "view", prep_res["issue"]]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        raise ValueError(f"GitHub CLI error: {result.stderr}")

    return json.loads(result.stdout)  # Let JSONDecodeError bubble up
```

## 🔒 Security Requirements

1. **ALWAYS use `shell=False`** in subprocess.run()
2. **Set timeout=30** for normal operations, timeout=2 for auth checks
3. **Build commands as arrays**, never concatenate strings
4. **Validate all inputs** before using in commands
5. **Never log sensitive data** (tokens, passwords, etc.)
6. **Use stderr for error detection**, not just return codes

## 📝 Interface Documentation Rules

```python
"""
Get GitHub issue details.

Interface:
- Reads: shared["issue_number"]: str  # Issue number to fetch
- Reads: shared["repo"]: str  # Repository in owner/repo format (optional)
- Writes: shared["issue_data"]: dict  # Complete issue details
    - number: int  # Issue number
    - title: str  # Issue title
    - author: dict  # Issue author information
      - login: str  # Username
      - name: str  # Full name
- Actions: default (always)
"""
```

**Critical Rules**:
1. Use double quotes: `shared["key"]` not `shared['key']`
2. Document nested structures with indentation
3. Don't duplicate shared reads as Params (automatic fallback exists!)
4. Only document Params that are configuration-only

## 🧪 Testing Strategy

### Unit Tests (Required)
```python
@patch('subprocess.run')
def test_exec_success(mock_run):
    mock_run.return_value = Mock(
        returncode=0,
        stdout='{"number": 123, "title": "Test", "author": {"login": "user"}}',
        stderr=""
    )

    node = GitHubGetIssueNode()
    result = node.exec({"issue": "123", "repo": None})

    assert result["number"] == 123
    assert result["author"]["login"] == "user"  # Native field name!
```

### Integration Tests (Optional)
```python
@pytest.mark.skipif(
    not os.environ.get("RUN_GITHUB_TESTS"),
    reason="Skipping GitHub integration tests (set RUN_GITHUB_TESTS=1 to run)"
)
def test_real_github_operation():
    # Only read operations in tests!
    node = GitHubGetIssueNode()
    node.set_params({"repo": "python/cpython", "issue_number": "1"})
    shared = {}
    node.run(shared)
    assert shared["issue_data"]["number"] == 1
```

## 🚀 Extension Opportunities

### High-Value Nodes to Add
1. **github-close-issue**: Close issues with optional comment
2. **github-add-comment**: Add comments to issues/PRs
3. **github-create-issue**: Create new issues
4. **github-merge-pr**: Merge pull requests
5. **github-list-prs**: List repository PRs
6. **github-create-release**: Create GitHub releases
7. **github-workflow-dispatch**: Trigger GitHub Actions

### Command Discovery Pattern
```bash
# Find available gh commands
gh --help

# Check if command supports JSON
gh issue view --help | grep -i json

# Test JSON fields available
gh issue view 1 --json 2>&1 | head -20  # Shows available fields
```

## 💡 Quick Reference

### Common gh Commands
```bash
# Issues
gh issue view NUMBER --json number,title,body,state,author,labels,assignees,createdAt,updatedAt
gh issue list --state open --limit 30 --json number,title,state,author
gh issue create --title "Title" --body "Body" --label bug

# Pull Requests
gh pr create --title "Title" --body "Body" --base main --head feature
gh pr view NUMBER --json number,url,title,state,author,reviewDecision
gh pr list --state open --limit 10

# Repository
gh repo view --json name,description,url,defaultBranch,isPrivate
```

### Error Patterns in stderr
- `"not authenticated"` → Need to run gh auth login
- `"Could not resolve to a Repository"` → Repo not found
- `"Could not find issue"` → Issue doesn't exist
- `"API rate limit exceeded"` → Rate limited
- `"Forbidden"` → No access to resource

### Available JSON Fields
Run `gh api` commands to discover fields:
```bash
# List all issue fields
gh api repos/owner/repo/issues/1

# List all PR fields
gh api repos/owner/repo/pulls/1
```

## ⚡ Performance Considerations

- Subprocess overhead: ~50-100ms per call
- Rate limits: 5000/hour authenticated, 60/hour unauthenticated
- JSON parsing: Negligible (<1ms for typical responses)
- Network latency: Variable, use 30s timeout

## 🔄 Common Workflow Patterns

### Issue-to-PR Flow
1. `github-get-issue` → Fetch issue details
2. `llm` → Generate solution
3. `write-file` → Save changes
4. `git-commit` → Commit changes
5. `git-push` → Push to branch
6. `github-create-pr` → Create PR referencing issue

Remember: All GitHub operations can target any repository, making these nodes powerful for cross-repo workflows!
