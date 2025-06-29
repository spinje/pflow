# Evaluation for 4.3

## Ambiguities Found

### 1. IR Field Naming Inconsistency - Severity: 3

**Description**: The IR schema documentation shows edges with "from/to" fields, but the subtask description and existing code use "source/target". Which is correct?

**Why this matters**: Using wrong field names will cause KeyError during edge processing.

**Options**:
- [x] **Option A**: Use "source/target" as shown in existing code
  - Pros: Consistent with _validate_ir_structure() which already exists
  - Cons: Inconsistent with schema documentation
  - Similar to: Existing validation code already expects these names

- [ ] **Option B**: Use "from/to" as shown in schema docs
  - Pros: Matches documented schema
  - Cons: Would break existing validation code
  - Risk: Need to update validation function too

**Recommendation**: Option A because the existing code already validates for "source/target" and changing it would require updating multiple places.

### 2. Start Node Detection Strategy - Severity: 2

**Description**: How should we detect the start node when not explicitly specified?

**Why this matters**: Without a clear start node, the Flow cannot be instantiated.

**Options**:
- [x] **Option A**: Use first node in array as fallback (as suggested in subtask)
  - Pros: Simple, deterministic, matches subtask description
  - Cons: Arbitrary if user didn't intentionally order nodes
  - Similar to: Common pattern in other workflow systems

- [ ] **Option B**: Find nodes with no incoming edges
  - Pros: More semantically correct
  - Cons: More complex, could have multiple candidates
  - Risk: What if all nodes have incoming edges (cycles)?

**Recommendation**: Option A because it's simpler and matches the subtask implementation details. Can enhance later if needed.

### 3. Registry ID vs Type Field - Severity: 2

**Description**: Schema shows nodes have "registry_id" field, but code uses "type". Which should we use?

**Why this matters**: Wrong field name means we can't look up nodes in registry.

**Options**:
- [x] **Option A**: Use "type" field as shown in existing code
  - Pros: Consistent with existing validation and registry implementation
  - Cons: Inconsistent with schema documentation
  - Similar to: Registry was built expecting "type" field

- [ ] **Option B**: Use "registry_id" as shown in schema
  - Pros: Matches documented schema
  - Cons: Would need to update registry lookup logic
  - Risk: Breaking change for existing code

**Recommendation**: Option A because the entire registry system and existing code expects "type" field.

## Conflicts with Existing Code/Decisions

### 1. Schema Documentation vs Implementation
- **Current state**: Code validates for nodes[].type and edges[].source/target
- **Schema assumes**: nodes[].registry_id and edges[].from/to
- **Resolution needed**: Update schema documentation to match implementation

## Implementation Approaches Considered

### Approach 1: Direct PocketFlow Instantiation (from Critical Insight #7)
- Description: Instantiate nodes directly and wire with operators
- Pros: Simple, direct use of pocketflow
- Cons: None identified
- Decision: [Selected] because it follows integration guide best practices

### Approach 2: Code Generation Approach
- Description: Generate Python code strings and eval()
- Pros: Could be more flexible
- Cons: Security risks, harder to debug, not recommended
- Decision: [Rejected] because integration guide warns against this

### Approach 3: Wrapper Classes Approach
- Description: Create PflowNode wrappers around pocketflow nodes
- Pros: Could add pflow-specific functionality
- Cons: Violates "extend don't wrap" principle
- Decision: [Rejected] because it adds unnecessary complexity

## Template Variable Handling Decision

**Question**: Should the compiler resolve template variables or pass them through?

**Decision**: Pass template variables through unchanged. The runtime will resolve $variables from shared store. This is consistent with the separation of compile-time vs runtime concerns.

## Node Instantiation Pattern

**Question**: How should we handle node instantiation with execution config (max_retries, wait)?

**Options**:
- Use Node base class constructor parameters if node inherits from Node
- Ignore execution config for nodes inheriting from BaseNode
- Always try to set via constructor, fall back to ignoring

**Decision**: For MVP, ignore execution config. Nodes that need retry inherit from Node and set their own defaults. This keeps it simple.

## Error Handling Granularity

**Question**: How detailed should our error messages be?

**Decision**: Follow the pattern from subtasks 4.1 and 4.2:
- Include phase, node_id, node_type where applicable
- Provide helpful suggestions (list available nodes, show correct syntax)
- Use CompilationError consistently

## Testing Strategy Clarification

**Question**: Should we test with real nodes or mocks?

**Decision**: Use mocks for unit tests (as done in 4.2). Can add one integration test with TestNode if it exists in registry.
