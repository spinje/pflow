# Nested Workflow Examples

This directory contains examples demonstrating the WorkflowNode feature, which allows workflows to execute other workflows as sub-components.

## Examples

### 1. Basic Nested Workflow (main-workflow.json)

Demonstrates basic workflow composition:
- Main workflow processes document title and body separately
- Uses `process-text.json` as a reusable sub-workflow
- Shows parameter mapping and output mapping
- Demonstrates sequential execution with edges

**Key features**:
- Loading workflows from files using `workflow_ref`
- Mapping parent values to child parameters
- Extracting specific outputs back to parent

### 2. Process Text Sub-Workflow (process-text.json)

A simple reusable workflow that can be called by other workflows:
- Takes text and mode as inputs
- Normalizes text based on the mode
- Can be reused with different parameters

### 3. Storage Isolation Example (isolated-processing.json)

Demonstrates different storage isolation modes:
- **Isolated mode**: Child workflow gets empty storage (no access to parent data)
- **Scoped mode**: Child sees filtered subset of parent storage
- **Error handling**: Custom error actions for failed sub-workflows

**Key features**:
- Inline workflow definition with `workflow_ir`
- Storage isolation for security
- Error action customization

## Running the Examples

```bash
# Run the main workflow example
pflow run examples/nested/main-workflow.json \
  --param document_title="Hello World" \
  --param document_body="This is the body text"

# Run with debug logging to see nested execution
pflow run examples/nested/main-workflow.json \
  --param document_title="Hello World" \
  --param document_body="This is the body text" \
  --debug
```

## Storage Modes Explained

1. **mapped** (default): Child only sees explicitly mapped parameters
2. **isolated**: Child gets completely empty storage
3. **scoped**: Child sees filtered view of parent storage with prefix
4. **shared**: Child uses same storage as parent (use with caution)

## Best Practices

1. Use `mapped` mode by default for safety
2. Keep nesting depth shallow (2-3 levels max)
3. Use descriptive workflow file names
4. Document expected inputs/outputs in metadata
5. Handle errors appropriately with custom error actions

## Advanced Usage

### Recursive Workflows

While possible, be careful with recursive workflows:
- Always set appropriate `max_depth`
- Ensure termination conditions
- Monitor resource usage

### Dynamic Workflow Selection

You can dynamically select workflows using template resolution:

```json
{
  "workflow_ref": "$workflow_path",
  "param_mapping": {
    "data": "$input_data"
  }
}
```

### Error Handling Patterns

Use custom error actions for graceful degradation:

```json
{
  "error_action": "use_fallback",
  "edges": [
    {"from": "workflow_node", "to": "primary_handler", "action": "default"},
    {"from": "workflow_node", "to": "fallback_handler", "action": "use_fallback"}
  ]
}
```
