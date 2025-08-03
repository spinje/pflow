# Task 26: GitHub CLI Nodes Implementation - Critical Handover Knowledge

## 🚨 STOP: Do NOT start implementing immediately!
Read this entire document first, then acknowledge you're ready to begin.

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

## The Nodes You MUST Implement

Based on Task 17's examples, these are the critical nodes needed:

### 1. `github-get-issue`
**Purpose**: Enable the "fix github issue 1234" example
```python
# Must return rich nested structure for template path testing:
shared["issue_data"] = {
    "number": 1234,
    "title": "Bug in login system",
    "body": "Full description...",
    "state": "open",
    "user": {
        "login": "johndoe",  # Critical for $issue_data.user.login
        "id": 12345
    },
    "labels": [
        {"name": "bug", "color": "d73a4a"},
        {"name": "priority:high", "color": "ff0000"}
    ],
    "created_at": "2024-01-15T10:30:00Z",
    "comments": 5
}
```

### 2. `github-create-pr`
**Purpose**: Complete the fix workflow
```bash
gh pr create --title "Fix: $title" --body "$body" --base main --head feature-branch
```

### 3. `github-list-issues`
**Purpose**: Discovery and browsing workflows
```bash
gh issue list --json number,title,state,labels --limit 10
```

### 4. `git-commit` (if time permits)
**Purpose**: Bridge between code changes and PR creation
```bash
git commit -m "Fix #$issue_number: $commit_message"
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
            cmd.extend(["--repo", prep_res["repo"]])
        cmd.extend(["--json", "number,title,body,state,author,labels,createdAt,comments"])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise ValueError(f"GitHub CLI error: {result.stderr}")

        return json.loads(result.stdout)

    def post(self, shared, prep_res, exec_res):
        # Rename 'author' to 'user' for consistency with Task 17 examples
        if "author" in exec_res:
            exec_res["user"] = exec_res.pop("author")
        shared["issue_data"] = exec_res
        return "default"
```

## Hidden Gotchas I Discovered

### 1. Field Name Mismatches
GitHub CLI returns `author` but Task 17 examples expect `user`. You'll need to rename fields in `post()`.

### 2. Repository Context
`gh` can infer repo from current directory, but nodes might run anywhere. Always allow explicit `--repo` parameter.

### 3. Authentication Check
Don't assume `gh` is authenticated. Check in `prep()` with `gh auth status`.

### 4. JSON Flag Variations
Different gh commands have different JSON field options:
- `gh issue view --json` accepts specific fields
- `gh pr create` returns different structure than `gh pr view`
- Test the exact JSON output format for each command

## Why Rich Data Structures Matter

Task 17's template variable system supports paths like `$issue_data.user.login`. Without rich nested structures, we can't test this critical feature. The GitHub API provides perfect test data:

```python
# This enables Task 17 to generate:
{"type": "llm", "params": {"prompt": "Fix issue #$issue_data.number: $issue_data.title by $issue_data.user.login"}}
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
# llm --prompt="Fix this issue: $issue_data" >>
# git-commit --message="Fix #1234: $issue_data.title" >>
# github-create-pr --title="Fix: $issue_data.title"
```

## Files to Reference

- `/Users/andfal/projects/pflow/src/pflow/nodes/llm/llm.py` - Perfect node implementation pattern
- `/Users/andfal/projects/pflow/src/pflow/nodes/file/read_file.py` - Simple node example
- `/Users/andfal/projects/pflow/.taskmaster/tasks/task_12/task-review.md` - How Task 12 succeeded
- `/Users/andfal/projects/pflow/.taskmaster/tasks/task_17/task-17-implementation-guide.md` - What Task 17 needs from you

## Testing Approach

1. **Manual testing first** - Just run the nodes directly
2. **Mock subprocess for unit tests** - Like Task 12 mocked llm library
3. **Skip integration tests by default** - Real API calls need `RUN_GITHUB_TESTS=1`

## Architecture Note: This is MVP

We're choosing subprocess overhead (50-100ms) for speed of implementation. In v2.0, we'll likely migrate to ghapi (35kB Python library) for better performance. But for now, getting Task 17 unblocked is more important than optimal performance.

## The Unspoken Requirement

Task 17's value proposition depends on these nodes. Without them, the planner can only generate trivial "read file and summarize" workflows. With them, it can generate the compelling "fix GitHub issue and create PR" workflows that showcase pflow's true power.

---

**Remember**: Do NOT start implementing until you've read this entire document and the task specification. When ready, acknowledge understanding and begin implementation.
