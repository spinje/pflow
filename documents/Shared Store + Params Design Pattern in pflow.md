# Shared Store + Proxy Design Pattern in pflow

## Overview

This document defines a core architectural principle in `pflow`: the coordination of logic and memory through a **shared store** with an optional **proxy layer** that enables standalone, reusable nodes without imposing binding complexity on node writers.

This pattern is implemented using the lightweight **pocketflow framework** (100 lines of Python), leveraging its existing `params` system and flow orchestration capabilities.

## Node Autonomy Principle

The fundamental insight is that **node writers shouldn't need to understand flow orchestration concepts**. They should write simple, testable business logic using natural key names, while flow designers handle mapping complexity at the orchestration level.

### Key Benefits

1. **Standalone Node Development** - Node writers use intuitive keys (`shared["text"]`)
2. **Simplified Testing** - Natural test setup with direct key access  
3. **Better Separation of Concerns** - Nodes focus on logic, flows handle routing
4. **Reduced Cognitive Load** - Node writers focus on their domain expertise
5. **More Readable Code** - `shared["text"]` beats `self.params["input_bindings"]["text"]`

## Key Concepts

### 1. Shared Store

- An in-memory dictionary (`shared: Dict[str, Any]`) passed through the flow.
- Nodes read from it during `prep()`, and write to it during `post()`.
- It serves as the coordination bus between otherwise isolated node executions.
- It holds transient memory, intermediate results, configuration, error logs, and final outputs.

### 2. NodeAwareSharedStore Proxy

- **Purpose**: Transparent mapping layer that enables simple node code while supporting complex flow routing
- **Behavior**: Maps keys when mappings defined, passes through otherwise
- **Performance**: Zero overhead when no mapping needed (direct pass-through)
- **Activation**: Only when IR defines mappings for a node

### 3. Config (Flat Structure)

- **Config** (`config: Dict[str, Any]`) stored directly in `self.params` (flat structure)
- Node-local configuration that doesn't affect shared store
- Simple access via `self.params.get("temperature", 0.7)`

## Integration with pocketflow Framework

Our pattern leverages the existing **pocketflow framework** which provides:

- **Node base class**: `prep()`/`exec()`/`post()` execution pattern
- **Params system**: `set_params()` method for node configuration
- **Flow orchestration**: `>>` operator for wiring nodes
- **Minimal overhead**: 100-line implementation with proven patterns

Node classes inherit from `pocketflow.Node` and access config through the simplified `self.params` dictionary.

> **See also**: [pocketflow documentation](../pocketflow/docs/core_abstraction/communication.md) for framework details

## The Standalone Node Pattern

The core innovation is **standalone nodes**: nodes are generic and reusable because they use natural, intuitive interfaces. Instead of binding complexity:

- **Nodes use natural keys** — `shared["text"]`, `shared["summary"]`
- **Proxy handles routing** — transparent mapping when needed for compatibility
- **Config is simple** — flat structure accessible via `self.params.get("key")`

Each node is written to:

1. **Use natural interfaces** via direct shared store access (`shared["text"]`)
2. **Access config simply** via `self.params.get("key", default)`
3. **Focus on business logic** without orchestration concerns

This decouples node logic from flow orchestration. The complexity becomes a property of the flow, not the node.

### Why This Pattern Matters

**Without proxy**: Nodes must understand binding indirection → complex for node writers → reduced productivity

**With proxy**: Same node works in different flows with transparent mapping → maximum simplicity and reusability

The flow orchestration acts as a "compiler," handling schema mapping so nodes can focus purely on business logic.

## Static Nodes vs Generated Flows

A crucial distinction in our implementation:

- **Static**: Node class definitions (written by developers once)
- **Generated**: Flow orchestration code (from IR) with optional proxy setup
- **Runtime**: CLI injection into shared store and config overrides

### Node Example (Static - Written Once)

```python
class Summarize(Node):  # Inherits from pocketflow.Node
    """Summarizes text content using LLM.
    
    Interface:
    - Reads: shared["text"] - input text to summarize
    - Writes: shared["summary"] - generated summary
    - Config: temperature (default 0.7) - LLM creativity
    """
    def prep(self, shared):
        return shared["text"]  # Simple, natural access
    
    def exec(self, prep_res):
        temp = self.params.get("temperature", 0.7)  # Flat config
        return call_llm(prep_res, temperature=temp)
    
    def post(self, shared, prep_res, exec_res):
        shared["summary"] = exec_res  # Direct assignment
```

## Node Testing Simplicity

The proxy pattern makes testing intuitive and natural:

```python
def test_summarize_node():
    node = Summarize()
    node.set_params({"temperature": 0.5})  # Just config
    
    # Natural, intuitive shared store
    shared = {"text": "Long article content here..."}
    
    node.run(shared)
    
    assert "summary" in shared
    assert len(shared["summary"]) < len(shared["text"])
```

Compare this to complex binding setup requirements in other approaches.

## Progressive Complexity Examples

### Level 1 - Simple Flow (Direct Access)

```python
# No mappings needed - nodes access shared store directly
shared = {"text": "Input content"}

summarize_node = Summarize()
summarize_node.set_params({"temperature": 0.7})

flow = Flow(start=summarize_node)
flow.run(shared)  # Node accesses shared["text"] directly
```

### Level 2 - Complex Flow (Proxy Mapping)

```python
# Marketplace compatibility - proxy maps keys transparently
shared = {"raw_transcript": "Input content"}  # Flow schema

# Generated flow code handles proxy creation
if "mappings" in ir and summarize_node.id in ir["mappings"]:
    mappings = ir["mappings"][summarize_node.id]
    proxy = NodeAwareSharedStore(
        shared,
        input_mappings={"text": "raw_transcript"},
        output_mappings={"summary": "article_summary"}
    )
    summarize_node._run(proxy)  # Node still uses shared["text"]
else:
    summarize_node._run(shared)  # Direct access
```

**Same node code works at both levels.**

### Flow Example (Generated from IR)

**Flow A** (Simple - Direct Access):
```python
# Generated flow code (from IR)
summarize_node = Summarize()

# Set params from IR config
summarize_node.set_params({
    "temperature": 0.3  # Conservative for academic content
})

# Wire the flow using pocketflow operators
flow = Flow(start=summarize_node)
```

**Flow B** (Complex - With Proxy Mapping):
```python
# Same static node class, different generated flow
summary_node = Summarize()  # Same node class!

# Set config from IR
summary_node.set_params({
    "temperature": 0.8  # More creative for informal content
})

# Generated proxy setup for marketplace compatibility
if summary_node.id in ir["mappings"]:
    proxy = NodeAwareSharedStore(
        shared,
        input_mappings={"text": "video_data/transcript"},
        output_mappings={"summary": "output/video_summary"}
    )
    summary_node._run(proxy)
else:
    summary_node._run(shared)
```

The same `Summarize` node class works in completely different contexts with different shared store schemas.

## Shared Store Namespacing

Path-like keys enable organized, collision-free shared store layouts:

**Key**: `"raw_texts/doc1.txt"`
**Maps to**:
```python
shared = {
    "raw_texts": {
        "doc1.txt": "Some input content"
    }
}
```

**Benefits**:
- **Namespacing**: Clear organization of related data
- **Collision avoidance**: `"inputs/doc1.txt"` vs `"outputs/doc1.txt"`
- **Debugging**: Easy to trace data flow through nested structure
- **Modularity**: Subflows can own their namespace

## Intermediate Representation (IR)

To enable agents to plan, inspect, mutate, and reason about flows without directly generating or editing Python code, `pflow` uses a structured JSON-based intermediate representation (IR).

The IR defines:

- The node graph (nodes, types, identifiers)
- Configuration for each node
- Mapping definitions for complex flows (when needed)
- Transitions between nodes

Example:

```json
{
  "nodes": [
    {
      "id": "summarize_1", 
      "name": "Summarize",
      "config": {"temperature": 0.7}
    },
    {
      "id": "store_1",
      "name": "Store",
      "config": {"format": "markdown"}
    }
  ],
  "edges": [
    {"from": "summarize_1", "to": "store_1"}
  ],
  "mappings": {
    "summarize_1": {
      "input_mappings": {"text": "raw_texts/doc1.txt"},
      "output_mappings": {"summary": "summaries/doc1.txt"}
    }
  }
}
```

Key change: Mappings are flow-level concern in IR, nodes just declare natural interfaces.

### Why JSON IR?

- **Introspectable** — agents and tools can analyze, visualize, or validate without executing code
- **Composable** — subflows can be inserted, replaced, transformed
- **Repairable** — if an agent makes a mistake, users or other agents can patch IR safely
- **Validated** — schemas and flow constraints (e.g. node types, mapping checks) can be enforced statically
- **Future-proof** — IR can be converted to/from code, GUI flows, or CLI scripts without ambiguity

Agents never generate node code directly. They output IR. IR is compiled into flow orchestration code using `set_params()` and pocketflow's flow wiring operators. Node logic lives in pre-written static classes.

## Developer Experience Benefits

- **Node development is simpler** - no binding knowledge required
- **Testing is intuitive** - natural shared store setup
- **Debugging is clearer** - direct key access in node code
- **Documentation is self-evident** - `shared["key"]` shows interface

## Benefits

### Reusability

- Nodes can be written once and reused in any flow
- They use natural interfaces that are self-documenting
- Same node, different proxy configuration = different behavior in different contexts

### Composability

- Flows can change shared schemas without rewriting nodes
- Intermediate outputs can be forked, merged, nested
- Flow orchestration can wire arbitrary node combinations

### Debuggability

- Node code is transparent (direct key access)
- Proxy mapping is explicit in generated flow code
- Clear separation between business logic and routing logic

### Flow-level Schema Definition

- The flow is the only place where mapping complexity is declared
- This makes flows explicit interfaces: they define how memory is shaped, not nodes
- Planners can reason about data flow without node internals

### Agent Planning Compatibility

- When an LLM plans a flow, it can define natural shared store schemas
- It optionally sets up proxy mappings for marketplace compatibility
- The LLM doesn't write code—it orchestrates simple, standalone nodes

### User-defined Flows with LLM-assisted Schema

- Even when users manually define flow structure, nodes remain simple
- The system can delegate schema mapping to flow orchestration
- This minimizes cognitive load while maintaining transparency and modularity

### Framework Integration Benefits

- **Minimal overhead**: Leverages existing 100-line pocketflow framework
- **Backward compatibility**: Existing pocketflow code works unchanged  
- **Clean separation**: Node logic vs flow orchestration vs CLI integration
- **Proven patterns**: Uses established `prep()`/`exec()`/`post()` model
- **No framework modifications**: Pure pattern implementation using existing APIs

## Alternatives and Rejections

### Why not force binding complexity on every node?

- Node writers shouldn't need to understand flow orchestration
- Testing becomes complex and unnatural
- Reduces developer productivity and increases cognitive load

### Why not only use shared with hardcoded keys?

- Works great for simple flows (and we support this!)
- Proxy provides compatibility layer for complex marketplace scenarios
- Progressive complexity model gives best of both worlds

### Why not create a central schema registry?

- Too heavy for CLI-native and agent-generated flows
- Schema is naturally emergent from flow design
- Overhead does not match the problem space

### Why not have agents generate code directly?

- Code is harder to validate, merge, or edit programmatically
- IR supports structural planning, inspection, and transformation
- Agents make fewer errors when emitting structured data
- Code generation remains possible via `pflow export` once the flow is stable

### Why not modify the pocketflow framework?

- Keeps framework minimal and focused
- Leverages existing, proven patterns
- Maintains backward compatibility
- Pattern works within existing APIs

## Summary

This design enables `pflow` to:

- Write standalone, simple nodes that focus purely on business logic
- Support both simple flows (direct access) and complex flows (proxy mapping)
- Provide a clear, testable, and auditable execution model
- Leverage JSON IR as the control plane for flow assembly, editing, and inspection
- Build on the proven pocketflow framework without modifications

The power is in simplicity. This pattern makes node development intuitive while preserving all the flexibility needed for complex orchestration scenarios.

> **For CLI usage and runtime configuration details**, see [Shared-Store & Parameter Model — Canonical Spec](./Shared-Store%20&%20Parameter%20Model%20—%20Canonical%20Spec.md)