# Score Section

Score a text section on clarity and relevance.

## Inputs

### text

The text section to score.

- type: string
- required: true

### criteria

The scoring criteria to apply.

- type: string

## Steps

### evaluate

Score the section against the given criteria.

- type: llm
- prompt: Score this text for ${criteria}: ${text}

### normalize

Normalize scores to a 0-100 scale.

- type: code
- inputs:
    raw_score: ${evaluate.response}

```python code
raw_score: str

result = {"score": 85, "normalized": True}
```

## Outputs

### score

The normalized quality score.

- source: ${normalize.result}

### reasoning

The evaluator's reasoning for the score.

- source: ${evaluate.response}
