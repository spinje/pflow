# Task 35 Handoff: Template Syntax Migration `$variable` → `${variable}`

**⚠️ IMPORTANT**: Do NOT begin implementing immediately. Read this entire handoff first and confirm you understand the context and critical warnings. Say "I'm ready to begin Task 35" only after you've absorbed this information.

## Critical Context You Need to Know

### The Three Template Bugs We Just Fixed (Still Fresh)

Before you change anything, understand that we JUST fixed three critical template bugs that were preventing templates from working at all:

1. **Regex Pattern Bug** (MOST RECENT):
   - Original regex had lookahead `(?=\s|$|[^\w.])` that prevented `$story_topic.` from matching
   - We changed it to `(?=\s|$|[^\w])` to allow punctuation after variables
   - This fix is in `template_resolver.py:24`
   - **Side effect**: Now `$node.` (where node is a dict) resolves to the entire dict string representation - ugly but rare edge case

2. **Execution Parameters Not in Shared Storage**:
   - Added `shared_storage.update(execution_params)` in `cli/main.py:528-531`
   - Without this, planner-extracted parameters were never available during template resolution
   - This was a CRITICAL bug - all planner workflows with templates were broken

3. **NamespacedSharedStore Dict Compatibility**:
   - Added `keys()`, `items()`, `values()` methods to `NamespacedSharedStore`
   - Without these, `dict(shared)` in `node_wrapper.py:101` would fail
   - Files: `runtime/namespaced_store.py:103-142`

**Why this matters**: Your new regex pattern must preserve these fixes, especially allowing punctuation after variables.

### Two Regex Patterns - Don't Miss Either!

There are TWO separate regex patterns that must be updated:

1. **Main pattern**: `src/pflow/runtime/template_resolver.py:24`
   ```python
   TEMPLATE_PATTERN = re.compile(r"(?<!\$)\$([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)(?=\s|$|[^\w])")
   ```

2. **Validation pattern**: `src/pflow/runtime/template_validator.py:338`
   ```python
   _PERMISSIVE_PATTERN = re.compile(r"\$([a-zA-Z_]\w*(?:\.\w*)*)")
   ```

Both need updating or validation will be inconsistent with resolution!

### The Planner Prompt is CRITICAL

**File**: `src/pflow/planning/prompts/workflow_generator.md`

This file has 12+ hardcoded examples of `$variable` syntax. If you don't update this, the LLM will continue generating the old syntax even after you change the regex! The planner reads this file to learn how to generate workflows.

Key sections with examples:
- Lines 12-47: Multiple examples showing `$variable` usage
- Line 92+: More complex examples with path traversal

### Test Failures Are Not Always Bad

Two tests currently fail with our recent regex fix:
- `test_handles_malformed_templates`
- `test_malformed_template_syntax`

These tests expect `$var.` to NOT match (they consider it malformed). But we intentionally changed this behavior to allow punctuation after variables. When you migrate to `${variable}`, these edge cases disappear entirely - that's one of the benefits!

### String Replacement Gotcha

In `template_resolver.py` lines 181 and 192, the code replaces unresolved variables back into the string using:
```python
f"${var_name}"
```

With the new syntax, this needs to be:
```python
f"${{{var_name}}}"  # Triple braces because f-string uses one pair
```

Don't miss this or unresolved templates will be malformed!

### Path Traversal Must Continue Working

The new regex must support:
- `${node.field}` - One level
- `${node.nested.subfield}` - Multiple levels
- `${data.items.0}` - Could support numeric indices if desired

Current capture group handles this with `(?:\.[a-zA-Z_]\w*)*` - preserve this capability!

### No Configuration System Exists

Template syntax is hardcoded everywhere - there's no config file or environment variable to change. This is actually good for the migration (no hidden config to update) but means you must find every occurrence.

### The Edge Case That Will Disappear

Current problem: `$node.` where `node` is a dict resolves to the dictionary's string representation.
With `${node}` syntax, this ambiguity disappears - `${node}.` is clearly the variable `node` followed by a period.

### File Counts From Research

- **~20 source files** need updates
- **44 test files** contain "$" (86 total occurrences)
- **35+ documentation/example files**

But many are just find/replace operations once the core is done.

### Integration Points That DON'T Need Changes

These components will automatically work with the new syntax:
- All node implementations (they receive resolved values)
- Workflow execution engine
- Shared store operations
- Shell integration (no conflict with bash variables)

## Files You Must Read First

1. **Current implementation**:
   - `src/pflow/runtime/template_resolver.py` - Core resolution logic
   - `src/pflow/runtime/template_validator.py` - Validation logic

2. **Recent fixes for context**:
   - `src/pflow/runtime/namespaced_store.py:103-142` - Dict compatibility we added
   - `src/pflow/cli/main.py:528-531` - Execution params injection we added

3. **Test files to understand behavior**:
   - `tests/test_runtime/test_template_resolver.py` - Shows all edge cases
   - `tests/test_runtime/test_template_validator.py` - Validation tests

## Patterns to Follow

1. **The new regex should be simpler** - no complex lookaheads/lookbehinds needed:
   ```python
   TEMPLATE_PATTERN = re.compile(r"\$\{([a-zA-Z_][\w.-]*(?:\.[a-zA-Z_][\w.-]*)*)\}")
   ```
   This allows hyphens in names which is a bonus!

2. **Error messages pattern** - There are ~15 error messages across multiple files that show `$variable` in examples. They all follow similar patterns.

## Warnings

1. **Don't break path traversal** - Make sure `${node.field.subfield}` still works
2. **Don't forget the validation regex** - Two patterns must be consistent
3. **Update the planner prompt** - Or it will generate wrong syntax
4. **Test with real planner** - Run an actual `uv run pflow "create a test"` to verify
5. **Check escaped syntax** - `$${variable}` should probably output literal `${variable}`

## Why This Migration Matters

Current pain:
- `reports/week_$week_number_report.md` → ERROR (underscore continues variable name)
- `reports/week_$week_number-report.md` → Works but ugly
- `data_$timestamp.json` → ERROR

After migration:
- `reports/week_${week_number}_report.md` → Perfect!
- `data_${timestamp}.json` → Works!
- No more complex regex patterns
- Aligns with bash, JavaScript, Docker syntax users already know

## Final Note

The template system is more fragile than it appears. We just spent hours fixing three interconnected bugs that completely broke template resolution. The migration to `${variable}` will eliminate entire classes of these problems, but be careful during the transition. Test thoroughly, especially with the planner generating real workflows.

**Remember**: Read everything first, understand the context, then say "I'm ready to begin Task 35" before starting implementation.