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
- Task 56: Implement Runtime Validation and Error Feedback Loop - The current RuntimeValidationNode implementation provides the foundation and patterns that will be adapted into the repair service

## Priority
high

## Details
Currently, RuntimeValidationNode executes workflows during the planning phase to detect runtime issues, causing duplicate execution and potential side effects (sending duplicate messages, making duplicate API calls). This task refactors that functionality into a separate repair service that only runs after workflow execution fails.

### The Core Innovation: Resume-Based Repair
Instead of complex caching with keys and invalidation, we implement a checkpoint/resume system:
- Execute workflow → Fail at node N → Save entire shared state as checkpoint
- Repair workflow IR → Resume from node N with saved state
- No re-execution of successful nodes, no duplicate side effects

### Phase 1: Foundation Refactoring
Extract workflow execution logic from CLI into reusable services:
- Create `WorkflowExecutorService` class to encapsulate execution logic (~500 lines from CLI)
- Implement `OutputInterface` abstraction for display independence (future REPL support)
- Create `DisplayManager` for reusable UX logic
- Add `update_metadata()` method to WorkflowManager for execution tracking
- Refactor CLI to thin pattern (~200 lines, just command parsing)
- **No user-visible changes** - Same behavior, better architecture

### Phase 2: Repair Service Implementation
Replace RuntimeValidationNode with repair service:
- Remove RuntimeValidationNode from planner flow (12 nodes → 11 nodes)
- Extend `InstrumentedNodeWrapper` with checkpoint tracking (~15 lines)
- Implement unified `execute_workflow()` function where repair is just a flag
- Create LLM-based repair service using claude-3-haiku (fast/cheap)
- Update CLI with `--no-repair` flag (auto-repair enabled by default)
- Enable resume from checkpoint to skip already-executed nodes

### Key Technical Decisions
- **Checkpoint via InstrumentedNodeWrapper**: Extend existing outermost wrapper rather than creating new one
- **Shared store checkpoint**: Store execution state in `shared["__execution__"]` with completed nodes and actions
- **Resume mechanism**: Nodes check if already completed and return cached action without executing
- **Unified execution**: Single `execute_workflow()` function handles both regular and repair cases
- **Display abstraction**: OutputInterface protocol allows Click-independent output
- **Thin CLI pattern**: Maximum reusability by extracting all logic to services

### Critical Implementation Details
- InstrumentedNodeWrapper is always the outermost wrapper in compilation chain
- PocketFlow's `flow.run()` stops on first error by design (no multi-error collection in MVP)
- Test boundary remains at `compile_ir_to_flow()` to maintain mock compatibility
- WorkflowExecutor is a PocketFlow Node, not a service (needs clarification vs WorkflowExecutorService)
- Template context extraction from RuntimeValidationNode should be simplified and ported for repair

### User Experience
When a workflow fails, users will see:
```
Executing workflow (6 nodes):
  fetch_messages... ✓ 1.8s
  get_timestamp... ✗ Command failed

🔧 Auto-repairing workflow...
  • Issue detected: Template ${get_time.stdout} not found

Resuming workflow from checkpoint...
  fetch_messages... ↻ cached
  get_timestamp... ✓ 0.1s
  save_results... ✓ 0.8s
✅ Workflow executed successfully
```

### Self-Healing Capabilities
The repair service enables workflows to automatically adapt to:
- API changes (field renames, response structure changes)
- Environment differences (Mac vs Linux shell commands)
- Credential updates (new API keys, different permissions)
- Template reference errors (wrong field paths)

This makes workflows future-proof and portable across environments without re-planning.

## Test Strategy
Testing will ensure the refactor maintains existing functionality while adding repair capabilities:

### Phase 1 Tests (Foundation)
- Unit tests for WorkflowExecutorService with various execution scenarios
- Test OutputInterface implementations and DisplayManager
- Test WorkflowManager.update_metadata() with concurrent access
- Integration tests verifying CLI works exactly as before
- Verify all existing tests pass without modification

### Phase 2 Tests (Repair)
- Delete 4 RuntimeValidationNode test files (no longer needed)
- Update planner flow tests to expect 11 nodes instead of 12
- Unit tests for checkpoint tracking in InstrumentedNodeWrapper
- Test resume behavior (nodes return cached actions without re-execution)
- Integration tests for complete repair flow (fail → repair → resume → success)
- Test repair with mocked LLM responses
- Verify no duplicate side effects during repair

### Key Test Scenarios
- Workflow executes successfully first time (no repair needed)
- Workflow fails and is automatically repaired
- Resume correctly skips already-executed nodes
- Repair attempts exceed limit (3 attempts max)
- User opts out of repair with --no-repair flag
- Non-fixable errors (auth, rate limits) handled appropriately