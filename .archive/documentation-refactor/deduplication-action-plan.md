# Deduplication Action Plan

## Overview

This plan provides specific, line-by-line changes to eliminate duplication while preserving all unique documentation. Each phase builds on the previous one to ensure smooth migration.

## Phase 1: Create Reference Documents (Day 1)

### 1.1 Create `docs/reference/node-reference.md`
**Content to migrate**:
```
# From shared-store.md (lines 220-292):
- Node lifecycle explanation
- LLMNode implementation example
- Best practices section

# From simple-nodes.md (lines 20-150):
- Core node patterns
- GitHubGetIssueNode example
- Implementation guidelines

# From architecture.md (lines 93-96, 347-368):
- Node lifecycle overview
- Remove duplicate LLMNode example

# From pflow-pocketflow-integration-guide.md (lines 35-47):
- What pocketflow provides (consolidate with other versions)

# New content to add:
- Comprehensive lifecycle diagram
- Node method signatures
- Common patterns and anti-patterns
- Testing strategies for nodes
```

### 1.2 Create `docs/reference/cli-reference.md`
**Content to migrate**:
```
# From cli-runtime.md:
- Lines 18-19: Basic syntax
- Lines 138-186: CLI to shared store flow
- Lines 421-481: Example flows

# From architecture.md:
- Lines 247-264: CLI examples
- Lines 256: Command structure

# From shell-pipes.md:
- Entire document content (keep as section)

# From registry.md:
- Lines 214-228: Composition syntax

# New content to add:
- Complete command reference
- Flag documentation
- Advanced composition patterns
- Troubleshooting guide
```

### 1.3 Create `docs/reference/execution-reference.md`
**Content to migrate**:
```
# From runtime.md:
- Lines 1-42: Execution overview
- Lines 80-134: Failure and retry behavior

# From architecture.md:
- Lines 413-454: Execution engine section

# From components.md:
- Lines 163-196: Runtime components

# From planner.md:
- Lines 802-814: Error codes

# New content to add:
- Execution flow diagram
- State machine representation
- Performance profiling guide
```

## Phase 2: Update Canonical Sources (Day 2)

### 2.1 Update `docs/schemas.md`
**Remove**:
- Lines 346-368: Execution behavior (→ execution-reference.md)
- Lines 187-215: Usage examples (→ node-reference.md)

**Keep**:
- All schema definitions
- Validation rules
- Type specifications

**Add**:
- Formal JSON Schema definitions
- Schema versioning guide

### 2.2 Update `docs/runtime.md`
**Remove**:
- Lines 1-42: General execution (→ execution-reference.md)
- Lines 34-47: Pocketflow provides (→ node-reference.md)

**Keep**:
- Lines 43-78: Caching strategy
- Lines 49-68: Cache key computation
- Safety decorators section

**Add**:
- Link to execution-reference.md
- Detailed cache implementation

### 2.3 Update `docs/shared-store.md`
**Remove**:
- Lines 266-292: LLMNode example (→ node-reference.md)
- Lines 220-229: Node lifecycle (→ node-reference.md)

**Keep**:
- Shared store pattern
- Proxy pattern
- Template variables
- Natural interfaces

**Add**:
- More proxy examples
- Advanced key mapping patterns

## Phase 3: Remove Duplications from Secondary Sources (Day 3)

### 3.1 Update `docs/architecture.md`
**Remove**:
- Lines 93-96: Node lifecycle (link to node-reference.md)
- Lines 347-368: LLMNode example (link to node-reference.md)
- Lines 413-454: Execution details (link to execution-reference.md)
- Lines 574-588: Cache formula (link to runtime.md)

**Replace with**:
```markdown
### Node System
Nodes follow the prep/exec/post lifecycle pattern.
> See [Node Reference](reference/node-reference.md) for implementation details

### Execution Engine
The runtime executes flows with caching and retry support.
> See [Execution Reference](reference/execution-reference.md) for behavior specification
```

### 3.2 Update `docs/prd.md`
**Remove**:
- Technical implementation details
- Duplicate shared store explanations

**Add**:
- Links to reference documents
- Focus on product requirements only

### 3.3 Update `docs/planner.md`
**Remove**:
- Lines 845-874: Caching details (link to runtime.md)
- Lines 560-600: Duplicate IR schema (link to schemas.md)

**Keep**:
- Planner-specific behavior
- Natural language compilation
- Planning strategies

### 3.4 Update `docs/cli-runtime.md`
**Remove**:
- Lines 18-19, 258, 282: Basic syntax (→ cli-reference.md)
- Lines 163-186: Node examples (→ schemas.md)

**Keep**:
- Runtime integration specifics
- Shared store management during execution

## Phase 4: Update Node Package Documentation (Day 4)

### 4.1 Update all node package docs
**For each file** in `core-node-packages/`:
```markdown
# Remove:
- Duplicate "check shared first" pattern
- Generic node implementation details

# Add at top:
> **Prerequisites**: Read [Node Reference](../reference/node-reference.md) for node implementation patterns

# Keep:
- Node-specific parameters
- Node-specific examples
- Platform integration details
```

## Phase 5: Reorganize and Polish (Day 5)

### 5.1 Create folder structure
```bash
mkdir -p docs/reference
mkdir -p docs/core-concepts
mkdir -p docs/architecture
mkdir -p docs/features
mkdir -p docs/node-packages

# Move files to new locations
mv docs/schemas.md docs/core-concepts/
mv docs/shared-store.md docs/core-concepts/
mv docs/runtime.md docs/core-concepts/
mv docs/registry.md docs/core-concepts/
# ... etc
```

### 5.2 Update `docs/index.md`
**Add**:
- New folder structure navigation
- Updated learning paths
- Reference document descriptions

### 5.3 Global cross-reference update
**Run search and replace**:
- Update all internal links to new paths
- Verify all cross-references work
- Add "See Also" sections where needed

## Validation Checklist

- [ ] No concept explained in more than one place
- [ ] All cross-references point to correct locations
- [ ] Each document has clear, non-overlapping purpose
- [ ] No loss of information during migration
- [ ] New reference docs are comprehensive
- [ ] Folder structure matches new organization

## Expected Outcomes

1. **Reduction**: ~2,000 lines of duplicated content removed
2. **Clarity**: Each concept has one authoritative location
3. **Maintainability**: Updates needed in only one place
4. **Discoverability**: Clear reference/concept/feature separation
5. **Consistency**: Single version of each technical detail

## Risk Mitigation

- Create backups before major changes
- Test all cross-references after updates
- Review each phase before proceeding
- Keep detailed change log
- Preserve git history for rollback
