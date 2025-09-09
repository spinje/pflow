# Task 58: Critical Handover Intelligence

**⚠️ TO THE IMPLEMENTING AGENT**: Read this entire document before starting. At the end, simply confirm you're ready to begin. This contains hard-won insights that will save you hours.

## 🔥 The Most Important Thing You Need to Know

The current tests **appear to work** but are fundamentally broken. They use 30+ mock nodes that don't exist (`slack-notify`, `build-project`, `analyze-code`, etc.). This gives everyone false confidence. Your job is to replace fantasy with reality while maintaining test coverage.

## 🎯 The User's Specific Decision

After extensive discussion, the user chose **Option C: Use shell workarounds + minimal MCP mocks**. This was a deliberate choice over:
- Option A: Pure reality (too limiting)
- Option B: Strategic mocks (too much fantasy)

**Critical**: Only mock 2 Slack MCP nodes. Everything else must be real or use shell workarounds.

## 💎 The Golden Trace File

**THIS IS GOLD**: `/Users/andfal/.pflow/debug/planner-trace-20250904-160230.json`

This trace shows how a REAL user actually created a workflow:
- Input: `"get the last 10 message from the channel with id C09C16NAU5B and use ai to answer any questions that is asked, send the answer to the same channel as a slack message"`
- Note the imperfect grammar, natural phrasing
- This is your template for realistic test prompts

## 🚀 The Shell Node Discovery

I spent significant time verifying this: **The shell node has ZERO restrictions on git/gh commands**.

File: `/Users/andfal/projects/pflow-test-workflow-generator-tests/src/pflow/nodes/shell/shell.py`
- Lines 51-92 show the security patterns
- Git and gh commands are NOT restricted
- You can run `git tag v1.0.0 && git push origin v1.0.0` directly
- You can run `gh release create` with full arguments
- This enables ALL our workarounds

**Don't second-guess this** - I verified it exhaustively.

## ⚠️ The MCP Trap

MCP nodes are **NOT in the registry by default**. They only appear after:
1. `pflow mcp add <server> <command>`
2. `pflow mcp sync <server>`

This is why we must mock the Slack MCP nodes. The pattern is in existing tests:
- `/Users/andfal/projects/pflow-test-workflow-generator-tests/tests/test_mcp/test_mcp_discovery_critical.py:213`

## 📊 What's Real vs Fantasy

### These nodes ACTUALLY exist (verified):
- All file nodes: `read-file`, `write-file`, `copy-file`, `move-file`, `delete-file`
- All git nodes: `git-commit`, `git-checkout`, `git-push`, `git-log`, `git-get-latest-tag`, `git-status`
- All GitHub API nodes: `github-list-issues`, `github-list-prs`, `github-create-pr`, `github-get-issue`
- Core nodes: `llm`, `shell`, `http`, `mcp`, `echo`

### These nodes DON'T exist (current tests pretend they do):
- ❌ `slack-notify` (30+ tests use this!)
- ❌ `build-project`
- ❌ `analyze-code`, `analyze-structure`
- ❌ `filter-data`, `validate-links`
- ❌ `backup-database`, `run-migrations`, `verify-data`
- ❌ `fetch-profile`, `fetch-data`
- ❌ `github-create-release` (use `shell` + `gh release create`)
- ❌ `git-tag` or `git-create-tag` (use `shell` + `git tag`)

## 🎭 The Test Philosophy Shift

Current tests: "Can the AI imagine a workflow with any nodes we dream up?"
New tests: "Can the AI create REAL workflows that ACTUALLY work?"

This is a fundamental shift from fantasy to reality.

## 🔧 Technical Gotchas

### 1. WorkflowTestCase Structure
The dataclass is fixed - don't change existing fields or you'll break the test infrastructure. You can ADD fields but not modify existing ones.

### 2. pytest-xdist Not Installed
Despite references to parallel execution, pytest-xdist is NOT in dependencies. The tests will run serially unless you manually install it. The 15-second target assumes parallel execution that won't happen by default.

### 3. Cost Tracking Exists But...
The $0.50 target is aspirational. Real costs are tracked in frontmatter but vary widely. Don't treat this as a hard constraint.

### 4. The create_test_registry() Function
This is your leverage point. It merges real nodes with mocks. Only add the 2 Slack MCP nodes here.

## 📝 Natural Language is Key

Look at the trace - users don't say:
> "Create a comprehensive changelog by fetching the last 30 closed issues from the GitHub repository anthropic/pflow, analyzing them with artificial intelligence to categorize by type..."

They say:
> "generate changelog from closed issues"

Your test prompts should reflect this reality.

## 🌟 The North Star Example

**This is non-negotiable**: The changelog generation example from `architecture/vision/north-star-examples.md` MUST be test #1. It's marked with 🌟 for a reason - it's the canonical example of pflow's value.

## 🚨 Warnings from the Trenches

1. **Don't get creative** - Follow the north star examples exactly
2. **Don't add "nice to have" mock nodes** - Only the 2 Slack MCP nodes
3. **Don't make prompts verbose** - Real users are lazy typists
4. **Don't change the test count** - Exactly 15 tests, replacing the current 13
5. **Don't forget shell workarounds** - They're not hacks, they're legitimate solutions

## 🔗 Critical Files for Reference

- **Current broken tests**: `/Users/andfal/projects/pflow-test-workflow-generator-tests/tests/test_planning/llm/prompts/test_workflow_generator_prompt.py`
- **Shell node (proving no restrictions)**: `src/pflow/nodes/shell/shell.py`
- **MCP mocking pattern**: `tests/test_mcp/test_mcp_discovery_critical.py:213`
- **North star examples**: `architecture/vision/north-star-examples.md`
- **Real user trace**: `/Users/andfal/.pflow/debug/planner-trace-20250904-160230.json`

## 🎬 Your Starting Point

1. Read the spec and implementation guide
2. Study the current test file to understand the structure
3. Look at the trace file for natural language patterns
4. Start with the north star changelog example
5. Build out the 15 tests incrementally
6. Run the accuracy tool to verify

## 🧠 The Unspoken Context

The user is clearly frustrated with mock-heavy tests that don't validate real functionality. They want tests that would actually catch problems if nodes were missing or broken. This isn't just about updating tests - it's about shifting from imagination to reality.

The journey from "let's test everything" to "let's test what actually exists" was painful but necessary. Don't undo this work by adding unnecessary mocks.

---

**Remember**: You're not just updating tests. You're grounding the entire workflow generator testing system in reality. Every mock you remove is a step toward truth.

**TO THE IMPLEMENTING AGENT**: Confirm you've read this and are ready to begin implementation of Task 58.