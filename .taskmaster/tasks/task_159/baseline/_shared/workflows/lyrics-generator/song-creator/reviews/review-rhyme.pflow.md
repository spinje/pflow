# Review: Rhyme Scheme Verification

Structural reviewer that checks whether the lyrics honor the rhyme commitments declared in the song's architecture. Flags broken rhyme pairs and same-word "rhymes" (e.g., `ljud / ljud`) that the writer's self-audit tends to rationalize as valid.

This reviewer is mechanical — it reads the architecture's declared scheme, reads the actual line endings, and checks whether each declared rhyme pair actually rhymes. It does not judge whether a line is good, only whether it rhymes when the blueprint says it should.

Callable standalone or as a sub-workflow from the song-creator.

## Inputs

### lyrics

The lyrics to verify.

- type: string
- required: true

### song_architecture

The architecture's blueprint, including the Musical Structure section that declares the intended rhyme scheme per part of the song.

- type: string
- required: true

### creative_direction

Creative direction containing the Language line. Used to apply rhyme conventions appropriate to the target language.

- type: string
- required: false

## Steps

### review

Walks through each section of the lyrics, lists end-of-line words, verifies each declared rhyme pair against the architecture's scheme, and outputs structured per-section flags.

- type: llm
- temperature: 0.3
- reasoning_effort: none
- prompt: ../specialist-reviews-rhyme.prompt.md

## Outputs

### review_text

The rhyme verification report, organized per section with a summary of broken rhymes, same-word "rhymes," and clean sections.

- source: ${review.response}
