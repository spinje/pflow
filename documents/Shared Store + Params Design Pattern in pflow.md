# Shared Store + Params Design Pattern in pflow

## Overview

This document defines a core architectural principle in `pflow`: the coordination of logic and memory through a hybrid model of a **shared store** and per-node **params**. The purpose is to enable modular, reusable, and inspectable flows without imposing rigid global schemas or brittle interfaces.

The mechanism is not novel in general systems design, but its application to LLM-driven, tool-integrated workflows in a CLI-native orchestration context fills a currently unaddressed need.

## Key Concepts

### 1\. Shared Store

- An in-memory dictionary (`shared: Dict[str, Any]`) passed through the flow.

- Nodes can read from it during `prep()`, and write to it during `post()`.

- It serves as the coordination bus between otherwise isolated node executions.

- It holds transient memory, intermediate results, configuration, error logs, and final outputs.

### 2\. Params

- A node-local dictionary (`params: Dict[str, Any]`) passed into each node (and its sub-flow, if applicable).

- It provides per-execution identity or configuration.

- It does not mutate across the flow.

- It is used to direct which keys in `shared` the node will operate on.

## The Pattern

- **Params handle routing** — they define which keys in the shared store a node reads from and writes to. They are node-local and immutable per invocation.

- **Shared handles data** — it is the flow-global state where actual content, results, and intermediate memory live.

Each node is written to:

1. **Expect param keys** like `input_key` or `output_key`, not hardcoded paths.

2. **Operate on `shared` values** at the specified keys.

This decouples node logic from shared memory structure. The memory schema becomes a property of the flow, not the node.

### Node Example

```
class Summarize(Node):
    def prep(self, shared):
        key = self.params["input_key"]
        return shared[key]

    def exec(self, text):
        return call_llm(text)

    def post(self, shared, _, summary):
        key = self.params["output_key"]
        shared[key] = summary

```

### Flow Example

```
shared = {
    "raw_texts": {
        "doc1.txt": "Some input",
        "doc2.txt": "Another input"
    },
    "summaries": {}
}

node = Summarize()
node.set_params({
    "input_key": "raw_texts/doc1.txt",
    "output_key": "summaries/doc1.txt"
})

node.run(shared)

```

This pattern is used repeatedly in batch scenarios or sub-flows. Each node becomes a reusable function, and the shared state becomes composable memory.

This gives you:

- **Isolation** — nodes don't assume global state layouts; they're portable.

- **Reuse** — nodes are decoupled from any one flow's data schema.

- **Memory** — the flow can persist and inspect structured results.

- **Interflow coordination** — shared enables nodes to build on one another’s outputs even across flow boundaries or iterations.

## Intermediate Representation (IR)

To enable agents to plan, inspect, mutate, and reason about flows without directly generating or editing Python code, `pflow` uses a structured JSON-based intermediate representation (IR).

The IR defines:

- The node graph (nodes, types, identifiers)

- Shared store schema (key bindings, namespaces)

- Parameter bindings for each node

- Transitions between nodes

Example:

```
{
  "nodes": [
    {"id": "a", "type": "Summarize", "params": {"input_key": "raw_texts/doc1.txt", "output_key": "summaries/doc1.txt"}},
    {"id": "b", "type": "Store"}
  ],
  "edges": [
    {"from": "a", "to": "b"}
  ]
}

```

### Why JSON IR?

- **Introspectable** — agents and tools can analyze, visualize, or validate without executing code.

- **Composable** — subflows can be inserted, replaced, transformed.

- **Repairable** — if an agent makes a mistake, users or other agents can patch IR safely.

- **Validated** — schemas and flow constraints (e.g. node types, param checks) can be enforced statically.

- **Future-proof** — IR can be converted to/from code, GUI flows, or CLI scripts without ambiguity.

Agents never generate node code directly. They output IR. IR is compiled or interpreted into flow objects. Flow logic lives in pre-written nodes.

The JSON IR may be saved as a `.pflow.json` file or managed in memory. CLI commands like `pflow plan`, `pflow explain`, or `pflow trace` can interface with it directly.

## Benefits

### Reusability

- Nodes can be written once and reused in any flow.

- They are blind to global memory layout.

### Composability

- Flows can change `shared` schemas without rewriting nodes.

- Intermediate outputs can be forked, merged, nested.

### Debuggability

- A full trace of what was read and written can be reconstructed.

- `pflow trace` can be implemented via shared key logs.

### Flow-level Schema Definition

- The flow is the only place where shared key layout is declared.

- This makes flows explicit interfaces: they define how memory is shaped, not nodes.

### Agent Planning Compatibility

- When an LLM plans a flow, it defines the shared schema.

- It also sets `params` to tell each node how to participate in that memory contract.

- The LLM doesn’t write code—it wires logic to a memory map.

### User-defined Flows with LLM-assisted Schema

- Even when users manually define flow structure using the CLI, the system can delegate the construction of the shared schema to the LLM.

- The LLM configures `params` for each node in the flow to correctly connect to the shared store layout it proposes.

- This minimizes the cognitive load on the user, making flow assembly more efficient without sacrificing transparency or modularity.

## Alternatives and Rejections

### Why not use only `params`?

- Large values don’t belong in `params`.

- You lose shared observability.

- No central place to inspect data lineage.

### Why not only use `shared` with hardcoded keys?

- Nodes become rigid.

- Reuse becomes error-prone.

- Flows become tightly coupled to node internals.

### Why not create a central schema registry?

- Too heavy for CLI-native and agent-generated flows.

- Schema is naturally emergent from flow design.

- Overhead does not match the problem space.

### Why not have agents generate code directly?

- Code is harder to validate, merge, or edit programmatically.

- IR supports structural planning, inspection, and transformation.

- Agents make fewer errors when emitting structured data.

- Code generation remains possible via `pflow export` once the flow is stable.

## Summary

This design enables `pflow` to:

- Coordinate intelligent logic modules using simple memory contracts.

- Support agent-generated or human-written flows interchangeably.

- Provide a clear, testable, and auditable execution model.

- Leverage JSON IR as the control plane for flow assembly, editing, and inspection.

The power is not in novelty but in fit. This pattern resolves the core tensions of AI workflow orchestration—modularity vs coordination, memory vs configuration, structure vs flexibility—using a mechanism that is minimal, expressive, and durable.