# MCP Integration Consistency Analysis

## Executive Summary

After thorough analysis of the MCP Server Integration and Security Model against the three source of truth documents, I've identified **several significant contradictions and gaps** that need to be addressed to ensure architectural consistency.

## 🚨 Critical Contradictions

### 1. Node Interface Pattern Violations

**Source of Truth**: Nodes should use natural interfaces like `shared["text"]` and focus on business logic
**MCP Document**: Shows wrapper generation but doesn't demonstrate adherence to shared store pattern

```python
# MCP shows this structure:
class Mcp_<tool>(Node):
    server_id   = "weather-remote"
    tool_name   = "get_weather"
    tool_version = "1.2.4"
    manifest_sha = "5c0…"
    side_effects = ["network"]
```

**Issue**: Missing demonstration of `prep()`/`exec()`/`post()` methods and natural shared store interfaces.

### 2. Registry Integration Disconnect

**Source of Truth**: Single node registry with metadata extraction from Python classes
**MCP Document**: Introduces separate `mcp.json` registry without clear integration

**Contradiction**: The planner spec describes automatic discovery of nodes through Python class scanning, but MCP introduces a parallel registry system without explaining how these integrate.

### 3. CLI Resolution Conflicts

**Source of Truth**: "Type flags; engine decides" - CLI flags are either data injection or param overrides
**MCP Document**: Shows CLI usage but doesn't follow established resolution algorithm

```bash
# MCP shows:
pflow mcp_github.search_code --query "TODO" >> summarize >> mcp_stripe.create_customer
```

**Issue**: No explanation of how `--query` resolves (shared store injection vs param override) according to the single-rule CLI model.

### 4. Parameter Structure Inconsistency

**Source of Truth**: Flat params structure via `self.params.get("key", default)`
**MCP Document**: No demonstration of how wrapper nodes handle parameters

**Gap**: Missing specification of how MCP tool parameters integrate with pflow's flat params system.

## ⚠️ Significant Gaps

### 5. Missing Shared Store Specification

**Source of Truth**: Nodes read from and write to shared store using natural keys
**MCP Document**: No specification of how MCP tools interact with shared store

**Critical Missing Elements**:
- How MCP tool inputs map to shared store keys
- How MCP tool outputs are written to shared store
- Natural interface design for generated wrapper nodes

### 6. Proxy Pattern Integration Unclear

**Source of Truth**: Optional proxy mappings for complex routing scenarios
**MCP Document**: No mention of how MCP nodes participate in proxy mapping

**Questions**:
- Can MCP wrapper nodes use proxy mappings?
- How do MCP tools handle input/output mapping for marketplace compatibility?

### 7. Flow Integration Gaps

**Source of Truth**: Flows use action-based transitions and JSON IR
**MCP Document**: No explanation of how MCP nodes integrate with flow orchestration

**Missing Specifications**:
- How MCP wrapper nodes define actions for conditional flow control
- How MCP tools participate in JSON IR generation
- Integration with planner's validation framework

## 🔧 Implementation Inconsistencies

### 8. Metadata Extraction Mismatch

**Source of Truth**: Node metadata extracted from docstrings and annotations
**MCP Document**: Metadata comes from `/tools/list` MCP endpoint

```python
# Source of Truth expects:
class YTTranscript(Node):
    """Fetches YouTube transcript.
    
    Interface:
    - Reads: shared["url"] - YouTube video URL
    - Writes: shared["transcript"] - extracted transcript text
    - Params: language (default "en") - transcript language
    """
```

**Issue**: MCP tools don't provide this docstring format, creating inconsistency in metadata discovery.

### 9. Purity Model Conflicts

**Source of Truth**: `@flow_safe` decorator for pure nodes, trust-based caching
**MCP Document**: `side_effects = ["network"]` and `--trust-pure` flag

**Contradiction**: Different purity classification systems that may not be compatible.

### 10. Error Handling Pattern Divergence

**Source of Truth**: Action-based transitions for error handling
**MCP Document**: Transport-specific error responses without flow integration

**Issue**: MCP error handling doesn't align with pflow's action-based conditional flow control.

## 📋 Recommended Corrections

### High Priority Fixes

1. **Align Wrapper Node Generation**:
   ```python
   class McpGithubSearchCode(Node):
       """Search code in GitHub repositories via MCP.
       
       Interface:
       - Reads: shared["query"] - search query string
       - Writes: shared["search_results"] - found code snippets
       - Params: max_results (default 10) - maximum results to return
       """
       
       def prep(self, shared):
           return shared["query"]
       
       def exec(self, prep_res):
           max_results = self.params.get("max_results", 10)
           return self.mcp_executor.call_tool("search_code", {
               "query": prep_res,
               "max_results": max_results
           })
       
       def post(self, shared, prep_res, exec_res):
           shared["search_results"] = exec_res
   ```

2. **Integrate with Single Registry**:
   - MCP wrapper nodes should be discoverable through same metadata extraction
   - `mcp.json` should be configuration, not a separate registry
   - Generated nodes should appear in planner's node discovery

3. **Follow CLI Resolution Rules**:
   ```bash
   # Should follow: flags matching shared keys = injection
   pflow mcp-github-search-code --query="TODO"  # shared["query"] = "TODO"
   ```

4. **Specify Shared Store Integration**:
   - Document natural key naming conventions for MCP tools
   - Show how tool inputs/outputs map to shared store
   - Demonstrate proxy mapping support for complex scenarios

### Medium Priority Improvements

5. **Align Purity Models**: Use `@flow_safe` decorator instead of `side_effects` array
6. **Integrate Error Handling**: Use action-based transitions for MCP failures
7. **Support Flow Orchestration**: Show how MCP nodes participate in JSON IR

## 🎯 Conclusion

The MCP integration document introduces a parallel architecture that doesn't fully align with pflow's established patterns. While the core concept of wrapping MCP tools as pflow nodes is sound, the implementation needs significant adjustments to maintain consistency with the shared store pattern, CLI resolution rules, and flow orchestration framework.

**Priority**: Address wrapper node generation and shared store integration first, as these are fundamental to pflow's architecture. The registry and CLI resolution issues should be resolved before implementation to avoid creating incompatible patterns. 