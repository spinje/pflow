# Documentation Updates Summary - CLI Planning

## Overview

Based on the discussion about CLI path planning, we've updated several key documents to reflect the MVP approach where both natural language (quoted) and CLI syntax (unquoted) are processed through the LLM planner.

## Key Insight

**MVP Simplification**: Direct CLI parsing is deferred to v2.0 because:
1. Users rarely specify all parameters and connections
2. LLM is needed anyway to intelligently fill gaps
3. CLI autocomplete provides more immediate user value
4. Direct parsing is only a minor optimization

## Documents Updated

### 1. `docs/features/planner.md` ✅

**Major Changes**:
- Section 3.2 title updated to clarify MVP uses LLM for CLI syntax too
- Added MVP implementation note after CLI path table
- Section 4.1 updated to show both paths use LLM in MVP
- Section 4.3 table updated to show LLM required for CLI path
- Section 4.4 code example shows MVP approach
- Added new Section 4.5 about CLI Autocomplete as MVP feature

**Key Update Example**:
```markdown
# CLI Pipe Syntax (unquoted) → LLM Planner (MVP approach)
pflow yt-transcript --url=X >> summarize-text --temperature=0.9

> **MVP Note**: For MVP, both natural language and CLI syntax are processed through the LLM planner.
```

### 2. `docs/features/mvp-scope.md` ✅

**Major Changes**:
- Added Section 5 "CLI Autocomplete (MVP Enhancement)"
- Updated exclusions to include "Direct CLI parsing" as v2.0
- Removed "CLI autocomplete" from excluded features
- Added autocomplete to the 9 critical MVP components
- Added lockfile system and complex error handling to v2.0 deferrals

### 3. `docs/features/autocomplete.md` ✅

**Major Changes**:
- Added MVP status header at top of document
- Added Section 1.1 "MVP vs v2.0 Feature Scope"
- Clarified basic autocomplete is MVP, advanced features are v2.0
- Emphasized that autocomplete works with LLM backend

### 4. `todo/tasks.json` ✅

**Major Changes**:
- Updated Task #19 to clarify it handles both input types via LLM
- Added Task #30: Shell Pipe Integration (high priority)
- Added Task #31: CLI Autocomplete (high priority MVP)
- Added Task #32: Direct CLI Parsing (deferred to v2.0)
- Added Task #33: Execution Tracing System
- Added Task #34: MVP Validation Test Suite

## Documents Still Needing Review

### 1. `docs/architecture/architecture.md`
- Should check if it references dual-path planning
- Ensure consistency with MVP approach

### 2. `docs/features/cli-runtime.md`
- May assume direct CLI parsing
- Should clarify relationship with planner

## Key Messages Reinforced

1. **Simplicity**: MVP routes everything through LLM for consistency
2. **User Value**: Autocomplete provides immediate discovery benefits
3. **Progressive Enhancement**: Unquoted syntax enables future optimizations
4. **Intelligence**: LLM fills the gaps users don't specify

## Implementation Impact

The simplified approach means:
- One code path to implement and test
- Consistent behavior for all inputs
- Shell features (autocomplete) still work
- Smooth upgrade path to v2.0 optimizations

## Next Steps

1. Review `architecture.md` for consistency
2. Check `cli-runtime.md` for assumptions
3. Ensure all task dependencies reflect new understanding
4. Consider updating implementation examples to show MVP approach
