# 03 — analyze-cache on song-creator sub-workflow (text)

**Surface**: 12-real-world-lyrics-generator

**Triggers**: Runs analyze-cache directly on the song-creator sub-workflow
which is where the `## Cache` block actually lives (5 chunks: concept,
concept_brief, creative-direction.response, song-architecture.response,
easter-eggs.response). 14 LLM nodes; cache subset declarations from
`[concept, concept_brief]` (creative-direction) up to all-5 (write-lyrics
+ generate-suno-prompt).

**Expected**: text report showing the 5-chunk `## Cache` block, cache
subsets per node, padding advisories where a node could pad its subset to
hit upstream cache writes (e.g. review-narrative could extend
`[song-architecture.response]` to `[concept, creative-direction.response,
song-architecture.response]` per the spec example).

**Why this complements case 01**: case 01 walks the parent and surfaces
sub-workflow boundaries; this case walks song-creator standalone and
exercises the in-file `## Cache` block + per-node prompt_cache subset
attribution. Different code paths in the analyzer (per-workflow vs
walk-down).

**Mutation contract**: regression in `cache.padding-advisory` emission or
in per-node prompt_cache subset rendering will visibly shift this output.
