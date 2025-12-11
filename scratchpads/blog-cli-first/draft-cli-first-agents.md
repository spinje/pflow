# Blog Draft: CLI-First Agent Tools

## Working Title
"Why pflow agents use the terminal (and why your agent tools should too)"

## Core Thesis
When building tools for AI agents, CLI-first design isn't a legacy choice—it's the optimal one. It aligns with how LLMs are trained to work and avoids fundamental problems with MCP-only approaches.

---

## The Setup

pflow supports two ways for agents to interact with it:
1. **CLI** - Agent runs terminal commands like `pflow workflow list`
2. **MCP** - Agent calls structured tools via Model Context Protocol

Both provide the same capabilities. But we recommend CLI as the default. Here's why.

---

## How LLMs Learn to Code

Look at any coding tutorial, Stack Overflow answer, or GitHub repo. The pattern is always:

1. Write code to a file
2. Run a command
3. See error output
4. Edit the file
5. Run again

This loop appears millions of times in LLM training data. It's the dominant pattern for how developers work. When an agent uses Cursor, Claude Code, or Windsurf, this is exactly what it does—Write tool, Bash tool, Edit tool, repeat.

LLMs aren't just familiar with this pattern. They're *optimized* for it.

---

## The Fundamental Difference: Path vs Content

Here's what happens when an agent validates a workflow via CLI:

```
Agent: Write workflow to ./workflow.json
Agent: Run `pflow --validate-only ./workflow.json`
pflow: [reads file from disk, validates, returns errors]
Agent: Edit ./workflow.json to fix errors
Agent: Run validation again
```

The agent passes a **file path**. pflow reads the file. The file system is the shared state.

Here's what happens via MCP:

```
Agent: Construct workflow JSON in context
Agent: Call validate_workflow tool with full JSON as parameter
pflow: [validates the JSON it received, returns errors]
Agent: Modify JSON in context
Agent: Call tool again with full JSON
```

The agent passes **file contents**. Every time. There is no shared state—the agent must provide everything on each call.

---

## Why This Matters for Iterative Work

Building a workflow isn't a single action. It's iterative:
- Create initial version
- Validate → errors
- Fix → validate → more errors
- Fix → validate → success
- Save

With CLI, each validation cycle costs ~30 tokens (the file path). With MCP, each cycle costs 500+ tokens (the full JSON). Over 5-10 iterations, that's a significant difference.

But token cost isn't the real problem.

---

## The Mental Model Problem

When an agent works with files, state is grounded:
- The file exists at a known location
- Whatever is in the file IS the current state
- Agent can re-read if uncertain
- Edit tool shows exact diffs

When an agent works with in-context state:
- "Current workflow" exists only in the context window
- Easy to lose track after multiple edits
- No way to verify except reconstructing mentally
- Diffs are implicit, not explicit

This is like asking a developer to write code entirely in a REPL without ever saving. Technically possible, but unnatural and error-prone.

---

## "But What If the Agent Writes to a Temp File?"

You might think: can't an MCP-using agent get the benefits of files by writing to a temp file first?

No. Here's why:

1. **MCP tools take content, not paths.** The agent still has to send the full JSON as a parameter. Writing to a file first just adds work.

2. **Now you have two sources of truth.** The agent wrote version A to the file. Then maybe modified it in-context before sending version B to MCP. Are they the same?

3. **Verification adds overhead.** To confirm the file matches what it sent, the agent has to re-read the file. More tool calls, more tokens, more latency.

4. **You're fighting the paradigm.** MCP is designed for stateless tool calls. Trying to bolt on file-based state defeats the purpose and adds complexity.

CLI doesn't have this problem because the file path IS the reference. There's no separate "content" to keep in sync.

---

## When MCP Makes Sense

MCP isn't wrong—it's just optimized for different cases:

**Use MCP when:**
- The tool has no terminal access (Claude Desktop)
- Operations are one-shot, not iterative (list workflows, describe a node)
- The agent is doing quick queries, not building

**Use CLI when:**
- The tool has terminal access (most coding agents do)
- Work is iterative (building, debugging, refining)
- State benefits from persistence (files survive context limits)

pflow supports both because different tools have different constraints. But when you have the choice, CLI is the better fit for how agents actually work.

---

## The Broader Principle

When building tools for AI agents, consider their training distribution.

LLMs learned to code by watching humans code. Humans use files, terminals, pipes, paths. These patterns are deeply embedded in what LLMs understand.

Novel interaction paradigms (like stateless RPC-style tool calls) can work, but they're swimming against the current. You're asking the LLM to do something it has seen less often and isn't optimized for.

The unix philosophy—small tools, files as interfaces, composable commands—isn't legacy. For AI agents, it's actually the most natural way to work.

---

## Takeaways

1. **CLI-first is agent-friendly.** It matches how LLMs are trained to iterate on code.

2. **File paths beat file contents.** Passing a reference is cheaper and creates shared state.

3. **MCP has its place.** Use it for tools without terminal access or one-shot operations.

4. **Design for the training distribution.** Build on patterns LLMs already understand.

---

## Notes for Final Version

- Add concrete token counts from real workflows (before/after comparison)
- Maybe include a diagram: CLI flow vs MCP flow
- Could reference specific agent behaviors observed in practice
- Consider adding "how to implement CLI-first in your own tools" section
