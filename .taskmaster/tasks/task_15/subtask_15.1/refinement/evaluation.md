# Evaluation for Subtask 15.1

## Ambiguities Found

### 1. Workflow Directory Location Handling - Severity: 2

**Description**: The handoff mentions using `Path.home()` for cross-platform compatibility, but should we allow configurable workflow directory locations?

**Why this matters**: Users might want to store workflows in custom locations (e.g., version-controlled directories, shared network drives).

**Options**:
- [x] **Option A**: Hard-code to `~/.pflow/workflows/` only
  - Pros: Simple, consistent with registry pattern, MVP-appropriate
  - Cons: Less flexible for advanced users
  - Similar to: Registry uses hard-coded `~/.pflow/registry.json`

- [ ] **Option B**: Accept optional path parameter with `~/.pflow/workflows/` as default
  - Pros: More flexible, future-proof
  - Cons: Adds complexity, parameter passing through multiple layers
  - Risk: Scope creep for MVP

**Recommendation**: Option A - Keep it simple for MVP. The Registry already uses a hard-coded path pattern, and we should follow it for consistency.

### 2. Workflow File Naming Conflicts - Severity: 1

**Description**: How should we handle workflow files that don't match their internal `name` field?

**Why this matters**: File `my-workflow.json` might contain `"name": "different-name"` which could cause confusion.

**Options**:
- [x] **Option A**: Trust the `name` field inside the JSON, ignore filename
  - Pros: Single source of truth, allows file renaming
  - Cons: Filename becomes meaningless
  - Similar to: Most package managers use internal metadata

- [ ] **Option B**: Enforce filename-name consistency
  - Pros: Clear file organization
  - Cons: Restrictive, prevents easy file management
  - Risk: User frustration with renaming restrictions

**Recommendation**: Option A - The internal `name` field should be authoritative, as decided in the ambiguities document.

## Conflicts with Existing Code/Decisions

None identified. The implementation aligns with existing patterns in the codebase.

## Implementation Approaches Considered

### Approach 1: Follow Registry Pattern
- Description: Model after Registry.load() implementation with similar error handling
- Pros: Consistent with existing codebase, proven pattern
- Cons: None significant
- Decision: **Selected** - Maintains consistency

### Approach 2: PocketFlow Map-Reduce Pattern
- Description: Use directory reading pattern from cookbook example
- Pros: Clean, tested pattern
- Cons: Might be overkill for simple JSON loading
- Decision: **Partially selected** - Use directory iteration approach but simplified

### Approach 3: Complex Caching System
- Description: Implement file watching and caching for performance
- Pros: Better performance with many workflows
- Cons: Complexity not justified for MVP
- Decision: **Rejected** - Premature optimization

## Test Strategy Clarification

### Test Workflow Contents
The handoff mentions using test nodes but doesn't specify exact workflow structure. Based on IR schema validation, test workflows should include:

1. **Valid workflows**:
   - Minimal valid workflow (single node)
   - Multi-node workflow with edges
   - Workflow with structured node outputs

2. **Invalid workflows**:
   - Missing required fields (`name`, `description`, `inputs`, `outputs`, `ir`)
   - Invalid IR structure (missing `nodes` array)
   - Malformed JSON

### Directory Structure for Tests
Tests should use `tmp_path` fixture to create isolated test directories, following the pattern from Task 5.3.

## Performance Considerations

### Loading Strategy
- Load all workflows at startup (no lazy loading for MVP)
- No size limits on individual workflow files
- Log warnings for exceptionally large files (>1MB) but still load them

### Error Recovery
- Skip individual invalid files with warnings
- Continue loading other files
- Return partial results rather than failing completely

## Edge Cases to Handle

1. **Empty directory**: Return empty list, not error
2. **Non-JSON files**: Skip with debug log (not warning)
3. **Hidden files**: Skip files starting with `.`
4. **Subdirectories**: MVP ignores subdirectories as decided
5. **Permission errors**: Log warning and skip file
6. **Symlinks**: Follow them (Path.resolve() handles this)
