# Batch Prewarm Recommended

## Inputs

### items

Items to score.

- type: array
- required: true

## Steps

### scoring

Batch scoring with a long static prefix that comes before ${item.X}.

- type: llm
- model: anthropic/claude-sonnet-4-5

```yaml batch
items: ${items}
parallel: true
```

```prompt
You are a quality scorer. Use the following extensive rubric to score each
candidate item. The rubric is identical for every call, which is exactly the
shape that benefits from prewarmed cache.

Criterion 1 — clarity. Criterion 2 — relevance. Criterion 3 — depth.
Criterion 4 — originality. Criterion 5 — practical utility. Criterion 6 —
emotional resonance. Criterion 7 — structural integrity. Criterion 8 —
factual accuracy. Criterion 9 — tonal consistency. Criterion 10 — craft.

Weighting: clarity 0.15, relevance 0.15, depth 0.20, originality 0.10,
practical 0.10, emotional 0.05, structural 0.10, accuracy 0.10, tonal 0.025,
craft 0.025.

This rubric is long enough to dominate the prompt and benefit from caching:
each batch call would otherwise re-send these instructions verbatim, and
prewarm would let calls 2..N read the cache instead of writing it.

Now score the candidate item below, returning only SCORE=<x.x> on a single
line with a one-sentence justification.

CANDIDATE: ${item.text}
```

## Outputs

### scores

Scores.

- source: ${scoring}
- type: array
