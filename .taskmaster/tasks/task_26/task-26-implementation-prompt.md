# Task 26: GitHub and Git Operation Nodes - Agent Instructions

## The Problem You're Solving

Task 17 (Natural Language Planner) is completely blocked without GitHub nodes. The entire Task 17 documentation uses "fix github issue 1234" as the canonical example workflow, but currently only `read-file`, `write-file`, and `llm` nodes exist. Without GitHub nodes, the planner can only generate trivial file operation workflows instead of the compelling real-world automation that showcases pflow's true value.

## Your Mission

Implement six critical nodes that enable GitHub and Git automation: three GitHub nodes using `gh` CLI for GitHub operations, and three Git nodes using native git commands for version control. These nodes will unblock Task 17 and enable workflows like "fix github issue 1234 and create a pull request" - the flagship example that demonstrates pflow's power.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_26/task-26.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_26/starting-context/`

**Files to read (in this order):**
1. `task-26-spec.md` - The specification (FOLLOW THIS PRECISELY) - Contains all requirements, test criteria, and verified JSON structures
2. `task-26-handover.md` - Critical implementation context with verified GitHub CLI behavior and patterns

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-26-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY. All GitHub CLI behavior has been verified and documented - NO additional verification is needed.

## What You're Building

You're implementing six nodes that enable GitHub and Git automation:

**GitHub Nodes (using gh CLI via subprocess):**
- `github-get-issue`: Fetches issue details with rich nested JSON structure
- `github-list-issues`: Lists repository issues as an array
- `github-create-pr`: Creates pull requests (two-step process: create returns URL, then fetch data)

**Git Nodes (using native git commands via subprocess):**
- `git-status`: Parses `git status --porcelain=v2` into structured JSON
- `git-commit`: Stages files and creates commits
- `git-push`: Pushes commits to remote repository

Example workflow this enables:
```bash
# The canonical Task 17 example
pflow "fix github issue 1234"

# Will generate and execute:
github-get-issue --issue_number=1234 >>
llm --prompt="Fix issue: $issue_data.title by $issue_data.author.login" >>
write-file --file_path=fix.py --content="$response" >>
git-commit --message="Fix #$issue_data.number: $issue_data.title" >>
git-push --branch=fix-issue-1234 >>
github-create-pr --title="Fix: $issue_data.title"
```

## Key Outcomes You Must Achieve

### 1. Core Node Implementation
- Six working nodes in proper directory structure
- Each node follows PocketFlow lifecycle (prep/exec/post/exec_fallback)
- Subprocess execution with security (shell=False, timeout=30)
- Parameter fallback pattern (shared → params → defaults)

### 2. Verified Data Structures
- Use native gh field names: `author` (not `user`), `createdAt` (not `created_at`)
- NO field transformation - Task 17 will use native names
- Rich nested structures for template variables like `$issue_data.author.login`
- Proper Interface docstring format with nested structure documentation

### 3. Special Handling
- PR creation: Parse URL from stdout, extract number, fetch full data with `gh pr view`
- Git status: Parse porcelain format to structured JSON
- Authentication: Check `gh auth status` in prep(), provide helpful errors
- Error messages: Transform technical errors to actionable user guidance

### 4. Testing & Documentation
- Comprehensive unit tests with mocked subprocess
- All test criteria from spec passing
- Integration tests (optional, behind RUN_GITHUB_TESTS flag)
- Complete Interface docstrings for registry discovery

## Implementation Strategy

### Phase 1: Package Structure Setup (30 minutes)
1. Create directory structure: `src/pflow/nodes/github/` and `src/pflow/nodes/git/`
2. Create `__init__.py` files in both directories
3. Set up initial file structure for all six nodes

### Phase 2: GitHub Nodes Implementation (2-3 hours)
1. Implement `GitHubGetIssueNode` with verified JSON structure
2. Implement `GitHubListIssuesNode` returning array of issues
3. Implement `GitHubCreatePRNode` with two-step URL parsing

### Phase 3: Git Nodes Implementation (2 hours)
1. Implement `GitStatusNode` with porcelain parsing
2. Implement `GitCommitNode` with native git commands
3. Implement `GitPushNode` with error handling

### Phase 4: Testing (2-3 hours)
1. Create test structure in `tests/test_nodes/test_github/` and `tests/test_nodes/test_git/`
2. Write comprehensive unit tests with mocked subprocess
3. Test all error conditions and retry behavior
4. Add integration tests (optional, skip by default)

### Phase 5: Documentation & Verification (1 hour)
1. Verify all Interface docstrings are properly formatted
2. Test registry discovery with `pflow list`
3. Run `make test` and `make check`
4. Create example workflows

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use subagents to work on debugging, testing and writing tests.

## Critical Technical Details

### Verified GitHub CLI JSON Structure
The exact structure returned by `gh issue view --json`:
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
    {"name": "bug", "color": "d73a4a", "description": ""}
  ],
  "assignees": [
    {"login": "assignee1", "name": "Assignee Name"}
  ],
  "createdAt": "2024-01-15T10:30:00Z",
  "updatedAt": "2024-01-16T14:22:00Z"
}
```

### Subprocess Pattern (CRITICAL)
```python
def exec(self, prep_res):
    # NO try/except! Let exceptions bubble for retry
    cmd = ["gh", "issue", "view", prep_res["issue"]]
    if prep_res["repo"]:
        cmd.extend(["--repo", prep_res["repo"]])  # Both --repo and -R work

    cmd.extend(["--json", "number,title,body,state,author,labels,createdAt,updatedAt,assignees"])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False  # SECURITY: Never use shell=True
    )

    if result.returncode != 0:
        raise ValueError(f"GitHub CLI error: {result.stderr}")

    return json.loads(result.stdout)

def post(self, shared, prep_res, exec_res):
    # NO TRANSFORMATION! Use native field names
    shared["issue_data"] = exec_res
    return "default"
```

### PR Creation Two-Step Process
```python
# Step 1: Create PR (returns URL only)
result = subprocess.run(
    ["gh", "pr", "create", "--title", title, "--body", body,
     "--base", base, "--head", head],
    capture_output=True, text=True, timeout=30
)
pr_url = result.stdout.strip()  # "https://github.com/owner/repo/pull/456"

# Step 2: Extract number and fetch full data
pr_number = pr_url.split('/')[-1]
cmd = ["gh", "pr", "view", pr_number, "--json", "number,url,title,state,author"]
```

### Git Status Porcelain Parsing
```python
# Parse git status --porcelain=v2 output
# Example: "1 .M N... 100644 100644 100644 abc123 def456 file.py"
# Convert to:
{
    "modified": ["file.py"],
    "untracked": [],
    "staged": [],
    "branch": "main",
    "ahead": 0,
    "behind": 0
}
```

### Interface Docstring Format (EXACT)
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
- Params: issue_number: str  # Issue number if not in shared
- Params: repo: str  # Repository if not in shared
- Actions: default (always)
"""
```

## Critical Warnings from Experience

### NO Field Transformation
All GitHub CLI field names have been verified. Use them exactly as returned:
- ✅ Use `author.login` (NOT `user.login`)
- ✅ Use `createdAt` (NOT `created_at`)
- ✅ Use `updatedAt` (NOT `updated_at`)
Task 17 will be updated to use these native field names.

### PR Creation Has No JSON Support
`gh pr create` returns ONLY a URL as plain text. You MUST:
1. Parse the URL from stdout
2. Extract the PR number
3. Make a second call to `gh pr view --json` to get full data

### Git Commands Use Native Git
GitHub CLI does NOT wrap git commands. Use native git:
- `git status --porcelain=v2` (NOT gh status)
- `git commit -m "message"` (NOT gh commit)
- `git push origin branch` (NOT gh push)

### Authentication Check Required
Always check authentication in prep():
```python
result = subprocess.run(["gh", "auth", "status"], capture_output=True)
if result.returncode != 0:
    raise ValueError("GitHub CLI not authenticated. Run 'gh auth login' first.")
```

## Key Decisions Already Made

1. **Use native gh field names** - NO transformation, Task 17 will adapt
2. **Subprocess with security** - shell=False, timeout=30, capture_output=True
3. **Parameter fallback pattern** - shared → params → defaults
4. **Error transformation** - Technical errors → actionable user messages
5. **Testing strategy** - Mock subprocess for unit tests, optional integration tests
6. **Registry discovery** - Use name class attribute and Interface docstring
7. **No caching or optimization** - MVP approach, keep it simple

**📋 Note on Specifications**: The specification file (`task-26-spec.md`) contains all verified JSON structures and field names. Everything has been researched and confirmed - trust the documented structures.

## Success Criteria

Your implementation is complete when:

- ✅ All six nodes are implemented and discoverable via `pflow list`
- ✅ All test criteria from the spec pass (22 test criteria)
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ Native gh field names are preserved (no transformation)
- ✅ PR creation uses two-step process (URL parsing)
- ✅ Git status parses porcelain format correctly
- ✅ Error messages are helpful and actionable
- ✅ Task 17 can use template variables like `$issue_data.author.login`

## Common Pitfalls to Avoid

1. **DON'T transform field names** - Use native gh names (author, createdAt)
2. **DON'T expect JSON from gh pr create** - It returns URL only
3. **DON'T use gh for git commands** - Use native git
4. **DON'T skip authentication check** - Always verify in prep()
5. **DON'T use shell=True** - Security risk, use command lists
6. **DON'T catch exceptions in exec()** - Let them bubble for retry
7. **DON'T forget nested docstring format** - Required for parser
8. **DON'T add features not in spec** - No caching, no optimization

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent subagents from conflicting.

### Why Planning Matters

1. **Prevents duplicate work and conflicts**: Multiple subagents won't edit the same files
2. **Identifies dependencies**: Discover what needs to be built in what order
3. **Optimizes parallelization**: Know exactly what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Node Implementation Patterns**
   - Task: "Analyze src/pflow/nodes/llm/llm.py to understand how nodes wrap external tools via subprocess, including parameter fallback, error handling, and retry patterns"
   - Task: "Examine src/pflow/nodes/file/ to understand simple node patterns and testing approaches"

2. **Registry Integration**
   - Task: "Analyze src/pflow/registry/scanner.py to understand how nodes are discovered and what requirements they must meet"
   - Task: "Examine src/pflow/registry/metadata_extractor.py to understand the exact Interface docstring format for nested structures"

3. **Testing Patterns**
   - Task: "Analyze tests/test_nodes/test_llm/ to understand how to mock external tools and test retry behavior"
   - Task: "Check tests/test_nodes/test_file/ for testing patterns with real vs mocked operations"

4. **Subprocess Usage**
   - Task: "Search the codebase for any existing subprocess.run() usage to understand security patterns"
   - Task: "Check how the project handles environment variables and command construction"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_26/implementation/implementation-plan.md`

Your plan should include:

1. **Comprehensive task breakdown** - Every file to create/modify
2. **Dependency mapping** - What must be done before what
3. **Subagent task assignments** - Who does what, ensuring no conflicts
4. **Risk identification** - What could go wrong and mitigation strategies
5. **Testing strategy** - How you'll verify each component works

### Subagent Task Scoping Guidelines

**✅ GOOD Subagent Tasks:**
```markdown
- "Implement GitHubGetIssueNode in src/pflow/nodes/github/get_issue.py following the LLM node pattern with subprocess, parameter fallback, and the verified JSON structure from the spec"
- "Write comprehensive unit tests for GitHubGetIssueNode in tests/test_nodes/test_github/test_get_issue.py, mocking subprocess.run for all scenarios: success, auth error, not found, rate limit"
- "Implement git status porcelain parsing in GitStatusNode.exec() to convert the v2 format into structured JSON"
```

**❌ BAD Subagent Tasks:**
```markdown
- "Implement all GitHub nodes" (too broad, will cause conflicts)
- "Fix any issues you find" (too vague)
- "Update all tests" (multiple agents will conflict)
```

**Key Rules:**
- One subagent per file
- Specific, bounded edits when modifying existing files
- Include full context about what the subagent needs to know
- Never assign overlapping file modifications
- Always use subagents to fix bugs, test, and write tests
- Always use subagents to gather information from the codebase or docs
- Parallelise only when subtasks are independent and with explicit bounds
- Subagents are your best weapon against unverified assumptions
- Always define termination criteria for subagents

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_26/implementation/progress-log.md`

```markdown
# Task 26 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### 1. Create Implementation Plan (SECOND!)

Follow the instructions in the "Create Your Implementation Plan FIRST" section to create a comprehensive plan before any coding.

### 2. Set up package structure
Create directories and initial files for all six nodes

### 3. Implement GitHub nodes
Start with GitHubGetIssueNode as the most complex, then list and create-pr

### 4. Implement Git nodes
Git status with porcelain parsing, then commit and push

### 5. Write comprehensive tests
Mock all subprocess calls, test every error condition

### 6. Verify registry discovery
Ensure all nodes appear in `pflow list`

### 7. Run full test suite
Fix any issues found by `make test` and `make check`

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - Implementing GitHubGetIssueNode
Attempting to parse gh JSON output...

Result: Success with native field names
- ✅ What worked: Direct json.loads() on stdout
- ✅ No transformation needed for author field
- 💡 Insight: gh CLI JSON is clean and consistent

Code that worked:
```python
exec_res = json.loads(result.stdout)
shared["issue_data"] = exec_res  # No transformation!
```
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION: PR Creation Returns URL
- Original plan: Expected JSON from gh pr create
- Why it failed: gh pr create only returns URL
- New approach: Parse URL, extract number, call gh pr view
- Lesson: Not all gh commands support JSON output
```

## Test Creation Guidelines

**Core Principle**: "Test what matters"

**Focus on quality over quantity**:
- Test subprocess command construction
- Test error handling for all known error types
- Test parameter fallback (shared → params)
- Test retry behavior with transient failures
- Test JSON parsing and field preservation

**What to test for GitHub nodes**:
- **Authentication check**: Mock gh auth status failure
- **Successful fetch**: Mock valid JSON response
- **Not found**: Mock "Could not find issue" error
- **Rate limiting**: Mock rate limit error with retry
- **Invalid JSON**: Mock malformed JSON response
- **Network timeout**: Mock TimeoutExpired exception
- **Parameter fallback**: Test shared vs params priority

**What to test for Git nodes**:
- **Porcelain parsing**: Various git status outputs
- **Commit success**: Exit code 0
- **Nothing to commit**: Exit code 1
- **Not in repository**: "not a git repository" error
- **Push rejection**: "rejected" in stderr

**Progress Log - Only document testing insights**:
```markdown
## 16:30 - Testing revealed gh pr create behavior
While testing GitHubCreatePRNode, confirmed that gh pr create
returns ONLY the URL. No JSON flag available. Must parse URL
and make second call. This is documented but worth noting.
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** modify existing node implementations (only adding new ones)
- **DON'T** change the workflow IR structure
- **DON'T** add backward compatibility code (we have ZERO users)
- **DON'T** transform field names (use native gh fields)
- **DON'T** expect JSON from all gh commands (pr create returns URL)
- **DON'T** use gh for git operations (use native git)
- **DON'T** skip authentication checks
- **DON'T** use shell=True in subprocess (security risk)
- **DON'T** catch exceptions in exec() (let them bubble)
- **DON'T** add caching or optimization (MVP only)

## Getting Started

1. Read the epistemic manifesto to understand the approach
2. Read the task overview and all context files
3. Create your progress log
4. Create your implementation plan with context gathering
5. Start with Phase 1: Package structure setup
6. Test frequently: `pytest tests/test_nodes/test_github/ -v`

## Final Notes

- All GitHub CLI behavior has been verified and documented
- The specification has exact JSON structures - trust them
- Use native field names throughout - no transformation
- PR creation is special - it returns URL only
- Git commands use native git, not gh
- Focus on getting the MVP working first
- This unblocks Task 17 - a critical dependency

## Remember

You're implementing the nodes that will unlock Task 17 and enable the flagship "fix github issue 1234" workflow. The GitHub CLI behavior has been thoroughly researched and verified. Trust the documented structures, use native field names, and focus on clean subprocess implementation with proper error handling.

This feature transforms pflow from a simple file manipulation tool into a powerful automation platform that can interact with real-world development workflows. Your implementation will enable users to automate their entire GitHub workflow with natural language commands.

Good luck! Your work here directly enables the most compelling use cases for pflow.
