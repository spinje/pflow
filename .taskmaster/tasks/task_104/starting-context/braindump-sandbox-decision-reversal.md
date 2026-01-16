# Braindump: Sandbox Decision Reversal for Task 104

## Where I Am

This conversation **reversed a key design decision** from the previous handover. The existing `task-104-handover.md` says "Sandboxed globals - Restrict `__builtins__` for security". This conversation concluded: **drop sandboxing entirely for MVP**.

This is the critical delta. Everything else in the existing docs is still valid.

## User's Mental Model

The user thinks about this in terms of **pragmatic tradeoffs**, not idealized security:

- "shell node will have its own sandbox later but thats a different topic"
- "we want to allow as much as possible from a python node, use pandas, use a lib for getting youtube transcripts, it should be possible"
- "we need a way for users to do anything while we work on the best possible solution"

**Their framing**: Code node is a bridge solution. Users need to get real work done NOW. The "right" architecture (lightweight nodes, guided creation) isn't figured out yet. Don't let perfect be the enemy of good.

**Key phrase the user used**: "Does this make sense?" - they were checking if I understood the pragmatic constraints, not asking for permission.

## Key Insights (The Non-Obvious Stuff)

### 1. Python Language-Level Sandboxing is Fundamentally Broken

This came up when user asked "can you explain why... bypassable". I explained the classic escapes:

```python
().__class__.__bases__[0].__subclasses__()  # Traverses to ALL classes
some_func.__globals__['__builtins__']        # Functions leak their globals
import json; json.__builtins__               # Modules carry unrestricted builtins
```

**The insight**: Python's object model is deeply interconnected. From ANY object, you can traverse to dangerous capabilities. This isn't theoretical - it's why pysandbox was abandoned, why Jinja2's sandbox has had CVEs, why no production system trusts `exec()` with restricted builtins.

**User's reaction**: This was new information to them. They asked clarifying questions, which led to...

### 2. TypeScript/JavaScript Has Real Sandboxing (V8 Isolates)

User asked: "would this still be a problem in typescript?"

Answer: **No**. V8 isolates are designed for untrusted code (browsers run JS from millions of websites). The key differences:
- No object traversal to dangerous capabilities (prototype chain doesn't lead to `fs`, `child_process`)
- True memory isolation between isolates
- Capabilities are injected explicitly, not discovered

**User's takeaway**: TypeScript might be the better path for "safe but powerful" execution in the future. This wasn't in scope for Task 104 but it's strategic context.

### 3. Container Sandboxing Brings Back Serialization

User asked: "cant you have sandboxing that allows for anything but everything runs in isolation, like a container?"

Yes, but containers are separate processes. To pass data in, you serialize. This negates the core value of code node (native objects, no JSON roundtrip).

**The tradeoff matrix**:
- In-process exec(): Native objects YES, Sandbox NO
- Container: Sandbox YES, Native objects NO (serialization required)

### 4. Shell Node Already Allows Script References

I initially suggested shell node shouldn't have explicit `script_path` parameter. User pointed out: "currently we allow referencing scripts in shell node, is that... okay?"

It's already the case - `command: "python myscript.py"` works. This is fine because:
- Shell node is "power mode" for local automation
- If you want portable/shareable workflows, avoid shell node
- Task 87 will add proper container sandboxing to shell node

### 5. The `requires` Field Serves Multiple Purposes

Not just documentation. The user sees it as:
- Self-describing workflows (what dependencies?)
- Future validation (can we even run this?)
- Future auto-install / containerization
- NOT enforcement for MVP - just declaration

## Assumptions & Uncertainties

**ASSUMPTION**: User is okay with code node being "trusted code only" for MVP. They said "we need a way for users to do anything" - I interpreted this as accepting the security tradeoff.

**ASSUMPTION**: The `requires` field is optional, not required. User said "the workflow should probably need to declare these" with "probably" suggesting flexibility.

**UNCLEAR**: Exact format of `requires` field. I proposed `"requires": ["pandas", "youtube-transcript-api"]` but didn't confirm syntax.

**UNCLEAR**: What happens when `requires` deps aren't installed? Error? Warning? Just documentation?

**NEEDS VERIFICATION**: User mentioned "in the future we want to have a way for pflow to guide agents to create lightweight nodes" - this is vague. Don't try to solve it in Task 104.

## Unexplored Territory

**UNEXPLORED**: Error message UX when user tries to import something not installed. Should code node catch `ImportError` and give helpful message like "Module 'pandas' not found. Add to workflow requires: ['pandas'] and install with pip install pandas"?

**UNEXPLORED**: How does `requires` interact with Task 107 markdown format? Probably in frontmatter:
```yaml
---
requires: [pandas, numpy]
---
```
But we didn't discuss this.

**CONSIDER**: Timeout for script execution. The old handover mentions 30s default. Still relevant? User didn't discuss in this conversation.

**CONSIDER**: stdout capture from `print()` statements. Task spec mentions it but we didn't revisit. Is it still wanted?

**MIGHT MATTER**: What if user code has a syntax error? The error message needs to show line numbers relative to THEIR code, not the exec() wrapper. This is mentioned in the old handover but is a real implementation detail.

**MIGHT MATTER**: Code that modifies the `inputs` dict. Should we pass a copy? Or trust user not to mutate?

**UNEXPLORED**: Integration with batch processing. If code node is used in a batch context, does each iteration get fresh locals? Probably yes but worth considering.

## What I'd Tell Myself

1. **Read the existing handover first** (`task-104-handover.md`) - it has valuable technical context about template resolution timing, type inference, etc. That's still valid.

2. **But ignore the sandboxing section** - this conversation explicitly reversed that decision. No restricted builtins, no blocked imports.

3. **The user's priority is "users can do real work"** - pandas, youtube transcripts, arbitrary libs. Don't be clever about restricting things.

4. **Shell node is the comparison point** - user kept referencing what shell node can/can't do. Code node's value is: native objects + readable code + good errors. Not security.

5. **`requires` is future-proofing, not enforcement** - implement it as a simple array field in the IR, validate it exists in schema, but don't try to do anything clever with it yet.

## Open Threads

### Thread 1: TypeScript Future
We established JS/TS has better sandboxing potential (V8 isolates). This could inform a future task. User seemed interested but didn't pursue. Don't implement anything, just note it for strategic planning.

### Thread 0: Sandboxed Script Execution — RESOLVED (Task 87)
User confirmed: sandboxed script execution belongs in **Task 87**, not Task 104.

When Task 87 is implemented, code node will have optional `sandbox: true` that:
- Runs in container (bubblewrap/Docker)
- Loses native objects (back to serialization)
- Same infrastructure as shell node sandbox

Task 104 should implement ONLY the unsandboxed mode. Sandboxed mode is Task 87's problem.

### Thread 2: Lightweight Node Creation
User explicitly mentioned wanting to "guide agents to create lightweight nodes" without MCP overhead. This is NOT Task 104's problem. But code node might be a stepping stone - common patterns in code nodes could later be extracted to reusable nodes. Keep implementation simple so this future is possible.

### Thread 3: Task 109 (Sandbox Bypass Security Controls)
I flagged this might need scope clarification. If Python sandbox is abandoned, what is Task 109 about? Container escapes for shell node (Task 87)? Something else?

## Relevant Files & References

**Already documented in existing handover** (don't re-read, just reference):
- `src/pflow/nodes/shell/shell.py` - pattern for complex node
- `src/pflow/nodes/llm/llm.py` - pattern for simpler node
- `src/pflow/runtime/template_resolver.py` - how templates work
- `pocketflow/__init__.py` - base Node class

**This conversation didn't touch code** - it was all design discussion.

**Related tasks to understand context**:
- Task 87: Shell node sandbox (container-level, different approach)
- Task 107: Markdown format (will use `requires` in frontmatter, ` ```python ` blocks for code)
- Task 109: Sandbox bypass controls (needs scope clarification)

## For the Next Agent

**Start by**: Reading `task-104-handover.md` for technical context, then this document for the decision reversal.

**Don't bother with**: Implementing sandboxing, restricted builtins, or blocked imports. That's explicitly abandoned.

**The user cares most about**:
1. Native objects as inputs (the core value)
2. Clean error messages (agents need to learn from failures)
3. `requires` field for dependency declaration
4. Allowing all imports (pandas, youtube libs, whatever)

**Key implementation decision**: No sandbox means simpler code. Just `exec(user_code, {'__builtins__': __builtins__, **inputs})`. Focus effort on error handling and the `requires` field instead.

**Update the task spec**: The task-104.md still mentions sandboxing. It should be updated to reflect:
- No restricted builtins
- All imports allowed
- Add `requires` field to params schema
- Remove sandbox-related test cases, add import-related ones

---

**Note to next agent**: Read this document fully before taking any action. The existing `task-104-handover.md` has good technical context but **wrong security decisions**. This braindump captures a significant design reversal. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
