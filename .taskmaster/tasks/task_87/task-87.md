# Task 87: Implement Sandboxed Execution Runtime

## Status
not started

## Scope

Implement container-level sandboxing for command/code execution nodes:
- **ClaudeCodeNode** - Enable SDK's built-in sandbox (trivial)
- **ShellNode** - bubblewrap (Linux) / sandbox-exec (macOS)
- **CodeNode** (Task 104) - Optional sandboxed mode using same infrastructure

## Key Insight

Code node sandboxing is the SAME problem as shell node sandboxing:
- Container sandbox = serialize inputs → run command → serialize outputs
- Shell: `bash -c "..."`
- Script: `python -c "..."` or `node -e "..."`

Code node's native objects only work in **unsandboxed** mode. Sandboxed mode loses this (acceptable tradeoff for security).

## Sandbox Approach by Node Type

| Node | Approach | Why |
|------|----------|-----|
| ClaudeCodeNode | SDK built-in | Trivial, Anthropic maintains |
| ShellNode | bubblewrap/sandbox-exec | Needs host tools (git, ssh) |
| CodeNode | Docker/container | Just needs interpreter + deps |

Note: "Docker is wrong for shell" (needs host tools) but Docker may be fine for code node (self-contained).

## References

- https://github.com/anthropic-experimental/sandbox-runtime - Anthropic's sandbox-runtime (TS only)
- https://github.com/daytonaio/daytona - Daytona dev environments
- See `research/` folder for detailed implementation research

## Open Questions

- Does this deprecate Task 63 (risk assessment)? Probably not - they're complementary (warn vs prevent)
- When is sandbox mandatory vs optional? (local use vs MCP server context)
- How do code node `requires` deps get installed in sandboxed container?