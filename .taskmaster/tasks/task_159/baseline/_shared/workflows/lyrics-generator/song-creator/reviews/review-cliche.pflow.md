# Review: Cliches

Specialist review detecting stock phrases, dead metaphors, generic emotional declarations, and structural cliches.

Callable standalone or as a sub-workflow from the song-creator.

## Inputs

### lyrics
The lyrics to review.
- type: string
- required: true

### creative_direction
Creative direction describing the narrator's persona and voice world. Used to identify the character's natural vocabulary before flagging phrases as cliché — a phrase native to the character's real voice world is diagnostic of that character, not a dead trope.
- type: string
- required: false

## Steps

### review

Runs the cliche detection review prompt against the provided lyrics.

- type: llm
- temperature: 0.3
- reasoning_effort: none
- prompt: ../specialist-reviews-cliche.prompt.md

## Outputs

### review_text

The cliche detection review text.

- source: ${review.response}
