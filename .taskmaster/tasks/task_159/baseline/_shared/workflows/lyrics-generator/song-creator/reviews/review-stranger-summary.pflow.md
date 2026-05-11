# Review: Stranger Summary

Specialist review that reads ONLY the lyrics (no brief, no direction, no architecture) and tries to answer, as a stranger would: what is this song about, what happens, who are the characters, what is the conflict. Flags legibility failures the other reviews miss — a song can have strong imagery, clean craft, and zero AI tells and still leave a stranger unable to say what it's about.

Callable standalone or as a sub-workflow from the song-creator.

## Inputs

### lyrics
The lyrics to review. This is intentionally the ONLY input — the reviewer must judge legibility with zero context.
- type: string
- required: true

## Steps

### review

Runs the stranger-summary review prompt against the provided lyrics.

- type: llm
- temperature: 0.3
- reasoning_effort: none
- prompt: ../specialist-reviews-stranger-summary.prompt.md

## Outputs

### review_text

The stranger-summary review text, including legibility verdict.

- source: ${review.response}
