# Workflow Outputs Gap Analysis

## The Asymmetry Problem

Task 21 adds **input** declarations to workflow IR:
```json
{
  "inputs": {
    "issue_number": {"required": true, "type": "string"}
  },
  "nodes": [...]
}
```

But there's no corresponding **output** declaration in the IR schema!

## Current State

### Where Outputs Live Now

1. **Nodes**: Have outputs in registry interface
   ```python
   interface["outputs"] = [
     {"key": "issue_data", "type": "dict", "structure": {...}}
   ]
   ```

2. **Workflows**: Have outputs in metadata (not IR)
   ```json
   {
     "metadata": {
       "outputs": {
         "normalized_text": "The normalized text result"
       }
     }
   }
   ```

### The Problems This Creates

1. **No Validation**: Can't verify workflows actually produce declared outputs
2. **No Structure Info**: Unlike nodes, workflow outputs lack type/structure
3. **Template Validation Fails**: Can't validate `$workflow_result.field` paths
4. **Poor Composition**: Can't match workflow A outputs to workflow B inputs

## Why This Matters for Task 17

The planner needs to understand workflow interfaces completely:

```python
# Planner wants to compose workflows:
# 1. "fix-issue" workflow outputs: pr_url, pr_number
# 2. "notify-team" workflow inputs: message, url

# Can these compose? Without output declarations, we can't know!
```

## The Missing Piece

Task 21 should probably include output declarations too:

```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "issue_number": {
      "description": "GitHub issue to fix",
      "required": true,
      "type": "string"
    }
  },
  "outputs": {  // THIS IS MISSING!
    "pr_url": {
      "description": "URL of created pull request",
      "type": "string"
    },
    "pr_number": {
      "description": "Number of created pull request",
      "type": "number"
    }
  },
  "nodes": [...]
}
```

## Benefits of Output Declarations

1. **Discovery**: Find workflows that produce specific data
2. **Composition**: Match outputs to inputs automatically
3. **Validation**: Verify workflows produce what they claim
4. **Documentation**: Self-documenting workflow contracts
5. **Template Validation**: Enable `$workflow_output.field` validation

## Impact on Architecture

### With Input+Output Declarations:
- Workflows become true composable components
- Clear contracts for both consumption and production
- Enable automated workflow composition
- Better tooling and discovery

### Current State (Input Only):
- Half a contract - know what goes in, not what comes out
- Can't validate workflow composition
- Template validation incomplete
- Discovery limited

## Questions

1. Should Task 21 be expanded to include outputs?
2. Or should outputs be a separate task?
3. How do we validate that declared outputs are actually produced?
4. Should output structure be as detailed as node outputs?

## Recommendation

Task 21 should be expanded to "Implement Workflow Input/Output Declaration" because:
- Inputs and outputs form a complete interface
- Both are needed for composition
- Similar implementation patterns
- Avoids doing half the work now, half later

Without output declarations, the planner can't effectively compose workflows because it doesn't know what data they produce.
