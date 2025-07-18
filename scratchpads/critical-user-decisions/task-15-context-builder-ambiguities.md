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

## Background Context

### What is the Context Builder?

The context builder is a critical component in pflow that transforms registry metadata into LLM-friendly markdown documentation. It serves as the bridge between pflow's node registry and the Natural Language Planner (Task 17), providing the planner with information about available nodes and workflows.

**Current Flow (Task 16)**:
1. Registry provides metadata dict: `{"node-id": {metadata}}`
2. Context builder formats this into readable markdown
3. Planner uses this context to understand available components

### The Two-Phase Discovery Problem

The original context builder (Task 16) creates a single large context with all node details. This causes "LLM overwhelm" - too much information for effective decision-making. Task 15 solves this by splitting into two phases:

1. **Discovery Phase**: Lightweight context with just names/descriptions
   - LLM browses available components
   - Selects potentially relevant ones

2. **Planning Phase**: Detailed context for selected components only
   - Full interface specifications
   - Structure information for data mapping
   - Enables precise workflow generation

### What are Proxy Mappings?

Proxy mappings are pflow's solution to incompatible node interfaces. When nodes don't naturally connect:

```
youtube-transcript writes: shared["transcript"]
llm reads: shared["prompt"]
```

Proxy mappings bridge this gap:
```json
{"prompt": "transcript"}  // Simple mapping
{"author": "issue_data.user.login"}  // Path-based mapping
```

Task 15's structure display decisions directly enable the planner to generate these mappings.

### Task Relationships

- **Task 16**: Created original `build_context()` function (single-phase)
- **Task 15**: Extends with two-phase approach and workflow discovery
- **Task 17**: The Natural Language Planner that will consume these contexts

The flow: User request → Planner calls discovery → Planner calls planning → Planner generates workflow

## Current Implementation Status

### What Already Exists

**1. The Context Builder (Task 16)**
```python
def build_context(registry_metadata: dict[str, dict[str, Any]]) -> str:
    """Current implementation creates a single markdown document with all nodes."""
    # Groups nodes by category (File Operations, AI/LLM Operations, etc.)
    # Formats each node with inputs, outputs, params, actions
    # Returns markdown like:
    # ### read-file
    # Reads content from a file
    # **Inputs**: file_path, encoding
    # **Outputs**: content, error
```

**2. Enhanced Interface Format**
Nodes now use structured docstrings:
```python
"""
Interface:
- Reads: shared["file_path"]: str  # Path to the file
- Writes: shared["content"]: str  # File contents
- Writes: shared["metadata"]: dict  # File metadata
    - size: int  # File size in bytes
    - modified: str  # Last modified timestamp
- Params: encoding: str  # File encoding (default: utf-8)
"""
```

**3. Structure Parser Implementation**
A 70-line recursive parser (`_parse_structure()` in metadata_extractor.py) that:
- Detects indented structure definitions
- Parses nested dictionaries and lists
- Handles descriptions for each field
- Returns nested dict representation

**4. Registry Metadata Format**
```python
{
    "read-file": {
        "module_path": "src.pflow.nodes.file.read_file",
        "class_name": "ReadFileNode",
        "metadata": {
            "description": "Reads content from a file",
            "inputs": [
                {"key": "file_path", "type": "str", "description": "Path to file"}
            ],
            "outputs": [
                {"key": "content", "type": "str", "description": "File contents",
                 "_has_structure": True, "structure": {...}}
            ]
        }
    }
}
```

## Key Concepts

### Nodes vs Workflows

**Nodes**: Individual, atomic operations (read-file, llm, github-get-issue)
- Defined in Python classes
- Have fixed interfaces (inputs/outputs)
- Execute single operations

**Workflows**: Compositions of nodes
- Saved as JSON IR (Intermediate Representation)
- Can be parameterized with template variables
- Reusable - "Plan Once, Run Forever"

### Discovery vs Planning Phases

**Discovery**: "What components might be useful?"
- Lightweight browsing
- Over-inclusive is fine
- Reduces cognitive load

**Planning**: "How do I connect these specific components?"
- Detailed interface information
- Enables proxy mapping generation
- Focused on selected components only

### Template Variables and Reusability

Workflows use template variables for reusability:
```json
{
    "nodes": [{
        "id": "fetch",
        "type": "github-get-issue",
        "params": {"issue_number": "$issue"}  // Template variable
    }]
}
```

Execution: `pflow fix-issue --issue=1234` → `$issue` becomes `1234`

### Shared Store and Data Flow

Pflow uses a shared store for inter-node communication:
- Nodes read inputs: `shared["key"]`
- Nodes write outputs: `shared["key"] = value`
- Proxy mappings route data when keys don't match

## Why These Decisions Matter

Each decision in this document directly impacts the success of Task 17's Natural Language Planner:

### Two-Phase Approach Impact
- **Reduces LLM errors**: Focused context prevents wrong selections
- **Improves performance**: Less tokens to process in each phase
- **Enables iteration**: Discovery errors can be corrected before planning

### LLM Comprehension Focus
- **Structure display format** → Accurate proxy mapping generation
- **No length limits** → Better component disambiguation
- **Combined JSON + paths** → Multiple mental models for accuracy

### Workflow Reusability
- **Storage decisions** → Enable "Plan Once, Run Forever"
- **Full metadata** → Better workflow discovery and versioning
- **Template variables** → Parameterized execution

### Error Recovery
- **Missing components** → Return to discovery, not partial workflows
- **Invalid workflows** → Skip with warnings, don't crash
- **Clear terminology** → Reduce implementation confusion

## Integration Points

### How the Planner Will Use These Functions

**1. Discovery Flow**:
```python
# Planner's discovery phase
all_node_ids = list(registry.get_metadata().keys())
all_workflows = load_saved_workflows()  # Task 15 implements this
discovery_context = build_discovery_context(all_node_ids, [w['name'] for w in all_workflows])
# LLM selects from discovery_context
selected = ["github-get-issue", "llm", "fix-issue-workflow"]
```

**2. Planning Flow**:
```python
# Planner's planning phase
planning_context = build_planning_context(
    selected_node_ids=["github-get-issue", "llm"],
    selected_workflow_names=["fix-issue-workflow"],
    registry_metadata=registry.get_metadata(),
    saved_workflows=all_workflows
)
# If missing components detected:
if isinstance(planning_context, dict) and "error" in planning_context:
    # Return to discovery with error info
    return to_discovery_with_feedback(planning_context["missing_nodes"])
```

**3. Structure Usage for Proxy Mappings**:
```markdown
From planning context:
Available paths:
- issue_data.user.login (str) - GitHub username

Planner generates:
{"author": "issue_data.user.login"}
```

### Backward Compatibility

The existing `build_context()` continues working by internally calling both new functions, ensuring tests don't break while enabling the new two-phase approach.

## 1. Workflow Storage Location and Management - Decision importance (4)

How should workflows be stored, organized, and discovered?

### Why This Decision Matters:
Workflow storage enables the core value proposition of pflow - "Plan Once, Run Forever". Without persistent storage, users would need to regenerate workflows every time. Task 15 must implement loading to enable workflow discovery, even though saving comes later in Task 17.

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

**The Chicken-and-Egg Problem**:
Task 15 needs to discover workflows that don't exist yet. Solution: Implement minimal loading infrastructure that Task 17 can use for saving.

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

### Why This Decision Matters:
The structure format directly determines how the planner generates proxy mappings. Without proper structure representation, the planner cannot create mappings like `"author": "issue_data.user.login"`. This is essential for connecting nodes with incompatible interfaces.

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
- No need to limit the length of the description in any way

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

### Why This Decision Matters:
This is the most common error scenario - LLMs often hallucinate component names or make typos. The wrong approach (skipping missing components) would create broken workflows. The right approach enables graceful recovery through the discovery phase.

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
The planning context will be read ONLY by an LLM (not humans). The LLM needs to understand data structures to generate valid proxy mappings like `"author": "issue_data.user.login"`. We must optimize for LLM comprehension and accuracy.

### LLM Processing Considerations:
- LLMs excel at pattern matching from training data
- Direct copying is more reliable than path reconstruction
- Multiple representations reduce errors through redundancy
- API documentation patterns are highly familiar from training

### Options:

- [ ] **Option A: Inline JSON**
  ```markdown
  **Outputs**:
  - `issue_data: dict` - {"number": "int", "user": {"login": "str"}}
  ```
  - **LLM perspective**: Requires path reconstruction, error-prone

- [ ] **Option B: Indented structure**
  ```markdown
  **Outputs**:
  - `issue_data: dict` - Complete issue data
    Structure of issue_data:
      - number: int - Issue number
      - user: dict - Author info
        - login: str - Username
  ```
  - **LLM perspective**: Must track indentation, reconstruct paths mentally

- [ ] **Option C: Table format**
  ```markdown
  | Path | Type | Description |
  |------|------|-------------|
  | issue_data.user.login | str | Username |
  ```
  - **LLM perspective**: Good but verbose, less common in training

- [ ] **Option D: Explicit paths only**
  ```markdown
  **Outputs**:
  - issue_data.user.login (str) - GitHub username
  - issue_data.user.id (int) - User ID
  ```
  - **LLM perspective**: Direct copying possible, but lacks structure context

- [x] **Option E: Combined format (JSON + Paths)** ✓ **SELECTED**
  ```markdown
  **Outputs**:
  - `issue_data: dict` - Complete issue data from GitHub API

  Structure (JSON format):
  ```json
  {
    "issue_data": {
      "number": "int",
      "title": "str",
      "user": {
        "login": "str",
        "id": "int"
      },
      "labels": [
        {
          "name": "str",
          "color": "str"
        }
      ]
    }
  }
  ```

  Available paths:
  - issue_data.number (int) - Issue number
  - issue_data.title (str) - Issue title
  - issue_data.user.login (str) - GitHub username
  - issue_data.user.id (int) - User ID
  - issue_data.labels[].name (str) - Label name
  - issue_data.labels[].color (str) - Label color
  ```

**LLM Benefits of Combined Approach**:
1. **Dual pattern recognition**: JSON for structure understanding, paths for mapping generation
2. **Error reduction**: Redundancy allows cross-validation between formats
3. **Zero reconstruction**: Can copy paths directly for proxy mappings
4. **Training familiarity**: This exact combination appears in countless API docs
5. **Cognitive flexibility**: Use JSON when understanding relationships, use paths when generating mappings

**Implementation Note**: With typical workflows using 5-20 nodes, the token overhead of dual representation is negligible compared to the accuracy improvements. This also enables A/B testing of which format performs better in practice.

### Implementation Requirements for Combined Format

The parser already produces a nested structure that needs to be transformed into two display formats:

**Parser Output** (from `_parse_structure()`):
```python
{
    "user": {
        "type": "dict",
        "description": "Author information",
        "structure": {
            "login": {"type": "str", "description": "Username"},
            "id": {"type": "int", "description": "User ID"}
        }
    }
}
```

**Required Transformations**:

1. **For JSON Display**:
   - Strip descriptions, keep only types
   - Convert nested "structure" dicts to clean JSON representation
   - Handle arrays by showing example item structure

2. **For Path List**:
   - Flatten the nested structure into dot-notation paths
   - Preserve descriptions for each path
   - Add array notation (e.g., `labels[]`) where appropriate
   - Generate one line per available path

The implementing agent will need to create these transformation functions in the context builder to convert the single parser output into both display formats.

**Recommendation**: Option E - Combined format provides optimal LLM comprehension through redundant representations. Each format complements the other, reducing errors and improving proxy mapping accuracy.

## 10. Performance Constraints - Decision importance (2)

What are the performance boundaries?

### Context:
The handoff mentions 200KB MAX_OUTPUT_SIZE but also 50KB in specs.

### Clarifications:

- [x] **No enforced limits in MVP** - Modern LLMs have huge context windows
- [x] **Context math**: 200KB ≈ 50,000 tokens, well within Sonnet's 200,000 token limit
- [x] **Discovery context**: No artificial limits - as many components as needed
- [x] **Planning context**: No limits - show all selected components fully
- [x] **Workflow file size**: Non-issue - workflow JSONs are tiny (few KB)

### MVP Approach:
1. **Load all workflows at once** - Simpler than lazy loading, negligible performance impact
2. **No description truncation** - Quality descriptions prevent errors
3. **No size-based filtering** - Workflow files are inherently small
4. **Consider structure caching only if profiling shows it's slow** - Measure first

### What NOT to implement:
- ❌ Arbitrary size limits
- ❌ Description length limits
- ❌ Lazy loading (unnecessary complexity)
- ❌ Workflow size filtering
- ❌ Timeout constraints

**Recommendation**: Keep it simple. No artificial limits in MVP. The only optimization worth considering is caching parsed structures IF profiling shows the recursive parser is slow. Everything else is premature optimization for non-existent problems.

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

## Example Usage

### Discovery Context Output

```markdown
## Available Nodes

### File Operations
### read-file
Read content from a file and add line numbers for display

### write-file
Write content to a file with automatic directory creation

### AI/LLM Operations
### llm
General-purpose language model for text processing

### test-node-structured
Test node that produces structured output data

## Available Workflows

### backup-files
Creates backups of specified files with timestamps

### test-data-pipeline
Processes user data through multiple transformations
```

### Planning Context Output

```markdown
## Selected Components

### read-file
Read content from a file and add line numbers for display

**Inputs**:
- `file_path: str` - Path to the file to read
- `encoding: str` - File encoding (default: utf-8)

**Outputs**:
- `content: str` - File contents with line numbers
- `error: str` - Error message if operation failed

**Parameters**:
- `validate: bool` - Validate file exists before reading

### test-node-structured
Test node that produces structured output data

**Inputs**:
- `user_id: str` - User ID to fetch data for

**Outputs**:
- `user_data: dict` - User information

Structure (JSON format):
```json
{
  "user_data": {
    "id": "str",
    "profile": {
      "name": "str",
      "email": "str",
      "age": "int"
    },
    "preferences": {
      "theme": "str",
      "notifications": "bool"
    }
  }
}
```

Available paths:
- user_data.id (str) - User ID
- user_data.profile.name (str) - Full name
- user_data.profile.email (str) - Email address
- user_data.profile.age (int) - Age in years
- user_data.preferences.theme (str) - UI theme preference
- user_data.preferences.notifications (bool) - Email notifications enabled
```

### How the Planner Uses This

1. **From user request**: "Get user data and save their name to a file"
2. **Discovery phase**: Planner sees all available nodes/workflows
3. **Selection**: Chooses `test-node-structured` and `write-file`
4. **Planning phase**: Gets detailed interfaces for just these two
5. **Proxy mapping generation**:
   ```json
   {
     "content": "user_data.profile.name"
   }
   ```
6. **Workflow generation**: Creates IR with proper data flow

## Testing Strategy Context

### Why Test Nodes?

**Production nodes** (file operations):
- Slow I/O operations
- Create/modify real files
- Hard to clean up
- Side effects complicate testing

**Test nodes**:
- Pure in-memory operations
- Instant execution
- No side effects
- Structured output for testing path-based mappings

### Test Scenarios

1. **Discovery Context Generation**
   - Test with 0, 1, 10, 100 nodes
   - Mix of nodes and workflows
   - Verify markdown formatting

2. **Planning Context Generation**
   - Test structure display (JSON + paths)
   - Missing component error handling
   - Large structure formatting

3. **Workflow Loading**
   - Invalid JSON handling
   - Missing required fields
   - Directory doesn't exist

4. **Integration Tests**
   - Full discovery → planning flow
   - Error recovery flow
   - Backward compatibility

### Test Workflows

Using test nodes, we'll create workflows that validate:
- Basic data flow
- Structure extraction
- Proxy mapping scenarios
- Workflow composition

> Note: These test workflows does not exists yet, you will need to create them as part of implementing this task (task 15).

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
4. ✓ Name + description for discovery (no length limits)
5. ✓ Combined JSON + paths display for optimal LLM comprehension
6. ✓ Internal delegation for backward compatibility with better terminology
7. ✓ Skip invalid workflow files with warnings
8. ✓ Return error info when components missing (for discovery retry)
9. ✓ Use test nodes for creating test workflows (faster, safer, better for structure testing)
10. ✓ No artificial limits in MVP - avoid premature optimization

These decisions prioritize simplicity, LLM comprehension, and pragmatic implementation while enabling the two-phase discovery pattern that Task 17's planner requires.
