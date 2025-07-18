# Task 15: Extend Context Builder for Two-Phase Discovery - Critical Decisions & Ambiguities

## Executive Summary

Task 15 extends the context builder to support two-phase discovery (lightweight selection → detailed planning) and workflow reuse. While the core concept is clear, several implementation details need clarification to ensure success.

**Key Ambiguities**:
1. Workflow storage format and validation requirements
2. Structure parsing output format and limitations
3. Discovery context information boundaries
4. Backward compatibility implementation strategy
5. Error handling and edge case behaviors
6. Performance and size constraints

## 1. Workflow Storage Location and Management - Decision importance (4)

How should workflows be stored, organized, and discovered?

### Context:
The handoff mentions `~/.pflow/workflows/` but doesn't specify:
- Directory creation behavior
- File naming conventions
- Handling of duplicate names
- Support for subdirectories/organization
- Workflow versioning strategy

**Current State Investigation Results**:
- No workflow storage implementation exists yet
- Task 21 (workflow lockfiles) is deferred
- Task 22 (named workflow execution) is pending
- Task 15 needs to load workflows but saving doesn't exist
- Only file operation nodes are available (Task 13 not implemented)

### Options:

- [x] **Option A: Simple flat directory with automatic management + Minimal implementation for Task 15**
  - Create `~/.pflow/workflows/` if missing
  - Store as `{workflow-name}.json`
  - Overwrite on name conflicts (last write wins)
  - No subdirectories in MVP
  - **Task 15 will implement**:
    - Directory creation in `_load_saved_workflows()`
    - Basic JSON loading functionality
    - Support for manually created test workflows
    - Test workflows limited to file operations or test nodes only
  - **Benefits**: Unblocks Task 15, foundation for Task 17, enables testing
  - **Drawbacks**: No save functionality yet, limited node types

- [ ] **Option B: Timestamped files with metadata index**
  - Files: `{workflow-name}-{timestamp}.json`
  - Maintain index file for latest versions
  - More complex but preserves history
  - **Benefits**: No data loss, version history
  - **Drawbacks**: Complexity, cleanup needed

- [ ] **Option C: User-managed organization**
  - Support subdirectories
  - Let users organize workflows
  - **Benefits**: Scalable, user control
  - **Drawbacks**: Complex discovery, path handling

**Recommendation**: Option A with minimal implementation - Task 15 will create the directory structure and implement loading functionality. This unblocks testing and creates the foundation for future tasks. Test workflows will use only available file operation nodes.

## 2. Workflow JSON Schema and Validation - Decision importance (5)

What exact format should saved workflows use?

### Context:
The handoff shows a basic structure but leaves questions:
- Required vs optional fields
- How to store the full IR
- Validation on load vs trust
- Metadata for discovery

### Proposed Schema:
```json
{
  "name": "fix-github-issue",          // Required, unique identifier
  "description": "Analyzes issue...",   // Required, for discovery
  "inputs": ["issue_number"],          // Required, parameter names
  "outputs": ["pr_number", "summary"], // Required, what it produces
  "created_at": "2024-01-15T10:30:00Z", // Optional, ISO format
  "updated_at": "2024-01-15T10:30:00Z", // Optional, ISO format
  "version": "1.0.0",                  // Optional, user version
  "ir_version": "0.1.0",               // Required, IR schema version
  "tags": ["github", "automation"],    // Optional, for future
  "ir": { /* Full workflow IR */ }    // Required, the actual workflow
}
```

### Options:

- [ ] **Option A: Minimal required fields + IR**
  - Only: name, description, inputs, outputs, ir_version, ir
  - Skip timestamps, versions, tags for MVP
  - **Benefits**: Simple, focused on core need
  - **Drawbacks**: Less metadata for future features

- [x] **Option B: Full metadata schema**
  - Include all fields: name, description, inputs, outputs, created_at, updated_at, version, ir_version, tags, ir
  - Rich metadata for discovery
  - **Benefits**: Future-proof, better UX, debugging info, version tracking
  - **Drawbacks**: Slightly more validation (but minimal extra work)
  - **Implementation note**: Tags can default to empty array, version to "1.0.0"

- [ ] **Option C: Just wrap the IR**
  - Store IR directly with minimal wrapper
  - Extract metadata from IR itself
  - **Benefits**: No duplication
  - **Drawbacks**: Expensive to scan

**Recommendation**: Option B - The extra fields are simple to implement now and provide valuable metadata for debugging, versioning, and future features. Timestamps help track workflow age, version field allows user-controlled versioning, and tags enable future categorization.

## 3. Structure Parsing Format Specification - Decision importance (5)

The structure parser exists but what format should it produce?

### Context:
The handoff confirms `_parse_structure()` is implemented with 70 lines of recursive parsing, but the output format affects the planner's ability to generate proxy mappings.

### Example Input/Output:

**Input** (in docstring):
```
- Writes: shared["issue_data"]: dict  # GitHub issue
    - number: int  # Issue number
    - user: dict  # Author information
      - login: str  # Username
      - id: int  # User ID
    - labels: list  # Issue labels
      - name: str  # Label name
```

### Format Options:

- [ ] **Option A: Flat path notation**
  ```json
  {
    "issue_data": "dict",
    "issue_data.number": "int",
    "issue_data.user": "dict",
    "issue_data.user.login": "str",
    "issue_data.user.id": "int",
    "issue_data.labels": "list",
    "issue_data.labels[].name": "str"
  }
  ```
  - **Benefits**: Easy to validate paths
  - **Drawbacks**: Loses hierarchy

- [x] **Option B: Nested structure format** ✓ **SELECTED**
  ```json
  {
    "key": "issue_data",
    "type": "dict",
    "description": "GitHub issue",
    "structure": {
      "number": {"type": "int", "description": "Issue number"},
      "user": {
        "type": "dict",
        "description": "Author information",
        "structure": {
          "login": {"type": "str", "description": "Username"},
          "id": {"type": "int", "description": "User ID"}
        }
      },
      "labels": {
        "type": "list",
        "description": "Issue labels",
        "items": {"name": {"type": "str", "description": "Label name"}}
      }
    }
  }
  ```
  - **Benefits**: Preserves hierarchy, rich information
  - **Drawbacks**: More complex to generate

- [ ] **Option C: JSONPath compatible**
  ```json
  {
    "paths": {
      "$.issue_data": {"type": "dict", "description": "GitHub issue"},
      "$.issue_data.number": {"type": "int", "description": "Issue number"},
      "$.issue_data.user.login": {"type": "str", "description": "Username"}
    }
  }
  ```
  - **Benefits**: Standard path format
  - **Drawbacks**: Verbose, library dependency

**Recommendation**: Option B - The nested format best represents the structure and aligns with the recursive parser implementation.

## 4. Structure Parsing Limitations and Edge Cases - Decision importance (3)

What are the parsing boundaries for MVP?

### Context:
Full type system support would be complex. Need clear boundaries.

**Current Implementation Discovery**:
- Default values are NOT extracted as separate fields
- They only appear in description text like "encoding (default: utf-8)"
- This is fine! The planner can see in the descriptions what the defaults are, if available.

### Specific Decisions:

- [x] **Supported types**: `str`, `int`, `float`, `bool`, `dict`, `list` only
- [x] **No union types**: Can't express `str | int`
- [x] **No optional markers**: Everything assumed required
- [x] **No default value extraction**: Defaults remain in description text only
- [x] **Max nesting depth**: 5 levels (reasonable limit)
- [x] **Array notation**: Support both `list` and `[{structure}]` syntax
- [x] **Fallback behavior**: Invalid syntax returns `{"_raw": "original string"}`

### Default Value Approach:
Since defaults are in descriptions:
- **This is sufficient for the planner** - LLMs understand "encoding (default: utf-8)" naturally
- Nodes should document defaults consistently in descriptions
- Recommended format: "description (default: value)"
- No need for separate default field in MVP
- The planner can intelligently use these defaults when generating workflows

### Example Limitations:
```python
# Supported:
- output: dict
    - name: str
    - tags: list
      - value: str

# NOT supported:
- output: dict
    - name: str | null  # No union types
    - age?: int         # No optional syntax
    - data: any         # No 'any' type
```

**Recommendation**: Document these limitations clearly in code comments and tests.

## 5. Discovery Context Information Boundaries - Decision importance (4)

How much information is "too much" for discovery phase?

### Context:
Discovery should be lightweight but useful. The handoff mentions avoiding LLM overwhelm.

### Options:

- [ ] **Option A: Name only**
  ```markdown
  ### github-get-issue
  ### fix-github-issue
  ```
  - **Benefits**: Minimal tokens
  - **Drawbacks**: Not enough for selection

- [x] **Option B: Name + one-line description** ✓ **SELECTED (no length limits)**
  ```markdown
  ### github-get-issue
  Fetches issue details from GitHub

  ### fix-github-issue
  Analyzes a GitHub issue and creates a PR with the fix
  ```
  - **Benefits**: Enough context, still lightweight
  - **Drawbacks**: Need good descriptions

- [ ] **Option C: Name + description + tags/category**
  ```markdown
  ### github-get-issue [GitHub, API]
  Fetches issue details from GitHub
  ```
  - **Benefits**: Better discovery
  - **Drawbacks**: More complex, not in MVP

**Recommendation**: Option B - One-line descriptions provide sufficient context without overwhelming.

### Size Constraints (Updated):
- **No enforced character limits in MVP** - Let descriptions be as long as needed
- The challenge is **node disambiguation**, not context size
- Good descriptions help LLM distinguish between similar nodes (e.g., "github-get-issue" vs "github-create-issue")
- Quality over brevity - clear, distinctive descriptions are more important than size limits

## 6. Backward Compatibility Strategy - Decision importance (2)

How should existing `build_context()` continue working?

### Context:
**Reality Check**: Only tests use `build_context()`, no production code depends on it yet.

**Terminology Issues**: Current code incorrectly uses `node_type` when these are actually node IDs/names. We should:
1. Document this terminology issue
2. Suggest refactoring to `node_id` or `node_name` while implementing Task 15
3. Use correct terminology in new functions

### Options:

- [ ] **Option A: Keep completely independent**
  - Three separate functions, no code sharing
  - **Benefits**: No regression risk
  - **Drawbacks**: Code duplication

- [x] **Option B: Delegate internally with explicit lists**
  ```python
  def build_discovery_context(node_ids=None, workflow_names=None):
      """Build lightweight discovery context.

      Args:
          node_ids: List of node IDs to include (None = all nodes)
          workflow_names: List of workflow names to include (None = all workflows)
      """
      # Flexibility: Can filter or use all

  def build_planning_context(selected_node_ids, selected_workflow_names, registry_metadata, saved_workflows=None):
      """Build detailed context for selected items."""
      # Explicit about what's included

  def build_context(registry_metadata):
      """Existing function - maintains compatibility."""
      # Delegate to new functions
      all_node_ids = list(registry_metadata.keys())
      discovery = build_discovery_context(all_node_ids, [])  # No workflows in old version
      planning = build_planning_context(all_node_ids, [], registry_metadata)
      return f"{discovery}\n\n{planning}"
  ```
  - **Benefits**:
    - Reuse code, consistent behavior
    - Explicit lists provide future flexibility
    - Can add filtering/exclusions later
    - Clear parameter names
  - **Refactor Note**: Consider renaming `node_type` → `node_id` throughout codebase

- [ ] **Option C: Break compatibility**
  - Since only tests use it, just replace
  - **Benefits**: Clean slate
  - **Drawbacks**: Need to update all tests

**Recommendation**: Option B - Internal delegation with explicit list parameters provides flexibility and maintains compatibility. Document terminology issues for future cleanup.

## 7. Workflow Loading Error Handling - Decision importance (3)

How to handle various failure modes when loading workflows?

### Context:
Files can be corrupted, malformed, or have missing fields.

### Error Handling Strategy:

| Error Type | Action | Logging |
|------------|--------|---------|
| Missing directory | Create silently | Debug log |
| Invalid JSON | Skip file | Warning log |
| Missing required field | Skip file | Warning log |
| Invalid IR structure | Skip file | Warning log |
| Duplicate names | Last wins | Info log |
| File permissions | Skip file | Warning log |

### Validation Levels:

- [x] **MVP Validation**: Check required fields exist (name, description, ir)
- [ ] **Full Validation**: Validate IR against schema
- [ ] **Deep Validation**: Check all node references exist

**Recommendation**: MVP validation only. Log warnings but don't crash.

## 8. Planning Context Component Selection - Decision importance (4)

How to handle selected components that don't exist?

### Context:
Between discovery and planning, components might be removed or renamed (or the llm may have selected a component that doesn't exist).

**Reality**: 95% of "missing components" will be LLM hallucinations or typos (e.g., "github-create-pr" instead of "github-create-pull-request"). Removed/renamed nodes are extremely rare in practice.

### Options:

- [ ] **Option A: Fail with error**
  - Raise exception if any component missing
  - **Benefits**: Fail fast
  - **Drawbacks**: Poor UX, no recovery path

- [ ] **Option B: Skip missing with warning**
  - Just skip and continue with available components
  - **Benefits**: Won't crash
  - **Drawbacks**: **Terrible idea!** Creates incomplete workflows that can't function
  - Like asking "build this puzzle, but some pieces are missing"

- [x] **Option C: Return error info for discovery retry**
  ```python
  # Example: final implementation may look different but this is the idea
  def build_planning_context(selected_node_ids, selected_workflow_names, registry_metadata, saved_workflows=None):
      missing_nodes = []
      missing_workflows = []

      # Check what's missing
      for node_id in selected_node_ids:
          if node_id not in registry_metadata:
              missing_nodes.append(node_id)

      for workflow_name in selected_workflow_names:
          if not any(w['name'] == workflow_name for w in (saved_workflows or [])):
              missing_workflows.append(workflow_name)

      if missing_nodes or missing_workflows:
          # Return error info instead of partial context
          error_msg = "Missing components detected:\n"
          if missing_nodes:
              error_msg += f"- Unknown nodes: {', '.join(missing_nodes)}\n"
              error_msg += "  (Check spelling, use hyphens not underscores)\n"
          if missing_workflows:
              error_msg += f"- Unknown workflows: {', '.join(missing_workflows)}\n"

          return {"error": error_msg, "missing_nodes": missing_nodes, "missing_workflows": missing_workflows}

      # All components found - build full context
      # ... rest of implementation
  ```
  - **Benefits**:
    - Enables retry with corrected selection
    - Clear feedback about what went wrong
    - Maintains workflow integrity
  - **Usage**: Planner detects error, returns to discovery with feedback

- [ ] **Option D: Fuzzy matching suggestions**
  - Find similar names and suggest corrections
  - **Benefits**: Even better UX
  - **Drawbacks**: More complex for MVP

**Recommendation**: Option C - Return error information to enable discovery retry. This maintains workflow integrity while providing a clear recovery path. The planner can use this error to refine its selection.

### Important Nuance: Discovery as "Browsing" vs "Selecting"

**Key Insight**: The discovery phase might be better framed as "browsing relevant components" rather than "selecting required components". This gives the planner flexibility:

- Discovery phase: "Here are nodes/workflows that might be relevant to your task"
- Planning phase: "From these relevant options, choose what you actually need"

This approach:
- Reduces pressure on perfect selection in discovery
- Allows planner to skip unnecessary components
- More natural workflow - like gathering ingredients before deciding final recipe
- The planner knows the full task context and can make better final decisions

**Implementation Note**: The prompt engineering for Task 17 will be crucial here. The discovery prompt should emphasize "find potentially relevant" rather than "select all required".

## 9. Structure Display in Planning Context - Decision importance (3)

How should structures be displayed in the planning context markdown?

### Context:
The planner needs to understand structure to generate proxy mappings.

### Options:

- [ ] **Option A: Inline JSON**
  ```markdown
  **Outputs**:
  - `issue_data: dict` - {"number": "int", "user": {"login": "str"}}
  ```
  - **Benefits**: Compact
  - **Drawbacks**: Hard to read

- [x] **Option B: Indented structure**
  ```markdown
  **Outputs**:
  - `issue_data: dict` - Complete issue data
    Structure of issue_data:
      - number: int - Issue number
      - user: dict - Author info
        - login: str - Username
  ```
  - **Benefits**: Human readable, clear hierarchy
  - **Drawbacks**: More lines

- [ ] **Option C: Table format**
  ```markdown
  | Path | Type | Description |
  |------|------|-------------|
  | issue_data | dict | Complete issue |
  | issue_data.number | int | Issue number |
  ```
  - **Benefits**: Structured
  - **Drawbacks**: Verbose, hard to generate

**Recommendation**: Option B - Indented structure is most readable and aligns with the parser.

## 10. Performance Constraints - Decision importance (2)

What are the performance boundaries?

### Context:
The handoff mentions 200KB MAX_OUTPUT_SIZE but also 50KB in specs.

### Clarifications:

- [x] **Discovery context limit**: 10KB (sufficient for 200+ components)
- [x] **Planning context limit**: 50KB per component group
- [x] **Total context limit**: 200KB (code shows this)
- [x] **Loading timeout**: 5 seconds for all workflows
- [x] **Parse timeout**: 100ms per structure parse

### Optimization Strategy:
1. Lazy load workflow files
2. Cache parsed structures
3. Limit description lengths (100 chars)
4. Skip very large workflow files (>1MB)

**Recommendation**: Use the 200KB limit from code, optimize if needed.

## Implementation Order

Based on these decisions:

1. **Create workflow directory utilities** (Option A - flat directory)
2. **Implement minimal workflow schema** (Option A - required fields only)
3. **Define structure output format** (Option B - nested structure)
4. **Implement discovery context** (Option B - name + description)
5. **Implement planning context** (Option B - indented structure)
6. **Add backward compatibility** (Option B - internal delegation)
7. **Handle errors gracefully** (Skip with warnings)
8. **Test with performance constraints**

## Risk Mitigation

1. **Risk**: Structure parser has unknown edge cases
   - **Mitigation**: Extensive tests, fallback to raw string

2. **Risk**: Workflow loading is slow with many files
   - **Mitigation**: Lazy loading, file size limits

3. **Risk**: Context size explodes with many components
   - **Mitigation**: Strict description length limits

4. **Risk**: Backward compatibility breaks something
   - **Mitigation**: Comprehensive tests before delegation

## Test Workflow Examples - Implementation Note

Only file operation nodes are available (Task 13 not implemented).
Instead of using file operation nodes (which would be slow and create real files), we'll use test nodes for Task 15:

### Available Test Nodes:
- **test_node** - Basic string input/output
- **test_node_retry** - Node with retry capabilities and parameters
- **test_node_structured** - Node with nested structure outputs (created for testing)

### Example Test Workflows:
1. **test-data-pipeline**
   - Description: "Processes user data through multiple transformations"
   - Uses: test_node_structured, test_node
   - Inputs: ["user_id"]
   - Outputs: ["processed_data"]

2. **test-retry-workflow**
   - Description: "Tests retry capabilities with fallback handling"
   - Uses: test_node_retry, test_node
   - Inputs: ["retry_input"]
   - Outputs: ["final_output"]

3. **test-structured-extraction**
   - Description: "Extracts and processes nested data structures"
   - Uses: test_node_structured
   - Inputs: ["user_id"]
   - Outputs: ["user_data", "tags"]

These test workflows are better because:
- Faster execution (no file I/O)
- Test structure parsing with nested data
- Won't create/modify real files during testing
- Can test all Task 15 features including proxy mappings

## Summary

The key decisions for Task 15:

1. ✓ Use flat `~/.pflow/workflows/` directory with minimal loading implementation
2. ✓ Full metadata schema (name, description, inputs, outputs, created_at, updated_at, version, ir_version, tags, ir)
3. ✓ Nested structure format from parser
4. ✓ Name + one-line description for discovery
5. ✓ Indented structure display for planning
6. ✓ Internal delegation for backward compatibility
7. ✓ Skip missing components with warnings
8. ✓ 200KB total context limit
9. ✓ Use test nodes for creating test workflows (faster, safer, better for structure testing)

These decisions prioritize simplicity and clear boundaries while enabling the two-phase discovery pattern that Task 17's planner requires.
