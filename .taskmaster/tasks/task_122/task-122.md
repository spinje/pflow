# Task 122: OpenClaw Integration Research

## Description

Research and design integration between pflow and OpenClaw. Explore whether pflow can serve as a workflow authoring layer that agents create on-the-fly, potentially replacing or complementing Lobster's pre-defined pipeline model.

## Status

not started

## Priority

medium

## Problem

OpenClaw uses Lobster for workflow automation — a YAML-based pipeline format where steps are shell commands with approval gates. Key characteristics:

- **Workflows are pre-defined by humans**, agents invoke them
- **Steps are shell commands** (`command: inbox list --json`), not typed nodes
- **Approval gates** halt execution until human confirms (with resume tokens)
- **Token efficiency** — one Lobster tool call vs. many individual tool calls

The limitation: agents can't author Lobster workflows on-the-fly. They invoke existing pipelines but can't create new ones for novel tasks.

pflow has the inverse properties:

- **Agents author workflows** dynamically
- **Typed nodes** with known interfaces (HTTP, LLM, Shell, MCP, etc.)
- **Validation before execution**
- **No approval gates** — workflows run to completion

The question: can pflow serve as the "agent-authored workflow" layer for OpenClaw?

## Research Findings

### Lobster's Design (from OpenClaw docs)

> "Clawdbot = the brain (understands what you want); Lobster = the hands (executes workflows safely)"

Lobster solves:
1. Token efficiency through consolidated tool calls
2. Hard safety gates (approval checkpoints that actually halt, not just prompts)
3. Statefulness (resume tokens for paused workflows)
4. Shareability (versionable workflow files)

### Approval Gate Implementation Options

**Option A: Blocking MCP call** (simple but fragile)
```markdown
### approve-emails
- type: mcp
- server: openclaw
- tool: request_approval
- message: "Send ${draft.count} emails?"
```
The MCP tool blocks until human responds. Problem: process waiting hours/days is wasteful and fragile (crashes, restarts lose state).

**Option B: Checkpoint + Resume** (robust, what Lobster does)
```markdown
### approve-emails
- type: approval
- message: "Send ${draft.count} emails?"
- notify: openclaw
```
Workflow serializes state, exits with "pending_approval" status + resume token. Human approves via OpenClaw UI. `pflow resume <token>` continues from checkpoint.

Option B is the right approach but requires new pflow infrastructure:
- Execution state serialization
- Checkpoint storage (`~/.pflow/pending/{token}.json`)
- Resume mechanism (`pflow resume <token>` or MCP tool)
- Notify integration (tell OpenClaw about pending approval)

### The Bigger Picture

This task isn't just about approval gates. It's about whether pflow can be a first-class OpenClaw integration:

1. **pflow as MCP server** — already exists, agents can run workflows
2. **pflow workflows invoked like Lobster** — OpenClaw agent calls `pflow run workflow.pflow.md`
3. **Agent-authored workflows** — unlike Lobster, agents create workflows dynamically
4. **Human-in-the-loop** — approval gates with checkpoint/resume
5. **Shared state with OpenClaw** — access to OpenClaw's MCP tools, context, etc.

## Open Questions

1. **Does OpenClaw want this?** — Need to understand OpenClaw's roadmap and whether they see value in agent-authored workflows.

2. **Replace or complement Lobster?** — pflow could be an alternative (for agent-authored) while Lobster remains (for human-defined). Or pflow could fully replace Lobster if it gains approval gates.

3. **How do agents discover available MCP tools?** — To author workflows, agents need to know what tools exist in the OpenClaw environment.

4. **Authentication/permissions** — How does pflow running in OpenClaw context inherit permissions for MCP tools?

5. **The minimal Python framework** — During research, we explored a ~400-line Python framework with t-string wiring (Python 3.14+). Would this be better suited for agent authoring than pflow's markdown format? This needs separate evaluation.

## Dependencies

- Task 107: Markdown Workflow Format — pflow needs a stable authoring format
- Task 98: Require investigation if relevant to this task
- Understanding of OpenClaw's MCP server architecture
- Clarity on OpenClaw team's interest

## Next Steps

1. Reach out to OpenClaw team to understand their roadmap
2. Evaluate whether pflow's MCP server mode already provides what's needed
3. Design approval gate / checkpoint-resume system if there's interest
4. Consider whether this justifies a separate "miniflow" project vs. extending pflow

## Related Research

During this exploration, we also discussed:

- **PocketFlow's design** — pflow is built on ~200-line PocketFlow framework; template wiring was added on top
- **A minimal Python framework** — ~400 lines with t-string wiring (PEP 750, Python 3.14+), pre-built nodes, PocketFlow's action routing. More natural for agents writing Python than markdown documents.
- **Eager vs. deferred execution** — t-strings enable deferred string interpolation that looks like f-strings

These are tangential but may inform whether pflow or a new minimal framework is the right integration point for OpenClaw.

## References

- [Lobster - OpenClaw docs](https://docs.openclaw.ai/tools/lobster)
- [GitHub - openclaw/lobster](https://github.com/openclaw/lobster)
- [PEP 750 – Template Strings](https://peps.python.org/pep-0750/)
