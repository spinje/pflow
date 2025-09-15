# Workflow Generation Retry Instructions

The workflow shown above failed validation. Review the errors and generate a corrected version.

## Your Task

1. **Analyze the validation errors** listed above
2. **Identify what needs to be fixed** in the workflow
3. **Generate a corrected workflow** that addresses all errors
4. **Maintain everything that was correct** in the previous attempt

## Common Validation Errors and Fixes

### Template Variable Errors
- **Error**: "Input 'param_name' declared but never used as template variable"
- **Fix**: Use `${param_name}` in the appropriate node's params
- **Example**: If you have an input `file_path`, use it as `"file_path": "${file_path}"` in a node

### Input Format Errors
- **Error**: "Input 'param_name' is not of type 'object'"
- **Fix**: Convert string inputs to proper objects with type, description, required
- **Wrong**: `"file_path": "Path to file"`
- **Right**: `"file_path": {"type": "string", "description": "Path to file", "required": true}`

### Node Reference Errors
- **Error**: "Node 'node_id' not found in registry"
- **Fix**: Use the correct node type from available components
- **Check**: The node type must match exactly what's in the registry

### Missing Required Fields
- **Error**: "Node missing required field 'purpose'"
- **Fix**: Add the missing field to the node
- **Example**: `"purpose": "Clear description of what this node does"`

### Parameter/Input Errors
- **Error**: "Missing required input: param_name"
- **Fix**: Add ALL discovered parameters as inputs (check context for full list)
- **Error**: "Unknown parameter 'reviewer' in workflow"
- **Fix**: Remove invented parameters - use ONLY discovered parameters
- **Error**: "Declared input(s) never used as template variable"
- **Fix**: Ensure every input is used with ${param_name} in at least one node

### Edge/Flow Errors
- **Error**: "Node has multiple outgoing edges"
- **Fix**: Ensure sequential execution - each node connects to only one next node
- **Error**: "Unreachable nodes detected"
- **Fix**: Ensure all nodes are connected in the flow

### Schema Errors
- **Error**: "Additional properties are not allowed ('name', 'description' were unexpected)"
- **Fix**: Remove extra fields from workflow root - stick to the exact schema

## Important Reminders

1. **Keep what works**: Don't change parts that were correct
2. **Fix only the errors**: Focus on the specific validation issues
3. **Maintain the plan**: The overall execution plan should remain the same
4. **Follow the Workflow System Overview**: Refer to the overview above for:
   - Proper input format (objects with type/description/required)
   - Template variable rules (user inputs vs node outputs)
   - Sequential execution constraints
5. **Use template variables**: Every declared input must be used

## Task

Generate the corrected JSON workflow that fixes all validation errors while maintaining the correct structure and logic from the previous attempt.