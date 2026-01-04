# Braindump: Task 108 Creation - Smart Trace Debug Output

## Where I Am

Task specification is **complete and committed**. No implementation has started. This was a requirements-gathering conversation where I interviewed the user to understand what they want. The task-108.md file captures the formal requirements, but this braindump captures the reasoning and context behind those decisions.

## User's Mental Model

The user thinks about this problem as **"making traces useful for agents iterating on workflow.json files"**. Key framing:

1. **"Smart" is the operative word** - Not a generic trace viewer, but intelligent extraction based on what went wrong. The user explicitly said: "we should create a 'smart' markdown file... that contains only the relevant info, we decide this smartly based on what went wrong"

2. **Progressive disclosure is core** - The user pointed me to Task 89 (structure-only mode) as the pattern to follow. Their mental model is: show structure first, let agents drill deeper with `read-fields` or jq commands. They said: "structure only output so llm can dig deeper if they want (minimize tokens and allow for progressive disclosure)"

3. **This is for debugging during iteration** - Not for prompt engineering (that's what analyze.py was for). Not for planner traces. Specifically: agents building workflows who hit errors and need to fix them fast.

4. **Token efficiency matters** - The user explicitly cares about both "agent iteration speed" AND "token efficiency (10x reduction)". These are the two success metrics.

## Key Insights

### The Structure-Only Pattern (Task 89) Is Central

The user kept steering me toward Task 89's approach. I researched it thoroughly:
- `registry run` has three output modes: `smart`, `structure`, `full`
- `read-fields` allows selective retrieval by field path
- This pattern achieves 600x token reduction for large API outputs

**The trace debug output should mirror this pattern**: show structure/summary, include commands to drill deeper, don't dump full data.

### Anomaly Detection Was Important to Them

When I asked about "unexpected output" (empty list, null) from successful nodes, the user chose "Yes, detect anomalies" immediately. This suggests they've hit this bug pattern before - node succeeds but produces empty data, causing downstream failures that are hard to diagnose.

### Deprecating analyze.py Is Intentional

The user chose to deprecate the existing `scripts/analyze-trace/analyze.py`. This means Task 108 needs to cover ALL trace analysis use cases, not just debugging. However, the user also said "we dont have to care about planner trace" - so the scope is workflow traces only.

### The User Likes Embedded Commands

When I asked about drill-down, they chose "Yes, include commands" and specifically mentioned "we can consider showing bash commands with jq to read full trace fields". They want the agent to have copy-paste-ready commands.

## Assumptions & Uncertainties

**ASSUMPTION**: The user wants a single markdown file, not multiple files. They explicitly chose "single file with sections" over "two files" or "links between files".

**ASSUMPTION**: Rule-based classification will be sufficient to start. The user said "we start with rule-based and if the file gets too overwhelming for llms... we consider using llm". This is a "start simple" approach.

**UNCLEAR**: The exact error types to classify. I listed template/API/validation/shell/LLM/timeout/MCP errors in the spec, but the user said "this has to be investigated more later". Don't treat my list as final.

**UNCLEAR**: How the iteration diff feature should work in the future. The user said it "sounds interesting but it can be a future improvement, but document it!" - so it's documented but the details are unspecified.

**NEEDS VERIFICATION**: Whether the existing trace format captures enough data for the "smart extraction" to work. The trace files have `shared_before`/`shared_after` and `template_resolutions`, but I didn't verify these are always populated correctly.

## Unexplored Territory

**UNEXPLORED**: How does this interact with Task 106 (Automatic Workflow Iteration Cache)? Task 106 caches node outputs during iteration. If an agent is using Task 106's cache and a workflow fails, does the trace still capture enough info for debugging?

**UNEXPLORED**: Binary data handling in the debug output. Traces already redact binary as `<binary data: N bytes>`. Should the markdown format show anything different?

**UNEXPLORED**: What happens with very long error chains? If node 5 fails because node 4 produced empty data because node 3 got a 404 because node 2 had the wrong URL... how deep does the "smart" analysis go?

**CONSIDER**: The MCP tool `get_debug_trace` returns markdown directly. This could be large. Should there be a `--summary-only` mode that returns just the error and suggestion?

**CONSIDER**: Trace file cleanup. The user didn't mention this, but if we're now generating both `.json` and `.md` files per execution, disk usage will grow faster.

**MIGHT MATTER**: The sandbox agent instructions mention "temporary solution until we add get trace tool". Task 108's MCP tool (`get_debug_trace`) IS that tool. Make sure the sandbox instructions get updated to remove the "temporary" language.

## What I'd Tell Myself

1. **Don't overthink the error classification**. Start with obvious patterns (template not found, HTTP 4xx/5xx, exit code != 0). The user wants simple rules first.

2. **The output format example in the spec is illustrative, not prescriptive**. I wrote a detailed example but the user didn't review it line-by-line. Iterate on the format during implementation.

3. **The structure-only pattern from Task 89 is the key insight**. Read that task's implementation thoroughly before starting. The formatter infrastructure is already there.

4. **"Progressive disclosure" means: summary → structure → commands to get full data**. Don't dump everything. Let the agent choose what to fetch.

5. **Test with real failing workflows**. The user has been iterating on pflow workflows, so there should be trace files in `~/.pflow/debug/` to test against.

## Open Threads

### The Missing Tasks Discovery

During this conversation, I discovered that Tasks 13, 42, and 48 are missing from CLAUDE.md's task list:
- **Task 13**: Only has research folder, likely deprecated
- **Task 42**: "Claude Code Agentic Node" - high priority, NOT STARTED, should be tracked
- **Task 48**: "Implement MCP Server for pflow" - superseded by Task 72

The user didn't ask me to fix this, but it should probably be addressed. Task 42 in particular looks like a real missing task.

### analyze.py Deprecation

The spec says to "mark analyze.py as deprecated" but I didn't specify how. Probably just a note in the README and maybe a warning if someone tries to run it. Not a high priority since it's a dev script.

### Agent Instructions Update

The spec includes updating `mcp-agent-instructions.md` and `mcp-sandbox-agent-instructions.md`. The sandbox instructions specifically have a "temporary solution" note that needs to be removed when Task 108 ships.

## Research Findings (From Subagent Investigation)

### Current Trace File Structure

Workflow traces (format version `1.2.0`) contain:
- `execution_id`, `workflow_name`, `start_time`, `end_time`, `duration_ms`
- `final_status`: tri-state (`success`/`degraded`/`failed`)
- `nodes`: array of node execution events with:
  - `node_id`, `node_type`, `duration_ms`, `success`
  - `shared_before`, `shared_after` (filtered/truncated)
  - `mutations`: `{added: [], removed: [], modified: []}`
  - `llm_call`, `llm_prompt`, `llm_response` (if LLM node)
  - `template_resolutions` (if templates used)
- `llm_summary`: `{total_calls, total_tokens, models_used}`

### Task 89 Structure-Only Pattern (Key Reference)

Three output modes controlled by `settings.json` → `registry.output_mode`:
- **`smart`** (default): Template paths WITH truncated values (>200 chars truncated)
- **`structure`**: Template paths ONLY (no values)
- **`full`**: Template paths WITH complete values

Smart filtering kicks in at **25-30 fields** - uses LLM to select most relevant fields. This is in `src/pflow/core/smart_filter.py`.

### MCP Server Gap

Currently **no MCP tools for trace access**. The sandbox agent instructions explicitly say:
> "(this is a temporary solution until we add get trace tool to pflow mcp server)"

Task 108's `get_debug_trace` tool fills this gap. The commented-out import `# from . import trace_tools` in `tools/__init__.py` shows this was planned.

### Trace File Locations

- Workflow traces: `~/.pflow/debug/workflow-trace-{name}-{YYYYMMDD-HHMMSS}.json`
- Planner traces: `~/.pflow/debug/planner-trace-{YYYYMMDD-HHMMSS}.json` (out of scope)
- New debug output: `~/.pflow/debug/workflow-debug-{name}-{timestamp}.md`

### Configurable Truncation Limits (Environment Variables)

```bash
PFLOW_TRACE_PROMPT_MAX=50000      # Prompt max length
PFLOW_TRACE_RESPONSE_MAX=20000    # Response max length
PFLOW_TRACE_STORE_MAX=10000       # Store value max
PFLOW_TRACE_DICT_MAX=50000        # Dict max size
PFLOW_TRACE_LLM_CALLS_MAX=100     # Max LLM calls tracked
```

## Relevant Files & References

**Task 108 Spec**: `.taskmaster/tasks/task_108/starting-context/task-108-spec.md` - full Q&A and implementation details

**Key files to study before implementation**:
- `src/pflow/runtime/workflow_trace.py` - Current trace format, WorkflowTraceCollector class
- `src/pflow/core/execution_cache.py` - ExecutionCache pattern from Task 89
- `src/pflow/execution/formatters/node_output_formatter.py` - Structure formatting, three output modes
- `src/pflow/cli/read_fields.py` - CLI for selective field retrieval
- `scripts/analyze-trace/analyze.py` - What we're deprecating (understand its features)

**Agent instructions to update**:
- `docs/mcp-agent-instructions.md`
- `docs/mcp-sandbox-agent-instructions.md`

**Architecture doc updated**:
- `architecture/features/debugging.md` - Now references Task 108

## For the Next Agent

**Start by**: Reading the task-108.md spec thoroughly. It has detailed output format examples and all the user's decisions.

**Then**: Study Task 89's implementation, especially `node_output_formatter.py`. The pattern is: structure → values (truncated) → drill-down commands.

**Don't bother with**: Planner traces. The user explicitly said this is for workflow traces during agent iteration.

**The user cares most about**:
1. Token efficiency (10x smaller than raw trace)
2. Agents fixing errors faster (fewer round-trips)
3. Progressive disclosure (structure first, details on demand)

**Key insight**: The "smart" part is about selecting WHAT to show based on error type, not about using an LLM. Rule-based classification first.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
