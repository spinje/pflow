# pflow

**Turn expensive, one-off AI workflows into permanent, instant CLI commands.**

What takes an AI agent 2 minutes and $1.00 to figure out *every time*, pflow figures out once, then runs in 2 seconds for free, forever.

```bash
# First time: AI plans your workflow (30 seconds)
$ pflow "analyze customer churn from stripe and hubspot"
✨ Generated flow saved as 'analyze-churn'

# Every time after: Instant execution (2 seconds)
$ pflow analyze-churn
✅ Analyzing customer churn... done!
```

## What is pflow?

Have you ever asked an AI agent to perform a multi-step task, like analyzing data from two different APIs? It works, but it's slow and you pay for the same reasoning every single time.

**`pflow` fixes this.**

`pflow` is a **workflow compiler**. It lets you describe a complex task in plain English *once*. An AI planner figures out the steps, connects the tools, and saves the result as a permanent, lightning-fast CLI command.

It turns your ideas into your own personal, reusable toolchain.

## The `pflow` Difference: Plan Once, Run Forever

This is not just another AI wrapper. `pflow` fundamentally changes the economics and speed of AI-driven automation.

1. **PLAN (First Run):** You describe a complex workflow. `pflow` uses AI to intelligently select, chain, and map the right tools, creating a deterministic plan. (*This is the only time you pay in time and tokens.*)

2. **COMPILE (Automatic):** `pflow` saves this plan as a reproducible, version-locked artifact. It is now a permanent part of your toolkit.

3. **EXECUTE (Every Subsequent Run):** You run your new command by name. It executes instantly with no AI, no planning, and no cost, giving you the exact same result, every time.

## Quick Start

### 1. Your First Flow

```bash
# Install pflow
pip install pflow

# Describe what you want in plain English
pflow "check my github PRs and summarize them for standup"

# pflow generates and shows you the workflow:
# → fetch-github-prs --state=open >> llm "summarize for standup"
# 
# Run this flow? [Y/n] y
✅ Flow saved as 'standup-prep'

# Tomorrow morning, just run:
pflow standup-prep
```

### 2. Build Complex Workflows

```bash
# Chain multiple tools together
pflow "fetch aws costs, analyze by service, create report, send to slack"

# See the generated pipeline:
# → aws-costs --period=7d >> analyze-costs >> create-markdown >> slack-send --channel=ops
```

### 3. Integrate Everything

```bash
# Use existing tools as building blocks
cat error.log | pflow "extract errors, find related code, suggest fixes" >> fixes.md

# Combine with any CLI tool
kubectl logs my-pod | pflow check-for-errors >> notify-if-critical
```

## Who is `pflow` for?

`pflow` is for you if you've ever felt the pain in the "messy middle" of automation:

* Your task is **too complex for a simple CLI pipe**, involving multiple tools, APIs, and data transformations.
* Your workflow is **too ad-hoc and exploratory for a production orchestrator** like Airflow or Prefect.
* You find yourself **asking an AI agent to write the same kind of script** over and over.
* You have a dozen different CLI tools and wish you could **combine them with a single command.**

`pflow` is designed to automate the automators.

## Why use `pflow`?

| Feature | Without `pflow` | With `pflow` |
| :--- | :--- | :--- |
| **Speed** | 2-5 minutes per run (agent re-thinks every time) | **\~2 seconds** (after one-time plan) |
| **Cost** | \~$0.10 per run (paying for LLM reasoning) | **Free** (after one-time plan) |
| **Reliability** | Non-deterministic; agent might change its mind | **100% Deterministic**; same input, same output |
| **Workflow** | Copy-paste from a chat log; hard to share | A shareable command: `pflow my-flow` |

## How It Works

`pflow` captures your intent and compiles it into a reliable tool ready to be used by you, your AI agents, or your team either as a simple CLI command or invoked by using natural language.

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

# Install with MCP support
pip install "pflow[mcp]"

# Enable shell completion
pflow completion bash >> ~/.bashrc
```

## Real-World Examples

### Daily Standup Automation

```bash
# Build a tool that does your morning prep in 3 seconds instead of 15 minutes
pflow "check my PRs, check team's PRs, summarize slack since yesterday, format for standup"
```

### Production Debugging

```bash
# Create a reusable "first response" tool for incidents
pflow "fetch datadog errors for service 'api', correlate with recent deploys, check related PRs for 'breaking change' labels"
```

### Multi-System Analysis

```bash
# Build a tool to answer complex business questions without writing a script
pflow "get stripe failed payments for last month, match with hubspot contacts, draft outreach emails for users on 'Pro' plan"
```

### Report Generation

```bash
pflow "analyze last week's API usage, calculate costs, compare to budget, create report"
# Scheduled in cron, runs in seconds
```

## Ecosystem: Plays Well With Others

`pflow` doesn't replace your favorite tools—it orchestrates them.

### 🔌 MCP Integration

Access any MCP-compatible tool as a native `pflow` node.

```bash
pflow registry add-mcp github slack stripe
```

### 🤖 Works with `llm`

Use Simon Willison's `llm` CLI as a node:

```bash
pflow fetch-data >> llm "analyze trends in this data" >> create-report
```

### 🚀 A Supercharger for Claude Code & other Agents

An agent can use `pflow` to build reliable tools, drastically reducing errors and making its own work reusable. `pflow` provides the stable, structured "API" that free-running agents need.

## Community

* **Discord**: [Join our community](https://discord.gg/pflow)
* **Examples**: [pflow-examples](https://github.com/pflow/examples)
* **Nodes**: [pflow-registry](https://github.com/pflow/registry)

## Contributing

We are actively building the future of developer automation. Come help\!

```bash
git clone https://github.com/pflow/pflow
cd pflow
pip install -e ".[dev]"
pytest
```

See our [CONTRIBUTING.md](https://www.google.com/search?q=CONTRIBUTING.md) for guidelines.

## Learn More

- **Quick Start Guide**: [docs/quickstart.md](docs/quickstart.md)
- **Creating Nodes**: [docs/nodes.md](docs/nodes.md)
- **Example Workflows**: [examples/](examples/)

---

**pflow** is open source (MIT licensed) and built on the simple idea that AI should help you create tools, not be the tool you run every time.

*Don't just run prompts. Build permanent tools* and transform your expensive AI workflows into instant CLI commands. [Get started now](#quick-start).
