# Task 15 Implementation Context: Extend Context Builder for Two-Phase Discovery

## Overview

Task 15 extends the existing context builder to support the Natural Language Planner's sophisticated requirements. The key innovation is splitting context generation into two phases to prevent LLM overwhelm while enabling workflow reuse.

## Background & Dependencies

### What Already Exists
1. **Task 16**: Created `src/pflow/planning/context_builder.py` with `build_context()` function
2. **Task 14**: Enhanced metadata extraction with type support:
   - Metadata now includes types and descriptions: `{"key": "shared[\"file_path\"]: str  # Path to file"}`
   - Parser supports enhanced Interface format but structure parsing is scaffolding only
3. **Registry System**: Provides node metadata in a dict format
4. **No workflow storage**: The `~/.pflow/workflows/` directory doesn't exist yet

### Critical Context from Ambiguities Document
From the resolved ambiguities (scratchpads/critical-user-decisions/task-17-planner-ambiguities.md):
- **Section 2.1**: Structure documentation is critical for path-based proxy mappings
- **Section 12**: Unified discovery pattern - workflows are building blocks like nodes
- **Section 3**: Workflow storage format has been decided (simple JSON with metadata)

## Implementation Requirements

### 1. Two-Phase Context Builder Functions

#### build_discovery_context(registry_metadata, saved_workflows=None)
**Purpose**: Lightweight context for component selection phase

**Input**:
- `registry_metadata`: Dict[str, dict] - Same as existing build_context()
- `saved_workflows`: Optional[List[dict]] - Loaded workflow metadata

**Output**: String (markdown) with ONLY names and descriptions

**Example Output**:
```markdown
## Available Nodes

### github-get-issue
Fetches issue details from GitHub

### llm
General-purpose language model for text processing

### read-file
Reads content from a file

## Available Workflows

### fix-github-issue
Analyzes a GitHub issue and creates a PR with the fix

### analyze-error-logs
Reads log files and summarizes errors with recommendations
```

**Key Requirements**:
- NO interface details (inputs, outputs, params)
- Include both nodes AND workflows
- Group by category (File Operations, AI/LLM Operations, etc.)
- Keep output lightweight to avoid token limits

#### build_planning_context(selected_components, registry_metadata, saved_workflows=None)
**Purpose**: Detailed context for planning phase

**Input**:
- `selected_components`: List[str] - IDs of selected nodes/workflows
- `registry_metadata`: Dict[str, dict] - Full registry data
- `saved_workflows`: Optional[List[dict]] - Loaded workflow metadata

**Output**: String (markdown) with FULL interface details

**Example Output**:
```markdown
## Selected Components

### github-get-issue
Fetches issue details from GitHub

**Inputs**:
- `issue_number`: int  # GitHub issue number
- `repo`: str  # Repository name (optional)

**Outputs**:
- `issue_data`: dict  # Complete issue data including {id: int, title: str, user: {login: str}, labels: [{name: str}]}
- `issue_title`: str  # Issue title for easy access

**Parameters**:
- `timeout`: int  # Request timeout in seconds

### fix-github-issue (workflow)
Analyzes a GitHub issue and creates a PR with the fix

**Inputs**:
- `issue_number`: int  # Issue to fix

**Outputs**:
- `pr_number`: int  # Created pull request number
- `fix_summary`: str  # Summary of the fix applied
```

**Key Requirements**:
- Include FULL interface details with types and descriptions
- Show structure information for nested data
- Clearly mark workflows vs nodes
- Only include selected components

### 2. Workflow Discovery Support

#### Workflow Storage Format
Location: `~/.pflow/workflows/*.json`

**Schema**:
```json
{
  "name": "fix-github-issue",
  "description": "Analyzes a GitHub issue and creates a PR with the fix",
  "inputs": ["issue_number"],
  "outputs": ["pr_number", "fix_summary"],
  "created_at": "2024-01-15T10:30:00Z",
  "ir_version": "0.1.0",
  "ir": {
    // Full workflow IR
  }
}
```

#### _load_saved_workflows() Helper
**Purpose**: Load and parse saved workflows

**Implementation Requirements**:
1. Create directory if it doesn't exist
2. Load all *.json files from ~/.pflow/workflows/
3. Validate basic structure (name, description required)
4. Handle invalid JSON gracefully (log warning, skip file)
5. Return list of workflow metadata dicts

**Example Return Value**:
```python
[
    {
        "id": "fix-github-issue",  # Use name as ID
        "name": "fix-github-issue",
        "description": "Analyzes a GitHub issue and creates a PR with the fix",
        "inputs": ["issue_number"],
        "outputs": ["pr_number", "fix_summary"],
        "type": "workflow"  # Mark as workflow
    }
]
```

### 3. Structure Documentation Enhancement

#### Current State (from Task 14)
The metadata extractor has a `_parse_structure()` method that's scaffolding only:
```python
def _parse_structure(self, structure_str: str) -> dict[str, Any]:
    """Parse structure documentation.

    TODO: Implement actual structure parsing.
    For now, returns a placeholder.
    """
    return {"_structure": structure_str}
```

#### Required Enhancement
Parse nested structure syntax to enable path-based proxy mappings.

**Input Examples**:
```python
# Simple structure
"issue_data: dict"

# Nested structure
"issue_data: {id: int, title: str, user: {login: str}}"

# Array structure
"labels: [{name: str, color: str}]"
```

**Output Format**:
```python
{
    "key": "issue_data",
    "type": "dict",
    "structure": {
        "id": {"type": "int"},
        "title": {"type": "str"},
        "user": {
            "type": "dict",
            "structure": {
                "login": {"type": "str"}
            }
        }
    }
}
```

**Limitations for MVP**:
- Only support basic types: str, int, float, bool, dict, list
- No union types or optional markers
- Basic parsing errors should fallback to string representation
- Document these limitations clearly

## Implementation Order

1. **Create workflow directory structure**
   - Ensure ~/.pflow/workflows/ exists
   - Add example workflow for testing

2. **Implement _load_saved_workflows()**
   - Basic file loading and JSON parsing
   - Error handling for invalid files
   - Return consistent format

3. **Implement build_discovery_context()**
   - Reuse existing category grouping logic
   - Format nodes with name + description only
   - Add workflows section
   - Test with various registry sizes

4. **Implement build_planning_context()**
   - Filter to only selected components
   - Include full interface details
   - Format with proper markdown structure
   - Handle both nodes and workflows

5. **Enhance structure parsing**
   - Extend _parse_structure() with real implementation
   - Support nested dict notation
   - Handle basic array syntax
   - Maintain backward compatibility

6. **Comprehensive testing**
   - Unit tests for each function
   - Integration tests with real metadata
   - Performance tests with large registries
   - Backward compatibility tests

## Critical Edge Cases

1. **Empty or missing workflow directory**
   - Should work gracefully with no workflows
   - Create directory if needed

2. **Invalid workflow files**
   - Malformed JSON → Skip with warning
   - Missing required fields → Skip with warning
   - Don't crash the whole system

3. **Structure parsing failures**
   - Invalid syntax → Return as plain string
   - Nested too deep → Limit recursion
   - Unknown types → Treat as string

## Testing Strategy

### Unit Tests
1. **test_build_discovery_context()**
   - With nodes only
   - With nodes and workflows
   - With empty registry

2. **test_build_planning_context()**
   - Single node selection
   - Multiple components (read, write, params)
   - Workflow selection
   - Missing components (read, write, params)

3. **test_load_saved_workflows()**
   - Valid workflows
   - Invalid JSON
   - Missing fields
   - Empty directory

4. **test_parse_structure()**
   - Simple types
   - Nested dicts
   - Arrays
   - Invalid syntax

### Integration Tests
1. Full discovery → planning flow
2. Backward compatibility with existing build_context()
3. Performance with realistic data

## Backward Compatibility

The existing `build_context()` function must continue working exactly as before:
1. Keep the same signature
2. Return the same format
3. Don't break existing code
4. Consider delegating to new functions internally

## Code Organization

```python
# src/pflow/planning/context_builder.py

def build_context(registry_metadata):
    """Existing function - maintain compatibility."""
    # Could potentially delegate to new functions
    pass

def build_discovery_context(registry_metadata, saved_workflows=None):
    """Lightweight context for discovery phase."""
    pass

def build_planning_context(selected_components, registry_metadata, saved_workflows=None):
    """Detailed context for planning phase."""
    pass

def _load_saved_workflows():
    """Load saved workflows from ~/.pflow/workflows/."""
    pass
```

## Success Criteria

1. **Discovery context is lightweight**
   - Only names and descriptions
   - Under 50KB for 100+ components (exam 0)
   - Clear categorization

2. **Planning context is comprehensive**
   - Full interface details
   - Type information included
   - Structure documentation parsed

3. **Workflows are first-class**
   - Appear alongside nodes
   - Can be selected and used
   - Marked clearly as workflows

4. **Structure parsing works**
   - Nested paths can be generated
   - Backward compatible
   - Graceful failure handling

5. **No regressions**
   - Existing build_context() works
   - All tests pass
   - Performance maintained

## Notes for Implementation

1. Start simple - get basic functionality working first
2. The context builder is performance-critical - avoid expensive operations
3. Structure parsing can be basic for MVP - just enough for path generation
4. Focus on clear, readable output format that LLMs can parse easily
5. Test with real data early to catch issues

This implementation will enable the Natural Language Planner to effectively discover and plan workflows without being overwhelmed by unnecessary details.
