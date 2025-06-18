# pflow-pocketflow Integration Guide

> **Version**: MVP
> **MVP Status**: ✅ Critical Implementation Guide
> For complete MVP boundaries, see [MVP Scope](../features/mvp-scope.md)

## Navigation

**Related Documents:**
- **Framework**: [pocketflow Source](../../pocketflow/__init__.py) | [pocketflow Docs](../../pocketflow/CLAUDE.md)
- **Architecture**: [Architecture](./architecture.md) | [Shared Store](../core-concepts/shared-store.md)
- **Components**: [CLI Runtime](../features/cli-runtime.md) | [Planner](../features/planner.md) | [Runtime](../core-concepts/runtime.md)
- **Implementation**: [Component Inventory](./components.md)

## Overview

This document captures critical insights about how pflow and pocketflow integrate. These insights were discovered through deep analysis and are essential for correct implementation.

## Critical Insight #1: PocketFlow IS the Execution Engine

**What new implementers often miss**: Task descriptions might suggest building an "execution engine" or "runtime system", but pocketflow's `Flow` class already provides complete execution orchestration.

```python
# WRONG - Don't reimplement execution
class PflowExecutionEngine:
    def execute_nodes(self, nodes):
        # Don't do this!

# RIGHT - Use pocketflow directly
from pocketflow import Flow
flow = Flow(start=first_node)
result = flow.run(shared)
```

**What pocketflow provides**:
- Complete node lifecycle management (prep→exec→post)
- Action-based routing between nodes using the `-` operator
- Built-in retry logic and error handling
- Flow composition and nesting
- Parameter passing system
- The `>>` operator for chaining nodes
- `Node` class with prep/exec/post lifecycle
- `Flow` class for orchestration (THIS IS THE EXECUTION ENGINE)
- Shared Store Pattern
    - NOT a built-in class, just a dictionary pattern
    - Nodes read in `prep(shared)`, write in `post(shared, ...)`
    - Framework passes the dictionary through execution

**What pflow adds**:
- CLI interface and command parsing
- JSON IR to Flow compilation
- Node registry and discovery
- Template variable resolution
- Natural language planning

## Critical Insight #2: No Wrapper Classes Needed

**The trap**: Initial instinct is to create `PflowNode(pocketflow.Node)` and `PflowFlow(pocketflow.Flow)` wrapper classes.

**The reality**: These wrappers add zero value and unnecessary complexity.

```python
# WRONG - Unnecessary wrapper
class PflowNode(pocketflow.Node):
    pass  # This adds nothing!

# RIGHT - Direct inheritance
from pocketflow import Node

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
    """Validate reserved keys and patterns."""
    if "stdin" in shared and not isinstance(shared["stdin"], str):
        raise ValueError("stdin must be string")
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
    """Replace $variables with shared store values."""
    import re
    def replacer(match):
        key = match.group(1)
        return str(shared.get(key, f"${key}"))

    return re.sub(r'\$(\w+)', replacer, text)

# Usage:
prompt = "Analyze this file: $content"
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

## Critical Insight #7: JSON IR Compilation Pattern

**What NOT to do**: Generate Python code strings or implement a complex compiler.

**What to do**: Instantiate pocketflow objects from JSON.

```python
def compile_ir_to_flow(ir_json):
    """Convert JSON IR to executable pocketflow.Flow."""
    from pocketflow import Flow
    from pflow.registry import get_node_class

    # Create nodes
    nodes = {}
    for node_spec in ir_json["nodes"]:
        NodeClass = get_node_class(node_spec["type"])
        node = NodeClass()
        if "params" in node_spec:
            node.set_params(node_spec["params"])
        nodes[node_spec["id"]] = node

    # Connect nodes
    for edge in ir_json["edges"]:
        from_node = nodes[edge["from"]]
        to_node = nodes[edge["to"]]
        action = edge.get("action", "default")

        if action == "default":
            from_node >> to_node
        else:
            from_node - action >> to_node

    # Create flow
    start_node = nodes[ir_json["start_node"]]
    return Flow(start=start_node)
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
# LLM output (JSON IR):
{
    "nodes": [
        {"id": "n1", "type": "read-file", "params": {"file_path": "$input_file"}},
        {"id": "n2", "type": "llm", "params": {"prompt": "Summarize: $content"}}
    ],
    "edges": [{"from": "n1", "to": "n2"}],
    "start_node": "n1"
}
```

## Critical Insight #10: What NOT to Build

**Avoid these common traps**:

1. **Execution orchestration** - pocketflow.Flow does this
2. **Retry mechanisms** - pocketflow.Node has this built-in
3. **Complex abstractions** - Use pocketflow directly
4. **SharedStore class** - It's just a dict with validation functions
5. **Template engine** - Simple string substitution is enough
6. **Node wrapper classes** - Direct inheritance is clearer
7. **Complex registry** - Filesystem scanning is sufficient
8. **Compatibility system** (MVP) - MVP nodes are designed to be compatible
9. **Metrics system** (MVP) - Focus on working code first
10. **Performance optimization** (MVP) - Make it work, then make it fast

## Implementation Principles

1. **When you see "system" or "engine" in a task** - Think "simple functions" first
2. **When you want to wrap pocketflow** - Use it directly instead
3. **When designing nodes** - Follow the natural interface pattern (shared["key"])
4. **When building the CLI** - Keep flag parsing simple
5. **When implementing planning** - Let the LLM handle structure, not details

## The Core Architecture

```
User Input → CLI Parser → Flag Categorization → Planning (optional) → JSON IR →
IR Compiler → pocketflow.Flow → Execution → Results

Where:
- CLI Parser: click-based command parsing
- Planning: LLM generates workflow structure
- IR Compiler: Converts JSON to pocketflow objects
- Execution: pocketflow handles everything
```

## Final Wisdom

pflow is a **CLI tool** that makes pocketflow accessible, not a framework on top of a framework. Every line of code should have a clear purpose: CLI interface, node discovery, workflow planning, or IR compilation. If you find yourself reimplementing something that feels like execution orchestration, you're probably duplicating pocketflow functionality.

**Remember**: We're extending pocketflow, not replacing it.
