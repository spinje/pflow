# Task 35: Migrate Template Syntax from $variable to ${variable} - Agent Instructions

## The Problem You're Solving

The current template syntax `$variable` has ambiguous boundaries that cause parsing failures when variables are adjacent to underscores or other characters (e.g., `data_$timestamp.json` fails). Users must use awkward workarounds like hyphens to avoid parsing errors. This migration to `${variable}` syntax provides explicit boundaries, eliminates parsing ambiguities, and aligns with industry standards like bash, JavaScript, and Docker.

## Your Mission

Replace all occurrences of `$variable` template syntax with `${variable}` across the entire pflow codebase. This is a clean-slate migration with no backward compatibility - we're making a complete switch to the new syntax.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_35/task-35.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_35/starting-context/`

**Files to read (in this order):**
1. `task-35-spec.md` - The specification (FOLLOW THIS PRECISELY - contains 13 atomic rules with exact line numbers)

**Instructions**: The spec contains all verified implementation details including exact line numbers for every change needed. It is your source of truth.

### 4. THIRD: Handoff Documents
**Files to read (in this order):**
1. `.taskmaster/tasks/task_35/handoffs/task-35-handover.md` - it contains critical context about recent bug fixes that must be preserved.
2. `.taskmaster/tasks/task_35/handoffs/task-35-handover-2.md` - even more useful information


## What You're Building

A complete syntax migration from `$variable` to `${variable}` that:
- Updates core regex patterns to match the new syntax
- Modifies template replacement logic to handle unresolved variables correctly
- Updates all examples, tests, and documentation to use the new syntax
- Supports hyphens in variable names as an enhancement
- Handles escaped syntax `$${variable}` to output literal `${variable}`

Example transformation:
```python
# Before:
"Hello $name from $location"
"data_$timestamp.json"  # This currently FAILS

# After:
"Hello ${name} from ${location}"
"data_${timestamp}.json"  # This will WORK
```

## Key Outcomes You Must Achieve

### Core Implementation
- Update regex patterns in `template_resolver.py:24` and `template_validator.py:338`
- Modify template replacement logic at lines 181, 192 in `template_resolver.py`
- Update log messages at lines 183, 194, 200 in `template_resolver.py`
- Update error messages at 10 specific line locations in `template_validator.py`
- Update error suggestions in `planning/nodes.py` at lines 1123, 1125

### Documentation & Examples
- Replace all 12+ examples in `workflow_generator.md` with new syntax
- Update docstring examples in `template_resolver.py:137-142`
- Update all documentation files (230+ occurrences)
- Update all example JSON workflows

### Testing & Cleanup
- Update all test files to assert against new syntax
- Delete all saved workflows in `~/.pflow/workflows/`
- Ensure all tests pass with no regressions

## Implementation Strategy

### Phase 1: Core Regex and Logic Updates (1 hour)
1. Update TEMPLATE_PATTERN in `template_resolver.py:24` to new regex with negative lookbehind
2. Update _PERMISSIVE_PATTERN in `template_validator.py:338`
3. Modify template replacement logic in `template_resolver.py` (lines 181, 192) to use triple braces
4. Update log messages in `template_resolver.py` (lines 183, 194, 200)
5. Update docstring examples in `template_resolver.py:137-142`

### Phase 2: Error Messages and Planner Updates (1 hour)
1. Update all error messages in `template_validator.py` at specified lines
2. Update error suggestions in `planning/nodes.py:1123,1125`
3. Replace ALL examples in `workflow_generator.md` (critical for planner)
4. Update any other planner prompts with template examples

### Phase 3: Test Updates (2 hours)
1. Update test assertions in `test_template_resolver.py`
2. Update test assertions in `test_template_validator.py`
3. Update all integration tests that use templates
4. Update test data and fixtures

### Phase 4: Documentation and Examples (2 hours)
1. Update all documentation files in `docs/`
2. Update all example JSON workflows in `examples/`
3. Update CLI reference documentation
4. Delete all saved workflows in `~/.pflow/workflows/`

### Phase 5: Verification (30 minutes)
1. Run full test suite with `make test`
2. Run linting and type checking with `make check`
3. Test planner generation with real command
4. Verify no occurrences of old syntax remain

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### The New Regex Pattern
```python
# Old pattern (complex with lookarounds):
r"(?<!\$)\$([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)(?=\s|$|[^\w])"

# New pattern (simpler with explicit boundaries):
r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:\.[a-zA-Z_][\w-]*)*)\}"
```

Key improvements:
- Explicit `${` and `}` boundaries eliminate ambiguity
- Allows hyphens in variable names (`[\w-]*`)
- Negative lookbehind `(?<!\$)` handles escaped syntax
- No complex positive lookahead needed

### F-String Triple Brace Pattern
When replacing unresolved variables back into strings:
```python
# WRONG - This will fail:
f"${var_name}"  # Outputs: $var_name (missing braces!)

# CORRECT - Use triple braces:
f"${{{var_name}}}"  # Outputs: ${var_name}
```

The outer braces are f-string syntax, the inner double braces produce literal braces.

### Escaped Syntax Behavior
```python
# Current behavior:
"$$variable" → "$$variable" (unchanged)

# New behavior:
"$${variable}" → "${variable}" (literal output)
```

The negative lookbehind in the regex prevents matching escaped templates.

### Files That Import Template Modules
These files use template resolution but don't need logic changes:
- `workflow_executor.py:274` - Resolves child workflow parameters
- `node_wrapper.py:114` - Resolves node parameters at runtime
- `compiler.py:505` - Validates templates during compilation
- `planning/nodes.py:1257` - Validates templates in planning

They'll automatically work with the new syntax after core updates.

## Critical Warnings from Experience

### Recent Regex Bug Fix Must Be Preserved
The original regex had `(?=\s|$|[^\w.])` which prevented `$story_topic.` from matching. This was recently fixed to `(?=\s|$|[^\w])` to allow punctuation after variables. The new regex eliminates this issue entirely with explicit boundaries.

### Two Regex Patterns Must Stay Synchronized
There are TWO patterns that must be updated:
1. Main pattern in `template_resolver.py:24` - for resolution
2. Validation pattern in `template_validator.py:338` - for validation

If these get out of sync, validation will be inconsistent with resolution!

### The Planner Prompt is CRITICAL
`workflow_generator.md` contains 12+ hardcoded examples that teach the LLM how to generate workflows. If you don't update this file, the planner will continue generating old syntax even after the code changes!

### Test Failures Are Expected
Two tests currently fail with the recent regex fix:
- `test_handles_malformed_templates`
- `test_malformed_template_syntax`

These expect `$var.` to NOT match. With the new `${var}` syntax, this edge case disappears entirely.

## Key Decisions Already Made

1. **Clean slate approach** - No backward compatibility, no migration scripts
2. **Delete all saved workflows** - Users will regenerate them (we have no production users)
3. **Allow hyphens in variable names** - Enhancement while we're changing syntax
4. **Escaped syntax uses `$${variable}`** - Consistent with current `$$variable` pattern
5. **Atomic migration** - Update everything in one pass, no dual-syntax period
6. **Leave prompt templates alone** - `{{variable}}` system is separate and unchanged

**📋 Note on Specifications**: The specification file `task-35-spec.md` contains 13 atomic rules with exact line numbers. Follow it precisely - do not deviate from specified behavior, test criteria, or implementation requirements.

## Success Criteria

Your implementation is complete when:

- ✅ All 13 rules from the spec are implemented exactly
- ✅ All 14 test criteria pass
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ No occurrences of `$variable` syntax remain (except in escape sequences)
- ✅ Planner generates workflows with new `${variable}` syntax
- ✅ All saved workflows are deleted from `~/.pflow/workflows/`
- ✅ Examples like `data_${timestamp}.json` work correctly

## Common Pitfalls to Avoid

1. **Missing the second regex pattern** - Both resolver AND validator patterns must be updated
2. **Forgetting triple braces in f-strings** - `f"${{{var_name}}}"` not `f"${var_name}"`
3. **Not updating the planner prompt** - workflow_generator.md is critical
4. **Leaving old syntax in error messages** - Check all 10 locations in template_validator.py
5. **Not handling escaped syntax** - Negative lookbehind is required
6. **Missing docstring examples** - template_resolver.py has examples in docstrings
7. **Partial updates** - This must be atomic, update everything

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent missed occurrences.

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Find All Template Occurrences**
   - Task: "Search for all files containing '$' followed by letters to find template usage"
   - Task: "List all test files that might contain template assertions"

2. **Documentation Analysis**
   - Task: "Find all markdown files in docs/ that contain template examples"
   - Task: "Identify all JSON files in examples/ with template variables"

3. **Error Message Locations**
   - Task: "Find all error messages that show $variable syntax in their text"
   - Task: "Locate all docstrings with template examples"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_35/implementation/implementation-plan.md`

Your plan should include:

1. **File change inventory** - Every file that needs modification
2. **Order of operations** - Core changes first, then ripple effects
3. **Verification strategy** - How to ensure nothing is missed
4. **Rollback plan** - How to revert if needed (though we won't need it)

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_35/implementation/progress-log.md`

```markdown
# Task 35 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
Reading task specification with 13 atomic rules...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. Read the epistemic manifesto and task specification
2. Create comprehensive implementation plan
3. Update core regex patterns (2 locations)
4. Update template replacement logic (5 locations)
5. Update all error messages (10+ locations)
6. Update planner prompt (workflow_generator.md)
7. Update all test files
8. Update all documentation
9. Update all example files
10. Delete saved workflows
11. Run comprehensive tests
12. Verify with real planner generation

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - Updating Core Regex
Changing template_resolver.py:24...

Old pattern: r"(?<!\$)\$([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)(?=\s|$|[^\w])"
New pattern: r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:\.[a-zA-Z_][\w-]*)*)\}"

Result:
- ✅ Pattern updated successfully
- ✅ Negative lookbehind preserved for escapes
- ✅ Hyphen support added
- 💡 Insight: Much simpler without positive lookahead!
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION FROM PLAN
- Original plan: Update all tests individually
- Why it failed: Too many test files (50+)
- New approach: Use sed/grep to bulk update simple cases, then handle complex ones
- Lesson: Bulk operations are essential for syntax migrations
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for updating tests and ensuring they properly test the new syntax.

For this migration, focus on:
- **Updating existing tests** to use new syntax
- **Verifying edge cases** like escaped templates and hyphens
- **Integration tests** to ensure planner generates correct syntax
- **No new test creation needed** - just update existing ones

**Progress Log - Only document testing insights**:
```markdown
## 15:30 - Test update revealed assumption
Updated test_template_resolver.py - discovered tests were
checking for specific error messages that include $variable.
Need to update error message strings in tests too.
```

## What NOT to Do

- **DON'T** add backward compatibility - This is a clean slate migration
- **DON'T** create migration scripts - We're deleting old workflows
- **DON'T** modify the prompt template system - `{{variable}}` is separate
- **DON'T** change template resolution logic - Only syntax is changing
- **DON'T** add features beyond hyphen support - Stay focused on migration
- **DON'T** leave ANY `$variable` syntax except in escape sequences

## Getting Started

1. Read the epistemic manifesto to understand the approach
2. Read the task specification - it has exact line numbers for every change
3. Create your implementation plan
4. Start with Phase 1: Update core regex patterns
5. Test frequently: `pytest tests/test_runtime/test_template_resolver.py -v`

## Final Notes

- The specification has 13 atomic rules with exact line numbers - follow them precisely
- This is an atomic migration - no partial updates
- The clean slate approach means no compatibility concerns
- Test with a real planner command after implementation to verify it works end-to-end
- Remember the f-string triple brace pattern for replacements

## Remember

You're performing a critical syntax migration that will eliminate an entire class of parsing ambiguities. The new `${variable}` syntax is cleaner, more intuitive, and aligns with industry standards. This change will make pflow templates more reliable and user-friendly.

The specification is highly detailed with exact line numbers - trust it. When you complete this migration, users will finally be able to write `data_${timestamp}.json` without workarounds!

Think carefully, be thorough, and remember: this is a one-way migration with no going back. Make it count!