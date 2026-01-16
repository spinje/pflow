# Braindump: Sandbox Architecture Context from Task 104 Discussion

## Where I Am

This braindump comes from a conversation about Task 104 (Python Code Node). That conversation concluded with a **scope expansion for Task 87**: code node sandboxing is the SAME infrastructure problem as shell node sandboxing, so Task 87 should cover both.

**Key context**:
- Task 104's code node will have **NO sandbox** for MVP (unsandboxed, native objects, fast)
- Task 87 should implement sandbox infrastructure that BOTH shell node AND code node can use
- When sandboxed, code node loses native objects (serialization required) - same tradeoff as shell node

## UPDATE (from follow-up conversation)

User explicitly confirmed: **Task 87 should cover code node sandboxing too.**

The reasoning:
1. Container sandbox for code node = serialize inputs, run Python/TS, serialize outputs
2. Container sandbox for shell node = serialize inputs, run bash, serialize outputs
3. It's the same infrastructure: bubblewrap/sandbox-exec/container around a subprocess
4. Only difference is what command runs inside (`python -c "..."` vs `bash -c "..."`)

**Language choice should be driven by libraries, not sandboxing.** User said: "some libs are available for python and some for ts, it should be easy for user to choose and pick between languages."

## User's Mental Model

The user sees a clear separation:

- **Code node** (Task 104): "trusted fast path" - native objects, in-process, no isolation
- **Shell node** (Task 87): "isolated power mode" - container-level sandbox, serialized I/O

User's exact words:
- "shell node will have its own sandbox later but thats a different topic"
- "if you want your workflow to be sharable and deployable you should probably avoid shell node entirely"

The user sees shell node as the place for:
1. Power users doing local automation (no sandbox needed)
2. Running untrusted/shared workflows (sandbox required)

## Key Insights

### 1. Why Language-Level Sandboxing Doesn't Work

We explored Python sandboxing deeply for Task 104. The conclusion: **language-level sandboxing (restricting `__builtins__`) is fundamentally broken**.

Classic escapes:
```python
().__class__.__bases__[0].__subclasses__()  # Find dangerous classes
some_func.__globals__['__builtins__']       # Functions leak globals
import json; json.__builtins__              # Modules carry full builtins
```

**Implication for Task 87**: Don't try to sandbox shell commands at the language level (e.g., parsing commands and blocking dangerous patterns). That's what Task 63's risk assessment does - it WARNS but can't PREVENT. Real isolation requires process/container boundaries.

### 2. Container Sandbox = Serialization Required

We discussed that container isolation means data must be serialized to pass between pflow and the sandboxed process. This is **already true for shell node** (stdin/stdout are text/JSON), so there's no additional cost.

This is different from code node, where native objects were the core value prop. Shell node doesn't lose anything by being containerized.

### 3. TypeScript/JavaScript Has Better Sandboxing

We established that V8 isolates enable true sandboxing without serialization overhead. This is tangential to Task 87 but strategic context:

- If pflow adds TypeScript script support in future, it could be both sandboxed AND have native objects
- Shell node sandbox (Task 87) is still necessary for shell commands regardless

### 4. The Portable vs Local Mental Model

The user framed it this way:

```
PORTABLE WORKFLOWS (shareable):
- llm node, http node, code node (with declared deps)
- Avoid shell node OR accept it needs sandbox

LOCAL WORKFLOWS (power users):
- Shell node without sandbox is fine
- User trusts their own commands
```

**Implication**: Task 87's sandbox might need to be opt-in for local use, mandatory for certain contexts (e.g., MCP server, shared workflows).

## Assumptions & Uncertainties

**ASSUMPTION**: Shell node sandbox will be container-based (bubblewrap/sandbox-exec/Docker), not language-level. This aligns with `key-insights.md` but wasn't explicitly confirmed in this conversation.

**ASSUMPTION**: The existing research in `task_87/research/` is still valid. This conversation didn't contradict it.

**UNCLEAR**: When should sandbox be mandatory vs optional? User said "shell node will have its own sandbox later" without specifying policy.

**VERIFIED**: User confirmed Task 87 should cover code node sandboxing. Code node will have two modes:
- Unsandboxed (default): Fast, native objects, trusted code
- Sandboxed (opt-in): Container isolation, serialized I/O, untrusted code OK

## Unexplored Territory

**RESOLVED**: Code node sandboxing is now explicitly in scope for Task 87. Both shell and code nodes can use the same infrastructure.

**UNEXPLORED**: How does sandbox interact with code node's `requires` field? If workflow has `requires: ["pandas"]`:
- Unsandboxed mode: pandas must be installed in user's environment
- Sandboxed mode: container needs pandas installed - how? Pre-built images? Install at runtime?

**CONSIDER**: The existing `key-insights.md` says "Docker is WRONG for shell commands" because it isolates too much (need host git, ssh keys, etc.). But for code node, Docker might actually be fine since:
- Code node doesn't need host tools
- Just needs Python/TS interpreter + deps
- Full container isolation is acceptable

This suggests **different sandbox approaches** for different use cases:
- Shell node: bubblewrap/sandbox-exec (partial isolation, keep host tools)
- Code node: Docker/container (full isolation, isolated interpreter)

**UNEXPLORED**: Performance implications. Spinning up container for every script execution might be slow. Options:
- Persistent container session per workflow?
- Pre-warmed container pool?
- Accept overhead for security?

**CONSIDER**: Integration with Task 109 (Sandbox Bypass Security Controls). If Task 87 implements real sandboxing, Task 109 might become "secure defaults and user overrides" rather than technical bypass prevention.

**MIGHT MATTER**: TypeScript has better in-process sandboxing (V8 isolates) than Python. Future TS code node could potentially have BOTH native objects AND sandboxing. Python is stuck with the container tradeoff. This is strategic context, not actionable now.

## What I'd Tell Myself

1. **Task 104's "no sandbox" decision makes Task 87 more important** - it's now the ONLY isolated execution path in pflow.

2. **Don't try to sandbox Python code in code node via Task 87's infrastructure** - the user explicitly separated these concerns. Code node is unsandboxed, shell node gets container isolation.

3. **Container isolation is fine because shell node already serializes** - you're not losing anything by containerizing.

4. **The mental model is "trusted fast path" vs "isolated power mode"** - code node is fast/trusted, shell node can be isolated when needed.

## Open Threads

### Thread 1: Code Node + Container Sandbox? — RESOLVED

**RESOLVED**: User explicitly confirmed code node should have optional sandbox via Task 87's infrastructure.

- Code node default: Unsandboxed, native objects, fast
- Code node with `sandbox: true`: Uses Task 87 container infrastructure, loses native objects
- Same infrastructure as shell node, just runs `python -c` instead of `bash -c`

### Thread 2: When Is Sandbox Mandatory?

User mentioned "if you want your workflow to be sharable and deployable you should probably avoid shell node entirely." This implies sandbox might be:
- Optional for local use (user trusts own code)
- Recommended for shared workflows
- Mandatory for MCP server context (untrusted callers)

Task 87 might need a policy layer, not just implementation.

### Thread 3: Relationship to Task 63 (Risk Assessment)

The existing task-87.md asks: "Evaluate if this deprecates the need for Task 63." Based on this conversation:
- Task 63 (risk assessment) = WARN about dangerous patterns
- Task 87 (sandbox) = PREVENT dangerous execution

They're complementary, not redundant. Risk assessment is useful even with sandbox (tells user WHY something is risky). Sandbox is the enforcement.

## Relevant Files & References

**Already in Task 87 folder:**
- `task-87.md` - Basic task description
- `research/key-insights.md` - Technical approach (bubblewrap, sandbox-exec)
- `research/sandbox-implementation-research.md` - Detailed research

**From this conversation (not in files):**
- Python sandbox escape techniques (documented in Task 104 braindump)
- TypeScript V8 isolate potential (strategic, not actionable now)

**Related tasks:**
- Task 104: Code node (unsandboxed, native objects)
- Task 63: Risk assessment (warning, not enforcement)
- Task 109: Sandbox bypass controls (policy layer?)

## For the Next Agent

**Start by**: Reading `research/key-insights.md` and `research/sandbox-implementation-research.md` - they have the technical approach. This braindump adds CONTEXT and SCOPE EXPANSION.

**Critical scope change**: Task 87 now covers BOTH shell node AND code node sandboxing. The infrastructure is shared.

**The user cares most about**:
1. Real container-level isolation (not language-level sandbox)
2. Code node has two modes: unsandboxed (default, fast) and sandboxed (opt-in, serialized)
3. Language choice (Python vs TS) driven by libs, not sandboxing - both should be sandboxable
4. Portability story: sandboxed execution is the path for shareable/untrusted workflows

**Key nuance**: Sandbox approach may differ by node type:
- **Shell node**: bubblewrap/sandbox-exec (need host tools like git, ssh keys)
- **Code node**: Docker might be fine (just needs interpreter + deps, no host tools)

This is a research question for implementation time. The existing research says "Docker is wrong for shell" but that logic doesn't apply to code node.

**Key insight to remember**: Sandboxing requires serialization. Both shell and code node pay this cost when sandboxed. Code node's native objects only work in unsandboxed mode.

---

**Note to next agent**: Read this document fully before taking any action. This braindump was UPDATED after user clarified that code node sandboxing belongs in Task 87. The existing research files have technical details but predate this scope expansion. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
