The Ideal Agent Workflow (Mental Model)

  An agent building workflows should follow this iterative feedback loop:

  UNDERSTAND → PLAN → BUILD → VERIFY → ITERATE
       ↓         ↓       ↓        ↓         ↓
    Context   Design  Create  Validate   Refine

  What's Currently Missing: The "UNDERSTAND" Phase

  The document jumps straight to discovery commands but doesn't help the agent understand the
  task first. Here's what I actually did (and struggled with):

  The Real Agent Workflow (What I Experienced)

  Phase 0: UNDERSTAND THE TASK (Currently Undocumented!)

  What I needed to do (but wasn't guided on):

  1. Parse the user's request into structured requirements:
  User: "get slack messages, answer with AI, send back, log to sheets with timestamps"

  Agent mental model:
  - Input: Slack channel ID
  - Actions: fetch → analyze → respond → log
  - Data flow: messages → questions/answers → responses → sheet rows
  - External services: Slack (read+write), Sheets (write), Shell (date/time)
  2. Identify the capability gaps:
    - Do I need to parse complex data structures?
    - Do I need to iterate over collections?
    - Do I need conditional logic?
    - Do I need to transform data formats?
  3. Map capabilities to node types:
    - Slack operations → MCP tools
    - Text processing → LLM
    - Data transformation → LLM with structured prompts
    - System commands → shell

  This entire phase is currently in the agent's head with no guidance!

  ---
  Perfect Document Structure (Proposed)

  1. Start with "How to Think About Workflows"

  ## How to Think About Workflows

  A workflow is a **data transformation pipeline**. Before building anything, map your task:

  ### Step 1: Identify Inputs and Outputs
  - **Input**: What data do you start with? (params, files, API data)
  - **Output**: What data do you need to produce? (files, messages, logs)

  ### Step 2: Break Down the Transformation
  - What steps transform input → output?
  - What external services are involved?
  - What data needs to persist between steps?

  ### Step 3: Identify Node Categories Needed
  - **Data retrieval**: read-file, http, mcp-slack-fetch, mcp-github-get
  - **Data transformation**: llm (for text), shell (for structured data)
  - **Data storage**: write-file, mcp-sheets-update, mcp-slack-send
  - **Control flow**: llm (for decisions), shell (for conditionals)

  **Example**:
  User request: "Analyze Slack messages and log Q&A to Sheets"

  Decomposition:
  1. Input: Slack channel ID → Fetch messages (mcp-slack)
  2. Transform: Messages → Q&A pairs (llm)
  3. Output: Send to Slack (mcp-slack) + Log to Sheets (mcp-sheets)
  4. Additional: Need timestamps → Shell commands

  Now you're ready to discover specific nodes!

  2. Add "Workflow Design Patterns" Section

  ## Common Workflow Patterns

  Learn to recognize these patterns in user requests:

  ### Pattern 1: Fetch → Transform → Store
  [Data Source] → [LLM/Processing] → [Data Sink]

  Example: Read file → Analyze → Write summary
  Nodes: read-file → llm → write-file

  ### Pattern 2: Fetch → Decide → Branch
  [Data Source] → [LLM Decision] → [Conditional Action]

  Example: Get PR → Check if approved → Merge or comment
  Nodes: github-get-pr → llm → (github-merge OR github-comment)
  Note: Currently requires LLM to output structured command

  ### Pattern 3: Iterate → Collect → Aggregate
  [Fetch Multiple] → [Process Each] → [Combine Results]

  Example: Get all issues → Analyze each → Generate report
  Challenge: pflow doesn't support loops yet - use LLM to batch process

  ### Pattern 4: Multi-Service Coordination
  [Service A] → [Transform] → [Service B] → [Service C]

  Example: Slack → AI analysis → Slack response → Sheets logging
  Nodes: mcp-slack-fetch → llm → mcp-slack-send → mcp-sheets-update

  **Match your task to a pattern, then build!**

  3. Add "Progressive Complexity" Learning Path

  ## Learning Path: Start Simple, Build Complex

  ### Level 1: Single Transform (5 minutes)
  **Goal**: Understand basic structure
  ```json
  {
    "nodes": [
      {"id": "process", "type": "llm", "params": {"prompt": "${input}"}}
    ],
    "inputs": {"input": {"type": "string", "required": true}}
  }
  Try: pflow workflow.json input="Hello"

  Level 2: Chain Two Nodes (10 minutes)

  Goal: Understand data flow with templates
  {
    "nodes": [
      {"id": "read", "type": "read-file", "params": {"file_path": "${file}"}},
      {"id": "analyze", "type": "llm", "params": {"prompt": "Summarize: ${read.content}"}}
    ],
    "edges": [{"from": "read", "to": "analyze"}],
    "inputs": {"file": {"type": "string", "required": true}}
  }
  Try: pflow workflow.json file="README.md"

  Level 3: Multi-Step Pipeline (20 minutes)

  Goal: Coordinate multiple services
  {
    "nodes": [
      {"id": "fetch", "type": "http", "params": {"url": "${api_url}"}},
      {"id": "analyze", "type": "llm", "params": {"prompt": "Extract key points:
  ${fetch.response}"}},
      {"id": "save", "type": "write-file", "params": {"file_path": "summary.md", "content":
  "${analyze.response}"}}
    ],
    "edges": [
      {"from": "fetch", "to": "analyze"},
      {"from": "analyze", "to": "save"}
    ]
  }

  Level 4: Real-World Integration (30+ minutes)

  Goal: Use MCP tools, handle complex data
  See "Complete Example" section for Slack+Sheets workflow

  ### 4. **Add "Decision Tree for Node Selection"**

  ```markdown
  ## Choosing the Right Nodes

  Use this decision tree when selecting nodes:

  ### Need to Get Data?
  - **From file system?** → `read-file`
  - **From web API?** → `http` (generic) OR `mcp-{service}` (if available)
  - **From external service?** → Check `pflow registry list` for MCP tools
  - **From shell command output?** → `shell`

  ### Need to Transform Data?
  - **Natural language processing?** → `llm`
  - **Structured data transformation?** → `llm` (with JSON prompts) OR `shell` (jq, sed)
  - **Data validation/filtering?** → `llm` OR `shell`

  ### Need to Store Data?
  - **To file system?** → `write-file`
  - **To external service?** → `mcp-{service}-{action}`
  - **To web API?** → `http` (POST/PUT)

  ### Need to Make Decisions?
  - **Based on content?** → `llm` (ask it to output structured choice)
  - **Based on system state?** → `shell` (if statements)

  **Pro tip**: When in doubt, `llm` can handle most text-based tasks!

  5. Add "The Agent Development Loop"

  This is the MOST CRITICAL missing piece:

  ## The Development Loop (Your Workflow)

  Follow this cycle for every workflow you build:

  ### 1. UNDERSTAND (5 min)
  - [ ] Parse user request into clear requirements
  - [ ] Identify inputs, outputs, transformations
  - [ ] Map to workflow pattern (fetch-transform-store, etc.)
  - [ ] List required external services

  **Output**: Clear mental model of what needs to happen

  ### 2. DISCOVER (5 min)
  - [ ] Identify node categories needed
  - [ ] Run `pflow registry list` to find relevant packages
  - [ ] Run `pflow registry describe node1 node2...` for specs
  - [ ] Note: input params, output structure, special requirements

  **Output**: List of nodes with their interfaces understood

  ### 3. DESIGN (5 min)
  - [ ] Sketch data flow on paper/mentally: A → B → C
  - [ ] Plan node IDs (descriptive names)
  - [ ] Identify template variables needed
  - [ ] Plan edge connections

  **Output**: Clear design of node graph

  ### 4. BUILD (10 min)
  - [ ] Create workflow JSON with nodes
  - [ ] Add edges for flow
  - [ ] Add inputs/outputs declarations
  - [ ] Write templates referencing data flow

  **Output**: workflow.json file

  ### 5. VALIDATE (2 min per iteration)
  - [ ] Run `pflow --validate-only workflow.json`
  - [ ] Read error messages carefully
  - [ ] Fix ONE error at a time
  - [ ] Re-validate

  **Output**: Structurally valid workflow

  ### 6. TEST (Variable)
  - [ ] If MCP tools with `result: Any`, test to discover output structure
  - [ ] Run `pflow --trace workflow.json params...`
  - [ ] Check trace file for actual outputs
  - [ ] Update templates if needed

  **Output**: Workflow that executes successfully

  ### 7. REFINE (Variable)
  - [ ] Improve prompts for better results
  - [ ] Add error handling (check docs for patterns)
  - [ ] Optimize data flow
  - [ ] Add better descriptions

  **Output**: Production-ready workflow

  ### 8. SAVE (1 min)
  - [ ] Run `pflow workflow save workflow.json name "description"`
  - [ ] Workflow now available globally

  **Output**: Reusable workflow in library

  ---

  **Estimated time**:
  - Simple workflow (2-3 nodes): 20-30 minutes
  - Complex workflow (5-7 nodes): 45-60 minutes
  - Expert mode (familiar with nodes): 10-15 minutes

  6. Add "Common Mistakes and How to Avoid Them"

  ## Common Mistakes (Learn from Others!)

  ### ❌ Mistake 1: Starting with JSON Before Understanding
  **What happens**: You write nodes but don't know what data flows where

  **Instead**: Spend 5 minutes mapping the task first (see "UNDERSTAND" phase)

  ### ❌ Mistake 2: Not Checking Node Output Structure
  **What happens**: Templates like `${fetch.data.items}` fail because output is actually
  `${fetch.result.data}`

  **Instead**: Always run `pflow registry describe node-type` BEFORE writing templates

  ### ❌ Mistake 3: Building Everything at Once
  **What happens**: 10 nodes, 50 errors, impossible to debug

  **Instead**: Build 2 nodes, validate, add 1 more, validate, repeat

  ### ❌ Mistake 4: Ignoring Validation Errors
  **What happens**: You execute anyway, get cryptic runtime errors

  **Instead**: Trust validation - it catches 90% of issues before execution

  ### ❌ Mistake 5: Using Generic Node IDs
  **What happens**: Templates like `${node2.output}` are unreadable

  **Instead**: Use descriptive IDs like `${fetch-messages.result}` for clarity

  ### ❌ Mistake 6: Forgetting MCP Tools Need Full Path
  **What happens**: `pflow registry describe SLACK_SEND_MESSAGE` → "Unknown node"

  **Instead**: Use full format: `mcp-slack-composio-SLACK_SEND_MESSAGE`

  ---
  Summary: What Makes This the "Perfect" Document

  The perfect agent instructions should:

  1. Start with mental models, not commands
  2. Teach the thinking process, not just the syntax
  3. Provide progressive complexity (crawl → walk → run)
  4. Show common patterns to recognize
  5. Include decision trees for node selection
  6. Document the full development loop (currently missing!)
  7. Call out common mistakes explicitly
  8. Provide time estimates (agents need to plan)
  9. Include "why" not just "how" (understanding vs. memorization)

  The current document is great for reference but weak for learning. It assumes the agent
  already knows HOW to think about workflows.

  The missing piece: Teaching the agent how to decompose tasks into workflows BEFORE jumping
  to commands.

---

Userfeedback:

Great work, I love your attention to details and enthusiasm! This is gold, we need to keep most of this! I few points I want to highlight before you finalize the plan and write a new document:

in the development loop:

2. discover:

pflow registry discover should be the main way to discover nodes. (registry list + registry describe are backups if the internal llm in pflow fails to discover the nodes)

6. test:

only discover "any" outputs if you truly need to know the exact output or if you NEED to include any of the nested information in your workflow output.

7. refine:

error handling in the workflow is not currently supported since the workflow ir does not support branching.
