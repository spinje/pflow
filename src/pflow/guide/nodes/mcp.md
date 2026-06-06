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
nested fields. Do not use `${node.field}` for MCP tool fields; validation only
knows the declared `result` output because MCP servers do not publish stable
output schemas.

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
`${create-audio.result.error}`, and so on. Guard workflows that poll, download,
or mutate follow-up state by checking the tool's own success field before
continuing.

MCP failure paths:

| Outcome | What it is | pflow behavior |
|---|---|---|
| Protocol/transport failure | MCP client/server call failed before a tool result | Writes `${node.error}` and `${node.error_details}` |
| `isError: true` | Tool set the MCP tool-error flag | Returns `error`, so `on-error` can route it |
| `result.status: "error"`, `result.ok: false`, etc. | Service failure inside a successful MCP payload | Stored under `${node.result}`; pflow surfaces explicit failure flags as API warnings |

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
| "Returns immediately" | Actually takes 5-10 seconds | Add timeout handling |

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
