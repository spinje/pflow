# Documentation Updates Needed - CLI Planning Insights

## Summary of Key Changes

1. **MVP Simplification**: Both natural language (quoted) AND CLI syntax (unquoted) will be routed through LLM planner
2. **CLI Autocomplete**: Should be MVP feature (high value), not v2.0
3. **Direct CLI Parsing**: Deferred to v2.0 (low value optimization)
4. **Rationale**: Even with "complete" CLI syntax, LLM is needed to fill gaps (parameters, connections, templates)

## Documents Requiring Updates

### 1. `docs/features/planner.md` - CRITICAL UPDATES

**Current Issues**:
- Section 3.2 "CLI Pipe Syntax Path" describes a validation-only planner that doesn't use LLM
- Section 4 "Dual-Mode Operation" shows two distinct paths with different behaviors
- Diagrams show CLI path bypassing LLM entirely
- Table in 4.3 shows "LLM Usage: Not used" for CLI path

**Required Changes**:
1. **Update Section 3.2** to clarify MVP approach:
   - CLI syntax still goes through LLM for intelligent connection
   - LLM fills in missing parameters, templates, connections
   - Direct parsing is v2.0 optimization

2. **Update Section 4** (Dual-Mode Operation):
   - For MVP, both paths use LLM
   - Difference is input format (quoted vs unquoted), not processing
   - Both generate CLI preview for user verification

3. **Add new subsection** about CLI autocomplete:
   - Available in MVP to help users discover nodes
   - Works even though CLI is processed by LLM

4. **Move direct CLI parsing** to Future Enhancements section

### 2. `docs/features/mvp-scope.md` - ADD EXPLICIT EXCLUSIONS

**Current Issues**:
- Doesn't explicitly list what's excluded from MVP
- No mention of direct CLI parsing being deferred

**Required Changes**:
1. Add section "Explicitly Excluded from MVP":
   - Direct CLI parsing without LLM (v2.0)
   - Real-time type checking during composition (v2.0)
   - Advanced error handling and retry logic
   - Lockfile system

2. Update implementation phases to include CLI autocomplete in MVP

### 3. `docs/features/autocomplete.md` - CLARIFY MVP STATUS

**Current Issues**:
- Doesn't explicitly state if it's MVP or v2.0
- Might be interpreted as post-MVP feature

**Required Changes**:
1. Add header clarifying: "**MVP Status**: ✅ Core Feature"
2. Emphasize basic autocomplete (node names, params) is MVP
3. Advanced features (type-aware suggestions) are v2.0

### 4. `docs/architecture/architecture.md` - MINOR UPDATES

**Current Issues**:
- May reference dual-path planning approach
- Should align with simplified MVP

**Required Changes**:
1. Ensure planner section reflects MVP simplification
2. Add note that CLI parsing optimization is future work

### 5. `docs/features/cli-runtime.md` - CLARIFY RELATIONSHIP

**Current Issues**:
- May assume direct CLI parsing capabilities

**Required Changes**:
1. Clarify that CLI provides syntax, planner handles interpretation
2. Note that direct parsing is v2.0 optimization

## Example Updates

### For planner.md Section 4.1:

**Current**:
```bash
# Natural Language → Full Planner
pflow "summarize this youtube video"

# CLI Pipe Syntax → Validation Planner
pflow yt-transcript --url=X >> summarize-text --temperature=0.9
```

**Updated**:
```bash
# Natural Language (quoted) → LLM Planner
pflow "summarize this youtube video"

# CLI Pipe Syntax (unquoted) → LLM Planner (MVP approach)
pflow yt-transcript --url=X >> summarize-text --temperature=0.9

# Note: For MVP, both inputs are processed by LLM planner
# Direct CLI parsing is a v2.0 optimization
```

### For planner.md Section 4.3:

**Current Table**:
| Aspect | Natural Language Path | CLI Pipe Path |
|---|---|---|
| **LLM Usage** | Required for node selection | Not used |

**Updated Table**:
| Aspect | Natural Language Path | CLI Pipe Path |
|---|---|---|
| **LLM Usage** | Required for node selection | Required for connections (MVP) |
| **Direct Parsing** | N/A | v2.0 optimization |

## Priority of Updates

1. **planner.md** - Most critical, contains incorrect architecture
2. **mvp-scope.md** - Need clear boundaries
3. **autocomplete.md** - Clarify it's MVP feature
4. Other docs - Minor consistency updates

## Key Messages to Emphasize

1. **MVP Simplicity**: One path through LLM is simpler to implement
2. **User Value**: CLI syntax enables autocomplete even with LLM backend
3. **Intelligent Connection**: LLM fills gaps that users don't specify
4. **Future Optimization**: Direct parsing is minor performance improvement

## Documentation Philosophy

When updating, emphasize:
- Why this approach makes sense (users rarely specify everything)
- How it enables progressive enhancement (autocomplete → direct parsing)
- That it maintains the user experience vision while simplifying implementation
