# Shared Store + Proxy Design Pattern in pflow

## Overview

This document defines a core architectural principle in `pflow`: the coordination of logic and memory through a **shared store** with an optional **proxy layer** that enables standalone, reusable nodes without imposing binding complexity on node writers.

This pattern is implemented using the lightweight **pocketflow framework** (100 lines of Python), leveraging its existing `params` system and flow orchestration capabilities.

## Shared Store vs Params Guidelines

Before diving into the autonomy principle, it's crucial to understand when to use shared store vs params:

### Use Shared Store When:
- **Data flows between nodes**: Input/output data that transforms through the pipeline
- **Content is dynamic**: User inputs, API responses, generated content
- **Data has workflow-level significance**: Core data the workflow operates on

### Use Params When:
- **Configuration is static**: Model selection, API endpoints, retry policies
- **Settings are node-specific**: Temperature, max_tokens, file formats
- **Values are operational**: How the node operates, not what it operates on

### Best Practice Pattern:
```python
def prep(self, shared):
    # Check shared store first (dynamic), then params (static)
    value = shared.get("key") or self.params.get("key")
    if not value:
        raise ValueError("key must be in shared store or params")
    return value
```

**Shared store takes precedence** - this allows dynamic workflow data to override static configuration when needed.

## Template Variable Resolution

Template variables (`$variable`) provide dynamic content substitution in node inputs, enabling sophisticated data flow between nodes:

### Template String Pattern
```bash
# Template string with $variable in CLI
claude-code --prompt="<instructions>
                        1. Understand the problem described in the issue
                        2. Search the codebase for relevant files
                        3. Implement the necessary changes to fix the issue
                        4. Write and run tests to verify the fix
                        5. Return a report of what you have done as output
                      </instructions>
                      This is the issue: $issue"

# At runtime: $issue → shared["issue"] (from github-get-issue node output)
claude-code --prompt="<instructions>...This is the issue: Button component touch events not working properly on mobile devices"
```

### Context-Aware CLI Resolution

The CLI intelligently routes different types of flags:

- **Data flags** (workflow data) → shared store: `--issue=1234` → `shared["issue_number"] = "1234"`
- **Behavior flags** (node configuration) → node parameters: `--temperature=0.3` → `node.set_params({"temperature": 0.3})`
- **Template variables** (dynamic content) → shared store at runtime: `$code_report` → `shared["code_report"]`

### Variable Dependency Flow

Template variables create dependencies between nodes:

```bash
# $issue depends on github-get-issue output
github-get-issue --issue=1234 >>  # Outputs: shared["issue"], shared["issue_title"]
claude-code --prompt="...This is the issue: $issue" >>  # Depends on: shared["issue"]
llm --prompt="Write commit message for: $code_report" >>  # Depends on: shared["code_report"]
git-commit --message="$commit_message"  # Depends on: shared["commit_message"]
```

### Missing Input Handling

When required inputs are missing (typically for first nodes expecting user input):

```bash
# User runs: pflow fix-issue
# Planner detects missing --issue flag for github-get-issue node
# Prompts user: "Please provide --issue=<issue_number> for github-get-issue"
# User provides: pflow fix-issue --issue=1234
# Continues with: shared["issue_number"] = "1234"
```

This ensures all node inputs are populated before execution begins.

## Node Autonomy Principle

The fundamental insight is that **node writers shouldn't need to understand flow orchestration concepts**. They should write simple, testable business logic using natural key names, while flow designers handle mapping complexity at the orchestration level.

### Key Benefits

1. **Standalone Node Development** - Node writers use intuitive keys (`shared["text"]`)
2. **Simplified Testing** - Natural test setup with direct key access
3. **Better Separation of Concerns** - Nodes focus on logic, flows handle routing
4. **Reduced Cognitive Load** - Node writers focus on their domain expertise
5. **More Readable Code** - `shared["text"]` beats `self.params["input_bindings"]["text"]`

### Node Isolation and "Dumb Pipes" Philosophy

**Core Isolation Principle:**
Nodes are **dumb pipes** - isolated computation units with no awareness of other nodes or flow context.

**Node Isolation Rules:**
- **No peer awareness**: Nodes cannot inspect or reference other nodes
- **No flow introspection**: Nodes don't know their position in flow topology
- **No conditional execution**: Nodes cannot skip or modify execution based on peer behavior
- **Single responsibility**: Each node performs one well-defined transformation

**Prohibited Inter-Node Dependencies:**
```python
# WRONG: Node aware of other nodes
class BadNode(Node):
    def exec(self, prep_res):
        if "previous_node_failed" in shared:
            return "skip"  # DON'T DO THIS

# RIGHT: Flow-level conditional logic
validator - "failed" >> error_handler
validator - "success" >> processor
```

**Benefits of Isolation:**
- **Composability**: Nodes work in any flow context
- **Testability**: Nodes tested independently
- **Reusability**: Same node used across different flows
- **Debugging**: Clear responsibility boundaries
- **Modularity**: Flow-level control over execution paths

**Conditional Logic Location:**
All conditional execution belongs at the **flow level** through action-based transitions, never within node internals.

## Node Design Constraints

### Control Flow Isolation
Nodes must not implement complex dynamic control flow internally. All conditional logic, loops, and branching should be expressed at the flow level through action-based transitions.

**Prohibited Patterns:**
- Internal loops with dynamic exit conditions
- Conditional branching based on shared store inspection
- Dynamic routing logic within node execution

**Correct Pattern:**
```python
# WRONG: Control flow in node
class BadNode(Node):
    def exec(self, prep_res):
        while not condition_met():
            result = process_data()
            if should_branch():
                return "special_path"
        return "default"

# RIGHT: Control flow at flow level
node_a >> validator
validator - "retry_needed" >> processor >> validator
validator - "complete" >> finalizer
```

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

### 3. Params (Flat Structure)

- **Params** (`params: Dict[str, Any]`) stored directly in `self.params` (flat structure)
- Node-local parameters that don't affect shared store
- Simple access via `self.params.get("temperature", 0.7)`

## Integration with pocketflow Framework

Our pattern leverages the existing **pocketflow framework** which provides:

- **Node base class**: `prep()`/`exec()`/`post()` execution pattern
- **Params system**: `set_params()` method for node parameters
- **Flow orchestration**: `>>` operator for wiring nodes
- **Minimal overhead**: 100-line implementation with proven patterns

Node classes inherit from `pocketflow.Node` and access params through the simplified `self.params` dictionary.

> **See also**: [pocketflow documentation](../pocketflow/docs/core_abstraction/communication.md) for framework details

## The Standalone Node Pattern

The core innovation is **standalone nodes**: nodes are generic and reusable because they use natural, intuitive interfaces. Instead of binding complexity:

- **Nodes use natural keys** — `shared["text"]`, `shared["summary"]`
- **Proxy handles routing** — transparent mapping when needed for compatibility
- **Params are simple** — flat structure accessible via `self.params.get("key")`

Each node is written to:

1. **Use natural interfaces** via direct shared store access (`shared["text"]`)
2. **Access params simply** via `self.params.get("key", default)`
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
- **Runtime**: CLI injection into shared store and params overrides

### Node Example (Static - Written Once)

```python
class LLMNode(Node):  # Inherits from pocketflow.Node
    """General-purpose LLM processing.

    Interface:
    - Reads: shared["prompt"] - prompt to send to LLM
    - Writes: shared["response"] - LLM's response
    - Params: model (default gpt-4), temperature (default 0.7), system
    """
    def prep(self, shared):
        # Best practice: check shared store first, then params
        prompt = shared.get("prompt") or self.params.get("prompt")
        if not prompt:
            raise ValueError("prompt must be in shared store or params")
        return prompt

    def exec(self, prep_res):
        return call_llm(
            prompt=prep_res,
            model=self.params.get("model", "gpt-4"),
            temperature=self.params.get("temperature", 0.7),
            system=self.params.get("system")
        )

    def post(self, shared, prep_res, exec_res):
        shared["response"] = exec_res  # Direct assignment
```

## Node Testing Simplicity

The proxy pattern makes testing intuitive and natural:

```python
def test_llm_node():
    node = LLMNode()
    node.set_params({"model": "gpt-4", "temperature": 0.5})  # Just params

    # Natural, intuitive shared store
    shared = {"prompt": "Summarize this: Long article content here..."}

    node.run(shared)

    assert "response" in shared
    assert len(shared["response"]) > 0
```

Compare this to complex binding setup requirements in other approaches.

## Progressive Complexity Examples

### Level 1 - Simple Flow (Direct Access)

```python
# No mappings needed - nodes access shared store directly
shared = {"prompt": "Summarize this content: Input content"}

llm_node = LLMNode()
llm_node.set_params({"model": "gpt-4", "temperature": 0.7})

flow = Flow(start=llm_node)
flow.run(shared)  # Node accesses shared["prompt"] directly
```

### Level 2 - Complex Flow (Proxy Mapping)

```python
# Marketplace compatibility - proxy maps keys transparently
shared = {"raw_transcript": "Input content"}  # Flow schema

# Generated flow code handles proxy creation
if "mappings" in ir and llm_node.id in ir["mappings"]:
    mappings = ir["mappings"][llm_node.id]
    proxy = NodeAwareSharedStore(
        shared,
        input_mappings={"prompt": "formatted_prompt"},  # Built from transcript
        output_mappings={"response": "summary"}
    )
    llm_node._run(proxy)  # Node still uses shared["prompt"]
else:
    llm_node._run(shared)  # Direct access
```

**Same node code works at both levels.**

### Flow Example (Generated from IR)

**Flow A** (Simple - Direct Access):

```python
# Generated flow code (from IR)
llm_node = LLMNode()

# Set params from IR
llm_node.set_params({
    "model": "gpt-4",
    "temperature": 0.3  # Conservative for academic content
})

# Wire the flow using pocketflow operators
flow = Flow(start=llm_node)
```

**Flow B** (Complex - With Proxy Mapping):

```python
# Same static node class, different generated flow
llm_node = LLMNode()  # Same node class!

# Set params from IR
llm_node.set_params({
    "model": "claude-3-opus",
    "temperature": 0.8  # More creative for informal content
})

# Generated proxy setup for marketplace compatibility
if llm_node.id in ir["mappings"]:
    proxy = NodeAwareSharedStore(
        shared,
        input_mappings={"prompt": "formatted_prompt"},  # Built from transcript
        output_mappings={"response": "output/video_summary"}
    )
    llm_node._run(proxy)
else:
    llm_node._run(shared)
```

The same `LLMNode` class works in completely different contexts with different shared store schemas.

## Shared Store Namespacing

**Future Feature**: Path-like keys enable organized, collision-free shared store layouts:

**Key**: `"raw_texts/doc1.txt"`
**Maps to**:

```python
shared = {
    "raw_texts": {
        "doc1.txt": "Some input content"
    }
}
```

> **Note**: MVP implementation focuses on flat key structure. Nested namespacing will be supported in future versions for the proxy pattern.

**Benefits**:

- **Namespacing**: Clear organization of related data
- **Collision avoidance**: `"inputs/doc1.txt"` vs `"outputs/doc1.txt"`
- **Debugging**: Easy to trace data flow through nested structure
- **Modularity**: Subflows can own their namespace

## Intermediate Representation (IR)

To enable agents to plan, inspect, mutate, and reason about flows without directly generating or editing Python code, `pflow` uses a structured JSON-based intermediate representation (IR).

The IR defines:

- The node graph (nodes, types, identifiers)
- Parameters for each node
- Mapping definitions for complex flows (when needed)
- Transitions between nodes

Example:

```json
{
  "nodes": [
    {
      "id": "llm",
      "params": {"model": "gpt-4", "temperature": 0.7}
    },
    {
      "id": "write-file",
      "params": {"format": "markdown"}
    }
  ],
  "edges": [
    {"from": "llm", "to": "write-file"}
  ],
  "mappings": {
    "llm": {
      "input_mappings": {"prompt": "formatted_prompt"},
      "output_mappings": {"response": "content"}
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

### Cognitive Traceability Benefits

The round-trip cognitive architecture enhances developer experience through description-driven flow management:

**Intent Preservation:**
- Every flow carries natural language description reflecting original intent
- Descriptions enable rediscovery of flows by purpose, not just structure
- LLM-powered flow matching based on semantic similarity

**Reusability Enhancement:**
- Flows serve as discoverable components for new compositions
- Natural language descriptions enable intuitive flow search
- Proven flows become building blocks for complex workflows

**Educational Transparency:**
- Flow descriptions explain purpose and context
- Users can understand flow intent without reading implementation details
- Supports progressive learning from simple to complex compositions

## Benefits

### Reusability

- Nodes can be written once and reused in any flow
- They use natural interfaces that are self-documenting
- Same node, different proxy mapping = different behavior in different contexts

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

### Educational Design Philosophy

This pattern enables **progressive user empowerment** by making flow orchestration transparent and modifiable:

**Learning Scaffolding:**
- Natural interfaces make node behavior intuitive and discoverable
- CLI pipe syntax reveals flow structure before execution
- Proxy mappings demonstrate advanced composition techniques
- Shared store pattern teaches data flow principles

**Skill Development Pathway:**
1. **Natural Language Users**: Express intent, learn from generated structures
2. **CLI Pipe Authors**: Write simple flows, understand data flow
3. **Advanced Composers**: Use proxy mappings for complex orchestration
4. **Node Developers**: Create reusable components with natural interfaces

**Educational Transparency:**
- Every abstraction level remains visible and modifiable
- No hidden magic prevents learning
- Complexity introduced progressively as users advance
- System knowledge becomes user knowledge over time

## See Also

> **For complete CLI usage, validation rules, and runtime parameter details**, see [Shared-Store & Proxy Model — CLI Runtime Specification](./shared-store-cli-runtime-specification.md)
