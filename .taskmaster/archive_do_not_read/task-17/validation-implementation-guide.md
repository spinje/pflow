# Validation Implementation Guide for Task 17

## Overview

This guide provides concrete implementation recommendations for the validation pipeline in the Natural Language Planner. These are **recommendations** based on analysis, not requirements.

## Core Principle: Progressive Validation

Validate progressively from cheap to expensive checks, failing fast when issues are found.

## Three Validation Levels for MVP

### Level 1: Syntactic Validation (Via Pydantic)

**What it does**: Ensures structurally valid JSON with correct types

**Implementation**:
```python
# Use Pydantic models with Simon Willison's llm library
response = model.prompt(
    prompt=planning_prompt,
    schema=FlowIR  # Pydantic model
)
flow_dict = json.loads(response.text())
```

**What it catches**:
- Malformed JSON
- Missing required fields
- Type mismatches
- Invalid field names

### Level 2: Static Analysis

**What it does**: Verifies nodes exist and basic parameter validity

**Implementation**:
```python
def validate_static(ir, registry_metadata):
    errors = []

    # Check all nodes exist
    for node in ir['nodes']:
        if node['type'] not in registry_metadata:
            errors.append(f"Unknown node type: {node['type']}")

    # Check for orphaned nodes
    node_ids = {n['id'] for n in ir['nodes']}
    for edge in ir.get('edges', []):
        if edge['from'] not in node_ids:
            errors.append(f"Edge references unknown node: {edge['from']}")
        if edge['to'] not in node_ids:
            errors.append(f"Edge references unknown node: {edge['to']}")

    return errors
```

**What it catches**:
- Unknown node types
- Invalid edge references
- Orphaned nodes
- Basic structural issues

### Level 3: Data Flow Analysis

**What it does**: Tracks data availability through the workflow

**Important Clarification**: This is NOT mock execution. It's static analysis that tracks which keys are available at each step.

**Implementation**:
```python
def analyze_data_flow(ir, registry_metadata):
    """
    Analyze if data flows correctly through the workflow.
    This is purely static - no actual execution occurs.
    """
    available_keys = set()
    errors = []

    # Add any initial data (from CLI flags, stdin, etc.)
    # This would be determined from the workflow context

    # Process nodes in topological order
    ordered_nodes = get_execution_order(ir['nodes'], ir.get('edges', []))

    for node in ordered_nodes:
        node_type = node['type']
        node_meta = registry_metadata.get(node_type, {})

        # Check inputs are available
        required_inputs = node_meta.get('inputs', [])

        # Handle proxy mappings if present
        if node['id'] in ir.get('mappings', {}):
            mappings = ir['mappings'][node['id']]
            input_mappings = mappings.get('input_mappings', {})

            # Check mapped keys exist
            for expected_key, source_key in input_mappings.items():
                if source_key not in available_keys:
                    errors.append(
                        f"Node '{node['id']}' expects '{source_key}' "
                        f"(mapped to '{expected_key}') but it's not available"
                    )
        else:
            # Direct access - check natural keys
            for input_key in required_inputs:
                if input_key not in available_keys:
                    errors.append(
                        f"Node '{node['id']}' expects '{input_key}' "
                        f"but it's not available"
                    )

        # Add outputs to available keys
        node_outputs = node_meta.get('outputs', [])
        available_keys.update(node_outputs)

    # Check template variables can resolve
    template_vars = extract_template_variables(ir)
    for var in template_vars:
        if var not in available_keys:
            errors.append(f"Template variable ${var} cannot be resolved")

    return errors
```

**What it catches**:
- Missing data dependencies
- Incorrect proxy mappings
- Unresolvable template variables
- Data flow breaks

## Helper Functions

### Topological Sort for Execution Order

```python
def get_execution_order(nodes, edges):
    """
    Determine node execution order from edges.
    Returns nodes in order they would execute.
    """
    # Build adjacency list
    graph = {node['id']: [] for node in nodes}
    in_degree = {node['id']: 0 for node in nodes}

    for edge in edges:
        graph[edge['from']].append(edge['to'])
        in_degree[edge['to']] += 1

    # Find nodes with no dependencies
    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    ordered = []

    while queue:
        node_id = queue.pop(0)
        ordered.append(node_id)

        # Process dependent nodes
        for next_id in graph[node_id]:
            in_degree[next_id] -= 1
            if in_degree[next_id] == 0:
                queue.append(next_id)

    if len(ordered) != len(nodes):
        raise ValueError("Circular dependency detected")

    # Return nodes in execution order
    node_map = {n['id']: n for n in nodes}
    return [node_map[node_id] for node_id in ordered]
```

### Template Variable Extraction

```python
def extract_template_variables(ir):
    """Extract all $variable references from the IR"""
    variables = set()

    def extract_from_value(value):
        if isinstance(value, str):
            # Find $variable patterns
            import re
            matches = re.findall(r'\$(\w+)', value)
            variables.update(matches)
        elif isinstance(value, dict):
            for v in value.values():
                extract_from_value(v)
        elif isinstance(value, list):
            for item in value:
                extract_from_value(item)

    # Check all node parameters
    for node in ir.get('nodes', []):
        extract_from_value(node.get('params', {}))

    return variables
```

## Error Recovery Recommendations

### Simple Retry Strategy

```python
def validate_with_retry(ir, registry_metadata, max_retries=3):
    """
    Validate and provide error feedback for retry.
    Returns (is_valid, errors, retry_hint)
    """
    # Level 1: Syntactic (already done by Pydantic)

    # Level 2: Static
    static_errors = validate_static(ir, registry_metadata)
    if static_errors:
        hint = generate_hint_for_static_errors(static_errors)
        return False, static_errors, hint

    # Level 3: Data flow
    flow_errors = analyze_data_flow(ir, registry_metadata)
    if flow_errors:
        hint = generate_hint_for_flow_errors(flow_errors)
        return False, flow_errors, hint

    return True, [], None

def generate_hint_for_static_errors(errors):
    """Generate LLM-friendly hints for static errors"""
    if any("Unknown node type" in e for e in errors):
        return "Use only nodes from the available node list provided"
    return "Check node types and edge references"

def generate_hint_for_flow_errors(errors):
    """Generate LLM-friendly hints for data flow errors"""
    if any("not available" in e for e in errors):
        return "Ensure nodes that produce data run before nodes that consume it"
    if any("Template variable" in e for e in errors):
        return "Make sure all $variables reference data produced by earlier nodes"
    return "Check the data flow between nodes"
```

## MVP Simplifications

1. **No Complex Mock Behaviors**: Just track inputs/outputs from metadata
2. **String Values Only**: Don't worry about type validation beyond strings
3. **No Performance Optimization**: Simple linear validation is fine
4. **Basic Error Messages**: Clear but not overly detailed
5. **Limited Retry Logic**: Simple hints, not complex recovery strategies

## What We're NOT Doing

1. **NOT simulating actual node execution**
2. **NOT maintaining complex mock state**
3. **NOT validating semantic correctness** (e.g., is this a good prompt?)
4. **NOT handling async or complex node behaviors**
5. **NOT doing extensive type checking**

## Integration with Planner

```python
class PlannerValidationNode(Node):
    """Node that validates generated workflows"""

    def exec(self, prep_res):
        ir = shared['generated_ir']
        registry_metadata = shared['registry_metadata']

        # Validate
        is_valid, errors, hint = validate_with_retry(ir, registry_metadata)

        if is_valid:
            return {
                'status': 'valid',
                'ir': ir
            }
        else:
            return {
                'status': 'invalid',
                'errors': errors,
                'retry_hint': hint
            }
```

## Key Takeaways

1. **Validation is about data flow**, not execution simulation
2. **Static analysis can catch 90%** of real issues
3. **Progressive validation** saves time and resources
4. **Simple is better** for MVP - enhance based on real usage
5. **Clear error messages** are more valuable than perfect validation

## Testing the Validator

Create test cases for common scenarios:

```python
def test_missing_input():
    """Node expects input that's never created"""
    ir = {
        'nodes': [
            {'id': 'n1', 'type': 'llm', 'params': {}}
        ]
    }
    # Should fail: llm expects 'prompt' but it's not available

def test_successful_flow():
    """Valid flow with proper data connections"""
    ir = {
        'nodes': [
            {'id': 'n1', 'type': 'read-file', 'params': {'path': 'test.txt'}},
            {'id': 'n2', 'type': 'llm', 'params': {'prompt': 'Summarize: $content'}}
        ],
        'edges': [{'from': 'n1', 'to': 'n2'}]
    }
    # Should pass: read-file outputs 'content', llm uses it

def test_proxy_mapping():
    """Flow using proxy mappings"""
    ir = {
        'nodes': [
            {'id': 'n1', 'type': 'youtube-transcript', 'params': {}},
            {'id': 'n2', 'type': 'llm', 'params': {}}
        ],
        'edges': [{'from': 'n1', 'to': 'n2'}],
        'mappings': {
            'n2': {
                'input_mappings': {'prompt': 'transcript'}
            }
        }
    }
    # Should pass: mapping connects transcript → prompt
```

## Conclusion

This validation approach is:
- **Simple**: Uses familiar static analysis concepts
- **Effective**: Catches real issues users would face
- **Maintainable**: No complex mock framework needed
- **Extensible**: Can add more sophisticated checks later

Remember: The goal is to catch obvious errors and help the LLM generate better workflows, not to guarantee perfection. Runtime will catch edge cases we miss.

*Note that this document only consists of recommendations not requirements. If anything is unclear, ambiguous or you think you can do something better, please use your own judgement and implement it in a way that is best for the project or ask the user for clarifications.*
