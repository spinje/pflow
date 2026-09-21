# MCP Tools

Tool docstrings and `Annotated`/`Field` descriptions are the public API seen by
agents. Tools delegate business logic to services; the parent guide owns the
async/thread and error-boundary contracts.

## Navigation

- `discovery_tools.py`: workflow/component discovery.
- `execution_tools.py`: execute, validate, plan, save, probe, cached-field reads,
  and cache analysis.
- `registry_tools.py`: node descriptions/listing.
- `workflow_tools.py`: saved workflow listing/descriptions.
- `__init__.py`: imports tool modules to trigger decorator registration.

## Public-schema conventions

- Explain parameter purpose and supported forms through Field descriptions and
  examples; avoid a redundant Args section.
- Document meaningful return variants, including errors and durable gate pauses.
- Use generic example names so examples do not imply a saved workflow/tool exists.
- Discovery tools need the complete user request, not an abbreviated technical query.
- `workflow_execute` can pause at an unapproved gate. Pre-approval represents the
  human's authorization; it is not a workaround for MCP's lack of interactive prompts.

`tests/test_mcp_server/test_tool_registration.py` checks registration/import wiring,
a critical tool-name subset and minimum count, workflow_validate's input schema,
and selected async definitions. Extend the relevant coverage when changing the API;
a passing service test alone does not verify tool exposure.
