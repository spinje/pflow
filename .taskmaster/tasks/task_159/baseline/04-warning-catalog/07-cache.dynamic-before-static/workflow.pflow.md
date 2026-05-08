# Dynamic Before Static

## Inputs

### dynamic

Dynamic short value.

- type: string
- required: true

## Steps

### scoring

Score with dynamic-first prompt.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Item to score: ${dynamic}

# Scoring rubric — long stable text (must exceed sonnet's 1024-token min)

Use the rubric below to score the item. Each criterion is weighted as noted.
Apply each criterion independently, then combine via the formula at the end.

Criterion 1 — clarity: how clearly the item expresses its central idea. Weight 0.15.
A maximally clear item has a single, well-stated thesis; supporting points
that obviously flow from the thesis; no ambiguous pronouns; no buried
qualifications; and a tone that matches its purpose. Score 1 to 10.

Criterion 2 — relevance: how well the item addresses the topic at hand.
Off-topic excursions, even if interesting, reduce relevance. Score 1 to 10.
Weight 0.15.

Criterion 3 — depth: how thoroughly the item explores its subject matter.
A deep treatment surfaces non-obvious connections, considers second-order
effects, names tradeoffs, and engages with counterarguments. Score 1 to 10.
Weight 0.20.

Criterion 4 — originality: how much the item contributes that is novel
relative to common framings of the topic. Reward original synthesis even
when individual elements are familiar. Score 1 to 10. Weight 0.10.

Criterion 5 — practical applicability: whether a reader can act on the item.
Items that produce concrete next-step actions, decision frameworks, or
checklists score higher than purely descriptive items. Score 1 to 10.
Weight 0.10.

Criterion 6 — emotional resonance: whether the item lands with its intended
audience emotionally as well as intellectually. Cold expertise scores
lower than warm expertise. Score 1 to 10. Weight 0.05.

Criterion 7 — structure: whether the item has a logical flow that makes
its argument easy to follow. Score 1 to 10. Weight 0.10.

Criterion 8 — accuracy: whether the item's factual claims are correct,
or where uncertainty exists, are appropriately hedged. Score 1 to 10.
Weight 0.10.

Criterion 9 — tone: whether the item's voice is consistent throughout
and appropriate for its audience. Score 1 to 10. Weight 0.025.

Criterion 10 — craft: the overall polish of the final form, including
typography, formatting, and visual presentation where applicable. Score
1 to 10. Weight 0.025.

Combine: total = sum(weight * score) across criteria. Round to one decimal.
Output a single line: SCORE=<x.x> with a one-sentence justification.
```

## Outputs

### score

Score.

- source: ${scoring.response}
- type: string
