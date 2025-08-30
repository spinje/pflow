# Task 32: Unified Metrics and Tracing System for Workflow Execution - Agent Instructions

## The Problem You're Solving

Currently, pflow users have no visibility into their AI costs or workflow execution. They don't know how much their LLM calls cost, can't identify performance bottlenecks, and have no way to debug workflow execution (unlike the planner which has tracing). Users are flying blind with their AI spend and debugging capabilities.

## Your Mission

Implement a comprehensive observability system that provides cost tracking, performance metrics, and debugging capabilities for both planner and workflow execution. The system collects lightweight metrics when using `--output-format json` and detailed traces with `--trace` flags, giving users complete visibility into LLM costs and execution performance.

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
**File**: `.taskmaster/tasks/task_32/task-32.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_32/starting-context/`

**Files to read (in this order):**
1. `implementation-guide.md` - Complete implementation guide with code examples and integration points
2. `task-32-handover.md` - Critical war stories, gotchas, and discoveries from investigation
3. `task-32-spec.md` - The specification (FOLLOW THIS PRECISELY for requirements and test criteria)

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-32-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

A unified telemetry system with three progressive modes:

1. **Default (no flags)**: Zero overhead, no collection - clean and fast
2. **Metrics (`--output-format json`)**: Lightweight cost/timing metrics in JSON output
3. **Tracing (`--trace` / `--trace-planner`)**: Full debugging details saved to files

The system uses a single `InstrumentedNodeWrapper` that serves both metrics collection (lightweight, always with JSON output) and tracing (detailed, opt-in with flags).

Example JSON output with metrics:
```json
{
  "result": {"analysis": "complete"},
  "is_error": false,
  "duration_ms": 3521,
  "duration_planner_ms": null,
  "total_cost_usd": 0.0127,
  "num_nodes": 4,
  "metrics": {
    "workflow": {
      "duration_ms": 3521,
      "nodes_executed": 4,
      "cost_usd": 0.0127,
      "node_timings": {
        "fetch_data": 487,
        "analyze_llm": 2876
      }
    }
  }
}
```

## Key Outcomes You Must Achieve

### Core Infrastructure
- MetricsCollector class for lightweight aggregation
- InstrumentedNodeWrapper for unified metrics/tracing
- WorkflowTraceCollector for detailed debugging
- Model pricing dictionary with accurate costs

### Integration
- Enhanced DebugWrapper to use MetricsCollector
- Modified compiler to apply InstrumentedNodeWrapper
- Updated CLI with new flags and JSON output wrapping
- LLM usage accumulation (solving the overwrite problem)

### Testing & Documentation
- Comprehensive test suite (CRITICAL: no tests exist currently!)
- All 31 test criteria from spec passing
- Performance overhead < 1%
- Clear documentation of metrics format

## Implementation Strategy

### Phase 1: Core Infrastructure (4-5 hours)
1. Create `src/pflow/core/metrics.py` with MetricsCollector
2. Create `src/pflow/runtime/instrumented_wrapper.py` with InstrumentedNodeWrapper
3. Create `src/pflow/runtime/workflow_trace.py` with WorkflowTraceCollector
4. Add MODEL_PRICING dictionary with per-million token pricing

### Phase 2: Planner Integration (2-3 hours)
1. Modify DebugWrapper in `src/pflow/planning/debug.py` to accept metrics
2. Update DebugContext to include metrics parameter
3. Pass metrics through planner execution flow

### Phase 3: Workflow Integration (3-4 hours)
1. Modify `_create_single_node` in compiler.py to apply InstrumentedNodeWrapper
2. Update `compile_ir_to_flow` to accept collectors
3. Ensure correct wrapper order: Instrumented → Namespaced → TemplateAware → Node

### Phase 4: CLI Integration (3-4 hours)
1. Add `--trace-planner` flag to CLI
2. Update `--trace` flag for workflow tracing
3. Modify execute_json_workflow for metrics/tracing
4. Implement JSON output wrapping with top-level metrics

### Phase 5: Testing (4-5 hours)
1. Create comprehensive unit tests for all components
2. Create integration tests for full flow
3. Test all 31 criteria from spec
4. Verify performance overhead < 1%

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### The LLM Usage Overwrite Problem
**CRITICAL**: `shared["llm_usage"]` is OVERWRITTEN on each LLM call, not accumulated!
```python
# PROBLEM: Each LLM node overwrites the previous
shared["llm_usage"] = {...}  # This replaces, doesn't accumulate!

# SOLUTION: Create accumulation list
if "__llm_calls__" not in shared:
    shared["__llm_calls__"] = []
shared["__llm_calls__"].append(llm_call_data)
```

### Timing Implementation
**CRITICAL**: Use `time.perf_counter()` NOT `time.time()`!
```python
# WRONG - wall clock time, affected by NTP
start = time.time()

# CORRECT - monotonic, high-resolution
start = time.perf_counter()
```

### Trace File Locations
**CRITICAL**: Directory is `~/.pflow/debug/` NOT `~/.pflow/traces/`
```python
# Filename format: timestamp-based, not UUID
timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
filename = f"pflow-trace-workflow-{timestamp}.json"
# UUID goes INSIDE JSON as execution_id field
```

### Wrapper Delegation Pattern
**MUST** follow this exact pattern from existing wrappers:
```python
def __getattr__(self, name: str) -> Any:
    if name in ("__setstate__", "__getstate__", "__getnewargs__", "__getnewargs_ex__"):
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
    inner = object.__getattribute__(self, "inner_node")
    return getattr(inner, name)
```

### Model Pricing
Use per-million token pricing to match existing test tool:
```python
MODEL_PRICING = {
    "anthropic/claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "anthropic/claude-sonnet-4-0": {"input": 3.00, "output": 15.00},
    # ... more models
}
```

## Critical Warnings from Experience

### The Lazy Response Bug
The `llm` library returns lazy Response objects. `prompt()` returns instantly—the actual API call happens when `response.json()` or `response.text()` is called. You MUST time the evaluation, not the prompt call!

### Zero Test Coverage Discovery
**WARNING**: The existing debug/tracing system has ZERO test coverage! The test files mentioned in Task 27 don't exist. You must create ALL tests from scratch.

### Template Resolution Gap
Templates are currently only logged at DEBUG level. There's no mechanism to capture them for traces. You'll need to implement capture from scratch around `node_wrapper.py:112-159`.

### The Wrapper Order Trap
InstrumentedNodeWrapper MUST be outermost to see all operations:
```
InstrumentedNodeWrapper (sees everything)
    ↓
NamespacedNodeWrapper (creates namespaced store)
    ↓
TemplateAwareNodeWrapper (resolves templates)
    ↓
BaseNode (actual implementation)
```

## Key Decisions Already Made

1. **Unified wrapper pattern** - Single instrumentation point for both metrics and tracing
2. **Top-level metrics in JSON** - Claude Code-compatible format with `is_error`, `duration_ms`, `total_cost_usd` at root
3. **Progressive enhancement** - No flags = zero overhead, `--output-format json` = metrics, `--trace` = full debugging
4. **Keep existing directory** - Use `~/.pflow/debug/` not create new `~/.pflow/traces/`
5. **Accumulate LLM usage in list** - Don't modify LLMNode, use `__llm_calls__` list
6. **Per-million token pricing** - Match existing test tool implementation
7. **No deprecation warnings** - This is a private MVP, just change behavior

**📋 Note on Specifications**: The specification file (`task-32-spec.md`) is the authoritative source. Follow it precisely - do not deviate from specified behavior, test criteria, or implementation requirements unless you discover a critical issue (in which case, document the deviation clearly or STOP and ask the user for clarification).

## Success Criteria

Your implementation is complete when:

- ✅ `pflow run workflow.json` = Clean output, no overhead
- ✅ `pflow run workflow.json --output-format json` includes top-level metrics
- ✅ `pflow run workflow.json --trace` saves workflow trace to ~/.pflow/debug/
- ✅ `pflow "create story" --trace-planner` saves planner trace
- ✅ Metrics show accurate costs based on token usage
- ✅ All 31 test criteria from spec pass
- ✅ Performance overhead < 1% when metrics enabled
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)

## Common Pitfalls to Avoid

1. **DON'T use `time.time()`** - Always use `time.perf_counter()` for timing
2. **DON'T rely on `shared["llm_usage"]` for aggregation** - It overwrites, use accumulation list
3. **DON'T forget the lazy response timing** - Time when `.json()` is called, not `prompt()`
4. **DON'T put InstrumentedNodeWrapper in wrong position** - Must be outermost wrapper
5. **DON'T skip creating tests** - No tests exist, you must create comprehensive coverage
6. **DON'T create `~/.pflow/traces/`** - Use existing `~/.pflow/debug/` directory
7. **DON'T modify LLMNode** - Use wrapper pattern to keep nodes pure

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

1. **Existing Debug System Analysis**
   - Task: "Analyze how DebugWrapper and TraceCollector work in src/pflow/planning/debug.py"
   - Task: "Find how LLM interception is implemented and where cleanup happens"

2. **Compiler Integration Points**
   - Task: "Analyze _create_single_node in compiler.py to understand wrapper application"
   - Task: "Find how compile_ir_to_flow passes parameters through compilation"

3. **CLI Flag Implementation**
   - Task: "Examine how --trace flag is currently implemented in main.py"
   - Task: "Find where JSON output formatting happens"

4. **LLMNode Behavior**
   - Task: "Verify how LLMNode stores usage data in shared store"
   - Task: "Check if llm_usage overwrites or accumulates"

5. **Testing Patterns**
   - Task: "Find how LLM mocking is done in existing planner tests"
   - Task: "Identify test patterns for wrapper classes"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_32/implementation/implementation-plan.md`

Your plan should include:

1. **Comprehensive task breakdown** - Every file to create/modify
2. **Dependency mapping** - What must be done before what
3. **Subagent task assignments** - Who does what, ensuring no conflicts
4. **Risk identification** - What could go wrong and mitigation strategies
5. **Testing strategy** - How you'll verify each component works

### Subagent Task Scoping Guidelines

**✅ GOOD Subagent Tasks:**
```markdown
- "Create MetricsCollector class in src/pflow/core/metrics.py with aggregation and cost calculation"
- "test-writer-fixer: Write unit tests for MetricsCollector focusing on LLM usage aggregation"
- "Modify _create_single_node in compiler.py to apply InstrumentedNodeWrapper as outermost wrapper"
```

**❌ BAD Subagent Tasks:**
```markdown
- "Implement the entire metrics system" (too broad)
- "Update all CLI files" (multiple agents will conflict)
- "Fix any issues you find" (too vague)
```

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_32/implementation/progress-log.md`

```markdown
# Task 32 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
Understanding that metrics and tracing are the same telemetry at different verbosity levels...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. Create implementation plan with context gathering
2. Implement MetricsCollector with cost calculation
3. Implement InstrumentedNodeWrapper with proper delegation
4. Implement WorkflowTraceCollector for debugging
5. Enhance DebugWrapper to use metrics
6. Modify compiler to apply instrumentation wrapper
7. Add CLI flags and update JSON output
8. Create comprehensive test suite
9. Verify performance overhead < 1%
10. Run full test suite and fix issues

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - Discovered LLM usage overwrite issue
Attempting to aggregate LLM usage from multiple nodes...

Result: shared["llm_usage"] is overwritten on each call!
- ✅ What worked: Creating __llm_calls__ list for accumulation
- ❌ What failed: Relying on llm_usage directly
- 💡 Insight: Need accumulation mechanism at wrapper level

Code that worked:
```python
if "__llm_calls__" not in shared:
    shared["__llm_calls__"] = []
shared["__llm_calls__"].append(llm_call_data)
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
- Original plan: Use shared["llm_usage"] for aggregation
- Why it failed: Each node overwrites instead of accumulating
- New approach: Create __llm_calls__ list for accumulation
- Lesson: Can't modify node behavior, must work around it
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**CRITICAL**: NO TESTS EXIST for the debug system! You must create from scratch.

**Core Principle**: "Test what matters"

**Focus on quality over quantity**:
- Test LLM usage aggregation from multiple nodes
- Test cost calculation for different models
- Test wrapper delegation and timing capture
- Test trace file generation and format
- Test CLI flag behavior
- Test JSON output with metrics
- Test performance overhead

**What to test**:
- **Aggregation**: Multiple LLM calls accumulate correctly
- **Cost calculation**: Accurate pricing for known/unknown models
- **Wrapper behavior**: Timing, delegation, error handling
- **Integration**: Full flow from CLI to output
- **Edge cases**: No LLM nodes, failed nodes, missing data

**Progress Log - Only document testing insights**:
```markdown
## 14:50 - Testing revealed overwrite bug
While testing multiple LLM nodes, discovered only last usage saved.
Created accumulation list pattern. This affects all metrics collection.
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** use `time.time()` - Always use `time.perf_counter()`
- **DON'T** modify existing nodes - Use wrapper pattern
- **DON'T** create new trace directory - Use `~/.pflow/debug/`
- **DON'T** add deprecation warnings - Just change behavior
- **DON'T** skip creating tests - ZERO tests exist currently
- **DON'T** forget lazy response timing - Time evaluation not prompt
- **DON'T** put wrapper in wrong order - Must be outermost

## Getting Started

1. Read the epistemic manifesto first
2. Read all context files in order
3. Create your progress log
4. Create comprehensive implementation plan
5. Start with MetricsCollector - it's the foundation
6. Test frequently: `pytest tests/test_core/test_metrics.py -v`

## Final Notes

- The implementation guide has complete code examples - use them!
- CRITICAL: Create tests as you go (none exist currently)
- Verify costs match Claude Code for comparison
- Template resolution capture needs new implementation
- This enables cost transparency - make it accurate

## Remember

You're implementing the observability layer that makes pflow's costs transparent. Users will rely on these metrics to understand their AI spend. The architecture is sound (unified telemetry at different verbosity levels), the patterns are proven (from Task 27), but the existing debug system has ZERO test coverage. Create comprehensive tests as you build.

This task transforms pflow from a black box to a transparent, cost-aware AI orchestration platform. Make it accurate, make it fast, make it useful.

Good luck! The hard decisions have been made, the gotchas have been discovered, and the implementation guide has working code. Now it's careful implementation with proper test coverage.