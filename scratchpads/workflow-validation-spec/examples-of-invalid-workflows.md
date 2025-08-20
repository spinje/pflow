# Examples of Invalid Workflows

This document shows real examples of invalid workflow files that the validation system should catch.

## Example 1: Missing Metadata Wrapper (The Original Issue)

**File**: `test-suite.json`

### Invalid Version (What caused the incident)
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "test_name": {
      "description": "Name of the test being run",
      "type": "string",
      "required": false,
      "default": "pflow-test"
    }
  },
  "nodes": [
    {
      "id": "start",
      "type": "echo",
      "params": {
        "message": "Starting test: ${test_name}"
      }
    }
  ],
  "edges": []
}
```

**Problem**: This is just the IR without the metadata wrapper.

**Error Message**:
```
WARNING: Skipping invalid workflow 'test-suite.json': Missing required field 'name'; Missing required field 'ir'
```

### Valid Version
```json
{
  "name": "test-suite",
  "description": "Test workflow for validation",
  "ir": {
    "ir_version": "0.1.0",
    "inputs": {
      "test_name": {
        "description": "Name of the test being run",
        "type": "string",
        "required": false,
        "default": "pflow-test"
      }
    },
    "nodes": [
      {
        "id": "start",
        "type": "echo",
        "params": {
          "message": "Starting test: ${test_name}"
        }
      }
    ],
    "edges": []
  },
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",
  "version": "1.0.0"
}
```

## Example 2: Missing Name Field

### Invalid
```json
{
  "description": "A workflow without a name",
  "ir": {
    "ir_version": "0.1.0",
    "nodes": [
      {
        "id": "hello",
        "type": "echo",
        "params": {"message": "Hello"}
      }
    ]
  }
}
```

**Error Message**:
```
WARNING: Skipping invalid workflow 'unnamed.json': Missing required field 'name'
```

## Example 3: Empty Name

### Invalid
```json
{
  "name": "",
  "description": "Workflow with empty name",
  "ir": {
    "ir_version": "0.1.0",
    "nodes": [{"id": "test", "type": "echo"}]
  }
}
```

**Error Message**:
```
WARNING: Skipping invalid workflow 'empty-name.json': Field 'name' must be a non-empty string
```

## Example 4: Wrong Type for Name

### Invalid
```json
{
  "name": 123,
  "description": "Name is a number instead of string",
  "ir": {
    "ir_version": "0.1.0",
    "nodes": [{"id": "test", "type": "echo"}]
  }
}
```

**Error Message**:
```
WARNING: Skipping invalid workflow 'wrong-type.json': Field 'name' must be a non-empty string
```

## Example 5: Invalid Characters in Name

### Invalid
```json
{
  "name": "my/workflow",
  "description": "Name contains invalid filesystem characters",
  "ir": {
    "ir_version": "0.1.0",
    "nodes": [{"id": "test", "type": "echo"}]
  }
}
```

**Error Message**:
```
WARNING: Skipping invalid workflow 'invalid-chars.json': Field 'name' contains invalid characters: ['/']
```

## Example 6: Missing IR Field

### Invalid
```json
{
  "name": "no-ir-workflow",
  "description": "This workflow has no IR field"
}
```

**Error Message**:
```
WARNING: Skipping invalid workflow 'no-ir.json': Missing required field 'ir'
```

## Example 7: IR is Not an Object

### Invalid
```json
{
  "name": "bad-ir-type",
  "description": "IR is a string instead of object",
  "ir": "not an object"
}
```

**Error Message**:
```
WARNING: Skipping invalid workflow 'bad-ir-type.json': Field 'ir' must be an object
```

## Example 8: Corrupted JSON

### Invalid
```json
{
  "name": "corrupted",
  "description": "This JSON is not valid"
  "ir": {
    "ir_version": "0.1.0"
  }
}
```
Note: Missing comma after "description" line

**Error Message**:
```
WARNING: Skipping invalid workflow 'corrupted.json': Invalid JSON: Expecting ',' delimiter: line 3 column 3
```

## Example 9: Root is Not an Object

### Invalid
```json
[
  {
    "name": "array-root",
    "ir": {}
  }
]
```

**Error Message**:
```
WARNING: Skipping invalid workflow 'array-root.json': Root must be an object
```

## Example 10: Null Name

### Invalid
```json
{
  "name": null,
  "description": "Name is null",
  "ir": {
    "ir_version": "0.1.0",
    "nodes": []
  }
}
```

**Error Message**:
```
WARNING: Skipping invalid workflow 'null-name.json': Field 'name' must be a non-empty string
```

## Example 11: Whitespace-Only Name

### Invalid
```json
{
  "name": "   ",
  "description": "Name is only whitespace",
  "ir": {
    "ir_version": "0.1.0",
    "nodes": []
  }
}
```

**Error Message**:
```
WARNING: Skipping invalid workflow 'whitespace-name.json': Field 'name' must be a non-empty string
```

## Example 12: Invalid IR Structure (Level 3 Validation)

### Invalid (when IR validation is enabled)
```json
{
  "name": "invalid-ir",
  "description": "IR structure is invalid",
  "ir": {
    "nodes": [
      {
        "id": "start",
        "type": "echo"
      }
    ]
  }
}
```

Note: Missing required `ir_version` in IR

**Error Message** (with IR validation enabled):
```
WARNING: Skipping invalid workflow 'invalid-ir.json': Invalid IR: Missing required field 'ir_version'
```

## Example 13: Complex Invalid Scenario

### Invalid
```json
{
  "name": "test|workflow*",
  "description": 123,
  "ir": {
    "ir_version": "0.1.0",
    "nodes": "should be array"
  },
  "created_at": "not-a-timestamp"
}
```

**Multiple Problems**:
1. Name contains invalid characters (|, *)
2. Description is wrong type (not critical, won't fail)
3. IR structure is invalid (would fail Level 3 validation)

**Error Message**:
```
WARNING: Skipping invalid workflow 'complex-invalid.json': Field 'name' contains invalid characters: ['|', '*']
```

## How These Examples Help

These examples demonstrate:

1. **Common user errors**: Missing wrapper, empty names, wrong types
2. **Filesystem issues**: Invalid characters that would prevent saving
3. **Data corruption**: Malformed JSON, partial files
4. **Type confusion**: Numbers/nulls where strings expected
5. **Structural issues**: Missing required fields, wrong nesting

## Testing Approach

Create a test that loops through these examples:

```python
def test_all_invalid_examples(workflow_manager):
    """Test validation catches all documented invalid examples."""

    invalid_examples = {
        "no_wrapper.json": {
            "ir_version": "0.1.0",
            "nodes": []
        },
        "no_name.json": {
            "ir": {}
        },
        "empty_name.json": {
            "name": "",
            "ir": {}
        },
        # ... etc
    }

    # Create all invalid files
    for filename, content in invalid_examples.items():
        file_path = workflow_manager.workflows_dir / filename
        with open(file_path, "w") as f:
            json.dump(content, f)

    # None should be loaded
    workflows = workflow_manager.list_all()
    assert len(workflows) == 0

    # Each should fail load() with appropriate error
    for filename in invalid_examples:
        name = filename.replace(".json", "")
        with pytest.raises(WorkflowValidationError):
            workflow_manager.load(name)
```

## User Recovery Guide

When users encounter these errors, here's how to fix them:

### Missing wrapper?
Wrap your IR in a metadata structure:
```json
{
  "name": "your-workflow-name",
  "description": "What this workflow does",
  "ir": { /* your existing content */ },
  "created_at": "2024-01-01T00:00:00Z",
  "version": "1.0.0"
}
```

### Invalid characters in name?
Remove these characters from the name field: / \ : * ? " < > |

### Missing name?
Add a `"name": "workflow-name"` field at the root level

### Wrong type?
Ensure `name` is a string and `ir` is an object

### Corrupted JSON?
Use a JSON validator to find and fix syntax errors