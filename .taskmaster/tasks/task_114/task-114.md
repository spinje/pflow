# Task 114: Lightweight Custom Node Creation

## Description

Enable users to create reusable custom nodes without the overhead of full MCP servers. Nodes should be discoverable via registry and usable in workflows like built-in nodes.

## Status

not started

## Priority

low

## Problem

MCP is the only way to add custom functionality, but it's heavyweight:
- Requires stdio server implementation
- Separate process per server
- Complex setup for simple code wrappers

Users want to wrap simple Python/TS code and make it reusable across workflows.

## Solution

TBD - See braindump for options explored.

## Dependencies

- Task 104: Python Code Node — Understanding script execution informs this design
- Task 113: TypeScript Code Node — Same pattern for TS

## Open Questions

- What format for defining custom nodes?
- How are they discovered?
- Can code node patterns be "extracted" into nodes?
- Relationship to MCP (coexist? replace for simple cases?)
