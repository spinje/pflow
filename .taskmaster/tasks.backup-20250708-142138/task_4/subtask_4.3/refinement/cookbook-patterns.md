# Cookbook Patterns for Flow Construction

## Pattern 1: Basic Node Instantiation and Wiring
**From**: pocketflow-flow/flow.py
**Relevance**: Shows the fundamental pattern for creating and connecting nodes

```python
# Node instantiation is simple
input_node = InputNode()
llm_node = LLMNode()
output_node = OutputNode()

# Default connections use >>
input_node >> llm_node >> output_node

# Action-based routing uses -
llm_node - "error" >> error_handler
llm_node - "success" >> output_node

# Create flow with start node
flow = Flow(start=input_node)
```

**Key Insights**:
- Nodes are instantiated with no parameters to constructor
- Chaining with >> returns the target node (allows multiple >>)
- The - operator must be immediately followed by >>

## Pattern 2: Parameter Setting
**From**: pocketflow-batch-flow/batch_flow.py
**Relevance**: Shows how nodes access parameters via self.params

```python
class ConfigurableNode(Node):
    def exec(self, prep_res):
        # Nodes access params set by flow
        threshold = self.params.get("threshold", 0.5)
        model = self.params.get("model", "gpt-4")

# In our compiler:
node = NodeClass()
if params:
    node.set_params(params)  # This sets node.params
```

**Key Insights**:
- Parameters are configuration values, not shared store data
- Set via set_params() method, accessed via self.params
- Nodes should have defaults for missing params

## Pattern 3: Action-Based Flow Control
**From**: pocketflow-agent/flow.py
**Relevance**: Shows complex routing based on dynamic actions

```python
# Multiple paths from one node
decide_node - "search" >> search_node
decide_node - "compute" >> compute_node
decide_node - "done" >> output_node

# Loops are possible
search_node - "more" >> decide_node
search_node - "found" >> process_node
```

**Key Insights**:
- Actions are strings returned by node's post() method
- Can have multiple actions from one node
- Supports loops and complex flow patterns

## Pattern 4: Flow as Building Block
**From**: pocketflow-workflow/flow.py
**Relevance**: Shows flows can be nested

```python
# A flow can be used like a node
inner_flow = Flow(start=step1)
step1 >> step2 >> step3

# Use in larger flow
start >> inner_flow >> end
```

**Key Insights**:
- Flows inherit from BaseNode, can be used as nodes
- Useful for modular workflow composition
- Our compiler should handle Flow objects same as nodes

## Anti-Patterns to Avoid

### ❌ Don't Pass Parameters to Constructor
```python
# Wrong
node = MyNode(param1="value")

# Right
node = MyNode()
node.set_params({"param1": "value"})
```

### ❌ Don't Connect Before All Nodes Exist
```python
# Wrong - forward reference
node_a >> node_b  # node_b doesn't exist yet
node_b = NodeB()

# Right - create all nodes first
node_a = NodeA()
node_b = NodeB()
node_a >> node_b
```

### ❌ Don't Assume Node Order
```python
# Wrong - assuming nodes[0] is always start
start = nodes[0]

# Right - explicit logic
start_id = ir_dict.get("start_node", ir_dict["nodes"][0]["id"])
start = nodes[start_id]
```

## Testing Patterns

### Mock Node for Testing
```python
class MockNode:
    def __init__(self):
        self.params = None
        self.connections = []

    def set_params(self, params):
        self.params = params

    def __rshift__(self, other):
        self.connections.append(("default", other))
        return other

    def __sub__(self, action):
        return MockActionTransition(self, action)
```

This allows testing the wiring without real node implementations.
