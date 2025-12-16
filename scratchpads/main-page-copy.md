# pflow Landing Page Copy

All text content from the main landing page (pflow.run).

---

## Navigation Bar

**Logo:** pflow

**Links:**
- How it Works
- Docs
- Blog

**CTA:** Get Started

---

## Hero Section

**Announcement Badge:**
> News: pflow CLI v1.0 Released

**Headline:**
> Agents can do incredible things.
> But they can't scale. **Yet.**

**Subheadline (with rotating word):**
> Your agent is [Thinking/Accomplishing/Actioning/Brewing/Calculating/Clauding/Coalescing/Cogitating/Computing/Conjuring/Considering/Cooking/Crafting/Creating/Crunching/Deliberating/Determining/Doing/Effecting/Finagling/Forging/Forming/Generating/Hatching/Herding/Honking/Hustling/Ideating/Inferring/Manifesting/Marinating/Moseying/Mulling/Mustering/Musing/Noodling/Percolating/Pondering/Processing/Puttering/Reticulating/Ruminating/Schlepping/Shucking/Simmering/Smooshing/Spinning/Stewing/Synthesizing/Transmuting/Vibing/Working]...
> through the same problem from scratch.
> Full cost. Same latency. Same risk of failure.
> Every time.
> **pflow** turns that reasoning into workflows your agent can reuse.
> Plan once. Run forever.

**CTAs:**
- Star on GitHub (primary)
- Join Cloud Waitlist (secondary)

**Compatibility Note:**
> Open source - Works with any agent - [Anthropic, OpenAI, Cursor, Windsurf, GitHub Copilot, Amazon Q, Claude logos]

**Below Terminal Demo:**
> Read the **prompt** or see full **evals**.

---

## Live Benchmark Card (Hero)

**Label:** Live Benchmark

**Metrics Display:**
> [X]% cheaper - [X]% faster

**Comparison Bars:**
- Cost:
  - Without pflow: $X.XX
  - With pflow: $X.XX*
- Time:
  - Without pflow: Xs
  - With pflow: Xs

**Per-Run Display:**
> Run [X]: $X.XX saved - Xs faster

---

## The Reasoning Tax Section

**Section Label:** The Reasoning Tax

**Headline:**
> Every tool call returns to the model. Every return costs tokens and time.

**Body Copy:**
> Traditional agents make round-trips to the model between every tool call—each one requiring inference. A 5-step workflow means 5+ inference passes, tokens accumulating at every step.

> **With pflow,** workflows compile once. After that, data flows through validated nodes without returning to the model which dramatically reduces token consumption.

### Traditional Agent Panel

**Title:** Traditional Agent

**Content Label:** Workflow Execution:

**Flow:**
```
Request
↓
load_mcp_schemas()          [skull] 47K tokens
↓
inference: "which tool?"           ~1K tokens
↓
call_github_api()           returns to model ~500
↓
inference: "what next?"            ~1K tokens
↓
call_sheets_api()           returns to model [skull] ~5K
↓
inference: "what next?"            ~1K tokens
↓
call_slack_api()            returns to model ~1K
↓
inference: "format result"         ~1K tokens
↓
format_result()                    ~500 tokens
↓
Response
```

**Warning Banner:**
> ~60K tokens - 4 inference passes - Every request

### pflow (compiled) Panel

**Title:** pflow (compiled)

**Content Label:** Workflow Execution:

**Flow:**
```
Request + params
↓
load_pflow_instructions            ~2K tokens
↓
discover_workflow()                ~500 tokens
↓
execute_workflow                   0 tokens
↓
node_1: github                     → data
↓
node_2: sheets                     → data
↓
node_3: process                    → data
↓
node_4: slack                      → data
↓
workflow_completed()        returns ~300
↓
format_result()                    ~500 tokens
↓
Response
```

**Success Banner:**
> ~3.5K tokens - 3 inference passes - 94% reduction

### The Scaling Effect Box

**Title:** The Scaling Effect

| Steps | Traditional | pflow | Savings |
|-------|-------------|-------|---------|
| 4 steps | 60K | 3.5K | 94% |
| 10 steps | 140K | 3.5K | 97% |
| 20 steps | [skull] 280K | [checkmark] 3.5K | 99% |

**Footer:**
> Traditional scales with steps. pflow stays flat.

**Footnote:**
> * Demo uses Claude Code (+18K system instructions token overhead on both sides)

**Additional Body Copy:**
> By writing explicit orchestration logic, Agents make fewer errors than when juggling multiple tool results in natural language. With pflow, just as with [Programmatic Tool Calling](https://www.anthropic.com/engineering/advanced-tool-use#programmatic-tool-calling), the model only needs to reason about the final result.

---

## How It Works Section

**Section Label:** How It Works

**Headline:**
> Five nodes. Infinite workflows.

**Body Copy:**
> Stop paying for the reasoning tax. Mix deterministic execution with selective intelligence. MCP, HTTP, and Shell nodes run at zero tokens. Use LLM and Agent nodes only when reasoning adds real value and choose the best model for the job.

> **So how does it work?**

### Node Types Panel

**Header:** Node Types | pflow orchestration layer

**Nodes Grid:**

**Deterministic Row:**
- **MCP NODE** - Any MCP server
- **HTTP NODE** - Direct REST
- **SHELL NODE** - Bash/CLI

**Divider:**
> 95% of steps don't need reasoning

**Intelligence Row:**
- **LLM NODE** - When needed
- **AGENT NODE** - Agentic subtasks (beta)

**Footer:**
> **Deterministic by default. Intelligent by choice.**
>
> Workflows are discovered intelligently. Node schemas load on demand. Responses and JSON schemas are optimized for LLM clarity and minimal token usage. pflow is an LLM-first workflow orchestrator.
>
> [Docs →]

---

## Agent Integration Pattern Section

### 1. Setup Panel

**Header:** 1. Setup | ~20 tokens

**Body:**
> Add to AGENTS.md, claude skill, or system prompt:

**Code:**
> "Use pflow for workflow automation"

**Comment:**
> # No overhead if using CLI, or use pflow MCP for one MCP to rule them all

### 2. Discover Panel

**Header:** 2. Discover | pflow instructions usage ~2k tokens

**Body:**
> Check if workflow already exists:

**Commands:**
```bash
$ pflow workflow discover "task"
$ pflow registry discover "capability"
```

**Match Found Branch:**
- Match Found | Execute
- # Run saved workflow
- `$ pflow workflow-name`
- # Or run node directly
- `$ pflow registry run node`
- Tokens: **0**

**No Match Branch:**
- No Match | Create workflow
- # Read build instructions
- `$ pflow instructions create`
- # Save for reuse
- `$ pflow workflow save workflow.json`
- Tokens: **~15k** (once)

**Success Banner:**
> Most requests hit existing workflows: 2k tokens total

### 3. Execute Forever Panel

**Header:** 3. Execute Forever | 0 tokens

**Body:**
> Saved workflows available to you and the agent:

**Command:**
```bash
$ pflow workflow-name param=value
```

**Comment:**
> # Same workflow, any parameters—no re-planning needed

---

## Direct Execution Section

**Section Label:** Direct Execution

**Headline:**
> Drop the agent

**Body Copy:**
> Compiled workflows run as CLI commands. Pipe them, chain them, cron them. No orchestration overhead. Minimal LLM costs. Same reliable output every time.

### Code Block

```bash
# Execute compiled workflow directly
pflow analyze-logs input=logs/api.log
# Pipe in from any CLI tool
cat error.log | pflow "extract errors and suggest fixes"
# Pipe out to files or chain commands
pflow analyze-logs | grep "ERROR" >> report.txt
# Perfect for automation
0 */6 * * * pflow daily-report >> ~/reports/latest.md
```

### Direct Execution Terminal (per scenario)

**Title:** pflow | direct cli execution
**Badges:** 95% cheaper, 85% faster

**API Analysis Scenario:**
```
$ pflow analyze-logs input=logs/api.log format=json

Executing workflow (9 nodes):
    fetch-messages... ✓ 1.8s
    analyze-patterns... ✓ 3.2s
    format-output... ✓ 0.4s
    write-results... ✓ 0.6s

✓ Workflow completed in 10.432s

Found 3 error patterns in 1,247 log entries
Output written to: analysis-report.json
```

**Data Processing Scenario:**
```
$ pflow process-csv input=data.csv output=summary.json

Executing workflow (7 nodes):
    load-csv... ✓ 0.8s
    validate-schema... ✓ 1.2s
    transform-data... ✓ 2.8s
    aggregate-metrics... ✓ 1.6s
    generate-summary... ✓ 0.9s

✓ Workflow completed in 9.847s

Processed 12,543 rows
Summary written to: summary.json
```

**Error Detection Scenario:**
```
$ pflow detect-errors source=logs threshold=critical

Executing workflow (8 nodes):
    scan-logs... ✓ 2.1s
    parse-entries... ✓ 1.9s
    detect-patterns... ✓ 3.4s
    classify-severity... ✓ 1.2s
    generate-report... ✓ 0.7s

✓ Workflow completed in 11.234s

Detected 7 critical errors across 8,456 log entries
Report saved to: error-report.json
```

---

## MCP Native Section

**Section Label:** MCP native

**Headline:**
> Every MCP you've been avoiding? Now you can use them.

**Body Copy:**
> Anthropic built [Tool Search](https://www.anthropic.com/engineering/advanced-tool-use#tool-search-tool) and [Code Execution](https://www.anthropic.com/engineering/code-execution-with-mcp#programmatic-tool-calling) to tackle MCP's context cost. pflow shares the goal but differs on philosophy: we believe LLMs perform best with clear, reusable blocks—not the freedom to generate anything. Structured workflows. Validated nodes. Like Lego: constrained pieces, infinite combinations. No sandbox required. No tool config to maintain.

**Emphasis:**
> Connect everything. pflow handles the complexity.

**Links:**
> See how pflow solves: MCP Context Tax - Inference overhead - Context pollution - Safety and reliability

**Visual:** Grid showing pflow logo connected to MCP service logos (GitHub, Slack, Notion, Linear, Google Calendar, Supabase)

---

## Install Section

**Install Commands (dropdown selector):**
- UV: `uv tool install pflow`
- PIP: `pip install pflow`

**Visual:** Grid with icons for Data, AI Models, Terminal, Open Source—all connected to install command in center

---

## Local-First Section

**Section Label:** Local-First - No Lock-In

**Headline:**
> Your terminal. Your data. Your AI models. Your agents.

**Body Copy:**
> Open source and free forever. pflow workflows runs locally with the AI providers you choose and gets created by Agents that you allready trust. No lock-in to OpenAI, Anthropic, or anyone else. Your workflow definitions and execution logs stay on your machine as json files. Install once, own forever.

---

## Build Reusable Skills Section (Dark)

**Section Label:** Build reusable skills for your agents

**Headline:**
> Run the same workflow more than 3 times?

**Subheadline:**
> You're paying for repeated reasoning that should have been compiled once.

**Code Block:** Shows compiled workflow JSON for `slack-qa-analyzer`:
```json
{
  "name": "slack-qa-analyzer",
  "description": "Fetches last 10 messages from a Slack channel, identifies questions, generates AI answers, sends responses back to Slack, and updates a Google Sheets spreadsheet with the Q&A pairs",
  "ir": {
    "inputs": {
      "channel_id": { ... },
      "spreadsheet_id": { ... },
      "sheet_name": { ... }
    },
    "nodes": [
      { "id": "fetch-messages", "type": "mcp-composio-slack-...", ... },
      { "id": "get-date", "type": "shell", ... },
      { "id": "get-time", "type": "shell", ... },
      { "id": "extract-messages-json", "type": "shell", ... },
      { "id": "identify-questions", "type": "llm", ... },
      { "id": "parse-qa-pairs", "type": "shell", ... },
      { "id": "count-questions", "type": "shell", ... },
      { "id": "format-slack-message", "type": "shell", ... },
      { "id": "send-to-slack", "type": "mcp-composio-slack-...", ... },
      { "id": "prepare-sheets-data", "type": "shell", ... },
      { "id": "update-google-sheets", "type": "mcp-googlesheets-composio-...", ... }
    ],
    "edges": [...],
    "outputs": {...}
  },
  "rich_metadata": {
    "execution_count": 66,
    "last_execution_success": true,
    ...
  }
}
```

---

## Efficient & Secure by Design Section

**Section Label:** Efficient & Secure by Design

**Headline:**
> The AI orchestrates. It never sees your data.

**Body Copy:**
> pflow uses structure-only orchestration during creation of workflows. AI understands what to connect, not the data flowing through it. Your sensitive information stays in the runtime, never enters AI context.

> **Result:** 5-100× token efficiency + compliance-ready security for healthcare, finance, and any regulated industry.

> **Usecase:** Let powerful cloud models create a workflow. Use local or compliance verified cheap models inside the workflow to read data.

### Traditional MCP Panel

**Title:** Traditional MCP
**Token Count:** 3,847 tokens
**Status:** EXPOSED

**Content Label:** AI Context Window:

```json
{
  "id": 123,
  "name": "John Smith",
  "email": "john@example.com",
  "ssn": "███-██-████",
  "dob": "1990-01-15",
  "address": {...},
  "payment_method": {...},
  ... 40 more fields
}
```

*(SSN field has skull icons overlaid indicating exposed sensitive data)*

### pflow (structure-only) Panel

**Title:** pflow (structure-only)
**Token Count:** 300 tokens
**Status:** PROTECTED

**Content Label:** AI Context Window:

```
Only see what's needed:
    ✓ ${customer.id} : int
    ✓ ${customer.name} : string
    ✓ ${customer.email} : string
    ✓ ${customer.status} : enum

[47 additional fields cached]
[Actual data → 🔒 permission required]
```

### Shield Protected Service Visual

Shows rotating logos of protected services (Notion, Slack, Google Calendar, Drive, Linear, Gmail, GitHub, Supabase, Discord, Google Sheets, Jira, Trello, YouTube, Firecrawl) with shield icon.

**Link:** Read more in our blog →

---

## Safe by Design / Compiled Guardrails Section

**Section Label:** Safe by Design

**Headline:**
> Your safety checks can't be skipped. Ever.

**Body Copy:**
> Traditional agents make individual tool calls, reasoning through each step every time. They might skip validation, modify the wrong data, or take different execution paths. This is why developers limit agents to read-only operations.

> **With pflow,** agents operate with workflows as composite tools instead of executing individual steps. The entire workflow becomes a single, deterministic tool call—safety checks and guardrails are compiled in and can't be bypassed.

> **The result?** You can finally automate write operations, deployments, and critical workflows you'd never trust to a traditional agent.

### Traditional Agent Panel

**Title:** Traditional Agent

**Content Label:** Workflow Execution:

| Run 1 | Run 2 | Run 3 |
|-------|-------|-------|
| → validate_input() | → validate_input() | ~~→ validate_input()~~ |
| → ask_confirmation() | ~~→ ask_confirmation()~~ | → exec_different_path() |
| → execute_write() | → execute_write() | |
| ✓ Success | ⚠ Skipped safety | ⚠ Different approach |
| | | ⚠ or failure |

**Warning Banner:**
> Unpredictable. Can't trust with writes.

### pflow (compiled) Panel

**Title:** pflow (compiled)

**Content Label:** Workflow Execution:

| Run 1 | Run 2 | Run 3 |
|-------|-------|-------|
| → validate_input() | → validate_input() | → validate_input() |
| → ask_confirmation() | → ask_confirmation() | → ask_confirmation() |
| → execute_write() | → execute_write() | → execute_write() |
| ✓ Success | ✓ Success | ✓ Success |

**Success Banner:**
> Deterministic. Safe for production.

---

## Two Ways to Use pflow Section

**Headline:**
> Two Ways to Use pflow

**Subheadline:**
> Open source CLI for individuals and technical teams. Managed cloud for teams that prioritize ease of use and collaboration.

---

## Open Source CLI Offering

**Headline:** Open Source CLI

**Tagline:** Install in 60 seconds

**Features:**
- → Local-first execution
- → Works with any (local) agent
- → Git-friendly workflow files
- → No external dependencies
- → Learning and experimentation

**Pricing:**
- Headline: **FREE**
- Note: [FSL/Apache 2.0 License](https://fsl.software/)

**Perfect For:**
- → Individual developers
- → CI/CD integration
- → Privacy-conscious workflows

**CTAs:**
- Star on GitHub (primary)
- Read Docs (secondary)

---

## Managed Cloud Offering

**Badge:** Coming Q1 2026

**Headline:** Managed Cloud

**Tagline:** Zero-setup infrastructure

**Features:**
- → Hosted workflow execution
- → Team collaboration
- → Workflow marketplace
- → Enterprise SSO

**Pricing:**
- Headline: **Based on usage**
- Note: First 100 teams get 6 months free

**Perfect For:**
- → Teams and organizations
- → Production deployments
- → Shared workflow libraries

**CTA:**
- Join Waitlist (primary)

---

## FAQ Section

**Section Label:** FAQ

**Headline:** Common Questions

**Subheadline:**
> Everything you need to know about pflow workflow compilation

### Q: Does this work with my current agent?

> Yes. If your agent can use bash tools OR MCP tools, it can use pflow. The only limitation right now is that the agent needs to run on your machine (like Claude Code, Cursor, Coxex, Claude Desktop App etc.), not in the cloud/browser. But this all changes with pflow cloud or by hosting your own pflow mcp server.

### Q: How is this different from prompt caching?

> Prompt caching reduces **input token costs** (context/schemas). pflow eliminates **output token costs** (reasoning). They're complementary—use both for maximum savings.
>
> The key difference: Prompt caching gives you a 90% discount on loading schemas. But you still pay full price ($15/1M tokens) for the AI to reason through orchestration every time. pflow compiles that reasoning once, then execution is free.

### Q: What if my workflow needs to change?

> You can modify workflows directly (they're just JSON files) or ask the agent to recompile. Changes are versioned like code in git. If you need a variation, you can either:
> - Edit the JSON workflow file manually
> - Use template variables for dynamic inputs
> - Recompile with new requirements (costs one more compilation)

### Q: Can I share workflows with my team?

> Yes. Workflows are standard JSON files. You can:
> - Commit to git and share via repository
> - Publish to npm as packages
> - Use our Cloud marketplace (coming Q1 2026)
> - Copy/paste the JSON directly
>
> Since workflows are just data files, they work with your existing collaboration tools.

### Q: What about security and compliance?

> The CLI runs locally with your credentials—nothing is sent to pflow servers. Workflows can be audited before execution since they're readable JSON.
>
> The Cloud version (coming soon) will have SOC 2 and GDPR compliance. But for sensitive workflows, the local CLI ensures everything stays on your machine.

### Q: Does compilation always save money?

> Yes for complex workflows (immediately), and yes for simple workflows (by run 2).
>
> **Complex workflows** (multi-step, $2-5): Save money from day one. pflow's optimizations—passing only essential data between steps and loading tools on-demand—reduce token usage and execution time compared to traditional agents, even on the first run.
> - **Run 1:** $2.50 with pflow vs $3.00 traditional (17% savings from optimizations)
> - **Run 2:** $2.70 total with pflow vs $6.00 traditional (55% savings)
> - **Run 10:** $4.30 with pflow vs $30.00 traditional (86% savings)
> - **Run 100:** $22.30 with pflow vs $300 traditional (**95%+ savings**)
>
> **Simple workflows** (1-3 steps, ~$1): Break even by run 2.
> - **Run 1:** $1.25 with pflow vs $1.00 traditional (25% compilation overhead)
> - **Run 2:** $1.45 total with pflow vs $2.00 traditional (already saving)
> - **Run 10:** $3.05 with pflow vs $10.00 traditional (70% savings)
> - **Run 100:** $21.25 with pflow vs $100 traditional (79% savings)
>
> **For repetitive tasks**, the math becomes compelling: A daily complex workflow ($3 each) costs $1,095/year with traditional agents vs $75/year with pflow. Break-even happens so fast it's barely a consideration. The question isn't 'if' you save money, but whether you save 80% or 99%.
>
> **The hidden value:** pflow enables safe write operations. Traditional agents are unpredictable—they might skip validation or modify the wrong data. With pflow, guardrails are compiled in and can't be bypassed. This lets you automate workflows you'd never trust to traditional agents.
>
> Manual execution via CLI/CI-CD? Just $0.002 per run using optimized models—essentially free.

### Q: How mature is this?

> Early stage. The CLI is functional but has rough edges. The Cloud version is in development.
>
> We're looking for early adopters who:
> - Can tolerate bugs and provide feedback
> - Want to shape the product direction
> - Need the cost/speed benefits now
>
> If you need production-ready with guaranteed uptime, wait for Cloud (Q2 2026).

### Q: Can I inspect the compiled workflow?

> Yes. Workflows are saved as human-readable JSON files. You can:
> - Read the entire workflow structure
> - See which tools are called and in what order
> - Understand the decision logic
> - Modify parameters manually
> - Version control with git
>
> We believe in transparency. No black boxes.

### What to Expect Box

> - A [public roadmap](https://docs.pflow.run/roadmap) shaped by your feedback
> - New [features and fixes](/changelog) every week

---

## Footer

### Contributor Call-Out

> **Help build pflow.** We're a small team building something big — early contributors are invaluable.
> Want to contribute or talk to the founder? Email me: andreas@pflow.run or dive into the code on [GitHub](https://github.com/spinje/pflow).

### Social Links
- GitHub
- Twitter/X
- Discord

### Copyright
> © 2025 pflow
> [FSL/Apache 2.0 License](https://github.com/spinje/pflow/blob/main/LICENSE)

### Footer Sections

**Product:**
- How It Works
- CLI
- Cloud (Coming Soon)
- Pricing
- Use Cases

**Resources:**
- Documentation
- Quick Start
- Examples
- API Reference
- Changelog

**Company:**
- About
- Blog
- Research
- Contact

**Community:**
- GitHub Discussions
- Discord
- Twitter
- Contributing

---

## Terminal Scenario Tabs

Three scenarios available for terminal comparison demo:

1. **API Analysis** - Analyze API logs
2. **Data Processing** - Process and transform data
3. **Error Detection** - Detect and classify errors

---

*Document generated from pflow-cloud landing page source code.*
