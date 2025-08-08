# Task 17 - Subtask 5: Validation & Refinement System - Agent Instructions

## Critical Pre-Requirement

**IMPORTANT**: This prompt assumes you have already thoroughly read and understand:
- All Task 17 documentation in `.taskmaster/tasks/task_17/`
- The epistemic manifesto
- The two-path architecture (Path A: reuse, Path B: generate)
- How subtasks interconnect and depend on each other
- The shared progress log system

If you haven't read these yet, STOP and read them first.

## The Problem You're Solving

The GeneratorNode produces workflows that are 99% correct, but that 1% could break at runtime. The generator sometimes creates typos in node names, forgets to use template variables, or declares inputs that are never used. Without validation, these errors would only surface when users try to execute workflows, breaking the "Plan Once, Run Forever" philosophy.

## Your Mission Within Task 17

Create the quality gate for Path B that ensures only executable workflows reach the convergence point (ParameterMappingNode). You'll validate generated workflows and extract metadata, acting as the safety net that catches generator mistakes before they become runtime failures.

## ⚠️ Critical Context: Task 17's Two-Path Architecture

Before implementing this subtask, you MUST understand the overall architecture:

**Path A (Workflow Reuse)**: Discovery → ParameterMapping → Preparation → Result
**Path B (Workflow Generation)**: Discovery → Browsing → ParamDiscovery → Generation → **Validation → Metadata** → ParameterMapping → Preparation → Result

**CONVERGENCE**: Both paths meet at ParameterMappingNode - the verification gate.

**This Subtask's Role**: Path B ONLY - You're the quality gate between generation and convergence. ValidatorNode orchestrates validation and routes based on results. MetadataGenerationNode only runs after successful validation, extracting metadata before convergence.

## Dependencies and Prerequisites

### Subtasks That Must Be Complete
- ✅ Subtask 1 (Foundation): Provides directory structure and test infrastructure
- ✅ Subtask 2 (Discovery): Provides routing that leads to generation
- ✅ Subtask 3 (Parameters): Parameter discovery happens before generation
- ✅ Subtask 4 (Generation): GeneratorNode creates workflows and routes to "validate"

### Files/Outputs You'll Use From Previous Subtasks
- `src/pflow/planning/nodes.py` with GeneratorNode that routes to you with action "validate"
- `src/pflow/planning/ir_models.py` with FlowIR Pydantic model
- Test fixtures from `tests/test_planning/conftest.py`
- GeneratorNode's output format in `shared["generated_workflow"]`

## Required Context Review

### MUST READ BEFORE STARTING (In This Order):

1. **Your Subtask Specification** (PRIMARY source of truth)
   **File**: `.taskmaster/tasks/task_17/starting-context/task-17-subtask-5-spec.md`
   - Defines exact behavior and interfaces
   - Specifies action strings ("retry", "metadata_generation", "failed")
   - Details the enhancement needed for TemplateValidator

2. **Handoff from Subtask 4**
   **File**: `.taskmaster/tasks/task_17/handoffs/handoff-to-subtask-5.md`
   - What GeneratorNode actually produces
   - Real patterns and edge cases discovered during Subtask 4
   - Critical warnings about template variables and registry issues

3. **Validation Insights and Clarifications**
   **File**: `.taskmaster/tasks/task_17/handoffs/subtask-5-validation-insights.md`
   - **CRITICAL**: Explains why you CANNOT detect "hardcoded values"
   - Clarifies what validation is actually possible
   - Details the existing validation landscape
   - Provides implementation strategy with code examples

**READ THESE THREE FILES CAREFULLY BEFORE WRITING YOUR PLAN OR ANY CODE!**

Key realizations from these documents:
1. ValidatorNode is an ORCHESTRATOR, not a monolithic validator
2. You CANNOT detect if values "should have been" parameterized (no access to discovered_params)
3. The critical validation is unused inputs detection (clear generator bug)
4. Existing validators handle most validation - you're filling gaps

## 🔄 Shared Progress Log (CRITICAL!)

**The progress log is SHARED across ALL Task 17 subtasks!**

**Location**: `.taskmaster/tasks/task_17/implementation/progress-log.md`

**Format for your entries**:
```markdown
## [Timestamp] - Subtask 5 - [What You're Trying]
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
- Always prefix entries with "Subtask 5"
- Check Subtask 4 entries to understand GeneratorNode's implementation
- Your insights about validation help future subtasks

## What You're Building

You're creating two nodes and one enhancement:

1. **ValidatorNode** - Orchestrates all validation checks:
   - Calls `validate_ir()` for structural validation
   - Calls enhanced `TemplateValidator` for template and unused input validation
   - Validates node types exist in registry
   - Routes based on validation results and retry count

2. **TemplateValidator Enhancement** - Add unused input detection:
   - Check if all declared inputs are used as template variables
   - Return error if inputs are declared but never referenced

3. **MetadataGenerationNode** - Extracts workflow metadata:
   - Creates suggested_name from user_input
   - Extracts description
   - Lists declared inputs/outputs
   - Only runs after successful validation

Example usage within the planner:
```python
# GeneratorNode routes to ValidatorNode
generator_node - "validate" >> validator_node

# ValidatorNode routes based on results
validator_node - "retry" >> generator_node  # If errors and attempts < 3
validator_node - "metadata_generation" >> metadata_node  # If valid
validator_node - "failed" >> result_node  # If attempts >= 3

# MetadataGenerationNode continues to convergence
metadata_node - "" >> parameter_mapping_node
```

## Shared Store Contract

### Keys This Subtask READS
- `shared["generated_workflow"]` - Complete workflow IR from GeneratorNode
- `shared["generation_attempts"]` - Number of attempts so far (1-indexed)
- `shared["planning_context"]` - Context for metadata extraction
- `shared["user_input"]` - Original request for metadata extraction

### Keys This Subtask WRITES
- `shared["validation_errors"]` - List of error strings for generator retry
- `shared["workflow_metadata"]` - Extracted metadata dict

### Expected Data Formats
```python
# What you read
shared["generated_workflow"] = {
    "ir_version": "0.1.0",
    "inputs": {
        "repo_name": {"type": "string", "required": True, "description": "..."},
        "limit": {"type": "integer", "required": False, "default": 50}
    },
    "nodes": [...],
    "edges": [...]
}

# What you write
shared["validation_errors"] = [
    "Template variable $repo_name used but not defined in inputs field",
    "Node type 'github-list-issuez' not found in registry",
    "Declared input 'unused_param' never used as template variable"
]

shared["workflow_metadata"] = {
    "suggested_name": "generate-changelog",
    "description": "Generate changelog from GitHub issues",
    "declared_inputs": ["repo_name", "limit"],
    "declared_outputs": ["changelog"]
}
```

## Key Outcomes You Must Achieve

### Core Deliverables
1. Enhanced `TemplateValidator` in `src/pflow/runtime/template_validator.py`
2. `ValidatorNode` class in `src/pflow/planning/nodes.py`
3. `MetadataGenerationNode` class in `src/pflow/planning/nodes.py`
4. Comprehensive tests for validation logic and routing

### Interface Requirements
- ValidatorNode must handle action "validate" from GeneratorNode
- Must return correct action strings: "retry", "metadata_generation", or "failed"
- Must store validation_errors as list of strings (not exceptions)
- MetadataGenerationNode must return empty string to continue flow

### Integration Points
- Receives workflows from GeneratorNode via "validate" action
- Sends errors back to GeneratorNode via "retry" action
- Routes to MetadataGenerationNode on success
- MetadataGenerationNode leads to ParameterMappingNode (convergence)

## Implementation Strategy

### Phase 1: Enhance TemplateValidator (30 minutes)
1. Locate `src/pflow/runtime/template_validator.py`
2. Find the `validate_workflow_templates()` method
3. Add logic to extract declared inputs from workflow
4. Check if each declared input appears in extracted template variables
5. Add unused input errors to the returned error list
6. Write tests for the enhancement

### Phase 2: Implement ValidatorNode (45 minutes)
1. Add ValidatorNode class to `src/pflow/planning/nodes.py`
2. Import: `from pflow.core import validate_ir, ValidationError`
3. Import: `from pflow.runtime.template_validator import TemplateValidator`
4. Import: `from pflow.registry import Registry`
5. Implement prep() to extract workflow and attempts
6. Implement exec() to orchestrate validations
7. Implement post() to route based on results
8. Write comprehensive tests

### Phase 3: Implement MetadataGenerationNode (30 minutes)
1. Add MetadataGenerationNode class to `src/pflow/planning/nodes.py`
2. Implement prep() to gather needed data
3. Implement exec() to extract metadata
4. Implement post() to store metadata and continue
5. Write tests for metadata extraction

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### Exact Import Paths and Signatures
```python
# ValidatorNode imports
from pflow.core import validate_ir, ValidationError
from pflow.runtime.template_validator import TemplateValidator
from pflow.registry import Registry

# ValidationError structure
class ValidationError(Exception):
    def __init__(self, message: str, path: str = "", suggestion: str = ""):
        self.message = message
        self.path = path
        self.suggestion = suggestion

# TemplateValidator signature
@staticmethod
def validate_workflow_templates(
    workflow_ir: dict[str, Any],
    available_params: dict[str, Any],
    registry: Registry
) -> list[str]:
    # Returns list of error messages (empty if valid)
```

### Action String Routing
```python
class ValidatorNode(Node):
    def post(self, shared, prep_res, exec_res):
        if not exec_res.get("errors"):
            # All validations passed
            shared["workflow_metadata"] = {}  # Prepare for metadata node
            return "metadata_generation"

        # Check retry limit
        if shared.get("generation_attempts", 0) >= 3:
            return "failed"

        # Store errors for retry
        shared["validation_errors"] = exec_res["errors"][:3]  # Top 3 only
        return "retry"
```

### Registry Validation Pattern
```python
# Registry automatically scans subdirectories via rglob
registry = Registry()  # Uses default ~/.pflow/registry.json
metadata = registry.get_nodes_metadata()

# Check if node type exists
for node in workflow.get("nodes", []):
    if node["type"] not in metadata:
        errors.append(f"Unknown node type '{node['type']}'")
```

## Critical Warnings from Task 17 Experience

### Template Variables Are Sacred
**NEVER let workflows through that hardcode values that should be template variables**. The whole point of validation is catching these issues.

### Understanding Your Path
ValidatorNode belongs ONLY to Path B (generation path). It never sees workflows from Path A (reuse path).

### Action Strings Are Exact
Use EXACTLY these action strings:
- "retry" - Goes back to GeneratorNode
- "metadata_generation" - Goes to MetadataGenerationNode
- "failed" - Goes to ResultPreparationNode
NOT "valid"/"invalid" as some docs suggest!

## Key Decisions Already Made for Task 17

From the spec and handoff documents:
- Maximum 3 validation errors returned to avoid overwhelming the LLM
- Pass empty dict for available_params to TemplateValidator (no access to discovered_params)
- Registry automatically scans subdirectories - no manual scanning needed
- Unused inputs validation is critical - prevents wasted extraction effort
- Generation attempts are already tracked by GeneratorNode (1-indexed)

**📋 Note on Specifications**: Your subtask specification is the authoritative source. Follow it precisely - do not deviate from specified behavior, interface contracts, or implementation requirements unless you discover a critical issue (document and ask for clarification).

## Success Criteria

Your implementation is complete when:

✅ TemplateValidator detects unused declared inputs
✅ ValidatorNode orchestrates all validation checks correctly
✅ ValidatorNode returns correct action strings based on validation results
✅ ValidatorNode limits errors to top 3 for retry
✅ MetadataGenerationNode extracts workflow metadata
✅ Integration with GeneratorNode's retry mechanism works
✅ Shared store keys are properly read/written
✅ All tests pass including integration tests
✅ make test passes
✅ make check passes
✅ Progress log documents your implementation journey

## Common Pitfalls to Avoid

1. **Wrong action strings** - Use "retry"/"metadata_generation"/"failed", NOT "valid"/"invalid"
2. **Forgetting to convert ValidationError to string** - Errors must be strings, not exception objects
3. **Not checking generation_attempts** - Must return "failed" when >= 3, not "retry"
4. **Modifying generated_workflow** - ValidatorNode only reads, never modifies
5. **Complex metadata extraction** - Keep it simple, extract basic info from user_input
6. **Not testing unused inputs** - This is the critical enhancement to TemplateValidator
7. **Registry scanning issues** - Trust automatic scanning, don't add manual logic

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent conflicts with other subtasks.

**Location**: `.taskmaster/tasks/task_17/implementation/subtask-5/implementation-plan.md`

### Why Planning Matters for Subtasks

1. **Prevents breaking interfaces**: GeneratorNode depends on your error format
2. **Identifies integration points**: How you connect to the retry loop
3. **Optimizes parallelization**: Template enhancement vs node implementation
4. **Surfaces unknowns early**: Metadata extraction algorithm needs design

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Previous Subtask Analysis**
   - Task: "Analyze GeneratorNode implementation in nodes.py, focusing on how it routes to 'validate' and expects validation_errors back"
   - Task: "Check how generation_attempts is tracked and incremented"

2. **Interface Discovery**
   - Task: "Examine TemplateValidator.validate_workflow_templates() to understand current implementation"
   - Task: "Check validate_ir() and ValidationError usage patterns in the codebase"

3. **Testing Pattern Analysis**
   - Task: "Examine tests/test_planning/llm/behavior/test_generator_core.py for how generator tests validation"
   - Task: "Identify test fixtures for workflow validation we can reuse"

4. **Integration Requirements**
   - Task: "Check how MetadataGenerationNode output will be used by ParameterMappingNode"
   - Task: "Verify the flow continues correctly from metadata to parameter mapping"
```

> Note: Your prompts to the subagents should be very specific and detailed, providing full Task 17 context.

### Step 2: Write Your Implementation Plan

Your plan should include:

1. **Interface verification** - Confirm GeneratorNode's expectations
2. **Component breakdown** - TemplateValidator enhancement, both nodes
3. **Integration strategy** - How to connect to the retry loop
4. **Risk identification** - What could break the generator
5. **Testing strategy** - How to verify retry mechanism works

### Implementation Plan Template

```markdown
# Task 17 - Subtask 5 Implementation Plan

## Dependencies Verified

### From Previous Subtasks
- GeneratorNode outputs workflow with action "validate"
- generation_attempts tracked in shared store
- Workflow structure matches FlowIR model

### For Next Subtasks
- MetadataGenerationNode provides metadata for ParameterMappingNode
- Validation ensures only good workflows reach convergence

## Shared Store Contract
- Reads: generated_workflow, generation_attempts, planning_context, user_input
- Writes: validation_errors (on retry), workflow_metadata (on success)

## Implementation Steps

### Phase 1: Enhance TemplateValidator
1. Add unused input detection logic
2. Test enhancement independently
3. Verify error format matches expectations

### Phase 2: Implement ValidatorNode
1. Create orchestration logic
2. Handle all three routing cases
3. Test with mock validators

### Phase 3: Implement MetadataGenerationNode
1. Design metadata extraction algorithm
2. Implement and test
3. Verify flow continues correctly

## Risk Mitigation

| Risk | Impact on Other Subtasks | Mitigation Strategy |
|------|-------------------------|-------------------|
| Wrong error format | Generator can't parse | Test with actual generator |
| Missing validation | Bad workflows pass | Comprehensive test cases |
| Metadata format wrong | ParameterMapping fails | Coordinate on structure |

## Validation Strategy
- Test retry loop with GeneratorNode
- Verify unused inputs caught
- Ensure metadata extracted correctly
```

### When to Revise Your Plan

Your plan is a living document. Update it when:
- You discover GeneratorNode expects different error format
- TemplateValidator enhancement is more complex than expected
- Metadata requirements change

Document plan changes in the SHARED progress log with rationale.

## Your Implementation Order

### 0. Review Shared Progress Log (FIRST!)

Check what Subtask 4 implemented: `.taskmaster/tasks/task_17/implementation/progress-log.md`

### 1. Create Your Implementation Plan (SECOND!)

Location: `.taskmaster/tasks/task_17/implementation/subtask-5/implementation-plan.md`

### Implementation Steps

1. Enhance TemplateValidator with unused input detection
2. Write tests for TemplateValidator enhancement
3. Implement ValidatorNode with orchestration logic
4. Test ValidatorNode routing (all three paths)
5. Implement MetadataGenerationNode
6. Test metadata extraction
7. Integration test with GeneratorNode's retry mechanism
8. Verify flow continues to ParameterMappingNode
9. Update progress log with insights
10. Run make test and make check

## Real-Time Learning Capture in SHARED Log

**AS YOU IMPLEMENT**, continuously append to the SHARED progress log:

```markdown
## [Timestamp] - Subtask 5 - Implementing unused input detection
Attempting to enhance TemplateValidator...

Result: Successfully added detection
- ✅ What worked: Comparing declared inputs to extracted template vars
- ❌ What failed: Initial regex missed nested paths
- 💡 Insight: Need to extract base variable name from paths like $var.field

Code that worked:
```python
# Extract base variable names
template_vars = set()
for var in all_templates:
    base_var = var.split('.')[0]
    template_vars.add(base_var)

# Check for unused inputs
unused = set(workflow.get("inputs", {}).keys()) - template_vars
```
```

**Remember**: Your insights help future subtasks!

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Consider impact on generator retry mechanism
4. Update the plan with new approach
5. Continue with new understanding

Append deviation to SHARED progress log:
```markdown
## [Time] - Subtask 5 - DEVIATION FROM PLAN
- Original plan: Return ValidationError objects
- Why it failed: Generator expects list of strings
- Impact on other subtasks: None if we convert to strings
- New approach: Convert all errors to strings before storing
- Lesson: Always verify interface expectations with actual code
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test the quality gate thoroughly"

**Focus on**:
- Unused input detection (the new feature)
- Retry routing when errors found
- Failed routing when attempts >= 3
- Success routing to metadata generation
- Error format for generator compatibility

**What to test**:
- **TemplateValidator enhancement**: Catches unused inputs
- **ValidatorNode routing**: All three paths (retry/metadata/failed)
- **Error limiting**: Only top 3 errors returned
- **Metadata extraction**: Basic name and description
- **Integration**: Works with GeneratorNode's retry

**Progress Log - Only document testing insights**:
```markdown
## {{time}} - Subtask 5 - Testing revealed retry issue
Discovered that generator expects exactly list[str], not list[dict].
Need to ensure all errors are converted to plain strings.
```

**Remember**: Test the quality gate thoroughly - it's the safety net!

## What NOT to Do

- DON'T use "valid"/"invalid" action strings - use "retry"/"metadata_generation"/"failed"
- DON'T return exception objects - convert all errors to strings
- DON'T modify generated_workflow - only read it
- DON'T implement complex metadata extraction - keep it simple
- DON'T forget to test unused inputs - it's the critical enhancement
- DON'T add manual registry scanning - it's automatic
- DON'T allow workflows with unused inputs through - they waste extraction effort
- DON'T skip integration testing with GeneratorNode

## Getting Started

1. Read the shared progress log to see what Subtask 4 implemented
2. Review your subtask specification carefully
3. Create your implementation plan
4. Start with TemplateValidator enhancement (smallest scope)
5. Test the enhancement independently
6. Then implement ValidatorNode
7. Finally implement MetadataGenerationNode
8. Run integration tests with GeneratorNode

Test your specific components:
```bash
# Test your validator
RUN_LLM_TESTS=1 pytest tests/test_planning/test_validation.py -xvs

# Test integration with generator
RUN_LLM_TESTS=1 pytest tests/test_planning/test_generator_validator_integration.py -xvs
```

## Final Notes

Remember that you're the quality gate for Path B. Every workflow that passes through you will be trusted by ParameterMappingNode to be executable. The convergence point depends on your validation being thorough.

The unused inputs validation is particularly critical - it prevents ParameterMappingNode from wasting effort trying to extract parameters that the workflow never uses.

Your work enables the retry mechanism that makes the generator self-correcting. Clear, actionable error messages are key to helping the LLM fix issues.

## Remember

You're implementing the quality gate that ensures only good workflows reach the convergence point. The generator produces 99% correct workflows - you catch that critical 1% that would break at runtime.

ValidatorNode and MetadataGenerationNode are Path B only - they never see reused workflows from Path A. Your validation enables the generator's retry mechanism to self-correct.

The two-path architecture converges at ParameterMappingNode, which trusts that validated workflows are executable. Don't let bad workflows through!

You're implementing Subtask 5 of 7 for Task 17's Natural Language Planner. Your work enables pflow's "Plan Once, Run Forever" philosophy. The two-path architecture with convergence at ParameterMappingNode is the key innovation. Your subtask is a critical piece of this sophisticated meta-workflow.

Your validation ensures that when users say "generate changelog from closed issues", the resulting workflow actually works - with proper template variables, valid node types, and no wasted parameters. You're the quality gate that makes the magic reliable!