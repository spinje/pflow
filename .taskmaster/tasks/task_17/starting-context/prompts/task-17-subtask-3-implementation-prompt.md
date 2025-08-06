# Task 17 - Subtask 3: Parameter Management System - Agent Instructions

## Critical Pre-Requirement

**IMPORTANT**: This prompt assumes you have already thoroughly read and understand:
- All Task 17 documentation in `.taskmaster/tasks/task_17/`
- The epistemic manifesto
- The two-path architecture (Path A: reuse, Path B: generate)
- How subtasks interconnect and depend on each other
- The shared progress log system

If you haven't read these yet, STOP and read them first.

## The Problem You're Solving

The Natural Language Planner needs sophisticated two-phase parameter handling that enables both execution paths to converge at a verification point. Parameters must be discovered early in Path B to inform generation, then ALL parameters must be independently verified for executability at the convergence point where both paths meet. This independent verification ensures workflows can actually execute with the user's input, regardless of which path was taken.

## Your Mission Within Task 17

Implement the parameter management nodes that create the convergence architecture - where Path A (workflow reuse) and Path B (workflow generation) meet at ParameterMappingNode. This is THE critical verification gate that ensures workflows have all required parameters before execution.

## ⚠️ Critical Context: Task 17's Two-Path Architecture

Before implementing this subtask, you MUST understand the overall architecture:

**Path A (Workflow Reuse)**: Discovery → ParameterMapping → Preparation → Result
**Path B (Workflow Generation)**: Discovery → Browsing → ParamDiscovery → Generation → Validation → Metadata → ParameterMapping → Preparation → Result

**CONVERGENCE**: Both paths meet at ParameterMappingNode - the verification gate.

**This Subtask's Role**: Creates the convergence point and two-phase parameter architecture. ParameterDiscoveryNode runs ONLY in Path B before generation. ParameterMappingNode runs in BOTH paths as the convergence point. ParameterPreparationNode formats the final parameters for execution.

## Dependencies and Prerequisites

### Subtasks That Must Be Complete
- ✅ Subtask 1 (Foundation): Provides directory structure, utilities, Pydantic models, and test infrastructure
- ✅ Subtask 2 (Discovery): Provides WorkflowDiscoveryNode and ComponentBrowsingNode that route to parameter nodes

### Files/Outputs You'll Use From Previous Subtasks
- `src/pflow/planning/nodes.py` with WorkflowDiscoveryNode and ComponentBrowsingNode
- `src/pflow/planning/utils/workflow_loader.py` from Subtask 1
- `src/pflow/planning/ir_models.py` with FlowIR Pydantic models
- Test fixtures from `tests/test_planning/conftest.py`
- `_parse_structured_response()` helper method in nodes.py (line 153)

## Required Context Review

### Primary Source: Your Subtask Specification
**File**: `.taskmaster/tasks/task_17/starting-context/specs/task-17-subtask-3-spec.md`

**This is your PRIMARY source of truth** for requirements, interface contracts, and implementation details specific to Subtask 3.

### Handoff Documentation
**File**: `.taskmaster/tasks/task_17/handoffs/handoff-to-subtask-3.md`

The previous implementer left critical discoveries and patterns that will save you hours. It contains hard-won insights about nested LLM responses, lazy loading requirements, and the convergence architecture.

Since you've already read all Task 17 documentation, focus on:
1. How your subtask's spec relates to the overall architecture
2. Dependencies listed in the spec vs what's actually implemented
3. Interface contracts specific to your subtask
4. Success criteria unique to this subtask

**CRITICAL**: The spec defines exact behavior and interfaces. Follow it PRECISELY. Read it carefully and make sure you understand it before you start doing anything else.

## 🔄 Shared Progress Log (CRITICAL!)

**The progress log is SHARED across ALL Task 17 subtasks!**

**Location**: `.taskmaster/tasks/task_17/implementation/progress-log.md`

**Format for your entries**:
```markdown
## [Timestamp] - Subtask 3 - [What You're Trying]
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

You're implementing three critical nodes that handle parameter extraction and verification:

1. **ParameterDiscoveryNode** (Path B only):
   - Analyzes natural language to extract named parameters BEFORE generation
   - Provides hints to the generator about what parameters are available
   - Example: "last 20 closed issues" → `{"limit": "20", "state": "closed"}`

2. **ParameterMappingNode** (BOTH paths - convergence point):
   - Does INDEPENDENT extraction (doesn't trust discovered_params)
   - Validates against workflow's `inputs` field
   - Routes "params_complete" or "params_incomplete"
   - This is THE verification gate

3. **ParameterPreparationNode**:
   - Formats extracted_params into execution_params
   - In MVP, mostly pass-through (prepares for future transformations)
   - Runs after successful parameter mapping

Example usage within the planner:
```python
# Path B: Discovery provides context for generation
discovery_node >> param_discovery >> generator
# Discovery node extracts: {"state": "closed", "limit": "20"}
# Generator uses this to create workflow with $state and $limit

# Both paths converge at mapping
param_mapping - "params_complete" >> param_preparation >> result
param_mapping - "params_incomplete" >> result  # Missing params
```

## Shared Store Contract

### Keys This Subtask READS
- `shared["user_input"]` - Natural language input from CLI
- `shared["stdin"]` - Text data piped from stdin (fallback parameter source)
- `shared["stdin_binary"]` - Binary stdin data if present
- `shared["stdin_path"]` - Temp file path for large stdin
- `shared["browsed_components"]` - Selected components from ComponentBrowsingNode (Path B)
- `shared["planning_context"]` - Detailed markdown OR empty string (Path B)
- `shared["registry_metadata"]` - Full registry dict for validation (Path B)
- `shared["found_workflow"]` - Existing workflow from discovery (Path A)
- `shared["generated_workflow"]` - Generated workflow from GeneratorNode (Path B, future)
- `shared["workflow_metadata"]` - Display/storage metadata (Path B, future)

### Keys This Subtask WRITES
- `shared["discovered_params"]` - Parameter hints for generation (ParameterDiscoveryNode)
- `shared["extracted_params"]` - Actual parameter values found (ParameterMappingNode)
- `shared["execution_params"]` - Final parameters ready for workflow execution
- `shared["missing_params"]` - List of missing required parameters (only when incomplete)

### Expected Data Formats
```python
# ParameterDiscoveryNode output
shared["discovered_params"] = {
    "state": "closed",
    "limit": "20"
    # Simple dict mapping parameter names to values
}

# ParameterMappingNode outputs
shared["extracted_params"] = {
    "filename": "report.csv",
    "data": {"field": "value"}  # For template path access
}

shared["missing_params"] = ["output_format", "delimiter"]  # When incomplete

# ParameterPreparationNode output
shared["execution_params"] = {
    "filename": "report.csv",
    "data": {"field": "value"}
    # In MVP, same as extracted_params
}
```

## Key Outcomes You Must Achieve

### Core Deliverables
1. Three nodes added to existing `src/pflow/planning/nodes.py`
2. Pydantic models for parameter structures (in nodes.py)
3. Independent extraction logic in ParameterMappingNode
4. Comprehensive tests showing both paths work
5. Updated shared progress log with implementation journey

### Interface Requirements
- ParameterDiscoveryNode must return to continue Path B
- ParameterMappingNode must route "params_complete" or "params_incomplete"
- ParameterPreparationNode must return to result
- All nodes must handle missing/empty inputs gracefully

### Integration Points
- Path A: WorkflowDiscoveryNode → ParameterMappingNode
- Path B: ComponentBrowsingNode → ParameterDiscoveryNode → (future nodes) → ParameterMappingNode
- Both paths: ParameterMappingNode → ParameterPreparationNode → ResultPreparationNode (future)

## Implementation Strategy

### Phase 1: Core Node Implementation (2-3 hours)
1. Read existing nodes.py to understand patterns
2. Create Pydantic models for parameter structures
3. Implement ParameterDiscoveryNode with LLM extraction
4. Implement ParameterMappingNode with independent extraction
5. Implement ParameterPreparationNode as pass-through
6. Add proper logging to all nodes

### Phase 2: Integration and Routing (1-2 hours)
1. Ensure correct action strings returned
2. Test routing from discovery nodes
3. Verify shared store keys read/written correctly
4. Add exec_fallback for error recovery

### Phase 3: Testing and Validation (2-3 hours)
1. Create comprehensive tests for all three nodes
2. Test both Path A and Path B scenarios
3. Test missing parameters trigger "params_incomplete"
4. Test stdin fallback for parameters
5. Integration tests with discovery nodes

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### Nested LLM Response Extraction
The Anthropic API nests structured data in a specific format. You MUST use this pattern:
```python
# Use the existing helper method
structured_data = self._parse_structured_response(response_data)

# Or if implementing directly:
response = model.prompt(prompt, schema=YourModel)
response_data = response.json()
if response_data is None:
    raise ValueError("LLM returned None response")
# Extract from nested structure
structured_data = response_data['content'][0]['input']
```

### Lazy Model Loading Pattern
Models must be loaded in exec(), not __init__():
```python
class ParameterDiscoveryNode(Node):
    def __init__(self, **params):
        super().__init__(**params)
        # DO NOT load model here

    def exec(self, prep_res):
        # Load model here
        model_name = prep_res.get("model_name", self.params.get("model", "anthropic/claude-sonnet-4-0"))
        model = llm.get_model(model_name)
        temperature = prep_res.get("temperature", self.params.get("temperature", 0.0))
```

### Independent Extraction in ParameterMappingNode
This node MUST NOT rely on discovered_params:
```python
def exec(self, prep_res):
    # Extract from scratch - don't use discovered_params
    user_input = prep_res["user_input"]
    workflow_ir = prep_res.get("workflow_ir", {})

    # Fresh extraction based on workflow's declared inputs
    inputs_spec = workflow_ir.get("inputs", {})
    extracted = self._extract_params_for_inputs(user_input, inputs_spec)

    # Verify all required params present
    missing = self._find_missing_required(extracted, inputs_spec)

    return {
        "extracted_params": extracted,
        "missing_params": missing,
        "complete": len(missing) == 0
    }
```

## Critical Warnings from Task 17 Experience

### Template Variables Are Sacred
**NEVER hardcode extracted values** - workflows must be reusable. When user says "20 issues", the workflow should have `"limit": "$limit"` NOT `"limit": "20"`. Your job is to extract the value "20" for the parameter "limit", not to modify workflows.

### Understanding Your Path
ParameterDiscoveryNode is Path B ONLY. ParameterMappingNode is the convergence point for BOTH paths. Know your role in the architecture.

### Planning Context Can Be Empty
ComponentBrowsingNode might write empty string to `shared["planning_context"]` if an error occurred. Handle this gracefully:
```python
planning_context = shared.get("planning_context", "")
if not planning_context:  # Could be empty string on error
    # Work with what you have
```

## Key Decisions Already Made for Task 17

1. **LLM Model**: Using anthropic/claude-sonnet-4-0 as default, configurable via params
2. **Retry Strategy**: max_retries=2 for consistency with existing nodes
3. **Template Syntax**: Support $var and $data.field notation only (no array indexing)
4. **Parameter Independence**: ParameterMappingNode does fresh extraction for verification
5. **Workflow IR Structure**: Uses `inputs` field with `required`, `type`, `description` per input
6. **Python Booleans**: Use True/False in code (becomes true/false in JSON automatically)

**📋 Note on Specifications**: Your subtask specification is the authoritative source. Follow it precisely - do not deviate from specified behavior, interface contracts, or implementation requirements unless you discover a critical issue (document and ask for clarification).

## Success Criteria

Your implementation is complete when:

✅ All three nodes added to existing nodes.py file
✅ ParameterDiscoveryNode extracts named parameters from natural language
✅ ParameterMappingNode does independent extraction and validation
✅ ParameterPreparationNode formats parameters for execution
✅ Correct routing: "params_complete" when all required params found
✅ Correct routing: "params_incomplete" when missing required params
✅ Template syntax ($var and $data.field) properly supported
✅ Stdin checked as fallback parameter source
✅ Both Path A and Path B scenarios tested
✅ Integration with discovery nodes verified
✅ make test passes (for your subtask's tests)
✅ make check passes
✅ Progress log documents your implementation journey

## Common Pitfalls to Avoid

1. **DON'T trust discovered_params in ParameterMappingNode** - It must do independent extraction
2. **DON'T hardcode parameter values** - Preserve template variables in workflows
3. **DON'T load models in __init__** - Always lazy-load in exec()
4. **DON'T forget nested response extraction** - Use `response_data['content'][0]['input']`
5. **DON'T skip exec_fallback** - All nodes need error recovery
6. **DON'T modify workflow IR** - Your job is parameter extraction, not workflow modification
7. **DON'T assume planning_context exists** - It might be empty string
8. **DON'T forget to check stdin** - It's a fallback parameter source

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent conflicts with other subtasks.

**Location**: `.taskmaster/tasks/task_17/subtask_3/implementation-plan.md`

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
   - Task: "Analyze outputs from Subtask 2 (Discovery) and identify how they route to parameter nodes"
   - Task: "Check shared store keys written by discovery nodes"

2. **Interface Discovery**
   - Task: "Identify how ParameterMappingNode serves as convergence point for both paths"
   - Task: "Analyze expected workflow IR structure with inputs field"

3. **Testing Pattern Analysis**
   - Task: "Examine tests/test_planning/test_discovery.py for testing patterns"
   - Task: "Identify test fixtures from conftest.py we can reuse"

4. **Integration Requirements**
   - Task: "Check how parameter nodes' outputs are used by future subtasks"
   - Task: "Verify shared store contract for discovered_params and execution_params"
```

> Note: Your prompts to the subagents should be very specific and detailed, providing full Task 17 context.

### Step 2: Write Your Implementation Plan

Your plan should include:

1. **Interface verification** - Confirm what discovery nodes provide
2. **Component breakdown** - Every node's specific responsibilities
3. **Integration strategy** - How to connect as convergence point
4. **Risk identification** - What could break the two-path architecture
5. **Testing strategy** - How to verify both paths work

### Implementation Plan Template

```markdown
# Task 17 - Subtask 3 Implementation Plan

## Dependencies Verified

### From Previous Subtasks
- WorkflowDiscoveryNode routes "found_existing" (Path A) or "not_found" (Path B)
- ComponentBrowsingNode provides browsed_components and planning_context
- Test fixtures and LLM mocking patterns available

### For Next Subtasks
- discovered_params for GeneratorNode context (Path B)
- execution_params for final workflow execution
- Convergence point established for both paths

## Shared Store Contract
- Reads: user_input, stdin, found_workflow (A), generated_workflow (B)
- Writes: discovered_params, extracted_params, execution_params, missing_params

## Implementation Steps

### Phase 1: Core Components
1. Create Pydantic models for parameter structures
2. Implement ParameterDiscoveryNode with LLM extraction
3. Implement ParameterMappingNode with independent extraction
4. Implement ParameterPreparationNode as pass-through

### Phase 2: Integration
1. Connect to discovery node routing
2. Establish convergence point logic
3. Verify action strings

### Phase 3: Testing
1. Test Path A scenarios
2. Test Path B scenarios
3. Test convergence behavior

## Risk Mitigation

| Risk | Impact on Other Subtasks | Mitigation Strategy |
|------|-------------------------|-------------------|
| Wrong routing | Breaks flow | Test action strings thoroughly |
| Dependent extraction | Invalid verification | Ensure independence |
| Missing stdin check | Incomplete params | Test fallback logic |

## Validation Strategy
- Verify routing from discovery nodes works
- Ensure both paths converge correctly
- Test parameter extraction independence
```

### When to Revise Your Plan

Your plan is a living document. Update it when:
- You discover interface mismatches with discovery nodes
- Integration tests reveal routing issues
- The convergence architecture needs adjustment

Document plan changes in the SHARED progress log with rationale.

## Your Implementation Order

### 0. Review Shared Progress Log (FIRST!)

Check what previous subtasks have implemented: `.taskmaster/tasks/task_17/implementation/progress-log.md`

### 1. Create Your Implementation Plan (SECOND!)

Location: `.taskmaster/tasks/task_17/implementation/subtask-3/implementation-plan.md`

### Implementation Steps

1. Read and understand existing nodes.py patterns
2. Create Pydantic models for parameter extraction
3. Implement ParameterDiscoveryNode with LLM-based extraction
4. Implement ParameterMappingNode with independent extraction logic
5. Implement ParameterPreparationNode as simple pass-through
6. Add comprehensive logging to track parameter flow
7. Test Path A routing (found_workflow → mapping)
8. Test Path B routing (browsing → discovery → mapping)
9. Verify convergence point behavior
10. Integration test with discovery nodes
11. Document insights in shared progress log

## Real-Time Learning Capture in SHARED Log

**AS YOU IMPLEMENT**, continuously append to the SHARED progress log:

```markdown
## [Timestamp] - Subtask 3 - Parameter extraction pattern discovered
Attempting to extract parameters from natural language...

Result: LLM can identify parameter names intelligently
- ✅ What worked: Using examples in prompt helps LLM understand parameter naming
- ❌ What failed: Simple regex patterns miss context
- 💡 Insight: Parameter names should match workflow's expected inputs

Code that worked:
```python
prompt = f"""Extract parameters with names from: "{user_input}"
Examples:
- "20 closed issues" → {{"limit": "20", "state": "closed"}}
- "report.csv file" → {{"filename": "report.csv"}}
"""
```
```

**Remember**: Your insights help future subtasks!

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Consider impact on convergence architecture
4. Update the plan with new approach
5. Continue with new understanding

Append deviation to SHARED progress log:
```markdown
## [Time] - Subtask 3 - DEVIATION FROM PLAN
- Original plan: Use discovered_params in mapping
- Why it failed: Breaks verification independence
- Impact on other subtasks: None - internal to parameter management
- New approach: Fresh extraction in ParameterMappingNode
- Lesson: Independence ensures verification integrity
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test the convergence architecture"

**Focus on**:
- Both paths reaching ParameterMappingNode correctly
- Independent extraction in mapping node
- Missing required parameters trigger "params_incomplete"
- Template syntax parsing ($var and $data.field)
- Stdin fallback when parameters missing from user_input

**What to test**:
- **Path A**: found_workflow → mapping → preparation
- **Path B**: browsing → discovery → (future) → mapping → preparation
- **Convergence**: Both paths handle parameters correctly
- **Independence**: Mapping doesn't rely on discovered_params
- **Validation**: Missing required params detected

**Progress Log - Only document testing insights**:
```markdown
## [Time] - Subtask 3 - Testing revealed convergence issue
Discovered that Path A and Path B need different prep logic in ParameterMappingNode.
Path A has found_workflow, Path B will have generated_workflow.
Need to handle both cases.
```

**Remember**: Integration tests > isolated unit tests for convergence architecture

## What NOT to Do

- DON'T modify workflow IR - preserve template variables
- DON'T trust discovered_params in ParameterMappingNode - do fresh extraction
- DON'T skip stdin checking - it's a fallback source
- DON'T load models in __init__ - always lazy-load
- DON'T forget nested response extraction pattern
- DON'T break the convergence architecture - both paths must work
- DON'T hardcode parameter values - keep workflows reusable
- DON'T skip integration testing with discovery nodes

## Getting Started

1. Open and read `.taskmaster/tasks/task_17/implementation/progress-log.md`
2. Review existing `src/pflow/planning/nodes.py` for patterns
3. Check the `_parse_structured_response()` helper method
4. Create your implementation plan at `.taskmaster/tasks/task_17/implementation/subtask-3/implementation-plan.md`
5. Start with ParameterDiscoveryNode (simplest)
6. Move to ParameterMappingNode (most critical)
7. Finish with ParameterPreparationNode (pass-through)
8. Test both paths thoroughly
9. Document everything in shared progress log

## Final Notes

The convergence architecture is what makes Task 17's planner reliable. Your ParameterMappingNode is THE critical verification gate that ensures workflows can actually execute. The two-phase approach (discovery then mapping) provides both context for generation AND verification for execution.

Remember that discovered_params is for the generator's benefit, but ParameterMappingNode must do its own extraction to maintain verification integrity. This independence is a feature, not redundancy.

## Remember

You're implementing the convergence point of Task 17's sophisticated meta-workflow. ParameterMappingNode is where both execution paths meet and verify that workflows have all required parameters. This is the keystone of the entire planner architecture.

The two-phase parameter handling enables intelligent generation (via discovery) while maintaining strict verification (via independent mapping). Your work ensures that every workflow - whether reused or generated - can actually execute with the user's input.

You're building the bridge between discovery and execution. Your nodes ensure that pflow's "Plan Once, Run Forever" philosophy actually works by verifying that workflows have everything they need to run. This is critical infrastructure for the Natural Language Planner.

Good luck implementing the Parameter Management System - it's the heart of Task 17's convergence architecture!
