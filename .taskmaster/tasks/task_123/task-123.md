# Task 123: OAuth Authentication for MCP HTTP Servers

## Description

Add OAuth 2.1 authentication for remote MCP HTTP servers, leveraging the MCP Python SDK's built-in `OAuthClientProvider`. This lets users connect to OAuth-protected servers (Supabase, GitHub MCP, etc.) without manually creating access tokens — the same way Claude Code, Cursor, and Cline handle it.

## Status

not started

## Priority

medium

## Problem

Connecting to OAuth-protected MCP servers requires users to manually:
1. Register an OAuth app in the server's developer portal
2. Generate a personal access token
3. Store it via `pflow settings set-env` or `export`
4. Reference it in headers: `"Authorization": "Bearer ${TOKEN}"`

This is the CI/non-interactive path (and remains valid — see Task 88 fix). But for interactive use, every other MCP client (Claude Code, Cursor, Cline) supports automatic OAuth: add server URL, browser opens, you log in, done. pflow has no equivalent.

## Solution

Add an `oauth` auth type that uses the MCP SDK's `OAuthClientProvider` (already installed, v1.26.0). The SDK handles the OAuth protocol (PKCE, DCR, token exchange, refresh). pflow needs to build:

1. **Token storage** — Persist OAuth tokens to `~/.pflow/auth/`
2. **Browser + callback handlers** — Open browser, run temporary localhost server
3. **CLI integration** — Flags for `pflow mcp add` and an auth trigger flow
4. **Transport integration** — Pass `auth=oauth_provider` to `streamablehttp_client`

### What the SDK provides (verified against v1.26.0)

- `OAuthClientProvider` — Full OAuth 2.1 authorization code flow with PKCE
- Automatic token refresh using refresh tokens
- Dynamic client registration (DCR) for servers that support it
- Protected resource metadata discovery (RFC 9728)
- Authorization server metadata discovery (RFC 8414)
- Integrates as `httpx.Auth` — can be passed directly to `streamablehttp_client(auth=)`

### What pflow must build

- `TokenStorage` implementation (SDK defines the protocol, pflow implements persistence)
- `redirect_handler` callback (open browser with auth URL)
- `callback_handler` callback (local HTTP server to receive OAuth redirect)
- CLI flags: `--client-id`, `--client-secret`, `--callback-port` (for non-DCR servers)
- Config schema: `"auth": {"type": "oauth", ...}` alongside existing bearer/api_key/basic

## Design Decisions

- **Use SDK's `OAuthClientProvider`, not custom OAuth**: The MCP SDK already implements the full OAuth 2.1 spec including PKCE, DCR, discovery, and token refresh. No reason to reimplement.

- **Old `streamablehttp_client` API is sufficient**: The old API already has `auth: httpx.Auth | None = None` parameter (verified). No need to migrate to the new `streamable_http_client(http_client=)` API. Just pass `auth=oauth_provider` alongside existing `headers=`.

- **Token storage in plain text JSON with `chmod 600`**: Same approach as AWS CLI, gh CLI, and pflow's existing `settings.json`. No keychain integration. Consistent with how pflow stores other secrets.

- **OAuth and static auth are separate paths**: When `auth.type` is `"oauth"`, create an `OAuthClientProvider` and pass it as `auth=`. When `auth.type` is `"bearer"/"api_key"/"basic"`, continue building headers via `build_auth_headers()` as today. Custom `headers` (non-auth) still go through `headers=` in both cases.

- **Support non-DCR servers via `--client-id`/`--client-secret`**: Major providers (GitHub, Google, Azure) don't support Dynamic Client Registration. Users must pre-register an OAuth app and provide credentials. This is the same approach Claude Code took in v2.1.30.

- **Browser flow with fallback**: Try `webbrowser.open()`, fall back to printing URL for headless/SSH environments. Claude Code has known issues with SSH sessions — we should handle this gracefully from the start.

- **Callback port strategy**: Try a fixed port (e.g., 8456), fall back if busy. Allow override via `--callback-port`. Claude Code and Cline both had port conflict bugs — learn from this.

## Dependencies

- Issue #88: MCP config env var expansion (completed) — Prerequisite fix ensuring `${VAR}` works in URLs and settings.json is checked. Without this, the manual token fallback path doesn't work.
- Task 97: OAuth for Remote MCP Servers — Check if this is the same task or a different scope. May need to be merged or one deprecated.

## Implementation Notes

### Config schema addition

```json
{
  "mcpServers": {
    "supabase": {
      "type": "http",
      "url": "https://mcp.supabase.com/mcp",
      "auth": {
        "type": "oauth"
      }
    },
    "github-custom": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "auth": {
        "type": "oauth",
        "clientId": "your-client-id",
        "callbackPort": 8080
      }
    }
  }
}
```

When `auth.type` is `"oauth"` with no `clientId`, the SDK uses DCR automatically. When `clientId` is provided, it's used for servers without DCR.

### Token storage

Implement the SDK's `TokenStorage` protocol:

```
~/.pflow/auth/{server_url_hash}.json
```

Each file stores `OAuthToken` (access_token, refresh_token, expires_at) and `OAuthClientInformationFull` (client registration data). File permissions `chmod 600`.

### CLI changes

```bash
# Auto-DCR (most servers):
pflow mcp add '{"supabase": {"type": "http", "url": "https://mcp.supabase.com/mcp", "auth": {"type": "oauth"}}}'

# Non-DCR (manual credentials):
pflow mcp add --client-id <id> --client-secret --callback-port 8080 \
  '{"github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/", "auth": {"type": "oauth"}}}'
```

The `--client-secret` flag should prompt for masked input (like Claude Code) or accept via `MCP_CLIENT_SECRET` env var for CI.

### Transport integration

In both `discovery.py` (`_discover_async`) and `nodes/mcp/node.py` (execution), when `auth.type == "oauth"`:

```python
# Instead of:
headers = build_auth_headers(config)
streamablehttp_client(url=url, headers=headers, ...)

# Do:
oauth_provider = await create_oauth_provider(server_name, config)
custom_headers = config.get("headers", {})  # Non-auth headers only
streamablehttp_client(url=url, headers=custom_headers, auth=oauth_provider, ...)
```

### Interactive auth trigger

Need an equivalent to Claude Code's `/mcp` command for triggering the browser flow. Options:
- Trigger automatically on first use (when no stored token exists)
- Add `pflow mcp auth <server-name>` command
- Both (auto-trigger + manual re-auth command)

### Key files to modify

- `src/pflow/mcp/auth_utils.py` — Add OAuth provider creation alongside existing auth types
- `src/pflow/mcp/discovery.py` — Pass `auth=` when OAuth configured
- `src/pflow/nodes/mcp/node.py` — Same transport change
- `src/pflow/cli/mcp.py` — Add `--client-id`, `--client-secret`, `--callback-port` flags; add `auth` subcommand
- `src/pflow/mcp/manager.py` — Validate `oauth` auth type in config schema
- New: `src/pflow/mcp/oauth_storage.py` — TokenStorage implementation
- New: `src/pflow/mcp/oauth_handlers.py` — Browser redirect + callback server

### Known pitfalls from other clients

These are bugs other MCP clients hit. Design around them:
- **Port conflicts**: Claude Code issue #15320 — multiple servers racing for same callback port. Use per-server ports or sequential fallback.
- **SSH/headless**: Claude Code issue #1178 — no browser available. Print URL as fallback, never hang waiting for browser.
- **Reconnection after OAuth**: Claude Code issue #10250 — tokens stored but tools unavailable until restart. Ensure connection is re-established after auth completes.
- **localhost vs 127.0.0.1**: OAuth treats these as different strings. Be consistent in redirect URI.

## Verification

- **DCR flow**: Add an OAuth-protected server (e.g., Supabase MCP), browser opens, user authenticates, tools are discovered. Subsequent runs reuse stored tokens without re-auth.
- **Non-DCR flow**: Add server with `--client-id`, authenticate via browser, tools work.
- **Token refresh**: Access token expires, SDK automatically refreshes using stored refresh token.
- **Token persistence**: Restart pflow, previously authenticated servers work without re-auth.
- **Missing token**: Clear stored tokens, next use triggers browser flow again.
- **Headless fallback**: When browser can't open (SSH), auth URL is printed to terminal.
- **Static auth unchanged**: Existing `bearer`/`api_key`/`basic` configs continue working.
- **Port conflict**: Two servers with OAuth don't deadlock on the same callback port.

## Research Reference

Detailed research notes (how other clients implement OAuth, SDK API details, spec references) saved in `scratchpads/mcp-oauth/research-notes.md`.
