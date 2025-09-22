# Task 68 Implementation Handover

**⚠️ TO THE IMPLEMENTING AGENT**: Read this entire document before starting. This contains critical insights that aren't obvious from the specs. At the end, confirm you're ready to begin.

## 🔥 The Journey That Changed Everything

We started thinking we needed a complex caching system with keys, invalidation, and side-effect analysis. Through a long exploration, we discovered something beautiful: **we don't need caching at all**. We need **resume from checkpoint**.

The user had the key insight: *"What we are essentially doing here is just skipping the nodes that have been executed and continuing from where we left off with exactly the same shared store as before."*

This completely reframed the problem from "optimize repeated execution" to "continue from failure point" - a much simpler and more natural approach for PocketFlow.

## 🎯 Critical Realizations You MUST Understand

### 1. WorkflowExecutor is NOT What You Think
**File**: `src/pflow/runtime/workflow_executor.py`

This is NOT a service! It's a PocketFlow Node that gets compiled into workflows for nested execution. We need to build WorkflowExecutorService from SCRATCH by extracting ~500 lines of logic from `src/pflow/cli/main.py:execute_json_workflow()`.

### 2. InstrumentedNodeWrapper is Your Golden Ticket
**File**: `src/pflow/runtime/instrumented_wrapper.py`

This wrapper is ALWAYS the outermost wrapper (applied last in compilation). It already:
- Captures state before/after execution
- Handles errors gracefully
- Has progress callbacks
- Tracks metrics

You just need to add ~15 lines for checkpoint tracking. Don't create a new wrapper!

### 3. PocketFlow Stops on First Error (By Design!)
```python
action = flow.run(shared)
# If ANY node returns "error" action, execution STOPS
# You CANNOT collect multiple errors without custom node-by-node execution
```

The specs mention `abort_on_first_error` parameter - this is aspirational. For MVP, it's just a placeholder. Both modes will capture only the first error.

## 💡 Non-Obvious Architectural Decisions

### Why Unified Execution Function
The user strongly pushed for a single `execute_workflow()` function where repair is just a boolean flag. They specifically said: *"If possible we should definitely try to have a Thin CLI, using your proposed option A."*

This means:
- CLI should be ~200 lines (just command parsing)
- ALL logic in services
- Repair isn't a separate path, it's a feature of execution

### Why Haiku for Repair (Not Sonnet)
We chose `claude-3-haiku` for repairs because:
- Repair is simpler than generation (fixing vs creating)
- We want fast iteration (user might wait)
- Cost matters when doing multiple attempts
- The user cares about the "demo experience"

### Why Not Rename WorkflowExecutor Yet
We suggested renaming `WorkflowExecutor` → `NestedWorkflowNode` but the user said: *"We currently do not support nested workflows so we don't have to worry about this right now but renaming it would be good."*

So rename it but know it's not critical for MVP.

## 🚨 Gotchas That Will Bite You

### 1. Shared Store Namespacing is Tricky
- Node outputs: `shared["node_id"]["field"]` (namespaced)
- System keys: `shared["__execution__"]` (NOT namespaced, always root)
- Templates: `${node_id.field}` (reference namespaced data)

Your checkpoint data goes in `shared["__execution__"]` at ROOT level.

### 2. OutputController Missing Method
The specs mention `display_cached_node()` but this method DOESN'T EXIST. You need to:
1. Add handling for `"node_cached"` event in `create_progress_callback()`
2. Show `↻ cached` instead of `✓ X.Xs` for resumed nodes

### 3. Template Context is Critical for Repair
RuntimeValidationNode (lines 2745-3201) has sophisticated template extraction. The key insight: don't just say "field missing", say "you tried 'username', available fields are: login, bio, email".

You should port a SIMPLIFIED version to help the repair LLM understand what to fix.

### 4. Test Boundary is compile_ir_to_flow
Tests extensively mock at this boundary. Your WorkflowExecutorService must call this function so existing mocks work:
```python
flow = compile_ir_to_flow(workflow_ir, ...)  # This gets mocked
result = flow.run(shared_store)
```

## 📍 User's Strong Preferences

1. **Auto-repair by default** - The user was adamant: all workflows should have repair enabled by default
2. **Thin CLI** - "Avoid as much code as possible in the CLI"
3. **Display independence** - Build for future REPL, not just Click
4. **Happy path assumptions** - "Just assume the happy case" for caching complexity
5. **Don't optimize for tests** - "Focus on core functionality... rewrite tests as needed"

## 🔗 Critical Code Locations

### Must Study:
- `src/pflow/cli/main.py:1391-1462` - The execute_json_workflow() to extract
- `src/pflow/runtime/instrumented_wrapper.py:285-345` - Where to add checkpoint
- `src/pflow/planning/nodes.py:2745-3201` - RuntimeValidationNode (delete but study template extraction first!)
- `src/pflow/core/output_controller.py` - Needs extension for cached display

### Will Create:
- `src/pflow/execution/` - New module for all execution logic
- `src/pflow/execution/workflow_execution.py` - The unified execute_workflow()
- `src/pflow/cli/cli_output.py` - Click-specific OutputInterface

## 🧩 The Checkpoint Data Structure

This is the key innovation - store execution state in shared:
```python
shared["__execution__"] = {
    "completed_nodes": ["fetch", "analyze", "send"],
    "node_actions": {
        "fetch": "default",
        "analyze": "default",
        "send": "default"
    },
    "failed_node": "process"  # Where we failed
}
```

When InstrumentedNodeWrapper sees a node in `completed_nodes`, it returns the cached action WITHOUT executing.

## ⚡ Implementation Order That Will Work

### Phase 1 Must Complete First
1. Extract WorkflowExecutorService (big job - ~500 lines from CLI)
2. Create OutputInterface abstraction
3. Thin CLI refactor
4. Test everything still works

### Phase 2 Builds on Phase 1
1. Extend InstrumentedNodeWrapper (just ~15 lines!)
2. Create repair service
3. Remove RuntimeValidationNode
4. Test repair flow

Don't try to do both phases at once. Phase 1 is substantial extraction work.

## 🎬 The Final Architecture

```python
# Ultra-thin CLI
result = execute_workflow(ir, params, enable_repair=True)
sys.exit(0 if result.success else 1)

# Unified execution (repair is just a flag)
def execute_workflow(..., enable_repair=True):
    # Execute
    result = executor.execute_workflow(shared_store=shared)

    if result.success:
        return result

    if not enable_repair:
        return result

    # Repair and resume with same shared store!
    repaired_ir = repair_workflow(ir, result.errors)
    return execute_workflow(repaired_ir, resume_state=result.shared_after)
```

## 🔴 What Could Go Wrong

1. **Checkpoint corruption** - Validate structure before trusting
2. **Infinite repair loop** - Hard stop at 3 attempts
3. **Breaking tests** - Keep exact same interfaces, add don't modify
4. **Wrong wrapper order** - InstrumentedNodeWrapper MUST be outermost

## 📚 Documents You Must Read

In `.taskmaster/tasks/task_68/starting-context/`:
- `master-architecture-spec.md` - The vision
- `phase-1-foundation-spec.md` - Your first implementation
- `phase-2-repair-spec.md` - Your second implementation
- `research-findings.md` - All the discoveries

## 🎯 Definition of Success

You'll know you succeeded when:
1. Workflow fails at node 3
2. Repair fixes the issue
3. Execution resumes from node 3 (nodes 1-2 show "↻ cached")
4. No duplicate side effects
5. User sees clear progress throughout

## Final Critical Insight

The beauty of this approach is that we're not fighting PocketFlow - we're extending it naturally. The shared store was always meant to hold execution state. We're just making that state persistent across repair attempts.

---

**TO THE IMPLEMENTING AGENT**: You now have all the context. The specs in `starting-context/` folder have the implementation details. This handover contains the "why" and the gotchas.

Please confirm you've read this document and are ready to begin implementing Task 68.