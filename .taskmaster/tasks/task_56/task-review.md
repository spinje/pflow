# Task 56 Review: Runtime Validation & Error Feedback Loop

## Metadata
<!-- Implementation Date: 2025-01-21 -->
<!-- Session ID: 428f4baa-9ab1-43a5-86b8-6f902b0ead65 -->
<!-- Branch: feat/runtime-validation-error-feedback -->

## Executive Summary
Implemented RuntimeValidationNode to enable workflows to self-correct template paths through execution feedback, achieving "Plan Once, Run Forever" by detecting missing fields in API responses and providing available alternatives for correction.

## Implementation Overview

### What Was Built
Implemented a runtime validation feedback loop that executes candidate workflows during planning to detect and fix template path mismatches. The system detects missing nested template paths (e.g., `${http.response.username}` when the field is actually `login`), provides available fields, and allows up to 3 retry attempts.

**Major deviation from spec**: Instead of HTTP node extraction with `params.extract`, used existing nested template variable system - simpler and more flexible.

### Implementation Approach
- Added RuntimeValidationNode to planner flow after ValidatorNode
- Node executes workflow with fresh shared store to detect runtime issues
- Three detection mechanisms: exceptions, namespaced errors, missing template paths
- Routes: default (success), runtime_fix (retry), failed_runtime (abort)
- Reused existing template infrastructure rather than building extraction logic

## Files Modified/Created

### Core Changes
- `src/pflow/planning/nodes.py` - Added RuntimeValidationNode class with template path detection
- `src/pflow/planning/flow.py` - Wired RuntimeValidationNode into planner flow, reordered to put metadata generation AFTER runtime validation
- `src/pflow/core/exceptions.py` - Added RuntimeValidationError class (though ultimately unused due to pivot)
- `src/pflow/core/__init__.py` - Exported RuntimeValidationError

### Supporting Changes
- `src/pflow/runtime/template_validator.py` - Enhanced regex pattern to support array notation `${node[0].field}`
- `src/pflow/runtime/template_resolver.py` - Added array notation support to resolution pattern
- `src/pflow/planning/debug.py` - Fixed debug wrapper breaking Gemini models (pre-existing bug exposed by this task)

### Test Files
- `tests/test_runtime_validation.py` - Integration tests for RuntimeValidationNode
- `tests/test_runtime_validation_simple.py` - Unit tests for template detection logic
- `tests/test_runtime_feedback_integration.py` - Demonstration of full feedback loop
- `tests/test_planning/integration/test_flow_structure.py` - Updated for 12 nodes and new connections
- `tests/test_planning/integration/test_planner_integration.py` - Added RuntimeValidationNode mocks
- `tests/test_planning/unit/test_validation.py` - Updated ValidatorNode action expectations

## Integration Points & Dependencies

### Incoming Dependencies
- ValidatorNode -> RuntimeValidationNode (via "runtime_validation" action)
- WorkflowGeneratorNode -> RuntimeValidationNode (after retry from "runtime_fix")

### Outgoing Dependencies
- RuntimeValidationNode -> MetadataGenerationNode (default success path)
- RuntimeValidationNode -> WorkflowGeneratorNode ("runtime_fix" retry)
- RuntimeValidationNode -> ResultPreparationNode ("failed_runtime" abort)
- RuntimeValidationNode -> Registry (for workflow compilation)

### Shared Store Keys
- `generated_workflow` - Read: The workflow IR to validate
- `execution_params` / `extracted_params` - Read: Parameters for workflow execution
- `runtime_attempts` - Read/Write: Retry counter (max 3)
- `runtime_errors` - Write: Structured error information for generator

## Architectural Decisions & Tradeoffs

### Key Decisions

**Nested Templates over Extraction**
- Decision: Use `${http.response.login}` instead of `extract: {username: "$.login"}`
- Reasoning: Simpler, more flexible, reuses existing infrastructure
- Alternative considered: HTTP node extraction as per original spec

**Node Independence**
- Decision: No pflow.core imports in nodes
- Reasoning: Nodes should be reusable PocketFlow units
- Alternative considered: Direct RuntimeValidationError usage

**Metadata Generation Reordering**
- Decision: Generate metadata AFTER runtime validation succeeds
- Reasoning: Avoid 1-4x duplicate metadata generation during retries
- Alternative considered: Keep original order (caused performance issue)

### Technical Debt Incurred
- Double execution accepted for MVP (once in validation, once for real)
- Simple path detection (not full JSONPath)
- No dry-run mode - always executes with potential side effects

## Testing Implementation

### Test Strategy Applied
- Unit tests for template detection logic
- Integration tests for node behavior
- Mock `_run()` not `exec()` for PocketFlow nodes (critical pattern)
- Demonstration tests showing real-world value

### Critical Test Cases
- `test_runtime_validation_simple.py::test_check_template_exists` - Core path detection
- `test_runtime_validation.py::test_runtime_validation_missing_paths` - Missing template detection
- `test_planner_integration.py::test_runtime_validation_receives_extracted_params` - Parameter flow

## Unexpected Discoveries

### Gotchas Encountered

**Mock Pattern for PocketFlow Nodes**
- Mocking `exec()` wasn't enough - `post()` still ran with empty data
- Must mock `_run()` to bypass entire prep/exec/post cycle

**Debug Wrapper Breaking Gemini**
- Debug system was injecting `model` parameter
- Gemini's pydantic model rejected extra fields
- Error messages were deeply misleading

**Parameter Flow Gap**
- RuntimeValidationNode initially read from wrong store key
- `execution_params` was None, needed fallback to `extracted_params`

### Edge Cases Found
- Workflows with required inputs fail validation when params not provided
- Array notation in templates needed special handling
- Namespaced errors need careful extraction

## Patterns Established

### Reusable Patterns

**Template Path Detection with Array Support**
```python
# Pattern now handles ${node[0].field.subfield}
_PERMISSIVE_PATTERN = re.compile(
    r"\$\{([a-zA-Z_][\w-]*(?:(?:\[[\d]+\])?(?:\.[\w-]*(?:\[[\d]+\])?)*)?)\}"
)
```

**Node Independence Pattern**
```python
# Nodes define own errors, runtime layer translates
class HttpExtractionError(ValueError):  # Node-specific
# Later translated to RuntimeValidationError by runtime layer
```

### Anti-Patterns to Avoid
- Don't import pflow.core in nodes
- Don't mock exec() for PocketFlow nodes - mock _run()
- Don't generate metadata before runtime validation

## Breaking Changes

### API/Interface Changes
- ValidatorNode now returns "runtime_validation" not "metadata_generation"
- Flow has 12 nodes instead of 11

### Behavioral Changes
- Metadata generated after runtime validation (performance improvement)
- Workflows executed during planning (potential side effects)

## Future Considerations

### Extension Points
- Task 68 proposes moving validation to post-execution repair service
- Could add dry-run mode to avoid side effects
- Template detection could support full JSONPath

### Scalability Concerns
- Double execution will become costly with complex workflows
- Side effects during planning problematic for production

## AI Agent Guidance

### Quick Start for Related Tasks

**Key files to read first:**
1. `src/pflow/planning/nodes.py::RuntimeValidationNode` - Core implementation
2. `tests/test_runtime_validation_simple.py` - Understand detection logic
3. `.taskmaster/tasks/task_56/implementation/revised-approach.md` - Architectural pivot explanation

**Pattern to follow for new planner nodes:**
```python
def post(self, shared, prep_res, exec_res) -> str:
    # Analyze results
    # Store in shared for next node
    # Return action string for routing
```

### Common Pitfalls

1. **Test Mocking**: Always mock `_run()` not `exec()` for PocketFlow nodes
2. **Node Dependencies**: Never import from pflow.core in node implementations
3. **Template Patterns**: Use TemplateValidator._extract_all_templates() instead of rolling your own
4. **Flow Changes**: Remember to update both flow.py connections AND node action strings
5. **Integration Tests**: Update mock response counts when changing flow order

### Test-First Recommendations

When modifying RuntimeValidationNode:
1. Run `test_runtime_validation_simple.py` first - fastest unit tests
2. Then `test_flow_structure.py` - verifies wiring
3. Finally `test_planner_integration.py` - full integration

When adding new template syntax:
1. Update both `template_validator.py` AND `template_resolver.py` patterns
2. Test with `test_runtime_validation_nested.py`

---

*Generated from implementation context of Task 56*