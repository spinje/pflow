# Task 26: GitHub and Git Operation Nodes - Implementation Plan

## Executive Summary

Implementing 6 nodes (3 GitHub, 3 Git) to unblock Task 17's natural language planner. All GitHub CLI behavior has been verified. Native field names will be used without transformation.

## Task Breakdown & Dependencies

### Phase 1: Package Structure Setup (15 minutes)
**Files to create:**
```
src/pflow/nodes/github/
    ├── __init__.py
    ├── get_issue.py
    ├── list_issues.py
    └── create_pr.py
src/pflow/nodes/git/
    ├── __init__.py
    ├── status.py
    ├── commit.py
    └── push.py
```

**Dependencies:** None - can start immediately

### Phase 2: GitHub Nodes Implementation (2 hours)

#### 2.1 GitHubGetIssueNode (45 min)
**File:** `src/pflow/nodes/github/get_issue.py`
**Key features:**
- Authentication check in prep()
- Subprocess call to `gh issue view --json`
- Native field preservation (author, createdAt)
- Nested structure documentation in Interface

#### 2.2 GitHubListIssuesNode (30 min)
**File:** `src/pflow/nodes/github/list_issues.py`
**Key features:**
- List filtering (state, limit)
- Returns array of issue objects
- Same structure as get_issue

#### 2.3 GitHubCreatePRNode (45 min)
**File:** `src/pflow/nodes/github/create_pr.py`
**Key features:**
- Two-step process: create returns URL, parse, then view
- URL parsing with regex
- Full PR data retrieval

**Dependencies:** Must complete 2.1 first to understand patterns

### Phase 3: Git Nodes Implementation (1.5 hours)

#### 3.1 GitStatusNode (45 min)
**File:** `src/pflow/nodes/git/status.py`
**Key features:**
- Parse `git status --porcelain=v2` output
- Convert to structured JSON
- Handle branch info (ahead/behind)

#### 3.2 GitCommitNode (30 min)
**File:** `src/pflow/nodes/git/commit.py`
**Key features:**
- Stage files with `git add`
- Commit with message
- Extract commit SHA from output

#### 3.3 GitPushNode (15 min)
**File:** `src/pflow/nodes/git/push.py`
**Key features:**
- Push to remote branch
- Handle rejection errors
- Simple success/failure result

**Dependencies:** Can be done in parallel with Phase 2

### Phase 4: Testing Implementation (2 hours)

#### 4.1 Test Structure Setup (15 min)
**Files to create:**
```
tests/test_nodes/test_github/
    ├── __init__.py
    ├── test_get_issue.py
    ├── test_list_issues.py
    └── test_create_pr.py
tests/test_nodes/test_git/
    ├── __init__.py
    ├── test_status.py
    ├── test_commit.py
    └── test_push.py
```

#### 4.2 GitHub Node Tests (1 hour)
- Mock subprocess.run for all gh commands
- Test authentication failures
- Test JSON parsing
- Test error conditions (not found, rate limit)
- Test parameter fallback

#### 4.3 Git Node Tests (45 min)
- Mock git commands
- Test porcelain parsing for status
- Test commit message extraction
- Test push success/failure

**Dependencies:** Must complete Phase 2 & 3 first

### Phase 5: Integration & Verification (30 min)
- Run `pflow list` to verify discovery
- Run `make test` for full test suite
- Run `make check` for linting
- Create example workflows
- Update progress log with results

## Subagent Task Assignments

### Parallel Batch 1 (Phase 1 & Initial Implementation)
Can be done simultaneously:

1. **Subagent 1: Package Structure**
   - Task: "Create the directory structure for GitHub and Git nodes in src/pflow/nodes/ with proper __init__.py files"
   - Files: All __init__.py files
   - No conflicts possible

2. **Subagent 2: GitHubGetIssueNode**
   - Task: "Implement GitHubGetIssueNode in src/pflow/nodes/github/get_issue.py following the verified JSON structure from the spec, with authentication check, subprocess pattern, and nested Interface documentation"
   - Files: src/pflow/nodes/github/get_issue.py only

3. **Subagent 3: GitStatusNode**
   - Task: "Implement GitStatusNode in src/pflow/nodes/git/status.py with porcelain v2 parsing to structured JSON"
   - Files: src/pflow/nodes/git/status.py only

### Parallel Batch 2 (After Batch 1)
Once GitHubGetIssueNode pattern is established:

4. **Subagent 4: GitHubListIssuesNode**
   - Task: "Implement GitHubListIssuesNode in src/pflow/nodes/github/list_issues.py following the pattern from get_issue.py"
   - Files: src/pflow/nodes/github/list_issues.py only

5. **Subagent 5: GitHubCreatePRNode**
   - Task: "Implement GitHubCreatePRNode in src/pflow/nodes/github/create_pr.py with two-step URL parsing process"
   - Files: src/pflow/nodes/github/create_pr.py only

6. **Subagent 6: Git Commit and Push**
   - Task: "Implement GitCommitNode and GitPushNode in their respective files following the patterns"
   - Files: src/pflow/nodes/git/commit.py, src/pflow/nodes/git/push.py

### Sequential Testing Phase
After implementation:

7. **Subagent 7: GitHub Tests**
   - Task: "Write comprehensive tests for all GitHub nodes with mocked subprocess"
   - Files: tests/test_nodes/test_github/*.py

8. **Subagent 8: Git Tests**
   - Task: "Write comprehensive tests for all Git nodes with mocked subprocess"
   - Files: tests/test_nodes/test_git/*.py

## Risk Identification & Mitigation

### Identified Risks:

1. **gh CLI not installed/authenticated**
   - Mitigation: Check in prep(), provide clear error message
   - Test with mock to avoid dependency

2. **PR creation URL parsing fails**
   - Mitigation: Robust regex, fallback error handling
   - Test multiple URL formats

3. **Git porcelain format changes**
   - Mitigation: Version-specific parsing, clear error on unknown format
   - Document expected git version

4. **Network timeouts in CI**
   - Mitigation: Mock all subprocess in tests
   - Optional integration tests with flag

5. **Registry discovery fails**
   - Mitigation: Follow exact Interface format with double quotes
   - Test with `pflow list` immediately

## Testing Strategy

### Unit Tests (Required)
- Mock all subprocess.run calls
- Test every error condition in spec
- Test parameter fallback pattern
- Test retry behavior (set wait=0.01)
- Verify exact command construction

### Integration Tests (Optional)
- Behind RUN_GITHUB_TESTS=1 flag
- Only read-only operations
- Skip in CI by default

### Test Coverage Goals
- 100% of error conditions from spec
- All 22 test criteria satisfied
- Both success and failure paths
- Parameter validation

## Success Criteria Checklist

- [ ] All 6 nodes implemented and in correct directories
- [ ] All nodes discoverable via `pflow list`
- [ ] Native gh field names preserved (author, createdAt)
- [ ] PR creation uses two-step process
- [ ] Git status parses porcelain correctly
- [ ] All 22 test criteria pass
- [ ] `make test` passes with no regressions
- [ ] `make check` passes (linting, typing)
- [ ] Error messages are helpful and actionable
- [ ] Template variables like `$issue_data.author.login` work

## Implementation Notes

### Critical Patterns to Follow:
1. **NO field transformation** - use native gh names
2. **NO try/except in exec()** - let exceptions bubble
3. **shell=False ALWAYS** - security requirement
4. **timeout=30** for operations
5. **Interface with double quotes** - shared["key"]
6. **Nested structure with indentation** - for parser
7. **Parameter fallback** - shared → params → defaults
8. **name attribute** - for registry discovery

### Command Examples:
```python
# GitHub issue view
cmd = ["gh", "issue", "view", issue_number, "--json", "number,title,body,state,author,labels,createdAt,updatedAt,assignees"]

# Git status
cmd = ["git", "status", "--porcelain=v2"]

# PR creation (step 1)
cmd = ["gh", "pr", "create", "--title", title, "--body", body, "--base", base, "--head", head]
```

## Timeline Estimate

- Phase 1: 15 minutes
- Phase 2: 2 hours
- Phase 3: 1.5 hours
- Phase 4: 2 hours
- Phase 5: 30 minutes
- **Total: ~6 hours**

With parallelization: ~4 hours

## Next Steps

1. Create package structure
2. Deploy parallel subagents for initial implementation
3. Test each node as completed
4. Write comprehensive tests
5. Verify with full test suite
6. Document any discoveries or deviations
