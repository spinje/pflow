# Task 6 Decomposition Plan

**File Location**: `.taskmaster/tasks/task_6/decomposition-plan.md`

*Created on: 2025-06-29*
*Purpose: Comprehensive prompt for task-master expand command*

## Task Overview
Task 6 aims to create JSON schema definitions for workflow intermediate representation (IR) in `src/pflow/core/ir_schema.py`. This schema is the foundational data structure that enables pflow to represent workflows in a standardized, validated format that can be converted to executable pocketflow.Flow objects.

## Decomposition Pattern
**Pattern**: Foundation-Integration-Polish

**Reasoning**: This pattern fits because we need to:
1. First establish the core schema structure (foundation)
2. Then implement validation and utility functions (integration)
3. Finally add comprehensive examples and polish error messages (polish)

## Complexity Analysis
- **Complexity Score**: 5/10
- **Reasoning**: Moderate complexity due to need for careful schema design, validation logic, and comprehensive testing
- **Total Subtasks**: 3

## Planned Subtasks

### Subtask 1: Define Core JSON Schema Structure
**Description**: Create the foundational JSON schema definitions for workflow IR in `src/pflow/core/ir_schema.py`. Define the minimal IR structure including nodes array (with id, type, params), edges array (with from, to, action), start_node, and optional mappings. Use standard JSON Schema format following the decisions in the research files.

**Dependencies**: None
**Estimated Hours**: 3-4
**Implementation Details**:
- Create `src/pflow/core/__init__.py` and `src/pflow/core/ir_schema.py`
- Define schema as Python dictionary using JSON Schema Draft 7 format
- Include minimal envelope with schema version for future compatibility
- Use 'type' field for nodes (not 'registry_id') per task example
- Make start_node optional with sensible default behavior
- Include optional action field in edges with "default" as default value
- Define mappings structure for proxy pattern support
- Write initial validation tests alongside implementation

**Test Requirements**:
- Test valid minimal IR (single node, no edges)
- Test valid complex IR (multiple nodes with edges)
- Test invalid IR (missing required fields, invalid references)
- Test edge cases (empty nodes array, self-referential edges)

### Subtask 2: Implement Validation Functions and Error Handling
**Description**: Add validation functions that use the jsonschema library to validate IR against the schema. Implement robust JSON loading with graceful error handling. Create custom validation error messages that provide clear guidance for fixing issues.

**Dependencies**: [6.1]
**Estimated Hours**: 3-4
**Implementation Details**:
- Add jsonschema to project dependencies if not present
- Implement `validate_ir()` function using jsonschema
- Create custom ValidationError with helpful error messages
- Add JSON loading function with proper error handling
- Include path to invalid field in error messages
- Suggest fixes for common mistakes
- Write comprehensive validation tests

**Test Requirements**:
- Test validation of all schema constraints
- Test clear error messages for various failure modes
- Test JSON loading with malformed files
- Test helpful error suggestions

### Subtask 3: Create Examples and Documentation
**Description**: Develop comprehensive valid and invalid IR examples for testing and documentation. Add detailed docstrings to all functions. Create example workflows that demonstrate all features of the IR schema including template variables, mappings, and action-based routing.

**Dependencies**: [6.2]
**Estimated Hours**: 2-3
**Implementation Details**:
- Create multiple valid IR examples (simple to complex)
- Create invalid IR examples for each validation rule
- Add comprehensive module and function docstrings
- Include examples in docstrings
- Document template variable support ($variable syntax)
- Create examples showing mappings usage
- Polish error messages based on example testing

**Test Requirements**:
- All examples must be tested programmatically
- Valid examples must pass validation
- Invalid examples must fail with expected errors
- Documentation examples must be executable

## Relevant pflow Documentation

### Core Documentation
- `docs/core-concepts/schemas.md` - Complete schema specification
  - Relevance: Primary reference for schema structure and governance
  - Key concepts: Document envelope, node/edge structures, versioning
  - Applies to subtasks: All subtasks, especially 1

- `docs/features/planner.md#10.1` - Template-driven IR details
  - Relevance: Explains template variable usage in IR
  - Key concepts: $variable syntax, runtime resolution
  - Applies to subtasks: 1 and 3 for template support

### Architecture Documentation
- `docs/architecture/pflow-pocketflow-integration-guide.md` - Integration patterns
  - Critical for: Understanding how IR gets converted to pocketflow objects
  - Must follow: IR is pure data format, not wrapper classes
  - Applies to subtasks: 1 for design decisions

### Supporting Documentation
- `docs/core-concepts/shared-store.md` - Proxy pattern and mappings
  - Relevance: Explains when mappings are needed
  - Key concepts: NodeAwareSharedStore, input/output mappings
  - Applies to subtasks: 1 for mappings schema, 3 for examples

## Research References

### For All Subtasks:
- Apply decisions from `.taskmaster/tasks/task_6/research/task-6-ir-schema-decisions.md`
- Specifically: Use standard JSON Schema, 'type' field, optional start_node, include action field
- Follow readiness assessment from `.taskmaster/tasks/task_6/research/task-6-readiness-assessment.md`

### For Subtask 3:
- Reference examples from `.taskmaster/tasks/task_6/research/pocketflow-patterns.md`
- Key insights: Template variable preservation, natural key documentation
- Adaptation: Simplify Pydantic examples to pure JSON Schema

## Key Architectural Considerations
- IR is a pure data format, not code or classes
- Schema must support template variables without resolving them
- Validation should happen at IR creation, not execution
- Design for extensibility but implement only MVP features
- Follow "test-as-you-go" pattern from knowledge base

## Dependencies Between Subtasks
- 6.2 requires 6.1 because validation needs the schema definition
- 6.3 requires 6.2 because examples need working validation

## Success Criteria
- [ ] Complete JSON Schema definition for workflow IR
- [ ] Robust validation with helpful error messages
- [ ] Comprehensive examples covering all features
- [ ] All tests pass including edge cases
- [ ] Clear documentation and docstrings
- [ ] Schema allows future extensions without breaking changes

## Special Instructions for Expansion
- Focus on MVP simplicity while allowing extensibility
- Ensure each subtask includes its own tests (no separate test subtask)
- Reference specific documentation sections in implementation details
- Include concrete file paths and module structure
- Emphasize clear error messages for user experience

---

**Note**: This file will be passed directly to `task-master expand` as the prompt. It contains all context needed for intelligent subtask generation, including explicit references to project documentation and research findings.
