# Pedagogical Framing Ideas for Guide Content

Distilled from an early agent postmortem (ideal-workflow.md, pre-CLI-restructure). All specific syntax/commands are outdated — these are **framing concepts** to consider when writing `core.md`.

## 1. Teach the thinking process, not just syntax

Agents struggle most in the "understand the task" phase — decomposing a user request into inputs, transformations, and outputs before touching any pflow commands. `core.md` should include this decomposition step.

## 2. Pattern recognition for common workflow shapes

- Fetch → Transform → Store (the most common)
- Fetch → Decide → Branch
- Iterate → Collect → Aggregate (batch)
- Multi-service coordination (Service A → Transform → Service B → Service C)

Agents that recognize these patterns map user requests to node types faster.

## 3. Node selection decision tree

Compact "Need X? Use Y" format:
- Get data from API → `http` or `mcp`
- Transform text → `llm`
- Transform structured data → `code`
- Run CLI tools → `shell`
- Read/write files → `file`

High-value in `core.md` because it's scannable and sticks in context.
