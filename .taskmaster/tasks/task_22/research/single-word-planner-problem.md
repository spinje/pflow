# Single-Word Planner Activation Problem

## Problem Statement

The current implementation sends single-word inputs to the AI planner when they don't match saved workflows. This creates poor UX and wastes resources.

### Current Behavior
```bash
pflow workflows     # → Sends to AI planner (10+ seconds)
pflow analyze       # → Sends to AI planner
pflow test          # → Sends to AI planner
pflow foobar        # → Sends to AI planner
pflow run          # → Sends to AI planner
```

### Why This Is Bad

1. **Insufficient Context**: Single words provide no actionable information
   - What should "analyze" analyze?
   - What kind of "test" workflow?
   - What does "workflows" even mean as a workflow request?

2. **User Expectation Mismatch**
   - `pflow workflows` - User likely wants to list workflows, not create one
   - `pflow run` - User expects to run something, not create a "run" workflow
   - `pflow test` - Could be looking for a saved workflow named "test"
   - Accidental typos trigger expensive AI calls

3. **Resource Waste**
   - Each planner call takes 10+ seconds
   - Costs API tokens
   - Generates useless or wrong workflows
   - Forces follow-up interactions to clarify

4. **Poor Error Recovery**
   - User types `pflow workflow` (forgets 'list')
   - Waits 10+ seconds for AI
   - Gets irrelevant workflow generation
   - Has to cancel and try again

5. **Habit Conflicts**
   - Users from other tools expect `pflow run workflow-name`
   - Currently this would try to create a "run" workflow

## Real-World Scenarios

### Scenario 1: Typo
```bash
# User wants to list workflows
pflow workflows     # Typo (plural instead of 'workflow list')
# Result: 10+ second wait, confused AI response
```

### Scenario 2: Exploration
```bash
# User exploring what commands exist
pflow test          # Checking if there's a test command
# Result: AI generates generic test workflow
```

### Scenario 3: Muscle Memory
```bash
# User from another tool expecting different syntax
pflow list          # Expecting to list something
# Result: AI tries to create a "list" workflow
```

## Solution: Two-Part Fix

### Part 1: Transparently Strip "run" Prefix

Users habitually type `run` from other tools (npm run, cargo run, etc.). We should silently handle this:

```python
def resolve_workflow(identifier: str, wm: WorkflowManager | None = None) -> tuple[dict | None, str]:
    # NEW: Transparently strip "run" prefix
    words = identifier.split()
    if words and words[0] == 'run':
        if len(words) == 1:
            # Just "run" by itself
            raise WorkflowNotFoundError("Need to specify what to run.\n\n"
                                       "Usage: pflow <workflow-name>\n"
                                       "List workflows: pflow workflow list")
        # Strip "run" and continue normally
        identifier = ' '.join(words[1:])

    # Continue with normal resolution...
```

### Part 2: Block Single Words from Planner

After stripping "run", check if we have a single word without context:

```python
def resolve_workflow(identifier: str, wm: WorkflowManager | None = None) -> tuple[dict | None, str]:
    # ... run stripping logic above ...
    # ... existing file path checks ...

    # Check saved workflows
    saved_workflow = wm.get_workflow(identifier)
    if saved_workflow:
        return saved_workflow, "saved"

    # NEW: Single word check - prevent planner activation
    if " " not in identifier and "=" not in identifier:
        # Single word with no parameters - don't send to planner
        error_msg = get_single_word_error(identifier)
        raise WorkflowNotFoundError(error_msg)

    # Multi-word or has parameters - can go to planner
    return None, "natural_language"

def get_single_word_error(word: str) -> str:
    """Generate contextual error for single word inputs."""

    # Only special-case VERY obvious mistakes
    if word == 'workflows':  # Clear typo
        return "Did you mean: pflow workflow list"

    if word in ['help', '--help', '-h']:  # Help-seeking
        return "For help: pflow --help"

    if word in ['list', 'ls']:  # Common CLI patterns
        return "Did you mean: pflow workflow list"

    # Default: assume it's a workflow name that wasn't found
    # Don't assume whether "test", "analyze" etc. are verbs or workflow names
    return (f"Workflow '{word}' not found.\n\n"
            "For saved workflows: pflow workflow list\n"
            "To create workflow: pflow \"describe what you want to do\"")
```

### Behavior After Fix

```bash
# "run" prefix - TRANSPARENTLY HANDLED
pflow run my-workflow          # → Same as: pflow my-workflow
pflow run test-suite           # → Same as: pflow test-suite
pflow run ./workflow.json      # → Same as: pflow ./workflow.json
pflow run "analyze data"       # → Same as: pflow "analyze data"
pflow run                      # → Error: "Need to specify what to run"

# Single words - ERROR (fast, clear)
pflow workflows                # → Error: "Did you mean: pflow workflow list"
pflow analyze                  # → Error: "Workflow 'analyze' not found..."
pflow test                     # → Error: "Workflow 'test' not found..."
pflow list                     # → Error: "Did you mean: pflow workflow list"

# Multi-word - ALWAYS PLANNER (by design)
pflow analyze data             # → Planner (multi-word = natural language)
pflow test my api              # → Planner (multi-word = natural language)
pflow create report            # → Planner (user is describing intent)

# Single word with params - PLANNER
pflow test input=data.csv      # → Planner (has parameter = context provided)

# Saved workflows - SINGLE WORDS (including kebab-case)
pflow my-workflow              # → Executes if exists (single word)
pflow analyze-data             # → Executes if exists (single word, kebab-case)
pflow my-workflow param=value  # → Executes with params
pflow ./my-workflow.json       # → Executes from file (path detected)
```

## Benefits of This Change

1. **Faster Feedback**: Instant error instead of 10+ second wait
2. **Clearer Intent**: Forces users to be explicit about AI usage
3. **Resource Efficient**: No wasted API calls on meaningless prompts
4. **Better UX**:
   - Helpful errors guide to correct usage
   - "run" prefix works transparently
   - Common mistakes get specific suggestions
5. **Predictable**: Single words = check saved only
6. **Habit-Friendly**: Users from npm/cargo/etc can keep typing "run"

## Implementation Impact

- **Code Change**: ~30 lines in `resolve_workflow()` + helper function
- **Test Updates**:
  - Add tests for single-word rejection
  - Add tests for "run" stripping
  - Add tests for contextual errors
- **Breaking Change**: Yes, but improves UX significantly
- **User Impact**: Positive - prevents confusion and wasted time

## Decision Required

This is a minor breaking change that significantly improves UX. Since we have zero users (MVP stage), now is the perfect time to fix this design flaw.

### Recommendation
Implement both changes:
1. **Transparently strip "run" prefix** - Zero friction for users with muscle memory
2. **Block single words from planner** - Prevent wasteful AI calls

This aligns with Task 22's philosophy of "making things just work" while preventing things that shouldn't work.

## Alternative Considerations

### Alternative 1: Always Send to Planner (Current)
- ❌ Wastes time and resources
- ❌ Confuses users with irrelevant results
- ❌ 10+ second wait for typos

### Alternative 2: Minimum Word Count (3+)
- ❌ Too restrictive: "analyze data" is valid
- ❌ Arbitrary threshold

### Alternative 3: Extensive Word Classification
- ❌ Can't know if "test" is a workflow name or verb
- ❌ Maintenance burden
- ❌ Will inevitably guess wrong

### Alternative 4: Require Quotes for Planner
- ❌ Adds friction for legitimate requests
- ❌ Not discoverable

### Chosen Solution ✅
**Hybrid approach**: Strip "run" + block single words + minimal special cases
- Prevents accidental AI activation
- Handles common habits (run prefix)
- Conservative about assumptions
- Fast, clear error messages
- Maintains ease of use for multi-word requests

## Complete Implementation Example

```python
def resolve_workflow(identifier: str, wm: WorkflowManager | None = None) -> tuple[dict | None, str]:
    """Resolve workflow from file path, saved name, or natural language.

    Resolution order:
    1. Strip "run" prefix if present
    2. Check if it's a file path
    3. Check saved workflows
    4. Block single words from planner
    5. Allow multi-word/parameterized to planner
    """
    if not wm:
        wm = WorkflowManager()

    # Strip "run" prefix transparently
    words = identifier.split(maxsplit=1)  # Split into at most 2 parts
    if words and words[0] == 'run':
        if len(words) == 1:
            # Just "run" by itself
            raise WorkflowNotFoundError(
                "Need to specify what to run.\n\n"
                "Usage: pflow <workflow-name>\n"
                "List workflows: pflow workflow list"
            )
        # Continue with everything after "run"
        identifier = words[1]

    # Check if it's a file path
    if "/" in identifier or identifier.endswith(".json"):
        # Handle file paths...
        pass

    # Try saved workflows (with and without .json)
    if identifier.endswith(".json"):
        name_without_ext = identifier[:-5]
        saved = wm.get_workflow(name_without_ext)
        if saved:
            return saved["ir"], "saved"

    saved = wm.get_workflow(identifier)
    if saved:
        return saved["ir"], "saved"

    # Block single words from reaching planner
    if " " not in identifier and "=" not in identifier:
        error_msg = get_single_word_error(identifier)
        raise WorkflowNotFoundError(error_msg)

    # Multi-word or has parameters - ALWAYS goes to planner
    # This is intentional: multi-word = user wants to describe something
    return None, "natural_language"

def get_single_word_error(word: str) -> str:
    """Generate helpful error for single-word inputs."""

    # Minimal special cases for obvious mistakes
    if word == 'workflows':
        return "Did you mean: pflow workflow list"

    if word in ['help', '--help', '-h']:
        return "For help: pflow --help"

    if word in ['list', 'ls']:
        return "Did you mean: pflow workflow list"

    # Default: treat as workflow name not found
    return (f"Workflow '{word}' not found.\n\n"
            "For saved workflows: pflow workflow list\n"
            "To create workflow: pflow \"describe what you want to do\"")
```

This implementation is clean, predictable, and user-friendly.

## Summary

The current behavior of sending single words to the AI planner is a **design bug**, not a feature. It:
- Wastes 10+ seconds on meaningless prompts
- Costs API tokens for no value
- Confuses users who make typos or have different expectations
- Violates the principle of "least surprise"

The proposed two-part fix:
1. **Transparently strips "run"** - Handles user habits from other tools
2. **Blocks single words** - Prevents wasteful planner activation

This small change (~30 lines) would:
- Save users from accidental 10+ second waits
- Provide instant, helpful feedback
- Make the tool more predictable
- Align with Task 22's simplification philosophy

Since we're at MVP stage with zero users, now is the perfect time to fix this before it becomes entrenched behavior.

### Edge Cases Considered

- **"run" alone**: Shows helpful error about what to run
- **"run run"**: Would become just "run", then check for saved workflow
- **Workflow named "run"**: After stripping first "run", would find the saved workflow
- **Parameters with single word**: `analyze input=file.csv` still goes to planner
- **Quoted single words**: Could add support for `pflow "analyze"` if explicit planner request needed