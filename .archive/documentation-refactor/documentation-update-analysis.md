# Documentation Update Analysis - CLI Planning Changes

## Key Changes to Document

1. **MVP Approach**: Both natural language (quoted) AND CLI syntax (unquoted) go through LLM
2. **CLI Autocomplete**: HIGH value MVP feature (not v2.0)
3. **Direct CLI Parsing**: LOW value, deferred to v2.0
4. **CLI Syntax**: Unquoted to enable shell features

## Documents Needing Updates

### 1. planner.md - MAJOR UPDATES NEEDED

**Current State**: Shows two distinct paths with CLI path doing direct parsing without LLM
**Conflicts**:
- Section 3.2 "CLI Pipe Syntax Path" shows validation-only planner
- Section 4 "Dual-Mode Operation" shows CLI bypassing LLM
- Diagrams show separate paths

**Updates Needed**:
- Clarify MVP routes both inputs through LLM
- Move direct CLI parsing to "Future Enhancement" section
- Update diagrams to show single path for MVP

### 2. mvp-scope.md - UPDATES NEEDED

**Check for**:
- Should explicitly list "Direct CLI parsing" as deferred to v2.0
- Should include "CLI autocomplete" in MVP features
- Ensure CLI syntax handling via LLM is clear

### 3. autocomplete.md - STATUS CHECK

**Current**: Likely marked as v2.0 feature
**Needed**: Should be MVP feature with high priority
**Note**: Basic autocomplete (node names, params) is MVP

### 4. architecture.md - MINOR UPDATES

**Check for**:
- References to dual-path planning
- CLI parsing without LLM
- Ensure architecture reflects MVP simplification

### 5. cli-runtime.md - CLARIFICATION NEEDED

**Check for**:
- How CLI syntax is parsed
- Relationship with planner
- Ensure it doesn't assume direct parsing

### 6. components.md - CHECK ALIGNMENT

**Check for**:
- Component list assuming direct CLI parser
- Ensure MVP components align with new approach

### 7. shell-pipes.md - PROBABLY OK

**Check**: Should be fine if focused on stdin/stdout handling

## Priority Order for Updates

1. **planner.md** - Most critical, has wrong architecture
2. **mvp-scope.md** - Needs to clearly state what's in/out
3. **autocomplete.md** - Check if it needs to be moved to MVP
4. **architecture.md** - Ensure consistency
5. Others - Minor checks

## Key Messages to Convey

1. **Simplification**: MVP is simpler - one path through LLM
2. **CLI Experience**: Unquoted syntax enables shell features
3. **Progressive Enhancement**: Start simple, optimize later
4. **User Value**: Autocomplete > direct parsing
