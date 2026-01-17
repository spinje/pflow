# pflow System Architecture

> **Version**: Current (MVP feature-complete)
> **Last Updated**: January 2026

## Overview

pflow is a CLI-first workflow execution system built on PocketFlow (a ~200-line Python framework in `pocketflow/__init__.py`). It enables AI agents and users to create, save, and execute workflows defined in JSON configuration files.

### Primary Interfaces

1. **CLI** - Execute workflows via `pflow workflow.json` or `pflow saved-name param=value`
2. **MCP Server** - AI agents can interact via Model Context Protocol (`src/pflow/mcp_server/`)
3. **Natural Language (Legacy)** - Built-in planner for NL to workflow conversion (being phased out)

> **Important:** Users and AI agents ALWAYS interact via these interfaces using JSON workflows. Direct PocketFlow usage (creating `Node` subclasses, `Flow` objects) is reserved for pflow internal development only. See `pflow-pocketflow-integration-guide.md` for internal development patterns.

### Core Principle

**Fight complexity at every step.** Build minimal, purposeful components that extend without rewrites.

## Interface Modes

pflow provides three interface modes for different use cases:

### 1. CLI Primitives (Primary - for AI Agents)

AI agents interact with pflow through CLI commands that expose internal capabilities as primitives:

**Discovery:**
- `pflow workflow discover "description"` - LLM-powered workflow search
- `pflow registry discover "capability"` - LLM-powered node search
- `pflow registry list <keywords>` - Filter available nodes
- `pflow registry describe <node>` - Get detailed node interface

**Execution:**
- `pflow registry run <node> params` - Execute single node
- `pflow workflow.json params` - Run workflow file
- `pflow saved-name params` - Run saved workflow
- `pflow read-fields exec-id path` - Inspect execution data

**Building:**
- `pflow instructions create --part 1/2/3` - Get workflow creation guide
- `pflow --validate-only workflow.json` - Validate without running
- `pflow workflow save ./file.json --name name` - Save to library

Agents write JSON workflows directly using these primitives. For the complete agent guide, run `pflow instructions usage`.

### 2. Natural Language (Legacy - for Human Users)

The built-in planner converts natural language to workflows:
```bash
pflow "create a summary of this file"
```

> **Status:** Legacy. Being phased out in favor of agent-direct JSON creation. Remains available for human users who prefer natural language input.

### 3. MCP Server (Experimental)

pflow can run as an MCP server for programmatic access:
```bash
pflow mcp serve  # Start stdio server
```

> **Status:** Experimental. Instructions not actively maintained. Prefer CLI primitives for agent integration.

## Execution Pipeline

```
CLI Entry (main_wrapper.py)
    │
    ├── Routes to: mcp / registry / workflow / settings / run
    │
    ▼
Workflow Resolution
    │
    ├── File path: Load JSON directly
    ├── Saved name: Look up in ~/.pflow/workflows/
    └── Natural language: Legacy planner generates workflow
    │
    ▼
Validation Pipeline (5 layers)
    │
    ├── 1. Structural: Required fields, valid node types
    ├── 2. Data Flow: Template dependencies resolved
    ├── 3. Template: ${var} syntax valid
    ├── 4. Node Type: Nodes exist in registry
    └── 5. Output: Declared outputs available
    │
    ▼
Compilation (runtime/compiler.py)
    │
    ├── IR → PocketFlow Flow object
    ├── Wrapper chain applied per node
    └── Shared store initialized
    │
    ▼
Execution (runtime/workflow_executor.py)
    │
    ├── Nodes execute: prep() → exec() → post()
    ├── Data flows through namespaced shared store
    └── Metrics/tracing captured
    │
    ▼
Output
    │
    ├── Declared outputs extracted
    └── Trace saved to ~/.pflow/debug/
```

## Key Abstractions

### Shared Store Pattern

The shared store is a simple dictionary that enables inter-node communication:

```python
# Two-level structure
shared = {
    "__execution__": {...},      # Reserved: execution metadata
    "__llm_calls__": [...],      # Reserved: LLM call tracking
    "node_id": {                 # Namespaced per node
        "output_key": value
    },
    "global_key": value          # Root level for workflow inputs
}
```

**Resolution Priority:**
1. Initial parameters (CLI args, workflow inputs)
2. Shared store (node outputs)
3. Workflow defaults

### Wrapper Chain

Each node is wrapped for instrumentation and namespacing:

```
InstrumentedWrapper (metrics, cache, trace)
    │
    ▼
NamespacedWrapper (collision prevention)
    │
    ▼
TemplateAwareWrapper (${var} resolution)
    │
    ▼
ActualNode (prep → exec → post)
```

> **Implementation details:** See `src/pflow/runtime/CLAUDE.md` for wrapper application order, set_params flow, and _run() interception chain.

### Template System

Templates use `${variable}` syntax:

```json
{
  "params": {
    "prompt": "Summarize: ${input_data}"
  }
}
```

**Features:**
- Nested access: `${node.field}`, `${data[0].name}`
- Type preservation for simple templates
- Auto JSON parsing for nested access
- Strict mode (error) vs permissive (warning)

## Node System

### Core Node Types

| Type | Module | Description |
|------|--------|-------------|
| `shell` | `nodes/shell/` | Execute shell commands |
| `http` | `nodes/http/` | HTTP requests |
| `llm` | `nodes/llm/` | LLM API calls (via `llm` library) |
| `read-file` | `nodes/file/` | Read file contents |
| `write-file` | `nodes/file/` | Write file contents |
| `claude-code` | `nodes/claude/` | Claude Code CLI integration |
| `mcp` | `nodes/mcp/` | Execute MCP tools |

> **Critical:** See `src/pflow/nodes/CLAUDE.md` for the mandatory retry pattern. Nodes that catch exceptions in exec() break automatic retries.

### Node Naming

pflow uses **simple node names** without namespaces or versions:

```
llm
shell
read-file
write-file
http
claude-code
mcp-<server>-<tool>
```

Run `pflow registry list` to see all available nodes.

**Platform Nodes** follow `platform-action` pattern:

| Platform | Examples |
|----------|----------|
| **File** | `read-file`, `write-file`, `copy-file`, `delete-file`, `move-file` |
| **MCP** | `mcp-filesystem-read_file`, `mcp-github-list_issues` (dynamically loaded) |

**General Nodes** use single-purpose names:

| Node | Purpose |
|------|---------|
| `llm` | General text processing |
| `shell` | Execute shell commands |
| `http` | HTTP requests |
| `claude-code` | Claude Code CLI for complex tasks |

**Naming Benefits**:
- **Predictable**: Users can guess node names
- **Discoverable**: `pflow registry search file` finds all file nodes
- **Composable**: Clear single-purpose functions

> **Future**: Namespace and version support (`core/llm@1.0.0`) planned for v2.0. See [Registry Versioning](./future-version/registry-versioning.md).

### Node Interface Format

Nodes declare their interface via docstrings:

```python
class MyNode(Node):
    """Description of what this node does.

    Params:
        param_name (type): Description

    Reads:
        key_name: Description of input

    Writes:
        output_key: Description of output

    Actions:
        default: Normal completion
        error: When something fails
    """
```

### Registry System

The registry (`src/pflow/registry/`) discovers and catalogs nodes:

```bash
pflow registry list              # List all nodes
pflow registry search "http"     # Search nodes
pflow registry describe shell    # Show node details
pflow registry run shell cmd="echo hello"  # Test a node
```

## MCP Integration (Fully Implemented)

pflow has complete MCP support in two directions:

### 1. MCP Client (MCPNode)

Workflows can call external MCP tools:

```json
{
  "type": "mcp",
  "params": {
    "server": "filesystem",
    "tool": "read_file",
    "arguments": {"path": "${file_path}"}
  }
}
```

**Supported Transports:**
- `stdio` - Local process communication
- `http` - Remote HTTP with authentication

### 2. MCP Server (pflow-as-server)

AI agents can use pflow via MCP (`src/pflow/mcp_server/`):

**Available Tools (11 production tools):**
- `workflow_discover` - LLM-powered workflow search
- `workflow_execute` - Execute a workflow
- `workflow_validate` - Validate workflow structure
- `workflow_save` - Save a workflow
- `workflow_list` - List saved workflows
- `workflow_describe` - Get workflow details
- `registry_discover` - LLM-powered node search
- `registry_list` - List available nodes
- `registry_describe` - Get node details
- `registry_search` - Search nodes by pattern
- `registry_run` - Execute a single node

> **Implementation details:** See `src/pflow/mcp_server/CLAUDE.md` for the 3-layer architecture (async tools → sync services → core pflow).

## Self-Healing Workflows (Runtime Feature)

pflow can detect and repair certain workflow errors at runtime:

1. **Checkpoint data** stored in `shared["__execution__"]`
2. **Error categorization** (repairable vs non-repairable)
3. **LLM-assisted repair** using Claude
4. **Resume from checkpoint** (skip completed nodes)

> **Note:** This is a runtime feature for handling execution failures. AI agents building workflows should use `pflow --validate-only` for pre-execution validation and iterate on JSON directly rather than relying on auto-repair.

> **Implementation details:** See `src/pflow/execution/CLAUDE.md` for checkpoint structure, error categories, and repair loop implementation.

## CLI Interface

### Running Workflows

```bash
# Run from file
pflow workflow.json

# Run saved workflow with parameters
pflow my-workflow param1=value1 param2=value2

# Run with stdin
cat data.txt | pflow my-workflow
```

### Managing Workflows

```bash
# Save a workflow
pflow workflow save ./workflow.json --name my-workflow

# List saved workflows
pflow workflow list

# Describe a saved workflow
pflow workflow describe my-workflow
```

### Settings Management

```bash
# Show current settings
pflow settings show

# Allow/deny specific nodes
pflow settings allow shell
pflow settings deny http
```

## Configuration

### Workflow JSON Format

```json
{
  "name": "example-workflow",
  "description": "What this workflow does",
  "inputs": {
    "input_name": {
      "type": "string",
      "description": "Description",
      "required": true
    }
  },
  "outputs": {
    "output_name": {
      "type": "string",
      "source": "node_id.key"
    }
  },
  "nodes": [
    {
      "id": "unique_id",
      "type": "node_type",
      "params": {...}
    }
  ]
}
```

### Storage Locations

```
~/.pflow/
├── workflows/          # Saved workflows
├── settings.json       # User settings (allow/deny lists)
├── debug/              # Execution traces
└── mcp/                # MCP server configurations
```

## Design Decisions

### Why PocketFlow?

- Minimal (~150 lines) with clear semantics
- Node lifecycle (prep/exec/post) separates concerns
- Flow orchestration with `>>` operator
- Shared store pattern for communication

### Why JSON Workflows?

- Machine-readable and validatable
- AI agents can generate them
- Version-controllable
- Portable across systems

### Why Namespaced Shared Store?

- Prevents node output collisions
- Clear data provenance
- Debugging visibility
- Supports complex workflows

## Related Documents

- **PocketFlow**: `pocketflow/CLAUDE.md` - Framework documentation
- **Integration Guide**: `architecture/pflow-pocketflow-integration-guide.md`
- **Runtime Components**: `architecture/runtime-components.md`
- **Node Reference**: `architecture/reference/node-reference.md`
