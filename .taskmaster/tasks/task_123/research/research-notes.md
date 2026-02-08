# MCP OAuth Research Notes

Saved here so the task spec can reference this without bloating the task file.

## Sources

- [Claude Code MCP docs](https://code.claude.com/docs/en/mcp)
- [Claude Code OAuth flags issue #22909](https://github.com/anthropics/claude-code/issues/22909)
- [Claude Code SSH OAuth issue #1178](https://github.com/anthropics/claude-code/issues/1178)
- [Claude Code port conflicts #15320](https://github.com/anthropics/claude-code/issues/15320)
- [Claude Code reconnection fails #10250](https://github.com/anthropics/claude-code/issues/10250)
- [Roo Code OAuth enhancement #8119](https://github.com/RooCodeInc/Roo-Code/issues/8119)
- [Cline OAuth issues #4523](https://github.com/cline/cline/issues/4523)
- [VS Code full MCP spec support](https://code.visualstudio.com/blogs/2025/06/12/full-mcp-spec-support)
- [mcp-remote npm](https://www.npmjs.com/package/mcp-remote)
- [MCP spec authorization (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25)
- [Docker: Connect to Remote MCP Servers with OAuth](https://www.docker.com/blog/connect-to-remote-mcp-servers-with-oauth/)
- [MCP Python SDK - OAuthClientProvider DeepWiki](https://deepwiki.com/modelcontextprotocol/python-sdk/7.2-documentation)

## How other clients implement OAuth

### Claude Code CLI
- Uses `/mcp` interactive command to trigger OAuth flow
- Opens browser, runs local callback server on configurable port (`--callback-port`)
- Since v2.1.30: `--client-id`, `--client-secret`, `--callback-port` flags for non-DCR servers
- Client secrets stored in system keychain (macOS) or credentials file, NOT in config JSON
- Tokens refreshed automatically
- Known bugs: doesn't work in SSH sessions, port conflicts with multiple servers, reconnection fails after OAuth
- Supports `${VAR}` expansion in `.mcp.json` for urls, headers, env, args, command

### Cline (VS Code)
- Uses VS Code's built-in OAuth support (June 2025 full MCP spec)
- Local callback server on ports 48801-48811 (sequential fallback for multi-instance)
- Persists tokens across sessions
- Historically limited OAuth support, improved via VS Code's native implementation

### Roo Code
- Does NOT have native OAuth yet (as of Feb 2026)
- Enhancement request #8119 has ~2000 lines at ~65% RFC compliance, awaiting architectural decisions
- Current workaround: `mcp-remote` npm package as stdio-to-HTTP bridge
- Planned: full OAuth 2.1 with PKCE, RFC 9728 discovery, DCR

### mcp-remote (npm, fallback for many clients)
- Stdio-to-HTTP bridge handling OAuth for clients that can't
- Callback on port 3334 (configurable), falls back to random if busy
- `--auth-timeout` flag (default 30s)
- Tokens stored in `~/.mcp-auth/{server_hash}/`

## MCP Python SDK (v1.26.0) OAuth Support

### What the SDK provides
- `OAuthClientProvider` in `mcp/client/auth/oauth2.py` — full OAuth 2.1 + PKCE
- Automatic token refresh
- Protected resource metadata discovery (RFC 9728)
- Authorization server metadata discovery (RFC 8414)
- Dynamic client registration (DCR)
- `ClientCredentialsOAuthProvider` for M2M flows
- `PrivateKeyJWTOAuthProvider` for advanced M2M

### TokenStorage protocol
```python
class TokenStorage(Protocol):
    async def get_tokens(self) -> OAuthToken | None: ...
    async def set_tokens(self, tokens: OAuthToken) -> None: ...
    async def get_client_info(self) -> OAuthClientInformationFull | None: ...
    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None: ...
```

### OAuthClientProvider signature
```python
OAuthClientProvider(
    server_url: str,
    client_metadata: OAuthClientMetadata,
    storage: TokenStorage,
    redirect_handler: Callable[[str], Awaitable[None]] | None = None,
    callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
    timeout: float = 300.0,
    client_metadata_url: str | None = None,
)
```

### OAuthClientMetadata fields
- redirect_uris, token_endpoint_auth_method, grant_types, response_types
- scope, client_name, client_uri, logo_uri, contacts
- tos_uri, policy_uri, jwks_uri, jwks, software_id, software_version

### SDK API availability (verified against installed v1.26.0)
- Old API: `streamablehttp_client(url, headers=, timeout=, ..., auth: httpx.Auth | None = None)`
  - Already has `auth=` parameter! pflow just doesn't use it.
- New API: `streamable_http_client(url, *, http_client: httpx.AsyncClient | None = None)`
  - Takes pre-configured httpx.AsyncClient

Key: OAuthClientProvider inherits from httpx.Auth, so can be passed as `auth=` to old API.

## pflow codebase state (verified)

### Current MCP CLI
- `pflow mcp add` accepts file paths or raw JSON, no interactive flags
- No `--client-id`, `--client-secret`, `--callback-port` flags
- No interactive auth flow exists

### Config format
- `~/.pflow/mcp-servers.json` with `mcpServers` key
- HTTP servers: `type`, `url`, `headers`, `auth`, `env`
- Auth types: `bearer` (token), `api_key` (key, header), `basic` (username, password)

### Storage
- Plain text JSON with `chmod 600` (same as AWS CLI, gh CLI)
- No keychain/keyring integration
- Settings in `~/.pflow/settings.json`

### Transport call sites
- `discovery.py` and `nodes/mcp/node.py` both call `streamablehttp_client(url=, headers=, timeout=, sse_read_timeout=)`
- Neither passes `auth=` parameter (but it's available)
- `build_auth_headers()` converts auth config to headers before transport call
