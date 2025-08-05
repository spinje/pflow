# Task 17 - Subtask 3: Generation & Validation Nodes - Agent Instructions

## Critical Pre-Requirement

**IMPORTANT**: This prompt assumes you have already thoroughly read and understand:
- All Task 17 documentation in `.taskmaster/tasks/task_17/`
- The epistemic manifesto
- The two-path architecture (Path A: reuse, Path B: generate)
- How subtasks interconnect and depend on each other
- The shared progress log system

If you haven't read these yet, STOP and read them first.

## The Problem You're Solving

The Natural Language Planner needs to generate executable workflows when no existing workflow matches the user's request. This requires LLM-based generation with sophisticated retry logic and two-phase validation to ensure both structural correctness and template variable usage. The generation system must produce reusable workflows with template variables, not hardcoded values.

## Your Mission Within Task 17

Implement the core workflow generation system for Path B, including the generator node with smart retry, the two-phase validator, and metadata extraction. These nodes transform planning context into validated, executable workflow IR.

## ⚠️ Critical Context: Task 17's Two-Path Architecture

Before implementing this subtask, you MUST understand the overall architecture:

**Path A (Workflow Reuse)**: Discovery → ParameterMapping → Preparation → Result
**Path B (Workflow Generation)**: Discovery → Browsing → ParamDiscovery → Generation → Validation → Metadata → ParameterMapping → Preparation → Result

**CONVERGENCE**: Both paths meet at ParameterMappingNode - the verification gate.

**This Subtask's Role**: Core of Path B - transforms planning context and components into validated workflow IR. The retry loop between Generator and Validator ensures progressive enhancement until valid workflow is produced or max retries reached.

## Dependencies and Prerequisites

### Subtasks That Must Be Complete
- ✅ Subtask 1 (Foundation): Provides directory structure, utilities, and Pydantic models
- ✅ Subtask 2 (Discovery): Provides ComponentBrowsingNode that outputs planning_context

### Files/Outputs You'll Use From Previous Subtasks
- `src/pflow/planning/ir_models.py` from Subtask 1 (NodeIR, EdgeIR, FlowIR)
- `src/pflow/planning/nodes.py` from Subtask 2 (adds to this file)
- `tests/test_planning/conftest.py` from Subtask 1 (test fixtures)
- ComponentBrowsingNode's `shared["planning_context"]` output

## Required Context Review

### Primary Source: Your Subtask Specification
**File**: `.taskmaster/tasks/task_17/starting-context/specs/task-17-subtask-3-spec.md`

**This is your PRIMARY source of truth** for requirements, interface contracts, and implementation details specific to Subtask 3.

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

Three interconnected nodes that form the generation and validation core of Path B:

1. **WorkflowGeneratorNode**: Uses LLM with structured output to generate workflow IR from planning context
2. **ValidatorNode**: Two-phase validation (structure + templates) with retry routing
3. **MetadataGenerationNode**: Extracts workflow metadata for discovery and reuse

Example usage within the planner:
```python
# In Path B flow (will be wired in Subtask 6):
generator = WorkflowGeneratorNode()
validator = ValidatorNode()
metadata = MetadataGenerationNode()

# Retry loop configuration
flow >> generator >> validator
validator - "invalid" >> generator  # Retry with feedback
validator - "valid" >> metadata      # Success path
validator - "failed" >> error_handler # Max retries exceeded
```

## Shared Store Contract

### Keys This Subtask READS
- `shared["user_input"]` - Natural language input from CLI
- `shared["planning_context"]` - Markdown context from ComponentBrowsingNode
- `shared["discovered_params"]` - Parameters from ParameterDiscoveryNode (empty dict initially)
- `shared["generation_attempts"]` - Counter for retry tracking
- `shared["validation_errors"]` - Previous template validation errors (list)
- `shared["validation_error"]` - Previous structure validation error (dict)

### Keys This Subtask WRITES
- `shared["generated_workflow"]` - Complete JSON IR workflow
- `shared["generation_attempts"]` - Updated attempt counter
- `shared["validation_errors"]` - Template validation errors for retry
- `shared["validation_error"]` - Structure validation error details
- `shared["workflow_metadata"]` - Extracted metadata (name, description, inputs, outputs)

### Expected Data Formats
```python
shared["generated_workflow"] = {
    "ir_version": "0.1.0",
    "nodes": [
        {
            "id": "llm-1",
            "type": "llm",
            "params": {
                "prompt": "Analyze these issues:\n$issues",  # Template variable!
                "model": "$model"  # Template variable!
            }
        }
    ],
    "edges": [...],
    "inputs": {"issues": "list", "model": "str"},
    "outputs": {"analysis": "str"}
}

shared["validation_errors"] = [
    "Node 'llm-1' param 'issues' has hardcoded value '20'. Use template variable like '$issues'",
    "Missing template variable for parameter 'model'"
]

shared["workflow_metadata"] = {
    "suggested_name": "analyze-github-issues",
    "description": "Analyzes GitHub issues using LLM",
    "inputs": ["issues", "model"],
    "outputs": ["analysis"]
}
```

## Key Outcomes You Must Achieve

### Core Deliverables
1. Add three node classes to `src/pflow/planning/nodes.py`
2. Implement smart retry logic with progressive enhancement
3. Create two-phase validation (structure + templates)
4. Extract workflow metadata for discovery
5. Comprehensive tests for all nodes and retry behavior

### Interface Requirements
- WorkflowGeneratorNode always outputs to ValidatorNode
- ValidatorNode routes based on validation results ("valid", "invalid", "failed")
- MetadataGenerationNode prepares workflow for storage/discovery
- All nodes must handle missing/malformed inputs gracefully

### Integration Points
- Uses Pydantic models from `ir_models.py` for structured LLM output
- Integrates with existing `validate_ir()` and `TemplateValidator`
- Connects to ParameterDiscoveryNode output (initially empty dict)
- Feeds into ParameterMappingNode (Subtask 5) via metadata

## Implementation Strategy

### Phase 1: Core Node Implementation (2 hours)
1. Add imports to `nodes.py` (llm, validate_ir, TemplateValidator)
2. Implement WorkflowGeneratorNode with basic prompt building
3. Implement ValidatorNode with two-phase validation
4. Implement MetadataGenerationNode with simple extraction
5. Add comprehensive logging throughout

### Phase 2: Smart Retry Logic (1.5 hours)
1. Enhance WorkflowGeneratorNode prompt building for retries
2. Add progressive enhancement based on attempt number
3. Implement proper error context passing
4. Test retry loop behavior with mocked LLM

### Phase 3: Integration & Testing (1.5 hours)
1. Add integration tests with ComponentBrowsingNode output
2. Test empty discovered_params handling
3. Verify template validation with Registry
4. Test all routing paths (valid, invalid, failed)
5. Run `make test` and `make check`

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### LLM Response Parsing
The llm library returns a response object. Parse with:
```python
response = self.model.prompt(prompt, schema=FlowIR, temperature=0)
workflow_dict = json.loads(response.text())  # NOT response.json()
```

### ValidationError Structure
The ValidationError from validate_ir has specific attributes:
```python
try:
    validate_ir(workflow)
except ValidationError as e:
    error_dict = {
        "path": e.path,        # Direct attribute access
        "message": e.message,  # NOT str(e)
        "suggestion": e.suggestion
    }
```

### Template Validation Returns List
TemplateValidator.validate_workflow_templates returns a list of error strings:
```python
errors = TemplateValidator.validate_workflow_templates(
    workflow, params, self.registry
)
if errors:  # List of strings, empty if valid
    # Handle template errors
```

### Progressive Retry Enhancement
Attempt 1: Basic generation with planning context
Attempt 2: Add validation errors to prompt for targeted fixes
Attempt 3: Emphasize template variables and basic nodes

## Critical Warnings from Task 17 Experience

### Template Variables Are Sacred
**NEVER hardcode extracted values** - workflows must be reusable. When user says "20 issues", generate `"limit": "$limit"` NOT `"limit": "20"`.

### Understanding Your Path
Your nodes are the CORE of Path B. Without successful generation and validation, no new workflows can be created.

### Two Error Formats
ValidatorNode handles two different error types:
- Structure errors: Single ValidationError with path/message/suggestion
- Template errors: List of human-readable error strings

Store them in DIFFERENT shared store keys for clarity.

## Key Decisions Already Made for Task 17

1. **LLM Model**: Use `anthropic/claude-sonnet-4-0` for all planner nodes
2. **Max Retries**: 3 attempts before routing to "failed"
3. **Temperature**: Always 0 for deterministic output
4. **Error Storage**: Separate keys for structure vs template errors
5. **Walking Skeleton**: Start with simple implementations, enhance iteratively

**📋 Note on Specifications**: Your subtask specification is the authoritative source. Follow it precisely - do not deviate from specified behavior, interface contracts, or implementation requirements unless you discover a critical issue (document and ask for clarification).

## Success Criteria

Your implementation is complete when:

✅ WorkflowGeneratorNode generates valid JSON IR with template variables
✅ ValidatorNode correctly identifies both structure and template errors
✅ Retry loop provides progressive enhancement with error feedback
✅ MetadataGenerationNode extracts basic workflow metadata
✅ All three nodes added to existing `nodes.py` file
✅ Comprehensive tests cover all paths (valid, invalid, failed)
✅ Integration works with ComponentBrowsingNode output
✅ Empty discovered_params handled gracefully
✅ make test passes (for your subtask's tests)
✅ make check passes
✅ Progress log documents your implementation journey

## Common Pitfalls to Avoid

1. **DON'T use response.json()** - Use json.loads(response.text())
2. **DON'T use getattr for ValidationError** - Access attributes directly
3. **DON'T assume discovered_params exists** - Default to empty dict
4. **DON'T hardcode values in generated workflows** - Always use template variables
5. **DON'T forget the two-phase validation** - Structure first, then templates
6. **DON'T skip retry logic testing** - It's critical for Path B success

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent conflicts with other subtasks.

**Location**: `.taskmaster/tasks/task_17/implementation/subtask_3/implementation-plan.md`

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
   - Task: "Analyze outputs from Subtask 2 ComponentBrowsingNode and identify what planning_context contains"
   - Task: "Check shared store keys written by Subtask 2 nodes"

2. **Interface Discovery**
   - Task: "Identify how validate_ir and TemplateValidator are imported and used"
   - Task: "Analyze the retry loop pattern in PocketFlow for best practices"

3. **Testing Pattern Analysis**
   - Task: "Examine tests/test_planning/ for existing test patterns"
   - Task: "Identify test fixtures from conftest.py we should use"

4. **Integration Requirements**
   - Task: "Check how ParameterMappingNode (Subtask 5) will use workflow_metadata"
   - Task: "Verify Registry usage pattern for template validation"
```

> Note: Your prompts to the subagents should be very specific and detailed, providing full Task 17 context.

### Step 2: Write Your Implementation Plan

Your plan should include:

1. **Interface verification** - Confirm planning_context format from Subtask 2
2. **Component breakdown** - WorkflowGeneratorNode, ValidatorNode, MetadataGenerationNode
3. **Integration strategy** - How retry loop connects the nodes
4. **Risk identification** - What could affect parameter nodes (Subtask 4/5)
5. **Testing strategy** - How to test retry logic and validation phases

### Implementation Plan Template

```markdown
# Task 17 - Subtask 3 Implementation Plan

## Dependencies Verified

### From Previous Subtasks
- ComponentBrowsingNode provides planning_context (markdown string)
- ir_models.py provides FlowIR, NodeIR, EdgeIR for structured output
- Test fixtures available in conftest.py

### For Next Subtasks
- generated_workflow must be valid IR for parameter extraction
- workflow_metadata needed by ParameterMappingNode
- validation_errors format must support retry enhancement

## Shared Store Contract
- Reads: planning_context, discovered_params (empty), generation_attempts, validation_errors
- Writes: generated_workflow, generation_attempts, validation_errors, validation_error, workflow_metadata

## Implementation Steps

### Phase 1: Core Components
1. Import required modules in nodes.py
2. Implement WorkflowGeneratorNode with basic generation
3. Implement ValidatorNode with two-phase validation
4. Implement MetadataGenerationNode with simple extraction

### Phase 2: Retry Logic
1. Add prompt enhancement for retries
2. Implement error feedback incorporation
3. Test retry loop behavior

### Phase 3: Integration Testing
1. Test with real ComponentBrowsingNode output
2. Verify template validation with Registry
3. Test all routing paths

## Risk Mitigation

| Risk | Impact on Other Subtasks | Mitigation Strategy |
|------|-------------------------|-------------------|
| Invalid IR format | Breaks parameter extraction | Strict Pydantic validation |
| Missing template vars | Workflows not reusable | Template validation phase |
| Retry loop infinite | Blocks flow completion | Max attempts limit |

## Validation Strategy
- Unit tests for each node
- Integration test for retry loop
- Template validation with real Registry
- All paths tested (valid, invalid, failed)
```

### When to Revise Your Plan

Your plan is a living document. Update it when:
- You discover planning_context has unexpected format
- Template validation needs different approach
- Integration with validate_ir reveals issues

Document plan changes in the SHARED progress log with rationale.

## Your Implementation Order

### 0. Review Shared Progress Log (FIRST!)

Check what previous subtasks have implemented: `.taskmaster/tasks/task_17/implementation/progress-log.md`

### 1. Create Your Implementation Plan (SECOND!)

Location: `.taskmaster/tasks/task_17/subtask_3/implementation-plan.md`

### Implementation Steps

1. Gather context using parallel subagents (planning_context format, validation APIs)
2. Add imports to existing `nodes.py` file
3. Implement WorkflowGeneratorNode with structured output
4. Implement ValidatorNode with two-phase validation
5. Implement MetadataGenerationNode with basic extraction
6. Add retry enhancement logic to generator
7. Create comprehensive tests with test-writer-fixer agent
8. Test integration with Subtask 2 outputs
9. Run make test and make check
10. Document insights in shared progress log

## Real-Time Learning Capture in SHARED Log

**AS YOU IMPLEMENT**, continuously append to the SHARED progress log:

```markdown
## [Timestamp] - Subtask 3 - Implementing retry logic
Attempting to add progressive enhancement to WorkflowGeneratorNode...

Result: Discovered that validation_errors needs special formatting
- ✅ What worked: Passing errors as bulleted list improves LLM understanding
- ❌ What failed: Simply appending errors created confusing prompts
- 💡 Insight: Structure validation errors differently than template errors in prompt

Code that worked:
```python
def _build_prompt(self, prep_res, attempt):
    if attempt > 0 and prep_res["validation_errors"]:
        error_section = "\n\nPrevious attempt failed with errors:\n"
        error_section += "\n".join(f"- {err}" for err in prep_res["validation_errors"])
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
## [Time] - Subtask 3 - DEVIATION FROM PLAN
- Original plan: Use simple prompt concatenation for retries
- Why it failed: LLM got confused by unstructured error lists
- Impact on other subtasks: None - internal implementation detail
- New approach: Structure errors with clear sections and formatting
- Lesson: LLM needs structured error feedback for effective fixes
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test the retry loop and validation phases"

**Focus on**:
- Retry loop behavior with mocked LLM
- Two-phase validation separation
- Template variable detection
- Error format handling
- All routing paths (valid, invalid, failed)

**What to test**:
- **Generator retry**: Progressive enhancement works
- **Validation phases**: Structure and template validation separate
- **Error handling**: Both error types stored correctly
- **Routing logic**: Correct action strings returned
- **Edge cases**: Empty inputs, malformed workflows

**Progress Log - Only document testing insights**:
```markdown
## {{time}} - Subtask 3 - Testing revealed retry behavior
Discovered that we need to mock consistent validation errors for retry tests.
Random errors make tests flaky. Using deterministic error sets.
```

**Remember**: Test the retry loop thoroughly - it's critical for Path B

## What NOT to Do

- DON'T implement ParameterDiscoveryNode - that's Subtask 4
- DON'T wire nodes into a flow - that's Subtask 6
- DON'T create new files - add to existing nodes.py
- DON'T use response.json() - use json.loads(response.text())
- DON'T hardcode values in generated workflows
- DON'T skip template validation phase
- DON'T assume discovered_params is populated
- DON'T create unbounded retry loops

## Getting Started

1. Read the shared progress log to see what Subtask 1 & 2 implemented
2. Review your subtask specification one more time
3. Create your implementation plan
4. Check planning_context format from ComponentBrowsingNode
5. Verify imports for validate_ir and TemplateValidator
6. Start with WorkflowGeneratorNode basic implementation
7. Test each node in isolation before integration
8. Use test-writer-fixer agent for comprehensive tests

Test your specific components:
```bash
# Test just your nodes
pytest tests/test_planning/test_nodes.py::TestWorkflowGeneratorNode -xvs
pytest tests/test_planning/test_nodes.py::TestValidatorNode -xvs
pytest tests/test_planning/test_nodes.py::TestMetadataGenerationNode -xvs

# Run all planning tests
pytest tests/test_planning/ -xvs
```

## Final Notes

This subtask is the HEART of Path B - without successful generation and validation, no new workflows can be created. The retry loop is sophisticated but critical for handling LLM generation challenges.

Template variables are non-negotiable - every parameter must use the $ syntax for reusability. The two-phase validation ensures both structural correctness and template compliance.

Your work enables the "generate" path of the two-path architecture. Focus on robustness and clear error handling.

## Remember

You're implementing the core generation system for Task 17's Natural Language Planner. The retry loop with progressive enhancement is a key innovation. Two-phase validation ensures workflows are both structurally valid and reusable.

The convergence at ParameterMappingNode depends on your metadata extraction. Future parameter nodes will use your generated workflows.

You're building the creative engine of the planner - where natural language becomes executable, reusable workflows. Make it robust, make it smart, make it work!

Good luck with Subtask 3! 🚀
