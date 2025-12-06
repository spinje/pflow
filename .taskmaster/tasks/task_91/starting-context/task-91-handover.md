# Task 91 Handoff Memo: Export Workflows as Self-Hosted MCP Server Packages

## Context: How This Task Was Born

The user had what they called a "silly thought" about exposing workflows as remote HTTP MCPs. Through discussion, we discovered **two distinct but complementary features**:

1. **Task 90**: Cloud-hosted MCP endpoints (pflow cloud manages everything)
2. **Task 91**: Self-hosted MCP server packages (user deploys anywhere)

The user explicitly confirmed Task 91 makes sense and wanted it documented separately. This is **not** a variant of Task 46—it's a sibling that shares infrastructure.

---

## The Three Export Paths (Critical Mental Model)

| Task | Output | Runs Where | Dependencies |
|------|--------|------------|--------------|
| Task 46 | Python/TS script | User runs CLI | Zero (stdlib) |
| Task 91 | MCP server package | User deploys | mcp, fastmcp |
| Task 90 | HTTP URL | pflow cloud | pflow account |

**Key insight**: Task 46 and 91 share the same code generation engine. The difference is the wrapper:

```
Task 46: workflow IR → compiled code → CLI wrapper (argparse, stdin)
Task 91: workflow IR → compiled code → MCP wrapper (FastMCP, @mcp.tool)
```

You are NOT building a new code generator. You are adding an output format to Task 46's infrastructure.

---

## Task 46 Handover is Your Bible

**READ THIS FIRST**: `.taskmaster/tasks/task_46/starting-context/task-46-handover.md`

That document contains 900+ lines of critical knowledge:
- IR schema understanding
- Template variable resolution
- Node code generation patterns
- Nested workflow handling
- Namespacing behavior
- Credential management
- Edge routing logic
- Stdin/stdout handling
- 8 specific traps and gotchas

Everything in that document applies to Task 91. The only new parts are:
1. MCP tool schema generation
2. FastMCP wrapper instead of CLI wrapper
3. Bundle support (multiple workflows → multiple tools)

---

## What I Learned from MCP Ecosystem Research

This context will help you understand why this feature matters:

### Adoption is Massive
- 16,000+ MCP servers exist (as of late 2025)
- OpenAI adopted MCP in March 2025 (ChatGPT, Agents SDK)
- Microsoft adding MCP to Windows
- ~90% of organizations expected to use MCP by end of 2025

### Remote HTTP is the Standard
- Streamable HTTP replaced HTTP+SSE as the transport
- ChatGPT supports remote MCP servers in Developer Mode (Pro/Team/Enterprise)
- Claude Desktop, Cursor, Windsurf all support remote MCP

### Pain Points (That Task 91 Solves)
- **Server sprawl**: Users install dozens of MCP servers
  - Task 91's bundle feature: one server, many tools
- **Setup complexity**: Creating MCP servers requires protocol knowledge
  - Task 91: "describe workflow → get deployable server"
- **Discovery friction**: Finding and configuring servers is manual
  - Task 91: Workflow becomes self-documenting tool

### Sources
- https://en.wikipedia.org/wiki/Model_Context_Protocol
- https://platform.openai.com/docs/mcp
- https://www.infoq.com/news/2025/06/anthropic-claude-remote-mcp/
- https://blog.christianposta.com/enterprise-challenges-with-mcp-adoption/

---

## pflow's Existing MCP Server (Pattern to Follow)

pflow already has an MCP server (Task 72) at `src/pflow/mcp_server/`. Study this:

**Server structure**:
```
src/pflow/mcp_server/
├── main.py          # Server startup
├── server.py        # FastMCP instance
├── tools/           # Tool implementations
├── services/        # Business logic
└── utils/           # Helpers
```

**Key patterns**:
- Uses FastMCP from `mcp.server.fastmcp`
- Tools are async but call sync services via `asyncio.to_thread`
- Tool descriptions are detailed docstrings
- Error handling returns structured messages

**Example tool definition** (from `src/pflow/mcp_server/tools/workflow_tools.py`):
```python
@mcp.tool()
async def workflow_execute(
    workflow: str,
    parameters: dict[str, Any] | None = None,
) -> str:
    """Execute a pflow workflow.

    Args:
        workflow: Workflow name, file path, or inline IR dict
        parameters: Optional parameter overrides

    Returns:
        Execution result or error message
    """
```

**For Task 91**: Generated code will look similar, but:
- The tool body is compiled workflow logic (not pflow runtime calls)
- No `import pflow` anywhere
- Sync execution is fine (no asyncio.to_thread needed)

---

## Tool Schema Generation (New for Task 91)

Workflow IR has `inputs` and `outputs`. These map to MCP tool schemas:

**Workflow IR**:
```json
{
  "name": "pr-notifier",
  "description": "Monitors GitHub PRs and posts to Slack",
  "inputs": [
    {"name": "repo", "type": "string", "description": "GitHub repository"},
    {"name": "channel", "type": "string", "description": "Slack channel"}
  ],
  "outputs": [
    {"name": "summary", "type": "string", "description": "Notification summary"}
  ]
}
```

**Generated MCP tool**:
```python
@mcp.tool()
def pr_notifier(repo: str, channel: str) -> str:
    """Monitors GitHub PRs and posts to Slack.

    Args:
        repo: GitHub repository
        channel: Slack channel

    Returns:
        Notification summary
    """
    # Compiled workflow logic...
    return summary
```

**Type mapping** (workflow IR → Python):
- `string` → `str`
- `number` → `float`
- `integer` → `int`
- `boolean` → `bool`
- `array` → `list`
- `object` → `dict`

---

## Bundle Strategy

When user exports multiple workflows:

```bash
pflow workflow export --format mcp workflow1 workflow2 --name my-tools
```

Generate ONE server with MULTIPLE tools:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-tools")

@mcp.tool()
def workflow1(...) -> str:
    """First workflow description."""
    # Compiled logic...

@mcp.tool()
def workflow2(...) -> str:
    """Second workflow description."""
    # Compiled logic...

if __name__ == "__main__":
    mcp.run()
```

**Why this matters**: Instead of deploying N servers, user deploys ONE. Less infrastructure, simpler discovery.

---

## Credential Handling

MCP servers use environment variables (standard pattern). Generated code should:

```python
import os

def get_credential(key: str) -> str:
    """Load credential from environment."""
    value = os.environ.get(key)
    if not value:
        raise ValueError(
            f"Missing required credential: {key}\n"
            f"Set it using: export {key}=<value>"
        )
    return value
```

**Don't** include the hybrid pflow settings.json lookup from Task 46. MCP servers are typically deployed in containers where env vars are the standard.

**Do** generate a README with required credentials:

```markdown
## Required Environment Variables

- `GITHUB_TOKEN`: GitHub API access
- `SLACK_TOKEN`: Slack API access

Set these before running the server:
\```bash
export GITHUB_TOKEN="ghp_..."
export SLACK_TOKEN="xoxb-..."
python server.py
\```
```

---

## Deployment Targets

### Python (FastMCP) - Phase 1
```
my_workflow_mcp/
├── server.py          # FastMCP server
├── requirements.txt   # mcp>=1.0.0
├── Dockerfile         # Optional
└── README.md          # Deployment instructions
```

### TypeScript (Future, After Task 46 Phase 2)
```
my_workflow_mcp/
├── src/
│   └── server.ts      # TypeScript MCP server
├── package.json
└── README.md
```

**Why TypeScript matters**: Cloudflare Workers, Deno Deploy, Vercel Edge. These are cheap, fast, globally distributed. Python can't run there.

---

## What's Different from Task 46

| Aspect | Task 46 (Script) | Task 91 (MCP Server) |
|--------|------------------|----------------------|
| Entry point | `if __name__ == "__main__"` with argparse | `mcp.run()` |
| Input handling | CLI args, stdin | Tool parameters |
| Output | Print to stdout | Return from tool |
| Dependencies | Zero (stdlib only) | `mcp`, `fastmcp` |
| Credentials | Hybrid (env + settings.json) | Env vars only |
| Multi-workflow | N scripts | 1 server, N tools |

**Shared** (from Task 46):
- IR parsing
- Template resolution → Python code
- Node code generation
- Edge routing logic
- Nested workflow handling
- Error handling patterns

---

## Files and Docs to Read

### Critical (Read Before Starting)
1. `.taskmaster/tasks/task_46/starting-context/task-46-handover.md` - The comprehensive code generation guide
2. `src/pflow/mcp_server/server.py` - pflow's existing MCP server patterns
3. `src/pflow/mcp_server/tools/workflow_tools.py` - Tool definition examples

### Useful Reference
4. `src/pflow/core/ir_schema.py` - Workflow IR schema (inputs/outputs)
5. `src/pflow/execution/formatters/` - Formatter pattern (return, don't print)
6. `architecture/features/mcp-server.md` - MCP server architecture docs

### External
7. FastMCP docs: https://gofastmcp.com/
8. MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk

---

## Questions to Resolve During Implementation

1. **Should generated servers be async or sync?**
   - pflow's server is async (uses asyncio.to_thread)
   - Generated code could be simpler with sync
   - Async might be needed for HTTP nodes

2. **How to handle streaming for long workflows?**
   - MCP supports streaming responses
   - Might not be needed for MVP

3. **Should we generate a Dockerfile?**
   - Makes deployment easier
   - Adds complexity to generator
   - Could be optional flag

4. **Transport configuration?**
   - stdio is default (works with Claude Desktop)
   - HTTP/SSE for remote deployment
   - Could generate both entry points

---

## Implementation Order Suggestion

1. **Start with Task 46** - Get the code generation working for scripts first
2. **Add MCP output format** - Wrap the same generated code in FastMCP
3. **Single workflow first** - Get one workflow → one tool working
4. **Then bundle support** - Multiple workflows → multiple tools
5. **Then polish** - README generation, Dockerfile, etc.

Task 91 is essentially "add `--format mcp` to Task 46's export command."

---

## Ready to Begin?

**DO NOT start implementing yet.**

First:
1. Read the Task 46 handover document thoroughly
2. Study pflow's existing MCP server in `src/pflow/mcp_server/`
3. Understand how workflow IR inputs/outputs map to tool schemas
4. Confirm Task 46 is complete (or at least the core code generation)

When you're ready, respond: **"I have read the handoff memo and understand that Task 91 builds on Task 46's code generation infrastructure. I am ready to begin implementation."**
