# Task 71 Handover: The Critical Context You Can't Get From Specs

*From: The agent who validated Task 70 and designed Task 71*
*To: The agent implementing Task 71*

**IMPORTANT**: Read this entire document before starting implementation. At the end, confirm you're ready to begin.

---

## The Philosophical Shift You Must Internalize

The user had a profound realization during our conversation:

> "The chaotic nature of self healing (error and repair) is actually a big part of why we are using an agent in the first place for 'running' pflow."

This changed EVERYTHING. We're not hiding repair from agents - we're exposing it so they can orchestrate it with their superior context. The agent knows WHY the workflow is being built, WHAT the user wants, and HOW to fix issues conversationally.

**This means**:
- `execute()` returns errors with checkpoints, NOT auto-repairs
- The agent fixes workflows by editing JSON files
- The chaos becomes visible and orchestratable

## The Journey From 14 Tools to 5 (And Why It Matters)

I started by identifying 14 potential MCP tools. The user stopped me cold:

> "Couldn't we make it even more simple?"

Then came the key insight: The agent already knows how to create and edit JSON files. Why are we rebuilding these capabilities as MCP tools?

**The revelation**: We only need 5 tools because agents use their native file editing for everything else.

The 5 tools are:
1. `browse_components` - What building blocks exist?
2. `list_library` - What workflows are already built?
3. `describe_workflow` - What does this workflow need?
4. `execute` - Run it (returns errors for agent to fix)
5. `save_to_library` - Keep the working one

Everything else (creating workflows, fixing errors, modifying) happens through file operations.

## The Stateless Pattern - This Is NON-NEGOTIABLE

During research, I discovered pflow creates fresh instances for EVERY operation:

```python
# From execution/workflow_execution.py line 106
registry = Registry()  # Fresh instance

# From line 248
workflow_manager = WorkflowManager()  # Fresh if not provided
```

**YOU MUST FOLLOW THIS PATTERN**. Every MCP request gets fresh instances. No caching. No shared state.

Why? Because:
- Registry can change (MCP sync, settings updates)
- Workflows can be modified outside MCP
- Thread safety is guaranteed by isolation
- It matches pflow's existing pattern

If you're tempted to cache for performance, DON'T. The 10-50ms overhead is nothing compared to the bugs you'll introduce.

## The ComponentBrowsingNode Trap

You'll see ComponentBrowsingNode in `src/pflow/planning/nodes.py` and think "perfect, I'll use this for browse_components!"

**DON'T.**

ComponentBrowsingNode:
- Requires an LLM to filter components
- Returns markdown strings, not structured data
- Is tightly coupled to the planner's workflow
- Returns only IDs, not full metadata

Instead, use Registry directly:
```python
registry = Registry()
nodes = registry.load()  # This has FULL interface metadata already!
```

The interface data is already parsed and stored in the registry at scan time. You don't need to extract it.

## The Hidden Gold in execute_workflow()

Task 68 already solved the hard part. The execute_workflow API is PERFECT as-is:

```python
result = execute_workflow(
    workflow_ir=workflow_dict,      # Takes dict directly!
    execution_params=params,        # MCP params map perfectly!
    enable_repair=False,           # This disables internal repair
    output=NullOutput()           # Silent execution
)
```

The result contains everything you need:
- `success`: Did it work?
- `output_data`: The actual outputs
- `errors`: Structured error list
- `shared_after["__execution__"]`: THE CHECKPOINT DATA!

That checkpoint has:
- `completed_nodes`: What already ran successfully
- `failed_node`: Where it broke
- `node_hashes`: MD5s for cache invalidation

When the agent fixes the workflow and re-executes, the checkpoint ensures only broken nodes re-run. This happens AUTOMATICALLY through the caching system.

## The Security Layers You Can't Skip

Path traversal isn't just about "../" - there are subtle attacks:

1. **Absolute paths**: "/etc/passwd"
2. **Home expansion**: "~/../../etc/passwd"
3. **Null bytes**: "workflow\x00.json"
4. **Unicode tricks**: Different encodings of "/"

You need MULTIPLE validation layers:
- Validate at MCP tool entry
- Validate in WorkflowManager
- Use Path.resolve() to check final location
- Never trust workflow names from agents

Also, REDACT sensitive params in logs:
```python
SENSITIVE = {'password', 'token', 'api_key', 'secret'}
```

## The asyncio.to_thread() Bridge

MCP is async. pflow is sync. The bridge is `asyncio.to_thread()`:

```python
async def tool_handler():
    result = await asyncio.to_thread(sync_function, args)
```

**Why this and not asyncio.run()?** Because MCPNode uses asyncio.run() which creates a NEW event loop each time. That's fine for one-off MCP calls, but the MCP SERVER already has an event loop running. Use to_thread() to run sync code in the thread pool.

## The File System Reality

Both CLI and MCP share `~/.pflow/workflows/`. This is intentional.

The workflow is:
1. Agent creates `~/.pflow/workflows/my-workflow-draft.json` using file editing
2. Agent calls `execute("my-workflow-draft")`
3. If it fails, agent edits the file
4. Agent calls `execute("my-workflow-draft")` again - checkpoint resumes!
5. Once working, agent calls `save_to_library("my-workflow-draft", "my-workflow", "description")`

The draft and library are in the SAME folder. Use naming conventions or a drafts/ subdirectory.

## The WorkflowManager Gaps

WorkflowManager is 90% ready but needs exactly 4 additions:

1. `search(query)` - Filter workflows
2. `for_drafts()` - Class method for draft directory
3. `get_workflow_interface()` - Extract inputs/outputs
4. Duration tracking in execution

That's it. Everything else already works. Don't over-engineer.

## The Template Variable Discovery

Task 21 already added `inputs` and `outputs` to the IR schema. They're right there in the workflow:

```python
workflow["ir"]["inputs"]   # Declared inputs
workflow["ir"]["outputs"]  # Declared outputs
```

But ALSO check for template variables in the workflow using TemplateValidator - these might not be declared.

## The Performance Numbers That Matter

From actual measurements:
- Registry.load(): 10-50ms (cached in memory after first)
- execute_workflow: 100-500ms without LLM
- asyncio.to_thread overhead: 1-5ms

Don't optimize prematurely. The bottleneck is workflow execution, not MCP overhead.

## The Testing Priority

Test these in ORDER:

1. **Stateless verification** - Multiple concurrent requests get isolated instances
2. **Path traversal** - All attack vectors blocked
3. **Checkpoint resume** - Second execution skips completed nodes
4. **Error structure** - Agents can parse error responses
5. **Claude Code discovery** - Tools found without prompting

If #1 fails, nothing else matters.

## The Patterns From MCPNode to Mirror

Look at `src/pflow/nodes/mcp/node.py`. It shows:
- How to bridge async/sync
- How to handle MCP responses
- How to unwrap nested JSON
- Error categorization patterns

Mirror these patterns but reverse them (we're the server, not client).

## What Task 68 Already Did For You

Task 68 extracted:
- WorkflowExecutorService (clean execution API)
- RepairService (you DON'T use this - agents do repair)
- DisplayManager (you use NullOutput instead)
- Checkpoint system (already in shared_after)

You're not building new systems. You're wrapping existing ones.

## The Gotchas That Wasted My Time

1. **MCP nodes return "default" on error** - This hides failures. They should return "error".
2. **Template resolution can return unchanged** - If a template can't resolve, it returns the original string unchanged. Check for this.
3. **WorkflowManager.load() vs load_ir()** - load() returns metadata wrapper, load_ir() returns just the IR. You usually want load_ir() for execution.
4. **Registry filtering** - Registry.load() respects settings.json filtering. Use load(include_filtered=True) if you need all nodes.

## The Critical Decision Log

Why these decisions were made:

1. **5 tools not 14**: Cognitive load on agents + file editing handles the rest
2. **Stateless not cached**: Correctness over 50ms performance
3. **No internal repair**: Agents have better context for fixing
4. **stdio not HTTP**: Faster integration, Claude Code uses stdio
5. **NullOutput not MCPOutput**: Simpler, no need for progress events yet

## The User's Emphasis Points

During our conversation, the user emphasized:
- "Think hard" - Always dig deeper than surface level
- "Even more simple" - Radical simplicity over feature completeness
- "Agent orchestrates repair" - This is the key philosophical shift
- File editing by agents - Don't rebuild what agents already do well

## Final Critical Warnings

1. **DO NOT** add caching "for performance" - it will break isolation
2. **DO NOT** use ComponentBrowsingNode - wrong abstraction
3. **DO NOT** enable internal repair - agents orchestrate repair
4. **DO NOT** trust workflow names - validate everything
5. **DO NOT** share instances between requests - stateless only

## Your Starting Point

Begin with `browse_components`. It's stateless, read-only, and proves the pattern. Once that works with Claude Code, the rest follows the same pattern.

The comprehensive research document has all the code snippets ready to copy. The spec has the full requirements. This handover fills the gaps with the "why" and the "watch out."

---

**Remember**: This isn't about building complex new systems. It's about exposing existing pflow capabilities through thin MCP wrappers so agents can orchestrate workflow building conversationally.

The magic is in the simplicity.

---

**IMPORTANT**: Before you begin implementation, respond with: "I've read and understood the Task 71 handover. I'm ready to begin implementation with the critical context about stateless design, agent-orchestrated repair, and the 5-tool simplicity."