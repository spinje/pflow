# Pflow MCP Server Configuration Format Research

## Executive Summary

**Pflow uses the standard MCP configuration format with explicit `type` field**, but with a smart default:
- **Absence of `type` field defaults to `"stdio"`** (not inferred from `command` vs `url`)
- **HTTP servers must explicitly set `type: "http"`**
- **This differs from VS Code's format where `command` and `url` are mutually exclusive fields with implicit detection**

---

## Standard MCP Format Used by Pflow

### Canonical Example
```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    },
    "http-server": {
      "type": "http",
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${TOKEN}"
      }
    }
  }
}
```

### Key Format Rules

1. **`mcpServers` wrapper is required** - All servers under this top-level key
2. **`type` field handling**:
   - **Optional for stdio servers** (absence = stdio)
   - **Required and must be `"http"` for HTTP servers**
   - Never use `type: "stdio"` (it's the default)
3. **No timestamps or metadata** - Unlike VS Code, pflow doesn't add `created_at`, `updated_at`
4. **Transport-specific fields**:
   - **stdio**: `command` (required), `args` (optional), `env` (optional)
   - **http**: `url` (required), `auth` (optional), `headers` (optional), `timeout` (optional), `sse_timeout` (optional), `env` (optional)

---

## Transport Detection Logic

### Source: `src/pflow/mcp/discovery.py` (line 94-102)

```python
# Standard format: use "type" field, default to stdio if not present
transport_type = server_config.get("type", "stdio")

if transport_type == "http":
    return await self._discover_async_http(server_name, server_config)
elif transport_type == "stdio" or transport_type is None:
    return await self._discover_async_stdio(server_name, server_config, verbose)
else:
    raise ValueError(f"Unsupported transport type: {transport_type}")
```

**Key Insight**: `server_config.get("type", "stdio")` means:
- No `type` field → defaults to `"stdio"`
- `type: null` → treated as stdio
- `type: "http"` → uses HTTP transport
- Any other value → error

---

## Field Definitions by Transport

### Stdio Transport
```json
{
  "command": "npx",           // REQUIRED: command to execute
  "args": ["-y", "server"],   // OPTIONAL: command arguments
  "env": {                    // OPTIONAL: environment variables
    "KEY": "${VALUE}"         // Supports ${VAR} and ${VAR:-default} expansion
  }
}
```

### HTTP Transport
```json
{
  "type": "http",            // REQUIRED for HTTP
  "url": "https://...",      // REQUIRED: server URL
  "auth": {                  // OPTIONAL: authentication config
    "type": "bearer",        // "bearer", "api_key", or "basic"
    "token": "..."           // auth-type-specific fields
  },
  "headers": {               // OPTIONAL: custom headers
    "X-Custom": "value"
  },
  "timeout": 30,             // OPTIONAL: HTTP timeout (seconds)
  "sse_timeout": 300,        // OPTIONAL: SSE read timeout (seconds)
  "env": {                   // OPTIONAL: environment variables
    "KEY": "${VALUE}"
  }
}
```

---

## Differences from VS Code MCP Format

| Feature | Pflow | VS Code (Cline) |
|---------|-------|-----------------|
| **Transport detection** | Explicit `type` field (default: stdio) | Implicit from `command` vs `url` |
| **`type` field** | Optional for stdio, required for http | Not used |
| **Stdio config** | `command` + `args` + `env` | Same |
| **HTTP config** | `type: "http"` + `url` + `auth` + `headers` | `url` + `headers` only |
| **Timestamps** | Not stored | `created_at`, `updated_at` |
| **Config wrapper** | `{"mcpServers": {...}}` | Same |

### Example: Same Server in Both Formats

**Pflow format** (explicit):
```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  }
}
```

**VS Code format** (identical for stdio):
```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  }
}
```

**HTTP server difference**:

Pflow:
```json
{
  "slack": {
    "type": "http",
    "url": "https://api.example.com/mcp"
  }
}
```

VS Code (inferred from `url` presence):
```json
{
  "slack": {
    "url": "https://api.example.com/mcp"
  }
}
```

---

## CLI Add Command Behavior

### Source: `src/pflow/cli/mcp.py` (lines 82-149)

The `pflow mcp add` command accepts **three JSON formats**:

1. **Full MCP format** (standard):
   ```bash
   pflow mcp add '{"mcpServers": {"github": {...}}}'
   ```

2. **Direct server map** (convenience):
   ```bash
   pflow mcp add '{"github": {"command": "npx", "args": [...]}}'
   ```
   → Automatically wrapped as `{"mcpServers": {...}}`

3. **Single server** (simplest):
   ```bash
   pflow mcp add '{"github": {"command": "npx"}}'
   ```
   → Automatically wrapped

### Detection Logic (lines 42-79)

```python
def _add_from_json_string(manager: MCPServerManager, json_str: str) -> list[str]:
    config = json.loads(json_str)

    # Format 1: Full MCP format with mcpServers wrapper
    if "mcpServers" in config:
        return manager.add_servers_from_config(config)

    # Format 2 & 3: Direct server map (one or more servers)
    # Check if all values are server configs (have command or url)
    if all(isinstance(v, dict) and _is_server_config(v) for v in config.values()):
        wrapped = {"mcpServers": config}
        return manager.add_servers_from_config(wrapped)

    raise ValueError("Invalid JSON format...")

def _is_server_config(config: dict) -> bool:
    """Check if a dict looks like a server config (has command/url, not nested servers)."""
    return "command" in config or "url" in config
```

**Key insight**: The CLI uses `command` or `url` presence to detect server configs for **wrapping purposes only**, NOT for transport type detection. Transport type is always determined by the explicit `type` field (or lack thereof).

---

## Validation Rules

### Source: `src/pflow/mcp/manager.py` (lines 397-547)

```python
def validate_server_config(self, config: dict[str, Any]) -> None:
    # Determine transport type from config
    # type field is optional for stdio, required and must be "http" for HTTP
    transport_type = config.get("type", "stdio")

    if transport_type == "stdio" or transport_type is None:
        self._validate_stdio_config(config)
    elif transport_type == "http":
        self._validate_http_config(config)
    else:
        raise ValueError(f"Unsupported transport type: {transport_type}")
```

**Stdio validation** (lines 423-442):
- `command` field is **required**
- `args` must be a list (if present)
- `env` must be a dict (if present)

**HTTP validation** (lines 443-466):
- `url` field is **required**
- URL must start with `http://` or `https://`
- Warns about non-HTTPS for non-localhost
- `auth` must be valid AuthConfig (if present)
- `headers` must be a dict (if present)
- `timeout` must be positive, max 600 seconds

---

## Authentication Configuration (HTTP Only)

### Source: `src/pflow/mcp/types.py` (lines 6-14)

```python
class AuthConfig(TypedDict, total=False):
    """Authentication configuration for HTTP transport."""
    type: Literal["bearer", "api_key", "basic"]
    token: Optional[str]      # For bearer
    key: Optional[str]        # For api_key
    header: Optional[str]     # For api_key (default: X-API-Key)
    username: Optional[str]   # For basic
    password: Optional[str]   # For basic
```

### Example: Bearer Auth
```json
{
  "type": "http",
  "url": "https://api.example.com/mcp",
  "auth": {
    "type": "bearer",
    "token": "${API_TOKEN}"
  }
}
```

---

## Environment Variable Expansion

Both transports support `${VAR}` expansion in `env` fields:

```json
{
  "env": {
    "GITHUB_TOKEN": "${GITHUB_TOKEN}",
    "API_KEY": "${API_KEY:-default_value}"
  }
}
```

**Syntax**:
- `${VAR}` - Required variable (fails if not set)
- `${VAR:-default}` - Optional with default value

**Expansion happens at runtime** when the server is started, not when config is saved.

---

## Practical Examples for Documentation

### Stdio Server (npx)
```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

### Stdio Server (uvx)
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "uvx",
      "args": ["mcp-server-filesystem", "/path/to/allowed/files"]
    }
  }
}
```

### HTTP Server with Bearer Auth
```json
{
  "mcpServers": {
    "slack": {
      "type": "http",
      "url": "https://mcp.example.com/slack",
      "auth": {
        "type": "bearer",
        "token": "${SLACK_TOKEN}"
      },
      "timeout": 60
    }
  }
}
```

### HTTP Server with Custom Headers
```json
{
  "mcpServers": {
    "custom": {
      "type": "http",
      "url": "https://api.example.com/mcp",
      "headers": {
        "X-API-Key": "${API_KEY}",
        "X-Client-ID": "pflow"
      }
    }
  }
}
```

---

## CLI Command Examples

### Add from file
```bash
pflow mcp add ./github.mcp.json
```

### Add from JSON (simple format)
```bash
pflow mcp add '{"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}}'
```

### Add HTTP server
```bash
pflow mcp add '{"slack": {"type": "http", "url": "https://mcp.example.com/slack"}}'
```

### Add from full MCP format
```bash
pflow mcp add '{"mcpServers": {"github": {"command": "npx", "args": ["..."]}}'
```

---

## Key Takeaways for Documentation

1. **Pflow uses standard MCP format with explicit `type` field**
   - Not implicit detection from `command`/`url` presence
   - Default is `"stdio"` when `type` is absent

2. **HTTP servers MUST include `type: "http"`**
   - Just having `url` is not enough
   - Common mistake to omit this

3. **Three input formats supported by CLI**
   - Full format: `{"mcpServers": {...}}`
   - Direct map: `{"name": {"command": "..."}}`
   - All auto-wrapped to standard format

4. **Environment variable expansion is powerful**
   - Works in both stdio and HTTP configs
   - Supports defaults: `${VAR:-default}`

5. **No timestamps in config file**
   - Unlike some other MCP implementations
   - Config is purely declarative

---

## Source Files Reference

- **Type definitions**: `src/pflow/mcp/types.py`
- **Config manager**: `src/pflow/mcp/manager.py`
- **Discovery logic**: `src/pflow/mcp/discovery.py`
- **CLI commands**: `src/pflow/cli/mcp.py`
- **Auth utilities**: `src/pflow/mcp/auth_utils.py`
