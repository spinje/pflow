# Task 36: Problem Analysis - Context Builder with Namespacing

## The Fundamental Disconnect

### What Changed with Task 9 (Automatic Namespacing)

Before namespacing:
```python
# Node writes
shared["content"] = data

# Another node reads directly
content = shared.get("content")  # ✅ Works!
```

After namespacing (enabled by default):
```python
# Node writes (to its namespace)
shared["node1"]["content"] = data

# Another node tries to read
content = shared.get("content")  # ❌ Returns None!
# Must be passed via params instead:
content = self.params.get("content")  # Where content = "${node1.content}"
```

### The Mental Model Mismatch

The context builder presents nodes as if the OLD model still works:

```markdown
### write-file
**Inputs**:
- `content: str` - Content to write
```

This suggests the node reads `content` from the shared store. But it CAN'T anymore!

## Concrete Examples of Confusion

### Example 1: The "Parameters: none" Problem

**What the LLM sees:**
```markdown
### read-file
**Inputs**:
- `file_path: str` - Path to the file to read

**Parameters**: none
```

**What the LLM thinks:**
"This node has no parameters, it reads file_path from shared store"

**Reality with namespacing:**
The node REQUIRES file_path as a parameter:
```json
{"params": {"file_path": "${input_file}"}}
```

### Example 2: The Inconsistent Presentation

**Node with exclusive params:**
```markdown
### llm
**Inputs**: prompt, system
**Parameters**: model, temperature
**Template Variable Usage**: [JSON examples]
```

**Node without exclusive params:**
```markdown
### read-file
**Inputs**: file_path
**Parameters**: none
```

The LLM has to understand that:
- For `llm`: Pass prompt via params, also set model/temperature
- For `read-file`: Pass file_path via params (despite "Parameters: none")

This inconsistency is confusing!

### Example 3: The Template Variable Confusion

**Current template variable section:**
```markdown
**Template Variables**: Use ${variables} in params field for inputs:
- file_path: "${key}"
- content: "${key}"
```

What does `"${key}"` mean? This is unhelpful placeholder text!

## Real-World Impact

### Workflow Generation Errors

The LLM might generate:
```json
{
  "nodes": [
    {"id": "read", "type": "read-file"},  // ❌ No params!
    {"id": "write", "type": "write-file", "params": {"file_path": "out.txt"}}
  ]
}
```

Error: "Missing required 'file_path' in shared store or params"

Should be:
```json
{
  "nodes": [
    {"id": "read", "type": "read-file", "params": {"file_path": "${input_file}"}},
    {"id": "write", "type": "write-file", "params": {
      "content": "${read.content}",
      "file_path": "out.txt"
    }}
  ]
}
```

### The Planner's Confusion

From workflow_generator.md prompt:
```
7. Avoid multiple nodes of the same type (causes shared store collision)
```

But with namespacing, collisions are SOLVED! The prompt is outdated.

## Why "Exclusive Params" Made Sense (But Doesn't Anymore)

### Historical Context

The "exclusive params" pattern was designed when:
1. Nodes could read inputs from shared store
2. Params were for "extra" configuration
3. Showing params that duplicated inputs was redundant

Example thinking:
- `file_path` is an input (can read from shared store)
- `file_path` is also a param (can override from params)
- Don't show it twice, that's redundant!

### Why It's Wrong Now

With namespacing:
1. Nodes CAN'T read inputs from shared store directly
2. ALL inputs MUST come through params
3. The distinction is meaningless and confusing

The term "Inputs" now means "what the node expects in params", not "what it reads from shared store".

## The Source of Truth Problem

### What Node Metadata Says
```python
"interface": {
    "inputs": [
        {"key": "content", "type": "str", "description": "Content to write"}
    ]
},
"params": ["content", "file_path", "append"]
```

### Multiple Interpretations

**Interpretation 1 (Old Model):**
- `inputs`: What node reads from shared store
- `params`: What can be passed as parameters

**Interpretation 2 (With Namespacing):**
- `inputs`: What node expects as parameters
- `params`: All available parameters

**Interpretation 3 (Exclusive Params):**
- `inputs`: Parameters that connect to other nodes
- `params`: Additional configuration parameters

The context builder uses Interpretation 3, but with namespacing, Interpretation 2 is correct!

## Evidence from the Codebase

### From node_wrapper.py (Template Resolution)
```python
# Build resolution context: shared store + planner parameters
context = dict(shared)  # Start with shared store data
context.update(self.initial_params)  # Planner parameters override
```

With namespacing, `dict(shared)` gets the namespaced view, so direct reads fail!

### From write_file.py (Node Implementation)
```python
content = shared.get("content") or self.params.get("content")
```

The fallback pattern REQUIRES params when shared.get() fails (which it always does with namespacing).

### From test_namespacing.py (Proof)
```python
# With namespacing enabled
assert "content" not in shared  # Not at root!
assert shared["node1"]["content"] == "data"  # In namespace!
```

## The Cost of Confusion

### Development Time
- Developers spend time debugging "missing content" errors
- LLM generates incorrect workflows
- Tests need constant fixing

### Mental Load
- Must remember which nodes have "exclusive params"
- Must understand when "Parameters: none" is lying
- Must know to always use template variables

### Documentation Debt
- Explanations become complex
- Edge cases multiply
- Workarounds needed

## Summary

The core problem is that the context builder presents nodes using a mental model that no longer matches reality. With automatic namespacing enabled by default, the presentation of "Inputs" and "Parameters" as separate concepts is not just unhelpful—it's actively misleading.

The solution is simple: present ALL parameters in one clear section, with concrete examples of how to use them. This eliminates the confusion without changing any other part of the system.