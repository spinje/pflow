# Review: Genre Authenticity

Specialist review checking whether the lyrics feel authentic to the intended genre — vocabulary, rhythmic feel, musical structure, and overall vibe.

Callable standalone or as a sub-workflow from the song-creator.

## Inputs

### lyrics
The lyrics to review.
- type: string
- required: true

### creative_direction
Intended genre and creative direction.
- type: string
- required: true

### song_architecture
Song architecture for reference on musical structure targets.
- type: string
- required: true

## Steps

### review

Runs the genre authenticity review prompt against the provided lyrics.

- type: llm
- temperature: 0.3
- reasoning_effort: none
- prompt: ../specialist-reviews-genre.prompt.md

## Outputs

### review_text

The genre authenticity review text.

- source: ${review.response}
