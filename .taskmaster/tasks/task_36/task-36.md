# Task 36: Update Context Builder for Namespacing Clarity

## Description
Modify the context builder to present node information in a way that clearly reflects how nodes work with automatic namespacing enabled by default. Since nodes can no longer directly read from the shared store, the current "Inputs" terminology is misleading - all data must be passed via params using template variables.

## Status
done

## Completed
2025-08-18

## Dependencies
- Task 9: Automatic Namespacing - This task introduced namespacing which fundamentally changed how nodes access data, making direct shared store reads impossible
- Task 18: Template Variable System - Template variables are now the only way to pass data between nodes, making them critical to understand

## Priority
high

## Details
With automatic namespacing enabled by default (Task 9), nodes can no longer directly read inputs from the shared store. Instead, all data must be explicitly passed through the params field using template variables like `${node_id.output}`. However, the context builder still presents node information using the old mental model, showing "Inputs" as if nodes can read them directly from shared store.

### Current Problems
1. **Misleading "Inputs" section**: Suggests nodes can read these values from shared store directly
2. **Confusing "Parameters: none"**: For nodes without exclusive params, it shows "Parameters: none" even though ALL inputs must be passed as params
3. **Inconsistent presentation**: Some nodes show template usage examples, others don't
4. **Outdated terminology**: The distinction between "inputs" and "exclusive params" no longer makes sense with namespacing

### Proposed Solution
Update the context builder to:
1. **Rename "Inputs" to "Parameters"** - Make it clear everything goes in the params field
2. **Show ALL parameters together** - Don't separate "inputs" from "exclusive params"
3. **Always show usage examples** - Consistent JSON examples for every node
4. **Keep it factual** - No explanations in the context, just data structure

### Example of New Format
```markdown
### write-file
Write content to a file with automatic directory creation.

**Parameters** (all go in params field):
- `content: str` - Content to write to the file
- `file_path: str` - Path to the file to write
- `encoding: str` - File encoding (optional, default: utf-8)
- `append: bool` - Append to file instead of overwriting (default: false)

**Outputs**:
- `written: bool` - True if write succeeded
- `error: str` - Error message if operation failed

**Example usage**:
```json
{"id": "save", "type": "write-file", "params": {"content": "${process.result}", "file_path": "${output_file}"}}
```
```

### Implementation Approach
- Modify only `src/pflow/planning/context_builder.py`
- No changes to node code, schemas, or prompts needed
- Update the formatting functions to present clearer information
- Ensure all tests still pass with the new format

### Key Design Decision
We're choosing to make this change ONLY in the context builder rather than updating the entire system because:
- It's the translation layer between node metadata and LLM understanding
- Minimal risk - single file change
- Maximum clarity - solves the ambiguity completely
- Easy to test and verify

## Test Strategy
The testing approach will focus on verifying the context builder output is correct and that the planner can still generate valid workflows:

- **Unit tests**: Update existing context builder tests to expect the new format
- **Format verification**: Ensure all nodes show parameters consistently
- **Example validation**: Verify JSON examples are syntactically correct
- **Integration tests**: Confirm the planner still generates valid workflows with the new context format
- **Regression tests**: Ensure no existing functionality is broken by the format change

Key test scenarios:
- Nodes with only data inputs (like read-file)
- Nodes with data inputs and config params (like llm)
- Nodes with complex nested outputs
- Workflow generation with multiple same-type nodes (testing namespacing)
