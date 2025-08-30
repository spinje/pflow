# Task 15 Project Context: Extend Context Builder for Two-Phase Discovery

## Task Overview

Task 15 extends the existing context builder (from Task 16) to support a sophisticated two-phase discovery approach and workflow reuse. This is essential for the Natural Language Planner (Task 17) to avoid LLM overwhelm and generate accurate workflows.

**Core Mission**: Split context building into discovery (lightweight browsing) and planning (detailed interfaces) phases, while adding workflow discovery support.

## Key Concepts

### Two-Phase Discovery Pattern

**Problem**: Single large context with all node details causes "LLM overwhelm" - too much information for effective decision-making.

**Solution**: Two-phase approach:
1. **Discovery Phase**: Lightweight markdown with just names/descriptions for browsing
2. **Planning Phase**: Detailed markdown with full interfaces for selected components only

### Proxy Mappings and Structure Documentation

Proxy mappings solve incompatible node interfaces:
```json
// Simple mapping
{"prompt": "transcript"}

// Path-based mapping (requires structure info)
{"author": "issue_data.user.login"}
```

Task 15's structure display enables the planner to generate these path-based mappings by showing available data paths.

### Workflow Reuse

Workflows are saved JSON IR compositions that can be reused as building blocks:
- Stored in `~/.pflow/workflows/*.json`
- Include metadata (name, description, inputs, outputs)
- Enable "Plan Once, Run Forever" philosophy
- Can be composed into other workflows

## Current State (from Task 16)

### What Already Exists

1. **Context Builder** (`src/pflow/planning/context_builder.py`):
   - `build_context()` - Creates single markdown with all nodes
   - `_process_nodes()` - Extracts metadata using PflowMetadataExtractor
   - `_format_node_section()` - Formats individual node details
   - `_format_structure()` - Displays hierarchical data (needs enhancement)
   - Groups nodes by category (File Operations, AI/LLM Operations, etc.)

2. **Metadata Extractor** (enhanced in Task 14):
   - Parses enhanced interface format from docstrings
   - Extracts structure information for complex types
   - Sets `_has_structure` flag when structures detected
   - Recursive parser implemented (lines 543-612)

3. **Critical Parser Fixes** (must preserve):
   - Multi-line support using `.extend()` not assignment
   - Comma-aware regex for shared keys and params
   - Exclusive params pattern (params not in Reads are filtered)
   - All 7 nodes migrated to enhanced format

## Architecture Context

### Where This Fits

```
Registry (Task 5) → Metadata Extractor (Task 7/14) → Context Builder (Task 15/16) → Planner (Task 17)
```

The context builder is the bridge that transforms technical metadata into LLM-friendly documentation.

### Integration with Natural Language Planner

The planner will use the two functions like this:

```python
# Discovery: "What components might help?"
discovery_ctx = build_discovery_context()  # All available
# LLM selects relevant components

# Planning: "How do I connect these?"
planning_ctx = build_planning_context(selected_components)
# LLM generates workflow with proxy mappings
```

## What Task 15 Needs to Implement

### 1. Split Context Builder into Two Functions

```python
def build_discovery_context(node_ids=None, workflow_names=None):
    """Lightweight context with names/descriptions only."""

def build_planning_context(selected_node_ids, selected_workflow_names,
                         registry_metadata, saved_workflows=None):
    """Detailed context with full interfaces for selected components."""
```

### 2. Add Workflow Discovery Support

```python
def _load_saved_workflows():
    """Load workflows from ~/.pflow/workflows/*.json"""
```

- Create directory if missing
- Parse and validate JSON files
- Skip invalid files with warnings
- Return list of workflow metadata

### 3. Enhance Structure Display

Current `_format_structure()` shows hierarchical format. Need to add:
- Combined JSON + paths format for optimal LLM comprehension
- Path extraction for proxy mapping generation
- Example: `issue_data.user.login (str) - GitHub username`

### 4. Handle Missing Components

When selected components don't exist:
- Return error dict with details
- Enable planner to retry discovery with feedback
- Don't create partial contexts

## Relevant Patterns from Completed Tasks

### From Task 16 (Context Builder)
- Dynamic imports for node classes
- Category grouping logic
- Exclusive params filtering pattern
- Performance considerations (200KB output limit)

### From Task 14 (Enhanced Metadata)
- Structure parsing is fully implemented
- All nodes use enhanced format
- Parser is fragile - regex changes break tests
- Empty params arrays expected by tests

### From Task 7 (Metadata Extractor)
- Interface format parsing
- Structure extraction logic
- Backward compatibility handling

## Essential Documentation References

### For Implementation
- `/src/pflow/planning/context_builder.py` - Current implementation
- `/src/pflow/registry/metadata_extractor.py` - Structure parser
- `.taskmaster/tasks/task_15/task-15-context-builder-ambiguities.md` - Detailed decisions
- `.taskmaster/tasks/task_15/task-15-technical-implementation-guide.md` - Code locations

### For Understanding
- `architecture/features/planner.md` - How planner uses context
- `architecture/core-concepts/shared-store.md` - Proxy mapping concepts
- `architecture/core-concepts/registry.md` - Registry architecture
- `architecture/core-concepts/schemas.md` - JSON IR schemas

## PocketFlow Context

While Task 15 doesn't directly use PocketFlow, understanding it helps:
- Nodes follow `prep/exec/post` lifecycle
- Shared store enables inter-node communication
- Proxy mappings route data between incompatible interfaces
- This is what the planner ultimately generates workflows for

## Key Decisions Made

1. **Workflow Storage**: Flat `~/.pflow/workflows/` directory
2. **Workflow Schema**: Full metadata (name, description, inputs, outputs, timestamps, version, tags, ir)
3. **Structure Format**: Nested structure from parser
4. **Discovery Format**: Name + description (no length limits)
5. **Planning Format**: Combined JSON + paths for structures
6. **Backward Compatibility**: Refactor `build_context()` - no compatibility needed
7. **Error Handling**: Return error info for missing components
8. **Performance**: No artificial limits in MVP

## Testing Strategy

### Unit Tests
- Discovery context generation (various component counts)
- Planning context with structure display
- Workflow loading and validation
- Missing component handling

### Integration Tests
- Full discovery → planning flow
- Error recovery scenarios
- Structure parsing verification

### Test Nodes Available
- `test_node` - Basic string I/O
- `test_node_retry` - With parameters
- `test_node_structured` - With nested structures (perfect for testing)

## Success Criteria

1. Two-phase context building reduces LLM overwhelm
2. Workflows appear in discovery alongside nodes
3. Structure information enables proxy mapping generation
4. Missing components trigger graceful error recovery
5. All existing tests pass
6. Performance acceptable (<1s for 100 nodes)

## Implementation Notes

- **Don't break the parser** - It's fragile but functional
- **Reuse existing methods** - Most logic already exists
- **Test with test nodes** - Faster than file operations
- **Focus on MVP** - No fancy features yet
- **Combined format is critical** - JSON + paths needed for planner

## Next Steps

This context provides the foundation for decomposing Task 15 into manageable subtasks. The implementing agent should:
1. Review the ambiguities and technical guide documents
2. Understand the existing code structure
3. Plan the implementation approach
4. Break down into logical subtasks
