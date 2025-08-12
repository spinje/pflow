# Task 27: Planner Debugging Capabilities - Agent Instructions

## The Problem You're Solving

The Natural Language Planner is currently failing/hanging with no visibility into where it fails (which node), why it fails (timeout, bad LLM response, validation error), or what the LLM sees (prompts) and returns (responses). Developers and AI agents cannot debug or improve the planner without this visibility, and raw LLM output dumped to terminal is unreadable and unsearchable.

## Your Mission

Implement comprehensive debugging capabilities for the planner that provide real-time progress visibility and detailed trace files for debugging, without modifying existing node implementations. Enable developers to see exactly what's happening during planner execution and capture all LLM interactions for prompt improvement.

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
**File**: `.taskmaster/tasks/task_27/task-27.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the PRD with the two-mode debugging system design and all technical specifications.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read Handoff Document
**Files to read:** `.taskmaster/tasks/task_27/task_27_handover.md` - Critical tacit knowledge from design phase

**Purpose**: These contain hard-won insights about why the planner hangs, what we discovered during investigation

### 4. Read ALL Starting Context Files
**Directory**: `.taskmaster/tasks/task_27/starting-context/`

**Files to read (in this order):**
1. `task-27-spec.md` - The specification (FOLLOW THIS PRECISELY - source of truth for requirements)
2. `main-agent-implementation-guide.md` - Core implementation guide with critical code
3. `agent-responsibilities.md` - Who does what and execution timeline
4. `integration-overview.md` - Architecture and component interaction
5. `code-implementer-tasks.md` - Isolated utility functions (can be assigned to multiple instances of code-implementer subagent, one subagent = one task)
6. `test-writer-fixer-plan.md` - Comprehensive test plan (for test-writer-fixer subagent)

**Instructions**: Read EACH file listed above in order. The specification (`task-27-spec.md`) contains all requirements and test criteria that MUST be met. The implementation guides contain working code that has been verified against the codebase. After reading each file, pause to understand how it relates to the others.

**IMPORTANT**: The specification file (`task-27-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

> Do NOT outsource reading any of these files to a subagent. You are the expert (main agent) and you need to understand the codebase and the requirements.

## What You're Building

A two-mode debugging system for the planner:

**Mode 1: Progress Indicators (Always On)**
```
🔍 Discovery... ✓ 2.1s
📦 Browsing... ✓ 1.8s
🤖 Generating... ✓ 3.2s
```
Clean, minimal progress in terminal showing which nodes are executing.

**Mode 2: Trace Files (On Failure or --trace)**
```json
{
  "execution_id": "uuid",
  "user_input": "analyze data.csv",
  "llm_calls": [
    {
      "node": "WorkflowDiscoveryNode",
      "prompt": "[full prompt for debugging]",
      "response": {...}
    }
  ]
}
```
Complete debugging data in JSON format, automatically saved on failure.

## Key Outcomes You Must Achieve

### Core Infrastructure
- DebugWrapper class that wraps all 9 planner nodes without modifying them
- TraceCollector class that accumulates execution data
- PlannerProgress class that displays progress indicators
- All in `src/pflow/planning/debug.py`

### Integration
- Modified `create_planner_flow()` to wrap nodes when debugging enabled
- New CLI flags: `--trace` and `--planner-timeout`
- Timeout detection (NOT interruption - Python limitation)
- Automatic trace saving on failure

### Testing & Documentation
- All 28 test criteria from spec passing
- Unit tests for debug module
- Integration tests with real planner
- CLI tests for new flags

## Implementation Strategy

### Phase 1: Core Debug Infrastructure (3-4 hours)
1. Create `src/pflow/planning/debug.py` with DebugWrapper, TraceCollector, PlannerProgress
2. Implement critical attribute delegation pattern in DebugWrapper
3. Set up LLM interception via monkey-patching
4. Implement trace file saving to ~/.pflow/debug/

### Phase 2: Utility Functions (1 hour - parallel with Phase 1)
Deploy code-implementer subagent for isolated utilities:
- `save_trace_to_file()` - JSON file saving with error handling
- `format_progress_message()` - Progress formatting with emojis
- `create_llm_interceptor()` - Helper for LLM call interception

### Phase 3: Flow Integration (1 hour)
1. Modify `src/pflow/planning/flow.py` to create wrapped nodes
2. Implement `create_planner_flow_with_debug()` function
3. Wire up debugging infrastructure

### Phase 4: CLI Integration (1 hour)
1. Add `--trace` and `--planner-timeout` flags to CLI
2. Implement timeout detection with threading.Timer
3. Wire up automatic trace saving on failure

### Phase 5: Testing (2-3 hours)
Deploy test-writer-fixer subagent for comprehensive testing:
- Unit tests for all debug components
- Integration tests with real planner
- CLI flag tests
- Edge case coverage

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### DebugWrapper Attribute Delegation (MOST CRITICAL)
The wrapper MUST preserve all node attributes that Flow expects:
```python
class DebugWrapper:
    def __init__(self, node, trace, progress):
        self._wrapped = node
        self.successors = node.successors  # CRITICAL: Copy Flow attributes
        self.params = getattr(node, 'params', {})

    def __getattr__(self, name):
        """CRITICAL: Delegate ALL unknown attributes"""
        return getattr(self._wrapped, name)
```
If this delegation fails, the entire planner breaks because Flow can't access node attributes.

### LLM Interception Pattern
Monkey-patch at the model level after `llm.get_model()`:
```python
if 'model_name' in prep_res:  # Node uses LLM
    original = llm.get_model
    llm.get_model = interceptor
    try:
        result = node.exec(prep_res)
    finally:
        llm.get_model = original  # ALWAYS restore
```

### Timeout Detection (NOT Interruption)
Python threads cannot be interrupted. We can only detect timeout after completion:
```python
timer = threading.Timer(timeout, lambda: timed_out.set())
timer.start()
flow.run(shared)  # Blocking call
if timed_out.is_set():  # Check AFTER completion
    # Handle timeout
```

### Progress Output
Use `click.echo(msg, err=True)` to avoid interfering with stdout piping.

## Critical Warnings from Experience

### Python Cannot Interrupt Threads
We verified that Python threads cannot be killed or interrupted. The timeout mechanism can only detect that time has elapsed, not actually stop execution. This is a Python limitation, not a design choice.

### Node Name Attribute Inconsistency
Most nodes don't have a `name` attribute. Always use:
```python
node_name = getattr(node, 'name', node.__class__.__name__)
```

### Single-Threaded Execution
The planner is completely single-threaded, which makes monkey-patching safe but means we can't interrupt hung LLM calls.

### Default Directory Must Match Project Patterns
Use `~/.pflow/debug/` not `/tmp` to match existing project directory patterns.

## Key Decisions Already Made

1. **Two-mode system**: Progress always shown, traces saved on failure or request
2. **Node wrapping pattern**: No modifications to existing nodes
3. **JSON trace format**: Searchable and parseable by AI agents
4. **~/.pflow/debug/ directory**: Matches existing project patterns
5. **Timeout detection only**: Cannot interrupt, only detect after completion
6. **Progress to stderr**: Use click.echo with err=True
7. **Attribute delegation**: Use __getattr__ to preserve Flow compatibility

**📋 Note on Specifications**: The specification file (`task-27-spec.md`) is the authoritative source. Follow it precisely - do not deviate from specified behavior, test criteria, or implementation requirements unless you discover a critical issue (in which case, document the deviation clearly or STOP and ask the user for clarification).

## Success Criteria

Your implementation is complete when:

- ✅ All 28 test criteria from the spec pass
- ✅ Progress indicators appear for all planner executions
- ✅ Timeout detected after 60 seconds default
- ✅ Failed executions automatically save trace file
- ✅ Trace files contain all LLM prompts and responses
- ✅ --trace flag forces trace file generation
- ✅ No modifications to existing node code
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ Documentation updated with debugging guide

## Common Pitfalls to Avoid

1. **Forgetting to delegate attributes** - The DebugWrapper MUST use __getattr__ or nodes break
2. **Not restoring LLM methods** - Always use try/finally when monkey-patching
3. **Trying to interrupt threads** - Python limitation, can only detect timeout
4. **Using /tmp for traces** - Use ~/.pflow/debug/ to match project patterns
5. **Modifying original nodes** - Use wrapper pattern, never modify nodes directly
6. **Saving sensitive data in traces** - Filter out keys starting with _ and large objects
7. **Forgetting err=True in click.echo** - Will interfere with stdout piping

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

1. **Flow Execution Analysis**
   - Task: "Analyze how PocketFlow's Flow class executes nodes in pocketflow/__init__.py, focusing on what attributes it accesses"
   - Task: "Find how the planner's create_planner_flow() wires up all 9 nodes"

2. **LLM Call Patterns**
   - Task: "Identify all places where llm.get_model() is called in the planner nodes"
   - Task: "Analyze the structure of LLM responses and token usage"

3. **CLI Integration Points**
   - Task: "Find where the planner is executed in src/pflow/cli/main.py"
   - Task: "Identify existing verbose/debug patterns in the CLI"

4. **Testing Infrastructure**
   - Task: "Examine how planner tests mock LLM calls"
   - Task: "Find existing test fixtures for nodes"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_27/implementation/implementation-plan.md`

Include task breakdown by agent role as specified in `agent-responsibilities.md`.

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_27/implementation/progress-log.md`

```markdown
# Task 27 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. **Review all implementation guides** - The main-agent-implementation-guide.md has complete working code
2. **Create debug.py** - Start with DebugWrapper (most critical component)
3. **Deploy code-implementer** - Get utility functions built in parallel
4. **Test DebugWrapper locally** - Verify delegation works before proceeding
5. **Integrate with flow.py** - Wrap all 9 nodes
6. **Add CLI flags** - Wire up --trace and --planner-timeout
7. **Test end-to-end** - Run real planner with debugging
8. **Deploy test-writer-fixer** - Get comprehensive test coverage
9. **Fix any issues** - Use test results to refine
10. **Document** - Update README with debugging instructions

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - Implementing DebugWrapper
Attempting to wrap a test node to verify delegation...

Result: Discovered that successors must be copied directly
- ✅ What worked: __getattr__ delegation for unknown attributes
- ❌ What failed: Flow couldn't find successors when delegated
- 💡 Insight: Some attributes must be explicitly copied

Code that worked:
```python
self.successors = node.successors  # Must copy directly
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
- Original plan: Delegate all attributes via __getattr__
- Why it failed: Flow checks hasattr() for successors
- New approach: Copy critical attributes explicitly
- Lesson: Some frameworks use hasattr checks that bypass __getattr__
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test what matters"

**Focus on quality over quantity**:
- Test that wrapper preserves node functionality
- Test that LLM calls are captured correctly
- Test timeout detection works
- Test trace file generation

**Critical Test Scenarios**:
- DebugWrapper doesn't break nodes
- Timeout detection works
- Trace files are valid JSON
- LLM calls are captured
- Progress shows in terminal

**Progress Log - Only document testing insights**:
```markdown
## 15:30 - Testing revealed delegation issue
Discovered that hasattr() checks bypass __getattr__.
Had to explicitly copy successors attribute.
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** modify any existing node implementations (if not absolutely necessary)
- **DON'T** try to interrupt threads (Python limitation)
- **DON'T** use /tmp for trace files (use ~/.pflow/debug/)
- **DON'T** forget to restore LLM methods after interception
- **DON'T** save internal keys (starting with _) in traces
- **DON'T** add features not in spec (no interactive debugging, no profiling)
- **DON'T** skip the delegation pattern in DebugWrapper

## Getting Started

1. Read the epistemic manifesto and all context files
2. Review the complete code in main-agent-implementation-guide.md
3. Start with creating debug.py and the DebugWrapper class
4. Test locally with a simple wrapped node before full integration
5. Run frequently: `pytest tests/test_planning/test_debug.py -v`

## Final Notes

- The implementation guides contain verified, working code - use it!
- The DebugWrapper's attribute delegation is the most critical piece
- Python's threading limitations mean we can only detect timeouts, not interrupt
- The spec has been verified against the actual codebase behavior
- Focus on the two modes: progress (always) and traces (on failure/request)

## Remember

You're implementing critical debugging infrastructure that will make the planner observable and debuggable. The planner is currently hanging with no visibility - your implementation will finally reveal what's happening inside. The design has been carefully verified against the codebase. Trust the implementation guides but verify against the epistemic principles.

This debugging system will transform the planner from a black box into a transparent, debuggable system. Without it, developers are blind to what's happening during the 10-30 second execution. Your work will make every failure diagnosable and every prompt improvable.

Good luck! Your implementation will be the key to making the planner work reliably. Think hard!