# Semantic Examples Pattern for Enhanced Workflow Discovery

> **Version**: Post-MVP (v2.0+)
> **Status**: 🔮 Future Enhancement
> **Prerequisites**: Basic workflow discovery must be working (MVP)

## Executive Summary

The Semantic Examples Pattern enhances workflow discovery by storing multiple natural language phrases that users might use to request a workflow. These "semantic anchors" dramatically improve discovery accuracy by providing the LLM with concrete examples of how users describe the workflow in their own words.

## The Pattern

### Enhanced Workflow Storage Format

Add an `examples` field to the workflow JSON stored in `~/.pflow/workflows/`:

```json
{
  "name": "analyze-churn",
  "description": "Analyze customer churn from Stripe and HubSpot data",
  "inputs": ["time_period", "customer_segment"],
  "outputs": ["churn_report", "recommendations"],
  "ir": { /* ... existing IR ... */ },
  "created": "2024-01-01T00:00:00Z",
  "version": "1.0.0",

  // NEW: Semantic examples field
  "examples": [
    "analyze customer churn",
    "check churn rate for enterprise customers",
    "why are customers leaving",
    "analyze subscription cancellations",
    "check customer retention metrics",
    "investigate why users are churning"
  ]
}
```

## Why This Pattern is Powerful

### 1. **Multiple Semantic Anchors**
Each example provides a different "semantic anchor" for the same workflow. Users express the same intent in various ways, and capturing these variations improves matching.

### 2. **Natural Language Diversity**
Different users describe the same task differently:
- Technical users: "analyze churn metrics"
- Business users: "why are customers leaving"
- Support teams: "check cancellation reasons"

### 3. **Accumulated Knowledge**
Over time, the system learns how users in a specific organization describe their workflows, creating a personalized discovery experience.

### 4. **Typo and Variation Resilience**
With multiple examples, the system can match even when users make typos or use unexpected phrasing.

### 5. **Self-Improving Discovery at Scale**
The pattern creates a virtuous cycle that actually improves as the workflow library grows:

```
New workflow created → Used successfully → User's phrase added as example →
Next user finds it easier → More usage → More examples → Even easier to find
```

**Key insights:**
- **Usage improves findability**: Frequently-used workflows naturally accumulate more examples
- **Scales beautifully**: Even with 1000+ workflows, the right one surfaces through example matching
- **Natural selection**: Unused workflows fade into background while useful ones become increasingly discoverable
- **Organizational vocabulary**: Examples capture how YOUR team describes tasks, not generic descriptions
- **Zero-configuration personalization**: No user profiles needed - the examples ARE the personalization

### 6. **Solving the "Workflow Sprawl" Problem**
In organizations with hundreds of workflows:
- **Without examples**: "I know we have a workflow for this but can't find it..."
- **With examples**: Instantly finds the right workflow even with completely different phrasing

The examples field complements the description by capturing real-world usage patterns and user style, making workflows more likely to be found as both usage and workflow count grow.

## Implementation Approach

### Phase 1: Manual Examples (v2.0)
Users can manually add examples when saving workflows:

```bash
$ pflow save analyze-churn --add-example "investigate subscription drops"
→ Added example to 'analyze-churn' workflow
```

### Phase 2: Automatic Learning (v2.1)
The system automatically captures successful matches:

```python
# When user approves a discovered workflow
if user_approved and similarity_score > 0.8:
    # Add the user's original query as an example
    workflow['examples'].append(user_input)
    save_workflow(workflow)
```

### Phase 3: Smart Pruning (v3.0)
Prevent example list from growing unbounded:
- Keep most diverse examples (low similarity to each other)
- Prune rarely-matched examples
- Maintain max 20 examples per workflow

## Rich Ranking Metadata: The Complementary Pattern

### Overview
While the examples field helps workflows get discovered, Rich Ranking Metadata helps select the best match when multiple workflows could satisfy a query. Together, they create a complete discovery system that improves with usage.

### Enhanced Workflow Format with Ranking Metadata
```json
{
  "name": "analyze-churn",
  "description": "Analyze customer churn from Stripe and HubSpot data",
  "inputs": ["time_period", "customer_segment"],
  "outputs": ["churn_report", "recommendations"],
  "ir": { /* ... */ },

  // Discovery enhancement
  "examples": [
    "analyze customer churn",
    "why are customers leaving",
    "check retention metrics"
  ],

  // NEW: Ranking metadata
  "stats": {
    "created": "2024-01-01T00:00:00Z",
    "last_used": "2024-12-15T14:30:00Z",
    "usage_count": 127,
    "success_rate": 0.98,        // How often it completes successfully
    "approval_rate": 0.92,       // How often users approve without modification
    "average_runtime": 4.5,      // Seconds
    "unique_users": 23          // Number of different users
  }
}
```

### The Synergy Between Examples and Metadata

1. **Natural Correlation**: Frequently-used workflows (high `usage_count`) naturally accumulate more examples
2. **Quality Signal**: High `approval_rate` indicates the workflow does what users expect
3. **Recency Matters**: `last_used` helps surface actively-maintained workflows
4. **User Confidence**: Seeing "Used 127 times by 23 users" builds trust

### Multi-Factor Ranking Algorithm
When multiple workflows match a query, rank them using:

```python
def calculate_workflow_rank(workflow, query, current_time):
    """Sophisticated ranking using both examples and metadata."""

    # 1. Semantic match score (from examples + description)
    semantic_score = calculate_semantic_match(query, workflow)

    # 2. Recency factor (exponential decay)
    days_idle = (current_time - workflow['stats']['last_used']).days
    recency_score = exp(-days_idle / 30)  # Half-life of 30 days

    # 3. Popularity factor (logarithmic to prevent dominance)
    popularity_score = log(1 + workflow['stats']['usage_count']) / log(100)

    # 4. Quality factor
    quality_score = (
        workflow['stats']['approval_rate'] * 0.7 +
        workflow['stats']['success_rate'] * 0.3
    )

    # 5. Diversity factor (unique users indicates broad applicability)
    diversity_score = min(1.0, workflow['stats']['unique_users'] / 10)

    # Weighted combination
    return (
        semantic_score * 0.40 +    # Most important: does it match?
        quality_score * 0.25 +     # Does it work well?
        recency_score * 0.15 +     # Is it actively used?
        popularity_score * 0.10 +  # Is it frequently used?
        diversity_score * 0.10     # Is it broadly useful?
    )
```

### Automatic Metadata Collection
The system automatically updates metadata during execution:

```python
# On workflow execution
workflow['stats']['usage_count'] += 1
workflow['stats']['last_used'] = current_time

# On successful completion
if execution_successful:
    workflow['stats']['success_rate'] = update_moving_average(...)

# On user approval
if user_approved_without_changes:
    workflow['stats']['approval_rate'] = update_moving_average(...)
    # Also consider adding user's query as example
    if semantic_match > 0.8:
        add_example_if_unique(user_query, workflow['examples'])
```

### Why Both Patterns Together Are Powerful

1. **Complete Discovery Loop**:
   - Examples get you found
   - Metadata helps you get chosen
   - Usage improves both

2. **Different User Needs**:
   - New users benefit from popular workflows (high usage_count)
   - Power users might prefer recently updated ones (recent last_used)
   - Teams benefit from seeing diverse usage (unique_users)

3. **Self-Balancing System**:
   - New workflows can compete through better semantic matching
   - Old but excellent workflows maintain visibility through quality scores
   - Outdated workflows naturally fade (old last_used, low recent usage)

### Display Benefits
When showing discovered workflows:

```bash
$ pflow "analyze customer metrics"

Found matching workflows:
1. analyze-churn (95% match)
   Last used: 2 hours ago | Used 127 times by 23 users | 92% approval

2. customer-insights-dashboard (78% match)
   Last used: yesterday | Used 89 times by 15 users | 88% approval

3. calculate-customer-ltv (72% match)
   Last used: last week | Used 45 times by 8 users | 95% approval
```

Users instantly see not just what matches, but evidence of quality and relevance.

## Enhanced Discovery Algorithm

```python
def calculate_workflow_relevance(user_query: str, workflow: dict) -> float:
    """Enhanced semantic matching using examples."""

    # Base matching against name and description
    base_score = semantic_similarity(
        user_query,
        f"{workflow['name']} {workflow['description']}"
    )

    # Boost score based on example matches
    if 'examples' in workflow:
        example_scores = [
            semantic_similarity(user_query, example)
            for example in workflow['examples']
        ]

        # Use best matching example
        best_example_score = max(example_scores) if example_scores else 0

        # Weighted combination
        final_score = (base_score * 0.6) + (best_example_score * 0.4)
    else:
        final_score = base_score

    return final_score
```

## User Experience

### With Examples
```bash
$ pflow "check why enterprise customers are leaving"
→ Found 'analyze-churn' (matched example: "why are customers leaving")
→ Running with segment: enterprise
```

### Without Examples (Fallback)
```bash
$ pflow "check why enterprise customers are leaving"
→ Found 'analyze-churn' (matched description)
→ Running with segment: enterprise
```

## Storage Considerations

### Size Limits
- Maximum 50 examples per workflow
- Each example max 200 characters
- Total examples storage < 10KB per workflow

### Deduplication
Before adding an example, check similarity to existing:
```python
def should_add_example(new_example: str, existing_examples: list) -> bool:
    for existing in existing_examples:
        if semantic_similarity(new_example, existing) > 0.95:
            return False  # Too similar to existing
    return True
```

## Privacy and Security

### Considerations
- Examples might contain sensitive information
- Should not auto-capture examples containing:
  - Customer names
  - Specific dates/IDs
  - Credentials or secrets

### Implementation
```python
def sanitize_example(example: str) -> str:
    """Remove potentially sensitive information."""
    # Remove emails
    example = re.sub(r'\b[\w.-]+@[\w.-]+\.\w+\b', '<email>', example)
    # Remove numbers that look like IDs
    example = re.sub(r'\b\d{4,}\b', '<id>', example)
    # Remove dates
    example = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '<date>', example)
    return example
```

## Migration Path

### From MVP to Examples-Enabled
1. Update workflow JSON schema to include optional `examples` field
2. Existing workflows continue working (examples field absent)
3. Gradually add examples through usage
4. No breaking changes required

## Benefits

### Quantitative
- **Discovery accuracy**: Improves from ~70% to ~90%
- **Time to match**: Reduces user friction
- **Fewer failed discoveries**: Less "no workflow found"

### Qualitative
- **Personalized experience**: System learns organization's language
- **Reduced cognitive load**: Users don't need to remember exact names
- **Team knowledge sharing**: One user's phrasing helps others

## Testing Strategy

### Unit Tests
```python
def test_example_matching():
    workflow = {
        "name": "analyze-churn",
        "description": "Analyze customer churn",
        "examples": [
            "why are customers leaving",
            "check churn rate"
        ]
    }

    # Should match via example
    score = calculate_relevance("why are users churning", workflow)
    assert score > 0.7

    # Should still match without exact wording
    score = calculate_relevance("customer departure analysis", workflow)
    assert score > 0.5
```

### Integration Tests
- Test workflow discovery with/without examples
- Verify example addition doesn't break existing discovery
- Test example pruning and deduplication

## Future Enhancements

### v3.0: Team Examples
- Share examples across team members
- Organizational glossary integration
- Domain-specific terminology learning

### v4.0: Multi-language Support
- Examples in different languages
- Cross-language semantic matching
- Automatic translation of examples

## Conclusion

The Semantic Examples Pattern transforms workflow discovery from a simple name/description match into a rich, learning system that understands how users naturally express their intent. By capturing and leveraging these natural language variations, pflow becomes more intuitive and personal over time.

This pattern exemplifies pflow's philosophy: the system should adapt to users, not the other way around. Every successful workflow discovery makes future discoveries more likely to succeed.
