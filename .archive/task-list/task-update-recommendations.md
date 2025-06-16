# Specific Task Update Recommendations

## Task #2: Implement basic shared store

### Current State:
```json
{
  "title": "Implement basic shared store",
  "description": "Create the core shared store class with simple dictionary-based implementation and natural key patterns",
  "details": "Create src/pflow/core/shared_store.py with SharedStore class that wraps pocketflow's shared dictionary pattern..."
}
```

### Recommended Update:
```json
{
  "title": "Implement shared store validation utilities",
  "description": "Create validation functions for shared store keys and natural patterns without wrapping the dictionary",
  "details": "Create src/pflow/core/store_utils.py with validation functions: validate_reserved_keys() to check for reserved keys like 'stdin', validate_natural_keys() for key pattern validation, and resolve_template_variables() for $variable substitution. No class wrapper needed - pocketflow already provides the dict pattern. These utilities will be used by the CLI resolver and runtime components."
}
```

**Rationale**: PocketFlow already provides the shared dictionary pattern. We only need validation and utility functions, not a wrapper class.

## Task #21: Create execution engine with template support

### Current State:
```json
{
  "title": "Create execution engine with template support",
  "description": "Build the runtime engine that executes workflows with template resolution",
  "details": "Create src/pflow/runtime/engine.py that extends pocketflow.Flow..."
}
```

### Recommended Update:
```json
{
  "title": "Create IR compiler and runtime coordinator",
  "description": "Build the IR to pocketflow.Flow compiler with template resolution support",
  "details": "Create src/pflow/runtime/compiler.py with IRCompiler class that converts JSON IR to pocketflow.Flow objects. Key functions: compile_ir_to_flow() to instantiate nodes and wire them with >> operator, setup_node_proxies() to create NodeAwareSharedStore when mappings defined, resolve_templates() to handle $variable substitution during execution. The class coordinates compilation and execution, not reimplementing pocketflow's engine. Reference docs: architecture.md#5.4, runtime.md"
}
```

**Rationale**: PocketFlow's Flow class IS the execution engine. We need a compiler that converts IR to Flow objects, not a new engine.

## Task #3: Create NodeAwareSharedStore proxy

### Current State:
```json
{
  "title": "Create NodeAwareSharedStore proxy",
  "description": "Implement the proxy pattern for transparent key mapping between nodes with incompatible interfaces"
}
```

### Recommended Update:
```json
{
  "title": "Create NodeAwareSharedStore proxy helper",
  "description": "Implement the optional proxy pattern for complex flows requiring key mapping between incompatible node interfaces",
  "details": "Create src/pflow/core/proxy.py with NodeAwareSharedStore class. This is a lightweight helper used by generated flow code when IR defines mappings. It provides transparent key translation with zero overhead when no mappings defined (passes through to underlying dict). Not a core component - only used for complex marketplace-style flows. Most simple flows will use direct shared store access without proxy."
}
```

**Rationale**: Clarify this is an optional helper for complex scenarios, not a core component always needed.

## Task #30: Establish PocketFlow Integration Foundation

### Recommendation: **REMOVE THIS TASK ENTIRELY**

**Rationale**:
- Creating wrapper classes (PflowNode, PflowFlow) adds no value
- All nodes should inherit directly from pocketflow.Node
- Documentation can explain integration patterns without code wrappers
- This task would create unnecessary abstraction layers

**Alternative Action**:
Update the task dependencies that reference #30 to instead ensure they:
1. Import pocketflow correctly
2. Inherit from pocketflow.Node directly
3. Follow pocketflow patterns without wrappers

## Dependency Updates

Since we're removing task #30, update these dependencies:
- Task #2: Remove dependency on #30 (was [30])
- All node tasks (#10-16) don't actually depend on #30 since they already inherit from pocketflow.Node correctly

## Summary of Changes

1. **Task #2**: Transform from class wrapper to validation utilities
2. **Task #21**: Rename and refocus on IR compilation, not engine reimplementation
3. **Task #3**: Clarify as optional helper, not core component
4. **Task #30**: Remove entirely - no wrapper classes needed

These changes will:
- Reduce code complexity by ~30%
- Make the architecture clearer
- Speed up development by avoiding unnecessary abstractions
- Better leverage pocketflow's existing capabilities
