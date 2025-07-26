# Template Validation Analysis

## The Problem

The current template validator uses heuristics to guess which variables come from `initial_params` vs `shared` store:
- Variables like `$content`, `$result` → assumes from shared store
- Other variables like `$input_file` → assumes from initial_params

But this is fundamentally flawed because:
1. The validator doesn't know what nodes write to shared store
2. Any variable name could come from either source
3. The heuristics can be wrong, causing false validation failures

## What We Actually Want to Validate

We want to ensure that when each node executes, all its required template variables will be resolvable from either:
1. `initial_params` (provided upfront)
2. Values written to `shared` store by previous nodes in the execution order

This is data flow analysis - tracking what data is available at each point in the workflow.

## Information Available

### In Workflow IR
- Node types and params (which may contain templates)
- Execution order (from edges)
- NO metadata about node inputs/outputs

### In Registry
- Raw docstrings containing Interface sections
- These specify what each node reads/writes from shared store

### In Metadata Extractor
- Can parse Interface sections to extract structured inputs/outputs
- Already used by context builder for the planner

## Options for Fixing Validation

### Option 1: Add Metadata to Workflow IR
When the planner generates a workflow, include node interface metadata:
```json
{
  "nodes": [{
    "id": "reader",
    "type": "read-file",
    "params": {"file_path": "$input_file"},
    "interface": {
      "reads": ["file_path", "encoding"],
      "writes": ["content"]
    }
  }]
}
```

**Pros:**
- Self-contained workflows
- Validator has all needed info
- No registry access needed

**Cons:**
- Duplicates metadata from docstrings
- Increases IR size
- Planner must add this data

### Option 2: Validator Accesses Registry
The validator looks up each node type and parses Interface metadata:
```python
def validate_templates(workflow_ir, initial_params, registry):
    for node in workflow_ir["nodes"]:
        metadata = registry.get_node_metadata(node["type"])
        interface = parse_interface(metadata["docstring"])
        # Use interface.writes to track shared store values
```

**Pros:**
- Single source of truth (docstrings)
- No IR changes needed
- Accurate validation

**Cons:**
- Validator needs registry dependency
- Slower (parsing docstrings)
- Complex implementation

### Option 3: Skip Shared Store Validation
Only validate that initial_params templates exist, assume nodes handle their own validation:
```python
def validate_templates(workflow_ir, initial_params):
    # Only check templates that look like CLI params
    # Ignore anything that might come from shared store
```

**Pros:**
- Simple implementation
- No false positives
- Fast

**Cons:**
- Less helpful error messages
- Can't detect some real errors
- Defeats purpose of validation

### Option 4: Runtime-Only Validation
Remove compile-time validation entirely, let nodes validate when they execute:
```python
# In compile_ir_to_flow
flow = compile_ir_to_flow(workflow, registry, initial_params)
# No validation here - nodes check their inputs during prep()
```

**Pros:**
- Most accurate
- Nodes already validate inputs
- No complex data flow analysis

**Cons:**
- Errors happen during execution
- Less user-friendly
- Can't preview issues

### Option 5: Two-Phase Validation
Validate what we can accurately, defer the rest:
```python
def validate_templates(workflow_ir, initial_params):
    # Phase 1: Check syntax of all templates
    # Phase 2: Validate only "obvious" CLI params
    # Skip ambiguous cases
```

**Pros:**
- Catches clear errors
- No false positives
- Simple implementation

**Cons:**
- Inconsistent validation
- Some errors slip through
- Still uses heuristics

## Revised Analysis: Simplified Option C

You're right - we can implement a simpler version of Option C that avoids complex data flow analysis while still providing accurate validation:

### Simplified Registry-Based Validation

1. **Build a set of all variables that will be written to shared store:**
   ```python
   written_vars = set()
   for node in workflow["nodes"]:
       metadata = registry.get_node_metadata(node["type"])
       interface = parse_interface(metadata)
       written_vars.update(interface["writes"])
   ```

2. **Validate that every template variable has a source:**
   ```python
   for template in all_templates:
       if template not in initial_params and template not in written_vars:
           errors.append(f"Template ${template} has no source")
   ```

This approach:
- **No execution order tracking** - just checks if SOME node writes each variable
- **No complex data flow** - simple set membership checking
- **Catches real errors** - like using `$api_config` when no node writes it
- **No false positives** - unlike current heuristics
- **Extensible** - can add data flow analysis later if needed

## Recommendation

For the MVP, I recommend **Simplified Option C: Registry-Based Validation without Data Flow**.

Reasoning:
1. The current heuristics cause false positives
2. Nodes already validate their inputs in `prep()`
3. The planner (Task 17) will ensure workflows are valid when generating them
4. A simpler validator is more maintainable

The validator would:
- Check template syntax is valid
- Verify all template variables in initial_params exist
- Ignore templates that might come from shared store
- Let nodes handle runtime validation

This aligns with the MVP philosophy: build minimal components that work correctly rather than complex ones that might fail.

## Future Enhancement (v2.0)

In v2.0, implement Option 1 where workflows include metadata:
```json
{
  "ir_version": "0.2.0",
  "metadata": {
    "inputs": ["input_file", "encoding"],  // Required from CLI/planner
    "outputs": ["processed_data"]          // Available after execution
  },
  "nodes": [...]
}
```

This enables precise validation without registry access or heuristics.
