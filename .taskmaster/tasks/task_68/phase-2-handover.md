# Task 68 Phase 2 - Implementation Handover

**TO THE PHASE 2 IMPLEMENTING AGENT**: This document contains everything you need to know to successfully implement Phase 2. Read it completely before starting.

## 🎯 Your Mission

Implement Phase 2: **Resume-Based Repair Service** that automatically fixes broken workflows and resumes from the failure point without re-executing successful nodes.

## 📚 Essential Documents to Read First

### Critical Task Documentation
1. **`.taskmaster/tasks/task_68/task-68.md`** - Original task specification
2. **`.taskmaster/tasks/task_68/starting-context/master-architecture-spec.md`** - Architectural vision
3. **`.taskmaster/tasks/task_68/starting-context/phase-2-repair-spec.md`** - Your implementation spec
4. **`.taskmaster/tasks/task_68/starting-context/task-68-handover.md`** - Original insights (MUST READ)
5. **`.taskmaster/tasks/task_68/starting-context/research-findings.md`** - Technical deep dive

### Phase 1 Implementation
6. **`.taskmaster/tasks/task_68/implementation/progress-log.md`** - What was actually built in Phase 1
7. **`.taskmaster/tasks/task_68/starting-context/research-findings-phase1.md`** - Phase 1 research

### PocketFlow Understanding
8. **`pocketflow/__init__.py`** - The 100-line framework (CRITICAL to understand)
9. **`pocketflow/CLAUDE.md`** - PocketFlow documentation guide

## 🏗️ What Phase 1 Built (Your Foundation)

### Created Services (`src/pflow/execution/`)
1. **`OutputInterface`** - Protocol for display operations
2. **`DisplayManager`** - UX logic (barely used in Phase 1, critical for Phase 2)
3. **`WorkflowExecutorService`** - Core execution logic extracted from CLI
4. **`ExecutionResult`** - Structured result dataclass

### Created CLI Support (`src/pflow/cli/`)
5. **`cli_output.py`** - Click implementation of OutputInterface

### Modified Files
6. **`src/pflow/cli/main.py`** - Now thin wrapper using services
7. **`src/pflow/core/workflow_manager.py`** - Added `update_metadata()` method

## 🔑 Critical Technical Knowledge

### 1. InstrumentedNodeWrapper is Your Golden Ticket
**File**: `src/pflow/runtime/instrumented_wrapper.py`

- **ALWAYS the outermost wrapper** (verified at compiler.py:571)
- Already captures shared_before/shared_after
- Has metrics and progress callbacks
- You just add ~15 lines for checkpoint tracking

### 2. Checkpoint Data Structure
Store in `shared["__execution__"]` at ROOT level (never namespaced):
```python
shared["__execution__"] = {
    "completed_nodes": ["fetch", "analyze", "send"],  # Nodes that succeeded
    "node_actions": {                                  # Actions they returned
        "fetch": "default",
        "analyze": "default",
        "send": "default"
    },
    "failed_node": "process"  # Where we failed
}
```

### 3. PocketFlow Execution Model
```python
action = flow.run(shared)
# If ANY node returns "error" action, execution STOPS immediately
# You CANNOT collect multiple errors - PocketFlow stops on first
```

### 4. DisplayManager's Role in Phase 2
In Phase 1, DisplayManager was created but barely used because CLI handlers already manage output. In Phase 2, it becomes critical for showing:
- "🔧 Auto-repairing workflow..."
- "Issue detected: Template ${data.username} not found"
- "Available fields: login, email, bio"
- "Resuming workflow from checkpoint..."
- Node progress with "↻ cached" for resumed nodes

## ⚠️ Critical Warnings

### 1. The Spec vs Reality
The spec shows `display.show_execution_result()` being called in the intermediate function. **DON'T DO THIS**. It breaks existing behavior. The handlers already manage all output correctly.

### 2. Handler Signatures are Sacred
The handler functions have INCONSISTENT parameter orders that MUST be preserved:
- `_handle_workflow_success` - 8 parameters in specific order
- `_handle_workflow_error` - 6 parameters in DIFFERENT order
- `_handle_workflow_exception` - 7 parameters with exception added

### 3. Test Boundaries
Tests mock at `compile_ir_to_flow()`. This signature CANNOT change:
```python
def compile_ir_to_flow(
    ir_json: Union[str, dict[str, Any]],
    registry: Registry,
    initial_params: Optional[dict[str, Any]] = None,
    validate: bool = True,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
) -> Flow:
```

### 4. RuntimeValidationNode Line Numbers
The spec says lines 2745-3201 but it's actually **2882-3387** in `src/pflow/planning/nodes.py`

## 📋 Phase 2 Implementation Checklist

### Step 1: Extend InstrumentedNodeWrapper
**File**: `src/pflow/runtime/instrumented_wrapper.py`

Add checkpoint tracking (~15 lines):
1. Initialize `shared["__execution__"]` if not present
2. Check if node already completed → return cached action
3. Track successful completions
4. Track failed node on error

### Step 2: Extend OutputController
**File**: `src/pflow/core/output_controller.py`

Add support for cached node display:
- Handle "node_cached" event in `create_progress_callback()`
- Show "↻ cached" instead of "✓ X.Xs"

### Step 3: Create Repair Service
**File**: `src/pflow/execution/repair_service.py` (NEW)

Create LLM-based repair:
1. `repair_workflow()` - Main repair function
2. `_analyze_errors_for_repair()` - Extract context from errors
3. `_create_repair_prompt()` - Build LLM prompt
4. `_extract_workflow_from_response()` - Parse LLM response
5. Use `claude-3-haiku` for speed/cost

### Step 4: Create Unified Execution Function
**File**: `src/pflow/execution/workflow_execution.py` (NEW)

The KEY innovation - single function where repair is just a flag:
```python
def execute_workflow(
    workflow_ir: dict,
    execution_params: dict,
    enable_repair: bool = True,  # Just a flag!
    resume_state: Optional[dict] = None,  # For checkpoint resume
    ...
) -> ExecutionResult:
```

### Step 5: Update CLI
**File**: `src/pflow/cli/main.py`

1. Add `--no-repair` flag to disable repair
2. Update `execute_json_workflow()` to use unified execution
3. Default repair to enabled

### Step 6: Remove RuntimeValidationNode
**File**: `src/pflow/planning/flow.py`

Remove RuntimeValidationNode from planner:
- Line 27: Remove from imports
- Line 70: Remove node creation
- Line 89: Remove debug wrapper
- Line 159: **CRITICAL** - Redirect validator output to metadata_generation
- Line 173, 177, 179: Remove flow wiring
- Update node count from 12 to 11

**File**: `src/pflow/planning/nodes.py`
- Lines 2882-3387: Delete RuntimeValidationNode class (NOT 2745-3201!)

### Step 7: Delete Old Tests
Delete these files completely:
- `tests/test_runtime_validation.py`
- `tests/test_runtime_validation_simple.py`
- `tests/test_runtime/test_runtime_validation_core.py`
- `tests/test_planning/integration/test_runtime_validation_flow.py`

## 🎯 Success Criteria

You know Phase 2 is complete when:

1. **Workflow fails at node 3** → Repair fixes issue → **Resumes from node 3**
2. Nodes 1-2 show "↻ cached" (NOT re-executed)
3. No duplicate side effects (no double API calls)
4. User sees clear progress throughout
5. Planner has 11 nodes (not 12)
6. All tests pass

## 💡 Key Insights from Phase 1

### What Worked Well
- Clean separation between CLI and services
- OutputInterface abstraction enables display flexibility
- WorkflowExecutorService is completely Click-independent
- Test design allowed seamless refactoring

### Surprises
- DisplayManager wasn't needed in Phase 1 (handlers already manage output)
- Some helper functions were unused (dead code)
- Test mocks needed updating for new import locations

### The Resume Innovation
Instead of complex caching with keys/invalidation, we use simple checkpoint:
- Execute → Fail → Save entire shared state
- Repair IR → Resume with saved state
- Nodes check if already completed → return cached action
- No re-execution, no side effects, simple!

## 🔧 Implementation Tips

1. **Test frequently** - Run `make test` after each component
2. **Start with InstrumentedNodeWrapper** - It's the simplest change
3. **Mock the LLM** in tests - Don't make real API calls
4. **Preserve test boundaries** - Don't change mock interfaces
5. **Use existing patterns** - Study how RuntimeValidationNode extracted template context

## 📞 If You Get Stuck

1. **Re-read** `.taskmaster/tasks/task_68/starting-context/task-68-handover.md`
2. **Study** how RuntimeValidationNode works before deleting it
3. **Check** the test mocks to understand boundaries
4. **Remember** PocketFlow stops on first error (no multi-error collection)
5. **Verify** InstrumentedNodeWrapper is outermost in compiler

## 🎬 Final Architecture After Phase 2

```
User runs workflow → Fails at node 3
    ↓
🔧 Auto-repairing workflow...
    ↓
Repair service fixes template error
    ↓
Resuming from checkpoint...
  node1... ↻ cached
  node2... ↻ cached
  node3... ✓ 0.5s
  node4... ✓ 0.8s
    ↓
✅ Workflow executed successfully
```

## Your First Steps

1. Read all documents listed above
2. Understand the checkpoint mechanism
3. Start with extending InstrumentedNodeWrapper
4. Test that checkpointing works
5. Then build repair service
6. Finally remove RuntimeValidationNode

Good luck! Phase 1 has built a solid foundation. Phase 2 will make workflows self-healing and resilient.

---

**Remember**: The beauty is in the simplicity. We're not fighting PocketFlow - we're extending it naturally. The shared store was always meant to hold execution state. We're just making it persistent across repair attempts.