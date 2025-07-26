# Node IR Understanding

## Current State

1. **Scanner** (`scanner.py`):
   - Discovers nodes
   - Extracts only basic metadata:
     ```python
     {
         "module": "pflow.nodes.file.read_file",
         "class_name": "ReadFileNode",
         "name": "read-file",
         "docstring": "raw docstring text...",  # UNPARSED
         "file_path": "/path/to/file.py"
     }
     ```

2. **Registry** (`~/.pflow/registry.json`):
   - Stores exactly what scanner provides
   - Just raw docstrings, no parsed interface data

3. **Context Builder** (`context_builder.py`):
   - Parses docstrings on-demand using MetadataExtractor
   - Extracts structured interface data:
     ```python
     {
         "description": "Read content from a file...",
         "inputs": ["file_path", "encoding"],    # PARSED from Reads:
         "outputs": ["content"],                  # PARSED from Writes:
         "params": ["file_path", "encoding"],
         "actions": ["default", "error"]
     }
     ```

## The Missing "Node IR"

You're right - we're repeatedly parsing the same docstrings! The natural solution is to extend what we store in the registry to include the parsed interface data. This would be the "Node IR" - a structured representation of each node's capabilities.

## Three Options

### Option 1: Extend Registry (Node IR)
Store parsed metadata in registry:
```json
{
  "read-file": {
    "class_name": "ReadFileNode",
    "docstring": "...",
    "interface": {                    // NEW: Parsed interface data
      "inputs": ["file_path", "encoding"],
      "outputs": ["content"],
      "params": ["file_path", "encoding"],
      "actions": ["default", "error"]
    }
  }
}
```

**Pros**:
- Parse once during scanning
- No runtime parsing overhead
- Single source of truth
- Registry becomes self-documenting

**Cons**:
- Larger registry file
- Need to update scanner

### Option 2: Extend Workflow IR
Add interface to nodes in workflows:
```json
{
  "nodes": [{
    "id": "reader",
    "type": "read-file",
    "params": {"file_path": "$input"},
    "interface": {                    // NEW: Interface for validation
      "inputs": ["file_path", "encoding"],
      "outputs": ["content"]
    }
  }]
}
```

**Pros**:
- Self-contained workflows
- No registry needed for validation

**Cons**:
- Duplicated data
- Planner must add this

### Option 3: Keep Current Approach
Continue parsing on-demand.

**Pros**:
- No changes needed
- Flexible

**Cons**:
- Performance overhead
- Complex validation

## Recommendation

**Option 1 (Extend Registry)** is the cleanest approach:
1. Scanner parses interface once during discovery
2. Registry stores structured node metadata (the "Node IR")
3. Validator/planner/context builder use pre-parsed data
4. No repeated parsing, better performance

This is what the user meant by "node IR" - we should be storing the parsed, structured representation of each node's interface, not just raw docstrings.
