# IR Compiler Design Decisions

This document outlines critical design decisions needed for implementing the IR compiler (Task 4) that transforms validated IR JSON into executable PocketFlow Flow objects.

## 1. Node Parameter Handling - Decision Importance: 2 (Reduced from 4)

After deep investigation, PocketFlow has a clear, established pattern for parameter handling that we should follow.

### Context:
- IR nodes have a `params` field: `{"type": "read-file", "params": {"path": "input.txt"}}`
- PocketFlow nodes have `self.params` dict and `set_params()` method built-in
- The `Flow._orch()` method in PocketFlow already calls `node.set_params()` during execution
- Clear distinction in PocketFlow:
  - **Shared Store**: For data that flows between nodes (content, results)
  - **Parameters**: For static configuration (model names, temperatures, identifiers)
- pflow's "simple node" pattern: Check shared store first, then params as fallback

### From PocketFlow source (`__init__.py` lines 98-101):
```python
def _orch(self, shared, params=None):
    curr, p, last_action = copy.copy(self.start_node), (params or {**self.params}), None
    while curr:
        curr.set_params(p)  # Flow automatically calls set_params
```

### Options:

- [x] **Option A: Use set_params() - The PocketFlow Way**
  - Instantiate node: `node = NodeClass()`
  - Set params: `node.set_params(ir_node["params"])`
  - This is the established PocketFlow pattern shown in all examples
  - The compiler sets params, nodes access via `self.params`
  - Pros: Standard PocketFlow pattern, all examples use this
  - Cons: None - this is how PocketFlow is designed to work

- [ ] ~~Option B: Create wrapper nodes~~ (Violates PocketFlow patterns)
- [ ] ~~Option C: Modify nodes~~ (Unnecessary - PocketFlow already supports this)

**Decision**: Option A - This isn't really a choice; it's the correct PocketFlow pattern.

## 2. Template Variable Resolution - Decision Importance: 4 (Increased from 3)

The IR supports template variables (`$variable` syntax) and this is critical for the "Plan Once, Run Forever" philosophy.

### Context:
- IR can contain: `{"path": "$input_file"}`, `{"prompt": "Analyze: $content"}`
- Task 19 creates a planner-internal template resolver utility
- Templates enable workflow reuse with different runtime values
- The integration guide shows template resolution happening in the compiler
- Template variables are core to pflow's value proposition

### New Insights:
- From integration guide: The compiler example shows params being passed directly to nodes
- Templates in params allow reusable workflows (key MVP feature)
- The planner generates workflows with template variables
- Runtime values come from shared store or CLI parameters

### Options:

- [ ] **Option A: Resolve templates during compilation**
  - Compiler takes IR + template values, resolves before node creation
  - Pros: Simple for nodes, they get final values
  - Cons: **Breaks workflow reusability** - can't run same workflow with different values

- [x] **Option B: Pass templates to nodes, let simple nodes handle it**
  - Pass template strings as-is to `node.set_params()`
  - Simple nodes already check shared store first (where runtime values live)
  - For template params, nodes can resolve during `prep()` using shared store
  - Pros: Enables true workflow reuse, aligns with pflow design
  - Cons: Nodes need template awareness (but simple nodes already do this)

- [ ] **Option C: Compiler partially resolves known values**
  - Resolve what's available, pass remaining templates to nodes
  - Pros: Flexible approach
  - Cons: Complex logic, inconsistent behavior

**Updated Recommendation**: Option B - Pass templates to nodes. This maintains workflow reusability and aligns with the simple node pattern where nodes check shared store for dynamic values.

## 3. Module Organization - Decision Importance: 2

Where should the compiler module live in the codebase?

### Context:
- No `src/pflow/runtime/` directory exists yet
- Related code in `src/pflow/core/` (IR schema)
- Scanner/registry in `src/pflow/registry/`

### Options:

- [x] **Option A: Create runtime package at src/pflow/runtime/**
  - New module: `src/pflow/runtime/compiler.py`
  - Pros: Clear separation, follows task specification
  - Cons: New directory for single module

- [ ] **Option B: Add to core package**
  - New module: `src/pflow/core/compiler.py`
  - Pros: Keeps IR-related code together
  - Cons: Core might get too large

**Recommendation**: Option A - Follows task spec, good separation of concerns.

## 4. Error Handling Strategy - Decision Importance: 3

How should the compiler handle errors during Flow construction?

### Context:
- Node imports can fail (ImportError, AttributeError)
- Node instantiation can fail
- BaseNode inheritance verification can fail
- Edge connections can reference non-existent nodes
- Registry lookups can fail
- The integration guide specifically mentions handling ImportError and AttributeError

### Options:

- [x] **Option A: Fail fast with descriptive errors**
  - Raise custom CompilationError with detailed context
  - Include: node ID, node type, import path, specific error reason
  - Example: `CompilationError: Failed to import node 'github-get-issue' (id: n1): No module named 'pflow.nodes.github'`
  - Pros: Clear errors, easier debugging, follows Python conventions
  - Cons: Stops at first error

- [ ] **Option B: Collect all errors and report**
  - Try to compile entire flow, collect all errors
  - Return comprehensive error report
  - Pros: See all issues in one pass
  - Cons: Complex state management, harder to implement correctly

**Recommendation**: Option A - Clear, actionable error messages are crucial for developer experience.

## 5. Start Node Handling - Decision Importance: 2

How to handle the optional start_node field in IR?

### Context:
- IR schema: start_node is optional
- If not specified, use first node in array
- PocketFlow Flow requires explicit start node

### Options:

- [x] **Option A: Use first node as default**
  - If no start_node specified: `start = nodes[0]`
  - Matches IR schema documentation
  - Pros: Simple, intuitive behavior
  - Cons: Implicit behavior

- [ ] **Option B: Require explicit start_node**
  - Raise error if not specified
  - Pros: Explicit, no ambiguity
  - Cons: Breaks IR schema contract

**Recommendation**: Option A - Follow IR schema specification.

## 6. Dynamic Import Pattern - Implementation Requirement (NOT a decision)

The registry stores metadata only (JSON strings), not class references. This is an architectural constraint, not a choice.

### Context:
- Registry is stored as JSON: `~/.pflow/registry.json`
- JSON can only store strings: `{"module": "pflow.nodes.file.read_file", "class_name": "ReadFileNode"}`
- Task 5 (scanner) and Task 4 (compiler) are separate components that don't share Python objects
- Must use dynamic imports to load node classes from their string paths

### Required Implementation:
```python
# This is the only way to do it:
module = importlib.import_module(metadata["module"])
NodeClass = getattr(module, metadata["class_name"])

# With proper error handling:
try:
    module = importlib.import_module(metadata["module"])
except ImportError as e:
    raise CompilationError(f"Cannot import module '{metadata['module']}': {e}")

try:
    NodeClass = getattr(module, metadata["class_name"])
except AttributeError:
    raise CompilationError(f"Module has no class '{metadata['class_name']}'")

# Validate inheritance
if not issubclass(NodeClass, (pocketflow.BaseNode, pocketflow.Node)):
    raise CompilationError(f"Node class must inherit from BaseNode or Node")
```

**This is not a decision** - it's the required implementation given the system architecture.

## 7. Edge Action Handling - Decision Importance: 3 (NEW)

How to handle action-based routing when connecting nodes?

### Context:
- IR edges have optional "action" field (default: "default")
- PocketFlow uses `>>` for default connections
- PocketFlow uses `-` operator for action-based routing: `node1 - "error" >> error_handler`
- From integration guide example: Connection logic shown

### Options:

- [x] **Option A: Simple conditional based on action**
  ```python
  if action == "default" or not action:
      from_node >> to_node
  else:
      from_node - action >> to_node
  ```
  - Pros: Clear, matches PocketFlow patterns exactly
  - Cons: None

- [ ] **Option B: Always use the `-` operator**
  - Use `from_node - action >> to_node` for all connections
  - Pros: Single code path
  - Cons: Less readable, "default" action is implicit in PocketFlow

**Decision**: Option A - Matches PocketFlow's intended usage patterns.

## Next Steps

With these updated insights and decisions:
1. **Parameter handling** is clear - use `set_params()`
2. **Template resolution** should pass templates to nodes for reusability
3. **Module organization** follows the task specification
4. **Error handling** should fail fast with clear messages
5. **Start node** uses first node as default per schema
6. **Dynamic imports** with proper validation
7. **Edge connections** follow PocketFlow patterns

All critical decisions have been addressed. The implementation path is now clear.

## Essential Documentation References

This section lists all the important documentation and files referenced in this document that are crucial for understanding Task 4 implementation.

### Core PocketFlow Documentation
- **`pocketflow/__init__.py`** - The 100-line framework source code. Essential for understanding Node, Flow, and parameter handling
- **`pocketflow/CLAUDE.md`** - PocketFlow repository map and component overview
- **`pocketflow/docs/core_abstraction/node.md`** - Node lifecycle and parameter patterns
- **`pocketflow/docs/core_abstraction/flow.md`** - Flow orchestration and >> operator usage
- **`pocketflow/docs/core_abstraction/communication.md`** - Shared store vs parameters distinction

### pflow Architecture Documentation
- **`docs/architecture/pflow-pocketflow-integration-guide.md`** - Critical insights about how pflow extends PocketFlow (MUST READ)
- **`docs/architecture/pocketflow-interface-guide.md`** - How to interface with PocketFlow components
- **`docs/architecture/architecture.md`** - Overall system architecture
- **`docs/core-concepts/schemas.md`** - JSON IR schema details
- **`docs/core-concepts/registry.md`** - Registry structure and metadata format
- **`docs/features/simple-nodes.md`** - Simple node pattern (shared-first, params-fallback)

### Task-Specific References
- **`.taskmaster/tasks/tasks.json`** - Task 4 definition and requirements
- **`src/pflow/core/ir_schema.py`** - IR schema implementation (Task 6 output)
- **`src/pflow/registry/scanner.py`** - Registry scanner implementation (Task 5 output)
- **`src/pflow/registry/registry.py`** - Registry class implementation (Task 5 output)

### Example Implementations
- **`pocketflow/cookbook/pocketflow-batch-flow/`** - Shows BatchFlow parameter usage
- **`pocketflow/cookbook/pocketflow-workflow/`** - Shows node chaining patterns
- **`src/pflow/nodes/test_node.py`** - Test nodes showing BaseNode inheritance

### Key Concepts from Documentation

1. **From pflow-pocketflow-integration-guide.md**:
   - PocketFlow IS the execution engine (don't reimplement)
   - No wrapper classes needed
   - Shared store is just a dict
   - Template resolution is string substitution
   - Extend, don't wrap

2. **From PocketFlow source**:
   - `Flow._orch()` automatically calls `set_params()` on nodes
   - Nodes access parameters via `self.params` dictionary
   - `>>` operator for default connections, `-` operator for actions

3. **From Task 4 specifications**:
   - Registry provides metadata ONLY (not class references)
   - Must use `importlib.import_module()` for dynamic imports
   - Must verify BaseNode/Node inheritance
   - Include proper error handling for ImportError and AttributeError

This document is specifically for **Task 4: Implement IR-to-PocketFlow Object Converter** and should be moved to `.taskmaster/tasks/task_4/research/` for reference during implementation.
