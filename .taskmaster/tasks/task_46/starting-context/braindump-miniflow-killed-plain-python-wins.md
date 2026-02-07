# Braindump: MiniFlow Exploration Killed, Plain Python Wins for Task 46

## Where I Am

A deep design conversation with the user explored whether MiniFlow (a ~500-line Python framework using t-strings for deferred template resolution) should exist. The conclusion: **it shouldn't**. The gap it tried to fill doesn't exist. This has direct implications for Task 46 — the generated output should be plain Python, not PocketFlow code.

No code was written. This is purely a design/architecture braindump.

## User's Mental Model

### How the conversation evolved

1. User started by asking me to read the MiniFlow spec and braindump with "fresh eyes" — specifically noting the previous model might have missed things
2. I pushed back: "what does MiniFlow give an agent over just writing Python?"
3. User probed: "the problem with pflow was that for wiring the nodes you have to author the nodes, they can't be reusable since you need the wiring to be IN THE NODES. Does this make sense?"
4. I read PocketFlow source and confirmed: yes, `prep()` reads from `shared` with hardcoded keys, `post()` writes to `shared` with hardcoded keys — the wiring IS in the nodes
5. User then asked "so how would this work for non-linear workflows?" — testing whether plain Python handles error routing, branching, loops
6. I showed plain Python handles all of them naturally (try/except, if/else, for/while)
7. User gave me the **killer test**: "how would you make this workflow in pure python?" and pasted a real, complex release-announcements workflow (8 steps, parallel batching, 3 LLM models, MCP calls, code nodes)
8. I wrote it in plain Python. It worked fine. But writing it changed my view — I admitted pflow's declarative format is actually *better* for this kind of workflow (documentation-as-artifact, renderable, editable by non-programmers)
9. User asked the direct question: "so the gap mini-flow tries to fill does not exist?"
10. I said yes. User then connected it to Task 46/91
11. User asked: "I think the thought was to generate 'pure' pocketflow python code. maybe you don't agree with that?"
12. I argued against PocketFlow as the generation target
13. User clinched it: "using pure pocketflow wouldn't even work without adding a shadow store on top to handle the shared store wiring of nodes?"
14. I confirmed — pflow's nodes don't use shared dict directly, they go through the wrapper chain
15. User then asked: "so 'exposing' pflow nodes as functions would be a part of this task?"
16. I said yes — it's the intermediate architecture that makes Task 46 clean

### What the user cares about

- **Intellectual honesty** — they wanted me to challenge the MiniFlow spec, not rubber-stamp it
- **Architectural clarity** — they want to understand WHY an approach is right, not just WHAT to build
- **Practical simplicity** — they repeatedly tested ideas against concrete examples
- **Not building unnecessary things** — they explicitly asked "so the gap doesn't exist?" and accepted the answer

### User's decision pattern

They ask probing questions, test your reasoning against concrete examples, and decide quickly once convinced. They're comfortable killing ideas (including their own) when the reasoning is clear.

## Key Insights

### 1. The MiniFlow gap doesn't exist

The spec identified three audiences:
- **Structured workflows** -> pflow's declarative format is better (docs-as-artifact, validation, metadata)
- **Need Python control flow** -> plain Python is better (no framework to learn)
- **Need both** -> pflow already has `code` nodes

MiniFlow sat in a middle ground that sounds logical ("explicit data flow + native Python") but neither side actually needs it.

### 2. PocketFlow's shared dict problem is real but scoped

PocketFlow's `prep(shared)` / `post(shared, ...)` pattern means nodes hardcode which keys they read/write. This prevents reuse across different workflows. **But this only matters for pre-built nodes.** When an agent generates all the code (which is the Task 46 scenario), it controls all the keys — no collision, no reuse concern. PocketFlow's weakness is irrelevant for generated code.

### 3. PocketFlow code generation is a dead end

**Critical insight the user surfaced**: pflow's actual node implementations (in `src/pflow/nodes/`) don't use `shared` directly. They expect resolved inputs via the wrapper chain:
- `TemplateAwareNodeWrapper` resolves `${node.key}` templates
- `NamespacedNodeWrapper` routes outputs to `shared[node_id][key]`

So you CAN'T generate "pure PocketFlow" using pflow's existing nodes without also generating the wrapper infrastructure. You'd essentially be bundling most of pflow's runtime, defeating the "zero dependency" goal. The user called this "adding a shadow store on top."

### 4. "Nodes as functions" is the right intermediate architecture for Task 46

The clean approach:
1. Extract node logic into pure functions: `http(url, method, retries, timeout) -> dict`
2. pflow's runtime wraps those functions in PocketFlow Node classes + wrappers (for the declarative engine)
3. Task 46 export generates code that calls those functions directly
4. For zero-dependency output, inline the function bodies
5. As a side effect, anyone with pflow installed can `from pflow.nodes import http, llm, shell`

This is NOT a separate task from Task 46 — it's the refactoring step that makes the export clean.

### 5. For non-linear workflows, plain Python beats action strings

I went looking for cases where PocketFlow's action-based routing (`post()` returns "error" -> routes to handler node) is clearly better than Python's native control flow. I didn't find any:
- Error routing: try/except is more natural and more flexible
- Conditional branching: if/else is universally understood
- Retry loops: for/while with break is more readable
- State machines: while loops with match/case

For the target user (agent writing Python), Python's control flow is always more natural than action strings.

### 6. pflow's declarative format is genuinely better for structured workflows

Writing the release-announcements workflow in plain Python changed my view. The Python version works, but the pflow markdown version:
- IS the documentation (renders on GitHub)
- Is editable by non-programmers (swap a model, tweak a prompt)
- Has structured metadata (execution count, timestamps)
- Is validatable before execution
- Has typed inputs with defaults

For workflows without complex branching (which is most of them), the declarative format adds real value that Python can't match.

## Assumptions & Uncertainties

ASSUMPTION: Task 46's "zero dependency" goal means the generated code should not require pflow or PocketFlow to run. This wasn't explicitly re-confirmed, but the user agreed with the direction.

ASSUMPTION: "Nodes as functions" refactoring can be done without breaking pflow's existing runtime. The current node implementations would need to be restructured: extract the core logic into a function, then have the Node class call that function. I haven't verified how much refactoring this requires.

UNCLEAR: Whether Task 46 should support both "light export" (imports pflow functions) and "full export" (inlines everything). The user didn't specify. Both seem useful.

UNCLEAR: The exact scope of Task 46 — the task spec says it depends on a "workflow-to-code compilation infrastructure" which doesn't exist yet. The architecture conversation we had establishes the approach but not the implementation details.

NEEDS VERIFICATION: How pflow's current node implementations are structured internally. I read the wrappers (`namespaced_wrapper.py`, `template_resolver.py`) but didn't read the actual node implementations (e.g., `src/pflow/nodes/http/`, `src/pflow/nodes/llm/`). The refactoring plan assumes the core logic can be cleanly extracted into functions.

## Unexplored Territory

UNEXPLORED: How batch processing would work in generated plain Python. The release-announcements example uses `ThreadPoolExecutor`, which is clean for simple cases. But pflow's batch system has `on_error="continue"`, result collection, and per-item retry. Generating equivalent Python code for complex batch configurations could be non-trivial.

UNEXPLORED: How MCP tool calls would work in generated code. The release-announcements workflow calls `mcp-composio-slack-SLACK_SEND_MESSAGE` and `mcp-discord-execute_action`. In generated code, these need to become actual MCP client calls. That requires an MCP client library dependency — potentially conflicting with "zero dependency."

CONSIDER: Whether the generated code should have any error handling at all. Plain Python with no try/except will give a traceback on failure. Is that sufficient? Or should the generator add structured error handling? This is a UX decision for Task 46.

CONSIDER: The relationship between Task 46 and Task 91 (MCP server export). Task 91 wraps the generated code in a FastMCP server. If the generated code is plain Python functions, this wrapping is trivial. If it's PocketFlow code, it's complicated. Our conclusion (generate plain Python) makes Task 91 simpler.

MIGHT MATTER: Template resolution complexity. pflow templates support nested paths (`${node.response.items[0].name}`), JSON auto-parsing, type preservation, and more (see `template_resolver.py`). Generated plain Python needs to handle all of this inline. For simple templates it's trivial (just variable access), but for complex nested paths with JSON parsing, the generated code could get ugly.

MIGHT MATTER: The `llm` library (Simon Willison's) that pflow uses. If generated code needs to make LLM calls, it either depends on this library or generates its own API calls. Using the library is simpler but adds a dependency.

UNEXPLORED: Whether the MiniFlow spec (`scratchpads/miniflow/miniflow-spec.md`) and braindump should be archived/annotated as "explored and rejected" so future agents don't re-explore the same path. The files still exist and could mislead.

## What I'd Tell Myself

1. **Don't re-explore MiniFlow.** We killed it with rigorous testing against a real workflow. The gap doesn't exist. If you find yourself designing a framework between PocketFlow and pflow, stop.

2. **The release-announcements workflow is the benchmark.** It's a real, complex workflow the user actually uses. Any proposed architecture for Task 46 should be tested against it: "can I generate clean Python for this?"

3. **"Nodes as functions" is the key refactoring.** Before writing the code generator, refactor pflow's node implementations to separate pure logic from PocketFlow class structure. This makes everything else clean.

4. **Don't generate PocketFlow code.** We established this conclusively. PocketFlow's abstractions help humans organizing code, not code generators producing output. And pflow's nodes can't work without the wrapper chain anyway.

5. **The user values intellectual honesty.** They brought me in specifically because the previous model might have had blind spots. They want you to challenge assumptions, not agree. Push back when something doesn't make sense.

## Open Threads

### MiniFlow spec files still exist

`scratchpads/miniflow/miniflow-spec.md` and `scratchpads/miniflow/miniflow-design-session-braindump.md` are still in the repo. A future agent might read them and think MiniFlow is an active project. Consider annotating them with a note that the approach was explored and rejected, or the user might want to archive them.

### Node refactoring scope unknown

The plan to extract node logic into pure functions requires understanding how each node is currently implemented. I didn't read the actual node source files. Start there before designing the refactoring.

### Task 46 task spec may need updating

The current Task 46 spec may reference PocketFlow code generation or other approaches that we've now rejected. The user may want to update it with the "generate plain Python" direction.

### Task 91 benefits from this decision

Task 91 (MCP server export) becomes much simpler when the generated code is plain Python functions. A FastMCP `@mcp.tool()` decorator around a plain Python function is trivial. Around PocketFlow code with shared dicts, it would be a nightmare.

## Relevant Files & References

### MiniFlow docs (explored and rejected)
- `scratchpads/miniflow/miniflow-spec.md` — comprehensive spec, well-written but the approach was killed
- `scratchpads/miniflow/miniflow-design-session-braindump.md` — previous session's braindump

### PocketFlow (understand the data flow problem)
- `src/pflow/pocketflow/__init__.py` — the 200-line framework. Key lines: 32-35 (`_run` with shared dict), 98-108 (flow orchestration)
- The shared dict is the ONLY communication channel between nodes

### pflow's wrapper chain (why PocketFlow codegen won't work)
- `src/pflow/runtime/namespaced_wrapper.py` — routes outputs to `shared[node_id][key]`
- `src/pflow/runtime/template_resolver.py` — resolves `${node.key}` templates (~580 lines of complexity)
- `src/pflow/runtime/node_wrapper.py` — template-aware wrapper (~680 lines)
- These exist because raw PocketFlow can't do reusable nodes

### Task specs
- `.taskmaster/tasks/task_46/task-46.md` — current Task 46 spec (may need updating)
- `.taskmaster/tasks/task_91/task-91.md` — Task 91 depends on Task 46

### The release-announcements workflow (benchmark for testing)
- The user pasted it in the conversation. It's a real workflow with: 8 steps, parallel batch LLM calls across 3 platforms, 3 different models (gemini/gpt/claude), MCP calls (Slack, Discord), code nodes, file operations, template wiring throughout. Any code generation approach should be tested against this.

## For the Next Agent

**Start by**: Reading this document, then the current Task 46 spec (`.taskmaster/tasks/task_46/task-46.md`), then the MiniFlow spec (`scratchpads/miniflow/miniflow-spec.md`) for context on what was explored and rejected.

**Don't bother with**: Designing a framework or library between PocketFlow and pflow. We explored this thoroughly and concluded the gap doesn't exist. Don't revisit MiniFlow, t-strings, Ref objects, or Flow classes.

**The user cares most about**: Architectural honesty. They want the simplest approach that actually works, tested against real workflows. They kill ideas that don't survive contact with concrete examples.

**The key architectural decision**: Task 46 should generate plain Python, not PocketFlow code. The intermediate step is refactoring pflow's node implementations to extract pure functions. This enables both the export (inline or import) and a "nodes as functions" capability as a side effect.

**Verify before proceeding**: Read the actual node implementations in `src/pflow/nodes/` to understand the refactoring scope. The plan assumes core logic can be cleanly separated from PocketFlow class structure. This needs confirmation.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
