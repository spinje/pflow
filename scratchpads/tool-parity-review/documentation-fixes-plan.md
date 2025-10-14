# Documentation Fixes Plan

**Generated:** 2025-10-12
**Source:** cli-and-agent-instructions-review.md
**Target:** AGENT_INSTRUCTIONS.md (2,328 lines)

## Executive Summary

The agent instructions are comprehensive and well-structured but contain **5 critical ambiguities** and **3 inconsistencies** that could confuse AI agents. This document outlines the fixes needed, organized by priority and impact.

---

## 🔴 Priority 1: Critical Ambiguities (Must Fix)

### 1. Settings vs Environment Variables Confusion ⭐⭐⭐⭐⭐

**Location:** Lines 904-958 (Authentication & Credentials section)

**Issue:** Conflates three distinct concepts without clear boundaries:
- "Settings" (file at `~/.pflow/settings.json`)
- "Environment variables" (actual shell env vars)
- "env" (a section inside settings.json)

**Current Problems:**
- `set-env` command name implies it sets shell environment variables, but it writes to settings.json
- "ENV" in precedence order refers to shell vars, not settings.json "env" section
- No explanation of when to use which approach
- Agents don't know where to look for credentials

**Proposed Fix:**

Add new subsection "Three Storage Layers" at line 904:

```markdown
### Three Storage Layers

**1. Settings File** (`~/.pflow/settings.json`)
```json
{
  "env": {
    "ANTHROPIC_API_KEY": "sk-ant-..."  ← Stored in file
  }
}
```
- **Managed by:** `pflow settings set-env KEY value`
- **Purpose:** Persistent storage for secrets
- **Scope:** Available to all pflow commands

**2. Shell Environment Variables**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."  ← In shell session
```
- **Managed by:** System shell commands (`export`, `.bashrc`, `.zshrc`)
- **Purpose:** Override settings file without modifying it
- **Scope:** Current shell session only

**3. CLI Arguments**
```bash
pflow workflow api_token="sk-ant-..."  ← Direct parameter
```
- **Purpose:** One-time use, highest precedence
- **Scope:** Single command invocation

### Resolution Order (highest to lowest)

1. **CLI arguments** - `pflow workflow param=value`
2. **Shell env vars** - `export PFLOW_VAR=value`
3. **Settings file** - `~/.pflow/settings.json` → `env` section
4. **Node defaults** - Built into node definitions

### Management Commands

**Write to settings file (persistent):**
```bash
pflow settings set-env ANTHROPIC_API_KEY "sk-ant-..."
# Writes to ~/.pflow/settings.json → env.ANTHROPIC_API_KEY
# Available to all future pflow commands
```

**Set shell environment (temporary override):**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
# Available in current shell session only
# Overrides settings file without modifying it
```

**View settings file:**
```bash
pflow settings show
# Shows full settings.json content
```

**List environment variables (from settings file):**
```bash
pflow settings list-env              # Masked (default)
pflow settings list-env --show-values  # Unmasked (caution)
```

**Check specific key:**
```bash
pflow settings get ANTHROPIC_API_KEY
# Returns value from settings file (masked by default)
```
```

**Impact:** HIGH - Prevents credential lookup confusion, clarifies three distinct concepts

---

### 2. Discovery Threshold Contradiction ⭐⭐⭐⭐⭐

**Location:** Lines 196-213 (Processing Discovery Results)

**Issue:** Contradictory match score thresholds:
- Line 201: "run/execute" requires ≥90%
- Line 208: "action request" requires ≥80%
- What's the difference between these two?

**Current Table:**
```markdown
| User Intent | Match Score | Required Params | Action |
|------------|-------------|-----------------|---------|
| "run/execute [workflow]" | ≥90% | All present | Execute immediately |
| "run/execute [workflow]" | ≥90% | Missing | Ask for params, then execute |
| Action request | ≥80% | All present | Execute immediately |
```

**Proposed Fix:**

Replace entire table at lines 196-213:

```markdown
### Decision Matrix: When to Execute Automatically

| User Intent | Match Score | Required Params | Action |
|------------|-------------|-----------------|---------|
| **Explicit: "run/execute [name]"** | ≥95% | All present | ✅ Execute immediately |
| Explicit: "run [name]" | 85-94% | All present | ⚠️ Ask "Run 'workflow-name'?" then execute |
| Explicit: "run [name]" | 85-94% | Missing | ⚠️ Ask for params + confirmation |
| Explicit: "run [name]" | <85% | Any | ❌ "No exact match. Found: [list]" |
| **Implicit: Action verb + target** | ≥90% | All present | ✅ Execute immediately |
| Implicit: "analyze my repo" | 75-89% | All present | ⚠️ Show match, ask confirmation |
| Implicit: any action | <75% | Any | ❌ Show alternatives, don't execute |

**Distinction:**
- **Explicit** = User says "run", "execute", or workflow name directly
  - Example: "run github-analyzer", "execute my-workflow"
  - Higher threshold (95%) for truly automatic execution

- **Implicit** = User describes desired action without naming workflow
  - Example: "analyze this PR", "summarize my code"
  - Lower threshold (90%) because user isn't aware workflow exists

**Conservative by Design:**
- Middle range requires confirmation to avoid unwanted executions
- Better to ask once than execute wrong workflow
```

**Impact:** HIGH - Prevents incorrect automatic execution, reduces user frustration

---

### 3. "System Constraint" Definition Missing ⭐⭐⭐⭐

**Location:** Lines 866-896 (The Input Decision Framework)

**Issue:** Docs say "hardcode system constraints" but don't define what qualifies as a "system constraint"

**Examples of Confusion:**
- `"encoding": "utf-8"` - System constraint? (YES per docs)
- `"method": "POST"` - System constraint? (Unclear)
- `"format": "json"` - System constraint? (Unclear)
- `"base_url": "https://api.service.com"` - System constraint? (Unclear)

**Proposed Fix:**

Add new subsection after line 896:

```markdown
### System Constraints (Always Hardcode)

**Definition:** Values that must be specific for the workflow to function correctly. Changing them would break the workflow's core logic.

**✅ Examples of System Constraints (Hardcode These):**
- `"encoding": "utf-8"` - Required for text processing to work
- `"method": "POST"` - API requires POST, GET wouldn't work
- `"protocol": "https"` - Security requirement
- `"content_type": "application/json"` - Parser expects JSON
- **LLM instructions/prompts** - Core workflow logic
- **Regex patterns** - Part of parsing logic
- **Technical protocols** - HTTP versions, auth schemes

**❌ NOT System Constraints (Make These Inputs):**
- `"format": "json"` - User might want CSV, XML, etc.
- `"base_url": "https://api.service.com"` - User might use staging vs prod
- `"limit": 10` - User might want different amounts
- `"timeout": 30` - User might have different network conditions
- **All data values** - Topics, names, IDs, paths, queries
- **Business logic values** - Thresholds, categories, filters

### The Litmus Test

**Ask yourself:**
> "If a user ran this workflow twice with different [value], would it still make sense?"

**Examples:**

| Value | Different Options | Makes Sense? | Decision |
|-------|------------------|--------------|----------|
| `encoding` | utf-8 vs latin-1 | ❌ No (breaks parsing) | Hardcode |
| `method` | POST vs GET | ❌ No (API won't work) | Hardcode |
| `format` | json vs csv | ✅ Yes (just different output) | Make input |
| `limit` | 10 vs 100 | ✅ Yes (same function, different scale) | Make input |
| `repo_name` | repo-a vs repo-b | ✅ Yes (same analysis, different target) | Make input |

**Rule of Thumb:**
- If changing it breaks the workflow → Hardcode
- If changing it varies the use case → Make input
```

**Impact:** HIGH - Prevents agents from making wrong input vs hardcoded decisions

---

## 🟠 Priority 2: Inconsistencies (Should Fix)

### 4. "Always Run Discovery" vs "Skip for Known Patterns"

**Location:** Line 28 vs Line 1186

**Conflict:**
- **Line 28:** "Run this command first. Always. No exceptions."
- **Line 1186:** "Skip testing for: Known patterns you've used before"

**Proposed Fix:**

Replace line 28-35 with:

```markdown
### Step 1: Check for Existing Workflows

**First time handling this type of request?**
```bash
uv run pflow workflow discover "user's exact request here"
```
- ≥95% match → Skip building, execute directly
- 80-94% match → Ask user to confirm
- <80% match → Continue to building

**Built similar workflow in this conversation?**
Ask user: "I can build [workflow type] similar to [previous]. Should I check for existing workflows first or proceed?"
- If user says proceed → Skip discovery, start building
- If uncertain → Run discovery

**Why not "always"?**
Discovery adds 5-10 seconds. Skip when:
- You just built similar workflow
- User explicitly says "build a new workflow"
- Request is clearly unique/custom
```

**Impact:** MEDIUM - Resolves contradiction, saves unnecessary LLM calls

---

### 5. Node Parameter Philosophy Contradiction

**Location:** Line 1024 vs Lines 481-496

**Conflict:**
- **Line 1024:** "Use node defaults whenever possible. Only set parameters the user explicitly requests."
- **Lines 481-496:** "For every user-specified value, create an input."

**Proposed Fix:**

Replace line 1024-1030 with:

```markdown
### Node Parameter Philosophy

**Required parameters (no defaults):**
ALWAYS set these - workflow won't run without them.

**Optional parameters with good defaults:**

Apply the "Commonly Customized Test":
> "Would a user likely want to change this between runs?"

**YES → Add as input with default:**
- `limit`, `count`, `max_items` - Users vary quantities
- `timeout` - Users have different network conditions
- `time_period` - Users want different date ranges
- `filter`, `search_query` - Users refine searches

**NO → Use node default, don't expose:**
- `encoding` - Technical detail (usually utf-8)
- `protocol` - System constraint (https)
- `retry_count` - Technical optimization
- `include_deleted` - Rare use case

**User explicitly mentions value → ALWAYS set it**

**Example:**
User: "Fetch messages from Slack channel C123"

```json
{
  "inputs": {
    "channel": {"type": "string", "required": true},      ← User mentioned
    "limit": {"type": "integer", "default": 10}           ← Commonly customized
    // NO include_deleted - rarely needed
    // NO timeout_ms - technical detail
  }
}
```
```

**Impact:** MEDIUM - Clear guidance on when to expose parameters

---

### 6. Error Handling: Proactive vs Reactive

**Location:** Line 102 vs Line 366

**Conflict:**
- **Line 102:** "Offer solutions, not just errors"
- **Line 366:** "If tests fail: [then offer solutions]"

**Proposed Fix:**

Replace line 102-110 with:

```markdown
### Error Handling Philosophy

**Before building workflows with external services:**

1. **Check if credentials are needed**
2. **Verify credentials exist:**
   ```bash
   pflow settings show
   # or
   pflow settings list-env
   ```
3. **If missing, help user add them BEFORE building**

**Example:**
```
"This workflow needs a Slack token. Let me check your settings...

⚠️  No SLACK_TOKEN found.

Here's how to add it:
1. Get token from api.slack.com/tokens
2. Run: pflow settings set-env SLACK_TOKEN "xoxb-your-token"

Should I wait while you add it, or continue and we'll add it later?"
```

**After errors during execution:**
1. Explain error in plain language
2. Show exact fix command
3. Wait for user to fix
4. Retry or rebuild
```

**Impact:** LOW - Clarifies when to check credentials

---

## 🟡 Priority 3: Missing Content (Should Add)

### 7. Template Variable Edge Cases

**Location:** After line 1077 (Template Variable Syntax section)

**Issue:** No guidance on composition, escaping, or optional values

**Proposed Addition:**

```markdown
### Advanced Template Patterns

#### Combining Multiple Templates

**Composition is supported:**
```json
{
  "params": {
    "output_path": "results/${date}/${category}/${filename}.json"
  }
}
```
Where:
- `${date}` comes from node output (e.g., `get-date.stdout`)
- `${category}` and `${filename}` are workflow inputs
- All parts get resolved independently

#### Literal Dollar Signs

**Not currently supported** - No escape syntax exists.

**Workaround:** Use a shell node:
```json
{
  "id": "format-price",
  "type": "shell",
  "params": {
    "command": "echo 'Price: $${amount}'"  ← Shell expands this
  }
}
```

#### Optional/Missing Values

**Templates that reference missing values cause validation errors.**

No optional template syntax (no `${var:-default}` like bash).

**Workaround:** Use `required: false` with defaults:
```json
{
  "inputs": {
    "prefix": {
      "type": "string",
      "required": false,
      "default": "",
      "description": "Optional prefix for output"
    }
  }
}
```

#### Nested Access

**Supported for structured data:**
```json
{
  "params": {
    "title": "${api_result.data.items[0].title}"
  }
}
```

**Works when node outputs:**
```json
{
  "data": {
    "items": [
      {"title": "First Item"}
    ]
  }
}
```
```

**Impact:** MEDIUM - Prevents template usage mistakes

---

### 8. Workflow Execution Time Expectations

**Location:** Lines 1502-1514 (Complexity Reality Checks)

**Issue:** Time estimates don't account for LLM latency or sequential execution

**Proposed Replacement:**

```markdown
### Time Expectations (Sequential Execution)

**Important:** ALL nodes run one after another. No parallelization.

| Workflow Type | Nodes | Time Range | Notes |
|--------------|-------|------------|-------|
| Simple file processing | 3-5 | 2-10 sec | No LLM, no APIs |
| Single API + LLM | 3-7 | 20-60 sec | 1 LLM call (~10-30s) + API (~5-15s) |
| Multi-API pipeline | 10-15 | 1-3 min | Each API: 5-30s sequential |
| Complex multi-step | 20+ | 3-10 min | Multiple LLM calls add 30s-2min |

**Latency Breakdown (per node):**
- **LLM nodes:** 5-30 seconds (depends on model, prompt length, thinking)
- **HTTP APIs:** 1-15 seconds (auth, rate limits, network)
- **MCP tools:** 2-30 seconds (varies by tool complexity)
- **File operations:** <1 second
- **Shell commands:** <5 seconds (unless running long processes)

**Sequential Execution Math:**
- 5 LLM nodes = 25-150 seconds minimum (5×5 to 5×30)
- 3 API calls = 3-45 seconds minimum (3×1 to 3×15)
- **Add them all up for total estimate**

**Optimization Tip:**
Use `Prefer: wait=60` header with HTTP nodes to eliminate polling:
- ❌ Without: 3 nodes (call → poll → poll) = 30-60 seconds
- ✅ With: 1 node (call with wait) = 10-60 seconds
```

**Impact:** LOW - Better time expectations, reduces user impatience

---

### 9. Command Output Schemas (NEW Section)

**Location:** New section after line 2000

**Issue:** Agents don't know exact structure of command outputs

**Proposed New Section:**

```markdown
## Command Output Schemas

### JSON Output Mode

**All commands support `--output-format json`** for programmatic access.

#### workflow execute

**Success:**
```json
{
  "success": true,
  "outputs": {
    "result": "...",
    "custom_field": "..."
  },
  "trace_path": "~/.pflow/debug/workflow-trace-20251012-143022.json",
  "metrics": {
    "execution_time_ms": 1234,
    "nodes_executed": 5,
    "nodes_cached": 2,
    "llm_cost_usd": 0.0123
  }
}
```

**Error:**
```json
{
  "success": false,
  "error": {
    "type": "NodeExecutionError",
    "message": "Node 'fetch-data' failed: Connection timeout",
    "node_id": "fetch-data",
    "details": "..."
  },
  "checkpoint": {
    "completed_nodes": ["node1", "node2"],
    "failed_node": "fetch-data",
    "state": {...}
  }
}
```

#### workflow validate

**Success:**
```json
{
  "valid": true,
  "message": "✓ All validations passed",
  "errors": [],
  "suggestions": []
}
```

**Error:**
```json
{
  "valid": false,
  "message": "Validation failed with 2 errors",
  "errors": [
    {
      "type": "TemplateError",
      "message": "Template variable '${unknown}' not found",
      "location": "nodes[1].params.content",
      "suggestion": "Did you mean ${known}?"
    }
  ]
}
```

#### registry run

**Returns formatted text** (not JSON) showing node outputs:
```
✓ Node executed successfully

Outputs:
  content: [file contents]
  file_path: /path/to/file
  error: null
```

#### registry describe

**Returns markdown text** with node specifications.

### Text Output Mode (Default)

**Formatted for human reading** with tables, colors, and visual structure.
See CLI Command Review section for examples.
```

**Impact:** MEDIUM - Enables programmatic parsing of outputs

---

### 10. MCP Integration Section (NEW Section)

**Location:** New section after line 2023

**Issue:** No mention of MCP server mode

**Proposed New Section:**

```markdown
## Using pflow via MCP Server

**pflow can run as an MCP server** for AI agents that support Model Context Protocol.

### Starting the Server

```bash
uv run pflow mcp serve
```

This starts a stdio-based MCP server that exposes all pflow commands as tools.

### Claude Desktop Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pflow": {
      "command": "uv",
      "args": ["run", "pflow", "mcp", "serve"],
      "cwd": "/path/to/pflow"
    }
  }
}
```

### Available MCP Tools

All CLI commands are available as MCP tools with exact parity:

| MCP Tool | CLI Equivalent | Output Format |
|----------|---------------|---------------|
| `workflow_list` | `pflow workflow list` | Markdown table |
| `workflow_describe` | `pflow workflow describe <name>` | Markdown |
| `workflow_discover` | `pflow workflow discover "query"` | Markdown |
| `workflow_execute` | `pflow <workflow> params` | JSON |
| `workflow_validate` | `pflow --validate-only <workflow>` | JSON |
| `workflow_save` | `pflow workflow save ...` | JSON |
| `registry_list` | `pflow registry list` | Markdown |
| `registry_search` | `pflow registry search <pattern>` | Markdown |
| `registry_describe` | `pflow registry describe <nodes>` | Markdown |
| `registry_discover` | `pflow registry discover "task"` | Markdown |
| `registry_run` | `pflow registry execute <node>` | Text |
| `settings_get` | `pflow settings get <key>` | Text |
| `settings_set` | `pflow settings set-env <key> <value>` | Text |
| `settings_show` | `pflow settings show` | JSON |

### CLI vs MCP: When to Use Which

**Use MCP tools when:**
- You're an AI agent with tool-calling capabilities
- You want structured responses for programmatic parsing
- You're building multi-step workflows interactively

**Use CLI directly when:**
- You're working in a terminal
- You want colored output and progress indicators
- You're writing shell scripts

### Output Parity

**MCP tools return the same format as CLI:**
- Markdown for human-readable text
- JSON for structured data
- Same error messages and suggestions
```

**Impact:** MEDIUM - Educates agents about MCP mode

---

## Implementation Plan

### Phase 1: Critical Fixes (Do First)
1. Settings vs Environment Variables (lines 904-958)
2. Discovery Thresholds (lines 196-213)
3. System Constraint Definition (lines 866-896)

**Estimated Time:** 2-3 hours
**Impact:** Prevents major confusion for agents

### Phase 2: Inconsistency Fixes
4. Discovery mandate contradiction (line 28 vs 1186)
5. Node parameter philosophy (line 1024 vs 481-496)
6. Error handling (line 102 vs 366)

**Estimated Time:** 1-2 hours
**Impact:** Removes conflicting guidance

### Phase 3: Missing Content
7. Template edge cases (after line 1077)
8. Execution time expectations (lines 1502-1514)
9. Command output schemas (new section ~line 2000)
10. MCP integration section (new section ~line 2023)

**Estimated Time:** 2-3 hours
**Impact:** Fills knowledge gaps

### Total Estimated Effort
**6-8 hours** for complete documentation overhaul

---

## Success Criteria

**After these fixes, agents should be able to:**
1. ✅ Know exactly where to find/store credentials
2. ✅ Make correct decisions about when to auto-execute
3. ✅ Distinguish system constraints from user inputs
4. ✅ Handle template composition and edge cases
5. ✅ Understand exact output formats for parsing
6. ✅ Know when to use CLI vs MCP mode

**Measure success by:**
- Reduced agent confusion in testing
- Fewer incorrect credential lookups
- Correct input vs hardcoded decisions
- Proper auto-execution threshold usage
