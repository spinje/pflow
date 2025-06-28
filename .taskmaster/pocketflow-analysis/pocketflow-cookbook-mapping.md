# PocketFlow Cookbook to pflow Implementation Mapping

This document maps specific PocketFlow cookbook examples to pflow implementation needs, providing a quick reference for which examples to study for each implementation task.

## Implementation Pattern to Cookbook Mapping

### 1. Basic Node Implementation Pattern
**Used in**: Tasks 11-14, 26-28 (all simple platform nodes)

**Primary Examples**:
- `pocketflow-node.ipynb` - Core node implementation pattern
- `pocketflow-file.ipynb` - File operations (directly applicable to Task 11)

**Key Patterns to Extract**:
- Node class structure with `prep()`, `exec()`, `post()` methods
- Accessing shared store via `self.get("key")` and `self.set("key", value)`
- Error handling within node execution
- Parameter handling via `set_params()`

### 2. LLM Integration Pattern
**Used in**: Task 12 (general LLM node), Task 25 (claude-code node)

**Primary Examples**:
- `pocketflow-chat.ipynb` - Chat-based LLM interaction
- `pocketflow-llm.ipynb` - General LLM patterns
- `pocketflow-agent.ipynb` - Complex agent patterns (for Task 25)

**Key Patterns to Extract**:
- Prompt construction from shared store data
- API response handling and parsing
- Token usage tracking
- Multi-step reasoning (agent pattern)

### 3. Flow Construction Pattern
**Used in**: Task 3 (Hello World), Task 4 (IR-to-Flow converter)

**Primary Examples**:
- `pocketflow-hello-world.ipynb` - Simplest flow pattern
- `pocketflow-flow.ipynb` - Flow construction details
- `pocketflow-tutorial.ipynb` - Step-by-step flow building

**Key Patterns to Extract**:
- Using `>>` operator to connect nodes
- Setting start node with `flow.set_start("node_name")`
- Running flow with `flow.run(shared)`
- Dynamic flow construction from configuration

### 4. Shared Store Proxy Pattern
**Used in**: Task 9 (collision detection and proxy)

**Primary Examples**:
- `pocketflow-proxy.ipynb` - Proxy pattern implementation
- Review `communication.md` for conceptual understanding

**Key Patterns to Extract**:
- Creating proxy wrapper around shared store
- Key mapping/remapping strategies
- Transparent access patterns
- Collision detection logic

### 5. Tool/External Service Pattern
**Used in**: Tasks 13-14 (GitHub/Git nodes), Tasks 26-28 (additional tools)

**Primary Examples**:
- `pocketflow-tool.ipynb` - External tool integration
- Look for examples with subprocess or API calls

**Key Patterns to Extract**:
- Calling external commands from `exec()`
- API integration patterns
- Error handling for external failures
- Output parsing and storage

### 6. Workflow Patterns
**Used in**: Understanding overall flow design

**Primary Examples**:
- `pocketflow-workflow.ipynb` - Workflow design patterns
- RAG and Map-Reduce examples for advanced patterns

**Key Patterns to Extract**:
- Common workflow structures
- Error handling strategies
- Data flow patterns between nodes

## Quick Reference by Task

| Task ID | Task Name | Primary Cookbook Examples | Secondary Examples |
|---------|-----------|-------------------------|-------------------|
| 3 | Hello World Workflow | `pocketflow-hello-world.ipynb` | `pocketflow-tutorial.ipynb` |
| 4 | IR-to-Flow Converter | `pocketflow-flow.ipynb` | Review Flow class in `__init__.py` |
| 9 | Shared Store Proxy | `pocketflow-proxy.ipynb` | `communication.md` docs |
| 11 | File I/O Nodes | `pocketflow-file.ipynb` | `pocketflow-node.ipynb` |
| 12 | LLM Node | `pocketflow-llm.ipynb` | `pocketflow-chat.ipynb` |
| 13 | GitHub Issue Node | `pocketflow-tool.ipynb` | API integration examples |
| 14 | Git Commit Node | `pocketflow-tool.ipynb` | Command execution examples |
| 25 | Claude-Code Node | `pocketflow-agent.ipynb` | Complex multi-step examples |

## Implementation Tips from Cookbook

### 1. Node Implementation Checklist
Based on cookbook patterns, every node should:
- [ ] Inherit from `BaseNode` (imported from pocketflow)
- [ ] Implement `exec()` method (required)
- [ ] Optionally implement `prep()` and `post()` methods
- [ ] Use `self.get()` and `self.set()` for shared store access
- [ ] Handle missing required inputs with clear errors
- [ ] Document interface in docstring

### 2. Flow Construction Checklist
When building flows dynamically:
- [ ] Create Flow instance: `flow = Flow()`
- [ ] Add nodes: `flow.add_node("name", node_instance)`
- [ ] Connect with edges: `flow >> "node1" >> "node2"`
- [ ] Set start node: `flow.set_start("first_node")`
- [ ] Run with shared store: `flow.run(shared_dict)`

### 3. Shared Store Best Practices
From cookbook examples:
- Always check if keys exist before accessing
- Use descriptive key names (not just "data")
- Document expected keys in node docstring
- Clean up temporary keys in `post()` if needed
- Consider namespace prefixes for complex flows

### 4. Error Handling Patterns
Common patterns across cookbook:
- Fail fast with clear messages for missing inputs
- Log warnings for non-critical issues
- Use try/except in `exec()` for external calls
- Return meaningful error states to shared store

## Study Priority for MVP

**Essential** (Study First):
1. `pocketflow/__init__.py` - Core framework understanding
2. `pocketflow-node.ipynb` - Basic node pattern
3. `pocketflow-hello-world.ipynb` - Simple flow pattern
4. `pocketflow-file.ipynb` - File operations pattern

**Important** (Study for Specific Tasks):
1. `pocketflow-llm.ipynb` - For LLM integration
2. `pocketflow-proxy.ipynb` - For shared store proxy
3. `pocketflow-tool.ipynb` - For external tools
4. `pocketflow-flow.ipynb` - For dynamic flow building

**Advanced** (Study as Needed):
1. `pocketflow-agent.ipynb` - For complex claude-code node
2. Workflow patterns - For understanding design
3. RAG/Map-Reduce - For future advanced features
