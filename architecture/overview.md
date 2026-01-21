# pflow Overview

> **Purpose:** Conceptual foundation for understanding pflow. For implementation details, see `architecture.md`.

## What pflow Is

pflow is a CLI-first workflow execution system that enables AI agents to create, save, and execute workflows defined in JSON. Built on PocketFlow (~200 lines of Python), it provides the infrastructure for workflows to persist, be discovered, reused, and composed.

**The core value proposition:**
> "Your agent solves the same problem from scratch. Full cost. Same latency. Same risk of failure. Every time. pflow turns that reasoning into workflows your agent can reuse. Plan once, run forever."

**Who uses pflow:**
- **Primary:** AI agents (Claude Code, Cursor, etc.) use pflow as infrastructure via CLI commands or MCP server
- **Secondary:** Humans can inspect, modify, and run workflows directly

Both use the same interface. This isn't a coincidence - designing for agents (who need simplicity and clarity) produces interfaces that work well for humans too.

---

## The Problem

### Using vs. Creating

Consider Anthropic's skills system. Skills are structured - they have names, descriptions, progressive disclosure. Using a skill that exists is relatively easy: the agent finds it, reads the instructions, runs it.

**Creating a new skill is the hard problem.**

When you need something new, you build from scratch. That means:
- Figuring out how to call different LLMs (each has different APIs, auth, response formats)
- Figuring out how to call MCP servers programmatically
- Handling errors, retries, edge cases
- Batching and parallelization
- Getting all of this right on the first try (because iteration is expensive for agents)

Each piece you reinvent is a potential failure point. And skills are isolated - you can't easily compose Skill A + Skill B into Skill C. There's no code sharing between them.

This is the creation problem: building new workflows is painful without reliable building blocks.

### The Architectural Root Cause

All major AI coding tools use tool-by-tool orchestration:

```
Agent → tool → Agent → tool → Agent → tool
         ↑         ↑         ↑
      LLM call  LLM call  LLM call
```

The LLM reasons between every step. Every intermediate result consumes context. This is costly (tokens), slow (round-trips), and fragile (context loss).

Claude Code, Cursor, Aider, Cline, Windsurf - they all do this.

### Three Approaches to Orchestration

| Approach | How it works | Who does it | Workflow lifecycle |
|----------|--------------|-------------|-------------------|
| **Tool-by-tool** | LLM reasons between every step | All major coding assistants | None |
| **Ephemeral execution** | Code runs deterministically, then discarded | Anthropic PTC, Cloudflare Code Mode | None - "throw it away" |
| **Workflow lifecycle** | Persist, search, reuse, compose, iterate | **Doesn't exist anywhere** | Full |

Cloud solutions (Anthropic, Cloudflare) solved execution efficiency - code runs without LLM in the loop. But the code is ephemeral. It runs once, then it's gone.

**Workflow lifecycle doesn't exist anywhere - not in cloud, not locally.** This is the gap pflow fills.

### Friction, Not Capability

Agents CAN solve most errors. The real issue:
- How much TIME does it take?
- How many USER DECISIONS are required?
- Can non-developers make those decisions?

pflow doesn't enable something impossible. It reduces friction on something possible but painful.

### Why Lifecycle Matters for Creation

The lifecycle (persist, discover, compose) matters because of creation:

1. You create something using reliable building blocks (nodes)
2. It persists and becomes discoverable
3. Next time you need something similar: find it OR compose from existing pieces
4. The library grows - each creation becomes a building block for future work

Building blocks exist at two levels:
- **Nodes:** Atomic operations (LLM call, HTTP request, shell command)
- **Workflows:** Compositions that become reusable themselves

A workflow you create today can be a building block tomorrow - called from other workflows or discovered when a similar need arises.

Without lifecycle, every creation is isolated. With lifecycle, creation compounds.

---

## pflow's Approach

### Core Bets

**1. Compile the Orchestration, Not the Outputs**

When you save a workflow, you're not making outputs deterministic. LLM nodes can still produce varying responses. You're making the PROCESS explicit and repeatable - same workflow path, same node sequence, same data flow.

**2. Structure > Flexibility**

> "Structure enforced by schema is different from conventions enforced by instructions."

- **Soft enforcement:** Reuse depends on an agent reading docs and inferring correctly
- **Hard enforcement:** Reuse is structural, schema-validated, doesn't depend on inference

pflow uses hard enforcement. Workflows are JSON with declared inputs, outputs, and node interfaces. This enables validation before execution, composition that scales, and discovery that works.

**3. Deterministic by Default, Intelligent by Choice**

95% of workflow steps don't need reasoning:
- **Deterministic nodes:** MCP, HTTP, Shell (0 tokens during execution)
- **Intelligence nodes:** LLM, Claude-Code (used only when reasoning adds value)

The orchestrating AI sees schemas and types, not actual data. Data stays in runtime, never enters the AI's context. This provides 5-100x token efficiency and keeps sensitive data out of AI context.

### What pflow Gives Up

Honest tradeoffs:
- **Flexibility:** Some tasks genuinely need arbitrary computation
- **Self-improvement in production:** Code execution systems can self-correct; pflow workflows are immutable once saved
- **Industry momentum:** Anthropic, Cloudflare, Docker are converging on code execution; pflow bets against this consensus

### The Gap Is Deliberate

The industry chose safety and observability over efficiency. Every tool call returns to the model so it can reason, observe, and recover from errors. This is a design choice, not an oversight.

pflow chooses different tradeoffs - for users who value efficiency and reusability over maximum flexibility.

---

## Architecture Concepts

### Three-Layer Model

```
AGENT (orchestrator)
  - Understands user intent
  - Discovers/selects workflows
  - Extracts parameters
  - Falls back when needed
       ↓
WORKFLOWS (compiled subroutines)
  - Execute proven process
  - Handle expected errors
  - Fast and cheap
       ↓
TOOLS (atomic operations)
  - MCP servers, HTTP APIs, shell commands
  - Single operations
```

The agent handles the "what" (intent, selection). The workflow handles the "how" (process, execution). Tools are the building blocks.

### Workflows, Nodes, Shared Store

**Workflows** are JSON files defining a sequence of nodes with inputs, outputs, and data flow.

**Nodes** are atomic operations: read a file, make an HTTP request, call an LLM, execute a shell command. Each node has declared inputs (params) and outputs (writes to shared store).

**Shared store** is the in-memory dictionary that nodes use to communicate. Node A writes its output to the store; Node B reads it via template variables (`${node_a.result}`).

### Where pflow Sits

```
Instructions layer (skills, /commands, reusable prompts)
    ↓ references
Workflows = execution chains (what pflow builds)
    ↓ composed of
Tools = single capabilities (MCP, LLM, shell, HTTP)
```

- pflow operates BENEATH the instructions layer
- Skills, /commands, and similar constructs can already reference anything (CLI commands, MCP tools, code)
- pflow doesn't depend on these evolving
- **pflow provides execution capabilities (composite tools), not instructions**

Skills and workflows are conceptually different. A skill is know-how—like a human skill, it's about knowing how to approach a problem. A workflow is an execution chain—operations that run. A complex skill means sophisticated instructions; a complex workflow means many chained operations. They vary on different dimensions.

pflow aims to be the complex building blocks embedded in instruction layers, not a replacement for them. A skill might say "run `pflow pr-analysis repo=X`" - the skill provides the instruction, pflow provides the execution capability.

### What pflow Is NOT

| Category | Example | How pflow differs |
|----------|---------|-------------------|
| Visual workflow builder | n8n, Zapier | pflow is CLI-first, designed for AI agents to author |
| Agent framework | LangChain, CrewAI | Those orchestrate LLM calls; pflow compiles them into reusable workflows |
| Code execution sandbox | Anthropic PTC, Cloudflare | Those run ephemeral code; pflow provides workflow lifecycle |

pflow doesn't replace agents - it gives them "hands." Agents still do the reasoning. pflow provides reliable, reusable execution.

---

## Key Design Decisions

### CLI-First

LLMs learned to code from training data containing millions of examples of:
```
Write → Run → See error → Edit → Run again
```

CLI-first aligns with this. File paths as shared state (cheaper than passing content). Unix philosophy (small tools, files as interfaces, composable commands) matches how LLMs naturally work.

MCP is supported for environments without terminal access, but CLI is recommended for iterative work.

### JSON Workflows

- Machine-readable and validatable
- AI agents can generate them
- Version-controllable
- Portable across systems
- Schema-enforced structure

YAML would work. JSON was chosen for stricter parsing and explicit structure.

### Structure-Only Orchestration

When an agent creates a workflow:
- It sees node interfaces (what inputs are needed, what outputs are produced)
- It never sees actual data
- Data flows through the runtime, not through the AI's context

This enables compliance-ready security (sensitive data never enters AI context) and dramatic token efficiency.

### Discovery at Scale

Progressive disclosure (load all metadata into context) breaks at ~30-50 items. Beyond that, even metadata becomes noise.

pflow uses search-based discovery:
- `pflow registry discover "description"` - LLM-powered node search
- `pflow workflow discover "description"` - LLM-powered workflow search

Agents search for what they need rather than loading everything.

### Agent-First Design

The design question isn't "can a human use this?" - it's "can an agent use this correctly on the first try?"

Agents have different constraints than humans:
- **Iteration is expensive** - each retry costs tokens and time
- **No exploration** - can't browse or poke around; need explicit discoverability
- **No visual inspection** - can't "look at" output; need programmatic validation

This means: clear typed interfaces, predictable behavior, good error messages, documentation that fits in context. Designing for these constraints produces interfaces that work well for humans too - simplicity benefits everyone.

---

## Capabilities

### How Agents Use pflow

The typical agent workflow:

1. **Discover workflows** - Does a complete solution already exist?
2. **Reuse or create:**
   - If found → reuse the existing workflow
   - If not → discover building blocks (nodes, sub-workflows) and create a new workflow
3. **Run** - Execute the workflow (validation happens automatically)
4. **Save** - Persist the workflow for future reuse

Saved workflows live in `~/.pflow/workflows/` and can be run by name:
```
pflow my-workflow input_file=data.json
```

The library grows over time. Each workflow created becomes discoverable and reusable.

### Interfaces

pflow has a dual MCP role:

- **CLI:** Primary interface for agents with terminal access
- **MCP Server:** Exposes pflow tools for agents without terminal access
- **MCP Client:** Workflows can call external MCP servers via the `mcp` node

The CLI is recommended for iterative work (building, debugging). The MCP server provides the same capabilities for environments like Claude Desktop where terminal access isn't available.

**Legacy Planner:** Natural language to workflow conversion exists but may be deprecated in favor of agent-driven workflow creation.

### Node Types

| Type | Purpose | Deterministic |
|------|---------|---------------|
| `shell` | Execute shell commands | Yes |
| `http` | HTTP requests | Yes |
| `read-file`, `write-file`, etc. | File operations | Yes |
| `mcp` | Call MCP server tools | Yes |
| `llm` | LLM API calls (via `llm` library) | No |
| `claude-code` | Claude Code CLI for complex tasks | No |

### Key Features

- **Workflow discovery:** Semantic search across saved workflows
- **Registry discovery:** Find nodes by capability description
- **Validation:** 6-layer validation before execution (structural, data flow, template, node type, output source, JSON anti-pattern)
- **Batch processing:** Process multiple items with same operation
- **Template variables:** `${node.output}` syntax for data flow
- **Structure-only mode:** Return schemas without data for token efficiency

---

## Vision & Direction

### The Substrate Vision

> "Success means invisibility. Primitives are infrastructure. pflow is not the destination; it is the substrate."

pflow aims to be invisible infrastructure at the bottom of the agent stack - the execution primitive that enables higher-level systems to work.

### Economic Context

Current state:
- VC subsidies hide true costs ("all you can eat token buffet")
- Users don't track actual consumption

The bet:
- Usage-based pricing will become standard
- Token efficiency will become a competitive advantage
- Deterministic execution (no LLM between steps) will become valuable

Model arbitrage:
- Planning (once): Expensive model reasons through the problem
- Execution (forever): Cheap model or pure deterministic execution

### Near-term Direction

**Workflow authoring optimized for LLMs:**
The current JSON format works but has friction - escaped strings, no inline documentation, cryptic data transformations. The direction is toward an authoring format that treats LLMs as the primary authors: literate workflows where documentation and code live together, lintable code blocks that standard tools can validate, and significant token efficiency gains. The authoring format changes; the execution model stays the same.

**Native data transformation:**
Most shell node usage is actually data transformation (filtering, mapping, formatting). Shell commands with jq one-liners are cryptic and error-prone. The direction is toward native code execution with multiple inputs as objects - readable, lintable, testable.

**Faster iteration loop:**
When workflows fail, agents currently parse large JSON traces to find what went wrong. The direction is toward smart debug output - focused, token-efficient summaries that show only what's relevant, with drill-down commands for details. Fewer round-trips to fix errors.

### Long-term Vision

**Current:** human → agent → pflow

The agent discovers, creates, or runs workflows. pflow provides the execution layer.

**Future:** human → agent → agent → pflow

Agents delegate to agents. The orchestrating agent interprets intent, splits work, recognizes when a task should become a reusable workflow, asks another agent to create it.

pflow doesn't orchestrate this multi-agent coordination - it sits at the bottom, providing fast, reliable execution that keeps the system coherent.

> "Execution speed isn't about cost. It's about coherence."

The faster a task completes, the less time for context to diverge. A 10-minute task creates reconciliation problems. A 2-second task doesn't.

---

## What's Validated vs. What's a Bet

### Validated (research-backed)
- Tool-by-tool orchestration pain is real
- Composition pain is distinct from setup pain ("works alone, breaks together")
- Creating workflows requires starting from scratch - no reusable building blocks
- Each piece reinvented is a failure point
- Market expanding to non-developers (Claude Cowork launched January 2026)

**Important distinction:** Research validated the PAIN, not demand for a specific solution. People describe symptoms ("too expensive", "approval prompts every 2 seconds", "takes 30 minutes instead of 5"), not mechanisms. They're not asking for "workflow lifecycle" - they're experiencing friction that workflow lifecycle might address.

### Bets (hypotheses)
- Workflow lifecycle is the right abstraction for this pain
- People will want this once it exists to try
- Cost pressure will drive demand for deterministic execution
- Non-developers entering market increases reliability requirements (they can't debug failures)
- Building blocks that work on first try are more valuable than maximum flexibility

---

## Related Documents

- **Implementation details:** `architecture.md`
- **Node development:** `pflow-pocketflow-integration-guide.md`
- **Shared store pattern:** `core-concepts/shared-store.md`
- **CLI reference:** Run `pflow --help`
- **Agent instructions:** Run `pflow instructions usage`
