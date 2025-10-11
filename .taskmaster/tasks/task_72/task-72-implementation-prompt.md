# Task 72: Implement MCP Server for pflow - Agent Instructions

## The Problem You're Solving

AI agents currently use pflow through CLI commands, which adds overhead from process spawning and requires text parsing of outputs. Some AI systems (Cursor, Continue, Claude Code) need programmatic access via MCP protocol for better performance and structured responses. Agents need a way to discover, build, test, and execute workflows without shell access.

## Your Mission

Implement an MCP (Model Context Protocol) server that exposes pflow's 13 core workflow building and execution capabilities as programmatically accessible tools for AI agents. This server provides the same capabilities as the CLI but with structured JSON responses and better performance.

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
**File**: `.taskmaster/tasks/task_72/task-72.md`

**Purpose**: High-level overview of the MCP server task, including the 13 tools to implement, design decisions, and implementation timeline. This document provides the essential context for what needs to be built.

**Why read second**: This gives you the big picture of the MCP server architecture and tool organization before diving into detailed specifications.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_72/starting-context/`

**Files to read (in this order):**
1. `final-implementation-spec.md` - Complete technical specification for the 13 tools
2. `mcp-implementation-guidance.md` - Consolidated best practices and patterns
3. `mcp-protocol-best-practices.md` - Protocol-level guidance for MCP
4. `task-72-comprehensive-research.md` - Analysis of pflow architecture readiness
5. `task-72-handover-doc.md` - Critical context from the analysis phase
6. `task-72-handover.md` - Additional handover context

**Instructions**: Read EACH file listed above in order. The `final-implementation-spec.md` is your source of truth for the 13 tools and their specifications. The guidance files contain critical patterns for security, stateless operation, and error handling.

### 4. Read Research Documentation
**Directory**: `.taskmaster/tasks/task_72/research/`

**Core Research Files:**
1. `pflow-commands-extraction.md` - Analysis of all CLI commands agents use

**MCP Documentation** (in `.taskmaster/tasks/task_72/research/mcp/`):
1. `server-basics.md` - FastMCP server initialization and setup
2. `tool-implementation.md` - How to define tools with decorators and schemas
3. `error-handling-testing.md` - Error patterns and testing approaches
4. `advanced-patterns.md` - Progress reporting and middleware
5. `full-docs-mcp.md` - Complete FastMCP reference (if needed, consider using subagents to gather information from this file instead of reading it yourself if you need to consult more docs)

**Instructions**: These research files contain the FastMCP patterns you'll implement. Pay special attention to the instance method registration pattern in `tool-implementation.md`.

If you are still unsure or run into problems, you can use subagents to gather information from `full-docs-mcp.md` or letting them search the internet for more information. Do not research internet yourself, let subagents do the research for you.

## What You're Building

An MCP server exposing **13 tools** organized in three priority tiers:

### Priority 1: Core Workflow Loop (6 tools)
1. **`workflow_discover`** - Find existing workflows using LLM matching
2. **`registry_discover`** - Find nodes for building using LLM selection
3. **`registry_run`** - Test node execution to reveal output structure
4. **`workflow_execute`** - Execute with JSON output, no repair, trace enabled
5. **`workflow_validate`** - Validate structure without execution
6. **`workflow_save`** - Save to global library

### Priority 2: Supporting Functions (5 tools)
7. **`registry_describe`** - Get detailed node specifications
8. **`registry_search`** - Find nodes by pattern
9. **`workflow_list`** - List saved workflows
10. **`settings_set`** - Configure API keys
11. **`settings_get`** - Retrieve settings

### Priority 3: Advanced (2 tools)
12. **`registry_list`** - Browse all nodes (verbose)
13. **`trace_read`** - Parse execution traces

Example usage pattern:
```python
# MCP server running
mcp = FastMCP("pflow", version="0.1.0")

@mcp.tool()
async def workflow_execute(workflow: str | dict, parameters: dict = None) -> dict:
    """Execute workflow with agent-optimized defaults."""
    # Always returns JSON, never auto-repairs, saves trace
    result = await asyncio.to_thread(execute_workflow, ...)
    return {"success": True, "outputs": result.output_data}
```

## Key Outcomes You Must Achieve

### Core Server Implementation
- FastMCP server with 13 tools in `src/pflow/mcp_server/`
- Direct service integration (not CLI wrapping)
- Stateless operation (fresh instances per request)
- Agent-optimized defaults (JSON output, no repair, traces)

### Tool Organization
- Discovery tools using LLM (ComponentBrowsingNode, WorkflowDiscoveryNode)
- Execution tools with structured responses and checkpoints
- Settings management for API keys
- Trace reading for debugging

### Integration & Testing
- `pflow serve mcp` CLI command for stdio transport
- Comprehensive unit tests for each tool
- Integration tests for workflow cycles
- Security validation (path traversal, sensitive data)

## Implementation Strategy

### Phase 1: Core Tools (2 days)
1. Set up FastMCP server structure in `src/pflow/mcp_server/`
2. Implement 6 Priority 1 tools with agent defaults
3. Test discovery → execute → save cycle
4. Verify stateless operation

### Phase 2: Supporting Tools (1 day)
1. Implement 5 Priority 2 tools
2. Add settings management
3. Test complete workflows
4. Verify error handling

### Phase 3: Testing & Validation (1 day)
1. Write comprehensive unit tests
2. Test with AGENT_INSTRUCTIONS workflows
3. Validate Claude Code discovery
4. Performance testing vs CLI

### Phase 4: Advanced Tools (0.5 day)
1. Implement Priority 3 tools if time permits
2. Documentation and examples
3. Final integration testing

### Use Subagents effectively

Use subagents to maximize efficiency and avoid context window limitations.

> Always use @agent-pflow-codebase-searcher to gather information, context, do research and verifying assumptions. This is important!
> Always use the @agent-test-writer-fixer subagent for writing tests, fixing test failures, and debugging test issues.
> Always give subagents small isolated tasks, never more than fixes for one file at a time.
> Always deploy subagents in parallel, never sequentially. This means using ONE function call block to deploy all subagents simultaneously.

Implementation should be done by yourself! Write tests using the @agent-test-writer-fixer subagent AFTER implementation is complete.

## Critical Technical Details

### Stateless Pattern (MANDATORY)
```python
# ✅ CORRECT - Fresh instances per request
async def execute_tool(name: str, **params):
    manager = WorkflowManager()  # Fresh instance
    registry = Registry()         # Fresh instance
    # use and discard

# ❌ WRONG - Shared state
class PflowMCPServer:
    def __init__(self):
        self.manager = WorkflowManager()  # Will go stale!
```

### Agent Mode Defaults
All tools automatically apply these defaults (no parameters needed):
- Always return JSON structures
- Never auto-repair (explicit errors)
- Always save execution traces
- Auto-normalize workflows (add ir_version, edges)

### Discovery Tools Use Planning Nodes
```python
# Direct node reuse pattern
from pflow.planning.nodes import WorkflowDiscoveryNode
node = WorkflowDiscoveryNode()
shared = {"user_input": query, "workflow_manager": WorkflowManager()}
node.run(shared)
result = shared["discovery_result"]
```

### Instance Method Registration Pattern
```python
class WorkflowTools:
    def __init__(self, mcp: FastMCP):
        self.mcp = mcp
        # Register instance methods as tools
        self.mcp.tool(self.workflow_execute)
        self.mcp.tool(self.workflow_validate)
```

### Security Validation
```python
def validate_workflow_name(name: str):
    if any(c in name for c in ['/', '\\', '..', '~']):
        raise SecurityError(f"Invalid characters: {name}")
```

## Critical Warnings from Experience

### Planning Nodes Require workflow_manager
ComponentBrowsingNode and WorkflowDiscoveryNode will fail with "Invalid request" if you don't include:
```python
shared = {
    "user_input": query,
    "workflow_manager": WorkflowManager()  # REQUIRED!
}
```

### MCP Node Testing is Essential
Documentation shows `result: Any` but reality is deeply nested:
```python
# What docs say: result
# What you get: result.data.tool_response.nested.deeply.url
# Use registry_run to reveal actual structure
```

### Token Overhead Considerations
Each tool adds ~100-500 tokens overhead. With 13 tools = ~1,300-6,500 tokens (acceptable but be aware).

### Error Response Pattern
Always use structured errors that LLMs can see:
```python
# Good - LLM visible
return {"success": False, "error": {"type": "validation", "message": "..."}}

# Bad - Hidden from LLM
raise Exception("...")
```

## Key Decisions Already Made

1. **13 tools, not 5 or 18** - Based on agent usage patterns from AGENT_INSTRUCTIONS
2. **Direct service integration** - Not CLI wrapping, for performance
3. **Clean interfaces** - No unnecessary parameters, sensible defaults
4. **Discovery uses LLM** - Unlike simple keyword search
5. **Stateless by design** - Matches pflow's existing patterns
6. **stdio transport** - Compatible with Claude Code
7. **No natural language execution** - Agents use individual tools
8. **Agent mode built-in** - No flags for JSON/repair/trace

**📋 Note on Specifications**: The `final-implementation-spec.md` is the authoritative source. Follow it precisely for tool schemas, response formats, and behavior.

## Success Criteria

Your implementation is complete when:

- ✅ MCP server exposes 13 tools via stdio transport
- ✅ Discovery tools use LLM for intelligent selection
- ✅ Execution returns structured JSON with errors and traces
- ✅ All tools use agent-optimized defaults (no flags needed)
- ✅ Agents can complete full workflow: discover → build → test → save
- ✅ Performance better than CLI spawning
- ✅ Security validation prevents path traversal
- ✅ `make test` passes with comprehensive tests
- ✅ `make check` passes (linting, type checking)
- ✅ `pflow serve mcp` command works

## Common Pitfalls to Avoid

- **DON'T share instances between requests** - Always create fresh WorkflowManager/Registry
- **DON'T expose natural language execution** - Removed per user decision
- **DON'T add parameters for agent mode** - Defaults are built-in
- **DON'T use CLI wrapping** - Direct service integration only
- **DON'T forget workflow_manager in planning nodes** - Required for discovery
- **DON'T trust workflow names** - Always validate for path traversal
- **DON'T skip progress reporting** - Important for long operations
- **DON'T return raw exceptions** - Always format errors for LLM visibility

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent subagents from conflicting.

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Service Integration Analysis**
   - Task: "Analyze WorkflowManager, Registry, and execute_workflow APIs in detail"
   - Task: "Find how CLI commands use these services for patterns to mirror"

2. **Planning Node Integration**
   - Task: "Analyze ComponentBrowsingNode and WorkflowDiscoveryNode implementation"
   - Task: "Find what shared store keys these nodes require"

3. **FastMCP Pattern Verification**
   - Task: "Check if FastMCP is already installed and what version"
   - Task: "Find any existing MCP server patterns in the codebase"

4. **Testing Infrastructure**
   - Task: "Analyze existing MCP client tests for testing patterns"
   - Task: "Find test utilities for mocking services"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_72/implementation/implementation-plan.md`

Include:
1. **File structure** for `src/pflow/mcp_server/`
2. **Tool grouping** into logical classes
3. **Dependency mapping** between tools
4. **Testing strategy** for each tool
5. **Integration approach** with CLI

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_72/implementation/progress-log.md`

```markdown
# Task 72 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### 1. Create Implementation Plan

Deploy subagents to gather context, then create comprehensive plan.

### 2. Set up MCP server structure

Create `src/pflow/mcp_server/` with proper organization.

### 3. Implement Priority 1 tools

Start with the 6 core workflow loop tools.

### 4. Implement Priority 2 tools

Add the 5 supporting tools.

### 5. Add CLI integration

Implement `pflow serve mcp` command.

### 6. Write comprehensive tests

Use test-writer-fixer subagent for quality tests.

### 7. Implement Priority 3 tools

If time permits, add advanced tools.

### 8. Final validation

Test with AGENT_INSTRUCTIONS workflows.

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to implement workflow_execute tool...

Result: What happened
- ✅ What worked: asyncio.to_thread handles sync code perfectly
- ❌ What failed: Forgot to create fresh WorkflowManager
- 💡 Insight: Stateless pattern prevents state pollution

Code that worked:
```python
async def workflow_execute(workflow: str | dict, parameters: dict = None):
    # Fresh instances - critical!
    manager = WorkflowManager()
    ...
```
```

## Handle Discoveries and Deviations

When you discover the plan needs adjustment:

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION FROM PLAN
- Original plan: Use single class for all tools
- Why it failed: Too many tools in one class
- New approach: Group into WorkflowTools, RegistryTools, SettingsTools
- Lesson: Logical grouping improves maintainability
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test what matters"

**What to test**:
- **Tool registration**: All 13 tools discoverable
- **Stateless operation**: Fresh instances per request
- **Error formatting**: Errors visible to LLM
- **Security**: Path traversal prevention
- **Integration**: Full workflow cycles

**Progress Log - Only document testing insights**:
```markdown
## 16:30 - Testing revealed state pollution
Testing concurrent requests showed shared WorkflowManager
caused data leakage. Fixed by ensuring fresh instances.
This is why stateless pattern is mandatory.
```

## What NOT to Do

- **DON'T** implement natural language execution tool
- **DON'T** add parameters for agent mode defaults
- **DON'T** wrap CLI commands - use services directly
- **DON'T** cache or share instances between requests
- **DON'T** expose sensitive data in responses
- **DON'T** skip the planning nodes for discovery
- **DON'T** forget progress reporting for long operations
- **DON'T** return raw exceptions - format for LLM visibility

## Getting Started

1. Install FastMCP: `pip install "mcp[cli]>=1.13.1"`
2. Read the epistemic manifesto to set your mindset
3. Create your progress log file
4. Deploy subagents to gather context
5. Create implementation plan
6. Start with Phase 1: Core tools

Test frequently with: `pytest tests/test_mcp_server/ -v`

## Final Notes

- The research files contain complete FastMCP patterns - use them!
- Planning nodes (WorkflowDiscoveryNode, ComponentBrowsingNode) already exist - reuse them
- Services (WorkflowManager, Registry, execute_workflow) are ready - integrate directly
- Security is critical - validate all paths and sanitize sensitive data
- Performance matters - this should be faster than CLI spawning

## Remember

You're implementing a critical interface that enables AI agents to use pflow programmatically. The MCP server unlocks new integrations with Cursor, Continue, and other AI tools that need structured access. The design in the specifications is based on extensive research of how agents actually use pflow.

The key insight: Agents follow a strict pattern (discover → build → test → save) that the MCP server must support with clean interfaces and sensible defaults. No complexity, just expose what works.

Think hard, but trust the research. When faced with ambiguity, check the specifications and research files. The answers are there.

Good luck! This MCP server will significantly expand pflow's reach by enabling programmatic access for AI agents beyond just CLI usage.