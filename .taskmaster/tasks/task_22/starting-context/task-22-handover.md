# Task 22: Named Workflow Execution - Critical Handover Knowledge

**STOP**: Read this entire document before starting ANY implementation. Say "I'm ready to begin implementing Task 22" only after you've absorbed everything here.

## 🔥 The Big Discovery That Changes Everything

**70% of named workflow execution is ALREADY IMPLEMENTED but buried under 200+ lines of unnecessary complexity.**

I spent hours investigating and discovered that:
- `pflow my-workflow param=value` already works for kebab-case names
- Parameter validation against workflow inputs ALREADY WORKS via `prepare_inputs()`
- Type conversion ALREADY WORKS via `infer_type()`
- Default values are ALREADY APPLIED for optional parameters
- The WorkflowManager is FULLY IMPLEMENTED with all needed methods

The problem isn't missing functionality - it's that the working code is hidden behind complex routing logic with THREE separate paths that all eventually call the same `execute_json_workflow()` function.

## 🎯 The User's Vision (They're Passionate About This)

The user was extremely enthusiastic when we discovered we could DELETE 200 lines of code rather than add features. They want radical simplification:

> "Everything should just work" - whether users type `pflow my-workflow`, `pflow workflow.json`, or `pflow ./workflow.json`

The user explicitly said: "We have ZERO users, this is the perfect time to break things for a better design." They chose removing `--file` completely over any backward compatibility.

## 💎 Hidden Gems You Must Know About

These functions ALREADY EXIST and work perfectly (I verified each one):

1. **`prepare_inputs(ir_dict, params)`** - Returns `(errors, defaults)` tuple
   - Already validates required vs optional
   - Already returns structured errors with message, path, suggestion
   - Already computes defaults to apply
   - Location: `src/pflow/runtime/workflow_validator.py`

2. **`infer_type(value: str)`** - Converts CLI strings to Python types
   - Handles: bool, int, float, JSON arrays/objects, strings
   - "true" → True, "5" → 5, '["a","b"]' → ["a","b"]
   - Location: `src/pflow/cli/main.py:1095`

3. **`WorkflowManager` class** - Complete implementation
   - `.exists(name)` - Check if workflow exists
   - `.load_ir(name)` - Get just the IR
   - `.list_all()` - Get all workflows with metadata
   - Storage: `~/.pflow/workflows/{name}.json`

## 🗑️ The Exact Functions to DELETE (This is Liberation)

Delete these functions from `src/pflow/cli/main.py` - they're the complexity hiding the simplicity:

1. `get_input_source()` - Lines ~150-195 (45 lines)
2. `_determine_workflow_source()` - Lines ~96-113 (15 lines)
3. `_determine_stdin_data()` - Lines ~116-152 (35 lines)
4. `process_file_workflow()` - Lines ~1024-1059 (35 lines)
5. `_execute_json_workflow_from_file()` - Lines ~975-1023 (35 lines)
6. `_get_file_execution_params()` - Lines ~864-884 (20 lines)

**Total: ~185-200 lines to DELETE**

## ⚠️ Critical Update: Shell Pipe Bug JUST Got Fixed

During our planning, I kept warning about a shell pipe bug that caused hangs. This was JUST FIXED (BF-20250901-tty-pipes-outputs):

**What changed**: CLI now checks both stdin AND stdout are TTYs before showing prompts

**Impact**: You can now safely test with:
```bash
pflow workflow | grep something  # Now works!
pflow workflow && echo done      # Now works!
pflow --output-format json workflow | jq '.result'  # Now works!
```

I updated the docs to reflect this, but be aware some comments in the code might still reference the old bug.

## 🚨 Critical Pattern Discoveries

### The Three-Path Duplication Pattern
```python
# Current insanity - THREE paths doing the same thing:
Path 1: _try_direct_workflow_execution() → parse_workflow_params() → execute_json_workflow()
Path 2: process_file_workflow() → _get_file_execution_params() → execute_json_workflow()
Path 3: _execute_with_planner() → (generates IR) → execute_json_workflow()

# Your simple solution - ONE path:
resolve_workflow() → parse_workflow_params() → execute_json_workflow()
```

### The is_likely_workflow_name() Limitation
Currently it's too conservative - single words like `pflow analyze` go to the planner. The user wants this improved but keep it simple - just add detection for `.json` and `/` characters.

## 🛑 What NOT to Do (The User Was Clear)

1. **DON'T add fuzzy matching** - The codebase uses simple substring matching everywhere. Don't add difflib or Levenshtein.

2. **DON'T keep --file "for compatibility"** - The user explicitly rejected this. We have no users. Delete it completely.

3. **DON'T create abstraction layers** - Use existing functions directly. Don't wrap WorkflowManager methods.

4. **DON'T overthink similarity** - Simple substring matching like the registry uses is fine:
   ```python
   similar = [n for n in all_names if name.lower() in n.lower()][:3]
   ```

## 🔗 Critical Code Locations

Functions you'll use directly:
- `parse_workflow_params()` - Line 1135 in main.py
- `infer_type()` - Line 1095 in main.py
- `execute_json_workflow()` - Line 792 in main.py
- `prepare_inputs()` - In workflow_validator.py
- `WorkflowManager` - In core/workflow_manager.py

Routing to update:
- `main_wrapper.py` - Add "workflow" command routing like "registry"
- End of `workflow_command()` in main.py - Replace complex branching

## 🧠 Subtle Gotchas I Discovered

1. **Saved workflows have metadata wrappers** - When loading from WorkflowManager, you get the IR directly. But when loading from a file, check if it has an 'ir' field (wrapper) or is raw IR.

2. **The planner saves workflows interactively** - Only when both stdin and stdout are TTYs (after the recent fix). This is in `_prompt_workflow_save()`.

3. **StdinData is a complex type** - It can have text_data, binary_data, or temp_path. Just pass it through to execute_json_workflow.

4. **ValidationError has structure** - It has message, path, and suggestion fields. Use them all in error messages.

5. **Single-word workflow detection** - The current heuristics require either kebab-case OR parameters. That's why `pflow analyze` doesn't work but `pflow analyze-code` does.

## 📊 The User's Decision Process

When we had to choose between options, the user consistently chose:
- Simplicity over compatibility
- Deletion over refactoring
- Breaking changes over gradual migration
- Clear errors over complex detection
- Existing patterns over new abstractions

The user got genuinely excited when they realized we could remove the --file flag entirely. They see this as making pflow "magical" - users just type what feels natural and it works.

## 🎪 The Beautiful Simplicity Pattern

The entire resolution logic should be ~30 lines:
```python
def resolve_workflow(identifier: str, wm: WorkflowManager = None) -> tuple[dict, str]:
    # 1. Files (has / or .json)
    # 2. Saved exact match
    # 3. Saved without .json
    # That's it!
```

Compare to the current ~200 lines of routing logic!

## 🔮 Final Wisdom

This task is about REMOVING complexity, not adding it. Every time you're tempted to add something, ask: "Can I delete something instead?"

The system already does what we need. Your job is to expose the elegant simplicity that's already there by deleting the code that hides it.

When you see how much code you're deleting, you'll know you're on the right path. This should feel like archaeology - uncovering something beautiful that was always there, just buried.

## 📚 Documents You Have

- `task-22-spec.md` - The formal requirements (follow precisely)
- `implementation-guide.md` - All the discoveries and step-by-step guidance
- `task-22-implementation-prompt.md` - Your main instructions
- This handover - The tacit knowledge and context

## Your First Concrete Steps

1. Create your progress log
2. Read all the context files
3. Find the 6 functions to delete and verify the line numbers
4. Create resolve_workflow() using the exact code from the implementation guide
5. Start deleting!

Remember: The user wants this to feel magical. No flags, no special knowledge. Just type what feels natural and it works.

---

**DO NOT BEGIN IMPLEMENTATION YET** - First, confirm you've read and understood everything by saying "I'm ready to begin implementing Task 22" and briefly summarizing the key insight about deletion over addition.