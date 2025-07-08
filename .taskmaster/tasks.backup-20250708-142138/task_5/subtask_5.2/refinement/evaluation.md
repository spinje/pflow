# Evaluation for Subtask 5.2

## Ambiguities Found

### 1. Registry File Format Structure - Severity: 3

**Description**: The subtask description shows the expected format as a dictionary with node names as keys, but doesn't specify how to handle potential naming conflicts or what happens if two nodes have the same name.

**Why this matters**: If two different nodes claim the same name (e.g., both have `name = "processor"`), the second one would overwrite the first in the dictionary structure.

**Options**:
- [ ] **Option A**: Use simple dictionary, last-scanned-wins for conflicts
  - Pros: Simple implementation, matches example format exactly
  - Cons: Silent data loss on name conflicts
  - Similar to: Standard Python dict behavior

- [x] **Option B**: Use dictionary but log warnings on name conflicts
  - Pros: Maintains simple format while alerting about issues
  - Cons: Adds slight complexity to save logic
  - Risk: Users might miss warnings in logs

- [ ] **Option C**: Store as list internally, convert to dict for JSON
  - Pros: Preserves all nodes, no data loss
  - Cons: More complex, doesn't match specified format
  - Risk: Downstream consumers expect dict format

**Recommendation**: Option B - Log warnings but maintain the specified dictionary format. This balances simplicity with user awareness.

### 2. Registry Class Design - Severity: 2

**Description**: Should the Registry class be a singleton, a regular class, or a module with functions? The task mentions "Create a Registry class" but doesn't specify the usage pattern.

**Why this matters**: Design affects how other components will interact with the registry and whether multiple registry instances are allowed.

**Options**:
- [x] **Option A**: Regular class with instance methods
  - Pros: Clear OOP design, testable, allows multiple instances
  - Cons: Requires instantiation before use
  - Similar to: Standard Python class patterns

- [ ] **Option B**: Singleton pattern
  - Pros: Global registry state, simple access
  - Cons: Harder to test, hidden global state
  - Risk: Testing complications

- [ ] **Option C**: Module-level functions
  - Pros: Simple usage, no instantiation needed
  - Cons: Less flexible, harder to mock
  - Risk: Limited extensibility

**Recommendation**: Option A - Regular class allows for better testing and future flexibility.

### 3. Merge Strategy for Registry Updates - Severity: 3

**Description**: When scanning finds nodes that already exist in the registry, how should updates be handled? Replace entirely, merge, or skip?

**Why this matters**: Determines complexity of implementation and whether manual registry edits are preserved.

**Options**:
- [x] **Option A**: Complete replacement on each scan
  - Pros: Simple implementation, always reflects current scanner output
  - Cons: Loses any manual additions or modifications
  - Risk: User frustration if manual edits are lost
  - Similar to: Simple cache invalidation

- [ ] **Option B**: Merge with timestamp checking
  - Pros: Would preserve manual changes, update only changed files
  - Cons: Requires file timestamps, comparison logic, much more complex
  - Risk: Over-engineering for MVP scope

- [ ] **Option C**: Only add new nodes, never update
  - Pros: Very safe, no data loss
  - Cons: Stale data accumulates, changes not reflected
  - Risk: Registry becomes outdated and misleading

**Recommendation**: Option A - Complete replacement is appropriate for MVP. Document clearly that manual edits to registry.json will be lost on rescan. This keeps implementation simple and behavior predictable. Future versions can consider more sophisticated merge strategies if needed.

**User Decision**: After discussion, confirmed that Option A (complete replacement) is the correct approach for MVP scope.

## Conflicts with Existing Code/Decisions

### 1. Import Location for Registry Class
- **Current state**: Scanner lives in `src/pflow/registry/scanner.py`
- **Task assumes**: Registry class location not specified
- **Resolution needed**: Should Registry class be in same file or separate `registry.py`?
- **Recommendation**: Create `src/pflow/registry/registry.py` for separation of concerns

## Implementation Approach Decisions

### Approach 1: Simple JSON Persistence (Recommended)
- Description: Direct JSON file read/write with Path operations
- Pros: Simple, no dependencies, easy to debug
- Cons: No transaction safety, potential race conditions
- Decision: **Selected** - Appropriate for MVP scope

### Approach 2: JSON with File Locking
- Description: Use fcntl or similar for file locking
- Pros: Prevents concurrent access issues
- Cons: Platform-specific, overkill for MVP
- Decision: **Rejected** - Over-engineering for current needs

### Approach 3: SQLite Backend
- Description: Use SQLite for ACID properties
- Pros: Transactional, queryable, scalable
- Cons: Additional dependency, format change
- Decision: **Rejected** - Violates JSON requirement

## Test Strategy Decisions

Based on successful test-as-you-go pattern:
1. Test Registry class methods individually (load, save, update)
2. Test directory creation behavior
3. Test handling of missing/corrupt registry files
4. Test name conflict detection and warnings
5. Integration test with real scanner output

## No Critical User Decisions Required

All ambiguities have reasonable defaults that can proceed with implementation. The main decisions (warning on conflicts, simple replacement strategy) are reversible and appropriate for MVP scope.
