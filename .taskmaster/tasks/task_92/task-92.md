# Task 92: Replace Planner with Agent + MCP Tools (Dogfooding)

## ID
92

## Title
Replace Planner with Agent + MCP Tools (Dogfooding)

## Description
Replace the complex multi-phase natural language planner with a simple agent node that uses pflow's own MCP tools. This dramatically reduces complexity while improving reliability by leveraging Claude's native tool-use capabilities instead of custom prompt orchestration.

## Status
not started

## Dependencies
- Task 72: Implement MCP Server for pflow - The MCP tools that the agent will use are already implemented
- Task 12: Implement LLM Node - The agent node infrastructure exists

## Priority
medium

## Details

### Problem Statement

The current planner (`src/pflow/planning/`) is one of the most complex subsystems in pflow:
- Multi-phase LLM orchestration (discovery → browsing → generation → validation)
- Custom prompts that require tuning and maintenance
- ~6 files, 1000+ lines of code
- Prompt caching, error handling, repair loops
- **Questionable reliability** - complex prompt chains are fragile

Meanwhile, pflow already has an MCP server (Task 72) that exposes all the tools needed to build workflows:
- `registry_discover` - Find nodes by capability
- `registry_describe` - Get detailed node specs
- `workflow_validate` - Validate workflow IR
- `workflow_execute` - Execute workflows
- etc.

### Proposed Solution (Option 1 - Recommended)

Replace the planner with an agent node that uses pflow's own MCP tools:

```python
# Conceptual implementation
def plan_and_execute(user_request: str) -> str:
    agent = ClaudeNode(
        tools=get_pflow_mcp_tools(),  # Same tools exposed via MCP server
        system_prompt=AGENT_SYSTEM_PROMPT,
    )
    return agent.run(user_request)
```

The agent:
1. Receives natural language request
2. Uses `registry_discover` to find relevant nodes
3. Uses `registry_describe` to understand node interfaces
4. Builds workflow IR
5. Uses `workflow_validate` to check it
6. Uses `workflow_execute` to run it
7. Returns results

**This is dogfooding** - using pflow's own tools to build pflow workflows.

### Why This Is Better

| Aspect | Current Planner | Agent + MCP Tools |
|--------|-----------------|-------------------|
| Code complexity | ~1000 lines, 6 files | ~100 lines |
| Reliability | Fragile prompt chains | Claude's robust tool use |
| Maintainability | Custom prompts drift | Model improvements help automatically |
| Flexibility | Fixed phases | Agent adapts to situation |
| Proves MCP works | No | Yes (dogfooding) |

### Trade-off: Cost

| Approach | LLM Calls | Token Usage |
|----------|-----------|-------------|
| Current planner | 3-5 structured calls | Lower |
| Agent + tools | 5-15 tool calls | Higher |

The agent approach costs more per invocation, but if the current planner doesn't work reliably, cost savings are meaningless.

### Implementation Approach

1. Create a new module (e.g., `src/pflow/planning/agent_planner.py`)
2. Reuse MCP tool implementations from `src/pflow/mcp_server/services/`
3. Wire up agent node with tool-calling capability
4. Replace planner invocation in CLI (`src/pflow/cli/main.py`)
5. Keep old planner code temporarily for comparison
6. Remove old planner once new approach is validated

### System Prompt (Draft)

```
You are a pflow workflow builder. Your job is to understand the user's request
and build a workflow that accomplishes it using the available pflow tools.

Workflow:
1. Use registry_discover to find nodes that match the user's needs
2. Use registry_describe to understand how those nodes work
3. Build a workflow IR that chains the nodes together
4. Use workflow_validate to check your workflow
5. If validation fails, fix the issues and try again
6. Use workflow_execute to run the workflow
7. Return the results to the user

Be thorough in discovery. Check node interfaces carefully. Validate before executing.
```

---

## Alternative Options (Documented for Future Reference)

### Option 2: Remove CLI Natural Language Entirely

Instead of replacing the planner, remove the `pflow "natural language"` interface entirely.

**Rationale**: If users are primarily using Claude Code, ChatGPT, or other agents, they don't need pflow to have its own natural language interface. The agent IS the interface.

**Implementation**:
- Remove `src/pflow/planning/` entirely
- Remove natural language handling from CLI
- Document that users should use pflow via MCP tools in their preferred agent

**Pros**: Maximum simplicity, no planner code at all
**Cons**: Loses standalone CLI appeal, requires users to have an agent

### Option 3: Keep Both (Planner for Cheap, Agent for Reliable)

Offer both approaches:
- `pflow "do X"` uses cheap planner (current)
- `pflow --agent "do X"` uses reliable agent approach

**Rationale**: Some users want cheap/fast, others want reliable.

**Pros**: User choice, preserves investment in planner
**Cons**: Maintains two code paths, complexity++

---

## Test Strategy

### Unit Tests
- Test agent node with mocked MCP tools
- Verify tool call sequences for simple requests
- Test error handling when tools fail

### Integration Tests
- End-to-end: natural language → agent → workflow execution
- Compare results with current planner (should be equivalent or better)
- Test with various request types (simple, complex, ambiguous)

### Comparison Tests
- Run same requests through old planner and new agent
- Compare success rates, execution times, costs
- Document where agent outperforms or underperforms

### Key Scenarios
- Simple single-node requests ("read file.txt")
- Multi-node workflows ("read file, summarize, write to output")
- Ambiguous requests (agent should ask for clarification or make reasonable choices)
- Invalid requests (should fail gracefully)
