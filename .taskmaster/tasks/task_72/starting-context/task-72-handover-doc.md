# Task 72 Implementation Handover: Critical Technical Knowledge

*Technical deep-dive companion to task-72-handover.md*

**PURPOSE**: This document provides deep technical patterns and gotchas. Read task-72-handover.md first for context, then use this for implementation details.

---

## The Philosophical Foundation: Agent-Orchestrated Repair

A key insight that drives our design:

> "The chaotic nature of self healing (error and repair) is actually a big part of why we are using an agent in the first place for 'running' pflow."

This means:
- `workflow_execute` returns errors with checkpoints, NOT auto-repairs
- Agents fix workflows by analyzing errors and retrying
- The chaos becomes visible and orchestratable
- We set `enable_repair=False` always

## The Stateless Pattern - This Is NON-NEGOTIABLE

pflow creates fresh instances for EVERY operation:

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

## Discovery Tools: Use Planning Nodes Directly

**CORRECTION from original**: We DO use ComponentBrowsingNode and WorkflowDiscoveryNode for discovery tools.

```python
# For registry_discover
from pflow.planning.nodes import ComponentBrowsingNode
node = ComponentBrowsingNode()
shared = {
    "user_input": query,
    "workflow_manager": WorkflowManager()  # Required!
}
node.run(shared)  # Returns structured data in shared["planning_context"]

# For workflow_discover
from pflow.planning.nodes import WorkflowDiscoveryNode
node = WorkflowDiscoveryNode()
# Similar pattern
```

These nodes provide LLM-powered intelligent selection, which is what agents expect from the CLI.

For simple operations like `registry_list`, use Registry directly:
```python
registry = Registry()
nodes = registry.load()  # Full interface metadata already parsed!
```

## The Hidden Gold in execute_workflow()

Task 68 already solved the hard part. The execute_workflow API is PERFECT as-is:

```python
result = execute_workflow(
    workflow_ir=workflow_dict,      # Takes dict directly!
    execution_params=params,        # MCP params map perfectly!
    enable_repair=False,           # Always disable for MCP
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

## Security Layers You Can't Skip

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

Also, REDACT sensitive params:
```python
SENSITIVE = {'password', 'token', 'api_key', 'secret', 'auth', 'credential'}
```

## The asyncio.to_thread() Bridge

MCP is async. pflow is sync. The bridge is `asyncio.to_thread()`:

```python
async def tool_handler():
    result = await asyncio.to_thread(sync_function, args)
```

**Why this and not asyncio.run()?** Because MCPNode uses asyncio.run() which creates a NEW event loop each time. That's fine for one-off MCP calls, but the MCP SERVER already has an event loop running. Use to_thread() to run sync code in the thread pool.

## Performance Numbers That Matter

From actual measurements:
- Registry.load(): 10-50ms (cached in memory after first)
- execute_workflow: 100-500ms without LLM
- asyncio.to_thread overhead: 1-5ms

Don't optimize prematurely. The bottleneck is workflow execution, not MCP overhead.

## Testing Priority

Test these in ORDER:

1. **Stateless verification** - Multiple concurrent requests get isolated instances
2. **Path traversal** - All attack vectors blocked
3. **Checkpoint resume** - Second execution skips completed nodes
4. **Error structure** - Agents can parse error responses
5. **Claude Code discovery** - Tools found without prompting

If #1 fails, nothing else matters.

## Patterns From MCPNode to Mirror

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

## Critical Gotchas

1. **MCP nodes return "default" on error** - This hides failures. They should return "error".
2. **Template resolution can return unchanged** - If a template can't resolve, it returns the original string unchanged. Check for this.
3. **WorkflowManager.load() vs load_ir()** - load() returns metadata wrapper, load_ir() returns just the IR. You usually want load_ir() for execution.
4. **Registry filtering** - Registry.load() respects settings.json filtering. Use load(include_filtered=True) if you need all nodes.
5. **Planning nodes need workflow_manager** - ComponentBrowsingNode and WorkflowDiscoveryNode require WorkflowManager() in shared store.

## Critical Warnings

1. **DO NOT** add caching "for performance" - it will break isolation
2. **DO NOT** enable internal repair - agents orchestrate repair
3. **DO NOT** trust workflow names - validate everything
4. **DO NOT** share instances between requests - stateless only
5. **DO** use planning nodes for discovery - they provide LLM intelligence

## Implementation Starting Point

Begin with `workflow_discover` or `registry_discover`. They prove the pattern of:
1. Using planning nodes directly
2. Stateless operation
3. asyncio.to_thread bridge
4. Structured responses

Once these work, the execution tools follow similar patterns.

## The Tool Count Evolution

The original handover mentioned 5 tools. We now know from AGENT_INSTRUCTIONS analysis that we need 13 tools:
- 6 Priority 1 (core loop)
- 5 Priority 2 (supporting)
- 2 Priority 3 (nice to have)

This isn't complexity - it's completeness. Each tool has a specific purpose in the agent workflow.

---

**Remember**: This isn't about building complex new systems. It's about exposing existing pflow capabilities through thin MCP wrappers so agents can orchestrate workflow building programmatically.

The magic is in keeping it simple while being complete.