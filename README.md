# pflow

**Turn expensive AI workflows into instant CLI commands.** 

What takes Claude Code 5 minutes and $2 to run, pflow runs in 2 seconds for free.

```bash
# First time: AI plans your workflow (30 seconds)
$ pflow "analyze customer churn from stripe and hubspot"
✨ Generated flow saved as 'analyze-churn'

# Every time after: Instant execution (2 seconds)
$ pflow analyze-churn
✅ Analyzing customer churn... done!
```

## What is pflow?

pflow is a **workflow compiler for AI agents**. It takes complex, multi-step automations that AI agents can do slowly and expensively, and transforms them into fast, deterministic CLI commands you can run instantly.

Think of it as "Claude Code, but 100x faster and infinitely reusable."

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

## Why pflow?

### ⚡ 100x Faster than AI Agents
- **Claude Code**: 5 minutes per run → **pflow**: 2 seconds after first run
- **ChatGPT plugins**: $2 per complex workflow → **pflow**: Free after first run

### 🔒 Deterministic and Shareable
- Same input = same output, every time
- Share workflows with your team: `pflow install teammate/standup-prep`
- Version control your automations

### 🧩 Composable Building Blocks
- Integrate any tool via MCP (Model Context Protocol)
- Chain with Unix pipes
- Combine with existing CLIs like `llm`, `jq`, `grep`

### 🎯 Perfect for Daily Developer Tasks
- Morning standup prep
- Production debugging  
- Cross-system analysis
- API integration workflows
- Report generation

## How It Works

1. **Describe** your workflow in natural language
2. **pflow generates** a reusable pipeline (one-time AI cost)
3. **Run instantly** forever (no AI needed)

```mermaid
graph LR
    A[Natural Language] -->|First Run| B[AI Plans Flow]
    B --> C[Saved Pipeline]
    C -->|Every Run After| D[Instant Execution]
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
pflow "check my PRs, check team's PRs, summarize slack since yesterday, format for standup"
# Runs in 3 seconds, saves 15 minutes daily
```

### Production Debugging
```bash
pflow "fetch datadog errors, correlate with recent deploys, check related PRs"
# Complex investigation in seconds
```

### Customer Analysis
```bash
pflow "get stripe failed payments, match with hubspot contacts, draft outreach emails"
# Multi-system workflow without writing code
```

### Report Generation
```bash
pflow "analyze last week's API usage, calculate costs, compare to budget, create report"
# Scheduled in cron, runs in seconds
```

## Ecosystem

### 🔌 MCP Integration
Access any MCP-compatible tool:
```bash
pflow registry add-mcp github slack stripe
```

### 🤖 Works with `llm`
Use Simon Willison's `llm` CLI as a node:
```bash
pflow fetch-data >> llm "analyze trends" >> create-report
```

### 🚀 Claude Code Compatible
pflow can execute any workflow Claude Code can, but:
- 100x faster after first run
- Deterministic results
- No repeated API costs

## Community

- **Discord**: [Join our community](https://discord.gg/pflow)
- **Examples**: [pflow-examples](https://github.com/pflow/examples)
- **Nodes**: [pflow-registry](https://github.com/pflow/registry)

## Contributing

We'd love your help making pflow better!

```bash
# Clone the repo
git clone https://github.com/pflow/pflow
cd pflow

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Learn More

- **Quick Start Guide**: [docs/quickstart.md](docs/quickstart.md)
- **Creating Nodes**: [docs/nodes.md](docs/nodes.md)
- **Example Workflows**: [examples/](examples/)

---

**pflow** is open source (MIT licensed) and built on the simple idea that AI should help you create tools, not be the tool you run every time.

Transform your expensive AI workflows into instant CLI commands. [Get started now](#quick-start).