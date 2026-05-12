# Inputs Indirection Batch

Regression fixture for cache analysis seeing through LLM `inputs:` aliases in
batch prompts.

## Steps

### score

Scores each concept against a stable rubric.

- type: llm
- model: anthropic/claude-haiku-4-5
- inputs:
    concept_md: ${item.concept_md}
- batch:
    items:
      - concept_md: Alpha concept
      - concept_md: Beta concept
      - concept_md: Gamma concept
    as: item

```prompt
Shared rubric stable criterion one stable criterion two stable criterion three stable criterion four stable criterion five.

Evaluate this concept:
${concept_md}
```
