# Task 45: Evaluate if wrapping n8n is worth the effort.

## Status
not started

> ⚠️ **Evaluated & shelved (2026-06-07).** No implementation started; intentionally deferred — revisit only after the core loop is great + user-validated. See below.

## Research & Decision (2026-06-07)
Full analysis: [`research/n8n-node-interop-and-integration-backend-strategy.md`](research/n8n-node-interop-and-integration-backend-strategy.md)
(supersedes the Jan-2025 `research/n8n-wrapper-vs-pure-pflow-decision.md` engine-pivot framing).

**One-line verdict:** The real feature is *managed integration breadth, agent-discoverable* — n8n is just one backend, and not the best-fit one. Design a generic provider seam; validate demand with the cheapest **MCP-native** backend first (Activepieces / Composio / Zapier MCP); treat n8n as a later *distribution* play. **Don't build pre-users.**

**Key facts captured (so we don't re-research):** pflow already speaks MCP both ways (zero core changes, reversible); n8n credential provisioning is headless for API-keys, 1-click for OAuth; ⚠️ n8n REST activation doesn't register webhooks ([#21614](https://github.com/n8n-io/n8n/issues/21614)) which blocks headless per-node provisioning; Activepieces (MIT, MCP-native) likely beats n8n for the "BYO self-hosted" slot. See the doc's Appendices for build-time artifacts + open questions.
