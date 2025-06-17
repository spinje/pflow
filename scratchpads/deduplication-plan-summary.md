# Deduplication Plan Summary

## Key Findings

After analyzing all 26 documentation files, I found **30-40% content duplication** across the docs folder:

- **Node lifecycle patterns**: Explained in 5+ files
- **CLI syntax**: Documented in 7+ files
- **JSON schemas**: Duplicated across 5+ files
- **Execution model**: Repeated in 4+ files
- **Cache key formula**: Identical in 4 files

## Proposed Solution: Create 3 New Reference Documents

### 1. `node-reference.md`
- Consolidates all node patterns, lifecycle, and examples
- Single source for "how to write a node"

### 2. `cli-reference.md`
- Complete CLI syntax, operators, and usage
- Consolidates content from 7+ files

### 3. `execution-reference.md`
- Runtime behavior, error handling, validation
- Authoritative source for "how pflow executes"

## Implementation Plan (5 Phases)

1. **Phase 1**: Create reference documents
2. **Phase 2**: Update canonical sources (schemas.md, runtime.md, shared-store.md)
3. **Phase 3**: Remove duplications from other docs, add cross-references
4. **Phase 4**: Update node package docs
5. **Phase 5**: Reorganize into folder structure

## Expected Impact

- **Remove ~2,000 lines** of duplicated content
- **Reduce maintenance** from 5+ locations to 1 per concept
- **Improve clarity** with single source of truth
- **Better organization** with reference/concepts/features separation

## Files Created

1. `/scratchpads/duplication-analysis-report.md` - Detailed analysis with examples
2. `/scratchpads/single-source-structure-design.md` - New document structure
3. `/scratchpads/deduplication-action-plan.md` - Step-by-step implementation
4. `/scratchpads/deduplication-plan-summary.md` - This summary

Ready to execute when you are!
