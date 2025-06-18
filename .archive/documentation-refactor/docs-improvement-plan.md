# Documentation Cross-Linking and Redundancy Reduction Plan

## Executive Summary

This plan addresses two critical issues in the pflow documentation:
1. **Missing cross-document links** making navigation difficult
2. **Significant redundancy** with concepts explained multiple times

The solution establishes clear document ownership, standardizes cross-references, and consolidates redundant content.

## Key Findings

### Redundancy Analysis
- **Shared Store Pattern**: Explained in 8+ documents, ~40% redundant
- **Template Variables**: Scattered across 5 documents with no canonical source
- **MVP Boundaries**: Listed in 12+ documents with occasional conflicts
- **PocketFlow Integration**: "100-line framework" mentioned 15+ times
- **Node Interfaces**: Duplicated between schemas.md and individual node docs

### Missing Cross-References
- Only 2 of 8 documents mentioning shared store reference the canonical doc
- No document fully cross-references related components
- Future version docs don't consistently link back to MVP scope
- Implementation details lack references to architectural decisions

## Document Ownership Model

### Canonical Sources by Concept

| Concept | Canonical Document | Reason |
|---------|-------------------|---------|
| Shared Store Pattern | `shared-store.md` | Most comprehensive, architectural focus |
| Template Variables | `shared-store.md` (new section) | Part of data flow pattern |
| MVP Boundaries | `mvp-scope.md` | Clear scope definition document |
| PocketFlow Integration | `pflow-pocketflow-integration-guide.md` | Practical implementation guidance |
| Node Interfaces | `schemas.md` | Centralized governance |
| JSON IR Format | `schemas.md` | Schema definitions |
| Planning System | `planner.md` | Complete planner specification |
| Registry Design | `registry.md` | Discovery and versioning |
| Runtime Behavior | `runtime.md` | Execution specification |
| CLI Syntax | `cli-runtime.md` | Command structure and parsing |

## Specific Update Recommendations

### Phase 1: Establish Canonical References (Priority: HIGH)

#### 1. Update `shared-store.md`
**Add sections:**
- "Template Variable Resolution" (move from architecture.md)
- "Cross-Document Navigation" (new navigation helper)

**Remove from other docs:**
- Template variable explanations in architecture.md (lines 210-278)
- Redundant shared store explanations in prd.md (lines 289-412)

#### 2. Update `mvp-scope.md`
**Add:**
- Version header template for all docs
- Complete component checklist (extract from components.md)

**Update all component docs to include:**
```markdown
> **Version**: MVP | v2.0 | v3.0
> **MVP Status**: ✅ Included | ❌ Deferred to v2.0
> See [MVP Scope](./mvp-scope.md) for complete boundaries.
```

#### 3. Standardize PocketFlow References
**Create standard reference:**
```markdown
Built on the [pocketflow framework](../pocketflow/__init__.py).
See [integration guide](./pflow-pocketflow-integration-guide.md) for implementation details.
```

**Remove:** Redundant framework explanations from all docs except the integration guide.

### Phase 2: Add Cross-References (Priority: HIGH)

#### 1. Core Architecture Documents

**`prd.md`** - Add navigation box at top:
```markdown
## Related Documents
- **Implementation**: [Architecture](./architecture.md) | [MVP Scope](./mvp-scope.md)
- **Patterns**: [Shared Store](./shared-store.md) | [Simple Nodes](./simple-nodes.md)
- **Components**: [Planner](./planner.md) | [Runtime](./runtime.md) | [Registry](./registry.md)
```

**`architecture.md`** - Add references:
- Link to shared-store.md when mentioning shared store pattern
- Link to schemas.md for JSON IR details
- Link to planner.md for planning pipeline

**`mvp-scope.md`** - Add references:
- Link to components.md for full inventory
- Link to each deferred feature's specification

#### 2. Pattern Documents

**`shared-store.md`** - Add:
- Links to all documents that implement the pattern
- "Used by" section listing components

**`simple-nodes.md`** - Add:
- Link to each node package specification
- Link to schemas.md for interface definitions

**`cli-runtime.md`** - Add:
- Link to shared-store.md for data flow
- Link to planner.md for IR generation

#### 3. Component Documents

**Each component doc** should include:
```markdown
## Dependencies
- **Patterns**: [List relevant patterns with links]
- **Components**: [List dependent components with links]
- **See Also**: [Related specifications]
```

### Phase 3: Reduce Redundancy (Priority: MEDIUM)

#### 1. Consolidate Shared Store Explanations

**Keep detailed explanation only in `shared-store.md`**

**Replace in other docs with:**
```markdown
This component uses the [shared store pattern](./shared-store.md) for inter-node
communication. Nodes read `shared["key"]` in prep() and write in post().
```

#### 2. Consolidate MVP Boundaries

**Keep comprehensive list only in `mvp-scope.md`**

**Replace in other docs with:**
```markdown
> **MVP Status**: ❌ Deferred to v2.0
> See [MVP Scope](./mvp-scope.md#excluded-features) for rationale.
```

#### 3. Consolidate Node Interface Definitions

**Keep canonical definitions in `schemas.md`**

**In node package docs, use:**
```markdown
## Interface
See [Node Metadata Schema](../schemas.md#node-metadata-schema) for interface format.

### `github-get-issue`
- **Reads**: `shared["issue_number"]` OR `params["issue_number"]`
- **Writes**: `shared["issue"]`
- **Side Effects**: GitHub API call
```

### Phase 4: Create Navigation Aids (Priority: MEDIUM)

#### 1. Add Document Headers

**Standard header for all docs:**
```markdown
---
title: [Document Title]
version: MVP | v2.0 | v3.0
type: Architecture | Pattern | Component | Implementation
related: [List of related docs]
---
```

#### 2. Create Concept Index

Add to `index.md`:
```markdown
## Concept Quick Reference
- **Shared Store** → [shared-store.md](./shared-store.md)
- **Template Variables** → [shared-store.md#template-variables](./shared-store.md#template-variables)
- **MVP Scope** → [mvp-scope.md](./mvp-scope.md)
- [... complete list]
```

#### 3. Add "See Also" Sections

At the end of each document:
```markdown
## See Also
- **Next**: [Suggested next document]
- **Related Patterns**: [List with links]
- **Implementation**: [Relevant implementation docs]
```

## Implementation Priority

### Immediate (Week 1)
1. Update `shared-store.md` with template variables section
2. Add version headers to all component docs
3. Create standard pocketflow reference snippet
4. Update `mvp-scope.md` with component checklist

### Short Term (Week 2)
1. Add navigation boxes to core architecture docs
2. Add cross-references to pattern documents
3. Replace redundant shared store explanations
4. Consolidate MVP boundary references

### Medium Term (Week 3-4)
1. Standardize all component dependencies sections
2. Create concept index in index.md
3. Add "See Also" sections to all docs
4. Review and update CLAUDE.md with new structure

## Success Metrics

1. **Redundancy Reduction**: 40% less duplicate content
2. **Navigation**: Every concept accessible within 2 clicks
3. **Clarity**: Single canonical source for each concept
4. **Maintenance**: Updates needed in only one location
5. **Discoverability**: Clear learning path through documents

## Standard Patterns to Adopt

### Cross-Reference Format
```markdown
[Concept Name](./document.md#section-anchor)
```

### Version Indicator
```markdown
> **Version**: MVP | v2.0 | v3.0
```

### Canonical Reference
```markdown
For detailed explanation, see [canonical document](./path.md).
```

### Brief Context + Link
```markdown
This uses the [shared store pattern](./shared-store.md) where nodes communicate
through a shared dictionary passed through the flow.
```

## Validation Checklist

After implementation:
- [ ] Each concept has ONE canonical document
- [ ] All mentions of concepts link to canonical source
- [ ] No detailed explanation appears in multiple places
- [ ] Every document has clear version indicator
- [ ] Navigation from any doc to related docs is obvious
- [ ] CLAUDE.md reflects the new organization
- [ ] Reading path is clear for new contributors

## Long-term Maintenance

1. **Review Quarterly**: Check for new redundancies
2. **Update Protocol**: Changes to canonical docs trigger reference updates
3. **New Document Checklist**: Must specify ownership and add cross-references
4. **Deprecation Process**: Mark outdated sections with forwarding links

This plan will transform the pflow documentation from a collection of overlapping documents into a well-organized, navigable knowledge base that supports both learning and reference use cases.
