# Braindump: TypeScript Code Node - Context from Sandbox Architecture Discussion

## Where I Am

Task 113 was created at the END of a long conversation primarily about Task 104 (Python Code Node) and Task 87 (Sandbox Runtime). The TypeScript task emerged from a key insight: **TypeScript can do something Python fundamentally cannot** - sandboxed execution with native objects via V8 isolates.

This task wasn't the main focus. It was created because the user wanted to capture the strategic insight before the context window reset.

## User's Mental Model

The user thinks about language support in terms of **library ecosystems**, not technical implementation:

> "some libs are available for python and some for ts, it should be easy for user to choose and pick between languages"

**Their priority**: Users pick language based on what libraries they need. Sandboxing shouldn't drive language choice.

**Implied requirement**: Both Python and TypeScript should eventually support sandboxed execution, but via different mechanisms appropriate to each language.

## Key Insights (The Non-Obvious Stuff)

### 1. Why TypeScript Matters for Sandboxing

This was the "aha" moment in the conversation. We established:

- **Python language-level sandboxing is broken** - Object traversal escapes (`().__class__.__bases__[0].__subclasses__()`)
- **Python container sandboxing loses native objects** - Must serialize to pass data across process boundary
- **TypeScript V8 isolates are different** - True memory isolation WITHOUT serialization

```
Python:
  Unsandboxed → Native objects ✅
  Sandboxed (container) → Serialization ❌

TypeScript:
  Unsandboxed → Native objects ✅
  Sandboxed (V8 isolate) → Native objects ✅ (potentially!)
```

This is why TypeScript support isn't just "nice to have" - it's the only path to sandboxed + fast execution.

### 2. Same Node vs Separate Node Decision

We explicitly discussed three options:
- **Option A**: Same node, `language` parameter ← CHOSEN
- **Option B**: Separate `ts-script` node
- **Option C**: Same node, but sandbox behavior differs by language

User didn't explicitly confirm, but the conversation flow suggested Option A. I wrote the task assuming this.

**ASSUMPTION**: User wants unified `script` node with `language` param. Verify if important.

### 3. This Task is Low Priority

The user created this task to capture the insight, not because it's urgent. The priority chain is:
1. Task 104: Python code node (MVP, needed now)
2. Task 87: Sandbox runtime (security)
3. Task 113: TypeScript support (future)

Don't start this before Task 104 is done.

## Assumptions & Uncertainties

**ASSUMPTION**: V8 isolates can pass objects without full JSON serialization. I believe this is true (isolated-vm supports transferring objects), but haven't verified the exact mechanism or limitations.

**ASSUMPTION**: Node.js is an acceptable dependency for TypeScript support. User didn't explicitly confirm, but it's the obvious choice.

**UNCLEAR**: Where does V8 isolate sandbox implementation live?
- Task 87 currently covers container sandboxing for shell/code nodes
- V8 isolates are fundamentally different (in-process, not container)
- Should V8 sandbox be part of Task 113, or expand Task 87?

**UNCLEAR**: How does `requires` work for npm packages?
- Python: User has packages installed locally, `requires` is documentation
- TypeScript: Same approach? Or something more sophisticated?

**NEEDS VERIFICATION**: Embedded V8 options for Python:
- PyMiniRacer - seems maintained
- py_mini_racer - different package?
- Deno as subprocess - has built-in permissions model
- Node.js + isolated-vm - most mature but subprocess = serialization?

## Unexplored Territory

**UNEXPLORED**: Performance characteristics of V8 isolates. We assumed they're fast, but:
- Startup time for creating isolates?
- Memory overhead per isolate?
- Can isolates be reused across workflow nodes?

**UNEXPLORED**: Type safety in TypeScript mode. The code is a string - no compile-time checking. Should we:
- Run tsc for type checking before execution?
- Just run as JavaScript (ignore types)?
- This affects error messages significantly

**CONSIDER**: Deno vs Node.js. Deno has:
- Built-in permission model (no filesystem/network by default)
- TypeScript support out of the box
- Single binary, easier dependency
- But: less mature, smaller ecosystem

The task mentions Deno in "Open Questions" but we didn't discuss it in depth.

**MIGHT MATTER**: Task 107 (Markdown Format) assumes ` ```typescript ` code blocks. If TypeScript support isn't implemented when Task 107 ships, there's a gap. Either:
- Task 107 ignores typescript blocks (error)
- Task 107 waits for Task 113
- Task 107 supports the syntax but execution fails gracefully

**UNEXPLORED**: async/await in TypeScript code. JavaScript is inherently async. How do we handle:
```typescript
const result = await fetch('https://api.example.com')
```
- Block until promise resolves?
- Disallow await?
- This is a bigger design question than Python's synchronous exec()

**CONSIDER**: The `inputs` interface assumes synchronous variable injection. In Python, we do:
```python
exec(code, {'data': data, 'config': config})
```
In JavaScript, this might look like:
```javascript
const fn = new Function('data', 'config', code);
fn(data, config);
```
But `new Function` is basically `eval` - security implications if not in isolate.

## What I'd Tell Myself

1. **This task is about the insight, not immediate action** - The user created it to capture the V8 isolate advantage. Don't rush to implement.

2. **Read Task 104 first** - TypeScript support extends the same node. Understand Python implementation before designing TypeScript.

3. **The sandbox story is the interesting part** - Basic TypeScript execution is straightforward (subprocess to Node). V8 isolate sandbox with native objects is the hard/valuable part.

4. **Deno might be simpler** - We didn't explore this deeply, but Deno's permission model might obviate the need for isolated-vm complexity.

5. **The user cares about ecosystem access** - They want users to be able to use npm packages. Don't design something that makes package usage painful.

## Open Threads

### Thread 1: V8 Isolate Native Objects
I claimed V8 isolates can pass native objects. This needs verification:
- Can isolated-vm transfer objects without serialization?
- What types are supported? (dict/list equivalents, not complex classes)
- Is there a size limit?

### Thread 2: Where Does V8 Sandbox Live?
Task 87 is "Sandboxed Execution Runtime" and now covers code node. But V8 isolates are fundamentally different from containers. Options:
- Expand Task 87 to include V8 isolates
- Keep V8 isolates in Task 113
- New Task 114 for "V8 Isolate Sandbox Infrastructure"

### Thread 3: Embedded V8 vs Subprocess
We never resolved this. Trade-offs:

| Approach | Native Objects | Complexity | Dependencies |
|----------|---------------|------------|--------------|
| PyMiniRacer | Maybe? | Low | pip package |
| Node subprocess | No (serialize) | Low | Node.js |
| Node + isolated-vm | No (serialize) | Medium | Node.js + npm |
| Deno subprocess | No (serialize) | Low | Deno binary |

The "native objects through sandbox" promise might only be achievable with embedded V8. Worth researching.

## Relevant Files & References

**Task files created/updated in this conversation:**
- `.taskmaster/tasks/task_113/task-113.md` - The task spec (just created)
- `.taskmaster/tasks/task_104/starting-context/braindump-sandbox-decision-reversal.md` - Python sandbox decision
- `.taskmaster/tasks/task_87/starting-context/braindump-sandbox-architecture-context.md` - Sandbox architecture context
- `.taskmaster/tasks/task_87/task-87.md` - Updated to include code node scope

**Research links (not verified, just mentioned):**
- isolated-vm: https://github.com/nicolo-ribaudo/isolated-vm
- PyMiniRacer: https://github.com/nicolo-ribaudo/PyMiniRacer
- Deno permissions: https://deno.land/manual/basics/permissions

**Related tasks:**
- Task 104: Python code node (implement first)
- Task 87: Sandbox runtime (V8 isolates might live here)
- Task 107: Markdown format (will have ` ```typescript ` blocks)

## For the Next Agent

**Start by**: Reading Task 104's implementation (when it exists). TypeScript support extends the same node.

**Don't bother with**: Starting implementation before Task 104 is done. This is low priority.

**The user cares most about**:
1. Language choice driven by library needs, not technical constraints
2. Eventually having sandboxed TypeScript with native objects (the unique value prop)
3. Unified interface (same `script` node, `language` parameter)

**Key research needed before implementation**:
1. Can V8 isolates (via PyMiniRacer or similar) actually pass objects without serialization?
2. Is Deno simpler than Node.js + isolated-vm for sandboxed execution?
3. How do we handle async/await in TypeScript code?

**The pitch for TypeScript support**: "Python sandbox requires containers and loses native objects. TypeScript V8 isolates can sandbox while preserving native objects. This is the only path to fast + safe execution."

---

**Note to next agent**: Read this document fully before taking any action. This task was created to capture a strategic insight, not for immediate implementation. Task 104 (Python) must be done first. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
