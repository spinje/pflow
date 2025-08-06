# Task 17 - Subtask 4: Generation System - Agent Instructions

## Critical Pre-Requirement

**IMPORTANT**: This prompt assumes you have already thoroughly read and understand:
- All Task 17 documentation in `.taskmaster/tasks/task_17/`
- The epistemic manifesto
- The two-path architecture (Path A: reuse, Path B: generate)
- How subtasks interconnect and depend on each other
- The shared progress log system

If you haven't read these yet, STOP and read them first.

## The Problem You're Solving

The Natural Language Planner needs a creative engine that transforms browsed components and parameter hints into executable workflows. The generator must create workflows with template variables (not hardcoded values) and define proper input specifications that enable parameter verification at the convergence point. This is the node that turns user intent into structured, reusable workflows.

## Your Mission Within Task 17

Implement the WorkflowGeneratorNode that creates linear workflows with template variables from browsed components. This node is the creative heart of Path B, using LLM to generate workflows that are both executable and reusable through proper parameterization.

## ⚠️ Critical Context: Task 17's Two-Path Architecture

Before implementing this subtask, you MUST understand the overall architecture:

**Path A (Workflow Reuse)**: Discovery → ParameterMapping → Preparation → Result
**Path B (Workflow Generation)**: Discovery → Browsing → ParamDiscovery → **[YOUR GENERATOR]** → Validation → Metadata → ParameterMapping → Preparation → Result

**CONVERGENCE**: Both paths meet at ParameterMappingNode - the verification gate.

**This Subtask's Role**: Path B ONLY. Sits between ParameterDiscoveryNode (provides hints) and ValidatorNode (validates output). Creates workflows that will be verified at the convergence point.

## Dependencies and Prerequisites

### Subtasks That Must Be Complete
- ✅ Subtask 1 (Foundation): Provides directory structure, utilities, and FlowIR models
- ✅ Subtask 2 (Discovery): Provides ComponentBrowsingNode that selects components for generation
- ✅ Subtask 3 (Parameters): Provides ParameterDiscoveryNode that extracts parameter hints

### Files/Outputs You'll Use From Previous Subtasks
- `src/pflow/planning/ir_models.py` with FlowIR Pydantic model from Subtask 1
- `src/pflow/planning/nodes.py` with existing nodes and `_parse_structured_response()` pattern
- Test fixtures from `tests/test_planning/conftest.py`
- Discovery and browsing nodes that route to your generator

## Required Context Review

### Primary Source: Your Subtask Specification
**File**: `.taskmaster/tasks/task_17/starting-context/specs/task-17-subtask-4-spec.md`

**This is your PRIMARY source of truth** for requirements, interface contracts, and implementation details specific to Subtask 4.

Since you've already read all Task 17 documentation, focus on:
1. How your generator creates the inputs field that ParameterMappingNode will verify
2. Template variable requirements ($var syntax, never hardcode)
3. Linear workflow constraint (MVP - no branching)
4. Progressive enhancement on validation failures

**CRITICAL**: The spec defines exact behavior and interfaces. Follow it PRECISELY. Read it carefully and make sure you understand it before you start doing anything else.

### Key Documents to Reference (must read)
- `.taskmaster/tasks/task_17/handoffs/handoff-to-subtask-4.md` - What Subtask 3 provides you
- `.taskmaster/tasks/task_17/implementation/subtask-4/subtask-4-ambiguities-clarifications.md` - Critical design decisions

## 🔄 Shared Progress Log (CRITICAL!)

**The progress log is SHARED across ALL Task 17 subtasks!**

**Location**: `.taskmaster/tasks/task_17/implementation/progress-log.md`

**Format for your entries**:
```markdown
## [Timestamp] - Subtask 4 - [What You're Trying]
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
- Always prefix entries with "Subtask 4"
- Check previous subtask entries to understand what's already implemented
- Your insights help future subtasks avoid pitfalls
- Document the Anthropic response parsing pattern for others

## What You're Building

The WorkflowGeneratorNode that:
1. Receives parameter hints from ParameterDiscoveryNode
2. Uses planning context about browsed components
3. Generates workflows with template variables ($var, $var.field)
4. Defines inputs field with parameter specifications
5. Routes to "validate" for verification
6. Supports progressive enhancement on retry

Example usage within the planner:
```python
# Path B flow
discovery_node >> "not_found" >> browsing_node
browsing_node >> "generate" >> parameter_discovery_node
parameter_discovery_node >> "" >> generator_node  # YOUR NODE
generator_node >> "validate" >> validator_node
```

## Shared Store Contract

### Keys This Subtask READS
- `shared["user_input"]` - Natural language input from CLI
- `shared["discovered_params"]` - Parameter hints from ParameterDiscoveryNode (optional)
- `shared["browsed_components"]` - Selected node_ids and workflow_names
- `shared["planning_context"]` - Detailed markdown about components (required non-empty)
- `shared["validation_errors"]` - Previous validation errors if retry (optional)
- `shared["generation_attempts"]` - Number of previous attempts (optional, default 0)

### Keys This Subtask WRITES
- `shared["generated_workflow"]` - Complete workflow IR with inputs field
- `shared["generation_attempts"]` - Updated attempt count

### Expected Data Formats
```python
# Input
shared["discovered_params"] = {
    "filename": "report.csv",
    "limit": "20"
}

shared["browsed_components"] = {
    "node_ids": ["read-file", "llm", "write-file"],
    "workflow_names": ["text-analyzer"]
}

# Output
shared["generated_workflow"] = {
    "ir_version": "0.1.0",
    "inputs": {
        "input_file": {  # Renamed for clarity
            "description": "File to process",
            "required": True,
            "type": "string"
        },
        "max_items": {  # Renamed from limit
            "description": "Maximum items",
            "required": False,
            "type": "integer",
            "default": 100  # Universal default, NOT 20
        }
    },
    "nodes": [
        {"id": "read_data", "type": "read-file", "params": {"path": "$input_file"}},
        {"id": "process", "type": "llm", "params": {"prompt": "Process up to $max_items items"}}
    ],
    "edges": [
        {"from": "read_data", "to": "process"}
    ]
}
```

## Key Outcomes You Must Achieve

### Core Deliverables
- WorkflowGeneratorNode class in `src/pflow/planning/nodes.py`
- Comprehensive tests in `tests/test_planning/`
- Integration with existing nodes
- Proper logging and error handling

### Interface Requirements
- Must parse Anthropic response from `response_data['content'][0]['input']`
- Must use `_parse_structured_response()` helper method
- Must return "validate" action string
- Must handle empty planning_context as error

### Integration Points
- Receives flow from ParameterDiscoveryNode
- Routes to ValidatorNode via "validate" action
- Generated workflow used by ParameterMappingNode at convergence

## Implementation Strategy

### Phase 1: Core Node Structure (30 minutes)
1. Add WorkflowGeneratorNode class to nodes.py
2. Set `name = "generator"` as class attribute
3. Implement `__init__` with max_retries parameter
4. Import FlowIR from pflow.planning.ir_models
5. Add basic logging setup

### Phase 2: Main Logic Implementation (45 minutes)
1. Implement prep() to gather all inputs
2. Implement exec() with:
   - Planning context validation
   - Lazy model loading
   - Prompt building with template emphasis
   - LLM call with FlowIR schema
   - Response parsing with nested structure
3. Implement post() to store workflow and route
4. Implement exec_fallback() for error handling

### Phase 3: Testing and Integration (45 minutes)
1. Write unit tests for all methods
2. Test Anthropic response parsing
3. Test template variable generation
4. Integration test with ParameterMappingNode
5. Verify linear workflow constraint

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### Anthropic Response Parsing
The LLM response from Anthropic has a nested structure that MUST be parsed correctly:
```python
response_data = response.json()
if response_data is None:
    raise ValueError("LLM returned None response")
# CRITICAL: Structured data is nested here
result = response_data['content'][0]['input']
```

### Template Variable Requirements
The generator MUST emphasize template variables in the prompt:
```python
prompt = '''
CRITICAL Requirements:
1. Use template variables ($variable) for ALL dynamic values
2. NEVER hardcode values like "1234" - use $issue_number instead
3. Generate LINEAR workflow only - no branching
4. Template variables can use paths like $data.field.subfield
'''
```

### Parameter Renaming Freedom
You have complete freedom to rename parameters for clarity:
```python
# discovered_params might have: {"filename": "report.csv"}
# You can create better names in inputs:
"inputs": {
    "input_file": {  # Renamed from "filename"
        "description": "File to process",
        "required": True,
        "type": "string"
    }
}
# Templates must match YOUR inputs keys:
"params": {"path": "$input_file"}  # Not $filename
```

## Critical Warnings from Task 17 Experience

### Template Variables Are Sacred
**NEVER hardcode extracted values** - workflows must be reusable. When user says "20 issues", generate `"limit": "$limit"` NOT `"limit": "20"`.

### Understanding Your Path
You belong to Path B (generation) ONLY. You create workflows that will be validated, then converge at ParameterMappingNode where they're verified for executability.

### Linear Workflows Only
MVP constraint: Generate only linear workflows (A → B → C). No branching, no conditional edges, no error handling edges.

### Planning Context is Required
If planning_context is empty, that's an error. Don't try to generate without component information.

## Key Decisions Already Made for Task 17

From `.taskmaster/tasks/task_17/implementation/subtask-4/subtask-4-ambiguities-clarifications.md`:
- Planning context must be available (error if empty)
- Generator has full control over inputs specification
- Use discovered_params as hints only, not requirements
- Rename parameters for clarity when appropriate
- Universal defaults only (not request-specific values)
- No fallback workflow generation in exec_fallback
- Fix specific validation errors on retry (no simplification)
- Avoid multiple nodes of same type (shared store collision)

## Success Criteria

Your implementation is complete when:

✅ WorkflowGeneratorNode class exists in nodes.py with correct structure
✅ Name attribute set to "generator" for registry discovery
✅ Lazy model loading implemented in exec()
✅ Anthropic response parsing works with nested structure
✅ Generated workflows use template variables exclusively
✅ Inputs field properly defines parameter contract
✅ Linear workflows only (no branching)
✅ Planning context validation implemented
✅ Routes to "validate" correctly
✅ exec_fallback handles errors gracefully
✅ Integration with ParameterMappingNode verified
✅ make test passes (for your subtask's tests)
✅ make check passes
✅ Progress log documents your implementation journey

## Common Pitfalls to Avoid

- DON'T hardcode parameter values - use template variables
- DON'T forget the nested Anthropic response structure
- DON'T generate branching workflows (MVP constraint)
- DON'T use discovered_params keys directly - rename for clarity
- DON'T create fallback workflows in exec_fallback
- DON'T validate node types - trust planning context
- DON'T use registry_metadata - ignore it completely
- DON'T set defaults to request-specific values

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent conflicts with other subtasks.

**Location**: `.taskmaster/tasks/task_17/implementation/subtask-4/implementation-plan.md`

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Previous Subtask Analysis**
   - Task: "Analyze ParameterDiscoveryNode output format in nodes.py"
   - Task: "Check how discovered_params is structured from Subtask 3"

2. **Interface Discovery**
   - Task: "Identify how ValidatorNode expects generated_workflow structure"
   - Task: "Analyze ParameterMappingNode to understand inputs field requirements"

3. **Testing Pattern Analysis**
   - Task: "Examine tests/test_planning/ for LLM mocking patterns"
   - Task: "Find test fixtures for Anthropic response structure"

4. **Integration Requirements**
   - Task: "Check how ValidatorNode validates the generated workflow"
   - Task: "Verify FlowIR model structure in ir_models.py"
```

### Step 2: Write Your Implementation Plan

Include interface verification, component breakdown, integration strategy, risk identification, and testing approach.

## Your Implementation Order

### 0. Review Shared Progress Log (FIRST!)

Check what previous subtasks have implemented: `.taskmaster/tasks/task_17/implementation/progress-log.md`

### 1. Create Your Implementation Plan (SECOND!)

Location: `.taskmaster/tasks/task_17/implementation/subtask-4/implementation-plan.md`

### Implementation Steps

1. Read the subtask specification thoroughly
2. Review handoff document from Subtask 3
3. Create implementation plan with subagent research
4. Add WorkflowGeneratorNode to nodes.py
5. Implement core methods (prep, exec, post, exec_fallback)
6. Add _parse_structured_response if not inherited
7. Write comprehensive tests with test-writer-fixer
8. Integration test with ParameterMappingNode
9. Verify linear workflow generation
10. Document insights in shared progress log

## Real-Time Learning Capture in SHARED Log

**AS YOU IMPLEMENT**, continuously append to the SHARED progress log:

```markdown
## [Timestamp] - Subtask 4 - Implementing WorkflowGeneratorNode
Attempting to generate workflow with template variables...

Result: Successfully generated linear workflow
- ✅ What worked: LLM reliably generates template variables when prompted explicitly
- ❌ What failed: Initial attempt hardcoded values until prompt was strengthened
- 💡 Insight: Must emphasize "NEVER hardcode" multiple times in prompt

Code that worked:
```python
prompt = '''
CRITICAL: Use template variables ($var) for ALL dynamic values
NEVER hardcode values like "1234" - use $variable instead
'''
```
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Consider impact on ValidatorNode (Subtask 5)
4. Update the plan with new approach
5. Continue with new understanding

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks.

**What to test**:
- Template variable generation (never hardcoded)
- Linear workflow constraint (no branching)
- Anthropic response parsing
- Planning context validation
- Parameter renaming logic
- Integration with ParameterMappingNode

**Critical test**:
```python
def test_template_variables_not_hardcoded():
    """Ensure generator NEVER hardcodes discovered param values."""
    # If discovered_params has {"limit": "20"}
    # Generated workflow must have "$limit" not "20"
```

## What NOT to Do

- DON'T hardcode any values from discovered_params
- DON'T generate branching workflows (edges with action field)
- DON'T create multiple nodes of same type
- DON'T skip the nested Anthropic response parsing
- DON'T use discovered_params keys without considering renaming
- DON'T validate against registry - trust planning context
- DON'T generate fallback workflows in exec_fallback
- DON'T modify shared store keys from other subtasks

## Getting Started

1. Read `.taskmaster/tasks/task_17/starting-context/specs/task-17-subtask-4-spec.md`
2. Review `.taskmaster/tasks/task_17/handoffs/handoff-to-subtask-4.md`
3. Check progress log for Subtask 3 insights
4. Create your implementation plan
5. Start with node class structure
6. Test with: `pytest tests/test_planning/test_generation.py -xvs`

## Final Notes

Remember that your generator is the creative engine of Path B. The workflows you generate will be validated, then converge at ParameterMappingNode where they're verified for executability. Your use of template variables enables the "Plan Once, Run Forever" philosophy.

The inputs field you create is the contract that ParameterMappingNode will verify. Make it clear, well-structured, and use descriptive names that improve on the raw discovered parameters.

## Remember

You're implementing the creative heart of Path B - the node that transforms user intent into executable workflows. Your generator bridges the gap between parameter discovery and validation, creating workflows that are both powerful and reusable through proper parameterization.

The two-path architecture depends on your generator creating workflows that can pass validation and meet at the convergence point. Your work enables natural language to become permanent, deterministic CLI commands.

You're implementing Subtask 4 of 7 for Task 17's Natural Language Planner. Your generator is what makes Path B possible - turning browsed components and parameter hints into real, executable workflows. Make them clean, linear, and properly parameterized.

Good luck! The generator you build will be the creative engine that powers pflow's natural language capabilities.
