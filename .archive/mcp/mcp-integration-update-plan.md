# MCP Integration Update Plan

## Executive Summary

This document outlines a comprehensive plan to update the MCP Server Integration and Security Model to align with pflow's architectural patterns. The plan addresses critical contradictions identified in the consistency analysis while leveraging MCP's strengths for external tool integration.

## 🎯 Core Alignment Strategy

### 1. Unified Architecture Vision

**Goal**: Transform MCP from a parallel integration to a native pflow pattern that follows the shared store + proxy model.

**Key Principle**: MCP wrapper nodes should be indistinguishable from manually-written pflow nodes in terms of interface, behavior, and integration patterns.

## 📋 Section-by-Section Update Plan

### Section 2: Terminology Updates

**Current Issues**:
- Introduces separate "Registrar" concept that conflicts with planner's single registry
- Uses MCP-specific terminology that doesn't align with pflow patterns

**Required Changes**:

```markdown
| Term | Meaning |
|---|---|
| **MCP Wrapper Node** | Auto-generated pflow Node subclass that exposes MCP tool via natural shared store interface |
| **MCP Configuration** | JSON config defining MCP server connections (part of pflow registry system) |
| **MCP Executor** | Internal component handling MCP protocol communication (hidden from node interface) |
| **Natural Interface Mapping** | Translation layer between MCP tool schemas and pflow's natural key conventions |
```

### Section 3: Registry Integration Overhaul

**Current Problem**: Separate `mcp.json` registry conflicts with planner's single registry system.

**New Approach**: Integrate MCP configuration into pflow's existing registry architecture.

**Implementation Plan**:

1. **Replace standalone `mcp.json`** with registry entries:
   ```python
   # In pflow's node registry system
   {
     "node_id": "mcp-github-search-code",
     "type": "mcp_wrapper",
     "mcp_config": {
       "server_id": "github-server",
       "tool_name": "search_code",
       "transport": "stdio",
       "command": "mcp-github",
       "version": "1.2.0"
     },
     "interface": {
       "inputs": ["query", "language"],
       "outputs": ["search_results"],
       "params": {"max_results": 10}
     }
   }
   ```

2. **Planner Integration**: MCP wrapper nodes appear in `/tools/list` metadata alongside manually-written nodes

3. **CLI Commands Update**:
   ```bash
   # Replace mcp-specific commands with registry integration
   pflow registry add-mcp --server github --tool search_code --command "mcp-github"
   pflow registry list --filter mcp
   ```

### Section 4: Wrapper Node Generation - Complete Rewrite

**Current Problem**: Shows incomplete node structure without pflow patterns.

**New Implementation**:

```python
# Generated wrapper follows full pflow Node pattern
class McpGithubSearchCode(Node):
    """Search code in GitHub repositories via MCP.

    Interface:
    - Reads: shared["query"] - search query string
    - Reads: shared["language"] - programming language filter (optional)
    - Writes: shared["search_results"] - array of code search results
    - Params: max_results (default 10) - maximum results to return
    - Actions: "default", "rate_limited", "auth_failed"
    """

    # MCP metadata (used internally)
    _mcp_server_id = "github-server"
    _mcp_tool_name = "search_code"
    _mcp_tool_version = "1.2.0"
    _mcp_manifest_hash = "sha256:abc123..."

    def __init__(self):
        super().__init__()
        self._mcp_executor = McpExecutor(self._mcp_server_id)

    def prep(self, shared):
        """Extract search parameters from shared store."""
        query = shared.get("query")
        if not query:
            raise ValueError("Missing required 'query' in shared store")

        return {
            "query": query,
            "language": shared.get("language"),  # Optional
            "max_results": self.params.get("max_results", 10)
        }

    def exec(self, prep_res):
        """Execute MCP tool call."""
        try:
            response = self._mcp_executor.call_tool(
                self._mcp_tool_name,
                prep_res,
                expected_version=self._mcp_tool_version
            )
            return response["results"]
        except McpRateLimitError:
            return "rate_limited"  # Action-based error handling
        except McpAuthError:
            return "auth_failed"

    def post(self, shared, prep_res, exec_res):
        """Write results to shared store or return action."""
        if isinstance(exec_res, str):  # Action string
            return exec_res

        shared["search_results"] = exec_res
        return "default"
```

### Section 5: Shared Store Integration Specification

**New Section**: Add comprehensive shared store integration patterns.

**Content Structure**:

1. **Natural Key Conventions**:
   ```python
   # MCP tool: get_weather
   # Natural interface:
   # Inputs: shared["location"], shared["units"]
   # Outputs: shared["weather_data"]

   # MCP tool: search_code
   # Natural interface:
   # Inputs: shared["query"], shared["language"]
   # Outputs: shared["search_results"]
   ```

2. **Schema Translation Rules**:
   - MCP tool parameter names → natural shared store keys
   - Complex nested outputs → flattened shared store structure
   - Optional parameters → shared store defaults or params

3. **Proxy Mapping Support**:
   ```json
   {
     "mappings": {
       "mcp-github-search-code": {
         "input_mappings": {
           "query": "search_terms",
           "language": "prog_lang"
         },
         "output_mappings": {
           "search_results": "code_matches"
         }
       }
     }
   }
   ```

### Section 6: CLI Resolution Integration

**Current Problem**: Examples don't follow "Type flags; engine decides" rule.

**New Implementation**:

1. **Flag Resolution Examples**:
   ```bash
   # CLI flag matches shared store key = data injection
   pflow mcp-github-search-code --query="TODO" --language="python"
   # Results in: shared["query"] = "TODO", shared["language"] = "python"

   # CLI flag matches param name = param override
   pflow mcp-github-search-code --max-results=20
   # Results in: params["max_results"] = 20
   ```

2. **Complex Flow Examples**:
   ```bash
   # Following established CLI pipe syntax
   echo "authentication bug" | pflow mcp-github-search-code --language=python >> summarize-text >> mcp-slack-send-message --channel=dev-team
   ```

### Section 7: Action-Based Error Handling

**New Section**: Replace transport-specific error handling with pflow's action-based pattern.

**Implementation**:

```python
# In wrapper node generation:
def map_mcp_errors_to_actions(self, mcp_error):
    """Map MCP errors to pflow actions."""
    error_mapping = {
        "rate_limited": "rate_limited",
        "unauthorized": "auth_failed",
        "not_found": "resource_missing",
        "timeout": "timeout",
        "server_error": "server_error"
    }
    return error_mapping.get(mcp_error.type, "error")

# Flow integration:
search_node = McpGithubSearchCode()
search_node >> process_results                    # Default path
search_node - "rate_limited" >> wait_and_retry   # Handle rate limits
search_node - "auth_failed" >> refresh_token     # Handle auth issues
```

### Section 8: Flow and IR Integration

**New Section**: Show complete integration with pflow's JSON IR and flow orchestration.

**Content**:

1. **JSON IR Integration**:
   ```json
   {
     "nodes": [
       {
         "id": "mcp-github-search-code",
         "type": "mcp_wrapper",
         "params": {"max_results": 15},
         "mcp_metadata": {
           "server_id": "github-server",
           "tool_name": "search_code",
           "version": "1.2.0"
         }
       }
     ],
     "mappings": {
       "mcp-github-search-code": {
         "input_mappings": {"query": "search_terms"}
       }
     }
   }
   ```

2. **Planner Integration**: MCP nodes discoverable via metadata extraction and participate in LLM selection

### Section 9: Metadata Alignment

**Replace Current Approach** with pflow-compatible metadata extraction:

```python
# Generated docstring follows pflow conventions
def generate_node_docstring(mcp_tool):
    return f'''
    """{mcp_tool.description}

    Interface:
    {format_inputs(mcp_tool.input_schema)}
    {format_outputs(mcp_tool.output_schema)}
    {format_params(mcp_tool.parameters)}
    {format_actions(mcp_tool.error_types)}

    MCP Source: {mcp_tool.server_id}/{mcp_tool.name} v{mcp_tool.version}
    """
    '''
```

### Section 10: Purity and Caching Integration

**Replace `side_effects` with `@flow_safe`**:

```python
from pocketflow import Node, flow_safe

# For read-only MCP tools
@flow_safe
class McpGithubGetRepository(Node):
    """Get repository information (read-only)."""
    # Implementation...

# For tools with side effects (default)
class McpSlackSendMessage(Node):
    """Send message to Slack (impure - has side effects)."""
    # No @flow_safe decorator = not cacheable
```

### Section 11: Complete Integration Examples

**Replace existing examples** with end-to-end scenarios showing:

1. **Simple MCP Integration**:
   ```python
   # 1. Install MCP server
   pflow registry add-mcp --server github --command "mcp-github" --transport stdio

   # 2. Auto-generated wrapper appears in registry
   # 3. Available in planner's node discovery
   # 4. Usable in CLI flows
   pflow mcp-github-search-code --query "authentication" >> summarize-text

   # 5. Participates in JSON IR generation
   # 6. Supports proxy mappings for complex flows
   ```

2. **Complex Flow Integration**:
   ```bash
   # Natural language planner can select MCP nodes
   pflow "find Python authentication bugs on GitHub and summarize them"

   # Generates IR with MCP nodes:
   # mcp-github-search-code >> summarize-text >> format-markdown
   ```

3. **Error Handling Flows**:
   ```python
   github_search >> process_results
   github_search - "rate_limited" >> exponential_backoff >> github_search
   github_search - "auth_failed" >> refresh_github_token >> github_search
   ```

## 🔧 Implementation Phases

### Phase 1: Core Pattern Alignment (Week 1-2)
- [ ] Rewrite wrapper node generation to follow pflow Node pattern
- [ ] Implement shared store integration
- [ ] Add action-based error handling
- [ ] Create metadata extraction that follows pflow conventions

### Phase 2: Registry Integration (Week 3)
- [ ] Replace standalone mcp.json with registry integration
- [ ] Update CLI commands to use registry system
- [ ] Ensure MCP nodes appear in planner's node discovery

### Phase 3: Flow Integration (Week 4)
- [ ] Add JSON IR support for MCP nodes
- [ ] Implement proxy mapping support
- [ ] Add CLI resolution following "type flags; engine decides"
- [ ] Test with complex flow scenarios

### Phase 4: Documentation and Examples (Week 5)
- [ ] Update all examples to follow new patterns
- [ ] Add comprehensive integration guides
- [ ] Create testing scenarios
- [ ] Validate against source of truth documents

## 🎯 Success Criteria

1. **Pattern Consistency**: MCP wrapper nodes indistinguishable from manual nodes in interface and behavior
2. **Registry Unity**: Single node discovery system includes MCP nodes
3. **CLI Compatibility**: MCP nodes follow established CLI resolution rules
4. **Flow Integration**: MCP nodes participate fully in JSON IR, proxy mappings, and action-based transitions
5. **Planner Compatibility**: LLM can discover and select MCP nodes naturally
6. **Error Handling**: MCP errors handled through action-based transitions, not transport-specific responses

## 📚 Documentation Dependencies

**Must Reference**:
- Shared Store + Proxy Design Pattern (primary architectural guide)
- Planner Responsibility & Functionality Spec (for registry and metadata integration)
- Shared-Store CLI Runtime Specification (for CLI resolution rules)
- pocketflow framework documentation (for Node patterns)

This plan ensures MCP integration becomes a natural extension of pflow's architecture rather than a parallel system.
