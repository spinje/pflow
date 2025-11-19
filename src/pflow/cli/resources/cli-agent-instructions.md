# pflow Agent Instructions - Complete Guide

> **Purpose**: Enable AI agents to build reusable workflows by transforming user-specific examples into general-purpose tools with precision and clarity.

## Part 1: Foundation & Mental Model

### Core Mission
You help users build **reusable workflows** - automated sequences that transform data reliably.
- Users describe their need with ONE specific example
- You build a tool that works for ANY similar case
- Every specific value becomes a configurable input
- The workflow runs deterministically every time

### 🎯 Primary Decision Rule + Quick Wins

**THE fundamental decision (saves 50-75% of LLM costs):**
Structured data (JSON/CSV/XML) → `shell` node · Unstructured → `llm` node

**Quick wins (memorize these):**
- **Workflow exists?** → Use it (5 sec vs 60 min to build)
- **Passing `${node.result}` wholesale?** → Skip testing
- **Async API?** → Try `Prefer: wait=60` header first
- **JSON from shell?** → Auto-parses to objects
- **Multiple API calls?** → Batch in one node

### Core Philosophy - Understanding the WHY

**Why pflow exists**: After an AI helps create a workflow, it runs forever without AI overhead. Deterministic execution means the same inputs always produce the same outputs. This is automation that doesn't "think" - it just executes reliably.

**Why edges vs templates matter**: Edges define a simple execution timeline (when), while templates enable flexible data composition (what). This separation lets you build complex data flows within simple linear execution. Edges control when nodes run (the timeline). Templates control what data each node sees (the history it can access).

**Why shell+jq over LLM for structured data**: Structured operations should be deterministic. Using LLM for JSON extraction costs tokens, adds latency, and risks hallucination. Shell+jq is free, instant, and precise. Reserve LLM for tasks requiring understanding, not extraction.

**Why test only what you'll use**: Testing every node output wastes time and adds complexity. If you're passing `${node.result}` wholesale to an LLM or service, that component handles any structure. Only investigate structure when you need specific paths like `${node.result.data.items[0].id}`.

**Why general over specific**: Users show you their immediate problem, but they'll have similar problems tomorrow with different data. Making values configurable transforms single-use scripts into reusable tools. Exception: when users explicitly say "for MY repository" or "only for this specific file" - then they might want a specific tool, not a general one.

### 🛑 MANDATORY First Step - Check for Existing Workflows

**This is non-negotiable. Before any other action:**
```bash
uv run pflow workflow discover "user's exact request here"
```

**Decision tree based on match score:**
- **≥95% match** → Execute immediately with `uv run pflow workflow-name`, you're done
- **80-94% match** → Show user: "Found [name] that does this. Should I use it, modify it, or build new?"
- **70-79% match** → Load workflow, show differences, suggest: "I can modify [name] to do what you need"
- **<70% match** → Continue to build new workflow

**Why this matters**: Building takes 30-60 minutes. Using existing takes 5 seconds.

### Supported Service Categories

MCP servers span these categories (each has unique output structure):
**Data** · **Communication** · **Storage** · **DevOps** · **Productivity** · **APIs**

Examples: Databases (PostgreSQL, MySQL), Chat (Slack, Discord), Cloud (S3, GCS), Version Control (GitHub, GitLab), Docs (Notion, Sheets), REST/GraphQL

**Always test - never assume similarity.**

### Two Fundamental Concepts - Edges vs Templates

**This distinction causes 80% of workflow rebuilding. Understand it completely.**

#### Concept 1: Execution Order (Edges)
**Edges define WHEN nodes run** - strictly sequential, one after another.

```
fetch-data → process-data → save-results
```

**What this means precisely:**
- `process-data` starts ONLY after `fetch-data` completely finishes
- `save-results` starts ONLY after `process-data` completely finishes
- No node can start until its predecessor completes
- Each node has exactly ONE successor (except the last node which has none)
- No parallel execution ever

#### Concept 2: Data Access (Templates)
**Templates define WHAT DATA nodes can see** - any node can access any PREVIOUS node's output.

**Critical example showing the difference:**
```json
{
  "nodes": [
    {
      "id": "step1-fetch",
      "type": "http",
      "params": {"url": "${api_url}"}
    },
    {
      "id": "step2-timestamp",
      "type": "shell",
      "params": {"command": "date +%Y-%m-%d"}
    },
    {
      "id": "step3-extract",
      "type": "shell",
      "params": {
        "stdin": "${step1-fetch.response}",  // Can access step1 even though step2 is between
        "command": "jq '.items'"
      }
    },
    {
      "id": "step4-analyze",
      "type": "llm",
      "params": {
        "prompt": "Analyze this data from ${step3-extract.stdout} fetched at ${step2-timestamp.stdout}"
      }
    },
    {
      "id": "step5-report",
      "type": "llm",
      "params": {
        "prompt": "Create report:\nRaw: ${step1-fetch.response}\nItems: ${step3-extract.stdout}\nAnalysis: ${step4-analyze.response}\nTime: ${step2-timestamp.stdout}"
      }
    }
  ],
  "edges": [
    {"from": "step1-fetch", "to": "step2-timestamp"},
    {"from": "step2-timestamp", "to": "step3-extract"},
    {"from": "step3-extract", "to": "step4-analyze"},
    {"from": "step4-analyze", "to": "step5-report"}
  ]
}
```

**Key insights from this example:**
- `step3-extract` accesses `step1-fetch.response` directly (skipping step2)
- `step5-report` accesses ALL previous outputs (step1, step2, step3, step4)
- Edges only control execution order, NOT data availability
- Think of it as: edges create a timeline, templates access history

**Data availability at each step:**
| Execution Order | Data Available to This Node |
|-----------------|------------------------------|
| step1-fetch | (none) |
| step2-timestamp | step1-fetch |
| step3-extract | step1-fetch, step2-timestamp |
| step4-analyze | step1-fetch, step2-timestamp, step3-extract |
| step5-report | ALL previous nodes |

This accumulation pattern is fundamental - each node adds to the available data pool.

### Common Misunderstandings About Edges vs Templates

❌ **Wrong**: "If I put nodes A→B→C, then C can only see B's output"
✅ **Right**: C can access A, B, or both. Edges don't restrict data access.

❌ **Wrong**: "I have to design nodes so each one only uses the previous one's data"
✅ **Right**: Design nodes for their purpose. Then in templates, pull data from wherever you need.

❌ **Wrong**: "Templates must follow the edge order"
✅ **Right**: Templates can jump over nodes. Edges just define execution sequence.

**Real-world example showing why template jumping matters:**
```
fetch-api → save-raw → extract-fields → format → send-slack

Problem: If templates couldn't jump, 'format' would never see the raw API response
Solution: 'format' uses BOTH ${extract-fields.stdout} AND ${fetch-api.response}
Result: Formatted output includes both extracted data and original context
```

### What Workflows CANNOT Do (Hard Limits)

**Recognize these immediately and offer alternatives:**

#### ❌ No Loops or Iteration
**User wants**: "Process each file in a directory differently based on its type"
**Why impossible**: Workflows can't create dynamic numbers of operations
**Alternative**: "I'll create a workflow that processes ALL files in one batch operation, applying the same logic to each"

#### ❌ No Conditional Logic
**User wants**: "If the API returns error, retry 3 times, else process data"
**Why impossible**: No if/then/else branching in workflows
**Alternative**: "I'll create two workflows: one for success path, one for error handling. You choose which to run based on the result"

#### ❌ No State or Memory
**User wants**: "Track which records we've already processed and skip them"
**Why impossible**: Each workflow run is completely independent
**Alternative**: "The workflow will process all current records. You could maintain a processed list externally"

#### ❌ No User Interaction During Execution
**User wants**: "Ask me to confirm before deleting files"
**Why impossible**: Workflows run to completion without pausing
**Alternative**: "I'll create a workflow that lists files to delete, then a separate one that performs deletion after your review"

#### ❌ No Dynamic Node Creation
**User wants**: "Create one processing node for each item in the response"
**Why impossible**: Workflow structure is fixed at creation time
**Alternative**: "I'll process all items in a single node using batch operations"

### One Workflow or Multiple? (Critical Decision)

**This decision shapes the entire implementation:**

#### Build ONE Workflow When:
- Steps are always done together as a unit
- Data flows between all steps
- User wants a single command to run everything
- The operations are logically coupled

**Example**: "Fetch API data, validate it, transform it, and store it"
→ ONE workflow (always done as complete sequence)

#### Build MULTIPLE Workflows When:
- Steps might be run independently
- Different scheduling/triggers needed
- Operations serve different purposes
- User might want partial execution

**Example**: "Monitor GitHub PRs, monitor issues, and monitor commits"
→ THREE workflows (each monitoring task is independent)

#### The Litmus Test
Ask yourself: "Would a user ever want to run step X without step Y?"
- If YES → Separate workflows
- If NO → Single workflow

**When unsure, ask the user directly**:
"Should this be one workflow that does everything, or separate workflows you can run independently?"

## Part 2: Node & Tool Selection Principles

### Node Type Selection (pflow-Specific)

**Which pflow node to use:**
- **Structured data** (JSON/CSV/XML) → `shell` node with jq/awk/grep commands
- **Unstructured data** → `llm` node (costs per workflow execution)
- **JSON REST APIs** → `http` node
- **Binary/streaming data** → `shell` node with curl
- **Service-specific APIs** → `mcp-{service}-{TOOL}` nodes (auto-auth)

**Async API optimization:**
Try `Prefer: wait=60` header in `http` node first (eliminates polling nodes)

## Part 3: The Complete Development Loop

### Step 1: UNDERSTAND - Parse Requirements Precisely

**Identify**: Inputs needed · Processing steps · Output format · Credentials

**Common patterns**: Fetch→Transform→Store · Multi-source aggregation · Service chain · Enrichment pipeline

**Intent signals to recognize:**
| User Says | Intent | Confidence | Action |
|-----------|--------|------------|--------|
| "run [specific workflow name]" | Execute | High | Find and run |
| "do X then Y then Z" | Build | High | Create workflow |
| "I need to [outcome]" | Explore | Medium | Clarify approach |
| "how can I [task]" | Learn | Low | Explain options |
| "automate [process]" | Build | High | Create workflow |

### Step 2: DISCOVER WORKFLOWS - Detailed Matching

```bash
uv run pflow workflow discover "exact user request, including all details"
```

**Match score actions:**
- **≥95%** → Execute immediately (or ask for missing params)
- **80-94%** → Show differences, ask: use/modify/build?
- **70-79%** → Suggest modifications
- **<70%** → Build new (continue to Step 3)

**Modify existing**: `cat ~/.pflow/workflows/[name].json` → Edit nodes/inputs/outputs → Validate (Step 9)

### Step 3: DISCOVER NODES - Finding Building Blocks

```bash
uv run pflow registry discover "[complete description of ALL operations needed]"
```

**Effective task descriptions:**
```bash
# ❌ Too vague
uv run pflow registry discover "process data"

# ✅ Complete and specific
uv run pflow registry discover "fetch JSON from REST API, extract specific fields, validate data completeness, transform to CSV format, upload to S3 bucket"
```

**Interpreting discovered nodes:**
- **Parameters with defaults** → Usually optional
- **Parameters without defaults** → Always required
- **Output type "Any"** → Need to test for structure
- **Output type specified** → Can use directly

### Step 4: EXTERNAL API INTEGRATION

**When no dedicated node exists, follow this systematic approach:**

#### Phase 1: Research
```bash
# Search for API documentation (conceptually - agents have web search)
# Look for: authentication method, main endpoints, request format, response structure, rate limits
```

**API integration**: JSON APIs → `http` node · Binary/streaming/custom → `shell` node with curl

#### Phase 3: Test Authentication
```bash
# Test with minimal call
uv run pflow registry run http \
  url="https://api.service.com/health" \
  headers='{"Authorization": "Bearer TOKEN"}'
```

### Step 5: TEST MCP/HTTP NODES - Precise Testing Criteria

## ⚡ STOP! Don't Test If You're Passing `${node.result}` Wholesale

**If you're doing this, SKIP ALL TESTING:**
```json
{
  "id": "analyze",
  "type": "llm",
  "params": {"prompt": "Analyze: ${fetch.result}"}  // Passing whole result = NO TEST NEEDED
}
```

**Only test when you need specific paths like `${node.result.data.items[0].id}`**

**Registry run output is pre-optimized for AI agents:**
- Automatically filtered to show only business-relevant fields (removes noise)
- Shows structure without data values
- **Don't grep/filter the output** - what's displayed is what matters
- Need actual values? Use: `pflow read-fields exec-id field.path1 field.path2`

**Decision tree for testing:**
```
Is it an MCP node?
├─ YES → Are you unsure what format it accepts OR accessing specific fields?
│        ├─ YES → Test with `registry run` AND your actual data format
│        └─ NO → Skip testing (just pass ${node.result} to next node)
└─ NO → Is it HTTP with unknown response?
         ├─ YES → Will you extract specific fields?
         │        ├─ YES → Test with real endpoint
         │        └─ NO → Skip testing
         └─ NO → Is it complex shell+jq?
                  ├─ YES → Test extraction logic
                  └─ NO → Skip testing
```

**Key insight**: If you're just passing `${mcp-node.result}` to an LLM or another service, you don't need to know its structure. Only test when you need specific paths like `${mcp-node.result.data.field}` OR when unsure if the node accepts your data format.

**Example - When to test vs skip:**
```json
{
  "nodes": [
    // Skip testing - passing whole result to next node
    {
      "id": "query-database",
      "type": "mcp-postgres-QUERY",
      "params": {"query": "${sql_query}"}
    },
    {
      "id": "analyze-data",
      "type": "llm",
      "params": {
        "prompt": "Analyze this data: ${query-database.result}"  // Whole result = no test needed
      }
    },

    // Need testing - accessing specific nested fields
    {
      "id": "fetch-pr",
      "type": "mcp-github-GET_PR",
      "params": {"pr": "${pr_number}"}
    },
    {
      "id": "check-status",
      "type": "shell",
      "params": {
        "command": "echo 'Status: ${fetch-pr.result.data.state}'"  // Specific path = test required
      }
    }
  ]
}
```

**MCP Testing Protocol:**
```bash
# 1. Inform user (conceptually)
echo "I need to test access to [service]. This will [describe effect]."

# 2. Ask permission if side effects
# If has_side_effects: "⚠️ This test will [visible effect]. Should I proceed?"

# 3. Test with structure discovery AND format compatibility
uv run pflow registry run mcp-{mcp-service-name}-{mcp-tool-name} \
  param1="your_actual_format_here"

# 4. Document results
# - Output structure for template paths
# - Whether your format was accepted directly
```

## ⚠️ MCP Output Has NO Standard Structure

**Every MCP server is completely different. Even the SAME operation:**

```python
# Three different "send message" MCPs:
Server A:  result.data.message.ts
Server B:  result.ok and result.ts           # Flat structure
Server C:  result.response.data[0].id       # Deep nesting

# Three different "query database" MCPs:
Server A:  result.rows[]                    # PostgreSQL style
Server B:  result.data.results[]            # Wrapped
Server C:  result.Items[]                   # DynamoDB style
```

**There are NO patterns. Test every MCP tool:**
`uv run pflow registry run mcp-service-TOOL param=value`

### Step 6: DESIGN - Data Flow Mapping

**Create a precise execution plan:**

```
Execution Order (Edges):
1. fetch-data
2. validate-data
3. get-timestamp
4. transform-data
5. format-output
6. deliver-result

Data Dependencies (Templates):
- validate-data needs: ${fetch-data.response}
- transform-data needs: ${fetch-data.response}, ${validate-data.result}
- format-output needs: ${transform-data.output}, ${get-timestamp.stdout}
- deliver-result needs: ${format-output.result}
```

### Step 7: PLAN & CONFIRM

**Requirements unclear?** → Present 2-3 options with tradeoffs, ask which approach
**Requirements clear?** → State plan: "I'll build: [steps]. Inputs: [list]. Output: [description]. Ready?"

### Step 8: BUILD - Systematic Construction

**If complex workflow - Build incrementally, test each step with minimal data using `limit`, `filter`, `offset` or other similar parameters before adding more nodes and capabilities**

⚠️ **CRITICAL: Development Format Rules**

Your workflow file must contain ONLY these four top-level keys:
- `inputs` (optional but recommended)
- `nodes` (required)
- `edges` (required)
- `outputs` (optional)

**DO NOT include these fields** (they cause validation errors):
- ❌ `name`
- ❌ `description`
- ❌ `version`
- ❌ `created_at`, `updated_at`
- ❌ Any other metadata fields

**Why?** The `pflow workflow save` command adds metadata automatically. Including them manually causes:
```
ValidationError: Additional properties are not allowed ('name', 'description' were unexpected)
```

**Correct development format:**
```json
{
  "inputs": {"param": {"type": "str", "required": true}},
  "nodes": [...],
  "edges": [...],
  "outputs": {...}
}
```

Save this as `my-workflow.json` anywhere you like. The save command will add all required metadata later.

---

#### Phase-Based Building for Complex Workflows

**When to phase (based on complexity, not count):**
- Multiple external services (even if only 5 nodes)
- Unknown API responses that need testing
- Complex data transformations with dependencies
- First time using certain nodes
- More than 15 nodes IF they're complex (20 simple shell commands might not need phasing)

**Phase 1: Core Data Path (Test Immediately)**
```json
{
  "inputs": {
    "source_url": {"type": "string", "required": true, "description": "Data source"}
  },
  "nodes": [
    {
      "id": "fetch",
      "type": "http",
      "params": {"url": "${source_url}"}
    },
    {
      "id": "extract",
      "type": "shell",
      "params": {
        "stdin": "${fetch.response}",
        "command": "jq '.data'"
      }
    },
    {
      "id": "test-output",
      "type": "write-file",
      "params": {
        "file_path": "/tmp/test.json",
        "content": "${extract.stdout}"
      }
    }
  ],
  "edges": [
    {"from": "fetch", "to": "extract"},
    {"from": "extract", "to": "test-output"}
  ]
}
```

**Test before continuing:**
```bash
uv run pflow phase1.json source_url="https://api.example.com/data"
# Verify: Did extraction work? Is data structure correct?
```

**Phase 2: Add Processing (One Service at a Time)**
```json
// Add to existing nodes
{
  "id": "process",
  "type": "llm",
  "params": {
    "prompt": "Analyze this data and extract key insights:\n${extract.stdout}"
  }
}
```

**Phase 3: Add External Services**
```json
// Add each external service and test
{
  "id": "send-notification",
  "type": "mcp-slack-send",
  "params": {
    "channel": "${notification_channel}",
    "text": "${process.response}"
  }
}
```

**Phase 4: Polish and Outputs**
```json
// Add formatting, final outputs
{
  "outputs": {
    "analysis": {"source": "${process.response}", "description": "Analysis results"}
  }
}
```

#### Input Declaration - Complete Rules

**Decision process for EVERY value:**

```
Is this value in the user's request?
├─ YES → Is it marked with "always" or "only"?
│        ├─ YES → Hardcode it
│        └─ NO → Make it an input
└─ NO → Is it implementation detail (prompt, jq command, script)?
         ├─ YES → Hardcode it (users don't customize implementation)
         └─ NO → Is it a system constraint?
                  ├─ YES → Hardcode it
                  └─ NO → Would users want to configure this?
                           ├─ YES → Make it an input with default
                           └─ NO → Hardcode it
```

**Key insight**: LLM prompts, jq extraction commands, and shell scripts are HOW the workflow works, not WHAT it processes. These stay hardcoded unless the user specifically asks to customize them.

**Input examples with rationale:**
```json
{
  "inputs": {
    // User value - becomes input
    "api_endpoint": {
      "type": "string",
      "required": true,
      "description": "API URL to fetch data from"
    },

    // User mentioned but with default
    "limit": {
      "type": "number",
      "required": false,
      "default": 10,
      "description": "Maximum items to process"
    },

    // Not mentioned but configurable
    "output_format": {
      "type": "string",
      "required": false,
      "default": "json",
      "description": "Output format (json, csv, xml)"
    },

    // Array input example
    "tags": {
      "type": "array",
      "required": false,
      "default": ["important"],
      "description": "Tags to filter by"
    },

    // Object input example
    "options": {
      "type": "object",
      "required": false,
      "default": {"verbose": false},
      "description": "Processing options"
    }
  }
}
```

#### Node Creation - Complete Patterns

```json
{
  "nodes": [
    // HTTP node with full options
    {
      "id": "fetch-with-auth",
      "type": "http",
      "purpose": "Fetch data from protected API",
      "params": {
        "url": "${api_url}",
        "method": "POST",
        "headers": {
          "Authorization": "Bearer ${api_token}",
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        "body": {
          "query": "${search_query}",
          "limit": "${limit}"
        }
      }
    },

    // Shell node with complex jq
    {
      "id": "complex-extraction",
      "type": "shell",
      "purpose": "Extract and transform nested data",
      "params": {
        "stdin": "${fetch-with-auth.response}",
        "command": "jq '[.data.items[] | select(.status == \"active\") | {id: .id, name: .name, value: .metrics.value}]'"
      }
    },

    // LLM with structured prompt
    {
      "id": "structured-analysis",
      "type": "llm",
      "purpose": "Analyze data with specific criteria",
      "params": {
        "prompt": "Analyze this data according to these criteria:\n\nData:\n${complex-extraction.stdout}\n\nCriteria:\n1. Identify patterns\n2. Find anomalies\n3. Suggest improvements\n\nFormat your response as:\n- Patterns: ...\n- Anomalies: ...\n- Improvements: ...",
        "temperature": 0.7,
        "model": "gpt-4"
      }
    },

    // MCP node with nested parameters
    {
      "id": "update-service",
      "type": "mcp-service-UPDATE",
      "purpose": "Update external service with results",
      "params": {
        "resource_id": "${resource_id}",
        "data": {
          "status": "completed",
          "results": "${structured-analysis.response}",
          "timestamp": "${get-timestamp.stdout}",
          "metadata": {
            "source": "${api_url}",
            "processed_count": "${limit}"
          }
        }
      }
    }
  ]
}
```

### Step 9: VALIDATE - Understanding Validation Errors

```bash
uv run pflow --validate-only workflow.json
```

**Common validation errors with precise fixes:**

| Error Message | Exact Cause | Precise Fix |
|---------------|-------------|-------------|
| `"Unknown node type 'mcp-slack-fetch'"` | Node type doesn't exist | Run `uv run pflow registry discover "fetch Slack messages"` to find correct type |
| `"Template variable '${channel_id}' not found in inputs or node outputs"` | Missing input declaration | Add to inputs: `"channel_id": {"type": "string", "required": true, "description": "..."}` |
| `"Node 'process' references '${analyze.result}' but 'analyze' hasn't executed yet"` | Wrong edge order | Fix edges so 'analyze' runs before 'process' |
| `"Circular dependency detected: A -> B -> C -> A"` | Edge loop | Remove the edge that creates the cycle |
| `"Missing required parameter 'url' in node 'fetch'"` | Required param not set | Add `"url": "${api_url}"` to node params |
| `"Invalid input type: expected string, got number"` | Wrong type in template | Check source node output type |
| `"Node 'x' is unreachable"` | No edge leading to node | Add edge from previous node |
| `"Multiple edges from node 'x'"` | Violates linear chain | Remove extra edges, keep only one |

### Step 10: TEST - Systematic Testing

```bash
# Always test with minimal parameters first
uv run pflow workflow.json param1=value1 param2=value2 limit=2
```

**Trace files**: `~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json` contains events, nodes, outputs, errors and more

### Step 11: SAVE - Make It Executable by Name

## 🚨 CRITICAL: Without This Step, Workflows Cannot Be Run by Name! 🚨

**Your workflow currently works with:**
```bash
uv run pflow /path/to/workflow.json param=value  # ✅ Works but requires full path
```

**To make it work with just a name (REQUIRED for reusability):**
```bash
uv run pflow workflow-name param=value  # ❌ Won't work until you save it!
```

**⚡ You MUST use the save command - this is NOT optional:**

```bash
uv run pflow workflow save /path/to/your-workflow.json \
  --name workflow-name \
  --description "Brief description of what it does"
```

**What this command does:**
- Adds required metadata for execution by name
- Saves to workflow library (`~/.pflow/workflows/`)
- Makes the workflow reusable across projects

**Example:**
```bash
# Save your tested workflow
uv run pflow workflow save /tmp/api-processor.json \
  --name api-data-processor \
  --description "Fetches data from API, processes with custom logic, delivers results"

# Now you can execute by name from anywhere
uv run pflow api-data-processor \
  api_url="https://api.example.com/data" \
  limit=100
```

**After saving, always show usage examples:**
```bash
# Original use case
uv run pflow api-data-processor \
  api_url="https://api.example.com/data" \
  limit=100 \
  output_format="json"

# Different use case showing reusability
uv run pflow api-data-processor \
  api_url="https://different-api.com/records" \
  limit=50 \
  output_format="csv"
```

🚫 **DO NOT manually copy to `~/.pflow/workflows/`** - Always use the save command.

## Part 4: Building Workflows - Technical Reference

**Before building, verify**: Discovered workflows (Step 2) · Discovered nodes (Step 3) · Tested MCP nodes (Step 5) · Designed flow (Step 6)

### Authentication Setup

#### Setting Up Credentials

**For API tokens:**
```bash
# User stores in settings
uv run pflow settings set-env SERVICE_API_TOKEN "sk-abc123..."
uv run pflow settings set-env GITHUB_TOKEN "ghp_xyz789..."

# Verify storage
uv run pflow settings show
```

**For LLM providers (using Simon Willison's llm tool):**
```bash
# Interactive setup
llm keys set anthropic
llm keys set openai

# Or direct
llm keys set anthropic --key "sk-ant-..."
```

**Critical**: Settings variables and env variables must be declared as inputs (not auto-available):
```json
{
  "inputs": {
    "api_token": {"type": "string", "required": true, "description": "..."}
  }
}
```
Example of using in nodes: `"Authorization": "Bearer ${api_token}"`

### Workflow Structure Complete Reference

```json
{
  "inputs": {
    "param_name": {
      "type": "string|number|boolean|array|object",
      "description": "What this parameter is for",
      "required": true|false,
      "default": "value"  // Only if required: false
    }
  },
  "nodes": [
    {
      "id": "descriptive-name",
      "type": "node-type-from-registry",
      "purpose": "What this step does",  // Optional but recommended for clarity
      "params": {
        "param1": "static_value",
        "param2": "${input_name}",
        "param3": "${other_node.output}"
      }
    }
  ],
  "edges": [
    {"from": "node1", "to": "node2"}  // Linear chain only
  ],
  "outputs": {  // Optional - skip for automation workflows
    "result_name": {
      "source": "${final_node.output}",
      "description": "What this output contains"
    }
  }
}
```

**Key insight**: Outputs are optional. Automation workflows (send, post, update) often don't need outputs since success is visible through side effects.

### Template Variable Complete Reference

#### Resolution Order (This Matters)
1. Check workflow `inputs` first
2. Then check previous node outputs (in execution order)
3. Error if not found

#### Critical: Automatic JSON Parsing for Simple Templates

**Simple templates (`${var}`) containing JSON strings are automatically parsed when the target parameter expects structured data (dict/list).** This enables shell+jq workflows without requiring LLM intermediate steps.

**Parsing Rules**:
- ✅ **Auto-parsed**: Simple templates like `${node.output}` when target expects dict/list
- ❌ **NOT parsed**: Complex templates like `"text ${var}"` always stay as strings (escape hatch)
- ✅ **Handles newlines**: Shell output with trailing `\n` is automatically stripped
- ✅ **Type-safe**: Only uses parsed result if type matches (array→list, object→dict)
- ✅ **Graceful fallback**: Invalid JSON stays as string (Pydantic validation catches it)

**What happens when you use simple templates:**

| Source Output | Target Parameter Type | What Actually Happens | Need Transformation? |
|--------------|----------------------|----------------------|---------------------|
| JSON string from shell | `body` (object) in HTTP | Auto-parsed to object | ❌ No |
| JSON string from shell | `values` (array) in MCP | Auto-parsed to array | ❌ No |
| JSON string from LLM | `data` (object) in any node | Auto-parsed to object | ❌ No |
| Plain text | `prompt` (string) in LLM | Stays as string | ❌ No |
| Malformed/broken JSON | Any structured type | Keeps as string, validation fails | ✅ Yes - fix format |

**Escape Hatch** (Force String):
If you need a JSON string to remain unparsed, use a complex template:
```json
// This WILL be auto-parsed:
{"params": {"data": "${json_var}"}}

// This will NOT be parsed (stays as string):
{"params": {"data": " ${json_var}"}}  // Leading space makes it complex
{"params": {"data": "${json_var} "}}  // Trailing space
{"params": {"data": "'${json_var}'"}}  // Wrapped in quotes
```

**Shell Output Handling**: Trailing newlines from shell commands are automatically stripped before parsing:
```json
// Shell outputs: '[["data"]]\\n'
// Auto-strips to: '[["data"]]' before parsing
{"params": {"values": "${shell.stdout}"}}  // Works perfectly!
```

**The Anti-Pattern to Avoid:**
```json
// ❌ WRONG - Unnecessary "defensive" extraction
{
  "id": "extract-json",
  "type": "shell",
  "params": {
    "stdin": "${llm.response}",
    "command": "jq '.'"  // Extracting valid JSON for "safety"
  }
}

// ✅ RIGHT - Direct pass (nodes handle parsing)
{
  "id": "use-data",
  "type": "http",
  "params": {
    "body": "${llm.response}"  // JSON string → auto-parsed
  }
}
```

**When you DO need transformation:**
- Malformed JSON (extra text, broken structure)
- Specific field extraction (getting `.items[0]` from larger response)
- Format conversion (JSON to CSV, etc.)

**How to verify:** Test with your EXACT source output format—including newlines, whitespace, and any formatting quirks. If it works in `registry run`, it will work in the workflow. Don't add transformations "just in case."

#### Transformation Complexity Checklist

**Before adding any extraction/processing steps (grep, sed, jq, etc.):**

1. **Can the source produce cleaner output?**
   - LLM: Add "Return ONLY valid JSON, no other text" to prompt
   - Shell: Use `-r` flag in jq to remove quotes
   - HTTP: Check if API has a `format=json` parameter
   - **If yes → Fix at source instead of extracting**

2. **Is each transformation adding risk?**
   - Valid JSON → grep → sed → BROKEN JSON (common!)
   - Each pipe is a new failure point, not a safety layer
   - **Principle: More steps = more risk, not more safety**
   - **Better**: Single `jq` command vs multiple grep/sed pipes

3. **Have you tested EACH transformation step independently?**
   - Test what the source node actually outputs
   - Test what your extraction produces FROM THAT OUTPUT
   - Not with "cleaned" test data
   ```bash
   # Step 1: Get actual upstream output
   uv run pflow registry run llm prompt="..." # See what LLM produces

   # Step 2: Test your extraction with that EXACT output
   uv run pflow registry run shell \
     stdin="[actual LLM output here]" \
     command="your grep/sed/jq command"
   # See what extraction produces - often broken!
   ```
   - **Each step should make data CLEANER, not messier**

4. **Are you solving a real problem or preventing an imaginary one?**
   - ✅ Real: "Parse error when running" → Add transformation
   - ❌ Imaginary: "Might fail, better be safe" → Don't add
   - **Test first. Transform only if test fails.**

**The golden rule:** Every transformation step must solve a verified problem, not prevent a hypothetical one.

#### Template Variables vs jq: Decision Rule

**Extraction (getting data) → Templates**
**Transformation (changing data) → jq**

```
Need data at specific path? → ${node.result.data.items[0].name}
Need to compute/transform?  → jq 'map(...)', jq 'length', jq 'select(...)'
Need to interpret meaning?  → LLM
```

Common mistake: Using jq for extraction creates unnecessary nodes. Templates handle all path traversal automatically.

#### All Template Patterns
```json
{
  "params": {
    // Simple references
    "basic_input": "${username}",
    "basic_output": "${fetch.response}",

    // Nested object access
    "nested": "${fetch.data.user.email}",

    // Array access
    "first_item": "${fetch.items[0]}",
    "specific_field": "${fetch.items[0].name}",
    "last_item": "${fetch.items[-1]}",

    // Multiple templates in one string
    "combined": "User ${username} data: ${fetch.response}",

    // Complex path
    "deep": "${fetch.result.data.users[0].profile.settings.email}",

    // In JSON structures
    "body": {
      "user": "${username}",
      "data": "${process.output}",
      "metadata": {
        "timestamp": "${get-time.stdout}",
        "source": "${api_url}"
      }
    },

    // In shell commands (be careful with escaping)
    "command": "echo '${data}' | jq '.items[0:${limit}]'",

    // Direct values (no template)
    "method": "POST",
    "static_value": 123
  }
}
```

#### Debugging Template Errors

**Error: `Template variable '${fetch.result.messages}' not found`**

Debug process:
```bash
# 1. Check what's actually available
cat ~/.pflow/debug/workflow-trace-*.json | jq '.nodes[] | select(.id == "fetch") | .outputs | keys'

# Output might be:
# ["response", "status", "headers"]

# 2. Explore the structure
cat ~/.pflow/debug/workflow-trace-*.json | jq '.nodes[] | select(.id == "fetch") | .outputs.response'

# 3. Fix template path
# Wrong: ${fetch.result.messages}
# Right: ${fetch.response.data.messages}
```

### Parameter Types - Complete Guide

```json
{
  "inputs": {
    // String - most common
    "text_input": {
      "type": "string",
      "required": true,
      "description": "Any text value"
    },

    // Number - integers or floats
    "count": {
      "type": "number",
      "required": false,
      "default": 10,
      "description": "Numeric value"
    },

    // Boolean - true/false
    "verbose": {
      "type": "boolean",
      "required": false,
      "default": false,
      "description": "Enable verbose output"
    },

    // Array - list of values
    "tags": {
      "type": "array",
      "required": false,
      "default": ["default-tag"],
      "description": "List of tags"
    },

    // Object - complex structure
    "config": {
      "type": "object",
      "required": false,
      "default": {"key": "value"},
      "description": "Configuration object"
    }
  }
}
```

## Part 5: Testing, Debugging & Validation

### Precise Testing Decision Matrix

| Node Type | Test? | Why | What to Check |
|-----------|-------|-----|---------------|
| MCP nodes | **DEPENDS** | See decision tree above | Actual paths if needed |
| New HTTP API | **DEPENDS** | Only if extracting fields | Response structure |
| Complex jq | **ALWAYS** | Verify extraction logic | Does filter work? Correct output? |
| Shell with pipes | **YES** | Chain might fail | Each pipe stage output |
| Simple shell | **NO** | Predictable output | - |
| File read/write | **NO** | Known interface | - |
| LLM | **NO** | Flexible output | - |
| Known HTTP | **NO** | Structure documented | - |

### MCP Meta-Discovery Process

**Before testing individual MCP tools, always check for helpers:**

```bash
# 1. Find all tools from a service
uv run pflow registry list "slack"

# Returns something like:
# mcp-slack-SEND_MESSAGE
# mcp-slack-FETCH_HISTORY
# mcp-slack-LIST_CHANNELS
# mcp-slack-GET_CHANNEL_INFO  ← Meta tool!

# 2. Use meta tools to understand
uv run pflow registry run mcp-slack-GET_CHANNEL_INFO \
  channel="general"

# 3. Now you know the actual structure for that service
```

### MCP Structure Discovery Process

**Often the documentation says "Output: result (Any)" - here's how to find the ACTUAL structure:**

```bash
# Step 1: Test with minimal real data
# Example for a service called "example-service" and a tool called "get-data"
uv run pflow registry run mcp-example-service-get-data query="test_value"

# Step 2: The output shows the actual structure (pre-filtered for agents, you will only see the output structure, not the data)
# Example output:
✓ Node executed successfully

Execution ID: exec-1763463202-0cd0c8fe # Use this execution ID to read the actual data with the read-fields tool if you REALLY NEED IT

Available template paths (from actual output (4 of 31 shown)): # Smart filtering always applied, no need to use grep/sed/jq to filter the output
✓ ${result.data.items} (list, 11 item)
✓ ${result.data.items[0].id} (str)
✓ ${result.data.items[0].title} (str)
✓ ${result.data.items[0].body} (str)

# Step 3: Copy the exact paths you see
# If output shows: result.data.items
# Then use exactly: ${node.result.data.items} to reference the array or ${node.result.data.items[0].id} to reference the first item's id
```

**Never assume. Always discover.**

### Systematic Debugging Process

#### Phase 1: Identify Error Type

```bash
uv run pflow workflow.json param=value
# Read the error carefully
```

**Error patterns and solutions:**

| Error | Immediate Cause | First Check | Solution |
|-------|----------------|-------------|----------|
| `KeyError: 'messages'` | Wrong path | Trace file for actual structure | Update template path |
| `401 Unauthorized` | Bad token | Settings and env vars | Fix credentials |
| `TypeError: expected string` | Type mismatch | Node output type | Convert or fix source |
| `Connection refused` | Service down | MCP server running? | Start service |
| `Rate limit exceeded` | Too many calls | API limits | Add delays or batch |
| `Template variable not found` | Missing input/output | Inputs and node outputs | Add missing declaration |
| `jq: parse error` | Invalid JSON | Previous node output | Fix JSON or escape properly |

#### Phase 2: Isolate Problem Node

```bash
# Test the specific failing node
uv run pflow registry run failing-node-type \
  param="test_value"

# Check its output structure
```

#### Phase 3: Trace Debugging

```bash
# Find latest trace
ls -lt ~/.pflow/debug/workflow-trace-*.json | head -1

# View timeline
cat ~/.pflow/debug/workflow-trace-*.json | jq '.events[] | {node: .node_id, duration: .duration_ms, error: .error}'

# See what data was available at failure point
cat ~/.pflow/debug/workflow-trace-*.json | jq '.nodes[] | select(.id == "failing-node") | .available_inputs'

# Check actual output of previous node
cat ~/.pflow/debug/workflow-trace-*.json | jq '.nodes[] | select(.id == "previous-node") | .outputs'
```

## Part 6: Workflow Patterns

### Critical Pattern: Extract from Structured Data

**This is the most important pattern. Master it completely.**

**Rule**: If you can describe the PATH, use template variables. Use jq ONLY for transformation/computation. Use LLM only for interpretation.

**❌ WRONG - Using LLM for structured extraction:**
```json
{
  "id": "extract-price",
  "type": "llm",
  "params": {
    "prompt": "Extract the price from this JSON: ${data}"
  }
}
```

**❌ ALSO WRONG - Using jq for simple path extraction:**
```json
{
  "id": "extract-price",
  "type": "shell",
  "params": {
    "stdin": "${data}",
    "command": "jq -r '.items[0].pricing.amount'"  // Unnecessary node!
  }
}
```

**✅ CORRECT - Using template variables:**
```json
{
  "id": "use-price",
  "params": {
    "amount": "${data.items[0].pricing.amount}"  // Direct path, no intermediate node
  }
}
```

**When to use jq (transformation, not extraction):**
```json
{
  "id": "calculate-total",
  "type": "shell",
  "params": {
    "stdin": "${data.items}",
    "command": "jq '[.[].pricing.amount] | add'"  // Computing sum - needs jq
  }
}
```

### Pattern: Multi-Stage Data Pipeline

**Use case**: Fetch → Validate → Transform → Enrich → Deliver

```json
{
  "nodes": [
    {
      "id": "fetch-raw",
      "type": "http",
      "purpose": "Get raw data from API",
      "params": {"url": "${source_url}"}
    },
    {
      "id": "validate-structure",
      "type": "shell",
      "purpose": "Ensure data has required fields",
      "params": {
        "stdin": "${fetch-raw.response}",
        "command": "jq 'if has(\"items\") and has(\"metadata\") then . else error(\"Invalid structure\") end'"
      }
    },
    {
      "id": "transform-data",
      "type": "shell",
      "purpose": "Reshape to our format",
      "params": {
        "stdin": "${validate-structure.stdout}",
        "command": "jq '[.items[] | {id: .id, name: .title, value: .metrics.current}]'"
      }
    },
    {
      "id": "enrich-with-analysis",
      "type": "llm",
      "purpose": "Add insights to data",
      "params": {
        "prompt": "Analyze these metrics and add insights:\n${transform-data.stdout}\n\nFor each item add: trend, risk_level, recommendation"
      }
    },
    {
      "id": "format-for-delivery",
      "type": "llm",
      "purpose": "Format for final output",
      "params": {
        "prompt": "Format this data as a markdown report:\n${enrich-with-analysis.response}\n\nInclude: summary, table, recommendations"
      }
    },
    {
      "id": "deliver",
      "type": "write-file",
      "params": {
        "file_path": "${output_path}",
        "content": "${format-for-delivery.response}"
      }
    }
  ]
}
```

### Pattern: Service Orchestration with Formatting

**Use case**: Multiple services with human-readable output

```json
{
  "nodes": [
    {
      "id": "fetch-service1",
      "type": "mcp-service1-GET_DATA",
      "params": {"resource": "${resource_id}"}
    },
    {
      "id": "fetch-service2",
      "type": "mcp-service2-LIST_ITEMS",
      "params": {"filter": "${filter_criteria}"}
    },
    {
      "id": "combine-data",
      "type": "llm",
      "purpose": "Merge data from multiple sources",
      "params": {
        "prompt": "Combine this data:\n\nService1: ${fetch-service1.result}\n\nService2: ${fetch-service2.result}\n\nCreate unified dataset with cross-references"
      }
    },
    {
      "id": "format-for-display",
      "type": "llm",
      "purpose": "Create human-readable output",
      "params": {
        "prompt": "Format this data as a professional report:\n${combine-data.response}\n\nUse markdown headers, bullet points, and clear sections"
      }
    },
    {
      "id": "send-report",
      "type": "mcp-email-SEND",
      "params": {
        "to": "${recipient_email}",
        "subject": "Data Analysis Report",
        "body": "${format-for-display.response}"
      }
    }
  ]
}
```

### Pattern: Batch Processing with Aggregation

```json
{
  "nodes": [
    {
      "id": "fetch-batch",
      "type": "http",
      "purpose": "Get all items to process",
      "params": {"url": "${batch_url}"}
    },
    {
      "id": "process-all",
      "type": "llm",
      "purpose": "Process entire batch at once",
      "params": {
        "prompt": "Process each item in this batch:\n${fetch-batch.response}\n\nFor each item:\n1. Validate data\n2. Calculate metrics\n3. Generate summary\n\nReturn as JSON array"
      }
    },
    {
      "id": "aggregate-results",
      "type": "shell",
      "purpose": "Calculate batch statistics",
      "params": {
        "stdin": "${process-all.response}",
        "command": "jq '{total: length, successful: [.[] | select(.status == \"success\")] | length, failed: [.[] | select(.status == \"failed\")] | length, avg_score: [.[].score] | add/length}'"
      }
    }
  ]
}
```

## Part 7: Reality Checks & Troubleshooting

### Common Mistakes - Detailed Solutions

#### 1. Skipping workflow discovery
**Impact**: Rebuild existing workflow (30-60 min wasted)
**Fix**: ALWAYS run first, even if user says "create new"
**Check**: First action should be `uv run pflow workflow discover`

#### 2. Not testing MCP outputs
**Impact**: Wrong template paths, failed execution
**Fix**: ALWAYS use `pflow registry run` for MCP
**Example**:
```bash
# Wrong assumption
"${data.messages}"  # Doesn't exist

# After testing
"${result.data.messages}"  # Correct path
```

#### 3. Building everything at once
**Impact**: Debug 20+ nodes simultaneously
**Fix**: Build in phases, test each phase
**Phases**: Core path → External services → Processing → Output

#### 4. Using wrong parameter name
**Impact**: Validation errors
**Fix**: Use `params` not `inputs` for nodes
```json
// ❌ Wrong
{"id": "x", "inputs": {...}}

// ✅ Correct
{"id": "x", "params": {...}}
```

#### 5. Over-specifying parameters
**Impact**: Brittle workflows
**Fix**: Only set what user specified or is required
**Example**: Don't set `temperature` unless user mentioned it

#### 6. Wrong tool for task
**Impact**: Expensive, slow, unreliable
**Fix**: shell+jq for structure, LLM for meaning
**Example**: Extract field with jq, interpret with LLM

#### 7. Missing format step
**Impact**: Raw JSON in user-facing outputs
**Fix**: Add formatting node before delivery
```json
{
  "id": "format-output",
  "type": "llm",
  "params": {
    "prompt": "Format this data for Slack with markdown:\n${data}"
  }
}
```

### Real Request Parsing - Handling Ambiguity

**When user says vague things, make them precise:**

| User Says | Ambiguity | Clarification Approach |
|-----------|-----------|------------------------|
| "recent messages" | How many is recent? | Make input with default: `"limit": {"default": 10}` |
| "process the data" | What data? What processing? | Ask: "What's the data source? What processing do you need?" |
| "send notification" | Where? To whom? | Ask: "Where should notifications go? (email, Slack, etc.)" |
| "fast processing" | How fast? At what cost? | Explain tradeoff: "I can optimize for speed or thoroughness" |
| "handle errors" | How to handle? | Explain: "Workflows can't branch. I can log errors or stop execution" |

**Template for clarification:**
```
I need to clarify a few details:

1. When you say "[ambiguous term]", do you mean:
   □ [Option A with example]
   □ [Option B with example]
   □ Something else?

2. For [missing detail], what should I use:
   □ [Suggested default]
   □ [Alternative]
   □ Your specific value?

3. Should the workflow [implicit assumption]:
   □ Yes, always
   □ No, never
   □ Make it configurable?
```

### MCP/HTTP Reality vs Documentation

**Documentation lies. Testing reveals truth.**

| What Docs Say | What You Get | How to Handle |
|---------------|--------------|---------------|
| `result: Any` | `result.data.tool_response.nested.deeply.value` | Always test structure with regsitry run |
| "Optional parameter" | Actually required or fails | Always provide it |
| "Returns array" | `{"items": [...], "metadata": {...}}` | Access via `.items` |
| "String parameter" | Needs specific format | Test with examples |
| "Async endpoint" | Might support Prefer:wait | Try header first |
| "Returns immediately" | Actually takes 5-10 seconds | Add timeout handling |

### Workflow Smells (Code Smells for Workflows)

**Red flags indicating poor design:**

| Smell | Problem | Fix |
|-------|---------|-----|
| No inputs | Not reusable | Extract all values as inputs |
| 30+ nodes | Too complex | Break into multiple workflows |
| Repetitive nodes | Inefficient | Consolidate operations |
| LLM for extraction | Expensive & unreliable | Use shell+jq |
| Hardcoded credentials | Security risk | Use inputs + settings |
| No output formatting | Poor UX | Add format step |
| Generic names | Hard to discover | Use descriptive names |
| No purpose fields | Hard to understand | Add purpose to every node |

### Reality vs Documentation Summary

**The harsh truths about workflow building:**

| Topic | Documentation Says | Reality | Action |
|-------|-------------------|---------|--------|
| Workflow size | "3-5 nodes typical" | 15-30 nodes common | Build in phases |
| MCP outputs | "result" | 3-5 levels nested | Always test structure |
| Execution time | "Quick" | 3-5 min for complex | Set expectations |
| Template paths | "Simple" | Complex nesting | Test and document |
| Error handling | "Automatic" | Need explicit checks | Add validation nodes |
| Settings | "Available" | Must declare as inputs | Always add to inputs |
| Node discovery | "Finds all" | Might miss some | Try different queries |
| Async ops | "Need polling" | Prefer:wait often works | Try header first |

## Part 8: Quick Reference

### Command Cheat Sheet

```bash
# Discovery & Research
uv run pflow workflow discover "complete user request"     # Find existing workflows
uv run pflow registry discover "all operations needed"      # Find nodes for building
uv run pflow registry describe node1 node2                  # Get node specifications
uv run pflow registry list "keyword1 keyword2"              # List all available nodes

# Testing & Debugging
uv run pflow registry run node-type param=value             # Test node (output pre-filtered for agents)
uv run pflow read-fields exec-id field.path                 # Get actual field values if needed
cat ~/.pflow/debug/workflow-trace-*.json | jq '.'          # Inspect trace (for debugging)

# Workflow Operations
uv run pflow --validate-only workflow.json                  # Check if workflow is valid
uv run pflow workflow.json param1=value1                    # Run workflow from file (while developing)
uv run pflow workflow save workflow-file.json --name workflow-name --description "description"  # Save workflow (when finished developing)

# Settings & Auth
uv run pflow settings set-env KEY_NAME "value"             # Store credential
uv run pflow settings show                                 # View settings
llm keys set provider                                      # Set LLM keys
```

### Template Variable Quick Reference

```
${input_name}                 # Workflow input
${node_id.output}            # Basic node output
${node_id.field.subfield}    # Nested object
${node_id.array[0]}          # Array index
${node_id.array[0].field}    # Array element field
${previous.result.data}      # Can skip nodes
"literal_value"              # No template needed
```

### Decision Quick Reference

**What becomes an input?**
```
User specified it? → YES → Input (unless "always/only")
System constraint? → YES → Hardcode
Would users configure? → YES → Input with default
Otherwise → Hardcode
```

**When to test?**
```
Need specific nested fields? → Test with show_structure
Passing whole result? → Skip testing
Complex extraction? → Test
Simple operations? → Skip
```

**Which tool to use?**
```
Extract nested field? → Template variable ${node.path.to.field}
Transform/compute? → shell+jq
Need meaning? → LLM
File download? → shell+curl
JSON API? → http node
Service-specific? → MCP node
```

### Workflow Naming Convention

Format: `verb-noun-qualifier`
- Examples: `fetch-api-data`, `process-csv-files`, `analyze-github-prs`
- Max 30 chars, lowercase, hyphens only
- Specific enough to find, generic enough to reuse

### Common Agent Mistakes to Avoid

| Mistake | Why It Happens | Prevention |
|---------|----------------|------------|
| **Using Slack as default example** | Document bias from old examples | Rotate between service categories |
| **Using LLM for JSON extraction** | Seems "safer" or more flexible | Trust jq for ALL structured data |
| **Over-testing nodes** | Uncertainty about structure | Test ONLY when accessing specific paths |
| **Creating defensive extraction steps** | Fear of malformed data | Nodes handle parsing automatically |
| **Ignoring workflow discovery** | Eager to build something new | ALWAYS check existing workflows first |
| **Forgetting to save workflow** | Step 12 seems optional | Save is REQUIRED for name-based execution |
| **Hardcoding service names** | Following specific examples | Use category patterns instead |
| **Building all at once** | Want to show complete solution | Build core path first, test, then add |

### Key Success Factors

1. **Always run workflow discovery first** - No exceptions
2. **Understand edges vs templates** - Execution order vs data access
3. **Test only when needed** - Skip if passing whole `${node.result}`
4. **Phase complex workflows** - Build incrementally
5. **Use templates for extraction, jq for transformation** - LLM only for meaning
6. **Every value becomes input** - Unless explicitly "always"
7. **Format user-facing output** - Never show raw JSON
8. **Document actual structures** - Not what docs claim
9. **Handle auth properly** - Inputs + settings
10. **Build general from specific** - One example → universal tool

---

**Final reminder**: Users show you ONE specific example. Your job is to build the GENERAL tool that works for everyone, with every specific value made configurable. When in doubt, make it an input.
