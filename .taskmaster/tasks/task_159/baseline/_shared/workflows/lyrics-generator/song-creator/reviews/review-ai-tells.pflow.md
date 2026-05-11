# Review: AI-Indicative Language

Specialist review scanning for words and patterns that betray AI authorship — fade, echo, neon, whisper-as-metaphor, abstract noun pairs, and other tells.

Callable standalone or as a sub-workflow from the song-creator.

## Inputs

### lyrics
The lyrics to review.
- type: string
- required: true

### creative_direction
Creative direction describing the narrator's persona and voice world. Used to identify the character's natural vocabulary before flagging phrases as AI-generic — an evangelical narrator's "standing in the gap" or a blue-collar narrator's "straight down the line" is voice-diagnostic, not AI decoration.
- type: string
- required: false

## Steps

### review

Runs the AI-indicative language review prompt against the provided lyrics.

- type: llm
- temperature: 0.3
- reasoning_effort: none
- prompt: ../specialist-reviews-ai-tells.prompt.md

## Outputs

### review_text

The AI-indicative language review text.

- source: ${review.response}
