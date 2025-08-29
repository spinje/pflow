Short answer: **Yes in principle, “hot-updating” the tool list is part of MCP.** Whether it actually updates **live during a session** depends on the client.

**How it’s supposed to work (per MCP):**

* Your server advertises `capabilities.tools.listChanged: true` on initialize.
* When tools are added/removed, the server emits `{"jsonrpc":"2.0","method":"notifications/tools/list_changed"}`.
* A well-behaved client then re-runs `tools/list` and refreshes the available tools. ([modelcontextprotocol.io][1])

**What happens in Claude Code today (Aug 2025):**

* Claude Code does speak MCP, but **handling of live “list\_changed” updates is inconsistent**. There are open issues/requests to refresh tools (and prompts/resources) on those notifications, which means you may not see new tools until you reconnect/restart. ([GitHub][2])

**Practical workarounds right now:**

* **Quick reload:** restart the MCP server *or* bounce Claude Code and re-enter with `claude --continue` to keep convo state while forcing a fresh tool discovery. (Community tip noted by users.) ([Reddit][3])
* **Dev ergonomics:** wrap your server with a *hot-reload* helper (several community wrappers exist) so Claude can trigger a lightweight restart when tools change. ([GitHub][4], [LobeHub][5])
* **Design pattern:** expose a **stable “router” tool** whose arguments select sub-operations. You can evolve internals without relying on the client to notice a new top-level tool.

If you want truly live updates mid-run, build your MCP server to emit `notifications/tools/list_changed` and test with a client known to handle it (per spec); with Claude Code, assume you’ll need a reconnect-style refresh until those issues are closed. ([modelcontextprotocol.io][1], [GitHub][2])

[1]: https://modelcontextprotocol.io/specification/2024-11-05/server/tools "Tools - Model Context Protocol"
[2]: https://github.com/anthropics/claude-code/issues/4118?utm_source=chatgpt.com "Capture MCP Tools Changed notifications"
[3]: https://www.reddit.com/r/ClaudeAI/comments/1lsc4kx/how_to_refresh_files_list_to_reference_in_claude/?utm_source=chatgpt.com "How to refresh files list to reference in claude code"
[4]: https://github.com/data-goblin/claude-code-mcp-reload?utm_source=chatgpt.com "data-goblin/claude-code-mcp-reload"
[5]: https://lobehub.com/mcp/claude-code-mcp-reload-mcp-hot-reload?utm_source=chatgpt.com "Claude Code - MCP Hot Reload"
