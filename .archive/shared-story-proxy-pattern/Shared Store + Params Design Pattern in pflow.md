# Shared Store + Bindings Design Pattern in pflow

## Overview

This document defines a core architectural principle in `pflow`: the coordination of logic and memory through a hybrid model of a **shared store** and per-node **bindings**. The purpose is to enable modular, reusable, and inspectable flows without imposing rigid global schemas or brittle interfaces.

This pattern is implemented using the lightweight **pocketflow framework** (100 lines of Python), leveraging its existing `params` system and flow orchestration capabilities.

The mechanism is not novel in general systems design, but its application to LLM-driven, tool-integrated workflows in a CLI-native orchestration context fills a currently unaddressed need.

## Key Concepts

### 1\. Shared Store

- An in-memory dictionary (`shared: Dict[str, Any]`) passed through the flow.

- Nodes can read from it during `prep()`, and write to it during `post()`.

- It serves as the coordination bus between otherwise isolated node executions.

- It holds transient memory, intermediate results, configuration, error logs, and final outputs.

### 2\. Bindings & Config

- **Input bindings** (`input_bindings: Dict[str, str]`) - map CLI interface names to shared store keys for reading
- **Output bindings** (`output_bindings: Dict[str, str]`) - map node output names to shared store keys for writing
- **Config** (`config: Dict[str, Any]`) - node-local configuration that doesn't affect shared store

These are stored within the pocketflow framework's existing `params` system and provide per-execution identity and routing without mutating across the flow.

## Integration with pocketflow Framework

Our pattern leverages the existing **pocketflow framework** which provides:

- **Node base class**: `prep()`/`exec()`/`post()` execution pattern
- **Params system**: `set_params()` method for node configuration
- **Flow orchestration**: `>>` operator for wiring nodes
- **Minimal overhead**: 100-line implementation with proven patterns

Node classes inherit from `pocketflow.Node` and access bindings through the existing `self.params` dictionary.

> **See also**: [pocketflow documentation](../pocketflow/docs/core_abstraction/communication.md) for framework details

## The Hybrid Power Pattern

The core innovation is the **Hybrid Power Pattern**: nodes are generic and reusable because they don't hardcode shared store keys. Instead:

- **Bindings handle routing** — they define which keys in the shared store a node reads from and writes to
- **Shared handles data** — it is the flow-global state where actual content, results, and intermediate memory live
- **Config handles tunables** — node-specific parameters that don't create data dependencies

Each node is written to:

1. **Expect binding definitions** via `self.params["input_bindings"]` and `self.params["output_bindings"]`
2. **Operate on shared values** at the dynamically specified keys
3. **Use config for behavior** via `self.params["config"]` without affecting data flow

This decouples node logic from shared memory structure. The memory schema becomes a property of the flow, not the node.

### Why This Pattern Matters

**Without bindings**: Nodes hardcode shared store keys → single schema change breaks every reuse → not scalable

**With bindings**: Same node works in different flows with different shared store layouts → maximum reusability

The planner acts as a "compiler," selecting keys and binding parameters so nodes can cooperate without hard-coding a global schema.

## Static Nodes vs Generated Flows

A crucial distinction in our implementation:

- **Static**: Node class definitions (written by developers once)
- **Generated**: Flow orchestration code (from IR)
- **Runtime**: CLI injection into shared store and config overrides

### Node Example (Static - Written Once)

```python
class Summarize(Node):  # Inherits from pocketflow.Node
    def prep(self, shared):
        # Access input binding through existing params system
        input_key = self.params["input_bindings"]["text"]  # "raw_transcript"
        return shared[input_key]

    def exec(self, prep_res):
        # Access config through existing params system
        temp = self.params["config"].get("temperature", 0.7)
        return call_llm(prep_res, temperature=temp)

    def post(self, shared, prep_res, exec_res):
        # Access output binding through existing params system
        output_key = self.params["output_bindings"]["summary"]  # "article_summary"
        shared[output_key] = exec_res
```

### Flow Example (Generated from IR)

**Flow A** (Document Processing):
```python
# Generated flow code (from IR)
yt_node = YTTranscript()
summarize_node = Summarize()

# Set params from IR bindings
yt_node.set_params({
    "input_bindings": {"url": "video_url"},
    "output_bindings": {"transcript": "raw_transcript"},
    "config": {"language": "en"}
})

summarize_node.set_params({
    "input_bindings": {"text": "raw_transcript"},
    "output_bindings": {"summary": "article_summary"},
    "config": {"temperature": 0.3}  # Conservative for academic content
})

# Wire the flow using pocketflow operators
yt_node >> summarize_node
flow = Flow(start=yt_node)
```

**Flow B** (Different Configuration):
```python
# Same static node classes, different generated flow
video_node = YTTranscript()
summary_node = Summarize()  # Same node class!

# Different bindings and config
video_node.set_params({
    "input_bindings": {"url": "source_url"},
    "output_bindings": {"transcript": "video_data/transcript"},
    "config": {"language": "es"}
})

summary_node.set_params({
    "input_bindings": {"text": "video_data/transcript"},
    "output_bindings": {"summary": "output/video_summary"},
    "config": {"temperature": 0.8}  # More creative for informal content
})

video_node >> summary_node
flow = Flow(start=video_node)
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
- Binding definitions for each node
- Configuration for each node
- Transitions between nodes

Example:

```json
{
  "nodes": [
    {
      "id": "summarize_1",
      "name": "Summarize",
      "input_bindings": {"text": "raw_texts/doc1.txt"},
      "output_bindings": {"summary": "summaries/doc1.txt"},
      "config": {"temperature": 0.7}
    },
    {
      "id": "store_1",
      "name": "Store",
      "input_bindings": {"content": "summaries/doc1.txt"},
      "output_bindings": {},
      "config": {"format": "markdown"}
    }
  ],
  "edges": [
    {"from": "summarize_1", "to": "store_1"}
  ]
}
```

### Why JSON IR?

- **Introspectable** — agents and tools can analyze, visualize, or validate without executing code
- **Composable** — subflows can be inserted, replaced, transformed
- **Repairable** — if an agent makes a mistake, users or other agents can patch IR safely
- **Validated** — schemas and flow constraints (e.g. node types, binding checks) can be enforced statically
- **Future-proof** — IR can be converted to/from code, GUI flows, or CLI scripts without ambiguity

Agents never generate node code directly. They output IR. IR is compiled into flow orchestration code using `set_params()` and pocketflow's flow wiring operators. Node logic lives in pre-written static classes.

## Benefits

### Reusability

- Nodes can be written once and reused in any flow
- They are blind to global memory layout
- Same node, different bindings = different behavior in different contexts

### Composability

- Flows can change shared schemas without rewriting nodes
- Intermediate outputs can be forked, merged, nested
- Planner can wire arbitrary node combinations

### Debuggability

- A full trace of what was read and written can be reconstructed
- `pflow trace` can be implemented via shared key logs
- Clear separation between data routing and business logic

### Flow-level Schema Definition

- The flow is the only place where shared key layout is declared
- This makes flows explicit interfaces: they define how memory is shaped, not nodes
- Planners can reason about data flow without node internals

### Agent Planning Compatibility

- When an LLM plans a flow, it defines the shared schema
- It also sets bindings to tell each node how to participate in that memory contract
- The LLM doesn't write code—it wires logic to a memory map

### User-defined Flows with LLM-assisted Schema

- Even when users manually define flow structure, the system can delegate shared schema construction to the LLM
- The LLM configures bindings for each node to correctly connect to the shared store layout it proposes
- This minimizes cognitive load while maintaining transparency and modularity

### Framework Integration Benefits

- **Minimal overhead**: Leverages existing 100-line pocketflow framework
- **Backward compatibility**: Existing pocketflow code works unchanged
- **Clean separation**: Node logic vs flow orchestration vs CLI integration
- **Proven patterns**: Uses established `prep()`/`exec()`/`post()` model
- **No framework modifications**: Pure pattern implementation using existing APIs

## Alternatives and Rejections

### Why not use only local config?

- Large values don't belong in config
- You lose shared observability between nodes
- No central place to inspect data lineage

### Why not only use shared with hardcoded keys?

- Nodes become rigid and non-reusable
- Reuse becomes error-prone across different flows
- Flows become tightly coupled to node internals

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

- Coordinate intelligent logic modules using simple memory contracts
- Support agent-generated or human-written flows interchangeably
- Provide a clear, testable, and auditable execution model
- Leverage JSON IR as the control plane for flow assembly, editing, and inspection
- Build on the proven pocketflow framework without modifications

The power is not in novelty but in fit. This pattern resolves the core tensions of AI workflow orchestration—modularity vs coordination, memory vs configuration, structure vs flexibility—using a mechanism that is minimal, expressive, and durable.

> **For CLI usage and runtime configuration details**, see [Shared-Store & Parameter Model — Canonical Spec](./Shared-Store%20&%20Parameter%20Model%20—%20Canonical%20Spec.md)
