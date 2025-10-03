# pflow Agent Instructions

**The complete guide for AI agents building workflows autonomously**

This guide teaches you how to think about workflows, discover pflow capabilities, build workflows iteratively, and create production-ready automations. You'll learn not just the commands, but the mental models that make you an effective workflow builder.

---

## Table of Contents

1. [How to Think About Workflows](#how-to-think-about-workflows)
2. [The Agent Development Loop](#the-agent-development-loop)
3. [Common Workflow Patterns](#common-workflow-patterns)
4. [Progressive Learning Path](#progressive-learning-path)
5. [Pre-Build Checklist](#pre-build-checklist)
6. [Discovery Commands](#discovery-commands)
7. [Building Workflows](#building-workflows)
   - [Critical Constraints](#-critical-constraints-read-first)
   - [Node Parameter Philosophy](#node-parameter-philosophy)
   - [Template Variable Syntax](#template-variable-syntax)
   - [Workflow Inputs](#workflow-inputs)
   - [Workflow Outputs](#workflow-outputs)
8. [Validation](#validation)
9. [Testing & Debugging](#testing--debugging)
10. [Saving Workflows](#saving-workflows)
11. [Executing Workflows](#executing-workflows)
12. [Context Efficiency](#context-efficiency)
13. [Common Mistakes](#common-mistakes)
14. [Quick Reference](#quick-reference)

---

## How to Think About Workflows

A workflow is a **data transformation pipeline**. Before writing any JSON, understand your task as a series of transformations.

### The Mental Model

```
[Input Data] → [Transform 1] → [Transform 2] → [Output Data]
```

Every workflow answers three questions:
1. **What data do I start with?** (inputs, files, APIs)
2. **What transformations happen?** (fetch, analyze, format, send)
3. **What data do I produce?** (files, messages, API calls)

### Breaking Down a Task

**Example**: "Analyze Slack messages, answer questions, log to Sheets"

**Step 1 - Identify inputs and outputs**:
- Input: Slack channel ID
- Output: Answered questions in Slack + logged in Sheets

**Step 2 - Map the transformations**:
1. Fetch messages from Slack → Messages data
2. Analyze with AI → Q&A pairs
3. Send answers to Slack → Confirmation
4. Log to Sheets → Sheet rows

**Step 3 - Identify node categories**:
- Data retrieval: Slack fetch (MCP)
- Transformation: LLM for analysis
- Data storage: Slack send (MCP) + Sheets update (MCP)
- Utilities: Shell for timestamps

**Now you're ready to discover specific nodes!**

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

**Example**:
```
User: "Get Slack messages, answer questions with AI, send back, log to Sheets"

Requirements:
- Input: Slack channel ID
- Transformations: fetch → analyze → respond → log
- External services: Slack (read+write), Sheets (write)
- Pattern: Multi-service coordination
- Additional: Need timestamps (shell commands)
```

**Output**: Clear mental model of what needs to happen

### 2. DISCOVER (5 minutes)

Find the right nodes using intelligent discovery.

**Primary method** (use this first):
```bash
pflow registry discover "I need to fetch Slack messages, analyze with AI, send responses, and log to Google Sheets"
```

This uses pflow's internal LLM to intelligently select relevant nodes with complete specs in one shot.

**Fallback methods** (only if LLM discovery fails):
```bash
pflow registry list                          # Browse all available nodes
pflow registry describe node1 node2 node3    # Get specific node specs
```

**Why fallback might be needed**:
- No LLM API key configured
- LLM discovery service unavailable
- You already know exact node names

**What you get**:
- Complete interface specifications
- Parameter types and descriptions
- Output structure
- Usage requirements

**Output**: List of nodes with interfaces understood

### 3. DESIGN (5 minutes)

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

### 4. BUILD (10 minutes)

Create the workflow JSON **step-by-step**.

#### Step 4.1: Declare Workflow Inputs (2 min)

**Only for user-provided values.**

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

#### Step 4.2: Create Nodes Array (5 min)

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

#### Step 4.3: Create Edges Array (1 min)

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

#### Step 4.4: Declare Workflow Outputs (2 min)

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

### 5. VALIDATE (2 minutes per iteration)

Catch structural errors before execution.

```bash
pflow --validate-only workflow.json
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

### 6. TEST (Variable - only when needed)

Execute the workflow to verify it works.

```bash
pflow workflow.json param1=value param2=value
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
pflow --trace test-workflow.json

# 2. Examine trace
cat ~/.pflow/debug/workflow-trace-*.json | jq '.nodes[0].outputs'

# 3. Use discovered structure in templates
```

**Output**: Working workflow that executes successfully

### 7. REFINE (Variable)

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

**Why**: Workflow IR currently supports linear pipelines only. Error handling and repair happens outside the workflow definition via pflow's automatic repair system.

**Output**: Production-ready workflow

### 8. SAVE (1 minute)

**When to do this**: After your workflow is tested and working correctly.

Save to global library for reuse across all projects:

```bash
pflow workflow save .pflow/workflows/your-draft.json workflow-name "Clear description"

# With optional enhancements
pflow workflow save .pflow/workflows/your-draft.json workflow-name "Description" --generate-metadata --delete-draft
```

See [Saving Workflows](#saving-workflows) section below for complete details.

**Output**: Reusable workflow available globally as `pflow workflow-name`

---

## Time Estimates

**Simple workflow** (2-3 nodes): 20-30 minutes
- Example: read-file → llm → write-file

**Complex workflow** (5-7 nodes): 45-60 minutes
- Example: Slack QA + Sheets logging

**Expert mode** (familiar with nodes): 10-15 minutes
- You've built similar workflows before

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
pflow --validate-only level1.json
pflow level1.json input="What is 2+2?"
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
pflow level2.json file="README.md"
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

### ✅ Workflow Discovery Complete
- [ ] I've understood that I must make sure that reusing existing workflows is the best option before building a new one from scratch. But executing a workflow that does not satisfy all the users requirements is the worst option of all.
- [ ] I've used `pflow workflow discover` with specific task description
- [ ] I've verified that no existing workflow matches my task description
- [ ] I've made an educated decision in cooperation with the user to decide to build a new workflow from scratch rather than reuse an existing one if they are not similar enough.

### ✅ Node Discovery Complete
- [ ] I've used `pflow registry discover` with specific task description
- [ ] I've reviewed each node's parameters with `pflow registry describe`
- [ ] I know the exact output structure I'll reference (checked documentation)
- [ ] I understand which outputs are `Any` type and if I need to investigate them

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

**If you can't check all boxes**: Go back to DISCOVER or DESIGN phase. If anything is unclear or if the task is impossible to build, ask the user for clarification by informing them of the current situation.

---

## Discovery Commands

### Two Types of Discovery

pflow has TWO intelligent discovery commands - use them based on your needs:

#### 1. Discover Existing Workflows

```bash
pflow workflow discover "I need to analyze GitHub pull requests"
```

**Use when**: You want to find if someone already built a workflow for your task.

**Returns**: Matching saved workflows from the global library with:
- Workflow name and description
- Input/output specifications
- Confidence score
- Reasoning for the match

**Example output**:
```
## pr-analyzer

**Description**: Analyzes GitHub pull requests
**Inputs**:
  - repo: string (required) - Repository owner/name
  - pr_number: integer (required) - PR number
**Outputs**:
  - analysis: string - Analysis result
**Confidence**: 95%

Match reasoning: This workflow fetches PR data and analyzes it with AI...
```

#### 2. Discover Nodes for Building

```bash
pflow registry discover "I need to fetch Slack messages and analyze with AI"
```

**Use when**: You're building a NEW workflow and need to find the right nodes.

**Returns**: Curated list of relevant nodes with complete specifications.

**Returns**:
```markdown
### mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY
Fetches messages from a Slack channel...

**Parameters**:
- channel: str - Channel ID
- limit: int - Number of messages

**Outputs**:
- result: Any - Message data

### llm
General-purpose LLM node...

**Parameters**:
- prompt: str - Text prompt
- system: str - System prompt (optional)

**Outputs**:
- response: any - Model's response
```

### Fallback: Manual Discovery

**Only use if LLM discovery fails** (no API key, service down):

#### Browse All Nodes
```bash
pflow registry list
```

Returns grouped list by package (file, git, github, llm, mcp, etc.)

#### Get Specific Node Specs
```bash
pflow registry describe node1 node2 node3
```

Returns complete interface documentation for each node.

**When to use**:
- You already know exact node names
- LLM discovery unavailable
- You want to browse all options

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
pflow registry describe mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY
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

#### Output Object Structure Rules

**Each output MUST be an object with these REQUIRED fields:**

```json
"output_name": {
  "source": "${node_id.output_key}",              // REQUIRED: Template expression
  "description": "Clear explanation of this data"  // REQUIRED
}
```

**That's it. Only `source` and `description`. No other fields allowed.**

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
| **File Creation** | Confirmation paths | `${write.file_path}` |
| **Analysis** | Full result | `${llm.response}` |
| **API Calls** | Status/confirmations | `${http.status_code}` |
| **Multi-step** | Final result only | Last node's meaningful output |

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
pflow --validate-only workflow.json
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

---

## Testing & Debugging

### Execute Workflow

```bash
pflow --output-format json --no-repair --trace workflow.json param1=value param2=value
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
--trace                 # Save execution trace to ~/.pflow/debug/
--no-repair            # Disable auto-repair on errors
--output-format json   # JSON output
```

> Note ALWAYS use ALL these three flags when building workflows for better error handling and debugging.

---

## Saving Workflows

**When to save**: After completing Step 8 in the development loop - your workflow is tested and working correctly.

Saving moves your workflow from local drafts (`.pflow/workflows/`) to the global library (`~/.pflow/workflows/`) for reuse across all projects.

### Save to Global Library

```bash
pflow workflow save FILE_PATH NAME "Description"
```

**Example**:
```bash
pflow workflow save .pflow/workflows/draft.json slack-qa-bot "Answers Slack questions and logs to Sheets"
```

**Name requirements** (auto-validated):
- Lowercase letters, numbers, hyphens only
- Max 30 characters
- Examples: `file-analyzer`, `pr-reviewer`, `slack-bot`

**Optional flags**:
- `--delete-draft` - Remove source file after save
- `--force` - Overwrite if exists
- `--generate-metadata` - AI-generate rich metadata (requires LLM)

**Success**:
```
✓ Saved workflow 'slack-qa-bot' to library
  Location: ~/.pflow/workflows/slack-qa-bot.json
  Execute with: pflow slack-qa-bot
```

### Library Locations

- **Local drafts**: `.pflow/workflows/` (project-specific)
- **Global library**: `~/.pflow/workflows/` (reusable everywhere)

> Always use the local drafts directory when creating new workflows for iteration and testing before saving to the global library.

---

## Executing Workflows

### From File

```bash
pflow workflow.json param1=value param2=value
```

### From Library

```bash
pflow my-saved-workflow param1=value param2=value
```

### Check What's Available

```bash
pflow workflow list                 # List saved workflows
pflow workflow describe my-workflow # Show workflow details
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

#### 1. Use Specific Queries Over Broad Searches

**❌ Inefficient workflow (fetch everything, then filter):**
```json
{
  "nodes": [
    {
      "id": "fetch-all",
      "type": "github-list-issues",
      "params": {
        "limit": 100  // Fetches 100 issues = ~10,000 tokens
      }
    },
    {
      "id": "filter",
      "type": "llm",
      "params": {
        "prompt": "Filter to only critical bugs from last week: ${fetch-all.issues}"
      }
    }
  ]
}
```
**Result**: LLM processes 10,000 tokens to find 3 relevant issues.

**✅ Efficient workflow (filter at source):**
```json
{
  "nodes": [
    {
      "id": "fetch-specific",
      "type": "github-search-issues",
      "params": {
        "query": "label:bug label:critical created:>2024-01-01",  // Filter at API level
        "limit": 10  // Only fetches 10 issues = ~300 tokens
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "params": {
        "prompt": "Analyze these bugs: ${fetch-specific.issues}"
      }
    }
  ]
}
```
**Result**: LLM processes 300 tokens. Same result, 97% less context used.

**Pattern**: Use search/filter parameters at the source node, not LLM filtering after fetching.

#### 2. Only Investigate MCP Outputs When Needed

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

#### 3. Chain Operations When Intermediate Outputs Aren't Needed

**❌ Inefficient:**
```json
{
  "nodes": [
    {"id": "fetch1", "type": "http", "params": {"url": "api/users"}},
    {"id": "fetch2", "type": "http", "params": {"url": "api/posts"}},
    {"id": "fetch3", "type": "http", "params": {"url": "api/comments"}},
    {"id": "combine", "type": "llm", "params": {"prompt": "Merge all data..."}}
  ]
}
```

**✅ Efficient:**
```json
{
  "nodes": [
    {"id": "analyze", "type": "llm", "params": {
      "prompt": "Fetch and analyze user activity from our API..."
    }}
  ]
}
```

**When LLMs can handle the entire operation, let them.**

#### 4. Request Only Needed Fields

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
- [ ] Am I fetching only what I need? (use filters, limits)
- [ ] Can I combine steps instead of chaining many small nodes?
- [ ] Am I investigating MCP outputs unnecessarily?
- [ ] Are my queries specific enough to avoid broad searches?
- [ ] Can an LLM handle this naturally without pre-processing?

**Remember**: Efficient != minimal nodes. Efficient = minimal unnecessary context.

---

## Common Mistakes

Learn from others' experiences!

### ❌ Mistake 1: Starting with JSON Before Understanding

**What happens**: You write nodes but don't know what data flows where.

**Fix**: Spend 5 minutes in UNDERSTAND phase - map the task first!

### ❌ Mistake 2: Not Using `pflow registry discover`

**What happens**: You manually search through hundreds of nodes.

**Fix**: Use `pflow registry discover "what you need"` - let LLM find nodes for you!

### ❌ Mistake 3: Not Checking Node Output Structure

**What happens**: Templates like `${fetch.data.items}` fail because output is `${fetch.result.items}`.

**Fix**: Run `pflow registry describe node-type` BEFORE writing templates.

### ❌ Mistake 4: Building Everything at Once

**What happens**: 10 nodes, 50 errors, impossible to debug.

**Fix**: Build 2 nodes → validate → add 1 more → validate → repeat.

### ❌ Mistake 5: Ignoring Validation Errors

**What happens**: You execute anyway, get cryptic runtime errors.

**Fix**: Trust validation - it catches 90% of issues before execution!

### ❌ Mistake 6: Using Generic Node IDs

**What happens**: Templates like `${node2.output}` are unreadable.

**Fix**: Use descriptive IDs like `${fetch-messages.result}` for clarity.

### ❌ Mistake 7: Forgetting MCP Format

**What happens**: `pflow registry describe SLACK_SEND_MESSAGE` → "Unknown node"

**Fix**: Use full format: `mcp-slack-composio-SLACK_SEND_MESSAGE`

### ❌ Mistake 8: Using `inputs` Instead of `params`

**What happens**: Validation fails with schema error.

**Fix**: Node configuration uses `params`, not `inputs`!

### ❌ Mistake 9: Investigating Every `result: Any`

**What happens**: Waste time discovering structures you don't need.

**Fix**: Only investigate when templates need nested paths!

### ❌ Mistake 10: Trying to Add Error Handling in IR

**What happens**: Frustration - branching not supported.

**Fix**: Let pflow's external repair system handle errors. Focus on happy path!

### ❌ Mistake 11: Using Too Many Nodes

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

### ❌ Mistake 12: Over-Specifying Node Parameters

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

## Complete Example: Building a Complex Workflow

Let's build the Slack QA + Sheets logging workflow from scratch.

### Step 1: UNDERSTAND

**User request**: "Get last 10 Slack messages, answer questions with AI, send back, log to Sheets with timestamps"

**Analysis**:
- Input: Slack channel ID, Sheets ID
- Transformations: fetch → analyze → respond → log
- Services: Slack (read+write), Sheets (write), Shell (date/time)
- Pattern: Multi-service coordination

### Step 2: DISCOVER

```bash
pflow registry discover "fetch Slack messages, analyze with AI, send Slack messages, update Google Sheets, get date and time from shell"
```

**Results**: Found all needed nodes with specs.

### Step 3: DESIGN

```
get-date (shell) → stdout
     ↓
get-time (shell) → stdout
     ↓
fetch-messages (mcp-slack-FETCH) → result
     ↓
analyze (llm) → response (Q&A pairs as JSON)
     ↓
format-for-sheets (llm) → response (2D array: [[date, time, q, a], ...])
     ↓
send-response (mcp-slack-SEND) → result
     ↓
log (mcp-sheets-UPDATE) → result (inserts multiple rows)
```

**Key pattern**: Since pflow doesn't support loops, we use LLM to transform Q&A pairs into a 2D array where each Q&A becomes a row. Google Sheets BATCH_UPDATE can insert multiple rows in one call. Try to use clever workaround like this to solve the users problem. Always strive to do exactly what the user asks for and if its not possible, say so!

### Step 4: BUILD

```json
{
  "nodes": [
    {
      "id": "get-date",
      "type": "shell",
      "params": {"command": "date +%Y-%m-%d"}
    },
    {
      "id": "get-time",
      "type": "shell",
      "params": {"command": "date +%H:%M:%S"}
    },
    {
      "id": "fetch-messages",
      "type": "mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY",
      "params": {
        "channel": "C09C16NAU5B",
        "limit": 10
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "params": {
        "prompt": "Analyze these Slack messages and identify questions. Answer each question.\n\nMessages: ${fetch-messages.result}\n\nReturn JSON: {\"qa_pairs\": [{\"question\": \"...\", \"answer\": \"...\"}]}"
      }
    },
    {
      "id": "format-for-sheets",
      "type": "llm",
      "params": {
        "prompt": "Convert this Q&A data into a 2D array for Google Sheets. Each Q&A pair should be a separate row with: [date, time, question, answer].\n\nDate: ${get-date.stdout}\nTime: ${get-time.stdout}\nQ&A pairs: ${analyze.response}\n\nReturn ONLY a JSON array like: [[\"2025-01-01\", \"12:00:00\", \"question 1\", \"answer 1\"], [\"2025-01-01\", \"12:00:00\", \"question 2\", \"answer 2\"]]"
      }
    },
    {
      "id": "send-response",
      "type": "mcp-slack-composio-SLACK_SEND_MESSAGE",
      "params": {
        "channel": "C09C16NAU5B",
        "markdown_text": "**Q&A Summary**\\n\\n${analyze.response}"
      }
    },
    {
      "id": "log",
      "type": "mcp-googlesheets-composio-GOOGLESHEETS_BATCH_UPDATE",
      "params": {
        "spreadsheet_id": "1rWrTSw0XT1D-e5XsrerWgupqEs-1Mtj-fT6e_kKYjek",
        "sheet_name": "Sheet1",
        "valueInputOption": "USER_ENTERED",
        "values": "${format-for-sheets.response}"
      }
    }
  ],
  "edges": [
    {"from": "get-date", "to": "get-time"},
    {"from": "get-time", "to": "fetch-messages"},
    {"from": "fetch-messages", "to": "analyze"},
    {"from": "analyze", "to": "format-for-sheets"},
    {"from": "format-for-sheets", "to": "send-response"},
    {"from": "send-response", "to": "log"}
  ]
}
```

### Step 5: VALIDATE

```bash
pflow --validate-only slack-qa.json
```

Result: ✓ All validations passed!

### Step 6: TEST

```bash
pflow --output-format json --no-repair --trace slack-qa.json
```

Result: ✓ Workflow executed successfully!

### Step 7: SAVE

Ask the user to verify the results and if they are happy, save the workflow to the global library.

```bash
pflow workflow save slack-qa.json slack-qa-bot "Answers Slack questions and logs Q&A pairs to Google Sheets with timestamps"
```

Result: ✓ Saved to global library!

> Note: Always ask the user before saving the workflow to the global library/registry.

### Step 8: REUSE

```bash
pflow slack-qa-bot param-1=value param-2=value
```

Done! Workflow runs anytime.

> Make sure the users new request matches the workflow description and parameters.
> - If it doesn't, ask the user if they want to update the workflow or create a new one.
> - Right now pflow does not support nested workflows so if the user wants to create a similar workflow, you must create a new one from scratch (but you can always copy the existing workflow and modify it).
> - If the user wants to update the workflow, you should still copy the existing workflow and work on it in the .pflow/workflows/ directory and when they user is satisfied, save the workflow to the global library using --force flag to overwrite the existing workflow. Ask the before overwriting!

---

## Quick Reference

### Command Cheat Sheet

```bash
# Discovery
pflow registry discover "natural language description"  # Primary method
pflow registry list                                     # Browse all nodes (**AVOID**: use registry discover to avoid context pollution)
pflow registry describe node1 node2                     # Get node specs

# Development
pflow --validate-only workflow.json                     # Validate structure

# Library
pflow workflow discover "what you want to build"        # Discover workflows to reuse
pflow workflow list                                     # List saved workflows (**AVOID**: use workflow discover to avoid context pollution)
pflow workflow save file name "desc"                    # Save workflow
pflow workflow describe name                            # Show workflow details

# Execution
pflow workflow.json param=value                         # Run from file
pflow saved-workflow param=value                        # Run from library

## Required Execution Flags
pflow --trace workflow-name                             # Run with trace
pflow --no-repair workflow-name                         # Disable auto-repair
pflow --output-format json workflow-name               # JSON output
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

### Workflow Building Order
**Always follow**: UNDERSTAND → DISCOVER → DESIGN → BUILD → VALIDATE → TEST → REFINE → SAVE

---

## Getting Help

- `pflow --help` - CLI help
- `pflow registry --help` - Registry commands
- `pflow workflow --help` - Workflow commands

---

**You're now ready to build workflows autonomously with pflow!**

Start with Level 1, work through the patterns, and soon you'll be building complex multi-service workflows with confidence. Remember: understand → discover → design → build → validate → test → refine → save.

Happy workflow building! 🚀
