# Planner Integration Patterns

## Overview

The Natural Language Planner is the central component that connects all parts of pflow. This document describes how it integrates with each subsystem.

## Integration Architecture

```
CLI → Planner → Registry
         ↓
    Validation
         ↓
    Approval → Storage
         ↓
    Execution
```

## CLI Integration

### Input Flow
```python
# CLI (main.py) sends raw input to planner
raw_input = "analyze customer churn from stripe"
planner_result = planner.compile_request(raw_input, context)
```

### The Planner Receives:
1. **Raw input string** - Exactly what user typed
2. **Input source** - Whether from args, stdin, or file
3. **CLI context** - Any flags or options

### The Planner Returns:
```python
{
    "workflow_ir": {...},        # Generated workflow
    "parameters": {...},         # Extracted parameters
    "confidence": 0.95,          # Confidence score
    "alternatives": [...],       # Other possible interpretations
    "requires_approval": True    # Whether to show approval dialog
}
```

## Registry Integration

### Building Context
```python
def build_planning_context(registry: Registry) -> str:
    """Build context for LLM from registry metadata."""
    context_lines = ["Available nodes:\n"]

    for node_name, metadata in registry.list_nodes().items():
        # Extract from metadata (NOT importing the node)
        context_lines.append(f"- {node_name}: {metadata['description']}")
        context_lines.append(f"  Inputs: {metadata.get('inputs', [])}")
        context_lines.append(f"  Outputs: {metadata.get('outputs', [])}")
        context_lines.append("")

    return "\n".join(context_lines)
```

### Node Validation
```python
def validate_node_exists(node_type: str, registry: Registry) -> bool:
    """Ensure planner only uses nodes that exist."""
    return node_type in registry.list_nodes()
```

## Shared Store Understanding

### Natural Key Conventions
The planner understands shared store patterns:

```python
# Planner knows these conventions:
COMMON_KEYS = {
    "file_path": "Path to file being processed",
    "content": "Text content from file or API",
    "url": "Web URL to fetch",
    "repo": "GitHub repository name",
    "issue_number": "GitHub issue number",
    "prompt": "LLM prompt text",
    "response": "LLM response text"
}
```

### Generating Compatible Workflows
```python
def generate_node_connections(nodes: List[str]) -> List[Edge]:
    """Generate edges ensuring data flow compatibility."""
    edges = []

    for i in range(len(nodes) - 1):
        current = nodes[i]
        next_node = nodes[i + 1]

        # Check if outputs of current match inputs of next
        if compatible(current.outputs, next_node.inputs):
            edges.append({
                "from": current.id,
                "to": next_node.id,
                "action": "default"
            })

    return edges
```

## Approval System Integration

### Approval Flow
```python
def get_user_approval(workflow: Dict, original_request: str) -> Dict:
    """Present workflow for user approval."""
    print(f"\nRequest: {original_request}")
    print(f"Generated workflow:\n")

    # Show human-readable format
    for node in workflow['nodes']:
        print(f"  {node['type']} --{format_params(node['params'])}")

    print("\nApprove? [Y/n/m(odify)]: ", end="")
    response = input().lower()

    if response == 'm':
        return modify_workflow(workflow)
    elif response in ['y', '']:
        return workflow
    else:
        return None
```

### Modification Support
```python
def modify_workflow(workflow: Dict) -> Dict:
    """Allow user to modify generated workflow."""
    # Show numbered list of nodes
    # Allow user to:
    # - Add/remove nodes
    # - Modify parameters
    # - Change connections
    return modified_workflow
```

## Storage Integration

### Saving Workflows
```python
def save_workflow(workflow: Dict, name: str, metadata: Dict):
    """Save approved workflow with metadata."""
    storage_doc = {
        "name": name,
        "workflow": workflow,
        "description": metadata.get('description'),
        "created": datetime.now().isoformat(),
        "parameters": extract_template_vars(workflow),
        "examples": [metadata.get('original_request')],
        "tags": extract_tags(workflow),
        "usage_count": 0
    }

    path = Path.home() / ".pflow/workflows" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(storage_doc, indent=2))
```

### Discovery Metadata
```python
def extract_discovery_metadata(workflow: Dict, request: str) -> Dict:
    """Extract metadata for future discovery."""
    return {
        "description": generate_description(workflow),
        "tags": extract_concepts(request),
        "inputs": get_workflow_inputs(workflow),
        "outputs": get_workflow_outputs(workflow),
        "examples": [request]  # Add more over time
    }
```

## Execution Integration

### Parameter Resolution
```python
def prepare_for_execution(workflow: Dict, runtime_params: Dict) -> Dict:
    """Prepare workflow for execution with runtime parameters."""
    # Resolve template variables
    resolved_workflow = copy.deepcopy(workflow)

    for node in resolved_workflow['nodes']:
        for param, value in node['params'].items():
            if isinstance(value, str) and value.startswith('$'):
                var_name = value[1:]
                if var_name not in runtime_params:
                    raise ValueError(f"Missing parameter: {var_name}")
                node['params'][param] = runtime_params[var_name]

    return resolved_workflow
```

## Error Handling Integration

### Graceful Failures
```python
def handle_planning_error(error: Exception, request: str) -> Dict:
    """Handle planning failures gracefully."""
    if isinstance(error, AmbiguousRequestError):
        return {
            "error": "ambiguous",
            "message": "Your request could mean multiple things:",
            "suggestions": error.suggestions
        }
    elif isinstance(error, UnknownNodeError):
        return {
            "error": "unknown_node",
            "message": f"I don't know how to: {error.action}",
            "available_nodes": list_similar_nodes(error.action)
        }
    else:
        # Fallback
        return {
            "error": "planning_failed",
            "message": "Could not understand request",
            "request": request
        }
```

## Performance Considerations

### Caching
```python
class PlannerCache:
    """Cache planning results for common requests."""

    def get(self, request: str) -> Optional[Dict]:
        # Normalize request (lowercase, strip whitespace)
        key = normalize(request)
        return self._cache.get(key)

    def set(self, request: str, result: Dict):
        key = normalize(request)
        self._cache[key] = result
```

### Async Planning (Future)
```python
async def plan_async(request: str) -> Dict:
    """Plan workflow asynchronously for better UX."""
    # Run LLM call in background
    # Show progress to user
    # Return result when ready
```

## Testing Integration Points

### Mock Registry
```python
def create_mock_registry():
    """Create registry with test nodes for planner testing."""
    return {
        "read-file": {
            "description": "Read file from disk",
            "inputs": ["file_path"],
            "outputs": ["content"]
        },
        "llm": {
            "description": "Process text with LLM",
            "inputs": ["prompt"],
            "outputs": ["response"]
        }
    }
```

### Integration Tests
```python
def test_planner_full_flow():
    """Test planner with all integrations."""
    # Setup
    registry = create_mock_registry()
    planner = Planner(registry)

    # Test planning
    result = planner.compile_request("read data.csv and summarize it")

    # Verify workflow
    assert len(result['workflow_ir']['nodes']) == 2
    assert result['workflow_ir']['nodes'][0]['type'] == 'read-file'
    assert result['workflow_ir']['nodes'][1]['type'] == 'llm'

    # Test parameter extraction
    assert result['parameters']['file_path'] == 'data.csv'
```

## Key Integration Principles

1. **Loose Coupling**: Planner doesn't import nodes directly
2. **Clear Contracts**: Well-defined interfaces between components
3. **Fail Gracefully**: Always provide useful error messages
4. **Preserve Context**: Pass along original request for debugging
5. **Enable Testing**: All integrations should be mockable

## Remember

The planner is the brain of pflow. It must integrate smoothly with all components while remaining testable and maintainable. When in doubt, favor explicit interfaces over implicit assumptions.
