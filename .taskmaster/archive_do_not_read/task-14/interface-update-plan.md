# Plan: Update All Interface Examples to Enhanced Format

## Overview
This plan outlines the systematic update of all Interface examples in pflow documentation from the simple format to the Enhanced Interface Format with type annotations and descriptions.

## Scope
- **Total occurrences**: 23 Interface examples
- **Files affected**: 11 documentation files
- **Estimated time**: 2-3 hours

## Current State
All code nodes in `src/pflow/nodes/` have been updated to use the enhanced format, but documentation still shows the old format. This creates inconsistency and confusion.

## Objectives
1. Update all Interface examples to include type annotations
2. Add semantic descriptions where helpful
3. Apply the exclusive params pattern
4. Use multi-line format for better readability
5. Ensure consistency across all documentation

## File Inventory and Update Strategy

### 1. Core Reference Documentation
**File**: `docs/reference/node-reference.md`
- **Occurrences**: Multiple examples throughout
- **Priority**: HIGH - This is the primary reference
- **Strategy**: Update all examples, add section about enhanced format

**File**: `docs/implementation-details/metadata-extraction.md`
- **Occurrences**: Examples showing extraction process
- **Priority**: HIGH - Must reflect new parser capabilities
- **Strategy**: Update examples to show enhanced format extraction

### 2. Feature Documentation
**File**: `docs/features/simple-nodes.md`
- **Occurrences**: Node implementation examples
- **Priority**: HIGH - Developers reference this
- **Strategy**: Convert all examples, emphasize type benefits

**File**: `docs/features/cli-runtime.md`
- **Occurrences**: Examples of nodes in workflows
- **Priority**: MEDIUM
- **Strategy**: Update to show typed interfaces

**File**: `docs/features/planner.md`
- **Occurrences**: Examples showing planner usage
- **Priority**: HIGH - Shows WHY types matter
- **Strategy**: Demonstrate type-aware planning

**File**: `docs/features/mcp-integration.md`
- **Occurrences**: MCP node examples
- **Priority**: MEDIUM
- **Strategy**: Update future-facing examples

### 3. Core Concepts
**File**: `docs/core-concepts/registry.md`
- **Occurrences**: Registry storage examples
- **Priority**: MEDIUM
- **Strategy**: Show how types are stored

### 4. Product Documentation
**File**: `docs/prd.md`
- **Occurrences**: Product requirement examples
- **Priority**: LOW
- **Strategy**: Update for consistency

### 5. Future Version Documentation
**Files in**: `docs/future-version/`
- **Priority**: LOW - These are speculative
- **Strategy**: Update to set correct expectations

**Files in**: `docs/core-node-packages/`
- **Priority**: MEDIUM - Package specifications
- **Strategy**: Update all package examples

## Transformation Rules

### Rule 1: Add Type Annotations
```python
# OLD
- Reads: shared["file_path"]

# NEW
- Reads: shared["file_path"]: str  # Path to the file
```

### Rule 2: Apply Exclusive Params Pattern
```python
# OLD
- Reads: shared["content"]
- Params: content, encoding, append

# NEW
- Reads: shared["content"]: str  # Content to write
- Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
- Params: append: bool  # Append mode (default: false)
# Note: content and encoding removed from Params!
```

### Rule 3: Use Multi-line Format
```python
# OLD
- Reads: shared["x"], shared["y"], shared["z"]
- Writes: shared["sum"], shared["product"]

# NEW
- Reads: shared["x"]: int  # First number
- Reads: shared["y"]: int  # Second number
- Reads: shared["z"]: int  # Third number
- Writes: shared["sum"]: int  # Sum of inputs
- Writes: shared["product"]: int  # Product of inputs
```

### Rule 4: Add Meaningful Descriptions
- Focus on semantics, not just type
- Include default values
- Mention valid ranges or options
- Explain the purpose

### Rule 5: Document Complex Types
```python
# For dict/list types, indicate they contain structures
- Writes: shared["data"]: dict  # User information
- Writes: shared["items"]: list  # Array of results
```

## Common Transformations

### File Operations
```python
# OLD
Interface:
- Reads: shared["file_path"], shared["encoding"]
- Writes: shared["content"], shared["error"]
- Params: file_path, encoding (as fallbacks)
- Actions: default, error

# NEW
Interface:
- Reads: shared["file_path"]: str  # Path to the file to read
- Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
- Writes: shared["content"]: str  # File contents
- Writes: shared["error"]: str  # Error message if operation failed
- Actions: default (success), error (failure)
```

### API/LLM Operations
```python
# OLD
Interface:
- Reads: shared["prompt"], shared["model"]
- Writes: shared["response"], shared["error"]
- Params: prompt, model, temperature
- Actions: default, error

# NEW
Interface:
- Reads: shared["prompt"]: str  # Input prompt for the model
- Reads: shared["model"]: str  # Model name (e.g., 'gpt-4')
- Writes: shared["response"]: str  # Model's response
- Writes: shared["error"]: str  # Error message if failed
- Params: temperature: float  # Sampling temperature (default: 0.7)
- Actions: default (success), error (failure)
```

## Quality Checklist

For each file updated:
- [ ] All Interface examples use type annotations
- [ ] Descriptions are clear and helpful
- [ ] Exclusive params pattern applied (no duplicate params)
- [ ] Multi-line format used for readability
- [ ] Examples are consistent with actual node implementations
- [ ] No syntax errors in examples
- [ ] Types are valid Python types (str, int, bool, dict, list, float)

## Validation Steps

1. **Visual inspection**: Each example should be readable and clear
2. **Parser test**: Examples should parse with the metadata extractor
3. **Consistency check**: Similar nodes should have similar patterns
4. **Cross-reference**: Check against actual implementations in `src/pflow/nodes/`

## Expected Outcomes

After completion:
- All documentation shows consistent enhanced format
- Developers understand how to write typed interfaces
- Examples demonstrate the value of type annotations
- Documentation matches actual implementation

## Potential Challenges

1. **Nested examples**: Some docs may have Interface examples in code blocks within lists
2. **Partial examples**: Some may show only parts of an Interface
3. **Theoretical nodes**: Examples for non-existent nodes need reasonable types
4. **Space constraints**: Some examples may need to stay compact

## Notes for Implementation

- Start with high-priority files first
- Test examples with the actual parser when possible
- Keep descriptions concise but meaningful
- When in doubt, check the actual node implementations
- Preserve the intent of the original example while adding types
