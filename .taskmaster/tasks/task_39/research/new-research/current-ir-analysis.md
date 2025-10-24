# Current pflow IR Schema Analysis

**Purpose**: Understanding the current JSON IR schema to inform branching and parallel execution design.

**Date**: 2025-01-23

---

## 1. Current IR Schema Structure

### Core Schema (from `ir_schema.py`)

```json
{
  "ir_version": "0.1.0",              // Required - semantic version
  "nodes": [...],                     // Required - array of node definitions
  "edges": [...],                     // Optional - array of connections
  "start_node": "node-id",            // Optional - defaults to first node
  "mappings": {...},                  // Optional - proxy mappings
  "inputs": {...},                    // Optional - workflow input declarations
  "outputs": {...},                   // Optional - workflow output declarations
  "enable_namespacing": true,         // Optional - default true
  "template_resolution_mode": "strict" // Optional - "strict" or "permissive"
}
```

### Node Structure

```json
{
  "id": "unique-id",        // Required - unique within workflow
  "type": "node-type",      // Required - references registry
  "purpose": "description", // Optional - human-readable description
  "params": {               // Optional - node configuration
    "key": "value",
    "template": "${variable}"  // Template variables supported
  }
}
```

### Edge Structure

```json
{
  "from": "source-node-id",  // Required - source node
  "to": "target-node-id",    // Required - target node
  "action": "default"        // Optional - conditional routing (default: "default")
}
```

---

## 2. Current Node Connection Model

### Sequential Execution (Default)

Nodes are connected in a **linear chain** by default:

```json
{
  "nodes": [
    {"id": "read", "type": "read-file", ...},
    {"id": "process", "type": "llm", ...},
    {"id": "write", "type": "write-file", ...}
  ],
  "edges": [
    {"from": "read", "to": "process"},
    {"from": "process", "to": "write"}
  ]
}
```

**Execution**: `read` → `process` → `write` (sequential)

### Conditional Branching (Action-Based)

Nodes can branch based on **action strings** returned by nodes:

```json
{
  "nodes": [
    {"id": "validate", "type": "llm", ...},
    {"id": "success_handler", "type": "write-file", ...},
    {"id": "error_handler", "type": "write-file", ...}
  ],
  "edges": [
    {"from": "validate", "to": "success_handler"},
    {"from": "validate", "to": "error_handler", "action": "error"}
  ]
}
```

**Execution**:
- If `validate` returns "default" → `success_handler`
- If `validate` returns "error" → `error_handler`

**Key Properties**:
- **One edge per action**: Each action string determines next node
- **Compiler support**: `_wire_nodes()` in `compiler.py:745-809` handles this
- **PocketFlow native**: Uses `node - "action" >> next_node` syntax

---

## 3. Compilation Process (from `compiler.py`)

### Compilation Pipeline (11 steps)

```
1. Parse IR (JSON → dict)
2. Validate structure
3. Validate inputs
4. Validate outputs
5. Validate templates
6. Instantiate nodes (with wrappers)
7. Wire nodes (create connections)
8. Get start node
9. Create Flow object
10. Wrap flow.run for output population
11. Return executable Flow
```

### Node Wiring (`_wire_nodes()` - lines 745-809)

```python
for edge in edges:
    source = nodes[edge["from"]]
    target = nodes[edge["to"]]
    action = edge.get("action", "default")

    if action == "default":
        source >> target           # Sequential
    else:
        source - action >> target  # Conditional
```

**Critical Insight**: All connections are **1:1** - each edge connects one source to one target.

---

## 4. Design Principles (from documentation)

### From `ir_schema.py` docstring:

1. **'type' vs 'registry_id'**: Uses 'type' for simplicity (MVP)
2. **Nodes as array**: Preserves order, simplifies duplicate detection
3. **Optional start_node**: Defaults to first node
4. **Action-based routing**: Conditional flow control via action strings

### From PocketFlow framework:

1. **`>>` operator**: Sequential chaining
2. **`-` operator**: Action-based routing (`node - "action" >> next`)
3. **Shared store**: All communication through `shared[key]`
4. **Execution model**: Nodes return action strings to determine next node

---

## 5. Current Limitations for Branching/Parallel

### No Built-In Support For:

1. **Multiple simultaneous branches**
   - Current: One action → one next node
   - Needed: One node → multiple nodes (fan-out)

2. **Parallel execution**
   - Current: Sequential-only execution
   - Needed: Concurrent node execution

3. **Join/merge operations**
   - Current: No way to wait for multiple nodes
   - Needed: Multiple nodes → one node (fan-in)

4. **Conditional multi-way branching**
   - Current: One condition → one branch
   - Needed: Multiple conditions → multiple branches

### What Works Today (via action strings):

```
     ┌──────────┐
     │  Node A  │
     └────┬─────┘
          │
    ┌─────┴──────┐
    │  "default" │
    │  "error"   │
    └─────┬──────┘
          │
     ┌────▼─────┐
     │  Node B  │  (if action == "default")
     └──────────┘

     ┌──────────┐
     │  Node C  │  (if action == "error")
     └──────────┘
```

**Problem**: Can't execute both B and C simultaneously, or based on data content.

---

## 6. JSON Example Patterns

### Simple Sequential

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "n1", "type": "read-file", "params": {"path": "input.txt"}},
    {"id": "n2", "type": "write-file", "params": {"path": "output.txt"}}
  ],
  "edges": [
    {"from": "n1", "to": "n2"}
  ]
}
```

### Conditional Error Handling

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "process", "type": "llm", ...},
    {"id": "save", "type": "write-file", ...},
    {"id": "log_error", "type": "write-file", ...}
  ],
  "edges": [
    {"from": "process", "to": "save"},
    {"from": "process", "to": "log_error", "action": "error"}
  ]
}
```

### Complex Multi-Branch (github-workflow.json)

```json
{
  "edges": [
    {"from": "fetch_commits", "to": "generate_changelog"},
    {"from": "read_version", "to": "create_release_notes"},
    {"from": "generate_changelog", "to": "create_release_notes"},
    {"from": "create_tag", "to": "rollback", "action": "error"}
  ]
}
```

**Pattern**: Multiple sources can target same node (fan-in)
**Limitation**: All execution is still sequential - no parallelism

---

## 7. Template Variable System

### Current Support (from `template_resolver.py`)

**Syntax**: `${variable}`, `${data.user.name}`, `${items[0].title}`

**Resolution Priority**:
1. `initial_params` (from planner)
2. Shared store (runtime data)
3. Workflow inputs

**Type Preservation**:
- Simple templates (`${var}`) preserve type (int, bool, None, dict, list)
- Complex templates (`"Hello ${name}"`) always return strings

**Example**:
```json
{
  "id": "llm",
  "type": "llm",
  "params": {
    "prompt": "Summarize: ${fetch.result}",
    "model": "${model_name}",
    "max_tokens": "${max_tokens}"
  }
}
```

---

## 8. Namespacing System

### Automatic Collision Prevention

**Enabled by default** (`enable_namespacing: true`)

**Behavior**:
- Writes: `shared[node_id][key]` (namespaced)
- Reads: Check both `shared[node_id][key]` and `shared[key]` (root)
- Special keys (`__*__`) bypass namespacing

**Example**:
```
Node A writes: shared["output"] = "A's data"
→ Actually stored: shared["node_a"]["output"] = "A's data"

Node B reads: ${node_a.output}
→ Resolves to: shared["node_a"]["output"]
```

---

## 9. Key Constraints for Design

### Must Maintain:

1. **Backward compatibility**: Existing workflows must still work
2. **PocketFlow compatibility**: Extensions must use valid PocketFlow patterns
3. **JSON-first**: IR must be human-readable and editable
4. **Template support**: `${variable}` resolution must work in all contexts
5. **Validation**: All new constructs must be validatable pre-execution

### Can Extend:

1. **Edge structure**: Add new optional fields
2. **Node properties**: Add new optional fields
3. **IR top-level fields**: Add new optional sections
4. **Action strings**: Define new semantic actions

---

## 10. Potential Extension Points

### Option 1: Extend Edge Structure

Add optional fields to edges:
```json
{
  "from": "source",
  "to": "target",
  "action": "default",
  "parallel": true,        // NEW: Execute target in parallel
  "condition": "${check}"  // NEW: Conditional execution
}
```

### Option 2: Add Parallel Section

New top-level construct:
```json
{
  "ir_version": "0.1.0",
  "nodes": [...],
  "edges": [...],
  "parallel_groups": [    // NEW: Groups of nodes to run in parallel
    {
      "id": "fetch_all",
      "nodes": ["fetch_a", "fetch_b", "fetch_c"],
      "join": "process"
    }
  ]
}
```

### Option 3: Add Special Node Types

Use synthetic nodes:
```json
{
  "id": "parallel_split",
  "type": "pflow.runtime.ParallelSplit",
  "params": {
    "branches": ["branch_a", "branch_b", "branch_c"]
  }
}
```

---

## 11. Compilation Compatibility Analysis

### What Would Need Changes:

1. **`_wire_nodes()`** (compiler.py:745-809)
   - Currently: 1 edge = 1 connection
   - Needed: Handle parallel edges, conditional edges

2. **`_get_start_node()`** (compiler.py:812-863)
   - Currently: Returns single start node
   - Needed: Might return multiple start nodes for parallel entry

3. **`validate_ir_structure()`** (workflow_validator.py)
   - Currently: Validates sequential structure
   - Needed: Validate parallel groups, merge points

4. **`build_execution_order()`** (workflow_data_flow.py)
   - Currently: Topological sort for linear order
   - Needed: Support parallel execution levels

### What Would Stay The Same:

1. **Template resolution**: Works at parameter level, independent of flow structure
2. **Namespacing**: Works at shared store level, independent of execution order
3. **Node instantiation**: Each node still instantiated individually
4. **Wrapper chain**: Template/namespace/instrumentation wrappers unchanged

---

## 12. PocketFlow Framework Limitations

### Current PocketFlow Support:

```python
# Sequential
node_a >> node_b >> node_c

# Conditional
node_a - "error" >> error_handler
node_a >> success_handler

# Join (via shared store)
node_a >> merger
node_b >> merger
# merger reads from both node_a and node_b outputs
```

### What PocketFlow DOESN'T Have:

1. **Built-in parallel execution**: No `Flow.run_parallel()`
2. **Explicit join operations**: No `Flow.join([node_a, node_b])`
3. **Barrier synchronization**: No waiting for multiple nodes

### What Would Need Custom Implementation:

```python
# Parallel execution (would need custom Flow wrapper)
parallel_flow = ParallelFlow([node_a, node_b, node_c])

# Join/merge (would need custom node or wrapper)
join_node = JoinNode(wait_for=["node_a", "node_b"])
```

---

## 13. Key Findings Summary

### ✅ Current Strengths:

1. **Clean IR structure**: Simple, JSON-based, human-readable
2. **Action-based routing**: Already supports conditional branching
3. **Template system**: Robust variable resolution
4. **Validation pipeline**: Comprehensive pre-execution checks
5. **Wrapper architecture**: Modular, extensible

### ⚠️ Current Limitations:

1. **No parallel execution**: All execution is sequential
2. **No explicit fan-out/fan-in**: Can't declaratively specify parallel branches
3. **No barrier sync**: Can't wait for multiple nodes to complete
4. **PocketFlow constraints**: Framework doesn't have parallel primitives

### 🎯 Design Requirements:

1. **Backward compatible**: Existing workflows must work unchanged
2. **Declarative**: Parallelism specified in IR, not in node logic
3. **Validatable**: Can detect invalid parallel structures pre-execution
4. **Template-aware**: Templates must resolve correctly in parallel contexts
5. **Efficient**: Don't pay cost for parallelism if not using it

---

## Next Steps

1. **Review PocketFlow async capabilities** (pocketflow/__init__.py)
2. **Evaluate parallel execution strategies** (threads vs async vs process)
3. **Design IR extensions** (backward compatible additions)
4. **Prototype validation logic** (detect invalid parallel structures)
5. **Plan compilation changes** (minimal modifications to compiler.py)
