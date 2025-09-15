# Final Cleanup Plan - Remove All Dead Code and Optimize Structure

## Issues to Fix

### 1. Dead Utility File: `cache_builder.py`
**Problem**: Contains 3 unused functions only referenced by tests
- `extract_static_from_prompt()` - Never used in production
- `should_use_caching()` - Logic obsolete after refactoring
- `format_cache_metrics()` - Never used

**Solution**: Delete the file entirely. Tests should test production code, not dead utilities.

### 2. Old Backup Files
**Problem**: Leftover backup files from refactoring
- `prompt_cache_helper_old.py` (if exists)

**Solution**: Delete all backup files

### 3. Unused Imports
**Problem**: Some nodes import `format_prompt` at the top but only use in fallback cases
- Lines 733, 937, 1469, 2148, 2414 in nodes.py

**Solution**: Move imports to where they're actually used (lazy import pattern)

### 4. MetadataGenerationNode Complexity
**Problem**: Has redundant `_build_metadata_prompt()` helper that:
- Formats a full prompt using `format_prompt()`
- Then we extract variables from it to use with `build_cached_prompt()`
- This is circular and wasteful

**Solution**: Remove `_build_metadata_prompt()` and inline the logic directly

### 5. Inconsistent Caching Patterns
**Problem**: Some nodes have custom `_build_cache_blocks()` methods, others don't
- WorkflowDiscoveryNode: Has custom method
- ComponentBrowsingNode: Has custom method
- Others: Use standard helper

**Solution**: This is actually correct - special nodes need special handling. Document this pattern clearly.

## Implementation Order

### Step 1: Remove Dead Files
1. Delete `src/pflow/planning/utils/cache_builder.py`
2. Delete `src/pflow/planning/utils/prompt_cache_helper_old.py` (if exists)
3. Remove any test files that ONLY test these dead utilities

### Step 2: Clean Up Imports
1. Find all `from pflow.planning.prompts.loader import format_prompt` at module level
2. Move them inside the functions where actually used
3. Keep imports that are used in main execution path

### Step 3: Refactor MetadataGenerationNode
1. Remove `_build_metadata_prompt()` method
2. Inline the variable preparation directly in `exec()`
3. Simplify the flow to avoid double-formatting

### Step 4: Document the Architecture
1. Add clear comments explaining the caching patterns
2. Document why some nodes have custom methods and others don't

## Expected Impact

- **Lines removed**: ~200+ (cache_builder.py + redundant code)
- **Clarity improved**: No more dead code confusing readers
- **Performance**: Slightly better (no redundant formatting)
- **Maintainability**: Much better - clear patterns, no dead code

## Validation

After each step:
1. Run a simple test to ensure nodes still work
2. Check imports are resolved
3. Verify caching still functions

## Principles

- **Production code drives tests**, not the other way around
- **Dead code is technical debt** - remove it immediately
- **Lazy imports are fine** for rarely-used paths
- **Document patterns** when they're not obvious