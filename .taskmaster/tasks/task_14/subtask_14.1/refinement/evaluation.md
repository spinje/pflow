# Evaluation for 14.1

## Ambiguities Found

### 1. Implementation vs Documentation Mismatch - Severity: 5

**Description**: The documentation describes a rich metadata schema with nested dictionaries, types, and descriptions, but the actual implementation returns simple string lists. The docs also reference an `InterfaceSectionParser` class that doesn't exist.

**Why this matters**: This fundamental mismatch needs resolution before implementation can begin. Are we implementing the documented rich format or enhancing the existing simple format?

**Current Reality**:
- Implementation returns: `{"inputs": ["key1", "key2"], "outputs": ["result", "error"]}`
- Documentation describes: `{"inputs": {"key1": {"type": "str", "required": true, "description": "..."}}}`

**Options**:
- [x] **Option A**: Enhance existing `PflowMetadataExtractor` to support both simple and rich formats
  - Pros: Maintains backward compatibility, incremental enhancement, aligns with handoff document
  - Cons: More complex parser logic
  - Similar to: Task 7's phased approach to parsing

- [ ] **Option B**: Implement the documented `InterfaceSectionParser` as a separate class
  - Pros: Clean separation, matches documentation exactly
  - Cons: Two parallel systems, migration complexity
  - Risk: May never migrate old nodes

- [ ] **Option C**: Keep simple format, update documentation to match reality
  - Pros: No code changes needed
  - Cons: Doesn't solve the planner's need for type information
  - Risk: Task 17 (planner) will fail without structure information

**Recommendation**: Option A - The handoff document and all task materials assume we're enhancing the existing extractor. This maintains backward compatibility while adding the needed functionality.

### 2. Missing `_extract_list_section()` Method - Severity: 4

**Description**: The task details mention extending `_extract_list_section()` as the entry point, but this method doesn't exist in the current implementation.

**Why this matters**: Need to identify the correct extension point for the implementation.

**Analysis**: After examining the code, the equivalent functionality is in:
- `_extract_shared_keys()` - extracts keys from shared["key"] patterns
- `_parse_interface_section()` - orchestrates the parsing

**Options**:
- [x] **Option A**: Create new helper methods for enhanced parsing
  - Create `_extract_enhanced_list()` for new format
  - Keep existing methods for backward compatibility
  - Add format detection logic to `_parse_interface_section()`

- [ ] **Option B**: Completely refactor existing methods
  - Risk: Breaking existing functionality
  - More complex testing

**Recommendation**: Option A - Create new methods alongside existing ones, with format detection to route appropriately.

### 3. Storage Format Transition - Severity: 3

**Description**: How should we store the enhanced metadata while maintaining backward compatibility?

**Current**: `{"outputs": ["key1", "key2"]}`
**Needed**: `{"outputs": [{"key": "key1", "type": "str", "description": "..."}]}`

**Options**:
- [x] **Option A**: Always return rich format, with defaults for simple inputs
  - Simple format: `{"key": "content", "type": "any", "description": ""}`
  - Rich format: Full type and structure information
  - Pros: Consistent output format, easier for consumers
  - Cons: Changes return type for all callers

- [ ] **Option B**: Return format based on input format
  - Simple input → simple output
  - Rich input → rich output
  - Pros: True backward compatibility
  - Cons: Consumers must handle both formats

**Recommendation**: Option A - Based on the task specification, we should always return the rich format. For simple inputs, we'll add default type "any" and empty descriptions.

## Conflicts with Existing Code/Decisions

### 1. Actual vs Theoretical Interface Format

- **Current state**: All nodes use single-line format: `Writes: shared["key"], shared["key2"]`
- **Task assumes**: Nodes will use structured format with types and indentation
- **Resolution needed**: Must support BOTH formats, detecting which one is used

### 2. Registry Storage Expectations

- **Current state**: Registry stores simple metadata from scanner
- **Task assumes**: Registry will store rich metadata with types
- **Resolution needed**: Ensure registry can handle the new format (likely already can since it just stores JSON)

## Implementation Approaches Considered

### Approach 1: Phased Enhancement (Similar to Task 7)
- Description: Add phases for format detection, type extraction, structure parsing
- Pros: Clean separation, proven pattern from Task 7
- Cons: Need to carefully integrate with existing phases
- Decision: **Selected** - This approach worked well in Task 7

### Approach 2: Complete Rewrite
- Description: Replace the entire metadata extractor
- Pros: Could match documentation exactly
- Cons: High risk of breaking existing functionality
- Decision: **Rejected** - Too risky for backward compatibility

### Approach 3: Minimal Changes
- Description: Only add type parsing, ignore structures
- Pros: Simpler implementation
- Cons: Doesn't meet full requirements for Task 17
- Decision: **Rejected** - Doesn't solve the core problem

## Critical Questions for User

Given the documentation/implementation mismatch, I need confirmation on the approach:

1. **Should I enhance the existing `PflowMetadataExtractor` class** (as the handoff suggests) rather than creating the documented but non-existent `InterfaceSectionParser`?

2. **Should the enhanced parser always return the rich format** (with defaults for simple inputs) or should it return different formats based on input?

3. **Is the indentation-based structure format final**, or should I follow the actual format shown in the current docstrings?

The handoff document strongly suggests Option A for all these questions, but I want to confirm before proceeding.
