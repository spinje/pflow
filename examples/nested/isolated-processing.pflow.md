# Isolated Processing

Demonstrate different storage isolation modes for nested workflow execution.
Shows isolated and scoped storage modes to control data visibility
between parent and child workflows.

## Steps

### prepare_data

Prepare data including sensitive and public values for processing.

- type: pflow.nodes.test_node
- sensitive_data: SECRET_KEY_123
- public_data: This is public

### isolated_process

Run a sub-workflow in isolated storage mode so it cannot access parent data.

- type: workflow
- storage_mode: isolated

```yaml workflow_ir
ir_version: "0.1.0"
nodes:
  - id: process
    type: pflow.nodes.test_node
    params:
      operation: process_isolated
edges: []
```

```yaml param_mapping
safe_input: ${public_data}
```

```yaml output_mapping
result: isolated_result
```

### scoped_process

Run a sub-workflow with scoped storage and a namespace prefix.

- type: workflow
- workflow_ref: ./process-text.pflow.md
- storage_mode: scoped
- scope_prefix: child_
- error_action: handle_error

```yaml param_mapping
text: ${child_data}
```
