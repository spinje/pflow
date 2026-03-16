# Vision Documents

> **⚠️ These documents describe potential FUTURE directions, NOT current implementation.**

This directory contains strategic vision and aspirational architecture documents. They inform future decisions but do NOT describe what currently exists.

## Before Reading These Documents

1. **Current architecture**: See `architecture/architecture.md`
2. **Current project status**: See root `CLAUDE.md`
3. **These may contradict current implementation** - that's intentional; they're aspirational

## Documents

| File | Purpose | Key Caveat |
|------|---------|------------|
| `AI-Agents-Need-Hands.md` | Marketing vision for workflow value | Presents implemented features as future possibilities |
| `mcp-as-extension-api.md` | Future MCP-only extension philosophy | Current pflow uses hybrid approach (platform nodes + MCP) |
| `north-star-examples.md` | Natural-language workflow examples | Uses `>>` CLI syntax that was never implemented |

## For AI Agents

Read these for design philosophy context, but **always verify technical claims against current codebase** before implementing features. Key reality checks:

1. **Platform nodes exist**: pflow has 30+ platform nodes (shell, file, git, etc.) - not MCP-only as some vision docs suggest
2. **CLI syntax**: pflow uses `pflow workflow.pflow.md` and `pflow saved-name`, NOT `node >> node >> node`
3. **Natural-language workflow generation**: Treat these examples as design intent, not current CLI guidance
4. **MCP integration**: MCP is implemented (both client and server), but as one option among several, not the sole extension mechanism
