# Template Variables with Path Support: MVP Implementation Guide

## Executive Summary

This document provides the implementation guide for the complete template variable system in pflow's MVP. This system enables the "Plan Once, Run Forever" philosophy by allowing workflows to be parameterized and reused with different values.

**The Complete System Includes**:
1. **Template Validation** - Ensures required parameters are available before execution
2. **Template Resolution** - Replaces variables with actual values during execution
3. **Path Support** - Access nested data (e.g., `$transcript_data.metadata.author`)

**Key Design Decision**: Task 18 implements both validation and resolution as they share core parsing logic and together form the complete template variable feature. Validation is essential for v2.0+ where users can execute saved workflows directly without the planner.

## Connection to Planner Output

The template variable system receives its initial parameters from the Natural Language Planner's output:

```python
# User input: "summarize this youtube video https://youtube.com/watch?v=xyz"
# Planner extracts parameters and returns:
planner_output = {
    "workflow_ir": {...},  # Contains template variables like $url
    "parameter_values": {
        "url": "https://youtube.com/watch?v=xyz"
    }
}

# The CLI passes parameter_values as initial_params to the compiler:
flow = compile_ir_to_flow(
    planner_output["workflow_ir"],
    registry,
    initial_params=planner_output["parameter_values"]  # <-- This connection
)
```

**Key Point**: `initial_params` are NOT command-line flags typed by users. They are values extracted from natural language by the planner's ParameterExtractionNode.

## This IS the Runtime Proxy

This template variable implementation **IS** the "runtime proxy" referenced throughout the planner documentation (task 17):

- **Transparently resolves** template variables at runtime
- **Enables "Plan Once, Run Forever"** by preserving templates in saved workflows
- **Acts as a proxy** between workflow definitions (with templates) and runtime values
- **No modification needed** to existing nodes due to the fallback pattern

Without this runtime proxy, workflows would be single-use with hardcoded values, defeating pflow's core value proposition.

### Why Dynamic Resolution is Critical

Template variables MUST be resolved at execution time, not compile time:

```python
# Example workflow execution demonstrating why runtime resolution is essential:

Node1 executes:
  - Writes shared["video_data"] = {"title": "Python Tutorial"}

Node2 executes:
  - Has param: {"prompt": "Summarize: $video_data.title"}
  - Must see: "Summarize: Python Tutorial"

Node3 executes:
  - Updates shared["video_data"] = {"title": "Advanced Python Tutorial"}

Node4 executes:
  - Has param: {"report": "Final video: $video_data.title"}
  - Must see: "Final video: Advanced Python Tutorial"  # NOT the old value!
```

The template must resolve to the CURRENT value in shared store at execution time.

## Two-Phase Architecture: Validation and Resolution

The template variable system operates in two distinct phases:

### Phase 1: Validation (Before Execution)
**When**: Before workflow execution begins
**Purpose**: Ensure all required parameters are available
**Called by**: Both planner and CLI (shared validation logic)

```
MVP Path: Planner → validate_templates() → fix if invalid → CLI → validate again → execute
v2.0 Path: CLI loads workflow → validate_templates() → error if missing → execute
```

**What it validates**:
- All CLI parameters referenced in templates are provided
- Template syntax is correct (`$var` or `$var.field.subfield`)
- No malformed paths or syntax errors

**Key insight**: We can validate CLI parameters completely because they're known at start. Shared store values can't be validated until runtime.

### Phase 2: Resolution (During Execution)
**When**: As each node executes
**Purpose**: Replace template variables with actual values
**Called by**: Node wrapper during execution

**Resolution sources** (in priority order):
1. Initial parameters from planner/CLI
2. Shared store values from node execution

**Behavior**: If a template can't be resolved, it remains as-is (e.g., `$missing_var`) for debugging visibility.

### Why Both Phases in One Task?

1. **Shared Logic**: Both need to parse template syntax
2. **Complete Feature**: Validation without resolution is useless
3. **v2.0 Requirement**: Direct execution needs validation
4. **Code Reuse**: Same regex patterns and parsing logic

**Critical for v2.0**: When users run `pflow fix-issue --issue=1234` directly (without planner), the template system must validate that all required parameters are provided. Without validation as part of task 18, v2.0 workflows would fail with cryptic `$missing_param` in outputs.

## Requirements and Specifications

### Functional Requirements

1. **Template Variable Detection**
   - MUST detect template variables in any string parameter value
   - MUST support `$variable` syntax only (planner generates this format)
   - MUST support nested path access: `$variable.field.subfield`
   - MUST handle multiple variables in a single string
   - MUST extract variables for both validation and resolution

2. **Template Validation** (New)
   - MUST validate all templates before workflow execution
   - MUST check CLI parameters are provided for referenced variables
   - MUST return clear error messages for missing parameters
   - MUST distinguish between CLI parameters and shared store variables
   - MUST be callable by both planner and CLI

3. **Template Resolution**
   - MUST resolve from shared store (workflow runtime data)
   - MUST resolve from parameter values extracted by planner
   - MUST prioritize planner-extracted parameters over shared store when same key exists
   - MUST maintain resolution context throughout workflow execution

4. **Path Traversal**
   - MUST traverse nested dictionaries using dot notation
   - MUST handle missing paths gracefully (no exceptions)
   - MUST convert all resolved values to strings
   - MUST preserve original template if path cannot be resolved

5. **Node Transparency**
   - MUST NOT require changes to existing node implementations
   - MUST intercept at the `_run()` method only
   - MUST preserve node atomicity and isolation
   - MUST work with all existing pflow nodes

### Technical Specifications

1. **Template Syntax**
   ```
   variable_pattern = $identifier
   identifier = word_char+ ( '.' word_char+ )*
   word_char = [a-zA-Z0-9_]

   Format: $identifier (only format supported)
   Path access: $field.subfield
   ```

2. **Resolution Algorithm**
   ```
   1. Parse template string to find all variables
   2. For each variable:
      a. Split by '.' to get path components
      b. Traverse context dict following path
      c. Convert final value to string
      d. Replace template with resolved value
   3. Return modified string
   ```

   **Critical: Single-Phase Runtime Resolution**
   ALL template resolution happens at runtime, never at compile time. This ensures consistent behavior whether a template appears as a complete value or embedded in a string:
   ```json
   // Both work identically because resolution happens at runtime with full context:
   {"url": "$endpoint"}                    // Complete value
   {"prompt": "Analyze video at $url"}     // Embedded in string
   ```

3. **Priority Order**
   ```
   Resolution Context = {
     ...shared_store,           # Lower priority (runtime data)
     ...planner_parameters      # Higher priority (extracted values)
   }
   ```

4. **Error Handling**
   - Invalid paths: Leave template unchanged (e.g., `$missing.path` remains `$missing.path`)
   - Non-dict traversal: Stop and leave template unchanged
   - Null/None values: Convert to empty string ("")
   - Complex objects: Convert using str() function
   - **Missing variables**: Template remains unchanged for debugging
   - **Resolution failures are not errors**: Nodes using fallback pattern handle missing values gracefully

5. **Type Conversion Rules**
   ```python
   None → ""         # Empty string
   "" → ""          # Empty string stays empty
   0 → "0"          # Zero becomes string "0"
   False → "False"  # Boolean becomes string "False"
   [] → "[]"        # Empty list becomes string "[]"
   {} → "{}"        # Empty dict becomes string "{}"
   ```

### Non-Functional Requirements

1. **Performance**
   - Resolution MUST complete in O(n*m) time where n=template length, m=path depth
   - No caching required for MVP (stateless resolution)

2. **Compatibility**
   - MUST work with Python 3.8+
   - MUST integrate with existing PocketFlow execution model
   - MUST maintain backward compatibility with non-template parameters

3. **Maintainability**
   - Code MUST be isolated in dedicated modules
   - MUST include comprehensive test coverage
   - MUST follow existing pflow code patterns

### Out of Scope for MVP

1. Array indexing: `$items.0.name`
2. Expression evaluation: `$count + 1`
3. Method calls: `$name.upper()`
4. Default values: `$var|default`
5. Type preservation (everything converts to string)
6. Proxy mappings or key renaming (deferred to task 9, v2.0)
7. Compile-time resolution
8. `${var}` brace syntax (only `$var` supported)

**Note on Proxy Mappings**: While some research documents discuss proxy mappings extensively, these are NOT part of the MVP implementation. Task 9 will implement proxy mappings in v2.0 to handle shared store key collisions. For MVP, we assume nodes don't overwrite each other's keys.

## What You're Building

A complete template variable system with two components:

### 1. Template Validator
- Validates workflows before execution
- Ensures all required CLI parameters are provided
- Returns clear errors: `"Missing required parameter: --url"`
- Called by both planner and CLI

### 2. Template Resolver
- Detects template variables in node parameters: `$variable` format only
- Supports path-based access to nested data: `$transcript_data.metadata.author`
- Resolves variables at runtime from two sources:
  - Planner-extracted parameters (higher priority)
  - Shared store values from node execution (lower priority)
- Converts all values to strings
- Works transparently without modifying existing nodes

**Real-World Example**:
```json
// User says: "summarize this youtube video https://youtube.com/watch?v=xyz"
// Planner extracts: {"url": "https://youtube.com/watch?v=xyz"}
// Workflow contains:
{
  "nodes": [
    {"id": "fetch_transcript", "type": "youtube-transcript",
     "params": {"url": "$url"}},
    {"id": "summarize", "type": "llm",
     "params": {"prompt": "Summarize this video titled '$transcript_data.title' by $transcript_data.metadata.author:\n\n$transcript_data.text"}}
  ]
}

// Runtime resolution:
// - $url → "https://youtube.com/watch?v=xyz" (from planner parameters)
// - $transcript_data.title → "How to Learn Programming" (from shared["transcript_data"]["title"])
// - $transcript_data.text → "In this video, we'll explore..." (from shared store)
```

## How Nodes Write to Shared Store

Understanding how nodes create the data structure that templates access is crucial:

```python
# Example: youtube-transcript node writes its output
def post(self, shared, result):
    # Nodes write directly to shared store keys
    shared["transcript_data"] = {
        "video_id": "xyz123",
        "title": "How to Learn Programming",
        "duration": 1200,
        "text": "In this video, we'll explore...",
        "metadata": {
            "author": "TechChannel",
            "views": 50000
        }
    }

# Templates can access this data using paths:
# $transcript_data.title → "How to Learn Programming"
# $transcript_data.metadata.author → "TechChannel"
```

**Key Pattern**: Nodes write directly to named keys in the shared store based on their output. The template resolver traverses this structure using dot notation. For MVP, we assume no key collisions between nodes.

## Template Variable Constraints

**CRITICAL**: Template variables can ONLY be used in node `params` values:
- ✅ `{"params": {"prompt": "Hello $name"}}` - CORRECT
- ❌ `{"id": "$dynamic_id"}` - NOT SUPPORTED
- ❌ `{"type": "$node_type"}` - NOT SUPPORTED
- ❌ `{"edges": [{"from": "$node1", "to": "$node2"}]}` - NOT SUPPORTED

The JSON IR structure (id, type, edges) must be static. Only parameter values can be dynamic.

## Critical PocketFlow Constraints

Understanding these constraints is essential for implementation:

### 1. Parameters Are Immutable During Execution
```python
# Once set_params() is called:
node.set_params({"file": "data.txt"})
# Node accesses params directly - we CANNOT intercept:
file_path = self.params["file"]  # No proxy possible here!
```

### 2. The Only Interception Point
```python
def _run(self, shared):  # <-- We can only intercept here
    # This is where we can modify node.params before execution
```

### 3. Nodes Are Copied Before Execution
```python
# PocketFlow does this internally:
curr = copy.copy(node)  # Fresh copy for each execution
curr.set_params(params)
curr._run(shared)       # Our interception point
```

## The Fallback Pattern Foundation

Every pflow node implements this pattern:
```python
# In EVERY node's prep() method:
value = shared.get("key") or self.params.get("key")
```

This enables template variables in params to work as dynamic values.

### Why This Pattern Enables Template Variables

This fallback pattern is implemented in EVERY pflow node and is the foundation that makes template variables work:

1. **Node attempts to read from shared store first**: `shared.get("key")`
2. **Falls back to params if not in shared**: `or self.params.get("key")`
3. **Template resolver leverages this**: By putting resolved values in params, they become available to nodes

Example flow:
- Planner extracts: `{"issue_number": "1234"}` from "fix issue 1234"
- Workflow has: `{"params": {"issue": "$issue_number"}}`
- Template resolver: Puts "1234" in node's params
- Node's prep(): `shared.get("issue") or self.params.get("issue")` gets "1234"

This elegant pattern means nodes don't need modification to support templates!

## Implementation Design

### Core Components

1. **TemplateResolver**: Detects and resolves template variables with path support
2. **TemplateAwareNodeWrapper**: Wraps nodes to provide transparent resolution
3. **Compiler Integration**: Wraps nodes that have template parameters

### Resolution Process

1. Detect template variables in parameters
2. At runtime, build context from shared store + planner parameters
3. Resolve paths by traversing nested objects
4. Replace templates with string values
5. Update node params before execution

## Code Implementation

### Phase 0: Template Validator

```python
# src/pflow/runtime/template_validator.py

from typing import Dict, List, Set, Any
from .template_resolver import TemplateResolver

class TemplateValidator:
    """Validates template variables before workflow execution."""

    @staticmethod
    def validate_workflow_templates(
        workflow_ir: Dict[str, Any],
        available_params: Dict[str, Any]
    ) -> List[str]:
        """
        Validates all template variables in a workflow.

        Args:
            workflow_ir: The workflow IR containing nodes with template parameters
            available_params: Parameters available from planner or CLI

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Extract all templates from workflow
        all_templates = TemplateValidator._extract_all_templates(workflow_ir)

        # Separate CLI params from potential shared store vars
        cli_params = set()
        shared_vars = set()

        for template in all_templates:
            # Get base variable name (before any dots)
            base_var = template.split('.')[0]

            # Heuristic: if it matches a known param, it's a CLI param
            # Otherwise, assume it's from shared store
            if base_var in available_params:
                cli_params.add(base_var)
            else:
                shared_vars.add(template)

        # Note: In v2.0+, workflows will include metadata with expected inputs:
        # {"inputs": ["url", "issue_number"], "ir": {...}}
        # This will make validation more precise than the current heuristic

        # Validate CLI parameters - these MUST be provided
        missing_params = cli_params - set(available_params.keys())
        for param in missing_params:
            errors.append(f"Missing required parameter: --{param}")

        # For shared store variables, we can't validate until runtime
        # But we can check syntax
        for var in shared_vars:
            if not TemplateValidator._is_valid_syntax(var):
                errors.append(f"Invalid template syntax: ${var}")

        return errors

    @staticmethod
    def _extract_all_templates(workflow_ir: Dict[str, Any]) -> Set[str]:
        """Extract all template variables from workflow."""
        templates = set()

        for node in workflow_ir.get('nodes', []):
            for param_value in node.get('params', {}).values():
                if TemplateResolver.has_templates(param_value):
                    # Extract variable names
                    templates.update(TemplateResolver.extract_variables(param_value))

        return templates

    @staticmethod
    def _is_valid_syntax(template: str) -> bool:
        """Check if template syntax is valid."""
        # Basic checks: no double dots, valid characters
        if '..' in template:
            return False
        if template.startswith('.') or template.endswith('.'):
            return False
        # More validation as needed
        return True
```

### Phase 1: Template Resolver

```python
# src/pflow/runtime/template_resolver.py

import re
from typing import Dict, Set, Any, Optional

class TemplateResolver:
    """Handles template variable detection and resolution with path support."""

    # Pattern supports $var format with paths
    TEMPLATE_PATTERN = re.compile(r'\$(\w+(?:\.\w+)*)')

    @staticmethod
    def has_templates(value: Any) -> bool:
        """Check if value contains template variables."""
        return isinstance(value, str) and '$' in value

    @staticmethod
    def extract_variables(value: str) -> Set[str]:
        """Extract all template variable names (including paths)."""
        return set(TemplateResolver.TEMPLATE_PATTERN.findall(value))

    @staticmethod
    def resolve_value(var_name: str, context: Dict[str, Any]) -> Optional[Any]:
        """Resolve a variable name (possibly with path) from context."""
        if '.' in var_name:
            # Handle path traversal like github_main.issue_data.title
            parts = var_name.split('.')
            value = context
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return None
            return value
        else:
            # Simple variable
            return context.get(var_name)

    @staticmethod
    def resolve_string(template: str, context: Dict[str, Any]) -> str:
        """Resolve all template variables in a string."""
        result = template

        for match in TemplateResolver.TEMPLATE_PATTERN.finditer(template):
            var_name = match.group(1)
            value = TemplateResolver.resolve_value(var_name, context)

            if value is not None:
                # Convert to string - explicit handling for None
                if value is None:
                    value_str = ""
                else:
                    value_str = str(value)

                # Replace $var format
                result = result.replace(f'${var_name}', value_str)

        return result
```

### Phase 2: Node Wrapper

```python
# src/pflow/runtime/node_wrapper.py

from typing import Dict, Any, Optional
from .template_resolver import TemplateResolver

class TemplateAwareNodeWrapper:
    """Wraps nodes to provide transparent template resolution.

    This is the runtime proxy that enables "Plan Once, Run Forever".
    """

    def __init__(self, inner_node, node_id: str, initial_params: Optional[Dict[str, Any]] = None):
        """
        Args:
            inner_node: The actual node being wrapped
            node_id: Node identifier from IR (creates namespace in shared store)
            initial_params: Parameters extracted by planner from natural language
        """
        self.inner_node = inner_node
        self.node_id = node_id  # Node ID creates namespace: shared[node_id]
        self.initial_params = initial_params or {}  # From planner extraction
        self.template_params = {}
        self.static_params = {}

    def set_params(self, params: Dict[str, Any]):
        """Separate template params from static params."""
        self.template_params.clear()
        self.static_params.clear()

        for key, value in params.items():
            if TemplateResolver.has_templates(value):
                self.template_params[key] = value
            else:
                self.static_params[key] = value

        # Set only static params on inner node
        self.inner_node.set_params(self.static_params)

    def _run(self, shared: Dict[str, Any]) -> Any:
        """Execute with template resolution."""
        # Skip if no templates
        if not self.template_params:
            return self.inner_node._run(shared)

        # Build resolution context: shared store + planner parameters
        # Planner parameters have higher priority (come second in update)
        context = dict(shared)  # Start with shared store (includes node namespaces)
        context.update(self.initial_params)  # Planner parameters override

        # Resolve all template parameters
        resolved_params = {}
        for key, template in self.template_params.items():
            resolved_params[key] = TemplateResolver.resolve_string(template, context)

        # Temporarily update inner node params
        original_params = self.inner_node.params
        merged_params = {**self.static_params, **resolved_params}
        self.inner_node.params = merged_params

        try:
            # Execute with resolved params
            return self.inner_node._run(shared)
        finally:
            # Restore original (though node copy will be discarded)
            self.inner_node.params = original_params

    def __getattr__(self, name):
        """Delegate all other attributes to inner node."""
        return getattr(self.inner_node, name)

    # Note: __setattr__ is not strictly needed for PocketFlow's set_params() pattern,
    # but is included for completeness to ensure the wrapper is fully transparent
    # if nodes use any direct attribute access patterns
    def __setattr__(self, name: str, value: Any) -> None:
        """Handle attribute setting to maintain proxy transparency."""
        # Define proxy's own attributes
        if name in ['inner_node', 'node_id', 'initial_params', 'template_params', 'static_params']:
            super().__setattr__(name, value)
        else:
            # Everything else goes to inner node
            setattr(self.inner_node, name, value)
```

### Phase 3: Compiler Integration

```python
# Modifications to src/pflow/runtime/compiler.py

from .template_validator import TemplateValidator
from .template_resolver import TemplateResolver
from .node_wrapper import TemplateAwareNodeWrapper

def compile_ir_to_flow(
    ir_dict: Dict[str, Any],
    registry: Registry,
    initial_params: Optional[Dict[str, Any]] = None,
    validate: bool = True
) -> Flow:
    """Compile IR with template variable support.

    Args:
        ir_dict: The workflow IR containing template variables
        registry: Node registry
        initial_params: Parameters extracted by planner from natural language
                       Example: {"issue_number": "1234", "repo": "pflow"}
                       from user saying "fix github issue 1234 in pflow repo"
        validate: Whether to validate templates (default: True)

    Raises:
        ValueError: If template validation fails
    """
    initial_params = initial_params or {}

    # Phase 1: Validate templates before compilation
    if validate:
        errors = TemplateValidator.validate_workflow_templates(ir_dict, initial_params)
        if errors:
            error_msg = "Template validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ValueError(error_msg)

    # Phase 2: Compile workflow with template support
    flow = Flow()
    nodes = {}

    # Create nodes
    for node_spec in ir_dict['nodes']:
        node_id = node_spec['id']
        node_type = node_spec['type']
        params = node_spec.get('params', {})

        # Get node class and instantiate
        node_class = registry.get(node_type)
        node = node_class()

        # Check if any parameters contain templates
        has_templates = any(TemplateResolver.has_templates(v) for v in params.values())

        if has_templates:
            # Wrap node for template support (runtime proxy)
            node = TemplateAwareNodeWrapper(node, node_id, initial_params)

        # Set parameters (wrapper will separate template vs static)
        node.set_params(params)
        nodes[node_id] = node
        flow.add_node(node_id, node)

    # Add edges
    for edge in ir_dict.get('edges', []):
        flow.add_edge(edge['from'], edge.get('action', 'default'), edge['to'])

    # Set start node
    if 'start_node' in ir_dict:
        flow.set_start(ir_dict['start_node'])

    return flow
```

## Complete End-to-End Example

Let's trace the complete flow from natural language to execution:

```python
# 1. User Input
user_input = "summarize this youtube video https://youtube.com/watch?v=xyz in bullet points"

# 2. Planner Extracts Parameters
planner_output = {
    "workflow_ir": {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "fetch",
                "type": "youtube-transcript",
                "params": {
                    "url": "$url"
                }
            },
            {
                "id": "summarize",
                "type": "llm",
                "params": {
                    "prompt": "Create a bullet-point summary of this video:\n\nTitle: $transcript_data.title\nAuthor: $transcript_data.metadata.author\n\nTranscript:\n$transcript_data.text"
                }
            },
            {
                "id": "save",
                "type": "write-file",
                "params": {
                    "file_path": "video_summary.md",
                    "content": "# $transcript_data.title\n\n$summary"
                }
            }
        ],
        "edges": [
            {"from": "fetch", "to": "summarize"},
            {"from": "summarize", "to": "save"}
        ]
    },
    "parameter_values": {
        "url": "https://youtube.com/watch?v=xyz"
    }
}

# 3. CLI Compiles with Template Support
flow = compile_ir_to_flow(
    planner_output["workflow_ir"],
    registry,
    initial_params=planner_output["parameter_values"]
)

# 4. Execution - First Node (fetch)
# Template resolution:
# - $url → "https://youtube.com/watch?v=xyz" (from initial_params)
# Node receives: {"url": "https://youtube.com/watch?v=xyz"}

# Node executes and writes to shared store:
shared["transcript_data"] = {
    "video_id": "xyz",
    "title": "How to Learn Programming",
    "duration": 1200,
    "text": "In this video, we'll explore the best strategies...",
    "metadata": {
        "author": "TechChannel",
        "views": 50000
    }
}

# 5. Execution - Second Node (summarize)
# Template resolution:
# - $transcript_data.title → "How to Learn Programming" (from shared store)
# - $transcript_data.metadata.author → "TechChannel" (from shared store)
# - $transcript_data.text → "In this video, we'll explore..." (from shared store)

# Node executes and writes:
shared["summary"] = "• Start with fundamentals\n• Practice daily\n• Build projects..."

# 6. Execution - Third Node (save)
# Template resolution:
# - $transcript_data.title → "How to Learn Programming" (from shared store)
# - $summary → "• Start with fundamentals..." (from shared store)
# Node receives resolved content and saves to file
```

## Testing Strategy

### Core Tests

```python
# tests/test_runtime/test_template_resolver.py

def test_planner_parameter_flow():
    """Test parameters extracted by planner from natural language."""
    # Simulating planner extraction from "fix github issue 1234"
    planner_params = {
        "issue_number": "1234",
        "repo": "pflow"
    }

    template = "Working on issue $issue_number in $repo"
    result = TemplateResolver.resolve_string(template, planner_params)
    assert result == "Working on issue 1234 in pflow"

def test_shared_store_path_access():
    """Test accessing nested data in shared store."""
    # Nodes write directly to shared store keys
    context = {
        "transcript_data": {
            "video_id": "xyz",
            "title": "Learning Python",
            "metadata": {
                "author": "CodeTeacher",
                "duration": 3600
            }
        },
        "summary": "Python is a versatile language..."
    }

    template = "Video: $transcript_data.title by $transcript_data.metadata.author"
    result = TemplateResolver.resolve_string(template, context)
    assert result == "Video: Learning Python by CodeTeacher"

def test_priority_planner_over_shared():
    """Test that planner parameters override shared store values."""
    wrapper = TemplateAwareNodeWrapper(
        TestNode(),
        "test",
        initial_params={"issue_number": "1234"}  # From planner
    )
    wrapper.set_params({"message": "Issue $issue_number"})

    shared = {"issue_number": "5678"}  # Different value in shared
    result = wrapper._run(shared)
    assert "Issue 1234" in result  # Planner value wins

def test_real_workflow_template():
    """Test template from actual workflow example."""
    context = {
        "transcript_data": {
            "video_id": "xyz",
            "title": "How to Learn Programming",
            "text": "In this video, we'll explore...",
            "metadata": {
                "author": "TechChannel",
                "views": 50000
            }
        },
        "summary": "• Start with fundamentals\n• Practice daily\n• Build projects",
        "url": "https://youtube.com/watch?v=xyz"
    }

    # Template from example workflow
    template = "Summary of '$transcript_data.title' by $transcript_data.metadata.author"
    result = TemplateResolver.resolve_string(template, context)
    assert result == "Summary of 'How to Learn Programming' by TechChannel"

def test_type_conversions():
    """Test explicit type conversion rules."""
    context = {
        "none_val": None,
        "empty_str": "",
        "zero": 0,
        "false": False,
        "empty_list": [],
        "empty_dict": {}
    }

    assert TemplateResolver.resolve_string("[$none_val]", context) == "[]"
    assert TemplateResolver.resolve_string("[$empty_str]", context) == "[]"
    assert TemplateResolver.resolve_string("[$zero]", context) == "[0]"
    assert TemplateResolver.resolve_string("[$false]", context) == "[False]"
    assert TemplateResolver.resolve_string("[$empty_list]", context) == "[[]]"
    assert TemplateResolver.resolve_string("[$empty_dict]", context) == "[{}]"

def test_complete_vs_embedded_templates():
    """Test that templates work identically as complete values or embedded in strings."""
    wrapper = TemplateAwareNodeWrapper(
        TestNode(),
        "test",
        initial_params={"video_id": "xyz123"}
    )
    wrapper.set_params({
        "id": "$video_id",                          # Complete value
        "message": "Processing video $video_id"     # Embedded in string
    })

    shared = {}
    wrapper._run(shared)

    # Both forms should resolve identically
    assert wrapper.inner_node.params["id"] == "xyz123"
    assert wrapper.inner_node.params["message"] == "Processing video xyz123"

def test_missing_template_variable():
    """Test that unresolved templates remain as-is for debugging."""
    context = {
        "url": "https://youtube.com/watch?v=xyz",
        # Note: missing 'video_title' that template references
    }

    template = "Processing video: $video_title from $url"
    result = TemplateResolver.resolve_string(template, context)

    # Missing variable remains as template, resolved variable is substituted
    assert result == "Processing video: $video_title from https://youtube.com/watch?v=xyz"
```

### Integration Tests

```python
def test_complete_workflow_with_planner_params():
    """Test full workflow execution with planner-extracted parameters."""
    # Workflow IR from planner
    ir = {
        "nodes": [
            {
                "id": "fetch",
                "type": "youtube-transcript",
                "params": {
                    "url": "$url"
                }
            },
            {
                "id": "summarize",
                "type": "llm",
                "params": {
                    "prompt": "Summarize: $transcript_data.title\n\n$transcript_data.text"
                }
            }
        ],
        "edges": [{"from": "fetch", "to": "summarize"}]
    }

    # Parameters extracted from "summarize this youtube video..."
    planner_params = {
        "url": "https://youtube.com/watch?v=xyz"
    }

    flow = compile_ir_to_flow(ir, registry, planner_params)
    shared = {}
    flow.run(shared)

    # Verify correct resolution throughout execution
    assert shared["transcript_data"]["video_id"] == "xyz"
    # LLM node should have received resolved prompt
```

### Validation Tests

```python
def test_template_validation_success():
    """Test successful validation when all params provided."""
    workflow_ir = {
        "nodes": [
            {"id": "fetch", "type": "youtube-transcript", "params": {"url": "$url"}},
            {"id": "save", "type": "write-file", "params": {
                "file_path": "summary.txt",
                "content": "$summary"
            }}
        ]
    }

    # All CLI params provided
    params = {"url": "https://youtube.com/watch?v=xyz"}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, params)
    assert len(errors) == 0  # No errors

def test_template_validation_missing_param():
    """Test validation catches missing CLI parameters."""
    workflow_ir = {
        "nodes": [
            {"id": "fetch", "type": "youtube-transcript", "params": {"url": "$url"}},
            {"id": "analyze", "type": "llm", "params": {"prompt": "Analyze $url"}}
        ]
    }

    # Missing 'url' parameter
    params = {}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, params)
    assert len(errors) == 1
    assert "Missing required parameter: --url" in errors[0]

def test_validation_distinguishes_cli_from_shared():
    """Test validation correctly identifies CLI params vs shared store."""
    workflow_ir = {
        "nodes": [
            {"id": "fetch", "type": "youtube-transcript", "params": {"url": "$url"}},
            {"id": "analyze", "type": "llm", "params": {
                "prompt": "Summarize: $transcript_data.title"  # From shared store
            }}
        ]
    }

    # Only CLI param provided
    params = {"url": "https://youtube.com/watch?v=xyz"}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, params)
    assert len(errors) == 0  # No errors - transcript_data is from shared store

def test_compile_with_validation():
    """Test that compile_ir_to_flow validates templates."""
    workflow_ir = {
        "nodes": [
            {"id": "process", "type": "processor", "params": {"input": "$missing_param"}}
        ]
    }

    # Try to compile without required parameter
    with pytest.raises(ValueError) as exc_info:
        compile_ir_to_flow(workflow_ir, registry, initial_params={})

    assert "Template validation failed" in str(exc_info.value)
    assert "Missing required parameter: --missing_param" in str(exc_info.value)
```

## Common Pitfalls and Solutions

### 1. Type Loss Through String Conversion
**Problem**: `$count` with value 3 becomes "3" (string)
**Solution**: Document this MVP limitation. All template values become strings. The planner validates paths exist using structure documentation.

### 2. Non-existent Paths
**Problem**: `$data.field.missing` when path doesn't exist
**Solution**: Leave template unchanged for debugging visibility (see test_missing_template_variable)

### 3. Array Access
**Problem**: User wants `$items.0.name` for array access
**Solution**: Not supported in MVP. Document as future enhancement.

### 4. Missing Variables
**Problem**: Template references variable not in planner params or shared store
**Solution**: Leave template unchanged - this helps debugging and matches planner validation

### 5. Complex Objects
**Problem**: `$user` where user is a complex object
**Solution**: Converts to string representation using str()

## Success Criteria

The implementation is complete when:

1. **Template validation works**:
   - Missing CLI parameters are caught before execution
   - Clear error messages: "Missing required parameter: --url"
   - Shared store variables are not flagged as errors
   - Both planner and CLI use the same validation

2. **Path-based access works**:
   ```json
   {"prompt": "Video '$transcript_data.title' by $transcript_data.metadata.author"}
   ```

3. **Planner parameters work**:
   ```python
   # From "summarize this youtube video...":
   planner_params = {"url": "https://youtube.com/watch?v=xyz"}
   # Template $url resolves correctly
   ```

4. **Dynamic values work**:
   - Templates can reference shared store values from previous nodes
   - Direct shared store keys are accessed properly
   - Nested paths traverse objects correctly

5. **Nodes remain unmodified**:
   - Existing nodes work without changes
   - Template resolution is transparent via runtime proxy

## MVP Limitations

Document these clearly for users:
1. All values convert to strings
2. No array indexing (`$items.0`)
3. No complex expressions or transformations
4. No fallback values or defaults
5. Missing paths leave template unchanged

## Implementation Checklist

- [ ] Implement TemplateResolver with path support
- [ ] Implement TemplateValidator for pre-execution validation
- [ ] Create comprehensive test suite for resolution and validation
- [ ] Implement TemplateAwareNodeWrapper
- [ ] Integrate validation with compiler (fail fast on missing params)
- [ ] Integrate resolution with runtime execution
- [ ] Test with real pflow nodes
- [ ] Document template syntax for users
- [ ] Add examples with nested paths
- [ ] Test edge cases (missing paths, null values, validation errors)

This implementation provides powerful template variable support with path traversal, enabling most workflow parameterization needs without the complexity of proxy mappings. It serves as the runtime proxy that makes pflow's "Plan Once, Run Forever" philosophy possible.
