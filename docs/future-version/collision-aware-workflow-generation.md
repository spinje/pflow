# Collision-Aware Workflow Generation

**Status**: Future Enhancement (Post-MVP)
**Priority**: Medium
**Prerequisite**: Evidence that LLM struggles with proxy mappings in practice

## Overview

This document describes an advanced approach to workflow generation that separates collision detection and proxy mapping generation from the main workflow creation process. This enhancement would improve the accuracy and reliability of the Natural Language Planner when dealing with workflows that have shared store key collisions.

## Problem Statement

### Current MVP Approach

The MVP planner generates workflows in a single step, handling both:
1. Node selection and connection
2. Proxy mapping generation for collision avoidance

This combined approach works but may lead to:
- LLM confusion when juggling multiple concepts
- Missed collision cases
- Incorrect proxy mapping syntax
- Harder debugging when generation fails

### Evidence Needed

Before implementing this enhancement, we need evidence that the current approach is insufficient:
- High rate of collision-related generation failures
- User complaints about proxy mapping errors
- Complex workflows consistently failing validation

## Proposed Solution

### Two-Step Generation Process

Split workflow generation into two focused steps:

#### Step 1: Collision Analysis
```python
# New context builder function
def build_collision_analysis_context(selected_node_ids: list[str]) -> dict:
    """
    Returns structured data about potential collisions.

    Returns:
        {
            "nodes": [
                {
                    "id": "api1",
                    "type": "api-call",
                    "outputs": ["response", "status_code"]
                },
                {
                    "id": "api2",
                    "type": "api-call",
                    "outputs": ["response", "status_code"]
                }
            ],
            "collisions": {
                "response": ["api1", "api2"],
                "status_code": ["api1", "api2"]
            }
        }
    """
```

#### Step 2: Workflow Generation with Collision Context
```python
# Enhanced planner prompt
if collision_analysis["collisions"]:
    prompt += f"""
    IMPORTANT: The following shared store keys have collisions:
    {format_collisions(collision_analysis["collisions"])}

    You MUST use output_mappings to avoid these collisions.
    For example, rename 'response' from different nodes to 'api1_response', 'api2_response'.
    """
```

### Implementation Architecture

```
User Input
    ↓
Node Selection (existing)
    ↓
Collision Analysis (new)
    ├─→ No collisions → Standard generation
    └─→ Has collisions → Enhanced generation with mappings
                           ↓
                        Validation
```

## Detailed Design

### 1. Context Builder Enhancement

Add new function to `src/pflow/planning/context_builder.py`:

```python
def build_collision_analysis_context(
    selected_node_ids: list[str],
    registry_metadata: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """
    Analyze selected nodes for potential shared store collisions.

    Args:
        selected_node_ids: List of node IDs to analyze
        registry_metadata: Full registry metadata

    Returns:
        Dictionary with:
        - nodes: List of node info with outputs
        - collisions: Dict mapping keys to list of node IDs that write to them
        - suggestions: Optional renaming suggestions
    """
    node_outputs = defaultdict(list)
    nodes_info = []

    for node_id in selected_node_ids:
        if node_id in registry_metadata:
            metadata = registry_metadata[node_id]
            outputs = metadata.get("outputs", [])

            nodes_info.append({
                "id": node_id,
                "type": node_id,  # In registry, ID is the type
                "outputs": [o["key"] for o in outputs]
            })

            for output in outputs:
                node_outputs[output["key"]].append(node_id)

    # Find collisions
    collisions = {
        key: nodes
        for key, nodes in node_outputs.items()
        if len(nodes) > 1
    }

    # Generate suggestions
    suggestions = {}
    if collisions:
        for key, nodes in collisions.items():
            suggestions[key] = {
                node: f"{node}_{key}"
                for node in nodes
            }

    return {
        "nodes": nodes_info,
        "collisions": collisions,
        "suggestions": suggestions
    }
```

### 2. Planner Node Enhancement

Modify `WorkflowGeneratorNode` to use collision analysis:

```python
class WorkflowGeneratorNode(Node):
    def exec(self, shared):
        # Get collision analysis if available
        collision_analysis = shared.get("collision_analysis", {})

        # Build prompt with collision awareness
        prompt = self._build_base_prompt(shared)

        if collision_analysis.get("collisions"):
            prompt += self._build_collision_section(collision_analysis)

        # Generate workflow
        response = self.model.prompt(prompt, schema=FlowIR)
        # ...
```

### 3. Validation Enhancement

Add collision validation that understands proxy mappings:

```python
def validate_no_output_collisions(
    workflow_ir: dict,
    registry_metadata: dict
) -> list[str]:
    """
    Validate that no two nodes write to the same shared store key
    after accounting for proxy mappings.
    """
    effective_outputs = defaultdict(list)
    mappings = workflow_ir.get("mappings", {})

    for node in workflow_ir["nodes"]:
        node_id = node["id"]
        node_type = node["type"]

        # Get base outputs from metadata
        base_outputs = get_node_outputs(node_type, registry_metadata)

        # Apply output mappings if present
        output_mappings = mappings.get(node_id, {}).get("output_mappings", {})

        for output_key in base_outputs:
            # Use mapped key if available, otherwise original
            effective_key = output_mappings.get(output_key, output_key)
            effective_outputs[effective_key].append(node_id)

    # Check for collisions
    errors = []
    for key, nodes in effective_outputs.items():
        if len(nodes) > 1:
            errors.append(
                f"Collision on '{key}': written by nodes {', '.join(nodes)}. "
                f"Use output_mappings to rename outputs."
            )

    return errors
```

## Benefits

### 1. Improved Accuracy
- LLM focuses on one problem at a time
- Clearer prompts for collision scenarios
- Reduced cognitive load during generation

### 2. Better Error Messages
- Can pinpoint exactly which keys collide
- Can suggest specific renaming strategies
- Validation knows about collision context

### 3. Performance Optimization
- Skip collision handling for simple workflows
- Only add complexity when needed
- Faster generation for common cases

### 4. Enhanced Debugging
- Clear separation of concerns
- Can log collision analysis separately
- Easier to identify where generation fails

## Tradeoffs

### Complexity
- Additional context builder function
- More complex planner logic
- Extra validation steps

### Performance
- Additional analysis step
- More LLM tokens for collision context
- Slightly slower for collision cases

### Maintenance
- More code to maintain
- Additional test cases needed
- Documentation complexity

## Migration Path

1. **Gather Data**: Log collision-related failures in production
2. **Analyze Patterns**: Identify common collision scenarios
3. **Prototype**: Test enhancement with problematic workflows
4. **Gradual Rollout**: Enable for specific workflow types first
5. **Full Implementation**: Deploy for all workflows if beneficial

## Alternatives Considered

### 1. Adding Reads/Writes to IR Schema
- Pros: Complete static analysis possible
- Cons: Major schema change, duplicated information

### 2. Automatic Collision Resolution
- Pros: No LLM involvement needed
- Cons: Less control, surprising renaming

### 3. Post-Generation Fixing
- Pros: Simpler implementation
- Cons: Multiple generation rounds, slower

## Success Criteria

This enhancement should be implemented when:
- >10% of workflow generations fail due to collisions
- User feedback indicates proxy mapping confusion
- Complex multi-node workflows become common

Success metrics:
- Reduce collision-related failures by >80%
- Improve first-attempt generation success by >20%
- Decrease user-reported proxy mapping issues

## Conclusion

This collision-aware generation approach represents a natural evolution of the planner as usage patterns emerge. By separating concerns and providing focused context for each problem, we can significantly improve the reliability of workflow generation while maintaining the simplicity of the current MVP approach for basic workflows.
