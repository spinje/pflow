# Task 3 Decomposition Plan

**File Location**: `.taskmaster/tasks/task_3/decomposition-plan.md`

*Created on: 2025-07-08*
*Purpose: Comprehensive prompt for task-master expand command*

## Task Overview
Task 3 "Execute a Hardcoded 'Hello World' Workflow" is the first integration milestone for pflow. It validates that all Phase 1 components work together by executing a simple read-file → write-file workflow from a JSON IR file. This task integrates the CLI (Task 2), IR validation (Task 6), Registry (Task 5), Compiler (Task 4), and File nodes (Task 11) into a working end-to-end pipeline.

**NOTE**: This task has been substantially implemented (see commit dff02c3). The workflow execution is functional, tests exist, and hello_workflow.json has been created. Subtasks should focus on review, polish, and ensuring completeness rather than implementing from scratch.

## Decomposition Pattern
**Pattern**: Foundation-Integration-Polish

**Reasoning**: This pattern fits perfectly because Task 3 is primarily an integration task. We need to:
1. Foundation: Wire up the basic workflow execution in the CLI
2. Integration: Connect all existing components (registry, compiler, validation)
3. Polish: Add comprehensive error handling, tests, and documentation

## Complexity Analysis
- **Complexity Score**: 4/10
- **Reasoning**: While conceptually straightforward (all components exist), the integration requires careful attention to error handling, user experience, and testing the complete pipeline
- **Total Subtasks**: 3

## Planned Subtasks

### Subtask 1: Review and Document Existing Workflow Implementation
**Description**: Review and polish the existing workflow execution implementation in `src/pflow/cli/main.py`. The basic execution is already implemented (lines 80-88), but verify it handles all edge cases properly. The `hello_workflow.json` already exists and successfully executes.

**Dependencies**: None (all component dependencies already complete)
**Estimated Hours**: 4-5
**Implementation Details**:
- Review existing implementation in `src/pflow/cli/main.py` (lines 80-88)
- Verify JSON detection and processing logic is complete
- Ensure all edge cases are handled (empty files, large files, etc.)
- Review shared store initialization and management
- Verify both "default" and "error" action results are properly handled
- Document any missing functionality or improvements needed
- Confirm the direct command pattern works correctly: `pflow --file workflow.json`

**Test Requirements**:
- Unit tests for JSON detection and routing logic
- Mock tests for component integration points
- Verify shared store state after execution
- Test error paths (invalid JSON, missing nodes, etc.)

### Subtask 2: Enhance Error Handling and User Feedback
**Description**: Review and enhance the existing error handling implementation. Basic error handling exists for missing registry, invalid JSON, and validation errors. Focus on improving clarity and coverage.

**Dependencies**: [3.1]
**Estimated Hours**: 3-4
**Implementation Details**:
- Review existing error handling in the pipeline stages
- Verify missing registry error shows populate instructions (already implemented)
- Enhance JSON parsing errors with better line/column information if needed
- Review if available nodes are shown when requested node not found
- Add structured logging with phase tracking if not already present
- Consider adding progress indicators for long-running workflows
- Apply patterns from `knowledge/patterns.md` where not already implemented

**Test Requirements**:
- Test each error scenario with appropriate fixtures
- Verify error messages are helpful and actionable
- Test logging output includes phase information
- Ensure graceful degradation (partial success reporting)

### Subtask 3: Complete Integration Test Coverage
**Description**: Review and expand the existing integration tests in `tests/test_e2e_workflow.py`. Basic tests already exist for workflow execution, missing registry, invalid JSON, and validation errors. Focus on ensuring comprehensive coverage.

**Dependencies**: [3.2]
**Estimated Hours**: 3-4
**Implementation Details**:
- Review existing tests for completeness (4 tests already exist)
- Add any missing test fixtures for edge cases
- Verify CliRunner tests cover all CLI scenarios
- Ensure file operations are properly tested with temporary directories
- Add tests to verify shared store contents after execution
- Test retry behavior for transient failures (PocketFlow feature)
- Add mock nodes for isolated component testing if needed
- Ensure all scenarios from the temporary registry population are tested

**Test Requirements**:
- Complete workflow execution from JSON to output file
- Missing input file handling
- Invalid JSON structure
- Missing nodes in registry
- Compilation errors
- Execution failures with retry
- Verify line numbering behavior from ReadFileNode

## Relevant pflow Documentation

### Core Documentation
- `architecture/features/cli-runtime.md` - CLI integration and shared store patterns
  - Relevance: Defines how CLI should integrate with the runtime
  - Key concepts: Shared store initialization, execution flow
  - Applies to subtasks: 1 and 2

- `architecture/core-concepts/schemas.md` - IR schema structure and validation
  - Relevance: Defines the JSON format for workflows
  - Key concepts: Node definitions, edge format, validation rules
  - Applies to subtasks: 1 and 3 (for test fixtures)

- `architecture/core-concepts/runtime.md` - Execution model (simplified for MVP)
  - Relevance: Explains how workflows execute
  - Key concepts: Synchronous execution, action-based transitions
  - Applies to subtasks: 1 and 2

- `architecture/reference/cli-reference.md` - CLI command structure
  - Relevance: Defines expected CLI behavior
  - Key concepts: Direct command execution, file input handling
  - Applies to subtasks: 1 and 3

### Architecture/Feature Documentation
- `architecture/architecture/pflow-pocketflow-integration-guide.md` - Integration patterns
  - Critical for: Understanding how pflow wraps PocketFlow
  - Must follow: Parameter passing conventions, shared store usage
  - Applies to subtasks: 1

- `architecture/features/simple-nodes.md` - Node design philosophy
  - Critical for: Understanding how file nodes work
  - Must follow: Natural interface pattern, fail-fast behavior
  - Applies to subtasks: 1 and 3

## Relevant PocketFlow Documentation

### Framework Core
- `pocketflow/__init__.py` - Core classes (Node, Flow, operators)
  - Pattern: Flow construction with >> operator, node lifecycle
  - Usage: Compiler creates Flow objects that subtask 1 executes

- `pocketflow/docs/core_abstraction/flow.md` - Flow orchestration
  - Pattern: Action-based transitions, shared store passing
  - Usage: Understanding how compiled flows execute

- `pocketflow/docs/core_abstraction/communication.md` - Shared store patterns
  - Pattern: Dictionary-based inter-node communication
  - Usage: Subtask 1 initializes and passes shared store

## Relevant PocketFlow Examples

### Cookbook Patterns
- `pocketflow/cookbook/pocketflow-hello-world/` - Minimal workflow example
  - Adaptation needed: None - directly applicable as reference
  - Applies to: Subtask 1 for basic flow execution

- `pocketflow/cookbook/pocketflow-communication/` - Shared store usage
  - Adaptation needed: None - shows data passing pattern
  - Applies to: Subtask 3 for testing shared store state

## Research References

### For Subtask 1:
- Apply integration approach from `.taskmaster/tasks/task_3/research/cli-and-compiler-integration.md`
- Specifically: The execute_json_workflow() pattern with registry checks
- Use the error handling flow for missing registry

### For Subtask 2:
- Reference: `.taskmaster/tasks/task_3/research/shared-store-pattern.md`
- Key insight: Natural key naming prevents collisions
- Apply structured logging pattern for phase tracking

### For Subtask 3:
- Reference: `.taskmaster/tasks/task_3/research/integration-test-patterns.md`
- Key insight: Test the complete pipeline with real files
- Use the fixture structure for workflow JSON files

## Key Architectural Considerations
- The CLI already has `--file` option from Task 2 - extend it, don't replace
- Registry must be populated first (temporary script exists)
- PocketFlow has been modified for parameter preservation (documented)
- ReadFileNode adds line numbers by design - tests must account for this
- No subcommands - use direct execution pattern
- Template variables in IR pass through unchanged (no resolution yet)

## Dependencies Between Subtasks
- 3.2 requires 3.1 because error handling needs the basic flow working
- 3.3 requires 3.2 because tests need complete error handling
- No parallel execution possible - strictly sequential

## Success Criteria
- [ ] Can execute `pflow --file hello_workflow.json` successfully
- [ ] Workflow reads input.txt and writes to output.txt with line numbers
- [ ] Clear error messages for all failure modes
- [ ] Registry missing error includes populate instructions
- [ ] All tests pass including retry behavior
- [ ] Structured logging shows execution phases
- [ ] Documentation includes working example

## Special Instructions for Expansion
- Each subtask should be self-contained but build on previous work
- Include specific file paths in implementation details
- Reference the research files for proven patterns
- Ensure error messages are helpful and actionable
- Focus on MVP scope - no natural language, no advanced features
- Test coverage is critical - this sets the pattern for future work
- Remember this is an integration task - we're connecting existing pieces

---

**Note**: This file will be passed directly to `task-master expand` as the prompt. All dependency tasks (1, 2, 4, 5, 6, 11) are complete, so Task 3 can proceed immediately. The research folder contains extensive implementation guidance that should be followed.
