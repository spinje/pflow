# Task 42: Claude Code Agentic Node - Agent Instructions

## The Problem You're Solving

Currently, pflow lacks integration with Claude Code, Anthropic's agentic coding assistant that can perform complex, multi-step development tasks with full project context. Users cannot leverage Claude's comprehensive development capabilities within workflows, limiting automation of sophisticated coding tasks that require understanding, analysis, and file modifications.

## Your Mission

Implement the Claude Code Agentic Node using the Python SDK (`claude-code-sdk`) with a dynamic schema-driven output system, enabling workflows to leverage Claude's AI-assisted development capabilities with structured, predictable outputs.

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
**File**: `.taskmaster/tasks/task_42/task-42.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_42/starting-context/`

**Files to read (in this order):**
1. `task-42-spec.md` - The verified specification (FOLLOW THIS PRECISELY - source of truth for requirements)
2. `implementation-insights.md` - Critical implementation guidance with SDK patterns and code examples
3. `task-42-handover.md` - Context from research phase including key discoveries and pitfalls

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-42-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

A "super node" for pflow that integrates with Claude Code Python SDK to execute comprehensive development tasks. The node features a dynamic schema-driven output system where users provide an output schema that gets converted to system prompt instructions, enabling structured outputs from Claude's unstructured text generation.

Example usage:
```python
# Basic execution
shared = {"task": "Write a fibonacci function"}
node = ClaudeCodeNode()
# Returns full text in shared["result"]

# With schema-driven output
shared = {
    "task": "Review this code for security issues",
    "output_schema": {
        "risk_level": {"type": "str", "description": "high/medium/low"},
        "issues": {"type": "list", "description": "List of security issues"}
    }
}
node = ClaudeCodeNode()
# Schema converted to JSON instructions in system prompt
# Response parsed and stored as: shared["risk_level"], shared["issues"]
# Fallback to shared["result"] if parsing fails
```

## Key Outcomes You Must Achieve

### Core SDK Integration
- Implement Claude Code node using `claude-code-sdk` Python package (NOT CLI subprocess)
- Use correct SDK parameters: `max_thinking_tokens` (NOT max_tokens), NO temperature parameter
- Implement async-to-sync wrapper using `asyncio.run()` pattern from MCP node
- Handle timeout at asyncio level (SDK has no timeout parameter)

### Dynamic Schema System
- Convert output_schema to JSON format instructions in system prompt
- Implement multiple JSON extraction strategies (code blocks, raw JSON, fallback patterns)
- Store parsed values in shared store using schema keys
- Fallback to `shared["result"]` and `shared["_schema_error"]` when parsing fails

### Security and Safety
- Enforce tool whitelist: ["Read", "Write", "Edit", "Bash"] only
- Validate working directory (no restricted paths)
- Check authentication via subprocess: `claude --version` and `claude doctor`
- Block dangerous bash patterns

## Implementation Strategy

### Phase 1: Package Structure and Core Node (1 hour)
1. Create package at `src/pflow/nodes/claude/`
2. Create `claude_code.py` with ClaudeCodeNode class
3. Add `__init__.py` with exports
4. Install dependency: `pip install claude-code-sdk`

### Phase 2: Authentication and Validation (1 hour)
1. Implement subprocess authentication check (`claude --version`, `claude doctor`)
2. Add working directory validation
3. Implement parameter validation and fallbacks
4. Add tool whitelist enforcement

### Phase 3: SDK Integration (2-3 hours)
1. Implement async-to-sync wrapper following MCP pattern exactly
2. Build ClaudeCodeOptions with correct parameters
3. Implement `_exec_async()` method with timeout handling
4. Parse AssistantMessage and TextBlock responses

### Phase 4: Schema System (2-3 hours)
1. Implement schema-to-prompt converter
2. Add JSON extraction with multiple strategies
3. Implement fallback to raw text on parse failure
4. Store results in shared store with schema keys

### Phase 5: Error Handling (1 hour)
1. Transform SDK exceptions to user-friendly messages
2. Implement exec_fallback for all error types
3. Add rate limit and timeout handling
4. Ensure errors bubble up for retry mechanism

### Phase 6: Testing (2-3 hours)
1. Create test structure at `tests/test_nodes/test_claude/`
2. Mock SDK query function and subprocess calls
3. Test all 23 criteria from spec
4. Use test-writer-fixer subagent for comprehensive tests

### Use Subagents effectively

Use subagents to maximize efficiency and avoid context window limitations.

> Always use @agent-pflow-codebase-searcher to gather information, context, do research and verifying assumptions. This is important!
> Always use the @agent-test-writer-fixer subagent for writing tests, fixing test failures, and debugging test issues.
> Always give subagents small isolated tasks, never more than fixes for one file at a time.
> Always deploy subagents in parallel, never sequentially. This means using ONE function call block to deploy all subagents simultaneously.

Implementation should be done by yourself! Write tests using the @agent-test-writer-fixer subagent AFTER implementation is complete.

## Critical Technical Details

### Correct SDK Parameters
```python
from claude_code_sdk import ClaudeCodeOptions

# ✅ CORRECT - These parameters exist:
options = ClaudeCodeOptions(
    model="claude-3-5-sonnet-20241022",
    max_thinking_tokens=8000,  # NOT max_tokens!
    allowed_tools=["Read", "Write", "Edit", "Bash"],
    system_prompt=schema_prompt + user_prompt,  # Merged prompts
    cwd=working_directory,
    permission_mode="acceptEdits"
)

# ❌ WRONG - These do NOT exist:
# temperature - NOT supported by SDK
# max_tokens - It's max_thinking_tokens
# timeout - Handle at asyncio level
```

### Async-to-Sync Pattern (EXACTLY like MCP node)
```python
def exec(self, prep_res: dict[str, Any]) -> str:
    """Execute synchronously."""
    # NO try/except here - let exceptions bubble up for retry!
    result = asyncio.run(self._exec_async(prep_res), debug=False)
    return "success"

async def _exec_async(self, prep_res: dict[str, Any]) -> None:
    """Async implementation with timeout."""
    timeout_context = getattr(asyncio, "timeout", None)
    if timeout_context is not None:
        # Python 3.11+
        async with timeout_context(300):
            await self._call_claude(prep_res)
    else:
        # Python 3.10
        await asyncio.wait_for(
            self._call_claude(prep_res),
            timeout=300
        )
```

### Schema-to-Prompt Conversion
```python
def _build_schema_prompt(self, schema: dict) -> str:
    """Convert schema to JSON instructions."""
    json_template = {}
    for key, config in schema.items():
        type_str = config.get("type", "str")
        desc = config.get("description", "")
        json_template[key] = f"<{type_str}: {desc}>"

    return (
        "You must structure your final response as valid JSON:\n"
        f"{json.dumps(json_template, indent=2)}\n"
        "Provide ONLY the JSON object in a code block after completing your analysis."
    )
```

## Critical Warnings from Experience

### Parameter Name Confusion
**The SDK uses `max_thinking_tokens` NOT `max_tokens`!** This was a major discovery during research. Also, `temperature` parameter DOES NOT EXIST in ClaudeCodeOptions - don't try to use it.

### Async Exception Handling
**DO NOT catch exceptions in exec() method!** Let them bubble up for PocketFlow's retry mechanism. This is intentional and follows the MCP node pattern.

### JSON Parsing Will Fail Sometimes
Claude won't always output clean JSON even with instructions. You MUST implement multiple extraction strategies and always have a fallback to raw text in `shared["result"]`.

### Authentication is Two-Step
The SDK doesn't have an auth check method. You must use subprocess to check CLI installation AND catch SDK auth errors as backup.

### Tool Names are Limited
Only these tools are verified to exist: ["Read", "Write", "Edit", "Bash"]. Don't add "LS", "Grep", or others without verification.

## Key Decisions Already Made

1. **Use Python SDK not CLI** - Better integration, structured responses, superior error handling
2. **Schema-as-system-prompt approach** - Convert schema to prompt instructions for structured output
3. **Conservative retry strategy** - Only 2 attempts (expensive API calls)
4. **Timeout at asyncio level** - 300 seconds via wrapper, not SDK parameter
5. **Tool whitelist enforcement** - Security over flexibility
6. **JSON fallback to raw text** - Data preservation over strict typing

**📋 Note on Specifications**: The specification file (`task-42-spec.md`) is the authoritative source. Follow it precisely - do not deviate from specified behavior, test criteria, or implementation requirements unless you discover a critical issue (in which case, document the deviation clearly or STOP and ask the user for clarification).

## Success Criteria

Your implementation is complete when:

- ✅ All 23 test criteria from the spec pass
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ Authentication check works via subprocess
- ✅ Schema-to-prompt conversion generates valid instructions
- ✅ JSON extraction works with fallback to raw text
- ✅ Timeout handling works at asyncio level
- ✅ Error messages are user-friendly with remediation steps
- ✅ Tool whitelist is enforced

## Common Pitfalls to Avoid

1. **Don't use `temperature` parameter** - It doesn't exist in the SDK
2. **Don't use `max_tokens`** - It's `max_thinking_tokens`
3. **Don't catch exceptions in exec()** - Let them bubble for retry
4. **Don't assume JSON parsing succeeds** - Always implement fallback
5. **Don't skip subprocess auth check** - SDK doesn't have this method
6. **Don't use `shell=True` in subprocess** - Security risk
7. **Don't hardcode tool names** - Use configurable whitelist
8. **Don't trust Claude's output format** - Always validate
9. **Don't implement streaming** - Not in v1 scope

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent conflicts.

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Node Implementation Patterns**
   - Task: "Analyze src/pflow/nodes/mcp/mcp_node.py to understand async-to-sync wrapper pattern and timeout handling"
   - Task: "Study src/pflow/nodes/llm/llm.py for parameter fallback patterns and external service integration"
   - Task: "Examine src/pflow/nodes/shell/shell.py for subprocess execution and security patterns"

2. **Testing Infrastructure**
   - Task: "Analyze tests/test_nodes/test_mcp/ for async mocking patterns"
   - Task: "Study tests/test_nodes/test_llm/ for external service mocking"
   - Task: "Check tests/conftest.py for test fixtures and utilities"

3. **Registry Integration**
   - Task: "Understand how nodes are registered in src/pflow/registry/"
   - Task: "Check how Enhanced Interface Format is parsed from docstrings"

4. **Error Handling Patterns**
   - Task: "Find exec_fallback implementations across existing nodes"
   - Task: "Identify user-friendly error transformation patterns"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_42/implementation/implementation-plan.md`

Your plan should include:
1. **Comprehensive task breakdown** - Every file to create/modify
2. **Dependency mapping** - SDK installation, authentication setup
3. **Risk identification** - JSON parsing reliability, auth check accuracy
4. **Testing strategy** - Mock patterns for SDK and subprocess

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_42/implementation/progress-log.md`

```markdown
# Task 42 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. Install claude-code-sdk dependency
2. Create package structure at src/pflow/nodes/claude/
3. Implement authentication checking via subprocess
4. Build core ClaudeCodeNode class with prep/exec/post
5. Add async-to-sync wrapper following MCP pattern
6. Implement schema-to-prompt converter
7. Add JSON extraction with multiple strategies
8. Implement exec_fallback error transformations
9. Write comprehensive tests with mocks
10. Verify all test criteria pass

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - Discovering SDK behavior
Attempting to use temperature parameter...

Result: AttributeError - ClaudeCodeOptions has no temperature
- ✅ What worked: max_thinking_tokens parameter
- ❌ What failed: temperature doesn't exist
- 💡 Insight: SDK parameters differ from typical LLM APIs

Code that worked:
```python
options = ClaudeCodeOptions(
    max_thinking_tokens=8000,  # Correct parameter
    # temperature=0.5  # DOESN'T EXIST
)
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

**Critical Test Areas**:
- Authentication check via subprocess
- Schema-to-prompt conversion
- JSON extraction with fallback
- Async timeout handling
- SDK exception transformation
- Tool whitelist enforcement

**Mock Patterns You'll Need**:
```python
# Mock SDK query function
@patch("pflow.nodes.claude.claude_code.query")
async def test_execution(mock_query):
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[
            TextBlock(text='{"result": "success"}')
        ])
    mock_query.return_value = mock_response()

# Mock subprocess for auth
@patch("subprocess.run")
def test_auth(mock_run):
    mock_run.side_effect = [
        Mock(returncode=0),  # claude --version
        Mock(returncode=0)   # claude doctor
    ]
```

## What NOT to Do

- **DON'T** use temperature parameter - doesn't exist
- **DON'T** use max_tokens - it's max_thinking_tokens
- **DON'T** implement CLI subprocess for SDK calls - use Python SDK
- **DON'T** catch exceptions in exec() - let them bubble
- **DON'T** assume JSON parsing works - always have fallback
- **DON'T** skip authentication check - critical for user experience
- **DON'T** add features not in spec - no streaming, no conversation state
- **DON'T** modify existing nodes - this is standalone

## Getting Started

1. First, read the epistemic manifesto to understand the approach
2. Read all three context files in order (spec, insights, handover)
3. Install the SDK: `pip install claude-code-sdk`
4. Check if Claude CLI is installed: `claude --version`
5. Create progress log and implementation plan
6. Start with package structure creation
7. Run tests frequently: `pytest tests/test_nodes/test_claude/ -v`

## Final Notes

- The schema-as-system-prompt approach is the key innovation
- The SDK research revealed critical parameter differences
- Authentication requires both subprocess and SDK error handling
- JSON extraction needs multiple fallback strategies
- The MCP node provides the exact async pattern to follow

## Remember

You're implementing a "super node" that breaks pflow's simple node philosophy intentionally because it provides comprehensive AI-assisted development capabilities. The schema-driven output system is a clever workaround for missing SDK features. When Claude Code SDK eventually adds native structured output support, this can be simplified.

The research phase discovered many pitfalls (wrong parameter names, missing features) that have been documented. Trust the implementation insights but verify against the specification.

This node will enable powerful AI-driven development workflows in pflow. Good luck!