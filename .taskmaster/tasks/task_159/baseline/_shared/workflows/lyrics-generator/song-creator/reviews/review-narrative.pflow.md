# Review: Narrative Arc

Specialist review checking whether the narrative arc holds — does each section accomplish its job, does the story progress, does the emotional journey work?

Callable standalone or as a sub-workflow from the song-creator.

## Inputs

### lyrics
The lyrics to review.
- type: string
- required: true

### song_architecture
The intended narrative arc and structural blueprint to verify against.
- type: string
- required: true

## Steps

### review

Runs the narrative arc review prompt against the provided lyrics.

- type: llm
- temperature: 0.3
- reasoning_effort: none
- prompt: ../specialist-reviews-narrative.prompt.md

## Outputs

### review_text

The narrative arc review text.

- source: ${review.response}
