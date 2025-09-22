# Current State and Proposed Changes

## Current State (What's Wrong)

### The Problem
1. **RuntimeValidationNode is in the planner flow** - It executes workflows during planning to find errors
2. **Duplicate execution** - Workflows run twice: once for validation, once for real
3. **Side effects during planning** - Sends real messages, updates real sheets during validation
4. **Tight coupling** - Execution logic is embedded in CLI, not reusable
5. **No execution history** - Workflows don't track execution params or errors

### Important Technical Context
The system distinguishes between two types of failures:
- **Workflow Errors**: Nodes return "error" action (controlled failure, e.g., file not found)
- **Workflow Exceptions**: Python exceptions bubble up (unexpected failure, e.g., missing API key)

This distinction affects error handling and repair strategies.

### Current Flow
```
User Request → Planner → RuntimeValidationNode (executes workflow) → Save → CLI (executes AGAIN)
                              ↑                                              ↑
                        Hidden execution                            Duplicate execution!
                        (side effects!)                            (user sees this one)
```

### Current Code Structure
```
src/pflow/
├── planning/
│   ├── flow.py           # Contains RuntimeValidationNode wiring
│   └── nodes.py          # Contains RuntimeValidationNode (lines 2745-3201)
├── cli/
│   └── main.py          # Contains all execution logic (tightly coupled)
└── core/
    └── workflow_manager.py  # No update method, no execution tracking
```

## Proposed Solution

### The Fix
1. **Remove RuntimeValidationNode from planner** - No execution during planning
2. **Single execution** - Workflows run once, after planning
3. **Repair on failure** - If execution fails, user can choose to repair
4. **Decoupled execution** - WorkflowExecutorService is reusable
5. **Execution tracking** - Metadata tracks params, errors, history

### New Flow
```
SUCCESS PATH:
User Request → Planner (no execution) → Save → CLI executes ONCE → Success ✅

FAILURE PATH:
User Request → Planner → Save → CLI executes → Fails → Prompt user
                                                            ↓
                                                   "Try to fix?" → Yes
                                                            ↓
                                                     Repair Service
                                                   (diagnose & fix)
                                                            ↓
                                                    Execute fixed → Success ✅
```

### New Code Structure
```
src/pflow/
├── planning/
│   ├── flow.py           # No RuntimeValidationNode (11 nodes instead of 12)
│   └── nodes.py          # RuntimeValidationNode REMOVED
├── cli/
│   └── main.py          # Thin wrapper using WorkflowExecutorService
├── core/
│   ├── workflow_manager.py        # WITH update_metadata() method
│   └── workflow_executor_service.py  # NEW - Reusable execution service
└── repair/              # NEW MODULE
    ├── repair_flow.py   # Repair orchestration
    ├── nodes.py         # WorkflowExecutorNode (was RuntimeValidationNode)
    └── repair_service.py  # High-level repair API
```

## Key Benefits of the Change

### For Users
1. **Better first experience** - Transparent auto-repair instead of hidden validation
2. **No duplicate side effects** - Messages sent once, not twice
3. **Self-healing workflows** - Workflows automatically adapt to:
   - API changes (field renames, response structure changes)
   - Environment differences (Mac vs Linux shell commands)
   - Credential updates (new API keys, different permissions)
   - System changes (different file paths, installed tools)
4. **Visible progress** - Users see what's happening during repair using familiar format:
   ```
   🔧 Auto-repairing workflow...
     • Issue detected: Template ${get_time.stdout} not found
   Executing workflow (4 nodes):
     get_timestamp... ✗ Validation stopped
   ✅ Workflow repaired successfully!
   ```
5. **Future-proof workflows** - Repair months later without re-planning

### For Developers
1. **Clean architecture** - Planning and repair are separate concerns
2. **Reusable components** - WorkflowExecutorService used everywhere
3. **Testable** - Each component can be tested independently
4. **Maintainable** - Clear separation of responsibilities

## Implementation Strategy

### Phase 1: Foundation (Can start immediately)
- Create WorkflowExecutorService
- Add metadata tracking
- Refactor CLI to use service
- **No user-visible changes**

**⚠️ Critical Limitation Discovered**: PocketFlow's `flow.run()` stops on first error by design (returns action string, not result object). The proposed `abort_on_first_error=False` mode cannot work natively. To collect multiple errors would require custom node-by-node execution logic similar to what RuntimeValidationNode currently implements. For Phase 1, we'll only capture the first error even when `abort_on_first_error=False`.

### Phase 2: Repair Service (After Phase 1)
- Remove RuntimeValidationNode
- Create repair module
- Add CLI repair prompt
- **User-visible improvement**: repair on failure

**Note**: The repair service benefits from RuntimeValidationNode's existing multi-error collection logic, which can be adapted for the WorkflowExecutorNode.

## Migration Path

### What Changes for Existing Code
1. **Planner tests** - Update node count from 12 to 11
2. **Flow structure tests** - Remove RuntimeValidationNode references
3. **CLI execution** - Now uses WorkflowExecutorService
4. **Workflow metadata** - Now includes execution history

### What Stays the Same
1. **Planner interface** - Same API, same usage
2. **Workflow format** - IR structure unchanged
3. **Node implementations** - All nodes work the same
4. **User commands** - Same CLI commands work

## Metrics for Success

### Phase 1 Success
- [ ] All existing tests pass
- [ ] CLI works exactly as before
- [ ] Metadata tracks executions
- [ ] WorkflowExecutorService works with both error modes

### Phase 2 Success
- [ ] No more duplicate execution
- [ ] Repair prompt works after failure
- [ ] Progress visible during repair
- [ ] All tests updated and passing

## Risk Mitigation

### Backwards Compatibility
- Old workflows without execution metadata will still work
- Existing CLI commands unchanged
- Planner API remains the same

### Testing Strategy
1. Phase 1: Refactor with no behavior change (safe)
2. Extensive testing between phases
3. Phase 2: Add repair as new feature (additive)

## The Killer Feature: Self-Healing Workflows

This architecture enables **self-healing workflows** - a major differentiator:

**Traditional Workflow Tools**:
- Break when APIs change
- Fail in different environments
- Require manual fixing
- Need complete regeneration

**pflow with Repair Service**:
- Automatically adapts to API changes
- Fixes environment-specific issues
- Shows transparent repair process
- Preserves workflow logic while fixing issues

### Example Scenarios

1. **API Evolution**: Slack changes `username` to `user_name`
   - Workflow breaks → Auto-repair detects → Fixes field reference → Continues

2. **Cross-Platform**: Workflow created on Mac, run on Linux
   - Shell commands fail → Auto-repair detects → Adapts commands → Works

3. **Credential Changes**: New API key with different permissions
   - Auth fails → Auto-repair detects → Adjusts approach → Succeeds

## Timeline Estimate

- **Phase 1**: 4-6 hours (mostly refactoring)
- **Testing**: 2-3 hours
- **Phase 2**: 6-8 hours (new functionality)
- **Testing**: 3-4 hours
- **Total**: ~20 hours for complete implementation

---

This document provides the context for why we're making these changes and what the end state will look like.