# Task 17 - Subtask 6: Flow Orchestration - Agent Instructions

## Critical Pre-Requirement

**IMPORTANT**: This prompt assumes you have already thoroughly read and understand:
- All Task 17 documentation in `.taskmaster/tasks/task_17/`
- **CRITICAL: `.taskmaster/tasks/task_17/handoffs/subtask-6-complete-learnings.md`** - Contains essential discoveries about testing and retry mechanisms
- The epistemic manifesto
- The two-path architecture (Path A: reuse, Path B: generate)
- How subtasks interconnect and depend on each other
- The shared progress log system

If you haven't read these yet, STOP and read them first. The subtask-6-complete-learnings.md file is ESPECIALLY important as it corrects misconceptions and provides key insights discovered during investigation.

## The Problem You're Solving

The Natural Language Planner has all individual nodes implemented but lacks the orchestration layer that connects them into a complete meta-workflow. Without proper flow wiring, the sophisticated two-path architecture with convergence at ParameterMappingNode cannot function, and the planner cannot transform natural language into executable workflows.

## Your Mission Within Task 17

Wire all 8 existing planner nodes plus the new ResultPreparationNode into a complete PocketFlow flow with proper branching, convergence, and retry logic, enabling the full "Plan Once, Run Forever" meta-workflow.

## ⚠️ Critical Context: Task 17's Two-Path Architecture

Before implementing this subtask, you MUST understand the overall architecture:

**Path A (Workflow Reuse)**: Discovery → ParameterMapping → Preparation → Result
**Path B (Workflow Generation)**: Discovery → Browsing → ParamDiscovery → Generation → Validation → Metadata → ParameterMapping → Preparation → Result

**CONVERGENCE**: Both paths meet at ParameterMappingNode - the verification gate.

**This Subtask's Role**: Creates the complete flow orchestration that enables both paths to execute with proper branching, retry logic (which works correctly with 3-attempt limit), and convergence at the critical verification point.

## Dependencies and Prerequisites

### Subtasks That Must Be Complete
- ✅ Subtask 1 (Foundation): Provides directory structure and utilities
- ✅ Subtask 2 (Discovery): Provides WorkflowDiscoveryNode and ComponentBrowsingNode
- ✅ Subtask 3 (Parameter Management): Provides ParameterDiscoveryNode, ParameterMappingNode, ParameterPreparationNode
- ✅ Subtask 4 (Generation): Provides WorkflowGeneratorNode
- ✅ Subtask 5 (Validation & Refinement): Provides ValidatorNode and MetadataGenerationNode

### Files/Outputs You'll Use From Previous Subtasks
- `src/pflow/planning/nodes.py` with all 8 implemented nodes
- Test fixtures from `tests/test_planning/conftest.py`
- WorkflowManager integration via shared store pattern
- All node action strings verified in previous subtasks

## Required Context Review

### Primary Source: Your Subtask Specification
**File**: `.taskmaster/tasks/task_17/starting-context/specs/task-17-subtask-6-spec.md`

**This is your PRIMARY source of truth** for requirements, interface contracts, and implementation details specific to Subtask 6.

Since you've already read all Task 17 documentation, focus on:
1. The exact action strings each node returns (all verified from code)
2. The three entry points to ResultPreparationNode
3. How retry mechanism works (ValidatorNode → WorkflowGeneratorNode loop)
4. The convergence at ParameterMappingNode from both paths

**CRITICAL**: The spec defines exact behavior and interfaces. Follow it PRECISELY. Read it carefully and make sure you understand it before you start doing anything else.

### Handoff Document from Previous Subtasks
**File**: `.taskmaster/tasks/task_17/handoffs/handoff-to-subtask-6.md`

This document provides the handoff from Subtask 5, including:
- What has been implemented in previous subtasks
- Exact action strings used by all nodes
- Critical notes about retry mechanism
- State of the implementation

### Essential Learnings Document
**File**: `.taskmaster/tasks/task_17/handoffs/subtask-6-complete-learnings.md`

This document contains CRITICAL discoveries from investigation:
- Full integration tests ARE feasible using test WorkflowManager
- Retry loops work correctly with 3-attempt limit
- PocketFlow loops are functional (not broken as initially thought)
- Test isolation pattern using WorkflowManager via shared store

### PocketFlow Framework Source and Documentation

#### Core Framework Source
**File**: `pocketflow/__init__.py`

**REQUIRED READING**: This 200-line file contains the entire PocketFlow framework. You MUST understand:
- How `Flow` class works (lines 83-117)
- How nodes are connected with `>>` and `-` operators
- How `copy.copy()` is used in flow execution
- The node lifecycle (prep, exec, post)

#### Essential PocketFlow Documentation

**File**: `pocketflow/docs/core_abstraction/flow.md`

This explains Flow orchestration in detail:
- How flows connect nodes and manage execution
- Action-based routing (critical for our retry loop)
- Flow lifecycle and termination
- Examples of branching and conditional routing

**File**: `pocketflow/docs/core_abstraction/node.md`

Understanding Node lifecycle for ResultPreparationNode:
- The prep/exec/post pattern
- How nodes communicate via shared store
- Action strings and routing decisions
- exec_fallback for error handling

**File**: `pocketflow/cookbook/pocketflow-flow/flow.py`

A working example of complex flow wiring:
- Shows practical use of `>>` and `-` operators
- Demonstrates branching patterns
- Example of how final nodes work

**Optional but Helpful**:
- `pocketflow/tests/test_flow_basic.py` - See working loop test (test_cycle_until_negative_ends_with_signal)
- `pocketflow/cookbook/pocketflow-retry/` - Retry patterns if you need examples

## 🔄 Shared Progress Log (CRITICAL!)

**The progress log is SHARED across ALL Task 17 subtasks!**

**Location**: `.taskmaster/tasks/task_17/implementation/progress-log.md`

**Format for your entries**:
```markdown
## [Timestamp] - Subtask 6 - [What You're Trying]
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
- Always prefix entries with "Subtask 6"
- Check previous subtask entries to understand what's already implemented
- Your insights help future subtasks avoid pitfalls

## What You're Building

You're creating the orchestration layer that connects all planner nodes into a complete flow:

1. **ResultPreparationNode**: The final node that packages output for CLI consumption
2. **create_planner_flow()**: The function that wires all nodes with proper edges
3. **Complete integration tests**: Using test WorkflowManager for isolation

Example usage within the planner:
```python
from pflow.planning import create_planner_flow

# Create the complete planner flow
flow = create_planner_flow()

# Run with controlled test environment
shared = {
    "user_input": "create a changelog from closed issues",
    "workflow_manager": WorkflowManager(test_dir)  # For testing
}
flow.run(shared)

# Access results
planner_output = shared["planner_output"]
```

## Shared Store Contract

### Keys This Subtask READS
- `shared["found_workflow"]` - Existing workflow from discovery (Path A)
- `shared["generated_workflow"]` - Generated workflow from generator (Path B)
- `shared["execution_params"]` - Final parameters from ParameterPreparationNode
- `shared["missing_params"]` - List of missing required parameters
- `shared["validation_errors"]` - List of validation errors from ValidatorNode
- `shared["workflow_metadata"]` - Metadata from MetadataGenerationNode
- `shared["generation_attempts"]` - Retry attempt counter
- `shared["discovery_result"]` - Result from WorkflowDiscoveryNode

### Keys This Subtask WRITES
- `shared["planner_output"]` - Final output dict for CLI consumption

### Expected Data Formats
```python
shared["planner_output"] = {
    "success": bool,                    # True if ready to execute
    "workflow_ir": dict or None,        # The workflow IR
    "execution_params": dict or None,   # Parameters for execution
    "missing_params": list or None,     # Missing required params
    "error": str or None,              # Human-readable error message
    "workflow_metadata": dict or None   # Metadata for saving/display
}
```

## Key Outcomes You Must Achieve

### Core Deliverables
1. ResultPreparationNode class in `src/pflow/planning/nodes.py`
2. create_planner_flow() function in `src/pflow/planning/flow.py`
3. Export create_planner_flow in `src/pflow/planning/__init__.py`
4. Comprehensive integration tests in `tests/test_planning/test_planner_integration.py`
5. Flow structure tests in `tests/test_planning/test_flow_structure.py`

### Interface Requirements
- ResultPreparationNode must handle 3 entry points
- Flow must wire all nodes with exact action strings
- Retry loop must be properly defined (it WILL work)
- Both paths must converge at ParameterMappingNode

### Integration Points
- ResultPreparationNode is the final node for ALL paths
- ParameterMappingNode is the convergence point for both paths
- ValidatorNode connects back to WorkflowGeneratorNode for retry

## Implementation Strategy

### Phase 1: Create ResultPreparationNode (30 minutes)
1. Add ResultPreparationNode class to nodes.py
2. Implement prep() to gather all potential inputs
3. Implement exec() to determine success/failure
4. Implement post() to return None (standard final node pattern)
5. Create unit tests for all 3 entry scenarios

### Phase 2: Create Flow Orchestration (45 minutes)
1. Create src/pflow/planning/flow.py
2. Import all nodes from nodes.py
3. Define create_planner_flow() function
4. Wire Path A edges (discovery → mapping → prep → result)
5. Wire Path B edges (all nodes including retry loop)
6. Document retry mechanism behavior in comments
7. Export function in __init__.py

### Phase 3: Create Integration Tests (1 hour)
1. Create test_planner_integration.py
2. Implement tests using test WorkflowManager pattern
3. Test Path A with existing workflow
4. Test Path B with generation
5. Test retry mechanism with controlled mocking
6. Test missing parameters scenario
7. Create test_flow_structure.py for structural verification

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### Exact Action Strings (Verified from Code)
```python
# These are the EXACT strings - use them precisely
WorkflowDiscoveryNode:     "found_existing" | "not_found"
ComponentBrowsingNode:     "generate"
ParameterDiscoveryNode:    "" (empty string)
ParameterMappingNode:      "params_complete" | "params_incomplete"
ParameterPreparationNode:  "" (empty string)
WorkflowGeneratorNode:     "validate"
ValidatorNode:            "metadata_generation" | "retry" | "failed"
MetadataGenerationNode:    "" (empty string)
ResultPreparationNode:     None (return None to end flow)
```

### PocketFlow Flow API Pattern
```python
from pocketflow import Flow

def create_planner_flow():
    # Create nodes
    discovery_node = WorkflowDiscoveryNode()
    # ... create all nodes

    # Create flow with start node
    flow = Flow(start=discovery_node)  # NOT Flow() >> discovery_node

    # Wire edges using exact syntax
    discovery_node - "found_existing" >> parameter_mapping
    discovery_node - "not_found" >> component_browsing

    # Empty string actions need explicit wiring
    parameter_discovery >> workflow_generator  # "" action

    return flow
```

### Test WorkflowManager Pattern (KEY DISCOVERY!)
```python
def test_planner_path_a_complete():
    """Test with complete control over workflows."""
    # Create isolated test environment
    test_dir = tmp_path / "test_workflows"
    test_manager = WorkflowManager(test_dir)

    # Add controlled test workflows
    test_manager.save(
        name="test-workflow",
        workflow={...},
        metadata={...}
    )

    # Run planner with test manager
    flow = create_planner_flow()
    shared = {
        "user_input": "test input",
        "workflow_manager": test_manager  # Complete control!
    }
    flow.run(shared)

    # Verify results
    assert shared["planner_output"]["success"]
```

## Critical Warnings from Task 17 Experience

### Template Variables Are Sacred
**NEVER hardcode extracted values** - workflows must be reusable. When user says "20 issues", generate `"limit": "$limit"` NOT `"limit": "20"`.

### Understanding Your Path
Know that your subtask creates the orchestration for BOTH paths with proper convergence at ParameterMappingNode.

### Retry Loops Work Correctly
Despite initial concerns, PocketFlow loops work fine. The retry mechanism with 3-attempt limit prevents infinite loops. Previous test issues were due to poor test setup, not framework limitations.

## Key Decisions Already Made for Task 17

From the learnings document:
- Integration tests ARE feasible using test WorkflowManager
- Retry loops work correctly (not broken as initially thought)
- Use None for ResultPreparationNode return (not "complete")
- Test full flow execution, not just structure
- WorkflowManager via shared store enables complete test isolation

**📋 Note on Specifications**: Your subtask specification is the authoritative source. Follow it precisely - do not deviate from specified behavior, interface contracts, or implementation requirements unless you discover a critical issue (document and ask for clarification).

## Success Criteria

Your implementation is complete when:

✅ ResultPreparationNode exists and handles all 3 entry points
✅ create_planner_flow() properly wires all nodes
✅ Both Path A and Path B are correctly defined
✅ Retry loop from ValidatorNode to WorkflowGeneratorNode is wired
✅ Convergence at ParameterMappingNode works for both paths
✅ Full integration tests pass using test WorkflowManager
✅ Flow structure can be verified without execution
✅ make test passes (for your subtask's tests)
✅ make check passes
✅ Progress log documents your implementation journey

## Common Pitfalls to Avoid

- DON'T assume loops don't work - they do with 3-attempt limit
- DON'T skip integration tests - they're feasible with test WorkflowManager
- DON'T use Flow() >> node syntax - use Flow(start=node)
- DON'T forget empty string actions need explicit wiring
- DON'T return "complete" from ResultPreparationNode - return None
- DON'T test with production WorkflowManager - use test isolation

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent conflicts with other subtasks.

**Location**: `.taskmaster/tasks/task_17/subtask_6/implementation-plan.md`

### Why Planning Matters for Subtasks

1. **Prevents breaking interfaces**: All nodes are already implemented
2. **Identifies integration points**: Discover exact wiring needed
3. **Optimizes parallelization**: Know what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Node Analysis**
   - Task: "Analyze all nodes in src/pflow/planning/nodes.py and list their exact action strings"
   - Task: "Verify all 8 nodes are implemented and understand their interfaces"

2. **Test Pattern Discovery**
   - Task: "Examine tests/test_planning/ for existing test patterns and fixtures"
   - Task: "Find examples of PocketFlow flow testing in pocketflow/tests/"

3. **Integration Requirements**
   - Task: "Check how PocketFlow Flow class works in pocketflow/__init__.py"
   - Task: "Understand WorkflowManager usage pattern in shared store"

4. **Previous Implementation Analysis**
   - Task: "Review progress-log.md for insights from Subtasks 1-5"
   - Task: "Check for any flow-related code already implemented"
```

> Note: Your prompts to the subagents should be very specific and detailed, providing full Task 17 context.

### Step 2: Write Your Implementation Plan

Your plan should include:

1. **Node inventory** - Confirm all 8 nodes exist
2. **Action string mapping** - Document exact strings
3. **Flow wiring diagram** - Visual representation of edges
4. **Test strategy** - How to test with isolation
5. **Risk identification** - What could break

### Implementation Plan Template

```markdown
# Task 17 - Subtask 6 Implementation Plan

## Node Inventory

### Existing Nodes (from previous subtasks)
- [x] WorkflowDiscoveryNode - Returns: "found_existing" | "not_found"
- [x] ComponentBrowsingNode - Returns: "generate"
- [x] ParameterDiscoveryNode - Returns: ""
- [x] ParameterMappingNode - Returns: "params_complete" | "params_incomplete"
- [x] ParameterPreparationNode - Returns: ""
- [x] WorkflowGeneratorNode - Returns: "validate"
- [x] ValidatorNode - Returns: "metadata_generation" | "retry" | "failed"
- [x] MetadataGenerationNode - Returns: ""

### To Create
- [ ] ResultPreparationNode - Returns: None

## Flow Wiring Diagram
[ASCII diagram showing all edges]

## Implementation Steps

### Phase 1: ResultPreparationNode
[Detailed steps]

### Phase 2: Flow Creation
[Wiring details]

### Phase 3: Integration Testing
[Test strategy with WorkflowManager]

## Risk Mitigation

| Risk | Impact | Mitigation Strategy |
|------|--------|-------------------|
| Wrong action string | Flow breaks | Verify from code |
| Missing edge | Path incomplete | Test both paths |
```

### When to Revise Your Plan

Your plan is a living document. Update it when:
- You discover action strings differ from documentation
- Integration tests reveal missing edges
- Better test patterns emerge

Document plan changes in the SHARED progress log with rationale.

## Your Implementation Order

### 0. Review Shared Progress Log (FIRST!)

Check what previous subtasks have implemented: `.taskmaster/tasks/task_17/implementation/progress-log.md`

### 1. Create Your Implementation Plan (SECOND!)

Location: `.taskmaster/tasks/task_17/implementation/subtask-6/implementation-plan.md`

### Implementation Steps

1. Read subtask-6-complete-learnings.md for critical discoveries
2. Create ResultPreparationNode with 3 entry point handling
3. Write unit tests for ResultPreparationNode
4. Create flow.py with create_planner_flow()
5. Wire all Path A edges
6. Wire all Path B edges including retry loop
7. Export function in __init__.py
8. Create integration tests with test WorkflowManager
9. Test both paths completely
10. Test retry mechanism with controlled mocking
11. Create structural verification tests
12. Document retry mechanism in code comments

## Real-Time Learning Capture in SHARED Log

**AS YOU IMPLEMENT**, continuously append to the SHARED progress log:

```markdown
## [Timestamp] - Subtask 6 - Wiring retry loop
Attempting to connect ValidatorNode back to WorkflowGeneratorNode...

Result: Loop wired successfully
- ✅ What worked: validator_node - "retry" >> generator_node
- ✅ Confirmed: Retry mechanism will execute correctly
- 💡 Insight: PocketFlow loops work fine despite initial concerns

Code that worked:
```python
validator_node - "retry" >> generator_node  # This actually works!
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
## [Time] - Subtask 6 - DEVIATION FROM PLAN
- Original plan: Test without WorkflowManager
- Why it failed: No test isolation
- Impact on other subtasks: None - better testing for all
- New approach: Use test WorkflowManager via shared store
- Lesson: WorkflowManager in shared store enables perfect test isolation
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test the complete flow with isolation"

**Focus on**:
- Full planner execution (both paths)
- Test WorkflowManager for isolation
- Retry mechanism with controlled mocking
- All 3 ResultPreparationNode entry points
- Convergence at ParameterMappingNode

**What to test**:
- **Path A complete**: Discovery → Result with existing workflow
- **Path B complete**: Discovery → Generation → Result
- **Retry mechanism**: Controlled failure then success
- **Missing parameters**: Both paths handling incomplete params
- **Flow structure**: Verify all edges without execution

**Progress Log - Only document testing insights**:
```markdown
## {{time}} - Subtask 6 - Test WorkflowManager pattern discovered
Found that passing WorkflowManager via shared store enables complete test isolation.
This is a game-changer for integration testing!
```

**Remember**: Full integration tests are now feasible and required

## What NOT to Do

- DON'T use subagents to read any documentation mentioned in this prompt
- DON'T assume retry loops don't work - they do
- DON'T skip integration tests thinking they're impossible
- DON'T hardcode parameter values - use template variables
- DON'T modify existing node implementations
- DON'T use incorrect PocketFlow Flow syntax
- DON'T forget to wire empty string actions explicitly
- DON'T return "complete" from ResultPreparationNode
- DON'T test with production workflows - use test isolation

## Getting Started

1. Read PocketFlow documentation:
   - `pocketflow/__init__.py` - The framework source code
   - `pocketflow/docs/core_abstraction/flow.md` - Flow orchestration concepts
   - `pocketflow/docs/core_abstraction/node.md` - Node lifecycle patterns
   - `pocketflow/cookbook/pocketflow-flow/flow.py` - Practical flow example
   - Let subagents do additional research into pocketflow/docs/ and pocketflow/cookbook/ if needed if you still don't understand something
2. **Read the shared progress log**: `.taskmaster/tasks/task_17/implementation/progress-log.md` - See what Subtasks 1-5 implemented and learned
3. Read `.taskmaster/tasks/task_17/handoffs/handoff-to-subtask-6.md` for handoff context
4. Read `.taskmaster/tasks/task_17/handoffs/subtask-6-complete-learnings.md` for critical insights
5. Verify all 8 nodes exist in nodes.py
6. Create implementation plan
7. Start with ResultPreparationNode
8. Then create flow wiring
9. Finally create comprehensive tests

Test your specific components:
```bash
# Test just your new components
pytest tests/test_planning/test_result_preparation.py -xvs
pytest tests/test_planning/test_flow_structure.py -xvs

# Test full integration
pytest tests/test_planning/test_planner_integration.py -xvs

# Run all planning tests
make test-planning
```

## Final Notes

This subtask brings everything together. The orchestration you create enables the entire Natural Language Planner to function. Pay special attention to:
- Exact action strings (verified from code)
- Three entry points to ResultPreparationNode
- Convergence at ParameterMappingNode
- Retry loop that DOES work
- Test isolation with WorkflowManager

The learnings document contains critical discoveries - especially about testing. Full integration tests are feasible and should be comprehensive.

## Remember

You're implementing the orchestration layer that makes Task 17's Natural Language Planner complete. The two-path architecture with convergence at ParameterMappingNode is fully realized through your flow wiring. The retry mechanism works correctly with a 3-attempt limit. Test everything thoroughly using the WorkflowManager isolation pattern.

Your work completes the sophisticated meta-workflow that enables pflow's "Plan Once, Run Forever" philosophy. This is the culmination of all previous subtasks - wire it correctly and the entire planner springs to life!

## Your Success Enables Everything

Subtask 6 is where all the pieces come together. Your successful implementation means:
- Natural language can be transformed into workflows
- Both reuse and generation paths work seamlessly
- The convergence architecture proves its value
- pflow gains its core planning capability

Make it work, test it thoroughly, and document your journey. You're building the heart of Task 17!