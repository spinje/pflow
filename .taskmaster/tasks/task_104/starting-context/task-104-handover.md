# Task 104 Handoff: Python Script Node

## How We Got Here - The Journey Matters

This task emerged organically from fixing a shell validation bug. Understanding this journey is crucial because it reveals the **real problem** the script node solves.

### The Original Bug (Issue #29)
We discovered that shell node's dict/list validation was broken:
1. `_check_command_template_safety()` ran AFTER template resolution - dead code
2. `_warn_shell_unsafe_json()` regex matched shell syntax like `[a-z]` - false positives

### The Fix Led to a Realization
While fixing this, we blocked dict/list in shell command parameters at compile time. This led to a critical discussion:

**User asked**: "Is blocking really the perfect solution?"

We explored shell escaping as an alternative but concluded it's essentially impossible to do 100% robustly because:
- Shell syntax is context-dependent (single quotes vs double quotes vs unquoted)
- You'd need to parse shell commands to detect quote context
- Different shells (bash/sh/zsh) have different rules
- Edge cases are endless

**Then the user made a key observation**: `${user.name}` (accessing nested string fields) already works! We're only blocking whole dict/list objects.

This means the problem space is actually smaller than we thought:
- `${user.name}` → string → ✅ Works
- `${user}` → dict → ❌ Blocked, use stdin
- Multiple dicts → ❌ Blocked, use... what?

### The Gap: Multiple Structured Inputs

stdin handles ONE dict elegantly. But what about:
```json
{"command": "process --config='${config}' --data='${data}'"}
```

Current workarounds are clunky:
1. **Temp files** - Write each to file, shell reads files (verbose)
2. **Shell + Python -c** - Still one stdin, code is escaped string nightmare

**User asked**: "Is a native script node better than using Python in shell?"

Answer: **Significantly better.**

## The Core Insight

A Python script node completely sidesteps shell complexity:

| Aspect | Shell + Python | Script Node |
|--------|---------------|-------------|
| Multiple inputs | ❌ One stdin | ✅ Unlimited native objects |
| Serialization | ❌ JSON roundtrip | ✅ None needed |
| Code readability | ❌ Escaped string in string | ✅ Clean Python code |
| Error messages | ❌ Cryptic shell errors | ✅ Python traceback with line numbers |
| Debugging | ❌ Hard | ✅ Easy |

The script node doesn't need escaping because **there's no shell layer parsing the data**.

## Critical Technical Context

### Template Resolution Timing

This is subtle but critical. In `node_wrapper.py` line ~862:
```python
merged_params = {**self.static_params, **resolved_params}
self.inner_node.params = merged_params
```

Templates are resolved by the wrapper BEFORE `node.prep()` runs. The old shell check was dead code because by prep() time, `${data}` was already `"[1, 2, 3]"` (JSON string).

For the script node, this means:
- `inputs: {"data": "${data}"}` will be resolved BEFORE your node runs
- You'll receive the actual Python dict, not a template string
- The wrapper handles all template resolution for you

### Type Inference Behavior

When we check types at validation time:
```python
infer_template_type("user", workflow_ir, node_outputs)      # → "object"
infer_template_type("user.name", workflow_ir, node_outputs) # → None
```

Nested field access returns `None` because we can't always infer nested types. Our validation skips `None` types (permissive). This is why `${user.name}` passes through - we don't know it's a string, but we allow it.

For the script node, you don't need to worry about this. You receive native Python objects - types are preserved automatically.

### How Shell Node Handles stdin (Reference Pattern)

Look at `shell.py` method `_adapt_stdin_to_string()` (around line 257 in current code):
```python
if isinstance(stdin, (dict, list)):
    return json.dumps(stdin, ensure_ascii=False)
```

Shell node serializes dict/list to JSON for stdin. **Your script node shouldn't need this** - pass dicts as dicts.

## Design Decisions Already Made

The user explicitly agreed to these:

1. **Python-only (MVP)** - pflow IS Python, guaranteed available
2. **In-process execution** - Use `exec()`, not subprocess
3. **Sandboxed globals** - Restrict `__builtins__` for security
4. **`result` variable as output** - User sets `result = ...`, node captures it
5. **Multiple inputs via `inputs` dict** - Each key becomes a local variable

## What the User Cares About

Throughout this session, the user showed strong preferences:

1. **Agent usability** - Error messages must be crystal clear and actionable
2. **Simplicity** - MVP mindset, no over-engineering
3. **Real solutions** - Don't suggest things that don't work (we updated error messages to remove bad suggestions)

The script node should have excellent error messages:
- Missing `result` variable: "Script did not set 'result' variable. Add: result = <your value>"
- Syntax error: Show the exact line in their code
- Runtime error: Full traceback pointing to their code

## Relationship to Task 103

Task 103 is about preserving types when resolving templates inside dict/list values:
```json
{"stdin": {"a": "${data-a}", "b": "${data-b}"}}
```

Currently this double-serializes (inner dicts become JSON strings). Task 103 would fix this.

**For your script node**: Task 103 is NOT a dependency. Your node receives inputs as native objects through the `inputs` parameter, not through stdin serialization. You're solving the problem differently.

However, if Task 103 is completed, shell node could also support multiple inputs via stdin. The script node remains superior for code readability and error handling.

## Files You'll Need

**Node implementation patterns**:
- `src/pflow/nodes/shell/shell.py` - Complex node with stdin, good reference
- `src/pflow/nodes/llm/llm.py` - Simpler node, cleaner interface definition

**Template system**:
- `src/pflow/runtime/template_resolver.py` - How templates get resolved
- `src/pflow/runtime/node_wrapper.py` - How nodes receive resolved params (TemplateAwareNodeWrapper)

**Registry/Interface**:
- `src/pflow/registry/metadata_extractor.py` - How node interfaces are extracted from docstrings

**PocketFlow base**:
- `pocketflow/__init__.py` - Base Node class with prep/exec/post lifecycle

## Security Considerations

The user mentioned sandboxing but didn't deep-dive. Consider:

```python
SAFE_BUILTINS = {
    'len', 'str', 'int', 'float', 'bool', 'list', 'dict', 'tuple', 'set',
    'range', 'enumerate', 'zip', 'map', 'filter', 'sorted', 'reversed',
    'min', 'max', 'sum', 'abs', 'round', 'any', 'all',
    'isinstance', 'type', 'hasattr', 'getattr',
    'True', 'False', 'None',
}

BLOCKED_BUILTINS = {
    'open', 'exec', 'eval', 'compile', '__import__', 'input',
    'globals', 'locals', 'vars', 'dir', 'breakpoint',
}
```

Also consider:
- Timeout for runaway loops (user mentioned 30s default)
- No `__builtins__['__loader__']` tricks
- Possibly restrict attribute access on certain types

## Questions Still Open

These weren't definitively resolved:

1. **Multiline code format** - How does user write multiline Python in JSON?
   - Option A: String with `\n`
   - Option B: Array of lines `["line1", "line2"]`
   - Option C: Support both

2. **Import support** - Can users `import json` or `import re`?
   - Safe: json, re, math, datetime, collections
   - Unsafe: os, sys, subprocess, socket

3. **Output beyond `result`** - Capture `print()` statements?
   - The task spec mentions optional stdout capture

## Final Advice

The script node is conceptually simple but the devil is in the details:
1. Get basic exec() working first
2. Add sandboxing carefully
3. Focus on error messages - they're how agents learn to use the node
4. Don't over-engineer - it's MVP

The user said something profound: "why haven't we considered this earlier?" The answer is we were too focused on fixing the immediate bug. Sometimes stepping back reveals a better solution.

---

**IMPORTANT**: Do not begin implementing yet. Read this document, read the task spec at `.taskmaster/tasks/task_104/task-104.md`, and confirm you understand the context. Then say you're ready to begin.
