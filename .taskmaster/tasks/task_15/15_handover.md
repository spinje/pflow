# Task 15 Handoff: Context Builder Evolution for Two-Phase Discovery

**IMPORTANT**: Please read this entire handoff before beginning implementation. When you're done, just say you're ready to begin - don't start implementing yet.

## Critical Context You Need to Know

### The "Aha!" Moment That Changes Everything

The original context builder (Task 16) was built with a single-phase approach - dump everything into one markdown document. But after deep analysis of the planner requirements, we discovered this creates a fundamental problem:

**The LLM gets overwhelmed with 100+ nodes' full interface details when it's just trying to select which 3-4 components to use.**

This led to the two-phase insight:
1. **Discovery Phase**: "What should I use?" (names + descriptions only)
2. **Planning Phase**: "How do I connect them?" (full details for selected items only)

### Critical Discovery #1: Workflows ARE Building Blocks

Initially, we thought workflows were just saved executions. **Wrong.** They're reusable components that can be composed into other workflows. This means:

```markdown
# Discovery context should show:
### fix-github-issue (workflow)
Analyzes a GitHub issue and creates a PR with fix

# Not just nodes!
```

The planner can then use existing workflows inside new workflows, enabling powerful composition.

### Critical Discovery #2: Structure Documentation is NOT Optional

Section 2.1 of the ambiguities document reveals why structure documentation is critical for MVP:

**Without structure information, the planner cannot generate path-based proxy mappings for custom APIs.**

Example of what the planner needs to generate:
```json
{
  "input_mappings": {
    "author_name": "issue_data.user.login"  // How does it know .user.login exists?
  }
}
```

The planner can't generate these paths without knowing the structure. It's not about validation - it's about **generation capability**.

## Key Implementation Insights

### 1. The Context Builder Split Pattern

The existing `build_context()` function should remain for backward compatibility. Add two new functions:

```python
def build_discovery_context(registry_metadata, saved_workflows=None):
    """Lightweight - just names and descriptions"""
    # Key insight: Reuse the exact same markdown format, just less detail
    # This makes it familiar to the LLM

def build_planning_context(selected_components):
    """Full details - but only for what's needed"""
    # selected_components is a list of node types and workflow names
    # Only load and format these specific items
```

### 2. Workflow Discovery Implementation

Workflows are stored in `~/.pflow/workflows/*.json` with this structure:
```json
{
  "name": "fix-github-issue",
  "description": "Analyzes a GitHub issue and creates a PR with fix",
  "inputs": ["issue_number"],
  "outputs": ["pr_number"],
  "ir": { ... }
}
```

**Critical**: You need the description field for semantic matching. The name alone isn't enough.

### 3. Structure Documentation Parsing

The metadata extractor needs to handle a new docstring format:

```python
"""
Outputs:
- issue_data: {
    "id": int,
    "title": str,
    "user": {"login": str},
    "labels": [{"name": str}]
  }
"""
```

**But maintain backward compatibility with**:
```python
"""
Outputs:
- issue_data
- issue_title
"""
```

### 4. Performance Considerations

The original context builder already has a 50KB limit (`MAX_OUTPUT_SIZE`). With two-phase approach:
- Discovery context can include many more items (just names)
- Planning context will be much smaller (only selected items)

## Files You Must Understand

1. **`/Users/andfal/projects/pflow/scratchpads/critical-user-decisions/task-17-planner-ambiguities.md`**
   - Section 2.1 explains WHY structure documentation is critical
   - Section 12 explains the two-phase discovery pattern
   - This is the source of truth for these requirements

2. **`/Users/andfal/projects/pflow/src/pflow/planning/context_builder.py`**
   - Current implementation to extend
   - Note the existing patterns for formatting and filtering

3. **`/Users/andfal/projects/pflow/src/pflow/registry/metadata_extractor.py`**
   - Needs extension for structure parsing
   - Be careful with the docstring parsing logic

4. **`/Users/andfal/projects/pflow/examples/advanced/github-workflow.json`**
   - Shows the kind of complex nested data structures nodes work with
   - This is what structure documentation needs to describe

## Critical Warnings

### 1. Don't Break Existing Functionality
The current `build_context()` is used by other parts of the system. Keep it working as-is while adding new functions.

### 2. Structure Parsing Complexity
Parsing Python-dict-like syntax from docstrings is tricky. Consider:
- Using `ast.literal_eval()` for safety
- Handling malformed structures gracefully
- Supporting both JSON-like and Python-dict syntax

### 3. Workflow Loading Edge Cases
- What if ~/.pflow/workflows/ doesn't exist?
- What if a workflow file is corrupted?
- What if a workflow has no description?

### 4. The Context Builder Module Location
Note that context_builder.py is in `src/pflow/planning/` not `src/pflow/registry/`. This is intentional - it's part of the planning subsystem.

## Anti-Patterns to Avoid

1. **Don't load all node details in discovery phase** - That's the whole point of splitting
2. **Don't make structure documentation required** - Many simple nodes don't need it
3. **Don't parse structure for every output** - Only when explicitly provided in new format

## Testing Priorities

1. **Two-phase flow**: Discovery returns lightweight, planning returns detailed
2. **Structure parsing**: Both valid and invalid syntax
3. **Workflow discovery**: With and without saved workflows
4. **Backward compatibility**: Existing build_context() still works

## The Hidden Dependency

Task 16 created the foundation, but it made assumptions that need adjustment:
- Single-phase context building
- Nodes-only focus
- No structure information

Your job is to evolve it while maintaining what works.

## Final Critical Insight

The planner's success depends on getting the right information at the right time:
- **Too much info in discovery** = LLM picks wrong components
- **Too little info in planning** = LLM can't connect components
- **No structure info** = Can't generate proxy mappings for real APIs

This task is about finding that balance.

## What is NOT in Scope (Critical Boundaries)

### 1. Planner Implementation Details
- **NOT**: Implementing the actual workflow selection logic
- **NOT**: Creating LLM prompts for workflow generation
- **NOT**: Building the component selection algorithm
- **Just**: Providing the context data in the right format

### 2. Proxy Mapping and Execution
- **NOT**: Generating actual proxy mappings from structure documentation
- **NOT**: Validating that paths in proxy mappings are correct
- **NOT**: Implementing the path resolution logic (e.g., `issue_data.user.login`)
- **Just**: Parsing and exposing the structure information

### 3. Workflow Management
- **NOT**: Creating workflows or modifying how they're stored
- **NOT**: Implementing workflow validation or execution
- **NOT**: Building workflow versioning or history tracking
- **NOT**: Creating a workflow management CLI
- **Just**: Reading existing workflows and extracting name/description

### 4. Registry Modifications
- **NOT**: Changing how nodes are registered or discovered
- **NOT**: Modifying the registry's storage format
- **NOT**: Adding new node types or categories
- **Just**: Extending metadata extraction for structure documentation

### 5. Runtime Features
- **NOT**: Template variable resolution (that's runtime's job)
- **NOT**: Actual data flow tracking during execution
- **NOT**: Implementing caching for context building
- **Just**: Static analysis of what nodes declare

### 6. Search and Discovery Logic
- **NOT**: Implementing semantic search or similarity matching
- **NOT**: Building embeddings or vector storage
- **NOT**: Creating the "find or build" decision logic
- **Just**: Formatting the available options for the planner

### 7. User-Facing Features
- **NOT**: Creating end-user documentation for structure format
- **NOT**: Building migration tools for old docstring formats
- **NOT**: Creating workflow templates or examples
- **NOT**: Implementing any CLI commands
- **Just**: Internal functions for the planner to use

### 8. Validation and Type Checking
- **NOT**: Validating that structure documentation matches actual node behavior
- **NOT**: Type checking the structure definitions
- **NOT**: Enforcing structure documentation requirements
- **Just**: Parsing what's there and passing it along

### Why These Boundaries Matter

The context builder's job is to be a **data provider**, not a **decision maker**. It should:
- Format information clearly
- Make no judgments about what's "better"
- Not implement any business logic
- Stay focused on extraction and presentation

If you find yourself writing code that:
- Makes decisions about which nodes to use
- Validates workflow correctness
- Generates IR or proxy mappings
- Implements search algorithms

**STOP** - that's outside this task's scope.

---

**Remember**: Don't start implementing yet. Just acknowledge you've read this handoff and are ready to begin when instructed.
