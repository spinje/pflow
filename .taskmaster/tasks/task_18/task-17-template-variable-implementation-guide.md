# Template Variable Implementation Guide for pflow

## Executive Summary

This document provides comprehensive guidance for implementing template variable support in pflow - a critical feature that enables the "Plan Once, Run Forever" philosophy. Template variables allow workflows to be reusable by substituting different values at runtime, similar to how SQL prepared statements work.

The implementation uses a proxy pattern similar to the existing `NodeAwareSharedStore`, ensuring nodes remain atomic and unaware of the template system. This document is written for a coding agent who will implement this feature.

## Table of Contents

1. [Background and Context](#background-and-context)
2. [The Problem](#the-problem)
3. [Why This Matters](#why-this-matters)
4. [Current State Analysis](#current-state-analysis)
5. [Proposed Solution](#proposed-solution)
6. [Implementation Guide](#implementation-guide)
7. [Integration Points](#integration-points)
8. [Testing Strategy](#testing-strategy)
9. [Examples and Use Cases](#examples-and-use-cases)
10. [Risks and Mitigations](#risks-and-mitigations)
11. [Success Criteria](#success-criteria)

## Background and Context

### What is pflow?

pflow is a workflow compiler that transforms natural language or CLI pipe syntax into permanent, deterministic CLI commands. Its core value proposition is "Plan Once, Run Forever" - users describe what they want once, and pflow generates a reusable workflow.

### Architecture Overview

```
User Input → Planner → JSON IR → Compiler → PocketFlow Flow → Execution
```

- **Planner**: Generates workflow definitions (JSON IR)
- **JSON IR**: Intermediate representation with nodes, edges, and parameters
- **Compiler**: Converts IR to executable PocketFlow objects
- **PocketFlow**: Minimal 200-line orchestration framework
- **Execution**: Runs the workflow with a shared store for inter-node communication

### What are Template Variables?

Template variables are placeholder strings in workflow parameters that get replaced with actual values at runtime:

```json
{
  "nodes": [
    {"id": "n1", "type": "github-get-issue", "params": {"issue": "$issue_number"}}
  ]
}
```

The `$issue_number` is a template variable that might be replaced with "1234", "5678", etc. on different runs.

## The Problem

### Two Types of Template Variables

1. **Initial Parameters** - Values known at workflow start
   ```
   User: "fix github issue 1234"
   Template: $issue_number
   Value: "1234" (extracted from natural language)
   ```

2. **Shared Store References** - Values created during execution
   ```
   Node 1 writes: shared["issue_data"] = {actual issue content}
   Node 2 uses: "Fix this issue: $issue_data"
   ```

### The Challenge

PocketFlow nodes are atomic - they receive static parameters via `set_params()` before execution begins. But template variables need dynamic resolution:

- Initial parameters need substitution before node execution
- Shared store references need substitution during workflow execution
- Nodes must remain unaware of templates (architectural principle)

### Current Limitations

No template substitution infrastructure currently exists. Workflows with template variables cannot be executed - the `$` placeholders remain as literal strings.

## Why This Matters

### Core to the Value Proposition

Without template variables, workflows are single-use:
```bash
# Without templates - new workflow needed for each issue
pflow "fix github issue 1234"  # Creates workflow specific to issue 1234
pflow "fix github issue 5678"  # Would need entirely new workflow

# With templates - reuse the same workflow
pflow fix-issue --issue=1234
pflow fix-issue --issue=5678
```

### Enables Natural Language Planning

The planner can generate generic, reusable workflows:
```json
{
  "params": {"prompt": "Summarize the file: $filename"}
}
```

Instead of hardcoding:
```json
{
  "params": {"prompt": "Summarize the file: report.txt"}  // Not reusable!
}
```

### Supports Complex Workflows

Nodes can reference outputs from previous nodes:
```
github-get-issue → shared["issue_data"]
llm with prompt "Fix: $issue_data" → shared["fix_code"]
git-commit with message "Fix: $issue_title - $commit_summary"
```

## Current State Analysis

### What Exists

1. **JSON IR Schema** (`src/pflow/core/ir_schema.py`)
   - Supports params with string values
   - No special handling for `$` variables
   - No `template_inputs` or `variable_flow` fields (despite documentation)

2. **NodeAwareSharedStore** (`src/pflow/runtime/proxy.py` or similar)
   - Proven proxy pattern for transparent key mapping
   - Already intercepts shared store access without node awareness

3. **PocketFlow Framework** (`pocketflow/__init__.py`)
   - 200-line orchestration framework
   - Must not be modified
   - Sets params once via `set_params()` before execution

4. **Compiler** (`src/pflow/runtime/compiler.py`)
   - Converts IR to Flow objects
   - Controls node instantiation
   - Natural place for proxy wrapping

### What's Missing

1. **Template Resolution Logic**
   - Pattern matching for `$variable` syntax
   - Substitution engine
   - Resolution ordering

2. **Runtime Integration**
   - Proxy wrapper for nodes with templates
   - Two-phase substitution coordination
   - Error handling for missing variables

3. **CLI Parameter Passing**
   - Mechanism to pass `--key=value` parameters
   - Storage format for parameter definitions
   - Validation of required parameters

## Proposed Solution

### High-Level Approach

Use a proxy pattern (like `NodeAwareSharedStore`) to transparently resolve templates without modifying nodes or PocketFlow:

```python
Node (thinks it has) → params: {"prompt": "Fix: actual issue content"}
                ↑
    TemplateResolvingProxy (converts from) → params: {"prompt": "Fix: $issue_data"}
```

### Two-Phase Resolution

1. **Compile-Time Resolution** (Initial Parameters)
   ```python
   # Before creating Flow objects
   workflow_ir = substitute_initial_params(workflow_ir, {"issue_number": "1234"})
   ```

2. **Runtime Resolution** (Shared Store References)
   ```python
   # During execution, via proxy
   node = TemplateResolvingNodeProxy(node, template_params)
   ```

### Architecture Diagram

```
┌─────────────────┐
│   Workflow IR   │  Contains: params: {"prompt": "Fix: $issue_data"}
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    Compiler     │  1. Substitutes initial params ($issue_number → "1234")
│                 │  2. Detects remaining templates
│                 │  3. Wraps nodes with proxy if needed
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Template Proxy  │  Intercepts _run() to resolve shared store templates
│    (if needed)  │  just before node execution
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Actual Node   │  Sees resolved params, remains atomic
└─────────────────┘
```

## Implementation Guide

### Phase 1: Template Detection and Parsing

```python
# src/pflow/runtime/template_resolver.py

import re
from typing import Dict, Set, Any, Union

class TemplateResolver:
    """Handles template variable detection and resolution."""

    # Regex pattern for $variable or ${variable}
    TEMPLATE_PATTERN = re.compile(r'\$\{?(\w+)\}?')

    @staticmethod
    def has_templates(value: Any) -> bool:
        """Check if a value contains template variables."""
        if not isinstance(value, str):
            return False
        return '$' in value

    @staticmethod
    def extract_variables(value: str) -> Set[str]:
        """Extract all template variable names from a string."""
        return set(TemplateResolver.TEMPLATE_PATTERN.findall(value))

    @staticmethod
    def resolve_string(template: str, values: Dict[str, Any]) -> str:
        """Resolve all template variables in a string."""
        result = template

        # Find all variables in the template
        for match in TemplateResolver.TEMPLATE_PATTERN.finditer(template):
            var_name = match.group(1)
            if var_name in values:
                # Replace both $var and ${var} formats
                result = result.replace(f"${{{var_name}}}", str(values[var_name]))
                result = result.replace(f"${var_name}", str(values[var_name]))

        return result

    @staticmethod
    def resolve_params(params: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve all template variables in a params dictionary."""
        resolved = {}

        for key, value in params.items():
            if isinstance(value, str) and TemplateResolver.has_templates(value):
                resolved[key] = TemplateResolver.resolve_string(value, values)
            elif isinstance(value, dict):
                # Recursively resolve nested dicts
                resolved[key] = TemplateResolver.resolve_params(value, values)
            elif isinstance(value, list):
                # Handle lists with potential templates
                resolved[key] = [
                    TemplateResolver.resolve_string(item, values)
                    if isinstance(item, str) and TemplateResolver.has_templates(item)
                    else item
                    for item in value
                ]
            else:
                resolved[key] = value

        return resolved
```

### Phase 2: Node Proxy Implementation

```python
# src/pflow/runtime/template_proxy.py

from typing import Dict, Any, Optional

class TemplateResolvingNodeProxy:
    """
    Proxy that transparently resolves template variables in node parameters.

    This follows the same pattern as NodeAwareSharedStore - nodes remain
    completely unaware that template resolution is happening.
    """

    def __init__(self, inner_node, node_id: str, template_params: Dict[str, Any]):
        """
        Args:
            inner_node: The actual node instance
            node_id: Unique identifier for this node
            template_params: Parameters that contain template variables
        """
        self._inner_node = inner_node
        self._node_id = node_id
        self._template_params = template_params

        # Separate static params (no templates) from template params
        self._static_params = {}
        for key, value in inner_node.params.items():
            if not (isinstance(value, str) and '$' in str(value)):
                self._static_params[key] = value

    def _run(self, shared: Dict[str, Any]) -> Any:
        """
        Intercept node execution to resolve templates just-in-time.

        This method:
        1. Resolves all template variables using current shared store state
        2. Temporarily sets resolved params on the node
        3. Executes the node
        4. Restores original params (keeps node reusable)
        """
        # Start with static params
        resolved_params = self._static_params.copy()

        # Resolve template params using current shared store state
        from .template_resolver import TemplateResolver
        template_resolved = TemplateResolver.resolve_params(
            self._template_params,
            shared
        )
        resolved_params.update(template_resolved)

        # Store original params
        original_params = self._inner_node.params

        try:
            # Set resolved params - node sees actual values, not templates!
            self._inner_node.params = resolved_params

            # Execute the node normally
            return self._inner_node._run(shared)

        finally:
            # Always restore original params to keep node stateless
            self._inner_node.params = original_params

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attributes to the inner node."""
        return getattr(self._inner_node, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Handle attribute setting carefully."""
        if name.startswith('_'):
            # Our internal attributes
            super().__setattr__(name, value)
        else:
            # Delegate to inner node
            setattr(self._inner_node, name, value)
```

### Phase 3: Compiler Integration

```python
# Modifications to src/pflow/runtime/compiler.py

def compile_ir_to_flow(
    ir_dict: Dict[str, Any],
    registry: Registry,
    initial_params: Optional[Dict[str, Any]] = None
) -> Flow:
    """
    Compile IR to executable Flow with template variable support.

    Args:
        ir_dict: The workflow IR
        registry: Node registry
        initial_params: Initial parameters for template substitution
    """
    # Phase 1: Substitute initial parameters in a copy of the IR
    if initial_params:
        ir_dict = _substitute_initial_params(ir_dict, initial_params)

    # Create the flow
    flow = Flow()
    nodes = {}

    # Create nodes with template proxy wrapping if needed
    for node_spec in ir_dict["nodes"]:
        node_id = node_spec["id"]
        node_type = node_spec["type"]
        params = node_spec.get("params", {})

        # Get node class from registry
        node_class = registry.get(node_type)
        if not node_class:
            raise ValueError(f"Unknown node type: {node_type}")

        # Create node instance
        node = node_class()

        # Check if params contain template variables
        template_params = _extract_template_params(params)

        if template_params:
            # Wrap node in template proxy
            from .template_proxy import TemplateResolvingNodeProxy
            node = TemplateResolvingNodeProxy(node, node_id, template_params)

        # Set all params (including templates) on the node/proxy
        node.set_params(params)

        nodes[node_id] = node

    # Build edges (rest of compilation logic remains the same)
    # ...

    return flow


def _substitute_initial_params(
    ir_dict: Dict[str, Any],
    initial_params: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Substitute initial parameters (from CLI) in the IR.

    This handles the first phase of template resolution - replacing
    variables that are known at workflow start time.
    """
    import copy
    from .template_resolver import TemplateResolver

    # Deep copy to avoid modifying original
    ir_copy = copy.deepcopy(ir_dict)

    # Substitute in each node's params
    for node_spec in ir_copy.get("nodes", []):
        if "params" in node_spec:
            node_spec["params"] = TemplateResolver.resolve_params(
                node_spec["params"],
                initial_params
            )

    return ir_copy


def _extract_template_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract only the parameters that contain template variables.

    Returns a dict of just the params that need runtime resolution.
    """
    from .template_resolver import TemplateResolver

    template_params = {}

    for key, value in params.items():
        if isinstance(value, str) and TemplateResolver.has_templates(value):
            template_params[key] = value
        elif isinstance(value, (dict, list)):
            # Could contain nested templates
            # For MVP, we might skip this complexity
            pass

    return template_params
```

### Phase 4: Integration with Existing Proxy Mapping

The template proxy works alongside the existing `NodeAwareSharedStore`:

```python
# In the execution logic (wherever nodes are run with proxies)

def execute_node_with_mappings(node, shared, mappings=None):
    """Execute a node with both proxy types if needed."""

    # Layer 1: NodeAwareSharedStore (if mappings exist)
    if mappings:
        # This proxy handles input/output key mapping
        proxy_shared = NodeAwareSharedStore(
            shared,
            input_mappings=mappings.get("input_mappings"),
            output_mappings=mappings.get("output_mappings")
        )
    else:
        proxy_shared = shared

    # Layer 2: Template resolution is handled by the node proxy itself
    # (already set up during compilation)

    # Execute - both proxies work together transparently!
    return node._run(proxy_shared)
```

## Integration Points

### 1. CLI Changes

The CLI needs to accept and pass parameters:

```python
# In src/pflow/cli/main.py

@click.command()
@click.argument('workflow_name')
@click.option('--param', '-p', multiple=True,
              help='Parameters in key=value format')
def run_workflow(workflow_name, param):
    """Run a saved workflow with parameters."""

    # Parse parameters
    params = {}
    for p in param:
        key, value = p.split('=', 1)
        params[key] = value

    # Load workflow
    workflow = load_workflow(workflow_name)

    # Compile with parameters
    flow = compile_ir_to_flow(workflow['ir'], registry, params)

    # Execute
    shared = {}
    result = flow.run(shared)
```

### 2. Planner Integration

The planner should return parameter information:

```python
{
    "workflow_ir": {
        "nodes": [...],  # Contains $variables
        "edges": [...]
    },
    "parameter_values": {
        "issue_number": "1234",  # Extracted from NL
        "date": "2024-01-20"     # Interpreted
    },
    "workflow_metadata": {
        "required_params": ["issue_number"],  # For validation
        "optional_params": ["priority"]
    }
}
```

### 3. Workflow Storage

Saved workflows should include parameter metadata:

```json
{
  "name": "fix-issue",
  "description": "Fix a GitHub issue",
  "parameters": {
    "issue_number": {
      "type": "string",
      "required": true,
      "description": "GitHub issue number"
    }
  },
  "ir": {
    "nodes": [...],  // Contains $issue_number
    "edges": [...]
  }
}
```

## Testing Strategy

### Unit Tests

```python
def test_template_detection():
    """Test that template variables are correctly detected."""
    from pflow.runtime.template_resolver import TemplateResolver

    assert TemplateResolver.has_templates("Fix: $issue")
    assert TemplateResolver.has_templates("${name} - ${date}")
    assert not TemplateResolver.has_templates("No templates here")

    vars = TemplateResolver.extract_variables("Fix $issue on $date")
    assert vars == {"issue", "date"}


def test_template_resolution():
    """Test template variable substitution."""
    from pflow.runtime.template_resolver import TemplateResolver

    template = "Fix issue $issue_number in $repo"
    values = {"issue_number": "123", "repo": "pflow"}

    result = TemplateResolver.resolve_string(template, values)
    assert result == "Fix issue 123 in pflow"


def test_node_proxy_execution():
    """Test that proxy resolves templates transparently."""
    from pflow.runtime.template_proxy import TemplateResolvingNodeProxy

    # Mock node that records what params it sees
    class TestNode:
        def __init__(self):
            self.params = {}
            self.seen_params = None

        def _run(self, shared):
            self.seen_params = self.params.copy()
            return "success"

    # Create node with template params
    node = TestNode()
    node.params = {"prompt": "Fix: $issue_data"}

    # Wrap in proxy
    proxy = TemplateResolvingNodeProxy(
        node,
        "test_node",
        {"prompt": "Fix: $issue_data"}
    )

    # Execute with shared store containing the value
    shared = {"issue_data": "Bug in login system"}
    result = proxy._run(shared)

    # Node should have seen resolved value
    assert node.seen_params == {"prompt": "Fix: Bug in login system"}

    # Original params should be unchanged
    assert node.params == {"prompt": "Fix: $issue_data"}
```

### Integration Tests

```python
def test_end_to_end_workflow_with_templates():
    """Test complete workflow with template variables."""

    # Workflow IR with templates
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "get",
                "type": "github-get-issue",
                "params": {"issue": "$issue_number"}
            },
            {
                "id": "analyze",
                "type": "llm",
                "params": {"prompt": "Analyze: $issue_data"}
            }
        ],
        "edges": [
            {"from": "get", "to": "analyze"}
        ]
    }

    # Initial parameters
    initial_params = {"issue_number": "123"}

    # Compile with parameters
    flow = compile_ir_to_flow(ir, registry, initial_params)

    # Mock the github node to write to shared
    def mock_github_exec(self, shared, prep_res):
        # Verify we got the substituted value
        assert self.params["issue"] == "123"
        shared["issue_data"] = "Bug: System crashes on startup"
        return "success"

    # Patch the node execution
    with patch.object(GitHubGetIssueNode, 'exec', mock_github_exec):
        # Run the workflow
        shared = {}
        flow.run(shared)

        # Verify the LLM node got resolved template
        # (would need to mock/spy on LLM node to verify)
```

### Error Cases

```python
def test_missing_template_variable():
    """Test error when template variable is not available."""

    ir = {
        "nodes": [{
            "id": "n1",
            "type": "llm",
            "params": {"prompt": "Process $missing_var"}
        }]
    }

    flow = compile_ir_to_flow(ir, registry)
    shared = {}  # No 'missing_var' in shared!

    # Should handle gracefully - either error or leave unresolved
    # Exact behavior TBD based on requirements
```

## Examples and Use Cases

### Example 1: GitHub Issue Workflow

```json
{
  "nodes": [
    {
      "id": "get-issue",
      "type": "github-get-issue",
      "params": {
        "issue": "$issue_number",
        "repo": "$repo_name"
      }
    },
    {
      "id": "analyze",
      "type": "claude-code",
      "params": {
        "prompt": "Fix the following issue:\n\n$issue_data\n\nFollow the coding standards:\n$coding_standards"
      }
    },
    {
      "id": "commit",
      "type": "git-commit",
      "params": {
        "message": "Fix #$issue_number: $commit_summary"
      }
    }
  ]
}
```

**Execution:**
```bash
# First time
pflow "fix github issue 1234 in the pflow repo"
# Saves workflow with templates

# Later runs
pflow fix-issue --issue_number=1234 --repo_name=pflow
pflow fix-issue --issue_number=5678 --repo_name=my-app
```

### Example 2: Data Processing Pipeline

```json
{
  "nodes": [
    {
      "id": "read",
      "type": "read-file",
      "params": {"path": "$input_file"}
    },
    {
      "id": "process",
      "type": "data-transform",
      "params": {
        "format": "$output_format",
        "options": {
          "delimiter": "$delimiter",
          "headers": "$include_headers"
        }
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "params": {
        "prompt": "Analyze this $output_format data:\n\n$transformed_data\n\nFocus on: $analysis_focus"
      }
    }
  ]
}
```

### Example 3: Template Variable Resolution Flow

```
Initial State:
- CLI params: {"issue_number": "123", "repo_name": "pflow"}
- Shared store: {}

Node 1 (get-issue) executes:
- Sees params: {"issue": "123", "repo": "pflow"}  // Resolved!
- Writes: shared["issue_data"] = {title: "Bug in...", body: "..."}
- Writes: shared["issue_title"] = "Bug in template system"

Node 2 (analyze) executes:
- Template: "Fix: $issue_data"
- Sees params: {"prompt": "Fix: {title: 'Bug in...', body: '...'}"}  // Resolved!
- Writes: shared["commit_summary"] = "Fixed template variable resolution"

Node 3 (commit) executes:
- Template: "Fix #$issue_number: $commit_summary"
- Sees: "Fix #123: Fixed template variable resolution"  // Both resolved!
```

## Risks and Mitigations

### Risk 1: Performance Impact

**Risk**: Template resolution adds overhead to every node execution.

**Mitigation**:
- Only wrap nodes that actually have templates
- Cache detection results during compilation
- Simple string replacement is fast

### Risk 2: Circular Dependencies

**Risk**: Template variables might reference each other circularly.

**Mitigation**:
- Simple implementation doesn't support variable-in-variable
- Clear error messages for unresolved variables
- Future: dependency analysis

### Risk 3: Security - Code Injection

**Risk**: Template substitution might enable code injection.

**Mitigation**:
- Only simple string substitution, no eval()
- Parameters are strings, not executed
- Nodes responsible for their own input validation

### Risk 4: Debugging Complexity

**Risk**: Harder to debug when templates are involved.

**Mitigation**:
- Log template resolution when verbose mode enabled
- Clear error messages showing template → value mapping
- Test mode that shows resolved params

## Success Criteria

### Functional Requirements

1. **Initial Parameter Substitution**
   - [ ] CLI parameters replace $variables in node params
   - [ ] Workflow remains reusable with different parameters
   - [ ] Original workflow preserves templates

2. **Shared Store Resolution**
   - [ ] $variables resolve from shared store during execution
   - [ ] Nodes see resolved values, not templates
   - [ ] Resolution happens just-in-time

3. **Node Atomicity**
   - [ ] Nodes remain unaware of template system
   - [ ] No modifications to existing node implementations
   - [ ] No modifications to PocketFlow framework

4. **Error Handling**
   - [ ] Clear errors for missing template variables
   - [ ] Graceful handling of resolution failures
   - [ ] Helpful error messages

### Non-Functional Requirements

1. **Performance**
   - [ ] Minimal overhead for non-template nodes
   - [ ] Fast string substitution
   - [ ] No performance regression

2. **Maintainability**
   - [ ] Clear separation of concerns
   - [ ] Well-documented code
   - [ ] Comprehensive tests

3. **Compatibility**
   - [ ] Works with existing NodeAwareSharedStore
   - [ ] No breaking changes to IR schema
   - [ ] Backward compatible

### Validation

The implementation is successful when:

```bash
# This workflow can be saved once
pflow "fix github issue 1234"

# And run many times with different parameters
pflow fix-issue --issue_number=1234
pflow fix-issue --issue_number=5678
pflow fix-issue --issue_number=9999

# Each execution correctly substitutes the issue number
# AND resolves shared store references like $issue_data
```

## Implementation Order

1. **Phase 1**: Template detection and resolution utilities
2. **Phase 2**: Initial parameter substitution (compile-time)
3. **Phase 3**: Node proxy for runtime resolution
4. **Phase 4**: Compiler integration
5. **Phase 5**: CLI parameter support
6. **Phase 6**: Testing and validation
7. **Phase 7**: Documentation updates

## Conclusion

This template variable system enables pflow's core value proposition while maintaining architectural integrity. By using the proven proxy pattern, we add powerful functionality without compromising the atomicity of nodes or modifying the PocketFlow framework.

The implementation is straightforward, testable, and aligns with existing patterns in the codebase. With this system in place, workflows become truly reusable, and the "Plan Once, Run Forever" philosophy becomes reality.
