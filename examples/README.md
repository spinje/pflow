# pflow IR Examples

This directory contains comprehensive examples of pflow's JSON Intermediate Representation (IR) format. These examples demonstrate various workflow patterns and help you understand how to create your own workflows.

## Quick Start

1. **Validate an example**:
```python
from pflow.core import validate_ir
import json

with open('core/minimal.json') as f:
    ir = json.load(f)
    validate_ir(ir)  # Raises ValidationError if invalid
```

2. **Learn from examples**: Each `.json` file has a corresponding `.md` file explaining its purpose and patterns.

3. **Start simple**: Begin with `core/minimal.json` and work your way up to advanced examples.

## Directory Structure

### 📁 core/
Essential examples showing fundamental patterns:

- **minimal.json** - Simplest valid IR (single node)
- **simple-pipeline.json** - Basic 3-node pipeline with edges
- **template-variables.json** - Using `$variable` syntax for dynamic workflows
- **error-handling.json** - Action-based routing for error recovery
- **proxy-mappings.json** - NodeAwareSharedStore interface adaptation

### 📁 advanced/
Complex real-world examples:

- **github-workflow.json** - Automated GitHub issue resolution with LLM
- **content-pipeline.json** - Multi-stage content generation with revision loops

### 📁 invalid/
Examples of common mistakes and their error messages:

- **missing-version.json** - Missing required `ir_version` field
- **duplicate-ids.json** - Multiple nodes with same ID
- **bad-edge-ref.json** - Edge referencing non-existent node
- **wrong-types.json** - Incorrect data types for fields

## Common Patterns

### 1. Sequential Pipeline
```json
"edges": [
  {"from": "step1", "to": "step2"},
  {"from": "step2", "to": "step3"}
]
```

### 2. Error Handling
```json
"edges": [
  {"from": "risky_op", "to": "success_handler"},
  {"from": "risky_op", "to": "error_handler", "action": "error"}
]
```

### 3. Template Variables
```json
"params": {
  "url": "$api_endpoint",
  "token": "$auth_token"
}
```

### 4. Proxy Mappings
```json
"mappings": {
  "node_id": {
    "input_mappings": {"expected_key": "actual_key"},
    "output_mappings": {"node_output": "shared_key"}
  }
}
```

## Validation Tips

1. **Always validate**: Use `validate_ir()` before attempting to execute
2. **Check error paths**: The `ValidationError` includes path and suggestions
3. **Start minimal**: Begin with few nodes and add complexity gradually
4. **Test incrementally**: Validate after each change

## Creating Your Own Workflows

1. **Define your nodes**: List the operations needed
2. **Map the flow**: Draw connections between nodes
3. **Add parameters**: Configure each node's behavior
4. **Handle errors**: Add error paths where operations might fail
5. **Use templates**: Make workflows reusable with variables

## Advanced Features

### Action-Based Routing
Nodes can have multiple exit paths based on execution results:
- `"action": "error"` - When node fails
- `"action": "retry"` - Custom retry logic
- `"action": "needs_revision"` - Conditional loops

### Start Node
By default, execution begins with the first node in the array. Override with:
```json
"start_node": "custom_start_id"
```

### Node Types
Node types map to registered implementations. Common types:
- I/O: `read-file`, `write-file`, `http-get`
- Transform: `json-extract`, `template-render`
- LLM: `llm-analyzer`, `llm-writer`
- Control: `conditional`, `loop`, `parallel`

## Testing Your IR

Create a test file to validate all your workflows:

```python
# test_workflows.py
import json
import glob
from pflow.core import validate_ir, ValidationError

for ir_file in glob.glob("workflows/*.json"):
    with open(ir_file) as f:
        try:
            ir = json.load(f)
            validate_ir(ir)
            print(f"✓ {ir_file}")
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"✗ {ir_file}: {e}")
```

## Next Steps

1. Study the examples to understand patterns
2. Modify examples for your use case
3. Create custom workflows
4. Contribute your examples back to the community

For more information, see the main pflow documentation.
