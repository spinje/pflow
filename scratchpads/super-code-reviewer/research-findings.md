# Super Code Reviewer Workflow - Research Findings

## Executive Summary

This document captures comprehensive research on implementing a "Super Code Reviewer and Fixer" workflow using pflow's Claude Code node and related infrastructure.

**Target Workflow:**
1. Create GitHub pull request (optionally with Claude Code session context)
2. Use Claude Code agent to review code with predefined prompt
3. Post review as PR comment via gh CLI
4. Send review to implementer agent that:
   - Critically assesses issues
   - Creates fix plan
   - Spawns parallel subagents to fix issues
   - Reviews subagent changes
   - Commits and outputs report
5. Update PR with change report comment
6. Send Slack notification with PR link

---

## Component Analysis

### 1. Claude Code Node

**Status: COMPLETE and PRODUCTION-READY** (with recent enhancements)

**Location:** `src/pflow/nodes/claude/claude_code.py`

**Key Capabilities:**
- Full agentic development with all tools (Read/Write/Edit/Bash/Task/Glob/Grep/etc.)
- Schema-driven structured outputs (JSON)
- Session ID capture and exposure
- **NEW: Session resumption via `resume` parameter**
- **NEW: Configurable timeout (30-3600s)**
- **NEW: All tools available by default (including Task for subagents)**
- Cost tracking and metrics
- Comprehensive error handling

**Interface:**
```python
# Inputs (shared store)
shared["task"]: str        # Required - Development task (max 10,000 chars)
shared["context"]: str|dict # Optional - Additional context
shared["output_schema"]: dict # Optional - JSON schema for structured output

# Parameters
working_directory: str     # Default: os.getcwd()
model: str                 # Default: claude-sonnet-4-20250514
allowed_tools: list        # Default: None (all tools including Task for subagents)
max_turns: int             # Default: 50, range: 1-100
max_thinking_tokens: int   # Default: 8000
timeout: int               # Default: 300, range: 30-3600
system_prompt: str         # Optional custom instructions
resume: str                # Optional - Session ID to resume

# Outputs
shared["result"]: str|dict # Response text OR parsed schema dict
shared["_claude_metadata"]: dict  # Execution metadata (includes session_id)
shared["llm_usage"]: dict  # Standardized usage metrics
```

**Session Resumption:**
```json
{
  "id": "continue_work",
  "type": "claude-code",
  "params": {
    "task": "Continue fixing remaining issues",
    "resume": "${previous_node._claude_metadata.session_id}"
  }
}
```

---

### 2. Subagent Capabilities (Built into Claude Code)

**Status: AVAILABLE via Task tool**

Claude Code has a built-in `Task` tool that spawns subagents:
- **Parallel execution:** Up to 10 concurrent subagents (batched if more)
- **Isolated context:** Each subagent has its own context window
- **Results aggregation:** Orchestrator receives summarized results
- **Limitation:** Subagents cannot spawn further subagents (no infinite nesting)

**Key Insight:** The parallelism happens *inside* Claude Code, not at the pflow level. One Claude Code node can orchestrate the entire review → fix → commit cycle.

---

### 3. GitHub Integration

**Status: PARTIAL - 4 nodes exist, comment capability MISSING**

**Existing Nodes:**
| Node | Purpose |
|------|---------|
| `github-get-issue` | Retrieve issue details |
| `github-list-issues` | List repository issues |
| `github-create-pr` | Create new pull requests |
| `github-list-prs` | List pull requests |

**MISSING (Required for workflow):**
- `github-add-comment` - Post comments to PRs/issues

**Implementation:** Use `gh issue comment <number> --body "<text>"` (works for both issues and PRs)

---

### 4. Slack Integration

**Status: AVAILABLE via HTTP webhooks or MCP**

**Option A: HTTP Node with Webhooks (Simple)**
```json
{
  "id": "notify_slack",
  "type": "http",
  "params": {
    "url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
    "method": "POST",
    "body": {"text": "PR Review Complete: ${pr_url}"}
  }
}
```

**Option B: MCP Integration (Rich features)**
- 9 Slack tools available via Composio MCP server
- Supports reactions, user lookup, channel management

---

### 5. Nested Workflow Execution

**Status: COMPLETE and PRODUCTION-READY**

Supports calling workflows by name, path, or inline definition with full parameter/output mapping.

---

## Gap Analysis

| Workflow Step | Current State | Gap | Effort |
|--------------|---------------|-----|--------|
| 1. Create PR | `github-create-pr` exists | None | Ready |
| 2. Claude Code review | Node complete with Task tool | None | Ready |
| 3. Post PR comment | Node missing | Implement `github-add-comment` | Medium |
| 4. Parallel subagents | Available via Task tool | None | Ready |
| 5. Update PR comment | Same as step 3 | Same gap | Same |
| 6. Slack notification | HTTP webhook works | None | Ready |

---

## Recommended Implementation

### Phase 1: MVP
1. Implement `github-add-comment` node
2. Build workflow with single Claude Code orchestrator

### Example Workflow:
```json
{
  "nodes": [
    {"id": "create_pr", "type": "github-create-pr", ...},
    {
      "id": "review_and_fix",
      "type": "claude-code",
      "params": {
        "task": "Review PR, spawn Task subagents to fix issues, commit changes",
        "timeout": 600,
        "max_turns": 100
      }
    },
    {"id": "post_review", "type": "github-add-comment", ...},
    {"id": "notify_slack", "type": "http", ...}
  ]
}
```

---

## Future Enhancement: pflow_tools Parameter

**Planned Feature (Task 99):** Expose pflow nodes as MCP tools to Claude Code

**New Parameter:**
```python
pflow_tools: list[str]  # e.g., ["github-create-pr", "http", "llm"]
```

**Behavior:**
- Creates minimal SDK MCP server with ONE tool: `pflow_run`
- Injects node metadata into system prompt
- Claude Code can call pflow nodes directly without pre-wiring

**Implementation Approach:**
- Create minimal FastMCP server wrapping `ExecutionService.run_registry_node()`
- Validate node_type against allowed list
- Pass server via `mcp_servers` to Claude Code SDK

---

## References

- Claude Code node: `src/pflow/nodes/claude/claude_code.py`
- GitHub nodes: `src/pflow/nodes/github/`
- MCP server: `src/pflow/mcp_server/`
- ExecutionService: `src/pflow/mcp_server/services/execution_service.py`
