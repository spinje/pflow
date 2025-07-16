# Task 14: Structured Output Metadata - Critical Ambiguities

## Executive Summary

While Task 14's goal is clear (enable the planner to see data structures), several implementation details need clarification before coding can begin. This document identifies each ambiguity with concrete options and recommendations.

**Update**: After analyzing the codebase, additional ambiguities have been identified regarding Interface section integration, partial structure documentation, and specific implementation patterns already established in the project.

## 1. Exact Docstring Format Specification - Decision importance (5)

The task shows an example format, but many variations are possible and each has trade-offs.

### The Ambiguity:
- Should we use JSON-like, YAML-like, or Python-dict-like syntax?
- How to represent types (Python types vs JSON types vs strings)?
- How to handle optional fields?
- How to represent arrays of objects?

### Corrected Understanding:
- We're extending the existing "Writes:" format in Interface section
- No separate "Outputs:" section exists or should be created
- Must maintain backward compatibility with simple format

### Options:

- [ ] **Option A: JSON-like with Python types**
  ```python
  """
  Interface:
  - Writes: shared["issue_data"]: {
      "id": int,
      "title": str,
      "user": {"login": str, "id": int},
      "labels": [{"name": str, "color": str}]
    }
  """
  ```
  - Pros: Familiar to Python developers, clear type info
  - Cons: Not valid JSON, types aren't strings, complex to parse

- [x] **Option B: Simplified indentation notation**
  ```python
  """
  Interface:
  - Reads: shared["issue_number"]: int, shared["repo"]: str
  - Writes: shared["issue_data"]: dict
      - id: int  # Issue number
      - title: str  # Issue title
      - user: dict  # Issue author
        - login: str  # GitHub username
        - id: int  # User ID
      - labels: list[dict]  # Issue labels
        - name: str  # Label text
        - color: str  # Hex color code
  - Writes: shared["error"]: str  # Error message if failed
  - Params: token: str  # GitHub API token
  """
  ```
  - Pros: Clean indentation-based, no brace matching needed, natural extension
  - Cons: Multiple Writes lines needed for multiple outputs

- [ ] **Option C: Type annotation style**
  ```python
  """
  Interface:
  - Writes: shared["issue_data"]: Dict[str, Any] with structure:
    {
      id: int,
      title: str,
      user: {login: str, id: int},
      labels: List[{name: str, color: str}]
    }
  """
  ```
  - Pros: Pythonic, type-hint familiar
  - Cons: Verbose, mixing formats, complex parsing

**Recommendation**: Option B - Indentation-based is easiest to parse and write, avoiding complex brace matching while remaining readable.

## 2. Type System Representation - Decision importance (4)

How should we represent types in the structure documentation?

### The Ambiguity:
- Use Python types (int, str, dict, list)?
- Use JSON types (number, string, object, array)?
- Use simplified types (text, number, object, array)?
- How to handle None/null, Any, Union types?

### Options:

- [x] **Option A: Python built-in types only**
  - Types: `str`, `int`, `float`, `bool`, `dict`, `list`, `None`
  - Simple and familiar to Python developers
  - Sufficient for MVP needs

- [ ] **Option B: JSON Schema types**
  - Types: `string`, `number`, `boolean`, `object`, `array`, `null`
  - More standard but less Pythonic
  - Might confuse Python developers

- [ ] **Option C: Rich type system**
  - Include Optional, Union, Any, custom types
  - More expressive but complex to parse
  - Overkill for MVP

**Recommendation**: Option A - Python built-in types are familiar and sufficient. We can always extend later.

## 3. Array Representation Ambiguity - Decision importance (4)

How to represent arrays of structured objects?

### The Ambiguity:
- How to show the structure of items in an array?
- Support homogeneous arrays only or mixed types?
- How to indicate "array of X"?

### Options:

- [x] **Option A: list[type] with example structure**
  ```python
  """
  Interface:
  - Writes: shared["labels"]: list[dict]
      - name: str
      - color: str
  """
  ```
  - Shows one example structure for all items
  - Assumes homogeneous arrays

- [ ] **Option B: JSON-style array notation**
  ```python
  """
  Interface:
  - Writes: shared["labels"]: [{"name": str, "color": str}]
  """
  ```
  - More compact but harder to parse

- [ ] **Option C: Explicit array documentation**
  ```python
  """
  Interface:
  - Writes: shared["labels"]: array
      items:
        - name: str
        - color: str
  """
  ```
  - Very explicit but verbose

**Recommendation**: Option A - Clear and consistent with the indentation-based approach.

## 4. Parsing Strategy - Decision importance (5)

How should we parse these structured docstrings?

### The Ambiguity:
- Use regex with state machine?
- Write a simple parser?
- Use existing parsing library?
- How to handle malformed structures?

### Options:

- [ ] **Option A: Enhanced regex parsing**
  - Extend existing regex approach
  - Add state tracking for nesting
  - Pros: Consistent with current code
  - Cons: Regex complexity explosion

- [x] **Option B: Simple indentation-based parser**
  - Parse based on indentation levels
  - Similar to YAML parsing
  - Pros: Clean, maintainable
  - Cons: New code pattern

- [ ] **Option C: Use existing library**
  - Use YAML parser with preprocessing
  - Pros: Robust parsing
  - Cons: New dependency, format constraints

**Recommendation**: Option B - Indentation-based parsing is simple and maintainable for our specific format.

## 5. Backward Compatibility Details - Decision importance (5)

How exactly do we maintain compatibility with existing simple format?

### The Ambiguity:
- How to detect which format is being used?
- Can both formats exist in same docstring?
- What about nodes with mixed simple/structured outputs?

### Options:

- [x] **Option A: Format detection by structure**
  - If line has `:` followed by type → structured
  - If comma-separated list → simple
  - Never mix formats in one section
  ```python
  # Simple format (existing):
  Outputs: key1, key2, key3

  # Structured format (new):
  Outputs:
  - key1: str
  - key2: dict
    - field: str
  ```

- [ ] **Option B: Explicit format marker**
  ```python
  Outputs (structured):
  - key: {...}
  ```
  - More explicit but breaks existing nodes

- [ ] **Option C: Support mixed formats**
  ```python
  Outputs: simple_key1, simple_key2
  - complex_key: dict
    - field: str
  ```
  - Flexible but confusing

**Recommendation**: Option A - Clean detection based on structure, never mix formats.

## 6. Structure Depth Limits - Decision importance (3)

How deep should we allow structures to go?

### The Ambiguity:
- Unlimited nesting depth?
- Practical limit for readability?
- How to handle recursive structures?

### Options:

- [ ] **Option A: Unlimited depth**
  - Parse any depth
  - Risk of huge docstrings
  - Parsing complexity

- [x] **Option B: Practical limit (3-4 levels)**
  - Sufficient for most APIs
  - Use "..." for deeper structures
  - Example:
  ```python
  - data: dict
    - user: dict
      - profile: dict
        - settings: dict  # Max depth
          - ...: Any    # Indicate more nesting
  ```

- [ ] **Option C: Depth limit with references**
  - Define structures separately
  - Reference by name
  - Too complex for MVP

**Recommendation**: Option B - 3-4 levels covers most use cases while keeping docstrings readable.

## 7. Error Handling Strategy - Decision importance (4)

What happens when structure parsing fails?

### The Ambiguity:
- Fail hard and block registry loading?
- Warn and fall back to simple format?
- Silent fallback?

### Options:

- [ ] **Option A: Fail hard**
  - Any parse error stops registry loading
  - Forces immediate fixes
  - Too disruptive

- [x] **Option B: Warn and fallback**
  - Log warning with specific error
  - Treat as simple output list
  - Preserves functionality
  - Example:
  ```python
  logger.warning(f"Failed to parse structure for {node}.outputs: {error}")
  # Fallback to simple format
  ```

- [ ] **Option C: Partial parsing**
  - Parse what we can, skip errors
  - Risk of incorrect structures

**Recommendation**: Option B - Graceful degradation maintains system stability while alerting developers.

## 8. Storage Format in Metadata - Decision importance (3)

How should parsed structures be stored in the metadata dictionary?

### The Ambiguity:
- Store as parsed Python dicts?
- Create a Structure class?
- Keep original text too?

### Options:

- [x] **Option A: Integrated storage with types in outputs array**
  ```python
  metadata = {
      "outputs": [
          {
              "key": "issue_data",
              "type": "dict",
              "description": "GitHub issue details",
              "structure": {
                  "id": {"type": "int", "description": "Issue number"},
                  "user": {
                      "type": "dict",
                      "description": "Issue author",
                      "structure": {
                          "login": {"type": "str", "description": "GitHub username"}
                      }
                  }
              }
          },
          {
              "key": "issue_number",
              "type": "int",
              "description": "Issue number for API calls"
          }
      ],
      # Similar structure for inputs and params
      "inputs": [
          {"key": "repo", "type": "str", "description": "Repository name"}
      ],
      "params": [
          {"key": "token", "type": "str", "description": "GitHub API token"}
      ]
  }
  ```

- [ ] **Option B: Separate structures dict**
  ```python
  metadata = {
      "outputs": ["issue_data", "issue_number"],
      "output_structures": {...}  # Separate dict
  }
  ```
  - Maintains current format
  - But separates related information

- [ ] **Option C: Structure classes**
  - Create OutputStructure, Field classes
  - More OOP but overkill for MVP

**Recommendation**: Option A - Storing types directly in the outputs/inputs/params arrays keeps related information together and provides a cleaner, more intuitive structure. This also naturally extends to support inputs and params with types.

## 9. Context Builder Integration Specifics - Decision importance (4)

How exactly should structures appear in the planning context?

### The Ambiguity:
- Full structure every time?
- Abbreviated common paths?
- Example-based format?

### Options:

- [x] **Option A: Full structure extraction**
  - Extract and store complete structure information
  - Task 14 includes small modifications to context builder to display the new type/structure information
  - Ensure existing tests continue to pass with the new metadata format
  - **Note**: Major context builder redesigns (like splitting into two files) are future enhancements
  - Task 14 focuses on making the enriched metadata available and visible

- [ ] **Option B: Path examples approach**
  ```markdown
  ### github-get-issue
  **Outputs**:
  - `issue_data`: Complex object
    - Example paths: `issue_data.id`, `issue_data.user.login`, `issue_data.labels[0].name`
    - Full structure: {...abbreviated...}
  ```
  - Gives LLM quick examples
  - Full structure available if needed

- [ ] **Option C: Interactive expansion**
  - Show top-level only
  - LLM can ask for more
  - Too complex for MVP

**Recommendation**: Option A - Extract all structure information. The context builder is responsible for intelligent presentation, splitting information into appropriate contexts to avoid overwhelming the LLM while ensuring all necessary details are available when needed.

## 10. Priority Node Selection - Decision importance (3)

Which nodes should we update first and why?

### The Ambiguity:
- Update all nodes at once?
- Just GitHub nodes?
- Criteria for priority?

### Options:

- [ ] **Option A: All API nodes**
  - Complete coverage
  - Time consuming
  - Risk of errors

- [x] **Option B: Strategic selection**
  Priority order:
  1. `github-get-issue` - Most complex, most used in examples
  2. `github-list-prs` - Array handling example
  3. `claude-code` - Complex output structure
  4. File operations returning metadata
  - Covers main patterns
  - Manageable scope

- [ ] **Option C: On-demand updates**
  - Update as needed
  - Inconsistent state

**Recommendation**: Option B - Strategic nodes provide templates for others to follow.

## 11. Interface Section Integration - Decision importance (5)

How should structured outputs integrate with the existing Interface section pattern?

### The Ambiguity:
- Existing nodes use `Interface:` section with Reads/Writes (where Writes = Outputs)
- Currently NO type information is included
- Should we extend Writes format or create something new?

### Context from Codebase:
- Current format: `Writes: shared["issue_data"], shared["error"]`
- "Writes" is stored as "outputs" in metadata
- No separate Outputs section exists
- No type information currently captured

### Options:

- [x] **Option A: Extend all Interface components with types**
  ```python
  """
  Interface:
  - Reads: shared["issue_number"]: int, shared["repo"]: str
  - Writes: shared["issue_data"]: dict
      - id: int  # Issue number
      - title: str  # Issue title
      - user: dict  # Issue author
        - login: str  # GitHub username
        - id: int  # User ID
      - labels: list[dict]  # Issue labels
        - name: str  # Label text
  - Writes: shared["error"]: str  # Error message if failed
  - Params: token: str, timeout: int  # API token and timeout in seconds
  - Actions: default, error
  """
  ```
  - Pros: Consistent type information across all components
  - Cons: More verbose, but provides complete interface clarity

- [ ] **Option B: Structure annotation after Writes**
  ```python
  """
  Interface:
  - Reads: shared["issue_number"]
  - Writes: shared["issue_data"], shared["error"]
    Where issue_data structure:
      - id: int
      - title: str
      - user: dict
        - login: str
  """
  ```
  - Pros: Keeps simple format for simple cases
  - Cons: Less intuitive parsing

- [ ] **Option C: Keep Writes simple, add separate structure**
  ```python
  """
  Interface:
  - Reads: shared["issue_number"]
  - Writes: shared["issue_data"], shared["error"]

  Output Structures:
  - issue_data: dict
    - id: int
    - title: str
  """
  ```
  - Pros: Clean separation
  - Cons: Breaks pattern of single Interface section

**Recommendation**: Option A - Extending all Interface components with types provides consistency and complete interface understanding. Types should be supported for Reads, Writes, and Params to avoid confusion and partial implementation.

### Important Clarification:
- **All Interface components get types in MVP** for consistency
- Reads: `shared["issue_number"]: int`
- Writes: `shared["data"]: dict` with optional structure
- Params: `timeout: int`
- This provides the planner with complete type information for workflow generation

## 12. Partial Structure Documentation - Decision importance (4)

Should nodes be able to document only commonly-used paths rather than full structures?

### The Ambiguity:
- Some APIs have huge response objects
- Full documentation might be overwhelming
- Most workflows only use a subset of fields

### Options:

- [x] **Option A: Always extract full structure**
  - Document complete structure in node docstrings
  - Context builder handles abbreviation if needed
  - Ensures planner has access to all available paths
  - Aligns with Ambiguity #9 decision

- [ ] **Option B: Allow partial with ellipsis**
  ```python
  """
  Interface:
  - Writes: shared["issue_data"]: dict
      - id: int
      - title: str
      - user: dict
        - login: str
        - id: int
        - ...: Any  # More fields available
      - labels: list[dict]
        - name: str
        - ...: Any
  """
  ```
  - Document commonly used fields
  - Indicate more fields exist
  - Practical for large APIs

- [ ] **Option C: Common paths only**
  ```python
  """
  Common paths:
  - issue_data.id
  - issue_data.user.login
  - issue_data.labels[*].name
  """
  ```
  - Minimal but less useful

**Recommendation**: Option A - Always document full structures. This is consistent with the decision in Ambiguity #9. The metadata extractor should capture complete structure information, and the context builder is responsible for intelligent presentation to avoid overwhelming the planner while ensuring all paths are discoverable.

## 13. Structure Validation Scope - Decision importance (4)

What validation should be performed on documented structures?

### The Ambiguity:
- Should we validate structure syntax during parsing?
- Should we validate consistency between structure and outputs list?
- How much validation is appropriate for MVP?

### Options:

- [x] **Option A: Syntax validation only (MVP)**
  - Validate structure is parseable
  - Ensure types are valid Python types
  - Don't validate paths at runtime
  - Example validation:
    - Valid: `dict`, `list[dict]`, `str`
    - Invalid: `dictionary`, `List<Dict>`

- [ ] **Option B: Full consistency validation**
  - Verify all structured keys appear in outputs list
  - Check for orphaned structures
  - More complex implementation

- [ ] **Option C: No validation**
  - Parse whatever is provided
  - Risk of confusing errors later

**Recommendation**: Option A - Basic syntax validation ensures structures are usable without over-complicating the MVP.

## 14. Test Strategy Specifics - Decision importance (4)

What specific test cases are critical for this feature?

### Required Test Cases:

1. **Backward Compatibility Tests**
   - Simple format still works: `Outputs: key1, key2`
   - Old nodes don't break

2. **Structure Parsing Tests**
   - Flat structure: `dict` with simple fields
   - Nested structure: `dict` containing `dict`
   - Array structure: `list[dict]`
   - Mixed simple and structured outputs
   - Partial documentation with ellipsis

3. **Error Recovery Tests**
   - Malformed structure syntax
   - Invalid type names
   - Incorrect indentation
   - Missing colons

4. **Integration Tests**
   - Metadata extractor captures structures
   - Context builder formats structures correctly
   - Full flow with planner using structures

5. **Edge Cases**
   - Very deep nesting (test depth limits)
   - Large structures (test context size limits)
   - Unicode in field names
   - Reserved Python keywords as field names

## 15. Simple Output Type Specification - Decision importance (5)

How should we specify types for simple (non-structured) outputs?

### The Ambiguity:
- Current format has NO types: `Writes: shared["content"], shared["error"]`
- Planner needs to know if `error` is str, dict, etc. for proper usage
- Must maintain backward compatibility
- Should types be mandatory or optional?

### Why This Matters:
- Planner can't generate appropriate handling without knowing types
- Is `content` a string to display or dict to process?
- Is `error` a string message or error object with fields?
- Type information is crucial for all outputs, not just complex ones

### Options:

- [x] **Option A: Optional inline types**
  ```python
  """
  Interface:
  - Writes: shared["content"]: str, shared["error"]: str, shared["metadata"]: dict
  """
  ```
  - Pros: Compact, natural extension of existing format
  - Cons: Can get long with many outputs
  - Both formats supported for compatibility:
    - Old: `Writes: shared["content"], shared["error"]`
    - New: `Writes: shared["content"]: str, shared["error"]: str`

- [ ] **Option B: Separate Writes lines with types**
  ```python
  """
  Interface:
  - Writes: shared["content"]: str
  - Writes: shared["error"]: str
  - Writes: shared["metadata"]: dict
      - timestamp: str
      - size: int
  """
  ```
  - Pros: Consistent format, clear types, allows structures
  - Cons: More verbose

- [ ] **Option C: Type inference with explicit overrides**
  ```python
  """
  Interface:
  - Writes: shared["content"], shared["error"]  # Inferred as str
  - Writes: shared["metadata"]: dict
  """
  ```
  - Pros: Less verbose for common cases
  - Cons: Implicit rules, potential confusion

- [ ] **Option D: Gradual typing approach**
  ```python
  """
  Interface:
  - Writes: shared["content"], shared["error"]  # Old format still works
  - Write Types: content=str, error=str  # New optional section
  """
  ```
  - Pros: Full compatibility, opt-in
  - Cons: Two ways to do same thing

**Recommendation**: Option A - Optional inline types provide a natural extension of the existing format. The parser can support both comma-separated lists (old format) and inline types (new format), providing full backward compatibility while enabling type information where needed. For complex structures, use separate lines as shown in Option B.

### Migration Strategy:
1. Old format: `Writes: shared["key1"], shared["key2"]` → outputs have unknown type
2. New format: `Writes: shared["key1"]: str` → output has explicit type
3. Parser detects format by presence of colon after shared["key"]
4. Context builder shows types when available: `**Outputs**: content (str), error (str)`

## 16. Field Descriptions for Semantic Understanding - Decision importance (5)

Should we add optional descriptions to help the planner understand field semantics?

### The Problem:
The planner sees structure but not meaning:
```python
- Writes: shared["pr_data"]: dict
    - id: int
    - state: str
    - merged: bool
    - user: dict
      - login: str
```

Critical questions the planner can't answer:
- Is `id` the PR number or internal database ID?
- What values can `state` have?
- What does `merged` mean exactly?
- Is `login` a username or email?

### Why This Matters:
- **Natural language mapping**: "Get the author" → which field?
- **Value understanding**: Can't generate `state == "open"` without knowing valid values
- **Disambiguation**: Multiple `id` fields, generic names like `data`, `value`
- **Semantic correctness**: Understanding what fields represent, not just their type

### Options:

- [x] **Option A: Inline comments**
  ```python
  """
  Interface:
  - Writes: shared["pr_data"]: dict
      - number: int  # PR number (use for API calls)
      - state: str  # "open", "closed", or "draft"
      - merged: bool  # True if PR has been merged
      - user: dict  # PR author
        - login: str  # GitHub username
        - type: str  # "User" or "Organization"
  """
  ```
  - Pros: Familiar Python style, readable, compact
  - Cons: Need to handle # in parsing

- [ ] **Option B: Separate description field**
  ```python
  """
  Interface:
  - Writes: shared["pr_data"]: dict
      - number: int
        desc: PR number (use for API calls)
      - state: str
        desc: "open", "closed", or "draft"
  """
  ```
  - Pros: Structured approach
  - Cons: Verbose, more complex parsing

- [ ] **Option C: No descriptions**
  - Keep it simple, rely on field names
  - Pros: Simpler implementation
  - Cons: Planner struggles with ambiguous fields

**Recommendation**: Option A - Inline comments provide crucial semantic information with minimal syntax overhead. Since we're already updating all nodes for types, adding descriptions now prevents another migration later.

### Description Guidelines:
1. **Focus on semantics**: What does this field represent?
2. **Clarify ambiguity**: Distinguish between similar fields
3. **Include formats**: Date formats, ID formats, units
4. **Keep it concise**: One line, essential info only
5. **Optional but encouraged**: Especially for generic names

### What NOT to Include in MVP:
- **Enum values in types**: While descriptions may mention common values, formal enum types are out of scope
- **Complex constraints**: Advanced validation rules beyond basic semantics

### Examples:
```python
# Clear semantics
- error: str  # Human-readable error message
- error_code: str  # Machine-readable code (e.g., "FILE_NOT_FOUND")

# Format specifications
- created_at: str  # ISO 8601 timestamp
- size: int  # File size in bytes

# Semantic clarification (NOT enum types for MVP)
- state: str  # PR state (commonly "open", "closed", "draft")
- priority: int  # Task priority, typically 1-5
```

Note: While descriptions may mention common values for clarity (e.g., "typically 'open' or 'closed'"), the MVP will not include formal enum type validation. This is purely for semantic understanding.

## 17. Documentation and Migration - Decision importance (3)

How should we document this feature and help migrate existing nodes?

### Options:

- [x] **Option A: Comprehensive guide with node migration**
  - Create structure documentation guide
  - Show progression from simple to complex
  - **Migrate all existing nodes as part of Task 14**:
    - All nodes in `src/pflow/nodes/`
    - Priority: github nodes, file operations, llm nodes
  - **Update examples in `examples/` folder**:
    - Update workflow examples to use typed nodes
    - Show proxy mapping with documented structures
  - Documentation sections:
    1. When to add types and structures
    2. Simple types (str, int, bool)
    3. Complex structures (dict with nested fields)
    4. Array handling (list[dict])
    5. Adding semantic descriptions
    6. Migration checklist for all nodes

- [ ] **Option B: Minimal documentation**
  - Just update existing node guide
  - Risk of inconsistent adoption

- [ ] **Option C: Auto-migration tool**
  - Script to help migrate nodes
  - Complex for MVP

**Recommendation**: Option A - Comprehensive documentation with full node migration ensures consistency across the codebase. Migrating existing nodes and updating examples is essential for Task 14 completion, not deferred to future work.

## Critical Implementation Order

1. **First**: Decide on format (Recommendation: Indentation-based)
2. **Second**: Implement parser with error handling
3. **Third**: Update metadata extractor
4. **Fourth**: Update 2-3 test nodes
5. **Fifth**: Integrate with context builder
6. **Sixth**: Test with full planner flow

## The Most Critical Decision

**Format choice (Ambiguity #1) affects everything else**. The indentation-based format recommended here:
- Easiest to parse
- Natural to write
- No brace matching complexity
- Familiar from YAML/Python

## Risk Mitigation

1. **Start with minimal structure support** - Just one level deep
2. **Test on one node completely** before updating others
3. **Keep backward compatibility** as non-negotiable requirement
4. **Use warning logs** to find issues without breaking system

This should resolve the key ambiguities and enable implementation to begin.

## Task Scope Expansion

The analysis revealed that Task 14 needs significant expansion beyond "structured output metadata" to include:

1. **Type information for ALL outputs** - Simple outputs like `error: str` need types too
2. **Semantic descriptions** - Optional but valuable descriptions to clarify field meanings
3. **Unified format** - Same syntax for simple types, complex structures, and descriptions
4. **Comprehensive solution** - Solves the planner's full understanding needs

This expansion is necessary because the planner needs:
- **Types**: To know valid operations (can you iterate? access fields?)
- **Structures**: To generate nested paths like `user.login`
- **Semantics**: To understand what fields mean ("author" → `user.login`)
- **Constraints**: To know valid values (`state: "open" or "closed"`)

The original task description focused on complex structures, but the planner's needs are much broader - it needs to understand not just shape, but meaning.

## Summary of Key Decisions

Based on codebase analysis and user feedback, the recommended approach is:

1. **Format**: Extend all Interface components (Reads, Writes, Params) with types
2. **Types**: Python built-in types (str, int, dict, list, etc.)
3. **Descriptions**: Optional inline comments for semantic understanding
4. **Parsing**: Simple indentation parser with comment handling
5. **Storage**: Types stored directly in outputs/inputs/params arrays
6. **Compatibility**: Full backward compatibility - old format without types still works
7. **Documentation**: Always full structures (context builder handles presentation)
8. **Validation**: Syntax validation only for MVP (no enum types)
9. **Migration**: All existing nodes and examples updated as part of Task 14

### Key Understanding:
- **Writes = Outputs** (they are the same concept)
- No separate Outputs section exists or should be created
- We're extending the existing Interface pattern, not creating new sections
- **ALL components need types** - Reads, Writes, and Params for consistency
- **Descriptions add semantic value** - especially for ambiguous fields

### Format Examples:
```python
# Old format (still supported):
- Reads: shared["file_path"]
- Writes: shared["content"], shared["error"]
- Params: encoding

# New format with types and descriptions:
- Reads: shared["file_path"]: str  # Path to file
- Writes: shared["content"]: str, shared["error"]: str  # Inline for simple outputs
- Params: encoding: str  # File encoding (default: utf-8)

# Complex structure with descriptions:
- Reads: shared["issue_number"]: int, shared["repo"]: str
- Writes: shared["issue_data"]: dict
    - number: int  # Issue number (use for API calls)
    - state: str  # Issue state (typically "open" or "closed")
    - user: dict  # Issue author
      - login: str  # GitHub username
    - labels: list[dict]  # Issue labels
      - name: str  # Label text
      - color: str  # Hex color code
- Params: token: str  # GitHub API token
```

### Implementation Checklist

- [ ] Extend Interface parsing in metadata_extractor.py for all components:
  - [ ] Parse types for Reads, Writes, and Params
  - [ ] Support both inline and separate line formats
  - [ ] Handle indentation-based structure parsing
  - [ ] Implement comment parsing for descriptions
- [ ] Update metadata storage format:
  - [ ] Store types directly in outputs/inputs/params arrays
  - [ ] Include type, description, and structure fields
- [ ] Update context builder (minimal changes only):
  - [ ] Display type information for inputs/outputs/params
  - [ ] Show structure information when available
  - [ ] Ensure tests pass with new metadata format
- [ ] Create comprehensive test suite:
  - [ ] Test all format variations
  - [ ] Verify backward compatibility
  - [ ] Test structure parsing edge cases
- [ ] Migrate ALL existing nodes:
  - [ ] github-get-issue (complex structure)
  - [ ] github-list-prs (array handling)
  - [ ] All file operation nodes
  - [ ] llm and claude-code nodes
  - [ ] Any other nodes in src/pflow/nodes/
- [ ] Update examples/ folder:
  - [ ] Update workflow examples to show typed interfaces
  - [ ] Add examples of proxy mapping with structures
- [ ] Write comprehensive documentation:
  - [ ] Node structure documentation guide
  - [ ] Migration guide for developers
  - [ ] Examples of all patterns

### Success Criteria

- Planner can generate valid proxy mapping paths on first attempt
- Existing nodes continue to work without modification
- Structure documentation is easy to write and understand
- System gracefully handles parsing errors
- Context builder presents structures clearly to LLM
