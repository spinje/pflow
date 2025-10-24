# pflow

**Turn expensive, one-off AI prompts into permanent, instant CLI commands.**

Workflows that take an AI agent 2 minutes and $1.00 to figure out *every time*, pflow figures out once, then runs in 2 seconds (at least the planning part) for free, forever.

One command that finds your workflow or builds it for you. Describe what you want—pflow either runs your existing workflow or creates it on the spot.

```bash
# Describe what you want:
$ pflow "analyze customer churn from stripe and hubspot for last month"

# First time: Creates the workflow (30 seconds)
→ No existing workflow found. Building one for you...
✨ Created and saved as 'analyze-churn'

# Every time after: Finds and runs it instantly (2 seconds)
$ pflow "analyze customer churn for this week"  # Different time period, same workflow
→ Found 'analyze-churn'. Running with period: 2025-07-22 to 2025-07-28
✅ Analysis complete!
```

## What is pflow?

Have you ever asked an AI agent to perform a multi-step task, like analyzing data from two different APIs? It works, but it's slow and you pay for the same reasoning every single time. You could ask the agent to write a script, but then you're stuck maintaining boilerplate code, and chaining multiple scripts together is a nightmare.

**`pflow` fixes this. Say goodbye to boilerplate and glue code.**

`pflow` is a **workflow compiler**. It lets you describe a complex task in plain English *once*. An AI planner figures out the steps, connects the tools (yes that includes MCP servers), and saves the result as a permanent, lightning-fast CLI command.

It turns your ideas into your own personal, reusable toolchain that you (or your AI agents) can use.

## The `pflow` Difference: Plan Once, Run Forever

This is not just another AI wrapper. `pflow` fundamentally changes the economics and speed of AI-driven automation.

1.  **PLAN (First Run):** You describe a complex workflow. `pflow` uses AI to intelligently select, chain, and map the right tools, creating a deterministic plan. (*This is the only time you pay in time, tokens, and reasoning overhead.*)

2.  **COMPILE (Automatic):** `pflow` saves this plan as a reproducible, version-locked artifact. It is now a permanent part of your toolkit.

3.  **EXECUTE (Every Subsequent Run):** You run your new command by name. It executes instantly with no AI, no planning, no cost, and no variation—giving you the exact same result, every time.

Workflows adapt to different inputs—analyze last month, this week, or any time period with the same workflow. It extracts and uses all dynamic values from the users input and integrates them into the workflow as resuable parameters.

## License

pflow is licensed under the [Functional Source License (FSL) v1.1](LICENSE) with Apache-2.0 future license.

- ✅ **Free for all use** except offering pflow as a managed service
- ✅ **Becomes fully open source** (Apache-2.0) on January 1, 2028
- ✅ **Modify, distribute, use commercially** - just don't compete directly with a hosted version

## Quick Start

### 1\. Your First Flow

```bash
# Install pflow
pip install pflow

# Just describe what you want:
pflow "check my github PRs and summarize them for standup"

# If it's new, pflow builds it:
# → Creating workflow: github-list-prs --state=open >> llm --prompt="summarize for standup"
# Save as 'standup-prep'? [Y/n] y

# If it exists, pflow runs it:
pflow "summarize my PRs for standup"
# → Found 'standup-prep'. Running...
```

### 2\. Build Complex Workflows

```bash
# Chain multiple tools together
pflow "fetch aws costs, analyze by service, create report, send to slack"

# See the generated pipeline:
# → aws-get-costs --period=7d >> llm --prompt="analyze by service" >> write-file --format=markdown >> slack-send --channel=ops
```

### 3\. Integrate Everything

```bash
# Use existing tools as building blocks
cat error.log | pflow "extract errors, find related code, suggest fixes" >> fixes.md

# Combine with any CLI tool
kubectl logs my-pod | pflow "check for errors and notify if critical"
```

## Wait.. my AI agent can already do this and it works great!

Does it? Try this:

```bash
# Load the GitHub MCP server and check its token usage:
$ claude --mcp-config ./github.mcp.json --strict-mcp-config --debug "list my PRs"
> Context used: 46,000 tokens before processing
```

That's 1/4 of Claude's context window gone just to load GitHub tools. Add Slack and JIRA:

```bash
$ claude --mcp-config ./github.mcp.json ./jira.mcp.json ./slack.mcp.json \
         --strict-mcp-config "check PRs, update tickets, post summary"
> Context: 64,050 tokens loaded
> Time: 30 seconds
> Cost: $0.22 per run
```

**Here's the problem**: Every time your AI agent needs GitHub, Slack, and JIRA tools, it loads 64k tokens of MCP schemas, reasons through the orchestration, and might choose a different approach than last time. Before thinking about your request, you've consumed 1/3 of your context window. Run this 10x daily? That's $803/year in context costs—plus reasoning overhead, plus non-determinism. These problems compound.

**pflow solves this**: Your agent uses pflow to build the workflow ONCE. It figures out which tools to use and compiles that knowledge into a workflow. After that? The workflow executes those same MCP tools without loading schemas, without reasoning, without variation—0 context, 0 cost, perfectly deterministic. Every avoided token, every skipped reasoning step, every guaranteed result multiplies across every execution.

**"What about MCP tool aggregators like Zapier MCP or Composio?"**

They give your agent access to 8,000+ actions, but solve a different problem:

| | **MCP Tool Aggregators**<br/><sub>Zapier MCP, Composio, Strata</sub> | **pflow** |
|---|:---:|:---:|
| **What they provide** | Individual actions<br/><sub>(send Slack message, get Stripe payment)</sub> | Workflow infrastructure<br/><sub>(build, validate, execute, debug)</sub> |
| **How agents use them** | Orchestrate actions in real-time<br/><sub>Think through steps every execution</sub> | Build workflow once<br/><sub>Execute compiled pattern forever</sub> |
| **Token cost** | Full reasoning overhead per run<br/><sub>$0.15 × 365 days = $55/year</sub> | One-time compilation<br/><sub>$0.15 once + $0.01 × 364 = $4/year</sub> |
| **Determinism** | ❌ Agent may change approach<br/><sub>Different results each time</sub> | ✅ Compiled workflow<br/><sub>Same inputs = same outputs</sub> |

**Different layers of the stack**: Tool aggregators expose APIs. pflow compiles how to use them.

**The dirty secret**: Most developers aren't even using MCP servers. They're playing the "training data lottery" instead:

```bash
# What they should do (but costs 46k tokens):
$ claude --mcp-config ./github.mcp.json "analyze my PRs"

# What they actually do (and hope it works):
$ claude "use gh cli to analyze my PRs"
# Praying the AI remembers 'gh' from 2023 training data
```

Your agent "works great" until you:
- Need the same workflow 10x daily ($2.20/day = $803/year)
- Want deterministic results (not different outputs each run)
- Load 5+ MCP servers (sessions become unusable)
- Need it to run in under 30 seconds

pflow compiles what your agent figures out into something that actually works at scale: 2-5 seconds, $0 cost, deterministic execution, every time.



## Who is `pflow` for?

`pflow` is for you if you've ever felt the pain in the "messy middle" of automation:

  * Your task is **too complex for a simple CLI pipe**, involving multiple tools, APIs, and data transformations.
  * Your workflow is **too ad-hoc and exploratory for a production orchestrator** like Airflow or Prefect.
  * You find **asking an AI agent to do the same multi step task** over and over or asking an AI agent to write **the same kind of scripts** again and again.
  * You have a dozen different CLI tools, mcp servers and custom scripts and wish you could **combine them with a single command.**
  * You know the negative impact of AI agents context window when using MCPS and wish you could **use them without the performance impact.**

`pflow` is designed to automate the automators.

## What Problems Does pflow Solve?

pflow addresses the **workflow compilation layer** that existing solutions don't. Even with access to thousands of tools, AI agents orchestrate them from scratch every time:

| Problem | MCP Tool Servers<br/><sub>Zapier MCP, Composio, Strata</sub> | Visual Workflow Builders<br/><sub>n8n, Zapier, Make.com</sub> | **pflow** |
|---------|:-------------------------------------------------------------:|:-------------------------------------------------------------:|:---------:|
| **Access to tools/APIs** | ✅ Thousands of integrations | ✅ Thousands of integrations | ✅ Any MCP server |
| **Agent can use tools** | ✅ Direct MCP access | ❌ Manual visual building | ✅ Conversational building |
| **Workflow compilation**<br/><sub>Build once, run forever</sub> | ❌ Orchestrate every time | ⚠️ Manual configuration | ✅ Automatic compilation |
| **Token efficiency**<br/><sub>Avoid repeated reasoning</sub> | ❌ Full cost every execution | N/A | ✅ 93% cost reduction |
| **Deterministic execution**<br/><sub>Same inputs = same outputs</sub> | ❌ Varies by agent mood | ✅ Fixed workflow | ✅ Compiled workflow |
| **Pattern reuse**<br/><sub>Learn from previous workflows</sub> | ❌ Zero learning | ⚠️ Manual templates | ✅ Automatic discovery |
| **Natural language interface** | ⚠️ Via agent wrapper | ❌ Visual drag-and-drop | ✅ Native |

**The gap**: Existing MCP servers give agents access to tools but require orchestration every time. Visual builders save workflows but need manual configuration. pflow compiles agent-orchestrated workflows into deterministic, reusable patterns.

## Why use `pflow`?

The real competition for `pflow` isn't just the AI chat window—it's the combination of scattered scripts and repeated AI prompts. Here's why `pflow` is better than both:

| Feature | AI-Generated `script.py` | `pflow` Flow |
| :--- | :--- | :--- |
| **Boilerplate** | Full of `argparse`, `requests`, and auth code you have to maintain. | **Zero boilerplate.** Nodes are pure logic. |
| **Composability**| Hard. Chaining two scripts requires manual edits and plumbing. | **Native.** `flow1 >> flow2` just works. |
| **Discoverability**| A messy folder of scripts (`do-thing.py`, `analysis_v2_final.py`). | Describe what you want—pflow finds or creates it. |
| **Maintenance** | An API changes? You hunt down and fix 10 different scripts. | An API changes? You update **one node.** |

> No more hunting through a dark forest of scripts for that `analysis_final_v2.py`

Why is it better than letting an AI agent call tools and mcp servers for you?

| Feature | Without `pflow` | With `pflow` |
| :--- | :--- | :--- |
| **Speed** | 1-5 minutes per run (agent re-thinks every time) | **\~2 seconds** (after one-time plan) |
| **Cost** | \~$0.10-2.00 per run (paying for LLM reasoning) | **Free** (after one-time plan) |
| **Reliability** | Non-deterministic; agent might change its mind | **100% Deterministic**; same input, same output |
| **Workflow** | Copy-paste from a chat log; hard to share | A shareable command: `pflow my-flow` |

## The Universal Automation Interface

`pflow` unifies workflow discovery and creation. One command does it all:

```bash
# Describe any task in natural language
pflow "analyze our AWS costs by service"

# If you've built it before:
→ Found 'aws-cost-analyzer'. Running...

# If it's new:
→ No workflow found. Creating: aws-costs >> llm-analyze >> report
→ Save as 'aws-cost-analyzer'? [Y/n]
```

No more wondering "do I have a script for this?" Just describe what you want—pflow handles the rest.

### Direct Execution: Even Faster

Once a workflow is saved, run it directly by name—no AI needed:

```bash
# Direct execution: 100ms instead of 2s
pflow aws-cost-analyzer

# With different parameters each time
pflow aws-cost-analyzer period=30d service=EC2

# Perfect for scripts and automation
0 9 * * * pflow daily-standup-prep >> ~/standup.md
```

When you know what you want to run, skip the discovery entirely.

## How It Works

`pflow` captures your intent and compiles it into a reliable tool, ready to be used by you, your team, or even other AI agents.

```mermaid
graph TD
    subgraph "Your Terminal"
        A[You: "pflow 'do a complex thing'"]
    end

    subgraph "pflow: Plan Once"
        B(AI Planner)
        C(Node Registry)
        D(Validation Engine)
        B -- Queries --> C
        B -- Generates --> D
    end

    subgraph "pflow: Compile"
        E[Saved CLI Command<br>(Deterministic Lockfile)]
    end

    subgraph "pflow: Run Forever"
        F[Instant Execution Engine]
    end

    A -- First Run --> B
    D -- Creates --> E
    A -- Subsequent Runs --> F
    E -- Informs --> F
```

## Installation

```bash
# Install via pip
pip install pflow
```

## How AI Agents Use pflow

Your AI agent (Claude, Cursor, ChatGPT, etc.) can work with pflow in two ways:

**1. Via pflow's MCP server** (recommended for programmatic control)

Add pflow to your Claude Desktop or AI tool:
```json
{
  "mcpServers": {
    "pflow": {
      "command": "pflow",
      "args": ["mcp"]
    }
  }
}
```

Your agent gets structured tools like `workflow_discover()`, `workflow_execute()`, `workflow_save()` to build and run workflows programmatically.

**2. Via CLI commands** (works anywhere with terminal access)

Your agent can run `pflow` commands directly. Same capabilities, different interface.

**The magic**: Either way, your agent builds workflows that USE MCP tools (GitHub, Stripe, Slack) without loading those MCP servers into context. One-time compilation → infinite free execution.

## MCP Integration

pflow supports **Model Context Protocol (MCP)** servers, letting you use any MCP-compatible tool as a workflow node. This opens up a vast ecosystem of AI tools that can be seamlessly integrated into your workflows.

### What is MCP?

MCP (Model Context Protocol) is Anthropic's open standard for connecting AI assistants to external tools. With pflow's MCP support, you can:
- Use filesystem operations, database queries, web scrapers, and more
- Access tools from the MCP ecosystem without writing custom nodes
- Combine MCP tools with native pflow nodes in workflows

### Quick Start with MCP

```bash
# 1. Add an MCP server (example: filesystem operations)
pflow mcp add filesystem npx @modelcontextprotocol/server-filesystem /Users/me/data

# 2. Sync available tools into pflow
pflow mcp sync

# 3. Use MCP tools in workflows (they appear as regular nodes!)
pflow "read all CSV files in my data folder and summarize them"
# → Automatically uses mcp__filesystem__read_file node
```

### Managing MCP Servers

```bash
# List configured servers
pflow mcp list

# View available tools from a server
pflow mcp tools filesystem

# Remove a server
pflow mcp remove filesystem

# Re-sync after server updates
pflow mcp sync --force
```

### Example: GitHub + Filesystem Workflow

```bash
# Add multiple MCP servers
pflow mcp add github npx @modelcontextprotocol/server-github
pflow mcp add fs npx @modelcontextprotocol/server-filesystem ~/projects

# Sync all tools
pflow mcp sync

# Create a workflow combining both
pflow "find all open PRs, save summaries to local files"
# Uses: mcp__github__search_pull_requests >> mcp__fs__write_file
```

MCP tools are prefixed with `mcp__<server>__` to avoid naming conflicts. They integrate seamlessly with pflow's planning system—just describe what you want, and pflow will find the right MCP tools.

> MCP servers added to pflow work with any AI agent that connects to pflow—no need to duplicate configurations across tools.

For detailed MCP configuration, see [architecture/features/mcp-integration.md](architecture/features/mcp-integration.md).

## Extensibility: MCP is the Way

**Every pflow extension is an MCP server. No custom node API to learn.**

> **Note**: This section is about extending pflow's capabilities by adding NEW tools (like a Stripe monitoring server). Your AI agent interacts with pflow *itself* via pflow's MCP server (described above) to build workflows using these tools.

Instead of building pflow-specific nodes, you build standard MCP servers that work everywhere:

```bash
# Need custom functionality? Build an MCP server
$ claude "Build an MCP server that monitors my Stripe webhooks"
# Claude generates stripe_monitor.py

# Add it to pflow
$ pflow mcp add stripe-monitor python stripe_monitor.py

# Use it immediately
$ pflow "alert me when a payment fails"
```

### Why MCP for Extensions?

- **No lock-in**: Your extensions work with Claude, ChatGPT, and any MCP-compatible tool
- **AI can build them**: Any AI assistant can create MCP servers without knowing pflow internals
- **Standard protocol**: Learn once, use everywhere
- **Ecosystem leverage**: Every MCP server built for other tools works with pflow

We don't have a custom node API because we don't need one. MCP is the extension mechanism.

## Real-World Examples

### Daily Standup Automation

```bash
# Build a tool that does your morning prep in 3 seconds instead of 15 minutes
pflow "check my PRs, check team's PRs, summarize slack since yesterday, format for standup"
# Runs identically every morning—same format, same reliability
```

### Production Debugging

```bash
# Create a reusable "first response" tool for incidents
pflow "fetch datadog errors for service 'api', correlate with recent deploys, check related PRs for 'breaking change' labels"
# Pattern reusable for any service—just change the service name
```

### Multi-System Analysis

```bash
# Build a tool to answer complex business questions without writing a script
pflow "get stripe failed payments for last month, match with hubspot contacts, draft outreach emails for users on 'Pro' plan"
```

### Report Generation

```bash
pflow "analyze last week's API usage, calculate costs, compare to budget, create report"
# Scheduled in cron, runs in seconds—deterministic results for auditing
```

## Debugging and Troubleshooting

pflow provides comprehensive debugging capabilities to help you understand and troubleshoot workflow generation:

### Real-Time Progress Indicators
See exactly what the planner is doing:
```bash
$ pflow "analyze code quality metrics"
🔍 Discovery... ✓ 2.1s
📦 Browsing... ✓ 1.8s
🤖 Generating... ✓ 3.2s
✅ Validation... ✓ 0.1s
```

### Trace Files for Deep Debugging
Capture complete execution details:
```bash
pflow "complex workflow request"
📝 Trace saved: ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json
```

Trace files include:
- All LLM prompts and responses
- Node execution times
- Decision paths taken
- Complete error information

### Configurable Timeouts
Prevent hanging with `--planner-timeout`:
```bash
pflow --planner-timeout 120 "very complex analysis"
# Allows up to 2 minutes for planning (default: 60s)
```

See the [Debugging Guide](architecture/features/debugging.md) for detailed trace analysis and troubleshooting tips.

## Ecosystem: Plays Well With Others

`pflow` doesn't replace your favorite tools—it orchestrates them.

### 🔌 MCP Integration

Access any MCP-compatible tool as a native `pflow` node:

```bash
# Add MCP servers for your favorite tools
pflow mcp add github npx @modelcontextprotocol/server-github
pflow mcp add stripe npx @modelcontextprotocol/server-stripe
pflow mcp sync
```

### 🤖 Works with `llm`

Use Simon Willison's `llm` CLI as a node:

```bash
pflow read-file --path=data.csv >> llm --prompt="analyze trends in this data" >> write-file --path=report.md
```

### 🚀 AI Agent Efficiency

When AI agents use `pflow`, they stop re-reasoning through repetitive tasks:

```bash
# First time: Agent figures out the workflow
Agent: "I'll analyze this PR by checking tests, reviewing changes..."

# Every time after: Agent just runs the workflow
Agent: `pflow analyze-pr --pr=123`
```

This reduces AI costs by 90% for repetitive tasks and lets agents work in parallel. `pflow` provides the stable, structured "API" that free-running agents need.

## The MCP Context Tax

Every MCP server you load consumes precious context:
- **GitHub MCP**: 46,000 tokens
- **Slack MCP**: 2,000 tokens
- **JIRA MCP**: 16,000 tokens
- **Database schemas**: 50,000+ tokens for complex tables

Load GitHub + Slack + JIRA? **64,050 tokens consumed before your agent even starts thinking.**

Run a workflow 10x daily with these servers? **$803/year** just in context costs (Claude Sonnet pricing).

**pflow's approach**: Pay the context tax once during workflow compilation. Figure out which tools to use and save that decision. Every execution after runs with zero MCP servers loaded, zero context consumed, zero cost.

Same workflow. Same MCP tools. Same results. Just compiled into a deterministic sequence your agent (or you) can execute instantly.

**Read more**: [The MCP Context Tax Nobody Talks About](architecture/vision/mcp-context-problem/the-mcp-context-tax-nobody-talks-about.md)

## Coming Soon

### Export to Zero-Dependency Code (v0.3)

Compile your workflows to standalone Python or TypeScript:

```bash
# Build workflow with pflow
$ pflow "analyze sales data and create report"

# Export to pure Python (no pflow needed!)
$ pflow export python analyze_sales.py
Generated: analyze_sales.py (142 lines, zero dependencies)

# Run anywhere
$ python analyze_sales.py  # No pflow required
```

The ultimate no lock-in guarantee: take your workflows and leave.

### pflow Cloud (Beta)

- **One-click OAuth**: Connect to GitHub, Slack, Notion without API key hassles
- **Team sharing**: Discover and reuse workflows across your organization
- **Cost tracking**: See exactly what your AI automation costs
- **For non-developers**: No CLI required

Join the waitlist at [getpflow.com](https://getpflow.com)

## Community

  * **Discord**: [Join our community](https://discord.gg/pflow)
  * **Examples**: [pflow-examples](https://github.com/pflow/examples)
  * **Nodes**: Browse MCP servers at [github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)

## Contributing

We are actively building the future of developer automation. Come help\!

```bash
git clone https://github.com/pflow/pflow
cd pflow
make install
make test
```

See our [CONTRIBUTING.md](https://www.google.com/search?q=CONTRIBUTING.md) for guidelines.

## Learn More

- **Quick Start Guide**: [docs/quickstart.md](docs/quickstart.md)
- **Creating Nodes**: [docs/nodes.md](docs/nodes.md)
- **Example Workflows**: [examples/](examples/)

---

**pflow** is open source (FSL with Apache-2.0 future license) and built on the simple idea that AI should help you create tools, not be the tool you run every time.

*Don't just run prompts. Build permanent tools* and transform your expensive AI workflows into instant CLI commands. [Get started now](#quick-start).
