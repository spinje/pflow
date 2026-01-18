> **HISTORICAL DOCUMENT**: Obsolete after Task 95 (llm library integration, 2025-12-19).
>
> This document describes Anthropic-specific thinking token optimization that was never
> implemented. The `llm` library now provides a provider-agnostic interface, making
> Anthropic-specific features like thinking tokens inaccessible through pflow.
>
> **Status**: Never implemented, now incompatible with current architecture.

---

# Thinking Tokens Optimization for Complex Workflow Generation

## Executive Summary

This document proposes an adaptive thinking token allocation system for the pflow planner that dynamically adjusts Claude's thinking budget based on workflow complexity predictions. By analyzing requirements and selected components, we can optimize both generation quality and token costs.

## Problem Statement

Currently, the PlanningNode and WorkflowGeneratorNode generate complex workflows without using Claude's thinking tokens feature. This leads to:
- Suboptimal reasoning for complex multi-node workflows
- Potential data flow errors in intricate pipelines
- Missed edge cases in conditional logic
- No differentiation between simple and complex generation tasks

## Proposed Solution: ComplexityEstimatorNode

### Architecture Position

Insert a new `ComplexityEstimatorNode` **after ComponentBrowsingNode** and **before PlanningNode**:

```
Current Flow:
Discovery → Requirements → ComponentBrowsing → Planning → Generation

Proposed Flow:
Discovery → Requirements → ComponentBrowsing → ComplexityEstimator → Planning → Generation
```

### Why After ComponentBrowsing?

1. **Maximum Information**: We have both requirements analysis AND selected components
2. **Accurate Prediction**: Actual node count vs. estimated node count
3. **Component Types**: Can analyze if LLM nodes, API calls, or complex transforms are involved
4. **Workflow Combinations**: Know if multiple workflows are being orchestrated

## Complexity Scoring Algorithm

### Multi-Factor Scoring System

The complexity score is **uncapped** and calculated from multiple factors:

```python
class ComplexityEstimatorNode(Node):
    """Estimates workflow complexity and allocates thinking tokens dynamically."""

    def calculate_complexity_score(self, prep_res: dict) -> float:
        """Calculate uncapped complexity score from multiple factors.

        Returns:
            Float score (typically 0-100, but uncapped for edge cases)
        """
        score = 0.0

        # 1. Node Count Score (0-30 points)
        score += self._score_node_count(prep_res)

        # 2. Operation Complexity (0-25 points)
        score += self._score_operation_complexity(prep_res)

        # 3. Data Flow Complexity (0-20 points)
        score += self._score_data_flow_complexity(prep_res)

        # 4. Orchestration Complexity (0-15 points)
        score += self._score_orchestration_complexity(prep_res)

        # 5. Component Type Complexity (0-10 points)
        score += self._score_component_types(prep_res)

        # 6. Bonus multipliers for special cases (can exceed 100)
        score *= self._calculate_multipliers(prep_res)

        return score
```

### Detailed Scoring Components

#### 1. Node Count Score (0-30 points)

```python
def _score_node_count(self, prep_res: dict) -> float:
    """Score based on actual vs estimated node count."""
    browsed = prep_res.get("browsed_components", {})
    requirements = prep_res.get("requirements_result", {})

    actual_nodes = len(browsed.get("node_ids", []))
    estimated_nodes = requirements.get("estimated_nodes", actual_nodes)

    # Base score from actual count
    if actual_nodes <= 2:
        base_score = 2
    elif actual_nodes <= 4:
        base_score = 8
    elif actual_nodes <= 6:
        base_score = 15
    elif actual_nodes <= 10:
        base_score = 22
    else:
        # Logarithmic scaling for very large workflows
        base_score = 22 + math.log2(actual_nodes - 10) * 3

    # Adjustment if actual significantly exceeds estimate
    if actual_nodes > estimated_nodes * 1.5:
        base_score += 5  # Complexity underestimated

    return min(30, base_score)
```

#### 2. Operation Complexity (0-25 points)

```python
def _score_operation_complexity(self, prep_res: dict) -> float:
    """Score based on types of operations required."""
    requirements = prep_res.get("requirements_result", {})
    steps = requirements.get("steps", [])

    score = 0
    complexity_patterns = {
        # Pattern: (keywords, points)
        "conditional": (["if", "when", "based on", "depending", "otherwise"], 5),
        "iteration": (["for each", "iterate", "loop", "batch", "all items"], 5),
        "aggregation": (["combine", "merge", "aggregate", "collect", "gather"], 4),
        "transformation": (["transform", "convert", "parse", "extract", "process"], 3),
        "analysis": (["analyze", "evaluate", "assess", "determine", "calculate"], 4),
        "orchestration": (["coordinate", "orchestrate", "sequence", "pipeline"], 4),
    }

    for pattern_name, (keywords, points) in complexity_patterns.items():
        for step in steps:
            if any(keyword in step.lower() for keyword in keywords):
                score += points
                break  # Only count each pattern once

    return min(25, score)
```

#### 3. Data Flow Complexity (0-20 points)

```python
def _score_data_flow_complexity(self, prep_res: dict) -> float:
    """Score based on data flow patterns and dependencies."""
    browsed = prep_res.get("browsed_components", {})
    node_ids = browsed.get("node_ids", [])

    score = 0

    # Check for complex data patterns
    if self._has_fan_out_pattern(node_ids):
        score += 5  # One input → multiple outputs

    if self._has_fan_in_pattern(node_ids):
        score += 5  # Multiple inputs → one output

    if self._has_pipeline_depth(node_ids) > 3:
        score += 5  # Deep pipeline

    if self._has_parallel_branches(prep_res):
        score += 5  # Parallel execution paths

    return score
```

#### 4. Orchestration Complexity (0-15 points)

```python
def _score_orchestration_complexity(self, prep_res: dict) -> float:
    """Score based on workflow orchestration needs."""
    browsed = prep_res.get("browsed_components", {})

    score = 0

    # Multiple workflows being combined
    workflow_count = len(browsed.get("workflow_names", []))
    if workflow_count > 1:
        score += workflow_count * 3

    # Mixed node and workflow usage
    if browsed.get("node_ids") and browsed.get("workflow_names"):
        score += 3  # Hybrid orchestration

    return min(15, score)
```

#### 5. Component Type Complexity (0-10 points)

```python
def _score_component_types(self, prep_res: dict) -> float:
    """Score based on types of components used."""
    browsed = prep_res.get("browsed_components", {})
    node_ids = browsed.get("node_ids", [])

    score = 0

    # High-complexity components
    if "llm" in node_ids:
        score += 3  # LLM requires prompt engineering

    if any("api" in node or "http" in node for node in node_ids):
        score += 2  # External API integration

    if any("mcp" in node for node in node_ids):
        score += 3  # MCP server interaction

    if "shell" in node_ids:
        score += 2  # Shell command orchestration

    return score
```

#### 6. Complexity Multipliers

```python
def _calculate_multipliers(self, prep_res: dict) -> float:
    """Calculate multipliers for special complexity cases."""
    multiplier = 1.0
    requirements = prep_res.get("requirements_result", {})

    # Vague requirements increase complexity
    if not requirements.get("is_clear", True):
        multiplier *= 1.3

    # Error handling requirements
    if any("error" in step.lower() or "fallback" in step.lower()
           for step in requirements.get("steps", [])):
        multiplier *= 1.2

    # State management requirements
    if "state" in str(requirements).lower() or "memory" in str(requirements).lower():
        multiplier *= 1.2

    return multiplier
```

## Dynamic Thinking Token Allocation

### Thinking Budget Formula

Instead of fixed tiers, use a **continuous function**:

```python
def calculate_thinking_tokens(self, complexity_score: float) -> int:
    """Calculate thinking tokens based on complexity score.

    Uses a sigmoid-like curve for smooth scaling:
    - Score 0-10: 0-1000 tokens (simple workflows)
    - Score 10-30: 1000-5000 tokens (moderate complexity)
    - Score 30-60: 5000-15000 tokens (complex workflows)
    - Score 60-100: 15000-30000 tokens (very complex)
    - Score 100+: 30000-50000 tokens (extreme cases)

    Args:
        complexity_score: Uncapped complexity score

    Returns:
        Number of thinking tokens to allocate
    """
    if complexity_score <= 10:
        # Linear scaling for simple workflows
        return int(complexity_score * 100)

    elif complexity_score <= 30:
        # Accelerating curve for moderate complexity
        normalized = (complexity_score - 10) / 20
        return int(1000 + normalized * normalized * 4000)

    elif complexity_score <= 60:
        # Steep curve for complex workflows
        normalized = (complexity_score - 30) / 30
        return int(5000 + normalized * 10000)

    elif complexity_score <= 100:
        # Logarithmic scaling for very complex
        normalized = (complexity_score - 60) / 40
        return int(15000 + normalized * 15000)

    else:
        # Capped at 50k for extreme cases
        overflow = min(complexity_score - 100, 50)
        return int(30000 + overflow * 400)
```

### Thinking Token Usage by Node

```python
def allocate_thinking_by_node(self, total_thinking: int, complexity_score: float) -> dict:
    """Allocate thinking tokens across planning and generation nodes.

    Distribution strategy:
    - PlanningNode: 40% (architecture decisions)
    - WorkflowGeneratorNode: 50% (implementation details)
    - RequirementsAnalysisNode: 10% (clarification analysis)

    Args:
        total_thinking: Total thinking token budget
        complexity_score: Complexity score for adjustment

    Returns:
        Dict with token allocation per node
    """
    # Base distribution
    distribution = {
        "requirements_analysis": 0.1,
        "planning": 0.4,
        "workflow_generator": 0.5,
    }

    # Adjust based on complexity patterns
    if complexity_score > 50:
        # Very complex needs more planning
        distribution["planning"] = 0.45
        distribution["workflow_generator"] = 0.45

    return {
        node: int(total_thinking * ratio)
        for node, ratio in distribution.items()
    }
```

## Implementation in Shared Store

```python
class ComplexityEstimatorNode(Node):
    """Estimates complexity and allocates thinking tokens."""

    def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        """Store complexity analysis in shared store."""

        # Store for downstream nodes
        shared["complexity_analysis"] = {
            "score": exec_res["complexity_score"],
            "thinking_tokens": exec_res["thinking_tokens"],
            "allocation": exec_res["token_allocation"],
            "reasoning": exec_res["complexity_reasoning"],
            "factors": exec_res["scoring_factors"],
        }

        # Log for debugging
        logger.info(
            f"Complexity: {exec_res['complexity_score']:.1f}, "
            f"Thinking tokens: {exec_res['thinking_tokens']}",
            extra={
                "complexity_score": exec_res["complexity_score"],
                "thinking_tokens": exec_res["thinking_tokens"],
            }
        )

        return "default"  # Continue to PlanningNode
```

## Usage in Planning and Generation Nodes

### PlanningNode Enhancement

```python
class PlanningNode(Node):
    def exec(self, prep_res: dict) -> dict:
        # Get thinking allocation
        complexity = prep_res.get("complexity_analysis", {})
        thinking_tokens = complexity.get("allocation", {}).get("planning", 0)

        if thinking_tokens > 0:
            # Use thinking-enabled generation
            response = self.client.generate_with_thinking(
                prompt=prompt,
                max_thinking_tokens=thinking_tokens,
                cache_blocks=blocks,
            )

            # Log thinking usage
            logger.info(f"Planning used {response.thinking_tokens} thinking tokens")
        else:
            # Standard generation for simple cases
            response = self.client.generate_standard(prompt, cache_blocks=blocks)
```

## Benefits

1. **Cost Optimization**: Simple workflows (80% of cases) use minimal/no thinking tokens
2. **Quality Improvement**: Complex workflows get the reasoning power they need
3. **Adaptive Scaling**: Uncapped scoring handles edge cases gracefully
4. **Debugging Aid**: Complexity analysis helps understand generation decisions
5. **Performance Metrics**: Can track complexity vs. success rate

## Monitoring and Adjustment

### Metrics to Track

```python
# In shared store after workflow execution
shared["execution_metrics"] = {
    "complexity_score": 45.2,
    "thinking_tokens_allocated": 12000,
    "thinking_tokens_used": 10500,
    "generation_success": True,
    "validation_passes": 1,
    "execution_time_ms": 3400,
}
```

### Feedback Loop

Over time, we can adjust the scoring algorithm based on:
- Actual thinking token usage vs. allocation
- Validation failure rates by complexity score
- User satisfaction with generated workflows
- Execution success rates

## Example Complexity Calculations

### Example 1: Simple File Conversion
```
User: "Convert data.csv to JSON"
Requirements: 2 steps, 2 nodes estimated
Components: ["read-file", "write-file"]
Complexity Score: 4.5
Thinking Tokens: 450
```

### Example 2: GitHub Changelog Generation
```
User: "Generate changelog from last 30 closed issues with categories"
Requirements: 5 steps, 4 nodes estimated
Components: ["github-list-issues", "llm", "write-file"]
Complexity Score: 28.5
Thinking Tokens: 4800
```

### Example 3: Complex Data Pipeline
```
User: "For each CSV in folder, validate schema, transform to JSON,
       merge into master file, generate summary report with statistics"
Requirements: 8 steps, 10 nodes estimated
Components: ["shell", "read-file", "llm", "write-file", "merge-json"]
Patterns: iteration, aggregation, transformation, analysis
Complexity Score: 67.3
Thinking Tokens: 18200
```

## Future Enhancements

1. **Learning System**: Track actual complexity vs. predicted, adjust weights
2. **User Preferences**: Allow users to set quality/cost trade-offs
3. **Caching Insights**: Cache thinking patterns for similar workflows
4. **Explanation Mode**: Use thinking tokens to explain workflow decisions
5. **A/B Testing**: Compare workflows generated with/without thinking

## Implementation Priority

1. **Phase 1**: Implement ComplexityEstimatorNode with basic scoring
2. **Phase 2**: Add thinking token support to PlanningNode
3. **Phase 3**: Extend to WorkflowGeneratorNode
4. **Phase 4**: Add metrics tracking and feedback loop
5. **Phase 5**: Optimize scoring algorithm based on real usage

## Conclusion

This adaptive thinking token system provides intelligent resource allocation, ensuring simple workflows remain fast and cheap while complex workflows get the reasoning depth they need for correctness and robustness.
