# MCP Configuration Refactor - Critical User Decisions

## 1. Config File Format Compatibility - Importance: 4/5

We need to support the standard MCP JSON format used by Claude Code and other clients. This means accepting files with the `mcpServers` wrapper structure.

### Context:
Currently, pflow uses its own format with a `servers` key. The standard format uses `mcpServers` and slightly different field names. We need to decide how to handle this discrepancy.

### Options:

- [x] **Option A: Full Compatibility Mode**
  - Accept standard MCP JSON files with `mcpServers` wrapper
  - Convert to internal format when storing in `~/.pflow/mcp-servers.json`
  - Keep internal format for backward compatibility
  - Benefits: Works with any MCP config file from other tools
  - Drawbacks: Two formats to maintain (external vs internal)

- [ ] **Option B: Migrate to Standard Format**
  - Change internal format to match standard `mcpServers` structure
  - Migrate existing configs automatically
  - Benefits: Single format everywhere
  - Drawbacks: Breaking change for existing users (though we have no users yet)

**Recommendation**: Option A - This maintains backward compatibility while supporting the standard. Since we're early in development, we could also consider Option B.

## 2. Auto-Discovery Behavior - Importance: 3/5

Should MCP servers be automatically discovered and synced when pflow starts, or keep the manual sync pattern?

### Context:
Currently users must run `pflow mcp sync` after adding servers. Auto-discovery would make tools immediately available but adds startup overhead.

### Options:

- [x] **Option A: Auto-discovery on startup**
  - Load all configured servers when pflow starts
  - Register tools automatically in background
  - Benefits: Seamless UX, tools always available
  - Drawbacks: Slower startup, potential connection failures

- [ ] **Option B: Lazy discovery on first use**
  - Discover tools when first MCP node is encountered
  - Cache results for session
  - Benefits: Fast startup, discover only what's needed
  - Drawbacks: First use might be slow

- [ ] **Option C: Keep manual sync**
  - Maintain current behavior
  - Benefits: Predictable, user controls when discovery happens
  - Drawbacks: Extra step for users

**Recommendation**: Option A - Better UX despite startup cost. We can optimize later with caching.

## 3. Config File Discovery - Importance: 2/5

How should pflow discover MCP config files beyond the explicit `pflow mcp add` command?

### Context:
Claude Code looks for `.mcp.json` files in project directories. Should pflow do the same?

### Options:

- [x] **Option A: Only explicit loading**
  - Only load configs via `pflow mcp add` command
  - No automatic discovery of `.mcp.json` files
  - Benefits: Predictable, no surprises
  - Drawbacks: Users must explicitly add each config

- [ ] **Option B: Auto-discover project configs**
  - Look for `.mcp.json` in current directory and parents
  - Auto-load if found
  - Benefits: Works like Claude Code
  - Drawbacks: Might load unwanted servers

**Recommendation**: Option A - Start simple, can add auto-discovery later based on user feedback.

## 4. Transport Type Validation - Importance: 4/5

The standard format uses optional `type` field for stdio and requires it for sse/http. How strictly should we validate?

### Context:
Standard allows omitting `type` for stdio but requires it for other transports. Current pflow always requires explicit `transport` field.

### Options:

- [x] **Option A: Follow standard exactly**
  - Missing `type` = stdio transport
  - Require `type` for sse and http
  - Benefits: Full compatibility with standard configs
  - Drawbacks: Implicit behavior might confuse

- [ ] **Option B: Always require type**
  - Make `type` mandatory for clarity
  - Benefits: Explicit is better than implicit
  - Drawbacks: Won't accept some valid standard configs

**Recommendation**: Option A - Follow the standard for maximum compatibility.

## 5. SSE Transport Support - Importance: 3/5

The standard includes SSE (Server-Sent Events) transport. Should we add support now or defer?

### Context:
Current implementation supports stdio and http. SSE is similar to HTTP but uses event streams.

### Options:

- [ ] **Option A: Add SSE support now**
  - Implement SSE alongside HTTP
  - Benefits: Full standard compliance
  - Drawbacks: More complexity, needs testing

- [x] **Option B: Defer SSE, error clearly**
  - Reject SSE configs with helpful message
  - Add support later if needed
  - Benefits: Ship faster, less to test
  - Drawbacks: Can't use SSE-based servers

**Recommendation**: Option B - We can add SSE later if users need it. Clear error message is key.

## 6. Environment Variable Handling - Importance: 5/5

How should we handle environment variables in imported configs?

### Context:
Standard uses `${VAR}` and `${VAR:-default}` syntax. We already support `${VAR}` but not defaults.

### Options:

- [x] **Option A: Full standard support**
  - Implement `${VAR:-default}` syntax
  - Expand at runtime (current behavior)
  - Benefits: Works with any standard config
  - Drawbacks: More complex parsing

- [ ] **Option B: Basic support only**
  - Only support `${VAR}` (current)
  - Reject configs with default syntax
  - Benefits: Simpler
  - Drawbacks: Some configs won't work

**Recommendation**: Option A - This is critical for compatibility. Many configs use the default syntax.