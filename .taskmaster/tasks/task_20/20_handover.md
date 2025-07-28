# Task 20 Handoff: WorkflowNode Implementation

**IMPORTANT**: Do not begin implementing immediately. Read this handoff completely and confirm you understand before starting.

## Critical Realizations That Will Save You Hours

### 1. We're NOT Using PocketFlow's Flow-as-Node Capability
I spent significant time confused about this. PocketFlow allows `Flow` objects to be used as nodes directly:
```python
inner_flow = Flow(start=node1)
outer_flow = Flow(start=inner_flow)  # This works!
```

**But WorkflowNode doesn't use this**. Instead, it's a regular node that happens to load and execute a Flow in its `exec()` method. This is architecturally correct because we need:
- Dynamic loading from files
- Parameter mapping
- Storage isolation

Don't try to "fix" this - it's intentional and correct.

### 2. There's No Architectural Mismatch
I initially panicked thinking WorkflowNode violated the node model because nodes are Python classes and workflows are JSON files. **This is wrong**. Nodes regularly load external files:
- `ReadFileNode` loads text files
- `WorkflowNode` loads workflow files

The registry stores the WorkflowNode class normally. The workflow files are loaded at runtime, not discovered by the scanner.

### 3. Registry Passing is Tricky
The compiler needs the registry to compile sub-workflows. Current approach:
- Registry is passed to compiler as parameter
- WorkflowNode needs it during execution
- **Don't** put it in shared storage (mixing concerns)
- The implementation passes it via `self.params.get("__registry__")` - this works but feels hacky

### 4. Critical Safety Checks You MUST Implement
These aren't optional:
1. **Circular dependency detection**: Use `_pflow_stack` in shared storage
2. **Max depth enforcement**: Default 10, configurable
3. **Path traversal security**: Validate workflow_ref paths
4. **File size limit**: 10MB max
5. **Reserved key prefix**: `_pflow_*` for internal use

### 5. Storage Isolation Gotchas
- **Mapped mode**: Creates NEW dict with only mapped params
- **Shared mode**: Same reference as parent (dangerous!)
- **Scoped mode**: Filters parent keys by prefix
- Always preserve `_pflow_*` keys for execution context

### 6. Template Resolution Works Differently Than Expected
Templates are resolved at runtime, not compile time. This means:
- WorkflowNode might be wrapped with `TemplateAwareNodeWrapper`
- Child workflows get their own template resolution context
- Parent's `initial_params` don't automatically flow to child

### 7. Error Context is Critical
Without proper error context, debugging nested workflows is impossible. The `WorkflowExecutionError` class with workflow path tracking is essential, not nice-to-have.

### 8. Hidden System Limitations
From my investigation:
- No execution timeouts anywhere in pflow
- Shared storage has no size limits (memory exhaustion risk)
- `copy.copy()` is used for nodes (shallow copy issues)
- Registry loaded from disk on every compilation (performance)

### 9. Test Infrastructure Gaps
- No existing test nodes to use in integration tests
- Mock registry pattern needed everywhere
- Testing storage isolation requires careful setup

### 10. The Workflow Loading Pattern Already Exists
Don't reinvent: `src/pflow/planning/context_builder.py` has `_load_saved_workflows()` that shows the expected workflow structure. Reuse or align with this pattern.

## Files You'll Need

### Files the Main Agent MUST Read Personally:
These contain critical context that affects all decisions:
- `/Users/andfal/projects/pflow/scratchpads/nested-workflows/workflownode-comprehensive-context.md` - Full context (READ FIRST)
- `/Users/andfal/projects/pflow/scratchpads/nested-workflows/workflownode-implementation-plan.md` - Your implementation roadmap
- `/Users/andfal/projects/pflow/pocketflow/__init__.py` (lines 98-113) - Flow._orch() method to understand execution
- `/Users/andfal/projects/pflow/src/pflow/runtime/compiler.py` (lines 253-328) - _instantiate_nodes() function

### Files to Delegate to Subagents:
These can be investigated in parallel when needed:
- `/Users/andfal/projects/pflow/src/pflow/runtime/node_wrapper.py` - For template resolution details
- `/Users/andfal/projects/pflow/src/pflow/planning/context_builder.py` - For workflow loading pattern
- `/Users/andfal/projects/pflow/src/pflow/nodes/file/` - For node implementation patterns
- `/Users/andfal/projects/pflow/tests/test_nodes/` - For test patterns
- All the analysis documents in `/Users/andfal/projects/pflow/scratchpads/nested-workflows/critical-user-decisions/` - For deeper understanding if confused

## What I'd Be Mad at Myself for Not Mentioning

1. **The `node.set_params()` pattern is sacred** - Nodes are instantiated with no constructor params, then `set_params()` is called. Don't try to pass params to `__init__`.

2. **Shared storage keys can be ANYTHING** - Users might have keys that conflict with your internal keys. That's why `_pflow_*` prefix is critical.

3. **The compiler validation happens BEFORE node execution** - But for sub-workflows, you're compiling during execution. Handle compilation errors gracefully.

4. **PocketFlow's `_orch()` method has a TODO comment** about parameter handling that affects nested workflows. Be aware but don't try to fix it.

5. **There's no workflow versioning** - `ir_version` field exists but isn't used. Don't assume version compatibility.

## Quick Sanity Checks

Before you start:
1. Can you explain why we're NOT using Flow-as-Node?
2. Do you understand the four storage isolation modes?
3. Are you clear on the reserved key prefix pattern?
4. Do you see why circular dependency detection is critical?

## Final Critical Warning

The most dangerous assumption is thinking WorkflowNode is special. It's not. It's just a node that loads and runs workflows. Keep it simple, follow the patterns, implement the safety checks, and it will work.

Good luck!
