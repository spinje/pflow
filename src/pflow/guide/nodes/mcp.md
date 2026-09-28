# MCP Node

**Use for**: Service-specific APIs (Slack, GitHub, Postgres, etc.) with automatic authentication.

Node naming: `mcp-{server}-{TOOL}` (e.g., `mcp-slack-SEND_MESSAGE`, `mcp-postgres-QUERY`).

**Caching**: MCP nodes don't cache by default — calls hit the live service each run, so reads see current state and writes always perform their side effect. Add `cache: true` only for an expensive, side-effect-free call whose result is stable for the run.

### Supported Service Categories

MCP servers span these categories (each has unique output structure):
**Data** · **Communication** · **Storage** · **DevOps** · **Productivity** · **APIs**

Examples: Databases (PostgreSQL, MySQL), Chat (Slack, Discord), Cloud (S3, GCS), Version Control (GitHub, GitLab), Docs (Notion, Sheets), REST/GraphQL

See `pflow mcp describe <tool> --help` for how to interpret tool details.

## ⚠️ MCP Output Has NO Standard Structure

MCP nodes expose one canonical output namespace: `result`.

Use `${node.result}` for the full tool payload and `${node.result.field}` for
nested fields. Do not use `${node.field}` for MCP tool fields. Validation keeps
`result` open-ended because server schemas may be missing or incomplete; probe
inspects the actual response to show the concrete paths.

**Every MCP server is completely different. Even the SAME operation:**

```python
# Three different "send message" MCPs:
Server A:  result.data.message.ts
Server B:  result.ok and result.ts           # Flat structure
Server C:  result.response.data[0].id       # Deep nesting

# Three different "query database" MCPs:
Server A:  result.rows[]                    # PostgreSQL style
Server B:  result.data.results[]            # Wrapped
Server C:  result.Items[]                   # DynamoDB style
```

**There are NO patterns. Test every MCP tool:**
`pflow probe mcp-service-TOOL param=value`

### pflow Parameters on Every MCP Node

Besides the tool's own parameters, every MCP node accepts two pflow parameters
that are never sent to the server:

| Parameter | Effect |
|---|---|
| `timeout` | Seconds before the tool call is abandoned (default: 30) |
| `result_format: json_block` | Parse the single fenced ` ```json ` block in a text result and use it as `result` |

Some tools answer for an LLM, wrapping their data in prose:

````text
Script ran on page and returned:
```json
{"count": 42}
```
````

By default that arrives as a plain string, so `${node.result.count}` cannot
resolve. With `- result_format: json_block` the parsed block becomes `result`,
and `${node.result.count}` works. The result must be text-only and hold exactly
one ` ```json ` block: other content (images, resources), zero or several
blocks, or invalid JSON inside it fail the node (routable with `on-error`)
rather than guess. `structuredContent`, when the
server sends it, still takes precedence, and a tool error (`isError`) is still
an error.

### MCP Tools Can Report Failure Inside `result`

Some MCP tools return a successful MCP response while the service payload says
the operation failed. Example: a tool can return:

```json
{
  "status": "error",
  "reason": "expired",
  "error": "Cannot create audio: NotebookLM auth is not valid",
  "hint": "nlm login"
}
```

That payload is available as `${create-audio.result.status}`,
`${create-audio.result.error}`, and so on in traces/reports. pflow promotes
common explicit failure flags (`status: "error"`, `ok: false`, `success:
false`, etc.) to API-warning failures, so use `on-error:` when a workflow
should recover from those. For tool-specific failure shapes pflow does not
classify, guard follow-up polling/download/mutation steps by checking the
tool's own success field before continuing.

MCP failure paths:

| Outcome | What it is | pflow behavior |
|---|---|---|
| Protocol/transport failure | MCP client/server call failed before a tool result | Writes `${node.error}` and `${node.error_details}` |
| `isError: true` | Tool set the MCP tool-error flag | Returns `error`, so `on-error` can route it |
| `result.status: "error"`, `result.ok: false`, etc. | Service failure inside a successful MCP payload | Stored under `${node.result}`; pflow surfaces explicit failure flags as API warnings |

### Choosing Tools for Deterministic Steps

Many MCP servers are built for an LLM taking turns. One server often offers two
styles of tool, and they behave very differently as fixed workflow steps:

- **Observe-then-act tools** return handles (element uids, cursor or session ids)
  that the next call uses after reading this result: `take_snapshot` → `click(uid)`.
  They fit a step count known up front, with handles threaded through templates.
  When the list of steps is runtime data, each step has to read the previous
  result to find its handle, which usually means an `agent` node in the loop.
- **Whole-program tools** take a complete script, query or form and return its
  result in one call (`evaluate_script`, a SQL `query`, `fill_form`). Prefer them
  when the steps are data, or when you would otherwise chain observe-then-act calls.

Then check three things before building on a tool:

- **Where the program runs.** Code that runs *inside* the target (a script
  evaluated in a web page) can only do what the target lets its own code do: in a
  page, no trusted input events and no request interception. A tool that drives the
  target *from the host* (a browser-automation API) can do both. If you need that,
  pick the host-side tool first; rebuilding it inside the target is a long detour.
- **What comes back.** Prefer tools, or programs you write, that return JSON over
  prose or markdown meant for an LLM (log listings, console dumps). For one fenced
  JSON block inside prose, use `result_format: json_block`. If you must parse
  prose, pin the server version and treat output changes as breaking.
- **What it can do, not just what it returns.** `pflow probe` shows the output
  shape. Also test the one capability the workflow depends on (does the input
  reach the field? is the request visible?). Each probe starts from a fresh server
  unless you keep one alive (see Server lifetime below).

**Slow calls.** A call is abandoned after `timeout` seconds. The server stays up
for the rest of the run, so an `on-error:` handler can call the same server and
read what the slow program left behind (e.g. results it pushed to a global as it
went). If the server runs one call at a time, the handler waits until the
abandoned call actually finishes, so give a long program its own deadline and
have it return early with what it has.

**Server lifetime.** Each run or probe connects to its MCP servers and
disconnects at the end; a stdio server is started and stopped with it. That suits
a reusable workflow, which should start clean, but it means state held in the
server process (an open browser page, a notebook kernel, a shell session) is gone
before your next probe. State the server writes to disk (a browser profile, a
database) survives either way, so check the server's options when a run must
start clean.

To explore step by step (look, act, look again across separate probes), keep one
server process alive outside pflow: run the stdio server behind a proxy that holds
a single child for its whole life, and register the proxy over HTTP.

```bash
# keep this running in its own process (another terminal, or backgrounded):
uvx --with 'mcp<2' mcp-proxy --port 8932 -- <server command>   # mcp<2: mcp-proxy 0.12 breaks on mcp 2.x
pflow mcp add '{"explore": {"type": "http", "url": "http://127.0.0.1:8932/mcp"}}'
# probe or run mcp-explore-* nodes; when done:
pflow mcp remove -f explore    # then stop the proxy process
```

A server's own HTTP mode is not the same: it may still discard state when the
last client disconnects, which every run end does. Playwright MCP's `--port`
restarts at `about:blank`; behind the proxy, its open page, localStorage and
session cookie carried across separate probes and runs. Everything using the
long-lived registration shares that one server and its state, so confirm the
finished workflow against the normal run-scoped registration.

### Node Creation Pattern

`````markdown
### update-service

Update external service with results.

- type: mcp-service-UPDATE
- resource_id: ${resource_id}

```yaml data
status: completed
results: ${structured-analysis.response}
timestamp: ${get-timestamp.stdout}
metadata:
  source: ${api_url}
  processed_count: ${limit}
```
`````

### Pattern: Service Orchestration with Formatting

**Use case**: Multiple services with human-readable output

`````markdown
## Steps

### fetch-service1

Query primary data source.

- type: mcp-service1-GET_DATA
- resource: ${resource_id}

### fetch-service2

List items from secondary source.

- type: mcp-service2-LIST_ITEMS
- filter: ${filter_criteria}

### analyze-and-format

Find relationships between datasets and format as report. One LLM call for both analysis and formatting.

- type: llm

````prompt
Analyze these two datasets and identify cross-references:

Service1: ${fetch-service1.result}

Service2: ${fetch-service2.result}

Find relationships, correlations, and connections. Format as a professional report with markdown headers and sections.
````

### send-report

Email the analysis report to the recipient.

- type: mcp-email-SEND
- to: ${recipient_email}
- subject: Data Analysis Report
- body: ${analyze-and-format.response}
`````

**Note**: `analyze-and-format` combines analysis and formatting in one LLM call - don't use separate LLM nodes when one can do both. If you just need to concatenate data with a fixed structure, use code node or templates instead.

### MCP/HTTP Reality vs Documentation

| What Docs Say | What You Get | How to Handle |
|---------------|--------------|---------------|
| `result: Any` | `result.data.tool_response.nested.deeply.value` | Always test structure with pflow probe |
| "Optional parameter" | Actually required or fails | Always provide it |
| "Returns array" | `{"items": [...], "metadata": {...}}` | Access via `.items` |
| "String parameter" | Needs specific format | Test with examples |
| "Async endpoint" | Might support Prefer:wait | Try header first |
| "Returns immediately" | Actually takes 5-10 seconds | Raise `timeout` (see Slow calls) |

### When to Probe MCP Nodes

**Probe when** you need specific nested fields like `${node.result.data.items[0].id}`.
**Skip probing when** you're passing `${node.result}` wholesale to the next step — you don't need to know the structure.

See `pflow probe --help` for output format and usage.

**MCP Testing Protocol:**
```bash
# 1. Inform user
echo "I need to test access to [service]. This will [describe effect]."

# 2. Ask permission if side effects
# If has_side_effects: "This test will [visible effect]. Should I proceed?"

# 3. Probe with actual data
pflow probe mcp-{mcp-service-name}-{mcp-tool-name} \
  param1="your_actual_format_here"

# 4. Copy template paths from output into your workflow
```

### MCP Meta-Discovery Process

**Before testing individual MCP tools, always check for helpers:**

```bash
# 1. Find all tools from a service
pflow mcp list "slack"

# Returns something like:
# mcp-slack-SEND_MESSAGE
# mcp-slack-FETCH_HISTORY
# mcp-slack-LIST_CHANNELS
# mcp-slack-GET_CHANNEL_INFO  ← Meta tool!

# 2. Use meta tools to understand
pflow probe mcp-slack-GET_CHANNEL_INFO \
  channel="general"

# 3. Now you know the actual structure for that service
```

### MCP Structure Discovery Process

**Often the documentation says "Output: result (Any)" - here's how to find the ACTUAL structure:**

```bash
# Probe with minimal real data
pflow probe mcp-example-service-get-data query="test_value"

# Copy the exact template paths from the output and use them in your workflow:
# If probe shows: ${result.data.items}
# Then use: ${node.result.data.items} in your workflow templates
```

**Never assume. Always discover.**

**MCP "JSON string" parameters**: When registry output shows a parameter as "JSON string" (like `body_schema`, `query_params`), still use object syntax. pflow auto-serializes with proper escaping. Manual `'{"key": "${val}"}'` breaks on newlines/quotes in template values.
