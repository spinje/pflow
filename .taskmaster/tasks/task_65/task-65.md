# Task 65: MCP Gateway Integration Support

## ID
65

## Title
MCP Gateway Integration Support

## Description
Enhance pflow to provide first-class support for MCP gateways (Docker MCP Gateway, IBM Context Forge) that aggregate multiple MCP services behind a single endpoint. This enables OAuth authentication, service aggregation, and enterprise features without requiring direct OAuth implementation in pflow.

## Status
not started

## Dependencies
- Task 47: Integrate MCP solution with Composio - The HTTP transport implementation from Task 47 provides the foundation for gateway connections. Gateways communicate over HTTP, so this is a prerequisite.

## Priority
medium

## Details
MCP gateways act as "AI service meshes" that sit between pflow and multiple MCP services, providing unified endpoints, OAuth handling, container isolation, and enterprise observability. Our research shows that pflow's current HTTP transport (from Task 47) is already gateway-compatible - gateways appear as standard HTTP MCP servers to pflow.

### Current State
- HTTP transport fully supports gateway connections without modifications
- Gateways aggregate tools from multiple services transparently
- Tool discovery and execution work through standard MCP protocol
- Authentication to gateways uses our existing bearer/API key support

### Proposed Enhancements

#### Phase 1: Gateway Documentation and Testing
- Create comprehensive documentation for gateway setup with pflow
- Test integration with Docker MCP Gateway
- Test integration with IBM Context Forge (if Linux available)
- Create example configurations for common gateway scenarios

#### Phase 2: Gateway-Aware Features (Optional)
- Add metadata to show which backend service each tool originates from
- Implement gateway health check monitoring
- Add service filtering during tool discovery (e.g., only sync GitHub tools)
- Display gateway information in `pflow mcp list` output

#### Phase 3: Gateway-Specific CLI Commands
- Add `pflow mcp gateway` command group for gateway-specific operations
- Implement `pflow mcp gateway test` to validate gateway connectivity
- Add `pflow mcp gateway services` to list backend services
- Create setup wizards for common gateways (Docker, IBM)

### Key Benefits
- **OAuth without implementation**: Gateways handle OAuth flows for GitHub, Google, Slack, etc.
- **Single endpoint**: One URL and one token provide access to many services
- **Enterprise features**: Container isolation, monitoring, rate limiting
- **Service aggregation**: All tools from all services appear in one catalog

### Technical Considerations
- Zero code changes required for basic gateway support (already works)
- Gateways use standard MCP protocol over HTTP transport
- Tool naming convention `mcp-{gateway}-{tool}` works perfectly
- Gateway tokens can provide access to multiple backend services

### Gateway Options
1. **Docker MCP Gateway**: Production-ready, Docker Desktop integration, container isolation
2. **IBM Context Forge**: Advanced features (federation, observability), alpha/beta status
3. **Custom gateways**: Any HTTP server implementing MCP protocol with aggregation

## Test Strategy
Testing will validate gateway integration across different gateway implementations:

### Unit Tests
- Mock gateway responses with aggregated tool lists
- Test tool routing through gateway prefixes
- Verify authentication token handling for gateways

### Integration Tests
- Set up local Docker MCP Gateway for testing
- Test tool discovery from multiple backend services
- Verify tool execution routing to correct services
- Test gateway-specific error scenarios (service down, auth failures)

### Manual Testing
- Document setup process for Docker MCP Gateway
- Test with real services (GitHub, Slack if available)
- Verify OAuth flow works through gateway
- Test performance with multiple backend services

### Test Scenarios
- Gateway with 3+ backend services
- Mixed authentication (some OAuth, some API key)
- Service failure handling (one service down)
- Token refresh and session management
- Large tool catalogs (100+ tools)