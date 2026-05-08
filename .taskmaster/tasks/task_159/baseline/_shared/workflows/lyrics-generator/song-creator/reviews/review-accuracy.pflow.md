# Review: Factual & Linguistic Accuracy

Specialist reviewer that audits the lyrics against external reality. Catches factual errors in real-world references, invented or non-standard words, grammatical errors, and cross-reference inconsistencies between lines. Especially important for non-English output where lexical and cultural accuracy matter most.

This reviewer does NOT judge craft or aesthetics. It checks whether claims in the song are accurate to the world being referenced and whether every word is valid in the target language.

Callable standalone or as a sub-workflow from the song-creator.

## Inputs

### lyrics

The lyrics to audit.

- type: string
- required: true

### creative_direction

Creative direction describing the narrator's persona, setting, and language. Used to determine which language to check lexical/grammatical accuracy against and what real-world context the lyrics are committing to.

- type: string
- required: false

### concept_brief

Per-concept material palette. May contain a "Factual Constraints" section listing real-world specifics the song commits to — these are the anchors against which the lyrics' factual claims should be verified.

- type: string
- required: false

## Steps

### review

Runs the accuracy review prompt against the lyrics, producing categorized flags for factual errors, lexical issues, grammatical errors, and cross-reference inconsistencies.

- type: llm
- temperature: 0.3
- reasoning_effort: none
- prompt: ../specialist-reviews-accuracy.prompt.md

## Outputs

### review_text

The accuracy review text, organized by category.

- source: ${review.response}
