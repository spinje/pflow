# Task 68: Refactor RuntimeValidation into Separate Repair Service

## ID
68

## Title
Refactor RuntimeValidation into Separate Repair Service

## Description
Remove RuntimeValidationNode from the planner flow and create a separate repair service that fixes broken workflows after execution. This eliminates duplicate execution during planning, reduces side effects, and enables self-healing workflows that can adapt to API changes and environment differences without re-planning.

## Status
not started

## Dependencies
- Task 56: Implement Runtime Validation and Error Feedback Loop - The current RuntimeValidationNode implementation provides the foundation and learning that will be adapted into the repair service

## Priority
high

## Details
Currently, RuntimeValidationNode executes workflows during the planning phase to detect runtime issues, causing duplicate execution and potential side effects. This task refactors that functionality into a separate repair service that only runs after workflow execution fails.

### Phase 1: Foundation (WorkflowExecutorService)
Create a reusable workflow execution service by extracting execution logic from the CLI:
- Implement `WorkflowExecutorService` class with configurable error behavior
- Add `update_metadata()` method to WorkflowManager for execution tracking
- Extend metadata structure to track execution history
- Refactor CLI to use the new service (no user-visible changes)
- Ensure all existing tests pass

**Key Implementation Detail**: PocketFlow's `flow.run()` stops on first error by design, so multi-error collection will be limited in the initial implementation.

### Phase 2: Repair Service Implementation
Remove RuntimeValidationNode and implement the repair service:
- Delete RuntimeValidationNode from planner flow (12 nodes → 11 nodes)
- Create new `repair` module with repair-specific nodes
- Implement `WorkflowExecutorNode` (adapts RuntimeValidationNode logic)
- Implement `RepairGeneratorNode` for LLM-based workflow fixes
- Add CLI integration with auto-repair as default behavior
- Update all affected tests

### Key Design Decisions
- **Auto-repair by default**: Failed workflows automatically attempt repair without prompting
- **Transparent progress**: Users see familiar "Executing workflow (N nodes):" format during repair
- **Single execution path**: Success path runs workflow only once (no duplicate execution)
- **Reusable components**: WorkflowExecutorService used by both CLI and repair service
- **Clean separation**: Planning and repair are separate concerns

### User Experience
When a workflow fails, users will see:
```
Executing workflow (6 nodes):
  fetch_messages... ✓ 1.8s
  get_timestamp... ✗ Command failed

🔧 Auto-repairing workflow...
  • Issue detected: Template ${get_time.stdout} not found
Executing workflow (4 nodes):
  get_timestamp... ✗ Validation stopped
  ✅ Workflow repaired successfully!

Executing workflow (6 nodes):
  [All nodes execute successfully]
```

### Self-Healing Capabilities
The repair service enables workflows to automatically adapt to:
- API changes (field renames, response structure changes)
- Environment differences (Mac vs Linux shell commands)
- Credential updates (new API keys, different permissions)
- System changes (different file paths, installed tools)

This makes workflows future-proof and portable across environments.

## Test Strategy
Testing will ensure the refactor maintains existing functionality while adding repair capabilities:

### Phase 1 Tests (Refactoring)
- Unit tests for WorkflowExecutorService with both error modes
- Test WorkflowManager.update_metadata() functionality
- Integration tests verifying CLI works exactly as before
- Verify metadata updates after execution

### Phase 2 Tests (Repair Service)
- Delete 4 RuntimeValidation test files (no longer needed)
- Update flow structure tests to expect 11 nodes instead of 12
- Unit tests for repair nodes (ErrorCheckerNode, WorkflowExecutorNode, RepairGeneratorNode)
- Test repair flow routing and retry logic
- Integration tests for auto-repair behavior
- Test CLI prompt for manual repair mode

### Key Test Scenarios
- Workflow executes successfully first time (no repair needed)
- Workflow fails and is automatically repaired
- Repair attempts exceed limit (3 attempts)
- User opts out of repair with --no-repair flag
- Workflow saved despite errors when repair fails