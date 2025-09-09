# Task 58: Update workflow generator prompt-tests to use better real world test cases - Agent Instructions

## The Problem You're Solving

The workflow generator tests currently use 30+ mock nodes that don't exist (like `slack-notify`, `build-project`, `analyze-code`), giving everyone false confidence about system capabilities. Tests pass with fictional nodes, but would fail in production when these nodes aren't found. This fundamentally undermines the value of testing.

## Your Mission

Replace the 13 fantasy-based tests with 15 reality-based tests that validate actual system capabilities. Use only real nodes from the registry, employ shell workarounds for missing features, and mock only 2 proven Slack MCP nodes.

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
**File**: `.taskmaster/tasks/task_58/task-58.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_58/starting-context/`

**Files to read (in this order):**
1. `task-58-spec.md` - The specification (source of truth for requirements)
2. `implementation-guide.md` - Detailed guide with verified node lists and patterns
3. `task-58-handover.md` - Critical insights from research phase

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-58-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

You're creating 15 new test cases for the workflow generator that use ONLY real nodes or shell workarounds. These tests validate that the workflow generator can create actual, executable workflows - not imaginary ones.

Example of what you're replacing:
```python
# BAD (current) - uses non-existent nodes
expected_nodes=["analyze-code", "slack-notify", "build-project"]

# GOOD (new) - uses real nodes or shell
expected_nodes=["read-file", "llm", "shell"]  # shell runs 'gh release create'
```

## Key Outcomes You Must Achieve

### Test Distribution (15 total)
- 5 real developer workflows (changelog, PR summaries, test generation)
- 5 MCP integration tests (including Slack automation from trace)
- 3 complex multi-step workflows (8+ nodes)
- 2 edge cases (template stress, validation recovery)

### Node Reality Check
- 13/15 tests use ONLY real nodes from registry
- 2/15 tests use Slack MCP mocks (based on real trace evidence)
- 0 tests use any other mock nodes

### Natural Language Prompts
- Brief, realistic user inputs (not verbose essays)
- Include reuse scenarios showing brief vs detailed prompts
- Based on patterns from real planner trace

## Implementation Strategy

### Phase 1: Understand Current State (30 minutes)
1. Read the current test file to understand structure
2. Identify all mock nodes being used
3. Review the create_test_registry() function
4. Note the WorkflowTestCase dataclass structure

### Phase 2: Prepare Test Registry (30 minutes)
1. Update create_test_registry() to remove ALL mock nodes
2. Add ONLY 2 Slack MCP mocks:
   - `mcp-slack-slack_get_channel_history`
   - `mcp-slack-slack_post_message`
3. Verify registry loads real nodes correctly

### Phase 3: Implement Test Cases (2-3 hours)
1. Start with north star example: changelog_from_issues
2. Implement 5 real developer workflows
3. Add 5 MCP integration tests
4. Create 3 complex pipelines
5. Add 2 edge case tests

### Phase 4: Validate and Polish (1 hour)
1. Run tests with pytest
2. Check accuracy with test tool
3. Ensure all categories are covered
4. Verify natural language patterns

### Use Subagents effectively

Use subagents to maximize efficiency and avoid context window limitations.

> Always use @agent-pflow-codebase-searcher to gather information, context, do research and verifying assumptions. This is important!
> Always use the @agent-test-writer-fixer subagent for writing tests, fixing test failures, and debugging test issues.
> Always give subagents small isolated tasks, never more than fixes for one file at a time.
> Always deploy subagents in parallel, never sequentially. This means using ONE function call block to deploy all subagents simultaneously.

Implementation should be done by yourself! Write tests using the @agent-test-writer-fixer subagent AFTER implementation is complete.

## Critical Technical Details

### The Shell Node Magic
The shell node has NO restrictions on git/gh commands. You can use it for:
```python
# Git tagging (missing git-create-tag node)
"shell" with params={"command": "git tag v${version} && git push origin v${version}"}

# GitHub releases (missing github-create-release node)
"shell" with params={"command": "gh release create v${version} --title '${title}' --notes '${notes}'"}

# PR comments (missing github-comment-pr node)
"shell" with params={"command": "gh pr comment ${pr_number} --body '${comment}'"}
```

### MCP Mocking Pattern
Only mock these exact 2 nodes:
```python
def create_test_registry():
    from pflow.registry import Registry
    registry = Registry()

    # Load real registry first
    real_data = registry.load()

    # Add ONLY these 2 Slack MCP mocks
    test_nodes = {
        "mcp-slack-slack_get_channel_history": {
            "class_name": "MCPNode",
            "module": "pflow.nodes.mcp.node",
            "interface": {
                "inputs": ["channel_id", "limit"],
                "outputs": ["messages", "channel_info"]
            }
        },
        "mcp-slack-slack_post_message": {
            "class_name": "MCPNode",
            "module": "pflow.nodes.mcp.node",
            "interface": {
                "inputs": ["channel_id", "text"],
                "outputs": ["message_id", "timestamp"]
            }
        }
    }

    # Merge and monkey-patch
    merged_data = {**real_data, **test_nodes}
    registry.load = lambda: merged_data
    return registry
```

### Natural Language Pattern
From real trace at `/Users/andfal/.pflow/debug/planner-trace-20250904-160230.json`:
- User said: "get the last 10 message from the channel with id C09C16NAU5B..."
- Note: Imperfect grammar, natural phrasing, specific but not verbose

### Available Real Nodes (Use These)
- File: `read-file`, `write-file`, `copy-file`, `move-file`, `delete-file`
- Git: `git-commit`, `git-checkout`, `git-push`, `git-log`, `git-get-latest-tag`, `git-status`
- GitHub: `github-list-issues`, `github-list-prs`, `github-create-pr`, `github-get-issue`
- Core: `llm`, `shell`, `http`, `mcp`, `echo`

## Critical Warnings from Experience

### Mock Node Pollution
Current tests use these non-existent nodes - DO NOT USE THEM:
- `slack-notify`, `build-project`, `analyze-code`, `analyze-structure`
- `filter-data`, `validate-links`, `backup-database`, `run-migrations`
- `verify-data`, `fetch-profile`, `fetch-data`

### The North Star is Sacred
Test #1 MUST be the changelog generation from north star examples. This is non-negotiable.

### Shell Can Do Anything
Don't forget the shell node can run ANY command. Use it creatively for:
- Git operations not available as nodes
- GitHub CLI commands
- File operations like `find`, `grep`
- Package management like `npm outdated`

### pytest-xdist Missing
Despite references to parallel execution, pytest-xdist is NOT installed. Tests will run serially unless you add it.

## Key Decisions Already Made

1. **Option C chosen**: Use shell workarounds + minimal MCP mocks (user's explicit decision)
2. **Exactly 15 tests**: Replacing current 13 with 15 new ones
3. **Only 2 Slack MCP mocks**: Based on real trace evidence
4. **Shell for missing features**: Git tag, GitHub release, PR comments via shell node
5. **Natural language focus**: Brief, realistic prompts like actual users
6. **North star primary**: Changelog example must be first test

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework.

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Current Test Analysis**
   - Task: "Analyze test_workflow_generator_prompt.py and list all mock nodes currently being used"
   - Task: "Extract the exact WorkflowTestCase structure and test patterns"

2. **Registry Analysis**
   - Task: "Verify which nodes actually exist in the registry"
   - Task: "Check how MCP nodes are registered and named"

3. **Shell Node Capabilities**
   - Task: "Verify shell node can execute git and gh commands without restrictions"
   - Task: "Find examples of shell node usage in tests"

4. **North Star Examples**
   - Task: "Extract the exact north star examples from architecture/vision/north-star-examples.md"
   - Task: "Identify which examples can be implemented with real nodes"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_58/implementation/implementation-plan.md`

Your plan should include:
1. List of all mock nodes to remove
2. Exact 15 test cases with names and expected nodes
3. Which tests use shell workarounds
4. Which 2 tests use Slack MCP mocks
5. Testing strategy for verification

## Success Criteria

Your implementation is complete when:

- ✅ Exactly 15 test cases implemented
- ✅ 13 tests use only real nodes
- ✅ 2 tests use Slack MCP mocks (no other mocks)
- ✅ Shell workarounds used for git/gh operations
- ✅ North star changelog example is test #1
- ✅ Natural language prompts (not verbose)
- ✅ All tests pass validation
- ✅ `make test` passes
- ✅ `make check` passes
- ✅ Test accuracy tool runs successfully

## Common Pitfalls to Avoid

1. **Don't add "nice to have" mocks** - Only the 2 Slack MCP nodes, nothing else
2. **Don't make prompts verbose** - "generate changelog" not a paragraph
3. **Don't use non-existent nodes** - Check registry if unsure
4. **Don't forget shell workarounds** - Use shell for missing git/gh features
5. **Don't change existing test infrastructure** - Keep WorkflowTestCase structure
6. **Don't skip the north star** - Changelog example must be first

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_58/implementation/progress-log.md`

```markdown
# Task 58 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### 1. Analyze current state
- List all mock nodes being removed
- Document the transition plan

### 2. Update registry mock
- Remove all fake nodes
- Add only 2 Slack MCP mocks

### 3. Implement north star test
- Start with changelog_from_issues
- Verify it uses only real nodes

### 4. Add remaining tests
- 4 more developer workflows
- 5 MCP integration tests
- 3 complex pipelines
- 2 edge cases

### 5. Validate everything
- Run pytest
- Check with accuracy tool
- Ensure categories are correct

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to replace mock slack-notify with shell workaround...

Result: Discovered shell can use curl for webhooks
- ✅ What worked: shell with curl command
- ❌ What failed: Direct slack integration
- 💡 Insight: Shell enables any external integration

Code that worked:
```python
expected_nodes=["github-list-issues", "llm", "shell"]
# shell runs: curl -X POST slack_webhook_url -d '{"text":"${message}"}'
```
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage.

**Core Testing Principle**: These ARE the tests - they're testing the workflow generator's ability to create valid workflows.

**Each test case needs**:
- Realistic user input (natural language)
- Correct expected nodes (only real ones or shell)
- Proper template variable expectations
- Clear category assignment

## What NOT to Do

- **DON'T** use any mock nodes except the 2 Slack MCP ones
- **DON'T** create verbose test prompts
- **DON'T** skip the north star example
- **DON'T** modify the test infrastructure
- **DON'T** add features not in spec
- **DON'T** forget to document discoveries in progress log

## Getting Started

1. Read all context files in order
2. Create your progress log
3. Analyze current tests to understand what's being replaced
4. Start with the registry update
5. Implement north star test first
6. Run frequently: `RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_workflow_generator_prompt.py -v`

## Final Notes

- The shell node is your Swiss Army knife - use it creatively
- Natural language is key - think like a lazy user
- The north star example is sacred - implement it exactly
- Document everything unusual in your progress log
- This is about reality vs fantasy in testing

## Remember

You're not just updating tests - you're shifting the entire testing philosophy from "can the AI imagine workflows" to "can the AI create REAL workflows that ACTUALLY work". Every mock node you remove is a step toward truth. Every shell workaround you add is a creative solution to a real constraint.

This task directly impacts the reliability of the workflow generator. By grounding tests in reality, you're ensuring that what passes tests will actually work in production.

Good luck! Make these tests reflect what pflow can actually do, not what we wish it could do.