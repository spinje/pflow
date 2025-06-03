# MCP Server Integration and Security Model

## 1 Scope

A practical, end‑to‑end spec for integrating **Model Context Protocol** servers into pflow. Covers:

- Transport discovery and connection for all spec‑compliant modes (`stdio`, `uds`, `pipe`, `sse`, `stream-http`).

- Installation, autostart, registry persistence.

- Wrapper‑node generation and version pinning.

- Authentication, scope validation, egress control.

- Failure semantics, retries, caching constraints.

- Examples that mirror Cursor’s documentation patterns.

---

## 2 Terminology

| Term | Meaning | 
|---|---|
| **Registrar** | pflow subsystem managing installation metadata and local server lifecycles. | 
| **Process Manager** | Part of Registrar that launches/monitors `stdio` servers. | 
| **Registry** | JSON file `~/.pflow/mcp.json` (or project‑local `.pflow/mcp.json`) enumerating all known servers. | 
| **Wrapper Node** | Python class auto‑generated from `/tools/list`; hard‑pins server ID, tool name, tool version, manifest hash. | 
| **Executor** | Runtime logic inside each wrapper node that submits a tool call using the correct transport handler. | 

---

## 3 Supported Transports

| `transport` | Typical use | Connection method | Autostart possible | Notes | 
|---|---|---|---|---|
| `stdio` | Local dev, high‑trust tools | Subprocess on stdin/stdout | Yes | Cursor default; OS prompt on first run (Windows/macOS). | 
| `uds` | Linux containers | `aiohttp.UnixConnector` | Yes | Path supplied in registry. | 
| `pipe` | Windows named‑pipes | `pywin32` client | Yes | Path `\\.\pipe\mcp‑<name>`. | 
| `sse` | Remote or local HTTP EventStream (`/sse`) | `httpx` stream POST | No | Requires BYO deployment; real‑time chunked events. | 
| `stream-http` | Emerging spec: single POST returning chunked JSON | `httpx` | No | Backward‑compatible with SSE wrappers—detect via header. | 

---

## 4 Registry (`mcp.json`)

```json
{
  "servers": {
    "local-fs": {
      "transport": "stdio",
      "command": "mcp-fs",
      "args": [],
      "env": {},
      "autostart": true,
      "version": "0.3.0"
    },
    "weather-remote": {
      "transport": "sse",
      "url": "https://api.weathercorp.com/sse",
      "token_env": "PFLOW_WEATHER_TOKEN",
      "version": "1.2.4"
    }
  }
}

```

- FS path precedence: project `.pflow/mcp.json` → user `~/.pflow/mcp.json` → system.

- Edits via CLI only (`pflow mcp add`, `pflow mcp edit`). Manual edits warned but not blocked.

---

## 5 Registrar Commands

| Command | Effect | 
|---|---|
| `pflow mcp add --transport sse --url https://… --name weather --token-env PFLOW_WEATHER_TOKEN` | Append entry, fetch manifest, generate wrappers. | 
| `pflow mcp launch <name>` | For `stdio/uds/pipe` entries: spawn process, record PID, health‑probe `/server/info`. | 
| `pflow mcp daemon` | On start, iterate registry, autostart flagged servers, restart on death. | 
| `pflow mcp list` | Show status: online/offline, version drift, tool count. | 

---

## 6 Wrapper Generation Algorithm

1. Resolve server entry.

2. Connect via chosen transport.

3. Call `/tools/list`; obtain `tool`, `inputSchema`, `outputSchema`, `version`, `scopes`.

4. For each tool produce:

```json
class Mcp_<tool>(Node):
    server_id   = "weather-remote"
    tool_name   = "get_weather"
    tool_version = "1.2.4"
    manifest_sha = "5c0…"
    side_effects = ["network"]  # read‑only by default

```

1. Write to `~/.pflow/nodes/mcp_weather_`[`get.py`](get.py) and register.

2. Add host to `~/.pflow/egress.allow` (for remote transports).

---

## 7 Executor Logic (per transport)

```python
if transport == "stdio":
    proc = ensure_running(server)
    proc.stdin.write(json.dumps(req)+"\n"); proc.stdin.flush()
    resp = json.loads(proc.stdout.readline())
elif transport == "uds":
    async with aiohttp.ClientSession(connector=connector) as s:
        resp = await s.post("http://unix/socket/tools/call", json=req)
elif transport in ("sse", "stream-http"):
    with httpx.stream("POST", server.url, json=req, headers=headers, timeout=30) as s:
        for chunk in s.iter_text():
            if chunk.startswith("data:"):
                resp = json.loads(chunk[5:]); break

```

- Fail if `tool_version` mismatch.

- Validate `resp` against stored `outputSchema` using `pydantic`.

---

## 8 Security Model

### 8\.1 Auth

- `token_env` names env var; absence aborts.

- stdio servers inherit env directly; remote transports send `Authorization: Bearer <token>`.

### 8\.2 TLS & Pinning

- `sse`/`stream-http`: refuse `http:`. CLI flag `--insecure` bypasses for dev.

- Optional pin file `~/.pflow/certs/<name>.pem`; wrapper sets `verify=that_file`.

### 8\.3 Scope Enforcement

- Wrapper records required scopes; `/server/info` exposes token scopes. Mismatch aborts.

### 8\.4 Side‑effect classification

- All remote tools default to `impure`; caching disabled, retry controlled by `exec.retries`.

- Mark tool as `pure` only if manifest `readonly=true` and user adds `--trust-pure` at install.

### 8\.5 Egress control

- Host allow‑list file; executor denies other hosts even if node attempts.

---

## 9 Failure Semantics

| Error | stdio response | sse/stream response | 
|---|---|---|
| Process missing | Suggest `pflow mcp launch` | n/a | 
| Broken pipe | Restart once, then fail | n/a | 
| TLS fail | n/a | abort | 
| 5xx | n/a | retry if `exec.retries` set | 
| Schema mismatch | abort flow | abort flow | 
| Timeout | user‑configurable retry | same | 

---

## 10 Cursor‑style Examples in pflow Syntax

### 10\.1 Local Node.js stdio server

```json
{
  "servers": {
    "gh": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "mcp-github"],
      "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
      "autostart": true
    }
  }
}

```

`pflow mcp launch gh` automatically spawns the server at runtime.

### 10\.2 Local Python stdio server

```json
{
  "servers": {
    "mem": {
      "transport": "stdio",
      "command": "python",
      "args": ["mcp_mem.py"],
      "autostart": true
    }
  }
}

```

### 10\.3 Remote SSE server

```json
{
  "servers": {
    "stripe": {
      "transport": "sse",
      "url": "https://billing.example.com/sse",
      "token_env": "STRIPE_MCP_KEY"
    }
  }
}

```

### Using in a flow

```bash
pflow mcp_github.search_code --query "TODO" >> summarize >> mcp_stripe.create_customer

```

Under the hood, wrappers route calls, validate scope, and respect transport details.

---

## 11 Testing

- Provide mock stdio server fixture; unit tests use `PFLOW_MCP_MOCK=1` to inject a fake process.

- Integration tests spin containerized SSE server and verify wrapper generation, scope mismatch handling, TLS enforcement.

---

## 12 Open Items for v1.1+

- PKI signature verification for manifests.

- Container image checksum pinning.

- GUI registry editor.

- Dynamic transport upgrade: transparently switch stdio→sse for team‑shared servers.