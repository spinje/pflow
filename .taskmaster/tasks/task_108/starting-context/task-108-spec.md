# Task 108 Specification: Smart Trace Debug Output

This document captures all design decisions and Q&A from requirements gathering for Task 108.

## Requirements Interview

### Q1: Agent Context Management (Large Traces)

**Question:** Traces can be 500KB+ JSON. When an agent requests trace data via MCP, should we return the full markdown (risks context exhaustion) or implement a structured query interface where agents ask for specific slices?

**User Answer:** "the query interface is interesting but this is perhaps solving a different issues. my initial thought is that we should create a 'smart' markdown file or yaml file (or combination) that contains only the relevant info, we decide this smartly based on what went wrong"

**Decision:** Smart extraction based on error type, not query interface.

---

### Q2: Data Flow Visualization

**Question:** Shared store snapshots (before/after each node) are key to debugging but verbose. How should we visualize mutations in markdown?

**User Answer:** "Diff-style (+/-)"

**Decision:** Show only what changed using git-diff style. Compact but loses context of unchanged data.

---

### Q3: Cache/Cost Stats

**Question:** The planner trace captures prompt caching (cache_creation vs cache_read tokens). This is critical for cost optimization. How prominently should cache efficiency be surfaced?

**User Answer:** "we dont have to care about planner trace, this is about workflow traces or more specifically when an agent is iterating when building a pflow workflow from file. as for your question we can expose this as a separate query, the main functionality should be about debugging i think"

**Decision:** Focus on workflow traces only. Cost analysis is out of scope - can be separate query later.

---

### Q4: Failure Emphasis

**Question:** When a workflow fails mid-execution, the trace contains successful nodes before the failure. Should the markdown format emphasize the failure point or show the full execution timeline equally?

**User Answer:** "we should only include the most relevant details nothing else that is noise"

**Decision:** Failure-first with minimal context. Not full timeline.

---

### Q5: Template Error Context

**Question:** For the 'smart' extraction: when a template error occurs (e.g., ${fetch.result.msg} not found), should the output include the actual structure of fetch.result so the agent can immediately see the correct path?

**User Answer:** "Show structure + suggestion"

**Decision:** Include real output shape AND suggest likely correct path based on similarity matching.

---

### Q6: API Error Handling

**Question:** When an API/HTTP node fails (e.g., 404, auth error), the response body often contains the actual error details. Should we extract and surface these from the shared store?

**User Answer:** "the output from nodes should be stored using our structure-only feature. please investigate this using subagents in parallel so you understand what this is and why its important. we could show just the structure of the error and let agents read more using the read-fields command"

**Decision:** Integrate with Task 89's structure-only pattern. Show structure, provide drill-down commands via `read-fields`.

---

### Q7: File Structure

**Question:** Should the smart output format be a single file or separate 'summary' and 'details' files? Agents could read summary first, then details only if needed.

**User Answer:** "single file, we can consider showing bash commands with jq to read full trace fields, this is something we can discuss later"

**Decision:** Single markdown file with embedded drill-down commands.

---

### Q8: Upstream Data for Failed Nodes

**Question:** For successful nodes before the failure: should we include their outputs in the debug file (in case the error is about wrong data flowing through), or only the failed node's context?

**User Answer:** "structure only output so llm can dig deeper if they want (minimize tokens and allow for progressive disclosure)"

**Decision:** Show structure of upstream node outputs, not full data. Progressive disclosure pattern.

---

### Q9: Smart Extraction Approach

**Question:** The smart debug output needs to determine 'what went wrong'. Should this classification be rule-based (pattern matching on error types) or use an LLM call to analyze the trace and extract relevant context?

**User Answer:** "we start with rulebased and if the file gets to overwhelming for llms (too much tokens and overhead) we consider using llm"

**Decision:** Rule-based first, LLM fallback documented as future enhancement.

---

### Q10: Output Format

**Question:** You mentioned 'markdown or yaml (or combination)'. For agent consumption, YAML is more structured/parseable but markdown is more readable. What's your preference?

**User Answer:** "Markdown with YAML blocks"

**Decision:** Human-readable markdown with embedded ```yaml blocks for structured data.

---

### Q11: Drill-Down Commands

**Question:** The trace contains an execution_id. Should the debug output include ready-to-use commands for drilling deeper (e.g., jq queries or pflow commands)?

**User Answer:** "Yes, include commands"

**Decision:** Show copy-paste-ready jq queries and pflow commands.

---

### Q12: Iteration Diff

**Question:** When an agent iterates on a workflow.json and re-runs, should the debug output diff against the previous trace to show what changed?

**User Answer:** "this sounds interesting but it can be a future improvement, but document it!"

**Decision:** Out of scope. Document as future enhancement.

---

### Q13: Output Location

**Question:** The debug output will be generated alongside the existing JSON trace. Should it be a separate file (workflow-debug-*.md) or replace the trace message shown to the agent?

**User Answer:** "Both"

**Decision:** Save to file AND return in response. File for persistence, response for immediate use.

---

### Q14: Error Types

**Question:** For the rule-based smart extraction, we need to categorize error types. Based on the codebase, I see: template errors, API/HTTP errors, validation errors, shell command failures, LLM errors. Any others to consider?

**User Answer:** "this has to be investigated more later"

**Decision:** Start with obvious error types, refine during implementation. Don't finalize list now.

---

### Q15: Anomaly Detection (Silent Failures)

**Question:** When a node succeeds but produces unexpected output (e.g., empty list, null), this often causes downstream failures. Should 'unexpected output' be a rule category even when the node itself succeeded?

**User Answer:** "Yes, detect anomalies"

**Decision:** Flag empty list, null, empty string as potential issues even on success.

---

### Q16: Existing Tools

**Question:** The existing `scripts/analyze-trace/analyze.py` creates per-LLM-call markdown files for prompt engineering. Should this task deprecate that script, or keep both tools for different purposes?

**User Answer:** "Deprecate analyze.py"

**Decision:** New tool covers all use cases. Mark scripts/analyze-trace/ as deprecated.

---

### Q17: MCP Integration

**Question:** For MCP tool access: should this be a new tool (e.g., `get_debug_trace`) or extend the existing workflow_execute response to include debug info on failure?

**User Answer:** "New dedicated tool"

**Decision:** `get_debug_trace(trace_path_or_id)` as explicit tool call.

---

### Q18: Success Metrics

**Question:** What's the primary success metric for this feature? How will we know it's working well?

**User Answer:** "both 1 and 2" (agent iteration speed AND token efficiency)

**Decision:** Dual metrics: fewer round-trips + 10x token reduction target.

---

### Q19: CLI Naming

**Question:** What should the CLI command be called? This affects discoverability and user mental model.

**User Answer:** "pflow trace debug" (option 1)

**Decision:** Subcommand of trace group. Clear purpose, follows 'trace' namespace.

---

### Q20: Trace Selection

**Question:** Should the command auto-detect the latest trace file, or always require explicit path?

**User Answer:** "auto detect with option to send in execution id"

**Decision:** `pflow trace debug` uses latest, `pflow trace debug <id>` for specific.

---

### Q21: Success vs Failure Format

**Question:** The debug output should work for both successful and failed workflows (success may have warnings/anomalies). Should the output format differ based on outcome?

**User Answer:** "Same format, different focus"

**Decision:** Same structure, but 'Warnings' section for success, 'Errors' section for failure.

---

### Q22: Docs Scope

**Question:** Should this task include updating the agent instructions (mcp-agent-instructions.md, mcp-sandbox-agent-instructions.md) to use the new debug tools, or keep that as a follow-up?

**User Answer:** "Include in this task"

**Decision:** Update agent instructions as part of this task. Complete feature delivery.

---

### Q23: Priority

**Question:** What task number should this be, and where does it fit in priority relative to current pending tasks (49-PyPI, 104-Python node, 107-Markdown workflow)?

**User Answer:** "Medium - after 107"

**Decision:** v0.7.0, after Markdown Workflow Format.

---

## Implementation Details

### CLI Command

```bash
# Auto-detect latest trace
pflow trace debug

# Specific execution ID
pflow trace debug exec-20260104-abc123

# Specific trace file
pflow trace debug ~/.pflow/debug/workflow-trace-my-workflow-20260104-143000.json

# Output to stdout instead of file
pflow trace debug --stdout
```

**Behavior:**
- Auto-detects most recent trace in `~/.pflow/debug/`
- Generates `workflow-debug-{timestamp}.md` alongside the JSON trace
- Returns path to debug file (or content if --stdout)

### MCP Tool

```python
async def get_debug_trace(
    trace_path: str | None = None,  # Path or execution_id, None = latest
) -> str:
    """Get smart debug output for a workflow trace.

    Returns focused markdown with:
    - Error classification and context
    - Structure of failed node's inputs/outputs
    - Drill-down commands for full data
    - Anomaly warnings (empty outputs, etc.)
    """
```

**Returns:** Markdown content directly (not just file path)

### Output Format Example

```markdown
# Workflow Debug: my-workflow

**Status:** FAILED at node `fetch-issues`
**Execution ID:** exec-20260104-143052-a1b2c3d4
**Duration:** 5.2s (failed at 3.1s)

---

## Error Summary

**Type:** Template Resolution Error
**Node:** `format-output` (llm)
**Message:** Template variable `${fetch-issues.result.messages}` not found

### Available Structure from `fetch-issues`

```yaml
result:
  issues: list[3]
    - id: int
    - title: str
    - body: str (~2000 chars)
    - labels: list
  total_count: int
```

**Suggested fix:** Change `${fetch-issues.result.messages}` to `${fetch-issues.result.issues}`

---

## Data Flow (Failed Node Context)

### Input to `format-output`

```diff
+ fetch-issues.result: {structure shown above}
+ fetch-issues.result.issues: list[3]
```

### Template Resolution Attempted

| Template | Status | Value/Error |
|----------|--------|-------------|
| `${fetch-issues.result.messages}` | FAILED | Key 'messages' not found |
| `${fetch-issues.result.total_count}` | OK | 3 |

---

## Anomalies Detected

- Node `filter-closed` returned empty list (0 items) - may cause downstream issues

---

## Drill-Down Commands

```bash
# Full output from fetch-issues
cat ~/.pflow/debug/workflow-trace-my-workflow-20260104-143052.json | jq '.nodes[] | select(.node_id == "fetch-issues") | .shared_after'

# Read specific field
pflow read-fields exec-20260104-143052-a1b2c3d4 fetch-issues.result.issues[0]
```

---

## Execution Timeline

| Node | Status | Duration | Notes |
|------|--------|----------|-------|
| fetch-issues | OK | 2.1s | 3 issues fetched |
| filter-closed | OK | 0.05s | **0 items returned** |
| format-output | FAILED | 0.9s | Template error |

---

*Generated by pflow trace debug. Full trace: ~/.pflow/debug/workflow-trace-my-workflow-20260104-143052.json*
```

### Error Type Classification (Rule-Based)

**Note:** Error types should be investigated further during implementation per user feedback.

| Error Type | Detection Pattern | Context to Include |
|------------|-------------------|-------------------|
| Template Error | `Template variable .* not found` | Structure of source node output, similar path suggestions |
| API Error | HTTP status 4xx/5xx, `"ok": false` | Response body structure, status code, endpoint |
| Validation Error | `ValidationError`, param format issues | Invalid params, expected format |
| Shell Error | Exit code != 0, stderr content | Command, exit code, stderr |
| LLM Error | Model/API errors | Prompt length, model, error message |
| Timeout | Duration exceeded threshold | Node duration, timeout setting |
| MCP Error | Server connection, tool not found | Server name, tool attempted |

### Anomaly Detection

Detect potential issues even when node status is "success":

| Anomaly | Detection | Warning Message |
|---------|-----------|-----------------|
| Empty list | `result == []` | "Returned empty list - may cause downstream issues" |
| Null value | `result == null` | "Returned null - check if expected" |
| Empty string | `result == ""` | "Returned empty string" |
| Truncated data | `len(result) == limit` | "Result may be truncated (exactly {limit} items)" |

### Progressive Disclosure Pattern

Following Task 89's structure-only approach:

1. **Summary first** - Error type, failed node, quick diagnosis
2. **Structure of data** - Template paths, not full values
3. **Drill-down commands** - jq queries and pflow commands for full data
4. **Minimal timeline** - Only execution order and status, not full details

### Output Locations

The debug output is:
1. **Saved to file** - `~/.pflow/debug/workflow-debug-{workflow}-{timestamp}.md`
2. **Returned in response** - CLI stdout, MCP tool return value

### Integration Points

**CLI Integration:**
- New command group: `pflow trace` (if not exists)
- Subcommand: `pflow trace debug`
- Uses existing trace file discovery logic

**MCP Integration:**
- New tool: `get_debug_trace` in `src/pflow/mcp_server/tools/`
- Returns markdown content directly
- Works with trace path, execution_id, or "latest"

**Existing Infrastructure to Reuse:**
- `WorkflowTraceCollector` - Trace data structure
- `format_node_output()` - Structure formatting from Task 89
- `ExecutionCache.retrieve()` - If caching debug output
- `TemplateResolver` - For suggested path fixes

### New Files

**Core:**
- `src/pflow/core/trace_analyzer.py` (~300 LOC)
  - `analyze_trace()` - Main entry point
  - `classify_error()` - Rule-based error classification
  - `extract_context()` - Select relevant trace sections
  - `detect_anomalies()` - Empty/null detection
  - `suggest_path_fix()` - Similar path matching

**CLI:**
- `src/pflow/cli/commands/trace.py` (~150 LOC)
  - `pflow trace debug` command
  - Auto-detect latest trace logic
  - File/stdout output handling

**MCP:**
- `src/pflow/mcp_server/tools/trace_tools.py` (~100 LOC)
  - `get_debug_trace` tool definition
  - Service layer integration

**Formatters:**
- `src/pflow/execution/formatters/trace_debug_formatter.py` (~200 LOC)
  - `format_debug_markdown()` - Main formatter
  - `format_error_section()` - Error-specific formatting
  - `format_structure_yaml()` - YAML block formatting
  - `format_drill_down_commands()` - jq/pflow commands

### Modified Files

- `src/pflow/cli/main_wrapper.py` - Add `trace` command group
- `src/pflow/mcp_server/tools/__init__.py` - Register trace_tools
- `docs/mcp-agent-instructions.md` - Document new tools
- `docs/mcp-sandbox-agent-instructions.md` - Document new tools
- `scripts/analyze-trace/README.md` - Add deprecation notice

## Future Enhancements (Document But Don't Implement)

### Iteration Diff Mode
```bash
# Compare with previous trace for same workflow
pflow trace debug --diff-previous

# Output includes:
# "Changed since last run:"
# - Node 'fetch-issues' params changed: url parameter updated
# - Node 'format-output' template fixed: messages → issues
```

### LLM-Assisted Smart Extraction
If rule-based extraction produces too much noise:
- Quick LLM call to analyze trace and select most relevant sections
- Token budget: <1000 tokens for analysis
- Cache analysis results for repeated queries

### Interactive Drill-Down
```bash
# Interactive mode with follow-up queries
pflow trace debug --interactive
> show full output from fetch-issues
> show llm prompt for format-output
```

## Test Strategy

### Unit Tests

**Smart Extraction:**
- `test_classify_template_error` - Correct classification and context
- `test_classify_api_error` - HTTP errors detected and parsed
- `test_classify_shell_error` - Exit codes and stderr captured
- `test_detect_empty_list_anomaly` - Anomaly flagged
- `test_detect_null_anomaly` - Null outputs flagged

**Output Formatting:**
- `test_markdown_structure` - Correct sections and formatting
- `test_yaml_blocks_valid` - Embedded YAML is parseable
- `test_drill_down_commands_valid` - jq commands are syntactically correct
- `test_structure_only_output` - Values not leaked, only paths

**Path Suggestions:**
- `test_suggest_similar_path` - "messages" → "issues" suggestion
- `test_suggest_case_correction` - "Messages" → "messages"
- `test_no_suggestion_when_no_match` - Graceful handling

### Integration Tests

**CLI:**
- `test_trace_debug_auto_detect` - Finds latest trace
- `test_trace_debug_by_execution_id` - Resolves execution ID to file
- `test_trace_debug_file_created` - Debug .md file saved
- `test_trace_debug_stdout` - --stdout returns content

**MCP:**
- `test_get_debug_trace_latest` - Works without arguments
- `test_get_debug_trace_by_path` - Accepts trace path
- `test_get_debug_trace_content` - Returns markdown directly

### Performance Tests

- `test_token_efficiency` - Debug output < 10% of full trace tokens
- `test_large_trace_handling` - 500KB+ trace processed in <1s

## Related Documentation

- Task 89: Structure-Only Mode - Pattern to follow for progressive disclosure
- Task 32: Unified Metrics and Tracing - Trace file format being consumed
- Task 72: MCP Server - MCP tool registration patterns
- `architecture/features/debugging.md` - References this task as planned enhancement
