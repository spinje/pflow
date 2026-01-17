# Task 91: Export Workflows as Self-Hosted MCP Server Packages

## Description
Enable users to export pflow workflows as standalone MCP server packages (Python/TypeScript) that can be deployed on their own infrastructure. This allows workflows to be distributed as installable MCP servers that any MCP-compatible agent can use, without requiring pflow runtime or cloud dependencies.

## Status
not started

## Dependencies
- Task 46: Workflow Export to Zero-Dependency Code - The core workflow-to-code compilation infrastructure is required. This task adds an MCP server wrapper around the same code generation engine.

## Priority
medium

## Details
This feature extends Task 46's code export capability to generate MCP server packages instead of (or in addition to) standalone scripts.

### Core Concept

The same workflow IR → code compilation from Task 46 is wrapped differently:

| Output Format | Wrapper | Use Case |
|---------------|---------|----------|
| `--format script` | CLI with argparse/stdin | Run workflow directly |
| `--format mcp` | FastMCP server with `@mcp.tool()` | Deploy as MCP server |

### Single Workflow Export

```bash
pflow workflow export --format mcp my-workflow
```

Generates:
```
my_workflow_mcp/
├── server.py          # FastMCP server with workflow as tool
├── requirements.txt   # Dependencies (mcp, etc.)
└── README.md          # Deployment instructions
```

### Bundle Multiple Workflows

```bash
pflow workflow export --format mcp workflow1 workflow2 workflow3 --name my-tools
```

Generates one MCP server with multiple tools:
```python
@mcp.tool()
def workflow1(...): ...

@mcp.tool()
def workflow2(...): ...

@mcp.tool()
def workflow3(...): ...
```

### Generated Server Structure

```python
# server.py (generated)
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-workflow")

@mcp.tool()
def my_workflow(repo: str, channel: str) -> str:
    """Monitors GitHub PRs and posts to Slack.

    Args:
        repo: GitHub repository (owner/repo format)
        channel: Slack channel to post to

    Returns:
        Summary of notifications sent
    """
    # ... compiled workflow logic from Task 46 ...
    return result
```

### Tool Schema Generation

Workflow inputs/outputs map to MCP tool schemas:
- Workflow `inputs` → tool parameters with types and descriptions
- Workflow `outputs` → tool return value
- Workflow `description` → tool docstring

### Deployment Targets

**Python (FastMCP)**:
- Local: `python server.py`
- Docker: Include Dockerfile
- Cloud Run / Lambda: Standard Python deployment

**TypeScript (future, after Task 46 Phase 2)**:
- Cloudflare Workers
- Deno Deploy
- Vercel Edge Functions

### Relationship to Other Tasks

| Task | What it does | Where it runs |
|------|--------------|---------------|
| Task 46 | Export as standalone script | User runs CLI |
| Task 90 | Cloud-hosted MCP endpoints | pflow cloud |
| Task 91 (this) | Export as MCP server package | User deploys anywhere |

### Key Design Decisions

1. **Shares code generation with Task 46** - Same IR → code compilation, different wrapper
2. **FastMCP for Python** - Well-supported, matches pflow's existing MCP server
3. **Zero pflow runtime dependency** - Generated server is completely standalone
4. **Bundle support** - Multiple workflows → one server with multiple tools
5. **Credential handling** - Environment variables (standard for MCP servers)

## Test Strategy
Testing approach builds on Task 46's test infrastructure:

### Unit Tests
- Test MCP tool schema generation from workflow inputs/outputs
- Test FastMCP decorator generation
- Test bundle generation (multiple workflows → multiple tools)
- Test requirements.txt generation with correct dependencies

### Integration Tests
- Export workflow → start generated MCP server → call tool via MCP client
- Verify tool response matches direct workflow execution
- Test with real MCP clients (Claude Desktop config, programmatic client)

### End-to-End Tests
- Export real workflow from examples/
- Deploy generated server (local subprocess)
- Connect MCP client and execute tool
- Verify results match pflow execution

### Key Scenarios
- Single workflow export
- Multiple workflow bundle
- Workflows with various node types (shell, file, git, github)
- Workflows with complex inputs (nested objects, arrays)
- Error handling in generated tools
