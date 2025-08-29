# Task 10: Create registry CLI commands - Agent Instructions

## The Problem You're Solving

Users currently must run a temporary script (`scripts/populate_registry.py`) to populate the registry, which is not user-friendly and requires manual intervention. There's no way to search for nodes, see detailed information about them, or add custom nodes safely. This friction prevents users from discovering and using available nodes effectively.

## Your Mission

Implement CLI commands for registry operations (`pflow registry list|describe|search|scan`) that enable zero-setup node discovery, safe custom node addition with security warnings, and comprehensive node exploration capabilities.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_10/task-10.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_10/starting-context/`

**Files to read (in this order):**
1. `TASK-10-SPECIFICATION.md` - Comprehensive implementation specification with code examples
2. `task-10-spec.md` - The formal specification (FOLLOW THIS PRECISELY for requirements and test criteria)
3. `task-10-handover.md` - Critical context and warnings from investigation phase

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-10-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

A complete registry CLI system that provides four commands:

```bash
# List all registered nodes (auto-discovers core nodes on first use)
$ pflow registry list
[Auto-discovering core nodes...]
Name                 Type    Description
────────────────────────────────────────
read-file           core    Read file contents
write-file          core    Write content to file
llm                 core    Process text with LLM

# Show detailed information about a specific node
$ pflow registry describe llm
Node: llm
Type: core
Description: Process text with language models
Interface:
  Inputs:
    - prompt: str - The prompt to send to the LLM

# Search nodes by name or description
$ pflow registry search github
Found 3 nodes matching 'github':
Name                 Type    Match   Description
────────────────────────────────────────────────
github-get-issue     core    prefix  Fetch GitHub issue

# Scan for custom user nodes (with security warning)
$ pflow registry scan ~/.pflow/nodes/
⚠️  WARNING: Custom nodes execute with your user privileges.
   Only add nodes from trusted sources.
Found 1 valid node:
  ✓ my-node: Custom functionality
Add to registry? [y/N]: y
✓ Added 1 custom node to registry
```

## Key Outcomes You Must Achieve

### Core Registry Enhancements
- Add auto-discovery of core nodes on first `load()`
- Implement `search()` method with substring matching and scoring
- Add type differentiation (core/user/mcp) to stored nodes
- Support version tracking for future upgrade detection
- Add in-memory caching for performance

### CLI Command Implementation
- Create `src/pflow/cli/registry.py` with Click command group
- Implement `list` command with table and JSON output
- Implement `describe` command with full interface details
- Implement `search` command with scored results
- Implement `scan` command with security warnings and confirmation

### System Integration
- Update `src/pflow/cli/main_wrapper.py` to route "registry" commands
- Update main help text to mention registry commands
- Ensure MCP nodes (mcp-* pattern) are properly typed
- Delete `scripts/populate_registry.py` after successful implementation

## Implementation Strategy

### Phase 1: Registry Class Enhancements (2 hours)
1. Add `_auto_discover_core_nodes()` method to scan `src/pflow/nodes/` on first load
2. Implement `search()` method with scoring logic (exact=100, prefix=90, contains=70, desc=50)
3. Add `scan_user_nodes()` method for user node discovery
4. Implement `_save_with_metadata()` to store version and timestamp
5. Add `_core_nodes_outdated()` check for version changes
6. Add caching with `_cached_nodes` attribute

### Phase 2: CLI Command Group Creation (2 hours)
1. Create `src/pflow/cli/registry.py` following MCP pattern
2. Implement `list` command with auto-discovery trigger
3. Implement `describe` command with interface details
4. Implement `search` command with ranking display
5. Implement `scan` command with security warning
6. Add `--json` flag support for all commands

### Phase 3: System Integration (1 hour)
1. Update `main_wrapper.py` to add registry routing
2. Update main CLI help text
3. Test routing works correctly
4. Verify MCP nodes show correct type

### Phase 4: Testing and Cleanup (2 hours)
1. Write comprehensive tests for all commands
2. Test auto-discovery on first use
3. Test error handling and edge cases
4. Delete `scripts/populate_registry.py`
5. Update any documentation referencing the old script

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### Registry Auto-Discovery Pattern
The Registry must auto-discover core nodes on first load:
```python
def load(self) -> dict[str, dict[str, Any]]:
    """Load registry, auto-discovering core nodes if needed."""
    if not self.registry_path.exists():
        # First time - auto-discover core nodes
        self._auto_discover_core_nodes()

    nodes = self._load_from_file()

    # Check if core nodes need refresh (version change)
    if self._core_nodes_outdated(nodes):
        nodes = self._refresh_core_nodes(nodes)

    self._cached_nodes = nodes
    return nodes
```

### CLI Routing Pattern (CRITICAL!)
You MUST follow the MCP pattern exactly in `main_wrapper.py`:
```python
elif first_arg == "registry":
    # Route to Registry group
    original_argv = sys.argv[:]
    try:
        registry_index = sys.argv.index("registry")
        sys.argv = [sys.argv[0]] + sys.argv[registry_index + 1 :]
        registry()  # Call the Click group
    finally:
        sys.argv = original_argv
```

### Node Type Detection
Determine node type based on naming and paths:
```python
if name.startswith("mcp-"):
    node_type = "mcp"
elif "/src/pflow/nodes/" in metadata.get("file_path", ""):
    node_type = "core"
else:
    node_type = "user"
```

### Search Scoring Algorithm
Simple substring matching with clear scoring:
```python
score = 0
if name_lower == query_lower:
    score = 100  # Exact match
elif name_lower.startswith(query_lower):
    score = 90   # Prefix match
elif query_lower in name_lower:
    score = 70   # Name contains
elif query_lower in description_lower:
    score = 50   # Description contains
```

## Critical Warnings from Experience

### Registry.save() is Destructive
The Registry's `save()` method **completely replaces** the registry.json file. It does NOT merge or update. Always:
1. Load existing registry first
2. Modify the loaded dict
3. Save the complete dict
Never call save() with partial data!

### Scanner Returns List, Registry Wants Dict
`scan_for_nodes()` returns a **list**, but Registry stores as **dict**. Use `update_from_scanner()` for conversion, but be aware: duplicate names cause last-wins behavior.

### MCP Nodes are Virtual
MCP nodes don't have real Python files. They use `"virtual://mcp"` paths and all point to the same MCPNode class. Detect them by the `mcp-` prefix in names.

### Click Routing is Non-Standard
Don't try to use Click's normal subcommand pattern. The catch-all workflow arguments require the sys.argv manipulation hack. Follow the MCP pattern exactly.

## Key Decisions Already Made

1. **Auto-discovery on first use** - No manual setup command required
2. **Simple substring search** - No fuzzy matching or external dependencies for MVP
3. **Security warning on every scan** - Not a one-time warning, show every time
4. **Type by convention** - Use naming patterns, not metadata fields
5. **No refresh command** - Auto-refresh when version changes
6. **No validate command** - Validation happens during scan with inline warnings
7. **Delete populate_registry.py** - It's the temporary solution being replaced
8. **Placeholder versioning** - Show "1.0.0" for all nodes in MVP

## Success Criteria

Your implementation is complete when:

- ✅ Core nodes auto-discover on first `pflow registry list` (no setup needed)
- ✅ All four commands work: list, describe, search, scan
- ✅ Search scoring works correctly (exact=100, prefix=90, contains=70, desc=50)
- ✅ Security warning shows for user node scanning
- ✅ All commands support `--json` output flag
- ✅ Node types show correctly (core/user/mcp)
- ✅ Registry routing works through main_wrapper.py
- ✅ Help text updated to mention registry commands
- ✅ All 19 test criteria from spec pass
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ `scripts/populate_registry.py` is deleted

## Common Pitfalls to Avoid

1. **Don't look for existing search method** - Registry has no search, you must add it
2. **Don't try normal Click patterns** - Use the main_wrapper.py routing hack
3. **Don't forget Registry.save() is destructive** - Always load, modify, save complete data
4. **Don't add features not in spec** - No refresh command, no validate command
5. **Don't optimize prematurely** - Simple O(n) search is fine for <1000 nodes
6. **Don't skip the security warning** - It must show every time for scan
7. **Don't forget to delete populate_registry.py** - It's being replaced

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent subagents from conflicting.

### Why Planning Matters

1. **Prevents duplicate work and conflicts**: Multiple subagents won't edit the same files
2. **Identifies dependencies**: Discover what needs to be built in what order
3. **Optimizes parallelization**: Know exactly what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Registry Architecture Analysis**
   - Task: "Analyze src/pflow/registry/registry.py to understand current methods and structure"
   - Task: "Find all usages of Registry class throughout the codebase"

2. **CLI Pattern Analysis**
   - Task: "Study src/pflow/cli/mcp.py to understand the Click command group pattern"
   - Task: "Analyze main_wrapper.py routing mechanism for MCP commands"

3. **Scanner and Metadata Understanding**
   - Task: "Examine how Scanner returns data and how Registry converts it"
   - Task: "Understand MetadataExtractor output format"

4. **Testing Pattern Discovery**
   - Task: "Find existing CLI test patterns in tests/test_cli/"
   - Task: "Identify test utilities for mocking Registry"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_10/implementation/implementation-plan.md`

Your plan should include specific file assignments for each subagent, ensuring no conflicts.

### When to Revise Your Plan

Update your plan when discoveries reveal new requirements or better approaches. Document changes with rationale.

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_10/implementation/progress-log.md`

```markdown
# Task 10 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### 1. Enhance Registry class with auto-discovery and search
### 2. Create CLI command group in registry.py
### 3. Implement each command (list, describe, search, scan)
### 4. Update main_wrapper.py routing
### 5. Write comprehensive tests
### 6. Update help documentation
### 7. Delete populate_registry.py
### 8. Run full test suite and fix issues

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to [specific action]...

Result: [What happened]
- ✅ What worked: [Specific detail]
- ❌ What failed: [Specific detail]
- 💡 Insight: [What I learned]

Code that worked:
```python
# Actual code snippet
```
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION FROM PLAN
- Original plan: [what was planned]
- Why it failed: [specific reason]
- New approach: [what you're trying instead]
- Lesson: [what this teaches us]
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test what matters"

**Focus on quality over quantity**:
- Test public interfaces and critical paths
- Test edge cases where bugs typically hide
- Create integration tests when components interact
- Document only interesting test discoveries in your progress log

**What to test**:
- **Critical paths**: Auto-discovery, search scoring, security warnings
- **Public APIs**: All CLI commands with various inputs
- **Error handling**: Missing nodes, corrupted registry, invalid paths
- **Integration points**: CLI routing, Registry-Scanner interaction

**What NOT to test**:
- Simple getters/setters
- Configuration loading
- Framework code
- Internal helper functions (unless complex)

**Progress Log - Only document testing insights**:
```markdown
## 14:50 - Testing revealed edge case
Registry auto-discovery fails if src/pflow/nodes/ has __pycache__
directories. Added filtering to skip them.
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** add a refresh command - Auto-refresh on version change only
- **DON'T** add a validate command - Validation happens during scan
- **DON'T** implement fuzzy search - Simple substring matching for MVP
- **DON'T** add remote node installation - Local scanning only
- **DON'T** try to use normal Click patterns - Follow MCP routing hack
- **DON'T** forget to delete populate_registry.py - It's being replaced
- **DON'T** add features not in spec - Follow the spec precisely

## Getting Started

1. Read all context files to understand the full scope
2. Create your implementation plan with specific subagent tasks
3. Start with Registry enhancements (Phase 1)
4. Test frequently with `pytest tests/test_registry/ -v`
5. Use the handoff memo for critical warnings about existing code

## Final Notes

- The Registry class currently has almost nothing - you're adding most functionality
- The CLI routing pattern is weird but necessary - follow MCP exactly
- Security warnings are non-negotiable - users must understand the risk
- Auto-discovery eliminates setup friction - this is the key UX improvement
- The spec has all 19 test criteria that must pass

## Remember

You're implementing the user's first interaction with pflow's node system. Zero-setup auto-discovery and clear security warnings are critical for a good experience. The simple search is intentionally basic - we'll add vector search in a future task. Focus on making the MVP commands work reliably and safely.

This task significantly improves pflow's usability by replacing a manual script with proper CLI commands. Users will appreciate being able to explore nodes easily and add custom nodes safely.

Good luck! Your implementation will make pflow much more accessible to new users.