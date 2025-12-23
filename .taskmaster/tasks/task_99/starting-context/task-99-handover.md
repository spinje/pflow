# Task 99 Handover Memo: Expose pflow Nodes as MCP Tools to Claude Code Node

## Context: Why This Task Exists

The user wants to build a "Super Code Reviewer and Fixer" workflow where Claude Code:
1. Reviews a PR
2. Spawns parallel subagents to fix issues
3. Posts comments to GitHub
4. Commits changes

The key insight that emerged: **Claude Code already has subagent capabilities via its built-in Task tool**. The parallelism happens INSIDE Claude Code, not at the pflow level. But Claude Code doesn't know about pflow's node ecosystem (github-add-comment, http, etc.).

**The user's goal**: Give Claude Code the ability to call pflow nodes on-demand, without pre-wiring everything in the workflow DAG.

**Security concern**: The user explicitly rejected exposing Bash so Claude could run `pflow registry run`. They want a scoped MCP tool approach.

---

## Critical SDK Knowledge I Discovered

### 1. ClaudeAgentOptions Parameters (SDK v0.1.18+)

From inspecting the actual SDK, these are the REAL parameters:

```python
ClaudeAgentOptions(
    allowed_tools: list[str] = [],           # Tools Claude can use
    system_prompt: str | None = None,
    mcp_servers: dict | str | Path = {},     # MCP server configurations
    resume: str | None = None,               # Session ID to resume
    max_turns: int | None = None,
    max_thinking_tokens: int | None = None,  # Extended thinking tokens
    cwd: str | Path | None = None,
    permission_mode: str | None = None,      # "bypassPermissions", "acceptEdits", etc.
    sandbox: SandboxSettings | None = None,  # Command isolation settings
    # ... more fields
)
```

### 2. How `mcp_servers` Works

The SDK accepts both external and SDK (in-process) servers:

```python
# External subprocess server
mcp_servers={
    "name": {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "server_module"]
    }
}

# SDK in-process server (what we want for Task 99)
mcp_servers={
    "pflow": sdk_server_instance  # FastMCP instance
}
```

**The SDK server approach is what the user wants** - no subprocess, no external dependencies.

### 3. Tool Naming Convention

When you add an MCP server named "pflow" with a tool "pflow_run", Claude Code sees it as:
```
mcp__pflow__pflow_run
```

You may need to add this to `allowed_tools` if you're restricting tools.

---

## Key Files to Study

| File | Why It Matters |
|------|----------------|
| `src/pflow/nodes/claude/claude_code.py` | Main file to modify. Current params: `prompt`, `cwd`, `model`, `allowed_tools`, `max_turns`, `max_thinking_tokens`, `timeout`, `system_prompt`, `resume`, `sandbox`. Study `_build_claude_options()`. |
| `src/pflow/mcp_server/services/execution_service.py` | Has `run_registry_node()` - this is the function to reuse. It's a classmethod that handles node loading, execution, and formatting. |
| `src/pflow/mcp_server/tools/execution_tools.py` | Look at `registry_run` MCP tool (line ~228). Shows the pattern for wrapping ExecutionService. |
| `src/pflow/planning/context_builder.py` | Has `build_planning_context()` for generating node descriptions. May be useful for system prompt injection. |

---

## Implementation Insight: The Async/Sync Bridge

pflow is synchronous. MCP protocol is async. The existing MCP tools use this pattern:

```python
@mcp.tool()
async def tool_name(param: str) -> str:
    def _sync_operation():
        return SyncService.method(param)

    return await asyncio.to_thread(_sync_operation)
```

**BUT** - the Claude Code SDK's `mcp_servers` with SDK servers might handle this differently. The FastMCP `@server.tool()` decorator may or may not require async functions. Test both:

```python
# Try sync first
@server.tool()
def pflow_run(node_type: str, parameters: dict) -> str:
    return ExecutionService.run_registry_node(node_type, parameters)

# If that fails, try async bridge
@server.tool()
async def pflow_run(node_type: str, parameters: dict) -> str:
    return await asyncio.to_thread(
        lambda: ExecutionService.run_registry_node(node_type, parameters)
    )
```

---

## The User's Exact Requirements

1. **Single MCP tool**: Named `pflow_run` (not multiple tools)
2. **Allowlist validation**: If `pflow_tools=["github-add-comment", "http"]`, reject calls to any other node
3. **Reuse existing code**: Don't duplicate `ExecutionService.run_registry_node()` logic
4. **System prompt injection**: Claude needs to know what nodes are available and their parameters

---

## Subtle Gotcha: `allowed_tools=None` vs Not Passing It

In the current implementation:
```python
# If allowed_tools is None, we DON'T pass it to ClaudeAgentOptions
if prep_res["allowed_tools"] is not None:
    options_kwargs["allowed_tools"] = prep_res["allowed_tools"]
```

This is intentional. `None` means "use SDK default (all tools)". If you explicitly pass `allowed_tools=None`, the SDK might interpret it differently.

When adding MCP tools, you might need to handle this:
```python
# If we're adding MCP server, we may need to explicitly allow the MCP tool
if pflow_tools:
    if prep_res["allowed_tools"] is not None:
        # User specified tools - add MCP tool to their list
        options_kwargs["allowed_tools"] = prep_res["allowed_tools"] + ["mcp__pflow__pflow_run"]
    # else: None means all tools, MCP tool automatically included
```

---

## Research Findings Location

I created a research document with all findings:
`scratchpads/super-code-reviewer/research-findings.md`

This includes:
- Claude Code SDK session management (resume, fork_session)
- Subagent capabilities via Task tool
- GitHub node gaps (github-add-comment missing)
- Full component analysis

---

## Questions I Couldn't Answer

1. **Does FastMCP work as SDK server with Claude Code?** I found docs saying it should, but didn't test it. The pattern is:
   ```python
   from mcp import FastMCP
   server = FastMCP("pflow-tools")
   @server.tool()
   def my_tool(): ...
   ```
   Then pass `server` directly to `mcp_servers`.

2. **What's the exact return type of `ExecutionService.run_registry_node()`?** I believe it's a string, but verify by reading the service code.

3. **Do MCP tool results show up in Claude's context?** The user wants Claude to use these tools dynamically, which requires Claude seeing the results.

---

## What The User Cares About

The user is building autonomous agent workflows. They want:
- **Simplicity**: One Claude Code node that can do complex things
- **Security**: Scoped access, not full Bash
- **Reusability**: Not pre-wiring every tool into every workflow

They do NOT care about:
- Perfect error messages (MVP)
- Comprehensive logging
- Backwards compatibility (no users yet)

---

## Don't Forget

1. **Tests**: The existing Claude Code tests mock the SDK heavily. You'll need similar mocking for MCP server tests.

2. **Docstrings**: Update the Interface section in the module docstring when adding `pflow_tools`.

3. **Run `make check`**: The project uses ruff for formatting and mypy for type checking.

---

## Final Note

The user explicitly said "Option A is best" referring to the minimal SDK MCP server approach. Don't over-engineer this. A single file with `create_pflow_tools_server()` that returns a FastMCP instance with one tool is the goal.

---

**⚠️ IMPORTANT: Do not begin implementing yet. Read this document, review the referenced files, and confirm you're ready to begin.**
