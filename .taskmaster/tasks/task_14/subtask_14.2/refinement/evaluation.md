# Evaluation for Subtask 14.2

## Current State Analysis

The context builder has already been partially updated to handle the rich format from the metadata extractor:
- ✅ Basic type display is implemented (`key: type` format)
- ✅ Exclusive params filtering works with dict format
- ❌ Structure navigation hints are missing for complex types
- ❌ No handling of descriptions from the rich format
- ❌ 50KB limit handling is basic (just truncates mid-node)

## Ambiguities Found

### 1. Structure Navigation Display - Severity: 4

**Description**: How should we display navigation hints for complex structures (dict/list with nested fields)?

**Why this matters**: The planner needs to know how to access nested fields like `issue_data.user.login`, but the current implementation only shows `issue_data: dict` without structure info.

**Options**:
- [x] **Option A**: Inline navigation hints
  ```
  **Outputs**: `issue_data: dict` - Navigate: .number, .user.login, .labels[]
  ```
  - Pros: Compact, doesn't break existing format, quick to scan
  - Cons: Limited detail, no type info for nested fields
  - Similar to: Common API documentation patterns

- [ ] **Option B**: Separate structure section
  ```
  **Outputs**: `issue_data: dict`
  **Structure**:
    - issue_data.number: int
    - issue_data.user.login: str
  ```
  - Pros: Full detail, clear type info
  - Cons: Takes more space, might exceed 50KB limit faster
  - Risk: More complex formatting, harder to read

- [ ] **Option C**: Hybrid approach with depth limit
  ```
  **Outputs**: `issue_data: dict` (structure: number, user.*, labels[])
  ```
  - Pros: Balance of detail and space
  - Cons: Might be unclear what the notation means
  - Risk: New notation to explain

**Recommendation**: Option A because it's minimal (as required), provides essential navigation info, and maintains readability for LLM consumption.

### 2. Description Display - Severity: 3

**Description**: Should we display the description field from the rich format metadata?

**Why this matters**: Descriptions provide semantic meaning (e.g., "GitHub username" vs just "login: str").

**Options**:
- [x] **Option A**: Omit descriptions entirely
  - Pros: Minimal change, saves space, cleaner output
  - Cons: Loses semantic information
  - Rationale: Task specifies "minimal changes"

- [ ] **Option B**: Show descriptions as comments
  ```
  **Inputs**: `repo: str` # Repository name
  ```
  - Pros: Preserves semantic info
  - Cons: More verbose, not minimal
  - Risk: Conflicts with "minimal changes" requirement

**Recommendation**: Option A to maintain minimal changes as specified in the task.

### 3. 50KB Limit Handling for Structures - Severity: 3

**Description**: How to handle the 50KB limit when structure information adds size?

**Why this matters**: Structure navigation hints will increase output size, potentially hitting the limit faster.

**Options**:
- [x] **Option A**: Show structure hints only for first N occurrences
  - Pros: Predictable size control, still helpful
  - Cons: Later nodes might lack navigation info
  - Implementation: Track structure hint count

- [ ] **Option B**: Abbreviate structure hints progressively
  - Pros: All nodes get some info
  - Cons: Complex to implement, inconsistent output
  - Risk: Over-engineering for MVP

- [ ] **Option C**: Exclude structure hints near limit
  - Pros: Simple to implement
  - Cons: Unpredictable which nodes get hints
  - Risk: Important nodes might lack hints

**Recommendation**: Option A - show full structure hints for first 20-30 complex types, then omit to save space.

## Conflicts with Existing Code/Decisions

### 1. Partial Implementation Already Done
- **Current state**: Basic type display and exclusive params are implemented
- **Task assumes**: Full integration needs to be done
- **Resolution needed**: Focus only on missing pieces (structure navigation)

### 2. Test Expectations
- **Current state**: Tests expect type display but not structure navigation
- **Task assumes**: Need to display structure information
- **Resolution needed**: Add new tests for structure navigation without breaking existing ones

## Implementation Approaches Considered

### Approach 1: Minimal Enhancement (Recommended)
- Description: Add inline navigation hints only for dict/list types with structures
- Pros: Minimal code change, maintains current format, easy to test
- Cons: Less detailed than full structure display
- Decision: **Selected** - aligns with "minimal changes" requirement

### Approach 2: Full Structure Display
- Description: Add complete structure sections with all nested fields
- Pros: Maximum information for planner
- Cons: Not minimal, significant format change, space concerns
- Decision: **Rejected** - too much change for this task

### Approach 3: Progressive Disclosure
- Description: Show basic info with expandable structure details
- Pros: Best of both worlds
- Cons: Not feasible in markdown format
- Decision: **Rejected** - technically not possible

## Decisions Made
1. Use inline navigation hints for structures (Option A)
2. Omit descriptions to maintain minimal changes
3. Limit structure hints to first 20-30 occurrences for space
4. Focus only on adding structure navigation to existing implementation
