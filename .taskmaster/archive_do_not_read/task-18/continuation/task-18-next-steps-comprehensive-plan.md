# Task 18 Template System: Next Steps and Integration Plan

## CRITICAL: Task 18 is COMPLETE

**IMPORTANT**: The template variable system (Task 18) is FULLY IMPLEMENTED and TESTED. All code is written, all tests pass. DO NOT modify the core implementation unless fixing bugs.

## Immediate Next Steps

### 1. Run Full Test Suite to Verify No Regressions
```bash
# Run all pflow tests to ensure template system doesn't break anything
make test

# Specifically check runtime tests
uv run python -m pytest tests/test_runtime/ -v

# Check if any existing integration tests need template support
uv run python -m pytest tests/test_integration/ -v
```

### 2. Create Simple Manual Test Workflow
Create a test workflow to manually verify the system works end-to-end:

```python
# test_templates.py
from pflow.runtime.compiler import compile_ir_to_flow
from pflow.registry import Registry

# Test IR with templates
test_ir = {
    "nodes": [
        {
            "id": "greet",
            "type": "test-node",  # You'll need a simple test node
            "params": {
                "message": "Hello $name from $location!",
                "count": "$iterations"
            }
        }
    ],
    "edges": []
}

# Compile with initial params
registry = Registry()
flow = compile_ir_to_flow(
    test_ir,
    registry,
    initial_params={"name": "Alice", "location": "NYC", "iterations": "5"}
)

# Run it
shared = {}
flow.run(shared)
print(shared)
```

### 3. Update Existing Integration Tests

Check these files for workflows that could benefit from templates:
- `tests/test_integration/test_e2e_workflow.py`
- `tests/test_integration/test_hello_world_flow.py`

Add test cases that use template variables to ensure integration works.

### 4. Documentation Updates Needed

Create/update these docs:
1. **User-facing documentation** in `architecture/features/template-variables.md`:
   - Explain template syntax (`$var`, `$var.field`)
   - Show examples of reusable workflows
   - Explain validation errors
   - Document limitations (strings only, no arrays)

2. **Update CLI reference** in `architecture/reference/cli-reference.md`:
   - Document how initial_params are passed
   - Show examples with templates

3. **Add to node development guide**:
   - Remind that nodes must use fallback pattern
   - Show template-aware workflow examples

## Integration Points to Verify

### 1. CLI Integration (When Planner is Ready)
The CLI will need to pass parameters from the planner:

```python
# In CLI main.py (conceptual - wait for planner)
def execute_natural_language(nl_input: str):
    # Planner extracts parameters
    planner_result = planner.plan(nl_input)

    # Pass to compiler
    flow = compile_ir_to_flow(
        planner_result["workflow_ir"],
        registry,
        initial_params=planner_result["parameter_values"]  # This is the key connection!
    )

    shared = {}
    flow.run(shared)
```

### 2. Direct Workflow Execution (v2.0 preview)
For saved workflows with templates:

```python
# Future v2.0 functionality
@click.command()
@click.option('--url', help='URL to process')
@click.option('--format', default='json', help='Output format')
def run_saved_workflow(url, format):
    # Load saved workflow with templates
    workflow = load_workflow("process-url")

    # Create initial_params from CLI args
    initial_params = {
        "url": url,
        "format": format
    }

    # Compile and run
    flow = compile_ir_to_flow(workflow, registry, initial_params)
```

## Testing Checklist

### Basic Functionality
- [ ] Simple variable resolution works
- [ ] Path-based resolution works
- [ ] Type conversion works as expected
- [ ] Validation catches missing params
- [ ] Unresolved templates remain visible

### Integration Testing
- [ ] Works with file nodes
- [ ] Works with multi-node workflows
- [ ] Errors propagate correctly
- [ ] Performance is acceptable

### Edge Cases
- [ ] Very long template paths
- [ ] Special characters in values
- [ ] Unicode in templates
- [ ] Empty string values
- [ ] Large parameter counts

## Potential Issues to Watch For

### 1. Performance with Many Templates
If a workflow has hundreds of templates, regex parsing might be slow. Monitor and optimize if needed.

### 2. Memory Usage
The wrapper creates copies of params. For very large param values, this could use significant memory.

### 3. Debugging Challenges
When templates don't resolve, users need clear feedback. Consider adding debug logging:

```python
# In template_resolver.py
logger.debug(f"Template ${var_name} resolved to: {value}")
logger.warning(f"Template ${var_name} could not be resolved")
```

### 4. Security Considerations
Templates could potentially expose sensitive data. Consider:
- Should certain variable names be restricted?
- Should we sanitize resolved values?
- Log redaction for sensitive params?

## Future Enhancements (Post-MVP)

### 1. Type Preservation
```python
# Future: Preserve types instead of converting to strings
"count": "$iterations"  # Could stay as int
```

### 2. Array Indexing
```python
# Future: Support array access
"first_item": "$items.0.name"
```

### 3. Default Values
```python
# Future: Fallback values
"name": "$username|Anonymous"
```

### 4. Expression Evaluation
```python
# Future: Simple expressions
"next_page": "$page + 1"
```

### 5. Template Functions
```python
# Future: Built-in functions
"title": "$name.upper()"
"slug": "$title.slugify()"
```

## Key Information for Future Development

### Understanding the Resolution Flow

1. **Planner Phase** (Task 17):
   - User says: "fix github issue 1234 in pflow repo"
   - Planner extracts: `{"issue_number": "1234", "repo": "pflow"}`

2. **Compilation Phase**:
   - Workflow has: `{"params": {"issue": "$issue_number"}}`
   - Validator ensures `issue_number` is available
   - Wrapper created for nodes with templates

3. **Runtime Phase**:
   - Node execution intercepted at `_run()`
   - Templates resolved from context (shared + initial_params)
   - Node sees resolved values: `{"issue": "1234"}`

### Critical Code Paths

1. **Template Detection**: `TemplateResolver.has_templates()` - O(1) check for '$'
2. **Variable Extraction**: `TemplateResolver.extract_variables()` - Regex findall
3. **Resolution**: `TemplateResolver.resolve_string()` - For each template, traverse path
4. **Validation**: `TemplateValidator.validate_workflow_templates()` - Before execution

### Design Rationale (Why These Choices)

1. **Why runtime resolution?** Values change during execution (shared store updates)
2. **Why string conversion?** Simplicity, covers 90% of use cases
3. **Why unresolved templates remain?** Debugging visibility
4. **Why wrapper pattern?** No modification to existing nodes needed
5. **Why initial_params priority?** User intent should override runtime data

## DO NOT FORGET

1. **The fallback pattern is CRITICAL** - Every node must implement it
2. **Templates only work in params** - Not in node IDs or types
3. **Validation is heuristic** - Not perfect at CLI vs shared detection
4. **Resolution is stateless** - No caching between executions
5. **Wrapper is transparent** - Nodes don't know they're wrapped

## Commands for Quick Testing

```bash
# Run template tests only
uv run python -m pytest tests/test_runtime/test_template* -v

# Check for any template strings in codebase
grep -r '\$[a-zA-Z_]' src/ --include="*.py"

# Run with debug logging
PFLOW_LOG_LEVEL=DEBUG uv run python -m pytest tests/test_runtime/test_template_resolver.py::test_name -s
```

## Final Reminders

1. **Task 18 is COMPLETE** - Don't reimplement unless fixing bugs
2. **Integration with Task 17** - Planner provides parameter_values
3. **Test with real nodes** - Not just mock nodes
4. **Document for users** - They need to understand template syntax
5. **Performance monitoring** - Watch for issues with large workflows

The template system is the bridge between static workflow definitions and dynamic execution. It's working and tested. Now it needs to be integrated with the planner and documented for users.
