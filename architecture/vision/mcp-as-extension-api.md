---
**Document Type**: Vision/Strategy (NOT current implementation)

**For Current Architecture**: See `architecture/architecture.md`

**Caveat**: Current pflow uses a hybrid approach with platform nodes (shell, file, git, etc.) AND MCP integration, not MCP-only as this vision proposes.

---

# MCP as pflow's Extension API: A Fundamental Simplification

## The Core Insight

**Custom nodes are obsolete. MCP (Model Context Protocol) is pflow's extension API.**

Every extension to pflow should be an MCP server, not a custom node. This isn't a compromise or integration strategy - it's a fundamental architectural principle that eliminates entire categories of complexity.

## The Problem We're Avoiding

Traditional workflow tools require users to learn proprietary extension APIs:

- **n8n**: Learn their node structure, implement their interface
- **Zapier**: Use their developer platform, follow their patterns
- **GitHub Actions**: Write actions with specific YAML schemas
- **pflow (old thinking)**: Would need custom node API, packaging, distribution

Each tool fractures the ecosystem. A Zapier integration doesn't work in n8n. An n8n node doesn't work in GitHub Actions. Developers must rebuild the same integration for every platform.

## The Solution: MCP as Universal Extension Layer

Instead of building a pflow-specific node API, we declare:

> **Every pflow extension is an MCP server.**

This means:
- No custom node development documentation
- No pflow-specific extension patterns
- No proprietary packaging or distribution
- No lock-in to pflow's ecosystem

## The Transformation

### Before: Multiple Extension Mechanisms
```
Native pflow nodes → Custom prep/exec/post lifecycle
Custom extensions → Learn pflow API → Package → Distribute
External tools → Build wrapper nodes → Maintain forever
MCP servers → Special integration → Treated as second-class
```

### After: One Extension Mechanism
```
Everything → MCP Server → pflow orchestrates
```

## Why This Changes Everything

### 1. AI Agents Become Extension Developers

Any AI that understands MCP can extend pflow:

```bash
# User needs custom functionality
$ claude "Build an MCP server that monitors my Stripe webhooks"
# Claude generates stripe_monitor.py

# User adds to pflow
$ pflow mcp add stripe-monitor -- python stripe_monitor.py

# Immediately available
$ pflow "when stripe payment fails, create support ticket"
```

The user never learns pflow's internals. Claude doesn't need pflow knowledge. It just works.

### 2. Zero Learning Curve for Developers

A developer who wants to extend pflow needs to know:
- ❌ ~~pflow's node lifecycle~~
- ❌ ~~Shared store patterns~~
- ❌ ~~Registry structure~~
- ❌ ~~Template variables~~
- ✅ How to build an MCP server (standard protocol)

Since MCP is becoming the standard for AI-tool interaction, developers learn once, use everywhere.

### 3. Ecosystem Network Effects

Every MCP server built for:
- **Claude Desktop** → works in pflow
- **ChatGPT** → works in pflow
- **pflow** → works everywhere else

This isn't integration - it's ecosystem participation. pflow doesn't build integrations; it orchestrates the world's MCP servers.

### 4. Radical Simplification

pflow's core becomes tiny:

```python
# Essential nodes only
MCPNode          # Executes any MCP server tool
ShellNode        # Command execution
LLMNode          # Intelligence layer
ConditionalNode  # Flow control
LoopNode         # Iteration
```

Everything else - databases, APIs, file systems, cloud services - comes from MCP servers.

## Practical Examples

### Custom Business Logic

**Traditional approach**: Build custom node with business logic
**MCP approach**:
```python
# my_business_logic.py (MCP server)
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("BusinessLogic")

@mcp.tool()
def calculate_customer_score(purchases: int, returns: int) -> float:
    """Calculate customer lifetime value score."""
    return (purchases * 100 - returns * 150) / purchases

# Add to pflow
$ pflow mcp add business -- python my_business_logic.py
```

### Proprietary API Integration

**Traditional approach**: Build wrapper node, handle auth, errors
**MCP approach**: AI generates it in 30 seconds
```bash
$ claude "Create MCP server for my API at api.company.com with Bearer auth"
# Claude generates complete MCP server
# User adds it, done
```

### Database Operations

**Traditional approach**: Build database nodes for each DB type
**MCP approach**: Use existing MCP servers
```bash
$ pflow mcp add postgres -- npx @modelcontextprotocol/postgres
$ pflow mcp add mongo -- npx @modelcontextprotocol/mongodb
$ pflow mcp add mysql -- npx @modelcontextprotocol/mysql
```

## Strategic Positioning

This positions pflow uniquely:

| Platform | Extension Model | Lock-in |
|----------|----------------|---------|
| Zapier | Proprietary apps | High - only works in Zapier |
| n8n | Custom nodes | High - only works in n8n |
| GitHub Actions | Action YAML | High - only works in GitHub |
| **pflow** | **MCP servers** | **None - works everywhere** |

pflow becomes the **orchestration layer** for the MCP ecosystem, not another walled garden.

## The Competitive Moat

Our moat isn't the nodes we build. It's:

1. **Best-in-class orchestration** of MCP tools
2. **Natural language planning** that understands MCP capabilities
3. **Deterministic workflow compilation** from English to execution
4. **CLI-first experience** for developers

Others can copy using MCP servers. They can't copy our orchestration intelligence.

## Implementation Philosophy

### What We Build
- **Orchestration engine** that's excellent
- **Natural language planner** that's intelligent
- **CLI experience** that's delightful
- **Core control flow** that's robust

### What We DON'T Build
- ❌ Database connectors (use MCP servers)
- ❌ API wrappers (use MCP servers)
- ❌ File format parsers (use MCP servers)
- ❌ Cloud service integrations (use MCP servers)

### The Test

Before building any node, ask:
> "Could this be an MCP server instead?"

If yes, don't build the node. Document how to use/build the MCP server.

## User Experience

### For End Users
```bash
# Install any MCP server
$ npm install -g @coolcompany/their-mcp-server

# Add to pflow
$ pflow mcp add coolservice -- their-mcp-server

# Use naturally
$ pflow "fetch data from coolservice and analyze it"
```

### For Developers
```markdown
# How to extend pflow

1. Build an MCP server (any AI can help you)
2. Add it: `pflow mcp add name -- command`
3. There is no step 3
```

### For AI Agents
```python
# AI agents already understand MCP
# No pflow-specific knowledge needed
# They can extend pflow without documentation
```

## The Long-term Vision

pflow becomes the **Unix pipes for MCP tools** - small, focused, exceptional at one thing: orchestrating MCP servers into workflows.

While others build proprietary ecosystems, we build on an open protocol. While others document custom APIs, we point to MCP standards. While others accumulate technical debt with hundreds of custom nodes, we maintain a tiny core.

## The Decision

This isn't a feature decision. It's a philosophy:

> **pflow orchestrates MCP servers. Period.**

Custom nodes are technical debt. MCP servers are assets. Every custom node we don't build is a victory for simplicity.

## Conclusion

By declaring MCP as our sole extension mechanism, we achieve:

- **Radical simplification** - tiny core, huge capability
- **Zero lock-in** - extensions work everywhere
- **AI-native extensibility** - any AI can extend pflow
- **Ecosystem leverage** - inherit all MCP servers
- **Focus** - orchestration, not integration

This isn't just architecture. It's architectural philosophy: **Do one thing excellently (orchestration), let MCP handle everything else.**

The future isn't building more nodes. It's orchestrating the world's MCP servers better than anyone else.