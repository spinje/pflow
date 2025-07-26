# Node IR Implementation: Implications Analysis

## Current State

### What Gets Parsed

The MetadataExtractor can parse and return:
```python
{
    "description": "Node description from first line",
    "inputs": [
        {
            "key": "repo",
            "type": "str",
            "description": "Repository name"
        }
    ],
    "outputs": [
        {
            "key": "issue_data",
            "type": "dict",
            "description": "Complete issue information",
            "structure": {
                "number": {"type": "int", "description": "Issue number"},
                "user": {
                    "type": "dict",
                    "description": "Author info",
                    "structure": {
                        "login": {"type": "str", "description": "GitHub username"},
                        "id": {"type": "int", "description": "User ID"}
                    }
                },
                "labels": {"type": "list[dict]", "description": "Issue labels"}
            }
        }
    ],
    "params": [...],
    "actions": ["default", "error"]
}
```

### Current Consumers and Their Needs

1. **Context Builder** (planning):
   - Needs: EVERYTHING - keys, types, descriptions, nested structures
   - Uses: Formats rich documentation for LLM planning
   - Critical for Task 17 planner

2. **Template Validator** (proposed):
   - Needs: Just key names from outputs (e.g., ["issue_data"])
   - Uses: Check if templates have sources

3. **Future Consumers**:
   - Type checking systems
   - Documentation generators
   - IDE integration

## Options for Node IR Storage

### Option 1: Full Rich Metadata (Store Everything)

```json
{
  "read-file": {
    "class_name": "ReadFileNode",
    "docstring": "...",
    "module": "...",
    "interface": {
      "inputs": [
        {
          "key": "file_path",
          "type": "str",
          "description": "Path to file"
        }
      ],
      "outputs": [
        {
          "key": "content",
          "type": "str",
          "description": "File contents"
        }
      ]
    }
  }
}
```

**Pros**:
- Single source of truth
- No runtime parsing
- All consumers get rich data
- Supports future features

**Cons**:
- Larger registry file
- More complex structure

### Option 2: Minimal Keys Only

```json
{
  "read-file": {
    "class_name": "ReadFileNode",
    "docstring": "...",
    "module": "...",
    "interface": {
      "inputs": ["file_path"],
      "outputs": ["content"],
      "params": ["file_path"],
      "actions": ["default", "error"]
    }
  }
}
```

**Pros**:
- Smaller registry
- Simple structure

**Cons**:
- Loses type/description info
- Context builder would need to re-parse
- Two parsing systems

### Option 3: Hybrid Approach

```json
{
  "read-file": {
    "class_name": "ReadFileNode",
    "docstring": "...",
    "module": "...",
    "interface": {
      "inputs": ["file_path"],
      "outputs": ["content"],
      "params": ["file_path"],
      "actions": ["default", "error"]
    },
    "interface_rich": {
      // Full metadata stored separately
      // Could be in a separate file
    }
  }
}
```

**Pros**:
- Best of both worlds
- Backward compatible

**Cons**:
- More complex
- Two fields to maintain

## Impact Analysis

### If We Store Full Rich Metadata

1. **Scanner Changes**:
   - Import MetadataExtractor
   - Call extract_metadata() during scanning
   - Store full result in interface field

2. **Context Builder Changes**:
   - Remove _process_nodes() parsing logic
   - Directly use registry interface data
   - Simpler, faster code

3. **Registry Size**:
   - Current: ~2KB per node
   - With full metadata: ~5-10KB per node
   - For 100 nodes: ~500KB-1MB (acceptable)

4. **Performance**:
   - Scanning: Slower (one-time cost)
   - Runtime: Much faster (no parsing)

### Migration Path

1. **Phase 1**: Update scanner to store full metadata
2. **Phase 2**: Update context builder to use it
3. **Phase 3**: Update validator to use it
4. **Phase 4**: Deprecate docstring parsing

## Recommendation

**Store Full Rich Metadata (Option 1)**

Reasons:
1. Registry size is not a concern (even 1MB is tiny)
2. Eliminates ALL runtime parsing
3. Single source of truth
4. Enables rich features (type checking, better docs)
5. Context builder already expects this format
6. Future-proof for Task 17 and beyond

The only real cost is updating the scanner, which is a one-time change. Every consumer benefits from having pre-parsed, structured data available immediately.
