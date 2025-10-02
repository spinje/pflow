# MCP Server Architecture

*This document defines the architectural design for pflow's MCP server implementation*

## The Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User Interfaces                       │
├──────────────────────┬───────────────────────────────────┤
│      CLI            │         MCP Server                 │
│  (click commands)   │     (MCP protocol)                 │
│                     │                                     │
│  pflow execute      │   browse_components()              │
│  pflow plan         │   list_library()                   │
│  pflow list         │   describe_workflow()              │
│                     │   execute()                        │
│                     │   save_to_library()                │
├──────────────────────┴───────────────────────────────────┤
│                   pflow Core Libraries                   │
│                                                          │
│  WorkflowManager    Registry         Compiler            │
│  WorkflowExecution  Validator        TemplateResolver    │
│  MetricsCollector   Settings         FileSystem          │
└──────────────────────────────────────────────────────────┘
```

## Core Architectural Decision: MCP Server as Peer to CLI

The MCP Server is **NOT**:
- A wrapper around CLI (no subprocess calls)
- Part of CLI (not embedded)
- A replacement for CLI

The MCP Server **IS**:
- A peer consumer of core libraries
- A separate interface layer for AI agents
- Stateless between requests

### Separation of Concerns

| Component | Responsibility | Used By |
|-----------|---------------|---------|
| **CLI** | Terminal UI, click commands, progress bars | Human users |
| **MCP Server** | MCP protocol, tool schemas, JSON responses | AI agents |
| **Core Libraries** | Business logic, execution, validation | Both CLI and MCP |

## File System Integration

Both CLI and MCP Server share the same file system:

```
~/.pflow/
├── workflows/           # Both CLI and MCP read/write here
│   ├── pr-analyzer.json        # Library workflow
│   ├── stripe-sync.json        # Library workflow
│   └── test-draft.json         # Agent draft file
├── registry.json        # Shared node registry
├── settings.json        # Shared configuration
└── metrics/            # Shared execution metrics
```

**Critical Pattern**: Agents create draft workflows directly via file editing, then execute them through MCP tools.

## Deployment Strategy

### Phase 1: MVP (Task 71)
```bash
pflow serve mcp  # Stdio-based MCP server
```

Implementation in `src/pflow/cli/commands/serve.py`:
```python
@click.group()
def serve():
    """Run pflow as a server."""
    pass

@serve.command()
def mcp():
    """Run as MCP server (stdio transport)."""
    from pflow.mcp_server import PflowMCPServer
    server = PflowMCPServer()
    asyncio.run(server.run())
```

### Phase 2: Future Enhancements
- HTTP transport support
- Authentication layer
- Multi-tenant isolation

## Output Interface Strategy

Leverage existing OutputInterface abstraction:

```python
# CLI uses
from pflow.execution.cli_output import CliOutput
output = CliOutput()  # Terminal display

# MCP Server uses
from pflow.execution.null_output import NullOutput
output = NullOutput()  # Silent execution
```

Future option: Create `MCPOutput` to capture structured progress events.

## Integration with Core Libraries

### Direct Library Usage
```python
from pflow.execution.workflow_execution import execute_workflow
from pflow.core.workflow_manager import WorkflowManager
from pflow.registry.registry import Registry

# No CLI dependencies, direct core library usage
```

### Stateless Pattern (CRITICAL)
```python
async def handle_tool_request(params):
    # Fresh instances per request
    manager = WorkflowManager()
    registry = Registry()

    # Use and discard
    result = process_with_instances(manager, registry, params)
    return result
```

## Testing Strategy

### Unit Tests
- Mock core libraries
- Verify correct API calls
- Test error formatting

### Integration Tests
- Use real core libraries
- Test full execution flow
- Verify checkpoint data

### Claude Code Validation
- Natural tool discovery
- Complete workflow cycle
- Error recovery flow

## Advantages of This Architecture

1. **No subprocess overhead** - Direct Python function calls
2. **Structured data flow** - No text parsing needed
3. **Full checkpoint access** - Direct access to shared store
4. **Code reuse** - All core logic shared with CLI
5. **Independent evolution** - CLI and MCP can change separately
6. **Clean boundaries** - Clear separation at library interfaces
7. **Shared persistence** - Same workflows accessible from both interfaces

## Migration Path

**Current (Task 71)**: Standalone MCP server process
**Future**: Deeper integration, multiple transports, enterprise features

The architecture is designed to evolve without breaking changes to the core separation.

---

*This architecture leverages pflow's existing clean separation between CLI and core libraries, requiring only the addition of an MCP protocol layer.*