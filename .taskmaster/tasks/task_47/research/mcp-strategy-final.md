# pflow MCP Strategy: Final Architecture

## Executive Summary

pflow uses a dual strategy for MCP (Model Context Protocol) integration:
- **CLI**: Pure local MCP servers, user-managed, free forever
- **Cloud**: Managed MCP via Composio partnership, one-click OAuth, subscription model

This document represents the final architectural decision after evaluating all options.

## The Two Products

### pflow CLI (Developers)
```bash
# Local MCP server execution
$ pflow mcp add github -- npx @modelcontextprotocol/github
$ export GITHUB_TOKEN=xxx
$ pflow "create github issue about bug"
```

**Characteristics:**
- Runs entirely on user's machine
- User manages authentication (env vars, config files)
- Free forever
- Full control and privacy
- No external dependencies

### pflow Cloud (Everyone Else)
```python
# One-click OAuth via Composio
User: "Connect GitHub"
pflow: [OAuth flow via Composio]
User: [Authorizes]
pflow: "GitHub connected!"
```

**Characteristics:**
- Managed MCP servers via Composio
- One-click OAuth for all services
- No technical knowledge required
- Subscription-based ($19-99/month)
- Enterprise features available

## Why This Strategy

### The Authentication Reality

We evaluated three approaches for cloud users:

1. **"Bring Your Own OAuth"** ❌
   - Users create OAuth apps themselves
   - Configure callback URLs
   - Manage secrets
   - **Result**: Nobody can do this except developers

2. **API Keys** ❌
   - Users find and create personal access tokens
   - Different process for every service
   - Still too complex for non-technical users
   - **Result**: High friction, low adoption

3. **Managed OAuth via Partner** ✅
   - Click "Connect Service"
   - Standard OAuth flow
   - Partner handles token management
   - **Result**: Actual usable experience

### The Build vs Partner Decision

**Building OAuth ourselves:**
- 3-6 months implementation
- Ongoing security responsibility
- Token storage and refresh logic
- Rate limiting and error handling
- Distraction from core value

**Using Composio:**
- 1 week integration
- 100+ services ready
- They handle security
- They handle maintenance
- We focus on orchestration

## Implementation Architecture

### CLI Architecture
```python
# Everything runs locally
class MCPNode:
    def exec(self):
        # Start local MCP server
        process = subprocess.Popen(["npx", "@modelcontextprotocol/github"])
        # Communicate via stdio
        result = process.communicate(json_rpc_request)
        return result
```

### Cloud Architecture
```python
# MCP servers run via Composio
class CloudMCPNode:
    def exec(self):
        if self.is_cloud_execution:
            # Use Composio API
            return composio.execute_tool(
                user_id=self.user_id,
                tool=self.tool,
                params=self.params
            )
        else:
            # Fall back to local execution
            return super().exec()
```

### Registry Structure

Both CLI and Cloud use the same registry entries:
```json
{
  "mcp-github-create-issue": {
    "module": "pflow.mcp.node",
    "class_name": "MCPNode",
    "mcp_config": {
      "server": "github",
      "tool": "create-issue"
    }
  }
}
```

The execution layer determines whether to use local or cloud MCP.

## Partner Selection: Composio

After evaluating all options (Klavis, Zapier MCP, Pipedream, etc.), Composio is the best fit:

### Why Composio

1. **Agent-Native**: Built specifically for AI agents, not retrofitted iPaaS
2. **100+ MCP Servers**: More than Klavis, focused selection vs Zapier's 8000
3. **Reasonable Pricing**: Free tier available, scales with usage
4. **Good Documentation**: Established with clear examples
5. **Fast Response Times**: Critical for workflow execution

### Integration Plan

**Phase 1 (Pre-Launch):**
- Test Composio integration locally
- Understand pricing model
- Build prototype cloud wrapper

**Phase 2 (Cloud Beta):**
- Start with Composio free tier
- Support top 10 most requested services
- Gather usage data

**Phase 3 (Scale):**
- Negotiate volume pricing
- Consider direct implementation for top 3 services
- Maintain Composio for long tail

## Pricing Strategy

### CLI: Free Forever
- Drives adoption
- Builds developer credibility
- Creates upgrade path to cloud

### Cloud: Simple Tiers

```yaml
Hobby (Free):
  - 10 workflows/day
  - 3 MCP connections
  - Community support

Pro ($19/month):
  - Unlimited workflows
  - 10 MCP connections
  - Email support

Team ($79/month):
  - Everything in Pro
  - Unlimited MCP connections
  - Team sharing
  - Priority support

Enterprise (Custom):
  - SSO, audit logs
  - Custom MCP servers
  - SLA
```

## Migration Path

Users can move between CLI and Cloud:

1. **Start on CLI** (free, local)
2. **Hit limitations** (want OAuth simplicity, team features)
3. **Upgrade to Cloud** (seamless migration)
4. **Export back to CLI** (no lock-in)

## Risk Mitigation

### Composio Dependency
- **Risk**: Service changes or shuts down
- **Mitigation**: Abstract interface, can swap providers
- **Backup**: Build OAuth for top 3 services if needed

### Pricing Changes
- **Risk**: Composio raises prices
- **Mitigation**: Negotiate long-term rates early
- **Backup**: Pass through costs or build critical services

### Performance
- **Risk**: Network latency for cloud execution
- **Mitigation**: Cache connections, optimize API calls
- **Backup**: Offer local execution option for Pro users

## Success Metrics

### CLI Success
- GitHub stars
- Weekly active users
- Workflow executions/day
- Community contributions

### Cloud Success
- Conversion rate (CLI → Cloud)
- Monthly recurring revenue
- Churn rate
- Services connected per user

## Timeline

**Now - Week 2:**
- Complete local MCP implementation
- Test Composio integration
- Choose between Composio and Klavis

**Week 3-4:**
- Ship CLI with local MCP
- Launch landing page with waitlist
- Begin cloud beta development

**Month 2:**
- Launch cloud beta with Composio
- Onboard first 100 users
- Gather feedback

**Month 3-6:**
- Iterate based on usage
- Add most requested MCP servers
- Optimize pricing

## The Final Word

This dual strategy serves both audiences without compromise:
- **Developers** get the pure, local, free tool they expect
- **Non-developers** get the simple, managed experience they need
- **pflow** focuses on orchestration excellence, not auth infrastructure

The key insight: These aren't competing products. They're complementary offerings that serve different users with different needs, united by the same powerful orchestration engine.

## Decision Made

✅ **CLI**: Pure local MCP, ships immediately
✅ **Cloud**: Composio partnership for managed MCP
✅ **Focus**: Orchestration excellence, not integration building

This is the final architecture. Execute against this plan.