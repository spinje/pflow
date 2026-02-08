# Braindump: Task 123 — OAuth for MCP HTTP Servers

## Where I Am

Research phase is complete. A prerequisite bug fix (Issue #88) was implemented and committed. The task spec is written. No OAuth implementation has started.

This session covered two things:
1. **Bug fix** (done): `${VAR}` in MCP server config URLs wasn't expanded, and settings.json env vars were ignored. Fixed by expanding the entire config dict once at entry points. Commit `e567f7e`, closes GitHub issue #88.
2. **Research** (done): How to add OAuth support, how other clients do it, what the SDK provides. Written up in task spec + research notes.

## User's Mental Model

The user thinks architecturally, not tactically. They consistently pushed me to simplify:

- When I proposed expanding env vars field-by-field (URL, headers, auth separately), they asked **"why do you have to specify each field?"** — leading to the much cleaner "expand whole config once" approach.
- When I said the URL "was just overlooked", they pushed back: **"what do you mean URL was just overlooked?"** — they don't accept speculation about intent without evidence.
- They wanted tests that **"test important behavior... quality over quantity. think deeply what actually matters"** — not coverage-driven testing.
- They asked me to write the GitHub issue **"as if written BEFORE this implementation"** — they care about process artifacts being genuine, not retroactive documentation.
- On OAuth, they said **"this is for research so we can create the task to do later"** — they're planning ahead, not rushing to implement. They want to understand the space before committing.
- They asked **"is there any ambiguity left? have you made any assumptions you need to verify?"** — they want epistemic rigor, not confident-sounding summaries.

Their priority hierarchy: understand the problem deeply → make clean design decisions → implement simply. They get annoyed by hand-waving and speculation.

## Key Insights

### The critical SDK finding

**The old `streamablehttp_client` API already has `auth: httpx.Auth | None = None`.** I verified this via `inspect.signature()` against the installed SDK v1.26.0. The pflow-codebase-searcher subagent got this WRONG — it reported the parameter doesn't exist because it only looked at pflow's call sites (which don't use it). If the next agent trusts the research notes from the subagent without checking, they might think an API migration is required. It isn't.

```python
# Verified signature (old API):
streamablehttp_client(url, headers=, timeout=, sse_read_timeout=, terminate_on_close=, httpx_client_factory=, auth: httpx.Auth | None = None)

# New API also exists:
streamable_http_client(url, *, http_client: httpx.AsyncClient | None = None)
```

Both APIs exist in the SDK. pflow uses the old one. The old one is sufficient — just add `auth=oauth_provider`. No migration needed.

### `OAuthClientProvider` is `httpx.Auth`

It inherits from `httpx.Auth`, which is why it can be passed as `auth=`. This is the cleanest integration path — the provider handles token acquisition, refresh, and injection into requests transparently.

### `headers=` and `auth=` coexist

When OAuth is used, custom headers (non-auth) should still go through `headers=`. The `auth=` parameter handles the `Authorization` header via the OAuth provider. httpx merges both. So the pattern becomes:

```python
if auth_type == "oauth":
    oauth = create_oauth_provider(...)
    custom_headers = config.get("headers", {})  # Non-auth headers only
    streamablehttp_client(url=url, headers=custom_headers, auth=oauth, ...)
else:
    headers = build_auth_headers(config)  # Existing path, includes auth + custom headers
    streamablehttp_client(url=url, headers=headers, ...)
```

NEEDS VERIFICATION: Does httpx handle the case where both `auth=` sets an Authorization header AND `headers=` has a non-auth custom header? I believe yes (httpx merges them), but test this.

### Claude Code's evolution is instructive

Claude Code started with DCR-only OAuth. Then in v2.1.30 (late January 2026) they added `--client-id`, `--client-secret`, `--callback-port` because major providers (GitHub, Google, Azure) don't support DCR. We should ship with both paths from day one.

### Port conflict is a real bug class

Claude Code issue #15320, Cline's 48801-48811 range, mcp-remote's fallback to random port — everyone hits this. The callback server port needs: (1) a sensible default, (2) per-server override via config, (3) fallback to random if busy. Don't use a single fixed port.

## Assumptions & Uncertainties

ASSUMPTION: `auth=` and `headers=` on `streamablehttp_client` work correctly together. Based on httpx behavior, but not tested with MCP SDK specifically.

ASSUMPTION: `OAuthClientProvider` handles the full flow including 401 → metadata discovery → DCR → browser → callback → token exchange. I read the SDK source and this appears correct, but haven't run it end-to-end.

ASSUMPTION: The SDK's `redirect_handler` is called with the full auth URL and pflow just needs to open a browser. The `callback_handler` is called to get the auth code from the redirect. Need to verify the exact contract — does pflow need to run the local HTTP server, or does the SDK do it?

UNCLEAR: The SDK's `callback_handler` signature is `Callable[[], Awaitable[tuple[str, str | None]]]` — returns `(code, state)`. This means pflow IS responsible for running the callback server and extracting the code/state from the redirect. The SDK doesn't run the server.

NEEDS VERIFICATION: Task 97 ("OAuth for Remote MCP Servers") — is this the same scope as Task 123? I flagged this in the task spec but didn't check. The next agent should read Task 97 and decide whether to merge, deprecate one, or keep them separate.

ASSUMPTION: Plain text JSON with `chmod 600` is sufficient for token storage. This matches pflow's existing pattern and what other CLI tools do, but the user didn't explicitly confirm this. They might want keychain integration.

## Unexplored Territory

UNEXPLORED: **OAuth during workflow execution UX.** When a workflow runs an MCP node and the token has expired, the SDK auto-refreshes silently. But what if the refresh token is also expired? The SDK would need to trigger a browser flow mid-workflow. How should this be handled? Fail the node? Pause and prompt?

UNEXPLORED: **Token revocation.** Claude Code has "Clear authentication" in the `/mcp` menu. pflow needs equivalent: `pflow mcp auth clear <server>` or similar. Not mentioned in task spec.

UNEXPLORED: **The MCP server execution path** (`src/pflow/mcp_server/services/execution_service.py`). This is pflow-as-MCP-server, not pflow-as-MCP-client. It already uses `include_settings=True` for env var expansion. OAuth probably doesn't apply here (the agent calling pflow handles its own auth), but worth confirming.

CONSIDER: **Client Credentials flow for CI.** The SDK has `ClientCredentialsOAuthProvider` for machine-to-machine auth. This could replace the manual PAT workflow for CI environments that have proper OAuth infrastructure. But it's a separate concern — the PAT path (Issue #88 fix) works fine for now.

CONSIDER: **CIMD (Client ID Metadata Documents).** The November 2025 MCP spec update prefers CIMD over DCR for client registration. The SDK may or may not support this yet. Worth checking when implementing, but DCR is the immediate priority since that's what servers support today.

MIGHT MATTER: **Multiple OAuth servers simultaneously.** If a workflow uses tools from two different OAuth-protected MCP servers, each needs its own token. The per-server storage design (`~/.pflow/auth/{server_hash}.json`) handles this, but the callback server port allocation needs to be thought through — can two servers need auth at the same time?

MIGHT MATTER: **The `timeout` parameter on `OAuthClientProvider` defaults to 300 seconds (5 minutes).** This is how long it waits for the user to complete the browser flow. Claude Code's mcp-remote uses 30 seconds. 5 minutes seems more reasonable for a first-time auth where the user might need to create an account or configure permissions.

## What I'd Tell Myself

1. **Start by verifying `auth=` works with `streamablehttp_client`.** Write a minimal test that creates an `OAuthClientProvider` with a mock server and passes it to `streamablehttp_client`. If this works, the rest is infrastructure. If it doesn't, the whole approach changes.

2. **Don't over-scope the first version.** The user explicitly said "create the task to do later" — they're not rushing. Phase 1 should be: DCR servers with auto-discovery (the happy path). Phase 2: non-DCR with `--client-id`/`--client-secret`. Phase 3: `pflow mcp auth` CLI commands.

3. **The bug fix we shipped (Issue #88) is the foundation.** The whole-config expansion pattern (`expand_env_vars_nested` with `include_settings=True`) is what makes the manual token path work. OAuth builds on top of this — it's an alternative auth method, not a replacement.

4. **Watch out for subagent hallucinations.** The pflow-codebase-searcher incorrectly stated that `streamablehttp_client` has no `auth=` parameter. I caught this because I had already verified it via `inspect.signature`. Always verify SDK API claims against the actual installed code.

## Open Threads

- **Task 97 overlap**: Need to check if Task 97 is the same scope. If so, merge or deprecate one.
- **`callback_handler` contract**: Need to understand exactly what the SDK expects. My reading: pflow runs a local HTTP server, waits for the redirect, extracts `code` and `state` from query params, returns them. But the SDK source should be read carefully.
- **Token storage encryption**: The task spec says plain text + `chmod 600`. The user didn't push back, but also didn't explicitly approve. If they care about keychain integration, that's a bigger scope.

## Relevant Files & References

### Modified in this session (bug fix)
- `src/pflow/mcp/auth_utils.py` — Removed env var expansion from `build_auth_headers`
- `src/pflow/mcp/discovery.py` — Whole-config expansion in `_discover_async`
- `src/pflow/nodes/mcp/node.py` — Whole-config expansion in `prep`
- `tests/test_mcp/test_mcp_config_expansion.py` — New test file for the fix

### Key files for OAuth implementation
- `.venv/lib/python3.13/site-packages/mcp/client/auth/oauth2.py` — SDK's OAuth implementation (~617 lines)
- `.venv/lib/python3.13/site-packages/mcp/shared/auth.py` — OAuth data models (OAuthClientMetadata, OAuthToken, etc.)
- `.venv/lib/python3.13/site-packages/mcp/client/streamable_http.py` — Both old and new API definitions
- `src/pflow/cli/mcp.py` — MCP CLI commands (needs `--client-id` etc.)
- `src/pflow/mcp/manager.py` — Config validation (needs `oauth` auth type)

### Task and research docs
- `.taskmaster/tasks/task_123/task-123.md` — Task spec
- `scratchpads/mcp-oauth/research-notes.md` — Detailed research with sources

## For the Next Agent

**Start by**: Reading the task spec, then verify the `auth=` parameter works with `streamablehttp_client` (write a quick integration test). This is assumption #1 that everything else depends on.

**Don't bother with**: Migrating to the new `streamable_http_client` API. The old API has everything needed.

**The user cares most about**: Clean design, minimal code, understanding why decisions were made. They will push back on unnecessary complexity. They want OAuth to feel like a natural extension of the existing auth system, not a bolted-on feature.

**Read carefully**: The SDK's `OAuthClientProvider` source code (`.venv/lib/python3.13/site-packages/mcp/client/auth/oauth2.py`). Understand what it does vs. what pflow needs to provide. The boundary is: SDK handles OAuth protocol, pflow handles storage + browser + CLI UX.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
