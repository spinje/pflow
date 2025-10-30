# Task 86: MCP Server Discovery and Installation Automation

**Status**: Not Started
**Priority**: High
**Estimated Effort**: 6-12 weeks (depending on scope chosen)
**Dependencies**: None (builds on existing registry system)
**Related Research**: `scratchpads/mcp-cli-gateway-pivot/`

---

## Problem Statement

### The Opportunity

pflow already acts as a lazy loading gateway for MCP servers - Claude Code only sees pflow's minimal interface (~1k tokens) instead of all tool definitions from 10+ MCP servers (50k+ tokens). This solves context bloat for **installed servers**.

However, users face significant friction when trying to **discover and install** servers from the 6,360+ server ecosystem:

1. **Discovery is manual** - Users must browse GitHub, registries, blogs to find relevant servers
2. **Installation is manual** - Users must edit `~/.pflow/mcp-servers.json` directly
3. **Auth configuration is complex** - OAuth flows, external providers (Composio), token management
4. **No programmatic expansion** - AI agents can't discover and install servers on-demand

### Validated Pain Points

**Research evidence** (`scratchpads/mcp-cli-gateway-pivot/`):
- 6,360+ MCP servers exist across 17+ registries (PulseMCP, GitHub MCP Registry, Docker Catalog)
- Users report "MCP servers scattered across numerous registries"
- GitHub MCP Registry launched Oct 2025 (~40 curated servers)
- Composio API enables programmatic server start/auth
- No unified discovery + installation tool exists

### Current vs Missing Capabilities

**What EXISTS today:**

```python
# pflow already has these MCP tools:
registry_discover(task: str) → nodes[]
  # Searches INSTALLED servers in ~/.pflow/mcp-servers.json
  # Returns matching nodes from installed servers only

registry_run(node_type: str, params: dict) → result
  # Executes tools from installed servers
  # Requires server already in ~/.pflow/mcp-servers.json
```

**What's MISSING:**

```python
# Need to add:
mcp_search(query: str) → servers[]
  # Search 6k+ servers from registries (NOT just installed)
  # Return: name, description, transport, auth requirements

mcp_install(server_id: str, config: dict) → result
  # Programmatically add to ~/.pflow/mcp-servers.json
  # Auto-configure stdio command or HTTP endpoint

mcp_auth_setup(server_id: str, credentials: dict) → result
  # Handle OAuth flows with external providers
  # Start remote servers via provider APIs (Composio)
  # Store credentials securely
```

---

## Proposed Solution: Two Scope Options

The implementer should choose scope during planning based on:
- Available time (6-12 weeks)
- User validation priorities
- Competitive timing considerations

### **Option A: Enhanced Discovery (Smaller Scope)**

**Goal**: Make pflow the "MCP package manager" - easy discovery and installation of servers

**What to build:**

1. **Server Registry Integration**
   - Connect to existing registries (GitHub MCP Registry API, PulseMCP, etc.)
   - Unified search across multiple sources
   - Cache registry data locally for performance

2. **Discovery MCP Tools**
   ```python
   mcp_search(query: str, filters: dict) → list[ServerInfo]
     # Search by keyword, category, tags
     # Return: name, description, stars, install_command, auth_required
     # Filter by: transport type, maintained status, quality score

   mcp_describe(server_id: str) → ServerDetails
     # Full metadata: tools available, auth requirements, docs
     # Installation instructions
     # Security/trust signals
   ```

3. **Installation MCP Tools**
   ```python
   mcp_install(server_id: str, config: dict) → InstallResult
     # Auto-update ~/.pflow/mcp-servers.json
     # Detect transport type (stdio/HTTP)
     # Configure basic auth (API keys, tokens)
     # Validate installation

   mcp_uninstall(server_id: str) → bool
     # Remove from ~/.pflow/mcp-servers.json
     # Clean up auth credentials

   mcp_list_installed() → list[ServerInfo]
     # Show installed servers with metadata
     # Include health status, last used, tools count
   ```

4. **Basic Auth Management**
   ```python
   mcp_auth_setup(server_id: str, credentials: dict) → AuthResult
     # Store credentials securely (keyring, env vars)
     # Validate auth works
     # Support: API keys, bearer tokens, basic auth

   mcp_auth_refresh(server_id: str) → AuthResult
     # Handle token refresh for supported providers
   ```

**Integration points:**
- GitHub MCP Registry API (https://github.com/modelcontextprotocol/servers)
- PulseMCP directory (6,360+ servers)
- Docker MCP Catalog (200+ curated)
- OSS Community Registry (1,000+)

**Time estimate**: 6-8 weeks

**Validation criteria:**
- AI agent can discover servers from natural language query
- AI agent can install servers without human JSON editing
- Installation success rate >90% for top 50 servers
- Auth setup works for common providers (GitHub, Composio, etc.)

---

### **Option B: Full Lazy Loading + Auto-Install (Larger Scope)**

**Goal**: Zero-configuration MCP access - servers discovered and installed on-demand during conversation

**Everything from Option A PLUS:**

5. **Universal Tool Discovery**
   ```python
   universal_discover(query: str) → ToolDiscoveryResult
     # Search across ALL servers (installed + uninstalled)
     # For uninstalled: flag as "available but requires install"
     # For installed: return directly
     # Intelligent ranking (quality, relevance, trust)

   discover_and_install(query: str) → ExecutableTools
     # Combined operation: search → rank → prompt user → install → return tools
     # Handles full workflow for AI agents
   ```

6. **Installation Approval Flow**
   - User prompting system (CLI or callback)
   - Security validation before auto-install
   - Trust scoring for servers (GitHub stars, verified publishers, etc.)
   - Sandboxing/permissions model

7. **External Provider Integration**
   ```python
   composio_start_server(app_name: str, credentials: dict) → ServerInfo
     # Use Composio API to start MCP server in cloud
     # Handle OAuth flow
     # Return HTTP endpoint and auth config

   composio_list_available() → list[AppInfo]
     # Show what apps Composio can expose as MCP
   ```

8. **Smart Caching and Preloading**
   - Learn usage patterns (which servers user needs together)
   - Predictive preloading for common workflows
   - Background server health checks
   - Auto-cleanup of unused servers

**Time estimate**: 10-14 weeks

**Validation criteria:**
- Everything from Option A PLUS:
- AI agent can work with uninstalled servers transparently
- Auto-install works with user approval (no manual config)
- Composio integration enables 100+ apps as MCP servers
- Security validation prevents malicious installs

---

## Technical Implementation Details

### Architecture

**Current state:**
```
AI Agent (Claude Code)
  ↓ MCP protocol
pflow MCP Server (11 existing tools + new discovery tools)
  ↓ reads
~/.pflow/mcp-servers.json (manually maintained)
  ↓ spawns/connects to
Installed MCP Servers (stdio or HTTP)
```

**After implementation:**
```
AI Agent (Claude Code)
  ↓ MCP protocol
pflow MCP Server
  ├─ registry_discover() [existing] → search installed servers
  ├─ registry_run() [existing] → execute installed tools
  ├─ mcp_search() [NEW] → search all 6k+ servers
  ├─ mcp_install() [NEW] → auto-add to config
  └─ mcp_auth_setup() [NEW] → configure auth
      ↓
  ┌─────────────┴──────────────┐
  ↓                            ↓
Registry APIs              ~/.pflow/mcp-servers.json
(GitHub, PulseMCP, etc.)   (auto-maintained)
  ↓                            ↓
Server Metadata            Installed MCP Servers
```

### Data Structures

**ServerInfo:**
```python
{
  "id": "github-mcp-server",
  "name": "GitHub MCP Server",
  "description": "Access GitHub APIs via MCP",
  "transport": "stdio",  # or "http", "sse"
  "install_command": "npx @modelcontextprotocol/server-github",
  "auth_required": True,
  "auth_type": "oauth",  # or "api_key", "bearer", "none"
  "tools": ["list_prs", "create_issue", ...],
  "stars": 1234,
  "verified": True,
  "source": "github-mcp-registry",
  "docs_url": "https://...",
  "homepage": "https://..."
}
```

**InstallConfig:**
```python
{
  "server_id": "github-mcp-server",
  "transport": "stdio",
  "command": "npx",
  "args": ["@modelcontextprotocol/server-github"],
  "env": {
    "GITHUB_TOKEN": "${secrets.github_token}"
  },
  # OR for HTTP:
  "url": "https://api.composio.dev/mcp/github",
  "headers": {
    "Authorization": "Bearer ${secrets.composio_api_key}"
  }
}
```

### Registry Integration

**Priority registries to integrate:**

1. **GitHub MCP Registry** (Official, ~40 curated)
   - API: https://github.com/modelcontextprotocol/servers
   - Format: GitHub repo with JSON metadata
   - Quality: Highest (manually curated)
   - Update frequency: Weekly

2. **PulseMCP** (6,360+ servers)
   - URL: https://pulsemcp.com/
   - Format: Web directory (may need scraping or API)
   - Quality: Mixed
   - Update frequency: Daily

3. **Docker MCP Catalog** (200+ verified)
   - API: Docker Hub API
   - Format: Container metadata
   - Quality: High (verified, signed)
   - Integration: `docker mcp` commands

4. **OSS Community Registry** (1,000+)
   - GitHub: Multiple "awesome-mcp-servers" repos
   - Format: Markdown lists, JSON files
   - Quality: Variable
   - Aggregation required

**Implementation approach:**
- Pluggable registry adapters (add new sources easily)
- Local cache with TTL (reduce API calls)
- Unified schema across registries
- Quality scoring/ranking algorithm

### Security Considerations

**Critical requirements:**

1. **Install-time validation**
   - Verify server source (GitHub verified publishers, Docker signed images)
   - Check server reputation (stars, forks, age)
   - Scan for known vulnerabilities (SBOM, CVE databases)
   - Warn on unverified sources

2. **Credential management**
   - NEVER store credentials in plain text
   - Use system keyring (keyring library) or env vars
   - Support secret managers (1Password, Bitwarden)
   - Encrypt sensitive config

3. **Sandboxing (Option B)**
   - Run stdio servers in restricted environment
   - Limit file system access
   - Network isolation options
   - Resource limits (CPU, memory)

4. **User consent**
   - Always prompt before auto-install
   - Show what permissions server requires
   - Display trust signals
   - Allow audit of installed servers

### Integration with Existing Systems

**Leverage existing pflow infrastructure:**

1. **Registry system** (`src/pflow/registry/`)
   - Extend `Registry` class to include remote servers
   - Add `RemoteServerRegistry` class
   - Merge installed + remote in search results

2. **MCP server** (`src/pflow/mcp_server/`)
   - Add new tools to `tools/` directory
   - Follow existing patterns (discovery_tools.py, registry_tools.py)
   - Use shared services layer

3. **Settings system** (`src/pflow/core/settings.py`)
   - Add MCP server credentials to settings
   - Use existing allow/deny patterns
   - Extend for registry configuration

4. **Security utilities** (`src/pflow/core/security_utils.py`)
   - Extend SENSITIVE_KEYS for MCP credentials
   - Add server validation functions

### External API Integration

**Composio API** (if implementing Option B):

```python
# Composio endpoints (research required for exact API)
POST /v1/mcp/servers/start
  # Start MCP server for an app (GitHub, Slack, etc.)
  # Returns: server URL, auth credentials

GET /v1/mcp/servers/list
  # List available apps

POST /v1/mcp/auth/oauth
  # Initiate OAuth flow
  # Handle callback

DELETE /v1/mcp/servers/:id
  # Stop running server
```

**Research needed:**
- Exact Composio API endpoints and authentication
- Rate limits and pricing
- Supported apps and their MCP capabilities
- OAuth flow implementation

---

## Success Criteria

### Phase 1: Server Discovery (Week 1-3)

**Must achieve:**
- [ ] `mcp_search()` tool works with 3+ registries
- [ ] Returns accurate results for common queries ("github", "database", "slack")
- [ ] Cache reduces API calls by 80%+
- [ ] Results include quality scores/trust signals
- [ ] AI agent can discover servers via natural language

**Validation:**
- Query "github automation" returns github-mcp-server in top 3
- Search latency <500ms for cached queries
- 100% of top 50 servers discoverable

### Phase 2: Installation (Week 4-6)

**Must achieve:**
- [ ] `mcp_install()` auto-updates ~/.pflow/mcp-servers.json
- [ ] Supports stdio and HTTP transports
- [ ] Installation success rate >90% for top 20 servers
- [ ] AI agent can install servers without human intervention
- [ ] Validation detects installation failures

**Validation:**
- Install github-mcp-server, verify in config, execute tool successfully
- Install composio HTTP server with auth
- Error handling for missing dependencies (npm, python, etc.)

### Phase 3: Auth Management (Week 7-8)

**Must achieve:**
- [ ] `mcp_auth_setup()` works for common auth types (API key, OAuth, bearer)
- [ ] Credentials stored securely (not plain text)
- [ ] Token refresh works for supported providers
- [ ] AI agent can configure auth with user-provided credentials

**Validation:**
- Configure GitHub token, verify MCP server can authenticate
- Store 5+ credentials, verify keyring/env var storage
- Refresh OAuth token for provider that supports it

### Phase 4 (Option B): Auto-Install Flow (Week 9-14)

**Must achieve:**
- [ ] `universal_discover()` searches installed + uninstalled servers
- [ ] User approval flow works (CLI prompt or callback)
- [ ] Security validation prevents malicious servers
- [ ] Composio integration enables cloud MCP servers
- [ ] End-to-end: query → discover → approve → install → execute

**Validation:**
- AI agent asks about uninstalled server, system prompts user, installs on approval
- Security scan flags suspicious server
- Composio integration: start Slack MCP server, execute tool

---

## Research References

**Market validation:**
- `scratchpads/mcp-cli-gateway-pivot/context-bloat-evaluation-misunderstood.md`
  - 6,360+ servers across 17+ registries
  - "MCP servers scattered across numerous registries"
  - GitHub MCP Registry launched Oct 2025

- `scratchpads/mcp-cli-gateway-pivot/mcp-gateway-competitive-analysis.md`
  - Docker has 200+ curated catalog (competitor benchmark)
  - No unified discovery + installation tool exists
  - 6-12 month competitive window

**Technical validation:**
- Multiple lazy loading proof-of-concepts (lazy-mcp, OpenMCP, MCP-Zero)
- 90-98% token reduction validated
- MCP protocol supports necessary primitives

---

## Open Questions for Implementer

**Before starting, research and decide:**

1. **Scope selection**: Option A (6-8 weeks) or Option B (10-14 weeks)?
   - Consider: competitive timing (6-12 month window)
   - Consider: user validation priorities
   - Recommendation: Start with Option A, expand if validated

2. **Registry priority**: Which registries to integrate first?
   - GitHub MCP Registry (official, small, high quality)
   - PulseMCP (large, comprehensive)
   - Docker Catalog (verified, container-based)
   - Recommendation: GitHub first, then PulseMCP

3. **Composio API details**: What's actually available?
   - Research Composio API documentation
   - Understand OAuth flow and server lifecycle
   - Determine if programmatic server start is feasible
   - May need to contact Composio for API access

4. **Security model**: How strict should validation be?
   - Auto-install with warnings vs require approval?
   - Sandboxing implementation approach
   - Trust scoring algorithm
   - Recommendation: Cautious (require approval) initially

5. **Credential storage**: What's the best approach?
   - System keyring (cross-platform challenges)
   - Encrypted config file
   - Environment variables only
   - Integration with 1Password/Bitwarden
   - Recommendation: Start with env vars, add keyring later

6. **Cache strategy**: How to keep registry data fresh?
   - TTL duration (24 hours? 1 week?)
   - Incremental updates vs full refresh
   - Storage location (~/.pflow/cache/registries.db?)
   - Recommendation: 24-hour TTL, SQLite cache

---

## Implementation Approach (Suggested)

### Week 1-2: Research and Planning
- Research registry APIs (GitHub, PulseMCP, Docker)
- Research Composio API (if doing Option B)
- Design data models and tool interfaces
- Set up dev environment for testing with real servers
- Create detailed implementation plan

### Week 3-4: Registry Integration
- Implement registry adapters (GitHub, PulseMCP)
- Build unified search API
- Add caching layer
- Implement quality scoring
- Test with real queries

### Week 5-6: Installation Automation
- Implement `mcp_install()` tool
- Auto-configuration for stdio and HTTP
- Validation and error handling
- Test with top 20 servers
- Handle edge cases (missing deps, network errors)

### Week 7-8: Auth Management
- Implement `mcp_auth_setup()` tool
- Credential storage (env vars or keyring)
- OAuth flow for common providers
- Token refresh logic
- Security audit

### Week 9-10 (Option B): Universal Discovery
- Implement `universal_discover()` tool
- Merge installed + uninstalled results
- Intelligent ranking algorithm
- User approval flow design

### Week 11-12 (Option B): Auto-Install Flow
- Security validation system
- Trust scoring implementation
- End-to-end testing
- Edge case handling

### Week 13-14 (Option B): Composio Integration
- API integration
- OAuth flow implementation
- Server lifecycle management
- Testing with multiple apps

---

## Testing Strategy

### Unit Tests
- Registry adapter tests (mock API responses)
- Installation logic tests (mock file system)
- Auth credential storage tests
- Tool interface tests (mock MCP calls)

### Integration Tests
- Real registry API calls (cached for CI)
- Install top 10 servers in test environment
- Auth flow with test credentials
- End-to-end: search → install → execute

### Manual Testing
- AI agent interaction testing
- Edge cases (network failures, auth errors)
- Security validation (try installing malicious server)
- Performance testing (search latency, install time)

---

## Risks and Mitigations

### Risk 1: Registry API Changes
**Likelihood**: Medium
**Impact**: High (breaks discovery)
**Mitigation**:
- Use official APIs where available
- Adapter pattern for easy updates
- Comprehensive error handling
- Regular monitoring

### Risk 2: Composio API Access
**Likelihood**: Medium
**Impact**: Medium (blocks Option B cloud integration)
**Mitigation**:
- Research API availability early
- Contact Composio if needed
- Have fallback plan (manual cloud server setup)

### Risk 3: Installation Failures
**Likelihood**: High (many servers, various dependencies)
**Impact**: Medium (poor UX)
**Mitigation**:
- Robust error detection and messaging
- Provide manual installation fallback
- Test with diverse servers
- Clear dependency requirements

### Risk 4: Security Vulnerabilities
**Likelihood**: Medium
**Impact**: High (malicious server compromise)
**Mitigation**:
- Conservative approval flow
- Security scanning before install
- Sandboxing (Option B)
- Clear trust indicators

---

## Documentation Requirements

**Must create:**
1. User guide: How to discover and install servers
2. Developer guide: How to add new registry adapters
3. Security guide: Trust model and best practices
4. API reference: New MCP tools documentation
5. Integration guide: Composio and other providers

**Update existing:**
- `architecture/features/mcp-integration.md` - Add discovery and installation sections
- `README.md` - Add server discovery examples
- `src/pflow/mcp_server/resources/instructions/` - Update agent instructions

---

## Definition of Done

**Task is complete when:**

1. ✅ Chosen scope (A or B) fully implemented
2. ✅ All success criteria met
3. ✅ Test coverage >80% for new code
4. ✅ Documentation complete
5. ✅ Manual testing with AI agent successful
6. ✅ Security validation passed
7. ✅ Performance benchmarks met (search <500ms, install <30s)
8. ✅ Top 20 servers installable with >90% success rate
9. ✅ Code review and approval
10. ✅ Merged to main branch

**Acceptance test:**
```
User to AI agent: "I need to analyze my GitHub pull requests"
AI agent: Uses mcp_search to find github-mcp-server
AI agent: Uses mcp_install to add it (with user approval)
AI agent: Uses registry_run to execute list_prs
Result: PRs returned successfully, zero manual configuration required
```

---

## Notes for Implementer

**Context:**
- pflow already solves context bloat for installed servers (lazy loading gateway works)
- This task is about making server discovery and installation easier
- Market research validates 6-12 month competitive window
- Speed to market is critical (competitors could add similar features)

**Recommendations:**
- Start with Option A (smaller scope, faster validation)
- Focus on top 50 servers (80/20 rule)
- Prioritize UX and reliability over feature completeness
- Ship iteratively (registry integration → installation → auth → advanced features)
- Validate with real users after each phase

**Resources:**
- Research docs: `scratchpads/mcp-cli-gateway-pivot/`
- Existing MCP tools: `src/pflow/mcp_server/tools/`
- Registry system: `src/pflow/registry/`
- MCP integration: `architecture/features/mcp-integration.md`

**Questions?**
- Discuss scope trade-offs with team
- Research Composio API before committing to Option B
- Validate security approach with security expert if available
- Consider user testing plan for each phase
