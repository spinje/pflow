# pflow-pocketflow Integration Guide

> **Version**: Current
> **Status**: ✅ Critical Guide for pflow Internal Development

## Navigation

**Related Documents:**
- **Framework**: pocketflow Source (`src/pflow/pocketflow/__init__.py`) | pocketflow Docs (`src/pflow/pocketflow/CLAUDE.md`)
- **Architecture**: [Architecture](./architecture.md) | [Shared Store](./core-concepts/shared-store.md)
- **Concepts**: Historical workflow-generation spec | [Execution Reference](./historical/execution-reference-original.md)
- **Implementation**: [Runtime CLAUDE.md](../src/pflow/runtime/CLAUDE.md)

## Overview

This document captures critical insights about how pflow and pocketflow integrate. These insights were discovered through deep analysis and are essential for correct implementation.

## Scope & Audience

> **This guide is for pflow internal developers**, not for users or AI agents building workflows.

**Users and AI agents** should ALWAYS use markdown workflows via the CLI (`pflow workflow.pflow.md`). They never interact with PocketFlow directly.

**This guide covers two internal development patterns:**

1. **Writing platform nodes** - All nodes inherit from `pocketflow.Node`. This is the standard pattern for extending pflow's capabilities. Wrappers (template resolution, namespacing, instrumentation) are applied automatically by the compiler - node authors don't implement these.

2. **Understanding the execution engine** - `WorkflowEngine` handles graph traversal and all runtime concerns. PocketFlow provides the node lifecycle only.

**For the compilation/runtime layer** where the workflow IR is transformed into `CompiledWorkflow` and executed via `WorkflowEngine`, see `src/pflow/runtime/CLAUDE.md`.

## Critical Insight #1: PocketFlow Provides the Node Lifecycle, Not Execution

PocketFlow is slimmed to ~85 lines: `BaseNode`, `_ConditionalTransition`, `Node`. The `Flow` class was removed (Task 135). Graph traversal and all runtime concerns are handled by `WorkflowEngine` in `runtime/engine/`.

**What PocketFlow provides**:
- Node lifecycle (prep→exec→post)
- Retry logic (`Node._exec` with `max_retries`/`wait`)
- The `>>` and `-` operators for wiring nodes during compilation
- Shared Store Pattern (a plain dictionary: nodes read in `prep(shared)`, write in `post(shared, ...)`)

**What pflow's engine adds** (all in `runtime/engine/`):
- Graph traversal (`WorkflowEngine.run` — walks node successors)
- Template resolution (resolve `${var}` against shared store)
- Namespacing (per-node output isolation via `NamespacedSharedStore`)
- Batch processing (sequential/parallel, retry, error handling)
- Instrumentation (memoization cache, trace, metrics, progress callbacks, loop guards)

**What pflow adds beyond the engine**:
- CLI interface and command parsing
- Markdown parser (`.pflow.md` → IR dict) and IR-to-CompiledWorkflow compilation
- Node registry and discovery
- `WorkflowRunner` (resolution → validation → compilation → execution → cleanup)

## Critical Insight #2: No Wrapper Classes Needed

**The trap**: Initial instinct is to create wrapper classes around PocketFlow nodes.

**The reality**: These wrappers add zero value and unnecessary complexity.

```python
# WRONG - Unnecessary wrapper
class PflowNode(pocketflow.Node):
    pass  # This adds nothing!

# RIGHT - Direct inheritance
from pflow.pocketflow import Node

class ReadFileNode(Node):
    def prep(self, shared):
        return shared.get("file_path")

    def exec(self, file_path):
        with open(file_path) as f:
            return f.read()

    def post(self, shared, prep_res, exec_res):
        shared["content"] = exec_res
        return "default"
```

## Critical Insight #3: Shared Store is Just a Dict

**What tasks might suggest**: Create a SharedStore class with validation and management.

**What's actually needed**: PocketFlow uses a plain dictionary. We only need validation functions.

```python
# WRONG - Over-engineered wrapper
class SharedStore(dict):
    def __setitem__(self, key, value):
        # Complex validation logic
        super().__setitem__(key, value)

# RIGHT - Simple validation functions
def validate_shared_store(shared):
    """Validate system keys and patterns."""
    if "__execution__" in shared and not isinstance(shared["__execution__"], dict):
        raise ValueError("__execution__ must be dict")
    return True

# In use:
shared = {}
shared["file_path"] = "input.txt"
validate_shared_store(shared)
```

## Critical Insight #4: Template Resolution is String Substitution

**The misconception**: Building a complex "template resolution system" or "engine".

**The reality**: It's just regex-based string replacement.

```python
def resolve_template(text, shared):
    """Replace ${variables} with shared store values."""
    import re
    def replacer(match):
        key = match.group(1)
        return str(shared.get(key, f"${key}"))

    return re.sub(r'\$(\w+)', replacer, text)

# Usage:
prompt = "Analyze this file: ${content}"
resolved = resolve_template(prompt, {"content": "file data"})
# Result: "Analyze this file: file data"
```

## Critical Insight #5: NodeAwareSharedStore Proxy is for MVP

**What documentation shows**: The proxy pattern exists for scenarios where nodes have incompatible interfaces.

**MVP**: All MVP nodes might seems to use consistent, natural interfaces:
- `shared["file_path"]` for file operations
- `shared["content"]` for text data
- `shared["prompt"]` and `shared["response"]` for LLMs

But this is ONLY true for sandboxed examples. In the real world, nodes have incompatible interfaces and we need to use the proxy pattern to get the architecture right from the start.

**When proxy is needed**: When combining nodes from different sources with incompatible key names.

## Critical Insight #6: CLI Parameter Resolution Pattern

**The challenge**: CLI flags need to be routed to either shared store or node parameters.

**The solution**: Simple categorization based on metadata.

```python
def categorize_flags(flags_dict, node_metadata):
    """Route CLI flags to appropriate destinations."""
    data_flags = {}
    param_flags = {}

    for key, value in flags_dict.items():
        if key in node_metadata.get("params", []):
            param_flags[key] = value  # Goes to node.set_params()
        else:
            data_flags[key] = value   # Goes to shared store

    return data_flags, param_flags
```

## Critical Insight #7: IR Compilation Pattern

**What NOT to do**: Generate Python code strings or implement a complex compiler.

**What to do**: Instantiate bare nodes from the IR dict, build per-node configs, return a `CompiledWorkflow`.

```python
def compile_workflow(ir_dict):
    """Convert IR dict to CompiledWorkflow (bare nodes + configs)."""
    from pflow.registry import get_node_class

    # Create bare nodes + configs
    nodes, configs = {}, {}
    for node_spec in ir_dict["nodes"]:
        NodeClass = get_node_class(node_spec["type"])
        node = NodeClass()
        node.node_id = node_spec["id"]
        if "params" in node_spec:
            node.set_params(node_spec["params"])
        nodes[node_spec["id"]] = node
        configs[node_spec["id"]] = NodeConfig(...)  # template, batch, namespace metadata

    # Connect nodes (PocketFlow wiring operators still used)
    for edge in ir_dict["edges"]:
        from_node = nodes[edge["from"]]
        to_node = nodes[edge["to"]]
        action = edge.get("action", "default")
        if action == "default":
            from_node >> to_node
        else:
            from_node - action >> to_node

    start_node = nodes[ir_dict["start_node"]]
    return CompiledWorkflow(start_node=start_node, node_configs=configs)
    # Execution: WorkflowEngine().run(compiled, shared_store)
```

## Critical Insight #8: Registry is Filesystem Scanning

**Not needed**: Package registry, versioning system, or complex indexing.

**What's needed**: Simple filesystem scanning for Node subclasses.

```python
def scan_for_nodes(directory):
    """Find all pocketflow.Node subclasses."""
    # Use ast or importlib to find Node subclasses
    # Return simple dict: {"read-file": ReadFileNode, ...}
```

## Critical Insight #9: Natural Language Planning Boundaries

**The LLM's job**:
- Select which nodes to use
- Determine the workflow structure
- Create template variables for data flow

**NOT the LLM's job**:
- Generate actual parameter values
- Implement execution logic
- Create detailed prompts for every node

```python
# LLM output (IR dict — produced from .pflow.md by the markdown parser):
{
    "nodes": [
        {"id": "n1", "type": "read-file", "params": {"file_path": "${input_file}"}},
        {"id": "n2", "type": "llm", "params": {"prompt": "Summarize: ${content}"}}
    ],
    "edges": [{"from": "n1", "to": "n2"}],
    "start_node": "n1"
}
```

## Critical Insight #10: What NOT to Build (and What Was Built Later)

**Core principles that remain true:**

1. **Execution orchestration** - WorkflowEngine handles graph traversal; don't reimplement
2. **Retry mechanisms** - pocketflow.Node has this built-in; use `max_retries` and `wait`
3. **Complex abstractions in nodes** - Nodes should be simple; complexity lives in the engine

**What the MVP avoided but was added as the system matured:**

4. **~~SharedStore class~~** → `NamespacedSharedStore` proxy for collision prevention (applied by engine)
5. **~~Simple template engine~~** → Template resolution grew to 600+ lines with path traversal, type preservation, auto JSON parsing
6. **~~No runtime layer~~** → `WorkflowEngine` orchestrates all runtime concerns (template resolution, namespacing, batch iteration, caching, tracing, progress callbacks) directly during graph traversal. Nodes remain bare — the engine handles everything.
7. **~~Simple registry~~** → Registry now includes metadata extraction, LLM-powered discovery
8. **~~No metrics~~** → `MetricsCollector` tracks timing, tokens, costs

**The lesson:** Start simple, but expect complexity to emerge. The key is that complexity was added in the **compiler/engine layer**, not in node implementations. Nodes remain simple.

## Implementation Principles

1. **When you see "system" or "engine" in a task** - Think "simple functions" first
2. **When you want to wrap pocketflow** - Use it directly instead
3. **When designing nodes** - Follow the natural interface pattern (shared["key"])
4. **When building the CLI** - Keep flag parsing simple
5. **When implementing workflow-generation helpers** - Let the LLM handle structure, not details

## The Core Principle: "Extend, Don't Wrap"

This principle guides every architectural decision:
- Inherit from `pocketflow.Node` directly, keep nodes simple
- Extend shared dict with validation functions, don't wrap in classes
- Extend CLI patterns, don't reinvent parsing
- Runtime concerns (templates, namespacing, batch, tracing) belong in the engine, not in node wrappers

This keeps pflow as a focused layer that:
- Makes workflow execution accessible via CLI
- Provides platform-specific nodes (shell, llm, http, mcp, etc.)
- Handles all runtime orchestration (engine) and compilation (compiler)
- Enables workflow reuse and composition

## The Core Architecture

```
User Input → CLI Parser → Markdown Parser → IR dict →
compile_workflow() → CompiledWorkflow(bare nodes + configs) →
WorkflowEngine.run(workflow, shared_store) → ExecutionResult

Where:
- Markdown Parser: .pflow.md → IR dict
- compile_workflow(): IR dict → bare node instances + NodeConfig metadata + wiring
- WorkflowEngine: walks graph, handles template resolution, batch, caching, tracing
- PocketFlow: provides Node lifecycle (prep/exec/post) and wiring operators (>>, -)
```

## Final Wisdom

pflow nodes are simple — they inherit from `pocketflow.Node`, implement `prep`/`exec`/`post`, and communicate via the shared store. All complexity (template resolution, namespacing, batch processing, caching, tracing) lives in the engine, not in the nodes. If you find yourself adding cross-cutting behavior to a node, it probably belongs in the engine instead.
