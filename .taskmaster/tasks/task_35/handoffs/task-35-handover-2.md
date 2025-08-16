# Task 35 Handoff: Critical Knowledge Transfer

**⚠️ IMPORTANT**: Do NOT begin implementing immediately. Read this entire handoff first, then the spec, then say "I'm ready to begin Task 35" only after you've absorbed this information.

## The Three Template Bugs We JUST Fixed (Don't Break Them!)

You're inheriting a template system that was recently fixed after hours of debugging. Three critical bugs were resolved that you must not reintroduce:

1. **The Regex Lookahead Bug** (MOST CRITICAL)
   - File: `src/pflow/runtime/template_resolver.py:24`
   - Original broken regex had `(?=\s|$|[^\w.])` - the dot in the character class prevented `$story_topic.` from matching
   - Was fixed to `(?=\s|$|[^\w])` - removing the dot from the negative character class
   - **Why this matters**: Your new regex `(?<!\$)\$\{([a-zA-Z_][\w-]*(?:\.[a-zA-Z_][\w-]*)*)\}` completely sidesteps this issue with explicit boundaries, but understand why the fix was needed

2. **Execution Parameters Never Made It to Templates**
   - File: `src/pflow/cli/main.py:528-531`
   - We had to add `shared_storage.update(execution_params)` because planner-extracted parameters weren't available during template resolution
   - Without this, ALL planner workflows with templates were completely broken
   - **Don't touch this code** - it's working now

3. **NamespacedSharedStore Wasn't Dict-Compatible**
   - File: `src/pflow/runtime/namespaced_store.py:103-142`
   - Had to add `keys()`, `items()`, `values()` methods
   - Without these, `dict(shared)` in `node_wrapper.py:101` would fail
   - **This is why templates work at all** in namespaced contexts

## The F-String Triple Brace Gotcha

This WILL bite you if you don't pay attention:

```python
# In template_resolver.py lines 181, 192:
# Current code:
result = result.replace(f"${var_name}", value_str)

# What you might think works for new syntax:
result = result.replace(f"${var_name}", value_str)  # WRONG! Outputs: $var_name

# What actually works:
result = result.replace(f"${{{var_name}}}", value_str)  # Outputs: ${var_name}
```

The outer braces are f-string syntax, the inner DOUBLE braces produce literal braces. Miss this and unresolved templates will be malformed.

## Two Separate Regex Patterns (Don't Miss Either!)

There are TWO regex patterns that MUST be updated in sync:

1. **Main pattern**: `src/pflow/runtime/template_resolver.py:24`
2. **Validation pattern**: `src/pflow/runtime/template_validator.py:338`

If these get out of sync, validation will pass templates that can't be resolved or vice versa. I've seen this happen - it's a nightmare to debug.

## The Planner Prompt is Your Biggest Risk

**File**: `src/pflow/planning/prompts/workflow_generator.md`

This file teaches the LLM how to generate workflows. It has 12+ hardcoded examples all using `$variable` syntax. If you don't update EVERY example here, the planner will keep generating old syntax even though your code expects new syntax. Users will get workflows that look right but fail mysteriously.

Key sections with examples:
- Lines 12-47: Basic examples
- Line 92+: Complex path traversal examples

## Saved Workflows Are Here (Delete Them All)

```bash
~/.pflow/workflows/
```

There are 8 workflows saved there. The user said "clean slate" - delete them all. No migration, no backward compatibility. We have zero production users.

## Test "Failures" That Are Actually Correct

These two tests currently fail and that's EXPECTED:
- `test_handles_malformed_templates`
- `test_malformed_template_syntax`

They expect `$var.` to be malformed (not match). But we intentionally changed this to allow punctuation after variables. With `${variable}` syntax, this ambiguity disappears entirely. Update these tests to reflect the new reality.

## Edge Case: The Dict String Representation Bug

Current problem that will disappear with new syntax:
- `$node.` where `node` is a dict resolves to the entire dict's string representation (ugly but rare)
- With `${node}.` this is unambiguous - the variable is `node`, the period is literal

## Escape Sequence Behavior Change

Current behavior:
- `$$var` → `$$var` (unchanged, the negative lookbehind prevents matching)

New behavior you're implementing:
- `$${var}` → `${var}` (literal output)

The negative lookbehind `(?<!\$)` in your new regex handles this. Test it thoroughly.

## Files That Call Template Methods (They'll Just Work)

These files import and use template modules but don't need logic changes:
- `workflow_executor.py:274` - calls `TemplateResolver.resolve_string()`
- `node_wrapper.py:114` - calls `TemplateResolver.resolve_string()`
- `compiler.py:505` - calls `TemplateValidator.validate_workflow_templates()`
- `planning/nodes.py:1257` - calls validator

They'll automatically work with the new syntax after you update the core modules. Don't waste time on them.

## The Prompt Template System is DIFFERENT

`src/pflow/planning/prompts/loader.py` uses `{{variable}}` syntax. This is NOT the same as workflow templates. Don't touch it. It's a completely separate system for LLM prompts, not workflows.

## Exact Line Numbers I Verified

I spent time verifying these exact locations. Trust them:

**template_resolver.py**:
- Line 24: TEMPLATE_PATTERN
- Lines 181, 192: replacement logic (needs triple braces)
- Lines 183, 194, 200: log messages
- Lines 137-142: docstring examples

**template_validator.py**:
- Line 338: _PERMISSIVE_PATTERN
- Lines 218, 245, 253, 259, 260, 264, 283, 291, 292, 296: error messages

**planning/nodes.py**:
- Lines 1123, 1125: error fix suggestions

## Why Clean Slate is a Gift

The user made the critical decision: no backward compatibility, no migration. This means:
- You can delete saved workflows without guilt
- You don't need dual-syntax support
- You don't need version checking
- You can make the change atomically
- Your regex can be simple

Don't second-guess this. It's a massive simplification.

## Performance Note

The new regex is actually simpler:
- Old: Complex lookarounds, multiple passes
- New: Single pass with explicit boundaries

This should be faster, but don't optimize prematurely. Get it working first.

## Testing Strategy

1. Run tests frequently during updates: `pytest tests/test_runtime/test_template* -v`
2. After everything is updated, test with real planner: `uv run pflow "create a hello world script"`
3. Check that generated workflow uses `${variable}` syntax
4. Verify it actually executes

## Files With Highest Risk of Missing

From my research, these have template references that are easy to miss:
- Docstrings in template_resolver.py (not just code)
- Error message strings in template_validator.py (10 locations)
- Test assertion strings (not just test data)
- JSON files in examples/ directory
- Markdown documentation (230+ occurrences)

## The Most Important Thing

This is an ATOMIC migration. Either everything uses new syntax or nothing does. Partial updates will create subtle bugs where some parts expect `$variable` and others expect `${variable}`.

When you think you're done, grep for `\$[a-zA-Z_]` to find any missed occurrences (except in escape sequences and the prompt template system).

## Your Lifeline

The spec at `.taskmaster/tasks/task_35/starting-context/task-35-spec.md` has 13 atomic rules with exact line numbers. I verified every single one. Follow it precisely.

Remember: Read everything first, understand the full scope, make a plan, then execute atomically. Don't start until you say "I'm ready to begin Task 35."