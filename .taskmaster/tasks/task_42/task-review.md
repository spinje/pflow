# Task 42 Review: Claude Code Agentic Node

## Metadata
<!-- Implementation Date: 2025-09-04 to 2025-09-07 -->
<!-- Session ID: dde18df2-7c45-4d38-a89a-a964a8ea5e5d -->
<!-- PR: https://github.com/spinje/pflow/pull/17 -->
<!-- Commit: 6fc9a69 -->

## Executive Summary
Implemented a "super node" for pflow that integrates Claude Code SDK to execute comprehensive development tasks with AI assistance. Features a dynamic schema-driven output system that converts user schemas to prompt instructions, enabling structured outputs from Claude's unstructured text generation while capturing full execution metadata including costs, tool usage, and streaming progress.

## Implementation Overview

### What Was Built
- **ClaudeCodeNode** class extending PocketFlow's Node base class
- Dynamic schema-to-prompt conversion system for structured outputs
- Dual authentication support (API key and CLI auth)
- Comprehensive metadata capture (cost, duration, token usage, tool uses)
- Full tracing integration following established LLM patterns
- Tool whitelist enforcement for security

**Major deviations from spec:**
- Removed `skip_auth_check` parameter - let SDK handle authentication
- Removed `append_system_prompt` - redundant with `system_prompt`
- Changed from individual schema keys in shared to nested dict structure
- Model default was initially wrong (`claude-sonnet-4-20250514` vs `claude-3-5-sonnet-20241022`)

### Implementation Approach
Followed MCP node's async-to-sync wrapper pattern exactly, prioritizing compatibility with existing pflow patterns over novel approaches. Used schema-as-system-prompt innovation to work around SDK's lack of native structured output support.

## Files Modified/Created

### Core Changes
- `src/pflow/nodes/claude/claude_code.py` - Main implementation with full node lifecycle
- `src/pflow/nodes/claude/__init__.py` - Package exports
- `tests/test_nodes/test_claude/test_claude_code.py` - Comprehensive test suite (31 tests)
- `pyproject.toml` - Added claude-code-sdk>=0.0.20 dependency
- `src/pflow/core/metrics.py` - Fixed cost calculation to use actual costs when available

### Test Files
- `tests/test_nodes/test_claude/test_claude_code.py` - All 23 spec criteria plus edge cases
- Critical tests: Authentication, schema parsing, JSON extraction, error transformations

## Integration Points & Dependencies

### Incoming Dependencies
- **Registry Scanner** -> ClaudeCodeNode (via Enhanced Interface Format in docstring)
- **InstrumentedNodeWrapper** -> ClaudeCodeNode (captures llm_usage for tracing)
- **WorkflowExecutor** -> ClaudeCodeNode (standard node execution)
- **Metrics System** -> ClaudeCodeNode.llm_usage (reads cost and token data)

### Outgoing Dependencies
- ClaudeCodeNode -> **claude-code-sdk** (core functionality)
- ClaudeCodeNode -> **subprocess** (removed - was for auth check)
- ClaudeCodeNode -> **asyncio** (async-to-sync wrapper)

### Shared Store Keys
- `shared["result"]` - Main output (dict with text or schema keys)
- `shared["llm_usage"]` - Standardized metrics format for tracing
- `shared["_claude_metadata"]` - Full metadata from ResultMessage
- `shared["_claude_tools"]` - Tool usage audit trail
- `shared["_claude_progress"]` - Streaming progress events
- `shared["_schema_error"]` - Error message when JSON parsing fails

## Architectural Decisions & Tradeoffs

### Key Decisions
1. **Schema-as-system-prompt** -> Converts schemas to JSON instructions -> Alternative: Wait for SDK structured output support
2. **Remove --output-format json** -> SDK crashes with it, streaming works fine -> Alternative: Subprocess fallback
3. **Conservative retry (2 attempts)** -> Expensive API calls -> Alternative: Standard 3 retries
4. **Store metadata in multiple formats** -> Backward compatibility + tracing -> Alternative: Single format
5. **Aggregate all token types** -> Accurate cost calculation -> Alternative: Only base tokens

### Technical Debt Incurred
- JSON extraction uses multiple regex strategies (fragile)
- No streaming output to users (accumulate-then-return)
- Schema prompt might need tuning for complex schemas
- Tool whitelist hardcoded (should be configurable)

## Testing Implementation

### Test Strategy Applied
Mock SDK at query() function level, not deep internals. Test integration patterns, not actual API calls. All 23 spec criteria covered plus edge cases.

### Test Suite Status
- **31 tests total** - All passing after fixing for consistent dict format
- **6 tests updated 2025-09-07** - Changed to expect dict format instead of raw strings
- **Full suite**: 1949 passed, 162 skipped

### Critical Test Cases
- `test_valid_task_with_schema` - Validates schema-driven output
- `test_rate_limit_error` - Error transformation to user-friendly message
- `test_schema_to_prompt_conversion` - Core innovation validation
- `test_partial_json_response` - Missing keys stored as None

## Unexpected Discoveries

### Gotchas Encountered
1. **SDK parameter names differ from typical LLM APIs**: `max_thinking_tokens` not `max_tokens`, no `temperature`
2. **--output-format json breaks SDK**: Returns error `'list' object has no attribute 'items'` - must use streaming
3. **ResultMessage contains metadata**: Not documented, found through testing - this is how we get cost/usage
4. **Token aggregation critical**: Cache tokens in separate fields, must sum for costs
5. **Metrics system ignores actual costs**: Always calculates from tokens with hardcoded pricing
6. **Metadata storage bug**: Must store metadata BEFORE any early returns in `_store_results()`
7. **Prompt changes needed**: Claude outputs preliminary text with schema unless prompt is very forceful

### Edge Cases Found
- Claude outputs preliminary text with `max_turns=1` instead of JSON
- Authentication can timeout with `claude doctor` command
- Large schemas (>50 keys) need validation
- Binary context data needs special handling

## Patterns Established

### Reusable Patterns
```python
# Async-to-sync wrapper (from MCP node)
def exec(self, prep_res: dict) -> dict:
    # NO try/except - let exceptions bubble for retry
    result = asyncio.run(self._exec_async(prep_res), debug=False)
    return result

# Standardized llm_usage format
shared["llm_usage"] = {
    "model": model,
    "input_tokens": total_input,  # Sum ALL token types
    "output_tokens": output_tokens,
    "total_tokens": total,
    "total_cost_usd": actual_cost,  # Actual > calculated
}
```

### Anti-Patterns to Avoid
- Don't use `extra_args=["--output-format", "json"]` - breaks SDK with AttributeError
- Don't catch exceptions in exec() - breaks retry mechanism
- Don't trust Claude's first response with max_turns=1 - outputs preliminary text
- Don't calculate cost from tokens when actual cost available
- Don't return early before storing metadata - causes data loss
- Don't use weak prompts with schema - Claude ignores JSON instructions

## Breaking Changes

### API/Interface Changes
None - follows standard node interface

### Behavioral Changes
- Metrics now show actual costs instead of estimates (592x difference fixed)
- Results always stored as dict structure for consistency:
  - Without schema: `{"text": response_text}`
  - With schema: dict with schema keys directly
  - Parse failure: `{"text": raw_text}` plus `_schema_error`

## Future Considerations

### Extension Points
- Add progress callbacks for real-time visibility
- Support for conversation state/memory
- Configurable tool whitelist
- Native structured output when SDK supports it

### Scalability Concerns
- Token costs can be high with cache creation
- 300s timeout might be insufficient for complex tasks
- No streaming means memory accumulation for long responses

## AI Agent Guidance

### Quick Start for Related Tasks
1. Read `src/pflow/nodes/mcp/mcp_node.py` for async patterns
2. Check `src/pflow/nodes/llm/llm.py` for parameter fallback patterns
3. Study `src/pflow/runtime/instrumented_wrapper.py` for tracing integration
4. Use `shared["llm_usage"]` format for metrics compatibility

### Common Pitfalls
- SDK parameters differ from OpenAI/Anthropic standard APIs
- Registry requires Enhanced Interface Format in CLASS docstring, not module
- Metrics system needs actual cost in `total_cost_usd` field
- Always aggregate ALL token types for accurate counts
- ResultMessage comes AFTER AssistantMessage in streaming

### Test-First Recommendations
Run these first when modifying:
```bash
# Quick validation
pytest tests/test_nodes/test_claude/test_claude_code.py::test_valid_task_with_schema -v

# Check tracing integration
pytest tests/test_nodes/test_claude/test_claude_code.py::test_metadata_capture -v

# Verify cost calculation
python -c "from pflow.nodes.claude import ClaudeCodeNode; print('Import works')"
```

## Latest Session Updates (2025-09-07)

### Critical Fixes Applied
1. **Output Format Investigation**: Discovered `--output-format json` breaks SDK, removed it
2. **Metadata Capture Fix**: ResultMessage provides metadata in streaming mode
3. **Test Suite Updates**: Fixed 6 failing tests to match dict return format
4. **Prompt Strengthening**: Made schema prompts more forceful with "YOU MUST RESPOND WITH JSON ONLY"

### Example Workflows Created
- `claude-code-basic.json` - Simple code generation with metadata reporting
- `claude-code-schema.json` - Code review with structured output schema
- `claude-code-debug.json` - Error analysis with detailed schema
- `claude-code-git-workflow.json` - Multi-step git workflow with cost tracking

### Documentation Created
- `AUTHENTICATION.md` - Comprehensive auth guide for both methods
- `examples/nodes/claude-code/README.md` - Usage examples and patterns
- Progress log with all implementation decisions and discoveries

---

*Generated from implementation context of Task 42*
*Final review updated: 2025-09-07*