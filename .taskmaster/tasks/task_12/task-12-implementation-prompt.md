# Task 12: Implement General LLM Node - Agent Instructions

## The Problem You're Solving

Currently, pflow has no way to incorporate LLM capabilities into workflows, severely limiting the types of workflows that can be created. Without an LLM node, the planner (Task 17) can only generate basic file manipulation workflows that don't showcase pflow's true value proposition. Users need a general-purpose LLM node that prevents proliferation of prompt-specific nodes.

## Your Mission

Implement a general-purpose LLM node that wraps Simon Willison's `llm` library, providing text processing capabilities for pflow workflows. This is the ONLY LLM node in pflow - a smart exception to the simple nodes philosophy.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Understand the Node Base Class
**File**: `pocketflow/__init__.py`

**Purpose**: Understand the Node base class that LLMNode will inherit from. This file contains:
- The complete PocketFlow framework implementation
- Node lifecycle methods (prep, exec, post, exec_fallback)
- How retry mechanism works internally
- Shared store patterns and best practices

**Why read second**: You MUST understand the Node base class before implementing LLMNode. This is the foundation your implementation builds upon.

### 3. THIRD: Task Overview
**File**: `.taskmaster/tasks/task_12/task-12.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read third**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 4. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_12/starting-context/`

**Files to read (in this order):**
1. `task-12-handover-context.md` - Implementation guidance with corrected usage tracking implementation
2. `task-12-spec.md` - The formal specification (FOLLOW THIS PRECISELY - contains all 22 test criteria)

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-12-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY. The handover document provides critical implementation patterns and corrected code examples.

## 🔍 Required Documentation Research with Subagents

**CRITICAL**: If ANYTHING about the llm library usage is unclear, you MUST deploy subagents to research:

### 1. Official LLM Library Documentation
Deploy a subagent to research the official documentation:
```
Task: "Research the Python API documentation at https://llm.datasette.io/en/stable/python-api.html
Focus on:
- How to use llm.get_model()
- The prompt() method and its parameters
- How response.text() works (lazy evaluation)
- The usage() method return type and structure
- Exception types like UnknownModelError and NeedsKeyException
Provide concrete code examples from the documentation."
```

### 2. Reference Implementation
Deploy a subagent to examine the llm library source:
```
Task: "Examine the llm-main/ directory in our repository to understand:
- How the Response class is structured
- What fields the Usage object contains
- How the prompt() method handles parameters
- Exception class definitions
This is reference code only - we use pip-installed llm, not this local copy."
```

### 3. PocketFlow Documentation
If unclear about Node implementation patterns:
```
Task: "Research pocketflow/docs/ to understand:
- Node lifecycle and execution patterns
- How shared store works
- Best practices for node implementation
- Examples of existing nodes"
```

**Remember**: It's better to deploy a subagent to clarify than to make assumptions!

## What You're Building

A general-purpose LLM node that enables text processing in workflows:

```python
# User runs:
pflow llm --prompt="Summarize this text"

# Or in a workflow:
read-file --path=report.txt >> llm --prompt="Summarize: $content"
```

The node:
- Takes a text prompt as input
- Sends it to an LLM (default: claude-sonnet-4-20250514)
- Returns the response and usage metrics
- Supports temperature control, system prompts, and token limits
- Tracks token usage for cost analysis (critical for demonstrating pflow's efficiency)

## Key Outcomes You Must Achieve

### Core Implementation
- LLMNode class in `src/pflow/nodes/llm/llm.py`
- Must have `name = "llm"` class attribute for registry discovery
- Implement PocketFlow pattern: prep(), exec(), post(), exec_fallback()
- Support parameter fallback pattern (shared store first, then params)
- Force response evaluation with response.text() (responses are lazy!)

### Usage Tracking
- Extract usage data with response.usage() (may return None)
- Store in shared["llm_usage"] with correct field names:
  - input_tokens, output_tokens, total_tokens
  - cache_creation_input_tokens, cache_read_input_tokens
- Empty dict {} when usage unavailable (not error)

### Error Handling
- Transform UnknownModelError → helpful message about 'llm models'
- Transform NeedsKeyException → helpful message about 'llm keys set'
- General failures → include retry count and model info
- All error handling in exec_fallback() ONLY

## Implementation Strategy

### Phase 1: Package Setup (30 minutes)
1. Create directory structure: `src/pflow/nodes/llm/`
2. Create `llm.py` with LLMNode class
3. Create `__init__.py` with proper exports
4. Update `pyproject.toml` to add `llm>=0.19.0` dependency

### Phase 2: Core Implementation (1.5 hours)
1. Implement prep() method with parameter fallback pattern
2. Implement exec() method - NO try/except blocks!
3. Implement post() method with usage tracking
4. Implement exec_fallback() with error transformations

### Phase 3: Testing (2 hours)
1. Create test file: `tests/test_nodes/test_llm.py`
2. Implement all 22 test criteria from spec
3. Use mocks for unit tests, VCR for integration tests
4. Ensure 100% coverage of critical paths
5. **MANDATORY**: Deploy test-writer-fixer subagent for verification:
   ```
   Task: "Review and verify all tests in tests/test_nodes/test_llm.py
   - Ensure all 22 test criteria from the spec are covered
   - Verify tests actually test the functionality (not just mocked returns)
   - Check for edge cases and error conditions
   - Ensure usage tracking tests verify correct field names
   - Fix any tests that are incomplete or incorrect
   - Add missing test cases if any criteria are not covered"
   ```

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use subagents to work on debugging, testing and writing tests.
> CRITICAL: You MUST use the test-writer-fixer subagent to review and verify ALL tests before considering the task complete!

## Critical Technical Details

### The `name` Attribute
```python
class LLMNode(Node):
    name = "llm"  # CRITICAL: Required for registry discovery
```
Without this, the registry won't find your node!

### Parameter Fallback Pattern
```python
def prep(self, shared: Dict[str, Any]) -> Dict[str, Any]:
    # Check shared first, then params
    prompt = shared.get("prompt") or self.params.get("prompt")
    system = shared.get("system") or self.params.get("system")
```

### Temperature Clamping
```python
temperature = self.params.get("temperature", 0.7)
temperature = max(0.0, min(2.0, temperature))  # ALWAYS clamp!
```

### Usage Extraction (Fixed Pattern)
```python
def exec(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
    # ... prompt execution ...
    text = response.text()
    usage_obj = response.usage()  # May return None

    return {
        "response": text,
        "usage": usage_obj,  # Pass raw object or None
        "model": prep_res["model"]
    }

def post(self, shared: Dict[str, Any], prep_res: Dict[str, Any],
         exec_res: Dict[str, Any]) -> str:
    shared["response"] = exec_res["response"]

    # Store usage metrics matching spec structure exactly
    usage_obj = exec_res.get("usage")
    if usage_obj:
        # Extract cache metrics from details if available
        details = getattr(usage_obj, 'details', {}) or {}
        cache_creation = details.get('cache_creation_input_tokens', 0)
        cache_read = details.get('cache_read_input_tokens', 0)

        shared["llm_usage"] = {
            "model": exec_res.get("model", "unknown"),
            "input_tokens": usage_obj.input,
            "output_tokens": usage_obj.output,
            "total_tokens": usage_obj.input + usage_obj.output,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read
        }
    else:
        # Empty dict per spec when usage unavailable
        shared["llm_usage"] = {}

    return "default"
```

### NO Try/Except in exec()
```python
def exec(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
    # NO try/except! Let exceptions bubble up for retry mechanism
    model = llm.get_model(prep_res["model"])
    response = model.prompt(prep_res["prompt"], **kwargs)
    # ...
```

## Critical Warnings from Experience

### Usage Object Attribute Access
The usage object from `response.usage()` may be None. NEVER access attributes directly without checking:
```python
# ❌ WRONG - Will crash if usage_obj is None
usage = {
    "input": usage_obj.input if usage_obj else 0  # Crashes!
}

# ✅ CORRECT - Check first, then access
if usage_obj:
    usage = {"input": usage_obj.input, ...}
else:
    usage = {}
```

### Template Variables Are NOT Your Concern
When a workflow has `{"prompt": "Summarize: $content"}`, the runtime resolves `$content` BEFORE your node executes. You just receive the resolved text. Don't implement any template handling!

### The llm Library Location
Use the pip-installed `llm` package (`import llm`). The `llm-main/` directory in the repo is for reference only - do NOT import from it.

## Key Decisions Already Made

1. **Default model**: claude-sonnet-4-20250514 (not "latest" or "newest")
2. **Default temperature**: 0.7 (good for general use)
3. **Usage tracking structure**: Must match spec exactly (input_tokens, output_tokens, etc.)
4. **Empty dict for missing usage**: Not None, not error - empty dict {}
5. **No advanced features**: No structured output, attachments, or tools for MVP
6. **This is the ONLY LLM node**: No prompt-specific nodes allowed

**📋 Note on Specifications**: The specification file (`task-12-spec.md`) contains all 22 test criteria that MUST pass. Follow it precisely - do not deviate from specified behavior unless you discover a critical issue (in which case, document the deviation clearly or STOP and ask the user for clarification).

## Success Criteria

Your implementation is complete when:

- ✅ All 22 test criteria from the spec pass
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ `pflow llm --prompt="Hello"` works correctly
- ✅ Registry auto-discovers the node (via `name = "llm"`)
- ✅ Usage tracking works with correct field names
- ✅ Error messages are helpful and guide to solutions
- ✅ Temperature clamping works correctly
- ✅ Empty response is handled (not treated as error)

## Common Pitfalls to Avoid

- **DON'T** forget the `name = "llm"` class attribute - registry won't find it
- **DON'T** add try/except in exec() - breaks retry mechanism
- **DON'T** access usage object attributes without checking for None first
- **DON'T** implement template variable resolution - runtime handles it
- **DON'T** use wrong field names for usage (must be input_tokens, not input)
- **DON'T** treat empty response as error - store empty string
- **DON'T** forget to clamp temperature to [0.0, 2.0]
- **DON'T** pass None values in kwargs - check first
- **DON'T** implement structured output or other advanced features

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

1. **Codebase Structure Analysis**
   - Task: "Analyze the structure of src/pflow/nodes/ and identify the pattern for adding new node types. Look at existing nodes like read_file.py and write_file.py to understand the implementation pattern."
   - Task: "Find how the LLM library is used elsewhere in the codebase, particularly in the planning module"

2. **LLM Library Research** (CRITICAL - Deploy if anything unclear)
   - Task: "Research https://llm.datasette.io/en/stable/python-api.html for the exact API of llm.get_model(), response.text(), and response.usage(). Document the exact return types and exception handling."
   - Task: "Examine llm-main/llm/models.py and llm-main/llm/cli.py to understand how UnknownModelError and NeedsKeyException are raised"
   - Task: "Research pocketflow/docs/core_abstraction/node.md to understand Node lifecycle methods and best practices"

3. **Integration Points Discovery**
   - Task: "Analyze how nodes are registered in the registry system - look for how the 'name' attribute is used"
   - Task: "Check how parameters are passed to nodes via set_params() method"

4. **Testing Pattern Analysis**
   - Task: "Examine tests/test_nodes/test_file.py to understand testing patterns for nodes"
   - Task: "Find examples of mocking external dependencies in the test suite"
   - Task: "Research VCR usage in the test suite for recording API responses"

5. **Documentation Requirements**
   - Task: "Check docs/reference/node-reference.md to understand how to document new nodes"
   - Task: "Find the enhanced Interface docstring format in existing nodes"
```

**REMEMBER**: When in doubt about llm library behavior, ALWAYS deploy a subagent to research the official docs or examine llm-main/ reference code!

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_12/implementation/implementation-plan.md`

Include all sections from the template, focusing on:
- How to structure the LLMNode class
- Test strategy for all 22 criteria
- Integration with registry system
- Error handling approach

### Subagent Task Scoping Guidelines

**✅ GOOD Subagent Tasks:**
```markdown
- "Implement the prep() method in llm.py following the parameter fallback pattern for prompt and system parameters"
- "Write unit tests for temperature clamping in test_llm.py - test values below 0, above 2, and at boundaries"
- "Create integration test using VCR for successful LLM call with usage tracking"
```

**❌ BAD Subagent Tasks:**
```markdown
- "Implement the entire LLM node" (too broad)
- "Fix any issues you find" (too vague)
- "Write all the tests" (multiple agents will conflict)
```

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_12/implementation/progress-log.md`

```markdown
# Task 12 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### 1. Create Implementation Plan (SECOND!)
- Deploy subagents to gather context
- Write comprehensive plan with task assignments
- Identify risks and dependencies

### 2. Create Package Structure
- Create `src/pflow/nodes/llm/` directory
- Create empty `llm.py` and `__init__.py` files

### 3. Implement LLMNode Class
- Add class with `name = "llm"` attribute
- Implement prep() with parameter fallback
- Implement exec() without try/except
- Implement post() with usage tracking
- Implement exec_fallback() with error messages

### 4. Write Tests
- Create `tests/test_nodes/test_llm.py`
- Implement all 22 test criteria
- Use mocks for unit tests
- Add VCR cassettes for integration tests

### 5. Update Dependencies
- Add `llm>=0.19.0` to pyproject.toml

### 6. Manual Testing
- Test `pflow llm --prompt="Hello"`
- Test with stdin data
- Verify registry discovery

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - Working on usage extraction
Attempting to extract usage data from response object...

Result: Discovered usage() can return None
- ✅ What worked: Checking for None before accessing attributes
- ❌ What failed: Direct attribute access crashed when None
- 💡 Insight: Always use defensive programming with external APIs

Code that worked:
```python
usage_obj = response.usage()
if usage_obj:
    # Safe to access attributes
else:
    # Handle None case
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
- Original plan: Store usage as simple dict
- Why it failed: Spec requires specific field names
- New approach: Map from usage object fields to spec fields
- Lesson: Always verify field names against spec
```

## Test Creation Guidelines

**Core Principle**: "Test what matters"

**Focus on quality over quantity**:
- Test public interfaces and critical paths
- Test edge cases where bugs typically hide
- Create integration tests when components interact
- Document only interesting test discoveries in your progress log

**What to test**:
- **Critical paths**: Prompt extraction, response storage, usage tracking
- **Public APIs**: The run() method and its behavior
- **Error handling**: Missing prompt, unknown model, missing API key
- **Integration points**: Registry discovery, parameter passing

**What NOT to test**:
- Simple getters/setters
- Configuration loading
- Framework code (PocketFlow base class)
- Internal helper functions (unless complex)

**Progress Log - Only document testing insights**:
```markdown
## 14:50 - Testing revealed temperature edge case
While testing temperature clamping, discovered that
float precision can cause 2.0000001 to pass through.
Added explicit max() min() clamping pattern.
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** forget the `name = "llm"` class attribute
- **DON'T** implement structured output, attachments, or tools
- **DON'T** create multiple LLM nodes for different prompts
- **DON'T** add custom retry logic - base class handles it
- **DON'T** use try/except in exec() method
- **DON'T** access usage attributes without None check
- **DON'T** use wrong usage field names (must match spec exactly)
- **DON'T** skip any of the 22 test criteria

## Getting Started

1. Read the epistemic manifesto to understand the approach
2. Read task overview and context files
3. Create your progress log
4. Deploy subagents to gather context
5. Create implementation plan
6. Start with package structure
7. Run tests frequently: `pytest tests/test_nodes/test_llm.py -v`

## Final Notes

- The handover document has the CORRECTED usage implementation - use it!
- All 22 test criteria from the spec MUST pass
- This node enables Task 17 (planner) to create meaningful workflows
- Usage tracking is critical for demonstrating pflow's efficiency
- The default model must be claude-sonnet-4-20250514 exactly

## Remember

You're implementing the ONLY LLM node in pflow - a critical piece of infrastructure that prevents node proliferation while enabling powerful text processing workflows. The spec has been carefully reviewed and corrected. Trust it, implement it precisely, and document your discoveries.

This node is what makes pflow workflows actually useful. Without it, we're limited to basic file operations. With it, we can create intelligent, cost-effective workflows that showcase pflow's "Plan Once, Run Forever" philosophy.

Good luck! Your implementation will unlock the full potential of pflow workflows.
