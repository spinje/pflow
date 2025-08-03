# Task 26: GitHub CLI Nodes Implementation - Critical Handover Knowledge

## 🚨 STOP: Do NOT start implementing immediately!
Read this entire document first, VERIFY the CLI commands, then acknowledge you're ready to begin.

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

## ⚠️ CRITICAL: CLI Verification Requirements

### Before writing ANY code, you MUST verify the actual CLI behavior:

1. **Authentication Check**:
   ```bash
   # Run this and verify the exit code and output format:
   gh auth status
   echo "Exit code: $?"
   # Document what authenticated vs. unauthenticated states look like
   ```

2. **Issue View Command**:
   ```bash
   # Test with a real public repo issue:
   gh issue view 1 --repo cli/cli --json number,title,body,state,author,labels,createdAt,comments

   # Questions to answer:
   # - Is the field called 'author' or 'user'?
   # - What's the exact structure of nested fields?
   # - What happens with missing fields?
   # - What error format for non-existent issues?
   ```

3. **PR Creation Command**:
   ```bash
   # In a test repo, verify the actual command and output:
   gh pr create --help

   # Questions to answer:
   # - What does successful creation return?
   # - How to capture the PR URL/number?
   # - What's the exact parameter format?
   # - What happens without required parameters?
   ```

4. **Repository Parameter**:
   ```bash
   # Test different repo specifications:
   gh issue list --repo owner/repo
   gh issue list -R owner/repo

   # Which format works? Both? Document it!
   ```

5. **JSON Field Discovery**:
   ```bash
   # List available JSON fields for each command:
   gh issue view --help | grep -A 20 "json"
   gh pr create --help | grep -A 20 "json"
   gh issue list --help | grep -A 20 "json"

   # Document EXACTLY which fields are available
   ```

### Field Mapping Table (VERIFY AND UPDATE THIS!)

| gh CLI field | Expected shared store field | Verified? |
|--------------|----------------------------|-----------|
| `author` | `user` | ❌ MUST VERIFY |
| `author.login` | `user.login` | ❌ MUST VERIFY |
| `createdAt` | `created_at` | ❌ MUST VERIFY |
| `number` | `number` | ❌ MUST VERIFY |
| `labels[].name` | `labels[].name` | ❌ MUST VERIFY |

### Error Handling Verification

Run these commands and document the EXACT error format:
```bash
# Non-existent issue
gh issue view 999999 --repo cli/cli 2>&1
echo "Exit code: $?"

# Invalid repo
gh issue view 1 --repo invalid/repo 2>&1
echo "Exit code: $?"

# Not authenticated
gh auth logout
gh issue view 1 --repo cli/cli 2>&1
echo "Exit code: $?"
gh auth login  # Re-authenticate after testing
```

## The Nodes You MUST Implement

Based on Task 17's examples, these are the critical nodes needed:

### 1. `github-get-issue`
**Purpose**: Enable the "fix github issue 1234" example
```python
# ⚠️ WARNING: This structure is what Task 17 EXPECTS, but you MUST verify
# what gh CLI actually returns and transform it in post() if needed!
#
# Expected structure for Task 17 compatibility:
shared["issue_data"] = {
    "number": 1234,
    "title": "Bug in login system",
    "body": "Full description...",
    "state": "open",
    "user": {  # ← gh might return 'author' instead!
        "login": "johndoe",  # Critical for $issue_data.user.login
        "id": 12345
    },
    "labels": [
        {"name": "bug", "color": "d73a4a"},
        {"name": "priority:high", "color": "ff0000"}
    ],
    "created_at": "2024-01-15T10:30:00Z",  # ← gh might return 'createdAt'
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
            cmd.extend(["--repo", prep_res["repo"]])  # ← VERIFY: --repo or -R?

        # ⚠️ VERIFY these fields actually exist with gh issue view --help
        cmd.extend(["--json", "number,title,body,state,author,labels,createdAt,comments"])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # ⚠️ VERIFY: Is the error in stderr or stdout?
            raise ValueError(f"GitHub CLI error: {result.stderr}")

        return json.loads(result.stdout)

    def post(self, shared, prep_res, exec_res):
        # ⚠️ CRITICAL: This transformation assumes gh returns 'author'
        # You MUST verify the actual field names and structure!

        # Transform gh CLI output to match Task 17's expected structure
        # Based on your CLI verification, you might need to:
        # - Rename 'author' to 'user'
        # - Rename 'createdAt' to 'created_at'
        # - Ensure nested structures match expectations

        if "author" in exec_res:  # ← VERIFY this field exists!
            exec_res["user"] = exec_res.pop("author")

        if "createdAt" in exec_res:  # ← VERIFY this field exists!
            exec_res["created_at"] = exec_res.pop("createdAt")

        shared["issue_data"] = exec_res
        return "default"
```

## Potential Gotchas to Verify

### 1. Field Name Mismatches (UNVERIFIED)
**Assumption**: GitHub CLI might return `author` but Task 17 examples expect `user`.
**Action**: VERIFY actual field names and add transformations in `post()`.

### 2. Repository Context
**Fact**: `gh` can infer repo from current directory.
**Risk**: Nodes might run anywhere, not in a git repo.
**Action**: Always allow explicit `--repo` parameter and test behavior outside repos.

### 3. Authentication Check
**Risk**: Don't assume `gh` is authenticated.
**Action**: Check in `prep()` with `gh auth status` and VERIFY the exit codes.

### 4. JSON Flag Variations
**Risk**: Different gh commands have different JSON field options.
**Action Required**:
- Run `gh issue view --help` and document available JSON fields
- Run `gh pr create --help` and document return format
- Test the EXACT JSON output format for each command

### 5. Error Location (UNVERIFIED)
**Assumption**: Errors are in `stderr`.
**Action**: Test where gh actually puts error messages (stderr vs stdout).

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

## Verification Checklist Before Implementation

### ✅ MUST complete before writing code:
- [ ] Run `gh auth status` and document exit codes
- [ ] Run `gh issue view 1 --repo cli/cli --json ...` with actual fields
- [ ] Document the EXACT JSON structure returned
- [ ] Verify field names (author vs user, createdAt vs created_at)
- [ ] Test error output location (stderr vs stdout)
- [ ] Verify `--repo` vs `-R` parameter format
- [ ] List all available JSON fields for each command
- [ ] Test behavior outside a git repository
- [ ] Document PR creation return format

### ✅ Document these findings:
- [ ] Create a table mapping gh output fields to expected shared store fields
- [ ] Note any field transformations needed in post()
- [ ] List exact error messages and exit codes for common failures

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

## ⚠️ FINAL WARNING

The example code in this document contains ASSUMPTIONS about gh CLI behavior that have NOT been verified. You MUST:

1. Complete the verification checklist
2. Document actual CLI behavior
3. Update your implementation based on findings
4. Transform data in post() to match Task 17's expectations

**Remember**: Do NOT start implementing until you've:
1. Read this entire document
2. Read the task specification
3. VERIFIED the actual gh CLI behavior
4. Documented your findings

When ready, acknowledge understanding, show your CLI verification results, then begin implementation.
