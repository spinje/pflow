# Automatic Proxy Mapping Architecture: Hidden Complexity, Natural Workflows

## Executive Summary

This document describes a breakthrough architectural approach for handling shared store collisions in pflow. Instead of requiring manual proxy mapping configuration (either from users or LLMs), the system automatically detects collisions and generates mappings transparently.

**Key Innovation**: The context builder shows the LLM a post-mapping view of the world, making collision handling completely invisible to both users and the planner.

**Result**: Natural workflow creation with zero configuration overhead.

## The Evolution of Understanding

### Stage 1: Manual Proxy Mappings (Original Design)
Users or LLMs had to explicitly configure mappings:
```json
{
  "mappings": {
    "api1": {"output_mappings": {"response": "api1_response"}},
    "api2": {"output_mappings": {"response": "api2_response"}}
  }
}
```
**Problem**: Complex, error-prone, requires understanding of internals.

### Stage 2: Template Variables with Paths (MVP Solution)
Added path support to template variables:
```
$issue_data.user.login
```
**Result**: Solved 80% of use cases, but collision problem remained.

### Stage 3: Automatic Generation (The Breakthrough)
System detects collisions and generates mappings automatically:
- No user configuration needed
- LLM never sees or generates mappings
- Context builder shows post-mapping view
- Everything just works

## Core Architecture

### The Collision Detection Algorithm

```python
def detect_collisions(nodes):
    """Detect which nodes write to the same keys."""
    outputs_by_key = defaultdict(list)

    for node in nodes:
        for output_key in node.outputs:
            outputs_by_key[output_key].append(node.id)

    # Find actual collisions
    collisions = {
        key: node_ids
        for key, node_ids in outputs_by_key.items()
        if len(node_ids) > 1
    }

    return collisions
```

### Smart Mapping Generation

```python
def generate_collision_mappings(nodes, collisions):
    """Generate mappings that preserve self-reading behavior."""
    mappings = {}

    for key, colliding_nodes in collisions.items():
        for node_id in colliding_nodes:
            node = get_node(node_id)

            # Critical: Check if node reads its own output
            if key in node.inputs:
                # Self-reading node - don't map this output
                continue

            # Safe to map - add prefixed version
            if node_id not in mappings:
                mappings[node_id] = {"output_mappings": {}}

            mappings[node_id]["output_mappings"][key] = f"{node_id}_{key}"

    return mappings
```

### Context Builder Transformation

```python
def build_planning_context(selected_nodes):
    """Build context showing POST-MAPPING view."""
    # Step 1: Detect collisions
    collisions = detect_collisions(selected_nodes)

    # Step 2: Generate mappings
    mappings = generate_collision_mappings(selected_nodes, collisions)

    # Step 3: Build context with mapped outputs
    context = []
    for node in selected_nodes:
        # Apply output mappings if they exist
        if node.id in mappings:
            displayed_outputs = apply_mappings(
                node.outputs,
                mappings[node.id]["output_mappings"]
            )
        else:
            displayed_outputs = node.outputs

        # Show the collision-free view
        context.append({
            "name": node.name,
            "id": node.id,
            "outputs": displayed_outputs  # Post-mapping names!
        })

    # Store mappings for compiler
    store_context_mappings(mappings)

    return format_context(context)
```

## The Complete Flow

### 1. User Intent
```
"Compare responses from GitHub and GitLab APIs"
```

### 2. Node Selection
Context builder identifies:
- 2x `api-call` nodes (collision potential)
- 1x `llm` node

### 3. Collision Detection
```python
# Detected collision:
{
    "response": ["api1", "api2"],
    "status": ["api1", "api2"]
}
```

### 4. Mapping Generation
```python
# Generated mappings:
{
    "api1": {"output_mappings": {"response": "api1_response", "status": "api1_status"}},
    "api2": {"output_mappings": {"response": "api2_response", "status": "api2_status"}}
}
```

### 5. Context Transformation
What the LLM sees:
```markdown
### api-call (api1)
**Outputs**: `api1_response`, `api1_status`

### api-call (api2)
**Outputs**: `api2_response`, `api2_status`

### llm
**Inputs**: `prompt`
**Outputs**: `analysis`
```

### 6. Natural LLM Generation
```json
{
  "nodes": [
    {"id": "api1", "type": "api-call", "params": {"url": "https://api.github.com/..."}},
    {"id": "api2", "type": "api-call", "params": {"url": "https://gitlab.com/api/..."}},
    {"id": "compare", "type": "llm", "params": {
      "prompt": "Compare $api1_response with $api2_response"
    }}
  ]
}
```

### 7. Compiler Integration
```python
def compile_workflow(ir, context_mappings):
    """Add hidden mappings to IR."""
    if context_mappings:
        ir["mappings"] = context_mappings
    return compile_ir_to_flow(ir)
```

### 8. Transparent Execution
The workflow executes with collision handling completely hidden from users.

## Implementation Details

### Collision Detection Rules

1. **Same Type, Same Output**: Most common collision
   ```python
   # Two api-call nodes both output "response"
   ```

2. **Different Types, Same Output**: Less common but handled
   ```python
   # file-read outputs "content"
   # api-call outputs "content"
   ```

3. **Self-Reading Preservation**:
   ```python
   # Node writes to "cache" and reads from "cache"
   # No mapping applied - preserves behavior
   ```

### Edge Case Handling

#### Case 1: Partial Self-Reading
Node writes multiple outputs but only reads some:
```python
# Node writes: ["data", "metadata", "status"]
# Node reads: ["metadata"]
# Result: Map "data" and "status", preserve "metadata"
```

#### Case 2: Chain Dependencies
A writes X, B reads X and writes X, C reads X:
```python
# Only A's output can be safely mapped
# B must read and write the same key
```

#### Case 3: Dynamic Node IDs
When nodes are dynamically generated:
```python
# Ensure unique IDs: api-1, api-2, api-3...
# Mappings become: api-1_response, api-2_response...
```

## Integration Architecture

### With Template Variables
Template variables naturally work with mapped names:
```json
// Before collision handling:
{"prompt": "Analyze $response"}  // Which response?

// After automatic mapping:
{"prompt": "Analyze $api1_response"}  // Clear!
```

### With Context Builder
Context builder becomes the central intelligence:
1. Analyzes node configurations
2. Detects potential collisions
3. Generates appropriate mappings
4. Presents collision-free view

### With Compiler
Compiler applies stored mappings:
```python
class EnhancedCompiler:
    def compile(self, ir):
        # Retrieve mappings generated during context building
        mappings = get_stored_context_mappings()

        if mappings:
            ir["mappings"] = mappings

        return create_flow(ir)
```

### With Planner
Planner remains blissfully unaware:
- Sees collision-free node descriptions
- Generates natural template variable references
- No special logic needed

## Real-World Examples

### Example 1: Multiple API Aggregation
```python
# User wants: "Aggregate weather from 3 sources"

# Context shows:
weather-api (source1): outputs `source1_temperature`, `source1_humidity`
weather-api (source2): outputs `source2_temperature`, `source2_humidity`
weather-api (source3): outputs `source3_temperature`, `source3_humidity`

# LLM naturally generates:
"Average temps: ($source1_temperature + $source2_temperature + $source3_temperature) / 3"
```

### Example 2: Pipeline with Caching
```python
# Process that caches intermediate results

# Nodes:
1. fetch-data: outputs `data`, `cache_key`
2. process-cache: inputs `cache_key`, outputs `cache_key`, `cached_data`
3. analyze: inputs `cached_data`

# Automatic handling:
- fetch-data.data → fetch-data_data (mapped)
- process-cache.cache_key → cache_key (preserved for self-read)
```

### Example 3: Workflow Composition
```python
# Combining existing workflows

# Workflow A outputs: result, summary, metrics
# Workflow B outputs: result, analysis, metrics

# Automatic mapping:
A.result → A_result
A.metrics → A_metrics
B.result → B_result
B.metrics → B_metrics
# summary and analysis remain unmapped (no collision)
```

## Benefits

### For Users
- Write natural workflows without collision concerns
- No need to understand proxy mappings
- Workflows "just work"

### For LLM/Planner
- Sees clean, collision-free world
- No mapping generation logic needed
- Simpler prompts and outputs

### For System Design
- Separation of concerns
- Hidden complexity
- Maintainable architecture
- Future-proof design

## Implementation Strategy

### Phase 1: Collision Detection (Week 1)
- [ ] Implement collision detection algorithm
- [ ] Handle node input/output analysis
- [ ] Test with various node configurations

### Phase 2: Mapping Generation (Week 2)
- [ ] Implement smart mapping rules
- [ ] Handle self-reading preservation
- [ ] Generate minimal necessary mappings

### Phase 3: Context Integration (Week 3)
- [ ] Modify context builder
- [ ] Store mappings for compiler
- [ ] Present post-mapping view

### Phase 4: Compiler Integration (Week 4)
- [ ] Retrieve stored mappings
- [ ] Apply to IR transparently
- [ ] Ensure execution correctness

## Key Design Principles

1. **Invisible Complexity**: Users and LLMs never see mappings
2. **Natural Workflows**: Write what you mean
3. **Smart Defaults**: System figures out the right thing
4. **Preserve Semantics**: Self-reading nodes work correctly
5. **Minimal Mappings**: Only map what collides

## Configuration and Overrides

While automatic handling covers 99% of cases, power users can still:

```json
// Explicit mapping (overrides automatic)
{
  "mappings": {
    "api1": {"output_mappings": {"response": "github_api_response"}}
  }
}
```

The system respects explicit mappings and only generates automatic ones for unmapped collisions.

## Testing Strategy

### Unit Tests
- Collision detection accuracy
- Mapping generation rules
- Self-reading preservation
- Edge case handling

### Integration Tests
- Context builder transformation
- Compiler mapping application
- End-to-end workflow execution
- Complex collision scenarios

### Validation Tests
- Ensure mapped outputs are accessible
- Verify self-reading nodes work
- Check template variable resolution

## Future Enhancements

1. **Collision Warnings**: Optional warnings about auto-handled collisions
2. **Custom Prefixes**: Configure prefix pattern (e.g., `{node}_{key}` vs `{key}_from_{node}`)
3. **Collision Strategies**: Different handling for different node types
4. **Performance Optimization**: Cache collision analysis for large workflows

## Conclusion

Automatic proxy mapping generation represents a significant simplification in pflow's architecture. By detecting collisions and generating mappings transparently, we enable natural workflow creation while maintaining system correctness.

The key insight—showing the LLM a post-mapping view—eliminates an entire class of complexity from workflow generation. This is architectural design at its best: solving complex problems in ways that make them disappear.

Users write what they mean, the system makes it work, and nobody needs to understand proxy mappings. Perfect.
