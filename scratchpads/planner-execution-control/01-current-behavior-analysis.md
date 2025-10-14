# Current Behavior Analysis: When Does Planner Execute?

## The Problem

Currently, the planner executes for many cases it shouldn't. We want it to ONLY execute when:
```bash
pflow "natural language prompt"  # Single quoted string
```

But it currently ALSO executes for:
```bash
pflow lets do this thing          # Multiple unquoted words
pflow jkahsd "some prompt"        # Word before quoted string
pflow --trace some random words   # Multiple words after flags
```

## Shell Argument Processing (Pre-Click)

Before Click even sees arguments, the shell processes them:

```bash
# Shell parses these as:
pflow "do something"              → ["pflow", "do something"]           (1 arg)
pflow lets do this                → ["pflow", "lets", "do", "this"]     (3 args)
pflow jkahsd "do something"       → ["pflow", "jkahsd", "do something"] (2 args)
pflow workflow.json               → ["pflow", "workflow.json"]          (1 arg)
pflow my-workflow input=file.txt  → ["pflow", "my-workflow", "input=file.txt"] (2 args)
```

## Click Processing

Click receives `sys.argv[1:]` and processes it based on decorators:

```python
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
```

This means:
- `nargs=-1`: Accept 0 or more arguments
- `type=click.UNPROCESSED`: Don't parse them, pass through as-is
- Result: `workflow` parameter is a `tuple[str, ...]`

## Current Execution Flow

In `workflow_command()` at lines 3373-3405:

```
1. Read stdin
2. Preprocess: handle 'run' prefix (strip it if present)
3. Try: _try_execute_named_workflow()
   ├─ Uses is_likely_workflow_name() heuristics
   ├─ If file path or saved workflow name detected → execute directly
   └─ Returns True if handled, False otherwise
4. Validate for natural language: _validate_and_prepare_natural_language_input()
   └─ Just joins workflow tuple with spaces and checks length
5. Try: _handle_single_token_workflow()
   ├─ If len(workflow)==1 AND no spaces in workflow[0]
   ├─ Try to load as saved workflow
   └─ Show helpful error if not found
6. FALLBACK: _execute_with_planner()
   └─ Everything that reaches here goes to planner
```

## The Issue: Step 6 is Too Permissive

**Current logic:**
```python
# After steps 3-5, if nothing matched, execute with planner
_execute_with_planner(ctx, raw_input, ...)
```

**This means ANY input that:**
- Is NOT a file path or saved workflow name
- Is NOT a single word
- Reaches this point → GOES TO PLANNER

## Examples Traced Through Current Flow

### Example 1: `pflow "do something"` ✅ CORRECT
```
workflow = ("do something",)
├─ Step 3: is_likely_workflow_name("do something", ()) → False (has space)
├─ Step 5: len==1 but HAS spaces → Skip
└─ Step 6: GO TO PLANNER ✅ CORRECT
```

### Example 2: `pflow lets do this thing` ❌ WRONG (should ERROR)
```
workflow = ("lets", "do", "this", "thing")
├─ Step 3: is_likely_workflow_name("lets", ("do"...)) → False
├─ Step 5: len==4 → Skip
└─ Step 6: GO TO PLANNER ❌ SHOULD ERROR
```

### Example 3: `pflow jkahsd "do something"` ❌ WRONG (should ERROR)
```
workflow = ("jkahsd", "do something")
├─ Step 3: is_likely_workflow_name("jkahsd", ("do something",)) → False
├─ Step 5: len==2 → Skip
└─ Step 6: GO TO PLANNER ❌ SHOULD ERROR
```

### Example 4: `pflow workflow.json` ✅ CORRECT
```
workflow = ("workflow.json",)
├─ Step 3: is_likely_workflow_name("workflow.json", ()) → True (ends with .json)
├─ resolve_workflow() → loads and executes
└─ DONE ✅ CORRECT
```

### Example 5: `pflow my-workflow input=file.txt` ✅ CORRECT
```
workflow = ("my-workflow", "input=file.txt")
├─ Step 3: is_likely_workflow_name("my-workflow", ("input=file.txt",))
│  └─ Returns True (has '-' and remaining has '=')
├─ resolve_workflow() → loads and executes with params
└─ DONE ✅ CORRECT
```

## Key Insight: What Makes Valid Planner Input?

Valid planner input should be:
1. **Single argument** (len(workflow) == 1)
2. **Contains spaces** (was quoted in shell)
3. **Not a file path** (no .json, no /, etc.)

Invalid cases that currently reach planner:
1. Multiple unquoted words: `pflow lets do this`
2. Mixed quoted/unquoted: `pflow jkahsd "prompt"`
3. Random text: `pflow asdfasdf asdfasdf`

## Root Cause

The fallback in step 6 assumes "if it's not a saved workflow or single word, it must be natural language."

But this is wrong! Most invalid inputs also aren't workflows or single words.

We need to **validate the structure** before sending to planner, not just fallback.

