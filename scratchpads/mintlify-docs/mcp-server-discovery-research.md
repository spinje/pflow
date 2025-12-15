# Research Task: Best Resources for Finding MCP Servers

## Context

We're writing user documentation for pflow, a CLI tool that lets AI agents build and run workflows. pflow supports MCP (Model Context Protocol) servers as a way to add external tools (GitHub, Slack, databases, etc.).

In our documentation (`docs/guides/adding-mcp-servers.mdx`), we currently link to:
- [mcp.run](https://mcp.run)
- [smithery.ai](https://smithery.ai)

**Problem**: We don't know if these are the best/most authoritative resources. We need to verify what we should recommend to users.

## Research Questions

### 1. Official MCP Resources
- What does the official MCP specification/documentation recommend?
- Is there an official MCP server registry maintained by Anthropic?
- What is modelcontextprotocol.io and is it the canonical source?
- Are there official MCP servers published by Anthropic?

### 2. Third-Party Aggregators
- What is mcp.run? Who runs it? Is it reliable?
- What is smithery.ai? Who runs it? Is it reliable?
- Are there other MCP server directories/aggregators?
- How do these compare in terms of:
  - Number of servers listed
  - Quality/verification of listings
  - Update frequency
  - Community trust

### 3. GitHub/npm Sources
- Are MCP servers typically published to npm under specific namespaces?
- Is there a GitHub org or topic for MCP servers?
- What's the @modelcontextprotocol npm namespace? Is it official?

### 4. Claude Desktop / Claude Code
- Where do Claude Desktop users find MCP servers?
- What does Anthropic's documentation recommend?
- Is there an "official" list somewhere?

### 5. Community Resources
- Are there community-maintained lists (awesome-mcp-servers, etc.)?
- Reddit/Discord communities with curated lists?
- Blog posts or guides that aggregate MCP servers?

## What We Need to Decide

After research, we need to recommend ONE or TWO resources that are:
1. **Authoritative** - Official or well-maintained
2. **Comprehensive** - Good coverage of available servers
3. **Reliable** - Won't disappear or become outdated
4. **Safe** - Not promoting malicious or low-quality servers

## Current State in Our Docs

```markdown
<Note>
Find more MCP servers at [mcp.run](https://mcp.run) and [smithery.ai](https://smithery.ai).
</Note>
```

We may need to change this to:
- Link to official resources only
- Link to one aggregator we've verified
- Link to GitHub/npm search patterns
- Remove the links entirely and just say "search for MCP servers"
- Some combination

## Output Expected

1. Summary of findings for each research question
2. Recommendation for what to link in our docs
3. Brief rationale for the recommendation
4. Any caveats or warnings we should include

## Additional Context

- pflow is pre-release, targeting developers comfortable with CLI
- Our users are likely also Claude Desktop / Claude Code users
- We want to be helpful but not direct users to unreliable sources
- pflow cloud (future) will have its own MCP server discovery, but that's not available yet
