# MCP Server

Exposes pflow as MCP tools: async tool wrappers → synchronous request-scoped
services → core execution/registry/workflow code. External MCP client integration
belongs to `../mcp/`.

## Directory map

```text
mcp_server/
├── main.py                       # Startup
├── server.py                     # Registration and exception boundary
├── tools/                        # Tool schemas and wrappers
├── services/                     # Request-scoped adapters
├── utils/                        # Boundary checks and compatibility shims
└── resources/
    ├── instruction_resources.py  # Resource loader
    └── instructions/             # Shipped instruction Markdown
```

## Navigation

| Concern | Owner |
|---|---|
| Startup, settings environment, stdio | `main.py:run_server` |
| Public server instructions and registration | `server.py:register_tools`; `tools/__init__.py` |
| Tool/resource exception boundary | `server.py:PflowMCP`, `_should_render` |
| Public tool schemas/docstrings | `tools/CLAUDE.md` |
| Runner adapters and shared formatting | `services/CLAUDE.md` |
| MCP parameter checks and compatibility exports | `utils/CLAUDE.md` |
| Instruction resources | `resources/instruction_resources.py:_get_instructions_path` |

## Boundaries to preserve

- **stdout carries only MCP protocol messages.** Log to stderr.
- `main.py` injects settings environment before LLM operations. FastMCP owns its
  event loop: call `mcp.run("stdio")`, never wrap it in `asyncio.run()`.
- Tools offload synchronous services with `asyncio.to_thread`; blocking core work
  must not run directly on the protocol loop.
- Services construct mutable dependencies per request. `ensure_stateless` only
  logs calls; it does not enforce isolation.
- Registration happens through import-time decorators. `register_tools` imports
  tool/resource modules; adding a service alone does not expose a tool.
- Reuse `execution/formatters/` for shared CLI/MCP semantics. Keep cycle-sensitive
  formatter imports local to service methods; formatters return values, not prints.
  Surface-specific presentation can differ—parity does not mean identical envelopes.

## Error and execution behavior

Services let exceptions reach `PflowMCP`. `_should_render` distinguishes
self-describing exceptions/producer bugs from legacy pre-rendered bare exceptions
that pass through. Tool and resource error protocols differ; do not assume every
failure becomes the same CallToolResult shape. Change the server boundary rather
than adding independent catch/render policies to tools.

`services/execution_service.py` delegates execution, validation, and planning to
`WorkflowRunner`. Workflow execution streams a trace, needed for durable gate
pause/resume; single-node registry probes remain traceless. Only a durable pause
may advertise a resume token. MCP cannot prompt a human: unapproved gates pause,
and pre-approval must reflect the human's authorization.

## Instruction resources

Public resources are `pflow://instructions` and `pflow://instructions/sandbox`.
Their content owns agent workflow-building advice; do not duplicate it here.
`_get_instructions_path` checks shipped package content before home and development
fallbacks. A home file does not override a resource present in the package.

Tests live in `tests/test_mcp_server/`; registration tests cover the public wiring,
while service tests exercise behavior behind it.
