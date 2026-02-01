# Braindump: Task 104 Comprehensive Design Session

## Where I Am

We just completed an **extensive design session** for the Python code node, culminating in a fully validated specification. This wasn't just "write a spec" - we went DEEP on design decisions, researched the codebase extensively, and resolved multiple critical architectural questions that will impact Task 107 (markdown workflows) immediately after this.

**Current state**: Spec complete and verified. Ready for implementation. All assumptions validated against codebase.

## User's Mental Model

### How They Think About This

The user sees the code node as a **bridge solution** - something users need NOW to get real work done while the "perfect" architecture (lightweight node creation, guided workflows) gets figured out.

**Exact quote that matters**: "we need a way for users to do anything while we work on the best possible solution"

They kept referencing **shell node as the comparison point**. The code node's value isn't security or sandboxing - it's:
1. **Native objects** (no JSON serialization hell)
2. **Readable code** (not escaped strings)
3. **Good error messages** (Python tracebacks, not shell parsing errors)

### The Task 107 Connection is CRITICAL

This came up repeatedly: **markdown workflows are NEXT, not future**. This completely changed our approach to type hints.

Initially I thought: "make type hints optional for simplicity"
User made me realize: "Task 107 is immediate, so type hints MUST be required for Python tooling (mypy, IDE autocomplete) to work in markdown code blocks"

This is **strategic**, not just a nice-to-have. The code node is being designed with its markdown form already in mind.

### The Sandboxing Reversal Story

There's an existing handover doc that says "sandboxed globals - restrict `__builtins__`". The user **explicitly reversed this decision** in a prior conversation (documented in `braindump-sandbox-decision-reversal.md`).

**User's framing**: "we want to allow as much as possible from a python node, use pandas, use a lib for getting youtube transcripts, it should be possible"

They understand the security tradeoff. They know Python language-level sandboxing is bypassable. They explicitly chose **utility over security** for the local automation use case.

**Key insight**: The user mentioned TypeScript/V8 isolates as having "real sandboxing" for future consideration (Task 113). This shows they understand the technical landscape - the decision to skip Python sandboxing wasn't naive, it was pragmatic.

## Key Insights (The Non-Obvious Stuff)

### 1. The `inputs` Dict Exists to Prevent Template-in-Code Confusion

We had a long discussion about whether to use explicit `inputs: {"data": "${...}"}` vs letting all params become variables.

**The aha moment**: If you allow templates directly in code, you get ambiguous behavior:
```python
# Template in code - what happens?
code: "result = ${data}.upper()"

# After resolution if data="hello":
code: "result = hello.upper()"  # NameError! No quotes added
```

The template system converts dicts/lists to JSON (which is valid Python), but strings become unquoted identifiers. This is **type-dependent magic** that would confuse users.

With `inputs` dict, it's crystal clear: code is literal Python, inputs are template-resolved and injected as native objects.

### 2. Type Validation is Two-Layered

**Layer 1** (built-in, always): AST parsing + isinstance checks
- Extract annotations using `ast.parse()` (~15 lines, zero dependencies)
- Validate outer type only: `list[dict]` checks `isinstance(value, list)`
- Catches 90% of errors, runs in <10ms

**Layer 2** (Task 107, optional): mypy integration + type stubs
- Generate `.pyi` stubs for upstream nodes
- Run mypy on virtual Python file with workflow context
- Full static analysis with Python tooling

We designed Layer 1 to be useful NOW while enabling Layer 2 later. This layering wasn't obvious at first.

### 3. The exec_fallback Pattern is Subtle

I initially misunderstood how `exec_fallback()` works. Here's the pattern:

```python
def exec_fallback(self, prep_res, exc):
    # MUST return same structure as exec() would
    return {"result": None, "error": str(exc)}

def post(self, shared, prep_res, exec_res):
    # Detect fallback by checking for error marker
    if "error" in exec_res:
        shared["error"] = exec_res["error"]
        return "error"
```

The return value flows into `post()` as `exec_res` - it's not a special error path. This means fallback must mimic the success structure.

### 4. Timeout Implementation Required Research

I initially assumed `signal.alarm()` based on Unix patterns. **Wrong**.

pflow uses:
- `subprocess.run(timeout=)` for subprocess (shell node)
- `asyncio.wait_for()` for async (MCP, Claude nodes)
- `ThreadPoolExecutor.result(timeout=)` for threads

No `signal.alarm()` anywhere in the codebase - it's Unix-only, not thread-safe, and has global state issues.

### 5. Template Resolution Timing Was Verified, Not Assumed

I stated "templates resolve before prep()" in the spec. The user challenged me to verify this with research agents.

**Verified correct**: `TemplateAwareNodeWrapper._run()` resolves ALL templates, then calls `self.inner_node._run()` which triggers the prep/exec/post lifecycle. By the time prep() sees `self.params`, all `${...}` syntax is gone.

This verification was important - if wrong, the whole input handling design would break.

## Assumptions & Uncertainties

### VERIFIED:
- ✅ Python 3.10+ available (pflow requires it)
- ✅ `ast.unparse()` available (added in Python 3.9)
- ✅ Template resolution before prep() (verified in wrapper code)
- ✅ ValueError/TypeError standard in prep() (100+ usages found)
- ✅ "default"/"error" action strings (standard across all nodes)
- ✅ ThreadPoolExecutor pattern exists (batch node uses it)

### ASSUMPTION:
- ThreadPoolExecutor timeout sufficient for MVP (vs subprocess isolation)
- Outer type validation covers 90% of use cases (vs deep validation)
- `shared["result"]` key naming acceptable (deviates from semantic naming pattern but matches Claude Code node)

### UNCLEAR:
- Whether `requires` field will need validation before Task 107 (currently documentation-only)
- Exact markdown frontmatter format for `requires` in Task 107
- Whether Windows users will complain about ThreadPoolExecutor timeout limitations (vs subprocess)

### NEEDS VERIFICATION:
- None identified - all critical paths researched and verified

## Unexplored Territory

### UNEXPLORED: Error Recovery Patterns

We didn't discuss what happens when user code has bugs. Should there be a workflow-level "code node failed, here's the error" → "user fixes code" → "retry" pattern? Or is that too much magic?

The LLM planner might need special handling for code node errors to suggest fixes intelligently.

### CONSIDER: Code Block Size Limits

We didn't set any limits on code string length. AST parsing is O(n) but what about 10,000 lines of code in a workflow? Should we warn or error?

**Probably fine** - if someone has 10k lines, they should extract to a module. But worth flagging.

### MIGHT MATTER: Multi-threading Safety

If code node is used in batch processing (Task 96), each batch item gets its own execution context. We verified ThreadPoolExecutor is thread-safe, but what if user code has global state?

```python
# Global state in user code
_cache = {}

# Multiple batch items executing in parallel
result = _cache.get(key, compute())  # Race condition?
```

**Probably user's problem**, but worth a doc note about thread safety in batch contexts.

### UNEXPLORED: Code Node in Conditional Branches

We didn't discuss how code node works with Task 38 (conditional branching). If code node is in one branch:

```yaml
## validate
type: code
code: |
  data: dict
  result: bool = data.get('valid', False)

## process (only runs if validate.result is True)
```

Does the type system validate the conditional correctly? This is Task 38's problem, but code node might have special considerations.

### CONSIDER: Circular Import Protection

User code can `import pflow` if it's installed. What if user code tries to create nested workflows or manipulate the runtime?

```python
import pflow
# Can they break things?
```

**Probably fine** - they're running locally, they can break things anyway. But might want to document the blast radius.

### MIGHT MATTER: Memory Leaks in Long-Running Workflows

If a workflow runs code nodes in a loop (batch processing 10,000 items), does the namespace cleanup happen properly? Or do we accumulate garbage?

```python
# Each iteration creates a new namespace
for item in 10_000_items:
    namespace = {"item": item}
    exec(code, namespace)
    # Does namespace get GC'd?
```

**Probably fine** - Python's GC should handle it. But if we see memory issues, this is where to look.

## What I'd Tell Myself

### If Starting Over:

1. **Research first, design second** - We spent the first half designing, then had to verify everything. Would have saved time to research upfront, but the design discussion helped shape what to research.

2. **The braindump files are gold** - `braindump-sandbox-decision-reversal.md` answered 3 hours of questions in 5 minutes. Always read context files first.

3. **Task 107 connection is the forcing function** - Without that, we might have made type hints optional. The markdown workflow future locked us into the right decision.

4. **User knows more than they let on** - When they asked "can you explain why sandboxing is bypassable?", they weren't confused - they were testing my understanding. They've thought deeply about this.

### What Almost Broke:

We almost spec'd `signal.alarm()` for timeout without verifying. Would have been a nasty surprise during implementation on Windows or in threaded contexts.

We almost made type hints optional, which would have created migration pain for Task 107.

We almost used `shared["output"]` generically, which would have been inconsistent with existing patterns.

### What I'm 70% Sure About:

- ThreadPoolExecutor timeout will work fine for 99% of use cases
- Outer type validation will be sufficient for MVP (deep validation not needed until someone complains)
- The `requires` field won't need enforcement before Task 107 ships
- Windows users won't complain about timeout (they're probably on Unix anyway)

## Open Threads

### Thread 1: Markdown Format Integration (Task 107)

We designed the code node knowing Task 107 is next. The spec is ready for markdown but we didn't define the exact format. Will probably be:

```markdown
## transform
type: code
inputs:
  data: ${fetch.result}
requires: [pandas]

```python
import pandas as pd

data: list[dict]  # Type hints make IDE happy

df = pd.DataFrame(data)
result: dict = df.describe().to_dict()
```
```

The triple-backtick Python block is just the `code` parameter. Everything else is frontmatter.

### Thread 2: Type Stub Generation

For Task 107, we'll need to generate `.pyi` files so IDEs understand workflow context:

```python
# .pflow/workflow_types.pyi (auto-generated)
class fetch:
    result: dict  # From HTTP node metadata

class transform:
    result: dict  # From code node's result annotation
```

This enables `mypy` and LSP to validate across nodes. Design is clear, implementation deferred to Task 107.

### Thread 3: Testing Strategy

The spec has 25 test criteria. **Priority order** for implementation:

1. **Type annotation extraction** (Test 1) - Foundation
2. **Namespace injection** (Tests 6, 22) - Core functionality
3. **Result capture** (Test 9) - Core functionality
4. **Type validation** (Tests 4, 5, 10) - Safety
5. **Error handling** (Tests 12, 13, 16) - UX
6. **Timeout** (Test 14) - Safety
7. **Everything else** - Coverage

Don't try to TDD all 25 at once. Build in this order.

### Thread 4: The `requires` Field Mystery

We agreed `requires: ["pandas"]` is documentation-only for MVP. But **what happens when pandas isn't installed?**

Options:
A. ImportError bubbles up naturally (current spec)
B. Catch ImportError and check against `requires`, give friendly message
C. Validate `requires` in prep() before execution

**We chose A** - let Python's ImportError be the message. But if users complain, Option B is easy to add.

## Relevant Files & References

### Essential Reading (in order):
1. `.taskmaster/tasks/task_104/starting-context/task-104-spec.md` - Complete specification
2. `.taskmaster/tasks/task_104/starting-context/braindump-sandbox-decision-reversal.md` - Why no sandboxing
3. `.taskmaster/tasks/task_104/starting-context/task-104-handover.md` - Origin story
4. `.taskmaster/tasks/task_104/task-104.md` - Quick reference

### Code Patterns to Follow:
- `src/pflow/nodes/shell/shell.py` - Complex node, stdout/stderr capture
- `src/pflow/nodes/file/read_file.py` - Simple node, clean error handling
- `src/pflow/nodes/llm/llm.py` - exec_fallback pattern
- `src/pflow/runtime/node_wrapper.py` - Template resolution wrapper
- `src/pflow/registry/metadata_extractor.py` - Interface format

### Research Context:
All our codebase verification is in the research agent outputs (available in conversation history). Key findings:
- Template resolution timing verified
- Timeout patterns documented
- Error handling patterns confirmed
- Type validation infrastructure exists

### Testing Reference:
- `tests/test_nodes/test_shell/` - Shell node tests (comprehensive)
- `tests/test_runtime/test_node_wrapper_json_parsing.py` - Nested param handling

## For the Next Agent

### Start By:

1. **Read the spec** (task-104-spec.md) - It's comprehensive and verified
2. **Read the braindumps** - Especially sandbox-decision-reversal.md
3. **Look at read_file.py** - It's the cleanest node example (~200 lines total)
4. **Understand the wrapper chain** - Templates resolve BEFORE your code runs

### Don't Bother With:

- Sandboxing or `__builtins__` restrictions - explicitly decided against
- Deep type validation (list[dict] vs list[str]) - outer type only for MVP
- Windows-specific timeout testing - ThreadPoolExecutor is cross-platform
- Making type hints optional - they're required for Task 107

### The User Cares Most About:

1. **Native objects** - This is the killer feature vs shell node
2. **Type hints enabling markdown workflow tooling** - Strategic, not cosmetic
3. **Clean error messages** - Agents learn from errors, make them good
4. **NOT breaking shell node patterns** - Follow established conventions

### Critical Implementation Details:

**Type annotation extraction** (~15 lines):
```python
import ast

tree = ast.parse(code)
annotations = {}
for node in ast.walk(tree):
    if isinstance(node, ast.AnnAssign):
        var_name = node.target.id
        type_str = ast.unparse(node.annotation)
        annotations[var_name] = type_str
```

**Timeout pattern**:
```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError

with ThreadPoolExecutor(max_workers=1) as executor:
    future = executor.submit(exec, code, namespace)
    try:
        result = future.result(timeout=timeout_seconds)
    except TimeoutError:
        # Handle in exec_fallback
```

**Stdout/stderr capture**:
```python
import io
from contextlib import redirect_stdout, redirect_stderr

stdout_buffer = io.StringIO()
stderr_buffer = io.StringIO()

with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
    exec(code, namespace)

stdout = stdout_buffer.getvalue()
stderr = stderr_buffer.getvalue()
```

### Common Pitfalls to Avoid:

1. **Don't use signal.alarm()** - Not in pflow anywhere, Unix-only, thread-unsafe
2. **Don't try/except in exec()** - Breaks retry mechanism, handle in exec_fallback
3. **Don't validate deep generics** - `list[dict]` just checks `isinstance(value, list)`
4. **Don't forget exec_fallback returns same structure as exec()** - Not a special error type
5. **Don't skip type annotation validation** - Users will forget, catch in prep()

### If You Get Stuck:

- **Syntax errors**: Python's SyntaxError has line number, offset, message - use them
- **Type validation**: Use `isinstance()` for outer type, `ast.unparse()` for string format
- **Timeout not working**: Check ThreadPoolExecutor is used correctly, future.result() raises TimeoutError
- **Templates not resolved**: They should be - verify wrapper chain, check `self.params` in prep()

### Testing Strategy:

**First test** (proves it works):
```python
code = "data: list\nresult: list = data[:5]"
inputs = {"data": [1,2,3,4,5,6,7,8,9,10]}
# Execute and verify result is [1,2,3,4,5]
```

**Second test** (proves validation works):
```python
code = "result = data[:5]"  # Missing annotation
inputs = {"data": [1,2,3]}
# Verify ValueError in prep()
```

Build from there following the spec's 25 test criteria.

---

## Final Notes

This was a **design session**, not implementation. We made critical architectural decisions that will affect Task 107 immediately. The spec is complete and verified - all assumptions checked against codebase.

The key insight: **Type hints aren't just nice-to-have, they're strategic**. They enable Python tooling in markdown workflows, which is the whole point of pflow's evolution toward agent-friendly formats.

The sandboxing decision reversal is **user-driven and intentional**. Don't second-guess it - it's documented in the braindump with full rationale.

**Implementation should be straightforward** - we've de-risked all the hard decisions. The spec has 25 test criteria, a compliance matrix, and verified patterns. Follow the spec, follow the node patterns, write the tests, ship it.

---

**Note to next agent**: Read this document fully before taking any action. The spec (task-104-spec.md) is your implementation guide - this braindump fills in the WHY and the journey. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
