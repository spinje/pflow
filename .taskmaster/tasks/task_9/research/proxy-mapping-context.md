# Proxy Mapping and Collision Detection Context

## Purpose of This Document

This document provides essential context for implementing the shared store proxy mapping system. It captures architectural decisions and clarifications that emerged from deep analysis of how black-box nodes can work together in pflow.

## The Fundamental Problem

pflow uses reusable, black-box nodes with fixed interfaces. These nodes cannot be modified for each workflow - they always read and write to the same shared store keys. This creates two critical challenges:

1. **Interface Mismatch**: Node A writes to `shared["transcript"]`, but Node B reads from `shared["prompt"]`
2. **Key Collisions**: Multiple LLM nodes all write to `shared["response"]`, overwriting each other

Without a solution, workflows would need dozens of adapter nodes just to move data around, defeating the purpose of simple, composable workflows.

## The Proxy Mapping Solution

The `NodeAwareSharedStore` proxy provides a translation layer between nodes and the shared store. It intercepts reads and writes, transforming them according to mappings defined in the workflow's JSON IR.

### What the Proxy Does

The proxy has **one job**: Transform shared store keys based on IR-defined mappings.

```python
# Node always does this:
shared["prompt"] = "Analyze this"

# But proxy transforms it based on IR:
# If IR says: {"output_mappings": {"prompt": "analyzer.input"}}
# Then proxy writes to: shared["analyzer"]["input"] = "Analyze this"
```

### What the Proxy Does NOT Do

- Does NOT make decisions about namespacing (planner does this)
- Does NOT detect collisions (planner prevents them)
- Does NOT generate mapping paths (planner creates them)
- Does NOT contain any business logic (it's just a translator)

## How Mappings Work

### Input Mappings
When a node reads a key, the proxy can redirect it to a different location:

```json
"input_mappings": {
  "prompt": "fetcher.issue_data.body"
}
```

This means: When node reads `shared["prompt"]`, actually give it the value from `shared["fetcher"]["issue_data"]["body"]`

### Output Mappings
When a node writes a key, the proxy can redirect it to avoid collisions:

```json
"output_mappings": {
  "response": "analyzer.response"
}
```

This means: When node writes `shared["response"]`, actually write to `shared["analyzer"]["response"]`

### Path-Based Extraction
The proxy supports dot notation for nested data access:

```
"issue_title": "github_response.data.title"
"first_label": "github_response.data.labels[0].name"
```

This eliminates the need for separate extraction nodes.

## Collision Prevention Strategy

Collisions are prevented **by the planner** during IR generation, not detected at runtime:

1. **Planner assigns namespaced outputs**: Every node's outputs are prefixed with the node ID
2. **IR contains explicit mappings**: All data routing is predetermined
3. **Proxy just follows instructions**: No runtime collision detection needed

Example:
```json
{
  "nodes": [
    {"id": "analyzer", "type": "llm"},
    {"id": "summarizer", "type": "llm"}
  ],
  "mappings": {
    "analyzer": {
      "output_mappings": {"response": "analyzer.response"}
    },
    "summarizer": {
      "input_mappings": {"prompt": "analyzer.response"},
      "output_mappings": {"response": "summarizer.response"}
    }
  }
}
```

## Simple Debugging for MVP

The debugging strategy is to make data flow visible through logging, not complex visualization:

### Execution Trace Format
```
[1] fetcher (github-get-issue)
    → writes: fetcher.issue_data, fetcher.issue_title

[2] analyzer (llm)
    ← reads: prompt from fetcher.issue_data.body
    → writes: analyzer.response

[3] summarizer (llm)
    ← reads: prompt from analyzer.response
    → writes: summarizer.response
```

### Implementation Approach
- Log each node execution with its ID and type
- Show input mappings as "reads X from Y"
- Show output mappings as "writes to Z"
- Display final shared store state

This provides complete visibility without complexity.

## Integration with pflow Architecture

### The Planner's Role
The planner (Task 17) is responsible for:
- Generating namespaced keys to prevent collisions
- Creating mappings to connect incompatible interfaces
- Tracking data shapes for path-based extraction

### The Runtime's Role
The runtime (Task 22) simply:
- Creates proxy with mappings from IR
- Wraps shared store for each node that has mappings
- Logs data flow for debugging

### The Node's Perspective
Nodes remain completely unaware of proxying:
- They use their natural interface keys
- They don't know about namespacing
- They can't detect or handle collisions

## Real-World Example

Consider a GitHub issue analysis workflow:

```json
{
  "nodes": [
    {"id": "fetch", "type": "github-get-issue"},
    {"id": "analyze", "type": "llm"},
    {"id": "fix", "type": "claude-code"}
  ],
  "mappings": {
    "analyze": {
      "input_mappings": {
        "prompt": "fetch.issue_data.body"
      },
      "output_mappings": {
        "response": "analysis"
      }
    },
    "fix": {
      "input_mappings": {
        "prompt": "template:Fix this issue:\n${fetch.issue_data.title}\n\nAnalysis:\n${analysis}"
      }
    }
  }
}
```

The proxy enables:
- Direct nested access to issue body
- Collision-free output from analyzer
- Template composition for the fix prompt

## Key Architectural Principle

The proxy mapping system is the **minimal viable solution** for making black-box nodes composable. It's not overengineering - it's the essential glue that makes pflow's vision of reusable workflows possible.

Without it, every workflow would need custom adapter nodes, defeating the entire purpose of pflow.

## What Success Looks Like

A successful implementation will:
- Make incompatible nodes work together seamlessly
- Keep nodes simple with natural interfaces
- Provide clear debugging through execution traces
- Add minimal complexity to the runtime
- Follow mappings exactly as specified in the IR

The proxy should be so simple that it's "obviously correct" - just a translator following instructions, nothing more.
