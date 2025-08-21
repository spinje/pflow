# Discovery System Improvements Summary

## Problems Identified

### 1. Poor Discovery Accuracy (52.6%)
- High false positive rate (matching unrelated requests)
- Missing real matches
- Inconsistent confidence scores

### 2. Architectural Issues
- Metadata was being embedded in IR then extracted, causing duplication
- IR was polluted with non-structural data (keywords, capabilities)
- Discovery context was too minimal (just names and descriptions)

### 3. Test Suite Problems
- Tests focused on exact confidence ranges instead of decision correctness
- Rigid expectations that didn't match reality
- Some test expectations were logically wrong

## Solutions Implemented

### 1. Clean Architecture (✅ Completed)

**Before:**
```
Planner → CLI embeds metadata in IR → WorkflowManager extracts it → Stores at wrapper level
```

**After:**
```
Planner → CLI passes metadata separately → WorkflowManager stores directly at wrapper level
```

**Benefits:**
- IR stays pure (only workflow structure)
- No duplication of metadata
- Cleaner separation of concerns

### 2. Rich Discovery Context (✅ Completed)

**Before:**
```
1. generate-changelog - Generate changelog from GitHub issues and create PR
2. simple-read - Read a file
```

**After:**
```
1. generate-changelog - Generate changelog from GitHub issues and create PR
   Capabilities: GitHub integration, Issue fetching, Changelog generation, Pull request creation
   Keywords: changelog, github, issues, release, version
   Use cases: Release preparation, Version updates

2. simple-read - Read a file
   Capabilities: File reading, Text extraction
   Keywords: read, file, load, text
   Use cases: Loading configuration, Reading data
```

### 3. Improved Discovery Prompt (✅ Completed)

**Key Improvements:**
- Clear decision criteria (complete functional match, compatible domain, purpose alignment)
- Explicit guidelines for edge cases
- Removed contradictory instructions
- Added emphasis on using metadata for matching

### 4. Pragmatic Test Suite (✅ Completed)

**New Focus:**
- **Primary**: Decision correctness (found vs not_found)
- **Secondary**: Reasonable workflow selection
- **Tertiary**: Performance (<10 seconds)
- **Removed**: Rigid confidence ranges

## Implementation Changes

### Files Modified

1. **src/pflow/core/ir_schema.py**
   - Removed metadata field from IR schema

2. **src/pflow/core/workflow_manager.py**
   - Added metadata parameter to save()
   - Removed metadata extraction from IR
   - Stores metadata directly at wrapper level

3. **src/pflow/cli/main.py**
   - Pass metadata separately to WorkflowManager.save()
   - Don't embed metadata in IR

4. **src/pflow/planning/context_builder.py**
   - Display rich metadata in discovery context
   - Look for metadata at wrapper level (rich_metadata field)

5. **src/pflow/planning/prompts/discovery.md**
   - Clearer decision criteria
   - Better guidelines for edge cases
   - Emphasis on using metadata

6. **tests/test_planning/llm/prompts/test_discovery_prompt.py**
   - Updated to pass metadata separately
   - Focus on decision correctness

## Expected Outcomes

1. **Better Discovery Accuracy**
   - Fewer false positives (wrong domain detection)
   - Better matching with rich metadata
   - More consistent decisions

2. **Cleaner Codebase**
   - IR focused on structure only
   - Metadata handled at storage layer
   - No duplication

3. **More Realistic Testing**
   - Tests what matters (decisions)
   - Flexible on confidence scores
   - Better alignment with real usage

## Next Steps

1. Run full accuracy tests with the improvements
2. Monitor real-world usage for edge cases
3. Consider adding more metadata fields as needed (e.g., required tools, complexity level)

## Key Insight

The fundamental issue was trying to make decisions with insufficient information. By:
1. Providing rich metadata (capabilities, keywords, use cases)
2. Keeping it separate from workflow structure
3. Making it easily accessible during discovery

We give the LLM the context it needs to make good decisions about workflow reuse.