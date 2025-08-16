# Nested Workflows Guide

This guide explains how to use nested workflows to compose workflows from other workflows, enabling modular and reusable workflow design.

> **Note**: Workflow execution is handled internally by the pflow runtime using the WorkflowExecutor component. Users simply specify `type: "workflow"` in their workflow definitions and the runtime handles the execution details.

## Overview

Nested workflows allow you to execute other workflows as sub-components. This enables:
- **Modular Design**: Break complex workflows into smaller, reusable pieces
- **Code Reuse**: Share common workflow patterns across projects
- **Isolation**: Run sub-workflows with controlled data access
- **Composition**: Build sophisticated workflows from simple building blocks

## When to Use Nested Workflows

Use nested workflows when you need to:
- Reuse a common sequence of operations across multiple workflows
- Isolate certain operations from the main workflow's data
- Create libraries of workflow components
- Organize complex workflows into manageable pieces
- Implement conditional sub-workflows based on runtime decisions

## Basic Usage

### Loading Workflow from File

The most common pattern is loading a workflow from a JSON file:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "validate",
      "type": "workflow",
      "params": {
        "workflow_ref": "common/validation.json",
        "param_mapping": {
          "data": "${input_data}",
          "rules": "${validation_rules}"
        },
        "output_mapping": {
          "is_valid": "validation_result",
          "errors": "validation_errors"
        }
      }
    }
  ]
}
```

### Inline Workflow Definition

For simple cases, define the workflow inline:

```json
{
  "id": "process",
  "type": "workflow",
  "params": {
    "workflow_ir": {
      "ir_version": "0.1.0",
      "nodes": [
        {
          "id": "transform",
          "type": "text_transform",
          "params": {"operation": "uppercase"}
        }
      ]
    },
    "param_mapping": {
      "text": "${input_text}"
    }
  }
}
```

## Parameter Mapping

### Input Mapping

Map parent workflow values to child workflow parameters:

```json
{
  "param_mapping": {
    "child_param1": "${parent_value}",
    "child_param2": "${parent.nested.value}",
    "child_param3": "static_value"
  }
}
```

Features:
- Template resolution with `${variable}` syntax
- Nested path access with dot notation
- Static values without templates
- Missing values resolve to empty strings

### Output Mapping

Extract specific values from child workflow back to parent:

```json
{
  "output_mapping": {
    "child_result": "parent_result",
    "child_metrics.score": "quality_score"
  }
}
```

Only mapped outputs are copied back to parent (except in "shared" storage mode).

## Storage Isolation Strategies

### Mapped Mode (Default)

Child only sees explicitly mapped parameters:

```json
{
  "storage_mode": "mapped",
  "param_mapping": {
    "allowed_data": "${sensitive_data}"
  }
  // Child cannot access other parent data
}
```

**Use when**: You want precise control over what data the child can access.

### Isolated Mode

Child gets completely empty storage:

```json
{
  "storage_mode": "isolated"
  // Child starts with no data at all
}
```

**Use when**: Running untrusted workflows or ensuring complete isolation.

### Scoped Mode

Child sees filtered subset of parent storage:

```json
{
  "storage_mode": "scoped",
  "scope_prefix": "child_",
  // Child sees: child_data → data, child_config → config
  // But not: parent_secret, other_data
}
```

**Use when**: Working with namespaced data structures.

### Shared Mode

Child uses same storage as parent (dangerous):

```json
{
  "storage_mode": "shared"
  // Child can read/write ALL parent data
}
```

**Use when**: Child workflow is trusted and needs full access. Use sparingly!

## Error Handling

### Custom Error Actions

Control what happens when child workflow fails:

```json
{
  "error_action": "skip",  // Instead of default "error"
  // Parent workflow continues with "skip" action
}
```

### Error Context

Errors include full execution context:

```
Workflow execution failed at analyzers/sentiment.json: Compilation failed
Workflow path: main.json -> processor.json -> analyzer.json
Original error: Node 'undefined_node' not found in registry
```

## Advanced Patterns

### Conditional Sub-Workflows

Use edges to conditionally execute workflows:

```json
{
  "nodes": [
    {
      "id": "check_type",
      "type": "check_data_type"
    },
    {
      "id": "process_json",
      "type": "workflow",
      "params": {
        "workflow_ref": "processors/json.json"
      }
    },
    {
      "id": "process_xml",
      "type": "workflow",
      "params": {
        "workflow_ref": "processors/xml.json"
      }
    }
  ],
  "edges": [
    {"from": "check_type", "to": "process_json", "action": "json"},
    {"from": "check_type", "to": "process_xml", "action": "xml"}
  ]
}
```

### Workflow Libraries

Organize reusable workflows:

```
workflows/
├── common/
│   ├── validation.json
│   ├── authentication.json
│   └── error_handling.json
├── processors/
│   ├── text_analysis.json
│   ├── data_transform.json
│   └── api_integration.json
└── main_workflows/
    ├── user_pipeline.json
    └── batch_processor.json
```

### Dynamic Workflow Selection

Select workflow based on runtime data:

```json
{
  "nodes": [
    {
      "id": "select_analyzer",
      "type": "template_eval",
      "params": {
        "template": "analyzers/${language_analyzer.json}"
      }
    },
    {
      "id": "analyze",
      "type": "workflow",
      "params": {
        "workflow_ref": "${analyzer_path}"
      }
    }
  ]
}
```

## Best Practices

### 1. Keep Nesting Shallow

Limit nesting to 2-3 levels for maintainability:
- ❌ main → process → validate → transform → normalize
- ✅ main → process → validate

### 2. Document Interfaces

Child workflows should clearly document expected inputs:

```json
{
  "metadata": {
    "description": "Validates user data against rules",
    "inputs": {
      "data": "User data object to validate",
      "rules": "Validation rules specification"
    },
    "outputs": {
      "is_valid": "Boolean validation result",
      "errors": "Array of validation errors"
    }
  }
}
```

### 3. Use Appropriate Storage Modes

- Default to "mapped" for safety
- Use "isolated" for untrusted workflows
- Reserve "shared" for special cases
- Consider "scoped" for namespace organization

### 4. Handle Errors Gracefully

Always consider what happens if child workflow fails:

```json
{
  "nodes": [
    {
      "id": "try_process",
      "type": "workflow",
      "params": {
        "workflow_ref": "process.json",
        "error_action": "fallback"
      }
    },
    {
      "id": "fallback_process",
      "type": "simple_processor"
    }
  ],
  "edges": [
    {"from": "try_process", "to": "success", "action": "default"},
    {"from": "try_process", "to": "fallback_process", "action": "fallback"}
  ]
}
```

### 5. Version Your Workflows

Include version metadata for compatibility:

```json
{
  "ir_version": "0.1.0",
  "metadata": {
    "workflow_version": "2.0.0",
    "compatible_with": "^2.0.0"
  }
}
```

## Security Considerations

1. **Path Traversal**: The runtime validates workflow paths to prevent accessing files outside intended directories
2. **Circular Dependencies**: Automatically detected and prevented
3. **Resource Limits**: Configure max_depth to prevent stack exhaustion
4. **Data Isolation**: Use appropriate storage_mode for your security requirements
5. **Reserved Keys**: System keys with `_pflow_` prefix are managed securely

## Troubleshooting

### Common Issues

**"Circular workflow reference detected"**
- Check for workflows that reference each other in a cycle
- Use workflow execution stack in error message to trace the cycle

**"Maximum workflow nesting depth exceeded"**
- Reduce nesting levels or increase max_depth parameter
- Consider flattening workflow structure

**"Failed to compile sub-workflow"**
- Verify workflow_ref path is correct
- Check child workflow JSON syntax
- Ensure all referenced nodes exist in registry

**Parameter not passed to child**
- Verify parameter name in param_mapping
- Check template syntax (needs $ prefix)
- Ensure source value exists in parent

## Examples

### Example 1: Data Processing Pipeline

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "fetch",
      "type": "fetch_data",
      "params": {"source": "api"}
    },
    {
      "id": "validate",
      "type": "workflow",
      "params": {
        "workflow_ref": "validators/api_response.json",
        "param_mapping": {
          "response": "${api_data}"
        },
        "error_action": "invalid_data"
      }
    },
    {
      "id": "transform",
      "type": "workflow",
      "params": {
        "workflow_ref": "transformers/normalize.json",
        "param_mapping": {
          "raw_data": "${api_data}"
        },
        "output_mapping": {
          "normalized": "processed_data"
        }
      }
    }
  ],
  "edges": [
    {"from": "fetch", "to": "validate"},
    {"from": "validate", "to": "transform", "action": "default"}
  ]
}
```

### Example 2: Multi-Environment Deployment

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "deploy_dev",
      "type": "workflow",
      "params": {
        "workflow_ref": "deploy/environment.json",
        "param_mapping": {
          "env": "development",
          "config": "${dev_config}"
        },
        "storage_mode": "isolated"
      }
    },
    {
      "id": "deploy_staging",
      "type": "workflow",
      "params": {
        "workflow_ref": "deploy/environment.json",
        "param_mapping": {
          "env": "staging",
          "config": "${staging_config}"
        },
        "storage_mode": "isolated"
      }
    }
  ],
  "edges": [
    {"from": "deploy_dev", "to": "deploy_staging", "action": "default"}
  ]
}
```

## Related Documentation

- [Runtime Components](../architecture/runtime-components.md) - Understanding runtime infrastructure
- [Shared Store Pattern](../core-concepts/shared-store.md) - Understanding data flow
- [Workflow Schemas](../core-concepts/schemas.md) - JSON IR format
- [Simple Nodes](simple-nodes.md) - Building workflow components
