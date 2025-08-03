# Task 26: GitHub CLI Nodes Implementation - Verified Implementation Guide

## ✅ All CLI Commands and Field Names Have Been Verified
This document has been updated with verified GitHub CLI documentation research.

## Why This Task Exists Now

Task 17 (Natural Language Planner) is blocked without GitHub nodes. The entire Task 17 documentation uses "fix github issue 1234" as the canonical example, but we only have `read-file`, `write-file`, and `llm` nodes. This makes the planner essentially untestable with realistic workflows.

## Critical Decision Already Made: Use GitHub CLI

After extensive research comparing three approaches:
1. **GitHub CLI (`gh`)** - WINNER for MVP ✅
2. **ghapi Python library** - Better long-term, but more complex
3. **MCP (Model Context Protocol)** - Deferred to v2.0

We chose `gh` CLI because:
- **Zero Python dependencies** - just subprocess calls
- **Authentication already handled** - users run `gh auth login` once
- **JSON output built-in** - use `--json` flag
- **50-100ms subprocess overhead is acceptable** for MVP
- **Can implement in hours, not days**

## ✅ Verified GitHub CLI Behavior

### Authentication Check:
- `gh auth status` returns exit code 0 when authenticated, non-zero when not
- Error message contains "not authenticated" when not logged in

### Issue View Command - VERIFIED Structure:
```json
{
  "number": 123,
  "title": "Issue title",
  "body": "Issue description",
  "state": "OPEN",
  "author": {
    "login": "username",
    "name": "Full Name",
    "id": "MDQ6VXNlcjM2NzI4OTMx"
  },
  "labels": [
    {"name": "bug", "color": "d73a4a", "description": "Something isn't working"}
  ],
  "assignees": [
    {"login": "assignee1", "name": "Assignee Name"}
  ],
  "createdAt": "2024-01-15T10:30:00Z",
  "updatedAt": "2024-01-16T14:22:00Z",
  "comments": 5
}
```

### PR Creation - IMPORTANT:
- `gh pr create` returns **URL only** (plain text), NOT JSON
- Must parse URL to extract PR number, then call `gh pr view` for full data
- Example output: `https://github.com/owner/repo/pull/456`

### Repository Parameter:
- Both `--repo` and `-R` work identically
- Format: `owner/repo` or `HOSTNAME/owner/repo`

### Available JSON Fields:
**Issue fields (21 total)**:
`assignees, author, body, closed, closedAt, closedByPullRequestsReferences, comments, createdAt, id, isPinned, labels, milestone, number, projectCards, projectItems, reactionGroups, state, stateReason, title, updatedAt, url`

**PR fields (many)**:
`author, number, title, body, state, url, createdAt, updatedAt, closedAt, mergedAt, headRefName, baseRefName, assignees, labels, milestone, reviewRequests, reviews, comments`

### Verified Field Names - NO TRANSFORMATION NEEDED

| gh CLI field | Use in templates | Status |
|--------------|------------------|--------|
| `author.login` | `$issue_data.author.login` | ✅ Verified |
| `author.name` | `$issue_data.author.name` | ✅ Verified |
| `createdAt` | `$issue_data.createdAt` | ✅ Verified (camelCase) |
| `updatedAt` | `$issue_data.updatedAt` | ✅ Verified (camelCase) |
| `number` | `$issue_data.number` | ✅ Verified |
| `labels[].name` | `$issue_data.labels[0].name` | ✅ Verified |
| `assignees[].login` | `$issue_data.assignees[0].login` | ✅ Verified |

### Verified Error Formats

**Non-existent issue**: Exit code 1, stderr contains "Could not find issue"
**Invalid repo**: Exit code 1, stderr contains "Could not resolve"
**Not authenticated**: Exit code 1, stderr contains "not authenticated"

## The Nodes You MUST Implement

Based on Task 17's examples, these are the critical nodes needed:

### 1. `github-get-issue`
**Purpose**: Enable the "fix github issue 1234" example
```python
# ✅ VERIFIED: This is the actual structure gh CLI returns
# NO TRANSFORMATION NEEDED - use native field names
shared["issue_data"] = {
    "number": 1234,
    "title": "Bug in login system",
    "body": "Full description...",
    "state": "OPEN",  # Note: uppercase
    "author": {  # ✅ Verified field name
        "login": "johndoe",  # Use: $issue_data.author.login
        "name": "John Doe",
        "id": "MDQ6VXNlcjM2NzI4OTMx"
    },
    "labels": [
        {"name": "bug", "color": "d73a4a", "description": ""},
        {"name": "priority:high", "color": "ff0000", "description": ""}
    ],
    "assignees": [
        {"login": "janedoe", "name": "Jane Doe"}
    ],
    "createdAt": "2024-01-15T10:30:00Z",  # ✅ Verified: camelCase
    "updatedAt": "2024-01-16T14:22:00Z",
    "comments": 5
}
```

### 2. `github-create-pr`
**Purpose**: Complete the fix workflow
```bash
# Step 1: Create PR (returns URL only)
pr_url=$(gh pr create --title "Fix: $title" --body "$body" --base main --head feature-branch)
# Output: https://github.com/owner/repo/pull/456

# Step 2: Extract PR number
pr_number=$(echo "$pr_url" | grep -o '[0-9]*$')

# Step 3: Get full PR data
gh pr view "$pr_number" --json number,url,title,state,author
```

### 3. `github-list-issues`
**Purpose**: Discovery and browsing workflows
```bash
gh issue list --json number,title,state,labels,author,createdAt --limit 10
# Returns array of issue objects with same structure as github-get-issue
```

### 4. `git-commit`
**Purpose**: Bridge between code changes and PR creation
```bash
# Uses native git commands (NOT gh)
git add .
git commit -m "Fix #$issue_number: $commit_message"
# Extract commit SHA from output
```

### 5. `git-status`
**Purpose**: Check repository state
```bash
# Uses native git with porcelain format for parsing
git status --porcelain=v2
# Must parse output to structured JSON
```

### 6. `git-push`
**Purpose**: Push changes to remote
```bash
# Uses native git command
git push origin branch-name
```

## Critical Implementation Patterns

### Pattern from Successful Task 12 (LLM Node)
```python
class GitHubGetIssueNode(Node):
    """Get GitHub issue details.

    Interface:
    - Reads: shared["issue_number"]: str  # Issue number to fetch
    - Reads: shared["repo"]: str  # Repository in owner/repo format (optional)
    - Writes: shared["issue_data"]: dict  # Complete issue details
    - Params: issue_number: str  # Issue number if not in shared
    - Params: repo: str  # Repository if not in shared
    - Actions: default (always)
    """

    name = "github-get-issue"  # CRITICAL for registry discovery!

    def prep(self, shared):
        # Parameter fallback pattern (shared → params)
        issue = shared.get("issue_number") or self.params.get("issue_number")
        repo = shared.get("repo") or self.params.get("repo")

        # Check gh is available
        result = subprocess.run(["gh", "auth", "status"], capture_output=True)
        if result.returncode != 0:
            raise ValueError("GitHub CLI not authenticated. Run 'gh auth login' first.")

        return {"issue": issue, "repo": repo}

    def exec(self, prep_res):
        # NO try/except! Let exceptions bubble for PocketFlow retry
        cmd = ["gh", "issue", "view", prep_res["issue"]]
        if prep_res["repo"]:
            cmd.extend(["--repo", prep_res["repo"]])  # ✅ Both --repo and -R work

        # ✅ VERIFIED: These fields are confirmed available
        cmd.extend(["--json", "number,title,body,state,author,labels,createdAt,updatedAt,comments,assignees"])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # ✅ VERIFIED: Errors are in stderr
            raise ValueError(f"GitHub CLI error: {result.stderr}")

        return json.loads(result.stdout)

    def post(self, shared, prep_res, exec_res):
        # ✅ VERIFIED: No transformation needed!
        # gh returns 'author' and 'createdAt' - use as-is
        # Task 17 will be updated to use these native field names

        shared["issue_data"] = exec_res
        return "default"
```

## Verified Implementation Details

### 1. Field Names - VERIFIED
**Confirmed**: GitHub CLI returns `author` (not `user`), uses camelCase for dates.
**Decision**: Use native field names without transformation. Task 17 will be updated.

### 2. Repository Context
**Fact**: `gh` can infer repo from current directory.
**Risk**: Nodes might run anywhere, not in a git repo.
**Action**: Always allow explicit `--repo` parameter and test behavior outside repos.

### 3. Authentication Check - VERIFIED
**Confirmed**: `gh auth status` returns exit code 0 when authenticated.
**Implementation**: Check in `prep()` and provide helpful error message.

### 4. JSON Support - VERIFIED
**gh issue/pr view**: Full JSON support with 20+ fields
**gh pr create**: NO JSON support - returns URL only as plain text
**git commands**: NO JSON support - use porcelain format and parse

### 5. Error Location - VERIFIED
**Confirmed**: All gh errors appear in `stderr` with non-zero exit codes.

## Why Rich Data Structures Matter

Task 17's template variable system supports paths like `$issue_data.author.login`. Without rich nested structures, we can't test this critical feature. The GitHub API provides perfect test data:

```python
# This enables Task 17 to generate:
{"type": "llm", "params": {"prompt": "Fix issue #$issue_data.number: $issue_data.title by $issue_data.author.login"}}
```

## Integration with Task 17 (Planner)

The planner's context builder will automatically discover your nodes if you:
1. Include `name = "github-get-issue"` class attribute
2. Use the Interface docstring format
3. Place nodes in `src/pflow/nodes/github/` directory

## What Success Looks Like

After implementing these nodes, this should work:
```bash
# The canonical example from Task 17
pflow "fix github issue 1234"

# Should generate and execute:
# github-get-issue --issue=1234 >>
# llm --prompt="Fix this issue: $issue_data.title by $issue_data.author.login" >>
# git-commit --message="Fix #1234: $issue_data.title" >>
# github-create-pr --title="Fix: $issue_data.title"
```

## Files to Reference

- `/Users/andfal/projects/pflow/src/pflow/nodes/llm/llm.py` - Perfect node implementation pattern
- `/Users/andfal/projects/pflow/src/pflow/nodes/file/read_file.py` - Simple node example
- `/Users/andfal/projects/pflow/.taskmaster/tasks/task_12/task-review.md` - How Task 12 succeeded
- `/Users/andfal/projects/pflow/.taskmaster/tasks/task_17/task-17-implementation-guide.md` - What Task 17 needs from you

## Implementation Checklist

### ✅ All verifications complete:
- ✅ gh auth status behavior verified
- ✅ gh issue view JSON structure documented
- ✅ Field names confirmed (author, createdAt)
- ✅ Error location confirmed (stderr)
- ✅ Repository parameter formats verified (both work)
- ✅ Available JSON fields documented
- ✅ PR creation behavior verified (URL only)
- ✅ Git command requirements verified (native git)

### 📝 Implementation notes:
- ✅ NO field transformations needed - use native names
- ✅ PR creation requires two-step process (create, then view)
- ✅ Git status requires porcelain parsing
- ✅ All error messages documented

## Testing Approach

1. **CLI verification first** - Document actual behavior before coding
2. **Manual testing second** - Run the nodes directly
3. **Mock subprocess for unit tests** - Like Task 12 mocked llm library
4. **Skip integration tests by default** - Real API calls need `RUN_GITHUB_TESTS=1`

## Architecture Note: This is MVP

We're choosing subprocess overhead (50-100ms) for speed of implementation. In v2.0, we'll likely migrate to ghapi (35kB Python library) for better performance. But for now, getting Task 17 unblocked is more important than optimal performance.

## The Unspoken Requirement

Task 17's value proposition depends on these nodes. Without them, the planner can only generate trivial "read file and summarize" workflows. With them, it can generate the compelling "fix GitHub issue and create PR" workflows that showcase pflow's true power.

---

## ✅ Ready for Implementation

All GitHub CLI behavior has been verified through documentation research:

1. ✅ Field names confirmed: `author.login`, `createdAt` (camelCase)
2. ✅ PR creation returns URL only (not JSON)
3. ✅ Git operations use native git commands (not gh)
4. ✅ No field transformation needed - use native names
5. ✅ Task 17 will be updated to use correct field paths

**Implementation approach**:
1. Use verified JSON structures as documented above
2. Implement two-step PR creation (create → parse URL → view)
3. Parse git status porcelain output to structured data
4. Use native field names throughout
5. Follow existing node patterns from LLM and file nodes
