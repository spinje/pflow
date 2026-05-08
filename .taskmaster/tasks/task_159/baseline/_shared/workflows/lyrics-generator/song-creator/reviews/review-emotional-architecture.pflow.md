# Review: Emotional Architecture

Specialist review checking whether the song's Kill Moments land, The Unsaid is felt, the Narrator's Blind Spot creates dramatic irony, breathing room exists, and the emotional trajectory works.

Callable standalone or as a sub-workflow from the song-creator.

## Inputs

### lyrics
The lyrics to review.
- type: string
- required: true

### concept_brief
Material palette containing Kill Moments, The Unsaid, Blind Spot, and other creative targets.
- type: string
- required: true

### creative_direction
Creative direction decisions — who the narrator is, what they want, genre, voice.
- type: string
- required: true

## Steps

### review

Runs the emotional architecture review prompt against the provided lyrics.

- type: llm
- temperature: 0.3
- reasoning_effort: none
- prompt: ../specialist-reviews-emotional-architecture.prompt.md

## Outputs

### review_text

The emotional architecture review text.

- source: ${review.response}
