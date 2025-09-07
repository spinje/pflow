# Task 42 Handoff: Claude Code Agentic Node

**TO THE IMPLEMENTING AGENT**: Read this entire document before starting implementation. At the end, confirm you're ready to begin.

## 🔴 Critical SDK Reality Check

The biggest discovery: **We're using the Python SDK, NOT CLI subprocess**. I started researching CLI integration, but found `claude-code-sdk` Python package exists and is superior. The user explicitly approved this change.

### What the SDK Actually Has vs What You Might Assume

```python
# ✅ CORRECT - These exist:
ClaudeCodeOptions(
    max_thinking_tokens=8000,  # NOT max_tokens!
    allowed_tools=["Read", "Write", "Edit", "Bash"],
    system_prompt="...",
    permission_mode="acceptEdits"
)

# ❌ WRONG - These DON'T exist:
ClaudeCodeOptions(
    temperature=0.5,  # NO! Doesn't exist
    max_tokens=1000,  # NO! It's max_thinking_tokens
    timeout=300       # NO! Handle at asyncio level
)
```

I wasted time assuming temperature existed. Don't make the same mistake.

## 🎯 The Schema-as-System-Prompt Innovation

The user specifically requested dynamic schema support but in a clever way: **merge the schema with the system prompt**. This was their exact quote: "use schema input and merge it with a system_prompt for claude code. this will work great I think"

Here's what this means:
1. User provides `output_schema` like `{"root_cause": "str", "fix_applied": "str"}`
2. We convert this to prompt instructions: "You must structure your final response as valid JSON with these exact keys..."
3. Claude follows these instructions (usually) and outputs JSON
4. We parse it and populate shared store with schema keys
5. If parsing fails, fallback to `shared["result"]` with raw text

This turns an unstructured text API into a structured data API through prompt engineering. It's the core innovation of this node.

## ⚠️ The Async Trap

The SDK is **async-only**. You MUST wrap it exactly like the MCP node does:

```python
def exec(self, prep_res):
    # NO try/except here! Let exceptions bubble up for retry!
    result = asyncio.run(self._exec_async(prep_res), debug=False)
    return "success"

async def _exec_async(self, prep_res):
    # Actual async implementation
    # Use timeout at asyncio level, not SDK level
```

I found this pattern by researching `src/pflow/nodes/mcp/`. Follow it exactly. The `debug=False` is important. The lack of try/except is intentional.

## 🔍 Hard-Won JSON Extraction

Claude won't always output clean JSON. You need THREE extraction strategies:
1. JSON in markdown code blocks (most common)
2. Raw JSON objects in text
3. Last resort - find `{` and match closing `}`

See `implementation-insights.md` for the exact regex patterns. I tested these against various Claude response formats.

## 🚨 Authentication is Subprocess + SDK

The SDK doesn't have an auth check method. You must:
1. Run `subprocess.run(["claude", "--version"])` to check CLI installed
2. Run `subprocess.run(["claude", "doctor"])` to check authentication
3. ALSO catch SDK auth errors as backup

This dual approach ensures we catch all auth failures with helpful messages.

## 💰 Conservative Retry Strategy

Each Claude Code call costs money and takes time (2-3 second CLI startup + API time). Use:
```python
super().__init__(max_retries=2, wait=1.0)  # Only 2 total attempts
```

Not 3 like other nodes. The user is paying for each retry.

## 🔧 File References

Critical files to study:
- `src/pflow/nodes/mcp/mcp_node.py` - The async pattern we're copying (lines 178-243)
- `architecture/core-node-packages/claude-nodes.md` - Original vision (outdated but shows intent)
- `.taskmaster/tasks/task_42/starting-context/task-42-spec.md` - The verified spec
- `.taskmaster/tasks/task_42/starting-context/implementation-insights.md` - Code snippets and patterns

## 🤔 Unresolved Questions

These remain uncertain but have mitigations:
- Will `claude doctor` actually return non-zero on auth failure? (Also catch SDK errors)
- Are tool names correct? (Conservative list: Read, Write, Edit, Bash)
- Will Claude follow JSON instructions? (Fallback to raw text)
- Is 300 seconds enough? (User can adjust if needed)

## 🎬 User's Vision

The user was excited about this approach. They specifically:
- Wanted dynamic schema (not fixed outputs)
- Approved Python SDK over CLI
- Suggested the schema-as-prompt merge approach
- Said "this will work great I think"

They see this as a "super node" that breaks the simple node philosophy intentionally because it provides comprehensive development capabilities.

## 🔮 Future SDK Changes

The SDK will likely evolve. Our approach (schema-as-prompt) is a clever workaround for missing structured output support. When the SDK adds native JSON mode, we can simplify. But for now, this approach works.

## 🏃 Performance Expectations

- CLI startup: 2-3 seconds overhead
- API response: Varies wildly (5-60 seconds)
- Total timeout: 300 seconds
- Response size: Can be several MB
- Memory: Budget 1GB for response processing

## 🐛 Subtle Gotchas I Hit

1. **Parameter name confusion**: Spent time debugging "max_tokens" before realizing it's "max_thinking_tokens"
2. **Missing temperature**: Assumed it existed, had to remove from spec
3. **Tool uncertainty**: Only Read/Write/Edit/Bash confirmed, others might exist
4. **Async wrapper**: First tried simple approach, had to copy MCP's timeout handling
5. **JSON parsing**: First attempt with single regex failed on real Claude output

## 🎯 Success Criteria

You'll know you've succeeded when:
1. Node executes Claude Code tasks via SDK
2. Schema provided → JSON parsed → keys in shared store
3. Schema missing → full text in shared["result"]
4. Parse fails → fallback preserves data
5. All test criteria from spec pass
6. Timeout, auth, and errors handled gracefully

## 🔗 Context You're Missing

I did extensive research with parallel subagents to understand:
- How pflow nodes work (studied Shell, Git, GitHub, LLM, MCP nodes)
- Claude Code SDK internals (from GitHub repo)
- Testing patterns (mocking async, subprocess)
- Security patterns (dangerous commands, tool whitelisting)

The journey from "use CLI subprocess" to "use SDK with schema-as-prompt" was based on discovering the SDK exists and realizing structured output needs clever prompt engineering.

---

**IMPORTANT**: Do not begin implementation until you've read:
1. This handoff document
2. `task-42-spec.md` (the verified specification)
3. `implementation-insights.md` (code patterns and examples)

Once you've absorbed all three documents, confirm you're ready to implement Task 42.