# Task 68: Master Architecture Specification
## Unified Execution and Resume-Based Repair System

### Executive Summary

This task refactors pflow's workflow execution architecture to create a unified, resume-based repair system that eliminates duplicate execution and enables self-healing workflows. The key innovation is using workflow resume from checkpoint rather than complex caching, making repair a natural extension of execution rather than a separate system.

### Core Architectural Vision

```
                    ┌─────────────────────────┐
                    │    Thin CLI Layer       │
                    │  (Command parsing only) │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │   execute_workflow()    │
                    │  THE execution function │
                    │  (Repair is just a flag)│
                    └───────────┬─────────────┘
                                │
                ┌───────────────┼───────────────┐
                ▼               ▼               ▼
        ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
        │ Executor     │ │ Display      │ │ Repair       │
        │ Service      │ │ Manager      │ │ Service      │
        └──────────────┘ └──────────────┘ └──────────────┘
                │
        ┌───────▼────────┐
        │ InstrumentedNodeWrapper │
        │ (Checkpoint tracking)   │
        └─────────────────────────┘
```

### Key Architectural Decisions

#### 1. **Thin CLI Pattern (Option A)**
- CLI only handles command parsing and exit codes
- All execution logic extracted to services
- Maximum reusability for future interfaces (REPL, API, etc.)

#### 2. **Resume-Based Repair (Not Caching)**
- Execute workflow → Fail at node N → Save entire shared state
- Repair workflow IR → Resume from node N with saved state
- No complex cache keys, no invalidation, no side effect analysis

#### 3. **Unified Execution Function**
- Single `execute_workflow()` handles all cases
- Repair is a boolean flag, not a separate code path
- Lazy instantiation of repair components (only when needed)

#### 4. **Checkpoint via InstrumentedNodeWrapper**
- Extend existing outermost wrapper (no new wrapper needed)
- Track execution in `shared["__execution__"]`
- Automatic resume when checkpoint data present
- **VERIFIED**: InstrumentedNodeWrapper is guaranteed to be outermost (compiler.py:571)

#### 5. **Display Abstraction**
- `OutputInterface` protocol (Click-independent)
- `DisplayManager` encapsulates all UX logic
- Reusable across CLI, repair service, future UIs

### The Resume Innovation

Instead of complex per-node caching with keys and invalidation, we use a simple checkpoint mechanism:

```python
# Execution checkpoint stored in shared store
shared["__execution__"] = {
    "completed_nodes": ["fetch", "analyze", "send"],  # Nodes that succeeded
    "node_actions": {                                  # Actions they returned
        "fetch": "default",
        "analyze": "default",
        "send": "default"
    }
}
```

When resuming:
1. InstrumentedNodeWrapper checks if node already completed
2. If yes, returns cached action without executing
3. If no, executes normally and records completion
4. Downstream nodes continue with exact same data flow

### Component Architecture

#### 1. **WorkflowExecutorService**
- Extracted from CLI's execute_json_workflow()
- Handles compilation, registry, metrics, tracing
- Returns structured ExecutionResult
- Manages shared store lifecycle

#### 2. **DisplayManager**
- Encapsulates all user-facing output
- Context-aware messages (execution vs repair vs resume)
- Format-aware (text, JSON, verbose modes)
- Progress callbacks for interactive display

#### 3. **Repair Service**
- LLM-based workflow correction
- Analyzes errors with template context
- Returns corrected workflow IR
- Minimal, focused responsibility

#### 4. **Modified InstrumentedNodeWrapper**
- Adds checkpoint tracking to existing wrapper
- Detects resume state automatically
- Shows cached indicator in progress display
- Zero changes to compilation order

### User Experience

#### Success Path (No Repair Needed)
```
Executing workflow (4 nodes):
  fetch_data... ✓ 1.2s
  process... ✓ 2.3s
  validate... ✓ 0.5s
  save... ✓ 0.8s
✅ Workflow executed successfully
```

#### Repair Path (Auto-Fix with Resume)
```
Executing workflow (4 nodes):
  fetch_data... ✓ 1.2s
  process... ✓ 2.3s
  validate... ✗ Failed

🔧 Auto-repairing workflow...
  • Issue detected: Template ${data.username} not found
  • Available fields: login, email, bio

Resuming workflow from checkpoint...
  fetch_data... ↻ cached
  process... ↻ cached
  validate... ✓ 0.5s
  save... ✓ 0.8s
✅ Workflow executed successfully
```

### Implementation Phases

#### Phase 1: Foundation Refactoring
- Extract WorkflowExecutorService from CLI
- Create OutputInterface abstraction
- Implement DisplayManager
- Thin CLI refactoring
- Add update_metadata() to WorkflowManager

#### Phase 2: Repair Service Implementation
- Remove RuntimeValidationNode from planner
- Extend InstrumentedNodeWrapper with checkpoint tracking
- Implement repair service with LLM
- Create unified execute_workflow() function
- Integration and testing

### Benefits Over Previous Approaches

| Aspect | Old (RuntimeValidation) | Caching Approach | Resume Approach |
|--------|------------------------|------------------|-----------------|
| Duplicate Execution | Yes (planning + real) | Avoided via cache | Avoided via checkpoint |
| Side Effects | Duplicated | Complex analysis | Natural skip |
| Implementation | Complex validation | Cache key generation | Simple state check |
| Maintenance | Scattered logic | Cache invalidation | Self-contained |
| PocketFlow Fit | Foreign concept | Bolted on | Native pattern |

### Critical Success Factors

1. **No Breaking Changes**: All existing workflows continue to work
2. **Transparent Repair**: Users see clear progress during repair
3. **Performance**: Resume eliminates re-execution overhead
4. **Simplicity**: Less code than current implementation
5. **Testability**: Clean boundaries between components

### Risk Mitigation

1. **Incremental Implementation**: Phase 1 works standalone, Phase 2 builds on it
2. **Feature Flag**: `--no-repair` disables repair for debugging
3. **Backward Compatibility**: Old workflows without checkpoints still execute
4. **Test Coverage**: Comprehensive tests for each component

### Future Extensions

This architecture enables:
- Persistent checkpoints (resume across sessions)
- Partial workflow execution (start from checkpoint)
- Workflow debugging (inspect checkpoint state)
- Distributed execution (checkpoint as handoff)
- Time-travel debugging (multiple checkpoints)

### Conclusion

This architecture achieves the original goal of eliminating duplicate execution while being simpler, more maintainable, and more aligned with PocketFlow's design philosophy than any alternative approach. The resume-based repair system transforms workflows from brittle scripts into self-healing, resilient automation.