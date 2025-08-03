# Task 26: GitHub and Git Operation Nodes - Implementation Review

## Executive Summary

**What We Built**: Six production-ready nodes enabling GitHub and Git automation - three GitHub nodes (`github-get-issue`, `github-list-issues`, `github-create-pr`) using `gh` CLI and three Git nodes (`git-status`, `git-commit`, `git-push`) using native git commands.

**Why It Matters**: Unblocks Task 17 (Natural Language Planner) by providing the essential nodes for the canonical "fix github issue 1234" workflow example.

**Critical Limitation**: Git nodes operate only on the current directory where pflow executes, while GitHub nodes can target any repository via the `repo` parameter.

**Key Achievement**: Preserved native GitHub CLI field names (`author`, `createdAt`) without transformation, enabling rich nested template variables like `$issue_data.author.login`.

## Quick Reference Card

| Node | Purpose | Key Inputs | Key Outputs |
|------|---------|------------|-------------|
| `github-get-issue` | Fetch issue details | `issue_number`, `repo` (opt) | `issue_data` (full JSON) |
| `github-list-issues` | List repository issues | `state`, `limit`, `repo` (opt) | `issues` (array) |
| `github-create-pr` | Create pull request | `title`, `body`, `head`, `base` | `pr_data` (after 2-step) |
| `git-status` | Get repository status | None | `git_status` (parsed) |
| `git-commit` | Create commit | `message`, `files` (opt) | `commit_sha`, `commit_message` |
| `git-push` | Push to remote | `branch` (opt), `remote` (opt) | `push_result` |

### Copy-Paste Workflow Example
```json
{
  "nodes": [
    {"id": "1", "type": "github-get-issue", "params": {"issue_number": "123"}},
    {"id": "2", "type": "llm", "params": {"prompt": "Fix {{issue_data.title}} by {{issue_data.author.login}}"}},
    {"id": "3", "type": "git-commit", "params": {"message": "Fix #{{issue_data.number}}"}},
    {"id": "4", "type": "github-create-pr", "params": {"title": "Fix: {{issue_data.title}}", "head": "fix-{{issue_data.number}}"}}
  ]
}
```

## Technical Specification

### Node Specifications

#### GitHubGetIssueNode
```python
# Location: src/pflow/nodes/github/get_issue.py
# Registry Name: github-get-issue

# Interface Contract (CORRECTED - no redundant params):
"""
Interface:
- Reads: shared["issue_number"]: str  # Issue number to fetch
- Reads: shared["repo"]: str  # Repository in owner/repo format (optional)
- Writes: shared["issue_data"]: dict  # Complete issue details
    - number: int
    - title: str
    - author: dict
      - login: str  # Template: {{issue_data.author.login}}
    - createdAt: str  # ISO format timestamp
- Actions: default (always)
"""

# Subprocess Command:
["gh", "issue", "view", issue_number, "--json", "number,title,body,state,author,labels,createdAt,updatedAt,assignees"]
```

#### GitHubCreatePRNode (Two-Step Process)
```python
# CRITICAL: gh pr create returns URL only, not JSON!
# Step 1: Create PR
["gh", "pr", "create", "--title", title, "--body", body, "--base", base, "--head", head]
# Returns: "https://github.com/owner/repo/pull/456"

# Step 2: Extract number with regex
match = re.search(r'/pull/(\d+)', pr_url)

# Step 3: Fetch full data
["gh", "pr", "view", pr_number, "--json", "number,url,title,state,author"]
```

#### GitStatusNode (Porcelain Parser)
```python
# Parses: git status --porcelain=v2
# Input: "1 .M N... 100644 100644 100644 abc123 def456 file.py"
# Output: {"modified": ["file.py"], "staged": [], "branch": "main", "ahead": 0}
```

### Verified GitHub CLI JSON Structure
```json
{
  "number": 123,
  "title": "Issue title",
  "state": "OPEN",  // Note: uppercase
  "author": {       // Note: "author" not "user"
    "login": "username",
    "name": "Full Name"
  },
  "createdAt": "2024-01-15T10:30:00Z",  // Note: camelCase
  "updatedAt": "2024-01-16T14:22:00Z"   // Note: camelCase
}
```

## Integration Architecture

### Registry Integration

**Discovery Mechanism**:
- Scanner finds nodes via `name` class attribute
- CamelCase class names auto-convert to kebab-case
- Location: `src/pflow/nodes/github/` and `src/pflow/nodes/git/`

**Interface Parsing Requirements**:
- Must use double quotes: `shared["key"]` ✅ not `shared['key']` ❌
- Nested structures use indentation (2 or 4 spaces)
- Parser extracts paths like `issue_data.author.login` automatically

**Registry Impact**:
```python
# What the scanner sees:
nodes = scan_for_nodes([Path('src/pflow/nodes')])
# Result includes:
# {'name': 'github-get-issue', 'module_path': 'src.pflow.nodes.github.get_issue', ...}
```

### Compiler Integration

**Runtime Wrapping**:
- Compiler wraps nodes in `RuntimeNode` for execution
- Template resolver handles `{{issue_data.author.login}}` paths
- Parameter fallback chain: shared → params → defaults (automatic!)

**Template Variable Resolution**:
```python
# Templates can access nested fields:
"Fix issue by {{issue_data.author.login}}"  # Resolves to author's username
"Label: {{issue_data.labels[0].name}}"      # First label's name
```

### Planner Integration (Task 17)

**Discovery Context**:
```python
# Planner's context builder will see:
{
  "github-get-issue": {
    "writes": ["issue_data"],
    "structure": {
      "issue_data": {
        "number": "int",
        "author": {
          "login": "str"
        }
      }
    }
  }
}
```

**Workflow Generation Considerations**:
1. Planner must account for directory limitation of Git nodes
2. Use native field names in templates (author.login, not user.login)
3. PR creation requires special handling (returns URL, not data)

### Workflow Manager Integration

**Save/Load Implications**:
- Workflows with Git nodes are directory-dependent
- Consider adding metadata about execution context
- Path resolution happens at runtime, not save time

## Implementation Patterns

### Subprocess Security Pattern
```python
# ALWAYS follow this pattern:
result = subprocess.run(
    cmd,  # Array of strings, never shell string
    capture_output=True,
    text=True,
    timeout=30,  # 30s for operations, 2s for checks
    shell=False  # NEVER True - security requirement
)
```

### Parameter Fallback Pattern
```python
# AUTOMATIC fallback provided by framework:
def prep(self, shared):
    # This automatically checks shared first, then params:
    issue = shared.get("issue_number") or self.params.get("issue_number")

    # Only use params directly for config that's NEVER in shared:
    model = self.params.get("model", "gpt-4")  # Config-only
```

### Error Transformation Pattern
```python
def exec_fallback(self, prep_res, exc):
    if "not authenticated" in str(exc):
        raise ValueError("GitHub CLI not authenticated. Run 'gh auth login' first.")
    if "Could not find issue" in str(exc):
        raise ValueError(f"Issue #{prep_res['issue']} not found")
    # Always provide actionable guidance
```

## Critical Discoveries & Limitations

### 1. Directory Context Limitation ⚠️

**The Issue**: Git nodes only operate on the current directory where pflow executes.

**Impact**:
- Can fetch issues from `RepoA` but only commit to current directory
- Breaks assumption that nodes are location-agnostic
- Workflows are not portable across repositories

**Workaround**:
- Execute pflow from target repository
- Use shell wrapper to change directories
- Document requirement clearly in workflow

**Future Enhancement**: Add `working_directory` parameter to Git nodes

### 2. Interface Documentation Rule 📝

**Discovery**: The framework AUTOMATICALLY provides shared→params fallback.

**Correct Pattern**:
```python
"""
Interface:
- Reads: shared["issue_number"]: str  # Always checked first
# DO NOT add "Params: issue_number" - it's redundant!
- Params: model: str  # Only for config that bypasses shared
"""
```

### 3. GitHub CLI Behaviors 🔧

**PR Creation is Special**: Returns URL only, requires two-step process
**Native Fields**: Use `author` not `user`, `createdAt` not `created_at`
**Authentication**: Check with `gh auth status` in prep()

## Usage Cookbook

### Fix Issue and Create PR
```python
# 1. Get issue details
shared = {"issue_number": "1234", "repo": "owner/repo"}
node = GitHubGetIssueNode()
node.run(shared)
# shared["issue_data"] now contains full issue

# 2. Create fix (using LLM or manual)
fix_content = generate_fix(shared["issue_data"])

# 3. Commit fix
shared["message"] = f"Fix #{shared['issue_data']['number']}"
node = GitCommitNode()
node.run(shared)

# 4. Create PR
shared["title"] = f"Fix: {shared['issue_data']['title']}"
shared["body"] = f"Fixes #{shared['issue_data']['number']}"
node = GitHubCreatePRNode()
node.run(shared)
```

### Anti-Patterns to Avoid
```python
# ❌ DON'T transform field names
issue_data["user"] = issue_data.pop("author")  # Wrong!

# ❌ DON'T expect JSON from gh pr create
pr_data = json.loads(result.stdout)  # Will fail!

# ❌ DON'T use shell=True
subprocess.run(f"gh issue view {number}", shell=True)  # Security risk!

# ❌ DON'T catch exceptions in exec()
try:
    result = subprocess.run(...)  # Let it bubble for retry!
except:
    pass
```

## Troubleshooting Reference

| Error Message | Cause | Solution |
|--------------|-------|----------|
| "GitHub CLI not authenticated" | gh not logged in | Run `gh auth login` |
| "Could not find issue" | Issue doesn't exist | Check issue number and repo |
| "not a git repository" | Not in git repo | Run from repository root |
| "Could not parse PR number from URL" | gh pr create format changed | Check gh version |
| "rejected - non-fast-forward" | Push conflicts | Pull and merge first |

## Cross-Component Impact Map

### Files Created
```
src/pflow/nodes/github/
├── __init__.py
├── get_issue.py (196 lines)
├── list_issues.py (184 lines)
└── create_pr.py (211 lines)

src/pflow/nodes/git/
├── __init__.py
├── status.py (165 lines)
├── commit.py (178 lines)
└── push.py (156 lines)

tests/test_nodes/test_github/ (3 test files, 75 tests)
tests/test_nodes/test_git/ (3 test files, 75 tests)
```

### Dependencies
- No new Python dependencies (uses subprocess only)
- External: `gh` CLI v2.0+ (GitHub nodes)
- External: `git` CLI (Git nodes)

### Performance Impact
- Subprocess overhead: 50-100ms per operation
- Timeout: 30s max per operation
- No caching implemented (MVP approach)

## Version Compatibility

**GitHub CLI**: v2.0+ required (tested with v2.40.0)
**Git**: v2.0+ (porcelain v2 format)
**Python**: 3.9+ (for type hints)
**OS**: All platforms (Windows needs Git Bash)

## Future Enhancements

1. **Working Directory Parameter** (Priority: HIGH)
   - Add `working_directory` to Git nodes
   - Enable cross-repository workflows

2. **Batch Operations** (Priority: MEDIUM)
   - `github-get-issues` for multiple issues
   - `git-commit-batch` for multiple commits

3. **Caching Layer** (Priority: LOW)
   - Cache issue data with TTL
   - Cache authentication status

4. **Performance Optimizations**
   - Connection pooling for gh CLI
   - Parallel execution for independent operations

## Key Takeaways for AI Agents

1. **When using these nodes**: Account for directory limitation in Git nodes
2. **When extending**: Follow subprocess security pattern exactly
3. **When debugging**: Check authentication first, then repository context
4. **When documenting**: Only use Params: for config-only parameters
5. **When testing**: Include real-world validation, not just mocks

## Verification Checklist

- [x] All 6 nodes discoverable via registry
- [x] Native GitHub field names preserved
- [x] Two-step PR creation working
- [x] 826 total tests passing
- [x] No regressions in existing code
- [x] Real-world tested with actual GitHub/Git

---

*This review documents Task 26 completed on 2025-08-03. For implementation details, see `.taskmaster/tasks/task_26/implementation/`*
