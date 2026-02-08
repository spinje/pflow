# Task 77: Distribute Agent Instructions to Nodes (Progressive Disclosure)

## Description

Break up the monolithic agent instructions file (`cli-agent-instructions.md`, ~1900 lines) and distribute node-specific knowledge to the nodes themselves. The instructions file becomes a concise hub that points agents to the right commands, not a comprehensive reference.

## Status
not started

## Priority
high

## The Problem

The current instructions file bundles three things:
1. **Format fundamentals** (~50 lines) — `## Inputs`, `## Steps`, `## Outputs`, headings, YAML params, code blocks
2. **Workflow design knowledge** (~800 lines) — when to use code vs shell vs LLM, step order vs templates, development loop
3. **Node-specific instructions** (~1000 lines) — batch configuration, code node rules (templates in inputs not code blocks, type annotations), MCP testing patterns, template syntax edge cases, LLM prompting patterns

Category 3 should not be in the instructions file. It should live with the nodes and be loaded dynamically when agents need it.

## The Architecture

### 1. Nodes carry their own usage guidance

Each node type provides not just its API interface (params, reads, writes) but also usage guidance — patterns, gotchas, examples, common mistakes. This goes beyond the current docstring.

Examples of what moves to nodes:
- **llm node**: batch configuration options, parallel settings, prompt best practices, when to use LLM vs code
- **code node**: templates go in `inputs` not code block, type annotations required, auto-parsed JSON, result variable pattern
- **shell node**: `$VAR` not `${VAR}` for shell variables, BSD vs GNU compatibility, when to use shell vs code
- **mcp node**: testing protocol, structure discovery process, "JSON string" parameter handling
- **batch (cross-node)**: all batch options, inline array patterns, dynamic indexing, results structure

### 2. `pflow registry discover` includes usage guidance

When an agent discovers nodes for building a workflow, the response includes relevant usage guidance — not just "here's the interface" but "here's how to use it well." The agent gets what it needs at the moment it needs it, not upfront.

### 3. `pflow registry describe` has actionable next steps

After showing the node interface, include actionable commands:
```
To see usage patterns and examples:
  pflow registry guide llm

To test this node:
  pflow registry run llm prompt="test" model=sonnet
```

### 4. `pflow instructions usage` becomes a hub with pointers

The usage instructions provide:
- Format fundamentals (the ~50 lines)
- Core workflow design principles (condensed from ~800 lines)
- Pointers to dig deeper:
  ```
  Learn about specific node types:
    pflow registry guide llm      # LLM calls, batching, prompting
    pflow registry guide code     # Python code nodes, type annotations
    pflow registry guide shell    # Shell commands, variable syntax
    pflow registry guide mcp      # MCP tools, testing protocol
    pflow registry guide batch    # Batch processing across node types
  ```

### 5. `pflow instructions create` becomes lighter

The creation instructions shrink dramatically because node-specific knowledge is loaded on demand. The creation guide covers:
- The development loop (discover → design → build → test → save)
- Step order vs templates (the core concept)
- Workflow limitations (no loops, no conditionals)
- Input declaration principles
- When to build one workflow vs multiple

Node-specific details are loaded when the agent actually discovers and uses those nodes.

## Success Criteria

1. `pflow instructions usage` is under 200 lines (currently embedded in the ~1900 line create file)
2. `pflow instructions create` is under 500 lines (currently ~1900 lines)
3. Node-specific guidance is accessible via `pflow registry describe` or `pflow registry guide`
4. `pflow registry discover` responses include relevant usage guidance
5. Agent can build a workflow using the same node types as before, without loading the full instructions upfront
6. No information is lost — everything currently in the instructions is accessible, just distributed

## Dependencies

- None blocking. Can be done incrementally — move one node type's instructions at a time.

## Implementation Notes

- Consider a `guidance` field in node metadata (alongside the existing docstring interface)
- `pflow registry guide <node>` could be a new subcommand, or guidance could be folded into `pflow registry describe --verbose`
- Batch guidance is cross-cutting (applies to any node type) — may need its own guide entry
- The template system documentation (patterns, edge cases, auto-parsing) might stay in the core instructions since it's not node-specific

## Context

From README session 6 discussion: the claim "no API to learn" is an overstatement while the instructions file is 1900 lines. The format itself is simple (markdown agents already know), but node-specific knowledge creates a learning curve. This task makes "simple to learn" increasingly true by distributing knowledge to where it's needed, when it's needed.

Connects to the "Progressive Disclosure for pflow Instructions" design goal in CORE-INSIGHTS.
