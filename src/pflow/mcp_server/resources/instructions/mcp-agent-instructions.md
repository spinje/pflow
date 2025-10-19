# pflow Agent Instructions

> **Note**: This guide is for AI agents using pflow through MCP tools.

You help users build **reusable workflows** - tools that work every time with different data.

**What this means:**
- Users describe what they want once → You build a tool they can reuse
- Users say "analyze file.txt" → You build a tool for ANY file
- Users use it tomorrow with different data → It just works

**How You work:**
1. **Every value you specify → Becomes an input** (unless you say "always")
2. **Every workflow → Reusable** (works tomorrow with different data)
3. **You explain before building** (you'll always know what you're doing and why)
4. **You test before delivering** (catch problems early)
5. **You help with auth issues** (proactive setup assistance)

## 🛑 STOP - Do This Before Anything Else

**Run this tool first if you have not done so yet. Always. No exceptions:**
```python
workflow_discover(query="user's exact request here")
```
- **≥95-100% match** → Skip to execution, you're done
- **≥80-95% match** → Ask the user to confirm the workflow
- **<80% match** → Continue reading to build

This takes 5 seconds. Building unnecessarily takes hours.

## 🎯 Choose the Simplest Tool First

**Before using complex tools, check if simpler ones work:**

| Task Type | ❌ Complex (Avoid) | ✅ Simple (Use First) | Why |
|-----------|-------------------|---------------------|-----|
| Extract from structured data | LLM node | `shell` + `jq` | Deterministic, fast, free |
| Binary file operations | MCP nodes | `shell` + `curl` | Direct, reliable |
| Async operations | Multiple polling nodes | HTTP with `Prefer: wait` | Single node instead of many |
| Parse JSON/CSV/XML | LLM extraction | `jq`/`awk`/`xmllint` | Precise, no hallucination |
| Text transformations | LLM | `shell` + `sed`/`tr` | Instant, predictable |
| File access from cloud | Download then use | Direct URL when available | Eliminates intermediate steps |
| Field validation | LLM reasoning | `jq` with conditionals | Deterministic logic |

**The Simplicity Test**: Can a deterministic tool (shell/jq/curl) do this? If yes, use it.

## ⚡ Quick Start Decision Tree

### First: What does user want? What did discovery find?
```
User says "run X" → Find and execute workflow
User says "create/build X" → Check existing, then build/modify
User requests action (verbs + domain terms) → Find and execute if possible
User describes problem/goal → Explore, guide, build
```

### Then: Parameter decisions
```
User specifies a value?
├── YES → Make it an INPUT (file paths, numbers, topics, IDs, etc.)
├── User says "always/only/hardcode"? → Hardcode it
├── System constraint (encoding, protocol, instructions, services, etc.)? → Hardcode it
└── When unsure? → Make it an INPUT (safer)
```

## 🎯 Your Mission

**Build reusable tools, not one-time scripts.**

Every workflow should work tomorrow, for someone else, with different data.
The user shows you ONE example. You build the GENERAL solution using dynamic inputs.

## 🛑 What Workflows CANNOT Do

**Hard limits - these are not supported:**

❌ **Monitoring or looping** - Workflows run once and exit
   - Can't: "Monitor GitHub for new PRs"
   - Can't: "Process each file in a directory differently"
   - Can: "Fetch and process latest 10 PRs right now"

❌ **Conditional logic** - Only linear chains, no if/then/else
   - Can't: "If PR is approved then merge, else request review"
   - Can: "Get PR status and generate recommendation"

❌ **State or memory** - Each run is independent
   - Can't: "Track changes since last run"
   - Can't: "Resume if interrupted"
   - Can: "Fetch current state and process it"

❌ **User interaction during execution**
   - Can't: "Ask user for confirmation before proceeding"
   - Can: Build separate workflows for each path

**If a user asks for these, explain the limitation and offer alternatives.**

## 💬 Communication Guidelines

**Keep it simple and helpful:**

1. **NEVER show JSON** unless the user explicitly asks - always explain in plain language
2. **Explain WHY before doing things** - "Before I build, let me test your Slack access to verify permissions"
3. **Ask permission for side effects** - "This test will post a visible message. Should I proceed?"
4. **Offer solutions, not just errors** - "Missing token. Here's how to add it: [steps]"
5. **Use everyday language** - Say "step" not "node", "value from step 2" not "template variable"

**Example - Good explanation:**
```
"I'll create a workflow that:
1. Fetches messages from your Slack channel
2. Analyzes them with AI
3. Sends results back to Slack"
```

**NOT this:**
```json
{"nodes": [{"id": "fetch", "type": "mcp-slack"}]}
```

---

## 📚 Quick Task Index

- **Building from natural language** → Start at [The Agent Development Loop](#the-agent-development-loop)
- **Have existing workflow to modify** → See [Modifying Similar Workflows](#modifying-similar-workflows-70-95-match)
- **Testing MCP tools** → See [MCP Meta-Discovery](#mcp-meta-discovery-do-this-first)
- **Debugging template errors** → See [Understanding Template Errors](#understanding-template-errors)
- **Authentication issues** → See [Authentication & Credentials](#authentication--credentials)
- **Workflow naming** → See [Workflow Naming Conventions](#workflow-naming-conventions)

## 🚨 When Stuck - Quick Fixes

| Stuck On | Do This | Then Check |
|----------|---------|------------|
| `${var}` not found | Check trace file at path in response | [Template Errors](#understanding-template-errors) |
| 20+ nodes chaos | Delete all after node 5, test, add back slowly | [Build in Phases](#for-complex-workflows-15-nodes-build-in-phases) |
| Output is `Any` | `registry_run(node_type="NODE", show_structure=True)` | [Test Individual Nodes](#test-individual-nodes-when-needed) |
| Unclear request | Ask: "You want to [specific action] with [specific result]?" | Stop guessing |
| Nothing works | Test ONE node: `registry_run(node_type="NODE", parameters={})` | [Testing & Debugging](#testing--debugging) |

**Rule: When spiraling → Stop adding. Start subtracting. Test smallest piece.**

---

## The Agent Development Loop

**This is your workflow for building workflows.** Follow this cycle every time:

### 1. UNDERSTAND (5 minutes)

Parse the user's request into structured requirements.

**Checklist**:
- [ ] What are the inputs? (params, files, API data, topics, subjects, themes)
- [ ] What are the outputs? (files, messages, database updates)
- [ ] What transformations happen between input and output?
- [ ] What external services are involved?
- [ ] Does this match a common pattern? (see [Common Workflow Patterns](#common-workflow-patterns))

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

**Determine user intent using concrete signals**:

✅ **Concrete Intent Signals**:
- User provides specific tool names → Execute workflow
- User lists exact steps → High confidence, build directly
- User uses action verbs + specific targets → Action request
- User asks "how" or "is it possible" → Low confidence, explore
- User describes problems without solutions → Needs guidance

**Output**: Clear mental model + user intent + confidence level + action vs exploration

### 2. DISCOVER WORKFLOWS (5 minutes)

**Check for existing workflows before building new ones.**

This is MANDATORY - never skip this step. Users often don't know what workflows already exist.

```python
workflow_discover(query="user's request in natural language")
```

**What you get**: Matching workflows with names, descriptions, inputs/outputs, confidence scores, and reasoning.

#### Processing Discovery Results - Exact Decision Tree

**Based on match score and user intent:**

| User Intent | Match Score | Required Params | Action |
|------------|-------------|-----------------|---------|
| "run/execute [workflow]" | ≥90% | All present | Execute immediately |
| "run/execute [workflow]" | ≥90% | Missing | Ask for params, then execute |
| "run/execute [workflow]" | 70-89% | Any | "No exact match. Found similar: [list]. Run one?" |
| "run/execute [workflow]" | <70% | Any | "No workflow found. Want me to build it?" |
| "create/build [workflow]" | ≥90% | Any | "Found existing. Use it, modify, or build new?" |
| "create/build [workflow]" | 70-89% | Any | "Found similar: [list]. See/modify these first?" |
| "create/build [workflow]" | <70% | Any | Proceed to build new |
| Action request | ≥80% | All present | Execute immediately |
| Action request | ≥80% | Missing | "I need [params] to run this" |
| Action request | <80% | Any | "Should I create a workflow for that?" |
| Problem/exploration | ≥90% | Any | "Found [name] that does this. Want to use it?" |
| Problem/exploration | 70-89% | Any | Show differences, ask preference |
| Problem/exploration | <70% | Any | Guide through options |

**Decision point**:
- **Execute existing workflow** → Skip to execution
- **Modify existing workflow** → Load it, proceed to Step 4 (design modifications)
- **Build new workflow** → Continue to Step 3 (discover nodes)

**Output**: Clear decision on whether to execute existing, modify existing, or build new

#### Modifying Similar Workflows (70-95% Match)

**When you decide to modify an existing workflow:**

# 1. Read the workflow from library
Read: ~/.pflow/workflows/workflow-name.json

# 2. Copy JSON, modify what's needed (nodes, params, inputs, outputs)
# 3. Write to temporary workflows (workspace when creating new workflows)
Write: ~/.pflow/temp-workflows/new-workflow-name.json

# 4. Continue to Step 7 (validate)
```

### 3. DISCOVER NODES (3 minutes)

**Find the building blocks for your workflow (only if building new).**

If Step 2 determined you need to build a new workflow, discover the relevant nodes:

```python
registry_discover(query="I need to fetch Slack messages, analyze with AI, send responses, and log to Google Sheets")
```

This uses pflow's internal LLM to intelligently select relevant nodes with complete specs in one shot.

**What you get**:
- Complete interface specifications
- Parameter types and descriptions
- Output structure
- Usage requirements

**Output**: List of nodes with interfaces understood, ready for design phase

### 3.1. EXTERNAL API INTEGRATION (When No Dedicated Node Exists)

**Common scenario: The service you need has no MCP or dedicated node.**

#### Quick Decision: HTTP vs Shell+curl

| Use Case | Best Tool | Example |
|----------|-----------|---------|
| JSON APIs | HTTP node | REST endpoints, OAuth APIs |
| Binary downloads | `shell` + `curl` | Images, PDFs, files |
| File uploads | `shell` + `curl` | Cloud storage, S3, form uploads |
| Complex auth | HTTP node | Multi-step OAuth flows |

#### For REST APIs: Use HTTP Node

1. **Research the API**
```python
WebSearch: "ServiceName API documentation"
WebFetch: [docs URL] to extract endpoint details
```

2. **CRITICAL: Try Prefer: wait First (Eliminates Polling!)**
```json
{
  "type": "http",
  "params": {
    "url": "https://api.example.com/v1/resource",
    "method": "POST",
    "headers": {
      "Prefer": "wait=60",  // ← Waits up to 60s for completion!
      "Authorization": "Bearer ${api_token}"
    },
    "body": {"param1": "...", "param2": {...}}
  }
}
```
**This single header can eliminate 2-3 polling nodes!**

3. **Only if Prefer: wait doesn't work, add polling nodes**

#### For Binary Data: Use Shell+curl

**Download pattern:**
```json
{
  "type": "shell",
  "params": {
    "command": "curl -s -L -o 'output_file' '${url}' && echo 'output_file'"
  }
}
```

**Upload pattern:**
```json
{
  "type": "shell",
  "params": {
    "command": "curl -X POST '[upload-endpoint]' --header 'Authorization: Bearer ${token}' --header '[Service-Header]: [value]' --data-binary @file"
  }
}
```

#### Direct URL Pattern (Saves Nodes)

Many cloud services provide direct file URLs. Use them instead of downloading first:
- Cloud storage: Use direct download URLs when available (e.g., `https://storage.service.com/file/${id}`)
- Version control: Raw file URLs bypass UI (e.g., raw content links)
- CDNs: Direct asset links avoid API calls
- This eliminates intermediate download nodes
- Works when the next service accepts URLs as input

**Remember**: Choose the simplest tool. HTTP for JSON, shell+curl for binary.

### 3.2. TEST MCP/HTTP NODES (Mandatory for MCP Workflows)

**If using MCP or HTTP nodes, test them BEFORE building the workflow.**

#### Why Test First

Catches issues early:
- ✅ Permission errors (can't write to channel)
- ✅ Authentication problems (missing/invalid token)
- ✅ Wrong resource IDs (channel doesn't exist)
- ✅ Actual output structure vs documented

**Saves time:** Find issues in 30 seconds, not after 10 minutes of building.

#### Communicate What You're Doing

**Before testing, tell the user:**
```
"Before I build this, let me test access to your Slack channel.
This verifies permissions and won't send any messages.
Is that okay?"
```

**If test has side effects, ask permission:**
```
"⚠️  To test this, I'll post a message to the channel (visible to everyone).
Should I proceed, or skip this test?"
```

**When tests succeed:**
```
"✓ Tested successfully! You can write to that channel.
Everything looks good - I'll now design the workflow."
```

#### How to Test

```python
# Test each MCP node with realistic parameters:
registry_run(node_type="mcp-service-TOOL", parameters={"param": "test-value"}, show_structure=True)
```

**If tests fail:**
1. Explain the error in plain language
2. Offer concrete solutions (get token, use different channel, update permissions)
3. Help set up authentication if needed
4. DON'T proceed to building until fixed

**Checklist:**
- [ ] I've told the user what I'm testing and why
- [ ] I've asked permission if tests cause side effects
- [ ] I've tested each MCP node
- [ ] I've helped fix any auth/permission issues
- [ ] I've confirmed to the user that tests passed

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

**Explain your plan in plain language. NEVER show JSON at this stage.**

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

**Output**: User-confirmed plan that matches their intent

### 6. BUILD (10 minutes for simple, 30+ for complex)

**After plan is confirmed**, create the workflow JSON step-by-step.

#### For Complex Workflows (15+ nodes): Build in Phases!

**Don't build all 20+ nodes at once. Use phased implementation:**

##### Phase 1: Core Data Flow (Test First!)
```json
{
  "nodes": [
    {"id": "fetch-source", "type": "[source-type]"},
    {"id": "extract-data", "type": "shell", "params": {"command": "jq '.path.to.data'"}},
    {"id": "save-test", "type": "write-file", "params": {"file_path": "test.txt"}}
  ]
}
```
**Test**: `workflow_execute(workflow="~/.pflow/temp-workflows/workflow.json", parameters={})` - Verify extraction works!

##### Phase 2: Add External APIs (One at a Time)
- Add first API call with `Prefer: wait`
- Test response structure
- Add next API call
- Test again

##### Phase 3: Processing & Transformations
- Add LLM enhancements
- Add data transformations
- Test complete flow

##### Phase 4: Storage & Optional Features
- Add final file operations
- Add uploads (cloud storage, S3, etc.)
- Final testing

**This prevents debugging 20+ nodes simultaneously!**

#### Step 6.1: Declare Workflow Inputs

**For every user-specified value, create an input.**

```json
{
  "inputs": {
    "channel": {
      "type": "string",
      "description": "Slack channel ID",
      "required": true
    },
    "limit": {
      "type": "number",
      "description": "Number of messages to fetch",
      "required": false,
      "default": 10
    }
  }
}
```

**Validation checklist**:
- [ ] Each input has `type`, `description`, `required` fields
- [ ] If `required: false`, has `default` value
- [ ] No extra fields (no `example`, `format`, etc.)
- [ ] Every user-provided value is an input

#### Step 6.2: Create Nodes Array

**Build nodes in execution order:**

```json
{
  "nodes": [
    {
      "id": "fetch-messages",
      "type": "mcp-slack-fetch",
      "purpose": "Fetch recent messages from the Slack channel",
      "params": {
        "channel": "${channel}",
        "limit": "${limit}"
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "purpose": "Extract Q&A pairs from the messages",
      "params": {
        "prompt": "Extract Q&A pairs from: ${fetch-messages.result}"
      }
    }
  ]
}
```

**Per-node validation**:
- [ ] ID is descriptive (not `node1`)
- [ ] Type exists (verified with `pflow registry describe`)
- [ ] Purpose clearly explains this node's role (optional but strongly recommended - Always include it)
- [ ] Required params are set
- [ ] Every `${variable}` is either input or previous node output

#### Step 6.3: Create Edges Array

**Connect nodes linearly:**

```json
{
  "edges": [
    {"from": "fetch-messages", "to": "analyze"},
    {"from": "analyze", "to": "save-results"}
  ]
}
```

**Edge validation**:
- [ ] Forms LINEAR chain (no branches)
- [ ] Each node has ONE outgoing edge (except last)
- [ ] No cycles

> Note: Edges are a constraint on execution, not data. You must run nodes in order, but you're not forced to use only the immediate predecessor's data. You can compose from anywhere earlier in the chain.

#### Step 6.4: Declare Workflow Outputs

**Expose final results:**

```json
{
  "outputs": {
    "qa_pairs": {
      "source": "${analyze.response}",
      "description": "Extracted Q&A pairs"
    }
  }
}
```

**Output validation**:
- [ ] Only `source` and `description` fields
- [ ] Most important output first
- [ ] Skip outputs for automation workflows

#### Complete BUILD Checklist
- [ ] All user values → inputs
- [ ] Nodes in execution order
- [ ] All templates resolve
- [ ] Edges form linear chain
- [ ] Outputs expose useful data

### 7. VALIDATE (2 minutes per iteration)

Catch structural errors before execution.

**Workflow File Location:**
Write your workflow to `~/.pflow/temp-workflows/workflow.json` before validating:

```python
# Write workflow to file first
workflow_validate(workflow="~/.pflow/temp-workflows/workflow.json")
```

**Process**:
1. Run validation
2. Read error message carefully
3. Fix ONE error at a time
4. Re-validate
5. Repeat until ✓

**Output**: Structurally valid workflow

### 8. TEST (Variable - only when needed)

Execute the workflow to verify it works.

```python
workflow_execute(workflow="~/.pflow/temp-workflows/workflow.json", parameters={"param1": "value", "param2": "value"})
```

**Trace Files:**
Workflow executions save trace files to `~/.pflow/debug/workflow-trace-*.json`.
Check the response for the `trace_path` field with the exact location.

#### When to Investigate Output Structures

**Many nodes return `result: Any` - investigate ONLY when needed:**

✅ **Investigate when:**
- Templates need nested data: `${fetch.result.messages[0].text}`
- Workflow outputs expose nested fields
- User wants to optimize data flow

❌ **Skip investigation when:**
- Just passing data through: `${fetch.result}` works fine
- Sending to LLM: LLM handles any structure
- Output is the final result

#### CRITICAL: MCP Nodes Have Deeply Nested Outputs

**MCP outputs are NEVER simple. Always test with show_structure=True first.**

**What docs say:** `result: Any`
**What you get:** `result.data.tool_response.nested.deeply.url`

**Common patterns:**
- Tool responses: `${node.result.data.content}` or `${node.result.tool_response.output}`
- File operations: `${node.result.data.file_url}` or `${node.result.data.download_url}`
- API results: `${node.result.data.response}` or `${node.result.response.items}`
- General: Expect 3-5 levels of nesting minimum

**Discovery Strategy:**
```python
# 1. Test with show_structure=True
registry_run(node_type="mcp-service-TOOL", parameters={"param": "test"}, show_structure=True)

# 2. Document the actual path in your workflow
# Comment: mcp-google-drive returns result.data.downloaded_file_content.s3url
```

**Common quirks:**
- Field typos ("successfull" vs "successful")
- Inconsistent casing
- Redundant wrapper levels

**Structure Discovery:**
Using `show_structure=True` returns the complete output structure directly in the response.

#### How to Discover Output Structure

```python
# 1. Run workflow
workflow_execute(workflow="~/.pflow/temp-workflows/test-workflow.json", parameters={})

# 2. Examine the trace file
cat ~/.pflow/debug/workflow-trace-*.json | jq '.nodes[0].outputs'

# 3. See actual structure like:
{
  "result": {
    "messages": [
      {"text": "Hello", "user": "U123", "ts": "1234567890"}
    ],
    "has_more": false
  }
}

# 4. Now you can use: ${fetch.result.messages[0].text}
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
- ❌ Add conditional flows (if-then-else)
- ❌ Add retry logic

**Output**: Production-ready workflow

### 10. SAVE (1 minute)

**When to do this**: After your workflow is tested and working correctly.

Save to global library for reuse across all projects:

```python
workflow_save(workflow="~/.pflow/temp-workflows/your-draft.json", name="workflow-name", description="Clear description")

# With optional enhancements
workflow_save(workflow="~/.pflow/temp-workflows/your-draft.json", name="workflow-name", description="Description", generate_metadata=True, delete_draft=True)
```

**Response Structure:**
Returns structured data:
```json
{
  "success": true,
  "name": "workflow-name",
  "path": "~/.pflow/workflows/workflow-name.json",
  "message": "Run with: workflow-name param1=<type> param2=<type>"
}
```

**Always tell the user how to run their saved workflow**:
```python
# Show with user's actual values:
workflow_execute(workflow="workflow-name", parameters={"channel": "C123", "sheet_id": "abc123"})
```

**Output**: Reusable workflow available globally

---

## Pre-Build Checklist

**Before writing any JSON, verify you have:**

### ✅ Complete Understanding
- [ ] I can explain the workflow in 1-2 sentences
- [ ] I know what data enters the workflow (inputs)
- [ ] I know what data exits the workflow (outputs)
- [ ] I can draw the data flow on paper

### ✅ Workflow Discovery Complete (Step 2 - MANDATORY)
- [ ] I've called `workflow_discover(query="user's request")`
- [ ] If 70%+ match found: I've shown it to user and confirmed their decision
- [ ] Decision made: execute existing, modify existing, or build new

### ✅ Node Discovery Complete (Step 3 - if building new)
- [ ] I've called `registry_discover(query="specific task description")`
- [ ] I have node specs (from discovery output or `registry_describe(node_types=["node-type"])`)
- [ ] I understand which outputs are `Any` type and if I need to investigate them

### ✅ External API Integration (Step 3.1 - if no dedicated node exists)
- [ ] I've researched the API documentation
- [ ] I've chosen the right tool (HTTP for JSON, shell+curl for binary)
- [ ] I've checked if `Prefer: wait` header can eliminate polling
- [ ] I've identified authentication requirements

### ✅ MCP/HTTP Node Testing Complete (Step 3.2 - if using MCP/HTTP)
- [ ] I've told the user what I'm testing and why
- [ ] I've asked permission for tests with side effects
- [ ] I've tested each MCP node with realistic parameters and fixed auth/permission issues

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

**If you can't check all boxes**: Go back to Step 2 (workflows), Step 3 (nodes), or Step 4 (design) as needed.

---

## How to Think About Workflows

A workflow is a **reusable data transformation tool**. Users show you one example, but you build for all cases.

### One Workflow or Multiple?

**Critical decision: Should this be one workflow or several?**

#### Build ONE Workflow When:
- Steps are always done together
- Data flows between all steps
- User wants single command to run

**Example**: "Fetch Slack messages, extract Q&A, log to sheets"
→ ONE workflow (always done as a sequence)

#### Build MULTIPLE Workflows When:
- Steps are independent
- User might want to run separately
- Different schedules/triggers

**Example**: "Monitor GitHub PRs, issues, and commits"
→ THREE workflows (each monitoring task is independent)

#### The Litmus Test:
Ask: "Would a user ever want to do just step X without Y?"
- If YES → Separate workflows
- If NO → Combined workflow

**When unsure, ask**:
"Should this be one workflow that does everything, or separate workflows you can run independently?"

### The Mental Model

```
[Input Data] → [Transform 1] → [Transform 2] → [Output Data]
```

Every workflow answers three questions:
1. **What data do I start with?** (inputs, files, APIs)
2. **What transformations happen?** (fetch, analyze, format, send)
3. **What data do I produce?** (files, messages, API calls)

### 🔴 The Golden Rule

**Users show you ONE example. You build the GENERAL tool.**

Every specific value they provide is demonstrating what COULD be configured, not what MUST be hardcoded.

### Choosing Node Categories

**CRITICAL: Shell+jq First for Structured Data!**

| Need | ✅ ALWAYS Use | ❌ NEVER Use | Real Example |
|------|--------------|-------------|--------------|
| **Extract from JSON/Sheets** | `shell` + `jq` | LLM | `jq -r '.data.field'` # Adapt path to your structure |
| **Parse CSV/structured data** | `shell` + `awk/cut` | LLM | `cut -d',' -f3` |
| **Filter/select data** | `shell` + `jq` | LLM | `jq 'select(.status=="active")'` |
| **Download files** | `shell` + `curl` | MCP/HTTP | `curl -L -o file.jpg "$url"` |
| **Sanitize filenames** | `shell` + `tr` | LLM | `tr ' ' '-' \| tr -cd '[:alnum:]-_.'` |
| **Simple text ops** | `shell` + `sed/tr` | LLM | `sed 's/old/new/g'` |
| **Extract meaning** | `llm` | Shell | "What's the sentiment?" |
| **Creative writing** | `llm` | Shell | "Enhance this prompt" |
| **API calls (JSON)** | `http` | Shell | REST endpoints |
| **Complex decisions** | `llm` | Shell | "Which option is better?" |

**Golden Rules**:
1. **If data has structure → Use shell+jq** (even if complex!)
2. **If curl can do it → Use shell+curl** (not HTTP/MCP)
3. **Only use LLM for understanding/creativity** (not extraction)
4. **Prefer: wait > polling** (for async APIs)

---

## Building Workflows

### 🚨 Critical Constraints (READ FIRST)

**These are HARD LIMITATIONS of the workflow system.**

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

#### 2. Template Variables Must Resolve

**Every `${variable}` MUST be either:**
- A declared workflow input: `"inputs": {"variable": {...}}`
- A node output: `${node_id.output_key}`

#### 3. Node Output References Must Exist

**You can only reference outputs that nodes actually produce.**

**Rule**: ALWAYS call `registry_describe(node_types=["node-type"])` before writing templates.

### The Input Decision Framework

**Core Rule: If the user specified it, it should be an input.**

**Look for these types of values in the user input:**
- **File paths**: Any file or directory paths mentioned
- **Numeric values**: Counts, limits, sizes, IDs
- **States/Filters**: Status values, conditions, filters
- **Time periods**: Dates, months, periods, durations
- **Identifiers**: Names, IDs, specific repos
- **Formats/Types**: Output formats, data types, units
- **Content descriptors**: Topics, subjects, descriptions

**Quick litmus test:** "Would the user ever run this with a different [value]?"
- If YES → Make it an input
- If NO or user said "always" → Hardcode it

**Decision Process:**
```
Did user specify this value?
  → YES: Make it an INPUT (applies to all types above)

Did user say "always", "only", or "hardcode"?
  → YES: Safe to hardcode

Is it a system constraint (encoding, protocols)?
  → YES: Hardcode it

When unsure?
  → Make it an INPUT (safer for reusability)
```

**Dos and Don'ts**:
- **DO extract**: Actual values, paths, names, numbers, states
- **DON'T extract**: Action verbs, commands, prompts, instructions, platform/service names (github, slack, API)

### Authentication & Credentials

**Settings (`~/.pflow/settings.json`) are ONLY for authentication secrets.**

**✅ Settings belong:**
- API tokens: `replicate_api_token`, `github_token`, `openai_api_key`
- Service credentials used universally
- LLM API keys (can also use LLM library)

**❌ Settings don't belong:**
- Resource IDs: `sheet_id`, `channel`, `repo` (workflow-specific)
- Data parameters: `limit`, `input_file`, `threshold` (varies by use case)

**Manage**: Users use pflow settings set-env command (e.g., `pflow settings set-env GITHUB_TOKEN "ghp_..."`)
**Precedence**: Explicit parameters > ENV > settings > defaults

> Note: NEVER set secrets as parameter defaults. Always use inputs or better yet, settings.json (user adds them)

#### CRITICAL: How Workflows Access Credentials

**Settings values are NOT automatically available as templates!**

❌ **WRONG - Settings don't auto-populate:**
```json
{
  "type": "http",
  "params": {
    "headers": {"Authorization": "Bearer ${api_token}"}  // This won't work!
  }
}
```

✅ **CORRECT - Declare as workflow input:**
```json
{
  "inputs": {
    "api_token": {
      "type": "string",
      "required": true,
      "description": "API token for external service"
    }
  },
  "nodes": [{
    "type": "http",
    "params": {
      "headers": {"Authorization": "Bearer ${api_token}"}  // Now it works
    }
  }]
}
```

**The Complete Authentication Flow:**
1. **User sets secrets**: `pflow settings set-env SERVICE_TOKEN "secret123"`
2. **Agent declares as workflow input** (required field):
   ```json
   {
     "inputs": {
       "service_token": {
         "type": "string",
         "required": true,
         "description": "API token for external service"
       }
     }
   }
   ```
3. **Workflow automatically reads from env var** with matching name (SERVICE_TOKEN)
4. **Or pass explicitly**: `workflow_execute(workflow="...", parameters={"service_token": "$SERVICE_TOKEN"})`

**Key Point**: Settings store secrets securely, but workflows must explicitly declare them as inputs to use them.

#### Being Proactive with Authentication

**When you discover a workflow needs credentials, help the user set them up:**

**Identify requirements:**
- Determine what API keys, tokens, or credentials are needed
- Explain clearly how to obtain them (with specific links/steps)

**Guide setup:**
- Instruct users to set api keys using the pflow settings set-env command:
  ```bash
  pflow settings set-env SLACK_TOKEN "xoxb-your-token-here"
  pflow settings set-env GITHUB_TOKEN "ghp_your-token-here"
  ```
- Explain that the workflow will automatically read from `~/.pflow/settings.json` env variables if:
  1. The workflow declares them as inputs
  2. The environment variable name matches (case-sensitive or uppercased)

- Instruct users to use Simon Willison's llm tool to help them set the api keys for llm providers:
  ```bash
  llm keys set openai
  llm keys set anthropic
  ```

### Workflow Structure Essentials

#### Minimal Workflow Structure

```json
{
  "nodes": [
    {
      "id": "unique-id",
      "type": "node-type",
      "purpose": "Clear description of what this node does",
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
      "source": "${node_id.output_key}",
      "description": "What this output contains"
    }
  }
}
```

**Key rules**:
- Use `params` not `inputs` for node configuration
- ID must be unique within workflow
- Type must exist in registry
- Purpose field is optional but strongly recommended for clarity (Always include it)

#### Node Parameter Philosophy

**Default Rule: Use node defaults whenever possible. Only set parameters the user explicitly requests.**

**When to Set Parameters:**
- ✅ User explicitly requests specific values
- ✅ Required parameter (no default exists)
- ✅ Workflow logic requires non-default behavior

**When NOT to Set:**
- ❌ Parameter has a good default
- ❌ User didn't mention it
- ❌ You're guessing what might be better

#### Template Variable Syntax

**Templates (`${...}`) are how data flows through your workflow.**

##### Decision Tree: What Goes Where?

```
Is this value PROVIDED BY USER when running workflow?
├─ YES → Declare in "inputs" section
│        THEN reference as: ${input_name}
│
│        Example:
│        "inputs": {"repo": {...}}
│        "params": {"repository": "${repo}"}
│
└─ NO → Is this value GENERATED BY A NODE?
    ├─ YES → Reference as: ${node_id.output_key}
    │        CHECK first: pflow registry describe node-type
    │
    │        Example:
    │        "params": {"content": "${read.content}"}
    │
    └─ NO → It's a STATIC VALUE
            Use literal value (no template)

            Example:
            "params": {"encoding": "utf-8"}
```

##### Common Template Patterns

```json
{
  "params": {
    "file_path": "${input_file}",           // Workflow input
    "content": "${read.content}",           // Node output (simple)
    "nested": "${fetch.result.data}",       // Nested object access
    "array": "${items.result[0].name}",     // Array indexing
    "hardcoded": "utf-8"                    // Static value (no template)
  }
}
```

##### Common Mistakes & Fixes

❌ **WRONG - Template for hardcoded value:**
```json
"params": {"format": "${json}"}  // No 'json' input exists
```
✅ **CORRECT:**
```json
"params": {"format": "json"}  // Static value
```

❌ **WRONG - Missing template syntax:**
```json
"params": {"data": "analyze.response"}  // Missing ${}
```
✅ **CORRECT:**
```json
"params": {"data": "${analyze.response}"}
```

❌ **WRONG - User value not declared as input:**
```json
"params": {"limit": "${10}"}  // '10' is not an input
```
✅ **CORRECT:**
```json
"inputs": {"limit": {"type": "number", "default": 10, ...}},
"params": {"limit": "${limit}"}

#### Workflow Inputs

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

#### Workflow Outputs

**Each output MUST be an object with these REQUIRED fields:**

```json
"output_name": {
  "source": "${node_id.output_key}",              // REQUIRED: Template expression
  "description": "Clear explanation of this data"  // REQUIRED
}
```

**That's it. Only `source` and `description`. No other fields allowed.**

**When to skip outputs entirely**: Automation workflows (send/update/post) where success is visible through side effects.

---

## MCP Meta-Discovery (Do This First)

**Critical for understanding MCP tool capabilities.**

Before testing individual MCP tools, check if the server has helper tools:

```python
# Search for meta-tools
registry_search(pattern="servername")

# Look for meta-tools that help you understand capabilities:
# - Tools ending in: LIST, GET_SCHEMA, GET_DOCS, GET_EXAMPLES
# - Tools for exploration: SEARCH, QUERY, BROWSE, DESCRIBE
```

**Common helper tool patterns:**
- `LIST_SCHEMAS` - Shows available data structures
- `GET_DOCUMENTATION` - Returns detailed tool docs
- `LIST_EXAMPLES` - Provides usage examples
- `DESCRIBE_*` - Explains specific resources
- `GET_METADATA` - Returns server capabilities

**Example exploration flow:**
```python
# 1. Find potential helper tools
registry_search(pattern="datastore")

# Found: GET_SCHEMA, LIST_TABLES, CREATE_RECORD, QUERY_RECORDS

# 2. Use helper tools to understand before building
registry_run(node_type="mcp-datastore-LIST_TABLES", parameters={"database_name": "my_database"}, show_structure=True)
# → Now I understand what tables exist and their structure

# 3. Test unclear tools with realistic data
registry_run(node_type="mcp-datastore-CREATE_RECORD", parameters={"table": "users", "data": {"name": "test"}}, show_structure=True)
# → Reveals actual output structure and constraints
```

---

## Testing & Debugging

### Test Individual Nodes (When Needed)

**Test unknown nodes. Skip testing for known patterns.**

#### When to Test (Worth the Time)

✅ **Always test:**
- MCP nodes (deeply nested outputs)
- External APIs you haven't used
- Complex shell+jq extractions
- Anything returning `Any` type that you need to access

❌ **Skip testing for:**
- Simple shell commands (`curl`, `echo`, `mkdir`)
- Known patterns you've used before
- File operations (read/write)
- Standard HTTP calls with known responses

#### Smart Testing Workflow

**Step 1: Test with show_structure=True (ALWAYS)**
```python
# For MCP nodes - reveals nested structures
registry_run(
    node_type="mcp-service-TOOL_NAME",
    parameters={"param1": "value1"},
    show_structure=True
)

# For HTTP nodes - test actual endpoints
registry_run(
    node_type="http",
    parameters={
        "url": "https://api.example.com/endpoint",
        "method": "POST",
        "headers": {"Authorization": "Bearer test"}
    },
    show_structure=True
)
```

**Step 2: Document the actual structure**
```python
# What documentation says:
Output: result (Any) - Tool result

# What show_structure=True reveals:
result.data.response.items[0].content.url  # The actual path!
result.metadata.status
result.error_details.message
```

**Step 3: Update your templates accordingly**
```json
// ❌ WRONG - Based on documentation
"params": {"data": "${fetch.result}"}

// ✅ CORRECT - Based on testing
"params": {"data": "${fetch.result.data.response.items[0].content.url}"}
```

#### Critical Testing Patterns

**Pattern 1: MCP Tools Always Have Complex Outputs**
```python
# Test reveals:
result.data.tool_response.nested.deeply.actual_value

# Not just:
result  # This almost never works
```

**Pattern 2: External APIs Need Authentication Testing**
```python
# Test with real token to verify:
- Authentication header format
- Response structure
- Error messages
- Rate limits
```

**Pattern 3: Binary Data Needs Special Handling**
```python
# Test file downloads/uploads:
registry_run(node_type="http", parameters={"url": "image.jpg"}, show_structure=True)
# Check if response is string, base64, or URL
```

**Time Investment:**
- Testing: 30-60 minutes
- Debugging without testing: 2-4 hours
- Choice is clear: TEST FIRST

### Execute Workflow

```python
# Execute workflow from file
workflow_execute(
    workflow="~/.pflow/temp-workflows/workflow.json",
    parameters={
        "param1": "value",
        "param2": "value"
    }
)
```

**Note**: Traces are always saved to `~/.pflow/debug/`

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
   Traces are automatically saved to ~/.pflow/debug/
```

**2. Use the trace file for complete field list**:
```python
# Find the latest trace
ls -lt ~/.pflow/debug/workflow-trace-*.json | head -1

# View all available fields from the failed node
cat ~/.pflow/debug/workflow-trace-*.json | jq '.events[] | select(.node_id == "fetch") | .shared_after.fetch | keys'
```

### Common Validation Errors

| Error | Solution |
|-------|----------|
| "Unknown node type 'X'" | Call `registry_discover(query="task that needs X")` |
| "Template variable '${X}' not found" | Add `X` to inputs OR verify node output |
| "Node 'A' references 'B.output' but B hasn't executed yet" | Reorder edges |
| "Circular dependency detected" | Check edges for loops |
| "Missing required parameter 'Y' in node 'Z'" | Call `registry_describe(node_types=["Z"])` |

---

## Progressive Learning Path

Start simple, build complexity gradually.

### Level 1: Single Node (5 minutes)

**Goal**: Understand basic workflow structure

```json
{
  "inputs": {
    "question": {
      "type": "string",
      "required": true,
      "description": "Question to answer"
    }
  },
  "nodes": [
    {
      "id": "answer",
      "type": "llm",
      "params": {
        "prompt": "Answer concisely: ${question}"
      }
    }
  ],
  "outputs": {
    "response": {
      "source": "${answer.response}",
      "description": "AI response"
    }
  }
}
```

**Try it**:
```python
workflow_execute(
    workflow="~/.pflow/temp-workflows/level1.json",
    parameters={"question": "What is 2+2?"}
)
```

### Level 2: Chain Two Nodes (10 minutes)

**Goal**: Understand data flow between nodes

```json
{
  "inputs": {
    "file_path": {
      "type": "string",
      "required": true,
      "description": "File to summarize"
    }
  },
  "nodes": [
    {
      "id": "read",
      "type": "read-file",
      "params": {
        "file_path": "${file_path}"
      }
    },
    {
      "id": "summarize",
      "type": "llm",
      "params": {
        "prompt": "Summarize in 3 points:\n\n${read.content}"
      }
    }
  ],
  "edges": [
    {"from": "read", "to": "summarize"}
  ],
  "outputs": {
    "summary": {
      "source": "${summarize.response}",
      "description": "File summary"
    }
  }
}
```

**Try it**:
```python
workflow_execute(
    workflow="~/.pflow/temp-workflows/level2.json",
    parameters={"file_path": "README.md"}
)
```

### Level 3: Multi-Step Pipeline (20 minutes)

**Goal**: Coordinate multiple operations

```json
{
  "inputs": {
    "api_url": {
      "type": "string",
      "required": true,
      "description": "API endpoint"
    },
    "output_file": {
      "type": "string",
      "required": false,
      "default": "analysis.md",
      "description": "Output file path"
    }
  },
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
        "prompt": "Extract key insights from:\n\n${fetch.response}"
      }
    },
    {
      "id": "save",
      "type": "write-file",
      "params": {
        "file_path": "${output_file}",
        "content": "# API Analysis\n\n${analyze.response}\n\nSource: ${api_url}"
      }
    }
  ],
  "edges": [
    {"from": "fetch", "to": "analyze"},
    {"from": "analyze", "to": "save"}
  ],
  "outputs": {
    "file": {
      "source": "${save.file_path}",
      "description": "Analysis file location"
    }
  }
}
```

**What you learn**: Templates, optional inputs, multi-step flows

### Level 4: Production Workflow (30 minutes)

See [Complete Example](#complete-example-slack-qa-bot) for a full production workflow.

### Level 5: Real-World Complexity (Reality Check)

**Most real workflows have 15-30 nodes. This is NORMAL.**

#### Example: Multi-Service Integration Workflow

```json
{
  "nodes": [
    {"id": "fetch-data", "type": "..."},        // Node 1
    {"id": "validate", "type": "..."},          // Node 2
    {"id": "transform", "type": "..."},         // Node 3
    {"id": "call-api-1", "type": "..."},        // Node 4
    {"id": "wait-for-api-1", "type": "..."},    // Node 5
    {"id": "call-api-2", "type": "..."},        // Node 6
    {"id": "process-response", "type": "..."},  // Node 7
    {"id": "generate-file-1", "type": "..."},   // Node 8
    {"id": "generate-file-2", "type": "..."},   // Node 9
    {"id": "generate-file-3", "type": "..."},   // Node 10
    {"id": "save-file-1", "type": "..."},       // Node 11
    {"id": "save-file-2", "type": "..."},       // Node 12
    {"id": "save-file-3", "type": "..."},       // Node 13
    {"id": "upload-results", "type": "..."},    // Node 14
    {"id": "notify-completion", "type": "..."}  // Node 15+
    // ... potentially more nodes
  ],
  "edges": [
    // Sequential chain - everything must execute in order
    {"from": "fetch-data", "to": "validate"},
    {"from": "validate", "to": "transform"},
    // ... all connections
  ]
}
```

#### Complexity Reality Checks

**What Makes Workflows Complex:**
- Each external API call needs 2-3 nodes (call, poll, process)
- Each file operation needs its own node
- Data transformations each need nodes
- NO parallel execution - everything sequential

**Time Expectations:**
- Simple workflow (3-5 nodes): 10-30 seconds
- Medium workflow (10-15 nodes): 1-2 minutes
- Complex workflow (20+ nodes): 3-5 minutes
- With external APIs: Add 30-60 seconds per API

**This is NOT a bug or poor design:**
- Sequential execution ensures predictability
- Each node has single responsibility
- Easier to debug when things fail
- Trade-off: simplicity over speed

---

## Common Workflow Patterns

### Pattern 0: Extract from Structured Data (CRITICAL PATTERN)

**❌ WRONG - Using LLM for extraction:**
```json
{
  "id": "extract-data",
  "type": "llm",
  "params": {
    "prompt": "Extract the value from the data: ${source.result}"
  }
}
```

**✅ CORRECT - Using shell+jq:**
```json
{
  "id": "extract-value",
  "type": "shell",
  "params": {
    "stdin": "${source.result}",
    "command": "jq -r '.data[] | select(.field != null) | .desired_field'"  # Adapt to your data structure
  }
}
```

**Why shell+jq is superior:**
- Deterministic (same input = same output)
- Free (no LLM tokens)
- Instant (no API latency)
- Precise (no hallucination)
- Can handle complex logic (select, filter, map)

### Pattern 1: Fetch → Transform → Store

```
[Data Source] → [LLM/Processing] → [Data Sink]
```

**Example**: Read file → Analyze → Write summary

```json
{
  "inputs": {
    "input_file": {
      "type": "string",
      "required": true,
      "description": "File to analyze"
    }
  },
  "nodes": [
    {
      "id": "read",
      "type": "read-file",
      "params": {
        "file_path": "${input_file}"
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "params": {
        "prompt": "Summarize this content in 3 bullet points:\n\n${read.content}"
      }
    },
    {
      "id": "save",
      "type": "write-file",
      "params": {
        "file_path": "summary.md",
        "content": "# Summary\n\n${analyze.response}"
      }
    }
  ],
  "edges": [
    {"from": "read", "to": "analyze"},
    {"from": "analyze", "to": "save"}
  ],
  "outputs": {
    "summary_path": {
      "source": "${save.file_path}",
      "description": "Path to saved summary"
    }
  }
}
```

### Pattern 2: Multi-Source → Combine → Process

```
[Source A] ──┐
             ├─→ [LLM Combines] → [Process]
[Source B] ──┘
```

**Example**: Fetch GitHub PR + issues → Analyze together → Generate report

```json
{
  "inputs": {
    "repo": {
      "type": "string",
      "required": true,
      "description": "Repository (owner/name)"
    },
    "pr_number": {
      "type": "number",
      "required": true,
      "description": "PR number to analyze"
    }
  },
  "nodes": [
    {
      "id": "get-pr",
      "type": "mcp-github-get-pr",
      "params": {
        "repo": "${repo}",
        "number": "${pr_number}"
      }
    },
    {
      "id": "get-issues",
      "type": "mcp-github-list-issues",
      "params": {
        "repo": "${repo}",
        "state": "open"
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "params": {
        "prompt": "PR:\n${get-pr.result}\n\nOpen Issues:\n${get-issues.result}\n\nIdentify which issues this PR might resolve."
      }
    }
  ],
  "edges": [
    {"from": "get-pr", "to": "get-issues"},
    {"from": "get-issues", "to": "analyze"}
  ],
  "outputs": {
    "analysis": {
      "source": "${analyze.response}",
      "description": "PR impact analysis"
    }
  }
}
```

### Pattern 3: Enrich → Process → Store

```
[Base Data] → [Enrich with Context] → [Process] → [Store]
```

**Example**: Get issue → Fetch related PRs → Analyze → Update issue

```json
{
  "inputs": {
    "repo": {
      "type": "string",
      "required": true,
      "description": "Repository (owner/name)"
    },
    "issue_number": {
      "type": "number",
      "required": true,
      "description": "Issue to analyze"
    }
  },
  "nodes": [
    {
      "id": "get-issue",
      "type": "mcp-github-get-issue",
      "params": {
        "repo": "${repo}",
        "number": "${issue_number}"
      }
    },
    {
      "id": "get-prs",
      "type": "mcp-github-list-prs",
      "params": {
        "repo": "${repo}",
        "state": "open"
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "params": {
        "prompt": "Issue:\n${get-issue.result}\n\nOpen PRs:\n${get-prs.result}\n\nWhich PRs might fix this issue?"
      }
    },
    {
      "id": "update",
      "type": "mcp-github-comment-issue",
      "params": {
        "repo": "${repo}",
        "number": "${issue_number}",
        "body": "Analysis:\n${analyze.response}"
      }
    }
  ],
  "edges": [
    {"from": "get-issue", "to": "get-prs"},
    {"from": "get-prs", "to": "analyze"},
    {"from": "analyze", "to": "update"}
  ]
}

---

## Workflow Naming Conventions

**Format**: verb-noun-target
- Examples: `analyze-github-prs`, `slack-qa-bot`, `process-invoices`
- Max 30 characters, lowercase, hyphens only
- Be specific: `slack-qa-bot` > `message-processor`

---

## Common Mistakes

### ❌ Mistake 1: Skipping Workflow Discovery
**Fix**: ALWAYS call `workflow_discover(query="...")` first (Step 2)

### ❌ Mistake 2: Not Checking Node Output Structure
**Fix**: Call `registry_describe(node_types=["node-type"])` BEFORE writing templates

### ❌ Mistake 3: Building Everything at Once
**Fix**: Build 2 nodes → validate → add 1 more → validate → repeat

### ❌ Mistake 4: Using `inputs` Instead of `params`
**Fix**: Node configuration uses `params`, not `inputs`!

### ❌ Mistake 5: Over-Specifying Node Parameters
**Fix**: Only set parameters user explicitly requests or workflow logic requires

### ❌ Mistake 6: Too Many Nodes
**Fix**: LLM nodes can consolidate multiple operations. Each node adds overhead.

### ❌ Mistake 7: Investigating Every `result: Any`
**Fix**: Only investigate when templates need nested paths!

---

## When NOT to Build a Workflow

**🛑 Recognize when pflow is the wrong tool:**

### Requires Conditional Logic
**User wants**: "If PR is approved, merge it, otherwise request review"
**Problem**: No branching in pflow
**Alternative**: Build two workflows or use external automation

### Needs Loops or Iteration
**User wants**: "Process each file in directory differently"
**Problem**: No loops in pflow
**Alternative**: Use shell script or batch processing

### Requires State Persistence
**User wants**: "Track progress and resume if interrupted"
**Problem**: Workflows are stateless
**Alternative**: Use database or file-based state tracking

### Needs User Interaction
**User wants**: "Ask user for confirmation before proceeding"
**Problem**: No interactive prompts
**Alternative**: Split into multiple workflows

### Real-Time Requirements
**User wants**: "Respond within 100ms"
**Problem**: LLM nodes add latency
**Alternative**: Use direct API calls without LLM

**Response Template**:
"This requires [feature] which pflow doesn't support. I can either:
1. Build a simplified version that [workaround]
2. Suggest an alternative approach using [tool]
Which would you prefer?"

---

## Debugging Playbook

**When validation passes but execution fails:**

### Step 1: Check the Error Type

```python
# Run workflow to capture error context
workflow_execute(workflow="~/.pflow/temp-workflows/workflow.json", parameters={})
```

| Error Pattern | Likely Cause | Fix |
|--------------|-------------|-----|
| `KeyError: 'result'` | Node output structure different than expected | Check trace file for actual structure |
| `401 Unauthorized` | Missing/invalid credentials | Check settings.json or environment variables |
| `TypeError: expected string` | Wrong data type in template | Verify node output types with registry describe |
| `Connection refused` | Service not running | Start required MCP servers |
| `Rate limit exceeded` | Too many API calls | Add delays or reduce batch size |

### Step 2: Isolate the Failing Node

```python
# Test just the failing node
registry_run(node_type="<node-type>", parameters={"param1": "value"}, show_structure=True)

# If it works alone, check data flow
cat ~/.pflow/debug/workflow-trace-*.json | jq '.nodes[] | select(.id=="failing-node")'
```

---

## Real Request Parsing

**How to handle ambiguous user requests:**

### Ambiguous Quantities
**User says**: "Get recent messages from Slack"
```
❌ DON'T: Guess that "recent" means 10
✅ DO: Make it an input with sensible default
"limit": {"default": 10, "description": "Number of recent messages"}
```

### Unclear Targets
**User says**: "Send the report"
```
❌ DON'T: Hardcode a destination
✅ DO: Ask for clarification
"Where should I send the report? (email, Slack, file, etc.)"
```

### Missing Context
**User says**: "Analyze the data"
```
❌ DON'T: Assume what data
✅ DO: Identify what's missing
"What data should I analyze? Please specify the source."
```

### Conflicting Requirements
**User says**: "Make it fast but check everything thoroughly"
```
✅ DO: Explain the tradeoff
"I can optimize for speed OR thoroughness. Which is more important?"
```

### Implicit Expectations
**User says**: "Process our customer data" (implies security)
```
✅ DO: Surface hidden requirements
"This involves customer data. Should I include any special security measures?"
```

**The Clarification Template**:
```
I need to clarify a few things:
1. When you say [ambiguous term], do you mean [option A] or [option B]?
2. For [missing piece], what should I use?
3. Should I [implicit requirement]?
```

---

## MCP and HTTP Tool Reality Check

**Tools often don't work as documented. Here's how to handle it:**

### Before Building: Test Everything
```python
# 1. Warn users before making tool calls that might be destructive or make dangerous side effects.
# 2. Always test with actual data first if not a very simple tool.
registry_run(node_type="mcp-tool", parameters={"param": "value"}, show_structure=True)

# 3. Verify that the tool works with the current inputs
# Debugging each tool call individually reduces complexity and the time to find the issue.
```

### Common MCP Quirks & Workarounds

| Tool Says | Reality | Workaround |
|-----------|---------|------------|
| "Returns array" | Returns object with array inside | Use `${result.items}` not `${result}` |
| "Optional parameter" | Actually required | Always provide it |
| "Accepts string" | Needs specific format | Test formats, document what works |
| "Any type" | Has hidden structure | Use `show_structure=True` to discover |
| "Returns result" | Returns nested response.data.result | Trace actual path |

### When Documentation is Wrong

Document what ACTUALLY works in `~/.pflow/temp-workflows/docs/<workflow-name>.md`

---

## When Stuck (Decision Tree)

```
Template error?
├─ Yes → Check trace file (Understanding Template Errors)
└─ No → Validation error?
    ├─ Yes → See Common Validation Errors
    └─ No → Execution error?
        ├─ Yes → Use Debugging Playbook
        └─ No → Discovery failed?
            ├─ Yes → Try manual discovery tools
            └─ No → Ask user for clarification
```

---

## Quick Reference

### Decision Table: What Becomes an Input?

| User Says | You Create | Why |
|-----------|------------|-----|
| "file.txt" | `input: file_path` | They'll use different files |
| "channel ABC123" | `input: channel` | Different channels later |
| "last 10 items" | `input: limit` (default: 10) | Might want 20 tomorrow |
| "song about cats" | `input: subject` (default: "cats") | Could be dogs, space, friendship, etc. |
| "always use prod" | Hardcode: "prod" | Explicitly said "always" |

### Tools Cheat Sheet

```python
# Discovery - ALWAYS use AI-powered discovery first
workflow_discover(query="user's request")                # Find existing workflows
registry_discover(query="what you need to build")        # Find nodes for building
workflow_list(filter="[filter]")

# Development
workflow_validate(workflow="~/.pflow/temp-workflows/workflow.json")    # Validate structure

# Saving
workflow_save(workflow="~/.pflow/temp-workflows/workflow.json", name="name", description="desc")  # Save to library

# Execution
workflow_execute(workflow="~/.pflow/temp-workflows/workflow.json", parameters={"param": "value"})  # Run from file
workflow_execute(workflow="saved-workflow", parameters={"param": "value"})                   # Run from library
```

### Template Syntax

- `${input_name}` - Workflow input
- `${node.output}` - Node output
- `${node.data.field}` - Nested field
- `${items[0].name}` - Array access

---

## Complete Example: Slack Q&A Bot

Let's build a complete workflow from user request to saved, reusable tool.

### User Request
"I need to fetch the last 15 messages from Slack channel C09C16NAU5B, extract Q&A pairs, and log them to Google Sheets ID abc123xyz"

### Step 1: UNDERSTAND
```
Inputs needed:
- channel: C09C16NAU5B → Make it an input
- limit: 15 → Make it an input with default
- sheet_id: abc123xyz → Make it an input

Pattern: Multi-Service Coordination
```

### Step 2: DISCOVER WORKFLOWS
```python
workflow_discover(query="fetch slack messages extract Q&A log to sheets")
# Result: No 80%+ matches, building new
```

### Step 3: DISCOVER NODES
```python
registry_discover(query="fetch Slack messages, extract Q&A with AI, append to Google Sheets")
# Found: mcp-slack-fetch, llm, mcp-sheets-append
```

### Step 4: DESIGN
```
fetch-messages (mcp-slack-fetch) → channel, limit
     ↓
extract-qa (llm) → prompt with messages
     ↓
log-to-sheets (mcp-sheets-append) → sheet_id, values
```

### Step 5: PLAN & CONFIRM
"I'll create a workflow that:
1. Fetches messages from Slack channel
2. Extracts Q&A pairs using AI
3. Logs results to Google Sheets

Inputs: channel, limit, sheet_id
Pattern: Multi-Service Coordination

Confirm?"

### Step 6: BUILD

```json
{
  "inputs": {
    "channel": {
      "type": "string",
      "required": true,
      "description": "Slack channel ID to fetch messages from"
    },
    "limit": {
      "type": "number",
      "required": false,
      "default": 15,
      "description": "Number of messages to fetch"
    },
    "sheet_id": {
      "type": "string",
      "required": true,
      "description": "Google Sheets ID for logging"
    }
  },
  "nodes": [
    {
      "id": "fetch-messages",
      "type": "mcp-slack-fetch",
      "purpose": "Fetch recent messages from the specified Slack channel",
      "params": {
        "channel": "${channel}",
        "limit": "${limit}"
      }
    },
    {
      "id": "extract-qa",
      "type": "llm",
      "purpose": "Extract Q&A pairs from the messages using AI",
      "params": {
        "prompt": "Extract Q&A pairs from these Slack messages. Format as:\nQ: [question]\nA: [answer]\n\nMessages:\n${fetch-messages.result}"
      }
    },
    {
      "id": "log-to-sheets",
      "type": "mcp-sheets-append",
      "purpose": "Log the extracted Q&A pairs to Google Sheets",
      "params": {
        "sheet_id": "${sheet_id}",
        "values": [
          ["${extract-qa.response}"]
        ]
      }
    }
  ],
  "edges": [
    {"from": "fetch-messages", "to": "extract-qa"},
    {"from": "extract-qa", "to": "log-to-sheets"}
  ],
  "outputs": {
    "qa_pairs": {
      "source": "${extract-qa.response}",
      "description": "Extracted Q&A pairs"
    },
    "sheet_update": {
      "source": "${log-to-sheets.result}",
      "description": "Sheets update confirmation"
    }
  }
}
```

### Step 7: VALIDATE
```python
workflow_validate(workflow="~/.pflow/temp-workflows/slack-qa.json")
# ✓ All validations passed!
```

### Step 8: TEST
```python
workflow_execute(
    workflow="~/.pflow/temp-workflows/slack-qa.json",
    parameters={
        "channel": "C09C16NAU5B",
        "limit": 15,
        "sheet_id": "abc123xyz"
    }
)
# ✓ Workflow executed successfully!
```

### Step 9: REFINE
- Improved prompt for better Q&A extraction
- Added timestamp to sheet logging
- Enhanced descriptions

### Step 10: SAVE
```python
workflow_save(workflow="~/.pflow/temp-workflows/slack-qa.json", name="slack-qa-bot", description="Extracts Q&A pairs from Slack and logs to Google Sheets")
```

### Final: User can now run
```python
# With their original values:
workflow_execute(
    workflow="slack-qa-bot",
    parameters={
        "channel": "C09C16NAU5B",
        "limit": 15,
        "sheet_id": "abc123xyz"
    }
)

# Or with different values:
workflow_execute(
    workflow="slack-qa-bot",
    parameters={
        "channel": "D456DEF",
        "limit": 50,
        "sheet_id": "xyz789"
    }
)
```

---

## Workflow Smells

**🚩 Red flags that indicate poor workflow design:**

### No Inputs Section
```json
// ❌ BAD - Not reusable
{"nodes": [...], "edges": [...]}
```
**Fix**: Extract all user values as inputs

### Hardcoded Values
```json
// ❌ BAD - Only works for one channel
"params": {"channel": "C09C16NAU5B"}
```
**Fix**: Make it an input: `"channel": "${channel}"`

### Over-Specific Input Names
```json
// ❌ BAD - Too specific
"inputs": {"slack_channel_C123": {...}}
```
**Fix**: Generic name: `"channel": {...}`

### Too Many Required Inputs
```json
// ❌ BAD - Everything required
"required": true, "required": true, "required": true
```
**Fix**: Add sensible defaults where possible

### Exposing Raw MCP Results
```json
// ❌ BAD - Too verbose
"outputs": {"data": {"source": "${fetch.result}"}}
```
**Fix**: Extract specific fields users need

---

## Input Extraction Examples

**Learn to extract inputs from user requests:**

### Example 1: File Operations
**User says**: "Convert data.csv to JSON format"
```json
"inputs": {
  "input_file": {
    "type": "string",
    "required": true,
    "description": "CSV file to convert"
  },
  "output_format": {
    "type": "string",
    "required": false,
    "default": "json",
    "description": "Output format"
  }
}
```
**Why**: Tomorrow they'll convert "report.csv" or want XML

### Example 2: API Monitoring
**User says**: "Alert when response time exceeds 500ms for api.example.com"
```json
"inputs": {
  "api_url": {
    "type": "string",
    "required": true,
    "description": "API endpoint to monitor"
  },
  "threshold_ms": {
    "type": "number",
    "required": false,
    "default": 500,
    "description": "Response time threshold in milliseconds"
  }
}
```
**Why**: Different APIs, different thresholds

### Example 3: Data Processing
**User says**: "Process last 30 GitHub issues with priority labels"
```json
"inputs": {
  "repo": {
    "type": "string",
    "required": true,
    "description": "Repository (owner/name format)"
  },
  "issue_count": {
    "type": "number",
    "required": false,
    "default": 30,
    "description": "Number of issues to process"
  },
  "labels": {
    "type": "string",
    "required": false,
    "default": "priority",
    "description": "Label filter"
  }
}
```
**Why**: Reusable for any repo, count, or label

---

## Reality vs Documentation Quick Reference

**What the docs suggest vs what actually happens:**

| Documentation Says | Reality | Action Required |
|-------------------|---------|-----------------|
| "Test nodes" (helpful) | Test unknown nodes only | Skip testing known patterns |
| `${result}` | `${result.data.nested.deeply.field}` | Test MCP nodes |
| 3-5 nodes typical | 15-30 nodes typical | Build in phases, test each phase |
| Use LLM for extraction | Shell+jq ALWAYS better | `jq -r '.data.field'` # Adapt to structure |
| Async needs polling | `Prefer: wait` eliminates polling | Add header, wait up to 60s |
| MCP for file operations | Shell+curl simpler | `curl -L -o file.jpg "$url"` |
| Download then use | Direct URLs work | `https://storage.service.com/file/${id}` |
| Settings auto-available | Must declare as inputs | Add `api_token` to inputs |
| "Any" type outputs | Complex nested structures | Test if you need nested access |
| HTTP node for uploads | Shell+curl more reliable | `curl -X POST --data-binary` |
| Build entire workflow | Phase it for 15+ nodes | Core → APIs → Processing → Storage |
| Linear execution (mentioned) | EVERYTHING sequential | No parallelization, ever |
| Quick execution | 3-5 minutes for complex | Set realistic expectations |

---

## Key Takeaways

1. **Choose simplest tool first** - Shell+jq > LLM, curl > MCP, Prefer:wait > polling
2. **Shell+jq for ALL structured data** - Never use LLM for extraction
3. **Prefer: wait eliminates polling** - One header saves 2-3 nodes
4. **Build complex workflows in phases** - Core → APIs → Processing → Storage
5. **Test only unknown patterns** - Skip testing curl, echo, known APIs
6. **Direct URLs save nodes** - Use when services provide direct file access
7. **Settings ≠ Auto-available** - Declare credentials as workflow inputs
8. **20+ nodes is NORMAL** - But build in phases to debug easily
9. **Users show ONE example** - You build the GENERAL tool

---

**You're now ready to build reusable workflows with pflow!** 🚀