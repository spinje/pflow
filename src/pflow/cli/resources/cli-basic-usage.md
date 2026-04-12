# pflow - Basic Usage Guide for AI Agents

> **Purpose**: Quick reference for AI agents to understand pflow basics and when to request comprehensive instructions.

## 🛑 MANDATORY First Step - Always Check for Existing Workflows

If the user is asking you to build a new workflow or wants you to do a complex task involving external tools, you MUST run the following command first:

**Before doing ANYTHING else, you MUST run:**

```bash
pflow find "user's exact request here"
```

**Why this is non-negotiable:**
- Building a workflow takes 5-30 minutes
- Using an existing workflow takes 5 seconds
- Users have likely solved similar problems before

**Decision Tree after running the above command:**
- **≥90% match** → Use it immediately with `pflow workflow-name`
- **70-90% match** → Ask user if they want to use, modify, or build new
- **50-70% match** → Suggest modifying the existing workflow
- **<50% match** → See "No Match" rules below

> Always make sure to make it clear what the differences are between the existing workflow and the user's request if there are any (<94% matches).

### No Match (<70%): Execute Directly vs Create Workflow

- **1-2 nodes needed** (e.g., fetch + save) → Ask user: "Execute directly (via `registry run`) or create reusable workflow?"
- **3+ nodes needed** → Create workflow (don't ask, just proceed with `pflow guide`)

## Essential Commands

### Workflow Discovery Commands (Use These First!)

```bash
# Find existing workflows if the request is complex
pflow find "what I want to do"

# List all saved workflows with a filter keyword if the user is asking for a specific workflow.
pflow list "<filter-keywords>" # Example: `pflow list "github pr"`
```

### Execute workflow by name

```bash
# Run a saved workflow
pflow workflow-name param1=value1 param2=value2

# Example output (stderr):
workflow-name was executed
  get-data... ✓ 1.0s
  save-data... ✓ 1.0s
✓ Workflow completed in 2.0s
💰 Cost: $0.0001 # LLM cost is shown only when > 0

Workflow output: # stderr header (not every workflow declares an output)

# Example output (stdout):
Data saved successfully # The declared workflow output goes here — this is what agents should capture

# If workflow was executed successfully, your work is done. Present the information to the user in a VERY CONCISE format. Don't overdo it with to detailed information like individual node execution times.
```
> **Important**: You should never run the workflow again if successful, this information is *more than enough* to present to the user and running it more than once can be disruptive. Do NOT attempt to gather more information about the workflow execution by using --verbose or --debug flags or anything else.

### Iterating on Workflow Files

Re-runs are automatically cached — unchanged nodes return instantly:

```bash
# Second run: unchanged nodes show [cached], instant
pflow ./workflow.pflow.md param1=value1

# Re-run just one node (upstream from cache, downstream skipped)
pflow ./workflow.pflow.md --only node-name

# Test with different input (cache miss for affected nodes only)
pflow ./workflow.pflow.md --only node-name param1=different

# Force fresh execution (bypass cache)
pflow ./workflow.pflow.md --no-cache

# Inspect a node in detail (resolved command, stderr, timing)
pflow ./workflow.pflow.md --only node-name --report

# See the workflow graph (saves Mermaid flowchart to file)
pflow visualize ./workflow.pflow.md -o graph.md
```

### Instructions for building workflows

```bash
# Read all 3 parts IN FULL before building workflows (do not truncate or skip any part):
pflow guide --part 1
pflow guide --part 2
pflow guide --part 3
```

**ONLY read these instructions when:**
- Building your first workflow
- User has approved the creation of a new workflow
- You are sure no existing workflow matches the user's request
- Running into errors when running a workflow
- You need to modify an existing workflow to fit the user's request

## Node Commands (run nodes individually as tools)

Use these commands to find available nodes if the user explicitly asks for a specific capability involving external tools. Like "<do something> using <external-tool-name>".
The difference between a workflow and a node is that a workflow is a collection of nodes that are executed in a specific order, while a node is a single operation that can be executed independently.

```bash
# Find available nodes if you need to search for a specific capability and you are not sure about what filter-keywords to use to find the node using the list command.
pflow mcp find "what capability I need"

# List all available nodes filtered by keywords. This is faster than the registry discover command but less flexible.
pflow mcp list <filter-keywords> # Example: `pflow mcp list slack` or `pflow mcp list "slack send message"`

# Get node details
pflow mcp describe <node-name>

# Run a node (returns metadata, not actual data)
pflow probe <node-name> param1=value1 param2=value2

# Example:
pflow probe mcp-slack-send-message channel="#general" text="Hello"

# Example output:
# ✓ Node executed successfully
# Execution ID: exec-1234567890-abcdef
# Available template paths (from actual output):
#   ✓ ${result} (str)
# Execution time: 2000ms
```

> **Note**: `registry run` shows execution metadata and template paths (for use in workflows), **not the actual data**. This is intentional - see below if you need actual values.

### Inspecting Actual Data (Only When Needed)

```bash
# Use the execution ID from registry run output
pflow read-fields exec-1234567890-abcdef result

# Access nested fields (path matches template paths shown by registry run)
pflow read-fields exec-1234567890-abcdef result.data.items
```

**Only use when:** user explicitly asks to see output data, or debugging requires it. Do NOT read fields by default.

## Quick Decision Tree

```
User Request Received
    ↓
Is it a complex task or workflow request?
    ↓
    ├─ YES: Complex task/workflow
    │   ↓
    │   Run: pflow find "user's request"
    │   ↓
    │   ├─ Match ≥90% → Run: pflow workflow-name params → DONE ✓
    │   │
    │   ├─ Match 50-90% → Show differences → Ask user:
    │   │                  "Use existing, modify, or build new?"
    │   │                  ↓
    │   │                  User decides → Execute or build
    │   │
    │   ├─ Match 50-70% → Suggest: "Can modify existing workflow-name"
    │   │                  ↓
    │   │                  User approves? → Proceed to build/modify
    │   │
    │   └─ Match <50% → No good match found
    │       ↓
    │       How many nodes needed?
    │       ├─ 1-2 nodes → Ask: "Execute directly or create workflow?"
    │       └─ 3+ nodes → Create workflow (pflow guide)
    │
    └─ NO: Simple request (specific node/tool)
        ↓
        Does user mention specific tool/capability?
        ↓
        ├─ YES → pflow mcp find "capability"
        │        or pflow mcp list <keywords>
        │        ↓
        │        Found node? → pflow probe <node-name> params
        │        ↓
        │        User needs actual data? → pflow read-fields exec-id result
        │        ↓
        │        DONE ✓
        │
        └─ NO → Ask for clarification or use workflow discovery
```
