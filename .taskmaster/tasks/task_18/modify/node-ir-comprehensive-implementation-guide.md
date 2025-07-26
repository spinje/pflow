# Node IR Implementation: Comprehensive Guide for Template Validation Fix

## Executive Summary

This document provides complete implementation guidance for fixing template validation by creating a proper "Node IR" - storing fully parsed interface metadata in the registry rather than just raw docstrings. This eliminates flawed heuristics, improves performance, and creates a single source of truth for node capabilities.

**Key Insight**: We're not adding new parsing - we're moving existing parsing from runtime (context builder) to scan-time (scanner), making it available to all consumers.

**MVP Focus**: Since pflow is in early development, we make a clean break - no backward compatibility, no fallbacks, just the right implementation.

## Table of Contents

1. [Problem Analysis](#problem-analysis)
2. [Current Architecture Deep Dive](#current-architecture-deep-dive)
3. [Proposed Solution: Full Node IR](#proposed-solution-full-node-ir)
4. [Consumer Impact Analysis](#consumer-impact-analysis)
5. [Implementation Guide](#implementation-guide)
6. [Technical Nuances and Edge Cases](#technical-nuances-and-edge-cases)
7. [Testing and Verification](#testing-and-verification)

## Problem Analysis

### The Validation Problem

Current template validation uses name-based heuristics that fail for valid workflows:

```python
# In template_validator.py lines 106-118
common_outputs = {
    "result", "output", "summary", "content", "response",
    "data", "text", "error", "status", "report", "analysis"
}
```

**The Core Issue**: The validator doesn't know what variables nodes actually write to the shared store. It just guesses based on variable names. If your variable isn't in the hardcoded list above, validation fails.

**Real Example - This Valid Workflow Fails**:

```json
{
  "nodes": [
    {
      "id": "loader",
      "type": "config-loader",
      "params": {"path": "$config_path"}
      // This node writes api_settings to shared store
    },
    {
      "id": "api",
      "type": "api-call",
      "params": {"config": "$api_settings"}
      // Uses the api_settings from loader
    }
  ]
}
```

**What the User Sees**:
```
ValueError: Template validation failed:
  - Missing required parameter: --api_settings
```

**Why This is Wrong**: The `config-loader` node writes `api_settings` to the shared store, so `$api_settings` is perfectly valid. But the validator doesn't know this - it only knows that "api_settings" isn't in its magic `common_outputs` list, so it assumes it must be a CLI parameter.

**The Solution**: Instead of guessing with heuristics, look at what each node's Interface section says it writes. If `config-loader` writes `api_settings`, then `$api_settings` is valid.

### The Parsing Problem

Currently, the same docstrings are parsed repeatedly:

1. **Scanner** (`scanner.py:72-80`): Extracts only raw docstring
2. **Context Builder** (`context_builder.py:83`): Parses docstring for planning
3. **Future Validator**: Would need to parse again

This violates DRY and wastes CPU cycles.

## Current Architecture Deep Dive

### 1. Scanner: What It Currently Extracts

```python
# scanner.py:72-80
def extract_metadata(cls: type, module_path: str, file_path: Path) -> dict[str, Any]:
    """Extract metadata from a node class."""
    return {
        "module": module_path,
        "class_name": cls.__name__,
        "name": get_node_name(cls),
        "docstring": inspect.getdoc(cls) or "",  # RAW STRING
        "file_path": str(file_path.absolute()),
    }
```

**Current Registry Entry**:
```json
{
  "read-file": {
    "class_name": "ReadFileNode",
    "docstring": "Read content from a file...\n\nInterface:\n- Reads: shared[\"file_path\"]...",
    "module": "pflow.nodes.file.read_file",
    "file_path": "/path/to/read_file.py"
  }
}
```

### 2. MetadataExtractor: Full Parsing Capabilities

The `MetadataExtractor` (`metadata_extractor.py`) can parse three formats:

#### Simple Format
```
Interface:
- Reads: shared["file_path"], shared["encoding"]
- Writes: shared["content"]
```

#### List Format
```
Interface:
- Reads:
  - file_path
  - encoding
```

#### Enhanced Format with Types and Descriptions
```
Interface:
- Reads: shared["repo"]: str  # Repository name
- Writes: shared["issue_data"]: dict  # Complete issue information
    - number: int  # Issue number
    - user: dict  # Author info
      - login: str  # GitHub username
      - id: int  # User ID
```

**What MetadataExtractor Returns**:
```python
{
    "description": "Read content from a file and add line numbers",
    "inputs": [
        {"key": "file_path", "type": "str", "description": "Path to file"},
        {"key": "encoding", "type": "str", "description": "File encoding"}
    ],
    "outputs": [
        {
            "key": "issue_data",
            "type": "dict",
            "description": "Complete issue information",
            "structure": {
                "number": {"type": "int", "description": "Issue number"},
                "user": {
                    "type": "dict",
                    "description": "Author info",
                    "structure": {
                        "login": {"type": "str", "description": "GitHub username"},
                        "id": {"type": "int", "description": "User ID"}
                    }
                }
            }
        }
    ],
    "params": [
        {"key": "token", "type": "str", "description": "API token"}
    ],
    "actions": ["default", "error"]
}
```

### 3. Context Builder: Current Runtime Parsing

```python
# context_builder.py:75-93
# For EVERY request, it:
1. Imports node modules dynamically
2. Creates MetadataExtractor instance
3. Calls extract_metadata() on each node class
4. Formats the results for display
```

This parsing happens repeatedly, even for the same nodes.

## Proposed Solution: Full Node IR

### New Registry Format

Store the complete parsed metadata:

```json
{
  "read-file": {
    "class_name": "ReadFileNode",
    "docstring": "Read content from a file...",  // Keep for reference
    "module": "pflow.nodes.file.read_file",
    "file_path": "/path/to/read_file.py",
    "interface": {
      "description": "Read content from a file and add line numbers",
      "inputs": [
        {"key": "file_path", "type": "str", "description": "Path to file"},
        {"key": "encoding", "type": "str", "description": "File encoding"}
      ],
      "outputs": [
        {"key": "content", "type": "str", "description": "File contents with line numbers"}
      ],
      "params": [
        {"key": "file_path", "type": "str", "description": "Path to file"},
        {"key": "encoding", "type": "str", "description": "File encoding"}
      ],
      "actions": ["default", "error"]
    }
  }
}
```

### Why Store Everything?

1. **Types**: Enable future type checking, better error messages
2. **Descriptions**: Rich documentation for users and LLMs
3. **Structures**: Critical for complex nodes (GitHub, APIs, etc)
4. **Actions**: Needed for workflow validation

Even storing ALL metadata for 100 nodes = ~1MB (negligible).

## Consumer Impact Analysis

### 1. Context Builder (Simplification)

**Before** (context_builder.py:75-110):
```python
# Complex dynamic import and parsing
module = importlib.import_module(module_path)
node_class = getattr(module, class_name)
metadata = extractor.extract_metadata(node_class)
```

**After**:
```python
# Direct usage of pre-parsed data
metadata = node_info.get("interface", {})
# No imports, no parsing, just formatting
```

Removes ~100 lines of parsing code!

### 2. Template Validator (New Capability)

**Before**: Flawed heuristics
**After**: Accurate validation using interface.outputs

```python
def _extract_written_variables(workflow_ir, registry):
    written_vars = set()
    for node in workflow_ir.get("nodes", []):
        metadata = registry.get_nodes_metadata([node["type"]])
        interface = metadata.get(node["type"], {}).get("interface", {})

        # Extract just the keys from outputs
        for output in interface.get("outputs", []):
            if isinstance(output, dict):
                written_vars.add(output["key"])
            else:
                written_vars.add(output)  # Backward compat
    return written_vars
```

### 3. Future Consumers

- **Task 17 Planner**: Gets rich metadata for LLM context
- **Type Checker**: Can validate data flow types
- **Documentation**: Auto-generated from registry

## Implementation Guide

### Phase 1: Update Scanner (scanner.py)

```python
# scanner.py - Update extract_metadata function
def extract_metadata(cls: type, module_path: str, file_path: Path) -> dict[str, Any]:
    """Extract metadata from a node class including parsed interface."""
    # Import at function level to avoid circular imports
    from pflow.registry.metadata_extractor import MetadataExtractor

    # Get basic metadata (current implementation)
    metadata = {
        "module": module_path,
        "class_name": cls.__name__,
        "name": get_node_name(cls),
        "docstring": inspect.getdoc(cls) or "",
        "file_path": str(file_path.absolute()),
    }

    # NEW: Parse interface from docstring
    try:
        extractor = MetadataExtractor()
        parsed = extractor.extract_metadata(cls)

        # Store full parsed interface
        metadata["interface"] = {
            "description": parsed.get("description", "No description"),
            "inputs": parsed.get("inputs", []),
            "outputs": parsed.get("outputs", []),
            "params": parsed.get("params", []),
            "actions": parsed.get("actions", [])
        }
    except Exception as e:
        # For MVP: Fail fast on parsing errors - fix the node!
        logger.error(f"Failed to parse interface for {cls.__name__}: {e}")
        raise

    return metadata
```

**Critical Details**:
- Import MetadataExtractor inside function (avoid circular imports)
- Fail fast on errors - no fallbacks for MVP
- Preserve ALL metadata (types, descriptions, structures)
- If scanning fails, fix the node rather than hide the problem

### Phase 2: Context Builder Simplification

```python
# context_builder.py - Update _process_nodes function
def _process_nodes(registry_metadata: dict[str, dict[str, Any]]) -> tuple[dict[str, dict], int]:
    """Process nodes from registry metadata."""
    processed_nodes = {}
    skipped_count = 0

    for node_type, node_info in registry_metadata.items():
        # NEW: Check for pre-parsed interface
        if "interface" in node_info:
            # Use pre-parsed data directly
            interface = node_info["interface"]
            processed_nodes[node_type] = {
                "description": interface.get("description", "No description"),
                "inputs": interface.get("inputs", []),
                "outputs": interface.get("outputs", []),
                "params": interface.get("params", []),
                "actions": interface.get("actions", []),
                "registry_info": node_info,
            }
        else:
            # FALLBACK: Old parsing logic for backward compatibility
            # (Current implementation remains for old registry format)
            try:
                # ... existing dynamic import and parsing code ...
            except Exception as e:
                logger.warning(f"Failed to process node '{node_type}': {e}")
                skipped_count += 1

    return processed_nodes, skipped_count
```

### Phase 3: Template Validator Implementation

```python
# template_validator.py - Add new validation method
@staticmethod
def validate_workflow_templates(
    workflow_ir: dict[str, Any],
    available_params: dict[str, Any],
    registry: Registry  # Required for MVP - no optional parameters
) -> list[str]:
    """Validate all template variables have sources."""
    errors = []

    # Extract all templates from workflow
    all_templates = TemplateValidator._extract_all_templates(workflow_ir)

    # Get variables that will be written by nodes
    written_vars = set()
    if registry:
        written_vars = TemplateValidator._extract_written_variables(workflow_ir, registry)

        # Build set of all available variables
        available_vars = set(available_params.keys()) | written_vars

        # Check each template has a source
        for template in all_templates:
            # Handle nested paths like $config.api.key
            base_var = template.split(".")[0]

            if base_var not in available_vars:
                errors.append(
                    f"Template variable ${template} has no source - "
                    f"not in initial_params and not written by any node"
                )
    else:
        # MVP: Registry is required for proper validation
        raise ValueError("Registry required for template validation")

    return errors

@staticmethod
def _extract_written_variables(workflow_ir: dict[str, Any], registry: Registry) -> set[str]:
    """Extract all variables written by nodes using interface metadata."""
    written_vars = set()

    for node in workflow_ir.get("nodes", []):
        node_type = node.get("type")
        if not node_type:
            continue

        # Get node metadata from registry
        nodes_metadata = registry.get_nodes_metadata([node_type])
        if node_type not in nodes_metadata:
            logger.warning(f"Node type '{node_type}' not found in registry")
            continue

        metadata = nodes_metadata[node_type]

        # Get pre-parsed interface (must exist after scanner update)
        interface = metadata["interface"]

        # Extract output keys
        for output in interface["outputs"]:
            written_vars.add(output["key"])  # Always dict format

    return written_vars
```

### Phase 4: Compiler Integration

```python
# compiler.py - Update compile_ir_to_flow (line ~511)
if validate:
    errors = TemplateValidator.validate_workflow_templates(
        ir_dict,
        initial_params or {},
        registry  # Pass the registry we already have!
    )
```

## Technical Nuances and Edge Cases

### 1. MetadataExtractor Normalization

The extractor normalizes all formats to rich format:

```python
# metadata_extractor.py:482-501
def _normalize_to_rich_format(self, items):
    """Convert simple strings to rich format with defaults."""
    if isinstance(items[0], dict):
        return items  # Already rich
    # Convert simple to rich
    return [{"key": item, "type": "any", "description": ""} for item in items]
```

This means scanner should store the normalized format.

### 2. Complex Structure Parsing

For nested structures, the extractor:
1. Detects `_has_structure` markers during initial parse
2. Calls `_parse_all_structures()` for second pass
3. Recursively builds structure trees

```python
# Example structure in interface:
{
    "key": "issue_data",
    "type": "dict",
    "structure": {
        "user": {
            "type": "dict",
            "structure": {
                "login": {"type": "str", "description": "Username"}
            }
        }
    }
}
```

### 3. Import Order Considerations

Scanner imports nodes dynamically, which can cause issues:
- Must import MetadataExtractor inside function
- Handle import failures gracefully
- Don't let one bad node break scanning

### 4. Backward Compatibility Strategy

Support both old and new registry formats:

```python
if "interface" in node_metadata:
    # New format - use directly
    interface = node_metadata["interface"]
else:
    # Old format - parse docstring
    # OR prompt user to re-run scanner
```

### 5. Memory Considerations

Full metadata for complex nodes can be large:
- GitHub node with full structure: ~5KB
- Simple file node: ~1KB
- 100 nodes: ~200KB average

This is still tiny compared to modern RAM.

### 6. Error Handling Philosophy

**Scanner**: Log warnings, use empty interface fallback
**Consumers**: Handle missing interface gracefully
**Never**: Let parsing errors break core functionality

## Testing and Verification

### 1. Scanner Tests

```python
def test_scanner_extracts_interface():
    """Test that scanner extracts and stores interface metadata."""
    # Create test node with known interface
    class TestNode(BaseNode):
        """Test node.

        Interface:
        - Reads: shared["input"]: str  # Test input
        - Writes: shared["output"]: str  # Test output
        """
        pass

    metadata = extract_metadata(TestNode, "test.module", Path("test.py"))

    assert "interface" in metadata
    assert len(metadata["interface"]["inputs"]) == 1
    assert metadata["interface"]["inputs"][0]["key"] == "input"
    assert metadata["interface"]["outputs"][0]["key"] == "output"
```

### 2. Backward Compatibility Tests

```python
def test_context_builder_handles_old_format():
    """Test context builder works with old registry format."""
    old_registry = {
        "test-node": {
            "docstring": "...",
            "module": "...",
            # No interface field
        }
    }
    # Should still work via fallback parsing
```

### 3. Validator Accuracy Tests

```python
def test_validator_uses_interface_data():
    """Test validator correctly uses interface outputs."""
    workflow = {
        "nodes": [
            {"type": "config-loader", "params": {"path": "$config_path"}},
            {"type": "api-call", "params": {"settings": "$api_config"}}
        ]
    }

    # With new registry including interface
    registry = Registry()
    # ... setup registry with interface data showing config-loader writes api_config

    errors = validate_workflow_templates(workflow, {"config_path": "/path"}, registry)
    assert len(errors) == 0  # No false positives!
```

### 4. Performance Benchmarks

Measure scanning time increase:
```python
# Before: ~0.1s per node (just docstring)
# After: ~0.2s per node (with parsing)
# Total for 50 nodes: 5s → 10s (acceptable one-time cost)
```

## Implementation Checklist

### Scanner Phase
- [ ] Import MetadataExtractor correctly (inside function)
- [ ] Add try/except with comprehensive error handling
- [ ] Store full interface metadata (not just keys)
- [ ] Test with nodes that have no Interface section
- [ ] Test with malformed Interface sections
- [ ] Verify performance impact is acceptable

### Context Builder Phase
- [ ] Add interface detection logic
- [ ] Implement fallback for old format
- [ ] Remove unnecessary imports after migration
- [ ] Test with both old and new registry formats
- [ ] Verify output remains identical

### Validator Phase
- [ ] Add registry parameter to signature
- [ ] Implement _extract_written_variables
- [ ] Keep heuristic fallback
- [ ] Add comprehensive logging
- [ ] Test with complex workflows

### Integration Phase
- [ ] Update compiler to pass registry
- [ ] Add migration command/script
- [ ] Update documentation
- [ ] Performance testing
- [ ] End-to-end testing

## Common Pitfalls to Avoid

1. **Don't assume all nodes have Interface sections** - Fail clearly if missing
2. **Don't hide parsing errors** - Let them fail so nodes get fixed
3. **Don't forget nested structures** - They're critical for complex nodes
4. **Don't lose type information** - Store full rich format
5. **Don't add unnecessary complexity** - MVP should be simple and correct

## Summary

This implementation creates a proper "Node IR" by moving parsing from runtime to scan-time. It's not adding complexity - it's moving existing complexity to the right place. The result is faster runtime, accurate validation, and a solid foundation for future features.
