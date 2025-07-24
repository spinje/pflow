# Workflow Discovery Implementation Guide

## Overview

Workflow discovery is what enables the "find" in "find or build". It's the mechanism that allows natural language queries to find existing workflows by semantic meaning, not just exact names.

## Core Requirements

1. **Semantic Understanding**: "analyze costs" finds "aws-cost-analyzer"
2. **Parameter Extraction**: Identify runtime parameters in the query
3. **Ranking**: Return best matches first
4. **Speed**: Near-instant for good UX (<100ms)

## Implementation Approach

### Phase 1: Simple Semantic Matching

Start with a straightforward approach:

```python
def find_similar_workflows(user_input: str, saved_workflows: Dict[str, Any]) -> List[Tuple[str, float]]:
    """
    Find workflows that semantically match the user input.
    Returns list of (workflow_name, similarity_score) tuples.
    """
    matches = []

    for name, workflow in saved_workflows.items():
        # Use workflow description and name for matching
        workflow_text = f"{name} {workflow.get('description', '')}"

        # Simple approach: Use LLM to score similarity
        score = calculate_similarity(user_input, workflow_text)

        if score > SIMILARITY_THRESHOLD:
            matches.append((name, score))

    # Sort by score descending
    return sorted(matches, key=lambda x: x[1], reverse=True)
```

### Phase 2: LLM-Based Similarity

Use the LLM to understand semantic similarity:

```python
def calculate_similarity(query: str, workflow_text: str) -> float:
    """Calculate semantic similarity using LLM."""
    prompt = f"""
    Rate the semantic similarity between these on a scale of 0-1:

    User Query: {query}
    Workflow: {workflow_text}

    Consider:
    - Do they describe the same task?
    - Are the key concepts similar?
    - Would the workflow satisfy the query?

    Return only a number between 0 and 1.
    """

    response = llm.complete(prompt)
    return float(response.strip())
```

### Phase 3: Embeddings (Future Optimization)

For better performance, pre-compute embeddings:

```python
# On workflow save:
workflow['embedding'] = compute_embedding(workflow['description'])

# On search:
query_embedding = compute_embedding(user_input)
similarities = cosine_similarity(query_embedding, all_workflow_embeddings)
```

## Parameter Handling

Extract parameters from the natural language query:

```python
def extract_parameters(user_input: str, workflow: Dict) -> Dict[str, Any]:
    """Extract runtime parameters from natural language."""
    # Example: "analyze churn for last month"
    # Should extract: {"time_period": "last month"}

    prompt = f"""
    Extract parameters from this query for the workflow:

    Query: {user_input}
    Workflow expects: {workflow.get('parameters', [])}

    Return as JSON mapping parameter names to values.
    """

    params_json = llm.complete(prompt)
    return json.loads(params_json)
```

## Storage Structure

Workflows should be stored with discovery metadata:

```json
{
  "analyze-churn": {
    "ir": { /* workflow IR */ },
    "description": "Analyze customer churn from Stripe and HubSpot data",
    "created": "2024-01-15T10:00:00Z",
    "last_used": "2024-01-20T15:30:00Z",
    "usage_count": 15,
    "parameters": ["time_period", "customer_segment"],
    "tags": ["analytics", "customers", "stripe", "hubspot"],
    "examples": [
      "analyze customer churn",
      "check churn rate for enterprise",
      "analyze why customers are leaving"
    ]
  }
}
```

## Discovery Flow

1. **Parse Query**: Extract intent and potential parameters
2. **Search Workflows**: Find semantically similar workflows
3. **Rank Results**: Consider similarity, recency, usage frequency
4. **Extract Parameters**: Map query parameters to workflow parameters
5. **Present Options**: Show user the matches (if multiple)
6. **Execute or Create**: Run existing or build new

## User Experience

### Single Match
```bash
$ pflow "analyze customer churn for last month"
→ Found 'analyze-churn'. Running with period: last month
```

### Multiple Matches
```bash
$ pflow "check errors"
→ Found 3 similar workflows:
  1. production-error-monitor (last used: yesterday)
  2. test-error-analyzer (last used: last week)
  3. error-log-parser (last used: 2 weeks ago)
→ Which one? (1-3, or 'n' for new):
```

### No Match
```bash
$ pflow "analyze weather patterns"
→ No existing workflow found. Building one for you...
```

## Performance Considerations

1. **Index Workflows**: Keep an in-memory index for fast searching
2. **Cache Embeddings**: Pre-compute and cache embeddings
3. **Limit Scope**: Only search user's workflows (not global)
4. **Background Updates**: Update indices asynchronously

## Testing Strategy

1. **Semantic Tests**: Verify similar queries find same workflow
2. **Parameter Tests**: Ensure parameters extracted correctly
3. **Performance Tests**: Discovery must be <100ms
4. **Edge Cases**: Empty queries, typos, ambiguous matches

## Future Enhancements

1. **Learning**: Track which workflows users select to improve ranking
2. **Aliases**: Allow users to add alternative names/descriptions
3. **Global Sharing**: Discover workflows from team/community
4. **Fuzzy Matching**: Combine semantic + fuzzy string matching

## Remember

Discovery is as important as creation. A great discovery experience makes users feel like pflow understands them, building trust and encouraging use.
