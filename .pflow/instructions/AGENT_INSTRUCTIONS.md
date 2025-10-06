# pflow Agent Instructions

## ⚡ Quick Start Decision Tree

### First: What does user want?
```
User says "run X" → Find and execute workflow
User says "create/build X" → Check existing, then build/modify
User requests action (verbs + domain terms) → Find and execute if possible
User describes problem/goal → Explore, guide, build
```

### Then: Parameter decisions
```
User provides a value?
├── It's specific (ID, path, number)? → Make it an INPUT
├── User says "always/only/hardcode"? → Hardcode it
├── It's a format/pattern? → Hardcode it
└── When unsure? → Make it an INPUT (safer)
```

## 🎯 Your Mission

**Build reusable tools, not one-time scripts.**

Every workflow should work tomorrow, for someone else, with different data.
The user shows you ONE example. You build the GENERAL solution using dynamic inputs based on the users example.

---

## Table of Contents

1. [How to Think About Workflows](#how-to-think-about-workflows)
2. [The Agent Development Loop](#the-agent-development-loop)
3. [Common Workflow Patterns](#common-workflow-patterns)
4. [Progressive Learning Path](#progressive-learning-path)
5. [Pre-Build Checklist](#pre-build-checklist)
6. [Building Workflows](#building-workflows)
   - [Critical Constraints](#-critical-constraints-read-first)
   - [Node Parameter Philosophy](#node-parameter-philosophy)
   - [Template Variable Syntax](#template-variable-syntax)
   - [Workflow Inputs](#workflow-inputs)
   - [Workflow Outputs](#workflow-outputs)
7. [Validation](#validation)
8. [Testing & Debugging](#testing--debugging)
9. [Saving Workflows](#saving-workflows)
10. [Executing Workflows](#executing-workflows)
11. [Context Efficiency](#context-efficiency)
12. [Common Mistakes](#common-mistakes)
13. [Quick Reference](#quick-reference)

---

## Workflow Philosophy

Three principles guide every decision:

1. **Maximize Reusability**: Every hardcoded value limits who can use this workflow
2. **Explicit Over Implicit**: Clear inputs/outputs beat hidden assumptions
3. **Intent Over Literal**: Users say "do X with Y" but mean "build a tool that does X-like things"

**The Reusability Test**: Before building, ask "Could someone else use this tomorrow for a similar task?"

---

## Working with Constraints

**pflow has limitations. Be creative:**

- **No loops** → Use LLM to batch-process (e.g., transform all Q&A pairs into rows at once)
- **No branching** → Use LLM to handle all cases in one output
- **Linear only** → Later nodes can reference any earlier outputs

**Your job**: Find creative ways to deliver what the user wants. If truly impossible, explain why and suggest alternatives.

---

## How to Think About Workflows

A workflow is a **reusable data transformation tool**. Users show you one example, but you build for all cases.

### The Mental Model

```
[Input Data] → [Transform 1] → [Transform 2] → [Output Data]
```

Every workflow answers three questions:
1. **What data do I start with?** (inputs, files, APIs)
2. **What transformations happen?** (fetch, analyze, format, send)
3. **What data do I produce?** (files, messages, API calls)

### Breaking Down a Task

**Your Thinking Process** (applies to ANY request):

User says: "Do X with specific-value-Y and send to specific-value-Z"

**Step 1 - Extract the pattern**:
- What's the general action? (fetch, analyze, send)
- What are the variable parts? (sources, destinations, parameters)

**Step 2 - Identify what becomes inputs**:
- specific-value-Y → `source` input (they'll want different sources)
- specific-value-Z → `destination` input (they'll want different destinations)
- Any counts/limits → inputs with defaults

**Step 3 - Map transformations**:
1. Get data from [SOURCE] → Data
2. Transform/analyze → Processed data
3. Send to [DESTINATION] → Confirmation

This pattern works whether it's Slack→Sheets, GitHub→Email, or Files→Database.

### Choosing Node Categories

Before discovering specific nodes, know which category you need:

| Need | Category | Examples |
|------|----------|----------|
| **Get data** | Data retrieval | `read-file`, `http`, `mcp-slack-fetch`, `mcp-github-get` |
| **Transform text** | AI/LLM processing | `llm` |
| **Transform data** | Data processing | `llm` (with structured prompts), `shell` (jq, awk) |
| **Store data** | Data storage | `write-file`, `mcp-slack-send`, `mcp-sheets-update` |
| **Run commands** | System operations | `shell` |
| **Make decisions** | Control flow | `llm` (outputs structured choices) |

**Pro tip**: When in doubt, `llm` can handle most text-based transformations!

---

## The Agent Development Loop

**This is your workflow for building workflows.** Follow this cycle every time:

### 1. UNDERSTAND (5 minutes)

Parse the user's request into structured requirements.

**Checklist**:
- [ ] What are the inputs? (params, files, API data)
- [ ] What are the outputs? (files, messages, database updates)
- [ ] What transformations happen between input and output?
- [ ] What external services are involved?
- [ ] Does this match a common pattern? (see [Common Patterns](#common-workflow-patterns))

**Example Thinking**:
```
User: "Get messages from source X, process with AI, send to destination Y"

Your Analysis:
- User inputs needed: source_id, destination_id
- Core transformations: fetch → process → send
- Services involved: [Identify from user's request]
- Pattern: Multi-service pipeline
- Additional: Consider if timestamps, limits, formats should be configurable
```

**Determine user intent**:
- **"Run/execute [workflow]"** → Named execution (user knows workflow name)
- **"Create/build [workflow]"** → Explicit building request
- **Action request** → "Analyze X", "Send Y", "Generate Z" → Domain task execution
- **"I need to [problem]"** → Exploration, needs guidance

**Assess user confidence**:

High confidence signals (user knows what they want):
- Lists specific steps or data flow
- Names exact tools/services/APIs
- Provides concrete input/output examples
- Uses definitive language ("fetch X, transform Y, send to Z")

Low confidence signals (user exploring):
- Describes desired outcome without method ("track things better")
- Uses uncertain language ("maybe", "somehow", "something like")
- Asks questions in request ("is it possible to...", "how can I...")
- Mentions problems without solutions

→ High confidence: Proceed directly to discover/build
→ Low confidence: Explore requirements first

**Recognize action requests vs exploration**:

Action request signals (wants immediate execution):
- Action verbs: analyze, generate, send, update, process, calculate, export
- Domain-specific terms: "customer churn", "revenue report", "team standup", "metrics"
- Time-bound references: "this week", "today", "for October", "Q4 data"
- Delegation tone: speaks as if asking a colleague who knows the job

NOT action requests (needs help/guidance):
- Problem descriptions: "I need to track X better"
- Questions: "How can I...", "Is it possible to..."
- Uncertainty: "something to help with...", "maybe we could..."
- Feature requests: "It should also do X"

→ Action request + workflow exists → Execute immediately (if params satisfied)
→ Problem/exploration → Guide through discovery

**Output**: Clear mental model + user intent + confidence level + action vs exploration

### 2. DISCOVER WORKFLOWS (5 minutes)

**Check for existing workflows before building new ones.**

This is MANDATORY - never skip this step. Users often don't know what workflows already exist.

```bash
uv run pflow workflow discover "user's request in natural language"
```

**What you get**: Matching workflows with names, descriptions, inputs/outputs, confidence scores, and reasoning.

#### Processing Discovery Results

Always surface relevant workflows (70%+ confidence) regardless of user intent - they might not know what exists.

**Based on user intent and match scores:**

**User said "run/execute [workflow]"** (believes it exists):
- **90-100% match + all params provided** → Execute immediately
- **90-100% match + missing params** → Ask for missing params, then execute
- **70-89% matches** → "No exact match. Found similar: [list]. Run one of these?"
- **<70%** → "No workflow found matching that name. Want me to build it?"

**User said "create/build [workflow]"** (wants something new):
- **90-100% match** → "Found existing `workflow-name` that does this. Use it, modify it, or build new?"
- **70-89% matches** → "Found similar workflows: [list]. Want to see/modify these first?"
- **<70%** → Proceed to build new workflow (continue to Step 3)

**User made an action request** (wants something done):
Examples: "analyze customer data", "send report", "process invoices"
- **80-100% match + all required params satisfied** → Execute immediately
- **80-100% match + missing params** → "I need [specific param] to run this"
- **<80% match** → "I don't have a workflow for that yet. Should I create one?"

**User described problem/need** (wants help/exploration):
Examples: "I need to track metrics better", "how can we monitor API usage?"

→ **Low confidence/exploring users**:
  1. "Let me help clarify what you need. Based on your request, you might want to:"
     - Option A: [One interpretation of their request]
     - Option B: [Another valid interpretation]
     - Option C: Something else?
  2. Based on their answer, show relevant workflows or suggest approach
  3. Guide to decision: use existing, modify, or build custom

→ **High confidence/clear requirements**:
  - **90-100% match** → "Found `workflow-name` that does exactly this. Want to use it?"
  - **70-89% matches** → Show differences clearly, ask preference
  - **<70%** → "I'll build a new workflow for your requirements"

#### Comparing Similar Workflows

When presenting workflows with 70%+ match, explain differences clearly:

```
Found `workflow-name` (85% match):
✅ Matches your requirements:
  - [Features that align with request]
❌ Differences:
  - [What's different and why it matters]
➕ Additional features:
  - [Extra capabilities they didn't request]

Impact: [How these differences affect their use case]
```

**Example comparison**:
```
Found `slack-to-sheets` (85% match):
✅ Matches:
  - Fetches from Slack
  - Processes with AI
  - Logs to Google Sheets
❌ Differences:
  - Analyzes sentiment (you want Q&A)
  - Different sheet format
➕ Additional:
  - Sends summary email
  - Archives messages

Impact: Core flow matches, but needs prompt adjustment for Q&A instead of sentiment.
```

**Decision point**:
- **Execute existing workflow** → Skip to execution
- **Modify existing workflow** → Load it, proceed to Step 4 (design modifications)
- **Build new workflow** → Continue to Step 3 (discover nodes)

**Output**: Clear decision on whether to execute existing, modify existing, or build new

### 3. DISCOVER NODES (3 minutes)

**Find the building blocks for your workflow (only if building new).**

If Step 2 determined you need to build a new workflow, discover the relevant nodes:

```bash
uv run pflow registry discover "I need to fetch Slack messages, analyze with AI, send responses, and log to Google Sheets"
```

This uses pflow's internal LLM to intelligently select relevant nodes with complete specs in one shot.

**What you get**:
- Complete interface specifications
- Parameter types and descriptions
- Output structure
- Usage requirements

**Only use manual commands if AI discovery is unavailable**:
- `pflow registry describe node1 node2` - Get specific node specs when you know exact names
- Avoid `pflow registry list` - pollutes context with hundreds of unnecessary nodes

**Output**: List of nodes with interfaces understood, ready for design phase

### 4. DESIGN (5 minutes)

Sketch the data flow before writing JSON.

**Checklist**:
- [ ] List nodes in execution order
- [ ] Choose descriptive node IDs (fetch-messages, not node1)
- [ ] Map data flow: which outputs feed which inputs?
- [ ] Identify template variables: `${node_id.output_key}`
- [ ] Plan edge connections

**Example design**:
```
get-date (shell) → stdout
     ↓
fetch-messages (mcp-slack) → result.messages
     ↓
analyze (llm) → response (Q&A pairs)
     ↓
send-response (mcp-slack) → result
     ↓
log (mcp-sheets) → result

Templates needed:
- ${fetch-messages.result}
- ${analyze.response}
- ${get-date.stdout}
```

**Output**: Clear node graph design

### 5. PLAN & CONFIRM (2 minutes)

**Show your understanding before building JSON.**

#### Adapt confirmation to user confidence

**For exploring users** (low confidence):
```
"Let me make sure I understand what you're trying to achieve:
- Goal: [outcome they want]
- Current situation: [problem they described]

Possible approaches:
1. [Approach A] - Pros: [...] Cons: [...]
2. [Approach B] - Pros: [...] Cons: [...]

Which direction fits best? Or should we explore other options?"
```

**For decisive users** (high confidence):
```
"I'll create a workflow that:
1. [Specific step with tool]
2. [Specific step with tool]
3. [Specific step with tool]

Inputs: [list]
Pattern: [which pattern]

Quick confirm - this matches what you need?"
```

**For unclear requests** (any confidence):
```
"I need clarification on a few points:
- When you say X, do you mean [option A] or [option B]?
- Should the output be [format 1] or [format 2]?
- What should happen if [edge case]?"
```

**Output**: User-confirmed plan that matches their intent

### 6. BUILD (10 minutes)

**After plan is confirmed**, create the workflow JSON step-by-step.

#### 🔴 The Input Decision Framework

**Core Rule: If the user specified it, it should be an input.**

The user is demonstrating ONE example. Build the GENERAL tool.

**Decision Process:**
```
Is it a specific value (ID, path, number, name)?
  → YES: Make it an INPUT

Did user say "always", "only", or "hardcode"?
  → YES: Safe to hardcode

Is it a system constraint (date format, encoding)?
  → YES: Hardcode it

Everything else?
  → Make it an INPUT (safer for reusability)
```

**Why**: Someone else will want to use this workflow with different values tomorrow.

#### Step 6.1: Declare Workflow Inputs (2 min)

**For all user-provided values (following the rule above).**

```json
{
  "inputs": {
    "user_value": {
      "type": "string",              // REQUIRED: string, number, boolean, array, object
      "description": "What this is",  // REQUIRED: Clear explanation
      "required": true                // REQUIRED: true or false
    }
  }
}
```

**Validation**:
- [ ] Each input is a value the USER provides (not generated by nodes)
- [ ] Each input has `type`, `description`, `required` fields
- [ ] If `required: false`, has sensible `default` value
- [ ] No extra fields (no `example`, `format`, etc.)

#### Step 6.2: Create Nodes Array (5 min)

**One node at a time, in execution order.**

```json
{
  "nodes": [
    {
      "id": "descriptive-id",       // Unique, use hyphens
      "type": "node-type",           // From registry
      "params": {
        "required_param": "value",          // Required params
        "input_ref": "${workflow_input}",   // Reference workflow input
        "node_ref": "${previous.output}"    // Reference previous node
      }
    }
  ]
}
```

**Validation (per node)**:
- [ ] ID is descriptive (not `node1`, `node2`)
- [ ] Type exists in registry (checked with `pflow registry describe`)
- [ ] All required params are set
- [ ] Optional params only set if user requested or logic requires
- [ ] Every `${variable}` is either a workflow input OR previous node output
- [ ] Used `params` not `inputs` for node configuration

#### Step 6.3: Create Edges Array (1 min)

**Connect nodes in execution order.**

```json
{
  "edges": [
    {"from": "node1", "to": "node2"},
    {"from": "node2", "to": "node3"}
  ]
}
```

**Validation**:
- [ ] Forms a LINEAR chain (no branches)
- [ ] Each node appears in order
- [ ] Each node has exactly ONE outgoing edge (except last)
- [ ] No cycles (node1 → node2 → node1)

#### Step 6.4: Declare Workflow Outputs (2 min)

**Expose specific results to users.**

```json
{
  "outputs": {
    "result_name": {
      "source": "${node_id.output_key}",  // REQUIRED: Template expression
      "description": "What this contains"  // REQUIRED: Clear explanation
    }
  }
}
```

**Validation**:
- [ ] Each output has ONLY `source` and `description` fields
- [ ] `source` uses `${}` template syntax
- [ ] Referenced node outputs exist (checked with `pflow registry describe`)
- [ ] Most important output is FIRST
- [ ] Follows output strategy (file workflows: confirmations, analysis: full results)

#### Build Checklist Summary

Before moving to VALIDATE:
- [ ] Workflow inputs declared for all user-provided values
- [ ] Nodes use descriptive IDs
- [ ] Node params use defaults (only override when necessary)
- [ ] All templates (`${...}`) are either inputs or node outputs
- [ ] Edges form a linear chain
- [ ] Workflow outputs expose useful data
- [ ] Used `params` not `inputs` for nodes

**Output**: Complete workflow.json file

**Don't worry about**: `ir_version` or empty `edges` - these are auto-added!

### 7. VALIDATE (2 minutes per iteration)

Catch structural errors before execution.

```bash
uv run pflow --validate-only workflow.json
```

**What gets validated**:
- ✅ Schema compliance (JSON structure)
- ✅ Data flow correctness (execution order, no cycles)
- ✅ Template structure (syntax, node references, output paths)
- ✅ Node types exist

**Process**:
1. Run validation
2. Read error message carefully
3. Fix ONE error at a time
4. Re-validate
5. Repeat until ✓

**Output**: Structurally valid workflow

### 8. TEST (Variable - only when needed)

Execute the workflow to verify it works.

```bash
uv run pflow workflow.json param1=value param2=value
```

**When to discover `result: Any` output structures**:

Only investigate MCP tool outputs when:
- ✅ You need nested data in templates: `${fetch.result.messages[0].text}`
- ✅ You need to expose nested fields in workflow outputs (Avoid in outputs unless necessary or explicitly asked for by the user)
- ✅ Your templates reference specific structure

Skip output discovery when:
- ❌ Just passing data through: `${fetch.result}` works fine
- ❌ Sending to LLM: `prompt: "Analyze: ${data.result}"` - LLM handles any structure
- ❌ Output is the final result: workflow ends there

**How to discover output structure** (if needed):
```bash
# 1. Create minimal test workflow
uv run pflow --trace test-workflow.json

# 2. Examine trace
cat ~/.pflow/debug/workflow-trace-*.json | jq '.nodes[0].outputs'

# 3. Use discovered structure in templates
```

**Output**: Working workflow that executes successfully

### 9. REFINE (Variable)

Improve the workflow for production use.

**What you CAN refine**:
- ✅ Improve LLM prompts for better results
- ✅ Optimize data flow and node ordering
- ✅ Add better descriptions for reusability
- ✅ Enhance input/output declarations

**What you CANNOT currently do**:
- ❌ Add error handling (no branching in IR)
- ❌ Add try-catch patterns
- ❌ Add conditional flows (if-then-else)
- ❌ Add retry logic (handled by `--no-repair` externally)


**Output**: Production-ready workflow

### 10. SAVE (1 minute)

**When to do this**: After your workflow is tested and working correctly.

Save to global library for reuse across all projects:

```bash
uv run pflow workflow save .pflow/workflows/your-draft.json workflow-name "Clear description"

# With optional enhancements
uv run pflow workflow save .pflow/workflows/your-draft.json workflow-name "Description" --generate-metadata --delete-draft
```

See [Saving Workflows](#saving-workflows) section below for complete details.

**Output**: Reusable workflow available globally as `pflow workflow-name`

**Always tell the user how to run their saved workflow**:
```bash
# If no inputs (all hardcoded):
uv run pflow workflow-name

# If has inputs (show with user's values):
uv run pflow workflow-name channel=C123 sheet_id=abc123
```

---

## Common Workflow Patterns

Learn to recognize these patterns in user requests:

### Pattern 1: Fetch → Transform → Store

```
[Data Source] → [LLM/Processing] → [Data Sink]
```

**Example**: Read file → Analyze → Write summary

**Nodes**:
```json
{
  "nodes": [
    {"id": "read", "type": "read-file", "params": {"file_path": "${input_file}"}},
    {"id": "analyze", "type": "llm", "params": {"prompt": "Summarize: ${read.content}"}},
    {"id": "write", "type": "write-file", "params": {"content": "${analyze.response}", "file_path": "summary.md"}}
  ],
  "edges": [
    {"from": "read", "to": "analyze"},
    {"from": "analyze", "to": "write"}
  ]
}
```

**Use when**: Simple ETL (Extract, Transform, Load) tasks

### Pattern 2: Multi-Source → Combine → Process

```
[Source A] ──┐
             ├─→ [LLM Combines] → [Process]
[Source B] ──┘
```

**Example**: Fetch GitHub PR + issues → Analyze together → Generate report

**Nodes**:
```json
{
  "nodes": [
    {"id": "get-pr", "type": "mcp-github-get-pr", "params": {"number": "${pr_number}"}},
    {"id": "get-issues", "type": "mcp-github-list-issues", "params": {"state": "open"}},
    {"id": "analyze", "type": "llm", "params": {
      "prompt": "PR: ${get-pr.result}\n\nIssues: ${get-issues.result}\n\nGenerate report"
    }}
  ],
  "edges": [
    {"from": "get-pr", "to": "analyze"},
    {"from": "get-issues", "to": "analyze"}
  ]
}
```

**Use when**: Combining data from multiple sources

### Pattern 3: Fetch → Decide → Act

```
[Data Source] → [LLM Decision] → [Conditional Action]
```

**Example**: Get PR → Check if approved → Take action

**Current limitation**: No native branching. Workaround: LLM outputs action command as text.

**Nodes**:
```json
{
  "nodes": [
    {"id": "get-pr", "type": "mcp-github-get-pr", "params": {"number": "${pr}"}},
    {"id": "decide", "type": "llm", "params": {
      "prompt": "Is this PR approved? ${get-pr.result}\nRespond ONLY with: MERGE or COMMENT"
    }},
    {"id": "comment", "type": "mcp-github-comment", "params": {
      "body": "Decision: ${decide.response}"
    }}
  ]
}
```

**Note**: True branching not yet supported. This pattern works for simple cases where you can describe both paths in one action.

**Use when**: Need to make decisions based on data content

### Pattern 4: Multi-Service Coordination

```
[Service A] → [Transform] → [Service B] → [Service C]
```

**Example**: Slack → AI analysis → Slack response → Sheets logging

**Nodes**:
```json
{
  "nodes": [
    {"id": "fetch", "type": "mcp-slack-fetch", "params": {"channel": "C123"}},
    {"id": "analyze", "type": "llm", "params": {"prompt": "Answer questions: ${fetch.result}"}},
    {"id": "respond", "type": "mcp-slack-send", "params": {"channel": "C123", "text": "${analyze.response}"}},
    {"id": "log", "type": "mcp-sheets-update", "params": {"values": [["${analyze.response}"]]}}
  ],
  "edges": [
    {"from": "fetch", "to": "analyze"},
    {"from": "analyze", "to": "respond"},
    {"from": "respond", "to": "log"}
  ]
}
```

**Use when**: Orchestrating multiple external services

### Pattern 5: Enrich → Process → Store

```
[Base Data] → [Enrich with Context] → [Process] → [Store]
```

**Example**: Get issue → Fetch related PRs → Analyze → Update issue

**Nodes**:
```json
{
  "nodes": [
    {"id": "get-issue", "type": "mcp-github-get-issue", "params": {"number": "${issue}"}},
    {"id": "get-prs", "type": "mcp-github-list-prs", "params": {"state": "open"}},
    {"id": "analyze", "type": "llm", "params": {
      "prompt": "Issue: ${get-issue.result}\nRelated PRs: ${get-prs.result}\nGenerate analysis"
    }},
    {"id": "update", "type": "mcp-github-update-issue", "params": {
      "number": "${issue}",
      "body": "${analyze.response}"
    }}
  ]
}
```

**Use when**: Need to gather context before processing

---

## Pattern Library

Quick examples showing the input extraction principle across different domains:

### File Operations
```
User: "Convert data.csv to JSON"
Your inputs: {
  "input_file": {"type": "string", "required": true, "description": "Source file path"},
  "output_format": {"type": "string", "required": false, "default": "json", "description": "Output format"}
}
Why: Tomorrow they'll convert "other.csv" or want XML output
```

### API Integrations
```
User: "Get issues from repo owner/name"
Your inputs: {
  "repo": {"type": "string", "required": true, "description": "Repository in owner/name format"}
}
Why: Reusable for any repository
```

### Threshold Monitoring
```
User: "Alert when value exceeds 100"
Your inputs: {
  "threshold": {"type": "number", "required": false, "default": 100, "description": "Alert threshold"}
}
Why: Different scenarios need different thresholds
```

### Data Processing
```
User: "Process last 30 items with batch size 5"
Your inputs: {
  "item_count": {"type": "number", "required": false, "default": 30},
  "batch_size": {"type": "number", "required": false, "default": 5}
}
Why: Optimal values vary by use case
```

**Key Pattern**: Every specific value becomes a configurable input unless explicitly told otherwise.

---

## Recognizing Action Requests vs Exploration

Understanding the difference between users wanting **immediate action** vs **needing help**.

### Action Requests (Execute immediately if possible)

**Examples**:
```
"Generate the weekly sales report" or "I need sales report now for this week"
"Send standup summary to team" or "Run the standup flow""
"Process today's transactions" or "Can we process today's transactions?"
```

**Pattern**: [Action/need/question] + [business object/workflow] + [urgency/specifics]
- Use your best judgement to determine if the user is asking for an action.
- If it seems like you should know what to do, thats a clear signal that the user is asking for execution.

**Response**: Find matching workflow and execute if possible. Don't compare alternatives.

### Exploration Requests (Need guidance)

**Examples**:
```
"I need something to track customer engagement"
"How can we monitor our API usage?"
"We should analyze our support tickets somehow"
"I want to automate our reporting"
"Is it possible to connect Stripe to Sheets?"
"Maybe we could track deployments better"
```

**Pattern**: [Problem/need] + [uncertainty] + [no specific action]

**Response**: Explore options, guide to solution, show comparisons.

### Key Principle: Missing HOW ≠ Confusion

When users say "analyze customer churn" without mentioning implementation:
- They're not confused about what they want
- They're delegating the HOW to you
- They expect you to handle the details
- Execute if you can, ask only for missing required params

---

## Progressive Learning Path

Start simple, build complexity gradually.

### Level 1: Single Transform (5 minutes)

**Goal**: Understand basic structure

```json
{
  "nodes": [
    {
      "id": "process",
      "type": "llm",
      "params": {
        "prompt": "${input}"
      }
    }
  ],
  "inputs": {
    "input": {
      "type": "string",
      "required": true,
      "description": "Text to process"
    }
  }
}
```

**Try it**:
```bash
uv run pflow --validate-only level1.json
uv run pflow level1.json input="What is 2+2?"
```

**What you learn**:
- Basic JSON structure
- Input declarations
- Validation workflow

### Level 2: Chain Two Nodes (10 minutes)

**Goal**: Understand data flow with templates

```json
{
  "nodes": [
    {
      "id": "read",
      "type": "read-file",
      "params": {
        "file_path": "${file}"
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "params": {
        "prompt": "Summarize this file:\n\n${read.content}"
      }
    }
  ],
  "edges": [
    {"from": "read", "to": "analyze"}
  ],
  "inputs": {
    "file": {
      "type": "string",
      "required": true,
      "description": "File path to analyze"
    }
  }
}
```

**Try it**:
```bash
uv run pflow level2.json file="README.md"
```

**What you learn**:
- Template variables `${node.output}`
- Edge connections
- Data flow between nodes

### Level 3: Multi-Step Pipeline (20 minutes)

**Goal**: Coordinate multiple operations

```json
{
  "nodes": [
    {
      "id": "fetch",
      "type": "http",
      "params": {
        "url": "${api_url}",
        "method": "GET"
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "params": {
        "prompt": "Extract key insights from this API response:\n\n${fetch.response}"
      }
    },
    {
      "id": "save",
      "type": "write-file",
      "params": {
        "file_path": "analysis.md",
        "content": "# Analysis\n\n${analyze.response}"
      }
    }
  ],
  "edges": [
    {"from": "fetch", "to": "analyze"},
    {"from": "analyze", "to": "save"}
  ],
  "inputs": {
    "api_url": {
      "type": "string",
      "required": true,
      "description": "API endpoint to fetch data from"
    }
  }
}
```

**What you learn**:
- Multi-step pipelines
- HTTP operations
- File operations

### Level 4: Real-World Integration (30+ minutes)

**Goal**: Use MCP tools, handle complex data

See [Complete Example](#complete-example-building-a-complex-workflow) for a full Slack + Sheets workflow.

**What you learn**:
- MCP tool usage
- Multi-service coordination
- Production patterns

---

## Pre-Build Checklist

**Before writing any JSON, verify you have:**

### ✅ Complete Understanding
- [ ] I can explain the workflow in 1-2 sentences
- [ ] I know what data enters the workflow (inputs)
- [ ] I know what data exits the workflow (outputs)
- [ ] I can draw the data flow on paper

### ✅ Workflow Discovery Complete (Step 2 - MANDATORY)
- [ ] I've run `pflow workflow discover "user's request"`
- [ ] If 70%+ match found: I've shown it to user and confirmed their decision
- [ ] Decision made: execute existing, modify existing, or build new

### ✅ Node Discovery Complete (Step 3 - if building new)
- [ ] I've run `pflow registry discover "specific task description"`
- [ ] I have node specs (from discovery output or `pflow registry describe`)
- [ ] I understand which outputs are `Any` type and if I need to investigate them

### ✅ Critical Nodes Tested (Recommended - Step 3.5)
- [ ] I've tested MCP nodes with `pflow registry run` to verify parameters
- [ ] I've confirmed auth/credentials work for external services
- [ ] I've seen exact output structure for `Any` type nodes using `--show-structure`
- [ ] I'm confident about parameter formats (especially arrays/objects)

**Why test first?** Catch parameter errors before building workflows. See actual output structures, not guessing. Verify credentials work independently. Build workflows with confidence (fewer iterations).

**When to test:**
- ✅ MCP nodes (especially with `Any` outputs)
- ✅ Nodes requiring authentication
- ✅ Complex parameter formats (arrays, objects)
- ❌ Simple nodes with known schemas (optional)

### ✅ Design Validated
- [ ] My workflow is a LINEAR chain (no parallel branches)
- [ ] Each node has exactly ONE successor
- [ ] I can trace how data flows: `input → node1.output → node2.param → node3.param`
- [ ] I know which values are user inputs vs. hardcoded vs. node outputs

### ✅ Ready to Build
- [ ] I have node types written down
- [ ] I have parameter names for each node
- [ ] I know which workflow inputs to declare
- [ ] I know which workflow outputs to expose

**Time investment**: 5-10 minutes on this checklist saves 30+ minutes of debugging.

**If you can't check all boxes**: Go back to Step 2 (workflows), Step 3 (nodes), or Step 4 (design) as needed. If anything is unclear or if the task is impossible to build, ask the user for clarification by informing them of the current situation.

---

## Building Workflows

### 🚨 Critical Constraints (READ FIRST)

**These are HARD LIMITATIONS of the workflow system. Violating them will cause execution failures.**

#### 1. Sequential Execution Only

**Workflows execute nodes in a LINEAR chain. NO parallel execution.**

**❌ WRONG - This will NOT work:**
```
fetch-data → analyze
          ↘ visualize
```

**✅ CORRECT - Sequential chain:**
```
fetch-data → analyze → visualize
```

**Why**: Each node can have ONLY ONE outgoing edge in the `edges` array.

**Workaround**: Later nodes can reference MULTIPLE earlier outputs:
```json
{
  "id": "visualize",
  "params": {
    "data": "${fetch-data.content}",      // Reference original data
    "insights": "${analyze.response}"      // Reference analysis result
  }
}
```

#### 2. Template Variables Must Resolve

**Every `${variable}` MUST be either:**
- A declared workflow input: `"inputs": {"variable": {...}}`
- A node output: `${node_id.output_key}`

**❌ WRONG - Undefined variable:**
```json
{"file_path": "${output_file}"}  // Not declared anywhere
```

**✅ CORRECT - Declared in inputs:**
```json
{
  "inputs": {
    "output_file": {
      "type": "string",
      "required": true,
      "description": "Where to save results"
    }
  },
  "nodes": [{
    "params": {"file_path": "${output_file}"}
  }]
}
```

#### 3. Node Output References Must Exist

**You can only reference outputs that nodes actually produce.**

**❌ WRONG - Node doesn't output this:**
```json
{"content": "${read.text}"}  // read-file outputs 'content', not 'text'
```

> Carefully read the node documentation to understand the exact output structure.

**✅ CORRECT - Check node docs first:**
```bash
pflow registry describe read-file  # Shows it outputs 'content'
```
```json
{"content": "${read.content}"}  // Correct output name
```

**Rule**: ALWAYS run `pflow registry describe node-type` before writing templates.

---

### Minimal Workflow Structure

You only need essentials:

```json
{
  "nodes": [
    {
      "id": "unique-id",
      "type": "node-type",
      "params": {
        "param1": "value",
        "param2": "${template}"
      }
    }
  ],
  "edges": [
    {"from": "node1", "to": "node2"}
  ],
  "inputs": {
    "input_name": {
      "type": "string",
      "required": true,
      "description": "What this input is for"
    }
  },
  "outputs": {
    "output_name": {
      "source": "node_id.output_key",
      "description": "What this output contains"
    }
  }
}
```

### Node Structure

```json
{
  "id": "descriptive-id",      // Unique within workflow (use hyphens)
  "type": "node-type",          // From registry (e.g., "llm", "read-file")
  "params": {                   // Use "params" NOT "inputs"!
    "param1": "value",
    "param2": "${template}"
  }
}
```

**Key rules**:
- Use `params` not `inputs` for node configuration
- ID must be unique within workflow
- Type must exist in registry

---

### Node Parameter Philosophy

**Default Rule: Use node defaults whenever possible. Only set parameters the user explicitly requests.**

#### Why This Matters

Nodes have **sensible defaults** built-in. Overriding them:
- ❌ Wastes tokens (more characters in JSON)
- ❌ May use outdated values from your training data
- ❌ Overrides improvements in node defaults
- ❌ Makes workflows less maintainable

#### When to Set Parameters

**✅ SET when:**
- User explicitly requests specific values
- Required parameter (no default exists)
- Workflow logic requires non-default behavior

**❌ DON'T SET when:**
- Parameter has a good default
- User didn't mention it
- You're guessing what might be better

#### Examples

**❌ WRONG - Over-specification:**
```json
{
  "id": "analyze",
  "type": "llm",
  "params": {
    "prompt": "Analyze this data: ${read.content}",
    "model": "gpt-4",              // ❌ User didn't request specific model
    "temperature": 0.7,            // ❌ User didn't request specific temperature
    "max_tokens": 1000,            // ❌ User didn't request token limit
    "system": "You are a helpful assistant"  // ❌ Generic, not needed
  }
}
```

**✅ CORRECT - Minimal specification:**
```json
{
  "id": "analyze",
  "type": "llm",
  "params": {
    "prompt": "Analyze this data: ${read.content}"
    // ✅ That's it! Node uses sensible defaults for model, temperature, etc.
  }
}
```

**✅ CORRECT - User-requested overrides:**
```json
// User said: "Use GPT-4 with low temperature for consistency"
{
  "id": "analyze",
  "type": "llm",
  "params": {
    "prompt": "Analyze this data: ${read.content}",
    "model": "gpt-4",              // ✅ User explicitly requested
    "temperature": 0.2             // ✅ User wants consistency
  }
}
```

#### Common Defaulted Parameters

These typically have good defaults (don't set unless requested):

| Node Type | Defaulted Params | When to Override |
|-----------|------------------|------------------|
| `llm` | model, temperature, max_tokens | User requests specific model/behavior |
| `read-file` | encoding | Non-UTF-8 file |
| `write-file` | encoding, mode | Specific encoding or append mode |
| `http` | method, headers | POST requests or auth needed |
| `shell` | shell, timeout | Specific shell or long-running command |

**Check what's required:**
```bash
pflow registry describe node-type  # Shows required vs optional params
```

#### The Decision Process

```
Need to add a parameter?
│
├─ Is it REQUIRED by the node? → YES → Add it
│
├─ Did user EXPLICITLY request it? → YES → Add it
│
└─ Does workflow LOGIC require it? → YES → Add it
   │
   └─ Otherwise → SKIP IT (use default)
```

### Template Variable Syntax

**Templates (`${...}`) are how data flows through your workflow.**

#### Decision Tree: What Goes Where?

**When you need to reference a value in node params, ask:**

```
┌─ Is this value PROVIDED BY USER when running workflow?
│
├─ YES → Declare in "inputs" section
│         THEN reference as: ${input_name}
│
│         Example:
│         "inputs": {"repo": {type, description, required}}
│         "params": {"repository": "${repo}"}
│
└─ NO → Is this value GENERATED BY A NODE?
   │
   ├─ YES → Reference as: ${node_id.output_key}
   │         CHECK node output first: pflow registry describe node-type
   │
   │         Example:
   │         "params": {"content": "${read.content}"}
   │
   └─ NO → It's a STATIC VALUE
             Use literal value (no template)

             Example:
             "params": {"encoding": "utf-8"}
```

#### The Golden Rule

**🔴 Every `${variable}` must be EITHER:**
1. **A workflow input**: Declared in `"inputs": {"variable": {...}}`
2. **A node output**: From an earlier node `${node_id.output_key}`

**If it's neither, validation will fail.**

#### Template Syntax Patterns

Once you know the source, use the right syntax:

```json
{
  "params": {
    "file_path": "${input_file}",           // ✅ Workflow input
    "content": "${read.content}",           // ✅ Node output (simple)
    "text": "${analyze.response}",          // ✅ Chained node data
    "nested": "${fetch.result.data}",       // ✅ Nested object access
    "array": "${items.result[0].name}",     // ✅ Array indexing
    "hardcoded": "utf-8"                    // ✅ Static value (no template)
  }
}
```

#### Common Mistakes

**❌ WRONG - Using ${} for node output that should be an input:**
```json
// User provides repo when running workflow
"params": {"repo": "${github.repo}"}  // ❌ No github node exists
```

**✅ CORRECT - Declare as input:**
```json
"inputs": {
  "repo": {"type": "string", "required": true, "description": "GitHub repo"}
},
"params": {"repo": "${repo}"}  // ✅ References workflow input
```

**❌ WRONG - Declaring input for node output:**
```json
"inputs": {
  "analysis": {  // ❌ Generated by llm node, not user
    "type": "string",
    "required": true,
    "description": "Analysis result"
  }
}
```

**✅ CORRECT - Reference node output:**
```json
// No input declaration needed
"params": {"analysis": "${llm.response}"}  // ✅ References node output
```

**❌ WRONG - Template without declaration:**
```json
"params": {"file": "${output_path}"}  // ❌ output_path not declared anywhere
```

**✅ CORRECT - Declare then reference:**
```json
"inputs": {
  "output_path": {"type": "string", "required": true, "description": "Output file"}
},
"params": {"file": "${output_path}"}  // ✅ Declared in inputs
```

### MCP Tool Nodes

MCP tools use the format: `mcp-{server}-{tool}`

Example json:

```json
{
  "id": "fetch-slack",
  "type": "mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY",
  "params": {
    "channel": "C09C16NAU5B",
    "limit": 10
  }
}
```

Get full specs with:
```bash
uv run pflow registry describe mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY
```

### Workflow Inputs

**Inputs define the API contract for your workflow - what users provide when running it.**

#### Input Object Structure Rules

**Each input MUST be an object with these REQUIRED fields:**

```json
"input_name": {
  "type": "string | number | boolean | array | object",  // REQUIRED
  "description": "Clear explanation of what this is",     // REQUIRED
  "required": true | false                                 // REQUIRED
}
```

**Optional field (only when `required: false`):**
```json
"default": "value"  // OPTIONAL: Only when required is false
```

#### Validation Checklist

Before declaring an input, verify:

- [ ] Is this value provided by the USER (not generated by a node)?
- [ ] Does the input object have `type`, `description`, and `required` fields?
- [ ] Is `type` one of: string, number, boolean, array, object?
- [ ] If `required: false`, does it have a sensible `default` value?
- [ ] Is `description` clear enough for someone who doesn't know the workflow?

#### Common Mistakes

**❌ WRONG - Simple string:**
```json
"input_file": "Path to the file"  // Missing type, required fields
```

**❌ WRONG - Extra fields:**
```json
"repo": {
  "type": "string",
  "description": "GitHub repo",
  "required": true,
  "default": "owner/repo",     // ❌ Can't have default when required=true
  "example": "foo/bar"          // ❌ Extra field not in schema
}
```

**❌ WRONG - Node output as input:**
```json
"inputs": {
  "analysis": {  // ❌ Generated by llm node, not user input
    "type": "string",
    "required": true,
    "description": "Analysis result"
  }
}
```

**✅ CORRECT:**
```json
{
  "inputs": {
    "input_file": {
      "type": "string",
      "required": true,
      "description": "Path to the file to analyze"
    },
    "max_items": {
      "type": "number",
      "required": false,
      "default": 10,
      "description": "Maximum items to process"
    }
  }
}
```

#### When to Set `required: false`

**Use `required: false` when:**
- Parameter has a sensible default value
- Node parameter is optional (check with `pflow registry describe`)
- User can reasonably skip this parameter

**Example - GitHub repo (often optional):**
```json
"repo": {
  "type": "string",
  "required": false,  // ✅ Many GitHub nodes default to current repo
  "description": "GitHub repository in owner/repo format"
}
```

**Rule**: Minimize required inputs. Make optional anything that has smart defaults.

---

### Workflow Outputs

**Outputs expose specific data from your workflow - what users receive when it completes.**

#### When To Skip Outputs Entirely

**Omit the entire `outputs` section when the workflow performs actions (not analysis)**:
- Workflow sends messages, updates databases, creates files
- Success is visible through side effects (message appears, file exists, database updated)
- User doesn't need confirmation data returned

**Examples**: Slack bot, database sync, file automation, API updates


#### Output Object Structure Rules

**Each output MUST be an object with these REQUIRED fields:**

```json
"output_name": {
  "source": "${node_id.output_key}",              // REQUIRED: Template expression
  "description": "Clear explanation of this data"  // REQUIRED
}
```

**That's it. Only `source` and `description`. No other fields allowed.**

#### ⚠️ Critical: Nodes with `Any` Outputs

**Nodes returning `result: Any` (MCP, HTTP) contain massive nested objects.**

```
Is this an automation (send/update/post)?
  → Skip outputs entirely - success is implied

Need the processed data?
  → Output specific field: ${analyze.response}

Never output ${node.result} directly - too verbose
```

#### Validation Checklist

Before declaring an output, verify:

- [ ] Does output object have ONLY `source` and `description` fields?
- [ ] Is `source` a valid template expression (`${node.output}`)?
- [ ] Does the referenced node output actually exist? (check with `pflow registry describe`)
- [ ] Is this output actually useful to the user?

#### Output Selection Strategy

**Choose outputs based on workflow purpose:**

| Workflow Type | Output Strategy | Example |
|---------------|-----------------|---------|
| **Analysis** | Processed data only | `${llm.response}` not `${fetch.result}` |
| **File Creation** | Path only | `${write.file_path}` |

**General Rules:**
1. **First output is most important** - users see this first
2. **Prefer specific over verbose** - `${http.status_code}` not `${http.response}`
3. **Avoid intermediate outputs** - only output from final nodes
4. **Skip metadata** - no `llm_usage`, `response_headers` unless specifically needed

#### Common Mistakes

**❌ WRONG - Extra fields:**
```json
"analysis": {
  "source": "${analyze.response}",
  "description": "Analysis result",
  "type": "string",        // ❌ Not allowed
  "format": "markdown"     // ❌ Not allowed
}
```

**❌ WRONG - Missing template syntax:**
```json
"file_path": {
  "source": "write.file_path",  // ❌ Missing ${}
  "description": "Saved file path"
}
```

**❌ WRONG - File workflow returning full content:**
```json
{
  "outputs": {
    "report": {
      "source": "${format.response}",  // ❌ Full report (already saved to file)
      "description": "Report content"
    }
  }
}
```

**✅ CORRECT - File workflow returns confirmation:**
```json
{
  "outputs": {
    "confirmation": {
      "source": "${write.file_path}",  // ✅ Just the path (content is in file)
      "description": "Path where report was saved"
    },
    "summary": {
      "source": "${analyze.key_findings}",  // ✅ Summary is useful
      "description": "Key findings from analysis"
    }
  }
}
```

**✅ CORRECT - Analysis workflow returns full result:**
```json
{
  "outputs": {
    "analysis": {
      "source": "${llm.response}",  // ✅ Full analysis (this IS the result)
      "description": "Complete analysis report"
    },
    "issues_count": {
      "source": "${fetch.total_count}",  // ✅ Useful metadata
      "description": "Number of issues analyzed"
    }
  }
}
```

#### Output Ordering

**Put most important output FIRST:**

```json
{
  "outputs": {
    "primary_result": {  // ✅ First - what user cares about most
      "source": "${final.result}",
      "description": "The main workflow result"
    },
    "metadata": {  // ✅ Second - supporting information
      "source": "${final.count}",
      "description": "Number of items processed"
    }
  }
}
```

---

## Validation

### Static Validation Command

```bash
uv run pflow --validate-only workflow.json
```

**No runtime parameters needed!** Pflow auto-generates dummy values for inputs but provide them if you want.

**What gets validated**:
- ✅ Schema compliance (JSON structure, required fields)
- ✅ Data flow correctness (execution order, no circular dependencies)
- ✅ Template structure (syntax, node references, output paths)
- ✅ Node types exist in registry

**What does NOT get validated**:
- ❌ Runtime values (that's execution-time)
- ❌ API credentials
- ❌ File existence

**Success output**:
```
✓ Schema validation passed
✓ Data flow validation passed
✓ Template structure validation passed
✓ Node types validation passed

Workflow is valid and ready to execute!
```

**Error output** (actionable):
```
✗ Static validation failed:
  - Unknown node type: 'nonexistent-node'
  - Node 'analyze' references 'read.missing_output'
```

### Iterative Validation

1. Run validation
2. Fix ONE error at a time
3. Re-validate
4. Repeat until ✓

Don't try to fix all errors at once - tackle them sequentially!

### Common Validation Errors

**"Unknown node type 'X'"**
→ Run `pflow registry discover "task that needs X"` OR check exact name with `pflow registry describe` if you know it

**"Template variable '${X}' not found"**
→ Either add `X` to `inputs` section OR verify previous node outputs it with `pflow registry describe`

**"Node 'A' references 'B.output' but B hasn't executed yet"**
→ Reorder edges: B must execute before A in the chain

**"Circular dependency detected"**
→ Check edges array for loops (A→B→A pattern)

**"Missing required parameter 'Y' in node 'Z'"**
→ Check node interface with `pflow registry describe Z` and add required param

**Still stuck?** Run with `--trace` flag and examine error in full execution context.

---

## Testing & Debugging

### Test Individual Nodes (Before Building Workflows)

Test nodes in isolation to verify parameters, discover output structure, and confirm authentication:

```bash
pflow registry run <node-type> param1=value1 param2=value2
```

**Output Modes:**
- `--output-format json` - For programmatic parsing
- `--show-structure` - Discover template paths for `Any` types (critical for MCP)
- `--verbose` - Show parameters and execution details

**Examples:**

```bash
# Test MCP node and see output structure
pflow registry run SLACK_SEND_MESSAGE channel=C123 text="test" --show-structure

# Verify GitHub credentials
pflow registry run github-list-issues repo=owner/repo state=open

# Test complex parameters
pflow registry run http url="https://api.example.com" body='{"key":"value"}' --output-format json
```

**Node name shortcuts (MCP):**
- Full: `mcp-slack-composio-SLACK_SEND_MESSAGE`
- Server-qualified: `slack-composio-SLACK_SEND_MESSAGE`
- Tool only: `SLACK_SEND_MESSAGE` (if unique)

### Execute Workflow

```bash
uv run pflow --output-format json --no-repair --trace workflow.json param1=value param2=value
```

> Using --output-format json --no-repair --trace flags is mandatory when building workflows for AI agents.

### When Output Structure is Unknown

Many MCP tools return `result: Any` because the upstream server doesn't provide output schemas.

**Only investigate when you need to**:
- ✅ Templates reference nested data: `${fetch.result.messages[0].text}`
- ✅ Workflow outputs expose nested fields
- ✅ User wants to optimize the workflow for performance only passing the most important data to LLM nodes
- ❌ Just passing data through: `${fetch.result}` is fine
- ❌ Sending to LLM: It handles any structure

**How to discover output structure**:

```bash
# 1. Run with trace
pflow --trace workflow.json

# 2. Examine output
cat ~/.pflow/debug/workflow-trace-*.json | jq '.nodes[0].outputs'

# 3. Use discovered structure
# Example output:
{
  "result": {
    "messages": [
      {"text": "Hello", "user": "U123", "ts": "1234567890.123"}
    ],
    "has_more": false
  }
}

# 4. Update templates
${fetch.result.messages[0].text}
```

### Execution Flags

```bash
--trace                 # Save execution trace to ~/.pflow/debug/ (RECOMMENDED for debugging)
--no-repair            # Disable auto-repair on errors
--output-format json   # JSON output
```

> **Critical**: ALWAYS use `--trace` flag when building workflows. It saves complete execution data including ALL available fields from nodes, essential for debugging template errors.

### Understanding Template Errors

When you get a template error like `${fetch.messages}` not found:

**1. Check the error output**:
```
Available fields in node (showing 5 of 147):
  - result
  - status
  - metadata
  - timestamp
  - request_id
  ... and 15 more (in error details)

📁 Complete field list available in trace file
   Run with --trace flag to save to ~/.pflow/debug/
```

**2. Use the trace file for complete field list**:
```bash
# Find the latest trace
ls -lt ~/.pflow/debug/workflow-trace-*.json | head -1

# View all available fields from the failed node
cat ~/.pflow/debug/workflow-trace-*.json | jq '.events[] | select(.node_id == "fetch") | .shared_after.fetch | keys'
```

**3. Update your template** with the correct field path:
```json
{
  "params": {
    "text": "${fetch.result.messages}"  // Correct path from trace
  }
}
```

> **Why this matters**: Error messages show only the first 20 fields to avoid overwhelming output. The trace file contains ALL fields (no limit), which is critical when nodes return 100+ fields.

> Note: ALWAYS use ALL these three flags when building workflows for better error handling and debugging.

---

## Saving Workflows

**When to save**: After completing Step 10 in the development loop - your workflow is tested and working correctly.

Saving moves your workflow from local drafts (`.pflow/workflows/`) to the global library (`~/.pflow/workflows/`) for reuse across all projects.

### Save to Global Library

```bash
uv run pflow workflow save FILE_PATH NAME "Description"
```

**Example**:
```bash
uv run pflow workflow save .pflow/workflows/draft.json slack-qa-bot "Answers Slack questions and logs to Sheets"
```

**Name requirements** (auto-validated):
- Lowercase letters, numbers, hyphens only
- Max 30 characters
- Examples: `file-analyzer`, `pr-reviewer`, `slack-bot`

**Optional flags**:
- `--delete-draft` - Remove source file after save
- `--force` - Overwrite if exists
- `--generate-metadata` - AI-generate rich metadata (requires LLM)

**Success** (now shows required parameters):
```
✓ Saved workflow 'workflow-name' to library
  Location: ~/.pflow/workflows/workflow-name.json
  Execute with: pflow workflow-name param1=<value> param2=<value>
  Optional params: param2
```

> **Important**: The save command shows parameter placeholders, but YOU should tell the user how to run with their ACTUAL values:
> Example: If user provided "channel C09C16NAU5B", show: `✨ pflow workflow-name channel-id=C09C16NAU5B limit=10` (without line breaks)
> This lets them immediately test the workflow with their specific configuration.
>
> **CRITICAL**: Always write commands on a SINGLE line (no line breaks or wrapping) to ensure easy copy-paste. Even with very long parameter lists, keep the ENTIRE command on ONE line. Users need to copy-paste commands directly without editing.

### Library Locations

- **Local drafts**: `.pflow/workflows/` (project-specific)
- **Global library**: `~/.pflow/workflows/` (reusable everywhere)

> Always use the local drafts directory when creating new workflows for iteration and testing before saving to the global library.

---

## Executing Workflows

### From File

```bash
uv run pflow workflow.json param1=value param2=value
```

### From Library

```bash
uv run pflow my-saved-workflow param1=value param2=value
```

### Check What's Available

```bash
uv run pflow workflow list                 # List saved workflows
uv run pflow workflow describe my-workflow # Show workflow details
```

---

## Context Efficiency

**You have limited context space. Every token matters.**

### Understanding Your Constraints

As an AI agent, you work differently than traditional programs:
- ❌ **Limited context**: You can't hold unlimited data in memory
- ✅ **Natural language strength**: You excel at processing unstructured data
- ❌ **Token cost**: Every character you read and write has a cost
- ✅ **Smart filtering**: You can understand relevance better than exact matching

### Efficient Strategies

#### 1. Only Investigate MCP Outputs When Needed

**Many MCP tools return `result: Any` (unstructured data).**

**✅ ONLY investigate when:**
- Templates need nested data: `${fetch.result.messages[0].text}`
- Workflow outputs expose nested fields
- User explicitly asks to optimize data flow

**❌ SKIP investigation when:**
- Just passing data through: `${fetch.result}` → works fine
- Sending to LLM: `prompt: "Analyze ${data.result}"` → LLM handles any structure
- Output is final: Workflow ends there

**Why**: LLMs naturally handle unstructured data. Use that strength!

#### 2. Request Only Needed Fields

**Some nodes support filtering/pagination. Use them:**

```json
// ❌ Inefficient
{"id": "fetch", "type": "github-list-issues", "params": {"limit": 100}}

// ✅ Efficient
{"id": "fetch", "type": "github-list-issues", "params": {
  "limit": 10,              // Only get what you need
  "state": "open",          // Filter at source
  "labels": "bug,critical"  // Be specific
}}
```

### Token Efficiency Checklist

Before building a workflow:
- [ ] Am I fetching only what I need? (use filters, limits if possible)
- [ ] Can I combine steps instead of chaining many small nodes?
- [ ] Am I investigating MCP outputs unnecessarily?
- [ ] Are my queries specific enough to avoid broad searches?
- [ ] Can an LLM handle this naturally without pre-processing?

**Remember**: Efficient != minimal nodes. Efficient = minimal unnecessary context.

---

## Workflow Smells

**🚩 Red flags that indicate poor workflow design:**

1. **No inputs section** → Not reusable
2. **Hardcoded IDs/paths** → Will break for other users
3. **Repeated literal values** → Should reference one input
4. **Over-specific input names** → `slack_channel_C123` instead of `channel`
5. **Missing defaults for optional params** → Poor user experience
6. **Too many required inputs** → Consider smart defaults
7. **Coupling service to workflow** → Input named `github_repo` instead of generic `repo`
8. **Exposing .result outputs** → `${mcp-node.result}` is too verbose

**Quick Fix Guide:**
- See hardcoded value? → Make it an input
- See repeated value? → Reference single input
- See specific name? → Generalize it
- See many required fields? → Add defaults where sensible

---

## Common Mistakes

Learn from others' experiences!

### ❌ Mistake 1: Skipping Workflow Discovery

**What happens**: You build from scratch when a workflow already exists.

**Fix**: ALWAYS run `pflow workflow discover` first (Step 2) - 70% of requests have existing solutions!

### ❌ Mistake 2: Starting with JSON Before Understanding

**What happens**: You write nodes but don't know what data flows where.

**Fix**: Spend 5 minutes in UNDERSTAND phase - map the task first!

### ❌ Mistake 3: Not Using `pflow registry discover`

**What happens**: You manually search through hundreds of nodes.

**Fix**: Use `pflow registry discover "what you need"` - let LLM find nodes for you!

### ❌ Mistake 4: Not Checking Node Output Structure

**What happens**: Templates like `${fetch.data.items}` fail because output is `${fetch.result.items}`.

**Fix**: Run `pflow registry describe node-type` BEFORE writing templates.

### ❌ Mistake 5: Building Everything at Once

**What happens**: 10 nodes, 50 errors, impossible to debug.

**Fix**: Build 2 nodes → validate → add 1 more → validate → repeat.

### ❌ Mistake 6: Ignoring Validation Errors

**What happens**: You execute anyway, get cryptic runtime errors.

**Fix**: Trust validation - it catches 90% of issues before execution!

### ❌ Mistake 7: Using Generic Node IDs

**What happens**: Templates like `${node2.output}` are unreadable.

**Fix**: Use descriptive IDs like `${fetch-messages.result}` for clarity.

### ❌ Mistake 8: Forgetting MCP Format

**What happens**: `pflow registry describe SLACK_SEND_MESSAGE` → "Unknown node"

**Fix**: Use full format: `mcp-slack-composio-SLACK_SEND_MESSAGE`

### ❌ Mistake 9: Using `inputs` Instead of `params`

**What happens**: Validation fails with schema error.

**Fix**: Node configuration uses `params`, not `inputs`!

### ❌ Mistake 10: Investigating Every `result: Any`

**What happens**: Waste time discovering structures you don't need.

**Fix**: Only investigate when templates need nested paths!

### ❌ Mistake 11: Trying to Add Error Handling in IR

**What happens**: Frustration - branching not supported.

**Fix**: Let pflow's external repair system handle errors. Focus on happy path!

### ❌ Mistake 12: Using Too Many Nodes

**What happens**: Workflow becomes verbose, consumes excessive context, harder to debug.

**Bad example**:
```json
{"id": "get-user", "type": "github-get-user", ...}
{"id": "get-repos", "type": "github-list-repos", ...}
{"id": "get-issues", "type": "github-list-issues", ...}
{"id": "filter", "type": "llm", "params": {"prompt": "Filter relevant repos..."}}
{"id": "analyze", "type": "llm", "params": {"prompt": "Analyze filtered data..."}}
```

**Good example**:
```json
{"id": "analyze", "type": "llm", "params": {
  "prompt": "Analyze GitHub user ${username}'s activity focusing on their top repositories and recent issues..."
}}
```

**Why**: LLM nodes can consolidate multiple operations. Each node call adds overhead.

**When to consolidate**: If operations are naturally chained and intermediate outputs aren't needed elsewhere.

### ❌ Mistake 13: Over-Specifying Node Parameters

**What happens**: Workflows use outdated values, waste tokens, override good defaults.

**Bad example**:
```json
{"id": "analyze", "type": "llm", "params": {
  "prompt": "...",
  "model": "gpt-4",         // ❌ Not requested by user
  "temperature": 0.7,       // ❌ Not requested by user
  "max_tokens": 1000        // ❌ Not requested by user
}}
```

**Good example**:
```json
{"id": "analyze", "type": "llm", "params": {
  "prompt": "..."  // ✅ Only required param, rest use defaults
}}
```

**Fix**: Only set parameters user explicitly requests or workflow logic requires.

---

## Complete Example: Building Any Multi-Service Workflow

Let's demonstrate the thinking process that applies to ANY workflow.

### Example Step 1: UNDERSTAND

**User request**: "Get last 10 messages from [SOURCE], process them, send results to [DESTINATION]"

**Your Thinking Process**:
```
What are the specific values they provided?
- "10" → message_limit input (they might want 20 tomorrow)
- [SOURCE ID] → source_id input (different sources later)
- [DESTINATION ID] → destination_id input (different destinations)

What stays constant?
- The pattern: fetch → process → send
- The transformation logic

What might they configure later?
- Processing parameters
- Output format
- Filtering criteria
```

### Example Step 2: DISCOVER WORKFLOWS

```bash
uv run pflow workflow discover "fetch messages, analyze, send to destination, log to sheets"
```

**Results**: No 70%+ matches found, proceeding to build new.

### Example Step 3: DISCOVER NODES

```bash
uv run pflow registry discover "fetch Slack messages, analyze with AI, send Slack messages, update Google Sheets, get date and time from shell"
```

**Results**: Found all needed nodes with specs.

### Example Step 4: DESIGN

```
fetch-data → process-data → format-output → send-result → log-confirmation

Key decisions:
- Each specific value becomes an input
- Each transformation is a separate node
- Data flows through template variables
```

**Design Principle**: Build the pipeline that could work with ANY similar source/destination pair.

### Example Step 6: BUILD

```json
{
  "inputs": {
    "source_id": {
      "type": "string",
      "required": true,
      "description": "Source identifier"
    },
    "destination_id": {
      "type": "string",
      "required": true,
      "description": "Destination identifier"
    },
    "limit": {
      "type": "number",
      "required": false,
      "default": 10,
      "description": "Number of items to process"
    }
  },
  "nodes": [
    {
      "id": "fetch-data",
      "type": "service-fetch-node",
      "params": {
        "source": "${source_id}",
        "limit": "${limit}"
      }
    },
    {
      "id": "process",
      "type": "llm",
      "params": {
        "prompt": "Process this data: ${fetch-data.result}"
      }
    },
    {
      "id": "send-result",
      "type": "service-send-node",
      "params": {
        "destination": "${destination_id}",
        "content": "${process.response}"
      }
    }
  ],
  "edges": [
    {"from": "fetch-data", "to": "process"},
    {"from": "process", "to": "send-result"}
  ]
  // No outputs - this is an automation workflow
}
```

### Example Step 7: VALIDATE

```bash
uv run pflow --validate-only slack-qa.json
```

Result: ✓ All validations passed!

### Example Step 8: TEST

```bash
uv run pflow --output-format json --no-repair --trace slack-qa.json
```

Result: ✓ Workflow executed successfully!

### Example Step 10: SAVE

Ask the user to verify the results and if they are happy, save the workflow to the global library.

```bash
uv run pflow workflow save slack-qa.json slack-qa-bot "Answers Slack questions and logs Q&A pairs to Google Sheets with timestamps"
```

Result: ✓ Saved to global library!

> Note: Always ask the user before saving the workflow to the global library/registry.

### Example: REUSE

```bash
# Show users exactly how to run with their original values:
uv run pflow workflow-name source_id=ORIGINAL_VALUE destination_id=ORIGINAL_VALUE limit=10

# They can now easily change any parameter:
uv run pflow workflow-name source_id=DIFFERENT_SOURCE destination_id=NEW_DEST limit=20
```

**Key**: Always show the command with the user's original values so they can test immediately.

> Make sure the users new request matches the workflow description and parameters.
> - If it doesn't, ask the user if they want to update the workflow or create a new one.
> - Right now pflow does not support nested workflows so if the user wants to create a similar workflow, you must create a new one from scratch (but you can always copy the existing workflow and modify it).
> - If the user wants to update the workflow, you should still copy the existing workflow and work on it in the .pflow/workflows/ directory and when they user is satisfied, save the workflow to the global library using --force flag to overwrite the existing workflow. Ask the before overwriting!

---

## Quick Reference

### Decision Table: What Becomes an Input?

| User Says | You Create | Why |
|-----------|------------|-----|
| "file.txt" | `input: file_path` | They'll use different files |
| "channel ABC123" | `input: channel` | Different channels later |
| "last 10 items" | `input: limit` (default: 10) | Might want 20 tomorrow |
| "repo owner/name" | `input: repo` | Other repos later |
| "threshold 100" | `input: threshold` (default: 100) | Different thresholds |
| "always use prod" | Hardcode: "prod" | Explicitly said "always" |
| Date format | Hardcode format string | System constraint |
| API endpoint | `input: endpoint` | Different endpoints |

**Rule**: When in doubt → make it an input.

### Command Cheat Sheet

```bash
# Discovery - ALWAYS use AI-powered discovery first
uv run pflow workflow discover "user's request"                # Find existing workflows (Step 2 - MANDATORY)
uv run pflow registry discover "what you need to build"        # Find nodes for building (Step 3)

# Only use these if AI discovery is unavailable
uv run pflow registry describe node1 node2                     # Get specific node specs
uv run pflow workflow describe name                            # Show specific workflow

# Development
uv run pflow --validate-only workflow.json                     # Validate structure

# Saving
uv run pflow workflow save file name "desc"                    # Save workflow to library

# Execution
uv run pflow workflow.json param=value                         # Run from file
uv run pflow saved-workflow param=value                        # Run from library

# Required Execution Flags (use together when testing)
uv run pflow --trace --no-repair --output-format json workflow-name
```

### Common Node Types

- `llm` - AI text processing
- `read-file` - Read file contents
- `write-file` - Write to file
- `shell` - Execute commands
- `http` - HTTP requests
- `mcp-{server}-{tool}` - MCP integrations

### Template Syntax

- `${input_name}` - Workflow input
- `${node.output}` - Node output
- `${node.data.field}` - Nested field
- `${items[0].name}` - Array access

---

## Key Takeaways

### Critical Rules (Never Violate)
1. **🚨 Sequential execution ONLY** - No parallel branches, one edge per node
2. **🚨 Every `${variable}` must be declared** - Either workflow input OR node output
3. **🚨 Check node outputs FIRST** - `pflow registry describe` before writing templates
4. **🚨 Input objects need 3 fields** - `type`, `description`, `required` (nothing else)
5. **🚨 Output objects need 2 fields** - `source`, `description` (nothing else)

### Best Practices (Follow These)
6. **Think before you code** - Pre-build checklist prevents 80% of errors
7. **Use intelligent discovery** - `pflow registry discover` finds relevant nodes
8. **Validate early and often** - Fix one error at a time, re-validate
9. **Build incrementally** - Add 2 nodes, validate, repeat
10. **Use node defaults** - Only override parameters when user explicitly requests
11. **Be context-efficient** - Specific queries > broad searches, investigate `Any` only when needed
12. **Focus on happy path** - Let pflow's repair system handle errors
13. **First output is most important** - Users see this first, choose wisely
14. **Action requests need action** - Don't compare workflows when user wants execution

### Workflow Building Order
**Always follow**: UNDERSTAND → DISCOVER WORKFLOWS → DISCOVER NODES → DESIGN → PLAN → BUILD → VALIDATE → TEST → REFINE → SAVE

## Running pflow

Always run pflow using uv or it will not work in the current environment:

```bash
uv run pflow ...
```

---

## Getting Help

- `pflow --help` - CLI help
- `pflow registry --help` - Registry commands
- `pflow workflow --help` - Workflow commands

---

## The Golden Rule

**Users show you ONE example. You build the GENERAL tool.**

Every specific value they provide is demonstrating what COULD be configured, not what MUST be hardcoded. Build workflows that work tomorrow, for someone else, with different data.

**When reviewing your workflow, ask:**
- Could someone reuse this with different values?
- Did I hardcode anything that might change?
- Would I be frustrated trying to adapt this?

If any answer is "no" or "yes" → add more inputs.

---

**You're now ready to build reusable workflows with pflow!** 🚀
