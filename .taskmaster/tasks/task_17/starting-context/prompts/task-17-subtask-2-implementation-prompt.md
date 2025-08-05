# Task 17 - Subtask 2: Discovery System - Agent Instructions

## Critical Pre-Requirement

**IMPORTANT**: This prompt assumes you have already thoroughly read and understand:
- All Task 17 documentation in `.taskmaster/tasks/task_17/`
- The epistemic manifesto
- The two-path architecture (Path A: reuse, Path B: generate)
- How subtasks interconnect and depend on each other
- The shared progress log system

If you haven't read these yet, STOP and read them first.

## The Problem You're Solving

The Natural Language Planner needs an intelligent entry point that makes the critical routing decision between workflow reuse (Path A) and workflow generation (Path B). This decision point determines whether the system can quickly reuse an existing workflow or must creatively generate a new one. Additionally, when generation is needed, the system must browse available components to provide building blocks for the workflow generator.

## Your Mission Within Task 17

Implement the discovery nodes that serve as the entry point and initial router for the entire Natural Language Planner meta-workflow. You'll create WorkflowDiscoveryNode (the universal entry point) and ComponentBrowsingNode (for Path B building block selection), establishing the foundation for the two-path architecture.

## ⚠️ Critical Context: Task 17's Two-Path Architecture

Before implementing this subtask, you MUST understand the overall architecture:

**Path A (Workflow Reuse)**: Discovery → ParameterMapping → Preparation → Result
**Path B (Workflow Generation)**: Discovery → Browsing → ParamDiscovery → Generation → Validation → Metadata → ParameterMapping → Preparation → Result

**CONVERGENCE**: Both paths meet at ParameterMappingNode - the verification gate.

**This Subtask's Role**: Creates the entry point (WorkflowDiscoveryNode) that routes to either Path A or Path B, and implements ComponentBrowsingNode that runs ONLY in Path B to find building blocks for workflow generation.

## Dependencies and Prerequisites

### Subtasks That Must Be Complete
- ✅ Subtask 1 (Foundation): Provides directory structure and utilities

### Files/Outputs You'll Use From Previous Subtasks
- `src/pflow/planning/utils/workflow_loader.py` from Subtask 1
- `src/pflow/planning/utils/registry_helper.py` from Subtask 1
- `src/pflow/planning/ir_models.py` with Pydantic models from Subtask 1
- Test fixtures from `tests/test_planning/conftest.py`
- LLM configuration already set up with anthropic plugin

## Required Context Review

### Primary Source: Your Subtask Specification **Read this first**
**File**: `.taskmaster/tasks/task_17/starting-context/specs/task-17-subtask-2-spec.md`

**This is your PRIMARY source of truth** for requirements, interface contracts, and implementation details specific to Subtask 2.

Since you've already read all Task 17 documentation, focus on:
1. How WorkflowDiscoveryNode makes the binary routing decision
2. The difference between discovery (complete match) and browsing (building blocks)
3. Two-phase context loading pattern with context_builder
4. Interface contracts for shared store keys

**CRITICAL**: The spec defines exact behavior and interfaces. Follow it PRECISELY. Read it carefully and make sure you understand it before you start doing anything else.

## 🔄 Shared Progress Log (CRITICAL!)

**The progress log is SHARED across ALL Task 17 subtasks!**

**Location**: `.taskmaster/tasks/task_17/implementation/progress-log.md`

**Format for your entries**:
```markdown
## [Timestamp] - Subtask 2 - [What You're Trying]
Attempting to [specific action]...

Result: [What happened]
- ✅ What worked: [Specific detail]
- ❌ What failed: [Specific detail]
- 💡 Insight: [What you learned]

Code that worked:
```python
# Actual code snippet
```
```

**IMPORTANT**:
- Always prefix entries with your subtask number
- Check previous subtask entries to understand what's already implemented
- Your insights help future subtasks avoid pitfalls

## What You're Building

You're implementing two critical PocketFlow nodes that establish the routing foundation for the entire planner:

1. **WorkflowDiscoveryNode**: The universal entry point that performs semantic matching against existing workflows. Makes a binary decision: complete match exists ("found_existing") or not ("not_found").

2. **ComponentBrowsingNode**: Runs only in Path B after "not_found". Browses available components (both nodes AND workflows) to select building blocks for generation. Uses over-inclusive selection to avoid missing critical components.

Example usage within the planner:
```python
# The planner starts here for ALL requests
discovery_node = WorkflowDiscoveryNode()
# Routes to either:
# - "found_existing" → Path A (fast reuse)
# - "not_found" → Path B (creative generation)

# If Path B, then browse for components
browsing_node = ComponentBrowsingNode()
# Selects multiple nodes and workflows as building blocks
```

## Shared Store Contract

### Keys This Subtask READS
- `shared["user_input"]` - Natural language input from CLI
- `shared["stdin_data"]` - Optional data from stdin pipe
- `shared["current_date"]` - ISO timestamp for context

### Keys This Subtask WRITES
**WorkflowDiscoveryNode writes:**
- `shared["discovery_context"]` - Markdown from build_discovery_context()
- `shared["discovery_result"]` - LLM decision with found/workflow_name/confidence/reasoning
- `shared["found_workflow"]` - Full workflow metadata from WorkflowManager.load() (Path A only)

**ComponentBrowsingNode writes:**
- `shared["browsed_components"]` - Dict with node_ids and workflow_names lists
- `shared["planning_context"]` - Detailed markdown from build_planning_context() or empty string on error
- `shared["registry_metadata"]` - Full registry metadata for downstream nodes

### Expected Data Formats
```python
# WorkflowDiscoveryNode output
shared["discovery_result"] = {
    "found": True,
    "workflow_name": "generate-changelog",
    "confidence": 0.95,
    "reasoning": "Exact match for changelog generation from issues"
}

# ComponentBrowsingNode output
shared["browsed_components"] = {
    "node_ids": ["github-list-issues", "llm", "write-file"],
    "workflow_names": ["text-analyzer"],  # Can use workflows as building blocks!
    "reasoning": "Selected GitHub and text processing components"
}
```

## Key Outcomes You Must Achieve

### Core Deliverables
1. Create `src/pflow/planning/nodes.py` with both node classes
2. Implement WorkflowDiscoveryNode with semantic matching via LLM
3. Implement ComponentBrowsingNode with over-inclusive selection
4. Integrate with existing context_builder from Tasks 15/16
5. Create comprehensive tests in `tests/test_planning/test_discovery.py`

### Interface Requirements
- WorkflowDiscoveryNode MUST return exactly "found_existing" or "not_found"
- ComponentBrowsingNode MUST always return "found" (even with empty selections)
- Both nodes MUST implement exec_fallback for LLM failure recovery
- Both nodes MUST use structured output with Pydantic models

### Integration Points
- WorkflowDiscoveryNode is the entry point for ALL planner requests
- ComponentBrowsingNode connects to ParameterDiscoveryNode (Subtask 3)
- Discovery context feeds into generation context (Subtask 4)
- Registry metadata propagates through entire Path B

## Implementation Strategy

### Phase 1: Core Node Implementation (2-3 hours)
1. Create `src/pflow/planning/nodes.py` with module-level setup
2. Implement WorkflowDiscoveryNode class with all methods
3. Implement ComponentBrowsingNode class with all methods
4. Add proper logging with `logger = logging.getLogger(__name__)`
5. Import and use Pydantic models from ir_models.py

### Phase 2: Integration and Context Loading (1-2 hours)
1. Integrate with context_builder functions (proper imports)
2. Test two-phase context loading pattern
3. Verify WorkflowManager integration for loading workflows
4. Ensure Registry instantiation and loading works
5. Handle planning_context error dict scenario

### Phase 3: Testing and Edge Cases (2-3 hours)
1. Create comprehensive test suite in test_discovery.py
2. Test both Path A and Path B routing scenarios
3. Test exec_fallback behavior for both nodes
4. Test edge cases (empty workflows, LLM failures, etc.)
5. Verify integration with mocked dependencies

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### Context Builder Integration
The context_builder from Tasks 15/16 provides two critical functions:
```python
# For browsing (lightweight)
discovery_context = build_discovery_context(
    node_ids=None,  # All nodes
    workflow_names=None,  # All workflows
    registry_metadata=None  # Will load from default registry
)

# For detailed planning (after selection)
planning_context = build_planning_context(
    selected_node_ids=["github-list-issues", "llm"],
    selected_workflow_names=["text-analyzer"],
    registry_metadata=registry_metadata,  # Required
    saved_workflows=None  # Will load automatically
)
```

**CRITICAL**: build_planning_context() can return an error dict if components are missing. Handle this case!

### LLM Structured Output Pattern
Use Simon Willison's llm library with Pydantic for type-safe responses:
```python
import llm
from pydantic import BaseModel

class WorkflowDecision(BaseModel):
    found: bool
    workflow_name: Optional[str] = None
    confidence: float
    reasoning: str

# In your exec method
model = llm.get_model("anthropic/claude-sonnet-4-0")
response = model.prompt(prompt, schema=WorkflowDecision, temperature=0)
return response.json()  # Already validated!
```

### Binary Decision vs Over-Inclusive Browsing
- **WorkflowDiscoveryNode**: Binary decision - complete match or not. Partial matches still return "not_found".
- **ComponentBrowsingNode**: Over-inclusive - better to include extra components than miss critical ones.

## Critical Warnings from Task 17 Experience

### Template Variables Are Sacred
**NEVER hardcode extracted values** - workflows must be reusable. When user says "20 issues", generate `"limit": "$limit"` NOT `"limit": "20"`.

### Understanding Your Path
Your nodes are the gateway to BOTH paths. WorkflowDiscoveryNode determines the path, ComponentBrowsingNode only runs in Path B.

### Discovery ≠ Browsing
Discovery finds complete workflow matches. Browsing finds building blocks. This distinction is CRITICAL for proper routing.

### Workflows as Building Blocks
ComponentBrowsingNode can select existing workflows to use as building blocks in new workflows. A workflow becomes a node when used this way.

## Key Decisions Already Made for Task 17

1. **Model Selection**: Use "anthropic/claude-sonnet-4-0" for all LLM calls
2. **Import Pattern**: Direct imports, no dependency injection through shared
3. **Node Organization**: All nodes in single `nodes.py` file
4. **Failure Handling**: exec_fallback returns safe defaults, never crashes
5. **Context Loading**: Two-phase pattern for efficiency
6. **Registry Access**: Instantiate Registry() when needed (not singleton)

**📋 Note on Specifications**: Your subtask specification is the authoritative source. Follow it precisely - do not deviate from specified behavior, interface contracts, or implementation requirements unless you discover a critical issue (document and ask for clarification).

## Success Criteria

Your implementation is complete when:

✅ WorkflowDiscoveryNode correctly routes to "found_existing" or "not_found"
✅ ComponentBrowsingNode selects appropriate building blocks with over-inclusive approach
✅ Both nodes handle LLM failures gracefully via exec_fallback
✅ Context builder integration works for both discovery and planning phases
✅ Shared store keys are properly read/written per specification
✅ Registry metadata propagates correctly for Path B
✅ make test passes for all discovery tests
✅ make check passes
✅ Progress log documents your implementation journey with insights
✅ Integration tests verify routing to subsequent subtasks

## Common Pitfalls to Avoid

1. **DON'T implement parameter extraction** - That's Subtask 3's responsibility
2. **DON'T hardcode any values** - Use template variables for everything dynamic
3. **DON'T forget exec_fallback** - Both nodes MUST handle LLM failures
4. **DON'T skip logging** - Future subtasks need visibility into routing decisions
5. **DON'T modify context_builder** - Just import and use it
6. **DON'T create thin wrappers** - Import directly per PocketFlow patterns
7. **DON'T forget error dict handling** - planning_context can return errors

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent conflicts with other subtasks.

**Location**: `.taskmaster/tasks/task_17/implementation/subtask-2/implementation-plan.md`

### Why Planning Matters for Subtasks

1. **Prevents breaking interfaces**: Other subtasks depend on your outputs
2. **Identifies integration points**: Discover how you connect to the flow
3. **Optimizes parallelization**: Know what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Previous Subtask Analysis**
   - Task: "Analyze outputs from Subtask 1 and identify what utilities are available"
   - Task: "Check if workflow_loader and registry_helper are properly implemented"

2. **Interface Discovery**
   - Task: "Identify how discovery nodes will connect to parameter nodes in Subtask 3"
   - Task: "Analyze how browsed components will be used by the generator in Subtask 4"

3. **Testing Pattern Analysis**
   - Task: "Examine tests/test_planning/conftest.py for available fixtures"
   - Task: "Identify patterns for mocking LLM responses in tests"

4. **Integration Requirements**
   - Task: "Check how context_builder functions are used"
   - Task: "Verify WorkflowManager and Registry usage patterns"
```

> Note: Your prompts to the subagents should be very specific and detailed, providing full Task 17 context.

### Step 2: Write Your Implementation Plan

Your plan should include:

1. **Interface verification** - Confirm what Subtask 1 provides
2. **Component breakdown** - Both nodes with all methods
3. **Integration strategy** - How to connect context_builder
4. **Risk identification** - What could affect other subtasks
5. **Testing strategy** - How to verify routing works correctly

### Implementation Plan Template

```markdown
# Task 17 - Subtask 2 Implementation Plan

## Dependencies Verified

### From Previous Subtasks
- workflow_loader.py provides load_workflow() and list_all_workflows()
- registry_helper.py provides get_node_interface(), get_node_outputs()
- ir_models.py has WorkflowDecision and ComponentSelection models
- Test fixtures include mock_llm_model and mock_registry

### For Next Subtasks
- Must provide discovery_result for parameter extraction
- Must provide browsed_components for workflow generation
- Must provide registry_metadata for downstream validation

## Shared Store Contract
- Reads: user_input, stdin_data, current_date
- Writes: discovery_context, discovery_result, found_workflow (Path A)
- Writes: browsed_components, planning_context, registry_metadata (Path B)

## Implementation Steps

### Phase 1: Core Components
1. Create nodes.py with logging setup
2. Implement WorkflowDiscoveryNode with semantic matching
3. Implement ComponentBrowsingNode with over-inclusive selection
4. Add exec_fallback to both nodes

### Phase 2: Integration
1. Import and use context_builder functions
2. Integrate WorkflowManager for loading workflows
3. Handle planning_context error dict case
4. Test Registry instantiation

### Phase 3: Testing
1. Create test_discovery.py
2. Test Path A routing (found_existing)
3. Test Path B routing (not_found)
4. Test edge cases and failures

## Risk Mitigation

| Risk | Impact on Other Subtasks | Mitigation Strategy |
|------|-------------------------|-------------------|
| Wrong action strings | Breaks flow routing | Follow spec exactly |
| Missing registry_metadata | Breaks validation | Always store in shared |
| Planning context errors | Breaks generation | Handle error dict case |

## Validation Strategy
- Verify routing strings match spec exactly
- Ensure all shared store keys are written
- Test integration with mocked downstream nodes
```

### When to Revise Your Plan

Your plan is a living document. Update it when:
- You discover interface mismatches with other subtasks
- Integration tests reveal issues
- Better approaches become apparent

Document plan changes in the SHARED progress log with rationale.

## Your Implementation Order

### 0. Review Shared Progress Log (FIRST!)

Check what previous subtasks have implemented: `.taskmaster/tasks/task_17/implementation/progress-log.md`

### 1. Create Your Implementation Plan (SECOND!)

Location: `.taskmaster/tasks/task_17/subtask_2/implementation-plan.md`

### Implementation Steps

1. Create `src/pflow/planning/nodes.py` with both node classes
2. Set up module-level imports and logging
3. Implement WorkflowDiscoveryNode with all methods
4. Implement ComponentBrowsingNode with all methods
5. Test context_builder integration locally
6. Create comprehensive test suite
7. Run make test and make check
8. Document insights in shared progress log

## Real-Time Learning Capture in SHARED Log

**AS YOU IMPLEMENT**, continuously append to the SHARED progress log:

```markdown
## [Timestamp] - Subtask 2 - Implementing discovery routing
Attempting to integrate context_builder for discovery...

Result: build_discovery_context() requires registry_metadata parameter
- ✅ What worked: Passing None loads default registry
- ❌ What failed: Initial attempt without any parameters
- 💡 Insight: Context builder has smart defaults, use them!

Code that worked:
```python
discovery_context = build_discovery_context(
    node_ids=None,  # Gets all nodes
    workflow_names=None,  # Gets all workflows
    registry_metadata=None  # Loads from default registry
)
```
```

**Remember**: Your insights help future subtasks!

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Consider impact on other subtasks
4. Update the plan with new approach
5. Continue with new understanding

Append deviation to SHARED progress log:
```markdown
## [Time] - Subtask 2 - DEVIATION FROM PLAN
- Original plan: Use simple string matching for workflows
- Why it failed: Need semantic understanding for variations
- Impact on other subtasks: None - interface unchanged
- New approach: Use LLM with structured output
- Lesson: Discovery requires intelligence, not just string matching
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test routing and integration"

**Focus on**:
- Correct routing: "found_existing" vs "not_found"
- Shared store keys written correctly
- Context builder integration
- LLM failure handling via exec_fallback
- Over-inclusive browsing behavior

**What to test**:
- **Routing logic**: Both paths route correctly
- **Shared store**: All keys properly written
- **Integration**: Context builder calls work
- **Error handling**: LLM failures don't crash
- **Edge cases**: Empty workflows, no matches, etc.

**Progress Log - Only document testing insights**:
```markdown
## 2024-01-15 14:30 - Subtask 2 - Testing revealed routing issue
Discovered that partial workflow matches were returning "found_existing".
Need to ensure only COMPLETE matches trigger Path A.
Fixed by emphasizing "complete satisfaction" in prompt.
```

**Remember**: Integration tests > isolated unit tests for subtasks

## What NOT to Do

- DON'T implement parameter extraction - That's Subtask 3
- DON'T implement workflow generation - That's Subtask 4
- DON'T modify shared store keys from other subtasks
- DON'T create new abstractions over context_builder
- DON'T forget to handle planning_context error dict
- DON'T hardcode workflow names or node types
- DON'T skip exec_fallback implementation
- DON'T return wrong action strings - follow spec exactly

## Getting Started

1. Check the shared progress log to see what Subtask 1 implemented
2. Create your implementation plan with parallel context gathering
3. Start with `nodes.py` and module-level setup
4. Implement WorkflowDiscoveryNode first (it's the entry point)
5. Test locally with `python -m pytest tests/test_planning/test_discovery.py -xvs`
6. Document discoveries in the shared progress log

## Final Notes

Remember that your nodes are the gateway to the entire planner. Every request flows through WorkflowDiscoveryNode first, making the critical Path A vs Path B decision. ComponentBrowsingNode sets up Path B for success by finding the right building blocks.

The distinction between discovery (binary complete match) and browsing (over-inclusive selection) is fundamental to the architecture. Get this right, and the rest of the planner flows smoothly.

Your work on the discovery system directly impacts the planner's ability to quickly reuse existing workflows (Path A) or creatively generate new ones (Path B). This routing decision is the key to performance and user satisfaction.

## Remember

You're implementing Subtask 2 of 7 for Task 17's Natural Language Planner. Your work enables pflow's "Plan Once, Run Forever" philosophy. The two-path architecture with convergence at ParameterMappingNode is the key innovation. Your subtask creates the intelligent entry point that makes this sophisticated routing possible.

The discovery system you're building is the foundation for the entire planner's decision-making. Every workflow reuse or generation starts with your nodes making the right routing choice.

Good luck implementing the discovery system - the gateway to intelligent workflow planning!
