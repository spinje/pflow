# Evaluation for 15.2

## Ambiguities Found

### 1. Structure Display Enhancement Requirement - Severity: 3

**Description**: The handoff mentions that `_format_structure()` needs enhancement for "Combined JSON + paths format", but the exact implementation approach isn't specified. The ambiguities doc (Decision 9) requires this format, but current `_format_structure()` only does hierarchical format.

**Why this matters**: The planner needs the combined format to generate accurate proxy mappings. Without it, path-based mappings like `"author": "issue_data.user.login"` won't work.

**Options**:
- [x] **Option A**: Create a new helper method `_format_structure_combined()` that generates both JSON and paths
  - Pros: Clean separation, doesn't break existing code, easier to test
  - Cons: Another method to maintain
  - Similar to: Pattern of creating focused helper methods (Task 15.1)

- [ ] **Option B**: Modify existing `_format_structure()` to support a format parameter
  - Pros: Single method for all structure formatting
  - Cons: Changes existing method signature, might break tests
  - Risk: Existing callers might not expect new format

**Recommendation**: Option A - Create new helper method. This follows the pattern from 15.1 of breaking complex functions into smaller, focused ones.

### 2. Workflow Categorization in Discovery - Severity: 2

**Description**: Nodes are grouped by category (File Operations, AI/LLM, etc.) but workflows don't have categories. How should workflows be displayed in discovery context?

**Why this matters**: Consistent organization helps LLM browse components effectively.

**Options**:
- [x] **Option A**: Single "Available Workflows" section after all node categories
  - Pros: Clear separation between nodes and workflows, simple to implement
  - Cons: Workflows might get overlooked at the end
  - Similar to: How the ambiguities doc shows it in examples

- [ ] **Option B**: Try to infer workflow categories from their constituent nodes
  - Pros: Better organization if many workflows
  - Cons: Complex logic, might miscategorize
  - Risk: Category inference could be wrong

**Recommendation**: Option A - Follows the examples in the ambiguities document exactly.

### 3. Test Workflow Filtering - Severity: 1

**Description**: `_process_nodes()` filters out test nodes, but `_load_saved_workflows()` doesn't filter test workflows. Should test workflows be excluded from discovery?

**Why this matters**: Test workflows might confuse the planner in production use.

**Options**:
- [x] **Option A**: Include all workflows (no filtering)
  - Pros: Simple, consistent with current implementation
  - Cons: Test workflows visible in production
  - Similar to: Current behavior

- [ ] **Option B**: Filter workflows with "test" in the name
  - Pros: Cleaner production experience
  - Cons: Might filter legitimate workflows
  - Risk: Over-filtering useful workflows

**Recommendation**: Option A for MVP - Keep it simple, no filtering. Can add filtering in future version if needed.

## Conflicts with Existing Code/Decisions

### 1. No Conflicts Identified
- **Current state**: All required helper methods exist and are functional
- **Task assumes**: We can reuse existing methods
- **Resolution needed**: None - everything aligns

## Implementation Approaches Considered

### Approach 1: Minimal Implementation Using Existing Helpers
- Description: Reuse all existing methods (_process_nodes, _group_nodes_by_category, _format_node_section)
- Pros: Leverages tested code, maintains consistency, faster implementation
- Cons: Might need minor adaptations
- Decision: **Selected** - This follows the principle of reusing existing patterns

### Approach 2: Complete Rewrite for Optimization
- Description: Write new optimized methods specifically for two-phase approach
- Pros: Could be more efficient
- Cons: Duplicates logic, more testing needed, breaks from established patterns
- Decision: **Rejected** - Violates DRY principle and increases maintenance burden

### Approach 3: Structure Display Implementation
- Description: Create new `_format_structure_combined()` for JSON + paths format
- Pros: Clean implementation, testable, doesn't break existing code
- Cons: Additional method to maintain
- Decision: **Selected** - Necessary for planner requirements
