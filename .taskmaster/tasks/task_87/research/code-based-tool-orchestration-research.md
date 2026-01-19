# Code-based tool orchestration: implementation patterns for AI agents

**Programmatic Tool Calling** represents a fundamental shift in how AI agents use tools: instead of the model making individual tool calls that return to its context, **the model writes code that orchestrates multiple tools inside a sandbox**, with only final results surfacing back. This approach delivers **37% token reduction**, **60% faster execution**, and up to **88% fewer API round trips** for complex workflows.

Three production implementations dominate: **Anthropic's Programmatic Tool Calling** (managed Python sandbox), **Cloudflare's Code Mode** (V8 isolates), and **E2B** (Firecracker microVMs). Each uses a different sandboxing technology with distinct security/performance trade-offs, but all share core architectural patterns around tool binding, execution loops, and context control.

---

## Sandbox implementation options and trade-offs

The sandbox technology choice determines cold start times, security isolation levels, and supported languages. Four primary options exist, each suited to different use cases.

### V8 isolates deliver millisecond startup for JavaScript workloads

V8 isolates are independent instances of the V8 JavaScript engine with completely separate heaps and garbage collectors. Cloudflare Workers runs thousands of isolates per process, achieving **~0.3-0.4ms** startup with isolate reuse and **~1-2ms** for fresh isolates.

**Security architecture:** Each isolate has complete memory isolation. Cloudflare adds multiple defense layers:
- **Date.now() locked** during execution to frustrate timing attacks
- **No multi-threading** to prevent Spectre side-channels
- **globalOutbound: null** blocks all network access
- **Linux namespaces + seccomp** on the process sandbox
- **32 GiB guard regions** with memory protection keys around each isolate

**Setting up a V8 isolate with external function injection:**

```cpp
// Create global object template with C++ callback
v8::Local<v8::ObjectTemplate> global = v8::ObjectTemplate::New(isolate);
global->Set(v8::String::NewFromUtf8(isolate, "callTool"),
            v8::FunctionTemplate::New(isolate, ToolCallback));

v8::Persistent<v8::Context> context =
    v8::Context::New(isolate, nullptr, global);

// The callback handles tool invocation
void ToolCallback(const v8::FunctionCallbackInfo<v8::Value>& args) {
    v8::HandleScope scope(args.GetIsolate());
    // Parse tool name and arguments, invoke external system, return result
}
```

**Limitation:** V8 isolates only support JavaScript/TypeScript/WebAssembly—no Python, no shell commands, no arbitrary binaries.

### Firecracker microVMs provide VM-grade isolation with ~125ms startup

Firecracker (open-sourced by AWS, powering Lambda) creates lightweight virtual machines using Linux KVM. Each microVM has **its own kernel**, providing hardware-level isolation with **<5 MiB memory overhead**.

| Metric | Performance |
|--------|-------------|
| Cold boot | ~125ms |
| Snapshot restore | <100ms |
| Creation rate | 150 microVMs/second/host |
| Memory overhead | <5 MiB per VM |

**Host-microVM communication** uses virtio-vsock (virtual sockets), REST API via Unix socket, or MMDS (Metadata Service). E2B builds on Firecracker, achieving **~150-200ms** sandbox startup through pre-configured VM snapshots:

```bash
# Firecracker setup via REST API
curl -X PUT --unix-socket "${API_SOCKET}" \
    --data '{"kernel_image_path": "./vmlinux", "boot_args": "console=ttyS0"}' \
    "http://localhost/boot-source"

curl -X PUT --unix-socket "${API_SOCKET}" \
    --data '{"drive_id": "rootfs", "path_on_host": "./rootfs.ext4", "is_root_device": true}' \
    "http://localhost/drives/rootfs"

curl -X PUT --unix-socket "${API_SOCKET}" \
    --data '{"action_type": "InstanceStart"}' \
    "http://localhost/actions"
```

### gVisor intercepts syscalls in user-space for container-compatible sandboxing

gVisor implements a user-space application kernel (the "Sentry") that intercepts all system calls and implements the Linux API in memory-safe Go. Only **~68 syscalls** reach the host kernel, compared to ~350 for standard containers.

Google's Agent Sandbox uses gVisor on GKE with **pre-warmed sandbox pools** for sub-second latency:

```yaml
apiVersion: extensions.agents.x-k8s.io/v1alpha1
kind: SandboxWarmPool
metadata:
  name: python-sandbox-warmpool
spec:
  replicas: 2  # Pre-warmed sandboxes ready for instant claiming
  sandboxTemplateRef:
    name: python-runtime-template
```

**Cold start:** 50-100ms without pools; **<1 second** with warm pools (90% improvement). Trade-off: syscall overhead makes I/O **2-9× slower** than native.

### Cold start comparison across technologies

| Technology | Cold Start | With Pre-warming | Isolation Level |
|------------|------------|------------------|-----------------|
| V8 Isolates | ~1-2ms | ~0.3ms (reused) | Process-level within V8 |
| Firecracker | ~125ms | <100ms (snapshot) | Hardware VM (own kernel) |
| gVisor | 50-100ms | <1s (warm pool) | User-space kernel |
| Docker (native) | 300-500ms | <100ms (pools) | Linux namespaces only |

---

## The tool-to-function bridge: making MCP tools callable from sandboxes

The core challenge is making external tools callable from generated code **without exposing credentials**. Three patterns have emerged, all using some form of capability-based security.

### Anthropic's allowed_callers pattern for programmatic tool access

Anthropic requires tools to explicitly opt-in to programmatic calling via the `allowed_callers` field:

```python
tools = [
    {
        "type": "code_execution_20250825",
        "name": "code_execution"
    },
    {
        "name": "query_database",
        "description": "Execute SQL query against database",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL query"}
            },
            "required": ["sql"]
        },
        "allowed_callers": ["code_execution_20250825"]  # Key field
    }
]

response = client.beta.messages.create(
    model="claude-sonnet-4-5",
    betas=["advanced-tool-use-2025-11-20"],
    max_tokens=4096,
    messages=[{"role": "user", "content": "Query top customers..."}],
    tools=tools
)
```

Tools with `allowed_callers: ["code_execution_20250825"]` can only be called from code execution, never directly. This prevents the model from bypassing the code orchestration layer.

### Cloudflare's bindings pattern hides credentials completely

Cloudflare's Dynamic Worker Loader creates sandboxes with **pre-authorized bindings**—the sandbox receives an interface to call tools but never sees API keys:

```typescript
let worker = env.LOADER.get("user-123", () => ({
    compatibilityDate: "2025-06-01",
    mainModule: "index.js",
    modules: {
        "index.js": `
            export default {
                async fetch(req, env) {
                    // GREETER is a binding - credentials hidden
                    const result = await env.TOOLS.callTool("get_weather", { location: "Austin" });
                    return new Response(JSON.stringify(result));
                }
            }
        `
    },
    env: {
        // Binding provides authorized interface without exposing secrets
        TOOLS: ctx.exports.ToolProxy({ props: { apiKey: env.WEATHER_API_KEY } })
    },
    globalOutbound: null  // Block ALL network access
}));
```

The `globalOutbound: null` ensures generated code **cannot make arbitrary network requests**—only explicitly provided bindings are accessible.

### E2B's MCP gateway pattern for multi-tool orchestration

E2B provides a localhost MCP gateway inside sandboxes that routes to external MCP servers:

```typescript
const sandbox = await Sandbox.create({
    mcp: {
        github: { githubPersonalAccessToken: process.env.GITHUB_TOKEN },
        notion: { internalIntegrationToken: process.env.NOTION_TOKEN }
    }
});

const mcpUrl = sandbox.getMcpUrl();
const mcpToken = await sandbox.getMcpToken();

// Inside sandbox, agent calls tools via localhost gateway
await sandbox.commands.run(
    `claude mcp add --transport http e2b-mcp-gateway ${mcpUrl} --header "Authorization: Bearer ${mcpToken}"`,
    { timeoutMs: 0 }
);
```

Credentials stay in E2B's infrastructure; the sandbox only receives a bearer token for the gateway.

### HTTP proxy pattern for simpler implementations

The `jx-codes/codemode-mcp` implementation uses a straightforward HTTP proxy—generated code calls `fetch()` to localhost endpoints:

```typescript
// Generated code inside sandbox
const result = await fetch("http://localhost:3001/mcp/call", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
        server: "github",
        tool: "create_issue",
        args: { repo: "myrepo", title: "Bug report" }
    })
}).then(r => r.json());
```

The proxy handles authentication externally. Simple but requires careful network isolation configuration.

---

## Generating typed APIs from tool schemas

Converting JSON Schema tool definitions into typed functions enables code completion, documentation, and runtime validation inside sandboxes. Two approaches exist: build-time code generation and runtime type inference.

### TypeScript generation with json-schema-to-typescript

This library converts JSON Schema to TypeScript interfaces with JSDoc comments from `description` fields:

```typescript
import { compile } from 'json-schema-to-typescript';

const toolSchema = {
    title: "SearchTool",
    type: "object",
    properties: {
        query: { type: "string", description: "Search query string" },
        limit: { type: "integer", minimum: 1, maximum: 100 }
    },
    required: ["query"]
};

const tsInterface = await compile(toolSchema, 'SearchToolParams', {
    bannerComment: "",
    additionalProperties: false
});
```

**Generated output:**

```typescript
export interface SearchToolParams {
    /** Search query string */
    query: string;
    limit?: number;
}
```

### Complete MCP tool codegen pipeline

This pattern generates both interfaces and typed wrapper functions from MCP tool definitions:

```typescript
async function generateToolBindings(tools: MCPTool[]): Promise<string> {
    let output = `declare function callTool(name: string, params: unknown): Promise<ToolResult>;\n\n`;

    for (const tool of tools) {
        const typeName = `${pascalCase(tool.name)}Params`;

        // Generate interface from inputSchema
        output += await compile(tool.inputSchema, typeName, { bannerComment: "" });

        // Generate typed async function
        output += `
/**
 * ${tool.description}
 */
export async function ${camelCase(tool.name)}(
    params: ${typeName}
): Promise<ToolResult> {
    return await callTool("${tool.name}", params);
}
`;
    }
    return output;
}
```

Cloudflare's Code Mode automatically generates this pattern when connecting to MCP servers:

```typescript
declare const codemode: {
    /** Fetch documentation from GitHub repository */
    fetch_agents_documentation: (input: FetchDocsInput) => Promise<FetchDocsOutput>;
    /** Search for code in repository */
    search_agents_code: (input: SearchCodeInput) => Promise<SearchCodeOutput>;
};
```

### Python type generation with datamodel-code-generator

For Python sandboxes, `datamodel-code-generator` creates Pydantic models:

```bash
datamodel-codegen \
    --input tool-schema.json \
    --input-file-type jsonschema \
    --output-model-type pydantic_v2.BaseModel \
    --output models.py
```

**Generated output:**

```python
from pydantic import BaseModel, Field
from typing import Optional, List

class SearchToolParams(BaseModel):
    query: str = Field(..., description="Search query string")
    limit: Optional[int] = Field(None, ge=1, le=100)
    filters: Optional[List[str]] = None
```

### Runtime validation with Ajv and Pydantic

Validating tool arguments before execution prevents runtime errors in generated code:

```typescript
import Ajv from "ajv";

const ajv = new Ajv({ allErrors: true });
const validate = ajv.compile(toolSchema);

function validateToolArgs(args: unknown): args is SearchToolParams {
    if (validate(args)) return true;
    const errors = validate.errors?.map(e => `${e.instancePath}: ${e.message}`).join("; ");
    throw new Error(`Validation failed: ${errors}`);
}
```

---

## The execution loop: protocol between orchestrator and sandbox

Each implementation uses a different protocol for the orchestrator-sandbox interaction, but all handle the same core flow: model generates code → code executes and calls tools → results return to model.

### Anthropic's server_tool_use protocol

Anthropic's response contains both the generated code (`server_tool_use`) and paused tool calls (`tool_use` with `caller` field):

```json
{
    "content": [
        {"type": "text", "text": "I'll query the database..."},
        {
            "type": "server_tool_use",
            "id": "srvtoolu_abc123",
            "name": "code_execution",
            "input": {"code": "results = await query_database('SELECT * FROM customers')..."}
        },
        {
            "type": "tool_use",
            "id": "toolu_def456",
            "name": "query_database",
            "input": {"sql": "SELECT * FROM customers"},
            "caller": {"type": "code_execution_20250825", "tool_id": "srvtoolu_abc123"}
        }
    ],
    "container": {"id": "container_xyz789", "expires_at": "2025-01-15T14:30:00Z"},
    "stop_reason": "tool_use"
}
```

**Execution flow:**

1. Model generates code in `server_tool_use` block
2. Code execution pauses at each `await toolName()` call
3. API returns `tool_use` block with `caller` indicating it's from code
4. You execute the tool and return result
5. Code resumes; if more tool calls, repeat steps 3-4
6. Code completes; `code_execution_result` contains only `stdout`

**Providing tool results:**

```python
response = client.beta.messages.create(
    model="claude-sonnet-4-5",
    betas=["advanced-tool-use-2025-11-20"],
    container="container_xyz789",  # Reuse container
    messages=[
        {"role": "user", "content": "Query top customers..."},
        {"role": "assistant", "content": [/* previous content */]},
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_def456",
                "content": '[{"customer_id": "C1", "revenue": 45000}]'
            }]
        }
    ],
    tools=[...]
)
```

**Critical constraint:** When responding to programmatic tool calls, messages must contain **only** `tool_result` blocks—no additional text.

### Cloudflare's RPC callback pattern

Cloudflare uses V8 isolate bindings with RPC callbacks to the parent worker:

```typescript
const { prompt, tools } = await codemode({
    prompt: "You are a helpful assistant...",
    tools: myTools,
    loader: env.LOADER,
    globalOutbound: null,
    proxy: this.ctx.exports.CodeModeProxy({
        props: { binding: "CodeMode", name: this.name, callback: "callTool" }
    })
});

// Inside sandbox, codemode.toolName() calls trigger RPC back to parent
// Parent executes actual tool, returns result through RPC
```

### E2B's command execution with streaming

E2B executes code as commands with real-time output streaming:

```python
async def execute_with_streaming():
    sandbox = await AsyncSandbox.create()

    await sandbox.commands.run(
        "python agent_code.py",
        on_stdout=lambda line: print(f"📤 {line}"),
        on_stderr=lambda line: print(f"⚠️ {line}"),
        timeout_ms=60000
    )
```

### Error handling patterns

**Syntax errors:** All implementations return these through stderr or error response. Anthropic's code execution result includes:

```json
{
    "type": "code_execution_result",
    "stdout": "",
    "stderr": "SyntaxError: unexpected token at line 3",
    "return_code": 1
}
```

**Tool call failures:** Return error message as tool result; code can handle via try/catch:

```python
# Generated code pattern for error handling
try:
    result = await query_database("SELECT * FROM users")
except Exception as e:
    print(f"Database query failed: {e}")
    result = fallback_data
```

**Timeouts:** Anthropic containers expire after ~4.5 minutes of inactivity. E2B supports up to 24-hour sandbox lifetime for Pro users.

---

## Controlling what the model sees

The key benefit of code-based orchestration is **intermediate results stay in the sandbox**, reducing token usage. But this requires explicit mechanisms to surface important data.

### Anthropic: stdout is the only channel back

Tool results from programmatic calls **never enter Claude's context**—only the final `stdout` from code execution does:

```python
# This 50KB of data stays in sandbox
logs = await fetch_logs(server_id)

# Only this ~1KB enters context
errors = [log for log in logs if "ERROR" in log]
for error in errors[-10:]:  # Only last 10
    print(error)
```

**Token efficiency:** Processing 2,000+ expense items with standard calling loads all data into context. With PTC, only the summary enters context—**10× token reduction** for aggregation workflows.

### Cloudflare: console.log() surfaces results

Code inside V8 isolates uses `console.log()` to surface data:

```typescript
// Intermediate processing stays in isolate
const docs = await codemode.fetch_documentation({});
const filtered = docs.filter(d => d.relevance > 0.8);

// Only this reaches the agent
console.log(JSON.stringify({
    topDocs: filtered.slice(0, 5),
    totalFound: filtered.length
}));
```

### Debugging when the model isn't getting information

**Common issues:**

1. **Silent failures:** Tool calls failing but code not printing error
   - Fix: Always wrap tool calls in try/catch with error logging

2. **Data not surfacing:** Forgetting to `print()` or `console.log()` results
   - Fix: Explicit instructions in system prompt about surfacing data

3. **Wrong format:** Model expects structured data but gets string
   - Fix: Document tool output formats in descriptions

**Debugging approach:**

```python
# Add verbose logging during development
result = await query_database(sql)
print(f"DEBUG: Query returned {len(result)} rows")
print(f"DEBUG: Sample: {result[0] if result else 'empty'}")

# Process data
summary = aggregate(result)
print(f"RESULT: {json.dumps(summary)}")  # This is what model sees
```

---

## Implementation-specific details and source code

### Anthropic Programmatic Tool Calling

**Source URLs:**
- Engineering blog: https://www.anthropic.com/engineering/advanced-tool-use
- Cookbook: https://github.com/anthropics/claude-cookbooks/blob/main/tool_use/programmatic_tool_calling_ptc.ipynb

**Sandbox:** Anthropic-managed Python container with ~4.5 minute expiration. Alternatively, self-managed with their open-source `@anthropic-ai/sandbox-runtime`:

```typescript
import { SandboxManager } from '@anthropic-ai/sandbox-runtime';

await SandboxManager.initialize();
const sandboxedCommand = await SandboxManager.wrapWithSandbox('python script.py');
spawn(sandboxedCommand, { shell: true });
await SandboxManager.reset();
```

**Performance:** 37% token reduction, 25.6% → 28.5% accuracy on knowledge retrieval benchmarks.

**Limitations:**
- No support for web search, web fetch, or MCP connector tools yet
- Cannot force programmatic calling via `tool_choice`
- Not available on Google Cloud Vertex AI

### Cloudflare Code Mode

**Source URLs:**
- Blog: https://blog.cloudflare.com/code-mode/
- Docs: https://developers.cloudflare.com/agents/
- SDK: https://github.com/cloudflare/agents (see `/docs/codemode.md`)

**Implementation:**

```typescript
import { experimental_codemode as codemode } from "@cloudflare/codemode/ai";
import { tool } from "ai";
import { z } from "zod";

const tools = {
    getWeather: tool({
        description: "Get weather for a location",
        parameters: z.object({ location: z.string() }),
        execute: async ({ location }) => {
            // This runs in PARENT worker, not sandbox
            const response = await fetch(`https://api.weather.com/${location}`, {
                headers: { 'Authorization': `Bearer ${env.WEATHER_API_KEY}` }
            });
            return response.json();
        }
    })
};

const { prompt, tools: wrappedTools } = await codemode({
    prompt: "You are a helpful assistant. Use TypeScript to call tools.",
    tools,
    loader: env.LOADER,
    globalOutbound: null,
    proxy: this.ctx.exports.CodeModeProxy({ props: {...} })
});

const stream = streamText({
    model: openai("gpt-5"),
    system: prompt,  // Modified with TypeScript API docs
    tools: wrappedTools,  // Single "execute code" tool
    messages
});
```

**Status:** SDK available, Dynamic Worker Loader in closed beta (signup: https://forms.gle/MoeDxE9wNiqdf8ri9)

### E2B sandbox

**Source URLs:**
- GitHub: https://github.com/e2b-dev/e2b
- MCP Server: https://github.com/e2b-dev/mcp-server

**Basic usage:**

```python
from e2b_code_interpreter import Sandbox

with Sandbox() as sandbox:
    # Stateful execution - variables persist
    sandbox.run_code("x = 1")
    execution = sandbox.run_code("x += 1; x")
    print(execution.text)  # "2"

    # Filesystem access
    sandbox.files.write("/home/user/data.json", json.dumps(data))

    # Shell commands
    result = sandbox.commands.run("pip install pandas")
```

**MCP integration:**

```typescript
const sandbox = await Sandbox.create({
    mcp: {
        github: { githubPersonalAccessToken: process.env.GITHUB_TOKEN },
        exa: { apiKey: process.env.EXA_API_KEY }
    }
});

// Get MCP gateway credentials
const mcpUrl = sandbox.getMcpUrl();
const mcpToken = await sandbox.getMcpToken();

// Agent inside sandbox accesses tools via gateway
```

**Custom templates:**

```dockerfile
# e2b.Dockerfile
FROM e2bdev/code-interpreter:latest
RUN pip install pandas numpy scikit-learn
COPY ./my_tools.py /home/user/
```

```bash
e2b template build --name my-agent-sandbox
```

### Open source implementations

**LangGraph CodeAct** (https://github.com/langchain-ai/langgraph-codeact):

```python
from langgraph_codeact import create_codeact
from langgraph.checkpoint.memory import MemorySaver

tools = [add, multiply, divide, sin, cos, sqrt]  # Python functions
code_act = create_codeact(model, tools, eval)  # Use langchain-sandbox for production
agent = code_act.compile(checkpointer=MemorySaver())
```

**jx-codes/codemode-mcp** (https://github.com/jx-codes/codemode-mcp):
- Deno sandbox with network-only access
- HTTP proxy pattern for MCP tool calls
- 30-second execution timeout

**UTCP Code-Mode** (https://github.com/universal-tool-calling-protocol/code-mode):
- Node.js VM sandboxing
- Auto-generates TypeScript interfaces from MCP schemas
- Benchmarks show **67-88% fewer iterations** vs traditional tool calling

---

## Security model summary

| Layer | Anthropic | Cloudflare | E2B |
|-------|-----------|------------|-----|
| Sandbox tech | Managed Python container | V8 isolates | Firecracker microVM |
| Network isolation | Sandboxed (no egress) | `globalOutbound: null` | Configurable |
| Credential exposure | Never in sandbox | Capability bindings | Gateway tokens only |
| Cold start | Container reuse | ~milliseconds | ~150-200ms |
| Max lifetime | ~4.5 min idle | Per-request | 24 hours (Pro) |

**Key security guarantees across all implementations:**
1. Generated code cannot access API keys (capability-based security)
2. Network access blocked or tightly controlled
3. Resource limits (CPU, memory, time) enforced
4. Each execution isolated from others

---

## Conclusion

Code-based tool orchestration is production-ready with three distinct implementation paths. **Anthropic's Programmatic Tool Calling** offers the simplest integration for Claude users with managed infrastructure. **Cloudflare's Code Mode** provides millisecond-startup V8 isolates ideal for edge deployment and TypeScript-native workflows. **E2B** offers the most flexibility with Firecracker microVMs supporting any language and full filesystem access.

For new implementations, the pattern is consistent: expose a single "execute code" tool, generate typed interfaces from tool schemas, inject authorized bindings (never raw credentials) into the sandbox, and use `stdout`/`console.log()` as the explicit channel for surfacing results. The **75-88% reduction in API round trips** for complex workflows makes this architecture essential for any agent handling multi-step tool orchestration.