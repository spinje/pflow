# Task 108: Smart Trace Debug Output for Agent Iteration

## ID
108

## Title
Smart Trace Debug Output for Agent Iteration

## Description
Implement an intelligent trace debugging system that generates focused, token-efficient markdown output from workflow traces. The system analyzes trace data to extract only relevant debugging information based on what went wrong, enabling AI agents to quickly diagnose and fix failing workflows during iteration.

This replaces the current workflow where agents must parse raw JSON traces or use external scripts.

## Status
not started

## Dependencies
- Task 89: Structure-Only Mode and Selective Data Retrieval - Progressive disclosure pattern to reuse
- Task 32: Unified Metrics and Tracing System - Trace files this task consumes
- Task 72: MCP Server for pflow - MCP tool integration point

## Priority
medium (after Task 107, v0.7.0)

## Context

### The Problem

When AI agents iterate on workflow.json files, debugging failures is painful:

1. **Raw JSON traces are huge** - 500KB+ files with verbose shared store snapshots
2. **Irrelevant noise** - Successful nodes, unchanged data, LLM call metadata
3. **No smart extraction** - Agents must parse everything to find the error
4. **Two-step process** - Generate trace → run external script → open in editor
5. **Sandbox agents blocked** - Cannot access trace files, documented as "temporary solution"

### The Solution

Smart debug output that:
1. **Analyzes what went wrong** - Rule-based classification of error types
2. **Extracts only relevant context** - Failed node + its inputs, structure of outputs
3. **Uses progressive disclosure** - Show structure, include drill-down commands
4. **Detects anomalies** - Flag empty/null outputs even on "success"
5. **Works everywhere** - CLI command + MCP tool + inline in responses

## Scope

### In Scope

| Component | Description |
|-----------|-------------|
| CLI command | `pflow trace debug` with auto-detect latest or explicit execution_id |
| MCP tool | `get_debug_trace(trace_path_or_id)` for agent access |
| Smart extraction | Rule-based error classification and context selection |
| Markdown output | Focused debug file with YAML blocks for structured data |
| Anomaly detection | Flag empty/null outputs even on successful nodes |
| Drill-down commands | Include jq queries and pflow commands for full data |
| Agent instructions | Update mcp-agent-instructions.md and sandbox variant |
| Deprecate scripts | Mark `scripts/analyze-trace/` as deprecated |

### Out of Scope

| Feature | Reason |
|---------|--------|
| Iteration diff (compare with previous trace) | Future enhancement - documented in spec |
| LLM-based smart extraction | Start with rules, add later if needed |
| Planner trace analysis | Focus on workflow traces for agent iteration |
| Real-time trace streaming | Post-execution analysis only |

## Key Design Decisions

1. **Rule-based extraction first** - Pattern match error types, LLM fallback only if needed later
2. **Markdown with YAML blocks** - Human-readable with structured data sections
3. **Structure-only for outputs** - Show template paths, not full data (reuse Task 89 pattern)
4. **Diff-style mutations** - Show +/- for what changed, not full before/after
5. **Include drill-down commands** - Ready-to-use jq/pflow commands for full data
6. **Both file and response** - Save .md file AND return content in response
7. **Deprecate analyze.py** - New tool covers all use cases

## Success Criteria

1. **Token Efficiency**: Debug output is 10x smaller than full trace (target: 5-10KB vs 50-500KB)
2. **Agent Iteration Speed**: Agents fix errors with fewer round-trips (qualitative)
3. **Error Resolution Rate**: Debug output contains actionable fix in 80%+ of template/API errors
4. **Complete Coverage**: Works for all error types (template, API, validation, shell, LLM)
5. **MCP Parity**: CLI and MCP tool produce identical output format
6. **Docs Updated**: Agent instructions reference new tools
7. **Scripts Deprecated**: analyze.py marked deprecated with pointer to new tool

## Implementation References

For detailed implementation guidance, see:
- `starting-context/task-108-spec.md` - Full Q&A from requirements gathering, output format examples, error classification tables, file structure
- `starting-context/braindump-task-creation.md` - Tacit knowledge and context from requirements session

## Related Documentation

- Task 89: Structure-Only Mode - Pattern to follow for progressive disclosure
- Task 32: Unified Metrics and Tracing - Trace file format being consumed
- Task 72: MCP Server - MCP tool registration patterns
- `architecture/features/debugging.md` - References this task as planned enhancement
