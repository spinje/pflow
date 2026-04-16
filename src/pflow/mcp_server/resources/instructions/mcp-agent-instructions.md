<!-- PART 1 START: Foundation & Mental Model -->
<!-- Covers: Core concepts, edges vs templates, workflow limitations, node selection, development steps 1-8 -->
# pflow Agent Instructions - Complete Guide (MCP Tools)

> **Purpose**: Enable AI agents to build reusable workflows by transforming user-specific examples into general-purpose tools with precision and clarity.
>
> **Interface**: These instructions are for agents using pflow **MCP tools** as their primary interface. CLI commands are referenced for supplementary operations (settings, trace debugging, LLM keys).

## Part 1: Foundation & Mental Model

### Core Mission
You help users build **reusable workflows** - automated sequences that transform data reliably.
- Users describe their need with ONE specific example
- You build a tool that works for ANY similar case
- Every specific value becomes a configurable input
- The workflow runs deterministically every time

### 🎯 Primary Decision Rule + Quick Wins

**THE fundamental decision (saves 50-75% of LLM costs):**
Data transformation → `code` node · External tools/side effects → `shell` node · Interpretation/judgment → `llm` node

**Quick wins (memorize these):**
- **Workflow exists?** → Use it (5 sec vs 10 min to build)
- **Step order = execution order** → No wiring needed, steps run top to bottom
- **Passing `${node.result}` wholesale?** → Skip testing
- **Templates reach any previous step** → No need for pass-through nodes
- **Same operation per item?** → `batch` config (Batch Processing pattern)
- **Need different paths?** → `on-error:` or code node with `next` (Conditional Branching pattern)
- **Keep it simple** → Don't invent requirements or add unnecessary nodes.

### Core Philosophy - Understanding the WHY

**Why pflow exists**: Workflows are executable documentation. You write a `.pflow.md` file that reads like a runbook — prose explains intent, parameters define behavior, code blocks execute. Once built, the workflow runs deterministically forever without AI overhead: same inputs, same outputs, every time.

**Why step order vs templates matter**: Step order defines WHEN nodes run (top to bottom in `## Steps`). Templates define WHAT DATA each node sees (any previous node's output). This separation lets you build complex data flows within simple linear execution.

**Why code/shell over LLM for structured data**: Structured operations should be deterministic. Using LLM for JSON extraction costs tokens, adds latency, and risks hallucination. Code nodes are free, instant, and operate on native objects. Reserve LLM for tasks requiring understanding, not extraction.

**Why test only what you'll use**: Testing every node output wastes time and adds complexity. If you're passing `${node.result}` wholesale to an LLM or service, that component handles any structure. Only investigate structure when you need specific paths like `${node.result.data.items[0].id}`.

**Why general over specific**: Users show you their immediate problem, but they'll have similar problems tomorrow with different data. Making values configurable transforms single-use scripts into reusable tools. Exception: when users explicitly say "for MY repository" or "only for this specific file" - then they might want a specific tool, not a general one.

### 🛑 MANDATORY First Step - Check for Existing Workflows

**This is non-negotiable. Before any other action:**
```python
workflow_discover(query="user's exact request here")
```

**Decision tree based on match score:**
- **≥95% match** → Execute immediately with `workflow_execute()`, you're done
- **80-94% match** → Show user: "Found [name] that does this. Should I use it, modify it, or build new?"
- **70-79% match** → Load workflow, show differences, suggest: "I can modify [name] to do what you need"
- **<70% match** → Continue to build new workflow

**Why this matters**: Building takes 30-60 minutes. Using existing takes 5 seconds.

### Supported Service Categories

MCP servers span these categories (each has unique output structure):
**Data** · **Communication** · **Storage** · **DevOps** · **Productivity** · **APIs**

Examples: Databases (PostgreSQL, MySQL), Chat (Slack, Discord), Cloud (S3, GCS), Version Control (GitHub, GitLab), Docs (Notion, Sheets), REST/GraphQL

**Always test - never assume similarity.**

### Two Fundamental Concepts - Step Order vs Templates

**This distinction causes 80% of workflow rebuilding. Understand it completely.**

#### Concept 1: Execution Order (Step Order)
**Step order defines WHEN nodes run** - strictly sequential, one after another.

```
fetch-data → process-data → save-results
```

**What this means precisely:**
- `process-data` starts ONLY after `fetch-data` completely finishes
- `save-results` starts ONLY after `process-data` completely finishes
- No node can start until its predecessor completes
- By default each node has one successor (next in document order), but conditional branching can override this (see Conditional Branching pattern)
- No parallel execution (use `batch` with `parallel: true` for concurrent operations)

#### Concept 2: Data Access (Templates)
**Templates define WHAT DATA nodes can see** - any node can access any PREVIOUS node's output.

**Critical example showing the difference:**
`````markdown
## Steps

### step1-fetch

Fetch data from the API.

- type: http
- url: ${api_url}

### step2-timestamp

Capture the current date for the report.

- type: shell

```shell command
date +%Y-%m-%d
```

### step3-transform

Extract and reshape items from the API response.

- type: code
- inputs:
    items: ${step1-fetch.response.items}

```python code
items: list

result: list = [{'id': i['id'], 'name': i['title']} for i in items]
```

### step4-analyze

Analyze the transformed data.

- type: llm

```prompt
Analyze this data from ${step3-transform.result} fetched at ${step2-timestamp.stdout}
```

### step5-report

Create a comprehensive report from all previous outputs.

- type: llm

```prompt
Create report:
Raw: ${step1-fetch.response}
Items: ${step3-transform.result}
Analysis: ${step4-analyze.response}
Time: ${step2-timestamp.stdout}
```
`````

**Key insights from this example:**
- `step3-transform` accesses `step1-fetch.response.items` directly (skipping step2)
- `step5-report` accesses ALL previous outputs (step1, step2, step3, step4)
- Edges (step order) only control execution sequence, NOT data availability
- Think of it as: step order creates a timeline, templates access history
- In `.pflow.md`, edges are implicit — steps execute top to bottom in document order

**Data availability at each step:**
| Execution Order | Data Available to This Node |
|-----------------|------------------------------|
| step1-fetch | (none) |
| step2-timestamp | step1-fetch |
| step3-transform | step1-fetch, step2-timestamp |
| step4-analyze | step1-fetch, step2-timestamp, step3-transform |
| step5-report | ALL previous nodes |

This accumulation pattern is fundamental - each node adds to the available data pool.

### Common Misunderstandings About Step Order vs Templates

❌ **Wrong**: "If I put steps A→B→C, then C can only see B's output"
✅ **Right**: C can access A, B, or both. Step order doesn't restrict data access.

❌ **Wrong**: "I have to design steps so each one only uses the previous one's data"
✅ **Right**: Design steps for their purpose. Then in templates, pull data from wherever you need.

❌ **Wrong**: "Templates must follow the step order"
✅ **Right**: Templates can jump over steps. Step order just defines execution sequence.

**Real-world example showing why template jumping matters:**
```
fetch-api → save-raw → extract-fields → format → send-slack

Problem: If templates couldn't jump, 'format' would never see the raw API response
Solution: 'format' uses BOTH ${extract-fields.result} AND ${fetch-api.response}
Result: Formatted output includes both extracted data and original context
```

### What Workflows CANNOT Do (Hard Limits)

**Recognize these immediately and offer alternatives:**

#### ❌ No Loops or Iteration
**User wants**: "Process each file in a directory differently based on its type"
**Why impossible**: Workflows can't create dynamic numbers of operations
**Alternative**: "I'll create a workflow that processes ALL files in one batch operation, applying the same logic to each"
**→ Solution**: `batch` config enables this. See Batch Processing pattern.

#### ✅ Conditional Branching (Supported)
**User wants**: "If the API returns error, handle it; else process data"
**How**: Use `- on-error:` for error routing, or a `code` node with `next: str = "target"` for data-driven decisions. See Conditional Branching pattern below.

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

#### ❌ No Parallel Paths
Conditional branching picks ONE path (not multiple simultaneously). Batch processing handles concurrent operations on multiple items.

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
- **Data transformation** (filter, reshape, merge, compute, string parsing) → `code` node with Python
  - Receives native objects from upstream nodes (no serialization)
  - Supports multiple inputs from different nodes
  - Type-annotated Python code for clarity and validation
- **External tools & side effects** → `shell` node
  - CLI tools: git, curl, docker, ffmpeg, terraform, npm
  - System commands: mkdir, chmod, which
  - Any program where the exit code or side effect is the point
  - Use macOS-compatible (BSD) commands, not GNU-specific extensions
  - Use `$VAR` not `${VAR}` for shell variables (braces conflict with pflow template syntax)
  - **Warning sign**: Long chains of `sed`, `awk`, `jq`, `tr`, `grep` piped together → use `code` node instead (more readable, portable, debuggable)
- **Unstructured data / interpretation** → `llm` node (costs per workflow execution)
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

```python
workflow_discover(query="exact user request, including all details")
```

**Match score actions:**
- **≥95%** → Execute immediately (or ask for missing params)
- **80-94%** → Show differences, ask: use/modify/build?
- **70-79%** → Suggest modifications
- **<70%** → Build new (continue to Step 3)

**Modify existing**: Read `~/.pflow/workflows/[name].pflow.md` → Edit sections → Validate (Step 9)

### Step 3: DISCOVER NODES - Finding Building Blocks

```python
registry_discover(task="[complete description of ALL operations needed]")
```

**Effective task descriptions:**
```python
# ❌ Too vague
registry_discover(task="process data")

# ✅ Complete and specific
registry_discover(task="fetch JSON from REST API, extract specific fields, validate data completeness, transform to CSV format, upload to S3 bucket")
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

#### Phase 2: Test Authentication
```python
# Test with minimal call
registry_run(
    node_type="http",
    parameters={
        "url": "https://api.service.com/health",
        "headers": {"Authorization": "Bearer TOKEN"}
    }
)
```

### Step 5: TEST MCP/HTTP NODES - Precise Testing Criteria

## ⚡ STOP! Don't Test If You're Passing `${node.result}` Wholesale

**If you're doing this, SKIP ALL TESTING:**
```markdown
### analyze

Analyze fetched results.

- type: llm
- prompt: "Analyze: ${fetch.result}"
```
Passing whole `${fetch.result}` = NO TEST NEEDED.

**Only test when you need specific paths like `${node.result.data.items[0].id}`**

**Registry run output is pre-optimized for AI agents:**
- Automatically filtered to show only business-relevant fields (removes noise)
- Shows structure without data values
- **Don't grep/filter the output** - what's displayed is what matters
- Need actual values? Use: `read_fields(execution_id="exec-id", field_paths=["field.path1", "field.path2"])`

**Decision tree for testing:**
```
Is it an MCP node?
├─ YES → Are you unsure what format it accepts OR accessing specific fields?
│        ├─ YES → Test with `registry_run` AND your actual data format
│        └─ NO → Skip testing (just pass ${node.result} to next node)
└─ NO → Is it HTTP with unknown response?
         ├─ YES → Will you extract specific fields?
         │        ├─ YES → Test with real endpoint
         │        └─ NO → Skip testing
         └─ NO → Is it a shell node with complex CLI tool pipelines?
                  ├─ YES → Test pipeline output
                  └─ NO → Skip testing
```

**Key insight**: If you're just passing `${mcp-node.result}` to an LLM or another service, you don't need to know its structure. Only test when you need specific paths like `${mcp-node.result.data.field}` OR when unsure if the node accepts your data format.

**Example - When to test vs skip:**
`````markdown
## Steps

### query-database

Query the database. Skip testing — passing whole result to next node.

- type: mcp-postgres-QUERY
- query: ${sql_query}

### analyze-data

Analyze query results. Whole result = no test needed.

- type: llm
- prompt: "Analyze this data: ${query-database.result}"

### fetch-data

Fetch data from an MCP service. Need testing — accessing specific nested fields.

- type: mcp-slack-GET_CHANNEL
- channel: ${channel_id}

### check-status

Check data status. Specific path `${fetch-data.result.data.status}` = test required.

- type: shell

```shell command
echo 'Status: ${fetch-data.result.data.status}'
```
`````

**MCP Testing Protocol:**
```python
# 1. Inform user (conceptually)
# "I need to test access to [service]. This will [describe effect]."

# 2. Ask permission if side effects
# If has_side_effects: "⚠️ This test will [visible effect]. Should I proceed?"

# 3. Test with structure discovery AND format compatibility
registry_run(
    node_type="mcp-{mcp-service-name}-{mcp-tool-name}",
    parameters={"param1": "your_actual_format_here"}
)

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
```python
registry_run(node_type="mcp-service-TOOL", parameters={"param": "value"})
```

### Step 6: DESIGN - Data Flow Mapping

**Create a precise execution plan:**

```
Execution Order (Step Order):
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

⚠️ **CRITICAL: Development Format**

Workflows are `.pflow.md` files using standard markdown structure:

````markdown
# Workflow Title

Description of what the workflow does (becomes the workflow description on save).

## Inputs

### input_name

Description of this input.

- type: string
- required: true

## Steps

### step-name

Description of what this step does.

- type: node-type
- param: value

## Outputs

### output_name

Description of this output.

- source: ${step-name.result}
````

**Key rules:**
- `## Inputs` and `## Outputs` are optional. `## Steps` is required (at least one node).
- Execution order = document order. No explicit edges needed.
- Every entity (`###` heading) must have a prose description.
- Use `-` for parameters, `*` for documentation bullets.
- Code blocks use tags: ` ```shell command `, ` ```python code `, ` ```prompt `, ` ```yaml output_schema `
- Batch config: inline `- batch:` for simple cases, ` ```yaml batch ` code block for complex inline arrays

**Development workflow**: Write `.pflow.md` file to disk, then test with `workflow_execute`. Save to library when it works.

> **File paths vs raw content**: Always use file paths when possible (`workflow_execute(workflow="./my-workflow.pflow.md")`). Only pass raw markdown content when the agent runs on a different machine from where pflow is installed (cloud, sandbox) — in that case, see `pflow://instructions/sandbox`.

---

#### Phase-Based Building for Complex Workflows

**When to phase (based on complexity, not count):**
- Multiple external services (even if only 5 nodes)
- Unknown API responses that need testing
- Complex data transformations with dependencies
- First time using certain nodes
- More than 15 nodes IF they're complex (20 simple shell commands might not need phasing)

**Phase 1: Core Data Path (Test Immediately)**
`````markdown
# Phase 1 Test

Core data path test.

## Inputs

### source_url

Data source URL.

- type: string
- required: true

## Steps

### fetch

Fetch raw data from the source.

- type: http
- url: ${source_url}

### test-output

Write fetched data to disk for inspection.

- type: write-file
- file_path: /tmp/test.json
- content: ${fetch.response.data}
`````

**Test before continuing:**
```python
# Run directly from file path during development
workflow_execute(
    workflow="phase1.pflow.md",
    parameters={"source_url": "https://api.example.com/data"}
)
# Verify: Is ${fetch.response.data} the structure you expected?
```

**Phase 2: Add Processing (One Service at a Time)**
````markdown
### process

Analyze fetched data and extract key insights.

- type: llm

```prompt
Analyze this data and extract key insights:
${fetch.response.data}
```
````

**Phase 3: Add External Services**
```markdown
### send-notification

Send analysis results to the team channel.

- type: mcp-slack-send
- channel: ${notification_channel}
- text: ${process.response}
```

**Phase 4: Polish and Outputs**
```markdown
## Outputs

### analysis

Analysis results from the LLM processing step.

- source: ${process.response}
```

#### Iteration is Free

pflow caches node outputs automatically. When you edit a prompt or parameter and re-run, only the changed node and its downstream re-execute. Use this:

- Edit a prompt file → re-run → only affected nodes execute (~seconds, not minutes)
- `--only <node>` → run just that node (upstream cached, downstream skipped)
- `--no-cache` → force everything fresh (side-effect nodes, external API changes)

<!-- PART 2 START: Building Workflows -->
<!-- Covers: Input declaration, node creation patterns, validation, testing, saving workflows, technical reference -->
#### Input Declaration - Complete Rules

**Decision process for EVERY value:**

```
Is this value in the user's request?
├─ YES → Is it marked with "always" or "only"?
│        ├─ YES → Hardcode it
│        └─ NO → Make it an input
└─ NO → Is it implementation detail (prompt, Python code, shell command)?
         ├─ YES → Hardcode it (users don't customize implementation)
         └─ NO → Is it a system constraint?
                  ├─ YES → Hardcode it
                  └─ NO → Would users want to configure this?
                           ├─ YES → Make it an input with default
                           └─ NO → Hardcode it
```

**Key insight**: LLM prompts, Python code, and shell commands are HOW the workflow works, not WHAT it processes. These stay hardcoded unless the user specifically asks to customize them.

**Input examples with rationale:**
```markdown
## Inputs

### api_endpoint

API URL to fetch data from. User-specified value — always an input.

- type: string
- required: true

### limit

Maximum items to process. User mentioned but with sensible default.

- type: number
- required: false
- default: 10

### output_format

Output format (json, csv, xml). Not mentioned but configurable.

- type: string
- required: false
- default: "json"

### tags

Tags to filter by. Array input example.

- type: array
- required: false
- default: ["important"]

### options

Processing options. Object input example.

- type: object
- required: false
- default: {"verbose": false}
```

#### Node Creation - Complete Patterns

`````markdown
## Steps

### fetch-with-auth

Fetch data from protected API with authentication.

- type: http
- url: ${api_url}
- method: POST
- headers:
    Authorization: Bearer ${api_token}
    Content-Type: application/json
    Accept: application/json
- body:
    query: ${search_query}
    limit: ${limit}

### list-recent-files

List recently modified files. Note: `$var` = shell variable, `${var}` = pflow template.

- type: shell

```shell command
find . -maxdepth ${depth} -type f -newer /tmp/marker 2>/dev/null | head -20
```

### filter-and-reshape

Filter active items and reshape for downstream processing.
Templates go in `inputs`, Python code in the code block.
All inputs and result MUST have type annotations.

- type: code
- inputs:
    items: ${fetch-with-auth.response.data.items}

```python code
items: list

result: list = [
    {'id': i['id'], 'name': i['name'], 'value': i['metrics']['value']}
    for i in items
    if i['status'] == 'active'
]
```

### merge-data

Merge and summarize data from two sources.
Downstream nodes access fields: `${merge-data.result.summary}`, `${merge-data.result.count}`.

- type: code
- inputs:
    api_data: ${fetch-with-auth.response.data.items}
    db_records: ${query-db.result}

```python code
api_data: list
db_records: list

merged = api_data + db_records
result: dict = {
    'items': merged,
    'count': len(merged),
    'summary': f'{len(api_data)} from API, {len(db_records)} from DB'
}
```

### structured-analysis

Analyze data with specific criteria.

- type: llm
- temperature: 0.7
- model: gpt-4

```yaml output_schema
type: object
properties:
  findings:
    type: array
    items:
      type: string
  risk_level:
    type: string
  recommendation:
    type: string
required:
  - findings
  - risk_level
  - recommendation
```

```prompt
Analyze this data according to these criteria:

Data:
${filter-and-reshape.result}

Criteria:
1. Identify patterns
2. Find anomalies
3. Suggest improvements
```

### update-service

Update external service with results.

- type: mcp-service-UPDATE
- resource_id: ${resource_id}

```yaml data
status: completed
results: ${structured-analysis.response}
timestamp: ${get-timestamp.stdout}
metadata:
  source: ${api_url}
  processed_count: ${limit}
```
`````

⚠️ **Code node rules:**
- Templates go in `- inputs:` param, NEVER in the `python code` block (code is literal Python, not a template)
- All inputs and `result` MUST have type annotations: `data: list`, `result: dict = ...`
- Upstream JSON is auto-parsed before your code runs — if source is JSON, declare `dict`/`list` not `str`
- Use `object` as type when you don't know the type (skips validation)
- Single output via `result` variable — use dict for structured output
- Downstream access: `${node.result}` or `${node.result.field}` for dict results

### Step 9: TEST - Systematic Testing

**Development loop: edit file → run with workflow_execute → debug → repeat until working**
Validation runs automatically before every execution — no separate validation step needed.

```python
# Run directly from file path during development (no saving needed)
workflow_execute(
    workflow="workflow.pflow.md",
    parameters={"param1": "value1", "param2": "value2", "limit": 2}
)
```

Keep iterating on the `.pflow.md` file until the workflow executes successfully. Do NOT save until it works.

**Trace files**: `~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json` — saved automatically every run. Use `--report` to generate a readable execution report, or `pflow report` post-hoc.

### Step 10: SAVE - Make It Executable by Name (Final Step)

⚠️ **Only do this AFTER your workflow runs successfully from the file path in Step 9.**

**Your workflow currently works with:**
```python
workflow_execute(workflow="/path/to/workflow.pflow.md", parameters={"param": "value"})  # ✅ Works but requires full path
```

**To make it work with just a name (REQUIRED for reusability):**
```python
workflow_execute(workflow="workflow-name", parameters={"param": "value"})  # ❌ Won't work until you save it!
```

**⚡ You MUST use the save tool - this is NOT optional:**

```python
workflow_save(
    workflow="./path/to/your-workflow.pflow.md",
    name="workflow-name"
)
```

**What this does:**
- Adds frontmatter metadata for execution by name
- Saves to workflow library (`~/.pflow/workflows/`)
- Makes the workflow reusable across projects
- Description is extracted from the `#` title prose in your `.pflow.md` file

**Example:**
```python
# Save your tested workflow
workflow_save(
    workflow="./api-processor.pflow.md",
    name="api-data-processor"
)

# Now you can execute by name from anywhere
workflow_execute(
    workflow="api-data-processor",
    parameters={
        "api_url": "https://api.example.com/data",
        "limit": 100
    }
)
```

**After saving, always show usage examples:**
```python
# Original use case
workflow_execute(
    workflow="api-data-processor",
    parameters={
        "api_url": "https://api.example.com/data",
        "limit": 100,
        "output_format": "json"
    }
)

# Different use case showing reusability
workflow_execute(
    workflow="api-data-processor",
    parameters={
        "api_url": "https://different-api.com/records",
        "limit": 50,
        "output_format": "csv"
    }
)
```

🚫 **DO NOT manually copy to `~/.pflow/workflows/`** - Always use the save tool.

## Part 4: Building Workflows - Technical Reference

**Before building, verify**: Discovered workflows (Step 2) · Discovered nodes (Step 3) · Tested MCP nodes (Step 5) · Designed flow (Step 6)

### Authentication Setup

#### Setting Up Credentials

**For API tokens:**
```bash
# User stores in settings (CLI command — settings MCP tools are disabled)
pflow settings set-env SERVICE_API_TOKEN "sk-abc123..."
pflow settings set-env GITHUB_TOKEN "ghp_xyz789..."

# Verify storage
pflow settings show
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
```markdown
### api_token

API authentication token.

- type: string
- required: true
```
Example of using in nodes: `- Authorization: Bearer ${api_token}` (in headers)

### Workflow Structure Complete Reference

`````markdown
# Workflow Title

Description of the workflow. This becomes the description shown in `workflow_list()`.

## Inputs

### param_name

What this parameter is for.

- type: string
- required: true
- default: "value"
- stdin: true

## Steps

### descriptive-name

What this step does and why.

- type: node-type-from-registry
- param1: static_value
- param2: ${input_name}
- param3: ${other_node.output}

## Outputs

### result_name

What this output contains.

- source: ${final_node.output}
`````

**Input fields**: `type` (string|number|boolean|array|object), `required` (true|false), `default` (only when required: false), `stdin` (true|false -- only one input can have this), description as prose.

**Output fields**: `source` (template expression like `${node.key}`), `type` (optional hint), `stdout` (true|false -- at most one output may set this; marks the output that streams to stdout in text mode). Single-output workflows don't need a marker. Multi-output workflows without a marker stream the first declared output and emit a stderr warning.

**Node fields**: `type` (required), all other params as `- key: value`. Code/prompts/batch go in tagged code blocks.

**Execution order**: Top to bottom in `## Steps`. No explicit edges.

**Outputs**: Optional -- skip for automation workflows (send, post, update).

### Template Variable Complete Reference

#### Resolution Order (This Matters)
1. Check workflow `inputs` first
2. Then check previous node outputs (in execution order)
3. Error if not found

#### Critical: Automatic JSON Parsing for Simple Templates

**Simple templates (`${var}`) automatically parse JSON strings.** This enables direct data access without intermediate extraction steps.

**Two contexts where auto-parsing occurs:**

1. **Path traversal**: `${node.stdout.field}` parses JSON to access nested properties
2. **Inline objects**: `{"data": "${node.stdout}"}` parses JSON for structured data composition

**What gets parsed:**
- All JSON types: objects `{}`, arrays `[]`, numbers, booleans, strings, null
- Shell **stdout** with trailing `\n` is automatically stripped (disable with `strip_newline: false`). stderr is never modified.
- Plain text and invalid JSON gracefully stay as strings

**Concrete examples** (inline object context):
| Template | Source value | After resolution |
|----------|--------------|------------------|
| `{"data": "${shell.stdout}"}` | `'{"items": [1,2,3]}\n'` | `{"data": {"items": [1,2,3]}}` |
| `{"resp": "${http.response}"}` | `'{"status": "ok"}'` | `{"resp": {"status": "ok"}}` |
| `{"items": "${mcp-node.result}"}` | `'[{"id": 1}, {"id": 2}]'` | `{"items": [{"id": 1}, {"id": 2}]}` |
| `{"config": "${read-file.content}"}` | `'{"debug": true}'` | `{"config": {"debug": true}}` |
| `{"count": "${shell-node.stdout}"}` | `'42\n'` | `{"count": 42}` |
| `{"valid": "${check.stdout}"}` | `'true'` | `{"valid": true}` |
| `{"text": "${any.output}"}` | `'plain text'` | `{"text": "plain text"}` |

**Escape Hatch** (force raw string):
Complex templates bypass parsing:
```yaml
# Auto-parsed (simple template):
- data: ${json_var}

# NOT parsed (complex templates):
- data: "${json_var} "        # Trailing space
- data: "'${json_var}'"       # Wrapped in quotes
- data: "raw: ${json_var}"    # Has prefix
```

**The Anti-Pattern to Avoid:**

```markdown
### extract-first

❌ WRONG — Unnecessary extraction before LLM.

- type: shell
- stdin: ${http-fetch.response}
- command: jq '.'

### analyze

❌ Extra step for nothing.

- type: llm
- prompt: "Analyze: ${extract-first.stdout}"
```

```markdown
### analyze

✅ RIGHT — Pass directly to LLM.

- type: llm
- prompt: "Analyze: ${http-fetch.response}"
```

````markdown
### process

✅ RIGHT — Combine and transform multiple sources with code node.

- type: code
- inputs:
    api_data: ${http-fetch.response}
    db_records: ${mcp-postgres.result}
    local_config: ${read-config.content}

```python code
api_data: dict
db_records: list
local_config: dict

result: list = api_data['items'] + db_records
```
````

#### Automatic JSON Serialization for String-Typed Parameters

Objects in `str`-typed params auto-serialize to JSON strings with proper escaping. Always use object syntax—never manually construct JSON strings.

```yaml
# ✅ Object syntax - auto-serializes with proper escaping
- request_body:
    query: ${user_input}
    limit: 10
# Result: '{"query": "Hello \"world\"\\nLine 2", "limit": 10}'

# ❌ String syntax - breaks on quotes/newlines
- request_body: '{"query": "${user_input}"}'
```

Works with or without template variables. Handles nested objects and arrays.

#### Transformation Complexity Checklist

**Before adding processing steps:**

1. **Can the source produce cleaner output?**
   - LLM: Use `output_schema` (JSON Schema in a `yaml output_schema` code block) — guarantees valid JSON via constrained decoding, response stored as dict
   - HTTP: Check if API has a `format=json` parameter
   - **If yes → Fix at source instead of adding nodes**

2. **Are you solving a real problem or preventing an imaginary one?**
   - ✅ Real: "Parse error when running" → Add transformation
   - ❌ Imaginary: "Might fail, better be safe" → Don't add
   - **Test first. Transform only if test fails.**

**The golden rule:** Every transformation step must solve a verified problem, not prevent a hypothetical one.

#### Extraction vs Transformation: Decision Rule

**Extraction (getting data) → Templates**
**Transformation (changing data) → code node**
**Interpretation (creative decisions) → LLM**

```
Need data at specific path? → ${node.result.data.items[0].name}
Need to compute/transform?  → code node
Need to combine/append?     → code node or templates
Need to interpret meaning?  → LLM
```

**⚠️ The LLM test**: Can you write a deterministic algorithm for it?
- **YES** (fixed structure, no creative decisions) → code/shell/templates, NOT LLM
- **NO** (requires judgment: what to emphasize, summarize, what matters) → LLM

| Task | Deterministic? | Use |
|------|----------------|-----|
| "Append section X to document" | YES - fixed structure | code node |
| "Combine A and B into report" | YES - concatenation | code node |
| "Create summary of this data" | NO - deciding importance | LLM |
| "Format for human readability" | DEPENDS - see below | ? |

**"Format" is ambiguous** - ask: is the output structure fixed?
- "Add markdown headers and bullet points" → YES, deterministic → code node
- "Format as professional report" → NO, requires judgment → LLM

Common mistake: Using LLM for extraction creates unnecessary nodes. Templates handle all path traversal automatically.

#### All Template Patterns

Templates work in any param value — inline `- key:` or code blocks:

```markdown
### example-node

- basic_input: ${username}
- basic_output: ${fetch.response}
- nested: ${fetch.data.user.email}
- first_item: ${fetch.items[0]}
- specific_field: ${fetch.items[0].name}
- by_input: ${fetch.items[${choice}]}
- combined: "User ${username} data: ${fetch.response}"
- deep: ${fetch.result.data.users[0].profile.settings.email}
- method: POST
- static_value: 123
```

**Structured objects** — inline nesting or code block:

```markdown
### fetch-with-auth

- type: http
- url: ${api_url}
- method: POST
- headers:
    Authorization: Bearer ${api_token}
    Content-Type: application/json
- body:
    query: ${search_query}
    limit: ${limit}
```

**When nesting gets deep** (objects within objects), use a `yaml param_name` code block for clarity:

````markdown
### update-record

- type: http
- url: ${api_url}
- method: POST

```yaml body
query: ${search_query}
filters:
  status: active
  tags:
    - ${primary_tag}
    - ${secondary_tag}
  metadata:
    source: ${source_name}
    priority: high
```
````

**Guideline**: Inline `- key: value` for flat params and simple nesting. `yaml param_name` code block for deep nesting or batch config. Both produce identical results.

**In shell commands** — pflow variables resolve before the shell runs. Use a code block for multi-line or complex commands:

````markdown
### run-pipeline

- type: shell

```shell command
mkdir -p ${output_dir}/images && curl -s ${api_url}/items?limit=${limit}
```
````

#### Debugging Template Errors

**Error: `Unresolved variables in parameter 'prompt': ${fetch.result.messages}`**

Debug process:
```bash
# 1. Generate an execution report — it includes fix suggestions for template errors
pflow report

# The summary.md Errors section will show:
#   - **format-output** (LLMNode): Unresolved variables in parameter 'prompt': ${fetch.result.messages}
#     - Suggestion: `${fetch.result.messages}`: key `messages` not found at `fetch.result`. Available keys: `issues`, `total_count`

# 2. Or check the upstream node's report file directly
cat ~/.pflow/reports/my-workflow/01-fetch.md
# Shows the full output structure — find the correct field name there

# 3. Fix template path
# Wrong: ${fetch.result.messages}
# Right: ${fetch.result.issues}
```

### Parameter Types - Complete Guide

```markdown
## Inputs

### text_input

Any text value. String is the most common type.

- type: string
- required: true

### count

Numeric value — integers or floats.

- type: number
- required: false
- default: 10

### verbose

Enable verbose output. Boolean — true/false.

- type: boolean
- required: false
- default: false

### tags

List of tags. Array input.

- type: array
- required: false
- default: ["default-tag"]

### config

Configuration object. Complex structure.

- type: object
- required: false
- default: {"key": "value"}

### data

Data from stdin or CLI. Receives piped input (e.g., `cat data.json | pflow workflow.pflow.md`).

- type: string
- required: true
- stdin: true
```

<!-- PART 3 START: Testing & Reference -->
<!-- Covers: Testing, debugging, workflow patterns, troubleshooting, quick reference cheat sheets -->
## Part 5: Testing, Debugging & Validation

### Precise Testing Decision Matrix

| Node Type | Test? | Why | What to Check |
|-----------|-------|-----|---------------|
| MCP nodes | **DEPENDS** | See decision tree above | Actual paths if needed |
| New HTTP API | **DEPENDS** | Only if extracting fields | Response structure |
| Code node | **NO** | Python errors are clear and actionable | - |
| Shell (CLI pipelines) | **YES** | Chain might fail | Each pipe stage output |
| Simple shell | **NO** | Predictable output | - |
| File read/write | **NO** | Known interface | - |
| LLM | **NO** | Flexible output | - |
| Known HTTP | **NO** | Structure documented | - |

**Testing shell pipelines independently:**
When building shell commands with piped CLI tools (e.g., git log | head, curl | grep), test the complete pipeline outside pflow first:
```bash
# Test with actual data source before integrating:
curl -s "https://example.com/api" | head -20

# Once verified, integrate into workflow
```

**Pipeline exit codes**: Only the last command's exit code is captured. In `grep | sed`, if sed fails you see sed's stderr, but can't tell if grep found matches or not.

### MCP Meta-Discovery Process

**Before testing individual MCP tools, always check for helpers:**

```python
# 1. Find all tools from a service
registry_list(filter_pattern="slack")

# Returns something like:
# mcp-slack-SEND_MESSAGE
# mcp-slack-FETCH_HISTORY
# mcp-slack-LIST_CHANNELS
# mcp-slack-GET_CHANNEL_INFO  ← Meta tool!

# 2. Use meta tools to understand
registry_run(
    node_type="mcp-slack-GET_CHANNEL_INFO",
    parameters={"channel": "general"}
)

# 3. Now you know the actual structure for that service
```

### MCP Structure Discovery Process

**Often the documentation says "Output: result (Any)" - here's how to find the ACTUAL structure:**

```python
# Step 1: Test with minimal real data
# Example for a service called "example-service" and a tool called "get-data"
registry_run(
    node_type="mcp-example-service-get-data",
    parameters={"query": "test_value"}
)

# Step 2: The output shows the actual structure (pre-filtered for agents, you will only see the output structure, not the data)
# Example output:
# ✓ Node executed successfully
#
# Execution ID: exec-1763463202-0cd0c8fe  # Use this to read actual data with read_fields if you REALLY NEED IT
#
# Available template paths (from actual output (4 of 31 shown)):  # Smart filtering always applied
# ✓ ${result.data.items} (list, 11 item)
# ✓ ${result.data.items[0].id} (str)
# ✓ ${result.data.items[0].title} (str)
# ✓ ${result.data.items[0].body} (str)

# Step 3: Copy the exact paths you see
# If output shows: result.data.items
# Then use exactly: ${node.result.data.items} to reference the array or ${node.result.data.items[0].id} to reference the first item's id

# Step 4 (optional): Read actual values if needed
read_fields(
    execution_id="exec-1763463202-0cd0c8fe",
    field_paths=["result.data.items[0].title", "result.data.items[0].id"]
)
```

**Never assume. Always discover.**

### Systematic Debugging Process

#### Phase 1: Identify Error Type

```python
workflow_execute(workflow="workflow.pflow.md", parameters={"param": "value"})
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

```python
# Test the specific failing node
registry_run(
    node_type="failing-node-type",
    parameters={"param": "test_value"}
)

# Check its output structure
```

#### Phase 3: Trace Debugging

```bash
# Generate an execution report (directory of markdown files — one per node)
pflow workflow.pflow.md --report

# Or generate a report from the most recent trace
pflow report

# The report includes:
# - summary.md: pipeline table with cost, errors section with fix suggestions, anomaly warnings
# - Per-node .md files: rendered prompts, responses, metadata (model, tokens, cost)
# - Batch items: per-item files with individual prompts/responses
# - Sub-workflows: nested directories mirroring workflow structure
```

## Part 6: Workflow Patterns

### Critical Pattern: Extract from Structured Data

**This is the most important pattern. Master it completely.**

**Rule**: If you can describe the PATH, use template variables. Use code node for transformation/computation. Use LLM only for interpretation.

**❌ WRONG - Using LLM for structured extraction:**
```markdown
### extract-price

- type: llm
- prompt: "Extract the price from this JSON: ${data}"
```

**❌ ALSO WRONG - Using jq for simple path extraction:**
```markdown
### extract-price

- type: shell
- stdin: ${data}
- command: jq -r '.items[0].pricing.amount'
```
Unnecessary node!

**✅ CORRECT - Using template variables:**
```yaml
# Direct path, no intermediate node needed:
- amount: ${data.items[0].pricing.amount}
```

**When to use code node (transformation, not extraction):**
````markdown
### calculate-total

Compute sum of all pricing amounts.

- type: code
- inputs:
    items: ${data.items}

```python code
items: list

result: float = sum(i['pricing']['amount'] for i in items)
```
````

### Pattern: Multi-Stage Data Pipeline

**Use case**: Fetch → Validate → Transform → Enrich → Deliver

`````markdown
## Steps

### fetch-raw

Get raw data from API.

- type: http
- url: ${source_url}

### validate-structure

Ensure data has required fields before processing.

- type: code
- inputs:
    data: ${fetch-raw.response}

```python code
data: dict

if 'items' not in data or 'metadata' not in data:
    raise ValueError('Invalid structure: missing items or metadata')
result: dict = data
```

### transform-data

Reshape API items to our internal format.

- type: code
- inputs:
    items: ${validate-structure.result.items}

```python code
items: list

result: list = [
    {'id': i['id'], 'name': i['title'], 'value': i['metrics']['current']}
    for i in items
]
```

### enrich-with-analysis

Add insights to each item using LLM batch processing.

- type: llm
- batch:
    items: ${transform-data.result}
    parallel: true

```prompt
Analyze this metric and add insights:
${item}

Provide: trend, risk_level, recommendation
```

### format-for-delivery

Format enriched data as a markdown report.

- type: llm

```prompt
Format this data as a markdown report:
${enrich-with-analysis.results}

Include: summary, table, recommendations
```

### deliver

Write the final report to disk.

- type: write-file
- file_path: ${output_path}
- content: ${format-for-delivery.response}
`````

### Pattern: Service Orchestration with Formatting

**Use case**: Multiple services with human-readable output

`````markdown
## Steps

### fetch-service1

Query primary data source.

- type: mcp-service1-GET_DATA
- resource: ${resource_id}

### fetch-service2

List items from secondary source.

- type: mcp-service2-LIST_ITEMS
- filter: ${filter_criteria}

### analyze-and-format

Find relationships between datasets and format as report. One LLM call for both analysis and formatting.

- type: llm

````prompt
Analyze these two datasets and identify cross-references:

Service1: ${fetch-service1.result}

Service2: ${fetch-service2.result}

Find relationships, correlations, and connections. Format as a professional report with markdown headers and sections.
````

### send-report

Email the analysis report to the recipient.

- type: mcp-email-SEND
- to: ${recipient_email}
- subject: Data Analysis Report
- body: ${analyze-and-format.response}
`````

**Note**: `analyze-and-format` combines analysis and formatting in one LLM call - don't use separate LLM nodes when one can do both. If you just need to concatenate data with a fixed structure, use code node or templates instead.

### Pattern: Batch Processing

Same operation × N items ("each", "for each", "in parallel" → batch, not single LLM). Add `batch` to any node:

````markdown
### process-each

Analyze each file.

- type: llm
- prompt: "Analyze: ${item}"
- batch:
    items: ${source.files}

### fetch-each

Fetch each URL in parallel.

- type: shell
- batch:
    items: ${urls}
    parallel: true
    max_concurrent: 40

```shell command
curl -s '${item}'
```
````

Current item: `${item}` (or custom `as`). Index: `${__index__}` (0-based). Results: `${node.results}` (array in input order).

**Options**:
| Field | Default | Notes |
|-------|---------|-------|
| `items` | required | Template reference OR inline array (must resolve to JSON array, not newline-separated string) |
| `as` | `"item"` | Custom name: `"file"` → `${file}` |
| `parallel` | `false` | Concurrent execution |
| `max_concurrent` | `10` | 1-100; use 20-40 for LLM APIs (rate limits) |
| `error_handling` | `"fail_fast"` | `"continue"` = process all despite errors |

**Text lines → JSON array:**
```shell
your-command | jq -R -s 'split("\n") | map(select(. != ""))'
```

**All outputs**: `${node.results}`, `.count`, `.success_count`, `.error_count`, `.errors`
Results contains only **successful** items. Each result contains `item` (original input) + inner node outputs, making results self-contained for downstream processing (e.g., `${node.results}` passed to LLM includes both inputs and outputs). With `error_handling: continue`, failed items are excluded from `results` — error details are in `errors`. `count` = total items attempted, `success_count` = `len(results)`, `error_count` = `len(errors)`.

**Inline array pattern** (parallel independent operations):
Batch is the way to run operations concurrently (conditional branching picks ONE path, not multiple).
````markdown
### multi-format

Reformat the report in multiple styles concurrently.

- type: llm
- prompt: "Reformat as ${item.style}:\n${item.content}"

```yaml batch
items:
  - style: executive-summary
    content: ${report.result}
  - style: technical-details
    content: ${report.result}
  - style: action-items
    content: ${report.result}
parallel: true
```
````
**Completely different operations** (each item defines its own prompt and data):
````markdown
### parallel-tasks

Run completely different operations in parallel.

- type: llm
- prompt: ${item.prompt}

```yaml batch
items:
  - prompt: "Summarize in 2 sentences: ${data}"
  - prompt: "Extract action items from: ${data}"
  - prompt: "Translate to Spanish: ${other-data}"
parallel: true
```
````
Each runs independently: `${parallel-tasks.results[0].response}`, `${parallel-tasks.results[0].item}` (original input)

**Dynamic indexing**: `${__index__}` gives current position (0-based). Use nested templates to correlate (requires `fail_fast` — not supported with `error_handling: continue`):
```
${previous.results[${__index__}]}     # Access by position (fail_fast only)
${previous.results[${item.idx}]}      # Access by item field (fail_fast only)
```

**Using results**:
```markdown
### report

- type: llm
- prompt: "Summary of ${process-each.success_count} items:\n${process-each.results}"
```

### Pattern: Conditional Branching

Route execution based on data or errors. Default flow is top-to-bottom; branching overrides it.

**Error routing** — any node can route failures to a handler:
````markdown
### call-api

Fetch data from the API.

- type: shell
- on-error: handle-error

```shell command
curl -f https://api.example.com/data
```

### process

Process the result.

- type: code
- inputs: { data: "${call-api.stdout}" }
- next: end

```python code
data: str
result: dict = {"processed": True}
```

### handle-error

Log the failure.

- type: shell
- next: end

```shell command
echo "API call failed" >&2
```
````

**Data-driven routing (literal)** — a `code` node sets `next` to pick the path. When all targets are string literals, pflow detects them automatically:
````markdown
### classify

Route based on input size.

- type: code
- inputs: { items: "${fetch.result}" }

```python code
items: list
result: int = len(items)
if len(items) > 100:
    next: str = "bulk-process"
else:
    next: str = "simple-process"
```

### simple-process

Handle small batches.

- type: shell
- next: end

```shell command
echo "Small batch: ${classify.result} items"
```

### bulk-process

Handle large batches.

- type: shell
- next: end

```shell command
echo "Large batch: ${classify.result} items"
```
````

**Data-driven routing (dynamic)** — when the target comes from a variable, declare all possible targets with `- next:`:
````markdown
### route

Pick path based on category.

- type: code
- inputs: { category: "${analyze.result}" }
- next: path-a, path-b

```python code
category: str
result: str = category
next: str = category
```

### path-a

Handle category A.

- type: shell
- next: end

```shell command
echo "A: ${route.result}"
```

### path-b

Handle category B.

- type: shell
- next: end

```shell command
echo "B: ${route.result}"
```
````

**Routing rules:**
- `- next: node-id` — override default successor (any node)
- `- next: end` — terminate flow (no successor)
- `- on-error: node-id` — route on failure (any node)
- `next: str = "node-id"` — dynamic routing (code nodes only)
- No `next` set in code → continues to next node in document order

**Required: Branch targets MUST have explicit `- next:`**
- Every node reached via `- on-error:` or named routing action MUST declare `- next: end` or `- next: <node-id>`
- Without this, branches fall through to the next node in document order (silent bug)
- If code uses dynamic routing (`next = variable`), the code node MUST declare `- next: target-a, target-b` listing all possible targets
- Literal routing (`next: str = "target"`) does NOT need `- next:` on the code node — pflow detects targets automatically

**When to use**: Error handling, classification/routing, skip-ahead, retry loops. NOT for parallel execution (use batch for that).

## Part 7: Reality Checks & Troubleshooting

### Common Mistakes - Detailed Solutions

#### 1. Skipping workflow discovery
**Impact**: Rebuild existing workflow (30-60 min wasted)
**Fix**: ALWAYS run first, even if user says "create new"
**Check**: First action should be `workflow_discover()`

#### 2. Not testing MCP outputs
**Impact**: Wrong template paths, failed execution
**Fix**: ALWAYS use `registry_run()` for MCP
**Example**:
```python
# Wrong assumption
"${data.messages}"  # Doesn't exist

# After testing
"${result.data.messages}"  # Correct path
```

#### 3. Building everything at once
**Impact**: Debug 20+ nodes simultaneously
**Fix**: Build in phases, test each phase
**Phases**: Core path → External services → Processing → Output

#### 4. Putting templates in code blocks instead of inputs (code nodes)
**Impact**: Template syntax in Python code causes parse errors
**Fix**: Templates go in `- inputs:` parameter, code block is literal Python
```markdown
### transform

- type: code
- inputs:
    data: ${fetch.result}
```
Never put `${...}` inside a `python code` block — it's literal Python, not a template.

#### 5. Over-specifying parameters
**Impact**: Brittle workflows
**Fix**: Only set what user specified or is required
**Example**: Don't set `temperature` unless user mentioned it

#### 6. Wrong tool for task
**Impact**: Expensive, slow, unreliable
**Fix**: Templates for extraction, code node for transformation, LLM for meaning
**Example**: `${node.data.field}` to extract, code node to filter/reshape, LLM to interpret

#### 7. Missing format step
**Impact**: Raw JSON in user-facing outputs
**Fix**: Add formatting node before delivery - but choose the right tool:
- **Fixed structure** (headers, bullets, tables with known columns) → code node
- **Requires judgment** (what to emphasize, summarize, professional tone) → LLM

#### 8. Manual JSON string construction for string-typed params
**Impact**: JSON parsing errors when content contains quotes, newlines, or backslashes
**Fix**: Use object syntax—pflow auto-serializes with proper escaping
```yaml
# ❌ Manual JSON string: '{"data": "${input}"}'  → breaks on special chars
# ✅ Object syntax:
- data: ${input}
# → auto-escapes correctly
```

### Real Request Parsing - Handling Ambiguity

**When user says vague things, make them precise:**

| User Says | Ambiguity | Clarification Approach |
|-----------|-----------|------------------------|
| "recent messages" | How many is recent? | Add a `### limit` input with `- default: 10` |
| "process the data" | What data? What processing? | Ask: "What's the data source? What processing do you need?" |
| "send notification" | Where? To whom? | Ask: "Where should notifications go? (email, Slack, etc.)" |
| "fast processing" | How fast? At what cost? | Explain tradeoff: "I can optimize for speed or thoroughness" |
| "handle errors" | How to handle? | Use `- on-error: handler-node` to route failures to a handler |

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
| `result: Any` | `result.data.tool_response.nested.deeply.value` | Always test structure with registry_run |
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
| Repetitive nodes | Inefficient | Use batch with inline array |
| LLM for extraction | Expensive & unreliable | Templates for paths, code node for transformation |
| Hardcoded credentials | Security risk | Use inputs + settings |
| No output formatting | Poor UX | Add format step |
| Generic names | Hard to discover | Use descriptive names |
| No descriptions | Hard to understand | Add description prose to every node |

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

### MCP Tool Cheat Sheet

```python
# Discovery & Research
workflow_discover(query="complete user request")                          # Find existing workflows
registry_discover(task="all operations needed")                           # Find nodes for building
registry_describe(nodes=["node1", "node2"])                              # Get node specifications
registry_list(filter_pattern="keyword1 keyword2")                         # List/filter available nodes

# Testing & Debugging
registry_run(node_type="node-type", parameters={"param": "value"})       # Test node (output pre-filtered for agents)
read_fields(execution_id="exec-id", field_paths=["field.path"])          # Get actual field values if needed

# Workflow Operations
workflow_execute(workflow="workflow.pflow.md", parameters={"p": "v"})     # Run workflow from file (while developing)
workflow_execute(workflow="workflow-name", parameters={"p": "v"})         # Run saved workflow by name
workflow_save(workflow="./workflow.pflow.md", name="workflow-name")       # Save workflow (when finished developing)

# Workflow Library
workflow_list(filter_pattern="keyword")                                   # List saved workflows
workflow_describe(name="workflow-name")                                   # Show workflow interface
```

### CLI Commands (Supplementary)

```bash
# Settings & Auth (MCP settings tools are disabled — use CLI)
pflow settings set-env KEY_NAME "value"             # Store credential
pflow settings show                                 # View settings
llm keys set provider                               # Set LLM keys

# Trace Debugging
cat ~/.pflow/debug/workflow-trace-*.json | jq '.'   # Inspect trace (for debugging)
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
Need specific nested fields? → Test with `registry_run`
Passing whole result? → Skip testing
Complex transformation? → Test
Simple operations? → Skip
```

**Which tool to use?**
```
Extract nested field? → Template variable ${node.path.to.field}
Transform/compute?    → code node
Combine/concatenate?  → code node or templates
Parse text → structured? → code node (NEVER LLM)
Need meaning/reasoning? → LLM (only if creative decisions needed)
Run external tool?    → shell node (git, curl, docker, ffmpeg)
File download?        → shell+curl
JSON API?             → http node
Service-specific?     → MCP node
```

### Workflow Naming Convention

Format: `verb-noun-qualifier`
- Examples: `fetch-api-data`, `process-csv-files`, `analyze-slack-messages`
- Max 30 chars, lowercase, hyphens only
- Specific enough to find, generic enough to reuse

### Common Agent Mistakes to Avoid

| Mistake | Why It Happens | Prevention |
|---------|----------------|------------|
| **Manual JSON string construction** | Trying to build `"{\"key\": \"${val}\"}"` | Use object syntax: `{"key": "${val}"}` - auto-serializes with proper escaping |
| **Using Slack as default example** | Document bias from old examples | Rotate between service categories |
| **Using LLM for JSON extraction** | Seems "safer" or more flexible | Templates extract paths, code node transforms |
| **Over-testing nodes** | Uncertainty about structure | Test ONLY when accessing specific paths |
| **Creating defensive extraction steps** | Fear of malformed data | Nodes handle parsing automatically |
| **Ignoring workflow discovery** | Eager to build something new | ALWAYS check existing workflows first |
| **Forgetting to save workflow** | Step 10 seems optional | Save is REQUIRED for name-based execution |
| **Hardcoding service names** | Following specific examples | Use category patterns instead |
| **Building all at once** | Want to show complete solution | Build core path first, test, then add |

### Key Success Factors

1. **Always run workflow_discover() first** - No exceptions
2. **Understand step order vs templates** - Execution order vs data access
3. **Test only when needed** - Skip if passing whole `${node.result}`
4. **Phase complex workflows** - Build incrementally
5. **Use templates for extraction, code node for transformation** - LLM only for meaning
6. **Every value becomes input** - Unless explicitly "always"
7. **Format user-facing output** - Never show raw JSON
8. **Document actual structures** - Not what docs claim
9. **Handle auth properly** - Inputs + settings
10. **Build general from specific** - One example → universal tool

---

**Final reminder**: Users show you ONE specific example. Your job is to build the GENERAL tool that works for everyone, with every specific value made configurable. When in doubt, make it an input.
