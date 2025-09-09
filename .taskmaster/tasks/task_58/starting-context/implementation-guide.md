# Task 58: Implementation Guide for Workflow Generator Test Updates

## Critical Context for Implementation

This guide captures essential information discovered during research and verification for Task 58. The implementing agent should read this alongside the spec to understand the full context.

## Current Test Problems (Why We're Doing This)

The current `test_workflow_generator_prompt.py` has 13 tests with these critical issues:
1. **Mock node pollution**: Uses non-existent nodes like `slack-notify`, `build-project`, `backup-database`, `fetch-profile`, `run-migrations`
2. **Zero MCP testing**: Despite 22+ MCP nodes available via `pflow mcp sync`
3. **Unrealistic prompts**: Overly verbose, unlike actual user behavior
4. **False confidence**: Tests pass with fictional nodes

## Verified Available Nodes (Use These Only)

### Core Nodes (All Verified to Exist)
- `llm` - General-purpose LLM with template variables
- `shell` - Execute ANY shell command (no restrictions on git/gh)
- `http` - HTTP requests
- `mcp` - Universal MCP node
- `echo` - Test node

### File Operations (All Exist)
- `read-file`, `write-file`, `copy-file`, `move-file`, `delete-file`

### Git Operations (All Exist)
- `git-status`, `git-commit`, `git-checkout`, `git-push`, `git-log`, `git-get-latest-tag`

### GitHub API Operations (All Exist)
- `github-list-issues`, `github-list-prs`, `github-create-pr`, `github-get-issue`

### What's Missing (Use Shell Workarounds)
- ❌ `github-create-release` → Use `shell` with `gh release create`
- ❌ `git-create-tag` → Use `shell` with `git tag v1.0.0`
- ❌ `github-comment-pr` → Use `shell` with `gh pr comment`
- ❌ Any Slack nodes → Mock only 2 MCP nodes (see below)

## Shell Node Capabilities (Verified)

The `ShellNode` has **NO restrictions** on git/gh commands:
- ✅ Can run: `git tag v1.0.0 && git push origin v1.0.0`
- ✅ Can run: `gh release create v1.0.0 --title "Release" --notes "Notes"`
- ✅ Can run: `gh pr comment 123 --body "Comment"`
- ✅ Supports pipes, &&, ||, for loops, command substitution
- ✅ Environment variables via `env` parameter
- ✅ Working directory via `cwd` parameter

## MCP Mocking Pattern (From Existing Tests)

Only mock these 2 Slack MCP nodes (based on real trace):

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

## Real-World Trace Pattern (Inform Test Design)

From `/Users/andfal/.pflow/debug/planner-trace-20250904-160230.json`:
- **User input**: "get the last 10 message from the channel with id C09C16NAU5B and use ai to answer any questions that is asked, send the answer to the same channel as a slack message"
- **Workflow**: `mcp-slack-slack_get_channel_history` → `llm` → `mcp-slack-slack_post_message`
- **Parameters extracted**: `channel_id`, `message_count`, `temperature`
- **Shows**: Real users give natural, slightly imperfect prompts

## Test Infrastructure Details (Verified)

### Current WorkflowTestCase Structure
```python
@dataclass
class WorkflowTestCase:
    name: str
    user_input: str
    discovered_params: dict[str, str]
    planning_context: str
    browsed_components: dict
    validation_errors: Optional[list[str]]  # For retry tests
    expected_nodes: list[str]
    min_nodes: int
    max_nodes: int
    must_have_inputs: list[str]
    must_not_have_inputs: list[str]
    node_output_refs: list[str]
    category: str
    why_hard: str
```

### Test Categories to Use
- `north_star` - Primary examples from architecture/vision/north-star-examples.md
- `mcp_integration` - Tests using MCP nodes
- `complex_pipeline` - 8+ node workflows
- `shell_workaround` - Tests using shell for missing functionality
- `edge_case` - Template stress, validation recovery

## Specific Test Cases to Implement (15 Total)

### 1. North Star: Changelog Generation ⭐
```python
name="changelog_from_issues",
user_input="Generate a changelog from the last 20 closed issues in github repo anthropic/pflow, categorize by type, write to CHANGELOG.md, and commit",
expected_nodes=["github-list-issues", "llm", "write-file", "git-commit"]
```

### 2. Release with Shell Workarounds
```python
name="release_workflow",
user_input="Get commits since last tag, generate release notes, create tag v1.3.0, push tag, create GitHub release",
expected_nodes=["git-get-latest-tag", "git-log", "llm", "shell", "shell"]  # shell for: git tag, gh release
```

### 3. Slack Q&A Automation (MCP)
```python
name="slack_qa_automation",
user_input="Get last 10 messages from slack channel C09C16NAU5B, answer questions with AI, send back to channel",
expected_nodes=["mcp-slack-slack_get_channel_history", "llm", "mcp-slack-slack_post_message"]
```

[Continue with remaining 12 test cases as designed in scratchpads]

## Implementation Checklist

1. [ ] Remove ALL mock nodes except 2 Slack MCP
2. [ ] Update `create_test_registry()` function
3. [ ] Replace 13 existing test cases with 15 new ones
4. [ ] Use natural language prompts (not verbose)
5. [ ] Include `category` field for each test
6. [ ] Test shell workarounds for git/gh operations
7. [ ] Preserve `report_failure()` mechanism
8. [ ] Maintain `pytest.mark.parametrize` pattern
9. [ ] Run `uv run python tools/test_prompt_accuracy.py workflow_generator` to verify

## Key Testing Patterns

### Shell Workaround Pattern
```python
# For missing github-create-release
"shell" with params={"command": "gh release create v${version} --title '${title}' --notes '${notes}'"}

# For missing git-create-tag
"shell" with params={"command": "git tag ${tag_name} && git push origin ${tag_name}"}
```

### Template Variable Testing
- User inputs → `${variable_name}`
- Node outputs → `${node_id.output_key}`
- Never put node outputs in workflow inputs section

## Common Pitfalls to Avoid

1. **Don't use these mock nodes** (they don't exist):
   - `slack-notify`, `build-project`, `analyze-code`, `filter-data`
   - `backup-database`, `run-migrations`, `verify-data`

2. **Don't forget shell can do anything**:
   - Git operations, GitHub CLI, grep, find, npm, etc.

3. **Don't make prompts too verbose**:
   - Bad: "Create a comprehensive changelog by fetching the last 30 closed issues..."
   - Good: "Generate changelog from last 30 closed issues"

## Success Criteria

- ✅ 13/15 tests use only real nodes
- ✅ 2/15 tests use Slack MCP mocks
- ✅ Shell workarounds for missing git/gh features
- ✅ Natural language prompts
- ✅ Tests pass validation
- ✅ Clear categories for organization
- ✅ North star example included