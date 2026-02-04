# pflow System Architecture

> **Version**: Current (MVP feature-complete)
> **Last Updated**: January 2026

## Overview

pflow is a CLI-first workflow execution system built on PocketFlow (a ~200-line Python framework in `src/pflow/pocketflow/__init__.py`). It enables AI agents and users to create, save, and execute workflows defined in markdown files (`.pflow.md`).

### Primary Interfaces

1. **CLI** - Execute workflows via `pflow workflow.pflow.md` or `pflow saved-name param=value`
2. **MCP Server** - AI agents can interact via Model Context Protocol (`src/pflow/mcp_server/`)
3. **Natural Language (Legacy)** - Built-in planner for NL to workflow conversion (being phased out)

> **Important:** Users and AI agents ALWAYS interact via these interfaces using `.pflow.md` workflows. Direct PocketFlow usage (creating `Node` subclasses, `Flow` objects) is reserved for pflow internal development only. See `pflow-pocketflow-integration-guide.md` for internal development patterns.

### Core Principle

**Fight complexity at every step.** Build minimal, purposeful components that extend without rewrites.

### How It Works (Workflow Authoring)

1. AI agent creates a `.pflow.md` workflow file
2. Runs it with `pflow ./my-workflow.pflow.md param1=value1` while iterating
3. When satisfied, saves with `pflow workflow save ./my-workflow.pflow.md --name my-workflow`
4. `pflow my-workflow` runs the saved workflow by name
5. Workflows are sequences of nodes: `shell`, `http`, `llm`, `file`, and dynamically loaded MCP tools

### Key Principles

- **Shared Store Pattern**: All node communication through shared store
- **Deterministic Structure**: Workflow execution order is fixed; individual node outputs (especially `llm`) may vary
- **Atomic Nodes**: Isolated, focused on business logic only
- **Agent-Friendly CLI**: Primary interface for AI agents to discover, create, and run workflows
- **Observability**: Clear logging and step-by-step traceability

### Technology Stack

**Core Dependencies** (discuss before adding others):
- `Python 3.10+` - Modern Python
- `click` - CLI framework
- `pydantic` - IR/metadata validation
- `llm` - Simon Willison's LLM CLI integration

**Development Tools**:
- `uv` - Fast Python package manager (use `uv pip`, not `pip`)
- `pytest` - Testing framework
- `mypy` - Type checking
- `ruff` - Linting and formatting
- `pre-commit` - Git hooks
- `make` - Development automation

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
- `pflow workflow.pflow.md params` - Run workflow file
- `pflow saved-name params` - Run saved workflow
- `pflow read-fields exec-id path` - Inspect execution data

**Building:**
- `pflow instructions create --part 1/2/3` - Get workflow creation guide
- `pflow --validate-only workflow.pflow.md` - Validate without running
- `pflow workflow save ./file.pflow.md --name name` - Save to library

Agents write `.pflow.md` workflows directly using these primitives. For the complete agent guide, run `pflow instructions usage`.

### 2. Natural Language (Legacy - for Human Users)

The built-in planner converts natural language to workflows:
```bash
pflow "create a summary of this file"
```

> **Status:** Legacy. Gated pending markdown format migration (Task 107). Being phased out in favor of agent-direct `.pflow.md` creation.

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
    ├── File path: Parse .pflow.md
    ├── Saved name: Look up in ~/.pflow/workflows/
    └── Natural language: Legacy planner (gated)
    │
    ▼
Validation Pipeline (6 layers)
    │
    ├── 1. Structural: Required fields, valid node types
    ├── 2. Data Flow: Template dependencies resolved
    ├── 3. Template: ${var} syntax valid
    ├── 4. Node Type: Nodes exist in registry
    ├── 5. Output: Declared outputs available
    └── 6. Unknown Params: Warns on unrecognized node params
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

### Markdown Parser

The markdown parser (`src/pflow/core/markdown_parser.py`, ~350 lines) converts `.pflow.md` files into the same IR dict that validation, compilation, and execution operate on.

**Key types:**
- `MarkdownParseResult` — dataclass with `ir` (dict), `title` (str), `description` (str), `metadata` (dict, from frontmatter), `source` (original markdown content for save operations)
- `MarkdownParseError(ValueError)` — includes `line` number and `suggestion` for markdown-native error messages

**Main function:** `parse_markdown(content: str) -> MarkdownParseResult`

**Architecture:** Line-by-line state machine. Delegates YAML param parsing to `yaml.safe_load()` and Python code block syntax checking to `ast.parse()`. Tracks line numbers throughout for error messages that reference markdown structure (e.g., `"Node '### fetch' (line 15) missing required 'type' parameter"`).

**Pipeline:**
```
workflow.pflow.md → parse_markdown() → dict (IR) → normalize_ir() → validate → compile → execute
```

### Shared Store Pattern

See [shared-store.md](./core-concepts/shared-store.md) for the shared store pattern.

### Wrapper Chain

Each node is wrapped for instrumentation and namespacing:

```
InstrumentedWrapper (metrics, cache, trace)
    │
    ▼
BatchWrapper (if configured - iteration)
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

Templates use `${variable}` syntax. In `.pflow.md` files, templates appear inline in params and code blocks:

```markdown
- prompt: Summarize: ${input_data}
- url: https://api.example.com/${endpoint}
```

**Features:**
- Nested access: `${node.field}`, `${data[0].name}`
- Type preservation for simple templates
- Auto JSON parsing for nested access
- Strict mode (error) vs permissive (warning)

## Node System

### Core Node Types

| Type | Module | Description | Status |
|------|--------|-------------|--------|
| `shell` | `nodes/shell/` | Execute shell commands | Active |
| `http` | `nodes/http/` | HTTP requests | Active |
| `llm` | `nodes/llm/` | LLM API calls (via `llm` library) | Active |
| `read-file` | `nodes/file/` | Read file contents | Active |
| `write-file` | `nodes/file/` | Write file contents | Active |
| `claude-code` | `nodes/claude/` | Claude Code CLI integration | Active |
| `mcp` | `nodes/mcp/` | Execute MCP tools | Active |
| `git/*` | `nodes/git/` | Git operations | ⚠️ Deprecated |
| `github/*` | `nodes/github/` | GitHub API operations | ⚠️ Deprecated |

> **Deprecation Notice**: The `git/*` and `github/*` nodes are deprecated. Use MCP GitHub server (`mcp-github-*`) instead for GitHub operations, and shell commands with `git` CLI for Git operations.

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

> **Future**: Namespace and version support (`core/llm@1.0.0`) planned for v2.0. See `.taskmaster/feature-dump/registry-versioning.md` for design notes.

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

```markdown
### read-config

Read the configuration file from the filesystem MCP server.

- type: mcp
- server: filesystem
- tool: read_file
- arguments: {"path": "${file_path}"}
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
- `workflow_save` - Save a workflow (accepts raw `.pflow.md` content or file path)
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

> **⚠️ GATED (Task 107 Decision 26).** Repair prompts assume JSON workflow format. All code is preserved in `src/pflow/execution/repair_service.py` but unreachable from CLI and MCP. The `--auto-repair` CLI flag is disabled. Re-enabling requires rewriting repair prompts for the `.pflow.md` markdown format. AI agents building workflows should use `pflow --validate-only` for pre-execution validation and iterate on `.pflow.md` files directly.

> **Implementation details:** See `src/pflow/execution/CLAUDE.md` for checkpoint structure, error categories, and repair loop implementation.

## CLI Interface

### Running Workflows

```bash
# Run from file
pflow workflow.pflow.md

# Run saved workflow with parameters
pflow my-workflow param1=value1 param2=value2

# Run with stdin
cat data.txt | pflow my-workflow
```

### Managing Workflows

```bash
# Save a workflow
pflow workflow save ./workflow.pflow.md --name my-workflow

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

### Workflow Markdown Format (`.pflow.md`)

```markdown
# Example Workflow

What this workflow does.

## Inputs

### input_name

Description of the input.

- type: string
- required: true

## Steps

### unique_id

Description of what this node does.

- type: node_type
- param: value

## Outputs

### output_name

Description of the output.

- type: string
- source: ${node_id.key}
```

### Storage Locations

```
~/.pflow/
├── workflows/          # Saved workflows (.pflow.md with YAML frontmatter)
├── settings.json       # User settings (allow/deny lists)
├── debug/              # Execution traces
└── mcp/                # MCP server configurations
```

Saved workflows have YAML frontmatter prepended by `pflow workflow save`. Metadata fields are flat (no nesting wrapper):

```yaml
---
created_at: "2026-01-14T15:43:57Z"
updated_at: "2026-01-14T22:03:06Z"
version: "1.0.0"
execution_count: 8
last_execution_success: true
last_execution_params:
  version: "1.0.0"
---
```

The markdown body is never modified by metadata updates — `update_metadata()` reads the file, updates only the frontmatter YAML, and writes back with the original body intact.

## Design Decisions

### Why PocketFlow?

- Minimal (~150 lines) with clear semantics
- Node lifecycle (prep/exec/post) separates concerns
- Flow orchestration with `>>` operator
- Shared store pattern for communication

### Why Markdown Workflows (`.pflow.md`)?

- LLMs generate natural markdown from training data
- Self-documenting: workflow IS documentation
- Proper syntax highlighting for code blocks (shell, Python, YAML)
- No escaping issues (prompts are multi-line code blocks, not single-line JSON strings)
- Renders on GitHub as readable documentation
- Compiles to same internal dict (IR) for validation and execution

### Why Namespaced Shared Store?

- Prevents node output collisions
- Clear data provenance
- Debugging visibility
- Supports complex workflows

## Runtime vs User-Facing Components

The pflow architecture separates concerns between user-facing nodes and internal runtime components.

### User-Facing Nodes
Building blocks users work with directly:
- Defined in `src/pflow/nodes/`
- Discoverable via `pflow registry list`
- Have metadata describing their interface
- Appear in workflow `.pflow.md` files with their `type` field
- Examples: `read-file`, `write-file`, `llm`, `shell`, `http`

### Runtime Components
Internal infrastructure that executes workflows:
- Defined in `src/pflow/runtime/` and `src/pflow/execution/`
- Not exposed in the registry
- Handle workflow execution infrastructure
- Users don't interact with them directly
- Examples: `WorkflowExecutor`, `Compiler`, wrappers

### Example: WorkflowExecutor

**What users see** (in `.pflow.md`):
```markdown
### run_subflow

Run a sub-workflow for processing.

- type: workflow
- workflow_ref: path/to/workflow.pflow.md
- param_mapping: { "input": "${data}" }
```

**What happens internally**:
1. Runtime sees `type: "workflow"` in the IR
2. Instantiates `WorkflowExecutor` (not a regular node)
3. Executor handles: loading sub-workflow, storage isolation, parameter mapping, recursive execution, output mapping, error context

Users simply specify `type: "workflow"` - they don't need to know about WorkflowExecutor.

### Why This Separation?

| Benefit | Explanation |
|---------|-------------|
| **Simplicity** | Users only need to know about node types, not implementation |
| **Evolution** | Runtime can improve without changing user API |
| **Safety** | Runtime components can have special privileges regular nodes shouldn't |
| **Performance** | Runtime components can be optimized differently than user nodes |

### Key Runtime Components

| Component | Location | Purpose |
|-----------|----------|---------|
| **Compiler** | `runtime/compiler.py` | Transforms workflow IR → executable PocketFlow objects |
| **WorkflowExecutor** | `runtime/workflow_executor.py` | Handles nested workflow execution |
| **Wrappers** | `runtime/*_wrapper.py` | Add instrumentation, namespacing, templates |
| **TemplateResolver** | `runtime/template_resolver.py` | Resolves `${var}` syntax |

### When to Create What?

- **User-facing feature?** → Create a node in `nodes/`
- **Execution infrastructure?** → Create a runtime component in `runtime/`
- **Cross-cutting concern?** → Consider a wrapper

## Related Documents

- **PocketFlow**: `src/pflow/pocketflow/CLAUDE.md` - Framework documentation
- **Integration Guide**: `architecture/pflow-pocketflow-integration-guide.md`
- **Node Interface Format**: `architecture/reference/enhanced-interface-format.md`
- **Shared Store**: `architecture/core-concepts/shared-store.md`
