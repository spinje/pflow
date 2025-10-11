# Task 72 Handoff: Critical Knowledge for MCP Server Implementation

**To the implementing agent**: Read this entire document before starting. This contains hard-won insights that aren't obvious from the specs. Say "I'm ready to implement Task 72" after reading.

## 🚨 Critical Context: Task 71 vs Task 72 Confusion

**YOU MUST UNDERSTAND THIS FIRST**: There's massive confusion in the older documentation. Many docs were written assuming Task 71 was the MCP implementation. Here's the truth:

- **Task 71** (COMPLETED): CLI extensions for agents (`pflow workflow discover`, etc.)
- **Task 72** (THIS TASK): MCP server exposing pflow as programmatic tools

If a document talks about "Task 71 MCP implementation" - it's WRONG. Task 71 is done, it added CLI discovery commands. We're building the MCP server NOW.

## 🎯 The Source of Truth: AGENT_INSTRUCTIONS

The breakthrough came from analyzing `.pflow/instructions/AGENT_INSTRUCTIONS.md`. A subagent extracted 23 CLI commands that agents ACTUALLY use (not what we theorized). Key insights:

1. **Agents follow this EXACT pattern**:
   - `workflow discover` first (MANDATORY - "5 seconds vs hours")
   - `registry discover` for building
   - `registry run --show-structure` for testing MCP nodes
   - Execute with `--output-format json --no-repair --trace` (ALL THREE)
   - `workflow save` to make reusable

2. **MCP nodes are NEVER simple**:
   - Docs say: `result: Any`
   - Reality: `result.data.tool_response.nested.deeply.url`
   - `registry_run` is CRITICAL for revealing actual structure

3. **Discovery is intelligent, not keyword search**:
   - Uses LLM for matching
   - Returns confidence scores
   - ≥95% = use existing, <80% = build new

## 🔧 Architecture Decisions (Non-Negotiable)

### Why 13 Tools (Not 5, Not 18)

Based on ACTUAL agent usage from AGENT_INSTRUCTIONS:
- **6 Priority 1**: Core workflow loop (discover → build → test → save)
- **5 Priority 2**: Supporting functions
- **2 Priority 3**: Advanced features

We rejected:
- Natural language execution (too complex, agents use steps)
- Multiple execution variants (one flexible tool instead)
- Parameter flags (built-in defaults)

### Direct Service Integration (NOT CLI Wrapping)

```python
# ✅ CORRECT - Direct service use
from pflow.core.workflow_manager import WorkflowManager
from pflow.execution.workflow_execution import execute_workflow

# ❌ WRONG - CLI wrapping
subprocess.run(["pflow", "execute", ...])
```

Why: Performance, structured responses, no text parsing needed.

### Stateless Pattern (CRITICAL)

```python
# Every request gets FRESH instances
async def tool_handler():
    manager = WorkflowManager()  # NEW instance
    registry = Registry()        # NEW instance
    # Use and discard
```

This matches pflow's own pattern. DO NOT cache instances. The 10-50ms overhead is nothing compared to the bugs you'll create with stale state.

## 🧩 Implementation Patterns You MUST Follow

### 1. Discovery Tools Use Planning Nodes DIRECTLY

```python
# For workflow_discover
from pflow.planning.nodes import WorkflowDiscoveryNode
node = WorkflowDiscoveryNode()
shared = {
    "user_input": query,
    "workflow_manager": WorkflowManager()  # REQUIRED!
}
action = node.run(shared)
```

DO NOT extract the logic. Use the nodes as-is. They're designed for this.

### 2. Agent Mode is BUILT-IN (No Parameters)

All tools automatically:
- Return JSON (no format parameter)
- Disable auto-repair (no repair flag)
- Save traces (no trace flag)
- Auto-normalize workflows (add ir_version, edges)

The user was explicit: "keep the mcp interface as clean as possible"

### 3. asyncio.to_thread Bridge Pattern

```python
# MCP is async, pflow is sync
result = await asyncio.to_thread(
    execute_workflow,  # Sync function
    workflow_ir=workflow,
    execution_params=params,
    output=NullOutput(),
    enable_repair=False  # Always False for MCP
)
```

### 4. Error Response Pattern

```python
# Always use isError flag so LLMs see it
return CallToolResult(
    isError=True,
    content=[TextContent(text="Error message")]
)
```

## ⚠️ Hidden Gotchas That Will Break Everything

1. **ComponentBrowsingNode requires workflow_manager**:
   - Missing it causes "Invalid request format" error
   - Always add: `"workflow_manager": WorkflowManager()`

2. **Template validation needs dummy params**:
   - Generate placeholders for workflow inputs
   - Enables structural validation without real values

3. **Workflow resolution order matters**:
   - Check library first (`~/.pflow/workflows/`)
   - Then check file paths
   - This encourages reusable workflows

4. **Security validation is CRITICAL**:
   - No path traversal (`../`, `~/`, absolute paths)
   - Validate ALL workflow names
   - Sanitize sensitive params in responses

5. **MCP node testing reveals truth**:
   - Documentation LIES about output structure
   - `registry_run` with actual test data is essential
   - Agents need the real nested paths for templates

## 📁 File References (Your Map)

### Implementation Specs
- **`.taskmaster/tasks/task_72/starting-context/final-implementation-spec.md`** - The TRUTH. 13 tools, clean interface
- **`.taskmaster/tasks/task_72/starting-context/pflow-commands-extraction.md`** - What agents ACTUALLY use (from AGENT_INSTRUCTIONS)
- **`.taskmaster/tasks/task_72/starting-context/mcp-implementation-guidance.md`** - Protocol patterns, security, testing

### Code to Study
- **`src/pflow/planning/nodes.py`** - WorkflowDiscoveryNode, ComponentBrowsingNode (use directly!)
- **`src/pflow/execution/workflow_execution.py`** - execute_workflow function
- **`src/pflow/execution/null_output.py`** - NullOutput for silent execution
- **`src/pflow/core/workflow_manager.py`** - WorkflowManager (stateless usage)

### Ignore These (Outdated/Wrong)
- Any doc mentioning "Task 71 MCP implementation"
- Recommendations for 18 tools (we chose 13)
- CLI wrapping approaches (we use direct integration)

## 🧪 Testing Approach

1. **Start with Priority 1 tools** - Get the core loop working
2. **Test with AGENT_INSTRUCTIONS examples** - Use real agent workflows
3. **Validate discovery → execute → save cycle** - The full pattern
4. **Test MCP node structure revelation** - registry_run MUST show nested outputs
5. **Performance: Should beat CLI** - Direct integration should be faster

### Specific Test Case

```python
# This is the pattern agents follow
result = await workflow_discover("analyze GitHub PRs")
# If <95% confidence, build new:
nodes = await registry_discover("fetch GitHub PR, analyze with AI")
# Test unknown nodes:
structure = await registry_run("mcp-github-GET_PULL_REQUEST", {"test": "params"})
# Validate workflow:
valid = await workflow_validate(workflow_json)
# Execute with defaults (JSON, no-repair, trace):
result = await workflow_execute(workflow_json, params)
# Save for reuse:
saved = await workflow_save(workflow_file, name, description)
```

## 🚫 Common Pitfalls (Don't Make These Mistakes)

1. **DON'T extract logic from planning nodes** - Use them directly
2. **DON'T add parameters for agent mode** - Build in the defaults
3. **DON'T cache service instances** - Fresh every time
4. **DON'T trust workflow names** - Validate for path traversal
5. **DON'T skip MCP node testing** - The structure is always nested
6. **DON'T implement natural language execution** - Too complex
7. **DON'T wrap CLI commands** - Use services directly

## 💡 Non-Obvious Insights

1. **The evolution of thinking**:
   - Started with 14-18 tools (too many)
   - Simplified to 5 (too few)
   - Settled on 13 based on ACTUAL usage

2. **Discovery-first is ENFORCED**:
   - Not a suggestion, it's mandatory
   - Agents waste hours rebuilding existing workflows
   - Confidence scores guide the decision

3. **Token overhead is acceptable**:
   - 13 tools = ~1,300-6,500 tokens
   - Well under the 40-tool warning limit

4. **Planning nodes already have defaults**:
   - Model: anthropic/claude-3-5-sonnet
   - Temperature: 0.0
   - No need to configure

## 🎬 Final Critical Notes

The user's key requirements:
1. "We should not expose the natural language execution"
2. "Keep the mcp interface as clean as possible"
3. "Expose all the pflow cli tools that are described in [AGENT_INSTRUCTIONS]"

Remember: We're exposing what agents ALREADY use via CLI, but with:
- Structured responses (no parsing)
- Better performance (no shell spawning)
- Programmatic access (for systems without shell)

The implementation should take 4.5 days following the phases in task-72.md.

---

**IMPORTANT**: Do not begin implementing until you've read this entire document. The confusion in the older docs will mislead you if you don't understand the Task 71/72 distinction and the insights from AGENT_INSTRUCTIONS.

When you're ready, say "I'm ready to implement Task 72 with full understanding of the context and gotchas."