# pflow MCP OAuth Implementation Specification

## Document Purpose

This document provides complete context for implementing OAuth authentication for remote MCP servers in pflow. It is intended to be self-contained—another developer or AI agent should be able to implement this feature using only this document.

---

## 1. Architectural Context

### 1.1 What pflow Is

pflow is a Python CLI tool that acts as a deterministic workflow engine. It compiles AI reasoning into reusable JSON artifacts. Users run pflow locally on their machines.

### 1.2 Where pflow Sits in the MCP Ecosystem

```
┌──────────────┐  stdio   ┌─────────────────┐  HTTP+OAuth  ┌─────────────────┐
│  AI Agent    │──────────│  pflow (local)  │──────────────│  Remote MCP     │
│  (Claude,    │          │  CLI tool       │              │  Server         │
│  Cursor,     │          │                 │              │  (Heptabase,    │
│  custom)     │          │                 │              │   GitHub, etc)  │
└──────────────┘          └─────────────────┘              └─────────────────┘
                                  │
                                  ▼
                          ~/.pflow/auth/
                          (credential storage)
```

**Key architectural facts:**

1. AI agents connect to pflow via stdio (local process). No authentication needed on this boundary—both run on the user's machine with user's permissions.

2. pflow connects to remote MCP servers via HTTP (Streamable HTTP or SSE transport). This boundary requires OAuth authentication.

3. pflow acts as an **MCP client** when talking to remote servers. It must implement the client-side of the MCP Authorization specification.

4. Credentials are stored locally. pflow is the credential manager for all connected MCP servers.

### 1.3 User Experience Goal

```bash
# User adds a remote MCP server
pflow mcp add heptabase https://api.heptabase.com/mcp

# Browser opens automatically
# User logs in to Heptabase, clicks "Authorize"
# Browser shows "Authorization successful, you can close this window"
# CLI confirms: "✓ Connected to Heptabase"

# Future commands use stored credentials transparently
pflow run my-workflow  # Tools from Heptabase work without re-auth
```

This mirrors the UX of `claude mcp add --transport http` in Claude Code.

---

## 2. MCP Authorization Protocol

### 2.1 Specification Version

The MCP Authorization specification was significantly revised in **June 2025**. Key changes:

- MCP servers are now formally classified as **OAuth Resource Servers** (not Authorization Servers)
- **Resource Indicators (RFC 8707)** are mandatory
- Clear separation between MCP server and Authorization Server roles

The current spec is at: https://modelcontextprotocol.io/specification/draft/basic/authorization

### 2.2 Protocol Overview

MCP uses **OAuth 2.1 with PKCE**. The flow has these phases:

1. **Discovery** - Client learns where to authenticate
2. **Registration** - Client registers itself (if DCR supported)
3. **Authorization** - User grants permission via browser
4. **Token Exchange** - Client exchanges auth code for tokens
5. **Authenticated Requests** - Client uses Bearer token for MCP calls
6. **Token Refresh** - Client refreshes expired tokens

### 2.3 Discovery Phase (Steps 1-4)

When pflow first connects to an MCP server:

```
pflow                           MCP Server                    Auth Server
  │                                 │                              │
  │ 1. GET /mcp (no auth)           │                              │
  │────────────────────────────────>│                              │
  │                                 │                              │
  │ 2. 401 Unauthorized             │                              │
  │    WWW-Authenticate: Bearer     │                              │
  │    resource_metadata="/.well-known/oauth-protected-resource"   │
  │<────────────────────────────────│                              │
  │                                 │                              │
  │ 3. GET /.well-known/oauth-protected-resource                   │
  │────────────────────────────────>│                              │
  │                                 │                              │
  │ 4. Protected Resource Metadata  │                              │
  │    { authorization_servers: ["https://auth.example.com"] }     │
  │<────────────────────────────────│                              │
  │                                 │                              │
  │ 5. GET /.well-known/oauth-authorization-server                 │
  │────────────────────────────────────────────────────────────────>
  │                                                                │
  │ 6. Authorization Server Metadata                               │
  │    { authorization_endpoint, token_endpoint,                   │
  │      registration_endpoint, scopes_supported, ... }            │
  │<────────────────────────────────────────────────────────────────
```

**Protected Resource Metadata (RFC 9728)** - Served by MCP server:
```json
{
  "resource": "https://api.heptabase.com/mcp",
  "authorization_servers": ["https://auth.heptabase.com"],
  "scopes_supported": ["read", "write"],
  "bearer_methods_supported": ["header"]
}
```

**Authorization Server Metadata (RFC 8414)** - Served by Auth server:
```json
{
  "issuer": "https://auth.heptabase.com",
  "authorization_endpoint": "https://auth.heptabase.com/oauth/authorize",
  "token_endpoint": "https://auth.heptabase.com/oauth/token",
  "registration_endpoint": "https://auth.heptabase.com/oauth/register",
  "scopes_supported": ["read", "write", "offline_access"],
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "code_challenge_methods_supported": ["S256"],
  "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"]
}
```

### 2.4 Dynamic Client Registration (Optional)

If the auth server supports DCR (RFC 7591), pflow can register itself:

```
POST /oauth/register
Content-Type: application/json

{
  "redirect_uris": ["http://127.0.0.1:8456/callback"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "none",
  "client_name": "pflow"
}
```

Response:
```json
{
  "client_id": "abc123",
  "client_secret": null,
  "redirect_uris": ["http://127.0.0.1:8456/callback"],
  "grant_types": ["authorization_code", "refresh_token"]
}
```

**Critical Reality:** Most OAuth providers do NOT support DCR:

| Provider | DCR Support |
|----------|-------------|
| Auth0 | Yes (requires config) |
| WorkOS | Yes |
| Stytch | Yes |
| Descope | Yes |
| Google | **No** |
| GitHub | **No** |
| Azure AD | **No** |
| AWS Cognito | **No** |

For servers that don't support DCR, pflow needs an alternative:
- Accept pre-registered client credentials from user
- Use static client metadata
- Some servers may provide a default "public client" ID

### 2.5 PKCE (Proof Key for Code Exchange)

PKCE is **mandatory** in OAuth 2.1. It prevents authorization code interception.

**Generate PKCE values:**
```python
import secrets
import hashlib
import base64

def generate_pkce():
    # code_verifier: 43-128 character random string
    code_verifier = secrets.token_urlsafe(32)  # 43 chars

    # code_challenge: SHA256 hash, base64url encoded
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode()

    return code_verifier, code_challenge
```

### 2.6 Authorization Phase

pflow opens the user's browser to the authorization endpoint:

```
https://auth.heptabase.com/oauth/authorize?
  response_type=code
  &client_id=abc123
  &redirect_uri=http://127.0.0.1:8456/callback
  &code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM
  &code_challenge_method=S256
  &scope=read+write+offline_access
  &resource=https://api.heptabase.com/mcp
  &state=xyz789
```

**Parameters:**
- `response_type=code` - Authorization code flow
- `client_id` - From DCR or pre-registered
- `redirect_uri` - Local callback server
- `code_challenge` - PKCE challenge
- `code_challenge_method=S256` - Always SHA256
- `scope` - Requested permissions
- `resource` - **Required by MCP spec (RFC 8707)** - The MCP server URL
- `state` - CSRF protection, random string

### 2.7 Callback Handling

pflow must run a temporary local HTTP server to receive the callback:

```python
# User completes auth in browser
# Browser redirects to:
# http://127.0.0.1:8456/callback?code=AUTH_CODE&state=xyz789

# pflow's callback server receives this, extracts code and state
```

**Callback server requirements:**
- Listen on localhost (127.0.0.1 or localhost)
- Port can be fixed or dynamic (if fixed port busy, pick another)
- Serve a success HTML page to user
- Extract `code` and `state` from query params
- Verify `state` matches what was sent
- Shut down after receiving callback (or timeout)

### 2.8 Token Exchange

Exchange authorization code for tokens:

```
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=AUTH_CODE
&redirect_uri=http://127.0.0.1:8456/callback
&client_id=abc123
&code_verifier=dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk
&resource=https://api.heptabase.com/mcp
```

Response:
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4...",
  "scope": "read write offline_access"
}
```

### 2.9 Authenticated MCP Requests

All subsequent requests include the token:

```
POST /mcp
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
Content-Type: application/json

{"jsonrpc": "2.0", "method": "tools/list", "id": 1}
```

### 2.10 Token Refresh

When access token expires, use refresh token:

```
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token
&refresh_token=dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4...
&client_id=abc123
&resource=https://api.heptabase.com/mcp
```

Response contains new access_token (and possibly new refresh_token).

---

## 3. Implementation Requirements

### 3.1 Core Components Needed

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

### 3.2 Discovery Module

```python
# discovery.py

@dataclass
class ProtectedResourceMetadata:
    resource: str
    authorization_servers: list[str]
    scopes_supported: list[str] | None = None
    bearer_methods_supported: list[str] | None = None

@dataclass
class AuthServerMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None = None
    scopes_supported: list[str] | None = None
    code_challenge_methods_supported: list[str] | None = None
    # ... other fields

async def discover_protected_resource(mcp_server_url: str) -> ProtectedResourceMetadata:
    """Fetch /.well-known/oauth-protected-resource from MCP server."""
    pass

async def discover_auth_server(auth_server_url: str) -> AuthServerMetadata:
    """Fetch /.well-known/oauth-authorization-server from auth server."""
    pass

async def discover_from_401(mcp_server_url: str) -> ProtectedResourceMetadata:
    """
    Make unauthenticated request, parse WWW-Authenticate header
    to find resource_metadata URL.
    """
    pass
```

### 3.3 Callback Server Module

```python
# callback.py

@dataclass
class CallbackResult:
    code: str
    state: str

class CallbackServer:
    def __init__(self, port: int = 8456, timeout: int = 120):
        self.port = port
        self.timeout = timeout
        self._result: CallbackResult | None = None

    async def start(self) -> str:
        """Start server, return redirect_uri."""
        pass

    async def wait_for_callback(self) -> CallbackResult:
        """Block until callback received or timeout."""
        pass

    async def stop(self):
        """Shutdown server."""
        pass
```

**Success page HTML:**
```html
<!DOCTYPE html>
<html>
<head><title>Authorization Successful</title></head>
<body>
  <h1>✓ Authorization Successful</h1>
  <p>You can close this window and return to pflow.</p>
  <script>window.close();</script>
</body>
</html>
```

### 3.4 Storage Module

```python
# storage.py

@dataclass
class StoredCredentials:
    server_url: str                    # The MCP server URL
    client_id: str
    client_secret: str | None
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None        # When access_token expires
    scopes: list[str]
    created_at: datetime
    last_used: datetime | None

class CredentialStorage:
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path

    def save(self, server_url: str, creds: StoredCredentials) -> None:
        pass

    def load(self, server_url: str) -> StoredCredentials | None:
        pass

    def delete(self, server_url: str) -> None:
        pass

    def list_servers(self) -> list[str]:
        pass
```

### 3.5 Auth Manager (Orchestrator)

```python
# manager.py

class AuthManager:
    def __init__(self, storage: CredentialStorage):
        self.storage = storage

    async def authenticate(self, mcp_server_url: str) -> StoredCredentials:
        """
        Full OAuth flow:
        1. Check for existing valid credentials
        2. If expired, try refresh
        3. If no creds or refresh fails, run full OAuth flow
        """
        pass

    async def get_access_token(self, mcp_server_url: str) -> str:
        """Get valid access token, refreshing if needed."""
        pass

    async def revoke(self, mcp_server_url: str) -> None:
        """Revoke tokens and delete stored credentials."""
        pass
```

### 3.6 HTTP Client Integration

When pflow makes MCP requests, it needs to inject the auth header:

```python
async def call_mcp_server(server_url: str, method: str, params: dict) -> dict:
    auth_manager = get_auth_manager()
    token = await auth_manager.get_access_token(server_url)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            server_url,
            json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
            headers={"Authorization": f"Bearer {token}"}
        )

        if response.status_code == 401:
            # Token might be invalid, try re-auth
            await auth_manager.authenticate(server_url)
            token = await auth_manager.get_access_token(server_url)
            # Retry request...

        return response.json()
```

---

## 4. Decisions Required

The following decisions affect implementation and should be made explicitly.

### 4.1 Storage Location

**Options:**

| Option | Location | Pros | Cons |
|--------|----------|------|------|
| A | `~/.pflow/auth/` | pflow-specific, clear ownership | Another config dir |
| B | `~/.config/pflow/auth/` | XDG-compliant on Linux | Different paths per OS |
| C | OS keychain | Most secure, native | Complex, platform-specific |

**Recommendation:** Start with Option A (`~/.pflow/auth/`) for simplicity. Can add keychain support later as enhancement.

**Decision needed:** Which storage location?

### 4.2 Storage Format

**Options:**

| Option | Format | Pros | Cons |
|--------|--------|------|------|
| A | JSON file per server | Simple, human-readable | Many files if many servers |
| B | Single JSON file | All creds in one place | Concurrent access issues |
| C | SQLite database | Robust, queryable | Heavier dependency |
| D | Encrypted JSON | Security at rest | Key management complexity |

**Recommendation:** Option B (single JSON file) for simplicity, with file locking for concurrent access. Tokens are already scoped to local user, so encryption is defense-in-depth rather than critical.

**Decision needed:** Which storage format? Should tokens be encrypted at rest?

### 4.3 Callback Port Strategy

**Options:**

| Option | Strategy | Pros | Cons |
|--------|----------|------|------|
| A | Fixed port (e.g., 8456) | Predictable, simple | Port conflicts |
| B | Dynamic port | Always works | redirect_uri varies per auth |
| C | Fixed with fallback | Best of both | Slightly more complex |

**Recommendation:** Option C - Try fixed port (8456), fall back to random available port if busy.

**`mcp-remote` uses:** Port 3334 by default, falls back to random if unavailable.

**Decision needed:** Which port strategy? What default port?

### 4.4 Handling Servers Without DCR

**Options:**

| Option | Approach | Pros | Cons |
|--------|----------|------|------|
| A | Require DCR | Simple | Many servers won't work |
| B | Accept manual client_id | Works everywhere | Worse UX |
| C | Maintain static client_ids | Good UX for known servers | Maintenance burden |
| D | Support all three | Maximum flexibility | More code paths |

**Recommendation:** Option D - Try DCR first, fall back to prompting user for client credentials if DCR fails or isn't advertised.

```bash
# If DCR fails:
pflow mcp add github https://api.github.com/mcp
# Output: "This server requires pre-registered OAuth credentials."
# Prompt: "Enter client_id: "
# Prompt: "Enter client_secret (or leave blank for public client): "
```

**Decision needed:** How to handle non-DCR servers?

### 4.5 Token Refresh Strategy

**Options:**

| Option | Strategy | Pros | Cons |
|--------|----------|------|------|
| A | Refresh on expiry | Simple | Request fails, then retry |
| B | Proactive refresh | Seamless UX | Background complexity |
| C | Refresh on use if near expiry | Good balance | Threshold selection |

**Recommendation:** Option C - Refresh if token expires within 5 minutes of use.

```python
def needs_refresh(creds: StoredCredentials) -> bool:
    if not creds.expires_at:
        return False
    buffer = timedelta(minutes=5)
    return datetime.utcnow() + buffer >= creds.expires_at
```

**Decision needed:** Which refresh strategy? What buffer time?

### 4.6 Browser Opening

**Options:**

| Option | Method | Pros | Cons |
|--------|--------|------|------|
| A | `webbrowser.open()` | Standard library | May not work in all environments |
| B | Print URL, let user open | Always works | Worse UX |
| C | Try auto-open, fall back to print | Best of both | Slightly more complex |

**Recommendation:** Option C

```python
import webbrowser

def open_browser(url: str) -> bool:
    try:
        return webbrowser.open(url)
    except Exception:
        return False

# Usage:
if not open_browser(auth_url):
    print(f"Please open this URL in your browser:\n{auth_url}")
```

**Decision needed:** Confirm browser opening strategy.

### 4.7 CLI Commands

**Proposed commands:**

```bash
# Add a new MCP server (triggers OAuth if needed)
pflow mcp add <name> <url>
pflow mcp add heptabase https://api.heptabase.com/mcp

# List connected servers
pflow mcp list

# Remove a server (revokes tokens, deletes credentials)
pflow mcp remove <name>

# Re-authenticate (force new OAuth flow)
pflow mcp auth <name>

# Show auth status
pflow mcp status <name>
```

**Decision needed:** What CLI commands and syntax?

### 4.8 Multiple Accounts / Tenants

Some servers support multiple accounts (e.g., different Atlassian workspaces).

**Options:**

| Option | Approach | Pros | Cons |
|--------|----------|------|------|
| A | One credential per server URL | Simple | Can't have multiple accounts |
| B | Support resource parameter for isolation | Full flexibility | More complex storage key |

**`mcp-remote` approach:** Uses `--resource` flag to isolate OAuth sessions per tenant.

```bash
pflow mcp add atlassian-tenant1 https://mcp.atlassian.com/sse --resource https://tenant1.atlassian.net/
pflow mcp add atlassian-tenant2 https://mcp.atlassian.com/sse --resource https://tenant2.atlassian.net/
```

**Recommendation:** Support this from the start. Storage key = hash of (server_url + resource_url).

**Decision needed:** Support multiple accounts per server from v1?

### 4.9 Timeout Values

| Timeout | Recommended | Notes |
|---------|-------------|-------|
| OAuth callback wait | 120 seconds | User might be slow typing password |
| HTTP request | 30 seconds | Standard API timeout |
| Token refresh | 10 seconds | Should be fast |

**Decision needed:** Confirm timeout values.

### 4.10 Error Messages

Errors should be clear and actionable:

```
# Connection failed
Error: Could not connect to https://api.heptabase.com/mcp
  → Check your internet connection
  → Verify the server URL is correct

# Auth server not found
Error: Server does not advertise an authorization server
  → This server may not support OAuth authentication
  → Contact the server administrator

# DCR failed
Error: Dynamic client registration failed
  → This server requires pre-registered OAuth credentials
  → Please provide client_id with: pflow mcp add --client-id <id> <name> <url>

# User cancelled
Error: Authorization was cancelled or timed out
  → Run 'pflow mcp auth <name>' to try again

# Token refresh failed
Error: Session expired and could not be refreshed
  → Run 'pflow mcp auth <name>' to re-authenticate
```

**Decision needed:** Review and refine error messages.

---

## 5. Reference Implementations

### 5.1 `mcp-remote` (JavaScript)

The most directly relevant reference. It's a stdio-to-HTTP bridge that handles OAuth.

**Repository:** https://github.com/geelen/mcp-remote

**Key files to study:**
- OAuth flow implementation
- Token storage in `~/.mcp-auth/`
- Callback server

**Token storage path:** `~/.mcp-auth/{server_hash}/`

### 5.2 TypeScript SDK OAuth Helpers

**Repository:** https://github.com/modelcontextprotocol/typescript-sdk

**Key files:**
- `src/client/auth.ts` - OAuth client implementation
- `src/server/auth/` - Server-side OAuth (for reference)

### 5.3 FastMCP (Python)

FastMCP has OAuth proxy support which includes client-side OAuth handling.

**Repository:** https://github.com/jlowin/fastmcp

**Token storage path:** `~/.fastmcp/oauth-mcp-client-cache/`

**Note:** FastMCP is more focused on server-side, but has useful Python patterns.

### 5.4 Cloudflare Workers OAuth Provider

Reference for understanding OAuth proxy pattern (server-side, but useful for understanding flows).

**Repository:** https://github.com/cloudflare/workers-sdk (look for MCP/OAuth examples)

---

## 6. Python Libraries

### 6.1 Recommended Dependencies

```toml
# pyproject.toml

[project]
dependencies = [
    "httpx>=0.25.0",      # Async HTTP client
    "pydantic>=2.0",      # Data validation
    "aiohttp>=3.9.0",     # For callback server (or use built-in)
]

[project.optional-dependencies]
keyring = [
    "keyring>=24.0.0",    # OS keychain support (optional)
]
```

### 6.2 Standard Library Usage

These stdlib modules are sufficient for core functionality:

```python
import secrets          # PKCE verifier generation
import hashlib          # PKCE challenge (SHA256)
import base64           # Base64url encoding
import webbrowser       # Opening auth URL
import json             # Credential storage
import urllib.parse     # URL manipulation
from http.server import HTTPServer, BaseHTTPRequestHandler  # Callback server
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timedelta
```

---

## 7. Security Considerations

### 7.1 Token Storage Security

- Tokens stored on local filesystem are protected by OS file permissions
- File should be readable only by owner: `chmod 600`
- Consider encryption at rest for defense-in-depth
- Never log tokens

### 7.2 PKCE Requirements

- `code_verifier` must be cryptographically random
- Use `secrets` module, not `random`
- Never reuse verifiers across auth flows

### 7.3 State Parameter

- Must be cryptographically random
- Must be verified on callback (CSRF protection)
- Should be single-use

### 7.4 Redirect URI

- Must use `127.0.0.1` or `localhost`
- Must use exact match validation
- Do not use `0.0.0.0`

### 7.5 Token Handling

- MCP spec forbids token passthrough (don't forward user tokens to other servers)
- Tokens should only be sent to the server they were issued for
- Validate `resource` parameter matches intended server

---

## 8. Testing Strategy

### 8.1 Unit Tests

- PKCE generation (verifier format, challenge derivation)
- Metadata parsing
- Token storage read/write
- Credential expiry checking

### 8.2 Integration Tests

- Discovery flow against mock server
- Full OAuth flow with test auth server
- Token refresh flow
- Error handling (401, network errors)

### 8.3 Manual Testing

**Test servers:**
- MCP Inspector (`npx @modelcontextprotocol/inspector`) can act as test client
- Auth0 free tier for DCR testing
- Any public MCP server with OAuth (Sentry, Make.com)

---

## 9. Implementation Phases

### Phase 1: Core OAuth Flow
- [ ] Discovery (protected resource metadata, auth server metadata)
- [ ] PKCE generation
- [ ] Callback server
- [ ] Token exchange
- [ ] Basic storage (JSON file)
- [ ] CLI: `pflow mcp add`, `pflow mcp remove`

### Phase 2: Robustness
- [ ] Token refresh
- [ ] Handle non-DCR servers (manual client credentials)
- [ ] Proper error messages
- [ ] CLI: `pflow mcp list`, `pflow mcp status`

### Phase 3: Polish
- [ ] Multiple accounts/tenants
- [ ] Token encryption at rest (optional)
- [ ] OS keychain support (optional)
- [ ] Timeout handling and retries

---

## 10. Open Questions

These questions may need user input or further research:

1. **What's pflow's existing config/storage pattern?** Should auth storage follow the same pattern?

2. **Does pflow already have HTTP client infrastructure?** Should auth integrate with existing patterns?

3. **Are there existing CLI patterns in pflow?** Should `pflow mcp add` follow existing conventions?

4. **What's the expected scale?** (1-5 servers? 50+ servers?) Affects storage design.

5. **Is there a need for "profiles" or "environments"?** (dev/staging/prod credentials)

---

## Appendix A: Full OAuth Flow Sequence

```
User                    pflow CLI               Callback Server         MCP Server              Auth Server
 │                          │                        │                      │                        │
 │ pflow mcp add foo URL    │                        │                      │                        │
 │─────────────────────────>│                        │                      │                        │
 │                          │                        │                      │                        │
 │                          │ GET URL (no auth)      │                      │                        │
 │                          │───────────────────────────────────────────────>│                        │
 │                          │                        │                      │                        │
 │                          │ 401 + WWW-Authenticate │                      │                        │
 │                          │<───────────────────────────────────────────────│                        │
 │                          │                        │                      │                        │
 │                          │ GET /.well-known/oauth-protected-resource     │                        │
 │                          │───────────────────────────────────────────────>│                        │
 │                          │                        │                      │                        │
 │                          │ Protected Resource Metadata                   │                        │
 │                          │<───────────────────────────────────────────────│                        │
 │                          │                        │                      │                        │
 │                          │ GET /.well-known/oauth-authorization-server   │                        │
 │                          │──────────────────────────────────────────────────────────────────────────>
 │                          │                        │                      │                        │
 │                          │ Auth Server Metadata   │                      │                        │
 │                          │<──────────────────────────────────────────────────────────────────────────
 │                          │                        │                      │                        │
 │                          │ Generate PKCE          │                      │                        │
 │                          │ (verifier, challenge)  │                      │                        │
 │                          │                        │                      │                        │
 │                          │ Start callback server  │                      │                        │
 │                          │───────────────────────>│ (listening)          │                        │
 │                          │                        │                      │                        │
 │    (browser opens)       │                        │                      │                        │
 │<─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│                        │                      │                        │
 │                          │                        │                      │                        │
 │ User logs in, authorizes │                        │                      │                        │
 │──────────────────────────────────────────────────────────────────────────────────────────────────────>
 │                          │                        │                      │                        │
 │ Redirect to callback     │                        │                      │                        │
 │ ?code=XYZ&state=ABC      │                        │                      │                        │
 │─────────────────────────────────────────────────>│                        │                        │
 │                          │                        │                      │                        │
 │                          │ Callback received      │                      │                        │
 │                          │<───────────────────────│                      │                        │
 │                          │                        │                      │                        │
 │ "Success" page           │                        │                      │                        │
 │<─────────────────────────────────────────────────│                        │                        │
 │                          │                        │                      │                        │
 │                          │ POST /oauth/token      │                      │                        │
 │                          │ (code + verifier)      │                      │                        │
 │                          │──────────────────────────────────────────────────────────────────────────>
 │                          │                        │                      │                        │
 │                          │ {access_token, refresh_token}                 │                        │
 │                          │<──────────────────────────────────────────────────────────────────────────
 │                          │                        │                      │                        │
 │                          │ Store credentials      │                      │                        │
 │                          │ (~/.pflow/auth/)       │                      │                        │
 │                          │                        │                      │                        │
 │ "✓ Connected to foo"     │                        │                      │                        │
 │<─────────────────────────│                        │                      │                        │
```

---

## Appendix B: Sample Credential Storage Format

```json
{
  "version": 1,
  "servers": {
    "https://api.heptabase.com/mcp": {
      "name": "heptabase",
      "server_url": "https://api.heptabase.com/mcp",
      "auth_server": "https://auth.heptabase.com",
      "client_id": "abc123",
      "client_secret": null,
      "access_token": "eyJhbGciOiJSUzI1...",
      "refresh_token": "dGhpcyBpcyBhIHJl...",
      "expires_at": "2025-12-22T15:30:00Z",
      "scopes": ["read", "write", "offline_access"],
      "created_at": "2025-12-22T14:30:00Z",
      "last_used": "2025-12-22T14:35:00Z"
    }
  }
}
```

---

## Appendix C: Error Handling Matrix

| Situation | HTTP Status | Action |
|-----------|-------------|--------|
| No auth header sent | 401 | Start OAuth flow |
| Token expired | 401 | Try refresh, then re-auth |
| Token invalid | 401 | Delete stored creds, re-auth |
| Insufficient scope | 403 | Re-auth with expanded scopes |
| Server unreachable | N/A | Retry with backoff, then fail |
| Auth server unreachable | N/A | Fail with clear message |
| User cancelled auth | N/A | Fail, suggest retry command |
| Callback timeout | N/A | Fail, suggest retry command |
| DCR rejected | 4xx | Fall back to manual client_id |
| Refresh token expired | 400 | Full re-auth required |
