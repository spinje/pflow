# Task 97: Implement OAuth Authentication for Remote MCP Servers

## Description
Enable pflow to authenticate with remote MCP servers using OAuth 2.1. This allows users to connect pflow to OAuth-protected MCP servers (like Heptabase, GitHub MCP, Sentry, etc.) by running a simple CLI command that triggers a browser-based OAuth flow, stores credentials locally, and uses them transparently for subsequent MCP calls.

## Status
not started

## Dependencies
None confirmed. However, the implementation should integrate with:
- pflow's existing HTTP client infrastructure (if any)
- pflow's existing CLI command patterns
- pflow's existing configuration/storage patterns

**Open questions** (see Details): The implementing agent should investigate what existing pflow patterns exist before starting implementation.

## Priority
high

## Details

### Context and Architecture

pflow runs locally on the user's machine as a CLI tool. It acts as an intermediary between AI agents and MCP servers:

```
┌──────────────┐  stdio   ┌─────────────────┐  HTTP+OAuth  ┌─────────────────┐
│  AI Agent    │──────────│  pflow (local)  │──────────────│  Remote MCP     │
│  (trusted)   │          │  CLI tool       │              │  Server         │
└──────────────┘          └─────────────────┘              └─────────────────┘
                                  │
                                  ▼
                          ~/.pflow/auth/
                          (credential storage)
```

**Key architectural facts:**
- No authentication needed between AI agent and pflow (both local, stdio transport)
- OAuth authentication required between pflow and remote MCP servers (HTTP transport)
- pflow acts as an **MCP client** implementing the client-side of the MCP Authorization spec
- Credentials stored locally, managed entirely by pflow

### User Experience Goal

```bash
pflow mcp add heptabase https://api.heptabase.com/mcp
# Browser opens → user logs in → clicks "Authorize" → browser shows success
# CLI confirms: "✓ Connected to heptabase"

# Future commands use stored credentials transparently
pflow run my-workflow  # Tools from heptabase work without re-auth
```

### Protocol Requirements

pflow must implement **OAuth 2.1 with PKCE** as specified by the MCP Authorization specification (June 2025 revision). The flow involves:

1. **Discovery** - Fetch metadata from `.well-known` endpoints
2. **Dynamic Client Registration** (if supported) - Register pflow as OAuth client
3. **PKCE Generation** - Create code_verifier and code_challenge
4. **Browser Authorization** - Open browser, user grants permission
5. **Callback Handling** - Receive auth code via local HTTP server
6. **Token Exchange** - Exchange code for access/refresh tokens
7. **Token Storage** - Persist credentials locally
8. **Token Refresh** - Automatically refresh expired tokens

### Implementation Components Needed

```
pflow/
├── auth/
│   ├── __init__.py
│   ├── discovery.py      # OAuth/MCP metadata discovery
│   ├── pkce.py           # PKCE generation
│   ├── client.py         # OAuth client (DCR, token exchange)
│   ├── callback.py       # Local HTTP callback server
│   ├── storage.py        # Credential storage
│   └── manager.py        # High-level auth orchestration
```

### Critical Implementation Details

**PKCE is mandatory** - Must generate cryptographically random code_verifier using `secrets` module, derive code_challenge via SHA256.

**Resource Indicators (RFC 8707) are mandatory** - The `resource` parameter must be included in auth requests to bind tokens to specific MCP servers.

**Most OAuth providers don't support DCR** - Google, GitHub, Azure AD do not support Dynamic Client Registration. pflow must handle this gracefully (prompt user for pre-registered client credentials).

**Callback server** - Must run temporary HTTP server on localhost to receive OAuth redirect. Handle port conflicts (try fixed port, fall back to random).

### Decisions Required Before/During Implementation

The following decisions affect implementation. They should be resolved by discussing with the user:

1. **Storage location**: `~/.pflow/auth/` vs `~/.config/pflow/auth/` vs OS keychain
2. **Storage format**: Single JSON file vs SQLite vs encrypted JSON
3. **Callback port strategy**: Fixed port (e.g., 8456) vs dynamic vs fixed-with-fallback
4. **Non-DCR handling**: How to handle servers that don't support DCR
5. **Token refresh strategy**: Refresh on expiry vs proactive vs refresh-when-near-expiry
6. **Browser opening**: Auto-open vs print URL vs try-auto-then-fallback
7. **CLI command syntax**: Exact commands and flags
8. **Multiple accounts**: Support from v1 or defer?
9. **Timeout values**: Callback wait time, HTTP timeouts
10. **Error messages**: Exact wording for various error conditions

### Reference Implementations

Study these for implementation patterns:

- **`mcp-remote`** (JS): https://github.com/geelen/mcp-remote - Most directly relevant, handles OAuth for stdio-to-HTTP bridging
- **TypeScript SDK**: https://github.com/modelcontextprotocol/typescript-sdk - Official OAuth client helpers
- **FastMCP** (Python): https://github.com/jlowin/fastmcp - Python patterns, stores tokens in `~/.fastmcp/oauth-mcp-client-cache/`

### Specification Document

A comprehensive specification document has been created and is available at:
`.taskmaster/tasks/task_96/starting-context/pflow-mcp-oauth-spec.md`

This document contains:
- Complete protocol flow with sequence diagrams
- Python code patterns for each component
- All 10 decisions with options and tradeoffs
- Security considerations
- Error handling matrix
- Sample credential storage format
- Testing strategy

**The implementing agent should read this spec document before starting.**

### Open Questions Requiring Investigation

Before implementing, the agent should investigate:

1. What is pflow's existing config/storage pattern? Auth storage should follow it.
2. Does pflow have existing HTTP client infrastructure? Auth should integrate.
3. What CLI patterns exist in pflow? `pflow mcp add` should follow conventions.
4. What's the expected scale? (1-5 servers vs 50+) Affects storage design.

## Test Strategy

### Unit Tests
- PKCE generation (verifier format: 43-128 chars, challenge derivation correct)
- Metadata parsing (handle missing fields, malformed JSON)
- Token storage read/write (round-trip, file permissions)
- Credential expiry checking (edge cases around expiry time)
- State parameter generation and validation

### Integration Tests
- Discovery flow against mock MCP server
- Full OAuth flow with test authorization server (Auth0 free tier)
- Token refresh flow
- Error handling (401 responses, network errors, timeouts)
- Callback server (port binding, request handling, timeout)

### Manual Testing
- Test with MCP Inspector as verification tool
- Test with real OAuth-protected MCP servers:
  - Sentry MCP (https://mcp.sentry.dev/mcp)
  - Make.com MCP
  - Any server supporting OAuth

### Test Scenarios
- Happy path: Full OAuth flow succeeds
- DCR not supported: Falls back to manual client credentials
- Token expired: Refresh succeeds transparently
- Refresh token expired: Prompts for re-authentication
- User cancels auth: Clean error message
- Callback timeout: Clean error message
- Network error during discovery: Retry then fail clearly
- Invalid server URL: Clear error message
- Multiple servers: Each has isolated credentials
