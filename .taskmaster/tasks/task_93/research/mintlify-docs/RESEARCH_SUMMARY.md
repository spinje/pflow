# MCP Configuration Format Research - Quick Summary

## Question: Does pflow use explicit `type` field or infer from `command` vs `url`?

**Answer: Pflow uses explicit `type` field with smart defaults**

## Key Findings

### 1. Transport Detection
- **Explicit `type` field** - not inferred from `command`/`url` presence
- **Default behavior**: absence of `type` → defaults to `"stdio"`
- **HTTP requires**: must explicitly set `type: "http"`

### 2. Configuration Format

**Stdio (type field optional):**
```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
}
```

**HTTP (type field required):**
```json
{
  "type": "http",
  "url": "https://api.example.com/mcp",
  "auth": {"type": "bearer", "token": "${TOKEN}"}
}
```

### 3. VS Code Difference

| Feature | Pflow | VS Code |
|---------|-------|---------|
| Transport detection | Explicit `type` field | Implicit from `command` vs `url` |
| HTTP servers | `type: "http"` required | Inferred from `url` presence |
| Stdio servers | `type` optional (default) | Inferred from `command` presence |

### 4. CLI Convenience

The CLI accepts three formats (all auto-wrapped):
```bash
# Full format
pflow mcp add '{"mcpServers": {"name": {...}}}'

# Direct map (convenience)
pflow mcp add '{"name": {"command": "..."}}'

# Single server (simplest)
pflow mcp add '{"name": {"command": "..."}}'
```

### 5. Common Mistake

❌ **Wrong** (missing type for HTTP):
```json
{"slack": {"url": "https://mcp.example.com/slack"}}
```

✅ **Correct**:
```json
{"slack": {"type": "http", "url": "https://mcp.example.com/slack"}}
```

## Documentation Implications

When documenting MCP configuration:
1. **Always show `type: "http"` for HTTP servers** - it's required
2. **Omit `type` for stdio servers** - it's the default
3. **Mention the three CLI input formats** - for convenience
4. **Show environment variable expansion** - `${VAR}` and `${VAR:-default}`
5. **Highlight the VS Code difference** - users may be confused

## Source Code References

- Transport detection: `src/pflow/mcp/discovery.py:94-102`
- Config validation: `src/pflow/mcp/manager.py:397-547`
- CLI wrapping: `src/pflow/cli/mcp.py:42-79`
- Type definitions: `src/pflow/mcp/types.py`

## Complete Details

See `mcp-config-format-findings.md` for comprehensive analysis with code examples and source references.
