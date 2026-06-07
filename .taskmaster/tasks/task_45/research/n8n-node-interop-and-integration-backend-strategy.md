# Research: n8n Node Interop & Managed-Integration Backend Strategy

**Date**: 2026-06-07
**Status**: 🅿️ **SHELVED — do not build yet.** Revisit only after the core pflow loop is great *and* validated by real users (see "When to revisit").
**Task**: 45 — *Evaluate if wrapping n8n is worth the effort*
**Supersedes (in framing)**: `n8n-wrapper-vs-pure-pflow-decision.md` (Jan 2025), which debated a full *engine pivot* (pflow's runtime = n8n). That question is stale. This doc asks a narrower, better one and then generalizes it.

> **Self-contained on purpose.** Written so a future reader — you with no memory of this, or another agent — can act without re-researching. Technical reference artifacts are in the Appendices; the strategic verdict is Part 5.

---

## TL;DR (read this first)

1. **The original question was wrong-shaped.** We are *not* asking "should pflow's engine become n8n." We asked: "can n8n's **node library** be reused inside pflow's existing engine?" — node-level interop, additive, not a pivot.
2. **Technically very feasible with ~zero pflow core changes**, because pflow already speaks MCP in both directions. Any bridge rides the existing `mcp-<server>-<tool>` seam and is fully reversible (`pflow mcp remove n8n`).
3. **The real feature isn't "n8n." It's "pflow workflows reach thousands of external services with managed auth, agent-discoverable."** n8n is *one possible backend*. Several others fit pflow's agent-first persona better with far less code.
4. **For a "bring-your-own, free, self-hosted" backend, [Activepieces](https://github.com/activepieces/activepieces) (MIT, MCP-native) probably beats n8n** — no fair-code license worry, no wrapper-provisioning dance, MCP-native. n8n's only edge over it is community size/mindshare.
5. **For zero-setup hosted breadth, Composio / Pipedream Connect / Zapier MCP** solve OAuth-as-a-service and are already MCP. (Trade: cost + dependency; Pipedream is being acquired by Workday.)
6. **n8n's *only* unique edge is distribution** — into the existing n8n community. That's a marketing/ethos bet, **not** a capability bet.
7. **⚠️ Known feasibility blocker for the "headless auto-provision" vision:** activating a workflow via n8n's REST API does **not** register its webhook path ([n8n #21614](https://github.com/n8n-io/n8n/issues/21614)); the workaround needs a UI save. So fully-headless per-node wrapper provisioning is **not currently reliable**. "Whole workflows as nodes" (human activates once in UI) still works.
8. **The credential/OAuth wall is lower than first assumed.** API-key / token / basic / header-auth integrations provision **fully headlessly** via n8n's REST API. Only OAuth2 needs a one-time human "connect" click per service.
9. **Why shelved:** pflow has ~0 users. Integrations *amplify* a product people already want; they don't *create* the want. Breadth-before-desire is the pre-PMF trap. Get the core loop loved by the first ~10 users first.

---

## Why this is shelved (the gating precondition)

Building any integration-breadth backend (n8n or otherwise) **before** the core pflow loop is desirable is solving a *theorized* problem ("users will want thousands of integrations") before validating the *observed* one ("does anyone want agent-driven CLI workflows at all?"). With ~0 users, the highest-leverage question is **"what makes the first 10 people use pflow twice?"** — not "how do I reach thousands of integrations."

**Precondition to revisit:** the core loop is great AND a handful of real users use it repeatedly. Only then does an integration backend amplify *real* demand instead of decorating its absence.

---

## Part 1 — The reframe (how the question evolved)

| Framing | Question | Verdict |
|---|---|---|
| Old (Jan 2025) | Should pflow's *execution engine* be replaced by n8n's? | Stale. pflow now has a solid 7-node engine + MCP. Pivot not on the table. |
| Mid (this convo) | Can n8n's *nodes* be made usable *as pflow nodes*, keeping pflow's engine? | Yes, feasible, ~0 core changes. But heavy + persona-mismatched. |
| **Final (this convo)** | What's the best **backend** for "pflow reaches 1000s of services with managed auth, agent-discoverable"? n8n is one option among better-fit ones. | **This is the right question. Design the seam generically; pick the cheapest backend to validate demand first. n8n/Activepieces = later BYO backends.** |

---

## Part 2 — Verified technical findings

### 2.1 How n8n nodes actually work (why "run a bare node" is the wrong mental model)

- An n8n "node" is **not** a standalone function. It's a TS class whose `execute()` expects n8n's runtime to hand it a context object (`this.getNodeParameter()`, `this.getCredentials()`, `this.helpers.httpRequest()`, item arrays in/out).
- Two flavors: **programmatic** (imperative `execute`) and **declarative** (a `routing` block ≈ a REST spec the n8n engine executes).
- **n8n executes *workflows*, never bare nodes.** A workflow needs a *trigger*. To run node X and get its value out, you need at minimum `[trigger] → [X] → [respond]`. This wrapper *can* be created programmatically via the REST API — but see §2.8 for a blocker.
- **Credentials are n8n's real moat** for this purpose. Central design axis for any approach: **keep n8n's runtime (inherit credentials free) vs bypass it (rebuild credentials yourself).**

### 2.2 The two different "n8n MCPs" (CRITICAL — easy to conflate)

- **(A) n8n's *native* MCP Server Trigger node** — n8n acts *as* an MCP server, exposing a **hand-wired, curated set of tools** you explicitly attach. Docs: it "only connects to and executes **tool** nodes." It does **not** reflect the global catalog and does **not** let you browse/create. *This is why a native-trigger approach cannot expose all nodes — it's curate-by-hand.* Escape hatch for arbitrary capability: the **Custom n8n Workflow Tool** node (wrap a sub-workflow, expose it). Supported trigger types for exposed workflows: Webhook, Chat, Form, Manual, Schedule. Transports: **SSE and streamable HTTP**.
- **(C) The community `n8n-mcp` project** (czlonkowski, MIT) — a *separate* MCP server giving an agent: (1) **node discovery** (`search_nodes`, `get_node_essentials`) over **~1,851 indexed nodes** incl. community; (2) with an API key, **workflow management** (`n8n_create_workflow`, `update`, `validate`, `autofix`, `list`, `delete`, trigger-via-webhook).
- **The "see nodes → create/execute a workflow" capability = (C), not (A).**

### 2.3 pflow's MCP architecture (the seam any bridge would ride) — verified in-codebase

- MCP servers registered **globally** in `~/.pflow/mcp-servers.json` (`pflow mcp add`); tools discovered at `pflow mcp sync`; each becomes a **virtual node type `mcp-<server>-<tool>`** referenced in `.pflow.md`. One universal `MCPNode` class backs all of them. Files: `src/pflow/nodes/mcp/node.py`, `src/pflow/mcp/manager.py`, `src/pflow/runtime/compilation/mcp_resolution.py`.
- **Transports**: local **stdio** subprocess and **streamable HTTP** (`streamablehttp_client`) with auth headers (`node.py:228-362`). ⚠️ pflow uses **streamable HTTP, not SSE** — older n8n MCP triggers were SSE-only; confirm the n8n version exposes streamable HTTP, or pflow would need SSE support (build-time check, Appendix B).
- Tool `inputSchema`/`outputSchema` captured at sync, converted to pflow param metadata (`src/pflow/mcp/discovery.py`); `structuredContent` is the preferred output path; text results auto-parsed as JSON. Schemas inform authoring/validation but are **not** a hard runtime gate (inferred — see Part 6).
- **Connection pool** keeps one session alive **per server name**, **per workflow run** (torn down at run end) (`src/pflow/mcp/pool.py`). With an HTTP backend this is moot — the backend is the persistent process.
- **Auto-sync on `pflow run`** (smart sync on config mtime+hash). `${VAR}` / `${VAR:-default}` expansion for env/auth.
- **pflow-as-MCP-server** (`src/pflow/mcp_server/`) exposes 13 meta-tools (execute/validate/discover/save workflows) to external agents — not individual saved workflows (that's planned Tasks 90/91).
- **Net: a bridge = "just another MCP server." Zero pflow core changes. Fully reversible.**

### 2.4 Node counts ("aren't there thousands?")

Yes. ~400 marketed integrations; **1,000–1,300+** counting operations + community nodes; `n8n-mcp` indexes **~1,851**.

### 2.5 Node-catalog introspection (constraint that bites)

- **No public REST API to list node types.** The catalog lives in either the **internal `/rest/node-types`** endpoint (editor-only, session/JWT auth, **unstable** across versions, includes the instance's installed community nodes) **or** a **bundled static dataset** parsed from n8n's npm packages (what `n8n-mcp`'s `nodes.db` is).

### 2.6 `nodes.db` (the "just take the db" idea)

- A **SQLite metadata file** built by n8n-mcp's `src/scripts/rebuild-database.ts` from n8n's npm packages. **Knowledge only — zero execution capability.**
- "I don't need the mcp" is **true for the knowledge half**: read the SQLite directly. But you **still need a running n8n + REST API to execute**.
- **Three caveats on vendoring it:** (1) **staleness treadmill** — pinned to an n8n version, misses installed community nodes, you own refresh; (2) **license** — n8n-mcp *code* is MIT, but the node definitions + **documentation text** derive from n8n's source under the **Sustainable Use License (fair-code, not OSI-open)** → redistributing docs text is a derivative-work question, **flagged not legally confirmed**; (3) knowledge-only.
- **Better for the "isolated feature" goal:** read metadata from the live instance's `/rest/node-types` (version-matched, includes community nodes), or **hybrid** (live, fall back to vendored db for offline browse). Or sidestep entirely by using an **MCP-native backend** (Activepieces/Composio) where the catalog *is* the MCP `tools/list`.
- **Study n8n-mcp's source regardless** — it solved the two hardest pieces: `rebuild-database.ts` (param-tree → flat schema extraction across `resource`/`operation`/`displayOptions`) and the `n8n_create_workflow` path (valid workflow JSON: nodes, connections, positions). Reference implementations; don't depend at runtime.

### 2.7 Credentials via API (the auth question — better than first assumed)

- `POST /api/v1/credentials` exists. Splits cleanly:
  - **API-key / token / basic / header-auth → fully programmable, headless.** Secret in the payload. No browser. Covers a *large* fraction of integrations.
  - **OAuth2 → partial.** Create the credential *record* via API (clientId/clientSecret), but **authorization** needs a one-time browser sign-in at n8n's Credentials dashboard ("users must visit the n8n Credentials dashboard to complete the OAuth sign-in for each newly created credential"). OAuth2 POST also has known schema-validation friction. *Not an n8n limitation — OAuth consent fundamentally requires a human at the provider.*
  - **Exception:** OAuth2 **client-credentials** grant (machine-to-machine, no user consent) may be fully automatable — narrower subset.
- `GET /credentials/schema/{type}` tells you required fields. Reading credential *data* back is restricted.
- **Design impact:** for **API-key integrations**, the *credential* half is fully headless. ⚠️ But the *wrapper-workflow* half is **not** reliably headless — see §2.8.

### 2.8 n8n REST API: access, execution mechanics, and the headless blocker (NEW)

- **Edition/access:** The public REST API **is available in self-hosted community edition** (free). Create an API key in **Settings → n8n API**; send it as header **`X-N8N-API-KEY`**. **Non-enterprise keys have full access** to all resources (scoped keys are enterprise-only). *(Mild ambiguity in sources: one said "API control available in starter plans and above" — that refers to n8n **Cloud** tiers; self-hosted community edition exposes the API. Re-confirm at build time, Appendix B.)*
- **Webhook URLs:** the Webhook node exposes two — `/webhook-test/<path>` (only works while the editor is open & listening) and `/webhook/<path>` (production; **requires the workflow to be active**).
- **Management trigger:** sources reference `/api/v1/workflows/:id/execute` as an API-key-protected trigger — **but this conflicts with prior knowledge that the public API has no execute endpoint** (you trigger via webhook). **Verify at build time (Appendix B).**
- **🚨 BLOCKER — webhook path not registered on API activation:** [n8n issue #21614](https://github.com/n8n-io/n8n/issues/21614) — creating + activating a workflow via the REST API does **not** register the webhook path, so the production webhook 404s; the documented workaround is to **save once via the UI**. **This breaks fully-headless per-node wrapper auto-provisioning** (the most ambitious "agent provisions on demand" vision). Implications:
  - **"Whole workflows as nodes" still works** — the human builds + activates the workflow once in the UI (Phase 1a).
  - **Per-node headless provisioning is currently unreliable** until #21614 is resolved or a workaround exists (e.g., a real execute endpoint, or programmatic re-save). Don't design Phase 1b/2 assuming headless activation works without confirming this.
  - **MCP-native backends sidestep this entirely** — Activepieces/Composio expose tools without the webhook-activation dance. Another point in their favor.

---

## Part 3 — Implementation option space (the HOW, if ever built)

| # | Approach | Code | Credentials/OAuth | Coverage | Fragility |
|---|----------|------|-------------------|----------|-----------|
| 1 | **n8n native MCP Server Trigger → pflow `mcp` node** | ~none | Free (n8n UI) | What you wire as tools (curated) | Low |
| 2 | **pflow-native n8n provider over REST API** (auto-provision `[Webhook]→[Node]→[Respond]`) | Medium | Free; API-key headless, OAuth 1-click | Arbitrary nodes, dynamic | **Med-High (blocked by #21614 for headless)** |
| 3 | **Embedded minimal runtime** (`n8n-core`/`n8n-workflow`/`n8n-nodes-base` in a Node sidecar) | High | **You rebuild it** | Arbitrary, auth-light only | High (rides n8n internals) |
| 4 | **Declarative-node transpiler → native pflow `http` nodes** | Medium | **You rebuild it** | Declarative subset only | Medium |
| 5 | **MCP-native automation backend (Activepieces / Composio / Zapier MCP)** — no n8n at all | ~none | Backend-managed | Broad | Low |
| 6 | **Null option: standalone single-service MCP servers** | none | per-server | The well-covered integrations | Low |

**Recommended HOW (if/when built):** prefer **Option 5** (MCP-native backend) — it rides pflow's seam with ~no code and dodges both the credential-rebuild trap *and* #21614. Use **Option 1** if specifically targeting the n8n community. Avoid 3/4 (rebuild the credential moat; 3 rides internals). Treat **Option 2** as gated on #21614.

### 3.1 Two tiers of difficulty (key insight)

- **Whole workflows as pflow nodes = the easy, robust win.** Author already defined input (webhook body) + output (response). pflow just registers it. **No schema flattening, no generic binding, no per-node provisioning, not blocked by #21614** (human activates once). **Start here.**
- **Every individual node as a pflow node = the ambitious phase.** All hard walls apply: schema flattening (resource/operation/`displayOptions`), generic param→expression binding, credential gating, per-node wrapper provisioning, the unstable catalog, **and #21614**.

### 3.2 Knowledge vs execution split

`nodes.db` / `/rest/node-types` = **knowledge** (what nodes/params exist). A **running n8n + REST API** = **execution**. Need both, from different sources. (MCP-native backends collapse this — the MCP server is both.)

### 3.3 Isolation boundary (the user's instinct — correct)

Build a self-contained **`pflow n8n` (or `pflow integrations`) provider** (CLI command group + node-registration path) that activates **only when configured**, touching **nothing** in core. Aligns with pflow's architecture guidance (deep module behind a small interface; concentrate complexity in one place; keep it deletable). Do **not** thread backend awareness through the engine.

---

## Part 4 — Phasing (if/when un-shelved)

- **Phase 1a** — Whole existing n8n/Activepieces workflow → pflow node. Days, low risk, exercises credentials end-to-end, not blocked by #21614. Proves the loop.
- **Phase 1b** — Individual **API-key** nodes, auto-registered. *Gated on #21614 for n8n*; trivial on an MCP-native backend.
- **Phase 2** — OAuth nodes: same machinery + a one-time "go authorize this in the backend" handoff.
- **Phase 3** — Schema-flattening generality for the long tail, only if demand is proven.

---

## Part 5 — Strategic assessment (the WHETHER/WHEN — most important)

### 5.1 The real feature is managed integration breadth, not "n8n"

The need underneath both this idea and the roadmap's "MCP Server Discovery" (Tasks 81/86) is: **"my agent-built pflow workflows should reach external services without me hand-wiring auth + HTTP per service."** n8n is one way; not the best-fit way for pflow's persona.

### 5.2 Backend landscape (so we never re-survey this)

| Backend | Setup for user | Auth/OAuth | License / cost | MCP-native? | Persona fit | Notes / unique edge |
|---|---|---|---|---|---|---|
| **Activepieces** | Self-host *or* cloud | Backend-managed | **MIT** (open-core), free self-host | **Yes** (~280+ pieces as MCP) | **Strong** | **Best "BYO free self-hosted" fit.** No fair-code worry, no webhook-wrapper dance. 300+ contributors. |
| **n8n (BYO)** | Heavy (self-host) | Their vault; OAuth = 1-click/service | Fair-code (Sustainable Use Lic.); free self-host | Partial (native trigger curated) | Mismatch (no-code crowd) | Largest community/mindshare → distribution. ⚠️ #21614 blocks headless provisioning. |
| **Composio** | Hosted dashboard | **End-to-end managed OAuth, per-user-scoped tokens**; SOC2+ISO27001 | Paid SaaS; closed tools | **Yes** (+ SDK) | **Strong** | 500+ AI-optimized toolkits. "Tool Router" = per-session user-scoped MCP URL (mitigates the static-`client_id` vuln, §5.3). Can't modify tools. |
| **Pipedream Connect** | Hosted | Managed auth, OAuth client mgmt, token refresh | Paid SaaS | **Yes** | Strong | ~2,700+ apps. ⚠️ **Being acquired by Workday** → continuity/dependency risk. |
| **Zapier MCP** | Hosted, non-technical | Pre-authenticated, hosted OAuth | Paid SaaS | **Yes** | Medium (least technical) | **9,000+ apps / 40,000+ actions** — most breadth, least setup. |
| **Nango** | Hosted/self-host | Unified auth/integrations infra | Open-core | Via SDK | Dev-focused | Composio alternative; more "auth infra" than "tool catalog". |
| **Build your own** | Light (for user) | You build OAuth infra | Your time | Yes | Strong | **Company-sized.** Full control, no dependency. Not a pre-users move. |

**Reading across:** for pflow's agent/CLI-first persona, an **MCP-native backend rides the existing seam with ~no code and solves OAuth as a service.** Among "free + self-hosted + BYO," **Activepieces (MIT, MCP-native) is the standout** and likely dominates n8n for pflow — n8n's residual advantage is purely *community distribution*. So n8n-as-backend is a **distribution/ethos bet, not a capability bet.**

### 5.3 Security constraint for ANY MCP backend (applies even to a home-grown one)

Late-2025 (Obsidian Security) disclosed **one-click account-takeover vulnerabilities in remote MCP servers**. Root cause: MCP servers implemented as **OAuth proxies using a single static `client_id`** to the upstream SaaS. Mitigation = **per-user / per-session user-scoped tokens & URLs** (Composio's Tool Router model). If pflow ever exposes a hosted integration backend, this is a hard design requirement; if it consumes one, prefer backends that scope tokens per user.

### 5.4 The case against building any of this now

1. **Amplifier, not creator.** Integrations amplify demand that exists; they don't create it. pflow has ~0 users.
2. **Competes with backends' own first-party reach.** n8n users wanting agent access already have the native MCP trigger; Zapier/Composio already ship MCP. pflow's wedge is the *narrow* "X + CLI-native + git-native workflows."
3. **Persona mismatch (n8n specifically).** n8n's audience self-selected for visual/no-code. Addressable = (self-host n8n) ∩ (want CLI/agent workflows) — thin slice of a thin slice.
4. **Prerequisite burden.** "You must already run n8n" shrinks TAM and asks users to run two heavyweight systems.
5. **Opportunity cost.** Solo builder, pre-users. Schema flattening + wrapper provisioning + #21614 workarounds + staleness treadmill = weeks not spent making the core loop loved.

### 5.5 The case for (steelman — keep it honest)

- The n8n community is large, passionate, **underserved on the CLI/dev side**; "git-native, agent-driven CLI for your n8n integrations" is a novel angle n8n's no-code positioning won't serve.
- **"Bring your own" = zero marginal integration cost to you** and free for self-hosters; appeals to the self-hosting dev crowd that dislikes paid SaaS dependencies/lock-in (Composio/Zapier/Pipedream all carry that).
- Concrete, demoable wedge: *"point pflow at your n8n/Activepieces — your agent now uses hundreds of integrations from the terminal."*

### 5.6 Recommendation

1. **Design the seam, not the backend.** A generic "managed-integration provider" interface (discover → expose-as-node → managed auth). Backends are pluggable: Activepieces, n8n, Composio, raw MCP. This is "MCP Server Discovery" generalized — the durable, reversible piece.
2. **Validate demand with the cheapest MCP-native backend first** (Activepieces self-host for free/ethos fit, or Zapier MCP/Composio for fastest breadth) — near-zero code. If nobody uses integrations via the cheap path, the expensive n8n path would've been wasted.
3. **Prefer Activepieces over n8n for the BYO-self-hosted slot** (MIT, MCP-native, no #21614). Make **n8n a distribution-motivated backend** justified only once (a) the core has traction and (b) there's a signal the *n8n community specifically* wants a CLI/agent companion.
4. **Don't build your own auth backend now** — company-sized; revisit only if integration demand is proven *and* hosted backends' cost/lock-in becomes the actual blocker (and then heed §5.3).

### 5.7 The decision that hinges on your goal (only the human can answer)

**Is the goal to reach the *n8n community specifically* (distribution), or to give *pflow's agent persona* maximum integration breadth (capability)?**
- **Capability** → MCP-native backend (Activepieces / Composio / Zapier MCP) is the better, cheaper, better-fit first move; n8n is a distraction.
- **Distribution into the n8n crowd** → n8n-as-backend is the *point*, but a marketing wedge invested in *after* the core is proven — not the thing that creates the want.

Under both: **is the core pflow loop yet desirable enough that *any* backend would amplify real demand rather than decorate its absence?** If unsure, validate that first.

---

## Part 6 — Trust boundaries (per epistemic manifesto)

**Verified (file-grounded or doc/issue-confirmed):**
- pflow MCP client/server architecture, transports (streamable HTTP, not SSE), `mcp-<server>-<tool>` flattening, connection pool — traced to files/lines by `pflow-codebase-searcher`.
- n8n native MCP Server Trigger "only connects to tool nodes"; supports SSE + streamable HTTP — n8n docs.
- `n8n-mcp` tool surface + ~1,851 node count + MIT license — project README/search.
- No public node-types API; `/rest/node-types` is internal — n8n docs + community.
- `POST /api/v1/credentials` exists; OAuth2 needs dashboard sign-in — n8n community + template docs.
- Public REST API usable in self-hosted community edition; `X-N8N-API-KEY` header; non-enterprise keys = full access — n8n docs.
- **#21614: API activation doesn't register webhook path** — n8n GitHub issue (confirmed bug + UI-save workaround).
- Backend landscape facts (Composio per-user OAuth/Tool Router/closed tools; Klavis MCP-infra/SOC2; Pipedream Connect managed auth + **Workday acquisition**; Zapier MCP 9k apps/40k actions; Activepieces MIT/MCP-native/280+ pieces) — vendor + third-party sources, June 2026.
- OAuth-proxy static-`client_id` account-takeover vuln class (Obsidian Security, late 2025) — security reporting.

**Assumed correct (not independently traced):**
- pflow `registrar.py` exact registry-entry creation; pool teardown call sites in `execution/runner.py`; "schemas not a hard runtime gate." Flagged by the searcher as unverified.
- `nodes.db` exact schema/contents (described from build-script behavior, not opened).

**Unable to verify / needs a human or build-time check:**
- **License**: redistributing n8n-derived node docs under the Sustainable Use License. **Legal check required.**
- Whether public `/api/v1/workflows/:id/execute` actually works (conflicting signals) vs webhook-only triggering.
- Whether #21614 is still open at build time / whether a clean headless workaround exists.
- Exact `n8n-mcp` trigger/execute tool names (referenced generically).
- Current pricing / free tiers / self-host options of Composio, Klavis, Pipedream, Zapier MCP (fast-moving — re-verify).
- Activepieces MCP per-tool granularity, self-host effort, OAuth UX.
- Whether the target n8n version's MCP trigger exposes **streamable HTTP** (pflow doesn't do SSE).

---

## Part 7 — When to revisit (trigger conditions)

Pick this up **only** when **all** of:
1. The core pflow loop is genuinely good (agent creates/iterates/runs `.pflow.md` and it's delightful), **and**
2. Real users use it repeatedly (retention, not demos), **and**
3. Those users (or a target community) express a concrete need for broad managed integrations.

Then, in order:
1. Re-confirm the **goal** (capability vs distribution — §5.7).
2. Build the **generic provider seam** (§5.6.1).
3. Validate with the **cheapest MCP-native backend** (§5.6.2) — likely **Activepieces** (free/ethos) or **Zapier MCP/Composio** (fastest breadth).
4. Only if distribution into the n8n community is the goal **and** the core is proven → build the **n8n provider**, Phase 1a → 1b → 2 (§4), respecting **#21614** (§2.8).

---

## Appendix A — Reference artifacts & build-time cheat-sheet

> Confidence: medium. Shapes are from current knowledge; verify against then-current versions (Appendix B).

### A.1 Register an MCP backend with pflow (`~/.pflow/mcp-servers.json`)

```json
{
  "mcpServers": {
    "n8n": {
      "type": "http",
      "url": "https://your-n8n.example.com/mcp/<trigger-path>",
      "headers": { "Authorization": "Bearer ${N8N_MCP_TOKEN}" }
    },
    "activepieces": {
      "type": "http",
      "url": "https://your-activepieces.example.com/api/v1/mcp/<id>/sse",
      "headers": { "Authorization": "Bearer ${AP_TOKEN}" }
    }
  }
}
```
Then: `pflow mcp add ...` (or edit the file) → `pflow mcp sync` → tools appear as `mcp-n8n-<tool>` / `mcp-activepieces-<tool>`.

### A.2 Use the registered tool in a `.pflow.md`

```markdown
### post-to-slack
- type: mcp-n8n-slack_postMessage
- channel: "#general"
- text: ${summary.result}
```
Output lands in `shared["result"]`; downstream reads `${post-to-slack.result.<field>}`.

### A.3 n8n quick setup

- Run: `npx n8n` (or Docker `docker run -p 5678:5678 n8nio/n8n`). UI at `http://localhost:5678`.
- API key: **Settings → n8n API → Create**. Send as header `X-N8N-API-KEY: <key>`.
- Webhook URLs: `/webhook-test/<path>` (editor open only) vs `/webhook/<path>` (production, needs active workflow). ⚠️ #21614.

### A.4 n8n REST endpoint cheat-sheet (`/api/v1`, `X-N8N-API-KEY`)

- `GET/POST/PUT/DELETE /workflows`, `/workflows/{id}` — CRUD.
- `POST /workflows/{id}/activate` / `/deactivate` — ⚠️ doesn't register webhook (#21614).
- `GET /executions`, `/executions/{id}` — run history/results.
- `POST /credentials`, `GET /credentials/schema/{type}` — create creds / inspect required fields. (OAuth2 needs UI consent.)
- `/api/v1/workflows/{id}/execute` — *claimed* management trigger; **verify** (Appendix B).
- **No** node-types catalog endpoint (use internal `/rest/node-types` or `n8n-mcp`'s db).

### A.5 Wrapper-workflow shape (conceptual, for Option 2)

```
[Webhook Trigger]  ->  [Target Node]  ->  [Respond to Webhook]
  path: /run-X         params bound via       returns node output
  POST body = args     expressions:           as JSON
                       ={{ $json.<arg> }}
```
Per-node, provisioned once, activated, cached by node type. Generic `args → params` expression binding is the fiddly part. **Blocked headless by #21614** — needs UI save or resolution.

---

## Appendix B — Open questions to verify at build time (surgical, not from-scratch)

1. Is **#21614** resolved, or is there a reliable headless workaround (real execute endpoint / programmatic re-save)? *Gates Option 2 / Phase 1b.*
2. Does public **`/api/v1/workflows/{id}/execute`** actually run a workflow and return output, or is webhook-only the truth? (Conflicting signals.)
3. Is the public REST API truly enabled in **free self-hosted community edition** for the endpoints we need (workflows + credentials CRUD)? (Cloud-tier vs self-host ambiguity.)
4. **License**: can n8n-derived node docs be redistributed under the Sustainable Use License? (Legal.)
5. **Activepieces**: MCP per-tool granularity, self-host effort, OAuth UX, whether tools carry good JSON schemas for pflow discovery.
6. Current **pricing/free-tier/self-host** for Composio, Klavis, Pipedream Connect (note Workday acquisition), Zapier MCP.
7. `n8n-mcp` exact tool names for **trigger/execute** a workflow.
8. Does the target backend's MCP endpoint speak **streamable HTTP** (pflow) and not only SSE?
9. Does the chosen hosted backend scope OAuth tokens **per-user** (§5.3 security)?

---

## Appendix C — Decision log (considered & rejected/deferred)

| Option | Decision | Why |
|---|---|---|
| Replace pflow engine with n8n | **Rejected** | Stale framing; pflow has its own solid engine + MCP. |
| Embedded n8n runtime (n8n-core sidecar) | **Rejected** | Rebuilds the credential/OAuth moat; rides non-public internals; fragile. |
| Declarative-node transpiler → pflow http nodes | **Deferred** | Partial coverage (declarative only); re-owns auth. |
| Vendor `nodes.db` | **Deferred** | Staleness + fair-code license; prefer live endpoint or MCP-native backend. |
| Build own auth backend | **Rejected (for now)** | Company-sized; premature pre-users; security burden (§5.3). |
| Build any of this now | **Rejected** | ~0 users; amplifier-not-creator; opportunity cost. |
| n8n native MCP trigger (Option 1) | **Viable later** | ~0 code; but curate-by-hand; for n8n-community distribution. |
| n8n REST auto-provision (Option 2) | **Gated** | Blocked headless by #21614. |
| **MCP-native backend (Option 5: Activepieces / Composio / Zapier MCP)** | **Preferred direction** | ~0 code; solves OAuth; dodges #21614; persona fit. Validate demand here first. |
| Generic provider seam | **Chosen architecture** | Backends pluggable; reversible; = "MCP Server Discovery" generalized. |

---

## Sources

- pflow MCP capabilities — in-repo: `src/pflow/nodes/mcp/node.py`, `src/pflow/mcp/{manager,discovery,pool,registrar,auth_utils}.py`, `src/pflow/runtime/compilation/mcp_resolution.py`, `src/pflow/cli/commands/mcp.py`, `src/pflow/mcp_server/`.
- [MCP Server Trigger node — n8n Docs](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/)
- [Set up and use the n8n MCP server — n8n Docs](https://docs.n8n.io/advanced-ai/mcp/accessing-n8n-mcp-server/)
- [n8n-mcp (czlonkowski) — discovery + workflow management, ~1,851 nodes, MIT](https://github.com/czlonkowski/n8n-mcp)
- [n8n public REST API reference (no node-types endpoint)](https://docs.n8n.io/api/api-reference/)
- [n8n API authentication — X-N8N-API-KEY](https://docs.n8n.io/api/authentication/)
- [n8n community edition features](https://docs.n8n.io/hosting/community-edition-features/)
- [🚨 n8n #21614 — API activation doesn't register webhook path](https://github.com/n8n-io/n8n/issues/21614)
- [n8n Webhook node — test vs production URLs](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/)
- [Programmatic OAuth2 credential creation needs dashboard sign-in — n8n template](https://n8n.io/workflows/2909-automate-google-oauth2-credential-creation-in-n8n/)
- [POST /credentials OAuth2 schema friction — n8n Community](https://community.n8n.io/t/n8n-api-post-credentials-with-oauth2-data-schema/17543)
- [Composio — per-user OAuth for AI agents / Tool Router](https://composio.dev/content/per-user-oauth-for-ai-agents)
- [Klavis AI — MCP infrastructure](https://www.klavis.ai/)
- [Pipedream Connect](https://pipedream.com/connect)
- [Zapier MCP — 9,000+ apps](https://zapier.com/mcp)
- [Activepieces — open-source (MIT), MCP-native](https://github.com/activepieces/activepieces) · [Activepieces MCP](https://www.activepieces.com/mcp)
- [Composio alternatives (Nango et al.)](https://nango.dev/blog/composio-alternatives/)
- [n8n integration counts](https://vps.us/blog/how-many-n8n-integrations/)

---

## Related roadmap tasks

- Task 81 — Find/Install Remote MCP Servers
- Task 86 — MCP Server Discovery Automation
- Task 65 — MCP Gateway Integration
- Task 90/91 — Workflows as Remote HTTP MCP Servers / Export as MCP Server Packages

> These are the *generic* version of this idea. If anything here gets built, it should land as a **backend behind that generic provider seam** (§5.6.1), not as a bespoke n8n feature.
