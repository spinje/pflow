# pflow × MCP Orchestration — consolidated note

## 0) TL;DR recommendation

* Use a **persistent MCP gateway** and treat `pflow` as an **ephemeral client** that attaches to it. This avoids per-run cold starts, centralizes auth/secrets, and keeps your CLI stateless. ✅ *Architecture pattern* (our design guidance).
* Safest default today: **Docker MCP Toolkit/Gateway** (integrated, stable docs, easy client hookup). ✅ ([Docker Documentation][1])
* Most feature-rich OSS gateway with an active community: **IBM ContextForge** (alpha/early-beta; rich features; larger GH footprint). ✅/⚠️ (status alpha) ([GitHub][2])
* Make future switching trivial by isolating transports/auth/discovery behind a tiny **`McpDriver`** interface (below). ✅ *Design guidance*

---

## 1) The core pattern: ephemeral CLI → persistent gateway

**What we’re doing:** don’t spawn MCP servers inside `pflow` each run. Instead, point `pflow` at a long-lived gateway that keeps servers warm and aggregates auth, secrets, and tool discovery.

* **Docker MCP Toolkit/Gateway** provides exactly this: a gateway layer that aggregates many servers and exposes them to multiple clients over **stdio** or **streamable HTTP**. ✅ ([GitHub][3])
* **Why it helps:** single connection point; consistent config across clients; secrets & OAuth handled centrally. (*Benefit statement is our inference from the gateway feature set.*) ⚠️ *inference* ([GitHub][3])

---

## 2) Gateway options you can standardize on

### A) Docker MCP Toolkit/Gateway (recommended default)

* **What it is:** a gateway baked into Docker Desktop; CLI plugin `docker mcp` also available. ✅ ([Docker Documentation][1])
* **Transports:** `docker mcp gateway run` (stdio) or `--transport streaming` for HTTP; suitable for ephemeral clients attaching/detaching. ✅ ([GitHub][3])
* **Catalog & custom servers:** Docker’s **MCP Catalog** + CLI let you import catalogs and enable servers:

  ```bash
  docker mcp catalog import <alias|url|file>
  docker mcp server enable <server-name>
  ```

  ✅ ([Docker Documentation][4])
* **OAuth & secrets:** Built-in **`docker mcp oauth`** commands (authorize/list/revoke). ✅ ([Docker Documentation][5])
  **Note:** Toolkit docs currently call out **GitHub OAuth** as supported “for now.” Broader provider support may depend on the specific server and/or evolve over time. ✅/⚠️ (provider scope) ([Docker Documentation][1])

### B) IBM **ContextForge** MCP Gateway (feature-rich OSS)

* **What it is:** a FastAPI-based **gateway + registry + proxy**, wraps MCP and REST; includes admin UI, rate-limits, retries, federation, OpenTelemetry, and multi-transport bridges (stdio/SSE/streamable HTTP). ✅ ([GitHub][2])
* **Project status:** README labels current release as **alpha/early beta**; evaluate before production. ✅/⚠️ (alpha) ([GitHub][2])
* **Auth/OAuth:** project docs/issues and community posts discuss built-in auth and SSO/OAuth configurations; Google SSO tracked in issues. **We haven’t validated a turnkey Google Docs flow end-to-end here.** ⚠️ *partially verified* ([GitHub][2])

### C) Open WebUI **mcpo** (MCP → OpenAPI proxy)

* **What it is:** a simple proxy that turns any MCP server (stdio/SSE/streamable-http) into **OpenAPI** endpoints; handy if your app stack prefers plain HTTP/OpenAPI. ✅ ([GitHub][6])

### D) **Octelium** (zero-trust platform with MCP gateway infra)

* **What it is:** OSS, K8s-native, identity/OPA-policy, OAuth2-centric infra that can front **MCP gateways** and AI/API workloads. Useful when you need zero-trust access, policy, and telemetry across networks. ✅ ([GitHub][7])

---

## 3) Adoption snapshot (GitHub stars ≈ community signal)

*(Numbers change frequently; verified today, Sep 15, 2025.)*

* **ContextForge:** \~**2.4k★**, \~**294 forks**. ✅ ([GitHub][2])
* **Docker MCP Gateway repo:** \~**541★**, \~**64 forks** (note: many real users via Docker Desktop beyond GH stars). ✅/⚠️ (*stars verified; usage scale inference*) ([GitHub][3])
* **Open-WebUI `mcpo`:** \~**3.3k★**, \~**368 forks**. ✅ ([GitHub][6])
* **MCP Registry (official):** \~**4.2k★**; preview announced **2025-09-08**. ✅ ([GitHub][8])
* **Octelium:** \~**2.3k★**, \~**68 forks**. ✅ ([GitHub][7])

---

## 4) OAuth and connecting to services (e.g., Google Docs)

* **Docker Toolkit/Gateway:** has **built-in OAuth commands**; docs **explicitly** call out **GitHub OAuth** “for now.” For Google Docs/Drive, you’d typically run a **Google-enabled MCP server** and let the gateway/client handle OAuth via that server’s flow. ✅/⚠️ (GitHub = verified, Google = depends on server) ([Docker Documentation][5])
* **ContextForge:** advertises built-in auth + SSO patterns; **issues discuss Google OAuth**. We haven’t validated a turnkey Google Docs setup ourselves here—treat as **partially verified**. ⚠️ ([GitHub][2])
* **General ecosystem note:** multiple guides show OAuth for MCP servers/gateways (Auth0/Ory/Zuplo/etc.). These demonstrate feasibility but aren’t endorsements of a specific production path for `pflow`. ✅/⚠️ (ecosystem examples) ([Medium][9])

---

## 5) Adding **custom MCP servers** in Docker Desktop

Yes—use the **catalog** commands, then **enable** them.
Typical flow:

```bash
# import/initialize catalogs
docker mcp catalog import ./my-catalog.yaml
docker mcp catalog ls
docker mcp catalog show my-catalog

# enable your server(s)
docker mcp server enable <your-server-name>
```

✅ ([Docker Documentation][10])

---

## 6) `pflow` integration plan (concrete)

### 6.1 Define a tiny seam so adding a second orchestrator is trivial

```ts
export interface McpDriver {
  connect(): Promise<Session>
  listTools(s: Session): Promise<ToolMeta[]>
  callTool<T=unknown>(s: Session, toolId: string, args: any, opts?: {stream?: boolean}): AsyncIterable<T> | Promise<T>
  openResource(s: Session, uri: string): Promise<Uint8Array>
  getToken?(scopes: string[]): Promise<{accessToken: string, expiresAt?: number}>
  dispose(s: Session): Promise<void>
}
```

Implement:

* `DockerGatewayDriver` (stdio or streamable-HTTP; tokens via `docker mcp oauth` or env). ✅ (CLI features verified) ([GitHub][3])
* `ContextForgeDriver` (HTTP/SSE; tokens via its auth config or your provider). ✅/⚠️ (CF auth patterns broadly documented; specifics vary) ([GitHub][2])

**Keep** session lifecycle, retries/backpressure, and tool caching in `pflow` core so drivers stay thin. ✅ *Design guidance*

### 6.2 Client/runtime behavior

* On start, `connect()` to the gateway (stdio if local; streamable-HTTP if remote). ✅ (transport options verified) ([GitHub][3])
* Discover tools once per session; cache signatures. ✅ *Design guidance*
* Normalize streaming to `AsyncIterable<Chunk>` regardless of backend event shape. ✅ *Design guidance*
* Add `--mcp-driver=docker|contextforge|http|stdio` and fallback to env (`MCP_GATEWAY=...`). ✅ *Design guidance*

---

## 7) Security & operational notes

* **OAuth “gotchas” are real** (discovery/endpoint abuse). Docker has publicly documented OAuth-related risks in the MCP ecosystem; review before exposing gateways. ✅ ([Docker][11])
* Prefer **gateway-brokered secrets/OAuth** over sprinkling tokens in envs. ✅ *Best-practice inference from toolkit & gateway design* ([GitHub][3])
* For teams, consider **Octelium** (zero-trust, OPA policies, OTel) to front remote MCP servers across networks. ✅ ([Octelium][12])

---

## 8) What we’re **confident** about vs. **marking unverified**

**✅ Verified (with sources):**

* Docker MCP Toolkit/Gateway exist, support stdio & streamable-HTTP, and integrate with Desktop; `docker mcp` CLI has OAuth & catalog/server commands. ([Docker Documentation][1])
* Docker docs note **GitHub OAuth** support “for now.” ([Docker Documentation][1])
* IBM ContextForge repo exists; feature set; **alpha/early-beta** status in README. ([GitHub][2])
* Open WebUI `mcpo`, MCP Registry, and Octelium projects exist with the star/fork counts shown above (today). ([GitHub][6])

**⚠️ Marked unverified / partial:**

* **“Turnkey” Google Docs OAuth** via Docker Toolkit or ContextForge as a one-click path. Feasible with a Google-enabled MCP server, but exact out-of-box flows vary by server and client; treat as **requires setup**. (We cited general OAuth capability and Google SSO discussions, not a tested recipe.) ([Docker Documentation][1])
* **“Servers stay warm = zero cold start”** is an **inference** from the gateway pattern; actual warmness depends on how you run/scale servers behind the gateway. ⚠️ *inference*
* Any claims beyond the docs/READMEs (e.g., total catalog size or partner lists) should be re-checked at time of use. ⚠️ *dynamic info*

---

## 9) Quick start snippets you can drop in

### Docker Gateway (stdio) for local dev

```bash
# Start (stdio for local ephemeral CLI)
docker mcp gateway run

# Or HTTP (streamable) on port 8080
docker mcp gateway run --port 8080 --transport streaming
```

✅ ([GitHub][3])

### Add a custom server via catalog

```bash
docker mcp catalog import ./docker-mcp.yaml
docker mcp server enable my-custom-server
```

✅ ([Docker Documentation][4])

### Do an OAuth handshake (where supported)

```bash
docker mcp oauth ls
docker mcp oauth authorize <app>   # e.g., github
```

✅ ([Docker Documentation][5])

---

## 10) If/when you want two gateways side-by-side

Because `pflow` talks to an abstract `McpDriver`, adding **ContextForge** after **Docker** (or vice-versa) is mostly wiring: implement the driver, map auth, and reuse the same planner/workflow and tests. ✅ *Design guidance*

---

If you want, I can turn this into a printable one-pager or add a minimal `McpDriver` scaffold for your codebase.

[1]: https://docs.docker.com/ai/mcp-catalog-and-toolkit/toolkit/?utm_source=chatgpt.com "Docker MCP Toolkit"
[2]: https://github.com/IBM/mcp-context-forge "GitHub - IBM/mcp-context-forge: A Model Context Protocol (MCP) Gateway & Registry. Serves as a central management point for tools, resources, and prompts that can be accessed by MCP-compatible LLM applications. Converts REST API endpoints to MCP, composes virtual MCP servers with added security and observability, and converts between protocols (stdio, SSE, Streamable HTTP)."
[3]: https://github.com/docker/mcp-gateway "GitHub - docker/mcp-gateway: docker mcp CLI plugin / MCP Gateway"
[4]: https://docs.docker.com/reference/cli/docker/mcp/catalog/catalog_import/?utm_source=chatgpt.com "docker mcp catalog import"
[5]: https://docs.docker.com/reference/cli/docker/mcp/oauth/?utm_source=chatgpt.com "docker mcp oauth"
[6]: https://github.com/open-webui/mcpo "GitHub - open-webui/mcpo: A simple, secure MCP-to-OpenAPI proxy server"
[7]: https://github.com/octelium/octelium "GitHub - octelium/octelium: A next-gen FOSS self-hosted unified zero trust secure access platform that can operate as a remote access VPN, a ZTNA/BeyondCorp architecture, API/AI gateway, a PaaS, an infrastructure for MCP & A2A architectures or even as an ngrok-alternative and a homelab infrastructure."
[8]: https://github.com/modelcontextprotocol/registry "GitHub - modelcontextprotocol/registry: A community driven registry service for Model Context Protocol (MCP) servers."
[9]: https://medium.com/neural-engineer/mcp-server-setup-with-oauth-authentication-using-auth0-and-claude-ai-remote-mcp-integration-8329b65e6664?utm_source=chatgpt.com "MCP Server Setup with OAuth Authentication using Auth0 ..."
[10]: https://docs.docker.com/reference/cli/docker/mcp/catalog/?utm_source=chatgpt.com "docker mcp catalog"
[11]: https://www.docker.com/blog/mcp-security-issues-threatening-ai-infrastructure/?utm_source=chatgpt.com "MCP Security Issues Threatening AI Infrastructure"
[12]: https://octelium.com/solutions/open-source-mcp-gateway?utm_source=chatgpt.com "Open Source, Self-Hosted, Secure MCP Gateway"

*Written by https://chatgpt.com/g/g-p-68b58af43cc481919527300bc5218d4d-pflow/c/68c801f4-abc8-8330-b897-91819de5ef7d?model=gpt-5-thinking*