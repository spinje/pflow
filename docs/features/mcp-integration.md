# MCP Server Integration and Security Model

> **Version**: v2.0
> **MVP Status**: ❌ Deferred to v2.0
> For complete MVP boundaries, see [MVP Scope](./mvp-scope.md)

## 1 · Scope

A comprehensive specification for integrating **Model Context Protocol** servers into pflow as native wrapper nodes that follow the shared store + proxy pattern. This integration ensures MCP tools are indistinguishable from manually-written pflow nodes in terms of interface, behavior, and orchestration capabilities.

**Key Integration Points**:

- Natural shared store interfaces using intuitive key names
- Full participation in JSON IR generation and flow orchestration
- Simple sequential data flow with clear error handling
- Unified registry system with planner-discoverable metadata
- CLI resolution following "Type flags; engine decides" principle
- Optional proxy mapping support for complex routing scenarios

> **For architectural context**, see [Shared Store + Proxy Design Pattern](../core-concepts/shared-store.md) and [Planner Responsibility & Functionality Spec](./planner.md)

---

## 2 · Terminology

| Term | Meaning |
|---|---|
| **MCP Wrapper Node** | Auto-generated pflow Node subclass that exposes MCP tool as simple, single-purpose node |
| **MCP Configuration** | Server connection metadata integrated into pflow's unified registry system |
| **MCP Executor** | Internal component handling MCP protocol communication (hidden from node interface) |
| **Natural Interface Mapping** | Translation layer between MCP tool schemas and pflow's intuitive key conventions |
| **Generated Node Metadata** | pflow-compatible docstring and interface specification extracted from MCP tool manifest |

---

## 3 · pocketflow Framework Integration

MCP wrapper nodes leverage the lightweight **pocketflow framework** (100 lines of Python) without modifications:

- **Node Base Class**: Inherit from `pocketflow.Node` with standard `prep()`/`exec()`/`post()` methods
- **Params System**: Use `set_params()` to configure wrapper nodes with flat parameter structure
- **Flow Orchestration**: Full compatibility with `>>` operator and simple sequential flow
- **No Framework Changes**: Pure pattern implementation using existing pocketflow APIs

```python
# MCP wrapper nodes follow identical patterns to manual nodes
from pocketflow import Node, flow_safe

class McpGithubSearchCodeNode(Node):  # Standard pocketflow inheritance
    # Natural shared store interface, same as any pflow node
    # Simple, single-purpose node design
    # Compatible with proxy mappings and JSON IR
```

> **See also**: pocketflow framework (`pocketflow/__init__.py`) for core implementation details

---

## 4 · Registry Integration

### 4.1 Unified Registry Approach

**Eliminates**: Standalone `mcp.json` registry that conflicts with planner architecture
**Adopts**: Integrated MCP configuration within pflow's single registry system

**Registry Entry Structure**:

```json
{
  "node_id": "mcp-github-search-code",
  "type": "mcp_wrapper",
  "description": "Search code in GitHub repositories via MCP",
  "mcp_config": {
    "server_id": "github-server",
    "tool_name": "search_code",
    "transport": "stdio",
    "command": "mcp-github",
    "version": "1.2.0",
    "manifest_hash": "sha256:abc123..."
  },
  "interface": {
    "inputs": ["query", "language"],
    "outputs": ["search_results"],
    "params": {"max_results": 10},
  },
  "purity": "impure"  # Most MCP tools have side effects
}
```

### 4.2 Planner Integration

**Node Discovery**: MCP wrapper nodes appear alongside manually-written nodes in planner's metadata extraction
**LLM Selection**: Thinking models can select MCP tools naturally during flow generation
**Metadata Format**: Generated nodes follow pflow's docstring conventions for consistent discovery

### 4.3 CLI Commands

```bash
# Registry integration (replaces mcp-specific commands)
pflow registry add-mcp --server github --tool search_code --command "mcp-github" --transport stdio
pflow registry list --filter mcp
pflow registry refresh --mcp-server github  # Re-scan tools

# Standard registry operations work with MCP nodes
pflow registry describe mcp-github-search-code
pflow registry validate --all
```

---

## 5 · Wrapper Node Generation

### 5.1 Complete pflow Node Implementation

Generated wrapper nodes follow the full pflow pattern with natural shared store interfaces:

```python
# Generated wrapper follows simple node pattern
class McpGithubSearchCodeNode(Node):
    """Search code in GitHub repositories via MCP.

    Interface:
    - Reads: shared["query"] - search query string
    - Reads: shared["language"] - programming language filter (optional)
    - Writes: shared["search_results"] - array of code search results
    - Params: max_results (default 10) - maximum results to return

    MCP Source: github-server/search_code v1.2.0
    """

    # MCP metadata (used internally by executor)
    _mcp_server_id = "github-server"
    _mcp_tool_name = "search_code"
    _mcp_tool_version = "1.2.0"
    _mcp_manifest_hash = "sha256:abc123..."

    def __init__(self):
        super().__init__()
        self._mcp_executor = McpExecutor(self._mcp_server_id)

    def prep(self, shared):
        """Extract search parameters from shared store using natural keys."""
        query = shared.get("query")
        if not query:
            raise ValueError("Missing required 'query' in shared store")

        return {
            "query": query,
            "language": shared.get("language"),  # Optional parameter
            "max_results": self.params.get("max_results", 10)
        }

    def exec(self, prep_res):
        """Execute MCP tool call with action-based error handling."""
        try:
            response = self._mcp_executor.call_tool(
                self._mcp_tool_name,
                prep_res,
                expected_version=self._mcp_tool_version
            )
            return response["results"]
        except McpRateLimitError:
            raise  # Let framework handle retries
        except McpAuthError:
            raise  # Auth errors should fail clearly
        except McpResourceNotFoundError:
            raise  # Resource errors should fail clearly

    def post(self, shared, prep_res, exec_res):
        """Write results to shared store."""
        # Natural interface - write results to intuitive key
        shared["search_results"] = exec_res
        return "default"
```

### 5.2 Metadata Extraction

**Docstring Generation**: Convert MCP tool manifests to pflow-compatible documentation:

```python
def generate_node_docstring(mcp_tool):
    """Convert MCP tool manifest to pflow docstring format."""
    return f'''
    """{mcp_tool.description}

    Interface:
    {format_shared_store_inputs(mcp_tool.input_schema)}
    {format_shared_store_outputs(mcp_tool.output_schema)}
    {format_params(mcp_tool.parameters)}
    {format_actions(mcp_tool.error_types)}

    MCP Source: {mcp_tool.server_id}/{mcp_tool.name} v{mcp_tool.version}
    """
    '''

def format_shared_store_inputs(input_schema):
    """Convert MCP input schema to natural shared store key documentation."""
    lines = []
    for param_name, param_def in input_schema.items():
        required = " (optional)" if not param_def.get("required", True) else ""
        lines.append(f"    - Reads: shared[\"{param_name}\"] - {param_def.description}{required}")
    return "\n".join(lines)
```

### 5.3 Simple Node Naming for MCP Tools

**MCP Tool → Simple Node Mapping**:

Each MCP tool becomes a single-purpose simple node following `mcp-platform-action` pattern:

| MCP Tool | Simple Node Name | Purpose |
|----------|------------------|---------|
| `get_weather` | `mcp-weather-get` | Get weather data for location |
| `search_repositories` | `mcp-github-search-repos` | Search GitHub repositories |
| `send_slack_message` | `mcp-slack-send-message` | Send message to Slack channel |
| `list_files` | `mcp-filesystem-list-files` | List files in directory |
| `get_stock_price` | `mcp-finance-get-stock` | Get current stock price |

**Natural Interface Examples**:

```python
# mcp-weather-get
# Inputs: shared["location"], shared["units"]
# Outputs: shared["weather_data"]

# mcp-github-search-repos
# Inputs: shared["query"], shared["language"], shared["sort_by"]
# Outputs: shared["repositories"]

# mcp-slack-send-message
# Inputs: shared["message"], shared["channel"]
# Outputs: shared["message_id"]
```

**Benefits of MCP Simple Node Naming**:
- **Discoverable**: `pflow registry search mcp-github` finds all GitHub MCP nodes
- **Predictable**: Users can guess node names (`mcp-slack-send-message`)
- **Future CLI Ready**: Natural mapping to `pflow mcp slack send-message` in v2.0
- **Consistent**: Same pattern as native platform nodes (`github-get-issue`, `slack-send-message`)

---

## 6 · Shared Store Integration

### 6.1 Natural Interface Design

**Core Principle**: MCP wrapper nodes use the same intuitive shared store patterns as manually-written nodes.

**Interface Mapping Process**:

1. **Analyze MCP Tool Schema**: Extract input/output parameters from `/tools/list`
2. **Generate Natural Keys**: Create intuitive shared store key names
3. **Handle Optional Parameters**: Map optional inputs to shared store with sensible defaults
4. **Flatten Complex Outputs**: Convert nested MCP responses to flat shared store structure

### 6.2 Proxy Pattern Support

**Complex Flow Compatibility**: MCP wrapper nodes fully support proxy mappings for marketplace integration:

```json
{
  "mappings": {
    "mcp-github-search-code": {
      "input_mappings": {
        "query": "search_terms",
        "language": "prog_lang_filter"
      },
      "output_mappings": {
        "search_results": "github_code_matches"
      }
    }
  }
}
```

**Generated Proxy Integration**: Flow orchestration code automatically handles proxy setup:

```python
# Generated flow code handles proxy when mappings defined
def execute_mcp_node_with_mapping(node, shared, mappings=None):
    if mappings and node.id in mappings:
        proxy = NodeAwareSharedStore(
            shared,
            input_mappings=mappings[node.id].get("input_mappings", {}),
            output_mappings=mappings[node.id].get("output_mappings", {})
        )
        return node._run(proxy)  # Node uses natural interface, proxy handles translation
    else:
        return node._run(shared)  # Direct access when no mapping needed
```

### 6.3 CLI Resolution Integration

**Follows Established Rules**: MCP wrapper nodes adhere to "Type flags; engine decides" CLI resolution:

```bash
# CLI flag matches shared store key = data injection
pflow mcp-github-search-code --query="authentication bugs" --language="python"
# Results in: shared["query"] = "authentication bugs", shared["language"] = "python"

# CLI flag matches param name = param override
pflow mcp-github-search-code --max-results=20
# Results in: params["max_results"] = 20

# Complex flow with established pipe syntax
echo "TODO comments" | pflow mcp-github-search-code --language=python >> summarize-text >> mcp-slack-send-message --channel=dev-team
```

---

## 7 · Simple Error Handling

### 7.1 MCP Error Handling

**Replaces**: Transport-specific error handling
**Adopts**: pflow's simple error propagation

```python
class McpErrorHandler:
    """Handles MCP protocol errors with clear error messages."""

    @classmethod
    def handle_mcp_error(cls, mcp_error):
        """Convert MCP error to clear exception with helpful message."""
        error_messages = {
            "rate_limited": "GitHub API rate limit exceeded. Please try again later.",
            "unauthorized": "Authentication failed. Check your GitHub token.",
            "forbidden": "Permission denied. Check your token scopes.",
            "not_found": "Resource not found. Check repository and query.",
            "timeout": "Request timed out. Please try again.",
            "server_error": "GitHub server error. Please try again later.",
            "network_error": "Network error. Check your connection."
        }

        message = error_messages.get(mcp_error.type, f"MCP error: {mcp_error}")
        raise RuntimeError(message)
```

### 7.2 Simple Error Integration

**Clear Error Messages**: MCP wrapper nodes provide helpful error messages:

```python
# Flow setup with comprehensive error handling
github_search = McpGithubSearchCode()
process_results = ProcessSearchResults()
retry_handler = ExponentialBackoff()
auth_refresher = RefreshGithubToken()
error_reporter = LogError()

# Primary flow path
github_search >> process_results

# Error handling paths using actions
github_search - "rate_limited" >> retry_handler >> github_search  # Loop back after delay
github_search - "auth_failed" >> auth_refresher >> github_search   # Refresh token and retry
github_search - "resource_missing" >> error_reporter              # Log and continue
github_search - "timeout" >> retry_handler                        # Standard retry logic

# Generated flow supports complex error recovery patterns
flow = Flow(start=github_search)
```

### 7.3 Transport Error Unification

**All Transports**: Unified error handling regardless of MCP transport mechanism:

| MCP Transport Error | Error Handling | Result |
|---|---|---|
| `stdio` process death | Clear error message | Flow fails with helpful message |
| `sse` connection timeout | Timeout exception | Flow fails with retry suggestion |
| `uds` socket error | Network error exception | Flow fails with connection advice |
| Rate limit (any transport) | Rate limit exception | Flow fails with retry timing |
| Auth failure (any transport) | Auth error exception | Flow fails with token guidance |

---

## 8 · Flow Orchestration & JSON IR

### 8.1 Complete IR Integration

**MCP Nodes in JSON IR**: Full participation in pflow's intermediate representation:

```json
{
  "metadata": {
    "planner_version": "1.0.0",
    "created_at": "2024-01-01T12:00:00Z",
    "prompt": "find Python authentication bugs on GitHub and post summary to Slack"
  },
  "nodes": [
    {
      "id": "mcp-github-search-code",
      "version": "1.0.0",
      "type": "mcp_wrapper",
      "params": {"max_results": 15},
      "mcp_metadata": {
        "server_id": "github-server",
        "tool_name": "search_code",
        "version": "1.2.0"
      }
    },
    {
      "id": "llm",
      "version": "1.0.0",
      "params": {"model": "gpt-4", "temperature": 0.3}
    },
    {
      "id": "mcp-slack-send-message",
      "version": "1.0.0",
      "type": "mcp_wrapper",
      "params": {},
      "mcp_metadata": {
        "server_id": "slack-server",
        "tool_name": "send_message",
        "version": "2.1.0"
      }
    }
  ],
  "edges": [
    {"from": "mcp-github-search-code", "to": "llm"},
    {"from": "llm", "to": "mcp-slack-send-message"}
  ],
  "mappings": {
    "mcp-slack-send-message": {
      "input_mappings": {"message": "summary", "channel": "dev-team-alerts"}
    }
  }
}
```

### 8.2 Planner Compatibility

**LLM Selection**: Thinking models can discover and select MCP wrapper nodes naturally:

```json
{
  "reasoning": "User wants to find GitHub issues and notify via Slack. I'll use MCP GitHub integration, LLM for processing, and Slack notification.",
  "selection_type": "new_composition",
  "chosen_nodes": [
    "mcp-github-search-code",
    "llm",
    "mcp-slack-send-message"
  ],
  "flow_structure": "search → summarize → notify"
}
```

**Validation Integration**: MCP nodes participate in planner's validation framework:

- Interface compatibility checking between MCP outputs and downstream node inputs
- Automatic mapping generation when key names don't align
- Action-based error path validation

### 8.3 Generated Flow Code

**Complete Flow Generation**: Compiler produces executable Python using pocketflow patterns:

```python
# Generated flow code from JSON IR
def create_mcp_integrated_flow():
    # Instantiate wrapper nodes (generated classes)
    github_search = McpGithubSearchCodeNode()
    processor = LLMNode()  # General LLM node
    slack_sender = McpSlackSendMessageNode()  # Another MCP wrapper

    # Configure with IR parameters using pocketflow's set_params()
    github_search.set_params({"max_results": 15})
    processor.set_params({"model": "gpt-4", "temperature": 0.3})
    slack_sender.set_params({})  # Uses defaults

    # Wire simple sequential flow
    github_search >> processor >> slack_sender

    return Flow(start=github_search)

# Runtime execution with shared store + proxy support
def execute_flow():
    shared = {
        "query": "authentication vulnerabilities",  # CLI injection
        "language": "python",                      # CLI injection
        "dev-team-alerts": "#security-alerts"     # Mapped to "channel"
    }

    flow = create_mcp_integrated_flow()

    # Handle proxy mappings when defined in IR
    for node in flow.nodes:
        if hasattr(node, '_mcp_tool_name') and node.id in ir.get("mappings", {}):
            # Proxy setup handled by generated code
            pass

    result = flow.run(shared)
    return result
```

---

## 9 · Security & Purity Model

### 9.1 Flow-Safe Integration

**Adopts pflow Patterns**: Use `@flow_safe` decorator instead of `side_effects` classification:

```python
from pocketflow import Node, flow_safe

# Read-only MCP tools (rare but possible)
@flow_safe
class McpGithubGetRepository(Node):
    """Get repository metadata (read-only operation)."""
    # Cacheable, can participate in pure flows
    # Generated only when MCP manifest declares readonly=true

# Default: impure tools (most MCP tools have side effects)
class McpSlackSendMessage(Node):
    """Send message to Slack channel (has side effects)."""
    # No @flow_safe decorator
    # Not cacheable, proper retry/failure handling required
```

### 9.2 Trust and Caching

**Caching Rules**:

- **MCP wrappers default to impure** - no caching unless explicitly marked `@flow_safe`
- **Read-only tools**: Can be marked `@flow_safe` if MCP manifest declares `readonly=true` AND user provides `--trust-readonly` flag
- **Cache keys**: Follow standard pflow pattern - `node_hash ⊕ effective_params ⊕ input_data_sha256`

### 9.3 Authentication & Authorization

**Environment Integration**:

```python
# MCP server configuration with auth
{
  "server_id": "github-enterprise",
  "transport": "sse",
  "url": "https://api.github.internal/mcp",
  "auth": {
    "token_env": "GITHUB_ENTERPRISE_TOKEN",  # Required env var
    "scopes": ["repo:read", "user:read"]     # Required OAuth scopes
  }
}
```

**Runtime Validation**:

- Token presence validated before node execution
- Scope compatibility checked against MCP server capabilities
- Auth failures trigger `"auth_failed"` action for flow-based recovery

### 9.4 Network Security

**Egress Control**:

- Generated wrapper nodes respect pflow's network policy
- Remote MCP servers added to allowlist automatically on registration
- Host validation performed by MCP executor before connection

**TLS Requirements**:

- `https://` required for remote SSE/HTTP transports
- Certificate pinning supported via optional pin files
- Development `--insecure` flag bypasses for local testing

---

## 10 · Complete Integration Examples

### 10.1 Simple MCP Integration

**End-to-End Workflow**:

```bash
# 1. Register MCP server in unified registry
pflow registry add-mcp --server github --command "mcp-github" --transport stdio

# 2. Wrapper nodes auto-generated and discoverable
pflow registry list --filter github
# mcp-github-search-code    Search code in repositories
# mcp-github-get-repo       Get repository information
# mcp-github-create-issue   Create new issue

# 3. Direct CLI usage with natural interface
pflow mcp-github-search-code --query "authentication" --language "python" >> summarize-text

# 4. Natural language planning automatically discovers MCP nodes
pflow "find Python authentication bugs on GitHub and create a summary"
# Planner selects: mcp-github-search-code >> llm >> write-file
```

### 10.2 Complex Flow with Error Handling

**Production-Ready Flow**:

```python
# Simple flow with MCP nodes
search_node = McpGithubSearchCodeNode()
processor = LLMNode()  # Use general LLM node for text processing
notifier = McpSlackSendMessageNode()

# Simple sequential flow
search_node >> processor >> notifier

# Clean, predictable execution path
flow = Flow(start=search_node)
```

**CLI Execution**:

```bash
# Simple pipe with multiple MCP tools
echo "security vulnerability" | \
  pflow mcp-github-search-code --language python --max-results 10 >> \
  llm --prompt="Summarize these security findings" --temperature 0.3 >> \
  mcp-slack-send-message --channel security-alerts
```

### 10.3 Marketplace Compatibility

**Proxy Mapping for Different Flow Schemas**:

```json
{
  "marketplace_flow": {
    "nodes": ["mcp-github-search-code", "text-processor", "notification-sender"],
    "mappings": {
      "mcp-github-search-code": {
        "input_mappings": {
          "query": "search_terms",
          "language": "target_language"
        },
        "output_mappings": {
          "search_results": "raw_code_data"
        }
      }
    }
  }
}
```

**Same wrapper node, different flow context** - proxy handles all translation transparently.

---

## 11 · Supported Transports

**Transport Implementation**: MCP executor handles all protocol details internally, wrapper nodes remain transport-agnostic.

| Transport | Use Case | Connection Method | Autostart | Notes |
|---|---|---|---|---|
| `stdio` | Local development, trusted tools | Subprocess stdin/stdout | Yes | Default for local MCP servers |
| `uds` | Linux containers, IPC | Unix domain socket | Yes | High-performance local communication |
| `pipe` | Windows named pipes | Windows pipe client | Yes | Windows-native IPC mechanism |
| `sse` | Remote HTTP servers | Server-Sent Events | No | Real-time streaming over HTTP |
| `stream-http` | HTTP-based MCP | Chunked HTTP POST | No | Emerging standard, SSE-compatible |

**Transport Selection**: Automatic based on MCP server configuration, transparent to wrapper node implementation.

---

## 12 · Testing & Validation

### 12.1 MCP Wrapper Testing

**Unit Testing**: Standard pflow node testing patterns apply:

```python
def test_mcp_github_search_node():
    """Test MCP wrapper node like any other pflow node."""
    # Arrange
    node = McpGithubSearchCode()
    node.set_params({"max_results": 5})
    shared = {"query": "test query", "language": "python"}

    # Mock the MCP executor to avoid external calls
    with patch.object(node._mcp_executor, 'call_tool') as mock_call:
        mock_call.return_value = {"results": [{"name": "test.py"}]}

        # Act
        node.run(shared)

        # Assert
        assert "search_results" in shared
        assert len(shared["search_results"]) == 1
        mock_call.assert_called_once()
```

### 12.2 Integration Testing

**End-to-End Validation**:

- Mock MCP servers for deterministic testing
- Transport-specific test suites for stdio/sse/uds validation
- Error simulation for action-based flow testing
- Proxy mapping validation with complex flow scenarios

### 12.3 Registry Validation

**MCP Registration Testing**:

- Wrapper generation validation against known MCP tool manifests
- Metadata extraction accuracy for planner integration
- CLI resolution correctness for generated natural interfaces

---

## 13 · Migration & Compatibility

### 13.1 Existing MCP Integration Migration

**For Current Users**: Smooth transition from standalone MCP configuration:

```bash
# Migrate existing mcp.json to unified registry
pflow registry migrate-mcp --from ~/.pflow/mcp.json --backup

# Validate migration results
pflow registry validate --mcp-wrappers
pflow registry test-mcp-connections
```

### 13.2 Backward Compatibility

**Deprecation Timeline**:

- **Phase 1**: Both systems supported, warnings for old commands
- **Phase 2**: Old `mcp.json` read-only, migration prompted
- **Phase 3**: Legacy system removed, registry-only approach

### 13.3 Tool Evolution

**MCP Version Management**:

- Automatic wrapper regeneration when MCP tool versions change
- Validation of breaking changes in tool interfaces
- Graceful handling of deprecated MCP tools

---

## 14 · Future Enhancements

### 14.1 Advanced MCP Features

**Roadmap Alignment** with MCP protocol development:

- **Streaming Support**: Chunked responses for large data sets
- **Multimodal Integration**: Video/audio MCP tools as pflow nodes
- **Agent Graphs**: MCP server composition for complex integrations

### 14.2 pflow-Specific Enhancements

**Enhanced Integration**:

- **Visual Flow Builder**: Drag-and-drop MCP tool integration
- **Performance Optimization**: Connection pooling for high-throughput MCP flows
- **Marketplace Integration**: Certified MCP wrapper node distribution

---

## 15 · Summary

This specification transforms MCP integration from a parallel subsystem into a native pflow pattern that fully embraces the shared store + proxy model. Key achievements:

✅ **Pattern Consistency**: MCP wrapper nodes indistinguishable from manual nodes
✅ **Registry Unity**: Single discovery system includes MCP tools
✅ **CLI Compatibility**: Natural flag resolution following established rules
✅ **Flow Integration**: Complete JSON IR, proxy mapping, and action-based error handling
✅ **Planner Compatibility**: LLM can discover and select MCP tools naturally
✅ **Framework Alignment**: Pure pocketflow implementation without modifications

**Result**: Developers can use MCP tools exactly like any other pflow node, with the full power of flow orchestration, conditional error handling, and intelligent planning.

## See Also

- **Architecture**: [Shared Store + Proxy Pattern](../core-concepts/shared-store.md) - Foundation for MCP wrapper node interfaces
- **Architecture**: [MVP Scope](./mvp-scope.md) - Why MCP is deferred to v2.0
- **Patterns**: [Simple Nodes](./simple-nodes.md) - How MCP tools become simple nodes
- **Components**: [Registry](../core-concepts/registry.md) - Unified registry integration for MCP nodes
- **Components**: [JSON Schemas](../core-concepts/schemas.md) - MCP metadata in Flow IR
- **Related Features**: [Autocomplete](./autocomplete.md) - MCP node discovery in CLI autocomplete
- **Implementation**: [Components](../architecture/components.md) - MCP components in v2.0 inventory
