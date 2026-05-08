# Review: Imagery Quality

Specialist review checking imagery quality — concrete vs abstract, image coherence, image system fidelity, sensory range.

Callable standalone or as a sub-workflow from the song-creator.

## Inputs

### lyrics
The lyrics to review.
- type: string
- required: true

### song_architecture
Song architecture for reference on the planned image system.
- type: string
- required: true

## Steps

### review

Runs the imagery quality review prompt against the provided lyrics.

- type: llm
- temperature: 0.3
- reasoning_effort: none
- prompt: ../specialist-reviews-imagery.prompt.md

## Outputs

### review_text

The imagery quality review text.

- source: ${review.response}
