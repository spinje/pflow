# Quick Reference: Files to Update

## Priority 1: Establish Canonical Sources

### `docs/shared-store.md`
**Why**: Make it the single source for shared store AND template variables
**Updates**:
- Add "Template Variable Resolution" section (move from architecture.md)
- Add navigation helper at top
- Add "Used By" section listing all components using the pattern

### `docs/mvp-scope.md`
**Why**: Single source of truth for what's in/out of MVP
**Updates**:
- Add complete component checklist
- Add version header template for other docs to copy
- Ensure all exclusions are clearly listed

### `docs/pflow-pocketflow-integration-guide.md`
**Why**: Already the best source for integration guidance
**Updates**:
- Add prominent link from CLAUDE.md
- Minor: Add standard header with related docs

## Priority 2: Remove Major Redundancies

### `docs/architecture.md`
**Remove**:
- Lines 210-278: Template variable detailed explanation → link to shared-store.md
- Redundant shared store explanations → brief mention + link

**Add**:
- Cross-references to canonical sources
- Navigation box at top

### `docs/prd.md`
**Remove**:
- Lines 289-412: Redundant shared store pattern details → link to shared-store.md
- Duplicate MVP listings → link to mvp-scope.md

**Add**:
- Navigation box for related documents
- Brief mentions with links instead of full explanations

### `docs/planner.md`
**Fix**:
- "Type Shadow Store" conflict with MVP scope
- Add clear version indicators

**Add**:
- Links to shared-store.md for template variables
- Links to schemas.md for metadata format

## Priority 3: Add Version Headers

### All Component Docs
Add to top of each file:
```markdown
> **Version**: MVP | v2.0 | v3.0
> **MVP Status**: ✅ Included | ❌ Deferred
```

Files needing headers:
- `docs/components.md`
- `docs/registry.md`
- `docs/runtime.md`
- `docs/planner.md`
- `docs/mcp-integration.md` (v2.0)
- `docs/implementation-details/autocomplete-impl.md` (v2.0)
- All files in `docs/future-version/` (v3.0)

## Priority 4: Cross-Reference Network

### Pattern Documents
- `simple-nodes.md` → Add links to all node package specs
- `cli-runtime.md` → Add links to shared-store.md and planner.md

### Node Package Docs
Each file in `docs/core-node-packages/`:
- Add link to schemas.md for interface format
- Add link to simple-nodes.md for design philosophy
- Remove duplicate interface explanations

### Component Docs
Each component spec should add:
- Dependencies section with links
- See Also section with related docs

## Files That Can Stay Mostly As-Is

These files are already well-focused:
- `docs/schemas.md` - Good canonical source for schemas
- `docs/registry.md` - Clear component specification
- `docs/runtime.md` - Focused on runtime behavior
- `docs/workflow-analysis.md` - Standalone analysis
- `docs/shell-pipes.md` - Specific feature doc

## Summary Stats

- **Files to update**: 18 of 26
- **Major content moves**: 3
- **Headers to add**: 12
- **Redundant sections to remove**: ~15
- **Cross-references to add**: ~50

This will reduce documentation size by ~15% while significantly improving navigability and maintainability.
