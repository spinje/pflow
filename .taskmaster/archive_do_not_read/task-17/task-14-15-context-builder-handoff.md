# Task 17 Planner Implementation: Critical Handoff from Tasks 14 & 15

## Executive Summary

This document provides essential information for implementing Task 17 (Natural Language Planner) based on the foundational work completed in Tasks 14 and 15. These tasks created the infrastructure that enables the planner to understand node interfaces, generate proxy mappings, and create accurate workflows.

**What This Handoff Provides:**
- Enhanced interface format capabilities for understanding node data structures
- Two-phase context building system for discovery and planning
- Structure display format optimized for LLM proxy mapping generation
- Integration patterns with registry and context builder systems
- Technical implementation guidance for workflow IR generation

## Table of Contents

1. [Enhanced Interface Format Foundation (Task 14)](#enhanced-interface-format-foundation-task-14)
2. [Two-Phase Context System (Task 15)](#two-phase-context-system-task-15)
3. [Critical Structure Display Format](#critical-structure-display-format)
4. [Proxy Mapping Generation Strategy](#proxy-mapping-generation-strategy)
5. [Integration Patterns](#integration-patterns)
6. [Implementation Examples](#implementation-examples)
7. [Error Handling and Edge Cases](#error-handling-and-edge-cases)
8. [Testing and Validation](#testing-and-validation)

## Enhanced Interface Format Foundation (Task 14)

### What Was Built

Task 14 implemented a comprehensive enhancement to node documentation that enables type-aware workflow planning:

#### 1. Structured Docstring Format
```python
class GitHubIssueNode(Node):
    """
    Fetch GitHub issue data with full metadata.

    Interface:
    - Reads: shared["issue_number"]: int  # Issue number to fetch
    - Reads: shared["repo"]: str  # Repository name (owner/repo format)
    - Writes: shared["issue_data"]: dict  # Complete issue information
        - number: int  # Issue number
        - title: str  # Issue title
        - user: dict  # Author information
          - login: str  # GitHub username
          - id: int  # User ID
        - labels: list  # Issue labels
          - name: str  # Label name
          - color: str  # Label color
    - Params: include_comments: bool  # Include issue comments (default: false)
    - Actions: default (success), error (API error)
    """
```

#### 2. Structure Parsing Engine
- **Location**: `src/pflow/registry/metadata_extractor.py` (lines 543-612)
- **Capability**: Recursively parses nested structures up to 5 levels deep
- **Output**: Structured metadata with type information and nested field definitions
- **Status**: Fully implemented and tested

#### 3. Metadata Extraction
The metadata extractor produces structured data like:
```python
{
    "key": "issue_data",
    "type": "dict",
    "description": "Complete issue information",
    "structure": {
        "number": {"type": "int", "description": "Issue number"},
        "user": {
            "type": "dict",
            "description": "Author information",
            "structure": {
                "login": {"type": "str", "description": "GitHub username"},
                "id": {"type": "int", "description": "User ID"}
            }
        },
        "labels": {
            "type": "list",
            "description": "Issue labels",
            "structure": {
                "name": {"type": "str", "description": "Label name"},
                "color": {"type": "str", "description": "Label color"}
            }
        }
    }
}
```

### Key Implications for Task 17

1. **Rich Type Information**: The planner can understand exact data types for all node inputs/outputs
2. **Nested Structure Awareness**: Complex data structures are fully documented and parseable
3. **Semantic Descriptions**: Each field has human-readable descriptions for context
4. **Validation Ready**: Type information enables input validation and compatibility checking

## Two-Phase Context System (Task 15)

### The Problem Solved

Original context builders created overwhelming amounts of information that caused "LLM overwhelm." Task 15 solved this with a two-phase approach:

1. **Discovery Phase**: Lightweight browsing of available components
2. **Planning Phase**: Detailed interface information for selected components only

### Phase 1: Discovery Context

**Purpose**: Help LLMs browse and select potentially relevant components
**Function**: `build_discovery_context(node_ids=None, workflow_names=None, registry_metadata=None)`

**Output Example**:
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

## Available Workflows

### backup-files
Creates backups of specified files with timestamps
```

**Usage Pattern**:
```python
# Get all available components for browsing
discovery = build_discovery_context(registry_metadata=registry.load())
# LLM reviews discovery context and selects relevant components
selected_nodes = llm_select_components(discovery, user_request)
```

### Phase 2: Planning Context

**Purpose**: Provide detailed interface information for workflow generation
**Function**: `build_planning_context(selected_node_ids, selected_workflow_names, registry_metadata)`

**Key Features**:
- Full interface specifications with types
- **Structure display in combined format** (critical for proxy mappings)
- Parameter details and default values
- Error information for missing components

**Usage Pattern**:
```python
# Get detailed information for selected components
planning = build_planning_context(
    selected_node_ids=["github-get-issue", "llm"],
    selected_workflow_names=[],
    registry_metadata=registry.load()
)

# Handle missing components
if isinstance(planning, dict) and "error" in planning:
    # Return to discovery with error feedback
    return handle_missing_components(planning)

# Generate workflow IR using detailed interface information
workflow_ir = generate_workflow(planning, user_request)
```

## Critical Structure Display Format

### The Combined JSON + Paths Format (Decision 9)

This is the **most critical feature** for Task 17. The planning context displays structures in a dual format specifically designed for LLM proxy mapping generation:

#### Format Example
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

### Why This Format Is Critical

1. **Dual Pattern Recognition**: JSON for structure understanding, paths for mapping generation
2. **Error Reduction**: Redundancy allows cross-validation between formats
3. **Zero Reconstruction**: Paths can be copied directly for proxy mappings
4. **Training Familiarity**: This format appears in countless API docs that LLMs have seen
5. **Cognitive Flexibility**: Use JSON for relationships, paths for specific mappings

### Implementation Access

**Function**: `_format_structure_combined(structure, parent_path="")`
**Location**: `src/pflow/planning/context_builder.py` (lines 267-333)
**Returns**: `(json_struct: dict, paths: list[tuple[str, str, str]])`

## Proxy Mapping Generation Strategy

### The Problem: Incompatible Node Interfaces

Nodes often have incompatible interfaces:
```python
# Node A writes:
shared["transcript"] = "video transcript content"

# Node B expects:
shared["prompt"] = "text to process"
```

### The Solution: Proxy Mappings

Proxy mappings bridge these gaps:
```python
# Simple mapping
{"prompt": "transcript"}

# Path-based mapping for complex structures
{"author": "issue_data.user.login"}
```

### How Task 17 Should Generate Mappings

#### 1. Simple Field Mappings
```python
def generate_simple_mapping(source_output, target_input):
    """Map one field to another field."""
    return {target_input["key"]: source_output["key"]}

# Example: shared["content"] -> shared["text"]
mapping = {"text": "content"}
```

#### 2. Structure Path Mappings
```python
def generate_path_mapping(source_structure_paths, target_input):
    """Map a nested field to a simple input."""
    # From available paths: issue_data.user.login (str) - GitHub username
    # To target input: author: str
    return {"author": "issue_data.user.login"}
```

#### 3. Complex Structure Mappings
```python
def generate_structure_mapping(source_structure, target_structure):
    """Map between compatible structures."""
    mappings = {}
    for target_field, target_info in target_structure.items():
        # Find compatible source field
        compatible_source = find_compatible_field(source_structure, target_info)
        if compatible_source:
            mappings[target_field] = compatible_source
    return mappings
```

### Mapping Integration in Workflow IR

```python
workflow_ir = {
    "nodes": [
        {
            "id": "fetch_issue",
            "type": "github-get-issue",
            "params": {"issue_number": "$issue"}
        },
        {
            "id": "analyze",
            "type": "llm",
            "params": {"model": "gpt-4"},
            "proxy_mappings": {
                "prompt": "issue_data.title"  # Map issue title to LLM prompt
            }
        }
    ],
    "flows": [
        {
            "from": "fetch_issue",
            "to": "analyze",
            "action": "default"
        }
    ]
}
```

## Integration Patterns

### 1. Registry Integration

```python
from pflow.registry import Registry

def get_node_metadata():
    """Load and process node metadata."""
    registry = Registry()
    metadata = registry.load()
    return metadata

# Usage in planner
def plan_workflow(user_request: str):
    registry_metadata = get_node_metadata()

    # Discovery phase
    discovery = build_discovery_context(registry_metadata=registry_metadata)
    selected_components = llm_discover(discovery, user_request)

    # Planning phase
    planning = build_planning_context(
        selected_components["nodes"],
        selected_components["workflows"],
        registry_metadata
    )

    return generate_workflow_ir(planning, user_request)
```

### 2. Context Builder Integration

```python
from pflow.planning.context_builder import (
    build_discovery_context,
    build_planning_context
)

class NaturalLanguagePlanner:
    def __init__(self):
        self.registry = Registry()

    def discover_components(self, user_request: str) -> list[str]:
        """Phase 1: Discover relevant components."""
        metadata = self.registry.load()
        discovery = build_discovery_context(registry_metadata=metadata)

        # LLM processes discovery context and selects components
        return self.llm_select_components(discovery, user_request)

    def plan_workflow(self, selected_components: list[str], user_request: str) -> dict:
        """Phase 2: Generate detailed workflow plan."""
        metadata = self.registry.load()
        planning = build_planning_context(
            selected_node_ids=selected_components,
            selected_workflow_names=[],
            registry_metadata=metadata
        )

        # Handle missing components
        if isinstance(planning, dict) and "error" in planning:
            return self.handle_missing_components(planning)

        # Generate workflow IR with proxy mappings
        return self.generate_workflow_ir(planning, user_request)
```

### 3. Error Recovery Integration

```python
def handle_missing_components(error_info: dict) -> dict:
    """Handle missing components by returning to discovery."""
    missing_nodes = error_info.get("missing_nodes", [])
    missing_workflows = error_info.get("missing_workflows", [])

    error_feedback = f"""
    Some selected components were not found:
    - Missing nodes: {', '.join(missing_nodes)}
    - Missing workflows: {', '.join(missing_workflows)}

    Please check spelling (use hyphens not underscores) and try again.
    """

    return {
        "status": "retry_discovery",
        "error": error_feedback,
        "missing_components": error_info
    }
```

## Implementation Examples

### 1. Complete Planner Flow

```python
class WorkflowPlanner:
    def __init__(self):
        self.registry = Registry()
        self.llm_client = LLMClient()  # Your LLM integration

    def plan_workflow(self, user_request: str) -> dict:
        """Complete workflow planning process."""

        # Step 1: Discovery Phase
        metadata = self.registry.load()
        discovery = build_discovery_context(registry_metadata=metadata)

        discovery_prompt = f"""
        User request: {user_request}

        Available components:
        {discovery}

        Select components that might be relevant for this request.
        Return a JSON list of node names: ["node1", "node2", ...]
        """

        selected = self.llm_client.complete(discovery_prompt)
        selected_nodes = json.loads(selected)

        # Step 2: Planning Phase
        planning = build_planning_context(
            selected_node_ids=selected_nodes,
            selected_workflow_names=[],
            registry_metadata=metadata
        )

        # Handle missing components
        if isinstance(planning, dict) and "error" in planning:
            return self.handle_missing_components(planning)

        # Step 3: Workflow Generation
        return self.generate_workflow_ir(planning, user_request)

    def generate_workflow_ir(self, planning_context: str, user_request: str) -> dict:
        """Generate workflow IR from planning context."""

        planning_prompt = f"""
        User request: {user_request}

        Available components with detailed interfaces:
        {planning_context}

        Generate a workflow that fulfills the user request.
        Pay special attention to:
        1. Structure paths for proxy mappings (e.g., "author": "issue_data.user.login")
        2. Compatible data types between nodes
        3. Required parameters and their defaults

        Return valid JSON IR format:
        {{
            "nodes": [...],
            "flows": [...],
            "proxy_mappings": {{...}}
        }}
        """

        result = self.llm_client.complete(planning_prompt)
        return json.loads(result)
```

### 2. Proxy Mapping Generation

```python
def extract_proxy_mappings(planning_context: str) -> dict[str, list[str]]:
    """Extract available proxy mapping paths from planning context."""

    mappings = {}

    # Parse structure paths from planning context
    lines = planning_context.split('\n')
    current_node = None

    for line in lines:
        # Detect node sections
        if line.startswith('### '):
            current_node = line[4:].strip()
            mappings[current_node] = []

        # Extract structure paths
        elif "Available paths:" in line:
            # Find all path lines after this
            for path_line in lines[lines.index(line)+1:]:
                if path_line.startswith('- '):
                    path_match = re.match(r'- (\S+) \((\w+)\) - (.+)', path_line)
                    if path_match:
                        path, type_name, description = path_match.groups()
                        mappings[current_node].append({
                            "path": path,
                            "type": type_name,
                            "description": description
                        })
                elif path_line.strip() == "" or path_line.startswith('#'):
                    break

    return mappings

def generate_proxy_mapping(source_node: str, target_node: str,
                          available_mappings: dict) -> dict:
    """Generate proxy mappings between two nodes."""

    source_outputs = available_mappings.get(source_node, [])
    target_inputs = available_mappings.get(target_node, [])

    mappings = {}

    for target_input in target_inputs:
        # Find compatible source output
        for source_output in source_outputs:
            if is_compatible_type(source_output["type"], target_input["type"]):
                mappings[target_input["path"]] = source_output["path"]
                break

    return mappings

def is_compatible_type(source_type: str, target_type: str) -> bool:
    """Check if two types are compatible for mapping."""
    # Simple type compatibility
    if source_type == target_type:
        return True

    # String compatibility (most things can become strings)
    if target_type == "str":
        return True

    # Numeric compatibility
    if source_type in ("int", "float") and target_type in ("int", "float", "str"):
        return True

    return False
```

## Error Handling and Edge Cases

### 1. Missing Components Error Recovery

```python
def handle_planning_errors(planning_result) -> tuple[bool, dict]:
    """Handle various planning phase errors."""

    if isinstance(planning_result, dict) and "error" in planning_result:
        error_type = planning_result.get("error_type", "missing_components")

        if error_type == "missing_components":
            return False, {
                "action": "retry_discovery",
                "feedback": planning_result["error"],
                "missing_nodes": planning_result.get("missing_nodes", []),
                "missing_workflows": planning_result.get("missing_workflows", [])
            }

        elif error_type == "invalid_registry":
            return False, {
                "action": "reload_registry",
                "error": "Registry data is invalid, reloading..."
            }

    return True, {"action": "proceed"}
```

### 2. Type Compatibility Validation

```python
def validate_workflow_compatibility(workflow_ir: dict, registry_metadata: dict) -> list[str]:
    """Validate that the workflow has compatible data types."""

    errors = []

    for flow in workflow_ir.get("flows", []):
        source_node = find_node_by_id(workflow_ir["nodes"], flow["from"])
        target_node = find_node_by_id(workflow_ir["nodes"], flow["to"])

        # Get node metadata
        source_metadata = registry_metadata.get(source_node["type"])
        target_metadata = registry_metadata.get(target_node["type"])

        if not source_metadata or not target_metadata:
            errors.append(f"Missing metadata for nodes in flow {flow['from']} -> {flow['to']}")
            continue

        # Check proxy mappings if present
        proxy_mappings = target_node.get("proxy_mappings", {})
        for target_key, source_path in proxy_mappings.items():
            if not is_valid_source_path(source_path, source_metadata):
                errors.append(f"Invalid source path '{source_path}' in proxy mapping")

            if not is_valid_target_key(target_key, target_metadata):
                errors.append(f"Invalid target key '{target_key}' in proxy mapping")

    return errors
```

### 3. Structure Path Validation

```python
def validate_structure_path(path: str, structure: dict) -> bool:
    """Validate that a structure path exists in the given structure."""

    parts = path.split('.')
    current = structure

    for part in parts:
        # Handle array notation
        if part.endswith('[]'):
            field_name = part[:-2]
            if field_name not in current:
                return False
            current = current[field_name]

            # For arrays, check if structure has items
            if current.get("type") != "list":
                return False
            current = current.get("structure", {})
        else:
            if part not in current:
                return False
            current = current[part]

            # Move to nested structure if available
            if isinstance(current, dict) and "structure" in current:
                current = current["structure"]

    return True
```

## Testing and Validation

### 1. Integration Testing Patterns

```python
def test_planner_integration():
    """Test complete planner workflow."""

    # Setup
    planner = WorkflowPlanner()
    user_request = "Read a GitHub issue and summarize it with AI"

    # Test discovery phase
    discovery = planner.discover_components(user_request)
    assert "github-get-issue" in discovery
    assert "llm" in discovery

    # Test planning phase
    workflow = planner.plan_workflow(user_request)
    assert "nodes" in workflow
    assert "flows" in workflow

    # Validate generated workflow
    errors = validate_workflow_compatibility(workflow, registry.load())
    assert len(errors) == 0
```

### 2. Proxy Mapping Testing

```python
def test_proxy_mapping_generation():
    """Test proxy mapping generation with structured data."""

    # Mock planning context with structure
    planning_context = """
    ### github-get-issue
    **Outputs**:
    - issue_data: dict - GitHub issue information

    Available paths:
    - issue_data.title (str) - Issue title
    - issue_data.user.login (str) - GitHub username

    ### llm
    **Inputs**:
    - prompt: str - Text to process
    """

    mappings = extract_proxy_mappings(planning_context)
    proxy_mapping = generate_proxy_mapping("github-get-issue", "llm", mappings)

    # Should map issue title to LLM prompt
    assert proxy_mapping.get("prompt") == "issue_data.title"
```

### 3. Error Recovery Testing

```python
def test_missing_component_recovery():
    """Test error recovery when components are missing."""

    planner = WorkflowPlanner()

    # Simulate selecting non-existent node
    planning = build_planning_context(
        selected_node_ids=["fake-node"],
        selected_workflow_names=[],
        registry_metadata={}
    )

    # Should return error dict
    assert isinstance(planning, dict)
    assert "error" in planning

    # Should provide recovery information
    recovery = planner.handle_missing_components(planning)
    assert recovery["action"] == "retry_discovery"
    assert "fake-node" in recovery["error"]
```

## Key Implementation Files

### Core Context Builder
- **File**: `src/pflow/planning/context_builder.py`
- **Key Functions**:
  - `build_discovery_context()` (lines 389-484)
  - `build_planning_context()` (lines 535-631)
  - `_format_structure_combined()` (lines 267-333)

### Registry Integration
- **File**: `src/pflow/registry/registry.py`
- **Key Functions**:
  - `Registry.load()` - Get all node metadata
  - Registry provides the metadata dict that feeds context builder

### Metadata Extraction
- **File**: `src/pflow/registry/metadata_extractor.py`
- **Key Functions**:
  - `extract_metadata()` - Extract from node classes
  - `_parse_structure()` (lines 543-612) - Parse nested structures

### Enhanced Format Documentation
- **File**: `architecture/reference/enhanced-interface-format.md`
- **Contains**: Complete specification of the enhanced docstring format

## Critical Success Factors

### 1. Use the Combined Format
The JSON + paths structure display format is **mandatory** for proxy mapping generation. Do not try to parse structures differently.

### 2. Handle Missing Components Gracefully
Always check if `build_planning_context()` returns an error dict and provide recovery paths.

### 3. Validate Compatibility
Use type information to validate that proxy mappings are compatible before generating workflow IR.

### 4. Follow Two-Phase Pattern
Always use discovery → planning flow. Don't try to get all information at once.

### 5. Test with Real Data
Use the existing test nodes (especially `test_node_structured`) for testing structure parsing and mapping generation.

## Implementation Readiness

### What's Ready for Use
- ✅ Enhanced interface format parsing
- ✅ Structure extraction and display
- ✅ Two-phase context building
- ✅ Registry integration
- ✅ Comprehensive test coverage
- ✅ Error handling patterns

### What Task 17 Needs to Build
- LLM integration for component selection
- Workflow IR generation with proxy mappings
- Type compatibility validation
- Natural language request parsing
- Error recovery and retry logic

### Dependencies
- Registry system (complete)
- Context builder (complete)
- Metadata extractor (complete)
- IR schema definitions (complete)
- PocketFlow integration (complete)

## Next Steps for Task 17

1. **Start with Discovery Integration**: Build LLM prompt templates for component discovery
2. **Implement Planning Integration**: Create prompt templates for workflow generation using planning context
3. **Focus on Proxy Mappings**: Use the structure paths to generate accurate mappings
4. **Add Type Validation**: Ensure generated workflows have compatible data types
5. **Build Error Recovery**: Handle missing components and invalid workflows gracefully

The foundation is solid and well-tested. Task 17 can focus on the LLM integration and workflow generation logic, knowing that the context building and structure parsing infrastructure is robust and ready for production use.

---

**Document Status**: Complete handoff from Tasks 14 & 15
**Last Updated**: Task 15.4 completion
**Contact**: Reference Task 15 implementation files for technical details
