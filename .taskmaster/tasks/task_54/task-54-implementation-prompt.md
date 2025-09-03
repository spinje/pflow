# Task 54: Implement HTTP Node - Agent Instructions

## The Problem You're Solving

pflow currently lacks native HTTP request capabilities, forcing users to rely on awkward shell+curl combinations or install MCP servers for basic HTTP operations. This makes common API integrations, webhook notifications, and data fetching workflows unnecessarily complex. Research shows 60% of HTTP operations are simple GET/POST with JSON, yet users have no straightforward way to perform these.

## Your Mission

Implement a native HTTP node for pflow that enables web requests with automatic JSON handling, authentication support, and proper error handling. This will be pflow's first node to directly use a Python library (requests) for external service interaction, setting a precedent for future direct-API nodes.

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
**File**: `.taskmaster/tasks/task_54/task-54.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_54/starting-context/`

**Files to read (in this order):**
1. `task-54-spec.md` - The specification (FOLLOW THIS PRECISELY - it is the source of truth)
2. `http-node-implementation-guide.md` - Complete implementation guide with working code examples
3. `task-54-handover.md` - Critical tacit knowledge about hidden patterns and gotchas

**Instructions**: Read EACH file listed above in order. After reading each file, pause to understand:
- The patterns that MUST be followed (PocketFlow retry, parameter fallback)
- The error handling distinction (GitHub pattern vs File pattern - use GitHub)
- The action pattern (only "default" and "error" exist)
- Why certain design decisions were made

**IMPORTANT**: The specification file (`task-54-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

An HTTP node that enables pflow workflows to make web requests. The node will:
- Support all standard HTTP methods (GET, POST, PUT, DELETE, PATCH)
- Auto-detect method based on body presence (POST with body, GET without)
- Handle both JSON and plain text responses
- Support Bearer token and API key authentication
- Provide actionable error messages with suggestions
- Follow pflow's established patterns exactly

Example usage:
```python
# Simple GET request
shared = {"url": "https://api.example.com/data"}
# Result: GET request, returns JSON data

# POST with JSON body and authentication
shared = {
    "url": "https://api.example.com/webhook",
    "body": {"message": "test"}
}
params = {"auth_token": "secret123"}
# Result: POST with Authorization: Bearer secret123
```

## Key Outcomes You Must Achieve

### Core Implementation
- HttpNode class in `src/pflow/nodes/http/` that inherits from `Node` (NOT BaseNode)
- Follows PocketFlow retry pattern exactly (NO try/except in exec method)
- Implements parameter fallback pattern for all inputs
- Returns only "default" or "error" actions (no custom actions)

### Critical Patterns
- NO exception handling in exec() - let ALL exceptions bubble up for retry mechanism
- Raise ValueError from exec_fallback() - follow GitHub/LLM pattern, NOT file pattern
- HTTP 4xx/5xx responses are valid responses handled in post(), not exceptions
- Only network failures (timeout, connection) are exceptions handled in exec_fallback()

### Testing & Integration
- Comprehensive tests mocking at requests library level (not subprocess)
- Verify retry mechanism actually retries (mock called multiple times)
- Natural language integration with proper Interface documentation
- Node appears in registry and works with planner

## Implementation Strategy

### Phase 1: Setup and Core Structure (30 minutes)
1. Add `requests>=2.32.0` to `pyproject.toml` dependencies
2. Create `src/pflow/nodes/http/` directory structure
3. Create `__init__.py` with proper HttpNode export
4. Create `http.py` with HttpNode class skeleton

### Phase 2: Core Implementation (2 hours)
1. Implement `__init__` with max_retries=3, wait=1.0
2. Implement `prep()` with parameter fallback pattern
3. Implement `exec()` with NO try/except - requests.request() call only
4. Implement `exec_fallback()` raising ValueError with actionable messages
5. Implement `post()` returning "default" for 2xx, "error" for others

### Phase 3: Features and Edge Cases (1 hour)
1. Auto-detect method (POST with body, GET without)
2. JSON serialization for dict bodies
3. JSON parsing for responses based on Content-Type
4. Bearer token and API key authentication
5. Query parameters support via params dict
6. Proper timeout handling (default 30 seconds)

### Phase 4: Testing (2 hours)
1. Create test file structure in `tests/test_nodes/test_http/`
2. Test required URL validation
3. Test method auto-detection
4. Test successful requests with mocked responses
5. Test retry mechanism (verify multiple calls)
6. Test error transformation in exec_fallback
7. Test action mapping in post()

### Phase 5: Integration and Documentation (1 hour)
1. Verify node appears in registry
2. Test with `pflow registry list`
3. Update natural language mappings in docstring
4. Run full test suite
5. Final verification with `make test` and `make check`

### Use Subagents effectively

Use subagents to maximize efficiency and avoid context window limitations.

> Always use @agent-pflow-codebase-searcher to gather information, context, do research and verifying assumptions. This is important!
> Always use the @agent-test-writer-fixer subagent for writing tests, fixing test failures, and debugging test issues.
> Always give subagents small isolated tasks, never more than fixes for one file at a time.
> Always deploy subagents in parallel, never sequentially. This means using ONE function call block to deploy all subagents simultaneously.

Implementation should be done by yourself! Write tests using the @agent-test-writer-fixer subagent AFTER implementation is complete.

## Critical Technical Details

### The PocketFlow Retry Pattern (MUST FOLLOW EXACTLY)
```python
def exec(self, prep_res: dict) -> dict:
    # ⚠️ NO try/except here! Let ALL exceptions bubble up!
    response = requests.request(
        method=prep_res["method"],
        url=prep_res["url"],
        # ... other params
    )

    # Only return SUCCESS data
    return {
        "response": response.json() if "json" in response.headers.get("content-type", "") else response.text,
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "duration": response.elapsed.total_seconds()
    }
```

### Error Pattern Discovery (GitHub vs File)
There are TWO patterns in the codebase:
- File nodes return error strings from exec_fallback (WRONG for HTTP)
- GitHub/LLM nodes raise ValueError from exec_fallback (CORRECT for HTTP)

You MUST use the GitHub pattern:
```python
def exec_fallback(self, prep_res: dict, exc: Exception) -> None:
    # MUST raise ValueError, not return string
    if isinstance(exc, requests.Timeout):
        raise ValueError(f"Request timed out after {prep_res['timeout']} seconds. Try --timeout=60")
    # ... more error handling
```

### HTTP Errors vs Network Errors
Critical distinction:
- **HTTP 4xx/5xx**: Valid responses with status_code - handled in post()
- **Network errors**: Exceptions (timeout, connection) - handled in exec_fallback()

Don't use `response.raise_for_status()` - let HTTP errors be normal responses!

## Critical Warnings from Experience

### The NonRetriableError Bug
NonRetriableError still triggers retries despite its name. This is a known issue. Don't try to fix it or use it.

### Environment Variable Expansion Confusion
The research findings showed code with `os.path.expandvars()` but this is WRONG. Only the MCP node does this. Don't implement environment variable expansion for auth tokens.

### Action Names Were Changed
The task document originally suggested "success/client_error/server_error" actions. These don't exist in pflow. Only "default" and "error" exist. The spec was corrected to reflect this.

### Mock response.elapsed Properly
In tests, mock `response.elapsed.total_seconds()` or you'll get AttributeError:
```python
mock_response.elapsed.total_seconds.return_value = 1.5
```

## Key Decisions Already Made

1. **Use requests library** - Not urllib, for better error messages
2. **30-second timeout default** - Industry standard from research
3. **Separate auth_token/api_key params** - Clearer than unified auth string
4. **Query params as dict** - Added despite no codebase precedent (research justified it)
5. **Follow GitHub error pattern** - Raise ValueError, don't return strings
6. **No environment variable expansion** - Only MCP node does this
7. **Only default/error actions** - No custom actions like client_error

**📋 Note on Specifications**: The specification file (`task-54-spec.md`) is the authoritative source. Follow it precisely - do not deviate from specified behavior, test criteria, or implementation requirements unless you discover a critical issue (in which case, document the deviation clearly or STOP and ask the user for clarification).

## Success Criteria

Your implementation is complete when:

✅ HttpNode properly inherits from `Node` with correct retry settings
✅ All 21 test criteria from the spec pass
✅ Parameter fallback pattern works for all inputs
✅ NO try/except in exec() method
✅ exec_fallback() raises ValueError (not returns string)
✅ Only "default" and "error" actions returned
✅ Retry mechanism verified to actually retry (tests prove it)
✅ `make test` passes with no regressions
✅ `make check` passes (linting, type checking)
✅ Node appears in registry and can be used in workflows

## Common Pitfalls to Avoid

1. **DON'T catch exceptions in exec()** - This breaks the retry mechanism
2. **DON'T return error strings from exec_fallback()** - Raise ValueError like GitHub nodes
3. **DON'T create custom actions** - Only "default" and "error" exist
4. **DON'T copy file node patterns** - They use the wrong error handling
5. **DON'T add environment variable expansion** - Not needed
6. **DON'T forget to mock response.elapsed** in tests
7. **DON'T use response.raise_for_status()** - HTTP errors are valid responses
8. **DON'T overthink** - The implementation guide has working code

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

1. **Existing Node Pattern Analysis**
   - Task: "Analyze how LLMNode and GitHubNode implement the PocketFlow retry pattern, focusing on their exec() and exec_fallback() methods"
   - Task: "Examine the parameter fallback pattern in file nodes and GitHub nodes, extracting the exact pattern"

2. **Registry Integration Discovery**
   - Task: "Find how nodes are registered in src/pflow/registry/ and what makes them discoverable"
   - Task: "Analyze the Interface documentation format requirements for natural language integration"

3. **Testing Pattern Analysis**
   - Task: "Examine how GitHub nodes mock subprocess calls and how this translates to mocking requests"
   - Task: "Find test patterns that verify retry mechanism actually retries"

4. **Error Handling Pattern Verification**
   - Task: "Compare error handling in file nodes vs GitHub nodes to understand the two patterns"
   - Task: "Verify how HTTP status codes should be handled vs network exceptions"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_54/implementation/implementation-plan.md`

Your plan should include:

1. **Pattern verification results** - Confirm critical patterns from research
2. **File creation/modification list** - Every file with no overlaps
3. **Dependency mapping** - What must exist before what
4. **Risk identification** - Potential issues and solutions
5. **Testing strategy** - How to verify each component

### Implementation Plan Template for HTTP Node

```markdown
# Task 54 HTTP Node Implementation Plan

## Verified Patterns

### PocketFlow Retry Pattern
- Confirmed: No try/except in exec()
- Confirmed: exec_fallback() raises ValueError
- Location: [specific files verified]

### Parameter Fallback Pattern
- Pattern: shared.get("key") or self.params.get("key")
- Used in: [list of nodes verified]

### Action Pattern
- Only "default" and "error" exist
- No custom actions found in codebase

## Implementation Steps

### Phase 1: Infrastructure Setup (Parallel Possible)
1. **Update Dependencies** (Independent)
   - File: pyproject.toml
   - Add: requests>=2.32.0

2. **Create Package Structure** (Independent)
   - Files: src/pflow/nodes/http/__init__.py, http.py
   - No conflicts with existing code

### Phase 2: Core Implementation (Sequential)
1. **Implement HttpNode Class**
   - File: src/pflow/nodes/http/http.py
   - Dependencies: Package structure must exist
   - Critical: Follow PocketFlow retry pattern exactly

### Phase 3: Testing (Use test-writer-fixer subagent)
1. **Create Test Structure**
   - Files: tests/test_nodes/test_http/test_http.py
   - Use test-writer-fixer for all test creation

### Phase 4: Integration Testing
1. **Verify Registry Integration**
   - Test node appears in registry
   - Test natural language planning

### Phase 5: Final Test Review
Deploy test-writer-fixer to review all tests and ensure they catch real bugs

## Risk Mitigation

| Risk | Mitigation Strategy |
|------|-------------------|
| Wrong error pattern used | Verify GitHub pattern, not file pattern |
| Retry mechanism broken | Test with mock proving multiple calls |
| HTTP errors as exceptions | Don't use raise_for_status() |
```

### Subagent Task Scoping Guidelines

**✅ GOOD Subagent Tasks for HTTP Node:**
```markdown
- "pflow-codebase-searcher: Verify the exact parameter fallback pattern in LLMNode and how it handles optional parameters"
- "test-writer-fixer: Write comprehensive tests for HTTP retry mechanism that verify requests is called multiple times on failure"
- "pflow-codebase-searcher: Find how GitHub nodes transform subprocess errors to user-friendly messages"
```

**❌ BAD Subagent Tasks:**
```markdown
- "Implement the entire HTTP node" (too broad)
- "Fix all test failures" (too vague)
- "Update multiple files" (conflict risk)
```

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_54/implementation/progress-log.md`

```markdown
# Task 54 HTTP Node Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. **Create implementation plan** following the template above
2. **Add requests dependency** to pyproject.toml
3. **Create package structure** in src/pflow/nodes/http/
4. **Implement HttpNode class** following the exact patterns
5. **Create comprehensive tests** using test-writer-fixer subagent
6. **Verify registry integration** and natural language support
7. **Run full test suite** and fix any issues

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - Implementing exec method
Attempting to implement exec without try/except...

Result: Works correctly
- ✅ What worked: Exceptions bubble up for retry
- ❌ What failed: Initially added try/except out of habit
- 💡 Insight: The retry mechanism depends on exceptions bubbling

Code that worked:
```python
def exec(self, prep_res: dict) -> dict:
    response = requests.request(...)  # No try/except!
    return {"response": ..., "status_code": ...}
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
## [Time] - DEVIATION FROM PLAN
- Original plan: Return different actions for status codes
- Why it failed: Only default/error actions exist
- New approach: Return error for all non-2xx
- Lesson: Always verify action names exist
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test what matters"

**Critical tests for HTTP Node**:
- **Retry verification**: Mock must be called multiple times to prove retries work
- **Error transformation**: Each exception type produces correct message
- **Action mapping**: Status codes map to correct actions
- **Parameter fallback**: Both shared and params sources work
- **Authentication**: Headers are set correctly

**Progress Log - Only document testing insights**:
```markdown
## 15:30 - Testing revealed retry issue
Mock wasn't properly set up to fail then succeed.
Fixed by using side_effect with list of responses.
This proves retry mechanism actually works.
```

## What NOT to Do

- **DON'T** catch exceptions in exec() - breaks retry mechanism completely
- **DON'T** return strings from exec_fallback() - must raise ValueError
- **DON'T** create actions like "client_error" - they don't exist
- **DON'T** copy file node error patterns - they're wrong for this
- **DON'T** implement environment variable expansion - not needed
- **DON'T** use response.raise_for_status() - HTTP errors aren't exceptions
- **DON'T** forget to test that retries actually happen
- **DON'T** skip reading the handover memo - it has critical insights

## Getting Started

1. Read all required files in order (epistemic manifesto first!)
2. Create your progress log immediately
3. Deploy subagents to verify patterns before coding
4. Follow the implementation guide's working code
5. Test frequently with `pytest tests/test_nodes/test_http/ -v`
6. Use test-writer-fixer for all test creation

## Final Notes

- The implementation guide has COMPLETE WORKING CODE - use it!
- The distinction between HTTP errors and network errors is CRITICAL
- You're setting precedent as the first direct Python library node
- The handover memo explains WHY certain decisions were made
- When uncertain about patterns, check GitHub nodes, not file nodes

## Remember

You're implementing pflow's first node that directly calls an external service using a Python library. This is a foundational component that will enable real API integration without shell hackery. The patterns have been thoroughly researched and verified. Trust the implementation guide, but verify against the specification.

The research showed this solves a real pain point - users desperately need clean HTTP capabilities. Your implementation will unlock webhook notifications, API monitoring, and data fetching workflows that are currently impossible or extremely fragile.

Think deeply, implement carefully, and test thoroughly. This node will be used extensively and must be rock solid!