# Evaluation for Subtask 16.1

## Ambiguities Found

### 1. Metadata Extraction Failure Handling - Severity: 3

**Description**: When PflowMetadataExtractor.extract_metadata() fails (e.g., ValueError for non-Node classes), should we skip the node entirely or show it with basic info from registry?

**Why this matters**: Affects whether users see all registered nodes or only those with valid metadata

**Options**:
- [x] **Option A**: Skip nodes that fail metadata extraction entirely
  - Pros: Clean output, only shows fully functional nodes
  - Cons: User might not know about nodes that exist but have issues
  - Similar to: Task 7's approach of graceful degradation

- [ ] **Option B**: Show node with registry info only (name, description from docstring)
  - Pros: User sees all registered nodes
  - Cons: Inconsistent formatting, potentially confusing
  - Risk: May show broken/test nodes

**Recommendation**: Option A - The handoff memo and user decisions document clearly state to "skip nodes with missing metadata entirely". This aligns with showing only production-ready nodes.

### 2. Category Grouping Logic - Severity: 2

**Description**: How should nodes be categorized? By directory structure, name patterns, or explicit metadata?

**Why this matters**: Affects how nodes are organized in the output, impacting discoverability

**Options**:
- [x] **Option A**: Simple pattern matching on node names (e.g., "file" in name → File Operations)
  - Pros: Simple to implement, works with current nodes
  - Cons: May miscategorize some nodes
  - Similar to: Common CLI tool organization

- [ ] **Option B**: Use directory structure from module path
  - Pros: Reflects code organization
  - Cons: May create too many categories
  - Risk: Directory structure might change

- [ ] **Option C**: Add explicit category metadata to nodes
  - Pros: Most accurate categorization
  - Cons: Requires updating all nodes
  - Risk: Over-engineering for MVP

**Recommendation**: Option A - The handoff explicitly states "Don't over-engineer categories. Simple pattern matching on node names is fine."

### 3. Test Node Detection - Severity: 2

**Description**: How to reliably detect and filter out test nodes from the registry?

**Why this matters**: Test nodes shouldn't appear in production context

**Options**:
- [x] **Option A**: Filter by "test" in file path or module name
  - Pros: Simple, catches most test files
  - Cons: Might miss unconventionally named tests
  - Similar to: Standard Python test conventions

- [ ] **Option B**: Add explicit test flag to registry metadata
  - Pros: Most reliable
  - Cons: Requires registry changes
  - Risk: Scope creep beyond current task

**Recommendation**: Option A - Simple and effective for MVP. The handoff mentions "files with 'test' in name/path".

## Conflicts with Existing Code/Decisions

None identified. The implementation aligns with existing registry and metadata systems.

## Implementation Approaches Considered

### Approach 1: Direct Registry-Only Formatting
- Description: Format nodes using only registry metadata (docstring)
- Pros: Simple, no imports needed
- Cons: Limited information, no Interface details
- Decision: **Rejected** - Need Interface information for proper formatting

### Approach 2: Full Metadata Extraction with Graceful Degradation
- Description: Try to extract metadata for each node, skip on failure
- Pros: Rich information for valid nodes, clean output
- Cons: Some nodes might be skipped
- Decision: **Selected** - Aligns with user decisions and quality requirements

### Approach 3: Hybrid with Fallback Display
- Description: Show all nodes, use basic info for those without metadata
- Pros: Complete node listing
- Cons: Inconsistent output format
- Decision: **Rejected** - User decisions specify skipping nodes without metadata

## Key Implementation Details Confirmed

1. **Function receives** `registry_metadata` parameter (not individual node lookups)
2. **Must use** `import_node_class()` from runtime.compiler for safe imports
3. **Filter parameters** to show only exclusive ones (not in inputs list)
4. **Create directory** `src/pflow/planning/` with `__init__.py`
5. **Log but continue** on import failures
6. **Skip test nodes** based on file path patterns
7. **Group by category** using simple name patterns
