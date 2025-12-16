# Agent-First Design: Debugging System Insights

> Research gathered 2025-12-12 to strengthen the "Agent-First Design" blog post

---

## Executive Summary

pflow's debugging infrastructure is a goldmine of agent-first design examples. The error messages, trace files, and validation system were all built with the assumption that **an AI agent will be the primary consumer**. This document captures verified findings that could strengthen the blog post.

**Key insight**: pflow doesn't just have "good error messages" - it has a **structured debugging API designed for machine consumption** that happens to also be readable by humans.

---

## Part 1: Rich Error Context (Task 71 Implementation)

### The Problem Traditional Tools Have

Most tools return errors like:
```
Error: Cannot read property 'messages' of undefined
```

An AI agent seeing this has to:
1. Guess what object was undefined
2. Guess what the correct property name might be
3. Search documentation or code to find alternatives
4. Try again (hoping it works)

### pflow's Agent-First Solution

When a workflow fails, pflow returns structured error data with everything an agent needs to self-correct:

```json
{
  "success": false,
  "errors": [{
    "source": "runtime",
    "category": "template_error",
    "message": "Node 'fetch' does not output 'msg'",
    "node_id": "process",
    "fixable": true,
    "available_fields": [
      "result",
      "result.messages",
      "result.messages[0]",
      "result.messages[0].text",
      "result.messages[0].user"
    ],
    "available_fields_total": 17,
    "available_fields_truncated": false
  }],
  "execution": {
    "duration_ms": 1234,
    "nodes_executed": 2,
    "steps": [
      {"node_id": "fetch", "status": "completed", "duration_ms": 800},
      {"node_id": "process", "status": "failed", "duration_ms": 434}
    ]
  },
  "checkpoint": {
    "completed_nodes": ["fetch"],
    "failed_node": "process"
  }
}
```

### What Makes This Agent-First

| Field | Purpose for Agent |
|-------|-------------------|
| `category` | Tells agent which repair strategy to use |
| `node_id` | Pinpoints exactly where to fix |
| `fixable` | Agent knows if auto-repair is possible |
| `available_fields` | Agent sees what DOES exist (self-correction data) |
| `execution.steps` | Agent understands the flow (what worked, what failed) |
| `checkpoint` | Agent can resume from last success |

### The Human Benefit (Accidental)

Humans reading this error can also immediately see:
- Which node failed
- What field was requested vs what exists
- The execution timeline
- Where to resume if retrying

**Quote for blog**: "We didn't design this for humans to read in a terminal. We designed it for Claude to parse and fix. But it turns out structured, actionable error data is exactly what frustrated humans want too."

---

## Part 2: "Did You Mean?" Suggestion System

### Implementation Details

**Location**: `src/pflow/runtime/template_validator.py` lines 349-383

**Algorithm**: Simple substring matching (not fuzzy/difflib)
- Case-insensitive comparison
- Ranks by match quality (longer substring = better)
- Returns top 3 suggestions
- Example: `"msg"` matches `"messages"` via substring

### What Agents See

When an agent references a non-existent field, the error is structured for self-correction:

**CLI Output** (human-readable):
```
Node 'fetch' does not output 'msg'

Available outputs from 'fetch':
  ✓ ${fetch.result} (dict)
  ✓ ${fetch.result.messages} (array)
  ✓ ${fetch.result.messages[0]} (dict)
  ✓ ${fetch.result.messages[0].text} (string)
  ... and 13 more outputs

Did you mean: ${fetch.result.messages}?

Common fix: Change ${fetch.msg} to ${fetch.result.messages}
```

**JSON Output** (machine-readable):
```json
{
  "available_fields": ["result", "result.messages", "result.messages[0].text"],
  "suggestions": ["result.messages"],
  "requested_field": "msg"
}
```

### Design Decisions

| Decision | Rationale |
|----------|-----------|
| Show up to 20 fields | Cognitive load balance - enough to find the right one |
| Top 3 suggestions | Research shows >3 options reduces decision quality |
| Include types | Agent knows if it's getting a dict vs string |
| Recursive flattening | Shows nested paths like `result.data[0].id` |

### Blog Angle

This is a perfect example of "agent-first = human-friendly":
- Agent gets structured data it can parse and act on
- Human gets a readable error with suggestions
- Same underlying system serves both audiences

---

## Part 3: Workflow Traces as Agent Debugging API

### The Design

Trace files are **JSON** (not log files) because they're designed for machine consumption:

**Location**: `~/.pflow/debug/workflow-trace-{name}-{timestamp}.json`

**Format Version**: 1.2.0

```json
{
  "format_version": "1.2.0",
  "execution_id": "uuid",
  "workflow_name": "my-workflow",
  "start_time": "2025-12-12T10:30:00Z",
  "end_time": "2025-12-12T10:30:05Z",
  "duration_ms": 5000,
  "final_status": "failed",
  "nodes_executed": 3,
  "nodes_failed": 1,
  "nodes": [
    {
      "node_id": "fetch-data",
      "node_type": "http",
      "duration_ms": 1200,
      "success": true,
      "shared_before": {"input": "..."},
      "shared_after": {"fetch-data": {"result": {...}}},
      "mutations": {
        "added": ["fetch-data"],
        "modified": [],
        "removed": []
      }
    },
    {
      "node_id": "process",
      "node_type": "llm",
      "duration_ms": 3800,
      "success": false,
      "error": "Template ${fetch-data.wrong_field} not found",
      "llm_call": {
        "model": "claude-sonnet-4-5",
        "prompt_tokens": 1500,
        "completion_tokens": 0,
        "cost_usd": 0.0045
      }
    }
  ],
  "llm_summary": {
    "total_calls": 1,
    "total_tokens": 1500,
    "total_cost_usd": 0.0045
  }
}
```

### Agent-First Design Elements

| Element | Why It's Agent-First |
|---------|---------------------|
| JSON format | Machines parse JSON; logs require regex |
| `shared_before`/`shared_after` | Agent sees exact data state at each step |
| `mutations` | Agent knows what changed without diffing |
| Per-node `llm_call` | Agent can analyze token usage and costs |
| Versioned format | Agents can handle schema evolution |

### How Agents Can Use Traces

```bash
# Find the failed node
cat trace.json | jq '.nodes[] | select(.success == false)'

# See what data was available at failure point
cat trace.json | jq '.nodes[] | select(.node_id == "process") | .shared_before'

# Get execution timeline
cat trace.json | jq '.nodes[] | {id: .node_id, ms: .duration_ms, ok: .success}'

# Calculate total LLM cost
cat trace.json | jq '.llm_summary.total_cost_usd'
```

### The Gap (Honest Assessment)

**What we do well**: Trace files are perfectly structured for agent consumption.

**What we don't do well**: Agents don't know to use them.

- Every response includes `trace_path`
- But tool docstrings don't explain what's inside
- Debugging guidance is buried in a 66KB instruction document
- Agents often ignore the trace and just retry

**Quote for blog**: "We built the perfect debugging API for agents - JSON traces with full execution history. Then we forgot to tell agents it exists. Agent-first design is a practice, not a checkbox."

---

## Part 4: Validation-Only Mode

### The Feature

```bash
pflow --validate-only workflow.json
```

**Exit codes**: 0 = valid, 1 = invalid

### What Gets Validated (Without Executing)

| Check | What It Catches |
|-------|-----------------|
| Schema compliance | Missing required fields, wrong types |
| Data flow | Circular dependencies, forward references |
| Template paths | `${node.field}` references non-existent outputs |
| Node types | Unknown node types, missing MCP tools |

### What's NOT Validated

- Runtime values (actual API responses)
- Credentials (API keys work)
- External resources (files exist, URLs respond)

### Agent-First Design

This exists because agents need **fast feedback**:
- Generate workflow → validate → fix → validate → execute
- Without `--validate-only`, every check requires full execution
- Validation is ~100ms vs execution potentially minutes

### Human Benefit

Humans can also use this to check workflows before running:
- CI/CD pipelines can validate without side effects
- Pre-commit hooks can catch template errors
- Documentation examples can be verified

---

## Part 5: Error Categories and Repair Strategy

### The Classification System

pflow categorizes errors to help agents choose repair strategies:

| Category | Meaning | Agent Strategy |
|----------|---------|----------------|
| `template_error` | Wrong field reference | Check `available_fields`, fix template |
| `api_validation` | API rejected input | Check error message, fix parameters |
| `execution_failure` | Runtime error | Check trace, understand data flow |
| `resource_error` | 404, 401, etc. | Cannot auto-fix, report to user |

### Non-Repairable Detection

pflow automatically detects errors that agents CANNOT fix:

**Patterns checked** (73 validation + 20 resource patterns):
- HTTP status codes: 401, 403, 404, 429
- API responses: `{"ok": false}` (Slack), `{"errors": [...]}` (GraphQL)
- Resource errors: "not found", "forbidden", "rate limit"

When detected, the error includes:
```json
{
  "fixable": false,
  "category": "resource_error"
}
```

**Agent behavior**: Don't attempt repair, report to user.

### Blog Angle

This is sophisticated agent-first design:
- Errors aren't just messages, they're **instructions**
- The `fixable` flag tells agents when to give up
- Categories map to repair strategies
- Non-repairable detection prevents wasted LLM calls

---

## Part 6: Execution State Tracking

### Per-Node Visibility

Every workflow execution tracks detailed state:

```json
{
  "execution": {
    "steps": [
      {
        "node_id": "fetch",
        "status": "completed",
        "duration_ms": 150,
        "cached": true,
        "repaired": false
      },
      {
        "node_id": "process",
        "status": "failed",
        "duration_ms": 734,
        "cached": false,
        "repaired": false
      },
      {
        "node_id": "output",
        "status": "not_executed",
        "duration_ms": 0,
        "cached": false,
        "repaired": false
      }
    ]
  }
}
```

### What Agents Learn

| Field | Agent Use |
|-------|-----------|
| `status` | Know exactly where failure occurred |
| `cached` | Understand if data is fresh or reused |
| `repaired` | Know if auto-repair was attempted |
| `duration_ms` | Identify slow nodes for optimization |

### Checkpoint for Resume

```json
{
  "checkpoint": {
    "completed_nodes": ["fetch"],
    "failed_node": "process",
    "node_hashes": {
      "fetch": "md5_of_config"
    }
  }
}
```

Agent can resume from checkpoint instead of re-running everything.

---

## Part 7: The Three-Part Error Format

### Structure

All user-facing errors follow WHAT-WHY-HOW:

```
Error: {title}                    # WHAT went wrong

{explanation}                     # WHY it failed

To fix this:                      # HOW to fix it
  1. {suggestion 1}
  2. {suggestion 2}
  3. {suggestion 3}

Run with --verbose for technical details.
```

### Example: MCP Error

```
Error: MCP tools not available

The workflow tried to use MCP tools that aren't registered.
This usually happens when MCP servers haven't been synced.

To fix this:
  1. Check your MCP servers: pflow mcp list
  2. Sync MCP tools: pflow mcp sync --all
  3. Verify tools are registered: pflow registry list | grep mcp
  4. Run your workflow again

Run with --verbose for technical details.
```

### Why This Is Agent-First

Traditional errors: "MCP tool not found"
- Agent has to search docs for fix
- Multiple possible causes, no guidance

pflow errors: Complete diagnosis + prescription
- Agent can try each suggestion in order
- Specific commands to run
- Clear success criteria

---

## Part 8: Trace File Configuration

### Environment Variables

```bash
PFLOW_TRACE_PROMPT_MAX=50000      # Max LLM prompt length in trace (default: 50K)
PFLOW_TRACE_RESPONSE_MAX=20000    # Max LLM response length (default: 20K)
PFLOW_TRACE_STORE_MAX=10000       # Max shared store value (default: 10K)
PFLOW_TRACE_DICT_MAX=50000        # Max dict size (default: 50K)
PFLOW_TRACE_LLM_CALLS_MAX=100     # Max LLM calls tracked (default: 100)
```

### Design Rationale

These limits exist because:
1. **Traces are for debugging, not archival** - truncation is acceptable
2. **Large traces slow down agents** - reading 100MB JSON defeats the purpose
3. **Security** - don't accidentally log sensitive data in full
4. **Disk space** - traces accumulate (no auto-cleanup)

### Truncation Behavior

When limits are exceeded:
```json
{
  "llm_prompt": "First 50000 chars...",
  "llm_prompt_truncated": true,
  "llm_prompt_original_length": 75000
}
```

Agent knows data was truncated and can request full version if needed.

---

## Part 9: What's Missing (Gaps to Address)

### Gap 1: Agents Don't Know About Traces

**Evidence**:
- `pflow instructions usage` doesn't mention trace files
- Tool docstrings just say "trace saved to X" without explaining value
- Debugging guidance buried in Step 10 of 66KB instruction doc

**Impact**: Agents ignore the most powerful debugging tool.

**Potential fix**: Add to error responses:
```json
{
  "debug_hint": "Inspect trace file for full execution history",
  "trace_path": "~/.pflow/debug/workflow-trace-..."
}
```

### Gap 2: No Trace Analysis Tool

**Current state**: Agents must use `cat | jq` to analyze traces.

**Potential tool**: `workflow_debug(trace_path)` that returns:
```json
{
  "summary": "Workflow failed at node 'process' after 2 successful nodes",
  "failed_node": {
    "id": "process",
    "error": "...",
    "input_data": {...},
    "suggestion": "Field 'msg' not found, try 'messages'"
  },
  "timeline": [...]
}
```

### Gap 3: No Auto-Cleanup

**Evidence**: `~/.pflow/debug/` accumulates indefinitely.

**Impact**: Disk space issues over time; old traces clutter analysis.

**Potential fix**: TTL-based cleanup or `pflow debug clean --older-than 7d`.

---

## Part 10: Quotes for the Blog

### On Error Design

> "When an AI agent hits an error, it can't squint at the screen and think 'hmm, maybe it's a type issue.' It needs the error message to tell it exactly what went wrong, what data IS available, and how to fix it. We built that - and humans love it too."

### On Trace Files

> "We made trace files JSON because agents need to parse them. We included `shared_before` and `shared_after` because agents need to see data flow. We added `mutations` because agents shouldn't have to diff. Then we realized: this is exactly what humans want when debugging too."

### On the Gap

> "We built the perfect debugging API - structured errors, JSON traces, execution checkpoints. Then we forgot to document it for agents. Agent-first design isn't a feature you ship; it's a discipline you practice."

### On Suggestions

> "Our 'Did you mean?' system uses simple substring matching. Not fuzzy matching, not ML, not embeddings. Just: does 'msg' appear in 'messages'? It's embarrassingly simple - and it works because agents don't need clever, they need correct."

### On Fixability

> "Every error in pflow has a `fixable` boolean. When an API returns 404, we set `fixable: false`. The agent knows: don't waste tokens trying to fix this, tell the human. That one boolean saves countless failed repair attempts."

---

## Part 11: Comparison with Other Tools

### Traditional Workflow Tools (n8n, Zapier, Make)

| Aspect | Traditional | pflow |
|--------|-------------|-------|
| Error format | Human-readable string | Structured JSON with metadata |
| Available fields | Not shown | Listed with types |
| Suggestions | Generic | Specific ("Did you mean X?") |
| Execution trace | Log files | JSON with per-node state |
| Resume capability | Start over | Checkpoint-based resume |

### Why pflow Is Different

Traditional tools assume a human will:
1. Read the error
2. Open documentation
3. Figure out the fix
4. Manually retry

pflow assumes an agent will:
1. Parse the structured error
2. Check `available_fields`
3. Apply the fix programmatically
4. Resume from checkpoint

---

## Part 12: Implementation References

### Error Formatting
- `src/pflow/core/user_errors.py` - Three-part format (WHAT-WHY-HOW)
- `src/pflow/execution/formatters/error_formatter.py` - JSON error building

### Rich Error Context
- `src/pflow/execution/executor_service.py:270-346` - Context extraction
- Task 71 implementation added `available_fields`, `status_code`, etc.

### Template Suggestions
- `src/pflow/runtime/template_validator.py:349-383` - Substring matching
- `src/pflow/core/suggestion_utils.py` - Shared suggestion logic

### Trace Files
- `src/pflow/runtime/workflow_trace.py` - 610 lines, full implementation
- Format version 1.2.0 with tri-state status

### Validation
- `src/pflow/core/workflow_validator.py` - Unified validation pipeline
- `src/pflow/runtime/template_validator.py` - Template path validation

---

## Summary: What This Adds to the Blog

The debugging research provides **3 strong additions** to the agent-first design narrative:

### 1. Richer Error Example

The JSON parsing error in Part 1 is good, but the template error with `available_fields` is **much stronger**:
- Shows self-correction data (not just diagnosis)
- Includes execution state (what worked, what failed)
- Has checkpoint for resume

### 2. New Section: Debugging as API

The trace file system is a perfect example of agent-first design:
- JSON format (not logs)
- Per-node state snapshots
- Structured for machine parsing
- Human-readable as side effect

### 3. Honest Gap Acknowledgment

The finding that agents don't use traces adds authenticity:
- We built great tools
- We forgot to teach agents about them
- Agent-first design is ongoing practice

---

*Research compiled: 2025-12-12*
*Sources: 6 parallel pflow-codebase-searcher agents + verified-error-handling-features.md*
