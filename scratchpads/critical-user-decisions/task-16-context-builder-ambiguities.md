# Task 16: Context Builder Implementation Decisions

This document outlines critical decisions needed before implementing the planning context builder. Each decision includes multiple options with clear trade-offs.

## 1. Node Inclusion Criteria - Importance: 4/5

The context builder must decide which nodes to include when formatting metadata for the LLM. This directly impacts the LLM's ability to build valid workflows.

### Options:

- [x] **Option A: Include only production nodes with valid Interface sections**
  - Include nodes that have at least one of: inputs, outputs, or actions in their metadata
  - Skip test nodes (files containing "test" in path or class name)
  - Skip nodes that fail to import
  - **Pros**: Clean, focused context with only working nodes
  - **Cons**: Might exclude some utility nodes without proper documentation

- [ ] **Option B: Include ALL nodes from registry**
  - Show every node, marking those without interfaces as "undocumented"
  - Include test nodes with special marking
  - **Pros**: Complete visibility of available nodes
  - **Cons**: Cluttered context, LLM might suggest test nodes inappropriately

- [ ] **Option C: Smart filtering based on metadata quality**
  - Require minimum metadata (description + at least inputs OR outputs)
  - Group undocumented nodes in separate section
  - **Pros**: Balance between completeness and quality
  - **Cons**: More complex logic, arbitrary quality threshold

**Recommendation**: Option A - Production nodes with valid interfaces provide the cleanest context for the LLM while avoiding confusion from test/utility nodes.

## 2. Import Failure Handling - Importance: 3/5

When import_node_class() fails, the context builder needs a consistent strategy for handling these failures.

### Options:

- [x] **Option A: Log warning and skip silently**
  - Log the failure with logger.warning()
  - Don't include the node in the output at all
  - **Pros**: Clean output, no broken nodes shown to LLM
  - **Cons**: Silent failures might hide configuration issues

- [ ] **Option B: Include with error notation**
  - Add node with special section: "⚠️ Import Error: module not found"
  - **Pros**: Visibility into what's broken
  - **Cons**: LLM might still try to use broken nodes

- [ ] **Option C: Collect and report at end**
  - Skip in main output but add summary at end: "3 nodes failed to import"
  - **Pros**: Awareness without cluttering main context
  - **Cons**: Additional complexity for marginal benefit

**Recommendation**: Option A - Silent skip with logging keeps the context clean while preserving debugging information in logs.

## 3. Output Format Structure - Importance: 4/5

The markdown structure significantly impacts LLM comprehension and node selection accuracy.

### Options:

- [x] **Option A: Grouped by directory with consistent headers**
  ```markdown
  ## File Operations

  ### read-file
  Reads content from a file...

  **Inputs**: `file_path`, `encoding`
  **Outputs**: `content` (success), `error` (failure)

  ### write-file
  ...

  ## Git Operations
  ...
  ```
  - **Pros**: Logical grouping, easy scanning, clear categories
  - **Cons**: Requires inferring categories from paths

- [ ] **Option B: Flat list with detailed subsections**
  - All nodes at same level with inputs/outputs/params/actions subsections
  - **Pros**: Consistent structure, no categorization needed
  - **Cons**: Harder to scan, no logical grouping

- [ ] **Option C: Table format**
  - Markdown table with columns: Node, Description, Inputs, Outputs
  - **Pros**: Compact, easy to compare
  - **Cons**: Limited space for details, harder to read complex nodes

**Recommendation**: Option A - Grouping by operation type helps LLM understand relationships and select appropriate nodes for tasks.

## 4. Parameter Section Redundancy - Importance: 3/5

Many node parameters duplicate their inputs (can be provided via shared store OR params). How should we present this?

### Options:

- [x] **Option A: Show Parameters only when different from Inputs/Outputs**
  - Omit Parameters section if all params are already listed in Inputs
  - Add note: "Parameters mirror inputs" when applicable
  - **Pros**: Reduces redundancy, cleaner output
  - **Cons**: Might miss nuance about dual-input pattern

- [ ] **Option B: Always show Parameters section**
  - List all parameters even if redundant
  - Add explanation about shared store vs params pattern
  - **Pros**: Complete information, reinforces the pattern
  - **Cons**: Verbose, repetitive

- [ ] **Option C: Merge into Inputs with notation**
  - Show as: **Inputs**: `file_path` (⚡ also available as param)
  - **Pros**: Compact while preserving information
  - **Cons**: Non-standard notation might confuse

**Recommendation**: Option A - Reducing redundancy keeps context focused while a single explanation at the top can clarify the pattern.

## 5. Missing Metadata Handling - Importance: 2/5

Some nodes may have no Interface section or empty metadata. How should these be presented?

### Options:

- [ ] **Option A: Include with standard "No interface information" note**
  - Show node name and description (if available)
  - Add italic note: *No interface information available*
  - **Pros**: Completeness, honest about limitations
  - **Cons**: Limited usefulness to LLM

- [x] **Option B: Skip entirely**
  - Don't include nodes without interface data
  - **Pros**: Only useful nodes in context
  - **Cons**: Might hide nodes that work but lack docs

- [ ] **Option C: Separate section for undocumented nodes**
  - Main section for documented nodes
  - "Other Available Nodes" section at end
  - **Pros**: Organization while maintaining completeness
  - **Cons**: Additional complexity

**Recommendation**: Option B - Skipping entirely is the simplest solution and nodes without interface data are not useful to the LLM.

## 6. Registry Data Source - Importance: 2/5

The function signature expects registry_metadata, but the exact format needs clarification.

### Options:

- [x] **Option A: Receive pre-loaded registry dict**
  - Caller does `registry.load()` and passes result
  - Function signature: `build_context(registry_metadata: dict[str, dict[str, Any]])`
  - **Pros**: Simple, testable, follows task description
  - **Cons**: Caller must handle registry initialization

- [ ] **Option B: Receive Registry instance**
  - Function loads data itself
  - Function signature: `build_context(registry: Registry)`
  - **Pros**: More control over loading
  - **Cons**: Deviates from task specification

**Recommendation**: Option A - Follows the task specification exactly and keeps the function focused on formatting.

## 7. Performance and Size Limits - Importance: 2/5

The context could grow large with many nodes. Should we implement limits?

### Options:

- [x] **Option A: No limits in MVP, add monitoring**
  - Generate full context regardless of size
  - Log warning if >50 nodes or >10KB of text
  - **Pros**: Simple, complete information
  - **Cons**: Might hit LLM context limits eventually

- [ ] **Option B: Implement hard limits**
  - Cap at 50 most important nodes
  - Prioritize by metadata completeness
  - **Pros**: Prevents context overflow
  - **Cons**: Premature optimization, might exclude needed nodes

- [ ] **Option C: Configurable limits**
  - Add optional max_nodes parameter
  - **Pros**: Flexibility
  - **Cons**: Additional complexity for MVP

**Recommendation**: Option A - Start simple with monitoring to understand real-world usage before adding limits.

## Additional Context for Implementation

### Context for Decision 1: Node Inclusion Criteria

**Current State**: The registry contains both production nodes (in `src/pflow/nodes/`) and test nodes (`test_node.py`, `test_node_retry.py`). Test nodes have minimal or no Interface sections and are used for scanner validation.

**LLM Impact**: Including test nodes would pollute the context with non-functional examples. The LLM might suggest `test-node` in actual workflows, causing runtime failures.

**Example**:
- Production: `ReadFileNode` has full Interface with inputs/outputs/actions
- Test: `TestNode` has minimal Interface for testing scanner functionality

### Context for Decision 2: Import Failure Handling

**Common Failure Causes**:
- Missing dependencies (e.g., node requires `requests` but it's not installed)
- Syntax errors in node files during development
- Incorrect module paths in registry after refactoring

**Downstream Effect**: Task 17's planner relies on this context. Silent failures mean the LLM won't suggest broken nodes, preventing workflow generation errors.

### Context for Decision 3: Output Format Structure

**Directory Structure Reality**:
```
src/pflow/nodes/
├── file/      # read_file, write_file, copy_file, etc.
├── git/       # git_commit, git_push (future)
├── github/    # github_get_issue (future)
└── llm.py     # General LLM node (future)
```

**Grouping Benefits**: The LLM can understand semantic relationships. When asked to "work with files", it knows to look in the File Operations section.

### Context for Decision 4: Parameter Section Redundancy

**The Unique pflow Pattern**:
```python
# Nodes check shared store first, then params:
file_path = shared.get("file_path") or self.params.get("file_path")
```

**Why This Matters**: The LLM needs to understand it can either:
- Connect nodes via shared store: `read-file >> write-file` (automatic data flow)
- Set params directly: `read-file --file_path=/tmp/test.txt`

### Context for Decision 5: Missing Metadata Handling

**Reality Check**: Task 7's extractor returns empty lists for nodes without Interface sections:
```python
{'description': 'A utility node', 'inputs': [], 'outputs': [], 'params': [], 'actions': []}
```

**LLM Understanding**: The LLM needs to know these nodes exist but can't effectively use them without understanding their I/O.

### Context for Decision 6: Registry Data Source

**Integration Point**: Task 17 will likely:
```python
registry = Registry()
registry_data = registry.load()  # Returns dict[str, dict[str, Any]]
context = build_context(registry_data)
# Use context in LLM prompt
```

**Testing Benefit**: Passing a dict makes unit testing trivial without file system dependencies.

### Context for Decision 7: Performance and Size Limits

**Current Scale**: ~11 file nodes exist. With planned nodes (git, github, llm, claude-code, CI), expect ~30-40 nodes total in MVP.

**LLM Context Reality**:
- Each node description: ~200-500 tokens
- 40 nodes ≈ 8,000-20,000 tokens
- Well within Claude's 100k+ context window

**Future Consideration**: v2.0 with MCP integration might have 100s of nodes, requiring pagination or filtering strategies.

## Summary of Recommendations

1. Include only production nodes with valid Interface sections
2. Skip failed imports with logging
3. Group nodes by category with clear markdown structure
4. Show Parameters only when different from Inputs
5. Include nodes with missing metadata with a note
6. Receive pre-loaded registry dict as specified
7. No size limits but monitor usage

These decisions optimize for LLM comprehension while keeping the implementation straightforward for the MVP.
