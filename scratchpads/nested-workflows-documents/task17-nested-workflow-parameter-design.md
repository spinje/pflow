# Nested Workflow Parameter Passing Design

## Executive Summary

This document outlines the design for passing parameters from parent workflows to child workflows in pflow. The design leverages existing patterns from BatchFlow parameter passing and the template resolution system to create an intuitive and flexible parameter mapping mechanism.

## Current System Analysis

### 1. How node.set_params() Works

From the PocketFlow core (`pocketflow/__init__.py`):
```python
def set_params(self, params):
    self.params = params
```

- Simple attribute assignment on the node
- Called by Flow._orch() before node execution
- Parameters are available during prep(), exec(), and post() phases

### 2. Template Resolution System

The TemplateAwareNodeWrapper (`src/pflow/runtime/node_wrapper.py`):
- Wraps nodes that have template parameters
- Resolves templates at runtime using shared store + initial_params
- Priority: initial_params > shared store values
- Supports nested paths like `$api_config.endpoint.url`

### 3. Planner Parameter Extraction

The planner extracts parameters from natural language and passes them as `initial_params`:
```python
# From compiler.py
flow = compile_ir_to_flow(workflow_ir, registry, initial_params=initial_params)
```

These parameters are available to all nodes via template resolution.

### 4. BatchFlow Pattern

BatchFlow shows how to pass different parameters to each execution:
```python
class BatchFlow(Flow):
    def _run(self, shared):
        pr = self.prep(shared) or []  # Returns list of param dicts
        for bp in pr:
            self._orch(shared, {**self.params, **bp})  # Merge params
```

Key insight: Each batch iteration gets merged parameters (flow params + batch-specific params).

## Design for Nested Workflow Parameters

### Core Concepts

1. **Parameter Mapping**: Explicit mapping from parent values to child parameters
2. **Template Support**: Full template resolution in parameter mappings
3. **Isolation Options**: Control how child workflows access parent data
4. **Runtime Resolution**: Parameters resolved at execution time, not compile time

### WorkflowNode Design

```python
class WorkflowNode(Node):
    """Execute another workflow as a sub-workflow with parameter mapping."""

    def set_params(self, params: dict[str, Any]) -> None:
        """Set node parameters including workflow reference and mappings.

        Expected params structure:
        {
            "workflow_ref": "path/to/workflow.json",  # OR
            "workflow_ir": {...},  # Inline workflow definition

            "param_mapping": {
                # Map parent values to child initial_params
                "child_param1": "$parent_value",  # Template from shared store
                "child_param2": "static_value",    # Static value
                "child_param3": "$user.name",      # Nested template path
                "child_param4": {                  # Complex mapping
                    "api_key": "$config.api_key",
                    "endpoint": "$config.endpoint"
                }
            },

            "output_mapping": {
                # Map child outputs back to parent shared store
                "child_output": "parent_key",
                "result.status": "workflow_status"  # Nested child output
            },

            "storage_mode": "isolated"  # or "shared" or "scoped"
        }
        """
        super().set_params(params)
```

### Parameter Resolution Flow

1. **Parent Workflow Execution**:
   ```python
   # Parent has initial_params from planner
   parent_initial_params = {"user_id": "123", "api_key": "secret"}

   # Parent shared store during execution
   parent_shared = {
       "file_content": "data from previous node",
       "analysis": {"score": 0.8}
   }
   ```

2. **WorkflowNode Preparation**:
   ```python
   def prep(self, shared):
       # Load child workflow IR
       child_ir = self._load_workflow()

       # Resolve parameter mappings using template resolution
       child_initial_params = {}
       for child_key, parent_template in self.params["param_mapping"].items():
           if isinstance(parent_template, str) and "$" in parent_template:
               # Use TemplateResolver with parent context
               context = {**shared, **self.initial_params}
               child_initial_params[child_key] = TemplateResolver.resolve(
                   parent_template, context
               )
           else:
               # Static value or complex object
               child_initial_params[child_key] = parent_template

       return {
           "child_ir": child_ir,
           "child_initial_params": child_initial_params
       }
   ```

3. **Child Workflow Execution**:
   ```python
   def exec(self, prep_result):
       child_ir = prep_result["child_ir"]
       child_initial_params = prep_result["child_initial_params"]

       # Compile child workflow with resolved parameters
       child_flow = compile_ir_to_flow(
           child_ir,
           self.registry,
           initial_params=child_initial_params
       )

       # Create child storage based on mode
       child_shared = self._create_child_storage(self.params["storage_mode"])

       # Execute child workflow
       result = child_flow.run(child_shared)

       return {
           "result": result,
           "child_shared": child_shared
       }
   ```

### IR Schema for Nested Workflows

```json
{
  "nodes": [
    {
      "id": "analyze_issues",
      "type": "pflow.nodes.workflow",
      "params": {
        "workflow_ref": "workflows/github-issue-analyzer.json",
        "param_mapping": {
          // Simple template mapping
          "repo_name": "$repo",
          "issue_number": "$current_issue",

          // Static value
          "max_results": 10,

          // Nested template path
          "api_token": "$github.access_token",

          // Complex object mapping
          "config": {
            "timeout": 30,
            "retry": "$settings.retry_count"
          }
        },
        "output_mapping": {
          // Map child outputs to parent shared store
          "analysis_result": "issue_analysis",
          "metrics.severity": "severity_score"
        },
        "storage_mode": "isolated"
      }
    }
  ]
}
```

### Storage Modes

1. **Isolated** (Default - Recommended):
   ```python
   # Child gets empty shared store
   # Only sees values passed via param_mapping
   child_shared = {}
   ```

2. **Scoped** (Advanced):
   ```python
   # Child gets filtered view of parent storage
   # Only keys matching a prefix or filter
   child_shared = {
       k: v for k, v in parent_shared.items()
       if k.startswith("child_")
   }
   ```

3. **Shared** (Dangerous - Not Recommended for MVP):
   ```python
   # Child uses same shared store as parent
   # Can read/write all parent data
   child_shared = parent_shared
   ```

### Template Variable Support

The parameter mapping fully supports template syntax:

```json
{
  "param_mapping": {
    // Simple variable
    "input_file": "$file_path",

    // Nested path
    "api_key": "$config.api.key",

    // Array index (if supported by TemplateResolver)
    "first_item": "$items[0]",

    // Multiple templates in one string
    "message": "Processing $file_name from $user_name",

    // Conditional (future enhancement)
    "mode": "$debug ? 'verbose' : 'normal'"
  }
}
```

### Validation at Compile Time

The compiler should validate parameter compatibility:

1. **Template Validation**:
   - Ensure template variables will be available
   - Check if paths are valid (when possible)
   - Warn about potential runtime resolution failures

2. **Type Checking** (Future):
   - Validate parameter types match child workflow expectations
   - Ensure required parameters are mapped
   - Check output mapping targets exist

### Example Use Cases

#### 1. Simple Parameter Passing
```json
{
  "param_mapping": {
    "file_to_process": "$input_file",
    "output_format": "json"
  }
}
```

#### 2. Configuration Inheritance
```json
{
  "param_mapping": {
    "api_config": {
      "base_url": "$config.api_base",
      "timeout": "$config.timeout",
      "retry": 3
    }
  }
}
```

#### 3. Dynamic Parameter Generation
```json
{
  "param_mapping": {
    "search_query": "$user_input",
    "limit": "$advanced_mode ? 100 : 10",
    "filters": "$search_filters"
  }
}
```

#### 4. Batch Processing Pattern
```python
# Parent workflow could iterate over items
for item in items:
    workflow_node.set_params({
        "param_mapping": {
            "item_id": item["id"],
            "item_data": item["data"]
        }
    })
    workflow_node.run(shared)
```

## Implementation Roadmap

### Phase 1: Basic Parameter Mapping
1. Implement WorkflowNode with simple param_mapping
2. Support static values and basic templates
3. Isolated storage mode only
4. Basic output mapping

### Phase 2: Advanced Templates
1. Full template resolution support
2. Nested path resolution
3. Complex object mapping
4. Better error messages for resolution failures

### Phase 3: Validation & Safety
1. Compile-time parameter validation
2. Template dependency checking
3. Scoped storage mode
4. Parameter type checking

### Phase 4: Advanced Features
1. Conditional parameter mapping
2. Parameter transformation functions
3. Shared storage mode (with safety guards)
4. Dynamic parameter generation

## Design Decisions

1. **Explicit Mapping Required**: No automatic parameter inheritance to avoid confusion
2. **Template-First**: Leverage existing template system for maximum flexibility
3. **Isolated by Default**: Safer default that prevents accidental data pollution
4. **Runtime Resolution**: Parameters resolved at execution time for dynamic workflows
5. **Familiar Syntax**: Use same template syntax as regular nodes

## Security Considerations

1. **Path Traversal**: Validate workflow_ref paths to prevent directory traversal
2. **Resource Limits**: Prevent infinite recursion with depth limits
3. **Parameter Injection**: Sanitize template resolution to prevent code injection
4. **Storage Isolation**: Default to isolated storage to prevent data leaks

## Performance Considerations

1. **Workflow Caching**: Cache compiled child workflows for reuse
2. **Template Resolution**: Optimize template resolver for nested workflows
3. **Storage Cloning**: Efficient storage isolation without deep copying
4. **Lazy Loading**: Only load child workflows when needed

## Migration Path

For existing BatchFlow-like patterns:
1. Convert batch iterations to WorkflowNode with param_mapping
2. Each iteration becomes a child workflow execution
3. Preserve same parameter merging semantics

## Conclusion

This design provides a flexible, intuitive system for passing parameters to nested workflows while maintaining safety and predictability. It leverages existing patterns (templates, parameter resolution) that users already understand, making it easy to adopt.
